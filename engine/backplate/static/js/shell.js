/* 셸 — 2층 해시 라우터, 좌측 레일(접기), 최근 프로젝트, 전역 단축키
 *
 * 라우터가 2층인 이유(사내 로컬 콘솔의 UX 법칙): **목록은 패널, 작업은 바탕.**
 * 패널을 열고 닫아도 베이스는 언마운트되지 않으므로, 몇 분 걸리는 스테이지
 * SSE 스트림과 덱 에디터의 미저장 텍스트가 살아 있다.
 *
 *   layer "base"  → #view 를 갈아치운다  (/frames /script /text /image /video /deck)
 *   layer "panel" → 패널을 띄운다        (/projects /workspace)
 */
"use strict";

import { $, $$, el, toast, api } from "./util.js";
import { hydrateIcons } from "./icons.js";
import { openPanel, closePanel, isOpen as panelOpen, setActions } from "./panel.js";
import { state, getProject, getProjects, invalidate } from "./store.js";
import { stepBadge } from "./steps.js";

const view = $("#view");

/* ★ 층 배치의 기준은 "미저장 텍스트가 있는가" 다.
 *
 *   바탕(base) — 일하는 곳. 자막을 고치고, 발음을 발음기호로 바꾸고, 캡션을
 *     다듬는다. 이런 화면은 Esc·스크림 클릭으로 닫히면 안 되므로 절대 패널에
 *     두지 않는다. 패널이 위에 떠도 바탕은 언마운트되지 않아 입력이 살아 있다.
 *
 *   패널(panel) — 고르고 닫는 곳. 현황판, 프로젝트 고르기, 워크스페이스.
 *     단계를 돌리는 것도 현황판 안이다. 패널을 닫아도 잡은 서버에서 계속 돌고,
 *     진행 상태는 레일의 전역 진행바가 계속 보여 준다.
 */
