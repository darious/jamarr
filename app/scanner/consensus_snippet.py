    async def _apply_artist_name_consensus(self, db, mbids):
        """
        Updates artist names based on the most common name found in the track tags for each MBID.
        """
        if not mbids: return

        logger.info(f"Running Artist Name Consensus for {len(mbids)} artists...")
        
        # Convert set to list for query
        mbid_list = list(mbids)
        
        # Logic: 
        # 1. Group tracks by artist_mbid
        # 2. Exclude multi-artist tracks (%;%) to avoid polluting name with "A; B"
        # 3. Count frequency of each 'artist' name
        # 4. Pick top ranked name
        # 5. Update artist table
        
        query = """
            WITH ranked_names AS (
                SELECT 
                    t.artist_mbid, 
                    t.artist as name, 
                    COUNT(*) as cnt,
                    ROW_NUMBER() OVER (PARTITION BY t.artist_mbid ORDER BY COUNT(*) DESC) as rn
                FROM track t
                WHERE 
                    t.artist_mbid = ANY($1::text[]) 
                    AND t.artist_mbid NOT LIKE '%;%' 
                    AND t.artist IS NOT NULL 
                    AND t.artist != ''
                GROUP BY t.artist_mbid, t.artist
            ),
            winners AS (
                SELECT artist_mbid, name
                FROM ranked_names
                WHERE rn = 1
            )
            UPDATE artist a
            SET name = w.name, updated_at = NOW()
            FROM winners w
            WHERE a.mbid = w.artist_mbid 
              AND a.name != w.name;
        """
        
        try:
            res = await db.execute(query, mbid_list)
            updated_count = res.split()[-1]
            if int(updated_count) > 0:
                logger.info(f"Consensus: Updated {updated_count} artist names based on tag popularity.")
        except Exception as e:
            logger.error(f"Error running artist name consensus: {e}")
