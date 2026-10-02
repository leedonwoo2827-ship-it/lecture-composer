# -*- coding: utf-8 -*-
"""배경판(11판) 눈으로 보기 — 배경 PNG + 웹 텍스트를 한 장으로 띄운다.

    python tools/plate_demo.py <배경.png> <원장.json> <data_id> [출력.html]

★ 왜 필요한가. 11판의 주장은 "글자가 그림이 아니라 진짜 텍스트다" 하나다.
  그건 **브라우저에서 드래그로 긁어 봐야** 확인된다. 그래서 파일 한 장으로
  띄워 두고, 그 위에서 글자를 선택해 볼 수 있게 한다.
★ 자리(--lx/--ly)는 지시문이 이미지 모델에게 "여기를 비워라" 라고 말한 좌표와
  같은 표에서 나온다(pipeline/s3a_imgprompt.py 의 PLACE_XY).
"""
from __future__ import annotations

import base64
import io
import json
import sys
from html import escape as esc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.s3a_imgprompt import labels_of  # noqa: E402

CSS = """
*{box-sizing:border-box} body{margin:0;background:#20242b;color:#d8dee9;
  font-family:Pretendard,"Malgun Gothic",system-ui,sans-serif}
h1{font-size:15px;font-weight:600;margin:0;padding:14px 18px;color:#9aa4b2}
.wrap{padding:0 18px 28px}
.stage{position:relative;width:100%;aspect-ratio:16/9;background:#F6F1E8;
  container-type:size;box-shadow:0 8px 40px #0008;border-radius:4px;overflow:hidden}
.stage>img{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;display:block}
.lbls{position:absolute;inset:0}
.lbl{position:absolute;left:var(--lx);top:var(--ly);width:var(--lw);
  word-break:keep-all;text-wrap:pretty}
.lbl b{display:block;font-weight:700;font-size:4cqh;line-height:1.25;
  letter-spacing:-.02em;color:#1F4E79}
.lbl span{display:block;margin-top:.35em;font-weight:500;font-size:2.6cqh;
  line-height:1.42;letter-spacing:-.01em;color:#334155}
.lbl b,.lbl span{text-shadow:0 0 6px #F6F1E8,0 0 12px #F6F1E8}
.note{max-width:1100px;margin:16px auto 0;font-size:13px;line-height:1.7;color:#9aa4b2}
.note b{color:#e5e9f0}
.on .lbls{outline:1px dashed #ff6b6b55}
.on .lbl{outline:1px dashed #ff6b6b}
button{font:inherit;padding:7px 13px;margin:12px 0 0;border-radius:5px;
  border:1px solid #3b4252;background:#2e3440;color:#d8dee9;cursor:pointer}
"""


def build(bg: Path, labels: list, title: str) -> str:
    b64 = base64.b64encode(bg.read_bytes()).decode()
    mime = "image/png" if bg.suffix.lower() == ".png" else "image/jpeg"
    lbl_html = "".join(
        f'<div class="lbl" style="--lx:{l["x"]}%;--ly:{l["y"]}%;--lw:{l["w"]}%">'
        f'<b>{esc(l["head"])}</b>'
        + (f'<span>{esc(l["sub"])}</span>' if l.get("sub") else "")
        + "</div>" for l in labels)
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>배경판 시험 — {esc(title)}</title><style>{CSS}</style></head><body>
<h1>11판 배경판 — 그림은 배경만, 글자는 화면이 얹는다</h1>
<div class="wrap">
  <div class="stage" id="st"><img src="data:{mime};base64,{b64}" alt="">
    <div class="lbls">{lbl_html}</div></div>
  <button onclick="st.classList.toggle('on')">글자 상자 테두리 보기</button>
  <p class="note"><b>확인하는 법.</b> 위 글자를 <b>마우스로 드래그해 긁어 보세요.</b>
  선택이 되면 그림이 아니라 진짜 텍스트입니다 — 그러므로 한글이 깨질 수가 없습니다.
  브라우저를 좌우로 줄였다 늘렸다 해 보세요. 글자 크기가 그림에 비례해 따라옵니다
  (cqh 기준). 라벨 {len(labels)}개.</p>
</div></body></html>"""


def main() -> None:
    bg, led_p, did = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    out = Path(sys.argv[4]) if len(sys.argv) > 4 else bg.with_name("배경판시험.html")
    entry = json.load(io.open(led_p, encoding="utf-8"))["by_id"][did]
    labels = labels_of(entry)
    if not labels:
        # 10판 원장이면 자리가 없다 — 지시문에서 자리를 되읽어 세워 준다
        from pipeline.s3a_imgprompt import _PLACE, PLACE_XY, LABEL_W
        import re
        places = re.findall(r"라벨 \d+ \(([^)]+)\):", entry.get("prompt") or "")
        subs = re.findall(r'그 아래 작게 "([^"]*)"', entry.get("prompt") or "")
        heads = entry.get("label_heads") or []
        labels = []
        for i, h in enumerate(heads):
            pl = places[i] if i < len(places) else "왼쪽 위"
            x, y = PLACE_XY.get(pl, (4.0, 13.9))
            labels.append({"head": h, "sub": subs[i] if i < len(subs) else "",
                           "x": x, "y": y, "w": LABEL_W, "place": pl})
    out.write_text(build(bg, labels, entry.get("title") or did), encoding="utf-8")
    print(f"{out}  (라벨 {len(labels)}개)")


if __name__ == "__main__":
    main()
