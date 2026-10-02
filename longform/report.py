"""강별 진행 상황 — CLI(status)와 웹앱이 같이 쓴다."""
from __future__ import annotations

from typing import Any, Dict, List

from longform.config import Job
from longform.state import State
from longform.util import read_json


def rows(job: Job) -> List[Dict[str, Any]]:
    cur = read_json(job.dir / "curriculum.json")
    if not cur:
        return []
    st = State(job)
    from longform import team
    claims = team.all_claims(job)
    out = []
    for L in cur["lectures"]:
        lid = L["id"]
        lec = st.lec(lid)
        n = len(L["sections"])
        d = job.out_dir / lid
        meta = read_json(job.meta_dir / f"{lid}.json", {}) or {}
        out.append({
            "id": lid, "no": L["no"], "subject_no": L["subject_no"], "subject": L["subject"],
            "title": L["title"], "sections": [s["id"] for s in L["sections"]], "n": n,
            "plan": L.get("plan", {}), "examples": len(L.get("examples") or []),
            "compose": sum(1 for s in L["sections"] if f"s2:{s['id']}" in lec),
            "render": sum(1 for s in L["sections"] if f"s3:{s['id']}" in lec),
            "stitch_sec": (lec.get("s4") or {}).get("sec"),
            "video": f"{lid}/{lid}.mp4" if (d / f"{lid}.mp4").exists() else "",
            "meta": bool(meta), "yt_title": meta.get("title", ""),
            "thumb": f"meta/{lid}.thumb.png" if (job.meta_dir / f"{lid}.thumb.png").exists() else "",
            "yt": (lec.get("yt") or {}).get("id", "") or ((claims.get(lid) or {}).get("yt") or {}).get("id", ""),
            "who": (claims.get(lid) or {}).get("who", ""),
            "team_status": (claims.get(lid) or {}).get("status", ""),
        })
    return out


def print_table(job: Job) -> None:
    rs = rows(job)
    if not rs:
        print("curriculum.json 없음 — plan 부터")
        return
    print(f"{'강':4} {'과목':3} {'원고':>7} {'렌더':>7} {'완성':>8} {'업로드':>13}  제목")
    for r in rs:
        s4 = r["stitch_sec"]
        print(f"{r['id']:4} {r['subject_no']:>3} {r['compose']:>3}/{r['n']:<3} {r['render']:>3}/{r['n']:<3} "
              f"{(str(round(s4 / 60, 1)) + '분') if s4 else '-':>8} {r['yt'] or '-':>13}  {r['title'][:40]}")
