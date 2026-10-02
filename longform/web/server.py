"""Lecture Composer 웹앱 — run.bat(인자 없이)이 띄운다.  http://127.0.0.1:5190

★ 화면은 **CLI 를 대신 눌러 주는 리모컨**이다. 실제 일은 `python -m longform <단계>` 하위 프로세스가
  하고, 화면은 그 로그를 흘려 보여 준다. 그래서 화면에서 한 일과 CLI 에서 한 일이 늘 같다.
★ 한 번에 하나만 돈다(렌더·업로드가 겹치면 디스크·브라우저가 엉킨다).
★ 127.0.0.1 에만 묶는다 — 유튜브 로그인 프로필을 다루는 앱이다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from longform.config import REPO, load_job
from longform.report import rows
from longform.util import read_json

STATIC = Path(__file__).resolve().parent / "static"
LOG = REPO / "logs" / "web-run.log"
STAGES = {"propose", "examples", "claim", "release", "me", "pack", "plan", "compose", "render", "stitch", "meta", "login", "publish",
          "register", "book", "textbook", "all", "make", "status"}

app = FastAPI(title="Lecture Composer")


class Runner:
    """하위 프로세스 하나. 로그는 파일로 받아 화면이 offset 으로 읽어 간다."""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.cmd: List[str] = []
        self.started = 0.0
        self.ended = 0.0
        self.code: Optional[int] = None
        self.lock = threading.Lock()

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def start(self, args: List[str]) -> None:
        with self.lock:
            if self.running():
                raise HTTPException(409, "이미 실행 중입니다 — 끝나거나 중지한 뒤 다시 누르십시오")
            LOG.parent.mkdir(parents=True, exist_ok=True)
            fh = LOG.open("w", encoding="utf-8")
            fh.write(f"$ run.bat {' '.join(args)}\n")
            fh.flush()
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
            self.proc = subprocess.Popen([sys.executable, "-m", "longform", *args], cwd=str(REPO),
                                         stdout=fh, stderr=subprocess.STDOUT, env=env)
            self.cmd, self.started, self.ended, self.code = args, time.time(), 0.0, None
            threading.Thread(target=self._wait, args=(fh,), daemon=True).start()

    def _wait(self, fh) -> None:
        code = self.proc.wait()
        self.code, self.ended = code, time.time()
        fh.write(f"\n[종료 코드 {code}]\n")
        fh.close()

    def stop(self) -> None:
        if self.running():
            self.proc.terminate()

    def info(self) -> Dict[str, Any]:
        return {"running": self.running(), "cmd": self.cmd, "started": self.started,
                "ended": self.ended, "code": self.code}


RUN = Runner()


def _job(name: str):
    try:
        from longform.config import default_job
        return load_job(name or default_job())
    except SystemExit as e:
        raise HTTPException(404, str(e))


# ── 화면 ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


# ── 잡 · 상태 ─────────────────────────────────────────────────────────────
@app.get("/api/jobs")
def jobs() -> List[str]:
    return sorted(p.name for p in (REPO / "jobs").iterdir()
                  if p.is_dir() and (p / "job.json").exists() and not p.name.startswith("_"))


@app.get("/api/status")
def status(job: str = "") -> Dict[str, Any]:
    from longform import team
    j = _job(job)
    ids = read_json(j.out_dir / "youtube_ids.json", {}) or {}
    bk = j.out_dir / "book"
    return {"job": job, "title": j.get("title"), "rows": rows(j), "run": RUN.info(), "me": team.me(),
            "has_input": (j.input_dir / "notes").exists() or (j.input_dir / "scripts").exists(),
            "has_curriculum": (j.dir / "curriculum.json").exists(),
            "uploaded": len(ids),
            "book": f"out/book/{j.name}.epub" if (bk / f"{j.name}.epub").exists() else "",
            "book_html": f"out/book/{j.name}.html" if (bk / f"{j.name}.html").exists() else "",
            "book_md": f"out/book/{j.name}.md" if (bk / f"{j.name}.md").exists() else "",
            "settings": {"target_min": j.get("curriculum.target_min"),
                         "lectures": sum((j.get("curriculum.lectures_per_subject") or {}).values()),
                         "image_mode": j.get("backplate.image_mode"), "web": j.get("enrich.web"),
                         "visibility": j.get("youtube.visibility"), "handle": j.get("youtube.handle")}}


# ── 목표서 · 편성표 (JSON 그대로 편집) ────────────────────────────────────
def _json_file(job: str, which: str) -> Path:
    j = _job(job)
    f = {"job": j.dir / "job.json", "local": j.dir / "job.local.json",
         "curriculum": j.dir / "curriculum.json"}.get(which)
    if not f:
        raise HTTPException(400, "which = job | local | curriculum")
    return f


@app.get("/api/json", response_class=PlainTextResponse)
def get_json(job: str, which: str) -> str:
    f = _json_file(job, which)
    return f.read_text(encoding="utf-8") if f.exists() else ("{}" if which == "local" else "")


@app.put("/api/json")
async def put_json(job: str, which: str, request: Request) -> Dict[str, Any]:
    f = _json_file(job, which)
    text = (await request.body()).decode("utf-8")
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON 형식 오류: {e}")
    if f.exists():
        shutil.copy2(f, f.with_suffix(f.suffix + ".bak"))
    f.write_text(text, encoding="utf-8")
    return {"ok": True, "saved": str(f.relative_to(REPO))}


# ── 원고 목록 ─────────────────────────────────────────────────────────────
@app.get("/api/manuscripts")
def manuscripts(job: str, lid: str) -> List[Dict[str, Any]]:
    j = _job(job)
    cur = read_json(j.dir / "curriculum.json", {}) or {}
    L = next((x for x in cur.get("lectures", []) if x["id"] == lid), None)
    if not L:
        raise HTTPException(404, lid)
    out = []
    for s in L["sections"]:
        m = read_json(j.manuscripts_dir / lid / f"{s['id']}.json", None)
        part = j.out_dir / lid / "parts" / f"{s['id']}.mp4"
        out.append({"id": s["id"], "title": s["title"], "target_chars": s["target_chars"],
                    "html": f"manuscripts/{lid}/{s['id']}.html" if m else "",
                    "slides": sum(len(g["slides"]) for g in m["groups"]) if m else 0,
                    "say_chars": (m or {}).get("say_chars", 0), "est_sec": (m or {}).get("est_sec", 0),
                    "figs": len((m or {}).get("figs") or []), "figs_new": (m or {}).get("figs_new", 0),
                    "from_script": (m or {}).get("from_script", False),
                    "sources": len((m or {}).get("sources") or []),
                    "part": f"out/{lid}/parts/{s['id']}.mp4" if part.exists() else ""})
    return out


# ── 파일(원고 HTML·썸네일·mp4·epub) — 잡 폴더 밖으로는 못 나간다 ────────────
@app.get("/files/{job}/{path:path}")
def files(job: str, path: str):
    j = _job(job)
    base = j.dir.resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, path)
    return FileResponse(str(f))


# ── 원천 파일 넣기(끌어다 놓기) ───────────────────────────────────────────
#   kind      저장 위치                        목표서에 반영
#   notes     input/notes/<이름>.html          inputs.notes   (파일 이름순 = 부 순서)
#   scripts   input/scripts/<이름>.html        inputs.scripts (파일 이름순 — 노트와 같은 순서로)
#   rounds    input/rounds/mNN.json            inputs.rounds_dir
#   review    input/review.html                register.review_html
KINDS = {"notes": (".html", ".htm"), "scripts": (".html", ".htm"), "rounds": (".json",), "review": (".html", ".htm")}


def _safe_name(name: str) -> str:
    import re as _re
    n = Path(name).name.strip()
    if not n or n.startswith(".") or _re.search(r'[<>:"/\\|?*\x00-\x1f]', n):
        raise HTTPException(400, f"쓸 수 없는 파일 이름: {name}")
    return n


def _sync_inputs(j) -> None:
    """input/ 폴더에 실제로 있는 파일로 목표서의 inputs 를 다시 적는다(파일이 기준이다)."""
    f = j.dir / "job.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    rel = lambda p: p.relative_to(REPO).as_posix()  # noqa: E731
    ins = doc.setdefault("inputs", {})
    ins["notes"] = [rel(p) for p in sorted((j.input_dir / "notes").glob("*.htm*"))]
    ins["scripts"] = [rel(p) for p in sorted((j.input_dir / "scripts").glob("*.htm*"))]
    ins["rounds_dir"] = rel(j.input_dir / "rounds")
    rv = j.input_dir / "review.html"
    reg = doc.setdefault("register", {})
    reg["review_html"] = rel(rv) if rv.exists() else ""
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _describe(kind: str, p: Path) -> Dict[str, Any]:
    """넣은 파일이 엔진이 읽을 수 있는 모양인지 바로 보여 준다."""
    info: Dict[str, Any] = {"name": p.name, "kb": round(p.stat().st_size / 1024)}
    try:
        if kind in ("notes", "scripts"):
            from longform.notes import chars, parse_note
            n = parse_note(p)
            subs = [x for s in n.sections for x in s.subs]
            info.update(subject=n.subject, subject_no=n.subject_no, h2=len(n.sections), h3=len(subs),
                        refs=sum(len(s.all_refs()) for s in n.sections),
                        say_chars=sum(chars(x.say) for x in subs),
                        read=sum(1 for x in subs if x.read), svgs=sum(len(s.svgs) for s in n.sections))
            if not n.sections:
                info["problem"] = "h2 제목이 없습니다 — 섹션을 나눌 수 없습니다"
            elif kind == "scripts" and not info["say_chars"]:
                info["problem"] = "h3 data-say 가 없습니다 — 영상 원고가 아니라 요약노트 같습니다"
        elif kind == "rounds":
            d = json.loads(p.read_text(encoding="utf-8"))
            qs = d.get("questions") or []
            info.update(round=d.get("round"), questions=len(qs))
            if not qs:
                info["problem"] = "questions 가 비어 있습니다"
        elif kind == "review":
            t = p.read_text(encoding="utf-8", errors="replace")
            info["has_videos"] = "VIDEOS_BY_TAB" in t
            if not info["has_videos"]:
                info["problem"] = "VIDEOS_BY_TAB 가 없습니다 — review.html 형식이 아닙니다"
    except Exception as e:  # 읽지 못하면 그대로 알려 준다
        info["problem"] = f"읽을 수 없습니다: {e}"
    return info


def _kind_dir(j, kind: str) -> Path:
    return j.input_dir if kind == "review" else j.input_dir / kind


@app.get("/api/inputs")
def inputs(job: str) -> Dict[str, Any]:
    j = _job(job)
    out: Dict[str, Any] = {}
    for kind in KINDS:
        if kind == "review":
            p = j.input_dir / "review.html"
            out[kind] = [_describe(kind, p)] if p.exists() else []
        else:
            d = j.input_dir / kind
            pats = ("m*.json",) if kind == "rounds" else ("*.html", "*.htm")
            files = sorted({f for pat in pats for f in d.glob(pat)}) if d.exists() else []
            out[kind] = [_describe(kind, f) for f in files]
    return out


@app.put("/api/upload")
async def upload(job: str, kind: str, name: str, request: Request) -> Dict[str, Any]:
    """파일 하나 = 요청 하나(본문이 파일 바이트). 화면이 여러 개를 차례로 보낸다."""
    j = _job(job)
    if kind not in KINDS:
        raise HTTPException(400, f"kind = {', '.join(KINDS)}")
    n = _safe_name(name)
    if not n.lower().endswith(KINDS[kind]):
        raise HTTPException(400, f"{kind} 칸에는 {' · '.join(KINDS[kind])} 만 넣을 수 있습니다: {n}")
    data = await request.body()
    if len(data) > 30_000_000:
        raise HTTPException(413, "30MB 를 넘는 파일은 넣을 수 없습니다")
    d = _kind_dir(j, kind)
    d.mkdir(parents=True, exist_ok=True)
    dst = d / ("review.html" if kind == "review" else n)
    dst.write_bytes(data)
    _sync_inputs(j)
    return _describe(kind, dst)


@app.delete("/api/inputs")
def remove_input(job: str, kind: str, name: str) -> Dict[str, Any]:
    j = _job(job)
    if kind not in KINDS:
        raise HTTPException(400, "kind")
    p = _kind_dir(j, kind) / ("review.html" if kind == "review" else _safe_name(name))
    if p.exists():
        p.unlink()
    _sync_inputs(j)
    return {"ok": True}


# ── 기획: 강 수 후보 · 결정 · 기획 메모 ──────────────────────────────────
@app.get("/api/proposals")
def get_proposals(job: str) -> Dict[str, Any]:
    j = _job(job)
    brief = j.dir / "brief.md"
    return {"proposals": read_json(j.dir / "proposals.json", None),
            "brief": brief.read_text(encoding="utf-8") if brief.exists() else "",
            "current": {"per": j.get("curriculum.lectures_per_subject") or {},
                        "target_min": j.get("curriculum.target_min")}}


@app.post("/api/propose")
def post_propose(job: str) -> Dict[str, Any]:
    from longform import propose
    return propose.propose(_job(job))


@app.post("/api/decide")
async def post_decide(request: Request) -> Dict[str, Any]:
    """정하기는 편성(plan)까지 돌므로 실행기(로그)로 보낸다 — CLI 와 같은 길."""
    b = await request.json()
    per = ",".join(str(int(x)) for x in b.get("per") or [])
    if not per:
        raise HTTPException(400, "per 가 없습니다")
    args = ["decide", "--job", (b.get("job") or ""), "--per", per]
    if b.get("target"):
        args += ["--target", str(int(b["target"]))]
    if b.get("note"):
        args += ["--note", str(b["note"])]
    RUN.start(args)
    return RUN.info()


# ── 새 IP(잡) ─────────────────────────────────────────────────────────────
@app.post("/api/jobs/new")
async def new_job(request: Request) -> Dict[str, Any]:
    """지금 잡의 목표서를 본으로 **빈 잡**을 만든다. 파일은 그다음 「원천」 탭에서 끌어다 놓는다.
    과정 전용 값(과목별 강 수·사이트 링크·태그·리뷰 탭·과정 이름)은 비운다 — 강 수는 plan 이 분량으로 정한다."""
    import re as _re
    b = await request.json()
    name = (b.get("name") or "").strip().lower()
    if not _re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", name):
        raise HTTPException(400, "잡 이름은 영문 소문자·숫자·- 로 2~41자")
    d = REPO / "jobs" / name
    if d.exists():
        raise HTTPException(409, f"이미 있습니다: jobs/{name}")

    base = json.loads((_job(b.get("base") or "").dir / "job.json").read_text(encoding="utf-8"))
    title = b.get("title") or name
    base.update({"title": title, "book": b.get("book") or title, "pd": name})
    base["source"] = {"_note": "파일은 웹앱 「원천」 탭에서 input/ 으로 넣는다", "notes_dir": "",
                      "rounds_dir": "", "scripts_dir": ""}
    base["inputs"] = {"notes": [], "scripts": [], "rounds_dir": f"jobs/{name}/input/rounds"}
    base.setdefault("curriculum", {})["lectures_per_subject"] = {}
    base["curriculum"]["target_min"] = int(b.get("target_min") or 35)
    base["backplate"]["workspace"] = f"jobs/{name}/bp"
    yt = base.setdefault("youtube", {})
    yt.update({"playlist": b.get("playlist") or title, "site_url": b.get("site_url") or "",
               "tags": [t for t in title.split() if t][:5],
               "profile": yt.get("profile") or f"profiles/{name}"})
    base["register"] = {"_note": "등록 결과는 out/register/ 에 만든다. 리뷰 페이지를 넣고 탭 키를 적으면 그 탭에 강 목록이 들어간다",
                        "review_html": "", "review_tab": b.get("review_tab") or "", "youtube_map_base": "", "pd": name}
    for k in ("notes", "scripts", "rounds"):
        (d / "input" / k).mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    got = import_folder(_job(name), b.get("import_dir") or "") if (b.get("import_dir") or "").strip() else {}
    return {"name": name, "imported": got}


def import_folder(j, folder: str) -> Dict[str, Any]:
    """폴더 안의 파일을 **복사**해 input/ 에 넣는다(한 번만 — 이후 실행은 사본만 본다).

    종류는 내용으로 가른다: h3 에 data-say 가 있으면 영상 원고, 없으면 요약노트,
    VIDEOS_BY_TAB 이 있으면 리뷰 페이지, mNN.json 은 문항. 상대경로는 레포 기준(`_context\\과정이름`).
    """
    import re as _re
    src = Path(folder.strip().strip('"'))
    if not src.is_absolute():
        src = REPO / src
    if not src.is_dir():
        raise HTTPException(400, f"가져올 폴더가 없습니다: {src}")
    n = {"notes": 0, "scripts": 0, "rounds": 0, "review": 0}
    # ★ 문항 앱의 **책 폴더**를 통째로 가리켜도 된다(구조는 docs/원천-가져오기.md):
    #   _rounds/mNN.json → 문항,  03/summary_*.html → 요약노트,  _book.json → 품목 코드(pd)
    files: List[Path] = []
    if (src / "_rounds").is_dir() or (src / "03").is_dir():
        files += sorted((src / "_rounds").glob("m*.json")) if (src / "_rounds").is_dir() else []
        files += sorted((src / "03").glob("summary_*.htm*")) if (src / "03").is_dir() else []
        bk = read_json(src / "_book.json", {}) or {}
        if bk.get("pd"):
            f = j.dir / "job.json"
            cfg = json.loads(f.read_text(encoding="utf-8"))
            cfg.setdefault("register", {})["pd"] = bk["pd"]
            if not (cfg.get("youtube") or {}).get("site_url"):
                tpl = (cfg.get("register") or {}).get("site_url_template") or ""
                if tpl:
                    cfg.setdefault("youtube", {})["site_url"] = tpl.replace("{pd}", bk["pd"])
            f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            n["pd"] = bk["pd"]
    files += [f for f in sorted(src.iterdir()) if f.is_file()]
    for f in files:
        if not f.is_file():
            continue
        low = f.name.lower()
        if low.endswith((".html", ".htm")):
            t = f.read_text(encoding="utf-8", errors="replace")
            if "VIDEOS_BY_TAB" in t:
                kind = "review"
            elif _re.search(r"<h3\b[^>]*data-say\s*=", t, _re.I):
                kind = "scripts"
            else:
                kind = "notes"
        elif _re.fullmatch(r"m\d+\.json", low):
            kind = "rounds"
        else:
            continue
        dst_dir = _kind_dir(j, kind)
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst_dir / ("review.html" if kind == "review" else f.name))
        n[kind] += 1
    _sync_inputs(j)
    return n


@app.post("/api/import")
async def api_import(request: Request) -> Dict[str, Any]:
    b = await request.json()
    j = _job(b.get("job", ""))
    return {"imported": import_folder(j, b.get("folder") or "")}


# ── 계정·로그인(이 PC 전용 — 토큰은 profiles/ 에, 깃 제외) ───────────────
@app.get("/api/accounts")
def get_accounts(job: str = "") -> Dict[str, Any]:
    from longform import accounts, team
    st = accounts.status(_job(job))
    st["me"] = team.me()
    return st


@app.post("/api/accounts/codex")
async def codex_action(request: Request) -> Dict[str, Any]:
    """칸 추가+로그인 / 기본 로그인 저장 / 쓸 칸 고르기 / 칸 지우기."""
    from longform import accounts
    b = await request.json()
    act, slot = b.get("action"), (b.get("slot") or "").strip()
    try:
        if act == "login":
            accounts.login_slot(slot)
            msg = "새 창에서 ChatGPT 로그인을 마친 뒤 「새로고침」을 누르십시오."
        elif act == "copy_default":
            accounts.copy_default_into(slot)
            msg = f"이 PC 의 기본 codex 로그인을 '{slot}' 칸으로 저장했습니다."
        elif act == "activate":
            accounts.set_active(slot)
            msg = f"이제 '{slot}' 칸으로 그림을 굽습니다."
        elif act == "remove":
            accounts.remove_slot(slot)
            msg = f"'{slot}' 칸을 지웠습니다."
        else:
            raise HTTPException(400, "action = login | copy_default | activate | remove")
    except SystemExit as e:
        raise HTTPException(400, str(e).replace("[error] ", ""))
    return {"ok": True, "message": msg}


@app.post("/api/accounts/claude")
def claude_console(job: str = "") -> Dict[str, Any]:
    """새 창에서 claude 를 띄운다 — 로그인/계정 바꾸기는 그 안에서 /login, 사용량은 /usage."""
    from longform import accounts
    from longform.s2_manuscript import find_claude
    try:
        accounts.new_console([find_claude(_job(job))])
    except SystemExit as e:
        raise HTTPException(400, str(e).replace("[error] ", ""))
    return {"ok": True, "message": "새 창의 claude 에서 /login(계정 바꾸기) 또는 /usage(사용량)를 입력하십시오."}


@app.post("/api/accounts/youtube")
def youtube_login(job: str = "") -> Dict[str, Any]:
    RUN.start(["login", "--job", job])
    return RUN.info()


@app.put("/api/me")
async def put_me(request: Request) -> Dict[str, Any]:
    from longform import team
    b = await request.json()
    team.set_me(b.get("me") or "")
    return {"me": team.me()}


@app.post("/api/claim")
async def post_claim(request: Request) -> Dict[str, Any]:
    from longform import team
    b = await request.json()
    j = _job(b.get("job", ""))
    lids = [str(x) for x in b.get("lids") or []]
    try:
        (team.release if b.get("release") else team.claim)(j, lids, force=bool(b.get("force")))
    except SystemExit as e:
        raise HTTPException(400, str(e).replace("[error] ", ""))
    return {"claims": team.all_claims(j)}


@app.post("/api/open")
def open_folder(job: str, what: str = "job") -> Dict[str, str]:
    """잡 폴더를 탐색기로 연다(이 PC 화면 전용 — 127.0.0.1 에만 열려 있다)."""
    j = _job(job)
    f = {"job": j.dir, "input": j.input_dir, "out": j.out_dir}.get(what, j.dir)
    f.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(f))  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(f)])
    return {"opened": str(f)}


SERVER_VERSION = "2026-10-02.2"


@app.get("/api/version")
def version() -> Dict[str, str]:
    return {"version": SERVER_VERSION}


# ── 실행 ──────────────────────────────────────────────────────────────────
@app.post("/api/run")
async def run(request: Request) -> Dict[str, Any]:
    b = await request.json()
    stage = b.get("stage", "")
    if stage not in STAGES:
        raise HTTPException(400, f"모르는 단계: {stage}")
    args = [stage, "--job", (b.get("job") or "")]
    if b.get("only"):
        args += ["--only", str(b["only"])]
    if b.get("sections"):
        args += ["--sections", str(int(b["sections"]))]
    if b.get("max"):
        args += ["--max", str(int(b["max"]))]
    if b.get("force"):
        args.append("--force")
    if b.get("dry_run"):
        args.append("--dry-run")
    RUN.start(args)
    return RUN.info()


@app.post("/api/stop")
def stop() -> Dict[str, Any]:
    RUN.stop()
    return RUN.info()


@app.get("/api/log")
def log(offset: int = 0) -> JSONResponse:
    if not LOG.exists():
        return JSONResponse({"text": "", "offset": 0, "run": RUN.info()})
    data = LOG.read_bytes()
    if offset > len(data):
        offset = 0
    chunk = data[offset:offset + 200_000].decode("utf-8", errors="replace")
    return JSONResponse({"text": chunk, "offset": offset + len(data[offset:offset + 200_000]),
                         "run": RUN.info()})


def main() -> None:
    import uvicorn
    import webbrowser
    port = int(os.environ.get("LECTURE_COMPOSER_PORT", "5190"))
    url = f"http://127.0.0.1:{port}"
    print(f"Lecture Composer → {url}  (끄려면 이 창을 닫으십시오)")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
