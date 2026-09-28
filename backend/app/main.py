from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="DataFlow Hub API", version="0.1.0", lifespan=lifespan)


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