const routes = [
  { re: /^\/home$/,   nav: "",    layer: "base", load: () => import("./home.js") },
  { re: /^\/start$/,  nav: "new", layer: "base", load: () => import("./start.js") },

  /* ★ 목차 확인 — 비싼 단계로 내려가기 전의 문. 바닥인 이유는 제목 입력칸 때문. */
  { re: /^\/outline$/, nav: "otl", layer: "base", load: () => import("./outline.js") },
  /* 초안 화면은 걷어냈다. 전체를 한 판에 읽는 자리로 만들었지만, 실제로는 목차와
     유형 화면 사이에서 같은 것을 한 번 더 보여 줄 뿐이었다. 원고 JSON 입출력은
     목차 화면이 그대로 쓴다(`/api/projects/{pid}/draft`) — API 는 남는다. */
  { re: /^\/frames$/, nav: "frm", layer: "base", load: () => import("./frames.js") },
  { re: /^\/script$/, nav: "scr", layer: "base", load: () => import("./script.js") },
  { re: /^\/text$/,   nav: "txt", layer: "base", load: () => import("./text.js") },
  { re: /^\/html$/,   nav: "htm", layer: "base", load: () => import("./html.js") },
  { re: /^\/image$/,  nav: "img", layer: "base", load: () => import("./image.js") },
  /* ★ 라벨 자리 — 배경판(11판) 전용. 그림이 비운 자리에 얹힌 글을 끌어 옮긴다.
     그림 위치는 그림을 다시 굽지 않고 여기서 고친다(지시문으로 못박는 길은
     이 레포에 실패 기록이 있다 — 3:2 시절 15장 전부가 칸을 넘겼다). */
  { re: /^\/labels$/, nav: "lbl", layer: "base", load: () => import("./labels.js") },
  { re: /^\/video$/,  nav: "vid", layer: "base", load: () => import("./video.js") },
  { re: /^\/deck$/,   nav: "dck", layer: "base", load: () => import("./deck.js") },
  /* 발음 사전 — 입력칸이 있으니 바닥이다(패널 금지). 덱에서 버튼으로 온다. */
  { re: /^\/dict$/,   nav: "",    layer: "base", load: () => import("./dict.js") },
  /* ★ 말하는 순간 — **덱 다음, 렌더링 앞**이다. 라벨이 뜨는 시각은 실측 음성
     길이에서 나오므로(`render/slides.cue_map`) 음성이 확정돼야 볼 수 있고,
     영상을 굽기 전에 맞춰야 한 번에 끝난다. 순서가 곧 메뉴 순서다. */
  { re: /^\/cues$/,   nav: "cue", layer: "base", load: () => import("./cues.js") },
  { re: /^\/mp4$/,    nav: "mp4", layer: "base", load: () => import("./mp4.js") },
  /* 모션 — 완성 mp4 를 재료로 다시 굽는다.
     ★ **레일에는 없다**(2026-09-18, `static/index.html`). 전면 판은 «영상
       렌더링» 한 번으로 모션까지 끝난다. 이 길은 액자(옛 프로젝트) 보수용으로만
       남았고, 주소를 직접 쳐야 닿는다 — 길을 지우지 않는 이유가 그것이다. */
  { re: /^\/motion$/, nav: "mtn", layer: "base", load: () => import("./motion.js") },

  // 부유 패널(위층) — 고르는 곳.
  // railed:false = 패널 안쪽 세로 서브레일을 쓰지 않는다. 안 쓰는데 켜 두면
  // 232px 짜리 빈 칸이 왼쪽에 남는다(실제로 그렇게 보였다).
  /* ★ 현황판은 **띄운 창**이다. 두 층 법칙 — 목록·현황은 위층, 작업은 바닥.
   * 표를 바닥에 두면 칸을 누를 때마다 화면이 통째로 갈아치워져서 돌아올 자리를
   * 잃는다. 위층이면 닫으면 원래 보던 장으로 그대로 돌아온다. */
  { re: /^\/board$/,     nav: "brd", layer: "panel", railed: false, load: () => import("./board.js") },
  { re: /^\/projects$/,  nav: "",    layer: "panel", railed: false, load: () => import("./projects.js") },
  { re: /^\/workspace$/, nav: "",    layer: "panel", railed: false, load: () => import("./workspace.js") },
];

const HOME = routes[0];
// 프로젝트가 골라져야 열리는 화면 — 레일에서 잠근다.
const NEEDS_PROJECT = new Set(["brd", "otl", "txt", "htm", "img", "lbl", "vid", "dck", "cue", "mp4", "mtn"]);

function parseHash() {
  let raw = (location.hash || "#/board").slice(1) || "/board";
  // ★ 스테이지 화면은 없앴다. 현황판의 "단계별로 자세히" 가 같은 것을 더 잘 한다
  //   — 전 단계가 상태·비용과 함께 한 줄씩 있고 거기서 바로 다시 돌린다.
  //   옛 주소(북마크·남은 버튼)는 조용히 현황판으로 보낸다.
  if (raw.startsWith("/stages")) raw = "/board";
  // 초안 화면을 걷어냈다 — 옛 주소는 목차로 보낸다(원고 JSON 입출력이 거기 있다)
  if (raw.startsWith("/draft")) raw = "/outline";
  const [path, qs] = raw.split("?");
  const params = new URLSearchParams(qs || "");
  for (const rt of routes) {
    const m = path.match(rt.re);
    if (m) return { path, rt, args: m.slice(1).map(decodeURIComponent), params };
  }
  return { path: "/home", rt: HOME, args: [], params };
}

let baseToken = 0;      // 레이어별 취소 토큰 — 섞으면 경쟁 상태가 생긴다
let panelToken = 0;
let basePath = null;
/* ★ 프로젝트가 바뀌면 **같은 화면이라도 다시 그려야 한다.**
 * 아래 render() 는 "같은 path 면 재마운트하지 않는다" 로 최적화돼 있는데(2층
 * 구조의 핵심이다 — 재마운트하면 스트림과 미저장 입력이 날아간다), 프로젝트가
 * 바뀐 경우는 예외다. 이걸 안 걸어 두면 탭이나 최근 목록에서 프로젝트를 눌러도
 * 강조만 옮겨 가고 내용은 이전 프로젝트 그대로 남는다 — 실제로 그렇게 보였다. */
