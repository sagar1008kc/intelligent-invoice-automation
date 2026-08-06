# Technical decisions

Staff-level tradeoffs for this prototype. Goal: ship a credible agentic AP MVP under ambiguity — not a framework tour.

## Orchestration: LangGraph (not CrewAI / AutoGen / pure custom)

| Option | Why considered | Why not (for this case) |
|---|---|---|
| **LangGraph** | Explicit state, conditional edges, retry/critique loops, easy to test | — **chosen** |
| CrewAI | Fast multi-agent personas | Harder to assert deterministic routing + audit stages |
| AutoGen | Strong chat patterns | Heavier conversational model than a staged AP pipeline needs |
| Custom FSM | Zero deps | Reinvents checkpointing/routing; worse signal for agentic sophistication |

**Decision:** LangGraph `StateGraph` with typed `InvoiceState` and stage logs. Reviewers can read the graph as the product contract.

## LLM: Grok via langchain-xai + resilient fallback

- Primary: `ChatXAI` / OpenAI-compatible xAI API for extraction + VP approval.
- Fallback: `HeuristicLLMClient` when no key, `--heuristic`, or 401/403/credit failures.
- Tests always inject the heuristic client — CI never depends on network or credits.

**Tradeoff accepted:** Heuristic mode is weaker than Grok on messy OCR; it keeps demos and pytest green. Live Grok is the scoring path.

## Extraction: parsers first, LLM second

| Format | Path |
|---|---|
| JSON / CSV / XML | Deterministic parsers → validation |
| TXT / PDF | Grok structured JSON + self-correction retry |

**Why:** LLM math and schema drift are expensive failure modes. Structured files should not burn tokens or invent fields. Invalid *business* data (negative qty, blank vendor) is intentionally left for validation — not “fixed” away by the model.

## Validation: tools over LLM judgment

Stock math, unknown SKUs, and blocked vendors are deterministic SQLite tool checks. Soft flags (price drift, EUR, urgency language) escalate to the VP agent instead of hard-stopping.

**Why:** FDEs put non-negotiable controls in code; use the model for judgment under uncertainty.

## Approval: rule priors + VP persona + one-way critique

1. Priors: amount threshold ($10k), hard/soft issue lists.
2. Grok VP returns decision + rationale + risk score (clamped to 0–1).
3. Critique may overturn `APPROVED → REJECTED` only (payment-safety bias).

**Why not bidirectional critique:** Overturning rejects to approvals in a prototype invites leakage. Production would add a human queue instead.

## Scope cuts (ruthless)

| Out | In |
|---|---|
| Real email ingest | Working local pipeline |
| ERP / banking rails | Observable decisions + audit JSON |
| Auth / cloud deploy | Fraud / stock controls |
| RAG over historical invoices | CLI + Streamlit demo surface |

Related: [ARCHITECTURE.md](ARCHITECTURE.md) · [BUSINESS_IMPACT.md](BUSINESS_IMPACT.md)
