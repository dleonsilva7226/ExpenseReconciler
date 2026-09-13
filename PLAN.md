# Project Jarvis: Personal OS & Automation Infrastructure
**Phase 1 Architecture & Technical Implementation Plan**

---

## 1. Executive Summary

Project Jarvis is an event-driven, decoupled personal assistant built on a micro-spoke pattern. The primary objective of Phase 1 is to deploy a low-friction **Finance Spoke** and an **Agent Core Engine** that handle passive transaction ingestion, automated credit utilization tracking, and proactive financial triage digests delivered via Telegram.

---

## 2. Technical Stack & Dependencies

* **Language & Runtime:** Python 3.12+
* **Framework:** FastAPI + Uvicorn (Async IO)
* **Database & ORM:** PostgreSQL + SQLAlchemy 2.0 (Async Engine) + `asyncpg`
* **Data Validation:** Pydantic v2
* **AI Orchestration:** OpenAI SDK (`gpt-4o-mini` for tool execution/ingest) + Gemini API (`gemini-1.5-flash` for high-context analytical triage)
* **Scheduler:** `APScheduler` (AsyncIOScheduler)
* **Messaging Interface:** Telegram Bot API
* **Infrastructure:** Docker Compose

---

## 3. Project File Structure

```text
jarvis/
├── app/
│   ├── main.py                     # App initialization & scheduler lifecycle
│   ├── config.py                   # Environment variables (Pydantic BaseSettings)
│   ├── database.py                 # Async SQLAlchemy engine & session factory
│   ├── gateway/
│   │   └── router.py               # Inbound Webhooks (Bank alerts & Telegram router)
│   ├── domains/
│   │   └── finance/
│   │       ├── models.py           # SQL Tables (CreditAccount, FinancialTransaction)
│   │       ├── schemas.py          # Pydantic models for webhook validation
│   │       └── service.py          # Transaction ingestion & ledger calculation logic
│   ├── agent/
│   │   ├── engine.py               # Tool execution loop & agent reasoning
│   │   └── tools.py                # Read-only SQL query tools for the Agent
│   └── jobs/
│       └── weekly_finance_audit.py # Cron task logic for Sunday Financial Triage
├── docker-compose.yml              # API & PostgreSQL container specification
└── requirements.txt