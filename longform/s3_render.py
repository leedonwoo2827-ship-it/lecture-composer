"""s3 — 섹션 원고마다 backplate-studio 프로젝트를 만들고 모션 mp4 까지 굽는다.

섹션 하나의 흐름:
    create(project.json, image_fit=full)  →  s2c-capture(원고 구조 → 목차)
    → 덮어쓰기(overrides): 표지/맺음 drop·문구, 라벨 = 우리 판서, 도식 장 그림
    → s6-script(내레이션 = data-say)  → 그림(image_mode)  → s3b-images(도착 그림 수거)
    → s10-tts → s11-audio → s8-assemble → s12h-hyper  →  out/Lxx/parts/<sec>.mp4 (+ timing.json)

image_mode
    section   섹션(노트 h2)마다 bg_per_section 장(기본 3, 20강 약 150장) — 기본
    backplate 엔진 방식 그대로 — 장마다 Claude 가 장면·라벨 자리를 설계(s3a)하고 굽는다(20강 약 1,050장)
    shared    소주제(원고 h2 = 노트 h3)마다 첫 장만 codex 로 굽고 묶음이 공유(20강 약 300장)
    per-slide 장마다 굽는다(20강 약 1,050장)
    none      굽지 않는다 — 아이보리 판 + 도식 PNG + 라벨만

★ 라벨(화면 글자)은 s3a(Claude) 대신 **우리 판서(bullets)로 직접** 넣는다 — 시험 용어가
  그대로 화면에 나와야 하고, 장마다 Claude 를 부르지 않아도 된다.
★ 렌더 임시 프레임(ROOT/_render-tmp)은 섹션마다 지운다(1분 ≈ 0.81GB).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform import accounts
from longform.config import REPO, Job
from longform.notes import chars
from longform import theme as vtheme
from longform.raster import card_slide_themed, fit_card, render_many, svg_slide, svg_slide_themed
from longform.state import State, sha
from longform.util import log, read_json, run as run_cmd, warn, write_json

HELPER = REPO / "longform" / "bp_helper.py"


class CodexStopped(SystemExit):
    """codex 가 그림을 못 그려 **전체 작업을 멈춘다**(사용자 지시 2026-10-02: 아이보리 판으로 넘어가지 말 것)."""
# 라벨·도식 배치 규칙을 바꾸면 올린다 → 해당 섹션이 다시 렌더된다(그림은 이미 구운 것을 다시 쓴다)
LAYOUT_VERSION = 3
STAGES_TAIL = ["s3b-images", "s10-tts", "s11-audio", "s8-assemble", "s12h-hyper"]


class Backplate:
    def __init__(self, job: Job):
        self.dir = job.path(job.get("backplate.dir"))
        if not self.dir or not (self.dir / "tools" / "run_stage.py").exists():
            raise SystemExit(f"[error] 렌더 엔진이 없습니다: {self.dir} (레포의 engine/backplate 가 있어야 합니다)")
        py = self.dir / ".venv-app" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not py.exists():
            raise SystemExit(f"[error] 렌더 엔진 venv 가 없습니다: {py} (setup.bat 을 먼저)")
        self.py = py
        self.ws = job.bp_workspace
        self.ws.mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ, SHOWCASE_WORKSPACE=str(self.ws), BACKPLATE_DIR=str(self.dir),
                        PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        self.use_codex_slot(accounts.active_slot())

    def use_codex_slot(self, slot: Optional[str]) -> None:
        """그림(codex)을 굽는 계정 — 칸이 있으면 그 auth.json 을 엔진에 넘긴다(전역 ~/.codex 는 그대로)."""
        self.codex_slot = slot
        p = accounts.auth_path(slot)
        if p:
            self.env["CODEX_AUTH_PATH"] = str(p)
        else:
            self.env.pop("CODEX_AUTH_PATH", None)

    def bake_images(self, pid: int, pdir: Path, where: str, failover: bool = True,
                    wait_hours: float = 24) -> None:
        """s3c(그림 굽기) + 사용량 기록.

        한도(429·quota)에 걸려 그림이 비면 ① 다른 칸으로 바꿔 다시, ② 바꿀 칸이 없으면 **1시간마다 다시**
        (최대 wait_hours) — 며칠 무인으로 돌 때 그림 없이(아이보리 판) 넘어가지 않게.
        token_revoked(로그인 만료)는 기다려도 안 풀리므로 바로 넘어간다(계정 탭에서 다시 로그인).
        이미 구운 번호는 엔진이 건너뛰므로 다시 돌려도 남은 것만 굽는다.
        """
        import time as _t
        deadline = _t.time() + wait_hours * 3600
        tried = {self.codex_slot}
        while True:
            p = run_cmd([str(self.py), "tools/run_stage.py", str(pid), "s3c-images-run"],
                        cwd=self.dir, env=self.env, check=False, capture=True)
            out = (p.stdout or "") + (p.stderr or "")
            sys.stdout.write(out[-3000:])
            data = ((read_json(pdir / "_cache" / "s3c-images-run.json", {}) or {}).get("data") or {})
            made, failed = int(data.get("made") or 0), int(data.get("failed") or 0)
            low = out.lower()
            revoked = "token_revoked" in low or "refresh_token" in low and "만료" in out
            limited = any(k in low for k in ("429", "rate limit", "usage limit", "quota", "insufficient_quota")) or "한도" in out
            accounts.record_usage(self.codex_slot, made, failed, limited or revoked, where)
            if not failed:
                if p.returncode != 0:
                    raise SystemExit(f"[error] 그림 굽기 실패({p.returncode}) — {where}")
                return
            nxt = accounts.next_slot(self.codex_slot) if failover else None
            if nxt and nxt not in tried:
                warn(f"codex 칸 '{self.codex_slot}' 한도 — '{nxt}' 칸으로 바꿔 남은 그림을 굽습니다")
                tried.add(nxt)
                self.use_codex_slot(nxt)
                accounts.set_active(nxt)
                continue
            why = ("로그인 만료(token_revoked) — 계정 탭에서 그 칸을 다시 로그인하십시오" if revoked else
                   "사용 한도" if limited else "그림 굽기 실패")
            if revoked or not limited or _t.time() + 3600 > deadline:
                raise CodexStopped(f"[중지] codex 가 그림을 못 그려 작업을 멈춥니다 — {why} · 칸 '{self.codex_slot}' · {where}. "
                                   f"못 그린 그림 {failed}장. 해결한 뒤 다시 누르면 이어서 합니다(이미 그린 그림·끝난 강은 건너뜀).")
            warn(f"codex 한도 — 바꿀 칸이 없어 1시간 뒤 다시 굽습니다({where})")
            _t.sleep(3600)
            tried = {self.codex_slot}

    def helper(self, *args: str) -> Dict[str, Any]:
        p = run_cmd([str(self.py), str(HELPER), *args], cwd=self.dir, env=self.env, capture=True)
        line = next((l for l in p.stdout.splitlines() if l.startswith("@@JSON@@")), None)
        if not line:
            raise SystemExit(f"[error] bp_helper 응답 없음: {p.stdout[-800:]} {p.stderr[-800:]}")
        return json.loads(line[len("@@JSON@@"):])

    def helper_json(self, cmd: str, pid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            tmp = fh.name
        try:
            return self.helper(cmd, str(pid), tmp)
        finally:
            os.unlink(tmp)

    def stages(self, pid: int, *names: str, force: bool = False) -> None:
        cmd = [str(self.py), "tools/run_stage.py", str(pid), *names] + (["--force"] if force else [])
        run_cmd(cmd, cwd=self.dir, env=self.env)

    def clean_tmp(self) -> None:
        t = self.ws / "_render-tmp"
        if t.exists():
            shutil.rmtree(t, ignore_errors=True)


# ── 라벨 배치 ─────────────────────────────────────────────────────────────
def _sentences(say: str) -> int:
    return max(1, len([s for s in re.split(r"(?<=[.?!])\s+", say.strip()) if s]))


def labels_for(slide: Dict[str, Any], has_bg: bool, sub_band: bool = False,
               th: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """화면 글자(라벨) 자리. sub_band=True(자막을 화면에 구울 때)면 아래 14% 를 비운다."""
    if th:
        return labels_themed(slide, has_bg, sub_band, th)
    kind = slide.get("kind") or ""
    bl = [b for b in slide.get("bullets") or [] if b]
    ns = _sentences(slide["say"])
    # ★ 글자 뒤에 판(box)을 깔지 않는다 — 폭이 넓으면 판이 배경 그림을 덮는다(2026-10-02 실측: 오른쪽 그림 윗부분이 가려짐).
    #   테두리(후광)만 두고, 배경이 있으면 글자는 **왼쪽 56%** 안에만 둔다(배경 지시문이 그림을 오른쪽 아래에 두게 한다).
    cell = "line"
    w = 56 if has_bg else 86
    if kind == "example-q" and bl:
        return [{"head": bl[0], "sub": "\n".join(bl[1:]), "x": 6, "y": 15, "w": 88, "say_i": 1, "cell": cell}]
    if kind == "example-a" and bl:
        return [{"head": bl[0], "sub": "\n".join(bl[1:]), "x": 6, "y": 17, "w": 60 if has_bg else 88, "say_i": 1, "cell": cell}]
    if slide.get("fig"):
        bl = bl[:2]
        return [{"head": b, "sub": "", "x": 6, "y": (66 if sub_band else 77) + i * (8 if sub_band else 10), "w": 88,
                 "say_i": 1 + round(i * ns / max(1, len(bl))), "cell": cell} for i, b in enumerate(bl)]
    bl = bl[:4]
    return [{"head": b, "sub": "", "x": 7, "y": 17 + i * (15 if sub_band else 18), "w": w,
             "say_i": 1 + round(i * ns / max(1, len(bl))), "cell": cell} for i, b in enumerate(bl)]


def labels_themed(slide: Dict[str, Any], has_bg: bool, sub_band: bool, th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """테마 판 — 왼쪽 텍스트 열(키커·제목 아래)에 번호 목록. 오브젝트는 오른쪽(video_theme.obj_box).
    ★ 시각(say_i)은 어림이다 — 렌더 엔진의 sync 가 **라벨 글자를 말하는 순간**으로 다시 박는다."""
    kind = slide.get("kind") or ""
    bl = [b for b in slide.get("bullets") or [] if b]
    ns = _sentences(slide["say"])
    w = th["text_w"] - 4 if has_bg else 84
    if kind in ("example-q", "example-a") and bl:
        return [{"head": bl[0], "sub": "\n".join(bl[1:]), "x": 6.5, "y": 40, "w": w, "say_i": 1, "cell": "line"}]
    if slide.get("fig"):
        # 도식 장: 카드가 30~80% 를 쓰므로 라벨은 카드 아래 한 줄(자막 자리를 비우면 생략)
        if sub_band:
            return []
        return [{"head": bl[0], "sub": "", "x": 7, "y": 83.5, "w": 86, "say_i": 1, "cell": "line"}] if bl else []
    bl = bl[:4]
    step = 11.5 if sub_band else 13
    top = 41 if len(bl) <= 3 else 38
    return [{"head": b, "sub": "", "x": 6.5, "y": top + i * step, "w": w,
             "say_i": 1 + round(i * ns / max(1, len(bl))), "cell": "line"} for i, b in enumerate(bl)]


def object_prompt(group_title: str, lecture_title: str, th: Dict[str, Any]) -> str:
    """테마 판의 오브젝트 — 배경이 아니라 **투명 바탕의 사물 하나**. 바탕·덩어리는 hyper 가 그린다."""
    pal = ", ".join(f"{k} {th[k]}" for k in ("accent", "cobalt", "mustard", "sage", "deep"))
    return (f"자격증 이론 강의 영상에 얹을 **사물 일러스트 하나**. 주제: 「{group_title}」(강의: {lecture_title}). "
            "주제를 상징하는 구체적인 물건 하나를 고른다(예: 데이터베이스 원통, 서랍장, 열쇠, 돋보기, 깔때기, 퍼즐 조각, "
            "자물쇠, 표가 그려진 카드, 톱니바퀴, 저울, 나침반, 서류철 — 주제에 가장 어울리는 것으로). "
            "스타일: 굵고 살짝 흔들리는 **검은 먹선(손그림 잉크 라인)** 으로 외곽을 그린 플랫 채색 일러스트, "
            "면은 단순한 두 톤 음영과 짧은 흰 하이라이트 획, 아주 옅은 종이 그레인, 살짝 기울어진 3/4 각도. "
            f"팔레트: {pal}, 크림 {th['paper']}, 먹 {th['ink']}. "
            "**배경은 완전히 투명**하게 비운다 — 바닥·그림자 판·테두리 프레임·배경색 없음. "
            "사물이 정사각 캔버스의 75~85% 를 채우게 가운데 둔다. 글자·숫자·로고·사람 얼굴 없음.")


def chunk_groups(groups: List[Dict[str, Any]], n: int, title: str) -> List[Dict[str, Any]]:
    """소주제 묶음들을 순서대로 n 덩이로 — 덩이마다 슬라이드 수가 비슷하게, 소주제는 쪼개지 않는다."""
    n = max(1, min(n, len(groups)))
    total = sum(len(g["slides"]) for g in groups) or 1
    out: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []
    acc = 0
    for i, g in enumerate(groups):
        cur.append(g)
        acc += len(g["slides"])
        left_groups, left_chunks = len(groups) - i - 1, n - len(out) - 1
        if left_chunks > 0 and (acc >= total * (len(out) + 1) / n or left_groups == left_chunks):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"title": c[0]["title"] if c[0].get("sub_id") not in ("intro", "wrap") else title,
             "slides": [s for g in c for s in g["slides"]]} for c in out]


def bg_prompt(group_title: str, lecture_title: str) -> str:
    return (f"자격증 이론 강의 슬라이드의 배경 그림. 주제: 「{group_title}」(강의: {lecture_title}). "
            "아이보리(#F6F1E8) 바탕. 주제를 상징하는 단순한 플랫 일러스트를 **화면 오른쪽 아래 25% 영역에만** 작게 둔다. "
            "위쪽 10% 띠와 왼쪽·가운데 75% 영역은 글자가 얹히므로 아이보리 단색으로 비워 둔다. "
            "글자·숫자·로고·사람 얼굴 없음. 진한 파랑(#1F4E79)·밝은 파랑(#9DC3E6) 포인트, 은은하고 차분한 톤.")


# ── 섹션 하나 렌더 ────────────────────────────────────────────────────────
def render_section(job: Job, bp: Backplate, state: State, L: Dict[str, Any], sec_i: int,
                   n_secs: int, force: bool) -> Optional[Path]:
    lid = L["id"]
    sid = L["sections"][sec_i]["id"]
    md = job.manuscripts_dir / lid
    jf, hf = md / f"{sid}.json", md / f"{sid}.html"
    if not jf.exists():
        warn(f"{lid} {sid} 원고가 없습니다 — s2 먼저")
        return None
    man = read_json(jf)
    mode = job.get("backplate.image_mode", "section")
    th = vtheme.get(job)                                    # None = 원래 룩(ivory)
    first, last = sec_i == 0, sec_i == n_secs - 1
    parts = job.out_dir / lid / "parts"
    out_mp4 = parts / f"{sid}.mp4"
    # ★ 하단 비움(자막 자리)을 해시에 넣는다 — 켜고 끄면 해당 섹션이 다시 렌더된다
    h = sha(hf, jf, mode, job.get("backplate.voice"), job.get("backplate.speed"), first, last, LAYOUT_VERSION,
            *(["sub_band"] if (job.get("subtitles.reserve_bottom", True) or job.get("subtitles.burn_in", False)) else []),
            # ★ 표 도식 모양을 바꾸면(2026-10-02) 표가 든 섹션만 다시 렌더된다
            *(["table_v2"] if any((f or "").lstrip().lower().startswith("<table") for f in man.get("figs") or []) else []),
            # ★ 영상 테마를 바꾸면 섹션이 다시 렌더된다(그림은 캐시를 다시 쓴다)
            *([f"theme:{th['name']}:2"] if th else []))
    key = f"s3:{sid}"
    if not force and state.done(lid, key, h) and out_mp4.exists():
        log(f"{lid} {sid} 렌더 — 그대로")
        return out_mp4

    # 0) 지난번에 중지·종료로 남은 렌더 임시 프레임(수 GB)을 먼저 비운다
    bp.clean_tmp()

    # 1) 프로젝트 — 있으면 원고만 갈아 끼운다
    prev = state.get(lid, key)
    pid = prev.get("pid")
    if pid:
        info = bp.helper("outline", str(pid)) if (Path(prev.get("dir", "")) / "_cache").exists() else None
    else:
        info = None
    if not info:
        title = f"{man['label']} — {man['title']}"
        args = {"title": title, "slug": f"{job.name}-{lid}-{sid}".lower(), "html": str(hf),
                "voice": job.get("backplate.voice"), "speed": job.get("backplate.speed"),
                "tag": {"job": job.name, "lecture": lid, "section": sid}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(args, fh, ensure_ascii=False)
            tmp = fh.name
        try:
            created = bp.helper("create", tmp)
        finally:
            os.unlink(tmp)
        pid = created["pid"]
        pdir = Path(created["dir"])
    else:
        pdir = Path(info["dir"])
        # 원고 사본 교체(참고 폴더의 html 하나)
        for f in (pdir / "00_기획" / "참고").glob("*.html"):
            shutil.copy2(hf, f)
    log(f"{lid} {sid} → backplate 프로젝트 {pid} ({pdir.name})")

    # 1b) 영상 테마 — 프로젝트 칸에 적으면 조립(s8)이 덱에 싣고 모션(s12h)이 그 룩으로 굽는다
    from longform.s2_manuscript import course
    c = course(job)
    bp.helper_json("project", pid, {
        "video_theme": th["name"] if th else "",
        "theme_logo": c["short"] if th else "",
        "theme_caption": (f"{c['series']} — L{int(L['no']):02d}" if th else "")})

    # 2) 구조
    bp.stages(pid, "s2c-capture")
    outline = bp.helper("outline", str(pid))["slides"]
    by_id = {s["data_id"]: s["no"] for s in outline if s.get("data_id")}
    cover = next((s["no"] for s in outline if s.get("kind") == "cover"), None)
    closing = next((s["no"] for s in outline if s.get("kind") == "closing"), None)

    slides = [(g, s) for g in man["groups"] for s in g["slides"]]
    missing = [s["id"] for _, s in slides if s["id"] not in by_id]
    if missing:
        warn(f"{lid} {sid} 목차에 없는 장 {len(missing)}개(600px 잘림 등): {missing[:3]}")

    # 3) 덮어쓰기
    ov: Dict[str, Any] = {"slides": {}}
    # ★ backplate 는 h1 의 data-say/data-outro-say 를 읽지 않고(표지·맺음은 고정 문구),
    #   h3 의 data-read 도 버린다(발음을 자막에서 다시 만든다 — s6_script.py:303).
    #   원고의 자막·발음이 그대로 나가도록 **덮어쓰기 narration 으로 못 박는다**:
    #   srt_text = data-say(자막), text = data-read(TTS 입력). text 를 안 주면 자막에서 만든다.
    def narr(say: str, read: str) -> Dict[str, str]:
        d = {"srt_text": say}
        if read.strip():
            d["text"] = read
        return d

    if cover:
        cv = man.get("cover") or {}
        if first and cv.get("say"):
            ov["slides"][str(cover)] = {"title": f"{L['no']}강 · {L['title']}",
                                        "narration": narr(cv["say"], cv.get("read", ""))}
        else:
            ov["slides"][str(cover)] = {"drop": True, "narration": {"srt_text": "", "text": ""}}  # 빠지는 장은 음성도 만들지 않는다
    if closing:
        oc = man.get("outro") or {}
        if last and oc.get("say"):
            ov["slides"][str(closing)] = {"narration": narr(oc["say"], oc.get("read", ""))}
        else:
            ov["slides"][str(closing)] = {"drop": True, "narration": {"srt_text": "", "text": ""}}  # 빠지는 장은 음성도 만들지 않는다

    img_dir = pdir / "09_이미지"
    img_dir.mkdir(parents=True, exist_ok=True)
    has_bg = mode in ("shared", "section", "per-slide")
    # 덩이(바탕이 바뀌는 단위) — section 모드면 배경 덩이와 같게, 아니면 소주제마다
    chunks = (chunk_groups(man["groups"], int(job.get("backplate.bg_per_section", 3)), man["title"])
              if mode == "section" else man["groups"])
    chunk_of: Dict[str, int] = {s["id"]: ci for ci, g in enumerate(chunks) for s in g["slides"]}
    group_of: Dict[str, str] = {s["id"]: g["title"] for g in man["groups"] for s in g["slides"]}
    gidx: Dict[str, int] = {g["title"]: gi for gi, g in enumerate(man["groups"], 1)}
    figs = man.get("figs") or []
    if th:
        from longform import redraw
        figs = redraw.redraw_all(job, figs)
    # ★ 자막(SRT)은 mp4 와 함께 올려 플레이어가 **화면 하단**에 띄운다 → 라벨·도식·문제 카드는 아래 14% 를 비운다
    sub_band = bool(job.get("subtitles.reserve_bottom", True) or job.get("subtitles.burn_in", False))
    fig_jobs = []
    for g, s in slides:
        no = by_id.get(s["id"])
        if not no:
            continue
        ov["slides"][str(no)] = {"narration": narr(s["say"], s.get("read", ""))}
        if mode != "backplate":
            # backplate 방식에서는 라벨(자리·문구)도 엔진의 이미지 설계(s3a)가 그림과 함께 정한다
            ov["slides"][str(no)]["labels"] = labels_for(s, has_bg, sub_band, th)
        is_fig = bool(s.get("fig") and 1 <= int(s["fig"]) <= len(figs))
        if th:
            gt = group_of.get(s["id"], "")
            ov["slides"][str(no)]["look"] = {
                "chunk": chunk_of.get(s["id"], 0),
                "kind": "card" if s.get("card") else "fig" if is_fig else "body",
                "kicker": f"{gidx.get(gt, 1):02d} — {gt}" if gt else ""}
        if s.get("card"):
            # 문제 장 — 카드 이미지가 화면 전부다(SQL·그림·표·보기). 라벨은 끈다
            card = (card_slide_themed(s["card"], th, 31, 16 if sub_band else 11) if th
                    else fit_card(s["card"], 16 if sub_band else 5))
            fig_jobs.append((card, img_dir / f"{no:03d}.png"))
            ov["slides"][str(no)]["labels"] = []
        elif is_fig:
            fig = figs[int(s["fig"]) - 1]
            fig_jobs.append((svg_slide_themed(fig, th, 31, 79 if not sub_band else 80) if th else
                             svg_slide(fig, bottom_pct=64 if sub_band else 74), img_dir / f"{no:03d}.png"))
    bp.helper_json("override", pid, ov)

    # 4) 내레이션(data-say) — 표지/맺음 외에는 Claude 를 부르지 않는다
    bp.stages(pid, "s6-script")

    # 5) 그림
    fig_nos = {int(p.stem) for _, p in fig_jobs}
    render_many(fig_jobs, theme=th["name"] if th else None)  # 도식 장은 도식 PNG(테마면 투명 바탕)
    if mode == "backplate":
        # 엔진 방식 그대로: 이미지 JSON 만들기(s3a, Claude 가 장마다 장면·라벨 자리 설계) → 그림 굽기(s3c).
        # 도식·문제 카드 장은 위에서 이미 PNG 가 있으므로 s3c 가 건너뛴다(있는 번호는 굽지 않음).
        bp.stages(pid, "s3a-imgprompt", "s3b-images")
        bp.bake_images(pid, pdir, f"{job.name}/{lid}/{sid}", bool(job.get("accounts.codex_failover", True)),
                       float(job.get("accounts.codex_wait_hours", 0)))
    elif has_bg:
        rows, followers = [], {}
        groups = man["groups"]
        if mode == "section":
            # 섹션(노트 h2)마다 배경 N장(기본 3) — 소주제 경계에서 슬라이드 수가 고르게 N덩이로 나눈다
            groups = chunk_groups(groups, int(job.get("backplate.bg_per_section", 3)), man["title"])
        for g in groups:
            nos = [by_id[s["id"]] for s in g["slides"] if s["id"] in by_id and by_id[s["id"]] not in fig_nos]
            if not nos:
                continue
            leads = nos if mode == "per-slide" else nos[:1]
            for n in leads:
                prompt = object_prompt(g["title"], L["title"], th) if th else bg_prompt(g["title"], L["title"])
                rows.append({"n": n, "title": g["title"], "type": "illustration" if th else "photo",
                             "level": "", "place": "", "prompt": prompt,
                             "negative": "글자, 숫자, 로고, 워터마크" + (", 배경색, 바닥, 테두리" if th else ""),
                             "keywords": [], "file": f"{n:03d}.png", "data_id": "", "labels": []})
            if mode in ("shared", "section"):
                followers[nos[0]] = nos[1:]
        if th:
            # ★ 오브젝트 캐시 — 같은 주제(프롬프트)는 강·섹션을 넘어 다시 쓴다(codex 사용량을 아낀다).
            #   이미 있는 번호는 엔진(s3c)이 건너뛴다.
            cache = job.dir / "objects"
            for r in rows:
                c = cache / f"{sha(r['prompt'])[7:23]}.png"
                if c.is_file() and not (img_dir / r["file"]).exists():
                    shutil.copy2(c, img_dir / r["file"])
        write_json(img_dir / "이미지프롬프트.json", {
            "deck": f"{lid}-{sid}", "aspect": "1:1" if th else "16:9", "count": len(rows), "prompts": rows,
            "style_hint": ("먹선 손그림 + 플랫 채색 사물 하나, 투명 바탕" if th else
                           "진한 파랑(#1F4E79)과 밝은 파랑(#9DC3E6) 중심, 플랫 벡터, 넉넉한 여백"),
            "target_box": ("1:1 투명 PNG — 사물만, 바탕 없음" if th else
                           "16:9 (1920×1080) — 위 10% 제목 띠와 왼쪽·가운데는 비운다")})
        if rows and any(not (img_dir / r["file"]).exists() for r in rows):
            if th:
                bp.env["CODEX_IMAGE_BACKGROUND"] = "transparent"
            try:
                bp.bake_images(pid, pdir, f"{job.name}/{lid}/{sid}", bool(job.get("accounts.codex_failover", True)),
                               float(job.get("accounts.codex_wait_hours", 0)))
            finally:
                bp.env.pop("CODEX_IMAGE_BACKGROUND", None)
        if th:
            (job.dir / "objects").mkdir(parents=True, exist_ok=True)
            for r in rows:
                c = job.dir / "objects" / f"{sha(r['prompt'])[7:23]}.png"
                if (img_dir / r["file"]).is_file() and not c.exists():
                    shutil.copy2(img_dir / r["file"], c)
        for lead, fol in followers.items():
            src = img_dir / f"{lead:03d}.png"
            if src.exists():
                for n in fol:
                    shutil.copy2(src, img_dir / f"{n:03d}.png")
            else:
                warn(f"{lid} {sid} 배경 {lead:03d}.png 가 구워지지 않았습니다 — 아이보리 판으로 갑니다")
        if th and rows:
            # 강 표지·맺음도 오브젝트를 얹는다 — 첫 덩이·끝 덩이 것을 빌린다
            for no, src_n in ((cover, rows[0]["n"]), (closing, rows[-1]["n"])):
                src = img_dir / f"{src_n:03d}.png"
                if no and src.is_file() and not (img_dir / f"{no:03d}.png").exists():
                    shutil.copy2(src, img_dir / f"{no:03d}.png")

    # 6) 소리·자막·조립·모션
    bp.stages(pid, *STAGES_TAIL)

    mp4s = sorted((pdir / "11_완성").glob("*-motion.mp4"), key=lambda p: p.stat().st_mtime)
    if not mp4s:
        raise SystemExit(f"[error] {lid} {sid} 모션 mp4 가 없습니다: {pdir / '11_완성'}")
    parts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp4s[-1], out_mp4)

    # 7) 이어붙이기용 타이밍 — s11(자막 시각)과 s8(덱: drop·오디오 길이)
    deck = read_json(pdir / "10_덱" / "deck.json", {}) or {}
    s11 = ((read_json(pdir / "_cache" / "s11-audio.json", {}) or {}).get("data") or {}).get("slides") or {}
    gid = {s["id"]: g["title"] for g, s in slides}
    no2id = {v: k for k, v in by_id.items()}
    timing = []
    for d in deck.get("slides") or []:
        if d.get("drop"):
            continue
        src_no = int(d.get("src_no") or d.get("no") or 0)
        au = float((d.get("audio") or {}).get("sec") or 0)
        srt = (s11.get(str(src_no)) or {}).get("srt") or ""
        timing.append({"no": src_no, "data_id": no2id.get(src_no, ""), "title": d.get("title") or "",
                       "group": gid.get(no2id.get(src_no, ""), ""), "audio_sec": au,
                       "srt": str(pdir / srt) if srt else ""})
    write_json(parts / f"{sid}.timing.json", {"mp4": str(out_mp4), "project": str(pdir), "slides": timing})
    bp.clean_tmp()
    state.mark(lid, key, h, pid=pid, dir=str(pdir))
    log(f"{lid} {sid} 완료 → {out_mp4}")
    return out_mp4


def run(job: Job, only: Optional[List[str]] = None, force: bool = False,
        sections_limit: Optional[int] = None) -> None:
    cur = read_json(job.dir / "curriculum.json")
    if not cur:
        raise SystemExit("[error] curriculum.json 이 없습니다 — 먼저 s1")
    bp = Backplate(job)
    state = State(job)
    for L in cur["lectures"]:
        if only and L["id"] not in only:
            continue
        n = len(L["sections"])
        m = min(n, sections_limit) if sections_limit else n
        for i in range(m):
            render_section(job, bp, state, L, i, n, force)
