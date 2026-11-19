"""ListenBrainz client, submission queue and account endpoints.

Nothing here talks to the real ListenBrainz: the client is exercised through
httpx.MockTransport, and the queue/endpoints through a recording fake.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import listenbrainz as lb
from app.listenbrainz_submissions import ListenBrainzSubmitter, retry_delay_seconds

ARTIST_A = "a74b1b7f-71a5-4011-9441-d0b5e4122711"
ARTIST_B = "0038bcbd-5f12-4a05-9f77-324652334345"
RECORDING = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
RELEASE = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


def _client(handler) -> lb.ListenBrainzClient:
    return lb.ListenBrainzClient(
        api_root="https://lb.test", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_validate_token_valid_sends_token_and_user_agent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["ua"] = request.headers.get("User-Agent")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"code": 200, "valid": True, "user_name": "someone"})

    client = _client(handler)
    assert await client.validate_token("tok") == "someone"
    assert seen["auth"] == "Token tok"
    assert seen["path"] == "/1/validate-token"
    assert seen["ua"].startswith("Jamarr/")
    await client.aclose()


@pytest.mark.asyncio
async def test_validate_token_invalid_is_none_not_error():
    client = _client(
        lambda r: httpx.Response(200, json={"code": 200, "valid": False, "message": "Token invalid."})
    )
    assert await client.validate_token("bad") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_submit_listens_posts_payload():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok"})

    client = _client(handler)
    listen = {"listened_at": 1, "track_metadata": {"artist_name": "A", "track_name": "T"}}
    await client.submit_listens("tok", "single", [listen])
    assert bodies == [{"listen_type": "single", "payload": [listen]}]
    with pytest.raises(ValueError):
        await client.submit_listens("tok", "single", [listen, listen])
    await client.aclose()


@pytest.mark.parametrize(
    "status_code, error_type, retryable",
    [
        (401, lb.ListenBrainzAuthError, False),
        (400, lb.ListenBrainzRejectedError, False),
        (413, lb.ListenBrainzRejectedError, False),
        (408, lb.ListenBrainzUnavailableError, True),
        (502, lb.ListenBrainzUnavailableError, True),
        (503, lb.ListenBrainzUnavailableError, True),
        # A wrong API root or a proxy page is not the listens' fault.
        (404, lb.ListenBrainzError, True),
        (403, lb.ListenBrainzError, True),
    ],
)
@pytest.mark.asyncio
async def test_submit_listens_maps_errors(status_code, error_type, retryable):
    client = _client(lambda r: httpx.Response(status_code, json={"error": "nope"}))
    with pytest.raises(error_type) as info:
        await client.submit_listens("tok", "import", [{"listened_at": 1, "track_metadata": {}}] * 2)
    assert info.value.retryable is retryable
    if status_code in (404, 403):
        assert not isinstance(info.value, lb.ListenBrainzRejectedError)
    await client.aclose()


@pytest.mark.asyncio
async def test_validate_token_non_json_reply_is_unavailable():
    client = _client(lambda r: httpx.Response(200, text="<html>captive portal</html>"))
    with pytest.raises(lb.ListenBrainzUnavailableError):
        await client.validate_token("tok")
    await client.aclose()


@pytest.mark.asyncio
async def test_network_failure_is_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client(handler)
    with pytest.raises(lb.ListenBrainzUnavailableError):
        await client.validate_token("tok")
    await client.aclose()


@pytest.mark.asyncio
async def test_429_reports_reset_window():
    client = _client(
        lambda r: httpx.Response(429, headers={"X-RateLimit-Reset-In": "42"}, json={})
    )
    with pytest.raises(lb.ListenBrainzRateLimitedError) as info:
        await client.validate_token("tok")
    assert info.value.retry_after == 42
    await client.aclose()


@pytest.mark.asyncio
async def test_exhausted_window_blocks_next_request_without_sending():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-In": "120"},
            json={"valid": True, "user_name": "someone"},
        )

    client = _client(handler)
    await client.validate_token("tok")
    with pytest.raises(lb.ListenBrainzRateLimitedError):
        await client.validate_token("tok")
    assert len(calls) == 1
    await client.aclose()


def test_build_track_metadata_full():
    md = lb.build_track_metadata(
        {
            "title": " Song ",
            "artist": "A feat. B",
            "album": "Album",
            "track_no": 3,
            "duration_seconds": 201.4,
            "artist_mbid": f"{ARTIST_A}; {ARTIST_B}; not-a-uuid; {ARTIST_A}",
            "track_mbid": RECORDING,
            "release_mbid": RELEASE,
            "release_group_mbid": None,
            "release_track_mbid": "garbage",
        }
    )
    assert md["artist_name"] == "A feat. B"
    assert md["track_name"] == "Song"
    assert md["release_name"] == "Album"
    info = md["additional_info"]
    assert info["artist_mbids"] == [ARTIST_A, ARTIST_B]
    assert info["recording_mbid"] == RECORDING
    assert info["release_mbid"] == RELEASE
    assert "release_group_mbid" not in info
    assert "track_mbid" not in info
    assert info["tracknumber"] == 3
    assert info["duration_ms"] == 201400
    assert info["submission_client"] == "Jamarr"


def test_build_track_metadata_needs_artist_and_title():
    assert lb.build_track_metadata({"title": "T", "artist": ""}) is None
    assert lb.build_track_metadata({"title": None, "artist": "A"}) is None


def test_retry_delay_doubles_and_caps():
    assert retry_delay_seconds(1) == 60
    assert retry_delay_seconds(2) == 120
    assert retry_delay_seconds(30) == 6 * 3600


# --------------------------------------------------------------------------
# Submission queue
# --------------------------------------------------------------------------


class FakeLB:
    """Records submissions; ``fail`` decides the outcome per call."""

    def __init__(self, username="lbuser"):
        self.calls = []
        self.username = username
        self.fail = None  # callable(listen_type, listens) -> Exception | None
        self.validate_error = None

    async def validate_token(self, token):
        if self.validate_error:
            raise self.validate_error
        return self.username if token == "good-token" else None

    async def submit_listens(self, token, listen_type, listens):
        self.calls.append((token, listen_type, listens))
        if self.fail:
            exc = self.fail(listen_type, listens)
            if exc:
                raise exc

    def submitted_titles(self, listen_type=None):
        return [
            item["track_metadata"]["track_name"]
            for _, kind, listens in self.calls
            if listen_type in (None, kind)
            for item in listens
        ]


@pytest.fixture
def fake_lb():
    fake = FakeLB()
    lb.set_client(fake)
    yield fake
    lb.set_client(None)


async def _user(db, *, since, token="good-token", enabled=True, username="lbfan"):
    return await db.fetchval(
        """
        INSERT INTO "user" (username, email, password_hash, listenbrainz_token,
                            listenbrainz_username, listenbrainz_enabled, listenbrainz_since)
        VALUES ($1, $2, 'x', $3, 'lbuser', $4, $5)
        RETURNING id
        """,
        username,
        f"{username}@example.com",
        token,
        enabled,
        since,
    )


async def _track(db, n, artist="Artist"):
    return await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, duration_seconds, track_mbid, artist_mbid)
        VALUES ($1, $2, $3, 'Album', 200, $4, $5) RETURNING id
        """,
        f"/music/{n}.flac",
        f"Song {n}",
        artist,
        RECORDING,
        ARTIST_A,
    )


