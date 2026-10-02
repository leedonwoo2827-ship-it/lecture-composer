#!/usr/bin/env python3
"""완성 mp4 → 마스크 지정기 HTML 한 방에 만들기.

    python make_picker.py "…\\19-img.mp4"          → 19-img-마스크지정기.html

하는 일은 넷이다.
  1) remaster.py 와 **똑같은 방법**으로 장면 전환을 찾는다 (씬 번호가 어긋나면 안 된다)
  2) 씬마다 자리 잡은 정지 화면을 한 장씩 뽑는다
  3) 글자 띠 후보를 넉넉히 찾아 **기본 상자**를 깔아 둔다 (사람이 고칠 밑그림)
  4) 정지 화면을 통째로 박아 넣은 **혼자 도는 HTML** 을 쓴다

사람이 그 HTML 에서 상자를 고치고 zones.json 을 내려받아
`remaster.py --zones zones.json` 으로 넘기면 끝난다.
"""
import base64, importlib.util, json, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rm", HERE / "remaster.py")
rm = importlib.util.module_from_spec(spec); spec.loader.exec_module(rm)


# ── 1) 장면 전환 ─────────────────────────────────────────────────────────
def scenes(src: Path):
    meta = rm.probe(src)
    ev = rm.find_events(src, sample_fps=rm.D["sample_fps"],
                        sens=rm.D["sensitivity"], limit=None)
    cuts = [0.0] + [t for t in ev if 0.25 < t < meta["sec"] - 0.05]
    times = []
    for i, t in enumerate(cuts):
        nxt = cuts[i + 1] if i + 1 < len(cuts) else meta["sec"]
        times.append(min(t + 5.0, max(t + 1.0, nxt - 2.0)))   # 자리 잡은 뒤
    return meta, cuts, times


