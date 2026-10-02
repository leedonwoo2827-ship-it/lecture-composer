#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""픽셀 일 — **비전이 대충 집은 자리를 잉크의 실제 가장자리로 조인다.**

    python zone_cv.py scenes  <mp4> -o scenes.json
    python zone_cv.py tighten <일감.json> -o 결과.json
    python zone_cv.py grid    <스틸.png> -o 격자.png

★ **왜 앱이 아니라 여기인가.** 앱은 `.venv-app` 으로 도는데 거기엔 numpy·Pillow 가
  없다(넣을 이유도 없다 — 앱은 픽셀을 안 만진다). `make_picker.py` 가 이미 PATH 의
  파이썬으로 따로 도는 구조라 **같은 자리**에 둔다. 두 세계의 접점은 JSON 파일
  하나다 — 코드로 이어 붙이지 않는다.

★ **비전이 픽셀을 정확히 찍을 거라 기대하지 않는다.** 실측(2026-09-14, 견본
  158개)으로 정한 분담이다.

      흐트러뜨린 정도   그냥 조이기        골짜기 쪼개기까지
      +25%             IoU 0.638 · 78%    IoU 0.684 · 88%
      +50%             IoU 0.443 · 27%    IoU 0.524 · 45%

  ±25% 안으로만 집어 주면 나머지는 여기서 끝난다. 그 이상 벗어나면 옆 라벨을
  삼키기 시작한다 — 그래서 여유(`margin`)를 넉넉히 주지 않는다.

★ **`make_picker.propose` 를 대신하는 물건이 아니다.** 저쪽은 「글자가 어디 있나」를
  혼자 알아내려 했고 그래서 못 했다 — 실측하면 그림에 구워진 라벨 130개 중 4개를
  잡는다. 여기는 **어디인지 이미 들은 뒤**에 가장자리만 잰다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent


_mods: Dict[str, Any] = {}


def _mod(name: str):
    """옆 파일을 모듈로 불러온다 — `make_picker` 가 `remaster` 를 부르는 방식 그대로.

    ★ 한 번만 읽는다. `tighten` 이 상자마다 부르는데, 그때마다 다시 읽으면
      `remaster` 까지 딸려 와 수백 번 로드된다.
    """
    if name not in _mods:
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _mods[name] = m
    return _mods[name]


# ── 잉크 ───────────────────────────────────────────────────────────────────
def ink_mask(arr: np.ndarray, x0: int, y0: int, x1: int, y1: int,
             pad: int = 14) -> np.ndarray:
    """그 자리의 **잉크**를 고른다 — 「어두움」이 아니라 「바탕과의 차이」로.

    ★ `remaster.zone_build` 가 쓰는 식을 **그대로** 가져왔다. 뒤에 효과를 거는
      쪽과 「무엇이 잉크인가」가 어긋나면, 여기서 딱 맞게 조인 상자가 저기서는
      반쯤 빈 상자가 된다.
    ★ 바탕은 **최빈값**이다. 중앙값을 쓰면 굵은 제목에서 값이 글자색에 얹혀 알파가
      뒤집힌다 — 배경이 글자로 잡히고 글자가 배경이 된다.
    ★ 최빈값은 상자 **둘레 14px 까지 넓혀** 잰다. 상자가 글자에 꽉 차 있으면
      상자 안의 최빈값이 글자색이 되어 버린다.
    ★ 어두운 글자만 보지 않는다는 것도 중요하다. 밝은 바탕 위 옅은 설명 줄도,
      짙은 판 위 흰 글자도 같은 식으로 잡힌다.
    """
    H, W = arr.shape[:2]
    px0, py0 = max(0, x0 - pad), max(0, y0 - pad)
    px1, py1 = min(W, x1 + pad), min(H, y1 + pad)
    p = arr[py0:py1, px0:px1].astype(np.float32)
    pl = p[:, :, 0] * .299 + p[:, :, 1] * .587 + p[:, :, 2] * .114
    hist, edge = np.histogram(pl, bins=32, range=(0, 255))
    k = int(np.argmax(hist))
    bg = float((edge[k] + edge[k + 1]) / 2)

    r = arr[y0:y1, x0:x1].astype(np.float32)
    luma = r[:, :, 0] * .299 + r[:, :, 1] * .587 + r[:, :, 2] * .114
    a = np.clip(np.abs(luma - bg) / 55.0, 0, 1)
    a[a < 0.14] = 0.0
    return a


