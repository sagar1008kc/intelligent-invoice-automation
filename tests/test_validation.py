from __future__ import annotations

from acme_invoice.models import ExtractedInvoice, LineItem
from acme_invoice.tools.inventory import InventoryRepository


def test_stock_ok(db_path):
    repo = InventoryRepository(db_path)
    inv = ExtractedInvoice(
        vendor="Widgets Inc.",
        amount=5000,
        items=[
            LineItem(name="WidgetA", quantity=10, unit_price=250),
            LineItem(name="WidgetB", quantity=5, unit_price=500),
        ],
    )
    issues, calls = repo.validate_invoice(inv)
    hard = [i for i in issues if i.severity.value == "hard"]
    assert hard == []
    assert any(c["tool"] == "get_stock" for c in calls)


def test_stock_mismatch_gadgetx(db_path):
    repo = InventoryRepository(db_path)
    inv = ExtractedInvoice(
        vendor="Gadgets Co.",
        amount=15000,
        items=[LineItem(name="GadgetX", quantity=20, unit_price=750)],
    )
    issues, _ = repo.validate_invoice(inv)
    assert any(i.code == "stock_mismatch" for i in issues)


def test_fake_item_and_blocked_vendor(db_path):
    repo = InventoryRepository(db_path)
    inv = ExtractedInvoice(
        vendor="Fraudster LLC",
        amount=100000,
        items=[LineItem(name="FakeItem", quantity=100, unit_price=1000)],
        raw_notes="URGENT - Pay immediately Wire transfer",
    )
    issues, _ = repo.validate_invoice(inv)
    codes = {i.code for i in issues}
    assert "out_of_stock" in codes or "suspicious_item" in codes
    assert "blocked_vendor" in codes
    assert "urgency_language" in codes


def test_unknown_item(db_path):
    repo = InventoryRepository(db_path)
    inv = ExtractedInvoice(
        vendor="NoProd Industries",
        amount=9900,
        items=[
            LineItem(name="SuperGizmo", quantity=12, unit_price=400),
            LineItem(name="MegaSprocket", quantity=6, unit_price=850),
        ],
    )
    issues, _ = repo.validate_invoice(inv)
    assert any(i.code == "unknown_item" for i in issues)


def test_negative_quantity(db_path):
    repo = InventoryRepository(db_path)
    inv = ExtractedInvoice(
        vendor="",
        amount=-250,
        items=[
            LineItem(name="WidgetA", quantity=-5, unit_price=250),
            LineItem(name="WidgetB", quantity=2, unit_price=500),
        ],
    )
    issues, _ = repo.validate_invoice(inv)
    codes = {i.code for i in issues}
    assert "invalid_quantity" in codes
    assert "missing_vendor" in codes
    assert "negative_amount" in codes


def test_aggregated_quantities_exceed_stock(db_path):
    repo = InventoryRepository(db_path)
    inv = ExtractedInvoice(
        vendor="Atlas Industrial Supply",
        amount=22562.80,
        items=[
            LineItem(name="WidgetA", quantity=15, unit_price=250),
            LineItem(name="WidgetA", quantity=5, unit_price=240),
            LineItem(name="WidgetA", quantity=2, unit_price=250),
        ],
    )
    issues, _ = repo.validate_invoice(inv)
    assert any(i.code == "stock_mismatch" and i.item == "WidgetA" for i in issues)
