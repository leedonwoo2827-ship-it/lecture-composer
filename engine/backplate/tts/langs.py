"""Supertonic 3가 지원하는 31개 언어 + 언어 무관(na) 모드.

Supertonic 2는 5개 언어(en/ko/es/pt/fr)뿐이었고, 벤더된 helper의
AVAILABLE_LANGS가 그 시절 값에서 갱신되지 않은 채 남아 있었다. 그래서
ja/de/ru 같은 나머지 26개 언어를 넘기면 ValueError로 거부됐다.

출처: https://github.com/supertone-inc/supertonic README "Supported Languages"
      "Synthesize directly from text across 31 languages, or pass lang="na"
       to let Supertonic process the text language-agnostically"
"""
from __future__ import annotations

# (code, 한국어 표기, 영문 표기)
LANGUAGES: list[tuple[str, str, str]] = [
    ("ko", "한국어", "Korean"),
    ("en", "영어", "English"),
    ("ja", "일본어", "Japanese"),
    ("ar", "아랍어", "Arabic"),
    ("bg", "불가리아어", "Bulgarian"),
    ("cs", "체코어", "Czech"),
    ("da", "덴마크어", "Danish"),
    ("de", "독일어", "German"),
    ("el", "그리스어", "Greek"),
    ("es", "스페인어", "Spanish"),
    ("et", "에스토니아어", "Estonian"),
    ("fi", "핀란드어", "Finnish"),
    ("fr", "프랑스어", "French"),
    ("hi", "힌디어", "Hindi"),
    ("hr", "크로아티아어", "Croatian"),
    ("hu", "헝가리어", "Hungarian"),
    ("id", "인도네시아어", "Indonesian"),
    ("it", "이탈리아어", "Italian"),
    ("lt", "리투아니아어", "Lithuanian"),
    ("lv", "라트비아어", "Latvian"),
    ("nl", "네덜란드어", "Dutch"),
    ("pl", "폴란드어", "Polish"),
    ("pt", "포르투갈어", "Portuguese"),
    ("ro", "루마니아어", "Romanian"),
    ("ru", "러시아어", "Russian"),
    ("sk", "슬로바키아어", "Slovak"),
    ("sl", "슬로베니아어", "Slovenian"),
    ("sv", "스웨덴어", "Swedish"),
    ("tr", "터키어", "Turkish"),
    ("uk", "우크라이나어", "Ukrainian"),
    ("vi", "베트남어", "Vietnamese"),
]

# 언어를 지정하지 않고 모델이 알아서 처리하게 하는 모드. 여러 언어가 한 문장에
# 섞여 있을 때 쓴다. 31개 언어 목록과는 성격이 달라 따로 둔다.
LANG_AGNOSTIC = ("na", "자동 (언어 무관)", "Language-agnostic")

ALL_LANGS: list[tuple[str, str, str]] = LANGUAGES + [LANG_AGNOSTIC]
LANG_CODES: list[str] = [c for c, _, _ in ALL_LANGS]
DEFAULT_LANG = "ko"


def is_supported(code: str) -> bool:
    return (code or "").strip().lower() in LANG_CODES


def normalize(code: str | None) -> str:
    """알 수 없는 코드는 조용히 기본값으로 떨어뜨리지 않고 그대로 돌려준다.

    엔진이 ValueError를 내야 사용자가 오타를 알아챈다. 빈 값만 기본값 처리.
    """
    c = (code or "").strip().lower()
    return c or DEFAULT_LANG


def label(code: str) -> str:
    c = normalize(code)
    for k, ko, en in ALL_LANGS:
        if k == c:
            return f"{ko} · {en} ({k})"
    return c


def as_dicts() -> list[dict]:
    return [{"code": c, "ko": ko, "en": en} for c, ko, en in ALL_LANGS]
