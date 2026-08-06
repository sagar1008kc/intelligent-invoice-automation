# Demo

3-minute walkthrough for reviewers. Prep once, then show STP → stock fail → fraud → UI.

## Prep

```bash
source .venv/bin/activate
python scripts/init_db.py --force
# .env has XAI_API_KEY, or use --heuristic / Streamlit offline toggle
```

## 1. Happy path (STP)

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
```

Clean invoice, stock OK, under $10k → VP approves → mock payment with txn id.

![CLI approved INV-1001](assets/cli-approved-1001.png)

## 2. Stock mismatch

```bash
python main.py --invoice_path=data/invoices/invoice_1002.txt
```

20× GadgetX vs 5 in inventory → hard validation fail → never pays.

![UI reject — stock mismatch](assets/ui-reject-stock-mismatch.png)

## 3. Fraud path

```bash
python main.py --invoice_path=data/invoices/invoice_1003.txt
```

Blocked vendor + FakeItem + urgency language → auto-reject with rationale.

## 4. Streamlit UI

```bash
streamlit run app.py
```

- **Single invoice:** pick a sample → Run pipeline → stage stepper, VP rationale, txn id, audit JSON download.
- **Batch suite:** run all samples → STP vs rejects scoreboard.

![Agents working](assets/ui-agents-working.png)

![Approved + payment](assets/ui-approve-payment.png)

![Batch suite](assets/ui-batch-suite.png)

## 5. Tests (optional closer)

```bash
pytest -q
```

37 offline tests (parsers, validation, critique, graph e2e) — no API required.
