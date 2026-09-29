from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app import demo_data
from app.models import Job, JobEvent, Tenant, UploadedFile
from conftest import login
from worker import main as worker


def test_generated_history_is_consistent(setup):
    client, db, _, _ = setup
    counts = demo_data.generate(db, jobs=300, days=30, seed=7)
    assert counts["jobs"] == counts["files"] == 300
    tenants = db.scalars(select(Tenant).where(Tenant.name.in_(demo_data.TENANTS))).all()
    assert len(tenants) == 3

    jobs = db.scalars(select(Job).where(Job.tenant_id.in_([t.id for t in tenants]))).all()
    statuses = Counter(job.status for job in jobs)
    assert set(statuses) == {"completed", "failed"}  # nothing the worker would pick up
    assert 0.8 < statuses["completed"] / len(jobs) < 0.97
    now = datetime.now(timezone.utc)
    for job in jobs:
        assert now - timedelta(days=31) < job.created_at <= job.started_at <= job.finished_at <= now + timedelta(minutes=5)
        assert job.status == "completed" or job.error_code
        assert (job.rows_out or 0) >= 0
    assert db.scalar(select(func.count()).select_from(UploadedFile).where(
        UploadedFile.tenant_id.in_([t.id for t in tenants]))) == 300

    # Every job's history starts at queued and ends in its final status, in order.
    events = db.scalars(select(JobEvent).order_by(JobEvent.job_id, JobEvent.id)).all()
    by_job = {}
    for event in events:
        by_job.setdefault(event.job_id, []).append(event)
    for job in jobs:
        chain = by_job[job.id]
        assert chain[0].from_status is None and chain[0].to_status == "queued"
        assert chain[-1].to_status == job.status
        assert sum(e.to_status == "processing" for e in chain) == job.attempt
        assert all(a.created_at <= b.created_at for a, b in zip(chain, chain[1:]))

    assert worker.claim_next(db, "w1") is None
    login(client, demo_data.DEMO_EMAIL, demo_data.DEMO_PASSWORD)
    busiest = max(tenants, key=lambda t: sum(j.tenant_id == t.id for j in jobs))
    body = client.get(f"/api/tenants/{busiest.id}/monitoring?period=30d").json()
    assert body["summary"]["completed"] + body["summary"]["failed"] == sum(j.tenant_id == busiest.id for j in jobs)
    assert body["error_codes"] and body["summary"]["retries"] >= 0


def test_same_seed_gives_same_distribution(setup):
    _, db, _, _ = setup
    demo_data.generate(db, jobs=150, days=10, seed=3)
    first = Counter(db.scalars(select(Job.job_type + ":" + Job.status)).all())
    demo_data.reset(db)
    demo_data.generate(db, jobs=150, days=10, seed=3)
    assert Counter(db.scalars(select(Job.job_type + ":" + Job.status)).all()) == first
