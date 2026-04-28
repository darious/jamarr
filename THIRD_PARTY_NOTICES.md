# Third-Party Notices

Jamarr is licensed under `AGPL-3.0-only`. Third-party dependencies, assets, names, logos, and trademarks remain under their own licenses and ownership.

This file is a starting point for public repository notices. It is not a full generated software bill of materials.

## Runtime and Build Dependencies

Jamarr uses open-source dependencies from the Python, Node.js, and Android ecosystems. The lockfiles and manifests are the source of truth for exact versions:

- `pyproject.toml` and `uv.lock`
- `web/package.json` and `web/package-lock.json`
- `android/build.gradle.kts`, `android/app/build.gradle.kts`, and Gradle lock/cache metadata where applicable

At the time this notice was added, the declared dependency set was primarily permissive licenses such as MIT, BSD, ISC, Apache-2.0, Python-2.0, CC0-1.0, and 0BSD.

Known non-permissive or attribution-sensitive transitive frontend packages include:

- `@img/sharp-libvips-*`: `LGPL-3.0-or-later`
- `@img/sharp-wasm32`: `Apache-2.0 AND LGPL-3.0-or-later AND MIT`
- `caniuse-lite`: `CC-BY-4.0`

These notices should be regenerated or reviewed before publishing official binary releases.

## Service Names, Logos, and Trademarks

Jamarr includes references to external music and metadata services. Names, logos, and trademarks for third-party services are owned by their respective owners and are used only to identify integrations, links, or metadata sources.

This includes, where present in the repository or UI:

- Discogs
- fanart.tv
- Last.fm
- MusicBrainz
- Qobuz
- Spotify
- TIDAL
- Wikidata
- Wikipedia

Third-party logos and trademarks are not relicensed under Jamarr's `AGPL-3.0-only` license.

## Media and Metadata

Jamarr can fetch or display metadata, biographies, artwork, album images, artist images, and links from third-party services. That fetched content may be subject to separate copyright, database, API, or service terms.

Do not commit cached third-party artwork, private music files, API responses, or metadata dumps unless their license permits redistribution in this repository.

