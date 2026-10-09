"""영상 테마 미리보기 — 집필(Claude)·backplate 프로젝트 없이 **SQLD 샘플 장면**으로 테마를 굽는다.

    .venv\\Scripts\\python tools\\theme_preview.py                     # danjeong, 장면 PNG
    .venv\\Scripts\\python tools\\theme_preview.py --mp4               # + 소리 있는 mp4(HyperFrames)
    .venv\\Scripts\\python tools\\theme_preview.py --codex             # 오브젝트를 codex 로 실제로 그림(캐시)
    .venv\\Scripts\\python tools\\theme_preview.py --redraw            # 도식을 Claude 로 다시 그림(캐시)
    .venv\\Scripts\\python tools\\theme_preview.py --theme ivory       # 원래 룩과 비교

결과: out/theme-preview/<theme>/  (still-XX.png · contact.png · preview.mp4 · _hyper/)
소리: Windows SAPI 한국어 음성(있으면)으로 장마다 wav 를 만든다 → 라벨이 **말하는 순간**에 뜨는지(sync) 본다.
      없으면 무음, 길이는 글자 수로 어림.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine" / "backplate"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ENGINE))

# ── SQLD 샘플(시험용 문장 — 자체 작성) ──────────────────────────────────────
OLD_SVG = """<svg viewBox="0 0 960 300" xmlns="http://www.w3.org/2000/svg">
<rect width="960" height="300" fill="#ffffff"/>
<g font-size="24" text-anchor="middle">
<rect x="20" y="90" width="190" height="110" rx="10" fill="#9DC3E6"/><text x="115" y="140" fill="#1F4E79" font-weight="700">제1정규형</text><text x="115" y="172" font-size="18" fill="#334155">원자값</text>
<rect x="260" y="90" width="190" height="110" rx="10" fill="#9DC3E6"/><text x="355" y="140" fill="#1F4E79" font-weight="700">제2정규형</text><text x="355" y="172" font-size="18" fill="#334155">부분 종속 제거</text>
<rect x="500" y="90" width="190" height="110" rx="10" fill="#9DC3E6"/><text x="595" y="140" fill="#1F4E79" font-weight="700">제3정규형</text><text x="595" y="172" font-size="18" fill="#334155">이행 종속 제거</text>
<rect x="740" y="90" width="190" height="110" rx="10" fill="#fff3d6"/><text x="835" y="140" fill="#1F4E79" font-weight="700">BCNF</text><text x="835" y="172" font-size="18" fill="#334155">결정자 = 후보키</text>
<path d="M212 145 H256 M452 145 H496 M692 145 H736" stroke="#1F4E79" stroke-width="3"/>
</g></svg>"""

TABLE = ("<table><tr><th>연산자</th><th>결과</th><th>중복 행</th></tr>"
         "<tr><td>UNION</td><td>두 결과의 합집합</td><td>제거(정렬 발생)</td></tr>"
         "<tr><td>UNION ALL</td><td>두 결과를 그대로 이어 붙임</td><td>유지</td></tr>"
         "<tr><td>INTERSECT</td><td>양쪽에 모두 있는 행</td><td>제거</td></tr>"
         "<tr><td>EXCEPT / MINUS</td><td>앞 결과에만 있는 행</td><td>제거</td></tr></table>")

CARD = ('<div class="qc"><div class="qh">기출 맛보기 · 문제 1</div>'
        '<div class="qq">다음 SQL 의 실행 결과로 반환되는 행의 수는?</div>'
        '<div class="qp"><pre>SELECT D.DEPT_NAME, COUNT(E.EMP_ID)\nFROM DEPT D\nLEFT OUTER JOIN EMP E\n  ON D.DEPT_ID = E.DEPT_ID\nGROUP BY D.DEPT_NAME;</pre>'
        '<p class="li">DEPT 는 4개 부서, EMP 는 그중 3개 부서에만 사원이 있다.</p></div>'
        '<ol><li>2</li><li>3</li><li>4</li><li>7</li></ol></div>')

SLIDES = [
    {"kind": "cover", "title": "3강 · 정규화와 조인", "chunk": 0,
     "say": "안녕하세요. 이번 강에서는 이상현상을 없애는 정규화와, 흩어진 테이블을 다시 잇는 조인, 그리고 인덱스를 정리합니다."},
    {"kind": "body", "chunk": 0, "group": "정규화", "gi": 1, "title": "정규화 — 이상현상을 없애는 분해",
     "bullets": ["삽입 이상", "갱신 이상", "삭제 이상"], "obj": "정규화",
     "say": "정규화는 한 테이블에 여러 주제가 섞여 생기는 문제를, 테이블을 나눠 없애는 과정입니다. "
            "원하지 않는 값까지 함께 넣어야 하는 삽입 이상, 같은 값을 여러 곳에서 고쳐야 하는 갱신 이상, "
            "하나를 지우면 다른 정보까지 사라지는 삭제 이상이 대표적입니다."},
    {"kind": "fig", "chunk": 0, "group": "정규화", "gi": 1, "title": "정규형의 단계", "fig": OLD_SVG,
     "say": "제1정규형은 모든 속성이 원자값을 갖게 하고, 제2정규형은 부분 함수 종속을, "
            "제3정규형은 이행 함수 종속을 없앱니다. BCNF 는 모든 결정자가 후보키가 되게 합니다."},
    {"kind": "body", "chunk": 1, "group": "조인", "gi": 2, "title": "조인 — 흩어진 테이블을 다시 잇다",
     "bullets": ["INNER JOIN", "LEFT OUTER JOIN", "NATURAL JOIN"], "obj": "조인",
     "say": "조인은 나눠 둔 테이블을 공통 컬럼으로 다시 잇는 연산입니다. 양쪽에 모두 있는 행만 남기는 INNER JOIN, "
            "왼쪽 테이블의 행을 모두 남기는 LEFT OUTER JOIN, 같은 이름의 컬럼으로 알아서 잇는 NATURAL JOIN 을 구분하세요."},
    {"kind": "fig", "chunk": 1, "group": "조인", "gi": 2, "title": "집합 연산자 한눈에", "fig": TABLE,
     "say": "집합 연산자는 두 SELECT 결과를 위아래로 합칩니다. UNION 은 중복을 지우고, UNION ALL 은 그대로 둡니다."},
    {"kind": "card", "chunk": 2, "group": "기출 맛보기", "gi": 3, "title": "기출 맛보기", "card": CARD,
     "say": "기출 문제로 확인해 봅시다. 부서 테이블을 기준으로 LEFT OUTER JOIN 을 하면 사원이 없는 부서도 남습니다."},
    {"kind": "body", "chunk": 2, "group": "인덱스", "gi": 4, "title": "인덱스 — 찾는 길을 미리 깔아 두기",
     "bullets": ["B-Tree 인덱스", "인덱스 스캔과 풀 스캔"], "obj": "인덱스",
     "say": "인덱스는 원하는 행을 빨리 찾도록 미리 정렬해 둔 길입니다. 대부분의 DBMS 는 B-Tree 인덱스를 기본으로 쓰고, "
            "조건에 따라 인덱스 스캔과 풀 스캔 중 더 싼 길을 옵티마이저가 고릅니다."},
    {"kind": "closing", "title": "다음 강 — 서브쿼리", "chunk": 3,
     "say": "오늘은 정규화와 조인, 인덱스를 정리했습니다. 다음 강에서는 서브쿼리를 다룹니다."},
]

PLACEHOLDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="900" height="900">
<g transform="rotate(-8 200 200)" stroke="#1F1D2B" stroke-width="7" stroke-linejoin="round" stroke-linecap="round">
<path d="M90 110 v180 c0 30 220 30 220 0 v-180" fill="{c1}"/>
<ellipse cx="200" cy="110" rx="110" ry="32" fill="{c2}"/>
<path d="M90 170 c0 30 220 30 220 0 M90 230 c0 30 220 30 220 0" fill="none"/>
<path d="M120 150 v40" stroke="#fff" stroke-width="9" opacity=".8"/></g></svg>"""


