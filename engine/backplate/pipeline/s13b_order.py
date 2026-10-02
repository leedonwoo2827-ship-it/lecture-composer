# -*- coding: utf-8 -*-
"""S13b 상자 차례 맞추기 — **상자 안 글자를 읽어 대본과 짝짓는다.**

    스틸에서 상자를 오려 낸다  →  Claude 가 읽는다  →  대본 문장과 짝짓는다
                                                      →  등장 시각을 넣는다

★ **왜 사람이 못 하고, 좌표로도 못 하나.**
  `remaster` 는 시각이 비면 상자를 `(y, x)` 로 — 위에서 아래로 — 띄운다. 그런데
  화면 위치는 **말하는 차례를 모른다.** 31장 중 25장이 한 줄에 상자를 좌우로
  둘씩 두고 있어서 그 정렬로는 차례가 정해지지 않는다(2026-08-16 실측).
  실제로 2.4 장은 「목표」를 맨 먼저 말하는데 화면에서는 맨 마지막에 떴다.

★ 좌표만 봐서는 상자 안에 무슨 글자가 있는지 알 수 없다. 그래서 **오려서 본다.**
  캡션 단계(S3)가 프레임을 보는 것과 같은 길이다(`ClaudeProvider.vision`).

★ **한 장에 한 번만 부른다.** 상자를 한 장의 세로 시트로 이어 붙여 보낸다 —
  호출당 최소 비용이 있어서 상자마다 부르면 값이 몇 배가 된다(S3 주석과 같은 이유).

★ 이 단계는 **덮어쓰기가 아니다.** 상자의 자리·크기·종류는 사람이 정한 그대로
  두고 **시각만** 넣는다. 사람이 잡은 것을 기계가 흔들지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline import s13_motion as motion

PAD = 6          # 상자를 오릴 때 둘레 여유(px) — 글자가 잘리면 못 읽는다
SHEET_W = 900    # 시트 가로. 너무 크면 토큰이 늘고, 작으면 글자가 뭉갠다

SCHEMA = {
    "type": "object",
    "properties": {
        "boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},          # 시트에 찍힌 번호
                    "text": {"type": "string"},        # 읽어 낸 글자
                    "cue": {"type": "integer"},        # 짝지은 문장 번호(0=없음)
                },
                "required": ["n", "text", "cue"],
            },
        },
    },
    "required": ["boxes"],
}

SYSTEM = """너는 강의 영상의 자막과 화면을 맞추는 사람이다.

슬라이드에서 오려 낸 **글자 상자**를 하나씩 준다. 그림 앞에 「상자 N」 이라고
번호가 적혀 있다. 그리고 이 슬라이드의 **내레이션 문장**을 번호와 함께 준다.

할 일은 둘이다.
1. 상자마다 **무슨 글자인지 그대로 읽어라**(text).
2. 그 글자가 **어느 문장을 말할 때 떠야 하는지** 문장 번호를 골라라(cue).

고르는 기준:
- 그 상자의 말이 문장에 나오면 그 문장이다. 「미국」 상자는 미국을 말하는 문장.
- 슬라이드 제목·헤드라인처럼 장 전체를 아우르는 것은 **첫 문장(1)** 이다.
- 어느 문장에도 안 걸리면 0 을 준다.
- **여러 상자가 같은 문장을 가리켜도 된다.** 같이 떠야 하는 것들이 그렇다.

