#!/usr/bin/env python3
"""Streamlit ops dashboard for Acme invoice automation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from acme_invoice.config import get_settings
from acme_invoice.graph import run_invoice_pipeline
from acme_invoice.llm import HeuristicLLMClient, get_llm_client
from acme_invoice.models import Decision
from acme_invoice.tools.inventory import InventoryRepository
from acme_invoice.tools.parsers.loader import list_invoice_files

st.set_page_config(
    page_title="Acme Invoice Automation",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)

SAMPLES = ROOT / "data" / "invoices"


def _ensure_db() -> bool:
    settings = get_settings()
    return Path(settings.inventory_db_path).exists()


def _stage_index(result) -> int:
    order = ["ingestion", "extraction", "validation", "approval", "approval_critique", "payment"]
    seen = {s.stage for s in result.stages}
    idx = 0
    for i, name in enumerate(order):
        if name in seen:
            idx = i
    if result.final_status == Decision.APPROVED:
        return len(order) - 1
    return idx


def main() -> None:
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(1200px 500px at 10% -10%, #d9e7ff 0%, transparent 55%),
            radial-gradient(900px 400px at 100% 0%, #e8fff4 0%, transparent 50%),
            linear-gradient(180deg, #f7f9fc 0%, #eef2f7 100%);
        }
        h1, h2, h3 { font-family: "Iowan Old Style", "Palatino Linotype", Palatino, serif; }
        .metric-quiet { color: #334155; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Acme Invoice Automation")
    st.caption("Multi-agent AP workflow — Ingest → Extract → Validate → Approve → Pay")

    with st.sidebar:
        st.header("Controls")
        use_heuristic = st.toggle(
            "Offline heuristic LLM",
            value=not get_settings().has_api_key,
            help="Use deterministic offline reasoning instead of live Grok",
        )
        if not _ensure_db():
            st.error("inventory.db missing. Run: python scripts/init_db.py")
            st.stop()

        st.subheader("Inventory snapshot")
        repo = InventoryRepository()
        inv_df = pd.DataFrame(
            [
                {
                    "item": i.item,
                    "stock": i.stock,
                    "unit_price": i.unit_price,
                    "category": i.category,
                }
                for i in repo.list_inventory()
            ]
        )
        st.dataframe(inv_df, use_container_width=True, hide_index=True)

    tab_single, tab_batch = st.tabs(["Single invoice", "Batch suite"])

    with tab_single:
        source = st.radio("Source", ["Sample file", "Upload"], horizontal=True)
        invoice_path: Path | None = None
        uploaded_bytes = None
        uploaded_name = None

        if source == "Sample file":
            samples = [p for p in list_invoice_files(SAMPLES) if "revised" not in p.name]
            labels = [p.name for p in samples]
            choice = st.selectbox("Choose sample invoice", labels, index=0)
            invoice_path = SAMPLES / choice
        else:
            uploaded = st.file_uploader(
                "Upload invoice",
                type=["txt", "pdf", "json", "csv", "xml"],
            )
            if uploaded is not None:
                uploaded_bytes = uploaded.getvalue()
                uploaded_name = uploaded.name

        run = st.button("Run pipeline", type="primary")
        if run:
            llm = HeuristicLLMClient() if use_heuristic else get_llm_client()
            if uploaded_bytes is not None and uploaded_name:
                suffix = Path(uploaded_name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded_bytes)
                    path = tmp.name
            elif invoice_path is not None:
                path = str(invoice_path)
            else:
                st.warning("Select or upload an invoice first.")
                st.stop()

            with st.spinner("Agents working..."):
                result = run_invoice_pipeline(path, llm=llm)

            steps = ["Ingest", "Extract", "Validate", "Approve", "Pay"]
            current = min(_stage_index(result), len(steps) - 1)
            cols = st.columns(len(steps))
            for i, (col, label) in enumerate(zip(cols, steps)):
                marker = "●" if i <= current else "○"
                color = "#0f766e" if i <= current else "#94a3b8"
                if result.final_status == Decision.REJECTED and i == current:
                    color = "#b91c1c"
                col.markdown(
                    f"<div style='text-align:center;color:{color};font-weight:600'>"
                    f"{marker}<br>{label}</div>",
                    unsafe_allow_html=True,
                )

            status_color = "green" if result.final_status == Decision.APPROVED else "red"
            st.markdown(
                f"### Final status: :{status_color}[{result.final_status.value}]"
            )

            c1, c2, c3 = st.columns(3)
            if result.extracted:
                c1.metric("Vendor", result.extracted.vendor or "—")
                c2.metric("Amount", f"${result.extracted.amount:,.2f}")
                c3.metric("Confidence", f"{result.extracted.confidence:.2f}")

            left, right = st.columns(2)
            with left:
                st.subheader("Validation")
                if result.validation:
                    if not result.validation.issues:
                        st.success("No issues — validation passed")
                    else:
                        st.dataframe(
                            pd.DataFrame([i.model_dump() for i in result.validation.issues]),
                            use_container_width=True,
                            hide_index=True,
                        )
                st.subheader("VP rationale")
                if result.approval:
                    st.write(result.approval.rationale)
                    if result.approval.reflections:
                        with st.expander("Critique / reflection loop"):
                            for note in result.approval.reflections:
                                st.write(f"- {note}")
            with right:
                st.subheader("Payment")
                if result.payment:
                    st.write(result.payment.message)
                    if result.payment.transaction_id:
                        st.code(result.payment.transaction_id)
                st.subheader("Stage timeline")
                if result.stages:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "stage": s.stage,
                                    "status": s.status,
                                    "ms": s.duration_ms,
                                    "message": s.message,
                                }
                                for s in result.stages
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

            st.download_button(
                "Download audit JSON",
                data=result.model_dump_json(indent=2),
                file_name=f"audit_{Path(result.invoice_path).stem}.json",
                mime="application/json",
            )

    with tab_batch:
        st.write("Run the full sample suite and score outcomes.")
        dedupe = st.checkbox("Skip PDF when TXT twin exists", value=True)
        if st.button("Run batch suite", type="primary"):
            llm = HeuristicLLMClient() if use_heuristic else get_llm_client()
            files = list_invoice_files(SAMPLES)
            files = [p for p in files if "revised" not in p.name]
            if dedupe:
                structured_stems = {
                    p.stem
                    for p in files
                    if p.suffix.lower() in {".txt", ".json", ".csv", ".xml"}
                }
                files = [
                    p
                    for p in files
                    if not (p.suffix.lower() == ".pdf" and p.stem in structured_stems)
                ]
            rows = []
            progress = st.progress(0.0)
            for i, path in enumerate(files):
                result = run_invoice_pipeline(str(path), llm=llm)
                rows.append(
                    {
                        "file": path.name,
                        "status": result.final_status.value,
                        "vendor": result.extracted.vendor if result.extracted else "",
                        "amount": result.extracted.amount if result.extracted else None,
                        "invoice_number": (
                            result.extracted.invoice_number if result.extracted else ""
                        ),
                        "payment": result.payment.status if result.payment else "",
                    }
                )
                progress.progress((i + 1) / len(files))
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            approved = (df["status"] == Decision.APPROVED.value).sum()
            st.metric("Approved", f"{approved}/{len(df)}")
            st.download_button(
                "Download batch results",
                data=df.to_json(orient="records", indent=2),
                file_name="batch_results.json",
                mime="application/json",
            )


if __name__ == "__main__":
    main()
