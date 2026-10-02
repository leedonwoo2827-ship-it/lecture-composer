# -*- coding: utf-8 -*-
"""덱 → 슬라이드 HTML. **이 앱의 유일한 HTML 생성기.**

미리보기와 최종 산출물이 같은 함수를 쓴다. 편집 화면에서 iframe 으로 보는 것도
이것이고, `dist/` 로 굽는 것도 이것이다 — 셋이 갈라지면 "OK 한 면" 과 "나가는 면"
이 달라진다.

**미완성 상태에서도 렌더된다.** 음성·자막·그림이 아직 없어도 제목과 본문만으로
면이 나와야 한다. 텍스트 연계가 어울리는지는 실제 면을 봐야 판단된다.

★ PPT 교안처럼 만들지 않는다. 불릿 나열 대신 **한 장에 하나**를 말하고,
  근거(파일 경로 · 커밋 · 수치)가 주인공 자리에 온다.

★ 브라우저 자동재생 정책: 소리 있는 오디오는 사용자 제스처 전에 재생되지 않는다.
  슬라이드를 넘기는 행위가 제스처라 2번째 장부터는 문제없지만 **첫 장은
  `▶ 시작` 이 필요하다.** 그 버튼이 첫 제스처가 되고 이후는 자동으로 흐른다.
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List

# 레인 색 — 브랜드 하나에서 파생한 계조. 범주형 색을 섞지 않는다.
LANE_COLORS = ["#9a4d33", "#c0714f", "#7d6a55", "#5c6b62", "#8a7f9a", "#a8894f"]

KIND_LABEL = {
    "cover": "", "context": "배경", "feature": "기능", "architecture": "구조",
    "decision": "판단", "metric": "수치", "ops": "운영", "note": "", "closing": "",
}


def esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _paras(text: str) -> str:
    """Claude 가 쓴 것은 **평문**이다. 전부 escape 하고 빈 줄만 문단으로 바꾼다."""
    parts = [p.strip() for p in str(text or "").split("\n\n") if p.strip()]
    return "".join(f"<p>{esc(p)}</p>" for p in parts)


def _evidence(s: Dict[str, Any]) -> str:
    ev = s.get("evidence") or []
    if not ev:
        return ""
    lis = "".join(f"<li>{esc(e)}</li>" for e in ev[:6])
    return f'<ul class="ev">{lis}</ul>'


def _media(s: Dict[str, Any], res) -> str:
    kind = s.get("media_kind")
    no = s.get("no")
    frames = [f for f in (s.get("frames") or []) if f.get("file")]

    if kind == "video" and s.get("video_id"):
        src = res.video(s)
        poster = res.asset(frames[0]["file"]) if frames else ""
        if src:
            p = f' poster="{esc(poster)}"' if poster else ""
            cap = (f'<figcaption>{esc(frames[0]["caption"])}</figcaption>'
                   if frames and frames[0].get("caption") else "")
            c = s.get("clip") or {}
            dur = float(s.get("video_duration") or 0)
            # ★ 편집 정보를 **항상** 내보낸다. 예전엔 사람이 자른 장에만 붙였는데,
            #   그러면 안 자른 장은 재생기가 "영상이 없는 장" 으로 보고 음성만
            #   기다렸다 — 영상이 도는 중에 다음 장으로 넘어가던 원인이다.
            #   안 자른 장은 0 ~ 원본 길이가 곧 구간이다.
            attr = (f' data-start="{float(c.get("start") or 0):.2f}"'
                    f' data-end="{float(c.get("end") or dur):.2f}"'
                    f' data-speed="{float(c.get("speed") or 1):.2f}"'
                    f' data-cuts="{esc(json.dumps(c.get("cuts") or []))}"')
            return (f'<figure class="m"><video playsinline preload="metadata" muted'
                    f'{p}{attr} src="{esc(src)}"></video>{cap}</figure>')
        if frames:
            f = frames[0]
            cap = f'<figcaption>{esc(f["caption"])}</figcaption>' if f.get("caption") else ""
            return (f'<figure class="m"><img loading="lazy" src="{esc(res.asset(f["file"]))}"'
                    f' alt=""/>{cap}</figure>')
        return '<div class="m m-todo">영상 대기</div>'

    if kind == "html":
        # ★ 그림으로 **갈아끼운 장**. 몸통(글줄)이 통째로 그림 한 판이 된다 —
        #   제목만 위에 남고, 설명은 내레이션이 한다. 뒤에 까는 배경이 아니다:
        #   글 위에 사진을 깔면 슬레이트 글자가 안 읽히고, 반투명 막을 씌우면
        #   그림이 뿌예진다. 둘 다 하지 않고 **자리를 바꾼다.**
        #   ★ 줄이 하나씩 떠오르는 것은 이 장에서 사라진다(줄이 없으니까).
        #     장 길이·전환·음성·자막은 그대로다 — 그래서 켜고 끄기가 안전하다.
        shots = [x for x in (s.get("images") or []) if x]
        if s.get("image_swap") and shots:
            src = res.asset(shots[0])
            if src:
                # ★ `loading="eager"` 다. 이 그림은 **곧 슬라이드 전체**라, 미뤘다가
                #   장이 뜰 때 아직 안 와 있으면 빈 화면이 그대로 영상에 구워진다
                #   (2026-08-14 실측: 화면이 1920×1080 로 잡혔는데 naturalWidth 가
                #   0 이었다). 글 옆에 붙는 그림과 달리 늦어도 되는 그림이 아니다.
                # ★ 11판이면 그림이 비워 둔 자리에 **진짜 글자**를 얹는다.
                #   10판은 글이 그림 안에 있으므로 `labels` 가 비어 있고,
                #   아래 한 줄은 빈 문자열이 되어 화면이 예전과 똑같다.
                return (f'<figure class="m m-shots m-html m-swap" data-n="0"'
                        f' data-at="[]"><img loading="eager" decoding="sync"'
                        f' src="{esc(src)}" alt=""/>{_labels_html(s)}</figure>')
        # ★ 조각은 이미 조립(s8)이 읽어 넣어 두었다 — 여기서 파일을 열지 않는다.
        #   렌더러는 `res` 가 주는 URL 밖에 못 보고, `dist/` 는 파일 한 장으로
        #   나가야 해서 나중에 불러올 수도 없다.
        frag = (s.get("html") or "").strip()
        if not frag:
            return f'<div class="m m-todo">원고 대기 — {int(no):03d}</div>'
        # 줄이 몇 초에 뜨는가. 조각 안 글자를 다시 쓰지 않고 **한 뭉치**로 넘긴다 —
        # 줄마다 심으려면 파이썬이 HTML 을 파싱해야 하는데, 그 순간 이 파일이
        # 렌더러가 아니라 파서가 된다. 순서(배열 자리)가 곧 줄 번호다.
        ats = [float(x) for x in (s.get("html_times") or [])]
        return (f'<figure class="m m-shots m-html" data-n="{len(ats)}"'
                f' data-at="{esc(json.dumps(ats))}">'
                f'<div class="doc">{frag}</div></figure>')

    if kind in ("text_image", "thumb"):
        shots = [x for x in (s.get("images") or ([s["image"]] if s.get("image") else [])) if x]
        if shots:
            # ★ 여러 장이면 대본 시간을 나눠 차례로 넘어간다 —
            #   멘토링처럼 신청 화면과 수락 화면이 따로 있는 메뉴가 있다.
            imgs = "".join(
                f'<img loading="lazy" src="{esc(res.asset(x))}" alt=""'
                f'{" class=on" if i == 0 else ""}/>' for i, x in enumerate(shots))
            dots = ("".join("<i></i>" for _ in shots)) if len(shots) > 1 else ""
            # ★ `m-pic` — **그림만 있는 칸.** `.m-shots` 는 16:10 상자를 고정하는데
            #   (`padding-top:62.5%`) 그림은 3:2 라 안에 들어가면서 좌우에 흰 여백이
            #   남는다(2026-08-17: "하얀 라인이 안 보이게 꽉 차게"). 원고 HTML 장은
            #   그 상자가 있어야 줄 뜨는 자리가 흔들리지 않으므로, 그림만 있는 칸에만
            #   상자를 풀고 **그림 제 비율대로** 놓는다. 자르지 않는다 — 그림 위에
            #   헤드라인이 인쇄돼 있어 자르면 제목이 날아간다.
            return (f'<figure class="m m-shots m-pic" data-n="{len(shots)}">{imgs}'
                    f'{f"<span class=sdots>{dots}</span>" if dots else ""}</figure>')
        return f'<div class="m m-todo">그림 대기 — {int(no):03d}.png</div>'

    if frames:
        f = frames[0]
        cap = f'<figcaption>{esc(f["caption"])}</figcaption>' if f.get("caption") else ""
        return (f'<figure class="m"><img loading="lazy" src="{esc(res.asset(f["file"]))}"'
                f' alt=""/>{cap}</figure>')
    return ""      # code 장은 근거 목록이 코드 자리를 대신한다


def _audio(s: Dict[str, Any], res) -> str:
    """장별 내레이션. `data-no` 로 JS 가 찾아 재생한다."""
    f = (s.get("audio") or {}).get("file")
    if not f:
        return ""
    return (f'<audio class="na" preload="none" data-no="{s.get("no")}"'
            f' src="{esc(res.asset(f))}"></audio>')


def _slide(s: Dict[str, Any], lane_i: int, total: int, res) -> str:
    no = s.get("no")
    kind = s.get("kind") or "note"
    color = LANE_COLORS[lane_i % len(LANE_COLORS)]
    label = KIND_LABEL.get(kind, "")
    au = _audio(s, res)
    media = _media(s, res)

    # ★ 표지도 **그림 자리가 있으면 맨 끝 장과 똑같이** 찍는다.
    #   예전에는 `kind == "cover"` 를 무조건 글자 판으로 일찍 돌려보냈다. 그래서
    #   삽입 이미지 화면에서 `001.png` 를 붙여도 판에는 영영 안 나왔고, 그림이
    #   저장이 안 된 것처럼 보였다(2026-08-16: "맨 앞은 왜 이미지가 안 바뀌나요").
    #   붙은 것과 보이는 것이 갈리면 사람은 저장을 의심한다 — 갈리지 않게 한다.
    #   그림 자리가 없는 표지는 그대로 글자 판이다(그때 `_media` 가 빈 문자열이다).
    if kind == "cover" and not media:
        p = s.get("_project") or {}
        meta = " · ".join(x for x in [p.get("repo", {}).get("name_with_owner"),
                                      " / ".join((p.get("stack") or [])[:3])] if x)
        return (
            f'<section class="s s-cover" data-no="{no}" data-src="{s.get("src_no") or no}"'
            f' style="--lane:{color}">'
            f'<div class="wrap">'
            f'<h1>{esc(s.get("title"))}</h1>'
            f'{_paras(s.get("body"))}'
            f'{f"<p class=meta>{esc(meta)}</p>" if meta else ""}'
            f'</div>{au}</section>'
        )

    tag = f'<span class="tag">{esc(label)}</span>' if label else ""
    # ★ 캡처 이미지 장(text_image)은 본문이 늘 비어 있다(S2c 캡처가 채우지
    #   않는다) — 그런데도 2단 그리드(텍스트 칸 + 이미지 칸)를 쓰면 빈 텍스트
    #   칸만큼 이미지가 절반 폭으로 쪼그라든다. "화면을 이미지가 다 덮어야
    #   한다"(2026-08-13)는 요구와 맞지 않아 이 종류만 통짜 폭으로 뺀다.
    # ★ 원고 장(html)도 `s-shots` 를 그대로 쓴다. 흰 배경 · 번호 감추기 · 좁은 제목
    #   여백 · 통짜 폭 · 재생 중 제목이 흔들리지 않게 하는 예외까지 전부 이미 여기
    #   붙어 있다. 새 클래스를 만들면 그 규칙들을 하나씩 다시 벌어야 한다.
    # ★ 영상 장도 **같은 상자**를 쓴다(2026-08-14).
    #   제목 아래 1688×944 통짜 자리 — 그림 장·원고 장과 자리도 크기도 같다.
    #   장 종류가 바뀔 때 화면이 들썩이지 않는 것이 이 자리를 하나로 두는 값이다.
    #   ★ `.s-media.vplay:not(.s-shots)` 의 "재생하면 글 칸이 접힌다" 는 이 장에
    #     이제 안 걸린다 — 접을 글 칸 없이 처음부터 통짜라 접을 것이 없다.
    cls = "s" + (" s-media" if media else "") + (
        " s-shots" if s.get("media_kind") in ("text_image", "thumb", "html", "video") else "")
    # ★ 그림으로 갈아낀 장은 **화면 전체가 그림**이다(1920×1080 한 판). 상자 안에
    #   앉히면 오른쪽·아래에 흰 여백이 남는데, 그건 "통으로 갈아낀다" 가 아니다
    #   (2026-08-14: "이걸 원하는 게 아니라니까"). 제목만 그 위에 얹힌다.
    if "m-swap" in media:
        cls += " s-swap"
        # ★ **전면 갈래**(2026-08-29). 액자를 걷고 화면을 네 귀퉁이까지 그림이
        #   덮는다. 옛 프로젝트는 이 클래스가 안 붙어 `.s-swap` 그대로 — 지난
        #   영상을 다시 구워도 화면이 안 바뀐다(그게 갈래를 나눈 이유다).
        #   ★ 값은 **문 앞에서 한 번** 정해진다(`static/js/start.js` 의 세 갈래).
        #     그림이 그 갈래에 맞춰 그려지므로 나중에 바꾸면 여백이 안 맞는다.
        if ((s.get("_project") or {}).get("image_fit") or "frame") == "full":
            cls += " s-swapfull"
    # ★ 썸네일 장(표지·마무리)은 **s-swap 과 다르다.** 그쪽은 3:2 액자에 넣고
    #   둘레에 바탕을 까는 방식이라, 물려 쓰면 그 여백이 그대로 따라온다.
    #   여기는 액자가 없다 — 화면 네 귀퉁이까지 그림이 덮고 제목도 안 띄운다
    #   (2026-08-17: "위에 텍스트 안 보이게 전체 화면에 강제로 늘려서 꽉 차게").
    if "m-pic" in media:
        cls += " s-pic"
        # ★ **전면 판의 표지·마무리는 제목을 띄운다**(2026-08-29).
        #   그림에 글자를 안 박게 되었으니 화면이
        #   대신 그려야 한다 — 안 그러면 표지가 글자 없는 그림 한 장이 된다.
        #   캡처 그림 장(`text_image`)과 옛 프로젝트는 그대로 글자 없이 둔다.
        if (s.get("media_kind") == "thumb"
                and ((s.get("_project") or {}).get("image_fit") or "frame") == "full"):
            cls += " s-picfull"

    return (
        f'<section class="{cls}" data-no="{no}" data-src="{s.get("src_no") or no}"'
        f' style="--lane:{color}">'
        f'<div class="wrap">'
        f'<header><span class="no">{no}<span class="of">/{total}</span></span>{tag}</header>'
        f'<h2>{esc(s.get("title"))}</h2>'
        f'<div class="cols">'
        f'<div class="txt">{_paras(s.get("body"))}{_evidence(s)}</div>'
        f'{media}'
        f'</div></div>{_cc_static(s)}{au}</section>'
    )


def _cc_static(s: Dict[str, Any]) -> str:
    """편집 화면에서만 보이는 자막 — **고친 것이 보여야 고칠 수 있다.**

    발표에서는 자막이 재생 중에 시간에 맞춰 뜨는데, 편집 화면의 iframe 은 소리를
    내지 않으므로 자막층이 꺼져 있다. 그러면 자막을 고쳐도 화면이 그대로라
    "저장이 안 되나" 로 읽힌다. 여기서는 시간과 무관하게 통째로 깔아 둔다.
    """
    t = ((s.get("narration") or {}).get("srt_text") or "").strip()
    return f'<div class="cc-st">{esc(t)}</div>' if t else ""


CSS = """
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;height:100%}
body{
  background:#f7f5f1;color:#2e2b27;
  font-family:"Pretendard",-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",system-ui,sans-serif;
  line-height:1.62;-webkit-font-smoothing:antialiased;
  word-break:keep-all;overflow:hidden;
}
#deck{height:100vh;overflow:hidden;position:relative}
.s{
  position:absolute;inset:0;display:grid;place-items:center;
  padding:6vh 7vw 9vh;opacity:0;pointer-events:none;transition:opacity .18s;
}
.s.on{opacity:1;pointer-events:auto}
/* ★ 이미지가 있는 장은 세로 중앙 정렬(place-items:center)을 쓰지 않는다.
   제목 줄 수가 장마다 달라 .wrap 높이가 조금씩 바뀌는데, 중앙 정렬이면 그때마다
   .wrap 전체가 위아래로 살짝 흔들린다 — 장을 넘길 때마다 그림이 미세하게
   움직이는 것처럼 보인다(2026-08-13).
   위쪽 정렬로 고정하면 상단 padding 만큼에서 항상 시작해 흔들리지 않는다. */
