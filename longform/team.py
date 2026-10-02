"""팀 분담 — 강을 나눠 맡아 각자 PC·각자 계정으로 돌린다.

    local.json                 (깃 제외) 이 PC 를 쓰는 사람: {"me": "홍길동"}
    jobs/<잡>/team/L03.json    (깃에 올림) 강 하나 = 파일 하나 → 여러 사람이 push 해도 충돌하지 않는다
        {"lecture": "L03", "who": "홍길동", "claimed_at": "...", "status": "claimed|composed|rendered|stitched|published",
         "yt": {"id": "...", "url": "..."}, "updated_at": "...", "pc": "<컴퓨터 이름>"}

규칙
    누군가 맡은 강은 **그 사람 PC 에서만** 돈다. 다른 사람이 --only 로 골라도 건너뛴다(--force 로만 덮어씀).
    아무도 안 맡은 강은 누구나 돌릴 수 있다. 맡은 사람이 하나라도 있으면, --only 없이 돌릴 때 **내 담당만** 돈다.
    게시(publish)한 영상 ID 는 그 강 파일에 남는다 → 등록(register)이 팀 전체 것을 모은다.
"""
from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import REPO, Job
from longform.util import log, read_json, warn, write_json

LOCAL = REPO / "local.json"
ORDER = ["claimed", "composed", "rendered", "stitched", "published"]


def me() -> str:
    d = read_json(LOCAL, {}) or {}
    return (d.get("me") or os.environ.get("LECTURE_COMPOSER_ME") or "").strip()


def set_me(name: str) -> None:
    d = read_json(LOCAL, {}) or {}
    d["me"] = name.strip()
    write_json(LOCAL, d)


def _dir(job: Job) -> Path:
    return job.dir / "team"


def get(job: Job, lid: str) -> Dict[str, Any]:
    return read_json(_dir(job) / f"{lid}.json", {}) or {}


def all_claims(job: Job) -> Dict[str, Dict[str, Any]]:
    d = _dir(job)
    return {f.stem: read_json(f, {}) for f in sorted(d.glob("L*.json"))} if d.exists() else {}


def _write(job: Job, lid: str, doc: Dict[str, Any]) -> None:
    doc.update({"lecture": lid, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "pc": platform.node()})
    write_json(_dir(job) / f"{lid}.json", doc)


def claim(job: Job, lids: List[str], who: Optional[str] = None, force: bool = False) -> None:
    who = (who or me()).strip()
    if not who:
        raise SystemExit("[error] 이 PC 의 이름이 없습니다 — 계정 탭에서 「내 이름」을 적거나 local.json 에 {\"me\": \"이름\"}")
    for lid in lids:
        cur = get(job, lid)
        if cur.get("who") and cur["who"] != who and not force:
            warn(f"{lid} 는 {cur['who']} 님 담당입니다 — 건너뜀(바꾸려면 --force)")
            continue
        doc = cur if cur.get("who") == who else {"status": "claimed"}
        doc.update({"who": who, "claimed_at": doc.get("claimed_at") or time.strftime("%Y-%m-%d %H:%M:%S")})
        _write(job, lid, doc)
        log(f"{lid} → {who} 담당")


def release(job: Job, lids: List[str], force: bool = False) -> None:
    for lid in lids:
        cur = get(job, lid)
        if cur.get("who") and cur["who"] != me() and not force:
            warn(f"{lid} 는 {cur['who']} 님 담당입니다 — 놓을 수 없습니다(--force)")
            continue
        f = _dir(job) / f"{lid}.json"
        if f.exists():
            f.unlink()
            log(f"{lid} 담당 해제")


def scope(job: Job, only: Optional[List[str]], all_ids: List[str], force: bool = False) -> Optional[List[str]]:
    """이번 실행에서 돌릴 강. None = 전부(분담을 안 쓰는 잡)."""
    claims = all_claims(job)
    if not claims:
        return only
    mine = me()
    wanted = only or [lid for lid in all_ids if (claims.get(lid) or {}).get("who") == mine]
    if not only:
        log(f"분담 중인 잡입니다 — 내 담당({mine or '이름 없음'})만 돕니다: {', '.join(wanted) or '없음'}")
    out = []
    for lid in wanted:
        who = (claims.get(lid) or {}).get("who")
        if who and who != mine and not force:
            warn(f"{lid} 는 {who} 님 담당 — 건너뜀(--force 로 덮어씀)")
            continue
        out.append(lid)
    return out


def mark(job: Job, lid: str, status: str, **extra: Any) -> None:
    """진행 상태를 담당 파일에 남긴다(맡은 사람이 없으면 남기지 않는다 — 혼자 쓰는 잡은 조용히)."""
    cur = get(job, lid)
    if not cur.get("who"):
        return
    if ORDER.index(status) >= ORDER.index(cur.get("status", "claimed")) or extra:
        cur["status"] = status if ORDER.index(status) >= ORDER.index(cur.get("status", "claimed")) else cur["status"]
    cur.update(extra)
    _write(job, lid, cur)


def sync_from_state(job: Job, lids: Optional[List[str]] = None) -> None:
    """state.json(이 PC 진행)을 보고 내 담당 강의 상태를 올린다."""
    from longform.report import rows
    for r in rows(job):
        if lids and r["id"] not in lids:
            continue
        c = get(job, r["id"])
        if not c.get("who") or c["who"] != me():
            continue
        if r["yt"]:
            mark(job, r["id"], "published", yt={"id": r["yt"], "url": f"https://youtu.be/{r['yt']}"})
        elif r["video"]:
            mark(job, r["id"], "stitched")
        elif r["render"] >= r["n"]:
            mark(job, r["id"], "rendered")
        elif r["compose"] >= r["n"]:
            mark(job, r["id"], "composed")
