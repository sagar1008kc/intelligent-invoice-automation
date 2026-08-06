"""Deterministic normalization helpers for item names and money values."""

from __future__ import annotations

import re
from typing import Optional

# Canonical catalog names used in inventory.db
CANONICAL_ITEMS = {
    "widgeta": "WidgetA",
    "widget a": "WidgetA",
    "widget-a": "WidgetA",
    "widgetb": "WidgetB",
    "widget b": "WidgetB",
    "widget-b": "WidgetB",
    "widgetc": "WidgetC",
    "widget c": "WidgetC",
    "gadgetx": "GadgetX",
    "gadget x": "GadgetX",
    "gadget-x": "GadgetX",
    "fakeitem": "FakeItem",
    "fake item": "FakeItem",
    "supergizmo": "SuperGizmo",
    "super gizmo": "SuperGizmo",
    "megasprocket": "MegaSprocket",
    "mega sprocket": "MegaSprocket",
}


def normalize_item_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    # Drop parenthetical notes like "WidgetA (rush order)"
    base = re.sub(r"\s*\(.*?\)\s*", "", cleaned).strip()
    key = base.lower().replace("_", " ").replace("-", " ")
    key = re.sub(r"\s+", " ", key)
    compact = key.replace(" ", "")
    if key in CANONICAL_ITEMS:
        return CANONICAL_ITEMS[key]
    if compact in CANONICAL_ITEMS:
        return CANONICAL_ITEMS[compact]
    # Title-case unknown items without spaces: WidgetC stays WidgetC
    if re.fullmatch(r"[A-Za-z]+\d*[A-Za-z]*", base):
        return base[0].upper() + base[1:]
    return base


def parse_money(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # Fix common OCR artifact: O vs 0 in amounts like 3,500.O0
    text = text.replace("O", "0").replace("o", "0")
    text = text.replace("$", "").replace(",", "").replace("€", "").replace("£", "")
    text = text.replace("USD", "").replace("EUR", "").strip()
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def parse_quantity(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None