JSON 만 출력한다."""


def _crops(pid: int, slug: str, no: int,
           boxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """상자를 하나씩 오려 `vision()` 이 받는 parts 로 만든다.

    ★ **ffmpeg 로 오린다.** 앱의 파이썬(`.venv-app`)에는 Pillow 가 없다 — 넣을
      이유도 없다(이 앱은 픽셀을 안 만진다). ffmpeg 는 이미 모든 그림 일을 하고
      있으니 그걸 쓴다.
    ★ 한 장으로 이어 붙이지 않고 **상자마다 따로** 보낸다. 번호를 그려 넣을
      필요가 없어지고(글로 붙이면 된다), 이어 붙이다 좌표가 어긋날 일도 없다.
    """
    import shutil
    import subprocess

    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg 를 찾지 못했습니다")
    still = motion.still_of(pid, slug, no)
    if still is None:
        raise RuntimeError(f"{no}장 스틸이 없습니다")

    d = ws.cache_dir(pid, slug) / f"_order-{no:03d}"
    d.mkdir(parents=True, exist_ok=True)
    parts: List[Dict[str, Any]] = []
    for i, b in enumerate(boxes, 1):
        x = max(0, int(b["x"]) - PAD)
        y = max(0, int(b["y"]) - PAD)
        w = int(b["w"]) + PAD * 2
        h = int(b["h"]) + PAD * 2
        p = d / f"{i:02d}.png"
        # 가로가 너무 길면 줄인다 — 토큰만 먹고 읽기는 더 안 좋아진다
        vf = f"crop={w}:{h}:{x}:{y}"
        if w > SHEET_W:
            vf += f",scale={SHEET_W}:-1"
        r = subprocess.run([ff, "-v", "error", "-y", "-i", str(still),
                            "-vf", vf, "-frames:v", "1", str(p)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not p.is_file():
            raise RuntimeError(f"{i}번 상자를 오리지 못했습니다: {(r.stderr or '')[:120]}")
        parts.append({"text": f"상자 {i}", "image": p})
    return parts


def _label_hint(pid: int, slug: str, no: int) -> str:
    """그림을 만들 때 적어 둔 라벨 목록. 없으면 빈 문자열.

    ★ 원장(`09_이미지/원장.json`)이 `label_heads` 를 **말하는 차례대로** 들고
      있고, 20장부터는 `label_says`(몇 번째 문장인가)까지 있다. 그러면 이 단계는
      「무슨 글자인지 알아내기」가 아니라 「이 상자가 그중 어느 것인가」가 된다 —
      훨씬 덜 틀린다.
    ★ 19장처럼 옛 판(PROMPT_FMT 5)으로 만든 프로젝트는 `label_says` 가 없다.
      그때는 이름만 주고 문장 짝짓기는 그림을 보고 하게 둔다.
    ★ **덱은 `10_덱/deck.json` 에서 읽는다.** 예전에는 `s8-assemble` 의 캐시에서
      `slides` 를 꺼냈는데 그 캐시에는 `deck_file` 과 `totals` 뿐이라
      (`s8_assemble.py` 의 `write_cache`), 이 함수가 **늘 빈 문자열을 돌려주고
      있었다.** 답지를 넘긴 적이 한 번도 없었다는 뜻이다. 조용해서 몰랐다.
    """
    try:
        deck = (ws.read_json(ws.deck_path(pid, slug), {}) or {}).get("slides") or []
        did = next((s.get("data_id") for s in deck if int(s.get("no", 0)) == no), None)
        if not did:
            return ""
        one = (ws.load_ledger(pid, slug).get("by_id") or {}).get(did) or {}
    except Exception:  # noqa: BLE001
        return ""
    heads = one.get("label_heads") or []
    if not heads:
        return ""
    says = one.get("label_says") or []
    out = ["── 이 그림에 넣은 라벨(만들 때 적어 둔 것) ──"]
    for i, h in enumerate(heads):
        k = says[i] if i < len(says) else 0
        out.append(f"- {h}" + (f"  → {k}번 문장에서 말한다" if k else ""))
    out.append("상자에서 읽은 글자가 이 중 하나면 그 라벨로 본다.")
    if any(says):
        out.append("옆에 적힌 문장 번호가 있으면 **그것을 그대로 cue 로 써라.**")
    return "\n".join(out)


def run_one(pid: int, slug: str, no: int, p: ClaudeProvider) -> Dict[str, Any]:
    """그 장 하나. 시각을 넣은 상자 목록과 읽어 낸 글자를 돌려준다."""
    sc = motion.scene_of(pid, slug, no)
    boxes, cues = sc["boxes"], sc["cues"]
    if not boxes:
        return {"no": no, "boxes": [], "read": [], "skip": "상자 없음"}
    if not cues:
        return {"no": no, "boxes": boxes, "read": [], "skip": "자막 없음"}

    # ★ 읽히는 차례를 고정한다 — 시트 번호와 상자 순서가 어긋나면 전부 틀린다
    boxes = sorted(boxes, key=lambda b: (b["y"], b["x"]))
    parts = _crops(pid, slug, no, boxes)

    lines = "\n".join(f"{i}. ({c['at']:.1f}초) {c['text']}"
                      for i, c in enumerate(cues, 1))
    intro = (f"슬라이드 {no}번 · 상자 {len(boxes)}개 · 문장 {len(cues)}개\n\n"
             f"── 내레이션 ──\n{lines}")

    # ★ 그림을 만들 때 적어 둔 라벨이 있으면 **같이 준다.** 열린 채로 맞추는 것보다
    #   「이 중 어느 것인가」가 훨씬 정확하다. 20장부터는 `say_i`(몇 번째 문장에서
    #   말하는가)까지 들어 있어서 사실상 정답표다(`s3a_imgprompt` PROMPT_FMT 6).
    if hint := _label_hint(pid, slug, no):
        intro += "\n\n" + hint

    raw = p.vision(SYSTEM, parts, schema=SCHEMA, intro=intro)

    read = {int(r["n"]): r for r in (raw.get("boxes") or []) if r.get("n")}
    body = max(1.0, float(sc["len"]) - 0.60)

    # 짝지은 문장의 시작 시각을 등장 시각으로. 같은 문장끼리는 같이 뜬다.
    for i, b in enumerate(boxes, 1):
        r = read.get(i) or {}
        k = int(r.get("cue") or 0)
        b["_text"] = (r.get("text") or "").strip()
        b["at"] = round(min(cues[k - 1]["at"], body - 0.5), 1) if 1 <= k <= len(cues) else None

    # 세우고 메우고 빛끝 채우기 — `s13c_zones` 와 **같은 함수**를 쓴다
    motion.fill_times(boxes, cues, float(sc["len"]))

    return {"no": no, "boxes": boxes,
            "read": [{"n": i, "text": b.get("_text", ""), "at": b["at"]}
                     for i, b in enumerate(boxes, 1)]}


def run(job, pid: int, slug: str, project: Dict[str, Any], *,
        only: List[int] | None = None) -> Dict[str, Any]:
    """모든 장(또는 지정한 장)의 상자 차례를 맞춘다."""
    cfg = config.load()
    z = motion.scene_of(pid, slug, 1)          # 재료가 있는지 먼저 본다
    if z.get("still") is None:
        raise RuntimeError("스틸이 없습니다 — 모션 지정기를 먼저 돌리세요")

    mp4 = motion.target(pid, slug)
    zj = motion._load_zones(mp4) if mp4 else {}
    nos = only or [int(s.get("i", -1)) + 1 for s in (zj.get("scenes") or [])
                   if (s.get("boxes") or [])]
    if not nos:
        raise RuntimeError("상자가 있는 장이 없습니다")

    p = ClaudeProvider(
        model=(project.get("models") or cfg["models"]).get("caption")
              or cfg["models"]["caption"],
        effort=cfg["effort"].get("caption", "medium"),
        allowed_tools=[],
        max_turns=int(cfg.get("caption_turns", 4)),
        budget_usd=cfg["budget_usd"]["per_stage"],
        on_activity=lambda s: job.progress(0, len(nos), s),
    )

    done, warn, cost = 0, [], 0.0
    job.add_log(f"{len(nos)}장 · 상자를 읽어 대본과 짝짓습니다")
    for i, no in enumerate(nos, 1):
        job.progress(i, len(nos), f"{no}장")
        try:
            r = run_one(pid, slug, no, p)
        except Exception as e:                 # noqa: BLE001
            warn.append(f"{no}장: {type(e).__name__}: {str(e)[:100]}")
            job.add_log(f"  {no}장 실패 — 계속합니다")
            continue
        cost += p.last_cost_usd
        if r.get("skip"):
            job.add_log(f"  {no}장 건너뜀 — {r['skip']}")
            continue
        # ★ 자리·크기·종류는 그대로. **시각만** 저장한다.
        motion.save_scene(pid, slug, no, r["boxes"])
        done += 1
        head = " · ".join(f"{x['at']}s {x['text'][:12]}" for x in r["read"][:3])
        job.add_log(f"  {no}장 · 상자 {len(r['boxes'])}개 — {head}")

    job.add_log(f"{done}장 정리 · ${cost:.2f}")
    return {"scenes": done, "cost_usd": round(cost, 4), "warnings": warn}
