"""Grid pages, id lists, detail, raw metadata, originals and their metadata-free copies,
thumbnails, renames and trashing."""

import json
import os
import re
import sqlite3
from typing import Any
from urllib.parse import quote

import polars as pl
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from comfylens import file_ops
from comfylens.analytics.collection import has_hash
from comfylens.analytics.scope import filter_files
from comfylens.api.schemas import (
    IdsQuery,
    IdsResponse,
    ImageDetail,
    ImagesPage,
    ImagesQuery,
    RawResponse,
    RenameRequest,
    RenameResponse,
    Sort,
    TrashRequest,
    TrashResponse,
)
from comfylens.api.server import (
    IMMUTABLE,
    MEDIA_TYPES,
    ApiError,
    Server,
    not_found,
    parse_id,
    same_origin,
    server_of,
    stored_json,
)
from comfylens.collection.drafts import rebuild_thumbnail
from comfylens.collection.store import HASH_RE
from comfylens.extract.normalize import size_facts
from comfylens.metadata.strip import CannotStrip, strip_metadata
from comfylens.paths import thumb_path, thumbs_dir

router = APIRouter(prefix="/api/images")
thumbs_router = APIRouter()

_SORT_COLUMNS = {
    "generated_at": "generated_at",
    "rel_path": "rel_path",
    "family": "model_family",
    "steps": "steps",
    "cfg": "cfg",
}
_ITEM_COLUMNS = [
    "id",
    "content_hash",
    "rel_path",
    "width",
    "height",
    pl.col("model_family").alias("family"),
    "generated_at",
    "status",
    "has_warnings",
    "timestamp_suspect",
    "saved",
]
_THUMB_NAME = re.compile(HASH_RE + r"\.webp")


def _sorted(server: Server, query: ImagesQuery | IdsQuery) -> pl.DataFrame:
    files = filter_files(server.store.current, query.filters, server)
    sort: Sort = query.sort
    column = _SORT_COLUMNS[sort.key]
    # Ties are broken by id, in the same direction.
    return files.sort([column, "id"], descending=[sort.descending] * 2, nulls_last=True)


@router.post("/query", response_model=ImagesPage)
def query(body: ImagesQuery, request: Request) -> dict[str, Any]:
    server = server_of(request)
    files = _sorted(server, body)
    page = (
        files.slice(body.offset, body.limit)
        .with_columns(has_hash(server.saved_hashes()).alias("saved"))
        .select(_ITEM_COLUMNS)
    )
    return {"total": files.height, "offset": body.offset, "items": page.to_dicts()}


@router.post("/ids", response_model=IdsResponse)
def ids(body: IdsQuery, request: Request) -> dict[str, Any]:
    return {"ids": _sorted(server_of(request), body)["id"].to_list()}


def _rows(conn: sqlite3.Connection, sql: str, *params: Any) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _file_row(conn: sqlite3.Connection, raw_id: str) -> dict[str, Any]:
    rows = _rows(conn, "SELECT * FROM files WHERE id = ?", parse_id(raw_id, "image"))
    if not rows:
        raise not_found("image", raw_id)
    return rows[0]


_BUSY = "the catalog is busy with an index run; try again"


@router.post("/trash", response_model=TrashResponse, dependencies=[Depends(same_origin)])
def trash(body: TrashRequest, request: Request) -> dict[str, Any]:
    """Move files to the system trash. Each file succeeds or fails on its own."""
    try:
        result = server_of(request).trash(body.ids)
    except sqlite3.OperationalError as e:
        raise ApiError(503, "catalog_busy", _BUSY) from e
    return {
        "trashed": result.removed,
        "failed": [{"id": i, "message": m} for i, m in result.failed],
    }


@router.get("/{raw_id}", response_model=ImageDetail)
def detail(raw_id: str, request: Request) -> dict[str, Any]:
    with server_of(request).reading() as conn:
        f = _file_row(conn, raw_id)
        file_id = f["id"]
        gens = _rows(conn, "SELECT * FROM generations WHERE file_id = ?", file_id)
        stages = _rows(
            conn,
            "SELECT stage_index AS 'index', node_id, class_type, seed, steps, cfg, sampler_name,"
            " scheduler, denoise, start_step, end_step, model_family, base_model, text_encoder,"
            " clip_type, lora_stack_key, positive_prompt, negative_prompt, guidance, shift,"
            " latent_source FROM sampler_stages WHERE file_id = ? ORDER BY stage_index",
            file_id,
        )
        loras = _rows(
            conn,
            "SELECT position, stage_index, node_id, entry, class_type, name_raw, name, base_name,"
            " step, strength_model, strength_clip, enabled, reachable FROM loras"
            " WHERE file_id = ? ORDER BY reachable DESC, stage_index, position IS NULL, position,"
            " node_id, entry",
            file_id,
        )
        inputs = _rows(
            conn, "SELECT node_id, filename, sha256 FROM input_images WHERE file_id = ?", file_id
        )
        warnings = _rows(
            conn, "SELECT code, node_id, message FROM warnings WHERE file_id = ?", file_id
        )
        reachable = dict(
            conn.execute(
                "SELECT node_id, reachable FROM nodes WHERE file_id = ?", (file_id,)
            ).fetchall()
        )
        prompt = conn.execute(
            "SELECT prompt_json FROM raw_metadata WHERE file_id = ?", (file_id,)
        ).fetchone()

    nodes = []
    if prompt and prompt[0]:
        for node_id, node in stored_json(prompt[0]).items():
            if not isinstance(node, dict):
                continue
            meta = node.get("_meta")
            title = meta.get("title") if isinstance(meta, dict) else None
            nodes.append(
                {
                    "id": node_id,
                    "class_type": str(node.get("class_type", "")),
                    "title": title if isinstance(title, str) else None,
                    "reachable": bool(reachable.get(node_id, False)),
                    "inputs": node.get("inputs") if isinstance(node.get("inputs"), dict) else {},
                }
            )
    for lora in loras:
        lora["enabled"], lora["reachable"] = bool(lora["enabled"]), bool(lora["reachable"])
    gen = gens[0] if gens else None
    if gen is not None:
        del gen["file_id"]
    return {
        "file": {
            "id": f["id"],
            "rel_path": f["rel_path"],
            "format": f["format"],
            "size": f["size"],
            "width": f["width"],
            "height": f["height"],
            **size_facts(f["width"], f["height"]),
            "content_hash": f["content_hash"],
            "generated_at": f["generated_at"],
            "timestamp_suspect": bool(f["timestamp_suspect"]),
            "status": f["status"],
            "error": f["error"],
        },
        "generation": gen,
        "stages": stages,
        "loras": loras,
        "input_images": inputs,
        "nodes": nodes,
        "warnings": warnings,
    }


