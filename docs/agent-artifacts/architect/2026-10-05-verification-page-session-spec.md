---
role: architect
status: approved
depends_on: [docs/agent-artifacts/manager/2026-10-05-verification-page-task-breakdown.md, docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md]
supersedes: [docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md]
---

# A2a amendment: Jarvis verification and bank connection

## Scope and decision

Replace the native browser Basic Auth prompt with a public, styled Jarvis verification page, using the existing single admin username/password and a 15-minute signed browser session. The same page guides verification, Plaid connection, and confirmation. This amendment supersedes A2a's Basic Auth and UI contracts only; preserve its Plaid behavior, account metadata, one-row-per-account persistence, and A1 pgcrypto token encryption. No dashboard, user registration, password recovery, account database, new dependencies, merge, or deployment.

Manager has recorded the user's explicit implementation request. Developer may begin only when this artifact is approved.

## Module boundaries

- `app/gateway/auth.py`: credential comparison, session signing/verification, request transport and same-origin guards, session-cookie lifecycle helpers, and the protected-route dependency. Remove HTTPBasic/browser challenges entirely. `AdminUser` may remain the protected dependency annotation returning the configured admin username to existing neighboring code.
- `app/gateway/router.py`: page/assets and session endpoints, session request Pydantic model, protected Plaid routes, and safe HTTP errors for Plaid failures. Existing Telegram, Plaid webhook, and weekly digest machine authentication remain separate.
- `app/gateway/static/link_account.html`: public semantic document containing the three page states, without embedded credentials or dynamic server templating.
- `app/gateway/static/link_account.css`: responsive page styling.
- `app/gateway/static/link_account.js`: session state and accessible UI transitions, JSON fetch calls, and Plaid Link integration. Load Plaid's existing official CDN script only after successful verification; do not expose bank/API secrets to the browser.
- Tests live under `tests/gateway/`; update previous Basic Auth expectations and preserve meaningful account persistence and webhook checks.

No database schema, dependency manifest, infrastructure, or `.env` changes. Existing `ENVIRONMENT`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `TOKEN_ENCRYPTION_KEY` bindings suffice.

## Credential and session contract

