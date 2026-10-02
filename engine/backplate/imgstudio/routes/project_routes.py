"""프로젝트(사이드바 리스트/폴더) CRUD."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.database import Image, Project
from .helpers import get_db

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str


@router.get("")
async def list_projects(db: Session = Depends(get_db)):
    rows = db.execute(select(Project).order_by(Project.created_at.desc())).scalars().all()
    counts = dict(
        db.execute(select(Image.project_id, func.count(Image.id)).group_by(Image.project_id)).all()
    )
    return [
        {"id": p.id, "name": p.name,
         "created_at": p.created_at.isoformat() if p.created_at else None,
         "count": counts.get(p.id, 0)}
        for p in rows
    ]


@router.post("")
async def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    name = (body.name or "").strip() or "새 리스트"
    p = Project(name=name)
    db.add(p)
    db.commit()
    return {"id": p.id, "name": p.name, "count": 0}


@router.patch("/{project_id}")
async def rename_project(project_id: int, body: ProjectIn, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    p.name = (body.name or "").strip() or p.name
    db.commit()
    return {"id": p.id, "name": p.name}


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    # 이미지의 project_id 만 비우고 이미지 자체는 보존
    for img in list(p.images):
        img.project_id = None
    db.delete(p)
    db.commit()
    return {"ok": True}
