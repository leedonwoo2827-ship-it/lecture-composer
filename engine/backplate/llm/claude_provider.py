# -*- coding: utf-8 -*-
"""Claude 프로바이더 — Claude Code 구독 OAuth. **API 키를 쓰지 않는다.**

사내 LLM 브릿지의 duck-typed 계약을 그대로 만족시킨다.
새 인터페이스를 발명하지 않는다 — 그래야 codex·agy 프로바이더와 갈아끼울 수 있다.

    model                                     # 반드시 **대입 가능한 필드**
    generate(system, messages) -> str
    stream(system, messages)   -> Iterator[str]      # ★ 증분 델타만
    structured(system, messages, schema) -> dict
    vision(system, parts, schema)        -> dict     # 신규 — 이미지 입력
    ping() -> (bool, str)

호출부는 동기(스레드 워커)라 겉면은 전부 동기다. 내부에서만 asyncio.run 한다.

M2 스모크로 확인한 사실(2026-08-08, claude-agent-sdk 0.2.132):
  - 키 없이 인증 통과. `.credentials.json` 의 구독 로그인으로 나간다.
  - `output_format={"type":"json_schema","schema":…}` 동작. draft-07.
  - **inline base64 이미지 블록 동작** — 1024px webp 에서 화면 텍스트까지 읽었다.
  - 호출당 최소 비용이 약 $0.24 다. 사소한 "OK" 한 마디도 같다.
    → 프레임은 반드시 **항목당 한 번에 묶어** 보낸다. 장당 한 번씩 부르면 안 된다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from .errors import NotAuthenticated, ProviderError, QuotaExceeded

# 이미지 확장자 → media_type. webp 가 기본(같은 화질에 base64 가 가장 작다).
MEDIA = {".webp": "image/webp", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}


# ── CLI 찾기 (instructional-design-agent/core/llm.py 와 동일) ──────────────
def find_cli() -> Optional[Path]:
    """claude 실행 파일. VSCode 확장에 번들된 것까지 찾는다(설치본이 없는 PC 대비)."""
    if env := (os.environ.get("CLAUDE_CLI") or "").strip().strip('"'):
        p = Path(env).expanduser()
        if p.exists():
            return p
    # ★ **배치본(.cmd/.bat)은 SDK 가 실행을 거부한다.** Windows 에서 .cmd 는
    #   cmd.exe 로 도는데 인자로 명령을 주입할 수 있고 안전한 이스케이프가 없다.
    #   npm 으로 깐 `claude` 는 `claude.CMD` 라 PATH 에서 먼저 잡히는데, 그걸
    #   집으면 **모든 Claude 단계가 통째로 실패한다**(2026-08-19: 22장 그림
    #   지시문 34장이 전부 빈 채로 끝났고, 화면에는 「JSON 이 없다」로만 보였다).
    #   그래서 배치본은 뒤로 미루고 네이티브를 먼저 찾는다.
    batch: Optional[Path] = None
    if w := shutil.which("claude"):
        p = Path(w)
        if p.suffix.lower() in (".cmd", ".bat"):
            batch = p
        else:
            return p
    # VSCode 확장이 네이티브 바이너리를 같이 깐다 — 설치본이 없는 PC 대비이기도 하고,
    # npm 배치본만 있는 PC 에서는 **유일하게 쓸 수 있는 것**이다.
    pats = ["anthropic.claude-code-*/resources/native-binary/claude.exe",
            "anthropic.claude-code-*/resources/native-binary/claude"]
    for pat in pats:
        hits = sorted((Path.home() / ".vscode" / "extensions").glob(pat))
        if hits:
            return hits[-1]      # 확장 버전이 올라가면 경로가 바뀐다 → 최신 선택
    # 네이티브가 없으면 배치본이라도 돌려준다 — SDK 가 내는 거부 메시지가
    # 「네이티브를 깔라」고 안내하므로, None 보다 그 메시지가 낫다.
    return batch


def scrubbed_env() -> Dict[str, str]:
    """오래된 export 가 OAuth 를 조용히 가로채 **다른 계정에 과금**되는 것을 막는다.

    빈 문자열로 덮으면 SDK 가 자식 환경에 그대로 넣어 무력화된다.
    """
    return {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_BASE_URL": ""}


def _classify_error(msg: str) -> Exception:
    """문자열 매칭으로 타입화 — 사내 LLM 브릿지와 같은 규칙."""
    low = (msg or "").lower()
    if any(k in low for k in ("not authenticated", "sign in", "401", "unauthorized", "login")):
        return NotAuthenticated(msg)
    if any(k in low for k in ("quota", "rate limit", "429", "usage limit", "overloaded")):
        return QuotaExceeded(msg)
    return ProviderError(msg)


def _run(coro):
    """동기 겉면 — 이미 루프가 돌고 있으면 별도 스레드에서 돌린다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# ── 프로바이더 ─────────────────────────────────────────────────────────────
