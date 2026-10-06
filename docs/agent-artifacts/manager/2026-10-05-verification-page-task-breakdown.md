---
role: manager
status: approved
depends_on: [docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md]
supersedes: []
---

User confirmed the proposed refactor and explicitly requested implementation and a review PR. PR #21 is verified MERGED at 6060e6ac08e56a7165d3f6b05e27624866153fb2, now origin/main. Preserve existing onboarding artifacts and use the isolated checkout without a worktree.

Architect: produce focused A2a amendment replacing browser Basic Auth with Jarvis verification form and brief secure session, reusing existing admin credentials. Specify routes, cookie/session lifecycle, CSRF/same-origin protection, local versus production HTTPS behavior, and accessible verification/connect/success screens. Keep single-user setup, existing Plaid token encryption, Telegram priority and no dashboard/deploy/user registration. Avoid new operational secret requirements where a supported design can reuse existing credentials securely. Write spec for Manager review; no app edits.

Developer: only after amendment approved, implement it on a new feature branch from origin/main; preserve Telegram/weekly digest flow. Add focused meaningful checks and status note. No push/PR before QA handoff. No infrastructure edits, merging or deployment.

QA: independently verify login failures/success, cookie attributes, session expiry/tampering/logout, protected API and CSRF behavior, mocked Plaid linking, accessible page states and browser flow where available; add tests and actual report. Do not fix app code. Manager routes defects, reviews artifacts, commits relevant task files and opens one PR after checks. Exclude prior onboarding artifacts.
