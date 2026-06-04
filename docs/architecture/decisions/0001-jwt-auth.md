# ADR-0001: JWT access + rotating refresh tokens

- **Status:** Accepted
- **Date:** 2025 (auth rebuild)

## Context

Jamarr needs to secure its API as the real boundary — any client (web, TUI,
Android, curl) must authenticate, not just the browser UI. The earlier design
used a server-side `jamarr_session` cookie, which is browser-centric and awkward
for non-browser clients and for `<audio>`/`EventSource` requests that can't set
headers. We wanted something homelab-simple (no full OIDC/SSO) without the common
foot-guns (long-lived tokens in `localStorage`, no revocation).

## Decision

Use two tokens:

- **Access token** — short-lived JWT (default 10 min), sent as
  `Authorization: Bearer`. Stateless; validated by signature + claims. Kept in
  memory on the web client, never in `localStorage`.
- **Refresh token** — opaque, long-lived (default 21 days), **rotating** (each
  refresh revokes the previous), **stateful** (stored hashed in
  `auth_refresh_session`, so sessions are revocable and multi-session). Delivered
  to browsers as an HttpOnly cookie (`jamarr_refresh`, path `/api`).

Passwords are hashed with **argon2**. Login is rate-limited (`slowapi`). The
legacy `jamarr_session` cookie is ignored. For streaming, a separate short-lived
signed URL is used instead of cookie auth (see streaming flow / ADR-0003).

## Consequences

- Same Bearer model works for every client — enabled the TUI and Android with no
  redesign.
- Stolen access tokens expire fast; refresh reuse hard-fails (401) and can be
  globally revoked per user (`/api/auth/logout-all`).
- Cost: clients must implement refresh-on-401, and endpoints that can't send
  headers (`<img>`, `EventSource`) need the `access_token=` query fallback.
- Stateless access tokens can't be individually revoked before expiry — accepted,
  given the short TTL.