Verify both username and password independently with `secrets.compare_digest` on their UTF-8 bytes (supports non-ASCII credentials without Python's string comparison exception); do not short-circuit one comparison. Incorrect credentials return the same generic response regardless of which field is wrong. Never log request credentials, tokens, session-cookie values, or encryption keys.

Use existing PyJWT with HS256, not a new dependency or a password-only signing key. Derive a domain-specific session key with HMAC-SHA256, keyed by the existing `settings.token_encryption_key`, with a message comprising `b"jarvis/link-account/session/v1\0"` followed by unambiguous JSON serialization of `[settings.admin_username, settings.admin_password]` encoded in UTF-8. The serialization must be stable (compact separators, explicit Unicode encoding); retain this definition in tests. HMAC domain separation avoids using the pgcrypto key directly as a JWT signing key. Binding current admin credentials invalidates existing sessions after an admin credential change. Do not expose this derived key. The existing encryption key must remain a strong secret; do not add a new signing-secret requirement.

JWT payload:

| Claim | Required value/type |
|---|---|
| `sub` | Exact literal `admin` |
| `purpose` | Exact literal `jarvis-link-account-v1` |
| `iat` | Integer issuance timestamp |
| `exp` | Integer timestamp exactly 900 seconds after issuance |
| `csrf` | Fresh `secrets.token_urlsafe(32)` string for this session |

Verify signature using an explicit `algorithms=["HS256"]`, require all claims, check literal subject/purpose, strict integer timestamps (booleans excluded), plausible issuance not in the future, nonempty CSRF string, and a lifetime of 900 seconds. Do not trust header-selected algorithms. Malformed, modified, wrongly signed, wrong-purpose, missing-claim, and expired tokens are unauthenticated; no uncaught decode exceptions. No rolling renewal or stored JWT in JavaScript/localStorage. A successful verification always creates a fresh session/CSRF token.

Cookie: `jarvis_link_session`, `HttpOnly`, `SameSite=Lax`, `Path=/link-account`, `Max-Age=900`, no Domain (host-only), and `Secure=True` in production or whenever the actual request is HTTPS. In local development only, plain HTTP on `localhost`, `127.0.0.1`, or `::1` may set `Secure=False`. The HTTPS policy below applies before accepting credentials or protected requests. Deleting the cookie uses the same name/path and security/SameSite attributes, `Max-Age=0`, and expired Expires.

Stateless sessions have no server-side session table or revocation store. Signing out deletes this browser's cookie and clears client state; a copied bearer cookie can remain valid until its original 15-minute expiry. Credential/encryption-key changes invalidate old signatures once settings are reloaded. Do not claim global server revocation in UX or tests.

## Transport and CSRF rules

Production verification/session/Plaid endpoints require `request.url.scheme == "https"`; deny HTTP with 403 and a safe HTTPS-required message before checking submitted credentials or doing side effects. Development HTTP is permitted only for the loopback hosts above. Page/assets can render publicly, but remote HTTP verification cannot authenticate. Keep existing machine endpoints outside this browser transport guard.

Use the ASGI request's scheme/authority after the server's trusted proxy handling. Never manually accept arbitrary `X-Forwarded-Proto` headers. Existing production TLS/proxy configuration remains a deployment prerequisite; no deployment is performed in this ticket.

Every browser mutation (`POST /link-account/session`, `POST /link-account/logout`, `POST /link-account/token`, `POST /link-account/callback`) must have a valid, non-null `Origin` exactly matching the request's scheme, hostname, and effective port. Parse origins; reject userinfo, paths other than empty/root, query, fragment, malformed strings, cross-origin, missing, and `null` origins. Compare normalized hostnames and effective default ports, not suffix matching. Reject `Sec-Fetch-Site: cross-site` when present. No permissive CORS or Referer fallback.

Login requires JSON Content-Type (`application/json`, optional charset) and the above Origin guard; there is no pre-login CSRF token to store. A cross-origin site cannot send this JSON mutation through a browser without a denied preflight. Token and callback requests also require JSON Content-Type; the frontend sends `{}` for token creation.

After verification, all mutation endpoints additionally require `X-CSRF-Token` constant-time equal to the verified session's `csrf` claim. Return 401 first for absent/invalid session and 403 for valid session with missing/wrong Origin or CSRF. Login Origin failure returns 403 before credential checking. These guards must run before any Plaid/network/database work. GET session status is read-only and returns CSRF only to the authenticated same-origin browser (no CORS); mark it `Cache-Control: no-store`.

All page/session/protected API responses, including errors, carry `Cache-Control: no-store`. Page response also carries `Referrer-Policy: no-referrer`. No `WWW-Authenticate: Basic` response exists anywhere in this flow, including errors. HTTP Basic Authorization headers cannot substitute for a valid session.

## HTTP interfaces and data models

| Route | Contract |
|---|---|
| `GET /link-account` | Public 200 HTML for verification/connect/success UI; an invalid/missing cookie never opens a browser popup or creates a blank screen. |
| `GET /link-account/assets/link_account.css` | Public known CSS file with correct MIME type. |
| `GET /link-account/assets/link_account.js` | Public known JS file with correct MIME type. |
| `GET /link-account/session` | 200 `{"authenticated": false}` when missing/invalid/expired; clear an invalid cookie. For valid session, 200 `{"authenticated": true, "csrf_token": "…", "expires_at": <integer epoch>}`. Apply transport rules. Never return JWT, credential, or signing key. |
| `POST /link-account/session` | Pydantic body `username: str` (1–256 characters), `password: str` (1–1024 characters), extra fields forbidden. JSON only, transport and Origin guarded. Valid credentials: 200 authenticated status shape above plus signed cookie. Wrong credentials: 401 `{"detail":"We couldn't verify those details. Please try again."}`, no Basic challenge and no new authenticated cookie. Validation errors may use FastAPI 422; UI maps them to a safe field/form message. |
| `POST /link-account/logout` | Valid session, Origin, CSRF required; 200 `{"authenticated": false}` and delete session cookie. Frontend sends JSON `{}`. Expired/missing session returns 401; frontend still clears its state. |
| `POST /link-account/token` | Valid session, Origin, CSRF, JSON required. Retain existing Plaid token creation and 200 `{"link_token":"…"}`. No minting for unauthorized/CSRF-failed requests. |
| `POST /link-account/callback` | Same protection as token endpoint. Preserve existing `LinkAccountCallbackRequest`: `public_token: str`, `institution_name: str`, `accounts: list[LinkAccountCallbackAccount]`; account fields `id`, `name`, optional `mask`, `type`, `subtype`. Keep empty-list 400 and existing one-row-per-account encrypted inserts. On committed success retain `{"linked":true,"item_id":"…","accounts_linked":N}`. |

Asset serving must allow only the two named files; do not mount the entire gateway directory or accept arbitrary file paths. Using two literal routes is sufficient.

Catch expected provider/DB failures at the bank-linking boundary and return a generic safe error with a failed status (502 for Plaid provider failure, 500 for persistence failure). Preserve transaction rollback and do not display/return raw provider exceptions, credentials, access/public tokens, or SQL. Safe logging can identify operation and exception type without exception text or sensitive payload. No response may claim success before DB commit. Do not alter webhook or finance-domain semantics.

## Page and interaction contract

A restrained light Jarvis page with a centered card, ample whitespace, brand label, heading “Connect your bank to Jarvis,” and step indicator “1 Verify · 2 Connect · 3 Done.” Responsive from narrow mobile screens through desktop, no external font dependency, no invented account features. Explain: “Verify access, then securely connect your bank through Plaid.” Clarify that the initial credentials are Jarvis access details and bank credentials are entered in Plaid.

1. On initial load, show a visible loading state while fetching session status; fall back to an actionable inline connection error on fetch failure. A 200 unauthenticated response reveals the verification form. A valid existing session reveals Connect directly.
2. Verification form has explicit associated labels “Username” and “Password,” `autocomplete="username"` / `autocomplete="current-password"`, real form submission for Enter-key use, required fields, and a Continue button. Disable Continue and show “Verifying…” while pending. Preserve username and clear password on failure; always clear password after success. Never persist either field in localStorage/sessionStorage or URLs.
3. Connect state explains the next step, offers “Connect bank account,” and a separate “Sign out” action. Request the token only on that button; show a pending label/disabled button while obtaining token, loading Plaid SDK, and running Link. Load the official existing CDN `https://cdn.plaid.com/link/v2/stable/link-initialize.js` lazily; handle SDK/network failures as inline retryable messages. Always use same-origin fetch with cookie credentials and the in-memory CSRF header, JSON Content-Type, and no Authorization Basic headers.
4. Plaid success forwards existing metadata without changing persistence; display “Connecting your account…” until the callback succeeds. Success state: “Your account is connected. Return to Telegram to ask Jarvis about your finances.” Offer “Connect another account” and “Sign out.” Do not invent a Telegram URL from secret bot credentials.
5. Plaid cancellation with no error returns to Connect with “Connection cancelled. You can try again when you're ready.” Provider failure shows a friendly retry message; no “check server logs.” Destroy obsolete Link handlers and prevent duplicate button submissions.
6. Any protected 401 transitions back to verification, clears in-memory CSRF and previous Plaid handler/public token, and explains “Your verification expired. Verify again to continue.” Do not automatically replay a callback/public token after re-verification; start a fresh Link attempt to avoid duplicate writes. A 403 clears the active attempt, shows a safe “Please refresh and verify again” message, and offers re-verification. Logout success returns to form with “You've signed out.” A logout failure other than 401 must not falsely claim the cookie was deleted; show a retry message.
7. Use `expires_at` to schedule the session-expiry transition while the page is open (recheck on focus/visibility if timers were suspended). Backend remains authoritative. Do not show credentials/connect actions indefinitely after known expiration.

Accessibility: semantic `main`, one h1, explicit form labels, visible keyboard focus, sufficient contrast, comfortable touch targets, hidden inactive panels removed from keyboard navigation, status container with `role="status"`/`aria-live="polite"`, errors announced and focus moved to the relevant form heading/first field. Render dynamic strings with `textContent`, never provider-supplied HTML. Include a useful noscript message explaining JavaScript is needed for secure bank connection. Avoid auto-opening Plaid on load.

## Required validation and handoff

Developer records scope, governing approved spec, actual checks, and deviations in its status note; Manager then delegates independent QA. At minimum verify:

- Public page and known assets render; no popup/challenge or leaked protected values; unknown/path-traversal assets inaccessible.
- Incorrect credentials, empty/malformed JSON, non-ASCII credentials, success, and refreshed session with fresh CSRF.
- Cookie HttpOnly/host-only/path/Lax/900-second lifetime; Secure on HTTPS and production; loopback HTTP allowed only for development; production/remote plaintext rejected; spoofed untrusted forwarding header does not bypass guard.
- Signed session tampering, algorithm/purpose/claim changes, expiry, future issuance, credential change, and invalid-token clearing; logout deletion and client state transitions. Explicitly do not test cookie deletion as global token revocation.
- Missing session, Basic-only credentials, missing/cross/null Origin, wrong port, missing/wrong CSRF, non-JSON mutations rejected without Plaid/DB calls; correct same-origin credentials/session can reach both protected endpoints.
- Mocked Plaid token → Link metadata → callback → encrypted one-row-per-account transaction → success, including empty accounts/provider failure/persistence rollback.
- Browser flow where a browser runner is available: form Enter submit, failure/success, pre-existing session, Link cancellation/success, session expiry, logout, mobile viewport, accessible labels/focus/status. Mock Plaid CDN/SDK and backend Plaid; no live bank connection or credentials.
- Full existing tests and lint, including Telegram mocked LLM-to-reply flow and weekly digest regressions.

This ticket requires no new credentials, deployment, scheduler change, or linked live bank data. Live delivery prerequisites remain outside this PR.
