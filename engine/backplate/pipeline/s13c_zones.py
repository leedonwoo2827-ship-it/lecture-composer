# -*- coding: utf-8 -*-
"""S13c 상자 자리 찾기 — **원장에 적어 둔 라벨만 찾아 상자를 놓는다.**

    원장의 라벨 답지  +  격자 얹은 스틸  →  Claude 가 「어디에 있나 · 제대로
    나왔나」를 답한다  →  잉크로 가장자리를 조인다  →  zones.json

★ **묻지 않은 것에는 상자가 생기지 않는다.** 이것이 이 단계의 뼈대다.
  예전 방식(`make_picker.propose`)은 화면을 훑어 「글자처럼 생긴 것」을 혼자
  찾았다. 그래서 화살표·톱니바퀴·받침대에 상자가 붙고, 정작 라벨은 놓쳤다 —
  실측하면 그림에 구워진 라벨 130개 중 **4개**를 잡는다(2026-09-14).
  여기서는 원장이 **무슨 글자가 있는지 이미 알고 있으므로**, 비전은 「이 글자가
  어디 있나」만 답한다. 그림에는 물어볼 이름이 없으니 상자도 없다.

★ **비전이 픽셀을 정확히 찍을 거라 기대하지 않는다.** 격자 얹은 그림으로
  실측하면 1~2%p(가로 38px·세로 21px) 안에서 자리를 짚는다. 그 정도면 충분하고,
  가장자리는 `tools/motion/zone_cv.py` 가 잉크를 보고 끝낸다.

★ **판정을 같이 받는다.** 라벨이 깨져 나온 장이 있다 — 자모가 뭉개지거나 없는
  글자가 섞인다. 그런 라벨은 `kind:"cover"` 로 덮어 당장 영상이 나가게 하고,
  「다시 그릴 장」 목록에 올린다.

★ 사람이 고친 것을 덮지 않는다. `done` 표시가 있는 장은 건너뛰고, 쓰기 전에
  물러 둘 것을 남긴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline import s13_motion as motion

# 라벨 하나의 줄들이 이만큼 안에 있으면 같은 묶음으로 본다(백분율 → 픽셀 변환 뒤)
MARGIN = 20

SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "verdict": {"type": "string",
                                "enum": ["found", "garbled", "missing", "different"]},
                    "read": {"type": "string"},
                    "on_panel": {"type": "boolean"},
                    "x": {"type": "number"}, "y": {"type": "number"},
                    "w": {"type": "number"}, "h": {"type": "number"},
                },
                "required": ["i", "verdict", "read", "on_panel",
                             "x", "y", "w", "h"],
            },
        },
    },
    "required": ["labels"],
}

SYSTEM = """너는 강의 영상에 들어갈 그림을 검수하는 사람이다.

그림에 **인쇄되어 있어야 할 라벨 목록**(답지)을 준다. 그림에는 10% 간격으로
**빨간 격자**가 그어져 있고 가장자리에 눈금 숫자가 적혀 있다. 옅은 선은 5%다.

라벨마다 둘을 답한다.

1. **판정** — 답지대로 나왔나
   found      답지 그대로 멀쩡히 인쇄되어 있다
   garbled    글자는 있는데 **깨졌다** — 자모가 뭉개졌거나, 획이 끊겼거나,
              없는 글자·이상한 기호가 섞였다
   missing    그 글자가 그림에 없다
   different  글자는 멀쩡한데 답지와 **다른 말**이다
   `read` 에는 **화면에 보이는 대로** 옮겨 적어라. 답지를 베끼지 마라.
   깨진 글자는 깨진 대로 적어야 사람이 무엇이 잘못됐는지 안다.