# ── 2) 기본 상자 제안 ────────────────────────────────────────────────────
def propose(img: np.ndarray):
    """밝은 바탕 위 어두운 글자 띠를 **넉넉히** 찾는다. 사람이 지울 밑그림이므로
    remaster.py 본체보다 기준을 풀어 둔다(놓치는 것보다 많이 잡는 편이 낫다)."""
    H, W, _ = img.shape
    f = img.astype(np.float32)
    luma = f[:, :, 0] * .299 + f[:, :, 1] * .587 + f[:, :, 2] * .114
    bg = float(np.median(luma))
    dark = luma < min(bg * 0.62, 140)
    rows = np.where(dark.mean(axis=1) > 0.002)[0]
    if not len(rows):
        return []
    runs, s = [], rows[0]
    for a, b in zip(rows, rows[1:]):
        if b - a > 10:
            runs.append((s, a)); s = b
    runs.append((s, rows[-1]))
    out = []

    def emit(ry0, ry1, depth=0):
        bh = ry1 - ry0 + 1
        if bh < 16:
            return
        band = dark[ry0:ry1 + 1]
        xs = np.where(band.any(axis=0))[0]
        if not len(xs):
            return
        bx0, bx1 = int(xs[0]), int(xs[-1]) + 1
        bw = bx1 - bx0
        if bh > H * 0.16 and depth < 3:          # 두꺼우면 골짜기에서 쪼갠다
            sub = band[:, bx0:bx1].mean(axis=1)
            lo = np.where(sub < max(sub.max() * 0.06, 0.004))[0]
            if len(lo):
                gaps, g = [], [lo[0]]
                for a, b in zip(lo, lo[1:]):
                    if b - a > 1:
                        gaps.append(g); g = [b]
                    else:
                        g.append(b)
                gaps.append(g)
                gaps = [g for g in gaps if len(g) >= 4 and 8 < g[0] < bh - 8]
                if gaps:
                    cut = max(gaps, key=len); m = ry0 + cut[len(cut) // 2]
                    emit(ry0, m - 1, depth + 1); emit(m + 1, ry1, depth + 1)
            return
        if bh > H * 0.16 or bw < W * 0.06 or bw / bh < 1.8:
            return
        fill = float(band[:, bx0:bx1].mean())
        if fill > 0.62:
            return
        keep = ~band[:, bx0:bx1]
        if keep.sum() < 20:
            return
        sd = float(luma[ry0:ry1 + 1, bx0:bx1][keep].std())
        kind = "text" if (fill <= 0.55 and sd <= 42 and bh <= 140) else "art"
        out.append({"x": int(bx0), "y": int(ry0), "w": int(bw), "h": int(bh),
                    "kind": kind})

    for a, b in runs:
        emit(a, b)
    return out


# ── 2b) 그림 조각 걸러내기 — 글자만 남긴다 ──────────────────────────────
def looks_text(img: np.ndarray, b: dict) -> bool:
    """상자 안이 **글자**인지 **그림 선**인지 가른다.

    글자는 획이 여러 번 끊겨 「덩어리 수」가 많다. 차트 축선·화살표·돌덩이 띠는
    한 덩어리로 쭉 이어져 덩어리 수가 1~5 로 뚝 떨어진다. 실측(25_19):

        제목 「같은 경제, 다른 렌즈」  ink 0.40  rpk 33   → 글자
        연표 라벨 줄                  ink 0.15  rpk 25   → 글자
        차트 가로 축선                ink 0.07  rpk 1.6  → 그림 (버린다)
        돌덩이 위 라벨 띠             ink 0.18  rpk 1.6  → 그림 (버린다)

    ★ 바탕은 **최빈값**으로 잰다. 굵은 제목은 중앙값을 쓰면 글자색에 얹힌다.
    ★ 그림에 효과를 걸면 자국이 남는다 — 그래서 애초에 후보에서 뺀다.
    """
    x0, y0 = max(0, int(b["x"])), max(0, int(b["y"]))
    x1 = min(img.shape[1], x0 + int(b["w"]))
    y1 = min(img.shape[0], y0 + int(b["h"]))
    if x1 - x0 < 12 or y1 - y0 < 10:
        return False
    reg = img[y0:y1, x0:x1].astype(np.float32)
    luma = reg[:, :, 0] * .299 + reg[:, :, 1] * .587 + reg[:, :, 2] * .114
    hist, _ = np.histogram(luma, bins=64, range=(0, 256))
    bg = (np.argmax(hist) + 0.5) * 4
    dark = luma < min(bg * 0.72, bg - 25)
    ink = float(dark.mean())
    cols = dark.any(axis=0).astype(np.int8)
    runs = int(((cols[1:] == 1) & (cols[:-1] == 0)).sum() + (1 if cols[0] else 0))
    rpk = runs / ((x1 - x0) / 1000.0)
    return rpk >= 18.0 and ink >= 0.12


TPL = Path(__file__).with_name("picker_template.html")


def load_zones(p: Path) -> dict:
    """미리 찾아 둔 상자를 씬 `cut` 시각으로 찾아 쓰게 담는다.

    ★ **번호가 아니라 `cut` 시각으로 짝짓는다.** 지정기·`remaster` 와 같은 규칙이다
      (±1.5초). 번호로 짝지었다가 채워 둔 시각 186개를 날린 적이 있다.
    """
    z = json.loads(p.read_text(encoding="utf-8-sig"))
    return {round(float(s.get("cut", -999)), 2): (s.get("boxes") or [])
            for s in (z.get("scenes") or [])}


def main():
    if len(sys.argv) < 2:
        sys.exit("쓰기: python make_picker.py <완성 mp4> [--zones 상자.json]")
    src = Path(sys.argv[1]).expanduser().resolve()
    # ★ `--zones` 를 주면 **그 상자를 밑그림으로 깐다.** 안 주면 예전처럼
    #   `propose()` 가 픽셀만 보고 찾는다 — 원장이 없는 옛 프로젝트의 자리다.
    pre = None
    if "--zones" in sys.argv:
        pre = load_zones(Path(sys.argv[sys.argv.index("--zones") + 1]).resolve())
        print(f"  미리 찾아 둔 상자를 씁니다 — {sum(len(v) for v in pre.values())}개")
    out = src.with_name(src.stem + "-마스크지정기.html")
    print("1/4 장면 전환 찾기")
    meta, cuts, times = scenes(src)
    print(f"  {len(cuts)}장")
    print("2/4 정지 화면 뽑기")
    tmp = src.parent / f"_{src.stem}-stills"; tmp.mkdir(exist_ok=True)
    imgs, boxes, dropped = [], [], 0
    for i, t in enumerate(times):
        p = tmp / f"s{i:02d}.png"
        if not p.exists():
            subprocess.run([rm.FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(src),
                            "-frames:v", "1", str(p), "-y"], check=True)
        arr = np.asarray(Image.open(p).convert("RGB"))
        if pre is not None:
            c = round(cuts[i], 2)
            hit = min(pre, key=lambda k: abs(k - c), default=None)
            keep = [dict(b) for b in (pre.get(hit) or [])]                 if hit is not None and abs(hit - c) <= 1.5 else []
            for b in keep:
                b.setdefault("kind", "text")
                b.setdefault("t", "")
        else:
            raw = propose(arr)
            keep = [b for b in raw if looks_text(arr, b)]
            for b in keep:
                b["kind"] = "text"      # ★ 상자는 글자에만 건다
                b["t"] = ""             # 등장~빛끝 (비면 자동)
            dropped += len(raw) - len(keep)
        boxes.append(keep)
        j = tmp / f"s{i:02d}.jpg"
        Image.fromarray(arr).resize((1120, 630), Image.LANCZOS).save(j, quality=68, optimize=True)
        imgs.append("data:image/jpeg;base64," + base64.b64encode(j.read_bytes()).decode())
    print(f"3/4 기본 상자 {sum(len(b) for b in boxes)}개 제안 "
          f"(그림 조각 {dropped}개는 걸러냈습니다)")
    ends = cuts[1:] + [meta["sec"]]
    data = {"W": meta["w"], "H": meta["h"], "video": src.name,
            "scenes": [{"i": i, "cut": round(cuts[i], 2), "still": round(times[i], 2),
                        "len": round(ends[i] - cuts[i], 2),
                        "boxes": boxes[i]} for i in range(len(cuts))]}
    print("4/4 HTML 쓰기")
    html = TPL.read_text(encoding="utf-8")
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__IMGS__", json.dumps(imgs))
    out.write_text(html, encoding="utf-8")
    print(f"완료 → {out}  ({out.stat().st_size / 1e6:.1f}MB)")
    print("  이 파일을 브라우저로 열어 상자를 고치고 zones.json 을 내려받으세요.")


if __name__ == "__main__":
    main()
