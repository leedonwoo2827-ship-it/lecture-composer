"""요약노트 HTML(exambook-forge summary-note 형식) 파서.

형식(문항 앱 책 폴더의 03/summary_*.html):
    <h1>2과목 · 데이터분석 기획</h1>
    <h2>1. 분석 기획의 방향성 <label class="q">…<span class="qn">모의 1회 11번 · 3회 11번</span></label></h2>
    <h3>1.1. … <label class="q">…</label></h3>
    <p>…</p><ul>…</ul><div class="fig"><svg>…</svg></div>

★ 본문은 h2/h3 의 **형제 요소**로 이어진다(중첩 section 없음). 그래서 h2/h3 태그
  위치로 잘라도 안전하다.
★ `<span class="qn">` 의 「모의 N회 M번」이 그 항목을 근거로 출제된 자사 문항이다.
  태그 매칭보다 정확하므로 이것으로 예시 문항을 고른다.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

# ★ 닫는 태그는 **아무 h 레벨이나** 받는다 — 실측: 어떤 과정 노트에 `<h2>…</h3>` 오타가 있어
#   \1 로 짝을 맞추면 제목이 다음 h3 본문까지 삼켰다(2026-10-01).
H_RE = re.compile(r"<(h[123])\b([^>]*)>(.*?)</h[1-6]\s*>", re.S | re.I)
ATTR_RE = re.compile(r'data-(say|read|id)\s*=\s*"([^"]*)"', re.S)
TABLE_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
# 문항 근거 배지 — 두 형식이 섞여 있다
#   <label class="q"><input…><b>12</b><span class="qn">모의 1회 7번 · 2회 6번</span></label>
#   <span class="q">모의 1회 42·43·44번 · 2회 45·46번</span>          (label 없이, 번호 여럿)
LABEL_RE = re.compile(r"<label\b[^>]*class=\"q\"[^>]*>.*?</label>|<span\b[^>]*class=\"q\"[^>]*>.*?</span>",
                      re.S | re.I)
QN_RE = re.compile(r"<span class=\"qn\">(.*?)</span>|<span\b[^>]*class=\"q\"[^>]*>(.*?)</span>", re.S | re.I)
TOK_RE = re.compile(r"(\d+)\s*회|(\d+)")
SVG_RE = re.compile(r"<svg\b.*?</svg>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
SUBJ_RE = re.compile(r"(\d)\s*과목")


def strip_tags(s: str) -> str:
    s = SVG_RE.sub(" ", s)
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = TAG_RE.sub(" ", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def chars(s: str) -> int:
    """공백 제외 글자 수 — backplate 의 말 속도(5.5자/초) 측정 기준과 같다."""
    return len(re.sub(r"\s", "", s))


def _refs(heading_html: str) -> List[Tuple[int, int]]:
    """「모의 1회 22번 · 38번 · 2회 21번」「1회 42·43·44번」 → [(1,22),(1,38),(2,21)…].

    회차는 다음 「N회」가 나올 때까지 이어진다(번호만 있는 조각은 앞 회차의 문항이다).
    """
    m = QN_RE.search(heading_html)
    if not m:
        return []
    text = strip_tags(m.group(1) or m.group(2) or "")
    out: List[Tuple[int, int]] = []
    rnd = None
    for t in TOK_RE.finditer(text):
        if t.group(1):
            rnd = int(t.group(1))
        elif rnd is not None:
            out.append((rnd, int(t.group(2))))
    return out


def _title(heading_html: str) -> str:
    return strip_tags(LABEL_RE.sub("", heading_html))


@dataclass
class Sub:
    id: str
    title: str
    html: str
    refs: List[Tuple[int, int]] = field(default_factory=list)
    say: str = ""       # 영상 원고(summaryhtml2videoscripthtml 산출물)의 h3 data-say — 검수된 내레이션
    read: str = ""      # data-read — 소리 나는 대로 적은 TTS 입력
    src_id: str = ""    # data-id (q1-01-03)

    @property
    def text(self) -> str:
        return strip_tags(self.html)

    @property
    def svgs(self) -> List[str]:
        return SVG_RE.findall(self.html)


@dataclass
class Section:
    id: str
    title: str
    lead_html: str               # h2 바로 아래, 첫 h3 전까지
    refs: List[Tuple[int, int]] = field(default_factory=list)
    subs: List[Sub] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join([strip_tags(self.lead_html)] + [s.title + " " + s.text for s in self.subs])

    @property
    def n_chars(self) -> int:
        return chars(self.text)

    @property
    def svgs(self) -> List[str]:
        return SVG_RE.findall(self.lead_html) + [g for s in self.subs for g in s.svgs]

    def all_refs(self) -> List[Tuple[int, int]]:
        out = list(self.refs)
        for s in self.subs:
            out += s.refs
        return out


@dataclass
class Note:
    subject_no: int
    subject: str
    file: Path
    style: str
    sections: List[Section]


def load_set(paths: List[Path]) -> List[Note]:
    """노트 여러 개. 「N과목」이 없는 원고(일반 도서 등)는 **파일 순서대로 1·2·3…** 을 매긴다.

    ★ 섹션 id(s{번호}-NN)가 이 번호에서 나오므로, 같은 순서로 넘기면 노트와 영상 원고가 짝지어진다.
    """
    out: List[Note] = []
    for i, p in enumerate(paths, 1):
        n = parse_note(p)
        if not n.subject_no:
            n.subject_no = i
            for s in n.sections:
                old = s.id
                s.id = f"s{i}" + old[old.index("-"):]
                for sub in s.subs:
                    sub.id = s.id + sub.id[len(old):]
        out.append(n)
    return out


def load_inputs(job) -> Tuple[List[Note], Dict[int, Note]]:
    """잡의 원천 — (요약노트들, {부 번호: 영상 원고}). 둘 다 load_set 규칙으로 번호를 매긴다."""
    paths = []
    for p in job.get("inputs.notes") or []:
        f = job.path(p)
        if not f or not f.exists():
            raise SystemExit(f"[error] 요약노트가 없습니다: {f} (원천 탭에서 넣으십시오)")
        paths.append(f)
    sp = [job.path(p) for p in job.get("inputs.scripts") or []]
    sp = [f for f in sp if f and f.exists()]
    scripts = {s.subject_no: s for s in load_set(sp)}
    # ★ 요약노트 없이 영상 원고만 있어도 된다 — 영상 원고에도 h2·h3 구조와 「모의 N회 M번」 배지가 있다
    notes = sorted(load_set(paths), key=lambda n: n.subject_no) if paths else \
        sorted(load_set(sp), key=lambda n: n.subject_no)
    return notes, scripts


def norm_title(t: str) -> str:
    return re.sub(r"\s", "", t)


def script_for(note: Note, script: "Note | None", sec: Section) -> Dict[str, List[Sub]]:
    """노트 소주제 id → 같은 제목의 영상 원고 h3 들(긴 항목은 2장으로 나뉘어 있다)."""
    out: Dict[str, List[Sub]] = {}
    if not script:
        return out
    ss = next((s for s in script.sections if norm_title(s.title) == norm_title(sec.title)), None)
    if not ss:
        return out
    for sub in sec.subs:
        out[sub.id] = [x for x in ss.subs if norm_title(x.title) == norm_title(sub.title)]
    return out


def parse_note(path: Path) -> Note:
    raw = path.read_text(encoding="utf-8")
    style = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", raw, re.S | re.I))
    # ★ style 주석 안에 `<body>` `<h3>` 같은 글자가 있다 — 먼저 걷어내야 오인하지 않는다
    clean = re.sub(r"<(style|script)\b.*?</\1>", "", raw, flags=re.S | re.I)
    clean = re.sub(r"<!--.*?-->", "", clean, flags=re.S)
    m_body = re.search(r"<body\b[^>]*>", clean, re.I)
    body = clean[m_body.end():] if m_body else clean
    body = body.rsplit("</body>", 1)[0]

    heads = list(H_RE.finditer(body))
    h1 = next((m for m in heads if m.group(1).lower() == "h1"), None)
    subject = _title(h1.group(3)) if h1 else path.stem
    sm = SUBJ_RE.search(subject)
    subject_no = int(sm.group(1)) if sm else 0

    sections: List[Section] = []
    cur: Section | None = None
    for i, m in enumerate(heads):
        tag = m.group(1).lower()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        content = body[m.end():end]
        if tag == "h2":
            cur = Section(id=f"s{subject_no}-{len(sections) + 1:02d}", title=_title(m.group(3)),
                          lead_html=content, refs=_refs(m.group(3)))
            sections.append(cur)
        elif tag == "h3" and cur is not None:
            at = {k: _html.unescape(v) for k, v in ATTR_RE.findall(m.group(2))}
            cur.subs.append(Sub(id=f"{cur.id}-{len(cur.subs) + 1:02d}", title=_title(m.group(3)),
                                html=content, refs=_refs(m.group(3)),
                                say=at.get("say", ""), read=at.get("read", ""), src_id=at.get("id", "")))
    return Note(subject_no=subject_no, subject=subject, file=path, style=style, sections=sections)
