"""s2 — 강의 원고. 섹션(h2) 하나 = backplate 프로젝트 하나 = 원고 HTML 하나.

    manuscripts/L03/s2-05.json   Claude 가 쓴 판서·내레이션(+ 예시 문항 슬라이드)
    manuscripts/L03/s2-05.html   backplate 입력 원고 (h1 강 제목 / p 책 / h2 소주제 / h3 슬라이드)

★ backplate 원고 규칙(tools/split_sections.mjs): h2 = 묶음, h3 = 슬라이드 한 장,
  h3 의 `data-say` = 내레이션, `data-id` = 이미지 원장 키. 본문은 h3 의 형제 요소이고
  렌더 높이 약 600px 에서 잘린다 → 판서는 2~4줄로 짧게.
★ 기출 맛보기 슬라이드는 **LLM 없이** 문항 데이터로 만든다(문제·보기·explanation_speech).
"""
from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from longform.config import REPO, Job
from longform.notes import (SVG_RE, TABLE_RE, Note, Section, Sub, chars, load_inputs,
                            script_for, strip_tags)
from longform.s1_curriculum import load_rounds
from longform.state import State, sha
from longform.util import log, read_json, run as run_cmd, warn, write_json

PROMPT = REPO / "longform" / "prompts" / "lecture_section.md"
def course(job: Job) -> Dict[str, str]:
    """과정 이름들 — 목표서 course 칸. 없으면 title/book 에서."""
    c = job.get("course", {}) or {}
    title = job.get("title") or job.name
    book = job.get("book") or title
    short = c.get("short") or book
    return {"role": c.get("role") or f"{book} 자격증", "short": short, "exam": c.get("exam") or short,
            "series": c.get("series") or title, "full": c.get("full") or book}


# 원고 조립 규칙(예시 대본·발음 보정 등)을 바꾸면 올린다 → 집필은 저장된 것을 재사용하고 원고만 다시 만든다
MANUSCRIPT_VERSION = 8
CIRCLED = "①②③④⑤"
SINO = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구", "십"]


