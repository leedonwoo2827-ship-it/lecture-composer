"""음성 체크 — 렌더된 강을 장마다 **귀로 듣고** 발음(TTS 입력)을 고친다.

    고친 발음   jobs/<잡>/voice/<Lxx>.json   {키: {"read": "...", "checked": true}}
                키 = 장의 data_id(L01-s1-01-003) · 표지 = "<섹션>:cover" · 맺음 = "<섹션>:outro"
    발음 사전   jobs/<잡>/voice/dict.json    [{"from": "CPU", "to": "씨피유"}, …] — 모든 강의 발음에 적용

흐름  화면에서 고침 → 「발음대로 다시 합성」(그 장만, 엔진 s10_tts.synth_one — 바로 다시 들어 봄)
      → 「음성 고친 판 굽기」(make --only Lxx). 렌더(s3)는 effective_read 를 덮어쓰기 narration 에 싣고,
        고친 것이 있는 섹션만 해시가 바뀌어 다시 굽는다(고친 것이 없으면 해시·화면 그대로).
★ 자막(say)은 바꾸지 않는다 — 화면에 보이는 원문은 원고(manuscripts/)가 원본이다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from longform.config import Job
from longform.state import State, sha
from longform.util import read_json, write_json


def _dir(job: Job):
    return job.dir / "voice"


def load_overlay(job: Job, lid: str) -> Dict[str, Dict[str, Any]]:
    return read_json(_dir(job) / f"{lid}.json", {}) or {}


def save_overlay(job: Job, lid: str, key: str, read: Optional[str] = None, checked: Optional[bool] = None) -> None:
    ov = load_overlay(job, lid)
    one = ov.setdefault(key, {})
    if read is not None:
        one["read"] = read
    if checked is not None:
        one["checked"] = bool(checked)
    write_json(_dir(job) / f"{lid}.json", ov)


def load_dict(job: Job) -> List[Dict[str, str]]:
    return [d for d in (read_json(_dir(job) / "dict.json", []) or []) if (d.get("from") or "").strip()]


def save_dict(job: Job, rows: List[Dict[str, str]]) -> None:
    rows = [{"from": r["from"].strip(), "to": (r.get("to") or "").strip()} for r in rows if (r.get("from") or "").strip()]
    write_json(_dir(job) / "dict.json", rows)


def apply_dict(text: str, rows: List[Dict[str, str]]) -> str:
    # 긴 말부터 바꾼다(「SQL」보다 「MySQL」이 먼저). 영문은 낱말 경계로만 — 「CPU」가 「CPUs」 안을 깨지 않게
    for r in sorted(rows, key=lambda r: -len(r["from"])):
        f = r["from"]
        if re.fullmatch(r"[A-Za-z0-9_.+-]+", f):
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(f)}(?![A-Za-z0-9])", r["to"], text)
        else:
            text = text.replace(f, r["to"])
    return text


def effective_read(job: Job, lid: str, key: str, say: str, read: str,
                   ov: Optional[Dict[str, Any]] = None, rows: Optional[List[Dict[str, str]]] = None) -> str:
    """실제로 TTS 에 넣을 글 — 손으로 고친 것(있으면) 위에 발음 사전."""
    ov = load_overlay(job, lid) if ov is None else ov
    rows = load_dict(job) if rows is None else rows
    mine = (ov.get(key) or {}).get("read")
    base = mine if mine is not None and mine.strip() else (read or say or "")
    return apply_dict(base, rows) if rows else base


def render_read(job: Job, lid: str, key: str, say: str, read: str,
                ov: Optional[Dict[str, Any]] = None, rows: Optional[List[Dict[str, str]]] = None) -> str:
    """렌더가 덮어쓰기에 싣는 발음 — 고친 것이 없으면 **원고 그대로**(빈 발음은 비워 둬 엔진이 자막에서 만든다)."""
    r1 = effective_read(job, lid, key, say, read, ov, rows)
    return r1 if r1 != (read or say) else read


def section_sig(job: Job, lid: str, man: Dict[str, Any], sid: str) -> Optional[str]:
    """이 섹션의 발음이 원고와 달라졌으면 그 해시(렌더 해시에 넣는다), 같으면 None — 화면·해시 그대로."""
    ov, rows = load_overlay(job, lid), load_dict(job)
    if not ov and not rows:
        return None
    diff = []
    items = [(f"{sid}:cover", man.get("cover") or {}), (f"{sid}:outro", man.get("outro") or {})]
    items += [(s["id"], s) for g in man.get("groups", []) for s in g.get("slides", [])]
    for key, s in items:
        if not s.get("say"):
            continue
        r0 = s.get("read", "") or ""
        r1 = effective_read(job, lid, key, s["say"], r0, ov, rows)
        if r1 != (r0 or s["say"]):
            diff.append((key, r1))
    return sha(*[f"{k}={v}" for k, v in diff]) if diff else None


def rows(job: Job, lid: str) -> Dict[str, Any]:
    """강 하나의 장 목록 — 렌더된 섹션(parts/<섹션>.timing.json)만. 장 순서는 영상 순서."""
    cur = read_json(job.dir / "curriculum.json", {}) or {}
    L = next((x for x in cur.get("lectures", []) if x["id"] == lid), None)
    if not L:
        raise ValueError(f"강이 없습니다: {lid}")
    ov, dic = load_overlay(job, lid), load_dict(job)
    state = State(job)
    out: List[Dict[str, Any]] = []
    for si, sm in enumerate(L["sections"]):
        sid = sm["id"]
        man = read_json(job.manuscripts_dir / lid / f"{sid}.json", {}) or {}
        tm = read_json(job.out_dir / lid / "parts" / f"{sid}.timing.json", {}) or {}
        pid = (state.get(lid, f"s3:{sid}") or {}).get("pid")
        by_id = {s["id"]: s for g in man.get("groups", []) for s in g.get("slides", [])}
        tl = tm.get("slides") or []
        for i, t in enumerate(tl):
            did = t.get("data_id") or ""
            if did:
                key, src = did, by_id.get(did) or {}
            elif i == 0 and si == 0:
                key, src = f"{sid}:cover", man.get("cover") or {}
            elif i == len(tl) - 1 and si == len(L["sections"]) - 1:
                key, src = f"{sid}:outro", man.get("outro") or {}
            else:
                continue
            say = src.get("say") or ""
            if not say:
                continue
            mine = ov.get(key) or {}
            out.append({"key": key, "sid": sid, "no": t["no"], "pid": pid, "title": t.get("title") or "",
                        "say": say, "read_orig": src.get("read") or "",
                        "read": effective_read(job, lid, key, say, src.get("read") or "", ov, dic),
                        "edited": bool((mine.get("read") or "").strip()), "checked": bool(mine.get("checked")),
                        "sec": t.get("audio_sec") or 0, "project": tm.get("project") or ""})
    return {"lecture": lid, "title": L["title"], "rows": out,
            "checked": sum(1 for r in out if r["checked"]), "total": len(out)}


AI_PROMPT = """너는 한국어 TTS(음성 합성) 발음 교정기다. 아래 [자막]을 TTS 가 **소리 나는 대로** 읽을 글로 바꿔라.
규칙:
- 영문 약어·용어는 한국어 발음으로(CPU→씨피유, SSD→에스에스디, Excel→엑셀, VLOOKUP→브이룩업, SUM→썸).
- 숫자·기호는 문맥에 맞게 읽는 대로(2급→이 급, 1과목→일 과목, 3개→세 개, 50%→오십 퍼센트, A1→에이 일, =→이퀄).
- 함수식·셀 주소는 강사가 말하듯 풀어 읽는다($A$1→달러 에이 달러 일).
- 그 밖의 글자·어순·문장부호는 바꾸지 마라. 설명·따옴표 없이 바꾼 글 한 덩어리만 출력하라.
{hint}
[자막]
{say}"""


def ai_read(job: Job, say: str, current: str = "") -> str:
    from longform.s2_manuscript import call_llm
    hint = f"(지금 발음 칸: {current} — 이상한 곳만 고쳐라)" if current.strip() else ""
    out = call_llm(job, AI_PROMPT.format(say=say, hint=hint)).strip()
    return out.strip("`\"' \n")
