"""LangGraph shared state for the invoice pipeline."""

from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict

from acme_invoice.models import (
    ApprovalResult,
    Decision,
    ExtractedInvoice,
    PaymentResult,
    StageLog,
    ValidationResult,
)


def _merge_stages(left: list[StageLog], right: list[StageLog]) -> list[StageLog]:
    """Reducer: append stage logs across nodes (do not re-emit prior stages)."""
    return (left or []) + (right or [])


class InvoiceState(TypedDict, total=False):
    """Mutable graph state passed between agent nodes."""

    invoice_path: str
    source_format: str
    raw_text: str
    extracted: Optional[ExtractedInvoice]
    extraction_errors: list[str]
    extraction_attempts: int
    validation: Optional[ValidationResult]
    approval: Optional[ApprovalResult]
    payment: Optional[PaymentResult]
    final_status: Decision
    # Annotated so each node can append only its own StageLog entries
    stages: Annotated[list[StageLog], _merge_stages]
    error: Optional[str]
    critique_done: bool
    metadata: dict[str, Any]
