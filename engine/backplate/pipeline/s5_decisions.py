# -*- coding: utf-8 -*-
"""S5 기술적 의사결정 — 레포를 직접 읽고 "무엇을 포기했는가" 를 채운다.

계정 내 60개 레포 어디에도 **코드베이스를 읽고 판단을 서술하는 것**은 없었다.
여기가 진짜 신규 구현이고, 발표물의 설득력이 여기서 나온다.

★ 모든 `evidence.ref` 는 **실존 검증**을 거친다. 파일 경로면 clone 안에 있어야 하고,
  커밋 sha 면 S2 가 가져온 목록에 있어야 한다. 없으면 그 근거를 버리고 경고를 남긴다.
  지어낸 경로가 발표 자료에 실리는 것이 가장 나쁘다.

비용을 아끼려고 **판단이 필요한 장만** 보낸다(decision · architecture · metric · ops).
텍스트 도입부나 영상 장은 여기 오지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import STAGES, cached_data, write_cache

# 판단을 물을 만한 장 종류
WANT_KINDS = {"decision", "architecture", "metric", "ops"}
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "problem": {"type": "string"},
                    "choice": {"type": "string"},
                    "rationale": {"type": "string"},
                    "tradeoff": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string",
                                         "enum": ["file", "commit", "comment"]},
                                "ref": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["kind", "ref"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["no", "problem", "choice", "rationale", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


def verify_evidence(ev: List[Dict[str, Any]], clone: Path,
                    shas: set[str]) -> tuple[List[Dict[str, Any]], List[str]]:
    """**실존 검증.** 없는 것은 버린다 — 지어낸 근거가 실리는 것이 가장 나쁘다."""
    ok: List[Dict[str, Any]] = []
    bad: List[str] = []
    for e in ev or []:
        ref = str(e.get("ref") or "").strip()
        if not ref:
            continue
        if e.get("kind") == "commit":
            m = SHA_RE.search(ref)
            if m and any(s.startswith(m.group(0)) for s in shas):
                ok.append(e)
            else:
                bad.append(f"커밋 없음: {ref}")
            continue
        # file / comment — 경로:줄 형태를 허용
        path = ref.split(":")[0].strip()
        if clone and (clone / path).exists():
            ok.append(e)
        else:
            bad.append(f"파일 없음: {path}")
    return ok, bad


def build_brief(targets: List[Dict[str, Any]], repo: Dict[str, Any]) -> str:
    lines = ["# 채울 슬라이드", ""]
    for s in targets:
        lines.append(f"## {s['no']} · {s['title']}")
        if s.get("note"):
            lines.append(f"메모: {s['note']}")
        if s.get("evidence_hint"):
            lines.append(f"볼 곳: {s['evidence_hint']}")
        lines.append("")

    if repo and not repo.get("skipped"):
        lines.append("# 참고 — 최근 커밋")
        for c in (repo.get("commits") or [])[:40]:
            lines.append(f"- {c['short_sha']} {c['subject']}")
        lines.append("")
        lines.append("레포는 현재 작업 폴더다. Read/Grep/Glob 으로 직접 열어 봐라.")
        rs = repo.get("repos") or []
        if len(rs) > 1:
            lines.append("")
            lines.append("레포가 여럿이다. 작업 폴더 아래 하위 폴더로 갈려 있다:")
            for r in rs:
                pre = (r.get("prefix") or "").rstrip("/") or "."
                live = f" · 라이브 {r['live_url']}" if r.get("live_url") else " · 사이트 없음"
                lines.append(f"  {pre}/  = {r['name_with_owner']}{live}")
            lines.append("근거 경로는 이 접두를 포함해서 쓴다 (예: axexam/app/src/…).")

    lines.append("\n주어진 no 만 채워라. JSON 만 출력.")
    return "\n".join(lines)


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s5-decisions"]

    outline = cached_data(pid, slug, "s2b-outline") or {}
    if not outline.get("slides"):
        raise RuntimeError("구조 설계(s2b-outline)를 먼저 돌리세요")
    repo = cached_data(pid, slug, "s2-repo") or {}
    clone = Path(repo["clone_dir"]) if repo.get("clone_dir") else None
    shas = {c["sha"] for c in (repo.get("commits") or [])}

    all_targets = [s for s in outline.get("slides", []) if s.get("kind") in WANT_KINDS]
    if not all_targets:
        job.add_log("판단을 채울 장이 없습니다")
        return write_cache(pid, slug, "s5-decisions",
                           input_hash=stage.input_hash(pid, slug, project),
                           data={"slides": {}}, code_version=stage.code_version,
                           status="skipped")

    targets = [s["no"] for s in all_targets]
    system = (Path(__file__).resolve().parent.parent
              / "llm" / "prompts" / "decisions.md").read_text(encoding="utf-8")

    # ★ 청크로 쪼갠다. 21장을 한 콜에 40턴으로 읽으면 예산($1.5)에서 끊기고
    #   **그때까지 읽은 것이 통째로 날아간다**(실제로 그랬다). 청크마다 결과가
    #   쌓이므로 중간에 끊겨도 앞부분은 남는다.
    # ★ 이미 나온 장은 다시 사지 않는다.
    #   묶음 하나가 실패해도 나머지는 살아남게 해 뒀는데, 재시도할 때 전부 다시
    #   부르면 실패 하나가 매번 전체 값을 물린다. 실패한 묶음만 채운다.
    prior = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {}) if not force else {}
    pending = [s for s in all_targets if str(s["no"]) not in prior]
    if prior:
        job.add_log(f"이미 나온 {len(prior)}장 재사용 · 남은 {len(pending)}장")

    CHUNK = int(cfg.get("decisions_chunk", 5))
    chunks = [pending[i:i + CHUNK] for i in range(0, len(pending), CHUNK)]
    job.add_log(f"대상 {len(targets)}장 → {len(chunks)}묶음 (묶음당 {CHUNK}장)")
    job.progress(0, len(chunks), "레포 읽는 중")

    out: Dict[str, Any] = dict(prior)
    warn: List[str] = []
    dropped = 0
    total_cost = 0.0
    model_used = ""

    for ci, chunk in enumerate(chunks, 1):
        if job.canceled:
            warn.append(f"{ci}묶음에서 취소됨")
            break
        p = ClaudeProvider(
            model=(project.get("models") or cfg["models"]).get("decisions")
                  or cfg["models"]["decisions"],
            effort=cfg["effort"].get("decisions", "high"),
            cwd=str(clone) if clone else None,
            allowed_tools=["Read", "Grep", "Glob"] if clone else [],
            max_turns=int(cfg.get("decisions_turns", 24)) if clone else 1,
            budget_usd=cfg["budget_usd"]["per_stage"],
            # 2~3분씩 간다. 무엇을 읽고 있는지 보여야 멈춘 걸로 안 본다.
            on_activity=lambda s: job.progress(0, 1, s),
        )
        model_used = p.model
        nos = [s["no"] for s in chunk]
        try:
            raw = p.structured(system,
                               [{"role": "user", "content": build_brief(chunk, repo)}],
                               schema=SCHEMA)
        except Exception as e:  # noqa: BLE001
            # 한 묶음이 실패해도 나머지는 계속한다 — 전부 잃는 것보다 낫다
            warn.append(f"{ci}묶음({nos}) 실패: {type(e).__name__}: {str(e)[:120]}")
            job.add_log(f"  {ci}/{len(chunks)} 실패 — 계속")
            total_cost += p.last_cost_usd
            continue

        total_cost += p.last_cost_usd
        want = set(nos)
        for d in raw.get("decisions") or []:
            no = int(d.get("no") or 0)
            if no not in want:
                warn.append(f"요청하지 않은 슬라이드 {no} → 버림")
                continue
            ev, bad = verify_evidence(d.get("evidence"), clone, shas)
            dropped += len(bad)
            for b in bad[:2]:
                warn.append(f"{no}: {b}")
            out[str(no)] = {
                "problem": d.get("problem", ""), "choice": d.get("choice", ""),
                "rationale": d.get("rationale", ""), "tradeoff": d.get("tradeoff", ""),
                "evidence": ev,
                "confidence": round(len(ev) / max(len(d.get("evidence") or [1]), 1), 2),
            }
        job.progress(ci, len(chunks), f"{ci}/{len(chunks)}묶음 · ${total_cost:.2f}")
        job.add_log(f"  {ci}/{len(chunks)} {nos} → {len(out)}장 누적 · ${p.last_cost_usd:.3f}")

    p = type("_", (), {"last_cost_usd": total_cost, "model": model_used})()
    missing = [n for n in targets if str(n) not in out]
    if missing:
        warn.append(f"채워지지 않은 장: {missing}")
    no_tradeoff = [n for n, v in out.items() if not v.get("tradeoff")]
    if no_tradeoff:
        job.add_log(f"트레이드오프가 비어 있는 장 {len(no_tradeoff)}개 — 구현일 뿐 판단이 아닐 수 있다")

    job.add_log(f"{len(out)}장 채움 · 근거 {sum(len(v['evidence']) for v in out.values())}건 "
                f"(검증 실패 {dropped}건 버림) · ${p.last_cost_usd:.3f}")

    return write_cache(pid, slug, "s5-decisions",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"slides": out}, code_version=stage.code_version,
                       model=p.model, cost_usd=p.last_cost_usd,
                       status="degraded" if (missing or dropped) else "ok",
                       warnings=warn)


STAGES["s5-decisions"].run = run
