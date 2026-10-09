# -*- coding: utf-8 -*-
"""영상 테마 — HyperFrames 컴포지션(`render/hyper.py`)의 **룩**을 갈아 끼운다.

    THEMES["ivory"]     지금까지의 룩(아이보리 판 · 적갈 제목 · 남색 라벨 · 빛 띠).
                        값이 비어 있으면 hyper.py 가 **원래 코드 그대로** 그린다 — 옛 잡은 한 픽셀도 안 바뀐다.
    THEMES["danjeong"]  「단정 스케치북」 — SUIT 굵은 글꼴 · 장(덩이)마다 바뀌는 바탕 ·
                        유기적 색 덩어리(blob) · 종이 결 · 먹선 손그림 오브젝트(codex 투명 PNG) ·
                        그어지며 나타나는 낙서 장식.

★ 테마는 목표서 `backplate.theme` 로 고른다. longform(s3_render)이 프로젝트에 `video_theme` 로
  적고, 장마다 `look`(덩이 번호·장 종류·키커)을 덮어쓰기로 싣는다. 이 파일은 그 둘만 읽는다.
★ 이 파일은 **그림을 계산만** 한다(문자열을 돌려줌). 시간 계산은 여전히 hyper._plan 한 곳뿐이다.
★ blob·장식은 장 번호로 시드를 고정한다 — 다시 구워도 같은 자리에 같은 모양이 나온다(결정론).
"""
from __future__ import annotations

import math
import random
import re
from html import escape as esc
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

APP = Path(__file__).resolve().parent.parent
FONT_DIR = APP / "static" / "fonts"

# ── 테마 정의 ─────────────────────────────────────────────────────────────
THEMES: Dict[str, Dict[str, Any]] = {
    # 지금 룩. hyper.py 가 원래 CSS 를 그대로 쓴다(아래 값은 문서·raster·썸네일용).
    "ivory": {
        "name": "ivory",
        "paper": "#F6F1E8", "ink": "#1d2433", "title": "#9a4d33", "accent": "#9a4d33",
        "label": "#1F4E79", "sub": "#334155",
    },
    "danjeong": {
        "name": "danjeong",
        "font": "SUIT",
        "font_dir": "suit",
        # 글꼴 파일 — 굵기별. 제목 900, 라벨 머리 800, 본문 600/500
        "faces": {400: "SUIT-Regular.woff2", 500: "SUIT-Medium.woff2", 600: "SUIT-SemiBold.woff2",
                  700: "SUIT-Bold.woff2", 800: "SUIT-ExtraBold.woff2", 900: "SUIT-Heavy.woff2"},
        "ink": "#1F1D2B",          # 제목·먹선
        "ink_sub": "#4A4757",      # 설명
        "ink_soft": "#7A7686",     # 머리말 캡션
        "paper": "#EEEAE1",        # 기본 바탕
        "deep": "#22314F",         # 강 표지·맺음
        "on_deep": "#F4F1EA",
        "accent": "#DD5A43",       # 토마토 — 제목 둘째 줄·번호·밑줄
        "cobalt": "#3550C8",
        "mustard": "#EBB43C",
        "sage": "#86AE84",
        # 덩이(소주제 묶음)마다 순환하는 바탕 — 바탕 · 큰 blob · 작은 blob · 강조색
        "bases": [
            {"bg": "#EEEAE1", "blob": "#DD5A43", "blob2": "#EBB43C", "accent": "#DD5A43"},
            {"bg": "#C9DAEA", "blob": "#3550C8", "blob2": "#EBB43C", "accent": "#2C44B0"},
            {"bg": "#D6E0CE", "blob": "#86AE84", "blob2": "#DD5A43", "accent": "#C24A34"},
            {"bg": "#F3DCC8", "blob": "#E58A62", "blob2": "#3550C8", "accent": "#B8452F"},
        ],
        # 도식·표·문제 카드(raster) — 먹선 상자 + 어긋난 단색 그림자
        "card_bg": "#FFFDF8", "card_line": "#1F1D2B", "card_shadow": "#1F1D2B",
        "table_head": "#F6E2B8", "code_bg": "#22314F", "code_fg": "#F4F1EA",
        # 기존 SVG 도식 색을 테마 색으로(대소문자 무시)
        "svg_remap": {"#1F4E79": "#22314F", "#9DC3E6": "#BFD3EA", "#334155": "#1F1D2B",
                      "#fff3d6": "#F8E6B5", "#F4F8FC": "#F6F2EA"},
        # 화면 비율(%) — 텍스트 열은 왼쪽, 사물은 오른쪽 아래에 작게(사용자 지시 2026-10-09: 반 크기·우하단).
        #   강 표지·맺음(deep)만 큰 자리(obj_box_cover)를 쓴다.
        "text_w": 68, "obj_box": (75, 46, 21, 37),   # left, top, width, height
        "obj_box_cover": (54, 13, 42, 74),
        "sheen": False,
        "sync": True,              # render/sync.py - labels appear when their words are spoken
        "label_reveal": "type",    # type = head typed out at speech pace | rise
        # 글이 많은 장(라벨 글자 수 ≥ dense_chars)의 사물 처리: keep · shrink · hide · backdrop · recede
        "dense_chars": 70, "dense_mode": "keep", "obj_box_small": (80, 58, 16, 28),
    },
}


