/* 삽입 영상 — 화면 녹화가 붙는 장을 자르고 배속하고 들어낸다.
 *
 *   위     번호 탭 (영상 장만 · 확정한 장은 진하게, 대본이 넘치면 빨간 점)
 *   좌 70  편집기 — 재생기 · 타임라인 · 버튼
 *   우 30  이 장에서 하는 말(대본) · 확정
 *
 * ★ 편집의 목표는 예쁘게가 아니라 **대본 길이에 맞추는 것**이다. 그래서
 *   "편집 후 몇 초 / 대본 몇 초"가 늘 같이 보이고, 대본이 오른쪽에 붙어 있다.
 *
 * ★ 이 화면은 **혼자 선다.** 텍스트·이미지 화면과 코드를 나눠 쓰지 않는다.
 *   편집기(videoedit.js)만 공유한다 — 그건 도구지 화면이 아니다.
 */
"use strict";


import { $, el, api, icon, toast, debounce } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";
import { videoEditor, clipOf, outSec, needSec } from "./videoedit.js";

/* ★ 손편집의 키는 **원래 번호(src_no)** 다.
 *
 * 장을 하나 빼면 조립이 1부터 번호를 다시 매긴다. 그런데 오버라이드 파일은
 * 구조(S2b)가 매긴 원래 번호로 읽힌다 — 화면에 보이는 번호로 저장하면 뺀 장
 * 뒤부터 **한 칸씩 밀려서 엉뚱한 장이 고쳐진다.** 아직 아무도 안 뺐을 때만
 * 우연히 맞는다. 그래서 저장은 언제나 src_no 로 한다.
 */
const okey = (s) => String(s.src_no != null ? s.src_no : s.no);

export const meta = {
  title: "영상",
  subtitle: "구간을 자르고 배속하고 중간을 들어냅니다. 대본 길이에 맞추는 게 목표입니다",
  actions: () => {
    const a = el("a", "btn");
    a.href = "/preview/" + (state.projectId || 0);
    a.target = "_blank";
    a.rel = "noopener";
    a.append(icon("slide", 14), el("span", null, "슬라이드에서 보기"));
    return [a];
  },
};

const sec1 = (n) => (n || 0).toFixed(1) + "초";

