"""텍스트/비전 엔진 — 프롬프트 빌더 전용 (키리스, ChatGPT OAuth 공유).

이미지 스튜디오와 **동일한 로그인**(`~/.codex/auth.json` 의 ChatGPT OAuth 토큰)으로
`https://chatgpt.com/backend-api/codex/responses` 에 직접 POST 한다. 모델은 추론 모델
(gpt-5.5)이고, 멀티모달이라 텍스트 대화와 이미지 분석(비전)을 모두 처리한다. 별도 API
키(LiteLLM/MiMo)가 필요 없다 — 로그인 하나로 빌더와 스튜디오가 함께 동작한다.

토큰 로드/갱신·헤더·SSE 스트림 파싱은 `codex_image` 의 검증된 메커니즘을 재사용한다.
호출부(routes)는 blocking 함수를 asyncio.to_thread 로 감싸 이벤트루프를 막지 않는다.
"""
from __future__ import annotations

import time
import urllib.error
from typing import Any, Dict, List, Optional

from .codex_image import (
    CODEX_MODEL,
    ImageEngineError,
    NotAuthenticated,
    _build_headers,
    _detect_codex_version,
    _extract_tokens,
    _load_auth,
    _persist_refreshed_auth,
    _refresh_access_token,
    _stream,
)

JsonDict = Dict[str, Any]

CHAT_TOTAL_TIMEOUT = 180.0
CHAT_STALL_TIMEOUT = 90.0

_VISION_INSTRUCTION = (
    "너는 이미지 분석가다. 첨부된 레퍼런스 이미지를 분석해 카드뉴스/표지/배너 제작에 쓸 "
    "프롬프트 재료를 한국어로 추출하라. 다음 항목을 간결한 글머리표로 정리한다: "
    "① 전체 인상/무드 ② 주요 색상(가능하면 HEX 추정) ③ 구도/레이아웃 ④ 조명/질감 "
    "⑤ 텍스트(헤드라인·보조문구) 배치와 폰트 느낌 ⑥ 가장 가까운 스타일(스타일 카탈로그 기준) 추정. "
    "이미지에 없는 내용은 지어내지 말 것."
)


# ── 사용자 친화 에러 메시지 ──────────────────────────────────────────────────
def friendly_error(exc: Exception) -> str:
    if isinstance(exc, NotAuthenticated):
        return (
            "ChatGPT 로그인이 필요합니다. 터미널에서 `codex login` 으로 "
            "구독 계정에 로그인한 뒤 다시 시도하세요."
        )
    msg = str(exc)
    low = msg.lower()
    status = getattr(exc, "status", None)
    if status == 401 or "401" in msg:
        return "인증이 만료되었습니다 — `codex login` 으로 다시 로그인하세요."
    if status == 429 or "429" in msg or "rate" in low:
        return "요청이 많아 잠시 제한되었습니다. 잠시 후 다시 시도하세요."
    if "timeout" in low or "지연" in msg or "중단" in msg:
        return "응답이 지연/중단되었습니다. 컷 수를 줄이거나 원고를 짧게 해 다시 시도하세요."
    if "network" in low or "네트워크" in msg:
        return "네트워크 오류입니다. 인터넷 연결을 확인하세요."
    return f"호출 오류: {msg[:300]}"


# ── 텍스트 응답 SSE 파싱 ─────────────────────────────────────────────────────
def _post_for_text(headers: dict, payload: JsonDict,
                   deadline: float, stall_timeout: float) -> str:
    chunks: List[str] = []
    final_text: Optional[str] = None
    failure_detail: Optional[str] = None
    seen: dict = {}
    try:
        for evt in _stream(headers, payload, deadline, stall_timeout):
            t = evt.get("type", "?")
            seen[t] = seen.get(t, 0) + 1
            if t == "response.output_text.delta":
                d = evt.get("delta")
                if isinstance(d, str):
                    chunks.append(d)
            elif t == "response.output_text.done":
                txt = evt.get("text")
                if isinstance(txt, str) and txt:
                    final_text = txt
            elif t == "response.output_item.done":
                item = evt.get("item")
                if isinstance(item, dict) and item.get("type") == "message":
                    buf = _text_from_content(item.get("content"))
                    if buf:
                        final_text = buf
            elif t in ("response.completed", "response.done"):
                resp = evt.get("response")
                if isinstance(resp, dict):
                    for it in resp.get("output", []) or []:
                        if isinstance(it, dict) and it.get("type") == "message":
                            buf = _text_from_content(it.get("content"))
                            if buf:
                                final_text = buf
            elif t in ("error", "response.failed"):
                detail = None
                if isinstance(evt.get("response"), dict):
                    err = evt["response"].get("error")
                    if isinstance(err, dict):
                        detail = err.get("message") or err.get("code")
                if isinstance(evt.get("error"), dict):
                    detail = evt["error"].get("message") or detail
                failure_detail = str(detail or evt.get("message") or evt.get("code") or "")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="ignore")
        raise ImageEngineError(f"HTTP {e.code}: {body_text[:400]}", status=e.code)
    except (TimeoutError, ConnectionError):
        raise ImageEngineError("백엔드 응답이 지연/중단되었습니다. 다시 시도하세요.")
    except urllib.error.URLError as e:
        raise ImageEngineError(f"네트워크 오류: {e.reason}")

    text = (final_text or "".join(chunks)).strip()
    if not text:
        if failure_detail:
            raise ImageEngineError(f"생성 실패: {failure_detail}")
        types_seen = ", ".join(sorted(seen)) or "(none)"
        raise ImageEngineError(f"빈 응답을 받았습니다. (events: {types_seen})")
    return text


