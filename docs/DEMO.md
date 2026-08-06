# 3-minute demo script

Use this when walking a reviewer through the repo.

## Prep (30s)

```bash
source .venv/bin/activate
python scripts/init_db.py --force
# .env has XAI_API_KEY set
```

## Script

### 1. Happy path — straight-through processing (~45s)

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
```

**Say:** Clean invoice, stock OK, under $10k → VP approves → mock payment with txn id. This is the minutes-not-days path.

### 2. Control failure — stock mismatch (~30s)

```bash
python main.py --invoice_path=data/invoices/invoice_1002.txt
```

**Say:** Requests 20× GadgetX, only 5 in inventory. Hard validation fail — never reaches payment. Deterministic tools, not LLM vibes.

### 3. Fraud path (~30s)

```bash
python main.py --invoice_path=data/invoices/invoice_1003.txt
```

**Say:** Blocked vendor + FakeItem + urgency language. Auto-reject with structured rationale. This is the leakage control story.

### 4. Ops UI (~45s)

```bash
streamlit run app.py
```

**Show:** Pick INV-1001 → Run pipeline → stage stepper + audit JSON download. Optionally run Batch suite for the full sample matrix.

## Optional closer

```bash
pytest -q
```

**Say:** 37 offline tests covering parsers, validation scenarios, approval critique, and graph e2e — no API required.
