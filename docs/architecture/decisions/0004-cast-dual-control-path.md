# ADR-0004: Two Cast control paths (server-driven + device-direct)

- **Status:** Accepted
- **Date:** 2026-04 (Chromecast refactor, Phases 2–3)

## Context

Chromecast can be controlled two ways, and Jamarr runs in two very different
topologies: a home server on the same LAN as the Cast devices, and a public/VPS
server reachable from anywhere. A single control path can't serve both — server
mDNS discovery fails across networks, and Android can't control Cast devices it
can't reach.

## Decision

Support **both** control paths, sharing the same renderer contract and stream
delivery:

| Path | Discovers | Controls | Topology |
|---|---|---|---|
| **Server-driven** | server (mDNS, `pychromecast`) | server | Cast devices on the server's LAN |
| **Device-direct** | Android (Cast SDK) | Android | server anywhere, phone + Cast on same Wi-Fi |

In both, the Cast device fetches the stream URL from the server over HTTP and
plays via the Default Media Receiver — no custom receiver app. Device-direct Cast
pins the server's active renderer to `local:<clientId>` and reports
queue/index/progress through the existing local-client path, so history and
scrobbling match Android device-UPnP.

## Consequences

- Home-server users get zero-config Cast; remote/VPS users still get Cast from
  their phone.
- Artwork URLs must be fetchable by the Cast receiver directly, which is why
  `/art/*` stays unauthenticated (see [Artwork](../artwork.md)).
- Device-direct Cast requires Google Play Services — de-Googled Android falls
  back to server-driven Cast only.
- Cost: two discovery/control implementations to maintain (server `pychromecast`
  + Android Cast SDK), kept manageable by the shared `RendererBackend` /
  `DeviceRendererController` contracts ([ADR-0002](0002-renderer-orchestration.md)).
- v1 does not transcode; unsupported codecs fail on the receiver.