def _text_from_content(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    buf: List[str] = []
    for p in content:
        if isinstance(p, dict) and p.get("type") in ("output_text", "text", "input_text"):
            if isinstance(p.get("text"), str):
                buf.append(p["text"])
    return "".join(buf)


# ── 페이로드 빌드 ────────────────────────────────────────────────────────────
def _build_payload(instructions: str, content: List[JsonDict],
                   verbosity: str = "medium") -> JsonDict:
    return {
        "model": CODEX_MODEL,
        "stream": True,
        "instructions": instructions,
        "input": [{"type": "message", "role": "user", "content": content}],
        "store": False,
        "reasoning": {"effort": "low", "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
        "text": {"verbosity": verbosity},
    }


# ── codex 호출 (401 시 토큰 갱신 후 1회 재시도) ──────────────────────────────
def _run(payload: JsonDict) -> str:
    auth = _load_auth()
    access, account_id, refresh = _extract_tokens(auth)
    if not access:
        raise NotAuthenticated(
            "~/.codex/auth.json 에 ChatGPT OAuth access_token 이 없습니다. "
            "`codex login` 으로 구독 계정에 로그인하세요."
        )
    version = _detect_codex_version()
    deadline = time.monotonic() + CHAT_TOTAL_TIMEOUT

    def _attempt(token: str) -> str:
        headers = _build_headers(token, account_id, version)
        return _post_for_text(headers, payload, deadline, CHAT_STALL_TIMEOUT)

    try:
        return _attempt(access)
    except ImageEngineError as e:
        if e.status == 401 and refresh:
            refreshed = _refresh_access_token(refresh)
            new_access = refreshed.get("access_token")
            if isinstance(new_access, str) and new_access:
                _persist_refreshed_auth(auth, refreshed)
                return _attempt(new_access)
        raise


# ── 공개 API ─────────────────────────────────────────────────────────────────
def chat_reply(messages: List[Dict[str, Any]]) -> str:
    """messages: OpenAI chat 포맷(system/user/assistant, content=str).

    system 메시지는 instructions 로, 나머지는 대화 기록(transcript)으로 묶어
    Responses API 의 단일 user 입력으로 전달한다(역할·콘텐츠 타입 호환 이슈 회피).
    """
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    instructions = "\n\n".join(p for p in system_parts if p) or "You are a helpful assistant."

    convo = [m for m in messages if m.get("role") in ("user", "assistant")]
    lines: List[str] = []
    for m in convo:
        tag = "사용자" if m.get("role") == "user" else "어시스턴트"
        lines.append(f"### {tag}\n{m.get('content', '')}".strip())
    transcript = "\n\n".join(lines)
    user_text = (
        "다음은 지금까지의 대화 기록이다. 마지막 사용자 발화에 대해 "
        "어시스턴트로서 이어질 답변만 생성하라(역할 머리말은 출력하지 말 것).\n\n"
        f"{transcript}"
    )
    payload = _build_payload(instructions, [{"type": "input_text", "text": user_text}])
    return _run(payload)


def analyze_image(images: List[str], note: str = "") -> str:
    """images: data:image/...;base64,... data URL 리스트. 분석 텍스트를 반환."""
    content: List[JsonDict] = [{"type": "input_text", "text": _VISION_INSTRUCTION}]
    if note.strip():
        content.append({"type": "input_text", "text": f"사용자 메모: {note.strip()}"})
    for url in images:
        if isinstance(url, str) and url.startswith("data:"):
            content.append({"type": "input_image", "image_url": url})
    payload = _build_payload("너는 이미지 분석가다.", content, verbosity="medium")
    return _run(payload)
