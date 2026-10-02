"""인증/상태 라우트 — codex(ChatGPT) 로그인 상태."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import codex_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def auth_status():
    st = codex_auth.status()
    st["ready"] = st["authenticated"]
    return st


@router.post("/login")
async def auth_login():
    """새 cmd 창에서 `codex login` 실행 — 계정 로그인/변경(다른 계정으로 다시 로그인)."""
    res = codex_auth.launch_console(codex_auth.login_terminal_cmd())
    res["message"] = "새 창에서 ChatGPT 로그인을 진행하세요. 완료 후 ‘상태 새로고침’을 누르세요."
    return res


@router.post("/logout")
async def auth_logout():
    """새 cmd 창에서 `codex logout` 실행 — 현재 계정 로그아웃."""
    res = codex_auth.launch_console(codex_auth.logout_terminal_cmd())
    res["message"] = "새 창에서 로그아웃이 진행됩니다. 완료 후 ‘상태 새로고침’을 누르세요."
    return res
