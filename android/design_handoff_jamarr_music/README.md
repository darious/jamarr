# Handoff: Jamarr Music — Android App

## Overview

Jamarr Music is a personal music streaming / scrobble-tracking Android app. The design covers 7 screens navigable from a 4-tab bottom nav bar. This package is a **high-fidelity prototype** built in HTML/React and is the design reference for implementation.

## About the Design Files

The files in this bundle (`Jamarr Music.html`, `data.js`, `android-frame.jsx`) are **HTML design prototypes — not production code**. Open `Jamarr Music.html` in a browser to interact with the full prototype.

Your task is to **recreate these screens in your target Android codebase** (Jetpack Compose recommended) using its established patterns and libraries, matching the visual design as closely as possible. Do not ship the HTML directly.

---

## Fidelity

**High-fidelity.** Exact colors, typography, spacing, and interaction patterns are defined below. Recreate pixel-accurately.

---

## Design Tokens

### Colors

| Token | Hex | Usage |
|---|---|---|
| `bg` | `#150808` | App background |
| `surface` | `#1e0e0e` | Bottom nav, elevated surfaces |
| `card` | `#261212` | Cards, list items |
| `primary` | `#FF2D55` | Active states, play buttons, highlights |
| `tertiary` | `#00996E` | Positive indicators, chart rises |
| `text` | `#FFCDD2` | Primary text |
| `muted` | `#A1A1A2` | Secondary text, inactive nav icons |
| `neutral` | `#8B7171` | Track numbers, timestamps |
| `border` | `#2e1818` | Dividers, card borders |

### Typography

All text uses **Inter** (Google Fonts). Weights: 300, 400, 500, 600, 700.

| Role | Size | Weight |
|---|---|---|
| Screen title | 20px | 700 |
| Section header | 15px | 600 |
| Card title | 12–14px | 600 |
| Body / list item | 13px | 400 |
| Caption / metadata | 10–11px | 400 |
| Track number | 12px | 400 |

### Spacing

- Screen horizontal padding: **16px**
- Section gap: **24px**
- Card border radius: **10px**
- Album art border radius: **6px** (detail views: **10px**)
- List item vertical padding: **8–10px**

### Shadows / Elevation

- Play button: `box-shadow: 0 4px 16px #FF2D5555`
- Album hero: `box-shadow: 0 16px 48px #00000088`
- Mini player: `box-shadow: 0 -4px 20px #00000055`

---

## Screens & Views

### 1. Home Screen

**Purpose:** Entry point. Shows library overview with horizontal scroll sections.

**Layout (top → bottom):**
1. **Header row** — greeting text left, avatar (36×36 circle, primary bg, initial "J") right. `padding-top: 4px`, `margin-bottom: 14px`
2. **Search bar** — full width, 10px vertical padding, 36px left padding for search icon, border-radius 10, bg `card`. Clears with × button. Typing filters albums + artists inline, hides all sections below and shows a results list instead.
3. **New Releases** — horizontal scroll of album art cards (130×130px). Title 12px/600, artist 11px/muted.
4. **Recently Added** — horizontal scroll, 100×100px art.
5. **Recently Played** — horizontal scroll, 100×100px art.
6. **Artists** — 2-column grid. Each cell: `card` bg, 10px border-radius, 8px padding, `ArtistArt` (40px circle, conic gradient) + name + play count.

**AlbumArt component:** A `div` with `linear-gradient(135deg, albumColor, #150808)`, showing the first letter of each word in the title. This is the placeholder — replace with real cover art images.

**ArtistArt component:** A circular `div` with a `conic-gradient` based on artist name initial character code, showing the artist's first initial.

---

### 2. Artist Screen (Detail — pushed)

**Purpose:** Full artist profile. Accessed by tapping any artist.

**Layout:**
1. **Hero area** (height 200px) — `conic-gradient` background (unique per artist), artist name 26px/700, genre + play count subtitle. Back button (34×34 circle, semi-transparent black) top-left. Play button (44px) bottom-right.
2. **Links dropdown** — tapping "Links" toggles a card list of external links (Last.fm, MusicBrainz, Bandcamp, Wikipedia, Discogs, AllMusic). Each link is primary-colored, 13px/500.
3. **Top Tracks** — 3 pill tabs: Most Scrobbled / Most Listened / Singles. Below: list of up to 6 tracks, each showing rank number, 38×38 album art, title + album, play count + duration.
4. **Discography** — 6 pill tabs: Albums / Compilations / Live / EPs / Singles / Appears On. Below: vertical list of album entries (52×52 art, title, year + track count).
5. **Similar Artists** — horizontal scroll of artist circles (64px), name + genre below.

---

### 3. Album Screen (Detail — pushed)

**Purpose:** Album detail with full tracklist.

**Layout:**
1. **Hero** — `linear-gradient(180deg, albumColor, #150808)` background. Centred 180×180 album art with `box-shadow`. Album title 22px/700, artist name (tappable, primary color) 14px/500, year + track count + duration 12px/muted.
2. **Actions row** — Play button (48px, primary) left, 1px divider line, Shuffle button (outlined pill) right.
3. **Track list** — each row: track number (or play icon if active), title + scrobble count, duration right-aligned. Active track highlights in `#FF2D5511` bg with primary-colored title.

---

### 4. Charts Screen

**Purpose:** Weekly top 100 albums chart.

**Header:** "Charts" title + "Top 100 Albums · This Week" subtitle. No period filter.

