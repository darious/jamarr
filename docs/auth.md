# Jamarr Authentication & API Security (Recommended Approach)

This document proposes a **pragmatic, homelab-friendly auth design** for Jamarr’s **FastAPI (uvicorn) backend** and **SvelteKit frontend**, based on the current architecture and deployment model. 

The goals are:

- Secure the **API** (the real security boundary) so any client (Svelte, Android, curl, scripts) must authenticate.
- Keep the implementation **simple** (no full SSO/OIDC provider), but avoid common foot-guns (e.g., long-lived tokens in localStorage).
- Make **prod** secure with HTTPS + cookies, while keeping **dev** easy.
- Provide a clear plan for **tests**.

---

## 1. Summary of the recommended model

### Use two tokens with different purposes

1. **Access token (JWT)**
   - Short-lived (e.g., **10 minutes**)
   - Sent on every protected request via:
     - `Authorization: Bearer <access_token>`
   - **Stateless**: backend validates signature + claims (expiry, issuer, etc.)

2. **Refresh token** (opaque random string)
   - Long-lived (e.g., **14–30 days**)
   - **Rotating**: each refresh invalidates the previous refresh token
   - **Stateful**: stored in DB (hashed), so you can revoke sessions
   - **Multi-session**: allow multiple active refresh sessions per user

### Browser storage strategy (Svelte)
- Refresh token stored as an **HttpOnly cookie** (JS can’t read it).
- Access token kept in **memory** (Svelte store), not localStorage.

### Non-browser clients (curl / scripts / Android)
- Use the same access token model.
- Re-login when access token expires (no JSON refresh).

---

## 1.5 Current Jamarr auth (today)

Jamarr currently uses **cookie-backed sessions**:

- A random session token is stored in the `session` table.
- The browser receives a `jamarr_session` **HttpOnly cookie**.
- The session uses **sliding expiration** (default 30 days).
- Endpoints live under `/api/auth/*` (see `app/api/auth.py`).

This is stable for same-origin browser usage but makes non-browser clients harder and
does not support short-lived access tokens or rotation.

---

## 2. Why this fits Jamarr

Jamarr already has:

- A persistent DB (PostgreSQL) for state and history
- A strong distinction between:
  - **backend control plane** (UPnP control, queue/state, streaming)
  - **frontend UX** (SvelteKit UI, optimistic updates)
- Multiple environments (dev/prod/test compose stacks) and scripts

The recommended model integrates cleanly into this setup while keeping the footprint small. 

---

## 3. Threat model (what this protects)

### Protected
- Direct API calls without auth: **401**
- Stolen access token reuse: limited by **short expiry**
- Session revocation: revoke refresh token row(s)
- Browser XSS token theft: refresh token is **HttpOnly**
- Future Android app reuse: same Bearer token approach

### Not magically solved
- A compromised server / reverse proxy
- A user with valid credentials doing allowed actions
- XSS that can *perform actions* in the user’s browser session (but it still can’t *steal* HttpOnly refresh tokens)

---

## 4. Endpoints & flows

### 4.1 Auth endpoints

Recommended endpoints:

- `POST /api/auth/login`
  - Input: username + password
  - Output: JSON access token
  - Side-effect: set refresh cookie (browser)

- `POST /api/auth/refresh`
  - Browser: uses refresh cookie
  - Non-browser: re-login on expiry (no JSON refresh)
  - Output: new access token
  - Side-effect: rotate refresh token (old one revoked)
  - Reuse of a revoked refresh token must 401 (optionally log at warn level)

- `POST /api/auth/logout`
  - Revokes the active refresh token and clears cookie

- `POST /api/auth/logout-all` (user settings)
  - Revokes all refresh sessions for the user

- `GET /api/auth/me` (optional but useful)
  - Returns current user profile + roles/scopes for UI gating
  - Must not refresh or mint tokens

### 4.2 Browser flow (SvelteKit)

1. User logs in → gets access token + refresh cookie.
2. Frontend stores access token **in memory**.
3. On page load:
   - call `/api/auth/refresh` to obtain an access token if refresh cookie exists.
4. On API 401:
   - attempt `/api/auth/refresh` once, then retry the request.
   - if refresh fails, redirect to login.

### 4.3 Script / curl flow

- Login to get an access token.
- Send `Authorization: Bearer …` for API calls.
- On expiry:
  - re-login.

---

## 5. Backend implementation plan (FastAPI)