@dataclass
class ClaudeProvider:
    model: str = ""                      # 빈 값 = CLI 기본
    effort: Optional[str] = None         # low | medium | high | xhigh | max
    cwd: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)
    max_turns: int = 1
    budget_usd: float = 1.5
    exe: Optional[Path] = field(default=None)
    # ★ 모델이 툴을 쓸 때마다 부른다. 레포를 읽는 단계는 2~3분씩 가는데, 그동안
    #   화면이 한 글자도 안 바뀌면 **멈춘 것으로 보인다.** 실제로 그 말을 들었다.
    #   무엇을 읽고 있는지를 그대로 흘려 보낸다.
    on_activity: Optional[Callable[[str], None]] = field(default=None, repr=False)

    last_cost_usd: float = 0.0
    last_turns: int = 0

    def __post_init__(self) -> None:
        if self.exe is None:
            self.exe = find_cli()

    # ── 옵션 조립 ──
    def _options(self, *, system: str = "", schema: Optional[dict] = None, **over):
        from claude_agent_sdk import ClaudeAgentOptions

        if self.exe is None:
            raise NotAuthenticated(
                "Claude Code CLI 를 찾지 못했습니다. Claude Code 로그인 후 다시 시도하거나 "
                "CLAUDE_CLI 환경변수로 실행 파일 경로를 지정하세요.")

        # ★ 빈 allowed_tools 는 "도구 없음" 이 아니라 --allowedTools 를 아예 안 넘기는
        #   것 — SDK 특성상 "제한 없음"으로 풀린다(disallowed_tools 만 막는다).
        #   진짜로 도구를 막으려면 여기서 명시적으로 disallow 해야 한다.
        disallowed = ["Bash", "Write", "Edit", "NotebookEdit",
                      "WebFetch", "WebSearch", "Task"]
        max_turns = self.max_turns
        if not self.allowed_tools:
            disallowed += ["Read", "Grep", "Glob"]
            # ★ disallow 해도 모델이 **일단 시도했다가 거절당하는** 왕복 자체가
            #   턴 하나를 쓴다(실제로 겪음 — "**/*.md 훑는 중" 이 찍히고 나서
            #   "Reached maximum number of turns (1)" 로 죽었다). 그 왕복 다음에
            #   진짜 답을 낼 턴이 하나 더 있어야 한다. 도구 없이 브리프만으로
            #   답하는 단계라도 max_turns 는 최소 1 을 넘겨 둔다.
            max_turns = max(max_turns, 3)

        kw: Dict[str, Any] = dict(
            cli_path=str(self.exe),
            # ★ 각자의 전역 ~/.claude/CLAUDE.md 유입 차단.
            #   안 하면 동아리원마다 결과가 달라진다 — 재현성 요구사항이다.
            setting_sources=[],
            env=scrubbed_env(),
            max_turns=max_turns,
            max_budget_usd=self.budget_usd,
            allowed_tools=list(self.allowed_tools),
            disallowed_tools=disallowed,
            permission_mode="default",
        )
        if system:
            kw["system_prompt"] = system          # 문자열 — claude_code 프리셋 안 씀
        if (m := (self.model or "").strip()) and m not in ("cli-default", "default"):
            kw["model"] = m
        if self.effort:
            kw["effort"] = self.effort
        if self.cwd:
            kw["cwd"] = str(self.cwd)
        if schema is not None:
            kw["output_format"] = {"type": "json_schema", "schema": schema}
        kw.update(over)
        return ClaudeAgentOptions(**kw)

    # ── 지금 무엇을 하고 있는가 ──
    _TOOL_KO = {"Read": "읽는 중", "Grep": "찾는 중", "Glob": "훑는 중"}

    def _activity(self, blocks) -> None:
        """ToolUseBlock 을 사람이 읽는 한 줄로. 경로는 뒤 두 칸만 남긴다."""
        if not self.on_activity:
            return
        for b in blocks:
            name = getattr(b, "name", "")
            if name not in self._TOOL_KO:
                continue
            inp = getattr(b, "input", None) or {}
            what = (inp.get("file_path") or inp.get("pattern")
                    or inp.get("path") or "")
            what = str(what).replace("\\", "/").rstrip("/")
            what = "/".join(what.split("/")[-2:])
            try:
                self.on_activity(f"{what} {self._TOOL_KO[name]}" if what
                                 else self._TOOL_KO[name])
            except Exception:            # noqa: BLE001 — 표시용이다. 절대 본작업을 죽이지 않는다
                pass

    def _record(self, result) -> None:
        self.last_cost_usd = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
        self.last_turns = int(getattr(result, "num_turns", 0) or 0)

    # ── 텍스트 ──
    def generate(self, system: str, messages: List[Dict], *,
                 max_tokens: int = 0, temperature: float = 0.0) -> str:
        """max_tokens·temperature 는 CLI 가 받지 않는다(시그니처 호환용)."""
        return "".join(self.stream(system, messages))

    def stream(self, system: str, messages: List[Dict], **_) -> Iterator[str]:
        """증분 텍스트를 흘린다.

        ★ SDK 는 증분과 **완성 전문**을 모두 준다. 둘 다 흘리면 문서가 두 번 나온다 —
          IDA 에서 강의계획서가 통째로 두 번 찍힌 적이 있다. 그래서 델타를 우선하고
          전문은 델타가 하나도 없었을 때만 폴백으로 쓴다.
        """
        chunks, whole = _run(self._collect(system, self._flatten(messages)))
        if chunks:
            yield from chunks
        elif whole:
            yield whole

    async def _collect(self, system: str, prompt: str) -> Tuple[List[str], str]:
        from claude_agent_sdk import (AssistantMessage, ResultMessage, TextBlock, query)

        deltas: List[str] = []
        whole = ""
        try:
            async for m in query(prompt=prompt,
                                 options=self._options(system=system,
                                                       include_partial_messages=True)):
                if isinstance(m, AssistantMessage):
                    part = "".join(b.text for b in m.content if isinstance(b, TextBlock))
                    if len(part) > len(whole):
                        whole = part
                elif isinstance(m, ResultMessage):
                    self._record(m)
                    if getattr(m, "subtype", "") != "success" and not whole and not deltas:
                        raise _classify_error(f"{m.subtype}: {getattr(m, 'result', '')}")
        except Exception as e:  # noqa: BLE001
            if isinstance(e, ProviderError):
                raise
            raise _classify_error(str(e)) from e
        return deltas, whole

    # ── 구조화 ──
    def structured(self, system: str, messages: List[Dict], *, schema: dict) -> dict:
        return _run(self._structured(system, self._flatten(messages), schema))

    async def _structured(self, system: str, prompt: str, schema: dict) -> dict:
        from claude_agent_sdk import AssistantMessage, ResultMessage, query

        out: Optional[dict] = None
        sub = "?"
        try:
            async for m in query(prompt=prompt,
                                 options=self._options(system=system, schema=schema)):
                if isinstance(m, AssistantMessage):
                    self._activity(m.content)
                if isinstance(m, ResultMessage):
                    self._record(m)
                    sub = getattr(m, "subtype", "?")
                    out = getattr(m, "structured_output", None)
        except Exception as e:  # noqa: BLE001
            raise _classify_error(str(e)) from e
        if not isinstance(out, dict):
            # ★ subtype == "success" 인데 structured_output 이 없는 경우도 있다.
            #   문서가 명시한 케이스다 — 실패로 취급한다.
            raise ProviderError(f"구조화 출력을 받지 못했습니다 (subtype={sub})")
        return out

    # ── 비전 ──
    def vision(self, system: str, parts: Iterable[Dict[str, Any]], *,
               schema: dict, intro: str = "") -> dict:
        """`parts` = [{"text": "...", "image": Path|None}, …] 를 한 번에 보낸다.

        **한 항목의 프레임 전부를 한 콜에 묶는다.** 호출당 최소 $0.24 라
        장당 한 번씩 부르면 비용이 10배가 된다.
        """
        blocks = self._image_blocks(parts)
        return _run(self._vision(system, intro, blocks, schema))

    @staticmethod
    def _image_blocks(parts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """★ 파일 읽기를 제너레이터 **밖**에서 끝낸다.

        Python SDK 는 메시지 제너레이터에서 난 예외를 debug 로만 로깅하고
        세션이 조용히 멈춘다(공식 문서 명시). 그래서 I/O 를 미리 끝내 둔다.
        """
        out: List[Dict[str, Any]] = []
        for p in parts:
            if txt := (p.get("text") or ""):
                out.append({"type": "text", "text": txt})
            img = p.get("image")
            if not img:
                continue
            path = Path(img)
            mt = MEDIA.get(path.suffix.lower())
            if mt is None:
                raise ProviderError(f"지원하지 않는 이미지 형식: {path.name}")
            out.append({"type": "image", "source": {
                "type": "base64", "media_type": mt,
                "data": base64.b64encode(path.read_bytes()).decode(),
            }})
        return out

    async def _vision(self, system: str, intro: str,
                      blocks: List[Dict[str, Any]], schema: dict) -> dict:
        from claude_agent_sdk import ClaudeSDKClient, ResultMessage

        # ★ **메시지는 하나여야 한다.** intro 를 따로 yield 하면 그것만으로 한 턴이
        #   성립해서, 모델이 이미지가 도착하기 전에 답해 버린다. 실제로 6개 중 3개가
        #   "이미지가 제공되지 않아 확인 불가" 를 반환하고 없는 프레임 id 를 지어냈다.
        #   레이스라 재현이 들쭉날쭉해서 더 위험하다 — 구조로 막는다.
        content = ([{"type": "text", "text": intro}] if intro else []) + blocks

        async def gen():
            yield {"type": "user", "message": {"role": "user", "content": content}}

        out: Optional[dict] = None
        sub = "?"
        try:
            async with ClaudeSDKClient(
                options=self._options(system=system, schema=schema)
            ) as client:
                await client.query(gen())
                async for m in client.receive_response():
                    if isinstance(m, ResultMessage):
                        self._record(m)
                        sub = getattr(m, "subtype", "?")
                        out = getattr(m, "structured_output", None)
        except Exception as e:  # noqa: BLE001
            raise _classify_error(str(e)) from e
        if not isinstance(out, dict):
            raise ProviderError(f"비전 구조화 출력을 받지 못했습니다 (subtype={sub})")
        return out

    # ── 상태 ──
    def ping(self) -> Tuple[bool, str]:
        if self.exe is None:
            return False, "Claude Code CLI 를 찾지 못했습니다 (CLAUDE_CLI 로 지정 가능)."
        try:
            txt = self.generate("You are a connection tester.",
                                [{"role": "user", "content": "Respond with exactly: OK"}])
            return True, f"OK (${self.last_cost_usd:.3f}) → {txt.strip()[:40]}"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"

    # ── 내부 ──
    @staticmethod
    def _flatten(messages: List[Dict]) -> str:
        """SDK 는 대화 배열이 아니라 한 프롬프트를 받는다 — 역할을 표시해 접는다."""
        if len(messages) == 1 and messages[0].get("role") == "user":
            return str(messages[0].get("content") or "")
        role_ko = {"user": "사용자", "assistant": "어시스턴트", "system": "지시"}
        return "\n\n".join(
            f"[{role_ko.get(m.get('role', 'user'), m.get('role', 'user'))}]\n"
            f"{m.get('content') or ''}" for m in messages)


def status() -> Dict[str, Any]:
    """설정 화면의 연결 칩이 읽는 것."""
    exe = find_cli()
    return {
        "provider": "claude",
        "label": "Claude Code (구독 OAuth)",
        "installed": exe is not None,
        "path": str(exe) if exe else None,
        "credentials": (Path.home() / ".claude" / ".credentials.json").is_file(),
        "api_key_env": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }
