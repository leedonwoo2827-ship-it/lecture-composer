# -*- coding: utf-8 -*-
"""스테이지 레지스트리 — DAG · 입력 해시 · 캐시 · resume.

**재실행 가능성이 이 파일의 존재 이유다.** Claude 호출은 비싸다. 한 스테이지를
다시 돌린다고 앞뒤가 같이 돌면 안 되고, 프롬프트를 고쳤을 때는 정확히 그
스테이지와 하위만 stale 이 되어야 한다.

캐시 봉투는 스테이지마다 같다:

    { "stage": "s3-caption", "code_version": 3, "input_hash": "sha256:…",
      "model": "claude-sonnet-5", "cost_usd": 0.184,
      "status": "ok|degraded|skipped", "warnings": [], "data": {…} }

`input_hash` = (상위 스테이지 data + 읽는 project.json 서브셋 + **프롬프트 파일
원문** + code_version) 의 canonical JSON sha256. 프롬프트를 고치면 그 스테이지가
stale 이 된다 — 코드를 안 고쳤어도.

★ 규칙: **Claude 스테이지는 stale 이어도 자동 실행하지 않는다.** 돈은 명시적
  클릭에만 쓴다. 결정론 스테이지(ffmpeg·gh·조립·렌더)만 자동 실행 대상이다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import workspace as ws

PROMPTS = Path(__file__).resolve().parent.parent / "llm" / "prompts"


# ── 캐시 ───────────────────────────────────────────────────────────────────
def cache_path(pid: int, slug: str, stage: str) -> Path:
    return ws.cache_dir(pid, slug) / f"{stage}.json"


def read_cache(pid: int, slug: str, stage: str) -> Optional[Dict[str, Any]]:
    return ws.read_json(cache_path(pid, slug, stage), None)


def write_cache(pid: int, slug: str, stage: str, *, input_hash: str, data: Any,
                code_version: int, model: str = "", cost_usd: float = 0.0,
                status: str = "ok", warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    env = {
        "stage": stage,
        "code_version": int(code_version),
        "input_hash": input_hash,
        # ★ 언제 돌았는가. 파일 시각(mtime)으로도 알 수 있지만 복사·백업 한 번에
        #   흐트러진다. "최근 한 일" 목록이 이걸 읽는다 — 무엇을 이미 했고 무엇을
        #   다시 해야 하는지가 이 툴에서 가장 자주 잃는 감각이라(2026-08-14),
        #   기록을 남기는 쪽이 맞다. 영상을 구운 건지 그 앞 슬라이드를 구운
        #   건지가 화면에서 안 보였다.
        "at": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "cost_usd": round(float(cost_usd), 4),
        "status": status,
        "warnings": warnings or [],
        "data": data,
    }
    ws.write_json(cache_path(pid, slug, stage), env)
    return env


def cached_data(pid: int, slug: str, stage: str) -> Any:
    env = read_cache(pid, slug, stage)
    return (env or {}).get("data")


def narration_of(pid: int, slug: str) -> Dict[str, Dict[str, Any]]:
    """장별 **실제로 쓸** 대본 — S6 이 낸 것 위에 손편집을 얹는다.

    ★ LLM 은 대본을 **처음 만들 때만** 쓴다. 사람이 발음을 발음기호로 고쳐 쓰거나
      자막 문장을 다듬는 일이 그다음에 온다. 그때 다시 만들어야 하는 것은 대본이
      아니라 **음성과 자막**이다 — 돈 드는 단계를 다시 부를 이유가 없다.

    그래서 소리를 내는 곳(S10)과 자막을 쓰는 곳(S11)은 S6 캐시를 직접 읽지 않고
    여기를 읽는다. 예전에는 S6 만 읽어서, 사람이 고쳐 쓴 발음이 **한 번도 소리로
    나가지 못했다.**

    돌려주는 값은 장 번호(문자열) → {"srt_text", "text", "est_sec", "over_sec"}.
    `text`(발음)가 비면 자막을 그대로 읽는다.
    """
    script = (cached_data(pid, slug, "s6-script") or {}).get("slides", {})
    ov = ws.load_overrides(pid, slug).get("slides", {})
    out: Dict[str, Dict[str, Any]] = {}
    for key in set(script) | set(ov):
        sc = script.get(key) or {}
        one = {
            "srt_text": (sc.get("srt_text") or "").strip(),
            "text": (sc.get("narration_text") or "").strip(),
            "est_sec": sc.get("narration_seconds") or 0,
            "over_sec": sc.get("over_sec") or 0,
        }
        hand = ((ov.get(key) or {}).get("narration") or {})
        for k in ("srt_text", "text"):
            if k in hand:                      # 빈 문자열도 뜻이 있다 — 지운 것이다
                one[k] = (hand.get(k) or "").strip()
        out[key] = one
    return out


# ── 해시 ───────────────────────────────────────────────────────────────────
def _canonical(obj: Any) -> str:
    """키 정렬 + 고정 구분자. dict 순서가 바뀌었다고 stale 이 되면 안 된다."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prompt_text(name: Optional[str]) -> str:
    if not name:
        return ""
    p = PROMPTS / name
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return f"<missing:{name}>"


