#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zones.json 채점기 — **손으로 그린 것을 정답지로 놓고 기계가 놓은 상자를 잰다.**

    python score_zones.py <생성 zones.json> <정답 zones.json> [--iou 0.5]

고치기 전에 재는 물건이 있어야 한다. 눈대중으로 프롬프트를 다듬으면 어제보다
나아졌는지 아무도 모른다.

★ **IoU 하나로 보지 않는다.** 사람이 그린 상자는 글자 둘레에 여유를 두고 있어서,
  잉크에 딱 붙은 정확한 상자도 IoU 가 0.5 밑으로 떨어진다. `remaster` 에게 정말
  필요한 것은 **글자를 덮느냐**다. 그래서 `덮음` 을 같이 낸다.

★ **합침에 너그럽다.** 사람은 라벨의 굵은 머리와 그 아래 설명을 합쳤다 갈랐다
  한다(실측: 어느 씬은 `437×171` 한 상자, 다음 씬은 `264×59`+`387×82` 두 상자).
  영상에 보이지도 않는 이 차이로 벌주면 엉뚱한 것을 쫓게 된다. 정답 상자마다
  **중심이 그 안에 든 생성 상자를 모두 합쳐** 놓고 잰다.

★ **제목과 라벨을 따로 낸다.** 제목은 화면(HTML)이 그린 것이라 DOM 에서 정확히
  얻고, 라벨은 그림에 구워진 것이라 비전이 찾는다. 섞어 놓으면 앞쪽의 만점이
  뒤쪽의 부진을 가린다.

표준 라이브러리만 쓴다 — 앱의 파이썬에서도, 도구의 파이썬에서도 돈다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

CUT_TOL = 1.5        # 씬을 짝짓는 창. 지정기·remaster 와 **같은 값**이어야 한다
TITLE_BAND = 0.10    # 화면 위 10% 는 덱이 그린 제목 자리


def load(p: Path) -> Dict[str, Any]:
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def area(b: Dict[str, Any]) -> int:
    return max(0, int(b["w"])) * max(0, int(b["h"]))


def inter(a: Dict[str, Any], b: Dict[str, Any]) -> int:
    ix = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return ix * iy


def iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    i = inter(a, b)
    u = area(a) + area(b) - i
    return i / u if u else 0.0


def centre_in(small: Dict[str, Any], big: Dict[str, Any]) -> bool:
    cx = small["x"] + small["w"] / 2
    cy = small["y"] + small["h"] / 2
    return (big["x"] <= cx <= big["x"] + big["w"]
            and big["y"] <= cy <= big["y"] + big["h"])


