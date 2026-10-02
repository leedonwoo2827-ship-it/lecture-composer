# -*- coding: utf-8 -*-
"""폰트 — Pretendard 를 **쓰는 글자만** 깎아 HTML 에 인라인한다.

`webzine-maker/tools/subset-fonts.py` 의 절차를 그대로 쓴다:

  1. 최종 HTML 을 통째로 읽어 `set()` 으로 사용 글자 수집
     (마크업·CSS·JS 식별자까지 포함 — 의도적 상위집합. 놓치는 것보다 낫다)
  2. `fontTools.subset` 으로 woff2 재생성
  3. base64 로 `@font-face` 에 인라인

★ **서브셋은 산문이 확정된 뒤의 마지막 단계다.** 텍스트를 고치고 다시 안 깎으면
  없는 글자가 맑은 고딕으로 튄다 — webzine-maker README 가 명시한 함정이다.

★ Chrome 은 `file://` 에서 woff2 를 CORS 로 막는다. 그래서 **폴더 빌드에서도
  인라인**한다. 폰트 3종 서브셋이면 수십 KB 라 그래도 된다.

fontTools 가 없으면 서브셋 없이 통짜로 넣거나, 그것도 크면 시스템 폰트로 폴백한다.
파이프라인을 막지 않는다.
"""
from __future__ import annotations

import base64
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
FACES: List[Tuple[str, int]] = [
    ("Pretendard-Regular.woff2", 400),
    ("Pretendard-SemiBold.woff2", 600),
    ("Pretendard-Bold.woff2", 700),
]
LICENSE = "LICENSE-Pretendard.txt"

# 본문에 안 나와도 항상 넣는다 — 숫자·기호는 JS 가 나중에 만들어 낸다.
#
# ★ 여기에 `U+AC00-D7A3`(한글 음절 11,172자)를 넣으면 안 된다. 서브셋이
#   스스로 무력화돼서 3종 1.8MB 가 그대로 인라인된다(실제로 그랬다).
#   본문에 실제로 쓰인 한글은 `--text-file` 이 이미 전부 잡는다.
ALWAYS = ("U+0000-00FF,U+2013-2014,U+2018-201D,U+2026,U+203B,U+2190-2193,"
          "U+2022,U+25B6,U+FEFF")


def have_fonttools() -> bool:
    try:
        import fontTools  # noqa: F401
        import brotli  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


_B64 = re.compile(r"base64,[A-Za-z0-9+/=]+")


def charset(html: str) -> str:
    """쓰인 글자 전부. 마크업까지 포함하는 상위집합이 안전하다.

    ★ base64 덩어리는 먼저 걷어낸다. 음성·이미지 data URI 가 수 MB 라 그대로
      넣으면 문자셋 수집이 느려지기만 하고 새로 얻는 글자는 하나도 없다
      (ASCII 는 ALWAYS 에 이미 있다).
    """
    return "".join(sorted(set(_B64.sub("base64,", html))))


def subset(src: Path, text: str, out: Path) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(text)
        tf = f.name
    try:
        r = subprocess.run(
            [sys.executable, "-m", "fontTools.subset", str(src),
             f"--text-file={tf}", f"--unicodes={ALWAYS}",
             "--layout-features=*", "--flavor=woff2",
             "--no-hinting", "--desubroutinize", f"--output-file={out}"],
            capture_output=True, text=True, timeout=180)
        return r.returncode == 0 and out.is_file()
    except Exception:  # noqa: BLE001
        return False
    finally:
        Path(tf).unlink(missing_ok=True)


def face_css(html: str, *, work: Path) -> Tuple[str, List[str]]:
    """`@font-face` 블록과 경고 목록. 폰트가 없으면 빈 문자열(시스템 폰트 폴백)."""
    notes: List[str] = []
    if not FONT_DIR.is_dir():
        return "", ["폰트 폴더가 없습니다 — tools/get_fonts.py 를 돌리세요"]

    use_subset = have_fonttools()
    if not use_subset:
        notes.append("fontTools/brotli 없음 — 서브셋 없이 통짜로 넣습니다")
    text = charset(html)
    work.mkdir(parents=True, exist_ok=True)

    blocks: List[str] = []
    total = 0
    for name, weight in FACES:
        src = FONT_DIR / name
        if not src.is_file():
            notes.append(f"없음: {name}")
            continue
        use = src
        if use_subset:
            dst = work / name
            if subset(src, text, dst):
                use = dst
            else:
                notes.append(f"서브셋 실패, 원본 사용: {name}")
        b = use.read_bytes()
        total += len(b)
        blocks.append(
            "@font-face{font-family:'Pretendard';font-style:normal;"
            f"font-weight:{weight};font-display:swap;"
            "src:url(data:font/woff2;base64," + base64.b64encode(b).decode()
            + ") format('woff2')}"
        )
    if blocks:
        notes.append(f"폰트 {len(blocks)}종 · {total // 1024}KB 인라인")
    return "".join(blocks), notes


def license_text() -> str:
    p = FONT_DIR / LICENSE
    return p.read_text(encoding="utf-8") if p.is_file() else ""


_HEAD = re.compile(r"(<style>)", re.I)


def inject(html: str, css: str) -> str:
    """`<style>` 맨 앞에 `@font-face` 를 끼운다."""
    if not css:
        return html
    return _HEAD.sub(lambda m: m.group(1) + css, html, count=1)
