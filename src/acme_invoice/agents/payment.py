"""Payment agent — execute mock payment or log rejection.

Payment runs only when validation passed AND approval is APPROVED.
All other paths log a structured skip/rejection (never calls the bank mock).
"""

from __future__ import annotations

from acme_invoice.models import Decision
from acme_invoice.observability import log_event, stage_timer
from acme_invoice.state import InvoiceState
from acme_invoice.tools.payment import process_payment, skip_payment


def payment_agent(state: InvoiceState) -> InvoiceState:
    invoice = state.get("extracted")
    approval = state.get("approval")
    with stage_timer("payment") as stage:
        # Dual gate: inventory/data integrity + VP decision
        if (
            approval
            and approval.decision == Decision.APPROVED
            and invoice is not None
            and state.get("validation")
            and state["validation"].passed
        ):
            payment = process_payment(invoice.vendor, invoice.amount)
            stage.message = payment.message
            stage.details = payment.model_dump()
            return {
                "payment": payment,
                "final_status": Decision.APPROVED,
                "stages": [stage],
            }

        reason_parts = []
        if state.get("validation") and not state["validation"].passed:
            hard = "; ".join(i.message for i in state["validation"].hard_issues)
            reason_parts.append(f"Validation failed: {hard}")
        if approval and approval.decision == Decision.REJECTED:
            reason_parts.append(f"Approval rejected: {approval.rationale}")
        if state.get("error"):
            reason_parts.append(state["error"])
        reason = " | ".join(reason_parts) or "Invoice not approved for payment"

        payment = skip_payment(
            reason,
            vendor=invoice.vendor if invoice else "",
            amount=invoice.amount if invoice else 0.0,
        )
        log_event(
            "invoice_rejected",
            invoice_path=state.get("invoice_path"),
            reason=reason,
            approval=approval.model_dump() if approval else None,
        )
        stage.message = reason
        stage.details = payment.model_dump()
        return {
            "payment": payment,
            "final_status": Decision.REJECTED,
            "stages": [stage],
        }


def reject_agent(state: InvoiceState) -> InvoiceState:
    """Terminal rejection path (validation hard-fail or approval reject)."""
    return payment_agent(state)
