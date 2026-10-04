"""Export and import: the whole collection as one zip, for backup or another machine.

The zip holds a manifest and the reference images byte for byte:

    comfylens-collection.json
    originals/<content hash>.<png|jpg|webp>

Importing adds the prompts whose uid the collection does not have yet, so importing the same
archive twice adds nothing. Nothing in an archive is trusted: the manifest is validated, every
image must hash to its name and be a PNG, JPEG or WebP, and sizes are bounded before reading.
"""

import json
import time
import zipfile
from dataclasses import dataclass
from typing import IO, Annotated, Any, Literal

import xxhash
from pydantic import BaseModel, Field, ValidationError

from comfylens.collection.drafts import MAX_UPLOAD_BYTES, UnsupportedImage, identify
from comfylens.collection.models import PromptSettings
from comfylens.collection.store import EXTENSIONS, CollectionStore, InvalidInput

MANIFEST = "comfylens-collection.json"
FORMAT = "comfylens-collection"
VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024 * 1024

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class InvalidArchive(ValueError):
    """Not a collection archive this comfylens can import; the message says why."""


class ArchiveImage(BaseModel):
    content_hash: Hash
    role: Literal["reference", "attempt"]
    position: int = Field(ge=0)


class ArchivePrompt(BaseModel):
    uid: str = Field(pattern=r"^[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=200)
    positive: str
    negative: str
    notes: str
    source_url: str | None
    model_family: str | None
    settings: PromptSettings
    tags: list[str]
    images: list[ArchiveImage]
    created_at: int
    updated_at: int


class ArchiveOriginal(BaseModel):
    content_hash: Hash
    format: Literal["png", "jpeg", "webp"]
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    size: int = Field(ge=0, le=MAX_UPLOAD_BYTES)
    api_prompt: str | None
    workflow: str | None


class Manifest(BaseModel):
    format: Literal["comfylens-collection"]
    version: int
    exported_at: int
    prompts: list[ArchivePrompt]
    originals: list[ArchiveOriginal]


@dataclass(frozen=True, slots=True)
class ImportStats:
    added: int  # prompts new to this collection
    skipped: int  # prompts it already had (same uid)
    images: int  # reference images in the archive


def _member(original: ArchiveOriginal | dict[str, Any]) -> str:
    o = original if isinstance(original, dict) else original.model_dump()
    return f"originals/{o['content_hash']}.{EXTENSIONS[o['format']]}"


def export_zip(store: CollectionStore, out: IO[bytes]) -> tuple[int, int]:
    """Write the collection to `out`; returns how many prompts and images it holds.

    An original whose file has gone missing is left out; its prompts keep their other images.
    """
    prompts, originals = store.export_rows()
    present = [o for o in originals if store.original(o["content_hash"]) is not None]
    manifest = Manifest(
        format=FORMAT,
        version=VERSION,
        exported_at=int(time.time()),
        prompts=[ArchivePrompt.model_validate(p) for p in prompts],
        originals=[ArchiveOriginal.model_validate(o) for o in present],
    )
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(MANIFEST, manifest.model_dump_json(indent=1), zipfile.ZIP_DEFLATED)
        for o in present:
            found = store.original(o["content_hash"])
            if found is not None:
                # Images are compressed already: stored, not deflated.
                z.write(found["path"], _member(o), zipfile.ZIP_STORED)
    return len(prompts), len(present)


def _read(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    try:
        info = z.getinfo(name)
    except KeyError:
        raise InvalidArchive(f"{name} is missing from the archive") from None
    if info.file_size > limit:
        raise InvalidArchive(f"{name} is larger than {limit >> 20} MiB")
    try:
        return z.read(info)  # the size and CRC are checked while reading
    except (zipfile.BadZipFile, OSError, EOFError) as e:
        raise InvalidArchive(f"{name} is damaged: {e}") from e


def import_zip(store: CollectionStore, source: IO[bytes]) -> ImportStats:
    """Add an archive's new prompts and their images; raises InvalidArchive.

    The database changes happen in one transaction: a bad prompt imports nothing. Image files
    are written first, so an import that fails leaves at most unused files, which the
    collection's garbage collection removes.
    """
    try:
        z = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as e:
        raise InvalidArchive("not a zip file") from e
    with z:
        try:
            raw = json.loads(_read(z, MANIFEST, MAX_MANIFEST_BYTES))
        except ValueError as e:
            raise InvalidArchive("the manifest is not valid JSON") from e
        if not isinstance(raw, dict) or raw.get("format") != FORMAT:
            raise InvalidArchive("not a comfylens collection archive")
        version = raw.get("version")
        if not isinstance(version, int) or version > VERSION:
            raise InvalidArchive(
                f"the archive is version {version}; this comfylens reads up to {VERSION}"
            )
        try:
            manifest = Manifest.model_validate(raw)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise InvalidArchive(f"the manifest is invalid at {where}: {first['msg']}") from e
        for o in manifest.originals:
            data = _read(z, _member(o), MAX_UPLOAD_BYTES)
            if xxhash.xxh3_128_hexdigest(data) != o.content_hash:
                raise InvalidArchive(f"{_member(o)} does not match its hash")
            try:
                fmt, width, height = identify(data)
            except UnsupportedImage as e:
                raise InvalidArchive(f"{_member(o)} is not a PNG, JPEG or WebP image") from e
            if fmt != o.format:
                raise InvalidArchive(f"{_member(o)} is not a {o.format.upper()} image")
            store.write_file(o.content_hash, fmt, data)
            o.width, o.height, o.size = width, height, len(data)
    try:
        added, skipped = store.import_rows(
            [p.model_dump() for p in manifest.prompts],
            [o.model_dump() for o in manifest.originals],
        )
    except InvalidInput as e:
        raise InvalidArchive(f"a prompt in the archive is invalid: {e}") from e
    return ImportStats(added, skipped, len(manifest.originals))
