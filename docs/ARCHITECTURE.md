# Architecture

Local multi-agent AP pipeline for Acme Corp.

**Ingest → Extract → Validate → Approve (critique) → Pay / Reject**

```text
CLI / Streamlit
      ↓
 LangGraph StateGraph
      ↓
 ingest → extract ⟲ → validate → approve ⟲critique → pay|reject
                         ↓
                   SQLite inventory.db
```

| Concern | Choice |
|---|---|
| Orchestration | LangGraph `StateGraph` — typed state, conditional edges, append-only stage audit |
| Reasoning | xAI Grok (`langchain-xai` / OpenAI-compatible API) |
| Controls | SQLite inventory + vendor risk tools (deterministic) |
| Surfaces | CLI (`main.py`) and Streamlit (`app.py`) |

Related: [DECISIONS.md](DECISIONS.md) · [RUNBOOK.md](RUNBOOK.md) · [DEMO.md](DEMO.md)

## Component map

| Layer | Module | Responsibility |
|---|---|---|
| CLI / UI | `main.py`, `cli.py`, `app.py` | Operator entrypoints |
| Graph | `graph.py` | Compile/run workflow |
| Agents | `agents/*` | Stage logic |
| Tools | `tools/*` | Parsers, inventory, mock payment |
| Models | `models.py` | Pydantic contracts |
| LLM | `llm.py` | Grok + heuristic + resilient fallback |
| Config | `config.py` | Env-driven settings |

## Graph flow

```text
START
  → ingest
  → extract ⟲ (self-correct up to MAX_EXTRACTION_RETRIES)
  → validate
      ├─ hard fail → reject → END
      └─ pass → approve
                  ├─ high scrutiny → critique → pay|reject → END
                  └─ done → pay|reject → END
```

### Ingestion

Load PDF/TXT/JSON/CSV/XML → `raw_text` + `source_format`. PDFs via `pdfplumber` (text layer; no OCR engine).

### Extraction

1. Deterministic parsers for JSON/CSV/XML when line items exist.
2. Else Grok structured JSON → Pydantic `ExtractedInvoice`.
3. Self-correction edge re-prompts on incomplete extracts (missing items / empty identity at low confidence).
4. Normalize catalog names (`Widget A` → `WidgetA`) before validation.

### Validation (tool use)

`InventoryRepository` tool surface:

- `get_stock(item)`
- `check_line_items(items)` — aggregates duplicate SKUs (INV-1010 / INV-1013)
- `check_price_anomaly(item, unit_price)`
- `check_vendor_risk(vendor)`

| Severity | Examples |
|---|---|
| Hard fail | Unknown item, qty ≤ 0, qty > stock, zero-stock/suspicious item, blocked vendor, missing vendor, negative/zero amount |
| Soft flag | Non-USD, price drift, urgency language, suspicious due date, watchlist vendor → escalate scrutiny |

### Approval (VP + critique)

Rule priors first, then Grok VP `{decision, rationale, risk_score, requires_scrutiny}`.  
Elevated-risk approvals get one critique pass. Critique may overturn **approve → reject only**.

### Payment

Dual gate: `validation.passed` **and** `approval == APPROVED` before `mock_payment`. Rejects log reason and never call the bank mock.

## State contract

`InvoiceState` includes path/raw text, `ExtractedInvoice`, `ValidationResult`, `ApprovalResult`, `PaymentResult`, append-merged `stages`, retry/critique counters, `final_status`, `error`.

## Threat model (prototype)

| Risk | Control |
|---|---|
| Fraudulent vendor / FakeItem | Vendor status + suspicious category |
| Over-ordering | Aggregated stock checks |
| High-value leakage | $10k scrutiny + critique |
| OCR / messy formats | LLM extract + retry |
| Accidental pay on bad data | Hard validation short-circuit |

## Offline / test mode

Unset key, `--heuristic`, or API 401/403 → `HeuristicLLMClient`. Pytest always injects it so CI stays offline.