def get(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """테마 사전. 이름이 없거나 'ivory' 면 None — hyper.py 가 원래 길로 간다."""
    if not name or name == "ivory":
        return None
    t = THEMES.get(str(name))
    if t is None:
        raise ValueError(f"모르는 영상 테마: {name} (있는 것: {', '.join(THEMES)})")
    return t


def base_for(theme: Dict[str, Any], chunk: int) -> Dict[str, str]:
    b = theme["bases"]
    return b[int(chunk or 0) % len(b)]


# ── 글꼴 ──────────────────────────────────────────────────────────────────
def font_files(theme: Dict[str, Any]) -> List[Path]:
    d = FONT_DIR / theme["font_dir"]
    return [d / f for f in theme["faces"].values()] + [d / "LICENSE-SUIT.txt"]


def font_faces(theme: Dict[str, Any], url_base: str = "./assets/fonts/") -> str:
    fam = theme["font"]
    return "".join(
        f'@font-face{{font-family:"{fam}";src:url("{url_base}{f}") format("woff2");'
        f'font-weight:{w};font-display:block}}\n'
        for w, f in theme["faces"].items())


# ── 종이 결 ───────────────────────────────────────────────────────────────
def paper_uri() -> str:
    """SVG feTurbulence 잡티 — 배경 이미지로 한 번 래스터되고 장마다 재사용된다."""
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='480' height='480'>"
           "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/>"
           "<feColorMatrix values='0 0 0 0 .12  0 0 0 0 .11  0 0 0 0 .16  0 0 0 .55 -.18'/></filter>"
           "<rect width='100%' height='100%' filter='url(#n)'/></svg>")
    return "data:image/svg+xml;utf8," + quote(svg)


# ── 유기적 덩어리(blob) ──────────────────────────────────────────────────
def blob_path(cx: float, cy: float, r: float, seed: int, n: int = 9, wob: float = .16) -> str:
    """닫힌 Catmull-Rom → 3차 베지어. 반지름을 점마다 조금씩 흔들어 손으로 오린 종이 같은 윤곽."""
    rnd = random.Random(seed)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n + rnd.uniform(-.12, .12)
        rr = r * (1 + rnd.uniform(-wob, wob))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a) * rnd.uniform(.86, 1.0)))
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d) + "Z"


def _blob(cls: str, cx: float, cy: float, r: float, color: str, seed: int, shade: bool = True) -> str:
    """덩어리 하나. 아래쪽에 한 톤 어두운 그림자 덩어리를 살짝 비껴 깐다(종이를 겹친 느낌)."""
    sh = (f'<path d="{blob_path(cx + 10, cy + 14, r, seed)}" fill="#1F1D2B" opacity=".10"/>' if shade else "")
    return (f'<svg class="blob {cls}" viewBox="0 0 1920 1080" preserveAspectRatio="none">'
            f'{sh}<path d="{blob_path(cx, cy, r, seed)}" fill="{color}"/></svg>')


# ── 낙서 장식 ─────────────────────────────────────────────────────────────
# 선(stroke)은 pathLength=1 로 정규화해 두고 GSAP 가 strokeDashoffset 1→0 으로 **긋는다**.
def _sparkle(x: float, y: float, s: float, color: str) -> str:
    return (f'<svg class="dd pop" style="left:{x}px;top:{y}px;width:{s}px;height:{s}px" viewBox="0 0 40 40">'
            f'<path d="M20 0 C21.5 13 27 18.5 40 20 C27 21.5 21.5 27 20 40 C18.5 27 13 21.5 0 20 C13 18.5 18.5 13 20 0Z" '
            f'fill="{color}"/></svg>')


def _star(x: float, y: float, s: float, fill: str, ink: str, rot: float) -> str:
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 18 if i % 2 == 0 else 8
        pts.append(f"{25 + r * math.cos(a):.1f},{25 + r * math.sin(a):.1f}")
    # ★ 회전은 SVG 안쪽 <g> 로 — 바깥 요소에 CSS transform 을 주면 GSAP(scale·rotation)과 부딪혀
    #   HyperFrames 린트가 막는다(2026-10-09 실측: 56 error)
    return (f'<svg class="dd pop" style="left:{x}px;top:{y}px;width:{s}px;height:{s}px" '
            f'viewBox="0 0 50 50"><g transform="rotate({rot:.1f} 25 25)"><polygon points="{" ".join(pts)}" '
            f'fill="{fill}" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/></g></svg>')


def _squiggle(color: str, w: float = 260) -> str:
    d = "M4 14 " + " ".join(f"Q{12 + i * 32} {2 if i % 2 == 0 else 26} {28 + i * 32} 14" for i in range(8))
    return (f'<svg class="squig" viewBox="0 0 {w} 28" style="width:{w}px;height:28px">'
            f'<path class="ln" pathLength="1" d="{d}" fill="none" stroke="{color}" stroke-width="5" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>')


