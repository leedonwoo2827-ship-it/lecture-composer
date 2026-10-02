# -*- coding: utf-8 -*-
"""검수지 — 씬 하나에 A4 **가로** 한 장. [그림 | 캡션] 위, [자막 · 읽는 말] 아래.

SME 가 훑으며 **발음이 이상한 곳**과 **글귀가 틀린 곳**을 잡는 자리다. 화면용
덱(`render/slides.py`)과 다르게 짠다 — 한 장 안에서 무엇이 보이고 무엇이
들리는지가 같이 있어야 한다.

★ 「읽는 말」은 `core/honorific.for_speech()` 를 그대로 태운 값이다. 성우에게
  실제로 넘어가는 글이라, 여기서 이상하면 소리도 이상하다.
  실측: A2A → 「A이 A」, xAPI → 「xAPI」(안 바뀜), RAG → 「알에이지」.
★ **자막과 읽는 말을 늘 같이 둔다.** 갈린 줄에만 읽는 말을 붙이면 종이가
  짧아지지만, SME 는 **자막으로 찾는다** — 귀에 걸린 대목을 자막에서 눈으로
  집은 뒤에야 옆 칸을 본다.
★ **원문은 손대지 않는다.** 처음엔 칸을 직접 고치게 했는데, 무엇이 원래였는지가
  흐려지고 토큰을 다시 이어 붙이는 자리에서 공백이 벌어져 **아무것도 안 고쳤는데
  383곳이 바뀐 것으로** 세졌다. 지금은 줄마다 **메모 칸**만 연다 — PDF 주석과
  같은 결이다.
★ 메모 모음·재생기는 **A4 밑**에 두고 인쇄에서 뺀다. SME 에게 보내는 PDF 는
  고치기 전이라 어차피 비어 있다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Callable, Dict

from core import honorific
from render.hyper import _cell_cls
from render.slides import cue_map, esc

TOK = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*|[가-힣]+|\S")


def mmss(v: float) -> str:
    v = max(0.0, float(v or 0))
    return f"{int(v // 60)}:{int(v % 60):02d}"


def mark(sub: str, spk: str) -> tuple:
    """자막 / 읽는 말 — **달라진 조각만** 물들인다.

    ★ **원문을 글자 그대로 다시 쓴다.** 처음엔 토큰을 쪼갰다가 공백으로 이어
      붙였는데, 그러자 「18장_2030년의」가 「18 장 _ 2030 년의」로 벌어졌다.
      그래서 토큰의 **자리**만 쓰고 글자는 원문에서 잘라 온다 — 이어 붙이면
      원문과 한 글자도 안 다르다.
    """
    a = [(m.group(), m.start(), m.end()) for m in TOK.finditer(sub)]
    b = [(m.group(), m.start(), m.end()) for m in TOK.finditer(spk)]
    ops = SequenceMatcher(None, [x[0] for x in a], [x[0] for x in b]).get_opcodes()
    A = B = ""
    ca = cb = 0
    for tag, i1, i2, j1, j2 in ops:
        ea = a[i2 - 1][2] if i2 > i1 else ca
        eb = b[j2 - 1][2] if j2 > j1 else cb
        xa, xb = sub[ca:ea], spk[cb:eb]
        if tag == "equal":
            A += esc(xa)
            B += esc(xb)
        else:
            A += f'<u class="hit">{esc(xa)}</u>' if xa else ""
            B += f'<u class="hit">{esc(xb)}</u>' if xb else ""
        ca, cb = ea, eb
    return A + esc(sub[ca:]), B + esc(spk[cb:])


CSS = """
/* ★ **A4 가로**다. 슬라이드가 16:9 라 세로 종이에 앉히면 그림이 작아지고
   아래가 표로만 길어진다. 가로로 눕히면 그림을 크게 두고 대사를 넓게 깔 수
   있다 — SME 는 「그림을 보며 대사를 훑는」 일을 한다. */