### 5.1 Libraries (small and standard)
- Password hashing: `passlib[bcrypt]` (or argon2)
- JWT signing/verification: `python-jose[cryptography]` (or PyJWT)
- Rate limiting (recommended): `slowapi` or similar
- Database layer: whatever Jamarr is already using (SQLAlchemy / SQLModel / raw queries)

### 5.2 JWT contents (claims)

Access token (JWT) should include:
- `sub`: user id (string)
- `exp`: expiry (10 minutes)
- `iat`: issued-at
- `iss`: issuer (e.g., `jamarr`)
- `aud`: audience (e.g., `jamarr-api`)
- `roles` or `scopes` (optional but recommended early)

### 5.3 Refresh token storage (DB)

Create a table like:

- `auth_refresh_session`
  - `id` (uuid / bigint)
  - `user_id`
  - `token_hash` (hash of refresh token, never store raw)
  - `created_at`
  - `expires_at`
  - `revoked_at` (nullable)
  - `last_used_at`
  - `user_agent` / `ip` (optional: useful for a small “Sessions” UI)
  - `token_hash` should be **UNIQUE**
  - Multiple active sessions per user are allowed

Rotation:
- On refresh: mark old session row revoked, insert a new row with a new token hash.
- If a revoked refresh token is presented again:
  - return 401
  - optionally log at warn level
  - optionally revoke all refresh sessions for that user (paranoid mode)

### 5.4 Protecting endpoints

Use a standard FastAPI dependency:
- Extract Authorization header
- Validate JWT signature + claims
- Load user
- Enforce roles/scopes if needed

For Jamarr, keep a single role for now and defer role gating until later.

### 5.5 Streaming endpoint considerations (`/api/stream/{track_id}`)

Browsers often use `<audio src="…">` which makes it awkward to attach Authorization headers.

Two common approaches:

**Option A (recommended): short-lived signed stream URL**
- Provide a separate endpoint:
  - `GET /api/stream-url/{track_id}` (auth required)
- Backend returns a URL containing a short-lived, single-purpose token:
  - `/api/stream/{track_id}?token=<signed_stream_token>`
- Token expiry: 1–5 minutes.
- Token grants **read-only** access to that track stream only.
- Token payload must include `track_id` (and optionally `user_id`) and reject mismatch.

**Option B: cookie-based access token**
- Store access token in HttpOnly cookie too (not just refresh).
- This simplifies `<audio>` playback but complicates CSRF and is usually not worth it.

Given Jamarr’s focus on correctness and control, **Option A** is the cleanest.

---

## 6. Prod vs Dev implementation

Jamarr already distinguishes dev/prod via compose stacks and scripts. 

### 6.1 Production requirements
- **HTTPS required** (Let’s Encrypt via Nginx reverse proxy is perfect).
- Refresh cookie should be:
  - `HttpOnly=true`
  - `Secure=true`
  - `SameSite=Lax` (start here)
  - `Path=/api/auth` (optional; limits exposure)
- Consider HSTS if you’re always HTTPS.

### 6.2 Development options

You **do not need Let’s Encrypt in dev**.

Pick one:

**Dev Option 1 (simplest): HTTP dev with relaxed cookie `Secure`**
- In dev only:
  - `Secure=false`
  - keep `HttpOnly=true`
  - keep `SameSite=Lax`
- Guard with env var so this can’t happen in prod.

**Dev Option 2 (prod-like): HTTPS in dev**
- Use `mkcert` (local trusted cert) or self-signed.
- Run via Nginx locally or directly with uvicorn TLS.
- Best if you’re debugging cookie/CORS edge cases.

### 6.3 Same-origin vs cross-origin in dev

To reduce cookie/CORS pain, prefer:
- Frontend and API under the same “site” (e.g. reverse proxy `/api`), OR
- Use a dev-server proxy so the browser sees same origin for API calls.

---

## 7. Security hardening checklist

Minimum recommended hardening:
- Passwords:
  - bcrypt/argon2, never plain
- Login brute-force protection:
  - rate limit login endpoint
- Session management:
  - refresh token rotation
  - allow admin/user to revoke all sessions
- Secrets:
  - JWT signing secret stored in env/secret manager, not in git
  - rotate if compromised
- Logging:
  - never log raw tokens
  - log auth failures at warn level
- CORS:
  - allow only your frontend origin(s)
  - do **not** rely on CORS as “security”; it’s a browser policy, not an auth control

---

## 8. Test plan (what to automate)

