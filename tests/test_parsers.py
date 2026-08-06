from __future__ import annotations

from pathlib import Path

from acme_invoice.tools.parsers.loader import ingest_invoice
from acme_invoice.tools.parsers.normalize import normalize_item_name, parse_money
from acme_invoice.tools.parsers.structured import (
    parse_csv_invoice,
    parse_json_invoice,
    parse_xml_invoice,
)


def test_normalize_item_names():
    assert normalize_item_name("Widget A") == "WidgetA"
    assert normalize_item_name("gadget x") == "GadgetX"
    assert normalize_item_name("WidgetA (rush order)") == "WidgetA"


def test_parse_money_ocr():
    assert parse_money("$3,500.O0") == 3500.0
    assert parse_money("15000.00") == 15000.0


def test_parse_json_1004(invoices_dir: Path):
    text = (invoices_dir / "invoice_1004.json").read_text()
    inv = parse_json_invoice(text)
    assert inv.vendor == "Precision Parts Ltd."
    assert inv.amount == 1890.0
    assert len(inv.items) == 2


def test_parse_json_1009_negative(invoices_dir: Path):
    text = (invoices_dir / "invoice_1009.json").read_text()
    inv = parse_json_invoice(text)
    assert inv.vendor == ""
    assert any(i.quantity < 0 for i in inv.items)
    assert "negative_quantity" in inv.anomalies


def test_parse_csv_kv_and_tabular(invoices_dir: Path):
    kv = parse_csv_invoice((invoices_dir / "invoice_1006.csv").read_text())
    assert kv.invoice_number == "INV-1006"
    assert len(kv.items) == 2

    tabular = parse_csv_invoice((invoices_dir / "invoice_1015.csv").read_text())
    assert tabular.vendor == "Reliable Components Inc."
    assert tabular.amount == 6500.0
    assert len(tabular.items) == 3


def test_parse_xml_1014(invoices_dir: Path):
    inv = parse_xml_invoice((invoices_dir / "invoice_1014.xml").read_text())
    assert inv.vendor == "TechParts International"
    assert inv.currency == "EUR"
    assert len(inv.items) == 2


def test_ingest_txt(invoices_dir: Path):
    doc = ingest_invoice(invoices_dir / "invoice_1001.txt")
    assert doc.source_format == "txt"
    assert "WidgetA" in doc.raw_text