async def _play(db, track_id, user_id, at):
    return await db.fetchval(
        'INSERT INTO playback_history (track_id, user_id, "timestamp") VALUES ($1, $2, $3) RETURNING id',
        track_id,
        user_id,
        at,
    )


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_drain_sends_plays_since_cutover_once(db, fake_lb):
    since = _now() - timedelta(hours=1)
    user_id = await _user(db, since=since)
    t1, t2, t3 = [await _track(db, n) for n in (1, 2, 3)]
    await _play(db, t1, user_id, since - timedelta(minutes=5))  # before cutover
    await _play(db, t2, user_id, since + timedelta(minutes=5))
    await _play(db, t3, user_id, since + timedelta(minutes=10))

    submitter = ListenBrainzSubmitter()
    assert await submitter.drain() == 2
    assert fake_lb.submitted_titles("import") == ["Song 2", "Song 3"]
    listens = fake_lb.calls[0][2]
    assert listens[0]["listened_at"] == int((since + timedelta(minutes=5)).timestamp())
    assert listens[0]["track_metadata"]["additional_info"]["recording_mbid"] == RECORDING

    statuses = await db.fetch("SELECT status FROM listenbrainz_submission")
    assert [r["status"] for r in statuses] == ["submitted", "submitted"]

    assert await submitter.drain() == 0
    assert len(fake_lb.calls) == 1


