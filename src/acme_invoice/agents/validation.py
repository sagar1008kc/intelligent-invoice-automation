"""Validation agent — inventory, vendor, and data-integrity checks.

Hard failures short-circuit the graph to reject (no VP approval / payment).
Soft flags (currency, price drift, urgency language) continue to approval.
"""

from __future__ import annotations

from acme_invoice.models import Decision, ValidationResult
from acme_invoice.observability import stage_timer
from acme_invoice.state import InvoiceState
from acme_invoice.tools.inventory import InventoryRepository


def validation_agent(state: InvoiceState, repo: InventoryRepository | None = None) -> InvoiceState:
    repository = repo or InventoryRepository()
    invoice = state.get("extracted")
    if invoice is None:
        result = ValidationResult(passed=False, issues=[])
        return {
            "validation": result,
            "final_status": Decision.REJECTED,
            "error": "Cannot validate without extracted invoice",
        }

    with stage_timer("validation") as stage:
        issues, tool_calls = repository.validate_invoice(invoice)
        passed = not any(i.severity.value == "hard" for i in issues)
        result = ValidationResult(passed=passed, issues=issues, tool_calls=tool_calls)
        stage.message = "Validation passed" if passed else "Validation failed"
        stage.details = {
            "passed": passed,
            "hard_count": len(result.hard_issues),
            "soft_count": len(result.soft_issues),
            "issues": [i.model_dump() for i in issues],
            "tool_calls": tool_calls,
        }
        updates: InvoiceState = {
            "validation": result,
            "stages": [stage],
        }
        if not passed:
            updates["final_status"] = Decision.REJECTED
        return updates


def route_after_validation(state: InvoiceState) -> str:
    validation = state.get("validation")
    if validation is None or not validation.passed:
        return "reject"
    return "approve"
