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

STAGE_LABELS = ["Ingest", "Extract", "Validate", "Approve", "Pay"]
STAGE_ORDER = [
    "ingestion",
    "extraction",
    "validation",
    "approval",
    "approval_critique",
    "payment",
]


def _ensure_db() -> bool:
    settings = get_settings()
    return Path(settings.inventory_db_path).exists()


def _stage_index(result) -> int:
    seen = {s.stage for s in result.stages}
    idx = 0
    for i, name in enumerate(STAGE_ORDER):
        if name in seen:
            idx = i
    if result.final_status == Decision.APPROVED:
        return len(STAGE_ORDER) - 1
    return idx


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(1100px 480px at 8% -12%, #dbeafe 0%, transparent 55%),
            radial-gradient(900px 420px at 100% 0%, #ecfdf5 0%, transparent 48%),
            linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
        }
        [data-testid="stSidebar"] {
          background: rgba(255, 255, 255, 0.88);
          border-right: 1px solid #e2e8f0;
        }
        h1 {
          font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
          letter-spacing: -0.02em;
          margin-bottom: 0.15rem !important;
        }
        h2, h3 {
          font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
        }
        .acme-caption {
          color: #475569;
          font-size: 0.95rem;
          margin-bottom: 1.25rem;
        }
        .stage-pill {
          text-align: center;
          padding: 0.55rem 0.35rem;
          border-radius: 10px;
          background: #fff;
          border: 1px solid #e2e8f0;
          font-weight: 600;
          font-size: 0.85rem;
        }
        div[data-testid="stMetric"] {
          background: #fff;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          padding: 0.75rem 0.9rem;
        }
        .stButton > button[kind="primary"] {
          border-radius: 10px;
          font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_stage_track(result) -> None:
    current = min(_stage_index(result), len(STAGE_LABELS) - 1)
    cols = st.columns(len(STAGE_LABELS))
    for i, (col, label) in enumerate(zip(cols, STAGE_LABELS)):
        done = i <= current
        failed = result.final_status == Decision.REJECTED and i == current
        if failed:
            color, marker = "#b91c1c", "●"
        elif done:
            color, marker = "#0f766e", "●"
        else:
            color, marker = "#94a3b8", "○"
        col.markdown(
            f"<div class='stage-pill' style='color:{color}'>{marker}<br>{label}</div>",
            unsafe_allow_html=True,
        )


def _stages_frame(result) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stage": s.stage,
                "status": s.status,
                "ms": round(s.duration_ms, 2),
                "message": s.message,
            }
            for s in result.stages
        ]
    )


def main() -> None:
    _inject_styles()

    st.title("Acme Invoice Automation")
    st.markdown(
        "<p class='acme-caption'>Multi-agent AP workflow — "
        "Ingest → Extract → Validate → Approve → Pay</p>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Controls")
        use_heuristic = st.toggle(
            "Offline heuristic LLM",
            value=not get_settings().has_api_key,
            help="Use deterministic offline reasoning instead of live Grok",
        )
        if not _ensure_db():
            st.error("inventory.db missing. Run: `python scripts/init_db.py`")
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
        st.dataframe(inv_df, width="stretch", hide_index=True)

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

        run = st.button("Run pipeline", type="primary", width="stretch")
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

            _render_stage_track(result)

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
                            pd.DataFrame(
                                [i.model_dump() for i in result.validation.issues]
                            ),
                            width="stretch",
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
                    st.dataframe(_stages_frame(result), width="stretch", hide_index=True)

            st.download_button(
                "Download audit JSON",
                data=result.model_dump_json(indent=2),
                file_name=f"audit_{Path(result.invoice_path).stem}.json",
                mime="application/json",
                width="content",
            )

    with tab_batch:
        st.write("Run the full sample suite and score outcomes.")
        dedupe = st.checkbox("Skip PDF when TXT twin exists", value=True)
        if st.button("Run batch suite", type="primary", width="stretch"):
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
            st.dataframe(df, width="stretch", hide_index=True)
            approved = int((df["status"] == Decision.APPROVED.value).sum())
            rejected = len(df) - approved
            m1, m2, m3 = st.columns(3)
            m1.metric("Approved", f"{approved}/{len(df)}")
            m2.metric("Rejected", f"{rejected}/{len(df)}")
            m3.metric("STP rate", f"{(approved / len(df) * 100):.0f}%")
            st.download_button(
                "Download batch results",
                data=df.to_json(orient="records", indent=2),
                file_name="batch_results.json",
                mime="application/json",
                width="content",
            )


if __name__ == "__main__":
    main()
