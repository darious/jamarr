import logging
import logging.handlers
import os
from app.config import load_config
from app.security import redact_secrets, strip_query_string


def configure_logging():
    """
    Configure centralized logging with rotation.
    Reads settings from config.yaml.
    """
    config = load_config()
    log_config = config.get("logging", {})

    # Defaults
    log_level_str = log_config.get("level", "INFO").upper()
    max_bytes = log_config.get("rotation", {}).get(
        "max_bytes", 10 * 1024 * 1024
    )  # 10MB
    backup_count = log_config.get("rotation", {}).get("backup_count", 5)

    log_level = getattr(logging, log_level_str, logging.INFO)

    # Ensure log directory exists
    log_dir = "cache/log"
    os.makedirs(log_dir, exist_ok=True)

    class RedactingFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.msg = redact_secrets(record.msg)
            if isinstance(record.args, tuple):
                args = list(record.args)
                if record.name == "uvicorn.access" and len(args) >= 3:
                    args[2] = strip_query_string(str(args[2]))
                record.args = tuple(redact_secrets(arg) for arg in args)
            elif isinstance(record.args, dict):
                record.args = {
                    key: redact_secrets(value) for key, value in record.args.items()
                }
            return True

    redacting_filter = RedactingFilter()
    if not getattr(logging, "_jamarr_redaction_factory_installed", False):
        original_factory = logging.getLogRecordFactory()

        def redacting_record_factory(*args, **kwargs):
            record = original_factory(*args, **kwargs)
            redacting_filter.filter(record)
            return record

        logging.setLogRecordFactory(redacting_record_factory)
        logging._jamarr_redaction_factory_installed = True

    def _remove_managed_handlers(logger):
        for handler in list(logger.handlers):
            if getattr(handler, "_jamarr_managed", False):
                logger.removeHandler(handler)
                handler.close()

    # Formatter
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    def _setup_file_handler(name, filename, level=None):
        handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler._jamarr_managed = True
        handler.addFilter(redacting_filter)
        handler.setFormatter(file_formatter)
        if level:
            handler.setLevel(level)
        return handler

    # 1. Root / Backend Logger
    # We want to capture everything else in backend.log, but exclude specific noisy children
    # that have their own files (scanner, upnp, player, access)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    _remove_managed_handlers(root_logger)

    # Backend Logger (Root) -> backend.log
    # We configure this via a filter on the handler attached to Root
    backend_handler = _setup_file_handler("backend", "backend.log")

    # 2. Scanner Logger
    scanner_logger = logging.getLogger("scanner")
    _remove_managed_handlers(scanner_logger)
    scanner_logger.setLevel(logging.DEBUG)
    scanner_handler = _setup_file_handler("scanner", "scanner.log")
    scanner_logger.addHandler(scanner_handler)

    # 3. UPnP Logger
    upnp_handler = _setup_file_handler("upnp", "upnp.log")

    upnp_logger = logging.getLogger("app.upnp")
    _remove_managed_handlers(upnp_logger)
    upnp_logger.setLevel(logging.DEBUG)  # UPnP manager uses debug extensively
    upnp_logger.addHandler(upnp_handler)

    upnp_client_logger = logging.getLogger("async_upnp_client")
    _remove_managed_handlers(upnp_client_logger)
    upnp_client_logger.setLevel(logging.WARNING)  # Keep library quiet
    upnp_client_logger.addHandler(upnp_handler)

    # 4. Player Logger
    player_logger = logging.getLogger("app.api.player")
    _remove_managed_handlers(player_logger)
    player_handler = _setup_file_handler("player", "player.log")
    player_logger.addHandler(player_handler)

    # 5. Last.fm Logger
    lastfm_logger = logging.getLogger("app.api.lastfm")
    _remove_managed_handlers(lastfm_logger)
    lastfm_handler = _setup_file_handler("lastfm", "lastfm.log")
    lastfm_logger.addHandler(lastfm_handler)
    lastfm_logger.setLevel(logging.DEBUG)

    # 6. Uvicorn access logger. Query strings are stripped by RedactingFilter.
    access_logger = logging.getLogger("uvicorn.access")
    _remove_managed_handlers(access_logger)
    access_handler = _setup_file_handler("frontend", "frontend.log")

    # Filter out /api/player/state from access logs (too chatty due to polling)
    class EndpointFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.getMessage().find("/api/player/state") == -1

    access_handler.addFilter(EndpointFilter())
    access_logger.addHandler(access_handler)
    access_logger.addFilter(EndpointFilter())  # Also filter propagation if enabled

    # 7. Application access and security audit logs
    app_access_logger = logging.getLogger("app.monitoring.access")
    _remove_managed_handlers(app_access_logger)
    app_access_handler = _setup_file_handler("access", "access.log")
    app_access_logger.addHandler(app_access_handler)
    app_access_logger.setLevel(logging.INFO)

    security_logger = logging.getLogger("app.security.audit")
    _remove_managed_handlers(security_logger)
    security_handler = _setup_file_handler("security", "security.log")
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.INFO)

    # Ensure uvicorn propogates to root (backend log)
    # We do NOT add backend_handler here explicitly because it is already on root
    logging.getLogger("uvicorn").propagate = True
    logging.getLogger("uvicorn.error").propagate = True

    # Silence chatty libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)

    # Filter for Backend Log to exclude split logs
    class ExcludeFilter(logging.Filter):
        def __init__(self, excluded_names):
            self.excluded_names = excluded_names

        def filter(self, record):
            if any(record.name.startswith(n) for n in self.excluded_names):
                return False
            return True

    backend_handler.addFilter(
        ExcludeFilter(
            [
                "scanner",
                "app.upnp",
                "async_upnp_client",
                "app.api.player",
                "app.api.lastfm",
                "uvicorn.access",
                "app.monitoring.access",
                "app.security.audit",
            ]
        )
    )
    root_logger.addHandler(backend_handler)

    # Enable propagation so they go to Console (which is on Root)
    scanner_logger.propagate = True
    upnp_logger.propagate = True
    upnp_client_logger.propagate = True
    player_logger.propagate = True
    lastfm_logger.propagate = True
    access_logger.propagate = True
    app_access_logger.propagate = True
    security_logger.propagate = True

    return {"level": log_level, "dir": log_dir}
