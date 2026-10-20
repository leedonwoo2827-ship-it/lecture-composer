"""이 PC 의 고르기 창(폴더·파일) — 웹앱 「① 원고」 의 「📁 폴더 지정하기 / 📄 파일 선택하기」 가 부른다.

    python -m longform.pick folder|files   → stdout 마지막 줄에 {"folder": "...", "files": [...]} (취소면 빈 값)
    종료 코드 3 = 창을 띄울 수 없음(tkinter 없음) → 화면이 경로를 붙여 넣으라고 묻는다.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "folder"
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        return 3
    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001
        return 3
    root.withdraw()
    root.attributes("-topmost", True)       # 브라우저 뒤에 숨지 않게
    root.update()
    out = {"folder": "", "files": []}
    if kind == "files":
        fs = filedialog.askopenfilenames(parent=root, title="원천 파일 고르기 — 요약노트·영상 원고(.html)·문항(mNN.json)",
                                         filetypes=[("원천", "*.html *.htm *.json"), ("모든 파일", "*.*")])
        out["files"] = list(fs or [])
    else:
        out["folder"] = filedialog.askdirectory(parent=root, title="원천 폴더 고르기 — 요약노트·영상 원고·문항이 든 폴더") or ""
    root.destroy()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