2. **자리** — `x y w h` 를 **백분율(0~100)** 로. 왼쪽 위가 0,0 이다.
   굵은 소제목과 **그 아래 딸린 설명 줄까지 한 덩어리로** 감싸라.
   `missing` 이면 자리는 0 을 준다.

   ★ **격자를 보고 재라. 짐작하지 마라.** 라벨이 「보통 이런 자리에 온다」는
     생각으로 답하지 마라. 글자의 왼쪽 끝이 어느 세로선과 어디쯤에서 만나는지,
     첫 줄 윗변이 어느 가로선 근처인지 **눈으로 짚어** 답해라.
   ★ 라벨마다 **크기가 다르다.** 여러 라벨에 같은 `w`·`h` 를 적었다면 재지 않고
     틀에 맞춰 적은 것이다 — 다시 봐라.

3. **뒤에 배경이 깔려 있나** (`on_panel`)
   그 글자 뒤에 **판·띠·칠판·카드·말풍선처럼 바탕과 다른 면**이 깔려 있으면
   `true`. 그냥 그림 위에 글자만 얹혀 있으면 `false`.
   (판 위에 얹힌 글자는 상자를 걸지 않는다 — 판째로 지워지면 화면이 뭉개진다.)

지켜야 할 것

- **답지에 없는 글자는 답하지 마라.** 그림 안에 있는 간판·책등·이정표 글자,
  화살표, 아이콘, 도표는 우리가 찾는 것이 아니다.
- 자리는 **글자에만** 맞춰라. 옆의 화살표나 그림을 끌어들이지 마라.
- 라벨 안에 화살표가 끼어 있어도(「제도 → 경험」) **이어 붙이려 애쓰지 마라.**
  떨어져 있는 글자 덩어리는 떨어진 채로 두고, 글자가 있는 곳만 감싸면 된다.
- **맨 위 10% 띠(y<10)는 보지 마라.** 거기 제목은 그림이 아니라 발표 화면이
  얹은 것이라 자리를 이미 안다.
- 받침대·판때기 **안에 박힌** 글자도 `missing` 으로 두지 말고 제대로 판정하되,
  `on_panel` 을 `true` 로 표시해라. 상자를 걸지 말지는 이쪽에서 정한다.

