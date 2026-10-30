# Configuration

Jamarr splits configuration into two places:

| File | Holds | Committed? |
|---|---|---|
| `.env` | Secrets + per-deployment settings (DB creds, API keys, paths, JWT secret) | No — copy from `.env.example` |
| `config.yaml` | Non-secret app config (MusicBrainz URL, logging, concurrency, renderer overrides); bind-mounted from beside `docker-compose.yml` | Yes (the default; edit your copy) |

## `.env`

Copy `.env.example` → `.env` and fill in values. Every variable is documented in
[Environment Variables](../reference/env-vars.md). The minimum required set is
listed in [Install](install.md).

Set `HOST_IP` to the server's LAN address: renderers fetch streams and artwork
from it, and the compose default of `127.0.0.1` only works for the browser on
the server itself. `dev.sh` fills it in from a route lookup for development.

## `config.yaml`

Non-secret application config. The repo copy is the default; an install keeps
its own beside `docker-compose.yml`, which mounts it into the container at
`/app/config.yaml`. Typical contents:

- MusicBrainz API root URL and rate limits
- Logging level / format
- Scanner concurrency
- UPnP renderer stream-proxy port (`renderer.stream_proxy_port`, default 8112)
- UPnP discovery interface address (`renderer.upnp_source_ip`, default: the
  default-route address) — set it on multi-homed hosts or with a VPN up
- UPnP next-track staging overrides (`renderer.upnp_gapless`: `enabled`,
  `disabled_udns`, `forced_udns`) — see
  [Renderers](../architecture/renderers.md#upnp-next-track-staging)
- UPnP event subscriptions (`renderer.upnp_events`, default `true`;
  `renderer.upnp_event_port`, default 8113, the NOTIFY callback port bound on
  the UPnP source address) — see
  [Renderers](../architecture/renderers.md#upnp-events-and-watchdog-polling)
- Per-renderer audio output constraints (`renderer.audio_constraints`, keyed by
  renderer id (`upnp:`/`cast:` prefix optional) / UPnP UDN / Cast UUID:
  `max_sample_rate_hz`, `max_bit_depth`,
  `max_channels`, `flac_max_block_size`, `prefer_wav`, `allow_lossy`,
  `quality`, `supported_mime_types`, `supported_codecs`) — see
  [Renderers](../architecture/renderers.md#audio-output-planning)
- Server Cast receiver queue / preload (`renderer.cast_queue`: `enabled`,
  `enabled_uuids`, `disabled_uuids`, `preload_seconds`; off by default) — see
  [Renderers](../architecture/renderers.md#cast-receiver-queue-preload)

Edit it directly and restart the stack (or rely on hot-reload in
[Dev Mode](dev-mode.md)).

## Production hardening

For internet-facing deployments behind a reverse proxy:

- `REFRESH_COOKIE_SECURE` — leave unset; the cookie is marked `Secure` per request (HTTPS, or `X-Forwarded-Proto: https` from a trusted proxy). Pinning it `true` locks out clients that reach the server over plain HTTP
- Set `ALLOWED_HOSTS`, `ALLOWED_ORIGINS`, and `TRUSTED_PROXY_IPS`
- See [Authentication](../architecture/auth.md) for the full cookie/TLS model
