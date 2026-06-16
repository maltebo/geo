"""FastAPI app: public read-only map, GeoJSON API, hosted per-search maps, admin."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pressmuenzen.logging import configure_logging

_BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Pressmuenzen", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")

    from pressmuenzen.web.routes import admin, api, health
    from pressmuenzen.web.routes import map as map_routes

    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(map_routes.router)
    app.include_router(admin.router)
    return app


app = create_app()
