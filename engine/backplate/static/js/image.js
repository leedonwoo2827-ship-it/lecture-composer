/* 삽입 이미지 — 그림이 들어갈 장에 그림을 넣고 바꾼다.
 *
 *   위     번호 탭 (그림 장만 · 붙은 장은 진하게)
 *   좌 70  실물 면 — 그림이 어디에 얼마나 크게 앉는지 보인다
 *   우 30  그림 자리(드롭존) + **추천 프롬프트**
 *
 * ★ 요청과 납품이 **한 화면**에 있다. 프롬프트를 파일로만 내보내면 사람이 그
 *   파일을 열어 번호를 찾아야 한다. 여기서 복사해 이미지 앱에 붙여 넣고, 나온
 *   그림을 바로 옆에 떨어뜨리면 끝이다.
 *
 * ★ 파일명은 **장 번호로 고정**한다(`005.png`). 이미지 앱이 낸 것도 직접 찍은
 *   캡처도 같은 규칙이라, 어디에 무슨 이름으로 넣을지 헷갈릴 일이 없다.
 *
 * ★ 이 화면은 **혼자 선다.** 텍스트·영상 화면과 코드를 나눠 쓰지 않는다.
 */
"use strict";

import { el, api, icon, toast, debounce, fitFrame } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";

export const meta = {
  title: "삽입 이미지",
  subtitle: "그림을 넣고 바꿉니다. 파일명은 장 번호로 고정됩니다",
  actions: () => {
    const a = el("a", "btn");
    a.href = "/preview/" + (state.projectId || 0);
    a.target = "_blank";
    a.rel = "noopener";
    a.append(icon("slide", 14), el("span", null, "슬라이드 보기"));
    return [a];
  },
};

