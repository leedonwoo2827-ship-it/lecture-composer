# -*- coding: utf-8 -*-
"""말하는 순간에 맞춰 화면 요소를 띄운다 — **STT 단어 시각**(있으면) 또는 **글자 비례**(없으면).

예전 길(`render/slides.stamp_label_times`)은 라벨을 "몇 번째 문장" 의 시작에 띄운다. 문장 시각도
실측이 아니라 글자 수로 나눈 어림(`auto_time_cues`)이다. 그래서 40초짜리 문장 안의 라벨은 길게는
수십 초 일찍 뜬다. 여기서는 **라벨 글자가 대본의 어디에서 나오는가**를 찾고, 그 글자 자리를
**실제 음성 시각**으로 바꾼다.

    1) 대본(srt_text) → 음절 열(공백·문장부호 제거, 원래 자리 기억)
    2) 음성 → 단어 시각  : faster-whisper(word_timestamps). 결과는 wav 옆 `*.words.json` 에 캐시
       없으면           : 음절 자리 / 전체 × 음성 길이(글자 비례)
    3) STT 음절 열과 대본 음절 열을 맞대어(difflib) 대본 음절마다 시각을 얻는다 — 발음이 다른 자리
       (KDD→케이디디)는 맞는 이웃 사이에서 보간한다
    4) 라벨 머리글을 대본에서 찾는다(앞 라벨 뒤에서부터, 완전 일치 → 가장 긴 공통 조각)
       → `at` = 그 자리 시각 − 리드, `say_end` = 그 조각을 다 말한 시각(타이핑 속도에 쓴다)

★ 찾지 못한 라벨은 원래 `at` 을 그대로 둔다 — 잃는 것보다 어림이 낫다.
★ 끄기: 환경변수 `BP_SYNC=off`. STT 만 끄기: `BP_SYNC=text`. 모델: `BP_SYNC_MODEL`(기본 small).
"""
from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LEAD = 0.25          # 말하기 조금 전에 뜬다 — 귀보다 눈이 먼저여야 "말과 같이" 로 느낀다
MIN_MATCH = 2        # 공통 조각 최소 음절 수

_SKIP = re.compile(r"[\s\.,!?·…\-—–:;\"'“”‘’()\[\]{}<>「」『』〈〉《》/\\|~`]+")
_model = None


def _syllables(text: str) -> Tuple[str, List[int]]:
    """공백·부호를 지운 글자 열과, 각 글자의 원문 자리."""
    out, pos = [], []
    for i, ch in enumerate(text or ""):
        if _SKIP.fullmatch(ch):
            continue
        out.append(ch.lower())
        pos.append(i)
    return "".join(out), pos


def mode() -> str:
    return (os.environ.get("BP_SYNC") or "auto").lower()


def stt_words(wav: Path) -> Optional[List[List[Any]]]:
    """[[start, end, word], …] — 캐시가 있으면 그것. faster-whisper 가 없으면 None."""
    if mode() in ("off", "text") or not wav or not wav.is_file():
        return None
    cache = wav.with_suffix(".words.json")
    if cache.is_file() and cache.stat().st_mtime >= wav.stat().st_mtime:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            pass
    try:
        from faster_whisper import WhisperModel           # 선택 설치(requirements-sync.txt)
    except ImportError:
        return None
    global _model
    try:
        if _model is None:
            _model = WhisperModel(os.environ.get("BP_SYNC_MODEL", "small"), device="cpu", compute_type="int8")
        # ★ wav 는 우리가 읽어 16kHz float 로 넘긴다 — faster-whisper 의 PyAV 디코더는 판이 어긋나면
        #   open() 인자에서 죽는다(2026-10-09 실측). TTS 산출물은 늘 PCM wav 라 이쪽이 단단하다.
        segs, _ = _model.transcribe(_pcm16k(wav), language="ko", word_timestamps=True, vad_filter=False,
                                    beam_size=1, condition_on_previous_text=False)
        words = [[round(w.start, 3), round(w.end, 3), w.word] for s in segs for w in (s.words or [])]
    except Exception as e:                                 # noqa: BLE001 — STT 가 죽어도 렌더는 간다(글자 비례)
        print(f"[warn] STT 실패 — 글자 비례로 맞춥니다: {e}")
        return None
    try:
        cache.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return words


