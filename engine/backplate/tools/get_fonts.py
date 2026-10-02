# -*- coding: utf-8 -*-
"""Pretendard 내려받기 — `static/fonts/` 는 gitignore 라 fresh clone 이면 비어 있다.

없으면 브라우저가 조용히 맑은 고딕으로 폴백한다. 에러도 없고 경고도 없이 화면만
미묘하게 달라져서, IDA 에서 한참 뒤에야 알아챘던 함정이다. setup 이 이걸 부른다.

woff2 를 쓰는 이유:
  - ttf 대비 약 1/4 크기 (전체 3종 ~500KB → ~130KB)
  - **최종 쇼케이스 페이지에서 서브셋할 소스와 같다.** webzine-maker 의
    tools/subset-fonts.py 가 같은 파일을 fontTools 로 깎아 단일 HTML 에 넣는다.

라이선스: SIL Open Font License 1.1. **재배포 시 LICENSE 를 반드시 동봉한다** —
dist/<slug>.zip 과 단일 HTML 에도 들어간다.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "fonts"

PRETENDARD_VER = "v1.3.9"
BASE = (f"https://cdn.jsdelivr.net/gh/orioncactus/pretendard@{PRETENDARD_VER}"
        f"/packages/pretendard/dist/web/static/woff2")
WEIGHTS = ["Regular", "SemiBold", "Bold"]

LICENSE_URL = (f"https://cdn.jsdelivr.net/gh/orioncactus/pretendard@{PRETENDARD_VER}"
               f"/packages/pretendard/dist/LICENSE.txt")
LICENSE_NAME = "LICENSE-Pretendard.txt"


def fetch(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "showcase-agent/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return len(data)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    missing = []

    for w in WEIGHTS:
        dest = OUT / f"Pretendard-{w}.woff2"
        if dest.is_file() and dest.stat().st_size > 10_000:
            print(f"  ok   Pretendard-{w}.woff2  ({dest.stat().st_size // 1024}KB, 이미 있음)")
            total += dest.stat().st_size
            continue
        try:
            n = fetch(f"{BASE}/Pretendard-{w}.woff2", dest)
            print(f"  받음 Pretendard-{w}.woff2  ({n // 1024}KB)")
            total += n
        except (urllib.error.URLError, OSError) as e:
            print(f"  실패 Pretendard-{w}.woff2  — {e}")
            missing.append(w)

    lic = OUT / LICENSE_NAME
    if not lic.is_file():
        try:
            fetch(LICENSE_URL, lic)
            print(f"  받음 {LICENSE_NAME}")
        except (urllib.error.URLError, OSError) as e:
            # 라이선스를 못 받으면 재배포가 곤란하다 — 조용히 넘어가지 않는다.
            print(f"  실패 {LICENSE_NAME} — {e}")
            print("       OFL 재배포에는 라이선스 동봉이 필요합니다. 수동으로 받아 두세요:")
            print(f"       {LICENSE_URL}")
            missing.append("LICENSE")

    print(f"\n  합계 {total // 1024}KB  →  {OUT}")
    if missing:
        print(f"  ⚠ 못 받은 항목: {', '.join(missing)}")
        print("    네트워크가 막혀 있으면 폰트 없이도 앱은 돌아갑니다(시스템 글꼴로 폴백).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
