"""글 많은 장 비교 — 실제 렌더된 섹션의 덱에서 라벨 글자가 많은 장을 골라, 사물 처리 방식별로 마지막 프레임을 나란히 굽는다.

    .venv\\Scripts\\python tools\\dense_compare.py --job sqld --only L01 [--top 4]

    방식(video_theme.DENSE_MODES): keep 그대로 · shrink 축소 · hide 빼기 · backdrop 배경처럼 · recede 물러나기
결과: out/dense-compare/<잡>-<강>/compare.png (행 = 장, 열 = 방식)
영상은 다시 굽지 않는다 — 그 장들만 컴포지션을 만들어 마지막 순간(라벨이 다 뜬 뒤)을 찍는다.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine" / "backplate"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ENGINE))
os.environ.setdefault("BP_SYNC", "text")          # 비교용 — STT 없이 글자 비례(빠름)

MODES = [("keep", "A 그대로"), ("shrink", "B 축소"), ("hide", "C 빼기"), ("backdrop", "D 배경"), ("recede", "D-2 물러나기")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--only", required=True, help="강 id, 예: L01")
    ap.add_argument("--top", type=int, default=4)
    a = ap.parse_args()

    from render import hyper, video_theme
    decks = sorted((REPO / "jobs" / a.job / "bp").glob(f"*-{a.only.lower()}-*/10_*/deck.json"))
    if not decks:
        raise SystemExit(f"[error] {a.only} 의 덱이 없습니다 — 먼저 render(s3)")
    th = video_theme.get("danjeong")
    pool = []
    for dp in decks:
        deck = json.loads(dp.read_text(encoding="utf-8"))
        for s in deck.get("slides") or []:
            if s.get("drop") or not s.get("image"):
                continue
            if (s.get("look") or {}).get("kind") not in (None, "", "body"):
                continue
            pool.append((video_theme.label_chars(s), dp, deck, s))
    pool.sort(key=lambda x: -x[0])
    # 같은 장 중복 제거(덱 사본이 여럿일 수 있다) → 풀이 장과 개념 장을 반반 섞는다
    seen, ans, con = set(), [], []
    for row in pool:
        s = row[3]
        if s["no"] in seen:
            continue
        seen.add(s["no"])
        (ans if (s.get("title") or "").startswith("정답") else con).append(row)
    half = a.top // 2
    pick = (ans[:half] + con[:a.top - half]) or pool[:a.top]
    if not pick:
        raise SystemExit("[error] 사물이 있는 본문 장이 없습니다")
    print("고른 장:", [(s["no"], n, (s.get("title") or "")[:20]) for n, _, _, s in pick])

    out = REPO / "out" / "dense-compare" / f"{a.job}-{a.only}"
    if out.exists():
        shutil.rmtree(out)
    shots = []          # [row][col] png
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 1920, "height": 1080})
        pg.add_init_script("window.__timelines = window.__timelines || {};")
        for r, (n, dp, deck, s) in enumerate(pick):
            row = []
            for mode, _ in MODES:
                d = copy.deepcopy(deck)
                one = copy.deepcopy(s)
                one.setdefault("look", {})["dense_mode"] = mode
                d["slides"] = [one]
                comp = out / f"r{r}-{mode}"
                hyper.build(d, proj_dir=dp.parent.parent, out_dir=comp, title="비교", theme="danjeong")
                sc = hyper._plan(d)[0]
                t = sc["start"] + max(0.5, sc["dur"] - 0.3)
                pg.goto((comp / "index.html").as_uri(), wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(600)
                pg.evaluate("document.fonts.ready.then(() => 1)")
                pg.evaluate(f"window.__timelines.main.seek({t}, false); 1")
                pg.wait_for_timeout(200)
                png = out / f"r{r}-{mode}.png"
                pg.screenshot(path=str(png))
                row.append(png)
            shots.append(row)
        # 모음: 행 = 장, 열 = 방식
        cw, ch = 560, 315
        head = "".join(f"<div style='width:{cw}px;font:800 26px sans-serif;padding:10px 0'>{lab}</div>" for _, lab in MODES)
        rows = "".join("<div style='display:flex;gap:8px;margin-bottom:8px'>" +
                       "".join(f"<img src='{p.as_uri()}' style='width:{cw}px;height:{ch}px'>" for p in row) + "</div>"
                       for row in shots)
        W = len(MODES) * (cw + 8)
        pg.set_viewport_size({"width": W, "height": 60 + len(shots) * (ch + 8)})
        pg.set_content(f"<body style='margin:0;background:#fff'><div style='display:flex;gap:8px'>{head}</div>{rows}</body>")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(out / "compare.png"), full_page=True)
        br.close()
    print("비교:", out / "compare.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
