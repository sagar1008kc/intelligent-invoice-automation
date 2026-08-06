"""Approval agent — VP persona with rule priors and critique loop.

1. Build deterministic priors (amount threshold, hard/soft issues).
2. Ask Grok (or heuristic) for APPROVED/REJECTED + rationale.
3. For elevated-risk approvals, run one critique pass that may overturn to REJECTED.
"""

from __future__ import annotations

import json

from acme_invoice.config import get_settings
from acme_invoice.llm import (
    LLMClient,
    approval_from_llm_payload,
    extract_json_object,
    get_llm_client,
)
from acme_invoice.models import ApprovalResult, Decision
from acme_invoice.observability import stage_timer
from acme_invoice.state import InvoiceState

APPROVAL_SYSTEM = """You are the VP of Finance at Acme Corp reviewing an AP invoice.
Make a clear APPROVED or REJECTED decision.

Return ONLY JSON:
{
  "decision": "APPROVED" | "REJECTED",
  "rationale": string,
  "risk_score": number,
  "requires_scrutiny": boolean
}

Policy priors:
- Reject if hard validation failures exist.
- Invoices over $10,000 require elevated scrutiny; approve only with strong justification.
- Reject blocked/fraudulent vendors, FakeItem, urgency/wire-pressure language, or clear fraud signals.
- Prefer REJECTED when uncertainty is high — false payments are costly.
"""

CRITIQUE_SYSTEM = """You are an internal audit critic reviewing a VP approval decision.
Challenge weak approvals. Confirm solid decisions.

Return ONLY JSON with the same schema as approval, plus optional "critique" string.
If the original approval is unjustified, overturn to REJECTED.
"""


def _rule_priors(state: InvoiceState) -> dict:
    settings = get_settings()
    invoice = state["extracted"]
    validation = state.get("validation")
    soft = [i.model_dump() for i in (validation.soft_issues if validation else [])]
    hard = [i.model_dump() for i in (validation.hard_issues if validation else [])]
    amount = invoice.amount if invoice else 0
    return {
        "amount": amount,
        "over_threshold": amount > settings.approval_amount_threshold,
        "threshold": settings.approval_amount_threshold,
        "hard_issues": hard,
        "soft_issues": soft,
        "vendor": invoice.vendor if invoice else "",
        "invoice_number": invoice.invoice_number if invoice else "",
        "items": [i.model_dump() for i in (invoice.items if invoice else [])],
        "currency": invoice.currency if invoice else "USD",
        "due_date": invoice.due_date if invoice else None,
        "anomalies": invoice.anomalies if invoice else [],
    }


def approval_agent(state: InvoiceState, llm: LLMClient | None = None) -> InvoiceState:
    client = llm or get_llm_client()
    with stage_timer("approval") as stage:
        priors = _rule_priors(state)

        # Hard short-circuit (should usually be routed away already)
        if priors["hard_issues"]:
            result = ApprovalResult(
                decision=Decision.REJECTED,
                rationale="Rejected due to hard validation failures.",
                risk_score=0.95,
                requires_scrutiny=True,
            )
            stage.message = "Auto-rejected on hard validation failures"
            stage.details = result.model_dump()
            return {
                "approval": result,
                "final_status": Decision.REJECTED,
                "stages": [stage],
            }

        user = (
            "Review this invoice package and decide.\n"
            + json.dumps(priors, indent=2)
        )
        try:
            payload = extract_json_object(client.complete(APPROVAL_SYSTEM, user))
            result = approval_from_llm_payload(payload)
        except Exception as exc:  # noqa: BLE001
            # Conservative fallback
            if priors["over_threshold"] or priors["soft_issues"]:
                result = ApprovalResult(
                    decision=Decision.REJECTED,
                    rationale=f"Approval LLM failed ({exc}); conservative reject.",
                    risk_score=0.8,
                    requires_scrutiny=True,
                )
            else:
                result = ApprovalResult(
                    decision=Decision.APPROVED,
                    rationale=f"Approval LLM failed ({exc}); low-risk invoice auto-approved.",
                    risk_score=0.35,
                    requires_scrutiny=False,
                )

        # Deterministic override: never approve with soft fraud-critical codes alone? 
        # Keep LLM decision but force reject for extreme amounts without scrutiny pass.
        if result.decision == Decision.APPROVED and priors["amount"] >= 100000:
            result = ApprovalResult(
                decision=Decision.REJECTED,
                rationale="Extreme amount auto-rejected pending board-level review.",
                risk_score=0.99,
                requires_scrutiny=True,
                reflections=result.reflections,
            )

        stage.message = f"VP decision: {result.decision.value}"
        stage.details = result.model_dump()
        return {
            "approval": result,
            "final_status": result.decision,
            "stages": [stage],
            "critique_done": False,
        }


def critique_agent(state: InvoiceState, llm: LLMClient | None = None) -> InvoiceState:
    client = llm or get_llm_client()
    prior = state.get("approval")
    if prior is None:
        return {"critique_done": True}

    with stage_timer("approval_critique") as stage:
        priors = _rule_priors(state)
        user = (
            "Challenge the following VP decision if weak:\n"
            + json.dumps(
                {
                    "prior_decision": prior.model_dump(),
                    "invoice_context": priors,
                },
                indent=2,
            )
        )
        try:
            payload = extract_json_object(client.complete(CRITIQUE_SYSTEM, user))
            critiqued = approval_from_llm_payload(payload)
            reflections = list(prior.reflections) + [
                critiqued.critique or critiqued.rationale
            ]
            critiqued.reflections = reflections
            # Only allow critique to overturn APPROVED -> REJECTED (safer), not the reverse
            if prior.decision == Decision.APPROVED and critiqued.decision == Decision.REJECTED:
                result = critiqued
            else:
                result = ApprovalResult(
                    decision=prior.decision,
                    rationale=prior.rationale,
                    risk_score=max(prior.risk_score, critiqued.risk_score),
                    requires_scrutiny=prior.requires_scrutiny or critiqued.requires_scrutiny,
                    critique=critiqued.critique,
                    reflections=reflections,
                )
        except Exception as exc:  # noqa: BLE001
            result = prior
            result.reflections = list(prior.reflections) + [f"Critique skipped: {exc}"]

        stage.message = f"Critique complete; decision={result.decision.value}"
        stage.details = result.model_dump()
        return {
            "approval": result,
            "final_status": result.decision,
            "critique_done": True,
            "stages": [stage],
        }


def should_critique(state: InvoiceState) -> str:
    settings = get_settings()
    approval = state.get("approval")
    if state.get("critique_done"):
        return "done"
    if approval is None:
        return "done"
    invoice = state.get("extracted")
    amount = invoice.amount if invoice else 0
    validation = state.get("validation")
    soft = bool(validation and validation.soft_issues)
    if approval.decision == Decision.APPROVED and (
        amount > settings.approval_amount_threshold or soft or approval.requires_scrutiny
    ):
        return "critique"
    return "done"


def route_after_approval(state: InvoiceState) -> str:
    approval = state.get("approval")
    if approval and approval.decision == Decision.APPROVED:
        return "pay"
    return "reject"