**Podium (top 3):**
- Displayed in order: 2nd (left), 1st (center, largest), 3rd (right)
- 1st place: 80px art, `2px solid primary` border. Bar height 110px.
- 2nd place: 64px art. Bar height 90px.
- 3rd place: 64px art. Bar height 75px.
- All tappable → navigate to album screen.

**Full list (ranks 4–100):**
- Row: rank number (28px wide), 42×42 art, title + artist + year, change indicator + play count.
- Change indicators: green ▲N (up), red ▼N (down), — (unchanged), green "NEW" badge.
- All rows tappable → navigate to album screen.

---

### 5. Playlists Screen

**Purpose:** Browse all user playlists.

**Header:** "Playlists" title, count subtitle, Updated / A–Z sort toggle (top-right).

**List:** Each row — 54×54 `PlaylistArt` (gradient square with list icon), playlist name 14px/600, track count + last updated date 11px/muted, chevron right.

**Date formatting:** Today / Yesterday / "N days ago" / "D Mon" for older.

---

### 6. Playlist Detail Screen (Detail — pushed)

**Purpose:** View and play tracks in a playlist.

Identical layout pattern to the Album Screen:
1. **Hero** — playlist gradient background, 180×180 icon art (the list icon SVG, large), playlist name, track count.
2. **Actions** — Play + Shuffle.
3. **Track list** — each row: position number, title, artist · album subtitle, duration. Active track highlighted.
4. Footer: "+ N more tracks" if not all tracks are shown.

---

### 7. History Screen

**Purpose:** Ranked listening statistics with date filtering.

**Date filters (pill row):** Today / Last 7 Days / Last 30 Days / Custom. Selecting Custom reveals two date pickers (from / to).

**Tabs:** Tracks / Albums / Artists (3 equal-width buttons, active state = primary tint + border).

**Stats summary row:** 3 cards (tracks played, albums played, artists count) — 18px/700 value, 10px/muted label.

**Ranked list:** Each entry has:
- Rank number (#1–N), colored primary for top 3
- Art (ArtistArt circle for artists, AlbumArt square for albums, music-note icon for tracks)
- Name + artist/album subtitle
- Play count right-aligned (formatted as "4.8k")
- Progress bar below: full-width at rank 1, scaled proportionally. Colors: primary (#1), tertiary (#2–3), neutral (rest)

---

## Navigation & Interactions

### Bottom Navigation (4 tabs)

| Tab | Icon | Screen |
|---|---|---|
| Home | House icon | Home |
| Playlists | List-with-dots icon | Playlists list |
| Charts | Waveform icon | Charts |
| History | Clock-arrow icon | History |

Active tab: icon + label in `primary`. Inactive: `muted`.

### Detail Navigation

Artist, Album, Playlist screens are pushed onto a stack. A back button appears in the hero. The bottom nav is replaced by a single centered "← Back" bar at the bottom during detail views.

### Mini Player

Persistent strip above the bottom nav (or back bar). Shows current track art (36×36), title + artist, play/pause button. Always visible.

### State Persistence

Save the active tab to local storage so the app returns to the last-visited tab on cold start. Detail screens (artist/album/playlist) do not persist — always start on a root tab.

---

## Data Model

See `data.js` for the full mock data shape. Key entities:

```typescript
Artist { id, name, genre, scrobbles, listeners }
Album  { id, title, artist, artistId, year, tracks, type, color }
Track  { id, title, album, albumId, duration, scrobbles, listens }
Playlist { id, name, trackCount, updatedAt, color, tracks: PlaylistTrack[] }
PlaylistTrack { n, title, artist, album, duration }
ChartEntry { rank, title, artist, year, plays, peak, change }
HistoryEntry { title/name, artist/album, plays }
```

Album `type` values: `'album'` | `'compilation'` | `'live'` | `'ep'` | `'single'` | `'appears'`

Chart `change` values: integer (positive = up, negative = down, 0 = unchanged) | `'NEW'`

---

## Implementation Notes for Claude Code

1. **Framework:** Jetpack Compose is the recommended target. The prototype uses React but the component model maps cleanly.
2. **Album art:** Replace the gradient placeholder `AlbumArt` component with `AsyncImage` / `Coil` loading from your real art URLs. The gradient + initials is a fallback for when art is unavailable.
3. **Artist art:** Same — replace with real artist images. The conic-gradient initial avatar is the no-image state.
4. **Horizontal scrolls:** Use `LazyRow` in Compose.
5. **Chart + History lists:** Use `LazyColumn`.
6. **Search:** The search box on Home filters local data. Wire to your actual search API.
7. **Date pickers:** The custom range in History uses HTML `<input type="date">`. Use `DatePickerDialog` in Compose.
8. **Navigation:** Use Compose Navigation with a `NavHost`. Bottom tabs are top-level destinations; artist/album/playlist screens are nested routes.

---

## Files in This Package

| File | Purpose |
|---|---|
| `Jamarr Music.html` | Full interactive prototype — open in browser |
| `data.js` | Mock data (artists, albums, tracks, playlists, charts, history) |
| `android-frame.jsx` | Android device bezel component (prototype only, not needed in app) |
| `README.md` | This document |

---

## Getting Started with Claude Code

```bash
# In your project directory, start Claude Code and paste this prompt:
```

> I have a design handoff package for a music streaming Android app called Jamarr Music. The README.md contains the full spec. Please read README.md and data.js, then implement the screens in Jetpack Compose starting with the design tokens, then the bottom navigation, then the Home screen.