# ── 노트 HTML → 모델에게 줄 텍스트 ────────────────────────────────────────
def _block_text(fragment: str, figs: List[str]) -> str:
    def fig_sub(m: re.Match) -> str:
        figs.append(m.group(0))
        words = " ".join(re.findall(r"<text\b[^>]*>(.*?)</text>", m.group(0), re.S))
        return f"\n[FIG {len(figs)}: 도식 — 그림 안 글자: {strip_tags(words)[:300]}]\n"

    s = SVG_RE.sub(fig_sub, fragment)
    s = re.sub(r"<li\b[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"</t[dh]>\s*<t[dh]\b[^>]*>", " | ", s, flags=re.I)
    s = re.sub(r"<tr\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<(p|div|br|ul|ol|table)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<(b|strong)>(.*?)</\1>", r"**\2**", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _script_block(x: Sub, figs: List[str]) -> str:
    """영상 원고 h3 한 장 — 도식(SVG·표)은 FIG 로 떼고, 검수된 내레이션을 붙인다."""
    body = x.html
    for t in TABLE_RE.findall(body):
        figs.append(t)
        body = body.replace(t, f"\n[FIG {len(figs)}: 표 — {strip_tags(t)[:200]}]\n", 1)
    txt = _block_text(body, figs)
    out = f"(기존 영상 원고 판서)\n{txt}\n(기존 내레이션 — 검수됨)\n{x.say}"
    if x.read and x.read.strip() != x.say.strip():
        out += f"\n(기존 발음)\n{x.read}"
    return out.strip()


def section_prompt_text(sec: Section, script: Dict[str, List[Sub]] | None = None) -> Tuple[str, List[str]]:
    """노트 섹션(+ 있으면 같은 섹션의 영상 원고) → 모델 입력 텍스트와 FIG 목록.

    ★ 영상 원고가 있으면 도식은 **원고 쪽 것**을 쓴다(노트보다 훨씬 많다: 3과목 2개 → 130개).
      노트 본문은 사실 근거로만 함께 준다.
    """
    figs: List[str] = []
    script = script or {}
    use_script = any(script.values())
    lead = re.sub(SVG_RE, "", sec.lead_html) if use_script else sec.lead_html
    parts = [f"## [{sec.id}] {sec.title}", _block_text(lead, figs)]
    for sub in sec.subs:
        parts.append(f"\n### [{sub.id}] {sub.title}")
        xs = script.get(sub.id) or []
        note_html = re.sub(SVG_RE, "", sub.html) if xs else sub.html
        parts.append("(요약노트 — 사실 근거)\n" + _block_text(note_html, figs))
        for x in xs:
            parts.append(_script_block(x, figs))
    return "\n".join(p for p in parts if p), figs


# ── LLM 호출 (Claude Code 구독 CLI, API 키 없음) ──────────────────────────
def find_claude(job: Job) -> str:
    """claude 실행 파일 — 엔진(backplate llm/claude_provider.find_cli)과 같은 순서로 찾는다.

    CLAUDE_CLI 환경변수 → job.json llm.cli(경로) → PATH 의 네이티브 → VSCode 확장 번들 → PATH 의 .cmd
    ★ 설치본 없이 VSCode 확장만 있는 PC 가 실제로 있다(이 PC 가 그렇다).
    """
    import os
    import shutil
    env = (os.environ.get("CLAUDE_CLI") or "").strip().strip('"')
    if env and Path(env).exists():
        return env
    cfg = job.get("llm.cli", "claude")
    if cfg and Path(cfg).exists():
        return cfg
    batch = None
    w = shutil.which(cfg or "claude")
    if w:
        if Path(w).suffix.lower() in (".cmd", ".bat"):
            batch = w
        else:
            return w
    for pat in ("anthropic.claude-code-*/resources/native-binary/claude.exe",
                "anthropic.claude-code-*/resources/native-binary/claude"):
        hits = sorted((Path.home() / ".vscode" / "extensions").glob(pat))
        if hits:
            return str(hits[-1])
    if batch:
        return batch
    raise SystemExit("[error] claude 실행 파일을 찾지 못했습니다 — Claude Code 를 설치·로그인하거나 CLAUDE_CLI 를 지정하십시오")


def call_llm(job: Job, prompt: str) -> str:
    import os
    cli = find_claude(job)
    cmd = [cli, "-p", "--output-format", "text"]
    if job.get("llm.model"):
        cmd += ["--model", job.get("llm.model")]
    if job.get("enrich.web"):
        cmd += ["--allowedTools", "WebSearch,WebFetch"]      # 보강 모드일 때만 웹을 연다
    # ★ 오래된 API 키 환경변수가 구독 로그인을 가로채 다른 계정에 과금되는 것을 막는다(엔진과 같은 규칙)
    env = dict(os.environ, ANTHROPIC_API_KEY="", ANTHROPIC_AUTH_TOKEN="", ANTHROPIC_BASE_URL="")
    from longform.llm_wait import is_limit, wait_for_claude
    for _ in range(4):
        p = run_cmd(cmd, input_text=prompt, capture=True, check=False, env=env,
                    timeout=float(job.get("llm.timeout_sec", 900)))
        out = (p.stdout or "") + (p.stderr or "")
        # ★ 5시간 한도 등에 걸리면 재설정 시각까지 기다렸다 같은 프롬프트로 다시(무인 제작이 멈추지 않게)
        if (p.returncode != 0 or len(p.stdout or "") < 400) and is_limit(out):
            if wait_for_claude(job, out[-800:]):
                continue
            raise RuntimeError(f"claude 한도가 풀리지 않았습니다: {out[-300:]}")
        if p.returncode != 0:
            raise RuntimeError(f"claude 실패({p.returncode}): {out[-500:]}")
        return p.stdout
    raise RuntimeError("claude 한도로 여러 번 실패했습니다")


def parse_json(text: str) -> Dict[str, Any]:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("JSON 이 없습니다")
    return json.loads(t[a:b + 1])


# ── 발음: 숫자 + 한자어 단위 ──────────────────────────────────────────────
# ★ TTS 는 「2번」을 「두 번」으로 읽는다(2026-10-02 실측: "정답은 두번입니다").
#   문항 번호·회차·강·과목 같은 단위는 한자어로 읽어야 한다 → 발음 대본(read)에서 미리 풀어 둔다.
#   고유어로 읽는 단위(개·가지·명·시간·살)는 건드리지 않는다.
SINO_UNITS = "번|회|강|과목|단계|장|절|점|년|월|일|층|차|쪽|퍼센트|등급|위|호|부|편|기"
_UNIT_RE = re.compile(r"(\d+)\s*(" + SINO_UNITS + r")(?![가-힣]{0,0}[다])")
_D = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]


def sino(n: int) -> str:
    if n == 0:
        return "영"
    out = []
    for val, name in ((10000, "만"), (1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, val)
        if q:
            out.append(("" if q == 1 and val != 10000 else (sino(q) if val == 10000 else _D[q])) + name)
    if n:
        out.append(_D[n])
    return "".join(out)


def fix_counters(text: str) -> str:
    """「정답은 2번입니다」→「정답은 이 번입니다」, 「6회 1번」→「육 회 일 번」."""
    return _UNIT_RE.sub(lambda m: f"{sino(int(m.group(1)))} {m.group(2)}", text or "")


def speech_read(say: str, read: str) -> str:
    """발음 대본 — 모델이 준 read 가 있으면 그것을, 없으면 자막에서. 숫자+한자어 단위만 고친다. 같으면 빈 값."""
    base = read or say
    fixed = fix_counters(base)
    return "" if fixed == say else fixed


# ── 예시 문항 슬라이드 ────────────────────────────────────────────────────
def _num_say(n: int) -> str:
    return SINO[n] if 0 <= n <= 10 else str(n)


FENCE_RE = re.compile(r"```[\w-]*\n(.*?)```", re.S)
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def passage_html(passage: str, assets: List[Dict[str, Any]]) -> str:
    """문항 앱(책 폴더 _rounds)의 지문(마크다운 조각) → 카드용 HTML. 코드 블록·그림(assets 의 svg)·표를 살린다."""
    svgs = {a.get("name"): a.get("svg") for a in assets or [] if a.get("svg")}
    out: List[str] = []
    pos = 0
    for m in FENCE_RE.finditer(passage or ""):
        out.append(_md_text(passage[pos:m.start()], svgs))
        out.append(f"<pre>{html.escape(m.group(1).rstrip())}</pre>")
        pos = m.end()
    out.append(_md_text((passage or "")[pos:], svgs))
    return "".join(out)


def _md_text(t: str, svgs: Dict[str, str]) -> str:
    out: List[str] = []
    rows: List[str] = []

    def flush() -> None:
        if rows:
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows
                     if not re.fullmatch(r"\|?[\s:\-|]+\|?", r.strip())]
            if cells:
                head, *body = cells
                out.append("<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in head) + "</tr>"
                           + "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in body)
                           + "</table>")
            rows.clear()

    for line in t.split("\n"):
        s = line.strip()
        if s.startswith("|"):
            rows.append(s)
            continue
        flush()
        if not s:
            continue
        m = IMG_RE.fullmatch(s)
        if m:
            name = Path(m.group(2)).stem
            if svgs.get(name):
                out.append(f'<div class="fig">{svgs[name]}</div>')
            continue
        if re.match(r"^[-*•]\s+", s):            # 「- (가) …」 목록 줄 → 글머리 없는 목록(기호는 화면에서 뺀다)
            item = html.escape(strip_tags(re.sub(r"^[-*•]\s+", "", s)))
            out.append(f'<p class="li">{item}</p>')
            continue
        out.append(f"<p>{html.escape(strip_tags(s))}</p>")
    flush()
    return "".join(out)


def passage_say(passage: str) -> str:
    """지문을 소리로 — 코드·그림·표는 읽지 않고 「보십시오」로 갈음한다."""
    t = FENCE_RE.sub(" 화면의 SQL 을 보십시오. ", passage or "")
    t = IMG_RE.sub(" 그림을 보십시오. ", t)
    t = "\n".join(l for l in t.split("\n") if not l.strip().startswith("|"))
    return re.sub(r"\s+", " ", strip_tags(t)).strip()


def example_label(k: int) -> str:
    # ★ 영상에는 회차·번호를 남기지 않는다(사용자 지시 2026-10-09: 「모의 N회 M번」도 「문제 12」도 쓰지 않음 —
    #   출간본·사이트의 번호와 다를 수 있다). k 는 말 순서(첫 문제/다음 문제)에만 쓴다. 교재(s8)는 「기출 맛보기 k」.
    return "기출 맛보기"


def question_card(q: Dict[str, Any], k: int) -> str:
    choices = q.get("choices") or []
    # ★ 칩(「기출 맛보기」)은 넣지 않는다 — 장 제목과 같은 말이 두 번 나왔다(사용자 지시 2026-10-09)
    return ('<div class="qc">'
            f'<div class="qq">{html.escape(q.get("question", ""))}</div>'
            + (f'<div class="qp">{passage_html(q.get("passage") or "", q.get("assets") or [])}</div>' if q.get("passage") else "")
            + "<ol>" + "".join(f"<li>{html.escape(c)}</li>" for c in choices) + "</ol></div>")


_HANGUL_ITEM = {"가": "가", "나": "나", "다": "다", "라": "라", "마": "마", "ㄱ": "기역", "ㄴ": "니은", "ㄷ": "디귿", "ㄹ": "리을"}
_NUM_KO = ["", "하나", "둘", "셋", "넷", "다섯"]


def spoken(text: str) -> str:
    """화면 글을 강사가 읽는 말로 — 목록 기호·줄표·낫표·괄호 항목을 말로 풀거나 뺀다."""
    t = text or ""
    t = re.sub(r"\(([가-라ㄱ-ㄹ])\)", lambda m: f"{_HANGUL_ITEM.get(m.group(1), m.group(1))},", t)   # (가) → 가,
    t = re.sub(r"(?m)^\s*[-*•·]\s*", "", t)                     # 목록 기호
    t = re.sub(r"\s*[—–]\s*", ", ", t)                           # 줄표 → 쉼표
    t = re.sub(r"[「」『』\"“”‘’]", "", t)                        # 낫표·따옴표
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)                      # 1,200 → 1200 (TTS 가 숫자로 읽게)
    t = re.sub(r"\s*\n\s*", ". ", t.strip())
    t = re.sub(r"\.\s*\.", ".", t)
    return re.sub(r"\s+", " ", t).strip()


