# Business impact

## Current-state pain (Acme Corp)

PE-backed manufacturing. AP is a working-capital drag:

| Signal | Today | Cost narrative |
|---|---|---|
| Error rate | ~30% | Rework, duplicate/missed payments, vendor disputes |
| Cycle time | ~5 days | Email-chain VP approvals; delayed close |
| Fraud / rush pressure | Ad hoc human judgment | Wire urgency + fake SKUs slip through |
| Annual leakage (stated) | ~$2M | Manual process tax on the PE hold period |

## Prototype value proposition

Compress inbox → decision → payment simulation into minutes for clean invoices, and **hard-stop** leakage cases before cash moves.

| Pain | Control in this system | Observable evidence |
|---|---|---|
| Extraction errors | Structured parsers + Grok self-correction | Confidence, anomalies, stage timings |
| Inventory mismatches | SQLite tools before approval | `stock_mismatch`, `unknown_item`, `out_of_stock` |
| Fraud / fake SKUs | Blocked vendors + suspicious items | Auto-reject; no payment call |
| Slow approvals | Grok VP + $10k critique loop | Rationale + risk score in audit log |
| Payment leakage | Dual gate: validate **and** approve | Mock txn id only on `APPROVED` |

## Observed prototype results (sample suite)

Offline heuristic batch on the Galatiq fixtures (`--batch --dedupe-pdf`):

| Metric | Result |
|---|---|
| Invoices processed | 16 |
| Straight-through (APPROVED + paid) | **8 / 16 (50%)** |
| Hard-stopped rejects | **8 / 16** (stock, fraud, unknown SKU, bad data) |
| Automated tests | **37 passed** (no network) |
| Live Grok smoke (INV-1001) | APPROVED + payment in ~6–10s wall time |

STP examples: INV-1001, 1004, 1006, 1010, 1011, 1012, 1014, 1015.  
Reject examples: INV-1002 (overstock), 1003 (fraud), 1008/1016 (unknown items), 1009 (integrity).

Live UI and CLI captures: [DEMO.md](DEMO.md).

## Pilot framing for PE / finance stakeholders

Directional — not audited ROI:

1. **Working capital:** clean invoices clear same day → fewer days payable outstanding surprises from process delay.
2. **Exception-based AP:** humans only touch hard fails + high-risk rejects; STP absorbs the easy half.
3. **Control narrative:** every decision has a stage audit (tool calls, VP rationale, critique). Auditable > tribal email chains.
4. **Expansion path:** email ingest → ERP PO match → human queue → real bank rails (see assumptions below).

## Why multi-agent (exec version)

One mega-prompt cannot own extraction *and* stock math *and* policy judgment safely. Split agents: models reason where judgment is needed; tools enforce where money and inventory are non-negotiable.

## Assumptions & next 30 days

**Assumptions baked into the MVP**

- Inventory master data can be represented in SQLite (or swapped for a real DB later).
- VP policy is expressible as threshold + soft-risk flags + LLM judgment.
- Mock payment is acceptable proof; production needs idempotent banking + reconciliation.

**If this landed inside Acme next month**

| Week | Focus |
|---|---|
| 1 | Email/share-drive ingest + invoice idempotency keys |
| 2 | PO / three-way match against ERP stub; human-in-the-loop queue UI |
| 3 | Decrement/reserve stock; duplicate-invoice detection |
| 4 | Audit export to finance lake; shadow-mode parallel run vs manual AP |

Ruthless non-goals for *this* repo: cloud deploy, SSO, real bank APIs, model fine-tuning.
