from contextlib import asynccontextmanager
import logging
import os
import re
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine
from app.auth import router as auth_router
from app.jobs import MAX_REQUEST_BYTES, router as jobs_router
from app.monitoring import router as monitoring_router
from app.projects import router as projects_router
from app.storage import StorageUnavailable, get_storage

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="DataFlow Hub API", version="0.5.0", lifespan=lifespan)
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
allowed_origins = {value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8000").split(",") if value.strip()}


@app.middleware("http")
async def protect_browser_requests(request, call_next):
    # Correlates the upload request with job rows and, later, worker logs.
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if REQUEST_ID.fullmatch(incoming) else uuid4().hex
    # Fail closed, including login/logout, to prevent cross-site cookie writes.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
        # Reject oversized bodies before multipart parsing spools them to disk.
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": "요청 크기가 허용 한도를 넘었습니다."})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(jobs_router)
app.include_router(monitoring_router)


@app.get("/api/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/api/health/ready")
def readiness():
    checks = {"database": "ok", "storage": "ok"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Do not expose connection strings or credentials in responses/logs.
        logger.warning("database_healthcheck_failed")
        checks["database"] = "unavailable"
    try:
        get_storage().check()
    except StorageUnavailable:
        logger.warning("storage_healthcheck_failed")
        checks["storage"] = "unavailable"
    if "unavailable" in checks.values():
        return JSONResponse(status_code=503, content={"status": "unavailable", **checks})
    return {"status": "ok", **checks}
