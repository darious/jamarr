from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)



from fastapi import BackgroundTasks
from app.scanner.scan import scan_library

from fastapi.staticfiles import StaticFiles
from app.media import art
from app.api import library, stream

app.include_router(art.router)
app.include_router(library.router)
app.include_router(stream.router)

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_library, "/root/music")
    return {"message": "Scan started"}

app.mount("/", StaticFiles(directory="web", html=True), name="web")
