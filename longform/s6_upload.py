"""s6 — YouTube Studio 자동 업로드 (Playwright + 실제 Chrome, CDP 접속).

    python -m longform login            # 처음 한 번: 전용 프로필 Chrome 이 뜬다 → 구글 로그인 → 창 닫기
    python -m longform upload [--only L01] [--dry-run] [--max N]

★ 왜 CDP 인가 — Playwright 가 띄운 브라우저는 구글이 로그인을 막는다("안전하지 않은 브라우저").
  그래서 **진짜 Chrome 을 전용 프로필(profiles/<채널>)로 직접 띄우고** Playwright 는 디버깅
  포트로 붙기만 한다. 로그인 쿠키는 그 프로필에 남아 이후 무인으로 돈다.
★ 순서: 업로드 대화상자 → 파일 → 제목·설명 → 썸네일 → 재생목록 → 아동용 아님 → 다음×3
  → 공개 범위(기본 일부공개) → 업로드 완료 대기 → 저장 → 영상 ID 기록.
★ 15분 넘는 영상은 채널 **전화 인증**이 필요하다. 맞춤 썸네일도 인증 채널만 된다.
★ Studio 화면은 자주 바뀐다. 선택자는 `ytcp-*` 요소·id 위주로 두고, 실패하면 단계마다 남긴
  스크린샷(logs/upload/)을 보고 SEL 표만 고치면 된다.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from longform.config import REPO, Job
from longform.state import State
from longform.util import log, read_json, statement, warn, write_json

SEL = {
    "file": 'ytcp-uploads-file-picker input[type="file"], input[name="Filedata"]',
    "title": "#title-textarea #textbox",
    "desc": "#description-textarea #textbox",
    "thumb": "input#file-loader",
    "playlist_trigger": "ytcp-video-metadata-playlists ytcp-dropdown-trigger, #basics ytcp-video-metadata-playlists .dropdown-trigger-text",
    "playlist_dialog": "ytcp-playlist-dialog",
    "kids_no": 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
    "kids_yes": 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_MFK"]',
    "next": "#next-button",
    "visibility": 'tp-yt-paper-radio-button[name="{v}"]',
    "done": "#done-button",
    "video_link": "ytcp-video-info a, .video-url-fadeable a",
    "progress": "ytcp-video-upload-progress, .progress-label",
    "close": "ytcp-video-share-dialog #close-button, ytcp-uploads-still-processing-dialog #close-button, #close-button",
}
LIMIT_RE = re.compile(r"일일 업로드 한도|daily upload limit|업로드 한도에 도달", re.I)
UPLOADING_RE = re.compile(r"(업로드 중|Uploading)[^0-9]*\d+\s*%", re.I)


class LimitReached(Exception):
    pass


# ── Chrome ────────────────────────────────────────────────────────────────
def _chrome(job: Job) -> str:
    c = job.get("youtube.chrome")
    for cand in [c, r"C:/Program Files/Google/Chrome/Application/chrome.exe",
                 r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"]:
        if cand and Path(cand).exists():
            return str(cand)
    raise SystemExit("[error] Chrome 을 찾지 못했습니다 — job.json youtube.chrome 을 지정하세요")


def _profile(job: Job) -> Path:
    p = job.path(job.get("youtube.profile", f"profiles/{job.name}"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def login(job: Job) -> None:
    prof = _profile(job)
    log(f"전용 프로필로 Chrome 을 엽니다: {prof}")
    log(f"→ {job.get('youtube.handle')} 채널 소유 구글 계정으로 로그인하고, Studio 가 열리면 창을 닫으십시오.")
    subprocess.run([_chrome(job), f"--user-data-dir={prof}", "--no-first-run",
                    "--no-default-browser-check", "https://studio.youtube.com"])
    log("로그인 창이 닫혔습니다. 이제 upload 를 돌리면 됩니다.")


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_chrome(job: Job) -> Optional[subprocess.Popen]:
    port = int(job.get("youtube.cdp_port", 9333))
    if _port_open(port):
        log(f"이미 떠 있는 Chrome(포트 {port})에 붙습니다")
        return None
    proc = subprocess.Popen([_chrome(job), f"--user-data-dir={_profile(job)}",
                             f"--remote-debugging-port={port}", "--no-first-run",
                             "--no-default-browser-check", "--window-size=1500,1000", "about:blank"])
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("[error] Chrome 디버깅 포트가 열리지 않았습니다(같은 프로필 Chrome 창이 이미 열려 있으면 닫으십시오)")


# ── 화면 조작 ─────────────────────────────────────────────────────────────
class Studio:
    def __init__(self, job: Job, page, shots: Path):
        self.job, self.page, self.shots = job, page, shots

    def shot(self, name: str) -> None:
        try:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(self.shots / f"{time.strftime('%m%d-%H%M%S')}-{name}.png"))
        except Exception:
            pass

    def channel_id(self, state: State) -> str:
        cid = self.job.get("youtube.channel_id") or state.doc.get("channel_id")
        if cid:
            return cid
        handle = self.job.get("youtube.handle")
        self.page.goto(f"https://www.youtube.com/{handle}", wait_until="domcontentloaded")
        html = self.page.content()
        m = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', html) or \
            re.search(r"youtube\.com/channel/(UC[\w-]{22})", html)
        if not m:
            raise SystemExit(f"[error] {handle} 의 채널 ID 를 못 찾았습니다 — job.json youtube.channel_id 를 직접 넣으십시오")
        state.doc["channel_id"] = m.group(1)
        state.save()
        log(f"채널 {handle} = {m.group(1)}")
        return m.group(1)

    def open_upload(self, cid: str) -> None:
        pg = self.page
        pg.goto(f"https://studio.youtube.com/channel/{cid}/videos/upload?d=ud", wait_until="domcontentloaded")
        if "accounts.google.com" in pg.url:
            raise SystemExit("[error] 로그인되어 있지 않습니다 — 먼저 `python -m longform login`")
        pg.wait_for_selector(SEL["file"], state="attached", timeout=60_000)

    def fill_box(self, sel: str, text: str) -> None:
        box = self.page.locator(sel).first
        box.wait_for(state="visible", timeout=120_000)
        box.click()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")
        box.fill(text)

    def check_limit(self) -> None:
        if LIMIT_RE.search(self.page.inner_text("body") or ""):
            raise LimitReached("일일 업로드 한도")

    def playlist(self, name: str) -> None:
        pg = self.page
        try:
            pg.locator(SEL["playlist_trigger"]).first.click(timeout=15_000)
            dlg = pg.locator(SEL["playlist_dialog"]).first
            dlg.wait_for(state="visible", timeout=15_000)
            item = dlg.locator("tp-yt-paper-checkbox, ytcp-checkbox-lit", has_text=name).first
            if item.count() == 0:
                log(f"재생목록 '{name}' 이 없어 새로 만듭니다")
                dlg.get_by_role("button", name=re.compile("새 재생목록|New playlist")).first.click()
                menu = pg.get_by_text(re.compile(r"^\s*(새 재생목록|New playlist)\s*$")).last
                if menu.count():
                    try:
                        menu.click(timeout=3000)
                    except Exception:
                        pass
                cre = pg.locator("ytcp-playlist-creation-dialog").first
                cre.wait_for(state="visible", timeout=15_000)
                cre.locator("#textbox, textarea").first.fill(name)
                cre.get_by_role("button", name=re.compile("만들기|Create")).last.click()
                time.sleep(2)
                item = dlg.locator("tp-yt-paper-checkbox, ytcp-checkbox-lit", has_text=name).first
            if item.count() and (item.get_attribute("aria-checked") or "false") != "true":
                item.click()
            dlg.get_by_role("button", name=re.compile("완료|Done")).last.click()
        except Exception as e:
            warn(f"재생목록 지정 실패({e.__class__.__name__}) — 업로드는 계속합니다. 나중에 Studio 에서 지정하십시오")
            self.shot("playlist-fail")
            try:
                pg.keyboard.press("Escape")
            except Exception:
                pass

    def wait_uploaded(self, timeout_s: int = 7200) -> None:
        t0 = time.time()
        last = ""
        while time.time() - t0 < timeout_s:
            txt = ""
            try:
                txt = " ".join(self.page.locator(SEL["progress"]).all_inner_texts())
            except Exception:
                pass
            if txt and not UPLOADING_RE.search(txt):
                log(f"업로드 완료 — {txt.strip()[:60]}")
                return
            if txt != last:
                log(f"  {txt.strip()[:60]}")
                last = txt
            time.sleep(5)
        raise TimeoutError("업로드가 끝나지 않았습니다")

    def video_id(self) -> str:
        for _ in range(60):
            try:
                href = self.page.locator(SEL["video_link"]).first.get_attribute("href") or ""
                m = re.search(r"(?:youtu\.be/|v=|/video/)([\w-]{11})", href)
                if m:
                    return m.group(1)
            except Exception:
                pass
            time.sleep(1)
        return ""

    def upload(self, cid: str, meta: Dict[str, Any], dry: bool) -> Dict[str, Any]:
        pg, lid = self.page, meta["lecture"]
        self.open_upload(cid)
        pg.locator(SEL["file"]).first.set_input_files(meta["video"])
        log(f"{lid} 파일 전송 시작 — {Path(meta['video']).name}")
        time.sleep(3)
        self.check_limit()
        self.fill_box(SEL["title"], meta["title"])
        self.fill_box(SEL["desc"], meta["description"])
        if meta.get("thumbnail") and Path(meta["thumbnail"]).exists():
            try:
                pg.locator(SEL["thumb"]).first.set_input_files(meta["thumbnail"], timeout=10_000)
            except Exception:
                warn("썸네일 지정 실패 — 채널 인증(맞춤 썸네일 권한)을 확인하십시오")
        if meta.get("playlist"):
            self.playlist(meta["playlist"])
        kids = SEL["kids_yes"] if self.job.get("youtube.made_for_kids") else SEL["kids_no"]
        pg.locator(kids).first.click(timeout=30_000)
        self.shot(f"{lid}-1-details")
        vid = self.video_id()
        for i in range(3):
            pg.locator(SEL["next"]).first.click(timeout=30_000)
            time.sleep(1.5)
        vis = (meta.get("visibility") or "UNLISTED").upper()
        pg.locator(SEL["visibility"].format(v=vis)).first.click(timeout=30_000)
        self.shot(f"{lid}-2-visibility")
        vid = vid or self.video_id()
        if dry:
            log(f"{lid} [dry-run] 저장 직전에서 멈춥니다(영상 {vid or '?'}) — 이 업로드는 Studio 에 초안으로 남습니다")
            return {"id": vid, "dry_run": True}
        self.wait_uploaded()
        pg.locator(SEL["done"]).first.click(timeout=60_000)
        time.sleep(4)
        self.shot(f"{lid}-3-done")
        try:
            pg.locator(SEL["close"]).first.click(timeout=15_000)
        except Exception:
            pass
        if not vid:
            raise RuntimeError("영상 ID 를 읽지 못했습니다 — Studio 에서 확인하십시오")
        return {"id": vid, "url": f"https://youtu.be/{vid}", "visibility": vis}


def run(job: Job, only: Optional[List[str]] = None, dry: bool = False,
        max_n: Optional[int] = None, force: bool = False) -> None:
    from playwright.sync_api import sync_playwright

    cur = read_json(job.dir / "curriculum.json")
    state = State(job)
    todo = []
    for L in cur["lectures"]:
        if only and L["id"] not in only:
            continue
        meta = read_json(job.meta_dir / f"{L['id']}.json")
        if not meta:
            warn(f"{L['id']} 메타가 없습니다 — s5 먼저")
            continue
        if state.get(L["id"], "yt").get("id") and not force:
            log(f"{L['id']} 이미 업로드됨 — {state.get(L['id'], 'yt')['id']}")
            continue
        todo.append(meta)
    cap = int(max_n or job.get("youtube.max_per_run", 10))
    todo = todo[:cap]
    if not todo:
        log("올릴 강이 없습니다")
        return

    proc = _start_chrome(job)
    port = int(job.get("youtube.cdp_port", 9333))
    try:
        with sync_playwright() as pw:
            br = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = br.contexts[0] if br.contexts else br.new_context()
            page = ctx.new_page()
            st = Studio(job, page, REPO / "logs" / "upload")
            cid = st.channel_id(state)
            for meta in todo:
                lid = meta["lecture"]
                for attempt in (1, 2):
                    try:
                        r = st.upload(cid, meta, dry)
                        break
                    except LimitReached:
                        warn("일일 업로드 한도에 걸렸습니다 — 내일 다시 돌리면 이어서 올립니다")
                        st.shot(f"{lid}-limit")
                        return
                    except Exception as e:
                        st.shot(f"{lid}-error{attempt}")
                        if attempt == 2:
                            raise
                        warn(f"{lid} 업로드 실패({e}) — 한 번 더 시도")
                if dry:
                    continue
                state.lec(lid)["yt"] = {**r, "title": meta["title"], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                state.save()
                ids = read_json(job.out_dir / "youtube_ids.json", {}) or {}
                ids[lid] = {**r, "title": meta["title"]}
                write_json(job.out_dir / "youtube_ids.json", ids)
                statement("uploaded", f"{job.get('pd', job.name)}/theory/{lid}",
                          {"yt_id": r["id"], "visibility": r.get("visibility")})
                log(f"{lid} 업로드 완료 → {r['url']}")
            page.close()
    finally:
        if proc:
            proc.terminate()
