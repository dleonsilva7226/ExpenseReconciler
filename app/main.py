"""FastAPI app initialization (D1).

No scheduler lifecycle here — per R4, the weekly digest job is
triggered externally (an outside cron service hitting an authenticated
endpoint, once A4/D6 exist), not run in-process via APScheduler.
`PLAN.md`'s original file-tree comment for this file ("scheduler
lifecycle") is stale relative to that decision.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.database import Base, engine
from app.gateway.router import router as gateway_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ASSUMPTION (flagged in status note): no migration tool (e.g.
    # Alembic) is spec'd yet, so schema setup happens here at startup
    # instead of via a separate migration step. Also enables pgcrypto
    # (A1's requirement) if it isn't already. Fine for a personal
    # project at this stage; revisit once a real migrations ticket
    # exists — this is not meant to be the permanent answer.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="ExpenseReconciler", lifespan=lifespan)

app.include_router(gateway_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
