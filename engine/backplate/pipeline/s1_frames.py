# -*- coding: utf-8 -*-
"""S1 프레임 추출 — 결정론. Claude 를 부르지 않는다.

알고리즘은 `mimo-video-script/make_script.py::extract_frames` 를 옮겼다.
**MiMo API 는 쓰지 않는다** — 가져온 건 ffmpeg 기반 추출 로직뿐이고,
비전 호출은 S3 에서 Claude 구독 OAuth 로 나간다.

  1) 씬 전환 감지 + 실제 타임스탬프 획득
  2) 씬 전환이 희소하면 고정 간격 앵커로 보충
  3) 시간순 정렬 → 너무 가까운 것 솎기 → 상한까지 균등 데시메이션

**236.7초짜리 5번 영상이 이 알고리즘의 존재 이유다.** 균등 분할로 12장을 뽑으면
20초마다 한 장이라 의미 있는 순간(폼 제출, 결과 렌더)을 놓친다. 씬 전환을 따라가면
화면이 바뀌는 지점에 프레임이 붙는다.

원본과 다른 점:
  - 씬 감지에서 **파일을 쓰지 않는다**(`-f null -`). 원본은 scene_*.jpg 를 다 쓰고
    타임스탬프만 골라 썼는데, 236초 영상이면 수십 장을 썼다 지우게 된다.
  - 최종 타임스탬프가 정해진 뒤 **그 지점만** 두 벌로 뽑는다:
      frames/  1600w  화면 표시용
      vision/  1024w  Claude 로 보낼 것 (base64 크기 = 비용)
  - 파생 파일명은 전부 ascii(`v1-f03.webp`). 한글은 JSON 값에만 산다.
  - 이미 있는 파일은 건너뛴다(resume).
"""
from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core import config, workspace as ws
from pipeline.registry import STAGES, write_cache

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
PTS = re.compile(r"pts_time:([0-9.]+)")