def _pcm16k(wav: Path):
    """PCM wav → 16kHz mono float32(numpy). 선형 보간 리샘플 — 단어 시각에는 충분하다."""
    import wave

    import numpy as np
    with wave.open(str(wav)) as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    dt = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    x = np.frombuffer(raw, dtype=dt).astype(np.float32)
    if sw == 1:
        x = (x - 128.0) / 128.0
    else:
        x /= float(2 ** (8 * sw - 1))
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        m = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, m), np.arange(len(x)), x).astype(np.float32)
    return x


def char_clock(ref: str, dur: float, words: Optional[List[List[Any]]]) -> List[float]:
    """대본 음절마다 시각(초). words 가 없으면 글자 비례."""
    n = len(ref)
    if n == 0:
        return []
    if not words:
        # 앞 0.15초는 숨, 끝 0.2초는 꼬리 — TTS 의 앞뒤 무음 어림
        a, b = 0.15, max(0.3, dur - 0.2)
        return [a + (b - a) * i / n for i in range(n)]
    hyp, ht = [], []
    for s, e, w in words:
        syl, _ = _syllables(str(w))
        k = len(syl)
        for j, ch in enumerate(syl):
            hyp.append(ch)
            ht.append(float(s) + (float(e) - float(s)) * (j / max(1, k)))
    times: List[Optional[float]] = [None] * n
    sm = difflib.SequenceMatcher(None, ref, "".join(hyp), autojunk=False)
    for blk in sm.get_matching_blocks():
        for j in range(blk.size):
            times[blk.a + j] = ht[blk.b + j]
    # 비는 자리 — 맞은 이웃 사이 보간, 양끝은 글자 비례로 늘린다
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        return char_clock(ref, dur, None)
    first, last = known[0], known[-1]
    for i in range(first):
        times[i] = times[first] * i / max(1, first)
    for i in range(last + 1, n):
        times[i] = times[last] + (dur - times[last]) * (i - last) / max(1, n - last)
    for a, b in zip(known, known[1:]):
        for i in range(a + 1, b):
            times[i] = times[a] + (times[b] - times[a]) * (i - a) / (b - a)
    # 단조 증가로 누른다(STT 가 가끔 되감는다)
    out, m = [], 0.0
    for t in times:
        m = max(m, float(t))
        out.append(m)
    return out


def _find(ref: str, needle: str, start: int) -> Optional[Tuple[int, int]]:
    """needle 을 ref[start:] 에서 찾는다 → (시작, 끝). 완전 일치가 없으면 가장 긴 공통 조각."""
    if not needle:
        return None
    k = ref.find(needle, start)
    if k < 0 and start:
        k = ref.find(needle)            # 앞 라벨보다 먼저 말하는 경우도 있다
    if k >= 0:
        return k, k + len(needle)
    sm = difflib.SequenceMatcher(None, ref, needle, autojunk=False)
    m = sm.find_longest_match(start, len(ref), 0, len(needle))
    if m.size < max(MIN_MATCH, int(len(needle) * .4)):
        m = sm.find_longest_match(0, len(ref), 0, len(needle))
    if m.size >= max(MIN_MATCH, int(len(needle) * .4)):
        return m.a, m.a + m.size
    return None


def stamp(slides: List[Dict[str, Any]], proj_dir: Optional[Path]) -> Dict[str, int]:
    """덱 장들의 라벨 `at`·`until`·`say_end` 를 말소리에 맞춰 고친다. 돌려주는 값은 통계."""
    st = {"stt": 0, "text": 0, "hit": 0, "miss": 0}
    if mode() == "off":
        return st
    for s in slides:
        lbs = [l for l in (s.get("labels") or []) if (l.get("head") or "").strip()]
        if not lbs:
            continue
        say = (s.get("narration") or {}).get("srt_text") or ""
        dur = float((s.get("audio") or {}).get("sec") or 0)
        if not say or dur <= 0:
            continue
        wav = (proj_dir / s["audio"]["file"]) if proj_dir and (s.get("audio") or {}).get("file") else None
        words = stt_words(wav) if wav else None
        st["stt" if words else "text"] += 1
        ref, _ = _syllables(say)
        clock = char_clock(ref, dur, words)
        cur = 0
        for l in lbs:
            needle, _ = _syllables(l["head"])
            hit = _find(ref, needle, cur)
            if not hit:
                st["miss"] += 1
                continue
            a, b = hit
            l["at"] = max(0.0, clock[a] - LEAD)
            l["say_end"] = clock[min(b, len(clock)) - 1]
            cur = b
            st["hit"] += 1
        order = sorted(lbs, key=lambda x: float(x.get("at") or 0))
        for x, y in zip(order, order[1:]):
            x["until"] = y["at"]
        if order:
            order[-1]["until"] = dur
    return st
