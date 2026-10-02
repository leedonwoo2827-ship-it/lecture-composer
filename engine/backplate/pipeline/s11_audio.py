# -*- coding: utf-8 -*-
"""S11 자막·큐시트 — 대본 + 실제 음성 길이 → SRT · 큐시트 · 타임라인.

두 가지를 만든다:

    08_자막/005.srt        장별 SRT. 슬라이드 페이지가 자막으로 띄운다
    08_자막/cue-sheet.md   영상팀 인계용. 몇 분 몇 초에 무엇이 나오는가
    08_자막/cue-sheet.csv  같은 것, 엑셀용(BOM)

★ **자막은 `srt_text`, 소리는 `narration_text`.** 화면에 "2vCPU" 로 뜨고 소리는
  "투 브이씨피유" 로 난다. 큐 분할은 자막 쪽 문장으로 하고, 길이만 실제 wav 에서
  가져온다.

★ 타이밍은 **강제정렬이 아니라 추정**이다(글자수 비례). 큐시트를 "초안" 으로
  부르는 이유고, 프리미어에서 미세조정하는 전제가 오히려 맞다.

음성이 없는 장은 대본 추정치로 타임라인을 잇는다 — 전체 길이를 미리 알아야
"발표 몇 분짜리인가" 를 답할 수 있다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from core import config, workspace as ws
from pipeline.registry import STAGES, cached_data, narration_of, write_cache

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vendor.vw_srt import (auto_time_cues, format_timestamp,  # noqa: E402
                           make_multi_srt, split_into_cues)


def hhmmss(sec: float) -> str:
    s = max(0.0, float(sec))
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s11-audio"]

    # ★ 손편집을 얹은 대본. 자막 문장을 다듬으면 SRT·큐시트가 따라와야 한다.
    script = narration_of(pid, slug)
    if not script:
        raise RuntimeError("대본(s6-script)을 먼저 돌리세요")
    audio = (cached_data(pid, slug, "s10-tts") or {}).get("slides", {})
    outline = cached_data(pid, slug, "s2b-outline") or {}
    slides = outline.get("slides") or []
    # ★ 편집 구간은 오버라이드에 있다. 큐시트에 적어 보내야 영상 편집 프로그램에서
    #   같은 자리를 자를 수 있다 — 이 앱은 재인코딩하지 않기 때문이다.
    ov_slides = ws.load_overrides(pid, slug).get("slides", {})
    sec_title = {s["id"]: s.get("title") for s in outline.get("sections") or []}

    sub_dir = ws.step_dir(pid, slug, "subtitle")
    step_name = ws.STEPS["subtitle"][0]

    out: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    warn: List[str] = []
    t = 0.0
    n_est = 0

    job.progress(0, len(slides), "자막")
    for i, sl in enumerate(slides, 1):
        no = sl["no"]
        key = str(no)
        sc = script.get(key) or {}
        srt_text = (sc.get("srt_text") or "").strip()
        au = audio.get(key) or {}

        # 실측이 있으면 실측, 없으면 대본 추정
        dur = au.get("duration_sec")
        source = au.get("source")
        if not dur:
            dur = sc.get("est_sec") or 0.0
            source = source or "none"
            if srt_text:
                n_est += 1

        cues = split_into_cues(srt_text) if srt_text else []
        timed = auto_time_cues(cues, dur) if (cues and dur) else []
        srt = make_multi_srt(timed)
        fname = ""
        if srt:
            ws.write_text(sub_dir / f"{no:03d}.srt", srt)
            fname = f"{step_name}/{no:03d}.srt"

        out[key] = {
            "start_sec": round(t, 2), "duration_sec": round(float(dur), 2),
            "end_sec": round(t + float(dur), 2),
            "source": source, "file": au.get("file"),
            "srt": fname, "cues": len(timed),
            "measured": bool(au.get("duration_sec")),
        }
        clip = (ov_slides.get(key) or {}).get("clip") or {}
        cliptxt = ""
        if clip:
            bits = [f"{float(clip.get('start') or 0):.1f}~{float(clip.get('end') or 0):.1f}s"]
            if float(clip.get("speed") or 1) != 1:
                bits.append(f"{clip['speed']}배속")
            for a, b in (clip.get("cuts") or []):
                bits.append(f"삭제 {a:.1f}~{b:.1f}")
            cliptxt = " · ".join(bits)
        rows.append({
            "no": no, "start": t, "sec": float(dur), "clip": cliptxt,
            "section": sec_title.get(sl.get("section")) or sl.get("section"),
            "title": sl.get("title") or "", "media": sl.get("media_kind") or "",
            "video": sl.get("video_id") or "", "source": source,
            "srt_text": srt_text,
        })
        t += float(dur)
        if i % 5 == 0 or i == len(slides):
            job.progress(i, len(slides), f"{i}/{len(slides)}")

    total = round(t, 1)

    # ── 큐시트 (영상팀 인계용) ────────────────────────────────────────────
    md: List[str] = [f"# {outline.get('deck_title') or slug} — 큐시트 초안", ""]
    md.append(f"총 {len(slides)}장 · {total / 60:.1f}분 ({total:.0f}초)")
    md.append("")
    md.append("타이밍은 글자수 비례 **추정**입니다. 편집에서 맞춰 주세요.")
    md.append("")
    md.append("| # | 시작 | 길이 | 섹션 | 슬라이드 | 미디어 | 음성 |")
    md.append("|---:|---|---:|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['no']} | {hhmmss(r['start'])} | {r['sec']:.1f}s | "
                  f"{r['section']} | {r['title']} | "
                  f"{r['media']}{(' ' + r['video']) if r['video'] else ''}"
                  f"{(' — ' + r['clip']) if r.get('clip') else ''} | {r['source']} |")
    md.append("")
    md.append("## 대본")
    for r in rows:
        if not r["srt_text"]:
            continue
        md.append(f"\n**{r['no']}. {r['title']}**  `{hhmmss(r['start'])}`\n")
        md.append(r["srt_text"])
    ws.write_text(sub_dir / "cue-sheet.md", "\n".join(md))

    # csv — 엑셀이 utf-8 을 알아보게 BOM
    csv: List[str] = ["번호,시작초,길이초,시작,섹션,슬라이드,미디어,영상,편집구간,음성,자막"]
    for r in rows:
        cells = [str(r["no"]), f"{r['start']:.2f}", f"{r['sec']:.2f}",
                 hhmmss(r["start"]), r["section"] or "", r["title"],
                 r["media"], r["video"], r.get("clip", ""), r["source"], r["srt_text"]]
        csv.append(",".join('"' + str(c).replace('"', '""') + '"' for c in cells))
    ws.write_text(sub_dir / "cue-sheet.csv", "\n".join(csv), bom=True)

    if n_est:
        warn.append(f"{n_est}장은 음성이 없어 대본 추정 길이를 썼다")
    job.add_log(f"자막 {sum(1 for v in out.values() if v['srt'])}장 · "
                f"전체 {total / 60:.1f}분 · 큐시트 {sub_dir / 'cue-sheet.md'}")

    return write_cache(pid, slug, "s11-audio",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"slides": out, "total_sec": total,
                             "cue_md": f"{step_name}/cue-sheet.md",
                             "cue_csv": f"{step_name}/cue-sheet.csv"},
                       code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s11-audio"].run = run
