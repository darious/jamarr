# API Reference

This page renders the **live OpenAPI schema** generated directly from the FastAPI
app — it is always in sync with the code, never hand-maintained.

!!! info "How this is generated"
    `scripts/docs/gen_openapi.py` imports the FastAPI app and dumps
    `app.openapi()` to `docs/reference/openapi.json` before every docs build.
    To enrich an endpoint's description here, add `summary=`, `description=`, a
    `response_model=`, or a docstring to the route in `app/`.

<swagger-ui src="openapi.json"/>

## Authentication

Most routes require a JWT access token:

```http
Authorization: Bearer <access_token>
```

`get_current_user_jwt` also accepts the token as an `access_token=<jwt>` query
parameter — used by the web UI for `EventSource`/`<img>` endpoints that cannot
set headers. Prefer the header everywhere else.

Refresh tokens live in an HttpOnly cookie (`jamarr_refresh`, path `/api`) and
rotate on every refresh. See [Authentication](../architecture/auth.md) for the
full model and [ADR-0001](../architecture/decisions/0001-jwt-auth.md) for the
rationale.

## Streaming

Playback uses a two-step, short-lived signed-URL flow:

1. `GET /api/stream-url/{track_id}` (auth required) → returns
   `{"url": "/api/stream/{track_id}?token=<stream_jwt>"}`.
2. `GET /api/stream/{track_id}?token=...` serves the audio `FileResponse`.

Stream tokens are stateless JWTs bound to `track_id`. Default TTL is 300 s
(`STREAM_TOKEN_TTL_SECONDS`); Cast playback uses a longer duration-aware TTL —
see [ADR-0003](../architecture/decisions/0003-cast-stream-token-policy.md).

## Artwork

Artwork routes are mounted twice (`/art/...` and `/api/art/...`) and are
currently unauthenticated so Cast/UPnP receivers can fetch images directly. The
web UI uses `GET /api/art/file/{sha1}?max_size=<n>` where `max_size` snaps to
`100`, `200`, `300`, `400`, or `600`. See [Artwork](../architecture/artwork.md).
