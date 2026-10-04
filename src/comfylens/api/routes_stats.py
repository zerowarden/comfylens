"""POST /api/stats, /api/timeline and /api/node-inputs/*."""

from typing import Any

import polars as pl
from fastapi import APIRouter, Request

from comfylens.analytics.node_inputs import input_keys, input_stats
from comfylens.analytics.scope import filter_files, resolve
from comfylens.analytics.stats import compute_stats, histogram_spec
from comfylens.analytics.timeline import timeline
from comfylens.api.schemas import (
    NodeKeysResponse,
    NodeStatsRequest,
    NodeStatsResponse,
    Scope,
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


@router.post("/node-inputs/keys", response_model=NodeKeysResponse)
def node_keys(body: Scope, request: Request) -> dict[str, Any]:
    server = server_of(request)
    snap = server.store.current
    resolved = resolve(snap, body, server.config.analysis, server)
    return {"scope": resolved.info, "keys": input_keys(snap, resolved)}


@router.post("/node-inputs/stats", response_model=NodeStatsResponse)
def node_stats(body: NodeStatsRequest, request: Request) -> dict[str, Any]:
    server = server_of(request)
    snap = server.store.current
    analysis = server.config.analysis
    resolved = resolve(snap, body, analysis, server)
    groups = input_stats(
        snap,
        resolved,
        body.class_type,
        body.input_name,
        round_decimals=analysis.round_decimals,
        top_n=analysis.top_n,
        histogram=histogram_spec(analysis),
    )
    return {
        "scope": resolved.info,
        "class_type": body.class_type,
        "input_name": body.input_name,
        "groups": groups,
    }
