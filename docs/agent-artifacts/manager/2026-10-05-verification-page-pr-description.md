The account-linking flow previously opened a native browser credential prompt over a blank-looking page. This change shows a responsive Jarvis verification form, then guides the user through connecting a bank with Plaid and returning to Telegram.

The page uses existing admin credentials to create a 15-minute HttpOnly session, with inline errors, loading states, expiry handling and sign-out. Plaid token/callback endpoints require the signed session and same-origin CSRF checks. Bank credentials stay in Plaid; account persistence retains pgcrypto encryption and one row per linked account.

The Render free-service Blueprint now configures Uvicorn's forwarded-header trust so HTTPS terminated at Render's ingress reaches the production HTTPS guard correctly. Docker enables proxy handling and keeps Uvicorn's restrictive default when the Render override is absent. Reassess the managed-ingress trust boundary before introducing paid/private ingress; the DevOps note records sources and deployment application steps.

Validation: 212 tests passed in the browser-capable runner, including 11 real Chromium checks and five actual-Uvicorn proxy regressions. Proxy tests use a non-loopback HTTP peer and verify forwarded HTTPS login, Secure cookies, protected Plaid access, and rejection of untrusted/HTTP or invalid Origin/CSRF requests. Full Telegram/weekly digest regressions, lint and JavaScript syntax checks passed. Browser tests use an optional external Playwright runner; exact commands are in the QA reports.

No new secrets, dependencies, database schema, dashboard or live deployment. Stateless sign-out clears the browser cookie; copied session tokens remain valid until expiry. Live bank linking and Render ingress remain untested.
