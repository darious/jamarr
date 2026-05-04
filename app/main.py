from contextlib import asynccontextmanager
import os
import re

from fastapi import FastAPI, HTTPException
from app.db import init_db, close_db
from app.security import configure_security_middleware, fastapi_docs_config, is_production


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.services.renderer import get_renderer_registry
    from app.scanner.scan_manager import ScanManager
    from app.scanner.dns_resolver import warm_dns_cache
    from app.scheduler import Scheduler

    # Critical: Warm DNS cache and install monkey-patch BEFORE any clients are created
    await warm_dns_cache()

    renderer_registry = get_renderer_registry()
    await renderer_registry.start_all()
    # ScanManager is lazy initialized but good to have it ready
    ScanManager.get_instance()
    await Scheduler.get_instance().start()
    yield
    await Scheduler.get_instance().stop()
    await renderer_registry.stop_all()
    await ScanManager.get_instance().shutdown()
    await close_db()


app = FastAPI(lifespan=lifespan, **fastapi_docs_config())
configure_security_middleware(app)

# Configure rate limiting (disabled in test/dev)
ENV = os.getenv("ENV", "development")

if ENV == "production":
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
else:
    # Disable rate limiting in dev/test
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    
    limiter = Limiter(key_func=get_remote_address, enabled=False)
    app.state.limiter = limiter


# Configure Centralized Logging
from app.logging_conf import configure_logging  # noqa: E402

configure_logging()

from app.monitoring import configure_monitoring_middleware  # noqa: E402

configure_monitoring_middleware(app)


from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pathlib import Path  # noqa: E402
from app.media import art  # noqa: E402
from app.api import library, stream, player, search, scan, auth, media_quality, charts, lastfm, history, scheduler, recommendation, favorites, cast_capability  # noqa: E402
from app import monitoring  # noqa: E402
from app import playlist  # noqa: E402

app.include_router(art.router)
app.include_router(art.router, prefix="/api")
app.include_router(library.router)
app.include_router(stream.router)
app.include_router(player.router)
app.include_router(search.router)
app.include_router(scan.router)
app.include_router(auth.router)
app.include_router(media_quality.router)
app.include_router(playlist.router)
app.include_router(charts.router, prefix="/api")
app.include_router(lastfm.router)
app.include_router(history.router)
app.include_router(scheduler.router)
app.include_router(recommendation.router, prefix="/api")
app.include_router(monitoring.router)
app.include_router(favorites.router)
app.include_router(cast_capability.router)


# Serve built SvelteKit frontend (output lives in web/build)
build_dir = Path("web/build")

if build_dir.exists():
    app.mount("/_app", StaticFiles(directory=build_dir / "_app"), name="svelte-app")
    app.mount(
        "/assets",
        StaticFiles(directory=build_dir / "assets", html=False, check_dir=False),
        name="assets",
    )
    app.mount(
        "/favicon.ico",
        StaticFiles(directory=build_dir, html=False, check_dir=False),
        name="favicon",
    )
else:
    print("Warning: web/build directory not found. Frontend will not be served.")


# Paths that must never fall through to the SPA index. Scanners probe these and
# a 200 (even if just the SvelteKit shell) lands the host in public exposure DBs.
_BLOCKED_PATH_PATTERNS = re.compile(
    r"""(?ix)
    (^|/) \.git(/|$)
    | (^|/) \.env (\.|/|$)
    | (^|/) \.htaccess$
    | (^|/) \.htpasswd$
    | \.(php|phtml|asp|aspx|jsp|cgi)(/|$)
    | (^|/) wp-(admin|login|content|includes|json) (/|$|\.)
    | (^|/) phpmyadmin (/|$)
    | (^|/) phpinfo (/|$|\.)
    | (^|/) administrator (/|$)
    | (^|/) \.well-known/ (?! security\.txt$ | acme-challenge/ )
    """
)


@app.get("/{path:path}")
async def spa(path: str):
    # Let API and art routes fall through to their handlers
    if path.startswith("api/") or path.startswith("art/"):
        raise HTTPException(status_code=404, detail="Not Found")

    if _BLOCKED_PATH_PATTERNS.search(path):
        raise HTTPException(status_code=404, detail="Not Found")

    if is_production() and path.rstrip("/") in {"docs", "redoc", "openapi.json"}:
        raise HTTPException(status_code=404, detail="Not Found")

    if '..' in path or '\0' in path or '\\' in path:
        raise HTTPException(status_code=404, detail="Not Found")

    base = str(build_dir.resolve())
    target = os.path.realpath(os.path.join(base, path.lstrip("/")))  # lgtm[py/path-injection]
    if not target.startswith(base + os.sep) and target != base:
        raise HTTPException(status_code=404, detail="Not Found")
    if os.path.isfile(target):
        return FileResponse(target)

    index_path = build_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    raise HTTPException(status_code=404, detail="Not Found")
