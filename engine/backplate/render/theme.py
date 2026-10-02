# -*- coding: utf-8 -*-
"""테마 — themeSpec(enum·hex) → CSS 변수. 그리고 브랜드 램프 파생.

두 가지 일을 한다.

1. **브랜드 램프 파생** (`derive_ramp`)
   퍼스널 컬러 hex 하나를 주면 8단 램프를 만든다. 손으로 고르면 반드시 틀리는
   것이 대비비다. IDA 의 램프는 500 에서 갈린다 — ≥500 은 작은 글씨로 읽히고
   ≤400 은 채움 전용이다. 그 사다리를 **숫자로 재현한다**:

       sky-400      2.98   채움 전용 (텍스트 금지)
       sky-500      4.90   라인 아이콘 · 링크 · 포커스 링
       brand        5.55   액션 채움 · 활성
       brand-hover  8.18   눌림 · 앵커

   색조(H)와 채도(S)를 고정하고 명도(L)만 이분탐색해서 목표 대비비를 맞춘다.

2. **themeSpec 검증·수리** (`normalize_theme`)
   Claude 는 마크업이 아니라 **선택지**만 낸다 — enum·hex·작은 정수뿐.
   스펙 밖 값이 와도 거부하지 않고 **수리**한다. 미지 enum은 기본값으로, 잘못된
   hex 는 seed 팔레트로, 대비 미달은 스냅. 무엇을 고쳤는지 warnings 에 남긴다.
   그래야 `"variant":"cinematic"` 같은 환각이 페이지를 깨지 않는다.
"""
from __future__ import annotations

import colorsys
import re
from typing import Any, Dict, List, Tuple

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# 흰 배경 기준 목표 대비비 — IDA 램프에서 측정한 값
TARGETS: Dict[str, float] = {
    "sky-400": 2.98,
    "sky-500": 4.90,
    "brand": 5.55,
    "brand-hover": 8.18,
}
# 틴트 3종은 대비 목표가 없다. 흰색과 섞는 비율로만 만든다.
TINTS: Dict[str, float] = {
    "sky-wash": 0.965,     # 아이콘박스 그라데이션 시작 · 호버 배경
    "brand-wash": 0.915,   # 활성 nav 배경 · 뱃지
    "brand-soft": 0.630,   # 아바타 후광 · ::selection
}


