"""propose / decide — 강 수를 **대화로** 정하기 위한 재료와 기록.

    run.bat propose --job <잡>             후보표(강 수·배분·길이별 확장비) → jobs/<잡>/proposals.json
    run.bat decide  --job <잡> --per 3,7 --target 35 --note "시험 배점에 맞춤"
                                           → 목표서에 적고, brief.md 결정 기록에 남기고, 편성(plan)을 새로 한다

★ 강 수는 정답이 없는 결정이다. 그래서 코드는 **후보와 근거(분량·배점·확장비)** 까지만 내고,
  고르는 것은 사람(+ Claude Code 와의 대화)이 한다. 결정과 이유는 brief.md 에 남는다.

확장비 = 목표 개념 분량 ÷ 기존 내레이션(영상 원고가 없으면 노트 본문)
    1.0~1.4  가장 좋다 — 검수된 내레이션을 살리며 조금만 늘린다
    < 0.9    기존이 목표보다 길다 — 줄여야 하거나 강이 길어진다
    > 2.0    지어내는 부분이 커진다(영상 원고 없이 노트만이면 흔하다)
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.notes import chars, load_inputs
from longform.s1_curriculum import build, load_rounds
from longform.util import log, write_json

CPS_DEFAULT = 5.5


def _weights(job: Job) -> Dict[str, Any]:
    """과목별 내용 분량(분)과 출제 비중(회차당 문항 수)."""
    notes, scripts = load_inputs(job)
    cps = float(job.get("curriculum.chars_per_sec", CPS_DEFAULT))
    subj: Dict[int, Dict[str, Any]] = {}
    for n in notes:
        if not n.sections:
            continue
        sc = scripts.get(n.subject_no)
        say = sum(chars(x.say) for s in sc.sections for x in s.subs) if sc else 0
        subj[n.subject_no] = {"subject": n.subject, "sections": len(n.sections),
                              "note_chars": sum(s.n_chars for s in n.sections),
                              "script_min": round(say / cps / 60, 1) if say else 0}
    rd = job.path(job.get("inputs.rounds_dir"))
    rounds = load_rounds(rd) if rd and rd.exists() else {}
    n_rounds = len({r for r, _ in rounds}) or 0
    for (_, _), q in rounds.items():
        sn = int(q.get("subject_no") or 0)
        if sn in subj:
            subj[sn]["questions"] = subj[sn].get("questions", 0) + 1
    for s in subj.values():
        s["q_per_round"] = round(s.get("questions", 0) / n_rounds, 1) if n_rounds else 0
    return {"subjects": subj, "rounds": n_rounds, "has_script": any(s["script_min"] for s in subj.values())}


def _alloc(total: int, w: Dict[int, float]) -> Dict[int, int]:
    """최대 나머지 방식 — 과목마다 최소 1강."""
    keys = sorted(w)
    s = sum(w.values()) or 1
    raw = {k: total * w[k] / s for k in keys}
    out = {k: max(1, int(raw[k])) for k in keys}
    while sum(out.values()) < total:
        k = max(keys, key=lambda k: raw[k] - out[k])
        out[k] += 1
    while sum(out.values()) > total:
        k = max((k for k in keys if out[k] > 1), key=lambda k: out[k] - raw[k])
        out[k] -= 1
    return out


def _trial(job: Job, per: Dict[int, int], target: int) -> Dict[str, Any]:
    j = copy.copy(job)
    j.cfg = copy.deepcopy(job.cfg)
    j.cfg.setdefault("curriculum", {})["lectures_per_subject"] = {str(k): v for k, v in per.items()}
    j.cfg["curriculum"]["target_min"] = target
    import longform.util as U
    saved, U.warn = U.warn, (lambda *a, **k: None)
    import longform.s1_curriculum as S1
    saved1, S1.warn = S1.warn, (lambda *a, **k: None)
    try:
        doc = build(j)
    finally:
        U.warn, S1.warn = saved, saved1
    r = [L["plan"]["expand_ratio"] for L in doc["lectures"]]
    ex = [L["plan"]["examples_sec"] / 60 for L in doc["lectures"]]
    return {"per": per, "target_min": target, "lectures": len(r), "hours": round(len(r) * target / 60, 1),
            "ratio_min": round(min(r), 2), "ratio_avg": round(sum(r) / len(r), 2), "ratio_max": round(max(r), 2),
            "over2": sum(1 for x in r if x > 2.0), "under09": sum(1 for x in r if x < 0.9),
            "examples_min": round(sum(ex) / len(ex)),
            "titles": [f"{L['id']} {L['subject_no']}과목 {L['title'][:30]} ×{L['plan']['expand_ratio']}" for L in doc["lectures"]]}


def _score(t: Dict[str, Any]) -> float:
    """작을수록 좋다 — 평균이 1.2 에 가깝고, 범위가 좁고, 2배 초과·0.9 미만이 적을 것."""
    return (abs(t["ratio_avg"] - 1.2) + (t["ratio_max"] - t["ratio_min"]) * 0.5
            + t["over2"] * 0.6 + t["under09"] * 0.25)


def propose(job: Job, targets: Optional[List[int]] = None, top: int = 6) -> Dict[str, Any]:
    w = _weights(job)
    subj = w["subjects"]
    if not subj:
        raise SystemExit("[error] 요약노트가 없습니다 — 원천(파일 넣기)부터")
    targets = targets or [30, 35, 40]
    content = {k: (v["script_min"] or v["note_chars"] / CPS_DEFAULT / 60 * 2.5) for k, v in subj.items()}
    exam = {k: v.get("q_per_round") or 0 for k, v in subj.items()}
    total_content_min = sum(content.values())
    cands: List[Dict[str, Any]] = []
    seen = set()
    for t in targets:
        concept_min = max(t - 15, t * 0.5)                  # 예시·오프닝을 뺀 개념 몫(대략)
        mid = max(len(subj), round(total_content_min * 1.2 / concept_min))
        for total in range(max(len(subj), mid - 3), mid + 4):
            for basis, wt in (("내용 비례", content), ("출제 비례", exam)):
                if not any(wt.values()):
                    continue
                per = _alloc(total, wt)
                key = (tuple(sorted(per.items())), t)
                if key in seen:
                    continue
                seen.add(key)
                tr = _trial(job, per, t)
                tr["basis"] = basis
                tr["score"] = round(_score(tr), 3)
                cands.append(tr)
    cands.sort(key=lambda c: c["score"])
    doc = {"job": job.name, "at": time.strftime("%Y-%m-%d %H:%M"), "weights": w,
           "candidates": cands[:top], "current": {
               "per": job.get("curriculum.lectures_per_subject") or {},
               "target_min": job.get("curriculum.target_min")}}
    write_json(job.dir / "proposals.json", doc)
    return doc


def print_proposals(doc: Dict[str, Any]) -> None:
    w = doc["weights"]
    print(f"\n원천 — 문항 {w['rounds']}회차 · 영상 원고 {'있음' if w['has_script'] else '없음(노트 기준)'}")
    for k, v in sorted(w["subjects"].items()):
        print(f"  {k}과목 {v['subject'][:24]:24} 섹션 {v['sections']:>2} · 기존 내레이션 {v['script_min']:>5}분 · "
              f"노트 {v['note_chars']:>6,}자 · 회차당 {v['q_per_round']}문항")
    print("\n후보 (좋은 순)  — 확장비 1.0~1.4 가 가장 좋음, <0.9 는 줄여야 함, >2.0 은 지어낼 몫이 큼")
    for i, c in enumerate(doc["candidates"], 1):
        per = "+".join(str(c["per"][k]) for k in sorted(c["per"]))
        print(f"  {i}) {per:>9} = {c['lectures']:>2}강 × {c['target_min']}분 = {c['hours']:>4}시간 [{c['basis']}] | "
              f"확장비 {c['ratio_min']}~{c['ratio_max']} (평균 {c['ratio_avg']}) · 2배 초과 {c['over2']} · 0.9 미만 {c['under09']} · 예시 {c['examples_min']}분")
    if doc["candidates"]:
        c = doc["candidates"][0]
        per = ",".join(str(c["per"][k]) for k in sorted(c["per"]))
        print(f"\n정하려면(예: 1번): run.bat decide --job {doc['job']} --per {per} --target {c['target_min']} --note \"이유\"")


def decide(job: Job, per_csv: str, target: Optional[int], note: str) -> None:
    w = _weights(job)
    keys = sorted(w["subjects"])
    vals = [int(x) for x in per_csv.replace("+", ",").split(",") if x.strip()]
    if len(vals) != len(keys):
        raise SystemExit(f"[error] 과목이 {len(keys)}개입니다({keys}) — --per 에 {len(keys)}개 숫자를 주십시오")
    per = dict(zip(keys, vals))
    f = job.dir / "job.json"
    cfg = json.loads(f.read_text(encoding="utf-8"))
    cur = cfg.setdefault("curriculum", {})
    old = (cur.get("lectures_per_subject"), cur.get("target_min"))
    cur["lectures_per_subject"] = {str(k): v for k, v in per.items()}
    if target:
        cur["target_min"] = int(target)
    f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    job.cfg.setdefault("curriculum", {}).update(cur)
    tr = _trial(job, per, int(cur.get("target_min") or 35))
    brief = job.dir / "brief.md"
    if not brief.exists():
        brief.write_text(f"# {job.get('title') or job.name} — 기획 메모\n\n"
                         "대화(Claude Code)와 화면에서 정한 것을 이유와 함께 남긴다. 위가 오래된 것, 아래가 새 것.\n\n",
                         encoding="utf-8")
    with brief.open("a", encoding="utf-8") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M')} — 강 수 결정\n"
                 f"- 배분: {' + '.join(f'{k}과목 {v}강' for k, v in per.items())} = **{tr['lectures']}강 × {tr['target_min']}분"
                 f" (약 {tr['hours']}시간)**\n"
                 f"- 확장비 {tr['ratio_min']}~{tr['ratio_max']} (평균 {tr['ratio_avg']}), 2배 초과 {tr['over2']}강, 0.9 미만 {tr['under09']}강\n"
                 f"- 이전: {old[0] or '자동'} × {old[1]}분\n"
                 f"- 이유: {note or '(적지 않음)'}\n\n")
    log(f"정했습니다 — {tr['lectures']}강 × {tr['target_min']}분 · 확장비 평균 {tr['ratio_avg']} → 목표서·brief.md")
    from longform import s1_curriculum
    s1_curriculum.run(job, force=True)
