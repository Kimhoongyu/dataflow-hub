from datetime import datetime
import hashlib
import logging
import os
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import Job, JobEvent, Project, UploadedFile, User
from app.projects import authorized_tenant
from app.storage import BlobNotFound, BlobStorage, StorageUnavailable, get_storage

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["jobs"])
logger = logging.getLogger("uvicorn.error")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
# Multipart framing and form fields add a little on top of the file itself.
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024

JobType = Literal["validation", "cleansing", "transformation", "aggregation"]
JobStatus = Literal["queued", "processing", "completed", "failed"]


class ProjectRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class FileRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    original_name: str
    size_bytes: int


class JobOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project: ProjectRef
    file: FileRef
    job_type: JobType
    status: JobStatus
    notes: str
    attempt: int
    rows_in: int | None
    rows_out: int | None
    error_row_count: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    next_attempt_at: datetime | None
    has_result: bool


class JobEventOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_status: JobStatus | None
    to_status: JobStatus
    message: str
    created_at: datetime


class JobDetail(JobOutput):
    events: list[JobEventOutput]


class JobPage(BaseModel):
    items: list[JobOutput]
    total: int


def read_csv_upload(file: UploadFile) -> tuple[str, bytes]:
    """Cheap checks at upload time; row-level validation is the worker's job."""
    name = os.path.basename((file.filename or "").replace("\\", "/")).strip()
    if len(name) <= 4 or len(name) > 255 or not name.lower().endswith(".csv"):
        raise HTTPException(422, "확장자가 .csv인 파일만 업로드할 수 있습니다.")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"파일은 {MAX_UPLOAD_BYTES / 1024 / 1024:g}MB 이하만 업로드할 수 있습니다.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "UTF-8 인코딩 CSV만 지원합니다.")
    if not text.strip():
        raise HTTPException(422, "빈 파일은 업로드할 수 없습니다.")
    if "\x00" in text:
        raise HTTPException(422, "CSV 형식의 텍스트 파일이 아닙니다.")
    return name, data


@router.post("/projects/{project_id}/jobs", response_model=JobOutput, status_code=201)
def create_job(project_id: UUID, request: Request, file: UploadFile = File(), job_type: JobType = Form(),
               notes: str = Form("", max_length=1000), tenant_id: UUID = Depends(authorized_tenant),
               user: User = Depends(current_user), db: Session = Depends(get_db),
               storage: BlobStorage = Depends(get_storage)):
    if not db.scalar(select(Project.id).where(Project.id == project_id, Project.tenant_id == tenant_id)):
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    name, data = read_csv_upload(file)
    request_id = request.state.request_id
    file_id, job_id = uuid4(), uuid4()
    blob_name = f"{tenant_id}/{project_id}/{file_id}.csv"
    try:
        storage.upload(blob_name, data)
    except StorageUnavailable:
        logger.warning("upload_storage_failed request_id=%s", request_id)
        raise HTTPException(503, "파일 저장소에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    db.add_all([
        UploadedFile(id=file_id, tenant_id=tenant_id, project_id=project_id, original_name=name, blob_name=blob_name,
                     size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), uploaded_by=user.id),
        Job(id=job_id, tenant_id=tenant_id, project_id=project_id, file_id=file_id, job_type=job_type,
            status="queued", notes=notes.strip(), attempt=0, request_id=request_id, created_by=user.id),
    ])
    try:
        # Without a relationship the unit of work cannot order the event after its job.
        db.flush()
        db.add(JobEvent(job_id=job_id, tenant_id=tenant_id, from_status=None, to_status="queued",
                        message="CSV 업로드 완료, 처리 대기열에 등록"))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        # Compensate so a failed DB write does not leave an unreferenced blob behind.
        try:
            storage.delete(blob_name)
        except StorageUnavailable:
            logger.error("orphan_blob blob_name=%s request_id=%s", blob_name, request_id)
        raise
    logger.info("job_created job_id=%s tenant_id=%s project_id=%s request_id=%s", job_id, tenant_id, project_id, request_id)
    return db.get(Job, job_id)


@router.get("/jobs", response_model=JobPage)
def list_jobs(tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db),
              project_id: UUID | None = None, status: JobStatus | None = None,
              offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    conditions = [Job.tenant_id == tenant_id]
    if project_id:
        conditions.append(Job.project_id == project_id)
    if status:
        conditions.append(Job.status == status)
    return {"items": db.scalars(select(Job).where(*conditions).order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit)).all(),
            "total": db.scalar(select(func.count()).select_from(Job).where(*conditions))}


def tenant_job(db: Session, tenant_id: UUID, job_id: UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job


@router.get("/jobs/{job_id}", response_model=JobDetail)
def job_detail(job_id: UUID, tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db)):
    job = tenant_job(db, tenant_id, job_id)
    events = db.scalars(select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.created_at, JobEvent.id)).all()
    return JobDetail(**JobOutput.model_validate(job).model_dump(),
                     events=[JobEventOutput.model_validate(event) for event in events])


@router.get("/jobs/{job_id}/result")
def download_result(job_id: UUID, tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db),
                    storage: BlobStorage = Depends(get_storage)):
    job = tenant_job(db, tenant_id, job_id)
    if not job.result_blob_name:
        raise HTTPException(404, "처리 결과가 아직 없습니다.")
    try:
        data = storage.download(job.result_blob_name)
    except BlobNotFound:
        raise HTTPException(404, "결과 파일을 찾을 수 없습니다.")
    except StorageUnavailable:
        raise HTTPException(503, "파일 저장소에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    stem = job.file.original_name.rsplit(".", 1)[0]
    filename = f"{stem}-{job.job_type}-result.csv"
    # RFC 5987 encoding keeps Korean file names intact across browsers.
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=\"result.csv\"; filename*=UTF-8''{quote(filename)}"})
