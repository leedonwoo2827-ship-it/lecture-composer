# -*- coding: utf-8 -*-
"""TTS 브리지 — **다른 venv 에서 도는 유일한 코드.**

콘솔(.venv-app)은 fastapi 를, 엔진(.venv)은 onnxruntime 를 쓴다. 둘을 한 venv 에
넣으면 충돌하고, 렌더 도중에 콘솔을 닫을 수도 있어야 한다. 그래서 **파일로만 대화한다.**

    콘솔  →  job.json   {"items":[{"no":5,"text":"…"}], …}
             ↓  이 스크립트를 엔진 venv 의 python 으로 실행
    콘솔  ←  result.json {"items":[{"no":5,"file":"005.wav","sec":4.1}], …}

stdout 을 파싱하지 않는다 — 진행 로그와 결과가 섞이면 한글 콘솔 인코딩에서
깨진다(실제로 겪는 문제). 결과는 항상 파일이다.

    python tts_bridge.py <job.json> <result.json>

★ **엔진이 바뀌었다: voicewright → 슈퍼토닉3(이 레포 안 `tts/`).**
  예전에는 형제 폴더에 clone 한 voicewright 를 sys.path 에 꽂아 썼다. 그러면
  다른 PC 에서 돌릴 때마다 그 폴더를 먼저 만들어야 한다. 「다른 팀원 자리나
  여분 PC 에서도 쓸 수 있어야 한다」는 요구를 그 구조로는 못 지킨다.
  이제 엔진 코드는 레포 안에 있고, 가중치(396MB)만 setup 이 내려받는다.
  API 는 그대로다 — `Engine.get()` · `synth(voice_code, lang, speed, total_step)`
  · `write_wav` · 44100Hz 모노. 그래서 `s10_tts.py` 는 한 줄도 안 고쳤다.

★ **`SUPERTONIC_PROJECT_ROOT` 를 반드시 박는다.** 슈퍼토닉의 `settings.py` 는
  조상 폴더를 거슬러 올라가며 `pyproject.toml`·`run.bat` 을 찾아 뿌리를 잡는다.
  이 레포에도 그 파일들이 있어서 **호스트 뿌리를 잡아 버리고**, 그러면
  `config/`·`assets/` 를 엉뚱한 데서 찾는다. 그쪽 docstring 에 이미 적힌 함정이다.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

APP = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: tts_bridge.py <job.json> <result.json>", file=sys.stderr)
        return 2
    job_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))

    # ★ 뿌리·자산·설정을 **명시적으로** 박는다. 자동 탐색에 맡기지 않는다.
    os.environ["SUPERTONIC_PROJECT_ROOT"] = str(APP)
    assets = job.get("assets_dir") or str(APP / "assets")
    os.environ["SUPERTONIC_ASSETS_DIR"] = assets
    cfg = APP / "tts" / "config"
    os.environ.setdefault("SUPERTONIC_VOICE_MAP", str(cfg / "voice_map.yaml"))
    os.environ.setdefault("SUPERTONIC_PRONUNCIATION_MAP",
                          str(cfg / "pronunciation_map.yaml"))
    os.environ.setdefault("SUPERTONIC_EXPRESSION_TAGS",
                          str(cfg / "expression_tags.yaml"))
    os.environ.setdefault("SUPERTONIC_USE_GPU", "auto")
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))

    result = {"items": [], "sample_rate": 0, "error": None}
    try:
        from tts.audio_io import write_wav
        from tts.engine import Engine

        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        voice = job.get("voice") or "F2"
        speed = float(job.get("speed") or 1.0)
        step = int(job.get("total_step") or 8)

        async def go():
            eng = await Engine.get()
            result["sample_rate"] = eng.sample_rate
            for it in job["items"]:
                no = int(it["no"])
                text = (it.get("text") or "").strip()
                if not text:
                    continue
                name = f"{no:03d}.wav"
                try:
                    wav = await eng.synth(text, voice_code=voice, lang="ko",
                                          speed=speed, total_step=step)
                except Exception as e:  # noqa: BLE001
                    result["items"].append({"no": no, "error": f"{type(e).__name__}: {e}"})
                    print(f"[{no}] 실패 {e}", flush=True)
                    continue
                write_wav(out_dir / name, wav, eng.sample_rate)
                sec = round(len(wav) / float(eng.sample_rate), 2)
                result["items"].append({"no": no, "file": name, "sec": sec})
                print(f"[{no}] {sec:.1f}s {name}", flush=True)

        asyncio.run(go())
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
