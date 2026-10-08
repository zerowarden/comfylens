"""POST /api/stats and /api/timeline."""

from typing import Any

import polars as pl
from fastapi import APIRouter, Request

from comfylens.analytics import compute_stats, filter_files, resolve, timeline
from comfylens.api.schemas import (
    StatsRequest,
    StatsResponse,
    TimelineRequest,
    TimelineResponse,
)
from comfylens.api.server import server_of

router = APIRouter(prefix="/api")


@router.post("/stats", response_model=StatsResponse)
def stats(body: StatsRequest, request: Request) -> dict[str, Any]:
    server = server_of(request)
    snap = server.store.current
    analysis = server.config.analysis
    resolved = resolve(snap, body, analysis, server)
    groups = compute_stats(snap, resolved, list(body.sections), body.lora_key, analysis)
    return {"scope": resolved.info, "groups": groups}


@router.post("/timeline", response_model=TimelineResponse)
def get_timeline(body: TimelineRequest, request: Request) -> dict[str, Any]:
    server = server_of(request)
    snap = server.store.current
    base = filter_files(snap, body.filters, server, ignore_dates=True)
    selected = snap.images.filter(pl.col("id").is_in(body.selection)) if body.selection else None
    return timeline(base, selected, body.bucket)
