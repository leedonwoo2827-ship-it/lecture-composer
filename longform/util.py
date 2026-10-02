"""공용 도구 — 로그, 외부 명령, xAPI식 기록, ffprobe."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import REPO

# ★ 윈도 콘솔 기본(cp949)은 —·①·· 를 못 찍는다 — 어디서 불러도 UTF-8 로
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [warn] {msg}", flush=True)


def run(cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None,
        check: bool = True, input_text: Optional[str] = None, capture: bool = False,
        timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env,
                       input=input_text, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture, timeout=timeout)
    if check and p.returncode != 0:
        if capture:
            sys.stderr.write((p.stdout or "")[-4000:] + (p.stderr or "")[-4000:])
        raise SystemExit(f"[error] 명령 실패({p.returncode}): {cmd[0]}")
    return p


def need(binary: str) -> str:
    b = shutil.which(binary)
    if not b:
        raise SystemExit(f"[error] '{binary}' 가 PATH 에 없습니다")
    return b


def ffprobe_duration(path: Path) -> float:
    p = subprocess.run([need("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def statement(verb: str, obj: str, result: Optional[Dict[str, Any]] = None,
              actor: str = "longform-bot") -> None:
    """보고서의 xAPI 원칙 — who / verb / object 한 줄 기록(logs/statements.jsonl)."""
    f = REPO / "logs" / "statements.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "actor": actor,
           "verb": verb, "object": obj, "result": result or {}}
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(p: Path, default: Any = None) -> Any:
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fmt_ts(sec: float) -> str:
    s = int(sec)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
