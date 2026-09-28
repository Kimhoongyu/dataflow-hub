from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine
from app.auth import router as auth_router
from app.projects import router as projects_router

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="DataFlow Hub API", version="0.2.0", lifespan=lifespan)
allowed_origins = {value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8000").split(",") if value.strip()}


@app.middleware("http")
async def protect_browser_requests(request, call_next):
    # Fail closed, including login/logout, to prevent cross-site cookie writes.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router)
app.include_router(projects_router)


@app.get("/api/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/api/health/ready")
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Do not expose connection strings or credentials in responses/logs.
        logger.warning("database_healthcheck_failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "unavailable"},
        )
    return {"status": "ok", "database": "ok"}
