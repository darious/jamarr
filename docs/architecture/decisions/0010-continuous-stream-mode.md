# ADR-0010: Continuous-stream mode for seamless album playback on Cast

- **Status:** Proposed (evaluation; no implementation)
- **Date:** 2026-10-28 (#316, Priority 2: Cast queues/preloading)

## Context

Server Cast loads one track per `LOAD`. Each transition goes IDLE(FINISHED),
then the next LOAD, then the receiver buffers, so live albums and classical
works get audible gaps. #316 asks to evaluate two remedies:

- **Receiver queues and preloading** (`QUEUE_LOAD` / `QUEUE_INSERT`,
  `preloadTime`). This is being implemented separately in the Cast
  session/queue work. This ADR does not repeat it. A receiver queue preloads
  the next item, but **does not by itself prove gapless playback**: the Default
  Media Receiver may still tear down and re-create its decoder between items.
- **A continuous PCM/audio stream**: one long HTTP response that concatenates
  the tracks. The device sees one endless media item, so transitions happen
  inside Jamarr's encoder and can be sample-accurate.

## Evaluation of continuous-stream mode

| Concern | Effect |
|---|---|
| **Gapless** | Best possible: Jamarr decodes track N and N+1 into one PCM timeline. Encoder delay/padding is handled once, not per track. |
| **Seeking** | Receiver-side seek is lost or wrong. A live stream (`streamType: LIVE`, no Content-Length) is not seekable. A "seek" becomes *stop and reload the stream at a new offset*, which costs a full rebuffer. Within-track seek is server-driven. |
| **Metadata** | The receiver shows the first item's metadata. Per-track title/art needs Jamarr to push metadata updates. The Default Media Receiver does not reliably honour mid-stream updates; ICY metadata is not supported. In practice it needs a custom receiver, or accepting album-level metadata. |
| **Position / progress** | The receiver reports position in the *stream* timeline. Jamarr must map it back to (track, offset) and drive history/scrobbling from that mapping, not from receiver IDLE events. |
| **Buffering** | Receivers buffer ahead (several seconds or more). Queue edits, skips and pause are only audible after the buffered audio drains, so "skip" means reloading the stream. Pausing a live stream may make the receiver drop it after a timeout. |
| **Cancellation** | The encoder must stop when the receiver disconnects, and a reload must cancel the old pipeline. That requires one ffmpeg/encoder process per active session, with a hard owner and teardown. Today's cached, seekable transcodes cannot be reused. |
| **Format** | WAV/LPCM over HTTP has no length for an endless stream. FLAC (streamable, no seektable) or a lossless-compressed live stream fits better. The output must satisfy the device constraints the audio planner knows (`OutputConstraints`). |
| **Tokens** | One stream token must live for the whole session. That makes the open revocation question ([ADR-0003](0003-cast-stream-token-policy.md)) more pressing. |

## Decision

- Do **not** make continuous streaming the default for Cast. The receiver-queue
  work comes first. Then **measure transition silence on real receivers**
  before deciding whether continuous mode is needed at all.
- If measurement shows audible gaps with receiver queues, add continuous mode
  as an **opt-in per-renderer mode** for "seamless album" playback. It reports
  `queue_ownership: continuous_stream`
  ([ADR-0006](0006-renderer-capability-contract.md)), with
  `can_seek: false` (server-side reload instead) and server-pushed metadata.
  The UI shares queue concepts with server-owned queues.
- The same mode is the only route to gapless playback on AirPlay/RAOP
  ([ADR-0007](0007-airplay-raop.md)), where each track is otherwise a separate
  RTSP session.

## Consequences

- No code yet. The cost is a long-lived encoder per session, a stream-timeline
  mapping for history, and degraded seek/skip latency.
- **Unverified**:
    - transition silence with and without receiver queues
    - Default Media Receiver behaviour with endless FLAC/LPCM streams
    - how the receiver handles pause on a live stream
    - whether mid-stream metadata updates display
  None have been measured on hardware.
