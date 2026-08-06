# Security

## API keys

- Store `XAI_API_KEY` only in a local **`.env`** file (never in source, README, tests, or screenshots).
- `.env` is listed in [`.gitignore`](../.gitignore). `.env.example` contains placeholders only.
- If a key was pasted into chat, email, or a ticket, **rotate it immediately** in the [xAI console](https://console.x.ai) and update local `.env`.
- Do not commit `inventory.db`, logs, or Streamlit secrets.

## Before pushing a new GitHub repo

```bash
# Confirm secrets are ignored
git status   # .env must NOT appear as an untracked file to add
rg -n 'xai-[A-Za-z0-9]{20,}' --glob '!.venv/**' --glob '!.env'   # should print nothing
```

## Runtime posture (prototype)

| Surface | Posture |
|---|---|
| Payment / banking | Mocked locally (`mock_payment`) |
| Inventory validation | Local SQLite only |
| Live Grok | Calls `api.x.ai` when key + credits present |
| Offline demos / CI | `--heuristic` avoids network use |

Related: [RUNBOOK.md](RUNBOOK.md) · [DEMO.md](DEMO.md)
