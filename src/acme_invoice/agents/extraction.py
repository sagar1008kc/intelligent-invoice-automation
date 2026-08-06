"""Extraction agent — structured parse + Grok self-correction."""

from __future__ import annotations

from pathlib import Path

from acme_invoice.config import get_settings
from acme_invoice.llm import (
    LLMClient,
    extract_json_object,
    get_llm_client,
    invoice_from_llm_payload,
)
from acme_invoice.models import ExtractedInvoice
from acme_invoice.observability import stage_timer
from acme_invoice.state import InvoiceState
from acme_invoice.tools.parsers.normalize import normalize_item_name
from acme_invoice.tools.parsers.structured import try_structured_parse

EXTRACTION_SYSTEM = """You are an expert AP data-entry specialist for Acme Corp.
Extract structured invoice data from messy text (typos, OCR errors, email wrappers).

Return ONLY valid JSON with this schema:
{
  "vendor": string,
  "invoice_number": string,
  "invoice_date": string|null,
  "due_date": string|null,
  "amount": number,
  "currency": string,
  "items": [{"name": string, "quantity": number, "unit_price": number|null}],
  "payment_terms": string|null,
  "confidence": number,
  "anomalies": [string],
  "raw_notes": string|null
}

Rules:
- Normalize item names to catalog forms when possible: WidgetA, WidgetB, GadgetX, FakeItem.
- Fix OCR artifacts (O/0, spaces in item names like "Widget A").
- If a field is missing, use empty string / null and lower confidence.
- Capture urgency/fraud language in anomalies or raw_notes.
"""


def _needs_retry(invoice: ExtractedInvoice, errors: list[str], threshold: float) -> bool:
    """Retry only when extraction is incomplete — not when data itself is invalid."""
    if errors:
        return True
    if not invoice.items:
        return True
    # Low confidence with no invoice number usually means a failed messy parse
    if invoice.confidence < threshold and not invoice.invoice_number and not invoice.vendor:
        return True
    return False


def _post_normalize(invoice: ExtractedInvoice) -> ExtractedInvoice:
    for item in invoice.items:
        item.name = normalize_item_name(item.name)
    return invoice


def _llm_extract(llm: LLMClient, raw_text: str, errors: list[str]) -> ExtractedInvoice:
    error_block = "\n".join(errors) if errors else "None"
    user = (
        f"Previous extraction issues to fix: {error_block}\n\n"
        f"INVOICE TEXT:\n{raw_text}"
    )
    content = llm.complete(EXTRACTION_SYSTEM, user)
    payload = extract_json_object(content)
    return _post_normalize(invoice_from_llm_payload(payload))


def extraction_agent(state: InvoiceState, llm: LLMClient | None = None) -> InvoiceState:
    """Extract an ExtractedInvoice from raw document text.

    Strategy: structured parsers first (JSON/CSV/XML), then Grok for messy TXT/PDF,
    with a bounded self-correction retry when the extract is incomplete.
    """
    settings = get_settings()
    client = llm or get_llm_client()
    attempts = int(state.get("extraction_attempts") or 0) + 1
    prior_errors = list(state.get("extraction_errors") or [])

    with stage_timer("extraction") as stage:
        path = Path(state["invoice_path"])
        raw_text = state.get("raw_text") or ""
        structured = try_structured_parse(path, raw_text)

        # Prefer deterministic parse for JSON/CSV/XML whenever line items exist.
        # Invalid business data (negative qty, blank vendor) is a validation concern.
        if structured is not None and structured.items:
            invoice = _post_normalize(structured)
            stage.message = "Deterministic structured parse succeeded"
            stage.details = {
                "mode": "structured",
                "confidence": invoice.confidence,
                "invoice_number": invoice.invoice_number,
                "anomalies": invoice.anomalies,
            }
            return {
                "extracted": invoice,
                "extraction_attempts": attempts,
                "extraction_errors": [],
                "stages": [stage],
            }

        # Messy text / PDF → LLM (with optional structured seed)
        seed_errors = prior_errors[:]
        if structured is not None:
            seed_errors.append(
                "Improve/repair this partial extraction: "
                + structured.model_dump_json()
            )

        try:
            invoice = _llm_extract(client, raw_text, seed_errors)
        except Exception as exc:  # noqa: BLE001
            if structured is not None:
                invoice = _post_normalize(structured)
                stage.message = f"LLM extraction failed ({exc}); using structured fallback"
            else:
                stage.message = f"LLM extraction failed: {exc}"
                return {
                    "extraction_attempts": attempts,
                    "extraction_errors": prior_errors + [str(exc)],
                    "error": f"Extraction failed: {exc}",
                    "stages": [stage],
                }

        new_errors: list[str] = []
        if not invoice.vendor:
            new_errors.append("vendor missing")
        if not invoice.items:
            new_errors.append("no line items extracted")
        if invoice.amount < 0:
            new_errors.append("negative amount")

        stage.message = "LLM extraction complete"
        stage.details = {
            "mode": "llm" if structured is None else "hybrid",
            "confidence": invoice.confidence,
            "invoice_number": invoice.invoice_number,
            "errors": new_errors,
            "attempt": attempts,
        }
        return {
            "extracted": invoice,
            "extraction_attempts": attempts,
            "extraction_errors": new_errors,
            "stages": [stage],
        }


def should_retry_extraction(state: InvoiceState) -> str:
    settings = get_settings()
    invoice = state.get("extracted")
    attempts = int(state.get("extraction_attempts") or 0)
    errors = list(state.get("extraction_errors") or [])
    if invoice is None:
        return "fail"
    if attempts < settings.max_extraction_retries and _needs_retry(
        invoice, errors, settings.confidence_threshold
    ):
        return "retry"
    return "continue"
