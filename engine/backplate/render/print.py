# -*- coding: utf-8 -*-
"""덱 → 대본 인쇄본. **SME(전문가) 검토용 종이/PDF.**

발표용 덱(render/slides.py)은 한 장씩 넘기는 화면이라 전체를 훑어보며 검토하기
어렵다. 여기는 그 반대 — 장마다 [화면에 뜨는 것 | 읽는 말]을 표 한 줄에 나란히
놓아, 위에서 아래로 쭉 읽으며 검토할 수 있게 만든다. 브라우저 인쇄(Ctrl+P)로
PDF 저장하면 그대로 SME에게 보낼 자료가 된다.

같은 조립 함수(pipeline.s8_assemble.compose)가 낸 덱을 그대로 읽는다 — 화면에서
보는 장 번호·제목과 인쇄본의 장 번호·제목이 갈라지면 검토가 엇갈린다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from render.slides import esc, KIND_LABEL


def _row(s: Dict[str, Any]) -> str:
    no = s.get("no")
    title = esc(s.get("title"))
    kind = str(s.get("kind") or "")
    kind_label = KIND_LABEL.get(kind, "")
    tag = f'<span class="tag">{esc(kind_label)}</span>' if kind_label else ""
    nar = (s.get("narration") or {}).get("text") or (s.get("narration") or {}).get("srt_text") or ""

    if not nar.strip():
        # ★ 읽는 말이 없는 장(표지·구분 등)은 한 줄로 접는다 — 빈 칸을 넓게
        #   비워 두면 종이만 넘어가고 검토자가 볼 것이 없다.
        return (f'<tr class="empty"><td class="c-no">{no}</td>'
                f'<td colspan="2" class="c-empty">{title}{tag}</td></tr>')

    return (
        f'<tr><td class="c-no">{no}</td>'
        f'<td class="c-scr"><b>{title}</b>{tag}</td>'
        f'<td class="c-nar">{esc(nar)}</td></tr>'
    )


def render_print(deck: Dict[str, Any], narration_cfg: Dict[str, Any] | None = None) -> str:
    proj = deck.get("project") or {}
    slides: List[Dict[str, Any]] = deck.get("slides") or []
    narration_cfg = narration_cfg or {}

    n_script = sum(1 for s in slides if (s.get("narration") or {}).get("text")
                   or (s.get("narration") or {}).get("srt_text"))
    meta_bits = [f"{len(slides)}씬"]
    if narration_cfg.get("voice"):
        meta_bits.append(f"목소리 {esc(narration_cfg['voice'])}")
    if narration_cfg.get("speed"):
        meta_bits.append(f"속도 {narration_cfg['speed']}")
    if n_script < len(slides):
        meta_bits.append(f"대본 {n_script}/{len(slides)}장 — 아직 안 채워진 장이 있습니다")

    rows: List[str] = []
    last_section = object()
    for s in slides:
        sec = s.get("section")
        if sec and sec != last_section:
            rows.append(f'<tr class="sec"><td colspan="3">{esc(sec)}</td></tr>')
        last_section = sec
        rows.append(_row(s))

    title = esc(proj.get("title") or deck.get("slug") or "대본 인쇄본")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>{title} — 대본 인쇄본</title>
<style>
@page {{ margin: 14mm 12mm; }}
*,*::before,*::after {{ box-sizing: border-box; }}
body {{
  font-family: "Pretendard","Malgun Gothic","맑은 고딕",system-ui,sans-serif;
  color: #1c2530; font-size: 12px; line-height: 1.6; margin: 0; padding: 18px 22px;
}}
h1 {{ font-size: 17px; margin: 0 0 4px; }}
.meta {{ color: #667; font-size: 11.5px; margin: 0 0 16px; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
thead {{ display: table-header-group; }}
th, td {{ border: 1px solid #cfd8e3; padding: 7px 9px; vertical-align: top; text-align: left; }}
th {{ background: #eef4fb; font-weight: 700; font-size: 11.5px; }}
.c-no {{ width: 34px; text-align: center; font-variant-numeric: tabular-nums; color: #8892a0; }}
.c-scr {{ width: 27%; }}
.c-scr b {{ display: block; color: #1c2530; }}
.c-nar {{ white-space: pre-wrap; }}
.tag {{ display: inline-block; margin-top: 4px; font-size: 10px; font-weight: 600;
  color: #0f766e; background: #e8f4f2; border-radius: 99px; padding: 1px 8px; }}
tr {{ break-inside: avoid; }}
tr.sec td {{ background: #f3ede4; font-weight: 700; color: #6b4a35; }}
tr.empty td {{ color: #98a1ad; font-style: italic; padding: 4px 9px; }}
tr.empty .tag {{ font-style: normal; }}
@media screen {{
  body {{ max-width: 1000px; margin: 24px auto; box-shadow: 0 0 0 1px #dfe3e8; }}
}}
</style></head>
<body>
<h1>{title} — 대본 인쇄본</h1>
<p class="meta">{esc(" · ".join(meta_bits))} · 왼쪽이 화면에 나오는 것, 오른쪽이 읽는 말입니다.
읽는 말이 없는 장은 한 줄로 접었습니다.</p>
<table>
<thead><tr><th class="c-no">#</th><th class="c-scr">화면(슬라이드)</th><th class="c-nar">읽는 말(나레이션)</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body></html>"""
