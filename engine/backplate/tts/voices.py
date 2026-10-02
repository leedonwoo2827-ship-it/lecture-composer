from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

ALL_VOICE_CODES = ["M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"]

# voice_map.yaml 이 없거나 그 안의 default 가 잘못됐을 때 쓸 화자.
# 예전에는 "파일 없음"이면 F2, "default 값이 이상함"이면 M5 로 서로 다르게
# 떨어져서, 같은 상황을 어떻게 실패했느냐에 따라 목소리가 바뀌었다.
# 배포되는 config/voice_map.yaml 의 default 와 같은 값으로 통일한다.
FALLBACK_VOICE = "M5"


@dataclass(frozen=True)
class VoiceInfo:
    code: str
    gender: str
    preset_path: Path


def list_voices(voice_styles_dir: Path) -> list[VoiceInfo]:
    voices = []
    for code in ALL_VOICE_CODES:
        p = voice_styles_dir / f"{code}.json"
        gender = "male" if code.startswith("M") else "female"
        voices.append(VoiceInfo(code=code, gender=gender, preset_path=p))
    return voices


@dataclass
class VoiceMap:
    default: str
    styles: dict[str, str]                # lowercase 키

    def resolve(self, voice_style: str | None) -> tuple[str, str | None]:
        """returns (resolved_code, warning_or_none)."""
        if not voice_style:
            return self.default, None

        key = voice_style.strip().lower()
        if not key:
            return self.default, None

        if key in self.styles:
            return self.styles[key], None

        if any(t in key for t in ("female", "여성")):
            return "F2", f"unmapped voice_style '{voice_style}' → F2 (female heuristic)"
        if any(t in key for t in ("male", "남성")):
            return "M3", f"unmapped voice_style '{voice_style}' → M3 (male heuristic)"

        return self.default, f"unmapped voice_style '{voice_style}' → {self.default} (default)"


def load_voice_map(path: Path) -> VoiceMap:
    if not path.exists():
        logger.warning(
            "voice_map.yaml을 찾을 수 없습니다 (%s). 기본값 %s로 동작합니다.", path, FALLBACK_VOICE
        )
        return VoiceMap(default=FALLBACK_VOICE, styles={})

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    default = str(data.get("default", FALLBACK_VOICE)).upper()
    if default not in ALL_VOICE_CODES:
        logger.warning(
            "voice_map.yaml의 default '%s'가 유효하지 않아 %s로 대체합니다.", default, FALLBACK_VOICE
        )
        default = FALLBACK_VOICE

    styles: dict[str, str] = {}
    for k, v in (data.get("styles") or {}).items():
        code = str(v).upper()
        if code not in ALL_VOICE_CODES:
            logger.warning("voice_map.yaml의 styles.%s='%s'가 유효하지 않아 무시합니다.", k, v)
            continue
        styles[str(k).strip().lower()] = code

    return VoiceMap(default=default, styles=styles)


def voice_preset_path(voice_styles_dir: Path, code: str) -> Path:
    code = code.upper()
    if code not in ALL_VOICE_CODES:
        raise ValueError(f"알 수 없는 보이스 코드: {code}. 사용 가능: {ALL_VOICE_CODES}")
    p = voice_styles_dir / f"{code}.json"
    if not p.exists():
        raise FileNotFoundError(f"보이스 프리셋이 없습니다: {p}")
    return p
