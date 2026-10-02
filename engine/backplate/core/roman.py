# -*- coding: utf-8 -*-
"""영문을 **한국어 소리로** 바꾼다 — 발음 칸 전용.

    자막   먼저 FROM 으로 어느 테이블에서 가져올지 정하고, GROUP BY 로 묶고
    발음   먼저 프롬 으로 어느 테이블에서 가져올지 정하고, 그룹 바이 로 묶고

★ **자막은 건드리지 않는다.** 화면에는 `SELECT` 라고 떠야 한다 — 그것이 배우는
  내용이다. 소리로만 「셀렉트」가 되면 된다.

★ **발음 칸의 글자를 바꾼다**(합성 직전에 몰래 바꾸지 않는다). 이 앱의 규칙은
  하나다 — **발음 칸에 보이는 대로 소리가 난다.** 사전이 뒤에서 바꿔 버리면 화면에는
  `FROM` 인데 소리는 「프롬」이 되어 사람이 눈으로 검수할 수가 없다(2026-08-23 에
  그렇게 만들어 90장에서 화면과 소리가 갈렸다).

★ **표는 voicewright 사전 하나뿐이다** — `voicewright/config/pronunciation_map.yaml`.
  거기에 이미 쌓아 둔 것이 있고(교육 용어 60여 개), voicewright 의 `/dict` 화면에서
  편집할 수 있다. 파이썬에 표를 또 두면 두 벌이 되어 언젠가 서로 다르게 읽는다.
  **새 용어는 그 파일에 한 줄 넣으면 여기까지 따라온다.**

★ 표에 없는 영문은 **글자 이름으로 읽는다**(`ABC` → 「에이비씨」). 사전에 없는 약자를
  영어 소리로 흘리는 것보다 또박또박 읽어 주는 편이 강의에서 낫다.

★ PyYAML 을 쓰지 않고 직접 읽는다. 의존성 하나가 동료 PC 의 setup 을 깨뜨리는 일이
  잦고(`server.py` 의 base64 주석과 같은 판단), 이 파일은 `키: 값` 한 줄씩이라
  그럴 필요가 없다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Tuple

# 알파벳 이름. Z 는 「제트」다 — 한국 강의에서 그렇게 읽는다.
LETTER = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프",
    "G": "지", "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘",
    "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
    "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유",
    "X": "엑스", "Y": "와이", "Z": "제트",
}

# `  KEY: VALUE` — 키에 공백이 들어갈 수 있다(`GROUP BY`). 주석·빈 줄은 건너뛴다.
_LINE = re.compile(r"^\s{1,4}(?!#)([^:#\n]+?)\s*:\s*(.+?)\s*$")
_UNQUOTE = re.compile(r'^(["\'])(.*)\1$')

_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}


def dict_path() -> Optional[Path]:
    """사전 파일 자리. `assets_dir` 의 부모가 voicewright 뿌리다."""
    from core import config

    tts = config.load().get("tts") or {}
    for base in (tts.get("assets_dir"), tts.get("voicewright_dir")):
        if not base:
            continue
        b = Path(str(base))
        for cand in (b.parent / "config" / "pronunciation_map.yaml",
                     b / "config" / "pronunciation_map.yaml",
                     b / "voicewright" / "config" / "pronunciation_map.yaml"):
            if cand.is_file():
                return cand
    return None


def rules() -> Dict[str, str]:
    """사전을 읽는다. **고치면 바로 반영된다** — 파일 시각으로 다시 읽는다."""
    p = dict_path()
    if p is None:
        return {}
    key = str(p)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]

    out: Dict[str, str] = {}
    started = False
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not started:
            started = s == "rules:"
            continue
        if not s or s.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break                      # `rules:` 블록이 끝났다
        m = _LINE.match(line)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        mq = _UNQUOTE.match(v)
        if mq:
            v = mq.group(2)
        if k and v:
            out[k] = v
    _cache[key] = (mtime, out)
    return out


def _spell(word: str) -> str:
    return "".join(LETTER.get(c.upper(), c) for c in word)


# ★ 글자 이름으로 읽어도 되는 것은 **짧은 대문자 약어**뿐이다(`SQL`·`DDL`·`API`).
#   `DECODE` 를 그렇게 읽으면 「디이씨오디이」가 되어 못 알아듣는다(2026-08-23 실측).
#   낱말처럼 생긴 것은 **건드리지 않고 그대로 둔다** — 사전에 넣어 주기 전까지는
#   모델이 읽는 소리가 글자 이름보다 낫다. 무엇이 빠졌는지는 사전 화면이 알려 준다.
_ACRONYM_MAX = 4


def is_acronym(word: str) -> bool:
    w = word.replace("_", "")
    return w.isupper() and 2 <= len(w) <= _ACRONYM_MAX


def spell(word: str) -> str:
    """글자 이름으로 읽기. 짧은 대문자 약어가 아니면 **빈 값**을 돌려준다 —
    사전 화면이 첫 제안으로 쓰는데, 엉뚱한 제안은 없느니만 못하다."""
    return _spell(word.replace("_", " ")) if is_acronym(word) else ""


def forget() -> None:
    """사전을 저장한 뒤 부른다 — 다음 호출에서 다시 읽게 한다."""
    _cache.clear()


def find_roman(text: str) -> list:
    """글 속의 영문 낱말을 모은다 — **사전에 무엇이 빠졌는지** 세는 데 쓴다.

    ★ 두 글자 이상만 센다. 한 글자는 수식 기호일 때가 많다(`n`·`x`·`k`).
    """
    return _REST_RE.findall(text or "") if text else []


# 표에 없이 남은 영문 덩어리. 두 글자 이상만 — 한 글자는 수식 기호일 때가 많다(`n`·`x`).
_REST_RE = re.compile(r"(?<![A-Za-z])[A-Za-z][A-Za-z_]{1,}(?![A-Za-z])")

# ★ **조사를 붙여 준다.** 자막은 영문 뒤 조사를 띄어 쓴다 — 「NULL 을」·「DECODE 와」.
#   영문일 때는 그게 읽기 좋은데, 한글로 바꾸고 나면 「널 을」·「디코드 와」가 되어
#   조사가 딴 낱말처럼 뚝 떨어져 읽힌다(2026-08-23). 그래서 **우리가 바꾼 자리
#   바로 뒤에 붙은 조사만** 한 칸을 지운다. 원래 한글 문장의 띄어쓰기는 안 건드린다 —
#   그쪽은 이미 조사가 붙어 있고, 규칙으로 훑으면 「수 도」 같은 멀쩡한 말을 망친다.
_JOSA = ("은|는|이가|이|가|을|를|와|과|의|에서|에게|에|으로|로|도|만|밖에|부터|까지"
         "|처럼|같이|보다|이나|나|이란|란|이라|라|인지|인|이고|고|이며|며|이든|든"
         "|조차|마저|이야|야|이다|다")
# 조사 뒤에 한글이 이어지면 낱말의 일부다 — 「널 인지를」의 「인지」는 붙이고
# 「널 인기」의 「인기」는 안 붙인다. 그래서 조사 다음이 한글이 아닐 때만 붙인다.
_TAIL = r"(?:[ \t]+(" + _JOSA + r")(?![가-힣]))?"


def speak_roman(text: str, *, spell_rest: bool = True) -> str:
    """영문을 한국어 소리로. 한글·숫자·기호는 건드리지 않는다.

    ★ 긴 키부터 잡는다 — `GROUP BY` 가 `GROUP` 보다, `NOT NULL` 이 `NOT` 보다
      먼저 걸려야 「그룹 바이」가 된다(안 그러면 「그룹 비와이」).
    ★ 경계는 **라틴 글자만** 막는다. `\b` 를 쓰면 파이썬이 한글도 낱말로 봐서
      `FROM 으로` 같은 조사 결합형을 놓친다(voicewright 사전이 같은 이유로 그렇게 한다).
    """
    if not text:
        return text
    tbl = rules()
    if tbl:
        keys = sorted(tbl, key=len, reverse=True)
        pat = re.compile(r"(?<![A-Za-z])("
                         + "|".join(map(re.escape, keys)) + r")(?![A-Za-z])" + _TAIL)
        text = pat.sub(lambda m: tbl[m.group(1)] + (m.group(2) or ""), text)
    if spell_rest:
        # 짧은 대문자 약어만 글자 이름으로. 나머지는 그대로 두고 사전에 채운다.
        rest = re.compile(_REST_RE.pattern.replace("(?<![A-Za-z])", "(?<![A-Za-z])(", 1)
                          .replace("(?![A-Za-z])", ")(?![A-Za-z])", 1) + _TAIL)
        text = rest.sub(
            lambda m: ((_spell(m.group(1).replace("_", " ")) + (m.group(2) or ""))
                       if is_acronym(m.group(1)) else m.group(0)), text)
    # 바꾼 자리마다 조사가 붙어 「프롬 으로」가 된다 — 두 칸 이상은 한 칸으로
    return re.sub(r"[ \t]{2,}", " ", text)
