---
role: devops
status: in-review
depends_on: [docs/agent-artifacts/manager/2026-10-05-render-proxy-review-handoff.md, docs/agent-artifacts/architect/2026-10-05-verification-page-session-spec.md]
supersedes: []
---

# Render proxy scheme correction for PR #22

The review is valid: Render terminates browser TLS at its edge and forwards HTTP to the container from outside loopback. Uvicorn's default trusted proxy addresses are loopback only, so the production HTTPS guard sees HTTP and rejects verification and protected bank-linking requests.

## Configuration and security boundary

- `Dockerfile` explicitly enables Uvicorn's supported `--proxy-headers` handling. Its trusted-address default remains restrictive; it does not set a wildcard or interpret forwarded headers in application code.
- `render.yaml` sets the nonsecret `FORWARDED_ALLOW_IPS="*"` override only for the existing Render `plan: free` web service. Uvicorn reads this environment variable and applies the forwarded scheme before the app's transport and Origin checks. No credentials or new application Settings field are needed.
- The wildcard relies on Render's managed public ingress being the external inbound path. Render's documented free web services cannot receive private-network inbound traffic. Do not reuse this wildcard for directly exposed Docker hosts or an untrusted private network.
- Before upgrading to a paid instance or adding any alternative/private ingress, reassess this assumption: isolate ingress so only trusted proxies can connect, or replace the wildcard with an explicit verified trusted-proxy IP/CIDR list. Merely accepting every private address is not an equivalent boundary.

The production HTTPS requirement, Secure session cookie, same-origin and CSRF guards are unchanged. Forwarded HTTP remains HTTP and is denied. In ordinary Docker/local use without the Render override, a non-loopback peer's spoofed forwarded HTTPS header remains untrusted.

## Operational application

For a future authorized Blueprint deployment, Render applies the environment override from `render.yaml`. An already-provisioned service not synchronized to this Blueprint requires the same named variable in its Render environment settings at that deployment. No Render settings, merge, or deployment were performed for this correction.

After an authorized deployment, verify HTTPS session-status/login and a protected Plaid token request through the real public Render URL, plus Secure cookie attributes. Mocked middleware checks validate application integration, not a live Render ingress.

## Evidence and validation handoff

Vendor website fetches were blocked by this cloud machine's network proxy (403). Official vendor sources were retrieved read-only through the available GitHub access instead, with TLS verification preserved:

- [Uvicorn settings source](https://github.com/encode/uvicorn/blob/724f82fdba1765fe5f821a3ebed6da5c1ddcb386/docs/settings.md#http): proxy headers default enabled but restricted by trusted connecting IPs; `--forwarded-allow-ips` defaults to `FORWARDED_ALLOW_IPS` when set; `*` trusts all peers. Local installed Uvicorn 0.54.0 `Config` source independently confirms the environment override and middleware wiring.
- [Render-authored web-service reference](https://github.com/render-examples/render-ops-agent-ts/blob/7f5d539be01a69a12982235fd4a06e93dcbf21b4/.agents/skills/render-web-services/SKILL.md#tls-and-https): TLS terminates at Render's edge; the process receives HTTP; only the selected `PORT` receives public HTTP traffic.
- [Render-authored private-network reference](https://github.com/render-examples/render-ops-agent-ts/blob/7f5d539be01a69a12982235fd4a06e93dcbf21b4/.agents/skills/render-networking/SKILL.md#who-can-communicate): free web services cannot receive inbound private traffic; paid web services can.
- Canonical references supplied in the review: [Render web services](https://render.com/docs/web-services), [Render private networking](https://render.com/docs/private-network), [Uvicorn settings](https://www.uvicorn.org/settings/).

QA should load the actual Blueprint trust value through Uvicorn `Config`/`ProxyHeadersMiddleware` with an HTTP ASGI scope and a non-loopback connecting peer. Prove forwarded HTTPS permits session-status, login with Secure cookie, and same-origin/CSRF protected requests; forwarded HTTP and an untrusted/default peer remain denied before Plaid calls. QA owns tests and their actual outcomes. No Docker daemon or live Render instance is available here; no image-build or deployed verification claim is made.

DevOps checks actually passed: Blueprint YAML parse and free-service scope, Docker CMD JSON parse and explicit proxy flag, Uvicorn consumption of the Blueprint environment override, restrictive trust with the variable absent, and `git diff --check`. Application behavior remains assigned to independent QA.
