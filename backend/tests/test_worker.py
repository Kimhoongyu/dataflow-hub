import csv
from datetime import datetime, timedelta, timezone
import io
from urllib.parse import unquote

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import Job, JobEvent, Project, Tenant, UploadedFile, WorkerHeartbeat
from conftest import login, upload
from worker import main as worker
from worker.processors import DataError, aggregate, cleanse, read_csv, transform, validate

PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)


def rows(output: bytes) -> list[list[str]]:
    assert output.startswith("﻿".encode())
    return list(csv.reader(io.StringIO(output.decode("utf-8-sig"))))


def statuses(db, job_id):
    events = db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id)).all()
    return [event.to_status for event in events]


# --- processors: pure functions -------------------------------------------------------------

def test_validate_reports_row_errors():
    result = validate(b"id,name\n1,Kim\n2,\n3,Lee,extra\n")
    assert (result.rows_in, result.rows_out, result.error_rows) == (3, 1, 2)
    assert rows(result.output) == [["line", "column", "error"], ["3", "name", "빈 값"],
                                   ["4", "", "열 개수 불일치: 3개 (헤더 2개)"]]


def test_cleanse_trims_dedupes_and_drops_malformed():
    result = cleanse(b"id, name \n1, Kim \n1,Kim\n\n2,Lee\n3\n")
    assert rows(result.output) == [["id", "name"], ["1", "Kim"], ["2", "Lee"]]
    assert (result.rows_in, result.rows_out, result.error_rows) == (4, 2, 1)
    assert "중복 1행" in result.summary


def test_transform_normalizes_headers_and_numbers():
    result = transform(b"Flight No,Passenger Count,flight-no\nKE001,\"1,234\",x\nKE017,\"1,2\",y\n")
    assert rows(result.output) == [["flight_no", "passenger_count", "flight_no_2"],
                                   ["KE001", "1234", "x"], ["KE017", "1,2", "y"]]


def test_aggregate_profiles_columns():
    result = aggregate("편명,승객\nKE001,280\nKE017,\"1,000\"\nKE017,\n".encode())
    header, flight, passengers = rows(result.output)
    assert header[:5] == ["column", "non_empty", "empty", "distinct", "numeric"]
    assert flight == ["편명", "3", "0", "2", "no", "", "", "", ""]
    assert passengers == ["승객", "2", "1", "2", "yes", "280", "1000", "1280", "640"]


@pytest.mark.parametrize("data, code", [
    (b"\xff\xfe", "INVALID_CSV"),
    (b'id,name\n1,"unclosed\n', "INVALID_CSV"),
    (b"\n \n", "EMPTY_FILE"),
    (b"id,name\n", "EMPTY_FILE"),
    (b"id,id\n1,2\n", "SCHEMA_MISMATCH"),
    (b"id,\n1,2\n", "SCHEMA_MISMATCH"),
])
def test_unusable_files_raise_data_error(data, code):
    with pytest.raises(DataError) as error:
        read_csv(data)
    assert error.value.code == code


# --- worker lifecycle against the test DB ---------------------------------------------------

def test_worker_completes_job_and_result_is_downloadable(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0], "승객 명단.csv", b"id,name\n1,Kim\n2,\n", "validation").json()["id"]
    assert worker.run_once(db, storage, "w1") is True
    job = db.get(Job, job_id)
    assert (job.status, job.attempt, job.worker_id) == ("completed", 1, "w1")
    assert (job.rows_in, job.rows_out, job.error_row_count) == (2, 1, 1)
    assert job.duration_ms is not None and job.finished_at is not None
    assert statuses(db, job.id) == ["queued", "processing", "completed"]
    heartbeat = db.get(WorkerHeartbeat, "w1")
    assert (heartbeat.processed_count, heartbeat.current_job_id) == (1, None)
    assert worker.run_once(db, storage, "w1") is False

    detail = client.get(f"/api/tenants/{tenants[0].id}/jobs/{job_id}").json()
    assert detail["has_result"] is True
    result = client.get(f"/api/tenants/{tenants[0].id}/jobs/{job_id}/result")
    assert result.status_code == 200
    assert rows(result.content)[1] == ["3", "name", "빈 값"]
    assert unquote(result.headers["content-disposition"].split("''")[1]) == "승객 명단-validation-result.csv"
    login(client, "b@test.local")
    assert client.get(f"/api/tenants/{tenants[0].id}/jobs/{job_id}/result").status_code == 404


def test_data_error_fails_without_retry(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0], content=b"id,id\n1,2\n").json()["id"]
    worker.run_once(db, storage, "w1")
    job = db.get(Job, job_id)
    assert (job.status, job.error_code, job.attempt, job.next_attempt_at) == ("failed", "SCHEMA_MISMATCH", 1, None)
    assert "중복된 열 이름" in job.error_message
    assert client.get(f"/api/tenants/{tenants[0].id}/jobs/{job_id}/result").status_code == 404


def test_missing_source_file_fails_without_retry(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0]).json()["id"]
    storage.blobs.clear()
    worker.run_once(db, storage, "w1")
    assert (db.get(Job, job_id).status, db.get(Job, job_id).error_code) == ("failed", "FILE_MISSING")