# ── 도식 — 그려지듯 나타난다(사용자 지시 2026-10-09: _context/section.mp4 0:30 처럼) ──────────────
# PNG 로 구우면 통째로 뜰 수밖에 없다. 그래서 SVG 를 DOM 에 그대로 두고 **요소마다** 순서대로:
#   선(상자·화살표·괘선) = stroke-dashoffset 1→0 으로 긋기  →  면 = fill-opacity 0→원래값  →  글자 = 나타남.
#   표는 행이 위에서부터 하나씩.
_DRAW_RE = re.compile(r"<(path|rect|line|polyline|polygon|circle|ellipse|text)\b([^>]*?)(/?)>", re.I)
_SVG_ROOT_RE = re.compile(r"<svg\b([^>]*)>", re.I)


def _add_class(attrs: str, cls: str) -> str:
    if re.search(r'\bclass\s*=\s*"', attrs):
        return re.sub(r'\bclass\s*=\s*"', f'class="{cls} ', attrs, count=1)
    return f' class="{cls}"' + attrs


def _xy(tag: str, attrs: str) -> Tuple[float, float]:
    """요소의 대략 첫 좌표 — 그리는 순서(왼→오, 위→아래)를 정하는 데만 쓴다(그룹 transform 은 무시)."""
    def a(name: str) -> Optional[float]:
        m = re.search(rf'\b{name}\s*=\s*"\s*(-?[\d.]+)', attrs)
        return float(m.group(1)) if m else None
    if tag in ("rect", "text"):
        return a("x") or 0.0, a("y") or 0.0
    if tag == "line":
        return a("x1") or 0.0, a("y1") or 0.0
    if tag in ("circle", "ellipse"):
        return a("cx") or 0.0, a("cy") or 0.0
    m = re.search(r'\b(?:d|points)\s*=\s*"\s*[Mm]?\s*(-?[\d.]+)[\s,]+(-?[\d.]+)', attrs)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def prep_fig(markup: str, th: Dict[str, Any]) -> Tuple[str, str, int]:
    """도식 문자열 → (종류 svg|table, 손본 마크업, 그려질 요소 수)."""
    m = (markup or "").strip()
    if m.lower().startswith("<table"):
        out = m.replace("<table", "<table class='tb'", 1)
        return "table", out, max(1, out.lower().count("<tr"))
    for a, b in (th.get("svg_remap") or {}).items():
        m = re.sub(re.escape(a), b, m, flags=re.I)

    def draw(mm: "re.Match") -> str:
        tag, attrs, close = mm.groups()
        txt = tag.lower() == "text"
        attrs = _add_class(attrs, "dk dt" if txt else "dk dw")
        x, y = _xy(tag.lower(), attrs)
        attrs += f' data-o="{int(x // 90) * 100000 + int(y)}"'
        if not txt and "pathlength" not in attrs.lower():
            attrs += ' pathLength="1"'
        return f"<{tag}{attrs}{close}>"

    m = _DRAW_RE.sub(draw, m)

    def root(mm: "re.Match") -> str:
        attrs = re.sub(r'\s(width|height|preserveAspectRatio)\s*=\s*"[^"]*"', "", mm.group(1))
        return f'<svg{_add_class(attrs, "rough figsvg")} preserveAspectRatio="xMidYMid meet">'

    m = _SVG_ROOT_RE.sub(root, m, count=1)
    return "svg", m, len(re.findall(r'class="dk ', m))


def fig_html(markup: str, th: Dict[str, Any]) -> str:
    kind, body, _ = prep_fig(markup, th)
    return f'<div class="figbox {kind}">{body}</div>'


# 손그림 흔들림(raster.ROUGH_DEF 와 같은 값) — 컴포지션에 한 번만 둔다
ROUGH_DEF = ('<svg width="0" height="0" style="position:absolute"><filter id="rough" x="-2%" y="-2%" '
             'width="104%" height="104%"><feTurbulence type="fractalNoise" baseFrequency=".018" numOctaves="2" '
             'seed="7"/><feDisplacementMap in="SourceGraphic" scale="2.6" xChannelSelector="R" '
             'yChannelSelector="G"/></filter></svg>')


def _dots(x: float, y: float, ink: str) -> str:
    return (f'<svg class="dd pop" style="left:{x}px;top:{y}px;width:70px;height:22px" viewBox="0 0 70 22">'
            + "".join(f'<circle cx="{8 + i * 26}" cy="11" r="5" fill="{ink}"/>' for i in range(3)) + "</svg>")


def _circle_scribble(x: float, y: float, w: float, h: float, color: str) -> str:
    return (f'<svg class="dd" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px" viewBox="0 0 200 120">'
            f'<path class="ln" pathLength="1" d="M100 8 C160 6 194 34 190 62 C186 98 132 114 88 112 '
            f'C36 110 6 86 10 56 C14 26 56 10 112 12 C150 14 170 22 178 30" fill="none" stroke="{color}" '
            f'stroke-width="3" stroke-linecap="round"/></svg>')


