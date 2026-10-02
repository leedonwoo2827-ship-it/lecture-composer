"""s5 — 유튜브 메타(제목·설명·챕터·태그) + 썸네일(1280×720 PNG, codex 없이 HTML 로 굽기).

    meta/L03.json   {"title", "description", "tags", "thumbnail", "video", "playlist", "visibility"}

★ 유튜브 설명란에는 `<` `>` 를 쓸 수 없다(저장이 거부된다) — 지운다.
★ 제목 100자, 설명 5,000자 상한.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.raster import render_many
from longform.s2_manuscript import course
from longform.util import fmt_ts, log, read_json, warn, write_json

SUBJECT_COLOR = {1: "#1F4E79", 2: "#0f766e", 3: "#9a4d33"}


def _clean(s: str) -> str:
    return s.replace("<", "(").replace(">", ")")


def thumb_html(job: Job, L: Dict[str, Any]) -> str:
    col = SUBJECT_COLOR.get(int(L["subject_no"]), "#1F4E79")
    names = [s["title"].split(".", 1)[-1].strip() for s in L["sections"]]
    head = names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}"
    return f"""
<div style="position:absolute;inset:0;background:#F6F1E8"></div>
<div style="position:absolute;left:0;top:0;bottom:0;width:26px;background:{col}"></div>
<div style="position:absolute;left:70px;top:56px;font-size:34px;font-weight:800;color:#fff;background:{col};
  padding:8px 22px;border-radius:12px">{html.escape(course(job)['series'])} · {html.escape(L['subject'].split('·')[0].strip())}</div>
<div style="position:absolute;left:66px;top:140px;font-size:190px;font-weight:900;color:{col};letter-spacing:-6px;
  line-height:1">{L['no']}강</div>
<div style="position:absolute;left:70px;right:60px;top:372px;font-size:76px;font-weight:900;color:#1d2433;
  line-height:1.15;letter-spacing:-2px;word-break:keep-all">{html.escape(head)}</div>
<div style="position:absolute;left:70px;right:60px;bottom:52px;font-size:34px;font-weight:600;color:#475569;
  word-break:keep-all">{html.escape(' · '.join(names)[:70])}</div>
"""


def build(job: Job, L: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lid = L["id"]
    d = job.out_dir / lid
    video = d / f"{lid}.mp4"
    if not video.exists():
        warn(f"{lid} 완성 mp4 가 없습니다 — s4 먼저")
        return None
    ch = (read_json(d / f"{lid}.chapters.json", {}) or {})
    yt = job.get("youtube", {})
    names = [s["title"].split(".", 1)[-1].strip() for s in L["sections"]]

    tag = course(job)['series']
    title = f"[{tag}] {L['no']}강 {' · '.join(names)} | {L['subject'].split('·')[-1].strip()} 이론"
    if len(title) > 100:
        title = f"[{tag}] {L['no']}강 {names[0]} 외 | {L['subject'].split('·')[-1].strip()} 이론"[:100]

    lines: List[str] = [
        f"{course(job)['full']} {job.get('title') or ''} {L['no']}강 — {L['subject']}".replace('  ', ' '),
        "",
        "이번 강에서 다루는 것",
        *[f"- {s['title']}" for s in L["sections"]],
    ]
    if L.get("examples"):
        lines += ["", f"기출 맛보기 {len(L['examples'])}문항: "
                  + ", ".join(f"모의 {e['round']}회 {e['no']}번" for e in L["examples"])]
    if yt.get("site_url"):
        lines += ["", f"문제집·모의고사 750제·요약노트: {yt['site_url']}"]
    if ch.get("chapters"):
        lines += ["", "챕터"] + [f"{fmt_ts(c['t'])} {c['title']}" for c in ch["chapters"]]
    tags = list(dict.fromkeys((yt.get("tags") or []) + [L["subject"].split("·")[-1].strip()] + names[:5]))
    lines += ["", " ".join("#" + t.replace(" ", "") for t in tags[:8])]
    desc = _clean("\n".join(lines))[:4900]

    thumb = job.meta_dir / f"{lid}.thumb.png"
    render_many([(thumb_html(job, L), thumb)], w=1280, h=720)

    meta = {"lecture": lid, "title": _clean(title), "description": desc, "tags": tags,
            "video": str(video), "thumbnail": str(thumb),
            "srt": str(d / f"{lid}.srt") if (d / f"{lid}.srt").exists() else "",
            "playlist": yt.get("playlist") or "", "visibility": yt.get("visibility", "UNLISTED"),
            "duration_sec": ch.get("total_sec")}
    write_json(job.meta_dir / f"{lid}.json", meta)
    log(f"{lid} 메타 → {meta['title']}")
    return meta


def run(job: Job, only: Optional[List[str]] = None, force: bool = False) -> None:
    cur = read_json(job.dir / "curriculum.json")
    for L in cur["lectures"]:
        if only and L["id"] not in only:
            continue
        build(job, L)
