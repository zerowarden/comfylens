"""GET /api/index/status and POST /api/index/rescan."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

from comfylens.api.errors import ApiError
from comfylens.api.schemas import IndexStatusModel
from comfylens.api.server import Server, server_of

router = APIRouter(prefix="/api/index")


def index_status(server: Server) -> dict[str, Any]:
    status = asdict(server.indexer.status)
    # The run is not over for the client until the new snapshot is served: "idle" before the
    # swap would make the UI refetch too early and keep the old data.
    if status["state"] == "idle" and server.indexing:
        status["state"] = "finalizing" if server.rebuilding else "scanning"
    return {**status, "last_error": server.last_error, "last_finished_at": server.last_finished_at}


@router.get("/status", response_model=IndexStatusModel)
def status(request: Request) -> dict[str, Any]:
    return index_status(server_of(request))


@router.post("/rescan", response_model=IndexStatusModel, status_code=202)
def rescan(request: Request) -> dict[str, Any]:
    server = server_of(request)
    if not server.start_index():
        raise ApiError(409, "index_running", "an index run is already in progress")
    return index_status(server)
