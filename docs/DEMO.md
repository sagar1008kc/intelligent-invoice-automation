# Demo guide

3-minute reviewer walkthrough with CLI and Streamlit screenshots from a live run.

## Prep (30s)

```bash
source .venv/bin/activate
python scripts/init_db.py --force
# .env has XAI_API_KEY set (or use --heuristic / UI toggle)
```

---

## 1. Happy path — straight-through processing (~45s)

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
```

**Talking point:** Clean invoice, stock OK, under $10k → VP approves → mock payment with txn id. Minutes, not days.

![CLI approved INV-1001](assets/cli-approved-1001.png)

---

## 2. Control failure — stock mismatch (~30s)

```bash
python main.py --invoice_path=data/invoices/invoice_1002.txt
```

**Talking point:** Requests 20× GadgetX, only 5 in inventory. Hard validation fail — never reaches payment. Deterministic tools, not LLM vibes.

![UI reject — stock mismatch on INV-1002](assets/ui-reject-stock-mismatch.png)

---

## 3. Fraud path (~30s)

```bash
python main.py --invoice_path=data/invoices/invoice_1003.txt
```

**Talking point:** Blocked vendor + FakeItem + urgency language. Auto-reject with structured rationale. This is the leakage-control story.

---

## 4. Soft flags / currency review (~30s)

```bash
python main.py --invoice_path=data/invoices/invoice_1014.xml
```

**Talking point:** Validation can pass while soft flags (e.g. non-USD) escalate scrutiny. VP + critique decide; payment stays gated.

![CLI rejected INV-1014 with soft flags](assets/cli-rejected-1014.png)

---

## 5. Ops UI — single invoice (~45s)

```bash
streamlit run app.py
```

1. Leave **Offline heuristic LLM** off for live Grok (or on for offline demos).
2. **Single invoice** → sample `invoice_1015.csv` → **Run pipeline**.
3. Show stage stepper, metrics, VP rationale, txn id, and **Download audit JSON**.

![Agents working](assets/ui-agents-working.png)

![Approved + payment on INV-1015](assets/ui-approve-payment.png)

---

## 6. Ops UI — batch suite (~30s)

1. Open **Batch suite**.
2. Keep **Skip PDF when TXT twin exists** checked.
3. **Run batch suite** → score STP vs hard-stopped rejects → **Download batch results**.

![Batch suite results](assets/ui-batch-suite.png)

---

## 7. Optional closer — tests

```bash
pytest -q
```

**Talking point:** Offline tests cover parsers, validation scenarios, approval critique, and graph e2e — no API required.

Payment success lines from a batch/demo session:

![CLI payment success logs](assets/cli-payment-logs.png)

---

## Screenshot index

| Asset | What it shows |
|---|---|
| `assets/cli-approved-1001.png` | CLI happy path — APPROVED + payment |
| `assets/ui-reject-stock-mismatch.png` | Streamlit reject — GadgetX over stock |
| `assets/ui-agents-working.png` | Streamlit spinner while agents run |
| `assets/ui-approve-payment.png` | Streamlit approve + txn id |
| `assets/ui-batch-suite.png` | Full sample suite scoreboard |
| `assets/cli-rejected-1014.png` | Soft-flag / currency scrutiny path |
| `assets/cli-payment-logs.png` | Mock payment confirmations |

See also: [RUNBOOK.md](RUNBOOK.md) · [BUSINESS_IMPACT.md](BUSINESS_IMPACT.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
