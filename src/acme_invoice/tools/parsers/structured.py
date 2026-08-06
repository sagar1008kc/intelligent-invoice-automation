"""Deterministic parsers for JSON, CSV, and XML invoices."""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from acme_invoice.models import ExtractedInvoice, LineItem
from acme_invoice.tools.parsers.normalize import normalize_item_name, parse_money, parse_quantity


def parse_json_invoice(text: str) -> ExtractedInvoice:
    data = json.loads(text)
    vendor_obj = data.get("vendor", "")
    if isinstance(vendor_obj, dict):
        vendor = vendor_obj.get("name") or ""
    else:
        vendor = vendor_obj or ""

    items: list[LineItem] = []
    for row in data.get("line_items") or data.get("items") or []:
        name = normalize_item_name(str(row.get("item") or row.get("name") or ""))
        qty = parse_quantity(row.get("quantity") if "quantity" in row else row.get("qty"))
        price = parse_money(row.get("unit_price") if "unit_price" in row else row.get("price"))
        line_total = parse_money(row.get("amount") or row.get("line_total"))
        if name:
            items.append(
                LineItem(
                    name=name,
                    quantity=qty if qty is not None else 0,
                    unit_price=price,
                    line_total=line_total,
                )
            )

    amount = parse_money(data.get("total") or data.get("amount") or data.get("total_amount")) or 0.0
    anomalies: list[str] = []
    if not vendor:
        anomalies.append("missing_vendor")
    if any(i.quantity < 0 for i in items):
        anomalies.append("negative_quantity")
    if amount < 0:
        anomalies.append("negative_amount")

    confidence = 0.95
    if anomalies:
        confidence = 0.55

    return ExtractedInvoice(
        vendor=str(vendor).strip(),
        invoice_number=str(data.get("invoice_number") or data.get("invoice") or ""),
        invoice_date=_as_str(data.get("date") or data.get("invoice_date")),
        due_date=_as_str(data.get("due_date")),
        amount=amount,
        currency=str(data.get("currency") or "USD"),
        items=items,
        payment_terms=_as_str(data.get("payment_terms")),
        confidence=confidence,
        anomalies=anomalies,
    )


def parse_csv_invoice(text: str) -> ExtractedInvoice:
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return ExtractedInvoice(confidence=0.1, anomalies=["empty_csv"])

    header = [c.strip().lower() for c in rows[0]]

    # Format A: field,value key-value CSV (INV-1006)
    if header[:2] == ["field", "value"] or (
        len(rows[0]) == 2 and "invoice" in rows[0][0].lower()
    ):
        return _parse_kv_csv(rows if header[:2] != ["field", "value"] else rows[1:])

    # Format B: tabular line-item CSV (INV-1007 / INV-1015)
    return _parse_tabular_csv(header, rows[1:])


def _parse_kv_csv(rows: list[list[str]]) -> ExtractedInvoice:
    meta: dict[str, str] = {}
    items: list[LineItem] = []
    current: dict[str, Any] = {}

    for row in rows:
        if len(row) < 2:
            continue
        key, value = row[0].strip().lower(), row[1].strip()
        if key == "item":
            if current.get("item"):
                items.append(_item_from_partial(current))
            current = {"item": value}
        elif key in {"quantity", "qty", "unit_price", "price"} and current:
            current[key] = value
        else:
            meta[key] = value

    if current.get("item"):
        items.append(_item_from_partial(current))

    amount = parse_money(meta.get("total") or meta.get("amount")) or 0.0
    return ExtractedInvoice(
        vendor=meta.get("vendor", ""),
        invoice_number=meta.get("invoice_number", meta.get("invoice", "")),
        invoice_date=meta.get("date"),
        due_date=meta.get("due_date"),
        amount=amount,
        items=items,
        payment_terms=meta.get("payment_terms"),
        confidence=0.9 if items and meta.get("vendor") else 0.5,
        anomalies=[],
    )


