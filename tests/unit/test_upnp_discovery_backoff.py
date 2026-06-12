"""Failure backoff / suspension state machine for UPnP renderer discovery."""

import logging
import time
from unittest.mock import MagicMock

import pytest

from app.services.upnp.discovery import (
    UPnPDiscovery,
    _FAILURE_COOLDOWN_STEPS,
    _SUSPEND_AFTER_FAILURES,
    _SUSPENDED_RETRY_INTERVAL,
)

LOCATION = "http://192.168.0.31:16854/desc.xml"


@pytest.fixture
def discovery():
    manager = MagicMock()
    return UPnPDiscovery(manager)


def _fail(discovery, n=1, bootid=None):
    for _ in range(n):
        discovery._track_failure(LOCATION, RuntimeError("boom"), bootid)


def test_first_failure_logs_warning(discovery, caplog):
    with caplog.at_level(logging.DEBUG, logger="app.services.upnp.discovery"):
        _fail(discovery)
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    discovery.manager.log.assert_called_once()


def test_repeat_failures_log_debug_not_error(discovery, caplog):
    _fail(discovery)
    discovery.manager.log.reset_mock()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="app.services.upnp.discovery"):
        _fail(discovery)
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]
    discovery.manager.log.assert_not_called()


def test_cooldown_steps_escalate(discovery):
    for i, step in enumerate(_FAILURE_COOLDOWN_STEPS):
        _fail(discovery)
        state = discovery._failure_state[LOCATION]
        assert state["failures"] == i + 1
        assert state["cooldown_until"] == pytest.approx(time.time() + step, abs=5)
        assert not discovery._should_attempt(LOCATION, None)


def test_attempt_allowed_after_cooldown_expires(discovery):
    _fail(discovery)
    discovery._failure_state[LOCATION]["cooldown_until"] = time.time() - 1
    assert discovery._should_attempt(LOCATION, None)


def test_suspension_after_max_failures(discovery, caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.upnp.discovery"):
        _fail(discovery, n=_SUSPEND_AFTER_FAILURES)
    state = discovery._failure_state[LOCATION]
    assert state["suspended"]
    assert state["cooldown_until"] == pytest.approx(
        time.time() + _SUSPENDED_RETRY_INTERVAL, abs=5
    )
    # Exactly one suspension WARNING at the moment of suspension (the first
    # failure logs its own WARNING), not on later failures.
    suspensions = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "probing at most" in r.message
    ]
    assert len(suspensions) == 1
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.services.upnp.discovery"):
        _fail(discovery)
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_suspended_device_skipped_until_bootid_changes(discovery):
    _fail(discovery, n=_SUSPEND_AFTER_FAILURES, bootid="1")
    assert not discovery._should_attempt(LOCATION, "1")
    assert not discovery._should_attempt(LOCATION, None)
    # New BOOTID means the device's UPnP stack restarted: fresh start.
    assert discovery._should_attempt(LOCATION, "2")
    assert LOCATION not in discovery._failure_state


def test_suspended_device_retried_after_interval(discovery):
    _fail(discovery, n=_SUSPEND_AFTER_FAILURES, bootid="1")
    discovery._failure_state[LOCATION]["cooldown_until"] = time.time() - 1
    assert discovery._should_attempt(LOCATION, "1")


def test_bootid_preserved_when_failure_has_none(discovery):
    _fail(discovery, bootid="1")
    _fail(discovery, bootid=None)
    assert discovery._failure_state[LOCATION]["bootid"] == "1"


def test_success_reset_makes_next_failure_warning_again(discovery, caplog):
    _fail(discovery, n=3)
    # _add_renderer pops state on success.
    discovery._failure_state.pop(LOCATION, None)
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="app.services.upnp.discovery"):
        _fail(discovery)
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_unknown_location_always_attempted(discovery):
    assert discovery._should_attempt("http://192.168.0.99:1234/desc.xml", None)
