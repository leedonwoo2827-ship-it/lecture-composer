# -*- coding: utf-8 -*-
"""S6 내레이션 대본 — 37장 전체의 **자막**과 **발음**.

세 텍스트가 서로 다르다. 이걸 섞으면 발표가 교안 낭독이 된다:

    슬라이드 문구   화면에 박혀 있는 글      (S2b·S5 가 이미 만든 것)
    자막 srt_text   입으로 말하는 것의 원문   ← 여기서 만든다
    발음 narration  TTS 가 소리 내는 표기     ← 여기서 만든다

`srt_text` 와 `narration_text` 는 **같은 문장의 두 표기**다. "2vCPU" 를 자막엔
그대로 두고 발음만 "투 브이씨피유" 로 바꾼다. voicewright 가 이미 쓰는 규약이라
TTS 가 공짜로 붙는다.

★ **영상 장은 길이가 제약이다.** 대본이 클립보다 길면 영상이 끝나고 말이 남는다.
  한 영상을 여러 장이 나눠 쓰면 길이도 나눠 갖는다. 초과분은 경고로 남기고
  편집표에서 눈에 띄게 한다 — 줄이든 마지막 프레임을 홀드하든 사람이 정한다.

S5 와 같은 이유로 **묶음으로 쪼갠다.** 한 콜에 37장을 넣으면 예산에서 끊기고
그때까지 쓴 것이 통째로 날아간다(실제로 겪었다).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List

from core import config, honorific, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "srt_text": {"type": "string"},
                    "narration_text": {"type": "string"},
                },
                "required": ["no", "srt_text", "narration_text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["slides"],
    "additionalProperties": False,
}

# 장 종류별 기본 길이(초). 영상 장은 클립 길이가 이긴다.
BASE_SEC = {
    "cover": 8, "context": 14, "feature": 16, "architecture": 18,
    "decision": 20, "metric": 14, "ops": 14, "note": 12, "closing": 10,
}
MD = re.compile(r"[*_`#>\[\]]|^\s*[-•]\s+", re.M)


def est_sec(text: str, cps: float) -> float:
    """scriptforge 규칙 — 공백 뺀 글자수 / 초당 글자수."""
    n = len(re.sub(r"\s", "", text or ""))
    return round(math.ceil(n / max(cps, 0.1) * 10) / 10, 1)


def budgets(slides: List[Dict[str, Any]], frames: Dict[str, Any],
            clips: Dict[str, Any] | None = None,
            target_sec: float = 0.0) -> Dict[int, float]:
    """장마다 몇 초를 줄지. **영상 장은 클립 길이를 n등분한다.**

    한 영상을 3장이 나눠 쓰면 각 장은 그 영상의 1/3 안에서 말해야 한다.
    그래야 슬라이드를 넘길 때 영상도 같이 흘러간다.
    """
    clips = clips or {}
    share: Dict[str, int] = {}
    for s in slides:
        if s.get("video_id"):
            share[s["video_id"]] = share.get(s["video_id"], 0) + 1

    out: Dict[int, float] = {}
    for s in slides:
        vid = s.get("video_id")
        if vid:
            # ★ **자른 길이를 따른다.** 사람이 구간을 줄였으면 그만큼만 말하면 된다.
            #   원본 길이로 잡으면 잘라 놓고도 대본이 그대로라 발표가 안 줄어든다.
            c = (clips.get(str(s["no"])) or {}).get("clip") or {}
            cut = sum(max(0.0, float(b) - float(a)) for a, b in (c.get("cuts") or []))
            if c.get("end"):
                dur = max(1.0, (float(c["end"]) - float(c.get("start") or 0) - cut)
                          / float(c.get("speed") or 1))
                out[s["no"]] = max(6.0, round(dur, 1))
                continue
            dur = (frames.get(vid) or {}).get("duration_sec")
            if dur:
                # ★ 영상 시간을 **채우는 것**이 목표다. 예전엔 0.5초를 빼서 "이 안에
                #   들어가라" 로 줬는데, 그러니 짧게 쓰고 영상만 도는 시간이 생겼다
                #   (실제로 181초). 이제는 규칙이 다르다 — 둘 중 긴 쪽을 기다리고
                #   영상이 짧으면 마지막 프레임에서 선다. 그러니 채우는 게 맞다.
                out[s["no"]] = max(6.0, round(dur / share[vid], 1))
                continue
        out[s["no"]] = float(BASE_SEC.get(s.get("kind"), 12))

    # ★ 목표 길이가 정해져 있으면 **텍스트 장을 거기에 맞춘다.**
    #   영상 장은 이미 클립 길이로 고정이라 건드리지 않는다. 남는 시간을
    #   텍스트 장에 나눠 준다 — 종류별 비중(표지는 짧고 판단은 길게)은 지킨다.
    if target_sec:
        vid_no = {s["no"] for s in slides if s.get("video_id")}
        txt = [s["no"] for s in slides if s["no"] not in vid_no]
        used = sum(out[n] for n in vid_no)
        left = max(0.0, target_sec - used)
        base = sum(out[n] for n in txt) or 1.0
        if txt and left > 0:
            k = left / base
            for n in txt:
                out[n] = max(5.0, round(out[n] * k, 1))
    return out


def build_brief(chunk: List[Dict[str, Any]], deck: Dict[str, Any],
                dec: Dict[str, Any], budget: Dict[int, float],
                prev_tail: str) -> str:
    lines: List[str] = []
    lines.append(f"# 발표\n{deck.get('deck_title') or ''}")
    if deck.get("deck_subtitle"):
        lines.append(deck["deck_subtitle"])
    lines.append(f"총 {len(deck.get('slides') or [])}장 중 아래 {len(chunk)}장을 쓴다.")
    if prev_tail:
        lines.append(f"\n# 바로 앞 장의 마지막 말\n{prev_tail}\n여기서 이어라.")

    lines.append("\n# 쓸 장")
    for s in chunk:
        no = s["no"]
        lines.append(f"\n## {no} · {s.get('title') or ''}   (목표 {budget[no]:.0f}초)")
        lines.append(f"종류: {s.get('kind')}")
        if s.get("note"):
            lines.append(f"화면 문구: {s['note']}")
        if s.get("video_id"):
            sec = budget[no]
            lines.append(f"영상: {s['video_id']} — 이 장에서 화면 녹화가 {sec:.0f}초 동안 "
                         f"돈다. **그 시간을 채워라.** 화면에서 벌어지는 일을 순서대로 "
                         f"짚으면 그만큼 나온다 (공백 뺀 글자 약 {int(sec * 5.7)}자).")
        if s.get("evidence_hint"):
            lines.append(f"근거: {s['evidence_hint']}")
        d = dec.get(str(no))
        if d:
            lines.append("판단(이 장의 재료 — 화면에 이미 적힌 것은 다시 읽지 마라):")
            for k, label in (("problem", "증상"), ("choice", "고른 것"),
                             ("rationale", "이유"), ("tradeoff", "포기한 것")):
                if d.get(k):
                    lines.append(f"  {label}: {d[k]}")
            for e in (d.get("evidence") or [])[:3]:
                lines.append(f"  근거: {e.get('ref')}")

    lines.append("\n주어진 no 만 채워라. JSON 만 출력.")
    return "\n".join(lines)


def clean(t: str) -> str:
    """평문만 남긴다 — 렌더러도 자막도 마크다운을 모른다."""
    return MD.sub("", str(t or "")).strip()


# ── 여는 말·닫는 말 — **고정한다** ─────────────────────────────────────────
# ★ 이 두 장만 LLM 에게 안 맡긴다. 인사와 맺음말은 발표마다 달라질 이유가 없는데,
#   매번 새로 쓰이니 회차마다 말이 달라졌다. 맺음말은 프롬프트가 "감사 인사 대신
#   **다음 행동**" 을 시켜서 「앞 장부터 순서대로 보시면 흐름이 이어지고요, 궁금한
#   대목은 목차에서 바로 찾아가시면 됩니다」 같은 안내문이 나갔다 —
#   짧은 인사면 될 자리다(2026-08-16).
#
# ★ 이미 만든 프로젝트에는 **닿지 않는다.** `registry` 의 `code_version` 을 일부러
#   안 올렸다 — 올리면 s10-tts·s11-audio 까지 낡아 검수 중인 음성을 다시 만든다.
#
# ★ 사람이 발음 화면에서 고친 것은 그대로 이긴다. 여기서 덮는 것은 **대본**이고,
#   손편집은 오버라이드에 따로 얹힌다(`registry.narration_of`).
#   2026-08-16 에 사람이 확정한 문장이다. 바꾸려면 여기만 고친다.


def _chapter(project: Dict[str, Any]) -> tuple:
    """(책 이름, 장 번호). 번호가 없으면 (이름, None)."""
    title = str(project.get("title") or "").strip()
    book = str(project.get("book") or "").strip()
    m = re.search(r"(\d+)\s*장", title)
    return book, (int(m.group(1)) if m else None)


def _open_lines(project: Dict[str, Any]) -> tuple:
    """여는 말 — (자막, 발음). **숫자를 갈라 쓴다.**

    ★ 자막은 `19장`, 발음은 `십구 장`이다. TTS 는 발음 대본을 글자 그대로 읽어서
      `19장` 을 주면 「일구장」으로 나온다(2026-08-16 사람이 손으로 그렇게 갈라
      넣었다). 자막과 발음이 다른 표기를 갖는 것이 이 앱의 원래 설계다.
    """
    title = str(project.get("title") or "").strip()
    book, n = _chapter(project)
    head = book or title or "이번 장"

    if book and n:
        return (f"안녕하세요. {head} {n}장을 시작하겠습니다.",
                f"안녕하세요. {head} {honorific.sino(n)} 장을 시작하겠습니다.")
    # 장 번호가 없는 발표 — 제목을 그대로 부른다(받침 보고 을/를)
    name = f"{book} {title}".strip() or head
    t = f"안녕하세요. {name}{honorific.josa(name, '을', '를')} 시작하겠습니다."
    return (t, t)


def _close_lines(project: Dict[str, Any]) -> tuple:
    """닫는 말 — (자막, 발음). 여는 말과 같은 규칙으로 숫자를 가른다.

    ★ 사람이 쓰는 완성형은 「지금까지 새뮤얼슨의 경제학 19장 **거시경제학 개요**
      였습니다」인데, 그 **주제(거시경제학)는 프로젝트 어디에도 저장돼 있지 않다**
      (`deck_subtitle` 은 책 이름이고 `sections` 는 「제19장」 하나뿐이다).
      없는 것을 지어내면 매번 틀린 주제를 소리 내어 읽게 된다.
    ★ **「개요」도 뺀다**(2026-08-17). 요약이 아닌 장에서는 틀린 말이 되고,
      맞는 말을 넣을 자리는 그 장의 자막 칸이다 — 여기서 지어낼 것이 아니다.
      「지금까지 새뮤얼슨의 경제학 이십일 장이었습니다」로 끝난다.
    """
    book, n = _chapter(project)
    title = str(project.get("title") or "").strip()
    if book and n:
        return (f"지금까지 {book} {n}장이었습니다. 들어주셔서 감사합니다.",
                f"지금까지 {book} {honorific.sino(n)} 장이었습니다. "
                f"들어주셔서 감사합니다.")
    name = f"{book} {title}".strip() or "이번 장"
    t = (f"지금까지 {name}"
         + honorific.josa(name, "이었습니다", "였습니다")
         + ". 들어주셔서 감사합니다.")
    return (t, t)


def _fix_ends(out: Dict[str, Any], slides: List[Dict[str, Any]],
              project: Dict[str, Any], cps: float, job) -> None:
    """표지 장과 맺음 장의 대본을 고정 문구로 갈아 끼운다."""
    op_srt, op_say = _open_lines(project)
    cl_srt, cl_say = _close_lines(project)
    fixed = {"cover": (op_srt, op_say), "closing": (cl_srt, cl_say)}

    for s in slides:
        pair = fixed.get(s.get("kind") or "")
        if not pair:
            continue
        srt, say = pair
        key = str(s["no"])
        cur = out.get(key) or {}
        if (cur.get("srt_text") or "") == srt and (cur.get("narration_text") or "") == say:
            continue
        # 이미 하십시오체라 to_polite 를 태우지 않는다
        out[key] = {**cur, "srt_text": srt, "narration_text": say,
                    "narration_seconds": est_sec(say, cps),
                    "budget_sec": cur.get("budget_sec") or 0,
                    "over_sec": 0, "from": "고정"}
        job.add_log(f"  {s['no']}장({s.get('kind')}) 고정 문구로 — {srt}")


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s6-script"]

    deck = cached_data(pid, slug, "s2b-outline") or {}
    slides = deck.get("slides") or []
    if not slides:
        raise RuntimeError("구조 설계(s2b-outline)를 먼저 돌리세요")
    dec = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {})
    frames = (cached_data(pid, slug, "s1-frames") or {}).get("items", {})

    cps = float((project.get("narration") or cfg["narration"]).get("chars_per_sec", 5.7))
    ovr = ws.load_overrides(pid, slug)
    target_sec = float(ovr.get("target_min") or 0) * 60
    budget = budgets(slides, frames, ovr.get("slides", {}), target_sec)
    if target_sec:
        job.add_log(f"목표 {target_sec / 60:.0f}분 — 예산 합계 "
                    f"{sum(budget.values()) / 60:.1f}분")

    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "script.md").read_text(encoding="utf-8")

    # ★ 이미 나온 장은 다시 사지 않는다.
    #   묶음 하나가 실패해도 나머지는 살아남게 해 뒀는데, 재시도할 때 전부 다시
    #   부르면 실패 하나가 매번 전체 값을 물린다. 실패한 묶음만 채운다.
    prior = (cached_data(pid, slug, "s6-script") or {}).get("slides", {}) if not force else {}

    # ★ **원고가 대본을 들고 왔으면 그것을 쓴다.** 작가 에이전트가 `data-say` 에
    #   그 장에서 말할 것을 적어 보낸다(`tools/split_sections.mjs` 가 실어 온다).
    #   그것을 힌트로만 쓰고 Claude 에게 다시 쓰게 하면 두 가지를 잃는다 —
    #   화면 문구를 쓴 쪽이 말도 같이 썼다는 일관성, 그리고 $1 짜리 호출.
    #   2026-08-14 실측: 29장에 9,105자(20분)가 이미 원고에 들어 있었는데
    #   저희는 그걸 버리고 다시 쓰고 있었다.
    # ★ 자막과 발음이 **같은 글**이 된다. 원고가 발음까지 갈라 주면 그때 나눈다
    #   (`data-speak` 같은 칸). 그때까지는 숫자·영문을 TTS 가 어떻게 읽는지
    #   사람이 발음 화면에서 고치면 된다.
    from_ms: Dict[str, Any] = {}
    for s in slides:
        t = clean(s.get("say"))
        if not t:
            continue
        old = prior.get(str(s["no"])) or {}
        # ★ **원고가 이긴다.** 캐시에 있어도 그것이 Claude 가 쓴 것이면 원고로
        #   갈아 끼운다. 원고는 출처이고 Claude 는 원고가 없을 때의 대타다.
        #   예전에는 「캐시에 있으면 넘어간다」를 원고 검사보다 **먼저** 걸어서,
        #   원고가 돌아와도 옛 대본을 붙들고 있었다(2026-08-17 실측: 원고 6,100자가
        #   되살아났는데 대본은 Claude 가 쓴 2,169자 그대로였다).
        #   사람이 화면에서 고친 것은 오버라이드에 따로 얹히므로 여기서 안 잃는다.
        # ★ **발음은 늘 자막에서 만든다.** 원고가 `data-read` 를 실어 보내도 쓰지
        #   않는다(2026-08-17).
        #   그쪽 발음은 원고가 길이를 재려고 만든 것이라 우리 규칙과 다를 수 있고,
        #   출처가 둘이면 어느 쪽이 소리로 나갔는지 알 수 없게 된다.
        #   `read` 는 캐시까지 실어 나르되 여기서는 참고하지 않는다.
        # ★ 괄호 걷기 · 하십시오체 · 숫자 · 퍼센트를 한 함수가 다 한다. 화면의
        #   「자막에서 발음 만들기」도 같은 함수를 부른다 — 규칙이 두 벌이면
        #   한쪽으로 굽고 다른 쪽으로 검수하게 된다.
        spoken = honorific.for_speech(t)
        # ★ 넘어가는 조건은 **원고와 발음이 둘 다 지금 것과 같을 때**다.
        #   「출처가 원고면 넘어간다」로 두면 원고가 그대로여도 **변환기가 바뀐
        #   것을 못 따라간다.** 2026-08-17 에 `합니다` 를 `합니입니다` 로 바꾸던
        #   버그를 고쳤는데, 그 검사가 먼저 걸려서 고친 변환기가 32장에 닿지
        #   않았다(182개 문장이 그대로 남았다).
        #   사람이 화면에서 고친 것은 오버라이드에 따로 얹히므로 여기서 안 잃는다.
        if (old and clean(old.get("srt_text")) == t
                and clean(old.get("narration_text")) == clean(spoken)):
            continue                       # 이미 이 원고를 이 변환기로 만들어 뒀다
        from_ms[str(s["no"])] = {
            "srt_text": t, "narration_text": spoken,
            "narration_seconds": est_sec(spoken, cps),
            "budget_sec": budget[s["no"]], "from": "원고",
        }
    if from_ms:
        job.add_log(f"원고가 들고 온 대본 {len(from_ms)}장 — 그대로 씁니다(공짜)")
    prior = {**prior, **from_ms}

    todo = [s for s in slides if str(s["no"]) not in prior]
    if prior:
        job.add_log(f"이미 나온 {len(prior)}장 재사용 · 남은 {len(todo)}장")

    CHUNK = int(cfg.get("script_chunk", 6))
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    job.add_log(f"{len(slides)}장 → {len(chunks)}묶음 (묶음당 {CHUNK}장)")
    job.progress(0, len(chunks), "대본")

    out: Dict[str, Any] = dict(prior)
    warn: List[str] = []
    total_cost = 0.0
    model_used = ""
    prev_tail = ""

    for ci, chunk in enumerate(chunks, 1):
        if job.canceled:
            warn.append(f"{ci}묶음에서 취소됨")
            break
        p = ClaudeProvider(
            model=(project.get("models") or cfg["models"]).get("script")
                  or cfg["models"]["script"],
            effort=cfg["effort"].get("script", "high"),
            allowed_tools=[],          # 레포를 다시 읽지 않는다 — 재료는 이미 왔다
            max_turns=1,
            budget_usd=cfg["budget_usd"]["per_stage"],
            # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
            on_activity=lambda s: job.progress(0, 1, s),
        )
        model_used = p.model
        nos = [s["no"] for s in chunk]
        try:
            raw = p.structured(
                system,
                [{"role": "user",
                  "content": build_brief(chunk, deck, dec, budget, prev_tail)}],
                schema=SCHEMA)
        except Exception as e:  # noqa: BLE001
            # 한 묶음이 실패해도 나머지는 계속한다
            warn.append(f"{ci}묶음({nos}) 실패: {type(e).__name__}: {str(e)[:120]}")
            job.add_log(f"  {ci}/{len(chunks)} 실패 — 계속")
            total_cost += p.last_cost_usd
            continue

        total_cost += p.last_cost_usd
        want = set(nos)
        got = 0
        for r in raw.get("slides") or []:
            no = int(r.get("no") or 0)
            if no not in want:
                warn.append(f"요청하지 않은 슬라이드 {no} → 버림")
                continue
            srt = clean(r.get("srt_text"))
            nar = clean(r.get("narration_text")) or srt
            if not srt:
                warn.append(f"{no}: 자막이 비어 있다")
                continue
            sec = est_sec(nar, cps)
            rec = {"srt_text": srt, "narration_text": nar,
                   "narration_seconds": sec, "budget_sec": budget[no]}
            # ★ 초과 판정은 **영상 장에만** 건다.
            #   텍스트 장의 목표 초는 길이를 잡아 주는 기준값일 뿐 제약이 아니다 —
            #   화면이 멈춰 있어도 되므로 대본이 길어도 아무것도 깨지지 않는다.
            #   영상은 다르다. 클립이 끝나고 말이 남으면 화면이 정지한 채 들린다.
            # ★ 이제 초과는 문제가 아니다. 재생기가 **둘 중 긴 쪽을 기다리고**
            #   영상이 짧으면 마지막 프레임에서 선다. 문제는 반대 — 영상은 도는데
            #   말이 모자란 경우다. 그걸 잡는다.
            is_video = any(s["no"] == no and s.get("video_id") for s in chunk)
            short = round(budget[no] - sec, 1)
            if is_video and short > 3.0:
                rec["short_sec"] = short
                warn.append(f"{no}: 영상이 {short:.0f}초 더 도는데 말이 없다")
            out[str(no)] = rec
            got += 1

        tail = None
        for s in reversed(chunk):
            if str(s["no"]) in out:
                tail = out[str(s["no"])]["srt_text"]
                break
        if tail:
            prev_tail = tail[-160:]

        job.progress(ci, len(chunks), f"{ci}/{len(chunks)}묶음 · ${total_cost:.2f}")
        job.add_log(f"  {ci}/{len(chunks)} {nos} → {got}장 · ${p.last_cost_usd:.3f}")

    _fix_ends(out, slides, project, cps, job)

    missing = [s["no"] for s in slides if str(s["no"]) not in out]
    if missing:
        warn.append(f"대본이 없는 장: {missing}")

    total_sec = round(sum(v["narration_seconds"] for v in out.values()), 1)
    over = [n for n, v in out.items() if v.get("over_sec")]
    job.add_log(f"{len(out)}장 · 합계 {total_sec:.0f}초 "
                f"({total_sec / 60:.1f}분) · 길이 초과 {len(over)}장 · ${total_cost:.3f}")

    return write_cache(pid, slug, "s6-script",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"slides": out, "total_sec": total_sec,
                             "chars_per_sec": cps},
                       code_version=stage.code_version,
                       model=model_used, cost_usd=total_cost,
                       status="degraded" if (missing or over) else "ok",
                       warnings=warn)


STAGES["s6-script"].run = run
