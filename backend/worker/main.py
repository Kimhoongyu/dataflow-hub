"""Job worker: claims queued jobs from PostgreSQL, processes the CSV and records the outcome.

Run with `python -m worker.main`. Several workers can run at once: FOR UPDATE SKIP LOCKED makes
each queued job go to exactly one of them. No DB lock is held while a file is processed; the
`processing` status plus the worker's heartbeat act as the lease, and the outcome is only
written if this worker still owns the job.
"""
from datetime import timedelta
import logging
import os
import signal
import socket
import threading
import time
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, lazyload

from app.db import engine
from app.models import Job, JobEvent, WorkerHeartbeat
from app.storage import ObjectNotFound, ObjectStorage, StorageUnavailable, get_storage
from worker.processors import PROCESSORS, DataError

logger = logging.getLogger("worker")
POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "2"))
HEARTBEAT_SECONDS = float(os.getenv("WORKER_HEARTBEAT_SECONDS", "10"))
STALE_SECONDS = int(os.getenv("WORKER_STALE_SECONDS", "60"))
MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))
RETRY_BASE_SECONDS = int(os.getenv("WORKER_RETRY_BASE_SECONDS", "10"))
_KEEP = object()


def add_event(db: Session, job: Job, from_status: str, to_status: str, message: str) -> None:
    db.add(JobEvent(job_id=job.id, tenant_id=job.tenant_id, from_status=from_status,
                    to_status=to_status, message=message[:1000]))


def locked_jobs():
    # Lock only the jobs rows; the eager joins to files/projects are not needed here.
    return select(Job).options(lazyload("*"))


def touch(db: Session, worker_id: str, current_job_id=_KEEP, processed: bool = False) -> None:
    values = {"last_seen_at": func.now()}
    if current_job_id is not _KEEP:
        values["current_job_id"] = current_job_id
    if processed:
        values["processed_count"] = WorkerHeartbeat.processed_count + 1
    statement = insert(WorkerHeartbeat).values(
        worker_id=worker_id, current_job_id=None if current_job_id is _KEEP else current_job_id,
        processed_count=1 if processed else 0)
    db.execute(statement.on_conflict_do_update(index_elements=[WorkerHeartbeat.worker_id], set_=values))


def claim_next(db: Session, worker_id: str) -> Job | None:
    """Marks the oldest runnable queued job as processing. The caller commits."""
    job = db.scalar(locked_jobs()
                    .where(Job.status == "queued", or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= func.now()))
                    .order_by(Job.created_at, Job.id).limit(1).with_for_update(skip_locked=True))
    if job is None:
        return None
    job.status, job.worker_id, job.attempt = "processing", worker_id, job.attempt + 1
    job.started_at, job.next_attempt_at, job.finished_at, job.duration_ms = func.now(), None, None, None
    add_event(db, job, "queued", "processing", f"Worker {worker_id} 처리 시작 ({job.attempt}회차)")
    touch(db, worker_id, current_job_id=job.id)
    return job


def process_job(db: Session, storage: ObjectStorage, job_id: UUID, worker_id: str) -> None:
    job = db.get(Job, job_id)
    source, job_type = job.file.blob_name, job.job_type
    result_blob = f"{job.tenant_id}/{job.project_id}/results/{job.id}.csv"
    # End the read transaction: nothing is locked while the file is processed.
    db.commit()
    started = time.monotonic()
    result, error, retryable = None, None, False
    try:
        result = PROCESSORS[job_type](storage.download(source))
        storage.upload(result_blob, result.output, overwrite=True)
    except DataError as data_error:
        error = (data_error.code, data_error.message)
    except ObjectNotFound:
        error = ("FILE_MISSING", "원본 파일을 저장소에서 찾을 수 없습니다.")
    except StorageUnavailable:
        error, retryable = ("STORAGE_ERROR", "파일 저장소에 연결할 수 없습니다."), True
    except Exception:
        logger.exception("job_crashed job_id=%s worker_id=%s", job_id, worker_id)
        error, retryable = ("INTERNAL", "처리 중 예기치 못한 오류가 발생했습니다."), True
    finish(db, job_id, worker_id, int((time.monotonic() - started) * 1000), result, result_blob, error, retryable)


