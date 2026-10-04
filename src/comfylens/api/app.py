"""The FastAPI application: JSON API, thumbnails and the built frontend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from comfylens.api import routes_images, routes_index, routes_library, routes_prompts, routes_stats
from comfylens.api.server import ApiError, Server, error_response
from comfylens.config import Config
from comfylens.index.watch import DEBOUNCE_MS

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Only these Host headers are served: without the check, a malicious page could reach the
# loopback server through DNS rebinding. "testserver" is Starlette's TestClient default.
ALLOWED_HOSTS = ("localhost", "127.0.0.1", "testserver")


def create_app(
    root: Path,
    config: Config,
    *,
    index_on_start: bool = True,
    watch: bool = False,
    watch_debounce_ms: int = DEBOUNCE_MS,
    web_dir: Path | None = WEB_DIR,
) -> FastAPI:
    server = Server(root, config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Serve from the existing catalog first; the incremental index then refreshes it.
        server.store.rebuild()
        if index_on_start:
            server.start_index()
        if watch:
            server.watch(watch_debounce_ms)
        yield
        server.stop_watching()

    # Responses go straight through Pydantic, which writes NaN (ComfyUI can emit it) as null.
    app = FastAPI(title="comfylens", lifespan=lifespan, docs_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS))
    app.state.server = server

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, e: ApiError) -> JSONResponse:
        return error_response(e.status, e.code, e.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, e: StarletteHTTPException) -> JSONResponse:
        # A wrong method on a known path is served as an unknown endpoint (404), not 405.
        status = 404 if e.status_code == 405 else e.status_code
        code = {404: "not_found"}.get(status, "http_error")
        return error_response(status, code, str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, e: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        return error_response(400, "invalid_request", problems)

    @app.exception_handler(Exception)
    async def _internal(_request: Request, e: Exception) -> JSONResponse:
        return error_response(500, "internal", f"{type(e).__name__}: {e}")

    for module in (routes_library, routes_index, routes_images, routes_stats, routes_prompts):
        app.include_router(module.router)
    app.include_router(routes_images.thumbs_router)

    _mount_frontend(app, web_dir)
    return app


def _mount_frontend(app: FastAPI, web_dir: Path | None) -> None:
    """Serve the built single-page app, falling back to index.html for client routes."""
    index = web_dir / "index.html" if web_dir else None

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def frontend(path: str) -> FileResponse | HTMLResponse | JSONResponse:
        if path.startswith(("api/", "thumbs/")) or path in ("api", "thumbs"):
            return error_response(404, "not_found", "no such endpoint")
        if web_dir is None or index is None or not index.is_file():
            return HTMLResponse(
                "<h1>comfylens</h1><p>The frontend is not built. Run "
                "<code>npm --prefix frontend install && npm --prefix frontend run build</code>.</p>"
            )
        candidate = (web_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(web_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
