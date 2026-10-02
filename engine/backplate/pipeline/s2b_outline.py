# -*- coding: utf-8 -*-
"""S2b 구조 설계 — **이 툴의 핵심.**

레포를 읽고 발표 덱의 뼈대를 짠다: 레인(sections)과 연속 번호 슬라이드(slides).

    S2b  번호 + 레인 배정        1 text · 2 video · 3 text_image · 4 text …
      ↓  레인별로 따로 채움      (S3 캡션 · S4 링크 · S5 의사결정 · S6 대본)
    S8   번호순으로 다시 모음
      ↓
    S9   하나로 렌더링           1,2,3,…,N

★ 레인은 **연속 구간이 아니다.** 텍스트가 1,4,7,10 이고 영상이 2,5,8 처럼 섞여야
  발표가 지루하지 않다. 프롬프트에 좋은 예/나쁜 예로 박아 두었고, 여기서도
  뭉침을 검사해 경고한다.

이 툴이 파는 것은 콘텐츠가 아니라 **기획**이다. 개발자는 재료를 이미 갖고 있고
없는 건 구성할 시간이다. 그래서 무게중심이 캡션 생성이 아니라 여기에 있다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from core import config, refs as refs_mod, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, read_cache, write_cache

LANE_KINDS = ("text", "text_image", "video", "code")
SLIDE_KINDS = ("cover", "context", "feature", "architecture", "decision",
               "metric", "ops", "note", "closing")

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "deck_title": {"type": "string"},
        "deck_subtitle": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": list(LANE_KINDS)},
                    "summary": {"type": "string"},
                },
                "required": ["id", "title", "kind", "summary"],
                "additionalProperties": False,
            },
        },
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "section": {"type": "string"},
                    "kind": {"type": "string", "enum": list(SLIDE_KINDS)},
                    "title": {"type": "string"},
                    "note": {"type": "string"},
                    "video_id": {"type": "string"},
                    "evidence_hint": {"type": "string"},
                },
                "required": ["no", "section", "kind", "title", "note"],
                "additionalProperties": False,
            },
        },
        # ★ 예산 때문에 못 담은 것. **버린 것을 적어 두는 게 늘리기의 재료다** —
        #   나중에 예산을 올릴 때 여기부터 넣으면 처음부터 다시 고민하지 않는다.
        "dropped": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["deck_title", "sections", "slides"],
    "additionalProperties": False,
}


def prd_block(prd: Dict[str, Any]) -> List[str]:
    """★ 기획서가 있으면 **맨 앞에** 온다. 구성은 이걸 따라야 한다."""
    if not prd:
        return []
    L = ["# 발표 기획서 — 이걸 따른다", ""]
    if prd.get("one_liner"):
        L.append(prd["one_liner"])
    if prd.get("audience"):
        L.append(f"보는 사람: {prd['audience']}")
    if prd.get("goal"):
        L.append(f"목표: {prd['goal']}")
    if prd.get("target_min"):
        L.append(f"목표 길이: {prd['target_min']}분")
    if prd.get("key_messages"):
        L.append("핵심 메시지:")
        L += [f"  - {m}" for m in prd["key_messages"]]
    if prd.get("sections"):
        L.append("정해진 섹션(장수는 참고값):")
        L += [f"  - {s.get('title')} · {s.get('slides')}장 — {s.get('why')}"
              for s in prd["sections"]]
    if prd.get("not_covering"):
        L.append("이번에 다루지 않는 것:")
        L += [f"  - {x}" for x in prd["not_covering"]]
    L.append("")
    return L


def build_brief(project: Dict[str, Any], repo: Dict[str, Any],
                frames: Dict[str, Any], prd: Dict[str, Any] | None = None,
                root: Path | None = None) -> str:
    """Claude 에게 줄 재료. **파일 내용은 안 넣는다** — 트리·커밋·README 만.
    본문이 필요하면 Read/Grep 으로 직접 가져가게 한다(토큰을 아끼고 근거가 정확해진다)."""
    lines: List[str] = []
    lines.append(f"# 프로젝트\n{project.get('title')}")
    for u in (project.get("urls") or []):
        lines.append(f"{u.get('label') or '사이트'}: {u.get('url')}")
    if not project.get("urls") and project.get("live_url"):
        lines.append(f"라이브: {project['live_url']}")

    if repo and not repo.get("skipped"):
        lines.append(f"\n# 레포\n{repo['name_with_owner']} · {repo['branch']} "
                     f"· HEAD {repo['head_sha'][:8]}")
        # 레포 없이 주소만 있는 것 — 같은 레포의 하위를 따로 배포한 경우가 많다
        for x in (repo.get("extra_sites") or []):
            lines.append(f"같이 도는 사이트: {x['url']}"
                         + (f" ({x['label']})" if x.get("label") else ""))
        lines.append(f"스택 추정: {', '.join(repo.get('stack') or []) or '미상'}")
        lines.append(f"파일 {repo['file_count']}개 · 커밋 {repo['commit_count']}건")
        lines.append("\n## README\n" + (repo.get("readme") or "(없음)")[:6000])

        lines.append("\n## 최근 커밋")
        for c in (repo.get("commits") or [])[:40]:
            lines.append(f"- {c['short_sha']} {c['date'][:10]} {c['subject']}")

        lines.append("\n## 파일 트리 (경로만)")
        tree = repo.get("tree") or []
        # 큰 파일부터 — 보통 중요한 파일이다
        top = sorted(tree, key=lambda t: -t["bytes"])[:220]
        for t in sorted(top, key=lambda t: t["path"]):
            lines.append(f"- {t['path']}")
        if len(tree) > len(top):
            lines.append(f"…외 {len(tree) - len(top)}개")

        if repo.get("docs"):
            lines.append("\n## 문서 후보\n" + "\n".join(f"- {d}" for d in repo["docs"]))

    lines.append("\n# 영상 (전부 어딘가에 배치해야 한다)")
    fitems = (frames or {}).get("items", {})
    for it in project.get("items", []):
        if not it.get("include", True):
            continue
        f = fitems.get(it["id"], {})
        dur = f.get("duration_sec")
        n = len(f.get("frames") or [])
        lines.append(f"- {it['id']} · {it.get('title')} · "
                     f"{dur:.0f}초 · 프레임 {n}컷" if dur else
                     f"- {it['id']} · {it.get('title')}")

    if root is not None:
        lines += refs_mod.brief_block(project.get("refs") or {}, root, budget=9000)

    want = slide_budget(project)
    lines.append(f"\n# 요구\n**장 예산: {want}장** (±2). 번호는 1부터 연속. "
                 f"예산을 넘기지 마라 — 못 담는 것은 버리고 dropped 에 한 줄씩 적어라. "
                 f"레인을 뭉치지 말고 섞어라. JSON 만 출력.")
    return "\n".join(lines)


# ★ 기본값을 **작게** 둔다. 장마다 문구·이미지·영상·음성 넷을 사람이 확정하므로,
#   40장은 확인 160번이다. 짧게 만들어 끝까지 가 보고, 모자라면 그때 늘린다.
BUDGET_DEFAULT = 14
BUDGET_STEPS = [14, 20, 26, 32, 40]


def slide_budget(project: Dict[str, Any]) -> int:
    try:
        n = int(project.get("slide_budget") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if 8 <= n <= 60 else BUDGET_DEFAULT


def normalize(raw: Dict[str, Any], project: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """**거부하지 않고 수리한다.** 스펙 밖 값이 와도 덱은 나와야 한다."""
    warn: List[str] = []

    secs: List[Dict[str, Any]] = []
    seen_ids = set()
    for s in raw.get("sections") or []:
        sid = str(s.get("id") or "").strip() or f"s{len(secs) + 1}"
        if sid in seen_ids:
            sid = f"{sid}{len(secs) + 1}"
        seen_ids.add(sid)
        kind = s.get("kind") if s.get("kind") in LANE_KINDS else "text"
        if s.get("kind") not in LANE_KINDS:
            warn.append(f"섹션 {sid}: 미지 kind={s.get('kind')!r} → text")
        secs.append({"id": sid, "title": str(s.get("title") or sid),
                     "kind": kind, "summary": str(s.get("summary") or "")})
    if not secs:
        secs = [{"id": "a", "title": "본문", "kind": "text", "summary": ""}]
        warn.append("섹션이 비어 기본 레인 하나를 만들었다")

    valid_sec = {s["id"] for s in secs}
    valid_vid = {it["id"] for it in project.get("items", []) if it.get("include", True)}

    slides: List[Dict[str, Any]] = []
    for sl in raw.get("slides") or []:
        sec = sl.get("section")
        if sec not in valid_sec:
            warn.append(f"슬라이드 {sl.get('no')}: 미지 섹션 {sec!r} → {secs[0]['id']}")
            sec = secs[0]["id"]
        kind = sl.get("kind") if sl.get("kind") in SLIDE_KINDS else "note"
        vid = sl.get("video_id")
        if vid and vid not in valid_vid:
            warn.append(f"슬라이드 {sl.get('no')}: 없는 영상 {vid!r} → 제거")
            vid = None
        slides.append({
            "no": int(sl.get("no") or 0),
            "section": sec, "kind": kind,
            "title": str(sl.get("title") or "").strip(),
            "note": str(sl.get("note") or "").strip(),
            "video_id": vid,
            "evidence_hint": sl.get("evidence_hint") or None,
            # 레인 kind 에서 미디어 종류를 파생한다 — Claude 가 따로 쓰지 않는다
            "media_kind": next((s["kind"] for s in secs if s["id"] == sec), "text"),
        })

    # 번호를 1부터 연속으로 다시 매긴다. 원래 순서는 지킨다.
    slides.sort(key=lambda s: (s["no"] if s["no"] > 0 else 10**6))
    for i, s in enumerate(slides, 1):
        if s["no"] != i:
            warn.append(f"번호 {s['no']} → {i} 재배열")
        s["no"] = i

    # 빠진 영상 보충 — "전부 배치" 규칙을 코드가 보장한다
    used = {s["video_id"] for s in slides if s.get("video_id")}
    missing = [v for v in valid_vid if v not in used]
    if missing:
        vsec = next((s["id"] for s in secs if s["kind"] == "video"), None)
        if vsec is None:
            vsec = "vid"
            secs.append({"id": vsec, "title": "화면", "kind": "video",
                         "summary": f"{len(missing)}개 기능"})
        titles = {it["id"]: it.get("title") for it in project.get("items", [])}
        for v in sorted(missing):
            slides.append({"no": len(slides) + 1, "section": vsec, "kind": "feature",
                           "title": titles.get(v) or v, "note": "",
                           "video_id": v, "evidence_hint": None,
                           "media_kind": "video"})
        warn.append(f"배치되지 않은 영상 {len(missing)}개를 뒤에 붙였다: {', '.join(sorted(missing))}")

    # 레인 뭉침 검사 — 같은 레인이 5장 넘게 연달으면 발표가 지루해진다
    run_len, run_sec, worst = 0, None, 0
    for s in slides:
        if s["section"] == run_sec:
            run_len += 1
        else:
            run_sec, run_len = s["section"], 1
        worst = max(worst, run_len)
    if worst >= 6:
        warn.append(f"같은 레인이 {worst}장 연달아 붙어 있다 — 섞이지 않았다")

    for s in secs:
        s["slide_nos"] = [x["no"] for x in slides if x["section"] == s["id"]]

    return ({"deck_title": str(raw.get("deck_title") or project.get("title") or ""),
             "deck_subtitle": str(raw.get("deck_subtitle") or ""),
             "sections": secs, "slides": slides,
             "budget": slide_budget(project),
             # 예산 밖으로 밀린 것 — 늘릴 때 이것부터 들어간다
             "dropped": [str(x).strip() for x in (raw.get("dropped") or [])
                         if str(x).strip()][:20]}, warn)


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s2b-outline"]

    repo = cached_data(pid, slug, "s2-repo") or {}
    frames = cached_data(pid, slug, "s1-frames") or {}
    if repo.get("skipped") or not repo:
        job.add_log("레포 없이 영상만으로 구성한다")

    prd = (cached_data(pid, slug, "s0-prd") or {}).get("prd") or {}
    if prd:
        job.add_log(f"기획서를 따릅니다 — 섹션 {len(prd.get('sections') or [])}개 "
                    f"· 목표 {prd.get('target_min')}분")
    brief = build_brief(project, repo, frames, prd, ws.project_dir(pid, slug))
    job.add_log(f"브리프 {len(brief)}자")
    job.progress(0, 1, "구조 설계")

    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "outline.md").read_text(encoding="utf-8")

    clone = (repo or {}).get("clone_dir")
    p = ClaudeProvider(
        model=(project.get("models") or cfg["models"]).get("script") or cfg["models"]["script"],
        effort=cfg["effort"].get("decisions", "high"),
        cwd=clone,                                   # 레포 안에서 근거를 직접 확인하게
        allowed_tools=["Read", "Grep", "Glob"] if clone else [],
        max_turns=30 if clone else 1,
        budget_usd=cfg["budget_usd"]["per_stage"],
        # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
        on_activity=lambda s: job.progress(0, 1, s),
    )
    raw = p.structured(system, [{"role": "user", "content": brief}], schema=SCHEMA)
    job.progress(1, 1, "검증")

    data, warn = normalize(raw, project)
    for w in warn:
        job.add_log("수리: " + w)

    n = len(data["slides"])
    want = slide_budget(project)
    job.add_log(f"섹션 {len(data['sections'])}개 · 슬라이드 {n}장 "
                f"(예산 {want}장) · ${p.last_cost_usd:.3f}")
    status = "ok"
    # 예산의 ±25% 를 넘으면 지시를 안 들은 것이다
    if abs(n - want) > max(3, want * 0.25):
        job.add_log(f"장수 {n} 이 예산 {want}장에서 많이 벗어났다")
        status = "degraded"
    for d in (data.get("dropped") or [])[:8]:
        job.add_log(f"  버림 · {d}")
    if data.get("dropped"):
        job.add_log(f"예산에 못 담은 것 {len(data['dropped'])}건 — 늘리면 이것부터 들어갑니다")

    # ★ **원고가 넣어 둔 칸을 지킨다.** 이 단계는 s2c(원고 구조 읽기)와 **같은
    #   캐시 자리**를 쓴다. 그런데 여기서 통째로 덮으면 원고가 실어 온 것들이
    #   조용히 날아간다 — `say`(그 장에서 말할 것) · `html`(화면에 박히는 글) ·
    #   줄 시각까지. 그러면 뒤에서 대본 단계가 빈 것을 보고 Claude 에게 새로
    #   쓰게 하고, 열아홉 분짜리 원고가 여섯 분짜리 대본이 된다.
    #   (2026-08-17 실측: 20장 원고 6,249자(19분)가 대본 2,169자(6.6분)로 줄었다.
    #    19장이 초기에 5분대였던 것도 같은 일이었다.)
    # ★ 제목·순서·예산은 이 단계가 정하는 것이니 그대로 덮는다. **원고에서만
    #   나올 수 있는 칸**만 되살린다.

    # ★ 되살릴 원본은 **원고가 남긴 것**이 먼저다(`s2c-capture` 의 `from_manuscript`).
    #   예전에는 옛 s2b 캐시만 봤는데, 그 자리는 이 단계가 덮는 자리라 한 번 비면
    #   되살릴 것이 영영 없어진다 — 21장이 그렇게 17분 원고에서 6.2분 대본이 됐다
    #   (2026-08-17). 원고 쪽은 이 단계가 손대지 않으니 몇 번을 돌려도 남아 있다.
    from pipeline.s2c_capture import manuscript_map, restore
    old = manuscript_map(pid, slug)
    kept = sum(restore(s, old.get(str(s.get("no"))))
               for s in (data.get("slides") or []))
    if kept:
        job.add_log(f"원고가 들고 온 대본 {kept}장 — 덮지 않고 지킵니다")

    return write_cache(pid, slug, "s2b-outline",
                       input_hash=stage.input_hash(pid, slug, project),
                       data=data, code_version=stage.code_version,
                       model=p.model, cost_usd=p.last_cost_usd,
                       status=status if not warn else ("degraded" if status == "degraded" else "ok"),
                       warnings=warn)


STAGES["s2b-outline"].run = run
