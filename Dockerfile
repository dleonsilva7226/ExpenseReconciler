# ExpenseReconciler — Render web service image (O1a).
#
# Chosen over Render's native Python buildpack so the exact Python
# version and runtime match CI (.github/workflows/ci.yml pins 3.12)
# and local dev, rather than depending on Render's buildpack picking
# up a `runtime.txt`/`PYTHON_VERSION` env var correctly. See the O1a
# infra-note (docs/agent-artifacts/devops/2026-09-27-render-neon-deploy-config.md)
# for the full reasoning.
#
# NOT verified with an actual `docker build` in this sandbox (no
# Docker available) — syntax-checked by hand only. See the infra-note
# for what was and wasn't verified.

FROM python:3.12-slim

WORKDIR /app

# requirements.txt's runtime deps (asyncpg, psycopg2-binary,
# cryptography, plaid-python, python-telegram-bot, openai,
# google-generativeai, ...) all ship manylinux wheels for this base
# image's architecture/Python version as of writing, so no apt-get
# build toolchain should be needed. If a future dependency addition
# breaks that assumption (pip falls back to a source build and fails),
# add `build-essential` here — flagging the possibility rather than
# installing it speculatively.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Render injects $PORT at runtime and routes traffic to it; default
# 8000 here only matters for a local `docker run` without Render's
# env. Do not hardcode a port in code — app/main.py has no port
# knowledge, this is purely a process-start concern.
ENV PORT=8000
EXPOSE 8000

# No migration step here: app/main.py's `lifespan` already runs
# `CREATE EXTENSION IF NOT EXISTS pgcrypto` + `Base.metadata.create_all`
# at startup (see app/main.py's own comment on why — no Alembic yet).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
