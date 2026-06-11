"""SPA fallback must 404 probe paths instead of serving the index shell."""

import pytest

import app.main


@pytest.fixture
def build_dir(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html>jamarr</html>")
    (tmp_path / "robots.txt").write_text("User-agent: *\n")
    monkeypatch.setattr(app.main, "build_dir", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.env_production",
        "/.env~",
        "/.env.local.bak",
        "/exceptions.zip",
        "/error_log.php",
        "/wp-admin/setup-config.php",
        "/phpmyadmin/",
        "/.git/config",
        "/backup.sql",
        "/unknown-toplevel",
    ],
)
async def test_probe_paths_get_404(client, build_dir, path):
    resp = await client.get(path)
    assert resp.status_code == 404
    assert "jamarr" not in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/charts",
        "/login",
        "/settings/library",
        "/album/R.E.M./Murmur",  # route params may contain dots
        "/artist/some-mbid",
    ],
)
async def test_spa_routes_get_index(client, build_dir, path):
    resp = await client.get(path)
    assert resp.status_code == 200
    assert "jamarr" in resp.text


async def test_real_files_in_build_still_served(client, build_dir):
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert "User-agent" in resp.text
