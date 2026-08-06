from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from acme_invoice.graph import run_invoice_pipeline
from acme_invoice.llm import HeuristicLLMClient
from acme_invoice.models import Decision
from acme_invoice.tools.inventory import InventoryRepository
from acme_invoice.tools.payment import mock_payment


@pytest.mark.parametrize(
    "filename,expected",
    [
        # Clean / within stock → approve + pay
        ("invoice_1001.txt", Decision.APPROVED),
        ("invoice_1004.json", Decision.APPROVED),
        ("invoice_1006.csv", Decision.APPROVED),
        ("invoice_1010.txt", Decision.APPROVED),
        ("invoice_1011.txt", Decision.APPROVED),
        ("invoice_1012.txt", Decision.APPROVED),  # messy OCR-style text
        ("invoice_1014.xml", Decision.APPROVED),  # EUR soft flag, still payable
        ("invoice_1015.csv", Decision.APPROVED),
        # Case-required rejects
        ("invoice_1002.txt", Decision.REJECTED),  # stock mismatch GadgetX
        ("invoice_1003.txt", Decision.REJECTED),  # FakeItem / fraud
        ("invoice_1005.json", Decision.REJECTED),  # over-stock
        ("invoice_1007.csv", Decision.REJECTED),  # over-stock
        ("invoice_1008.txt", Decision.REJECTED),  # unknown items
        ("invoice_1009.json", Decision.REJECTED),  # negative qty / missing vendor
        ("invoice_1013.json", Decision.REJECTED),  # aggregated over-stock
        ("invoice_1016.json", Decision.REJECTED),  # WidgetC unknown
    ],
)
def test_scenario_matrix(filename, expected, invoices_dir, db_path, heuristic_llm):
    repo = InventoryRepository(db_path)
    result = run_invoice_pipeline(
        str(invoices_dir / filename),
        llm=heuristic_llm,
        repo=repo,
    )
    assert result.final_status == expected, (
        f"{filename}: expected {expected}, got {result.final_status}; "
        f"validation={result.validation}; approval={result.approval}"
    )


def test_payment_not_called_on_reject(invoices_dir, db_path, heuristic_llm):
    repo = InventoryRepository(db_path)
    with patch("acme_invoice.tools.payment.mock_payment", wraps=mock_payment) as mocked:
        result = run_invoice_pipeline(
            str(invoices_dir / "invoice_1003.txt"),
            llm=heuristic_llm,
            repo=repo,
        )
        assert result.final_status == Decision.REJECTED
        mocked.assert_not_called()


def test_payment_called_on_approve(invoices_dir, db_path, heuristic_llm):
    repo = InventoryRepository(db_path)
    with patch("acme_invoice.tools.payment.mock_payment", wraps=mock_payment) as mocked:
        result = run_invoice_pipeline(
            str(invoices_dir / "invoice_1001.txt"),
            llm=heuristic_llm,
            repo=repo,
        )
        assert result.final_status == Decision.APPROVED
        mocked.assert_called_once()
        assert result.payment is not None
        assert result.payment.status == "success"


def test_stock_mismatch_1002(invoices_dir, db_path, heuristic_llm):
    repo = InventoryRepository(db_path)
    result = run_invoice_pipeline(
        str(invoices_dir / "invoice_1002.txt"),
        llm=heuristic_llm,
        repo=repo,
    )
    assert result.final_status == Decision.REJECTED
    assert result.validation is not None
    assert any(i.code == "stock_mismatch" for i in result.validation.issues)
