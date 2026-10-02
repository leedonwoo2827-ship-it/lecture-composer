# -*- coding: utf-8 -*-
"""개발자 프레젠트 지원 에이전트 — 로컬 콘솔 서버.

FastAPI + 무빌드 바닐라 SPA. 사내 로컬 콘솔 표준(
instructional-design-agent)과 같은 형태다.

산출물은 앱 폴더 밖 형제 폴더에 쌓인다 — core/workspace.py 참고.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote
from typing import Any, Dict, List, Optional

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import (activity, config, htmldoc, manuscript as ms, refs as refs_mod,
                  versions, workspace as ws)
from core.jobs import get_registry
from pipeline.registry import (STAGES, cache_path, cached_data,
                               narration_of, read_cache,
                               stage_states, write_cache)
import pipeline.s0_prd     # noqa: F401
import pipeline.s0a_ask    # noqa: F401
import pipeline.s1_frames  # noqa: F401  — import 시 STAGES 에 run 을 붙인다
import pipeline.s2_repo    # noqa: F401
import pipeline.s2b_outline  # noqa: F401
import pipeline.s2c_capture  # noqa: F401
import pipeline.s3_caption  # noqa: F401
import pipeline.s3a_imgprompt  # noqa: F401
import pipeline.s3b_images  # noqa: F401
import pipeline.s5_decisions # noqa: F401
import pipeline.s6_script   # noqa: F401
import pipeline.s7_copy     # noqa: F401
import pipeline.s8_assemble # noqa: F401
import pipeline.s9_render   # noqa: F401
import pipeline.s10_tts     # noqa: F401
import pipeline.s11_audio   # noqa: F401
import pipeline.s12_video   # noqa: F401
import pipeline.s3c_images_run  # noqa: F401  — 11판: 그림 굽기
import pipeline.s12h_hyper      # noqa: F401  — 11판: HyperFrames 렌더
# ★ 모션은 **스테이지가 아니다** — STAGES 에 붙지 않으므로 이름을 들고 쓴다
from pipeline import s13_motion as motion
from pipeline import s3a_imgprompt as imgprompt

APP_DIR = Path(__file__).resolve().parent
STATIC = APP_DIR / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """서버가 실제로 듣기 시작한 뒤에 브라우저를 연다.

    run.bat 에서 `start ""` 로 먼저 열면 부팅(1~3초)을 앞질러
    ERR_CONNECTION_REFUSED 페이지가 뜬다 — IDA 에서 실제로 겪은 문제.

    ★ `@app.on_event("startup")` 은 최신 FastAPI 에서 deprecated 라 조용히
      안 도는 경우가 있다(실제로 창이 안 떴다). lifespan 이 현재 방식이다.
    """
    if os.environ.get("SHOWCASE_OPEN_BROWSER") == "1":
        port = config.load()["port"]
        threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    yield


app = FastAPI(title="개발자 프레젠트 지원 에이전트", docs_url=None, redoc_url=None,
              lifespan=lifespan)


# ── 정적 ───────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC / "index.html"))


class FreshStatic(StaticFiles):
    """★ 브라우저 캐시를 끈다.

    이 앱은 무빌드다 — 파일명에 해시가 안 붙으니 브라우저가 예전 .js 를 계속
    쓴다. 고쳐 놓고 "안 고쳐졌는데요" 를 몇 번이나 겪었고, 그때마다 사람이
    Ctrl+Shift+R 을 눌러야 했다. 로컬에서 도는 앱이라 캐시로 아낄 게 없다.
    """

    def is_not_modified(self, *a, **kw) -> bool:
        return False                      # 304 도 주지 않는다

    async def get_response(self, path: str, scope):
        r = await super().get_response(path, scope)
        r.headers["cache-control"] = "no-store, must-revalidate"
        return r


app.mount("/static", FreshStatic(directory=str(STATIC)), name="static")

# ── 이미지 스튜디오 ────────────────────────────────────────────────────────
# 예전에는 별도 앱(8765 포트)이라 사람이 이미지프롬프트.json 을 들고 창을 옮겨
# 다녔다. 같은 FastAPI 라 라우터로 얹는다 — 터미널이 하나가 된다.
# ★ 라우터를 먼저 걸고 정적 마운트를 나중에 건다. 순서가 뒤집히면
#   /imgstudio 마운트가 /imgstudio/api/* 까지 삼킨다.
from imgstudio.mount import attach as _attach_imgstudio  # noqa: E402

_attach_imgstudio(app)


# ── 건강 확인 ──────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> Dict[str, Any]:
    from llm.claude_provider import find_cli

    exe = find_cli()
    return {
        "ok": True,
        "app_dir": str(APP_DIR),
        "workspace": ws.describe(),
        "claude_cli": str(exe) if exe else None,
        "vision_mode": config.load()["vision_mode"],
        "python": sys.version.split()[0],
    }


# ── 설정 ───────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    cfg = dict(config.load())
    cfg["workspace"] = ws.describe()
    return cfg


@app.post("/api/settings")
def post_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(config.save(patch))
    cfg["workspace"] = ws.describe()
    return cfg


# ── 프로젝트 ───────────────────────────────────────────────────────────────
class ProjectIn(BaseModel):
    """만들 때 받는 **좌표**. 제목 말고는 전부 선택이다.

    ★ 제목을 안 적어도 된다 — 레포 이름이나 영상 폴더 이름에서 따온다. 시작할 때
      제목부터 고민하게 만들면 시작이 안 된다. 나중에 S0 기획서가 더 나은 제목을
      제안하고, 덱 제목은 S2b 가 따로 짓는다.

    ★ 사이트는 **여러 개**다. 서비스 본체와 중계기처럼 주소가 갈리는 경우가 있다.
    ★ `refs` 는 레포에도 영상에도 없는 재료 — 구조 설명 HTML, 기획 메모 같은 것.
    """
    title: str | None = None
    slug: str | None = None
    video_dir: str | None = None
    live_url: str | None = None            # 남겨 둔다(예전 화면 호환)
    urls: List[Dict[str, str]] | None = None   # [{"url":…, "label":…}]
    repo: str | None = None                # "owner/name" (예전 화면 호환)
    # ★ 레포와 라이브 URL은 **쌍**이다 — 레포마다 사이트가 있을 수도, 없을 수도 있다
    #   (로컬 앱·플러그인처럼). 한 발표가 레포 하나로 끝나지 않는 경우가 많다.
    sources: List[Dict[str, str]] | None = None   # [{"repo":…, "url":…}]
    refs: List[str] | None = None          # 참고 문서 경로(파일 또는 폴더) — 서버 로컬 경로
    ref_uploads: List[Dict[str, str]] | None = None  # [{"name":…, "data_url":…}] — 드래그앤드롭. 브라우저는 경로를 안 준다


@app.get("/api/projects")
def list_projects() -> List[Dict[str, Any]]:
    return ws.list_projects()


def _find(pid: int) -> Dict[str, Any]:
    for p in ws.list_projects():
        if p["id"] == int(pid):
            doc = ws.load_project(pid, p["slug"])
            if doc:
                return doc
    raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")


@app.get("/api/projects/{pid}")
def get_project(pid: int) -> Dict[str, Any]:
    return _find(pid)


@app.post("/api/projects")
def create_project(body: ProjectIn) -> Dict[str, Any]:
    # ★ 영상은 **없어도 된다.** 레포만으로도 발표는 나온다. 나중에 더 찍어서
    #   폴더에 넣고 프레임 단계를 다시 돌리면 그때 항목이 는다.
    files: List[Path] = []
    vdir = None
    if (body.video_dir or "").strip():
        vdir = Path(body.video_dir.strip().strip('"')).expanduser()
        if not vdir.is_dir():
            raise HTTPException(status_code=400, detail=f"영상 폴더가 없습니다: {vdir}")
        exts = {".mkv", ".mp4", ".mov", ".webm", ".avi"}
        files = sorted([f for f in vdir.iterdir()
                        if f.is_file() and f.suffix.lower() in exts],
                       key=lambda f: ws.nfc(f.name))

    # 좌표 쌍 — 새 화면은 sources 를, 예전 화면은 repo/live_url 을 준다
    sources = [{"repo": (s.get("repo") or "").strip(),
                "url": (s.get("url") or "").strip()}
               for s in (body.sources or []) if (s.get("repo") or "").strip()]
    if not sources and body.repo:
        sources = [{"repo": body.repo.strip(), "url": (body.live_url or "").strip()}]

    urls = [u for u in (body.urls or []) if (u or {}).get("url")]
    if not urls:
        urls = [{"url": s["url"], "label": s["repo"].split("/")[-1]}
                for s in sources if s["url"]]
    if body.live_url and not urls:
        urls = [{"url": body.live_url, "label": "라이브"}]
    if not files and not sources and not urls and not body.refs and not body.ref_uploads:
        raise HTTPException(status_code=400,
                            detail="레포 · 영상 폴더 · 사이트 · 참고 자료 중 하나는 있어야 합니다")

    # ★ 제목이 없으면 만들어 준다 — 시작할 때 제목부터 고민하게 하지 않는다
    title = (body.title or "").strip()
    if not title:
        if sources:
            title = sources[0]["repo"].rstrip("/").split("/")[-1].removesuffix(".git")
        elif vdir:
            title = ws.nfc(vdir.name).lstrip("_")
        elif urls:
            title = re.sub(r"^https?://(www\.)?", "", urls[0]["url"]).split("/")[0]
        elif body.ref_uploads:
            title = ws.nfc(Path(body.ref_uploads[0].get("name") or "").stem) or "새 발표"
        elif body.refs:
            title = ws.nfc(Path(str(body.refs[0])).stem) or "새 발표"
        else:
            title = "새 발표"

    items = [{
        "id": f"v{i}",
        "file": ws.nfc(f.name),
        "title": ws.nfc(f.stem),
        "route_hint": None,
        "api_hint": [],
        "frame_count": config.load()["frames"]["max_frames"],
        "include": True,
        "media_mode": None,
    } for i, f in enumerate(files, 1)]

    pid = ws.next_pid()
    slug = ws.ascii_slug(body.slug or title)
    doc = {
        "schema_version": 1,
        "slug": slug,
        "title": title,
        "live_url": urls[0]["url"] if urls else None,
        "urls": urls,
        "language": "ko",
        "media_mode": "still",
        "video_dir": str(vdir) if vdir else None,
        "items": items,
        "sources": sources,
        "repo": ({"name_with_owner": sources[0]["repo"], "ref": "main",
                  "include": [], "exclude": [], "redact": []} if sources else None),
        "narration": dict(config.load()["narration"], enabled=True),
        "models": dict(config.load()["models"]),
    }
    ws.save_project(pid, slug, doc)
    # 참고 자료는 **복사해 둔다** — 원본이 옮겨져도 발표가 안 깨져야 한다
    # ★ 문이 둘이다 — 서버 로컬 경로(refs) 와 드래그앤드롭 업로드(ref_uploads).
    #   둘 다 오면 번호를 이어 붙여 한 목록으로 합친다.
    if body.refs or body.ref_uploads:
        items: List[Dict[str, Any]] = []
        refs_dir = None
        if body.refs:
            got = refs_mod.collect(pid, slug, body.refs)
            refs_dir, items = got["dir"], got["items"]
        if body.ref_uploads:
            got2 = refs_mod.collect_uploaded(pid, slug, body.ref_uploads,
                                             start=len(items) + 1)
            refs_dir = refs_dir or got2["dir"]
            items += got2["items"]
        doc["refs"] = {"dir": refs_dir, "items": items}
        ws.save_project(pid, slug, doc)
    return ws.load_project(pid, slug)


class RecopyIn(BaseModel):
    """한 장만 문구를 다시 뽑는다.

    ★ 전체(37장)를 다시 돌리면 $0.73 이고 이미 확정한 장까지 갈아엎는다.
      한 장이 마음에 안 들 때 그 한 장만 다시 뽑는 자리가 있어야, 사람이
      "이건 좀 아닌데" 를 눌러서 해결할 수 있다.

    `hint` 는 사람이 주는 지시다 — "더 짧게", "숫자를 앞에", "기업 회원 화면 얘기로".
    """
    tone: str | None = None
    hint: str = ""
    only: str | None = None      # "title" | "body" | None(둘 다)


@app.post("/api/projects/{pid}/recopy/{no}")
def recopy_slide(pid: int, no: int, body: RecopyIn) -> Dict[str, Any]:
    from pipeline.s7_copy import DEFAULT_TONE, SCHEMA, TONES, build_brief, clean
    from llm.claude_provider import ClaudeProvider

    doc = _find(pid)
    slug = doc["slug"]
    deck = cached_data(pid, slug, "s2b-outline") or {}
    sl = next((x for x in (deck.get("slides") or []) if x["no"] == no), None)
    if not sl:
        raise HTTPException(status_code=404, detail=f"{no}번 장이 없습니다")
    dec = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {})

    tone = body.tone or doc.get("slide_tone") or DEFAULT_TONE
    if tone not in TONES:
        tone = DEFAULT_TONE

    cfg = config.load()
    system = (APP_DIR / "llm" / "prompts" / "copy.md").read_text(encoding="utf-8")
    brief = build_brief([sl], deck, dec, tone)
    if body.hint.strip():
        brief += ("\n\n# 사람이 준 지시 — **이걸 최우선으로 따른다**\n"
                  + body.hint.strip())

    p = ClaudeProvider(
        model=(doc.get("models") or cfg["models"]).get("script") or cfg["models"]["script"],
        effort=cfg["effort"].get("script", "high"),
        allowed_tools=[], max_turns=1, budget_usd=cfg["budget_usd"]["per_stage"],
    )
    try:
        raw = p.structured(system, [{"role": "user", "content": brief}], schema=SCHEMA)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {str(e)[:160]}")

    r = next((x for x in (raw.get("slides") or []) if int(x.get("no") or 0) == no), None)
    if not r or not clean(r.get("title")):
        raise HTTPException(status_code=502, detail="문구가 비어 돌아왔습니다")

    title, note = clean(r.get("title")), clean(r.get("body"))
    prev = (ws.load_overrides(pid, slug).get("slides", {}).get(str(no)) or {})
    if body.only == "title":
        note = prev.get("note", note)
    elif body.only == "body":
        title = prev.get("title", title)
    ov = ws.load_overrides(pid, slug)
    cur = ov.setdefault("slides", {}).setdefault(str(no), {})
    cur["title"], cur["note"] = title, note
    ws.save_overrides(pid, slug, ov)
    return {"ok": True, "no": no, "title": title, "note": note,
            "tone": tone, "cost_usd": round(p.last_cost_usd, 4)}


@app.get("/api/projects/{pid}/youtube")
def get_youtube(pid: int) -> Dict[str, Any]:
    """유튜브에 올릴 제목·설명·타임스탬프·태그.

    ★ 파일이 있으면 그것을 읽고, 없으면 **덱에서 지금 만들어 준다.** 영상을 이미
      구워 둔 프로젝트(파일이 없던 시절에 구운 것)에서도 화면이 비지 않아야 한다.

    ★ **덱보다 오래된 파일은 안 읽는다.** 제목을 고치거나 대본을 손보면 덱이 다시
      조립되는데, 그때 만들어 둔 `유튜브.txt` 는 옛 제목을 이고 있다(2026-08-15:
      제목을 바꿨는데 유튜브 글에는 `19_원고` 가 그대로 남았다).
    """
    from render import youtube

    doc = _find(pid)
    slug = doc["slug"]
    p = ws.project_dir(pid, slug, create=False) / ws.STEPS["dist"][0] / "유튜브.txt"
    # ★ s8 캐시에는 덱이 아니라 **파일 경로**만 들어 있다 — 덱 본체는 `deck.json` 이다
    dp = ws.deck_path(pid, slug)
    if p.is_file() and dp.is_file() and p.stat().st_mtime >= dp.stat().st_mtime:
        return {"ok": True, "text": p.read_text(encoding="utf-8"), "file": str(p)}
    deck = ws.read_json(dp, {}) or {}
    if not deck.get("slides"):
        raise HTTPException(status_code=404, detail="덱을 먼저 조립하세요")
    txt = youtube.build(deck, title=(doc.get("title") or slug),
                        led=(ws.load_ledger(pid, slug).get("by_id") or {}),
                        book=str(doc.get("book") or ""))
    return {"ok": True, "text": txt, "file": ""}


@app.get("/api/projects/{pid}/youtube/thumbs")
def youtube_thumbs(pid: int) -> Dict[str, Any]:
    """썸네일 후보 — 스튜디오가 낸 두 벌(후킹형·차분형)을 고르게 한다.

    ★ 지시문을 두 벌 내므로(`render/thumbnail.py`) 그림도 두 장 온다. 어느 쪽이
      나은지는 장마다 달라 기계가 고를 일이 아니다 — 나란히 놓고 사람이 고른다.
    """
    doc = _find(pid)
    slug = doc["slug"]
    img = ws.step_dir(pid, slug, "images", create=False)
    dist = ws.step_dir(pid, slug, "dist", create=False)
    picked = (dist / "썸네일.png")

    out: List[Dict[str, Any]] = []
    if img.is_dir():
        for f in sorted(img.glob("썸네일*.png")):
            out.append({
                "name": f.name,
                # 「썸네일-후킹형.png」 → 「후킹형」
                "kind": re.sub(r"^썸네일[-_]?|\.png$", "", f.name) or f.stem,
                "mb": round(f.stat().st_size / 1e6, 1),
                "url": f"/api/projects/{pid}/file/{ws.STEPS['images'][0]}/{f.name}",
            })
    return {"thumbs": out, "picked": picked.name if picked.is_file() else "",
            "picked_url": (f"/api/projects/{pid}/file/{ws.STEPS['dist'][0]}/썸네일.png"
                           if picked.is_file() else "")}


@app.post("/api/projects/{pid}/youtube/thumb/pick")
def youtube_thumb_pick(pid: int, name: str) -> Dict[str, Any]:
    """고른 한 장을 완성본 폴더에 `썸네일.png` 로 앉힌다.

    ★ 옮기지 않고 **복사한다.** 후보는 그대로 두어야 나중에 다른 쪽으로 바꿀 수 있다.
    """
    import shutil as _sh

    doc = _find(pid)
    slug = doc["slug"]
    src = ws.safe_child(ws.step_dir(pid, slug, "images", create=False), name)
    if src is None or not src.is_file():
        raise HTTPException(status_code=404, detail=f"없는 파일입니다: {name}")
    dst = ws.step_dir(pid, slug, "dist") / "썸네일.png"
    _sh.copy2(src, dst)
    return {"ok": True, "picked": name, "file": str(dst),
            "url": f"/api/projects/{pid}/file/{ws.STEPS['dist'][0]}/썸네일.png"}


class PronDictIn(BaseModel):
    """사전 통째로 받는다 — 화면이 표를 들고 있고 저장은 한 번에 한다."""
    rules: Dict[str, str]


@app.get("/api/pron-dict")
def pron_dict_get(pid: int | None = None) -> Dict[str, Any]:
    """발음 사전 + **이 덱에서 아직 사전에 없는 영문**.

    ★ 사전만 보여 주면 무엇을 채워야 하는지 모른다. SQL 덱처럼 용어가 쏟아지는
      과목에서는 그것이 일의 전부다 — 그래서 덱을 훑어 **빠진 것만 빈도순으로**
      같이 낸다. 채울 자리가 화면에 보여야 채운다.
    """
    from core import roman

    path = roman.dict_path()
    rules = dict(roman.rules())
    missing: List[Dict[str, Any]] = []
    if pid is not None:
        import collections

        doc = _find(pid)
        now = narration_of(pid, doc["slug"]) or {}
        cnt: "collections.Counter[str]" = collections.Counter()
        for cur in now.values():
            for field in ("text", "srt_text"):
                cnt.update(roman.find_roman(cur.get(field) or ""))
        for word, n in cnt.most_common():
            if word not in rules:
                missing.append({"word": word, "n": n, "guess": roman.spell(word)})
    return {"path": str(path or ""), "count": len(rules), "rules": rules,
            "missing": missing[:200]}


@app.post("/api/pron-dict")
def pron_dict_post(body: PronDictIn) -> Dict[str, Any]:
    """사전을 통째로 다시 쓴다 — voicewright 의 `/dict` 화면과 **같은 형식**으로.

    ★ 머리말 주석은 그대로 두고 `rules:` 블록만 갈아 끼운다. 키 정렬도 그쪽과
      같게 한다 — 두 화면이 같은 파일을 번갈아 쓰는데 형식이 갈리면 매번 통째로
      바뀐 것처럼 보인다.
    ★ 저장 전에 **백업 한 벌**을 남긴다. 사람이 쌓아 온 표이고, 실수로 비우면
      되돌릴 길이 없다.
    """
    from core import roman

    path = roman.dict_path()
    if path is None:
        raise HTTPException(status_code=404, detail="사전 파일을 찾지 못했습니다")

    rules = {k.strip(): v.strip() for k, v in (body.rules or {}).items()
             if k.strip() and v.strip()}
    if not rules:
        raise HTTPException(status_code=400, detail="사전이 비었습니다 — 저장하지 않습니다")

    raw = path.read_text(encoding="utf-8")
    head = raw.split("rules:", 1)[0].rstrip("\n") + "\n\n" if "rules:" in raw else ""
    path.with_suffix(".yaml.bak").write_text(raw, encoding="utf-8")

    def q(s: str) -> str:
        return f'"{s}"' if (":" in s or s != s.strip()
                            or s.startswith(("'", '"', "*", "&", "#"))) else s

    body_txt = "".join(f"  {q(k)}: {q(rules[k])}\n" for k in sorted(rules))
    ws.write_text(path, head + "rules:\n" + body_txt)
    roman.forget()
    return {"ok": True, "count": len(rules), "file": str(path)}


@app.post("/api/projects/{pid}/speak-roman-all")
def speak_roman_all(pid: int, apply: bool = False) -> Dict[str, Any]:
    """**덱 전체**의 발음 칸에서 영문만 한국어 소리로 바꾼다.

    ★ `pronounce-all`(발음 대본 생성)과 갈라 둔 이유가 이 함수의 전부다. 그쪽은
      **자막에서 다시 만들어서** 손으로 고쳐 둔 발음을 지운다. 여기는 **지금 발음
      칸에 있는 글에** 영문 변환만 얹는다 — 「새느 수」처럼 귀로 골라 고쳐 둔 것이
      살아남는다. 이미 손댄 덱에서 영문만 고치려면 그것 말고는 장마다 버튼을
      누르는 수밖에 없고, 112장이면 말이 안 된다.

    ★ 오버라이드에 쓴다(대본 캐시가 아니다). 스테이지를 다시 돌려도 남는다.

    ★ Claude 를 부르지 않는다. 결정론이라 공짜이고, 몇 번 눌러도 같은 결과다
      (이미 바뀐 장에는 영문이 없어 그대로다).
    """
    from core.roman import speak_roman

    doc = _find(pid)
    slug = doc["slug"]
    now = narration_of(pid, slug)
    if not now:
        raise HTTPException(status_code=400, detail="대본을 먼저 만드세요")

    cps = float((doc.get("narration") or config.load()["narration"])
                .get("chars_per_sec", 5.7))
    plan: Dict[str, str] = {}
    for key, cur in now.items():
        said = (cur.get("text") or cur.get("srt_text") or "").strip()
        if not said:
            continue
        new = speak_roman(said)
        if new != said:
            plan[key] = new

    if not apply:
        return {"ok": True, "n": len(now), "changed": len(plan),
                "sample": [{"no": int(k), "text": v[:70]}
                           for k, v in list(plan.items())[:3]]}

    ov = ws.load_overrides(pid, slug)
    slides = ov.setdefault("slides", {})
    for key, new in plan.items():
        nar = slides.setdefault(key, {}).setdefault("narration", {})
        nar["text"] = new
    ws.save_overrides(pid, slug, ov)

    # ★ 음성·자막을 낡게 만든다 — 안 올리면 "할 일 없음" 이라 옛 음성이 남는다
    doc["narration_rev"] = int(doc.get("narration_rev") or 0) + 1
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, slug, doc)
    return {"ok": True, "n": len(now), "changed": len(plan),
            "narration_rev": doc["narration_rev"]}


@app.post("/api/projects/{pid}/pronounce-report")
def pronounce_report(pid: int) -> Dict[str, Any]:
    """**손으로 정한 읽는 법**을 표로 내고 그 폴더를 연다.

    ★ 왜 이 버튼이 필요한가. 발음은 두 곳에서 정해진다 — 규칙은 코드에 있고
      (`core/honorific.py`), 예외는 **이 프로젝트 폴더에만** 있다(`Q1 → 큐원`,
      `m1 → 엠원`). 다음 과목을 쓰는 사람은 후자를 모르니 같은 자리에서 같은
      고민을 다시 하고, 나는 같은 발음을 또 손으로 고친다. 그것을 끊는 파일이다.

    ★ 장별듣기 **뒤**, 영상 렌더링 **앞**에 놓는 이유: 손편집이 다 끝난 시점이
      여기다. 더 앞에서 뽑으면 아직 안 고친 장이 빠지고, 더 뒤에서 뽑으면 이미
      영상을 굽고 나서라 다음 과목에 못 쓴다.

    ★ Claude 를 부르지 않는다. 결정론이라 공짜다 — 몇 번 눌러도 손해가 없다.
    """
    from render import pronounce

    doc = _find(pid)
    slug = doc["slug"]
    if not narration_of(pid, slug):
        raise HTTPException(status_code=400, detail="대본을 먼저 만드세요")

    txt = pronounce.build(pid, slug, title=(doc.get("title") or slug))
    d = ws.step_dir(pid, slug, "subtitle")
    p = ws.write_text(d / "발음교정표.txt", txt)
    return {"ok": True, "file": str(p), "dir": str(d),
            "hand": pronounce.n_hand(txt)}


@app.post("/api/projects/{pid}/youtube/thumb")
def make_thumb(pid: int) -> Dict[str, Any]:
    """썸네일용 **원고 한 장**(.md)을 완성 폴더에 내고 그 폴더를 연다.

    ★ 이미지 스튜디오의 «프롬프트 생성기» 는 JSON 이 아니라 **원고 파일**을 받는다
      (PDF·TXT·MD·DOCX·HWPX·PPTX). 그래서 아홉 칸 JSON 이 아니라 모델이 읽을 글을
      낸다 — 거기에 끌어다 놓고 「용도=배너·썸네일 · 컷 수=1컷」 만 고르면 된다.
    """
    from render import youtube

    doc = _find(pid)
    slug = doc["slug"]
    deck = ws.read_json(ws.deck_path(pid, slug), {}) or {}
    if not deck.get("slides"):
        raise HTTPException(status_code=404, detail="덱을 먼저 조립하세요")
    d = ws.step_dir(pid, slug, "dist")
    p = ws.write_text(d / "유튜브썸네일-원고.txt",
                      youtube.thumb_md(deck, title=(doc.get("title") or slug),
                                       led=(ws.load_ledger(pid, slug).get("by_id") or {}),
                                       book=str(doc.get("book") or "")))
    return {"ok": True, "file": str(p), "dir": str(d)}


class RescriptIn(BaseModel):
    """한 장만 **대본**을 다시 쓴다. 자막과 발음 두 줄이 같이 나온다."""
    hint: str = ""


@app.post("/api/projects/{pid}/rescript/{no}")
def rescript_slide(pid: int, no: int, body: RescriptIn) -> Dict[str, Any]:
    """그 장의 자막·발음 대본을 다시 쓴다.

    ★ 제목·본문에는 「한 장만 다시」가 있는데 대본에는 없었다. 대본 전체를 다시
      돌리면 31장을 통째로 갈아엎고 이미 손본 장까지 날아간다 — 한 장이 마음에
      안 들 때 그 한 장만 고치는 자리가 있어야 한다(2026-08-14).

    ★ **원고가 준 대본이 있으면 늘 그것이다.** 작가 에이전트가 `data-say` 에 적어
      보낸 것이 있으면 Claude 를 안 부른다 — 돈을 쓰고도 더 나빠지기 때문이다.
      2026-08-14 실측: 거시경제학 장에 대고 「이 서비스의 화면은 두 갈래로
      나뉩니다… 내 경력 하나를 들여다보는」 이 나왔다($0.22). 이 앱의 대본
      프롬프트(`script.md`)는 **개발자 포트폴리오 발표**용이라 책 강의에 안 맞는다.
      AI 로 다시 쓰려면 **사람이 지시를 적어야** 한다 — 그때만 부른다.
    """
    from pipeline.s6_script import SCHEMA, build_brief, budgets, clean, est_sec
    from llm.claude_provider import ClaudeProvider

    doc = _find(pid)
    slug = doc["slug"]
    deck = cached_data(pid, slug, "s2b-outline") or {}
    slides = deck.get("slides") or []
    sl = next((x for x in slides if x["no"] == no), None)
    if not sl:
        raise HTTPException(status_code=404, detail=f"{no}번 장이 없습니다")

    cfg = config.load()
    cache = cached_data(pid, slug, "s6-script") or {}
    cur = dict((cache.get("slides") or {}).get(str(no)) or {})
    cps = float((doc.get("narration") or cfg["narration"]).get("chars_per_sec", 5.7))

    # 원고가 대본을 들고 왔으면 — 지시가 없는 한 늘 그것이다(공짜)
    say = clean(sl.get("say"))
    if say and not body.hint.strip():
        rec = {"srt_text": say, "narration_text": say,
               "narration_seconds": est_sec(say, cps), "from": "원고"}
        _save_script(pid, slug, no, cache, rec)
        return {"ok": True, "no": no, "cost_usd": 0.0, "source": "원고", **rec}

    dec = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {})
    frames = (cached_data(pid, slug, "s1-frames") or {}).get("items", {})
    ovr = ws.load_overrides(pid, slug)
    budget = budgets(slides, frames, ovr.get("slides", {}),
                     float(ovr.get("target_min") or 0) * 60)

    system = (APP_DIR / "llm" / "prompts" / "script.md").read_text(encoding="utf-8")
    brief = build_brief([sl], deck, dec, budget, "")
    if body.hint.strip():
        brief += ("\n\n# 사람이 준 지시 — **이걸 최우선으로 따른다**\n"
                  + body.hint.strip())

    p = ClaudeProvider(
        model=(doc.get("models") or cfg["models"]).get("script") or cfg["models"]["script"],
        effort=cfg["effort"].get("script", "high"),
        allowed_tools=[], max_turns=1, budget_usd=cfg["budget_usd"]["per_stage"],
    )
    try:
        raw = p.structured(system, [{"role": "user", "content": brief}], schema=SCHEMA)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {str(e)[:160]}")

    r = next((x for x in (raw.get("slides") or []) if int(x.get("no") or 0) == no), None)
    srt = clean((r or {}).get("srt_text"))
    if not srt:
        raise HTTPException(status_code=502, detail="자막이 비어 돌아왔습니다")
    nar = clean((r or {}).get("narration_text")) or srt
    rec = {"srt_text": srt, "narration_text": nar,
           "narration_seconds": est_sec(nar, cps), "budget_sec": budget.get(no, 0)}
    _save_script(pid, slug, no, cache, rec)
    return {"ok": True, "no": no, "cost_usd": round(p.last_cost_usd, 4),
            "source": "AI", **rec}


def _save_script(pid: int, slug: str, no: int, cache: Dict[str, Any],
                 rec: Dict[str, Any]) -> None:
    """대본 캐시에 한 칸만 덮어쓴다. 나머지 장은 건드리지 않는다.

    ★ `narration_rev` 를 올린다 — 음성·자막이 이 값을 보고 낡음을 판정한다.
      안 올리면 대본을 고쳐도 "할 일 없음" 이라 옛 음성이 그대로 남는다.
    """
    stage = STAGES["s6-script"]
    doc = ws.load_project(pid, slug)
    slides = dict(cache.get("slides") or {})
    slides[str(no)] = rec
    write_cache(pid, slug, "s6-script",
                input_hash=stage.input_hash(pid, slug, doc),
                data={**cache, "slides": slides},
                code_version=stage.code_version, model=cache.get("model", ""),
                cost_usd=0.0, status="ok", warnings=[])
    doc["narration_rev"] = int(doc.get("narration_rev") or 0) + 1
    ws.save_project(pid, slug, doc)


@app.get("/api/projects/{pid}/verify/{no}")
def verify_slide(pid: int, no: int) -> Dict[str, Any]:
    """근거 검증 — **이 장이 인용한 경로가 레포에 진짜 있나.**

    공짜다(파일 존재 확인일 뿐). 지어낸 경로가 발표 자료에 실리는 것이 가장 나쁘고,
    문구를 손으로 고치다 보면 경로만 남고 내용이 어긋나는 일이 생긴다.
    """
    doc = _find(pid)
    slug = doc["slug"]
    repo = cached_data(pid, slug, "s2-repo") or {}
    clone = Path(repo["clone_dir"]) if repo.get("clone_dir") else None
    shas = {c["sha"] for c in (repo.get("commits") or [])}

    dec = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {}).get(str(no)) or {}
    outline = cached_data(pid, slug, "s2b-outline") or {}
    sl = next((x for x in (outline.get("slides") or []) if x["no"] == no), {})

    refs: List[str] = [str(e.get("ref")) for e in (dec.get("evidence") or []) if e.get("ref")]
    if not refs and sl.get("evidence_hint"):
        raw = str(sl["evidence_hint"]).replace(",", "\n")
        refs = [x.strip() for x in raw.split("\n") if x.strip()]

    out = []
    for ref in refs[:8]:
        head = ref.split(":")[0].strip()
        if re.fullmatch(r"[0-9a-f]{7,40}", head):
            ok = any(x.startswith(head) for x in shas)
            out.append({"ref": ref, "kind": "commit", "ok": ok})
        else:
            ok = bool(clone and (clone / head).exists())
            out.append({"ref": ref, "kind": "file", "ok": ok})
    bad = [x for x in out if not x["ok"]]
    return {"no": no, "checked": len(out), "bad": len(bad), "items": out,
            "repo": bool(clone)}


@app.get("/api/projects/{pid}/imgprompt/{no}")
def img_prompt(pid: int, no: int) -> Dict[str, Any]:
    """그 장에 넣을 **그림 프롬프트**.

    이미지 스튜디오에 그대로 붙여 넣는다. 프롬프트를 여기서 보여 주는 이유:
    파일(`09_이미지/이미지프롬프트.json`)만 내보내면 사람이 그 파일을 열어 해당
    번호를 찾아야 한다. 그림을 넣는 자리에서 바로 복사되는 게 맞다 — 요청과
    납품이 한 화면에 있어야 한다.

    ★ 지시문은 **여기서 만들지 않는다.** 원장(`09_이미지/원장.json`)에서 꺼내
      온다. 화면이 보여 주는 것과 파일로 나가는 것이 갈리면 안 되기 때문이다.
      아직 없으면 「그림 지시문(S3a)을 돌리세요」라고 답한다.
    """
    from pipeline.s3a_imgprompt import slide_id

    doc = _find(pid)
    slug = doc["slug"]
    outline = cached_data(pid, slug, "s2b-outline") or {}
    sl = next((x for x in (outline.get("slides") or []) if x["no"] == no), None)
    if not sl:
        raise HTTPException(status_code=404, detail=f"{no}번 장이 없습니다")
    did = slide_id(slug, sl)
    e = (ws.load_ledger(pid, slug).get("by_id") or {}).get(did) or {}
    return {"no": no, "title": sl.get("title") or e.get("title") or "",
            "data_id": did, "prompt": (e.get("prompt") or "").strip(),
            "style": (config.load().get("image") or {}).get("negative", ""),
            "file": f"{no:03d}.png"}


class SlideImageIn(BaseModel):
    """슬라이드에 붙일 그림 한 장.

    ★ multipart 대신 **base64 JSON** 을 받는다. `python-multipart` 를 새로
      깔지 않으려는 것이다 — 의존성 하나가 동료 PC 에서 setup 을 깨뜨리는 일이
      실제로 잦고, 그림 한 장은 base64 로도 충분히 작다.
    """
    data_url: str
    name: str = ""


IMG_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
            "image/gif": ".gif"}

SHOTS_DIR = "01b_캡처"          # tools/shots.mjs 가 떨어뜨리는 곳
SHOTS_INDEX = "shots.json"


@app.post("/api/projects/{pid}/slide-image/{no}")
def put_slide_image(pid: int, no: int, body: SlideImageIn,
                    i: int = 1) -> Dict[str, Any]:
    """그 장의 그림을 **여기서 바로 바꾼다.**

    파일명은 슬라이드 번호로 고정한다(`005.png`). 규칙이 하나여야 이미지 앱이 낸
    것과 사람이 찍은 것이 같은 자리에 앉는다.
    """
    import base64 as _b64

    doc = _find(pid)
    m = re.match(r"^data:([^;]+);base64,(.+)$", body.data_url or "", re.S)
    if not m:
        raise HTTPException(status_code=400, detail="이미지 형식을 알 수 없습니다")
    mime, b64 = m.group(1).lower(), m.group(2)
    ext = IMG_MIME.get(mime)
    if not ext:
        raise HTTPException(status_code=400,
                            detail=f"지원하지 않는 형식입니다: {mime}")
    try:
        raw = _b64.b64decode(b64)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="이미지를 읽지 못했습니다")
    if len(raw) > 12_000_000:
        raise HTTPException(status_code=400, detail="12MB 를 넘습니다")

    return _attach_slide_image(pid, doc, no, i, raw, ext)


def _attach_slide_image(pid: int, doc: Dict[str, Any], no: int, i: int,
                        raw: bytes, ext: str) -> Dict[str, Any]:
    """바이트를 그 장의 자리에 앉힌다 — 드롭존과 캡처 고르기가 같이 쓴다.

    ★ 들어오는 길이 둘이어도 **앉는 자리는 하나**여야 한다. 캡처를 고른 그림이
      `00_기획/참고/` 가 아닌 딴 곳에 있으면, 덱을 굽거나 폴더째 옮길 때
      한쪽만 따라오지 않는다.
    """
    d = ws.sub_dir(pid, doc["slug"], "prd", "참고")
    # ★ 한 장에 여러 그림. 두 번째부터는 `-2`, `-3` 이 붙는다.
    #   멘토링처럼 신청 화면과 수락 화면이 따로 있는 메뉴는 한 컷으로 안 된다.
    stem = f"{no:03d}" if i <= 1 else f"{no:03d}-{int(i)}"
    # 같은 자리의 옛 파일은 치운다 — 확장자가 달라 둘 다 남으면 뭐가 붙는지 모른다
    for old in d.glob(f"{stem}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    p = d / f"{stem}{ext}"
    p.write_bytes(raw)
    rel = f"{ws.STEPS['prd'][0]}/참고/{p.name}"

    # 덱이 바로 쓰게 오버라이드에 박는다(스테이지를 안 돌려도 보인다)
    ov = ws.load_overrides(pid, doc["slug"])
    cur = ov.setdefault("slides", {}).setdefault(str(no), {})
    shots = list(cur.get("images") or ([cur["image"]] if cur.get("image") else []))
    idx = max(1, int(i)) - 1
    while len(shots) <= idx:
        shots.append("")
    shots[idx] = rel
    shots = [x for x in shots if x]
    cur["images"] = shots
    cur["image"] = shots[0]
    ws.save_overrides(pid, doc["slug"], ov)
    return {"ok": True, "file": rel, "bytes": len(raw), "name": p.name,
            "index": int(i), "images": shots}


@app.get("/api/projects/{pid}/shots")
def get_shots(pid: int) -> Dict[str, Any]:
    """화면 캡처 목록 — `01b_캡처/shots.json`.

    ★ 폴더를 훑지 않고 **매니페스트만** 읽는다. 폴더에는 옛 이름이 남아 있을 수
      있고, 무엇보다 순서·그룹·"어느 역할 메뉴였는지" 는 파일명에 없다.
    """
    doc = _find(pid)
    root = ws.project_dir(pid, doc["slug"], create=False)
    idx = root / SHOTS_DIR / SHOTS_INDEX
    if not idx.is_file():
        return {"ok": False, "dir": SHOTS_DIR, "shots": [],
                "hint": f"node tools/shots.mjs <config.json> — 결과를 {SHOTS_DIR}/ 에"}
    doc_json = ws.read_json(idx, {}) or {}
    out = []
    for s in doc_json.get("shots", []):
        if s.get("status") != "ok":
            continue
        rel = f"{SHOTS_DIR}/{s.get('file','')}"
        if not (root / rel).is_file():
            continue
        out.append({
            "file": rel, "label": s.get("label") or "", "slug": s.get("slug") or "",
            "role": s.get("role") or "", "role_label": s.get("role_label") or "",
            "group": s.get("group") or "", "no": s.get("no") or 0,
            "path": s.get("path") or "", "common": bool(s.get("common")),
            "roles": s.get("roles") or [],
        })
    return {"ok": True, "dir": SHOTS_DIR, "base": doc_json.get("base") or "",
            "shots": out}


class ShotPickIn(BaseModel):
    file: str          # `01b_캡처/personal/personal-03-career.png`


@app.post("/api/projects/{pid}/slide-image/{no}/from-shot")
def pick_slide_image(pid: int, no: int, body: ShotPickIn,
                     i: int = 1) -> Dict[str, Any]:
    """캡처 한 장을 그 장의 자리에 복사한다.

    ★ 원본을 **참조하지 않고 복사한다.** 캡처는 사이트가 바뀌면 다시 찍혀
      덮어써지는 물건이라, 참조로 두면 확정한 발표의 그림이 나중에 조용히 바뀐다.
    """
    doc = _find(pid)
    root = ws.project_dir(pid, doc["slug"], create=False).resolve()
    rel = (body.file or "").replace("\\", "/")
    if not rel.startswith(SHOTS_DIR + "/") or ".." in rel or ":" in rel:
        raise HTTPException(status_code=400, detail="캡처 폴더 밖입니다")
    src = (root / rel).resolve()
    try:
        src.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="폴더 밖")
    if not src.is_file():
        raise HTTPException(status_code=404, detail="없는 캡처")
    ext = src.suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 형식: {ext}")
    r = _attach_slide_image(pid, doc, no, i, src.read_bytes(), ext)

    # ★ 어느 캡처에서 왔는지를 남긴다. 복사본은 `003.png` 라 출처가 지워지는데,
    #   19장을 훑는 동안 "이건 이미 썼다" 가 안 보이면 같은 화면을 두 번 넣는다.
    ov = ws.load_overrides(pid, doc["slug"])
    cur = ov.setdefault("slides", {}).setdefault(str(no), {})
    srcs = list(cur.get("image_srcs") or [])
    idx = max(1, int(i)) - 1
    while len(srcs) <= idx:
        srcs.append("")
    srcs[idx] = rel
    cur["image_srcs"] = srcs[:len(r["images"])]
    ws.save_overrides(pid, doc["slug"], ov)
    r["image_srcs"] = cur["image_srcs"]
    return r


# 배경음악 기본 볼륨 — **아주 작게 깐다.** 배경음악은 알아채면 이미 큰 것이고,
# 이 앱의 발표는 처음부터 끝까지 말이 깔린다. 귀로 맞춰야 하는 값이라
# 프로젝트별로 project.json 의 bgm.volume / bgm.duck 에서 덮어쓴다.
BGM_VOL, BGM_DUCK = 0.15, 0.04

AUDIO_MIME = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a",
              "audio/x-m4a": ".m4a", "audio/ogg": ".opus", "audio/wav": ".wav",
              "audio/x-wav": ".wav", "audio/webm": ".opus"}


class BgmIn(BaseModel):
    """배경음악 한 곡. 그림과 같은 base64 JSON 이다(python-multipart 를 안 깐다)."""
    data_url: str
    name: str = ""


@app.get("/api/projects/{pid}/bgm")
def get_bgm(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    cfg = doc.get("bgm") or {}
    rel = str(cfg.get("file") or "")
    ok = bool(rel) and (ws.project_dir(pid, doc["slug"], create=False) / rel).is_file()
    return {"ok": ok, "file": rel if ok else "", "name": cfg.get("name") or "",
            "volume": cfg.get("volume") or BGM_VOL, "duck": cfg.get("duck") or BGM_DUCK}


@app.post("/api/projects/{pid}/bgm")
def put_bgm(pid: int, body: BgmIn) -> Dict[str, Any]:
    """배경음악을 프로젝트 안으로 들인다.

    ★ 원본을 **프로젝트 폴더에 복사한다.** 완성본의 `assets/` 는 렌더할 때마다
      통째로 지워지고(s9_render), 바깥 경로를 참조해 두면 그 PC 를 떠나는 순간
      끊긴다. 발표물은 폴더째 옮겨 다니는 물건이다.
    """
    import base64 as _b64

    doc = _find(pid)
    m = re.match(r"^data:([^;]+);base64,(.+)$", body.data_url or "", re.S)
    if not m:
        raise HTTPException(status_code=400, detail="오디오 형식을 알 수 없습니다")
    mime, b64 = m.group(1).lower(), m.group(2)
    ext = AUDIO_MIME.get(mime)
    if not ext:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 형식입니다: {mime}")
    try:
        raw = _b64.b64decode(b64)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="오디오를 읽지 못했습니다")
    if len(raw) > 12_000_000:
        raise HTTPException(status_code=400, detail="12MB 를 넘습니다")

    d = ws.step_dir(pid, doc["slug"], "audio")
    for old in d.glob("bgm.*"):          # 확장자가 달라 둘 다 남으면 뭐가 붙는지 모른다
        try:
            old.unlink()
        except OSError:
            pass
    p = d / f"bgm{ext}"
    p.write_bytes(raw)

    rel = f"{ws.STEPS['audio'][0]}/{p.name}"
    doc["bgm"] = {"file": rel, "name": body.name or p.name,
                  "volume": (doc.get("bgm") or {}).get("volume") or BGM_VOL,
                  "duck": (doc.get("bgm") or {}).get("duck") or BGM_DUCK}
    ws.save_project(pid, doc["slug"], doc)
    return {"ok": True, "file": rel, "name": doc["bgm"]["name"], "bytes": len(raw)}


@app.delete("/api/projects/{pid}/bgm")
def del_bgm(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    d = ws.step_dir(pid, doc["slug"], "audio", create=False)
    n = 0
    if d.is_dir():
        for old in d.glob("bgm.*"):
            try:
                old.unlink(); n += 1
            except OSError:
                pass
    doc.pop("bgm", None)
    ws.save_project(pid, doc["slug"], doc)
    return {"ok": True, "removed": n}


@app.delete("/api/projects/{pid}/slide-image/{no}")
def del_slide_image(pid: int, no: int, i: int = 1) -> Dict[str, Any]:
    doc = _find(pid)
    d = ws.sub_dir(pid, doc["slug"], "prd", "참고", create=False)
    stem = f"{no:03d}" if i <= 1 else f"{no:03d}-{int(i)}"
    n = 0
    if d.is_dir():
        for old in d.glob(f"{stem}.*"):
            try:
                old.unlink(); n += 1
            except OSError:
                pass
    ov = ws.load_overrides(pid, doc["slug"])
    cur = ov.get("slides", {}).get(str(no)) or {}
    shots = list(cur.get("images") or ([cur["image"]] if cur.get("image") else []))
    idx = max(1, int(i)) - 1
    if idx < len(shots):
        shots.pop(idx)
    # 출처 기록도 같이 민다 — 안 그러면 뺀 캡처가 고르기 격자에서 계속 "썼음" 이다
    srcs = list(cur.get("image_srcs") or [])
    if idx < len(srcs):
        srcs.pop(idx)
    if shots:
        cur["images"], cur["image"] = shots, shots[0]
    else:
        cur.pop("images", None)
        cur.pop("image", None)
    if srcs:
        cur["image_srcs"] = srcs[:len(shots)]
    else:
        cur.pop("image_srcs", None)
    ws.save_overrides(pid, doc["slug"], ov)
    return {"ok": True, "removed": n, "images": shots,
            "image_srcs": cur.get("image_srcs") or []}


class RefsIn(BaseModel):
    paths: List[str]


@app.post("/api/projects/{pid}/refs")
def post_refs(pid: int, body: RefsIn) -> Dict[str, Any]:
    """참고 자료를 나중에 더 넣는다. 중계기 구조 HTML 같은 것."""
    doc = _find(pid)
    got = refs_mod.collect(pid, doc["slug"], body.paths)
    cur = (doc.get("refs") or {}).get("items") or []
    seen = {i["source"] for i in cur}
    cur += [i for i in got["items"] if i["source"] not in seen]
    for n, it in enumerate(cur, 1):
        it["id"] = f"r{n}"
    doc["refs"] = {"dir": got["dir"], "items": cur}
    ws.save_project(pid, doc["slug"], doc)
    return doc["refs"]


@app.get("/api/projects/{pid}/activity")
def get_activity(pid: int) -> Dict[str, Any]:
    """최근 한 일 · 다시 해야 할 것 — 오른쪽 서랍(#log-rail)이 읽는다.

    ★ 이력 파일을 따로 쓰지 않는다. 디스크에 이미 있는 것(캐시·산출물 파일 시각)만
      읽어서 만든다 — 그래야 목록이 항상 실제와 같다.
    """
    doc = _find(pid)
    return activity.build(pid, doc["slug"], doc)


@app.delete("/api/projects/{pid}")
def hide_project(pid: int) -> Dict[str, Any]:
    """★ 감추기다. 지우기가 아니다 — 폴더는 그대로 두고 경로를 돌려준다."""
    doc = _find(pid)
    return {"ok": True, "dir": ws.hide_project(pid, doc["slug"]),
            "title": doc.get("title") or doc.get("slug")}


# ── 스테이지 ───────────────────────────────────────────────────────────────
@app.get("/api/projects/{pid}/stages")
def get_stages(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    reg = get_registry()
    job = reg.latest(pid)
    return {
        "project_id": pid,
        "stages": stage_states(pid, doc["slug"], doc),
        "job": job.to_dict() if job else None,
    }


@app.get("/api/projects/{pid}/frames")
def get_frames(pid: int) -> Dict[str, Any]:
    """S1 결과 + 오버라이드. 프레임 화면(바닥)이 읽는다."""
    doc = _find(pid)

    data = cached_data(pid, doc["slug"], "s1-frames") or {"items": {}}
    caps = cached_data(pid, doc["slug"], "s3-caption") or {"items": {}}
    ov = ws.load_overrides(pid, doc["slug"]).get("items", {})

    out = []
    for it in doc.get("items", []):
        iid = it["id"]
        src = data.get("items", {}).get(iid)
        if not src:
            continue
        cap = (caps.get("items", {}) or {}).get(iid, {})
        cap_frames = {c.get("id"): c for c in (cap.get("frames") or [])}
        oframes = (ov.get(iid, {}) or {}).get("frames", {})
        frames = []
        for f in src["frames"]:
            c = dict(cap_frames.get(f["id"], {}))
            c.update(oframes.get(f["id"], {}))       # 손편집이 마지막에 이긴다
            frames.append({**f, "caption": c.get("caption"), "alt": c.get("alt"),
                           "selected": bool(c.get("selected")),
                           "check_reason": c.get("check_reason")})
        out.append({
            "id": iid, "title": it.get("title") or iid,
            "source_label": src.get("source_label"),
            "duration_sec": src.get("duration_sec"),
            "peak_score": src.get("peak_score"),
            "pick_method": src.get("pick_method"),
            "frames": frames,
        })
    return {"project_id": pid, "items": out, "has_captions": bool(caps.get("items"))}


@app.get("/api/projects/{pid}/deck")
def get_deck(pid: int) -> Dict[str, Any]:
    """세로 편집표가 읽는 것 — 레인 + 슬라이드(연속번호) + 손편집 병합.

    S2b 가 뼈대를 만들고, 하위 스테이지가 레인별로 채운 것을 번호로 다시 모은다.
    (팬아웃 → 팬인. 아직 안 돈 스테이지의 칸은 비어 있다.)
    """
    doc = _find(pid)
    slug = doc["slug"]
    outline = cached_data(pid, slug, "s2b-outline") or {}
    if not outline:
        return {"project_id": pid, "ready": False, "sections": [], "slides": []}

    frames = (cached_data(pid, slug, "s1-frames") or {}).get("items", {})
    caps = (cached_data(pid, slug, "s3-caption") or {}).get("items", {})
    script = (cached_data(pid, slug, "s6-script") or {}).get("slides", {})
    copy = (cached_data(pid, slug, "s7-copy") or {}).get("slides", {})
    audio = (cached_data(pid, slug, "s11-audio") or {}).get("slides", {})
    ov_slides = ws.load_overrides(pid, slug).get("slides", {})
    # ★ 그림과 라벨 — 「라벨 자리」 화면이 이 둘을 같이 본다. 그림이 비워 둔
    #   자리에 글이 얹히므로 따로 받아서는 맞출 수가 없다.
    #   그림은 번호가 키고(s3b), 원장은 **이름표(data_id)가 키다**.
    imgs = (cached_data(pid, slug, "s3b-images") or {}).get("images", {})
    led = (ws.load_ledger(pid, slug) or {}).get("by_id", {})

    titles = {it["id"]: it.get("title") for it in doc.get("items", [])}
    out: List[Dict[str, Any]] = []
    for sl in outline.get("slides", []):
        no = str(sl["no"])
        s = dict(sl)
        vid = sl.get("video_id")
        if vid:
            f = frames.get(vid, {})
            s["video_title"] = titles.get(vid)
            s["video_duration"] = f.get("duration_sec")
            # ✓ 로 고른 프레임만 후보로 올린다 — 한 줄 = 한 장 = 미디어 하나
            picked = [c for c in (caps.get(vid, {}).get("frames") or [])
                      if c.get("selected")]
            s["frame_candidates"] = [c["id"] for c in picked]
        cp = copy.get(no) or {}
        if cp.get("title"):
            s["title"], s["note"] = cp["title"], cp.get("body") or ""
        # 문구 단계가 돌았는지 — "누가 쓴 글인가" 를 구별하는 데만 쓴다
        s["has_copy"] = bool(cp.get("title"))
        s.setdefault("approve", {})
        # 뺀 장도 목록에는 남긴다 — 되돌릴 수 있어야 하므로 숨기지 않고 표시만 한다
        s["drop"] = bool((ov_slides.get(no) or {}).get("drop"))
        sc = script.get(no) or {}
        s["narration"] = {"text": sc.get("narration_text"),
                          "srt_text": sc.get("srt_text"),
                          "est_sec": sc.get("narration_seconds"),
                          "over_sec": sc.get("over_sec")}
        au = audio.get(no) or {}
        s["audio"] = {"source": au.get("source"), "sec": au.get("duration_sec"),
                      "file": au.get("file")}
        got = imgs.get(no) or {}
        shots = [x.get("file") for x in (got.get("shots") or []) if x.get("file")]
        if not shots and got.get("file"):
            shots = [got["file"]]
        s["images"] = shots
        s["image"] = shots[0] if shots else ""
        s["labels"] = imgprompt.labels_of(led.get(sl.get("data_id") or "") or {})
        # 손편집이 마지막에 이긴다
        for k, v in (ov_slides.get(no) or {}).items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k] = {**s[k], **v}
            else:
                s[k] = v
        # ★ 화면에 실제로 박히는 본문. **손편집 뒤에** 정한다 — 문구 단계가 낸 것도,
        #   구조 설계의 메모도, 사람이 고쳐 쓴 것도 결국 여기로 모인다. 앞에서
        #   정하면 사람이 써 넣은 글이 초안 화면에서 통째로 사라진다.
        s["body"] = (s.get("note") or "").strip()
        # 원고 장의 줄 등장 시각 — 조립(s8)과 **같은 함수**로 확정한다. 두 곳이 각자
        # 계산하면 수정 화면에 적힌 시각과 발표에서 뜨는 시각이 갈린다.
        # ★ 조각 HTML 자체는 여기 싣지 않는다 — 이 응답은 화면이 목록을 그릴 때마다
        #   오가는 것이라, 장마다 5~20KB 를 붙이면 목록 한 번에 수 MB 가 된다.
        #   수정 화면은 미리 뽑아 둔 `html_text`(줄 앞머리)로 충분하다.
        htmldoc.resolve(s)
        out.append(s)

    return {
        "project_id": pid, "ready": True,
        # ★ 판(10/11)을 화면도 알아야 한다 — 영상 렌더 버튼이 이 값으로
        #   굽개를 고르고(s12-video / s12h-hyper), 라벨 화면도 이걸 본다.
        "project": {"image_fit": doc.get("image_fit") or "frame",
                    "title": doc.get("title") or "",
                    "slug": doc.get("slug") or slug},
        "deck_title": outline.get("deck_title"),
        "deck_subtitle": outline.get("deck_subtitle"),
        "sections": outline.get("sections", []),
        "slides": out,
        "tone": (cached_data(pid, slug, "s7-copy") or {}).get("tone"),
        "target_min": ws.load_overrides(pid, slug).get("target_min") or 0,
        "filled": {"caption": bool(caps), "script": bool(script),
                   "audio": bool(audio), "copy": bool(copy)},
    }


# ── 최종 점검 ──────────────────────────────────────────────────────────────
# ★ **굽기 직전에 본다.** 영상 한 편이 몇 십 분이라, 다 굽고 나서 "라벨이 제목에
#   걸렸네" 를 알면 그 시간이 통째로 버려진다. 실제로 그렇게 잃었다(2026-09-18:
#   라벨 아홉 개가 제목 띠에 걸려 있었는데 영상을 굽고 나서야 봤다).
# ★ **이름으로 말한다.** "문제 3건" 이 아니라 "장 7 「갈라 둔 이유」가 제목과
#   겹칩니다 — 라벨 자리에서 y 를 10 위로" 라고 적는다. `tools/doctor.py` 와
#   같은 태도다: 무엇이 없어서 안 되는지를 사람이 바로 고칠 수 있게.
# ★ **막지 않는다.** 경고일 뿐 렌더를 세우지 않는다 — 일부러 그렇게 둔 장도 있다.

# 영상의 제목: 58px · left 3.2% · line-height 1.2 (render/hyper.py 의 h2)
_TTL_PX, _TTL_LH, _TTL_X = 58.0, 1.2, 3.2


def _title_box() -> tuple:
    """제목이 차지하는 세로 띠 (위%, 아래%)."""
    return 2.1, 2.1 + (_TTL_PX * _TTL_LH) / 1080.0 * 100.0


def _title_right(t: str) -> float:
    """제목 오른쪽 끝(%). **어림이다** — 글꼴을 재지 않고 글자 수로 센다.
    한글은 글자마다 폭이 같아서 이 어림이 잘 맞는다. 넉넉히 잡지 않는 이유:
    없는 겹침을 경고하면 사람이 경고를 안 읽게 된다."""
    w = sum(55.0 if "가" <= c <= "힣" else 30.0 for c in (t or ""))
    return (_TTL_X / 100.0 * 1920.0 + w) / 1920.0 * 100.0


@app.get("/api/projects/{pid}/check")
def get_check(pid: int) -> Dict[str, Any]:
    """굽기 전 점검. 막지 않고 **이름으로** 알린다."""
    from render.slides import cue_map

    doc = _find(pid)
    slug = doc["slug"]
    deck = get_deck(pid)
    if not deck.get("ready"):
        return {"ready": False, "items": []}

    items: List[Dict[str, Any]] = []
    def add(level: str, where: str, what: str, fix: str) -> None:
        items.append({"level": level, "where": where, "what": what, "fix": fix})

    cues = cue_map(deck)
    ty0, ty1 = _title_box()

    for s_ in deck.get("slides") or []:
        if s_.get("drop"):
            continue
        no = s_.get("no")
        tag = f"장 {no}"
        title = s_.get("title") or ""

        if s_.get("image_swap") and not s_.get("image"):
            add("err", tag, "그림이 없습니다", "원고 HTML 의 «그림 굽기»")

        nar = (s_.get("narration") or {}).get("srt_text") or ""
        if nar and not (s_.get("audio") or {}).get("file"):
            add("err", tag, "음성이 없습니다", "덱의 «음성/자막 굽기»")

        lbs = [l for l in (s_.get("labels") or []) if (l.get("head") or "").strip()]
        if not lbs:
            continue

        tx1 = _title_right(title)
        for l in lbs:
            y, x = l.get("y"), l.get("x")
            if y is None or x is None:
                continue
            if float(y) < ty1 and float(x) < tx1:
                add("warn", tag, f"「{l.get('head')}」가 제목과 겹칩니다"
                                 f" (x {x} · y {y}, 제목은 y {ty0:.1f}~{ty1:.1f}%"
                                 f" · x {tx1:.0f}% 까지)",
                    "라벨 자리에서 y 를 10 위로")

        cl = cues.get(str(no)) or []
        if not cl:
            continue
        seen: Dict[int, str] = {}
        for l in lbs:
            i = max(0, int(l.get("say_i") or 0))
            k = min(i - 1 if i > 0 else 0, len(cl) - 1)
            if i == 0:
                add("warn", tag, f"「{l.get('head')}」의 말하는 문장이 안 정해졌습니다",
                    "말하는 순간에서 문장 고르기")
            elif k in seen:
                add("warn", tag,
                    f"「{l.get('head')}」와 「{seen[k]}」가 같은 문장({k + 1})에서 뜹니다",
                    "말하는 순간에서 하나를 옮기기")
            seen.setdefault(k, l.get("head") or "")

    # 손편집이 덱에 실렸는가 — 안 실리면 화면에서 고친 것이 영상에 안 나간다
    for st in stage_states(pid, slug, doc):
        if st["key"] == "s8-assemble" and st.get("state") in ("stale", "missing"):
            add("warn", "덱", "손편집이 아직 덱에 안 실렸습니다",
                "«전체 적용» 또는 영상 렌더(조립을 먼저 돌립니다)")

    return {"ready": True,
            "ok": not any(i["level"] == "err" for i in items),
            "items": items}


@app.get("/api/projects/{pid}/cues")
def get_cues(pid: int) -> Dict[str, Any]:
    """장별 자막 문장 `[[시작, 끝, 글], …]` — 「말하는 순간」 화면이 읽는다.

    ★ **같은 함수로 낸다**(`render/slides.cue_map`). 화면이 제 나름대로 문장을
      쪼개면 거기서 고른 번호가 영상에서 다른 문장을 가리킨다 — 맞추라고 만든
      화면이 어긋남의 원인이 된다.
    ★ 음성이 없으면 빈 칸이 온다. 큐 시각은 **실측 음성 길이**에서 나오므로
      합성 전에는 가리킬 초가 아예 없다.
    """
    from render.slides import cue_map
    deck = get_deck(pid)
    if not deck.get("ready"):
        return {"project_id": pid, "ready": False, "cues": {}}
    return {"project_id": pid, "ready": True, "cues": cue_map(deck)}


@app.get("/review/{pid}")
def review_sheet(pid: int, n: int | None = None):
    """검수지 — 씬마다 A4 가로 한 장. SME 에게 보낼 PDF 의 원본이다.

    ★ **파일을 만들지 않는다.** 덱·큐를 그 자리에서 읽어 그린다 — 라벨을 옮기고
      대본을 고친 것이 곧바로 비친다. 파일로 떨궈 두면 「언제 뽑은 것인가」를
      매번 따져야 한다.
    ★ `?n=` 으로 한 씬만 볼 수 있다. 시안을 볼 때와, 고친 장 하나만 다시
      찍어 볼 때 쓴다.
    ★ 그림·소리 주소는 **이미 있는 창구**를 준다. 검수지가 제 나름대로
      경로를 짜면 폴더 구조가 바뀔 때 여기만 조용히 깨진다.
    """
    from fastapi.responses import HTMLResponse

    from render.review import build

    deck = get_deck(pid)
    if not deck.get("ready"):
        return HTMLResponse(
            "<meta charset='utf-8'><body style=\"font-family:system-ui;padding:40px\">"
            "<h2>아직 덱 구조가 없습니다</h2></body>", status_code=200)
    html = build(
        deck,
        img_url=lambda rel: f"/api/projects/{pid}/file/{quote(rel)}",
        audio_url=lambda no: f"/api/projects/{pid}/audio/{no}",
        only=n,
    )
    return HTMLResponse(html)


@app.get("/preview/{pid}")
def preview(pid: int, n: int | None = None):
    """HTML 슬라이드 미리보기 — **미완성 상태에서도 렌더된다.**

    음성·자막·이미지가 아직 없어도 제목과 노트만으로 면이 나와야 한다.
    텍스트 연계가 어울리는지는 실제 슬라이드를 봐야 판단되기 때문이다.
    파일을 만들지 않고 현재 캐시로 즉석에서 그린다(최종 빌드는 S9 가 따로).
    """
    from fastapi.responses import HTMLResponse

    from pipeline.s8_assemble import compose
    from render.slides import PreviewResolver, render_deck

    doc = _find(pid)
    try:
        # ★ 최종 빌드(S9)와 **같은 조립 함수**를 쓴다. 둘이 갈라지면
        #   "여기서 OK 한 면" 과 "나가는 면" 이 달라진다.
        deck, _warn = compose(pid, doc["slug"], doc)
    except RuntimeError as e:
        return HTMLResponse(
            "<meta charset='utf-8'><body style=\"font-family:system-ui;padding:40px\">"
            f"<h2>아직 덱 구조가 없습니다</h2><p>{e}</p></body>", status_code=200)
    # ★ `?n=` 이 붙으면 **한 장만 보는 자리**(편집 화면의 iframe)다.
    #   시작 문을 그리지 않는다 — 거기서는 소리를 낼 일이 없고 문이 면을 가린다.
    # 배경음악은 굽기 전에도 들려야 고를 수 있다. 한 장만 보는 자리(`?n=`)는 제외 —
    # render_deck 이 one=True 면 알아서 뺀다.
    # 폴더를 같이 넘긴다 — 그림 주소에 수정시각을 붙여 캐시가 옛 그림을
    # 물고 있지 않게 한다(`PreviewResolver.asset` 주석 참고).
    res = PreviewResolver(pid, ws.project_dir(pid, doc["slug"], create=False))
    cfg = doc.get("bgm") or {}
    rel = str(cfg.get("file") or "")
    bgm = res.asset(rel) if rel and (
        ws.project_dir(pid, doc["slug"], create=False) / rel).is_file() else ""
    html = render_deck(deck, res,
                       title=(deck.get("project") or {}).get("title") or "",
                       one=n is not None, bgm=bgm,
                       bgm_vol=float(cfg.get("volume") or BGM_VOL),
                       bgm_duck=float(cfg.get("duck") or BGM_DUCK))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/print/{pid}")
def print_script(pid: int):
    """대본 인쇄본 — **SME에게 보낼 자료.** 장마다 [화면 | 읽는 말]을 표로 훑는다.

    Ctrl+P 로 PDF 저장하면 그대로 검토용 자료가 된다. /preview 와 같은 조립
    함수를 쓴다 — 화면에서 보는 장 번호·제목과 인쇄본이 갈라지면 검토가 엇갈린다.
    """
    from fastapi.responses import HTMLResponse

    from pipeline.s8_assemble import compose
    from render.print import render_print

    doc = _find(pid)
    try:
        deck, _warn = compose(pid, doc["slug"], doc)
    except RuntimeError as e:
        return HTMLResponse(
            "<meta charset='utf-8'><body style=\"font-family:system-ui;padding:40px\">"
            f"<h2>아직 덱 구조가 없습니다</h2><p>{e}</p></body>", status_code=200)
    html = render_print(deck, doc.get("narration"))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


class BriefIn(BaseModel):
    """설문 답 — **질문이 고정이 아니므로 답도 자유형이다.**

    S0a 가 레포를 읽고 질문을 만들기 때문에 키가 프로젝트마다 다르다. 넷
    (`audience`·`goal`·`target_min`·`slide_tone`)만 뒤 단계가 이름으로 읽고,
    나머지는 기획서 브리프에 그대로 실려 간다.
    """
    answers: Dict[str, Any]


# 뒤 단계가 이름으로 읽는 키 — 프로젝트 최상위로 올린다
PROMOTED = {"audience", "goal", "target_min", "slide_tone"}


@app.get("/api/projects/{pid}/ask")
def get_ask(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    d = cached_data(pid, doc["slug"], "s0a-ask") or {}
    return {"project_id": pid, "questions": d.get("questions") or [],
            "answers": doc.get("answers") or {}}


@app.post("/api/projects/{pid}/brief")
def post_brief(pid: int, body: BriefIn) -> Dict[str, Any]:
    doc = _find(pid)
    ans = {str(k): v for k, v in (body.answers or {}).items()
           if v not in (None, "")}
    doc["answers"] = ans
    for k in PROMOTED & set(ans):
        v = ans[k]
        doc[k] = int(re.sub(r"\D", "", str(v)) or 0) if k == "target_min" else v
    ws.save_project(pid, doc["slug"], doc)
    return {"ok": True, "answers": ans}


# ── 목차 확인 ──────────────────────────────────────────────────────────────
#
# ★ **사람이 목차를 보고 확정한 다음에 아래로 내려간다.**
#
# 구조 설계가 짠 것을 그대로 믿고 문구·판단·대본을 만들면, 마음에 안 드는
# 목차 위에 비싼 단계들이 쌓인다. 목차는 지금 고치면 공짜고, 나중에 고치면
# 그 뒤를 전부 다시 돌려야 한다. 그래서 여기 문을 하나 둔다.
#
# 확정본은 **구조 설계 캐시를 직접 덮어쓴다** — 오버라이드가 아니다.
# 뒤 단계(판단·문구·대본)가 읽는 것이 그 캐시라서, 오버라이드에 적어 두면
# 사람이 고친 목차를 못 보고 원래 것으로 글을 쓴다.
@app.get("/api/projects/{pid}/outline")
def get_outline(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    d = cached_data(pid, doc["slug"], "s2b-outline") or {}
    return {"ready": bool(d.get("slides")),
            "deck_title": d.get("deck_title", ""),
            "sections": d.get("sections") or [],
            "slides": d.get("slides") or [],
            "dropped": d.get("dropped") or [],
            "budget": d.get("budget") or 0,
            "confirmed_at": doc.get("outline_confirmed_at") or ""}


class OutlineSlide(BaseModel):
    no: int = 0                 # 0 = 새로 끼운 장 (원본이 없다)
    section: str = ""
    kind: str = "note"
    title: str = ""
    note: str = ""
    media_kind: str = "text"
    video_id: Optional[str] = None
    evidence_hint: str = ""


class OutlineIn(BaseModel):
    slides: List[OutlineSlide]


@app.post("/api/projects/{pid}/outline")
def post_outline(pid: int, body: OutlineIn) -> Dict[str, Any]:
    doc = _find(pid)
    slug = doc["slug"]
    env = read_cache(pid, slug, "s2b-outline")
    if not env or not (env.get("data") or {}).get("slides"):
        raise HTTPException(status_code=400, detail="구조 설계를 먼저 돌리세요")
    data = dict(env["data"])

    # ★ **원고가 실어 온 칸을 되살린다.** 화면이 보내는 것은 번호·제목·갈래뿐이라
    #   `say`(그 장에서 말할 것)·줄 시각·그림 이름표가 통째로 빠져 있다. 그대로
    #   쓰면 대본 단계가 빈 것을 보고 Claude 에게 새로 쓰게 하고, 열일곱 분짜리
    #   원고가 여섯 분짜리 대본이 된다(2026-08-17 실측 · 21장에서 실제로 났다).
    #   되살릴 원본은 원고 쪽 캐시다 — 목차를 몇 번 덮어도 거긴 안 바뀐다.
    from pipeline.s2c_capture import manuscript_map, restore
    keep = manuscript_map(pid, slug)

    # 1부터 다시 매긴다. 옛 번호 → 새 번호를 기억해 둔다.
    remap: Dict[str, str] = {}
    slides: List[Dict[str, Any]] = []
    kept = 0
    for i, s in enumerate(body.slides, 1):
        d = s.model_dump()
        if d["no"]:
            remap[str(d["no"])] = str(i)
            kept += restore(d, keep.get(str(d["no"])))
        d["no"] = i
        slides.append(d)
    data["slides"] = slides

    # 장이 하나도 안 남은 섹션은 목차에서 사라진다
    secs = []
    for sec in data.get("sections") or []:
        nos = [s["no"] for s in slides if s["section"] == sec.get("id")]
        if nos:
            secs.append({**sec, "slide_nos": nos})
    data["sections"] = secs

    # ★ 손편집을 같이 옮긴다. 번호가 밀렸는데 안 옮기면 **엉뚱한 장이 고쳐진다** —
    #   이 앱에서 이미 한 번 겪은 사고라, 번호를 건드리는 곳마다 같이 처리한다.
    ov = ws.load_overrides(pid, slug)
    if ov.get("slides"):
        ov["slides"] = {remap[k]: v for k, v in ov["slides"].items() if k in remap}
        ws.save_overrides(pid, slug, ov)

    write_cache(pid, slug, "s2b-outline",
                input_hash=env.get("input_hash", ""), data=data,
                code_version=int(env.get("code_version") or 1),
                model=env.get("model", ""), cost_usd=float(env.get("cost_usd") or 0),
                status=env.get("status", "ok"), warnings=env.get("warnings") or [])

    doc["outline_confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, slug, doc)
    return {"ok": True, "slides": len(slides), "sections": len(secs), "kept": kept}


class OutlineImport(BaseModel):
    """목차 JSON 통째로. 밖에서 만들어 온 것을 그대로 받는다."""
    deck_title: str = ""
    deck_subtitle: str = ""
    sections: List[Dict[str, Any]] = []
    slides: List[Dict[str, Any]] = []
    dropped: List[str] = []


@app.post("/api/projects/{pid}/outline/import")
def import_outline(pid: int, body: OutlineImport) -> Dict[str, Any]:
    """★ 목차를 **밖에서 만들어 와 넣는다.**

    구조 설계를 다시 돌리는 것($1 남짓)과 달리 공짜고, 무엇보다 사람이 손으로
    짠 목차를 그대로 쓸 수 있다. 내보내기 → 편집기에서 고치기 → 불러오기.

    거부하지 않고 **수리한다.** 밖에서 온 JSON 은 어디가 빠져 있을지 모른다 —
    빠진 칸은 기본값으로 채우고 번호는 1부터 다시 매긴다.
    """
    doc = _find(pid)
    slug = doc["slug"]
    if not body.slides:
        raise HTTPException(status_code=400, detail="slides 가 비어 있습니다")

    # ★ 목록을 여기 적지 않는다 — core/manuscript.py 가 유일한 출처다. 예전엔 여기
    #   따로 적혀 있어서, 종류를 늘려도 이 문을 지나가는 순간 모르는 값이 "text" 로
    #   깎였다(목차를 한 번 저장하면 html 장이 전부 글자 장이 되는 사고).
    kinds = set(ms.MEDIA_KINDS)
    slides: List[Dict[str, Any]] = []
    for i, s in enumerate(body.slides, 1):
        title = str(s.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400,
                                detail=f"{i}번째 장에 title 이 없습니다")
        mk = str(s.get("media_kind") or "text")
        slides.append({
            "no": i,
            "section": str(s.get("section") or ""),
            "kind": str(s.get("kind") or "note"),
            "title": title,
            "note": str(s.get("note") or ""),
            "media_kind": mk if mk in kinds else "text",
            "video_id": s.get("video_id") or None,
            "evidence_hint": str(s.get("evidence_hint") or ""),
        })

    # 섹션은 준 것을 쓰되, 장이 가리키는데 없는 섹션은 만들어 준다
    secs = [{"id": str(x.get("id") or ""), "title": str(x.get("title") or ""),
             "kind": str(x.get("kind") or "text"),
             "summary": str(x.get("summary") or "")}
            for x in (body.sections or []) if x.get("id")]
    have = {x["id"] for x in secs}
    for s in slides:
        if s["section"] and s["section"] not in have:
            have.add(s["section"])
            secs.append({"id": s["section"], "title": s["section"],
                         "kind": "text", "summary": ""})
    for sec in secs:
        sec["slide_nos"] = [s["no"] for s in slides if s["section"] == sec["id"]]
    secs = [s for s in secs if s["slide_nos"]]

    env = read_cache(pid, slug, "s2b-outline") or {}
    data = {
        "deck_title": body.deck_title or (env.get("data") or {}).get("deck_title")
                      or doc.get("title") or slug,
        "deck_subtitle": body.deck_subtitle
                         or (env.get("data") or {}).get("deck_subtitle") or "",
        "sections": secs, "slides": slides,
        "budget": len(slides), "dropped": list(body.dropped or []),
    }
    stage = STAGES["s2b-outline"]
    write_cache(pid, slug, "s2b-outline",
                input_hash=stage.input_hash(pid, slug, doc), data=data,
                code_version=stage.code_version, model="(불러온 JSON)",
                cost_usd=0.0, status="ok", warnings=[])

    # ★ 손편집 키는 옛 번호를 가리킨다. 통째로 갈아 끼웠으니 다 버린다 —
    #   남겨 두면 엉뚱한 장에 옛 자막이 붙는다.
    ws.save_overrides(pid, slug, {})
    doc["slide_budget"] = len(slides)
    doc["outline_confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, slug, doc)
    return {"ok": True, "slides": len(slides), "sections": len(secs)}


# ── 초안 통째로 (밖에서 다 짜 와서 넣기) ──────────────────────────────────
#
# ★ **목차 + 문구 + 대본을 한 파일로.** 이 앱을 안 거치고 다른 데서 전부 짜
#   온 경우를 위한 문이다. 넣으면 Claude 단계를 하나도 안 돌리고 바로 굽기로
#   갈 수 있다.
#
# 캐시를 직접 쓴다(오버라이드가 아니다). 뒤 단계가 읽는 것이 캐시라서,
# 오버라이드에 적으면 조립 때만 반영되고 대본은 TTS 로 가지도 못한다.
class DraftSlide(BaseModel):
    no: int = 0
    section: str = ""
    kind: str = "note"
    title: str = ""
    note: str = ""
    media_kind: str = "text"
    video_id: Optional[str] = None
    evidence_hint: str = ""
    body: str = ""                  # 화면에 박히는 본문
    narration: Dict[str, Any] = {}  # {srt_text, text} — 자막과 발음


class DraftIn(BaseModel):
    deck_title: str = ""
    deck_subtitle: str = ""
    sections: List[Dict[str, Any]] = []
    slides: List[DraftSlide]
    dropped: List[str] = []
    tone: str = ""


@app.get("/api/projects/{pid}/draft")
def get_draft(pid: int) -> Dict[str, Any]:
    """지금 상태를 통째로. 이대로 내보내 고쳐서 다시 넣는다."""
    doc = _find(pid)
    slug = doc["slug"]
    o = cached_data(pid, slug, "s2b-outline") or {}
    cp = (cached_data(pid, slug, "s7-copy") or {}).get("slides") or {}
    sc = (cached_data(pid, slug, "s6-script") or {}).get("slides") or {}
    ov = (ws.load_overrides(pid, slug).get("slides") or {})

    slides = []
    for s in (o.get("slides") or []):
        k = str(s["no"])
        if (ov.get(k) or {}).get("drop"):
            continue
        c, n = cp.get(k) or {}, sc.get(k) or {}
        slides.append({
            "no": s["no"], "section": s.get("section", ""),
            "kind": s.get("kind", "note"), "title": c.get("title") or s.get("title", ""),
            "note": s.get("note", ""), "media_kind": s.get("media_kind", "text"),
            "video_id": s.get("video_id"), "evidence_hint": s.get("evidence_hint", ""),
            "body": c.get("body") or "",
            "narration": {"srt_text": n.get("srt_text") or "",
                          "text": n.get("narration_text") or n.get("srt_text") or ""},
        })
    # ★ 설명을 맨 위에 얹어서 내보낸다 — 파일을 받는 쪽은 이 레포가 없다
    return ms.wrap({
            "deck_title": o.get("deck_title", ""),
            "deck_subtitle": o.get("deck_subtitle", ""),
            "sections": [{"id": x.get("id"), "title": x.get("title"),
                          "kind": x.get("kind", "text"), "summary": x.get("summary", "")}
                         for x in (o.get("sections") or [])],
            "slides": slides, "dropped": o.get("dropped") or [],
            "tone": doc.get("slide_tone") or ""})


@app.post("/api/projects/{pid}/draft/import")
def import_draft(pid: int, body: DraftIn) -> Dict[str, Any]:
    """목차·문구·대본을 한 번에 갈아 끼운다. **거부하지 않고 수리한다.**"""
    doc = _find(pid)
    slug = doc["slug"]
    if not body.slides:
        raise HTTPException(status_code=400, detail="slides 가 비어 있습니다")

    kinds = set(ms.MEDIA_KINDS)      # 유일한 출처 — 위 outline/import 와 같은 이유
    cps = float((config.load().get("narration") or {}).get("chars_per_sec") or 5.7)
    cps = float((doc.get("narration") or {}).get("chars_per_sec") or cps)

    slides, copy, script = [], {}, {}
    for i, s in enumerate(body.slides, 1):
        title = (s.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail=f"{i}번째 장에 title 이 없습니다")
        mk = s.media_kind if s.media_kind in kinds else "text"
        slides.append({"no": i, "section": (s.section or "").strip(),
                       "kind": s.kind or "note", "title": title,
                       "note": s.note or "", "media_kind": mk,
                       "video_id": s.video_id or None,
                       "evidence_hint": s.evidence_hint or ""})
        if (s.body or "").strip() or title:
            copy[str(i)] = {"title": title, "body": (s.body or "").strip(),
                            "tone": body.tone or doc.get("slide_tone") or "pitch"}
        nar = s.narration or {}
        srt = str(nar.get("srt_text") or nar.get("text") or "").strip()
        if srt:
            spoken = str(nar.get("text") or srt).strip()
            # 길이는 글자수에서 추정한다. 합성이 끝나면 실측으로 다시 잡힌다.
            n_ch = len(re.sub(r"\s", "", spoken))
            script[str(i)] = {"srt_text": srt, "narration_text": spoken,
                              "narration_seconds": round(n_ch / max(cps, 0.1), 1),
                              "budget_sec": 0.0}

    secs = [{"id": str(x.get("id") or ""), "title": str(x.get("title") or ""),
             "kind": str(x.get("kind") or "text"),
             "summary": str(x.get("summary") or "")}
            for x in (body.sections or []) if x.get("id")]
    have = {x["id"] for x in secs}
    for s in slides:
        if s["section"] and s["section"] not in have:
            have.add(s["section"])
            secs.append({"id": s["section"], "title": s["section"],
                         "kind": "text", "summary": ""})
    for sec in secs:
        sec["slide_nos"] = [s["no"] for s in slides if s["section"] == sec["id"]]
    secs = [s for s in secs if s["slide_nos"]]

    def put(stage_key: str, data: Dict[str, Any]) -> None:
        st = STAGES[stage_key]
        write_cache(pid, slug, stage_key,
                    input_hash=st.input_hash(pid, slug, doc), data=data,
                    code_version=st.code_version, model="(불러온 JSON)",
                    cost_usd=0.0, status="ok", warnings=[])

    old = cached_data(pid, slug, "s2b-outline") or {}
    put("s2b-outline", {
        "deck_title": body.deck_title or old.get("deck_title") or doc.get("title") or slug,
        "deck_subtitle": body.deck_subtitle or old.get("deck_subtitle") or "",
        "sections": secs, "slides": slides,
        "budget": len(slides), "dropped": list(body.dropped or [])})
    if copy:
        put("s7-copy", {"slides": copy, "tone": body.tone or doc.get("slide_tone") or "pitch"})
    if script:
        put("s6-script", {"slides": script,
                          "total_sec": round(sum(v["narration_seconds"]
                                                 for v in script.values()), 1),
                          "chars_per_sec": cps})

    # 옛 손편집은 옛 번호를 가리킨다 — 통째로 갈았으니 버린다
    ws.save_overrides(pid, slug, {})
    doc["slide_budget"] = len(slides)
    doc["outline_confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, slug, doc)
    return {"ok": True, "slides": len(slides), "sections": len(secs),
            "copy": len(copy), "script": len(script)}


class BudgetIn(BaseModel):
    slide_budget: int


@app.post("/api/projects/{pid}/budget")
def post_budget(pid: int, body: BudgetIn) -> Dict[str, Any]:
    """장 예산. ★ 이 값을 바꾸면 구조 설계가 stale 이 되고, 눌러서 다시 짜야 한다.

    자동으로 다시 돌리지 않는다 — Claude 단계는 명시적 클릭에만 돈을 쓴다.
    """
    from pipeline.s2b_outline import slide_budget

    doc = _find(pid)
    doc["slide_budget"] = max(8, min(60, int(body.slide_budget)))
    ws.save_project(pid, doc["slug"], doc)
    return {"ok": True, "slide_budget": slide_budget(doc)}


class SwapIn(BaseModel):
    image_swap: bool
    # 그림을 화면에 어떻게 앉힐까
    #   "frame" 액자(3:2)  ·  "full" 전면(16:9, 글자를 그림에 굽는다)
    #   "plate" 배경판(16:9, **글자는 화면이 얹는다**) ← 11판
    image_fit: str = ""


@app.post("/api/projects/{pid}/image-swap")
def post_image_swap(pid: int, body: SwapIn) -> Dict[str, Any]:
    """원고 장의 몸통을 그림 한 판으로 갈아끼울까.

    켜면 그림이 **도착한 장만** 갈린다 — 안 온 장은 글 그대로 나가므로, 27장 중
    4장만 그려 놓고 켜도 화면이 비지 않는다. 제목·음성·자막·전환은 어느 쪽이든
    그대로다(그림은 몸통 자리만 차지한다).

    ★ 조립(S8)만 다시 돌리면 된다 — 결정론이라 돈이 안 든다. Claude 단계는
      아무것도 낡지 않는다. 그래서 켜고 끄며 둘을 견줘 볼 수 있다.

    ★ `image_fit` 은 **한 번 정하면 안 바꾸는 값**이다(2026-08-29). 그림이
      「액자」로 만들어졌는지 「전면」으로 만들어졌는지에 따라 그림 안의 여백이
      다르다 — 액자 그림을 전면으로 앉히면 그림에 인쇄된 제목이 화면 제목과
      겹치고, 전면 그림을 액자에 넣으면 위아래가 허전해진다. 그래서 **안 보내면
      건드리지 않는다** — 지난 프로젝트를 다시 열어도 값이 그대로 남는다.
    """
    doc = _find(pid)
    doc["image_swap"] = bool(body.image_swap)
    fit = (body.image_fit or "").strip()
    if fit in ("frame", "full", "plate"):
        doc["image_fit"] = fit
        # ★ 판을 바꾸면 **지시문이 낡는다.** 10판 지시문에는 라벨 문구가 박혀
        #   있고 11판은 그 자리를 비우라고 해야 하므로, 같은 지시문을 쓸 수 없다.
        #   `s3a` 의 input_hash 가 image_fit 을 읽으니 자동으로 잡히지만,
        #   사람에게도 보이게 overrides_rev 를 올린다.
        if fit == "plate":
            doc["image_swap"] = True   # 배경판은 몸통을 대신하는 것이 전제다
    # 조립이 이 값을 읽는다 — 바꿨으면 덱이 낡은 것으로 잡혀야 한다
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, doc["slug"], doc)
    return {"ok": True, "image_swap": doc["image_swap"],
            "image_fit": doc.get("image_fit") or "frame"}


class VersionIn(BaseModel):
    name: str
    note: str = ""


@app.get("/api/projects/{pid}/versions")
def get_versions(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    return versions.describe(pid, doc["slug"])


@app.post("/api/projects/{pid}/versions")
def save_version(pid: int, body: VersionIn) -> Dict[str, Any]:
    """지금 상태를 한 벌 뜬다 — 캐시 + 손편집. 원본(영상·레포)은 복사하지 않는다."""
    doc = _find(pid)
    return versions.save(pid, doc["slug"], body.name, body.note)


@app.post("/api/projects/{pid}/versions/{name}/restore")
def restore_version(pid: int, name: str) -> Dict[str, Any]:
    doc = _find(pid)
    if get_registry().latest(pid) and (get_registry().latest(pid).running):
        raise HTTPException(status_code=409, detail="실행 중에는 되돌릴 수 없습니다")
    try:
        return versions.restore(pid, doc["slug"], name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/projects/{pid}/versions/{name}")
def delete_version(pid: int, name: str) -> Dict[str, Any]:
    doc = _find(pid)
    versions.remove(pid, doc["slug"], name)
    return {"ok": True}


@app.get("/api/projects/{pid}/dist")
def get_dist(pid: int) -> Dict[str, Any]:
    """완성본에 무엇이 나왔나.

    ★ 답해야 하는 질문은 하나다 — **무엇을 올리나.**
      그래서 맨 위에 "이 폴더를 통째로 올리세요" 가 오고, 나머지는 곁다리다.
    """
    doc = _find(pid)
    step = ws.STEPS["dist"][0]
    d = ws.project_dir(pid, doc["slug"], create=False) / step
    a = ws.ascii_slug(doc["slug"])
    web = d / a

    def mb(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    out: Dict[str, Any] = {"dir": str(d), "web": None, "extras": []}
    if web.is_dir():
        out["web"] = {
            "name": a,
            "path": str(web),
            "bytes": mb(web),
            "files": sum(1 for f in web.rglob("*") if f.is_file()),
            # 앱 안에서 열어 보는 주소. 옆의 assets/ 가 상대 경로로 그대로 붙는다.
            "url": f"/api/projects/{pid}/file/{step}/{a}/index.html",
        }
    for name, why in ((f"{a}.html", "파일 한 장 — 메일·USB 로 보내면 그대로 열립니다"),
                      (f"{a}.mp4", "슬라이드+내레이션을 이어 붙인 영상 — 재생만 하면 됩니다"),
                      ("올리는법.txt", "무엇을 올리고 무엇을 안 올리는지")):
        f = d / name
        if f.is_file():
            out["extras"].append({
                "name": name, "bytes": f.stat().st_size, "why": why,
                "url": f"/api/projects/{pid}/file/{step}/{name}"})
    cue = d / "cue"
    if cue.is_dir():
        n = sum(1 for f in cue.iterdir() if f.is_file())
        out["extras"].append({"name": "cue/", "bytes": mb(cue), "count": n,
                              "why": f"자막·큐시트 {n}개 — 영상팀용. 웹에는 안 올립니다",
                              "url": ""})
    return out


@app.post("/api/projects/{pid}/reveal")
def reveal(pid: int, step: str = "dist") -> Dict[str, Any]:
    """산출물 폴더를 탐색기에서 연다.

    ★ 로컬 앱이라서 할 수 있는 일이다. 산출물은 앱 밖에 있고 경로도 길어서,
      "어디에 나왔나" 를 글로 알려 주면 사람이 복사해 붙여넣어야 한다.

    ★ `step` 은 **폴더 이름이 아니라 열쇠**다(`ws.STEPS` 의 키). 화면이 경로를
      보내면 탈출 방어가 딸려 오지만, 열쇠는 아는 것만 열리므로 그 문제가 없다.
      예전엔 완성 폴더 하나로 고정했는데, 그림을 주고받는 `09_이미지` 도
      사람이 여는 자리가 됐다(2026-08-14: "직후 만든 폴더를 띄울 수 있는 버튼").
    """
    doc = _find(pid)
    if step not in ws.STEPS:
        raise HTTPException(status_code=400, detail=f"모르는 자리: {step}")
    d = ws.project_dir(pid, doc["slug"], create=False) / ws.STEPS[step][0]
    if not d.is_dir():
        raise HTTPException(status_code=404, detail=f"아직 {ws.STEPS[step][1]} 폴더가 없습니다")
    try:
        if sys.platform == "win32":
            os.startfile(str(d))                       # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"열지 못했습니다: {e}")
    return {"ok": True, "dir": str(d)}


class SpeakIn(BaseModel):
    text: str = ""


@app.post("/api/speak-numbers")
def speak_numbers_api(body: SpeakIn) -> Dict[str, str]:
    """발음 칸의 **숫자만** 소리대로 바꿔 돌려준다. 저장은 하지 않는다.

    ★ 화면이 아니라 여기서 바꾸는 이유 — 규칙이 한 벌이어야 한다. 같은 변환이
      파이썬(대본)과 JS(화면)에 두 벌 있으면 언젠가 서로 다르게 읽는다.
    """
    from core import honorific
    return {"text": honorific.speak_numbers(body.text or "")}


@app.post("/api/speak-roman")
def speak_roman_api(body: SpeakIn) -> Dict[str, str]:
    """발음 칸의 **영문만** 한국어 소리로 바꿔 돌려준다. 저장은 하지 않는다.

    ★ 「숫자를 소리대로」와 같은 자리·같은 방식이다. 자막에서 다시 만들지 않는 것이
      핵심이다 — 발음 칸에는 손으로 고친 것이 이미 얹혀 있어서, 다시 만들면 날아간다.
    ★ 표는 `voicewright/config/pronunciation_map.yaml` 하나뿐이다. 그 파일에 한 줄
      넣으면 여기까지 따라오고, voicewright 의 `/dict` 화면에서 편집할 수 있다.
    """
    from core.roman import speak_roman

    return {"text": speak_roman(body.text or "")}


@app.post("/api/pronounce")
def pronounce_api(body: SpeakIn) -> Dict[str, str]:
    """자막 원문을 **발음 대본**으로 — 괄호·어미·숫자·기호를 한 번에.

    ★ 대본 단계(`s6_script`)가 쓰는 것과 **같은 함수**다. 한 장만 다시 만들고
      싶을 때 전체를 다시 굽지 않게 하는 창구다.
    ★ 몇 번을 돌려도 같은 글이 나온다.
    """
    from core import honorific
    return {"text": honorific.for_speech(body.text or "")}


@app.post("/api/projects/{pid}/pronounce-all")
def pronounce_all(pid: int, apply: bool = False) -> Dict[str, Any]:
    """**덱 전체**의 발음 대본을 지금 자막에서 다시 만든다.

    ★ 왜 자막과 갈랐나 — 손이 가는 순서가 「자막을 읽고 고친다 → 그 자막대로
      발음을 만든다」이기 때문이다(2026-08-17). 한 번에 만들면 자막을
      고쳐도 발음은 옛 자막에서 나온 채로 남는다.
    ★ Claude 를 부르지 않는다. 결정론이라 공짜이고 몇 초다 — 자막을 고칠 때마다
      다시 눌러도 손해가 없다.
    ★ `apply=false` 면 **세어만 본다.** 무엇이 덮이는지 먼저 말하고 묻는다 —
      이 앱에서 조용히 덮은 적이 있고(시각 186개), 그 뒤로는 늘 먼저 말한다.

    손편집(`deck.overrides.json`)의 발음은 **지운다.** 안 지우면 손편집이 늘
      이겨서 다시 만든 것이 화면에 안 보인다 — 20장에서 실제로 그랬다.
      자막 손편집은 건드리지 않는다. 그것이 이 변환의 재료다.
    """
    from core import honorific
    doc = _find(pid)
    slug = doc["slug"]
    env = read_cache(pid, slug, "s6-script")
    if not env or not (env.get("data") or {}).get("slides"):
        raise HTTPException(status_code=400, detail="대본을 먼저 만드세요")

    cps = float((doc.get("narration") or config.load()["narration"])
                .get("chars_per_sec", 5.7))
    now = narration_of(pid, slug)          # 손편집이 얹힌 지금 값
    ov = ws.load_overrides(pid, slug)
    ov_slides = ov.get("slides") or {}
    slides = (env["data"]["slides"])

    changed, hand, plan = 0, 0, {}
    for key, cur in now.items():
        srt = (cur.get("srt_text") or "").strip()
        if not srt:
            continue
        new = honorific.for_speech(srt)
        if new == (cur.get("text") or "").strip():
            continue
        changed += 1
        # 손으로 고쳐 둔 발음이 있는 장 — 덮이는 것이 이것이다
        if "text" in ((ov_slides.get(key) or {}).get("narration") or {}):
            hand += 1
        plan[key] = new

    if not apply:
        return {"ok": True, "n": len(now), "changed": changed, "hand": hand,
                "sample": [{"no": int(k), "text": v[:70]}
                           for k, v in list(plan.items())[:3]]}

    for key, new in plan.items():
        row = slides.get(key) or {}
        row["narration_text"] = new
        row["narration_seconds"] = round(
            len(re.sub(r"\s", "", new)) / max(cps, 0.1), 1)
        slides[key] = row
        # 손편집의 발음만 걷는다 — 자막 손편집은 재료라서 그대로 둔다
        nar = (ov_slides.get(key) or {}).get("narration")
        if isinstance(nar, dict) and "text" in nar:
            nar.pop("text", None)
            if not nar:
                ov_slides[key].pop("narration", None)
            if not ov_slides[key]:
                ov_slides.pop(key, None)

    env["data"]["slides"] = slides
    env["at"] = datetime.now().isoformat(timespec="seconds")
    ws.write_json(cache_path(pid, slug, "s6-script"), env)
    if hand:
        ov["slides"] = ov_slides
        ws.save_overrides(pid, slug, ov)
    return {"ok": True, "n": len(now), "changed": changed, "hand": hand}


# ── 장별 음성 ──────────────────────────────────────────────────────────────
def _audio_rel(pid: int, slug: str, no: int) -> str:
    """그 장의 음성 파일 경로(프로젝트 폴더 기준). 없으면 빈 문자열.

    ★ 자리를 새로 정하지 않는다 — **S10 이 적어 둔 것**을 읽는다. 성우 파일이
      있으면 그것, 없으면 합성본이라는 순서가 거기서 이미 정해졌고, 여기서 또
      찾으면 두 규칙이 갈려서 화면과 영상이 다른 소리를 낸다.
    """
    one = ((cached_data(pid, slug, "s10-tts") or {}).get("slides") or {}).get(str(no))
    return str((one or {}).get("file") or "")


@app.get("/api/projects/{pid}/audio/{no}")
def get_audio(pid: int, no: int):
    """그 장의 음성 — **덱 화면의 재생기가 부르는 자리.**

    ★ 이 창구가 없어서 재생기가 계속 404 를 받고 `0:00 / 0:00` 만 띄웠다
      (2026-08-16 발견: "여기서 왜 음성이 안 나올까요"). 파일도 대본도 멀쩡했고
      부를 곳이 없었을 뿐이다.
    """
    doc = _find(pid)
    rel = _audio_rel(pid, doc["slug"], no)
    if not rel:
        raise HTTPException(status_code=404, detail=f"{no}장 음성이 아직 없습니다")
    root = ws.project_dir(pid, doc["slug"], create=False).resolve()
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="폴더 밖")
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"파일이 없습니다: {rel}")
    from render.resolvers import MIME
    # ★ 캐시를 걸지 않는다 — 다시 합성하면 **같은 이름에 다른 소리**가 들어온다.
    #   600초 캐시가 걸려 있으면 고친 발음을 눌러도 옛 소리가 다시 난다.
    return FileResponse(str(p), media_type=MIME.get(p.suffix.lower(), "audio/wav"),
                        headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/revoice/{no}")
def revoice(pid: int, no: int) -> Dict[str, Any]:
    """발음을 고친 그 장만 **다시 합성한다.**

    ★ 전체 합성은 31장에 몇 분이다. 발음 한 군데 고칠 때마다 그걸 돌리면 검수가
      끝나지 않는다. 여기서 고치고, 여기서 듣고, 여기서 OK 한다.
    """
    doc = _find(pid)
    from pipeline import s10_tts
    try:
        r = s10_tts.synth_one(pid, doc["slug"], no)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # ★ 길이가 달라졌으면 **자막 시각이 밀린다.** s11 은 start/end 를 누적으로
    #   들고 있어서, 한 장이 0.1초 짧아지면 그 뒤 장이 전부 어긋난다. 여기서
    #   몰래 고치지 않고 **화면이 말하게** 한다 — 자막은 공짜(결정론)라 다시
    #   돌리면 그만이고, 조용히 어긋난 자막이 나가는 쪽이 훨씬 비싸다.
    old = (((cached_data(pid, doc["slug"], "s11-audio") or {}).get("slides") or {})
           .get(str(no)) or {}).get("duration_sec")
    new = r.get("duration_sec")
    shifted = (old is None or new is None or abs(float(old) - float(new)) > 0.02)
    return {"ok": True, "no": r["no"], "sec": new, "file": r.get("file"),
            "was": old, "subtitle_stale": bool(shifted),
            # 화면이 곧바로 다시 듣게 — 캐시를 피하는 꼬리표를 같이 준다
            "url": f"/api/projects/{pid}/audio/{no}?v={int(time.time())}"}


# ── 모션 리마스터 ──────────────────────────────────────────────────────────
# ★ 스테이지가 아니다 — 렌더링에서 끝나는 영상도 있다. 자세한 이유는
#   `pipeline/s13_motion.py` 머리말에 있다.
@app.get("/api/projects/{pid}/motion")
def get_motion(pid: int) -> Dict[str, Any]:
    doc = _find(pid)
    return motion.state(pid, doc["slug"])


@app.post("/api/projects/{pid}/motion/picker")
def motion_picker(pid: int, force: bool = False) -> Dict[str, Any]:
    doc = _find(pid)
    try:
        job = get_registry().start(
            project_id=pid, stage="s13-motion", label="마스크 지정기",
            work=lambda j: motion.run_picker(j, pid, doc["slug"], doc, force=force))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return job.to_dict()


class ZonesIn(BaseModel):
    """지정기에서 내려받은 zones.json.

    ★ 슬라이드 그림과 **같은 방식**(base64 JSON)이다 — `python-multipart` 를
      새로 깔지 않으려는 것. 마스크 파일은 수십 KB 라 넉넉하다.
    """
    data_url: str = ""
    text: str = ""


@app.post("/api/projects/{pid}/motion/zones")
def motion_zones(pid: int, body: ZonesIn) -> Dict[str, Any]:
    import base64 as _b64

    doc = _find(pid)
    raw = b""
    if body.data_url:
        m = re.match(r"^data:[^;]*;base64,(.+)$", body.data_url, re.S)
        if not m:
            raise HTTPException(status_code=400, detail="파일을 읽지 못했습니다")
        try:
            raw = _b64.b64decode(m.group(1))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="파일을 읽지 못했습니다")
    elif body.text:
        raw = body.text.encode("utf-8")
    if not raw:
        raise HTTPException(status_code=400, detail="빈 파일입니다")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=400, detail="8MB 를 넘습니다")
    try:
        return motion.save_zones(pid, doc["slug"], raw)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 스토리보드 정리 — 장 하나씩 ────────────────────────────────────────────
@app.get("/api/projects/{pid}/motion/still/{no}")
def motion_still(pid: int, no: int):
    """그 장의 **영상 프레임**. 마스킹 상자와 좌표계가 같아야 해서 이걸 깐다.

    ★ 살아 있는 미리보기(iframe)를 깔면 안 된다. 상자 좌표는 1920×1080 영상
      기준인데 미리보기는 브라우저가 다시 레이아웃해서 픽셀이 어긋난다.
    """
    doc = _find(pid)
    p = motion.still_of(pid, doc["slug"], no)
    if p is None:
        raise HTTPException(status_code=404, detail=f"{no}장 스틸이 없습니다")
    return FileResponse(str(p), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/projects/{pid}/motion/scene/{no}")
def motion_scene(pid: int, no: int) -> Dict[str, Any]:
    """그 장의 상자 + 시각 + 자막 문장. 화면이 이것 하나로 그린다."""
    doc = _find(pid)
    return motion.scene_of(pid, doc["slug"], no)


class SceneIn(BaseModel):
    boxes: List[Dict[str, Any]] = []
    done: Optional[bool] = None


@app.post("/api/projects/{pid}/motion/scene/{no}")
def motion_scene_save(pid: int, no: int, body: SceneIn) -> Dict[str, Any]:
    """**그 장만** 저장한다 — 나머지 씬은 건드리지 않는다."""
    doc = _find(pid)
    try:
        return motion.save_scene(pid, doc["slug"], no, body.boxes, body.done)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/projects/{pid}/motion/scene/{no}/autotime")
def motion_autotime(pid: int, no: int) -> Dict[str, Any]:
    """자막 문장 시각으로 상자 시각을 깔아 준다. 저장은 화면이 시킨다."""
    doc = _find(pid)
    return {"boxes": motion.autotime(pid, doc["slug"], no)}


@app.post("/api/projects/{pid}/motion/order")
def motion_order(pid: int, no: int = 0) -> Dict[str, Any]:
    """상자 안 글자를 **읽어서** 대본과 짝짓고 차례를 잡는다.

    ★ `no` 를 주면 그 장만, 안 주면 상자가 있는 장 전부. 돈이 드는 단계라
      (Claude vision) 명시적으로 눌러야 돈다 — 자동 실행 대상이 아니다.
    """
    doc = _find(pid)
    from pipeline import s13b_order
    only = [no] if no else None
    try:
        job = get_registry().start(
            project_id=pid, stage="s13b-order",
            label=f"{no}장 차례 잡기" if no else "차례 잡기",
            work=lambda j: s13b_order.run(j, pid, doc["slug"], doc, only=only))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return job.to_dict()


@app.post("/api/projects/{pid}/motion/zones/auto")
def motion_zones_auto(pid: int, no: int = 0, apply: bool = False) -> Dict[str, Any]:
    """원장에 적어 둔 **라벨을 그림에서 찾아** 상자를 놓고, 제대로 나왔는지 본다.

    ★ `zones.json` 을 건드리지 않는다. 찾은 상자는 `<stem>-zones.gen.json` 에 두고
      「지정기 만들기」가 그것을 밑그림으로 깐다 — 사람이 고친 것을 덮지 않는다.
    ★ 돈이 드는 단계라(Claude vision) 눌러야 돈다. `no` 를 주면 그 장만.
    """
    doc = _find(pid)
    from pipeline import s13c_zones
    only = [no] if no else None
    try:
        job = get_registry().start(
            project_id=pid, stage="s13c-zones",
            label=f"{no}장 상자 찾기" if no else "상자 자리 찾기",
            work=lambda j: s13c_zones.run(j, pid, doc["slug"], doc,
                                          only=only, apply=apply))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return job.to_dict()


@app.post("/api/projects/{pid}/motion/bake")
def motion_bake(pid: int, mode: str = "시안", vals: str = "") -> Dict[str, Any]:
    doc = _find(pid)
    try:
        job = get_registry().start(
            project_id=pid, stage="s13-motion",
            label="모션 시안" if mode != "전체" else "모션 전체",
            work=lambda j: motion.run_bake(j, pid, doc["slug"], doc,
                                           mode=mode, vals=vals))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return job.to_dict()


@app.get("/api/projects/{pid}/file/{rel:path}")
def get_file(pid: int, rel: str):
    """프로젝트 폴더 안의 산출물 서빙(프레임·그림·음성·자막).

    ★ 경로 탈출 차단이 이 함수의 존재 이유다. `rel` 은 덱 데이터에서 오고,
      덱 데이터에는 Claude 가 쓴 값이 섞인다. 절대경로·`..` 을 모두 거부하고
      resolve 후 프로젝트 폴더 안인지 다시 확인한다.
    """
    doc = _find(pid)
    root = ws.project_dir(pid, doc["slug"], create=False).resolve()
    if ".." in rel or rel.startswith(("/", "\\")) or ":" in rel:
        raise HTTPException(status_code=400, detail="잘못된 경로")
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="폴더 밖")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="없는 파일")
    from render.resolvers import MIME
    return FileResponse(str(p), media_type=MIME.get(p.suffix.lower(),
                                                    "application/octet-stream"),
                        headers={"Cache-Control": "public, max-age=600"})


@app.get("/api/projects/{pid}/img/{step}/{name}")
def get_image(pid: int, step: str, name: str):
    """추출된 프레임 서빙. **경로 탈출을 막는다** — name 은 모델/사용자 입력일 수 있다."""
    doc = _find(pid)
    if step not in ws.STEPS:
        raise HTTPException(status_code=404, detail="모르는 단계")
    base = ws.step_dir(pid, doc["slug"], step, create=False)
    p = ws.safe_child(base, name)
    if p is None:
        raise HTTPException(status_code=404, detail="없는 파일")
    return FileResponse(str(p), media_type="image/webp",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/projects/{pid}/video/{iid}")
def get_video(pid: int, iid: str):
    """원본 영상 미리보기.

    ★ 원본은 **복사하지 않는다.** `_video-context/` 에 그대로 두고 여기서 읽는다.
      다만 mkv 는 브라우저가 재생하지 못하므로 mp4 로 **리먹스**한다 —
      `-c copy` 라 재인코딩이 아니고 무손실이며 몇 초면 끝난다.
      결과는 07_음성 옆이 아니라 프레임 단계 아래 `_preview/` 에 캐시한다.

    프레임을 고를 때 "이 순간이 맞나" 를 확인하려면 영상을 그 지점부터 볼 수
    있어야 한다. 그게 없으면 스틸만 보고 ✓ 를 찍게 된다.
    """
    doc = _find(pid)
    item = next((i for i in doc.get("items", []) if i["id"] == iid), None)
    if item is None:
        raise HTTPException(status_code=404, detail="없는 항목")

    src = Path(doc["video_dir"]) / item["file"]
    if not src.is_file():
        # NFC/NFD 불일치 대비 — macOS 에서 온 파일명은 == 이 실패한다
        from pipeline.s1_frames import _resolve

        src = _resolve(Path(doc["video_dir"]), item["file"])
        if src is None:
            raise HTTPException(status_code=404, detail=f"영상 파일이 없습니다: {item['file']}")

    prev = ws.sub_dir(pid, doc["slug"], "frames", "_preview") / f"{iid}.mp4"
    if not (prev.is_file() and prev.stat().st_size > 1000):
        from pipeline.s1_frames import _run

        r = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                  "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
                  "-c", "copy", "-movflags", "+faststart", str(prev)], timeout=600)
        if r.returncode != 0 or not prev.is_file():
            # 코덱이 mp4 컨테이너에 안 들어가는 경우 — 그때만 재인코딩
            r = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                      "-i", str(src), "-vf", "scale=1280:-2:flags=lanczos", "-r", "30",
                      "-c:v", "libx264", "-crf", "26", "-preset", "veryfast",
                      "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                      "-movflags", "+faststart", str(prev)], timeout=1800)
            if r.returncode != 0:
                raise HTTPException(status_code=500,
                                    detail=f"영상 변환 실패: {(r.stderr or '')[-200:]}")

    # FileResponse 가 Range(206) 를 처리한다 — seek 이 되려면 필요하다.
    return FileResponse(str(prev), media_type="video/mp4",
                        headers={"Accept-Ranges": "bytes",
                                 "Cache-Control": "public, max-age=3600"})


class OverrideIn(BaseModel):
    patch: Dict[str, Any]


@app.post("/api/projects/{pid}/overrides")
def post_overrides(pid: int, body: OverrideIn) -> Dict[str, Any]:
    """손편집 저장(sparse deep-merge). 스테이지를 다시 돌려도 이건 살아남는다."""
    doc = _find(pid)
    cur = ws.load_overrides(pid, doc["slug"])

    def merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(a)
        for k, v in (b or {}).items():
            out[k] = merge(out.get(k, {}), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        return out

    ws.save_overrides(pid, doc["slug"], merge(cur, body.patch))

    # ★ 손편집도 **조립을 낡게 만든다.** 오버라이드 파일은 스테이지 해시에 안
    #   들어가서, 예전엔 문구를 고쳐도 완성본이 "최신" 으로 남았다 — 그러면
    #   고쳐 놓고 안 구운 채로 발표하러 간다. 세는 값 하나를 프로젝트에 두고
    #   s8 이 그걸 읽게 해서, 고치는 순간 "다시 구우세요" 가 뜨게 한다.
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1

    # ★ 대본을 고친 것만 따로 센다. 음성 합성은 22장을 다시 읽는 일이라, 그림 한 장
    #   넣었다고 같이 돌면 몇 분이 그냥 나간다. `overrides_rev` 는 조립(s8)이 읽고,
    #   이 값은 음성·자막(s10·s11)이 읽는다 — 낡음의 이유가 서로 다르다.
    touched_narration = any(
        isinstance(v, dict) and "narration" in v
        for v in ((body.patch or {}).get("slides") or {}).values())
    if touched_narration:
        doc["narration_rev"] = int(doc.get("narration_rev") or 0) + 1

    ws.save_project(pid, doc["slug"], doc)
    return {"ok": True, "overrides_rev": doc["overrides_rev"],
            "narration_rev": doc.get("narration_rev") or 0}


@app.post("/api/projects/{pid}/stages/{stage}/run")
def run_stage(pid: int, stage: str, force: bool = False) -> Dict[str, Any]:
    doc = _find(pid)
    spec = STAGES.get(stage)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"모르는 스테이지: {stage}")
    if spec.run is None:
        raise HTTPException(status_code=501, detail=f"{spec.label} 은 아직 구현 전입니다")

    reg = get_registry()
    try:
        job = reg.start(
            project_id=pid, stage=stage, label=spec.label,
            work=lambda j: spec.run(j, pid, doc["slug"], doc, force=force),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return job.to_dict()


# ── 잡 ─────────────────────────────────────────────────────────────────────
@app.get("/api/jobs/running")
def job_running() -> Dict[str, Any]:
    j = get_registry().any_running()
    return j.to_dict() if j else {"running": False}


@app.get("/api/jobs/{job_id}")
def job_get(job_id: str) -> Dict[str, Any]:
    j = get_registry().get(job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="없는 잡입니다")
    return j.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> Dict[str, Any]:
    j = get_registry().get(job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="없는 잡입니다")
    j.cancel()
    return j.to_dict()


# ── 오류 봉투 ──────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
def on_error(_req, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500,
                        content={"detail": f"{type(exc).__name__}: {exc}"})


# ── 부팅 ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def _open_browser() -> None:
    """서버가 실제로 듣기 시작한 뒤에 브라우저를 연다.

    run.bat 에서 `start ""` 로 먼저 열면 부팅(1~3초)을 앞질러
    ERR_CONNECTION_REFUSED 페이지가 뜬다 — IDA 에서 실제로 겪은 문제.
    """
    if os.environ.get("SHOWCASE_OPEN_BROWSER") != "1":
        return
    port = config.load()["port"]
    threading.Timer(0.6, lambda: webbrowser.open(f"http://localhost:{port}")).start()
