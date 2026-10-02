# -*- coding: utf-8 -*-
"""이미 만든 장(10판)을 배경판(11판)으로 옮긴다 — **Claude 를 다시 부르지 않고.**

    python tools/plate_migrate.py <프로젝트폴더> [--apply]

★ 왜 되는가. 10판 지시문 안에 이미 라벨이 **한 줄씩 적혀 있다** —
    라벨 1 (오른쪽 위): 굵게 "튜터의 구조" / 그 아래 작게 "…"
  11판이 필요로 하는 것(문구·설명줄·자리)이 전부 그 줄에 있다. 그러니
  다시 물어볼 필요 없이 **읽어 내면 된다.** s3a 를 다시 돌리면 장당 돈이 든다.

★ 무엇을 바꾸나.
    09_이미지/원장.json  각 칸에 label_subs·label_places 를 채우고 fmt=11,
                         prompt 를 배경판 지시문으로 갈아끼운다
    project.json         image_fit: "full" → "plate"
  그림 파일은 **건드리지 않는다.** 기존 그림에는 글자가 구워져 있으므로,
  배경판으로 다시 구울 때까지는 화면에 글이 두 겹으로 보인다 — 그게 정상이다.

★ `--apply` 없이 돌리면 무엇이 바뀌는지만 보여 준다.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.to_plate import convert  # noqa: E402


def _ledger_path(proj: Path) -> Path:
    for p in (proj / "09_이미지" / "원장.json",
              proj / "09_이미지" / "bak" / "원장.json"):
        if p.is_file():
            return p
    raise SystemExit("원장.json 을 찾지 못했습니다.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", type=Path)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    lp = _ledger_path(a.proj)
    book = json.load(io.open(lp, encoding="utf-8"))
    by_id = book.get("by_id") or {}

    moved, skipped = 0, 0
    for did, e in by_id.items():
        prompt = (e.get("prompt") or "").strip()
        if not prompt:
            skipped += 1
            continue
        new_prompt, labels = convert(prompt)
        if not labels:
            # 라벨 줄이 없는 칸 — 썸네일·표지처럼 원래 글자가 없는 장이다
            skipped += 1
            continue
        heads = [l["head"] for l in labels]
        e["label_heads"] = heads
        e["label_subs"] = [l["sub"] for l in labels]
        e["label_places"] = [l["place"] for l in labels]
        # label_says 가 짧으면 0 으로 채운다 — 시각은 나중에 큐에서 붙는다
        says = list(e.get("label_says") or [])
        e["label_says"] = (says + [0] * len(heads))[:len(heads)]
        e["prompt"] = new_prompt
        e["fmt"] = 11
        moved += 1
        if moved <= 3:
            print(f"  {did}: 라벨 {len(labels)}개 "
                  f"{[l['place'] for l in labels]}")

    pj = a.proj / "project.json"
    proj = json.load(io.open(pj, encoding="utf-8"))
    old_fit = proj.get("image_fit")

    print(f"\n옮길 장 {moved}개 · 건너뛴 칸 {skipped}개")
    print(f"image_fit: {old_fit} → plate")

    if not a.apply:
        print("\n(미리보기입니다. 실제로 바꾸려면 --apply)")
        return

    shutil.copy2(lp, lp.with_suffix(".json.bak"))
    shutil.copy2(pj, pj.with_suffix(".json.bak"))
    lp.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
    proj["image_fit"] = "plate"
    pj.write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n적용했습니다. 원본은 .bak 으로 남겼습니다.")
    print("다음: s8-assemble 을 다시 돌려야 deck.json 에 라벨이 실립니다.")


if __name__ == "__main__":
    main()