# ── CSS ───────────────────────────────────────────────────────────────────
def css(theme: Dict[str, Any], W: int, H: int) -> str:
    t = theme
    f = t["font"]
    return f"""
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:{W}px;height:{H}px;background:{t['paper']};overflow:hidden;
  font-family:"{f}","Malgun Gothic",sans-serif;-webkit-font-smoothing:antialiased;color:{t['ink']}}}
.clip{{position:absolute;inset:0;width:{W}px;height:{H}px;overflow:hidden;background:var(--bg)}}
.clip>.grain{{position:absolute;inset:0;background-image:url("{paper_uri()}");background-size:480px 480px;
  mix-blend-mode:multiply;opacity:.55;pointer-events:none;z-index:9}}
.blob{{position:absolute;inset:0;width:100%;height:100%;overflow:visible;transform-origin:50% 50%}}
.clip>img.obj{{position:absolute;object-fit:contain;display:block;z-index:3;
  filter:drop-shadow(10px 14px 0 rgba(31,29,43,.10))}}
.clip>img.obj.back{{opacity:.26;filter:saturate(.55);z-index:2}}
.blob.dim{{opacity:.38}}
.clip>img.full{{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;display:block;z-index:3}}
/* 도식 상자 — 먹선 카드 + 어긋난 단색 그림자(raster._box_css 와 같은 값). 아래 20% 는 자막 자리 */
.figbox{{position:absolute;left:7%;right:7%;top:31%;bottom:20%;z-index:5;box-sizing:border-box;
  background:{t['card_bg']};border:3px solid {t['card_line']};border-radius:22px;
  box-shadow:9px 10px 0 {t['card_shadow']};padding:26px 36px;display:flex;align-items:center;justify-content:center}}
.figbox svg.figsvg{{width:100%;height:100%;max-width:100%;max-height:100%;overflow:visible}}
.figbox.svg .rough{{filter:url(#rough)}}
.figbox svg text{{font-family:"{f}","Malgun Gothic",sans-serif}}
.figbox .dw{{stroke-dasharray:1;stroke-dashoffset:1;fill-opacity:0}}
.figbox .dt{{opacity:0}}
.figbox .tb{{width:100%;border-collapse:collapse;font-size:28px;line-height:1.38;color:{t['ink']}}}
.figbox .tb th{{background:{t['table_head']};font-weight:800;padding:12px 18px;text-align:left;
  border-top:3px solid {t['ink']};border-bottom:3px solid {t['ink']}}}
.figbox .tb td{{padding:11px 18px;border-bottom:1.5px solid rgba(31,29,43,.22);vertical-align:top;
  word-break:keep-all;font-weight:500}}
.figbox .tb tr:last-child td{{border-bottom:3px solid {t['ink']}}}
.figbox .tb td:first-child{{font-weight:800}}
.figbox .tb tr{{opacity:0}}
.dd{{position:absolute;overflow:visible;z-index:4}}
.ln{{stroke-dasharray:1;stroke-dashoffset:1}}
/* 머리말 — 왼쪽 로고타입 · 오른쪽 자간 넓은 캡션 · 아래 페이지 */
.logo{{position:absolute;left:96px;top:54px;font-weight:900;font-size:34px;letter-spacing:-.03em;z-index:6}}
.logo i{{font-style:normal;color:var(--accent)}}
.cap{{position:absolute;right:96px;top:62px;font-weight:600;font-size:19px;letter-spacing:.34em;
  color:{t['ink_soft']};z-index:6}}
.pg{{position:absolute;right:96px;bottom:52px;font-weight:600;font-size:22px;letter-spacing:.22em;
  color:{t['ink_soft']};z-index:6}}
.pg b{{color:{t['ink']};font-weight:800}}
.pager{{position:absolute;left:96px;bottom:60px;display:flex;gap:13px;z-index:6}}
.pager i{{width:9px;height:9px;border-radius:50%;background:{t['ink']};opacity:.22}}
.pager i.on{{opacity:1;transform:scale(1.25)}}
.prog{{position:absolute;left:96px;bottom:64px;width:420px;height:3px;border-radius:2px;
  background:rgba(31,29,43,.16);z-index:6}}
.prog i{{position:absolute;left:0;top:0;height:100%;border-radius:2px;background:var(--accent)}}
.clip.deep .prog{{background:rgba(244,241,234,.22)}}
/* 제목 덩어리 — 키커 · 제목(둘째 줄 강조) · 물결 밑줄 */
.tblock{{position:absolute;left:124px;top:150px;width:var(--tw);z-index:6}}
.kick{{font-weight:700;font-size:21px;letter-spacing:.32em;color:{t['ink_sub']};margin-bottom:22px}}
.kick em{{font-style:normal;color:var(--accent)}}
h2.ttl{{font-weight:900;font-size:68px;line-height:1.2;letter-spacing:-.022em;word-break:keep-all}}
h2.ttl .l2{{display:block;color:var(--accent)}}
.squig{{display:block;margin-top:16px}}
/* 라벨 — 번호 · 굵은 머리 · 설명 */
.lbl{{position:absolute;left:var(--lx);top:var(--ly);width:var(--lw);padding-left:78px;word-break:keep-all;z-index:6}}
.lbl>em{{position:absolute;left:0;top:4px;font-style:normal;font-weight:800;font-size:30px;
  letter-spacing:.06em;color:var(--accent)}}
.lbl>em::after{{content:"";position:absolute;left:0;top:44px;width:40px;height:3px;border-radius:2px;
  background:currentColor;opacity:.35}}
.lbl>b{{display:block;font-weight:800;font-size:40px;line-height:1.3;letter-spacing:-.025em;white-space:pre-wrap}}
.lbl>span{{display:block;margin-top:.4em;font-weight:500;font-size:27px;line-height:1.5;color:{t['ink_sub']};
  white-space:pre-wrap}}
.clip.figs .lbl>b{{font-size:34px}}
.lbl>b>i{{font-style:normal}}
.lbl>b>.caret{{display:inline-block;width:4px;height:.95em;margin-left:4px;vertical-align:-.1em;
  background:var(--accent);opacity:0;text-decoration:none}}
/* 강 표지·맺음 — 깊은 남색 바탕 */
.clip.deep{{color:{t['on_deep']}}}
.clip.deep .cap,.clip.deep .pg{{color:rgba(244,241,234,.6)}}
.clip.deep .pg b{{color:{t['on_deep']}}}
.clip.deep .pager i{{background:{t['on_deep']}}}
.clip.deep .kick{{color:rgba(244,241,234,.75)}}
.clip.deep h2.ttl{{font-size:104px;line-height:1.08}}
.clip.deep .grain{{mix-blend-mode:screen;opacity:.18}}
.clip.deep .lbl>span{{color:rgba(244,241,234,.8)}}
"""


