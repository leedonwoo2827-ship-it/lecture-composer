"""이미지 라우트 — 생성 / 수정(자연어·마스크) / 병합 / 목록 / 파일 / 삭제."""
from __future__ import annotations

import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import load_settings
from ..core.constants import IMAGES_DIR
from ..core.database import EditEvent, Image
from .helpers import decode_data_url, get_db, read_image_file, save_image_bytes
from ..services import codex_image
from ..services.codex_image import ImageEngineError, NotAuthenticated

router = APIRouter(prefix="/api/images", tags=["images"])


# ── 요청 모델 ────────────────────────────────────────────────────────────────
class GenerateReq(BaseModel):
    prompt: str
    project_id: Optional[int] = None
    size: Optional[str] = None


class EditReq(BaseModel):
    instruction: str
    type: str = "nl"                 # "nl" | "mask"
    mask_image: Optional[str] = None  # mask 일 때: 마스크 강조 합성본(data URL/base64)
    size: Optional[str] = None


class ComposeReq(BaseModel):
    prompt: str
    source_ids: List[int] = []
    extra_images: List[str] = []      # 라이브러리 밖에서 가져온 이미지(base64)
    project_id: Optional[int] = None
    size: Optional[str] = None


# ── 엔진 호출 래퍼 (예외 → HTTP) ──────────────────────────────────────────────
async def _run_engine(prompt: str, size: str, refs: Optional[List[bytes]]):
    settings = load_settings()
    try:
        return await asyncio.to_thread(
            codex_image.generate_image, prompt,
            size=size, refs=refs, settings=settings,
        )
    except NotAuthenticated as e:
        raise HTTPException(401, str(e))
    except ImageEngineError as e:
        raise HTTPException(502, str(e))


def _new_image(db: Session, *, prompt: str, meta: dict, size: str, kind: str,
               file_path: str, project_id: Optional[int], parent_id: Optional[int]) -> Image:
    img = Image(
        project_id=project_id, prompt=prompt, engine=meta.get("engine", "codex"),
        model=meta.get("model", ""), size=size, file_path=file_path,
        kind=kind, parent_id=parent_id,
    )
    db.add(img)
    db.commit()
    return img


# ── 목록 / 상세 / 파일 ────────────────────────────────────────────────────────
@router.get("")
async def list_images(project_id: Optional[int] = None, favorite: Optional[bool] = None,
                      db: Session = Depends(get_db)):
    stmt = select(Image).order_by(Image.created_at.desc())
    if project_id is not None:
        stmt = stmt.where(Image.project_id == project_id)
    if favorite:
        stmt = stmt.where(Image.favorite.is_(True))
    return [i.to_dict() for i in db.execute(stmt).scalars().all()]


@router.get("/{image_id}")
async def get_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        raise HTTPException(404, "image not found")
    events = db.execute(
        select(EditEvent).where(EditEvent.image_id == image_id).order_by(EditEvent.created_at)
    ).scalars().all()
    # 편집 계보(조상 체인)
    lineage = []
    cur = img
    seen = set()
    while cur and cur.id not in seen:
        seen.add(cur.id)
        lineage.append(cur.to_dict())
        cur = db.get(Image, cur.parent_id) if cur.parent_id else None
    return {**img.to_dict(), "events": [e.to_dict() for e in events],
            "lineage": list(reversed(lineage))}


@router.get("/{image_id}/file")
async def image_file(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        raise HTTPException(404, "image not found")
    path = IMAGES_DIR / img.file_path
    if not path.is_file():
        raise HTTPException(404, "file missing")
    return FileResponse(path, media_type="image/png")


# ── 1) 생성 ───────────────────────────────────────────────────────────────────
@router.post("/generate")
async def generate(req: GenerateReq, db: Session = Depends(get_db)):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "프롬프트를 입력하세요.")
    size = req.size or load_settings().get("default_size", "auto")
    data, meta = await _run_engine(prompt, size, None)
    fname = save_image_bytes(data)
    img = _new_image(db, prompt=prompt, meta=meta, size=size, kind="generate",
                     file_path=fname, project_id=req.project_id, parent_id=None)
    return img.to_dict()


