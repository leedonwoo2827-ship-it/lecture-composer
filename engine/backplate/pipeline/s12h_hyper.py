# -*- coding: utf-8 -*-
"""S12h 모션 영상 — 덱 → HyperFrames 컴포지션 → mp4 → −16 LUFS.

    11_완성/_hyper/           컴포지션 폴더(자기완결)
    11_완성/<slug>-motion.mp4 결과물

★ **왜 s12-video 를 대신하는가.** 예전 길은 거꾸로였다 — 글자를 그림에 구워
  놓고 스틸을 찍어 이어붙인 뒤, 그 픽셀에서 글자 상자를 **되찾아** 움직였다.
  되찾는 일이 안 됐다(줄 단위 9개를 사람이 5개로 합쳤고, 비전·순서 패스에
  덱당 $2~3 을 태웠다). 11판은 글자가 DOM 이라 **움직일 대상이 이미 있다.**

★ 순서가 중요하다: 렌더 → **정규화**. 반대로 하면 다시 인코딩하면서 이득이
  풀린다. 그리고 정규화는 **합본에** 건다 — 장마다 걸면 장이 바뀔 때마다
  소리가 출렁인다.

★ 린트를 먼저 돌린다. 린트가 막히면 layout·contrast 감사가 꺼진 채로
  「통과」처럼 보이는 망가진 영상이 나온다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, workspace as ws
from pipeline.registry import STAGES, write_cache
from render import hyper, loudness

APP = Path(__file__).resolve().parent.parent
RENDER_MJS = APP / "scripts" / "render.mjs"

_TAG = re.compile(r"^\[(stage|progress|warn|perf|done|error)\]\s*(.*)$")


def _hyperframes_bin() -> List[str]:
    """이 레포의 node_modules 를 쓴다 — 전역 설치에 기대지 않는다."""
    local = APP / "node_modules" / ".bin" / (
        "hyperframes.cmd" if sys.platform == "win32" else "hyperframes")
    return [str(local)] if local.is_file() else ["npx", "hyperframes"]


def _frames_tmp(job) -> Path:
    """프레임이 쌓일 자리 — **산출물과 같은 드라이브**에 둔다.

    ★ **왜 옮기는가.** HyperFrames 는 프레임을 전부 파일로 찍어 놓고 나중에
      이어 붙인다(`<tmp>/hf-render-XXXX/captured-frames`). 그 자리를
      `os.tmpdir()` 로 잡는데, 윈도우에서 그건 사용자 AppData 아래의 Temp 다.
      결과 mp4 가 D 에 있어도 **작업은 C 에서** 한다.
    ★ 실측(2026-09-19): 22.2분 영상이 **40,380장 · 468KB · 18.0GB**. 분당
      0.81GB 다. 2시간이면 98GB, 3시간이면 146GB — C 가 먼저 죽는다.
      실제로 `ENOSPC: no space left on device` 로 렌더가 통째로 터졌다.
    ★ C 가 꽉 차면 윈도우와 다른 프로그램까지 같이 망가진다. 산출물 폴더는
      사람이 큰 디스크에 잡아 두므로 거기가 맞다.
    ★ **정상 종료하면 스스로 지운다**(실측으로 확인). 다만 터졌을 때는 남을 수
      있어서, 시작할 때 지난 찌꺼기를 먼저 치운다 — 안 그러면 18GB 가 남은 채로
      다음 장이 연달아 터진다.
    """
    d = ws.ROOT / "_render-tmp"
    d.mkdir(parents=True, exist_ok=True)
    for stale in d.glob("hf-*"):
        if not stale.is_dir():
            continue
        gb = sum(f.stat().st_size for f in stale.rglob("*") if f.is_file()) / 1e9
        shutil.rmtree(stale, ignore_errors=True)
        job.add_log(f"지난 렌더 찌꺼기를 치웠습니다 — {stale.name} ({gb:.1f}GB)")
    return d


def _run_tagged(cmd: List[str], *, job, timeout: int = 7200,
                env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """태그 줄(`[stage]`/`[progress]`/…)을 읽으며 실행한다.

    ★ `asyncio.create_subprocess_exec` 를 쓰지 않는다 — Windows + uvicorn
      `--reload` 조합에서 깨진다. `Popen` + 한 줄씩 읽기로 간다.
    ★ node 에 `CREATE_NO_WINDOW` 를 **걸지 않는다.** 거꾸로였다 — 그 플래그를
      걸면 node 가 콘솔을 못 가져서 Chrome 자식마다 새 콘솔이 뜬다
      (260831 실측: 빈 검은 창 11개, conhost 19개).
    """
    res: Dict[str, Any] = {"warnings": [], "perf": None, "out": None, "error": None}
    p = subprocess.Popen(cmd, cwd=str(APP), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    last = -1
    try:
        for line in p.stdout:                      # type: ignore[union-attr]
            m = _TAG.match(line.strip())
            if not m:
                continue
            kind, body = m.group(1), m.group(2)
            if kind == "stage":
                job.add_log(body)
            elif kind == "progress":
                pct = int((body.split() or ["0"])[0] or 0)
                if pct - last >= 10:               # 10%마다만 — 로그가 수천 줄이 된다
                    last = pct
                    job.progress(pct, 100, body.partition(" ")[2])
            elif kind == "warn":
                res["warnings"].append(body)
            elif kind == "perf":
                try:
                    res["perf"] = json.loads(body)
                except Exception:                  # noqa: BLE001
                    pass
            elif kind == "done":
                res["out"] = body
            elif kind == "error":
                res["error"] = body
        p.wait(timeout=timeout)
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode != 0 and not res["error"]:
        res["error"] = f"렌더가 {p.returncode} 로 끝났습니다"
    return res


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s12h-hyper"]
    deck_p = ws.step_dir(pid, slug, "deck") / "deck.json"
    if not deck_p.is_file():
        raise RuntimeError("덱이 없습니다 — 먼저 조립(s8-assemble)을 돌리세요.")
    deck = json.loads(deck_p.read_text(encoding="utf-8"))

    proj_dir = ws.project_dir(pid, slug)
    dist = ws.step_dir(pid, slug, "dist")
    comp = dist / "_hyper"

    job.add_log("컴포지션 만드는 중")
    built = hyper.build(deck, proj_dir=proj_dir, out_dir=comp,
                        title=project.get("title") or slug)
    job.add_log(f"{built['scenes']}장 · 라벨 {built['labels']}개 · "
                f"{built['sec']:.0f}초")
    warn: List[str] = list(built.get("missing") or [])

    # ★ 먼저 린트. 막히면 굽기 전에 안다 — 2700프레임을 굽고 나서 알면 늦다.
    job.add_log("린트")
    lint = subprocess.run([*_hyperframes_bin(), "lint", str(comp)],
                          cwd=str(APP), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    tail = (lint.stdout or lint.stderr or "").strip().splitlines()[-1:] or [""]
    job.add_log(f"린트: {tail[0].strip()}")
    if lint.returncode != 0:
        raise RuntimeError("린트가 막았습니다:\n" + (lint.stdout or lint.stderr or "")[-800:])

    raw = dist / f"{ws.ascii_slug(slug)}-hyper.raw.mp4"
    out = dist / f"{ws.ascii_slug(slug)}-motion.mp4"

    # ★ 프레임 18GB 가 쌓일 자리를 산출물 쪽으로 돌린다(`_frames_tmp` 머리말).
    #   `TMP`·`TEMP`·`TMPDIR` 셋을 다 준다 — node 는 윈도우에서 TEMP, 리눅스에서
    #   TMPDIR 을 본다. 하나만 주면 그 플랫폼에서 조용히 옛 자리로 돌아간다.
    tmp = _frames_tmp(job)
    env = {**os.environ, "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp)}
    job.add_log(f"프레임 임시 폴더 — {tmp}")

    job.add_log("렌더 — 길이에 비례해 오래 걸립니다")
    r = _run_tagged(["node", str(RENDER_MJS),
                     "--dir", str(comp), "--out", str(raw),
                     "--fps", str(hyper.FPS), "--quality", "standard"],
                    job=job, env=env)
    warn += r["warnings"]
    if r["error"]:
        raise RuntimeError(r["error"])

    # ★ 마지막에 소리를 맞춘다. 영상은 복사만 하므로 화질이 안 깎인다.
    cfg = (config.load().get("video") or {})
    job.add_log("라우드니스 맞추는 중 (−16 LUFS)")
    lo = loudness.normalize(raw, out, {
        "i": float(cfg.get("loudnorm", {}).get("i", -16.0)),
        "tp": float(cfg.get("loudnorm", {}).get("tp", -1.5)),
        "lra": float(cfg.get("loudnorm", {}).get("lra", 11.0)),
        "abitrate": cfg.get("abitrate", "192k"),
        "ar": int(cfg.get("ar", 48000)), "ac": int(cfg.get("ac", 2)),
    })
    raw.unlink(missing_ok=True)
    job.add_log(f"{lo['before_lufs']} → {lo['after_lufs']} LUFS · "
                f"TP {lo['after_tp']} dBTP")

    mb = round(out.stat().st_size / 1e6, 2)
    job.add_log(f"완성 {out.name} · {mb}MB")

    return write_cache(pid, slug, "s12h-hyper",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"file": out.name, "dir": str(dist),
                             "scenes": built["scenes"], "labels": built["labels"],
                             "sec": built["sec"], "mb": mb,
                             "loudness": lo, "perf": r.get("perf")},
                       code_version=stage.code_version, cost_usd=0.0,
                       status="degraded" if warn else "ok", warnings=warn[:10])


STAGES["s12h-hyper"].run = run
