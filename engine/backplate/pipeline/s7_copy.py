# -*- coding: utf-8 -*-
"""S7 슬라이드 문구 — **구조는 그대로 두고 문체만 갈아 끼운다.**

    S2b 가 정한 것   장수 · 순서 · 번호 · 레인 · 무슨 장인지   ← 안 건드린다
    S7 이 정하는 것  각 장의 제목과 본문 문체                  ← 여기

문체를 바꾸려고 S2b 를 다시 돌리면 구성이 통째로 다시 짜여서 이미 OK 한 순서와
영상 배치가 날아간다. 그래서 문구만 따로 뗀다. 개조식으로 굽고 마음에 안 들면
광고로 다시 굽는 게 $0.5 짜리 결정이 된다.

    explain  설명문 — 완결된 문장, 존댓말
    bullet   개조식 — 체언 종결, 한 줄 한 사실
    pitch    광고   — 짧고 세게, 숫자를 앞세운다   ← 기본

★ **화면은 기능을 판다.** 사연·공감 유도·감정 서사는 프롬프트에서 금지한다.
  "십 년 경력인데 이력서 한 장으로 끝난다" 같은 문제 제기는 발표를 약하게 만든다.

이 단계는 **음성 대본을 건드리지 않는다.** 화면 문구와 입으로 말하는 것은 별개다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import config
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

TONES = {
    "explain": "설명문 — 완결된 문장, 존댓말, 한 장에 두세 문장",
    "bullet": "개조식 — 체언으로 끝내고 한 줄에 한 사실, 3~5줄",
    "pitch": "광고 — 짧고 세게, 숫자를 앞세운다, 제목 한 줄 + 본문 한두 문장",
}
DEFAULT_TONE = "pitch"
MD = re.compile(r"[*_`#>]|^\s*[-•]\s+", re.M)

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["no", "title", "body"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["slides"],
    "additionalProperties": False,
}


def clean(t: Any) -> str:
    return MD.sub("", str(t or "")).strip()


def build_brief(chunk: List[Dict[str, Any]], deck: Dict[str, Any],
                dec: Dict[str, Any], tone: str) -> str:
    lines: List[str] = [
        f"tone = {tone}   ({TONES.get(tone, '')})", "",
        f"# 발표\n{deck.get('deck_title') or ''}",
    ]
    if deck.get("deck_subtitle"):
        lines.append(deck["deck_subtitle"])
    lines.append("\n# 다시 쓸 장")
    for s in chunk:
        no = s["no"]
        lines.append(f"\n## {no}   종류: {s.get('kind')}")
        lines.append(f"현재 제목: {s.get('title') or ''}")
        if s.get("note"):
            lines.append(f"현재 본문: {s['note']}")
        if s.get("video_id"):
            lines.append("이 장에는 화면 녹화 영상이 붙는다 — 화면에서 되는 일을 말해라")
        if s.get("evidence_hint"):
            lines.append(f"근거 경로: {s['evidence_hint']}")
        d = dec.get(str(no))
        if d:
            lines.append("재료(레포에서 확인된 것):")
            for k, label in (("problem", "증상"), ("choice", "고른 것"),
                             ("rationale", "이유"), ("tradeoff", "포기한 것")):
                if d.get(k):
                    lines.append(f"  {label}: {d[k]}")
            for e in (d.get("evidence") or [])[:3]:
                lines.append(f"  경로: {e.get('ref')}")
    lines.append("\n주어진 no 만 채워라. JSON 만 출력.")
    return "\n".join(lines)


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s7-copy"]

    deck = cached_data(pid, slug, "s2b-outline") or {}
    slides = deck.get("slides") or []
    if not slides:
        raise RuntimeError("구조 설계(s2b-outline)를 먼저 돌리세요")
    dec = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {})

    tone = str(project.get("slide_tone") or cfg.get("slide_tone") or DEFAULT_TONE)
    if tone not in TONES:
        job.add_log(f"모르는 문체 {tone!r} → {DEFAULT_TONE}")
        tone = DEFAULT_TONE

    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "copy.md").read_text(encoding="utf-8")

    # ★ 이미 나온 장은 다시 사지 않는다.
    #   묶음 하나가 실패해도 나머지는 살아남게 해 뒀는데, 재시도할 때 전부 다시
    #   부르면 실패 하나가 매번 전체 값을 물린다. 실패한 묶음만 채운다.
    prior = (cached_data(pid, slug, "s7-copy") or {}).get("slides", {}) if not force else {}
    prior = {k: v for k, v in prior.items() if v.get("tone") == tone}
    todo = [s for s in slides if str(s["no"]) not in prior]
    if prior:
        job.add_log(f"이미 나온 {len(prior)}장 재사용 · 남은 {len(todo)}장")

    CHUNK = int(cfg.get("copy_chunk", 8))
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    job.add_log(f"문체 {tone} · {len(slides)}장 → {len(chunks)}묶음")
    job.progress(0, len(chunks), f"문구 ({tone})")

    out: Dict[str, Any] = dict(prior)
    warn: List[str] = []
    total_cost = 0.0
    model_used = ""

    for ci, chunk in enumerate(chunks, 1):
        if job.canceled:
            warn.append(f"{ci}묶음에서 취소됨")
            break
        p = ClaudeProvider(
            model=(project.get("models") or cfg["models"]).get("script")
                  or cfg["models"]["script"],
            effort=cfg["effort"].get("script", "high"),
            allowed_tools=[], max_turns=1,
            budget_usd=cfg["budget_usd"]["per_stage"],
            # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
            on_activity=lambda s: job.progress(0, 1, s),
        )
        model_used = p.model
        nos = [s["no"] for s in chunk]
        try:
            raw = p.structured(system,
                               [{"role": "user",
                                 "content": build_brief(chunk, deck, dec, tone)}],
                               schema=SCHEMA)
        except Exception as e:  # noqa: BLE001
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
            title = clean(r.get("title"))
            if not title:
                warn.append(f"{no}: 제목이 비어 원문 유지")
                continue
            out[str(no)] = {"title": title, "body": clean(r.get("body")), "tone": tone}
            got += 1
        job.progress(ci, len(chunks), f"{ci}/{len(chunks)} · ${total_cost:.2f}")
        job.add_log(f"  {ci}/{len(chunks)} {nos} → {got}장 · ${p.last_cost_usd:.3f}")

    missing = [s["no"] for s in slides if str(s["no"]) not in out]
    if missing:
        warn.append(f"문구가 없는 장 {len(missing)}개(원문 유지): {missing}")
    long_body = [n for n, v in out.items() if len(v["body"]) > 260]
    if long_body:
        job.add_log(f"본문이 긴 장 {len(long_body)}개 — 화면이 문서가 되고 있습니다")

    job.add_log(f"{len(out)}장 · 문체 {tone} · ${total_cost:.3f}")

    return write_cache(pid, slug, "s7-copy",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"slides": out, "tone": tone},
                       code_version=stage.code_version,
                       model=model_used, cost_usd=total_cost,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s7-copy"].run = run
