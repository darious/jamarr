# Implementation Plan - Scanner Refactor v2

This plan outlines the steps to refactor the Jamarr scanner to strict "Brand New" specifications, focusing on modularity (`services` package), correctness (`quick_hash` change detection), and performance (SQL-level filtering).

## User Review Required
> [!IMPORTANT]
> **Database Schema Update**: The [track](file:///root/code/jamarr/app/scanner/core.py#2051-2086) table requires new columns: `size_bytes` (BIGINT) and `quick_hash` (BYTEA). You must run the provided SQL migration before starting the new scanner.

## Proposed Changes

### 1. Database Schema
#### [NEW] [migration_v2.sql](file:///root/code/jamarr/scripts/migration_v2.sql)
- Add columns to [track](file:///root/code/jamarr/app/scanner/core.py#2051-2086):
    - `size_bytes` (BIGINT).
    - `quick_hash` (BYTEA) - **BLAKE3-256** (32 bytes).

### 2. Backend Services (Refactor [metadata.py](file:///root/code/jamarr/app/scanner/metadata.py))
**Goal**: Split the monolithic [metadata.py](file:///root/code/jamarr/app/scanner/metadata.py) into focused, reusable service modules.

#### [NEW] `app/scanner/services/`
- `__init__.py`: Expose key classes.
- `coordinator.py`: `MetadataCoordinator` (Orchestrator for parallel fetching).
- `musicbrainz.py`: `fetch_core`, `fetch_singles` (Strict Rate Limiting).
- `lastfm.py`: `fetch_top_tracks`, `fetch_similar` (MBID-keyed).
- [artwork.py](file:///root/code/jamarr/app/scanner/artwork.py): [fetch_fanart](file:///root/code/jamarr/app/scanner/metadata.py#94-138), `fetch_spotify(spotify_id)` (Strictly ID-based fallback).
- `wikipedia.py`: `fetch_bio(url)` (Strictly URL-based).
- `wikidata.py`: `fetch_links` (External ID resolution).

#### [DELETE] [app/scanner/metadata.py](file:///root/code/jamarr/app/scanner/metadata.py)
- Once functionality is moved to `services/`.

### 3. Core Logic ([app/scanner/core.py](file:///root/code/jamarr/app/scanner/core.py))
**Goal**: Implement the "File Change Detection Strategy" and strict MBID usage.

#### [MODIFY] [app/scanner/core.py](file:///root/code/jamarr/app/scanner/core.py)
- **[scan_filesystem](file:///root/code/jamarr/app/scanner/core.py#52-360)**:
    - **Wipe Logic**: Use `WHERE path LIKE $1 || '/%'` (normalized with trailing slash) to safely scope deletions.
    - Update DB cache pre-fetch to include `size_bytes`, `quick_hash`.
    - **Change Detection**:
        - Check `mtime` and `size_bytes` against DB.
        - **ONLY** compute `quick_hash` if:
            1. New File.
            2. Mtime or Size differs.
            3. DB Hash is NULL (Legacy).
    - **Legacy Optimization**: If matches mtime+size but no hash -> Compute Hash -> **Update Full Signature** (quick_hash + size + mtime) to ensure consistency.
- **[process_file](file:///root/code/jamarr/app/scanner/core.py#554-752)**:
    - Add **MBID Validation Gate**: Log & Skip if `artist_mbid` **OR** `release_group_mbid` missing.
    - **Atomic Upsert**: Use `INSERT ... ON CONFLICT (path) DO UPDATE SET ...` to update tags + `size_bytes` + `quick_hash` atomically.
    - **Error Handling**: Catch IO/Permission errors during hashing -> Log & Skip file.
- **`get_artists_for_enrichment`**:
    - Implement the Optimized SQL Query builder (filtering by path, missing columns, etc).

### 4. Orchestrator ([app/scanner/scan_manager.py](file:///root/code/jamarr/app/scanner/scan_manager.py))
**Goal**: Align with new [ScanRequest](file:///root/code/jamarr/app/api/scan.py#12-29) API and Phase 1-2-3 lifecycle.

#### [MODIFY] [app/scanner/scan_manager.py](file:///root/code/jamarr/app/scanner/scan_manager.py)
- Update [start_scan](file:///root/code/jamarr/app/scanner/scan_manager.py#125-139) to accept the new config dict.
- Rewrite [_run_scan](file:///root/code/jamarr/app/scanner/scan_manager.py#140-181) to follow the sequence:
    1.  **Filesystem** (Conditional)
    2.  **Metadata** (Conditional, using `get_artists_for_enrichment` + `MetadataManager`)
    3.  **Prune** (Always)
- Update `broadcast_event` to send `progress_current`/`total` and `api_stats`.

### 5. API ([app/api/scan.py](file:///root/code/jamarr/app/api/scan.py))
#### [MODIFY] [app/api/scan.py](file:///root/code/jamarr/app/api/scan.py)
- Update Pydantic models to match the new [ScanRequest](file:///root/code/jamarr/app/api/scan.py#12-29) JSON schema.

## Comprehensive Verification Plan & Test Suite

To ensure 100% logic coverage, the following test suites will be constructed.

### 1. File Change Detection Matrix (`tests/unit/test_scanner_change_detection.py`)
**Goal**: Verify the "Composite Change Signature" logic in `Scanner.scan_filesystem`.
| Case | DB Mtime | DB Size | DB Hash | File Mtime | File Size | File Hash | Expected Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **NoOp** | Match | Match | Match | Match | Match | Match | **SKIP** (Unchanged) |
| **Mtime Change** | Old | Match | Match | **NEW** | Match | Match | **PROCESS** (Changed) |
| **Size Change** | Match | Old | Match | Match | **NEW** | **NEW** | **PROCESS** (Changed) |
| **Content Change** | Match | Match | Old | Match | Match | **NEW** | **SKIP** (Non-detectable optimization) |
| **Legacy Record** | Match | Match | **NULL** | Match | Match | **CALC** | **UPDATE FULL SIGNATURE** (Optimize) |
| **New File** | **NULL** | **NULL** | **NULL** | Exists | Exists | **CALC** | **PROCESS** (New Insert) |

### 2. File Processing Logic (`tests/unit/test_scanner_process_file.py`)
**Goal**: Verify strict MBID validation and tag extraction.
*   **Case 2.1**: File has `artist_mbid` + `release_group_mbid`. -> **SUCCESS** (Atomic Upsert).
*   **Case 2.2**: File missing `artist_mbid`. -> **SKIP** (Log Warning).
*   **Case 2.3**: File missing `release_group_mbid`. -> **SKIP** (Log Warning).
*   **Case 2.4**: File has valid logic but DB Constraint Error. -> **HANDLE** (Log Error, continue).
*   **Case 2.5**: File has Embedded Art. -> **EXTRACT** (Save to Cache, Hash, Link).
*   **Case 2.6**: File has NO Art. -> **NOOP**.
*   **Case 2.7**: **IO/Permission Error** during Hash/Read. -> **SKIP** (Log Error).
*   **Case 2.8**: **Path Normalization**. -> Test trailing slashes and Unicode inputs.
*   **Case 2.9**: **Hash Invariant**. -> Verify `len(quick_hash) == 32`. If not, treat as Legacy -> Recompute.

### 3. Service Isolation Tests (`tests/unit/services/`)
**Goal**: Verify each `app.scanner.services.*` module independently (Mocked HTTP).

#### 3.1 `test_service_musicbrainz.py`
*   **Core**: Valid MBID -> Returns Dict. Invalid MBID -> Returns None. 404/500 -> Handle Gracefully.
*   **RateLimit**: Fire 5 requests in <0.5s -> Verify total duration >= 5s (1 req/sec).
*   **NetworkError**: Simulate Timeout -> Retry X times or Fail Cleanly.

#### 3.2 `test_service_artwork.py`
*   **Fanart Success**: Returns `{thumb, background}`.
*   **Fanart Fail -> Spotify Success**: Returns `{thumb}` from Spotify.
*   **Fanart Fail -> Spotify Fail**: Returns `{thumb: None}`.
*   **Spotify RateLimit**: Simulate 429 -> Verify Backoff/Wait behavior.

#### 3.3 `test_service_lastfm.py`
*   **TopTracks**: Valid Artist -> Returns List[Track]. Empty -> Returns [].
*   **Similar**: Valid Artist -> Returns List[MBID]. No Matches -> Returns [].

### 4. Orchestrator State Machine (`tests/integration/test_scan_manager.py`)
**Goal**: Verify [ScanManager](file:///root/code/jamarr/app/scanner/scan_manager.py#13-645) handles all configuration permutations.

| Test ID | Scan FS? | Force? | Missing Only? | Options (Enrich) | Expected Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **INT-01** | **YES** | **True** | - | {} (None) | **Wipe DB** -> Scan FS -> No Enrich. |
| **INT-02** | **YES** | **False** | - | {} (None) | **Diff DB** -> Scan FS -> No Enrich. |
| **INT-03** | **NO** | - | **True** | {All: True} | Bypass FS -> Query DB (WHERE missing) -> Enrich 6 Branches. |
| **INT-04** | **NO** | - | **False** | {Bio: True} | Bypass FS -> Query DB (All) -> Enrich Bio Only. |
| **INT-05** | **NO** | - | - | {Art: True} | Bypass FS -> Query DB (All) -> Enrich Art (Fanart->Spot). |
| **INT-06** | **YES** | **False** | **True** | {All: True} | Scan FS -> **Feed Result Artists** to Enricher -> Enrich (Missing). |

### 5. API & Event Stream (`tests/api/test_scan_endpoints.py`)
*   **Start**: POST valid config -> 200 OK + JSON. Parallel POST -> 409 Conflict.
*   **Cancel**: POST cancel -> Manager sets Event -> Task stops gracefully.
*   **Events**: Connect SSE -> Receive "filesystem" items -> Receive "metadata" items -> Receive "idle". Verify Stats Counters increment.