let forceBase = false;

export function navigate(path) {
  if (location.hash === "#" + path) render();
  else location.hash = path;
}
export const currentBase = () => basePath || "/home";

/* ── 유형 메뉴 ─────────────────────────────────────────
 *
 * ★ 유형은 **미디어 종류**다. 주제(무엇을 만들었나 · 움직이는 화면 …)가 아니다.
 *   주제는 프로젝트마다 달라서 사람이 외울 수 없고, 정작 손이 가는 단위는
 *   "텍스트만인가 / 그림이 붙나 / 영상이 붙나" 다. 만드는 비용이 거기서 갈린다.
 *
 *     슬라이드 텍스트     쉽다. 문구만 보면 된다
 *     + 삽입 이미지       그림을 만들어 넣어야 한다
 *     + 삽입 영상         잘라야 하고 길이를 대본에 맞춰야 한다
 *
 *   현황판의 확정 단위와 **같은 축**이다. 화면이 달라도 세는 기준이 하나여야 한다.
 *
 * 누르면 화면을 갈아치우지 않고 그 유형 첫 장으로 간다.
 */
/* ★ `슬라이드 텍스트` 는 **전체 장**이다(미디어 종류로 거르지 않는다).
 *   그림 장에도 영상 장에도 화면 문구는 있고, 문구를 다듬는 일은 한 화면에서
 *   쭉 훑는 게 맞다. 아래 둘만 해당 장으로 좁힌다. */
/* ★ `+ 원고 HTML` 은 참고 원고의 한 항목을 **글 그대로** 얹은 장이다(그림이
 *   아니다). 손이 가는 일이 다른 종류와 다르다 — 그림처럼 만들어 넣는 게 아니라,
 *   **줄마다 몇 초에 뜰지**를 정하는 일이다. 그래서 칸을 따로 둔다. */
const KIND_MENU = [
  {kind: null,         label: "슬라이드 텍스트", color: "#9a4d33", go: "/text"},
  {kind: "html",       label: "+ 원고 HTML",   color: "#7d6a55", go: "/html"},
  {kind: "text_image", label: "+ 삽입 이미지",  color: "#c0714f", go: "/image"},
  {kind: "thumb",      label: "+ 썸네일",      color: "#8a7f9a", go: "/image"},
  {kind: "video",      label: "+ 삽입 영상",    color: "#5c6b62", go: "/video"},
];
let lanesKey = "";

async function refreshLanes(token) {
  const wrap = $("#side-lanes-wrap"), box = $("#side-lanes");
  if (!wrap || !box) return;
  if (!state.projectId) { wrap.hidden = true; lanesKey = ""; return; }

  let d = null;
  try { d = await api(`/api/projects/${state.projectId}/deck`); } catch { /* 아직 없음 */ }
  if (token !== railToken) return;

  const slides = (d && d.ready && d.slides) || [];
  const rows = KIND_MENU
    .map((k) => ({...k, nos: (k.kind ? slides.filter((s) => s.media_kind === k.kind)
                                     : slides).map((s) => s.no)}))
    .filter((k) => k.nos.length);

  const key = state.projectId + ":" + rows.map((r) => r.kind + r.nos.length).join("|");
  if (key === lanesKey) return;
  lanesKey = key;

  wrap.hidden = !rows.length;
  box.innerHTML = "";
  for (const r of rows) {
    const b = el("button", "side-lane");
    b.type = "button";
    b.style.setProperty("--lane", r.color);
    b.append(el("i", "side-lane-dot"),
             el("span", "sl-name", r.label),
             el("span", "sl-n", `${r.nos.length}`));
    b.title = `${r.label} — ${r.nos.length}장
${r.nos.join(", ")}`;
    if (r.kind === "video") b.classList.add("has-tool");
    b.onclick = () => {
      navigate(`${r.go}?n=${r.nos[0]}`);
      setTimeout(() => dispatchEvent(new CustomEvent("deck:goto",
        {detail: {no: r.nos[0], kind: r.kind}})), 40);
    };
    box.appendChild(b);
  }
}


