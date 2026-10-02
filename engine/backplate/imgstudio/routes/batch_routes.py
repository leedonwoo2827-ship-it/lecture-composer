"""슬라이드 JSON 일괄 생성 라우트 — 파싱 / 폴더 확인 / 시작 / 진행 / 중단 / 재시도."""
from __future__ import annotations

import json
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.config import load_settings
from ..services import batch_jobs

router = APIRouter(prefix="/api/batch", tags=["batch"])


# ── 요청 모델 ────────────────────────────────────────────────────────────────
class ParseReq(BaseModel):
    text: Optional[str] = None       # JSON 원문(파일 내용 붙여넣기/업로드)
    data: Optional[Any] = None       # 이미 파싱된 객체


class DirReq(BaseModel):
    dir: str


class BatchItemIn(BaseModel):
    n: int
    prompt: str
    title: str = ""


class StartReq(BaseModel):
    items: List[BatchItemIn]
    out_dir: str
    size: Optional[str] = None
    deck: str = ""
    workers: int = batch_jobs.DEFAULT_WORKERS
    retries: int = batch_jobs.DEFAULT_RETRIES
    skip_existing: bool = True
    with_title: bool = False
    to_gallery: bool = True


# ── 1) JSON 파싱 (프롬프트 목록 정규화) ───────────────────────────────────────
@router.post("/parse")
async def parse(req: ParseReq):
    raw = req.data
    if raw is None:
        text = (req.text or "").strip().lstrip("﻿")
        if not text:
            raise HTTPException(400, "JSON 내용이 비어 있습니다.")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON 파싱 실패: {e.lineno}행 {e.colno}열 — {e.msg}")
    try:
        return batch_jobs.normalize_payload(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── 2) 출력 폴더 확인 / 열기 ──────────────────────────────────────────────────
@router.post("/inspect")
async def inspect(req: DirReq):
    return batch_jobs.inspect_dir(req.dir)


@router.post("/reveal")
async def reveal(req: DirReq):
    return batch_jobs.reveal_dir(req.dir)


# ── 3) 시작 / 목록 / 진행 ─────────────────────────────────────────────────────
@router.post("/start")
async def start(req: StartReq):
    settings = load_settings()
    size = req.size or settings.get("default_size", "auto")
    fmt = settings.get("default_format", "png")
    items = [{"n": it.n, "title": it.title, "prompt": it.prompt} for it in req.items]
    try:
        job = batch_jobs.start_job(
            items=items, out_dir=req.out_dir, size=size, deck=req.deck,
            workers=req.workers, retries=req.retries,
            skip_existing=req.skip_existing, with_title=req.with_title,
            fmt=fmt, to_gallery=req.to_gallery,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job": job.to_dict()}


@router.get("")
async def jobs():
    running = batch_jobs.active_job()
    return {"jobs": batch_jobs.list_jobs(), "active": running.id if running else None}


@router.get("/active")
async def active():
    job = batch_jobs.active_job()
    return {"job": job.to_dict() if job else None}


@router.get("/{job_id}")
async def job_detail(job_id: str):
    job = batch_jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다. (서버를 재시작하면 진행 상태가 사라집니다)")
    return {"job": job.to_dict()}


@router.post("/{job_id}/stop")
async def stop(job_id: str):
    r = batch_jobs.stop_job(job_id)
    if not r.get("ok"):
        raise HTTPException(404, r.get("error", "실패"))
    return r


@router.post("/{job_id}/retry")
async def retry(job_id: str):
    r = batch_jobs.retry_failed(job_id)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "실패"))
    return r
