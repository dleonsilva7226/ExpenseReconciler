# ExpenseReconciler

## Local development

This runs the API and a local Postgres via Docker Compose
(`docker-compose.yml`, DevOps ticket O1). It's for local iteration
only — production runs on Render + Neon (see `render.yaml`), which
this compose setup does not touch.

### Prerequisites

- Docker Desktop (or another Docker Engine) installed and running.
- `docker-compose` (bundled with Docker Desktop) or the `docker
  compose` plugin.

### 1. Create your local `.env`

```sh
cp .env.example .env
```

`app/config.py` requires every field in `.env.example` to be *present
and syntactically valid* for the app to start — but most of them don't
need to be *real* for a basic local smoke test, because the app
constructs the Plaid/OpenAI/Gemini/Telegram clients lazily (only when
those code paths actually run), not at startup. Concretely:

- **`DATABASE_URL`** — must be real. Point it at the `db` service this
  compose file brings up:
  ```
  DATABASE_URL=postgresql://localdev:localdev@db:5432/jarvis_local
  ```
  (`localdev`/`localdev`/`jarvis_local` matches `docker-compose.yml`'s
  `db` service exactly — these are throwaway local-only credentials,
  not real secrets.)
- **`TELEGRAM_ALLOWED_CHAT_ID`** — must be a real *integer* (Pydantic
  types this field as `int`), even though it doesn't need to be your
  actual Telegram chat ID to let the app start. The placeholder text
  in `.env.example` (`your-telegram-chat-id-here`) will fail startup
  validation — replace it with any numeric value, e.g. `0`.
- **`ADMIN_USERNAME`/`ADMIN_PASSWORD`** — any values work; these gate
  the `/link-account` admin UI via HTTP Basic Auth, not an external
  service.
- **`TOKEN_ENCRYPTION_KEY`**, **`TELEGRAM_WEBHOOK_SECRET_TOKEN`**,
  **`JOBS_TRIGGER_SECRET`** — any non-empty string works to let the
  app start; the app doesn't validate these against anything external.
  Use real generated values (`openssl rand -base64 32` /
  `openssl rand -hex 32`) if you plan to actually exercise pgcrypto
  encryption or hit the webhook/job-trigger endpoints with a matching
  header.
- **`PLAID_CLIENT_ID`/`PLAID_SECRET`**, **`TELEGRAM_BOT_TOKEN`**,
  **`OPENAI_API_KEY`**, **`GEMINI_API_KEY`** — placeholder text is
  fine for the server to *start* and for non-Plaid/non-agent endpoints
  (e.g. `/health`) to work. They only need real values once you
  actually exercise the code paths that use them: linking a real bank
  account (`/link-account`, Plaid sandbox credentials), receiving/
  sending real Telegram messages, or running an agent/digest query
  (OpenAI/Gemini keys).

### 2. Bring the stack up

```sh
docker-compose up --build
```

This builds the `api` image from the repo's `Dockerfile` and starts
it alongside a `postgres:16` container (`db`), waiting for `db`'s
health check before starting `api`.

There is no separate migration step — `app/main.py`'s startup
(`lifespan`) runs `CREATE EXTENSION IF NOT EXISTS pgcrypto` and
`Base.metadata.create_all` against `DATABASE_URL` automatically. No
Alembic/migrations exist in this repo yet.

### 3. Hit it

```sh
curl http://localhost:8000/health
# {"status":"ok"}
```

That endpoint has no dependencies beyond a running app process, so
it's the right first check that the stack came up correctly. The
admin UI is at `http://localhost:8000/link-account` (HTTP Basic Auth,
`ADMIN_USERNAME`/`ADMIN_PASSWORD` from your `.env`) — linking an
actual account through it needs real Plaid sandbox credentials.

### 4. Bring it down / reset the local DB

```sh
docker-compose down          # stop containers, keep the DB volume
docker-compose down -v       # stop containers AND delete the local DB volume
```

Use `-v` if you want a clean database on the next `docker-compose up`
(e.g. after a schema change, since there's no migration/rollback tool
yet).