# ── 장 하나 ───────────────────────────────────────────────────────────────
def _split_title(title: str) -> List[str]:
    """제목은 **한 줄**(사용자 지시 2026-10-09) — 둘로 가르면 둘째 줄이 도식·카드 위를 덮었다."""
    return [title]


DENSE_MODES = ("keep", "shrink", "hide", "backdrop", "recede")


def label_chars(sc: Dict[str, Any]) -> int:
    return sum(len(l.get("head") or "") + len(l.get("sub") or "") for l in sc.get("labels") or [])


def dense_mode(sc: Dict[str, Any], t: Dict[str, Any]) -> str:
    """이 장에 쓸 방식. look.dense_mode 가 있으면 그것(장마다 손으로), 없으면 글자 수가 기준을 넘을 때 테마 기본."""
    look = sc.get("look") or {}
    if look.get("dense_mode") in DENSE_MODES:
        return look["dense_mode"]
    if label_chars(sc) >= int(t.get("dense_chars", 70)):
        return t.get("dense_mode", "keep")
    return "keep"


def scene_html(sc: Dict[str, Any], i: int, n: int, theme: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """section.clip 안쪽. sc 는 hyper._plan 의 장 사전(+look·kind)."""
    t = theme
    look = sc.get("look") or {}
    kind = look.get("kind") or ("cover" if sc.get("kind") == "cover" else
                                "closing" if sc.get("kind") == "closing" else "body")
    deep = kind in ("cover", "closing")
    b = base_for(t, look.get("chunk", 0))
    bg = t["deep"] if deep else b["bg"]
    accent = t["mustard"] if deep else b["accent"]
    seed = int(sc["no"]) * 7919 + int(look.get("chunk", 0)) * 131
    rnd = random.Random(seed)
    ink = t["on_deep"] if deep else t["ink"]
    p: List[str] = []
    p.append(f'<style>#sc{sc["no"]:03d}{{--bg:{bg};--accent:{accent};--tw:{t["text_w"]}%}}</style>')

    has_obj = bool(sc["image"]) and kind not in ("fig", "card")
    ox, oy, ow, oh = t["obj_box_cover"] if deep else t["obj_box"]
    # 글이 많은 장 — 사물을 어떻게 할지(dense_mode): keep 그대로 · shrink 오른쪽 아래로 작게 ·
    #   hide 빼기 · backdrop 흐리게 크게 깔아 배경처럼 · recede 처음엔 앞에, 라벨이 뜨면 뒤로 물러남
    mode = dense_mode(sc, t) if has_obj and not deep else "keep"
    lab_w = None
    if mode == "shrink":
        ox, oy, ow, oh = t.get("obj_box_small", (68, 52, 26, 32))
        lab_w = 60
    elif mode == "hide":
        has_obj = False
        lab_w = 84
    elif mode in ("backdrop", "recede"):
        lab_w = 84 if mode == "backdrop" else None
        if mode == "backdrop":
            ox, oy, ow, oh = (50, 4, 58, 96)
    # ① 덩어리 — 오브젝트 뒤 큰 것 하나, 모서리에서 삐져나온 작은 것 하나
    if kind in ("fig", "card"):
        p.append(_blob("b2", -60 + rnd.uniform(-30, 30), 1080 + rnd.uniform(-20, 30), 250, b["blob2"], seed + 2, False))
    else:
        cx = (ox + ow / 2) / 100 * 1920 + rnd.uniform(-30, 30)
        cy = (oy + oh / 2) / 100 * 1080 + rnd.uniform(-20, 20)
        big = b["blob"] if not deep else t["accent"]
        if mode == "hide":       # 사물이 없으면 큰 덩어리는 오른쪽 위 구석에 작게
            cx, cy = 1920 + rnd.uniform(-60, -10), 120 + rnd.uniform(-20, 20)
        r1 = {"shrink": 170, "hide": 280, "backdrop": 520}.get(mode, (360 if deep else 215) if has_obj else 300)
        p.append(_blob("b1" + (" dim" if mode == "backdrop" else ""), cx, cy, r1, big, seed + 1))
        corner = rnd.choice([(-40, 1100), (1980, -30), (-50, -40)])
        p.append(_blob("b2", corner[0], corner[1], 230, b["blob2"] if not deep else t["cobalt"], seed + 2, False))
    # ② 그림 — 오브젝트(투명 PNG) 또는 도식/문제 카드 전면 PNG
    if kind == "fig" and look.get("fig"):
        # 도식은 PNG 가 아니라 **살아 있는 SVG/표** — 선이 그어지고 면·글자가 차례로 채워진다(fig_html·timeline)
        p.append(fig_html(look["fig"], t))
    elif sc["image"]:
        if kind in ("fig", "card"):
            p.append(f'<img class="full" src="./img/{sc["no"]:03d}.png" alt="">')
        elif has_obj:
            cls = {"backdrop": "obj back", "recede": "obj recede"}.get(mode, "obj")
            p.append(f'<img class="{cls}" src="./img/{sc["no"]:03d}.png" alt="" '
                     f'style="left:{ox}%;top:{oy}%;width:{ow}%;height:{oh}%">')
    # ③ 낙서 장식 — 오브젝트 둘레(본문) / 오른쪽 위(도식)
    if kind in ("fig", "card"):
        p.append(_sparkle(1760, 150, 38, ink))
    else:
        ax, ay = ox / 100 * 1920, oy / 100 * 1080
        aw, ah = ow / 100 * 1920, oh / 100 * 1080
        p.append(_sparkle(ax + rnd.uniform(-20, 40), ay + rnd.uniform(-10, 40), 46, ink))
        p.append(_star(ax + aw - 60 + rnd.uniform(-30, 10), ay + rnd.uniform(-30, 30), 62, t["mustard"], t["ink"],
                       rnd.uniform(-18, 18)))
        if mode not in ("hide", "backdrop"):          # 사물 둘레 장식은 사물이 앞에 있을 때만
            if rnd.random() < .5:
                p.append(_dots(ax + aw - 120, ay + ah + 10, ink))
            else:
                p.append(_circle_scribble(ax + aw - 170, ay + ah - 70, 170, 100, accent))
            # 화살표 낙서는 쓰지 않는다(사용자 지시 2026-10-09)
    p.append('<div class="grain"></div>')
    # ④ 머리말
    logo = meta.get("logo") or ""
    if logo:
        p.append(f'<div class="logo">{esc(logo)}<i>.</i></div>')
    if meta.get("caption"):
        p.append(f'<div class="cap">{esc(meta["caption"])}</div>')
    # ⑤ 제목 덩어리
    title = sc.get("title") or ""
    if title:
        lines = _split_title(title)
        tt = esc(lines[0]) + (f'<span class="l2">{esc(lines[1])}</span>' if len(lines) > 1 else "")
        kick = look.get("kicker") or ""
        kh = ""
        if kick:
            num, _, rest = kick.partition(" — ")
            kh = (f'<div class="kick"><em>{esc(num)}</em> — {esc(rest)}</div>' if rest
                  else f'<div class="kick">{esc(kick)}</div>')
        top = 300 if deep else 150
        p.append(f'<div class="tblock" style="top:{top}px">{kh}<h2 class="ttl">{tt}</h2>'
                 f'{_squiggle(accent, 220 if not deep else 300)}</div>')
    # ⑥ 라벨
    for j, l in enumerate(sc["labels"]):
        sub = f'<span>{esc(l["sub"])}</span>' if l["sub"].strip() else ""
        num = f"{j + 1:02d}"
        head = esc(l["head"])
        if t.get("label_reveal") == "type":
            head = "".join(f"<i>{esc(c)}</i>" for c in l["head"]) + '<u class="caret"></u>'
        lw = max(l["w"], lab_w) if lab_w else l["w"]
        p.append(f'<div class="lbl" data-i="{j}" style="--lx:{l["x"]}%;--ly:{l["y"]}%;--lw:{lw}%">'
                 f'<em>{num}</em><b>{head}</b>{sub}</div>')
    # ⑦ 아래 — 페이저 · 쪽수
    # 쪽수 — longform 이 실은 강 전체 번호(look.page/pages)가 있으면 그것. 섹션을 이어 붙여도 이어진다
    cur, tot = int(look.get("page") or i + 1), int(look.get("pages") or n)
    if tot <= 24:
        dots = "".join(f'<i class="{"on" if k == cur - 1 else ""}"></i>' for k in range(tot))
        p.append(f'<div class="pager">{dots}</div>')
    else:
        # 장이 많으면 점 대신 가는 진행선 — 회색 괘선 위로 강조색이 강 전체 비율만큼
        p.append(f'<div class="prog"><i style="width:{100 * cur / tot:.2f}%"></i></div>')
    p.append(f'<div class="pg"><b>{cur:02d}</b> / {tot:02d}</div>')
    return "\n".join(p)


def section_class(sc: Dict[str, Any]) -> str:
    look = sc.get("look") or {}
    kind = look.get("kind") or sc.get("kind") or ""
    if kind in ("cover", "closing"):
        return "clip deep"
    if kind in ("fig", "card"):
        return "clip figs"
    return "clip"


# ── 모션 ─────────────────────────────────────────────────────────────────
def timeline(sc: Dict[str, Any], sid: str, lbl_dur: float, lbl_rise: float, sec,
             theme: Optional[Dict[str, Any]] = None) -> List[str]:
    """장 하나의 GSAP 줄들. 라벨 시각(at)은 hyper 가 계산한 것을 그대로 쓴다."""
    s0, dur = sc["start"], sc["dur"]
    L: List[str] = []
    q = lambda sel: f"#{sid} {sel}"  # noqa: E731
    # 덩어리 — 커지며 들어오고(0.9s) 장 내내 아주 느리게 숨쉰다
    L.append(f'tl.from("{q(".blob")}", {{ scale: .82, autoAlpha: 0, duration: .9, ease: "power3.out", '
             f'stagger: .12 }}, {s0:.3f});')
    breath = max(0.0, dur - 1.0)
    if breath > 2:
        L.append(f'tl.to("{q(".blob.b1")}", {{ scale: 1.035, rotation: 1.2, duration: {breath / 2:.3f}, '
                 f'ease: "sine.inOut", yoyo: true, repeat: 1 }}, {s0 + .9:.3f});')
    # 오브젝트 — 살짝 기울어 떨어지듯 들어오고, 떠 있다
    # 사물 — 붓으로 칠하듯 대각선으로 쓸며 드러난다(떨어지듯 들어오는 대신, 사용자 지시 2026-10-09)
    L.append(f'tl.fromTo("{q("img.obj")}", {{ clipPath: "polygon(0% 0%, 0% 0%, -40% 100%, -40% 100%)" }}, '
             f'{{ clipPath: "polygon(0% 0%, 140% 0%, 100% 100%, -40% 100%)", duration: 1.5, ease: "power1.inOut" }}, '
             f'{s0 + .3:.3f});')
    if breath > 2:
        n = max(1, int(breath // 3.2))
        L.append(f'tl.to("{q("img.obj")}", {{ y: -12, rotation: 1.2, duration: {breath / (2 * n):.3f}, '
                 f'ease: "sine.inOut", yoyo: true, repeat: {2 * n - 1} }}, {s0 + 1.05:.3f});')
    L.append(f'tl.from("{q("img.full")}", {{ y: 24, autoAlpha: 0, duration: .7, ease: "power3.out" }}, {s0 + .1:.3f});')
    # 제목 — 키커 → 제목 → 밑줄이 그어진다
    L.append(f'tl.from("{q(".kick")}", {{ x: -18, autoAlpha: 0, duration: .5, ease: "power3.out" }}, {s0 + .1:.3f});')
    L.append(f'tl.from("{q("h2.ttl")}", {{ y: 22, autoAlpha: 0, duration: .6, ease: "power3.out" }}, {s0 + .2:.3f});')
    L.append(f'tl.to("{q(".squig .ln")}", {{ strokeDashoffset: 0, duration: .8, ease: "power2.inOut" }}, {s0 + .6:.3f});')
    # 낙서 — 팝(반짝이·별·점) / 그어짐(화살표·동그라미)
    L.append(f'tl.from("{q(".dd.pop")}", {{ scale: 0, rotation: -40, autoAlpha: 0, duration: .55, '
             f'ease: "back.out(2.2)", stagger: .15 }}, {s0 + .8:.3f});')
    L.append(f'tl.to("{q(".dd .ln")}", {{ strokeDashoffset: 0, duration: .9, ease: "power2.inOut", '
             f'stagger: .2 }}, {s0 + 1.0:.3f});')
    if breath > 2:
        L.append(f'tl.to("{q(".dd.pop")}", {{ rotation: 12, scale: 1.08, duration: 1.6, ease: "sine.inOut", '
                 f'yoyo: true, repeat: {max(1, int(breath // 1.6) - 1)} }}, {s0 + 1.4:.3f});')
    # 라벨 — 말하는 순간에(번호 먼저, 글 뒤따라)
    for i, l in enumerate(sc["labels"]):
        sel = f"#{sid} .lbl[data-i='{i}']"
        at = min(sec(l["at"]), max(0.0, dur - lbl_dur))
        a0 = s0 + at
        if (theme or {}).get("label_reveal") == "type":
            # typing - per-char pace follows how long the narrator takes to say this head
            n = max(1, len(l["head"]))
            say = sec(l.get("say_end"), 0) - sec(l["at"], 0) if l.get("say_end") is not None else n * .11
            per = min(.09, max(.035, say / n))
            typ = per * n
            L.append(f'tl.from("{sel}>em", {{ x: -16, autoAlpha: 0, duration: .35, ease: "power3.out" }}, {a0:.3f});')
            L.append(f'tl.set("{sel}>b>.caret", {{ opacity: 1 }}, {a0 + .1:.3f});')
            L.append(f'tl.from("{sel}>b>i", {{ autoAlpha: 0, duration: .01, stagger: {per:.3f} }}, {a0 + .15:.3f});')
            L.append(f'tl.to("{sel}>b>.caret", {{ opacity: 0, duration: .12, repeat: 3, yoyo: true }}, {a0 + .15 + typ:.3f});')
            L.append(f'tl.set("{sel}>b>.caret", {{ display: "none" }}, {a0 + .7 + typ:.3f});')
            L.append(f'tl.from("{sel}>span", {{ y: 14, autoAlpha: 0, duration: .5, ease: "power3.out" }}, {a0 + .2 + typ:.3f});')
        else:
            L.append(f'tl.from("{sel}", {{ y: {lbl_rise}, autoAlpha: 0, duration: {lbl_dur}, ease: "power3.out" }}, {a0:.3f});')
            L.append(f'tl.from("{sel}>em", {{ x: -16, duration: {lbl_dur}, ease: "power3.out" }}, {a0:.3f});')
    # 도식 — 문서 순서(대개 왼쪽→오른쪽, 위→아래)대로 그린다. 상자 선을 긋고 → 면을 채우고 → 글자.
    #   전체 그리기 시간 = 요소당 0.22초(최소 3초), 장 길이의 60% 를 넘지 않게
    look = sc.get("look") or {}
    if look.get("kind") == "fig" and look.get("fig"):
        fk, _, n = prep_fig(look["fig"], theme or {})
        t0 = s0 + .9
        span = min(max(3.0, n * .22), max(3.0, dur * .6))
        step = span / max(1, n)
        if fk == "svg":
            # ★ 그리는 순서 = **화면 위치**(왼→오, 같은 열이면 위→아래). Claude 가 쓴 SVG 는 상자를 다 쓰고
            #   글자를 몰아 쓰므로 문서 순서대로 그리면 상자가 다 생긴 뒤에야 글자가 나온다(2026-10-09 캡처).
            #   열 폭 90 단위로 묶어 상자·그림자·글자가 한 묶음으로 그려지게 한다.
            L.append(f'(function(){{const E=[...document.querySelectorAll("#{sid} .figbox .dk")]'
                     f'.sort((a,b)=>(+a.dataset.o||0)-(+b.dataset.o||0));'
                     f'E.forEach((e,i)=>{{const t={t0:.3f}+i*{step:.4f};'
                     # 글자는 왼쪽→오른쪽으로 써지듯(clip-path 가 글자 상자를 걷어 낸다)
                     f'if(e.classList.contains("dt")){{tl.fromTo(e,{{opacity:1,clipPath:"inset(-20% 100% -20% 0%)"}},'
                     f'{{clipPath:"inset(-20% 0% -20% 0%)",duration:.55,ease:"none"}},t);}}'
                     f'else{{const fo=+(e.getAttribute("fill-opacity")||1);'
                     # 선을 먼저 끝까지 긋고(1초) → 그다음 면을 채운다 — 「나타남」이 아니라 「그림」으로 보이게
                     f'tl.to(e,{{strokeDashoffset:0,duration:1.0,ease:"power1.inOut"}},t);'
                     f'tl.to(e,{{fillOpacity:fo,duration:.6,ease:"power1.out"}},t+.85);}}}});}})();')
        else:
            L.append(f'(function(){{const E=[...document.querySelectorAll("#{sid} .figbox tr")];'
                     f'E.forEach((e,i)=>tl.fromTo(e,{{opacity:0,y:10}},{{opacity:1,y:0,duration:.45,ease:"power2.out"}},'
                     f'{t0:.3f}+i*{max(.35, step):.3f}));}})();')
    # recede — 첫 라벨이 뜰 때 사물이 흐려지며 뒤로 물러난다(글이 주인공이 되는 순간)
    ats = [min(sec(l["at"]), max(0.0, dur - lbl_dur)) for l in sc["labels"]]
    if ats:
        t0 = s0 + max(1.2, min(ats))
        L.append(f'tl.to("{q("img.recede")}", {{ opacity: .26, scale: 1.12, xPercent: 8, '
                 f'filter: "saturate(.55)", duration: 1.2, ease: "power2.inOut" }}, {t0:.3f});')
        L.append(f'tl.to("{q(".blob.b1")}", {{ opacity: .38, duration: 1.2, ease: "power2.inOut" }}, {t0:.3f});')
    # 없는 요소(오브젝트 없는 장·설명 없는 라벨 등)는 건너뛴다 — GSAP 경고·린트 잡음을 없앤다
    return [re.sub(r'^tl\.(\w+)\("([^"]+)"', r'has("\2") && tl.\1("\2"', x) for x in L]
