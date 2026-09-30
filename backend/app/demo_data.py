"""Generate realistic history for demos and backup/restore practice (local only).

    docker compose exec api python -m app.demo_data --local
    docker compose exec api python -m app.demo_data --local --jobs 20000 --days 90 --reset

Creates three demo tenants with projects and N finished jobs spread over the last D days
(business hours weighted, KST), with a realistic mix of successes, retries and failures, so
the operations dashboard has something to show. Only final states (completed/failed) are
written, so the worker never picks these jobs up. Object storage is not touched: the files
are DB records only, so result downloads for demo jobs return 404 by design.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import random
from uuid import uuid4

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.auth import password_hasher
from app.db import engine
from app.models import Job, JobEvent, Membership, Project, Tenant, UploadedFile, User

DEMO_EMAIL = "demo-ops@dataflow.local"
DEMO_PASSWORD = "Demo-local-2026!"
KST = timezone(timedelta(hours=9))
TENANTS = {
    "Demo Cargo Ops": ["화물 적재 목록", "통관 서류 검증", "창고 재고"],
    "Demo Maintenance": ["부품 교체 이력", "정비 작업 지시", "공구 점검"],
    "Demo Customer Care": ["문의 접수", "설문 응답", "환불 요청"],
}
FILE_STEMS = ["daily-export", "manifest", "report", "records", "batch", "snapshot"]
JOB_TYPES = [("validation", 0.35), ("cleansing", 0.3), ("transformation", 0.2), ("aggregation", 0.15)]
DATA_ERRORS = [
    ("SCHEMA_MISMATCH", "중복된 열 이름: id", 0.4),
    ("INVALID_CSV", "CSV 구문 오류 (12행): unexpected end of data", 0.3),
    ("EMPTY_FILE", "헤더만 있고 데이터 행이 없습니다.", 0.2),
    ("FILE_MISSING", "원본 파일을 저장소에서 찾을 수 없습니다.", 0.1),
]
BATCH = 1000


def pick(rng: random.Random, weighted):
    return rng.choices(weighted, weights=[w[-1] for w in weighted])[0]


def business_time(rng: random.Random, now: datetime, days: int) -> datetime:
    """A moment in the last `days` days, mostly weekday 9–18 KST."""
    while True:
        day = (now - timedelta(days=rng.uniform(0, days))).astimezone(KST)
        weekend = day.weekday() >= 5
        hour = rng.gauss(13.5, 3.2) if rng.random() < 0.85 else rng.uniform(0, 24)
        if weekend and rng.random() < 0.7:
            continue
        moment = day.replace(hour=int(min(max(hour, 0), 23.99)), minute=rng.randrange(60), second=rng.randrange(60))
        if now - timedelta(days=days) <= moment < now:  # stay inside the window after moving the hour
            return moment.astimezone(timezone.utc)


def build_job(rng, now, days, tenant_id, project_id, user_id, project_name):
    created = business_time(rng, now, days)
    rows = int(rng.lognormvariate(7, 1.2)) + 10
    size = rows * rng.randint(40, 120)
    job_type = pick(rng, JOB_TYPES)[0]
    file_id, job_id = uuid4(), uuid4()
    stem = f"{rng.choice(FILE_STEMS)}-{created.astimezone(KST):%Y%m%d}-{rng.randrange(100):02d}"
    file = {"id": file_id, "tenant_id": tenant_id, "project_id": project_id, "original_name": f"{stem}.csv",
            "blob_name": f"{tenant_id}/{project_id}/{file_id}.csv", "size_bytes": size,
            "sha256": hashlib.sha256(file_id.bytes).hexdigest(), "uploaded_by": user_id, "created_at": created}
    events = [(None, "queued", "CSV 업로드 완료, 처리 대기열에 등록", created)]
    clock = created
    roll = rng.random()
    # 88% first try, 4% after a transient retry, 6% data error, 2% transient errors exhausting retries.
    plan = (["ok"] if roll < 0.88 else ["retry", "ok"] if roll < 0.92
            else ["data"] if roll < 0.98 else ["retry", "retry", "exhausted"])
    worker = f"worker-{rng.randrange(1, 4)}"
    attempt = 0
    for step in plan:
        attempt += 1
        clock += timedelta(seconds=rng.uniform(0.2, 4) if attempt == 1 else 10 * 2 ** (attempt - 2))
        started = clock
        events.append(("queued", "processing", f"Worker {worker} 처리 시작 ({attempt}회차)", started))
        duration = int(min(rows / rng.uniform(800, 3000) * 1000, 60000)) + rng.randint(5, 40)
        clock += timedelta(milliseconds=duration)
        if step == "retry":
            delay = 10 * 2 ** (attempt - 1)
            events.append(("processing", "queued", f"파일 저장소에 연결할 수 없습니다. {delay}초 후 재시도 ({attempt}/3)", clock))
    job = {"id": job_id, "tenant_id": tenant_id, "project_id": project_id, "file_id": file_id, "job_type": job_type,
           "notes": "", "attempt": attempt, "worker_id": worker, "request_id": uuid4().hex, "created_by": user_id,
           "created_at": created, "started_at": started, "finished_at": clock, "duration_ms": duration,
           "next_attempt_at": None, "rows_in": None, "rows_out": None, "error_row_count": None,
           "error_code": None, "error_message": None, "result_blob_name": None}
    final = plan[-1]
    if final == "ok":
        bad = int(rows * rng.uniform(0, 0.03)) if rng.random() < 0.4 else 0
        out = {"validation": rows - bad, "cleansing": rows - bad - int(rows * rng.uniform(0, 0.05)),
               "transformation": rows - bad, "aggregation": rng.randint(3, 20)}[job_type]
        job.update(status="completed", rows_in=rows, rows_out=out, error_row_count=bad,
                   result_blob_name=f"{tenant_id}/{project_id}/results/{job_id}.csv")
        events.append(("processing", "completed", f"처리 완료: {rows}행 처리 ({project_name})", clock))
    elif final == "data":
        code, message, _ = pick(rng, DATA_ERRORS)
        job.update(status="failed", error_code=code, error_message=message)
        events.append(("processing", "failed", f"처리 실패 [{code}]: {message}", clock))
    else:
        message = "파일 저장소에 연결할 수 없습니다."
        job.update(status="failed", error_code="STORAGE_ERROR", error_message=message)
        events.append(("processing", "failed", f"처리 실패 [STORAGE_ERROR]: {message} (최대 3회 시도 초과)", clock))
    rows_events = [{"job_id": job_id, "tenant_id": tenant_id, "from_status": f, "to_status": t, "message": m, "created_at": at}
                   for f, t, m, at in events]
    return file, job, rows_events


def reset(db: Session) -> None:
    db.execute(delete(Tenant).where(Tenant.name.in_(TENANTS)))  # cascades to projects, files, jobs, events
    db.execute(delete(User).where(User.email == DEMO_EMAIL))
    db.commit()


def generate(db: Session, jobs: int, days: int, seed: int) -> dict:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    user = User(email=DEMO_EMAIL, name="Demo Ops", password_hash=password_hasher.hash(DEMO_PASSWORD))
    db.add(user)
    projects = []
    for tenant_name, project_names in TENANTS.items():
        tenant = Tenant(name=tenant_name)
        db.add(tenant)
        db.flush()
        db.add(Membership(user_id=user.id, tenant_id=tenant.id))
        for name in project_names:
            project = Project(tenant_id=tenant.id, name=name, description="데모 데이터",
                              created_at=now - timedelta(days=days + 1))
            db.add(project)
            projects.append(project)
    db.flush()
    weights = [rng.uniform(0.5, 2) for _ in projects]  # some projects are busier than others
    counts = {"files": 0, "jobs": 0, "events": 0}
    for start in range(0, jobs, BATCH):
        files, job_rows, event_rows = [], [], []
        for _ in range(min(BATCH, jobs - start)):
            project = rng.choices(projects, weights=weights)[0]
            file, job, events = build_job(rng, now, days, project.tenant_id, project.id, user.id, project.name)
            files.append(file)
            job_rows.append(job)
            event_rows.extend(events)
        # Parents first: jobs reference files, events reference jobs.
        db.execute(insert(UploadedFile), files)
        db.execute(insert(Job), job_rows)
        db.execute(insert(JobEvent), event_rows)
        counts["files"] += len(files)
        counts["jobs"] += len(job_rows)
        counts["events"] += len(event_rows)
    db.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="로컬 데모용 작업 이력 생성")
    parser.add_argument("--local", action="store_true", help="공개된 데모 계정을 만든다는 것을 확인 (로컬 전용)")
    parser.add_argument("--jobs", type=int, default=2000)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42, help="같은 seed는 같은 분포를 만듭니다")
    parser.add_argument("--reset", action="store_true", help="기존 데모 조직·계정을 지우고 다시 만듭니다")
    args = parser.parse_args()
    if not args.local:
        parser.error("공개된 데모 계정을 만듭니다. 로컬 개발에서만 --local을 붙여 실행하세요.")
    with Session(engine) as db:
        if args.reset:
            reset(db)
        elif db.scalar(select(User.id).where(User.email == DEMO_EMAIL)):
            parser.error(f"{DEMO_EMAIL} 데모 데이터가 이미 있습니다. 다시 만들려면 --reset을 붙이세요.")
        counts = generate(db, args.jobs, args.days, args.seed)
    print(f"생성 완료: 조직 {len(TENANTS)}개, 프로젝트 {sum(map(len, TENANTS.values()))}개, "
          f"파일 {counts['files']}건, 작업 {counts['jobs']}건, 이력 {counts['events']}건")
    print(f"로그인: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
