# comfylens

A local web app that indexes ComfyUI output images and shows the generation settings they used. It writes inside the library only when you rename or trash an image from the UI.

## Quick Start

Requires `make`, [uv](https://docs.astral.sh/uv/) (it fetches Python 3.14 if needed) and Node.js 24.

```sh
make LIBRARY=/path/to/comfyui/output
```

This installs dependencies, builds the UI, indexes in the background, watches for new images and opens http://localhost:8765/. If port 8765 is taken, the next free port is used. `make help` lists the targets and variables (`LIBRARY`, `PORT`, `HOST`, `WATCH`).

```sh
uv run comfylens serve DIR              # --port, --host, --watch, --no-index, --no-open
uv run comfylens index DIR              # --full re-reads, --reextract re-extracts
uv run comfylens report DIR             # --json, --family NAME
uv run comfylens inspect IMAGE.png      # one file, no catalog; --json
uv run comfylens collection export DIR  # back up saved prompts to a zip
uv run comfylens collection import FILE.zip
```

There is no authentication. A non-loopback `--host` lets anyone who can reach the port rename and trash your images.

### What gets created

| Path | Contents |
| --- | --- |
| `~/.local/share/comfylens/` | One catalog per library, and the saved-prompt collection |
| `~/.cache/comfylens/` | Thumbnails |
| `~/.config/comfylens/config.toml` | Optional config, only if you create it; defaults in `src/comfylens/data/default_config.toml` |
| `.venv/`, `frontend/node_modules/`, `src/comfylens/web/`, `.cache/` | Dependencies, the built UI and tool caches, inside the clone |
| `/tmp/comfylens-synthetic/` | Only from `make synthetic` |

`$XDG_DATA_HOME`, `$XDG_CACHE_HOME` and `$XDG_CONFIG_HOME` replace the `~/.local/share`, `~/.cache` and `~/.config` prefixes when set. Images you trash go to the system trash.

To uninstall, delete the clone and the three `comfylens` paths in your home directory. Export the collection first: catalogs and thumbnails can be rebuilt, the collection cannot. uv and npm also keep download caches (`~/.cache/uv`, `~/.local/share/uv/python`, `~/.npm`), which other projects share.

## Development

```sh
make dev LIBRARY=DIR   # API and Vite with hot reload, each on a free port; Ctrl-C stops both
make check             # ruff, pyright, ESLint, Prettier, pytest, Vitest
make synthetic N=1000  # synthetic library in /tmp/comfylens-synthetic, for performance testing
make clean             # remove the built UI and .cache/
```

- `frontend/src/api/types.ts` mirrors `src/comfylens/api/schemas.py`. Keep them in sync.
- Images copied into `tests/fixtures/private/` (gitignored) are run through `inspect` by `tests/test_private.py`, which expects status `ok`.
- After an intended extraction change, regenerate the golden file with `COMFYLENS_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` and review the diff.

## License

MIT
