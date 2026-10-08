"""Build and run comfylens in Docker against the .comfylensrc scan directory.

    uv run python scripts/docker.py up           # build, start, serve in the background
    uv run python scripts/docker.py up DIR       # ignore .comfylensrc and scan DIR
    uv run python scripts/docker.py logs|down|build

`make docker` is the supported entry point. The containers publish comfylens.local on
the host, keep the catalog and thumbnails in the host's comfylens data and cache
directories, and run as the invoking user so files they write into the library stay
yours. The mounted library is only read while indexing; it is written to only when a
rename, tag, fix or trash is requested in the UI.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from comfylens.paths import cache_root, config_root, data_root
from comfylens.rc import RcError, rc_path, scan_directory

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ("docker", "compose", "-f", str(ROOT / "docker-compose.yml"))


def _library(given: str | None) -> Path | None:
    """The scan directory from the argument or .comfylensrc; None when neither is set."""
    try:
        if given:
            path = Path(given).expanduser()
        elif rc_path().is_file():
            return scan_directory()
        else:
            return None
    except RcError as e:
        sys.exit(f"error: {e}")
    if not path.is_dir():
        sys.exit(f"error: {path} is not a directory")
    return path.resolve()


def _environment(library: Path, port: str, bind: str) -> dict[str, str]:
    """Compose variables, including the host directories the containers mount."""
    data, cache, config = data_root(), cache_root(), config_root()
    for directory in (data, cache, config, data / "home"):
        directory.mkdir(parents=True, exist_ok=True)
    return os.environ | {
        "COMFYLENS_LIBRARY": str(library),
        "COMFYLENS_PORT": port,
        "COMFYLENS_BIND": bind,
        "COMFYLENS_DATA": str(data),
        "COMFYLENS_CACHE": str(cache),
        "COMFYLENS_CONFIG": str(config),
        "COMFYLENS_UID": str(os.getuid()),
        "COMFYLENS_GID": str(os.getgid()),
    }


def _compose(action: list[str], env: dict[str, str]) -> int:
    if shutil.which("docker") is None:
        sys.exit("error: docker is not installed")
    return subprocess.call([*COMPOSE, *action], env=env)


def _url(port: str) -> str:
    return f"http://comfylens.local{'' if port == '80' else f':{port}'}/"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", nargs="?", default="up", choices=("up", "down", "logs", "build"))
    parser.add_argument("library", nargs="?", help="Directory to scan (default: .comfylensrc).")
    parser.add_argument(
        "--port", default=os.environ.get("COMFYLENS_PORT", "80"), help="Host port (default: 80)."
    )
    parser.add_argument(
        "--bind",
        default=os.environ.get("COMFYLENS_BIND", "127.0.0.1"),
        help="Host address to publish on (default: 127.0.0.1).",
    )
    parser.add_argument("--foreground", action="store_true", help="up: stay attached to the logs.")
    args = parser.parse_args()

    library = _library(args.library)
    if args.action == "up" and library is None:
        sys.exit(
            "error: no scan directory: pass LIBRARY or create ~/.comfylensrc"
            " (see .comfylensrc.example)"
        )
    # down/logs/build do not mount the library, but Compose still needs the variable.
    env = _environment(library or ROOT, args.port, args.bind)

    if args.action == "up":
        command = ["up", "--build"] + ([] if args.foreground else ["--detach"])
        code = _compose(command, env)
        if code == 0 and not args.foreground:
            print(f"comfylens is starting at {_url(args.port)}")
            print(f"scanning {library}; data in {data_root()}")
        raise SystemExit(code)

    commands = {"down": ["down"], "logs": ["logs", "--follow", "comfylens"], "build": ["build"]}
    raise SystemExit(_compose(commands[args.action], env))


if __name__ == "__main__":
    main()