_JAMO_NAME = {"ㄱ": "기역", "ㄴ": "니은", "ㄷ": "디귿", "ㄹ": "리을", "ㅁ": "미음", "ㅂ": "비읍", "ㅅ": "시옷", "ㅇ": "이응"}


def jamo_read(text: str) -> str:
    """해설의 보기 기호를 소리로 — 「(ㄱ)」→「, 기역」, 「ㄴ은」→「니은은」. 자막은 그대로 두고 발음(read)에만 쓴다.

    ★ 사이트 문항에는 말 해설(explanation_speech)이 없어 글 해설을 그대로 읽힌다 → TTS 가 「(ㄴ)」을 엉뚱하게 읽었다
      (2026-10-09 L01 실측: 풀이 장 4곳, 사용자 귀에는 「17번ㄴ」처럼 들림).
    """
    t = re.sub(r"\(\s*([ㄱ-ㅇ])\s*\)", lambda m: f", {_JAMO_NAME[m.group(1)]}", text or "")
    # 앞에 음절이 붙지 않은 자음 하나 = 보기 기호(뒤에 조사 「은·의·이·:」가 와도 된다)
    return re.sub(r"(?<![가-힣ㄱ-ㅎ])([ㄱ-ㅇ])(?![ㄱ-ㅎ])", lambda m: _JAMO_NAME[m.group(1)], t)