const IMG_TYPES = "image/png,image/jpeg,image/webp,image/gif";
const MAX_BYTES = 12e6;

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
  const slides = ((deck.ready && deck.slides) || [])
    .filter((s) => (s.media_kind === "text_image" || s.media_kind === "thumb") && !s.drop);
  if (!slides.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "그림이 들어갈 장이 없습니다."));
    box.appendChild(el("p", null, "구조 설계가 그림 장을 만들면 여기에 나옵니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("layers", 14), el("span", null, "현황판 열기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  // 캡처 목록 — 없으면(아직 안 찍었으면) 고르기 칸을 아예 안 세운다
  let allShots = [];
  try {
    allShots = (await api(`/api/projects/${state.projectId}/shots`)).shots || [];
  } catch { /* 없어도 이 화면은 돈다 */ }

  const hd = el("div", "deck-head");
  const sum = el("p", "deck-sub");
  const strip = el("div", "numstrip");
  hd.append(sum, strip);
  const stage = el("div", "vstage");
  page.append(hd, stage);

  const chips = {};
  const okOf = (s) => !!(s.image || (s.images || []).length);
  const want = Number((ctx && ctx.params && ctx.params.get("n")) || 0);
  let cur = slides.some((x) => x.no === want) ? want : slides[0].no;

  drawSum();
  drawStrip();
  show(cur);

  function drawSum() {
    const n = slides.filter(okOf).length;
    sum.textContent = `${slides.length}장 중 ${n}장 도착`
      + (n === slides.length ? " — 전부 됐습니다" : ` · 남은 ${slides.length - n}장`);
  }

  function drawStrip() {
    strip.textContent = "";
    for (const k of Object.keys(chips)) delete chips[k];
    for (const s of slides) {
      const c = el("button", "num-chip" + (s.no === cur ? " active" : "")
                             + (okOf(s) ? " done" : ""));
      c.type = "button";
      c.append(el("i", "num-dot"), el("span", null, String(s.no)));
      c.title = `${s.no}. ${s.title || ""}` + (okOf(s) ? " — 그림 있음" : " — 아직 없음");
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
    const reload = () => {
      fr.src = `/preview/${state.projectId}?n=${s.no}&t=${Date.now()}#${s.no}`;
    };

    // ── 우 30: 그림 넣기 ──
    const side = el("div", "iside");
    const fileName = `${String(s.no).padStart(3, "0")}.png`;
    side.appendChild(el("div", "fm-lb", `그림 자리 — ${fileName}`));

    /* ★ 한 장에 **여러 그림**을 넣을 수 있다. 멘토링처럼 신청 화면과 수락 화면이
     * 따로 있는 메뉴는 한 컷으로 안 된다. 있는 만큼 칸을 세우고 빈 칸을 하나 더 둔다.
     * 파일명은 `005.png · 005-2.png · 005-3.png` 로 자동으로 붙는다.
     * 발표에서는 커져 있는 동안 대본 시간을 나눠 차례로 넘어간다. */
    const slots = el("div", "islots");
    side.appendChild(slots);

    function shots() {
      return (s.images && s.images.length) ? s.images : (s.image ? [s.image] : []);
    }

    // 아래 캡처 격자가 세워지면 자기 자신을 여기 꽂는다 — 그림을 빼도 격자의
    // "썼음" 표시가 같이 풀려야 한다.
    let redrawShots = () => {};

    function paint() {
      slots.textContent = "";
      const list = shots();
      const n = list.length;
      for (let k = 0; k <= n; k++) {          // 있는 것 + 빈 칸 하나
        slots.appendChild(slot(k + 1, list[k] || ""));
      }
      const lb = side.querySelector(".fm-lb");
      if (lb) lb.textContent = n > 1
        ? `그림 ${n}장 — ${fileName} 외 ${n - 1}장`
        : `그림 자리 — ${fileName}`;
    }

    function slot(idx, file) {
      const box = el("div", "islot");
      const name = idx === 1 ? fileName
        : `${String(s.no).padStart(3, "0")}-${idx}.png`;
      const view = el("div", "idrop" + (file ? " has" : ""));
      const input = el("input");
      input.type = "file";
      input.accept = IMG_TYPES;
      input.hidden = true;

      if (file) {
        const im = el("img");
        im.src = `/api/projects/${state.projectId}/file/${encodeURI(file)}?t=${Date.now()}`;
        im.alt = "";
        view.appendChild(im);
      } else {
        const ph = el("div", "idrop-ph");
        ph.append(icon("image", 18), el("b", null, name),
                  el("span", null, idx === 1 ? "끌어다 놓거나 눌러서"
                                             : "여기에 더 넣을 수 있습니다"));
        view.appendChild(ph);
      }
      view.onclick = () => input.click();
      input.onchange = () => send(input.files[0], idx);
      view.ondragover = (e) => { e.preventDefault(); view.classList.add("over"); };
      view.ondragleave = () => view.classList.remove("over");
      view.ondrop = (e) => {
        e.preventDefault();
        view.classList.remove("over");
        send(e.dataTransfer.files[0], idx);
      };

      const bar = el("div", "imgdrop-bar");
      bar.appendChild(el("span", "islot-n", `${idx}`));
      if (file) {
        const rm = el("button", "btn sm ghost");
        rm.type = "button";
        rm.textContent = "빼기";
        rm.onclick = (e) => { e.stopPropagation(); remove(idx); };
        bar.appendChild(rm);
      }
      box.append(view, bar, input);
      return box;
    }

    async function send(file, idx) {
      if (!file) return;
      if (file.size > MAX_BYTES) { toast("12MB 를 넘습니다", "err"); return; }
      slots.classList.add("busy");
      try {
        const data_url = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = rej;
          r.readAsDataURL(file);
        });
        const r = await api(
          `/api/projects/${state.projectId}/slide-image/${s.no}?i=${idx}`,
          {method: "POST", body: {data_url, name: file.name}});
        s.images = r.images;
        s.image = r.images[0] || "";
        paint(); drawStrip(); markStrip(s.no); drawSum(); reload(); redrawShots();
        toast(`${r.name} 넣었습니다`);
      } catch (e) {
        toast("넣지 못했습니다: " + e.message, "err");
      } finally {
        slots.classList.remove("busy");
      }
    }

    async function remove(idx) {
      try {
        const r = await api(
          `/api/projects/${state.projectId}/slide-image/${s.no}?i=${idx}`,
          {method: "DELETE"});
        s.images = r.images;
        s.image = r.images[0] || "";
        s.image_srcs = r.image_srcs || [];
        paint(); drawStrip(); markStrip(s.no); drawSum(); reload(); redrawShots();
      } catch (e) { toast("빼지 못했습니다: " + e.message, "err"); }
    }

    // ── 캡처에서 고르기 ──
    /* ★ 그림 장의 대부분은 **화면 캡처**다. 파일 탐색기를 열어 폴더를 찾아
     * 끌어다 놓는 왕복이 장마다 반복되는데, 캡처는 이미 프로젝트 폴더 안에 있고
     * 목록(`01b_캡처/shots.json`)에는 메뉴 이름과 순서까지 들어 있다.
     * 여기서 눌러 넣으면 그 왕복이 통째로 없어진다. */
    if (allShots.length) {
      const pick = el("div", "pbox");
      pick.appendChild(el("div", "fm-lb", `캡처에서 고르기 — ${allShots.length}장`));

      const q = el("input", "dc-in");
      q.type = "search";
      q.placeholder = "메뉴 이름으로 — 쉼표로 여러 개 (내 경력, 학력, 자격증)";
      pick.appendChild(q);

      const roles = [...new Map(allShots.map((x) => [x.role, x.role_label])).entries()];
      let role = "";
      const tabs = el("div", "numstrip");
      const drawTabs = () => {
        tabs.textContent = "";
        for (const [id, lb] of [["", "전체"], ...roles]) {
          const c = el("button", "num-chip" + (role === id ? " active" : ""));
          c.type = "button";
          c.append(el("span", null, lb || id));
          c.onclick = () => { role = id; drawTabs(); drawGrid(); };
          tabs.appendChild(c);
        }
      };
      pick.appendChild(tabs);

      const grid = el("div", "shotgrid");
      pick.appendChild(grid);

      function drawGrid() {
        // 쉼표 = 또(OR) · 띄어쓰기 = 그리고(AND). 한 장에 여러 캡처를 넣는 일이
        // 흔해서, "내 경력, 학력, 자격증" 한 번에 4장을 뽑을 수 있어야 한다.
        const terms = q.value.toLowerCase().split(",")
          .map((t) => t.trim().split(/\s+/).filter(Boolean)).filter((w) => w.length);
        const list = allShots.filter((x) => {
          if (role && x.role !== role) return false;
          if (!terms.length) return true;
          const hay = `${x.label} ${x.slug} ${x.path} ${x.group}`.toLowerCase();
          return terms.some((words) => words.every((w) => hay.includes(w)));
        });
        grid.textContent = "";
        if (!list.length) {
          grid.appendChild(el("div", "empty", "찾는 화면이 없습니다."));
          return;
        }
        const used = new Set(s.image_srcs || []);
        for (const sh of list) {
          const b = el("button", "shotcard" + (used.has(sh.file) ? " used" : ""));
          b.type = "button";
          const im = el("img");
          im.src = `/api/projects/${state.projectId}/file/${encodeURI(sh.file)}`;
          im.alt = "";
          im.loading = "lazy";
          const cap = el("span", "shotcard-cap", sh.label || sh.slug);
          b.title = `${sh.role_label}${sh.group ? " · " + sh.group : ""}\n${sh.path}`
                  + (sh.common ? `\n공통 — ${(sh.roles || []).join(", ")}` : "");
          b.append(im, cap);
          if (sh.common) b.appendChild(el("i", "shotcard-tag", "공통"));
          b.onclick = () => attach(sh);
          grid.appendChild(b);
        }
      }

      async function attach(sh) {
        grid.classList.add("busy");
        try {
          const idx = shots().length + 1;      // 빈 칸에 이어 붙는다
          const r = await api(
            `/api/projects/${state.projectId}/slide-image/${s.no}/from-shot?i=${idx}`,
            {method: "POST", body: {file: sh.file}});
          s.images = r.images;
          s.image = r.images[0] || "";
          s.image_srcs = r.image_srcs || [];
          paint(); drawStrip(); markStrip(s.no); drawSum(); reload(); drawGrid();
          toast(`${sh.label} → ${r.name}`);
        } catch (e) {
          toast("넣지 못했습니다: " + e.message, "err");
        } finally {
          grid.classList.remove("busy");
        }
      }

      q.oninput = debounce(drawGrid, 150);
      redrawShots = drawGrid;
      drawTabs();
      drawGrid();
      side.appendChild(pick);
    }

    // ── 추천 프롬프트 ──
    const pbox = el("div", "pbox");
    pbox.appendChild(el("div", "fm-lb", "추천 프롬프트"));
    const pta = el("textarea", "dc-ta pbox-ta");
    pta.rows = 8;
    pta.value = "불러오는 중…";
    pbox.appendChild(pta);

    const pbar = el("div", "imgdrop-bar");
    const copy = el("button", "btn sm");
    copy.type = "button";
    copy.append(icon("clipboard", 12), el("span", null, "복사"));
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(pta.value);
        toast("복사했습니다 — 이미지 앱에 붙여 넣으세요");
      } catch {
        pta.select();
        document.execCommand("copy");
        toast("복사했습니다");
      }
    };
    pbar.appendChild(copy);
    pbox.appendChild(pbar);
    pbox.appendChild(el("div", "imgdrop-path",
      "D:\\00work\\260628-로컬이미지_앞에프롬프트필더 에 붙여 넣고, "
      + `나온 그림을 위에 넣거나 00_기획/참고/ 에 ${fileName} 로 저장하세요`));
    side.appendChild(pbox);

    api(`/api/projects/${state.projectId}/imgprompt/${s.no}`)
      .then((r) => { pta.value = r.prompt; })
      .catch(() => { pta.value = "프롬프트를 만들지 못했습니다."; });

    paint();
    split.append(st, side);
    stage.appendChild(split);
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
