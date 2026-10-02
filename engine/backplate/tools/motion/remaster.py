# -*- coding: utf-8 -*-
"""완성 mp4 → **요소가 하나씩 드러나고 화면이 계속 살아 있는** mp4.

    python remaster.py "…/11_완성/19-img.mp4"

원본 앱(`260812-summary-shocase`)은 건드리지 않는다. 원본 mp4 는 **읽기만 한다** —
결과는 언제나 `-motion` 이 붙은 새 파일이다.

**왜 완성본을 다시 굽지 않고 mp4 를 재료로 쓰는가.** 처음부터 다시 만들면 TTS·
브라우저·폰트가 다시 개입해 소리가 달라진다(실제로 그 문제를 겪었다). 여기는
**소리를 아예 손대지 않는다** — 원본 오디오 트랙을 스트림 복사로 옮기고, 새로
만드는 것은 영상 트랙뿐이다. 길이도 원본과 같다.

## 무엇이 움직이나

    1  액자가 훑고 들어온다        좌→오 부드러운 마스크 (0.9초)
    2  그림 속 제목이 천천히 슝     글자를 떼어내 따로 올린다 (0.9초)
    3  그다음은 **완전히 정지**      원본 픽셀 그대로. 아무것도 안 움직인다

★ **정지가 기본이다.** 세밀한 일러스트를 계속 조금씩 확대·이동하면 매 프레임
  다시 그려지면서 가는 선이 스멀거려 **눈이 아프다**(실제로 그렇게 나왔다).
  움직임은 장이 바뀌는 2~3초에만 두고, 나머지는 원본을 그대로 둔다.
  화면을 살리고 싶으면 `--drift 2.5` 로 안착을 켤 수 있다(기본 꺼짐).

★ **제목은 크기가 안 변한다.** 그림만 줄어들고 글자는 원본 크기로 얹혀 있다.
  글자를 같이 줄이면 흐려져서, 정지 화면보다 못해진다.

## 어떻게 "요소" 를 아는가

    1) 화면이 바뀌는 순간   저해상 회색으로 훑어 찾는다
    2) 바뀐 자리의 모양     새로 생긴 픽셀인지, 갈아치우는 것인지
    3) 그림 안의 글자       밝은 바탕 위의 어두운 글자 띠를 떼어낸다

3) 이 핵심이다. 그림으로 갈음한 판(`-img`)은 한 장이 통짜 그림이라 "요소" 가
없어 보이지만, **제목은 밝은 바탕 위에 얹혀 있다.** 그 글자 띠를 떼어내고 그
자리를 같은 줄의 배경색으로 메우면 「글자 없는 그림판」이 생긴다. 그러면 순서가
만들어진다 — 그림이 먼저, 글자가 나중에, 그리고 글자만 따로 계속 움직인다.

돋보기·컵·노트 같은 **그림 요소는 못 뗀다** — 하나의 그림에 겹쳐 그려져 있어
떼어낸 자리에 무엇이 있었는지 알 수가 없다. 그것까지 하려면 그림을 만들 때부터
요소를 나눠 받아야 한다.

필요한 것: ffmpeg / ffprobe (PATH), python 3.10+, numpy, Pillow.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# ── 기본값 — 여기 숫자가 "느낌" 이다 ──────────────────────────────────────
D = dict(
    fps=30,
    rise=22,          # (글 판) 새 줄이 올라오는 거리(px)
    dur=0.42,         # (글 판) 새 줄이 뜨는 시간(초)
    stagger=0.07,     # 같은 순간에 여럿이면 순서를 주는 간격(초)
    wipe_dur=0.90,    # 액자·표가 훑어 드러나는 시간(초)
    wipe_soft=0.25,   # 훑는 경계의 부드러움(폭 비율)
    wipe_dir="lr",    # lr(왼→오) · tb(위→아래)
    frame_in=0,       # 장 첫머리에 액자가 훑고 들어오나. 0=끔(기본) · 1=켬
                      # ★ 껐다. 경계가 부드러워 장 바뀔 때 오른쪽이 흐렸다.
    text_rise=30,     # 그림 속 제목이 올라오는 거리(px)
    text_dur=0.95,    # 그림 속 제목이 뜨는 시간(초) — 천천히
    text_gap=0.30,    # 액자 등장 → 제목, 제목 → 다음 글자 간격(초)
    text_zone=0.42,   # 그림의 위쪽 몇 %까지를 제목 자리로 볼지
    drift=0.0,        # 그림이 **줄어드는** 양(%). ★ 0 이 기본 — 그림은 안 움직인다
    settle=2.5,       # 안착을 쓸 때 그 시간(초). 그 뒤는 완전 정지
    pan=0.0,          # 좌우로 흐르는 양. ★ 0 이 기본 — 그림이 흔들려 보이면 안 된다
    float_px=0.0,     # 제목이 계속 부유하는 거리(px, ±). ★ 0 이 기본
    text_sheen=0.6,   # 빛과 빛 **사이에 쉬는 시간**(초). 0 이면 빛 없음
    text_sheen_dur=1.1,   # 빛이 한 번 지나가는 시간(초)
    #   ↑ 둘을 더한 것이 한 주기다 — 0.6+1.1 = 1.7초마다 한 번 지나간다.
    #     글이 짧아 금방 지나가므로, 쉬는 시간을 길게 두면 죽은 화면이 된다.
    text_sheen_amp=0.45,  # 글자가 밝아지는 정도(0.3~0.6)
    text_sheen_wide=0.16, # 빛 띠의 폭(마스크 폭 대비). 작을수록 또렷한 한 줄기
    art_edge=1.0,     # 그림 윤곽선이 빛을 받는 정도(0.5 은은 · 1.3 또렷)
    sheen=0.0,        # 빛이 **액자 전체**를 훑는 주기(초). 0 이면 없음
    sheen_dur=1.6,    # 빛이 한 번 지나가는 시간(초)
    sheen_amp=0.10,   # 빛의 세기(0.06~0.16). 넘기면 번쩍여서 눈이 아프다
    sheen_wide=0.30,  # 빛 띠의 폭(액자 폭 대비)
    float_sec=7.0,    # 부유 한 주기(초)
    # ★ 씬이 끝날 때 **걷어내기**. 이게 없으면 새 씬이 훑고 들어오는 0.9초 동안
    #   이전 슬라이드가 오른쪽에 그대로 남아 두 장이 겹쳐 보인다("자국이 남는다").
    out_dur=0.45,     # 걷어내는 시간(초). 0 이면 안 걷어낸다
    out_dir="rl",     # 걷어내는 방향 — rl(오→왼) · lr · tb · bt
    sample_fps=20,
    sensitivity=0.0004,
    # ★ **최종 용량은 여기서 정해진다** — 모션이 영상을 통째로 다시 굽기 때문에,
    #   앞단(s12)을 아무리 조여도 최종 mp4 에는 반영되지 않는다. 예전 20 에서는
    #   76.7분짜리가 영상만 401MB 였다(실측 697kbps). 정지 슬라이드를 재료로 삼는
    #   판이라 24 에서 글자·선이 눈에 띄게 무너지지 않는다.
    crf=24,
    preset="veryfast",
)


def sh(args: list[str], timeout: int = 7200) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def need(name: str) -> str:
    p = shutil.which(name)
    if not p:
        sys.exit(f"{name} 을 찾지 못했습니다 — PATH 를 확인하세요")
    return p


FFMPEG, FFPROBE = need("ffmpeg"), need("ffprobe")
QUIET = ["-hide_banner", "-loglevel", "error", "-nostdin", "-y"]


def probe(src: Path) -> dict:
    r = sh([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,r_frame_rate", "-show_entries",
            "format=duration", "-of", "json", str(src)])
    j = json.loads(r.stdout or "{}")
    st = (j.get("streams") or [{}])[0]
    num, den = (st.get("r_frame_rate") or "30/1").split("/")
    audio = bool(sh([FFPROBE, "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                     str(src)]).stdout.strip())
    return {"w": int(st.get("width") or 1920), "h": int(st.get("height") or 1080),
            "fps": (float(num) / float(den or 1)) or 30.0,
            "sec": float((j.get("format") or {}).get("duration") or 0), "audio": audio}


def ease_out(p: float) -> float:
    return 1.0 - (1.0 - max(0.0, min(1.0, p))) ** 3


# ── 1) 화면이 바뀌는 순간 ────────────────────────────────────────────────
def find_events(src: Path, *, sample_fps: int, sens: float,
                limit: float | None, log=print) -> list[float]:
    """저해상 회색 프레임을 훑어 **바뀐 순간**만 남긴다.

    씬 검출(scene)을 쓰지 않는다 — 한 줄이 뜨는 변화는 임계값 밑으로 떨어져
    놓치는 일이 많다. 480×270 회색이면 19분짜리도 1~2분에 훑는다.
    """
    w, h = 480, 270
    cmd = [FFMPEG, "-v", "error", "-nostdin"]
    if limit:
        cmd += ["-t", f"{limit:.3f}"]
    cmd += ["-i", str(src), "-vf",
            f"fps={sample_fps},scale={w}:{h}:flags=bilinear,format=gray",
            "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=w * h * 16)
    n, prev, k, hits = w * h, None, 0, []
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        f = np.frombuffer(b, np.uint8).reshape(h, w).astype(np.int16)
        if prev is not None and float((np.abs(f - prev) > 10).sum()) / n > sens:
            hits.append(round(k / sample_fps, 3))
        prev, k = f, k + 1
    p.stdout.close(); p.wait()
    ev: list[float] = []
    for t in hits:                       # 한 변화가 두 샘플에 걸치면 하나로
        if not ev or t - ev[-1] > 0.15:
            ev.append(t)
    log(f"  변화 {len(ev)}곳 (샘플 {k}프레임)")
    return ev


# ── 2) 정지 화면 ────────────────────────────────────────────────────────
def grab_all(src: Path, times: list[float], out_dir: Path, log=print) -> dict[int, Path]:
    def one(it):
        i, t = it
        p = out_dir / f"s{i:05d}.png"
        r = sh([FFMPEG, *QUIET, "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
                "-frames:v", "1", str(p)], timeout=180)
        return i, (p if (p.is_file() and r.returncode == 0) else None)

    out: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, p in ex.map(one, list(enumerate(times))):
            if p:
                out[i] = p
    log(f"  정지 화면 {len(out)}장")
    return out


# ── 3) 바뀐 자리 자르기 ─────────────────────────────────────────────────
def pieces(prev: np.ndarray, cur: np.ndarray, *, gap: int = 26, min_h: int = 6):
    """바뀐 곳을 **가로 줄 뭉치**로 자른다.

    글은 줄 단위로 뜨고 표·그림은 덩어리로 뜬다. 세로로 붙어 있으면 한 조각으로
    묶는다(`gap`) — 한 줄 안에서 글자마다 따로 뜨면 그건 모션이 아니라 소음이다.
    """
    d = np.abs(cur.astype(np.int16) - prev.astype(np.int16)).max(axis=2) > 12
    rows = np.where(d.any(axis=1))[0]
    if not len(rows):
        return []
    runs, s = [], rows[0]
    for a, b in zip(rows, rows[1:]):
        if b - a > gap:
            runs.append((s, a)); s = b
    runs.append((s, rows[-1]))
    out = []
    for y0, y1 in runs:
        if y1 - y0 + 1 < min_h:
            continue
        xs = np.where(d[y0:y1 + 1].any(axis=0))[0]
        out.append((int(xs[0]), int(y0), int(xs[-1]) + 1, int(y1) + 1))
    return out


def is_add(prev: np.ndarray, box, *, th: int = 12) -> bool:
    """그 자리가 **비어 있었나**(새로 생기는 것) 아니면 갈아치우는 것인가."""
    x0, y0, x1, y1 = box
    r = prev[y0:y1, x0:x1].astype(np.int16)
    if r.size == 0:
        return True
    med = np.median(r.reshape(-1, 3), axis=0)
    return float((np.abs(r - med).max(axis=2) > th).mean()) < 0.08


# ── 4) 그림 안의 글자 떼어내기 — 이 도구의 핵심 ─────────────────────────
def text_layers(cur: np.ndarray, box, *, zone: float, log=None):
    """액자 안에서 **밝은 바탕에 얹힌 어두운 글자 띠**를 찾아 떼어낸다.

    돌려주는 것은 `(plate, [(띠, 알파), …])`. `plate` 는 글자를 지운 그림이고
    알파는 글자 모양이다. 좌표는 **액자 안쪽 기준**이다.

    ★ 지우는 방법은 **같은 줄의 배경색으로 메우기**다. 제목은 하늘·아이보리처럼
      평평한 곳에 얹히므로 줄마다 그 줄의 배경 중앙값으로 채우면 눈에 안 띈다.
      글자가 그림 위에 바로 얹힌 띠는 메운 자리가 번지므로 **건드리지 않는다**
      (아래 네 가지 검사). 못 떼면 액자를 통째로 훑어 드러내는 것으로 돌아간다.
    """
    x0, y0, x1, y1 = box
    reg = cur[y0:y1, x0:x1].astype(np.int16)
    h, w, _ = reg.shape
    if h < 80 or w < 200:
        return None, []
    # ★ int16 으로 곱하면 넘친다(255×299=76245) — 밝기가 음수로 나와 아무것도
    #   글자로 안 잡힌다. 실제로 그 사고를 한 번 냈다. float32 로 잰다.
    f = reg.astype(np.float32)
    luma = f[:, :, 0] * 0.299 + f[:, :, 1] * 0.587 + f[:, :, 2] * 0.114
    bg = float(np.median(luma))
    if bg < 120:                       # 어두운 판은 이 방법이 안 맞는다
        return None, []
    dark = luma < min(bg * 0.55, 120)
    rows = np.where(dark[:int(h * zone)].any(axis=1))[0]
    if not len(rows):
        return None, []
    runs, s = [], rows[0]
    for a, b in zip(rows, rows[1:]):
        if b - a > 14:
            runs.append((s, a)); s = b
    runs.append((s, rows[-1]))

    plate = reg.copy()
    layers = []
    for ry0, ry1 in runs:
        bh = ry1 - ry0 + 1
        if bh < 14 or bh > h * 0.15:      # 이보다 두꺼우면 글자가 아니라 그림이다
            continue
        band = dark[ry0:ry1 + 1]
        xs = np.where(band.any(axis=0))[0]
        bx0, bx1 = int(xs[0]), int(xs[-1]) + 1
        bw = bx1 - bx0
        if bw < w * 0.10 or bw / bh < 2.2 or float(band[:, bx0:bx1].mean()) > 0.42:
            continue                    # 글자 띠라기엔 너무 두껍거나 좁다
        keep = ~band[:, bx0:bx1]
        if keep.sum() < 20 or float(luma[ry0:ry1 + 1, bx0:bx1][keep].std()) > 36:
            continue                    # 바탕이 평평하지 않다 — 메우면 번진다
        a = np.zeros((h, w), np.float32)
        soft = np.clip((min(bg * 0.85, 190) - luma[ry0:ry1 + 1]) / 60.0, 0, 1)
        a[ry0:ry1 + 1] = np.maximum(band.astype(np.float32), soft * (soft > 0.15))
        a[ry0:ry1 + 1, :bx0] = 0
        a[ry0:ry1 + 1, bx1:] = 0
        layers.append(((bx0, ry0, bx1, ry1 + 1), a))
        # ★ 메울 자리는 **글자보다 넓게**. 글자 테두리(안티에일리어싱)는 옅어서
        #   마스크에 안 걸리는데, 남기면 지운 자리에 흰 유령 윤곽이 보인다
        #   (첫 시험에서 그렇게 나왔다). 9px 부풀린다.
        wide = np.asarray(Image.fromarray(((a > 0.02) * 255).astype(np.uint8))
                          .filter(ImageFilter.MaxFilter(9))) > 127
        for yy in range(max(0, ry0 - 4), min(h, ry1 + 5)):
            sel = wide[yy]
            if not sel.any():
                continue
            keep_row = reg[yy][~sel]
            if keep_row.size < 90:
                keep_row = reg[yy]
            plate[yy][sel] = np.median(keep_row.reshape(-1, 3), axis=0)
    if not layers:
        return None, []
    if log:
        log(f"    그림 속 글자 {len(layers)}띠 분리")
    return plate.astype(np.uint8), layers




# ── 4a) 시간표 읽기 — "0:03~0:15" ───────────────────────────────────────
def _sec(x: str) -> float | None:
    """'0:03' · '3' · '0:03.5' → 초. 빈 칸이면 None."""
    x = (x or "").strip()
    if not x:
        return None
    try:
        if ":" in x:
            m, s = x.split(":")[-2:]
            return int(m or 0) * 60 + float(s or 0)
        return float(x)
    except ValueError:
        return None


def parse_span(z: dict) -> tuple[float | None, float | None]:
    """상자 하나의 (등장 시각, 빛 끝 시각). **씬이 시작한 뒤 몇 초인지**를 뜻한다.

    지정기가 넣어 주는 `"t": "0:03~0:15"` 가 기본이고, 숫자로 준 `at`/`until` 도 받는다.
    비어 있으면 (None, None) — 예전처럼 순서대로 자동 배치된다.
    """
    s = str(z.get("t") or z.get("span") or "").strip()
    if s:
        p = re.split(r"[~\-–—]", s)
        return (_sec(p[0]) if p else None, _sec(p[1]) if len(p) > 1 else None)
    a, u = z.get("at"), z.get("until")
    return (float(a) if a is not None else None,
            float(u) if u is not None else None)


# ── 4b) 사람이 지정한 마스크(zones.json) ────────────────────────────────
def zone_build(cur: np.ndarray, zboxes: list[dict], *, W: int, H: int,
               edge_gain: float = 1.0, log=None):
    """지정기에서 그린 상자로 (plate, rises, art, mask, mbox, report, items, covers) 를 만든다.

    ★ 자동 검출과 달리 **자리는 사람이 정해 준다.** 이 함수가 하는 일은
      (1) 상자 안에서 글자 획 모양(알파)을 뽑고
      (2) 띄울 상자는 그 자리를 배경색으로 메워 「없는 판」을 만들고
      (3) 빛이 지나갈 마스크를 모으고
      (4) 「가리기」 상자는 배경색으로 메운 채 `covers` 에만 담아 — 다시 안 뜬다.

    ★ 알파는 **밝기 차**로 잰다 — 어두운 글자(밝은 바탕)와 밝은 글자(어두운 바탕)가
      섞여 있기 때문이다. 어두운 쪽만 보면 흰 글자를 통째로 놓친다.
    """
    plate = cur.copy()
    rises, art, report, items, covers = [], [], [], [], []
    mask = np.zeros((H, W), np.float32)
    used = []
    for bi, z in enumerate(sorted(zboxes, key=lambda b: (b["y"], b["x"]))):
        x0 = max(0, int(z["x"])); y0 = max(0, int(z["y"]))
        x1 = min(W, x0 + int(z["w"])); y1 = min(H, y0 + int(z["h"]))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        kind = z.get("kind", "text")
        reg = cur[y0:y1, x0:x1].astype(np.float32)
        # ★ 「가리기」— 예전에 글자가 깨져 나오던 자리를 계속 지운 채로 둔다.
        #   text/art 처럼 나중에 슝 올리거나 훑어 드러내지 않는다 — `rises`/`art`/
        #   `items` 어디에도 넣지 않으면 다시 떠오를 자리가 없다. 테두리 링 색으로
        #   메운다(art 와 같은 방법) — 안이 뭐였는지 몰라도 어색하지 않게 지워진다.
        if kind == "cover":
            ring = np.concatenate([reg[:, :6].reshape(-1, 3), reg[:, -6:].reshape(-1, 3),
                                   reg[:6].reshape(-1, 3), reg[-6:].reshape(-1, 3)])
            plate[y0:y1, x0:x1] = np.median(ring, axis=0)
            covers.append((x0, y0, x1, y1))
            used.append((x0, y0, x1, y1))
            report.append(f"{bi + 1}:가리기")
            continue
        luma = reg[:, :, 0] * 0.299 + reg[:, :, 1] * 0.587 + reg[:, :, 2] * 0.114
        # ★ 바탕색은 **줄별 중앙값이 아니라 최빈값**으로 잰다. 굵은 제목을 딱 맞게
        #   싸면 한 줄의 절반 넘게 글자라서 중앙값이 글자색에 얹힌다 — 그러면
        #   알파가 뒤집혀 배경이 글자로 잡히고, "바탕이 거칠다" 며 버려진다.
        #   (실제로 「세금이 지나는 두 갈래」가 그렇게 탈락했다.)
        px0, py0 = max(0, x0 - 14), max(0, y0 - 14)
        px1, py1 = min(W, x1 + 14), min(H, y1 + 14)
        pad = cur[py0:py1, px0:px1].astype(np.float32)
        pl_ = pad[:, :, 0] * 0.299 + pad[:, :, 1] * 0.587 + pad[:, :, 2] * 0.114
        hist, edge = np.histogram(pl_, bins=32, range=(0, 255))
        bgv = float((edge[int(np.argmax(hist))] + edge[int(np.argmax(hist)) + 1]) / 2)
        alpha = np.clip(np.abs(luma - bgv) / 55.0, 0, 1)
        alpha[alpha < 0.14] = 0.0
        flat = alpha < 0.05
        # ★ 그림에는 **획 전체가 아니라 윤곽선만** 빛나게 한다. 글자는 획이 가늘어
        #   통째로 밝아져도 예쁘지만, 도장·화살표처럼 **면이 넓은 그림**은 통째로
        #   밝아지면 하얗게 날아가 사라져 보인다(실측: 세액공제 도장이 지워졌다).
        art_a = alpha
        if kind != "text":
            gx = np.zeros_like(luma); gy = np.zeros_like(luma)
            gx[:, 1:-1] = luma[:, 2:] - luma[:, :-2]
            gy[1:-1] = luma[2:] - luma[:-2]
            e = np.clip(np.sqrt(gx * gx + gy * gy) / 38.0, 0, 1)
            e = np.asarray(Image.fromarray((e * 255).astype(np.uint8))
                           .filter(ImageFilter.MaxFilter(3)), np.float32) / 255.0
            art_a = np.clip(e * edge_gain, 0, 1)
        rough = float(luma[flat].std()) if flat.sum() > 60 else 999.0
        note = ""
        if kind == "text" and rough > 30.0:
            kind = "sheen"                      # 바탕이 거칠다 — 지우면 번진다
            note = f"바탕 거칢(sd {rough:.0f}) → 빛만"
        if kind in ("text", "art"):
            wide = np.asarray(Image.fromarray(((alpha > 0.02) * 255).astype(np.uint8))
                              .filter(ImageFilter.MaxFilter(9))) > 127
            if kind == "art":
                ring = np.concatenate([reg[:, :6].reshape(-1, 3), reg[:, -6:].reshape(-1, 3),
                                       reg[:6].reshape(-1, 3), reg[-6:].reshape(-1, 3)])
                plate[y0:y1, x0:x1] = np.median(ring, axis=0)
            else:
                # ★ 메울 색을 **상자 전체에서 한 번 미리** 잡아 둔다.
                #   바탕 밝기(bgv, 최빈값)에 가까운 픽셀만 모아 RGB 중앙값을 낸다 —
                #   그게 글자가 얹히기 전의 진짜 바탕색이다.
                near = np.abs(pl_ - bgv) < 12.0
                bg_rgb = (np.median(pad[near], axis=0) if int(near.sum()) >= 40
                          else np.median(pad.reshape(-1, 3), axis=0))
                sub = plate[y0:y1, x0:x1]
                for yy in range(y1 - y0):
                    sel = wide[yy]
                    if not sel.any():
                        continue
                    keep = reg[yy][~sel]
                    # ★ 줄에 바탕이 넉넉하면 그 줄 색으로 메운다(세로 그러데이션을
                    #   따라가려고). 모자라면 **상자 바탕색**으로 메운다.
                    #   예전에는 모자랄 때 `reg[yy]` — 즉 **글자까지 섞인 줄 전체**의
                    #   중앙값을 썼다. 글자가 빽빽한 줄만 회색이 되고 성긴 줄은 제
                    #   색으로 메워져 **가로 줄무늬**가 남았다. 좁게 잡은 상자는
                    #   거의 모든 줄이 이 길로 빠진다(2026-08-16 실측: 306x29 상자의
                    #   29줄 중 27줄, 325x25 는 25줄 전부. 785x100 만 멀쩡했다).
                    sub[yy][sel] = (np.median(keep, axis=0) if keep.shape[0] >= 40
                                    else bg_rgb)
        full = np.zeros((H, W), np.float32)
        full[y0:y1, x0:x1] = alpha if kind == "text" else art_a
        if kind == "text":
            rises.append(((x0, y0, x1, y1), full))
        elif kind == "art":
            art.append((x0, y0, x1, y1))
        mask = np.maximum(mask, full)
        used.append((x0, y0, x1, y1))
        report.append(f"{bi + 1}:{kind}{(' ' + note) if note else ''}")
        # ★ 시간표(zones.json 의 "t": "0:03~0:15")를 그대로 달고 다닌다.
        at, until = parse_span(z)
        items.append({"kind": kind, "box": (x0, y0, x1, y1), "alpha": full,
                      "at": at, "until": until, "label": f"{bi + 1}"})
    if not used:
        return None, [], [], None, None, report, [], []
    mbox = (max(0, min(b[0] for b in used) - 8), max(0, min(b[1] for b in used) - 8),
            min(W, max(b[2] for b in used) + 8), min(H, max(b[3] for b in used) + 8))
    return plate, rises, art, mask, mbox, report, items, covers


# ── 5) 한 프레임 그리기 ─────────────────────────────────────────────────
def draw(base: np.ndarray, steps: list[dict], t: float) -> np.ndarray:
    out = base.astype(np.float32).copy()
    H = out.shape[0]
    for st in steps:
        p = (t - st["start"]) / max(st["dur"], 1e-6)
        if p <= 0:
            continue
        e = ease_out(p)
        x0, y0, x1, y1 = st["box"]
        seg = st["src"][y0:y1, x0:x1].astype(np.float32)
        if st["kind"] == "wipe":
            bw, bh = x1 - x0, y1 - y0
            d = st.get("dir", "lr")
            horiz = d in ("lr", "rl")
            n = bw if horiz else bh
            sp = max(8.0, st.get("soft", 0.25) * n)
            edge = -sp + e * (n + sp)
            a = np.clip((edge - np.arange(n, dtype=np.float32)) / sp, 0, 1)
            if d in ("rl", "bt"):            # 반대 방향 — 끝에서부터 훑는다
                a = a[::-1]
            A = (np.tile(a, (bh, 1)) if horiz
                 else np.tile(a[:, None], (1, bw)))[:, :, None]
            out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - A) + seg * A
        else:                                    # rise
            dy = int(round((1.0 - e) * st["rise"]))
            a = st["alpha"][y0:y1, x0:x1] * e
            ty0, ty1 = y0 - dy, y1 - dy
            cy0, cy1 = max(0, ty0), min(H, ty1)
            if cy1 <= cy0:
                continue
            A = a[cy0 - ty0:cy1 - ty0][:, :, None]
            out[cy0:cy1, x0:x1] = (out[cy0:cy1, x0:x1] * (1 - A)
                                   + seg[cy0 - ty0:cy1 - ty0] * A)
    return np.clip(out, 0, 255).astype(np.uint8)


def sheen_frames(still: np.ndarray, card, *, dur: float, amp: float,
                wide: float, fps: int):
    """**화면은 고정한 채 빛만 훑고 지나간다.**

    ★ 화면을 움직이지 않는 게 핵심이다. 그림을 조금씩 확대·이동하면 매 프레임
      다시 그려져 가는 선이 스멀거리는데(눈이 아프다), 빛은 **밝기만** 더하므로
      선이 그대로다. 원본 픽셀을 옮기지 않는다.

    ★ 띠는 넓고 흐릿하게, 세기는 약하게. 좁고 센 띠는 번쩍임이 되어 더 피곤하다.
    """
    x0, y0, x1, y1 = card
    cw = x1 - x0
    n = max(1, int(round(dur * fps)))
    xs = np.arange(cw, dtype=np.float32)
    sig = max(30.0, wide * cw)
    base = still.astype(np.float32)
    for k in range(n):
        p = (k + 1) / n
        pos = -sig + p * (cw + 2 * sig)
        a = np.exp(-0.5 * ((xs - pos) / sig) ** 2) * amp
        # 가장자리에서 뚝 끊기지 않게 처음·끝을 부드럽게 재운다
        a *= float(min(1.0, 4 * p, 4 * (1 - p)))
        out = base.copy()
        reg = out[y0:y1, x0:x1]
        out[y0:y1, x0:x1] = reg + (255.0 - reg) * a[None, :, None]
        yield np.clip(out, 0, 255).astype(np.uint8)


def text_sheen_frames(still, mask, box, *, dur, amp, fps, back=False, wide=0.16):
    """**글자 위로만** 빛이 지나간다. 화면은 1픽셀도 안 움직인다.

    ★ 밝아지는 것은 **글자 획 자체**다(마스크가 글자 모양이라서). 배경은 손대지
      않으므로 사각형 자국이 안 생기고, 원본 픽셀을 옮기지 않으니 선이 스멀거릴
      일도 없다 — 눈이 아픈 원인(리샘플링)을 아예 만들지 않는다.

    ★ 한 번은 왼→오, 다음은 오→왼. 같은 방향으로만 반복하면 배너처럼 보인다.
    """
    x0, y0, x1, y1 = box
    w = x1 - x0
    n = max(1, int(round(dur * fps)))
    xs = np.arange(w, dtype=np.float32)
    sig = max(30.0, wide * w)
    m = mask[y0:y1, x0:x1]
    base = still.astype(np.float32)
    for k in range(n):
        p = (k + 1) / n
        if back:
            p = 1.0 - p
        pos = -sig + p * (w + 2 * sig)
        band = np.exp(-0.5 * ((xs - pos) / sig) ** 2) * amp
        a = (m * band[None, :])[:, :, None]
        out = base.copy()
        reg = out[y0:y1, x0:x1]
        out[y0:y1, x0:x1] = reg + (255.0 - reg) * a
        yield np.clip(out, 0, 255).astype(np.uint8)


def zoom_card(img: np.ndarray, card, z: float, pan_p: float, pan: float) -> np.ndarray:
    """액자 **안쪽만** z 배로 보이게(=바깥을 잘라내) 다시 얹는다. 밖은 고정."""
    if z <= 1.0001:
        return img
    x0, y0, x1, y1 = card
    cw, ch = x1 - x0, y1 - y0
    out = img.copy()
    im = Image.fromarray(img[y0:y1, x0:x1]).resize(
        (max(1, int(cw * z)), max(1, int(ch * z))), Image.BILINEAR)
    zw, zh = im.size
    ox = int((zw - cw) * min(1.0, max(0.0, 0.5 + pan * (pan_p - 0.5))))
    oy = int((zh - ch) * 0.5)
    out[y0:y1, x0:x1] = np.asarray(im.crop((ox, oy, ox + cw, oy + ch)))
    return out


# ── 6) 구간(segment) 굽기 ───────────────────────────────────────────────
def enc_args(a, fps) -> list[str]:
    return ["-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf),
            "-pix_fmt", "yuv420p", "-r", str(int(fps)), "-vsync", "cfr"]


def seg_frames(frames, dst: Path, size, fps, a) -> bool:
    """PIL 로 만든 프레임을 **파일로 안 남기고** 바로 인코더에 흘린다.

    ★ PNG 로 떨어뜨리면 22분짜리는 4만 장이 되고 디스크가 먼저 죽는다.
    """
    w, h = size
    p = subprocess.Popen([FFMPEG, *QUIET, "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{w}x{h}", "-framerate", str(int(fps)), "-i", "-",
                          *enc_args(a, fps), str(dst)], stdin=subprocess.PIPE)
    try:
        for f in frames:
            p.stdin.write(np.ascontiguousarray(f).tobytes())
    finally:
        p.stdin.close()
    return p.wait() == 0


def seg_hold(still: Path, dst: Path, frames: int, fps, a) -> bool:
    """정지 구간. ★ **초가 아니라 프레임 수**로 못 박는다.

    초로 주면 구간마다 반올림 오차가 조금씩 남고, 그게 300개쯤 쌓이면 영상이
    원본보다 2초 짧아진다 — 뒤로 갈수록 화면이 내레이션보다 빨라진다(실측 1.86초).
    """
    n = max(1, int(frames))
    return sh([FFMPEG, *QUIET, "-loop", "1", "-framerate", str(int(fps)),
               "-i", str(still), "-frames:v", str(n),
               *enc_args(a, fps), str(dst)]).returncode == 0


def seg_drift(plate: Path, dst: Path, sec: float, *, card, z0: float, t0: float,
              span: float, title: Path | None, tpos, fps, a) -> bool:
    """그림은 **줄어들고**, 제목은 크기 그대로 아주 조금 부유한다.

    ffmpeg 이 한다 — 프레임을 파이썬으로 만들면 22분에 4만 장이라 몇십 분이 든다.
    `zoompan` 은 확대만 하므로, **z 를 시간에 따라 줄여** 안착을 만든다(1.05→1.00).
    """
    x0, y0, x1, y1 = card
    cw, ch = x1 - x0, y1 - y0
    d = max(0.0, z0 - 1.0)
    gt = f"({t0:.3f}+on/{int(fps)})"
    z = f"max(1,1+{d:.5f}*(1-{gt}/{max(span, 0.001):.3f}))"
    px = f"(iw-iw/zoom)*(0.5+{a.pan:.3f}*({gt}/{max(span, 0.001):.3f}-0.5))"
    fc = (f"[0:v]split=2[bg][src];"
          f"[src]crop={cw}:{ch}:{x0}:{y0},zoompan=z='{z}':x='{px}':"
          f"y='(ih-ih/zoom)/2':d=1:s={cw}x{ch}:fps={int(fps)}[c];"
          f"[bg][c]overlay={x0}:{y0}")
    ins = [FFMPEG, *QUIET, "-loop", "1", "-framerate", str(int(fps)),
           "-t", f"{max(sec, 1.0/fps):.3f}", "-i", str(plate)]
    if title is not None and a.float_px > 0:
        ins += ["-loop", "1", "-framerate", str(int(fps)),
                "-t", f"{max(sec, 1.0/fps):.3f}", "-i", str(title)]
        fc += (f"[b];[b][1:v]overlay={tpos[0]}:"
               f"y='{tpos[1]}+{a.float_px:.2f}*sin(2*PI*(t+{t0:.3f})/{a.float_sec:.2f})'"
               f":eval=frame")
    elif title is not None:
        ins += ["-loop", "1", "-framerate", str(int(fps)),
                "-t", f"{max(sec, 1.0/fps):.3f}", "-i", str(title)]
        fc += f"[b];[b][1:v]overlay={tpos[0]}:{tpos[1]}"
    r = sh(ins + ["-filter_complex", fc, *enc_args(a, fps), str(dst)])
    if r.returncode != 0:
        print("    드리프트 실패 — 정지로 대체:", (r.stderr or "")[-200:])
        return False
    return True


# ── 6b) 시간표대로 한 씬 굽기 (zones.json 전용) ─────────────────────────
def bake_zoned(*, cur, plate, items, card, F0: int, F1: int, fps: int, a,
               seg_dir: Path, tag: str, still_src: Path, W: int, H: int):
    """한 씬을 **사람이 찍어 준 시각표대로** 굽는다.

    한 씬의 시간축은 이렇게 생겼다 — 초는 **씬이 시작한 순간부터** 센다.

        0.0  빈 배경에서 액자가 훑고 들어온다
        0:03 「제목」이 뜬다 → 그 순간부터 0:12 까지 **그 상자에만** 빛이 왕복한다
        0:12 「부제」가 뜬다 → 0:12~0:25 빛이 그리로 옮겨간다
        …
        끝   화면을 **걷어낸다**(out_dur). 다음 씬은 빈 배경에서 시작한다

    ★ 걷어내기가 핵심이다. 이게 없으면 새 씬이 훑고 들어오는 동안 이전 슬라이드가
      옆에 남아 두 장이 겹쳐 보인다 — 실제로 "자국이 남아 지저분하다" 는 평을 받았다.

    ★ 빛은 **말하고 있는 그 상자에만** 간다. 화면 전체에 계속 빛을 흘리면 어디를
      봐야 하는지 알려 주지 못한다. 시각표의 뒤 숫자가 "여기까지 보세요" 다.

    돌려주는 것: (구간 파일들, 실제로 만든 프레임 수). 프레임 수는 **항상 F1-F0** 이다
    — 소리와 어긋나지 않게 절대 프레임으로 맞춰 채운다.
    """
    N = max(0, F1 - F0)
    segs: list[Path] = []
    made = 0
    if N < 2:
        return segs, 0

    bg = np.median(np.concatenate([cur[0:5].reshape(-1, 3),
                                   cur[H - 5:].reshape(-1, 3)]), axis=0)
    blank = plate.copy()
    # ★ 액자를 **비우는 것**과 **훑어 되살리는 것**은 한 쌍이다. 훑기만 빼면
    #   되살릴 사람이 없어져 그림이 통째로 사라진다(2026-08-16에 그렇게 만들어
    #   빈 판이 나왔다). 액자 등장을 끄면 비우지도 않는다 — 그림은 처음부터
    #   제자리에 있고, 글자만 떠오른다.
    if card and a.frame_in:
        blank[card[1]:card[3], card[0]:card[2]] = bg

    out_n = min(int(round(max(0.0, a.out_dur) * fps)), max(0, N // 5))
    body = N - out_n
    bsec = body / fps

    def fr(x: float) -> int:
        return int(round(x * fps))

    # ── 시간표를 짠다 ───────────────────────────────────────────────
    steps: list[dict] = []
    tt = 0.0
    # ★ 액자가 훑고 들어오는 등장은 **기본으로 끈다**(2026-08-16) —
    #   글자 효과만으로 충분하다.
    #   훑는 경계가 부드러워서(`--wipe-soft 0.25`) 장이 바뀌는 순간 오른쪽 절반이
    #   흐리게 비쳤다. 글자 등장과 빛은 그대로 둔다.
    # ★ `--wipe-dur 0` 으로 끄지 않는 이유 — 그 값은 `art` 상자가 훑어 드러나는
    #   시간이기도 해서, 0 으로 만들면 그림 상자까지 같이 죽는다.
    #   되살리려면 `--frame-in 1`.
    if card and a.frame_in:
        steps.append({"kind": "wipe", "box": card, "src": plate, "start": 0.0,
                      "dur": a.wipe_dur, "soft": a.wipe_soft, "dir": a.wipe_dir})
        tt = a.wipe_dur * 0.8 + a.text_gap
    tl: list[dict] = []
    for it in items:
        dur = a.text_dur if it["kind"] == "text" else a.wipe_dur
        at = it["at"]
        auto = at is None
        if auto:
            at = tt
        at = max(0.0, min(float(at), max(0.0, bsec - dur - 0.05)))
        tt = at + a.text_gap
        tl.append({**it, "at": at, "dur": dur, "auto": auto})
    tl.sort(key=lambda d: (d["at"], d["box"][1], d["box"][0]))
    for k, it in enumerate(tl):
        u = it["until"]
        if u is None:                    # 안 적었으면 **다음 상자가 뜰 때까지**
            u = tl[k + 1]["at"] if k + 1 < len(tl) else bsec
        it["until"] = max(it["at"] + it["dur"], min(float(u), bsec))
        if it["kind"] == "text":
            steps.append({"kind": "rise", "box": it["box"], "src": cur,
                          "alpha": it["alpha"], "start": it["at"],
                          "dur": it["dur"], "rise": a.text_rise})
        elif it["kind"] == "art":
            steps.append({"kind": "wipe", "box": it["box"], "src": cur,
                          "start": it["at"], "dur": it["dur"],
                          "soft": a.wipe_soft, "dir": a.wipe_dir})

    last_end = max([fr(s["start"] + s["dur"]) for s in steps], default=0)
    marks = {0, body}
    for s in steps:
        marks.add(fr(s["start"])); marks.add(fr(s["start"] + s["dur"]))
    for it in tl:
        marks.add(fr(it["at"])); marks.add(fr(it["until"]))
    marks = sorted({min(max(m, 0), body) for m in marks})

    def moving(s: int, e: int) -> bool:
        return any(fr(st["start"]) < e and fr(st["start"] + st["dur"]) > s
                   for st in steps)

    j = 0
    for s, e in zip(marks, marks[1:]):
        if e <= s:
            continue
        if moving(s, e):
            def gen(s=s, e=e):
                for f in range(s, e):
                    # ★ 등장이 다 끝나는 그 한 장은 **원본 그대로** 넣는다.
                    #   합성판에서 원본으로 넘어갈 때 한 프레임 튀면 흔들려 보인다.
                    if f == last_end - 1:
                        yield cur
                    else:
                        yield draw(blank, steps, (f + 1) / fps)
            p = seg_dir / f"{tag}_{j:03d}a.mp4"
            if seg_frames(gen(), p, (W, H), fps, a):
                segs.append(p); made += e - s
            j += 1
            continue

        # 안 움직이는 구간 — 이 순간의 화면 한 장을 만들어 놓고 빛만 지나간다
        if s >= last_end:
            still_p, still_img = still_src, cur      # 원본 그대로
        else:
            still_img = draw(blank, steps, (s + 0.5) / fps)
            still_p = seg_dir / f"{tag}_{j:03d}s.png"
            Image.fromarray(still_img).save(still_p)
        lit = [it for it in tl if fr(it["at"]) <= s < fr(it["until"])]
        left = e - s
        if lit and a.text_sheen_amp > 0 and a.text_sheen_dur > 0:
            m = np.maximum.reduce([it["alpha"] for it in lit])
            bx = (max(0, min(i["box"][0] for i in lit) - 8),
                  max(0, min(i["box"][1] for i in lit) - 8),
                  min(W, max(i["box"][2] for i in lit) + 8),
                  min(H, max(i["box"][3] for i in lit) + 8))
            k = 0
            while left > 0 and k < 200:
                g = min(int(round(max(0.0, a.text_sheen) * fps)), left)
                if g > 0:
                    p = seg_dir / f"{tag}_{j:03d}g{k}.mp4"
                    if not seg_hold(still_p, p, g, fps, a):
                        break
                    segs.append(p); made += g; left -= g
                if left <= 0:
                    break
                sn = min(int(round(a.text_sheen_dur * fps)), left)
                if sn < 6:
                    break
                p = seg_dir / f"{tag}_{j:03d}h{k}.mp4"
                if not seg_frames(text_sheen_frames(
                        still_img, m, bx, dur=sn / fps, amp=a.text_sheen_amp,
                        fps=fps, back=(k % 2 == 1), wide=a.text_sheen_wide),
                        p, (W, H), fps, a):
                    break
                segs.append(p); made += sn; left -= sn
                k += 1
        if left > 0:                        # 남은 자리는 정지로 채운다
            p = seg_dir / f"{tag}_{j:03d}c.mp4"
            if seg_hold(still_p, p, left, fps, a):
                segs.append(p); made += left
        j += 1

    # ── 걷어내기 — 오→왼으로 훑어 빈 배경만 남긴다 ────────────────────
    if out_n > 0:
        so = [{"kind": "wipe", "box": (0, 0, W, H), "src": blank, "start": 0.0,
               "dur": out_n / fps, "soft": 0.22, "dir": a.out_dir}]
        p = seg_dir / f"{tag}_out.mp4"
        if seg_frames((draw(cur, so, (f + 1) / fps) for f in range(out_n)),
                      p, (W, H), fps, a):
            segs.append(p); made += out_n

    if made < N:                            # 무엇이 실패했든 길이는 지킨다
        p = seg_dir / f"{tag}_pad.mp4"
        if seg_hold(still_src, p, N - made, fps, a):
            segs.append(p); made += N - made
    return segs, made


# ── 7) 조립 ─────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="완성 mp4 를 모션 mp4 로 (원본은 그대로)")
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default="")
    for k, v in D.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    ap.add_argument("--limit", type=float, default=0, help="앞 N초만 (미리보기)")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--zones", default="", help="지정기에서 내려받은 zones.json")
    a = ap.parse_args()

    src = Path(a.src).expanduser().resolve()
    if not src.is_file():
        sys.exit(f"파일이 없습니다: {src}")
    out = Path(a.out).expanduser() if a.out else src.with_name(src.stem + "-motion.mp4")
    if out.resolve() == src:
        sys.exit("원본을 덮어쓸 수 없습니다 — 다른 이름을 쓰세요")
    meta = probe(src)
    fps = int(a.fps or meta["fps"])
    W, H = meta["w"], meta["h"]
    span_all = min(meta["sec"], a.limit) if a.limit else meta["sec"]
    print(f"원본 {W}×{H} · {meta['fps']:.3g}fps · {meta['sec']:.1f}초"
          + (f" · 앞 {a.limit:g}초만" if a.limit else ""))

    tmp = Path(tempfile.mkdtemp(prefix="motion-"))
    seg_dir = tmp / "seg"; seg_dir.mkdir()
    try:
        print("1/4 변화 지점 찾기")
        ev = find_events(src, sample_fps=a.sample_fps, sens=a.sensitivity,
                         limit=span_all if a.limit else None)
        cuts = [0.0] + [t for t in ev if 0.25 < t < span_all - 0.05]

        ZON = None
        if a.zones:
            zj = json.loads(Path(a.zones).expanduser().read_text(encoding="utf-8"))
            zs = zj["scenes"]
            ZON = {}
            for k, t in enumerate(cuts):            # 전환 시각으로 짝짓는다
                hit = min(zs, key=lambda s0: abs(s0.get("cut", -999) - t))
                if abs(hit.get("cut", -999) - t) <= 1.5:
                    ZON[k] = hit.get("boxes", [])
            print(f"  지정 마스크 {sum(len(v) for v in ZON.values())}개 "
                  f"/ 씬 {len(ZON)}개 짝지음 (전체 {len(cuts)}장)")

        print("2/4 정지 화면 뽑기")
        pick = []
        for i, t in enumerate(cuts):
            nxt = cuts[i + 1] if i + 1 < len(cuts) else span_all
            pick.append(min(t + 0.30, max(t + 0.02, nxt - 0.10)))
        shots = grab_all(src, pick, tmp)
        if 0 not in shots:
            sys.exit("첫 화면을 못 뽑았습니다")

        print("3/4 장마다 모션 굽기")
        segs: list[Path] = []
        emitted = 0                     # 지금까지 낸 프레임 수 — 반올림 누적 방지
        prev: np.ndarray | None = None
        card0 = None
        for i, t in enumerate(cuts):
            if i not in shots:
                continue
            cur = np.asarray(Image.open(shots[i]).convert("RGB"))
            nxt = cuts[i + 1] if i + 1 < len(cuts) else span_all
            span = max(0.05, nxt - t)

            boxes = sorted(pieces(prev, cur), key=lambda b: (b[1], b[0])) if prev is not None else []
            big = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) > W * H * 0.06]
            card = big[0] if big else None
            if card:
                card0 = card
            # 첫 장은 비교할 앞 화면이 없다 — 액자를 비운 판을 만들어 등장시킨다
            if prev is None:
                card = card0
                if card is None and len(cuts) > 1 and (i + 1) in shots:
                    nb = [b for b in pieces(cur, np.asarray(Image.open(shots[i + 1]).convert("RGB")))
                          if (b[2] - b[0]) * (b[3] - b[1]) > W * H * 0.06]
                    card = nb[0] if nb else None
                bg = np.median(np.concatenate([cur[0:5].reshape(-1, 3),
                                               cur[H - 5:].reshape(-1, 3)]), axis=0)
                base = cur.copy()
                if card:
                    base[card[1]:card[3], card[0]:card[2]] = bg
                    boxes, big = [card], [card]
                else:
                    boxes, big = [], []
            else:
                base = prev

            # ── 이 장의 계획 ────────────────────────────────────────────
            steps: list[dict] = []
            layers: list = []
            plate_full = None
            tt = 0.0
            z0 = 1.0 + (a.drift / 100.0 if card else 0.0)
            zmask = None; zbox = None
            if ZON is not None and ZON.get(i):
                # ★ 사람이 지정한 마스크가 있으면 자동 검출을 쓰지 않는다.
                zp, zrise, zart, zmask, zbox, zrep, zitems, zcovers = zone_build(
                    cur, ZON[i], W=W, H=H, edge_gain=a.art_edge)
                if zp is not None:
                    # ★ 「가리기」는 **`text`/`art` 와 다르다** — 나중에 원본(`cur`)으로
                    #   되돌아가는 자리가 두 곳 있다: 등장이 끝난 뒤 흔들림 없게 넣는
                    #   "마지막 한 장은 원본 그대로"(`bake_zoned` 안, 아래 991행 부근)와
                    #   정지 구간의 밑그림 파일(`still_src`, 디스크의 스크린샷 그대로).
                    #   `cur` 를 그대로 두면 그 두 자리에서 지운 글자가 도로 나타난다
                    #   — 그래서 가린 자리만 `zp`(이미 메운 판) 값으로 바꿔치기한
                    #   `cur_final` 을 만들어 **`cur` 대신** 넘긴다.
                    cur_final = cur
                    if zcovers:
                        cur_final = cur.copy()
                        for (cx0, cy0, cx1, cy1) in zcovers:
                            cur_final[cy0:cy1, cx0:cx1] = zp[cy0:cy1, cx0:cx1]
                        Image.fromarray(cur_final).save(shots[i])
                    # ★ 시간표대로 굽는 길 — 빈 배경에서 시작해 걷어내며 끝난다.
                    F1 = int(round(nxt * fps))
                    ss, made = bake_zoned(
                        cur=cur_final, plate=zp, items=zitems, card=card,
                        F0=emitted, F1=F1, fps=fps, a=a, seg_dir=seg_dir,
                        tag=f"{i:05d}", still_src=shots[i], W=W, H=H)
                    segs += ss
                    emitted += made
                    tset = sum(1 for z in ZON[i] if parse_span(z)[0] is not None)
                    print(f"    마스크 {len(ZON[i])}개 · 시각 지정 {tset}개 — "
                          + ", ".join(zrep))
                    if i % 5 == 0 or i == len(cuts) - 1:
                        print(f"  {i+1}/{len(cuts)} · {made/fps:.1f}초 "
                              f"(걷어내기 {min(a.out_dur, made/fps/5):.2f}초)")
                    prev = cur
                    continue
                if False:
                    plate_full = zp
                    if card:
                        src_img = zoom_card(plate_full, card, z0, 0.0, a.pan)
                        steps.append({"kind": "wipe", "box": card, "src": src_img,
                                      "start": tt, "dur": a.wipe_dur,
                                      "soft": a.wipe_soft, "dir": a.wipe_dir})
                        tt += a.wipe_dur * 0.8 + a.text_gap
                    for gb, al in zrise:               # 지정한 글자 — 획 모양대로 슝
                        steps.append({"kind": "rise", "box": gb, "src": cur,
                                      "alpha": al, "start": tt, "dur": a.text_dur,
                                      "rise": a.text_rise})
                        tt += a.text_gap
                    for gb in zart:                    # 지정한 그림 — 칸 전체 훑기
                        steps.append({"kind": "wipe", "box": gb, "src": cur,
                                      "start": tt, "dur": a.wipe_dur,
                                      "soft": a.wipe_soft, "dir": a.wipe_dir})
                        tt += a.text_gap
                    boxes = []
                    print(f"    마스크 {len(ZON[i])}개 — " + ", ".join(zrep))
            for box in boxes:
                x0, y0, x1, y1 = box
                if box in big:
                    pl, layers = text_layers(cur, box, zone=a.text_zone)
                    plate_full = cur.copy()
                    if pl is not None:
                        plate_full[y0:y1, x0:x1] = pl
                    src_img = zoom_card(plate_full, box, z0, 0.0, a.pan)
                    steps.append({"kind": "wipe", "box": box, "src": src_img,
                                  "start": tt, "dur": a.wipe_dur,
                                  "soft": a.wipe_soft, "dir": a.wipe_dir})
                    tt += a.wipe_dur * 0.8 + a.text_gap
                    for lb, la in layers:          # 그림 속 제목 · 부제
                        al = np.zeros((H, W), np.float32)
                        al[y0:y1, x0:x1] = la
                        gb = (lb[0] + x0, lb[1] + y0, lb[2] + x0, lb[3] + y0)
                        steps.append({"kind": "rise", "box": gb, "src": cur,
                                      "alpha": al, "start": tt, "dur": a.text_dur,
                                      "rise": a.text_rise})
                        tt += a.text_gap
                elif is_add(prev if prev is not None else cur, box):
                    d = np.abs(cur.astype(np.int16) - base.astype(np.int16)).max(axis=2)
                    steps.append({"kind": "rise", "box": box, "src": cur,
                                  "alpha": np.clip(d / 26.0, 0, 1).astype(np.float32),
                                  "start": tt, "dur": a.dur, "rise": a.rise})
                    tt += a.stagger
                else:
                    steps.append({"kind": "wipe", "box": box, "src": cur,
                                  "start": tt, "dur": min(0.45, a.wipe_dur),
                                  "soft": 0.3, "dir": a.wipe_dir})
                    tt += 0.12
            need_sec = max((s["start"] + s["dur"] for s in steps), default=0.0)
            if need_sec > span * 0.7:                      # 구간이 짧으면 줄인다
                k = (span * 0.7) / need_sec
                for s in steps:
                    s["start"] *= k; s["dur"] *= k
                need_sec = span * 0.7

            # ── (a) 등장 구간 ───────────────────────────────────────────
            n = int(round(need_sec * fps))
            if n:
                sa = seg_dir / f"{i:05d}a.mp4"
                # ★ 마지막 한 장은 **원본 그대로** 쓴다. 떼어낸 글자를 다시 얹은
                #   합성판과 원본은 글자 테두리에서 미세하게 다른데, 그 상태로
                #   정지 구간(원본)으로 넘어가면 한 프레임 툭 튄다 — 그게 화면이
                #   흔들리는 것처럼 보인다.
                def _entry():
                    for f in range(n - 1):
                        yield draw(base, steps, (f + 1) / fps)
                    yield cur
                if seg_frames(_entry(), sa, (W, H), fps, a):
                    emitted += n
                    segs.append(sa)
                else:
                    n = 0
            rest = span - n / fps

            # ── (b) 남은 시간 — 그림이 안착하고 제목이 부유한다 ─────────
            settle_sec = min(a.settle, rest) if (card and a.drift > 0) else 0.0
            if settle_sec > 0.05 and plate_full is not None:
                sb = seg_dir / f"{i:05d}b.mp4"
                done = False
                if True:
                    pp = seg_dir / f"{i:05d}p.png"
                    Image.fromarray(plate_full).save(pp)
                    tp = None; tpos = (0, 0)
                    if layers:
                        lx0 = min(l[0][0] for l in layers) + card[0]
                        ly0 = min(l[0][1] for l in layers) + card[1]
                        lx1 = max(l[0][2] for l in layers) + card[0]
                        ly1 = max(l[0][3] for l in layers) + card[1]
                        al = np.zeros((H, W), np.float32)
                        al[card[1]:card[3], card[0]:card[2]] = np.maximum.reduce(
                            [l[1] for l in layers])
                        rgba = np.dstack([cur, (np.clip(al, 0, 1) * 255).astype(np.uint8)])
                        tp = seg_dir / f"{i:05d}t.png"
                        Image.fromarray(rgba[ly0:ly1, lx0:lx1], "RGBA").save(tp)
                        tpos = (lx0, ly0)
                    done = seg_drift(pp, sb, settle_sec, card=card, z0=z0,
                                     t0=0.0, span=settle_sec, title=tp,
                                     tpos=tpos, fps=fps, a=a)
                if done:
                    segs.append(sb); emitted += int(round(settle_sec * fps))
                else:
                    settle_sec = 0.0
            # ★ 이 장이 끝나야 하는 절대 프레임을 기준으로 남은 프레임을 센다 —
            #   그래야 반올림이 쌓이지 않고 소리와 화면이 끝까지 붙어 있는다.
            # ★ `emitted` 에는 등장 프레임(n)이 **이미 들어 있다.** 여기서 n 을 또
            #   빼면 그 장이 n 프레임만큼 짧아지고, 그게 쌓여 영상이 원본보다
            #   2초 짧아진다(실측: 41194 vs 41253 프레임).
            hold_n = int(round(nxt * fps)) - emitted - int(round(settle_sec * fps))
            hold = max(0, hold_n) / fps
            if hold_n > 0 or (n == 0 and settle_sec == 0):
                tmask = None; tbox = None
                if zmask is not None and zbox is not None:
                    tmask, tbox = zmask, zbox
                elif card and layers:
                    tmask = np.zeros((H, W), np.float32)
                    tmask[card[1]:card[3], card[0]:card[2]] = np.maximum.reduce(
                        [l[1] for l in layers])
                    lx0 = min(l[0][0] for l in layers) + card[0] - 8
                    ly0 = min(l[0][1] for l in layers) + card[1] - 8
                    lx1 = max(l[0][2] for l in layers) + card[0] + 8
                    ly1 = max(l[0][3] for l in layers) + card[1] + 8
                    tbox = (max(0, lx0), max(0, ly0), min(W, lx1), min(H, ly1))
                if tmask is not None and a.text_sheen > 0 and hold > a.text_sheen:
                    left, j = hold, 0
                    while left > 0.001 and j < 60:
                        gap = min(a.text_sheen, left)
                        gn = int(round(gap * fps))
                        sc = seg_dir / f"{i:05d}g{j}.mp4"
                        if gn > 0 and seg_hold(shots[i], sc, gn, fps, a):
                            segs.append(sc); left -= gn / fps; emitted += gn
                        if left > a.text_sheen_dur + 0.2:
                            sd = seg_dir / f"{i:05d}h{j}.mp4"
                            if seg_frames(text_sheen_frames(
                                    cur, tmask, tbox, dur=a.text_sheen_dur,
                                    amp=a.text_sheen_amp, fps=fps, back=(j % 2 == 1),
                                    wide=a.text_sheen_wide),
                                    sd, (W, H), fps, a):
                                sn = int(round(a.text_sheen_dur * fps))
                                segs.append(sd); left -= sn / fps; emitted += sn
                        j += 1
                    rest_n = int(round(nxt * fps)) - emitted
                    if rest_n > 0:
                        sc = seg_dir / f"{i:05d}gz.mp4"
                        if seg_hold(shots[i], sc, rest_n, fps, a):
                            segs.append(sc); emitted += rest_n
                elif card and a.sheen > 0 and hold > a.sheen:
                    # 빛이 지나가는 사이사이는 **완전 정지**다(원본 그대로)
                    left, j, t_in = hold, 0, 0.0
                    while left > 0.001:
                        gap = min(a.sheen, left)
                        if gap > 0.001:
                            sc = seg_dir / f"{i:05d}c{j}.mp4"
                            gn = int(round(gap * fps))
                            if seg_hold(shots[i], sc, gn, fps, a):
                                segs.append(sc); emitted += gn
                            left -= gn / fps
                        if left > a.sheen_dur + 0.2:
                            sd = seg_dir / f"{i:05d}d{j}.mp4"
                            if seg_frames(sheen_frames(cur, card, dur=a.sheen_dur,
                                                       amp=a.sheen_amp,
                                                       wide=a.sheen_wide, fps=fps),
                                          sd, (W, H), fps, a):
                                sn = int(round(a.sheen_dur * fps))
                                segs.append(sd); emitted += sn
                                left -= sn / fps
                        j += 1
                        if j > 40:
                            break
                    rest_n = int(round(nxt * fps)) - emitted
                    if rest_n > 0:
                        sc = seg_dir / f"{i:05d}z.mp4"
                        if seg_hold(shots[i], sc, rest_n, fps, a):
                            segs.append(sc); emitted += rest_n
                elif hold_n > 0:
                    sc = seg_dir / f"{i:05d}c.mp4"
                    if seg_hold(shots[i], sc, hold_n, fps, a):
                        segs.append(sc); emitted += hold_n
            if i % 5 == 0 or i == len(cuts) - 1:
                print(f"  {i+1}/{len(cuts)} · 등장 {need_sec:.1f}초 · "
                      f"안착 {settle_sec:.1f}초 · 정지 {max(0.0, rest-settle_sec):.1f}초"
                      f" · 글자 {len(layers)}띠")
            prev = cur

        print(f"4/4 이어 붙이기 — 구간 {len(segs)}개")
        cat = tmp / "list.txt"
        cat.write_text("\n".join(f"file '{s.resolve().as_posix()}'" for s in segs),
                       encoding="utf-8")
        args = [FFMPEG, *QUIET, "-f", "concat", "-safe", "0", "-i", str(cat)]
        if meta["audio"]:
            args += ["-i", str(src)]
        args += ["-map", "0:v:0", "-c:v", "copy"]
        if meta["audio"]:
            args += ["-map", "1:a:0", "-c:a", "copy"]
        args += ["-movflags", "+faststart"]
        if a.limit:
            args += ["-t", f"{span_all:.3f}"]
        args += ["-shortest", str(out)]
        r = sh(args)
        if r.returncode != 0:
            sys.exit("이어 붙이기 실패:\n" + (r.stderr or "")[-1500:])
        print(f"완료 → {out}  ({out.stat().st_size/1e6:.1f}MB)")
    finally:
        if a.keep:
            print(f"중간 파일: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
