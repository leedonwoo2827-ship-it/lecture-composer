# -*- coding: utf-8 -*-
"""S13 모션 리마스터 — 완성 mp4 를 **재료로** 다시 굽는다.

    11_완성/19-img.mp4        ← S12 가 낸 완성본. 여기서는 **읽기만** 한다
        ↓  make_picker.py
    11_완성/19-img-마스크지정기.html
        ↓  사람이 상자와 시간을 찍고 zones.json 을 내려받는다
    11_완성/19-img-zones.json  ← 화면의 «JSON 불러오기» 로 들어온다
        ↓  remaster.py
    11_완성/19-img-motion.mp4  ← **새 파일**

★ **이 앱 안에 모션 엔진을 넣지 않는다.** 도구는 `motion-remaster` 폴더에 따로
  살고(`showcase.config.local.json` 의 `motion.tool_dir`), 여기는 완성본을 넘기고
  결과를 되받기만 한다. 이유는 `09_이미지` 를 이미지 스튜디오와 주고받는 것과
  같다 — 두 프로세스를 코드로 이어 붙이면 한쪽이 죽었을 때 어디가 죽었는지
  모르게 되고, 접점이 폴더 하나면 사람이 눈으로 볼 수 있다.

★ **레지스트리 스테이지가 아니다.** 렌더링에서 끝나는 영상도 있다. DAG 에 넣으면
  그런 프로젝트의 현황판에 영영 「안 함」 한 칸이 남고 "다음 할 일" 이 계속
  조른다. 모션은 **하고 싶을 때 하는 뒷단계**라서 화면만 갖는다.

★ 사람이 끼는 자리가 한 번 있다 — 상자 찍기. 그 앞뒤로 일을 두 동강 낸다
  (지정기 만들기 / 굽기). 자동으로 이어 붙일 수 있는 자리가 아니다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config
from core import workspace as ws
from pipeline.registry import cached_data

# 시안은 앞 95초만 — 한 씬(45초)이 통째로 들어가고 2분이면 끝난다
PREVIEW_SEC = 95

# 확정값. 사람이 달리 말하지 않으면 이 줄 그대로 굽는다.
# ★ 손으로 고른 값이다(2026-08-15). 빛의 세기·주기·글자 뜨는 속도가 여기 다 있다.
#   바꿔야 할 때는 화면의 「값」 칸에 적는다 — 코드를 고치지 않는다.
VALS: List[str] = [
    "--text-sheen", "1.4", "--text-sheen-dur", "2.0",
    "--text-sheen-amp", "0.45", "--text-sheen-wide", "0.11",
    "--text-dur", "1.25", "--text-gap", "0.40",
    "--out-dur", "0.45", "--drift", "0", "--pan", "0",
]

# 영상 길이와 오디오 길이가 이보다 벌어지면 잘린 내레이션이 있다는 뜻이다
DUR_TOL = 0.1


# ── 도구 ───────────────────────────────────────────────────────────────────
def _python(m: Dict[str, Any]) -> str:
    """도구를 돌릴 파이썬.

    ★ **`sys.executable` 이 기본이면 안 된다.** 이 앱은 `.venv-app` 으로 도는데
      거기에는 numpy 가 없다(넣을 이유도 없다 — 이 앱은 배열 계산을 안 한다).
      도구는 numpy·Pillow 를 쓰므로 **PATH 의 파이썬**을 먼저 본다. 그것도 아니면
      설정에 직접 적는다.
    """
    if p := (m.get("python") or "").strip():
        return p
    return shutil.which("python") or shutil.which("py") or sys.executable


_deps_cache: Dict[str, bool] = {}


def has_deps(py: str) -> bool:
    """그 파이썬이 numpy·Pillow 를 갖고 있나 — **굽기 전에** 본다.

    ★ 30분을 태우고 나서 `ModuleNotFoundError` 를 보여 주지 않으려는 것이다.
      한 번 재고 기억한다(화면을 열 때마다 프로세스를 띄우면 느리다).
    """
    if py in _deps_cache:
        return _deps_cache[py]
    try:
        r = subprocess.run([py, "-c", "import numpy, PIL"],
                           capture_output=True, timeout=30)
        ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        ok = False
    _deps_cache[py] = ok
    return ok


# ★ 도구는 이제 **이 프로젝트 안에** 산다(`tools/motion/`). 예전에는 옆 폴더
#   (`260815-motion-remaster`)를 가리켰는데, 그 폴더를 지우면 모션이 통째로
#   죽는다(2026-08-16: "저 폴더는 결국 지울 겁니다"). 설정으로 딴 데를 가리킬
#   수는 있지만, 아무것도 안 적어도 그냥 돌아야 한다.
BUNDLED = Path(__file__).resolve().parent.parent / "tools" / "motion"


def tool() -> Optional[Dict[str, str]]:
    """모션 도구가 어디 있나. 없으면 None — 화면이 「폴더를 알려 주세요」를 띄운다."""
    m = (config.load().get("motion") or {})
    d = (m.get("tool_dir") or "").strip()
    root = Path(d) if d else BUNDLED
    if not (root / "remaster.py").is_file() or not (root / "make_picker.py").is_file():
        return None
    return {
        "dir": str(root),
        "picker": str(root / "make_picker.py"),
        "remaster": str(root / "remaster.py"),
        "python": _python(m),
    }


def _ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def durations(p: Path) -> Dict[str, Optional[float]]:
    """영상 길이와 오디오 길이를 따로 잰다 — **두 값이 같아야 성공이다.**

    ★ 원본은 영상 트랙이 오디오보다 1.8초쯤 길다(마지막 장이 소리보다 조금 더
      머문다). 모션판은 `-shortest` 로 오디오에 맞춰 끝나므로 둘이 같아진다.
      안 같으면 내레이션이 잘린 것이다.
    """
    ff = _ffprobe()
    if not ff or not p.is_file():
        return {"video": None, "audio": None}

    def one(args: List[str]) -> Optional[float]:
        try:
            r = subprocess.run([ff, "-v", "error", *args,
                                "-of", "csv=p=0", str(p)],
                               capture_output=True, text=True, timeout=60)
            return round(float((r.stdout or "").strip().splitlines()[0]), 2)
        except Exception:  # noqa: BLE001
            return None

    return {"video": one(["-show_entries", "format=duration"]),
            "audio": one(["-select_streams", "a:0",
                          "-show_entries", "stream=duration"])}


# ── 자리 ───────────────────────────────────────────────────────────────────
def verdict(v: Optional[float], a: Optional[float],
            preview: bool) -> Optional[bool]:
    """길이 판정 — 통과 / 실패 / **판정 안 함**.

    ★ 셋째 값이 필요하다. 시안은 `--limit` 이 영상만 정확히 자르고 오디오는
      복사본이라 패킷 경계에서 끝나므로 두 값이 늘 다르다. 그것을 「실패」로
      찍으면 매번 틀린 경고가 뜨고, 틀린 경고는 진짜 경고까지 같이 죽인다.
      그래서 시안은 `None` — 숫자만 보여 주고 판정은 하지 않는다.
    """
    if preview or v is None or a is None:
        return None
    return abs(v - a) <= DUR_TOL


def target(pid: int, slug: str) -> Optional[Path]:
    """무엇을 재료로 삼나 — **S12 가 낸 그 파일.**

    ★ 폴더를 훑어 `*.mp4` 를 아무거나 집지 않는다. 모션 결과도 같은 폴더에 mp4 로
      쌓이므로(`-motion.mp4`), 훑으면 **자기가 구운 것을 다시 재료로 삼는** 일이
      생긴다. 스테이지 캐시가 파일 이름을 정확히 들고 있으니 그것을 읽는다.
    """
    dist = ws.step_dir(pid, slug, "dist", create=False)
    name = ((cached_data(pid, slug, "s12-video") or {}).get("file") or "").strip()
    if name:
        p = dist / name
        if p.is_file():
            return p
    # 캐시가 지워졌을 때 — 이름 규칙으로만 찾는다(-motion·-시안 은 제외된다)
    a = ws.ascii_slug(slug)
    for cand in (dist / f"{a}-img.mp4", dist / f"{a}.mp4"):
        if cand.is_file():
            return cand
    return None


def _slides_dir(pid: int, slug: str, mp4: Path) -> Optional[Path]:
    """슬라이드 원본이 있는 곳 — 씬 수를 검산하는 재료다."""
    dist = mp4.parent
    for cand in (dist / ws.ascii_slug(slug) / ws.ASSETS,
                 dist / mp4.stem / ws.ASSETS,
                 dist / ws.ASSETS):
        if cand.is_dir():
            return cand
    return None


def _free(p: Path) -> Path:
    """같은 이름이 있으면 `-2`, `-3` … **덮어쓰지 않는다.**

    ★ 이전 모션판은 산출물이지 재료가 아니지만, 몇십 분을 태운 파일이다.
      새로 구운 것이 마음에 안 들 때 견줄 것이 없으면 그 시간이 통째로 날아간다.
    """
    if not p.exists():
        return p
    for i in range(2, 100):
        q = p.with_name(f"{p.stem}-{i}{p.suffix}")
        if not q.exists():
            return q
    raise RuntimeError(f"이름이 다 찼습니다: {p.name}")


def picker_path(mp4: Path) -> Path:
    return mp4.with_name(mp4.stem + "-마스크지정기.html")


def zones_path(mp4: Path) -> Path:
    return mp4.with_name(mp4.stem + "-zones.json")


def gen_path(mp4: Path) -> Path:
    """기계가 찾아 둔 상자 — 사람이 손댄 `zones.json` 과 **파일을 가른다.**

    같은 파일에 쓰면 다시 돌릴 때마다 사람이 고친 것을 덮는다. 지정기가 이것을
    밑그림으로 깔고, 사람이 고쳐 내려받은 것이 `zones.json` 이 된다.
    """
    return mp4.with_name(mp4.stem + "-zones.gen.json")


def report_path(mp4: Path) -> Path:
    return mp4.with_name(mp4.stem + "-라벨검수.md")


# ── 상태 ───────────────────────────────────────────────────────────────────
def _count(zpath: Path) -> Dict[str, int]:
    try:
        z = json.loads(zpath.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {"scenes": 0, "boxes": 0}
    sc = z.get("scenes") or []
    return {"scenes": len(sc),
            "boxes": sum(len(s.get("boxes") or []) for s in sc)}


def state(pid: int, slug: str) -> Dict[str, Any]:
    """모션 화면이 그리는 것 전부. **어디까지 왔나** 한 눈에."""
    t = tool()
    mp4 = target(pid, slug)
    out: Dict[str, Any] = {
        "tool_dir": (t or {}).get("dir") or "",
        "python": (t or {}).get("python") or "",
        "deps": bool(t) and has_deps(t["python"]),
        "ffprobe": bool(_ffprobe()),
        "mp4": None, "picker": None, "zones": None, "gen": None,
        "report": "", "bakes": [],
        "slides": 0, "expect_scenes": 0, "note": "",
    }
    if mp4 is None:
        out["note"] = "아직 완성 mp4 가 없습니다 — 영상 렌더링을 먼저 하세요."
        return out

    d = durations(mp4)
    out["mp4"] = {"name": mp4.name, "path": str(mp4),
                  "mb": round(mp4.stat().st_size / 1e6, 1), "sec": d["video"]}

    if (sd := _slides_dir(pid, slug, mp4)) is not None:
        n = sum(1 for f in sd.glob("*.png"))
        out["slides"] = n
        # ★ **표지 1장은 영상에 없다.** 그림 29장이면 씬 28개가 맞다.
        out["expect_scenes"] = max(0, n - 1)

    pk = picker_path(mp4)
    if pk.is_file():
        out["picker"] = {"name": pk.name, "path": str(pk),
                         "mb": round(pk.stat().st_size / 1e6, 1)}

    zp = zones_path(mp4)
    if zp.is_file():
        out["zones"] = {"name": zp.name, "path": str(zp), **_count(zp)}

    # 기계가 찾아 둔 상자 — 사람이 고친 `zones.json` 과 **파일이 다르다**
    gp = gen_path(mp4)
    if gp.is_file():
        out["gen"] = {"name": gp.name, "path": str(gp), **_count(gp)}
    rp = report_path(mp4)
    if rp.is_file():
        out["report"] = rp.name

    # 구워 둔 것들 — 시안이든 완성이든 같은 자리에 쌓인다
    for f in sorted(mp4.parent.glob(f"{mp4.stem}-*.mp4")):
        dd = durations(f)
        prev = "시안" in f.name
        out["bakes"].append({
            "name": f.name, "path": str(f),
            "mb": round(f.stat().st_size / 1e6, 1),
            "video": dd["video"], "audio": dd["audio"],
            "ok": verdict(dd["video"], dd["audio"], prev),
            "preview": prev,
            "url": f"/api/projects/{pid}/file/{ws.STEPS['dist'][0]}/{f.name}",
        })
    return out


# ── 실행 ───────────────────────────────────────────────────────────────────
def _need_deps(t: Dict[str, str]) -> None:
    """★ 30분을 태운 뒤에 «numpy 가 없습니다» 를 보는 일이 없게, 앞에서 막는다."""
    if has_deps(t["python"]):
        return
    raise RuntimeError(
        f"{t['python']} 에 numpy·Pillow 가 없습니다 — "
        "그 둘이 있는 파이썬 경로를 showcase.config.local.json 의 "
        "motion.python 에 적어 주세요")


# ── 스토리보드 정리 — 장 하나씩 ────────────────────────────────────────────
# ★ 이 묶음이 있는 이유. 상자를 찍는 자리(지정기)와 대본을 보는 자리(덱)가 갈려
#   있어서, **말하는 차례를 모르는 채로** 상자를 찍었다. `remaster` 는 시각이
#   비면 상자를 위→아래로 띄우는데, 31장 중 25장이 한 줄에 상자를 좌우로 둘씩
#   두고 있어 그 정렬로는 차례가 정해지지 않는다(2026-08-16 실측).
#   그래서 **자막 문장을 옆에 놓고 차례를 정하는** 화면이 필요하고, 아래 셋이
#   그 화면의 재료다.

def stills_dir(mp4: Path) -> Path:
    """지정기가 뽑아 둔 원본 해상도 스틸 — `_<이름>-stills/s00.png …`"""
    return mp4.with_name(f"_{mp4.stem}-stills")


def still_of(pid: int, slug: str, no: int) -> Optional[Path]:
    """그 장의 스틸. 씬 k ↔ 슬라이드 k 라 `s{no-1:02d}.png` 다."""
    mp4 = target(pid, slug)
    if mp4 is None or no < 1:
        return None
    p = stills_dir(mp4) / f"s{no - 1:02d}.png"
    return p if p.is_file() else None


def _cues(pid: int, slug: str, no: int) -> List[Dict[str, Any]]:
    """그 장의 자막 문장 — 시각과 글이 **같이** 온다.

    ★ 화면이 SRT 를 따로 읽지 않게 서버가 붙여 보낸다. 시각과 문장이 갈라지면
      상자 옆에 붙은 글이 딴 말을 하게 되고, 그러면 차례를 볼 수가 없다.
    """
    p = ws.step_dir(pid, slug, "subtitle", create=False) / f"{no:03d}.srt"
    if not p.is_file():
        return []
    out: List[Dict[str, Any]] = []
    for blk in re.split(r"\n\n+", p.read_text(encoding="utf-8").strip()):
        L = [x for x in blk.strip().split("\n") if x.strip()]
        if len(L) < 3:
            continue
        m = re.match(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> "
                     r"(\d\d):(\d\d):(\d\d),(\d\d\d)", L[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        out.append({"at": round(g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, 2),
                    "until": round(g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, 2),
                    "text": " ".join(L[2:]).strip()})
    return out


def _load_zones(mp4: Path) -> Dict[str, Any]:
    zp = zones_path(mp4)
    if zp.is_file():
        try:
            return json.loads(zp.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _mmss(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _parse_t(s: str) -> tuple:
    """`"0:04.4~0:17.4"` → (4.4, 17.4). 못 읽으면 (None, None)."""
    def one(x: str) -> Optional[float]:
        x = (x or "").strip()
        if not x:
            return None
        m = re.match(r"^(?:(\d+):)?([\d.]+)$", x)
        if not m:
            return None
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    parts = re.split(r"[~\-–—]", str(s or ""), maxsplit=1)
    return (one(parts[0]) if parts else None,
            one(parts[1]) if len(parts) > 1 else None)


def scene_of(pid: int, slug: str, no: int) -> Dict[str, Any]:
    """그 장의 상자 · 시각 · 자막 문장. 화면이 이것 하나로 그린다.

    ★ 상자는 **등장 시각 순**으로 돌려준다. `remaster` 가 `at` 으로 다시 정렬하므로
      (`tl.sort(key=lambda d: (d["at"], …))`) 화면에 보이는 차례와 영상에 나오는
      차례가 같아야 한다. 시각이 없는 상자는 뒤로 보내되 위→아래를 지킨다.
    """
    mp4 = target(pid, slug)
    out: Dict[str, Any] = {"no": no, "W": 1920, "H": 1080, "len": 0.0,
                           "boxes": [], "cues": _cues(pid, slug, no),
                           "still": None, "has_zones": False, "mp4": False}
    if mp4 is None:
        return out
    # ★ 영상은 있는데 스틸이 아직 없는 것과, 영상 자체가 없는 것은 **다르다.**
    #   앞은 「지정기 만들기」를 눌러야 하는 상태이고 뒤는 여기서 할 일이 없다.
    #   가르지 않으면 화면이 둘 다 조용히 사라져, 사람이 모션 화면까지 가서야
    #   무엇을 눌러야 하는지 알게 된다(2026-08-17).
    out["mp4"] = True
    if still_of(pid, slug, no) is not None:
        out["still"] = f"/api/projects/{pid}/motion/still/{no}"

    z = _load_zones(mp4)
    out["W"], out["H"] = int(z.get("W") or 1920), int(z.get("H") or 1080)
    sc = next((s for s in (z.get("scenes") or []) if int(s.get("i", -1)) + 1 == no), None)
    if sc is None:
        return out
    out["has_zones"] = True
    out["len"] = round(float(sc.get("len") or 0), 2)
    out["done"] = bool(sc.get("done"))
    # ★ **어디까지 봤나.** 31장을 한자리에서 다 볼 수 없고, 어제 어디서 멈췄는지가
    #   파일에 남아야 오늘 이어서 본다. 상자가 있는 장만 센다 — 표지·맺음은
    #   상자가 없어 볼 것이 없다.
    todo = [s for s in (z.get("scenes") or []) if (s.get("boxes") or [])]
    out["done_n"] = sum(1 for s in todo if s.get("done"))
    out["todo_n"] = len(todo)

    rows = []
    for b in (sc.get("boxes") or []):
        at, until = _parse_t(b.get("t") or "")
        rows.append({"x": int(b["x"]), "y": int(b["y"]),
                     "w": int(b["w"]), "h": int(b["h"]),
                     "kind": b.get("kind") or "text",
                     "at": at, "until": until})
    rows.sort(key=lambda r: (r["at"] is None, r["at"] or 0, r["y"], r["x"]))
    out["boxes"] = rows
    return out


def save_scene(pid: int, slug: str, no: int, boxes: List[Dict[str, Any]],
               done: Optional[bool] = None) -> Dict[str, Any]:
    """**그 장의 상자만** 갈아 끼운다. 나머지 씬은 손대지 않는다.

    ★ 파일 전체를 화면이 들고 있다 통째로 쓰면 사고가 난다 — 2026-08-16 에 그렇게
      해서, 채워 둔 시각 186개가 사람이 올린 옛 파일에 통째로 덮였다. 서버가 읽어
      그 씬만 바꾸고 즉시 쓴다.
    """
    mp4 = target(pid, slug)
    if mp4 is None:
        raise RuntimeError("완성 mp4 가 없습니다")
    z = _load_zones(mp4)
    if not z.get("scenes"):
        raise RuntimeError("zones.json 이 없습니다 — 지정기를 먼저 돌리세요")

    sc = next((s for s in z["scenes"] if int(s.get("i", -1)) + 1 == no), None)
    if sc is None:
        raise RuntimeError(f"{no}장에 해당하는 씬이 없습니다")

    W, H = int(z.get("W") or 1920), int(z.get("H") or 1080)
    fresh = []
    for b in boxes:
        x = max(0, min(W - 8, int(b.get("x", 0))))
        y = max(0, min(H - 8, int(b.get("y", 0))))
        w = max(8, min(W - x, int(b.get("w", 0))))
        h = max(8, min(H - y, int(b.get("h", 0))))
        # ★ kind 는 `text` 만 쓴다 — 그림 위에 걸면 자국이 남는다(확인된 결론).
        #   **`cover` 하나가 예외다.** 깨져 나온 글자를 영상 내내 덮으라고 거는
        #   상자인데, 여기서 `text` 로 떨어뜨리면 덮으라고 건 그 글자를 오히려
        #   다시 띄운다 — 지정기와 `remaster` 는 이미 제대로 다루고 앱만 떨어
        #   뜨리고 있었다.
        kind = b.get("kind") if b.get("kind") in ("text", "art", "sheen", "cover") \
            else "text"
        at, until = b.get("at"), b.get("until")
        t = ""
        # 가리기는 시각을 갖지 않는다 — 처음부터 끝까지 덮인다(`remaster.zone_build`
        # 가 `parse_span` 앞에서 건너뛴다). 시각이 실려 오면 버린다.
        if kind != "cover" and at is not None:
            t = _mmss(at) + "~" + (_mmss(until) if until is not None else "")
        fresh.append({"x": x, "y": y, "w": w, "h": h, "kind": kind, "t": t})
    sc["boxes"] = fresh
    if done is not None:
        sc["done"] = bool(done)

    zones_path(mp4).write_text(json.dumps(z, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    return {"ok": True, "no": no, "boxes": len(fresh),
            "timed": sum(1 for b in fresh if b["t"]),
            "done": bool(sc.get("done"))}


def fill_times(boxes: List[Dict[str, Any]], cues: List[Dict[str, Any]],
               scene_len: float, *, gap: float = 0.40) -> List[Dict[str, Any]]:
    """`at` 이 정해진 상자들 사이를 메우고 `until`(빛끝)을 채운다.

    들어오는 상자는 `at` 을 이미 들고 있거나 `None` 이다. 여기서 하는 일은 셋.
      1. 시각 순으로 세운다 — 시각이 없는 것은 뒤로 (위→아래 차례는 지킨다)
      2. 시각이 없는 것은 앞엣것에서 `gap` 만큼 뒤로 밀어 채운다
      3. 빛끝은 **다음의 「다른」 시각**까지. 마지막은 장 끝까지

    ★ 3번이 요점이다. 한 라벨의 굵은 머리와 그 아래 설명은 **같이 떠야 해서 같은
      시각을 나눠 갖는다.** 그냥 「다음 상자의 시각」으로 잡으면 형제의 같은 시각을
      물어 빛끝이 `at + 1.0` 으로 주저앉는다 — 뜨자마자 꺼진다.
    ★ `s13b_order` 와 `s13c_zones` 가 **같은 함수를 쓴다.** 두 벌로 두면 반드시
      어긋난다.
    """
    if not boxes:
        return boxes
    body = max(1.0, float(scene_len) - 0.60)      # 끝 걷어내기 자리를 비워 둔다
    tail = min(cues[-1]["until"], body) if cues else body

    boxes.sort(key=lambda b: (b.get("at") is None, b.get("at") or 0,
                              b.get("y", 0), b.get("x", 0)))
    for i, b in enumerate(boxes):
        if b.get("at") is None:
            prev = boxes[i - 1]["at"] if i else 0.0
            b["at"] = round(min(body - 0.5, prev + gap), 1)
        b["at"] = round(min(float(b["at"]), body - 0.5), 1)
    for i, b in enumerate(boxes):
        nxt = next((o["at"] for o in boxes[i + 1:] if o["at"] > b["at"] + 0.05), tail)
        b["until"] = round(max(b["at"] + 1.0, nxt), 1)
    return boxes


def autotime(pid: int, slug: str, no: int) -> List[Dict[str, Any]]:
    """자막 문장 시각을 상자 수에 맞춰 나눠 준다 — 저장은 하지 않는다.

    ★ 2026-08-16 에 손으로 돌려 186개를 채운 그 규칙 그대로다. 실측으로 대본과
      맞는 것을 확인했다(14장: 0.0 / 4.4 / 17.4 / 19.4 / 32.2 / 36.9).
    ★ 완벽한 초를 노리지 않는다. 사람이 보는 것은 **차례**이고, 이건 그 차례를
      대충 맞게 깔아 주는 밑그림이다.
    """
    sc = scene_of(pid, slug, no)
    boxes, cues = sc["boxes"], sc["cues"]
    if not boxes or not cues:
        return boxes
    n, m = len(boxes), len(cues)
    body = max(1.0, float(sc["len"]) - 0.60)     # 끝 걷어내기 자리를 비워 둔다
    ats, prev = [], -99.0
    for i in range(n):
        at = cues[min(int(i * m / n), m - 1)]["at"]
        if at <= prev + 0.05:                    # 상자가 문장보다 많은 장
            at = prev + 0.40
        at = min(at, body - 0.5)
        prev = at
        ats.append(round(at, 1))
    for i, b in enumerate(boxes):
        b["at"] = ats[i]
        b["until"] = round(ats[i + 1] if i + 1 < n
                           else min(cues[-1]["until"], body), 1)
    return boxes


def _stream(job, args: List[str], cwd: str, *, timeout: int) -> int:
    """자식 프로세스의 말을 **한 줄씩 그대로** 잡의 로그로 흘린다.

    ★ `encoding="utf-8"` 을 명시한다. 윈도에서 text 모드 기본값은 cp949 라
      도구가 찍는 한국어(`3/4 장마다 모션 굽기`)가 깨져서 올라온다.
      자식 쪽에도 `PYTHONIOENCODING` 을 박아야 파이프로 나갈 때 안 깨진다.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    p = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace",
                         bufsize=1)
    try:
        for line in p.stdout or []:
            line = line.rstrip()
            if line:
                job.add_log(line)
            if job.canceled:
                p.terminate()
                raise RuntimeError("사람이 멈췄습니다")
    finally:
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise RuntimeError(f"{timeout}초를 넘겨 멈췄습니다")
    return int(p.returncode or 0)


