"""프리셋 카탈로그 라우트 — 목록/상세/저장/삭제."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from ..services import presets

router = APIRouter(prefix="/api/builder/presets", tags=["builder-presets"])


@router.get("")
def list_presets() -> dict[str, Any]:
    return {"ok": True, "presets": presets.list_presets()}


@router.get("/{name}")
def preset_detail(name: str) -> dict[str, Any]:
    detail = presets.get_preset_detail(name)
    return {"ok": bool(detail), "preset": detail}


@router.post("")
async def save_preset(
    name: str = Form(...),
    description: str = Form(""),
    keywords: str = Form(""),          # 콤마 구분
    body: str = Form(""),
    purpose: str = Form(""),
    tone: str = Form(""),
    color: str = Form(""),
    style: str = Form(""),
    cuts: str = Form(""),
    cover: UploadFile | None = File(None),
) -> dict[str, Any]:
    if not name.strip():
        return {"ok": False, "error": "이름을 입력하세요."}
    kw = [k.strip() for k in keywords.split(",") if k.strip()]
    cover_bytes, cover_ext = None, "png"
    if cover is not None:
        cover_bytes = await cover.read()
        cover_ext = (cover.filename or "cover.png").rsplit(".", 1)[-1]
    options = {
        "purpose": purpose, "tone": tone, "color": color, "style": style,
        "cuts": int(cuts) if cuts.strip().isdigit() else None,
    }
    detail = presets.save_preset(name, description, kw, body, cover_bytes, cover_ext, options)
    return {"ok": True, "preset": detail}


@router.delete("/{name}")
def delete_preset(name: str) -> dict[str, Any]:
    ok = presets.delete_preset(name)
    return {"ok": ok, "error": "" if ok else "내장 프리셋은 삭제할 수 없습니다."}
