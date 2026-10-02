"""잡 설정(jobs/<job>/job.json) 읽기.

★ 경로는 **레포 루트 기준 상대경로** 또는 절대경로. 다른 PC(노트북)에서는
  `jobs/<job>/job.local.json` 에 그 PC의 경로만 덮어쓴다(깃에 안 올라간다).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parent.parent


def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Job:
    name: str
    dir: Path
    cfg: Dict[str, Any]

    def path(self, p: str | None) -> Path | None:
        """설정의 경로 문자열 → Path. 상대경로는 레포 루트 기준."""
        if not p:
            return None
        q = Path(p).expanduser()
        return q if q.is_absolute() else (REPO / q)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.cfg
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # 자주 쓰는 폴더
    @property
    def input_dir(self) -> Path:
        return self.dir / "input"

    @property
    def manuscripts_dir(self) -> Path:
        return self.dir / "manuscripts"

    @property
    def out_dir(self) -> Path:
        return self.dir / "out"

    @property
    def meta_dir(self) -> Path:
        return self.dir / "meta"

    @property
    def bp_workspace(self) -> Path:
        return self.path(self.get("backplate.workspace")) or (self.dir / "bp")


def default_job() -> str:
    """--job 을 안 주면 — jobs/ 아래 잡이 하나면 그것, LECTURE_COMPOSER_JOB 이 있으면 그것."""
    import os
    env = os.environ.get("LECTURE_COMPOSER_JOB", "").strip()
    if env:
        return env
    names = sorted(p.name for p in (REPO / "jobs").iterdir()
                   if p.is_dir() and (p / "job.json").exists() and not p.name.startswith("_") and p.name != "example")
    if len(names) == 1:
        return names[0]
    raise SystemExit("[error] 잡을 고르십시오: --job " + (" | ".join(names) or "(jobs/ 에 잡이 없습니다 — jobs/example 을 복사)"))


def load_job(name: str) -> Job:
    d = REPO / "jobs" / name
    f = d / "job.json"
    if not f.exists():
        raise SystemExit(f"[error] 잡 설정이 없습니다: {f}")
    cfg = json.loads(f.read_text(encoding="utf-8"))
    local = d / "job.local.json"
    if local.exists():
        cfg = _merge(cfg, json.loads(local.read_text(encoding="utf-8")))
    return Job(name=name, dir=d, cfg=cfg)
