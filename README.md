# comfylens

A local web app that indexes ComfyUI output images and shows the generation settings they used. It writes inside the library only when you ask it to from the UI: renaming, tagging or trashing images, or Fix, which removes LoRAs that cannot affect an image from its embedded prompt and workflow (PNG only, in place).

## Quick Start

Requires `make`, [uv](https://docs.astral.sh/uv/) (it fetches Python 3.14 if needed), Node.js 24 and [pnpm](https://pnpm.io/) 11 (both available through Corepack).

```sh
cp .comfylensrc.example ~/.comfylensrc   # once: set scan.directory to your output
make
```

`make` scans the directory named by `~/.comfylensrc`; `make LIBRARY=/path/to/comfyui/output` overrides it. Either way, it installs dependencies, builds the UI, indexes in the background, watches for new images and opens http://localhost:8765/. If port 8765 is taken, the next free port is used. `make help` lists the targets and variables (`LIBRARY`, `PORT`, `HOST`, `WATCH`, `DOCKER_PORT`).

```sh
uv run comfylens serve DIR              # --port, --host, --watch, --no-index, --no-open
uv run comfylens index DIR              # --full re-reads, --reextract re-extracts
uv run comfylens report DIR             # --json, --family NAME
uv run comfylens inspect IMAGE.png      # one file, no catalog; --json
uv run comfylens collection export DIR  # back up saved prompts to a zip
uv run comfylens collection import FILE.zip
```

`serve`, `index` and `report` also run with no directory at all, using `~/.comfylensrc`.

There is no authentication. A non-loopback `--host` lets anyone who can reach the port rename, tag, fix and trash your images.

## Docker

Docker Compose builds and runs comfylens against the same `~/.comfylensrc` scan directory:

```sh
make docker          # build, start and serve in the background
make docker-logs     # follow the logs
make docker-down     # stop it (data, cache and configuration are kept)
```

The container publishes on `127.0.0.1:80` and is reachable at http://comfylens.local/. A
small sidecar container advertises that name over mDNS through the host's Avahi daemon, so
no `/etc/hosts` edit is needed; if the name does not resolve, add `127.0.0.1
comfylens.local` to `/etc/hosts` yourself. `DOCKER_PORT=8080 make docker` publishes
elsewhere (use http://comfylens.local:8080/ then), `LIBRARY=DIR make docker` ignores the
rc file, and `make docker-build` builds without starting.

The catalog, thumbnails and saved prompts stay in `~/.local/share/comfylens`,
`~/.cache/comfylens` and `~/.config/comfylens` on the host, and the container runs as your
user, so files it writes into the library stay yours. The library is mounted at the same
path inside the container, so the UI names the directory you actually scan, and the host
CLI and the container share one catalog.

### What gets created

| Path | Contents |
| --- | --- |
| `~/.comfylensrc` | Optional: the scan directory used when none is on the command line |
| `~/.local/share/comfylens/` | One catalog per library, and the saved-prompt collection |
| `~/.cache/comfylens/` | Thumbnails |
| `~/.config/comfylens/config.toml` | Optional config, only if you create it; defaults in `src/comfylens/data/default_config.toml` |
| `.venv/`, `frontend/node_modules/`, `src/comfylens/web/`, `.cache/` | Dependencies, the built UI and tool caches, inside the clone |
| `/tmp/comfylens-synthetic/` | Only from `make synthetic` |

`$XDG_DATA_HOME`, `$XDG_CACHE_HOME` and `$XDG_CONFIG_HOME` replace the `~/.local/share`, `~/.cache` and `~/.config` prefixes when set. Images you trash go to the system trash.

To uninstall, delete the clone, `~/.comfylensrc` and the three `comfylens` paths in your home directory. Export the collection first: catalogs and thumbnails can be rebuilt, the collection cannot. uv and pnpm also keep download caches (`~/.cache/uv`, `~/.local/share/uv/python`, pnpm's store under `~/.local/share/pnpm`, and Corepack's under `~/.cache/node/corepack`), which other projects share.

## Development

```sh
make dev               # API and Vite with hot reload, each on a free port; Ctrl-C stops both
make check             # ruff, pyright, ESLint, Prettier, pytest, Vitest
make synthetic N=1000  # synthetic library in /tmp/comfylens-synthetic, for performance testing
make clean             # remove the built UI and .cache/
```

- `frontend/src/api/types.ts` mirrors `src/comfylens/api/schemas.py`. Keep them in sync.
- Images copied into `tests/fixtures/private/` (gitignored) are run through `inspect` by `tests/test_private.py`, which expects status `ok`.
- After an intended extraction change, regenerate the golden file with `COMFYLENS_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` and review the diff.

## License

MIT
