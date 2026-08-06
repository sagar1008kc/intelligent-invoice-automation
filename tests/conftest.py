from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _init_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
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
            status TEXT NOT NULL,
            notes TEXT
        )
        """
    )
    cur.execute("DELETE FROM inventory")
    cur.execute("DELETE FROM vendors")
    cur.executemany(
        "INSERT INTO inventory VALUES (?, ?, ?, ?)",
        [
            ("WidgetA", 15, 250.0, "widget"),
            ("WidgetB", 10, 500.0, "widget"),
            ("GadgetX", 5, 750.0, "gadget"),
            ("FakeItem", 0, 1000.0, "suspicious"),
        ],
    )
    cur.executemany(
        "INSERT INTO vendors VALUES (?, ?, ?)",
        [
            ("Widgets Inc.", "approved", "ok"),
            ("Gadgets Co.", "approved", "ok"),
            ("Fraudster LLC", "blocked", "fraud"),
            ("Precision Parts Ltd.", "approved", "ok"),
            ("Acme Industrial Supplies", "approved", "ok"),
            ("NoProd Industries", "watch", "watch"),
            ("Summit Manufacturing Co.", "approved", "ok"),
            ("Reliable Components Inc.", "approved", "ok"),
            ("QuickShip Distributers", "approved", "ok"),
            ("TechParts International", "approved", "ok"),
            ("Consolidated Materials Group", "approved", "ok"),
            ("Atlas Industrial Supply", "approved", "ok"),
            ("MegaWidgets Corp", "approved", "ok"),
            ("Global Supply Chain Partners", "approved", "ok"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "inventory.db"
    _init_test_db(path)
    monkeypatch.setenv("INVENTORY_DB_PATH", str(path))
    from acme_invoice.config import get_settings

    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture()
def invoices_dir() -> Path:
    return ROOT / "data" / "invoices"


@pytest.fixture()
def heuristic_llm():
    from acme_invoice.llm import HeuristicLLMClient

    return HeuristicLLMClient()
