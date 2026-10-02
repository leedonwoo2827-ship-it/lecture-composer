# -*- coding: utf-8 -*-
"""순서 번호 — **이 표가 유일한 출처다.**

단계가 열여섯 개인데 사람이 실제로 누르는 것은 일곱 개뿐이다. 그런데 자리마다
이름이 조금씩 다르다 — 덱의 버튼은 행동을 말하고(「발음대본 생성」) 오른쪽 이력은
산출물을 말한다(「내레이션 대본」). 같은 일인지 다른 일인지가 안 읽혀서 늘 이
질문이 남았다:

    "지금이 3번 할 타이밍인가 4번 할 타이밍인가" (2026-08-14)

이름은 그대로 두고 **번호가 둘을 잇는다.** 다음 숫자를 누르면 된다.

★ 번호는 실행 순서(registry.ORDER)가 아니라 **사람이 누르는 순서**다. 둘은 다르다.
★ 안 쓰는 번호가 있어도 된다. 원고(HTML)로 만드는 발표에는 영상이 없어 1번이
  영영 안 돈다 — 그때는 2번부터 시작하면 된다. 번호를 촘촘히 메우려고 프로젝트
  종류마다 다르게 매기면, 번호가 가리키는 것이 그때그때 달라져 "다음 숫자" 라는
  감각 자체가 무너진다.
★ 이름은 **단계 라벨의 낱말을 그대로** 쓴다(2026-08-14: "최근 한 일에 있는
  단어들이 교육공학적으로 맞는 것 같습니다").
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

STEPS: List[Dict[str, Any]] = [
    {"n": 1, "name": "재료 모으기",
     "tip": "프레임 추출 · 레포 수집 · 쓸 컷 고르기 · 슬라이드 이미지",
     "keys": ["s1-frames", "s2-repo", "s3-caption", "s3b-images"]},
    {"n": 2, "name": "구조 설계",
     "tip": "몇 장으로 어떻게 나눌지 — 원고 구조 읽기도 여기입니다",
     "keys": ["s0a-ask", "s0-prd", "s2b-outline", "s2c-capture"]},
    {"n": 3, "name": "슬라이드 문구",
     "tip": "화면에 박히는 글 — 기술적 의사결정 포함",
     "keys": ["s5-decisions", "s7-copy"]},
    {"n": 4, "name": "배경음악",
     "tip": "굽기 전에 정합니다 — 안 넣어도 됩니다",
     "keys": ["bgm"]},
    {"n": 5, "name": "자막 대본",
     "tip": "화면에 보이는 원문 — 여기서 글이 정해집니다",
     "keys": ["s6-script"]},
    # ★ 자막과 발음을 **가른다**(2026-08-17). 손이 가는 순서가 「자막을 읽고
    #   고친다 → 그 자막대로 발음을 만든다」이기 때문이다. 한 번에 만들면 자막을
    #   고쳐도 발음은 옛 자막에서 나온 채로 남는다 — 20장에서 실제로 그랬다.
    #   스테이지가 아니라 창구다(`/api/projects/{pid}/pronounce-all`). 자막을
    #   읽어 괄호·어미·숫자만 바꾸는 결정론이라 공짜이고 몇 초다.
    {"n": 6, "name": "발음 대본",
     "tip": "그 자막을 소리 나는 대로 — 괄호 걷기 · 하십시오체 · 숫자 · 퍼센트",
     "keys": ["pronounce"]},
    {"n": 7, "name": "완성본 굽기",
     "tip": "음성 합성 · 자막 · 덱 조립 · 완성본 렌더",
     "keys": ["s10-tts", "s11-audio", "s8-assemble", "s9-render"]},
    {"n": 8, "name": "영상 렌더",
     "tip": "장마다 화면을 찍어 mp4 하나로 잇습니다",
     "keys": ["s12-video"]},
]

BY_KEY: Dict[str, Dict[str, Any]] = {}
for _s in STEPS:
    for _k in _s["keys"]:
        BY_KEY[_k] = _s

# 손으로 고친 것은 순서에 없다 — 아무 때나 일어난다. 다만 **어느 단계보다 앞이냐**
# 는 정해야 낡음을 판정할 수 있다. 문구·대본을 손보는 일이므로 굽기(7) 앞이다.
HAND_BEFORE = 7


def of(key: Optional[str]) -> Optional[Dict[str, Any]]:
    """스테이지 키(또는 산출물 파일 이름) → 그 단계. 모르면 None."""
    if not key:
        return None
    hit = BY_KEY.get(key)
    if hit:
        return hit
    s = str(key).lower()
    if s.endswith(".mp4"):
        return BY_KEY["s12-video"]
    if s.endswith(".html"):
        return BY_KEY["s9-render"]
    return None


def n_of(key: Optional[str]) -> Optional[int]:
    st = of(key)
    return st["n"] if st else None
