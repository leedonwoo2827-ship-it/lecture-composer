# -*- coding: utf-8 -*-
"""발음 교정표 — **사람이 손으로 정한 읽는 법**만 모아 넘긴다.

이 파일이 있는 이유. 발음은 두 번 정해진다.

    ① 자동   `core/honorific.for_speech()` — 숫자·퍼센트·어미. 규칙이라 코드에 있다
    ② 손      화면에서 사람이 고친 것 — `Q1 → 큐원`, `m1 → 엠원`, `z-점수 → 제트 점수`

②는 **코드에 없고 이 프로젝트 폴더에만 있다.** 다음 과목을 쓰는 사람은 그것을
모르니 같은 자리에서 같은 고민을 다시 한다. 그래서 ②만 뽑아 표로 낸다 — 대본을
쓰는 사람에게 넘기면 애초에 읽히는 대로 써 올 수 있다.

★ **낱말 단위로 뽑는다.** 문장을 그대로 나열하면 사람이 다시 눈으로 비교해야
  한다. `difflib` 로 바뀐 조각만 집어 내면 `Q1 → 큐원` 한 줄이 남는다. 이 표
  하나가 이 파일의 값 전부다.

★ 자동분(①)은 **참고**로 뒤에 붙인다. 앞에 두면 손으로 정한 것이 숫자 변환
  수십 줄에 묻힌다 — 넘기려는 것은 ②다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

# 낱말로 자른다. 공백으로만 자르면 「Q1과」 가 통째로 남아 「큐원과」 와 짝이
# 맞는데, 그게 오히려 읽기 좋다 — 조사까지 붙은 채로 보여야 어디를 고쳤는지 안다.
_TOK = re.compile(r"\S+")


def _tokens(s: str) -> List[str]:
    return _TOK.findall(s or "")


def _bare(s: str) -> str:
    """공백을 뗀 알맹이. 「띄어쓰기만 다른 짝」을 걸러내는 데 쓴다."""
    return re.sub(r"\s+", "", s)


def _pairs(before: str, after: str) -> List[Tuple[str, str]]:
    """두 문장에서 **바뀐 조각만** 짝지어 낸다.

    ★ `replace` 만 쓴다. `insert`/`delete` 는 문장을 다듬은 것(군말 추가·삭제)이라
      「이 말은 이렇게 읽는다」 가 아니다 — 발음표에 섞으면 표가 못 쓰게 된다.
    """
    a, b = _tokens(before), _tokens(after)
    out: List[Tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if tag != "replace":
            continue
        # 한쪽이 훨씬 길면 문장을 고친 것이다 — 낱말 대응이 아니다
        if abs((i2 - i1) - (j2 - j1)) > 2:
            continue
        out.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return out


def _strip_affix(before: str, after: str) -> Tuple[str, str]:
    """양쪽에 **똑같이 붙어 있는 앞뒤 글자를 벗긴다.**

        M1에   → 엠원에     ⇒  M1 → 엠원
        M1이고, → 엠원이고,  ⇒  M1 → 엠원

    ★ 조사 때문이다. 안 벗기면 `M1에`·`M1은`·`M1을`·`M1이고,` 가 **네 줄**로
      잡혀서, 규칙 하나뿐인 표가 열 줄로 부푼다(실측: 23장에서 `M1` 하나가
      다섯 줄이었다). 받는 사람이 필요한 것은 `M1 → 엠원` 한 줄이다.

    ★ **두 글자는 남긴다.** 한 글자까지 벗기면 `내적 → 내쩍` 이 `적 → 쩍` 이
      되어 어느 낱말 얘기인지 사라진다(실측). 낱말이 보여야 표가 쓸모 있다.
    """
    keep = 2
    b, a = before, after
    while (len(b) > keep and len(a) > keep) and b[-1] == a[-1]:
        b, a = b[:-1], a[:-1]
    while (len(b) > keep and len(a) > keep) and b[0] == a[0]:
        b, a = b[1:], a[1:]
    return b.strip(), a.strip()


def _table(rows: List[Tuple[str, str, List[int]]], indent: str = "  ") -> List[str]:
    """`자막 → 발음   (3·17·42장)` 꼴로 줄을 맞춘다."""
    if not rows:
        return []
    w = min(38, max(len(r[0]) for r in rows))
    out = []
    for before, after, nos in rows:
        where = "·".join(str(n) for n in nos[:8]) + ("…" if len(nos) > 8 else "")
        out.append(f"{indent}{before.ljust(w)}  →  {after}"
                   + (f"      ({where}장)" if nos else ""))
    return out


def _collect(items: List[Tuple[int, str, str]],
             *, drop: set | None = None) -> List[Tuple[str, str, List[int]]]:
    """장별 (before, after) 를 낱말 짝으로 모아 **중복을 접는다.**

    같은 짝이 여러 장에서 나오면 그것이 이 덱의 규칙이다 — 장 번호를 뒤에 달아
    두면 받는 사람이 "한 번 나온 예외인지 통용되는 규칙인지" 를 안다.
    """
    seen: Dict[Tuple[str, str], List[int]] = {}
    for no, before, after in items:
        for raw in _pairs(before, after):
            pair = _strip_affix(*raw)
            if pair[0] == pair[1] or not pair[0] or not pair[1]:
                continue
            # ★ **공백만 다른 것은 규칙이 아니다.** `세 번 → 세번` 같은 짝이
            #   낱말 규칙 자리에 앉으면, 정작 봐야 할 `M1 → 엠원` 이 그만큼
            #   밀려난다(실측: 1과목 10줄 중 3줄이 이것이었다).
            if _bare(pair[0]) == _bare(pair[1]):
                continue
            if drop and pair in drop:
                continue          # 코드가 자동으로 하는 것 — 사람이 정한 게 아니다
            seen.setdefault(pair, [])
            if no not in seen[pair]:
                seen[pair].append(no)
    # 많이 나온 것 먼저 — 규칙이 예외보다 위에 있어야 읽힌다
    return sorted(((b, a, sorted(nos)) for (b, a), nos in seen.items()),
                  key=lambda r: (-len(r[2]), r[0]))


def report(*, deck_title: str, rows: List[Dict[str, Any]]) -> str:
    """교정표 한 장.

    `rows` 는 장마다 `{no, title, srt, auto, said, hand}`:
        srt   자막 원문
        auto  `for_speech()` 가 낸 것 (자동)
        said  실제로 읽은 것
        hand  사람이 손으로 고친 장인가
    """
    hand_rows = [r for r in rows if r.get("hand")]

    # ★ 기준선은 **자막**이다(자동 결과가 아니다). 받는 사람이 쓰는 것은 자막이고,
    #   그가 알아야 하는 것은 「내가 `M1` 이라고 쓰면 `엠원` 으로 읽힌다」다.
    #   자동 결과를 기준선으로 삼으면 왼쪽 칸에 `M일` 이 나와, 정작 타이핑할
    #   글자가 표에 없다.
    # ★ 그러면 숫자 변환이 통째로 섞여 든다 — 그래서 **자동분을 뺀다.** 자막에서
    #   자동으로도 그렇게 바뀌는 짝이면 사람이 정한 것이 아니다.
    auto_pairs = _collect([(r["no"], r["srt"], r["auto"])
                           for r in rows if r.get("auto")])
    auto_keys = {(b, a) for b, a, _ in auto_pairs}
    hand_pairs = _collect([(r["no"], r["srt"], r["said"]) for r in hand_rows],
                          drop=auto_keys)

    L: List[str] = []
    L.append(f"발음 교정표 — {deck_title}")
    L.append("=" * 60)
    L.append("")
    L.append("이 덱에서 **사람이 손으로 정한 읽는 법**입니다. 대본·문제를 쓰실 때")
    L.append("아래대로 읽히도록 써 주시면 발음을 다시 고칠 일이 없습니다.")
    L.append("")
    L.append(f"장 {len(rows)}개 중 손으로 고친 장 {len(hand_rows)}개 "
             f"· 낱말 규칙 {len(hand_pairs)}개")
    L.append("")

    L.append("─" * 60)
    L.append("1. 낱말 대응표  ← 이것만 보시면 됩니다")
    L.append("─" * 60)
    if hand_pairs:
        L.append("")
        L.extend(_table(hand_pairs))
    else:
        L.append("")
        L.append("  손으로 고친 발음이 없습니다.")
    L.append("")

    L.append("─" * 60)
    L.append("2. 장별 내역  ← 문맥이 필요할 때만")
    L.append("─" * 60)
    for r in hand_rows:
        L.append("")
        L.append(f"[{r['no']}장] {r.get('title') or ''}")
        L.append(f"  자막  {r['srt']}")
        if r.get("auto") and r["auto"] != r["srt"]:
            L.append(f"  자동  {r['auto']}")
        L.append(f"  발음  {r['said']}")
    if not hand_rows:
        L.append("")
        L.append("  (없음)")
    L.append("")

    L.append("─" * 60)
    L.append("3. 참고 — 코드가 자동으로 바꾸는 것 (손댈 필요 없습니다)")
    L.append("─" * 60)
    L.append("")
    L.append("  숫자·퍼센트·어미는 `core/honorific.py` 가 알아서 소리로 바꿉니다.")
    L.append("  아래는 이번 덱에서 실제로 그렇게 바뀐 예입니다.")
    L.append("")
    L.extend(_table(auto_pairs[:40]) or ["  (없음)"])
    if len(auto_pairs) > 40:
        L.append(f"  … 그 밖에 {len(auto_pairs) - 40}개")
    L.append("")
    return "\n".join(L) + "\n"


def build(pid: int, slug: str, *, title: str) -> str:
    """장별 자료를 모아 교정표 한 장으로. **부르는 자리가 둘이라 여기 한 벌만 둔다.**

        덱 화면의 「발음 교정표」 버튼   손편집을 끝낸 그 자리에서 뽑고 싶을 때
        영상 렌더링(S12) 끝            누를 것 없이 저절로 나오게

    둘이 각자 자료를 모으면 표가 갈린다 — 같은 프로젝트에서 두 파일의 내용이
    다르면 어느 쪽을 넘겨야 하는지가 남는다.

    ★ 어느 장을 사람이 고쳤나는 **오버라이드가 답이다.** 실제 발음과 자동 결과를
      비교해 짐작하면, `for_speech()` 가 나중에 바뀐 장까지 손편집으로 잡힌다.
    """
    from core import honorific, workspace as ws
    from pipeline.registry import cached_data, narration_of

    now = narration_of(pid, slug)
    ov_slides = (ws.load_overrides(pid, slug).get("slides") or {})
    titles = {str(s["no"]): (s.get("title") or "")
              for s in ((cached_data(pid, slug, "s2b-outline") or {}).get("slides") or [])}

    rows: List[Dict[str, Any]] = []
    for key in sorted(now, key=lambda k: int(k)):
        cur = now[key]
        srt = (cur.get("srt_text") or "").strip()
        said = (cur.get("text") or "").strip()
        if not srt and not said:
            continue
        hand = "text" in ((ov_slides.get(key) or {}).get("narration") or {})
        rows.append({"no": int(key), "title": titles.get(key, ""), "srt": srt,
                     "auto": honorific.for_speech(srt) if srt else "",
                     "said": said or srt, "hand": bool(hand and said)})
    return report(deck_title=title, rows=rows)


def n_hand(text: str) -> int:
    """낸 표에서 「손으로 고친 장」 수를 되읽는다 — 로그·토스트에 쓴다."""
    m = re.search(r"손으로 고친 장 (\d+)개", text)
    return int(m.group(1)) if m else 0