@page { size: A4 landscape; margin: 9mm 10mm; }
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font-family:"Pretendard","Malgun Gothic",sans-serif;
  color:#1f2430;font-size:8.6pt;line-height:1.45;background:#f4f2ee}
.sheet{width:277mm;min-height:191mm;margin:0 auto 6mm;background:#fff;
  page-break-after:always;display:flex;flex-direction:column}
@media print{body{background:#fff}.sheet{margin:0}}
@media screen{.sheet{box-shadow:0 1px 10px rgba(0,0,0,.14);padding:7mm 8mm}}

.hd{display:flex;align-items:baseline;gap:8px;border-bottom:1.4pt solid #1F4E79;
  padding-bottom:1.8mm;margin-bottom:2.6mm;flex:0 0 auto}
.hd .ttl{font-size:12pt;font-weight:800;letter-spacing:-.02em;color:#9a4d33;
  margin:0;word-break:keep-all;flex:1;min-width:0}
.hd .bk{font-size:7.6pt;color:#9a958a;white-space:nowrap}
.hd .ed{font-size:7pt;color:#b4ada0;white-space:nowrap}
@media print{.hd .ed{display:none}}
.hd .no{font-weight:800;color:#1F4E79;font-size:10pt;
  font-variant-numeric:tabular-nums;white-space:nowrap}

/* ★ 위는 **그림 | 캡션(설명·좌표)**, 아래는 **자막 · 읽는 말**이다.
   그림을 보며 글귀를 맞추는 일과, 소리를 들으며 대사를 훑는 일은 서로 다른
   일이다 — 가로로만 나란히 두면 눈이 두 번 왕복한다. */
/* ★ **한 씬이 A4 두 장이다.** 1쪽은 그림만 — 가로 277mm 에 16:9 면 높이가
   156mm 라 종이를 거의 꽉 채운다. 그림 옆에 표를 끼우면 그림이 절반으로
   줄어드는데, 검수는 **그림을 크게 봐야** 하는 일이다.
   2쪽에 캡션과 대사를 몰아 둔다. */
.caps{margin-bottom:3mm}
.sheet.pic .slide{flex:1 1 auto}

.slide{position:relative;width:100%;aspect-ratio:16/9;background:#F6F1E8;
  container-type:size;border:.5pt solid #d9d3c8;overflow:hidden}
.slide>img{position:absolute;inset:0;width:100%;height:100%;
  object-fit:cover;object-position:top center}
.slide .st{position:absolute;left:3.2%;top:2.1%;margin:0;font-size:5.4cqh;
  font-weight:800;letter-spacing:-.035em;color:#9a4d33;
  -webkit-text-stroke:.76cqh #F6F1E8;paint-order:stroke fill}
.lbl{position:absolute;left:var(--lx);top:var(--ly);width:var(--lw);
  word-break:keep-all}
.lbl>b{display:block;font-weight:700;font-size:4cqh;line-height:1.25;
  letter-spacing:-.02em;color:#1F4E79;white-space:pre-wrap}
.lbl>span{display:block;margin-top:.35em;font-weight:500;font-size:2.6cqh;
  line-height:1.42;color:#334155;white-space:pre-wrap}
.lbl.cell-line>b{-webkit-text-stroke:.56cqh #F6F1E8;paint-order:stroke fill}
.lbl.cell-line>span{-webkit-text-stroke:.36cqh #F6F1E8;paint-order:stroke fill}
.lbl.cell-box{box-sizing:content-box;padding:1.2cqh 1.6cqh;margin:-1.2cqh -1.6cqh;
  background:#F6F1E8;border-radius:.9cqh}
/* 그림 위 번호 — 아래 캡션 표와 **같은 번호**다 */
.pin{position:absolute;left:-2cqh;top:-.4cqh;width:3.2cqh;height:3.2cqh;
  border-radius:50%;background:#1F4E79;color:#fff;font-size:2.1cqh;
  font-weight:800;font-style:normal;display:flex;align-items:center;
  justify-content:center}

/* 캡션 표 — 좌표는 %(화면 폭·높이 대비). 「라벨 자리」 화면의 숫자칸과 같은 값 */
.pt{width:100%;border-collapse:collapse;font-size:7.2pt;table-layout:fixed}
.pt th{text-align:left;font-weight:700;color:#8a8577;
  border-bottom:.6pt solid #d9d3c8;padding:0 1mm .8mm}
.pt td{padding:.9mm 1mm;border-bottom:.3pt solid #efeae1;vertical-align:top;
  word-break:keep-all}
.pt .k{width:5mm;text-align:center;font-weight:800;color:#fff;
  background:#1F4E79;border-radius:50%;padding:0;line-height:3.6mm}
.pt thead .k{background:none;color:#8a8577;border-radius:0}
.pt .h{width:20mm;font-weight:700;color:#1F4E79}
.pt .b{color:#5a6472}
.pt .n{width:7mm;text-align:right;font-variant-numeric:tabular-nums;color:#8a8577}
.pt .memo{width:26mm}

/* 대사표 — 한 줄에 [시각 | 자막 | 읽는 말 | 메모] */
.ct{width:100%;border-collapse:collapse;table-layout:fixed;flex:1 1 auto}
.ct th{font-size:7.4pt;font-weight:700;color:#6b7280;text-align:left;
  border-bottom:.8pt solid #c9c2b6;padding:0 1.4mm 1.2mm}
.ct td{padding:1.1mm 1.4mm;border-bottom:.4pt solid #eee9e0;
  vertical-align:top;word-break:keep-all;font-size:8pt}
.ct .c-t{width:11mm;font-size:7.2pt;color:#a8a296;
  font-variant-numeric:tabular-nums}
.ct .c-s{width:34%}
.ct .c-p{width:34%;color:#4a5462;border-left:.4pt solid #f0ece4}
.ct tr.risk td{background:#fffaf6}
.ct tr.risk .c-t{color:#8a3d2a;font-weight:700}
/* 자막과 읽는 말이 **갈린 조각**. 여기만 보면 된다. */
.hit{text-decoration:none;background:#fbe3d8;color:#8a3d2a;font-weight:700;
  padding:0 .4mm;border-radius:1pt}

/* 메모 — 이 종이에서 **유일하게 쓰는 칸**이다. 원문은 손대지 않는다.
   바탕을 살짝 눕혀 「쓸 수 있는 자리」로 읽히게 하고, 인쇄에선 흰 종이가 된다. */
.memo{background:#fcfbf8;border-left:.4pt solid #e9e4db;min-width:22mm}
.memo:focus{outline:1.2pt solid #1F4E79;background:#fff}
.memo.has{background:#fdf1ec;color:#8a3d2a;font-weight:600;
  box-shadow:inset 2pt 0 0 #8a3d2a}
.memo.spot{outline:2pt solid #e0714a;outline-offset:-1pt}
@media print{.memo{background:#fff;box-shadow:none}}

/* ── 넘칠 때 ───────────────────────────────────────────────────────────
   ★ 대사가 길면 한 씬이 두 장을 넘어간다(지금은 제일 긴 씬이 17줄이라 안
     넘치지만, 더 긴 장이 올 수 있다). 그때를 위한 규칙 셋이다.
   ★ `thead` 를 **머리 그룹**으로 두면 다음 장에도 「시각 | 자막 | 읽는 말 |
     메모」가 다시 찍힌다. 없으면 둘째 장부터 어느 칸이 무엇인지 모른다.
   ★ 줄은 **안 쪼갠다.** 한 줄이 장에 걸쳐 잘리면 자막 반쪽만 읽힌다.
   ★ 인쇄에서는 `flex` 를 걷고 보통 블록으로 둔다 — flex 상자는 쪽 나누기를
     제대로 못 하는 브라우저가 있다. */
thead{display:table-header-group}
tr{break-inside:avoid;page-break-inside:avoid}
@media print{
  .sheet{display:block;min-height:0}
  .ct{page-break-inside:auto}
}

.foot{flex:0 0 auto;display:flex;gap:10px;font-size:7.2pt;color:#a8a296;
  border-top:.4pt solid #e9e4db;padding-top:1.4mm;margin-top:2mm}
.foot .r{margin-left:auto}

/* ── A4 **밑에** 붙는 자리 — 화면에서만 쓴다 ───────────────────────────
   SME 에게 보내는 PDF 는 **고치기 전**이라 메모가 비어 있다. 인쇄에 빈 칸을
   끼우면 장마다 종이가 한 장씩 늘 뿐이다. */
@media print{.below,.bar{display:none}}
.below{width:277mm;margin:0 auto 10mm;background:#fff;border-radius:2mm;
  box-shadow:0 1px 10px rgba(0,0,0,.10);padding:5mm 8mm 6mm}
.bh{display:flex;align-items:center;gap:8px;font-size:8.6pt;color:#6b7280;
  border-bottom:.6pt solid #e9e4db;padding-bottom:2mm;margin-bottom:2mm}
.bh b{color:#1F4E79}
.bh .cnt{color:#a8a296}
.bh .cnt.on{color:#8a3d2a;font-weight:700}
.bh audio{height:26px;margin-left:auto}
.bh .noaud{margin-left:auto;font-size:7.6pt;color:#c3bdb2}
.diffs:empty::after{content:"메모가 여기에 쌓입니다.";font-size:8pt;color:#c3bdb2}
.df{display:grid;grid-template-columns:34mm 1fr;gap:2mm 4mm;padding:1.8mm 0;
  border-bottom:.4pt solid #f0ece4;font-size:8.4pt;cursor:pointer}
.df:hover{background:#fbfaf7}
.df .w{color:#8a8577;font-size:7.8pt}
.df .n{color:#8a3d2a;font-weight:700}

/* 떠 있는 바 — 화면에만 */
.bar{position:fixed;right:14px;bottom:14px;z-index:9;display:flex;gap:8px;
  align-items:center;background:#1f2430;color:#fff;border-radius:8px;
  padding:8px 12px;box-shadow:0 4px 18px rgba(0,0,0,.28);font-size:12px}
.bar b{font-variant-numeric:tabular-nums}
.bar button{border:0;border-radius:6px;padding:6px 12px;font:inherit;
  font-weight:700;cursor:pointer;background:#e0714a;color:#fff}
.bar button:disabled{background:#4a4f5a;color:#9aa0aa;cursor:default}
.bar .nv{background:#3a4150;padding:6px 10px}
.bar .dl,.bar .ld{background:#3a4150}
.bar .pos{font-variant-numeric:tabular-nums;color:#9aa0aa;min-width:46px;
  text-align:center}
"""

JS = """
/* 검수지 — **메모만** 모은다.
   ★ 원문은 손대지 않는다. 고쳐 쓰게 했더니 무엇이 원래였는지가 흐려지고,
     토큰을 이어 붙이는 자리에서 공백이 벌어져 아무것도 안 고쳤는데 383곳이
     바뀐 것으로 세졌다. 그래서 **옆에 메모를 다는** 쪽으로 바꿨다.
   ★ 줄바꿈 escape 를 쓰지 않는다 — 이 글은 파이썬 문자열 안에 있어 두 번
     해석되면 진짜 줄바꿈이 되어 문자열이 깨진다. NL 로 만들어 쓴다. */
(function () {
  var NL = String.fromCharCode(10);

  /* ★ **한 번 담아 두지 않는다.** 내려받은 파일을 다시 열면 이 글이 또 도는데,
     그때 미리 담아 둔 목록은 그 문서의 것이 아니다. 셀 때마다 다시 찾는다. */
  function memos() {
    return [].slice.call(document.querySelectorAll(".memo[contenteditable]"));
  }
  function filled() {
    return memos().filter(function (m) { return m.textContent.trim() !== ""; });
  }

  /* ★ **바는 하나뿐이어야 한다.** 내려받은 HTML 에는 찍힐 당시의 바가 그대로
     들어가 있다. 지우지 않으면 파일을 열 때 바가 둘이 되고, 옛 바는 「묶는 중」
     같은 그때의 글자에 멈춰 있어 어느 쪽이 살아 있는지 알 수 없다. */
  document.querySelectorAll(".bar").forEach(function (x) { x.remove(); });

  var cur = -1;
  function show(m) {
    document.querySelectorAll(".spot").forEach(function (x) {
      x.classList.remove("spot");
    });
    m.classList.add("spot");
    m.scrollIntoView({ behavior: "smooth", block: "center" });
    var at = m.dataset.at;
    if (at) {
      var au = document.querySelector(
        ".below[data-s=" + JSON.stringify(m.dataset.s) + "] audio");
      if (au) { try { au.currentTime = parseFloat(at); au.play(); } catch (e) {} }
    }
  }
  function go(n) {
    var f = filled();
    if (!f.length) return;
    cur = (n + f.length) % f.length;
    show(f[cur]);
    bar.querySelector(".pos").textContent = (cur + 1) + " / " + f.length;
  }

  function draw() {
    var f = filled(), by = {};
    memos().forEach(function (m) {
      m.classList.toggle("has", m.textContent.trim() !== "");
    });
    f.forEach(function (m) { (by[m.dataset.s] = by[m.dataset.s] || []).push(m); });
    document.querySelectorAll(".diffs").forEach(function (box) {
      var list = by[box.dataset.s] || [];
      box.innerHTML = "";
      list.forEach(function (m) {
        var d = document.createElement("div");
        d.className = "df";
        var w = document.createElement("span");
        w.className = "w";
        w.textContent = m.dataset.w || "";
        var n = document.createElement("span");
        n.className = "n";
        n.textContent = m.textContent.trim();
        d.appendChild(w);
        d.appendChild(n);
        d.onclick = function () { show(m); };
        box.appendChild(d);
      });
      var cnt = document.querySelector(
        ".cnt[data-s=" + JSON.stringify(box.dataset.s) + "]");
      if (cnt) {
        cnt.textContent = list.length ? "메모 " + list.length + "개" : "메모 없음";
        cnt.classList.toggle("on", !!list.length);
      }
    });
    var n = f.length;
    bar.querySelector("b").textContent = n;
    bar.querySelector(".sv").disabled = !n;
    bar.querySelectorAll(".nv").forEach(function (x) { x.disabled = !n; });
    if (!n) { cur = -1; bar.querySelector(".pos").textContent = "0 / 0"; }
  }

  var bar = document.createElement("div");
  bar.className = "bar";
  bar.innerHTML = "<span>메모 <b>0</b></span>"
    + "<button type=button class=nv data-d=-1>◀</button>"
    + "<span class=pos>0 / 0</span>"
    + "<button type=button class=nv data-d=1>▶</button>"
    + "<button type=button class=ld>검수내역 불러오기</button>"
    + "<button type=button class=dl>HTML 내려받기</button>"
    + "<button type=button class=sv>검수내역 저장</button>";
  document.body.appendChild(bar);
  bar.querySelectorAll(".nv").forEach(function (x) {
    x.onclick = function () { go(cur + Number(x.dataset.d)); };
  });

  /* 저장 — 메모만 담는다. 어디에 달렸는지는 좌표(씬·갈래·번호)로 남긴다. */
  bar.querySelector(".sv").onclick = function () {
    var out = { book: document.title,
                at: new Date().toISOString().slice(0, 19), notes: [] };
    filled().forEach(function (m) {
      out.notes.push({ scene: Number(m.dataset.s), kind: m.dataset.kind,
                       i: Number(m.dataset.i), where: m.dataset.w || "",
                       text: m.textContent.trim() });
    });
    var blob = new Blob([JSON.stringify(out, null, 2)],
                        { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (document.title.split(" ")[0] || "검수") + "-검수내역.json";
    a.click();
  };

  /* 불러오기 — SME 가 보낸 검수내역을 이 화면에 물린다.
     ★ 못 찾은 것을 **조용히 넘기지 않는다.** 장을 잘못 열었거나 그 사이
       대본이 바뀐 것이라, 말해 주지 않으면 몇 줄이 사라진 줄 모른다. */
  var pick = document.createElement("input");
  pick.type = "file";
  pick.accept = ".json,application/json";
  pick.style.display = "none";
  document.body.appendChild(pick);
  bar.querySelector(".ld").onclick = function () { pick.click(); };
  pick.onchange = function () {
    var f = pick.files && pick.files[0];
    if (!f) return;
    var fr = new FileReader();
    fr.onload = function () {
      var j, hit = 0, miss = 0;
      try { j = JSON.parse(fr.result); }
      catch (e) { alert("읽지 못했습니다 — 검수내역 JSON 이 맞습니까?"); return; }
      (j.notes || []).forEach(function (e) {
        var q = ".memo[data-s=" + JSON.stringify(String(e.scene))
              + "][data-kind=" + JSON.stringify(String(e.kind))
              + "][data-i=" + JSON.stringify(String(e.i)) + "]";
        var m = document.querySelector(q);
        if (!m) { miss++; return; }
        m.textContent = e.text;
        hit++;
      });
      draw();
      var msg = "불러왔습니다 — 메모 " + hit + "개";
      if (miss) {
        msg += NL + "못 찾은 것 " + miss + "개 (다른 장이거나 대본이 바뀌었습니다)";
      }
      alert(msg);
      if (hit) go(0);
      pick.value = "";
    };
    fr.readAsText(f, "utf-8");
  };

  /* HTML 내려받기 — 그림을 글자로 바꿔 넣어(data URI) 서버 없이도 열린다.
     ★ **소리는 안 넣는다.** 씬마다 5MB 가 넘어 한 파일이 100MB 를 넘긴다. */
  bar.querySelector(".dl").onclick = async function () {
    var btn = this, was = btn.textContent;
    btn.disabled = true;

    /* ★ **살아 있는 화면을 건드리지 않는다.** 처음엔 여기서 바로 그림 주소를
       바꾸고 소리 재생기를 지웠는데, 내려받고 나면 보던 화면에서 소리가
       사라졌다. 사본을 떠서 그쪽만 손본다. */
    var srcs = [];
    var imgs = [].slice.call(document.images);
    for (var i = 0; i < imgs.length; i++) {
      btn.textContent = "그림 " + (i + 1) + "/" + imgs.length;
      var u = imgs[i].src;
      if (u.indexOf("data:") === 0) { srcs.push(u); continue; }
      try {
        var r = await fetch(u);
        var bl = await r.blob();
        srcs.push(await new Promise(function (ok) {
          var rd = new FileReader();
          rd.onload = function () { ok(rd.result); };
          rd.readAsDataURL(bl);
        }));
      } catch (e) { srcs.push(u); }
    }

    btn.textContent = "묶는 중";
    var clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll(".bar").forEach(function (x) { x.remove(); });
    clone.querySelectorAll("input[type=file]").forEach(function (x) { x.remove(); });
    clone.querySelectorAll(".spot").forEach(function (x) {
      x.classList.remove("spot");
    });
    /* 소리는 안 싣는다 — 씬마다 5MB 가 넘어 한 파일이 100MB 를 넘긴다 */
    clone.querySelectorAll("audio").forEach(function (a) {
      var sp = document.createElement("span");
      sp.className = "noaud";
      sp.textContent = "소리는 앱에서 들으세요";
      a.parentNode.replaceChild(sp, a);
    });
    var ci = clone.querySelectorAll("img");
    for (var k = 0; k < ci.length; k++) {
      if (srcs[k]) ci[k].setAttribute("src", srcs[k]);
    }

    var doc = "<!doctype html>" + clone.outerHTML;
    var blob = new Blob([doc], { type: "text/html;charset=utf-8" });
    var a2 = document.createElement("a");
    a2.href = URL.createObjectURL(blob);
    a2.download = (document.title.split(" ")[0] || "검수지") + "-검수지.html";
    a2.click();
    btn.textContent = was;
    btn.disabled = false;
  };

  document.addEventListener("input", function (e) {
    if (e.target && e.target.classList
        && e.target.classList.contains("memo")) draw();
  });
  draw();
})();
"""


def build(deck: Dict[str, Any], *, img_url: Callable[[str], str],
          audio_url: Callable[[int], str], only: int | None = None,
          pics: bool = True) -> str:
    """덱 → 검수지 HTML. 그림·소리 주소는 부르는 쪽이 준다(서버/파일 둘 다).

    ★ `pics=False` 면 **그림 쪽을 통째로 뺀다.** 검수는 라벨 글귀와 발음을
      잡는 일이라 그림이 없어도 된다. 그림을 글자로 바꿔 넣으면(data URI)
      한 장이 8MB 가 되는데, 빼면 200KB 다 — 메일로 보낼 수 있는 크기다.
      그림이 필요하면 앱의 `/review/{pid}` 를 열면 된다.
    """
    cues = cue_map(deck)
    book = (deck.get("project") or {}).get("title") or ""
    slides = [s for s in (deck.get("slides") or []) if not s.get("drop")]
    total = len(slides)
    if only is not None:
        slides = [s for s in slides if int(s.get("no") or 0) == only]

    P = []
    for i, s in enumerate(slides, 1):
        no = int(s.get("no") or 0)
        cl = cues.get(str(no)) or []

        # ★ **소리를 옆에 둔다.** 발음은 눈으로 못 고른다 — 들어야 안다.
        af = (s.get("audio") or {}).get("file") or ""
        audio = (f'<audio controls preload="none" src="{audio_url(no)}"></audio>'
                 if af else '<span class="noaud">음성 없음</span>')

        img = s.get("image") or ""
        pic = f'<img src="{img_url(img)}" alt="">' if img else ""
        lbs = [l for l in (s.get("labels") or []) if (l.get("head") or "").strip()]

        # 라벨마다 번호를 물린다 — 아래 캡션 표와 같은 번호라 눈으로 바로 잇는다
        lab = "".join(
            f'<div class="lbl{_cell_cls(l)}" style="--lx:{float(l.get("x", 4)):.2f}%;'
            f'--ly:{float(l.get("y", 14)):.2f}%;--lw:{float(l.get("w", 23)):.2f}%">'
            f'<i class="pin">{k}</i><b>{esc(l.get("head") or "")}</b>'
            + (f'<span>{esc(l.get("sub") or "")}</span>'
               if (l.get("sub") or "").strip() else "") + "</div>"
            for k, l in enumerate(lbs, 1))

        def memo(kind: str, k: int, w: str, at: str = "") -> str:
            """이 종이에서 **유일하게 쓰는 칸**. `data-w` 는 어디에 달린 메모인지."""
            a = f' data-at="{at}"' if at else ""
            return (f'<td class="memo" contenteditable="true" spellcheck="false" '
                    f'data-s="{no}" data-kind="{kind}" data-i="{k}" '
                    f'data-w="{esc(w)}"{a}></td>')

        pin_rows = "".join(
            f'<tr><td class="k">{k}</td>'
            f'<td class="h">{esc(l.get("head") or "")}</td>'
            f'<td class="b">{esc(l.get("sub") or "")}</td>'
            f'<td class="n">{float(l.get("x", 4)):.1f}</td>'
            f'<td class="n">{float(l.get("y", 14)):.1f}</td>'
            f'<td class="n">{float(l.get("w", 23)):.1f}</td>'
            f'<td class="n">{int(l.get("say_i") or 0) or "—"}</td>'
            + memo("label", k, f'캡션{k} {l.get("head") or ""}')
            + "</tr>"
            for k, l in enumerate(lbs, 1))
        caps = (f'<table class="pt"><thead><tr><th class="k">#</th>'
                f'<th class="h">소제목</th><th class="b">설명</th>'
                f'<th class="n">x</th><th class="n">y</th><th class="n">폭</th>'
                f'<th class="n">문장</th><th class="memo">메모</th></tr></thead>'
                f'<tbody>{pin_rows}</tbody></table>'
                if lbs else '<div style="color:#b4ada0;font-size:8pt">라벨 없음</div>')

        rows, nrisk = [], 0
        for k, c in enumerate(cl):
            sub = c[2]
            try:
                spk = honorific.for_speech(sub)
            except Exception:                                  # noqa: BLE001
                spk = sub
            A, B = mark(sub, spk)
            risk = "hit" in A
            nrisk += 1 if risk else 0
            rows.append(
                f'<tr class="{"risk" if risk else ""}">'
                f'<td class="c-t">{mmss(c[0])}</td>'
                f'<td class="c-s">{A}</td>'
                f'<td class="c-p">{B}</td>'
                + memo("cue", k, f"{mmss(c[0])} 줄", f"{c[0]:.2f}")
                + "</tr>")
        if not rows:
            rows.append('<tr><td class="c-t"></td><td class="c-s" colspan="3" '
                        'style="color:#b4ada0">읽는 말이 없는 장입니다'
                        '(표지·마무리).</td></tr>')

        # 그림 쪽 — `pics=False` 면 아예 안 만든다
        page1 = (f'''<section class="sheet pic">
  <div class="hd"><h2 class="ttl">{esc(s.get("title") or "")}</h2>
    <span class="bk">{esc(book)}</span>
    <span class="no">{i} / {total}</span></div>
  <div class="slide">{pic}<div class="st">{esc(s.get("title") or "")}</div>{lab}</div>
  <div class="foot"><span>씬 {no} · 라벨 {len(lbs)}개</span>
    <span class="r">다음 장에 캡션과 대사가 있습니다</span></div>
</section>''' if pics else "")

        P.append(page1 + f"""<section class="sheet data">
  <div class="hd"><h2 class="ttl">{esc(s.get("title") or "")}</h2>
    <span class="bk">{esc(book)}</span>
    <span class="ed">메모 칸에만 적어 주세요</span>
    <span class="no">{i} / {total}</span></div>
  <div class="caps">{caps}</div>
  <table class="ct"><thead><tr>
    <th class="c-t">시각</th>
    <th class="c-s">자막 — 화면에 보이는 글</th>
    <th class="c-p">읽는 말 — 성우에게 넘어가는 글</th>
    <th class="memo">메모 — 고칠 것을 여기 적어 주세요</th>
  </tr></thead><tbody>{''.join(rows)}</tbody></table>
  <div class="foot"><span>씬 {no} · 갈린 줄 {nrisk}개</span>
    <span class="r">검수: ______________   날짜: ____________</span></div>
</section>
<div class="below" data-s="{no}">
  <div class="bh"><b>씬 {no}</b> 검수 메모
    <span class="cnt" data-s="{no}">메모 없음</span>{audio}</div>
  <div class="diffs" data-s="{no}"></div>
</div>""")

    return (f'<!doctype html><html lang="ko"><head><meta charset="UTF-8">'
            f'<title>{esc(book)} — 검수지</title><style>{CSS}</style></head>'
            f'<body>{"".join(P)}<script>{JS}</script></body></html>')
