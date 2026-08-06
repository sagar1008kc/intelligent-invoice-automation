#!/usr/bin/env python3
"""Initialize the local SQLite inventory database used by the validation agent."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_DB = ROOT / "inventory.db"

INVENTORY_ROWS = [
    # item, stock, unit_price, category
    ("WidgetA", 15, 250.0, "widget"),
    ("WidgetB", 10, 500.0, "widget"),
    ("GadgetX", 5, 750.0, "gadget"),
    ("FakeItem", 0, 1000.0, "suspicious"),
]

VENDOR_ROWS = [
    # name, status, notes
    ("Widgets Inc.", "approved", "Preferred vendor"),
    ("Gadgets Co.", "approved", "Standard supplier"),
    ("Precision Parts Ltd.", "approved", "Trusted"),
    ("Global Supply Chain Partners", "approved", "High volume"),
    ("Acme Industrial Supplies", "approved", "Internal-adjacent"),
    ("MegaWidgets Corp", "approved", "Bulk supplier"),
    ("NoProd Industries", "watch", "Unknown catalog items in past"),
    ("Fraudster LLC", "blocked", "Known fraud risk — do not pay"),
    ("Consolidated Materials Group", "approved", "Standard"),
    ("Summit Manufacturing Co.", "approved", "Standard"),
    ("QuickShip Distributers", "approved", "AKA FastShip Ltd."),
    ("Atlas Industrial Supply", "approved", "Bulk orders"),
    ("TechParts International", "approved", "EUR invoices common"),
    ("Reliable Components Inc.", "approved", "Standard"),
]


def init_db(db_path: Path, *, force: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if force and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                item TEXT PRIMARY KEY,
                stock INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'general'
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS vendors (
                name TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('approved', 'watch', 'blocked')),
                notes TEXT
            )
            """
        )
        cur.execute("DELETE FROM inventory")
        cur.execute("DELETE FROM vendors")
        cur.executemany(
            "INSERT INTO inventory (item, stock, unit_price, category) VALUES (?, ?, ?, ?)",
            INVENTORY_ROWS,
        )
        cur.executemany(
            "INSERT INTO vendors (name, status, notes) VALUES (?, ?, ?)",
            VENDOR_ROWS,
        )
        conn.commit()
    finally:
        conn.close()

    print(f"Initialized inventory database at {db_path}")
    print(f"  inventory rows: {len(INVENTORY_ROWS)}")
    print(f"  vendor rows:    {len(VENDOR_ROWS)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Acme inventory SQLite DB")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB,
        help="Path to inventory.db (default: ./inventory.db)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate the database from scratch",
    )
    args = parser.parse_args()
    init_db(args.db_path, force=args.force)


if __name__ == "__main__":
    main()
