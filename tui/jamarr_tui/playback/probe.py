from __future__ import annotations

import shutil


class NoBackendError(RuntimeError):
    """No supported audio backend was found on $PATH."""


def detect_backend() -> str:
    """Return the first available local audio backend name.

    Raises NoBackendError if mpv is not installed.
    """
    if shutil.which("mpv"):
        return "mpv"
    raise NoBackendError(
        "No local audio backend found. Install mpv and ensure it is on $PATH."
    )
