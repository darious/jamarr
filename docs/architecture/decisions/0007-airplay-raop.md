# ADR-0007: AirPlay/RAOP via pyatv — evaluated, not built

- **Status:** Accepted (evaluation; no backend ships)
- **Date:** 2026-10-29 (#316, Priority 3)

## Context

`airplay` is a recognised renderer kind with no backend. #316 asks for an
independent evaluation covering:

- URL playback versus streamed audio
- pairing, passwords and persistent credentials
- per-device features
- timing and latency
- session cleanup
- receiver generations, seeking, gapless playback and multiroom

The candidate library is [pyatv](https://pyatv.dev/), assessed from its
[streaming guide](https://pyatv.dev/development/stream/), its
[interface API](https://pyatv.dev/api/interface/), the 0.18.0 source, and a
prototype backend driven against two real receivers.

**Python 3.14.** pyatv 0.18.0 (June 2026) declares 3.14. Its native dependency
`miniaudio` ships cp314 manylinux wheels and the rest are pure Python. It adds
six packages (`chacha20poly1305-reuseable`, `miniaudio`, `pyatv`, `srptools`,
`tabulate`, `tinytag`).

**Two playback paths.**

| | `stream.play_url(url)` (AirPlay) | `stream.stream_file(src)` (RAOP) |
|---|---|---|
| Who fetches audio | the receiver fetches the URL | pyatv fetches/decodes, then pushes ALAC over RTP |
| Receivers | AirPlay *video* receivers only (Apple TV class) | AirPort Express, HomePod, AirPlay speakers, Apple TV |
| Formats | what the receiver decodes | MP3, WAV, FLAC, OGG decoded by miniaudio |
| Wire format | original bytes | ALAC at the receiver's mDNS `sr`/`ss`/`ch`, by default 44.1 kHz/16-bit/2 ch |
| Control | stop only (pause/seek need MRP on Apple TV) | stop, volume, metadata; "pause" = stop |
| Returns | when playback ends (request held open) | when the stream ends |

`play_url` is only offered when the receiver advertises an AirPlay video
feature flag (`SupportsAirPlayVideoV1/V2`); audio-only receivers never get it.
AirPlay 2 receivers that set `HasUnifiedAdvertiserInfo` take RAOP through the
AirPlay service, so the absence of a separate `_raop._tcp` record does not mean
"URL playback only".

**Pairing.** tvOS ≥ 10.2 and most AirPlay 2 receivers require device
authentication. `pyatv.pair()` → `begin()` / `pin()` / `finish()` yields a
credentials string that must be stored and passed back on every connect;
HomePods and some third-party receivers use transient pairing, which pyatv
does by itself without a PIN.

**Timing.** pyatv says playback starts about 2 s after streaming begins, from
receiver buffering it cannot shorten, and the receiver gives "no feedback if
anything is not working". pyatv has no PTP clock, so it cannot do **AirPlay 2
multiroom sync**.

**Seeking.** RAOP streams from the start; pyatv's RAOP `pause()` stops the
stream. `play_url` accepts a start position but has no mid-stream seek
without MRP.

**Gapless.** Each `stream_file` call is one RTSP session (SETUP → RECORD →
TEARDOWN). Track N+1 starts a new session with the ~2 s buffer, so gapless
playback is not achievable per track. Only a continuous stream could be
gapless ([ADR-0010](0010-continuous-stream-mode.md)).

## Hardware evaluation (2026-10-29)

A prototype backend (pyatv 0.18.0) was run against two AirPlay 2 receivers: an
audio streamer that advertises RAOP and a TV that advertises AirPlay only.

**Naim Uniti Atom** (AirPlay 2, firmware 3.11, `AirTunes/366.0`): nothing played.

- With `srptools` 2.0.0 (released 2026-10-26, three days earlier) every
  connection failed inside pyatv: `SRPClientSession.__init__() takes 2
  positional arguments but 3 were given`. srptools 2.0 made the private key
  keyword-only; pyatv 0.18 passes it positionally. Any pyatv user needs
  `srptools<2` until pyatv is fixed. This breaks all authentication and pairing,
  not just this receiver.
- With srptools pinned to 1.0.1, pyatv's AirPlay 2 RAOP session reached
  `SETUP`, but the receiver answered the text-metadata `SET_PARAMETER`
  (`application/x-dmap-tagged`) with **500**, which aborts the stream. Initial
  `volume` `SET_PARAMETER`s also got 500 (pyatv retries those).
- With text metadata suppressed, `RECORD`/`FLUSH` succeeded, but the audio
  UDP port refused the packets (`Connection refused`) within a second.
- Forcing AirPlay 1 (`protocol_version = 1`): the connection dropped after
  `ANNOUNCE`.

**Sony XR-65X90J TV** (AirPlay 2, `AirTunes/377.40.00`, pairing *Mandatory*):

- No video feature flag, so `play_url` is unavailable ("play_url is not
  supported"). Choosing the playback path from whether a separate RAOP service
  exists, as the prototype did, picks the one path this TV can never use.
- Through RAOP on the unified AirPlay service, pyatv paired **transiently
  without a PIN** and the TV played the stream.
- **pyatv sent `volume: -20.1` (its 33 % default) at stream start**, replacing
  the TV's own volume. The test track played very loud. Every stream start
  does this unless the caller passes a volume explicitly.
- Volume changes made with the TV remote arrived as pyatv events (`POST
  /command` on the event channel); the prototype ignored them.

**Prototype behaviour that was wrong on real hardware:**

- It reported `PLAYING` once a stream survived 3 s without failing. On the
  Naim the stream died about 10 s in, so it showed `PLAYING` while nothing
  played: the false `PLAYING` that #316's first priority removed elsewhere.
- pyatv's HTTP source waits its full 10 s read timeout at end of file while
  reading tags, which delays start.
- Resume restarted the track; track completion was never observed, because no
  track reached its end.

## Decision

**No AirPlay backend ships.** The `airplay` renderer kind stays reserved; the
prototype, its migration, API, web pairing UI and the pyatv dependency were
removed before merge.

pyatv 0.18 cannot stream to one of the two receivers tested at all, needs a
dependency pin to work at all, and overrides the receiver's volume on every
stream start. A backend built on it would need, at minimum, before being
offered:

- `srptools<2` (or a pyatv release that supports srptools 2);
- the playback path chosen from the feature flags (unified RAOP over the AirPlay
  service), never from the presence of a separate RAOP record;
- **no volume sent unless the user changed it in Jamarr**, and receiver-side
  volume changes followed from pyatv's events;
- `PLAYING` reported from receiver feedback, not from a timer;
- text metadata skipped for receivers that refuse it, without failing the
  stream;
- testing on each receiver family at an agreed time and volume.

## Consequences

- Jamarr cannot play to AirPlay receivers. Both receivers tested also speak
  UPnP AVTransport (and the TV Cast), which Jamarr supports.
- Revisit when pyatv supports srptools 2 and AirPlay 2 audio more completely,
  or if an AirPlay-only receiver becomes important. The hardware notes above
  are the starting test plan.
- A continuous-stream mode ([ADR-0010](0010-continuous-stream-mode.md)) would
  still be the only route to gapless AirPlay.
