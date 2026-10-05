"""The saved-prompt collection: prompts, drafts, links to library images, and originals."""

import os
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from comfylens.analytics.collection import library_counts, library_ids
from comfylens.api.errors import ApiError, not_found, parse_id
from comfylens.api.schemas import (
    CollectionList,
    DeleteResponse,
    Draft,
    ImageCollection,
    ImportResponse,
    LinkRequest,
    LinkResponse,
    PromptInput,
    RawOriginal,
    SavedPrompt,
    TextDraftRequest,
    UnlinkRequest,
)
from comfylens.api.server import (
    IMMUTABLE,
    MEDIA_TYPES,
    Server,
    same_origin,
    server_of,
    stored_json,
)
from comfylens.collection.archive import InvalidArchive, export_filename, export_zip, import_zip
from comfylens.collection.drafts import (
    MAX_UPLOAD_BYTES,
    UnsupportedImage,
    build_draft,
    text_draft,
)
from comfylens.collection.models import EXTENSIONS
from comfylens.collection.store import (
    HASH,
    CollectionStore,
    InvalidInput,
    PromptData,
    UnknownOriginal,
)
from comfylens.extract.normalize import prompt_key
from comfylens.index import file_ops

router = APIRouter(prefix="/api/collection")

MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024


def _store(server: Server) -> CollectionStore:
    if server.collection is None:
        raise ApiError(
            503,
            "collection_unavailable",
            f"the prompt collection cannot be opened: {server.collection_error}",
        )
    return server.collection


@contextmanager
def _errors() -> Iterator[None]:
    """The store's exceptions as API errors."""
    try:
        yield
    except InvalidInput as e:
        raise ApiError(400, "invalid_request", str(e)) from e
    except UnknownOriginal as e:
        raise ApiError(400, "unknown_original", f"no collection image with hash {e}") from e
    except sqlite3.OperationalError as e:
        raise ApiError(503, "collection_busy", "the collection is busy; try again") from e


def _id(raw_id: str) -> int:
    return parse_id(raw_id, "saved prompt")


def _not_found(prompt_id: int) -> ApiError:
    return not_found("saved prompt", prompt_id)


def _saved_prompt(server: Server, store: CollectionStore, prompt_id: int) -> dict[str, Any]:
    with _errors():
        prompt = store.get(prompt_id)
        links = store.links(prompt_id)
    if prompt is None or links is None:
        raise _not_found(prompt_id)
    snap = server.store.current
    ids = library_ids(snap, [i["content_hash"] for i in prompt["images"]])
    images = [{**i, "library_ids": ids.get(i["content_hash"], [])} for i in prompt["images"]]
    counts = library_counts(snap, {prompt_id: links})
    del prompt["positive_key"], prompt["images"]
    return {
        **prompt,
        "references": [i for i in images if i["role"] == "reference"],
        "attempts": [i for i in images if i["role"] == "attempt"],
        "library_count": None if counts is None else counts[prompt_id],
    }