def example_slides(q: Dict[str, Any], k: int) -> List[Dict[str, Any]]:
    """기출 맛보기 2장 — 문제 장(카드 이미지 + 강사식 읽기), 풀이 장(말 해설).

    ★ 지문을 글자 그대로 읽지 않는다(실측: "- (가) … — …「」" 를 다 읽어 어색했다). 기호는 말로 풀고,
      표·코드·그림이 있거나 길면 「화면의 자료를 보십시오」로 넘어간다.
    """
    choices = q.get("choices") or []
    ans = int(q.get("answer_index", 0))
    body_q = [q["question"]] + ([passage_say(q["passage"])[:120]] if q.get("passage") else [])
    # ★ 문제를 줄줄 읽지 않는다(사용자 지시 2026-10-02: "핵심만 말해줘도 되") — 화면에 문제가 다 보인다.
    #   무엇을 묻는 문제인지 + 핵심 개념(태그) 한 줄 + 풀어 보라는 말. 정답·이유는 다음 장(풀이)이 말 해설로 한다.
    stem = spoken(q["question"]).rstrip("?？. ")
    stem = re.sub(r"(것은|것을 고르면|것은 무엇인가)$", "것", stem)
    tags = [t for t in (q.get("tags") or []) if t][:2]

    def _wa(w: str) -> str:            # 받침 있으면 「과」, 없으면 「와」
        c = w[-1] if w else ""
        return "과" if ("가" <= c <= "힣" and (ord(c) - 0xAC00) % 28) else "와"

    key = ""
    if len(tags) == 2:
        # 태그 안에 「와」가 이미 있을 수 있다(「데이터와 정보」) → 「A, 그리고 B」
        key = (f" 핵심은 {tags[0]}, 그리고 {tags[1]}입니다." if ("와 " in tags[0] or "과 " in tags[0])
               else f" 핵심은 {tags[0]}{_wa(tags[0])} {tags[1]}입니다.")
    elif tags:
        key = f" 핵심은 {tags[0]}입니다."
    what = f"{stem}을 고르는 문제입니다" if stem.endswith("것") else f"{stem}, 이것을 묻는 문제입니다"
    lead = "기출 맛보기입니다." if k <= 1 else "다음 문제입니다."
    say_q = (f"{lead} {what}.{key} "
             "화면의 자료와 보기를 보면서 잠시 정답을 골라 보십시오.")
    expl = q.get("explanation") or ""
    first = re.split(r"(?<=[.다])\s+", expl.strip())
    say_a = q.get("explanation_speech") or expl
    return [
        {"title": example_label(k), "kind": "example-q",
         "bullets": body_q + [f"{CIRCLED[i]} {c}" for i, c in enumerate(choices[:5])],
         # ★ 문제 장은 카드 이미지로 굽는다(렌더 단계) — SQL 코드·그림·표가 라벨 글자로는 안 산다
         "card": question_card(q, k),
         "say": say_q, "read": jamo_read(say_q), "fig": None},
        {"title": f"정답 {CIRCLED[ans] if ans < 5 else ans + 1} · 풀이", "kind": "example-a",
         "bullets": [f"{CIRCLED[ans] if ans < 5 else ans + 1} {choices[ans]}" if ans < len(choices) else ""]
                    + [x for x in first[:2] if x],
         # 자막은 해설 그대로, 소리는 보기 기호를 말로(jamo_read)
         "say": say_a, "read": jamo_read(say_a), "fig": None},
    ]


# ── 원고 HTML ─────────────────────────────────────────────────────────────
STYLE = """
body{font-family:'Pretendard','Noto Sans KR',sans-serif;line-height:1.55;color:#1d2433;max-width:960px;margin:24px auto}
h1{font-size:30px}h2{font-size:24px;margin-top:28px}h3{font-size:20px}
ul{margin:6px 0 10px 18px}li{margin:3px 0}
svg,img{max-height:300px;width:auto;max-width:100%;height:auto;display:block;margin:10px auto}
.fig{text-align:center}
"""


def _a(name: str, val: str) -> str:
    return f' {name}="{html.escape(val, quote=True)}"' if (val or "").strip() else ""


def render_html(lecture_label: str, book: str, groups: List[Dict[str, Any]],
                figs: List[str], cover: Optional[Dict[str, str]] = None,
                outro: Optional[Dict[str, str]] = None) -> str:
    """영상 원고 HTML — summaryhtml2videoscripthtml 산출물과 **같은 속성 규칙**.

        h1  data-say / data-read           표지에서 읽을 여는 말 / 그 발음
            data-outro-say / data-outro-read  마무리에서 읽을 닫는 말 / 그 발음
        h3  data-id    안 바뀌는 이름표(그림이 여기 매달린다)
            data-say   자막 겸 내레이션
            data-read  소리 나는 대로 적은 발음(다를 때만)
            data-src   근거가 된 기존 원고 h3 의 data-id (추적용)
            data-fig   이 장의 도식 번호(longform 전용)
    """
    cover, outro = cover or {}, outro or {}
    h1 = ("<h1" + _a("data-say", cover.get("say", "")) + _a("data-read", cover.get("read", ""))
          + _a("data-outro-say", outro.get("say", "")) + _a("data-outro-read", outro.get("read", ""))
          + f">{html.escape(lecture_label)}</h1>")
    out = [f"<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
           f"<title>{html.escape(lecture_label)}</title><style>{STYLE}</style></head><body>",
           h1, f"<p>{html.escape(book)}</p>"]
    for g in groups:
        out.append(f"<h2>{html.escape(g['title'])}</h2>")
        for s in g["slides"]:
            attrs = f' data-id="{s["id"]}"' + _a("data-say", s["say"])
            if (s.get("read") or "").strip() and s["read"].strip() != s["say"].strip():
                attrs += _a("data-read", s["read"])
            attrs += _a("data-src", s.get("src", ""))
            if s.get("fig"):
                attrs += f' data-fig="{int(s["fig"])}"'
            out.append(f"<h3{attrs}>{html.escape(s['title'])}</h3>")
            bl = [b for b in s.get("bullets") or [] if b]
            if bl:
                out.append("<ul>" + "".join(f"<li>{html.escape(b)}</li>" for b in bl) + "</ul>")
            fi = s.get("fig")
            if fi and 1 <= int(fi) <= len(figs):
                out.append(f"<div class=\"fig\">{figs[int(fi) - 1]}</div>")
    out.append("</body></html>")
    return "\n".join(out)


