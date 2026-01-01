import yaml
import os

CONFIG_PATH = "config.yaml"

_config = None


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
    return load_config().get("pearlarr", {}).get("url")


def get_music_path():
    return load_config().get("music_path", "/root/music")


def get_spotify_credentials():
    cfg = load_config().get("spotify", {})
    return cfg.get("client_id"), cfg.get("client_secret")


def get_musicbrainz_root_url():
    return (
        load_config().get("musicbrainz", {}).get("root_url", "https://musicbrainz.org")
    )


def get_musicbrainz_rate_limit():
    val = load_config().get("musicbrainz", {}).get("rate_limit", 1.0)
    if str(val).lower() == "none":
        return None
    return float(val)


def get_qobuz_region():
    return load_config().get("qobuz", {}).get("region", "us-en")


def get_qobuz_credentials():
    cfg = load_config().get("qobuz", {})
    return (
        cfg.get("app_id"),
        cfg.get("secret"),
        cfg.get("email"),
        cfg.get("password")
    )


def get_tidal_credentials():
    cfg = load_config().get("tidal", {})
    return cfg.get("client_id"), cfg.get("client_secret")


def get_fanarttv_api_key():
    """Return the configured Fanart.tv API key, if provided."""
    return load_config().get("fanarttv", {}).get("apikey")


def get_lastfm_credentials():
    config = load_config()
    lastfm = config.get("lastfm", {})
    return lastfm.get("apikey"), lastfm.get("sharedsecret")


def get_max_workers():
    return load_config().get("max_workers", 4)


def get_user_agent():
    return "Jamarr/0.1 ( internal )"
