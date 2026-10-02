"""s4 — 섹션 mp4 를 강 하나로 잇고(무손실 concat), 음량을 −16 LUFS 로 맞추고, 챕터·합본 자막을 만든다.

    out/L03/parts/s2-05.mp4 …  →  out/L03/L03.mp4, L03.srt, L03.chapters.json

★ 섹션들은 같은 backplate 설정(H.264 High / AAC 48k)으로 구워졌으므로 `-c copy` 로 잇는다.
★ 장 길이 = 오디오 + 0.45초(render/hyper.py TAIL_SEC). 섹션 시작은 실제 mp4 길이(ffprobe)로 누적한다.
★ 유튜브 챕터 규칙: 첫 줄 0:00, 3개 이상, 각 10초 이상.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.state import State, sha
from longform.util import ffprobe_duration, fmt_ts, log, need, read_json, run as run_cmd, warn, write_json

TAIL_SEC = 0.45
TS_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _t(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def _fmt_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _read_srt(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = block.strip().split("\n")
        for i, ln in enumerate(lines):
            m = TS_RE.search(ln)
            if m:
                g = m.groups()
                cues.append({"a": _t(*g[:4]), "b": _t(*g[4:]), "text": "\n".join(lines[i + 1:])})
                break
    return cues


def _loudnorm(src: Path, dst: Path, i: float = -16, tp: float = -1.5, lra: float = 11) -> None:
    ff = need("ffmpeg")
    p = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(src), "-af",
                        f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        warn("loudnorm 측정 실패 — 1패스로 진행")
        af = f"loudnorm=I={i}:TP={tp}:LRA={lra}"
    else:
        d = json.loads(m.group(0))
        af = (f"loudnorm=I={i}:TP={tp}:LRA={lra}:measured_I={d['input_i']}:measured_TP={d['input_tp']}:"
              f"measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:offset={d['target_offset']}:linear=true")
    run_cmd([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-c:v", "copy",
             "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", str(dst)])


def burn_subtitles(job: Job, video: Path, srt: Path) -> None:
    """합본 자막을 화면 **하단**에 굽는다(반투명 띠 + 흰 글씨). 자막 없는 판은 <강>.clean.mp4 로 남긴다.

    ★ 렌더 단계가 subtitles.burn_in 일 때 아래 14% 를 비워 두므로 라벨·도식과 겹치지 않는다.
    ★ libass 의 SRT 기준 높이는 288 — FontSize 13 ≈ 1080p 에서 약 49px, MarginV 14 ≈ 52px.
    """
    st = job.get("subtitles", {}) or {}
    clean = video.with_name(video.stem + ".clean.mp4")
    video.replace(clean)
    style = ",".join([
        f"FontName={st.get('font', 'Malgun Gothic')}", f"FontSize={st.get('size', 13)}",
        "PrimaryColour=&H00FFFFFF", "OutlineColour=&H80000000", "BackColour=&H80000000",
        f"BorderStyle={st.get('border_style', 3)}", "Outline=1", "Shadow=0",
        f"MarginV={st.get('margin_v', 14)}", "Alignment=2"])
    # ★ subtitles 필터는 경로의 ':' 를 구분자로 읽는다 → 같은 폴더에서 파일 이름만 넘긴다
    run_cmd([need("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", clean.name,
             "-vf", f"subtitles={srt.name}:force_style='{style}'",
             "-c:v", "libx264", "-crf", str(st.get("crf", 20)), "-preset", "medium", "-pix_fmt", "yuv420p",
             "-c:a", "copy", "-movflags", "+faststart", video.name], cwd=video.parent)
    log(f"자막을 화면 하단에 구웠습니다 → {video.name} (자막 없는 판: {clean.name})")


def stitch(job: Job, L: Dict[str, Any], state: State, force: bool) -> Optional[Path]:
    lid = L["id"]
    d = job.out_dir / lid
    parts = [d / "parts" / f"{s['id']}.mp4" for s in L["sections"]]
    if not all(p.exists() for p in parts):
        miss = [p.name for p in parts if not p.exists()]
        warn(f"{lid} 섹션 mp4 가 모자랍니다({', '.join(miss)}) — s3 먼저")
        return None
    out = d / f"{lid}.mp4"
    h = sha(*[p.stat().st_size for p in parts], [p.name for p in parts], job.get("subtitles", {}))
    if not force and state.done(lid, "s4", h) and out.exists():
        log(f"{lid} 이어붙이기 — 그대로")
        return out

    lst = d / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    raw = d / f"{lid}.raw.mp4"
    run_cmd([need("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-c", "copy", str(raw)])
    _loudnorm(raw, out)
    raw.unlink(missing_ok=True)

    # 챕터·자막
    chapters: List[Dict[str, Any]] = []
    cues: List[Dict[str, Any]] = []
    off = 0.0
    for sec, p in zip(L["sections"], parts):
        tm = read_json(p.with_suffix(".timing.json"), {}) or {}
        t = off
        last_group = None
        for s in tm.get("slides") or []:
            grp = s.get("group") or ""
            if grp and grp != last_group:
                chapters.append({"t": t, "title": grp})
                last_group = grp
            for c in _read_srt(Path(s["srt"])) if s.get("srt") else []:
                cues.append({"a": t + c["a"], "b": t + c["b"], "text": c["text"]})
            au = float(s.get("audio_sec") or 0)
            t += (au + TAIL_SEC) if au > 0 else 4.0
        off += ffprobe_duration(p)

    total = ffprobe_duration(out)
    # 규칙 맞추기: 0:00 시작, 10초 미만 간격은 합치기
    # ★ 표지(제목만, 몇 초)는 묶음이 없다 → 첫 챕터가 10초 안에 시작하면 그것을 0:00 으로 당긴다
    #   (안 그러면 「오프닝」이 둘 생기고 첫 소주제가 10초 규칙에 밀려 사라진다 — 2026-10-01 실측)
    chapters = sorted(chapters, key=lambda c: c["t"])
    if chapters and chapters[0]["t"] < 10:
        chapters[0]["t"] = 0.0
    fixed: List[Dict[str, Any]] = []
    for c in chapters:
        if fixed and c["title"] == fixed[-1]["title"]:
            continue
        if fixed and c["t"] - fixed[-1]["t"] < 10:
            continue                     # 10초 안에 또 바뀌면 앞 챕터를 남긴다(유튜브 규칙)
        fixed.append(c)
    if not fixed or fixed[0]["t"] > 0:
        fixed.insert(0, {"t": 0.0, "title": "오프닝"})
    fixed[0]["t"] = 0.0
    if fixed and total - fixed[-1]["t"] < 10 and len(fixed) > 1:
        fixed.pop()
    write_json(d / f"{lid}.chapters.json", {"total_sec": total, "chapters": fixed})

    with (d / f"{lid}.srt").open("w", encoding="utf-8-sig", newline="\r\n") as fh:
        for i, c in enumerate(cues, 1):
            fh.write(f"{i}\n{_fmt_srt(c['a'])} --> {_fmt_srt(c['b'])}\n{c['text']}\n\n")

    if job.get("subtitles.burn_in", False) and cues:
        burn_subtitles(job, out, d / f"{lid}.srt")
    state.mark(lid, "s4", h, sec=round(total, 1), chapters=len(fixed))
    log(f"{lid} 완성 {fmt_ts(total)} · 챕터 {len(fixed)}개 · 자막 {len(cues)}개 → {out}")
    if total < 25 * 60 or total > 45 * 60:
        warn(f"{lid} 길이 {fmt_ts(total)} — 목표 30~40분에서 벗어났습니다(curriculum 분량 조정 고려)")
    return out


def run(job: Job, only: Optional[List[str]] = None, force: bool = False) -> None:
    cur = read_json(job.dir / "curriculum.json")
    state = State(job)
    for L in cur["lectures"]:
        if only and L["id"] not in only:
            continue
        stitch(job, L, state, force)
