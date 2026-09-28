"""Operations dashboard: tenant-scoped aggregates computed straight from the jobs tables.

Period metrics count uploads by upload time and outcomes by finish time. Queue numbers are
current values. Worker counts are platform-wide and expose no tenant data.
"""
from datetime import datetime, timedelta
import os
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobEvent, Project, UploadedFile, WorkerHeartbeat
from app.projects import authorized_tenant

router = APIRouter(prefix="/api/tenants/{tenant_id}/monitoring", tags=["monitoring"])
Period = Literal["24h", "7d", "30d"]
PERIODS = {"24h": (timedelta(hours=24), "hour"), "7d": (timedelta(days=7), "day"), "30d": (timedelta(days=30), "day")}
TIMEZONE = os.getenv("DASHBOARD_TIMEZONE", "Asia/Seoul")
# Same setting the worker uses to decide that a worker is gone.
STALE_SECONDS = int(os.getenv("WORKER_STALE_SECONDS", "60"))
RECENT_ERRORS = 10


class Summary(BaseModel):
    uploads: int
    completed: int
    failed: int
    success_rate: float | None
    avg_duration_ms: float | None
    p95_duration_ms: float | None
    retries: int


class Queue(BaseModel):
    queued: int
    processing: int
    oldest_queued_seconds: float | None
    stuck: int
    workers_alive: int
    workers_stale: int


class ProjectStats(BaseModel):
    id: UUID
    name: str
    uploads: int
    completed: int
    failed: int
    success_rate: float | None
    active: int
    last_finished_at: datetime | None


class Bucket(BaseModel):
    start: str  # local time in `timezone`, without offset
    completed: int
    failed: int


class RecentError(BaseModel):
    job_id: UUID
    project_name: str
    file_name: str
    status: str
    error_code: str
    error_message: str | None
    attempt: int
    occurred_at: datetime | None


class ErrorCount(BaseModel):
    error_code: str
    count: int


class Overview(BaseModel):
    period: Period
    since: datetime
    generated_at: datetime
    timezone: str
    bucket: Literal["hour", "day"]
    summary: Summary
    queue: Queue
    projects: list[ProjectStats]
    timeseries: list[Bucket]
    error_codes: list[ErrorCount]
    recent_errors: list[RecentError]


def rate(completed: int, failed: int) -> float | None:
    return round(completed / (completed + failed), 4) if completed + failed else None


TIMESERIES = text("""
WITH buckets AS (
    SELECT generate_series(date_trunc(:unit, timezone(:tz, :since)), date_trunc(:unit, timezone(:tz, :now)),
                           CAST(:step AS interval)) AS bucket
), counts AS (
    SELECT date_trunc(:unit, timezone(:tz, finished_at)) AS bucket,
           count(*) FILTER (WHERE status = 'completed') AS completed,
           count(*) FILTER (WHERE status = 'failed') AS failed
    FROM jobs
    WHERE tenant_id = :tenant_id AND finished_at >= :since AND status IN ('completed', 'failed')
    GROUP BY 1
)
SELECT b.bucket, coalesce(c.completed, 0), coalesce(c.failed, 0)
FROM buckets b LEFT JOIN counts c USING (bucket)
ORDER BY b.bucket
""")


