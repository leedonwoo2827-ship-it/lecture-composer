# -*- coding: utf-8 -*-
"""산출물 아카이브 — 파일시스템이 source of truth.

**경로를 조립하는 유일한 곳.** 다른 모듈은 여기서만 경로를 받아 간다.

산출물은 앱 폴더 **밖**, 형제 폴더에 쌓인다:

    D:\\00work\\260808-jarang\\        ← 앱 (git)
    D:\\00work\\showcase-out-260808\\  ← 산출물 (SHOWCASE_WORKSPACE 로 재지정)

이렇게 두는 이유:
  - `git clean` 이나 레포 재클론이 산출물을 지울 수 없다.
  - 백업·이관이 폴더 하나 복사로 끝난다.
  - 앱을 지우고 다시 받아도 만들어 둔 쇼케이스가 그대로 남는다.

폴더는 **파이프라인 단계와 1:1** 이다. 어느 단계 산출물인지 경로만 봐도 알아야 하고,
한 단계를 다시 돌려도 다른 단계 결과가 섞이지 않는다.

    showcase-out-260808/
      01_example-service/           ← 프로젝트 (NN_slug)
        project.json
        01_프레임/   v1-f03.webp · vision/v1-f03.webp
        02_레포/     repo/ · tree.json · commits.json
        03_캡션/     caption.json
        04_연결/     link.json
        05_의사결정/ decisions.json
        06_대본/     v1_script.json
        07_음성/     v1.wav(성우) · v1.draft.wav(TTS) · v1.opus
        08_자막/     v1.srt · cue-sheet.md · cue-sheet.csv
        09_테마/     theme.json
        10_덱/       deck.json · deck.overrides.json
        11_완성/     index.html · assets/ · <slug>.html · <slug>.zip
        _cache/      스테이지 캐시 (input_hash · cost · status)
        _logs/
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

APP_DIR = Path(__file__).resolve().parent.parent

# 기본값은 앱 폴더의 **형제**. IDA 의 IDA_WORKSPACE 와 같은 규약.
ROOT = Path(
    os.environ.get("SHOWCASE_WORKSPACE")
    or (APP_DIR.parent / f"showcase-out-{APP_DIR.name.split('-')[0]}")
)

# 단계 키 → (폴더명, 사람이 읽는 이름)
# ★ 폴더명은 바꾸지 않는다. 이미 만든 프로젝트의 산출물이 미아가 된다.
STEPS: Dict[str, Tuple[str, str]] = {
    "prd":       ("00_기획", "발표 기획서"),
    "frames":    ("01_프레임", "프레임 추출"),
    "repo":      ("02_레포", "레포 수집"),
    "caption":   ("03_캡션", "쓸 컷 고르기"),
    "link":      ("04_연결", "기능-코드 연결"),
    "decisions": ("05_의사결정", "기술적 의사결정"),
    "script":    ("06_대본", "내레이션 대본"),
    "audio":     ("07_음성", "음성"),
    "subtitle":  ("08_자막", "자막·큐시트"),
    "images":    ("09_이미지", "슬라이드 이미지"),
    "deck":      ("10_덱", "덱 조립"),
    "dist":      ("11_완성", "완성본"),
}

CACHE = "_cache"
LOGS = "_logs"
VISION = "vision"          # 01_프레임/vision/ — Claude 로 보낼 축소본
REPO = "repo"              # 02_레포/repo/    — shallow clone
ASSETS = "assets"          # 11_완성/assets/

F_PROJECT = "project.json"
F_DECK = "deck.json"
F_OVERRIDES = "deck.overrides.json"
F_LEDGER = "원장.json"
# 기계가 읽는 것을 치워 두는 자리. 사람이 여는 폴더에는 집어야 할 파일만 남긴다.
BAK = "bak"

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ASCII_BAD = re.compile(r"[^a-z0-9-]+")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def nfc(s: str) -> str:
    """macOS 에서 온 파일명은 NFD 라 `==` 매칭이 실패한다. 비교 전 항상 통과시킨다."""
    return unicodedata.normalize("NFC", s or "")


def slug(name: str, limit: int = 40) -> str:
    """폴더명으로 안전한 이름. 한글은 그대로 둔다(사람이 폴더를 직접 여니까)."""
    s = _BAD.sub("", nfc(name).strip())
    s = re.sub(r"\s+", "-", s).strip(". -")
    return (s or "project")[:limit]


def ascii_slug(name: str, limit: int = 40) -> str:
    """파생 **파일명**용. 한글 파일명이 ffmpeg·URL·zip 을 깨는 것을 원천 차단한다.

    한글은 JSON 값(`source_label`)에만 살고, 디스크의 파생물은 전부 ascii 다.
    """
    s = _ASCII_BAD.sub("-", nfc(name).strip().lower()).strip("-")
    return (s or "item")[:limit]


# ── 경로 ──────────────────────────────────────────────────────────────────
def project_dir(pid: int, slug_name: str, *, create: bool = True) -> Path:
    """프로젝트 폴더. 같은 pid 폴더가 이미 있으면(이름이 바뀌었어도) 그것을 쓴다."""
    ROOT.mkdir(parents=True, exist_ok=True)
    prefix = f"{int(pid):02d}_"
    for d in sorted(ROOT.iterdir()):
        if d.is_dir() and d.name.startswith(prefix):
            return d
    p = ROOT / f"{prefix}{slug(slug_name)}"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def step_dir(pid: int, slug_name: str, step: str, *, create: bool = True) -> Path:
    p = project_dir(pid, slug_name, create=create) / STEPS[step][0]
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def step_label(step: str) -> str:
    return STEPS[step][1]


def sub_dir(pid: int, slug_name: str, step: str, which: str, *, create: bool = True) -> Path:
    d = step_dir(pid, slug_name, step, create=create) / which
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(pid: int, slug_name: str, *, create: bool = True) -> Path:
    d = project_dir(pid, slug_name, create=create) / CACHE
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir(pid: int, slug_name: str, *, create: bool = True) -> Path:
    d = project_dir(pid, slug_name, create=create) / LOGS
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


# ── 읽기/쓰기 ─────────────────────────────────────────────────────────────
def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(p: Path, obj) -> Path:
    """원자적 쓰기. 중간에 죽어도 반쪽짜리 JSON 이 남지 않는다."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def write_text(p: Path, text: str, *, bom: bool = False) -> Path:
    """BOM 없는 utf-8 이 기본. csv 만 엑셀 때문에 BOM 을 붙인다."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
    tmp.replace(p)
    return p


# ── 프로젝트 메타 ──────────────────────────────────────────────────────────
def project_path(pid: int, slug_name: str, *, create: bool = False) -> Path:
    return project_dir(pid, slug_name, create=create) / F_PROJECT


def load_project(pid: int, slug_name: str) -> Dict[str, Any]:
    return read_json(project_path(pid, slug_name), {}) or {}


def save_project(pid: int, slug_name: str, doc: Dict[str, Any]) -> Path:
    doc = dict(doc or {})
    doc["id"] = int(pid)
    doc["updated_at"] = _now()
    return write_json(project_path(pid, slug_name, create=True), doc)


# ── 그림 프롬프트 원장 ──────────────────────────────────────────────────────
def ledger_path(pid: int, slug_name: str, *, create: bool = False) -> Path:
    """이미지 프롬프트 원장. **이름표(`data_id`)가 키다** — 슬라이드 번호가 아니다.

    번호는 앞에 장 하나만 끼어들어도 전부 밀린다(`005.png` 가 남의 장 그림이 된다).
    이름표는 안 밀린다. 그래서 프롬프트는 이름표에 매달고 **번호는 내보낼 때만**
    매긴다.

    ★ `bak/` 안에 둔다. 이 폴더는 **사람이 여는 자리**고(이미지 스튜디오와의 접점),
      열었을 때 집어야 할 파일이 하나로 보여야 한다. 원장은 기계가 읽는 장부라
      사람이 열 일이 없다(2026-08-14).
    """
    d = step_dir(pid, slug_name, "images", create=create)
    if create:
        (d / BAK).mkdir(parents=True, exist_ok=True)
    return d / BAK / F_LEDGER


def load_ledger(pid: int, slug_name: str) -> Dict[str, Any]:
    p = ledger_path(pid, slug_name)
    if not p.is_file():
        # 예전 자리(폴더 바로 밑)에 있던 원장을 그대로 읽는다 — 못 읽으면 모든 장이
        # 새 장으로 잡혀 이미 그린 그림이 통째로 「다시 그릴 것」이 된다.
        old = step_dir(pid, slug_name, "images", create=False) / F_LEDGER
        if old.is_file():
            return read_json(old, {}) or {}
    return read_json(p, {}) or {}


def save_ledger(pid: int, slug_name: str, doc: Dict[str, Any]) -> Path:
    out = write_json(ledger_path(pid, slug_name, create=True), doc)
    old = step_dir(pid, slug_name, "images", create=False) / F_LEDGER
    if old.is_file():
        old.unlink(missing_ok=True)          # 옛 자리에 한 벌 더 남기지 않는다
    return out


# ── 덱 ─────────────────────────────────────────────────────────────────────
def deck_path(pid: int, slug_name: str, *, create: bool = False) -> Path:
    return step_dir(pid, slug_name, "deck", create=create) / F_DECK


def overrides_path(pid: int, slug_name: str, *, create: bool = False) -> Path:
    return step_dir(pid, slug_name, "deck", create=create) / F_OVERRIDES


def load_overrides(pid: int, slug_name: str) -> Dict[str, Any]:
    return read_json(overrides_path(pid, slug_name), {}) or {}


def save_overrides(pid: int, slug_name: str, doc: Dict[str, Any]) -> Path:
    """손편집 패치 — **내용이 같으면 쓰지 않고, 다르면 .bak 을 남긴다.**

    이 파일은 콘솔 UI 와 사람이 함께 고친다. 그냥 덮어쓰면 손으로 다듬은 캡션을
    날린다. IDA 의 나레이션 저장이 같은 이유로 같은 규칙을 쓴다.
    """
    p = overrides_path(pid, slug_name, create=True)
    new = json.dumps(doc or {}, ensure_ascii=False, indent=2)
    if p.is_file():
        old = p.read_text(encoding="utf-8")
        if old == new:
            return p
        p.with_suffix(p.suffix + ".bak").write_text(old, encoding="utf-8")
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(p)
    return p


# ── 다운로드 (경로 탈출 차단) ──────────────────────────────────────────────
def safe_child(base: Path, filename: str) -> Optional[Path]:
    """`base` 밖으로 나가는 경로를 거부한다. 다운로드 엔드포인트 전용."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    p = (base / filename).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