def sapi_wav(text: str, out: Path) -> float:
    """Windows SAPI 한국어 음성으로 wav. 실패하면 0."""
    if os.name != "nt":
        return 0.0
    ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -eq 'ko-KR'}|select -First 1; "
          "if(-not $v){exit 3}; $s.SelectVoice($v.VoiceInfo.Name); $s.Rate=1; "
          f"$s.SetOutputToWaveFile('{out}'); $s.Speak([IO.File]::ReadAllText('{out}.txt')); $s.Dispose()")
    out.with_suffix(".wav.txt").write_text(text, encoding="utf-8")
    Path(str(out) + ".txt").write_text(text, encoding="utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    if r.returncode != 0 or not out.is_file():
        return 0.0
    with wave.open(str(out)) as w:
        return w.getnframes() / float(w.getframerate())


def make_object(name: str, prompt: str, out: Path, use_codex: bool, cache: Path, th) -> None:
    key = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]
    c = cache / f"{key}.png"
    if c.is_file():
        shutil.copy2(c, out)
        return
    if use_codex:
        os.environ["CODEX_IMAGE_BACKGROUND"] = "transparent"
        from imgstudio.services.codex_image import generate_image
        print(f"  codex: {name} …", flush=True)
        img, _ = generate_image(prompt, size="1024x1024")
        cache.mkdir(parents=True, exist_ok=True)
        c.write_bytes(img)
        shutil.copy2(c, out)
        return
    from longform.raster import render_many
    svg = PLACEHOLDER.replace("{c1}", th["cobalt"] if th else "#9DC3E6").replace("{c2}", th["mustard"] if th else "#fff")
    render_many([(f"<div style='width:900px;height:900px'>{svg}</div>", out)], w=900, h=900,
                theme=th["name"] if th else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="danjeong")
    ap.add_argument("--mp4", action="store_true")
    ap.add_argument("--codex", action="store_true")
    ap.add_argument("--redraw", action="store_true", help="도식을 Claude 로 다시 그림(longform 잡 없이 임시 잡으로)")
    ap.add_argument("--no-tts", action="store_true")
    a = ap.parse_args()

    from longform import theme as vtheme
    from longform.raster import (card_slide_themed, fit_card, render_many, svg_slide, svg_slide_themed)
    from longform.s3_render import labels_for, object_prompt
    th = vtheme.get(a.theme)

    out = REPO / "out" / "theme-preview" / a.theme
    proj = out / "proj"
    for d in (proj / "img", proj / "audio"):
        d.mkdir(parents=True, exist_ok=True)

    # 1) 소리
    for i, s in enumerate(SLIDES, 1):
        wav = proj / "audio" / f"{i:03d}.wav"
        sec = 0.0 if a.no_tts else (sapi_wav(s["say"], wav) if not wav.is_file() else
                                    wave.open(str(wav)).getnframes() / float(wave.open(str(wav)).getframerate()))
        s["sec"] = sec or round(len(s["say"]) / 5.5, 2)
        s["has_audio"] = bool(sec)
    print("소리:", "SAPI" if any(s["has_audio"] for s in SLIDES) else "없음(글자 수 어림)")

    # 2) 도식·카드 PNG
    figs = []
    for i, s in enumerate(SLIDES, 1):
        p = proj / "img" / f"{i:03d}.png"
        if s["kind"] == "fig":
            f = s["fig"]
            if a.redraw and th and not f.lstrip().startswith("<table"):
                from longform.config import load_job
                from longform.redraw import redraw_one
                job = load_job("sqld-danjeong-sample")
                f = redraw_one(job, f)
            s["fig_live"] = f                     # 화면에서 그려지듯 — look.fig 로 싣는다(렌더와 같은 길)
            figs.append((svg_slide_themed(f, th, 31, 80) if th else svg_slide(f, bottom_pct=74), p))
        elif s["kind"] == "card":
            figs.append((card_slide_themed(s["card"], th) if th else fit_card(s["card"], 16), p))
    render_many(figs, theme=th["name"] if th else None)

    # 3) 오브젝트(테마) — 주제마다 하나, 표지·맺음은 빌려 쓴다
    if th:
        objs = {}
        for i, s in enumerate(SLIDES, 1):
            if s.get("obj"):
                objs.setdefault(s["obj"], i)
                make_object(s["obj"], object_prompt(s["obj"], "정규화와 조인", th), proj / "img" / f"{i:03d}.png",
                            a.codex, out.parent / "_objects", th)
        first, last = proj / "img" / f"{min(objs.values()):03d}.png", proj / "img" / f"{max(objs.values()):03d}.png"
        shutil.copy2(first, proj / "img" / "001.png")
        shutil.copy2(last, proj / "img" / f"{len(SLIDES):03d}.png")

    # 4) 덱
    slides = []
    for i, s in enumerate(SLIDES, 1):
        img = proj / "img" / f"{i:03d}.png"
        lab = labels_for({"kind": "", "bullets": s.get("bullets") or [], "say": s["say"],
                          "fig": 1 if s["kind"] == "fig" else None}, has_bg=bool(th), sub_band=True, th=th) \
            if s["kind"] in ("body", "fig") else []
        d = {"no": i, "kind": s["kind"] if s["kind"] in ("cover", "closing") else "", "title": s["title"],
             "image": f"img/{i:03d}.png" if img.is_file() else "",
             "audio": {"file": f"audio/{i:03d}.wav" if s["has_audio"] else "", "sec": s["sec"]},
             "narration": {"srt_text": s["say"]}, "labels": lab}
        if th:
            d["look"] = {"chunk": s["chunk"], "kind": s["kind"],
                         "kicker": f"{s['gi']:02d} — {s['group']}" if s.get("group") else ""}
            if s.get("fig_live"):
                d["look"]["fig"] = s["fig_live"]
        slides.append(d)
    deck = {"project": {"video_theme": a.theme if th else "", "theme_logo": "SQLD",
                        "theme_caption": "SQLD 종합본 — L03"}, "slides": slides}

    from render import hyper
    comp = out / "_hyper"
    if comp.exists():
        shutil.rmtree(comp)
    built = hyper.build(deck, proj_dir=proj, out_dir=comp, title="SQLD 미리보기", theme=a.theme)
    print(f"컴포지션: {built['scenes']}장 · {built['sec']:.1f}초 · 라벨 {built['labels']} · sync {built.get('sync')}")
    (out / "deck.json").write_text(json.dumps(deck, ensure_ascii=False, indent=1), encoding="utf-8")

    # 5) 스틸 — 장마다 끝 무렵(모든 라벨이 뜬 뒤)
    from playwright.sync_api import sync_playwright
    scenes = hyper._plan(deck)
    shots = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 1920, "height": 1080})
        pg.add_init_script("window.__timelines = window.__timelines || {};")  # HyperFrames 런타임이 하던 일
        pg.goto((comp / "index.html").as_uri())
        pg.wait_for_timeout(800)
        pg.evaluate("document.fonts.ready")
        for sc in scenes:
            t = sc["start"] + max(0.5, sc["dur"] - 0.6)
            pg.evaluate(f"""() => {{ const t = {t};
              document.querySelectorAll('section.clip').forEach(s => {{
                const a = +s.dataset.start, d = +s.dataset.duration;
                s.style.visibility = (t >= a && t < a + d) ? 'visible' : 'hidden'; }});
              window.__timelines.main.seek(t, false); }}""")
            pg.wait_for_timeout(150)
            p = out / f"still-{sc['no']:02d}.png"
            pg.screenshot(path=str(p))
            shots.append(p)
        # 낱장 모음
        cells = "".join(f"<img src='{p.as_uri()}' style='width:640px;height:360px;display:block'>" for p in shots)
        pg.set_viewport_size({"width": 1920, "height": 360 * ((len(shots) + 2) // 3)})
        pg.set_content(f"<body style='margin:0;display:flex;flex-wrap:wrap;width:1920px'>{cells}</body>")
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out / "contact.png"), full_page=True)
        br.close()
    print("스틸:", out)

    # 6) mp4
    if a.mp4:
        mp4 = out / "preview.mp4"
        r = subprocess.run(["node", "scripts/render.mjs", "--dir", str(comp), "--out", str(mp4), "--fps", "30"],
                           cwd=str(ENGINE))
        print("mp4:", mp4 if r.returncode == 0 else f"실패({r.returncode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
