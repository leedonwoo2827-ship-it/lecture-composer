"""사이트 내보내기 가져오기 — 문제집 사이트(exam/assets/pd/<과정>)에서 받은 파일을 잡의 input/ 형식으로 바꾼다.

    run.bat import-site --job sqld --dir _assets\\sqld-2627

    <폴더>/problems.js           window.PROBLEMS = [...]  → input/rounds/mNN.json (exambook-forge 형식, 회차마다)
    <폴더>/figs/*.svg            문항 그림                 → 각 문항 assets 에 SVG 를 담고 지문 맨 앞에 ![그림](이름.svg)
    <폴더>/theory.js             과목 목록(label·href·sub)
    <폴더>/theory/summary_*.js   window.THEORY_HTML["theory/summary_x.html"] = "<html 문자열>"
    <폴더>/theory_content.js     (예전 판) 같은 내용을 한 파일에             → input/notes/0N-summary_x.html

★ 레포는 문항을 `_rounds/mNN.json`(문항 앱 책 폴더)으로만 읽는다(`s1_curriculum.load_rounds`). 사이트 내보내기는
  같은 문항을 웹용 JSON 으로 담고 있어 이름만 바꿔 옮긴다. 말 해설(explanation_speech)은 사이트에 없으므로 비운다 —
  풀이 장은 해설(explanation)을 그대로 읽는다.
★ 그림 `-답` 판(해설용)은 문제 카드에 넣지 않는다 — 정답이 보인다.
★ 웹앱 기획 화면의 「가져올 폴더」에 이 폴더를 적어도 같은 일을 한다(`web/server.py import_folder`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from longform.config import REPO, Job
from longform.util import log, warn


def is_site_export(src: Path) -> bool:
    return (src / "problems.js").is_file() or (src / "theory").is_dir() or (src / "theory_content.js").is_file()


def _js_value(text: str) -> Any:
    """`window.X = <json>;` 의 <json> 부분."""
    v = text.split("=", 1)[1].strip().rstrip(";").strip()
    return json.loads(v, strict=False)


def _theory_html(src: Path) -> Dict[str, str]:
    """href → HTML. 파일마다 한 줄씩(신판) / 한 파일에 여러 줄(구판) / 객체 하나(더 옛판) 모두 받는다."""
    out: Dict[str, str] = {}
    files = sorted((src / "theory").glob("*.js")) if (src / "theory").is_dir() else []
    if (src / "theory_content.js").is_file():
        files.append(src / "theory_content.js")
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            m = re.match(r'window\.THEORY_HTML\["([^"]+)"\]\s*=', line)
            if m:
                out[m.group(1)] = _js_value(line)
            elif re.match(r"window\.THEORY_HTML\s*=\s*\{", line):
                out.update(_js_value(line))
    return out


def _notes(src: Path, dst: Path) -> int:
    html = _theory_html(src)
    subs: List[Dict[str, Any]] = []
    if (src / "theory.js").is_file():
        subs = _js_value((src / "theory.js").read_text(encoding="utf-8", errors="replace"))
    if not subs:      # 목록이 없으면 HTML 에 있는 것 전부(h1 의 「N과목」 으로 번호가 매겨진다)
        subs = [{"href": k, "sub": i} for i, k in enumerate(sorted(html), 1) if "index" not in k]
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in subs:
        body = html.get(s.get("href", ""))
        if not body:
            warn(f"요약노트 내용이 없습니다: {s.get('href')}")
            continue
        name = f"{int(s.get('sub') or n + 1):02d}-{Path(s['href']).stem}.html"
        doc = ("<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
               f"<title>{s.get('label', '')}</title></head><body>\n{body}\n</body></html>\n")
        (dst / name).write_text(doc, encoding="utf-8")
        n += 1
    return n


def _question(q: Dict[str, Any], figs: Path) -> Dict[str, Any]:
    assets, marks = [], []
    for fn in q.get("figures") or []:
        p = figs / fn
        if Path(fn).stem.endswith("-답"):
            continue
        if p.is_file():
            assets.append({"name": Path(fn).stem, "svg": p.read_text(encoding="utf-8", errors="replace")})
            marks.append(f"![그림]({fn})")
        else:
            warn(f"그림 파일이 없습니다: {fn}")
    passage = "\n\n".join(marks + ([q["passage"]] if q.get("passage") else []))
    return {"question_no": int(q["number"]), "subject_no": int(q.get("subject_no") or 0),
            "subject": q.get("subject", ""), "question": q.get("question", ""), "passage": passage,
            "choices": q.get("choices") or [], "answer_index": int(q.get("answer_index") or 0),
            "answer": q.get("answer", ""), "explanation": q.get("explanation", ""), "explanation_speech": "",
            "tags": q.get("tags") or [], "difficulty": q.get("difficulty", ""), "assets": assets,
            "src_id": q.get("src_id", "")}


def _rounds(src: Path, dst: Path) -> Dict[str, int]:
    probs = _js_value((src / "problems.js").read_text(encoding="utf-8", errors="replace"))
    by: Dict[int, List[Dict[str, Any]]] = {}
    for q in probs:
        by.setdefault(int(q["round_num"]), []).append(_question(q, src / "figs"))
    dst.mkdir(parents=True, exist_ok=True)
    for r, qs in sorted(by.items()):
        qs.sort(key=lambda x: x["question_no"])
        (dst / f"m{r:02d}.json").write_text(json.dumps({"round": r, "questions": qs}, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    return {"rounds": len(by), "questions": len(probs),
            "with_figure": sum(1 for qs in by.values() for x in qs if x["assets"])}


def sync_inputs(job: Job) -> None:
    """input/ 에 실제로 있는 파일로 목표서 inputs 를 다시 적는다(웹앱 `_sync_inputs` 와 같은 규칙)."""
    f = job.dir / "job.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    rel = lambda p: p.relative_to(REPO).as_posix()  # noqa: E731
    ins = doc.setdefault("inputs", {})
    ins["notes"] = [rel(p) for p in sorted((job.input_dir / "notes").glob("*.htm*"))]
    ins["scripts"] = [rel(p) for p in sorted((job.input_dir / "scripts").glob("*.htm*"))]
    ins["rounds_dir"] = rel(job.input_dir / "rounds")
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def convert(job: Job, src: Path) -> Dict[str, Any]:
    if not is_site_export(src):
        raise SystemExit(f"[error] 사이트 내보내기 폴더가 아닙니다(problems.js·theory/ 없음): {src}")
    got: Dict[str, Any] = {"notes": _notes(src, job.input_dir / "notes")}
    if (src / "problems.js").is_file():
        got.update(_rounds(src, job.input_dir / "rounds"))
    sync_inputs(job)
    log(f"사이트 내보내기 가져옴 — 요약노트 {got['notes']} · 회차 {got.get('rounds', 0)} · "
        f"문항 {got.get('questions', 0)} (그림 {got.get('with_figure', 0)})")
    return got


def run(job: Job, folder: str) -> Dict[str, Any]:
    src = Path(folder.strip().strip('"'))
    if not src.is_absolute():
        src = (REPO / src).resolve()
    return convert(job, src)
