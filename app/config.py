import os
import yaml

CONFIG_PATH = "config.yaml"

_config = None


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if value is None or value == "":
        raise ValueError(f"{var_name} must be set in the environment")
    return value


def load_config():
    global _config
    if _config:
        return _config

    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r") as f:
        _config = yaml.safe_load(f)
    return _config


def get_pearlarr_url():
    url = os.environ.get("PEARLARR_URL") or load_config().get("pearlarr", {}).get("url")
    if not url:
        raise ValueError("PEARLARR_URL must be set in the environment")
    return url


def get_music_path():
    return os.environ.get("MUSIC_PATH") or load_config().get("music_path", "/root/music")


def get_spotify_credentials():
    return _require_env("SPOTIFY_CLIENT_ID"), _require_env("SPOTIFY_CLIENT_SECRET")


def get_musicbrainz_root_url():
    return os.environ.get("MUSICBRAINZ_ROOT_URL") or load_config().get(
        "musicbrainz", {}
    ).get("root_url", "https://musicbrainz.org")


def get_musicbrainz_rate_limit():
    val = load_config().get("musicbrainz", {}).get("rate_limit", 1.0)
    if str(val).lower() == "none":
        return None
    return float(val)


def get_qobuz_region():
    return load_config().get("qobuz", {}).get("region", "us-en")


def get_qobuz_credentials():
    return (
        _require_env("QOBUZ_APP_ID"),
        _require_env("QOBUZ_SECRET"),
        _require_env("QOBUZ_EMAIL"),
        _require_env("QOBUZ_PASSWORD"),
    )


def get_tidal_credentials():
    return _require_env("TIDAL_CLIENT_ID"), _require_env("TIDAL_CLIENT_SECRET")


def get_fanarttv_api_key():
    """Return the configured Fanart.tv API key."""
    return _require_env("FANARTTV_API_KEY")


def get_lastfm_credentials():
    return _require_env("LASTFM_API_KEY"), _require_env("LASTFM_SHARED_SECRET")


def get_lastfm_api_key():
    """Return the Last.fm API key."""
    return _require_env("LASTFM_API_KEY")


def get_lastfm_shared_secret():
    """Return the Last.fm shared secret."""
    return _require_env("LASTFM_SHARED_SECRET")


def get_max_workers():
    return load_config().get("max_workers", 4)


def get_user_agent():
    return "Jamarr/0.1 ( internal )"
