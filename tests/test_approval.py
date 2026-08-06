from __future__ import annotations

from acme_invoice.agents.approval import approval_agent, critique_agent, should_critique
from acme_invoice.models import (
    Decision,
    ExtractedInvoice,
    IssueSeverity,
    LineItem,
    ValidationIssue,
    ValidationResult,
)


def _state(amount: float, soft=None, hard=None):
    return {
        "extracted": ExtractedInvoice(
            vendor="Widgets Inc.",
            invoice_number="INV-TEST",
            amount=amount,
            items=[LineItem(name="WidgetA", quantity=1, unit_price=250)],
        ),
        "validation": ValidationResult(
            passed=not hard,
            issues=(hard or []) + (soft or []),
        ),
        "critique_done": False,
    }


def test_low_value_approved(heuristic_llm):
    state = _state(5000)
    out = approval_agent(state, llm=heuristic_llm)
    assert out["approval"].decision == Decision.APPROVED


def test_high_value_rejected_by_heuristic(heuristic_llm):
    state = _state(15000)
    out = approval_agent(state, llm=heuristic_llm)
    assert out["approval"].decision == Decision.REJECTED
    assert out["approval"].requires_scrutiny is True


def test_hard_issues_short_circuit(heuristic_llm):
    hard = [
        ValidationIssue(
            code="stock_mismatch",
            message="too many",
            severity=IssueSeverity.HARD,
        )
    ]
    state = _state(100, hard=hard)
    out = approval_agent(state, llm=heuristic_llm)
    assert out["approval"].decision == Decision.REJECTED


def test_critique_triggered_for_soft_flags(heuristic_llm):
    soft = [
        ValidationIssue(
            code="price_anomaly",
            message="price drift",
            severity=IssueSeverity.SOFT,
        )
    ]
    state = _state(5000, soft=soft)
    out = approval_agent(state, llm=heuristic_llm)
    state.update(out)
    assert should_critique(state) == "critique"
    crit = critique_agent(state, llm=heuristic_llm)
    assert crit["critique_done"] is True


def test_approval_risk_score_normalized():
    from acme_invoice.llm import approval_from_llm_payload

    percent = approval_from_llm_payload(
        {"decision": "APPROVED", "rationale": "ok", "risk_score": 80}
    )
    assert abs(percent.risk_score - 0.8) < 1e-9

    overshoot = approval_from_llm_payload(
        {"decision": "REJECTED", "rationale": "x", "risk_score": 1.5}
    )
    assert overshoot.risk_score == 1.0
    assert overshoot.decision == Decision.REJECTED
