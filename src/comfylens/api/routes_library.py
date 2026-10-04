"""GET /api/library and GET /api/facets."""

from importlib import metadata
from typing import Any

import polars as pl
from fastapi import APIRouter, Request

from comfylens import version
from comfylens.analytics.facets import facets
from comfylens.analytics.snapshot import NO_METADATA
from comfylens.api.routes_index import index_status
from comfylens.api.schemas import Facets, LibraryInfo
from comfylens.api.server import ApiError, server_of
from comfylens.db.connection import get_meta

router = APIRouter(prefix="/api")


@router.get("/library", response_model=LibraryInfo)
def library(request: Request) -> dict[str, Any]:
    server = server_of(request)
    snap = server.store.current
    images = snap.images
    last_index_at = None
    try:
        conn = server.connect()
    except ApiError:
        pass  # not indexed yet
    else:
        try:
            value = get_meta(conn, "last_index_at")
            last_index_at = int(value) if value else None
        finally:
            conn.close()
    return {
        "root": str(server.root),
        "total": images.height,
        "counts_by_status": dict(images.group_by("status").len().iter_rows()),
        "counts_by_family": dict(
            images.select(pl.col("model_family").fill_null(NO_METADATA))
            .group_by("model_family")
            .len()
            .iter_rows()
        ),
        "timestamp_suspect": int(images["timestamp_suspect"].sum()),
        "fts_available": snap.fts,
        "last_index_at": last_index_at,
        "index": index_status(server),
        "versions": {
            "app": metadata.version("comfylens"),
            "schema_version": version.SCHEMA_VERSION,
            "extractor_version": version.EXTRACTOR_VERSION,
        },
        "snapshot_built_at": snap.built_at,
        "prompts_ready": snap.prompts is not None,
        "watching": server.watching,
    }


@router.get("/facets", response_model=Facets)
def get_facets(request: Request) -> dict[str, Any]:
    return facets(server_of(request).store.current)