def looks_glyph(arr: np.ndarray, box: Dict[str, Any]) -> bool:
    """이 상자 안이 **글자**인가, 그림인가.

    ★ `make_picker.looks_text` 를 못 쓰는 이유가 실측으로 드러났다(씬27).
      저쪽은 **어두운 글자만** 본다(`luma < bg*0.72`). 그래서

        「기술」 「제도」 「경험」  짙은 받침대 위 **흰 글자** → 잉크 0 → 탈락
        빈 받침대                 바깥 크림색과 견주니 어둡다  → 통과

      글자를 버리고 그림을 들이는 정반대 판정이 났다. 여기서는 `ink_mask` 의
      **바탕과의 차이**를 쓴다 — 검은 글자든 흰 글자든 같게 잡힌다.

    가르는 것 둘.
      얼마나 차 있나   글자는 성기다. 텅 비었거나(아무것도 없다) 꽉 찼으면
                       (받침대·판때기) 글자가 아니다.
      몇 번 끊기나     글자는 가로로 훑으면 획과 여백이 **여러 번** 갈마든다.
                       면으로 된 그림은 한 줄로 쭉 이어져 끊김이 거의 없다.

    ★ 문턱은 실측으로 잡았다(2026-09-14, 실제로 놓인 상자 291개를 사람이 그린
      것과 견줘 글자 253개 · 그림 38개로 가른 뒤).

          끊김 밀도   글자 하위5% = 20.3   그림 중앙값 = 17.8
          차 있는 정도 글자 하위5% = 0.247  그림 하위5% = 0.173

      그런데 실제로 돌려 보니 이 검문이 **진짜 라벨을 자꾸 떨어뜨렸다.**
      「흔적의 기록」이 같은 높이의 화살표까지 물어 참 0.198·끊김 18.9 로
      간발에 미달했고, 「제도 → 경험」처럼 **화살표가 라벨 글자 안에 들어 있는**
      것들이 통째로 사라졌다. 그래서 크게 풀었다 — **참 0.05~0.62 · 끊김 9.**
      이제 이 검문은 「받침대·판때기처럼 통째로 메워진 면」만 걷어 낸다.
      그래도 괜찮은 이유는 **애초에 원장이 이름을 댄 라벨 자리만 들여다보기
      때문**이다. 그림에는 물어볼 이름이 없어 후보로 들어오지도 않는다.
      더 조이면 그림을 더 거르지만 글자도 같이 잃는다 — 놓치는 쪽이 더 나쁘다
      (사람이 마지막에 늘려 보므로, 없는 상자보다 넘치는 상자가 낫다).
    """
    H, W = arr.shape[:2]
    x0 = max(0, int(box["x"])); y0 = max(0, int(box["y"]))
    x1 = min(W, x0 + int(box["w"])); y1 = min(H, y0 + int(box["h"]))
    if x1 - x0 < 12 or y1 - y0 < 8:
        return False
    a = ink_mask(arr, x0, y0, x1, y1) > 0
    fill = float(a.mean())
    if fill < 0.05 or fill > 0.62:
        return False
    rows = a[a.any(axis=1)]
    if not len(rows):
        return False
    # 줄마다 「잉크가 시작되는 횟수」를 세어 평균 낸다
    starts = (rows[:, 1:] & ~rows[:, :-1]).sum(axis=1) + rows[:, 0]
    rpk = float(starts.mean()) / max(0.001, (x1 - x0) / 1000.0)
    return rpk >= 9.0


def _runs(flags: np.ndarray, gap: int) -> List[Tuple[int, int]]:
    """켜진 자리를 묶음으로 — `gap` 보다 넓게 끊기면 딴 묶음."""
    idx = np.where(flags)[0]
    if not len(idx):
        return []
    out, s = [], int(idx[0])
    for a, b in zip(idx, idx[1:]):
        if b - a > gap:
            out.append((s, int(a)))
            s = int(b)
    out.append((s, int(idx[-1])))
    return out


