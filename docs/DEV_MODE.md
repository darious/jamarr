# Development Mode Guide

## Quick Start

```bash
./dev.sh
```

This starts all services with hot-reload enabled. No rebuilds needed!

## What Changed?

### Before (The Problem)
- Frontend was built into Docker image at build time
- Any frontend change required `docker compose build` (slow!)
- Backend reload worked but you were rebuilding anyway

### After (The Solution)
- **Frontend**: Runs separately with Vite dev server (port 5173)
  - Hot Module Replacement (HMR) - instant updates!
  - No Docker rebuild needed
- **Backend**: Runs in Docker with uvicorn --reload
  - Auto-reloads on Python file changes
  - No Docker rebuild needed
- **Database & CloudBeaver**: Unchanged

## Services

| Service | URL | Hot Reload |
|---------|-----|------------|
| Frontend | http://127.0.0.1:5173 | ✅ Vite HMR |
| Backend API | http://127.0.0.1:8111 | ✅ Uvicorn --reload |
| PostgreSQL | localhost:8110 | N/A |
| CloudBeaver | http://127.0.0.1:8978 | N/A |

## Development Workflow

1. **Start dev mode**: `./dev.sh`
2. **Edit frontend code** (`web/src/**`): Changes appear instantly in browser
3. **Edit backend code** (`app/**`): Server auto-restarts in ~1-2 seconds
4. **No rebuilds needed!** 🎉

## Production Build

When ready to deploy:

```bash
docker compose build
docker compose up -d
```

This builds the frontend into the Docker image (as before) for production.

## Troubleshooting

### Frontend not updating?
- Check that Vite dev server is running (should see logs)
- Visit http://127.0.0.1:5173 (not 8111)

### Backend not reloading?
- Check volume mounts in docker-compose.dev.yml
- Ensure WATCHFILES_FORCE_POLLING=true is set

### Need to rebuild?
Only rebuild if you:
- Change Python dependencies (pyproject.toml)
- Change system dependencies (Dockerfile)
- Want to test production build
