from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import numpy as np

from . import settings as settings_module
from ._assets_check import check_assets
from ._vendor.supertonic_helper import (
    Style,
    TextToSpeech,
    load_text_to_speech_with_providers,
    load_voice_style,
)
from . import langs, tags
from .pronunciation import PronunciationMap, load_pronunciation_map
from .voices import voice_preset_path

logger = logging.getLogger(__name__)


# 한국어 긴 문장에서 Supertonic alignment가 흔들려 중간 단어를 통째로 누락하는
# 증상이 보고됨 (예: 4문장·115자 한 덩어리 입력에서 "로부터", "지식의" 드롭).
# 벤더된 helper의 chunk_text(max_len=120)는 너무 관대해서 한국어 음절 밀도엔
# 부족하다. 우리 레이어에서 항상 문장 단위로 자르고, 한 문장이 길면 쉼표
# 기준으로 추가 분할한 뒤 조각별로 따로 합성해 붙인다.
_SENT_END_RE = re.compile(r"(?<=[.!?。！？…])\s+")
_COMMA_RE = re.compile(r"(?<=[,，、])\s+")
_TTS_MAX_CHARS = 60
_INTER_PIECE_SILENCE_SEC = 0.18


def _is_tagonly(piece: str) -> bool:
    """표현 태그(와 구두점)만 남은 조각인가.

    이런 조각을 따로 합성하면 앞뒤로 0.18초 무음이 붙어 어색해지고, 모델도
    문맥 없이 태그 하나만 보게 된다. 앞 조각에 도로 붙여야 한다.
    """
    return not tags.strip(piece).strip(" .,!?;:…").strip()


def _split_for_tts(text: str, max_chars: int = _TTS_MAX_CHARS) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    out: list[str] = []
    for sent in _SENT_END_RE.split(text):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= max_chars:
            out.append(sent)
            continue
        parts = [p.strip() for p in _COMMA_RE.split(sent) if p.strip()]
        cur = ""
        for p in parts:
            if not cur:
                cur = p
            elif len(cur) + 1 + len(p) <= max_chars:
                cur = cur + " " + p
            else:
                out.append(cur)
                cur = p
        if cur:
            out.append(cur)

    # 태그만 있는 조각은 직전 조각에 흡수시킨다. 맨 앞이면 다음 조각에 붙인다.
    merged: list[str] = []
    for piece in out:
        if _is_tagonly(piece) and merged:
            merged[-1] = merged[-1] + " " + piece
        else:
            merged.append(piece)
    if len(merged) > 1 and _is_tagonly(merged[0]):
        merged[1] = merged[0] + " " + merged[1]
        merged.pop(0)
    return merged


# GPU 프로바이더 실사용 가능 여부 프로브 결과 캐시.
# (프로바이더 이름 -> 실제로 세션이 만들어지는가)
_PROBE_CACHE: dict[str, bool] = {}


def _probe_provider(provider: str, onnx_dir: Path) -> bool:
    """그 프로바이더로 세션이 진짜 만들어지는지 실제 모델 하나로 확인한다.

    `ort.get_available_providers()` 는 **빌드에 포함됐는지**만 알려준다. 런타임
    DLL(cublasLt64_13.dll 등)이 없어도 CUDAExecutionProvider 는 목록에 그대로
    들어있다. 그 상태로 4개 모델을 로드하면 모델마다 CUDA 초기화가 실패하며
    긴 에러 스택이 네 번 찍히고, 결국 CPU 로 조용히 떨어진다 — 사용자는 GPU 로
    도는 줄 안다.

    그래서 가장 작은 모델(duration_predictor, 약 3.6MB)로 한 번만 찔러보고,
    안 되면 아예 목록에서 뺀다. 로그는 한 줄로 끝나고 로딩도 빨라진다.
    """
    if provider in _PROBE_CACHE:
        return _PROBE_CACHE[provider]

    ok = False
    try:
        import onnxruntime as ort

        probe_model = onnx_dir / "duration_predictor.onnx"
        if not probe_model.exists():
            candidates = sorted(onnx_dir.glob("*.onnx"), key=lambda p: p.stat().st_size)
            probe_model = candidates[0] if candidates else None

        if probe_model is not None:
            # 프로브가 실패하는 건 예상된 경우다. ORT 의 C++ 로거가 뱉는 긴 스택은
            # 우리가 대신 한 줄로 설명하므로 잠시 막는다. SessionOptions 의
            # log_severity_level 로는 못 막힌다 - 프로바이더 브리지 오류는 세션이
            # 만들어지기 전에 전역 로거로 나간다.
            ort.set_default_logger_severity(4)          # 4 = Fatal
            try:
                sess = ort.InferenceSession(
                    str(probe_model), ort.SessionOptions(), providers=[provider]
                )
                ok = provider in sess.get_providers()
                del sess
            finally:
                ort.set_default_logger_severity(2)      # 2 = Warning (ORT 기본값)
    except Exception as exc:
        logger.debug("%s 프로브 실패: %s", provider, exc)
        ok = False

    _PROBE_CACHE[provider] = ok
    return ok


