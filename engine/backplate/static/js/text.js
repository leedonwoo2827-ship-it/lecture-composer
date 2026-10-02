/* 슬라이드 텍스트 — **모든 장**의 화면 문구를 고치고 확정한다.
 *
 *   위     번호 탭 (37장 · 확정한 장은 진하게)
 *   좌 70  실물 면 — 최종 렌더러가 그린 그대로. 글이 면에 어떻게 앉는지가 판단 대상이다
 *   우 30  제목 · 본문 · AI 버튼 줄 · 확정
 *
 * ★ 이 화면은 **혼자 선다.** 이미지·영상 화면과 코드를 나눠 쓰지 않는다.
 *   공유 모듈로 묶었더니 한쪽을 고칠 때마다 다른 쪽이 깨졌다(실제로 그랬다).
 *   화면마다 하는 일이 다르므로 파일도 따로 둔다 — 중복이 조금 있는 편이 낫다.
 *
 * 여기가 바닥(base)인 이유: 미저장 입력이 있다. 패널은 Esc 로 닫힌다.
 */
"use strict";


import { el, api, icon, toast, debounce, fitFrame } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";

/* ★ 손편집의 키는 **원래 번호(src_no)** 다.
 *
 * 장을 하나 빼면 조립이 1부터 번호를 다시 매긴다. 그런데 오버라이드 파일은
 * 구조(S2b)가 매긴 원래 번호로 읽힌다 — 화면에 보이는 번호로 저장하면 뺀 장
 * 뒤부터 **한 칸씩 밀려서 엉뚱한 장이 고쳐진다.** 아직 아무도 안 뺐을 때만
 * 우연히 맞는다. 그래서 저장은 언제나 src_no 로 한다.
 */
const okey = (s) => String(s.src_no != null ? s.src_no : s.no);

export const meta = {
  title: "슬라이드 텍스트",
  subtitle: "화면에 박히는 글. 고치면 미리보기가 따라옵니다",
  actions: () => {
    const a = el("a", "btn");
    a.href = "/preview/" + (state.projectId || 0);
    a.target = "_blank";
    a.rel = "noopener";
    a.append(icon("slide", 14), el("span", null, "슬라이드 보기"));
    return [a];
  },
};

/** 내용만큼 늘어나는 입력칸 — 스크롤바가 생기면 전체가 안 보인다 */
function autoSize(t) {
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight + 2, 340) + "px";
}

