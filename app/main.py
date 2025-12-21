from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.upnp import UPnPManager
    UPnPManager.get_instance().start_background_scan()
    yield
    UPnPManager.get_instance().stop_background_scan()

app = FastAPI(lifespan=lifespan)

# Configure Rich Logging
import logging
from rich.logging import RichHandler

FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)]
)

# Force Uvicorn to use RichHandler
for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    logger = logging.getLogger(logger_name)
    logger.handlers = [] # Remove default Uvicorn handlers
    logger.propagate = True # Let it bubble up to root (which has RichHandler)


# Silence chatty libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("async_upnp_client").setLevel(logging.WARNING)

# Filter out /api/player/state from access logs (too chatty due to polling)
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/api/player/state") == -1

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())



from fastapi import BackgroundTasks
from app.scanner.scan import scan_library

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from app.media import art
from app.api import library, stream, player, search

app.include_router(art.router)
app.include_router(library.router)
app.include_router(stream.router)
app.include_router(player.router)
app.include_router(search.router)

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks, force_rescan: bool = False):
    from app.config import get_music_path
    background_tasks.add_task(scan_library, get_music_path(), force_metadata=False, force_rescan=force_rescan)
    return {"message": "Scan started", "force_rescan": force_rescan}

@app.post("/api/scan_artist")
async def trigger_artist_scan(artist_name: str):
    from app.scanner.scan import refresh_artist_metadata
    await refresh_artist_metadata(artist_name)
    return {"message": f"Metadata refresh completed for {artist_name}"}

@app.post("/api/scan_artist_singles")
async def trigger_artist_singles_scan(artist_name: str):
    from app.scanner.scan import refresh_artist_singles_only
    await refresh_artist_singles_only(artist_name)
    return {"message": f"Singles refresh completed for {artist_name}"}

# Serve built SvelteKit frontend (output lives in web/build)
build_dir = Path("web/build")

if build_dir.exists():
    app.mount("/_app", StaticFiles(directory=build_dir / "_app"), name="svelte-app")
    app.mount("/assets", StaticFiles(directory=build_dir / "assets", html=False, check_dir=False), name="assets")
    app.mount("/favicon.ico", StaticFiles(directory=build_dir, html=False, check_dir=False), name="favicon")
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
