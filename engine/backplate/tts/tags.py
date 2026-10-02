"""Supertonic 3 표현 태그(expression tags) — 10종.

## 왜 이 파일이 필요한가

공식 문서는 태그가 10개라고만 하고 3개만 이름을 밝힌다.

  supertone-inc/supertonic README:
    "🎭 Expression Tags — 10 inline tags (e.g. <laugh>, <breath>, <sigh>)"

나머지 7개를 묻는 이슈 #155("What are all the Expression Tags?")는 답변 없이
남았고, 리포지토리는 2026-09-09에 아카이브됐다. 7개는 서드파티 통합
(Anonymzx/ComfyUI-Supertonic3TTS)의 표에서 가져왔고 개수가 공식 "10"과
일치한다 — 하지만 공식 확인은 아니다. 그래서 태그마다 출처(source)와 청취
검증 상태(verified)를 데이터로 들고 다닌다. 확인 안 된 걸 확인된 것처럼
쓰지 않기 위해서다.

## 모델이 태그를 처리하는 방식

Supertonic은 문자 단위(character-level) 모델이다. <laugh>는 특수 토큰이
아니라 학습된 7글자 리터럴이다 (<ko>...</ko> 언어 래퍼와 같은 메커니즘).
따라서:

  * 에셋 어디에도 태그 목록 파일이 없다 — unicode_indexer.json은 코드포인트
    → 임베딩 인덱스 배열일 뿐 문자열이 없다.
  * 모르는 태그는 에러 없이 조용히 실패한다. 글자로 읽히거나 무시된다.
    그래서 A/B 길이 비교가 유일한 정량 판정 수단이다 (표현 태그 실험실).

## 문법 제약 (벤더 전처리 코드에서 유도)

_vendor/supertonic_helper.py `UnicodeProcessor._preprocess_text`:

  * `replacements`가 "[", "]"를 공백으로 치환한다 → `[laugh]`는 " laugh "가
    되어 **영어 단어로 낭독된다**. 대괄호는 태그가 아니다.
  * `"_": " "` 도 있다 → `<throat_clear>`는 `<throat clear>`로 깨진다.
    실제 태그가 `<throatclear>`(붙임)인 것과 일관된다.
  * "<", ">"는 치환·제거 목록 어디에도 없고 indexer에서 유효한 인덱스를
    가진다 → 모델까지 그대로 전달된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 청취 검증 상태
VERIFIED_AUDIBLE = "audible"    # 확실히 들린다
VERIFIED_SILENCE = "silence"    # 짧은 정적만 삽입
VERIFIED_NONE = "none"          # 아무 효과 없음
VERIFIED_UNKNOWN = "unknown"    # 아직 안 들어봄

# 출처
SOURCE_OFFICIAL = "official"    # Supertone 공식 모델카드/README
SOURCE_COMMUNITY = "community"  # 서드파티 통합 문서 (개수는 공식과 일치)


@dataclass(frozen=True)
class ExpressionTag:
    tag: str            # "<laugh>"
    name: str           # "웃음"
    effect: str         # 한 줄 설명
    source: str         # SOURCE_*
    verified: str       # VERIFIED_* — 기본 추정값. config로 덮어쓴다.

    @property
    def word(self) -> str:
        """꺾쇠를 뺀 알맹이. "<laugh>" -> "laugh" """
        return self.tag[1:-1]


# 순서 = UI 칩 순서. 공식 3종을 앞에 둔다.
EXPRESSION_TAGS: tuple[ExpressionTag, ...] = (
    ExpressionTag("<laugh>", "웃음", "웃음소리를 넣는다", SOURCE_OFFICIAL, VERIFIED_AUDIBLE),
    ExpressionTag("<breath>", "숨소리", "숨을 들이쉰다", SOURCE_OFFICIAL, VERIFIED_SILENCE),
    ExpressionTag("<sigh>", "한숨", "한숨을 쉰다", SOURCE_OFFICIAL, VERIFIED_SILENCE),
    ExpressionTag("<surprise>", "놀람", "놀란 톤으로 바뀐다", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
    ExpressionTag("<scream>", "비명", "비명·외침", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
    ExpressionTag("<throatclear>", "헛기침", "목을 가다듬는다", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
    ExpressionTag("<sad>", "슬픔", "슬픈 톤으로 바뀐다", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
    ExpressionTag("<angry>", "화남", "화난 톤으로 바뀐다", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
    ExpressionTag("<cough>", "기침", "기침 소리", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
    ExpressionTag("<yawn>", "하품", "하품 소리", SOURCE_COMMUNITY, VERIFIED_UNKNOWN),
)

TAG_WORDS: tuple[str, ...] = tuple(t.word for t in EXPRESSION_TAGS)
BY_TAG: dict[str, ExpressionTag] = {t.tag: t for t in EXPRESSION_TAGS}

# 알려진 태그만 매칭. 대소문자 구분 없이 잡아서 <LAUGH> 같은 오타도 검출한다.
TAG_RE = re.compile(r"<(" + "|".join(TAG_WORDS) + r")>", re.IGNORECASE)

# 태그처럼 생겼지만 우리 목록에 없는 것 — 오타 경고용.
_TAGLIKE_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9 _-]{0,30})\s*>")

# 대괄호/괄호 형태의 흔한 착각. 태그가 아니라 글자로 읽힌다.
_FAKE_TAG_RE = re.compile(
    r"\[\s*(" + "|".join(TAG_WORDS) + r")\s*\]"
    r"|\(\s*(웃음|한숨|기침|하품|헛기침|숨소리)\s*\)",
    re.IGNORECASE,
)

# 발음 변환 중 태그를 숨겨둘 사용자 영역(Private Use Area) 문자.
# U+E000부터 태그 하나당 하나씩. 일반 텍스트에 나올 일이 없다.
_SENTINEL_BASE = 0xE000


def normalize(text: str) -> str:
    """<LAUGH>, < laugh > 같은 변형을 정규형 <laugh>로 맞춘다."""
    return TAG_RE.sub(lambda m: "<" + m.group(1).lower() + ">", text or "")


def find(text: str) -> list[str]:
    """텍스트에 실제로 들어있는 태그 목록 (정규형, 등장 순서, 중복 포함)."""
    return ["<" + m.group(1).lower() + ">" for m in TAG_RE.finditer(text or "")]


def strip(text: str) -> str:
    """태그를 제거한다. 자막(SRT)에 <laugh>가 찍히면 안 되므로 필수.

    태그를 지우면서 생긴 이중 공백과 " ," 같은 자국까지 정리한다.
    """
    out = TAG_RE.sub(" ", text or "")
    out = re.sub(r"\s+([,.!?;:…])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def protect(text: str) -> tuple[str, dict[str, str]]:
    """태그를 PUA 문자로 치환해 발음 변환에서 보호한다.

    발음사전은 긴 키 우선 정규식으로 치환하고, 사전에 없는 대문자 덩어리를
    글자별로 읽어준다(spell_unknown_acronyms). 태그를 날것으로 두면 그 규칙이
    태그 안쪽 글자를 건드릴 수 있다. 변환 전에 빼두고 끝나면 되돌린다.

    returns: (치환된 텍스트, {sentinel: 원래 태그})
    """
    text = normalize(text)
    mapping: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        tag = "<" + m.group(1).lower() + ">"
        idx = TAG_WORDS.index(m.group(1).lower())
        sentinel = chr(_SENTINEL_BASE + idx)
        mapping[sentinel] = tag
        return sentinel

    return TAG_RE.sub(_sub, text or ""), mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    for sentinel, tag in mapping.items():
        text = text.replace(sentinel, tag)
    return text


def validate(text: str) -> list[str]:
    """사용자에게 보여줄 경고 목록. 합성을 막지는 않는다."""
    warnings: list[str] = []
    known = {t.lower() for t in TAG_WORDS}

    for m in _TAGLIKE_RE.finditer(text or ""):
        word = m.group(1)
        # 공백·밑줄·하이픈을 지운 뒤 비교한다. 벤더 전처리가 "_"를 공백으로
        # 바꾸므로 <throat_clear>는 <throat clear>로 깨져 태그로 안 먹힌다.
        squashed = re.sub(r"[\s_-]+", "", word).lower()
        if squashed not in known:
            warnings.append(
                f"'{m.group(0)}' 는 지원 태그가 아닙니다. 이대로 두면 에러 없이 "
                f"글자로 읽히거나 무시됩니다. 지원 태그: {', '.join(t.tag for t in EXPRESSION_TAGS)}"
            )
        elif m.group(0) != f"<{squashed}>":
            warnings.append(
                f"'{m.group(0)}' — 태그는 소문자로, 공백·밑줄 없이 붙여 써야 합니다. "
                f"'<{squashed}>' 로 고치세요."
            )

    for m in _FAKE_TAG_RE.finditer(text or ""):
        bracket = "대괄호" if m.group(0).startswith("[") else "괄호"
        warnings.append(
            f"'{m.group(0)}' 는 태그가 아닙니다 — {bracket} 형태는 그냥 글자로 "
            f"낭독됩니다. 꺾쇠 형태로 쓰세요."
        )

    return warnings


def as_dicts(overrides: dict[str, str] | None = None) -> list[dict]:
    """UI/API용 직렬화. overrides로 청취 검증 결과를 덮어쓴다."""
    ov = overrides or {}
    return [
        {
            "tag": t.tag,
            "word": t.word,
            "name": t.name,
            "effect": t.effect,
            "source": t.source,
            "verified": ov.get(t.tag, t.verified),
            "official": t.source == SOURCE_OFFICIAL,
        }
        for t in EXPRESSION_TAGS
    ]
