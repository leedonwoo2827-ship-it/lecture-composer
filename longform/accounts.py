"""계정·로그인을 한곳에 — Claude(집필) · codex(배경 그림, 계정 여러 개) · YouTube(게시).

codex 계정 칸(slot)
    profiles/codex/<칸>/auth.json      칸마다 따로 로그인한다(CODEX_HOME=그 폴더로 `codex login`)
    profiles/codex/active.txt          지금 쓰는 칸 이름
    렌더 단계는 엔진에 CODEX_AUTH_PATH=<칸>/auth.json 을 넘긴다 → 전역 ~/.codex 를 갈아 끼우지 않는다.
    (엔진 imgstudio/services/codex_image.py 가 이 변수를 읽고, 토큰 갱신도 그 파일에 다시 쓴다)
    칸이 하나도 없으면 이 PC 의 기본 로그인(~/.codex/auth.json)을 쓴다.

사용량 공유
    logs/usage.jsonl 에 칸마다 몇 장을 구웠고 몇 번 한도에 걸렸는지 남긴다 → 계정 탭이 칸별로 합산해 보여 준다.
    렌더 중 한도에 걸려 그림이 비면, 다른 칸으로 바꿔 **한 번 더** 굽는다(accounts.codex_failover).

★ profiles/ 는 깃에 올라가지 않는다(로그인 토큰·쿠키).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import REPO

CODEX_DIR = REPO / "profiles" / "codex"
ACTIVE = CODEX_DIR / "active.txt"
USAGE = REPO / "logs" / "usage.jsonl"
DEFAULT_AUTH = Path.home() / ".codex" / "auth.json"


# ── 공통 ──────────────────────────────────────────────────────────────────
def _jwt_email(token: str) -> Optional[str]:
    try:
        part = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return data.get("email") or (data.get("https://api.openai.com/profile") or {}).get("email")
    except Exception:
        return None


def _auth_info(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {"logged_in": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"logged_in": False, "problem": "auth.json 을 읽을 수 없습니다"}
    t = d.get("tokens") or {}
    email = _jwt_email(t.get("id_token") or "") or _jwt_email(t.get("access_token") or "")
    return {"logged_in": bool(t.get("access_token")), "email": email, "last_refresh": d.get("last_refresh")}


def new_console(args: List[str], env: Optional[Dict[str, str]] = None) -> None:
    """새 콘솔 창에서 실행(로그인은 브라우저를 열고 입력을 기다리므로 창이 보여야 한다)."""
    e = dict(os.environ, **(env or {}))
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/k", *args], env=e, creationflags=0x00000010)  # CREATE_NEW_CONSOLE
    else:
        subprocess.Popen(args, env=e)


def codex_bin() -> str:
    for c in ("codex", "codex.cmd"):
        w = shutil.which(c)
        if w:
            return w
    appdata = os.environ.get("APPDATA", "")
    p = Path(appdata) / "npm" / "codex.cmd"
    if p.exists():
        return str(p)
    raise SystemExit("[error] codex CLI 가 없습니다 — npm i -g @openai/codex")


# ── codex 칸 ──────────────────────────────────────────────────────────────
def slots() -> List[str]:
    if not CODEX_DIR.exists():
        return []
    return sorted(d.name for d in CODEX_DIR.iterdir() if d.is_dir())


def active_slot() -> Optional[str]:
    s = ACTIVE.read_text(encoding="utf-8").strip() if ACTIVE.exists() else ""
    have = slots()
    if s in have:
        return s
    ready = [x for x in have if _auth_info(CODEX_DIR / x / "auth.json").get("logged_in")]
    return ready[0] if ready else None


def set_active(slot: str) -> None:
    if slot not in slots():
        raise SystemExit(f"[error] 없는 칸: {slot}")
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE.write_text(slot, encoding="utf-8")


def add_slot(slot: str) -> Path:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", slot or ""):
        raise SystemExit("[error] 칸 이름은 영문·숫자·_- 1~30자 (예: main, sub)")
    d = CODEX_DIR / slot
    d.mkdir(parents=True, exist_ok=True)
    return d


def login_slot(slot: str) -> None:
    d = add_slot(slot)
    new_console([codex_bin(), "login"], {"CODEX_HOME": str(d)})


def copy_default_into(slot: str) -> None:
    """이미 이 PC 에 `codex login` 해 둔 계정을 칸으로 저장(다시 로그인하지 않아도 되게)."""
    if not DEFAULT_AUTH.exists():
        raise SystemExit("[error] 이 PC 의 기본 codex 로그인(~/.codex/auth.json)이 없습니다")
    d = add_slot(slot)
    shutil.copy2(DEFAULT_AUTH, d / "auth.json")


def remove_slot(slot: str) -> None:
    d = CODEX_DIR / slot
    if d.exists():
        shutil.rmtree(d)


def auth_path(slot: Optional[str] = None) -> Optional[Path]:
    """렌더에 넘길 auth.json — 칸이 없으면 None(엔진 기본 ~/.codex 사용)."""
    s = slot or active_slot()
    return (CODEX_DIR / s / "auth.json") if s else None


def next_slot(current: Optional[str]) -> Optional[str]:
    ready = [x for x in slots() if _auth_info(CODEX_DIR / x / "auth.json").get("logged_in")]
    if not ready:
        return None
    if current not in ready:
        return ready[0]
    i = ready.index(current)
    return ready[(i + 1) % len(ready)] if len(ready) > 1 else None


# ── 사용량 ────────────────────────────────────────────────────────────────
def record_usage(slot: Optional[str], made: int, failed: int, limited: bool, where: str) -> None:
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    email = _auth_info(auth_path(slot) or DEFAULT_AUTH).get("email") if (slot or DEFAULT_AUTH.exists()) else None
    row = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "slot": slot or "(기본)", "email": email,
           "made": made, "failed": failed, "limited": limited, "where": where}
    with USAGE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def usage_summary() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not USAGE.exists():
        return out
    today = time.strftime("%Y-%m-%d")
    for line in USAGE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        s = out.setdefault(r.get("slot") or "(기본)", {"made": 0, "failed": 0, "limited": 0, "today": 0, "last": ""})
        s["made"] += int(r.get("made") or 0)
        s["failed"] += int(r.get("failed") or 0)
        s["limited"] += 1 if r.get("limited") else 0
        if (r.get("at") or "").startswith(today):
            s["today"] += int(r.get("made") or 0)
        s["last"] = r.get("at") or s["last"]
    return out


# ── 전체 상태 ──────────────────────────────────────────────────────────────
def status(job=None) -> Dict[str, Any]:
    us = usage_summary()
    act = active_slot()
    codex_rows = [{"slot": s, "active": s == act, **_auth_info(CODEX_DIR / s / "auth.json"),
                   "usage": us.get(s, {})} for s in slots()]
    default = {"slot": "(기본)", "active": act is None, **_auth_info(DEFAULT_AUTH), "usage": us.get("(기본)", {})}

    claude = {"path": None}
    try:
        from longform.s2_manuscript import find_claude
        from longform.config import load_job
        from longform.config import default_job
        claude["path"] = find_claude(job or load_job(default_job()))
    except SystemExit as e:
        claude["problem"] = str(e)
    cred = Path.home() / ".claude" / ".credentials.json"
    claude["logged_in"] = cred.exists() or bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))

    yt: Dict[str, Any] = {}
    if job is not None:
        prof = job.path(job.get("youtube.profile", f"profiles/{job.name}"))
        cookies = any((prof / p).exists() for p in ("Default/Network/Cookies", "Default/Cookies")) if prof else False
        state = {}
        sf = job.dir / "state.json"
        if sf.exists():
            try:
                state = json.loads(sf.read_text(encoding="utf-8"))
            except Exception:
                pass
        yt = {"handle": job.get("youtube.handle"), "profile": str(prof) if prof else "",
              "logged_in": cookies, "channel_id": job.get("youtube.channel_id") or state.get("channel_id") or "",
              "visibility": job.get("youtube.visibility"), "playlist": job.get("youtube.playlist")}
    return {"claude": claude, "codex": {"active": act, "slots": codex_rows, "default": default,
                                         "failover": True}, "youtube": yt}
