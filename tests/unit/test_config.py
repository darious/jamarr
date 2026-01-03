import os

import pytest

import app.config as config


def _set_config_path(tmp_path, contents: str, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(contents)
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    config._config = None  # reset cache
    return path


def test_env_overrides_config(monkeypatch, tmp_path):
    _set_config_path(
        tmp_path,
        """
music_path: "/cfg/music/"
musicbrainz:
  root_url: "https://from-config.example"
qobuz:
  region: "us-en"
""",
        monkeypatch,
    )
    monkeypatch.setenv("MUSIC_PATH", "/env/music/")
    monkeypatch.setenv("MUSICBRAINZ_ROOT_URL", "http://env-mb")

    assert config.get_music_path() == "/env/music/"
    assert config.get_musicbrainz_root_url() == "http://env-mb"
    assert config.get_qobuz_region() == "us-en"


def test_required_env_values_returned(monkeypatch, tmp_path):
    _set_config_path(tmp_path, "{}", monkeypatch)
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("QOBUZ_APP_ID", "appid")
    monkeypatch.setenv("QOBUZ_SECRET", "qsecret")
    monkeypatch.setenv("QOBUZ_EMAIL", "user@example.com")
    monkeypatch.setenv("QOBUZ_PASSWORD", "pass")
    monkeypatch.setenv("TIDAL_CLIENT_ID", "tid")
    monkeypatch.setenv("TIDAL_CLIENT_SECRET", "tsecret")
    monkeypatch.setenv("LASTFM_API_KEY", "lkey")
    monkeypatch.setenv("LASTFM_SHARED_SECRET", "lsecret")
    monkeypatch.setenv("FANARTTV_API_KEY", "fkey")
    monkeypatch.setenv("PEARLARR_URL", "https://pear.example")

    assert config.get_spotify_credentials() == ("cid", "csecret")
    assert config.get_qobuz_credentials() == (
        "appid",
        "qsecret",
        "user@example.com",
        "pass",
    )
    assert config.get_tidal_credentials() == ("tid", "tsecret")
    assert config.get_lastfm_credentials() == ("lkey", "lsecret")
    assert config.get_fanarttv_api_key() == "fkey"
    assert config.get_pearlarr_url() == "https://pear.example"


@pytest.mark.parametrize(
    "env_var, getter",
    [
        ("SPOTIFY_CLIENT_ID", config.get_spotify_credentials),
        ("SPOTIFY_CLIENT_SECRET", config.get_spotify_credentials),
        ("QOBUZ_APP_ID", config.get_qobuz_credentials),
        ("QOBUZ_SECRET", config.get_qobuz_credentials),
        ("QOBUZ_EMAIL", config.get_qobuz_credentials),
        ("QOBUZ_PASSWORD", config.get_qobuz_credentials),
        ("TIDAL_CLIENT_ID", config.get_tidal_credentials),
        ("TIDAL_CLIENT_SECRET", config.get_tidal_credentials),
        ("LASTFM_API_KEY", config.get_lastfm_credentials),
        ("LASTFM_SHARED_SECRET", config.get_lastfm_credentials),
        ("FANARTTV_API_KEY", config.get_fanarttv_api_key),
        ("PEARLARR_URL", config.get_pearlarr_url),
    ],
)
def test_required_env_missing_raises(monkeypatch, tmp_path, env_var, getter):
    # Clear cache and config path
    _set_config_path(tmp_path, "{}", monkeypatch)
    # Ensure all relevant env vars removed for this test
    for key in [
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "QOBUZ_APP_ID",
        "QOBUZ_SECRET",
        "QOBUZ_EMAIL",
        "QOBUZ_PASSWORD",
        "TIDAL_CLIENT_ID",
        "TIDAL_CLIENT_SECRET",
        "LASTFM_API_KEY",
        "LASTFM_SHARED_SECRET",
        "FANARTTV_API_KEY",
        "PEARLARR_URL",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError):
        getter()