def _run(args: List[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    """★ 항상 인자 리스트 + shell=False. 명령 문자열을 만들지 않으므로
    한글 경로가 cmd.exe 파싱을 거치지 않는다 — 인코딩 사고가 원천 차단된다."""
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, shell=False,
                          creationflags=CREATE_NO_WINDOW)


def probe(video: Path) -> Tuple[float, int, int, bool]:
    """(길이초, 가로, 세로, 오디오유무)"""
    r = _run(["ffprobe", "-v", "error", "-print_format", "json",
              "-show_format", "-show_streams", str(video)], timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {(r.stderr or '')[-300:]}")
    import json

    j = json.loads(r.stdout)
    dur = float(j.get("format", {}).get("duration") or 0.0)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    a = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
    return dur, int(v.get("width") or 0), int(v.get("height") or 0), a


SCORE = re.compile(r"pts_time:([0-9.]+)[\s\S]{0,80}?lavfi\.scene_score=([0-9.]+)")


def scene_scores(video: Path, cfg: Dict[str, Any]) -> List[Tuple[float, float]]:
    """[(초, 변화점수)] 전체. **절대 임계값을 쓰지 않는다.**

    ★ 원본(mimo-video-script)은 `gt(scene,0.35)` 로 하드컷을 찾는다. 편집된 영상엔
      맞지만 **화면녹화에는 안 맞는다** — 타이핑·스크롤은 변화가 완만해서 점수가
      0.35 를 넘지 않는다. 실제로 236.7초 영상의 최댓값이 0.071 이었고, 감지가
      조용히 0개를 돌려주며 앵커 폴백만 돌았다.

      그래서 점수를 전부 받아 와 **상대적인 봉우리**를 고른다. 하드컷 영상이면
      큰 값들이, 화면녹화면 작지만 분명한 변화들이 뽑힌다. 콘텐츠 종류에
      상관없이 같은 코드가 동작한다.

    비용: 저해상(320w) + 4fps 로 샘플링해 한 패스만 돈다(236초 영상에 10초).
    """
    fps = float(cfg.get("sample_fps", 4))
    r = _run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(video),
              "-vf", f"fps={fps},scale=320:-2,select='gte(scene,0)',"
                     f"metadata=print:file=-",
              "-an", "-f", "null", "-"], timeout=900)
    out: List[Tuple[float, float]] = []
    for m in SCORE.finditer(r.stdout or ""):
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def pick_times(duration: float, scores: List[Tuple[float, float]],
               cfg: Dict[str, Any], want: int) -> Tuple[List[float], str]:
    """변화가 큰 지점부터 욕심껏 고르되 서로 min_gap 이상 떨어뜨린다.

    반환: (시각 리스트, 어떻게 골랐는지)
    """
    # ★ 최소 간격은 고정이 아니라 **영상 길이에 비례**해야 한다.
    #   화면이 한 번 바뀌면 봉우리가 보통 둘로 나온다(변화 시작·끝). 236초 영상에서
    #   1.5초 간격이면 31.0/33.0 처럼 거의 같은 화면이 짝으로 뽑혀 12장 중 절반이
    #   중복이 된다 — 실제로 그랬다. 길이/장수의 1/3 을 하한으로 둔다.
    min_gap = max(float(cfg["min_gap_sec"]), duration / max(want, 1) / 3.0)
    edge = min(1.0, duration * 0.05)          # 맨 앞/뒤는 보통 빈 화면이라 피한다

    usable = [(t, s) for t, s in scores if edge <= t <= duration - edge * 0.5]
    peak = max((s for _, s in usable), default=0.0)

    # 변화가 사실상 없는 영상(정지 화면 녹화)이면 균등 분할이 맞다.
    if peak < 0.004 or len(usable) < 3:
        n = max(3, min(want, int(duration // 2) or 3))
        return [duration * (i + 0.5) / n for i in range(n)], "균등분할(변화없음)"

    picked: List[float] = []
    for t, _s in sorted(usable, key=lambda x: -x[1]):
        if len(picked) >= want:
            break
        if all(abs(t - p) >= min_gap for p in picked):
            picked.append(t)

    # 봉우리가 부족하면 빈 구간을 균등 분할로 메운다 —
    # 앞부분만 몰려 있고 뒤가 통째로 비는 것을 막는다.
    if len(picked) < want and duration > 0:
        for i in range(want):
            t = duration * (i + 0.5) / want
            if len(picked) >= want:
                break
            if all(abs(t - p) >= min_gap for p in picked):
                picked.append(t)

    picked.sort()
    return picked, f"변화봉우리(최대 {peak:.3f})"


def grab(video: Path, t: float, out: Path, width: int, quality: int) -> bool:
    """한 시점을 webp 로. 이미 있으면 건너뛴다(resume)."""
    if out.is_file() and out.stat().st_size > 500:
        return True
    out.parent.mkdir(parents=True, exist_ok=True)
    r = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
              "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
              "-vf", f"scale={width}:-2:flags=lanczos",
              "-c:v", "libwebp", "-quality", str(quality),
              "-compression_level", "4", str(out)], timeout=120)
    return r.returncode == 0 and out.is_file()


def _resolve(video_dir: Path, name: str) -> Path | None:
    """매니페스트의 파일명 ↔ 디스크. macOS 에서 온 파일은 NFD 라 == 이 실패한다."""
    want = unicodedata.normalize("NFC", name)
    for f in video_dir.iterdir():
        if f.is_file() and unicodedata.normalize("NFC", f.name) == want:
            return f
    return None


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()["frames"]
    stage = STAGES["s1-frames"]
    # ★ 영상은 **없어도 된다.** 레포만으로도 발표는 나온다 — 로컬 앱이나
    #   플러그인처럼 보여 줄 화면이 아직 없는 경우가 실제로 있다.
    #   예전엔 여기서 `Path(None)` 으로 터졌다(TypeError). 건너뛰는 게 맞다.
    raw_dir = (project.get("video_dir") or "").strip()
    items = [it for it in project.get("items", []) if it.get("include", True)]
    if not raw_dir or not items:
        job.add_log("화면 녹화가 없습니다 — 건너뜁니다")
        job.add_log("나중에 찍어서 폴더에 넣고 이 단계를 다시 돌리면 항목이 늡니다")
        return write_cache(pid, slug, "s1-frames",
                           input_hash=stage.input_hash(pid, slug, project),
                           data={"items": {}}, code_version=stage.code_version,
                           status="skipped")

    video_dir = Path(raw_dir)
    if not video_dir.is_dir():
        raise RuntimeError(f"영상 폴더가 없습니다: {video_dir}")

    job.progress(0, len(items), "준비")

    disp_dir = ws.step_dir(pid, slug, "frames")
    vis_dir = ws.sub_dir(pid, slug, "frames", ws.VISION)

    out: Dict[str, Any] = {"items": {}}
    for n, it in enumerate(items, 1):
        if job.canceled:
            break
        iid = it["id"]
        src = _resolve(video_dir, it["file"])
        if src is None:
            job.add_log(f"{iid}: 파일 없음 — {it['file']}")
            continue

        job.progress(n - 1, len(items), f"{iid} 분석")
        dur, w, h, has_audio = probe(src)
        scores = scene_scores(src, cfg)
        want = int(it.get("frame_count") or cfg["max_frames"])
        times, how = pick_times(dur, scores, cfg, want)
        job.add_log(f"{iid}: {dur:.1f}s · 샘플 {len(scores)}개 · {how} → {len(times)}장")

        frames = []
        for i, t in enumerate(times, 1):
            if job.canceled:
                break
            fid = f"{iid}-f{i:02d}"
            d = disp_dir / f"{fid}.webp"
            v = vis_dir / f"{fid}.webp"
            ok = grab(src, t, d, cfg["display_width"], 80)
            ok = grab(src, t, v, cfg["vision_width"], 62) and ok
            if not ok:
                job.add_log(f"  {fid}: 추출 실패 (t={t:.2f})")
                continue
            frames.append({
                "id": fid, "t_sec": round(t, 3),
                "file": f"{ws.STEPS['frames'][0]}/{fid}.webp",
                "vision": f"{ws.STEPS['frames'][0]}/{ws.VISION}/{fid}.webp",
                "bytes": d.stat().st_size,
            })
            job.progress(n - 1, len(items), f"{iid} {i}/{len(times)}장")

        out["items"][iid] = {
            "source_label": it["file"],
            "duration_sec": round(dur, 3),
            "width": w, "height": h, "has_audio": has_audio,
            "sample_count": len(scores),
            "peak_score": round(max((s for _, s in scores), default=0.0), 4),
            "pick_method": how,
            "frames": frames,
        }
        job.progress(n, len(items), f"{iid} 완료")

    total = sum(len(v["frames"]) for v in out["items"].values())
    job.add_log(f"총 {len(out['items'])}개 항목 · {total}장")

    return write_cache(pid, slug, "s1-frames",
                       input_hash=stage.input_hash(pid, slug, project),
                       data=out, code_version=stage.code_version,
                       status="ok" if not job.canceled else "degraded")


STAGES["s1-frames"].run = run
