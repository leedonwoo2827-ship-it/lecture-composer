# -*- coding: utf-8 -*-
"""영상이 도는데 말이 모자란 장만 **이어 붙인다.**

전체를 다시 돌리면 이미 맞은 장까지 갈아엎고 $1.4 가 또 나간다. 모자란 장만
"지금 대본 뒤에 N초만큼 더 이어 써라" 로 부른다 — 앞부분은 글자 그대로 두고
뒤에만 붙이므로 흐름이 안 깨진다.

    .venv-app\\Scripts\\python tools\\fill_gaps.py 1
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import cached_data, read_cache
from pipeline.s6_script import SCHEMA, clean, est_sec

MIN_GAP = 3.0

SYS = """너는 **사이트를 소개하는 목소리**의 대본에 이어질 말을 쓴다.

이미 쓴 대본이 주어진다. 그 뒤에 자연스럽게 이어지는 말을 더 쓴다.
앞부분은 고치지 마라 — 뒤에 붙일 것만 낸다.

이 장에는 화면 녹화가 붙어 있고, 지금 대본으로는 **영상이 도는 동안 말이 모자란다.**
화면에서 이어서 벌어지는 일을 순서대로 짚어라. 기다리는 동안 무엇이 도는지,
결과가 뜨면 어디를 보면 되는지.

- 앞 문장과 같은 말을 반복하지 마라.
- **기술 이야기를 하지 마라.** 파일 경로·스택 이름·아키텍처 용어 금지.
  사용자가 화면에서 겪는 일만 말한다.
- 빈 문장으로 채우지 마라. "이렇게 유용하게 쓸 수 있습니다" 같은 말은 금지.
- 문체는 앞부분과 똑같이. 존댓말, 현재형, 화면을 안내하듯.
- `srt_text` 는 자막(원문), `narration_text` 는 TTS 발음 표기.
- 평문만. JSON 만 출력.
"""


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    proj_row = next((p for p in ws.list_projects() if p["id"] == pid), None)
    if not proj_row:
        print(f"프로젝트 {pid} 없음")
        return 1
    slug = proj_row["slug"]

    cfg = config.load()
    proj = ws.load_project(pid, slug)
    env = read_cache(pid, slug, "s6-script")
    if not env:
        print("대본이 없습니다")
        return 1
    S = env["data"]["slides"]
    byno = {s["no"]: s for s in (cached_data(pid, slug, "s2b-outline") or {}).get("slides", [])}
    cps = float((proj.get("narration") or cfg["narration"]).get("chars_per_sec", 5.7))

    todo = []
    for k, v in S.items():
        no = int(k)
        if not byno.get(no, {}).get("video_id"):
            continue
        gap = round(v["budget_sec"] - v["narration_seconds"], 1)
        if gap > MIN_GAP:
            todo.append((no, v, gap))
    if not todo:
        print("이어 붙일 장이 없습니다")
        return 0
    print(f"이어 붙일 장 {len(todo)}개: {[n for n, _, _ in todo]}")

    out = dict(S)
    cost = 0.0
    for no, v, gap in todo:
        s = byno[no]
        need = int(gap * cps)
        brief = (
            f"# 장 {no} · {s.get('title')}\n"
            f"화면 녹화가 이 장에서 {v['budget_sec']:.0f}초 돈다.\n"
            f"지금 대본은 {v['narration_seconds']:.0f}초 분량이라 **{gap:.0f}초가 빈다.**\n\n"
            f"## 이미 쓴 대본 (고치지 마라)\n{v['srt_text']}\n\n"
            f"## 요구\n뒤에 이어질 말을 공백 뺀 글자 약 {need}자 만큼 더 써라.\n"
            f"`no` 는 {no} 로 두고, **이어 붙일 부분만** 담아라."
        )
        p = ClaudeProvider(
            model=(proj.get("models") or cfg["models"])["script"],
            effort=cfg["effort"].get("script", "high"),
            allowed_tools=[], max_turns=1, budget_usd=cfg["budget_usd"]["per_stage"],
        )
        try:
            raw = p.structured(SYS, [{"role": "user", "content": brief}], schema=SCHEMA)
        except Exception as e:  # noqa: BLE001
            print(f"  {no} 실패: {type(e).__name__}: {str(e)[:80]}")
            continue
        cost += p.last_cost_usd
        r = next((x for x in (raw.get("slides") or []) if int(x.get("no") or 0) == no), None)
        add_srt = clean((r or {}).get("srt_text"))
        if not add_srt:
            print(f"  {no} 빈 응답")
            continue
        add_nar = clean(r.get("narration_text")) or add_srt
        srt = (v["srt_text"] + " " + add_srt).strip()
        nar = (v["narration_text"] + " " + add_nar).strip()
        sec = est_sec(nar, cps)
        rec = dict(v, srt_text=srt, narration_text=nar, narration_seconds=sec)
        left = round(v["budget_sec"] - sec, 1)
        if left > MIN_GAP:
            rec["short_sec"] = left
        else:
            rec.pop("short_sec", None)
        out[str(no)] = rec
        print(f"  {no}: {v['narration_seconds']:.0f}초 → {sec:.0f}초 "
              f"(영상 {v['budget_sec']:.0f}초, 남은 빈 시간 {max(0, left):.0f}초) "
              f"· ${p.last_cost_usd:.3f}")

    total = round(sum(x["narration_seconds"] for x in out.values()), 1)
    warn = [f"{n}: 영상이 {x['short_sec']:.0f}초 더 도는데 말이 없다"
            for n, x in out.items() if x.get("short_sec")]
    env["data"]["slides"] = out
    env["data"]["total_sec"] = total
    env["warnings"] = warn
    env["cost_usd"] = round(env.get("cost_usd", 0) + cost, 4)
    env["status"] = "degraded" if warn else "ok"
    ws.write_json(ws.cache_dir(pid, slug) / "s6-script.json", env)

    print(f"\n전체 {total:.0f}초 ({total / 60:.1f}분) · 추가 ${cost:.3f}")
    print("남은 경고:", warn or "없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
