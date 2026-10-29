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


AUDIO_ANALYSIS_SETTING_KEYS = ("batch_size", "concurrency", "timeout_seconds")


def get_audio_analysis_settings():
    """Return AudioAnalysisRunner overrides set in config.yaml.

    Only keys actually present are returned, so the runner keeps its own
    defaults for anything the deployment has not tuned.
    """
    section = load_config().get("audio_analysis") or {}
    settings = {}
    for key in AUDIO_ANALYSIS_SETTING_KEYS:
        value = section.get(key)
        if value is None:
            continue
        settings[key] = int(value)
    return settings


def get_user_agent():
    return "Jamarr/0.1 ( internal )"


def get_art_resize_workers() -> int:
    """How many artwork resizes may decode at once (default 2, minimum 1).

    Env ``ART_RESIZE_WORKERS`` wins over ``artwork.resize_workers`` in
    config.yaml. Each in-flight resize holds the decoded source (reduced where
    the format allows) plus the output, so this bounds peak image memory.
    """
    value = os.environ.get("ART_RESIZE_WORKERS")
    if not value:
        try:
            value = (load_config().get("artwork") or {}).get("resize_workers")
        except (FileNotFoundError, AttributeError):
            value = None
    try:
        return max(1, int(value)) if value else 2
    except (TypeError, ValueError):
        return 2


def get_upnp_source_ip():
    """Optional IPv4 address UPnP discovery binds to and advertises in stream URLs.

    Env ``UPNP_SOURCE_IP`` wins over ``renderer.upnp_source_ip`` in
    config.yaml. ``None`` (the default) keeps the default-route address.
    """
    value = os.environ.get("UPNP_SOURCE_IP")
    if not value:
        try:
            value = (load_config().get("renderer") or {}).get("upnp_source_ip")
        except (FileNotFoundError, AttributeError):
            value = None
    value = str(value).strip() if value else ""
    return value or None


DEFAULT_UPNP_EVENT_PORT = 8113


def get_upnp_event_config():
    """UPnP event (GENA) subscription settings.

    ``renderer.upnp_events`` (env ``UPNP_EVENTS``): ``false`` turns event
    subscriptions off, leaving the monitor on 1 s polling. ``renderer.
    upnp_event_port`` (env ``UPNP_EVENT_PORT``, default 8113): TCP port of the
    NOTIFY callback server, bound to the UPnP source address; ``0`` lets the
    OS pick one.
    """
    try:
        section = load_config().get("renderer") or {}
    except (FileNotFoundError, AttributeError):
        section = {}
    if not isinstance(section, dict):
        section = {}
    enabled_env = os.environ.get("UPNP_EVENTS")
    if enabled_env:
        enabled = enabled_env.strip().lower() not in ("false", "0", "no", "off")
    else:
        enabled = section.get("upnp_events", True) is not False
    port_env = os.environ.get("UPNP_EVENT_PORT")
    raw_port = port_env if port_env else section.get("upnp_event_port", DEFAULT_UPNP_EVENT_PORT)
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = DEFAULT_UPNP_EVENT_PORT
    return {"enabled": enabled, "port": port}


def _normalize_udn(value) -> str:
    udn = str(value or "").strip().lower()
    return udn[len("uuid:"):] if udn.startswith("uuid:") else udn


def get_upnp_gapless_config():
    """Per-renderer SetNextAVTransportURI staging policy from config.yaml.

    ``renderer.upnp_gapless``: ``enabled: false`` switches staging off for
    every renderer; ``disabled_udns`` never stage; ``forced_udns`` stage even
    when the device description does not advertise the action. UDNs match
    case-insensitively, with or without the ``uuid:`` prefix.
    """
    try:
        section = (load_config().get("renderer") or {}).get("upnp_gapless") or {}
    except (FileNotFoundError, AttributeError):
        section = {}
    if not isinstance(section, dict):
        section = {}
    return {
        "enabled": section.get("enabled", True) is not False,
        "disabled_udns": {_normalize_udn(u) for u in section.get("disabled_udns") or [] if u},
        "forced_udns": {_normalize_udn(u) for u in section.get("forced_udns") or [] if u},
    }


def upnp_gapless_override(udn: str):
    """``"off"``, ``"on"`` or ``None`` (follow the device) for one renderer."""
    cfg = get_upnp_gapless_config()
    if not cfg["enabled"]:
        return "off"
    key = _normalize_udn(udn)
    if key in cfg["disabled_udns"]:
        return "off"
    if key in cfg["forced_udns"]:
        return "on"
    return None


CAST_QUEUE_DEFAULT_PRELOAD_SECONDS = 20


def _normalize_cast_uuid(value) -> str:
    uuid = str(value or "").strip().lower()
    return uuid[len("cast:"):] if uuid.startswith("cast:") else uuid


def get_cast_queue_config():
    """Server Cast receiver-queue (preload) policy from config.yaml.

    ``renderer.cast_queue``: ``enabled: true`` stages the next track in the
    receiver's queue on every Cast device; ``enabled_uuids`` turns it on for
    listed devices only (when ``enabled`` is unset or false);
    ``disabled_uuids`` always wins. ``preload_seconds`` is the receiver's
    preloadTime. Off by default: transition silence is unmeasured.
    """
    try:
        section = (load_config().get("renderer") or {}).get("cast_queue") or {}
    except (FileNotFoundError, AttributeError):
        section = {}
    if not isinstance(section, dict):
        section = {}
    try:
        preload = float(section.get("preload_seconds", CAST_QUEUE_DEFAULT_PRELOAD_SECONDS))
    except (TypeError, ValueError):
        preload = CAST_QUEUE_DEFAULT_PRELOAD_SECONDS
    return {
        "enabled": section.get("enabled") is True,
        "enabled_uuids": {_normalize_cast_uuid(u) for u in section.get("enabled_uuids") or [] if u},
        "disabled_uuids": {_normalize_cast_uuid(u) for u in section.get("disabled_uuids") or [] if u},
        "preload_seconds": max(0.0, preload),
    }


def cast_queue_enabled(uuid: str) -> bool:
    """Whether server Cast stages the next track in the receiver queue."""
    cfg = get_cast_queue_config()
    key = _normalize_cast_uuid(uuid)
    if key in cfg["disabled_uuids"]:
        return False
    return cfg["enabled"] or key in cfg["enabled_uuids"]