async def _receive(
    request: Request, limit: int, too_large: ApiError, write: Callable[[bytes], object]
) -> None:
    """Stream the request body into `write`, refusing it once it passes `limit` bytes."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit:
        raise too_large
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large
        write(chunk)


def _data(body: PromptInput) -> PromptData:
    return PromptData(**body.model_dump())


@router.get("/prompts", response_model=CollectionList)
def list_prompts(
    request: Request, q: str = "", tag: str | None = None, family: str | None = None
) -> dict[str, Any]:
    server = server_of(request)
    store = _store(server)
    with _errors():
        rows = store.summaries(q, tag, family)
        tags, families = store.facets()
        counts = server.library_counts()
    for row in rows:
        row["library_count"] = None if counts is None else counts.get(row["id"], 0)
    return {
        "items": rows,
        "tags": [{"value": v, "count": n} for v, n in tags],
        "families": [{"value": v, "count": n} for v, n in families],
    }


@router.get("/prompts/{raw_id}", response_model=SavedPrompt)
def get_prompt(raw_id: str, request: Request) -> dict[str, Any]:
    server = server_of(request)
    return _saved_prompt(server, _store(server), _id(raw_id))


@router.post("/prompts", response_model=SavedPrompt, dependencies=[Depends(same_origin)])
def create_prompt(body: PromptInput, request: Request) -> dict[str, Any]:
    server = server_of(request)
    store = _store(server)
    with _errors():
        prompt_id = store.create(_data(body))
    return _saved_prompt(server, store, prompt_id)


@router.post("/prompts/{raw_id}", response_model=SavedPrompt, dependencies=[Depends(same_origin)])
def update_prompt(raw_id: str, body: PromptInput, request: Request) -> dict[str, Any]:
    """Replace the fields, tags and references; attempts listed are linked in addition."""
    server = server_of(request)
    store = _store(server)
    prompt_id = _id(raw_id)
    with _errors():
        if not store.update(prompt_id, _data(body)):
            raise _not_found(prompt_id)
    return _saved_prompt(server, store, prompt_id)


@router.post(
    "/prompts/{raw_id}/delete", response_model=DeleteResponse, dependencies=[Depends(same_origin)]
)
def delete_prompt(raw_id: str, request: Request) -> dict[str, Any]:
    """Its copied images are removed later, once no prompt has used them for a day."""
    store = _store(server_of(request))
    prompt_id = _id(raw_id)
    with _errors():
        if not store.delete(prompt_id):
            raise _not_found(prompt_id)
    return {"deleted": True}


@router.post(
    "/prompts/{raw_id}/attempts", response_model=LinkResponse, dependencies=[Depends(same_origin)]
)
def link_attempts(raw_id: str, body: LinkRequest, request: Request) -> dict[str, Any]:
    """Link library images to the prompt by content hash."""
    server = server_of(request)
    store = _store(server)
    prompt_id = _id(raw_id)
    wanted = list(dict.fromkeys(body.file_ids))
    with server.reading() as conn:
        found = dict(
            conn.execute(
                f"SELECT id, content_hash FROM files WHERE id IN ({','.join('?' * len(wanted))})",
                wanted,
            ).fetchall()
        )
    hashes = [found[i] for i in wanted if found.get(i)]
    skipped = [i for i in wanted if not found.get(i)]
    with _errors():
        added = store.link_attempts(prompt_id, hashes)
    if added is None:
        raise _not_found(prompt_id)
    return {"added": added, "skipped": skipped}


@router.post(
    "/prompts/{raw_id}/attempts/remove",
    response_model=SavedPrompt,
    dependencies=[Depends(same_origin)],
)
def unlink_attempts(raw_id: str, body: UnlinkRequest, request: Request) -> dict[str, Any]:
    server = server_of(request)
    store = _store(server)
    prompt_id = _id(raw_id)
    with _errors():
        if not store.unlink_attempts(prompt_id, body.hashes):
            raise _not_found(prompt_id)
    return _saved_prompt(server, store, prompt_id)


def _draft(server: Server, store: CollectionStore, data: bytes) -> dict[str, Any]:
    with _errors():
        try:
            draft = build_draft(data, store, server.config)
        except UnsupportedImage as e:
            raise ApiError(400, "unsupported_image", str(e)) from e
    original = draft["original"]
    original["library_ids"] = library_ids(server.store.current, [original["content_hash"]]).get(
        original["content_hash"], []
    )
    return draft


@router.post("/drafts/upload", response_model=Draft, dependencies=[Depends(same_origin)])
async def upload(request: Request) -> dict[str, Any]:
    """The request body is the image file itself."""
    server = server_of(request)
    store = _store(server)
    too_large = ApiError(413, "too_large", f"images up to {MAX_UPLOAD_BYTES >> 20} MiB only")
    data = bytearray()
    await _receive(request, MAX_UPLOAD_BYTES, too_large, data.extend)
    return await run_in_threadpool(_draft, server, store, bytes(data))


@router.post(
    "/drafts/from-image/{raw_id}", response_model=Draft, dependencies=[Depends(same_origin)]
)
def draft_from_image(raw_id: str, request: Request) -> dict[str, Any]:
    """A draft from a library image: its bytes are copied into the collection."""
    server = server_of(request)
    store = _store(server)
    file_id = parse_id(raw_id, "image")
    with server.reading() as conn:
        row = conn.execute("SELECT rel_path FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise not_found("image", raw_id)
    try:
        with open(file_ops.library_path(server.root, row[0]), "rb") as f:
            data = f.read()
    except (file_ops.FileMissing, FileNotFoundError) as e:
        raise server.file_gone() from e
    return _draft(server, store, data)


@router.post("/drafts/text", response_model=Draft, dependencies=[Depends(same_origin)])
def draft_from_text(body: TextDraftRequest) -> dict[str, Any]:
    return text_draft(body.positive, body.negative)


@router.get("/for-image/{raw_id}", response_model=ImageCollection)
def for_image(raw_id: str, request: Request) -> dict[str, Any]:
    """Saved prompts a library image is linked to, and those with the same positive prompt."""
    server = server_of(request)
    store = _store(server)
    file_id = parse_id(raw_id, "image")
    with server.reading() as conn:
        row = conn.execute(
            "SELECT f.content_hash, g.positive_prompt FROM files f"
            " LEFT JOIN generations g ON g.file_id = f.id WHERE f.id = ?",
            (file_id,),
        ).fetchone()
    if row is None:
        raise not_found("image", raw_id)
    content_hash, positive = row
    key = prompt_key(positive)
    with _errors():
        linked = store.prompts_for_hash(content_hash) if content_hash else []
        same = store.prompts_for_key(key) if key is not None else []
    linked_ids = {pid for pid, _title, _role in linked}
    return {
        "linked": [{"id": pid, "title": t, "role": role} for pid, t, role in linked],
        "matching": [
            {"id": pid, "title": t, "role": None} for pid, t in same if pid not in linked_ids
        ],
    }


def _original(server: Server, content_hash: str) -> dict[str, Any]:
    original = None
    if HASH.fullmatch(content_hash):
        with _errors():
            original = _store(server).original(content_hash)
    if original is None:
        raise ApiError(404, "not_found", "no such collection image")
    return original


@router.get("/originals/{content_hash}", response_model=None)
def original_file(content_hash: str, request: Request, download: bool = False) -> FileResponse:
    original = _original(server_of(request), content_hash)
    return FileResponse(
        original["path"],
        media_type=MEDIA_TYPES[original["format"]],
        filename=f"{content_hash}.{EXTENSIONS[original['format']]}",
        content_disposition_type="attachment" if download else "inline",
        headers=IMMUTABLE,
    )


@router.get("/originals/{content_hash}/raw", response_model=RawOriginal)
def original_raw(content_hash: str, request: Request) -> dict[str, Any]:
    server = server_of(request)
    _original(server, content_hash)
    with _errors():
        texts = _store(server).original_metadata(content_hash)
    prompt, workflow = texts or (None, None)
    return {"prompt": stored_json(prompt), "workflow": stored_json(workflow)}


@router.get("/export", response_model=None)
def export(request: Request) -> FileResponse:
    """The whole collection as a zip download; see collection.archive."""
    store = _store(server_of(request))
    fd, path = tempfile.mkstemp(prefix="comfylens-export-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as out, _errors():
            export_zip(store, out)
    except BaseException:
        os.unlink(path)
        raise
    return FileResponse(
        path,
        media_type="application/zip",
        filename=export_filename(date.today()),
        background=BackgroundTask(os.unlink, path),
    )


def _import(store: CollectionStore, archive: Any) -> dict[str, Any]:
    with _errors():
        try:
            stats = import_zip(store, archive)
        except InvalidArchive as e:
            raise ApiError(400, "invalid_archive", str(e)) from e
    return {"added": stats.added, "skipped": stats.skipped, "images": stats.images}


@router.post("/import", response_model=ImportResponse, dependencies=[Depends(same_origin)])
async def import_archive(request: Request) -> dict[str, Any]:
    """The request body is an archive from /export. Prompts already here are skipped."""
    store = _store(server_of(request))
    too_large = ApiError(413, "too_large", f"archives up to {MAX_ARCHIVE_BYTES >> 30} GiB only")
    with tempfile.TemporaryFile() as archive:
        await _receive(request, MAX_ARCHIVE_BYTES, too_large, archive.write)
        archive.seek(0)
        return await run_in_threadpool(_import, store, archive)
