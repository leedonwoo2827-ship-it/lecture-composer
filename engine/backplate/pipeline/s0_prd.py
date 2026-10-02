# -*- coding: utf-8 -*-
"""S0 기획서(PRD) — **파이프라인의 맨 앞. 양방향이다.**

    없을 때   레포·영상·라이브를 읽고 **PRD 를 만들어 준다**   ← 지금
    있을 때   사람이 써 온 PRD 를 **그대로 읽어 쓴다**         ← 익숙해진 뒤

이 단계가 필요한 이유는 뒤가 앞을 못 지어내기 때문이다. S2b 는 "무엇을 몇 장으로"
를 정하는데, 그 판단의 재료 — 누구에게 보여 주는가, 무엇을 팔려는가, 어떤 부가자료를
준비해야 하는가 — 는 레포에 안 적혀 있다. 그래서 **한 번 문서로 세워 두고** 거기서
아래로 내려간다.

    09_기획/prd.md          ← 사람이 읽고 고치는 문서. **여기가 원본이다.**
    09_기획/prd.json        ← 구조화본. S2b 가 읽는다.

`prd.md` 를 사람이 고쳐 두면 다음 실행 때 **그 파일이 이긴다.** 그래서 "PRD 를
작업해 와서 넣는" 흐름이 코드 변경 없이 성립한다. 파일 하나가 접점이다.

★ 부가자료 예상 목록(`assets_needed`)이 이 단계의 실질적 산출물이다. 화면 캡처가
  몇 장 필요한지, 어떤 그림을 그려 와야 하는지를 **미리** 알아야 준비할 수 있다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from core import config, refs as refs_mod, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

MD = re.compile(r"[*_`#>]|^\s*[-•]\s+", re.M)

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "one_liner": {"type": "string"},
        "audience": {"type": "string"},
        "goal": {"type": "string"},
        "target_min": {"type": "integer"},
        "key_messages": {"type": "array", "items": {"type": "string"}},
        "proof_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"},
                               "evidence": {"type": "string"}},
                "required": ["claim", "evidence"],
                "additionalProperties": False,
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"},
                               "why": {"type": "string"},
                               "slides": {"type": "integer"}},
                "required": ["title", "why", "slides"],
                "additionalProperties": False,
            },
        },
        "assets_needed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["screenshot", "diagram", "video", "data"]},
                    "what": {"type": "string"},
                    "why": {"type": "string"},
                    "have": {"type": "boolean"},
                },
                "required": ["kind", "what", "why", "have"],
                "additionalProperties": False,
            },
        },
        "not_covering": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["one_liner", "audience", "goal", "target_min",
                 "key_messages", "sections", "assets_needed"],
    "additionalProperties": False,
}

KIND_LABEL = {"screenshot": "화면 캡처", "diagram": "그림·도식",
              "video": "화면 녹화", "data": "수치·로그"}


def plain(t: Any) -> str:
    return MD.sub("", str(t or "")).strip()


def to_md(d: Dict[str, Any], title: str) -> str:
    """사람이 읽고 고치는 원본. **이 파일이 다음 실행에서 이긴다.**"""
    L: List[str] = [f"# {title} — 발표 기획서", ""]
    L.append(f"> {d.get('one_liner', '')}")
    L.append("")
    L.append(f"- 보는 사람: {d.get('audience', '')}")
    L.append(f"- 이 발표의 목표: {d.get('goal', '')}")
    L.append(f"- 목표 길이: {d.get('target_min', 0)}분")
    L.append("")
    L.append("## 핵심 메시지")
    for m in d.get("key_messages") or []:
        L.append(f"- {m}")
    if d.get("proof_points"):
        L.append("")
        L.append("## 근거")
        L.append("")
        L.append("| 주장 | 근거 |")
        L.append("|---|---|")
        for p in d["proof_points"]:
            L.append(f"| {p.get('claim')} | {p.get('evidence')} |")
    L.append("")
    L.append("## 구성")
    L.append("")
    L.append("| 섹션 | 장수 | 왜 필요한가 |")
    L.append("|---|---:|---|")
    for s in d.get("sections") or []:
        L.append(f"| {s.get('title')} | {s.get('slides')} | {s.get('why')} |")
    L.append("")
    L.append("## 준비해야 할 자료")
    L.append("")
    L.append("여기 `없음` 인 것을 먼저 만들어 두면 뒤가 막히지 않습니다.")
    L.append("")
    L.append("| 종류 | 무엇 | 왜 | 있나 |")
    L.append("|---|---|---|---|")
    for a in d.get("assets_needed") or []:
        L.append(f"| {KIND_LABEL.get(a.get('kind'), a.get('kind'))} | {a.get('what')} "
                 f"| {a.get('why')} | {'있음' if a.get('have') else '**없음**'} |")
    if d.get("not_covering"):
        L.append("")
        L.append("## 이번에 다루지 않는 것")
        for x in d["not_covering"]:
            L.append(f"- {x}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("이 파일을 고치면 다음 실행에서 **고친 내용이 이깁니다.**")
    L.append("직접 쓴 기획서로 갈아 끼우려면 이 파일을 통째로 바꿔 두세요.")
    return "\n".join(L)


def build_brief(project: Dict[str, Any], repo: Dict[str, Any],
                frames: Dict[str, Any], root: Path | None = None) -> str:
    L: List[str] = [f"# 프로젝트\n{project.get('title')}"]
    for u in (project.get("urls") or []):
        L.append(f"{u.get('label') or '사이트'}: {u.get('url')}")
    if not project.get("urls") and project.get("live_url"):
        L.append(f"라이브: {project['live_url']}")
    if repo and not repo.get("skipped"):
        L.append(f"\n# 레포\n{repo.get('name_with_owner')} · 커밋 {repo.get('commit_count')}건")
        for x in (repo.get("extra_sites") or []):
            L.append(f"같이 도는 사이트: {x['url']}"
                     + (f" ({x['label']})" if x.get("label") else "")
                     + " — 레포는 위 중 하나에 들어 있다")
        L.append(f"스택: {', '.join(repo.get('stack') or []) or '미상'}")
        L.append("\n## README\n" + (repo.get("readme") or "(없음)")[:5000])
        L.append("\n## 최근 커밋")
        for c in (repo.get("commits") or [])[:30]:
            L.append(f"- {c['short_sha']} {c['subject']}")
        tree = repo.get("tree") or []
        L.append(f"\n## 파일 트리 ({len(tree)}개 중 주요)")
        for t in sorted(sorted(tree, key=lambda t: -t["bytes"])[:120],
                        key=lambda t: t["path"]):
            L.append(f"- {t['path']}")
    L.append("\n# 이미 가지고 있는 화면 녹화")
    fitems = (frames or {}).get("items", {})
    for it in project.get("items", []):
        if not it.get("include", True):
            continue
        f = fitems.get(it["id"], {})
        dur = f.get("duration_sec")
        L.append(f"- {it['id']} · {it.get('title')}" + (f" · {dur:.0f}초" if dur else ""))
    if root is not None:
        L += refs_mod.brief_block(project.get("refs") or {}, root, budget=10000)
    L.append("\nJSON 만 출력.")
    return "\n".join(L)


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s0-prd"]
    d = ws.step_dir(pid, slug, "prd")
    md_path = d / "prd.md"

    # ★ 사람이 써 둔 PRD 가 있으면 그것이 이긴다. 코드 변경 없이 갈아 끼워진다.
    prior = cached_data(pid, slug, "s0-prd") or {}
    if md_path.is_file() and not force:
        text = md_path.read_text(encoding="utf-8")
        if text.strip() and text != (prior.get("md") or ""):
            job.add_log("사람이 고친 prd.md 를 씁니다 — 모델을 부르지 않습니다")
            job.add_log(f"  {md_path}")
            data = dict(prior.get("prd") or {})
            return write_cache(pid, slug, "s0-prd",
                               input_hash=stage.input_hash(pid, slug, project),
                               data={"prd": data, "md": text, "source": "manual"},
                               code_version=stage.code_version, status="ok")

    repo = cached_data(pid, slug, "s2-repo") or {}
    frames = cached_data(pid, slug, "s1-frames") or {}
    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "prd.md").read_text(encoding="utf-8")

    job.progress(0, 1, "기획서")
    p = ClaudeProvider(
        model=(project.get("models") or cfg["models"]).get("script")
              or cfg["models"]["script"],
        effort=cfg["effort"].get("decisions", "high"),
        cwd=(repo or {}).get("clone_dir"),
        allowed_tools=["Read", "Grep", "Glob"] if repo.get("clone_dir") else [],
        max_turns=int(cfg.get("prd_turns", 20)) if repo.get("clone_dir") else 1,
        budget_usd=cfg["budget_usd"]["per_stage"],
        # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
        on_activity=lambda s: job.progress(0, 1, s),
    )
    raw = p.structured(system,
                       [{"role": "user",
                         "content": build_brief(project, repo, frames, d.parent)}],
                       schema=SCHEMA)
    job.progress(1, 1, "정리")

    # 문자열은 전부 평문으로 — 이 값들이 나중에 화면에도 들어간다
    for k in ("one_liner", "audience", "goal"):
        raw[k] = plain(raw.get(k))
    raw["key_messages"] = [plain(x) for x in (raw.get("key_messages") or [])][:7]

    md = to_md(raw, project.get("title") or slug)
    ws.write_text(md_path, md)
    ws.write_json(d / "prd.json", raw)

    need = [a for a in (raw.get("assets_needed") or []) if not a.get("have")]
    warn: List[str] = []
    job.add_log(f"섹션 {len(raw.get('sections') or [])}개 · 목표 {raw.get('target_min')}분 "
                f"· 준비할 자료 {len(need)}건 · ${p.last_cost_usd:.3f}")
    for a in need[:8]:
        job.add_log(f"  없음 · {KIND_LABEL.get(a.get('kind'), '')} — {a.get('what')}")
    if need:
        warn.append(f"아직 없는 자료 {len(need)}건")
    job.add_log(f"기획서: {md_path}")
    job.add_log("이 파일을 고쳐 두면 다음 실행에서 고친 내용이 이깁니다")

    return write_cache(pid, slug, "s0-prd",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"prd": raw, "md": md, "source": "generated"},
                       code_version=stage.code_version,
                       model=p.model, cost_usd=p.last_cost_usd,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s0-prd"].run = run
