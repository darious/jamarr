import os
import mimetypes
import logging
import time
from app.db import get_db
from app.upnp import UPnPManager
from app.services.player.state import get_renderer_state_db, update_renderer_state_db
from app.services.player.globals import last_track_start_time

logger = logging.getLogger(__name__)

async def play_next_track_internal(udn: str):
    """Internal helper to advance queue and play next track."""
    upnp = UPnPManager.get_instance()
    async for db in get_db():
        state = await get_renderer_state_db(db, udn)
        queue = state["queue"]
        current_index = state["current_index"]

        next_index = current_index + 1
        if 0 <= next_index < len(queue):
            track = queue[next_index]
            logger.info(
                f"[Player] Auto-advancing to track {next_index}: {track['title']}"
            )

            # Setup UPnP
            # Note: We assume UPnPManager needs active renderer set.
            # This follows the pattern in play_track endpoint.
            await upnp.set_renderer(udn)

            # Use stored IP/Port if possible, or attempt to reconstruct
            # Since this is a background task, accessing request.url is hard.
            # We rely on UPnPManager's existing base_url or reconstruct it.
            # If base_url is missing, art might break.
            upnp.base_url = f"http://{upnp.local_ip}:8111"

            # Check if mime is present, else guess
            if "mime" not in track or not track["mime"]:
                mime, _ = mimetypes.guess_type(track.get("path", ""))
                if not mime:
                    ext = os.path.splitext(track.get("path", ""))[1].lower()
                    if ext == ".flac":
                        mime = "audio/flac"
                    elif ext == ".mp3":
                        mime = "audio/mpeg"
                    elif ext == ".m4a":
                        mime = "audio/mp4"
                    elif ext == ".wav":
                        mime = "audio/wav"
                    elif ext == ".ogg":
                        mime = "audio/ogg"
                    else:
                        mime = "audio/flac"
                track["mime"] = mime

            await upnp.play_track(track["id"], track["path"], track)
            # Record track start time to prevent false "track finished" detection
            last_track_start_time[udn] = time.time()

            # Update DB
            state["current_index"] = next_index
            state["is_playing"] = True
            state["position_seconds"] = 0
            # state['transport_state'] = "PLAYING" # Optimistic
            await update_renderer_state_db(db, udn, state)

            # Remove immediate history logging.
            # We rely on the client (PlayerBar) to log history after 30s threshold to ensure:
            # 1. Correct Client IP/ID is logged.
            # 2. Track is actually listened to (not skipped immediately).
            # await log_history(db, track['id'], "127.0.0.1", "System Auto-Advance")

        else:
            logger.info("[Player] End of queue reached.")
            state["is_playing"] = False
            state["position_seconds"] = 0
            # state['transport_state'] = "STOPPED" # Already stopped
            await update_renderer_state_db(db, udn, state)
