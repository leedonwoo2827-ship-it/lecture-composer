# -*- coding: utf-8 -*-
"""S0a 설문 만들기 — **질문을 고정하지 않는다.**

물어볼 것은 프로젝트마다 다르다. 결제가 뼈대만 있는 레포에는 "결제를 넣을까요"
를 물어야 하고, 릴레이가 임시 구조면 "이관 계획을 말할까요" 를 물어야 한다.
고정 질문 넷을 돌려 쓰면 이 단계를 만든 의미가 없다.

    ① 좌표 입력  →  S1 프레임 · S2 레포 (결정론 · 공짜)
                     ↓
    ② **여기** — 레포를 읽고 이 프로젝트에 맞는 질문을 만든다. 추천까지 붙인다
                     ↓
    ③ 사람이 답함  →  S0 기획서  →  S2b 구조 …

★ 질문마다 **추천 하나와 그 이유**를 붙인다. 답을 강요하는 게 아니라, 레포를 읽은
  쪽이 먼저 의견을 내는 것이다 — 빈 화면에서 고르라고 하면 아무도 못 고른다.
  이유는 레포에서 가져온다("커밋 40건 중 마지막 하루가 전부 안정화라 아직 베타다").

★ 네 키(`audience` `goal` `target_min` `slide_tone`)는 **이름을 고정**한다.
  뒤 단계가 이름으로 읽기 때문이다. 나머지는 모델이 자유롭게 짓는다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import config, refs as refs_mod, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

MD = re.compile(r"[*_`#>]|^\s*[-•]\s+", re.M)
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")

# 뒤 단계가 이름으로 읽는 키 — 모델이 지어내면 안 된다
FIXED = {"audience", "goal", "target_min", "slide_tone"}
TONES = {"pitch", "bullet", "explain"}
MINUTES = {"10", "15", "20", "30", "40", "60", "90", "120"}

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "hint": {"type": "string"},
                    "why": {"type": "string"},
                    "recommended": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"value": {"type": "string"},
                                           "label": {"type": "string"},
                                           "effect": {"type": "string"}},
                            "required": ["value", "label", "effect"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["key", "label", "options", "recommended", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def plain(t: Any) -> str:
    return MD.sub("", str(t or "")).strip()


def build_brief(project: Dict[str, Any], repo: Dict[str, Any],
                frames: Dict[str, Any], root: Path | None = None) -> str:
    L: List[str] = [f"# 프로젝트\n{project.get('title')}"]
    for u in (project.get("urls") or []):
        L.append(f"{u.get('label') or '사이트'}: {u.get('url')}")
    if not project.get("urls") and project.get("live_url"):
        L.append(f"라이브: {project['live_url']}")

    if repo and not repo.get("skipped"):
        # ★ 레포가 여럿이면 각각을 보여 준다 — 한 발표에 레포 셋이 실제로 있다.
        #   "어느 레포가 주인공인가" 는 코드가 답할 수 없는 질문이라 물어야 한다.
        rs = repo.get("repos") or []
        if len(rs) > 1:
            L.append(f"\n# 레포 {len(rs)}개 — 한 발표에 여러 레포가 엮여 있다")
            for r in rs:
                live = r.get("live_url") or "(사이트 없음)"
                L.append(f"- {r['name_with_owner']} · 파일 {r['file_count']}개 "
                         f"· 커밋 {r['commit_count']}건 · {live}")
            L.append("어느 레포가 주인공인지, 셋을 어떻게 엮어 말할지도 물어볼 만하다.")
        else:
            L.append(f"\n# 레포\n{repo.get('name_with_owner')} "
                     f"· 커밋 {repo.get('commit_count')}건")
        for x in (repo.get("extra_sites") or []):
            L.append(f"같이 도는 사이트: {x['url']}"
                     + (f" ({x['label']})" if x.get("label") else "")
                     + " — 레포는 위 중 하나에 들어 있다")
        L.append(f"스택: {', '.join(repo.get('stack') or []) or '미상'}")
        L.append("\n## README\n" + (repo.get("readme") or "(없음)")[:4000])
        L.append("\n## 최근 커밋 — 여기에 '아직 미완성인 것' 이 드러난다")
        for c in (repo.get("commits") or [])[:30]:
            L.append(f"- {c['short_sha']} {c['date'][:10]} {c['subject']}")
        tree = repo.get("tree") or []
        L.append(f"\n## 파일 트리 ({len(tree)}개 중 주요)")
        for t in sorted(sorted(tree, key=lambda t: -t["bytes"])[:100],
                        key=lambda t: t["path"]):
            L.append(f"- {t['path']}")
    else:
        L.append("\n# 레포\n(없음 — 영상만으로 발표를 만든다)")

    L.append("\n# 이미 가지고 있는 화면 녹화")
    fitems = (frames or {}).get("items", {})
    if not project.get("items"):
        L.append("(없음 — 아직 화면 녹화가 없다. 그림이나 캡처로 가야 한다. "
                 "무엇을 찍어 올지도 물어볼 만하다.)")
    for it in project.get("items", []):
        if not it.get("include", True):
            continue
        f = fitems.get(it["id"], {})
        dur = f.get("duration_sec")
        L.append(f"- {it['id']} · {it.get('title')}" + (f" · {dur:.0f}초" if dur else ""))

    if root is not None:
        L += refs_mod.brief_block(project.get("refs") or {}, root, budget=8000)

    L.append("\n# 요구")
    L.append("이 레포를 만든 사람에게 물어볼 것을 3~6개 정해라.")
    L.append("코드를 읽으면 알 수 있는 것은 묻지 마라 — 코드 밖에 있는 것만 물어라.")
    L.append("질문마다 추천 하나와 그 이유(레포 근거)를 붙여라. JSON 만 출력.")
    return "\n".join(L)


def normalize(raw: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    """**거부하지 않고 수리한다.** 설문이 안 나오면 시작 화면이 막힌다."""
    warn: List[str] = []
    out: List[Dict[str, Any]] = []
    seen = set()

    for q in (raw.get("questions") or [])[:8]:
        key = str(q.get("key") or "").strip().lower()
        if not KEY_RE.match(key) or key in seen:
            warn.append(f"이상한 키 {key!r} → 버림")
            continue
        opts = []
        for o in (q.get("options") or [])[:6]:
            v, lb = str(o.get("value") or "").strip(), plain(o.get("label"))
            if not v or not lb:
                continue
            # 고정 키는 값 집합이 정해져 있다 — 뒤 단계가 그걸 믿는다
            if key == "slide_tone" and v not in TONES:
                warn.append(f"slide_tone 보기 {v!r} → 버림")
                continue
            if key == "target_min":
                v = re.sub(r"\D", "", v)
                if v not in MINUTES:
                    warn.append(f"target_min 보기 {o.get('value')!r} → 버림")
                    continue
            # ★ 고르면 어떻게 되는지. 이게 있어야 결과를 보고 고른다.
            opts.append({"value": v, "label": lb, "effect": plain(o.get("effect"))})
        if len(opts) < 2:
            warn.append(f"{key}: 보기가 모자라 버림")
            continue

        rec = str(q.get("recommended") or "").strip()
        if key == "target_min":
            rec = re.sub(r"\D", "", rec)
        if rec not in {o["value"] for o in opts}:
            warn.append(f"{key}: 추천 {rec!r} 이 보기에 없다 → 첫 보기로")
            rec = opts[0]["value"]

        seen.add(key)
        out.append({"key": key, "label": plain(q.get("label")) or key,
                    "hint": plain(q.get("hint")), "why": plain(q.get("why")),
                    "options": opts, "recommended": rec,
                    "fixed": key in FIXED})

    missing = FIXED - seen
    if missing:
        warn.append(f"고정 질문이 빠졌다: {sorted(missing)}")
    if not out:
        warn.append("질문이 하나도 안 나왔다")
    return out, warn


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s0a-ask"]

    repo = cached_data(pid, slug, "s2-repo") or {}
    frames = cached_data(pid, slug, "s1-frames") or {}

    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "ask.md").read_text(encoding="utf-8")
    job.progress(0, 1, "물어볼 것 정하기")

    clone = (repo or {}).get("clone_dir")
    p = ClaudeProvider(
        model=(project.get("models") or cfg["models"]).get("caption")
              or cfg["models"]["caption"],
        effort=cfg["effort"].get("caption", "medium"),
        cwd=clone,
        allowed_tools=["Read", "Grep", "Glob"] if clone else [],
        max_turns=int(cfg.get("ask_turns", 14)) if clone else 1,
        budget_usd=cfg["budget_usd"]["per_stage"],
        # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
        on_activity=lambda s: job.progress(0, 1, s),
    )
    raw = p.structured(system,
                       [{"role": "user",
                         "content": build_brief(project, repo, frames,
                                                ws.project_dir(pid, slug))}],
                       schema=SCHEMA)
    job.progress(1, 1, "정리")

    qs, warn = normalize(raw)
    for w in warn:
        job.add_log("수리: " + w)
    job.add_log(f"질문 {len(qs)}개 · ${p.last_cost_usd:.3f}")
    for q in qs:
        rec = next((o["label"] for o in q["options"] if o["value"] == q["recommended"]), "")
        job.add_log(f"  {q['label']}  → 추천: {rec}")

    return write_cache(pid, slug, "s0a-ask",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"questions": qs}, code_version=stage.code_version,
                       model=p.model, cost_usd=p.last_cost_usd,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s0a-ask"].run = run
