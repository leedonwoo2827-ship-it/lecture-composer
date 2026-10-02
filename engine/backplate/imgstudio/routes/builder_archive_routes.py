"""보관함(게시판) 라우트 — 목록/보관/열람/삭제."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import archive

router = APIRouter(prefix="/api/builder/archives", tags=["builder-archives"])


class ArchiveBody(BaseModel):
    title: str = "프롬프트"
    content: str


@router.get("")
def list_archives() -> dict[str, Any]:
    return {"ok": True, "archives": archive.list_archives()}


@router.get("/{archive_id}")
def get_archive(archive_id: str) -> dict[str, Any]:
    item = archive.get_archive(archive_id)
    return {"ok": bool(item), "archive": item}


@router.post("")
def save_archive(body: ArchiveBody) -> dict[str, Any]:
    if not body.content.strip():
        return {"ok": False, "error": "보관할 내용이 없습니다."}
    return {"ok": True, "archive": archive.save_archive(body.title, body.content)}


@router.delete("/{archive_id}")
def delete_archive(archive_id: str) -> dict[str, Any]:
    return {"ok": archive.delete_archive(archive_id)}