@router.post("/{raw_id}/rename", response_model=RenameResponse, dependencies=[Depends(same_origin)])
def rename(raw_id: str, body: RenameRequest, request: Request) -> dict[str, Any]:
    """Give a file a new base name in its directory; never replaces another file."""
    server = server_of(request)
    file_id = parse_id(raw_id, "image")
    try:
        renamed = server.rename(file_id, body.name)
    except file_ops.UnknownFile as e:
        raise not_found("image", raw_id) from e
    except file_ops.InvalidName as e:
        raise ApiError(400, "invalid_name", str(e)) from e
    except file_ops.NameTaken as e:
        raise ApiError(409, "name_taken", f"a file named {e} already exists") from e
    except file_ops.FileMissing as e:
        raise server.file_gone() from e
    except sqlite3.OperationalError as e:
        raise ApiError(503, "catalog_busy", _BUSY) from e
    except OSError as e:
        raise ApiError(500, "rename_failed", e.strerror or str(e)) from e
    return {"id": file_id, "rel_path": renamed.rel_path, "generated_at": renamed.generated_at}


@router.get("/{raw_id}/raw", response_model=RawResponse)
def raw(raw_id: str, request: Request) -> dict[str, Any]:
    with server_of(request).reading() as conn:
        file_id = _file_row(conn, raw_id)["id"]
        row = conn.execute(
            "SELECT sources, prompt_json, workflow_json, other_json FROM raw_metadata"
            " WHERE file_id = ?",
            (file_id,),
        ).fetchone()
    if row is None:
        return {"sources": {}, "prompt": None, "workflow": None, "other": {}}
    sources, prompt, workflow, other = row
    others = {}
    for key, text in (json.loads(other) if other else {}).items():
        try:
            others[key] = json.loads(text) if text.lstrip().startswith("{") else text
        except ValueError:
            others[key] = text
    return {
        "sources": json.loads(sources) if sources else {},
        "prompt": stored_json(prompt),
        "workflow": stored_json(workflow),
        "other": others,
    }


def _original_path(request: Request, raw_id: str) -> tuple[str, str]:
    """The file's absolute path and media type. The path comes from the catalog only, never
    from the request."""
    server = server_of(request)
    with server.reading() as conn:
        f = _file_row(conn, raw_id)
    try:
        path = file_ops.library_path(server.root, f["rel_path"])
    except file_ops.FileMissing:
        path = None
    if path is None or not os.path.isfile(path):
        raise ApiError(404, "not_found", "the original file is missing")
    return path, MEDIA_TYPES.get(f["format"], "application/octet-stream")


@router.get("/{raw_id}/file", response_model=None)
def original(raw_id: str, request: Request, download: bool = False) -> FileResponse:
    """The original bytes."""
    path, media_type = _original_path(request, raw_id)
    return FileResponse(
        path,
        media_type=media_type,
        filename=os.path.basename(path),
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{raw_id}/stripped", response_model=None)
def stripped(raw_id: str, request: Request) -> Response:
    """A copy of the original without its metadata, as an attachment under the same name."""
    path, media_type = _original_path(request, raw_id)
    try:
        with open(path, "rb") as f:
            data = strip_metadata(f.read())
    except FileNotFoundError as e:
        raise ApiError(404, "not_found", "the original file is missing") from e
    except CannotStrip as e:
        raise ApiError(422, "cannot_strip", str(e)) from e
    except OSError as e:
        raise ApiError(500, "read_failed", e.strerror or str(e)) from e
    # As FileResponse writes it: a name that needs escaping goes in filename*.
    name = os.path.basename(path)
    quoted = quote(name)
    disposition = f'filename="{name}"' if quoted == name else f"filename*=utf-8''{quoted}"
    return Response(
        data, media_type=media_type, headers={"Content-Disposition": f"attachment; {disposition}"}
    )


@thumbs_router.get("/thumbs/{name}", response_model=None)
def thumbnail(name: str, request: Request) -> FileResponse:
    """Only a 32-character lowercase hex hash is accepted; anything else is 404.

    Index runs restore library thumbnails; a collection image's is rebuilt here, on request.
    """
    if not _THUMB_NAME.fullmatch(name):
        raise ApiError(404, "not_found", "no such thumbnail")
    content_hash = name.removesuffix(".webp")
    path = thumb_path(thumbs_dir(), content_hash)
    server = server_of(request)
    if not path.is_file() and not (
        server.collection is not None
        and rebuild_thumbnail(server.collection, content_hash, server.config)
    ):
        raise ApiError(404, "not_found", "no such thumbnail")
    return FileResponse(
        path,
        media_type="image/webp",
        headers=IMMUTABLE,
    )
