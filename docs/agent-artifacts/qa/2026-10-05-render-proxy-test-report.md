---
role: qa
status: in-review
depends_on: [docs/agent-artifacts/manager/2026-10-05-render-proxy-review-handoff.md, docs/agent-artifacts/devops/2026-10-05-render-proxy-infra-note.md, docs/agent-artifacts/developer/2026-10-05-verification-page-status.md]
supersedes: []
---

# PR #22 Render proxy regression validation

Independent QA validated the DevOps trusted-proxy correction on
`dev/verification-page`. No blocking defects found. QA changed only the focused
test file `tests/gateway/test_render_proxy_qa.py` and this report. No application,
infra, dependency, credential, branch, commit, push, merge or deployment changes
were made by QA. Unrelated onboarding artifacts remain untouched.

## Actual results

- Focused proxy regression: **5 passed**.
- Full browser-capable suite: **212 passed**, including all **11 Chromium
  browser tests**, with no skips. This is the prior 207 tests plus 5 new proxy
  tests.
- `ruff check .`, `git diff --check`, and JavaScript syntax check passed.
- Existing warnings only: deprecated Gemini SDK and Starlette's 422 constant.

Commands actually run from `/workspace/ExpenseReconciler`:

```bash
PYTHONPATH=/workspace/cloud-setup/venv/lib/python3.12/site-packages \
  /workspace/verification-qa-runner/bin/python -m pytest -q tests/gateway/test_render_proxy_qa.py
PYTHONPATH=/workspace/cloud-setup/venv/lib/python3.12/site-packages \
  /workspace/verification-qa-runner/bin/python -m pytest -q
/workspace/cloud-setup/venv/bin/ruff check .
git diff --check
node --check app/gateway/static/link_account.js
```

## Regression evidence

The new tests read the actual `Dockerfile` CMD and `render.yaml` scalar
environment configuration, then construct real Uvicorn `Config` (installed
version 0.54.0). The Blueprint trust value is supplied through
`FORWARDED_ALLOW_IPS`; the Docker command's proxy-header flag controls Config's
proxy middleware. `Config.load()` supplies the actual Uvicorn proxy wrapper.
App lifespan is disabled to avoid a live database connection; all real browser
routes, verification logic and guards execute. Only the Plaid token provider is
mocked.

TestClient starts every request with an **HTTP** URL and a non-loopback socket
peer (`10.42.0.8`). An observation hook immediately inside Uvicorn's wrapper
records the scheme the application actually receives. No HTTPS TestClient base
URL or application-level forwarded-header override bypasses this regression.

- The actual Render environment makes forwarded HTTPS visible as HTTPS for
  session status, login, authenticated status and protected Plaid token creation.
  Login creates a Secure session cookie. The harness explicitly sends the
  resulting Cookie header because a real HTTPS browser sends it to Render,
  whereas its modeled internal HTTP hop would not resend a Secure cookie
  automatically. Matching HTTPS Origin and fresh CSRF allow exactly one mock
  Plaid call.
- Removing the Render override reproduces the original defect: the same
  non-loopback peer's forwarded HTTPS stays HTTP under Uvicorn's default trust.
  Session status, login and protected token creation all return 403 before any
  provider call or session-cookie mutation, even with a valid signed session.
- Trusted forwarded HTTP likewise stays HTTP and receives the same denials.
- Correct proxy trust and forwarded HTTPS still reject an incorrect Origin or
  CSRF token with 403 and no provider call.

## Limits and recommendation

Ready for Manager review. This validates the configured Uvicorn/application
integration in the intended proxy scenario; it does not establish the live
Render ingress boundary or a deployed bank connection. Render's free-service
wildcard trust assumption and the required reassessment before paid/private
ingress are documented by DevOps. No Docker image build or live deployment was
performed. Production HTTPS, session and Origin/CSRF application guards remain
unchanged.
