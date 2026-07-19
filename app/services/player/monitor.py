import asyncio
import os
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
    last_playing_seen,
    last_playing_position,
    start_retries,
)
from app.services.player.state import (
    get_renderer_state_db,
    strip_art_ids,
)
from app.services.player.queue import play_next_track_internal
from app.services.player.history import log_history

logger = logging.getLogger(__name__)

# Ignore STOPPED churn this soon after issuing Play (renderers flap during URI load).
TRANSITION_GRACE_S = 5.0
# STOPPED with the last seen position within this of the duration = track finished.
FINISH_MARGIN_S = 10.0
# STOPPED with the last seen position at or below this = the track never really
# got going (failed start), as opposed to an external stop mid-track.
FAILED_START_MAX_POS_S = 10.0
# How long to keep treating STOPPED as "still buffering" for a track that has
# not been seen PLAYING at all, before re-issuing Play.
START_RETRY_AFTER_S = 8.0
# Play re-issues per track before giving up and skipping.
MAX_START_RETRIES = 2
# Warm the next track's file this close to the end of the current one.
PREWARM_LEAD_S = 30.0
PREWARM_BYTES = 8 * 1024 * 1024

# Queue index already prewarmed per renderer, and the task doing it.
_prewarmed_index: dict[str, int] = {}
_prewarm_tasks: dict[str, asyncio.Task] = {}


