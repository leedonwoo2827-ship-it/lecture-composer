/* 스토리보드 정리 — **말하는 차례와 글자 뜨는 차례를 맞추는 자리.**
 *
 * ★ 왜 있나. 상자를 찍는 자리(지정기)와 대본을 보는 자리(덱)가 갈려 있었다.
 *   대본이 옆에 없으니 **말하는 차례를 모르는 채로** 상자를 찍게 되고,
 *   `remaster` 는 시각이 비면 상자를 위→아래로 띄운다. 그런데 31장 중 **25장**이
 *   한 줄에 상자를 좌우로 둘씩 두고 있어서, 그 정렬로는 차례가 정해지지 않는다
 *   (2026-08-16 실측). 실제로 2.4 장에서 「개발도상국」이 「미국」보다 먼저 떴다.
 *
 * ★ 맞추려는 것은 **초가 아니라 순서**다(2026-08-16) — 초가 딱 맞을 필요는
 *   없지만 상자 순서는 맞아야 한다. 그래서 시각 칸 옆에 **그때 나오는 자막
 *   문장**을 붙인다. 문장이 옆에 있어야 이 상자가 이 말에 뜨는 게 맞는지 읽힌다.
 *
 * ★ 슬라이드는 미리보기(iframe)가 아니라 **영상 스틸**을 깐다. 상자 좌표는
 *   1920×1080 영상 기준인데 미리보기는 브라우저가 다시 레이아웃해서 어긋난다.
 *
 * ★ 저장은 **장 하나씩** 서버로 보낸다. 파일 전체를 화면이 들고 있다 통째로 쓰면
 *   한쪽에서 고친 것이 다른 쪽에서 덮인다 — 2026-08-16 에 실제로 그렇게 시각
 *   186개가 날아갔다.
 */
"use strict";

import { el, api, icon, toast } from "./util.js";
import { state } from "./store.js";

const fmt = (v) => (v == null ? "" : Number(v).toFixed(1));

/**
 * 그 장의 스토리보드를 **두 자리에** 나눠 붙인다. 없으면 아무것도 안 붙인다.
 *
 * ★ 스틸은 위(슬라이드 자리), 순서 표는 음성 아래 — 사람이 그린 배치다.
 *   손이 가는 순서가 그렇기 때문이다: 듣는다 → 발음을 고친다 → 그 말이 나올 때
 *   어느 글자가 떠야 하는지 정한다.
 *
 * @param {HTMLElement} stageHost 스틸 + 상자를 놓을 자리(위)
 * @param {HTMLElement} rowsHost  순서 표를 놓을 자리(아래)
 * @param {HTMLElement} cueHost   자막을 문장별로 펼칠 자리(자막 칸 밑)
 */
