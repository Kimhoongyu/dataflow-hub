from contextlib import asynccontextmanager
import logging
import os
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine
from app.auth import router as auth_router
from app.jobs import MAX_REQUEST_BYTES, router as jobs_router
from app.monitoring import router as monitoring_router
from app.observability import HTTP_DURATION, HTTP_REQUESTS, request_id_var, setup_logging
from app.projects import router as projects_router
from app.storage import StorageUnavailable, get_storage

setup_logging("api")
logger = logging.getLogger("api")
# Probes and scrapes would drown the access log; they are still counted in metrics.
QUIET_PATHS = {"/api/health/live", "/api/health/ready", "/metrics"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="DataFlow Hub API", version="0.5.0", lifespan=lifespan)
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
allowed_origins = {value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8000").split(",") if value.strip()}


def guard(request) -> JSONResponse | None:
    # Fail closed, including login/logout, to prevent cross-site cookie writes.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
        # Reject oversized bodies before multipart parsing spools them to disk.
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": "요청 크기가 허용 한도를 넘었습니다."})
    return None


@app.middleware("http")
async def request_context(request, call_next):
    # Correlates the upload request with job rows and worker logs.
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if REQUEST_ID.fullmatch(incoming) else uuid4().hex
    token = request_id_var.set(request.state.request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = guard(request) or await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        elapsed = time.perf_counter() - started
        # Route template (e.g. /api/tenants/{tenant_id}/jobs), never the raw path with IDs in it.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
        HTTP_DURATION.labels(request.method, route).observe(elapsed)
        if request.url.path not in QUIET_PATHS:
            logger.info("http_request", extra={"method": request.method, "route": route, "status": status,
                                               "duration_ms": round(elapsed * 1000, 1)})
        request_id_var.reset(token)


app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(jobs_router)
app.include_router(monitoring_router)


@app.get("/metrics", include_in_schema=False)
def metrics():
    # Scraped inside the cluster only; the ingress exposes /api, not /metrics.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
