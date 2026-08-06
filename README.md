# Acme Invoice Automation

Multi-agent AP prototype for **Acme Corp** ([Galatiq case](https://github.com/galatiq-ai/galatiq-case-invoices)).

**Ingest → Extract → Validate → Approve (reflect) → Pay / Reject**

LangGraph + xAI Grok · Local SQLite · Mock payments · CLI + Streamlit

> Clean invoices pay in minutes; stock mismatches and fraud never hit the bank mock.  
> `python main.py --invoice_path=data/invoices/invoice_1001.txt`  
> Walkthrough + screenshots: [docs/DEMO.md](docs/DEMO.md)

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

cp .env.example .env          # set XAI_API_KEY=...
python scripts/init_db.py --force

python main.py --invoice_path=data/invoices/invoice_1001.txt
python main.py --invoice_path=data/invoices/ --batch --dedupe-pdf
streamlit run app.py
pytest -q
```

No API credits? Add `--heuristic` (or toggle offline mode in Streamlit).  
Keys live in `.env` only — never commit. Rotate shared keys at [console.x.ai](https://console.x.ai).

## Why this exists

Acme loses ~$2M/year on manual AP (~30% errors, ~5-day email approvals). This MVP shows:

- **Straight-through processing** for clean invoices (minutes, not days)
- **Hard stops** for overstock, unknown SKUs, and fraud before payment
- **Auditable VP decisions** ($10k scrutiny + critique) instead of email chains

Out of scope (on purpose): email ingest, ERP/bank rails, cloud deploy, SSO.  
Next if embedded: ingest → PO match → human queue → real payment + stock reserve.

## Architecture

```text
CLI / Streamlit
      ↓
 LangGraph StateGraph
      ↓
 ingest → extract ⟲ → validate → approve ⟲critique → pay|reject
                         ↓
                   SQLite inventory.db
```

```mermaid
flowchart TD
  CLI[main.py CLI] --> Graph
  UI[Streamlit app.py] --> Graph
  Graph[LangGraph StateGraph]
  Graph --> Ingest[IngestionAgent]
  Ingest --> Extract[ExtractionAgent Grok]
  Extract -->|missing_or_low_confidence| Extract
  Extract --> Validate[ValidationAgent]
  Validate -->|hard_fail| Reject[RejectAndLog]
  Validate -->|pass_or_soft_flags| Approve[ApprovalAgent VP]
  Approve -->|critique_loop| Approve
  Approve -->|approved| Pay[PaymentAgent]
  Approve -->|rejected| Reject
  Validate --> Inventory[(SQLite inventory.db)]
  Pay --> MockPay[mock_payment]
```

| Agent | Role |
|---|---|
| Ingestion | PDF / TXT / JSON / CSV / XML |
| Extraction | Parsers first; Grok + self-correction for messy text |
| Validation | Inventory / vendor / price tools (hard vs soft) |
| Approval | VP persona, $10k scrutiny, critique loop |
| Payment | `mock_payment` only after validate **and** approve |

**Hard fails** short-circuit to reject (no payment). **Soft flags** (EUR, price drift, urgency) escalate VP scrutiny.

## Design choices (short)

| Decision | Why |
|---|---|
| LangGraph | Explicit state, retry/critique edges, easy to test vs CrewAI/AutoGen |
| Parsers before Grok | JSON/CSV/XML stay deterministic; LLM for messy TXT/PDF only |
| Tools for stock/vendor | Money controls in code; model for judgment under uncertainty |
| Critique approve→reject only | Payment-safety bias; production would add a human queue |
| Heuristic fallback | Demos/CI work without credits; live Grok is the scoring path |

## Results

| Signal | Value |
|---|---|
| Sample suite STP | **8 / 16** approved + paid |
| Hard-stopped rejects | **8 / 16** (stock / fraud / unknown SKU / bad data) |
| Offline tests | **37 passed** |
| Live Grok | INV-1001 APPROVED + paid (~6–10s) |

| Invoice | Expected |
|---|---|
| INV-1001 / 1004 / 1006 / 1011 / 1015 | Approve → pay |
| INV-1002 | Reject — GadgetX over stock |
| INV-1003 | Reject — FakeItem / blocked vendor |
| INV-1008 / 1016 | Reject — unknown items |
| INV-1009 | Reject — negative qty / missing vendor |
| INV-1005 / 1007 / 1013 | Reject — aggregated over-stock |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `XAI_API_KEY` | _(empty)_ | xAI key (local `.env` only) |
| `XAI_MODEL` | `grok-3` | Grok model |
| `INVENTORY_DB_PATH` | `inventory.db` | SQLite path |
| `APPROVAL_AMOUNT_THRESHOLD` | `10000` | VP scrutiny threshold |
| `CONFIDENCE_THRESHOLD` | `0.7` | Extraction retry threshold |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Inventory database not found` | `python scripts/init_db.py --force` |
| `ModuleNotFoundError: acme_invoice` | `pip install -e .` in `.venv` |
| HTTP 401 / 403 from xAI | Fix key / add credits, or use `--heuristic` |
| Invoice path not found | Run from repo root: `data/invoices/...` |