/* ── 렌더 ─────────────────────────────────────────── */
async function render() {
  const { path, rt, args, params } = parseHash();
  $$("#side-nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === rt.nav));
  refreshRail();

  if (rt.layer === "panel") {
    if (!basePath) await mountBase(HOME, "/home", [], new URLSearchParams());
    await mountPanel(rt, path, args, params);
    return;
  }

  if (panelOpen()) closePanel();

  // 이미 이 화면이 바탕에 떠 있으면 다시 마운트하지 않는다.
  // 이게 2층 구조의 존재 이유다 — 재마운트하면 스트림과 입력이 날아간다.
  if (path === basePath && view.firstElementChild && !forceBase) {
    view.focus({ preventScroll: true });
    return;
  }
  forceBase = false;
  await mountBase(rt, path, args, params);
}

function resolve(v, ctx) {
  return typeof v === "function" ? v(ctx) : v;
}

/* 프로젝트 탭 — 바닥 상단에 항상. 화면 종류는 유지한 채 프로젝트만 바꾼다. */
async function applyTabs(page, path) {
  let list = [];
  try { list = await getProjects(); } catch { return; }
  if (!list.length) return;
  const { projectTabs } = await import("./tabs.js");
  const bar = projectTabs(list, state.projectId, (id) => {
    if (id === null) { navigate("/start"); return; }   // + = 새 발표
    state.projectId = id;                              // 화면(path)은 그대로 둔다
  });
  page.insertBefore(bar, page.firstChild);
}

function applyHead(mod, ctx, root) {
  const page = root.querySelector(".page") || root;
  const head = el("div", "page-head");
  head.appendChild(el("h1", null, resolve(mod.meta.title, ctx) || ""));
  const sub = resolve(mod.meta.subtitle, ctx);
  if (sub) head.appendChild(el("p", null, sub));
  const acts = mod.meta.actions ? mod.meta.actions(ctx) : [];
  if (acts && acts.length) {
    const box = el("div", "head-actions");
    acts.forEach((n) => box.appendChild(n));
    head.appendChild(box);
  }
  page.insertBefore(head, page.firstChild);
}

async function mountBase(rt, path, args, params) {
  const token = ++baseToken;
  view.innerHTML = '<div class="empty">불러오는 중…</div>';
  try {
    const mod = await rt.load();
    if (token !== baseToken) return;
    view.innerHTML = "";
    basePath = path;
    const ctx = { args, params, path, navigate };
    await mod.mount(view, ctx);
    if (mod.meta) applyHead(mod, ctx, view);
    // 탭은 헤드보다 위 — 헤드를 넣은 뒤에 앞에 끼운다
    await applyTabs(view.querySelector(".page") || view, path);
  } catch (e) {
    console.error(e);
    if (token !== baseToken) return;
    view.innerHTML = "";
    basePath = path;
    view.appendChild(el("div", "empty", "화면을 불러오지 못했습니다: " + e.message));
  }
  hydrateIcons(view);
  view.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

async function mountPanel(rt, path, args, params) {
  const token = ++panelToken;
  const host = openPanel({ railed: rt.railed !== false });
  host.body.innerHTML = '<div class="empty">불러오는 중…</div>';
  try {
    const mod = await rt.load();
    if (token !== panelToken) return;
    host.body.innerHTML = "";
    const ctx = { args, params, path, navigate, panel: host };
    if (mod.meta) {
      host.setHead(resolve(mod.meta.title, ctx) || "", resolve(mod.meta.subtitle, ctx));
      setActions(mod.meta.actions ? mod.meta.actions(ctx) : []);
    }
    await mod.mount(host.body, ctx);
  } catch (e) {
    console.error(e);
    if (token !== panelToken) return;
    host.body.innerHTML = "";
    host.body.appendChild(el("div", "empty", "불러오지 못했습니다: " + e.message));
  }
  hydrateIcons(host.root);
}

/* ── 레일 ─────────────────────────────────────────── */
let railToken = 0;

async function refreshRail() {
  const token = ++railToken;
  const has = !!state.projectId;
  $$("#side-nav a").forEach((a) => {
    if (NEEDS_PROJECT.has(a.dataset.nav)) a.classList.toggle("locked", !has);
  });

  let list = [];
  try {
    list = await getProjects();
  } catch { /* 서버가 아직 안 떴을 수 있다 — 조용히 넘어간다 */ }
  if (token !== railToken) return;

  const box = $("#side-recent");
  box.innerHTML = "";
  if (!list.length) {
    box.appendChild(el("div", "side-empty", "아직 프로젝트가 없습니다."));
  } else {
    for (const p of list.slice(0, 8)) {
      const a = el("button", "side-recent-item" + (p.id === state.projectId ? " active" : ""));
      a.type = "button";
      a.append(el("span", "sri-name", p.title || p.slug),
               el("span", "sri-meta", `${p.items || 0}개 항목`));
      a.onclick = () => {
        state.projectId = p.id;               // 이것만으로 화면이 다시 그려진다
        if (basePath === "/home" || basePath === "/start") navigate("/board");
      };

      /* 휴지통 — 산출물 폴더가 통째로 사라진다. 되돌릴 수 없으므로 **이름을
       * 직접 치게** 한다. 확인 버튼 하나면 지나가다 누른다. */
      const del = el("button", "sri-del");
      del.type = "button";
      del.title = "정리 — 목록에서 감추고, 지울 폴더 경로를 알려 줍니다";
      del.innerHTML = '<span data-icon="trash" data-icon-size="15"></span>';
      /* ★ 여기서 지우지 않는다. 산출물에는 몇 시간짜리 결과가 들어 있어서,
       *   목록의 작은 버튼 하나로 없앨 수 있게 두지 않는다. 워크스페이스로
       *   데려가 **어느 폴더인지 정확히 보여 준 뒤** 사람이 직접 지운다. */
      del.onclick = (e) => {
        e.stopPropagation();
        state.focusProject = p.id;
        navigate("/workspace");
      };

      const row = el("div", "side-recent-row" + (p.id === state.projectId ? " active" : ""));
      row.append(a, del);
      box.appendChild(row);
    }
  }
  // ★ 레일은 나중에 다시 그려진다. hydrateIcons 는 최초 1회만 돌므로 여기서
  //   다시 불러야 한다 — 안 그러면 data-icon 이 빈 span 으로 남아 안 보인다.
  hydrateIcons(box);

  await refreshLanes(token);

  let proj = null;
  try { proj = await getProject(); } catch { /* 위와 동일 */ }
  if (token !== railToken) return;
  $("#su-name").textContent = proj ? (proj.title || proj.slug) : "프로젝트를 고르세요";
  $("#su-team").textContent = proj ? `${(proj.items || []).length}개 항목` : "—";
  $("#su-avatar").textContent = proj ? (proj.title || proj.slug).slice(0, 2) : "SA";
}

/* ── 오른쪽 서랍 — 최근 한 일 ────────────────────────────────────────────
 *
 * ★ 이 서랍이 답하는 질문은 딱 둘이다.
 *     "방금 무엇을 눌렀나"  — 영상을 낸 건가, 그 앞 슬라이드를 낸 건가
 *     "무엇을 다시 해야 하나" — 뭘 고쳤으니 어느 단계가 낡았나
 *   현황판(`/board`)은 **지금 상태**를 격자로 보여 주지만 시간 순서를 안 보여
 *   준다. 몇 분짜리 단계를 몇 번 돌리다 보면 순서를 잃는데, 그때 필요한 것은
 *   격자가 아니라 **줄줄이 적힌 시각**이다(2026-08-14).
 *
 * ★ 왼쪽이 아니라 오른쪽이다. 왼쪽 레일은 "어디로 갈까"(목록)이고 이것은
 *   "무엇을 했나"(이력)라 성격이 다르다 — 섞으면 둘 다 안 읽힌다.
 *
 * ★ 접힌 상태가 기본. 편 상태는 기억한다(localStorage) — 한 번 펴 둔 사람은
 *   계속 보고 싶어 하고, 안 쓰는 사람 화면을 상시로 좁히지 않는다.
 */
const LOG_KEY = "sa.lograil.open";
let logTimer = null, logKey = "";

function logOpen() { return $("#log-rail")?.dataset.open === "1"; }

function setLogOpen(on) {
  const r = $("#log-rail");
  if (!r) return;
  r.dataset.open = on ? "1" : "0";
  $("#log-tab")?.setAttribute("aria-expanded", on ? "true" : "false");
  try { localStorage.setItem(LOG_KEY, on ? "1" : "0"); } catch { /* 사생활 모드 */ }
  if (on) refreshLog(true);
}

function ago(iso) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return "방금";
  if (s < 3600) return `${Math.round(s / 60)}분 전`;
  if (s < 86400) return `${Math.round(s / 3600)}시간 전`;
  const d = new Date(t);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function refreshLog(force) {
  const body = $("#log-body");
  if (!body) return;
  if (!state.projectId) {
    body.textContent = "";
    body.appendChild(el("div", "side-empty", "프로젝트를 고르면 여기에 쌓입니다."));
    $("#log-tab-dot").hidden = true;
    return;
  }
  let a = null;
  try { a = await api(`/api/projects/${state.projectId}/activity`); } catch { return; }

  // 다시 해야 할 것이 있으면 탭에 점 — 서랍을 닫아 둬도 알 수 있어야 한다
  // ★ 점은 **낡은 것이 있을 때만.** 아직 안 한 단계까지 점을 켜면 새 프로젝트는
  //   처음부터 점이 켜져 있어서 점이 아무 뜻도 갖지 못한다.
  const dot = $("#log-tab-dot");
  if (dot) dot.hidden = !(a.todo || []).length;

  // 안 바뀌었으면 다시 그리지 않는다 — 20초마다 화면이 깜박이면 눈이 피로하다
  const key = state.projectId + ":"
    + (a.done || []).map((r) => r.at + r.key).join("|")
    + "#" + (a.todo || []).map((r) => r.key).join("|") + "#" + (a.pending || 0);
  if (!force && key === logKey) return;
  logKey = key;

  body.textContent = "";

  if ((a.todo || []).length) {
    body.appendChild(el("div", "log-h", "다시 해야 할 것"));
    for (const t of a.todo) {
      const b = el("button", "log-todo");
      b.type = "button";
      if (t.n) b.appendChild(stepBadge(t.n, `${t.n}. ${t.label}`));
      // ★ **무엇 때문에** 낡았는지를 같이 적는다. 그게 없으면 "왜 또 하라는
      //   거지" 가 되고, 한 번 그렇게 읽히면 그 다음부터 이 줄을 안 믿는다.
      b.append(el("span", "log-todo-n", t.label),
               el("span", "log-todo-s", t.why ? `${t.why} 뒤` : "낡음"));
      b.title = `${t.label} 다음에 «${t.why}» 를 했습니다 — 다시 돌리면 맞춰집니다`;
      b.onclick = () => navigate("/board");
      body.appendChild(b);
    }
  }

  body.appendChild(el("div", "log-h", "최근 한 일"));
  if (!(a.done || []).length) {
    body.appendChild(el("div", "side-empty", "아직 아무것도 돌리지 않았습니다."));
  }
  for (const r of a.done || []) {
    const row = el("div", "log-row log-" + r.kind
                        + (r.status && r.status !== "ok" ? " bad" : ""));
    row.append(el("span", "log-when", ago(r.at)));
    const mid = el("span", "log-mid");
    /* ★ 덱의 버튼과 **같은 번호, 같은 배지**를 단다. 이름은 서로 다르다 —
     * 버튼은 「발음대본 생성」, 여기는 「내레이션 대본」. 그 둘이 같은 일인지
     * 매번 헷갈렸다("지금이 3번 할 타이밍인가 4번 할 타이밍인가"). 번호가
     * 그 둘을 잇는다. 순서에 없는 일(손편집)에는 억지로 붙이지 않는다. */
    const head = el("b");
    if (r.n) head.appendChild(stepBadge(r.n, `${r.n}. ${r.step}`));
    head.appendChild(el("span", null, r.label || r.key));
    mid.appendChild(head);
    const sub = [];
    if (r.note) sub.push(r.note);
    if (r.mb) sub.push(`${r.mb}MB`);
    if (r.cost_usd) sub.push(`$${r.cost_usd}`);
    if (r.warn) sub.push(`경고 ${r.warn}`);
    if (sub.length) mid.appendChild(el("span", "log-sub", sub.join(" · ")));
    row.appendChild(mid);
    row.title = new Date(r.at).toLocaleString("ko-KR");
    body.appendChild(row);
  }
  // 아직 안 한 단계는 **숫자만.** 여기 다 늘어놓으면(영상 없는 발표에는 영영 안
  // 도는 단계가 여럿이다) 목록이 늘 길어서 정작 위쪽 "다시 해야 할 것" 을 안 본다.
  if (a.pending) {
    const b = el("button", "log-todo new");
    b.type = "button";
    b.append(el("span", "log-todo-n", "아직 안 한 단계"),
             el("span", "log-todo-s", String(a.pending)));
    b.title = "현황판에서 무엇이 남았는지 봅니다";
    b.onclick = () => navigate("/board");
    body.appendChild(b);
  }
  if (a.spent_usd) {
    body.appendChild(el("div", "log-foot", `이 프로젝트에 쓴 돈 $${a.spent_usd}`));
  }
  hydrateIcons(body);
}

function scheduleLog(ms) {
  clearTimeout(logTimer);
  if (document.hidden || !logOpen()) return;
  logTimer = setTimeout(() => { refreshLog(); scheduleLog(20000); }, ms);
}

function initLogRail() {
  const tab = $("#log-tab");
  if (!tab) return;
  tab.onclick = () => { setLogOpen(!logOpen()); scheduleLog(20000); };
  let want = "0";
  try { want = localStorage.getItem(LOG_KEY) || "0"; } catch { /* 무시 */ }
  if (want === "1") setLogOpen(true);
  hydrateIcons($("#log-rail"));
  scheduleLog(20000);
}

/* ── 전역 진행바 — 스테이지 하나가 몇 분씩 간다 ────────
 * 탭이 숨겨지면 폴링을 멈춘다. 안 그러면 창을 열어 둔 채 자리를 뜬 동안
 * 25초마다 요청이 계속 나간다.
 */
const POLL_RUN = 4000;
const POLL_IDLE = 20000;
let pollTimer = null;

let wasRunning = false;

async function pollJob() {
  let j = null;
  try { j = await api("/api/jobs/running"); } catch { /* 무시 */ }
  const bar = $("#render-bar");
  if (!j || !j.running) {
    bar.hidden = true;
    // ★ 방금 무언가 끝났으면 "최근 한 일" 을 바로 갱신한다. 이 서랍이 있는 이유가
    //   "방금 무엇을 눌렀나" 라, 끝난 줄이 20초 뒤에 뜨면 늦다.
    if (wasRunning) { wasRunning = false; refreshLog(true); }
    schedulePoll(POLL_IDLE);
    return;
  }
  wasRunning = true;
  bar.hidden = false;
  bar.classList.toggle("dead", !!j.died);
  $("#render-bar-title").textContent = j.label || "스테이지";
  const pct = j.total ? Math.round((j.completed / j.total) * 100) : 0;
  $("#render-bar-pct").textContent = j.died ? "중단됨" : `${pct}%`;
  $("#render-bar-fill").style.width = `${j.died ? 100 : pct}%`;
  // j.stage 는 내부 키(s6-script)다. 사람이 읽을 것은 j.step("3/7묶음 · $0.31")
  $("#render-bar-msg").textContent = j.step || j.stage || "";
  schedulePoll(POLL_RUN);
}

function schedulePoll(ms) {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  pollTimer = setTimeout(pollJob, ms);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(pollTimer);
  else schedulePoll(0);
});

/* ── 부팅 ─────────────────────────────────────────── */
function initRail() {
  const railed = localStorage.getItem("sa.rail") === "collapsed";
  if (railed) document.body.dataset.rail = "collapsed";

  const toggle = () => {
    const now = document.body.dataset.rail === "collapsed";
    if (now) delete document.body.dataset.rail;
    else document.body.dataset.rail = "collapsed";
    localStorage.setItem("sa.rail", now ? "" : "collapsed");
  };
  $("#rail-toggle")?.addEventListener("click", toggle);
  $("#brand-mark")?.addEventListener("click", () => {
    if (document.body.dataset.rail === "collapsed") toggle();
    else navigate("/board");
  });

  $("#side-user")?.addEventListener("click", () => navigate("/workspace"));
  $("#side-section-more")?.addEventListener("click", () => navigate("/projects"));
  /* 맨 위 큰 단추 — **새로 시작한다.** 프로젝트가 골라져 있든 말든 같은 곳으로
     간다. 조건에 따라 다른 데로 보내면 "이걸 누르면 뭐가 되지" 를 매번 생각해야
     한다 — 큰 단추는 하나만 하는 게 맞다. 무엇이 남았는지는 오른쪽 서랍이 말한다. */
  $("#btn-new-deck")?.addEventListener("click", () => navigate("/start"));

  // 레일 링크 가로채기 — 잠긴 항목은 프로젝트 고르기로 보낸다
  $("#side-nav")?.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-nav]");
    if (!a || a.target === "_blank") return;
    if (a.classList.contains("locked")) {
      e.preventDefault();
      toast("먼저 프로젝트를 고르세요", "warn");
      navigate("/projects");
    }
  });
}

