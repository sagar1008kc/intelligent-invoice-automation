"""Ingestion agent — load invoice files into raw text."""

from __future__ import annotations

from acme_invoice.observability import stage_timer
from acme_invoice.state import InvoiceState
from acme_invoice.tools.parsers.loader import ingest_invoice


def ingestion_agent(state: InvoiceState) -> InvoiceState:
    with stage_timer("ingestion") as stage:
        doc = ingest_invoice(state["invoice_path"])
        stage.message = f"Loaded {doc.path.name} as {doc.source_format}"
        stage.details = {
            "path": str(doc.path),
            "format": doc.source_format,
            "chars": len(doc.raw_text),
        }
        return {
            "invoice_path": str(doc.path),
            "source_format": doc.source_format,
            "raw_text": doc.raw_text,
            "stages": [stage],
            "extraction_attempts": 0,
            "extraction_errors": [],
            "critique_done": False,
        }
