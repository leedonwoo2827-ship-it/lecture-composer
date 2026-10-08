"""도식 다시 그리기 — 요약노트·영상 원고에서 온 SVG 를 영상 테마 스타일로 **새로 그린다**(Claude).

    글자·숫자·구조는 원본 그대로, 선·채움·화살표·그림자만 테마(단정 스케치북)로.
    결과는 jobs/<잡>/redraw/<원본해시>.svg 에 캐시 — 같은 도식은 다시 부르지 않는다.
    검증(clean_svg)·글자 대조에 실패하면 **원본을 쓴다**(raster 가 색 치환 + 손그림 흔들림으로 톤만 맞춘다).

목표서: manuscript.redraw_figs (테마가 danjeong 이면 기본 true)
명령:   run.bat redraw --job J   (render 가 필요할 때 알아서도 부른다)
"""
from __future__ import annotations

import hashlib
import re
from html import unescape
from pathlib import Path
from typing import Any, Dict, List

from longform.config import REPO, Job
from longform.util import log, warn

PROMPT = REPO / "longform" / "prompts" / "redraw_svg.md"
_TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def enabled(job: Job) -> bool:
    from longform import theme
    dflt = theme.get(job) is not None
    v = job.get("manuscript.redraw_figs", None)
    return dflt if v is None else bool(v)


def _texts(svg: str) -> List[str]:
    """SVG 안 글자 — 공백을 지운 조각 목록(대조용)."""
    out = []
    for m in _TEXT.finditer(svg or ""):
        t = re.sub(r"\s+", "", unescape(_TAG.sub("", m.group(1))))
        if t:
            out.append(t)
    return out


def _same_words(a: str, b: str) -> bool:
    """원본 글자가 새 그림에 **다 있는가**(줄바꿈으로 tspan 이 쪼개질 수 있어 이어 붙여 비교)."""
    have = "".join(_texts(b))
    return all(t in have for t in _texts(a))


def _prompt(svg: str, th: Dict[str, Any]) -> str:
    fills = ", ".join(f"`{c}`" for c in (th["table_head"], th["bases"][1]["bg"], th["bases"][2]["bg"],
                                         th["bases"][3]["bg"], th["card_bg"]))
    return (PROMPT.read_text(encoding="utf-8")
            .replace("{ink}", th["ink"]).replace("{accent}", th["accent"])
            .replace("{fills}", fills).replace("{svg}", svg))


def redraw_one(job: Job, svg: str) -> str:
    from longform import theme
    from longform.s2_manuscript import call_llm, clean_svg, parse_json
    th = theme.get(job)
    if not th or svg.lstrip().lower().startswith("<table"):
        return svg                                   # 표는 CSS 가 모양을 맡는다
    key = hashlib.sha1((th["name"] + "\n" + svg).encode("utf-8")).hexdigest()[:16]
    cache = job.dir / "redraw" / f"{key}.svg"
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    bad = job.dir / "redraw" / f"{key}.failed"
    if bad.is_file():
        return svg
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc = parse_json(call_llm(job, _prompt(svg, th)))
        new = clean_svg((doc or {}).get("svg", ""))
    except Exception as e:                           # noqa: BLE001 — 실패해도 원본으로 간다
        warn(f"도식 다시 그리기 실패 — 원본을 씁니다: {e}")
        new = ""
    if not new or not _same_words(svg, new):
        if new:
            warn("다시 그린 도식의 글자가 원본과 달라 버립니다 — 원본을 씁니다")
        bad.write_text(new or "", encoding="utf-8")
        return svg
    cache.write_text(new, encoding="utf-8")
    return new


def redraw_all(job: Job, figs: List[str]) -> List[str]:
    if not enabled(job):
        return figs
    out = []
    for i, f in enumerate(figs, 1):
        out.append(redraw_one(job, f))
    n = sum(1 for a, b in zip(figs, out) if a != b)
    if figs:
        log(f"도식 다시 그리기 {n}/{len(figs)}")
    return out


def run(job: Job, only: List[str] | None = None) -> None:
    """잡의 모든 섹션 원고 도식을 미리 다시 그린다(렌더 전에 한꺼번에 — 렌더 중 Claude 대기를 줄인다)."""
    from longform.util import read_json
    for jf in sorted(job.manuscripts_dir.glob("L*/*.json")):
        if only and jf.parent.name not in only:
            continue
        man = read_json(jf, {}) or {}
        figs = man.get("figs") or []
        if figs:
            log(f"{jf.parent.name} {jf.stem} 도식 {len(figs)}개")
            redraw_all(job, figs)