def test_transient_error_retries_with_backoff_then_succeeds(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0]).json()["id"]
    storage.fail = True
    worker.run_once(db, storage, "w1")
    job = db.get(Job, job_id)
    assert (job.status, job.attempt, job.error_code) == ("queued", 1, "STORAGE_ERROR")
    assert job.next_attempt_at is not None
    # Backoff: not claimable before next_attempt_at.
    assert worker.run_once(db, storage, "w1") is False
    storage.fail = False
    job.next_attempt_at = PAST
    db.commit()
    worker.run_once(db, storage, "w1")
    job = db.get(Job, job_id)
    assert (job.status, job.attempt, job.error_code, job.error_message) == ("completed", 2, None, None)
    assert statuses(db, job.id) == ["queued", "processing", "queued", "processing", "completed"]


def test_transient_error_fails_after_max_attempts(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0]).json()["id"]
    storage.fail = True
    for _ in range(worker.MAX_ATTEMPTS):
        db.get(Job, job_id).next_attempt_at = PAST
        db.commit()
        assert worker.run_once(db, storage, "w1") is True
    job = db.get(Job, job_id)
    assert (job.status, job.attempt, job.error_code) == ("failed", worker.MAX_ATTEMPTS, "STORAGE_ERROR")
    assert "최대 3회 시도 초과" in db.scalars(select(JobEvent.message).where(JobEvent.job_id == job.id).order_by(JobEvent.id.desc())).first()


def test_stale_worker_jobs_are_recovered(env):
    client, db, tenants, projects, storage = env
    upload(client, tenants[0], projects[0], "a.csv")
    upload(client, tenants[0], projects[0], "b.csv")
    first = worker.claim_next(db, "dead").id
    second = worker.claim_next(db, "alive").id
    # Stale, but recent enough not to be pruned yet.
    db.get(WorkerHeartbeat, "dead").last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=worker.STALE_SECONDS + 30)
    db.get(Job, second).attempt = worker.MAX_ATTEMPTS  # the live worker's job must stay untouched
    db.commit()
    assert worker.recover_stale(db) == 1
    db.commit()
    job = db.get(Job, first)
    assert (job.status, job.attempt) == ("queued", 1)
    assert "Worker dead 응답 없음" in db.scalars(select(JobEvent.message).where(JobEvent.job_id == job.id).order_by(JobEvent.id.desc())).first()
    assert db.get(Job, second).status == "processing"
    assert db.get(WorkerHeartbeat, "dead") is not None  # only day-old heartbeats are pruned


def test_stale_job_at_max_attempts_fails_as_worker_lost(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0]).json()["id"]
    worker.claim_next(db, "dead")
    db.get(Job, job_id).attempt = worker.MAX_ATTEMPTS
    db.get(WorkerHeartbeat, "dead").last_seen_at = PAST
    db.commit()
    worker.recover_stale(db)
    db.commit()
    assert (db.get(Job, job_id).status, db.get(Job, job_id).error_code) == ("failed", "WORKER_LOST")


def test_worker_that_lost_ownership_does_not_overwrite(env):
    client, db, tenants, projects, storage = env
    job_id = upload(client, tenants[0], projects[0]).json()["id"]
    worker.claim_next(db, "w1")
    db.commit()
    db.get(Job, job_id).worker_id = "w2"  # recovered and re-claimed elsewhere meanwhile
    db.commit()
    worker.process_job(db, storage, job_id, "w1")
    job = db.get(Job, job_id)
    assert (job.status, job.worker_id, job.result_blob_name) == ("processing", "w2", None)


def test_skip_locked_gives_each_worker_a_different_job():
    """Uses real committed rows and two connections, so it cleans up after itself."""
    with Session(engine) as setup_db:
        tenant = Tenant(name="concurrency")
        setup_db.add(tenant)
        setup_db.flush()
        project = Project(tenant_id=tenant.id, name="p", description="")
        setup_db.add(project)
        setup_db.flush()
        for index in range(2):
            file = UploadedFile(tenant_id=tenant.id, project_id=project.id, original_name=f"{index}.csv",
                                blob_name=f"concurrency/{tenant.id}/{index}.csv", size_bytes=1, sha256="0" * 64)
            setup_db.add(file)
            setup_db.flush()
            setup_db.add(Job(tenant_id=tenant.id, project_id=project.id, file_id=file.id, job_type="validation",
                             status="queued", notes="", attempt=0, request_id="t"))
        setup_db.commit()
        tenant_id = tenant.id
    try:
        with Session(engine) as a, Session(engine) as b:
            first = worker.claim_next(a, "worker-a")   # holds its row lock, uncommitted
            second = worker.claim_next(b, "worker-b")  # must skip that row instead of waiting
            third = worker.claim_next(b, "worker-b")
            assert first is not None and second is not None
            assert first.id != second.id
            assert third is None
            a.rollback()
            b.rollback()
    finally:
        with Session(engine) as cleanup:
            cleanup.delete(cleanup.get(Tenant, tenant_id))
            cleanup.commit()
