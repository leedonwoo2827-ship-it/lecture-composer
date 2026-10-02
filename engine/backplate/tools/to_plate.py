# -*- coding: utf-8 -*-
"""이미 있는 지시문(fmt 10) → 배경판(fmt 11)로 바꾼다.

    python tools/to_plate.py <이미지프롬프트.json> [-n 31,30,29] [-o 나갈.json]

★ 왜 필요한가. 11판 지시문을 처음부터 다시 쓰려면 s3a 를 다시 돌려야 하고
  그건 Claude 호출이라 돈이 든다. 그런데 10판 지시문에는 배경·구도·색/톤이
  **이미 다 들어 있고**, 11판이 달라지는 것은 라벨을 인쇄하느냐 하나뿐이다.
  그래서 라벨 줄만 걷어내고 나머지는 **한 글자도 건드리지 않는다** —
  톤앤매너가 그대로 이어지는지 보려면 이 편이 오히려 정확하다.

★ 자리는 버리지 않는다. 「라벨 1 (오른쪽 위)」 의 **자리 이름만** 뽑아
  「여기를 비워라」로 바꾼다. 그림이 비운 자리와 화면이 글을 얹는 자리가
  같아야 하기 때문이다(pipeline/s3a_imgprompt.py 의 PLACE_XY).
"""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

_LABEL = re.compile(r"^라벨 \d+ \(([^)]+)\):")
_SUB = re.compile(r'그 아래 작게 "([^"]*)"')
_HEAD = re.compile(r'굵게 "([^"]*)"')

# ★ 라벨만 뺀다. 장면 속 글자(책등·서류철 탭·분류 라벨)는 **남긴다** —
#   다 지웠더니 정보를 담은 그림이 빈 사무실 삽화가 됐다
#   (2026-09-18).
#   깨지던 것은 긴 문장인 콜아웃 라벨이지 사물에 붙은 짧은 낱말이 아니다.
_NO_TEXT = ("글자: **라벨(소제목+설명)을 그림에 인쇄하지 마라.** 그 글은 화면이 "
            "진짜 텍스트로 얹는다 — 네가 그리면 두 겹으로 겹친다. "
            "제목·헤드라인도 넣지 않는다")
# ★ 장면 속 글자는 **남긴다.** 다 지웠더니 정보를 담은 그림이 빈 사무실
#   삽화가 됐다(2026-09-18). 깨지던 것은
#   긴 문장인 콜아웃 라벨이지 사물에 붙은 짧은 낱말이 아니다.
_IN_SCENE = ("다만 **장면 속 사물에 붙은 글자는 넣어라** — 책등의 과목명, 서류철 "
             "탭, 분류 라벨, 게시물, 표지의 짧은 낱말 같은 것이다. 그것이 있어야 "
             "장면이 정보를 담은 그림이 된다. 없으면 빈 사무실 삽화가 된다. "
             "다만 **짧은 낱말**로만 두어라(두세 어절 이내) — 설명하는 긴 문장은 "
             "쓰지 마라. 길수록 글자가 깨진다")
_NO_BOX = ("비운 자리에 상자·카드·둥근 판·테두리·말풍선 같은 **글자 담을 그릇을 "
           "미리 그리지 마라.** 바탕이 그대로 드러나 있어야 한다")
_COORD = ("비울 자리(2칸 안의 좌표): 「위」라고 적은 자리는 y=150~330, 「아래」라고 "
          "적은 자리는 y=730~1010 이다. 그 띠에는 바탕만 두고 주요 사물·굵은 선·"
          "짙은 무늬를 두지 마라 — 화면이 그 위에 글자를 얹는다. 「아래」는 1칸이 "
          "아니라 **2칸의 아래쪽**을 뜻한다")


def convert(prompt: str) -> Tuple[str, List[Dict[str, str]]]:
    """(배경판 지시문, 뽑아낸 라벨 목록)."""
    labels: List[Dict[str, str]] = []
    out: List[str] = []
    for ln in prompt.splitlines():
        m = _LABEL.match(ln)
        if m:                                    # 라벨 줄 — 문구는 화면이 그린다
            h, s = _HEAD.search(ln), _SUB.search(ln)
            labels.append({"place": m.group(1),
                           "head": h.group(1) if h else "",
                           "sub": s.group(1) if s else ""})
            continue
        if ln.startswith("라벨은 **글자만**") or ln.startswith("글자 크기:"):
            continue                             # 그릴 글자가 없으니 규칙도 없다
        if ln.startswith("라벨 자리(2칸 안의 좌표):"):
            out.append(_COORD)
            continue
        out.append(ln)

    ins: List[str] = []
    if labels:
        # ★ 「비워라」가 아니라 「한가하게 두라」다 — s3a_imgprompt 의 같은 주석 참고.
        ins.append("라벨 자리(글자가 얹힐 곳): "
                   + " · ".join(f"「{l['place']}」" for l in labels)
                   + f" — 모두 {len(labels)}곳이다. **화면은 네 가장자리까지 꽉 "
                     "채운 채로**, 이 자리들만 잔무늬·작은 사물·복잡한 결이 없는 "
                     "**한가한 면**이 되게 하라 — 큰 면, 고른 벽, 넓은 바닥, 열린 "
                     "하늘 같은 것이다. 비우라는 말이 아니다. 장면을 가운데로 "
                     "몰거나 가장자리를 비우면 화면이 헐거워진다. 화면이 이 자리에 "
                     "글자를 얹으므로 **글자는 네가 그리지 않는다**")
    ins += [_NO_TEXT, _IN_SCENE, _NO_BOX]

    # 「산출물 규격」 바로 앞에 끼운다 — 규격은 늘 마지막 줄이어야 한다
    try:
        i = next(i for i, x in enumerate(out) if x.startswith("산출물 규격:"))
    except StopIteration:
        i = len(out)
    return "\n".join(out[:i] + ins + out[i:]), labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("-n", "--nums", default="", help="쉼표로 고른 슬라이드 번호")
    ap.add_argument("-o", "--out", type=Path, default=None)
    a = ap.parse_args()

    doc: Dict[str, Any] = json.load(io.open(a.src, encoding="utf-8"))
    want = {int(x) for x in a.nums.split(",") if x.strip()} if a.nums else None
    rows = [r for r in doc.get("prompts", []) if want is None or r.get("n") in want]
    if not rows:
        raise SystemExit("고른 번호에 해당하는 항목이 없습니다.")

    for r in rows:
        r["prompt"], labels = convert(r["prompt"])
        r["labels"] = labels
        leak = [l["head"] for l in labels if l["head"] and l["head"] in r["prompt"]]
        print(f"  {r['n']:>3}번  라벨 {len(labels)}개  "
              f"자리 {[l['place'] for l in labels]}  "
              f"{'⚠ 문구 남음 ' + str(leak) if leak else '문구 안 남음'}")

    doc["prompts"] = rows
    doc["count"] = len(rows)
    doc["_fmt"] = 11
    out = a.out or a.src.with_name(a.src.stem + "-배경판.json")
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{out}  ({len(rows)}장)")


if __name__ == "__main__":
    main()
