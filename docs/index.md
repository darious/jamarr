<div class="jamarr-hero" markdown>
![Jamarr](assets/logo-text.png)
</div>

# Jamarr

**Self-hosted, web-based music controller.**

Scan a local music library, enrich it with metadata from MusicBrainz and Spotify,
then browse and play through a fast web UI. Supports local playback, UPnP
renderers (e.g. Naim Uniti Atom) with gapless queue management, and Chromecast.

## Features

- **Library scanning** — fast tag-based scan with incremental updates and MusicBrainz ID extraction
- **Rich metadata** — artist bios, artwork, similar artists, top tracks, external links
- **Local + UPnP + Cast playback** — local streaming, UPnP control, and Chromecast
- **Gapless playback** — via UPnP `SetNextAVTransportURI` queue management
- **Instant search** — across artists, albums, and tracks
- **History + Last.fm** — local playback history merged with matched Last.fm scrobbles
- **Recommendations** — artist/album/track recommendations from listening history
- **Playlists** — create and manage ordered playlists
- **Multiple clients** — SvelteKit web UI, terminal UI, and native Android (incl. Android Auto)

## Where to start

| If you want to… | Go to |
|---|---|
| Deploy Jamarr | [Install](getting-started/install.md) |
| Run it for development | [Dev Mode](getting-started/dev-mode.md) |
| Understand the system | [Architecture Overview](architecture/overview.md) |
| Call the API | [API Reference](reference/api.md) |
| Scan your music | [Scanning a Library](guides/scanning.md) |
| See what's planned | [Roadmap](roadmap.md) |

## How these docs stay current

The API reference and database schema are **generated from the code** on every
build (FastAPI OpenAPI + [tbls](https://github.com/k1LoW/tbls)), so they cannot
drift. Hand-written docs cover the *why* — architecture, design decisions
([ADRs](architecture/decisions/index.md)), and guides.

## License

Jamarr is licensed under the **GNU AGPL-3.0-only**. See `LICENSE` and
`THIRD_PARTY_NOTICES.md` in the repository.