.s-media{align-items:start}
.wrap{width:min(1180px,100%)}
header{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.no{font-variant-numeric:tabular-nums;font-weight:800;font-size:15px;color:var(--lane)}
.of{color:#948e86;font-weight:600}
.tag{padding:2px 9px;border-radius:99px;background:#efebe4;color:#6b6660;
  font-size:11px;font-weight:700}
h1{margin:0 0 20px;font-size:clamp(28px,4.4vw,54px);font-weight:700;
   letter-spacing:-.03em;line-height:1.18;color:#1f1d1a}
h2{margin:0 0 22px;font-size:clamp(21px,2.7vw,34px);font-weight:700;
   letter-spacing:-.025em;line-height:1.28;color:#1f1d1a}
h2::after{content:"";display:block;width:52px;height:3px;margin-top:14px;background:var(--lane)}
p{margin:0 0 11px;font-size:clamp(14px,1.15vw,17px);color:#4a453f;max-width:62ch}
.s-cover p{font-size:clamp(15px,1.3vw,19px);color:#6b6660}
.s-cover .meta{margin-top:22px;font-size:12.5px;color:#948e86;
  font-family:ui-monospace,SFMono-Regular,Consolas,monospace}

.cols{display:grid;gap:34px;grid-template-columns:1fr}
.s-media .cols{grid-template-columns:minmax(0,1fr) minmax(0,1.05fr);align-items:start}
/* ★ 분기를 640 까지 낮춘다. 편집 화면의 iframe 은 700~900px 이라 900 으로 두면
   거기서만 세로로 쌓여서, 실제 발표 화면과 다른 배치를 보고 판단하게 된다. */
@media (max-width:640px){.s-media .cols{grid-template-columns:1fr}}
/* 좁은 폭에서는 간격과 글자를 줄여 두 칸이 그대로 유지되게 */
@media (max-width:900px){.cols{gap:20px}.s{padding:5vh 5vw 7vh}}

/* 근거 — 이게 주인공이다. 불릿 나열이 아니라 출처 목록. */
.ev{margin:18px 0 0;padding:0;list-style:none;
    border-top:1px solid rgb(40 34 28/.10);padding-top:12px}
.ev li{font-family:ui-monospace,SFMono-Regular,"Cascadia Mono",Consolas,monospace;
  font-size:11.5px;color:#7d756b;padding:2px 0;word-break:break-all}
.ev li::before{content:"";display:inline-block;width:5px;height:5px;
  margin-right:8px;vertical-align:middle;background:var(--lane);border-radius:1px}

.m{margin:0;min-width:0}
.m video,.m img{width:100%;display:block;border-radius:10px;background:#efebe4;
  box-shadow:0 1px 0 rgb(40 34 28/.10)}
.m figcaption{margin-top:8px;font-size:12px;color:#7d756b}

/* ★ 영상은 **재생 중에만 커진다.**
   장이 뜰 때는 제목·본문과 나란히 작게 있다가, 재생이 시작되면 화면을 차지하고,
   끝나면 다시 제자리로 돌아온다. 발표에서 눈이 갈 곳이 매 순간 하나여야 한다.
   레이아웃을 갈아치우지 않고 grid-template-columns 와 opacity 만 바꾼다 —
   video 요소가 DOM 에서 안 움직이므로 재생이 끊기지 않는다. */
.s-media .cols{transition:grid-template-columns .55s cubic-bezier(.22,.68,.2,1)}
.s-media .txt{transition:opacity .34s,transform .55s cubic-bezier(.22,.68,.2,1)}
/* ★ "재생 중 커지기" 효과는 작은 썸네일이 화면을 차지하러 커지는 연출이다 —
   .s-shots 는 처음부터 폭 전체를 쓰므로 커질 자리가 없다. 그런데도 JS 는
   모든 그림 장에 .vplay 를 그대로 걸어서(render/slides.py JS, armShots),
   이 규칙이 .s-shots 에도 그대로 먹으면 커지는 건 안 보이고 **제목만 진하게
   가라앉았다 돌아오는 깜빡임**만 남는다(2026-08-13).
   .s-shots 는 이 대상에서 뺀다 — 제목이 재생 내내 그대로다. */
.s-media.vplay:not(.s-shots) .cols{grid-template-columns:0fr minmax(0,1fr);gap:0}
.s-media.vplay:not(.s-shots) .txt{opacity:0;transform:translateX(-14px);pointer-events:none;overflow:hidden}
.s-media.vplay:not(.s-shots) h2,.s-media.vplay:not(.s-shots) header{opacity:.34;transition:opacity .3s}
.s-media.vplay .m video{border-radius:12px;box-shadow:0 10px 40px rgb(40 34 28/.18)}
.s-media.vplay .m figcaption{opacity:0}
.m-shots{position:relative}
/* ★ 캡처 높이를 이 박스 비율(padding-top:62.5%)에 맞춰 뽑으므로 보통은 여백이
   안 남는다 — 그래도 마지막 항목처럼 내용이 짧아 남는 경우, 배경(#efebe4,
   누런빛)이 비쳐 보이던 것을 없애고(투명 → 페이지 배경과 같아짐) 위쪽에
   붙인다(2026-08-13: 덱 레이아웃은 그대로 두고 이미지만 위로). */
.m-shots img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
  object-position:top;background:transparent;
  opacity:0;transition:opacity .35s}
.m-shots img.on{opacity:1}
.m-shots::before{content:"";display:block;padding-top:62.5%}
/* ★ 그림만 있는 칸 — 고정 비율 상자를 **풀고** 그림 제 비율대로 놓는다.
     상자를 두면 3:2 그림이 16:10 칸 안에 들어가면서 좌우에 흰 띠가 남는다.
     첫 장은 그대로 보이고(opacity 0 이면 높이가 0 이 된다), 여러 장이면
     둘째부터만 겹쳐 놓는다 — 넘길 때 자리가 흔들리지 않게. */
.m-pic::before{display:none}
/* ★ `object-fit:fill` 이다(contain 이 아니다). 그림이 16:9 에 **한두 픽셀 모자라게**
     오는 일이 있는데(실측: 1672×941 — 16:9 면 1673 이어야 한다), contain 이면 그
     모자란 만큼이 오른쪽에 흰 세로선으로 남는다. 여기서는 칸이 곧 그림 비율이라
     늘어나 봐야 1px 이고, 자르지 않는 편이 낫다 — 그림 위에 제목이 인쇄돼 있다. */
.m-pic img{position:static;width:100%;height:auto;object-fit:fill;display:block}
.m-pic img:not(:first-of-type){position:absolute;inset:0;height:100%;
  object-fit:cover;object-position:top center}
.m-pic img:first-of-type{opacity:1}
.m-pic[data-n="1"] img{opacity:1}

/* ── 배경판 위의 글(11판) ──────────────────────────────────────────────────
   ★ 이 글은 **그림이 아니다.** 10판은 라벨을 이미지 모델이 그림 안에 인쇄했고
     그러다 한글이 깨졌다(저자 지적 2026-09-14 "한글이 조금 깨지는 문제").
     여기서는 브라우저가 그린다 — 깨질 수가 없고, 드래그로 선택되며,
     모션이 이 요소를 직접 움직일 수 있다(상자를 되찾을 필요가 없다).
   ★ 자리는 `--lx/--ly` 로 들어온다. 그 값은 지시문이 이미지 모델에게
     "여기를 비워라" 라고 말한 좌표와 **같은 표**에서 나온다
     (pipeline/s3a_imgprompt.py 의 PLACE_XY). 둘이 어긋나면 글이 그림을 덮는다.
   ★ 크기는 그림 **높이** 기준이다. 10판이 모델에게 요구하던 수치를 그대로
     옮겼다 — 소제목 4%, 설명은 그 65%. cqh 를 쓰면 그림 칸이 커지든 작아지든
     비율이 유지된다(발표 화면·영상 프레임·편집 미리보기가 다 다른 크기다). */
.m-swap{container-type:size}
.lbls{position:absolute;inset:0;pointer-events:none}
.lbl{position:absolute;left:var(--lx);top:var(--ly);width:var(--lw);
     pointer-events:none;text-wrap:pretty;word-break:keep-all}
.lbl b{display:block;font-weight:700;font-size:4cqh;line-height:1.25;
       letter-spacing:-.02em;color:#1F4E79}
.lbl span{display:block;margin-top:.35em;font-weight:500;font-size:2.6cqh;
          line-height:1.42;letter-spacing:-.01em;color:#334155}
/* 그림이 밝은 아이보리라 보통은 그냥 읽힌다. 다만 장면이 라벨 자리로
   번지는 장이 있어 **아주 옅은 후광**을 깔아 둔다. 그래도 안 읽히는 자리는
   아래 `.cell` 로 판을 깐다 — 라벨마다 사람이 켠다. */
.lbl b,.lbl span{text-shadow:0 0 6px #F6F1E8,0 0 12px #F6F1E8}
/* 사람이 친 **엔터를 그대로 살린다**(2026-09-18). HTML 은 줄바꿈을
   공백으로 뭉개므로 그냥 두면 입력칸에서 두 줄로 친 설명이 화면에서 한 줄로
   이어 붙는다.
   ★ `
` 을 `<br>` 로 바꾸지 **않는다.** 그 길은 라벨 글이 HTML 로 해석되는
     문을 여는 것이고(사람이 치는 칸이다), 입력칸 ↔ 화면이 글자 그대로
     오가지 않게 된다. `pre-wrap` 은 텍스트를 텍스트인 채로 두면서 줄바꿈만
     살린다 — 긴 줄은 여전히 상자 폭에 맞춰 접힌다. */
.lbl b,.lbl span{white-space:pre-wrap}

/* 셀색 세 갈래 — **윤곽(기본) · 판 · 끔**.

   ★ **윤곽이 기본이다**(2026-09-18).
     판은 글 길이와 상관없이 `--lw`(23%) 만큼 깔려 그림을 헛되이 가렸다.
     윤곽은 **글자 모양 그대로** 아이보리가 둘러싸므로 그림이 거의 다 산다.
   ★ **`paint-order:stroke fill` 이 핵심이다.** 이것 없이 text-stroke 만 걸면
     윤곽이 글자 안쪽으로도 파고들어 한글 획이 뭉갠다(28px 설명줄에서 특히).
     윤곽을 먼저 긋고 글자 본체를 그 위에 덮으면 **바깥 절반만** 남는다.
   ★ **판을 안 버린다.** 청사진·도면처럼 바탕이 아주 복잡한 자리는 윤곽으로
     부족하다(실측 4장: 「목적」·「두 번째 축」이 도면 선과 섞였다). 그 자리만
     사람이 «셀색» 을 눌러 판으로 올린다.
   ★ 굵기는 글자 크기의 **14%** — 보이는 것은 그 절반인 7% 다. 세 곳이 같은
     비율이어야 편집 화면이 거짓말을 안 한다.

   (아래는 판 갈래의 유래다.) 글자 뒤에 바탕과 **같은 아이보리** 판을 깐다.
   ★ **라벨마다 켠다.** 한가한 면에 앉은 글까지 판을 깔면 배경판이 아니라 카드
     슬라이드가 된다 — 깔아야 하는 자리와 안 깔아도 되는 자리가 갈린다
     (2026-09-18). 기본은 꺼짐 — 지시문이 만든 라벨은 판이 없다.
   ★ 예전 주석은 「상자·카드는 쓰지 않는다 — 그림 위에 판을 깔면 배경판을 쓰는
     뜻이 없어진다」였다. 그 이유는 **안 맞는다.** 배경판의 값어치는 한글이 안
     깨지는 것과 모션이 DOM 을 직접 움직이는 것인데, 셀색은 둘 중 어느 것도
     건드리지 않는다. 그림이 라벨 자리로 번진 장에서는 후광만으로는 안 읽힌다.
   ★ **padding 만큼 margin 을 되민다.** 안 그러면 판이 생기는 순간 글이
     padding 만큼 오른쪽·아래로 밀려, 손으로 맞춰 둔 자리가 전부 어긋난다.
     `box-sizing:content-box` 도 같은 이유다 — `--lw` 는 **글자 폭**이다.
   ★ 판이 깔리면 후광을 끈다. 둘을 같이 두면 판 가장자리에서 글자가 번져 보인다. */
/* ★ **기본은 켜짐**(2026-09-18). 끄는 쪽이 사람 일이다 — 켜는 쪽을 사람
     일로 두면 **안 켠 장이 안 읽히는 채로 그냥 나간다.** 켜져 있으면 눈에
     거슬려서라도 끄게 된다. 안전한 쪽을 기본으로 두는 규칙이다.
   ★ 그래서 판정은 `cell` 이 **`false` 인가**로 한다. 없거나 true 면 켜짐 —
     지시문이 만든 라벨에는 이 칸이 아예 없다(`labels_of`). */
.lbl.cell-box{box-sizing:content-box;padding:1.2cqh 1.6cqh;margin:-1.2cqh -1.6cqh;
              background:#F6F1E8;border-radius:.9cqh}
.lbl.cell-line b{-webkit-text-stroke:.56cqh #F6F1E8;paint-order:stroke fill}
.lbl.cell-line span{-webkit-text-stroke:.36cqh #F6F1E8;paint-order:stroke fill}
.lbl.cell-box b,.lbl.cell-box span,
.lbl.cell-line b,.lbl.cell-line span{text-shadow:none}
@container (max-width:900px){
  .lbl b{font-size:4.6cqh}
  .lbl span{font-size:3cqh}
}

/* ★ 캡처(text_image) 장 전용 — 텍스트 칸이 늘 비어 있으니 통짜 폭으로 쓰고,
   고정 비율 박스 없이 캡처 원래 크기 그대로 얹는다. 장마다 이미지 실제
   높이만큼만 차지하고 화면 맨 위(제목 바로 아래)에서 시작하며, 남는 아래
   쪽은 그냥 페이지 배경이다 — 억지로 박스를 채우려 자르거나 늘이지 않는다
   (2026-08-13).
   장 번호 표시(header)는 그 공간을 아끼려 이 종류에서는 숨긴다(가려도
   된다고 확인받음).
   ★ `.wrap`은 원래 `.s{place-items:center}`를 물려받아 **가로로 가운데
   정렬**된다 — 폭이 min(1180px,100%)로 고정돼 있으니, 영상은 항상
   1920px 로 찍혀서(render_frames.mjs) 좌우로 남는 폭이 커 왼쪽 패딩을
   아무리 줄여도 정작 왼쪽 정렬 효과가 약했다(2026-08-14: "좌측은 최대로
   붙여야"). justify-items 를 start 로 바꿔 이 장 종류만 왼쪽 끝(패딩
   위치)에 붙인다. */
/* ★ 이 장 종류만 배경을 흰색으로 바꾼다(2026-08-14: "배경을 하얀색으로") —
   카드(.m-shots)는 이미 흰색인데 그 둘레(제목 위·오른쪽 여백)만 크림색
   (#f7f5f1, body 배경)이라 화면 전체가 하나로 안 보였다. 전체 앱의
   body 배경은 그대로 둔다 — 다른 장 종류(표지·판단 등)는 크림 바탕을
   기준으로 태그·색이 설계돼 있어서 거긴 안 건드린다. */
/* ★ 왼쪽 여백을 **0 으로** 둔다(2026-08-14) — 본문을 최대한 왼쪽에 붙이고
   붙인 만큼 폭을 늘린다. 예전 0.5vw(9.6px)를
   오른쪽 아바타 칸으로 넘겨, 1920 기준 **본문 1688 + 아바타 232** 가 된다.
   오른쪽 패딩(7vw)은 남겨 두지만 본문 상자가 width 를 직접 가지므로 상자를
   밀지 않는다 — 다른 장 종류(표지·판단)가 쓰는 값이라 건드리지 않는다. */
.s-shots{padding:2vh 7vw 2vh 0;justify-items:start;background:#fff}
.s-shots header{display:none}
/* ★ 제목만 왼쪽에서 조금 떼어 둔다(2026-08-14) — 윗여백만큼 왼쪽에도 둔다.
   본문 상자는 화면 왼쪽
   끝(0)에 그대로 붙어 있고 — 그래야 오른쪽 아바타 칸 232px 이 지켜진다 —
   제목만 위 여백과 같은 값(2vh = 1080 기준 21.6px)만큼 들어온다.
   본문(원고 HTML)은 자기 여백을 이미 갖고 있어서 건드리지 않는다.

   ★ **밑줄을 뺀다**(2026-08-14: "선이 너무 눈에 띄어서 · 제목을 한 포인트
     키우고 다른 색으로 굵게 하면 선을 지워도 될 것 같습니다").
     줄이 하는 일은 "여기가 제목이다" 를 말하는 것인데, 제목 자신이 충분히
     달라 보이면 줄은 같은 말을 두 번 하는 셈이다. 게다가 폭이 52px 로 고정돼
     있어 제목 길이와 무관하게 늘 같은 자리에서 끊겨 어긋나 보였다.
     대신 제목을 키우고(34 → 38px) 색을 레인 색으로 바꾸고 더 굵게(700 → 800)
     한다 — 굵기·자간·색이 함께 달라지면 눈에는 다른 서체처럼 읽힌다.
     ★ 새 글꼴 파일을 들이지 않는다: 완성본은 파일 한 장으로 나가야 하고,
       바깥에서 불러오는 것은 따라가지 않는다.
   ★ 높이는 오히려 는다 — 줄(3px)과 그 위 여백(6px)이 빠지고 제목이 5px
     커져서, 본문이 쓸 수 있는 세로가 4px 늘어난다. */
.s-shots h2{margin-bottom:15px;padding-left:2vh;
  font-size:clamp(24px,2vw,38px);font-weight:800;letter-spacing:-.035em;
  color:var(--lane)}
.s-shots h2::after{display:none}
.s-shots .cols{grid-template-columns:1fr;gap:0}
.s-shots .m-shots::before{content:none}
/* ★ 폭을 100%로 꽉 채우지 않는다(2026-08-14) — 캡처 원본이 옆으로
   넓게 늘어나 보이던 것을, 왼쪽 정렬 + 폭 제한으로 오른쪽에 배경이 남게
   바꾼다. 세로(fitShot, 위 JS)는 그대로 — 높이가 길면 그쪽만 줄어든다.
   기본 block 요소라 margin 없이 두면 저절로 왼쪽 붙는다.
   ★ 카드(.m-shots)에 흰 배경만 준다(늘리지는 않는다 — 위 fitShot 참고) —
   이미지 자체와 카드 경계 사이에 이질감이 없게, 테두리 그림자도 뺐다. */
/* ★ .wrap 자체는 그대로 둔다(2026-08-14: "슬라이드 판은 그냥 두고 이미지만
   늘려달라") — 제목·레이아웃 자리는 안 건드린다. 대신 박스 폭을 %(=wrap
   기준, 1180px 에서 막힘) 가 아니라 **vw(=화면 기준)** 로 준다 — 그러면
   wrap 폭과 무관하게 박스가 그 오른쪽 경계를 넘어 실제로 더 커진다. wrap
   을 벗어나도 막는 것(overflow:hidden)이 없어서 그대로 커져 보인다.
   61vw ≈ 화면 전체 기준 오른쪽 여백이 1/3 정도 되도록 실측한 값. */
/* ★ max-width 로는 안 됐다 — 그리드 칸(.cols)이 기본으로 wrap 폭(1180px)
   까지 아이템을 늘리는데(stretch), max-width 값이 그보다 크면(예: 66vw=
   1267px > 1180px) 상한이 실제 계산값보다 커서 아무 효과가 없다(실측:
   66vw 줘도 그대로 1180px 로 나옴). width 를 직접 줘야 그 스트레치를
   덮어쓰고 지정한 크기 그대로(넘치면 넘치는 대로) 나간다. */
/* ★ vw(화면 폭 비례)에서 고정 px로 바꾼다(2026-08-14) — vw 는 미리보기
   창 크기에 따라 실제 픽셀이 계속
   달라져서 볼 때마다 다르게 보였다. 영상은 항상 1920px 로 찍히니
   (render_frames.mjs), 그 기준 66%인 1267px 로 못박는다 — 미리보기
   창 크기와 무관하게 항상 이 값이다. */
/* ★ 본문 폭 = 1688px. 1920 화면에서 **왼쪽 여백 9.6px + 본문 1688 + 오른쪽 222**
   이 되게 잡은 값이다(2026-08-14).

   왜 이 숫자인가 — 세로를 직접 키우면 장마다 글자 크기가 튄다. 대신 **옆으로
   늘리면 배율이 커지고 세로가 따라 자란다**("영상은 저렇게 두고 옆을 늘리는
   형태"). 실측(88장): 폭 1536 일 때 제일 긴 장이 화면 세로의 91% 였는데,
   1688 로 넓히면 배율이 1.627 → 1.788 이 되어 **딱 100%** 로 끝난다.

   오른쪽에 남는 222px 이 아바타(우하단) 자리다 — 그래서 이 둘은 한 몸이다.
   한쪽을 바꾸면 다른 쪽도 같이 바뀐다(#av 의 width 참고).

   ★ 창이 이보다 좁으면 상자가 창을 넘쳐 글이 오른쪽 끝까지 가 버린다(화면
     배율 125% PC 나 창을 줄인 경우). 88vw 를 상한으로 둔다 — 1920 에서는
     88vw=1690 이라 min() 이 1688 을 고르므로 값이 그대로다.
   ★ `max-width` 로는 안 된다: 그리드 칸이 .wrap(1180px)까지만 늘려서, 그보다
     큰 max-width 는 아무 효과가 없다(그래서 원래도 width 를 직접 준다). */
.s-shots .m-shots{background:#fff;width:min(1688px,88vw);max-width:none}
/* ★ 영상 장도 **같은 자리 같은 크기**다(2026-08-14). 영상 `<figure>` 에는
     `.m-shots` 가 없어 위 폭 규칙이 안 걸리므로 여기서 따로 같은 값을 준다.
     `contain` 인 이유: 화면 녹화가 16:9 가 아닐 수도 있는데 `cover` 로 두면
     가장자리가 잘려 나간다 — 그림과 달리 영상은 잘리면 안 되는 것이 찍혀 있다.
     남는 자리는 검정이라 영상 프레임처럼 보인다. */
.s-shots .m:not(.m-shots){width:min(1688px,88vw);max-width:none;margin:0;
  aspect-ratio:16/9;background:#000;overflow:hidden;border-radius:inherit}
.s-shots .m:not(.m-shots)>video,
.s-shots .m:not(.m-shots)>img{display:block;width:100%;height:100%;
  object-fit:contain;max-width:none;box-shadow:none}
/* ★ `:first-child` 도 붙여 아래 `.m-shots img:first-child{position:absolute}`
   (여러 장 캡션 전환용 — 이 종류엔 항상 이미지가 한 장뿐이라 그게 곧
   first-child 다)와 명시성을 맞춘다. 같은 명시성이면 소스 순서상 저 규칙이
   나중이라 이겨서 `position:static` 이 씹혔다 — 그러면 이미지가 레이아웃
   흐름을 안 채워 카드(.m-shots) 높이가 0으로 무너진다(2026-08-14 실측:
   화면엔 잘 보이는데 좌표를 재면 height:0). */
.s-shots .m-shots img:first-child{position:static;width:auto;max-width:100%;
  height:auto;object-fit:unset;object-position:unset;opacity:1;box-shadow:none}
.m-shots img:first-child{position:absolute}

/* ── 원고 장(html) — 그림이 아니라 **글 그대로** ────────────────────────
   ★ 캡처와 **픽셀이 겹치도록** 만든 값이다. 실측 근거:
       원본 문서는 960px 뷰포트에서 배치되고, body 테두리 상자는 944px 이다
       (UA 기본값 `body{margin:8px}` 이 좌우로 8px 씩 먹는다).
       그것을 2배로 찍어 1888px PNG 가 되고, 위 `.m-shots{width:1536px}` 상자에
       들어가 축소된다 → 실효 배율 1536 / 944 = 1.62712.
   그래서 살아 있는 글도 **944px 폭에서 배치한 뒤 1.62712 배로 확대**한다.
   줄바꿈 위치도 표 칸 너비도 캡처와 같다 — 배치가 같은 폭에서 일어나기 때문이다.
   `zoom` 이나 글자 크기 키우기로는 안 된다. `zoom` 은 1536px 에서 배치를 다시 해
   줄바꿈이 달라지고, 글자 크기는 원본이 섞어 쓰는 rem(문서 기준)과 em(부모 기준)이
   서로 다른 비율로 자라 비례가 깨진다. */
.m-html{position:relative;margin:0;background:#fff;overflow:hidden}
.m-html>.doc{width:944px;transform-origin:top left;box-sizing:border-box}
/* 조각 안은 원본 문서의 상자 계산을 그대로 둔다 — 위 전역 border-box 가 표 칸
   여백까지 바꿔 버리면 캡처와 어긋난다. */
.m-html>.doc *{box-sizing:content-box}
/* 원본 `body` 의 좌우 여백(4px)은 남기고 위아래는 뺀다 — 그 여백은 문서의 처음과
   끝에 두라고 준 것인데 조각은 문서 중간이다. 좌우를 빼면 본문 폭이 936→944 로
   벌어져 줄바꿈이 달라지므로 **좌우는 꼭 남긴다.** */
/* ★ 왼쪽 여백을 제목과 **같은 값**으로 맞춘다(2026-08-14) — 글자로 시작하는
   장이 잘려 보였다. 원본 `body` 가 주는 좌우 여백은 4px 뿐인데, 배율(1.788)을
   먹여도 7px 밖에 안 된다 — 불릿(●)으로 시작하는 장은 점이 안쪽에 있어 괜찮지만
   글자로 시작하는 장은 첫 글자가 화면 모서리에 닿아 잘린 것처럼 보인다.
   제목이 들어온 만큼(2vh) 들어오면 둘이 나란히 서고 잘려 보이지도 않는다.
   ★ `padding` 이 아니라 `margin-left` 다 — padding 을 키우면 `width:944px`
     안쪽이 좁아져 **줄바꿈 위치가 달라진다**(캡처와 픽셀이 겹치던 근거가 깨진다).
     margin 은 상자를 통째로 옮길 뿐이라 안쪽 배치가 그대로다. */
.m-html>.doc{padding-top:5px;padding-bottom:0;margin-left:calc(2vh / 1.788)}
.m-html>.doc>*:first-child{margin-top:0}
.m-html>.doc>*:last-child{margin-bottom:0}

/* ★ 그림으로 갈아끼운 장 — 몸통 자리를 그림 한 판이 채운다.
   `.doc` 이 없으므로 위 944px 배치·배율 규칙은 하나도 안 걸린다. 아래 JS 도
   `.doc` 이 없으면 일찍 돌아간다(그 자리에 주석을 남겼다).

   ★ 비율은 **그림이 만들어지는 비율**을 그대로 쓴다 — 3:2. gpt-image 의
     `landscape` 가 1536×1024 다(`showcase.config.json` 의 `image.aspect`).
     예전엔 16:9 상자에 `cover` 로 넣어 위아래를 잘랐는데, 만든 비율대로 두면
     **잘려 나가는 것이 없다**(2026-08-14). 그 설정을 바꾸면 아래
     `aspect-ratio` 도 같이 바꿀 것.

   ★ 크기는 **높이가 정한다.** 폭부터 잡으면(1688) 3:2 에서 높이가 1125 가 되어
     제목 아래 자리(944)를 넘친다. 높이를 944 로 두면 폭이 1416 으로 따라온다 —
     **자리에 들어가는 가장 큰 3:2** 다. 글 판이 1688 이었으니 비율을 맞춘 것만으로
     이미 한 뼘 줄어든 셈이고, 거기서 더 줄이면 옆이 허전해진다(2026-08-14: 처음에
     848 로 줄였더니 "너무 줄인 것 같다" — 「조금 줄여」를 두 번 적용한 것이었다).
     더 줄이고 싶으면 `--swap-h` 하나만 바꾸면 된다. 폭은 비율이 알아서 따라온다.

   ★ 셀렉터를 길게 쓴 이유 — 위 `.s-shots .m-shots img:first-child{width:auto}`
     (캡처 그림을 원래 크기로 두려고 넣은 규칙)가 **우선순위로 이긴다**(0,3,1 대
     0,1,1). 짧게 쓰면 그림이 제 크기로 앉아 상자를 안 채운다(2026-08-14 실측:
     상자 1688 인데 그림 1416). 같은 자릿수로 맞추고 뒤에 두어 이긴다. */
.m-swap{background:#fff;--swap-h:944px}
/* ★ 그림에 **글이 박혀 오면** 화면을 통째로 준다 — 제목·번호를 걷고 상자도 없앤다.
     그림 안에 헤드라인이 이미 인쇄돼 있어서, 위에 HTML 제목을 또 띄우면 한 장에
     제목이 둘이 된다(2026-08-14 실측: "1 경제 전체를 보는 눈" 위에 "같은 경제,
     다른 렌즈" 가 같이 떴다). 이게 「유튜브 크기로 통으로 갈아낀다」의 완성형이다.
   ★ `cover` 다 — 3:2 를 16:9 에 꽉 채우면 위아래가 조금 잘린다. 지시문이 상단에
     제목 자리를 넓게 비우게 시키므로 글자가 잘려 나가지 않는다. */
/* 번호 배지와 빈 글칸만 걷는다. **제목은 남긴다** — 그림 안에 헤드라인이 박혀
   와도 화면 위 제목을 같이 두기로 했다(2026-08-14). 그림 위에 얹히므로
   z-index 로 띄운다. */
.s-swap header,.s-swap .txt{display:none}
/* ★ **자르지 않고, 남는 자리를 디자인으로 만든다.**
     그림은 3:2(1536×1024)이고 화면은 16:9 다. 채우면 위아래가 잘리는데 그림 맨
     위에 헤드라인이 인쇄돼 있어 **제목이 날아간다.** 그러니 자를 수 없고, 남는
     자리는 반드시 생긴다. 흰 여백으로 두면 "덜 만든 화면" 으로 보이므로
     (2026-08-14: "하얗거나 잘린 듯할 때 이질감이 크다"), 바탕을 깔고 그림을
     **액자에 넣은 판**으로 만든다. 오른쪽에 남는 자리는 원래 **아바타 자리**다
     (위 `.s-shots` 폭 주석의 222px — 사람이 우하단에 뜬다).
   ★ absolute 로 띄우지 않는다. 그렇게 했더니 장이 화면 아래로 밀리고(y=1080)
     그림 높이가 40px 로 잡혔다. 폭·높이는 아래 3:2 규칙이 이미 잘 잡고 있다. */
/* ★ 자리 배분 — **왼쪽으로 붙이고 위에 한 줄 남긴다**(2026-08-14).
     위   제목 한 줄. 나중에 로고가 같이 앉는다
     왼쪽 34px 만 띄운다 — 그림이 화면을 최대한 쓰게
     오른쪽 남는 자리(≈450px)가 **아바타 자리**다. 사람이 우하단에 뜬다 */
/* ★ **글 장도 같은 액자를 쓴다**(2026-08-15). 그림 장만 액자에 들어가 있으면
     장이 넘어갈 때 바탕이 흰색↔아이보리로 튄다. 안쪽은 흰 판 그대로 두고
     — 원고 CSS 가 흰 바탕을 전제로 색을 잡아 두었다 — 바깥 바탕과 테두리만
     그림 장과 같게 맞춘다. */
.s-shots{background:radial-gradient(120% 100% at 18% 0%,#F7F4ED 0%,#EFEAE0 55%,#E7E1D5 100%)}
.s-shots .m-html:not(.m-swap){background:#fff;border-radius:14px;overflow:hidden;
  box-shadow:0 1px 2px rgba(58,50,38,.10),0 2px 8px rgba(58,50,38,.06),
             0 28px 64px -22px rgba(58,50,38,.42)}
/* 조각 안쪽에 숨 쉴 자리 — 액자에 닿아 글자가 붙어 보이지 않게 */
.s-shots .m-html:not(.m-swap)>.doc{padding-top:16px;padding-bottom:14px}
.s.s-swap{background:radial-gradient(120% 100% at 18% 0%,#F7F4ED 0%,#EFEAE0 55%,#E7E1D5 100%)}
/* ★ 치수를 **여기 한 자리에서** 잡는다. 섹션 padding 을 고치는 길은 위쪽
     `.s`·`.s-shots` 와 자릿수 싸움이 되고, `--swap-h` 는 `.m-swap` 이 제 값을
     들고 있어 섹션에서 내려보내도 안 먹는다(2026-08-14 실측: 956 을 줘도 944).
   ★ **픽셀이 아니라 창 크기 단위**로 적는다. 처음에 1434×956 으로 못박았더니
     1920×1080 아닌 창에서 카드가 화면을 넘쳐 제목이 잘렸다(2026-08-14 실측).
     영상은 늘 1920 으로 찍히지만 사람은 아무 크기 창에서 완성본을 연다.
       높이 88.5vh = 956/1080 · 왼쪽 여백 1.77vw = 34/1920
       음수 margin 은 섹션의 5vw padding 을 빼는 값이다(1.77 - 5 = -3.23)
     남는 오른쪽(≈23.5vw)이 아바타 자리다. */
.s.s-shots.s-swap .m-shots.m-swap{height:min(88.5vh,calc(94vh - 62px));
  width:auto;aspect-ratio:3/2;max-width:none;margin-left:-3.23vw}
/* ★ 썸네일 장 — **화면을 네 귀퉁이까지 그림이 덮는다.**
     액자도 여백도 제목도 없다. 표지·마무리는 그 자체가 한 장의 그림이고,
     그림 안에 이미 제목이 인쇄돼 있어 위에 또 띄우면 제목이 둘이 된다.
   ★ 받아 오는 비율이 제각각이다(표지 1672×941 ≒16:9 · 썸네일 1536×1024 =3:2).
     `contain` 이면 남는 쪽에 흰 자리가 남고, `fill` 이면 3:2 가 16:9 로 눌려
     **글자가 찌그러진다** — 스튜디오에 16:9(1536×864)로 시켜도 3:2 로 온다.
     그래서 `cover` + `object-position:top` 이다: 폭을 채우고 **아래를 자른다**.
     글자는 그림 위쪽에 인쇄돼 있어 잘리는 쪽은 배경뿐이다
     (2026-08-21). */
/* ★ `position` 을 건드리지 않는다. `.s` 가 이미 `absolute; inset:0` 으로 화면
     전체를 차지하는데, 여기서 `relative` 로 덮었더니 그 규칙이 풀려 장 높이가
     100px 로 주저앉았다(2026-08-17 실측). padding 만 걷는다. */
.s.s-pic{padding:0;background:#fff}
.s.s-pic>.wrap{padding:0;margin:0;max-width:none;width:100%;height:100%;
  display:block;place-items:stretch}
.s.s-pic>.wrap>h2,.s.s-pic>.wrap>header,.s.s-pic .txt{display:none}
.s.s-pic .cols{display:block;grid-template-columns:none;gap:0;height:100%}
.s.s-pic .m-shots.m-pic{position:absolute;inset:0;width:100%;height:100%;
  margin:0;max-width:none;border-radius:0;background:transparent;overflow:hidden}
.s.s-pic .m-shots.m-pic img{position:absolute;inset:0;
  width:100%;height:100%;object-fit:cover;object-position:top center}
/* 상단 한 줄 — 제목과 로고가 나란히 설 자리. 로고를 넣을 때 이 줄에 붙이면 된다 */
.s.s-swap>.wrap>h2{margin:0 0 1.3vh;padding-left:6px;line-height:1.25;
  font-size:clamp(18px,1.56vw,30px)}
.s.s-swap .m-shots.m-swap{background:transparent;border-radius:14px;overflow:hidden;
  box-shadow:0 1px 2px rgba(58,50,38,.10),0 2px 8px rgba(58,50,38,.06),
             0 28px 64px -22px rgba(58,50,38,.42)}
.s.s-swap .m-shots.m-swap>img{width:100%;height:100%;object-fit:cover;
  border-radius:inherit}
/* 제목은 바탕 위에 앉는다 — 그림 안 헤드라인과 결이 갈리지 않게 색을 낮춘다 */
.s.s-swap>.wrap>h2{color:#5A5142}
.s.s-swap>.wrap>h2::after{background:#C9BFAC}
.s-shots .m-shots.m-swap{aspect-ratio:3/2;height:min(var(--swap-h),88vh);
  width:auto;max-width:88vw}
.s-shots .m-shots.m-swap>img{display:block;width:100%;height:100%;
  object-fit:contain;max-width:none;position:static;box-shadow:none}

/* ══ 전면 갈래(.s-swapfull) — 액자를 걷고 화면을 통째로 준다 ═══════════════
   2026-08-29.
   위 `.s-swap` 은 3:2 액자에 앉히느라 오른쪽 456px 을 비워 뒀다(아바타 자리로
   남긴 것인데 `#av` 는 232px 만 쓰고 아직 비어 있다). 여기서는 가로를 꽉 채운다.

   ★ **옛 갈래를 한 줄도 안 고친다.** 그림은 만들어질 때의 갈래에 맞춰 여백이
     잡혀 있어서, 액자용으로 그린 그림을 전면으로 앉히면 그림에 인쇄된 제목이
     화면 제목과 겹친다. 지난 영상을 다시 구울 때 화면이 달라지면 안 된다.

   ★ 셈. 그림을 **16:9(1920×1080)로 받는다**(2026-08-29부터). 화면과 비율이 같아
     `cover` 를 걸어도 **한 픽셀도 안 잘린다** — 배율 1.0 으로 딱 맞는다.
   ★ `object-fit:cover` 를 그대로 둔다. 비율이 같으면 아무 일도 안 하고, 옛 3:2
     그림이 섞여 들어오면(판을 바꾸기 전에 그린 장) 위를 맞춰 아래를 잘라 준다 —
     `contain` 이면 그런 장에 좌우로 흰 자리가 생겨 더 나쁘다.

   ★ **제목은 그림 위에 얹힌다** — 그림을 내리지 않는다(2026-08-29).
     한 번 62px 내려 봤는데, 지시문이 이미 그림 **위 5% 를 비우게** 시키므로
     빈 자리가 두 겹이 됐다("그림에 제목자리를 비워놓고 그린거 아닌가요?!").
     제목 띠 62px 은 그림 높이의 **4.84%** 라, 그림이 비워 둔 5% 안에 그대로
     들어앉는다. 내리면 아래로 5%p 를 더 잘라 내는 손해까지 겹친다
     (20.5% vs 15.6% — 002.png 은 그 차이로 라벨이 살고 죽었다).
   ★ 되돌리려면 아래 `top:0` 을 `top:62px` 로만 바꾸면 된다.

   ★ **`.wrap` 과 `.cols` 를 같이 풀어야 한다.** 예전에 `.m-swap` 만 absolute 로
     띄웠더니 장이 화면 아래로 밀리고(y=1080) 그림 높이가 40px 로 잡혔다
     (2026-08-14 실측). 감싸는 두 상자가 grid 인 채로 남아 있어서였다. */
.s.s-swapfull{padding:0;background:#F6F1E8}
/* ★ **판을 16:9 로 못박고 남는 자리는 바탕으로 둔다**(2026-08-29).
     `.s` 는 창을 그대로 채우는데, 창이 16:9 보다 납작하면 `cover` 가 그만큼 더
     잘라 낸다 — 발표용 창(1911×912)에서 재 보니 그림의 **71.6%** 만 보였다
     (1920×1080 에서는 84.4%). 지시문은 84.4% 를 전제로 「아래 25% 를 비워라」고
     시키므로, 창 모양에 따라 잘리는 양이 달라지면 그 약속이 깨진다.
   ★ 그래서 `.wrap` 을 **가운데 놓인 16:9 무대**로 만든다. 창이 어떻든 잘리는 양이
     늘 15.6% 다. 1920×1080 에서는 `min()` 이 양쪽 다 꽉 차 지금과 똑같다 —
     **영상은 한 픽셀도 안 바뀐다.**
   ★ 안쪽 치수를 `cqh`·`cqw`(무대 기준)로 적는다. `vh`·px 로 두면 무대는 줄었는데
     제목만 그대로라 그림이 비워 둔 5% 띠를 넘는다. 앞 줄의 px 은 이 단위를
     모르는 브라우저용 받침이다. */
.s.s-swapfull>.wrap{position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);
  width:min(100%,calc(100vh * 16 / 9));height:min(100%,calc(100vw * 9 / 16));
  padding:0;margin:0;max-width:none;display:block;place-items:stretch;
  overflow:hidden;container-type:size}
.s.s-swapfull .cols{display:block;grid-template-columns:none;gap:0;height:100%}
.s.s-shots.s-swapfull .m-shots.m-swap{position:absolute;left:0;right:0;
  top:0;bottom:0;width:auto;height:auto;margin:0;max-width:none;
  aspect-ratio:auto;border-radius:0;box-shadow:none;background:transparent;
  overflow:hidden}
.s.s-shots.s-swapfull .m-shots.m-swap>img{position:absolute;inset:0;
  width:100%;height:100%;max-width:none;object-fit:cover;
  object-position:top center;border-radius:0;box-shadow:none}
/* 제목 — 그림 위 62px 띠. **고정 높이**라 장마다 크기가 안 흔들린다
   (2026-08-29: "제목사이즈가 들쑥날쑥해서 지금과 같은 형태를 취하는 겁니다").
   ★ `height` 가 아니라 `min-height` 다. 제목이 두 줄이 되면 `height` 는 넘치는
     만큼 위아래로 벌어져 **첫 줄이 y=0 위로 나가 잘린다.** min-height 면 0 에서
     아래로만 자라고, 그 아래는 그림이 비워 둔 자리다. */
.s.s-swapfull>.wrap>h2{position:absolute;left:0;right:0;top:0;
  z-index:2;display:flex;align-items:center;margin:0;line-height:1.25;
  color:#5A5142;
  min-height:62px;min-height:5.74cqh;          /* 62/1080 */
  padding:0 34px;padding:0 1.77cqw;            /* 34/1920 */
  font-size:clamp(18px,1.56vw,30px);font-size:2.78cqh}   /* 30/1080 */
/* (판이던 시절의 유래.) 공짜 안전판이다 — 그림이 제목칸(1칸)을 아이보리로
   비워 두라는 지시를 지키면 같은 색이라 **안 보이고**, 안 지키면 그 위에 판이
   깔린다(2026-09-18: "어차피 지켜지면 같은 색상이고 안 지켜질 경우 색 박스니").
   라벨의 «셀색» 과 달리 끄는 스위치를 두지 않는 이유가 그것이다 — 지켜진 장에는
   흔적이 없으므로 끌 일이 없다.
   ★ 여기는 위 둘과 꼴이 다르다 — 글자 둘레 판이 아니라 **맨 위 62px 띠 통째**다
     (left:0;right:0;top:0). 그림의 1칸이 바로 이 띠라, 띠를 칠하는 것이 곧
     1칸을 칠하는 것이다. padding 을 되밀 일도 없다. */
/* 제목도 **테두리**다(2026-09-18). 라벨과 같은 이유 —
   판은 글 길이와 상관없이 깔려 그림을 헛되이 가린다. `paint-order:stroke fill`
   로 윤곽을 먼저 긋고 글자 본체를 덮으므로 **바깥 절반만** 남는다.
   ★ 덤으로 **덱에서 제목 띠가 라벨 머리를 덮던 것**이 풀린다. 띠는 위쪽 62px
     통째를 칠하는 데다 z-index 가 2 라, 그 띠에 걸친 라벨이 통째로 잘렸다.
   ★ 굵기는 글자의 14% — 라벨과 같은 비율이다. 셋이 같아야 편집 화면이
     거짓말을 안 한다.
   여기 제목은 2.78cqh(=30px) 로 작다. 그 14% = .39cqh. */
.s.s-swapfull>.wrap>h2{-webkit-text-stroke:.39cqh #F6F1E8;paint-order:stroke fill}
.s.s-swapfull>.wrap>h2::after{display:none}

/* ══ 전면 판의 표지·마무리(.s-picfull) — 그림 장과 같은 틀 ════════════════
   그림에 글자를 안 박으므로 제목을 화면이 그린다. 판을 16:9 로 못박는 것도
   같은 이유다 — 창이 납작하면 `cover` 가 더 잘라 낸다.
   ★ `.s-pic` 의 `h2{display:none}` 을 이겨야 해서 클래스를 하나 더 겹쳐 쓴다
     (0,4,1 대 0,3,1). 짧게 쓰면 자릿수가 같아 소스 순서 싸움이 된다. */
.s.s-pic.s-picfull>.wrap{position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);
  width:min(100%,calc(100vh * 16 / 9));height:min(100%,calc(100vw * 9 / 16));
  padding:0;margin:0;max-width:none;display:block;place-items:stretch;
  overflow:hidden;container-type:size}
/* ★ **표지·마무리에는 글자를 안 얹는다**(2026-09-05) — 16:9 그림이 그대로
     나가고 위에 아무 글자도 안 뜬다.
     한때 제목을 그림 위 띠에 얹어 봤는데, 표지는 **그림 한 장이 그 자체로 말을
     하는 자리**라 글자가 없는 편이 낫다는 결론이었다. `.s-pic` 이 이미
     `h2{display:none}` 이라 여기서 되살리지만 않으면 된다.
   ★ 그림도 안 내린다 — 위 `.m-pic{inset:0}` 그대로 화면을 통째로 덮는다.
     `.s-picfull` 이 하는 일은 이제 **판을 16:9 로 못박는 것 하나**다(아래 wrap).
     지시문도 위를 비울 이유가 없어졌다(`render/thumbnail.py`). */
.s.s-pic.s-picfull{background:#F6F1E8}

/* 줄 등장 — `display` 가 아니라 `opacity` 다. display 로 감추면 줄이 뜰 때마다
   아래 내용이 밀려 글이 통째로 튄다. 자리는 처음부터 잡아 두고 보이기만 바꾼다.
   ★ `<tr>` 에는 transform 이 안 먹는다(표 행은 이동 대상이 아니다) — 그래서
     올라오는 움직임 없이 opacity 만 쓴다. 종류마다 다르게 하면 표와 불릿이
     서로 다른 리듬으로 떠서 산만하다. */
.m-html .hb{opacity:0;transition:opacity .34s}
.m-html .hb.on{opacity:1}
/* 인쇄·PDF 에는 시간이 없다 — 다 보여야 한다. 안 그러면 안 뜬 줄이 통째로 빈다. */
@media print{.m-html .hb{opacity:1}}
.sdots{position:absolute;left:50%;bottom:-16px;transform:translateX(-50%);
  display:flex;gap:5px}
.sdots i{width:5px;height:5px;border-radius:50%;background:#d6cfc4;transition:background .2s}
.sdots i.on{background:#9a4d33}
.m-todo{display:grid;place-items:center;aspect-ratio:16/9;border-radius:10px;
  background:#efebe4;color:#948e86;font-size:12px;
  box-shadow:inset 0 0 0 1px rgb(40 34 28/.08)}

/* 자막 — 발표 중에는 켜 두고, 화면만 보여 줄 때는 C 로 끈다 */
#cc{position:fixed;left:50%;bottom:52px;transform:translateX(-50%);
  max-width:min(900px,86vw);padding:9px 18px;border-radius:8px;
  background:rgb(31 29 26/.86);color:#fff;font-size:clamp(14px,1.5vw,19px);
  line-height:1.5;text-align:center;text-wrap:balance;
  opacity:0;transition:opacity .12s;pointer-events:none}
#cc.on{opacity:1}

/* 시작 — 첫 제스처. 이게 없으면 1장 음성이 브라우저에 막힌다. */
#gate{position:fixed;inset:0;display:grid;place-items:center;z-index:9;
  background:rgb(247 245 241/.94);backdrop-filter:blur(3px)}
#gate.off{display:none}
.gate-in{display:grid;justify-items:center;gap:10px}
.gate-in>button{margin:0}
#gate button.alt{background:#efebe4;color:#6b6660;box-shadow:none}
#gate button.alt:hover{background:#e6e0d7}
#gate button{display:inline-flex;align-items:center;gap:10px;
  padding:14px 28px;border:0;border-radius:99px;background:#9a4d33;color:#fff;
  font-family:inherit;font-size:16px;font-weight:700;cursor:pointer;
  box-shadow:0 6px 24px rgb(154 77 51/.28)}
#gate p{margin-top:16px;color:#948e86;font-size:12.5px;text-align:center}

/* 진행 — 레인이 번호에 섞여 있으므로 색 눈금이 갈래를 보여 준다 */
#bar{position:fixed;left:0;right:0;bottom:0;height:3px;display:flex;gap:1px;background:#efebe4;z-index:8}
#bar i{flex:1;background:#e0dad1;transition:background .15s;cursor:pointer}
#bar i.done{background:var(--c)}
/* ★ 오른쪽 **위**다(2026-08-14).
   먼저 왼쪽에서 오른쪽으로 옮겼던 이유는 그대로 살아 있다 — .s-shots 장은 흰
   카드를 왼쪽에 붙이므로 왼쪽 아래에 두면 카드 위에 겹쳐 표를 가린다. 이번에는
   거기서 한 번 더 위로 올린다: **우하단이 아바타(말하는 사람) 자리**가 되기
   때문이다(#av). 그 자리에 버튼이 있으면 나중에 아바타가 버튼을 깔고 앉는다.
   진행바(#bar)는 화면 아래 가로 전체를 3px 로 지나갈 뿐이라 그대로 둔다. */
/* ★ **한 줄로 묶는다**(2026-08-29) — 진행 글자를 오른쪽 위 자동재생 단추
     앞으로 옮긴다. 진행 표시(#hud)를 단추 왼쪽에 붙이는데, 단추 글자가 「자동 재생」·
     「멈춤」·「이어서」로 바뀌며 **폭이 달라진다.** 그래서 #hud 를 고정 좌표로
     밀어 넣지 않고 둘을 flex 한 줄에 세운다 — 단추가 넓어지면 글자가 저절로
     왼쪽으로 밀린다. #pz 가 `hidden` 일 때는 #hud 만 오른쪽 끝에 남는다. */
#topr{position:fixed;right:18px;top:18px;z-index:8;
  display:flex;align-items:center;gap:10px}
#pz{padding:6px 14px;border:0;border-radius:99px;
  background:rgb(31 29 26/.62);color:#fff;backdrop-filter:blur(6px);
  font-family:inherit;font-size:12px;font-weight:700;cursor:pointer}
#pz:hover{background:rgb(31 29 26/.86)}
#pz.on{background:#9a4d33}
body.one #pz{display:none}
/* 배경음악 토글 — 재생 버튼 바로 아래. 발표 중에 손이 닿아야 한다.
   ★ button 이라 클릭 네비게이션에서 이미 제외된다(아래 click 핸들러의 closest). */
#bgmb{position:fixed;right:18px;top:56px;z-index:8;width:30px;height:30px;
  padding:0;border:0;border-radius:99px;background:rgb(31 29 26/.5);color:#fff;
  backdrop-filter:blur(6px);font-size:13px;line-height:1;cursor:pointer;opacity:.55}
#bgmb:hover{opacity:1}
#bgmb.on{background:#9a4d33;opacity:1}
body.one #bgmb{display:none}
#hud{font-size:11px;color:#948e86;white-space:nowrap;
     font-variant-numeric:tabular-nums;text-align:right}
/* 아바타 자리 — **비워만 둔다.** 나중에 말하는 사람이 여기 들어온다.
   본문은 1920 중 왼쪽 1536px 을 쓰므로 오른쪽이 이미 비어 있고, 그 아래쪽이다.
   ★ 고정 px 이 아니라 %/비율로 잡는다 — 영상은 1920×1080 으로 찍히는데 편집
     화면 iframe 은 더 좁은 폭으로 그린 뒤 줄여 보여 준다. px 로 두면 두 자리가
     어긋나 미리보기에서 본 위치와 영상 위치가 달라진다.
   ★ pointer-events:none — 아직 아무것도 없으니 클릭을 먹지 않아야 한다. */
/* 폭 12.1% = 1920 기준 232px — 본문(1688px)이 왼쪽 끝에 붙고 남긴 바로 그 칸이다.
   본문 폭과 **한 몸**이라 한쪽을 바꾸면 여기도 같이 바꿔야 한다. */
#av{position:fixed;right:0;bottom:0;width:12.1%;aspect-ratio:3/4;z-index:7;
    pointer-events:none}
body.one #av{display:none}
/* ★ 맨몸 모드 — 우상단 단추를 통째로 감춘다(2026-08-14). 재생 단추·안내
   글자가 본문 오른쪽 끝과
   겹쳐, 이 화면을 그대로 담을 때 같이 찍힌다.
   `?bare=1` 로 시작하거나 재생 중 **H** 로 껐다 켠다 — 띄워 놓고 손을 뻗어
   끌 수 있어야 하므로 글쇠가 필요하다. 영상 렌더링 화면(`/mp4`)의 미리보기가
   `?bare=1` 로 연다.
   진행바(#bar)는 남긴다. 화면 맨 아래 3px 이라 본문을 가리지 않는다. */
body.bare #pz,body.bare #bgmb,body.bare #hud{display:none}
#hud b{color:#6b6660}
#hud kbd{font:inherit;color:#b3aca3}
#hud em{font-style:normal;font-weight:800;color:#9a4d33}
#hud em.p{color:#b01f41}
/* 한 장만 보는 자리 — 진행바·HUD·자막층은 군더더기다 */
body.one #bar,body.one #hud,body.one #cc{display:none}
body.one .s{padding:5vh 5vw}
/* …대신 자막을 통째로 깔아 둔다. 발표본에서는 안 나온다(재생 중에 #cc 가 맡는다) */
.cc-st{display:none}
body.one .cc-st{display:block;position:absolute;left:5vw;right:5vw;bottom:2.2vh;
  font-size:15px;line-height:1.6;color:#6f675e;text-align:center;
  border-top:1px solid rgba(0,0,0,.07);padding-top:10px}
@media print{
  body{overflow:visible}
  #deck{height:auto}
  .s{position:static;opacity:1;pointer-events:auto;page-break-after:always;
     min-height:100vh;padding:8vh 8vw}
  #bar,#hud,#cc,#gate{display:none}
}
"""

JS = r"""
const D=window.__DECK__||{cues:{}};
const slides=[...document.querySelectorAll('.s')];
const bar=document.getElementById('bar'),hud=document.getElementById('hud'),
      cc=document.getElementById('cc'),gate=document.getElementById('gate'),
      pz=document.getElementById('pz');
slides.forEach(s=>{const b=document.createElement('i');
  b.style.setProperty('--c',getComputedStyle(s).getPropertyValue('--lane'));bar.appendChild(b);});
const ticks=[...bar.children];
ticks.forEach((t,k)=>t.onclick=()=>go(k));
/* ★ 시작 장은 **쿼리 먼저, 해시 나중.**
   해시만 다른 URL(`#2` → `#5`)은 브라우저가 문서를 다시 읽지 않아서, 편집 화면의
   iframe 이 앞 장을 그대로 보여 준다(머리글은 2인데 안은 5인 상태가 실제로 났다).
   쿼리는 URL 자체가 달라지므로 항상 새로 읽힌다. */
const _p=new URLSearchParams(location.search);
const _q=_p.get('n');
/* ★ 편집 화면의 iframe(=한 장만 보는 자리)에서는 시작 문을 띄우지 않는다.
   거기서는 소리를 낼 일이 없고, 문이 면을 가려서 정작 볼 것을 못 본다.
   `?n=` 이 붙어 있다는 것 자체가 "한 장만 본다" 는 뜻이다. */
const _one=_q!=null;
/* ★ `?at=` — **그 시각의 화면을 정지 상태로** 그린다. 영상 프레임을 찍을 때
   (tools/render_frames.mjs) 와 수정 화면에서 "9초에 어떻게 보이나" 를 확인할 때
   쓴다. 애니메이션이 아니라 결과 상태라서, 찍는 쪽이 몇 초를 기다릴 필요가 없다. */
const _atQ=_p.has('at')?parseFloat(_p.get('at')):null;
// 맨몸 모드 — 우상단 단추를 감춘다. `?bare=1` 로 시작하거나 H 로 껐다 켠다.
if(_p.get('bare')==='1')document.body.classList.add('bare');
// 한 장만 보는 자리 — 진행바·HUD·자막층은 군더더기다
if(_one){document.body.classList.add('one');}
/* ★ `?n=` 은 **원래 번호**(src_no)다 — 순번이 아니다. 뺀 장이 있으면 조립이
   1부터 다시 번호를 매기므로(s8_assemble), 순번으로 읽으면 뺀 장 뒤부터 편집
   화면과 미리보기가 한 장씩 어긋난다. 먼저 src 로 찾고, 없으면 순번으로 본다
   (뺀 장이 없던 시절에 만든 링크·북마크가 그대로 돌아야 한다). */
const _want=parseInt(_q||location.hash.slice(1))||1;
const _bySrc=slides.findIndex((s)=>parseInt(s.dataset.src)===_want);
let i=_bySrc>=0?_bySrc:Math.max(0,Math.min(slides.length-1,_want-1));
// ★ 기본값을 꺼짐으로 바꿨다(2026-08-14) — 자막을 몰라서 못 끄는
//   사람(동료 데모, SME)에게는 그냥 안 뜨는 게 낫다. 궁금하면 C로 켠다
//   (안내는 화면 우하단 "C 자막"에 이미 있다). 지운 게 아니라 기본값만
//   뒤집은 거라 기능은 그대로 산다.
let started=false, subs=false, timer=null, lead$=null;

/* ★ 자동 넘김 — **내레이션이 끝나면 다음 장으로.**
   사람 없이 처음부터 끝까지 도는 발표가 필요할 때 켠다(강의장에 걸어 두기 · 검토
   받기). 중간에 ←/→ 로 끼어들 수도 있다(수동 조작이 들어오면 자동은 그 장에서
   멈추지 않는다). mp4 파일이 필요하면 이 화면을 담는 게 아니라 `/mp4` 에서 굽는다.

   음성이 없는 장은 자막 글자수로 시간을 잡는다. 영상만 있는 장은 영상 길이. */
let auto=new URLSearchParams(location.search).get('auto')==='1';
let hold=null, holdH=null, paused=false;
const DEFAULT_HOLD=4200, PER_CHAR=170, TAIL=600;
/* 원고 장에서 **마지막 줄이 뜬 뒤** 더 머무는 시간. 마지막 줄이 흔히 그림이나
   결론이라, 뜨자마자 넘기면 그걸 보라고 순서를 정한 의미가 없어진다
   (2026-08-14 실측: TAIL 만 두니 1.1초 뒤에 넘어갔다). */
const LAST_HOLD=1600;

/* ── 배경음악 ──────────────────────────────────────────────────────────
   ★ **자동 재생으로 시작했을 때만** 저절로 튼다. 손으로 넘기며 설명하는
     자리에서는 음악이 말을 방해하기만 한다. ♪ 버튼과 M 키로 언제든 켤 수 있다.
   ★ 내레이션이 나올 동안은 볼륨을 낮춘다(덕킹). 이게 없으면 말이 안 들린다.
     볼륨을 뚝 끊으면 그것대로 거슬려서 짧게 램프를 준다.
   ★ `onended=` 대입은 쓰지 않는다 — armAuto 가 이미 그 자리를 쓰고 있어서
     서로 덮어쓴다. addEventListener 로만 붙인다. */
const bgmEl=document.getElementById('bgm'),
      bgmBtn=document.getElementById('bgmb');
const BG=(D.bgm||{on:false,vol:.2,duck:.06});
let bgmWant=false, ducked=false, fade$=null, duckT=null;

function bgmFade(to,ms){
  if(!bgmEl)return;
  clearInterval(fade$);
  const from=bgmEl.volume, steps=Math.max(1,Math.round(ms/25));
  let k=0;
  fade$=setInterval(()=>{
    k++;
    bgmEl.volume=Math.min(1,Math.max(0,from+(to-from)*k/steps));
    if(k>=steps)clearInterval(fade$);
  },25);
}
function applyDuck(on){
  if(!bgmEl||ducked===on)return;
  /* ★ 음악이 꺼져 있어도 **상태는 따라간다.** 안 그러면 말이 나오는 도중에 M 으로
     켰을 때 원래 볼륨으로 튀어나와 그 장의 내레이션을 덮는다. */
  ducked=on;
  if(bgmWant)bgmFade(on?BG.duck:BG.vol,on?220:700);
}
function bgmDuck(on){
  /* ★ 올리는 것만 **늦춘다.** 자동 재생에서는 한 장이 끝나고 다음 장이 곧바로
     말을 시작하는데, 끝나자마자 음악을 올리면 장마다 부풀었다 꺼졌다 해서
     내레이션보다 그 출렁임이 더 귀에 걸린다. 잠깐 기다렸다가, 그 사이에 다음
     말이 시작되면 올리지 않는다. */
  clearTimeout(duckT);
  if(on){ applyDuck(true); return; }
  duckT=setTimeout(()=>applyDuck(false),900);
}
function bgmSet(on){
  if(!bgmEl)return;
  bgmWant=on;
  if(bgmBtn)bgmBtn.classList.toggle('on',on);
  if(on){
    bgmEl.volume=0;
    bgmEl.play().catch(()=>{});
    bgmFade(ducked?BG.duck:BG.vol,600);
  }else{
    clearInterval(fade$);
    bgmEl.pause();
  }
}
if(bgmBtn)bgmBtn.onclick=()=>bgmSet(!bgmWant);

function holdMs(sec){
  const no=sec.dataset.no, cues=D.cues[no]||[];
  /* ★ 원고 장은 **마지막 줄이 뜬 뒤까지** 머문다. 안 그러면 28초에 뜨기로 한
     줄이 나오기도 전에 다음 장으로 넘어가서, 사람이 시각을 정해 둔 의미가 없다.
     자막이 있으면 둘 중 늦은 쪽을 기다린다. */
  const last=htmlLastMs(sec);
  if(cues.length) return Math.max(cues[cues.length-1][1]*1000, last)+TAIL;
  if(last) return last+TAIL+LAST_HOLD;
  /* 대본이 없는 장 — 글자 수로 어림한다. ★ `.txt` 만 본다. 예전엔 없으면 장
     전체(`sec`)를 봤는데, 원고 장은 본문 글자가 통째로 거기 들어 있어서 어림값이
     늘 20초 상한에 붙어 버린다(원고 장은 위에서 이미 돌아 나간다 — 여기 오는
     것은 줄이 하나도 없는 장뿐이다). */
  const t=(sec.querySelector('.txt')||{}).textContent||'';
  return Math.max(DEFAULT_HOLD, Math.min(20000, t.replace(/\s/g,'').length*PER_CHAR));
}
/* ★ 발표가 **끝나는 자리.** 예전에는 마지막 장에서 armAuto 가 그냥 빠져나가서,
   아무 일도 일어나지 않았다 — 배경음악은 `loop` 라 영원히 돈다(2026-08-14:
   "렌더링 끝에서 계속 음악 나오는데 어떻게 해요?"). 마지막 장의 말이 끝나면
   음악을 2.2초에 걸쳐 내리고 세운다. */
/* 마무리 — 말이 끝나면 **음악을 한 번 올렸다가 내린다.** 그냥 뚝 끊으면 끝인지
   멈춘 건지 알 수 없다. 올라가는 소리가 "이제 끝입니다" 를 말해 주고, 내려가는
   동안 마지막 화면을 잠깐 더 보여 준다(2026-08-14). */
const OUTRO_UP=1200, OUTRO_HOLD=2600, OUTRO_DOWN=1800;

function endDeck(){
  auto=false;
  clearTimeout(hold); clearTimeout(holdH);
  document.body.classList.add('ended');
  paint();
  // 음악이 없으면 할 일이 없다 — 마지막 화면이 그대로 남는 것이 곧 끝이다
  if(bgmEl&&bgmWant){
    clearTimeout(duckT); ducked=false;          // 말이 끝났으니 덕킹을 푼다
    bgmFade(Math.min(1,BG.vol*1.8),OUTRO_UP);
    setTimeout(()=>{
      bgmFade(0,OUTRO_DOWN);
      setTimeout(()=>{
        clearInterval(fade$); bgmEl.pause(); bgmWant=false;
        if(bgmBtn)bgmBtn.classList.remove('on');
      },OUTRO_DOWN+200);
    },OUTRO_UP+OUTRO_HOLD);
  }
}

function armAuto(sec){
  clearTimeout(hold); clearTimeout(holdH);
  if(!auto||paused) return;
  const last=i>=slides.length-1;
  const m=media(sec);

  /* ★ **영상과 음성 중 긴 쪽을 기다린다.**
     음성이 끝났다고 넘기면 영상이 돌던 중에 잘린다. 반대로 영상만 보면 영상이
     짧은 장에서 말이 잘린다. 둘 다 끝나야 다음 장이다.
     한쪽만 있는 장은 그 하나만 기다린다. */
  /* ★ 원고 장의 **마지막 줄**도 기다린다. 사람이 손으로 "이 줄은 40초에" 라고
     정해 뒀는데 음성이 30초에 끝나면, 그 줄은 뜨지도 못하고 다음 장으로 넘어간다.
     시각을 정할 수 있게 만들어 놓고 그 시각을 안 지키면 만든 의미가 없다. */
  const lastH=htmlLastMs(sec);
  const needA=!!m.a, needV=!!(m.v&&m.v.dataset.end), needH=lastH>0;
  let doneA=!needA, doneV=!needV, doneH=!needH;
  const tick=()=>{ if(auto&&!paused&&doneA&&doneV&&doneH) setTimeout(()=>{
    if(!auto||paused) return;
    // 마지막 장이면 다음이 없다 — 넘기는 대신 마무리한다
    if(last) endDeck(); else go(i+1);
  },450); };

  if(needA){ m.a.onended=()=>{ doneA=true; tick(); }; }
  // 마지막 줄이 뜨자마자 넘기지 않는다 — 뜬 것을 읽을 시간이 필요하다(실측:
  // TAIL 만으로는 1.1초 뒤에 넘어가서 마지막 그림을 못 봤다). holdMs 와 같은 값.
  if(needH){ holdH=setTimeout(()=>{ doneH=true; tick(); }, lastH+TAIL+LAST_HOLD); }

  if(needV){
    const st=parseFloat(m.v.dataset.start||0), en=parseFloat(m.v.dataset.end||0),
          sp=parseFloat(m.v.dataset.speed||1);
    const cues=D.cues[sec.dataset.no]||[];
    const lead=cues.length>1?Math.min(cues[0][1]*1000,6000):600;   // 소개 문장만큼 늦게 뜬다
    hold=setTimeout(()=>{ doneV=true; tick(); },
                    Math.max(1200,(en-st)/sp*1000+lead+TAIL));
  }

  /* 텍스트만 있는 장 — 자막 길이로 잡는다.
     ★ `needH` 를 빼야 한다. 줄 등장이 있는 장은 위 holdH 가 이미 넘김을 맡는데,
       여기서 또 타이머를 걸면 **둘 다 넘겨서 한 장을 건너뛴다**(holdH 가 넘긴
       뒤 900ms 후에 이 타이머가 한 번 더 go(i+1) 를 부른다). */
  if(!needA&&!needV&&!needH){
    hold=setTimeout(()=>{ if(auto&&!paused) go(i+1); }, holdMs(sec));
  }
}

function media(s){return {a:s.querySelector('audio.na'),v:s.querySelector('video')};}

/* ★ 캡처 이미지가 화면보다 길면(표가 긴 장 등) 원래 크기 그대로 얹다가
   화면 밑으로 잘려 나갔다 — 배경이 한 톨도 안 보이니 "잘렸다"와 "다 안
   보여준다"를 구분할 수 없다(2026-08-13). 그래서 이미지가 시작하는
   지점부터 화면 끝까지 남는 높이를 재서, 그보다 크면 **비율 그대로 축소**
   한다(자르지 않는다) — 그러면 밑에 배경이 최소 BOTTOM_GAP 만큼은 항상
   보이고, 화면에 맞는 장은 원래 크기(100%) 그대로다. */
const SHOT_BOTTOM_GAP=18;
function fitShot(sec){
  if(!sec||!sec.classList.contains('s-shots'))return;
  /* ★ 전면 갈래는 건드리지 않는다(2026-08-29). 그림이 화면을 통째로 덮는데
     아래 maxHeight 계산이 18px 을 더 깎아 바닥에 아이보리 띠가 생긴다.
     이 장들은 CSS 가 이미 다 잡았다(`.s-swapfull` · `.s-picfull`).
     ★ 옛 갈래(`.s-pic`)는 일부러 그대로 둔다 — 지난 영상과 한 픽셀도 달라지면
       안 된다. 거기도 18px 이 깎이지만 그것이 지금까지 나간 화면이다. */
  if(sec.classList.contains('s-swapfull')||sec.classList.contains('s-picfull'))return;
  const img=sec.querySelector('.m-shots img');
  const fig=sec.querySelector('.m-shots');
  if(!img||!fig)return;
  const top=img.getBoundingClientRect().top;
  const avail=Math.round(innerHeight-top-SHOT_BOTTOM_GAP);
  img.style.maxHeight=Math.max(40,avail)+'px';
  // ★ 카드를 남는 높이까지 강제로 늘리는 건 되돌린다(2026-08-14). 제일 긴
  //   장이 꽉 차는 건 좋은데, 내용이 짧은 장까지 억지로 늘리면 빈 흰 종이만
  //   커 보인다. 원래 그대로 — 카드는 이미지 자기 키만큼만.
  //   내용이 화면 높이에 가까운 장은 원래도 거의 꽉 찬다. 이음매(그림자)만
  //   없앤 상태로 둔다(아래 .s-shots .m-shots img 의 box-shadow:none).
}
/* ── 원고 장(html) — 크기 맞추기 · 줄 등장 ─────────────────────────────
   비율은 CSS 주석(.m-html)에 적어 둔 그 값이다: 944px 폭에서 배치하고 1.62712 배.
   여기서는 **화면 폭에서 직접 잰다** — 미리보기 창이 1920 이 아닐 수도 있어서,
   상수를 박아 두면 그때 캡처와 어긋난다. 상자 폭 ÷ 944 가 곧 배율이다. */
const HTML_SRC_W=944;
function fitHtml(sec){
  if(!sec)return;
  const box=sec.querySelector('.m-html'); if(!box)return;
  /* ★ `.doc` 을 **이름으로** 찾는다(예전엔 firstElementChild 였다). 그림으로
     갈아끼운 장(.m-swap)은 첫 자식이 `<img>` 라, 자리로 집으면 그림에 944px
     배율을 먹여 통째로 찌그러진다. 그 장은 CSS(aspect-ratio)가 알아서 맞춘다. */
  const doc=box.querySelector(':scope>.doc'); if(!doc)return;
  doc.style.transform='none';            // 재려면 먼저 풀어야 한다
  box.style.height='auto';
  const nat=doc.scrollHeight;            // 944px 폭에서의 실제 높이
  let k=box.clientWidth/HTML_SRC_W;
  const avail=Math.round(innerHeight-box.getBoundingClientRect().top-SHOT_BOTTOM_GAP);
  // 한 화면을 넘칠 때만 줄인다 — 자르지 않는다(fitShot 과 같은 원칙).
  if(nat*k>avail) k=avail/Math.max(nat,1);
  doc.style.transform='scale('+k+')';
  /* ★ transform 은 배치 높이에 기여하지 않는다 — 상자 높이를 직접 넣어야 한다.
     안 넣으면 화면엔 멀쩡히 보이는데 좌표를 재면 height:0 이다. `.m-shots` 에서
     똑같은 사고가 있었다(2026-08-14 실측). */
  box.style.height=Math.ceil(nat*k)+'px';
}

let htmlT=[], htmlT0=0, htmlAcc=0;
function htmlAts(box){
  try{return JSON.parse(box.dataset.at||'[]');}catch(e){return [];}
}
/* 줄을 시각에 맞춰 띄운다.
   음성이 있으면 아래 go() 의 100ms 시계(showCue 와 같은 타이머)가 맡는다 —
   `audio.currentTime` 이 유일하게 멈춤·되감기를 따라오는 시계다. 음성이 없는
   장만 여기서 타이머로 돈다(armShots 가 쓰는 방식 그대로).
   ★ 그 장에서 **흐른 시간을 따로 센다**(htmlAcc). 멈췄다 이어서 할 때 이걸 안
     세면 처음부터 다시 시작해서, 이미 떠 있던 줄이 도로 사라졌다 다시 뜬다. */
function armHtml(sec,resume){
  htmlT.forEach(clearTimeout); htmlT=[];
  if(!sec)return;
  fitHtml(sec);
  const box=sec.querySelector('.m-html'); if(!box)return;
  const bs=[...box.querySelectorAll('.hb')], ats=htmlAts(box);
  /* 한 장만 보는 자리(편집 화면 iframe)와 시작 전에는 **다 보여 준다.**
     거기서는 시간이 흐르지 않아서 안 뜬 줄이 영원히 안 뜬다 — 고친 줄이 화면에
     없으면 고쳤는지 알 수가 없다. `?at=` 이 있으면 그 시각 상태로 굳힌다
     (영상 프레임 촬영이 이걸 쓴다). */
  if(_atQ!=null){bs.forEach((b,k)=>b.classList.toggle('on',(ats[k]||0)<=_atQ));return;}
  if(_one||!started){bs.forEach(b=>b.classList.add('on'));return;}
  if(!resume)htmlAcc=0;
  htmlT0=Date.now();
  if(media(sec).a) return;               // 음성이 있으면 시계가 맡는다
  const el=htmlAcc;
  bs.forEach((b,k)=>{
    const at=(ats[k]||0)*1000;
    if(at<=el)b.classList.add('on');
    else htmlT.push(setTimeout(()=>b.classList.add('on'),at-el));
  });
}
function pauseHtml(){
  if(htmlT0)htmlAcc+=Date.now()-htmlT0;
  htmlT0=0;
  htmlT.forEach(clearTimeout); htmlT=[];
}
/* ★ **켜기만 한다. 끄지 않는다.**
   한 장 안에서 등장은 되돌아가지 않는다 — 뜬 줄이 다시 사라질 이유가 없다.
   장을 넘길 때는 go() 가 통째로 걷으므로 여기서 끌 필요도 없다.
   `toggle` 로 두었더니 이런 일이 났다(2026-08-14 실측): `?n=` 한 장 보기와
   영상 프레임 촬영은 재생을 하지 않아 `currentTime` 이 0에 머무는데, 이 시계는
   100ms 마다 계속 돌아서 **armHtml 이 다 켜 놓은 줄을 0.1초 뒤에 도로 껐다.**
   그래서 영상에 표 안이 텅 빈 채로 구워졌다. */
function showReveal(sec,t){
  const box=sec&&sec.querySelector('.m-html'); if(!box)return;
  const ats=htmlAts(box);
  box.querySelectorAll('.hb').forEach((b,k)=>{
    if((ats[k]||0)<=t) b.classList.add('on');
  });
}
/* 그 장의 마지막 줄이 뜨는 시각(ms) — 자동 넘김이 이보다 일찍 넘어가면 안 된다. */
function htmlLastMs(sec){
  const box=sec&&sec.querySelector('.m-html'); if(!box)return 0;
  const ats=htmlAts(box);
  return ats.length?ats[ats.length-1]*1000:0;
}
addEventListener('resize',()=>{fitShot(slides[i]);fitHtml(slides[i]);});

/* ★ 그림만 있는 장도 **한 번 커졌다 내려온다.**
   영상과 같은 리듬이다 — 소개 문장 동안은 글과 나란히 작게, 그다음 커져서 보여
   주고, 말이 끝나갈 때 다시 내려와 마무리를 듣게 한다.
   그림이 여러 장이면 커져 있는 동안 **대본 시간을 나눠 차례로 넘어간다.** */
let shotT=[];
function armShots(sec){
  fitShot(sec);
  shotT.forEach(clearTimeout); shotT=[];
  const fig=sec.querySelector('.m-shots'); if(!fig)return;
  const imgs=[...fig.querySelectorAll('img')];
  imgs.forEach((im,k)=>im.classList.toggle('on',k===0));
  const dots=[...fig.querySelectorAll('.sdots i')];
  dots.forEach((d,k)=>d.classList.toggle('on',k===0));
  if(!started)return;

  const cues=D.cues[sec.dataset.no]||[];
  const total=(cues.length?cues[cues.length-1][1]:holdMs(sec)/1000)*1000;
  const lead=cues.length>1?Math.min(cues[0][1]*1000,5000):900;   // 소개 문장
  const tail=Math.min(2600,total*0.22);                          // 마무리
  const big=Math.max(1200,total-lead-tail);

  shotT.push(setTimeout(()=>sec.classList.add('vplay'),lead));
  shotT.push(setTimeout(()=>sec.classList.remove('vplay'),lead+big));
  if(imgs.length>1){
    const step=big/imgs.length;
    imgs.forEach((_,k)=>{
      if(!k)return;
      shotT.push(setTimeout(()=>{
        imgs.forEach((im,j)=>im.classList.toggle('on',j===k));
        dots.forEach((d,j)=>d.classList.toggle('on',j===k));
      },lead+step*k));
    });
  }
}

/* 무음 영상 편집을 재생기가 따른다 — 구간 · 배속 · 들어내기.
   파일을 다시 굽지 않으므로 편집 화면에서 본 것과 여기가 정확히 같다. */
slides.forEach(sec=>{
  const v=sec.querySelector('video[data-end]'); if(!v)return;
  const st=parseFloat(v.dataset.start||0), en=parseFloat(v.dataset.end||0),
        sp=parseFloat(v.dataset.speed||1);
  let cuts=[]; try{cuts=JSON.parse(v.dataset.cuts||'[]');}catch(e){}
  v.addEventListener('loadedmetadata',()=>{v.playbackRate=sp;v.currentTime=st;});
  v.addEventListener('timeupdate',()=>{
    if(v.currentTime<st-0.05)v.currentTime=st;
    /* ★ 끝나면 **마지막 프레임에서 멈춘다.** 되감지 않는다 —
       영상이 음성보다 짧으면 남은 말이 끝날 때까지 그 화면이 서 있어야 한다.
       되감아 다시 돌면 같은 장면이 두 번 나가고 발표가 어수선해진다. */
    if(en&&v.currentTime>=en){v.pause();v.currentTime=Math.max(st,en-0.05);return;}
    for(const c of cuts){if(v.currentTime>=c[0]&&v.currentTime<c[1]){v.currentTime=c[1];break;}}
  });
  v.addEventListener('ended',()=>{v.currentTime=Math.max(st,(en||v.duration)-0.05);});
});

function showCue(no,t){
  if(!subs){cc.className='';return;}
  const list=D.cues[no]||[];
  const c=list.find(x=>t>=x[0]&&t<x[1]);
  cc.textContent=c?c[2]:'';
  cc.className=c?'on':'';
}

// 영상은 재생 중에만 커진다 — 시작하면 펼치고 끝나면 접는다
slides.forEach(s=>{
  const v=s.querySelector('video');
  if(!v)return;
  v.addEventListener('play',()=>s.classList.add('vplay'));
  ['ended','pause'].forEach(e=>v.addEventListener(e,()=>s.classList.remove('vplay')));
});

/* 내레이션이 끝나면 음악을 원래대로. **한 번만** 걸어 둔다 — go() 안에서 걸면
   장을 오갈 때마다 같은 핸들러가 쌓인다. */
document.querySelectorAll('audio.na').forEach(a=>{
  a.addEventListener('ended',()=>bgmDuck(false));
});

function go(n){
  const prev=slides[i];
  if(prev){const m=media(prev);if(m.a)m.a.pause();if(m.v)m.v.pause();
           prev.classList.remove('vplay');}
  clearInterval(timer); clearTimeout(lead$); shotT.forEach(clearTimeout); shotT=[];
  htmlT.forEach(clearTimeout); htmlT=[];
  // 떠난 장의 줄은 도로 걷는다 — 되돌아왔을 때 처음부터 다시 떠야 한다.
  if(prev)prev.querySelectorAll('.m-html .hb').forEach(b=>b.classList.remove('on'));
  i=Math.max(0,Math.min(slides.length-1,n));
  slides.forEach((s,k)=>s.classList.toggle('on',k===i));
  ticks.forEach((t,k)=>t.classList.toggle('done',k<=i));
  const no=slides[i].dataset.no;
  paint();
  history.replaceState(null,'','#'+(i+1));
  cc.className='';cc.textContent='';
  const m=media(slides[i]);
  // 말이 나오는 장에서만 음악을 낮춘다. 말 없는 장에서는 원래 볼륨으로 돌린다.
  bgmDuck(!!m.a && started);
  if(started){
    // 영상은 항상 무음이다 — 소리는 내레이션 트랙이 낸다
    if(m.a){m.a.currentTime=0;m.a.play().catch(()=>{});}
    /* ★ 영상은 **작게 시작한다.** 장이 뜨는 순간 화면을 덮으면 소개할 틈이 없다.
       "여섯 기능 중 첫 번째는 이것입니다" 를 말하는 동안은 제목·본문과 나란히
       작게 있다가, 그 문장이 끝나면 그때 커지면서 재생된다.
       기준은 **첫 자막 큐가 끝나는 시각** — 소개 문장 하나가 딱 그것이다. */
    if(m.v){
      m.v.muted=true; m.v.pause();
      m.v.currentTime=parseFloat(m.v.dataset.start||0);
      const cues=D.cues[no]||[];
      const lead=cues.length>1?cues[0][1]*1000:(m.a?1800:600);
      const mine=slides[i];
      lead$=setTimeout(()=>{
        if(slides[i]!==mine) return;        // 그새 넘어갔으면 재생하지 않는다
        m.v.play().catch(()=>{});           // play 이벤트가 .vplay 를 켠다
      }, Math.min(lead, 6000));
    }
  }
  armShots(slides[i]);
  armHtml(slides[i]);
  armAuto(slides[i]);
  if(m.a){
    /* ★ 시계는 **하나뿐이다.** 자막과 줄 등장이 같은 100ms 틱을 나눠 쓴다.
       타이머를 따로 두면 둘이 조금씩 어긋나서, 자막은 넘어갔는데 줄은 아직
       안 뜬 상태가 생긴다. 그리고 `audio.currentTime` 이 유일하게 멈춤·되감기를
       따라오는 시계다 — setTimeout 은 멈추면 그대로 흘러가 버린다. */
    timer=setInterval(()=>{
      showCue(no,m.a.currentTime);
      showReveal(slides[i],m.a.currentTime);
    },100);
  }else if(D.cues[no]&&D.cues[no].length){
    // 음성이 아직 없는 장 — 자막을 첫 줄만 띄워 둔다
    cc.textContent=D.cues[no][0][2];cc.className=subs?'on':'';
  }
}
addEventListener('keydown',e=>{
  if(e.key===' '){
    e.preventDefault();
    /* 자동일 때 Space 는 **멈춤/재개**다. 발표 중 질문을 받으면 세워야 한다.
       자동이 아닐 때는 예전처럼 다음 장으로 넘긴다. */
    if(auto) setPaused(!paused); else go(i+1);
    return;
  }
  if(e.key==='ArrowRight'||e.key==='PageDown'){e.preventDefault();go(i+1);}
  if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();go(i-1);}
  if(e.key==='Home')go(0); if(e.key==='End')go(slides.length-1);
  if(e.key==='c'||e.key==='C'){subs=!subs;if(!subs)cc.className='';}
  if(e.key==='a'||e.key==='A'){setAuto(!auto);}
  if(e.key==='m'||e.key==='M'){bgmSet(!bgmWant);}
  // 맨몸 — 우상단 단추 감추기/보이기. 띄워 놓고 손을 뻗어 끌 수 있어야 한다.
  if(e.key==='h'||e.key==='H'){document.body.classList.toggle('bare');}
});

function setPaused(on){
  paused=on;
  const m=media(slides[i]);
  // 멈추면 음악도 같이 선다 — 질문을 받는 동안 혼자 흐르면 이상하다
  if(bgmEl&&bgmWant){ on?bgmEl.pause():bgmEl.play().catch(()=>{}); }
  // 멈추면 아직 안 뜬 줄도 그 자리에 선다 — 타이머만 걷으면 된다(음성 있는 장은
  // 시계가 멈춘 오디오를 읽으므로 저절로 선다).
  if(on){ clearTimeout(hold); pauseHtml();
          if(m.a)m.a.pause(); if(m.v)m.v.pause(); }
  else  { if(m.a)m.a.play().catch(()=>{}); if(m.v&&slides[i].classList.contains('vplay'))
            m.v.play().catch(()=>{});
          armShots(slides[i]);
          armHtml(slides[i],true);        // 이어서 — 흐른 시간을 이어 센다
  armAuto(slides[i]); }
  paint();
}

function paint(){
  /* ★ 이 단추는 **항상 보인다.** 예전엔 자동일 때만 나타났는데, 자동을 켜는
   * 길이 A 키뿐이라 키를 모르면 영영 못 켰다. 그래서 편집 화면에 "전체 자동
   * 재생" 버튼을 따로 뒀고, 그게 "슬라이드 보기" 와 같은 것으로 보였다.
   * 여기서 켤 수 있으면 버튼은 하나면 된다. */
  if(pz){
    pz.hidden=false;
    pz.textContent=!auto?'▶ 자동 재생':(paused?'▶ 이어서':'❚❚ 멈춤');
    pz.className=(auto&&!paused)?'on':'';
    pz.title=!auto?'내레이션이 끝나면 다음 장으로 — 자동 재생 (A)':'멈춤 (Space)';
  }
  hud.innerHTML='<b>'+(i+1)+'</b> / '+slides.length
    +(auto?(paused?' &nbsp;<em class="p">멈춤</em>':' &nbsp;<em>자동</em>'):'')
    +' &nbsp;<kbd>Space 멈춤 · ← → · A 자동 · C 자막 · H 단추 감추기</kbd>';
}

function setAuto(on){
  auto=on;
  paused=false;
  clearTimeout(hold);
  const u=new URL(location); on?u.searchParams.set('auto','1'):u.searchParams.delete('auto');
  history.replaceState(null,'',u);
  // ★ 음악은 **자동 재생일 때만** 저절로 튼다. 손으로 넘기며 설명하는 자리에서는
  //   음악이 말을 방해하기만 한다. 필요하면 ♪ 나 M 으로 켠다.
  if(BG.on) bgmSet(on);
  if(on){ if(!started){started=true;if(gate)gate.className='off';} go(i); }
  else { clearTimeout(hold); paint(); }
}
if(pz)pz.onclick=()=>{ if(!auto){setAuto(true);setPaused(false);} else setPaused(!paused); };
addEventListener('click',e=>{if(e.target.closest('video,audio,a,button,#bar'))return;
  go(e.clientX<innerWidth*0.28?i-1:i+1);});
let x0=null;
addEventListener('touchstart',e=>x0=e.touches[0].clientX,{passive:true});
addEventListener('touchend',e=>{if(x0==null)return;
  const dx=e.changedTouches[0].clientX-x0;if(Math.abs(dx)>50)go(i+(dx<0?1:-1));x0=null;},{passive:true});

/* 한 장만 보는 자리에서는 서버가 문을 아예 안 그린다. 여기서는 있으면 잇는다. */
if(gate){
  gate.querySelector('[data-go="manual"]').onclick=()=>{started=true;gate.className='off';go(i);};
  gate.querySelector('[data-go="auto"]').onclick=()=>{started=true;gate.className='off';setAuto(true);};
}
/* 자동재생 정책 때문에 첫 제스처가 필요하다. 다만 —
   · 한 장만 보는 자리(`?n=`)  문을 아예 없앤다. 소리도 내지 않는다
   · 음성이 하나도 없는 덱      낼 소리가 없으니 문이 필요 없다
   ★ 배경음악이 있으면 **낼 소리가 있다.** 내레이션이 없다고 문을 닫아 버리면
     첫 제스처가 사라져서 음악이 정책에 막힌다. */
if(!gate){started=false;}
else if(!document.querySelector('audio.na')&&!BG.on){started=true;gate.className='off';}
go(i);
"""


class PreviewResolver:
    """미리보기 — 서버 API 로 미디어를 가리킨다(파일 복사 없음)."""

    def __init__(self, pid: int, root=None) -> None:
        self.pid = pid
        # 파일 수정시각을 읽을 프로젝트 폴더. 없어도 동작한다(주소에 판만 안 붙는다).
        self.root = root

    def asset(self, rel: str) -> str:
        """`/api/…/file/<rel>?v=<수정시각>`.

        ★ **`?v=` 가 이 함수의 존재 이유다**(2026-08-29). 파일 서빙이
          `Cache-Control: public, max-age=600` 을 걸어 두어서, 같은 이름으로 그림을
          갈아 끼우면 브라우저가 **십 분 동안 옛 그림을 물고 있다.** 그림 넣는
          화면은 미리보기 HTML 을 `&t=` 로 새로 부르지만(`static/js/image.js`),
          그 HTML 안의 **그림 주소**는 그대로라 캐시를 그냥 지나쳤다 — 표지를
          바꿔 넣었는데 옛 표지가 계속 떴다.
        ★ 수정시각을 붙이면 **바뀐 파일만** 주소가 달라진다. 안 바뀐 그림은 주소가
          같아 캐시가 그대로 듣는다 — 캐시를 끄는 것(`no-store`)보다 낫다.
          파일을 못 읽으면 그냥 판 없이 낸다(경로가 아직 없는 장이 있다).
        """
        if not rel:
            return ""
        from urllib.parse import quote
        url = f"/api/projects/{self.pid}/file/{quote(rel)}"
        if self.root is not None:
            try:
                url += f"?v={int((self.root / rel).stat().st_mtime)}"
            except OSError:
                pass
        return url

    def video(self, s: Dict[str, Any]) -> str:
        v = s.get("video_id")
        return f"/api/projects/{self.pid}/video/{v}" if v else ""


def cue_map(deck: Dict[str, Any]) -> Dict[str, List[Any]]:
    """장별 자막 큐 `[[start, end, text], …]`. SRT 파일을 다시 읽지 않고
    같은 분할 규칙을 여기서 한 번 더 돌린다 — 산출물이 자기완결이어야 한다."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from vendor.vw_srt import auto_time_cues, split_into_cues

    out: Dict[str, List[Any]] = {}
    for s in deck.get("slides") or []:
        txt = (s.get("narration") or {}).get("srt_text") or ""
        if not txt:
            continue
        dur = float((s.get("audio") or {}).get("sec")
                    or (s.get("narration") or {}).get("est_sec") or 0)
        if dur <= 0:
            continue
        cues = auto_time_cues(split_into_cues(txt), dur)
        out[str(s.get("no"))] = [[round(c.start, 2), round(c.end, 2), c.text] for c in cues]
    return out


def stamp_label_times(slides: List[Dict[str, Any]],
                      cues: Dict[str, List[Any]]) -> None:
    """라벨마다 **몇 초에 뜨는가**를 박는다.

    ★ 시각의 출처는 **LLM 이 정한 `say_i`** 다 — 그 라벨을 몇 번째 문장에서
      말하는가. 그림이 나온 뒤에 픽셀에서 되찾는 것이 아니라 지시문을 쓸 때
      이미 정해져 있다. 여기서는 그 문장 번호를 **실측된 큐 시각**에 맞춰
      초로 바꾸기만 한다.
    ★ `until` 은 다음 라벨이 뜨는 때. 마지막 라벨은 장 끝까지 간다.
    """
    for s in slides:
        lbs = [l for l in (s.get("labels") or []) if (l.get("head") or "").strip()]
        if not lbs:
            continue
        cl = cues.get(str(s.get("no"))) or []
        end = float(cl[-1][1]) if cl else float(
            (s.get("audio") or {}).get("sec") or 0)
        for l in lbs:
            # ★ **`say_i` 는 1부터 센다.** 지시문 프롬프트가 LLM 에게 그렇게
            #   시키고(`llm/prompts/imgprompt.md`: "몇 번째 문장에서 말하는가
            #   (1부터). 어디에도 안 걸리면 0"), 스키마 주석도 그렇다.
            #   그런데 여기서는 **0부터 세는 배열 자리로 읽고 있었다** — 그래서
            #   모든 라벨이 **한 문장씩 늦게** 떴다(2026-09-18 실측, 3장:
            #   「1부의 일」이 "2부의 제목은…" 을 말할 때 떴다).
            #   `s13b_order` 는 이 값을 LLM 에게 **글로** 넘기므로(“{k}번 문장”)
            #   1부터가 맞다 — 고칠 곳은 여기 하나였다.
            i = max(0, int(l.get("say_i") or 0))
            k = i - 1 if i > 0 else 0        # 1부터 → 배열 자리. 0=못 정함 → 첫 문장
            # 문장 번호가 큐 수를 넘으면 마지막 문장에 붙인다 — 라벨을 잃는
            # 것보다 늦게라도 뜨는 편이 낫다
            l["at"] = float(cl[min(k, len(cl) - 1)][0]) if cl else 0.0
        order = sorted(lbs, key=lambda x: x["at"])
        for a, b in zip(order, order[1:]):
            a["until"] = b["at"]
        if order:
            order[-1]["until"] = end or order[-1]["at"]


def _cell_cls(l: Dict[str, Any]) -> str:
    """라벨 한 칸 → 셀색 갈래 클래스. **세 곳이 같은 규칙이어야 한다**
    (`render/hyper.py` · `static/js/labels.js`).

        없음 / "line" → 윤곽(기본)      False → 끔      "box" / True → 판

    ★ `True` 를 판으로 읽는 것은 **옛 값 때문**이다. 판만 있던 하루 동안 저장된
      overrides 가 `cell: true` 를 들고 있을 수 있다 — 그때 뜻이 「판」이었다.
    """
    v = (l or {}).get("cell")
    if v is False:
        return ""
    if v is True or v == "box":
        return " cell-box"
    return " cell-line"


def _labels_html(s: Dict[str, Any]) -> str:
    """배경판 위에 얹는 글. **진짜 텍스트다** — 그림이 그린 글자가 아니다.

    ★ 이것이 11판의 전부다. 10판은 이 글을 이미지 모델이 그림 안에 인쇄했고,
      그러다 한글이 깨졌다(저자 지적 2026-09-14). 여기서는 브라우저가 그리므로
      깨질 수가 없고, 드래그로 선택되며, 모션이 이 요소를 직접 움직일 수 있다.
    ★ 크기는 10판이 이미지 모델에게 요구하던 수치 그대로다 —
      소제목 4%(=그림 높이), 설명은 그 65%.
    """
    lbs = [l for l in (s.get("labels") or []) if (l.get("head") or "").strip()]
    if not lbs:
        return ""
    out = []
    for l in lbs:
        sub = (l.get("sub") or "").strip()
        at = l.get("at")
        attrs = f' data-say="{int(l.get("say_i") or 0)}"'
        if at is not None:
            attrs += f' data-at="{float(at):.2f}"'
        if l.get("until") is not None:
            attrs += f' data-until="{float(l["until"]):.2f}"'
        out.append(
            f'<div class="lbl{_cell_cls(l)}"'
            f' style="--lx:{float(l.get("x", 4)):.2f}%;'
            f'--ly:{float(l.get("y", 14)):.2f}%;'
            f'--lw:{float(l.get("w", 23)):.2f}%"{attrs}>'
            f'<b>{esc(l.get("head") or "")}</b>'
            + (f'<span>{esc(sub)}</span>' if sub else "")
            + '</div>')
    return f'<div class="lbls">{"".join(out)}</div>'


def render_deck(deck: Dict[str, Any], res, *, title: str = "",
                one: bool = False, bgm: str = "", bgm_vol: float = 0.15,
                bgm_duck: float = 0.04) -> str:
    sections = deck.get("sections") or []
    lane_i = {s["id"]: i for i, s in enumerate(sections)}
    slides = deck.get("slides") or []
    total = len(slides)
    proj = deck.get("project") or {}

    for s in slides:
        s["_project"] = proj
    # ★ 큐를 **먼저** 만든다. 라벨 시각이 여기서 나오고, 아래 `__DECK__` 도
    #   같은 것을 쓴다 — 두 번 계산하면 둘이 어긋날 수 있다.
    cues = cue_map(deck)
    stamp_label_times(slides, cues)
    body = "".join(_slide(s, lane_i.get(s.get("section"), 0), total, res) for s in slides)
    for s in slides:
        s.pop("_project", None)

    t = esc(title or proj.get("title") or "덱")
    # ★ 한 장만 보는 자리(편집 화면 iframe)에는 배경음악을 넣지 않는다. 거기서
    #   소리가 나면 스무 장을 훑는 동안 스무 번 음악이 새로 시작한다.
    bg = "" if one else (bgm or "")
    data = json.dumps({"cues": cues,
                       "bgm": {"on": bool(bg), "vol": bgm_vol, "duck": bgm_duck}},
                      ensure_ascii=False)

    return (
        "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{t}</title>"
        "<meta name=\"color-scheme\" content=\"light\">"
        f"<style>{CSS}</style>"
        # 참고 원고의 원래 스타일 — **문서당 한 벌, 페이지에 한 번.** 장마다 넣으면
        # 4KB 짜리가 장 수만큼 복사돼 `dist/` 한 장 파일이 수백 KB 씩 불어난다.
        # 셀렉터는 이미 `.doc` 밑으로 가둬져 있다(tools/split_sections.mjs) —
        # 안 가두면 원고의 `body{}` · `*{max-width:100%}` 가 덱 CSS 를 무너뜨린다.
        + (f"<style>{deck.get('html_style')}</style>" if deck.get("html_style") else "")
        + "</head><body>"
        f"<main id=\"deck\">{body}</main>"
        "<div id=\"cc\"></div>"
        + ("" if one else
           "<div id=\"gate\"><div class=\"gate-in\">"
           "<button type=\"button\" data-go=\"manual\">&#9654; 시작</button>"
           "<button type=\"button\" data-go=\"auto\" class=\"alt\">&#9654;&#9654; 자동 재생</button>"
           "<p>자동 재생은 내레이션이 끝나면 다음 장으로 넘어갑니다 — 사람 없이 끝까지 돕니다.<br>"
           "언제든 ←/→ 로 끼어들 수 있고, A 로 자동을 껐다 켤 수 있습니다.</p></div></div>")
        + (f"<audio id=\"bgm\" loop preload=\"auto\" src=\"{bg}\"></audio>"
           "<button id=\"bgmb\" type=\"button\" title=\"배경음악 켜기/끄기 (M)\">"
           "&#9834;</button>" if bg else "")
        + "<div id=\"topr\"><div id=\"hud\"></div>"
          "<button id=\"pz\" type=\"button\" hidden></button></div>"
        # 아바타(말하는 사람) 자리 — 지금은 **비어 있다.** 자리만 잡아 두면 나중에
        # 채울 때 이 한 줄에 내용만 넣으면 되고, 그 전까지 다른 것이 그 자리를
        # 차지하지 않는다(그래서 재생 단추들을 우상단으로 올렸다).
        "<div id=\"av\"></div>"
        "<div id=\"bar\"></div>"
        f"<script>window.__DECK__={data};</script>"
        f"<script>{JS}</script></body></html>"
    )