# ── 목록 ───────────────────────────────────────────────────────────────────
def list_projects() -> List[Dict[str, Any]]:
    """workspace 안의 프로젝트 목록. **파일이 source of truth** — DB 행이 없어도 보인다."""
    out: List[Dict[str, Any]] = []
    if not ROOT.is_dir():
        return out
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        m = re.match(r"^(\d+)_", d.name)
        if not m:
            continue
        if (d / F_HIDDEN).exists():      # 감춘 것 — 폴더는 그대로 있다
            continue
        meta = read_json(d / F_PROJECT, {}) or {}
        out.append({
            "id": int(meta.get("id") or m.group(1)),
            "slug": meta.get("slug") or d.name[len(m.group(0)):],
            "title": meta.get("title") or d.name[len(m.group(0)):],
            "dir": str(d),
            "items": len(meta.get("items") or []),
            "updated_at": meta.get("updated_at"),
        })
    return out


def all_pids() -> List[int]:
    """폴더에 있는 **모든** 번호. 감춘 것도 센다."""
    out: List[int] = []
    if not ROOT.is_dir():
        return out
    for d in ROOT.iterdir():
        m = re.match(r"^(\d+)_", d.name) if d.is_dir() else None
        if m:
            out.append(int(m.group(1)))
    return out


