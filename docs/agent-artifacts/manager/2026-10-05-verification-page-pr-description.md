The account-linking flow previously opened a native browser credential prompt over a blank-looking page. This change shows a responsive Jarvis verification form, then guides the user through connecting a bank with Plaid and returning to Telegram.

The page uses existing admin credentials to create a 15-minute HttpOnly session, with inline errors, loading states, expiry handling and sign-out. Plaid token/callback endpoints require the signed session and same-origin CSRF checks. Bank credentials stay in Plaid; account persistence retains pgcrypto encryption and one row per linked account. No new secrets, dependencies, database schema, dashboard or deployment changes.

The Architect amendment and Developer/QA handoffs record the flow and validation. Session sign-out clears the browser cookie; copied session tokens remain valid until expiry. Live bank linking remains untested.

Validation: 207 tests passed in the browser-capable runner, including 11 real Chromium checks for keyboard login, errors, session resume/logout/expiry, mocked Plaid connection, retries and desktop/mobile layout. Full Telegram/weekly digest regressions, lint and JavaScript syntax checks passed. Browser tests use an optional external Playwright runner; exact commands are in the QA report.