# ── 2) 수정 (자연어 / 마스크) ─────────────────────────────────────────────────
@router.post("/{image_id}/edit")
async def edit(image_id: int, req: EditReq, db: Session = Depends(get_db)):
    base = db.get(Image, image_id)
    if not base:
        raise HTTPException(404, "image not found")
    instruction = (req.instruction or "").strip()
    if not instruction:
        raise HTTPException(400, "수정 지시문을 입력하세요.")

    size = req.size or base.size or "auto"
    base_bytes = read_image_file(base)

    if req.type == "mask" and req.mask_image:
        # 마우스로 칠한 영역을 강조한 합성본을 함께 보내 영역 위주 편집을 유도.
        # gpt-image-2 에 전용 mask 파라미터가 없어, 원본 + 강조본 2장을 참조로 전달한다.
        try:
            mask_bytes = decode_data_url(req.mask_image)
        except Exception:
            raise HTTPException(400, "마스크 이미지 디코드 실패")
        refs = [base_bytes, mask_bytes]
        prompt = (
            f"{instruction}. 두 번째 이미지에서 반투명 색으로 강조 표시된 영역만 수정하고, "
            f"표시되지 않은 영역은 첫 번째(원본) 이미지와 동일하게 유지하라. "
            f"강조 표시 자체는 결과물에 포함하지 말 것."
        )
        ev_type = "mask"
    else:
        refs = [base_bytes]
        prompt = instruction
        ev_type = "nl"

    data, meta = await _run_engine(prompt, size, refs)
    fname = save_image_bytes(data)
    new_img = _new_image(db, prompt=instruction, meta=meta, size=size, kind="edit",
                         file_path=fname, project_id=base.project_id, parent_id=base.id)
    db.add(EditEvent(image_id=base.id, type=ev_type, instruction=instruction,
                     source_image_ids=json.dumps([base.id]), result_image_id=new_img.id))
    db.commit()
    return new_img.to_dict()


# ── 3) 병합 / 가져오기 ("+") ──────────────────────────────────────────────────
@router.post("/compose")
async def compose(req: ComposeReq, db: Session = Depends(get_db)):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "병합 지시문을 입력하세요.")
    refs: List[bytes] = []
    used_ids: List[int] = []
    for iid in req.source_ids[:16]:
        img = db.get(Image, iid)
        if img:
            refs.append(read_image_file(img))
            used_ids.append(iid)
    for b64 in req.extra_images[:16]:
        try:
            refs.append(decode_data_url(b64))
        except Exception:
            continue
    if not refs:
        raise HTTPException(400, "병합할 이미지를 1장 이상 선택하세요.")

    size = req.size or load_settings().get("default_size", "auto")
    data, meta = await _run_engine(prompt, size, refs)
    fname = save_image_bytes(data)
    parent = used_ids[0] if used_ids else None
    new_img = _new_image(db, prompt=prompt, meta=meta, size=size, kind="merge",
                         file_path=fname, project_id=req.project_id, parent_id=parent)
    db.add(EditEvent(image_id=new_img.id, type="merge", instruction=prompt,
                     source_image_ids=json.dumps(used_ids), result_image_id=new_img.id))
    db.commit()
    return new_img.to_dict()


# ── 즐겨찾기 / 이동 / 삭제 ────────────────────────────────────────────────────
class MoveReq(BaseModel):
    project_id: Optional[int] = None


@router.post("/{image_id}/favorite")
async def toggle_favorite(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        raise HTTPException(404, "image not found")
    img.favorite = not img.favorite
    db.commit()
    return {"id": img.id, "favorite": img.favorite}


@router.post("/{image_id}/move")
async def move_image(image_id: int, body: MoveReq, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        raise HTTPException(404, "image not found")
    img.project_id = body.project_id
    db.commit()
    return img.to_dict()


@router.delete("/{image_id}")
async def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        raise HTTPException(404, "image not found")
    try:
        (IMAGES_DIR / img.file_path).unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(img)
    db.commit()
    return {"ok": True}