@dataclass
class Stage:
    key: str                      # "s3-caption"
    label: str                    # "쓸 컷 고르기"
    step: str                     # workspace.STEPS 키
    kind: str                     # "det"(결정론) | "claude" | "ext"(외부 프로세스)
    deps: List[str] = field(default_factory=list)
    prompt: Optional[str] = None          # llm/prompts/<name>
    reads: List[str] = field(default_factory=list)   # project.json 에서 읽는 키
    code_version: int = 1
    run: Optional[Callable[..., Any]] = None         # None = 아직 구현 전

    @property
    def is_claude(self) -> bool:
        return self.kind == "claude"

    def input_hash(self, pid: int, slug: str, project: Dict[str, Any]) -> str:
        payload = {
            "code_version": self.code_version,
            "prompt": _prompt_text(self.prompt),
            "project": {k: project.get(k) for k in sorted(self.reads)},
            "deps": {d: cached_data(pid, slug, d) for d in sorted(self.deps)},
        }
        return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:32]


# ── 스테이지 정의 ──────────────────────────────────────────────────────────
# 순서 = 화면에 보이는 순서 = 실행 순서.
# ★ S9(render)가 마지막이다. 페이지가 음성을 품으므로 TTS·오디오가 먼저 끝나야
#   하고, 폰트 서브셋은 산문이 확정된 뒤에 돌아야 한다.
_DEFS: List[Stage] = [
    Stage("s1-frames", "프레임 추출", "frames", "det",
          reads=["video_dir", "items"], code_version=1),
    Stage("s2-repo", "레포 수집", "repo", "det",
          reads=["repo", "sources"], code_version=2),
    # ★ 물어볼 것을 **고정하지 않는다.** 결제가 뼈대만 있는 레포에는 "결제를
    #   넣을까요" 를 물어야 한다. 그래서 재료를 읽은 뒤에 질문을 만든다.
    Stage("s0a-ask", "물어볼 것", "prd", "claude",
          deps=["s1-frames", "s2-repo"], prompt="ask.md",
          reads=["title", "live_url", "urls", "refs", "items", "repo", "sources", "models"],
          code_version=1),
    # ★ 기획서가 구조보다 먼저다. "누구에게 무엇을 팔 것인가" 는 레포에 안 적혀 있고,
    #   뒤 단계가 그걸 지어낼 수는 없다. 사람이 써 온 prd.md 가 있으면 그게 이긴다.
    Stage("s0-prd", "발표 기획서", "prd", "claude",
          deps=["s0a-ask", "s1-frames", "s2-repo"], prompt="prd.md",
          reads=["title", "live_url", "urls", "refs", "items", "repo", "sources",
                 "models", "audience", "goal", "target_min", "answers",
                 "slide_budget"],
          code_version=2),
    # ★ slide_budget 을 읽는다 — 예산을 바꾸면 이 단계가 stale 이 되어야 한다.
    Stage("s2b-outline", "구조 설계", "deck", "claude",
          deps=["s0-prd", "s1-frames", "s2-repo"], prompt="outline.md",
          reads=["title", "live_url", "urls", "refs", "items", "repo", "sources",
                 "models", "slide_budget"], code_version=3),
    # ★ HTML 참고자료는 이미 장별로 정리돼 있다(제목이 곧 장 경계) — AI 구조설계가
    #   필요 없다. 이 문으로 들어오면 S0a·S0·S2b 를 건너뛰고 s2b-outline 캐시를
    #   직접 확정한다(위 s2b-outline 과 산출물 자리가 같다).
    #   `capture_mode` 를 읽는다 — html(글 그대로) ↔ image(화면 캡처)를 바꾸면
    #   결과가 통째로 달라지므로, 바꿨을 때 이 단계가 낡은 것으로 잡혀야 한다.
    Stage("s2c-capture", "원고 구조 읽기", "deck", "ext",
          reads=["title", "refs", "capture_mode"], code_version=2),
    # 캡션은 **영상 레인이 쓸 컷만** 고른다. 몇 컷이 필요한지는 S2b 가 정하므로
    # 구조 설계에 딸린다 — 덱이 바뀌면 골라야 할 컷 수도 바뀐다.
    Stage("s3-caption", "쓸 컷 고르기", "caption", "claude",
          deps=["s1-frames", "s2b-outline"], prompt="caption.md",
          reads=["items", "language", "models"], code_version=2),
    Stage("s5-decisions", "기술적 의사결정", "decisions", "claude",
          deps=["s2b-outline"], prompt="decisions.md",
          reads=["items", "repo", "models"], code_version=1),
    # 문체만 갈아 끼우는 단계. 구조(S2b)를 다시 돌리면 순서·영상 배치가 날아간다.
    Stage("s7-copy", "슬라이드 문구", "deck", "claude",
          deps=["s2b-outline", "s5-decisions"], prompt="copy.md",
          reads=["slide_tone", "models"], code_version=1),
    # ★ `_fix_ends`(표지·맺음 고정 문구)를 넣었지만 **code_version 은 올리지
    #   않는다.** 올리면 s6 가 낡고, 그 데이터를 물고 있는 s10-tts·s11-audio 까지
    #   같이 낡아 **이미 검수 중인 음성을 다시 만들게** 된다(2026-08-16: 씬마다
    #   오디오를 듣고 발음 원고를 확정하는 중이었다). 새 프로젝트는 처음 돌 때
    #   자동으로 고정 문구를 받는다. 이미 만든 프로젝트에 적용하고 싶으면 그때
    #   이 숫자를 올리거나 s6 를 강제로 다시 돌린다 — 나머지 장은 캐시에서
    #   나오므로 돈은 안 든다.
    # code_version 2 — 하십시오체 변환기가 이미 존댓말인 문장을 또 바꾸던 것을
    # 고쳤다(`합니다` → `합니입니다`). 원고를 그대로 살려 쓰게 되면서 드러났다.
    Stage("s6-script", "내레이션 대본", "script", "claude",
          deps=["s2b-outline", "s5-decisions"], prompt="script.md",
          reads=["items", "narration", "language", "models"], code_version=2),
    # ★ 그림 지시문과 그림 받기를 **가른다.** 지시문 쓰기는 Claude 를 부르고
    #   (돈이 든다 · 자동 실행하면 안 된다), 받기는 결정론이라 낡으면 저절로
    #   돈다. 한 단계에 묶으면 그림 한 장 넣을 때마다 지시문을 다시 사게 된다.
    # ★ **image_fit 을 반드시 읽는다.** 판이 지시문을 정한다 —
    #   액자(6판) 는 라벨 문구를 그림에 인쇄하라고 시키고,
    #   전면·배경판(11판) 은 그 자리를 비우라고 시킨다. 같은 지시문일 수가 없다.
    #   이 칸을 빼 두면 판을 바꿔도 **옛 지시문이 그대로 재사용된다**
    #   (2026-09-18 실측: plate 로 바꿨는데 fmt 10 프롬프트가 나왔다).
    # ★ code_version 2→3(2026-09-18): 전면도 글자를 안 박게 바뀌었다
    #   (`s3a_imgprompt.is_plate`). 2 로 두면 「라벨을 인쇄하라」고 적힌 옛
    #   지시문이 캐시에서 그대로 나와 그림에 또 글자가 구워진다.
    Stage("s3a-imgprompt", "그림 지시문", "images", "claude",
          deps=["s2b-outline"], prompt="imgprompt.md",
          reads=["title", "models", "image_fit"], code_version=5),
    # 그림은 이제 **같은 서버**가 만든다(s3c-images-run). 예전에는 다른 앱
    # (8765 포트)이 만들어서 사람이 JSON 을 들고 창을 옮겨 다녔다.
    Stage("s3b-images", "슬라이드 이미지", "images", "det",
          deps=["s2b-outline", "s5-decisions", "s3a-imgprompt"],
          reads=["title", "image_fit"], code_version=3),
    # ★ 둘 다 `narration_rev` 를 읽는다 — **손으로 고친 대본이 낡음의 이유다.**
    #   LLM 은 대본을 처음 만들 때만 쓰고, 발음을 발음기호로 고쳐 쓰거나 자막
    #   문장을 다듬는 일은 그다음에 온다. 그때 다시 만들 것은 음성과 자막이다.
    #   예전에는 S6 캐시만 보고 낡음을 판정해서, 고쳐 놓아도 "할 일 없음" 이었다.
    #   `overrides_rev`(조립이 읽는 것)가 아닌 이유: 그림 한 장 넣었다고 음성
    #   22장을 다시 합성하면 몇 분이 그냥 나간다.
    # ★ code_version 2→3(2026-09-18): `find_engine` 이 옛 엔진 폴더를 보느라
    #   합성을 건너뛴 캐시가 남아 있다. 안 올리면 그 「skipped」 가 그대로
    #   신선한 값으로 앉아 있어 현황판이 「할 일 없음」 이라 말한다.
    # ★ **설정(config)은 input_hash 에 안 들어간다** — `reads` 는 project 키만
    #   본다(위 `input_hash`). 그래서 tts 엔진을 켜고 꺼도 이 단계는 안 낡는다.
    #   엔진을 새로 이은 뒤에는 사람이 «음성/자막 굽기» 를 눌러야 한다.
    Stage("s10-tts", "음성 합성", "audio", "ext",
          deps=["s6-script"], reads=["narration", "narration_rev"], code_version=3),
    Stage("s11-audio", "자막·큐시트", "subtitle", "det",
          deps=["s6-script", "s10-tts"], reads=["items", "narration_rev"],
          code_version=2),
    Stage("s8-assemble", "덱 조립", "deck", "det",
          deps=["s2b-outline", "s3-caption", "s5-decisions", "s7-copy",
                "s6-script", "s3b-images", "s11-audio"],
          # overrides_rev — 손편집이 조립을 낡게 만든다(위 server.py 참고)
          # image_swap — 그림으로 갈아끼우기를 켜고 끄면 덱이 통째로 달라진다
          reads=["title", "slug", "live_url", "items", "brand", "overrides_rev",
                 "image_swap"],
          code_version=2),
    # `bgm` — 배경음악을 갈아 끼우면 완성본만 다시 구우면 된다. 조립(s8)은
    # 배경음악을 모르므로 여기서만 읽는다. 결정론이라 돈이 들지 않는다.
    Stage("s9-render", "완성본 렌더", "dist", "det",
          deps=["s8-assemble"], reads=["slug", "title", "bgm"], code_version=2),
    # ★ S9 뒤에 둔다 — 산출물 폴더(11_완성)에 같이 쌓이고, 오디오(S10)가
    #   끝나야 장마다 조각 길이가 정해진다. Claude 를 안 써서 "ext"(S10 과 같은
    #   분류) — stale 이면 "다음 할 일"이 자동으로도 돌린다.
    Stage("s12-video", "영상 렌더", "dist", "ext",
          deps=["s8-assemble", "s10-tts"], reads=["slug", "title"], code_version=1),
    # ── 11판(배경판) 전용 ────────────────────────────────────────────────
    # ★ **그림 굽기.** 예전에는 사람이 이미지프롬프트.json 을 들고 다른 앱으로
    #   건너가 한 장씩 눌렀다. 이제 같은 서버 안이라 스테이지로 돈다.
    #   "ext" 인 이유: Claude 가 아니라 바깥 이미지 백엔드를 부른다(구독 할당량).
    Stage("s3c-images-run", "그림 굽기", "images", "ext",
          deps=["s3a-imgprompt", "s3b-images"],
          reads=["slug", "title", "image_fit"], code_version=2),
    # ★ **HyperFrames 렌더.** s12-video(Playwright 스틸 + ffmpeg 이어붙이기)를
    #   대신한다. 글자가 DOM 이라 GSAP 이 직접 움직이고, 상자를 되찾을 일이 없다.
    #   오디오도 HyperFrames 가 먹고, 마지막에 −16 LUFS 로 맞춘다.
    Stage("s12h-hyper", "모션 영상(HyperFrames)", "dist", "ext",
          deps=["s8-assemble", "s10-tts"],
          reads=["slug", "title", "image_fit"], code_version=1),
]

