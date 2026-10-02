"""원자적 JSON/텍스트 파일 쓰기.

설정 파일을 저장할 때 항상 사용한다. 평범한 `open("w") + json.dump` 는 첫 쓰기에서
파일을 비운 뒤 새 내용을 채우므로, 중간에 강제 종료/전원 차단/OOM 이 나면 잘리거나 빈
파일이 남는다(데이터 손실). 여기서는 같은 디렉토리의 임시 파일에 쓰고 fsync 한 뒤
os.replace 로 교체한다(같은 파일시스템에서 원자적).

(260606-googleOuth-aim-od/core/atomic_io.py 패턴 차용.)
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional


def atomic_write_json(path: str, data: Any, *, indent: Optional[int] = 2) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
