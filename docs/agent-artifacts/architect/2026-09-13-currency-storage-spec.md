---
role: architect
status: superseded
depends_on: [docs/agent-artifacts/researcher/2026-09-13-postgres-currency-data-types.md]
supersedes: []
---

**Superseded by `docs/agent-artifacts/architect/2026-09-20-finance-schema-spec.md` (A1), 2026-09-20.**

# Spec (dry run): Currency Storage for Financial Transactions

**Task:** dry-run test artifact per
`docs/agent-artifacts/manager/2026-09-13-pipeline-dry-run.md`. This is
a pipeline test, not an approved design — no implementation should be
started from this artifact without a real Manager-approved task.

## Input

Researcher findings at
`docs/agent-artifacts/researcher/2026-09-13-postgres-currency-data-types.md`
evaluated `NUMERIC`, `MONEY`, integer-minor-units, and floating point
for storing monetary amounts in PostgreSQL, and recommended
`NUMERIC(19,4)` plus a separate ISO 4217 currency code column.

## Summary of decision

Adopting the Researcher's recommendation for the purposes of this
dry run: monetary amounts are modeled as `NUMERIC(19,4)`, currency as
a 3-character ISO 4217 code, rejecting `MONEY` (locale-dependent,
no multi-currency support) and floating point (rounding error) as
documented in the source findings.

## Data model implications (illustrative — `app/domains/finance/models.py`)

```python
amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
```

- `amount` uses Python's `Decimal` at the SQLAlchemy/Pydantic layer to
  preserve precision end-to-end (avoid casting through `float`).
- `currency_code` constrained via `CHECK (currency_code ~ '^[A-Z]{3}$')`
  or a lookup table, per the Researcher's note on ISO 4217.

## Open questions (would block real implementation)

1. Does this project need to store amounts in more than one currency
   per transaction (e.g. original + converted), which would require a
   second amount/currency pair or a separate FX-rate table?
2. What minor-unit precision do the target banks'/cards' webhook
   payloads actually report at ingestion — does 4 decimal places match
   source data, or is 2 sufficient and `NUMERIC(19,4)` over-provisioned?

These would need a follow-up Researcher task before this spec could
move from `draft` to `approved` in a real (non-dry-run) task.

## Requires User Approval

None — this is a dry-run artifact only; no schema migration, code, or
infra change is authorized by it.