# ── 개념 도형 보충 ────────────────────────────────────────────────────────
def fig_quota(job: Job, L: Dict[str, Any], sec_meta: Dict[str, Any]) -> int:
    """강당 도식 목표(기본 4)를 섹션 분량 비례로 나눈 이 섹션의 몫."""
    per = float(job.get("manuscript.figs_per_lecture", 4))
    tot = sum(s["target_chars"] for s in L["sections"]) or 1
    return int(round(per * sec_meta["target_chars"] / tot))


def fig_rule(need: int, have: int, job: Optional[Job] = None) -> str:
    if need <= 0:
        return "새 도형은 그리지 않는다. `new_figs` 는 빈 배열 []."
    from longform import theme
    th = theme.get(job) if job is not None else None
    if th:
        # 영상 테마 — 새 도형도 처음부터 테마 스타일로(먹선·어긋난 그림자·파스텔 채움·투명 바탕)
        fills = " ".join([th["table_head"], th["bases"][1]["bg"], th["bases"][2]["bg"], th["bases"][3]["bg"]])
        return (f"이 섹션은 노트 도식이 {have}개뿐이라 **개념 도형 SVG {need}개를 새로 그려** `new_figs` 에 넣는다. "
                f"새 도형 번호는 FIG {have + 1}부터 순서대로이고, 슬라이드의 `fig` 로 가리킨다. 규칙: "
                "노트에 있는 개념·관계·절차·비교만 그린다(흐름도, 계층 트리, 2×2 표, 비교표, 벤다이어그램, 축 그래프 등). "
                "viewBox 는 \"0 0 960 420\" 안팎의 가로형, **배경 rect 없음(투명)**, 글자는 한국어 font-size 18 이상·20자 이내. "
                f"스타일: 모든 외곽선 stroke {th['ink']} 굵기 3·round, 상자는 rx 14 + 오른쪽 6·아래 7 비낀 같은 크기 "
                f"{th['ink']} rect 를 뒤에 깔아 단색 그림자, 채움은 {fills} 를 돌려 쓰고 핵심 한 곳만 {th['accent']}(글자 흰색), "
                f"글자 fill {th['ink']} 굵기 800(제목)/500(설명), 화살표는 살짝 휜 path + 열린 화살촉(marker 금지). "
                "script·foreignObject·image·filter·외부 링크·font-family 지정 금지. 따옴표는 JSON 안이므로 \\\" 로 이스케이프한다.")
    return (f"이 섹션은 노트 도식이 {have}개뿐이라 **개념 도형 SVG {need}개를 새로 그려** `new_figs` 에 넣는다. "
            f"새 도형 번호는 FIG {have + 1}부터 순서대로이고, 슬라이드의 `fig` 로 가리킨다. 규칙: "
            "노트에 있는 개념·관계·절차·비교만 그린다(흐름도, 계층 트리, 2×2 표, 비교표, 벤다이어그램, 축 그래프 등). "
            "viewBox 는 \"0 0 960 420\" 안팎의 가로형, 첫 요소로 흰 배경 rect, 글자는 한국어 font-size 18 이상·20자 이내, "
            "색은 #1F4E79(진한 파랑) #9DC3E6(밝은 파랑) #334155(글자) #fff3d6(강조) 만. "
            "script·foreignObject·image·외부 링크·font-family 지정 금지. 따옴표는 JSON 안이므로 \\\" 로 이스케이프한다.")


_BAD_SVG = re.compile(r"<\s*(script|foreignObject|image|iframe)\b|\bon\w+\s*=|javascript:|xlink:href\s*=\s*\"http", re.I)


def clean_svg(svg: str) -> str:
    """모델이 그린 SVG 를 받아도 되는지 — XML 로 읽히고, 위험 요소가 없고, 너무 크지 않을 것."""
    import xml.etree.ElementTree as ET
    s = (svg or "").strip()
    if not s.startswith("<svg") or len(s) > 60_000 or _BAD_SVG.search(s):
        return ""
    if "xmlns=" not in s[:200]:
        s = s.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    try:
        root = ET.fromstring(s)
    except ET.ParseError:
        return ""
    if not root.tag.endswith("svg") or len(list(root.iter())) < 3:
        return ""
    return s


