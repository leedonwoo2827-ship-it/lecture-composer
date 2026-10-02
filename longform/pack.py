"""pack — 원천(요약노트·문항)을 jobs/<job>/input/ 으로 복사한다.

★ 원천이 있는 PC에서 한 번. 이후 이 레포만 들고 가면 다른 PC(노트북)에서 돌아간다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from longform.config import Job
from longform.util import log


def run(job: Job) -> None:
    src_notes = job.path(job.get("source.notes_dir"))
    src_rounds = job.path(job.get("source.rounds_dir"))
    if not src_notes or not src_notes.exists():
        raise SystemExit(f"[error] 원천 요약노트 폴더가 없습니다: {src_notes}")

    dst_notes = job.input_dir / "notes"
    dst_notes.mkdir(parents=True, exist_ok=True)
    for p in job.get("inputs.notes") or []:
        name = Path(p).name
        s = src_notes / name
        if not s.exists():
            raise SystemExit(f"[error] 요약노트가 없습니다: {s}")
        shutil.copy2(s, dst_notes / name)
        log(f"노트 {name} 복사")

    if src_rounds and src_rounds.exists():
        dst_r = job.input_dir / "rounds"
        dst_r.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in sorted(src_rounds.glob("m*.json")):
            shutil.copy2(f, dst_r / f.name)
            n += 1
        log(f"문항 회차 {n}개 복사")
    src_sc = job.path(job.get("source.scripts_dir"))
    if src_sc and src_sc.exists():
        dst_s = job.input_dir / "scripts"
        dst_s.mkdir(parents=True, exist_ok=True)
        for p in job.get("inputs.scripts") or []:
            s = src_sc / Path(p).name
            if s.exists():
                shutil.copy2(s, dst_s / s.name)
                log(f"영상 원고 {s.name} 복사")
            else:
                log(f"[warn] 영상 원고가 없습니다: {s}")
    log(f"완료 → {job.input_dir}")
