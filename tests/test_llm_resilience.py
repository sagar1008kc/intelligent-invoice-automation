from __future__ import annotations

from acme_invoice.llm import HeuristicLLMClient, ResilientLLMClient


class _FailingClient:
    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("Error code: 403 - permission-denied credits")


def test_resilient_falls_back_on_403():
    client = ResilientLLMClient(_FailingClient(), HeuristicLLMClient())
    out = client.complete(
        "Extract structured invoice data as JSON",
        "INVOICE TEXT:\nVendor: Widgets Inc.\nInvoice Number: INV-1001\nTotal Amount: $5000\nWidgetA qty: 10",
    )
    assert "Widgets Inc." in out
    # Second call should use cached fallback without raising
    out2 = client.complete(
        "You are the VP of Finance",
        '{"amount": 5000, "hard_issues": []}',
    )
    assert "APPROVED" in out2 or "REJECTED" in out2
