# -*- coding: utf-8 -*-
"""콘솔 없이 스테이지를 돌린다.

브라우저 창을 닫으면 서버가 함께 죽고, 그러면 돌던 스테이지도 중간에 끊긴다.
길게 도는 단계(대본·판단·구조)는 콘솔과 무관하게 돌 수 있어야 한다.

    .venv-app\\Scripts\\python tools\\run_stage.py 1 s6-script --force
    .venv-app\\Scripts\\python tools\\run_stage.py 1 s10-tts s11-audio s8-assemble s9-render
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from core import workspace as ws
from pipeline.registry import STAGES
import pipeline.s0_prd      # noqa: F401
import pipeline.s0a_ask     # noqa: F401
import pipeline.s1_frames   # noqa: F401
import pipeline.s2_repo     # noqa: F401
import pipeline.s2b_outline # noqa: F401
import pipeline.s2c_capture # noqa: F401
import pipeline.s3_caption  # noqa: F401
import pipeline.s3a_imgprompt  # noqa: F401
import pipeline.s3b_images  # noqa: F401
import pipeline.s5_decisions  # noqa: F401
import pipeline.s6_script   # noqa: F401
import pipeline.s7_copy     # noqa: F401
import pipeline.s8_assemble # noqa: F401
import pipeline.s9_render   # noqa: F401
import pipeline.s10_tts     # noqa: F401
import pipeline.s11_audio   # noqa: F401
import pipeline.s12_video   # noqa: F401
import pipeline.s3c_images_run  # noqa: F401  — 11판: 그림 굽기
import pipeline.s12h_hyper      # noqa: F401  — 11판: HyperFrames 렌더


class Job:
    """콘솔의 잡 객체와 같은 모양. 로그는 그냥 화면으로 흘린다."""

    canceled = False

    def add_log(self, msg: str) -> None:
        print(f"  {msg}", flush=True)

    def progress(self, done: int, total: int, note: str = "") -> None:
        print(f"  … {done}/{total} {note}", flush=True)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if len(args) < 2:
        print(__doc__)
        return 2

    pid = int(args[0])
    keys = args[1:]
    proj = next((p for p in ws.list_projects() if p["id"] == pid), None)
    if not proj:
        print(f"프로젝트 {pid} 없음")
        return 1
    slug = proj["slug"]
    doc = ws.load_project(pid, slug)

    for key in keys:
        st = STAGES.get(key)
        if not st or not st.run:
            print(f"✗ {key} — 없거나 미구현")
            return 1
        print(f"\n=== {key} · {st.label}" + (" (강제)" if force else ""))
        t0 = time.time()
        try:
            env = st.run(Job(), pid, slug, doc, force=force)
        except Exception as e:  # noqa: BLE001
            print(f"✗ 실패: {type(e).__name__}: {e}")
            return 1
        print(f"  → {env.get('status')} · ${env.get('cost_usd', 0):.3f} "
              f"· {time.time() - t0:.0f}초")
        for w in (env.get("warnings") or [])[:6]:
            print(f"    경고: {w}")
        doc = ws.load_project(pid, slug)      # 단계가 project.json 을 고칠 수 있다
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
