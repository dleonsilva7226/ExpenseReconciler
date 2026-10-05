---
role: devops
status: in-review
depends_on: [docs/agent-artifacts/manager/2026-10-05-verification-review-followup.md, docs/agent-artifacts/architect/2026-10-05-verification-page-session-spec.md]
supersedes: []
---

# Verification setup documentation review fix

Addressed PR #22 thread `discussion_r4187890001`. Updated active setup
guidance in `README.md` and `.env.example` from obsolete Basic Auth to
the public Jarvis verification form and signed 15-minute browser session
protecting Plaid linking endpoints. Clarified existing admin credentials,
separate bank credentials, `TOKEN_ENCRYPTION_KEY`'s domain-separated signing
derivation, development loopback HTTP, and production HTTPS requirements.
Historical artifacts and existing variable names/placeholder values remain
unchanged; no new settings, secret values, app edits, or deployment.

## Documentation checks

- Compared guidance with approved session spec, `app/gateway/auth.py`,
  `Dockerfile`, and `render.yaml`.
- Verified no Basic Auth references remain in active `README.md` or
  `.env.example`, environment assignments are unchanged, and
  `git diff --check` passes.
- No runtime behavior changed; application/browser validation belongs to
  the concurrent QA handoff. No commits, pushes, merges, or deployments.
