"""s8 — 교재(종합본) 원고 작성. 이 강의의 교재를 **새로 쓴다**(강의 원고를 옮기는 것이 아니다).

    재료  요약노트(사실) + 강의 원고(manuscripts/, 설명 흐름) + 도식 + 문항(기출 맛보기)
    집필  섹션마다 Claude 1회 → jobs/<잡>/textbook/Lxx/<섹션>.json (해시 캐시, 깃에 올림 — 검수·수정 대상)
    조립  과목마다 HTML 하나 → out/textbook/NN-textbook-<과목>.html
          ★ 요약노트(03/summary_*.html)와 **같은 형식**(그 <style>, h1 과목 · h2 · h3 · div.fig 인라인 SVG)이다.
            요약노트를 HWPX 로 바꾸는 과정에 그대로 넣을 수 있게.
    파생  같은 HTML 에서 <과목>.md + img/*.png(도식 PNG — SVG 를 못 넣는 곳용), book_export.epub=true 면 EPUB

교재의 장(=강) 구성
    h2 제N강 제목 · 학습 목표 · 도입
      h3 섹션(요약노트 번호 그대로)
        h4 소주제 — 본문 문단 · 도식 · 핵심 정리 · 주의
        기출 맛보기(문제·보기·정답·글 해설)
    이 장의 핵심
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from longform.config import REPO, Job
from longform.notes import Note, Section, chars, load_inputs, script_for
from longform.s1_curriculum import load_rounds
from longform.s2_manuscript import call_llm, parse_json, section_prompt_text
from longform.s8_book import CIRCLED, example_box, to_markdown, write_epub, xhtml_doc, xml_frag
from longform.state import State, sha
from longform.util import log, read_json, warn, write_json

PROMPT = REPO / "longform" / "prompts" / "textbook_section.md"

EXTRA_CSS = """
.goals,.points,.wrap{border:1px solid #9DC3E6;background:#F4F8FC;border-radius:8px;padding:10px 16px;margin:12px 0}
.goals b,.points b,.wrap b{color:#1F4E79}
.caution{border-left:4px solid #b45309;background:#fff7ed;padding:6px 12px;margin:10px 0}
.ex{border:1px solid #c9b48a;background:#FBF7EE;border-radius:8px;padding:10px 16px;margin:14px 0}
.ex h4{margin:.2em 0 .4em}.ex .ans{margin-top:.6em;color:#7a4b14}
.lec{page-break-before:always}
h4{margin:1.1em 0 .4em;color:#334155}
"""
BASE_CSS = """
body{font-family:'Pretendard','Noto Sans KR','Malgun Gothic',sans-serif;line-height:1.75;color:#1d2433;max-width:960px;margin:24px auto;padding:0 16px}
h1{font-size:28px}h2{font-size:23px;margin-top:36px;border-bottom:2px solid #1F4E79;padding-bottom:4px}h3{font-size:19px;margin-top:24px;color:#1F4E79}
svg,img{max-height:320px;width:auto;max-width:100%;height:auto;display:block;margin:10px auto}
table{border-collapse:collapse;margin:10px 0}td,th{border:1px solid #b9b0a2;padding:4px 10px}th{background:#eef2f6}
"""


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _lecture_text(man: Optional[Dict[str, Any]]) -> str:
    """강의 원고에서 개념 장의 내레이션만 — 소주제 제목 아래로."""
    if not man:
        return "(강의 원고 없음 — 요약노트만으로 쓴다)"
    out = []
    for g in man.get("groups", []):
        says = [s.get("say", "") for s in g.get("slides", []) if not s.get("kind")]
        if says:
            out.append(f"### [{g.get('sub_id')}] {g.get('title')}\n" + "\n".join(says))
    return "\n\n".join(out)


def _position(i: int, n: int) -> Tuple[str, str]:
    first, last = i == 0, i == n - 1
    rules = []
    if first:
        rules.append("이 절은 장의 **첫 절**이다 — `goals`(학습 목표 3개)와 `intro`(장 도입 문단)를 쓴다.")
    else:
        rules.append("`goals` 와 `intro` 는 빈 값으로 둔다.")
    if last:
        rules.append("이 절은 장의 **마지막 절**이다 — `wrap`(이 장의 핵심 4~6줄)을 쓴다.")
    else:
        rules.append("`wrap` 은 빈 배열로 둔다.")
    pos = "장의 " + ("첫" if first else "") + (" · " if first and last else "") + ("마지막" if last else "") + " 절"
    return (pos if (first or last) else "장의 중간 절"), " ".join(rules)


def _fallback(sec: Section, man: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """book_export.style=lecture — Claude 없이 강의 원고를 그대로 본문으로(무료 미리보기)."""
    by = {g.get("sub_id"): g for g in (man or {}).get("groups", [])}
    subs = []
    for sub in sec.subs:
        g = by.get(sub.id) or {}
        cs = [s for s in g.get("slides", []) if not s.get("kind")]
        subs.append({"sub_id": sub.id, "paragraphs": [s["say"] for s in cs] or [sub.text],
                     "points": [b for s in cs for b in (s.get("bullets") or [])][:5], "caution": "",
                     "fig": next((s.get("fig") for s in cs if s.get("fig")), None)})
    return {"goals": [], "intro": "", "subs": subs, "wrap": []}


def write_section(job: Job, L: Dict[str, Any], i: int, sec: Section, man: Optional[Dict[str, Any]],
                  script, state: State, force: bool) -> Tuple[Dict[str, Any], List[str]]:
    lid = L["id"]
    note_text, figs = section_prompt_text(sec, script)
    if man and man.get("figs"):
        figs = man["figs"]                       # 강의와 같은 도식 번호를 쓴다
    fig_list = "\n".join(f"[FIG {k}] {re.sub(r'<[^>]+>', ' ', f)[:160]}" for k, f in enumerate(figs, 1)) or "(없음)"
    n = len(L["sections"])
    pos, rule = _position(i, n)
    ratio = float(job.get("book_export.expand", 2.0))
    target = max(800, int(sec.n_chars * ratio))
    prompt = PROMPT.read_text(encoding="utf-8").format(
        course=job.get("title"), lecture_label=f"제{L['no']}강 {L['title']}", section_title=sec.title,
        position=pos, position_rule=rule, target_chars=target, section_id=sec.id,
        note_text=note_text, lecture_text=_lecture_text(man), fig_list=fig_list)
    out_f = job.dir / "textbook" / lid / f"{sec.id}.json"
    if job.get("book_export.style", "prose") == "lecture":
        return _fallback(sec, man), figs
    h = sha(prompt, job.get("llm.model"))
    key = f"s8:{sec.id}"
    cached = read_json(out_f, None)
    if cached and not force and (cached.get("_hash") == h or state.done(lid, key, h)):
        return cached, figs
    log(f"{lid} {sec.id} 교재 원고 작성 — 목표 {target}자 · {sec.title}")
    doc = None
    for attempt in range(2):
        try:
            doc = parse_json(call_llm(job, prompt))
            break
        except Exception as e:
            warn(f"{lid} {sec.id} 교재 JSON 실패({e}) — " + ("다시 시도" if attempt == 0 else "강의 원고로 대신"))
    if not doc:
        doc = _fallback(sec, man)
    doc["_hash"] = h
    write_json(out_f, doc)
    state.mark(lid, key, h)
    got = sum(chars(p) for s in doc.get("subs", []) for p in s.get("paragraphs", []))
    log(f"{lid} {sec.id} → 본문 {got}자")
    return doc, figs


def lecture_html(L: Dict[str, Any], parts: List[Tuple[Section, Dict[str, Any], List[str]]], rounds: Dict,
                 book_extra: int = 0, book_used: set | None = None) -> str:
    """강 하나의 교재 HTML. book_extra = 절마다 영상 문항 **밖에** 더 싣는 문항 수(책은 영상보다 문제가 많다)."""
    b = [f'<h2 class="lec">제{L["no"]}강 {esc(L["title"])}</h2>']
    first = parts[0][1] if parts else {}
    if first.get("goals"):
        b.append('<div class="goals"><b>학습 목표</b><ul>' + "".join(f"<li>{esc(g)}</li>" for g in first["goals"]) + "</ul></div>")
    if first.get("intro"):
        b.append(f"<p>{esc(first['intro'])}</p>")
    for sec, doc, figs in parts:
        b.append(f"<h3>{esc(sec.title)}</h3>")
        by = {s.get("sub_id"): s for s in doc.get("subs", [])}
        used = set()
        for sub in sec.subs:
            s = by.get(sub.id) or {}
            b.append(f"<h4>{esc(sub.title)}</h4>")
            b += [f"<p>{esc(p)}</p>" for p in s.get("paragraphs", []) if p.strip()]
            try:
                fi = int(s.get("fig") or 0)
            except (TypeError, ValueError):
                fi = 0
            if 1 <= fi <= len(figs) and fi not in used:
                frag = xml_frag(figs[fi - 1])
                if frag:
                    b.append(f'<div class="fig">{frag}</div>')
                    used.add(fi)
            if s.get("points"):
                b.append('<div class="points"><b>핵심 정리</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in s["points"]) + "</ul></div>")
            if (s.get("caution") or "").strip():
                b.append(f'<p class="caution"><b>주의</b> {esc(s["caution"])}</p>')
        k = 0
        for e in L.get("examples") or []:
            if not e["anchor"].startswith(sec.id):
                continue
            q = rounds.get((e["round"], e["no"]))
            if q:
                k += 1
                b.append(example_box(q, f"기출 맛보기 {k}"))
        # ★ 책에는 문제를 더 싣는다(사용자 지시 2026-10-09) — 이 절의 요약노트 배지가 가리키는 문항 중
        #   영상에 안 나온 것, 책 전체에서 아직 안 쓴 것. 영상 문항과 같은 번호 줄로 이어 센다.
        if book_extra and rounds:
            from longform.s1_curriculum import _pick_examples
            used = set(book_used if book_used is not None else set())
            used |= {(e["round"], e["no"]) for e in L.get("examples") or []}
            for e in _pick_examples([sec], rounds, used, book_extra):
                q = rounds.get((e["round"], e["no"]))
                if q:
                    k += 1
                    b.append(example_box(q, f"기출 맛보기 {k}"))
                    if book_used is not None:
                        book_used.add((e["round"], e["no"]))
    last = parts[-1][1] if parts else {}
    if last.get("wrap"):
        b.append('<div class="wrap"><b>이 장의 핵심</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in last["wrap"]) + "</ul></div>")
    return "\n".join(b)


def run(job: Job, only: Optional[List[str]] = None, force: bool = False) -> Optional[Path]:
    cur = read_json(job.dir / "curriculum.json")
    if not cur:
        raise SystemExit("[error] curriculum.json 이 없습니다 — 먼저 plan")
    notes, scripts = load_inputs(job)
    by_sub = {n.subject_no: n for n in notes}
    rd = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rd) if rd and rd.exists() else {}
    state = State(job)
    odir = job.out_dir / "textbook"
    odir.mkdir(parents=True, exist_ok=True)
    title = job.get("book_export.title") or f"{job.get('title')} 교재"

    files: List[Path] = []
    chapters: List[Dict[str, str]] = []
    # 책에만 더 싣는 문항 — 절마다 N개(영상 문항 밖), 책 전체에서 한 번씩만
    book_extra = int(job.get("book_export.examples_per_section", 10))
    book_used: set = set()
    for sno in sorted({L["subject_no"] for L in cur["lectures"]}):
        note: Optional[Note] = by_sub.get(int(sno))
        if not note:
            continue
        secs = {s.id: s for s in note.sections}
        sc = scripts.get(int(sno))
        body: List[str] = []
        for L in [L for L in cur["lectures"] if L["subject_no"] == sno]:
            if only and L["id"] not in only:
                continue
            parts = []
            for i, sm in enumerate(L["sections"]):
                sec = secs.get(sm["id"])
                if not sec:
                    continue
                man = read_json(job.manuscripts_dir / L["id"] / f"{sec.id}.json", None)
                doc, figs = write_section(job, L, i, sec, man, script_for(note, sc, sec), state, force)
                parts.append((sec, doc, figs))
            if parts:
                lh = lecture_html(L, parts, rounds, book_extra, book_used)
                body.append(lh)
                chapters.append({"file": f"{L['id'].lower()}.xhtml", "title": f"제{L['no']}강 {L['title']}",
                                 "xhtml": xhtml_doc(L["title"], lh)})
        if not body:
            continue
        m = re.search(r"summary[_-]?(.+)$", note.file.stem)
        key = (m.group(1) if m else note.file.stem).strip("_-") or f"part{sno}"
        f = odir / f"{int(sno):02d}-textbook-{key}.html"
        css = (note.style or BASE_CSS) + EXTRA_CSS
        f.write_text(f"<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>{esc(note.subject)} — 교재</title>"
                     f"<style>{css}</style></head><body>\n<h1>{esc(note.subject)}</h1>\n" + "\n".join(body) + "\n</body></html>",
                     encoding="utf-8")
        md, figs = to_markdown(note.subject, "\n".join(body))
        from longform.raster import svgs_to_png
        img = odir / f"{f.stem}_img"
        svgs_to_png([(svg, img / name) for name, svg in figs])
        f.with_suffix(".md").write_text(md.replace("](img/", f"]({img.name}/"), encoding="utf-8")
        files.append(f)
        log(f"{note.subject} 교재 → {f.name} (+ {f.with_suffix('.md').name}, 도식 PNG {len(figs)}장)")
    if not files:
        log("교재로 묶을 강이 없습니다")
        return None
    if job.get("book_export.epub", False):
        ep = odir / f"{job.name}-textbook.epub"
        write_epub(ep, title, job.get("author", "") or job.get("book", ""), chapters)
        log(f"EPUB → {ep.name}")
    log(f"교재 {len(files)}개 과목 → {odir}  (요약노트와 같은 HTML 형식 — HWPX 변환에 그대로 넣으면 됩니다)")
    return odir