# ── 섹션 하나 ─────────────────────────────────────────────────────────────
def _position(i: int, n: int, L: Dict[str, Any], prev_title: Optional[str],
              short: str = "", exam: str = "") -> Tuple[str, str]:
    first, last = i == 0, i == n - 1
    pos = ("강의의 첫 섹션" if first else "강의의 중간 섹션") + (" 겸 마지막 섹션" if last and not first else "")
    if first and last:
        pos = "강의 전체(섹션 하나)"
    rules = []
    if first:
        rules.append(f"`cover` 에 표지에서 할 여는 말을 쓴다(\"안녕하십니까. {short} 이론 {L['no']}강, …입니다.\"로 시작, 2~3문장). "
                     f"그리고 맨 앞에 group 하나를 더 두어 sub_id 를 \"intro\" 로 하고, 오프닝 슬라이드 2장을 넣는다: "
                     f"① 이번 강에서 배울 것(이 강의 섹션들: {L['title']}) ② "
                     + (f"지난 강({prev_title}) 핵심 한 줄 복습과 연결" if prev_title else f"{exam} 시험에서 이 과목의 위치와 공부법"))
    if last:
        rules.append("맨 뒤에 group 하나를 더 두어 sub_id 를 \"wrap\" 으로 하고, 이번 강 전체 핵심 정리 슬라이드 2장을 넣는다"
                     f"(시험에 나오는 포인트 위주, 새 사실 금지). 그리고 `outro` 에 마무리에서 할 닫는 말을 쓴다"
                     f"(\"여기까지 {L['no']}강 …였습니다.\"로 시작, 다음 강 예고 한 문장, 2~3문장).")
    if not rules:
        rules.append("오프닝·정리 슬라이드는 넣지 않는다(다른 섹션이 맡는다). 바로 개념 설명으로 시작한다.")
    return pos, " ".join(rules)


def enrich_rule(job: Job) -> str:
    """웹 보강 — 목표에 따라 켠다(job.json enrich.web). 기조·맥락을 흔들지 않는 것이 조건이다."""
    if not job.get("enrich.web"):
        return "웹 검색은 하지 않는다. `sources` 는 빈 배열 []."
    n = int(job.get("enrich.max_searches", 3))
    focus = job.get("enrich.focus") or "최신 실무 사례, 시험 출제 경향, 개념을 이해시키는 친숙한 비유"
    return (f"웹 검색을 **최대 {n}회** 할 수 있다. 쓰임은 보충뿐이다 — {focus}. "
            "규칙: ① 노트·기존 내레이션이 언제나 우선이고, 웹 내용이 그와 어긋나면 버린다. "
            "② 정의·공식·분류 같은 시험 개념은 웹으로 바꾸지 않는다. "
            "③ 강의의 말투·순서·분량 배분을 바꾸지 않는다 — 보충은 슬라이드 몇 장 안의 한두 문장 수준. "
            "④ 확인되지 않은 수치·연도는 쓰지 않는다. "
            "⑤ 쓴 것은 `sources` 에 [{\"url\":…, \"used_for\": \"어느 슬라이드에 무엇을\"}] 로 남긴다.")


NOTE_RULE ="입력은 요약노트뿐이다. 노트의 사실을 쉬운 말로 풀고 예시·헷갈리는 포인트·시험 포인트로 분량을 채운다."
SCRIPT_RULE = ("입력에 「기존 내레이션 — 검수됨」이 있다. 이것은 이미 사람이 검수해 영상으로 낸 문장이므로 "
               "**뼈대로 그대로 살린다**(순서·용어·설명 방식 유지, 문장은 다듬어도 됨). 목표 분량까지는 "
               "그 사이에 예시·비교·헷갈리는 포인트·시험에서 묻는 방식을 덧붙여 늘린다. 「기존 영상 원고 판서」의 "
               "도식(FIG)은 가능한 한 그대로 다시 쓴다.")


