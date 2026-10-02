# -*- coding: utf-8 -*-
"""showcase.config.json 로더.

**환경변수 → 파일 → 기본값** 순으로 덮는다. 파일에 없는 키가 있어도 기본값으로
메워지므로, 설정 파일을 갱신하지 않은 동료의 PC 에서도 그냥 돈다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("SHOWCASE_CONFIG") or (APP_DIR / "showcase.config.json"))

# ★ 내 PC 전용 값은 여기로 뺀다 — **배포본에 개인 절대경로가 나가면 안 된다.**
#   TTS 엔진 위치, 실측 보정값처럼 사람마다 다른 것이 여기 산다. gitignore 대상이고,
#   없으면 그냥 없는 대로 돈다(TTS 는 건너뛰고 덱·자막은 전부 나온다).
LOCAL_PATH = APP_DIR / "showcase.config.local.json"

DEFAULTS: Dict[str, Any] = {
    "port": 5178,
    "auth": "claude-code",
    "vision_mode": "inline",
    "models": {
        "caption": "claude-sonnet-5",
        "link": "claude-sonnet-5",
        "decisions": "claude-opus-5",
        "script": "claude-opus-5",
        "theme": "claude-opus-5",
        "imgprompt": "claude-opus-5",
    },
    "effort": {
        "caption": "medium", "link": "medium",
        "decisions": "high", "script": "high", "theme": "medium",
        "imgprompt": "medium",
    },
    "budget_usd": {"per_stage": 1.5, "warn_total": 5.0},
    "frames": {
        "scene_threshold": 0.35, "anchor_interval": 8.0, "min_gap_sec": 1.5,
        "max_frames": 12, "display_width": 1600, "vision_width": 1024,
    },
    "narration": {"chars_per_sec": 3.0, "voice": "F2", "speed": 1.0, "total_step": 8},
    "tts": {"engine": "none", "python": None, "voicewright_dir": None,
            "assets_dir": None, "timeout_ms": 300000},
    # 모션 리마스터 — 완성 mp4 를 **재료로** 다시 굽는 별도 도구(motion-remaster).
    # ★ 이 앱 안에 넣지 않는다. 완성본을 받아 새 파일을 내는 뒷단계이고, 여기
    #   파이프라인과 아무것도 공유하지 않는다. 폴더 하나만 가리킨다 —
    #   `09_이미지` 를 이미지 스튜디오와 주고받는 방식과 같다.
    # ★ 없으면 없는 대로 돈다. 모션 화면이 "폴더를 알려 주세요" 만 띄운다.
    "motion": {"tool_dir": None, "python": None},
    "render": {"seed_hex": "#7a5cc0", "max_single_file_mb": 10,
               "single_file_audio": "opus32"},
    # ★ 산출물 규격 — 교육기관 제출 기준을 **설정으로 못박는다.**
    #   숫자가 코드에 흩어져 있으면 「우리 영상 규격이 뭔가」에 답할 데가 없다.
    #   ffprobe 로 재서 이 값과 대조하면 끝난다.
    #   −16 LUFS 는 **스테레오 기준**이다. 모노면 같은 체감이 −19 라 어긋난다.
    "video": {
        "width": 1920, "height": 1080, "fps": 30,
        "vcodec": "libx264", "crf": 20, "preset": "medium",
        "profile": "high", "level": "4.0",
        "acodec": "aac", "abitrate": "192k", "ar": 48000, "ac": 2,
        "loudnorm": {"i": -16.0, "tp": -1.5, "lra": 11.0},
    },
    # ★ 자막은 **만들되 띄우지 않는다.** 규격은 추후 범용성을 위해
    #   세워만 둔다 — 지금은 사이드카 SRT 로만 나간다.
    #   현재 vendor/vw_srt.py 의 규칙은 55자 한 줄뿐이고 CPS·최소·최대가 없다.
    "subtitle": {"max_lines": 2, "max_chars": 42, "cps": 14.0,
                 "min_sec": 1.5, "max_sec": 7.0, "burn_in": False},
    # 원고를 장으로 나눌 때
    "capture": {
        "mode": "html",
        # 그림 한 줄(`<svg>`)을 보는 데 주는 시간. 글자 수로 재지 않는다 —
        # 이유는 `core/htmldoc.auto_ats()` 주석에 있다.
        "fig_sec": 3.0,
    },
    # 슬라이드 그림 — 이미지 스튜디오에 넘길 프롬프트의 문체와 규격.
    # ★ 이 그림은 **몸통을 대신한다**(뒤에 까는 배경이 아니다). 제목만 위에 남고
    #   1920×1080 한 판을 그림이 채운다. 그래서 가로로 꽉 차야 한다.
    "image": {
        "aspect": "landscape",          # gpt-image 네이티브: 1536×1024 (3:2)
        # ★ 바탕색. **강조색보다 먼저 적어야 한다** — 자세한 이유는
        #   `s3a_imgprompt.compose()` 주석에 있다. 덱의 액자가 아이보리라
        #   어두운 그림이 오면 한 화면에서 결이 갈린다.
        "bg": "#F6F1E8",
        "accent_a": "#1F4E79",          # 원고 SVG 의 파랑 네 단과 같은 결로
        "accent_b": "#9DC3E6",
        # ★ **어두운 배경을 여기서도 막는다.** 본문에 「바탕은 반드시 밝은
        #   아이보리」라고 적어 두었는데도 한 번씩 검은 판으로 나온다
        #   (2026-08-17 실측: 20장 12개 중 006·010 둘. 19장에서도 003 이 그랬다).
        #   본문은 길어서 뒤로 밀리지만 negative 는 짧아 잘 듣는다.
        "negative": ("dark background, black background, night scene, "
                     "dark panel, low contrast text, "
                     "watermark, logo, low quality, distorted, extra limbs"),
        # 그림을 몸통 대신 깔까. 기본은 **꺼짐** — 켜기 전까지 지금과 똑같이 돈다.
        "swap": False,
    },
}


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_cache: Dict[str, Any] | None = None


def load(force: bool = False) -> Dict[str, Any]:
    global _cache
    if _cache is not None and not force:
        return _cache
    file_cfg: Dict[str, Any] = {}
    if CONFIG_PATH.is_file():
        try:
            # ★ utf-8-sig — BOM 을 허용한다. 메모장이나 PowerShell 의
            #   Set-Content -Encoding UTF8 은 BOM 을 붙이는데, 순수 utf-8 로 읽으면
            #   "Unexpected UTF-8 BOM" 으로 통째로 터진다(실제로 겪음).
            file_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{CONFIG_PATH.name} 를 읽지 못했습니다: {e}") from e
    # 내 PC 전용 덮어쓰기 — 있으면 마지막에 이긴다
    local_cfg: Dict[str, Any] = {}
    if LOCAL_PATH.is_file():
        try:
            local_cfg = json.loads(LOCAL_PATH.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{LOCAL_PATH.name} 를 읽지 못했습니다: {e}") from e

    cfg = _deep_merge(_deep_merge(DEFAULTS, file_cfg), local_cfg)
    if p := os.environ.get("PORT") or os.environ.get("SHOWCASE_PORT"):
        try:
            cfg["port"] = int(p)
        except ValueError:
            pass
    _cache = cfg
    return cfg


# 이 키들은 **사람마다 다른 값**이라 배포본이 아니라 local 파일로 간다
LOCAL_KEYS = {"tts", "motion"}


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """설정 화면에서 바꾼 값만 덮어쓴다. 파일에 없던 키는 그대로 둔다.

    ★ `tts` 처럼 절대경로가 들어가는 키는 `showcase.config.local.json` 으로 보낸다.
      배포본 설정 파일에 내 PC 경로가 섞이면 동료가 받았을 때 엉뚱한 곳을 가리킨다.
    """
    local_patch = {k: v for k, v in (patch or {}).items() if k in LOCAL_KEYS}
    patch = {k: v for k, v in (patch or {}).items() if k not in LOCAL_KEYS}
    if local_patch:
        cur_local: Dict[str, Any] = {}
        if LOCAL_PATH.is_file():
            try:
                cur_local = json.loads(LOCAL_PATH.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                cur_local = {}
        LOCAL_PATH.write_text(
            json.dumps(_deep_merge(cur_local, local_patch), ensure_ascii=False, indent=2),
            encoding="utf-8")

    cur: Dict[str, Any] = {}
    if CONFIG_PATH.is_file():
        try:
            cur = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            cur = {}
    merged = _deep_merge(cur, patch or {})
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return load(force=True)
