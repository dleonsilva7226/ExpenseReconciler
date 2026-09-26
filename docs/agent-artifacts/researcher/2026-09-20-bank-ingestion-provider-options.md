---
role: researcher
status: draft
depends_on: []
supersedes: []
---

# Findings: Bank Transaction Ingestion — Provider Options (R1)

**Task:** resolves the open question flagged in
`docs/agent-artifacts/manager/2026-09-20-project-completion-tickets.md`
(ticket R1). User context: currently banks with Chase and Capital One,
also uses Rocket Money as a consumer budgeting app. Wants Chase
supported first, with the architecture able to add other banks later
without hardcoding.

## Question

How should this project pull transaction data out of a bank like
Chase, in a way that doesn't lock the architecture to Chase
specifically?

## Option 1: Chase's own direct developer API

Chase runs a Developer Portal (`developer.chase.com`) exposing an
FDX-aligned "Account Data Sharing API" — account profiles, balances,
transactions, statements, via OAuth 2.0 with FDX consent flows, using
tokenized account numbers instead of real ones.

**Catch:** this API is for parties with "an existing partnership with
Chase" — it's built for fintechs that go through a formal
onboarding/partnership process with Chase, not something a solo
developer can self-serve register for and start calling. Not
practical as the direct integration path for a personal project.

Building against Chase's API directly would also mean repeating that
partnership process, and a separate bespoke integration, for every
additional bank (Capital One, etc.) — the opposite of what was asked
for.

## Option 2: A bank-data aggregator (Plaid / Finicity / MX)

These sit between the app and the banks: the app integrates once
against the aggregator's API, and the aggregator handles the
per-institution connections (including Chase's and Capital One's own
FDX-aligned APIs where available, falling back to other connection
methods elsewhere), returning transaction data in one normalized
format regardless of which bank it came from.

- **Plaid** — broadest US coverage, explicitly includes Chase, Capital
  One, Bank of America, Wells Fargo, Citibank, and thousands of
  smaller institutions/credit unions. As of April 2026, Plaid offers a
  **free Trial plan** for new developer teams: real production data,
  up to 10 linked "Items" (roughly, up to 10 linked accounts/banks),
  including Transactions, Auth, Balance, and other products bundled
  in. That easily covers "Chase now, Capital One later" for a personal
  project at zero cost.
- **Finicity** (Mastercard) — has direct connections to Chase, Bank of
  America, Wells Fargo, Capital One too; historically strongest for
  lending/income-verification use cases, less relevant here.
- **MX** — strong for credit unions/community banks, slightly narrower
  big-bank coverage than Plaid, no evidence of a comparable no-cost
  hobbyist tier.

For this project's shape (personal use, 2-3 banks, no lending/KYC
use case), **Plaid is the standout option**, largely because of the
free hobbyist-tier fit — the other two don't change the architectural
conclusion, just the vendor.

## Option 3: Rocket Money as a data source

Rocket Money is a consumer-facing budgeting/subscription-tracking app
— it is itself built on top of an aggregator (not a bank), and it does
not expose a public API for third-party apps to pull a user's own
transaction data back out. It isn't a viable ingestion source for this
project; it's a separate tool the user happens to also use, not
infrastructure to build on. (Mentioning explicitly since it was in
scope of the question — ruling it out, not recommending it.)

## Relevant regulatory context

Section 1033 of Dodd-Frank ("open banking rule") would eventually
require banks to provide standardized, free consumer data-access APIs
directly. As of September 2026 it is **finalized but enjoined by a
federal court and under active reconsideration/rewrite by the CFPB** —
not currently in force, and its eventual shape (including whether
banks can charge for access) is unsettled. This is a reason *not* to
architect around banks' direct APIs as a near-term default even where
they nominally exist (like Chase's) — the aggregator layer is the
stable near-term choice, and would also be positioned to absorb
whatever the 1033 rule eventually requires, since aggregators like
Plaid already integrate directly with banks' FDX APIs where available.

## Recommendation (non-binding — decision belongs to Architect/you)

1. Use **Plaid** as the ingestion provider, on its free Trial tier.
2. Architecturally, treat "Plaid" itself as one interchangeable
   implementation behind a small **provider interface** (e.g. a
   `BankConnector` abstraction with a `fetch_transactions(account_id)`
   shape), rather than importing Plaid's SDK/types directly into
   `app/domains/finance/service.py`. This satisfies the "not hardcoded"
   goal at two levels:
   - **Per-bank:** Plaid already normalizes Chase vs. Capital One vs.
     any other institution into one transaction schema — adding
     Capital One later is a config/linking step, not new code.
   - **Per-provider:** if Plaid's terms, pricing, or coverage ever stop
     fitting (e.g. exceeding the 10-Item free cap), swapping to
     Finicity/MX later only requires a new implementation of the same
     `BankConnector` interface, not a rewrite of ingestion/service
     logic.
3. This should be formalized as part of Architect ticket **A2**
   (webhook/ingestion contract) — this findings doc unblocks A2, which
   was previously blocked on R1.

## Sources

- [Chase Developer](https://developer.chase.com/)
- [Chase Developer — Account and Customer Information API guide](https://developer.chase.com/products/aggregation-fdx/guides/using-the-account-and-customer-information-api/)
- [Account Data Sharing API Demo | Chase Developer](https://apidemo.chase.com/)
- [Chase — Security Center / data sharing](https://www.chase.com/digital/data-sharing)
- [Banking Data Aggregation APIs (2026): Compare Plaid, Finicity, MX](https://www.openbankingtracker.com/banking-data-aggregation)
- [Plaid vs MX vs Finicity: Banking API Comparison](https://phoenixstrategy.group/blog/plaid-vs-mx-vs-finicity-banking-api-comparison)
- [Plaid vs MX vs Finicity: Which US Open Banking API Should You Integrate?](https://www.fintegrationfs.com/post/plaid-vs-mx-vs-finicity-which-us-open-banking-api-should-you-integrate)
- [Can I use Plaid for free? – Plaid Customer Help Center](https://support.plaid.com/hc/en-us/articles/16194695660311-Can-I-use-Plaid-for-free)
- [Pricing - United States & Canada | Plaid](https://plaid.com/pricing/)
- [Section 1033 Status & Timeline (2026): Is the Open Banking Rule in Effect?](https://openbankingtracker.com/guides/section-1033-status)
- [Cozen O'Connor: Section 1033 Compliance Date: Open Banking Rule Enjoined and Under Reconsideration](https://www.cozen.com/news-resources/publications/2026/section-1033-compliance-date-open-banking-rule-enjoined-and-under-reconsideration)
