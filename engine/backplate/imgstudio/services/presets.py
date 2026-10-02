"""프리셋 폴더 스캔/저장 로직.

presets/<이름>/
  meta.json   # {"description": "...", "keywords": [...], "builtin": true|false}
  preset.md   # (선택) 상세 설명/프롬프트 골격
  cover.*     # (선택) 썸네일/예시 이미지

- builtin=True  : 폴더에 직접 떨군 기본 프리셋(본인 카드뉴스 등) — 삭제 불가
- builtin=False : UI '내 프리셋'으로 저장한 것 — 삭제 가능
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core import constants

_COVER_NAMES = ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp")


def _safe_name(name: str) -> str:
    """경로 분리자/위험 문자 제거. 한글은 허용."""
    name = (name or "").strip()
    name = re.sub(r"[\\/:*?\"<>|]", "", name)        # 윈도우 금지 문자
    name = name.replace("..", "").strip(". ")
    return name[:60] or "untitled"


def _read_meta(folder: Path) -> dict[str, Any]:
    meta_path = folder / "meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _cover_url(folder: Path) -> str:
    for cover in _COVER_NAMES:
        if (folder / cover).exists():
            return f"{constants.URL_PREFIX}/presets/{folder.name}/{cover}"
    return ""


def parse_style_catalog() -> list[dict[str, Any]]:
    """prompts/style_catalog.md 의 표(15종)를 프리셋 항목으로 파싱. 단일 출처."""
    path = constants.PROMPTS_DIR / "style_catalog.md"
    items: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return items
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 4 or not cols[0].isdigit():   # 헤더·구분선 제외
            continue
        name = cols[1].replace("★", "").strip()
        desc = cols[2].replace("★", "").strip()
        keywords = [k.strip() for k in cols[3].split(",") if k.strip()]
        items.append({
            "name": name, "description": desc, "keywords": keywords,
            "cover_url": "", "builtin": True, "kind": "style",
        })
    return items


def _folder_presets() -> list[dict[str, Any]]:
    constants.PRESETS_DIR.mkdir(exist_ok=True)
    items: list[dict[str, Any]] = []
    for folder in sorted(constants.PRESETS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith(("_", ".")):
            continue
        meta = _read_meta(folder)
        description = meta.get("description", "")
        if not description and (folder / "preset.md").exists():
            try:
                first = (folder / "preset.md").read_text(encoding="utf-8").strip().splitlines()
                description = next((l.lstrip("# ").strip() for l in first if l.strip()), "")
            except OSError:
                pass
        items.append({
            "name": folder.name,
            "description": description,
            "keywords": meta.get("keywords", []),
            "cover_url": _cover_url(folder),
            "builtin": bool(meta.get("builtin", True)),  # 메타 없으면 기본=내장(삭제불가)
            "kind": "folder",
            # 프리셋이 2번 탭 옵션에 매핑되는 값들 (없으면 빈 값)
            "purpose": meta.get("purpose", ""),
            "tone": meta.get("tone", ""),
            "color": meta.get("color", ""),
            "style": meta.get("style", ""),
            "cuts": meta.get("cuts"),
        })
    items.sort(key=lambda p: (not p["builtin"], p["name"]))  # 내장 먼저, 그다음 내 프리셋
    return items


def list_presets() -> list[dict[str, Any]]:
    """폴더 프리셋(카드뉴스/내 프리셋) + 스타일 카탈로그 15종을 합쳐 반환."""
    return _folder_presets() + parse_style_catalog()


def get_preset_detail(name: str) -> dict[str, Any]:
    folder = constants.PRESETS_DIR / _safe_name(name)
    if not folder.is_dir():
        return {}
    meta = _read_meta(folder)
    body = ""
    if (folder / "preset.md").exists():
        body = (folder / "preset.md").read_text(encoding="utf-8")
    return {
        "name": folder.name,
        "description": meta.get("description", ""),
        "keywords": meta.get("keywords", []),
        "body": body,
        "cover_url": _cover_url(folder),
        "builtin": bool(meta.get("builtin", True)),
    }


def save_preset(name: str, description: str, keywords: list[str],
                body: str = "", cover_bytes: bytes | None = None,
                cover_ext: str = "png", options: dict[str, Any] | None = None) -> dict[str, Any]:
    folder = constants.PRESETS_DIR / _safe_name(name)
    folder.mkdir(parents=True, exist_ok=True)

    meta = {"description": description.strip(), "keywords": keywords, "builtin": False}
    for key in ("purpose", "tone", "color", "style", "cuts"):
        val = (options or {}).get(key)
        if val not in (None, ""):
            meta[key] = val
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = f"# {name}\n\n{description.strip()}\n"
    if keywords:
        md += "\n키워드: " + ", ".join(keywords) + "\n"
    if body.strip():
        md += "\n" + body.strip() + "\n"
    (folder / "preset.md").write_text(md, encoding="utf-8")

    if cover_bytes:
        ext = cover_ext.lower().lstrip(".")
        if ext not in ("png", "jpg", "jpeg", "webp"):
            ext = "png"
        (folder / f"cover.{ext}").write_bytes(cover_bytes)

    return get_preset_detail(folder.name)


def delete_preset(name: str) -> bool:
    """내 프리셋(builtin=False)만 삭제. 내장은 거부."""
    folder = constants.PRESETS_DIR / _safe_name(name)
    if not folder.is_dir():
        return False
    if bool(_read_meta(folder).get("builtin", True)):
        return False
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
    return True
