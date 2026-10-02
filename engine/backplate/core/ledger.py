# -*- coding: utf-8 -*-
"""이미지 프롬프트 원장 — **원고를 고쳐도 그려 둔 그림이 안 버려지게.**

이 파일이 있는 이유는 요구사항 한 줄이다(2026-08-14):

    "페이지 셋팅을 다 할 때 수정이 있다면 json 파일을 다시 불러와서 다시
     만들어야 할 수도 있습니다. 이게 굳이 html 로 보였다가 이미지 작업을
     하는 이유입니다."

원고를 눈으로 보고 고친 **뒤에** 그림을 만든다. 그런데 그림 파일은 슬라이드
번호로 이름이 붙는다(`005.png` = 5번 장). 앞에 장이 하나 끼어들면 번호가 전부
한 칸씩 밀리고, `005.png` 는 남의 장 그림이 된다. 예순 장짜리 원고에서 두 번째
장을 하나 늘리면 쉰여덟 장의 그림이 통째로 어긋난다.

그래서 **번호가 아니라 이름표(`data_id`)에 프롬프트를 매단다.** 번호는 내보낼
때만 매긴다. 규약 5-① 이 「안 바뀌는 이름표」를 요구한 것이 정확히 이 문제 때문이고,
여기서는 있으면 좋은 것이 아니라 **뼈대**다.

원장 한 칸:

    "sam-19-03": {
        "prompt": "…", "title": "…", "level": "이해", "type": "photo",
        "keywords": ["…"],
        "body_hash": "…",     그 장 몸통의 해시. 같으면 프롬프트를 안 다시 만든다
        "last_n": 7,          직전에 내보낼 때 매긴 번호. 이름 바꾸기 표의 근거
        "dirty": true,        내보낸 뒤에 프롬프트가 새로 만들어졌다 → 부족분에 넣는다
        "made_at": "…",
        "retired": false      원고에서 빠진 장. 지우지 않는다 — 되살아나면 재사용
    }

★ **번호가 밀린 것과 다시 그려야 하는 것은 다르다.** 처음엔 번호가 바뀐 장을 전부
  부족분에 넣었는데, 앞쪽 장 하나를 빼자 스물네 장이 「다시 그릴 것」으로 나왔다.
  그 스물네 장은 내용이 그대로라 **이름만 바꾸면 되는** 장이다. 그래서 「다시
  만들었나」(`dirty`)를 따로 들고 다닌다 — 번호는 `last_n` 이, 내용은 `dirty` 가 답한다.

★ **지우지 않는다.** 장을 뺐다가 되살리는 일이 실제로 있고, 그때 프롬프트가
  그대로 돌아와야 이미 그린 그림도 같이 살아난다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Tuple


def body_hash(blocks: List[Dict[str, Any]], title: str = "") -> str:
    """그 장 몸통의 지문. **화면에 뜨는 글자만** 넣는다.

    제목과 줄의 글을 합쳐 해시한다. 줄 순서가 바뀌면 다른 값이 나오는데, 그게 맞다
    — 순서가 바뀌면 그 장이 말하는 것도 달라진다.
    """
    payload = json.dumps(
        {"t": (title or "").strip(),
         "b": [f"{b.get('kind')}:{(b.get('html') or '').strip()}" for b in blocks or []]},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def plan(ledger: Dict[str, Any], slides: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """무엇을 새로 만들고 무엇을 그대로 쓸까. `(새로, 그대로)` 를 이름표로 돌려준다.

    판단은 두 가지뿐이다.
      원장에 없다        → 새 장이다. 만든다
      몸통 해시가 다르다 → 내용이 바뀌었다. 다시 만든다
    나머지는 전부 그대로 쓴다 — **값을 아끼려는 게 아니라, 같은 장의 프롬프트가
    이유 없이 바뀌면 이미 그린 그림과 어긋나기 때문이다.**
    """
    by_id: Dict[str, Any] = ledger.get("by_id") or {}
    make: List[str] = []
    keep: List[str] = []
    for s in slides:
        did = s["data_id"]
        old = by_id.get(did)
        if old and not old.get("retired") and old.get("body_hash") == s.get("body_hash") \
                and (old.get("prompt") or "").strip():
            keep.append(did)
        else:
            make.append(did)
    return make, keep


def apply(ledger: Dict[str, Any], made: Dict[str, Dict[str, Any]],
          slides: List[Dict[str, Any]]) -> Dict[str, Any]:
    """새로 만든 것을 원장에 얹고, 원고에서 빠진 장을 물러남으로 표시한다."""
    by_id: Dict[str, Any] = dict(ledger.get("by_id") or {})
    now = datetime.now().isoformat(timespec="seconds")
    live = {s["data_id"] for s in slides}

    for s in slides:
        did = s["data_id"]
        cur = dict(by_id.get(did) or {})
        cur["retired"] = False
        cur["title"] = s.get("title") or cur.get("title") or ""
        cur["body_hash"] = s.get("body_hash") or cur.get("body_hash") or ""
        if did in made:
            cur.update({k: v for k, v in made[did].items() if v not in (None, "")})
            cur["made_at"] = now
            # 내보내기가 이 표시를 보고 부족분을 고른다. 지우는 것은 `stamp()` 다.
            cur["dirty"] = True
        by_id[did] = cur

    for did, cur in by_id.items():
        if did not in live:
            cur["retired"] = True                 # 지우지 않는다. 되살아날 수 있다

    return {"by_id": by_id}


def number_at(ledger: Dict[str, Any],
              pairs: List[Tuple[str, int]]) -> Dict[str, Any]:
    """번호를 **덱에게 받아** 적고, 밀린 것의 이름 바꾸기 표를 낸다.

    돌려주는 값 넷은 **서로 다른 질문에 답한다.** 섞으면 안 된다.

        n_of    {이름표: 이번 번호}
        renames [(옛 번호, 새 번호, 이름표)] — 번호가 바뀌었다 → **이름만 바꾸면 된다**
        fresh   한 번도 안 내보낸 장          → 새로 그려야 한다
        dirty   프롬프트가 다시 만들어진 장    → 다시 그려야 한다

    ★ `renames` 는 부족분이 **아니다.** 앞쪽 장 하나를 빼면 뒤 스물네 장의 번호가
      전부 밀리는데, 그 스물네 장은 내용이 그대로다. 예전에 이것을 부족분에 넣었더니
      "장 하나 뺐는데 스물네 장을 다시 그리라"는 말이 나왔다 — 이 앱이 막으려던
      바로 그 일이다.

    ★ 번호를 **세지 않고 받는다.** 그림이 들어가는 장이 2번부터 죽 이어지는 덱
      (책 원고 한 편이 통째로 들어온 덱)에서는 세도 맞지만, 영상·글·그림이 섞인
      덱에서는 그림 장 번호가 띄엄띄엄하다(2·5·6·9…). 세면 통째로 밀린다.
      `number(start=2)` 는 이 함수의 특수한 경우다.
    """
    by_id: Dict[str, Any] = ledger.get("by_id") or {}
    n_of: Dict[str, int] = {}
    renames: List[Tuple[int, int, str]] = []
    fresh: List[str] = []
    dirty: List[str] = []

    for did, n in pairs:
        n = int(n)
        n_of[did] = n
        e = by_id.get(did) or {}
        old = e.get("last_n")
        if not old:
            fresh.append(did)
        else:
            if int(old) != n:
                renames.append((int(old), n, did))
            if e.get("dirty"):
                dirty.append(did)
    return {"n_of": n_of, "renames": renames, "fresh": fresh, "dirty": dirty}


def number(ledger: Dict[str, Any], order: List[str], *, start: int = 2) -> Dict[str, Any]:
    """번호를 **순서대로 세어** 매긴다 — 덱이 번호를 안 알려줄 때.

    `start=2` 인 이유: 1번은 표지다(조립할 때 자동으로 붙는다). 그래서 원고의 첫
    장이 2번이 되고, 발표 쇼케이스에서 세는 번호와 같아진다. 표지를 안 붙이는
    흐름을 만들면 이 값을 같이 바꿔야 한다 — **여기가 어긋나면 그림이 통째로
    한 칸씩 밀린다.**

    번호를 이미 아는 쪽에서는 `number_at()` 을 쓸 것.
    """
    return number_at(ledger, [(did, start + i) for i, did in enumerate(order)])


def stamp(ledger: Dict[str, Any], n_of: Dict[str, int]) -> Dict[str, Any]:
    """번호를 확정하고 「다시 만들었음」 표시를 지운다.
    **내보내기가 실제로 끝난 뒤에** 부를 것.

    ★ 번호를 매기자마자 찍으면, 파일을 쓰다 실패했을 때 원장에는 새 번호가 남고
      디스크의 그림은 옛 번호로 있다. 그다음 내보내기는 「바뀐 것 없음」 이라
      말하고, 이름 바꾸기 표가 영영 안 나온다.
    """
    by_id: Dict[str, Any] = dict(ledger.get("by_id") or {})
    for did, n in n_of.items():
        if did in by_id:
            by_id[did] = {**by_id[did], "last_n": int(n), "dirty": False}
    return {"by_id": by_id}