@router.get("", response_model=Overview)
def overview(period: Period = "24h", tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db)):
    window, unit = PERIODS[period]
    now = db.scalar(select(func.now()))
    since = now - window
    own = Job.tenant_id == tenant_id
    finished = and_(own, Job.finished_at >= since, Job.status.in_(("completed", "failed")))
    is_completed, is_failed = Job.status == "completed", Job.status == "failed"

    uploads = db.scalar(select(func.count()).select_from(UploadedFile)
                        .where(UploadedFile.tenant_id == tenant_id, UploadedFile.created_at >= since))
    completed, failed, avg_ms, p95_ms = db.execute(select(
        func.count().filter(is_completed), func.count().filter(is_failed),
        func.avg(Job.duration_ms).filter(is_completed),
        func.percentile_cont(0.95).within_group(Job.duration_ms).filter(is_completed),
    ).where(finished)).one()
    retries = db.scalar(select(func.count()).select_from(JobEvent).where(
        JobEvent.tenant_id == tenant_id, JobEvent.from_status == "processing", JobEvent.to_status == "queued",
        JobEvent.created_at >= since))

    alive_cutoff = now - timedelta(seconds=STALE_SECONDS)
    alive_workers = select(WorkerHeartbeat.worker_id).where(WorkerHeartbeat.last_seen_at >= alive_cutoff)
    queued, processing, oldest, stuck = db.execute(select(
        func.count().filter(Job.status == "queued"), func.count().filter(Job.status == "processing"),
        func.min(Job.created_at).filter(Job.status == "queued"),
        func.count().filter(Job.status == "processing", or_(Job.worker_id.is_(None), Job.worker_id.not_in(alive_workers))),
    ).where(own, Job.status.in_(("queued", "processing")))).one()
    workers_alive, workers_stale = db.execute(select(
        func.count().filter(WorkerHeartbeat.last_seen_at >= alive_cutoff),
        func.count().filter(WorkerHeartbeat.last_seen_at < alive_cutoff))).one()

    job_stats = (select(Job.project_id,
                        func.count().filter(finished, is_completed).label("completed"),
                        func.count().filter(finished, is_failed).label("failed"),
                        func.count().filter(Job.status.in_(("queued", "processing"))).label("active"),
                        func.max(Job.finished_at).label("last_finished_at"))
                 .where(own).group_by(Job.project_id).subquery())
    upload_stats = (select(UploadedFile.project_id, func.count().label("uploads"))
                    .where(UploadedFile.tenant_id == tenant_id, UploadedFile.created_at >= since)
                    .group_by(UploadedFile.project_id).subquery())
    uploads_col = func.coalesce(upload_stats.c.uploads, 0)
    project_rows = db.execute(
        select(Project.id, Project.name, uploads_col, func.coalesce(job_stats.c.completed, 0),
               func.coalesce(job_stats.c.failed, 0), func.coalesce(job_stats.c.active, 0), job_stats.c.last_finished_at)
        .outerjoin(job_stats, job_stats.c.project_id == Project.id)
        .outerjoin(upload_stats, upload_stats.c.project_id == Project.id)
        .where(Project.tenant_id == tenant_id)
        .order_by(uploads_col.desc(), Project.name).limit(50)).all()

    buckets = db.execute(TIMESERIES, {"unit": unit, "step": f"1 {unit}", "tz": TIMEZONE, "since": since,
                                      "now": now, "tenant_id": tenant_id}).all()

    error_codes = db.execute(select(Job.error_code, func.count()).where(finished, is_failed)
                             .group_by(Job.error_code).order_by(func.count().desc(), Job.error_code)).all()
    occurred = func.coalesce(Job.finished_at, Job.started_at)
    recent = db.execute(select(Job.id, Project.name, UploadedFile.original_name, Job.status, Job.error_code,
                               Job.error_message, Job.attempt, occurred)
                        .join(Project, Project.id == Job.project_id).join(UploadedFile, UploadedFile.id == Job.file_id)
                        # Failed jobs plus jobs waiting to retry after an error.
                        .where(own, Job.error_code.is_not(None), Job.status.in_(("failed", "queued")), occurred >= since)
                        .order_by(occurred.desc(), Job.id).limit(RECENT_ERRORS)).all()

    return Overview(
        period=period, since=since, generated_at=now, timezone=TIMEZONE, bucket=unit,
        summary=Summary(uploads=uploads, completed=completed, failed=failed, success_rate=rate(completed, failed),
                        avg_duration_ms=round(avg_ms, 1) if avg_ms is not None else None,
                        p95_duration_ms=round(p95_ms, 1) if p95_ms is not None else None, retries=retries),
        queue=Queue(queued=queued, processing=processing,
                    oldest_queued_seconds=round((now - oldest).total_seconds(), 1) if oldest else None,
                    stuck=stuck, workers_alive=workers_alive, workers_stale=workers_stale),
        projects=[ProjectStats(id=r[0], name=r[1], uploads=r[2], completed=r[3], failed=r[4], success_rate=rate(r[3], r[4]),
                               active=r[5], last_finished_at=r[6]) for r in project_rows],
        timeseries=[Bucket(start=b[0].isoformat(), completed=b[1], failed=b[2]) for b in buckets],
        error_codes=[ErrorCount(error_code=code, count=count) for code, count in error_codes],
        recent_errors=[RecentError(job_id=r[0], project_name=r[1], file_name=r[2], status=r[3], error_code=r[4],
                                   error_message=r[5], attempt=r[6], occurred_at=r[7]) for r in recent],
    )
