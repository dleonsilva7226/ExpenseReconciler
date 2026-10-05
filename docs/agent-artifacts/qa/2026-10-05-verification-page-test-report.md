---
role: qa
status: in-review
depends_on: [docs/agent-artifacts/manager/2026-10-05-verification-page-qa-handoff.md, docs/agent-artifacts/architect/2026-10-05-verification-page-session-spec.md, docs/agent-artifacts/developer/2026-10-05-verification-page-status.md]
supersedes: []
---

Independent QA completed against Developer commit `3884f9a` on `dev/verification-page`, based on merged PR #21. No blocking defects found. No application files, dependencies, manifests, environment bindings, infrastructure, branch, or commits were changed by QA. No live integrations or deployment were used.

## Actual results

- Full suite in the isolated browser-capable runner: **207 passed**, including **11 actual Chromium browser tests** and **12 new independent backend tests**. No browser tests skipped in this run. Existing 184 tests include Telegram/agent mocked flow and weekly digest regressions.
- `ruff check .`, `git diff --check`, and `node --check app/gateway/static/link_account.js`: passed.
- Existing warnings only: deprecated Google Gemini SDK and Starlette's 422 constant.

Exact full-suite command:

```bash
PYTHONPATH=/workspace/cloud-setup/venv/lib/python3.12/site-packages \
  /workspace/verification-qa-runner/bin/python -m pytest -q
/workspace/cloud-setup/venv/bin/ruff check .
git diff --check
node --check app/gateway/static/link_account.js
```

Playwright 1.63.0 was installed in `/workspace/verification-qa-runner` with uv's writable workspace cache; browser executable was `/usr/bin/chromium`. The app requirements are unchanged. `test_verification_browser_qa.py` uses `pytest.importorskip`: a standard environment without optional Playwright skips that module. The reported **207 executed passes** are from the browser-capable runner, not a standard run with browser checks skipped; the browser subset was also actually run separately (**11 passed**). Standard-run backend count is 196 tests, with browser module optional; no duplicate full standard run was necessary.

The first expiry test attempt used a millisecond integer in Playwright's seconds-based clock API and immediately simulated a distant future. QA corrected the runner to use an explicit UTC datetime, then reran the browser subset and the full suite. This was a harness error, not an application defect. No assertion was weakened and no app code was patched.

## Behavior verified

The browser harness starts and stops only its own ephemeral loopback Uvicorn server with lifespan disabled. It serves the real app routes and actual HTML/CSS/JavaScript. Actual HTTP verification, cookie storage, session status, Origin/CSRF guards, token endpoint, callback route and encrypted transaction construction execute. Only the Plaid CDN/SDK/provider and database session boundary are mocked. The mock Link SDK records opening/destruction and invokes real application callbacks.

- Public page/assets, literal asset serving, no Basic challenge, no-store and no-referrer; protected endpoints reject Basic-only access.
- Session signing/domain-separated HMAC, non-ASCII credential checking, all required claims, incorrect signature/algorithm/purpose, expired/future/modified sessions, strict timestamp type/lifetime, credential rotation, invalid-cookie deletion, secure transport and spoofed forwarded-header denial. Existing Developer security tests independently executed without changes.
- Fresh CSRF after re-verification rejects the previous CSRF; exact normalized hostname/default-port comparison accepts equivalent default authority and denies the wrong port. Logout deliberately clears this browser cookie without claiming global stateless token revocation.
- Added callback/logout guard tests prove invalid Origin, wrong CSRF, cross-site request metadata and non-JSON bodies cannot reach provider, database or cookie-deletion effects.
- Added second-account insert failure verifies rollback, no commit and no success; both attempted inserts use pgcrypto. Empty account list cannot exchange a token. Existing provider/commit failure and metadata tests pass.
- Real browser Enter submission, incorrect details, retained username, cleared password, error focus, successful verification and heading focus; valid session resumes on reload. Cookie is HttpOnly, path-restricted and SameSite=Lax; browser JavaScript cannot read it; local/session storage remain empty.
- Lazy SDK loading only on Connect; SDK failure is retryable; no automatic Link opening. Link cancellation and provider failure are safe, actionable and release the disabled button/destroy handlers.
- Real browser success sends two mock Plaid account metadata records through the actual protected callback route, constructs two encrypted inserts, commits before confirmation, then offers another connection. A failed callback cannot show success.
- Protected 401 returns to verification; 403 offers re-verification; token/provider failure stays retryable. Logout failure preserves the session and never claims sign-out.
- Simulated expiry while a callback is pending destroys the active handler and returns to verification; completing that stale callback cannot restore the success panel. No callback/public token replay occurs.
- Desktop 1280×900 and mobile 320/390px checked: one h1, associated Username/Password labels, polite live status, keyboard order, hidden panels excluded from interaction, visible focus, minimum 44px touch targets, no horizontal overflow. No application JavaScript page errors.

## Screenshots and Manager review

Clean empty-field screenshots were captured outside the checkout (no credentials shown):

- `/workspace/verification-qa-artifacts/verify-desktop.png`
- `/workspace/verification-qa-artifacts/verify-mobile.png`
- `/workspace/verification-qa-artifacts/connect-desktop.png`
- `/workspace/verification-qa-artifacts/connect-mobile.png`

Manager reviewed verification desktop/mobile appearance and approved the clear polished layout, readable steps and comfortable inputs. Screenshots and QA runner artifacts are local verification aids, not app dependencies or repository-generated outputs.

## Scope limits and recommendation

Ready for Manager review and a PR. Tests establish the mocked workflow and security boundaries, not live Plaid connectivity, real bank persistence, production trusted-proxy/TLS configuration, or real Telegram delivery. No new credentials requested. Merge/deployment and dashboard remain outside this ticket.
