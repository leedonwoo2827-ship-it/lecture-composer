"""보관함 — 생성한 프롬프트를 서버에 영구 보관(게시판). archives.json 단일 인덱스."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ..core import constants


def _load() -> list[dict[str, Any]]:
    if constants.ARCHIVES_PATH.exists():
        try:
            return json.loads(constants.ARCHIVES_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(items: list[dict[str, Any]]) -> None:
    constants.ARCHIVES_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _preview(content: str, n: int = 90) -> str:
    text = re.sub(r"```[a-zA-Z]*", "", content).replace("\n", " ").strip()
    return text[:n] + ("…" if len(text) > n else "")


def list_archives() -> list[dict[str, Any]]:
    """내용 제외한 목록(최신순)."""
    items = _load()
    items.sort(key=lambda x: x.get("created", ""), reverse=True)
    return [{
        "id": it["id"], "title": it.get("title", "(제목 없음)"),
        "created": it.get("created", ""), "chars": len(it.get("content", "")),
        "preview": _preview(it.get("content", "")),
    } for it in items]


def get_archive(archive_id: str) -> dict[str, Any] | None:
    return next((it for it in _load() if it["id"] == archive_id), None)


def save_archive(title: str, content: str) -> dict[str, Any]:
    items = _load()
    now = datetime.now()
    entry = {
        "id": now.strftime("%Y%m%d-%H%M%S-") + str(len(items) + 1),
        "title": (title or "프롬프트").strip()[:80],
        "created": now.strftime("%Y-%m-%d %H:%M"),
        "content": content,
    }
    items.append(entry)
    _save(items)
    return entry


def delete_archive(archive_id: str) -> bool:
    items = _load()
    kept = [it for it in items if it["id"] != archive_id]
    if len(kept) == len(items):
        return False
    _save(kept)
    return True
