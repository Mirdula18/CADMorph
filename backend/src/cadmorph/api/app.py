"""FastAPI application factory.

No CORS middleware is registered: same-origin only by default (FR-016).
All error responses use the contract's error envelope (contracts/api.md).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from cadmorph.api.routes import max_upload_bytes, router
from cadmorph.observability import configure_logging
from cadmorph.pipeline import JobStore, cleanup_loop


def error_envelope(code: str, message: str, comparison_id: str | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if comparison_id is not None:
        error["comparison_id"] = comparison_id
    return {"error": error}


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # TTL cleanup job (T045): sweep on startup, then hourly by default
        interval = float(os.environ.get("CADMORPH_CLEANUP_INTERVAL_S", "3600"))
        sweeper = asyncio.create_task(cleanup_loop(app.state.store, interval))
        try:
            yield
        finally:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper

    app = FastAPI(title="CADMorph", version="0.1.0", lifespan=lifespan)
    app.state.store = JobStore(data_dir or os.environ.get("CADMORPH_DATA_DIR", "data"))
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def upload_size_guard(request: Request, call_next):
        """Fast-fail oversized uploads on declared Content-Length before the
        body is buffered (T046). The per-file check in routes still guards
        undeclared-length bodies."""
        declared = request.headers.get("content-length", "")
        cap = 2 * max_upload_bytes() + 1_048_576  # two files + form overhead
        if request.method == "POST" and declared.isdigit() and int(declared) > cap:
            return JSONResponse(
                status_code=413,
                content=error_envelope(
                    "file_too_large",
                    f"request body exceeds {cap // 1_048_576} MiB "
                    f"(per-file limit {max_upload_bytes() // 1_048_576} MiB)",
                ),
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = str(exc.errors()[:1])
        return JSONResponse(status_code=400, content=error_envelope("missing_file", detail))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Route/method misses etc. must use the contract envelope too
        (contracts/api.md: error envelope on ALL non-2xx)."""
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code, content=error_envelope(code, str(exc.detail))
        )

    @app.exception_handler(Exception)
    async def internal_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content=error_envelope("internal", "internal error"))

    return app


app = create_app()
