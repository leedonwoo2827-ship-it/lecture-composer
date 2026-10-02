# -*- coding: utf-8 -*-
"""capture_sections.mjs 가 낸 manifest.json 을 프로젝트에 그대로 붙인다.

목차(제목·미디어종류)를 한 번에 갈아 끼우고, 캡처 이미지를 장 번호 그대로
업로드한다. 본문·대본은 비워 둔다 — 나중에 화면에서 채우거나, 원고 JSON을
따로 만들어 `draft/import`로 다시 덮어써도 된다.

표준 라이브러리만 쓴다. 서버가 떠 있어야 한다(run.bat).

    .venv-app\\Scripts\\python.exe tools\\attach_captures.py <pid> <manifest.json 경로>
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ★ Windows 콘솔은 기본이 cp949 라 em-dash 같은 문자에서 죽는다(실제로 겪음).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP = Path(__file__).resolve().parent.parent


def call(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body if body is not None else {}).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"{method} {path} -> {e.code}: {e.read().decode('utf-8', 'replace')}") from e


def base_url() -> str:
    port = 5178
    p = APP / "showcase.config.json"
    if p.is_file():
        try:
            port = json.loads(p.read_text(encoding="utf-8-sig")).get("port", port)
        except Exception:  # noqa: BLE001
            pass
    return f"http://127.0.0.1:{port}"


def main() -> None:
    if len(sys.argv) < 3:
        print("사용법: attach_captures.py <pid> <manifest.json 경로>")
        sys.exit(2)
    pid = int(sys.argv[1])
    manifest_path = Path(sys.argv[2])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    img_dir = manifest_path.parent

    base = base_url()
    try:
        call(base, "GET", "/api/health")
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 서버에 연결할 수 없습니다({base}) — 먼저 run.bat 을 실행하세요.\n  {e}")
        sys.exit(1)

    slides = [{
        "no": s["no"], "section": "", "kind": s.get("kind", "note"),
        "title": s["title"], "note": "", "media_kind": s.get("media_kind", "text"),
        "video_id": None, "evidence_hint": "", "body": "", "narration": {},
    } for s in manifest["slides"]]

    r = call(base, "POST", f"/api/projects/{pid}/draft/import",
             {"deck_title": manifest.get("deck_title") or "", "slides": slides})
    print(f"[목차] {r['slides']}장 넣음")

    for s in manifest["slides"]:
        if not s.get("image"):
            continue
        raw = (img_dir / s["image"]).read_bytes()
        data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        rr = call(base, "POST", f"/api/projects/{pid}/slide-image/{s['no']}",
                  {"data_url": data_url, "name": s["image"]})
        print(f"[{s['no']}] 이미지 붙임 · {rr.get('bytes', 0) // 1024}KB")

    print(f"\n완료 — {base}/#/deck 에서 확인하세요 (프로젝트 #{pid})")


if __name__ == "__main__":
    main()
