# -*- coding: utf-8 -*-
"""라우드니스 정규화 — EBU R128 2-pass.

    normalize(src, dst, cfg) → {"before": -23.3, "after": -16.1, …}

★ **왜 2-pass 인가.** 1-pass loudnorm 은 흘러가며 맞추느라 앞부분이 뜬다.
  먼저 전체를 재고(measured_I·TP·LRA·thresh·offset), 그 값을 넣어 다시 걸면
  처음부터 끝까지 같은 이득이 걸린다. 강의 영상처럼 **한 사람이 처음부터
  끝까지 말하는** 소리에서는 차이가 눈에 띈다.

★ **합본에 건다. 장마다 걸지 않는다.** 장별로 정규화하면 조용한 장은 올라가고
  큰 장은 내려가서 **장이 바뀔 때마다 소리가 출렁인다.** 사람 목소리는 한
  사람이고, 기준도 하나여야 한다.

★ **영상은 재인코딩하지 않는다**(`-c:v copy`). 소리만 바꾸는데 화질을 한 번 더
  깎을 이유가 없고, 32장짜리를 다시 굽는 시간도 아깝다.

★ 순서: 렌더 → **정규화** → (fmt 10 이면) 모션 베이크. 모션은 오디오를 그대로
  복사하므로(`-c:a copy`) 이 순서여야 모션본도 정규화된 소리를 물려받는다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from render.ff import bin_path

# ★ −16 LUFS 는 **스테레오 기준**이다. 모노 그대로면 같은 체감 음량이
#   −19 LUFS 라 규격과 어긋난다. 그래서 스테레오로 올려 두고 잰다.
DEFAULT = {"i": -16.0, "tp": -1.5, "lra": 11.0,
           "acodec": "aac", "abitrate": "192k", "ar": 48000, "ac": 2}

_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def _run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    ff = bin_path("ffmpeg")
    if not ff:
        raise FileNotFoundError("ffmpeg 없음")
    return subprocess.run([ff, "-hide_banner", "-nostdin", "-y", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def measure(src: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """1차 — 전체를 재기만 한다. 파일을 쓰지 않는다(`-f null`)."""
    c = {**DEFAULT, **(cfg or {})}
    r = _run(["-i", str(src),
              "-af", f"loudnorm=I={c['i']}:TP={c['tp']}:LRA={c['lra']}:print_format=json",
              "-f", "null", "-"])
    m = _JSON.search(r.stderr or "")
    if not m:
        raise RuntimeError("라우드니스를 재지 못했습니다:\n" + (r.stderr or "")[-600:])
    d = json.loads(m.group(0))
    return {k: float(d[k]) for k in
            ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def normalize(src: Path, dst: Path, cfg: Optional[Dict[str, Any]] = None
              ) -> Dict[str, Any]:
    """2차 — 잰 값을 넣어 실제로 건다. 영상은 복사, 소리만 다시 인코딩."""
    c = {**DEFAULT, **(cfg or {})}
    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise FileNotFoundError(src)

    before = measure(src, c)
    af = (f"loudnorm=I={c['i']}:TP={c['tp']}:LRA={c['lra']}"
          f":measured_I={before['input_i']}"
          f":measured_TP={before['input_tp']}"
          f":measured_LRA={before['input_lra']}"
          f":measured_thresh={before['input_thresh']}"
          f":offset={before['target_offset']}"
          f":linear=true:print_format=summary")

    tmp = dst.with_suffix(".norm.tmp.mp4")
    r = _run(["-i", str(src), "-map", "0",
              "-c:v", "copy",
              "-c:a", str(c["acodec"]), "-b:a", str(c["abitrate"]),
              "-ar", str(c["ar"]), "-ac", str(c["ac"]),
              "-af", af, "-movflags", "+faststart", str(tmp)])
    if r.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError("정규화 실패:\n" + (r.stderr or "")[-600:])

    shutil.move(str(tmp), str(dst))
    after = measure(dst, c)
    return {"file": str(dst),
            "before_lufs": round(before["input_i"], 1),
            "after_lufs": round(after["input_i"], 1),
            "before_tp": round(before["input_tp"], 1),
            "after_tp": round(after["input_tp"], 1),
            "target": c["i"], "bitrate": c["abitrate"],
            "ar": c["ar"], "ac": c["ac"]}
