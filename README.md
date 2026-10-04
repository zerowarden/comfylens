# comfylens

A local, read-only web app that indexes a directory of ComfyUI output images and reports the generation settings they used.

## Quick start

```sh
make LIBRARY=/path/to/comfyui/output       # install and build what is stale, then serve and open the browser
make dev LIBRARY=/path/to/comfyui/output   # API plus Vite with hot reload on :5173; Ctrl-C stops both
make check                                 # ruff, pyright, ESLint, Prettier, pytest, Vitest
make help                                  # every target and variable (LIBRARY, PORT, HOST, WATCH, ...)
```

## Setup

Requires [uv](https://docs.astral.sh/uv/) with Python 3.14, and Node.js 24 for the frontend. `make` runs these steps for you.

```sh
uv sync
npm --prefix frontend ci
npm --prefix frontend run build   # writes the UI to src/comfylens/web/
```

Checks:

```sh
uv run pytest
uv run ruff check . && uv run pyright
npm --prefix frontend test && npm --prefix frontend run lint
```

Frontend development: run `uv run comfylens serve DIR --no-open` and `npm --prefix frontend run dev` side by side. Vite proxies `/api` and `/thumbs` to `127.0.0.1:8765`.

## Usage

```sh
uv run comfylens serve DIR              # web UI at http://localhost:8765/
uv run comfylens index DIR              # incremental; --full re-reads, --reextract re-extracts
uv run comfylens report DIR             # add --json, or --family qwen-image-2.1
uv run comfylens inspect IMAGE.png      # one file, no catalog; add --json
```

- **`serve`:** starts the web UI on 127.0.0.1. It serves the existing catalog at once, indexes in the background and opens a browser. Use `--no-index`, `--no-open`, `--port` and `--host` to change that. A non-loopback `--host` prints a warning, because there is no authentication. With `--watch`, new images are indexed as ComfyUI writes them; `make` turns this on by default.
- **`index`:** scans the library and reads new or changed files once in a process pool. It writes the catalog and WebP thumbnails, and flags bulk-copied timestamps. It never writes inside the library.
- **`report`:** shows the parse success rate, families, reachable node classes with no handler, warnings and suspect timestamp clusters. It also prints per-family statistics, LoRAs and top configurations, plus index timing.
- **`inspect`:** shows everything extraction finds in one file.

In the UI:

- **Compare:** select exactly two images and click Compare to see their settings, LoRA chains and a word-level prompt diff side by side.
- **Distinctive terms:** with a selection, the Prompts tab shows the words and phrases that set the selection apart from the rest of the filtered images.
- **Families:** images are grouped by model family using the `[[families]]` rules in the config. The defaults cover Qwen Image, Krea 2 (local `krea-2` and hosted `krea-2-api`), FLUX and Ideogram.

State lives outside the library:

| What | Where |
| --- | --- |
| Catalog | `$XDG_DATA_HOME/comfylens/<library-id>/catalog.sqlite` |
| Thumbnails | `$XDG_CACHE_HOME/comfylens/thumbs/` |
| Config | `$XDG_CONFIG_HOME/comfylens/config.toml` |

Deleting the catalog or the thumbnail directory is always safe; the next `index` rebuilds it.

## Configuration

Optional: `$XDG_CONFIG_HOME/comfylens/config.toml`, which defaults to `~/.config/comfylens/config.toml`. Keys are merged over `src/comfylens/data/default_config.toml`, and every valid key appears there.

## Synthetic library

```sh
make synthetic N=100000 SYNTHETIC=/tmp/comfylens-synthetic
```

This writes small PNGs with varied graphs, families, LoRA stacks, batches and mtimes, for performance testing.

## Testing with your own files

Copy images into `tests/fixtures/private/`, which is gitignored. `tests/test_private.py` runs each one through `inspect` and expects status `ok`. Nothing is ever written to that folder.

The golden test (`tests/test_golden.py`) compares against `tests/fixtures/golden/sample_qwen21.expected.json`. After an intended extraction change, regenerate that file with `COMFYLENS_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py`, then review the diff.