def _select_providers(use_gpu: bool, onnx_dir: Path | None = None) -> list[str]:
    if not use_gpu:
        return ["CPUExecutionProvider"]
    try:
        import onnxruntime as ort
        available = set(ort.get_available_providers())
    except Exception:
        available = set()

    preferred = ["CUDAExecutionProvider", "DmlExecutionProvider"]
    chosen = [p for p in preferred if p in available]

    # 목록에 있다고 되는 게 아니다. 실제로 세션이 만들어지는 것만 남긴다.
    if onnx_dir is not None:
        usable = []
        for p in chosen:
            if _probe_provider(p, onnx_dir):
                usable.append(p)
            else:
                logger.warning(
                    "%s 를 쓸 수 없어 CPU 로 실행합니다. onnxruntime-gpu 가 요구하는 "
                    "CUDA/cuDNN 런타임이 없거나 버전이 안 맞습니다. Supertonic 3 는 CPU "
                    "에서도 잘 돌아갑니다. 이 안내를 없애려면 SUPERTONIC_USE_GPU=0 으로 두세요.",
                    p,
                )
        chosen = usable

    chosen.append("CPUExecutionProvider")
    return chosen


class Engine:
    _instance: "Engine | None" = None
    _init_lock = asyncio.Lock()

    def __init__(self, onnx_dir: Path, voice_styles_dir: Path, use_gpu: bool):
        check_assets(onnx_dir, voice_styles_dir)
        providers = _select_providers(use_gpu, onnx_dir)
        logger.info("Loading Supertonic engine from %s with providers=%s", onnx_dir, providers)
        self._tts: TextToSpeech = load_text_to_speech_with_providers(str(onnx_dir), providers)
        self._infer_lock = asyncio.Lock()
        self.providers = providers
        self.use_gpu_active = "CUDAExecutionProvider" in providers or "DmlExecutionProvider" in providers
        self.sample_rate: int = int(self._tts.sample_rate)
        self._voice_styles_dir = voice_styles_dir
        self._style_cache: dict[str, Style] = {}
        self._pmap: PronunciationMap | None = None
        self._pmap_mtime: float = -1.0

    def _get_pmap(self) -> PronunciationMap:
        s = settings_module.load()
        path = s.pronunciation_map_path
        mtime = path.stat().st_mtime if path.exists() else 0.0
        if self._pmap is None or mtime != self._pmap_mtime:
            self._pmap = load_pronunciation_map(path)
            self._pmap_mtime = mtime
            if self._pmap.rules:
                logger.info("pronunciation_map loaded: %d rules", len(self._pmap.rules))
        return self._pmap

    @classmethod
    async def get(cls) -> "Engine":
        if cls._instance is None:
            async with cls._init_lock:
                if cls._instance is None:
                    s = settings_module.load()
                    cls._instance = cls(s.onnx_dir, s.voice_styles_dir, s.resolve_use_gpu())
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def _style_for(self, voice_code: str) -> Style:
        code = voice_code.upper()
        if code not in self._style_cache:
            path = voice_preset_path(self._voice_styles_dir, code)
            self._style_cache[code] = load_voice_style([str(path)])
        return self._style_cache[code]

    def _styles_for(self, voice_codes: list[str]) -> Style:
        paths = [str(voice_preset_path(self._voice_styles_dir, c.upper())) for c in voice_codes]
        return load_voice_style(paths)

    def _trim_wav(self, wav: np.ndarray, dur: np.ndarray, idx: int = 0) -> np.ndarray:
        """trailing silence만 잘라낸다 (텍스트 잘림 방지).

        예전엔 duration_predictor가 예측한 dur로 단순 슬라이싱했는데, 그
        값이 실제 발화 길이보다 짧을 때 마지막 단어가 잘려 들어가지 않는
        현상이 있었음. 이제는 신호 진폭으로 trailing silence를 찾아
        그 직후까지만 자른다. 말미에 150ms 여유 버퍼를 둔다.
        """
        full = wav[idx] if wav.ndim == 2 else wav
        if full.size == 0:
            return full

        threshold = 0.01  # |sample| <= 0.01 (-40dB) → silence
        nonzero = np.where(np.abs(full) > threshold)[0]
        if len(nonzero) == 0:
            # 통째로 무음이면 dur로 잘라 padding 제거 (fallback)
            n = int(self.sample_rate * float(dur[idx]))
            return full[: max(0, min(n, full.shape[-1]))]

        tail = int(self.sample_rate * 0.15)
        end = min(int(nonzero[-1]) + tail, full.shape[-1])
        return full[:end]

    def prepare_text(self, text: str) -> str:
        """합성에 실제로 들어가는 문자열을 만든다 (표현 태그는 살려둔 채).

        발음사전은 긴 키 우선 정규식 치환 + 미등록 대문자 철자 읽기를 하므로,
        태그를 날것으로 두면 태그 안쪽 글자를 건드릴 수 있다. 태그를 사용자
        영역 문자로 빼두고 변환한 뒤 되돌린다.
        """
        protected, mapping = tags.protect(text or "")
        converted = self._get_pmap().apply(
            protected, spell_unknown_acronyms=True, convert_years=True
        )
        return tags.restore(converted, mapping)

    async def synth(
        self,
        text: str,
        *,
        voice_code: str,
        lang: str | None = None,
        total_step: int | None = None,
        speed: float | None = None,
    ) -> np.ndarray:
        wav, _ = await self.synth_timed(
            text, voice_code=voice_code, lang=lang, total_step=total_step, speed=speed
        )
        return wav

    async def synth_timed(
        self,
        text: str,
        *,
        voice_code: str,
        lang: str | None = None,
        total_step: int | None = None,
        speed: float | None = None,
    ) -> tuple[np.ndarray, dict]:
        """synth()와 같지만 합성 시간·RTF 메트릭을 함께 돌려준다.

        UI의 "생성 시간 / 오디오 길이 / 실시간 대비" 3종 표시에 쓰인다.
        """
        s = settings_module.load()
        ts = total_step if total_step is not None else s.default_total_step
        sp = speed if speed is not None else s.default_speed
        lg = langs.normalize(lang if lang is not None else s.default_lang)

        # 합성 직전 항상 전체 발음 변환: 발음사전 + 영문 약어 음역 + 연도
        # (1989년→천구백…) + 숫자·단위. 표현 태그는 보호돼 그대로 통과한다.
        # (자막 SRT에는 적용 안 됨 — 원문 유지) 모든 합성 경로가 이걸 거친다.
        text = self.prepare_text(text)
        style = self._style_for(voice_code)

        pieces = _split_for_tts(text)
        if not pieces:
            return np.zeros(0, dtype=np.float32), {
                "synth_seconds": 0.0,
                "duration_seconds": 0.0,
                "rtf": 0.0,
                "pieces": 0,
                "lang": lg,
                "tags": [],
            }

        silence = np.zeros(int(self.sample_rate * _INTER_PIECE_SILENCE_SEC), dtype=np.float32)
        parts: list[np.ndarray] = []
        started = time.perf_counter()
        async with self._infer_lock:
            for i, piece in enumerate(pieces):
                wav, dur = await asyncio.to_thread(self._tts, piece, lg, style, ts, sp)
                parts.append(self._trim_wav(wav, dur, 0))
                if i < len(pieces) - 1:
                    parts.append(silence)
        elapsed = time.perf_counter() - started

        out = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        duration = len(out) / self.sample_rate if self.sample_rate else 0.0
        return out, {
            "synth_seconds": round(elapsed, 3),
            "duration_seconds": round(duration, 3),
            # 실시간 대비 배속. 1보다 크면 재생 시간보다 빨리 만들었다는 뜻.
            "rtf": round(duration / elapsed, 2) if elapsed > 0 else 0.0,
            "pieces": len(pieces),
            "lang": lg,
            "tags": tags.find(text),
        }

    async def synth_batch_same_voice(
        self,
        text_list: list[str],
        *,
        voice_code: str,
        lang: str | None = None,
        total_step: int | None = None,
        speed: float | None = None,
    ) -> list[np.ndarray]:
        # 각 scene을 chunked synth()로 처리해 alignment dropout을 막는다.
        # 벤더 batch ONNX 호출은 텍스트별 alignment 이슈를 그대로 가지고 있어
        # 정확성을 위해 직렬 호출로 전환했다.
        out: list[np.ndarray] = []
        for t in text_list:
            wav = await self.synth(
                t,
                voice_code=voice_code,
                lang=lang,
                total_step=total_step,
                speed=speed,
            )
            out.append(wav)
        return out