export async function mount(root, ctx) {
  const page = el("div", "page vpage");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let d;
  try {
    d = await api(`/api/projects/${state.projectId}/deck`);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }
  const scenes = (d.slides || []).filter((s) => s.video_id && !s.drop);
  if (!scenes.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "영상이 붙은 장이 없습니다."));
    box.appendChild(el("p", null, "구조 설계가 영상을 어느 장에 배치하면 여기에 나옵니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "실행기 열기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  // ── 저장 ── (덱과 같은 오버라이드 파일 · 손편집이 항상 이긴다)
  const pending = {};
  const flush = debounce(async () => {
    const patch = {slides: {...pending}};
    for (const k of Object.keys(pending)) delete pending[k];
    try {
      await api(`/api/projects/${state.projectId}/overrides`,
                {method: "POST", body: {patch}});
    } catch (e) { toast("저장 실패: " + e.message, "err"); }
  }, 600);

  const hd = el("div", "deck-head");
  hd.appendChild(el("h2", null, "영상"));
  const sum = el("p", "deck-sub");
  hd.appendChild(sum);

  const strip = el("div", "numstrip");
  hd.appendChild(strip);
  page.appendChild(hd);

  const stage = el("div", "vstage");
  page.appendChild(stage);
  const chips = {};

  // 시작 장은 주소로 받는다 — 현황판에서 8번을 누르면 8번이 열려야 한다
  const want = Number((ctx && ctx.params && ctx.params.get("n")) || 0);
  let cur = (want && scenes.some((x) => x.no === want)) ? want : scenes[0].no;
  let editor = null;

  function drawSummary() {
    let short = 0, total = 0;
    for (const s of scenes) {
      const o = outSec(clipOf(s));
      total += o;
      if (needSec(s) - o > 0.5) short++;
    }
    sum.textContent = `영상 ${scenes.length}장 · 편집 후 합계 ${sec1(total)}`
      + (short ? ` · 대본이 더 긴 장 ${short}개` : " · 전부 대본이 들어갑니다");
  }

  function drawList() {
    strip.textContent = "";
    for (const k of Object.keys(chips)) delete chips[k];
    for (const s of scenes) {
      const clip = clipOf(s);
      const o = outSec(clip), n = needSec(s);
      const ok = !!(s.approve || {}).mute;
      const c = el("button", "num-chip" + (s.no === cur ? " active" : "")
                             + (ok ? " done" : "") + (n - o > 0.5 ? " warn" : ""));
      c.type = "button";
      c.append(el("i", "num-dot"), el("span", null, String(s.no)));
      c.title = `${s.no}. ${s.title || ""}
편집 후 ${sec1(o)}`
        + (n ? ` · 대본 ${sec1(n)}` : "") + (ok ? " · 확정함" : "");
      c.onclick = () => show(s.no);
      strip.appendChild(c);
      chips[s.no] = c;
    }
  }

  function show(no) {
    cur = no;
    const s = scenes.find((x) => x.no === no);
    stage.textContent = "";
    if (!s) return;

    /* 좌 70 편집기 / 우 30 대본·확정. **선언을 맨 위로** 둔다 —
     * 아래에서 먼저 쓰면 초기화 전 접근으로 화면이 통째로 안 뜬다(실제로 그랬다). */
    const split = el("div", "split7030");
    const leftCol = el("div", "vleft");
    const rightCol = el("div", "vright");
    split.append(leftCol, rightCol);

    const hdr = el("div", "vstage-hd");
    hdr.append(el("span", "slide-no", String(s.no)),
               el("h3", null, s.title || ""));
    const goDeck = el("button", "btn ghost");
    goDeck.type = "button";
    goDeck.append(el("span", null, "이 장 전체 보기"));
    goDeck.onclick = () => navigate("/deck");
    hdr.appendChild(goDeck);
    stage.appendChild(hdr);

    /* ★ 대본을 **편집기 위**에 둔다.
     * 이 화면에서 하는 판단은 "영상을 얼마나 자를까" 가 아니라 "이 말이 이 영상
     * 안에 들어가나" 다. 대본이 아래 있으면 영상을 보고 스크롤을 내려서 확인해야
     * 하고, 그러면 둘을 같이 못 본다. 위에 두면 한 눈에 들어온다. */
    const nar = (s.narration || {}).srt_text;
    if (nar) {
      const q = el("div", "vscript");
      q.append(el("span", "ved-lb", "이 장에서 하는 말"), el("p", null, nar));
      const pron = (s.narration || {}).text;
      if (pron && pron !== nar) {
        const d = el("details", "vpron");
        const sm2 = el("summary");
        sm2.textContent = "발음 (TTS 가 읽는 표기)";
        d.append(sm2, el("p", null, pron));
        q.appendChild(d);
      }
      rightCol.appendChild(q);
    } else {
      const q = el("div", "vscript muted");
      q.textContent = "아직 대본이 없습니다 — 대본을 만들면 여기 뜹니다.";
      rightCol.appendChild(q);
    }

    /* 확정 — 여기서도 찍을 수 있어야 한다. 영상을 보고 대본을 읽은 자리가
     * 여기인데 확정하러 덱으로 건너가게 하면 판단이 끊긴다. */
    const gbar = el("div", "gate-bar");
    gbar.appendChild(el("span", "gate-lb", "확인"));
    for (const [k, label, tip] of [
      ["mute", "영상 무음", "원본 소리를 죽이고 내레이션만 얹어도 된다"],
      ["script", "대본", "이 말이 이 영상 안에 들어간다"],
    ]) {
      const b = el("button", "gate-btn" + ((s.approve || {})[k] ? " on" : ""));
      b.type = "button";
      b.title = tip;
      b.append(icon("check", 13), el("span", null, label));
      b.onclick = () => {
        s.approve = {...(s.approve || {})};
        s.approve[k] = !s.approve[k];
        b.classList.toggle("on", !!s.approve[k]);
        ((pending[okey(s)] ||= {}).approve ||= {})[k] = s.approve[k];
        flush();
        drawList();
      };
      gbar.appendChild(b);
    }
    const over = (s.narration || {}).over_sec;
    if (over > 0.5) {
      const w = el("span", "gate-warn");
      w.textContent = `대본이 ${over.toFixed(1)}초 깁니다`;
      gbar.appendChild(w);
    }
    rightCol.appendChild(gbar);

    editor = videoEditor(s, {
      src: `/api/projects/${state.projectId}/video/${s.video_id}`,
      big: true,
      onChange: (clip) => {
        s.clip = clip;
        (pending[okey(s)] ||= {}).clip = clip;
        flush();
        drawList();
        drawSummary();
      },
    });
    leftCol.appendChild(editor);
    stage.appendChild(split);

    for (const [k, c] of Object.entries(chips)) {
      c.classList.toggle("active", Number(k) === no);
    }
    chips[no]?.scrollIntoView({block: "nearest", inline: "center"});
  }

  /* 단축키 — 편집기에 위임한다. 입력창 안에서는 커서 이동이 우선. */
  const onKey = (e) => {
    const t = e.target;
    if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT")) return;
    if (e.key === "[" || e.key === "]") {
      e.preventDefault();
      const i = scenes.findIndex((x) => x.no === cur);
      const j = e.key === "]" ? i + 1 : i - 1;
      if (scenes[j]) show(scenes[j].no);
      return;
    }
    editor && editor.onKey && editor.onKey(e);
  };
  addEventListener("keydown", onKey);
  page.addEventListener("x-unmount", () => removeEventListener("keydown", onKey));

  addEventListener("deck:goto", (e) => {
    const no = e.detail && e.detail.no;
    if (scenes.some((x) => x.no === no)) show(no);
  });

  drawSummary();
  drawList();
  show(cur);
}
