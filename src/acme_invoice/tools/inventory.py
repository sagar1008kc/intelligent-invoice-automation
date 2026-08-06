"""SQLite inventory tools used during validation.

These are the "function calling" surfaces the validation stage uses:
get_stock, check_line_items, check_price_anomaly, check_vendor_risk.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from acme_invoice.config import get_settings
from acme_invoice.models import ExtractedInvoice, IssueSeverity, LineItem, ValidationIssue
from acme_invoice.tools.parsers.normalize import normalize_item_name


@dataclass
class InventoryItem:
    item: str
    stock: int
    unit_price: float
    category: str


@dataclass
class VendorRecord:
    name: str
    status: str
    notes: Optional[str] = None


class InventoryRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path or settings.inventory_db_path)
        self.price_tolerance = settings.price_anomaly_tolerance

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Inventory database not found at {self.db_path}. "
                "Run: python scripts/init_db.py"
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_stock(self, item: str) -> Optional[InventoryItem]:
        name = normalize_item_name(item)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT item, stock, unit_price, category FROM inventory WHERE item = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return InventoryItem(
            item=row["item"],
            stock=int(row["stock"]),
            unit_price=float(row["unit_price"]),
            category=row["category"],
        )

    def list_inventory(self) -> list[InventoryItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT item, stock, unit_price, category FROM inventory ORDER BY item"
            ).fetchall()
        return [
            InventoryItem(
                item=r["item"],
                stock=int(r["stock"]),
                unit_price=float(r["unit_price"]),
                category=r["category"],
            )
            for r in rows
        ]

    def get_vendor(self, vendor: str) -> Optional[VendorRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT name, status, notes FROM vendors WHERE lower(name) = lower(?)",
                (vendor.strip(),),
            ).fetchone()
        if row is None:
            return None
        return VendorRecord(name=row["name"], status=row["status"], notes=row["notes"])

    def check_line_items(self, items: list[LineItem]) -> tuple[list[ValidationIssue], list[dict[str, Any]]]:
        issues: list[ValidationIssue] = []
        tool_calls: list[dict[str, Any]] = []

        # Aggregate duplicate SKUs so bulk invoices (INV-1010 / INV-1013) can't bypass stock caps
        aggregated: dict[str, float] = {}
        for item in items:
            name = normalize_item_name(item.name)
            aggregated[name] = aggregated.get(name, 0.0) + float(item.quantity)

        for name, qty in aggregated.items():
            record = self.get_stock(name)
            tool_calls.append(
                {
                    "tool": "get_stock",
                    "input": {"item": name},
                    "output": None
                    if record is None
                    else {
                        "item": record.item,
                        "stock": record.stock,
                        "unit_price": record.unit_price,
                        "category": record.category,
                    },
                }
            )

            if record is None:
                issues.append(
                    ValidationIssue(
                        code="unknown_item",
                        message=f"Item '{name}' not found in inventory",
                        severity=IssueSeverity.HARD,
                        item=name,
                    )
                )
                continue

            if qty <= 0:
                issues.append(
                    ValidationIssue(
                        code="invalid_quantity",
                        message=f"Item '{name}' has invalid quantity {qty}",
                        severity=IssueSeverity.HARD,
                        item=name,
                        details={"quantity": qty},
                    )
                )

            if record.stock <= 0:
                issues.append(
                    ValidationIssue(
                        code="out_of_stock",
                        message=f"Item '{name}' is out of stock (stock={record.stock})",
                        severity=IssueSeverity.HARD,
                        item=name,
                        details={"stock": record.stock, "requested": qty},
                    )
                )
            elif qty > record.stock:
                issues.append(
                    ValidationIssue(
                        code="stock_mismatch",
                        message=(
                            f"Requested {qty} of '{name}' exceeds available stock {record.stock}"
                        ),
                        severity=IssueSeverity.HARD,
                        item=name,
                        details={"stock": record.stock, "requested": qty},
                    )
                )

            if record.category == "suspicious":
                issues.append(
                    ValidationIssue(
                        code="suspicious_item",
                        message=f"Item '{name}' is marked suspicious in inventory",
                        severity=IssueSeverity.HARD,
                        item=name,
                    )
                )

        # Per-line price anomaly checks
        for item in items:
            name = normalize_item_name(item.name)
            record = self.get_stock(name)
            if record is None or item.unit_price is None:
                continue
            expected = record.unit_price
            if expected <= 0:
                continue
            drift = abs(item.unit_price - expected) / expected
            tool_calls.append(
                {
                    "tool": "check_price_anomaly",
                    "input": {
                        "item": name,
                        "unit_price": item.unit_price,
                        "expected": expected,
                    },
                    "output": {"drift": drift, "tolerance": self.price_tolerance},
                }
            )
            if drift > self.price_tolerance:
                issues.append(
                    ValidationIssue(
                        code="price_anomaly",
                        message=(
                            f"Unit price ${item.unit_price:.2f} for '{name}' differs from "
                            f"catalog ${expected:.2f} by {drift:.0%}"
                        ),
                        severity=IssueSeverity.SOFT,
                        item=name,
                        details={
                            "unit_price": item.unit_price,
                            "expected": expected,
                            "drift": drift,
                        },
                    )
                )

        return issues, tool_calls

    def check_vendor_risk(self, vendor: str) -> tuple[list[ValidationIssue], dict[str, Any]]:
        record = self.get_vendor(vendor)
        output = {
            "tool": "check_vendor_risk",
            "input": {"vendor": vendor},
            "output": None
            if record is None
            else {"name": record.name, "status": record.status, "notes": record.notes},
        }
        issues: list[ValidationIssue] = []
        if not vendor.strip():
            issues.append(
                ValidationIssue(
                    code="missing_vendor",
                    message="Vendor is missing",
                    severity=IssueSeverity.HARD,
                )
            )
            return issues, output

        if record is None:
            issues.append(
                ValidationIssue(
                    code="unknown_vendor",
                    message=f"Vendor '{vendor}' is not in the approved vendor list",
                    severity=IssueSeverity.SOFT,
                )
            )
        elif record.status == "blocked":
            issues.append(
                ValidationIssue(
                    code="blocked_vendor",
                    message=f"Vendor '{vendor}' is blocked: {record.notes or 'high risk'}",
                    severity=IssueSeverity.HARD,
                )
            )
        elif record.status == "watch":
            issues.append(
                ValidationIssue(
                    code="watchlist_vendor",
                    message=f"Vendor '{vendor}' is on the watchlist",
                    severity=IssueSeverity.SOFT,
                )
            )
        return issues, output

    def validate_invoice(self, invoice: ExtractedInvoice) -> tuple[list[ValidationIssue], list[dict[str, Any]]]:
        issues: list[ValidationIssue] = []
        tool_calls: list[dict[str, Any]] = []

        if not invoice.items:
            issues.append(
                ValidationIssue(
                    code="no_line_items",
                    message="Invoice has no line items",
                    severity=IssueSeverity.HARD,
                )
            )

        if invoice.amount is None:
            issues.append(
                ValidationIssue(
                    code="missing_amount",
                    message="Invoice amount is missing",
                    severity=IssueSeverity.HARD,
                )
            )
        elif invoice.amount < 0:
            issues.append(
                ValidationIssue(
                    code="negative_amount",
                    message=f"Invoice amount is negative ({invoice.amount})",
                    severity=IssueSeverity.HARD,
                )
            )
        elif invoice.amount == 0:
            issues.append(
                ValidationIssue(
                    code="zero_amount",
                    message="Invoice amount is zero",
                    severity=IssueSeverity.HARD,
                )
            )

        vendor_issues, vendor_call = self.check_vendor_risk(invoice.vendor)
        issues.extend(vendor_issues)
        tool_calls.append(vendor_call)

        item_issues, item_calls = self.check_line_items(invoice.items)
        issues.extend(item_issues)
        tool_calls.extend(item_calls)

        if invoice.currency and invoice.currency.upper() != "USD":
            issues.append(
                ValidationIssue(
                    code="non_usd_currency",
                    message=f"Currency {invoice.currency} requires treasury review",
                    severity=IssueSeverity.SOFT,
                    details={"currency": invoice.currency},
                )
            )

        due = (invoice.due_date or "").strip().lower()
        if due in {"", "null", "none"}:
            issues.append(
                ValidationIssue(
                    code="missing_due_date",
                    message="Due date is missing",
                    severity=IssueSeverity.SOFT,
                )
            )
        elif due in {"yesterday", "immediate", "asap"}:
            issues.append(
                ValidationIssue(
                    code="suspicious_due_date",
                    message=f"Due date '{invoice.due_date}' looks suspicious",
                    severity=IssueSeverity.SOFT,
                )
            )

        notes = (invoice.raw_notes or "") + " " + " ".join(invoice.anomalies)
        urgency_tokens = ["urgent", "wire transfer", "immediate", "pay immediately", "penalty"]
        if any(token in notes.lower() for token in urgency_tokens):
            issues.append(
                ValidationIssue(
                    code="urgency_language",
                    message="Invoice contains high-pressure payment language",
                    severity=IssueSeverity.SOFT,
                )
            )

        for anomaly in invoice.anomalies:
            if anomaly in {"negative_quantity", "missing_vendor", "negative_amount"}:
                # Already covered by structured checks; keep soft info if not duplicated
                continue
            issues.append(
                ValidationIssue(
                    code="extraction_anomaly",
                    message=f"Extraction anomaly: {anomaly}",
                    severity=IssueSeverity.SOFT,
                    details={"anomaly": anomaly},
                )
            )

        return issues, tool_calls
