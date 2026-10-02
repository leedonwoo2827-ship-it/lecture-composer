# -*- coding: utf-8 -*-
"""S3 프레임 캡션 — **영상 레인이 쓸 컷만.**

전수 캡션은 과설계다. 레퍼런스 덱(cc-video-editing-deck)도 프레임별 캡션이 없다 —
라벨과 ✓ 와 섹션 제목만으로 읽힌다. 의미를 나르는 것은 구조지 캡션이 아니다.

그래서 여기가 하는 일은 캡션 생성이 아니라 **선별**이다:

    S1 이 61컷 추출  →  S3 가 영상마다 필요한 만큼만 ✓  →  ✓ 하나가 슬라이드 하나

몇 개를 고를지는 S2b 가 정한다. `v1` 을 쓰는 슬라이드가 3장이면 3컷을 고른다.
사람이 편집표에서 갈아 끼울 수 있고(오버라이드), 그 손편집은 재실행에도 살아남는다.

호출은 **영상당 한 번.** 프레임 8~12컷을 한 콜에 묶는다 — 호출당 최소 비용이 있어
컷마다 부르면 열 배가 된다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "caption": {"type": "string"},
                    "selected": {"type": "boolean"},
                    "check_reason": {"type": "string"},
                },
                "required": ["id", "caption", "selected"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["frames"],
    "additionalProperties": False,
}


def want_counts(outline: Dict[str, Any]) -> Dict[str, int]:
    """영상마다 슬라이드가 몇 장인가 = 몇 컷을 골라야 하는가."""
    n: Dict[str, int] = {}
    for s in outline.get("slides") or []:
        v = s.get("video_id")
        if v:
            n[v] = n.get(v, 0) + 1
    return n


def build_parts(item: Dict[str, Any], root: Path) -> List[Dict[str, Any]]:
    """`[{"text": 라벨}, {"image": 경로}, …]` — 비전 콜의 재료."""
    parts: List[Dict[str, Any]] = []
    for f in item.get("frames") or []:
        img = root / f["vision"]
        if not img.exists():
            img = root / f["file"]
        if not img.exists():
            continue
        parts.append({"text": f"[{f['id']}] t={f['t_sec']:.1f}s"})
        parts.append({"image": img})
    return parts


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s3-caption"]

    frames = (cached_data(pid, slug, "s1-frames") or {}).get("items", {})
    if not frames:
        raise RuntimeError("프레임 추출(s1-frames)을 먼저 돌리세요")
    outline = cached_data(pid, slug, "s2b-outline") or {}
    wants = want_counts(outline)

    root = ws.project_dir(pid, slug)
    titles = {it["id"]: it.get("title") for it in project.get("items", [])}
    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "caption.md").read_text(encoding="utf-8")

    # ★ 덱이 안 쓰는 영상은 건너뛴다. 안 고른 컷에 돈을 쓰지 않는다.
    todo = [v for v in frames if not wants or wants.get(v)]
    skipped = [v for v in frames if v not in todo]
    if skipped:
        job.add_log(f"덱이 쓰지 않는 영상 {len(skipped)}개 건너뜀: {', '.join(sorted(skipped))}")

    # ★ 이미 성공한 영상은 다시 부르지 않는다.
    #   비전 콜은 실패가 섞인다(모델이 한 턴을 더 쓰려다 max_turns 에 걸린다).
    #   재시도할 때마다 성공한 것까지 다시 사면 실패 하나가 전체 값을 매번 물린다.
    prior = (cached_data(pid, slug, "s3-caption") or {}).get("items", {}) if not force else {}
    reuse = [v for v in todo if (prior.get(v) or {}).get("frames")]
    if reuse:
        job.add_log(f"이미 된 영상 {len(reuse)}개 재사용: {', '.join(sorted(reuse))}")
        todo = [v for v in todo if v not in reuse]

    job.add_log(f"영상 {len(todo)}개 · 프레임 {sum(len(frames[v].get('frames') or []) for v in todo)}컷")
    job.progress(0, len(todo), "캡션")

    out: Dict[str, Any] = {v: prior[v] for v in reuse}
    warn: List[str] = []
    total_cost = 0.0
    model_used = ""

    for i, vid in enumerate(sorted(todo), 1):
        if job.canceled:
            warn.append(f"{vid} 에서 취소됨")
            break
        item = frames[vid]
        parts = build_parts(item, root)
        if not parts:
            warn.append(f"{vid}: 프레임 파일이 없다")
            continue
        n_frames = len([p for p in parts if p.get("image")])
        want = min(max(wants.get(vid, 1), 1), n_frames)

        p = ClaudeProvider(
            model=(project.get("models") or cfg["models"]).get("caption")
                  or cfg["models"]["caption"],
            effort=cfg["effort"].get("caption", "medium"),
            allowed_tools=[],
            # ★ max_turns=1 이면 모델이 생각을 한 번 더 흘리는 순간
            #   error_max_turns 로 통째로 실패한다(6개 중 2개가 그랬다).
            #   툴이 없으므로 턴을 늘려도 비용은 거의 안 는다.
            max_turns=int(cfg.get("caption_turns", 4)),
            budget_usd=cfg["budget_usd"]["per_stage"],
            # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
            on_activity=lambda s: job.progress(0, 1, s),
        )
        model_used = p.model
        intro = (f"영상: {titles.get(vid) or vid} ({vid})\n"
                 f"길이 {item.get('duration_sec', 0):.0f}초 · 프레임 {n_frames}컷\n"
                 f"요구: 정확히 {want}컷을 selected=true 로 골라라. JSON 만 출력.")
        try:
            raw = p.vision(system, parts, schema=SCHEMA, intro=intro)
        except Exception as e:  # noqa: BLE001
            warn.append(f"{vid} 실패: {type(e).__name__}: {str(e)[:120]}")
            job.add_log(f"  {i}/{len(todo)} {vid} 실패 — 계속")
            total_cost += p.last_cost_usd
            if prior.get(vid):
                out[vid] = prior[vid]      # 직전 것이라도 살린다
            continue
        total_cost += p.last_cost_usd

        valid = {f["id"]: f for f in item.get("frames") or []}
        rows: List[Dict[str, Any]] = []
        for r in raw.get("frames") or []:
            fid = str(r.get("id") or "")
            if fid not in valid:
                warn.append(f"{vid}: 없는 프레임 {fid!r} → 버림")
                continue
            rows.append({
                "id": fid, "t_sec": valid[fid]["t_sec"],
                "file": valid[fid]["file"],
                "caption": str(r.get("caption") or "").strip(),
                "selected": bool(r.get("selected")),
                "check_reason": str(r.get("check_reason") or "").strip(),
            })
        rows.sort(key=lambda r: r["t_sec"])

        # ★ 개수를 코드가 맞춘다. 모델이 3개를 요구받고 5개를 고르는 일이 있다.
        picked = [r for r in rows if r["selected"]]
        if len(picked) != want:
            warn.append(f"{vid}: {want}컷 요구 → {len(picked)}컷 선택, 보정함")
            for r in rows:
                r["selected"] = False
            if len(picked) > want:
                # 시간순으로 고르게 남긴다 — 앞쪽에 몰려 있으면 발표가 늘어진다
                step = len(picked) / want
                keep = {picked[min(int(k * step), len(picked) - 1)]["id"] for k in range(want)}
            else:
                keep = {r["id"] for r in picked}
                rest = [r for r in rows if r["id"] not in keep]
                step = max(len(rest) / max(want - len(keep), 1), 1)
                for k in range(want - len(keep)):
                    j = min(int(k * step), len(rest) - 1)
                    if rest:
                        keep.add(rest[j]["id"])
            for r in rows:
                r["selected"] = r["id"] in keep

        out[vid] = {"frames": rows,
                    "want": want,
                    "picked": [r["id"] for r in rows if r["selected"]]}
        job.progress(i, len(todo), f"{i}/{len(todo)} · ${total_cost:.2f}")
        job.add_log(f"  {i}/{len(todo)} {vid} → {n_frames}컷 중 {want}컷 ✓ · ${p.last_cost_usd:.3f}")

    total_picked = sum(len(v["picked"]) for v in out.values())
    job.add_log(f"영상 {len(out)}개 · ✓ {total_picked}컷 · ${total_cost:.3f}")

    return write_cache(pid, slug, "s3-caption",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"items": out}, code_version=stage.code_version,
                       model=model_used, cost_usd=total_cost,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s3-caption"].run = run
