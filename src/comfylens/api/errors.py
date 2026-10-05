"""The JSON error envelope every endpoint uses."""

from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}, **extra}, status_code=status)


def not_found(what: str, raw_id: object) -> ApiError:
    return ApiError(404, "not_found", f"no {what} with id {raw_id!r}")


def parse_id(raw_id: str, what: str) -> int:
    """Ids are parsed here rather than by FastAPI: anything malformed is a plain 404."""
    if not raw_id.isdigit():
        raise not_found(what, raw_id)
    return int(raw_id)


def no_catalog() -> ApiError:
    return ApiError(503, "no_catalog", "the library has not been indexed yet")
