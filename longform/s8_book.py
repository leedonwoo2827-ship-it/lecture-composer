"""s8 — 강의 원고 → **책 원고(EPUB3)** 역변환. 부가 산출물.

    manuscripts/Lxx/<섹션>.json  ──(문체 변환: 강의체 → 서술체, Claude, 캐시)──▶  <섹션>.book.json
                                 ──(조립: 부=과목, 장=강, 절=섹션, 항=소주제)──▶  out/book/<제목>.epub (+ .html 미리보기)

책의 한 절(섹션) 구성
    본문      : 내레이션(say)을 문어체(~다) 문단으로 — 사실·순서는 그대로, 말버릇·인사·"다음 장에서" 제거
    도식      : 원고의 FIG(SVG·표)를 그 자리에 그대로(EPUB3 는 인라인 SVG 를 지원한다)
    핵심 정리 : 소주제마다 판서(bullets)를 상자로
    기출 맛보기: 문제·보기 → 정답·해설(말 대본이 아니라 글 해설 explanation)

`book_export.style`
    prose    (기본) Claude 로 문어체 변환 — 섹션당 1회 호출, 해시 캐시
    lecture  변환 없이 내레이션을 그대로 문단으로(무료, 강의록 느낌)
"""
from __future__ import annotations

import html
import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.s1_curriculum import load_rounds
from longform.s2_manuscript import call_llm, parse_json
from longform.state import State, sha
from longform.util import log, read_json, warn, write_json

CIRCLED = "①②③④⑤"

PROSE_PROMPT = """당신은 자격증 수험서 편집자입니다. 아래는 강의 영상의 내레이션(구어체)입니다.
이것을 **수험서 본문(문어체, ~다/~한다)**으로 옮기십시오.

규칙
1. 사실·용어·설명 순서는 그대로. 새 사실을 더하지 않는다. 빼는 것은 말버릇뿐이다.
2. 인사, "자,", "여러분", "다음 장에서 보겠습니다", "앞에서 보았듯이" 같은 강의 진행 말은 지운다.
3. 같은 말의 반복(강의에서 강조하려고 되풀이한 것)은 한 번으로 줄인다.
4. 소주제(group)마다 문단 1~4개. 문단은 3~6문장.
5. 출력은 JSON 하나만: {{"groups": [{{"sub_id": "…", "paragraphs": ["…", "…"]}}]}}

[내레이션]
{body}
"""

CSS = """
body{font-family:serif;line-height:1.75;margin:0 4%}
h1{font-size:1.6em;margin:1.2em 0 .6em}h2{font-size:1.3em;margin:1.4em 0 .5em;border-bottom:1px solid #ccc}
h3{font-size:1.1em;margin:1.2em 0 .4em;color:#1F4E79}
p{text-indent:1em;margin:.4em 0}
.fig{text-align:center;margin:1em 0}.fig svg{max-width:100%;height:auto}
table{border-collapse:collapse;margin:1em auto}td,th{border:1px solid #999;padding:.3em .6em}
.box{border:1px solid #9DC3E6;background:#F4F8FC;padding:.6em 1em;margin:1em 0}
.box h4{margin:.2em 0 .4em;color:#1F4E79}
.ex{border:1px solid #c9b48a;background:#FBF7EE;padding:.6em 1em;margin:1em 0}
.ex .ans{margin-top:.6em;color:#7a4b14}
.part{page-break-before:always;text-align:center;margin-top:30%}
"""


# ── XHTML 안전 ────────────────────────────────────────────────────────────
def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def xml_frag(frag: str) -> str:
    """도식(SVG·표)을 XHTML 에 넣을 수 있게. XML 로 안 읽히면 빈 문자열."""
    s = (frag or "").strip()
    s = re.sub(r"<br\s*>", "<br/>", s, flags=re.I)
    s = re.sub(r"&nbsp;", "&#160;", s)
    if s.startswith("<svg") and "xmlns=" not in s[:200]:
        s = s.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    try:
        ET.fromstring(s)
    except ET.ParseError:
        return ""
    return s