def _union(bs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not bs:
        return None
    x0 = min(b["x"] for b in bs)
    y0 = min(b["y"] for b in bs)
    x1 = max(b["x"] + b["w"] for b in bs)
    y1 = max(b["y"] + b["h"] for b in bs)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def split_head_body(lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """줄 묶음을 **굵은 소제목**과 **그 아래 설명**으로 가른다.

    ★ 프롬프트가 「설명은 소제목의 65%」로 못 박아 두었다
      (`s3a_imgprompt.compose`). 그래서 가장 높은 줄이 소제목이고, 그 아래로
      0.8배 이하인 것들이 설명이다. 견본도 그 꼴이다 — 씬3 의 「흔적의 기록」은
      머리 h=64, 몸통 h=49.
    """
    if not lines:
        return {"head": None, "body": None}
    tall = max(lines, key=lambda ln: ln["h"])
    hi = lines.index(tall)
    body = [ln for ln in lines[hi + 1:] if ln["h"] <= tall["h"] * 0.8]
    return {"head": tall, "body": _union(body)}


def _grow(arr: np.ndarray, cl: int, cr: int, ry0: int, ry1: int,
          *, gap: int = 16, cap: int = 200) -> Tuple[int, int]:
    """줄의 양 끝을 **띄어쓰기가 나올 때까지** 밖으로 늘린다.

    찾는 범위의 경계가 글자 위에 떨어지면 낱말이 잘린다. 잘렸는지는 경계에
    잉크가 붙어 있는지로 안다. 붙어 있으면 `gap` 픽셀이 비는 자리가 나올 때까지
    따라가고, `cap` 을 넘어서까지는 안 간다(옆 라벨로 넘어가지 않게).
    """
    H, W = arr.shape[:2]
    ry0, ry1 = max(0, ry0), min(H, ry1 + 1)
    wx0, wx1 = max(0, cl - cap), min(W, cr + cap + 1)
    if ry1 - ry0 < 4 or wx1 - wx0 < 4:
        return cl, cr
    lit = ink_mask(arr, wx0, ry0, wx1, ry1).mean(axis=0) > 0.003
    n = len(lit)
    i = cl - wx0
    while i > 0:
        run = lit[max(0, i - gap):i]
        if not run.any():
            break
        i = max(0, i - gap) + int(np.where(run)[0][0])
        i -= 1
    j = cr - wx0
    while j < n - 1:
        run = lit[j + 1:min(n, j + 1 + gap)]
        if not run.any():
            break
        j = j + 1 + int(np.where(run)[0][-1])
    return wx0 + max(0, i), wx0 + min(n - 1, j)


def tighten(arr: np.ndarray, box: Dict[str, Any], *, margin: int = 24,
            row_gap: int = 6, pad: int = 7, my: int = 14,
            hm: int = 60, fit: str = "rows") -> Dict[str, Any]:
    """라벨 하나의 대충 자리를 받아 **줄마다 하나씩** 조인 상자를 내놓는다.

    ★ 내놓는 단위는 **라벨별로 묶고, 그 안에서 줄별로**다(2026-09-14 확정).
      한 라벨의 줄들은 같은 시각에 함께 뜨고(그 라벨의 `say_i`), 상자는 줄마다
      따로 선다. 화살표가 줄 사이에 끼어도 신경 쓰지 않는다 — 마지막 손질은
      사람이 지정기에서 한다.

    돌려주는 것
      lines  줄마다 조인 상자 (위→아래, 왼→오른쪽) ← **이것이 결과다**
      all    전부 합친 상자 (검문·보고용)
      head   가장 높은 줄 (굵은 소제목)
      body   그 아래 작은 줄들을 합친 것

    ★ `pad` 는 **글자에 딱 붙이지 않기 위한 여백**이다. 잉크의 바깥 가장자리에
      정확히 맞추면 획 끝의 반투명한 부분(안티앨리어싱)이 상자 밖에 남아,
      `remaster` 가 글자를 지울 때 테두리가 유령처럼 남는다. 사람이 그린 견본도
      위아래로 6~8px 씩 여유를 두고 있다 — 그 값을 따른다.

    ★ **가로로는 끊지 않는다.** 한때 화살표를 떼어 내려고 끊어 봤는데, 글자
      사이 띄어쓰기에서도 끊겨 **낱말 가운데를 자른 상자**가 나왔다
      (「일을 이어서 한다는 건」, 「챗봇이 어|이전트로」). 한 줄은 **온전한 네모
      하나**여야 한다 — 줄을 걸친 ㄱ·ㄴ 모양은 안 된다(2026-09-14).
      화살표는 아래 검문이 걸러 내고, 남는 것은 사람이 지정기에서 손본다.
    """
    # ★ **찾는 범위를 비전이 준 자리 언저리로 묶는다.**
    #
    #   여기서 세 번 헛디뎠고 그 자국을 남겨 둔다.
    #     1. 범위를 비전 자리 폭으로 딱 맞췄더니 — 줄이 그 경계에서 끊겨
    #        「AI가 낸 점|수와 근거를」처럼 **낱말 가운데가 잘렸다.**
    #     2. 가로로 넓게 찾았더니 — 나란히 선 옆 라벨과 **한 줄로 붙었다.**
    #     3. 가로 폭을 비전 것으로 고정했더니 — 짧은 굵은 소제목에 넓은 상자가
    #        씌워져 「차 있는 정도」가 낮아 **검문에서 떨어졌다.**
    #   답은 가운데다. 가로는 잉크로 찾되 **비전 자리 ±`hm`** 밖으로는 안 나간다.
    #   비전의 오차가 가로 40px 안쪽이므로 그만큼만 여유를 준다.
    #   세로는 좁게 둔다 — 넓히면 위아래 딴 줄을 주워 온다.
    H, W = arr.shape[:2]
    x0 = max(0, int(box["x"]) - hm)
    x1 = min(W, int(box["x"]) + int(box["w"]) + hm)
    y0 = max(0, int(box["y"]) - my)
    y1 = min(H, int(box["y"]) + int(box["h"]) + my)
    if x1 - x0 < 12 or y1 - y0 < 8:
        return {"lines": [], "all": None, "head": None, "body": None}

    a = ink_mask(arr, x0, y0, x1, y1)
    lines: List[Dict[str, Any]] = []
    # 줄 사이 골짜기에서 쪼갠다 — 견본의 씬3 은 소제목과 설명 사이 틈이 0px 이었다
    for ra, rb in _runs(a.mean(axis=1) > 0.004, row_gap):
        if rb - ra < 6:
            continue
        band = a[ra:rb + 1]
        lit = band.mean(axis=0) > 0.003
        # ★ **가로로도 끊되, 낱말 사이는 절대 끊지 않는다.**
        #   같은 높이에 화살표가 앉는 장이 많다. 안 끊으면 「흔적의 기록」(236px)
        #   이 화살표까지 물어 595px 이 되고, 그러면 상자 안이 헐거워져 아래
        #   검문에서 **글자가 아닌 것으로 떨어진다**(실측: 참 0.198 · 끊김 18.9).
        #   실제 간격은 이렇게 갈린다 —
        #       낱말 사이        12~20px
        #       글자와 화살표 사이  275px
        #   그 한참 사이에 문턱을 둔다. 한때 줄 높이에 맞춰 26~44px 로 끊었더니
        #   띄어쓰기에서도 갈라져 **낱말 가운데가 잘렸다**. 그래서 넉넉히 잡는다.
        for ca, cb in _runs(lit, max(70, int((rb - ra) * 1.4))):
            seg = band[:, ca:cb + 1]
            rs = np.where(seg.mean(axis=1) > 0.004)[0]
            if not len(rs):
                continue
            # 찾는 범위 경계에 글자가 걸쳤으면 띄어쓰기가 나올 때까지 늘린다
            cl, cr = _grow(arr, x0 + ca, x0 + cb, y0 + ra, y0 + rb)
            by = max(0, y0 + ra + int(rs[0]) - pad)
            bh = min(H - by, int(rs[-1] - rs[0]) + 1 + pad * 2)
            bx = max(0, cl - pad)
            bw = min(W - bx, cr - cl + 1 + pad * 2)
            if bw < 10 or bh < 8:
                continue
            lines.append({"x": bx, "y": by, "w": bw, "h": bh})
    lines.sort(key=lambda b: b["y"])
    inside, outside = lines, []

    # ★ **비전이 말한 자리를 믿는다.** 여유(`margin`)는 글자가 그 자리를 조금
    #   넘칠 때를 위한 것이지 딴 라벨을 주워 오라는 것이 아니다. 그래서 원래
    #   자리에 **닿는** 조각만 남기고, 여유 띠에만 앉은 조각은 버린다.
    #   경계를 그렇게 그으면 규칙이 하나로 끝나고, 문턱을 더 둘 필요가 없다.
    inside = [b for b in lines
              if (min(b["x"] + b["w"], box["x"] + box["w"]) - max(b["x"], box["x"])) > 0
              and (min(b["y"] + b["h"], box["y"] + box["h"]) - max(b["y"], box["y"])) > 0]
    outside = [b for b in lines if b not in inside]

    # ★ **텍스트만 남긴다.** 라벨의 대충 자리 안이라도 화살표·아이콘·그림 조각이
    #   섞여 든다. `make_picker.looks_text` 가 아니라 `looks_glyph` 를 쓴다 —
    #   저쪽은 어두운 글자만 봐서 짙은 판 위 흰 글자를 버린다(위 주석).
    glyph = [b for b in inside if looks_glyph(arr, b)]
    notglyph = [b for b in inside if b not in glyph]
    whole = _union(glyph)
    return {"lines": glyph, "outside": outside, "notglyph": notglyph,
            "all": whole, "ok": bool(whole), **split_head_body(glyph)}


# ── 격자 ───────────────────────────────────────────────────────────────────
_FONTS = ("C:/Windows/Fonts/arial.ttf",
          "C:/Windows/Fonts/malgun.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

# 긴 변을 이만큼으로. API 가 1568px 에서 다시 줄이므로 **그 앞에서** 그려야
# 격자선이 또렷하게 남는다.
GRID_W = 1456


def _font() -> Optional[str]:
    """ffmpeg 의 drawtext 가 쓸 **파일로 된** 글꼴.

    ★ `render/fonts.py` 는 못 쓴다 — 거긴 HTML 용 woff2 를 base64 로 뱉는다.
      libfreetype 은 디스크의 ttf 가 필요하다. 눈금은 숫자뿐이라 아무 글꼴이나 된다.
    """
    return next((f for f in _FONTS if Path(f).is_file()), None)


def grid(src: Path, out: Path) -> Path:
    """스틸에 **백분율 격자**를 얹는다.

    비전에게 좌표를 물으려면 셀 자가 있어야 한다. 10%마다 굵은 선, 5%마다 옅은
    선을 긋고 가장자리에 눈금 숫자를 적는다. 글꼴을 못 찾으면 선만 긋는다 —
    숫자가 없어도 「굵은 선이 10%」라고 말로 일러 주면 셀 수 있다.
    """
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg 를 찾지 못했습니다")
    vf = [f"scale={GRID_W}:-2",
          "drawgrid=w=iw/20:h=ih/20:t=1:c=0x3A6EA5@0.18",
          "drawgrid=w=iw/10:h=ih/10:t=2:c=0xE03030@0.42"]
    fp = _font()
    if fp:
        esc = fp.replace(":", "\\:")
        common = ("fontsize=19:fontcolor=0xC01010:box=1:"
                  "boxcolor=white@0.72:boxborderw=2")
        for k in range(1, 10):
            n = k * 10
            # ★ drawtext 안에서는 `w`/`h` 가 **입력 영상**의 크기다. `iw`/`ih` 는
            #   여기서 정의되지 않아 「Undefined constant」 로 죽는다.
            vf.append(f"drawtext=fontfile='{esc}':text='{n}':"
                      f"x=w*0.{k}+3:y=2:{common}")
            vf.append(f"drawtext=fontfile='{esc}':text='{n}':"
                      f"x=2:y=h*0.{k}+3:{common}")
    r = subprocess.run([ff, "-v", "error", "-y", "-i", str(src),
                        "-vf", ",".join(vf), "-frames:v", "1", str(out)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"격자를 못 그렸습니다: {(r.stderr or '')[:200]}")
    return out


# ── 명령 ───────────────────────────────────────────────────────────────────
def cmd_scenes(mp4: Path, out: Path) -> None:
    """씬 전환 시각과 스틸 — **`make_picker` 와 같은 함수를 쓴다.**

    씬 번호가 한 칸만 어긋나도 상자가 통째로 엉뚱한 장에 붙는다. 그래서 새로
    찾지 않고 그쪽 함수를 불러 쓴다.
    """
    mkp = _mod("make_picker")
    rm = _mod("remaster")
    meta, cuts, times = mkp.scenes(mp4)
    tmp = mp4.parent / f"_{mp4.stem}-stills"
    tmp.mkdir(exist_ok=True)
    ends = cuts[1:] + [meta["sec"]]
    scenes = []
    for i, t in enumerate(times):
        p = tmp / f"s{i:02d}.png"
        if not p.exists():
            subprocess.run([rm.FFMPEG, "-v", "error", "-ss", f"{t:.2f}",
                            "-i", str(mp4), "-frames:v", "1", str(p), "-y"],
                           check=True)
        scenes.append({"i": i, "cut": round(cuts[i], 2), "still": str(p),
                       "len": round(ends[i] - cuts[i], 2)})
    out.write_text(json.dumps({"video": mp4.name, "W": meta["w"], "H": meta["h"],
                               "stills": str(tmp), "scenes": scenes},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(scenes)}장")


def cmd_tighten(job: Path, out: Path) -> None:
    """일감을 받아 한꺼번에 조인다.

    들어오는 것: `{"items": [{"id", "still", "box": {x,y,w,h}, "margin"?}]}`
    나가는 것:   `{"items": [{"id", "lines", "all", "head", "body", "ok"}]}`

    ★ `ok` 는 `make_picker.looks_text` 의 검문 결과다 — 글자가 아니라 그림에
      앉았으면 False. **그럴 때도 상자는 돌려준다**(사람이 눈으로 볼 수 있게)
      다만 표시를 달아 보고에 올린다. 필터를 상자 **고르는** 자리에서 빼고
      **검문** 자리에만 남긴 것이 이번 변경의 요점이다.
    """
    mkp = _mod("make_picker")
    spec = json.loads(job.read_text(encoding="utf-8-sig"))
    cache: Dict[str, np.ndarray] = {}
    res = []
    for it in spec.get("items") or []:
        sp = str(it["still"])
        if sp not in cache:
            cache[sp] = np.asarray(Image.open(sp).convert("RGB"))
        arr = cache[sp]
        hm = 8 if it.get("fit") == "both" else 60
        t = tighten(arr, it["box"], hm=hm)
        ok = bool(t["all"]) and mkp.looks_text(arr, t["all"])
        res.append({"id": it.get("id"), **t, "ok": ok})
    out.write_text(json.dumps({"items": res}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"{len(res)}개 조임")


def main() -> None:
    ap = argparse.ArgumentParser(description="모션 상자의 픽셀 일")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("scenes", help="씬 전환 시각과 스틸")
    a.add_argument("mp4", type=Path)
    a.add_argument("-o", "--out", type=Path, required=True)
    b = sub.add_parser("tighten", help="대충 자리를 잉크 가장자리로 조인다")
    b.add_argument("job", type=Path)
    b.add_argument("-o", "--out", type=Path, required=True)
    c = sub.add_parser("grid", help="백분율 격자를 얹는다")
    c.add_argument("src", type=Path)
    c.add_argument("-o", "--out", type=Path, required=True)
    n = ap.parse_args()
    if n.cmd == "scenes":
        cmd_scenes(n.mp4, n.out)
    elif n.cmd == "tighten":
        cmd_tighten(n.job, n.out)
    else:
        grid(n.src, n.out)


if __name__ == "__main__":
    main()
