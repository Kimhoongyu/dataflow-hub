from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import Membership, Project, User

router = APIRouter(prefix="/api/tenants/{tenant_id}/projects", tags=["projects"])


def authorized_tenant(tenant_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> UUID:
    if not db.get(Membership, (user.id, tenant_id)):
        raise HTTPException(404, "조직을 찾을 수 없습니다.")
    return tenant_id


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)


class ProjectOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    name: str
    description: str
    created_at: datetime


class ProjectPage(BaseModel):
    items: list[ProjectOutput]
    total: int


@router.get("", response_model=ProjectPage)
def list_projects(tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db),
                  offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    condition = Project.tenant_id == tenant_id
    return {"items": db.scalars(select(Project).where(condition).order_by(Project.created_at.desc(), Project.id).offset(offset).limit(limit)).all(),
            "total": db.scalar(select(func.count()).select_from(Project).where(condition))}


@router.post("", response_model=ProjectOutput, status_code=201)
def create_project(data: ProjectInput, tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db)):
    project = Project(tenant_id=tenant_id, **data.model_dump())
    db.add(project)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "같은 이름의 프로젝트가 이미 있습니다.")
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOutput)
def project_detail(project_id: UUID, tenant_id: UUID = Depends(authorized_tenant), db: Session = Depends(get_db)):
    project = db.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if not project:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    return project
