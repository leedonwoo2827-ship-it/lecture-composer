# -*- coding: utf-8 -*-
"""S8 덱 조립 — 팬아웃한 것을 **번호순으로 다시 모은다.**

    S2b   번호 + 레인 배정          1 · 2 · 3 · … · N
      ↓   레인별로 따로 채움
    S3 캡션 · S3b 그림 · S5 판단 · S6 대본 · S10 음성 · S11 자막
      ↓
    S8   번호로 조인               ← 여기
      ↓
    S9   하나로 렌더링

여기가 **Claude 와 렌더러의 유일한 seam** 이다. 이 파일을 지나면 모든 텍스트는
평문이고, 모든 경로는 실존이 확인됐고, 모든 id 는 ascii 다. 렌더러는 그것만 믿는다.

세 가지를 코드가 보장한다:
  1. 손편집(`deck.overrides.json`)이 **마지막에 이긴다.** 스테이지를 다시 돌려도 산다.
  2. 파일 경로는 **디스크에 있는 것만** 남는다. 없으면 그 자리는 비고 경고가 남는다.
  3. 텍스트에서 마크다운을 걷어낸다 — 렌더러는 escape 만 하지 파싱하지 않는다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from core import config, htmldoc, workspace as ws
from pipeline.registry import ORDER, STAGES, cached_data, read_cache, write_cache
from pipeline.s3a_imgprompt import labels_of

MD = re.compile(r"[*_`#>]|^\s*[-•]\s+", re.M)


def plain(t: Any) -> str:
    return MD.sub("", str(t or "")).strip()


def decision_body(d: Dict[str, Any]) -> str:
    """판단을 발표 문단으로. **트레이드오프를 마지막에 둔다** — 거기가 힘이 세다."""
    paras: List[str] = []
    for k in ("problem", "choice", "rationale", "tradeoff"):
        v = plain(d.get(k))
        if v:
            paras.append(v)
    return "\n\n".join(paras)


def compose(pid: int, slug: str, project: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """캐시에 있는 것으로 덱 하나를 만든다. **미완성이어도 만든다.**

    미리보기(`/preview/{pid}`)와 최종 빌드(S8)가 **같은 함수**를 쓴다. 둘이 갈라지면
    "화면에서 OK 한 것" 과 "산출물" 이 달라지고, 그건 이 툴의 존재 이유를 깬다.
    """
    root = ws.project_dir(pid, slug)

    outline = cached_data(pid, slug, "s2b-outline") or {}
    slides_in = outline.get("slides") or []
    if not slides_in:
        raise RuntimeError("구조 설계(s2b-outline)를 먼저 돌리세요")

    # 원고 장의 몸통을 그림 한 판으로 갈아끼울까. **기본은 꺼짐** — 켜기 전까지
    # 지금까지 나온 덱과 한 글자도 다르지 않게 돈다. 프로젝트가 설정보다 세고,
    # 장별 손편집(`overrides.slides.N.image_swap`)이 그보다 더 세다(아래 병합).
    _cfg_swap = bool((config.load().get("image") or {}).get("swap"))
    swap_on = bool(project.get("image_swap", _cfg_swap))

    caps = (cached_data(pid, slug, "s3-caption") or {}).get("items", {})
    imgs = (cached_data(pid, slug, "s3b-images") or {}).get("images", {})
    # ★ 그림 원장 — 11판 라벨(문구·설명줄·자리)이 여기 산다. 캐시가 아니라
    #   원장을 읽는 이유: 라벨은 그림과 함께 살아 있는 값이고, 사람이 장을
    #   다시 뽑아도 되살아나야 한다.
    _led = (ws.load_ledger(pid, slug) or {}).get("by_id", {})
    dec = (cached_data(pid, slug, "s5-decisions") or {}).get("slides", {})
    copy = (cached_data(pid, slug, "s7-copy") or {}).get("slides", {})
    script = (cached_data(pid, slug, "s6-script") or {}).get("slides", {})
    audio = (cached_data(pid, slug, "s10-tts") or {}).get("slides", {})
    tl = (cached_data(pid, slug, "s11-audio") or {}).get("slides", {})
    frames = (cached_data(pid, slug, "s1-frames") or {}).get("items", {})
    repo = cached_data(pid, slug, "s2-repo") or {}
    ov = ws.load_overrides(pid, slug).get("slides", {})
    # 원고 문서별 스타일 — 장마다가 아니라 **문서당 한 벌**만 모은다(아래 deck 에 실림)
    styles: Dict[str, str] = {}

    warn: List[str] = []

    def keep(rel: str | None) -> str:
        """디스크에 있는 것만 남긴다. 없는 경로가 산출물에 실리면 안 된다."""
        if not rel:
            return ""
        if (root / rel).is_file():
            return rel
        warn.append(f"파일 없음 → 비움: {rel}")
        return ""

    titles = {it["id"]: it.get("title") for it in project.get("items", [])}
    out: List[Dict[str, Any]] = []

    for sl in slides_in:
        no = sl["no"]
        key = str(no)
        # ★ 뺀 장은 여기서 사라진다. 구조(S2b)는 그대로 두고 **손편집으로만** 뺀다 —
        #   구조를 다시 돌리면 되살아나야 하는 게 아니라, 뺀 것이 계속 빠져 있어야
        #   한다. 그래서 오버라이드에 표시하고 조립에서 거른다.
        if (ov.get(key) or {}).get("drop"):
            continue
        d = dec.get(key) or {}
        sc = script.get(key) or {}
        au = audio.get(key) or {}
        tm = tl.get(key) or {}

        # 문구 — S7(문체)이 있으면 그것이 화면에 나간다.
        #   S7 은 구조를 안 건드리고 제목·본문만 다시 쓴 것이라 여기서 그냥 얹으면 된다.
        #   없으면 S5 판단 → S2b 뼈대 순으로 내려간다.
        cp = copy.get(key) or {}
        title = plain(cp.get("title")) or plain(sl.get("title"))
        body = plain(cp.get("body")) or decision_body(d) or plain(sl.get("note"))

        # 근거 — 검증된 것만 (S5 가 실존 확인을 끝냈다)
        ev: List[str] = [str(e.get("ref")) for e in (d.get("evidence") or []) if e.get("ref")]
        if not ev and sl.get("evidence_hint"):
            ev = [e.strip() for e in str(sl["evidence_hint"]).replace(",", "\n").split("\n")
                  if e.strip()]

        s: Dict[str, Any] = {
            "no": no, "section": sl.get("section"), "kind": sl.get("kind"),
            "media_kind": sl.get("media_kind"), "title": title,
            # 원고가 준 이름표 — 그림 원장이 이것으로 프롬프트를 찾는다(S3a·S3b).
            # 번호는 아래에서 1..N 으로 다시 매겨지지만 이것은 안 바뀐다.
            "data_id": sl.get("data_id") or "", "say": sl.get("say") or "",
            "body": body, "evidence": ev[:6],
            "video_id": sl.get("video_id"), "frames": [], "image": "",
            # ★ 11판(배경판)에서 화면이 그릴 라벨. 10판은 글자가 그림 안에
            #   있으므로 빈 목록이다 — 옛 프로젝트는 아무것도 안 바뀐다.
            "labels": [],
            # 무음 영상 편집 — 구간·배속·삭제. 사람이 편집 화면에서 정하고
            # 오버라이드로 들어온다. 재인코딩하지 않고 재생기가 따른다.
            "clip": None,
            "narration": {"srt_text": sc.get("srt_text") or "",
                          "text": sc.get("narration_text") or "",
                          "est_sec": sc.get("narration_seconds") or 0,
                          "over_sec": sc.get("over_sec") or 0},
            "audio": {"file": keep(au.get("file")), "source": au.get("source") or "none",
                      "sec": au.get("duration_sec") or 0},
            "srt": keep(tm.get("srt")),
            "start_sec": tm.get("start_sec", 0),
        }

        vid = sl.get("video_id")
        if vid:
            s["video_title"] = titles.get(vid)
            s["video_duration"] = (frames.get(vid) or {}).get("duration_sec")
            fmap = {f["id"]: f for f in (frames.get(vid) or {}).get("frames") or []}
            cmap = {c["id"]: c for c in (caps.get(vid) or {}).get("frames") or []}
            for fid in (caps.get(vid) or {}).get("picked") or []:
                f = fmap.get(fid)
                if not f:
                    continue
                s["frames"].append({"id": fid, "t_sec": f["t_sec"],
                                    "file": keep(f["file"]),
                                    "caption": plain((cmap.get(fid) or {}).get("caption"))})
        if sl.get("media_kind") == "html":
            # ★ 조각 HTML 은 **여기서 읽어 실어 보낸다.** 렌더러(render/slides.py)는
            #   파일을 못 읽는다 — 자원 해석기(res)가 주는 것은 URL 이지 내용이
            #   아니다. 그리고 `dist/` 는 파일 한 장으로 나가야 해서 나중에 불러올
            #   수도 없다. 그래서 조립 시점에 글자를 통째로 담는다.
            rel = sl.get("html_file")
            p = htmldoc.find_doc(root, rel)
            s["html_file"] = rel or ""
            s["html_sec"] = sl.get("html_sec")
            s["html_blocks"] = int(sl.get("html_blocks") or 0)
            s["html_text"] = list(sl.get("html_text") or [])
            s["html_at_default"] = [float(x) for x in (sl.get("html_at_default") or [])]
            s["html"] = htmldoc.section(p, int(sl.get("html_sec") or 0)) if p else ""
            s["html_chars"] = [int(x) for x in (sl.get("html_chars") or [])]
            # 줄 종류 — `htmldoc.resolve()` 가 그림 줄만 고정 시간으로 뺄 때 본다
            s["html_tags"] = [str(x) for x in (sl.get("html_tags") or [])]
            if p:
                # 원본 문서 스타일 — 덱 전체에 **한 번만** 넣는다(아래 deck 조립).
                styles.setdefault(str(rel), htmldoc.style(p))
            elif rel:
                warn.append(f"{no}번 장: 원고를 못 찾음 — {rel}")

        if sl.get("media_kind") in ("text_image", "thumb", "html"):
            # ★ 한 장에 여러 그림. `image` 는 첫 장(예전 화면 호환), `images` 가 전부다.
            # ★ `html` 장에도 붙인다. 붙이기만 하고 **쓸지 말지는 렌더러가 정한다**
            #   (`image_swap`). 여기서 거르면 그림이 와 있는지조차 화면에서 알 수 없다.
            got = imgs.get(key) or {}
            shots = [keep(x.get("file")) for x in (got.get("shots") or [])]
            shots = [x for x in shots if x]
            if not shots and got.get("file"):
                one = keep(got["file"])
                shots = [one] if one else []
            s["images"] = shots
            s["image"] = shots[0] if shots else ""
            # ★ 라벨은 **그림과 한 몸**이다. 그림이 비워 둔 자리에 얹히므로
            #   그림을 붙이는 이 자리에서 같이 붙인다.
            # ★ 원장은 **이름표(data_id)가 키다** — 번호가 아니다. 번호는 앞에
            #   장 하나만 끼어들어도 전부 밀리지만 이름표는 안 밀린다
            #   (core/workspace.py 의 ledger_path 주석 참고).
            s["labels"] = labels_of(_led.get(sl.get("data_id") or "") or {})
            if sl.get("media_kind") == "html":
                # ★ **의도와 결과를 가른다.** `image_swap` 은 "이 장은 그림으로
                #   갈 장이다" 라는 **작정**이고, 그림이 아직 안 왔어도 참이다.
                #   실제로 갈아끼우는 것은 렌더러가 정한다(그림이 있을 때만).
                #   둘을 한 값으로 합쳐 두면 「그림 기다리는 장」이 화면 어디에도
                #   안 보인다 — 그림이 와야 비로소 유형이 생기니까. 수정 유형을
                #   처음부터 갈라 두어야 한다(2026-08-14).
                s["image_swap"] = bool(swap_on)

        # ★ 손편집이 마지막에 이긴다
        for k, v in (ov.get(key) or {}).items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k] = {**s[k], **v}
            else:
                s[k] = v

        # 줄이 몇 초에 뜨는가 — **손편집이 들어온 뒤에** 확정한다(`html_at` 이
        # 오버라이드로 오므로). 재생기도 수정 화면도 이 값 하나만 본다.
        htmldoc.resolve(s)

        out.append(s)

    # ★ 뺀 장이 있으면 번호가 비므로 **1부터 다시 매긴다.** 발표에서 "3번 다음이
    #   5번" 은 이상하다. 원래 번호(`src_no`)는 남겨 둔다 — 손편집 키가 그것이고,
    #   편집 화면에서도 그 번호로 찾는다.
    for i, s in enumerate(out, 1):
        s["src_no"] = s["no"]
        s["no"] = i

    dropped = [int(k) for k, v in ov.items() if (v or {}).get("drop")]
    if dropped:
        warn.append(f"뺀 장 {len(dropped)}개: {sorted(dropped)}")

    total = round(sum(float((tl.get(str(s["src_no"])) or {}).get("duration_sec") or 0)
                      for s in out), 1)
    n_audio = sum(1 for s in out if s["audio"]["file"])
    n_script = sum(1 for s in out if s["narration"]["srt_text"])
    n_media = sum(1 for s in out if s["frames"] or s["image"] or s["video_id"])
    over = [s["no"] for s in out if (s["narration"].get("over_sec") or 0) > 0.5]

    if n_script < len(out):
        warn.append(f"대본이 없는 장 {len(out) - n_script}개")
    if over:
        warn.append(f"영상보다 대본이 긴 장: {over}")

    deck = {
        "schema_version": 1,
        "project": {
            "slug": slug, "title": outline.get("deck_title") or project.get("title"),
            "subtitle": outline.get("deck_subtitle") or "",
            "live_url": project.get("live_url") or "",
            "language": project.get("language") or "ko",
            # ★ **그림을 화면에 어떻게 앉힐까**(액자·전면). 렌더러가 이 값으로
            #   `.s-swapfull` 을 붙인다(`render/slides.py`). 이 칸은 **손으로 고른
            #   몇 개만** 담는 자리라, 여기 안 적으면 프로젝트에 값이 있어도 화면까지
            #   못 간다 — 실제로 전면으로 만든 덱이 액자로 떴다(2026-08-29).
            #   값이 없으면 액자다: 옛 프로젝트가 그대로 나와야 한다.
            "image_fit": project.get("image_fit") or "frame",
            "repo": {"name_with_owner": repo.get("name_with_owner") or "",
                     "head_sha": (repo.get("head_sha") or "")[:8],
                     "commit_count": repo.get("commit_count") or 0},
            "stack": repo.get("stack") or [],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "sections": outline.get("sections") or [],
        "slides": out,
        # 원고 문서의 스타일 — **문서당 한 벌**. 장마다 넣으면 4KB 짜리가 장 수만큼
        # 복사돼 `dist/` 한 장 파일이 수백 KB 씩 불어난다.
        "html_style": "\n".join(v for v in styles.values() if v),
        "totals": {"slides": len(out), "sec": total,
                   "audio": n_audio, "script": n_script, "media": n_media},
        "build": {
            "stages": {k: {"status": (read_cache(pid, slug, k) or {}).get("status"),
                           "cost_usd": (read_cache(pid, slug, k) or {}).get("cost_usd", 0.0)}
                       for k in ORDER},
            "total_cost_usd": round(sum((read_cache(pid, slug, k) or {}).get("cost_usd", 0.0)
                                        for k in ORDER), 4),
        },
    }
    return deck, warn


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s8-assemble"]
    deck, warn = compose(pid, slug, project)
    out = deck["slides"]
    t = deck["totals"]
    ws.write_json(ws.deck_path(pid, slug, create=True), deck)

    job.add_log(f"{len(out)}장 조립 · 대본 {t['script']} · 음성 {t['audio']} "
                f"· 미디어 {t['media']} · {t['sec'] / 60:.1f}분")
    for w in warn[:8]:
        job.add_log("  " + w)
    if warn:
        job.add_log(f"경고 {len(warn)}건 — 미완성이어도 렌더는 됩니다")

    return write_cache(pid, slug, "s8-assemble",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"deck_file": str(ws.deck_path(pid, slug)),
                             "totals": t},
                       code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s8-assemble"].run = run
