/* 라벨 자리 — 배경판(11판) 위의 글을 고치고 옮긴다.
 *
 *   위     번호 탭 (라벨이 있는 장만)
 *   좌 68  실물 면 — 16:9 그대로. 상자를 끌어 옮기고 모서리로 폭을 바꾼다
 *   우 32  라벨마다 제목·설명 입력칸
 *
 * ★ **왜 드래그인가.** 그림 모델에게 「여기를 비워라」로 자리를 못박는 길도
 *   있었지만 이 레포에 실패 기록이 있다 — 3:2 시절 「블리드칸을 비워라」를
 *   두 판에 걸쳐 시켰는데 **15장 전부가 그 칸을 넘겼다**(중앙값 85.1%).
 *   그림 모델은 판을 채우려는 성향이 강하다. 그래서 어긋난 자리는 **그림을
 *   다시 굽지 않고 여기서 옮긴다.** 돈이 안 들고 즉시 보인다.
 *
 * ★ 저장은 `deck.overrides.json` 이다 — 언제나 이긴다. 스테이지를 다시 돌려도
 *   산다. 다만 **배열을 통째로** 덮으므로, 한 번 손대면 그 장의 라벨은 사람이
 *   가져간다(내레이션 손편집과 같은 규칙). 되돌리려면 「원래대로」.
 *
 * ★ 좌표는 **%** 다. 실물 면이 몇 픽셀이든, 영상이 1920 이든 같은 자리에 앉는다.
 */
"use strict";

import { el, api, icon, toast, debounce } from "./util.js";
import { state } from "./store.js";

export const meta = {
  title: "라벨 자리",
  subtitle: "배경판 위의 글을 고치고 끌어서 옮깁니다",
  actions: () => {
    const a = el("a", "btn");
    a.href = "/preview/" + (state.projectId || 0);
    a.target = "_blank";
    a.rel = "noopener";
    a.append(icon("slide", 14), el("span", null, "슬라이드 보기"));
    return [a];
  },
};

// 상자 폭(%) — 너무 좁으면 두 글자씩 끊기고, 너무 넓으면 그림을 가린다
const MIN_W = 8;
const MAX_W = 46;

/* 모눈종이 — 눈금 간격(%). 상자가 이 칸에 **달라붙는다.**
 *
 * ★ **보이기만 해서는 안 맞는다.** 격자를 깔아 두고 눈으로 맞추는 것은 지금과
 *   같다 — 실측(2026-09-18, 2장)에서 사람이 맞춘 아래 줄 넷이
 *   y 83.1 · 82.2 · 82.4 로 1%p 씩 어긋나 있었다. 멈춰 있는 화면에서는 안
 *   보이지만 영상에서 글이 하나씩 떠오를 때 줄이 울렁인다. 그래서 **깔고
 *   달라붙게** 한다.
 * ★ **2.5 인 이유.** 아래 줄에 라벨 넷이 서는 판이 흔한데(하단 4분할),
 *   2.5 칸이면 x 0 · 25 · 50 · 72.5 로 떨어지고 y 는 넷이 한 줄에 선다.
 *   1 로 하면 눈금이 촘촘해 안 맞는 것과 같고, 5 로 하면 폭 23 짜리 상자가
 *   놓일 자리가 모자란다.
 * ★ **Alt 를 누른 채 끌면 잠깐 벗어난다.** 그림이 눈금과 안 맞게 그려진 장이
 *   있다 — 그때 격자를 통째로 끄러 가지 않아도 되게 한다.
 */
const GRID = 2.5;

/* 셀색 세 갈래 — **윤곽(기본) · 판 · 끔**.
 * ★ 읽는 규칙이 `render/slides.py` · `render/hyper.py` 의 `_cell_cls` 와
 *   **같아야 한다.** 어긋나면 이 화면이 거짓말을 한다.
 * ★ `true` 를 판으로 읽는 것은 옛 값 때문이다 — 판만 있던 동안 저장된
 *   overrides 가 `cell:true` 를 들고 있을 수 있고, 그때 뜻이 「판」이었다. */
const CELL_LABEL = { line: "윤곽", box: "판", off: "없음" };
const CELL_NEXT = { line: "box", box: false, off: "line" };

function cellMode(l) {
  const v = l.cell;
  if (v === false) return "off";
  if (v === true || v === "box") return "box";
  return "line";
}