def union_box(bs: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if not bs:
        return None
    x0 = min(b["x"] for b in bs); y0 = min(b["y"] for b in bs)
    x1 = max(b["x"] + b["w"] for b in bs); y1 = max(b["y"] + b["h"] for b in bs)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def covered(gt: Dict[str, Any], props: List[Dict[str, Any]]) -> float:
    """정답 상자 넓이의 몇 %가 제안들에 덮였나 — 쪼개져 있어도 인정한다.

    넓이가 크지 않으니 줄 단위로 센다(numpy 없이).
    """
    a = area(gt)
    if not a:
        return 0.0
    hit = 0
    for yy in range(gt["y"], gt["y"] + gt["h"]):
        spans: List[Tuple[int, int]] = []
        for p in props:
            if p["y"] <= yy < p["y"] + p["h"]:
                x0 = max(gt["x"], p["x"])
                x1 = min(gt["x"] + gt["w"], p["x"] + p["w"])
                if x1 > x0:
                    spans.append((x0, x1))
        if not spans:
            continue
        spans.sort()
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s > cur_e:
                hit += cur_e - cur_s; cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        hit += cur_e - cur_s
    return hit / a


def pair_scenes(gen: Dict[str, Any], truth: Dict[str, Any]) -> List[Tuple[Any, Any]]:
    """씬은 **`cut` 시각으로** 짝짓는다 — 번호가 아니다.

    2026-08-16 에 번호로 짝지었다가 채워 둔 시각 186개가 통째로 날아갔다.
    다시 구운 영상은 씬이 하나 늘거나 줄어도 시각은 거의 그대로다.
    """
    gs = gen.get("scenes") or []
    out = []
    for t in (truth.get("scenes") or []):
        tc = float(t.get("cut", -999))
        hit = min(gs, key=lambda s: abs(float(s.get("cut", -999)) - tc), default=None)
        if hit is not None and abs(float(hit.get("cut", -999)) - tc) <= CUT_TOL:
            out.append((hit, t))
        else:
            out.append((None, t))
    return out


def score(gen_p: Path, truth_p: Path, thr: float, quiet: bool) -> Dict[str, Any]:
    gen, truth = load(gen_p), load(truth_p)
    H = int(truth.get("H") or 1080)
    band = H * TITLE_BAND

    tot = {"gt": 0, "gen": 0, "hit": 0, "cov": 0.0, "iou": 0.0, "spread": 0.0}
    split = {"제목": dict(gt=0, hit=0, cov=0.0), "라벨": dict(gt=0, hit=0, cov=0.0)}
    miss_scenes = 0

    for g, t in pair_scenes(gen, truth):
        gts = [b for b in (t.get("boxes") or []) if b.get("kind") != "cover"]
        gbs = list((g or {}).get("boxes") or [])
        if g is None and gts:
            miss_scenes += 1
        tot["gt"] += len(gts); tot["gen"] += len(gbs)
        for b in gts:
            # ① 쪼갬에 너그럽게 — 중심이 정답 안에 든 생성 상자들을 합쳐 하나로 본다
            near = [q for q in gbs if centre_in(q, b)]
            u = union_box(near)
            i = iou(b, u) if u else 0.0
            c = covered(b, gbs)
            # ② **합침에도 너그럽게.** 기계가 라벨 하나를 한 상자로 잡으면 그 상자
            #    하나가 사람의 상자 **둘**(굵은 머리 + 그 아래 설명)을 덮는다.
            #    ①만 보면 큰 상자의 중심이 작은 정답 안에 없어 0점이 된다.
            #    덮기만 하면 `remaster` 는 할 일을 다 한다 — 다만 아무거나 크게
            #    그려 놓고 점수를 따지 못하게 **3배까지만** 인정한다(번짐은 따로 센다).
            wrap = any(inter(q, b) >= 0.85 * area(b) and area(q) <= 3 * area(b)
                       for q in gbs)
            ok = i >= thr or wrap
            tot["hit"] += ok; tot["cov"] += c; tot["iou"] += i
            if u:
                tot["spread"] += area(u) / max(1, area(b))
            k = "제목" if b["y"] < band else "라벨"
            split[k]["gt"] += 1; split[k]["hit"] += ok; split[k]["cov"] += c
        if not quiet:
            cov = (sum(covered(b, gbs) for b in gts) / len(gts)) if gts else 1.0
            print(f"  씬{int(t.get('i', -1)):02d}  정답 {len(gts):3d}  생성 {len(gbs):3d}"
                  f"  덮음 {cov:5.1%}")

    n = max(1, tot["gt"])
    # 정밀도 — 생성 상자 중 어느 정답에도 안 걸린 것을 뺀다
    stray = 0
    for g, t in pair_scenes(gen, truth):
        gts = [b for b in (t.get("boxes") or []) if b.get("kind") != "cover"]
        for q in ((g or {}).get("boxes") or []):
            if q.get("kind") == "cover":
                continue                      # 가리기는 정답지에 없다 — 따로 본다
            if not any(inter(q, b) > 0.2 * area(q) for b in gts):
                stray += 1
    prec = 1.0 - stray / max(1, tot["gen"])

    print(f"\n{'':4}{'정답':>6} {'생성':>6} {'재현율':>8} {'덮음':>8} {'IoU':>7}")
    print(f"{'전체':4}{tot['gt']:6d} {tot['gen']:6d} {tot['hit']/n:8.1%} "
          f"{tot['cov']/n:8.1%} {tot['iou']/n:7.3f}")
    for k, v in split.items():
        m = max(1, v["gt"])
        print(f"{k:4}{v['gt']:6d} {'':6} {v['hit']/m:8.1%} {v['cov']/m:8.1%}")
    print(f"\n정밀도(헛 상자 {stray}개 뺀 값)  {prec:.1%}")
    print(f"번짐(정답 대비 몇 배)            {tot['spread']/n:.2f}배")
    if miss_scenes:
        print(f"⚠ 짝을 못 지은 씬 {miss_scenes}개 — cut 이 {CUT_TOL}초 넘게 어긋났습니다")

    return {"recall": tot["hit"] / n, "coverage": tot["cov"] / n,
            "iou": tot["iou"] / n, "precision": prec,
            "spread": tot["spread"] / n, "gt": tot["gt"], "gen": tot["gen"],
            "title_recall": split["제목"]["hit"] / max(1, split["제목"]["gt"])}


def main() -> None:
    ap = argparse.ArgumentParser(description="zones.json 을 정답지에 대고 채점한다")
    ap.add_argument("gen", type=Path, help="기계가 만든 zones.json")
    ap.add_argument("truth", type=Path, help="손으로 그린 정답 zones.json")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("-q", "--quiet", action="store_true", help="씬별 줄을 숨긴다")
    a = ap.parse_args()
    score(a.gen, a.truth, a.iou, a.quiet)


if __name__ == "__main__":
    main()
