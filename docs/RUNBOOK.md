# Operator runbook

Failure modes and what to do. Prototype-oriented — not a production SRE playbook.

## Setup failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `Inventory database not found` | DB not initialized | `python scripts/init_db.py --force` |
| `Invoice not found` | Bad path / cwd | Run from repo root; use `data/invoices/...` |
| `Unsupported invoice format` | Wrong extension | Use `.txt .pdf .json .csv .xml` |
| `ModuleNotFoundError: acme_invoice` | Package not installed | `pip install -e .` inside `.venv` |

## LLM / API failures

| Symptom | Likely cause | Fix |
|---|---|---|
| HTTP 401 / invalid key | Bad or rotated key | Update `.env` → `XAI_API_KEY=...` |
| HTTP 403 / no credits | Team has no license | Add credits at console.x.ai **or** run with `--heuristic` |
| Slow extraction (>15s) | Model latency | Expected on live Grok; use `--heuristic` for demos if needed |
| Falls back silently to heuristic | Resilient client caught 401/403/timeout | Check logs for `Grok API unavailable`; restore credits for live scoring |
| Approval parse error on `risk_score` | Model returned value outside 0–1 | Client clamps/normalizes; upgrade package if still seen |

## Pipeline outcomes (how to read them)

| Final status | Meaning | Operator action |
|---|---|---|
| `APPROVED` + payment `success` | STP — paid via mock API | None in prototype |
| `REJECTED` after validation | Hard data/inventory/vendor failure | Fix master data or reject invoice |
| `REJECTED` after approval/critique | Policy / risk judgment | Manual AP review in a real system |
| Soft flags only (still approved) | e.g. EUR, price drift | VP scrutinized; audit rationale in stage log |

## Useful commands

```bash
# Offline demo (no network)
python main.py --invoice_path=data/invoices/invoice_1001.txt --heuristic

# Full suite summary
python main.py --invoice_path=data/invoices/ --batch --dedupe-pdf --heuristic

# Machine-readable audit
python main.py --invoice_path=data/invoices/invoice_1002.txt --output json

# Ops UI
streamlit run app.py

# Tests (always offline)
pytest -q
```

## Known prototype limits

- Does not ingest email or write back to ERP.
- Does not reserve/decrement stock after payment.
- Critique will not promote a reject to approve (by design).
- PDF text quality depends on `pdfplumber` extractability (no OCR engine).

Related: [DEMO.md](DEMO.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [SECURITY.md](SECURITY.md)
