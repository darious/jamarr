from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.upnp import UPnPManager
    from app.scanner.scan_manager import ScanManager
    from app.scanner.dns_resolver import warm_dns_cache
    from app.scheduler import Scheduler

    # Critical: Warm DNS cache and install monkey-patch BEFORE any clients are created
    await warm_dns_cache()

    UPnPManager.get_instance().start_background_scan()
    # ScanManager is lazy initialized but good to have it ready
    ScanManager.get_instance()
    await Scheduler.get_instance().start()
    yield
    await Scheduler.get_instance().stop()
    await UPnPManager.get_instance().stop_background_scan()
    await ScanManager.get_instance().shutdown()
    await close_db()


app = FastAPI(lifespan=lifespan)


# Configure Centralized Logging
from app.logging_conf import configure_logging  # noqa: E402

configure_logging()


from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pathlib import Path  # noqa: E402
from app.media import art  # noqa: E402
from app.api import library, stream, player, search, scan, auth, media_quality, charts, lastfm, history, scheduler  # noqa: E402
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

app.include_router(playlist.router)
app.include_router(charts.router, prefix="/api")
app.include_router(lastfm.router)
app.include_router(history.router)
app.include_router(scheduler.router)


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


@app.get("/{path:path}")
async def spa(path: str):
    # Let API and art routes fall through to their handlers
    if path.startswith("api/") or path.startswith("art/"):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not Found")

    target = build_dir / path
    if target.is_file():
        return FileResponse(target)

    index_path = build_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Not Found")
