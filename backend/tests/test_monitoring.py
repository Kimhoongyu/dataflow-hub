from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import Job, JobEvent, Project, UploadedFile, WorkerHeartbeat
from conftest import login


@pytest.fixture()
def data(setup):
    """Tenant A: a spread of jobs across time and states. Tenant B: one job that must never leak."""
    client, db, tenants, _ = setup
    a, b = tenants
    now = db.scalar(select(func.now()))
    main = db.scalar(select(Project).where(Project.tenant_id == a.id))
    idle = Project(tenant_id=a.id, name="A idle", description="")
    db.add(idle)
    db.flush()

    def job(tenant, project, status, ago, duration=None, error=None, worker=None, finished=True):
        file = UploadedFile(tenant_id=tenant.id, project_id=project.id, original_name=f"{status}-{ago}.csv",
                            blob_name=f"t/{uuid4()}.csv", size_bytes=1, sha256="0" * 64, created_at=now - ago)
        db.add(file)
        db.flush()
        row = Job(tenant_id=tenant.id, project_id=project.id, file_id=file.id, job_type="validation", status=status,
                  notes="", attempt=1, request_id="t", created_at=now - ago, started_at=now - ago,
                  finished_at=now - ago if finished else None, duration_ms=duration, worker_id=worker,
                  error_code=error, error_message=f"{error} message" if error else None)
        db.add(row)
        db.flush()
        return row

    job(a, main, "completed", timedelta(hours=1), 100)
    job(a, main, "completed", timedelta(hours=2), 300)
    job(a, main, "failed", timedelta(hours=3), 50, "SCHEMA_MISMATCH")
    job(a, main, "completed", timedelta(days=3), 1000)                        # outside 24h, inside 7d
    job(a, main, "queued", timedelta(minutes=5), finished=False)
    retrying = job(a, main, "queued", timedelta(minutes=10), error="STORAGE_ERROR", finished=False)
    job(a, main, "processing", timedelta(minutes=2), worker="ghost", finished=False)  # worker has no heartbeat
    db.add(JobEvent(job_id=retrying.id, tenant_id=a.id, from_status="processing", to_status="queued", message="retry"))
    b_project = db.scalar(select(Project).where(Project.tenant_id == b.id))
    job(b, b_project, "completed", timedelta(hours=1), 5000)
    db.add_all([WorkerHeartbeat(worker_id="w-live", last_seen_at=now, processed_count=0),
                WorkerHeartbeat(worker_id="w-old", last_seen_at=now - timedelta(minutes=5), processed_count=0)])
    db.commit()
    login(client)
    return client, a, b, main, idle


def test_overview_last_24h(data):
    client, a, _, main, idle = data
    result = client.get(f"/api/tenants/{a.id}/monitoring")
    assert result.status_code == 200
    body = result.json()
    assert body["period"] == "24h" and body["bucket"] == "hour" and body["timezone"] == "Asia/Seoul"
    assert body["summary"] == {"uploads": 6, "completed": 2, "failed": 1, "success_rate": 0.6667,
                               "avg_duration_ms": 200.0, "p95_duration_ms": 290.0, "retries": 1}
    queue = body["queue"]
    assert (queue["queued"], queue["processing"], queue["stuck"]) == (2, 1, 1)
    assert queue["oldest_queued_seconds"] == 600.0
    assert (queue["workers_alive"], queue["workers_stale"]) == (1, 1)

    projects = {p["name"]: p for p in body["projects"]}
    assert set(projects) == {main.name, "A idle"}  # never tenant B's project
    stats = projects[main.name]
    assert (stats["uploads"], stats["completed"], stats["failed"], stats["success_rate"], stats["active"]) == (6, 2, 1, 0.6667, 3)
    assert stats["last_finished_at"] is not None
    assert projects["A idle"]["uploads"] == 0 and projects["A idle"]["success_rate"] is None

    series = body["timeseries"]
    assert len(series) == 25  # hourly buckets from the start hour through the current hour
    assert sum(b["completed"] for b in series) == 2 and sum(b["failed"] for b in series) == 1
    assert body["error_codes"] == [{"error_code": "SCHEMA_MISMATCH", "count": 1}]
    assert [(e["status"], e["error_code"]) for e in body["recent_errors"]] == [("queued", "STORAGE_ERROR"), ("failed", "SCHEMA_MISMATCH")]


def test_longer_period_includes_older_jobs(data):
    client, a, *_ = data
    body = client.get(f"/api/tenants/{a.id}/monitoring?period=7d").json()
    assert body["bucket"] == "day"
    assert (body["summary"]["uploads"], body["summary"]["completed"]) == (7, 3)
    assert len(body["timeseries"]) in (7, 8)  # depends on where "now" falls within the local day
    assert sum(b["completed"] for b in body["timeseries"]) == 3
    assert client.get(f"/api/tenants/{a.id}/monitoring?period=1y").status_code == 422


def test_monitoring_is_tenant_scoped(data):
    client, a, b, *_ = data
    login(client, "b@test.local")
    assert client.get(f"/api/tenants/{a.id}/monitoring").status_code == 404
    body = client.get(f"/api/tenants/{b.id}/monitoring").json()
    assert (body["summary"]["completed"], body["summary"]["avg_duration_ms"]) == (1, 5000.0)
    assert body["queue"]["queued"] == 0 and body["recent_errors"] == []


def test_empty_tenant_has_no_rates(setup):
    client, _, tenants, _ = setup
    login(client)
    body = client.get(f"/api/tenants/{tenants[0].id}/monitoring").json()
    assert body["summary"]["success_rate"] is None and body["summary"]["p95_duration_ms"] is None
    assert body["queue"]["oldest_queued_seconds"] is None
    assert all(b["completed"] == b["failed"] == 0 for b in body["timeseries"])