# ── 문체 변환 ─────────────────────────────────────────────────────────────
def prose_for(job: Job, man: Dict[str, Any], cache: Path, state: State, force: bool) -> Dict[str, List[str]]:
    concept = [g for g in man["groups"] if g.get("sub_id") not in ("intro",)]
    body_parts = []
    for g in concept:
        says = [s["say"] for s in g["slides"] if not s.get("kind")]
        if says:
            body_parts.append(f"### [{g.get('sub_id')}] {g['title']}\n" + "\n".join(says))
    body = "\n\n".join(body_parts)
    if job.get("book_export.style", "prose") == "lecture" or not body:
        return {g.get("sub_id"): [s["say"] for s in g["slides"] if not s.get("kind")] for g in concept}
    h = sha(body, PROSE_PROMPT, job.get("llm.model"))
    key = f"s8:{man['section']}"
    old = read_json(cache, None)
    if old and not force and state.done(man["lecture"], key, h):
        return old
    log(f"{man['lecture']} {man['section']} 책 문체로 변환")
    try:
        doc = parse_json(call_llm(job, PROSE_PROMPT.format(body=body)))
        out = {g["sub_id"]: [p for p in g.get("paragraphs", []) if p.strip()] for g in doc.get("groups", [])}
    except Exception as e:
        warn(f"{man['section']} 문체 변환 실패({e}) — 내레이션 그대로 씁니다")
        out = {g.get("sub_id"): [s["say"] for s in g["slides"] if not s.get("kind")] for g in concept}
    write_json(cache, out)
    state.mark(man["lecture"], key, h)
    return out


# ── 장(강) XHTML ──────────────────────────────────────────────────────────
def example_box(q: Dict[str, Any], title: str) -> str:
    ch = q.get("choices") or []
    ans = int(q.get("answer_index", 0))
    out = [f'<div class="ex"><h4>{esc(title)}</h4><p>{esc(q.get("question", ""))}</p>']
    if q.get("passage"):
        txt = re.sub(r"<[^>]+>", " ", q["passage"])
        out.append("".join(f"<p>{esc(ln.strip())}</p>" for ln in txt.split("\n") if ln.strip()))
    out.append("<ol>" + "".join(f"<li>{esc(c)}</li>" for c in ch) + "</ol>")
    lab = CIRCLED[ans] if ans < 5 else str(ans + 1)
    expl = "".join(f"<p>{esc(p)}</p>" for p in (q.get("explanation") or "").split("\n") if p.strip())
    out.append(f'<div class="ans"><b>정답 {lab}</b>{expl}</div></div>')
    return "".join(out)


def chapter_xhtml(job: Job, L: Dict[str, Any], mans: List[Dict[str, Any]], proses: List[Dict[str, List[str]]],
                  rounds: Dict) -> str:
    b = [f"<h1>제{L['no']}강 {esc(L['title'])}</h1>"]
    for man, prose in zip(mans, proses):
        b.append(f"<h2>{esc(man['title'])}</h2>")
        figs = man.get("figs") or []
        used: set = set()
        for g in man["groups"]:
            if g.get("sub_id") == "intro":
                continue
            concept = [s for s in g["slides"] if not s.get("kind")]
            exs = [s for s in g["slides"] if s.get("kind") == "example-q"]
            if g.get("sub_id") == "wrap":
                b.append('<div class="box"><h4>이 강의 핵심</h4><ul>'
                         + "".join(f"<li>{esc(x)}</li>" for s in concept for x in s.get("bullets") or [])
                         + "</ul></div>")
                continue
            b.append(f"<h3>{esc(g['title'])}</h3>")
            for p in prose.get(g.get("sub_id"), []):
                b.append(f"<p>{esc(p)}</p>")
            for s in concept:
                fi = s.get("fig")
                if fi and fi not in used and 1 <= int(fi) <= len(figs):
                    frag = xml_frag(figs[int(fi) - 1])
                    if frag:
                        b.append(f'<div class="fig">{frag}</div>')
                        used.add(fi)
            pts = [x for s in concept for x in (s.get("bullets") or []) if x]
            if pts:
                b.append('<div class="box"><h4>핵심 정리</h4><ul>' + "".join(f"<li>{esc(x)}</li>" for x in pts[:6])
                         + "</ul></div>")
            for s in exs:
                m = re.search(r"모의 (\d+)회 (\d+)번", s["title"])
                q = rounds.get((int(m.group(1)), int(m.group(2)))) if m else None
                if q:
                    b.append(example_box(q, f"기출 맛보기 — {s['title'].split('·', 1)[-1].strip()}"))
    return "\n".join(b)


