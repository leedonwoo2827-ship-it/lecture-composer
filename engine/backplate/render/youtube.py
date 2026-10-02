# -*- coding: utf-8 -*-
"""유튜브에 올릴 때 붙여 넣을 글 — **제목 · 설명란 · 타임스탬프 · 태그.**

영상 파일만 나오면 그다음이 막힌다. 유튜브 올리기 화면은 제목 칸, 설명 칸,
태그 칸을 요구하는데 그걸 매번 사람이 새로 쓴다. 덱에는 그 재료가 이미 다 있다 —
장 제목이 곧 챕터고, `start_sec` 이 곧 타임스탬프다.

★ **타임스탬프는 유튜브 규칙을 지켜야 붙는다.** 첫 줄이 `0:00` 이어야 하고, 최소
  세 개, 각 구간이 10초 이상이어야 챕터로 인식된다. 안 지키면 그냥 글자로 남는다.
  10초를 못 채운 장은 앞 챕터에 합친다 — 장 수와 챕터 수가 꼭 같을 이유는 없다.

★ 챕터 이름은 **그림에 박힌 헤드라인**을 먼저 쓴다. 그게 제일 짧고 세다(원장에
  있다). 없으면 장 제목에서 앞 순번을 뗀다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 챕터로 인정받는 최소 간격 — 유튜브 규칙
MIN_GAP = 10.0


def mmss(t: float) -> str:
    t = int(round(max(0.0, t)))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _eul(word: str) -> str:
    """받침을 보고 `을`/`를` 을 고른다. 「개요를」·「제19장을」.

    ★ 이 한 글자를 안 맞추면 「제19장를 정리했습니다」가 설명란 첫 줄에 뜬다.
      거기가 유튜브 목록에 미리보기로 나오는 자리라 눈에 제일 잘 띈다.
    """
    w = (word or "").rstrip()
    if not w:
        return "을"
    ch = w[-1]
    if "가" <= ch <= "힣":
        return "을" if (ord(ch) - 0xAC00) % 28 else "를"
    # 숫자로 끝나면 읽는 소리로 판단한다 — 1·3·6·7·8·0 은 받침이 있다
    if ch.isdigit():
        return "을" if ch in "136780" else "를"
    # 영문자는 **알파벳 이름**을 읽은 소리로 본다 — `GDP`=지디피(받침 없음),
    # `AS`=에이에스(받침 있음). 이걸 안 보면 「GDP을」이 나온다.
    if ch.isalpha():
        #   받침이 있는 것은 L(엘)·M(엠)·N(엔)·R(알) 넷뿐이다
        return "을" if ch.upper() in "LMNR" else "를"
    return "을"


def _headline(s: Dict[str, Any], led: Dict[str, Any]) -> str:
    """그 장을 한 줄로. **그림에 박힌 제목** → 장 제목 순.

    ★ 프롬프트 꼴이 판마다 달라져서 두 이름을 다 본다 — 4판까지는 `헤드라인`,
      5판부터는 `제목` 이다(`pipeline/s3a_imgprompt.py` 의 `PROMPT_FMT`).
      옛 판으로 만든 프로젝트의 유튜브 글이 갑자기 비면 안 된다.
    """
    e = led.get(s.get("data_id") or "") or {}
    m = re.search(r'(?:헤드라인|제목).*?:\s*"(.*?)"', e.get("prompt") or "")
    if m and m.group(1).strip():
        return m.group(1).strip()
    return re.sub(r"^\s*\d+(\.\d+)*[.\s]\s*", "", s.get("title") or "").strip()


def chapters(slides: List[Dict[str, Any]], led: Dict[str, Any]) -> List[tuple]:
    out: List[tuple] = []
    last = -MIN_GAP
    for s in slides:
        t = float(s.get("start_sec") or 0)
        if not out:                          # 첫 줄은 반드시 0:00
            out.append((0.0, _headline(s, led) or "여는 말")); last = 0.0; continue
        if t - last < MIN_GAP:
            continue
        name = _headline(s, led)
        if not name:
            continue
        out.append((t, name)); last = t
    return out


def thumb_md(deck: Dict[str, Any], *, title: str, led: Optional[Dict] = None,
             book: str = "") -> str:
    """썸네일용 **원고 한 장**(마크다운).

    이미지 스튜디오의 «프롬프트 생성기» 는 JSON 을 받지 않는다 — 원고 파일
    (PDF·TXT·MD·DOCX·HWPX·PPTX)을 받아 옵션대로 프롬프트를 만든다. 그래서
    아홉 칸 JSON 이 아니라 **모델이 읽을 글**을 낸다.

    ★ 한 장만 낸다. 세 벌을 미리 만들어 두는 것보다, 원고 하나를 넣고 그 화면에서
      톤·스타일을 바꿔 가며 뽑는 편이 사람 손에 맞는다(2026-08-15).

    ★ 넣는 법 — «프롬프트 생성기» 에 이 파일을 끌어다 놓고
        용도 = 배너·썸네일 · 컷 수 = 1컷
      을 고르면 된다. 나머지(톤·색·스타일)는 취향껏.
    """
    led = led or {}
    slides = [s for s in (deck.get("slides") or []) if not s.get("drop")]
    heads = [h for h in (_headline(s, led) for s in slides) if h]
    last = slides[-1] if slides else {}
    total = float(last.get("start_sec") or 0) + float((last.get("audio") or {}).get("sec") or 0)

    L: List[str] = []
    # 유튜브 제목과 **같은 앞머리**를 쓴다 — 썸네일과 제목이 한 세트로 보이게
    L.append(f"# [{book} {title}]" if book else f"# [{title}]")
    L.append("")
    L.append(f"유튜브 영상 썸네일 한 장을 만들려고 합니다. 영상 길이는 {mmss(total)}, "
             f"슬라이드 {len(slides)}장짜리 강의입니다.")
    L.append("")
    L.append("## 이 영상이 다루는 것")
    for h in heads[:12]:
        L.append(f"- {h}")
    L.append("")
    L.append("## 썸네일에 넣을 글자")
    # ★ **한 줄만** 넣는다. 큰 제목 + 작은 줄로 두 단을 주면 모델이 큰 쪽을
    #   포스터 제목처럼 키운다. 사람이 보기 좋았던 것은 **작은 쪽 크기**였다
    #   (2026-08-15: "두 번째 글자 사이즈가 더 좋더라, 첫 번째는 부담").
    #   그래서 큰 단을 아예 없애고 그 크기 한 줄만 남긴다.
    L.append(f"- {heads[0] if heads else title}")
    L.append("")
    L.append("## 지켜 주세요")
    L.append("- 가로 16:9 한 장.")
    # ★ 스타일을 여기 적어 둔다. 2026-08-15 에 사람이 여러 스타일로 뽑아 보고
    #   고른 것이 이것이다 — 미니어처 질감이 「손에 쥐고 들여다본다」는 느낌을
    #   주어 강의 썸네일에 잘 맞았다. 화면에서 매번 고르지 않아도 되게 남긴다.
    L.append("- 스타일은 **스톱모션 퍼핏 / 클레이메이션** — 점토·펠트 질감의 "
             "미니어처 세트, 실사 조명, 부드러운 그림자, 손맛 있는 형태.")
    L.append("- 글자는 **한 줄만**, 크지 않게. 포스터 제목이 아니라 장면 위에 "
             "단정히 얹힌 리드문 정도면 됩니다.")
    L.append("- 글자가 화면을 지배하면 안 됩니다. **장면이 주인공**이고 글자는 얹는 것입니다.")
    L.append("- 글자는 위쪽이나 한쪽 구석에 모아 주세요. 한가운데를 가리지 마세요.")
    L.append("- 색은 진한 파랑과 밝은 파랑, 바탕은 밝은 아이보리. "
             "영상 안의 그림과 같은 결이어야 합니다.")
    L.append("- 실존 인물·로고·서비스 화면은 넣지 마세요.")
    L.append("- 사람 얼굴 대신 사물과 배치로 뜻을 전해 주세요.")
    return "\n".join(L) + "\n"


def build(deck: Dict[str, Any], *, title: str, led: Optional[Dict] = None,
          book: str = "") -> str:
    led = led or {}
    slides = [s for s in (deck.get("slides") or []) if not s.get("drop")]
    if not slides:
        return ""
    last = slides[-1]
    total = float(last.get("start_sec") or 0) + float((last.get("audio") or {}).get("sec") or 0)
    chaps = chapters(slides, led)
    heads = [c[1] for c in chaps[1:4]]

    # ★ 제목 앞에 **[책 이름 + 몇 장]** 을 대괄호로 단다. 유튜브 목록에서 같은
    #   시리즈가 죽 늘어설 때, 앞머리가 같아야 한 묶음으로 보인다
    #   (2026-08-15).
    brand = f"[{book} {title}]" if book else f"[{title}]"
    span = (f"{heads[0]}부터 {heads[-1]}까지" if len(heads) > 1
            else (heads[0] if heads else ""))

    L: List[str] = []
    L.append("유튜브에 올릴 때 이 파일의 칸을 그대로 옮겨 붙이세요.")
    L.append("")
    L.append("━━ 제목 (하나 고르세요) ━━")
    if span:
        L.append(f"  {brand} {span}")
    L.append(f"  {brand} {mmss(total)} 정리")
    if heads:
        L.append(f"  {brand} {heads[0]}")
    L.append("")
    L.append(f"길이 {mmss(total)} · 슬라이드 {len(slides)}장 · 챕터 {len(chaps)}개")
    L.append("")
    L.append("━━ 설명란 ━━")
    # ★ 설명란 **첫 줄이 목록에 미리보기로 뜬다.** 대괄호 앞머리를 여기 또 넣으면
    #   제목과 같은 말이 두 번 보이고, 정작 무슨 내용인지는 잘려서 안 보인다.
    #   그래서 첫 줄은 **한 문장으로 무엇을 정리했는지**만 말한다
    #   (2026-08-15).
    #   길이(22:45)도 빼는데, 유튜브가 그 숫자를 이미 화면에 보여 준다.
    L.append(f"{book} {title}{_eul(title)} 정리했습니다." if book
             else f"{title}{_eul(title)} 정리했습니다.")
    if heads:
        L.append("다루는 것 — " + " · ".join(heads))
    L.append("")
    for t, name in chaps:
        L.append(f"{mmss(t)} {name}")
    L.append("")
    L.append("━━ 태그 ━━")
    # ★ **`#` 을 붙여 낸다.** 설명란에 그대로 붙여 넣으면 유튜브가 클릭되는
    #   해시태그로 만든다(2026-08-15). 쉼표로 나열하면 그냥 글자로 남는다.
    #   ★ 해시태그는 **띄어쓰기를 못 쓴다** — 「새뮤얼슨의 경제학 하권」처럼 사이가
    #     벌어진 말은 거기서 끊겨 `#새뮤얼슨의` 만 태그가 된다. 그래서 붙여 쓴다.
    L.append(" ".join("#" + t.replace(" ", "")
                      for t in tags(deck, title=title, led=led, book=book)))
    return "\n".join(L) + "\n"


# 태그로 쓸 만한 말 — **낱말이 아니라 검색어**다. 화면 문구·대본에서 이 말이
# 나오면 태그로 올린다. 문장을 공백으로 쪼개면 「경제를」·「보는」·「개의」 같은
# 조각이 나오는데 아무도 그렇게 검색하지 않는다(2026-08-15).
TERMS = [
    "거시경제학", "미시경제학", "경제학", "경제 공부", "경제 상식",
    "GDP", "국내총생산", "명목GDP", "실질GDP", "잠재GDP", "경제성장률",
    "경기순환", "경기변동", "경기후퇴", "경기침체", "불황", "호황", "대공황",
    "인플레이션", "물가상승", "물가상승률", "소비자물가지수", "디플레이션",
    "실업", "실업률", "고용", "완전고용",
    "통화정책", "재정정책", "금리", "중앙은행", "정부지출", "조세", "세금",
    "총수요", "총공급", "AD곡선", "AS곡선", "균형",
    "케인스", "새뮤얼슨", "경상수지", "무역수지", "환율", "세계화",
]
# 화면 문구에 이렇게 적혀 있으면 위 태그로 친다
ALIAS = {
    "국내총생산": "GDP", "실질 GDP": "실질GDP", "명목 GDP": "명목GDP",
    "잠재 GDP": "잠재GDP", "물가상승": "인플레이션", "물가 안정": "물가상승률",
    "경기순환": "경기순환", "총수요": "총수요", "총공급": "총공급",
}


def tags(deck: Dict[str, Any], *, title: str, led: Optional[Dict] = None,
         book: str = "") -> List[str]:
    """유튜브 태그 — **사람이 검색할 만한 말**만 고른다.

    ★ 원고와 대본에 실제로 나온 말 중에서 고른다. 목록에 있다고 다 넣지 않는다 —
      영상에 안 나온 말을 태그로 달면 잘못 들어온 사람이 바로 나가고, 그게 더 나쁘다.
    """
    led = led or {}
    slides = [s for s in (deck.get("slides") or []) if not s.get("drop")]
    hay = " ".join(
        [title, book]
        + [str(s.get("title") or "") for s in slides]
        + [_headline(s, led) for s in slides]
        + [str((s.get("narration") or {}).get("srt_text") or "") for s in slides]
    )
    for a, b in ALIAS.items():
        if a in hay:
            hay += " " + b
    out: List[str] = []
    for t in TERMS:
        if t.replace(" ", "") in hay.replace(" ", "") and t not in out:
            out.append(t)
    # 책 이름과 강의 이름은 늘 넣는다 — 이 영상을 콕 집어 찾는 사람이 쓴다
    head = [x for x in (book, title) if x and x not in out]
    return (head + out)[:28]
