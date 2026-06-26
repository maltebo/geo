"""Public read-only map page and hosted per-search map pages."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from pressmuenzen.config import get_settings
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import Coordinate
from pressmuenzen.services.maps import machines_to_geojson, parse_map_token
from pressmuenzen.services.search import SearchService
from pressmuenzen.web.app import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def public_map(request: Request) -> HTMLResponse:
    # The public page fetches /api/machines client-side (keeps it lightweight).
    return templates.TemplateResponse(
        request,
        "map.html",
        {
            "title": "Pressmünzen-Karte",
            "embedded_geojson": None,
            "api_url": "/api/machines",
            "bot_username": get_settings().telegram_bot_username,
        },
    )


@router.get("/map/{token}", response_class=HTMLResponse)
async def hosted_map(request: Request, token: str) -> HTMLResponse:
    payload = parse_map_token(token)
    if payload is None:
        return HTMLResponse("Link ungültig oder abgelaufen.", status_code=404)

    mode = payload["mode"]

    if mode == "diff":
        old_point = (
            json.dumps({"lat": payload["old_lat"], "lon": payload["old_lon"]})
            if "old_lat" in payload
            else "null"
        )
        new_point = json.dumps({"lat": payload["new_lat"], "lon": payload["new_lon"]})
        return templates.TemplateResponse(
            request,
            "diff_map.html",
            {
                "title": f"Positionskorrektur – {payload['name']}",
                "machine_name": payload["name"],
                "old_point": old_point,
                "new_point": new_point,
            },
        )

    origin = Coordinate(lat=payload["lat"], lon=payload["lon"])
    value = payload["value"]

    async with session_scope() as session:
        service = SearchService(MachineRepository(session))
        if mode == "radius":
            hits = await service.within_radius(origin, float(value))
            show_origin: Coordinate | None = origin
        elif mode == "nearest":
            hits = await service.nearest(origin, int(value))
            show_origin = origin
        else:  # "all"
            hits = await service.all_machines()
            show_origin = None

    geojson = machines_to_geojson(hits, origin=show_origin)
    return templates.TemplateResponse(
        request,
        "map.html",
        {
            "title": "Pressmünzen – Suchergebnis",
            "embedded_geojson": json.dumps(geojson),
            "api_url": None,
            "bot_username": get_settings().telegram_bot_username,
        },
    )