def xhtml_doc(title: str, body: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko" xml:lang="ko">'
            f'<head><meta charset="utf-8"/><title>{esc(title)}</title>'
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
            f"<body>{body}</body></html>")


# ── EPUB 조립 ─────────────────────────────────────────────────────────────
def write_epub(path: Path, title: str, author: str, chapters: List[Dict[str, str]]) -> None:
    uid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, title)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    nav = ("<nav epub:type=\"toc\" id=\"toc\"><h1>차례</h1><ol>"
           + "".join(f'<li><a href="{c["file"]}">{esc(c["title"])}</a></li>' for c in chapters) + "</ol></nav>")
    manifest = "".join(f'<item id="c{i}" href="{c["file"]}" media-type="application/xhtml+xml"'
                       f'{" properties=\"svg\"" if "<svg" in c["xhtml"] else ""}/>'
                       for i, c in enumerate(chapters))
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="ko">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="uid">{uid}</dc:identifier><dc:title>{esc(title)}</dc:title>'
           f'<dc:creator>{esc(author)}</dc:creator><dc:language>ko</dc:language>'
           '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
           '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="css" href="style.css" media-type="text/css"/>' + manifest + '</manifest>'
           f'<spine><itemref idref="nav"/>{spine}</spine></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>', compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", xhtml_doc("차례", nav), compress_type=zipfile.ZIP_DEFLATED)
        for c in chapters:
            z.writestr(f"OEBPS/{c['file']}", c["xhtml"], compress_type=zipfile.ZIP_DEFLATED)


