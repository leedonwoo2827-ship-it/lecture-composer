# -*- coding: utf-8 -*-
"""S9 완성본 렌더 — **마지막 스테이지.**

    11_완성/<slug>/               ★ **이 폴더를 통째로 올린다.** 그게 웹 루트다
              index.html          .../<slug>/ 로 들어가면 이게 열린다
              assets/             음성·영상
              LICENSE-Pretendard.txt
              .nojekyll           GitHub Pages 가 파일을 거르지 않게
    11_완성/<slug>.html            파일 하나. 외부 참조 0. 메일로 보낼 수 있다
    11_완성/cue/                   자막·큐시트 — 영상팀용. 웹에는 안 올린다
    11_완성/<slug>-원고.json       ★ 이 발표를 통째로 되살리는 한 파일
    11_완성/올리는법.txt

압축본은 만들지 않는다. 로컬로 건넬 때 폴더를 우클릭해 묶는 편이 빠르고,
zip 이 옆에 있으면 "무엇을 올리나" 가 매번 헷갈린다.

순서 주의: **여기가 맨 뒤다.** 페이지가 음성을 품으므로 S10·S11 이 먼저 끝나야
하고, 폰트 서브셋은 산문이 확정된 뒤에 돌아야 한다.

단일 파일 빌드는 두 가지를 **단언**한다. 어기면 실패로 남긴다:
  - `src=`/`href=` 에 `http:`/`https:` 가 하나도 없을 것
  - 크기가 `render.max_single_file_mb` 이하일 것

**통합 mp4 를 여기서 만들지 않는다.** 그건 S12 가 맡는다 — 장마다 화면을 찍어
내레이션 길이만큼 이어 붙인다. 이 단계가 만드는 것은 **재생되는 페이지**고,
S12 가 만드는 것은 **파일 하나**다. 둘은 쓰임이 다르므로 둘 다 남긴다.
"""
from __future__ import annotations

import re
import shutil
import sys

from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, manuscript as ms, workspace as ws
from pipeline.registry import STAGES, write_cache
from pipeline.s8_assemble import compose
from render import fonts
from render.resolvers import FolderResolver, SingleFileResolver
from render.slides import render_deck

# 산출물 폴더에 같이 넣는 안내. 여기 말고 다른 데 적어 두면 아무도 안 읽는다.
UPLOAD_HOWTO = """웹에 올리는 법
===============================================================

■ {slug}/ 폴더를 통째로 올리면 끝입니다.

  그 안에 페이지와 음성과 폰트 라이선스가 다 들어 있습니다.
  PHP·Node·DB 아무것도 필요 없습니다. 밖으로 나가는 주소가
  하나도 없어서, 정적 파일만 얹히는 곳이면 어디서든 똑같이 돕니다.

      GitHub Pages   폴더 내용을 레포에 넣고 Settings > Pages
      nginx / VPS    폴더를 두고 root 를 그리로
      카페24 · FTP   폴더를 통째로 업로드
      S3 · Cloudflare  폴더를 끌어다 놓기

  폴더 안의 .nojekyll 은 GitHub 가 파일을 제 방식대로 걸러
  내지 않게 하는 빈 파일입니다. 지우지 마세요.


■ 같이 올리지 않는 것

    {slug}.html   같은 내용의 **파일 한 장** 입니다. 음성까지
                  안에 박혀 있어 메일·USB 로 보내면 그대로
                  열립니다. 웹에 올릴 거라면 필요 없습니다.

    cue/          자막(.srt)과 큐시트입니다. 영상팀에 넘기는
                  것이지 사이트에 필요한 것이 아닙니다.

    {slug}-원고.json
                  목차·화면 문구·대본이 다 든 한 파일입니다.
                  앱의 "JSON 불러오기" 에 넣으면 이 발표가
                  그대로 다시 섭니다. 다음 발표의 뼈대로 쓰거나,
                  밖에서 고쳐 올 때도 이 파일을 씁니다.


■ 로컬로 건넬 때

    {slug}/ 폴더를 우클릭해서 압축하면 됩니다.
    받는 사람은 풀고 index.html 을 더블클릭하면 되는데,
    브라우저에 따라 file:// 에서 폰트가 막히기도 합니다.
    그럴 땐 {slug}.html 한 장을 보내는 편이 확실합니다.


■ 확인

    올린 주소를 열어 첫 장의 ▶ 를 누르고 소리가 나면 된 것입니다.
    소리가 안 나면 assets/ 가 같이 안 올라간 것입니다.
"""
EXTERNAL = re.compile(r'(?:src|href)\s*=\s*["\']https?:', re.I)


def video_lookup(project: Dict[str, Any]):
    """`v1` → 원본 파일 경로. 한글 파일명은 NFC 로 맞춰 찾는다."""
    vdir = project.get("video_dir")
    by_id = {it["id"]: it for it in project.get("items", [])}

    def find(vid: str) -> Optional[Path]:
        it = by_id.get(vid)
        if not it or not vdir:
            return None
        p = Path(vdir) / ws.nfc(it.get("file") or "")
        if p.is_file():
            return p
        # NFD 로 저장된 폴더 대비 — 이름을 정규화해 다시 훑는다
        want = ws.nfc(it.get("file") or "")
        d = Path(vdir)
        if d.is_dir():
            for f in d.iterdir():
                if ws.nfc(f.name) == want:
                    return f
        return None

    return find


