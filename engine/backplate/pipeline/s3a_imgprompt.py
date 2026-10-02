# -*- coding: utf-8 -*-
"""S3a 그림 지시문 — **원장에 없는 장만 만든다.**

이 단계의 핵심은 **안 부르는 것**이다. 세 겹으로 안 부른다.

    1. 원고가 `data-img` 를 들고 왔으면      → 그것을 쓴다. Claude 를 안 부른다
    2. 원장에 있고 몸통 해시가 같으면        → 옛 프롬프트를 쓴다. 안 부른다
    3. 그 밖에만                              → Claude 에게 쓰게 한다

값을 아끼려는 게 아니다. **같은 장의 프롬프트가 이유 없이 바뀌면 이미 그려 둔
그림과 어긋난다.** 원고를 고쳐 번호가 밀렸을 뿐인 장까지 다시 그리게 되면, 장
하나 끼워 넣은 값이 스물네 장을 다시 그리는 값이 된다.

★ ①이 가장 중요하다. 작가 에이전트가 원고를 쓰면서 **같은 몸통을 보고** 그림
  지시문을 같이 썼다. 여기서 제목·본문을 다시 읽어 조립하면 화면 문구와 그림이
  따로 논다 — 같은 단계에서 같은 몸통을 본 쪽이 늘 더 맞다.

★ 문체(`style_hint`)와 「글자 없음」 꼬리는 **코드가 붙인다.** 모델이 매번 다시
  쓰게 두면 장마다 조금씩 달라져서 한 덱 안에서 그림 결이 갈린다.

원장은 `09_이미지/원장.json` 이고 키는 **이름표**다(`core/ledger.py`). 번호는
내보낼 때(S3b) 처음 매긴다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import config, ledger as lg, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

BATCH = 10
LEVELS = ("기억", "이해", "적용", "분석", "평가", "창조")

# ★ 프롬프트 **모양**의 판번호. 원장은 「몸통이 안 바뀌면 다시 안 만든다」로 도는데,
#   프롬프트 꼴 자체가 바뀌면 몸통은 그대로여도 옛 프롬프트를 쓰면 안 된다.
#   판번호가 다른 칸은 다시 만든다.
#     1  영어 · 「글자 없음」 삽화 (2026-08-14 오전)
#     2  한국어 다섯 칸 · 헤드라인/서브카피가 그림에 박힘 (2026-08-14 저녁)
#     3  + 글자 크기 못박기(헤드라인 8~10%) · 「안 잘린다, 네 귀퉁이까지 채워라」
#     4  + 「원고 제목을 헤드라인에 다시 쓰지 마라」 · 헤드라인 더 작게(6~8%)
#     5  + 라벨 2~4개를 사물 둘레에 · 배치 여섯 갈래 · 글자 세 단 크기
#     6  + 라벨마다 **몇 번째 문장에서 말하는지**(`say_i`) · 말하는 차례로 적기
#        ★ 19장에서 겪은 것 때문이다. 그림이 한 판으로 오면 「어디에 무슨 글자가
#          있는지」가 사라져서, 뒤에서 상자를 오려 읽어 되찾아야 했다. 31장 중
#          25장이 라벨을 좌우로 두어 위→아래 정렬로는 차례가 안 정해졌고,
#          2.4 장은 제일 먼저 말하는 「목표」가 화면 맨 아래라 마지막에 떴다.
#          만들 때 적어 두면 되찾을 일이 없다(2026-08-17).
#     7  **전면 판** — 그림이 화면 가로를 꽉 채운다(2026-08-29)
#        ★ 6판까지는 3:2 액자에 앉혀 오른쪽 456px 을 비웠다(아바타 자리로 남긴
#          것인데 `#av` 는 232px 만 쓰고 아직 비어 있다). 7판은 가로를 다 쓰고
#          아래 20.5% 를 잘라 낸다 — 그래서 「어디까지 그려라」를 숫자로 못박고,
#          제목은 그림에서 빼 코드가 62px 고정으로 그린다.
PROMPT_FMT = 6        # 액자 판 — **옛 프로젝트가 이 판을 그대로 지킨다**
PROMPT_FMT_FULL = 10  # 전면 판 (10판: 그림이 **16:9 로 온다** — 잘리는 데가 없다)
                      # ★ 2026-09-18 이후로는 **안 만들어진다.** 전면도 글자를
                      #   안 박으므로 11판으로 적힌다(`fmt_of`). 옛 원장을
                      #   읽자고 남겨 둔 번호다.
PROMPT_FMT_PLATE = 13  # 배경판 (13판: 배경만 · **자리 지시를 아예 안 한다**)
                      # ★ 12 → 13(2026-09-19). 12판은 비울 네모를 좌표로
                      #   줬는데 **모델이 그 네모를 실제로 그렸다**(흰 상자가
                      #   박힌 그림). 자리 지시를 통째로 뺀다.
                      #   번호를 올려야 원장이 「바뀐 것 없음」이라도 다시
                      #   쓴다(아래 `old_fmt`).

# ★ **11판이 왜 생겼나.** 저자 지적(2026-09-14): "한글이 조금 깨지는 문제를
#   제외하고는 괜찮다". 10판은 그림 모델에게 한글 라벨을 **인쇄**하라고 시킨다.
#   모델이 글자를 틀리면(한다→한타) 고칠 방법이 마스크로 덮는 것뿐이었다
#   (11_완성/*-라벨검수.md 의 "깨짐" 줄들이 그것이다).
#   11판은 그림에서 글자를 통째로 뺀다. 라벨은 화면이 진짜 텍스트로 얹으므로
#   **깨질 수가 없다.** 덤으로 모션이 DOM 요소를 직접 움직일 수 있어
#   상자를 되찾는 일(zones·지정기·비전)이 통째로 없어진다.
#
# ★ **다 지우는 것이 아니다.** 처음엔 「글자를 하나도 넣지 마라」로 막았더니
#   책등의 과목명·서류철 탭·분류 라벨 같은 **장면 속 글자**까지 사라져
#   정보를 담은 그림이 빈 사무실 삽화가 됐다 — 톤이 통째로 달라졌다
#   (2026-09-18). 깨지던 것은 **긴 문장인 콜아웃 라벨**이지 사물에 붙은
#   짧은 낱말이 아니다. 그래서 라벨만 빼고 장면 속 글자는 남긴다.

# ★ 판을 **프로젝트마다** 고른다(`image_fit`). 한 자리에서 올려 버리면 지난
#   프로젝트의 지시문까지 전부 낡은 것으로 잡혀 다시 쓰인다 — 그 그림들은 액자에
#   맞춰 그려져 있어서 전면 지시문으로 바꿔 봐야 맞지 않는다 — 지난 영상을
#   보수할 수 있어야 한다(2026-08-29).


def is_plate(project: Dict[str, Any]) -> bool:
    """이 덱이 **배경판**인가 — 그림에 글자를 안 넣고 화면이 얹는다.

    ★ **전면(full)도 여기 들어온다**(2026-09-18). 판 셋 중 액자와 배경판을
      문에서 걷어내고 전면 하나만 남겼는데(`static/js/start.js` 의 「이미지 원고 ·
      전면」), 글자를 안 박는 규칙이 `plate` 에만 걸려 있었다. 그래서 전면
      지시문이 다시 라벨을 그림에 **인쇄하라고** 시켰다.
      그런데 원장은 판과 무관하게 `label_subs`·`label_places` 를 적고
      (아래 `made[did]`), 화면은 그것을 `_labels_html()` 로 그대로 얹는다 —
      **글자가 두 겹으로 겹쳤다**(실측 2026-09-18, 1장 002: 「재확인 시점」과
      「갱신의 몫」이 그림에 한 번 화면에 한 번).
      판이 하나로 좁혀졌으니 **전면이 곧 배경판**이다. 두 갈래로 두면 같은 사고가
      다시 난다.
    ★ 액자(frame, 옛 프로젝트)는 **그대로 둔다.** 그 그림들은 글자가 구워진 채로
      이미 나갔다 — 지시문이 흔들리면 보수할 때 통째로 다시 굽게 된다.
    """
    return ((project or {}).get("image_fit") or "frame") in ("full", "plate")


def is_full(project: Dict[str, Any]) -> bool:
    """이 덱이 **16:9 전면 판**인가. 값이 없으면 액자 판이다 — 옛 프로젝트가 그렇다.

    ★ 배경판(11)도 전면 판이다. 판 나누기·비율·잘림 없음은 10판과 똑같고,
      다르게 가는 것은 **글자를 넣느냐** 하나뿐이다.
    """
    return ((project or {}).get("image_fit") or "frame") in ("full", "plate")


def fmt_of(project: Dict[str, Any]) -> int:
    # ★ 전면이 `is_plate` 에 들어오면서 **11판이 새로 만들어지는 유일한 판**이
    #   됐다. `PROMPT_FMT_FULL`(10) 은 이제 **읽기 전용**이다 — 옛 원장이 그
    #   번호를 들고 있고 `s13b_order`·`render/youtube.py` 가 그걸 보고 갈린다.
    if is_plate(project):
        return PROMPT_FMT_PLATE
    return PROMPT_FMT_FULL if is_full(project) else PROMPT_FMT

# 그림이 들어갈 수 있는 레인.
#   html        원고 장 — 몸통을 그림 한 판으로 갈아끼운다
#   text_image  예전 캡처 레인 — 글 옆에 그림이 붙는다
WANT_MEDIA = ("html", "text_image", "thumb")

# ★ 라벨을 벌려 놓는 여섯 갈래. 본보기(NotebookLM 슬라이드 20쪽)를 재어 보니
#   이 여섯이 되풀이된다. 「알아서 배치하라」고 두면 죄다 상단에 몰아 놓는다.
#   값은 곧 프롬프트에 적히는 자리 지시다(아래 `_PLACE`).
ARRANGE = ("좌우", "세로삼단", "아래삼등분", "사방", "가로흐름", "가운데위")

# 갈래마다 라벨이 앉는 자리. 라벨 수가 모자라면 앞에서부터 쓴다.
# ★ 갈래마다 **다섯~여섯 자리**를 둔다. 긴 장은 라벨이 더 필요한데(아래 `want_n`)
#   자리가 셋뿐이면 넷째부터 갈 데가 없다.
_PLACE: Dict[str, List[str]] = {
    # ★ 좌우는 **번갈아** 앉힌다. 왼쪽 셋을 먼저 채우면 「좌우로 나눈다」가 깨진다
    "좌우":       ["왼쪽 가운데", "오른쪽 위", "오른쪽 아래",
                   "왼쪽 위", "왼쪽 아래", "오른쪽 가운데"],
    "세로삼단":   ["오른쪽 위", "오른쪽 가운데", "오른쪽 아래",
                   "왼쪽 위", "왼쪽 아래"],
    "아래삼등분": ["아래 왼쪽", "아래 가운데", "아래 오른쪽",
                   "위 왼쪽", "위 오른쪽"],
    "사방":       ["왼쪽 위", "오른쪽 위", "왼쪽 아래", "오른쪽 아래",
                   "가운데 위", "가운데 아래"],
    "가로흐름":   ["아래 왼쪽", "아래 가운데 왼쪽", "아래 가운데 오른쪽",
                   "아래 오른쪽", "위 왼쪽", "위 오른쪽"],
    "가운데위":   ["가운데 위", "왼쪽 아래", "오른쪽 아래",
                   "왼쪽 가운데", "오른쪽 가운데"],
}

# 라벨 수 — 그 장이 **몇 초짜리냐**에 맞춘다. 사람이 라벨을 하나씩 밝히며
# 이야기를 끄는데, 45초 장에 셋뿐이면 한 라벨이 십오 초씩 버텨야 한다.
# 대략 **열 초에 하나**로 잡고 셋~여섯 사이로 묶는다.
LABEL_MIN, LABEL_MAX = 3, 6
SEC_PER_LABEL = 10.0


def say_sentences(say: str) -> List[str]:
    """대본을 문장으로 쪼갠다. **번호가 곧 말하는 차례다.**

    ★ 나중에 음성이 나오면 자막(`08_자막/NNN.srt`)이 거의 이 단위로 끊긴다.
      그래서 여기서 매긴 번호가 그대로 「몇 초에 뜨는가」로 이어진다.
    """
    t = re.sub(r"\s+", " ", str(say or "")).strip()
    if not t:
        return []
    return [x.strip() for x in re.split(r"(?<=[.!?。])\s+", t) if x.strip()]


def _say_lines(say: str) -> str:
    ss = say_sentences(say)
    if not ss:
        return "  (없음)"
    return "\n".join(f"  {i}. {x}" for i, x in enumerate(ss, 1))


def want_n(say: str, cps: float = 5.7) -> int:
    """이 장에 라벨을 몇 개 쓸까. 대본 길이로 어림한다."""
    n = len(re.sub(r"\s", "", str(say or "")))
    sec = n / max(cps, 0.1)
    return max(LABEL_MIN, min(LABEL_MAX, round(sec / SEC_PER_LABEL)))
# 순서가 있는 갈래 — 라벨 사이에 화살표를 넣게 한다
_FLOW = ("가로흐름",)

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "data_id": {"type": "string"},
                    "level": {"type": "string", "enum": list(LEVELS)},
                    "background": {"type": "string"},
                    "layout": {"type": "string"},
                    "tone": {"type": "string"},
                    # 그림 안에 인쇄될 글자. **이것도 쓴다** — 원고 문장을 그대로
                    # 옮기면 길고 딱딱해서 카드가 안 된다(원고는 읽는 글, 이건 보는 글).
                    "title": {"type": "string"},
                    # ★ **라벨을 여러 개 받는다.** 제목 한 줄만 박힌 그림은 45초
                    #   동안 화면에 볼 것이 없다 — 마스킹으로 하나씩 밝힐 덩어리가
                    #   없어서다(2026-08-16). 사물 둘레에 흩어 놓는다.
                    "labels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "head": {"type": "string"},   # 굵은 소제목 6~12자
                                "body": {"type": "string"},   # 설명 2~3줄
                                # ★ **몇 번째 문장에서 말하는가**(1부터). 0=못 정함.
                                #   이것이 나중에 「글자가 언제 떠야 하나」가 된다.
                                "say_i": {"type": "integer"},
                            },
                            "required": ["head", "body", "say_i"],
                            "additionalProperties": False,
                        },
                    },
                    # 라벨을 어떻게 벌려 놓을까 — 그 장이 말하는 꼴에 맞춰 고른다
                    "arrange": {"type": "string", "enum": list(ARRANGE)},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["data_id", "level", "background", "layout", "tone",
                             "title", "labels", "arrange", "keywords"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["prompts"],
    "additionalProperties": False,
}


def _one(t: Any, n: int) -> str:
    """한 줄로 눌러 담는다. 프롬프트는 칸마다 한 줄이라 줄바꿈이 들어가면 칸이 깨진다."""
    return re.sub(r"\s+", " ", str(t or "")).strip()[:n]


# ── 자리 이름 → 화면 좌표 ──────────────────────────────────────────────────
# ★ **이 표가 그림과 화면을 맞물린다.** 11판에서 그림은 이 자리를 비우고
#   화면은 이 자리에 글을 얹는다. 둘이 어긋나면 글이 그림 위에 겹친다.
#   숫자는 프롬프트가 모델에게 말하는 좌표와 같은 것이다 —
#     「위」 y=150~330  → 150/1080 = 13.9%
#     「아래」 y=730~1010 → 730/1080 = 67.6%
#     가운데 띠는 그 사이(y≈440) = 40.7%
#   가로는 실측한 zones.json 의 상자에서 가져왔다(왼쪽 x=72 · 오른쪽 x=1436 ·
#   너비 437 → 4% · 74.8% · 22.8%). 네 칸짜리 가로흐름은 23%씩 붙여 놓는다.
_X_L, _X_CL, _X_CR, _X_C, _X_R = 4.0, 27.0, 50.0, 38.5, 73.0
_Y_T, _Y_M, _Y_B = 13.9, 40.7, 67.6
LABEL_W = 23.0          # 상자 너비(%) — 라벨 설명 두세 줄이 들어가는 폭

PLACE_XY: Dict[str, tuple] = {
    "왼쪽 위":            (_X_L,  _Y_T),
    "왼쪽 가운데":        (_X_L,  _Y_M),
    "왼쪽 아래":          (_X_L,  _Y_B),
    "오른쪽 위":          (_X_R,  _Y_T),
    "오른쪽 가운데":      (_X_R,  _Y_M),
    "오른쪽 아래":        (_X_R,  _Y_B),
    "가운데 위":          (_X_C,  _Y_T),
    "가운데 아래":        (_X_C,  _Y_B),
    "위 왼쪽":            (_X_L,  _Y_T),
    "위 오른쪽":          (_X_R,  _Y_T),
    "아래 왼쪽":          (_X_L,  _Y_B),
    "아래 가운데":        (_X_C,  _Y_B),
    "아래 오른쪽":        (_X_R,  _Y_B),
    "아래 가운데 왼쪽":   (_X_CL, _Y_B),
    "아래 가운데 오른쪽": (_X_CR, _Y_B),
}


def labels_of(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """원장 한 칸 → 화면이 그릴 라벨 목록.

    11판에서 `render/slides.py` 와 `s8_assemble` 이 이것을 쓴다. 10판 원장에는
    `label_subs`·`label_places` 가 없으므로 **빈 목록이 나온다** — 옛 프로젝트를
    건드리지 않기 위해서다(그쪽은 글자가 그림 안에 있다).
    """
    heads = list(entry.get("label_heads") or [])
    if not heads:
        return []
    subs = list(entry.get("label_subs") or [])
    places = list(entry.get("label_places") or [])
    says = list(entry.get("label_says") or [])
    if not subs and not places:
        return []               # 10판 원장 — 화면이 그릴 것이 없다
    out: List[Dict[str, Any]] = []
    for i, head in enumerate(heads):
        place = places[i] if i < len(places) else ""
        x, y = PLACE_XY.get(place, (_X_L, _Y_T))
        out.append({
            "head": head,
            "sub": subs[i] if i < len(subs) else "",
            "place": place,
            "x": x, "y": y, "w": LABEL_W,
            # 몇 번째 내레이션 문장에서 이 라벨을 말하는가 — 모션이 읽는다
            "say_i": int(says[i]) if i < len(says) else 0,
        })
    return out


def _places_for(arrange: str, n: int) -> List[str]:
    """라벨 n개가 앉을 자리 이름. `compose()` 가 쓰는 규칙과 **같아야** 한다 —
    그림은 이 자리를 비우고 화면은 이 자리에 글을 얹으므로, 둘이 어긋나면
    글이 그림 위에 겹친다."""
    a = arrange if arrange in ARRANGE else "좌우"
    return _PLACE[a][:max(0, int(n))]


def compose(*, background: str, layout: str, tone: str, title: str,
            labels: List[Dict[str, Any]], arrange: str,
            cfg: Dict[str, Any], full: bool = False, plate: bool = False) -> str:
    """이미지 스튜디오가 그대로 먹는 **한국어 프롬프트.**

    ★ 이 그림은 **글자를 넣는 그림**이다. 예전엔 정반대였다 — 영어로 「no text」를
      세 겹으로 걸었다. 그림이 몸통을 대신하는데 글자가 없으면 그 장이 말하려던
      것이 통째로 사라진다(2026-08-14 실측: 제목 한 줄만 남고 문단·불릿·타임라인이
      전부 없어졌다).

    ★ **제목 한 줄로는 모자란다.** 한 장이 45초씩 가는데 화면에 읽을 것이 그것뿐이면
      말만 길고 볼 것이 없다. 사람이 그 구간에 마스킹 효과를 거는데, 걸 덩어리가
      없어서 장당 세 개(대부분 제목)밖에 안 잡혔다(2026-08-16).
      그래서 **사물 둘레에 라벨을 흩어 놓는다** — 굵은 소제목 + 설명 두세 줄.

    ★ 자리를 **갈래로 못박는다.** 「알아서 배치하라」고 두면 죄다 상단에 몰아 놓는다.
      본보기(NotebookLM 슬라이드)를 재어 보니 여섯 갈래가 되풀이됐다(`ARRANGE`).
    """
    img = cfg["image"]
    bg = img.get("bg", "#F6F1E8")      # 1칸을 칠할 색. 바탕과 같아야 한다
    # ★ **「중심」이라고 쓰지 않는다.** 그 낱말은 "이 색으로 화면을 채우라" 로
    #   읽힌다. 실제로 원하는 것은 *글자와 강조에* 그 파랑을 쓰라는 것이다.
    tone = _one(tone, 220) or (
        f"글자와 강조에 진한 파랑({img['accent_a']})과 밝은 파랑({img['accent_b']}), "
        "본문 글자는 슬레이트(#334155), 플랫 벡터에 은은한 입체감")
    arrange = arrange if arrange in ARRANGE else "좌우"
    spots = _PLACE[arrange]

    lines = [
        # ★ **바탕을 맨 앞 독립된 줄로.** 예전에는 색/톤 줄 **끝에** 붙였는데,
        #   모델은 그 줄을 앞에서부터 읽어 "진한 파랑" 을 먼저 만나면 그것을
        #   화면의 지배색 = 배경으로 잡아 버린다. 뒤에 오는 "바탕은 아이보리" 는
        #   이미 정해진 배경을 못 뒤집는다. 그래서 **대부분 맞다가 간혹 뒤집히는**
        #   산발적 실패가 났다(2026-08-16 003 · 2026-08-17 20장의 006·010).
        # ★ 검정만 막으면 **비네팅·어두운 그라데이션·발광**으로 빠져나간다.
        #   결과는 똑같이 글자가 묻힌다 — 006 이 그 경우였다. 같이 막는다.
        f"바탕: 화면 전체를 밝은 아이보리({img.get('bg', '#F6F1E8')}) 단색으로 고르게 "
        "칠한다 — 네 귀퉁이와 가장자리까지 같은 밝기다. 어두운 배경·검정 판·"
        "야간 장면·비네팅(가장자리 어둡게)·어두운 그라데이션·발광(글로우) 금지 "
        "— 글자가 묻힌다. 진한 파랑은 글자와 강조에만 쓰고 배경에는 쓰지 않는다",
    ]
    if full:
        # 칸마다 한 줄 — 지시문 규약이 그렇다. 한 줄에 몰아넣으면 칸이 깨진다.
        # ★ **10판에서 칸이 셋에서 둘로 줄었다**(2026-08-29). 그림이 3:2 로 오던
        #   동안은 16:9 화면에 앉힐 때 아래 15.6% 가 잘려서, 그 자리를 비워 달라고
        #   「3칸 블리드칸」을 두고 부탁해야 했다. 두 판(8·9판)을 그렇게 썼지만
        #   **15장 전부가 그 칸을 넘겼다**(중앙값 85.1% · 최악 93.8%). 그림 모델은
        #   판을 채우려는 성향이 강해서, 문구를 아무리 세게 써도 안 지켜졌다.
        # ★ 이제 그림이 **16:9 로 온다.** 화면과 비율이 같아 **한 픽셀도 안 잘린다** —
        #   부탁할 일이 통째로 없어졌다. 남은 것은 제목 자리 하나뿐이다.
        lines.append(
            "판 나누기: 이 그림은 위에서 아래로 **두 칸**이 쌓인 판이다. 크기는 "
            "1920×1080(16:9)이고 두 칸의 높이를 합치면 1080px 다")
        lines.append(
            f"  1칸 제목칸  y=0~108 (108px, 높이의 10%): 아이보리({bg}) 단색. "
            "장면도 글자도 없다. 발표 화면의 제목이 이 칸 위에 얹힌다")
        lines.append(
            "  2칸 그림칸  y=108~1080 (972px, 높이의 90%): **장면과 글자는 오직 이 "
            "칸 안에 있다.** 가로는 0~1920px 끝에서 끝까지, 세로는 맨 아래 "
            "y=1080 까지 남김없이 채운다 — 아래쪽에 여백을 두지 마라")
        lines.append(
            "  ★ 이 판은 화면과 비율이 같아서 **잘려 나가는 데가 없다.** 네 "
            "가장자리까지 그대로 나간다. 그러니 「잘릴까 봐」 가장자리를 비우거나 "
            "주제를 한가운데로 몰지 마라 — 화면이 헐거워진다. 비우는 것은 "
            "**1칸 하나뿐**이다")
    lines += [
        f"배경: {_one(background, 220)}",
        # ★ 꼬리는 **전면 판에만** 붙인다. 양쪽에 붙이면 액자 판 지시문이 옛것과
        #   달라져 지난 프로젝트가 통째로 다시 쓰인다(2026-08-29 실측으로 잡았다).
        f"구도: {_one(layout, 260)}"
        + (" (장면은 2칸 y=108~1080 안에서 짠다)" if full else ""),
        f"색/톤: {tone}",
    ]
    # ★ **전면 판은 제목을 그림에 안 그린다.** 화면 위 제목은 코드가 62px 고정으로
    #   그린다 — 그림이 그리면 장마다 제목 크기가 들쑥날쑥했다(2026-08-29).
    #   그림은 그 자리를 비워 주기만 하면 된다.
    # ★ 이 자리에 `제목: "…"` 꼴을 되살리면 안 된다 — `render/youtube.py` 가 그
    #   꼴을 찾아 챕터 제목으로 쓴다. 못 찾으면 원고 제목으로 내려간다.
    if full:
        # ★ **「비워라」가 아니라 「칠해라」로 적는다**(2026-08-29) — 「아래 25%는
        #   아이보리로 채운다」처럼 적는다. 「비워 둔다」는 모델에게
        #   「그리다 말라」로 읽혀 배경 무늬·바닥선·그림자가 그 띠를 그대로 가로지른다.
        #   색을 못박으면 **칠해야 할 면**이 되어 결과가 훨씬 덜 흔들린다.
        lines.append(
            "제목: 그림 안에 제목·헤드라인을 인쇄하지 마라. 1칸은 발표 화면의 "
            "제목이 얹힐 빈 자리다")
    else:
        lines.append(f'제목(한글, 굵게, 화면 맨 위 가운데): "{_one(title, 40)}"')
    if plate:
        # ★ **자리를 아예 안 알려 준다**(2026-09-19). 자리 맞추기는 화면 쪽
        #   글자 테두리·셀색으로 사람이 한다.
        #   그전에는 두 겹으로 자리를 못박았다 — 낱말로 한 번(「왼쪽 가운데」),
        #   네모 좌표로 한 번(x=77~518 · y=440~584). **둘 다 역효과였다.**
        #     · 「한가하게 두라」 → 모델이 네 귀퉁이를 비우고 장면을 가운데 띠로
        #       몰아 화면이 헐거워졌다(1장 002·003).
        #     · 「네모 안에는 바탕만」 → 모델이 그 네모를 **실제로 그렸다.**
        #       흰 상자가 박힌 그림이 나왔다(4장 002 실측).
        #   「그리지 마라」를 아무리 겹쳐 적어도 네모를 **말하는 순간** 모델은
        #   그린다. 말을 안 꺼내는 것이 유일하게 듣는 길이었다.
        # ★ 그래서 자리 맞추기는 **사람 몫으로 내린다.** 글이 그림을 가리면
        #   「라벨 자리」에서 끌어 옮기고(돈 안 듦), 바탕이 복잡하면 셀색을
        #   윤곽에서 판으로 올린다. 그림을 다시 굽는 것보다 싸고 확실하다.
        # 라벨(콜아웃)만 뺀다.
        lines.append(
            "글자: **라벨(소제목+설명)을 그림에 인쇄하지 마라.** 그 글은 화면이 "
            "진짜 텍스트로 얹는다 — 네가 그리면 두 겹으로 겹친다. "
            "제목·헤드라인도 넣지 않는다")
        # ★ 장면 속 글자는 **남긴다.** 다 지웠더니 정보를 담은 그림이 빈 사무실
        #   삽화가 됐다(2026-09-18).
        lines.append(
            "다만 **장면 속 사물에 붙은 글자는 넣어라** — 책등의 과목명, 서류철 "
            "탭, 분류 라벨, 게시물, 표지의 짧은 낱말 같은 것이다. 그것이 있어야 "
            "장면이 정보를 담은 그림이 된다. 없으면 빈 사무실 삽화가 된다. "
            "다만 **짧은 낱말**로만 두어라(두세 어절 이내) — 설명하는 긴 문장은 "
            "쓰지 마라. 길수록 글자가 깨진다")
    else:
        for i, lb in enumerate(labels[:len(spots)]):
            head = _one((lb or {}).get("head"), 20)
            body = _one((lb or {}).get("body"), 80)
            if not head:
                continue
            lines.append(f'라벨 {i + 1} ({spots[i]}): 굵게 "{head}" / 그 아래 작게 "{body}"')
    if arrange in _FLOW and len(labels) > 1:
        lines.append("라벨 사이에 진행 방향을 가리키는 화살표를 하나씩 넣어라 "
                     "— 왼쪽에서 오른쪽으로 이어지는 순서다")
    # ★ **잇는 선을 넣지 않는다**(2026-08-16). 라벨과 그림을 가는 선으로
    #   이으면 화면이 지저분해지고, 마스크로 라벨을 하나씩 밝힐 때 선만 먼저
    #   떠 있어 다음에 무엇이 나올지 미리 보인다. 라벨은 **가까이 놓아** 무엇을
    #   가리키는지 알게 한다.
    if not plate:
        lines.append("라벨은 **글자만** 놓아라 — 라벨과 그림을 잇는 선이나 점을 그리지 "
                     "말고, 라벨을 상자·카드·둥근 판·테두리에 담지도 마라. 바탕 위에 "
                     "글자만 얹고, 가리키는 부분 **가까이에** 놓아 저절로 이어져 보이게 한다")
    else:
        # ★ **금지만 남긴다.** 앞말이 「비운 자리에」였는데 이제 비우라고 안
        #   하므로 붕 떴다. 금지 자체는 지운다 — 화면이 글자를 얹는데 그림에
        #   빈 그릇이 있으면 그 위에 또 겹친다(2026-09-18 실측: 라벨 판과
        #   그림 속 흰 카드가 두 겹).
        # ★ 12판의 교훈은 **좌표를 주지 말라**는 것이지 금지를 빼라는 것이
        #   아니다. 11판은 이 줄을 달고도 상자가 안 나왔다 — 네모를 그리라고
        #   읽힌 것은 「이 네모 안에는 바탕만」 쪽이었다.
        lines.append("글자를 담는 상자·카드·둥근 판·테두리·말풍선을 그리지 마라 "
                     "— 넣을 글이 없으니 빈 그릇만 남고, 화면이 얹는 글자와 "
                     "두 겹으로 겹친다")

    # ★ **글자 크기를 세 단으로 못박는다.** 안 적으면 모델이 라벨을 제목만큼 키워
    #   화면이 글자로 덮인다. 본보기의 제목:소제목:설명이 대략 1 : 0.6 : 0.4 였다.
    # ★ 전면 판에는 그림 안에 제목이 없다. 없는 것을 기준으로 적으면 모델이
    #   기준을 못 찾아 라벨을 제목만 하게 키운다 — 그래서 **그림 높이로** 적는다
    #   (옛 판의 제목 7% × 0.6 = 4.2%, 그 65% = 2.7%. 결이 같다).
    if plate:
        pass   # 그림 안에 글자가 없으니 글자 크기를 적을 것이 없다.
               # 화면 쪽 크기는 render/slides.py 의 .lbl 이 정한다
               # (소제목 4% · 설명은 그 65% — 10판이 모델에게 시키던 그 수치).
    elif full:
        lines.append("글자 크기: 라벨 소제목은 그림 높이의 4% 안팎, 그 아래 설명은 "
                     "소제목의 65%. 두 단이 눈에 띄게 달라야 한다. 글자가 화면을 "
                     "덮으면 안 된다 — 그림이 주인공이고 라벨은 그 둘레에 얹힌다. "
                     "포스터 머리글처럼 키우지 마라")
    else:
        lines.append("글자 크기: 제목은 그림 높이의 7% 안팎, 라벨 소제목은 제목의 60%, "
                     "라벨 설명은 소제목의 65%. 세 단이 눈에 띄게 달라야 한다. "
                     "글자가 화면을 덮으면 안 된다 — 그림이 주인공이고 라벨은 그 둘레에 "
                     "얹힌다. 포스터 제목처럼 키우지 마라")
    # ★ **액자 안이 곧 그림 전부다.** 화면에서 이 그림은 3:2 액자에 통째로 앉고
    #   한 픽셀도 안 잘린다(`render/slides.py` 의 `.s-swap` — 자르지 않으려고
    #   남는 자리를 바탕으로 처리했다). 그런데 「16:9 로 잘릴 수 있다」고 적어
    #   두면 모델이 가장자리를 비워 두려고 주제를 한가운데로 몰아 화면이 헐거워진다.
    #   이제는 반대로 **가장자리까지 다 쓰라고** 말해 준다.
    if full:
        # ★ **어디까지 그려야 하는지를 숫자로 못박는다**(2026-08-29).
        #   제목 62px 아래 1920×1018 에 가로를 꽉 채워 앉으므로
        #   배율이 1.25 가 되고 세로 1280 중 **아래 262px(20.5%)이 잘린다.**
        # ★ 「가장자리까지 다 쓰라」와 정면으로 부딪히므로 **어느 쪽이 이기는지**를
        #   적어 준다. 안 적으면 둘을 반씩 지켜 라벨이 잘리는 자리에 앉는다.
        if plate:
            # ★ **좌표를 안 준다**(2026-09-19). 위 `if plate:` 머리말 참고 —
            #   네모를 말하면 모델이 네모를 그린다. 자리 맞추기는 화면에서 한다.
            pass
        else:
            lines.append("라벨 자리(2칸 안의 좌표): 「위」라고 적은 자리는 y=150~330, "
                         "「아래」라고 적은 자리는 y=730~1010 이다 — 라벨의 **설명 "
                         "줄까지** y=1010 안에서 끝나야 한다. 「아래」는 1칸이 아니라 "
                         "**2칸의 아래쪽**을 뜻한다")
        # ★ **16:9 로 뽑는다**(10판). 화면과 비율이 같아 잘리는 데가 없다 —
        #   「안 잘린다」를 분명히 적어야 모델이 가장자리를 비워 두지 않는다.
        lines.append("산출물 규격: **16:9 가로(1920×1080)**. 발표 화면과 비율이 "
                     "같아서 이 판이 **한 픽셀도 안 잘리고 그대로** 나간다 — 네 "
                     "가장자리까지 다 쓰고, 안전 여백을 위해 주제를 한가운데로 "
                     "몰지 마라. 실존 로고·서비스 화면·실존 인물 금지")
    else:
        lines.append("산출물 규격: 3:2 가로(1536×1024). 화면의 액자 안에 통째로 들어가며 "
                     "잘리는 부분이 없다 — 가장자리까지 다 쓰고, 안전 여백을 위해 "
                     "주제를 한가운데로 몰지 마라. 실존 로고·서비스 화면·실존 인물 금지")
    return "\n".join(lines)


def plain_title(s: Dict[str, Any]) -> str:
    """제목에서 앞 순번(`3 `)을 뗀 것. 헤드라인을 못 받았을 때 이걸 쓴다."""
    return re.sub(r"^\s*\d+[.\s]\s*", "", str(s.get("title") or "")).strip()


def first_line(s: Dict[str, Any]) -> str:
    """원고의 첫 글줄. 서브카피를 못 받았을 때 쓰고, 브리프에도 재료로 넣는다."""
    for b in (s.get("blocks") or []):
        t = _one(b.get("html"), 80)
        if t and not t.startswith("[그림]"):
            return t
    return _one(s.get("say"), 80)


def slide_id(slug: str, s: Dict[str, Any]) -> str:
    """이 장의 이름표. 원고가 안 줬으면 만들어 준다.

    원장은 이름표가 있어야 도는데, 문제집 원고(`1과목2.html` 계열)에는 `data-id`
    가 없다. 그럴 때는 번호로 만든다 — 이름표만큼 튼튼하지는 않지만(장이 끼어들면
    같이 밀린다), 없는 것보다는 낫고 그 갈래는 원고가 잘 안 바뀐다.
    """
    return str(s.get("data_id") or "").strip() or f"{slug}-{int(s['no']):03d}"


def body_of(s: Dict[str, Any]) -> List[Dict[str, Any]]:
    """몸통 해시를 낼 때 쓰는 줄 목록. `ledger.body_hash()` 가 먹는 모양으로."""
    texts = s.get("html_text") or []
    if texts:
        return [{"kind": "line", "html": str(t)} for t in texts]
    # 원고 장이 아니면(text_image 레인) 본문 한 덩어리가 전부다
    return [{"kind": "note", "html": str(s.get("note") or "")}]


def build_brief(project: Dict[str, Any], batch: List[Dict[str, Any]]) -> str:
    lines = ["# 발표", project.get("title") or ""]
    # ★ **이번 덱이 어느 판인지 여기서 못박는다.** `구도` 칸은 모델이 쓰는 글이라,
    #   비워 둘 자리를 여기서 알려 주지 않으면 「상단에 제목 자리」 같은 옛 판
    #   문장을 그대로 쓴다. 코드가 붙이는 꼬리(`compose`)와 어긋나면 그림이 그
    #   틈에서 흔들린다.
    if is_full(project):
        lines += ["", "# 이 덱의 판 — **전면**",
                  "그림이 16:9(1920×1080)로 와서 화면을 그대로 덮는다. 잘리는 데가 없다.",
                  # ★ 「비운다」가 아니라 「칠한다」로 적는다 — `compose` 의 위·아래
                  #   띠 지시와 같은 말이어야 한다. 두 글이 다른 낱말을 쓰면 모델이
                  #   그 틈에서 흔들린다(2026-08-29).
                  "- `구도` 칸에 **맨 위 10%(y=0~108)만 아이보리 단색으로 비우고, "
                  "장면은 y=108~1080 을 네 가장자리까지 채운다**고 반드시 적어라.",
                  "- **`제목` 은 그림에 인쇄되지 않는다.** 화면 위 제목은 코드가 "
                  "그린다. 그래도 한 줄 써라 — 다른 자리에서 쓴다."]
    else:
        lines += ["", "# 이 덱의 판 — **액자**",
                  "그림이 3:2 액자에 통째로 앉고 잘리는 부분이 없다.",
                  "- `구도` 칸에 상단 제목 자리를 넓게 비운다고 적어라.",
                  "- `제목` 은 그림 맨 위에 굵게 인쇄된다."]
    lines += ["", "# 그림을 그릴 장"]
    for s in batch:
        rows = "\n".join(f"  - {b['html']}" for b in s["blocks"] if b.get("html"))
        lines += [
            # ★ 제목은 **화면 위에 이미 뜬다.** 그걸 안 알려 주면 모델이 제목을
            #   그대로 헤드라인에 옮겨서 한 화면에 같은 말이 두 번 뜬다
            #   (2026-08-15 실측: "1.2. 짧은 물결과 긴 흐름" 위에 "짧은 물결과 긴 흐름").
            f"\n## {s['data_id']}",
            f"- 화면 위에 이미 떠 있는 제목(**그림 제목에 다시 쓰지 마라**): "
            f"{plain_title(s)}",
            # ★ 장마다 **몇 개를 쓸지 숫자로 준다.** 사람이 말하는 차례대로 라벨을
            #   하나씩 밝히며 이야기를 끄는데, 45초 장에 셋뿐이면 한 라벨이
            #   십오 초씩 버텨야 한다(2026-08-16: "그 말을 할 때 나타나서 말하는
            #   동안 계속 빛을 비춘다"). 열 초에 하나꼴로 잡아 준다.
            f"- **이 장은 라벨 {want_n(s.get('say'))}개를 써라.**",
            # ★ 대본을 **문장마다 번호를 붙여** 준다. 라벨이 그 번호를 가리키게
            #   하려는 것이다(`say_i`). 한 덩이로 주면 「몇 번째 말에 이 라벨이
            #   뜨는가」를 가리킬 방법이 없다.
            "- 말할 것(문장 번호가 곧 말하는 차례다):",
            _say_lines(s.get("say")),
            "- 그 장의 화면 문구(라벨은 여기서 뽑아 쓴다):",
            rows or "  (없음)",
        ]
    lines.append("\n주어진 data_id 만 채워라. 장마다 적힌 라벨 개수를 지켜라. "
                 "JSON 만 출력.")
    return "\n".join(lines)


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s3a-imgprompt"]
    cfg = config.load()
    # ★ 판번호는 **이 덱의 갈래**가 정한다. 액자 판(옛 프로젝트)은 6 그대로라
    #   원장이 낡은 것으로 안 잡힌다 — 지난 영상을 보수해도 지시문이 안 흔들린다.
    full = is_full(project)
    plate = is_plate(project)
    fmt = fmt_of(project)

    outline = cached_data(pid, slug, "s2b-outline") or {}
    slides = outline.get("slides") or []
    if not slides:
        raise RuntimeError("구조 설계(s2b-outline)를 먼저 돌리세요")

    targets = [s for s in slides if s.get("media_kind") in WANT_MEDIA]
    if not targets:
        raise RuntimeError("그림이 들어갈 장이 없습니다 (html · text_image 레인이 없음)")

    rows: List[Dict[str, Any]] = []
    for s in targets:
        blocks = body_of(s)
        rows.append({
            "data_id": slide_id(slug, s),
            "no": s["no"],
            "title": s.get("title") or "",
            "say": s.get("say") or "",
            "img": re.sub(r"\s+", " ", str(s.get("img") or "")).strip(),
            "blocks": blocks,
            "body_hash": lg.body_hash(blocks, s.get("title") or ""),
        })

    book = ws.load_ledger(pid, slug)
    make_ids, keep_ids = lg.plan(book, rows)
    # ★ 프롬프트 꼴이 바뀌었으면 몸통이 그대로여도 다시 만든다. 안 그러면 원장이
    #   「바뀐 것 없음」 이라 말하고 옛 꼴 프롬프트가 그대로 나간다.
    old_fmt = [d for d in keep_ids
               if int(((book.get("by_id") or {}).get(d) or {}).get("fmt") or 1) != fmt]
    if old_fmt:
        keep_ids = [d for d in keep_ids if d not in set(old_fmt)]
        make_ids = make_ids + old_fmt
        job.add_log(f"프롬프트 꼴이 바뀌어 다시 씁니다 — {len(old_fmt)}장 "
                    "(옛 꼴: 영어·글자 없는 삽화)")
    if force:
        make_ids, keep_ids = [r["data_id"] for r in rows], []

    # ★ 원고의 `data-img` 는 **이 모드에 못 쓴다.** 그것은 「글자 없는 삽화를
    #   글 뒤에 깐다」는 전제로 영어로 쓰인 것이라(끝에 no text 가 세 겹) 지금
    #   필요한 「글이 박힌 한 판」과 정반대다. 그래서 여기서는 늘 새로 쓴다.
    #   원장은 그대로 작동한다 — 몸통이 안 바뀐 장은 다시 안 부른다.
    made: Dict[str, Dict[str, Any]] = {}
    by_id = {r["data_id"]: r for r in rows}
    ask_ids = list(make_ids)

    job.add_log(f"그림이 필요한 장 {len(rows)}개 — 원장에서 그대로 {len(keep_ids)}개 · "
                f"새로 쓸 것 {len(ask_ids)}개")

    # ── ③ 남은 것만 Claude 에게 ──────────────────────────────────────────────
    warn: List[str] = []
    cost = 0.0
    if ask_ids:
        want = [by_id[d] for d in ask_ids]
        system = (Path(__file__).resolve().parent.parent
                  / "llm" / "prompts" / "imgprompt.md").read_text(encoding="utf-8")
        batches = [want[i:i + BATCH] for i in range(0, len(want), BATCH)]
        p = ClaudeProvider(
            model=(project.get("models") or {}).get("imgprompt") or cfg["models"]["imgprompt"],
            effort=cfg["effort"]["imgprompt"],
            budget_usd=cfg["budget_usd"]["per_stage"],
            on_activity=job.add_log,
        )
        for i, batch in enumerate(batches):
            job.progress(i, len(batches), f"{batch[0]['data_id']} … {batch[-1]['data_id']}")
            try:
                raw = p.structured(system,
                                   [{"role": "user",
                                     "content": build_brief(project, batch)}],
                                   schema=SCHEMA)
            except Exception as e:                    # noqa: BLE001
                warn.append(f"{batch[0]['data_id']} 묶음 실패: {type(e).__name__}: {e}")
                continue
            cost += p.last_cost_usd
            for r in raw.get("prompts") or []:
                did = (r.get("data_id") or "").strip()
                if did not in by_id:
                    warn.append(f"모르는 이름표라 버렸습니다: {did}")
                    continue
                src = by_id[did]
                if len(_one(r.get("layout"), 999)) < 20:
                    warn.append(f"{did}: 구도가 너무 짧습니다")
                    continue
                labels = [x for x in (r.get("labels") or [])
                          if _one((x or {}).get("head"), 20)]
                if len(labels) < 2:
                    # 라벨이 하나뿐이면 마스킹으로 밝힐 덩어리가 안 생긴다 —
                    # 그림을 뽑기 전에 걸러야 스물아홉 장을 또 버리지 않는다.
                    warn.append(f"{did}: 라벨이 {len(labels)}개뿐입니다")
                made[did] = {
                    "title": src["title"],
                    "level": r.get("level") if r.get("level") in LEVELS else "이해",
                    # ★ 표본 JSON 은 전부 `photo` 다. 갈릴 축이 없어 고정한다 —
                    #   스튜디오도 이 칸을 안 읽는다.
                    "type": "photo",
                    "fmt": fmt,
                    # 유튜브 챕터·썸네일이 이 값을 읽는다(render/youtube.py)
                    "label_heads": [_one(x["head"], 20) for x in labels],
                    # ★ **설명줄과 자리를 버리지 않는다.** 10판은 이 둘을 프롬프트
                    #   문자열 안에만 남기고 버렸다 — 그림이 인쇄해 줄 테니 다시
                    #   쓸 일이 없었기 때문이다. 11판은 화면이 직접 그려야 해서
                    #   **구조화된 채로** 있어야 한다.
                    "label_subs": [_one(x.get("body"), 80) for x in labels],
                    "label_places": _places_for(r.get("arrange") or "", len(labels)),
                    "arrange": (r.get("arrange") if r.get("arrange") in ARRANGE
                                else "좌우"),
                    # ★ 라벨마다 **몇 번째 문장에서 말하는가**. 모션이 이걸 읽어
                    #   상자 차례를 정한다 — 그림이 오고 나서 되찾을 필요가 없다.
                    "label_says": [max(0, int(x.get("say_i") or 0)) for x in labels],
                    # 제목을 못 받으면 원고 제목으로 받쳐 준다 — 글자 없는 카드가
                    # 나가는 것보다 원고 제목이라도 박히는 편이 낫다.
                    "prompt": compose(background=r.get("background"),
                                      layout=r.get("layout"), tone=r.get("tone"),
                                      title=_one(r.get("title"), 40) or plain_title(src),
                                      labels=labels, arrange=r.get("arrange") or "",
                                      cfg=cfg, full=full, plate=plate),
                    "keywords": [str(k) for k in (r.get("keywords") or [])][:1],
                }
        job.progress(len(batches), len(batches), "정리")

    book = lg.apply(book, made, rows)
    ws.save_ledger(pid, slug, book)

    miss = [r["data_id"] for r in rows
            if not ((book["by_id"].get(r["data_id"]) or {}).get("prompt") or "").strip()]
    job.add_log(f"원장 {len(book['by_id'])}칸 · 지시문 있는 장 "
                f"{len(rows) - len(miss)}/{len(rows)}개 · ${cost:.3f}")
    if miss:
        job.add_log(f"지시문이 없는 장 {len(miss)}개: {', '.join(miss[:10])}")
    for w in warn[:10]:
        job.add_log(w)

    return write_cache(pid, slug, "s3a-imgprompt",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"made": len(made), "kept": len(keep_ids),
                             "fmt": fmt,
                             "asked": len(ask_ids), "missing": miss,
                             "ledger": len(book["by_id"])},
                       code_version=stage.code_version, cost_usd=cost,
                       status="degraded" if miss or warn else "ok",
                       warnings=warn + ([f"지시문이 없는 장 {len(miss)}개"] if miss else []))


STAGES["s3a-imgprompt"].run = run
