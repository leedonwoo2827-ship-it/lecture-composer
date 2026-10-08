"""영상 테마 — 정의는 렌더 엔진 한 곳(`engine/backplate/render/video_theme.py`)에만 둔다.

longform 은 그 파일을 경로로 읽어 같은 값을 쓴다(도식·문제 카드 PNG, 썸네일, 오브젝트 프롬프트).
목표서 `backplate.theme` — 비우거나 "ivory" 면 지금까지의 룩, "danjeong" 이면 단정 스케치북.
"""
from __future__ import annotations

import base64
import importlib.util
from functools import lru_cache
from typing import Any, Dict, Optional

from longform.config import REPO, Job

_VT = REPO / "engine" / "backplate" / "render" / "video_theme.py"


@lru_cache(maxsize=1)
def _mod():
    spec = importlib.util.spec_from_file_location("lc_video_theme", _VT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)  # type: ignore[union-attr]
    return m


def name_of(job: Job) -> str:
    return str(job.get("backplate.theme") or "ivory")


def get(job_or_name: Any) -> Optional[Dict[str, Any]]:
    """테마 사전 — ivory 면 None(원래 코드 길)."""
    name = name_of(job_or_name) if isinstance(job_or_name, Job) else job_or_name
    return _mod().get(name)


def base_for(th: Dict[str, Any], chunk: int) -> Dict[str, str]:
    return _mod().base_for(th, chunk)


@lru_cache(maxsize=4)
def font_css(name: str) -> str:
    """raster(Playwright set_content)용 @font-face — 파일 URL 은 about:blank 에서 막힐 수 있어 data URI 로 싣는다."""
    th = get(name)
    if not th:
        return ""
    d = _mod().FONT_DIR / th["font_dir"]
    out = []
    for w, f in th["faces"].items():
        if w not in (500, 700, 800, 900):        # PNG 에 쓰는 굵기만(페이지마다 싣는 크기를 줄인다)
            continue
        p = d / f
        if p.is_file():
            b64 = base64.b64encode(p.read_bytes()).decode()
            out.append(f'@font-face{{font-family:"{th["font"]}";src:url(data:font/woff2;base64,{b64}) '
                       f'format("woff2");font-weight:{w}}}')
    return "".join(out)
