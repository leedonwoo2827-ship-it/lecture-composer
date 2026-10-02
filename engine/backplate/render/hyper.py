# -*- coding: utf-8 -*-
"""덱 → HyperFrames 컴포지션 폴더.

    <dist>/_hyper/
      index.html            컴포지션 한 장
      vendor/gsap.min.js    자체 호스팅 — 렌더 중 네트워크 fetch 금지(결정론)
      assets/fonts/*.woff2  한글 폰트. 시스템 폰트에 기대지 않는다
      img/002.png …         배경판
      audio/002.wav …       내레이션

★ **왜 HyperFrames 인가.** 예전 길은 거꾸로였다 — 글자를 그림에 구워 놓고,
  스틸을 찍어 이어붙인 뒤, 그 픽셀에서 글자 상자를 **되찾아** 움직였다.
  상자를 되찾는 일이 안 됐다(줄 단위 9개를 사람이 5개로 합쳤다).
  11판은 글자가 DOM 이므로 **움직일 대상이 이미 있다.** GSAP 이 그 요소를
  직접 움직이고, HyperFrames 가 결정론적으로 굽는다. 상자도 지정기도 없다.

★ **시간을 여기서 다 계산한다.** 템플릿은 계산하지 않는다. 두 곳에서 계산하면
  언젠가 서로 달라지고, 그때 화면과 소리가 갈린다.

★ `data-start` 는 **숫자**여야 한다. id 참조를 쓰면 HyperFrames 의 static-frame
  중복 제거가 꺼져 렌더가 2.1배 느려진다(260831 실측: 51.9s vs 24.7s).

★ 오디오는 **HyperFrames 가 먹는다.** `<audio data-audio-group="voiceover">` 를
  놓으면 알아서 믹스한다 — ffmpeg 로 토막을 이어붙일 일이 없다.
"""
from __future__ import annotations

import json
import shutil
from html import escape as esc
from pathlib import Path
from typing import Any, Dict, List

APP = Path(__file__).resolve().parent.parent
FONT_DIR = APP / "static" / "fonts"
GSAP = APP / "static" / "vendor" / "gsap.min.js"

W, H, FPS = 1920, 1080, 30

# 장 사이의 숨. 소리가 끝나자마자 다음 장으로 넘어가면 숨이 찬다.
TAIL_SEC = 0.45
# 라벨 하나가 떠오르는 데 걸리는 시간과 올라오는 거리
LBL_DUR, LBL_RISE = 0.55, 26.0

# 빛 — **뜬 라벨 위로 빛이 천천히 왕복한다.**
# ★ **은은한 쪽으로 잡는다**(2026-09-18).
#   같은 밝기라도 **좁고 빠르면 번쩍이고, 넓고 느리면 숨쉬듯** 보인다. 그래서
#   remaster 의 1.1초/0.6초보다 크게 늘리고, 띠도 넓혀 옅게 깐다.
# ★ 1.9초도 **너무 빨랐다**(2026-09-18). 3.6초로 늘린다 — 글자 폭을
#   가로지르는 데 눈이 따라갈 만큼 느려야 "훑는다" 로 읽힌다.
# ★ **사이에 안 쉰다**(2026-09-18). `yoyo` 로 오른쪽 끝까지 갔다가 그대로
#   되돌아온다 — 쉼을 두면 "멎었다 다시 켜진다" 로 읽히는데, 원하는 것은
#   **끊기지 않고 살아 있는** 결이다. 느리기(3.6초)가 이미 그 일을 한다.
#   쉼이 필요해지는 때는 빠를 때다 — 빠른데 안 쉬면 그때 번쩍인다.
# ★ 세기를 올리지 마라. remaster 주석: "넘기면 번쩍여서 눈이 아프다".
SHEEN_DUR, SHEEN_GAP, SHEEN_FADE = 3.6, 0.0, 0.6
# 제목은 장이 시작하자마자
TITLE_DUR, TITLE_RISE = 0.5, 18.0

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:%(W)dpx;height:%(H)dpx;background:#F6F1E8;overflow:hidden;
  font-family:"Pretendard","Malgun Gothic",sans-serif;
  -webkit-font-smoothing:antialiased}
