from __future__ import annotations

from jamarr_tui.playback.controller import PlaybackController
from jamarr_tui.playback.mpv import PlaybackState


class FakeClient:
    client_id = "test-client"

    def __init__(self) -> None:
        self.paused = False
        self.resumed = False
        self.seeked_to: float | None = None
        self.volume: int | None = None
        self.index: int | None = None
        self.state = {
            "renderer_id": "cast:kitchen",
            "renderer_kind": "cast",
            "queue": [
                {
                    "id": 10,
                    "title": "Remote Song",
                    "artist": "Remote Artist",
                    "album": "Remote Album",
                    "duration_seconds": 180,
                    "art_sha1": "abc",
                },
                {
                    "id": 11,
                    "title": "Next Song",
                    "artist": "Remote Artist",
                    "album": "Remote Album",
                    "duration_seconds": 200,
                },
            ],
            "current_index": 0,
            "position_seconds": 42,
            "is_playing": True,
            "transport_state": "PLAYING",
            "volume": 33,
        }

    async def player_state(self):
        return dict(self.state)

    async def pause_player(self) -> None:
        self.paused = True
        self.state["is_playing"] = False
        self.state["transport_state"] = "PAUSED"

    async def resume_player(self) -> None:
        self.resumed = True
        self.state["is_playing"] = True
        self.state["transport_state"] = "PLAYING"

    async def seek_player(self, seconds: float) -> None:
        self.seeked_to = seconds
        self.state["position_seconds"] = seconds

    async def set_player_volume(self, percent: int) -> None:
        self.volume = percent
        self.state["volume"] = percent

    async def set_player_index(self, index: int) -> None:
        self.index = index
        self.state["current_index"] = index
        self.state["position_seconds"] = 0


class FakeMpv:
    def __init__(self) -> None:
        self.state = PlaybackState()
        self.stopped = False

    def on_track_end(self, callback) -> None:
        self.callback = callback

    async def stop_playback(self) -> None:
        self.stopped = True


async def test_remote_state_drives_current_and_playback_state() -> None:
    client = FakeClient()
    controller = PlaybackController(client=client)  # type: ignore[arg-type]
    controller._mpv = FakeMpv()  # noqa: SLF001

    await controller.activate_renderer("cast:kitchen")

    assert not controller.is_local_active
    assert controller.current is not None
    assert controller.current.title == "Remote Song"
    assert controller.state.loaded is True
    assert controller.state.paused is False
    assert controller.state.position_s == 42
    assert controller.state.duration_s == 180
    assert controller.volume == 0.33
    assert controller._mpv.stopped is True  # noqa: SLF001


async def test_remote_transport_controls_call_server() -> None:
    client = FakeClient()
    controller = PlaybackController(client=client)  # type: ignore[arg-type]
    controller._mpv = FakeMpv()  # noqa: SLF001
    await controller.activate_renderer("cast:kitchen")

    await controller.toggle_pause()
    await controller.seek(99)
    await controller.set_volume(0.5)
    await controller.next()

    assert client.paused is True
    assert client.seeked_to == 99
    assert client.volume == 50
    assert client.index == 1


class ReorderingClient(FakeClient):
    """FakeClient that also records reorders and can refuse one as stale."""

    def __init__(self, *, refuse_once: bool = False) -> None:
        super().__init__()
        self.state["queue_revision"] = 7
        for i, t in enumerate(self.state["queue"]):
            t["entry_id"] = f"e{i}"
        self.reorders: list[tuple[list[dict], int | None]] = []
        self.state_reads = 0
        self._refuse_once = refuse_once

    async def player_state(self):
        self.state_reads += 1
        return dict(self.state)

    async def reorder_player_queue(self, tracks, expected_revision=None):
        from jamarr_tui.api.client import ApiError

        self.reorders.append(([dict(t) for t in tracks], expected_revision))
        if self._refuse_once:
            self._refuse_once = False
            self.state["queue_revision"] = 8
            raise ApiError(409, '{"detail": {"code": "queue_conflict"}}')
        # As the server does: the entry that was current stays current.
        current = self.state["queue"][self.state["current_index"]]["entry_id"]
        self.state["queue"] = [dict(t) for t in tracks]
        self.state["current_index"] = next(
            i for i, t in enumerate(tracks) if t["entry_id"] == current
        )
        self.state["queue_revision"] += 1


async def test_remote_reorder_sends_entry_ids_and_the_revision_it_read() -> None:
    client = ReorderingClient()
    controller = PlaybackController(client=client)  # type: ignore[arg-type]
    controller._mpv = FakeMpv()  # noqa: SLF001
    await controller.activate_renderer("cast:kitchen")

    await controller.move(1, 0)

    sent, expected = client.reorders[0]
    assert [t["entry_id"] for t in sent] == ["e1", "e0"]
    assert expected == 7
    # The playing occurrence followed the move.
    assert controller.index == 1


async def test_remote_reorder_refused_as_stale_refreshes_instead_of_forcing() -> None:
    client = ReorderingClient(refuse_once=True)
    controller = PlaybackController(client=client)  # type: ignore[arg-type]
    controller._mpv = FakeMpv()  # noqa: SLF001
    await controller.activate_renderer("cast:kitchen")
    reads_before = client.state_reads

    await controller.move(1, 0)

    # One attempt, then the live state was pulled back in; the server's
    # order (unchanged) is what the controller shows now.
    assert len(client.reorders) == 1
    assert client.state_reads > reads_before
    assert [t["entry_id"] for t in controller.queue] == ["e0", "e1"]
    assert controller._remote_revision == 8  # noqa: SLF001