# ── 색 유틸 ────────────────────────────────────────────────────────────────
def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b)))
    )


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg: str, bg: str = "#ffffff") -> float:
    """WCAG 대비비. 1.0 ~ 21.0"""
    a, b = luminance(hex_to_rgb(fg)), luminance(hex_to_rgb(bg))
    lo, hi = min(a, b), max(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _hsl(hex_: str) -> Tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in hex_to_rgb(hex_))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _from_hsl(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex(r * 255, g * 255, b * 255)


def _mix_white(hex_: str, amount: float) -> str:
    """amount=1.0 이면 흰색, 0.0 이면 원색."""
    r, g, b = hex_to_rgb(hex_)
    return rgb_to_hex(
        r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount
    )


def at_contrast(seed: str, target: float, *, bg: str = "#ffffff") -> str:
    """seed 의 색조·채도를 지키면서 목표 대비비에 맞는 명도를 이분탐색으로 찾는다.

    ★ 방향이 배경에 따라 뒤집힌다. 흰 배경에서는 명도가 오를수록 대비가 **낮아지고**,
      어두운 배경에서는 **높아진다.** 한쪽만 가정하면 다크 테마에서 조용히 틀린 색이
      나온다(탐색이 엉뚱한 끝으로 수렴한다). 그래서 배경 밝기로 방향을 먼저 정한다.
    """
    h, s, _ = _hsl(seed)
    dark_bg = luminance(hex_to_rgb(bg)) < 0.18
    lo, hi = 0.0, 1.0
    best, best_err = seed, 1e9
    for _ in range(48):
        mid = (lo + hi) / 2
        cand = _from_hsl(h, s, mid)
        c = contrast(cand, bg)
        err = abs(c - target)
        if err < best_err:
            best, best_err = cand, err
        # 어두운 배경: 대비가 목표보다 크면 더 어둡게(명도 ↓) 가야 한다
        too_high = c > target
        if too_high != dark_bg:
            lo = mid
        else:
            hi = mid
    return best


def _mix_bg(hex_: str, bg: str, amount: float) -> str:
    """배경 쪽으로 섞는다. 라이트면 흰색, 다크면 어두운 바탕으로 수렴한다."""
    r, g, b = hex_to_rgb(hex_)
    br, bg_, bb = hex_to_rgb(bg)
    return rgb_to_hex(r + (br - r) * amount, g + (bg_ - g) * amount, b + (bb - b) * amount)


def derive_ramp(seed: str, *, bg: str = "#ffffff", desat: float = 1.0) -> Dict[str, str]:
    """퍼스널 컬러 hex 하나 → 8단 브랜드 램프.

    `seed` 는 어느 단이어도 된다. 색조만 가져가고 명도는 다시 계산한다.
    `desat` < 1.0 이면 채도를 눌러 **K 가 섞인** 가라앉은 톤이 된다
    (인쇄로 치면 먹을 더 넣는 것). 다크 UI 에서 순색은 형광펜처럼 튄다.
    """
    if not HEX_RE.match(seed or ""):
        seed = "#8e2a3e"
    if desat != 1.0:
        h, s, l = _hsl(seed)
        seed = _from_hsl(h, max(0.0, min(1.0, s * desat)), l)

    ramp = {name: at_contrast(seed, t, bg=bg) for name, t in TARGETS.items()}
    base = ramp["brand"]
    for name, amt in TINTS.items():
        ramp[name] = _mix_bg(base, bg, amt)
    # 웹↔산출물 공유 앵커. 브랜드보다 더 가라앉은 색.
    h, s, _ = _hsl(base)
    anchor_l = 0.82 if luminance(hex_to_rgb(bg)) < 0.18 else 0.20
    ramp["brand-deep"] = _from_hsl(h, max(0.18, s * 0.55), anchor_l)
    return ramp


def ramp_report(ramp: Dict[str, str]) -> List[str]:
    """대비 사다리가 실제로 맞았는지 확인용."""
    order = ["sky-wash", "brand-wash", "brand-soft", "sky-400",
             "sky-500", "brand", "brand-hover", "brand-deep"]
    out = []
    for k in order:
        v = ramp.get(k, "")
        c = contrast(v) if v else 0
        tgt = TARGETS.get(k)
        mark = "" if tgt is None else f"  목표 {tgt:.2f}"
        out.append(f"  --{k:<12} {v}   대비 {c:5.2f}{mark}")
    return out


# ── themeSpec 검증·수리 ────────────────────────────────────────────────────
ENUMS: Dict[str, Tuple[Tuple[str, ...], str]] = {
    "variant":          (("slides", "phases", "gallery", "dossier"), "slides"),
    "density":          (("airy", "compact"), "airy"),
    "accent_treatment": (("underline", "left-rule", "chip", "dot"), "left-rule"),
    "hero_style":       (("poster", "gradient", "frame-collage"), "poster"),
    "frame_strip":      (("strip", "grid", "stacked"), "strip"),
}
TYPO_SCALE = (("compact", "default", "editorial"), "default")
SECTIONS = ("hero", "summary", "phases", "decisions", "stack", "footer")
PALETTE_KEYS = ("bg", "surface", "ink", "ink_muted", "accent", "accent_alt", "ok", "border")

# 텍스트로 쓰이는 색은 배경 대비 4.5:1 을 넘어야 한다.
TEXT_ON_BG = {"ink": 7.0, "ink_muted": 4.5, "accent": 4.5}


def default_palette(seed_hex: str) -> Dict[str, str]:
    r = derive_ramp(seed_hex)
    return {
        "bg": "#f6f4f2",
        "surface": "#ffffff",
        "ink": "#14161a",
        "ink_muted": "#5b626d",
        "accent": r["brand"],
        "accent_alt": r["brand-hover"],
        "ok": "#0e7355",
        "border": "rgb(26 34 48 / .10)",
    }


def normalize_theme(spec: Any, *, seed_hex: str = "#8e2a3e") -> Dict[str, Any]:
    """Claude 가 낸 themeSpec 을 **거부하지 않고 수리**한다."""
    warn: List[str] = []
    spec = spec if isinstance(spec, dict) else {}
    if not isinstance(spec, dict):
        warn.append("themeSpec 이 객체가 아님 → 기본값")

    out: Dict[str, Any] = {}

    for key, (allowed, dflt) in ENUMS.items():
        v = spec.get(key)
        if v in allowed:
            out[key] = v
        else:
            out[key] = dflt
            if v is not None:
                warn.append(f"{key}={v!r} 은 미지 값 → {dflt!r}")

    typo = spec.get("typography") if isinstance(spec.get("typography"), dict) else {}
    scale = typo.get("scale")
    if scale not in TYPO_SCALE[0]:
        if scale is not None:
            warn.append(f"typography.scale={scale!r} 미지 → {TYPO_SCALE[1]!r}")
        scale = TYPO_SCALE[1]
    weight = typo.get("display_weight")
    if not isinstance(weight, int) or weight not in (400, 500, 600, 700, 800):
        if weight is not None:
            warn.append(f"display_weight={weight!r} 미지 → 600")
        weight = 600
    out["typography"] = {"scale": scale, "display_weight": weight}

    radius = spec.get("radius")
    if radius not in (0, 2, 4, 6, 10, 14):
        if radius is not None:
            warn.append(f"radius={radius!r} 미지 → 10")
        radius = 10
    out["radius"] = radius

    # 팔레트 — hex 가 아니면 seed 파생값으로 스냅
    base = default_palette(seed_hex)
    pal_in = spec.get("palette") if isinstance(spec.get("palette"), dict) else {}
    pal: Dict[str, str] = {}
    for k in PALETTE_KEYS:
        v = pal_in.get(k)
        if isinstance(v, str) and (HEX_RE.match(v) or v.startswith("rgb")):
            pal[k] = v
        else:
            pal[k] = base[k]
            if v is not None:
                warn.append(f"palette.{k}={v!r} 은 hex 가 아님 → {base[k]}")

    # 대비 수리 — 텍스트로 쓰이는 색이 배경에서 안 읽히면 스냅
    bg = pal["bg"] if HEX_RE.match(pal["bg"]) else "#ffffff"
    for k, need in TEXT_ON_BG.items():
        if not HEX_RE.match(pal[k]):
            continue
        c = contrast(pal[k], bg)
        if c < need:
            pal[k] = base[k]
            warn.append(f"palette.{k} 대비 {c:.2f} < {need} → {base[k]} 로 스냅")
    out["palette"] = pal

    # section_order — 중복 제거 후, 빠진 것은 정규 순서로 뒤에 붙인다
    raw = spec.get("section_order")
    order: List[str] = []
    if isinstance(raw, list):
        for s in raw:
            if s in SECTIONS and s not in order:
                order.append(s)
        dropped = [s for s in raw if s not in SECTIONS]
        if dropped:
            warn.append(f"section_order 미지 항목 제거: {dropped}")
    missing = [s for s in SECTIONS if s not in order]
    if missing and raw is not None:
        warn.append(f"section_order 누락 보충: {missing}")
    out["section_order"] = order + missing

    out["locked"] = bool(spec.get("locked"))
    out["source"] = spec.get("source") if spec.get("source") in ("claude", "manual", "fallback") else "claude"
    out["warnings"] = warn
    return out


def to_css_vars(theme: Dict[str, Any], *, seed_hex: str = "#8e2a3e") -> str:
    """검증된 theme → `:root{...}` 블록. **문자열을 그대로 흘려보내지 않는다.**"""
    ramp = derive_ramp(seed_hex)
    pal = theme["palette"]
    scale = {"compact": 0.94, "default": 1.0, "editorial": 1.12}[theme["typography"]["scale"]]
    lines = [
        f"--bg:{pal['bg']}", f"--surface:{pal['surface']}",
        f"--ink:{pal['ink']}", f"--ink-muted:{pal['ink_muted']}",
        f"--accent:{pal['accent']}", f"--accent-alt:{pal['accent_alt']}",
        f"--ok:{pal['ok']}", f"--border:{pal['border']}",
        f"--brand-deep:{ramp['brand-deep']}",
        f"--radius:{int(theme['radius'])}px",
        f"--scale:{scale}",
        f"--display-weight:{int(theme['typography']['display_weight'])}",
    ]
    return ":root{" + ";".join(lines) + "}"


if __name__ == "__main__":  # 파생 결과 눈으로 확인
    import sys

    seed = sys.argv[1] if len(sys.argv) > 1 else "#8e2a3e"
    r = derive_ramp(seed)
    print(f"seed {seed}  →  브랜드 램프")
    print("\n".join(ramp_report(r)))
