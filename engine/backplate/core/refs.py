# -*- coding: utf-8 -*-
"""참고 자료 — **레포에도 영상에도 없는 재료.**

중계기 구조를 설명한 HTML, 기획 메모, 벤치마크 표 같은 것들이다. 코드가 아니라
문서고, 화면 녹화도 아니다. 그래서 지금까지 들어갈 자리가 없었다.

    사람이 경로를 넣는다  →  00_기획/참고/ 로 복사  →  텍스트로 뽑아 브리프에 실림

★ **원본을 복사해 둔다.** 원래 자리의 파일이 지워지거나 옮겨져도 발표가 안 깨져야
  한다. 산출물 폴더 하나만 있으면 재현되는 게 이 앱의 규칙이다.

★ HTML 은 **의존성 없이** 본문만 뽑는다. `script`/`style` 을 버리고 태그를 벗긴다.
  완벽한 파서가 아니라 **모델에게 읽힐 만큼**이면 된다 — 어차피 Claude 가 읽는다.

★ 파생 파일명은 ascii. 한글 파일명이 URL·zip 을 깨는 것을 원천 차단한다.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List

from core import workspace as ws

TEXT_EXT = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".log"}
HTML_EXT = {".html", ".htm", ".xhtml"}
# ★ 이미지도 여기 들어온다. 기획서가 "이 캡처가 필요합니다" 라고 하면 같은 폴더에
#   넣으면 된다 — 요청과 납품이 한 자리에서 끝나야 잊히지 않는다.
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
OK_EXT = TEXT_EXT | HTML_EXT | IMG_EXT
MAX_BYTES = 2_000_000        # 텍스트는 2MB 넘으면 앞부분만
MAX_IMG_BYTES = 12_000_000
MAX_FILES = 60

# 파일명이 번호로 시작하면 **그 장에 붙는다.** `005.png` `5-대시보드.png` 둘 다.
NO_RE = re.compile(r"^0*(\d{1,3})(?:\D|$)")


class _Strip(HTMLParser):
    """태그를 벗기고 본문만 남긴다. script/style 안쪽은 통째로 버린다."""

    # head 를 통째로 건너뛰면 <title> 도 못 읽는다 — script/style 만 버린다
    SKIP = {"script", "style", "noscript", "svg"}
    BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BREAK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title and not self.title:
            self.title = data.strip()
        if data.strip():
            self.out.append(data)

    def text(self) -> str:
        t = "".join(self.out)
        t = re.sub(r"[ \t]+", " ", t)
        return re.sub(r"\n{3,}", "\n\n", t).strip()


def bytes_to_text(raw: bytes, suffix: str) -> tuple[str, str]:
    """(제목, 본문). 경로 없이 바이트로도 쓸 수 있게 — 업로드는 경로가 없다."""
    raw = raw[:MAX_BYTES]
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            s = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return "", ""

    if suffix.lower() in HTML_EXT:
        pr = _Strip()
        try:
            pr.feed(s)
        except Exception:  # noqa: BLE001
            return "", re.sub(r"<[^>]+>", " ", s)[:MAX_BYTES]
        return pr.title, pr.text()
    return "", s


def to_text(p: Path) -> tuple[str, str]:
    """(제목, 본문). 읽지 못하면 빈 문자열."""
    try:
        raw = p.read_bytes()[:MAX_BYTES]
    except OSError:
        return "", ""
    return bytes_to_text(raw, p.suffix)


def expand(paths: List[str]) -> List[Path]:
    """폴더를 넣으면 안쪽을 훑는다. 파일이면 그것만."""
    out: List[Path] = []
    for raw in paths or []:
        p = Path(str(raw).strip().strip('"')).expanduser()
        if p.is_file() and p.suffix.lower() in OK_EXT:
            out.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in OK_EXT:
                    out.append(f)
        if len(out) >= MAX_FILES:
            break
    return out[:MAX_FILES]


def slide_no(name: str) -> int | None:
    """`005.png` · `5-대시보드.png` → 5. 없으면 None."""
    m = NO_RE.match(ws.nfc(name).strip())
    return int(m.group(1)) if m else None


def collect(pid: int, slug: str, paths: List[str]) -> Dict[str, Any]:
    """복사 + (텍스트면) 추출. 결과는 `00_기획/참고/` 에 남는다.

    ★ 이미지는 **파일명이 번호로 시작하면 그 장에 붙는다.** 이미지 에이전트가 낸
      `005.png` 도, 사람이 직접 찍어 `5-대시보드.png` 로 넣은 것도 같은 규칙이다.
      규칙이 하나여야 어디에 넣을지 헷갈리지 않는다.
    """
    d = ws.sub_dir(pid, slug, "prd", "참고")
    items: List[Dict[str, Any]] = []
    for i, src in enumerate(expand(paths), 1):
        ext = src.suffix.lower()
        stem = ws.ascii_slug(src.stem, 30)
        name = f"{i:02d}-{stem}{ext}"

        if ext in IMG_EXT:
            try:
                b = src.read_bytes()
                if len(b) > MAX_IMG_BYTES:
                    continue
                (d / name).write_bytes(b)
            except OSError:
                continue
            items.append({
                "id": f"r{i}", "file": f"{ws.STEPS['prd'][0]}/참고/{name}",
                "source": str(src), "label": ws.nfc(src.stem),
                "kind": "image", "bytes": len(b), "slide_no": slide_no(src.name),
            })
            continue

        title, text = to_text(src)
        if not text.strip():
            continue
        try:
            (d / name).write_bytes(src.read_bytes()[:MAX_BYTES])
        except OSError:
            continue
        ws.write_text(d / f"{i:02d}-{stem}.txt", text)
        items.append({
            "id": f"r{i}", "file": f"{ws.STEPS['prd'][0]}/참고/{name}",
            "source": str(src), "label": ws.nfc(title or src.stem),
            "chars": len(text), "kind": "html" if ext in HTML_EXT else "text",
        })
    return {"dir": str(d), "items": items}


def collect_uploaded(pid: int, slug: str, uploads: List[Dict[str, Any]],
                      *, start: int = 1) -> Dict[str, Any]:
    """드래그앤드롭으로 받은 파일 — **브라우저는 경로를 안 준다, 바이트만 온다.**

    `uploads` 는 `[{"name": "a.html", "data_url": "data:text/html;base64,…"}]`.
    나머지 로직(추출·저장·번호규칙)은 `collect()` 와 같다 — 문이 두 개일 뿐
    도착한 자리는 하나(`00_기획/참고/`)다.
    """
    import base64

    d = ws.sub_dir(pid, slug, "prd", "참고")
    items: List[Dict[str, Any]] = []
    i = start
    for u in (uploads or [])[:MAX_FILES]:
        name = ws.nfc(str(u.get("name") or "").strip())
        ext = Path(name).suffix.lower()
        if not name or ext not in OK_EXT:
            continue
        raw_url = str(u.get("data_url") or u.get("data") or "")
        m = re.match(r"^data:[^;]*;base64,(.+)$", raw_url, re.S)
        b64 = m.group(1) if m else raw_url
        try:
            b = base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            continue

        stem = ws.ascii_slug(Path(name).stem, 30)
        out_name = f"{i:02d}-{stem}{ext}"

        if ext in IMG_EXT:
            if len(b) > MAX_IMG_BYTES:
                continue
            (d / out_name).write_bytes(b)
            items.append({
                "id": f"r{i}", "file": f"{ws.STEPS['prd'][0]}/참고/{out_name}",
                "source": name, "label": ws.nfc(Path(name).stem),
                "kind": "image", "bytes": len(b), "slide_no": slide_no(name),
            })
            i += 1
            continue

        title, text = bytes_to_text(b, ext)
        if not text.strip():
            continue
        (d / out_name).write_bytes(b[:MAX_BYTES])
        ws.write_text(d / f"{i:02d}-{stem}.txt", text)
        items.append({
            "id": f"r{i}", "file": f"{ws.STEPS['prd'][0]}/참고/{out_name}",
            "source": name, "label": ws.nfc(title or Path(name).stem),
            "chars": len(text), "kind": "html" if ext in HTML_EXT else "text",
        })
        i += 1
    return {"dir": str(d), "items": items}


def brief_block(refs: Dict[str, Any], root: Path, *, budget: int = 12000) -> List[str]:
    """모델 브리프에 넣을 조각. **예산 안에서 고르게 나눠 담는다** —
    한 파일이 길다고 다른 파일이 통째로 빠지면 안 된다."""
    items = [i for i in ((refs or {}).get("items") or []) if i.get("kind") != "image"]
    imgs = [i for i in ((refs or {}).get("items") or []) if i.get("kind") == "image"]
    if not items and not imgs:
        return []
    per = max(1200, budget // max(len(items), 1))
    L = ["# 참고 자료 — 레포에도 영상에도 없는 재료다. 여기 있는 것도 발표에 쓸 수 있다."]
    for it in items:
        txt = ""
        stem = Path(it["file"]).stem
        tp = root / Path(it["file"]).parent / f"{stem}.txt"
        if tp.is_file():
            txt = tp.read_text(encoding="utf-8", errors="replace")
        if not txt:
            continue
        L.append(f"\n## {it['label']}  ({it['chars']:,}자)")
        L.append(txt[:per] + ("\n…(줄임)" if len(txt) > per else ""))
    if imgs:
        # 그림은 본문에 안 싣는다(토큰이 크다). **있다는 것만** 알려 배치에 쓰게 한다.
        L.append("\n## 이미 있는 화면 캡처 — 슬라이드에 쓸 수 있다")
        for it in imgs:
            n = it.get("slide_no")
            L.append(f"- {it['label']}" + (f"  (→ {n}번 장 지정)" if n else ""))
    return L
