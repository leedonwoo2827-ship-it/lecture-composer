# -*- coding: utf-8 -*-
"""슈퍼토닉3 가 쓸 수 있는 상태인지 보고 `showcase.config.local.json` 의 tts 를 채운다.

★ **예전과 무엇이 다른가.** 전에는 형제 폴더에 clone 한 `voicewright/` 를 봤다.
  그러면 새 PC 마다 그 폴더를 먼저 만들어야 하고, 「다른 팀원 자리나 여분 PC
  에서도 쓸 수 있어야 한다」는 요구를 그 구조로는 못 지킨다.
  이제 엔진 코드는 **이 레포 안 `tts/`** 에 있고, 밖에서 와야 하는 것은
  가중치(`assets/`, 약 396MB)와 onnxruntime 가 깔린 엔진 venv 둘뿐이다.

★ 둘 다 없어도 파이프라인은 돈다 — 덱·자막·큐시트는 음성 없이 전부 나온다.
  그때는 engine 을 "none" 으로 두고 무엇이 없는지 이름으로 알려 준다.

★ 절대경로는 `showcase.config.local.json` 에만 쓴다(gitignore). 배포본에
  개인 경로가 나가면 안 된다 — `core/config.py` 의 LOCAL_KEYS 규칙 그대로다.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
# ★ 레포 뿌리를 **먼저** 꽂는다. `python tools/wire_tts.py` 로 부르면 sys.path 에
#   `tools/` 만 들어가서 `core` 가 이 PC 의 **다른 프로젝트** core 로 잡힌다
#   (실제로 260519-localnotebooklm/core 를 물었다).
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from core import config  # noqa: E402
ENGINE = APP / "tts" / "engine.py"          # 벤더링한 엔진 코드
ASSETS = APP / "assets"                     # HuggingFace 에서 받은 가중치
VOCODER = ASSETS / "onnx" / "vocoder.onnx"  # 이게 있으면 받아진 것이다

# 엔진 venv — onnxruntime 는 콘솔 의존성과 충돌해서 따로 둔다
VENV_PY = APP / ".venv" / ("Scripts/python.exe" if sys.platform == "win32"
                           else "bin/python")


def _engine_python() -> str:
    """엔진을 돌릴 파이썬. 전용 venv 가 있으면 그것, 없으면 지금 이 파이썬."""
    return str(VENV_PY) if VENV_PY.is_file() else sys.executable


def main() -> None:
    missing = []
    if not ENGINE.is_file():
        missing.append("엔진 코드(tts/)")
    if not VOCODER.is_file():
        missing.append("모델 가중치(assets/onnx/)")

    if not missing:
        py = _engine_python()
        config.save({"tts": {
            "engine": "supertonic3",
            "python": py,
            # 브리지가 sys.path 에 꽂을 뿌리 — 이 레포 자신이다
            "voicewright_dir": str(APP),
            "assets_dir": str(ASSETS),
            "timeout_ms": 300000,
        }})
        print(f"[tts] 슈퍼토닉3 연결됨 · python={py}")
        print(f"[tts] 가중치={ASSETS}")
        return

    config.save({"tts": {"engine": "none", "python": None,
                         "voicewright_dir": None, "assets_dir": None}})
    print("[tts] 음성을 끕니다 — 없는 것: " + ", ".join(missing))
    if not VOCODER.is_file():
        print("[tts] 가중치를 받으려면:")
        print("        git lfs install")
        print("        git clone https://huggingface.co/Supertone/supertonic-3 assets")
        print("      (약 396MB · OpenRAIL-M 이라 레포에 넣지 않습니다)")
    print("[tts] 덱·자막·큐시트는 음성 없이도 전부 나옵니다.")


if __name__ == "__main__":
    main()
