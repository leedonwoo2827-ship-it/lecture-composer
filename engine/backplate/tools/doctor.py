# -*- coding: utf-8 -*-
"""진단 — 이 PC 에서 무엇이 되고 무엇이 안 되는지 **이름으로** 알려 준다.

    python tools/doctor.py

★ 왜 필요한가. 이 레포는 다른 팀원 자리나 여분 PC 에서도 돌아야 한다. 그런데
  막히는 자리가 늘 같다 — 로그인 둘(사람마다 따로 해야 한다), 가중치 396MB,
  node 22+, ffmpeg. 「안 됩니다」가 아니라 **무엇이 없어서 안 되는지**와
  **무엇을 치면 되는지**를 한 화면에 내놓는다.

★ 없어도 되는 것과 없으면 안 되는 것을 가른다. 음성이 없어도 덱·자막·큐시트는
  전부 나온다. 그런 것은 경고로 두고 진행을 막지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# ★ **한국어 콘솔(CP949)에서 죽지 않게.** 이 파일은 한글과 기호(— · ✓ △ ✗)를
#   찍는데, cmd 의 기본 코드페이지가 949 면 em dash 하나에 UnicodeEncodeError 로
#   통째로 죽는다(2026-09-18 실측). 진단기가 죽으면 「무엇이 없는지」를 알 길이
#   없어지므로, 여기서만은 반드시 살아남아야 한다. errors="replace" 까지 둔다 —
#   글자 하나가 깨지더라도 표는 나와야 한다.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001  — 파이프로 넘길 때 등
    pass

OK, WARN, BAD = "OK  ", "주의", "없음"
_rows: list[tuple[str, str, str, str]] = []   # (상태, 이름, 값, 고치는 법)


def row(state: str, name: str, value: str = "", fix: str = "") -> None:
    _rows.append((state, name, value, fix))


def _ver(cmd: list[str]) -> str:
    """버전 한 줄. **shutil.which 로 먼저 푼다** — 윈도우에서 npm 전역 명령은
    `codex.cmd` 라 이름만으로는 subprocess 가 못 찾는다(PATHEXT 를 안 본다)."""
    exe = shutil.which(cmd[0])
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                           timeout=20, encoding="utf-8", errors="replace")
        out = (r.stdout or r.stderr or "").strip()
        return out.splitlines()[0][:60] if out else exe
    except Exception:
        return ""


def check_binaries() -> None:
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    row(OK if sys.version_info >= (3, 11) else WARN, "Python", py,
        "3.11~3.13 을 씁니다" if sys.version_info < (3, 11) else "")

    node = shutil.which("node")
    if node:
        v = _ver(["node", "--version"])
        major = int(v.lstrip("v").split(".")[0] or 0) if v else 0
        row(OK if major >= 22 else WARN, "Node", v,
            "HyperFrames 가 22+ 를 요구합니다" if major < 22 else "")
    else:
        row(BAD, "Node", "", "https://nodejs.org 에서 22 이상 설치")

    for name, cmd, why, hard in (
        ("ffmpeg", ["ffmpeg", "-version"], "winget install Gyan.FFmpeg", True),
        ("ffprobe", ["ffprobe", "-version"], "ffmpeg 에 같이 들어 있습니다", True),
        ("git", ["git", "--version"], "https://git-scm.com", True),
        ("git-lfs", ["git", "lfs", "version"], "git lfs install", False),
        ("gh", ["gh", "--version"], "레포 수집에만 씁니다", False),
        ("codex", ["codex", "--version"], "npm i -g @openai/codex", False),
    ):
        v = _ver(cmd)
        row(OK if v else (BAD if hard else WARN), name, v, "" if v else why)


def check_node_packages() -> None:
    nm = APP / "node_modules"
    if not nm.is_dir():
        row(BAD, "npm 패키지", "", "npm install")
        return
    for pkg in ("hyperframes", "@hyperframes/producer", "playwright"):
        p = nm / pkg / "package.json"
        if p.is_file():
            try:
                row(OK, pkg, json.loads(p.read_text(encoding="utf-8")).get("version", ""))
            except Exception:
                row(OK, pkg, "")
        else:
            row(BAD, pkg, "", "npm install")


# 엔진 venv — onnxruntime 는 콘솔 의존성과 충돌해서 따로 둔다
_VENV_PY = APP / ".venv" / ("Scripts/python.exe" if sys.platform == "win32"
                            else "bin/python")


def check_python_packages() -> None:
    """콘솔 의존성은 **이 파이썬**에서, 엔진 의존성은 **엔진 venv**에서 본다.

    ★ 처음엔 둘 다 이 파이썬에서 찾았는데, onnxruntime 는 `.venv` 에 깔리고
      doctor 는 `.venv-app` 에서 도니 **멀쩡한데도 없다고 나왔다**
      (2026-09-18 실측 오탐). venv 를 나눠 둔 구조에서는 어느 venv 를 보는지가
      곧 답을 가른다.
    """
    import importlib
    for mod, label, why in (
        ("fastapi", "fastapi", "pip install -e ."),
        ("uvicorn", "uvicorn", "pip install -e ."),
        ("claude_agent_sdk", "claude-agent-sdk", "pip install -e ."),
        ("fontTools", "fonttools", "pip install -e ."),
        ("sqlalchemy", "SQLAlchemy", "이미지 스튜디오에 필요 — pip install -e ."),
        ("httpx", "httpx", "pip install -e ."),
    ):
        try:
            m = importlib.import_module(mod)
            row(OK, label, str(getattr(m, "__version__", "")))
        except Exception:
            row(BAD, label, "", why)

    # ── 엔진 venv 쪽 ──────────────────────────────────────────────────────
    if not _VENV_PY.is_file():
        row(WARN, "엔진 venv", "",
            "setup.bat 이 .venv 를 만듭니다 — 없으면 음성만 빠집니다")
        return
    probe = ("import onnxruntime,soundfile,numpy,yaml;"
             "print(onnxruntime.__version__, soundfile.__version__)")
    try:
        r = subprocess.run([str(_VENV_PY), "-c", probe], capture_output=True,
                           text=True, timeout=120, encoding="utf-8",
                           errors="replace")
        if r.returncode == 0:
            ort, sf = (r.stdout or "").split()[:2]
            row(OK, "onnxruntime", f"{ort} (엔진 venv)")
            row(OK, "soundfile", f"{sf} (엔진 venv)")
        else:
            row(WARN, "엔진 의존성", "",
                ".venv/Scripts/python -m pip install -r requirements-engine.txt")
    except Exception:
        row(WARN, "엔진 의존성", "", "엔진 venv 를 확인하지 못했습니다")


def check_assets() -> None:
    fonts = list((APP / "static" / "fonts").glob("Pretendard-*.woff2"))
    row(OK if len(fonts) >= 3 else WARN, "Pretendard 폰트",
        f"{len(fonts)}종", "" if len(fonts) >= 3 else "python tools/get_fonts.py")

    gsap = APP / "static" / "vendor" / "gsap.min.js"
    row(OK if gsap.is_file() else BAD, "GSAP", "",
        "" if gsap.is_file() else "static/vendor/gsap.min.js 가 없습니다")

    voc = APP / "assets" / "onnx" / "vocoder.onnx"
    if voc.is_file():
        mb = sum(f.stat().st_size for f in (APP / "assets" / "onnx").glob("*.onnx")) / 1e6
        row(OK, "슈퍼토닉3 가중치", f"{mb:.0f}MB")
    else:
        row(WARN, "슈퍼토닉3 가중치", "",
            "git lfs install && git clone https://huggingface.co/Supertone/supertonic-3 assets "
            "(약 396MB · 없으면 음성만 빠집니다)")


def check_logins() -> None:
    # Codex — 파일이 있는지가 아니라 **살아 있는지**를 본다. 만료된 토큰이
    # 파일로는 멀쩡해 보인다(2026-09-18 에 실제로 겪었다: token_revoked).
    auth = Path.home() / ".codex" / "auth.json"
    if not auth.is_file():
        row(WARN, "Codex 로그인", "", "codex login  (그림 생성에 필요)")
    else:
        try:
            d = json.loads(auth.read_text(encoding="utf-8"))
            has = bool((d.get("tokens") or {}).get("access_token"))
            row(OK if has else WARN, "Codex 로그인",
                (d.get("last_refresh") or "")[:10],
                "" if has else "codex login")
        except Exception:
            row(WARN, "Codex 로그인", "", "codex login")

    # ★ **앱과 같은 방법으로 찾는다.** 처음엔 shutil.which("claude") 만 봤는데,
    #   이 PC 에는 PATH 에 없고 **VSCode 확장 안**에 네이티브 바이너리가 있었다.
    #   앱(llm/claude_provider.find_cli)은 그걸 찾아 잘 쓰는데 진단만 「없음」이라
    #   했다 — 멀쩡한 것을 없다고 하면 사람이 헛일을 한다(2026-09-18 실측).
    try:
        from llm.claude_provider import find_cli
        exe = find_cli()
    except Exception:  # noqa: BLE001
        exe = None
    if exe:
        where = "VSCode 확장" if ".vscode" in str(exe) else "PATH"
        row(OK, "Claude 실행파일", f"{where}")
    else:
        row(WARN, "Claude 실행파일", "",
            "터미널에서 `claude` 를 한 번 실행해 로그인 — 대본·지시문 단계에 필요")


def check_workspace() -> None:
    try:
        from core import workspace as ws
        root = ws.ROOT
        n = len([d for d in root.iterdir() if d.is_dir()]) if root.is_dir() else 0
        row(OK, "작업 폴더", f"{root} · 프로젝트 {n}개")
    except Exception as e:  # noqa: BLE001
        row(BAD, "작업 폴더", "", f"{type(e).__name__}: {e}")


def main() -> int:
    print(f"\n  backplate-showcase 진단 — {APP}\n")
    check_binaries()
    check_python_packages()
    check_node_packages()
    check_assets()
    check_logins()
    check_workspace()

    w = max(len(n) for _, n, _, _ in _rows) + 1
    bad = warn = 0
    for state, name, value, fix in _rows:
        mark = {OK: "  ✓", WARN: "  △", BAD: "  ✗"}[state]
        line = f"{mark} {name:<{w}} {value}"
        print(line.rstrip())
        if fix:
            print(f"      → {fix}")
        bad += state == BAD
        warn += state == WARN

    print()
    if bad:
        print(f"  {bad}개가 없어 진행할 수 없습니다. 위 → 줄을 따라 하세요.")
    elif warn:
        print(f"  주의 {warn}건 — 그 기능만 빠지고 나머지는 돕니다.")
    else:
        print("  전부 준비됐습니다. run.bat 으로 시작하세요.")
    print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
