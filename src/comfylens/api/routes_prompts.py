"""POST /api/prompts and /api/prompts/distinctive."""

from typing import Any

import polars as pl
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from comfylens.analytics.distinctive import distinctive_terms
from comfylens.analytics.prompts import analyze_prompts
from comfylens.analytics.scope import resolve
from comfylens.api.schemas import (
    DistinctiveRequest,
    DistinctiveResponse,
    PromptsRequest,
    PromptsResponse,
    Scope,
)
from comfylens.api.server import ApiError, error_response, server_of

router = APIRouter(prefix="/api")


def _warming() -> JSONResponse:
    return error_response(503, "warming", "prompt analysis is still being prepared", warming=True)


@router.post("/prompts", response_model=PromptsResponse, responses={503: {}})
def prompts(body: PromptsRequest, request: Request) -> dict[str, Any] | JSONResponse:
    server = server_of(request)
    snap = server.store.current
    frames = snap.prompts
    if frames is None:
        return _warming()
    resolved = resolve(snap, body, server.config.analysis, server)
    groups = analyze_prompts(
        frames,
        resolved.rows.select("id", "content_hash", "group", "generated_at"),
        body.side,
        include_template=body.include_template,
        by=body.by,
        config=server.config.prompts,
    )
    return {"scope": resolved.info, "side": body.side, "groups": groups}


@router.post("/prompts/distinctive", response_model=DistinctiveResponse, responses={503: {}})
def distinctive(body: DistinctiveRequest, request: Request) -> dict[str, Any] | JSONResponse:
    """The selection against the rest of the filtered set, per family of the selection."""
    if not body.selection:
        raise ApiError(400, "selection_required", "select images to compare with the rest")
    server = server_of(request)
    snap = server.store.current
    frames = snap.prompts
    if frames is None:
        return _warming()
    analysis = server.config.analysis
    chosen = resolve(snap, body, analysis, server)
    filtered = resolve(snap, Scope(filters=body.filters), analysis, server)
    library = resolve(snap, Scope(), analysis, server)
    # Copies of selected images belong to neither side.
    picked = chosen.files.select("id", "content_hash")
    rest_rows = filtered.rows.filter(
        ~pl.col("id").is_in(picked["id"].implode())
        & ~pl.col("content_hash").is_in(picked["content_hash"].implode())
    )
    terms = distinctive_terms(
        frames,
        chosen.rows,
        rest_rows,
        library.rows,
        body.side,
        body.by,
        server.config.prompts.distinctive_alpha0,
    )
    groups = [{"family": group, **terms[group]} for group, _rows in chosen.groups()]
    return {"scope": chosen.info, "side": body.side, "groups": groups}
