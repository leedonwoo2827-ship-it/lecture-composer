"""이미지 엔진 — 생성 / 편집 / 병합.

주 엔진 = **codex (키리스)**: `~/.codex/auth.json` 의 ChatGPT OAuth 토큰으로
`https://chatgpt.com/backend-api/codex/responses` 에 직접 POST 한다. 요청에 싣는 모델은
**추론 모델(gpt-5.5)**이고, 그림은 그 안의 `image_generation` 툴이 만든다. 툴이 쓰는
이미지 모델은 **gpt-image-2** — 응답에는 이름이 안 실리지만 OpenAI 문서에 이미지 생성
모델이 그것뿐이고 동작(16의 배수·1:3~3:1·최대 4K)도 일치한다.
API 키가 필요 없고 사용량은 사용자의 ChatGPT 구독 한도에서 차감된다.

> 주의: codex/responses 는 Codex CLI 가 쓰는 내부(비공식) 엔드포인트다. 구글/오픈AI 의
> 공개 SDK 가 아니므로 변경될 수 있다. 구현은 오픈소스 chatgpt-imagegen 의 검증된
> 메커니즘(토큰 로드/갱신·헤더·페이로드·SSE 파싱)을 차용했다.

호출부(routes)는 blocking 함수를 asyncio.to_thread 로 감싸 이벤트루프를 막지 않는다.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

from ..core.atomic_io import atomic_write_json

# ── 상수 (chatgpt-imagegen 차용) ─────────────────────────────────────────────
CODEX_BACKEND = "https://chatgpt.com/backend-api/codex/responses"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # Codex CLI 공개 client id
FALLBACK_VERSION = "0.130.0"
FALLBACK_UA = f"codex_cli_rs/{FALLBACK_VERSION} (Windows 11; x64) image-studio"
AUTH_PATH = Path(os.environ.get("CODEX_AUTH_PATH", str(Path.home() / ".codex" / "auth.json")))
VERSION_PATH = Path.home() / ".codex" / "version.json"

CODEX_MODEL = os.environ.get("CODEX_IMAGE_MODEL", "gpt-5.5")

# image_generation 툴이 받는 크기 규칙(공식 문서 기준).
#   · 가로·세로 모두 **16의 배수**
#   · 비율은 **1:3 ~ 3:1** 사이
#   · 최대 3840x2160 (2560x1440 초과는 실험적)
#
# 예전에 이 파일은 "1024x1024 · 1536x1024 · 1024x1536 셋뿐"으로 알고 막아 뒀는데,
# 그건 구형 gpt-image-1 기준이라 지금 모델에는 맞지 않는다. 그 탓에 16:9 를 고르면
# 조용히 3:2 로 바뀌어 나갔다.
#
# 2026-08-29 실측 — 16:9·9:16·4:3·21:9 모두 그대로 생성됐다:
#     1536x864  요청 → 1672x941   (16:9)
#     864x1536  요청 → 941x1672   (9:16)
#     1408x1056 요청 → 1448x1086  (4:3)
#     1536x656  요청 → 1918x820   (21:9)
# 보다시피 **비율은 지키지만 해상도는 백엔드가 자기 기준으로 다시 잡는다.**
# size 는 정확한 픽셀 지정이 아니라 사실상 비율 지정에 가깝다.
CODEX_MAX_W, CODEX_MAX_H = 3840, 2160

# 배경을 불투명으로 못박는다. image_generation 툴의 background 기본값이 "auto" 라서
# 모델이 그때그때 정하고, 간혹 알파(투명)로 비워 버린다. 투명 PNG 는 보는 쪽 배경색이
# 그대로 비치므로 — 다크모드 탐색기, 어두운 PPT 마스터에서 글자가 배경에 묻힌다.
# 프롬프트에 "바탕을 칠하라"를 적어도 알파로 비우면 그대로 통과하니 여기서 막아야 한다.
# (2026-08-17 실측: 제21장 32장 중 003·014 두 장만 RGBA 로 나왔다.)
# 잘라내기용 투명 PNG 가 필요하면 CODEX_IMAGE_BACKGROUND=transparent 로 돌린다.
CODEX_BACKGROUND = os.environ.get("CODEX_IMAGE_BACKGROUND", "opaque")
DEFAULT_TOTAL_TIMEOUT = int(os.environ.get("IMAGE_TIMEOUT", "300"))
DEFAULT_STALL_TIMEOUT = 120.0
REF_B64_SOFT_CAP = 8 * 1024 * 1024  # 참조 이미지 base64 상한(초과 시 경고만)

JsonDict = dict


class ImageEngineError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class NotAuthenticated(ImageEngineError):
    pass


# ── 토큰 로드/추출/갱신 ───────────────────────────────────────────────────────
def _load_auth() -> JsonDict:
    try:
        with open(AUTH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        raise NotAuthenticated(
            "~/.codex/auth.json 이 없습니다. 터미널에서 `codex login` 으로 "
            "ChatGPT 계정에 로그인하세요."
        )
    except Exception as e:
        raise ImageEngineError(f"auth.json 읽기 실패: {e}")


def _extract_tokens(auth: JsonDict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    tokens = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else {}
    access = tokens.get("access_token") if isinstance(tokens.get("access_token"), str) else None
    account_id = tokens.get("account_id") if isinstance(tokens.get("account_id"), str) else None
    refresh = tokens.get("refresh_token") if isinstance(tokens.get("refresh_token"), str) else None
    return access, account_id, refresh


def _refresh_access_token(refresh_token: str, timeout: int = 30) -> JsonDict:
    data = urllib.parse.urlencode({
        "client_id": OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "openid profile email",
    }).encode("utf-8")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL, data=data, method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": FALLBACK_UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        oauth_err = ""
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
                oauth_err = parsed["error"]
        except Exception:
            pass
        if oauth_err == "invalid_grant":
            raise NotAuthenticated(
                "refresh_token 이 만료되었습니다 — `codex login` 으로 다시 로그인하세요.",
                status=e.code,
            )
        raise ImageEngineError(
            f"토큰 갱신 실패: HTTP {e.code}" + (f" ({oauth_err})" if oauth_err else ""),
            status=e.code,
        )


def _persist_refreshed_auth(original: JsonDict, refreshed: JsonDict) -> None:
    tokens = original.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
        original["tokens"] = tokens
    for k in ("access_token", "refresh_token", "id_token"):
        if isinstance(refreshed.get(k), str):
            tokens[k] = refreshed[k]
    original["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        atomic_write_json(str(AUTH_PATH), original, indent=2)
    except Exception:
        pass  # 갱신 실패해도 이번 요청은 새 토큰으로 진행


# ── 헤더/버전 ────────────────────────────────────────────────────────────────
def _detect_codex_version() -> str:
    def parse(v: str):
        return tuple(int(p) for p in v.split(".")) if re.fullmatch(r"\d+\.\d+\.\d+", v) else None

    floor = FALLBACK_VERSION
    try:
        if VERSION_PATH.exists():
            data = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
            v = data.get("latest_version")
            if isinstance(v, str):
                pv, pf = parse(v), parse(floor)
                if pv and pf:
                    return v if pv >= pf else floor
                if pv:
                    return v
    except Exception:
        pass
    return floor


def _build_headers(token: str, account_id: Optional[str], version: str) -> dict:
    sid = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Connection": "Keep-Alive",
        "version": version,
        "session_id": sid,
        "x-client-request-id": sid,
        "User-Agent": f"codex_cli_rs/{version} (Windows 11; x64) image-studio",
        "originator": "codex_cli_rs",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


# ── 참조 이미지 ───────────────────────────────────────────────────────────────
def _sniff_mime(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _encode_ref(raw: bytes) -> Tuple[str, str]:
    mime = _sniff_mime(raw) or "image/png"
    return base64.b64encode(raw).decode("ascii"), mime


# ── 페이로드 ──────────────────────────────────────────────────────────────────
def _build_user_text(prompt: str, size: str, output_format: str, is_edit: bool) -> str:
    if is_edit:
        text = (
            "Use the image_generation tool to edit the attached reference image(s). "
            "Treat the reference as the canonical subject — reproduce its exact pattern, "
            "colours, and texture faithfully; do not redesign the subject itself. "
            f"Request: {prompt}. Output format: {output_format}."
        )
    else:
        text = (
            "Use the image_generation tool to render the following. "
            f"Request: {prompt}. Output format: {output_format}."
        )
    if size and size != "auto":
        text += f" Size: {size}."
    text += " Do not include explanatory text — produce only the image."
    return text


def _build_payload(prompt: str, size: str, output_format: str, model: str,
                   refs: Optional[List[Tuple[str, str]]]) -> JsonDict:
    is_edit = bool(refs)
    user_text = _build_user_text(prompt, size, output_format, is_edit)

    image_tool: JsonDict = {"type": "image_generation", "output_format": output_format}
    if CODEX_BACKGROUND:
        image_tool["background"] = CODEX_BACKGROUND
    if size and size != "auto":
        image_tool["size"] = size

    if refs:
        content = [
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
            for (b64, mime) in refs
        ]
        content.append({"type": "input_text", "text": user_text})
        tool_choice = "required"
    else:
        content = [{"type": "input_text", "text": user_text}]
        tool_choice = "auto"

    return {
        "model": model,
        "stream": True,
        "instructions": "You are an image generation assistant.",
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [image_tool],
        "tool_choice": tool_choice,
        "parallel_tool_calls": False,
        "store": False,
        "reasoning": {"effort": "low", "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
        "text": {"verbosity": "low"},
    }


# ── SSE 스트림 파싱 ───────────────────────────────────────────────────────────
def _loosen_read_timeout(resp: Any, timeout: float) -> None:
    try:
        resp.fp.raw._sock.settimeout(timeout)  # type: ignore[attr-defined]
    except Exception:
        pass


def _stream(headers: dict, body: JsonDict, deadline: float, stall_timeout: float) -> Iterator[JsonDict]:
    req = urllib.request.Request(
        CODEX_BACKEND, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST",
    )
    initial = max(1.0, min(30.0, deadline - time.monotonic()))
    resp = urllib.request.urlopen(req, timeout=initial)
    _loosen_read_timeout(resp, min(stall_timeout, max(1.0, deadline - time.monotonic())))
    try:
        data_buf: List[str] = []
        for raw in resp:
            if time.monotonic() >= deadline:
                raise ImageEngineError("스트림이 전체 시간 예산을 초과했습니다.")
            line = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            if line == "":
                if not data_buf:
                    continue
                payload = "\n".join(data_buf)
                data_buf = []
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except Exception:
                    pass
                continue
            if line.startswith(":") or line.startswith("event:"):
                continue
            if line.startswith("data:"):
                chunk = line[len("data:"):]
                if chunk.startswith(" "):
                    chunk = chunk[1:]
                data_buf.append(chunk)
    finally:
        resp.close()


def _post_for_image(headers: dict, payload: JsonDict,
                    deadline: float, stall_timeout: float) -> Tuple[bytes, JsonDict]:
    image_b64: Optional[str] = None
    item_meta: JsonDict = {}
    seen: dict = {}
    failure_detail: Optional[str] = None
    try:
        for evt in _stream(headers, payload, deadline, stall_timeout):
            t = evt.get("type", "?")
            seen[t] = seen.get(t, 0) + 1
            if t in ("error", "response.failed"):
                detail = None
                if isinstance(evt.get("response"), dict):
                    err = evt["response"].get("error")
                    if isinstance(err, dict):
                        detail = err.get("message") or err.get("code")
                if isinstance(evt.get("error"), dict):
                    detail = evt["error"].get("message") or detail
                failure_detail = str(detail or evt.get("message") or evt.get("code") or "")
            if t == "response.output_item.done":
                item = evt.get("item")
                if isinstance(item, dict) and item.get("type") == "image_generation_call":
                    if isinstance(item.get("result"), str):
                        image_b64 = item["result"]
                        item_meta = {k: v for k, v in item.items() if k != "result"}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="ignore")
        raise ImageEngineError(f"HTTP {e.code}: {body_text[:400]}", status=e.code)
    except (TimeoutError, ConnectionError):
        raise ImageEngineError("이미지 백엔드 응답이 지연/중단되었습니다. 다시 시도하세요.")
    except urllib.error.URLError as e:
        raise ImageEngineError(f"네트워크 오류: {e.reason}")

    if not image_b64:
        types_seen = ", ".join(sorted(seen)) or "(none)"
        if failure_detail:
            raise ImageEngineError(f"생성 실패: {failure_detail} (events: {types_seen})")
        raise ImageEngineError(f"이미지가 반환되지 않았습니다. (events: {types_seen})")
    try:
        return base64.b64decode(image_b64, validate=True), item_meta
    except Exception:
        raise ImageEngineError("백엔드가 잘못된 base64 를 반환했습니다.")


def _check_size(size: str) -> None:
    """보내기 전에 크기 규칙을 확인한다 — 백엔드 오류 문구가 불친절해서."""
    if not size or size == "auto":
        return
    m = re.fullmatch(r"(\d+)\s*[xX]\s*(\d+)", size.strip())
    if not m:
        raise ImageEngineError(f"크기 형식이 잘못됐습니다: {size} (예: 1536x1024)")
    w, h = int(m.group(1)), int(m.group(2))
    if w % 16 or h % 16:
        raise ImageEngineError(f"{size} — 가로·세로 모두 16의 배수여야 합니다.")
    if not (1 / 3) <= (w / h) <= 3:
        raise ImageEngineError(f"{size} — 비율은 1:3 에서 3:1 사이여야 합니다.")
    if w > CODEX_MAX_W or h > CODEX_MAX_H:
        raise ImageEngineError(
            f"{size} — 최대 {CODEX_MAX_W}x{CODEX_MAX_H} 까지입니다.")


# ── codex 엔진 진입점 (401 시 갱신 후 1회 재시도) ─────────────────────────────
def _run_codex(prompt: str, size: str, output_format: str,
               refs: Optional[List[bytes]]) -> Tuple[bytes, JsonDict]:
    _check_size(size)
    auth = _load_auth()
    access, account_id, refresh = _extract_tokens(auth)
    if not access:
        raise NotAuthenticated(
            "~/.codex/auth.json 에 ChatGPT OAuth access_token 이 없습니다. "
            "`codex login` 으로 구독 계정에 로그인하세요. (OPENAI_API_KEY 로는 대체 불가)"
        )

    loaded_refs = None
    if refs:
        loaded_refs = [_encode_ref(r) for r in refs]

    version = _detect_codex_version()
    payload = _build_payload(prompt, size, output_format, CODEX_MODEL, loaded_refs)
    deadline = time.monotonic() + DEFAULT_TOTAL_TIMEOUT

    def _attempt(token: str) -> Tuple[bytes, JsonDict]:
        headers = _build_headers(token, account_id, version)
        return _post_for_image(headers, payload, deadline, DEFAULT_STALL_TIMEOUT)

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


# ── 공개 API ──────────────────────────────────────────────────────────────────
def generate_image(prompt: str, *, size: str = "auto",
                   refs: Optional[List[bytes]] = None,
                   settings: Optional[dict] = None) -> Tuple[bytes, dict]:
    """프롬프트(+ 선택 참조 이미지)로 이미지 1장을 생성/편집/병합한다.

    refs 가 있으면 편집/병합 경로(image-to-image). 반환: (png_bytes, meta).
    """
    settings = settings or {}
    output_format = settings.get("default_format", "png")
    img, meta = _run_codex(prompt, size, output_format, refs)
    meta["engine"] = "codex"
    meta["model"] = CODEX_MODEL
    return img, meta
