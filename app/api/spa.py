"""Serves the web interface with SPA fallback.

Two candidate directories, in order: the built Vite output (`frontend/dist`, once that phase is
built) and `web/`, the dependency-free interim interface. Whichever exists is mounted, so adding
the real frontend build later needs no code change here.

The fallback returns index.html for any unmatched path so client-side routes survive a page
reload, while anything under /api, /health or /metrics is left alone to 404 properly.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.settings import REPO_ROOT, Settings

logger = structlog.get_logger(__name__)

# Prefixes that must keep their own 404 behaviour rather than being handed the SPA shell.
API_PREFIXES = ("/api", "/health", "/metrics")


def resolve_web_root(settings: Settings) -> Path | None:
    for candidate in (settings.frontend_dist_dir, REPO_ROOT / "web"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def mount_web_interface(app: FastAPI, settings: Settings) -> None:
    root = resolve_web_root(settings)
    if root is None:
        logger.warning(
            "web.not_mounted",
            looked_in=[str(settings.frontend_dist_dir), str(REPO_ROOT / "web")],
            consequence="only the API is served; / will return a JSON pointer to /api/docs",
        )

        @app.get("/", include_in_schema=False, response_model=None)
        async def _no_interface() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": "No web interface is built. The developer API is at /api/docs.",
                    "docs": "/api/docs",
                }
            )

        return

    index = root / "index.html"

    # Registered before the static mount so it wins for the bare root path.
    @app.get("/", include_in_schema=False, response_model=None)
    async def _index() -> FileResponse:
        return FileResponse(index)

    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def _spa_fallback(request: Request, full_path: str) -> FileResponse | JSONResponse:
        if request.url.path.startswith(API_PREFIXES):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # A request with a file extension is asking for an asset that does not exist; handing it
        # index.html would make a missing image look like a working page.
        if "." in Path(full_path).name:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(index)

    logger.info("web.mounted", root=str(root))
