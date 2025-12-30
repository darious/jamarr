import asyncio
import logging
from app.scanner.stats import get_api_tracker
from app.db import get_pool
from app.scanner.services.utils import get_client
from app.scanner.services import musicbrainz, lastfm, artwork, wikidata, wikipedia
from app.scanner.artwork import download_and_save_artwork, upsert_artwork_record, upsert_image_mapping


logger = logging.getLogger("scanner.coordinator")

class MetadataCoordinator:
    def __init__(self, progress_cb=None):
        # Optional callback for UI progress updates (current, total, message)
        self.progress_cb = progress_cb
        self.pool = get_pool()

    async def update_metadata(self, artists: list, options: dict, local_release_group_ids_map: dict = None):
        """
        Main entry point for batch metadata update.
        artists: list of artist objects (dicts) from DB.
        options: dict of flags (fetch_metadata, fetch_artwork, etc.)
        """
        if not artists:
            return

        logger.info(f"Starting metadata update for {len(artists)} artists...")
        
        # Helper to get local RGs for an artist
        def get_local_rgs(mbid):
            if local_release_group_ids_map:
                return local_release_group_ids_map.get(mbid, set())
            return set()

        total_artists = len(artists)
        processed_count = 0
        results = []

        fetch_workers = min(total_artists, 5) or 1
        writer_workers = 2
        fetch_semaphore = asyncio.Semaphore(fetch_workers)
        queue: asyncio.Queue = asyncio.Queue()
        progress_lock = asyncio.Lock()

        async def fetch_artist(artist, client):
            mbid = artist.get("mbid")
            if not mbid:
                return
            local_rgs = get_local_rgs(mbid)
            async with fetch_semaphore:
                try:
                    payload = await self.process_artist(artist, options, local_rgs, fetch_only=True, client=client)
                except Exception as e:
                    payload = e
                await queue.put((artist, payload))
                async with progress_lock:
                    nonlocal processed_count
                    processed_count += 1
                    if self.progress_cb:
                        self.progress_cb(
                            processed_count,
                            total_artists,
                            f"Metadata: {artist.get('name') or artist.get('mbid')}",
                        )

        async def writer():
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    break
                artist, payload = item
                if isinstance(payload, Exception) or payload is None or payload is True:
                    results.append(payload if isinstance(payload, Exception) else True)
                    queue.task_done()
                    continue
                updates, art_res = payload
                mbid = artist["mbid"]
                try:
                    async with self.pool.acquire() as db:
                        await self.save_artist_metadata(db, mbid, updates, art_res)
                        get_api_tracker().track_processed("artists", mbid)
                        get_api_tracker().track_processed("artists_metadata", mbid)
                    results.append(True)
                except Exception as e:
                    logger.error(f"DB Save Error for {mbid}: {e}")
                    results.append(e)
                queue.task_done()

        writer_tasks = [asyncio.create_task(writer()) for _ in range(writer_workers)]
        
        fetch_tasks = []
        # Create shared client for this batch
        async with get_client() as client:
             # Redefine fetch_artist or just pass client? 
             # Since fetch_artist is a closure, we can just access 'client' if we define it inside?
             # But fetch_artist is defined above.
             # Let's redefine fetch_artist inside the context or pass client to it.
             # Easier to just change how we call process_artist inside fetch_artist.
             
             # Actually, simpler: define client before fetch_artist if possible, or pass it.
             # But fetch_artist is called by asyncio.create_task list comp.
             
             # Let's just wrap the gathering.
             
             fetch_tasks = [asyncio.create_task(fetch_artist(a, client)) for a in artists if a.get("mbid")]
             if fetch_tasks:
                 await asyncio.gather(*fetch_tasks)
        
        # Always signal writers to shut down (even if no artists processed)
        for _ in writer_tasks:
            await queue.put(None)
        
        # Only wait for queue if we processed artists
        if fetch_tasks:
            await queue.join()
        
        # Always wait for writer tasks to finish
        await asyncio.gather(*writer_tasks)

        success_count = 0
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Artist update failed: {res}")
            elif res:
                success_count += 1

        logger.info(f"Metadata update complete. updated {success_count}/{len(artists)} artists.")

    async def process_artist(self, artist, options, local_release_group_ids, fetch_only=False, client=None):
        """
        Enrich a single artist.
        """
        mbid = artist["mbid"]
        name = artist["name"]
        
        # Flags
        fetch_metadata = options.get("fetch_metadata", False)
        fetch_base_metadata = options.get("fetch_base_metadata", fetch_metadata) # Backwards compat
        # Links are not fetched by default; only when explicitly requested or needed for other branches
        fetch_links = options.get("fetch_links", False)
        fetch_artwork = options.get("fetch_artwork", False)
        fetch_spotify_artwork = options.get("fetch_spotify_artwork", False)
        
        # Map UI option names to internal names
        fetch_top_tracks = options.get("fetch_top_tracks") or options.get("refresh_top_tracks", False)
        fetch_singles = options.get("fetch_singles") or options.get("refresh_singles", False)
        fetch_similar_artists = options.get("fetch_similar_artists") or options.get("refresh_similar_artists", False)
        fetch_bio = options.get("fetch_bio", False)
        missing_only = options.get("missing_only", False)

        # Smart Skip if missing_only: only fetch branches that are missing data
        if missing_only:
            # Base metadata/links: skip only if we already have core metadata AND links.
            if fetch_base_metadata:
                have_links = any(
                    artist.get(f)
                    for f in [
                        "homepage",
                        "spotify_url",
                        "wikipedia_url",
                        "qobuz_url",
                        "tidal_url",
                        "lastfm_url",
                        "discogs_url",
                    ]
                )
                has_core = bool(artist.get("name"))
                if has_core and have_links:
                    fetch_base_metadata = False

            # Bio
            if fetch_bio and artist.get("bio"):
                fetch_bio = False

            # Artwork: fetch only if missing OR current image is Spotify (allow Fanart upgrade). Spec: missing_only_art node.
            if artist.get("image_url") and artist.get("image_source") != "spotify":
                fetch_artwork = False
                fetch_spotify_artwork = False

            # Links: if we already have at least one link, skip link refresh
            if fetch_links and any(
                artist.get(f)
                for f in [
                    "homepage",
                    "spotify_url",
                    "wikipedia_url",
                    "qobuz_url",
                    "tidal_url",
                    "lastfm_url",
                    "discogs_url",
                ]
            ):
                fetch_links = False

            # Top tracks / similar / singles: skip if already populated
            if fetch_top_tracks and (artist.get("top_tracks") or artist.get("has_top_tracks")):
                fetch_top_tracks = False

            if fetch_similar_artists and (artist.get("similar_artists") or artist.get("has_similar")):
                fetch_similar_artists = False

            if fetch_singles and (artist.get("singles") or artist.get("has_singles")):
                fetch_singles = False
                
        updates = {
            # updated_at is handled in save_artist_metadata via NOW()
        }
        
        spotify_candidates = []
        wikidata_url = None
        
        # Determine if we actually need links (for bio or spotify art) based on missing data
        need_links_for_bio = fetch_bio and not artist.get("wikipedia_url")
        need_links_for_spotify = fetch_spotify_artwork and not artist.get("spotify_url")
        effective_fetch_links = fetch_links or need_links_for_bio or need_links_for_spotify

        # Enforce fanart-first, Spotify fallback
        fanart_requested = fetch_artwork or fetch_spotify_artwork

        # If nothing to fetch, short-circuit
        any_fetch = any(
            [
                fetch_base_metadata,
                effective_fetch_links,
                fanart_requested,
                fetch_top_tracks,
                fetch_similar_artists,
                fetch_singles,
                fetch_bio,
                fetch_spotify_artwork and not artist.get("image_url"),
            ]
        )
        if not any_fetch:
            return True if fetch_only else True

        async with get_client(client) as client:
            
            # --- PARALLEL BLOCK 1: Core Services ---
            tasks = []
            
            # 1. MB Core (Relations, Genres, Basic Info)
            if fetch_base_metadata or effective_fetch_links:
                 res = musicbrainz.fetch_core(mbid, client, artist_name=name)
                 tasks.append(res)
                 # We can't track result here easily as it's async task. 
                 # Wait, tasks.append appends a coroutine. 
                 # The coordinator gathers them later. 
                 # We need to wrap them or track inside the service?
                 # Or track after gather?
                 # The implementation plan said "Call track_detailed ... in process_artist".
                 # But process_artist builds a list of tasks and gathers them.
                 # I cannot inspect result immediately.
                 # Ah, the architecture is: tasks.append(coro). Then await asyncio.gather(*tasks).
                 # Wait, looking at the file...
                 # It does: `results = await asyncio.gather(*tasks, return_exceptions=True)`
                 # Then iterates results.
                 # So I should track stats *after* the gather, when processing results.
            else:
                 tasks.append(asyncio.sleep(0, result=None))

            # 2. Fanart (always before Spotify when either artwork option is requested)
            if fanart_requested:
                tasks.append(artwork.fetch_fanart_artist_images(mbid, client))
            else:
                tasks.append(asyncio.sleep(0, result={}))

            # 3. Last.fm Top Tracks
            if fetch_top_tracks:
                tasks.append(lastfm.fetch_top_tracks(mbid, name, client))
            else:
                tasks.append(asyncio.sleep(0, result=None))
                
            # 4. Last.fm Similar
            if fetch_similar_artists:
                 tasks.append(lastfm.fetch_similar_artists(mbid, name, client))
            else:
                 tasks.append(asyncio.sleep(0, result=None))
                 
            # 5. Last.fm URL (Links)
            if effective_fetch_links:
                 tasks.append(lastfm.fetch_artist_url(mbid, client))
            else:
                 tasks.append(asyncio.sleep(0, result=None))

            # 6. Singles (MB)
            if fetch_singles:
                tasks.append(musicbrainz.fetch_release_groups(mbid, "single", client, artist_name=name))
            else:
                tasks.append(asyncio.sleep(0, result=None))

            # 7. Albums/EPs (MB - for linking)
            if fetch_base_metadata:
                 tasks.append(musicbrainz.fetch_release_groups(mbid, "album", client, artist_name=name))
                 tasks.append(musicbrainz.fetch_release_groups(mbid, "ep", client, artist_name=name))
            else:
                 tasks.append(asyncio.sleep(0, result=None))
                 tasks.append(asyncio.sleep(0, result=None))


            # Execute Block 1
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log any exceptions
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"[{name}] Task {i} failed: {result}")
            
            # Unpack
            mb_core_res = results[0]
            if isinstance(mb_core_res, dict) and (fetch_base_metadata or effective_fetch_links):
                updates.update({k: v for k, v in mb_core_res.items() if not k.startswith("_")})
                spotify_candidates = mb_core_res.get("_spotify_candidates", [])
                wikidata_url = mb_core_res.get("wikidata_url")
                wikidata_url = mb_core_res.get("wikidata_url")
                logger.info(f"[{name}] MusicBrainz: {len(mb_core_res)} fields, wikidata={'yes' if wikidata_url else 'no'}")
                get_api_tracker().track_detailed("MusicBrainz Core", "found")
            elif fetch_base_metadata or effective_fetch_links:
                get_api_tracker().track_detailed("MusicBrainz Core", "missing")
            
            fanart_res = results[1]
            if isinstance(fanart_res, dict):
                thumb_url = fanart_res.get("image_url") or fanart_res.get("thumb")
                bg_url = fanart_res.get("background")
                if thumb_url:
                    updates["image_url"] = thumb_url
                    updates["image_source"] = "fanart"
                if bg_url:
                    updates["background_url"] = bg_url
                logger.info(f"[{name}] Fanart.tv: thumb={'yes' if thumb_url else 'no'}, background={'yes' if bg_url else 'no'}")
                get_api_tracker().track_detailed("Fanart", "found" if thumb_url or bg_url else "missing")
            elif fanart_requested:
                get_api_tracker().track_detailed("Fanart", "missing")
                
            top_tracks_res = results[2]
            if isinstance(top_tracks_res, list):
                updates["top_tracks"] = top_tracks_res
                logger.info(f"[{name}] Last.fm Top Tracks: {len(top_tracks_res)} tracks")
                get_api_tracker().track_detailed("Top Tracks", "found" if top_tracks_res else "missing")
            elif fetch_top_tracks:
                get_api_tracker().track_detailed("Top Tracks", "missing")
                
            similar_res = results[3]
            if isinstance(similar_res, list):
                updates["similar_artists"] = similar_res
                logger.info(f"[{name}] Last.fm Similar: {len(similar_res)} artists")
                get_api_tracker().track_detailed("Similar Artists", "found" if similar_res else "missing")
            elif fetch_similar_artists:
                 get_api_tracker().track_detailed("Similar Artists", "missing")
                
            lfm_url = results[4]
            if lfm_url:
                updates["lastfm_url"] = lfm_url
                
            singles_res = results[5]
            if isinstance(singles_res, list):
                updates["singles"] = singles_res
                logger.info(f"[{name}] MusicBrainz Singles: {len(singles_res)} singles")
                get_api_tracker().track_detailed("Singles", "found" if singles_res else "missing")
            elif fetch_singles:
                get_api_tracker().track_detailed("Singles", "missing")
                
            albums_res = results[6]
            eps_res = results[7]
            
            # Combine albums and EPs and filter
            all_albums = []
            if isinstance(albums_res, list):
                all_albums.extend(albums_res)
            if isinstance(eps_res, list):
                all_albums.extend(eps_res)
            
            if all_albums and local_release_group_ids:
                updates["albums"] = [a for a in all_albums if a["mbid"] in local_release_group_ids]
            
            
            # --- BLOCK 2: Dependent Services (Wikidata, Wikipedia, Spotify) ---
            
            # 8. Wikidata Links & Wiki URL (Depends on MB Core)
            logger.debug(f"[{name}] Starting Block 2: Wikidata/Wiki/Spotify")
            target_wiki_url = updates.get("wikipedia_url")
            logger.debug(f"[{name}] Block 2 Vars: wikidata={wikidata_url}, wiki_url={target_wiki_url}, eff_links={effective_fetch_links}, bio={fetch_bio}, sp_art={fetch_spotify_artwork}")
            
            existing = {
                "spotify_url": updates.get("spotify_url"),
                "tidal_url": updates.get("tidal_url"),
                "qobuz_url": updates.get("qobuz_url"),
                "lastfm_url": updates.get("lastfm_url"),
                "discogs_url": updates.get("discogs_url"),
                "homepage": updates.get("homepage"),
            }

            if wikidata_url and (effective_fetch_links or need_links_for_bio):
                logger.debug(f"[{name}] Entering Wikidata Block")
                # Fetch missing links if needed
                
                # We need title for Bio if not present
                if not target_wiki_url:
                    target_wiki_url = await wikidata.fetch_wikipedia_title(client, wikidata_url)
                    if target_wiki_url:
                         # normalize to url
                         target_wiki_url = f"https://en.wikipedia.org/wiki/{target_wiki_url}"
                         updates["wikipedia_url"] = target_wiki_url
                
                if effective_fetch_links:
                    logger.debug(f"[{name}] Fetching Wikidata external links for {wikidata_url}")
                    wd_links = await wikidata.fetch_external_links(client, wikidata_url, existing)
                    updates.update(wd_links)
                    get_api_tracker().track_detailed("External Links", "found" if wd_links else "missing")
            elif effective_fetch_links and not existing.get("spotify_url"):
                # If we intended to fetch but couldn't (no wikidata url)
                get_api_tracker().track_detailed("External Links", "missing")

            # 9. Wikipedia Bio (Depends on Wiki URL)
            logger.debug(f"[{name}] Checking Bio Block (url={target_wiki_url})")
            if fetch_bio and target_wiki_url:
                logger.debug(f"[{name}] Fetching Wikipedia Bio for {target_wiki_url}")
                bio = await wikipedia.fetch_bio(client, target_wiki_url)
                if bio:
                    updates["bio"] = bio
                    logger.info(f"[{name}] Wikipedia Bio: {len(bio)} chars")
                    get_api_tracker().track_detailed("Bio", "found")
                else:
                    logger.info(f"[{name}] Wikipedia Bio: not found")
                    get_api_tracker().track_detailed("Bio", "missing")
            elif fetch_bio:
                get_api_tracker().track_detailed("Bio", "missing")

            # 10. Spotify Artwork (Dependent on candidates or resolved link). Only as fallback after Fanart.
            logger.debug(f"[{name}] Checking Spotify Block (candidates={len(spotify_candidates) if spotify_candidates else 0})")
            if fetch_spotify_artwork and not updates.get("image_url"):
                # Try to resolve ID
                sp_id = None
                sp_url = updates.get("spotify_url") or artist.get("spotify_url")
                
                # Extract from URL if present
                if sp_url:
                     parts = sp_url.split("/")
                     if parts: 
                         sp_id = parts[-1].split("?")[0]
                
                # Or resolve from candidates
                if not sp_id and spotify_candidates:
                    logger.debug(f"[{name}] Resolving Spotify ID from {len(spotify_candidates)} candidates")
                    sp_id, sp_res_url = await artwork.resolve_spotify_id(spotify_candidates, name, client)
                    if sp_res_url:
                        updates["spotify_url"] = sp_res_url
                        
                if sp_id:
                    # Fetch Image
                    logger.debug(f"[{name}] Fetching Spotify Image for {sp_id}")
                    img = await artwork.fetch_spotify_artist_images(sp_id, client)
                    if img:
                        updates["image_url"] = img
                        updates["image_source"] = "spotify"
                        get_api_tracker().track_detailed("Spotify Art", "found")
                
            if fetch_spotify_artwork and not updates.get("image_url") and not updates.get("image_source") == "spotify":
                 get_api_tracker().track_detailed("Spotify Art", "missing")

            # Download Artwork (thumb + optional background)
            logger.debug(f"[{name}] Checking Download Block (img={updates.get('image_url')})")
            art_res = {"thumb": None, "background": None}
            if updates.get("image_url"):
                try:
                    logger.debug(f"[{name}] Downloading artwork from {updates['image_url']}")
                    art_res["thumb"] = await download_and_save_artwork(updates["image_url"], art_type="artistthumb")
                except Exception as e:
                    logger.warning(f"Failed to download artist thumb for {mbid}: {e}")

            if updates.get("background_url"):
                try:
                    art_res["background"] = await download_and_save_artwork(updates["background_url"], art_type="artistbackground")
                except Exception as e:
                    logger.warning(f"Failed to download artist background for {mbid}: {e}")

            if fetch_only:
                return updates, art_res

        if fetch_only:
            # If no meaningful updates/art, return True to signal skip
            if not updates and not art_res:
                return True
            return updates, art_res

        return True

    async def save_artist_metadata(self, db, mbid, data, art_res=None):
        """
        Persist metadata to DB.
        """
        # This logic needs to update 'artist', 'external_link', 'top_track', 'similar_artist', 'artist_genre',
        # 'missing_album' (from singles/albums lists).

        # Since this method logic is DB heavy, it might belong in Core or here if using db directly.
        try:
             async with db.transaction():
                     # Upsert Artwork (thumb + background)
                     artwork_id = None
                     background_id = None
                     if art_res:
                         # Normalize shape: allow dict with thumb/background or single art dict
                         if isinstance(art_res, dict):
                             thumb_res = art_res.get("thumb")
                             bg_res = art_res.get("background")
                         else:
                             thumb_res = art_res
                             bg_res = None

                         if thumb_res:
                             try:
                                 artwork_id = await upsert_artwork_record(db, thumb_res.get("sha1"), meta=thumb_res.get("meta"), source=data.get("image_source"), source_url=data.get("image_url"))
                                 if artwork_id:
                                     await upsert_image_mapping(db, artwork_id, "artist", mbid, "artistthumb")
                                     data["artwork_id"] = artwork_id
                             except Exception as e:
                                 logger.error(f"Artwork Save Error (thumb): {e}")

                         if bg_res:
                             try:
                                 background_id = await upsert_artwork_record(db, bg_res.get("sha1"), meta=bg_res.get("meta"), source=data.get("image_source"), source_url=data.get("background_url"))
                                 if background_id:
                                     await upsert_image_mapping(db, background_id, "artist", mbid, "artistbackground")
                             except Exception as e:
                                 logger.error(f"Artwork Save Error (background): {e}")

                     # 1. Update Artist Table
                     cols = []
                     vals = []
                     i = 1
                     
                     for key in ["name", "sort_name", "bio", "image_url", "artwork_id"]:
                         if key in data and data[key] is not None:
                             cols.append(f"{key} = ${i}")
                             vals.append(data[key])
                             i += 1
                     
                     # Always update timestamp
                     cols.append("updated_at = NOW()")
                             
                     if cols:
                         vals.append(mbid)
                         await db.execute(
                             f"UPDATE artist SET {', '.join(cols)} WHERE mbid = ${i}",
                             *vals
                         )
                     
                     # 2. External Links
                     links = []
                     for k in ["spotify_url", "tidal_url", "qobuz_url", "lastfm_url", "discogs_url", "homepage", "musicbrainz_url", "wikipedia_url", "wikidata_url"]:
                         if data.get(k):
                             l_type = k.replace("_url", "")
                             links.append((l_type, data[k]))
                             
                     for l_type, url in links:
                         await db.execute("""
                             INSERT INTO external_link (entity_type, entity_id, type, url)
                             VALUES ('artist', $1, $2, $3)
                             ON CONFLICT (entity_type, entity_id, type) DO UPDATE SET url = EXCLUDED.url
                         """, mbid, l_type, url)

                     # 3. Top Tracks (Replace all for this type)
                     if "top_tracks" in data:
                         await db.execute("DELETE FROM top_track WHERE artist_mbid = $1 AND type = 'top'", mbid)
                         for t in data["top_tracks"]:
                             await db.execute("""
                                 INSERT INTO top_track (artist_mbid, type, external_name, rank, popularity, external_mbid)
                                 VALUES ($1, 'top', $2, $3, $4, $5)
                             """, mbid, t["name"], int(t["rank"]), int(t["popularity"]), t["mbid"])

                     # 4. Singles (MusicBrainz singles go into top_track with type='single')
                     if "singles" in data:
                        await db.execute("DELETE FROM top_track WHERE artist_mbid = $1 AND type = 'single'", mbid)
                        
                        for i, s in enumerate(data["singles"], start=1):
                            await db.execute("""
                                INSERT INTO top_track (artist_mbid, type, external_name, external_album, external_date, external_mbid, rank)
                                VALUES ($1, 'single', $2, $3, $4, $5, $6)
                                ON CONFLICT (artist_mbid, type, external_mbid) DO NOTHING
                            """, mbid, s["title"], s.get("album"), s.get("date"), s["mbid"], i)
                            
                     # 5. Similar Artists
                     if "similar_artists" in data:
                         await db.execute("DELETE FROM similar_artist WHERE artist_mbid = $1", mbid)
                         for i, s in enumerate(data["similar_artists"], start=1):
                             await db.execute("""
                                 INSERT INTO similar_artist (artist_mbid, similar_artist_name, similar_artist_mbid, rank)
                                 VALUES ($1, $2, $3, $4)
                             """, mbid, s["name"], s["mbid"], i)

                     # 6. Genres
                     if "genres" in data:
                         await db.execute("DELETE FROM artist_genre WHERE artist_mbid = $1", mbid)
                         for g in data["genres"]:
                             await db.execute("""
                                 INSERT INTO artist_genre (artist_mbid, genre, count)
                                 VALUES ($1, $2, $3)
                             """, mbid, g["name"], g["count"])
                             
        except Exception as e:
            logger.error(f"DB Save Error for {mbid}: {e}")

    async def scan_missing_albums(self, artist_filter=None, mbid_filter=None):
        """
        Scans for missing albums (Release Groups) from MusicBrainz for local artists.
        """
        logger.info("Starting Missing Albums Scan...")
        from app.tidal import TidalClient, year_from_date
        
        try:
             # 1. Get Artists
             query = "SELECT DISTINCT a.mbid, a.name FROM artist a"
             params = []
             clauses = []
             joins = []
             
             if mbid_filter:
                 if isinstance(mbid_filter, (list, set, tuple)):
                     filtered = [m for m in mbid_filter if m]
                     if filtered:
                         clauses.append(f"a.mbid = ANY(${len(params) + 1}::text[])")
                         params.append(filtered)
                 else:
                     clauses.append(f"a.mbid = ${len(params) + 1}")
                     params.append(mbid_filter)
             elif artist_filter:
                 clauses.append(f"a.name ILIKE ${len(params) + 1}")
                 params.append(f"%{artist_filter}%")
             else:
                 joins.append("JOIN artist_album aa ON a.mbid = aa.artist_mbid")
                 
             if joins:
                 query += " " + " ".join(joins)
             if clauses:
                 query += " WHERE " + " AND ".join(clauses)
                 
             artists = await self.db.fetch(query, *params)
             
             total = len(artists)
             processed = 0
             
             async with get_client() as client:
                 tidal_client = TidalClient()
                 
                 for row in artists:
                     processed += 1
                     mbid, name = row["mbid"], row["name"]
                     current_name = name or "Unknown"
                     
                     # Local RGs
                     rows = await self.db.fetch("SELECT album_mbid FROM artist_album WHERE artist_mbid = $1", mbid)
                     local_rgs = {r[0] for r in rows}
                     
                     await self.db.execute("DELETE FROM missing_album WHERE artist_mbid = $1", mbid)
                     
                     try:
                         # Fetch MB Albums (using clean logic)
                         mb_albums = await musicbrainz.fetch_release_groups(mbid, "album", client)
                         
                         for album in mb_albums:
                             rg_id = album["mbid"]
                             if rg_id in local_rgs:
                                 continue
                             
                             # Resolve Links
                             match = await musicbrainz.fetch_best_release_match(rg_id, client)
                             
                             tidal_url = None
                             qobuz_url = None
                             for link in match.get("links", []):
                                 if link["type"] == "tidal":
                                     tidal_url = link["url"]
                                 elif link["type"] == "qobuz":
                                     qobuz_url = link["url"]
                                 
                             if not tidal_url:
                                 try:
                                     want_year = year_from_date(album.get("date"))
                                     found = tidal_client.find_album_match(current_name, album["title"], want_year)
                                     if found:
                                         tidal_url = found
                                 except Exception:
                                     pass
                                 
                             # Insert
                             await self.db.execute("""
                                 INSERT INTO missing_album
                                 (artist_mbid, release_group_mbid, title, release_date, primary_type, musicbrainz_url, tidal_url, qobuz_url, updated_at)
                                 VALUES ($1, $2, $3, $4, 'Album', $5, $6, $7, NOW())
                                 ON CONFLICT (artist_mbid, release_group_mbid) DO NOTHING
                             """, mbid, rg_id, album["title"], album["date"], album.get("musicbrainz_url"), tidal_url, qobuz_url)
                                 
                     except Exception as e:
                         logger.warning(f"Error checking missing albums for {current_name}: {e}")
                         
             logger.info(f"Missing albums scan complete. Checked {processed}/{total} artists.")
             
        except Exception as e:
            logger.error(f"Missing Album Scan Failed: {e}")