Given Jamarr has a dedicated test compose stack, tests should be automated and runnable there
(see `test.sh`).

### 8.1 Unit tests (fast)
- Password hashing:
  - hash + verify
- JWT:
  - encode/decode
  - expiry enforced
  - issuer/audience mismatch rejected (if used)
- Refresh token:
  - token hashing (consistent)
  - rotation logic: old revoked, new created

### 8.2 Integration tests (pytest + test DB)
Spin up app + test DB, then validate:

**Auth flows**
- `POST /api/auth/login`
  - success
  - wrong password → 401
  - rate limiting triggers
- `POST /api/auth/refresh`
  - valid cookie → new access token
  - rotated refresh token cannot be reused → 401
- `POST /api/auth/logout`
  - refresh revoked
  - refresh after logout fails
- `POST /api/auth/logout-all`
  - all refresh sessions revoked

**Authorisation**
- protected endpoints:
  - no token → 401
  - expired token → 401
  - wrong role → 403
- public endpoints remain public (if any)

**Streaming**
- `GET /api/stream-url/{track_id}` requires auth
- stream token:
  - works within TTL
  - fails after expiry
  - cannot be used for different `track_id`
 - legacy session cookie ignored:
   - requests relying only on `jamarr_session` are rejected

### 8.3 Security regression tests (cheap but valuable)
- Ensure refresh cookie flags differ between dev/prod:
  - dev: Secure=false
  - prod: Secure=true
- Ensure access token is not set as a long-lived cookie in the browser flow (unless intentionally chosen)

---

## 9. Implementation notes for Jamarr’s structure

Jamarr already has an `app/auth.py` file.
Suggested structure:

- `app/auth.py`
  - user lookup, password verify, token minting, refresh session operations
- `app/api/auth_routes.py` (or `app/api/auth.py`)
  - `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`, `/api/auth/me`
  - `/api/auth/logout-all`
- `app/api/deps.py`
  - `get_current_user()` dependency
- `web/src/lib/api.ts`
  - fetch wrapper that:
    - adds Authorization header
    - refreshes on 401 once
    - uses a shared "refresh in progress" promise to avoid concurrent refresh storms
- `web/src/lib/stores/auth.ts`
  - in-memory access token store

Explicit CSRF protection is not required at this stage due to SameSite cookies and
bearer-token auth for state-changing endpoints.

---

## 10. Operational guidance

### Secret management
- Store:
  - JWT signing secret
  - cookie secret(s)
  - password pepper (optional)
in environment variables or docker secrets.

### Session revocation UX (optional)
A simple admin endpoint:
- `POST /admin/users/{id}/revoke-sessions`
- Deletes/revokes all refresh sessions for that user.

User settings endpoint:
- `POST /api/auth/logout-all`
- Revokes all refresh sessions for the current user.

---

## 11. “Definition of done” checklist

- [ ] Access JWT auth required for all non-public `/api/*` endpoints
- [ ] Refresh token rotation implemented + stored hashed in DB
- [ ] Refresh delivered via HttpOnly cookie for browser clients
- [ ] Refresh reuse hard-fails (revoked token reuse returns 401)
- [ ] `/api/auth/me` validates only; never refreshes
- [ ] `/api/auth/logout-all` revokes all refresh sessions
- [ ] Dev vs prod cookie flags correctly set via environment
- [ ] Streaming uses short-lived stream tokens (or alternative explicitly chosen)
- [ ] Stream tokens bound to `track_id` (and optionally `user_id`)
- [ ] Login rate-limited
- [ ] Integration tests cover login/refresh/logout + 401/403 behaviour
- [ ] Legacy `jamarr_session` cookies ignored for auth
- [ ] Docs updated with how to use curl/scripts (login + bearer token)

---

## Appendix A: Recommended defaults

- Access token TTL: **10 minutes**
- Refresh token TTL: **21 days**
- Refresh rotation: **on every refresh**
- Cookie settings:
  - Prod: `HttpOnly=true`, `Secure=true`, `SameSite=Lax`
  - Dev: `HttpOnly=true`, `Secure=false`, `SameSite=Lax`
- Roles:
  - Single role for now (no role gating yet)

---

## Appendix B: Notes on “securing the frontend”

The frontend code (JS) is always downloadable by users. This is normal.

Security is enforced by the API:
- The frontend is *useful* only when it can obtain valid tokens.
- The API only accepts requests with valid tokens, regardless of client.

This is the correct model and enables a future Android client with no redesign.
