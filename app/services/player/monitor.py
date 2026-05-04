import asyncio
import time
import logging
import json
from app.db import get_db
from app.upnp import UPnPManager
from app.services.player.globals import (
    playback_monitors,
    monitor_start_times,
    monitor_starting,
    last_track_start_time,
)
from app.services.player.state import (
    get_renderer_state_db,
    strip_art_ids,
)
from app.services.player.queue import play_next_track_internal
from app.services.player.history import log_history

logger = logging.getLogger(__name__)

def _mark_monitor_starting(udn: str):
    monitor_starting[udn] = time.time()


def _clear_monitor_starting(udn: str):
    monitor_starting.pop(udn, None)


def _is_monitor_starting(udn: str, window_s: float = 10.0) -> bool:
    started_at = monitor_starting.get(udn)
    return bool(started_at) and (time.time() - started_at) < window_s


def start_monitor_task(udn: str):
    existing = playback_monitors.get(udn)
    if existing and not existing.done():
        return existing
    playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
    monitor_start_times[udn] = time.time()
    return playback_monitors[udn]


async def monitor_upnp_playback(udn: str):
    """Background task to poll UPnP device for position and update DB."""
    logger.info(f"[Player] Starting UPnP monitor for {udn}")
    upnp = UPnPManager.get_instance()

    # Grace period: Wait for device to react to Play command before polling
    logger.info(f"[Player] Monitor {udn}: Task started, waiting 3s grace period...")
    await asyncio.sleep(3)

    was_playing = False  # Initialize to prevent UnboundLocalError
    consecutive_errors = 0
    error_started_at = 0.0  # when the first error in the current streak occurred
    try:
        while True:
            # 1. Fetch position & transport from UPnP
            try:
                logger.info(f"[Player] Monitor {udn}: Polling...")
                rel_time, _ = await upnp.get_position(udn)
                transport_state = await upnp.get_transport_info(udn)
                logger.info(f"[Player] Monitor {udn}: Got pos={rel_time}, state={transport_state}")
                consecutive_errors = 0  # Reset on success
                error_started_at = 0.0
            except Exception as e:
                now = time.time()
                consecutive_errors += 1
                if error_started_at == 0.0:
                    error_started_at = now
                error_duration = now - error_started_at
                # Kill only after 5 minutes of continuous errors
                if error_duration > 300:
                    logger.error(
                        f"[Player] Monitor {udn}: Errors persisted {error_duration:.0f}s, stopping"
                    )
                    break
                # Exponential backoff: 1s → 2s → 4s → 8s → 16s → cap 30s
                backoff = min(1 << (consecutive_errors - 1), 30)
                logger.error(
                    f"[Player] Monitor {udn}: Error fetching state (#{consecutive_errors}, "
                    f"backoff {backoff}s, streak {error_duration:.0f}s): {e}"
                )
                await asyncio.sleep(backoff)
                continue

            # 2. Update DB
            async for db in get_db():
                # What the DB currently thinks (may differ from the device)
                state = await get_renderer_state_db(db, udn)
                was_playing = state["is_playing"]

                # Update live stats from the device
                if transport_state == "PLAYING" and (rel_time is None or rel_time == 0):
                    # Some renderers report 0 at start; keep moving forward based on last known position.
                    rel_time = max(0, state.get("position_seconds", 0) + 1)
                state["position_seconds"] = rel_time
                state["transport_state"] = transport_state
                state["is_playing"] = transport_state not in [
                    "PAUSED_PLAYBACK",
                    "STOPPED",
                    "NO_MEDIA_PRESENT",
                ]

                # Auto-advance logic:
                # If we think we are playing but the device reports STOPPED/NO_MEDIA_PRESENT and position ~0,
                # assume the track finished. Keep this separate from the normal play/pause flow so we do not
                # overwrite queue/volume fields while a user action is in flight.
                if was_playing:
                    if transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                        # Ignore STOPPED if it arrives immediately after a Play/Skip (renderer churn).
                        time_since_start = time.time() - last_track_start_time.get(
                            udn, 0
                        )
                        if time_since_start < 5.0:
                            logger.info(
                                f"[Player] Ignoring STOPPED state during transition (started {time_since_start:.1f}s ago)"
                            )
                            continue
                        logger.info(
                            f"[Player] Track finished detection: State={transport_state}, Expected=Playing"
                        )
                        # Trigger next track outside DB loop; helper opens its own connection.
                    else:
                        # Still playing or paused/buffering. If user paused via remote, sync is_playing to False.
                        if "PAUSE" in transport_state:
                            state["is_playing"] = False

                        # Race Condition Fix: status-only UPDATE so we do not overwrite queue/volume changes
                        # that might have happened via API while this UPnP poll was in flight.
                        await db.execute(
                            """
                            UPDATE renderer_state
                            SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                            WHERE renderer_udn = $4
                            """,
                            state["position_seconds"],
                            state["transport_state"],
                            bool(state["is_playing"]),
                            udn,
                        )
                else:
                    # Not previously playing; just persist snapshot of state.
                    await db.execute(
                        """
                        UPDATE renderer_state
                        SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                        WHERE renderer_udn = $4
                        """,
                        state["position_seconds"],
                        state["transport_state"],
                        bool(state["is_playing"]),
                        udn,
                    )

                # History logging for remote playback (based on renderer state queue)
                if (
                    state["is_playing"]
                    and state["current_index"] is not None
                    and state["current_index"] >= 0
                ):
                    queue = state.get("queue") or []
                    if 0 <= state["current_index"] < len(queue):
                        track = queue[state["current_index"]]
                        
                        # Only check if not already logged
                        if not track.get("logged", False):
                            track_id = track.get("id")
                            duration = track.get("duration_seconds") or 0
                            
                            # Threshold check
                            threshold = min(30, duration * 0.2) if duration > 0 else 30
                            
                            if rel_time >= threshold:
                                renderer_ip = (
                                    upnp.renderers.get(udn, {}).get("ip")
                                    if upnp.renderers
                                    else None
                                )
                                await log_history(
                                    db,
                                    track_id,
                                    client_ip=renderer_ip or "unknown",
                                    client_id=udn,
                                    user_id=track.get("user_id"),
                                )
                                
                                # Mark logged and persist
                                track["logged"] = True
                                await db.execute(
                                    "UPDATE renderer_state SET queue = $1 WHERE renderer_udn = $2",
                                    json.dumps(strip_art_ids(queue)),
                                    udn,
                                )

            # Execute side effects outside DB context (avoids holding a transaction open)
            if was_playing and transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                await play_next_track_internal(udn)
                await asyncio.sleep(4)  # Give the new track a moment to start

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info(f"UPnP monitor for {udn} cancelled")
    except Exception as e:
        logger.error(f"UPnP monitor error for {udn}: {e}")
        import traceback

        traceback.print_exc()
