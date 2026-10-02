# -*- coding: utf-8 -*-
"""S12 영상 렌더 — 슬라이드 화면 + 내레이션 음성을 이어 붙여 mp4 한 편으로.

S9(완성본)는 **재생되는 페이지**를 만들고, 이 단계는 **파일 하나**를 만든다.

    1) `/preview/{pid}?n=` 로 그 장 화면만 시작 문 없이 정지 캡처하고
       — 줄이 하나씩 뜨는 장은 **뜨는 순간마다 한 컷씩** 찍는다
    2) 컷마다 다음 컷 시각까지 머무는 조각을 ffmpeg 로 만들고
       (한 장의 내레이션은 자르지 않고 통째로 깐다)
    3) 조각을 번호 순서로 이어 붙인다.

예전에는 이 자리를 **실시간 화면녹화**가 맡았다. 버린 이유는 세 가지다 —
지지직 소리가 섞이고, 크롬이 mp4 안에 opus 를 넣어 줘서 폰에서 검은 화면이 뜨고,
18분짜리를 얻으려면 18분을 실제로 재생해야 했다. 여기는 실시간이 아니라 계산이다:
조각 길이 자체가 오디오 길이라 화면과 소리가 어긋날 자리가 없고, 몇 번을 돌려도
같은 파일이 나온다.

화면 캡처는 Playwright(Node) 가 한다. 이 서버 프로세스 자신에게 HTTP 로 붙는다
(`tools/render_frames.mjs`) — 새 브라우저 컨텍스트가 렌더된 페이지를 그대로 본다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from core import config, workspace as ws
from pipeline.registry import STAGES, write_cache
from pipeline.s8_assemble import compose
from render import ff

APP = Path(__file__).resolve().parent.parent
FRAME_SCRIPT = APP / "tools" / "render_frames.mjs"


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s12-video"]
    root = ws.project_dir(pid, slug)

    deck, _warn0 = compose(pid, slug, project)
    slides = [s for s in (deck.get("slides") or []) if not s.get("drop")]
    if not slides:
        raise RuntimeError("장이 없습니다 — 목차부터 확정하세요")

    node = shutil.which("node")
    if not node:
        raise RuntimeError("node 를 찾지 못했습니다 — Node.js 설치를 확인하세요")

    dist = ws.step_dir(pid, slug, "dist")
    frames_dir = ws.cache_dir(pid, slug) / "_video_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # ── 1) 화면 캡처 ─────────────────────────────────────────────────────
    job.progress(0, 3, "화면 캡처")
    # ★ **실제로 떠 있는 포트**를 따른다. 설정값만 보면, 다른 포트로 띄운 서버가
    #   자기 화면을 못 찾고 옆에 떠 있는 다른 서버(옛 코드일 수도 있다)에 붙는다.
    #   run.bat 이 `SHOWCASE_PORT` 를 읽으므로 같은 값을 여기서도 본다.
    port = int(os.environ.get("SHOWCASE_PORT") or cfg.get("port") or 5178)
    base = f"http://127.0.0.1:{port}"
    cmd = [node, str(FRAME_SCRIPT), "--pid", str(pid), "--out", str(frames_dir), "--base", base]
    proc = subprocess.Popen(cmd, cwd=str(APP), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        if line:
            job.add_log("  " + line[:160])
        if job.canceled:
            proc.terminate()
            raise RuntimeError("사용자가 취소함")
    proc.wait(timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"화면 캡처 실패(exit {proc.returncode}) — "
                           "Node/Playwright 설치를 확인하세요(npm install && "
                           "npx playwright install chromium)")

    # ── 2) 장마다 이미지+오디오 조각 ─────────────────────────────────────
    job.progress(1, 3, "장면 조립")
    seg_dir = ws.cache_dir(pid, slug) / "_video_segments"
    if seg_dir.is_dir():
        shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True, exist_ok=True)

    # 컷 목록 — render_frames.mjs 가 장마다 몇 컷을 찍었는지 적어 둔다
    fjson = {int(f["no"]): f for f in (ws.read_json(frames_dir / "frames.json", []) or [])}

    segments: List[Path] = []
    warn: List[str] = []
    total_sec = 0.0
    n_cuts = 0
    for i, s in enumerate(slides, 1):
        no = int(s["no"])
        au = s.get("audio") or {}
        audio_path = (root / au["file"]) if au.get("file") else None
        dur = float(au.get("sec") or 0) or 3.0
        seg = seg_dir / f"{i:04d}.mp4"

        cuts = [c for c in ((fjson.get(no) or {}).get("cuts") or [])
                if (frames_dir / c["image"]).is_file()]
        if not cuts:
            img = frames_dir / f"{no:03d}.png"
            if not img.is_file():
                warn.append(f"{no}번 캡처 없음 — 건너뜀")
                continue
            cuts = [{"image": img.name, "at": 0.0}]

        if len(cuts) == 1:
            ok, err = ff.image_audio_clip(frames_dir / cuts[0]["image"], seg,
                                          audio=audio_path, duration=dur)
        else:
            # ★ 컷마다 **다음 컷 시각까지** 머문다. 마지막 컷은 그 장이 끝날 때까지.
            #   그래야 화면이 바뀌는 순간이 실제 재생과 같아진다.
            ats = [float(c["at"]) for c in cuts]
            spans = [max(0.05, (ats[k + 1] if k + 1 < len(ats) else dur) - ats[k])
                     for k in range(len(ats))]
            # ★ 내레이션 길이를 같이 넘긴다 — 컷 시각이 그보다 뒤에 있으면
            #   그림이 오디오보다 길어져 장 끝에 무음이 붙는다(`ff.py` 주석).
            ok, err = ff.image_seq_audio_clip(
                [frames_dir / c["image"] for c in cuts], spans, seg,
                audio=audio_path, audio_sec=dur)

        if not ok:
            warn.append(f"{no}번 조각 실패: {err[:120]}")
            continue
        segments.append(seg)
        total_sec += dur
        n_cuts += len(cuts)
        job.progress(i, len(slides), f"{no}번 조각 · 컷 {len(cuts)}")

    if not segments:
        raise RuntimeError("영상 조각을 하나도 못 만들었습니다 — ffmpeg 설치를 확인하세요")

    # ── 3) 이어 붙이기 ───────────────────────────────────────────────────
    job.progress(2, 3, "이어 붙이기")
    # ★ 두 판이 **나란히 남는다.** 글이 한 줄씩 뜨는 판과 그림 한 판으로 갈아낀
    #   판은 같은 덱의 두 얼굴이고, 사람이 둘을 견줘 보고 고른다. 같은 이름으로
    #   내면 나중에 구운 것이 앞엣것을 덮어써서 견줄 수가 없다(2026-08-14) —
    #   원고 HTML 영상과 그림으로 갈아낀 영상을 **둘 다** 두고 견준다.
    swap = any(s.get("image_swap") for s in slides)
    out_path = dist / f"{ws.ascii_slug(slug)}{'-img' if swap else ''}.mp4"
    ok, err = ff.concat(segments, out_path)
    if not ok:
        raise RuntimeError(f"이어 붙이기 실패: {err[:300]}")

    shutil.rmtree(seg_dir, ignore_errors=True)
    shutil.rmtree(frames_dir, ignore_errors=True)

    job.progress(3, 3, "완료")
    mb = out_path.stat().st_size / 1e6
    n_missing = sum(1 for s in slides if not (s.get("audio") or {}).get("file"))
    if n_missing:
        warn.append(f"내레이션 없는 장 {n_missing}개 — 그 장은 무음으로 들어갔습니다")
    extra = f" · 컷 {n_cuts}" if n_cuts > len(segments) else ""
    job.add_log(f"영상 완료 · {len(segments)}장{extra} · {total_sec / 60:.1f}분 · {mb:.1f}MB")
    job.add_log(f"파일: {out_path}")

    # ★ 영상만 나오면 그다음이 막힌다 — 유튜브 올리기 화면은 제목·설명·태그를
    #   요구하고, 그 재료는 덱에 이미 다 있다(장 제목이 챕터, `start_sec` 이
    #   타임스탬프). 여기서 같이 내면 사람이 다시 쓸 일이 없다.
    try:
        from render import youtube
        txt = youtube.build(deck, title=(project.get("title") or slug),
                            led=(ws.load_ledger(pid, slug).get("by_id") or {}),
                            book=str(project.get("book") or ""))
        led = ws.load_ledger(pid, slug).get("by_id") or {}
        if txt:
            p_yt = ws.write_text(dist / "유튜브.txt", txt)
            job.add_log(f"유튜브 글: {p_yt}")
        # 썸네일 원고 — 이미지 스튜디오의 «프롬프트 생성기» 가 받는 것은 JSON 이
        # 아니라 원고 파일이다. 거기에 끌어다 놓고 「배너·썸네일 · 1컷」 만 고르면 된다.
        p_th = ws.write_text(dist / "유튜브썸네일-원고.txt",
                             youtube.thumb_md(deck, title=(project.get("title") or slug),
                                              led=led, book=str(project.get("book") or "")))
        job.add_log(f"썸네일 원고: {p_th}")
        # ★ 발음 교정표 — **손으로 정한 읽는 법**만 모은 표. 대본·문제 쓰는 사람에게
        #   넘기면 다음 과목에서 같은 발음을 또 고칠 일이 없다. 여기서 같이 내는
        #   이유는 유튜브 글과 같다 — 누를 것을 늘리지 않는 편이 낫고, 이 시점이면
        #   발음 손편집은 이미 끝나 있다(장별듣기 → 영상 렌더링 순서다).
        #   덱 화면의 「발음 교정표」 버튼과 **같은 함수**를 쓴다(`render/pronounce.build`).
        from render import pronounce
        pron = pronounce.build(pid, slug, title=(project.get("title") or slug))
        p_pr = ws.write_text(ws.step_dir(pid, slug, "subtitle") / "발음교정표.txt", pron)
        job.add_log(f"발음 교정표: {p_pr} (손으로 고친 장 {pronounce.n_hand(pron)}개)")
    except Exception as e:                      # noqa: BLE001
        # 영상은 이미 나왔다 — 곁다리가 실패해도 그것까지 실패로 만들지 않는다
        job.add_log(f"유튜브 글은 못 만들었습니다: {type(e).__name__}: {e}")

    return write_cache(pid, slug, "s12-video",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"file": out_path.name, "dir": str(dist),
                             "slides": len(segments), "cuts": n_cuts,
                             "sec": round(total_sec, 1), "mb": round(mb, 2)},
                       code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s12-video"].run = run
