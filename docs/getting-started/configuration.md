# Configuration

Jamarr splits configuration into two places:

| File | Holds | Committed? |
|---|---|---|
| `.env` | Secrets + per-deployment settings (DB creds, API keys, paths, JWT secret) | No — copy from `.env.example` |
| `config.yaml` | Non-secret app config (MusicBrainz URL, logging, concurrency) | Yes |

## `.env`

Copy `.env.example` → `.env` and fill in values. Every variable is documented in
[Environment Variables](../reference/env-vars.md). The minimum required set is
listed in [Install](install.md).

`HOST_IP` is auto-detected by `dev.sh` and `deploy.sh` via a route lookup; set it
explicitly only if detection fails or you need to override it:

```bash
HOST_IP=192.168.1.50 ./deploy.sh
```

## `config.yaml`

Non-secret application config that ships in the repo. Typical contents:

- MusicBrainz API root URL and rate limits
- Logging level / format
- Scanner concurrency
- UPnP renderer stream-proxy port (`renderer.stream_proxy_port`, default 8112)

Edit it directly and restart the stack (or rely on hot-reload in
[Dev Mode](dev-mode.md)).

## Production hardening

For internet-facing deployments behind a reverse proxy:

- `REFRESH_COOKIE_SECURE=true` (requires HTTPS)
- Set `ALLOWED_HOSTS`, `ALLOWED_ORIGINS`, and `TRUSTED_PROXY_IPS`
- See [Authentication](../architecture/auth.md) for the full cookie/TLS model