def finish(db: Session, job_id: UUID, worker_id: str, duration_ms: int, result, result_blob: str,
           error: tuple[str, str] | None, retryable: bool) -> None:
    job = db.scalar(locked_jobs().where(Job.id == job_id, Job.status == "processing", Job.worker_id == worker_id)
                    .with_for_update())
    if job is None:
        # Recovered by another worker while we were busy; its outcome wins.
        db.rollback()
        logger.warning("job_ownership_lost job_id=%s worker_id=%s", job_id, worker_id)
        return
    job.duration_ms = duration_ms
    if error is None:
        job.status, job.finished_at, job.result_blob_name = "completed", func.now(), result_blob
        job.rows_in, job.rows_out, job.error_row_count = result.rows_in, result.rows_out, result.error_rows
        job.error_code = job.error_message = None
        add_event(db, job, "processing", "completed", f"처리 완료: {result.summary}")
    else:
        job.error_code, job.error_message = error
        if retryable and job.attempt < MAX_ATTEMPTS:
            delay = RETRY_BASE_SECONDS * 2 ** (job.attempt - 1)
            job.status, job.next_attempt_at = "queued", func.now() + timedelta(seconds=delay)
            add_event(db, job, "processing", "queued", f"{error[1]} {delay}초 후 재시도 ({job.attempt}/{MAX_ATTEMPTS})")
        else:
            job.status, job.finished_at = "failed", func.now()
            suffix = f" (최대 {MAX_ATTEMPTS}회 시도 초과)" if retryable else ""
            add_event(db, job, "processing", "failed", f"처리 실패 [{error[0]}]: {error[1]}{suffix}")
    touch(db, worker_id, current_job_id=None, processed=True)
    status = job.status
    db.commit()
    logger.info("job_finished job_id=%s worker_id=%s status=%s error_code=%s duration_ms=%s",
                job_id, worker_id, status, error[0] if error else None, duration_ms)


def recover_stale(db: Session) -> int:
    """Re-queues processing jobs whose worker stopped sending heartbeats. The caller commits."""
    cutoff = func.now() - timedelta(seconds=STALE_SECONDS)
    alive = select(WorkerHeartbeat.worker_id).where(WorkerHeartbeat.last_seen_at >= cutoff)
    jobs = db.scalars(locked_jobs().where(Job.status == "processing", or_(Job.worker_id.is_(None), Job.worker_id.not_in(alive)))
                      .with_for_update(skip_locked=True)).all()
    for job in jobs:
        lost = f"Worker {job.worker_id} 응답 없음"
        if job.attempt < MAX_ATTEMPTS:
            job.status, job.next_attempt_at = "queued", None
            add_event(db, job, "processing", "queued", f"{lost}, 다시 대기열에 등록")
        else:
            job.status, job.finished_at = "failed", func.now()
            job.error_code, job.error_message = "WORKER_LOST", f"{lost}, 최대 {MAX_ATTEMPTS}회 시도 초과"
            add_event(db, job, "processing", "failed", f"처리 실패 [WORKER_LOST]: {job.error_message}")
        logger.warning("job_recovered job_id=%s dead_worker=%s status=%s", job.id, job.worker_id, job.status)
    db.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at < func.now() - timedelta(days=1)))
    return len(jobs)


def run_once(db: Session, storage: ObjectStorage, worker_id: str) -> bool:
    job = claim_next(db, worker_id)
    if job is None:
        db.commit()
        return False
    job_id = job.id
    db.commit()
    logger.info("job_claimed job_id=%s worker_id=%s", job_id, worker_id)
    process_job(db, storage, job_id, worker_id)
    return True


def heartbeat_loop(worker_id: str, stop: threading.Event) -> None:
    # Separate thread so a long-running job does not look like a dead worker.
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            with Session(engine) as db:
                touch(db, worker_id)
                db.commit()
        except SQLAlchemyError:
            logger.warning("heartbeat_failed worker_id=%s", worker_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Keep SDK chatter (e.g. credential lookups) out of the job log.
    logging.getLogger("botocore").setLevel(logging.WARNING)
    worker_id = os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    storage = get_storage()
    with Session(engine) as db:
        touch(db, worker_id)
        db.commit()
    threading.Thread(target=heartbeat_loop, args=(worker_id, stop), daemon=True).start()
    logger.info("worker_started worker_id=%s max_attempts=%s stale_seconds=%s", worker_id, MAX_ATTEMPTS, STALE_SECONDS)
    last_recovery = 0.0
    while not stop.is_set():
        worked = False
        try:
            with Session(engine) as db:
                if time.monotonic() - last_recovery >= HEARTBEAT_SECONDS:
                    recover_stale(db)
                    db.commit()
                    last_recovery = time.monotonic()
                worked = run_once(db, storage, worker_id)
        except SQLAlchemyError:
            logger.exception("worker_db_error worker_id=%s", worker_id)
        if not worked:
            stop.wait(POLL_SECONDS)
    # Graceful stop (SIGTERM from docker/Kubernetes): the current job has finished by now.
    with Session(engine) as db:
        db.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))
        db.commit()
    logger.info("worker_stopped worker_id=%s", worker_id)


if __name__ == "__main__":
    main()