def _parse_tabular_csv(header: list[str], rows: list[list[str]]) -> ExtractedInvoice:
    def idx(*names: str) -> int | None:
        for name in names:
            if name in header:
                return header.index(name)
        return None

    i_inv = idx("invoice number", "invoice_number", "invoice")
    i_vendor = idx("vendor")
    i_date = idx("date")
    i_due = idx("due date", "due_date")
    i_item = idx("item", "description")
    i_qty = idx("qty", "quantity")
    i_price = idx("unit price", "unit_price", "price")
    i_line = idx("line total", "line_total", "amount")

    vendor = ""
    invoice_number = ""
    invoice_date = None
    due_date = None
    items: list[LineItem] = []
    total = 0.0

    for row in rows:
        # Totals footer rows often have empty leading cells
        joined = ",".join(row).lower()
        if "total" in joined and "subtotal" not in joined and "tax" not in joined:
            money = parse_money(row[-1]) if row else None
            if money is not None:
                total = money
            continue
        if "subtotal" in joined or "tax" in joined:
            continue

        item_name = row[i_item].strip() if i_item is not None and i_item < len(row) else ""
        if not item_name:
            continue

        if i_vendor is not None and i_vendor < len(row) and row[i_vendor].strip():
            vendor = row[i_vendor].strip()
        if i_inv is not None and i_inv < len(row) and row[i_inv].strip():
            invoice_number = row[i_inv].strip()
        if i_date is not None and i_date < len(row) and row[i_date].strip():
            invoice_date = row[i_date].strip()
        if i_due is not None and i_due < len(row) and row[i_due].strip():
            due_date = row[i_due].strip()

        qty = parse_quantity(row[i_qty]) if i_qty is not None and i_qty < len(row) else 0
        price = parse_money(row[i_price]) if i_price is not None and i_price < len(row) else None
        line_total = parse_money(row[i_line]) if i_line is not None and i_line < len(row) else None
        items.append(
            LineItem(
                name=normalize_item_name(item_name),
                quantity=qty or 0,
                unit_price=price,
                line_total=line_total,
            )
        )

    if total <= 0 and items:
        total = sum(
            (i.line_total if i.line_total is not None else (i.quantity * (i.unit_price or 0)))
            for i in items
        )

    return ExtractedInvoice(
        vendor=vendor,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        amount=total,
        items=items,
        confidence=0.9 if vendor and items else 0.5,
        anomalies=[],
    )


def parse_xml_invoice(text: str) -> ExtractedInvoice:
    root = ET.fromstring(text)
    header = root.find("header") if root.find("header") is not None else root

    def text_of(parent: ET.Element | None, *tags: str) -> str:
        if parent is None:
            return ""
        for tag in tags:
            node = parent.find(tag)
            if node is not None and node.text:
                return node.text.strip()
        return ""

    vendor = text_of(header, "vendor") or text_of(root, "vendor")
    invoice_number = text_of(header, "invoice_number", "invoice") or text_of(
        root, "invoice_number", "invoice"
    )
    invoice_date = text_of(header, "date") or text_of(root, "date") or None
    due_date = text_of(header, "due_date") or text_of(root, "due_date") or None
    currency = text_of(header, "currency") or text_of(root, "currency") or "USD"

    items: list[LineItem] = []
    line_parent = root.find("line_items")
    item_nodes = list(line_parent.findall("item")) if line_parent is not None else root.findall(".//item")
    for node in item_nodes:
        name = text_of(node, "name", "item")
        if not name:
            continue
        qty = parse_quantity(text_of(node, "quantity", "qty")) or 0
        price = parse_money(text_of(node, "unit_price", "price"))
        items.append(LineItem(name=normalize_item_name(name), quantity=qty, unit_price=price))

    totals = root.find("totals")
    amount = parse_money(text_of(totals, "total") if totals is not None else text_of(root, "total")) or 0.0
    payment_terms = text_of(root, "payment_terms") or None

    return ExtractedInvoice(
        vendor=vendor,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        amount=amount,
        currency=currency,
        items=items,
        payment_terms=payment_terms,
        confidence=0.92 if vendor and items else 0.5,
        anomalies=["non_usd_currency"] if currency.upper() != "USD" else [],
    )


def try_structured_parse(path: Path, text: str) -> ExtractedInvoice | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return parse_json_invoice(text)
        if suffix == ".csv":
            return parse_csv_invoice(text)
        if suffix == ".xml":
            return parse_xml_invoice(text)
    except Exception:  # noqa: BLE001 - fall back to LLM extraction
        return None
    return None


def _item_from_partial(partial: dict[str, Any]) -> LineItem:
    qty = parse_quantity(partial.get("quantity") or partial.get("qty")) or 0
    price = parse_money(partial.get("unit_price") or partial.get("price"))
    return LineItem(
        name=normalize_item_name(str(partial.get("item", ""))),
        quantity=qty,
        unit_price=price,
    )


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