def run_picker(job, pid: int, slug: str, doc: Dict[str, Any], *,
               force: bool = False) -> Dict[str, Any]:
    """1) 마스크 지정기 HTML 을 만든다. 그리고 **연다.**

    ★ 만들고 나서 열어 주는 것까지가 한 동작이다. 경로만 알려 주면 사람이
      탐색기에서 찾아 들어가야 하고, 그 파일은 이름이 길다.
    """
    t = tool()
    if t is None:
        raise RuntimeError("모션 도구 폴더를 못 찾았습니다 — "
                           "showcase.config.local.json 의 motion.tool_dir 을 보세요")
    _need_deps(t)
    mp4 = target(pid, slug)
    if mp4 is None:
        raise RuntimeError("완성 mp4 가 없습니다 — 영상 렌더링을 먼저 하세요")

    pk = picker_path(mp4)
    if pk.is_file() and not force:
        job.add_log(f"이미 있습니다 — {pk.name} (다시 만들려면 «새로»)")
    else:
        job.progress(0, 1, "지정기 만드는 중")
        job.add_log(f"재료: {mp4}")
        args = [t["python"], t["picker"], str(mp4)]
        # ★ 「상자 자리 찾기」(S13c)가 먼저 돌았으면 **그 상자를 밑그림으로 깐다.**
        #   없으면 예전처럼 픽셀만 보고 찾는다 — 원장이 없는 옛 프로젝트의 자리다.
        gen = gen_path(mp4)
        if gen.is_file():
            args += ["--zones", str(gen)]
            job.add_log(f"찾아 둔 상자를 밑그림으로 씁니다 — {gen.name}")
        rc = _stream(job, args, cwd=t["dir"], timeout=1800)
        if rc != 0 or not pk.is_file():
            raise RuntimeError(f"지정기를 만들지 못했습니다 (종료 {rc})")

    # 도구가 찍는 `  28장` 에서 씬 수를 줍는다
    scenes = 0
    for l in reversed(job.log):
        if m := re.search(r"(\d+)\s*장\s*$", l):
            scenes = int(m.group(1))
            break

    st = state(pid, slug)
    want = st.get("expect_scenes") or 0
    if scenes and want and scenes != want:
        # ★ 막지는 않는다 — 사람이 보고 정한다. 다만 **말은 한다.**
        job.add_log(f"⚠ 씬 {scenes}개인데 슬라이드로 세면 {want}개입니다. "
                    f"굽기 전에 지정기에서 장 수를 확인하세요")
    elif scenes:
        job.add_log(f"씬 {scenes}개 — 슬라이드 {st.get('slides')}장과 맞습니다")

    _open(pk)
    job.add_log(f"열었습니다 — {pk.name}")
    job.add_log("상자와 시간을 찍고 zones.json 을 내려받은 뒤, "
                "이 화면의 «zones.json 불러오기» 로 넣으세요")
    job.progress(1, 1, "완료")
    return {"file": str(pk), "scenes": scenes, "expect": want}


