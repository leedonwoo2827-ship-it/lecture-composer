# -*- coding: utf-8 -*-
"""분할된 참고 원고(`*2.html`)를 읽는 **유일한 자리.**

`tools/split_sections.mjs` 가 낸 파일 하나 안에 세 가지가 같이 들어 있다.

    <style id="src-css">   원본 문서의 스타일 (전부 `.doc` 밑으로 가둬 둔 것)
    <section class="hs" data-no="N">…<figure class="m-html"><div class="doc">…
    <script type="application/json" id="manifest">   장·줄 목록

부속 파일로 흩지 않고 한 파일에 넣은 이유는 **사람이 여는 것과 기계가 읽는 것이
같아야 하기 때문**이다. 사람이 그 파일을 열어 확인한 그 화면이, 그대로 발표에
들어간다. 대신 그 대가로 "파일에서 조각을 오려 오는 일" 이 생기는데, 그것을 여기
한 곳에 모은다 — 여러 곳에서 각자 오려 내면 규칙이 갈라진다.

★ 오려 내는 규칙은 **생성기와 짝**이다(`tools/split_sections.mjs` 의 파일 조립
  부분). 한쪽을 고치면 다른 쪽도 고쳐야 한다. 그래서 두 파일 모두에 서로를
  가리키는 주석을 남겨 둔다.

★ 읽은 것은 파일이 바뀌기 전까지 들고 있는다. `/preview` 한 번에 장 수만큼
  `_media()` 가 불리는데(90장이면 90번), 그때마다 190KB 를 다시 읽고 파싱하면
  미리보기가 눈에 띄게 느려진다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# 생성기가 박아 둔 표식들 — 이 문자열이 곧 두 파일 사이의 약속이다.
_SEC_OPEN = '<section class="hs" data-no="'
_SEC_ANY = '<section class="hs"'
_DOC_OPEN = '<div class="doc">'
_DOC_CLOSE = "</div></figure>"
_MANIFEST = re.compile(
    r'<script type="application/json" id="manifest">(.*?)</script>', re.S)
_STYLE = re.compile(r'<style id="src-css">(.*?)</style>', re.S)

# {경로: (mtime, 본문)} — 파일이 바뀌면 저절로 다시 읽는다
_cache: Dict[str, Any] = {}

# ── 그림 줄 ────────────────────────────────────────────────────────────
# 글자 수로 시간을 재면 안 되는 줄들. `markBlocks()` 가 붙이는 태그 이름이다.
FIG_TAGS = frozenset(("svg", "figure", "img", "picture"))
# 그림 한 장을 보는 데 걸리는 시간. `showcase.config.json` 의 `capture.fig_sec`
# 으로 덮을 수 있다 — 원고를 보고 사람이 조정할 값이라서다.
FIG_SEC = 3.0


def _text(path: Path) -> str:
    key = str(path)
    try:
        mt = path.stat().st_mtime
    except OSError:
        _cache.pop(key, None)
        return ""
    hit = _cache.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    raw = path.read_text(encoding="utf-8")
    _cache[key] = (mt, raw)
    return raw


def manifest(path: Path) -> Dict[str, Any]:
    """장·줄 목록. 없으면 빈 dict — 이 파일이 분할본이 아니라는 뜻이다."""
    m = _MANIFEST.search(_text(path))
    if not m:
        return {}
    # 생성기가 `<` 를 `<` 로 이스케이프해 두었다(본문에 `</script>` 가 섞여도
    # 태그가 일찍 닫히지 않게). JSON 파서가 그 이스케이프를 알아서 되돌린다.
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def style(path: Path) -> str:
    """원본 문서 스타일. **문서당 한 번만** 페이지에 넣는다 — 장마다 넣으면
    4KB 짜리가 장 수만큼 복사된다(90장이면 360KB)."""
    m = _STYLE.search(_text(path))
    return m.group(1).strip() if m else ""


def section(path: Path, no: int) -> str:
    """`data-no=no` 장의 몸통(`.doc` 안쪽)만 오려 온다.

    `<section>` 은 서로 겹치지 않는 형제라(생성기가 그렇게만 낸다) 다음
    `<section class="hs"` 전까지가 그 장이다. 그 안에서 `.doc` 의 안쪽을 꺼낸다 —
    닫는 표식이 `</div></figure>` 라 본문에 `<div>` 가 들어 있어도 안 헷갈린다.

    표지·마무리 장에는 `.doc` 이 없다 — 빈 문자열이 정상이다.
    """
    raw = _text(path)
    if not raw:
        return ""
    head = f'{_SEC_OPEN}{int(no)}"'
    i = raw.find(head)
    if i < 0:
        return ""
    j = raw.find(_SEC_ANY, i + len(head))
    chunk = raw[i:j] if j >= 0 else raw[i:]
    a = chunk.find(_DOC_OPEN)
    if a < 0:
        return ""
    b = chunk.rfind(_DOC_CLOSE)
    if b < 0 or b <= a:
        return ""
    return chunk[a + len(_DOC_OPEN):b]


def block_ats(slide: Dict[str, Any]) -> List[float]:
    """이 장의 줄들이 **몇 초에** 뜨는가. 손편집 → 자동 배분 순으로 이긴다.

    ★ 이 함수가 유일한 출처다. 수정 화면이 보여 주는 시각과 발표에서 실제로 뜨는
      시각이 갈리면 사람이 맞출 수가 없다 — 화면에서 9초로 고쳤는데 발표에서는
      다른 때 뜨면, 무엇을 믿어야 할지 알 수 없다.

    `html_at` 은 **번호를 키로 하는 dict** 다(배열이 아니다). 오버라이드 병합이
    dict 는 깊게 합치고 배열은 통째로 갈아치우기 때문에, 배열이면 한 줄만 고쳐도
    나머지 전부를 같이 보내야 한다 — 그 사이에 장이 바뀌면 남의 값을 덮어쓴다.
    """
    base = [float(x) for x in (slide.get("html_at_default") or [])]
    over = slide.get("html_at") or {}
    if not isinstance(over, dict):
        return base
    out: List[float] = []
    for k, v in enumerate(base):
        hand = over.get(str(k))
        out.append(v if hand is None else float(hand))
    return out


def _fig_sec() -> float:
    """설정의 `capture.fig_sec`. 설정을 못 읽어도 이 모듈은 계속 돌아야 한다 —
    여기는 원고를 읽는 자리고, 설정은 있으면 좋은 것이다."""
    try:
        from core import config
        return float((config.load().get("capture") or {}).get("fig_sec") or FIG_SEC)
    except Exception:                                   # noqa: BLE001
        return FIG_SEC


def _is_fig(tags: Optional[List[str]], i: int) -> bool:
    """이 줄이 그림인가. `tags` 를 안 주면 늘 False — 옛 프로젝트가 그대로 돈다."""
    if not tags or i >= len(tags):
        return False
    return str(tags[i]).lower() in FIG_TAGS


def auto_ats(chars: List[int], dur: float, *, cps: float = 5.7,
             min_step: float = 0.8, tags: Optional[List[str]] = None,
             fig_sec: float = FIG_SEC) -> List[float]:
    """줄 길이에 비례해 등장 시각을 나눈다. **그림 줄만 빼고.**

    `dur` 이 있으면(음성이 붙었거나 대본 길이를 알면) 그 안에 다 들어가게 맞추고,
    없으면 초당 글자 수로 어림한다. 어느 쪽이든 **줄 사이 최소 간격**은 지킨다 —
    짧은 줄 세 개가 같은 초에 우르르 뜨면 순서대로 나오는 의미가 없다.

    ★ **그림 줄은 글자 수로 재지 않는다.** 그림은 읽는 게 아니라 보는 것이라
      글자 수와 보는 시간이 아무 상관이 없다. 그런데 `<svg>` 의 `textContent` 는
      라벨을 다 세므로, 책 원고에서는 그림 한 줄이 **글줄보다 글자가 많다**
      (2026-08-14 실측: 그림 중앙값 81~93자 · 글줄 34자). 비례로 나누면 그림
      하나가 그 장 시간의 **40%**(최대 58%)를 가져가고 글줄이 쪼그라든다.
      바닥값만 올려서는 안 고쳐진다 — 이미 바닥보다 한참 위이기 때문이다.
      그래서 그림 몫을 **먼저 떼어 두고**, 남은 시간만 글줄끼리 나눈다.

    ★ 짝이 있다 — `tools/split_sections.mjs` 의 등장 시각 배분. 한쪽을 고치면
      다른 쪽도 고쳐야 한다. 원고를 브라우저로 열어 본 리듬과 발표에서 뜨는
      리듬이 달라지면, 사람이 눈으로 확인한 것이 확인이 아니게 된다.
    """
    n = len(chars)
    if n == 0:
        return []
    fig = [_is_fig(tags, i) for i in range(n)]
    span = [fig_sec if fig[i] else max(min_step, c / max(cps, 0.1))
            for i, c in enumerate(chars)]

    if dur and dur > 0:
        # 그림은 고정으로 빼 두고 **글줄만** 남은 시간에 맞춘다. 그림까지 같이
        # 줄이면 「그림에 3초」가 장마다 다른 값이 되어 못박은 뜻이 없어진다.
        budget = dur * 0.88          # 마지막 줄이 끝나기 전에 뜨도록 살짝 당긴다
        fixed = sum(span[i] for i in range(n) if fig[i])
        flow = sum(span[i] for i in range(n) if not fig[i])
        # 그림만으로 예산을 다 먹는 장(그림 한 줄뿐인 장)에는 억지로 자리를
        # 만들지 않는다 — 아래 바닥값이 받아 준다.
        left = max(0.0, budget - fixed)
        if flow > 0 and left > 0:
            k = left / flow
            span = [span[i] if fig[i] else span[i] * k for i in range(n)]

    out, t = [], 0.0
    for i, x in enumerate(span):
        out.append(round(t, 1))
        t += max(fig_sec if fig[i] else min_step, x)
    return out


def resolve(s: Dict[str, Any]) -> None:
    """장 하나의 등장 시각을 확정해 `html_times` 에 넣는다. **제자리에서 고친다.**

    조립(s8)과 콘솔 API(`/api/projects/{pid}/deck`)가 **같이 부른다.** 두 곳이 각자
    계산하면 수정 화면에 적힌 시각과 발표에서 실제로 뜨는 시각이 갈린다 — 화면에서
    9초로 고쳤는데 발표에서 다른 때 뜨면 무엇을 믿어야 할지 알 수 없다.

    ★ **손편집이 들어온 뒤에** 부를 것. `html_at`(사람이 고친 값)이 오버라이드로
      들어오므로, 병합 전에 부르면 그 값이 반영되지 않는다.
    """
    if s.get("media_kind") != "html":
        return
    chars = [int(x) for x in (s.get("html_chars") or [])]
    dur = (float((s.get("audio") or {}).get("sec") or 0)
           or float((s.get("narration") or {}).get("est_sec") or 0))
    # ★ 자동 배분을 여기서 다시 계산한다. 원고를 나눌 때 잡은 값은 글자 수로만
    #   어림한 것이고, 그 뒤에 대본·음성이 붙으면 그 장이 실제로 몇 초인지 알게
    #   된다. 알고도 옛 어림값을 쓰면 음성은 40초인데 줄은 20초에 다 떠 버리고
    #   남은 20초를 빈 화면으로 보낸다.
    if dur > 0 and chars:
        s["html_at_default"] = auto_ats(chars, dur, tags=s.get("html_tags"),
                                        fig_sec=_fig_sec())
    s["html_times"] = block_ats(s)


def find_doc(root: Path, rel: Optional[str]) -> Optional[Path]:
    """프로젝트 안 상대 경로 → 실제 파일. 없으면 None(빈 장으로 렌더된다)."""
    if not rel:
        return None
    p = root / rel
    return p if p.is_file() else None
