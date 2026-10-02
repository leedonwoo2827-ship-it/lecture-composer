"""backplate-studio 안에서 도는 작은 도우미 — **backplate 의 .venv-app 파이썬으로 실행한다.**

    python bp_helper.py create   <args.json>   → {"pid", "slug", "dir"}
    python bp_helper.py outline  <pid>         → s2b-outline 캐시의 slides(no, data_id, kind, title)
    python bp_helper.py override <pid> <patch.json>   → deck.overrides.json 에 병합 + overrides_rev++
    python bp_helper.py project  <pid> <patch.json>   → project.json 에 병합

★ SHOWCASE_WORKSPACE 는 호출하는 쪽(s3_render)이 환경변수로 넘긴다.
★ 생성 로직은 server.py create_project() 를 그대로 옮겼다(웹 UI 와 같은 project.json).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BP = Path(os.environ["BACKPLATE_DIR"]).resolve()
sys.path.insert(0, str(BP))

from core import config, workspace as ws  # noqa: E402
from core import refs as refs_mod  # noqa: E402


def _find(pid: int):
    for p in ws.list_projects():
        if int(p.get("id") or p.get("pid") or 0) == pid:
            return pid, p["slug"]
    # list_projects 형식이 달라도 폴더 이름으로 찾는다
    for d in ws.ROOT.iterdir():
        if d.is_dir() and d.name.startswith(f"{pid:02d}_"):
            return pid, d.name.split("_", 1)[1]
    raise SystemExit(f"project {pid} not found")


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def create(args: dict) -> dict:
    pid = ws.next_pid()
    slug = ws.ascii_slug(args["slug"])
    cfg = config.load()
    narration = dict(cfg["narration"], enabled=True)
    if args.get("voice"):
        narration["voice"] = args["voice"]
    if args.get("speed"):
        narration["speed"] = float(args["speed"])
    doc = {
        "schema_version": 1, "slug": slug, "title": args["title"],
        "live_url": None, "urls": [], "language": "ko", "media_mode": "still",
        "video_dir": None, "items": [], "sources": [], "repo": None,
        "narration": narration, "models": dict(cfg["models"]),
        "image_fit": "full", "image_swap": True,
        "longform": args.get("tag") or {},
    }
    ws.save_project(pid, slug, doc)
    got = refs_mod.collect(pid, slug, [args["html"]])
    doc["refs"] = {"dir": got["dir"], "items": got["items"]}
    ws.save_project(pid, slug, doc)
    return {"pid": pid, "slug": slug, "dir": str(ws.project_dir(pid, slug))}


def outline(pid: int) -> dict:
    pid, slug = _find(pid)
    f = ws.project_dir(pid, slug) / "_cache" / "s2b-outline.json"
    d = json.loads(f.read_text(encoding="utf-8"))["data"]
    return {"pid": pid, "slug": slug, "dir": str(ws.project_dir(pid, slug)),
            "slides": [{k: s.get(k) for k in ("no", "data_id", "kind", "title", "media_kind")}
                       for s in d["slides"]]}


def override(pid: int, patch: dict) -> dict:
    pid, slug = _find(pid)
    ov = ws.load_overrides(pid, slug) or {}
    _merge(ov, patch)
    ws.save_overrides(pid, slug, ov)
    doc = ws.load_project(pid, slug)
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, slug, doc)
    return {"ok": True}


def project(pid: int, patch: dict) -> dict:
    pid, slug = _find(pid)
    doc = ws.load_project(pid, slug)
    _merge(doc, patch)
    ws.save_project(pid, slug, doc)
    return {"ok": True}


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "create":
        out = create(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    elif cmd == "outline":
        out = outline(int(sys.argv[2]))
    elif cmd == "override":
        out = override(int(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")))
    elif cmd == "project":
        out = project(int(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")))
    else:
        raise SystemExit(f"unknown: {cmd}")
    sys.stdout.write("@@JSON@@" + json.dumps(out, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
