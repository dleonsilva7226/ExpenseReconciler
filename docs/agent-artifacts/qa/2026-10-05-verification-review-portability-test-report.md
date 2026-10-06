---
role: qa
status: in-review
depends_on: [docs/agent-artifacts/manager/2026-10-05-verification-review-followup.md, docs/agent-artifacts/architect/2026-10-05-verification-page-session-spec.md]
supersedes: []
---

## Scope and changes

PR #22 review thread `discussion_r4187889998` identifies a real portability issue:
the screenshot test wrote to a cloud-container-only absolute path. QA updated
`tests/gateway/test_verification_browser_qa.py` on `dev/verification-page` at
base commit `ee00f7220d8e876c41f294ea6e000057d793eb1a` to create screenshots in
pytest's per-test `tmp_path / "verification-screenshots"` directory. Existing
desktop/mobile layout, keyboard focus and real-browser workflow assertions remain
intact. The same browser test now reads each of the four actual output files and
checks its PNG signature; no mocked filesystem or path-only test was added.

The adjacent hardcoded `/usr/bin/chromium` launch path was also removed. The
optional runner accepts `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`, otherwise discovers
Chromium/Chrome on PATH, otherwise leaves the executable unset so Playwright uses
its managed Chromium. This adds no application or repository dependency.

## Actual verification

- All **11 existing Chromium tests passed**, with system browser autodetection.
  No tests in the browser subset skipped. Duration: 17.83 seconds.
- The actual screenshot/layout test passed again with the explicit browser
  override: **1 passed**, 3.03 seconds. This verifies the supported override
  against a real browser, rather than mocking the launcher.
- `ruff check .`: all checks passed.
- `git diff --check`: passed.
- Both browser invocations emitted the existing Gemini SDK deprecation warning.
  No application defect was found.

Commands executed from the repository:

```bash
PYTHONPATH=/workspace/cloud-setup/venv/lib/python3.12/site-packages \
  /workspace/verification-qa-runner/bin/python -m pytest -q \
  tests/gateway/test_verification_browser_qa.py \
  --basetemp=/tmp/expense-review-browser-qa
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium \
  PYTHONPATH=/workspace/cloud-setup/venv/lib/python3.12/site-packages \
  /workspace/verification-qa-runner/bin/python -m pytest -q \
  tests/gateway/test_verification_browser_qa.py::test_mobile_layout_accessible_focus_and_clean_screenshots \
  --basetemp=/tmp/expense-review-browser-override
/workspace/cloud-setup/venv/bin/ruff check .
git diff --check
```

Each test invocation created `verify-desktop.png`, `verify-mobile.png`,
`connect-mobile.png`, and `connect-desktop.png` under its own pytest temporary
directory, with all four PNG signature assertions passing. Actual directories:

- `/tmp/expense-review-browser-qa/test_mobile_layout_accessible_0/verification-screenshots/`
- `/tmp/expense-review-browser-override/test_mobile_layout_accessible_0/verification-screenshots/`

The real harness exercised the application's HTML/CSS/JavaScript and ephemeral
loopback HTTP server, with only Plaid and database boundaries mocked as before.
It did not require `/workspace/verification-qa-artifacts` or change existing
screenshots there.

## Limits and handoff

Only the optional browser test harness and this QA artifact were edited by QA.
No app, infrastructure, dependency, README or environment-example edits; no
branch changes, commits, pushes, merges or deployment. Unrelated onboarding
artifacts were preserved. No full application suite was repeated because no
application behavior changed. Playwright-managed-browser fallback is supported
by passing an unset executable, but was not executed in this machine; actual
verification used installed Chromium through autodetection and explicit override.

Ready for Manager review, inclusion in PR #22, and review-thread response with
the executed browser results and temporary screenshot-directory evidence.
