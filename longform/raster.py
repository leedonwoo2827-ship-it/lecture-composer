"""HTML/SVG → PNG (Playwright 크로미움). 도식 슬라이드 배경과 유튜브 썸네일에 쓴다.

★ backplate 의 모션 렌더(s12h-hyper)는 슬라이드의 HTML 조각을 그리지 않는다 — 그림(NNN.png)·
  제목·라벨만 그린다. 그래서 요약노트의 SVG 도식은 **여기서 PNG 로 구워** 그 장의 그림으로 넣는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

IVORY = "#F6F1E8"


def _page_html(inner: str, w: int, h: int, bg: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"html,body{{margin:0;width:{w}px;height:{h}px;background:{bg};overflow:hidden;"
            f"font-family:'Pretendard','Malgun Gothic','Noto Sans KR',sans-serif}}</style></head>"
            f"<body>{inner}</body></html>")


def svg_slide(svg: str, top_pct: float = 13, bottom_pct: float = 74) -> str:
    """1920×1080 판: 위 제목 띠는 비우고, **흰 카드** 위에 도식을 비율 유지로 꽉 채운다(아래는 라벨·자막 자리)."""
    if svg.lstrip().lower().startswith("<table"):
        # ★ 영상 원고의 도식 중에는 **표**가 있다 — SVG 처럼 키울 수 없으므로 표 전용 모양을 준다
        #   (2026-10-02 실측: 기본 글씨 그대로 아주 작게 나왔다). 넘치면 글자를 줄여 다 보이게.
        return (f"<style>.tb{{width:100%;border-collapse:collapse;font-size:30px;line-height:1.35;color:#1d2433}}"
                ".tb th{background:#1F4E79;color:#fff;font-weight:700;padding:12px 16px;text-align:left}"
                ".tb td{padding:11px 16px;border-bottom:1px solid #d9e2ec;vertical-align:top;word-break:keep-all}"
                ".tb tr:nth-child(even) td{background:#F4F8FC}.tb td:first-child{font-weight:700;color:#1F4E79}</style>"
                f"<div id='tbox' style='position:absolute;left:7%;right:7%;top:{top_pct}%;bottom:{100 - bottom_pct}%;"
                "background:#fff;border-radius:22px;box-shadow:0 10px 30px rgba(31,78,121,.12),0 2px 6px rgba(0,0,0,.06);"
                "padding:28px 36px;box-sizing:border-box;display:flex;align-items:center;overflow:hidden'>"
                + svg.replace("<table", "<table class='tb'", 1) + "</div>"
                "<script>const b=document.getElementById('tbox'),t=b.querySelector('table');let s=30;"
                "while((t.scrollHeight>b.clientHeight-56||t.scrollWidth>b.clientWidth-72)&&s>16){s-=1;t.style.fontSize=s+'px';}</script>")
    fit = ('<svg style="max-width:100%;max-height:100%;width:100%;height:100%" '
           'preserveAspectRatio="xMidYMid meet"')
    body = svg.replace("<svg", fit, 1)
    return (f"<div style='position:absolute;left:7%;right:7%;top:{top_pct}%;bottom:{100 - bottom_pct}%;"
            "background:#fff;border-radius:22px;box-shadow:0 10px 30px rgba(31,78,121,.12),0 2px 6px rgba(0,0,0,.06);"
            "padding:28px 36px;box-sizing:border-box;display:flex;align-items:center;justify-content:center'>"
            f"{body}</div>")


CARD_CSS = """
@counter-style circled{system:fixed;symbols:"①" "②" "③" "④" "⑤";suffix:"  "}
.qc{position:absolute;left:6%;right:6%;top:12.5%;bottom:5%;box-sizing:border-box;padding:34px 46px;
    background:#fff;border-radius:24px;box-shadow:0 12px 34px rgba(31,78,121,.13),0 2px 6px rgba(0,0,0,.06);
    font-size:29px;line-height:1.5;color:#1d2433;overflow:hidden}
.qc .qh{display:inline-block;font-size:21px;font-weight:700;color:#fff;background:#9a4d33;border-radius:999px;
        padding:3px 16px;margin-bottom:12px}
.qc .qq{font-size:37px;font-weight:800;color:#1F4E79;line-height:1.35;margin-bottom:16px;word-break:keep-all;letter-spacing:-.01em}
.qc .qp{background:#F7F4EE;border:1px solid #E6DED0;border-radius:14px;padding:14px 22px;margin:0 0 16px}
.qc p{margin:3px 0;word-break:keep-all}
.qc p.li{padding-left:1.1em;text-indent:-.8em}.qc p.li::before{content:"·  ";color:#9a4d33;font-weight:800}
.qc pre{font-family:Consolas,'D2Coding',monospace;font-size:24px;line-height:1.4;background:#1f2937;color:#e5edf5;
        border-radius:12px;padding:14px 20px;margin:10px 0;white-space:pre-wrap}
.qc table{border-collapse:collapse;font-size:24px;margin:10px 0;background:#fff}
.qc td,.qc th{border:1px solid #cfc6b6;padding:5px 14px}.qc th{background:#EEF3F8;color:#1F4E79}
.qc .fig{text-align:center;margin:8px 0}.qc .fig svg{max-height:290px;max-width:100%;height:auto;width:auto}
.qc ol{list-style:circled;margin:6px 0 0 0;padding-left:1.6em}
.qc li{margin:7px 0;padding-left:.2em;word-break:keep-all}
.qc li::marker{color:#1F4E79;font-weight:800}
"""


def card_slide(card_html: str, bottom_pct: float = 5) -> str:
    """기출 맛보기 문제 카드 — 위 제목 띠(12%)는 비우고 문제·지문(코드·그림·표)·보기를 담는다."""
    return f"<style>{CARD_CSS}.qc{{bottom:{bottom_pct}%}}</style>{card_html}"


def fit_card(card_html: str, bottom_pct: float = 5) -> str:
    """내용이 넘치면 글자를 줄인다(브라우저에서 높이를 재며 축소) — 잘리는 것보다 작게라도 다 보이게."""
    return (card_slide(card_html, bottom_pct) +
            "<script>const c=document.querySelector('.qc');let s=1;"
            "while(c.scrollHeight>c.clientHeight+2&&s>0.55){s-=0.05;c.style.fontSize=(29*s)+'px';"
            "c.querySelectorAll('pre,table').forEach(e=>e.style.fontSize=(24*s)+'px');"
            "c.querySelector('.qq').style.fontSize=(37*s)+'px';}</script>")


def _save(out: Path, data: bytes) -> None:
    """PNG 쓰기 — 다른 프로그램(이미지 뷰어·탐색기 미리보기)이 파일을 잡고 있으면 Windows 가 덮어쓰기를 막는다
    (2026-10-02 실측: OSError Errno 22). 몇 번 다시 시도하고, 그래도 안 되면 알아볼 수 있게 알린다."""
    import time
    for i in range(6):
        try:
            out.write_bytes(data)
            return
        except OSError:
            time.sleep(1.5)
    raise SystemExit(f"[error] 그림 파일을 쓸 수 없습니다 — 다른 프로그램(이미지 뷰어 등)에서 열려 있는지 보고 닫은 뒤 다시 누르십시오: {out}")


def svgs_to_png(items: List[Tuple[str, Path]], scale: float = 2.0) -> None:
    """[(svg, out_png)] — 도식을 원래 비율·고해상도(2배) PNG 로. HWPX 등 SVG 를 못 넣는 곳에 쓴다."""
    if not items:
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(device_scale_factor=scale, viewport={"width": 1200, "height": 900})
        import re as _re
        for svg, out in items:
            out.parent.mkdir(parents=True, exist_ok=True)
            # ★ SVG 에 width 가 없으면 감싼 상자가 0폭으로 접힌다(실측: 빈 PNG) → viewBox 로 폭을 정한다
            m = _re.search(r'viewBox\s*=\s*"[\d.\-]+\s+[\d.\-]+\s+([\d.]+)\s+([\d.]+)"', svg)
            vw = float(m.group(1)) if m else 800.0
            w = int(min(1180, max(480, vw * 1.25)))
            pg.set_content("<!doctype html><html><head><meta charset='utf-8'><style>body{margin:0;background:#fff;"
                           "font-family:'Pretendard','Malgun Gothic',sans-serif}"
                           f"#f{{width:{w}px;padding:8px}}#f svg{{display:block;width:100%;height:auto}}</style></head>"
                           f"<body><div id='f'>{svg}</div></body></html>", wait_until="load")
            _save(out, pg.locator("#f").screenshot())
        br.close()


def render_many(jobs: List[Tuple[str, Path]], w: int = 1920, h: int = 1080, bg: str = IVORY) -> None:
    """[(inner_html, out_png)] 를 한 브라우저로 차례로 굽는다."""
    if not jobs:
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": w, "height": h})
        for inner, out in jobs:
            out.parent.mkdir(parents=True, exist_ok=True)
            pg.set_content(_page_html(inner, w, h, bg), wait_until="load")
            _save(out, pg.screenshot(full_page=False))
        br.close()