JSON 만 출력한다."""

# 원장의 `prompt` 에 `compose()` 가 적어 둔 라벨 줄 — 설명 문장과 앉힐 자리가 있다
_LAB = re.compile(r'라벨\s*(\d+)\s*\(([^)]*)\)\s*:\s*굵게\s*"([^"]*)"'
                  r'(?:\s*/\s*그 아래 작게\s*"([^"]*)")?')


def _labels_of(pid: int, slug: str, no: int) -> List[Dict[str, Any]]:
    """그 장에 넣기로 한 라벨 목록 — **이 단계의 답지다.**

    `label_heads`(굵은 소제목)와 `label_says`(몇 번째 문장에서 말하나)는 원장에
    칸으로 들어 있고, **설명 문장과 앉힐 자리**는 `prompt` 안에 한 줄씩 적혀
    있다(`s3a_imgprompt.compose`). 둘을 합쳐 답지를 세운다.

    ★ 덱은 `10_덱/deck.json` 에서 읽는다. `s8-assemble` 캐시에는 `slides` 가
      없다 — `s13b_order._label_hint` 가 그것을 읽다가 **늘 빈 손으로 돌아왔다.**
    """
    deck = (ws.read_json(ws.deck_path(pid, slug), {}) or {}).get("slides") or []
    did = next((s.get("data_id") for s in deck if int(s.get("no", 0)) == no), None)
    if not did:
        return []
    one = (ws.load_ledger(pid, slug).get("by_id") or {}).get(did) or {}
    heads = one.get("label_heads") or []
    if not heads:
        return []
    says = one.get("label_says") or []
    body = {int(m.group(1)): (m.group(2), m.group(4) or "")
            for m in _LAB.finditer(one.get("prompt") or "")}
    out = []
    for k, h in enumerate(heads, 1):
        spot, desc = body.get(k, ("", ""))
        out.append({"i": k, "head": h, "body": desc, "spot": spot,
                    "say": int(says[k - 1]) if k <= len(says) else 0})
    return out


def _grid(pid: int, slug: str, no: int, still: Path) -> Path:
    """스틸에 백분율 격자를 얹는다 — 픽셀 도구가 ffmpeg 로 그린다."""
    d = ws.cache_dir(pid, slug) / f"_zones-{no:03d}"
    d.mkdir(parents=True, exist_ok=True)
    out = d / "grid.png"
    if out.is_file() and out.stat().st_mtime >= still.stat().st_mtime:
        return out
    t = motion.tool()
    if not t:
        raise RuntimeError("모션 도구를 찾지 못했습니다")
    cv = Path(t["dir"]) / "zone_cv.py"
    r = subprocess.run([t["python"], str(cv), "grid", str(still), "-o", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"격자를 못 그렸습니다: {(r.stdout or r.stderr or '')[:200]}")
    return out


def _tighten(pid: int, slug: str, no: int, still: Path,
             items: List[Dict[str, Any]]) -> Dict[Any, Dict[str, Any]]:
    """대충 자리들을 한꺼번에 조인다 — 픽셀 일은 딴 파이썬이 한다.

    ★ 앱의 `.venv-app` 에는 numpy·Pillow 가 없다(`s13_motion._python` 주석).
      그래서 **JSON 파일 하나**를 사이에 두고 넘긴다.
    """
    if not items:
        return {}
    t = motion.tool()
    if not t:
        raise RuntimeError("모션 도구를 찾지 못했습니다")
    d = ws.cache_dir(pid, slug) / f"_zones-{no:03d}"
    d.mkdir(parents=True, exist_ok=True)
    job, res = d / "job.json", d / "tight.json"
    job.write_text(json.dumps({"items": [
        {"id": it["id"], "still": str(still), "box": it["box"],
         "fit": it.get("fit") or "rows"}
        for it in items]}, ensure_ascii=False), encoding="utf-8")
    cv = Path(t["dir"]) / "zone_cv.py"
    r = subprocess.run([t["python"], str(cv), "tighten", str(job), "-o", str(res)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    if r.returncode != 0 or not res.is_file():
        raise RuntimeError(f"상자를 못 조였습니다: {(r.stdout or r.stderr or '')[:200]}")
    return {x.get("id"): x
            for x in (json.loads(res.read_text(encoding="utf-8")).get("items") or [])}


def _pct_to_px(r: Dict[str, Any], W: int, H: int) -> Optional[Dict[str, int]]:
    """백분율 → 픽셀. 값이 안 들어왔으면 None."""
    w = float(r.get("w") or 0) * W / 100.0
    h = float(r.get("h") or 0) * H / 100.0
    if w < 8 or h < 6:
        return None
    x = max(0.0, min(W - 8, float(r.get("x") or 0) * W / 100.0))
    y = max(0.0, min(H - 6, float(r.get("y") or 0) * H / 100.0))
    return {"x": int(x), "y": int(y),
            "w": int(min(w, W - x)), "h": int(min(h, H - y))}


def _no_overlap(boxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """**상자끼리 겹치지 않게** 정리한다.

    라벨마다 따로 자리를 찾으므로 이웃 라벨의 줄을 같이 잡는 일이 생기고, 그러면
    상자 둘이 같은 글자를 물어 `remaster` 가 그 자리를 두 번 지웠다 올린다 —
    획이 두 겹으로 뜨거나 한쪽이 남는다.

    푸는 법은 겹치는 꼴에 따라 둘이다.
      같은 줄에서 겹치면   하나로 **합친다** (같은 글자를 가리키고 있다)
      위아래로 겹치면      겹친 만큼 **서로 물러선다** (줄 사이 경계로 가른다)
    """
    out: List[Dict[str, Any]] = []
    for b in sorted(boxes, key=lambda z: (z["y"], z["x"])):
        eaten = False
        for a in out:
            if a["kind"] != b["kind"]:
                continue
            ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            u = a["w"] * a["h"] + b["w"] * b["h"] - inter
            # 거의 같은 자리면 **같은 것을 두 번 찾은 것**이다 — 하나로 합친다
            if u and inter / u > 0.5:
                x1 = max(a["x"] + a["w"], b["x"] + b["w"])
                y1 = max(a["y"] + a["h"], b["y"] + b["h"])
                a["x"] = min(a["x"], b["x"]); a["y"] = min(a["y"], b["y"])
                a["w"] = x1 - a["x"]; a["h"] = y1 - a["y"]
                if a.get("at") is None:
                    a["at"] = b.get("at")
                eaten = True
                break
            # ★ 그 밖에는 **합치지 않는다.** 나란히 선 딴 라벨을 합치면 상자
            #   하나가 라벨 둘을 걸친다(실측: 6개가 3개로 줄었다). 덜 겹친 축으로
            #   서로 물러서게 해 경계를 가른다.
            if iy <= ix:
                mid = (max(a["y"], b["y"]) + min(a["y"] + a["h"], b["y"] + b["h"])) // 2
                if a["y"] < b["y"]:
                    a["h"] = max(8, mid - a["y"])
                    b["h"] = max(8, b["y"] + b["h"] - mid); b["y"] = mid
                else:
                    b["h"] = max(8, mid - b["y"])
                    a["h"] = max(8, a["y"] + a["h"] - mid); a["y"] = mid
            else:
                mid = (max(a["x"], b["x"]) + min(a["x"] + a["w"], b["x"] + b["w"])) // 2
                if a["x"] < b["x"]:
                    a["w"] = max(8, mid - a["x"])
                    b["w"] = max(8, b["x"] + b["w"] - mid); b["x"] = mid
                else:
                    b["w"] = max(8, mid - b["x"])
                    a["w"] = max(8, a["x"] + a["w"] - mid); a["x"] = mid
        if not eaten:
            out.append(b)
    return out


def run_one(pid: int, slug: str, no: int, p: ClaudeProvider) -> Dict[str, Any]:
    """그 장 하나 — 상자 목록과 라벨 판정을 돌려준다."""
    labs = _labels_of(pid, slug, no)
    if not labs:
        return {"no": no, "boxes": [], "labels": [], "skip": "원장에 라벨이 없음"}
    still = motion.still_of(pid, slug, no)
    if still is None:
        return {"no": no, "boxes": [], "labels": [], "skip": "스틸 없음"}
    sc = motion.scene_of(pid, slug, no)
    W, H = int(sc["W"]), int(sc["H"])
    cues = sc["cues"]

    lines = []
    for L in labs:
        s = f'{L["i"]}. 굵게 "{L["head"]}"'
        if L["body"]:
            s += f' / 그 아래 작게 "{L["body"]}"'
        # ★ 「넣기로 한 자리」(왼쪽 위 …)는 **주지 않는다.** 주면 화면을 재는
        #   대신 그 말을 좌표로 옮겨 적는다 — 실측(2026-09-15, 54_1-1 4장):
        #   라벨 셋이 `w=307 h=86` 으로 **완전히 같은 상자**를 받았고 x 도
        #   153/1420 처럼 되풀이됐다. 여섯 중 넷이 빈 벽을 가리켰다.
        #   그림을 만들 때 쓴 지시일 뿐, 실제로 거기 앉았다는 보장도 없다.
        lines.append(s)
    intro = (f"슬라이드 {no}번 · 라벨 {len(labs)}개\n\n"
             "── 이 그림에 넣기로 한 라벨(답지) ──\n" + "\n".join(lines))
    if cues:
        intro += ("\n\n── 이 장의 내레이션 ──\n"
                  + "\n".join(f"{i}. {c['text']}" for i, c in enumerate(cues, 1)))

    raw = p.vision(SYSTEM, [{"text": f"슬라이드 {no}번", "image": _grid(pid, slug, no, still)}],
                   schema=SCHEMA, intro=intro)
    got = {int(r["i"]): r for r in (raw.get("labels") or []) if r.get("i")}

    # 대충 자리를 모아 한 번에 조인다
    #
    # ★ **맨 위 제목은 비전에게 묻지 않는다.** 그 글자는 그림이 아니라 발표 화면
    #   (`render/slides.py`)이 얹은 것이고, 늘 같은 띠에 앉는다. 실측하면 지금의
    #   픽셀 제안이 제목만큼은 **100%** 잡는다 — 물어서 돈을 쓸 이유가 없다.
    #   그 띠를 통째로 대충 자리로 주고 잉크만 찾게 한다.
    jobs = [{"id": "_title", "fit": "both",
             "box": {"x": 0, "y": 0, "w": W, "h": int(H * 0.11)}}]
    report = []
    for L in labs:
        r = got.get(L["i"]) or {}
        v = r.get("verdict") or "missing"
        L["verdict"], L["read"] = v, (r.get("read") or "").strip()
        L["panel"] = bool(r.get("on_panel"))
        if v == "missing":
            continue
        if (b := _pct_to_px(r, W, H)):
            jobs.append({"id": L["i"], "box": b})
        else:
            L["verdict"] = "missing"
    tight = _tighten(pid, slug, no, still, jobs)

    boxes: List[Dict[str, Any]] = []
    # 제목 — 장이 시작할 때 뜬다(첫 문장). `s13b_order` 도 같은 규칙을 쓴다.
    for ln in ((tight.get("_title") or {}).get("lines") or []):
        boxes.append({**ln, "kind": "text",
                      "at": cues[0]["at"] if cues else 0.0, "until": None})
    for L in labs:
        v = L["verdict"]
        t = tight.get(L["i"]) or {}
        # 말하는 문장의 시작 시각 — 한 라벨의 줄들은 **같이** 뜬다
        k = L["say"]
        at = cues[k - 1]["at"] if 1 <= k <= len(cues) else None
        if v == "garbled":
            # 깨진 글자는 영상 내내 덮는다. 시각이 없다(`remaster` 가 안 본다).
            if (whole := t.get("all")):
                boxes.append({**whole, "kind": "cover", "at": None, "until": None})
        elif L.get("panel"):
            # ★ **뒤에 판이 깔린 글자에는 상자를 걸지 않는다**(2026-09-15).
            #   글자를 지우려면 그 판까지 같이 건드리게 되고, 그러면 화면이
            #   뭉개진다. 판정은 그대로 보고에 남긴다.
            pass
        elif v in ("found", "different"):
            # ★ **라벨 하나에 상자 하나.** 굵은 소제목과 그 아래 설명을 한 덩어리로
            #   묶는다(2026-09-15 지시 — 「라벨에서 한 줄 한 줄 할 필요는 없다」).
            #   줄마다 쪼개면 씬당 상자가 두 배로 늘고, 라벨 사이에 낀 화살표를
            #   쫓다 오히려 그림에 상자가 붙었다.
            if (whole := t.get("all")):
                boxes.append({**whole, "kind": "text", "at": at, "until": None})
        report.append({"i": L["i"], "head": L["head"], "verdict": v,
                       "read": L["read"], "say": k, "panel": L.get("panel"),
                       "lines": len(t.get("lines") or []), "ok": t.get("ok")})

    motion.fill_times(boxes, cues, float(sc["len"] or 0))
    # 가리기는 시각을 갖지 않는다
    for b in boxes:
        if b["kind"] == "cover":
            b["at"] = b["until"] = None
    return {"no": no, "boxes": boxes, "labels": report}


def _report(pid: int, slug: str, rows: List[Dict[str, Any]]) -> Optional[Path]:
    """검수 보고 — 완성본 폴더에 둔다. 폴더 하나가 사람과의 접점이다."""
    mp4 = motion.target(pid, slug)
    if mp4 is None:
        return None
    out = motion.report_path(mp4)
    bad: List[int] = []
    L = ["# 라벨 검수", "",
         "| 장 | 라벨 | 판정 | 화면에서 읽은 글자 | 상자 | 말하는 문장 |",
         "|---|---|---|---|---|---|"]
    mark = {"found": "정상", "garbled": "**깨짐**", "missing": "**없음**",
            "different": "다름"}
    for r in rows:
        for x in r.get("labels") or []:
            if x["verdict"] in ("garbled", "missing"):
                bad.append(r["no"])
            box = "판 위라 안 검" if x.get("panel") else (
                "가리기" if x["verdict"] == "garbled" else
                ("없음" if x["verdict"] == "missing" else "글자"))
            L.append(f"| {r['no']} | {x['head']} | {mark.get(x['verdict'], x['verdict'])} "
                     f"| {x['read']} | {box} | {x['say'] or '—'} |")
    L += ["", f"다시 그릴 장: {', '.join(str(n) for n in sorted(set(bad))) or '없음'}"]
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def _scenes(job, pid: int, slug: str, mp4: Path) -> Dict[str, Any]:
    """씬 전환 시각과 스틸을 만든다 — `make_picker` 와 **같은 함수**를 쓴다.

    ★ 씬 번호가 한 칸만 어긋나도 상자가 통째로 엉뚱한 장에 붙는다. 그래서 새로
      찾지 않고 도구 쪽 `zone_cv.py scenes` 를 부른다(그쪽이 `make_picker.scenes`
      를 그대로 불러 쓴다).
    """
    t = motion.tool()
    if not t:
        raise RuntimeError("모션 도구를 찾지 못했습니다")
    out = ws.cache_dir(pid, slug) / "_zones-scenes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv = Path(t["dir"]) / "zone_cv.py"
    rc = motion._stream(job, [t["python"], str(cv), "scenes", str(mp4),
                              "-o", str(out)], cwd=t["dir"], timeout=1800)
    if rc != 0 or not out.is_file():
        raise RuntimeError(f"씬을 찾지 못했습니다 (종료 {rc})")
    d = json.loads(out.read_text(encoding="utf-8"))
    return {"video": mp4.name, "W": d["W"], "H": d["H"],
            "scenes": [{"i": s["i"], "cut": s["cut"], "len": s["len"], "boxes": []}
                       for s in d["scenes"]]}


def run(job, pid: int, slug: str, project: Dict[str, Any], *,
        only: List[int] | None = None, apply: bool = False) -> Dict[str, Any]:
    """장마다 라벨 자리를 찾아 **`<stem>-zones.gen.json`** 에 놓는다.

    ★ **기본은 `zones.json` 을 건드리지 않는다.** 그 파일은 사람이 고친 것이고,
      이 단계는 몇 번이고 다시 돌 수 있어야 한다. 찾은 상자는 딴 파일에 두고,
      지정기가 그것을 밑그림으로 깐다(`s13_motion.run_picker`). 사람이 고쳐
      내려받은 것이 비로소 `zones.json` 이 된다.
    ★ `apply=True` 면 `zones.json` 에도 **장마다 하나씩** 써 넣는다. 화면의
      장면 편집기로 바로 이어서 보고 싶을 때만 쓴다.
    """
    cfg = config.load()
    mp4 = motion.target(pid, slug)
    if mp4 is None:
        raise RuntimeError("완성 mp4 가 없습니다")
    z = motion._load_zones(mp4)
    if not z.get("scenes"):
        # ★ **지정기보다 먼저 돌 수 있어야 한다.** 예전에는 여기서 「zones.json 이
        #   없습니다」 하고 멈췄는데, 그 파일은 지정기를 돌리고 사람이 내려받아야
        #   생긴다 — 그러면 0단계가 1단계 뒤에만 도는 앞뒤 안 맞는 절차가 된다.
        #   씬 목록은 `make_picker` 와 **같은 함수**로 직접 만든다(스틸도 같이).
        job.add_log("씬을 먼저 찾습니다 — 지정기를 아직 안 돌렸습니다")
        z = _scenes(job, pid, slug, mp4)

    # ★ 씬 ↔ 슬라이드 1:1 이 성립하는 덱에서만 돈다. 원고 덱은 한 장 안에서
    #   줄이 뜨며 컷이 여럿 생겨 씬이 갈라진다 — 그러면 상자가 엉뚱한 장에 붙는다.
    v = motion.cached_data(pid, slug, "s12-video") or {}
    if v.get("cuts") and v.get("slides") and int(v["cuts"]) != int(v["slides"]):
        raise RuntimeError(f"씬({v['cuts']})과 장({v['slides']})이 1:1 이 아닙니다 — "
                           "이 덱에는 아직 쓸 수 없습니다")

    nos = only or [int(s.get("i", -1)) + 1 for s in z["scenes"]]
    skip_done = {int(s.get("i", -1)) + 1 for s in z["scenes"] if s.get("done")}
    nos = [n for n in nos if n not in skip_done]
    if not nos:
        raise RuntimeError("볼 장이 없습니다")

    if apply and motion.zones_path(mp4).is_file():
        bak = motion.zones_path(mp4).with_name(mp4.stem + "-zones.bak.json")
        shutil.copy2(motion.zones_path(mp4), bak)
        job.add_log(f"물러 둘 것: {bak.name}")

    p = ClaudeProvider(
        model=(project.get("models") or cfg["models"]).get("caption")
              or cfg["models"]["caption"],
        effort=cfg["effort"].get("caption", "medium"),
        allowed_tools=[],
        max_turns=int(cfg.get("caption_turns", 4)),
        budget_usd=cfg["budget_usd"]["per_stage"],
        on_activity=lambda s: job.progress(0, len(nos), s),
    )

    rows, warn, cost, nbox = [], [], 0.0, 0
    job.add_log(f"{len(nos)}장 · 원장의 라벨을 그림에서 찾습니다")
    for i, no in enumerate(nos, 1):
        job.progress(i, len(nos), f"{no}장")
        try:
            r = run_one(pid, slug, no, p)
        except Exception as e:                       # noqa: BLE001
            warn.append(f"{no}장: {type(e).__name__}: {str(e)[:100]}")
            job.add_log(f"  {no}장 실패 — 계속합니다")
            continue
        cost += p.last_cost_usd
        if r.get("skip"):
            job.add_log(f"  {no}장 건너뜀 — {r['skip']}")
            continue
        rows.append(r)
        nbox += len(r["boxes"])
        if apply:
            motion.save_scene(pid, slug, no, r["boxes"])
        bad = [x for x in r["labels"] if x["verdict"] in ("garbled", "missing")]
        job.add_log(f"  {no}장 · 라벨 {len(r['labels'])}개 → 상자 {len(r['boxes'])}개"
                    + (f"  ⚠ {len(bad)}개 문제" if bad else ""))

    # 찾은 상자는 **언제나** 따로 남긴다 — 지정기가 이것을 밑그림으로 깐다
    gen = motion.gen_path(mp4)
    by = {r["no"]: r["boxes"] for r in rows}
    for sc in z["scenes"]:
        b = by.get(int(sc.get("i", -1)) + 1)
        if b is not None:
            sc["boxes"] = [{"x": x["x"], "y": x["y"], "w": x["w"], "h": x["h"],
                            "kind": x["kind"],
                            "t": motion._mmss(x["at"]) + "~" +
                                 (motion._mmss(x["until"]) if x.get("until") is not None else "")
                                 if x.get("at") is not None and x["kind"] != "cover" else ""}
                           for x in b]
    gen.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8")
    job.add_log(f"찾은 상자 → {gen.name}  (지정기가 이것을 깝니다)")

    rep = _report(pid, slug, rows)
    job.add_log(f"{len(rows)}장 · 상자 {nbox}개 · ${cost:.2f}")
    if rep:
        job.add_log(f"검수 보고 → {rep.name}")
    return {"scenes": len(rows), "boxes": nbox, "cost_usd": round(cost, 4),
            "report": str(rep) if rep else None, "warnings": warn}
