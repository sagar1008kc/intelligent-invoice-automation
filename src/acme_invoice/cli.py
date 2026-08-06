"""Command-line interface for Acme invoice automation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from acme_invoice.config import ROOT_DIR, get_settings
from acme_invoice.graph import run_invoice_pipeline
from acme_invoice.llm import HeuristicLLMClient, get_llm_client
from acme_invoice.models import Decision, PipelineResult
from acme_invoice.observability import setup_logging
from acme_invoice.tools.parsers.loader import list_invoice_files

console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acme Corp multi-agent invoice processing system",
    )
    parser.add_argument(
        "--invoice_path",
        required=True,
        help="Path to an invoice file or a directory of invoices",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all supported invoices under invoice_path (if directory)",
    )
    parser.add_argument(
        "--output",
        choices=["rich", "json"],
        default="rich",
        help="Output format (default: rich)",
    )
    parser.add_argument(
        "--heuristic",
        action="store_true",
        help="Force offline heuristic LLM (no Grok API calls)",
    )
    parser.add_argument(
        "--dedupe-pdf",
        action="store_true",
        help="In batch mode, skip PDF when a .txt twin exists",
    )
    return parser


def render_result(result: PipelineResult) -> None:
    status = result.final_status.value
    style = "green" if status == Decision.APPROVED.value else "red"
    console.print(
        Panel.fit(
            f"[bold]{status}[/bold] — {Path(result.invoice_path).name}",
            border_style=style,
            title="Invoice Result",
        )
    )

    if result.error:
        console.print(f"[red]Error:[/red] {result.error}")

    if result.extracted:
        inv = result.extracted
        table = Table(title="Extracted Invoice", show_header=True, header_style="bold")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("Vendor", inv.vendor)
        table.add_row("Invoice #", inv.invoice_number)
        table.add_row("Amount", f"{inv.amount:,.2f} {inv.currency}")
        table.add_row("Due Date", inv.due_date or "—")
        table.add_row("Confidence", f"{inv.confidence:.2f}")
        items = ", ".join(f"{i.name}×{i.quantity:g}" for i in inv.items) or "—"
        table.add_row("Items", items)
        console.print(table)

    if result.validation:
        vtable = Table(title="Validation Issues", show_header=True, header_style="bold")
        vtable.add_column("Severity")
        vtable.add_column("Code")
        vtable.add_column("Message")
        if not result.validation.issues:
            vtable.add_row("—", "—", "No issues")
        for issue in result.validation.issues:
            color = "red" if issue.severity.value == "hard" else "yellow"
            vtable.add_row(
                f"[{color}]{issue.severity.value}[/{color}]",
                issue.code,
                issue.message,
            )
        console.print(vtable)

    if result.approval:
        console.print(
            Panel(
                f"{result.approval.rationale}\n\n"
                f"Risk score: {result.approval.risk_score:.2f}\n"
                f"Scrutiny: {result.approval.requires_scrutiny}",
                title=f"VP Approval — {result.approval.decision.value}",
                border_style="cyan",
            )
        )
        if result.approval.reflections:
            tree = Tree("Reflection / critique loop")
            for note in result.approval.reflections:
                tree.add(note)
            console.print(tree)

    if result.payment:
        console.print(
            Panel(
                result.payment.message
                + (
                    f"\nTxn: {result.payment.transaction_id}"
                    if result.payment.transaction_id
                    else ""
                ),
                title="Payment",
                border_style="magenta",
            )
        )

    if result.stages:
        timeline = Table(title="Stage Timeline", show_header=True, header_style="bold")
        timeline.add_column("Stage")
        timeline.add_column("Status")
        timeline.add_column("ms")
        timeline.add_column("Message")
        for stage in result.stages:
            timeline.add_row(
                stage.stage,
                stage.status,
                f"{stage.duration_ms:.1f}",
                stage.message,
            )
        console.print(timeline)


def _select_files(path: Path, batch: bool, dedupe_pdf: bool) -> list[Path]:
    if path.is_file():
        return [path]
    files = list_invoice_files(path)
    if not batch and path.is_dir():
        console.print(
            "[yellow]Directory provided without --batch; "
            "processing all files. Pass --batch to acknowledge.[/yellow]"
        )
    if dedupe_pdf:
        structured_stems = {
            p.stem for p in files if p.suffix.lower() in {".txt", ".json", ".csv", ".xml"}
        }
        files = [
            p
            for p in files
            if not (p.suffix.lower() == ".pdf" and p.stem in structured_stems)
        ]
    # Prefer primary samples; skip revised duplicate unless alone
    files = [p for p in files if "revised" not in p.name]
    return files


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()

    path = Path(args.invoice_path).expanduser()
    if not path.is_absolute():
        candidate = (Path.cwd() / path).resolve()
        if not candidate.exists():
            candidate = (ROOT_DIR / path).resolve()
        path = candidate

    if not path.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        return 1

    db_path = settings.inventory_db_path
    if not Path(db_path).exists():
        console.print(
            f"[red]Inventory DB missing at {db_path}.[/red] "
            "Run: python scripts/init_db.py"
        )
        return 1

    llm = HeuristicLLMClient() if args.heuristic else get_llm_client()
    files = _select_files(path, batch=args.batch or path.is_dir(), dedupe_pdf=args.dedupe_pdf)
    if not files:
        console.print("[red]No invoice files found.[/red]")
        return 1

    results: list[PipelineResult] = []
    for file_path in files:
        console.rule(f"[bold]Processing {file_path.name}")
        result = run_invoice_pipeline(str(file_path), llm=llm)
        results.append(result)
        if args.output == "json":
            console.print_json(result.model_dump_json(indent=2))
        else:
            render_result(result)

    if len(results) > 1:
        summary = Table(title="Batch Summary", show_header=True, header_style="bold")
        summary.add_column("Invoice")
        summary.add_column("Status")
        summary.add_column("Vendor")
        summary.add_column("Amount")
        for r in results:
            summary.add_row(
                Path(r.invoice_path).name,
                r.final_status.value,
                r.extracted.vendor if r.extracted else "—",
                f"{r.extracted.amount:,.2f}" if r.extracted else "—",
            )
        console.print(summary)
        approved = sum(1 for r in results if r.final_status == Decision.APPROVED)
        console.print(f"Approved: {approved}/{len(results)}")

    # Exit non-zero if single invoice rejected
    if len(results) == 1 and results[0].final_status != Decision.APPROVED:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