export async function storyboard(stageHost, rowsHost, cueHost, no) {
  let d;
  try {
    d = await api(`/api/projects/${state.projectId}/motion/scene/${no}`);
  } catch {
    return null;                       // 모션을 안 쓰는 프로젝트 — 조용히 넘어간다
  }
  if (!d || !d.mp4) return null;       // 아직 영상을 안 구웠다 — 여기서 할 일이 없다

  /* ── 영상은 있는데 스틸이 없다 ─────────────────────────────
     ★ 이 자리에 지정기를 둔다. 스틸은 지정기를 만들 때 같이 뽑히는데, 예전에는
       화면이 조용히 사라져서 **모션 화면까지 가야** 그걸 알 수 있었다
       (2026-08-17: "각 슬라이드장에 음성 슬라이드별로 실행하는 데에 모여 있게").
       한 장을 확정하는 데 필요한 것은 다 이 화면에 있어야 한다. */
  if (!d.still) {
    const b = el("div", "sb sb-need");
    const x = el("div", "sb-need-x", "마스킹을 하려면 먼저 지정기를 만드세요");
    x.appendChild(el("i", null,
      "영상에서 장마다 스틸을 뽑고 글자 자리를 상자로 찍어 둡니다 — "
      + "1~2분 걸리고, 한 번만 하면 됩니다"));
    b.appendChild(x);
    const mk = el("button", "btn primary");
    mk.type = "button";
    mk.append(icon("external", 12), el("span", null, "지정기 만들고 열기"));
    mk.title = "영상에서 스틸을 뽑아 새 창으로 엽니다 — 한 번만 하면 됩니다";
    mk.onclick = async () => {
      mk.disabled = true;
      const sp = mk.querySelector("span");
      const was = sp.textContent;
      sp.textContent = "만드는 중…";
      try {
        await api(`/api/projects/${state.projectId}/motion/picker`, {method: "POST"});
        toast("지정기를 엽니다 — 상자를 찍고 이 화면을 새로고침하세요");
      } catch (e) {
        toast("만들지 못했습니다: " + e.message, "err");
      } finally { sp.textContent = was; mk.disabled = false; }
    };
    b.appendChild(mk);
    rowsHost.appendChild(b);
    return null;                       // 스틸이 없으니 미리보기는 그대로 둔다
  }

  /* ── 자막을 문장별로 펼친다 ─────────────────────────────
     ★ 자막이 한 덩이 textarea 로만 있으면 **몇 초에 무슨 말인지** 알 수가 없다.
       그걸 알아야 상자에 넣을 초를 정한다 — 칸이 나뉘어야 몇 분 몇 초부터인지
       보이고, 그 순서로 시각을 정한다(2026-08-16).
     ★ 시각은 실제 음성에서 잰 값이다(`08_자막/NNN.srt`). 여기서 고치지 않는다 —
       고칠 것은 상자 쪽이고, 이건 **읽는 자**다. 눌러서 그 초를 집어 갈 수 있다. */
  if (cueHost && (d.cues || []).length) {
    const cl = el("div", "sb-cues");
    cl.appendChild(el("div", "sb-cues-h",
      `자막 ${d.cues.length}줄 — 몇 초에 무슨 말 (누르면 그 초가 복사됩니다)`));
    d.cues.forEach((c) => {
      const r = el("div", "sb-cue");
      r.append(el("span", "sb-cue-t", `${fmt(c.at)}~${fmt(c.until)}`),
               el("span", "sb-cue-x", c.text));
      r.title = "누르면 이 시각이 클립보드로 — 상자 칸에 붙여 넣으세요";
      r.onclick = () => {
        navigator.clipboard?.writeText(fmt(c.at)).catch(() => {});
        toast(`${fmt(c.at)}초 복사 — 상자 «등장» 칸에 붙여 넣으세요`);
      };
      cl.appendChild(r);
    });
    cueHost.appendChild(cl);
  }

  const box = el("div", "sb");
  rowsHost.appendChild(box);

  const hd = el("div", "sb-hd");
  hd.append(el("b", null, "스토리보드 — 말하는 차례와 글자 뜨는 차례"));
  /* ★ 어디까지 봤는지 — 31장을 한자리에서 다 볼 수 없다. 파일에 남은 것을
     그대로 보여 준다(`zones.json` 의 씬마다 `done`). */
  if (d.todo_n) {
    const pg = el("span", "sb-done" + (d.done ? " on" : ""),
      `${d.done_n} / ${d.todo_n} 정리됨` + (d.done ? " · 이 장 됨" : ""));
    hd.appendChild(pg);
  }
  const cnt = el("span", "sb-cnt");
  hd.appendChild(cnt);

  /* ★ 지정기를 여기서도 연다. 상자를 여러 장에 걸쳐 한꺼번에 찍을 때는 아직
       지정기가 빠르다(모든 씬에 이 상자 복사 같은 것이 거기 있다). 다만 —
       ★ **지정기는 zones.json 을 읽지 못한다.** 열면 처음 자동 제안 상태이고,
         거기서 내려받아 다시 넣으면 **여기서 고친 것이 통째로 덮인다**
         (2026-08-16 에 시각 186개가 그렇게 날아갔다). 그래서 경고를 붙인다. */
  const pick = el("button", "btn sm");
  pick.type = "button";
  pick.append(icon("external", 12), el("span", null, "지정기 열기"));
  pick.title = "상자를 한꺼번에 찍을 때\n"
    + "★ 지정기에서 내려받아 불러오면 여기서 고친 상자·시각이 덮입니다";
  pick.onclick = async () => {
    pick.disabled = true;
    try {
      await api(`/api/projects/${state.projectId}/motion/picker`, {method: "POST"});
      toast("지정기를 엽니다 — 내려받아 «불러오기» 하면 여기서 고친 것이 덮입니다", "warn");
    } catch (e) {
      toast("열지 못했습니다: " + e.message, "err");
    } finally { pick.disabled = false; }
  };

  /* ── zones.json 넣기 — 지정기에서 내려받은 것을 여기서 바로 ─────────
     ★ 모션 화면까지 가지 않아도 되게 같은 자리에 둔다. 지정기 → 내려받기 →
       여기 넣기 → 순서 잡기가 한 화면에서 끝난다.
     ★ **덮어쓰기다.** 파일 전체가 갈리므로 여기서 잡아 둔 순서·시각도 같이
       날아간다(2026-08-16 에 그렇게 186개가 사라졌다). 그래서 몇 개가 어떻게
       바뀌는지 **먼저 세어 보여 주고** 묻는다. */
  const zin = el("input");
  zin.type = "file";
  zin.accept = "application/json,.json";
  zin.hidden = true;
  hd.appendChild(zin);

  const load = el("button", "btn sm");
  load.type = "button";
  load.append(icon("upload", 12), el("span", null, "zones.json 넣기"));
  load.title = "지정기에서 내려받은 파일을 넣습니다 — 상자가 통째로 갈립니다";
  load.onclick = () => zin.click();

  zin.onchange = async () => {
    const f = zin.files && zin.files[0];
    zin.value = "";
    if (!f) return;
    let txt;
    try { txt = await f.text(); } catch { toast("파일을 읽지 못했습니다", "err"); return; }
    let n = 0, timed = 0;
    try {
      const j = JSON.parse(txt);
      for (const s of (j.scenes || [])) {
        n += (s.boxes || []).length;
        timed += (s.boxes || []).filter((b) => (b.t || "").trim()).length;
      }
    } catch { toast("zones.json 이 아닙니다", "err"); return; }
    // ★ 잃는 것을 **숫자로 보여 주고** 묻는다. "덮어쓸까요" 만으로는 무엇을 잃는지 모른다.
    const lose = (d.boxes || []).filter((b) => b.at != null).length;
    const msg = `새 파일: 상자 ${n}개 · 시각 ${timed}개\n`
      + `지금 이 장: 상자 ${(d.boxes || []).length}개 · 시각 ${lose}개\n\n`
      + "전체 장의 상자가 새 파일로 통째로 바뀝니다. 넣을까요?";
    if (!confirm(msg)) return;
    try {
      const r = await api(`/api/projects/${state.projectId}/motion/zones`,
                          { method: "POST", body: { text: txt } });
      toast(`넣었습니다 — 씬 ${r.scenes}개 · 상자 ${r.boxes}개. 새로고침합니다`);
      if (r.warn) toast(r.warn, "warn");
      setTimeout(() => location.reload(), 900);
    } catch (e) {
      toast("넣지 못했습니다: " + e.message, "err");
    }
  };

  /* ★ 이 단추가 이 화면의 값이다 — **상자 안 글자를 읽어** 대본과 짝짓는다.
       좌표만으로는 상자에 무슨 글자가 있는지 알 수 없어 위→아래로 띄울 수밖에
       없었고, 그래서 31장 중 25장의 차례가 어긋났다. 오려서 보면 된다.
     ★ 돈이 드는 단계(Claude vision)라 **누를 때만** 돈다. */
  const smart = el("button", "btn sm");
  smart.type = "button";
  const smLab = el("span", null, "대본에 맞춰 차례 잡기");
  smart.append(icon("target", 12), smLab);
  smart.title = "상자 안 글자를 읽어 어느 말에 떠야 하는지 맞춥니다\n"
    + "자리·크기·종류는 그대로 두고 시각만 넣습니다";
  smart.onclick = () => runOrder(`?no=${no}`, smart, smLab, "이 장");

  const smartAll = el("button", "btn sm");
  smartAll.type = "button";
  const saLab = el("span", null, "전체");
  smartAll.append(saLab);
  smartAll.title = "상자가 있는 장 전부 — 몇 분 걸립니다";
  smartAll.onclick = () => runOrder("", smartAll, saLab, "전체");

  async function runOrder(q, btn, lab, what) {
    btn.disabled = true;
    const was = lab.textContent;
    const t0 = Date.now();
    const iv = setInterval(() => {
      const v = Math.floor((Date.now() - t0) / 1000);
      lab.textContent = `읽는 중 · ${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
    }, 1000);
    try {
      const j = await api(`/api/projects/${state.projectId}/motion/order${q}`,
                          { method: "POST" });
      for (;;) {
        await new Promise((z) => setTimeout(z, 2000));
        const s = await api(`/api/jobs/${j.job_id}`);
        if (s.running) continue;
        if (s.error) throw new Error(s.error);
        break;
      }
      toast(`${what} 차례를 잡았습니다 — 훑어보고 틀린 것만 고치세요`);
      location.reload();
    } catch (e) {
      toast("못 잡았습니다: " + e.message, "err");
    } finally {
      clearInterval(iv); lab.textContent = was; btn.disabled = false;
    }
  }

  const auto = el("button", "btn sm");
  auto.type = "button";
  auto.append(icon("wand", 12), el("span", null, "시간 자동 채우기"));
  auto.title = "자막 문장이 나오는 시각으로 상자 차례를 깔아 줍니다";

  const save = el("button", "btn sm primary");
  save.type = "button";
  const sLab = el("span", null, "정리됨 · 저장");
  save.append(icon("check", 12), sLab);

  hd.append(pick, load, smart, smartAll, auto, save);
  box.appendChild(hd);

  /* ── 스틸 + 상자 ─────────────────────────────────────────
     상자는 1920×1080 좌표다. 화면 폭에 맞춰 배율만 곱해 얹는다. */
  const stage = el("div", "sb-stage");
  const img = el("img", "sb-img");
  img.src = d.still;
  img.alt = "";
  const layer = el("div", "sb-layer");
  stage.append(img, layer);
  stageHost.appendChild(stage);        // ★ 위 — 슬라이드 자리

  const list = el("div", "sb-rows");
  box.appendChild(list);

  const foot = el("div", "sb-foot");
  foot.textContent = "상자를 끌면 옮겨지고, 모서리를 끌면 크기가 바뀝니다. "
    + "빈 곳을 끌면 새 상자. 줄을 끌면 차례가 바뀝니다.";
  box.appendChild(foot);

  let boxes = (d.boxes || []).map((b) => ({ ...b }));
  let sel = -1;

  const scale = () => (img.clientWidth || 1) / (d.W || 1920);

  /* 그 시각에 나오는 자막 문장 — 상자 옆에 붙일 글 */
  const said = (at) => {
    if (at == null || !d.cues.length) return "";
    let best = d.cues[0];
    for (const c of d.cues) if (c.at <= at + 0.05) best = c;
    return best.text;
  };

  function draw() {
    /* ★ 장을 넘기면 이 판은 DOM 에서 떨어져 나간다. 아래 resize 리스너는 그때
       같이 안 떨어지므로, 31장을 훑고 나면 죽은 판 31개를 다시 그리려 든다.
       붙어 있을 때만 그린다. */
    if (!img.isConnected) return;
    const k = scale();
    layer.textContent = "";
    boxes.forEach((b, i) => {
      /* ★ 가리기는 **덮는** 상자다 — 글자 상자와 같은 모양으로 그리면 실수로
         멀쩡한 자리에 걸어 놓고도 못 알아챈다. 빗금으로 다르게 그린다. */
      const r = el("div", "sb-box" + (i === sel ? " on" : "")
                        + (b.kind === "cover" ? " cover" : ""));
      r.style.left = `${b.x * k}px`;
      r.style.top = `${b.y * k}px`;
      r.style.width = `${b.w * k}px`;
      r.style.height = `${b.h * k}px`;
      r.appendChild(el("span", "sb-no", String(i + 1)));
      const grip = el("i", "sb-grip");
      r.appendChild(grip);
      r.onmousedown = (e) => startDrag(e, i, e.target === grip ? "size" : "move");
      layer.appendChild(r);
    });
    rows();
    /* ★ **시각이 빠진 상자를 세어 보여 준다.** 비어 있으면 `remaster` 가 그 장의
       글자를 앞 2~3초에 몰아 띄운다 — 그런데 화면 어디에도 그 사실이 안 보여서,
       13장 하나가 빈 채로 굽기 직전까지 갔다(2026-08-17). 숫자로 세운다. */
    const empty = boxes.filter((b) => b.at == null).length;
    cnt.textContent = `상자 ${boxes.length}개 · 문장 ${d.cues.length}개`
      + (empty ? ` · ⚠ 시각 없는 상자 ${empty}개` : " · 시각 다 있음");
    cnt.className = "sb-cnt" + (empty ? " warn" : "");
  }

  function rows() {
    list.textContent = "";
    boxes.forEach((b, i) => {
      const r = el("div", "sb-row" + (i === sel ? " on" : ""));
      r.draggable = true;
      r.append(el("span", "sb-drag", "⠿"), el("span", "sb-rn", String(i + 1)));

      const a = el("input", "sb-t");
      a.type = "text"; a.value = fmt(b.at); a.placeholder = "등장";
      a.oninput = () => { b.at = a.value.trim() === "" ? null : parseFloat(a.value); say.textContent = said(b.at); };

      const u = el("input", "sb-t");
      u.type = "text"; u.value = fmt(b.until); u.placeholder = "빛끝";
      u.oninput = () => { b.until = u.value.trim() === "" ? null : parseFloat(u.value); };

      /* ★ 종류 — 글자 · 그림 · 빛만 · 가리기.
         화살표·도표처럼 **면이 넓은 그림**에 글자 방식(획 모양대로 지웠다 올리기)을
         걸면 자국이 남는다. 그림은 칸 전체가 좌→오로 훑려 드러나야 한다.
         바탕이 거친 자리는 `빛만` — 지우면 번지므로 빛만 지나간다.
         `가리기` 는 **깨져 나온 글자를 영상 내내 덮는다.** 등장이 없으니 시각 칸을
         잠근다 — 시각을 적어도 `remaster` 가 보지 않는다. */
      const kind = el("select", "sb-kind");
      for (const [v, t] of [["text", "글자"], ["art", "그림"], ["sheen", "빛만"],
                            ["cover", "가리기"]]) {
        const o = el("option", null, t);
        o.value = v;
        if ((b.kind || "text") === v) o.selected = true;
        kind.appendChild(o);
      }
      const lockT = () => {
        const cv = kind.value === "cover";
        a.disabled = u.disabled = cv;
        a.title = u.title = cv ? "가리기는 영상 내내 덮습니다 — 시각이 없습니다" : "";
        r.classList.toggle("sb-cover", cv);
      };
      kind.onchange = () => { b.kind = kind.value; lockT(); draw(); };
      lockT();

      /* ★ 시각 옆에 그때의 말이 붙는다 — 이 화면의 존재 이유다 */
      const say = el("span", "sb-say", said(b.at));

      const del = el("button", "sb-x");
      del.type = "button"; del.textContent = "✕";
      del.onclick = () => { boxes.splice(i, 1); sel = -1; draw(); };

      r.append(a, u, kind, say, del);
      r.onmouseenter = () => { sel = i; paintSel(); };
      /* ★ 줄을 누르면 **그 상자를 보여 준다**(2026-08-16). 줄은 아래, 스틸은
         위라 화면이 길면 번호만으로는 어느 글자인지 눈으로 찾아야 한다.
         스틸을 화면 안으로 데려오고 그 상자를 잠깐 크게 표시한다. */
      r.onclick = (e) => {
        if (e.target.tagName === "INPUT" || e.target === del) return;
        sel = i; paintSel();
        stage.scrollIntoView({ behavior: "smooth", block: "center" });
        const n = layer.children[i];
        if (!n) return;
        n.classList.add("flash");
        setTimeout(() => n.classList.remove("flash"), 900);
      };
      r.ondragstart = (e) => { e.dataTransfer.setData("i", String(i)); };
      r.ondragover = (e) => e.preventDefault();
      r.ondrop = (e) => {
        e.preventDefault();
        const from = Number(e.dataTransfer.getData("i"));
        if (Number.isNaN(from) || from === i) return;
        /* ★ 줄을 옮기면 **상자만** 자리를 바꾸고 시각은 그 자리에 남긴다.
           차례가 곧 시각 순서라, 시각까지 따라가면 아무것도 안 바뀐다. */
        const ts = boxes.map((x) => [x.at, x.until]);
        const [m] = boxes.splice(from, 1);
        boxes.splice(i, 0, m);
        boxes.forEach((x, k2) => { x.at = ts[k2][0]; x.until = ts[k2][1]; });
        sel = i;
        draw();
      };
      list.appendChild(r);
    });
  }

  function paintSel() {
    [...layer.children].forEach((n, i) => n.classList.toggle("on", i === sel));
    [...list.children].forEach((n, i) => n.classList.toggle("on", i === sel));
  }

  /* ── 끌기 — 옮기기 · 크기 · 새로 그리기 ───────────────── */
  function startDrag(e, i, mode) {
    e.preventDefault();
    sel = i; paintSel();
    const k = scale();
    const b = boxes[i];
    const x0 = e.clientX, y0 = e.clientY;
    const o = { ...b };
    const move = (ev) => {
      const dx = (ev.clientX - x0) / k, dy = (ev.clientY - y0) / k;
      if (mode === "move") { b.x = Math.max(0, Math.round(o.x + dx)); b.y = Math.max(0, Math.round(o.y + dy)); }
      else { b.w = Math.max(8, Math.round(o.w + dx)); b.h = Math.max(8, Math.round(o.h + dy)); }
      draw();
    };
    const up = () => { removeEventListener("mousemove", move); removeEventListener("mouseup", up); };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  }

  layer.onmousedown = (e) => {
    if (e.target !== layer) return;               // 상자 위가 아니라 빈 곳
    const k = scale();
    const rect = layer.getBoundingClientRect();
    const sx = (e.clientX - rect.left) / k, sy = (e.clientY - rect.top) / k;
    const b = { x: Math.round(sx), y: Math.round(sy), w: 8, h: 8, kind: "text", at: null, until: null };
    boxes.push(b);
    sel = boxes.length - 1;
    startDrag(e, sel, "size");
  };

  auto.onclick = async () => {
    auto.disabled = true;
    try {
      const r = await api(
        `/api/projects/${state.projectId}/motion/scene/${no}/autotime`,
        { method: "POST", body: {} });
      boxes = (r.boxes || []).map((b) => ({ ...b }));
      draw();
      toast("자막 시각으로 차례를 깔았습니다 — 순서만 보시면 됩니다");
    } catch (e) {
      toast("못 채웠습니다: " + e.message, "err");
    } finally { auto.disabled = false; }
  };

  save.onclick = async () => {
    save.disabled = true;
    const was = sLab.textContent;
    try {
      const r = await api(`/api/projects/${state.projectId}/motion/scene/${no}`,
        { method: "POST", body: { boxes, done: true } });
      toast(`${no}장 정리됐습니다 — 상자 ${r.boxes}개 · 시각 ${r.timed}개`);
      /* ★ 정리하고 → 다음. 이 화면의 주 동작이 그것이라 저장이 곧 넘김이다.
         31장을 한 장씩 눌러 찾아가게 두면 훑는 일이 금세 지친다. */
      const nx = document.querySelector(".focus-nav .nx:not(:disabled)");
      if (nx) setTimeout(() => nx.click(), 400);
      else dispatchEvent(new CustomEvent("sb:done", { detail: { no } }));
    } catch (e) {
      toast("저장하지 못했습니다: " + e.message, "err");
    } finally { sLab.textContent = was; save.disabled = false; }
  };

  if (img.complete) draw(); else img.onload = draw;
  addEventListener("resize", draw);
  return box;
}
