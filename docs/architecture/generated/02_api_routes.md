<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# API Routes

15 routes from the live FastAPI app (`app/main.py` → `app/api/router.py`), enumerated via the OpenAPI schema. Auth is derived structurally — public routers are health + webhooks; every other route is under the `get_current_user`-gated protected sub-router.

| Method | Path | Auth | Tags |
|---|---|---|---|
| `GET` | `/api/_auth/whoami` | 🔒 auth | auth |
| `GET` | `/api/approvals/pending` | 🔒 auth | approvals |
| `POST` | `/api/approvals/{approval_id}/decide` | 🔒 auth | approvals |
| `POST` | `/api/chat` | 🔒 auth | chat |
| `POST` | `/api/chat/stream` | 🔒 auth | chat |
| `GET` | `/api/costs` | 🔒 auth | costs |
| `GET` | `/api/costs/history` | 🔒 auth | costs |
| `GET` | `/api/documents/search` | 🔒 auth | documents |
| `POST` | `/api/documents/upload` | 🔒 auth | documents |
| `GET` | `/api/health` | public | health |
| `GET` | `/api/memory/profile` | 🔒 auth | memory |
| `GET` | `/api/memory/search` | 🔒 auth | memory |
| `POST` | `/api/voice/stream` | 🔒 auth | voice |
| `POST` | `/api/webhooks/gmail` | public | webhooks |
| `POST` | `/api/webhooks/telegram` | public | webhooks |