function cellCls(l) {
  const m = cellMode(l);
  return m === "off" ? "" : " cell-" + m;
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

  const slides = ((deck.ready && deck.slides) || [])
    .filter((s) => !s.drop && (s.labels || []).length && s.image);
  if (!slides.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "라벨이 있는 장이 없습니다."));
    box.appendChild(el("p", null,
      "배경판(11판) 프로젝트에서 그림 지시문을 만들면 여기에 나옵니다."));
    page.appendChild(box);
    return;
  }

  // ── 저장 ──────────────────────────────────────────────────────────────
  const pending = {};
  const flush = debounce(async () => {
    const keys = Object.keys(pending);
    if (!keys.length) return;
    const patch = { slides: {} };
    for (const k of keys) {
      patch.slides[k] = pending[k];
      delete pending[k];
    }
    try {
      await api(`/api/projects/${state.projectId}/overrides`,
                { method: "POST", body: { patch } });
      dirty.textContent = "저장됨";
      dirty.className = "lb-save ok";
    } catch (e) {
      dirty.textContent = "저장 실패";
      dirty.className = "lb-save err";
      toast("저장 실패: " + e.message, "err");
    }
  }, 500);

  function save(s) {
    // ★ 배열 통째로. 서버 병합이 dict 만 얕게 합치고 배열은 갈아끼운다.
    pending[String(s.src_no ?? s.no)] = { labels: s.labels };
    dirty.textContent = "저장 중…";
    dirty.className = "lb-save";
    flush();
  }

  // ── 뼈대 ──────────────────────────────────────────────────────────────
  const tabs = el("div", "lb-tabs");
  const dirty = el("span", "lb-save ok", "저장됨");
  const stage = el("div", "lb-stage");
  const side = el("div", "lb-side");
  const wrap = el("div", "lb-wrap");
  wrap.append(stage, side);
  page.append(tabs, wrap);

  let cur = slides[0];

  slides.forEach((s) => {
    const b = el("button", "lb-tab", String(s.no));
    b.title = s.title || "";
    b.onclick = () => { cur = s; draw(); };
    s._tab = b;
    tabs.appendChild(b);
  });

  /* ── 모눈종이 켜고 끄기 ──────────────────────────────────────────────
     ★ **보이는 것과 달라붙는 것이 한 스위치다.** 둘을 따로 두면 "격자는
       켜 뒀는데 왜 안 붙나" 가 된다. 꺼져 있으면 눈금도 없고 자유 배치다.
     ★ 고른 것은 브라우저에 남긴다 — 장을 넘길 때마다 다시 켜지 않는다. */
  let grid = localStorage.getItem("lb-grid") !== "off";
  const gbtn = el("button", "lb-gridbtn");
  gbtn.type = "button";
  gbtn.title = `상자를 ${GRID}% 눈금에 맞춰 놓습니다`
             + " — Alt 를 누른 채 끌면 잠깐 벗어납니다";
  const paint = () => {
    gbtn.textContent = grid ? `모눈 ${GRID}%` : "모눈 끔";
    gbtn.classList.toggle("on", grid);
    const g = stage.querySelector(".lb-grid");
    if (g) g.classList.toggle("off", !grid);
  };
  gbtn.onclick = () => {
    grid = !grid;
    localStorage.setItem("lb-grid", grid ? "on" : "off");
    paint();
  };
  tabs.append(gbtn, dirty);

  // ── 그리기 ────────────────────────────────────────────────────────────
  function draw() {
    slides.forEach((s) => s._tab.classList.toggle("on", s === cur));
    stage.replaceChildren();
    side.replaceChildren();

    const box = el("div", "lb-frame");
    const im = el("img");
    im.src = `/api/projects/${state.projectId}/file/${encodeURI(cur.image)}?t=${Date.now()}`;
    im.alt = "";
    box.appendChild(im);
    /* ★ 그림 **위**, 상자 **아래**. 상자보다 위에 깔면 눈금선이 글자를 가로질러
       글이 읽히지 않고, 그림 아래면 그림에 덮여 안 보인다. */
    box.appendChild(el("div", "lb-grid" + (grid ? "" : " off")));
    box.appendChild(el("h2", "lb-title", cur.title || ""));

    cur.labels.forEach((l, i) => box.appendChild(makeBox(l, i, box)));
    stage.appendChild(box);

    const head = el("div", "lb-head");
    head.append(el("strong", null, `${cur.no}. ${cur.title || ""}`),
                el("span", "muted", `라벨 ${cur.labels.length}개`));
    side.appendChild(head);

    cur.labels.forEach((l, i) => side.appendChild(makeRow(l, i)));

    const reset = el("button", "btn", "원래대로");
    reset.title = "손편집을 지우고 지시문이 만든 라벨로 되돌립니다";
    reset.onclick = async () => {
      if (!confirm("이 장의 라벨 손편집을 지울까요?")) return;
      const key = String(cur.src_no ?? cur.no);
      try {
        await api(`/api/projects/${state.projectId}/overrides`,
                  { method: "POST",
                    body: { patch: { slides: { [key]: { labels: null } } } } });
        toast("되돌렸습니다. 다시 열면 반영됩니다.");
      } catch (e) { toast("실패: " + e.message, "err"); }
    };
    side.appendChild(reset);
  }

  // 상자 하나 — 끌면 옮기고, 오른쪽 아래 손잡이를 끌면 폭이 바뀐다
  function makeBox(l, i, frame) {
    const d = el("div", "lb-box" + cellCls(l));
    d.dataset.i = String(i);
    d.style.setProperty("--lx", (l.x ?? 4) + "%");
    d.style.setProperty("--ly", (l.y ?? 14) + "%");
    d.style.setProperty("--lw", (l.w ?? 23) + "%");
    d.append(el("b", null, l.head || ""), el("span", null, l.sub || ""));
    const grip = el("i", "lb-grip");
    d.appendChild(grip);

    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const pct = (e) => {
      const r = frame.getBoundingClientRect();
      return { x: ((e.clientX - r.left) / r.width) * 100,
               y: ((e.clientY - r.top) / r.height) * 100 };
    };

    let mode = null;
    let off = null;

    d.addEventListener("pointerdown", (e) => {
      mode = (e.target === grip) ? "size" : "move";
      const p = pct(e);
      off = { dx: p.x - (l.x ?? 4), dy: p.y - (l.y ?? 14) };
      d.setPointerCapture(e.pointerId);
      d.classList.add("drag");
      e.preventDefault();
    });

    /* 눈금에 맞춘다 → 판 밖으로 안 나가게 자른다 → 0.1 로 떨군다.
       ★ **순서가 이렇다.** 자르고 나서 맞추면 가장자리 상자가 판 밖으로
         반 칸 밀려난다. 맨 끝의 0.1 은 소수점 찌꺼기를 터는 것이다 —
         그게 남으면 `x 72.50000000000001` 이 그대로 저장된다. */
    const q = (v, free) =>
      (grid && !free) ? Math.round(v / GRID) * GRID : v;

    d.addEventListener("pointermove", (e) => {
      if (!mode) return;
      const p = pct(e);
      if (mode === "move") {
        l.x = Math.round(clamp(q(p.x - off.dx, e.altKey), 0, 100 - (l.w ?? 23)) * 10) / 10;
        l.y = Math.round(clamp(q(p.y - off.dy, e.altKey), 0, 96) * 10) / 10;
        d.style.setProperty("--lx", l.x + "%");
        d.style.setProperty("--ly", l.y + "%");
      } else {
        l.w = Math.round(clamp(q(p.x - (l.x ?? 4), e.altKey), MIN_W, MAX_W) * 10) / 10;
        d.style.setProperty("--lw", l.w + "%");
      }
      syncNums(i, l);
    });

    const up = (e) => {
      if (!mode) return;
      mode = null;
      d.classList.remove("drag");
      try { d.releasePointerCapture(e.pointerId); } catch (_) {}
      save(cur);
    };
    d.addEventListener("pointerup", up);
    d.addEventListener("pointercancel", up);
    return d;
  }

  /* 끌기·숫자칸·되돌리기가 모두 여기로 온다 — 값을 화면에 되비추는 곳이
     한 군데여야 셋이 안 어긋난다. `document.activeElement` 는 건드리지 않는다:
     치고 있는 칸을 덮어쓰면 커서가 맨 뒤로 튄다. */
  function syncNums(i, l) {
    const row = side.querySelector(`.lb-row[data-i="${i}"]`);
    if (!row) return;
    for (const key of ["x", "y", "w"]) {
      const inp = row.querySelector(`input[data-k="${key}"]`);
      if (inp && inp !== document.activeElement) inp.value = String(l[key] ?? "");
    }
  }

  // 오른쪽 입력 줄
  function makeRow(l, i) {
    const row = el("div", "lb-row");
    row.dataset.i = String(i);
    row.appendChild(el("span", "lb-n", String(i + 1)));

    const h = el("input", "lb-in");
    h.value = l.head || "";
    h.placeholder = "소제목";

    const p = el("textarea", "lb-in lb-ta");
    p.value = l.sub || "";
    p.placeholder = "설명";
    p.rows = 2;

    const redraw = () => {
      const b = stage.querySelector(`.lb-box[data-i="${i}"]`);
      if (!b) return;
      b.querySelector("b").textContent = l.head || "";
      b.querySelector("span").textContent = l.sub || "";
    };
    h.oninput = () => { l.head = h.value; redraw(); save(cur); };
    p.oninput = () => { l.sub = p.value; redraw(); save(cur); };

    /* ── 셀색 ──────────────────────────────────────────────────────────
       ★ **라벨마다다.** 장 단위 스위치로 만들면 한 장 안에서 한가한 면에 앉은
         글까지 판이 깔려 카드 슬라이드가 된다. 실제로 갈리는 것은 장이 아니라
         라벨 하나하나다 — 같은 장에서 청사진 위의 셋은 판이 필요하고 열린
         바닥 위의 하나는 필요 없다(2026-09-18, 4장).
       ★ 저장은 라벨 배열에 얹혀 `deck.overrides.json` 으로 간다 — 스테이지를
         다시 돌려도 산다. 「원래대로」를 누르면 같이 없어진다. */
    /* ── 좌표를 숫자로 ────────────────────────────────────────────────
       ★ **끌기와 숫자칸은 굵기가 다르다.** 끌기는 모눈 2.5% 에 달라붙어 여럿을
         한 줄에 세우는 일을 하고, 숫자칸은 0.1 단위라 그 다음의 미세 조정을
         한다(2026-09-18: "전체 기준일을 세밀하게 움직이기 위해"). 둘을 같은
         굵기로 맞추면 한쪽이 쓸모가 없어진다.
       ★ **치는 동안에는 칸을 안 건드린다.** 잘린 값을 바로 칸에 써 넣으면
         「82」를 치다가 「77」이 되어 뒤 글자가 엉뚱한 데 붙는다. 칸은 그대로
         두고 **값만** 자르고, 칸을 떠날 때 참값으로 맞춰 준다.
       ★ 빈 칸·`-` 만 있는 중간 상태에서는 **아무것도 안 한다.** 지우는 중에
         0 으로 튀면 상자가 구석으로 날아간다. */
    const foot = el("div", "lb-foot");
    const lim = {
      x: () => [0, 100 - (l.w ?? 23)],
      y: () => [0, 96],
      w: () => [MIN_W, MAX_W],
    };
    for (const [key, cap] of [["x", "x"], ["y", "y"], ["w", "폭"]]) {
      const box = el("label", "lb-num");
      box.appendChild(el("span", null, cap));
      const inp = el("input");
      inp.type = "number";
      inp.step = "0.1";
      inp.dataset.k = key;
      inp.value = String(l[key] ?? "");
      inp.oninput = () => {
        const v = parseFloat(inp.value);
        if (!Number.isFinite(v)) return;
        const [lo, hi] = lim[key]();
        l[key] = Math.round(Math.min(hi, Math.max(lo, v)) * 10) / 10;
        const b = stage.querySelector(`.lb-box[data-i="${i}"]`);
        if (b) b.style.setProperty("--l" + key, l[key] + "%");
        save(cur);
      };
      // 칸을 떠나면 참값으로. 폭이 줄면 x 의 상한도 같이 움직이므로 셋 다 맞춘다
      inp.onblur = () => syncNums(i, l);
      box.appendChild(inp);
      foot.appendChild(box);
    }
    const cb = el("button", "lb-cell");
    cb.type = "button";
    cb.title = "글자 뒤 처리 — 윤곽(기본) → 판 → 없음 순으로 바뀝니다."
             + " 도면처럼 바탕이 복잡한 자리만 판으로 올리세요";
    const paintCell = () => {
      const m = cellMode(l);
      cb.textContent = "셀색 " + CELL_LABEL[m];
      cb.classList.toggle("on", m !== "off");
      const b = stage.querySelector(`.lb-box[data-i="${i}"]`);
      if (b) b.className = "lb-box" + cellCls(l);
    };
    cb.onclick = () => {
      // ★ 늘 **명시값**으로 적는다. 「값이 없음」은 윤곽이라, 끈 것을 비워 두면
      //   다음에 열 때 도로 윤곽이 된다.
      l.cell = CELL_NEXT[cellMode(l)];
      paintCell();
      save(cur);
    };
    paintCell();
    foot.appendChild(cb);

    row.append(h, p, foot);
    return row;
  }

  draw();
  paint();
}
