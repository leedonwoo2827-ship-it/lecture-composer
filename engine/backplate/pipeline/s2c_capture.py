# -*- coding: utf-8 -*-
"""S2c 구조 설계 — HTML 참고자료를 **그대로** 슬라이드 구조로.

참고자료가 이미 장별로 정리된 HTML(이론 요약 같은 것)이면, "몇 장으로 나눌까"
를 AI 가 판단할 필요가 없다 — 제목 경계가 이미 그 판단이다. 그래서 HTML 참고
자료가 있으면 이 문으로 들어와 S0a(설문)·S0(기획서)·S2b(AI 구조설계)를 전부
건너뛰고 **바로 목차가 확정된 상태**로 간다.

    참고자료의 HTML 문서 하나당: 표지 1장 + 항목마다 1장 + 마무리 1장
    문서가 여럿이면 순서대로 이어 붙인다.

── 두 가지 방식 ────────────────────────────────────────────────────────
`html`(기본) — `tools/split_sections.mjs` 가 그 구간의 **HTML 을 오려 온다.**
    납작한 그림이 아니라 살아 있는 글이라, 줄 하나씩 시간에 맞춰 나타나게 할 수
    있고 나중에 그 줄을 영상으로 갈아끼울 수도 있다. 글자도 원래 해상도로 다시
    그려져 더 선명하다.
`image` — `tools/capture_sections.mjs` 가 **화면을 찍어 PNG** 로 만든다. 2026-08-14
    까지 쓰던 방식. 원고가 오려 내기 어려운 꼴이면(본문이 제목보다 깊이 들어가
    있다든지) 이쪽으로 되돌릴 수 있게 남겨 둔다. `showcase.config.json` 의
    `capture.mode` 또는 프로젝트의 `capture_mode` 로 고른다.

결과는 s2b-outline 캐시를 **직접 쓴다**(오버라이드가 아니다) — 뒤 단계
(문구·대본)가 그 캐시를 읽으므로, 여기서 확정해야 곧바로 이어진다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config, htmldoc, workspace as ws
from pipeline.registry import STAGES, read_cache, write_cache

# ★ **원고에서만 나올 수 있는 칸.** 이 목록이 유일한 출처다.
#
#   이걸 한 곳에 모은 이유 — 목차(s2b) 캐시를 쓰는 자리가 셋이고, 그중 둘이
#   차례로 이 칸들을 날렸다(2026-08-17, 같은 버그를 세 번 고쳤다):
#     1. 원고 구조 읽기        여기. 원고를 읽어 심는다
#     2. 구조 설계(s2b)        Claude 가 다시 짠다 — 덮으면서 잃었다
#     3. 「이 목차로 확정」     화면에서 온 목록으로 다시 쓴다 — 화면은 이 칸을
#                              안 들고 있어서 통째로 사라졌다
#   그래서 원고 5,620자가 대본 2,095자(6.2분)로 줄었다. 세 자리 다 아래
#   `manuscript_map()` 으로 되살린다.
KEEP_FIELDS = ("say", "read", "img", "data_id", "html_file", "html_sec",
               "html_blocks", "html_text", "html_chars", "html_tags",
               "html_at", "html_at_default")


def manuscript_map(pid: int, slug: str) -> Dict[str, Dict[str, Any]]:
    """장 번호(문자열) → 원고가 실어 온 칸들.

    ★ **원고 쪽(`s2c-capture`)이 먼저다.** 그 캐시는 목차를 쓰는 어느 자리도
      건드리지 않으므로, 목차가 몇 번 덮여도 원본이 남아 있다. 옛 목차 캐시는
      보조로만 본다 — 손으로 끼운 장처럼 원고에 없는 것이 거기 있을 수 있다.
    """
    out: Dict[str, Dict[str, Any]] = {}
    prev = ((read_cache(pid, slug, "s2b-outline") or {}).get("data") or {})
    for s in (prev.get("slides") or []):
        out[str(s.get("no"))] = {k: s[k] for k in KEEP_FIELDS if k in s}
    src = ((read_cache(pid, slug, "s2c-capture") or {}).get("data") or {})
    for s in (src.get("from_manuscript") or []):
        k = str(s.get("no"))
        out[k] = {**out.get(k, {}),
                  **{a: b for a, b in s.items()
                     if a in KEEP_FIELDS and b not in ("", None, [])}}
    return out


def restore(slide: Dict[str, Any], src: Optional[Dict[str, Any]]) -> int:
    """빈 칸만 되살린다. 되살린 개수(`say` 만 센다)."""
    if not src:
        return 0
    got = 0
    for k in KEEP_FIELDS:
        if not str(slide.get(k) or "").strip() and str(src.get(k) or "").strip():
            slide[k] = src[k]
            if k == "say":
                got = 1
    return got

APP = Path(__file__).resolve().parent.parent
CAPTURE_SCRIPT = APP / "tools" / "capture_sections.mjs"
SPLIT_SCRIPT = APP / "tools" / "split_sections.mjs"


def _mode(project: Dict[str, Any]) -> str:
    """`html`(기본) 또는 `image`. 프로젝트가 설정보다 세다."""
    cfg = (config.load().get("capture") or {}).get("mode")
    m = str(project.get("capture_mode") or cfg or "html").lower()
    return m if m in ("html", "image") else "html"


def _node(job, cmd: List[str], what: str, *, timeout: int = 180) -> None:
    proc = subprocess.run(cmd, cwd=str(APP), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            job.add_log("  " + line[:160])
    if proc.returncode != 0:
        for line in (proc.stderr or "").splitlines()[-6:]:
            if line.strip():
                job.add_log("  " + line[:200])
        raise RuntimeError(f"{what} 실패")


def _split(job, node: str, pid: int, slug: str, root: Path, i: int,
           src: Path, item: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """원고를 항목별로 나눈 HTML 한 장을 만들고, 그 파일의 프로젝트 상대 경로를 준다.

    ★ **이미 나뉜 원고는 다시 나누지 않는다.** 사람이 `_new-context/1과목2.html`
      처럼 이미 나눠 둔 것을 그대로 넣는 흐름이 있다(그 파일은 브라우저로 열어
      눈으로 확인한 바로 그 파일이다). 다시 나누면 그 파일의 `<section>` 들이
      본문으로 오인돼 빈 장이 잔뜩 생긴다. 안에 `#manifest` 가 있으면 나뉜
      원고라는 뜻이므로 손대지 않고 그대로 쓴다.
    """
    label = item.get("label") or src.stem
    man = htmldoc.manifest(src)
    if man:
        job.add_log(f"  {label} — 이미 나뉜 원고({len(man.get('slides') or [])}장), 그대로 씁니다")
        return man, item["file"]

    out_dir = ws.cache_dir(pid, slug) / "_split" / str(i)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}2.html"
    _node(job, [node, str(SPLIT_SCRIPT), str(src), "--out", str(out)],
          f"{label} 나누기")
    man = htmldoc.manifest(out)
    if not man:
        raise RuntimeError(f"{label} — 나눈 결과에서 장 목록을 못 읽었습니다")

    # 참고자료 자리에 앉힌다 — 렌더러가 여기서 조각을 오려 온다
    d = ws.sub_dir(pid, slug, "prd", "참고")
    name = f"{ws.nfc(src.stem)}2.html"
    (d / name).write_bytes(out.read_bytes())
    return man, f"{ws.STEPS['prd'][0]}/참고/{name}"


def _capture(job, node: str, pid: int, slug: str, i: int, src: Path,
             label: str) -> Tuple[Dict[str, Any], Path]:
    """예전 방식 — 화면을 찍어 PNG 로. `capture.mode: "image"` 일 때만 온다."""
    out_dir = ws.cache_dir(pid, slug) / "_capture" / str(i)
    _node(job, [node, str(CAPTURE_SCRIPT), str(src), "--out", str(out_dir)],
          f"{label} 캡처", timeout=120)
    man = ws.read_json(out_dir / "manifest.json", None)
    if not man:
        raise RuntimeError(f"{label} manifest 를 못 읽었습니다")
    return man, out_dir


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s2c-capture"]
    root = ws.project_dir(pid, slug)
    refs = (project.get("refs") or {}).get("items") or []
    html_items = [r for r in refs if r.get("kind") == "html"]
    if not html_items:
        raise RuntimeError("HTML 참고자료가 없습니다")

    node = shutil.which("node")
    if not node:
        raise RuntimeError("node 를 찾지 못했습니다 — Node.js 설치를 확인하세요")

    mode = _mode(project)
    job.add_log(f"방식: {'HTML 그대로 오려 오기' if mode == 'html' else '화면 캡처(PNG)'}")

    slides: List[Dict[str, Any]] = []
    images: List[Tuple[int, Path]] = []
    mans: List[Dict[str, Any]] = []      # 원고마다의 장 목록 — 제목을 여기서 꺼낸다
    no = 1
    job.progress(0, len(html_items), "구조 읽기")
    for i, item in enumerate(html_items, 1):
        src = root / item["file"]
        if not src.is_file():
            job.add_log(f"  건너뜀 — 파일 없음: {src}")
            continue
        label = item.get("label") or src.stem

        if mode == "html":
            manifest, doc_rel = _split(job, node, pid, slug, root, i, src, item)
        else:
            manifest, out_dir = _capture(job, node, pid, slug, i, src, label)
            doc_rel = None

        mans.append(manifest)
        for s in manifest["slides"]:
            # manifest 의 `section` 은 항목 갈래일 뿐 — 덱의 장 종류(SLIDE_KINDS)에는
            # 없는 이름이다. 표지·마무리만 그대로 두고 나머지는 `note` 로 앉힌다.
            k = s.get("kind") or "note"
            slide: Dict[str, Any] = {
                "no": no, "section": label,
                "kind": k if k in ("cover", "closing") else "note",
                "title": s["title"], "note": "",
                "media_kind": s.get("media_kind", "text"), "video_id": None,
                "evidence_hint": "", "body": "", "narration": {},
                # 원고가 준 이름표 셋(`tools/split_sections.mjs` 가 `#manifest` 에 실어 준다).
                # 원고에 없으면 빈 문자열 — 문제집 원고에는 셋 다 없다.
                #   data_id  그림 원장이 프롬프트를 매다는 키. 번호가 아니라 이것이다
                #   say      그 장에서 말할 문장
                #   img      그 장 그림의 영어 지시문 (s3a 가 있으면 Claude 를 안 부른다)
                #   read     소리 나는 대로 적은 발음 대본. 숫자·약어가 이미 풀려
                #            있다(`1929년` → `천구백이십구 년`). 있으면 이것이
                #            그대로 TTS 입력이 되고 `say` 는 자막으로 남는다 —
                #            **사람이 단추를 눌러서 만드는 것이 아니라 처음부터
                #            이렇게 나와야 한다**(2026-08-17).
                "data_id": s.get("data_id") or "",
                "say": s.get("say") or "",
                "img": s.get("img") or "",
                "read": s.get("read") or "",
            }
            if slide["media_kind"] == "html" and doc_rel:
                blocks = s.get("blocks") or []
                # ★ 조각 HTML 자체는 여기 담지 않는다. 원고 파일이 원본이고 슬라이드는
                #   거기를 가리킬 뿐이다 — 조각을 목차 캐시에 복사해 넣으면 원고를
                #   고쳤을 때 두 벌이 어긋난다. 조각은 조립(s8)이 그때 읽어 온다.
                slide["html_file"] = doc_rel
                slide["html_sec"] = s.get("sec")
                slide["html_blocks"] = len(blocks)
                # 수정 화면이 줄마다 보여 줄 미리보기 — HTML 을 파싱하지 않게 미리 뽑아 둔다
                slide["html_text"] = [b.get("text") or "" for b in blocks]
                # 줄 길이 — 조립(s8)이 음성 길이를 알게 된 뒤 시각을 다시 나눌 때 쓴다.
                # `html_text` 는 80자에서 잘린 미리보기라 길이를 재는 데 못 쓴다.
                slide["html_chars"] = [int(b.get("chars") or 0) for b in blocks]
                # 줄 종류 — 그림 줄(`svg`)은 글자 수로 시간을 잡으면 안 된다.
                # 이 원고의 SVG 는 라벨이 많아 글자 수가 **글줄보다 많고**(중앙값 81자
                # 대 34자), 비례로 나누면 그림 하나가 그 장 시간의 40% 를 가져간다.
                # `core/htmldoc.auto_ats()` 가 이 값을 보고 그림만 고정 시간으로 뺀다.
                slide["html_tags"] = [str(b.get("tag") or "") for b in blocks]
                # 자동 배분값. 사람이 고친 값(overrides.html_at)이 이것을 이긴다.
                slide["html_at_default"] = [float(b.get("at") or 0) for b in blocks]
                if s.get("q"):
                    slide["evidence_hint"] = f"문항 {s['q']}회"
            if s.get("image"):
                images.append((no, out_dir / s["image"]))
            slides.append(slide)
            no += 1
        job.progress(i, len(html_items), f"{label} 완료")

    if not slides:
        raise RuntimeError("씬을 하나도 못 만들었습니다")

    # ── 목차(s2b-outline 캐시)를 직접 확정한다 ──────────────────────────────
    secs_by_id: Dict[str, Dict[str, Any]] = {}
    for s in slides:
        lb = s["section"]
        if lb and lb not in secs_by_id:
            secs_by_id[lb] = {"id": lb, "title": lb, "kind": "text", "summary": ""}
    for sec in secs_by_id.values():
        sec["slide_nos"] = [s["no"] for s in slides if s["section"] == sec["id"]]

    # ★ **제목은 원고가 안다.** 프로젝트 제목은 드래그드랍한 파일 이름에서 오므로
    #   `19_원고` 같은 것이 그대로 완성본·유튜브 글에 나간다(2026-08-15).
    #   원고의 `h1`(제목)과 그 아래 `<p>`(책 이름)를 쓰고, 없을 때만 파일 이름으로
    #   내려간다. 사람이 목차 화면에서 고친 제목이 있으면 그것이 가장 세다.
    man_title = ""
    man_sub = ""
    for m in mans:
        man_title = man_title or str(m.get("deck_title") or "").strip()
        man_sub = man_sub or str(m.get("deck_subtitle") or "").strip()
    cur = str(project.get("title") or "").strip()
    # 파일 이름 티가 나는 제목(참고자료 이름과 같거나 `_원고` 꼴)은 원고 것으로 바꾼다
    stems = {ws.nfc(Path(r["file"]).stem) for r in html_items}
    looks_file = (not cur) or cur == slug or ws.nfc(cur) in stems or cur.endswith("_원고")
    deck_title = (man_title if (looks_file and man_title) else cur) or slug

    outline_data = {
        "deck_title": deck_title, "deck_subtitle": man_sub,
        "sections": list(secs_by_id.values()), "slides": slides,
        "budget": len(slides), "dropped": [],
    }
    write_cache(pid, slug, "s2b-outline",
               input_hash="capture:" + stage.input_hash(pid, slug, project),
               data=outline_data, code_version=STAGES["s2b-outline"].code_version,
               model=f"({'원고' if mode == 'html' else '캡처'})",
               cost_usd=0.0, status="ok", warnings=[])

    # ── 캡처 이미지를 그 장의 참고자료 자리에 앉힌다 (image 방식일 때만) ────
    if images:
        d = ws.sub_dir(pid, slug, "prd", "참고")
        ov = ws.load_overrides(pid, slug)
        for no_, img_path in images:
            raw = img_path.read_bytes()
            name = f"{no_:03d}.png"
            (d / name).write_bytes(raw)
            rel = f"{ws.STEPS['prd'][0]}/참고/{name}"
            cur = ov.setdefault("slides", {}).setdefault(str(no_), {})
            cur["images"] = [rel]
            cur["image"] = rel
        ws.save_overrides(pid, slug, ov)

    # ── 목차 확정 표시 — 화면이 "설문/기획서"가 아니라 "목차 확정됨"으로 본다
    doc = ws.load_project(pid, slug)
    # 파일 이름이 제목 자리에 앉아 있었으면 원고 것으로 바꿔 준다 — 완성본·유튜브
    # 글·썸네일 원고가 전부 이 값을 쓴다.
    if looks_file and man_title:
        doc["title"] = deck_title
        if man_sub:
            doc["book"] = man_sub
        job.add_log(f"제목을 원고에서 가져왔습니다 — {deck_title}"
                    + (f" ({man_sub})" if man_sub else ""))
    doc["outline_confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    doc["slide_budget"] = len(slides)
    doc["overrides_rev"] = int(doc.get("overrides_rev") or 0) + 1
    ws.save_project(pid, slug, doc)

    n_html = sum(1 for s in slides if s["media_kind"] == "html")
    n_line = sum(int(s.get("html_blocks") or 0) for s in slides)
    extra = f" · 원고 장 {n_html}개(줄 {n_line}개)" if n_html else ""
    job.add_log(f"씬 확정 — {len(slides)}장 (문서 {len(html_items)}개){extra}"
                " · 문구·대본을 채우면 됩니다")

    # ★ **여기서 길이를 말한다.** 원고의 `data-say` 가 그대로 내레이션이 되는데,
    #   예전에는 그림·음성·영상을 다 만들고 **음성을 구운 뒤에야** 짧은 것을
    #   알았다(2026-08-17: 20장이 6분으로 나와 되돌렸다). 원고를 넣는 이 순간이
    #   가장 싸게 되돌릴 수 있는 자리다.
    # ★ 초당 5.5자 — 실측값이다(voicewright F2 초당 5.47자, 19장 22.8분으로 확인).
    #   앱 기본 추정값 3.0 은 첫 판에서 길이를 절반쯤으로 보이게 한다. 음성을 한 번
    #   구우면 보정되지만(`s10_tts._calibrate`) 그 전에는 알 수 없으니 여기서는
    #   실측값을 쓴다.
    say_ch = sum(len(re.sub(r"\s", "", s.get("say") or "")) for s in slides)
    n_say = sum(1 for s in slides if (s.get("say") or "").strip())
    say_min = say_ch / 5.5 / 60
    if say_ch:
        job.add_log(f"원고 대본 {n_say}장 · {say_ch:,}자 → 약 {say_min:.1f}분")
    else:
        job.add_log("★ 원고에 대본(data-say)이 없습니다 — 대본을 새로 지어내게 되고 "
                    "그러면 훨씬 짧아집니다")
    # 목표가 원고 맨 위에 적혀 있으면(`<!-- 20장 · 목표 15~20분 -->`) 그것과 견준다
    want = _target_min(html_items)
    if want and say_ch:
        lo, hi = want
        if say_min < lo:
            warn_len = (f"★ 목표 {lo}~{hi}분인데 지금 원고는 {say_min:.1f}분입니다 — "
                        f"{int((lo * 60 - say_ch / 5.5) * 5.5):,}자쯤 모자랍니다. "
                        "그림·음성으로 가기 전에 원고를 늘리세요")
        elif say_min > hi:
            warn_len = (f"★ 목표 {lo}~{hi}분인데 지금 원고는 {say_min:.1f}분입니다 — "
                        "깁니다")
        else:
            warn_len = f"목표 {lo}~{hi}분 안에 들어옵니다"
        job.add_log(warn_len)

    # ★ **원고가 실어 온 것을 여기 한 벌 남긴다.** 이 단계는 목차(s2b) 캐시를
    #   직접 쓰는데, 나중에 구조 설계를 다시 돌리면 그 자리가 덮인다. 예전에는
    #   구조 설계가 **옛 s2b 캐시**에서 되살렸다 — 그래서 그 사이에 한 번이라도
    #   비면 되살릴 원본이 없어졌다(2026-08-17 실측: 21장 원고 5,620자(17분)가
    #   대본 2,095자(6.2분)가 됐다. 20장도 같은 길이었다).
    #   원고가 원본이다. 여기 남겨 두면 구조 설계를 몇 번 돌려도 되살아난다.
    src = [{k: s[k] for k in ("no",) + KEEP_FIELDS if k in s} for s in slides]

    return write_cache(pid, slug, "s2c-capture",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"slides": len(slides), "docs": len(html_items),
                             "mode": mode, "html_slides": n_html, "lines": n_line,
                             "say_chars": say_ch, "say_min": round(say_min, 1),
                             "from_manuscript": src},
                       code_version=stage.code_version, status="ok", warnings=[])


def _target_min(html_items: List[Dict[str, Any]]) -> Optional[tuple]:
    """원고 맨 위에 적힌 **목표 길이**. 없으면 None.

    받는 꼴 — 주석이든 meta 든, 「목표」 옆에 분이 적혀 있으면 집는다.

        <!-- 20장 · 목표 15~20분 -->
        <meta name="lecture" content="20장 · 목표 15~20분">
        <!-- 목표 18분 -->

    ★ **글자 수는 앱이 직접 센다.** 원고가 알려 줄 수 없는 것은 「몇 분짜리여야
      하는가」뿐이라, 그것만 읽는다. 없으면 길이만 알려 주고 넘어간다 — 목표를
      안 적었다고 막을 일은 아니다 — 없으면 알아서 정하고, 있으면 꼭
      따른다(2026-08-17).
    """
    for it in html_items:
        p = it.get("path")
        if not p:
            continue
        try:
            head = Path(p).read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        m = re.search(r"목표\s*(\d+)\s*(?:~|-|–|에서)\s*(\d+)\s*분", head)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            return (min(lo, hi), max(lo, hi)) if lo != hi else (lo, hi)
        m = re.search(r"목표\s*(\d+)\s*분", head)
        if m:
            n = int(m.group(1))
            return (n, n)
    return None


STAGES["s2c-capture"].run = run
