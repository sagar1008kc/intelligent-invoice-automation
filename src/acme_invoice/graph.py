"""LangGraph orchestration for the invoice processing workflow.

Flow:
  ingest → extract (optional self-correct) → validate
    → approve (optional critique) → pay | reject

Inject `llm` / `repo` in tests to avoid live API and share a temp DB.
"""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from acme_invoice.agents.approval import (
    approval_agent,
    critique_agent,
    route_after_approval,
    should_critique,
)
from acme_invoice.agents.extraction import extraction_agent, should_retry_extraction
from acme_invoice.agents.ingestion import ingestion_agent
from acme_invoice.agents.payment import payment_agent, reject_agent
from acme_invoice.agents.validation import route_after_validation, validation_agent
from acme_invoice.llm import LLMClient
from acme_invoice.models import Decision, PipelineResult
from acme_invoice.state import InvoiceState
from acme_invoice.tools.inventory import InventoryRepository


def build_graph(
    llm: LLMClient | None = None,
    repo: InventoryRepository | None = None,
):
    extract = partial(extraction_agent, llm=llm)
    approve = partial(approval_agent, llm=llm)
    critique = partial(critique_agent, llm=llm)
    validate = partial(validation_agent, repo=repo)

    graph = StateGraph(InvoiceState)
    graph.add_node("ingest", ingestion_agent)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("approve", approve)
    graph.add_node("critique", critique)
    graph.add_node("pay", payment_agent)
    graph.add_node("reject", reject_agent)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "extract")
    graph.add_conditional_edges(
        "extract",
        should_retry_extraction,
        {
            "retry": "extract",
            "continue": "validate",
            "fail": "reject",
        },
    )
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "approve": "approve",
            "reject": "reject",
        },
    )
    graph.add_conditional_edges(
        "approve",
        should_critique,
        {
            "critique": "critique",
            "done": "route_payment",
        },
    )
    # Passthrough router — must not re-emit stages (Annotated reducer would duplicate)
    graph.add_node("route_payment", lambda _state: {})
    graph.add_conditional_edges(
        "route_payment",
        route_after_approval,
        {
            "pay": "pay",
            "reject": "reject",
        },
    )
    graph.add_conditional_edges(
        "critique",
        route_after_approval,
        {
            "pay": "pay",
            "reject": "reject",
        },
    )
    graph.add_edge("pay", END)
    graph.add_edge("reject", END)
    return graph.compile()


def run_invoice_pipeline(
    invoice_path: str,
    *,
    llm: LLMClient | None = None,
    repo: InventoryRepository | None = None,
) -> PipelineResult:
    app = build_graph(llm=llm, repo=repo)
    initial: InvoiceState = {
        "invoice_path": invoice_path,
        "stages": [],
        "extraction_attempts": 0,
        "extraction_errors": [],
        "critique_done": False,
        "final_status": Decision.PENDING,
    }
    try:
        final_state = app.invoke(initial)
    except Exception as exc:  # noqa: BLE001
        return PipelineResult(
            invoice_path=invoice_path,
            final_status=Decision.REJECTED,
            error=str(exc),
        )

    return PipelineResult(
        invoice_path=final_state.get("invoice_path", invoice_path),
        final_status=final_state.get("final_status") or Decision.PENDING,
        extracted=final_state.get("extracted"),
        validation=final_state.get("validation"),
        approval=final_state.get("approval"),
        payment=final_state.get("payment"),
        stages=list(final_state.get("stages") or []),
        error=final_state.get("error"),
    )