def build_section(job: Job, L: Dict[str, Any], i: int, sec_meta: Dict[str, Any], sec: Section,
                  rounds: Dict, prev_title: Optional[str], force: bool, state: State,
                  script: Optional[Dict[str, List[Sub]]] = None) -> Path:
    lid = L["id"]
    d = job.manuscripts_dir / lid
    jf, hf = d / f"{sec.id}.json", d / f"{sec.id}.html"
    text, figs = section_prompt_text(sec, script)
    has_script = any((script or {}).values())
    n = len(L["sections"])
    crs = course(job)
    pos, rule = _position(i, n, L, prev_title, crs["short"], crs["exam"])
    target = int(sec_meta["target_chars"]) + (500 if i == 0 else 0) + (500 if i == n - 1 else 0)
    label = f"{job.get('title')} {lid} · {L['subject']}"
    need = fig_quota(job, L, sec_meta) - len(figs)
    # ★ 과정 이름은 지시문 틀에 먼저 글자 그대로 넣는다 — 같은 과정이면 지시문·해시가 예전과 한 글자도 다르지 않다
    tpl = PROMPT.read_text(encoding="utf-8").replace("{course_role}", crs["role"])
    prompt = tpl.format(
        lecture_label=f"{label} — {L['title']}", section_title=sec.title, position=pos,
        position_rule=rule, fig_rule=fig_rule(need, len(figs), job),
        source_rule=SCRIPT_RULE if has_script else NOTE_RULE, enrich_rule=enrich_rule(job),
        target_chars=target, target_slides=max(3, round(target / 220)),
        section_id=sec.id, section_text=text)
    exs = [e for e in L["examples"] if e["anchor"].startswith(sec.id)]
    # ★ 해시를 둘로 나눈다. 집필(Claude) = 프롬프트·모델만, 원고 = 집필 + 예시 문항.
    #   문항이 나중에 확정돼도(run.bat examples) Claude 를 다시 부르지 않고 예시만 끼운다.
    llm_h = sha(prompt, job.get("llm.model"), tpl)
    h = sha(llm_h, exs, MANUSCRIPT_VERSION)
    key = f"s2:{sec.id}"
    if not force and state.done(lid, key, h) and jf.exists() and hf.exists():
        log(f"{lid} {sec.id} 원고 — 그대로(해시 같음)")
        return hf

    cache = d / f"{sec.id}.llm.json"
    cached = read_json(cache, None)
    doc = None
    if cached and not force and cached.get("hash") == llm_h:
        doc = json.loads(json.dumps(cached["doc"]))
        log(f"{lid} {sec.id} 집필은 저장된 것 재사용 — 예시 문항만 다시 끼웁니다")
    else:
        log(f"{lid} {sec.id} 원고 생성 — 목표 {target}자 · {sec.title}")
    feedback = ""
    for attempt in range(0 if doc else 2):
        raw = call_llm(job, prompt + feedback)
        try:
            doc = parse_json(raw)
        except Exception as e:
            feedback = f"\n\n(이전 출력이 JSON 이 아니었습니다: {e}. JSON 하나만 출력하십시오.)"
            doc = None
            continue
        got = sum(chars(s.get("say", "")) for g in doc.get("groups", []) for s in g.get("slides", []))
        if got >= target * 0.8 or attempt == 1:
            if got < target * 0.8:
                warn(f"{lid} {sec.id} 분량 부족 {got}/{target}자 — 그대로 진행")
            break
        feedback = (f"\n\n(이전 출력의 내레이션이 공백 제외 {got}자로 목표 {target}자에 모자랍니다. "
                    f"노트 범위 안에서 설명을 더 풀어 같은 형식으로 다시 출력하십시오.)")
    if not doc:
        raise SystemExit(f"[error] {lid} {sec.id} 원고 JSON 을 얻지 못했습니다")
    if not (cached and cached.get("hash") == llm_h):
        write_json(cache, {"hash": llm_h, "doc": doc})
    doc = json.loads(json.dumps(doc))       # 아래에서 예시를 끼우며 고치므로 사본으로

    # 새 개념 도형 — 검증을 통과한 것만 FIG 번호를 이어 붙인다
    n_note = len(figs)
    for f in (doc.get("new_figs") or [])[:max(0, need)]:
        svg = clean_svg((f or {}).get("svg", ""))
        if svg:
            figs.append(svg)
        else:
            warn(f"{lid} {sec.id} 새 도형 하나가 SVG 검증에 실패해 버립니다")
    groups = doc.get("groups", [])
    for g in groups:
        for s in g.get("slides", []):
            try:
                fi = int(s.get("fig") or 0)
            except (TypeError, ValueError):
                fi = 0
            s["fig"] = fi if 1 <= fi <= len(figs) else None
    # 예시 문항 슬라이드를 근거 소주제 뒤에 붙인다(없으면 마지막 개념 group 뒤)
    by_sub = {g.get("sub_id"): g for g in groups}
    concept = [g for g in groups if g.get("sub_id") not in ("intro", "wrap")]
    # k = 그 강 안의 순번 — 강의 예시 목록(L["examples"]) 순서. 섹션이 나뉘어도 번호가 이어진다
    order = {(x["round"], x["no"]): i for i, x in enumerate(L.get("examples") or [], 1)}
    for e in exs:
        q = rounds.get((e["round"], e["no"]))
        if not q:
            continue
        k = order.get((e["round"], e["no"]), 1)
        tgt = by_sub.get(e["anchor"]) or (concept[-1] if concept else None)
        if tgt is None:
            tgt = {"sub_id": e["anchor"], "title": "기출 맛보기", "slides": []}
            groups.append(tgt)
        tgt["slides"].extend(example_slides(q, k))
    # wrap 은 항상 맨 뒤
    groups = [g for g in groups if g.get("sub_id") != "wrap"] + [g for g in groups if g.get("sub_id") == "wrap"]

    k = 0
    for g in groups:
        g["slides"] = [s for s in g.get("slides", []) if (s.get("say") or "").strip()]
        src_ids = ",".join(x.src_id for x in (script or {}).get(g.get("sub_id"), []) if x.src_id)
        for s in g["slides"]:
            k += 1
            s["id"] = f"{lid}-{sec.id}-{k:03d}"
            s["say"] = s["say"].strip()
            # 발음: 모델이 준 read 위에 숫자+한자어 단위(2번 → 이 번)만 고친다
            s["read"] = speech_read(s["say"], (s.get("read") or "").strip())
            if src_ids and not s.get("kind"):
                s["src"] = src_ids
            if s.get("fig") in ("", 0):
                s["fig"] = None
    groups = [g for g in groups if g["slides"]]

    # ★ 2섹션부터는 표지(인사)가 빠지므로, 첫 장이 무엇을 배우는지 알리지 않으면 앞 섹션에서 툭 넘어간다
    #   (2026-10-02 실측: 1섹션 "…모두 살펴보았습니다." → 2섹션 "정형과 반정형, 비정형을 가르는 기준은…").
    #   이미 들어가는 말이 있으면 두고, 없으면 「이어서 ○○을 보겠습니다.」를 붙인다(Claude 호출 없음).
    if i > 0 and groups and groups[0]["slides"]:
        s0 = groups[0]["slides"][0]
        if not re.match(r"^\s*(이번|이제|이어서|다음으로|지금부터|계속해서)", s0["say"]):
            topic = re.sub(r"^\s*\d+(\.\d+)*\.?\s*", "", sec.title).strip()
            spoken_t = re.sub(r"\s*[·∙]\s*", ", ", re.sub(r"\s*[—–-]\s*", ", ", topic)).strip(", ")
            c = spoken_t[-1] if spoken_t else ""
            obj = "을" if ("가" <= c <= "힣" and (ord(c) - 0xAC00) % 28) else "를"
            bridge = f"이어서 {spoken_t}{obj} 보겠습니다. "
            s0["say"] = bridge + s0["say"]
            s0["read"] = speech_read(s0["say"], (bridge + s0["read"]) if s0.get("read") else "")

    def _pair(d: Any) -> Dict[str, str]:
        d = d if isinstance(d, dict) else {}
        say, read = (d.get("say") or "").strip(), (d.get("read") or "").strip()
        return {"say": say, "read": speech_read(say, read)}

    # 여는 말은 첫 섹션, 닫는 말은 마지막 섹션만 — 모델이 안 줬으면 기본 문구
    cover = _pair(doc.get("cover")) if i == 0 else {"say": "", "read": ""}
    outro = _pair(doc.get("outro")) if i == n - 1 else {"say": "", "read": ""}
    if i == 0 and not cover["say"]:
        cover = {"say": f"안녕하십니까. {job.get('title')} {L['no']}강, {L['title']}입니다.", "read": ""}
    if i == n - 1 and not outro["say"]:
        outro = {"say": f"여기까지 {L['no']}강이었습니다. 다음 강에서 뵙겠습니다. 감사합니다.", "read": ""}

    total = sum(chars(s["say"]) for g in groups for s in g["slides"]) + chars(cover["say"] + outro["say"])
    write_json(jf, {"lecture": lid, "section": sec.id, "title": sec.title, "label": label,
                    "cover": cover, "outro": outro,
                    "groups": groups, "figs": figs, "figs_note": n_note, "figs_new": len(figs) - n_note,
                    "from_script": has_script, "sources": doc.get("sources") or [],
                    "say_chars": total,
                    "est_sec": round(total / float(job.get("curriculum.chars_per_sec", 5.5)))})
    hf.parent.mkdir(parents=True, exist_ok=True)
    hf.write_text(render_html(f"{label} — {sec.title}", job.get("book", ""), groups, figs, cover, outro),
                  encoding="utf-8")
    state.mark(lid, key, h, slides=k, say_chars=total, figs=len(figs), figs_new=len(figs) - n_note)
    log(f"{lid} {sec.id} → 슬라이드 {k}장 · 내레이션 {total}자(약 {total / 5.5 / 60:.1f}분) · "
        f"도식 {len(figs)}개(새로 {len(figs) - n_note})")
    return hf


