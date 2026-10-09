"""s1 — 요약노트 → 커리큘럼(curriculum.json).

과목마다 h2 섹션을 **순서를 지키며** 연속 구간으로 묶어 N강을 만든다(최대 분량을
최소화하는 선형 분할). 강마다 예시 문항(자사 모의고사)을 노트의 「모의 N회 M번」
근거에서 고른다 — 여러 항목이 가리키는 문항일수록 우선, 강 사이 중복 없이.

분량 공식(공백 제외 글자, backplate 실측 5.5자/초):
    강 길이(초) = 오프닝·정리(fixed_sec) + 예시 문항 수 × 문항당 초 + 개념(나머지)
    개념 목표 글자 = 개념 초 × chars_per_sec  → 섹션별로 노트 분량 비례 배분
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from longform.config import Job
from longform.notes import Note, Section, chars, load_inputs
from longform.util import log, read_json, warn, write_json


def _partition(weights: List[int], k: int) -> List[Tuple[int, int]]:
    """weights 를 순서대로 k 구간으로 — 구간 합이 평균에서 벗어난 제곱합을 최소화(DP).

    ★ 「가장 무거운 구간 최소화」는 나머지 구간을 아무렇게나 둔다(실측: 군집분석 1,140자가
      혼자 한 강이 되어 확장비 4.5배). 고르게 나누는 것이 목적이므로 편차 제곱합을 쓴다.
    """
    n = len(weights)
    k = max(1, min(k, n))
    pre = [0]
    for w in weights:
        pre.append(pre[-1] + w)
    avg = pre[-1] / k
    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0
    for j in range(1, k + 1):
        for i in range(1, n + 1):
            for p in range(j - 1, i):
                v = dp[j - 1][p] + (pre[i] - pre[p] - avg) ** 2
                if v < dp[j][i]:
                    dp[j][i], cut[j][i] = v, p
    out, i = [], n
    for j in range(k, 0, -1):
        p = cut[j][i]
        out.append((p, i))
        i = p
    return out[::-1]


def load_rounds(rounds_dir: Path) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """(회차, 번호) → 문항. _rounds/mNN.json(exambook-forge author-questions 형식)."""
    out: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for f in sorted(rounds_dir.glob("m*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        rnd = int(doc.get("round") or int(f.stem.lstrip("m")))
        for q in doc.get("questions") or []:
            out[(rnd, int(q["question_no"]))] = q
    return out


def question_seconds(q: Dict[str, Any], cps: float) -> float:
    """예시 문항 2장(문제 장 + 풀이 장)의 예상 길이.

    ★ 문제 장은 지문·보기를 **읽지 않는다**(s2 example_slides: 무엇을 묻는지 + 핵심 한 줄 + "골라 보십시오").
      예전 어림은 지문·보기까지 다 읽는다고 쳐서 실제의 1.7배로 잡혔다(2026-10-09 L01 실측: 14문항 계획 15.7분 → 실제 9.4분).
      문제 장 ≈ 문제 문장 + 45자, 풀이 장 = 해설, 장 사이 숨 2번(0.9초).
    """
    say_q = chars(q.get("question", "")) + 45
    say_a = chars(q.get("explanation_speech") or q.get("explanation") or "") + 15
    return (say_q + say_a) / cps + 0.9


def _pick_examples(secs: List[Section], rounds: Dict, used: set, n: int) -> List[Dict[str, Any]]:
    """강의 섹션들이 가리키는 문항 중 n개. 많이 가리켜질수록, 회차가 겹치지 않을수록 우선."""
    score: Dict[Tuple[int, int], int] = {}
    where: Dict[Tuple[int, int], str] = {}
    spec: Dict[Tuple[int, int], int] = {}     # 근거 소주제의 근거 수 — 적을수록 그 문항에 구체적
    for s in secs:
        for sub in s.subs:
            for r in sub.refs:
                score[r] = score.get(r, 0) + 1
                if r not in spec or len(sub.refs) < spec[r]:
                    spec[r], where[r] = len(sub.refs), sub.id
        for r in s.refs:
            score[r] = score.get(r, 0) + 1
            where.setdefault(r, s.subs[0].id if s.subs else s.id)
    cand = sorted((r for r in score if r in rounds and r not in used),
                  key=lambda r: (-score[r], r))
    picked: List[Tuple[int, int]] = []
    seen_rounds: set = set()
    for r in cand:                       # 1차: 회차가 겹치지 않게
        if len(picked) >= n:
            break
        if r[0] not in seen_rounds:
            picked.append(r)
            seen_rounds.add(r[0])
    for r in cand:                       # 2차: 모자라면 채운다
        if len(picked) >= n:
            break
        if r not in picked:
            picked.append(r)
    used.update(picked)
    return [{"round": r[0], "no": r[1], "anchor": where[r], "score": score[r]} for r in picked]


def fit_examples(secs: List[Section], rounds: Dict, used: set, n: int, budget_sec: float,
                 cps: float) -> List[Dict[str, Any]]:
    """예산(초) 안에 드는 만큼 — 많이 가리켜진 문항부터, 넘치면 뒤에서 덜어 낸다."""
    if not rounds or n <= 0 or budget_sec <= 0:
        return []
    ex = _pick_examples(secs, rounds, used, n)
    while ex and sum(question_seconds(rounds[(e["round"], e["no"])], cps) for e in ex) > budget_sec:
        used.discard((ex[-1]["round"], ex[-1]["no"]))
        ex.pop()
    return ex


def refresh_examples(job: Job) -> Path:
    """문항만 바뀌었을 때 — 편성표의 강 나누기(사람이 고친 것 포함)는 그대로 두고 **예시만** 다시 고른다."""
    out = job.dir / "curriculum.json"
    doc = read_json(out)
    if not doc:
        raise SystemExit("[error] curriculum.json 이 없습니다 — 먼저 plan")
    c = job.get("curriculum", {})
    cps = float(c.get("chars_per_sec", 5.5))
    n_ex = examples_per_lecture(job)
    budget = (float(c.get("examples_budget_min", 14)) * 60) if n_ex > 0 else 0.0
    rd = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rd) if rd and rd.exists() else {}
    if not rounds:
        raise SystemExit("[error] 문항(input/rounds/mNN.json)이 없습니다 — 먼저 넣으십시오")
    notes, _ = load_inputs(job)
    by_id = {s.id: s for n in notes for s in n.sections}
    used: set = set()
    filled = 0
    for L in doc["lectures"]:
        secs = [by_id[s["id"]] for s in L["sections"] if s["id"] in by_id]
        L["examples"] = fit_examples(secs, rounds, used, n_ex, budget, cps)
        p = L.setdefault("plan", {})
        p["examples_sec"] = round(sum(question_seconds(rounds[(e["round"], e["no"])], cps) for e in L["examples"]))
        p["examples_budget_sec"] = round(budget)
        p["examples_pending"] = not L["examples"]
        filled += len(L["examples"])
        log(f"{L['id']} 예시 {len(L['examples'])}문항 · {p['examples_sec'] // 60}분 / 예산 {budget / 60:.0f}분")
    write_json(out, doc)
    log(f"예시 {filled}문항 반영 — 강 나누기는 그대로입니다. 이어서 compose(원고는 저장된 집필을 재사용) → render")
    return out


SLIDE_GAP = 0.45      # 장 사이 숨(render/hyper.py TAIL_SEC)


def examples_per_lecture(job: Job) -> int:
    """영상에 넣는 기출 맛보기 수. curriculum.video_examples=false 면 0 — 영상은 개념만, 문제는 교재에만
    (사용자 결정 2026-10-09: 「종합본 강의에는 문제가 안 나와도 된다, 책에는 자주 나와도 된다」)."""
    if not job.get("curriculum.video_examples", True):
        return 0
    return int(job.get("curriculum.examples_per_lecture", 10))


def fill_to_target(job: Job, lid: str) -> int:
    """집필이 끝난 강의 **실제 원고 길이**를 재서, 강 길이 목표에 모자란 만큼 기출 맛보기를 더 넣는다.

    ★ 원고는 목표 분량보다 짧게 나오기도 한다(2026-10-09 L01: 25.1분/30분). 모자란 시간은 문제로 채운다 —
      문항 하나 ≈ 37.5초(문제 장 + 풀이 장, L01·L02 실측). 강의 섹션들이 가리키는 문항 중, 다른 강이 아직 안 쓴 것만.
    ★ 끄기: 목표서 curriculum.fill_with_examples=false. 돌려준 값 = 더 넣은 문항 수(0 이면 그대로).
    """
    if not job.get("curriculum.fill_with_examples", True) or not job.get("curriculum.video_examples", True):
        return 0
    out = job.dir / "curriculum.json"
    doc = read_json(out)
    L = next((x for x in (doc or {}).get("lectures", []) if x["id"] == lid), None)
    if not L:
        return 0
    c = job.get("curriculum", {})
    cps = float(c.get("chars_per_sec", 5.5))
    target = float(c.get("target_min", 35)) * 60
    md = job.manuscripts_dir / lid
    total, n = 0.0, len(L["sections"])
    for i, s in enumerate(L["sections"]):
        man = read_json(md / f"{s['id']}.json", {}) or {}
        if not man:
            return 0                                   # 아직 집필 전 — 잴 수 없다
        for g in man.get("groups") or []:
            for sl in g.get("slides") or []:
                total += chars(sl.get("say") or "") / cps + SLIDE_GAP
        for key, here in (("cover", i == 0), ("outro", i == n - 1)):
            cv = man.get(key) or {}
            if here and cv.get("say"):
                total += chars(cv["say"]) / cps + SLIDE_GAP
    short = target - total
    if short < 30:
        return 0
    rd = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rd) if rd and rd.exists() else {}
    if not rounds:
        return 0
    notes, _ = load_inputs(job)
    by_id = {s.id: s for nt in notes for s in nt.sections}
    secs = [by_id[s["id"]] for s in L["sections"] if s["id"] in by_id]
    used = {(e["round"], e["no"]) for X in doc["lectures"] for e in X.get("examples") or []}
    extra = fit_examples(secs, rounds, used, int(short // 30) + 1, short, cps)
    if not extra:
        warn(f"{lid} {short / 60:.1f}분 모자라지만 더 넣을 문항이 없습니다(이 강의 근거 문항을 다 씀)")
        return 0
    L["examples"] = (L.get("examples") or []) + extra
    p = L.setdefault("plan", {})
    p["examples_sec"] = round(sum(question_seconds(rounds[(e["round"], e["no"])], cps) for e in L["examples"]))
    p["filled"] = len(extra)
    write_json(out, doc)
    log(f"{lid} 원고 {total / 60:.1f}분 → {short / 60:.1f}분 모자라 기출 맛보기 {len(extra)}문항 추가(총 {len(L['examples'])})")
    return len(extra)


def build(job: Job) -> Dict[str, Any]:
    c = job.get("curriculum", {})
    cps = float(c.get("chars_per_sec", 5.5))
    target_sec = float(c.get("target_min", 35)) * 60
    fixed_sec = float(c.get("fixed_sec", 180))
    n_ex = examples_per_lecture(job)
    per_subject = {int(k): int(v) for k, v in (c.get("lectures_per_subject") or {}).items()}

    notes, scripts = load_inputs(job)
    # 영상 원고가 있으면 섹션별 기존 내레이션 분량(공백 제외)을 잰다 — 확장비의 실제 기준
    script_chars: Dict[str, int] = {}
    for sno, sn in scripts.items():
        nn = next((n for n in notes if n.subject_no == sno), None)
        if not nn:
            continue
        for ns in nn.sections:
            ss = next((x for x in sn.sections if re.sub(r"\s", "", x.title) == re.sub(r"\s", "", ns.title)), None)
            if ss:
                script_chars[ns.id] = sum(chars(x.say) for x in ss.subs)

    rounds_dir = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rounds_dir) if rounds_dir and rounds_dir.exists() else {}
    # ★ 예시(기출 맛보기)는 **고정 예산**이다(기본 14분). 문항이 아직 없거나 확정 전이어도 그 자리를
    #   비워 두고 개념 분량을 정한다 → 나중에 문항이 들어와도 개념 분량·원고가 흔들리지 않는다
    #   (`run.bat examples` 가 예시만 채운다). examples_per_lecture=0 이면 예산도 0(개념만).
    budget_sec = (float(c.get("examples_budget_min", 14)) * 60) if n_ex > 0 else 0.0
    if not rounds and budget_sec:
        warn(f"문항(_rounds)이 아직 없습니다 — 강마다 기출 맛보기 자리 {budget_sec / 60:.0f}분을 비워 두고 편성합니다"
             "(문항을 넣은 뒤 run.bat examples)")

    lectures: List[Dict[str, Any]] = []
    used: set = set()
    no = 0
    for note in notes:
        if not note.sections:
            warn(f"{note.file.name} 에 h2 섹션이 없습니다 — 편성에서 뺍니다(원천 탭에서 확인하십시오)")
            continue
        k = per_subject.get(note.subject_no) or max(1, round(sum(s.n_chars for s in note.sections) / 2000))
        for a, b in _partition([s.n_chars for s in note.sections], k):
            no += 1
            secs = note.sections[a:b]
            ex = fit_examples(secs, rounds, used, n_ex, budget_sec, cps)
            ex_sec = sum(question_seconds(rounds[(e["round"], e["no"])], cps) for e in ex)
            concept_sec = max(target_sec - fixed_sec - budget_sec, target_sec * 0.3)
            concept_chars = int(concept_sec * cps)
            note_chars = sum(s.n_chars for s in secs) or 1
            sc_chars = sum(script_chars.get(s.id, 0) for s in secs)
            lid = f"L{no:02d}"
            nums = [s.title.split(".", 1)[0] for s in secs]
            names = [s.title.split(".", 1)[-1].strip() for s in secs]
            lectures.append({
                "id": lid, "no": no,
                "subject_no": note.subject_no, "subject": note.subject,
                "title": " · ".join(names),
                "note_file": str(note.file),
                "sections": [{
                    "id": s.id, "title": s.title, "note_chars": s.n_chars,
                    "target_chars": int(concept_chars * s.n_chars / note_chars),
                    "subs": [{"id": x.id, "title": x.title} for x in s.subs],
                    "svgs": len(s.svgs),
                } for s in secs],
                "examples": ex,
                "plan": {
                    "target_sec": target_sec, "fixed_sec": fixed_sec,
                    "examples_sec": round(ex_sec), "examples_budget_sec": round(budget_sec),
                    "examples_pending": bool(budget_sec and not ex),
                    "concept_sec": round(concept_sec),
                    "concept_chars": concept_chars, "note_chars": note_chars,
                    "script_chars": sc_chars,
                    # 기준 = 영상 원고 내레이션(있으면) / 노트 본문(없으면)
                    "expand_ratio": round(concept_chars / (sc_chars or note_chars), 2),
                    "expand_base": "script" if sc_chars else "note",
                },
                "range": f"{nums[0]}~{nums[-1]}" if len(nums) > 1 else nums[0],
            })

    doc = {"job": job.name, "title": job.get("title"), "chars_per_sec": cps,
           "lectures": lectures}
    return doc


def run(job: Job, force: bool = False) -> Path:
    out = job.dir / "curriculum.json"
    if out.exists() and not force:
        log(f"커리큘럼이 이미 있습니다(사람이 고쳤을 수 있으니 덮지 않음): {out}  — 다시 만들려면 --force")
        return out
    doc = build(job)
    write_json(out, doc)
    tot = 0.0
    for L in doc["lectures"]:
        p = L["plan"]
        tot += p["target_sec"]
        flag = "  ⚠ 확장비 높음" if p["expand_ratio"] > 3.5 else ""
        base = f"원고 {p['script_chars']:>5}자" if p.get("expand_base") == "script" else f"노트 {p['note_chars']:>5}자"
        log(f"{L['id']} {L['subject_no']}과목 섹션 {L['range']:>6} | {base} → 개념 "
            f"{p['concept_chars']:>5}자 (×{p['expand_ratio']}) + 예시 {len(L['examples'])}문항 "
            f"{p['examples_sec'] // 60}분 | {L['title'][:40]}{flag}")
    log(f"총 {len(doc['lectures'])}강 · 약 {tot / 3600:.1f}시간 → {out}")
    return out