STAGES: Dict[str, Stage] = {s.key: s for s in _DEFS}
ORDER: List[str] = [s.key for s in _DEFS]


# ── 상태 ───────────────────────────────────────────────────────────────────
def stage_states(pid: int, slug: str, project: Dict[str, Any]) -> List[Dict[str, Any]]:
    """화면의 스테이지 그리드가 쓰는 것. missing / stale / fresh / degraded."""
    out: List[Dict[str, Any]] = []
    blocked_by: Optional[str] = None

    for key in ORDER:
        st = STAGES[key]
        env = read_cache(pid, slug, key)
        want = st.input_hash(pid, slug, project)

        if env is None:
            state = "missing"
        elif env.get("input_hash") != want:
            state = "stale"
        elif env.get("status") == "degraded":
            state = "degraded"
        elif env.get("status") == "skipped":
            state = "skipped"
        else:
            state = "fresh"

        # 상위가 아직 안 돌았으면 이 스테이지는 시작할 수 없다
        missing_deps = [d for d in st.deps
                        if (read_cache(pid, slug, d) or {}).get("data") is None]

        out.append({
            "key": key,
            "label": st.label,
            "kind": st.kind,
            "step_dir": ws.STEPS[st.step][0],
            "deps": st.deps,
            "state": state,
            "blocked": bool(missing_deps),
            "missing_deps": missing_deps,
            "implemented": st.run is not None,
            # ★ Claude 스테이지는 stale 이어도 자동 실행 대상이 아니다
            "auto": (not st.is_claude) and state in ("missing", "stale") and not missing_deps,
            "cost_usd": (env or {}).get("cost_usd", 0.0),
            "model": (env or {}).get("model", ""),
            "warnings": (env or {}).get("warnings", []),
        })
        if blocked_by is None and state != "fresh":
            blocked_by = key

    return out


def total_cost(pid: int, slug: str) -> float:
    return round(sum((read_cache(pid, slug, k) or {}).get("cost_usd", 0.0)
                     for k in ORDER), 4)
