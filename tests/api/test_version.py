import importlib

import pytest
from httpx import AsyncClient

from app import version as version_module


@pytest.mark.asyncio
async def test_version_requires_auth(client: AsyncClient):
    response = await client.get("/api/version")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_version_returns_the_running_build(auth_client: AsyncClient):
    response = await auth_client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"version": version_module.__version__}


def test_an_untagged_build_reports_dev(monkeypatch):
    # Nothing in the tree carries a version: it is baked in from the release
    # tag, so anything else must say so rather than claim a release number.
    monkeypatch.delenv("JAMARR_VERSION", raising=False)
    assert version_module.get_version() == "dev"

    monkeypatch.setenv("JAMARR_VERSION", "   ")
    assert version_module.get_version() == "dev"


def test_a_release_build_reports_its_tag(monkeypatch):
    monkeypatch.setenv("JAMARR_VERSION", "1.7.1")
    assert version_module.get_version() == "1.7.1"


def test_openapi_publishes_the_version(monkeypatch):
    # The generated API reference renders whatever FastAPI was given, which is
    # where the stale "0.1.0" used to come from.
    monkeypatch.setenv("JAMARR_VERSION", "9.9.9")
    reloaded = importlib.reload(version_module)
    try:
        assert reloaded.__version__ == "9.9.9"
    finally:
        monkeypatch.delenv("JAMARR_VERSION", raising=False)
        importlib.reload(version_module)
