# -*- coding: utf-8 -*-
"""버전 — **같은 재료로 여러 벌을 만들어 두고 고른다.**

초기에는 한 번에 맞출 수 없다. 광고 문체로 굽고, 개조식으로도 굽고, 20분짜리와
40분짜리를 만들어 놓고 나란히 본다. 그때마다 앞 것이 덮여 사라지면 비교가 안 된다.

한 버전은 **스테이지 캐시 + 손편집** 한 벌이다. 원본(영상·레포·프레임)은 무겁고
바뀌지 않으므로 복사하지 않는다 — S1/S2 는 버전을 타지 않는다.

    10_덱/_versions/<이름>/
      _cache/         s2b-outline.json · s5-decisions.json · s6-script.json · …
      deck.overrides.json
      meta.json       {"name","note","saved_at","tone","slides","sec","cost_usd"}

★ 되돌리기 전에 **지금 것을 자동으로 한 벌 뜬다**(`_auto/직전`). 복원은 되돌릴 수
  없는 동작인데, 실수로 눌렀을 때 잃을 게 있으면 안 된다.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import workspace as ws

# S1·S2 는 원본 수집이라 버전을 타지 않는다 — 무겁고 어차피 같다
SKIP = {"s1-frames", "s2-repo"}
DIRNAME = "_versions"
AUTO = "직전"


def _root(pid: int, slug: str) -> Path:
    return ws.step_dir(pid, slug, "deck") / DIRNAME


def _safe(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", ws.nfc(name or "").strip())
    return (re.sub(r"\s+", "-", s).strip(". -") or "버전")[:40]


def _summary(pid: int, slug: str) -> Dict[str, Any]:
    from pipeline.registry import ORDER, read_cache
    tone = (read_cache(pid, slug, "s7-copy") or {}).get("data", {}) or {}
    script = (read_cache(pid, slug, "s6-script") or {}).get("data", {}) or {}
    timeline = (read_cache(pid, slug, "s11-audio") or {}).get("data", {}) or {}
    outline = (read_cache(pid, slug, "s2b-outline") or {}).get("data", {}) or {}
    # ★ 실측(합성된 wav 길이)이 있으면 그것이 이긴다. 대본 추정치는 폴백일 뿐이다 —
    #   실측 초당 글자수를 보정하기 전에는 두 배 가까이 틀렸다.
    return {
        "tone": tone.get("tone"),
        "slides": len(outline.get("slides") or []),
        "sec": timeline.get("total_sec") or script.get("total_sec") or 0,
        "measured": bool(timeline.get("total_sec")),
        "cost_usd": round(sum((read_cache(pid, slug, k) or {}).get("cost_usd", 0.0)
                              for k in ORDER), 4),
    }


def save(pid: int, slug: str, name: str, note: str = "") -> Dict[str, Any]:
    d = _root(pid, slug) / _safe(name)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    (d / ws.CACHE).mkdir(parents=True, exist_ok=True)

    src = ws.cache_dir(pid, slug)
    n = 0
    for f in sorted(src.glob("*.json")):
        if f.stem in SKIP or f.name.startswith("_"):
            continue
        shutil.copy2(f, d / ws.CACHE / f.name)
        n += 1

    ov = ws.overrides_path(pid, slug)
    if ov.is_file():
        shutil.copy2(ov, d / ws.F_OVERRIDES)

    meta = {"name": _safe(name), "note": note, "stages": n,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            **_summary(pid, slug)}
    ws.write_json(d / "meta.json", meta)
    return meta


def listing(pid: int, slug: str) -> List[Dict[str, Any]]:
    r = _root(pid, slug)
    if not r.is_dir():
        return []
    out = []
    for d in sorted(r.iterdir()):
        if not d.is_dir():
            continue
        m = ws.read_json(d / "meta.json", None)
        if m:
            out.append(m)
    return sorted(out, key=lambda m: m.get("saved_at") or "", reverse=True)


def restore(pid: int, slug: str, name: str) -> Dict[str, Any]:
    d = _root(pid, slug) / _safe(name)
    if not d.is_dir():
        raise FileNotFoundError(f"없는 버전: {name}")

    # ★ 되돌리기 전에 지금 것을 한 벌 뜬다 — 실수로 눌러도 잃을 게 없어야 한다
    save(pid, slug, AUTO, note="복원 직전 자동 저장")

    cur = ws.cache_dir(pid, slug)
    for f in sorted((d / ws.CACHE).glob("*.json")):
        shutil.copy2(f, cur / f.name)
    src_ov = d / ws.F_OVERRIDES
    if src_ov.is_file():
        ws.save_overrides(pid, slug, ws.read_json(src_ov, {}) or {})
    return ws.read_json(d / "meta.json", {}) or {}


def remove(pid: int, slug: str, name: str) -> None:
    d = _root(pid, slug) / _safe(name)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


def describe(pid: int, slug: str) -> Dict[str, Any]:
    return {"current": _summary(pid, slug), "versions": listing(pid, slug)}