.clip{position:absolute;inset:0;width:%(W)dpx;height:%(H)dpx;background:#F6F1E8}
.clip>img{position:absolute;inset:0;width:100%%;height:100%%;object-fit:fill;display:block}
/* 제목 — 그림이 비워 둔 위 10%% 띠에 앉는다. 그림 안에는 제목이 없다. */
/* (판이던 시절의 유래.) 공짜 안전판이다 — 그림이 제목칸(1칸)을 아이보리로
   비워 두라는 지시를 지키면 같은 색이라 **안 보이고**, 안 지키면 그 위에 판이
   깔린다(2026-09-18: "어차피 지켜지면 같은 색상이고 안 지켜질 경우 색 박스니").
   라벨의 «셀색» 과 달리 끄는 스위치를 두지 않는 이유가 그것이다 — 지켜진 장에는
   흔적이 없으므로 끌 일이 없다.
   ★ padding 만큼 margin 을 되민다 — 글자는 3.2%%·2.1%% 그대로 앉는다.
     편집 화면(.lb-title)의 .93cqh/1.67cqh 를 1080 기준 px 로 옮긴 값이다. */
/* 제목도 **테두리**다(2026-09-18). 라벨과 같은 이유 —
   판은 글 길이와 상관없이 깔려 그림을 헛되이 가린다. `paint-order:stroke fill`
   로 윤곽을 먼저 긋고 글자 본체를 덮으므로 **바깥 절반만** 남는다.
   ★ 덤으로 **덱에서 제목 띠가 라벨 머리를 덮던 것**이 풀린다. 띠는 위쪽 62px
     통째를 칠하는 데다 z-index 가 2 라, 그 띠에 걸친 라벨이 통째로 잘렸다.
   ★ 굵기는 글자의 14%% — 라벨과 같은 비율이다. 셋이 같아야 편집 화면이
     거짓말을 안 한다.
   58px 의 14%% = 8px, 보이는 것은 4px. */
h2{position:absolute;left:3.2%%;top:2.1%%;font-size:58px;font-weight:800;
  letter-spacing:-.035em;color:#9a4d33;line-height:1.2;
  -webkit-text-stroke:8px #F6F1E8;paint-order:stroke fill}
/* 라벨 — 좌표는 %%다. 편집 화면(labels.js)과 **같은 규칙**이어야 한다.
   크기도 같다: 소제목 4%% of 1080 = 43px, 설명은 그 65%% = 28px. */
.lbl{position:absolute;left:var(--lx);top:var(--ly);width:var(--lw);
  word-break:keep-all}
.lbl>b{display:block;font-weight:700;font-size:43px;line-height:1.25;
  letter-spacing:-.02em;color:#1F4E79}
.lbl>span{display:block;margin-top:.35em;font-weight:500;font-size:28px;
  line-height:1.42;letter-spacing:-.01em;color:#334155}
/* 배경이 라벨 자리로 번진 장이 있다. 후광을 옅게 깔고, 그래도 안 읽히는
   자리는 `.cell` 로 판을 깐다 — 라벨마다 사람이 켠다(labels.js 의 «셀색»).
   ★ padding 만큼 margin 을 되민다: 판이 생겨도 글은 있던 자리에 그대로 있다.
     수치는 편집 화면·덱의 cqh 와 **같은 값**이다 — 1.2cqh of 1080 = 13px,
     1.6cqh = 17px, .9cqh = 10px. 셋이 어긋나면 편집 화면이 거짓말을 한다. */
.lbl>b,.lbl>span{text-shadow:0 0 8px #F6F1E8,0 0 16px #F6F1E8}
/* 사람이 친 **엔터를 그대로 살린다**(2026-09-18). HTML 은 줄바꿈을
   공백으로 뭉개므로 그냥 두면 입력칸에서 두 줄로 친 설명이 화면에서 한 줄로
   이어 붙는다.
   ★ `
` 을 `<br>` 로 바꾸지 **않는다.** 그 길은 라벨 글이 HTML 로 해석되는
     문을 여는 것이고(사람이 치는 칸이다), 입력칸 ↔ 화면이 글자 그대로
     오가지 않게 된다. `pre-wrap` 은 텍스트를 텍스트인 채로 두면서 줄바꿈만
     살린다 — 긴 줄은 여전히 상자 폭에 맞춰 접힌다. */
.lbl>b,.lbl>span{white-space:pre-wrap}
/* ★ **기본은 켜짐**(2026-09-18). 끄는 쪽이 사람 일이다 — 켜는 쪽을 사람
     일로 두면 **안 켠 장이 안 읽히는 채로 그냥 나간다.** 켜져 있으면 눈에
     거슬려서라도 끄게 된다. 안전한 쪽을 기본으로 두는 규칙이다.
   ★ 그래서 판정은 `cell` 이 **`false` 인가**로 한다. 없거나 true 면 켜짐 —
     지시문이 만든 라벨에는 이 칸이 아예 없다(`labels_of`). */
.lbl.cell-box{box-sizing:content-box;padding:13px 17px;margin:-13px -17px;
  background:#F6F1E8;border-radius:10px}
/* 굵기는 글자의 14%% — 소제목 43px→6px, 설명 28px→4px. 보이는 것은 그 절반. */
.lbl.cell-line>b{-webkit-text-stroke:6px #F6F1E8;paint-order:stroke fill}
.lbl.cell-line>span{-webkit-text-stroke:4px #F6F1E8;paint-order:stroke fill}
.lbl.cell-box>b,.lbl.cell-box>span,
.lbl.cell-line>b,.lbl.cell-line>span{text-shadow:none}
/* 빛 — **말하고 있는 라벨의 글자 위로만** 한 줄기가 천천히 오간다.
   ★ **네모 면이 아니라 글자를 훑는다**(2026-09-18). 앞 판은 반투명 네모를
     얹었는데, 윤곽 라벨
     (cell-line)에는 깔 판이 없어 **허공에 흰 네모가 떠다니는** 꼴이었다.
   ★ 방법: 글자를 **한 벌 더** 겹쳐 놓고(`<i class="shn">` 안의 b·span),
     그 사본에 `background-clip:text` 로 띠 그러데이션을 물린다. 사본은
     `color:transparent` 라 **띠가 글자를 지나는 자리에만** 흰빛이 보인다.
     바탕도 여백도 안 건드린다 — 글자만 환해진다.
   ★ 사본은 읽히면 안 된다: `aria-hidden` + `pointer-events:none`.
     글자 모양이 본체와 **한 픽셀도 달라선 안 되므로** 크기·자간·줄높이를
     그대로 다시 적는다(`.lbl>b` 규칙은 사본에 안 걸린다 — 직계가 아니다).
   ★ 셀색 판(cell-box)은 본체에 여백이 있다. 사본에도 같은 여백을 줘야
     글자가 겹친다 — 안 주면 빛이 글자에서 비켜난다.
   ★ **옅기는 이 정도로 굳힌다**(2026-09-18 확인: "옅기의 정도는 지금 정도면
     됩니다"). 띠를 넓게 잡고(전체의 16%%) 옅게 둔다 — 좁고 진하면 같은
     밝기라도 번쩍이는 획으로 보인다. */
.lbl>.shn{position:absolute;inset:0;pointer-events:none;opacity:0;
  color:transparent;
  -webkit-background-clip:text;background-clip:text;
  background-repeat:no-repeat;background-size:260%% 100%%;
  background-position:-80%% 0;
  background-image:linear-gradient(100deg,
    rgba(255,255,255,0) 42%%, rgba(255,255,255,.85) 50%%,
    rgba(255,255,255,0) 58%%)}
.lbl.cell-box>.shn{padding:13px 17px}
.lbl>.shn>b{display:block;font-weight:700;font-size:43px;line-height:1.25;
  letter-spacing:-.02em;color:transparent}
.lbl>.shn>span{display:block;margin-top:.35em;font-weight:500;font-size:28px;
  line-height:1.42;letter-spacing:-.01em;color:transparent}
.lbl>.shn>b,.lbl>.shn>span{white-space:pre-wrap;word-break:keep-all}
""" % {"W": W, "H": H}

HEAD = """<!doctype html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=%(W)d, height=%(H)d">
<title>%(title)s</title>
<script src="./vendor/gsap.min.js"></script>
<style>
@font-face{font-family:"Pretendard";src:url("./assets/fonts/Pretendard-Regular.woff2") format("woff2");font-weight:400;font-display:block}
@font-face{font-family:"Pretendard";src:url("./assets/fonts/Pretendard-SemiBold.woff2") format("woff2");font-weight:600;font-display:block}
@font-face{font-family:"Pretendard";src:url("./assets/fonts/Pretendard-Bold.woff2") format("woff2");font-weight:700;font-display:block}
/* OS 폴백 — 내려받을 파일이 없으므로 선언만 한다. 선언이 없으면
   lint 의 font_family_without_font_face 로 막힌다. */
@font-face{font-family:"Malgun Gothic";src:local("Malgun Gothic")}
%(css)s</style></head><body>
"""


def _sec(v: Any, dflt: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return dflt


def plan(deck: Dict[str, Any]) -> List[Dict[str, Any]]:
    # ★ **여기서 라벨 시각을 박는다**(2026-09-18에 잡은 구멍).
    #   `stamp_label_times` 는 `render/slides.py` 의 덱 렌더에서만 불리고 있었다.
    #   영상은 그 길을 안 지나므로 `at` 이 계속 비어 있었고, 아래 `_scene_labels`
    #   의 받침값 `i * 1.2` 가 대신 들어갔다 — **69초짜리 장의 라벨 여섯 개가
    #   앞 6초에 다 떠버렸다**(실측 3장). 지시("말하는 순간 등장")와 정반대다.
    #   `say_i` 는 지시문을 쓸 때부터 원장에 있었다. 없던 것은 그것을 **초로
    #   바꾸는 한 줄**뿐이었다.
    # ★ 조립(s8) 이 아니라 **그릴 때** 박는 이유: 큐 시각이 음성 길이에서 나온다.
    #   음성을 다시 합성하면 길이가 달라지므로 덱에 굳혀 두면 어긋난다.
    # ★ 임포트를 함수 안에 둔다 — `render.slides` 는 무거운 모듈이고, 이 파일을
    #   상수만 보려고 읽는 자리(`s12h_hyper` 의 import)가 있다.
    from render.slides import cue_map, stamp_label_times
    stamp_label_times(deck.get("slides") or [], cue_map(deck))
    return _plan(deck)


def _plan(deck: Dict[str, Any]) -> List[Dict[str, Any]]:
    """장마다 시작·길이·라벨 시각을 정한다. **시간 계산은 여기 한 곳뿐이다.**

    길이는 그 장 오디오 길이 + 숨. 오디오가 없으면 라벨 수로 가늠한다
    (라벨 하나에 10초 — s3a 의 SEC_PER_LABEL 과 같은 어림이다).
    """
    out: List[Dict[str, Any]] = []
    t = 0.0
    for s in deck.get("slides") or []:
        if s.get("drop"):
            continue
        au = _sec((s.get("audio") or {}).get("sec"))
        lbs = [l for l in (s.get("labels") or []) if (l.get("head") or "").strip()]
        dur = au + TAIL_SEC if au > 0 else max(4.0, 10.0 * max(1, len(lbs)))
        out.append({
            "no": int(s.get("no") or 0),
            "title": s.get("title") or "",
            "image": s.get("image") or "",
            "audio": (s.get("audio") or {}).get("file") or "",
            "audio_sec": au,
            "start": round(t, 3),
            "dur": round(dur, 3),
            # 라벨 시각은 **장 시작 기준**이다. 절대 시각은 타임라인에서 더한다.
            "labels": [{
                "head": l.get("head") or "",
                "sub": l.get("sub") or "",
                "x": _sec(l.get("x"), 4.0),
                "y": _sec(l.get("y"), 14.0),
                "w": _sec(l.get("w"), 23.0),
                # at 이 없으면 순서대로 벌려 놓는다 — 다 같이 뜨는 것보다 낫다
                "at": _sec(l.get("at"), i * 1.2),
                # 빛이 멎는 때 = **다음 라벨이 뜨는 때**(마지막은 장 끝).
                # 없으면 빛을 안 준다 — 끝을 모르면 장 끝까지 번쩍이게 된다.
                "until": l.get("until"),
                # 셀색 갈래 — 없음/"line"=윤곽(기본) · False=끔 · "box"/True=판.
                # **값을 그대로 넘긴다** — 읽는 규칙은 `_cell_cls` 한 곳에 둔다
                "cell": l.get("cell"),
            } for i, l in enumerate(lbs)],
        })
        t += dur
    return out


def _cell_cls(l: Dict[str, Any]) -> str:
    """셀색 갈래 클래스. `render/slides.py` · `static/js/labels.js` 와 **같은 규칙**.

        없음 / "line" → 윤곽(기본)      False → 끔      "box" / True → 판
    """
    v = (l or {}).get("cell")
    if v is False:
        return ""
    if v is True or v == "box":
        return " cell-box"
    return " cell-line"


def _body(scenes: List[Dict[str, Any]], total: float) -> str:
    p: List[str] = []
    p.append(f'<div id="root" data-composition-id="main" data-start="0" '
             f'data-width="{W}" data-height="{H}" data-duration="{total:.3f}" '
             f'data-fps="{FPS}">')
    for sc in scenes:
        sid = f"sc{sc['no']:03d}"
        p.append(f'<section id="{sid}" class="clip" data-start="{sc["start"]:.3f}" '
                 f'data-duration="{sc["dur"]:.3f}">')
        if sc["image"]:
            p.append(f'<img src="./img/{sc["no"]:03d}.png" alt="">')
        if sc["title"]:
            p.append(f'<h2 class="ttl">{esc(sc["title"])}</h2>')
        for i, l in enumerate(sc["labels"]):
            sub = f'<span>{esc(l["sub"])}</span>' if l["sub"].strip() else ""
            # 빛 띠 — 글자 **위**에 얹고 screen 으로 섞는다. 바탕(아이보리)은
            # 그대로 두고 어두운 글자만 밝힌다. 밑에 깔면 셀색 판에 가린다.
            p.append(f'<div class="lbl{_cell_cls(l)}" data-i="{i}" '
                     f'style="--lx:{l["x"]}%;--ly:{l["y"]}%;--lw:{l["w"]}%">'
                     f'<b>{esc(l["head"])}</b>{sub}'
                     f'<i class="shn" aria-hidden="true">'
                     f'<b>{esc(l["head"])}</b>{sub}</i></div>')
        p.append("</section>")

    # ★ 내레이션. id 가 없으면 lint media_missing_id 이고 **오디오가 조용히 빠진다.**
    #   data-duration 은 **오디오 자체 길이**다(장 길이가 아니다) — 숨 구간까지
    #   오디오 슬롯으로 잡으면 나중에 더킹 구간 계산이 어긋난다.
    for sc in scenes:
        if sc["audio"] and sc["audio_sec"] > 0:
            p.append(f'<audio id="vo{sc["no"]:03d}" src="./audio/{sc["no"]:03d}.wav" '
                     f'data-audio-group="voiceover" data-start="{sc["start"]:.3f}" '
                     f'data-duration="{sc["audio_sec"]:.3f}" data-volume="1"></audio>')
    p.append("</div>")
    return "\n".join(p)


def _timeline(scenes: List[Dict[str, Any]]) -> str:
    """GSAP 타임라인. **라벨마다 제 시각에** 뜨고, 뜬 뒤로 빛이 왕복한다.

    ★ 이것이 예전 모션과 갈리는 자리다. 예전에는 상자에 시각이 비어 있으면
      0.4초 간격으로 위에서 아래로 몰아 띄웠다 — "40초짜리 장의 글이 앞
      2.4초에 다 뜬다". 지금은 LLM 이 정한 `label_says`(몇 번째 문장에서
      말하는가)가 실측 큐 시각으로 바뀌어 여기 들어온다.
    ★ **그 주석이 오래 거짓말이었다**(2026-09-18에 잡음). `stamp_label_times`
      가 이 길에서 안 불려 `at` 이 비어 있었고, 받침값 `i * 1.2` 가 들어가
      똑같이 앞에서 몰아 떴다. 이제 `plan()` 이 박는다.
    ★ 빛은 **뜬 순간부터 다음 라벨이 뜰 때까지** 그 라벨 위로만 간다
      (`tools/motion/remaster.py`: "그 상자에만 빛이 왕복한다").
    """
    L = ["const tl = gsap.timeline({ paused: true });"]
    for sc in scenes:
        sid = "sc%03d" % sc["no"]
        L.append('tl.from("#%s .ttl", { y: %s, autoAlpha: 0, duration: %s, '
                 'ease: "power3.out" }, %.3f);'
                 % (sid, TITLE_RISE, TITLE_DUR, sc["start"]))
        for i, l in enumerate(sc["labels"]):
            sel = "#%s .lbl[data-i='%d']" % (sid, i)
            # 장 안 시각 → 절대 시각. 장 끝을 넘지 않게 눌러 둔다
            at = min(_sec(l["at"]), max(0.0, sc["dur"] - LBL_DUR))
            a0 = sc["start"] + at
            L.append('tl.from("%s", { y: %s, autoAlpha: 0, duration: %s, '
                     'ease: "power3.out" }, %.3f);' % (sel, LBL_RISE, LBL_DUR, a0))

            # ── 빛 ────────────────────────────────────────────────────────
            # 끝을 모르면(until 없음) 안 준다 — 장 끝까지 번쩍이게 된다.
            end = l.get("until")
            if end is None:
                continue
            span = min(_sec(end), sc["dur"]) - at
            # 한 번도 못 지나갈 만큼 짧으면 건너뛴다. 뜨자마자 꺼지면 깜빡임이다
            if span < SHEEN_DUR + SHEEN_FADE * 2:
                continue
            # (reps+1)번 지나가고 사이마다 쉰다 — 총합이 span 을 안 넘게
            body = span - SHEEN_FADE * 2
            reps = max(0, int((body - SHEEN_DUR) // (SHEEN_DUR + SHEEN_GAP)))
            L.append('tl.to("%s>.shn", { opacity: 1, duration: %s }, %.3f);'
                     % (sel, SHEEN_FADE, a0))
            # ★ 글자에 물린 띠는 **배경을 밀어야** 움직인다 — 요소를 옮기면
            #   글자 사본이 같이 움직여 본체에서 어긋난다.
            #   `background-size:260%%` 라 -80%%~180%% 가 왼쪽 밖에서 오른쪽
            #   밖까지다(퍼센트 위치는 그릇−그림에 비례한다).
            L.append('tl.fromTo("%s>.shn", { backgroundPosition: "-80%% 0" }, '
                     '{ backgroundPosition: "180%% 0", duration: %s, '
                     'ease: "sine.inOut", repeat: %d, repeatDelay: %s, '
                     'yoyo: true }, %.3f);'
                     % (sel, SHEEN_DUR, reps, SHEEN_GAP, a0 + SHEEN_FADE))
            L.append('tl.to("%s>.shn", { opacity: 0, duration: %s }, %.3f);'
                     % (sel, SHEEN_FADE, a0 + span - SHEEN_FADE))
    L.append('window.__timelines["main"] = tl;')
    return "\n".join(L)

def build(deck: Dict[str, Any], *, proj_dir: Path, out_dir: Path,
          title: str = "") -> Dict[str, Any]:
    """컴포지션 폴더를 만든다. 돌려주는 값은 사람이 읽을 요약."""
    scenes = plan(deck)
    total = round(sum(s["dur"] for s in scenes), 3)

    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("img", "audio", "vendor", "assets/fonts"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    # 자산 복사 — 컴포지션은 **자기완결**이어야 한다. 렌더 중 바깥을 읽지 않는다.
    if not GSAP.is_file():
        raise FileNotFoundError(f"gsap 이 없습니다: {GSAP}")
    shutil.copy2(GSAP, out_dir / "vendor" / "gsap.min.js")
    for f in FONT_DIR.glob("Pretendard-*.woff2"):
        shutil.copy2(f, out_dir / "assets" / "fonts" / f.name)
    lic = FONT_DIR / "LICENSE-Pretendard.txt"
    if lic.is_file():                      # SIL OFL — 재배포 시 동봉해야 한다
        shutil.copy2(lic, out_dir / "assets" / "fonts" / lic.name)

    missing: List[str] = []
    for sc in scenes:
        if sc["image"]:
            src = proj_dir / sc["image"]
            if src.is_file():
                shutil.copy2(src, out_dir / "img" / f"{sc['no']:03d}.png")
            else:
                missing.append(f"{sc['no']}번 그림")
        if sc["audio"]:
            src = proj_dir / sc["audio"]
            if src.is_file():
                shutil.copy2(src, out_dir / "audio" / f"{sc['no']:03d}.wav")
            else:
                missing.append(f"{sc['no']}번 소리")

    html = (HEAD % {"W": W, "H": H, "title": esc(title or "덱"), "css": CSS}
            + _body(scenes, total)
            + "\n<script>\n" + _timeline(scenes) + "\n</script>\n</body></html>\n")
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    return {"dir": str(out_dir), "scenes": len(scenes), "sec": total,
            "labels": sum(len(s["labels"]) for s in scenes),
            "missing": missing}