export async function mount(root, ctx) {
  const page = el("div", "page vpage");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let deck;
  try {
    deck = await api(`/api/projects/${state.projectId}/deck`);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }
  const slides = (deck.ready && deck.slides) || [];
  if (!slides.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 슬라이드가 없습니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("layers", 14), el("span", null, "현황판 열기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  // ── 저장 ── 손편집은 언제나 이긴다
  const pending = {};
  const flush = debounce(async () => {
    const patch = {slides: {...pending}};
    for (const k of Object.keys(pending)) delete pending[k];
    try {
      await api(`/api/projects/${state.projectId}/overrides`,
                {method: "POST", body: {patch}});
    } catch (e) { toast("저장 실패: " + e.message, "err"); }
  }, 600);
  const put = (no, key, val) => { (pending[String(no)] ||= {})[key] = val; flush(); };
  // 대본은 한 겹 안쪽이다(narration.srt_text · narration.text). 덱 화면과 **같은 키**를
  // 써야 두 화면에서 고친 것이 서로를 덮지 않는다.
  const putIn = (no, k1, k2, val) => {
    ((pending[String(no)] ||= {})[k1] ||= {})[k2] = val;
    flush();
  };

  const hd = el("div", "deck-head");
  const sum = el("p", "deck-sub");
  const strip = el("div", "numstrip");
  hd.append(sum, strip);
  const stage = el("div", "vstage");
  page.append(hd, stage);

  const chips = {};
  const okOf = (s) => !!(s.approve || {}).slide;
  const want = Number((ctx && ctx.params && ctx.params.get("n")) || 0);
  let cur = slides.some((x) => x.no === want) ? want : slides[0].no;

  drawSum();
  drawStrip();
  show(cur);

  function drawSum() {
    const live = slides.filter((s) => !s.drop);
    const n = live.filter(okOf).length;
    const dropped = slides.length - live.length;
    sum.textContent = `${live.length}장 중 ${n}장 확정`
      + (n === live.length ? " — 전부 됐습니다" : ` · 남은 ${live.length - n}장`)
      + (dropped ? ` · 뺀 장 ${dropped}개` : "");
  }

  function drawStrip() {
    strip.textContent = "";
    for (const k of Object.keys(chips)) delete chips[k];
    for (const s of slides) {
      const c = el("button", "num-chip" + (s.no === cur ? " active" : "")
                             + (okOf(s) ? " done" : "") + (s.drop ? " dropped" : ""));
      c.type = "button";
      c.append(el("i", "num-dot"), el("span", null, String(s.no)));
      c.title = `${s.no}. ${s.title || ""}`
        + (s.drop ? " — 뺀 장" : okOf(s) ? " — 확정함" : "");
      c.onclick = () => show(s.no);
      strip.appendChild(c);
      chips[s.no] = c;
    }
  }

  function markStrip(no) {
    for (const [k, c] of Object.entries(chips)) {
      c.classList.toggle("active", Number(k) === no);
    }
    chips[no]?.scrollIntoView({block: "nearest", inline: "center"});
  }

  function show(no) {
    cur = no;
    const s = slides.find((x) => x.no === no);
    stage.textContent = "";
    if (!s) return;
    markStrip(no);

    const i = slides.findIndex((x) => x.no === no);
    stage.appendChild(header(s, i));

    // ── 좌 70: 실물 면 ──
    const split = el("div", "split7030");
    const st = el("div", "focus-stage");
    st.dataset.no = `${s.no} / ${slides.length}`;
    const fr = el("iframe", "focus-frame");
    fr.src = `/preview/${state.projectId}?n=${s.no}#${s.no}`;
    fr.title = `슬라이드 ${s.no}`;
    st.appendChild(fr);
    // 영상과 같은 픽셀로 그린다 — 여기서 본 것이 곧 영상이다(1920x1080)
    fitFrame(st, fr, 1920);
    const reload = debounce(() => {
      fr.src = `/preview/${state.projectId}?n=${s.no}&t=${Date.now()}#${s.no}`;
    }, 1200);

    // ── 우 30: 고치는 곳 ──
    const side = el("div", "focus-meta");

    side.appendChild(el("label", "fm-lb", "제목 — 한 줄, 서른 자 안팎"));
    const tin = el("textarea", "fm-title");
    tin.rows = 1;
    tin.value = s.title || "";
    tin.placeholder = "제목";
    side.appendChild(tin);

    side.appendChild(el("label", "fm-lb", "본문 — 두세 줄. 나머지는 입으로 말합니다"));
    const bin = el("textarea", "fm-body");
    bin.rows = 3;
    bin.value = s.note || "";
    bin.placeholder = "본문 (비워도 됩니다)";
    side.appendChild(bin);

    const len = el("div", "fm-len");
    side.appendChild(len);
    function showLen() {
      const n = (bin.value || "").replace(/\s/g, "").length;
      len.textContent = `제목 ${(tin.value || "").length}자 · 본문 ${n}자`
        + (n > 130 ? " — 화면이 문서가 되고 있습니다" : "");
      len.classList.toggle("over", n > 130);
    }
    tin.oninput = () => {
      s.title = tin.value; put(okey(s), "title", tin.value);
      autoSize(tin); showLen(); reload(); drawStrip(); markStrip(s.no);
    };
    bin.oninput = () => {
      s.note = bin.value; put(okey(s), "note", bin.value);
      autoSize(bin); showLen(); reload();
    };
    showLen();

    /* ★ 자막·발음을 여기 같이 둔다. 화면 글과 입으로 하는 말은 **한 장의 앞뒤**라
     * 따로 보면 같은 말을 두 번 하거나(화면에 다 써 놓고 그대로 읽기) 어긋난다.
     * 덱 화면에도 같은 칸이 있고 키가 같으므로 어느 쪽에서 고쳐도 된다. */
    side.appendChild(el("label", "fm-lb", "자막 — 입으로 하는 말. 화면 아래에 뜹니다"));
    const sin = el("textarea", "fm-body");
    sin.rows = 4;
    sin.value = (s.narration && s.narration.srt_text) || "";
    sin.placeholder = "대본을 돌리면 채워집니다";
    side.appendChild(sin);

    side.appendChild(el("label", "fm-lb", "발음 — TTS 가 실제로 읽는 글"));
    const pin = el("textarea", "fm-body fm-pron");
    pin.rows = 4;
    pin.value = (s.narration && s.narration.text) || "";
    pin.placeholder = "비우면 자막을 그대로 읽습니다";
    side.appendChild(pin);

    const nlen = el("div", "fm-len");
    side.appendChild(nlen);
    function showNlen() {
      const n = (sin.value || "").replace(/\s/g, "").length;
      // 3자/초 기준 — 설정의 chars_per_sec 과 같은 어림이다
      nlen.textContent = n ? `자막 ${n}자 · 말하면 ${Math.round(n / 3)}초쯤` : "";
    }
    sin.oninput = () => {
      s.narration = {...(s.narration || {}), srt_text: sin.value};
      putIn(okey(s), "narration", "srt_text", sin.value);
      autoSize(sin); showNlen(); reload();
    };
    pin.oninput = () => {
      s.narration = {...(s.narration || {}), text: pin.value};
      putIn(okey(s), "narration", "text", pin.value);
      autoSize(pin);
    };
    showNlen();

    if (s.evidence_hint) {
      const ev = el("div", "slide-ev");
      ev.append(icon("file", 11), el("span", null, s.evidence_hint));
      side.appendChild(ev);
    }

    // ── AI 버튼 줄 ──
    const hint = el("input", "llm-hint");
    hint.type = "text";
    hint.placeholder = "어떻게 고칠까요 — 더 짧게 / 숫자를 앞에 / 기업 회원 화면 얘기로";
    const tone = el("select", "dc-sel llm-tone");
    for (const [v, lb] of [["", "지금 문체"], ["pitch", "광고"],
                           ["bullet", "개조식"], ["explain", "설명문"]]) {
      const o = el("option", null, lb);
      o.value = v;
      tone.appendChild(o);
    }
    const bigBtn = el("button", "btn sm primary");
    bigBtn.type = "button";
    bigBtn.append(icon("wand", 12), el("span", null, "AI 문구 다시"));

    const row = el("div", "llmrow");
    const vout = el("span", "llm-vout");
    const btnTitle = mkBtn("제목만 다시", "refresh");
    const btnBody = mkBtn("본문만 다시", "refresh");
    /* ★ 대본에도 「한 장만 다시」를 둔다. 제목·본문에는 있는데 대본에만 없어서,
       한 장이 마음에 안 들면 31장을 통째로 다시 돌려야 했다(2026-08-14).
       원고가 `data-say` 로 대본을 보내 왔으면 그것부터 공짜로 넣어 준다. */
    const btnScript = mkBtn("자막·발음 다시", "refresh");
    const btnVerify = mkBtn("근거 검증", "check");
    const okb = el("button", "btn sm ok-force");
    okb.type = "button";
    okb.append(icon("check", 12), el("span", null,
      okOf(s) ? "확정됨 — 되돌리기" : "이대로 확정"));
    okb.classList.toggle("on", okOf(s));
    okb.title = "마음에 안 들어도 사람이 이대로 간다고 정할 수 있습니다";
    /* ★ 이 장 빼기 — 구조를 다시 돌리지 않고 손편집으로만 뺀다.
     * 구조(S2b)를 다시 돌리면 되살아나야 하는 게 아니라, 뺀 것이 계속 빠져 있어야
     * 한다. 그래서 오버라이드에 표시하고 조립 단계에서 거른다. 되돌리기도 된다. */
    const dropb = el("button", "btn sm drop" + (s.drop ? " on" : ""));
    dropb.type = "button";
    dropb.append(icon("trash", 12),
                 el("span", null, s.drop ? "뺀 장 — 되돌리기" : "이 장 빼기"));
    dropb.title = "발표에서 제외합니다. 완성본에서 사라지고 번호가 다시 매겨집니다";
    dropb.onclick = () => {
      s.drop = !s.drop;
      dropb.classList.toggle("on", s.drop);
      dropb.querySelector("span").textContent =
        s.drop ? "뺀 장 — 되돌리기" : "이 장 빼기";
      put(okey(s), "drop", s.drop);
      drawStrip(); markStrip(s.no); drawSum();
      toast(s.drop ? `${s.no}번을 뺐습니다 — 굽기 전까지 되돌릴 수 있습니다`
                   : `${s.no}번을 되돌렸습니다`);
    };
    row.append(btnTitle, btnBody, btnScript, btnVerify, dropb, okb, vout);

    const llm = el("div", "llmbar");
    llm.append(hint, tone, bigBtn);
    side.append(llm, row);

    function mkBtn(label, ic) {
      const b = el("button", "btn sm");
      b.type = "button";
      b.append(icon(ic, 12), el("span", null, label));
      return b;
    }

    async function recopy(only) {
      const all = [bigBtn, btnTitle, btnBody, btnVerify];
      all.forEach((b) => (b.disabled = true));
      const lb = bigBtn.querySelector("span");
      const was = lb.textContent;
      lb.textContent = "다시 뽑는 중…";
      try {
        const r = await api(`/api/projects/${state.projectId}/recopy/${s.no}`,
                            {method: "POST",
                             body: {hint: hint.value, tone: tone.value || null,
                                    only: only || null}});
        s.title = r.title; s.note = r.note;
        tin.value = r.title; bin.value = r.note;
        autoSize(tin); autoSize(bin); showLen(); reload();
        drawStrip(); markStrip(s.no);
        toast(`다시 뽑았습니다 · $${r.cost_usd.toFixed(3)}`);
      } catch (e) {
        toast("다시 뽑지 못했습니다: " + e.message, "err");
      } finally {
        all.forEach((b) => (b.disabled = false));
        lb.textContent = was;
      }
    }
    bigBtn.onclick = () => recopy(null);
    btnTitle.onclick = () => recopy("title");
    btnBody.onclick = () => recopy("body");

    btnScript.onclick = async () => {
      const all = [bigBtn, btnTitle, btnBody, btnScript, btnVerify];
      all.forEach((b) => (b.disabled = true));
      const lb = btnScript.querySelector("span");
      const was = lb.textContent;
      lb.textContent = "쓰는 중…";
      try {
        const r = await api(`/api/projects/${state.projectId}/rescript/${s.no}`,
                            {method: "POST", body: {hint: hint.value}});
        sin.value = r.srt_text || "";
        pin.value = r.narration_text || "";
        autoSize(sin); autoSize(pin); showNlen();
        s.narration = {...(s.narration || {}),
                       srt_text: r.srt_text, text: r.narration_text};
        reload();
        toast(r.source === "원고"
              ? "원고에 있던 대본을 넣었습니다 (공짜)"
              : `대본을 다시 썼습니다 · $${(r.cost_usd || 0).toFixed(3)}`);
      } catch (e) {
        toast("대본을 쓰지 못했습니다: " + e.message, "err");
      } finally {
        all.forEach((b) => (b.disabled = false));
        lb.textContent = was;
      }
    };
    hint.onkeydown = (e) => { if (e.key === "Enter") recopy(null); };

    btnVerify.onclick = async () => {
      vout.textContent = "확인 중…";
      vout.className = "llm-vout";
      try {
        const r = await api(`/api/projects/${state.projectId}/verify/${s.no}`);
        if (!r.checked) { vout.textContent = "인용한 근거 없음"; return; }
        vout.textContent = r.bad
          ? `${r.checked}건 중 ${r.bad}건이 레포에 없습니다`
          : `${r.checked}건 전부 실존`;
        vout.className = "llm-vout " + (r.bad ? "bad" : "ok");
        vout.title = r.items.map((x) => `${x.ok ? "○" : "✗"} ${x.ref}`).join("\n");
      } catch {
        vout.textContent = "확인 실패";
        vout.className = "llm-vout bad";
      }
    };

    okb.onclick = () => {
      s.approve = {...(s.approve || {})};
      s.approve.slide = !s.approve.slide;
      okb.classList.toggle("on", !!s.approve.slide);
      okb.querySelector("span").textContent =
        s.approve.slide ? "확정됨 — 되돌리기" : "이대로 확정";
      put(okey(s), "approve", s.approve);
      drawStrip(); markStrip(s.no); drawSum();
    };

    split.append(st, side);
    stage.appendChild(split);
    setTimeout(() => { autoSize(tin); autoSize(bin); }, 0);
  }

  function header(s, i) {
    const hdr = el("div", "vstage-hd");
    hdr.append(el("span", "slide-no", String(s.no)),
               el("h3", null, s.title || "(제목 없음)"));
    const nav = el("div", "focus-nav");
    const prev = el("button", "btn ghost sm");
    prev.type = "button";
    prev.append(icon("chevronLeft", 13), el("span", null, "이전"));
    prev.disabled = i <= 0;
    prev.onclick = () => show(slides[i - 1].no);
    const next = el("button", "btn ghost sm");
    next.type = "button";
    next.append(el("span", null, "다음"), icon("chevronRight", 13));
    next.disabled = i >= slides.length - 1;
    next.onclick = () => show(slides[i + 1].no);
    nav.append(prev, next);
    hdr.appendChild(nav);
    return hdr;
  }

  const onGoto = (e) => {
    const no = e.detail && e.detail.no;
    if (slides.some((x) => x.no === no)) show(no);
  };
  addEventListener("deck:goto", onGoto);
  page.addEventListener("x-unmount", () => removeEventListener("deck:goto", onGoto));
}
