"""Load invoice files into raw text for downstream extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".json", ".csv", ".xml"}


@dataclass
class IngestedDocument:
    path: Path
    source_format: str
    raw_text: str


def ingest_invoice(path: str | Path) -> IngestedDocument:
    invoice_path = Path(path).expanduser().resolve()
    if not invoice_path.exists():
        raise FileNotFoundError(f"Invoice not found: {invoice_path}")
    if not invoice_path.is_file():
        raise ValueError(f"Invoice path is not a file: {invoice_path}")

    suffix = invoice_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported invoice format '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    if suffix == ".pdf":
        raw_text = _load_pdf(invoice_path)
    else:
        raw_text = invoice_path.read_text(encoding="utf-8", errors="replace")

    if not raw_text.strip():
        raise ValueError(f"Invoice file is empty: {invoice_path}")

    return IngestedDocument(
        path=invoice_path,
        source_format=suffix.lstrip("."),
        raw_text=raw_text,
    )


def _load_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required for PDF ingestion. Install with: pip install pdfplumber"
        ) from exc

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                chunks.append(text)
    return "\n\n".join(chunks)


def list_invoice_files(path: str | Path) -> list[Path]:
    root = Path(path).expanduser().resolve()
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise FileNotFoundError(f"Path not found: {root}")
    files = [
        p
        for p in sorted(root.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    # Prefer non-duplicate PDFs when txt twin exists for same stem? Keep all;
    # batch mode can de-dupe later. Filter revised duplicates optionally.
    return files