def run(job: Job, only: Optional[List[str]] = None, force: bool = False) -> Optional[Path]:
    cur = read_json(job.dir / "curriculum.json")
    if not cur:
        raise SystemExit("[error] curriculum.json 이 없습니다 — 먼저 s1")
    rounds_dir = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rounds_dir) if rounds_dir and rounds_dir.exists() else {}
    state = State(job)
    title = job.get("book_export.title") or f"{job.get('title')} — 강의로 읽는 {job.get('book', '')}".strip()
    chapters: List[Dict[str, str]] = []
    preview: List[str] = []
    last_sub = None
    for L in cur["lectures"]:
        if only and L["id"] not in only:
            continue
        d = job.manuscripts_dir / L["id"]
        mans = [read_json(d / f"{s['id']}.json") for s in L["sections"]]
        if not all(mans):
            warn(f"{L['id']} 원고가 다 있지 않아 책에서 뺍니다 — s2 먼저")
            continue
        proses = [prose_for(job, m, d / f"{m['section']}.book.json", state, force) for m in mans]
        if L["subject_no"] != last_sub:
            part = f'<div class="part"><h1>{esc(L["subject"])}</h1></div>'
            chapters.append({"file": f"part{L['subject_no']}.xhtml", "title": L["subject"],
                             "xhtml": xhtml_doc(L["subject"], part)})
            preview.append(part)
            last_sub = L["subject_no"]
        body = chapter_xhtml(job, L, mans, proses, rounds)
        chapters.append({"file": f"{L['id'].lower()}.xhtml", "title": f"제{L['no']}강 {L['title']}",
                         "xhtml": xhtml_doc(L["title"], body)})
        preview.append(body)
    if not [c for c in chapters if not c["file"].startswith("part")]:
        log("책으로 묶을 강이 없습니다")
        return None
    # ★ 원본은 HTML 하나(도식 SVG 까지 한 파일). EPUB·HWPX 는 여기서 뽑는다.
    #   HWPX 는 SVG 를 못 넣으므로 도식을 PNG 로 바꾼 Markdown 묶음(<잡>.md + img/)을 따로 낸다.
    bdir = job.out_dir / "book"
    bdir.mkdir(parents=True, exist_ok=True)
    html_out = bdir / f"{job.name}.html"
    html_out.write_text(
        f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><h1>{esc(title)}</h1>{''.join(preview)}</body></html>", encoding="utf-8")
    md_out = bdir / f"{job.name}.md"
    md, figs = to_markdown(title, "".join(preview))
    from longform.raster import svgs_to_png
    svgs_to_png([(svg, bdir / "img" / name) for name, svg in figs])
    md_out.write_text(md, encoding="utf-8")
    n = len([c for c in chapters if not c["file"].startswith("part")])
    made = [html_out.name, f"{md_out.name} + img/ {len(figs)}장"]
    if job.get("book_export.epub", False):
        ep = bdir / f"{job.name}.epub"
        write_epub(ep, title, job.get("author", "") or job.get("book", ""), chapters)
        made.append(ep.name)
    log(f"책 원고 {n}강 → {bdir} : " + " · ".join(made))
    return html_out


# ── HTML → Markdown(HWPX 변환용) ───────────────────────────────────────────
def _txt(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def to_markdown(title: str, body: str) -> tuple:
    """우리가 만든 책 HTML(형식이 정해져 있다) → Markdown. 도식은 img/figNNN.png 로 뺀다."""
    figs: List[tuple] = []

    def fig(m: re.Match) -> str:
        name = f"fig{len(figs) + 1:03d}.png"
        figs.append((name, m.group(1)))
        return f"\n\n![그림 {len(figs)}](img/{name})\n\n"

    def table(m: re.Match) -> str:
        rows = re.findall(r"<tr>(.*?)</tr>", m.group(0), re.S)
        cells = [[_txt(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)] for r in rows]
        if not cells:
            return ""
        w = max(len(r) for r in cells)
        cells = [r + [""] * (w - len(r)) for r in cells]
        out = ["| " + " | ".join(cells[0]) + " |", "|" + "---|" * w]
        out += ["| " + " | ".join(r) + " |" for r in cells[1:]]
        return "\n\n" + "\n".join(out) + "\n\n"

    def box(m: re.Match) -> str:
        inner = m.group(2)
        head = re.search(r"<h4>(.*?)</h4>", inner, re.S)
        lines = [f"**{_txt(head.group(1))}**"] if head else []
        inner = re.sub(r"<h4>.*?</h4>", "", inner, flags=re.S)
        # 보기(ol)는 ①②③④ — 정답 번호와 맞춰 볼 수 있게
        inner = re.sub(r"<ol>(.*?)</ol>", lambda o: "".join(
            f"<p>{CIRCLED[i] if i < 5 else i + 1} {_txt(t)}</p>"
            for i, t in enumerate(re.findall(r"<li>(.*?)</li>", o.group(1), re.S))), inner, flags=re.S)
        for kind, t in re.findall(r"<(li|p|b)[^>]*>(.*?)</\1>", inner, re.S):
            t = _txt(t)
            if t:
                lines.append(("- " if kind == "li" else "") + t)
        return "\n\n" + "\n".join("> " + l for l in lines) + "\n\n"

    s = re.sub(r'<div class="fig">(<svg.*?</svg>)</div>', fig, body, flags=re.S)
    s = re.sub(r"<table>.*?</table>", table, s, flags=re.S)
    s = re.sub(r'<div class="(box|ex)">(.*?)</div>\s*(?=<h[1-4]|<div class="(?:box|ex|part|fig)"|$)', box, s, flags=re.S)
    s = re.sub(r'<div class="part"><h1>(.*?)</h1></div>', lambda m: f"\n\n# {_txt(m.group(1))}\n\n", s, flags=re.S)
    for lv in (1, 2, 3, 4):
        s = re.sub(rf"<h{lv}>(.*?)</h{lv}>", lambda m, lv=lv: f"\n\n{'#' * (lv + 1)} {_txt(m.group(1))}\n\n", s, flags=re.S)
    s = re.sub(r"<li>(.*?)</li>", lambda m: f"\n- {_txt(m.group(1))}", s, flags=re.S)
    s = re.sub(r"<p>(.*?)</p>", lambda m: f"\n\n{_txt(m.group(1))}\n\n", s, flags=re.S)
    s = re.sub(r"</?(ul|ol|div)[^>]*>", "\n", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return f"# {title}\n\n{s}\n", figs
