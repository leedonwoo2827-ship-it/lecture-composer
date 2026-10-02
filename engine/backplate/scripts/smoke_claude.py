"""M2 스모크 — Claude Code 구독 OAuth 로 (1) 텍스트 (2) 비전 (3) 구조화 출력이 되는가.

이 프로젝트 전체에서 가장 위험한 미지수를 여기서 먼저 끝낸다.
계정 내 기존 OAuth 전례(codex exec / agy --print / wham)는 전부 text-in/text-out 이고,
**키 없이 이미지를 모델에 보내는 전례가 없다.** 그래서 비전 경로를 두 가지로 시험한다.

  A. inline   — base64 image 블록을 streaming-input 으로 보낸다 (문서화된 경로).
  B. read     — 프레임을 디스크에 두고 에이전트에게 Read 시킨다 (툴 왕복 비용, 대신 안전).

A 가 한 번에 통과하면 A. 조금이라도 불안정하면 B.
결과는 showcase.config.json 의 vision_mode 값을 무엇으로 둘지 결정한다.

사용:
    .venv-app\\Scripts\\python scripts\\smoke_claude.py            # 전부
    .venv-app\\Scripts\\python scripts\\smoke_claude.py --only vision-inline
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE_WEBP = ROOT / "_tmp" / "probe.webp"

# Windows 콘솔에서 한글/이모지가 깨지지 않게
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# ── CLI 찾기 (core/llm.py 의 find_cli 를 그대로 가져옴) ──────────────────────
def find_cli() -> Path | None:
    """claude 실행 파일. VSCode 확장에 번들된 것까지 찾는다(설치본이 없는 PC 대비)."""
    if env := (os.environ.get("CLAUDE_CLI") or "").strip().strip('"'):
        p = Path(env).expanduser()
        if p.exists():
            return p
    if w := shutil.which("claude"):
        return Path(w)
    pats = [
        "anthropic.claude-code-*/resources/native-binary/claude.exe",
        "anthropic.claude-code-*/resources/native-binary/claude",
    ]
    for pat in pats:
        hits = sorted((Path.home() / ".vscode" / "extensions").glob(pat))
        if hits:
            return hits[-1]  # 확장 버전이 올라가면 경로가 바뀐다 → 최신 선택
    return None


# ── 공통 ────────────────────────────────────────────────────────────────────
def scrubbed_env() -> dict[str, str]:
    """오래된 export 가 OAuth 를 조용히 가로채 **다른 계정에 과금**되는 것을 막는다.

    SDK 의 env 는 자식 프로세스 환경에 merge 되므로, 빈 문자열로 덮어 무력화한다.
    """
    return {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_BASE_URL": ""}


def base_options(**kw):
    from claude_agent_sdk import ClaudeAgentOptions

    exe = find_cli()
    return ClaudeAgentOptions(
        cli_path=str(exe) if exe else None,
        setting_sources=[],  # ★ 각자의 전역 CLAUDE.md 유입 차단 (동아리원 간 재현성)
        env=scrubbed_env(),
        **kw,
    )


def _result_of(messages: list) -> object | None:
    from claude_agent_sdk import ResultMessage

    for m in messages:
        if isinstance(m, ResultMessage):
            return m
    return None


def _text_of(messages: list) -> str:
    from claude_agent_sdk import AssistantMessage, TextBlock

    out = []
    for m in messages:
        if isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, TextBlock):
                    out.append(b.text)
    return "".join(out)


def _report(res) -> str:
    if res is None:
        return "result 메시지 없음"
    cost = getattr(res, "total_cost_usd", None)
    turns = getattr(res, "num_turns", None)
    sub = getattr(res, "subtype", "?")
    return f"subtype={sub} turns={turns} cost=${cost if cost is not None else '?'}"


# ── 0. 환경 ────────────────────────────────────────────────────────────────
def check_env() -> bool:
    print("── 0. 환경 " + "─" * 50)
    exe = find_cli()
    print(f"  claude CLI : {exe or '✗ 못 찾음'}")
    if exe is None:
        print("     → Claude Code 로그인 후 재시도하거나 CLAUDE_CLI 로 경로를 지정하세요.")
        return False

    creds = Path.home() / ".claude" / ".credentials.json"
    print(f"  credentials: {'있음' if creds.exists() else '✗ 없음'}  ({creds})")

    leaked = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
              if os.environ.get(k)]
    if leaked:
        print(f"  ⚠ 부모 환경에 {', '.join(leaked)} 설정됨 → 자식 env 에서 무력화합니다.")
    else:
        print("  API 키    : 없음 (구독 OAuth 로만 나감) ✓")

    import claude_agent_sdk as s

    print(f"  SDK       : claude-agent-sdk {getattr(s, '__version__', '?')}")
    return True


# ── 1. 텍스트 ──────────────────────────────────────────────────────────────
async def test_text() -> bool:
    from claude_agent_sdk import query

    print("\n── 1. 텍스트 (키 없이 인증) " + "─" * 34)
    t0 = time.time()
    msgs = []
    try:
        async for m in query(
            prompt="Respond with exactly: OK",
            options=base_options(max_turns=1, allowed_tools=[]),
        ):
            msgs.append(m)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {type(e).__name__}: {e}")
        return False

    text = _text_of(msgs).strip()
    res = _result_of(msgs)
    ok = "OK" in text
    print(f"  응답      : {text[:60]!r}")
    print(f"  {_report(res)}  ({time.time() - t0:.1f}s)")
    print(f"  {'✓ 통과' if ok else '✗ 실패'}")
    return ok


# ── 2. 구조화 출력 ─────────────────────────────────────────────────────────
SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["ok", "note"],
    "additionalProperties": False,
}


async def test_structured() -> bool:
    from claude_agent_sdk import query

    print("\n── 2. 구조화 출력 (draft-07 json_schema) " + "─" * 21)
    t0 = time.time()
    msgs = []
    try:
        async for m in query(
            prompt="Set ok=true and note to the single word 'ready'.",
            options=base_options(
                max_turns=1,
                allowed_tools=[],
                output_format={"type": "json_schema", "schema": SCHEMA},
            ),
        ):
            msgs.append(m)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {type(e).__name__}: {e}")
        return False

    res = _result_of(msgs)
    data = getattr(res, "structured_output", None) if res else None
    print(f"  structured_output: {json.dumps(data, ensure_ascii=False) if data else '✗ 없음'}")
    print(f"  {_report(res)}  ({time.time() - t0:.1f}s)")
    ok = isinstance(data, dict) and data.get("ok") is True
    print(f"  {'✓ 통과' if ok else '✗ 실패'}")
    return ok


# ── 3. 비전 A: inline base64 image 블록 ────────────────────────────────────
VISION_SYSTEM = (
    "너는 화면녹화 프레임을 보고 한국어 캡션을 다는 도구다.\n"
    "화면에 **실제로 보이는** 요소만 쓴다. 추측·과장·일반론을 쓰지 않는다.\n"
    "한 문장, 40자 이내."
)

CAPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "visible_text": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["caption", "visible_text"],
    "additionalProperties": False,
}


async def test_vision_inline() -> bool:
    from claude_agent_sdk import ClaudeSDKClient

    print("\n── 3A. 비전 · inline base64 " + "─" * 34)
    if not PROBE_WEBP.exists():
        print(f"  ✗ 테스트 프레임 없음: {PROBE_WEBP}")
        return False
    b64 = base64.b64encode(PROBE_WEBP.read_bytes()).decode()
    print(f"  프레임    : {PROBE_WEBP.name}  ({PROBE_WEBP.stat().st_size // 1024}KB "
          f"→ base64 {len(b64) // 1024}KB)")

    async def gen():
        # ★ 이 제너레이터에서 예외가 나면 Python SDK 는 debug 로만 로깅하고
        #   세션이 조용히 멈춘다. 그래서 위에서 파일을 먼저 읽어 뒀다.
        yield {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "[v6-f01] t=6.0s 이 프레임에 캡션을 달아라."},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/webp",
                            "data": b64,
                        },
                    },
                ],
            },
        }

    t0 = time.time()
    msgs = []
    try:
        async with ClaudeSDKClient(
            options=base_options(
                max_turns=1,
                allowed_tools=[],
                system_prompt=VISION_SYSTEM,
                output_format={"type": "json_schema", "schema": CAPTION_SCHEMA},
            )
        ) as client:
            await client.query(gen())
            async for m in client.receive_response():
                msgs.append(m)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {type(e).__name__}: {e}")
        return False

    res = _result_of(msgs)
    data = getattr(res, "structured_output", None) if res else None
    print(f"  캡션      : {json.dumps(data, ensure_ascii=False) if data else _text_of(msgs)[:120]!r}")
    print(f"  {_report(res)}  ({time.time() - t0:.1f}s)")
    ok = isinstance(data, dict) and bool(data.get("caption"))
    print(f"  {'✓ 통과 — vision_mode=\"inline\" 사용 가능' if ok else '✗ 실패 → B 경로로'}")
    return ok


# ── 4. 비전 B: Read-from-disk 폴백 ─────────────────────────────────────────
async def test_vision_read() -> bool:
    from claude_agent_sdk import query

    print("\n── 3B. 비전 · Read-from-disk 폴백 " + "─" * 28)
    if not PROBE_WEBP.exists():
        print(f"  ✗ 테스트 프레임 없음: {PROBE_WEBP}")
        return False
    print(f"  프레임    : {PROBE_WEBP}")

    t0 = time.time()
    msgs = []
    try:
        async for m in query(
            prompt=f"Read the image at {PROBE_WEBP.name} and caption it.",
            options=base_options(
                max_turns=4,
                allowed_tools=["Read"],
                disallowed_tools=["Bash", "Write", "Edit", "WebFetch", "WebSearch", "Task"],
                cwd=str(PROBE_WEBP.parent),
                system_prompt=VISION_SYSTEM,
                output_format={"type": "json_schema", "schema": CAPTION_SCHEMA},
            ),
        ):
            msgs.append(m)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {type(e).__name__}: {e}")
        return False

    res = _result_of(msgs)
    data = getattr(res, "structured_output", None) if res else None
    print(f"  캡션      : {json.dumps(data, ensure_ascii=False) if data else _text_of(msgs)[:120]!r}")
    print(f"  {_report(res)}  ({time.time() - t0:.1f}s)")
    ok = isinstance(data, dict) and bool(data.get("caption"))
    print(f"  {'✓ 통과' if ok else '✗ 실패'}")
    return ok


# ── main ───────────────────────────────────────────────────────────────────
TESTS = {
    "text": test_text,
    "structured": test_structured,
    "vision-inline": test_vision_inline,
    "vision-read": test_vision_read,
}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(TESTS), help="한 가지만 실행")
    ap.add_argument("--debug", action="store_true", help="SDK 디버그 로깅 (제너레이터 예외 확인용)")
    args = ap.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

    if not check_env():
        return 2

    names = [args.only] if args.only else list(TESTS)
    results: dict[str, bool] = {}
    for n in names:
        results[n] = await TESTS[n]()

    print("\n" + "═" * 60)
    for n, ok in results.items():
        print(f"  {'✓' if ok else '✗'}  {n}")

    if results.get("vision-inline"):
        print('\n  → showcase.config.json:  "vision_mode": "inline"')
    elif results.get("vision-read"):
        print('\n  → showcase.config.json:  "vision_mode": "read"   (inline 실패, 폴백 사용)')
    elif "vision-inline" in results or "vision-read" in results:
        print("\n  ⚠ 비전 경로 둘 다 실패 — 설계 재검토 필요")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
