# -*- coding: utf-8 -*-
"""S10 음성 합성 — 발음대본 → wav.

**성우 파일이 항상 이긴다.** `07_음성/005.wav` 를 사람이 넣어 두면 그 장은 합성하지
않는다. 가안(TTS)으로 전체를 한 번 굽고, 중요한 장만 성우로 갈아 끼우는 것이
실제 작업 순서다.

    07_음성/005.wav        ← 성우. 사람이 직접 넣는다. source="vo"
    07_음성/tts/005.wav    ← 합성 가안.                 source="tts"

엔진은 **다른 venv 에서 서브프로세스**로 돈다(`scripts/tts_bridge.py`). onnxruntime
와 콘솔 의존성이 충돌하고, 합성 중에 콘솔을 닫아도 되어야 하기 때문이다.

엔진이 없으면 **건너뛴다.** 음성 없이도 덱·자막·큐시트는 전부 나온다 — TTS 는
있으면 좋은 것이지 파이프라인을 막을 것이 아니다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, workspace as ws
from pipeline.registry import (STAGES, cache_path, cached_data, narration_of,
                               read_cache, write_cache)

APP = Path(__file__).resolve().parent.parent
BRIDGE = APP / "scripts" / "tts_bridge.py"
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".opus", ".flac")


def find_engine(cfg: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """설정에 적힌 것만 쓴다. **찾아 헤매지 않는다** — 남의 폴더를 뒤지면
    엉뚱한 설치본을 물고 조용히 이상한 목소리가 나온다."""
    t = cfg.get("tts") or {}
    if (t.get("engine") or "none") == "none":
        return None
    py, vw, assets = t.get("python"), t.get("voicewright_dir"), t.get("assets_dir")
    if not (py and vw):
        return None
    if not Path(py).is_file():
        return None
    # ★ **엔진이 바뀌었는데 이 검사만 옛 자리를 봤다**(2026-09-18에 잡음).
    #   전에는 형제 폴더에 clone 한 `voicewright/` 를 꽂아 썼고, 지금은 엔진이
    #   이 레포 안 `tts/` 에 벤더링돼 있다(`scripts/tts_bridge.py` 머리말).
    #   `voicewright_dir` 은 **이름만 남은 칸**이라 이제 레포 뿌리가 들어온다
    #   (`tools/wire_tts.py`) — 그 밑에 `voicewright/` 가 있을 리 없다.
    #   그래서 가중치도 venv 도 다 갖춰 놓고 `doctor.py` 가 전부 초록인데
    #   합성만 조용히 건너뛰었다(s10-tts status=skipped · engine=none).
    #   **`wire_tts.py` 가 보는 것과 같은 것을 본다** — 둘이 갈라지면 또 난다.
    if not (Path(vw) / "tts" / "engine.py").is_file():
        return None
    return {"python": py, "voicewright_dir": vw, "assets_dir": assets or "",
            "timeout_ms": int(t.get("timeout_ms") or 300000)}


def probe_sec(path: Path) -> Optional[float]:
    """ffprobe 로 실제 길이. 성우 파일은 우리가 만든 게 아니라 재 봐야 한다."""
    import shutil
    ff = shutil.which("ffprobe")
    if not ff:
        return None
    try:
        r = subprocess.run(
            [ff, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30)
        return round(float(r.stdout.strip()), 2)
    except Exception:  # noqa: BLE001
        return None


def find_vo(audio_dir: Path, no: int) -> Optional[Path]:
    for pat in (f"{no:03d}", str(no)):
        for ext in AUDIO_EXT:
            p = audio_dir / f"{pat}{ext}"
            if p.is_file():
                return p
    return None


def _calibrate(script: Dict[str, Any], measured: Dict[str, Any]) -> Optional[float]:
    """실측 wav 길이에서 초당 글자수를 뽑는다. 합성한 장만 센다(성우는 속도가 다르다)."""
    import re as _re
    ch = sec = 0
    for k, m in measured.items():
        if m.get("source") != "tts" or not m.get("duration_sec"):
            continue
        t = (script.get(k) or {}).get("text") or ""
        ch += len(_re.sub(r"\s", "", t))
        sec += m["duration_sec"]
    if sec < 20 or ch < 100:
        return None                 # 표본이 적으면 건드리지 않는다
    return round(ch / sec, 2)


def _bridge(job_spec: Dict[str, Any], work: Path, eng: Dict[str, str]) -> Dict[str, Any]:
    """합성기를 한 번 돌린다 — **파일로만 대화한다.**

    전체 합성(`run`)과 한 장 다시 합성(`synth_one`)이 같이 쓴다. 두 벌로 두면
    보이스·속도·스텝수가 갈려서 **다시 합성한 한 장만 목소리가 달라진다.**
    """
    job_p, res_p = work / "_tts_job.json", work / "_tts_result.json"
    ws.write_json(job_p, job_spec)
    if res_p.exists():
        res_p.unlink()
    cmd = [eng["python"], str(BRIDGE), str(job_p), str(res_p)]
    proc = subprocess.run(cmd, cwd=str(APP), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=eng["timeout_ms"] / 1000)
    res = ws.read_json(res_p, {}) or {}
    if not res and proc.returncode != 0:
        res = {"error": (proc.stdout or proc.stderr or "")[-400:]}
    return res


def synth_one(pid: int, slug: str, no: int) -> Dict[str, Any]:
    """**그 장만** 다시 합성한다 — 발음을 고치고 그 자리에서 들어 보려고.

    ★ 전체 합성은 31장에 몇 분이 걸린다. 발음 한 군데를 고칠 때마다 그걸 다시
      돌리면 검수가 끝나지 않는다 — 한 장만 다시 합성하고 바로 다시 들을 수
      있어야 한다(2026-08-16).

    ★ 읽는 글은 **손편집을 얹은 것**이다(`narration_of`). 화면에서 고친 발음이
      곧바로 소리가 되어야 고친 보람이 있다.

    ★ 스테이지 캐시의 그 장 칸만 갈아 끼우고 **`input_hash` 는 건드리지 않는다.**
      낡음 판정은 이 함수가 할 일이 아니다 — 발음을 고쳤으면 `narration_rev` 가
      이미 s10 을 낡게 만들어 두었고, 그것이 "나머지 장도 다시 봐야 한다" 는
      정직한 신호다.
    """
    cfg = config.load()
    eng = find_engine(cfg)
    if eng is None:
        raise RuntimeError("음성 엔진이 설정되어 있지 않습니다 "
                           "(showcase.config.local.json 의 tts)")
    sc = (narration_of(pid, slug) or {}).get(str(no)) or {}
    text = (sc.get("text") or sc.get("srt_text") or "").strip()
    if not text:
        raise RuntimeError(f"{no}장에 읽을 글이 없습니다 — 발음 칸을 채우세요")

    project = ws.load_project(pid, slug)
    nar = dict(cfg["narration"], **(project.get("narration") or {}))
    tts_dir = ws.sub_dir(pid, slug, "audio", "tts")
    step_name = ws.STEPS["audio"][0]

    res = _bridge({
        "out_dir": str(tts_dir),
        "voicewright_dir": eng["voicewright_dir"],
        "assets_dir": eng["assets_dir"],
        "voice": nar.get("voice", "F2"), "speed": nar.get("speed", 1.0),
        "total_step": nar.get("total_step", 8),
        "items": [{"no": int(no), "text": text}],
    }, ws.cache_dir(pid, slug), eng)

    if res.get("error"):
        raise RuntimeError("엔진 오류: " + str(res["error"])[-300:])
    items = [r for r in (res.get("items") or []) if str(r.get("no")) == str(no)]
    if not items:
        raise RuntimeError("합성기가 아무것도 내놓지 않았습니다")
    r = items[0]
    if r.get("error"):
        raise RuntimeError(str(r["error"])[:300])

    rel = f"{step_name}/tts/{r.get('file')}"
    one = {"source": "tts", "duration_sec": r.get("sec"), "file": rel}

    # 캐시의 그 칸만 고쳐 쓴다 — envelope(해시·비용·시각)는 그대로 둔다
    env = read_cache(pid, slug, "s10-tts")
    if env is not None:
        env.setdefault("data", {}).setdefault("slides", {})[str(no)] = one
        ws.write_json(cache_path(pid, slug, "s10-tts"), env)
    return {**one, "no": int(no), "text": text}


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s10-tts"]

    # ★ S6 캐시가 아니라 **손편집을 얹은 것**을 읽는다. 발음을 발음기호로 고쳐
    #   쓰는 일이 이 단계의 주된 재실행 이유인데, 캐시만 읽으면 고친 것이 한 번도
    #   소리로 나가지 못한다.
    script = narration_of(pid, slug)
    if not script:
        raise RuntimeError("대본(s6-script)을 먼저 돌리세요")

    audio_dir = ws.step_dir(pid, slug, "audio")
    tts_dir = ws.sub_dir(pid, slug, "audio", "tts")
    step_name = ws.STEPS["audio"][0]

    out: Dict[str, Any] = {}
    warn: List[str] = []
    todo: List[Dict[str, Any]] = []

    # 1) 성우 파일 먼저 — 있으면 합성하지 않는다
    for no_s, sc in sorted(script.items(), key=lambda kv: int(kv[0])):
        no = int(no_s)
        vo = find_vo(audio_dir, no)
        if vo:
            out[no_s] = {"source": "vo", "file": f"{step_name}/{vo.name}",
                         "duration_sec": probe_sec(vo)}
            continue
        # 발음이 비면 자막을 그대로 읽는다
        text = (sc.get("text") or sc.get("srt_text") or "").strip()
        if text:
            todo.append({"no": no, "text": text})

    n_vo = len(out)
    if n_vo:
        job.add_log(f"성우 파일 {n_vo}장 — 이 장들은 합성하지 않는다")

    eng = find_engine(cfg)
    if not eng:
        job.add_log("TTS 엔진이 설정되지 않았습니다 — 합성을 건너뜁니다")
        job.add_log("설정 → tts.python / tts.voicewright_dir / tts.assets_dir")
        job.add_log(f"성우 파일을 넣으려면: {audio_dir} 에 005.wav 처럼 번호로")
        warn.append(f"TTS 미설정 — {len(todo)}장이 무음")
        return write_cache(pid, slug, "s10-tts",
                           input_hash=stage.input_hash(pid, slug, project),
                           data={"slides": out, "engine": "none"},
                           code_version=stage.code_version,
                           status="skipped" if not out else "degraded", warnings=warn)

    if not todo:
        job.add_log("합성할 장이 없습니다 (전부 성우)")
        return write_cache(pid, slug, "s10-tts",
                           input_hash=stage.input_hash(pid, slug, project),
                           data={"slides": out, "engine": "vo"},
                           code_version=stage.code_version, status="ok")

    # 2) 합성 — 파일로만 대화한다
    nar = dict(cfg["narration"], **(project.get("narration") or {}))
    work = ws.cache_dir(pid, slug)
    job_p, res_p = work / "_tts_job.json", work / "_tts_result.json"
    ws.write_json(job_p, {
        "out_dir": str(tts_dir),
        "voicewright_dir": eng["voicewright_dir"],
        "assets_dir": eng["assets_dir"],
        "voice": nar.get("voice", "F2"), "speed": nar.get("speed", 1.0),
        "total_step": nar.get("total_step", 8),
        "items": todo,
    })
    if res_p.exists():
        res_p.unlink()

    job.add_log(f"{len(todo)}장 합성 — 보이스 {nar.get('voice')} · {eng['python']}")
    job.progress(0, len(todo), "음성 합성")

    cmd = [eng["python"], str(BRIDGE), str(job_p), str(res_p)]
    try:
        proc = subprocess.Popen(cmd, cwd=str(APP), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        done = 0
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("["):
                done += 1
                job.progress(done, len(todo), f"{done}/{len(todo)}")
            job.add_log("  " + line[:160])
            if job.canceled:
                proc.terminate()
                warn.append("사용자가 취소함")
                break
        proc.wait(timeout=eng["timeout_ms"] / 1000)
    except Exception as e:  # noqa: BLE001
        warn.append(f"합성 프로세스 실패: {type(e).__name__}: {str(e)[:160]}")

    res = ws.read_json(res_p, {}) or {}
    if res.get("error"):
        warn.append("엔진 오류: " + str(res["error"])[-300:])
        job.add_log("엔진 오류 — 자세한 내용은 " + str(res_p))

    for r in res.get("items") or []:
        no = str(r.get("no"))
        if r.get("error"):
            warn.append(f"{no}: {r['error'][:120]}")
            continue
        out[no] = {"source": "tts", "duration_sec": r.get("sec"),
                   "file": f"{step_name}/tts/{r.get('file')}"}

    missing = [int(k) for k in script if k not in out]
    if missing:
        warn.append(f"음성이 없는 장 {len(missing)}개: {missing[:12]}")

    total = round(sum(v.get("duration_sec") or 0 for v in out.values()), 1)
    job.add_log(f"음성 {len(out)}장 · 합계 {total:.0f}초 ({total / 60:.1f}분) "
                f"· 성우 {n_vo}장 · 합성 {len(out) - n_vo}장")

    # ★ **실측으로 초당 글자수를 되잡는다.**
    #   기본값 3.0 은 실제(voicewright F2 기준 5.7)의 절반이었다. 그 상태로는
    #   "이 발표 몇 분짜리인가" 가 두 배로 틀리고, 영상 길이 초과 판정도 전부
    #   거짓 경보가 된다. 한 번 재고 나면 다음부터는 맞는다.
    calib = _calibrate(script, out)
    if calib:
        cur = float((project.get("narration") or {}).get("chars_per_sec")
                    or cfg["narration"]["chars_per_sec"])
        if abs(calib - cur) / max(cur, 0.1) > 0.08:
            doc = ws.load_project(pid, slug)
            doc.setdefault("narration", {})["chars_per_sec"] = calib
            ws.save_project(pid, slug, doc)
            job.add_log(f"초당 글자수 보정: {cur} → {calib} (실측)")
            job.add_log("  대본 추정 길이가 다시 계산됩니다 — 대본을 다시 굽지 않아도 됩니다")

    # ★ 해시는 **지금 상태의 project 로** 적는다. 시작할 때 받은 `project` 로
    #   적으면 안 된다 — 바로 위에서 이 단계가 `narration.chars_per_sec` 을
    #   되써 넣는데, 그 값이 이 단계의 입력(`reads=["narration", …]`)이기 때문이다.
    #   옛 값으로 적으면 **방금 성공한 이 단계가 저장하는 순간 「낡음」이 된다.**
    #   화면에서는 18분짜리 음성 합성을 막 끝냈는데 "다시 해야 할 것: 음성 합성"
    #   이 떠서, 무엇을 더 눌러야 하는지 알 수 없었다(2026-08-14) —
    #   「낡음」은 앞 단계가 바뀌었을 때 떠야 뜻이 있다.
    return write_cache(pid, slug, "s10-tts",
                       input_hash=stage.input_hash(pid, slug,
                                                   ws.load_project(pid, slug)),
                       data={"slides": out, "engine": "voicewright",
                             "sample_rate": res.get("sample_rate"),
                             "total_sec": total},
                       code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s10-tts"].run = run