def _open(p: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(p))                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError:
        pass                                          # 못 열어도 경로는 화면에 있다


def save_zones(pid: int, slug: str, raw: bytes) -> Dict[str, Any]:
    """2) 사람이 내려받은 zones.json 을 **완성본 폴더로 들인다.**

    ★ 다운로드 폴더를 뒤지지 않는다. 사람이 화면에서 파일을 고르는 것이 확실하고,
      남의 폴더를 훑는 코드는 잘못 골랐을 때 되돌릴 방법이 없다
      (`pipeline/s3b_images.py` 가 같은 이유로 자동 이동을 안 한다).
    """
    mp4 = target(pid, slug)
    if mp4 is None:
        raise RuntimeError("완성 mp4 가 없습니다")
    try:
        z = json.loads(raw.decode("utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"JSON 을 읽지 못했습니다: {e}")
    sc = z.get("scenes")
    if not isinstance(sc, list) or not sc:
        raise RuntimeError("zones.json 이 아닙니다 — scenes 가 없습니다")

    zp = zones_path(mp4)
    zp.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8")
    c = _count(zp)
    # 지정기가 어느 영상을 보고 만든 것인지 — 다른 영상의 zones 를 넣으면 여기서 걸린다
    said = str(z.get("video") or "")
    warn = ""
    if said and said != mp4.name:
        warn = f"이 zones 는 «{said}» 를 보고 만든 것입니다 — 지금 재료는 {mp4.name} 입니다"
    return {"ok": True, "file": str(zp), "name": zp.name, **c, "warn": warn}


def run_bake(job, pid: int, slug: str, doc: Dict[str, Any], *,
             mode: str = "시안", vals: str = "") -> Dict[str, Any]:
    """3) 굽는다. `시안` 은 앞 95초, `전체` 는 끝까지.

    ★ 시안을 먼저 굽는 것이 규칙이다. 23분짜리 전체는 30~40분이고, 값이 마음에
      안 들면 그 시간이 통째로 날아간다. 시안은 2분이다.
    """
    t = tool()
    if t is None:
        raise RuntimeError("모션 도구 폴더를 못 찾았습니다")
    _need_deps(t)
    mp4 = target(pid, slug)
    if mp4 is None:
        raise RuntimeError("완성 mp4 가 없습니다")
    zp = zones_path(mp4)
    if not zp.is_file():
        raise RuntimeError("zones.json 이 없습니다 — 지정기에서 찍어 불러오세요")

    # ★ **시안을 강제하지 않는다.** 원래 규칙은 "40분 태우고 나서 값이 틀린 걸
    #   알게 되는 사고"를 막으려던 것인데, 값이 확정된 뒤로는 시안이 확인해 줄
    #   것이 없다(2026-08-16: "개인적으로 저는 시안을 안 구워도 된다고 생각해요").
    #   시안은 여전히 굽을 수 있다 — 다만 전체를 굽는 조건이 아니다.
    preview = (mode or "시안") != "전체"

    out = _free(mp4.with_name(
        f"{mp4.stem}-시안{PREVIEW_SEC}초.mp4" if preview else f"{mp4.stem}-motion.mp4"))
    if out.resolve() == mp4.resolve():                # 있을 수 없지만, 있으면 사고다
        raise RuntimeError("원본을 덮어쓸 뻔했습니다")

    args = [t["python"], t["remaster"], str(mp4), "-o", str(out),
            "--zones", str(zp)]
    if preview:
        args += ["--limit", str(PREVIEW_SEC)]
    # 화면에서 값을 적어 보냈으면 그것을, 아니면 확정값을
    args += (vals.split() if vals.strip() else VALS)

    job.progress(0, 1, "시안 굽는 중" if preview else "전체 굽는 중")
    job.add_log(f"재료: {mp4.name} · 마스크: {zp.name}")
    job.add_log(f"결과: {out.name}")
    if not preview:
        sec = (durations(mp4).get("video") or 0)
        if sec:
            job.add_log(f"원본 {sec / 60:.0f}분 — {sec * 1.5 / 60:.0f}~"
                        f"{sec * 1.8 / 60:.0f}분쯤 걸립니다. 자리를 뜨셔도 됩니다")

    rc = _stream(job, args, cwd=t["dir"], timeout=4 * 3600)
    if rc != 0 or not out.is_file():
        raise RuntimeError(f"굽지 못했습니다 (종료 {rc}) — 위 로그를 보세요")

    # ── 검증 ──
    d = durations(out)
    v, a = d["video"], d["audio"]
    mb = round(out.stat().st_size / 1e6, 1)
    job.add_log(f"영상 {v} · 오디오 {a}")
    ok = verdict(v, a, preview)
    if preview:
        # ★ **시안은 길이를 재지 않는다.** `--limit 95` 는 영상을 정확히 95.000 초에
        #   자르는데, 오디오는 재인코딩 없이 그대로 복사되므로 패킷 경계에서 끝난다
        #   (실측 95.0 대 93.39). 즉 시안은 **언제나** 두 값이 다르다. 여기에 경고를
        #   띄우면 매번 틀린 경고가 뜨고, 그런 경고는 곧 아무도 안 읽는다 —
        #   그러면 정작 전체판의 진짜 경고까지 같이 묻힌다.
        job.add_log(f"시안 나왔습니다 — {out.name} ({mb}MB). "
                    f"길이는 전체를 구울 때 맞춥니다")
    elif ok:
        job.add_log(f"길이가 맞습니다 — {out.name} ({mb}MB)")
    else:
        job.add_log("⚠ 길이가 다릅니다 — 잘린 내레이션이 있을 수 있습니다")
    job.progress(1, 1, "완료")
    return {"file": str(out), "name": out.name, "mb": mb,
            "video": v, "audio": a, "ok": ok, "preview": preview,
            "url": f"/api/projects/{pid}/file/{ws.STEPS['dist'][0]}/{out.name}"}
