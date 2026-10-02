"""대화 + 스타일 카탈로그 라우트."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..core import constants
from ..services import codex_text, prompt_spec

router = APIRouter(prefix="/api/builder", tags=["builder-chat"])


class ChatMessage(BaseModel):
    role: str                       # "user" | "assistant"
    content: str = ""               # 텍스트
    images: list[str] = []          # data URL 리스트 (user 메시지에만)


class ChatRequest(BaseModel):
    messages: list[ChatMessage]     # 전체 대화 히스토리 (MVP: 클라이언트 보관)
    finalize: bool = False          # '프롬프트 마감' — 최종 프롬프트 확정 출력


@router.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    """텍스트는 Codex(ChatGPT)로, 이미지가 있으면 먼저 비전으로 분석 후 텍스트가 응답."""
    history: list[dict[str, str]] = [
        {"role": "system", "content": prompt_spec.build_system_prompt()}
    ]
    vision_used = False

    for msg in req.messages:
        if msg.role == "user" and msg.images:
            # 이미지 → 비전 모델로 텍스트 분석 추출
            try:
                analysis = codex_text.analyze_image(msg.images, note=msg.content)
                vision_used = True
            except Exception as exc:  # noqa: BLE001
                analysis = f"(이미지 분석 실패: {codex_text.friendly_error(exc)})"
            user_text = msg.content.strip() or "(첨부한 레퍼런스 이미지를 참고해줘)"
            history.append({
                "role": "user",
                "content": (
                    f"{user_text}\n\n[첨부 레퍼런스 이미지 분석 결과]\n{analysis}"
                ),
            })
        else:
            history.append({"role": msg.role, "content": msg.content})

    if req.finalize:
        history.append({"role": "system", "content": prompt_spec.build_finalize_prompt()})

    try:
        reply = codex_text.chat_reply(history)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": codex_text.friendly_error(exc)}

    if not reply.strip():
        return {"ok": False, "error": "모델이 빈 응답을 반환했습니다. 다시 시도하거나, 컷 수를 줄이거나 원고를 짧게 해보세요."}
    return {"ok": True, "reply": reply, "vision_used": vision_used}


@router.get("/style-catalog")
def style_catalog() -> dict[str, Any]:
    path = constants.PROMPTS_DIR / "style_catalog.md"
    try:
        return {"ok": True, "markdown": path.read_text(encoding="utf-8")}
    except OSError:
        return {"ok": False, "markdown": ""}
