from app.api.lastfm import SyncRequest, sync_scrobbles_for_user
from app.db import get_pool


async def sync_all_lastfm_scrobbles() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch(
            """
            SELECT id, username, lastfm_username, lastfm_session_key, lastfm_enabled
            FROM "user"
            WHERE lastfm_session_key IS NOT NULL
              AND lastfm_username IS NOT NULL
              AND lastfm_enabled = TRUE
            """
        )

    if not users:
        return 0

    count = 0
    for user in users:
        async with pool.acquire() as conn:
            await sync_scrobbles_for_user(
                conn,
                dict(user),
                SyncRequest(fetch_new=True, rematch_all=False, limit=None),
                None,
            )
            count += 1
    return count