def run(job: Job, only: Optional[List[str]] = None, force: bool = False,
        sections_limit: Optional[int] = None) -> None:
    cur = read_json(job.dir / "curriculum.json")
    if not cur:
        raise SystemExit("[error] curriculum.json 이 없습니다 — 먼저 s1")
    rounds_dir = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rounds_dir) if rounds_dir and rounds_dir.exists() else {}
    state = State(job)
    # 노트 + 영상 원고(summaryhtml2videoscripthtml 산출물, 없어도 됨) — 부 번호로 짝짓는다
    note_list, scripts = load_inputs(job)
    notes: Dict[int, Note] = {n.subject_no: n for n in note_list}
    if not scripts:
        warn("영상 원고가 없습니다 — 요약노트만으로 집필합니다")

    tasks = []
    prev_title = None
    for L in cur["lectures"]:
        if only and L["id"] not in only:
            prev_title = L["title"]
            continue
        note = notes.get(int(L["subject_no"]))
        if not note:
            raise SystemExit(f"[error] {L['id']} 의 노트({L['subject_no']}부)가 없습니다 — 편성표와 원천이 맞는지 보십시오")
        secs = {s.id: s for s in note.sections}
        metas = L["sections"][:sections_limit] if sections_limit else L["sections"]
        sc = scripts.get(int(L["subject_no"]))
        for i, sm in enumerate(metas):
            sec = secs[sm["id"]]
            tasks.append((L, i, sm, sec, prev_title, script_for(note, sc, sec)))
        prev_title = L["title"]

    par = max(1, int(job.get("llm.parallel", 3)))
    with ThreadPoolExecutor(max_workers=par) as ex:
        futs = [ex.submit(build_section, job, L, i, sm, sec, rounds, pt, force, state, smap)
                for (L, i, sm, sec, pt, smap) in tasks]
        for f in as_completed(futs):
            f.result()
    log(f"원고 {len(tasks)}개 완료 → {job.manuscripts_dir}")
