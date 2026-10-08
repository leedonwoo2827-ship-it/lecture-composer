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


def thumb_html_themed(job: Job, L: Dict[str, Any], th: Dict[str, Any]) -> str:
    """테마 썸네일 — 깊은 남색 바탕 · 큰 강 번호 · 굵은 제목 · 덩어리 두 개 · 반짝이."""
    import math
    import random
    rnd = random.Random(int(L["no"]))
    names = [s["title"].split(".", 1)[-1].strip() for s in L["sections"]]
    head = names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}"
    base = th["bases"][(int(L["no"]) - 1) % len(th["bases"])]

    def blob(cx, cy, r, col, seed):
        g = random.Random(seed)
        pts = [(cx + r * (1 + g.uniform(-.15, .15)) * math.cos(2 * math.pi * i / 9),
                cy + r * (1 + g.uniform(-.15, .15)) * math.sin(2 * math.pi * i / 9)) for i in range(9)]
        d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts) + "Z"
        return (f'<svg style="position:absolute;inset:0" width="1280" height="720"><path d="{d}" fill="{col}" '
                f'stroke-linejoin="round" stroke="{col}" stroke-width="60"/></svg>')
    return f"""
<div style="position:absolute;inset:0;background:{th['deep']}"></div>
{blob(1050 + rnd.uniform(-20, 20), 300, 230, th['accent'], 1)}
{blob(-20, 760, 230, base['blob2'], 2)}
<div style="position:absolute;left:70px;top:58px;font-size:30px;font-weight:900;color:{th['on_deep']};letter-spacing:-1px">
  {html.escape(course(job)['short'])}<span style="color:{th['mustard']}">.</span></div>
<div style="position:absolute;right:70px;top:66px;font-size:20px;font-weight:700;letter-spacing:.3em;color:rgba(244,241,234,.65)">
  {html.escape(L['subject'].split('·')[0].strip())}</div>
<div style="position:absolute;left:66px;top:150px;font-size:200px;font-weight:900;color:{th['mustard']};letter-spacing:-8px;line-height:1">{L['no']}강</div>
<div style="position:absolute;left:70px;right:330px;top:385px;font-size:78px;font-weight:900;color:{th['on_deep']};
  line-height:1.12;letter-spacing:-3px;word-break:keep-all">{html.escape(head)}</div>
<svg style="position:absolute;left:72px;top:560px" width="260" height="28" viewBox="0 0 260 28"><path d="M4 14 Q12 2 28 14 Q44 26 60 14 Q76 2 92 14 Q108 26 124 14 Q140 2 156 14 Q172 26 188 14 Q204 2 220 14 Q236 26 252 14" fill="none" stroke="{th['accent']}" stroke-width="6" stroke-linecap="round"/></svg>
<div style="position:absolute;left:70px;right:60px;bottom:48px;font-size:30px;font-weight:600;color:rgba(244,241,234,.75);
  word-break:keep-all">{html.escape(' · '.join(names)[:60])}</div>
<svg style="position:absolute;left:1120px;top:520px" width="70" height="70" viewBox="0 0 40 40"><path d="M20 0 C21.5 13 27 18.5 40 20 C27 21.5 21.5 27 20 40 C18.5 27 13 21.5 0 20 C13 18.5 18.5 13 20 0Z" fill="{th['on_deep']}"/></svg>
"""


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
    from longform import theme as vtheme
    th = vtheme.get(job)
    if th:
        render_many([(thumb_html_themed(job, L, th), thumb)], w=1280, h=720,
                    theme=th["name"])
    else:
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
