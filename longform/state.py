"""단계 상태 — jobs/<job>/state.json.

    {"lectures": {"L01": {"s2": {"hash": "...", "at": "..."}, "s3": {...}, "yt": {"id": "..."}}}}

★ 단계마다 **입력 해시**를 기록한다. 같은 해시면 건너뛰고(재시작 가능),
  요약노트를 고치면 해당 강의 해시만 바뀌어 그 강만 다시 만든다.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

from longform.config import Job


def sha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, (bytes, bytearray)):
            h.update(p)
        elif isinstance(p, Path):
            h.update(p.read_bytes() if p.exists() else b"<missing>")
        else:
            h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return "sha256:" + h.hexdigest()[:32]


class State:
    def __init__(self, job: Job):
        self.file = job.dir / "state.json"
        self.doc: Dict[str, Any] = {"lectures": {}}
        if self.file.exists():
            self.doc = json.loads(self.file.read_text(encoding="utf-8"))
            self.doc.setdefault("lectures", {})

    _lock = threading.Lock()   # 원고는 섹션 병렬로 만든다

    def save(self) -> None:
        with self._lock:
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.doc, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.file)

    def lec(self, lid: str) -> Dict[str, Any]:
        return self.doc["lectures"].setdefault(lid, {})

    def done(self, lid: str, stage: str, h: str) -> bool:
        return (self.lec(lid).get(stage) or {}).get("hash") == h

    def mark(self, lid: str, stage: str, h: str, **extra: Any) -> None:
        self.lec(lid)[stage] = {"hash": h, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **extra}
        self.save()

    def get(self, lid: str, stage: str) -> Dict[str, Any]:
        return self.lec(lid).get(stage) or {}
