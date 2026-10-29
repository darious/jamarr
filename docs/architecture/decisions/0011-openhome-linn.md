# ADR-0011: Native OpenHome/Linn backend — evaluated, not built

- **Status:** Accepted (evaluation; no backend ships)
- **Date:** 2026-10-29 (#316, Priority 3)

## Context

#316 asks to evaluate a native OpenHome/Linn backend: Product / Playlist / Time
/ Volume / Info and the legacy Linn variants as separate capabilities; Jamarr
tracks mapped to renderer queue ids (Insert / ReadList / DeleteId / SeekId);
device-side shuffle/repeat; event-based reconciliation; several controllers
agreeing on one renderer-owned playlist; source/standby only where supported;
and never assuming AVTransport.

A prototype was written from the OpenHome service specifications and the
legacy Linn SCPDs, and tested only against in-memory fakes. A network scan on
2026-10-29 (SSDP `ssdp:all` plus each description's service list) found **no
device advertising any `av-openhome-org` or `linn-co-uk` service**; every
renderer present is plain AVTransport. Nothing could be tested on hardware,
so the prototype was removed before merge.

### What the prototype established

**OpenHome is a different queue model.** The device holds the whole playlist,
advances through it by itself, and other controllers (Kazoo, BubbleUPnP, …)
edit the same list. Jamarr would mirror it, not load one track at a time:
`queue_ownership: renderer` in the capability contract
([ADR-0006](0006-renderer-capability-contract.md)).

**Detection, per service and per action.** Search
`urn:av-openhome-org:service:Playlist:1` in addition to the AVTransport
targets. Classify every service separately (`av-openhome-org` Product /
Playlist / Time / Volume / Info / Radio / Transport; legacy `linn-co-uk` Ds /
Playlist / Preamp / Product / Time / Info) and every operation against the
actions in its SCPD. Nothing implies anything else: a Playlist does not imply
Volume or Product, Product without `SetStandby` gives no standby, and
OpenHome never implies AVTransport. Queue operations come from **one family**
(OpenHome Playlist, or Linn `Playlist` + `Ds`), because item ids are only
valid within the service that issued them. Bind arguments positionally to the
SCPD's own names, so OpenHome (`AfterId`) and Linn (`aAfterId`) take the same
call.

**Routing.** A device with both OpenHome and AVTransport should prefer
OpenHome, also when one description holds exactly one OpenHome Source and one
plain MediaRenderer as sibling devices, with a per-device override to stay on
AVTransport. An OpenHome-only device is only playable this way.

**Queue mapping.**

| Jamarr action | Device |
|---|---|
| set queue | `DeleteAll`; insert the start track, `SeekId` + `Play`; insert the rest around it (capped at `TracksMax`) in the background |
| append / reorder / remove | minimal edit: ids already in order stay (the playing one always), others `DeleteId` + `Insert`; non-Jamarr entries never touched |
| skip / play track | `SeekId` (inserting first if needed) |
| pause / resume / stop / seek | `Pause` / `Play` / `Stop` / `SeekSecondAbsolute`, on the active source's Transport (or Radio) when another source is selected |
| volume / mute | Volume (or Preamp) `SetVolume` scaled to `VolumeMax`, `SetMute` |
| clear | `DeleteAll` |
| before playing | leave standby and select the Playlist source, only if Product has those actions |

Each Jamarr queue item stores the renderer-assigned id. Queue edits must hold
a per-renderer lock from the stored write until the device has the edit, or a
reconciliation in the gap rebuilds the queue from the device and drops the
new items.

**Formats.** The Playlist's own `ProtocolInfo` (legacy `Ds.ProtocolInfo`) says
what the queue accepts, in the same shape as ConnectionManager
`GetProtocolInfo`, so the protocolInfo negotiation and playback plan that
AVTransport uses apply unchanged. Insert has no metadata stages to fall back
through.

**Stream tokens.** The device fetches each URL whenever it gets there, possibly
days later. Tokens must cover the wait plus playback, capped (7 days was the
prototype's default), and items still queued whose token nears expiry must be
swapped in place (`Insert` the fresh copy after the old id, then `DeleteId`),
never touching the playing item.

**Events.** Playlist (IdArray, Id, TransportState, Shuffle, Repeat), Time and
Volume, or their Linn equivalents, plus Product, Info, Radio and Transport
where present, subscribed through the same GENA manager as AVTransport
(`app/services/upnp/events.py`): one NOTIFY server, shared renewal, backoff
and health. Healthy only when Playlist, Time and Volume all are; otherwise
poll, bounded (2 s while playing, 15 s otherwise). The IdArray is the queue:
ids another controller inserted are resolved with `ReadList`, and ones
pointing at `/api/stream/<id>` become Jamarr tracks. The current `Id` becomes
`current_index`, and history runs off it once per play. Jamarr never advances
the queue itself.

**Other sources.** Product `SourceIndex`/`SourceXml` say which source is
active. While it is not the Playlist (radio, an input, a streaming service),
transport controls go to that source's Transport (or Radio) service, and
**Info** describes what plays.

## Decision

**No OpenHome backend ships.** With no OpenHome device available, the
prototype could only be checked against fakes written from the same reading
of the specification, which proves nothing about real firmware. The design
above is the starting point if one is built.

## Consequences

- OpenHome-only renderers are not offered. Devices that also speak
  AVTransport play through the UPnP backend, without device-side
  shuffle/repeat/standby/source or a shared multi-controller playlist.
- The capability contract keeps `queue_ownership` / `queue_operations`
  ([ADR-0006](0006-renderer-capability-contract.md)), so a renderer-owned
  backend can be added without changing the API.
- To build it, test against a real device first. Without Linn hardware,
  [upmpdcli](https://www.lesbonscomptes.com/upmpdcli/) (a software OpenHome
  renderer on MPD) is a practical test device, though not a substitute for
  Linn firmware.
- The OpenHome bridge facade in [ADR-0009](0009-dlna-server-and-bridge-roles.md)
  depends on this backend existing.
