# -*- coding: utf-8 -*-
"""목표 길이에 맞춰 **영상 구간을 자른다.**

발표를 10분으로 줄이려면 어디를 줄일지 정해야 한다. 텍스트 장은 이미 짧고,
길이를 잡아먹는 것은 **긴 화면 녹화**다. 237초짜리 하나가 4분을 먹는다.

    전체 = 영상 장(영상 길이) + 나머지 장(대본 길이)

그래서 영상만 줄이고 나머지는 남는 시간에 맞춘다.

★ **아무 데나 자르지 않는다.** 캡션 단계가 ✓ 로 골라 둔 컷이 그 영상에서 볼 만한
  순간이다. 그 시각을 **중심으로** 창을 잡는다 — 입력하는 장면, 결과가 뜬 장면처럼
  의미 있는 순간이 창 한가운데 오게 된다.

    .venv-app\\Scripts\\python tools\\fit_length.py 1 --min 10
    .venv-app\\Scripts\\python tools\\fit_length.py 1 --min 10 --dry
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from core import config, workspace as ws
from pipeline.registry import cached_data

MIN_CLIP = 8.0        # 이보다 짧게 자르면 무슨 화면인지 알아볼 수 없다
TEXT_MIN = 8.0        # 텍스트 장 최소
TEXT_MAX = 22.0       # 텍스트 장 최대 — 이보다 길면 화면이 안 넘어가 지루하다


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pid = int(args[0]) if args else 1
    target_min = 10.0
    if "--min" in sys.argv:
        target_min = float(sys.argv[sys.argv.index("--min") + 1])
    dry = "--dry" in sys.argv

    row = next((p for p in ws.list_projects() if p["id"] == pid), None)
    if not row:
        print(f"프로젝트 {pid} 없음")
        return 1
    slug = row["slug"]

    outline = cached_data(pid, slug, "s2b-outline") or {}
    slides = outline.get("slides") or []
    frames = (cached_data(pid, slug, "s1-frames") or {}).get("items", {})
    caps = (cached_data(pid, slug, "s3-caption") or {}).get("items", {})
    ov = ws.load_overrides(pid, slug)
    ov_slides = ov.setdefault("slides", {})

    live = [s for s in slides if not (ov_slides.get(str(s["no"])) or {}).get("drop")]
    vids = [s for s in live if s.get("video_id")]
    texts = [s for s in live if not s.get("video_id")]

    target = target_min * 60
    # 텍스트 장에 줄 시간을 먼저 잡는다 — 여기가 발표의 뼈대라 너무 줄이면 안 된다
    text_each = max(TEXT_MIN, min(TEXT_MAX, target * 0.55 / max(len(texts), 1)))
    text_total = text_each * len(texts)
    video_total = max(0.0, target - text_total)

    # 영상 장에 나눠 준다. 원본이 짧은 장은 원본을 넘길 수 없다.
    share: dict[str, int] = {}
    for s in vids:
        share[s["video_id"]] = share.get(s["video_id"], 0) + 1
    orig = {s["no"]: (frames.get(s["video_id"]) or {}).get("duration_sec", 0)
                     / share[s["video_id"]] for s in vids}
    orig_total = sum(orig.values())
    scale = min(1.0, video_total / orig_total) if orig_total else 1.0

    print(f"목표 {target_min:.0f}분 = {target:.0f}초")
    print(f"  텍스트 {len(texts)}장 × {text_each:.0f}초 = {text_total:.0f}초")
    print(f"  영상 {len(vids)}장 — 원본 {orig_total:.0f}초 → {orig_total * scale:.0f}초 "
          f"(×{scale:.2f})\n")

    for s in vids:
        no, vid = s["no"], s["video_id"]
        full = (frames.get(vid) or {}).get("duration_sec", 0)
        want = max(MIN_CLIP, round(orig[no] * scale, 1))
        if want >= full - 0.5:
            print(f"  {no:>3} {vid}  {full:.0f}초 — 그대로")
            continue

        # ★ ✓ 로 고른 컷 중 이 장 몫을 중심으로 창을 잡는다
        picked = [c for c in (caps.get(vid, {}).get("frames") or []) if c.get("selected")]
        mine = [x for x in vids if x["video_id"] == vid]
        k = mine.index(s)
        center = (picked[k]["t_sec"] if k < len(picked)
                  else full * (k + 0.5) / len(mine))
        start = max(0.0, min(full - want, center - want / 2))
        end = round(start + want, 1)
        start = round(start, 1)

        cur = ov_slides.setdefault(str(no), {})
        cur["clip"] = {"start": start, "end": end, "speed": 1, "cuts": []}
        src = f"컷 {center:.0f}초" if k < len(picked) else "균등"
        print(f"  {no:>3} {vid}  {full:.0f}초 → {start:.0f}~{end:.0f}초 "
              f"({want:.0f}초, {src} 중심)")

    if dry:
        print("\n--dry — 저장하지 않았습니다")
        return 0
    ov["target_min"] = int(target_min)
    ws.save_overrides(pid, slug, ov)
    est = orig_total * scale + text_total
    print(f"\n저장했습니다 · 예상 {est / 60:.1f}분")
    print("이어서:  tools\\run_stage.py 1 s6-script --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
