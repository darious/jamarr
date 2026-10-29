# ADR-0008: Fire TV: no Fling; Matter Casting not viable for a server today

- **Status:** Proposed (evaluation; no implementation)
- **Date:** 2026-10-28 (#316, Priority 3)

## Context

#316 asks whether modern Fire TV support is worth adding. Requirements:
URL loading, metadata, serialized control commands and status callbacks behind
an explicit capability-aware adapter, with no new Amazon Fling dependency.

- **Fling**: Amazon ended standard support for the Fling SDK on 2026-03-05 and
  directs new work to Matter Casting. Its integration page now returns 404.
  Fling is ruled out.
- **Matter Casting**, from Amazon's
  [overview](https://developer.amazon.com/docs/fire-tv/overview-of-matter-casting.html)
  and [integration guide](https://developer.amazon.com/docs/fire-tv/matter-casting-integration.html)
  and the connectedhomeip `examples/tv-casting-app`. It has three roles:
    - **Player**: Fire TV (Fire OS 7+) or Echo Show.
    - **Content app**: an app *installed on the Fire TV* that declares Matter
      clusters (Content Launcher, Media Playback, Account Login, …) and
      receives `MATTER_COMMAND` intents through Amazon's Matter agent.
      Its manifest carries a vendor ID and product ID.
    - **Casting client**: Amazon documents only Android/iOS SDKs. The
      connectedhomeip repo has a C++ Linux sample client.
- **Onboarding** is User Directed Commissioning (UDC). The client joins the
  player's Matter fabric with an 8-digit passcode shown on the TV, once per
  player. The client must present a **Device Attestation Certificate**, and
  Amazon says production needs a valid DAC. In practice that means a CSA vendor
  ID and attestation chain, not the test vendor 0xFFF1 (65521) used in the
  examples.
- Casting drives *a content app*. Neither page says the player can play a bare
  URL without a cooperating app on the TV.

## Decision

Do **not** build a Fire TV backend now.

1. **Server-side Matter Casting client: not viable.** Python has no maintained
   binding for the casting client. The Linux path is a C++ sample built inside
   the connectedhomeip tree. Production attestation needs a DAC chain that a
   self-hosted, open-source server cannot ship credibly. And it would still need
   a Jamarr content app on the TV to play anything.
2. **What an adapter would need**, if revisited:
    - a Jamarr **content app** on Fire TV. The Android client is the natural
      base, but it has no Android TV/leanback manifest today. It would implement
      Content Launcher (LaunchURL/LaunchContent to a Jamarr track or queue),
      Media Playback (play/pause/seek/stop plus state attributes) and Account
      Login.
    - a casting client holding fabric credentials and a DAC.
    - a backend mapping those clusters onto `RendererBackend` and
      `SupportsStatusEvents`, with `pairing: required` (the UDC passcode).
3. **Pragmatic alternative**: a Fire TV can already sideload the Jamarr
   Android app and play locally. If server-driven control of such a device is
   wanted, the cheaper design is a Jamarr-native "remote client" renderer: the
   app registers with the server and takes commands over the existing
   authenticated channel. No Matter fabric, DAC or vendor registration is
   needed. That is a separate feature, not a Matter adapter.

## Consequences

- No Fling or Matter dependency is added. Fire TV owners use the Android app
  directly. If Amazon's DLNA/Cast apps are installed, they cover UPnP/Cast as
  any renderer.
- **Unverified**:
    - whether current Fire OS builds accept a third-party casting client with
      a development DAC
    - whether a Fire TV can play a URL with no content app
    - the Linux sample's state
  None of these were tested; no Fire TV was used.
- Revisit if the CSA/Amazon publish a server or desktop casting SDK with
  practical attestation, or if Jamarr gains an Android TV build.
