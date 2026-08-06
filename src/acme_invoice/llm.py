"""Grok / ChatXAI helpers with injectable fakes for tests."""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol

from acme_invoice.config import get_settings
from acme_invoice.models import ApprovalResult, Decision, ExtractedInvoice, LineItem
from acme_invoice.observability import logger
from acme_invoice.tools.parsers.normalize import normalize_item_name, parse_money, parse_quantity


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class GrokClient:
    """Thin wrapper around langchain-xai ChatXAI (or OpenAI-compatible fallback)."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.xai_model
        self.api_key = api_key if api_key is not None else settings.xai_api_key
        self._chat = None

    def _get_chat(self) -> Any:
        if self._chat is not None:
            return self._chat
        if not self.api_key:
            raise RuntimeError(
                "XAI_API_KEY is not set. Add it to .env or export it in your shell."
            )
        try:
            from langchain_xai import ChatXAI

            self._chat = ChatXAI(
                model=self.model,
                api_key=self.api_key,
                temperature=0,
            )
            return self._chat
        except Exception as exc:  # noqa: BLE001
            logger.warning("langchain-xai unavailable (%s); falling back to OpenAI SDK", exc)
            from openai import OpenAI

            self._chat = OpenAI(api_key=self.api_key, base_url="https://api.x.ai/v1")
            return self._chat

    def complete(self, system: str, user: str) -> str:
        chat = self._get_chat()
        # ChatXAI path
        if hasattr(chat, "invoke"):
            from langchain_core.messages import HumanMessage, SystemMessage

            response = chat.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
            content = response.content
            if isinstance(content, list):
                return "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            return str(content)

        # OpenAI-compatible path
        response = chat.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""


class HeuristicLLMClient:
    """Deterministic offline stand-in for CI, demos without credits, and API outages.

    Not a substitute for Grok in production scoring — keeps the pipeline runnable offline.
    """

    def complete(self, system: str, user: str) -> str:
        if "Extract structured invoice data" in system or "invoice extraction" in system.lower():
            return self._extract(user)
        if "VP of Finance" in system or "approval decision" in system.lower():
            return self._approve(user)
        if "critique" in system.lower() or "Challenge the following" in user:
            return self._critique(user)
        return "{}"

    def _extract(self, user: str) -> str:
        # Pull invoice text after marker if present
        text = user
        if "INVOICE TEXT:" in user:
            text = user.split("INVOICE TEXT:", 1)[1]

        vendor = (
            _match(r"(?:^|\n)\s*Vendor:\s*(.+)", text)
            or _match(r"(?:Vndr|FROM:)\s*:?\s*(.+)", text)
            or ""
        )
        vendor = vendor.split("\n")[0].strip().strip('"')
        # Skip email addresses mistakenly captured as vendor
        if "@" in vendor and "Vendor:" in text:
            vendor = _match(r"Vendor:\s*(.+)", text) or vendor
            vendor = vendor.split("\n")[0].strip()
        inv = _match(r"(?:Invoice Number|Inv #|INV NO:|Invoice:|INVOICE #)\s*:?\s*(INV[-\s]?\d+|\d+)", text)
        if inv and not inv.upper().startswith("INV"):
            inv = f"INV-{inv}"
        if inv:
            inv = inv.replace(" ", "").upper()
            if not inv.startswith("INV-") and inv.startswith("INV"):
                inv = "INV-" + inv[3:]

        amount = parse_money(
            _match(
                r"(?:Total Amount|Grand Total|TOTAL|Amt|Total:)\s*:?\s*\$?([\d,]+(?:\.\d+)?)",
                text,
            )
        )
        # Prefer last TOTAL-like match over SUBTOTAL
        total_matches = re.findall(
            r"(?i)(?:Total Amount|Grand Total|(?<!Sub)Total|Amt)\s*:?\s*\$?([\d,]+(?:\.\d+)?)",
            text,
        )
        if total_matches:
            amount = parse_money(total_matches[-1])

        due = _match(r"(?:Due Date|Due Dt|Due:|DUE:)\s*:?\s*(.+)", text)
        if due:
            due = due.split("\n")[0].strip()

        notes = _match(r"(?:Notes|NOTES):\s*(.+)", text)
        anomalies: list[str] = []
        raw_notes = notes
        if re.search(r"urgent|wire transfer|pay immediately", text, re.I):
            anomalies.append("urgency_language")
            raw_notes = (raw_notes or "") + " " + "URGENT payment language detected"

        items = []
        for line in text.splitlines():
            m = re.search(
                r"(WidgetA|WidgetB|WidgetC|GadgetX|FakeItem|SuperGizmo|MegaSprocket|Widget A|Widget B|Gadget X)"
                r".{0,40}?(?:qty[:\s]*|x\s*|×\s*)?(\d+)",
                line,
                re.I,
            )
            if not m:
                # Pattern: "- SuperGizmo       x12     $400.00 each"
                m = re.search(
                    r"(SuperGizmo|MegaSprocket|WidgetA|WidgetB|GadgetX|FakeItem).{0,20}?[xX×]\s*(\d+)",
                    line,
                    re.I,
                )
            if not m:
                continue
            price_m = re.search(r"\$?\s*([\d,]+\.\d{2})", line)
            items.append(
                {
                    "name": normalize_item_name(m.group(1)),
                    "quantity": float(m.group(2)),
                    "unit_price": parse_money(price_m.group(1)) if price_m else None,
                }
            )

        confidence = 0.75 if vendor and items else 0.4
        payload = {
            "vendor": vendor,
            "invoice_number": inv or "",
            "due_date": due,
            "amount": amount or 0,
            "currency": "USD",
            "items": items,
            "confidence": confidence,
            "anomalies": anomalies,
            "raw_notes": raw_notes,
        }
        return json.dumps(payload)

    def _approve(self, user: str) -> str:
        amount = parse_money(_match(r'"amount":\s*([0-9.]+)', user) or _match(r"Amount:\s*\$?([0-9,.]+)", user)) or 0
        hard = "hard_issues\": []" not in user and "hard_issues" in user
        # crude: if hard_issues list non-empty in JSON blob
        if re.search(r'"hard_issues"\s*:\s*\[[^\]]+', user):
            hard = True
        if 'hard_issues": []' in user or '"hard_issues":[]' in user:
            hard = False

        soft_fraud = any(
            token in user.lower()
            for token in ["fraudster", "fakeitem", "urgency", "blocked_vendor", "suspicious"]
        )
        if hard or soft_fraud or amount >= 100000:
            decision = "REJECTED"
            rationale = "Rejected due to validation failures and/or elevated fraud risk."
            risk = 0.9
        elif amount > 10000:
            decision = "REJECTED"
            rationale = "High-value invoice requires additional scrutiny; rejecting pending manual review in prototype."
            risk = 0.7
        else:
            decision = "APPROVED"
            rationale = "Within policy thresholds; inventory checks passed; approving for payment."
            risk = 0.2
        return json.dumps(
            {
                "decision": decision,
                "rationale": rationale,
                "risk_score": risk,
                "requires_scrutiny": amount > 10000 or soft_fraud,
            }
        )

    def _critique(self, user: str) -> str:
        if "APPROVED" in user and ("10000" in user or "risk" in user.lower()):
            return json.dumps(
                {
                    "decision": "REJECTED",
                    "rationale": "Critique overturned weak approval on high-risk invoice.",
                    "risk_score": 0.85,
                    "requires_scrutiny": True,
                    "critique": "Approval rationale insufficient for elevated risk.",
                }
            )
        # Keep original decision encoded in user if present
        decision = _match(r'"decision":\s*"(APPROVED|REJECTED)"', user) or "APPROVED"
        return json.dumps(
            {
                "decision": decision,
                "rationale": "Critique confirms prior decision.",
                "risk_score": 0.3,
                "requires_scrutiny": False,
                "critique": "No material issues found in reflection pass.",
            }
        )


class ResilientLLMClient:
    """Prefer Grok; fall back to heuristic on credit/auth/network failures."""

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self.primary = primary
        self.fallback = fallback
        self._use_fallback = False

    def complete(self, system: str, user: str) -> str:
        if self._use_fallback:
            return self.fallback.complete(system, user)
        try:
            return self.primary.complete(system, user)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            transient = any(
                token in msg
                for token in (
                    "403",
                    "401",
                    "permission-denied",
                    "credits",
                    "license",
                    "rate limit",
                    "timeout",
                    "connection",
                    "api key",
                )
            )
            if not transient:
                raise
            logger.warning(
                "Grok API unavailable (%s); falling back to HeuristicLLMClient",
                exc,
            )
            self._use_fallback = True
            return self.fallback.complete(system, user)


def get_llm_client(*, force_heuristic: bool = False) -> LLMClient:
    settings = get_settings()
    if force_heuristic or not settings.has_api_key:
        logger.info("Using HeuristicLLMClient (no live Grok API key)")
        return HeuristicLLMClient()
    return ResilientLLMClient(GrokClient(), HeuristicLLMClient())


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group())


def invoice_from_llm_payload(payload: dict[str, Any]) -> ExtractedInvoice:
    items: list[LineItem] = []
    for row in payload.get("items") or []:
        name = normalize_item_name(str(row.get("name") or row.get("item") or ""))
        if not name:
            continue
        qty = parse_quantity(row.get("quantity"))
        items.append(
            LineItem(
                name=name,
                quantity=qty if qty is not None else 0,
                unit_price=parse_money(row.get("unit_price")),
                line_total=parse_money(row.get("line_total")),
            )
        )
    return ExtractedInvoice(
        vendor=str(payload.get("vendor") or "").strip(),
        invoice_number=str(payload.get("invoice_number") or "").strip(),
        invoice_date=payload.get("invoice_date"),
        due_date=payload.get("due_date"),
        amount=parse_money(payload.get("amount")) or 0.0,
        currency=str(payload.get("currency") or "USD"),
        items=items,
        payment_terms=payload.get("payment_terms"),
        confidence=float(payload.get("confidence") or 0.5),
        anomalies=list(payload.get("anomalies") or []),
        raw_notes=payload.get("raw_notes"),
    )


def approval_from_llm_payload(payload: dict[str, Any]) -> ApprovalResult:
    decision_raw = str(payload.get("decision") or "PENDING").upper()
    try:
        decision = Decision(decision_raw)
    except ValueError:
        decision = Decision.REJECTED
    try:
        risk = float(payload.get("risk_score") or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    # Normalize — models sometimes return 0–100 or values slightly > 1.
    if risk > 100.0:
        risk = 1.0
    elif risk >= 2.0:
        risk = risk / 100.0  # e.g. 80 → 0.80
    elif risk > 1.0:
        risk = 1.0  # slight overshoot (e.g. 1.2)
    risk = max(0.0, min(1.0, risk))
    return ApprovalResult(
        decision=decision,
        rationale=str(payload.get("rationale") or ""),
        risk_score=risk,
        requires_scrutiny=bool(payload.get("requires_scrutiny")),
        critique=payload.get("critique"),
    )


def _match(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None
