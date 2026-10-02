"""원고 파일 → 텍스트 추출 라우트."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile

from ..services import manuscript

router = APIRouter(prefix="/api/builder", tags=["builder-manuscript"])


@router.post("/extract-text")
async def extract_text(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    text, note = manuscript.extract_text(file.filename or "", data)
    truncated = len(text) > manuscript.MAX_CHARS
    return {
        "ok": bool(text),
        "filename": file.filename,
        "text": text[: manuscript.MAX_CHARS],
        "chars": len(text),
        "truncated": truncated,
        "note": note,
    }