@pytest.mark.asyncio
async def test_single_play_uses_single_listen_type(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    await _play(db, await _track(db, 1), user_id, _now())
    await ListenBrainzSubmitter().drain()
    assert [kind for _, kind, _ in fake_lb.calls] == ["single"]


@pytest.mark.asyncio
async def test_unavailable_marks_retry_and_backs_off(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    await _play(db, await _track(db, 1), user_id, _now())
    fake_lb.fail = lambda kind, listens: lb.ListenBrainzUnavailableError("502")

    submitter = ListenBrainzSubmitter()
    assert await submitter.drain() == 0
    row = await db.fetchrow("SELECT status, attempts, next_attempt_at, last_error FROM listenbrainz_submission")
    assert row["status"] == "retry"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] > _now()
    assert "502" in row["last_error"]

    # Not due yet: nothing is sent.
    fake_lb.fail = None
    assert await submitter.drain() == 0
    assert len(fake_lb.calls) == 1

    await db.execute("UPDATE listenbrainz_submission SET next_attempt_at = NOW() - INTERVAL '1 second'")
    assert await submitter.drain() == 1
    row = await db.fetchrow("SELECT status, attempts, last_error FROM listenbrainz_submission")
    assert (row["status"], row["attempts"], row["last_error"]) == ("submitted", 2, None)


@pytest.mark.asyncio
async def test_rate_limit_uses_reset_window(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    await _play(db, await _track(db, 1), user_id, _now())
    fake_lb.fail = lambda kind, listens: lb.ListenBrainzRateLimitedError("429", retry_after=900)
    await ListenBrainzSubmitter().drain()
    row = await db.fetchrow("SELECT status, next_attempt_at FROM listenbrainz_submission")
    assert row["status"] == "retry"
    assert row["next_attempt_at"] > _now() + timedelta(minutes=14)


@pytest.mark.asyncio
async def test_rejected_batch_is_split_to_isolate_bad_listen(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    base = _now() - timedelta(minutes=30)
    for n in range(1, 6):
        await _play(db, await _track(db, n), user_id, base + timedelta(minutes=n))

    def fail(kind, listens):
        titles = {item["track_metadata"]["track_name"] for item in listens}
        return lb.ListenBrainzRejectedError("bad listen") if "Song 4" in titles else None

    fake_lb.fail = fail
    assert await ListenBrainzSubmitter().drain() == 4
    rows = await db.fetch(
        """
        SELECT t.title, s.status FROM listenbrainz_submission s
        JOIN playback_history ph ON ph.id = s.playback_history_id
        JOIN track t ON t.id = ph.track_id ORDER BY t.title
        """
    )
    assert {r["title"]: r["status"] for r in rows} == {
        "Song 1": "submitted",
        "Song 2": "submitted",
        "Song 3": "submitted",
        "Song 4": "rejected",
        "Song 5": "submitted",
    }


@pytest.mark.asyncio
async def test_not_found_retries_instead_of_rejecting(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    for n in (1, 2):
        await _play(db, await _track(db, n), user_id, _now() - timedelta(minutes=n))
    fake_lb.fail = lambda kind, listens: lb.ListenBrainzError("ListenBrainz error 404", status_code=404)
    assert await ListenBrainzSubmitter().drain() == 0
    assert len(fake_lb.calls) == 1  # no bisecting
    statuses = {r["status"] for r in await db.fetch("SELECT status FROM listenbrainz_submission")}
    assert statuses == {"retry"}


@pytest.mark.asyncio
async def test_play_deleted_mid_send_does_not_block_the_rest(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    first = await _play(db, await _track(db, 1), user_id, _now() - timedelta(minutes=2))
    await _play(db, await _track(db, 2), user_id, _now() - timedelta(minutes=1))

    async def delete_first():
        await db.execute("DELETE FROM playback_history WHERE id = $1", first)

    deleted = []

    class Deleting(FakeLB):
        async def submit_listens(self, token, listen_type, listens):
            await super().submit_listens(token, listen_type, listens)
            if not deleted:
                deleted.append(True)
                await delete_first()

    deleting = Deleting()
    lb.set_client(deleting)
    assert await ListenBrainzSubmitter().drain() == 2
    assert await db.fetchval("SELECT COUNT(*) FROM listenbrainz_submission") == 1
    assert await ListenBrainzSubmitter().drain() == 0
    assert len(deleting.calls) == 1


@pytest.mark.asyncio
async def test_track_without_artist_is_rejected_locally(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    await _play(db, await _track(db, 1, artist=""), user_id, _now())
    assert await ListenBrainzSubmitter().drain() == 0
    assert fake_lb.calls == []
    assert await db.fetchval("SELECT status FROM listenbrainz_submission") == "rejected"


@pytest.mark.asyncio
async def test_bad_token_pauses_user_until_reconnect(db, fake_lb):
    user_id = await _user(db, since=_now() - timedelta(hours=1))
    await _play(db, await _track(db, 1), user_id, _now())
    fake_lb.fail = lambda kind, listens: lb.ListenBrainzAuthError("Invalid authorization token.")

    submitter = ListenBrainzSubmitter()
    assert await submitter.drain() == 0
    assert "Invalid" in await db.fetchval('SELECT listenbrainz_auth_error FROM "user" WHERE id = $1', user_id)
    # Play stays due (no submission row) but the user is skipped.
    assert await db.fetchval("SELECT COUNT(*) FROM listenbrainz_submission") == 0
    assert await submitter.drain() == 0
    assert len(fake_lb.calls) == 1

    fake_lb.fail = None
    await db.execute('UPDATE "user" SET listenbrainz_auth_error = NULL WHERE id = $1', user_id)
    assert await submitter.drain() == 1


@pytest.mark.asyncio
async def test_disabled_or_disconnected_users_are_skipped(db, fake_lb):
    since = _now() - timedelta(hours=1)
    off = await _user(db, since=since, enabled=False, username="off")
    gone = await _user(db, since=since, token=None, username="gone")
    track = await _track(db, 1)
    await _play(db, track, off, _now())
    await _play(db, track, gone, _now())
    assert await ListenBrainzSubmitter().drain() == 0
    assert fake_lb.calls == []


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_validates_and_status_hides_token(auth_client, db, fake_lb):
    response = await auth_client.post("/api/listenbrainz/connect", json={"token": " good-token "})
    assert response.status_code == 200, response.text
    assert response.json()["username"] == "lbuser"

    row = await db.fetchrow(
        'SELECT listenbrainz_token, listenbrainz_since FROM "user" WHERE username = $1', "testuser"
    )
    assert row["listenbrainz_token"] == "good-token"
    assert row["listenbrainz_since"] is not None

    status_response = await auth_client.get("/api/listenbrainz/status")
    data = status_response.json()
    assert data["connected"] is True
    assert data["username"] == "lbuser"
    assert data["enabled"] is True
    assert data["pending"] == 0
    assert "good-token" not in status_response.text


@pytest.mark.asyncio
async def test_connect_rejects_invalid_token(auth_client, db, fake_lb):
    response = await auth_client.post("/api/listenbrainz/connect", json={"token": "nope"})
    assert response.status_code == 400
    assert await db.fetchval('SELECT listenbrainz_token FROM "user" WHERE username = $1', "testuser") is None


@pytest.mark.asyncio
async def test_connect_reports_listenbrainz_down(auth_client, fake_lb):
    fake_lb.validate_error = lb.ListenBrainzUnavailableError("timeout")
    response = await auth_client.post("/api/listenbrainz/connect", json={"token": "good-token"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_reconnect_same_account_keeps_since_unless_given(auth_client, db, fake_lb):
    cutover = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
    response = await auth_client.post(
        "/api/listenbrainz/connect", json={"token": "good-token", "since": cutover.isoformat()}
    )
    assert response.status_code == 200
    await auth_client.post("/api/listenbrainz/connect", json={"token": "good-token"})
    since = await db.fetchval('SELECT listenbrainz_since FROM "user" WHERE username = $1', "testuser")
    assert since == cutover


async def _testuser_id(db):
    return await db.fetchval('SELECT id FROM "user" WHERE username = $1', "testuser")


@pytest.mark.asyncio
async def test_pause_skips_paused_plays_but_keeps_earlier_backlog(auth_client, db, fake_lb):
    since = _now() - timedelta(hours=2)
    await auth_client.post("/api/listenbrainz/connect", json={"token": "good-token", "since": since.isoformat()})
    user_id = await _testuser_id(db)
    queued = await _play(db, await _track(db, 1), user_id, _now() - timedelta(hours=1))
    # ListenBrainz was down for the queued play.
    await db.execute(
        "INSERT INTO listenbrainz_submission (playback_history_id, user_id, status, attempts, next_attempt_at)"
        " VALUES ($1, $2, 'retry', 1, NOW() - INTERVAL '1 second')",
        queued,
        user_id,
    )

    assert (await auth_client.post("/api/listenbrainz/toggle", json={"enabled": False})).json()["enabled"] is False
    await _play(db, await _track(db, 2), user_id, _now() + timedelta(seconds=1))
    status_response = (await auth_client.get("/api/listenbrainz/status")).json()
    assert status_response["enabled"] is False
    assert status_response["pending"] == 1  # the backlog, not the paused play

    assert (await auth_client.post("/api/listenbrainz/toggle", json={"enabled": True})).status_code == 200
    assert await db.fetchval('SELECT listenbrainz_since FROM "user" WHERE id = $1', user_id) == since

    assert await ListenBrainzSubmitter().drain() == 1
    assert fake_lb.submitted_titles() == ["Song 1"]
    rows = await db.fetch(
        "SELECT t.title, s.status FROM listenbrainz_submission s"
        " JOIN playback_history ph ON ph.id = s.playback_history_id JOIN track t ON t.id = ph.track_id"
    )
    assert {r["title"]: r["status"] for r in rows} == {"Song 1": "submitted", "Song 2": "skipped"}


@pytest.mark.asyncio
async def test_reconnect_while_paused_does_not_send_paused_plays(auth_client, db, fake_lb):
    since = _now() - timedelta(hours=1)
    await auth_client.post("/api/listenbrainz/connect", json={"token": "good-token", "since": since.isoformat()})
    user_id = await _testuser_id(db)
    await auth_client.post("/api/listenbrainz/toggle", json={"enabled": False})
    await _play(db, await _track(db, 1), user_id, _now() + timedelta(seconds=1))

    assert (await auth_client.post("/api/listenbrainz/connect", json={"token": "good-token"})).status_code == 200
    assert await ListenBrainzSubmitter().drain() == 0
    assert fake_lb.calls == []
    assert await db.fetchval("SELECT status FROM listenbrainz_submission") == "skipped"


@pytest.mark.asyncio
async def test_disconnect_clears_account(auth_client, db, fake_lb):
    await auth_client.post("/api/listenbrainz/connect", json={"token": "good-token"})
    assert (await auth_client.post("/api/listenbrainz/disconnect")).status_code == 200
    row = await db.fetchrow(
        'SELECT listenbrainz_token, listenbrainz_since FROM "user" WHERE username = $1', "testuser"
    )
    assert row["listenbrainz_token"] is None
    assert row["listenbrainz_since"] is None
    assert (await auth_client.get("/api/listenbrainz/status")).json()["connected"] is False


@pytest.mark.asyncio
async def test_toggle_requires_connection(auth_client, fake_lb):
    response = await auth_client.post("/api/listenbrainz/toggle", json={"enabled": True})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_popularity_labs_and_radio_requests():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.url.path, dict(request.url.params)))
        if request.url.host == "labs.api.listenbrainz.org":
            return httpx.Response(200, json=[{"artist_mbid": ARTIST_B, "name": "B", "score": 1}])
        if "lb-radio" in request.url.path:
            return httpx.Response(200, json={ARTIST_B: [{"similar_artist_name": "B"}]})
        return httpx.Response(200, json=[{"recording_mbid": RECORDING, "recording_name": "T"}])

    client = _client(handler)
    assert (await client.top_recordings_for_artist(ARTIST_A))[0]["recording_name"] == "T"
    assert (await client.similar_artists(ARTIST_A))[0]["name"] == "B"
    assert ARTIST_B in await client.radio_similar_artists(ARTIST_A, 5)
    top, labs, radio = seen
    assert top[1] == f"/1/popularity/top-recordings-for-artist/{ARTIST_A}"
    assert labs[0] == "labs.api.listenbrainz.org"
    assert labs[2]["artist_mbids"] == ARTIST_A
    assert labs[2]["algorithm"] == lb.SIMILAR_ARTISTS_ALGORITHM
    assert radio[1] == f"/1/lb-radio/artist/{ARTIST_A}"
    assert radio[2]["max_similar_artists"] == "5"
    await client.aclose()


@pytest.mark.asyncio
async def test_unexpected_reply_shapes_are_unavailable():
    client = _client(lambda r: httpx.Response(200, json={"not": "a list"}))
    with pytest.raises(lb.ListenBrainzUnavailableError):
        await client.top_recordings_for_artist(ARTIST_A)
    with pytest.raises(lb.ListenBrainzUnavailableError):
        await client.similar_artists(ARTIST_A)
    await client.aclose()
