#!/usr/bin/env python
"""Dump the FastAPI OpenAPI schema to docs/reference/openapi.json.

Run from repo root:  uv run python scripts/docs/gen_openapi.py

Imports the FastAPI app and serialises app.openapi() without starting a server.
The generated file is consumed by docs/reference/api.md via the
mkdocs-swagger-ui-tag plugin. It is build-time output and gitignored; CI
regenerates it before every docs build.
"""

import json
import os
import sys
from pathlib import Path

# Repo root on path so `import app.main` works.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# App reads these at import time; provide harmless defaults so importing the
# module never tries to talk to a real database or external service.
os.environ.setdefault("JWT_SECRET_KEY", "docs-build-placeholder")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/placeholder")

OUT = ROOT / "docs" / "reference" / "openapi.json"


def main() -> int:
    from app.main import app  # noqa: E402  (env must be set first)

    schema = app.openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, indent=2) + "\n")
    paths = len(schema.get("paths", {}))
    print(f"Wrote {OUT.relative_to(ROOT)} ({paths} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