def next_pid() -> int:
    """★ **감춘 폴더도 번호를 차지한다.**

    예전엔 보이는 목록에서만 최댓값을 셌다. 04 를 감춰 두면 다음 번호가 다시
    04 가 되고, 새 프로젝트가 감춰진 폴더 안으로 들어간다 — 만들자마자
    "프로젝트를 찾을 수 없습니다" 가 뜨고 폼이 초기화된다. 실제로 그랬다.
    폴더 이름의 번호를 직접 센다.
    """
    return max(all_pids(), default=0) + 1


F_HIDDEN = "_감춤"


def hide_project(pid: int, slug_name: str) -> str:
    """★ **지우지 않는다.** 목록에서 감추고, 폴더 경로를 돌려준다.

    산출물에는 몇 시간짜리 Claude 호출 결과와 손으로 고친 대본이 들어 있다.
    그것을 버튼 하나로 지우는 코드는 두지 않는다 — 잘못 눌렀을 때 되돌릴 방법이
    없기 때문이다. 앱은 시야에서 치우기만 하고, 폴더는 사람이 탐색기에서 직접
    지운다. 마음이 바뀌면 이 표시 파일만 지우면 목록에 다시 나온다.
    """
    d = project_dir(pid, slug_name, create=False)
    if d.is_dir():
        (d / F_HIDDEN).write_text(
            "이 파일이 있으면 앱 목록에 나오지 않습니다.\n"
            "다시 보이게 하려면 이 파일을 지우세요.\n", encoding="utf-8")
    return str(d)


def describe() -> Dict[str, Any]:
    """설정 화면에 보여줄 현재 워크스페이스 정보."""
    return {
        "app_dir": str(APP_DIR),
        "root": str(ROOT),
        "exists": ROOT.is_dir(),
        "from_env": bool(os.environ.get("SHOWCASE_WORKSPACE")),
        "projects": len(list_projects()),
    }
