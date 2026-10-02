"""s7 — 업로드된 영상 ID 를 사이트·리뷰 페이지·기록용 파일로 만든다(사람이 ID 를 붙여넣던 일을 없앤다).

★ **레포 밖에는 쓰지 않는다.** 결과는 전부 jobs/<job>/out/register/ 에 생긴다.
  사이트(문항 앱)·보고서 폴더로 옮기는 것은 사람이 한다 — 이 레포가 다른 폴더에 기대지 않게.

    out/register/youtube_map.<pd>.json   문항 앱 사이트 데이터 폴더에 그대로 넣는 형식
        theory["1"|"2"|"3"] = 그 과목 첫 강(사이트 이론 탭의 과목 버튼은 하나뿐이다)
        theory_lectures[Lxx] = 모든 강(사이트는 아직 안 읽는다 — 기록·다음 확장용)
    out/register/review.html             input/review.html 의 VIDEOS_BY_TAB[review_tab] 맨 앞에 강 목록을 넣은 사본
        `// longform:begin` ~ `// longform:end` 사이만 다시 쓴다 → 몇 번 돌려도 같은 결과, 기존 항목 보존
    out/register/README.txt              어디로 옮기면 되는지
    logs/statements.jsonl                published 기록(xAPI 식)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from longform.config import Job
from longform.state import State
from longform.util import log, read_json, statement, warn, write_json

BEGIN, END = "// longform:begin", "// longform:end"


def _collect(job: Job) -> List[Dict[str, Any]]:
    cur = read_json(job.dir / "curriculum.json")
    state = State(job)
    ids = read_json(job.out_dir / "youtube_ids.json", {}) or {}
    from longform import team
    claims = team.all_claims(job)        # 팀원이 각자 PC 에서 올린 것(깃으로 모인다)
    rows = []
    for L in cur["lectures"]:
        yt = state.get(L["id"], "yt") or ids.get(L["id"]) or (claims.get(L["id"]) or {}).get("yt") or {}
        if yt.get("id") and not yt.get("dry_run"):
            rows.append({"L": L, "id": yt["id"], "title": yt.get("title", "")})
    return rows


def update_map(job: Job, rows: List[Dict[str, Any]], out_dir: Path) -> Path:
    pd = job.get("register.pd") or job.get("pd") or job.name
    f = out_dir / f"youtube_map.{pd}.json"
    base = job.path(job.get("register.youtube_map_base"))   # 레포 안에 둔 기존 맵(있으면 이어 씀)
    doc = read_json(f, None) or (read_json(base, None) if base and base.exists() else None)
    if doc is None:
        doc = {"_note": "longform 파이프라인이 theory·theory_lectures 를 만든다. videos(회차 영상)는 손대지 않는다.",
               "_provider": "youtube", "videos": {}}
    theory = doc.setdefault("theory", {})
    lect = doc.setdefault("theory_lectures", {})
    by_sub: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        by_sub.setdefault(int(r["L"]["subject_no"]), []).append(r)
        lect[r["L"]["id"]] = {"id": r["id"], "provider": "youtube", "subject": r["L"]["subject_no"],
                              "label": f"{r['L']['no']}강 · {r['L']['title']}"}
    for sub, rs in by_sub.items():
        rs.sort(key=lambda r: r["L"]["no"])
        theory[str(sub)] = {"id": rs[0]["id"], "provider": "youtube",
                            "label": f"{sub}과목 이론 강의 ({rs[0]['L']['no']}강부터)"}
    write_json(f, doc)
    log(f"youtube_map — 이론 {len(by_sub)}과목 · 강 {len(lect)}개 → {f}")
    return f


def _js(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def update_review(job: Job, rows: List[Dict[str, Any]], out_dir: Path) -> Path | None:
    src = job.path(job.get("register.review_html"))
    tab = job.get("register.review_tab", "")
    if not src or not src.exists() or not tab:
        warn("register.review_html / review_tab 이 없어 리뷰 페이지는 건너뜁니다")
        return None
    with src.open(encoding="utf-8", newline="") as fh:      # ★ 원본 줄바꿈(CRLF)을 지킨다
        text = fh.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    m = re.search(r'\n([ \t]*)"%s"\s*:\s*\{' % re.escape(tab), text)
    if not m:
        warn(f"review.html 에 탭 '{tab}' 블록이 없습니다 — 건너뜀")
        return None
    ind = m.group(1)
    body = re.sub(r"\r?\n[ \t]*%s.*?%s[^\r\n]*" % (re.escape(BEGIN), re.escape(END)), "", text[m.end():],
                  count=1, flags=re.S)
    by_sub: Dict[str, List[Dict[str, Any]]] = {}
    for r in sorted(rows, key=lambda r: r["L"]["no"]):
        by_sub.setdefault(f"이론 강의 · {r['L']['subject']}", []).append(r)
    lines = [f"{ind}  {BEGIN} (자동 생성 — 이 사이만 다시 쓴다)"]
    for grp, rs in by_sub.items():
        lines.append(f"{ind}  {_js(grp)}: [")
        lines += [f"{ind}    {{ label:{_js(str(r['L']['no']) + '강 · ' + r['L']['title'][:40])}, "
                  f"provider:\"youtube\", id:{_js(r['id'])} }}," for r in rs]
        lines.append(f"{ind}  ],")
    lines.append(f"{ind}  {END}")
    out = out_dir / "review.html"
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text[:m.end()] + nl + nl.join(lines) + body)
    log(f"review.html '{tab}' 탭에 강 {len(rows)}개 → {out}")
    return out


def run(job: Job) -> None:
    rows = _collect(job)
    if not rows:
        log("등록할 업로드 기록이 없습니다")
        return
    out_dir = job.out_dir / "register"
    out_dir.mkdir(parents=True, exist_ok=True)
    ymap = update_map(job, rows, out_dir)
    rev = update_review(job, rows, out_dir)
    pd = job.get("register.pd") or job.get("pd") or job.name
    (out_dir / "README.txt").write_text(
        "이 폴더의 파일을 옮기면 사이트·보고서에 반영됩니다(이 레포는 다른 폴더에 직접 쓰지 않습니다).\n\n"
        f"1) {ymap.name}\n   → 문항 앱의 사이트 데이터 폴더(youtube_map.*.json 이 있는 곳)에 덮어쓰기\n"
        f"   → 그다음 문항 앱에서 평소처럼 사이트를 다시 빌드(--pd {pd})하고 배포\n"
        + (f"2) review.html\n   → 보고서 별첨 _context/review.html 을 이것으로 교체(사이트 v1instruction/ 에도 올림)\n" if rev else ""),
        encoding="utf-8")
    for r in rows:
        statement("published", f"{pd}/theory/{r['L']['id']}", {"yt_id": r["id"]})
    log(f"등록 파일 완료 — {len(rows)}강 → {out_dir}  (README.txt 에 옮길 곳)")