async def _prewarm_next_track(path: str) -> None:
    """Read the head of the file to pull it into the OS page cache.

    Cold NFS reads are slow enough that some renderers (Server room TV) give
    up starting a track; serving the first fetch from RAM removes that stall.
    """
    try:
        import aiofiles

        from app.config import get_music_path

        if not os.path.isabs(path):
            path = os.path.join(get_music_path(), path)
        async with aiofiles.open(path, "rb") as fh:
            remaining = PREWARM_BYTES
            while remaining > 0:
                chunk = await fh.read(min(512 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        logger.info(f"[Player] Prewarmed next track: {os.path.basename(path)}")
    except Exception:
        logger.debug("Prewarm failed for %s", path, exc_info=True)


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
            finished_reason = None
            replay_track = None
            async for db in get_db():
                # What the DB currently thinks (may differ from the device)
                state = await get_renderer_state_db(db, udn)
                was_playing = state["is_playing"]

                # Raw device-reported position, before the keep-moving hack below.
                device_position = rel_time

                if transport_state == "PLAYING":
                    last_playing_seen[udn] = time.time()
                    if device_position:
                        last_playing_position[udn] = float(device_position)
                        if device_position > FAILED_START_MAX_POS_S:
                            # The track is definitely going; the start-retry
                            # budget belongs to the next troubled start.
                            start_retries.pop(udn, None)

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
                # Treat STOPPED as end-of-track only when the evidence says so.
                # The device's last seen position vs the track duration tells us
                # *where* playback stopped, which distinguishes "finished" from
                # "failed to start" (retry) from "externally stopped" (halt).
                # recently_playing covers renderers that signal end-of-track as
                # PLAYING -> PAUSED_PLAYBACK -> STOPPED: the PAUSED poll clears
                # is_playing in the DB, so was_playing alone would miss it.
                if transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                    recently_playing = was_playing or (
                        time.time() - last_playing_seen.get(udn, 0) <= 5.0
                    )
                    if recently_playing:
                        started_at = last_track_start_time.get(udn, 0)
                        time_since_start = time.time() - started_at
                        # Whether the device has reached PLAYING for *this* track;
                        # was_playing is set optimistically at Play time and
                        # last_playing_seen/-position may be from the previous
                        # track, so everything is gated on started_at.
                        played_since_start = last_playing_seen.get(udn, 0) >= started_at
                        last_pos = (
                            last_playing_position.get(udn, 0.0) if played_since_start else 0.0
                        )
                        duration = 0
                        queue = state.get("queue") or []
                        idx = state.get("current_index")
                        if idx is not None and 0 <= idx < len(queue):
                            duration = queue[idx].get("duration_seconds") or 0
                        retries = start_retries.get(udn, 0)
                        # min-clamp so very short tracks aren't "finished" at 0s
                        finish_threshold = max(duration - FINISH_MARGIN_S, duration * 0.5)

                        if time_since_start < TRANSITION_GRACE_S:
                            logger.info(
                                f"[Player] Ignoring STOPPED state during transition (started {time_since_start:.1f}s ago)"
                            )
                        elif duration > 0 and played_since_start and last_pos >= finish_threshold:
                            logger.info(
                                f"[Player] Track finished detection: stopped at "
                                f"{last_pos:.0f}s of {duration:.0f}s"
                            )
                            # Trigger next track outside DB loop; helper opens its own connection.
                            finished_reason = "stopped"
                        elif duration > 0 and (
                            not played_since_start or last_pos <= FAILED_START_MAX_POS_S
                        ):
                            # Failed start: never reached PLAYING, or died within
                            # the first seconds (Server room TV does both).
                            if not played_since_start and time_since_start < START_RETRY_AFTER_S:
                                logger.info(
                                    f"[Player] Ignoring STOPPED: renderer has not started the track "
                                    f"yet ({time_since_start:.1f}s since Play)"
                                )
                            elif retries < MAX_START_RETRIES:
                                start_retries[udn] = retries + 1
                                # Re-issue Play outside the DB loop.
                                replay_track = queue[idx]
                            else:
                                logger.warning(
                                    f"[Player] Track failed to start after {MAX_START_RETRIES} "
                                    f"Play retries; skipping to next"
                                )
                                finished_reason = "stopped"
                        elif duration > 0:
                            # Stopped mid-track: an external stop (TV remote,
                            # another controller). Halt instead of fighting it.
                            logger.info(
                                f"[Player] Playback stopped mid-track at {last_pos:.0f}s of "
                                f"{duration:.0f}s; stopping queue"
                            )
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
                            # No duration metadata; fall back to time-based logic.
                            if not played_since_start and time_since_start < 30.0:
                                logger.info(
                                    f"[Player] Ignoring STOPPED: renderer has not started the track "
                                    f"yet ({time_since_start:.1f}s since Play)"
                                )
                            else:
                                if not played_since_start:
                                    logger.warning(
                                        f"[Player] Renderer never started the track after "
                                        f"{time_since_start:.0f}s; skipping to next"
                                    )
                                logger.info(
                                    f"[Player] Track finished detection: State={transport_state}, Expected=Playing"
                                )
                                finished_reason = "stopped"
                    else:
                        # Genuinely idle; just persist snapshot of state.
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

                    # Watchdog: some renderers get stuck reporting PLAYING at position 0
                    # after the audio actually ended, never emitting STOPPED. If the device
                    # has reported no real position for longer than the track's duration
                    # plus a margin, assume the track finished.
                    if was_playing and transport_state == "PLAYING":
                        started = last_track_start_time.get(udn)
                        duration = 0
                        queue = state.get("queue") or []
                        idx = state.get("current_index")
                        if idx is not None and 0 <= idx < len(queue):
                            duration = queue[idx].get("duration_seconds") or 0
                        if (
                            started
                            and duration > 0
                            and (device_position or 0) <= 1
                            and time.time() - started > duration + 60
                        ):
                            logger.warning(
                                f"[Player] Watchdog: renderer stuck PLAYING at position 0 for "
                                f"{time.time() - started:.0f}s (track is {duration:.0f}s); assuming finished"
                            )
                            finished_reason = "watchdog"

                        # Prewarm: pull the next track's file head into the page
                        # cache shortly before the transition, so the renderer's
                        # first fetch is served from RAM instead of cold NFS.
                        next_idx = (idx if idx is not None else -1) + 1
                        if (
                            duration > 0
                            and device_position
                            and device_position >= duration - PREWARM_LEAD_S
                            and 0 <= next_idx < len(queue)
                            and _prewarmed_index.get(udn) != next_idx
                        ):
                            next_path = queue[next_idx].get("path")
                            if next_path:
                                _prewarmed_index[udn] = next_idx
                                _prewarm_tasks[udn] = asyncio.create_task(
                                    _prewarm_next_track(next_path)
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
            if replay_track is not None:
                logger.warning(
                    f"[Player] Track failed to start ('{replay_track.get('title')}'); "
                    f"re-issuing Play (attempt {start_retries.get(udn, 0)}/{MAX_START_RETRIES})"
                )
                try:
                    await upnp.play_track(replay_track["id"], replay_track["path"], replay_track)
                    last_track_start_time[udn] = time.time()
                    last_playing_position.pop(udn, None)
                except Exception:
                    logger.exception(f"[Player] Play retry failed for {udn}")
                await asyncio.sleep(4)  # Give the retried track a moment to start
            elif finished_reason:
                await play_next_track_internal(udn)
                await asyncio.sleep(4)  # Give the new track a moment to start

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info(f"UPnP monitor for {udn} cancelled")
    except Exception as e:
        logger.error(f"UPnP monitor error for {udn}: {e}")
        import traceback

        traceback.print_exc()
