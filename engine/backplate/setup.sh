#!/usr/bin/env bash
# backplate-showcase — 새 PC에서 한 번 (macOS / Linux)
#
# ★ setup.bat 과 **같은 여섯 걸음**이다. 예전에는 여기가 넷뿐이라 엔진 venv 와
#   npm 이 빠져 있었고, 그대로 돌리면 **영상이 아예 안 나왔다**(HyperFrames 가
#   없다). 둘이 갈라지면 「맥에서는 왜 안 되지」를 매번 다시 찾게 된다.
# ★ 무엇이 없어서 안 되는지는 마지막 `doctor.py` 가 이름으로 알려 준다.
set -u
cd "$(dirname "$0")"

echo "== backplate-showcase — 첫 설치 =="
echo

command -v python3 >/dev/null 2>&1 || { echo "[오류] Python 3.10+ 가 필요합니다."; exit 1; }
command -v node    >/dev/null 2>&1 || { echo "[오류] Node.js 가 필요합니다 (영상 렌더)."; exit 1; }
command -v ffmpeg  >/dev/null 2>&1 || echo "[주의] ffmpeg 이 없습니다 — 프레임 추출·영상 변환이 안 됩니다."
command -v gh      >/dev/null 2>&1 || echo "[주의] gh CLI 가 없습니다 — 레포 수집이 안 됩니다."

echo "[1/6] 콘솔 환경 (.venv-app)"
[ -x ".venv-app/bin/python" ] || python3 -m venv .venv-app || { echo "[오류] venv 생성 실패."; exit 1; }
.venv-app/bin/python -m pip install --quiet --upgrade pip
.venv-app/bin/python -m pip install --quiet -e . || { echo "[오류] 의존성 설치 실패."; exit 1; }

# ★ onnxruntime 은 콘솔 의존성과 부딪혀 **따로 둔다**(`.venv`). 한 venv 에 넣으면
#   설치가 서로를 밀어낸다 — 윈도우에서 겪고 나눈 구조다.
echo "[2/6] 엔진 환경 (.venv) — onnxruntime 은 콘솔과 따로 둔다"
[ -x ".venv/bin/python" ] || python3 -m venv .venv || echo "[주의] 엔진 venv 실패 — 음성이 빠집니다."
if [ -x ".venv/bin/python" ]; then
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements-engine.txt \
    || echo "[주의] 엔진 의존성 설치 실패 — 음성이 빠집니다."
fi

echo "[3/6] node 꾸러미 (HyperFrames + Playwright)"
npm install --silent || { echo "[오류] npm install 실패 — 영상 렌더가 안 됩니다."; exit 1; }

echo "[4/6] 폰트 (Pretendard)"
.venv-app/bin/python tools/get_fonts.py || echo "[주의] 폰트 내려받기 실패 — 시스템 폰트로 떨어집니다."

# ★ 엔진 코드는 **이 레포 안 `tts/`** 에 있다(예전엔 형제 폴더의 voicewright/).
#   밖에서 와야 하는 것은 가중치(assets/, 약 396MB)뿐이다.
echo "[5/6] 음성 모델 연결 (슈퍼토닉3)"
.venv-app/bin/python tools/wire_tts.py

echo "[6/6] 진단"
.venv-app/bin/python tools/doctor.py

echo
echo "다 됐습니다. 로그인 둘은 사람마다 따로 해야 합니다:"
echo "    claude          한 번 실행해 구독 로그인   (대본·지시문)"
echo "    codex login     한 번 실행해 ChatGPT 로그인 (그림)"
echo
echo "그다음  ./run.sh   →  http://localhost:5178"
