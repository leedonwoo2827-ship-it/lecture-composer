"""앱 설정 — data/settings.json 에 저장/로드.

기본 생성 옵션(크기·형식)을 담는다. 이미지 엔진은 codex(ChatGPT 구독, 키리스) 하나뿐이라
엔진 선택 항목은 없다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from .atomic_io import atomic_write_json
from .constants import SETTINGS_PATH

_DEFAULTS: Dict[str, Any] = {
    "default_size": "auto",     # auto | 1024x1024 | 1536x1024 | 1024x1536
    "default_format": "png",    # png | jpeg | webp
}


def load_settings() -> Dict[str, Any]:
    data = dict(_DEFAULTS)
    try:
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in _DEFAULTS})
    except Exception:
        pass
    return data


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    data = load_settings()
    for k, v in (patch or {}).items():
        if k in _DEFAULTS:
            data[k] = v
    atomic_write_json(str(SETTINGS_PATH), data)
    return data


def get_setting(key: str, default: Any = None) -> Any:
    return load_settings().get(key, default)
