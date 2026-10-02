"""설정 라우트 — 기본 생성 옵션(크기·형식)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.config import load_settings, save_settings
from ..core.constants import SIZE_CHOICES

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _public(s: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(s)
    out["size_choices"] = SIZE_CHOICES
    return out


class SettingsPatch(BaseModel):
    default_size: str | None = None
    default_format: str | None = None


@router.get("")
async def get_settings():
    return _public(load_settings())


@router.post("")
async def update_settings(patch: SettingsPatch):
    data = {k: v for k, v in patch.model_dump().items() if v is not None}
    return _public(save_settings(data))
