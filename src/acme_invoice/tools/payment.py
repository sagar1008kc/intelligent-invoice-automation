"""Mock payment API for approved invoices."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from acme_invoice.models import PaymentResult
from acme_invoice.observability import log_event


def mock_payment(vendor: str, amount: float) -> dict[str, Any]:
    """Simulate a banking API payment call."""
    print(f"Paid {amount} to {vendor}")
    result = {
        "status": "success",
        "vendor": vendor,
        "amount": amount,
        "transaction_id": f"TXN-{uuid.uuid4().hex[:12].upper()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    log_event("payment_executed", **result)
    return result


def process_payment(vendor: str, amount: float) -> PaymentResult:
    raw = mock_payment(vendor, amount)
    return PaymentResult(
        status=raw["status"],
        vendor=vendor,
        amount=amount,
        transaction_id=raw.get("transaction_id"),
        timestamp=raw.get("timestamp"),
        message=f"Paid {amount:,.2f} to {vendor}",
    )


def skip_payment(reason: str, vendor: str = "", amount: float = 0.0) -> PaymentResult:
    log_event("payment_skipped", reason=reason, vendor=vendor, amount=amount)
    return PaymentResult(
        status="skipped",
        vendor=vendor,
        amount=amount,
        message=reason,
    )
