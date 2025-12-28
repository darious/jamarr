import logging
import logging.handlers
import os
from app.config import load_config


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
        handler.setFormatter(file_formatter)
        if level:
            handler.setLevel(level)
        return handler

    # 1. Root / Backend Logger
    # We want to capture everything else in backend.log, but exclude specific noisy children
    # that have their own files (scanner, upnp, player, access)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Backend Logger (Root) -> backend.log
    # We configure this via a filter on the handler attached to Root
    backend_handler = _setup_file_handler("backend", "backend.log")

    # 2. Scanner Logger
    scanner_logger = logging.getLogger("scanner")
    scanner_logger.setLevel(logging.DEBUG)
    scanner_handler = _setup_file_handler("scanner", "scanner.log")
    scanner_logger.addHandler(scanner_handler)

    # 3. UPnP Logger
    upnp_handler = _setup_file_handler("upnp", "upnp.log")

    upnp_logger = logging.getLogger("app.upnp")
    upnp_logger.setLevel(logging.DEBUG)  # UPnP manager uses debug extensively
    upnp_logger.addHandler(upnp_handler)

    upnp_client_logger = logging.getLogger("async_upnp_client")
    upnp_client_logger.setLevel(logging.WARNING)  # Keep library quiet
    upnp_client_logger.addHandler(upnp_handler)

    # 4. Player Logger
    player_logger = logging.getLogger("app.api.player")
    player_handler = _setup_file_handler("player", "player.log")
    player_logger.addHandler(player_handler)

    # 5. Frontend / Access Logger
    access_logger = logging.getLogger("uvicorn.access")
    access_handler = _setup_file_handler("frontend", "frontend.log")

    # Filter out /api/player/state from access logs (too chatty due to polling)
    class EndpointFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.getMessage().find("/api/player/state") == -1

    access_handler.addFilter(EndpointFilter())
    access_logger.addHandler(access_handler)
    access_logger.addFilter(EndpointFilter())  # Also filter propagation if enabled

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
                "uvicorn.access",
            ]
        )
    )
    root_logger.addHandler(backend_handler)

    # Enable propagation so they go to Console (which is on Root)
    scanner_logger.propagate = True
    upnp_logger.propagate = True
    upnp_client_logger.propagate = True
    player_logger.propagate = True
    access_logger.propagate = True

    return {"level": log_level, "dir": log_dir}
