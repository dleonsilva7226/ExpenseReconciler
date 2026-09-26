---
role: researcher
status: draft
depends_on: []
supersedes: []
---

# Findings: Currency Data Types in PostgreSQL

**Task:** dry-run test artifact per
`docs/agent-artifacts/manager/2026-09-13-pipeline-dry-run.md`. Content
below is a genuine but non-exhaustive summary for pipeline-testing
purposes, not a vetted recommendation for production use.

## Question

What data type(s) should PostgreSQL use to store monetary amounts, and
what are the tradeoffs relevant to a finance-tracking application?

## Options considered

### 1. `NUMERIC(p,s)` / `DECIMAL(p,s)`
- Arbitrary-precision, exact decimal arithmetic — no floating-point
  rounding error.
- Common convention: `NUMERIC(19,4)` — supports large balances with 4
  decimal places, enough headroom for currencies with sub-cent
  precision or intermediate FX calculations.
- Slightly more storage and CPU cost than native integer/float types,
  but negligible at typical transaction-table scale.
- Requires the application layer to track the currency's minor-unit
  count itself (not all currencies have 2 decimal places — e.g. JPY
  has 0, BHD has 3).

### 2. `MONEY`
- Native PostgreSQL type, fixed fractional precision tied to the
  server's `lc_monetary` locale setting at the time of formatting.
- Generally discouraged for application use: precision is
  locale-dependent, rounding behavior on division is surprising, and
  it doesn't handle multi-currency data (no embedded currency code).
- Faster/smaller than `NUMERIC` but the correctness tradeoffs usually
  outweigh the performance gain for financial ledgers.

### 3. Integer minor units (`BIGINT` storing cents/minor units)
- Exact, fast, simple comparisons — avoids decimal type entirely.
- Common in payment-processing systems (e.g. Stripe stores amounts as
  integer cents).
- Requires consistent convention across the codebase for how many
  minor units per currency, and conversion at every input/output
  boundary (API, display, reports).

### 4. Floating point (`FLOAT`, `DOUBLE PRECISION`)
- Not suitable for currency — binary floating point cannot represent
  most decimal fractions exactly, leading to cumulative rounding
  errors. Not recommended for any monetary column.

## Currency code storage

Regardless of the numeric type chosen, multi-currency support requires
a companion column for the currency itself — typically a `CHAR(3)`
or `VARCHAR(3)` storing an ISO 4217 code (e.g. `USD`, `EUR`), often
paired with a `CHECK` constraint or lookup table to constrain valid
values.

## Recommendation (non-binding)

For a project doing transaction ingestion and reconciliation across
possibly-multiple currencies, `NUMERIC(19,4)` for the amount column
plus a separate ISO 4217 `currency_code` column is the most common,
well-understood pattern, and avoids `MONEY`'s locale-dependent
behavior. Final decision belongs to the Architect role.

## Sources

- PostgreSQL documentation: Numeric Types (`numeric`, `money`).
- Common industry practice (e.g. Stripe API amount-in-minor-units
  convention) as a point of comparison, not a binding source for this
  project's schema.