window.addEventListener("keydown", (e) => {
  if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
    e.preventDefault();
    $("#rail-toggle")?.click();
  }
  // 최근 한 일 — 왼쪽 레일이 Ctrl+B 니 오른쪽 서랍은 그 옆 글쇠로 둔다
  if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "j") {
    e.preventDefault();
    $("#log-tab")?.click();
  }
});

window.addEventListener("sa:project-changed", () => {
  invalidate();
  /* ★ 시작 화면은 예외다.
   *
   * 시작 마법사는 **자기가 프로젝트를 만든다.** 만들자마자 state.projectId 를
   * 세우는데, 그때 이 이벤트가 돌아 화면을 다시 그리면 마법사가 방금 그린
   * 진행 줄(… 레포 받아 읽기 …)이 통째로 지워지고 빈 폼이 다시 뜬다.
   * 겉보기엔 "눌러도 아무 일이 없다가 몇 분 뒤 갑자기 설문이 뜬다" 가 된다.
   * 마법사는 스스로 다음 단계를 그리므로 여기서 손대지 않는다. */
  if (basePath !== "/start") forceBase = true;
  refreshRail();
  logKey = "";                 // 프로젝트가 바뀌면 이력도 통째로 다른 것이다
  refreshLog(true);
  if (basePath !== "/start") render();
});
window.addEventListener("hashchange", render);

initRail();
hydrateIcons(document);
render();
schedulePoll(0);
initLogRail();
