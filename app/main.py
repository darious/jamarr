from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.upnp import UPnPManager
    UPnPManager.get_instance().start_background_scan()
    yield

app = FastAPI(lifespan=lifespan)



from fastapi import BackgroundTasks
from app.scanner.scan import scan_library

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from app.media import art
from app.api import library, stream, player

app.include_router(art.router)
app.include_router(library.router)
app.include_router(stream.router)
app.include_router(player.router)

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_library, "/root/music")
    return {"message": "Scan started"}

@app.post("/api/scan_artist")
async def trigger_artist_scan(artist_name: str, background_tasks: BackgroundTasks):
    from app.scanner.scan import refresh_artist_metadata
    background_tasks.add_task(refresh_artist_metadata, artist_name)
    return {"message": f"Metadata refresh started for {artist_name}"}

@app.post("/api/scan_artist_singles")
async def trigger_artist_singles_scan(artist_name: str, background_tasks: BackgroundTasks):
    from app.scanner.scan import refresh_artist_singles_only
    background_tasks.add_task(refresh_artist_singles_only, artist_name)
    return {"message": f"Singles refresh started for {artist_name}"}

# Serve built SvelteKit frontend (output lives in web/build)
build_dir = Path("web/build")
app.mount("/_app", StaticFiles(directory=build_dir / "_app", html=False, check_dir=False), name="svelte-app")
app.mount("/assets", StaticFiles(directory=build_dir / "assets", html=False, check_dir=False), name="assets")
app.mount("/favicon.ico", StaticFiles(directory=build_dir, html=False, check_dir=False), name="favicon")

@app.get("/{full_path:path}")
async def spa(full_path: str):
    # Let API and art routes fall through to their handlers
    if full_path.startswith("api/") or full_path.startswith("art/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
    index_path = build_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not Found")