def manuscript(pid: int, slug: str, deck: Dict[str, Any]) -> Dict[str, Any]:
    """발표 원고 한 파일. 앱의 JSON 불러오기가 그대로 먹는 모양이다.

    ★ 조립된 덱(`deck`)에서 뽑는다 — 캐시가 아니라. 뺀 장은 이미 빠져 있고
      번호도 1부터 다시 매겨져 있어서, **화면에서 보던 그대로**가 나간다.
    """
    from pipeline.registry import cached_data

    o = cached_data(pid, slug, "s2b-outline") or {}
    slides = []
    for s in deck.get("slides") or []:
        n = s.get("narration") or {}
        slides.append({
            "no": s.get("no"), "section": s.get("section", ""),
            "kind": s.get("kind", "note"), "title": s.get("title", ""),
            "note": s.get("note", ""), "media_kind": s.get("media_kind", "text"),
            "video_id": s.get("video_id"),
            "evidence_hint": s.get("evidence_hint", ""),
            "body": s.get("body", ""),
            "narration": {"srt_text": n.get("srt_text") or "",
                          "text": n.get("text") or n.get("srt_text") or ""},
        })
    # ★ 완성본에도 주석을 붙인다. 이 파일이야말로 **남에게 건네는 것**이라
    #   — 다음 발표의 뼈대로 쓰거나 다른 에이전트에게 넘길 때 — 규격이 같이
    #   가야 한다. 주석은 스물몇 줄이고 불러올 때 무시된다.
    return ms.wrap({
        "deck_title": (deck.get("project") or {}).get("title") or "",
        "deck_subtitle": (deck.get("project") or {}).get("subtitle") or "",
        "sections": [{"id": x.get("id"), "title": x.get("title"),
                      "kind": x.get("kind", "text"), "summary": x.get("summary", "")}
                     for x in (deck.get("sections") or o.get("sections") or [])],
        "slides": slides,
        "dropped": o.get("dropped") or [],
    })


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    cfg = config.load()
    stage = STAGES["s9-render"]
    root = ws.project_dir(pid, slug)

    deck = ws.read_json(ws.deck_path(pid, slug), None)
    if not deck:
        deck, _ = compose(pid, slug, project)
    title = (deck.get("project") or {}).get("title") or slug

    dist = ws.step_dir(pid, slug, "dist")
    warn: List[str] = []
    out: Dict[str, Any] = {}

    # 배경음악 — 프로젝트에 지정돼 있으면 두 벌 모두에 얹는다.
    # ★ 원본은 `07_음성/bgm.*` 에 산다. `assets/` 에 손으로 넣어 두면 아래에서
    #   폴더째 지워진다 — 그래서 반드시 이 길로 들어와야 한다.
    bgm_cfg = project.get("bgm") or {}
    bgm_rel = str(bgm_cfg.get("file") or "")
    if bgm_rel and not (root / bgm_rel).is_file():
        warn.append(f"배경음악 파일이 없습니다: {bgm_rel}")
        bgm_rel = ""
    bgm_kw = {"bgm_vol": float(bgm_cfg.get("volume") or 0.15),
              "bgm_duck": float(bgm_cfg.get("duck") or 0.04)}

    # ── 1) 웹 폴더 ────────────────────────────────────────────────────────
    #
    # ★ **폴더 하나가 곧 웹 루트다.** 예전엔 index.html·assets 를 완성 폴더에
    #   흩뿌리고 zip 을 따로 만들었는데, 그러면 "이 다섯 개 중 무엇을 올리나"
    #   를 매번 물어야 했다. 통째로 올리면 되는 폴더 하나로 만든다.
    #   압축은 안 한다 — 로컬로 건넬 때 사람이 우클릭으로 묶는 게 더 빠르다.
    job.progress(0, 3, "웹 폴더")
    # ★ 그림으로 갈아낀 판은 **이름을 갈라 낸다** — 글 판과 나란히 남아야 둘을
    #   견줄 수 있다. 같은 이름이면 나중에 구운 것이 앞엣것을 덮어쓴다(S12 도 같다).
    name = ws.ascii_slug(slug) + (
        "-img" if any(s.get("image_swap") for s in (deck.get("slides") or [])) else "")
    web = dist / name
    if web.is_dir():
        shutil.rmtree(web, ignore_errors=True)
    web.mkdir(parents=True, exist_ok=True)
    fr = FolderResolver(root, web)
    fr.src_lookup = video_lookup(project)
    html = render_deck(deck, fr, title=title,
                       bgm=fr.bgm(bgm_rel) if bgm_rel else "", **bgm_kw)

    work = ws.cache_dir(pid, slug) / "_fontwork"
    css, notes = fonts.face_css(html, work=work)
    html = fonts.inject(html, css)
    for n in notes:
        job.add_log("  폰트: " + n)
    warn.extend(f"에셋 {n}" for n in fr.notes[:6])

    ws.write_text(web / "index.html", html)
    lic = fonts.license_text()
    if lic:
        ws.write_text(web / "LICENSE-Pretendard.txt", lic)
    # GitHub Pages 는 밑줄로 시작하는 것을 제 방식대로 걸러 낸다 — 미리 끈다
    ws.write_text(web / ".nojekyll", "")
    n_assets = len(list((web / "assets").glob("*"))) if (web / "assets").is_dir() else 0
    size = (web / "index.html").stat().st_size
    out["folder"] = {"dir": web.name, "file": "index.html",
                     "assets": n_assets, "html_bytes": size}
    job.add_log(f"웹 폴더 {web.name}/ · index.html {size // 1024}KB · 에셋 {n_assets}개")

    # ── 2) 단일 파일 ──────────────────────────────────────────────────────
    job.progress(1, 3, "단일 파일")
    tmp = ws.cache_dir(pid, slug) / "_single"
    sr = SingleFileResolver(root, audio_kbps=32, bgm_kbps=64, tmp=tmp)
    one = render_deck(deck, sr, title=title,
                      bgm=sr.bgm(bgm_rel) if bgm_rel else "", **bgm_kw)
    one = fonts.inject(one, css)
    for n in sr.notes[:4]:
        warn.append("단일: " + n)

    single = dist / f"{name}.html"      # 그림 판이면 `-img` 가 붙는다(위 참고)
    ws.write_text(single, one)
    mb = single.stat().st_size / 1e6
    limit = float((cfg.get("render") or {}).get("max_single_file_mb", 10))

    hits = EXTERNAL.findall(one)
    if hits:
        warn.append(f"단일 파일에 외부 참조 {len(hits)}건 — 오프라인에서 깨집니다")
    if mb > limit:
        warn.append(f"단일 파일 {mb:.1f}MB > 한도 {limit}MB")
    out["single"] = {"file": single.name, "mb": round(mb, 2),
                     "external_refs": len(hits), "limit_mb": limit}
    job.add_log(f"단일 파일 · {mb:.1f}MB · 외부참조 {len(hits)}건 "
                f"{'OK' if (not hits and mb <= limit) else '확인 필요'}")
    shutil.rmtree(tmp, ignore_errors=True)

    # ── 3) 인계물 ─────────────────────────────────────────────────────────
    # 자막·큐시트는 **웹 폴더 밖**이다. 영상팀에 넘기는 것이지 사이트에 필요한
    # 것이 아니라, 안에 두면 올릴 때 같이 딸려 올라간다.
    job.progress(2, 3, "인계물")
    cue = dist / "cue"
    shutil.rmtree(cue, ignore_errors=True)
    sub = ws.step_dir(pid, slug, "subtitle", create=False)
    n_cue = 0
    if sub.is_dir():
        cue.mkdir(parents=True, exist_ok=True)
        for f in sorted(sub.iterdir()):
            if f.is_file() and f.suffix in (".srt", ".md", ".csv"):
                shutil.copy2(f, cue / f.name)
                n_cue += 1
    out["cue"] = {"dir": "cue", "files": n_cue}
    job.add_log(f"인계물 cue/ · {n_cue}개 (자막·큐시트 — 웹에는 안 올립니다)")

    # ★ 원고 한 파일 — **이 발표를 통째로 되살릴 수 있는 것.**
    #   목차·화면 문구·대본이 다 들어 있다. 앱의 초안/목차 화면에 그대로 넣으면
    #   같은 발표가 다시 선다. 산출물이 폴더 여기저기 흩어져 있는 것과 달리
    #   이 파일 하나만 챙기면 된다 — 다른 PC 로 옮기거나, 다음 발표의 뼈대로
    #   쓰거나, 밖에서 고쳐 오는 길이 전부 이 파일이다.
    ws.write_json(dist / f"{ws.ascii_slug(slug)}-원고.json",
                  manuscript(pid, slug, deck))

    # 폴더를 열었을 때 무엇을 올리는지가 거기 있어야 한다
    ws.write_text(dist / "올리는법.txt",
                  UPLOAD_HOWTO.format(slug=ws.ascii_slug(slug)))
    old = dist / f"{ws.ascii_slug(slug)}.zip"
    if old.is_file():
        old.unlink()                     # 구조가 바뀌었다 — 옛 zip 은 헷갈린다
    for stray in ("index.html", "LICENSE-Pretendard.txt"):
        f = dist / stray                 # 예전엔 여기 흩어져 있었다
        if f.is_file():
            f.unlink()
    if (dist / "assets").is_dir():
        shutil.rmtree(dist / "assets", ignore_errors=True)

    job.progress(3, 3, "완료")

    t = deck.get("totals") or {}
    job.add_log(f"완성 — {t.get('slides')}장 · {float(t.get('sec') or 0) / 60:.1f}분")
    job.add_log(f"올릴 폴더: {web}")
    job.add_log(f"한 장으로 보낼 것: {single}")

    return write_cache(pid, slug, "s9-render",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"dir": str(dist), **out},
                       code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s9-render"].run = run
