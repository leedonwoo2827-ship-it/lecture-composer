/* 현황판 — **어느 씬의 어느 작업을 OK 했나.**
 *
 * 이 화면이 답하는 질문은 하나다. 그래서 모양도 하나다 — **씬 × 4열 매트릭스.**
 *
 *      씬   텍스트   이미지   영상   음성·자막      제목
 *       1     ✓       —       —       ·          CAIND ODA Expert
 *       2     ✓       —       ✓       ·          내 경력을 6개 축으로…
 *       3     ·       —       —       ·          개인과 기업, 대시보드가…
 *
 *   ✓  확정했다        ·  아직 — **누르면 그걸 고치는 화면의 그 장으로 간다**
 *   —  해당 없음        …  앞 칸이 먼저다
 *
 * ★ **왜 4열인가.** 확정할 것은 넷이다 — 화면에 박히는 글, 그림, 영상, 소리.
 *   `코드` 는 열을 따로 주지 않는다. 코드 장도 결국 텍스트 슬라이드이고 근거
 *   목록이 붙을 뿐이라, 사람이 확정할 것은 문구 하나다. 열을 늘리면 매번 `—` 만
 *   찍히는 칸이 생기고, 그런 칸은 읽는 사람을 지치게 한다.
 *
 * ★ 카드로 묶어 봤는데 틀렸다. "텍스트 37장 중 12장" 은 진행률이지 **할 일 목록이
 *   아니다.** 어느 장이 남았는지 알려면 결국 덱으로 건너가 하나씩 봐야 했다.
 *   매트릭스는 빈 칸이 그대로 할 일이고, 누르면 바로 거기로 간다.
 *
 * ★ 맨 아래 덱은 **감싸는 것**이다. 위가 다 차야 굽는다.
 */
"use strict";

import { $, el, api, icon, toast } from "./util.js";
import { state, getStages, invalidateStages } from "./store.js";
import { navigate } from "./shell.js";
import { runSteps } from "./runner.js";

export const meta = {
  title: "현황판",
  subtitle: "어느 씬의 어느 작업을 확정했나. 빈 칸을 누르면 그걸 고치는 화면으로 갑니다",
};

/* 4열 — 확정 단위.
 *   has   이 장에 해당하는 일인가
 *   ok    확정했는가
 *   go    고치러 가는 곳 (그 장으로)
 *   make  재료를 만드는 단계들 */
const COLS = [
  {
    id: "text", short: "텍스트", title: "슬라이드 텍스트",
    make: ["s2b-outline", "s5-decisions", "s7-copy"],
    has: () => true,
    ok: (s) => !!(s.approve || {}).slide,
    go: "/text",
  },
  {
    /* 원고 장 — 만드는 단계는 «원고 구조 읽기»(s2c) 하나다. 그게 돌면 글과
       줄 등장 시각이 같이 들어온다. "됐다" 의 기준은 **줄이 있는가** — 시각을
       손으로 맞추는 것은 다듬는 일이지 없으면 안 되는 일이 아니다(자동 배분이
       늘 채워져 있다). */
    id: "html", short: "원고", title: "원고 HTML",
    make: ["s2c-capture"],
    has: (s) => s.media_kind === "html" && !s.image_swap,
    ok: (s) => (s.html_blocks || 0) > 0,
    go: "/html",
  },
  {
    /* ★ 그림으로 갈 원고 — **원고 장과 다른 유형**이다. 같은 `media_kind:"html"`
       이지만 가는 길이 다르다: 글은 안 뜨고 그림 한 판이 몸통을 대신한다.
       원고를 넣을 때 어느 쪽인지 정하고, 여기서는 **그림이 왔는가**만 본다 —
       작정(`image_swap`)은 그림보다 먼저 서고, 그림은 나중에 온다. 둘을 한
       유형으로 묶으면 「그림 기다리는 장」이 어디에도 안 보인다. */
    id: "swap", short: "그림 원고", title: "그림으로 갈 원고",
    make: ["s3a-imgprompt", "s3b-images"],
    has: (s) => s.media_kind === "html" && !!s.image_swap,
    ok: (s) => !!s.image,
    go: "/html",
  },
  /* ★ 「삽입 이미지」(text_image) 칸은 **뺐다**(2026-08-14). 그 레인은 화면
     캡처로 만들던 옛 길(`capture.mode:"image"`)이고, 지금 원고는 전부 `html` 로
     들어온다. 그림은 위 「그림으로 갈 원고」 한 유형으로 모은다 — 같은 일을 하는
     칸이 둘이면 어느 쪽을 눌러야 하는지 매번 물어야 한다.
     레인 자체는 살아 있다(s3b 가 여전히 받는다) — 현황판에만 안 세운다. */
  {
    id: "video", short: "영상", title: "삽입 영상",
    make: ["s1-frames", "s3-caption"],
    has: (s) => !!s.video_id,
    ok: (s) => !!(s.approve || {}).mute,
    go: "/video",
  },
  {
    id: "script", short: "음성·자막", title: "음성 · 자막",
    make: ["s6-script", "s10-tts", "s11-audio"],
    has: () => true,
    ok: (s) => !!(s.approve || {}).script,
    // ★ 맨 마지막 — 영상 길이가 정해져야 대본이 그 안에 들어가는지 판정된다
    after: "video",
    go: "/deck",
  },
];

const SEED = ["s1-frames", "s2-repo", "s0a-ask", "s0-prd", "s2b-outline"];
const BAKE = ["s8-assemble", "s9-render"];
const STATE_LABEL = {
  missing: "안 함", stale: "다시 필요", fresh: "됨",
  degraded: "일부만", skipped: "건너뜀",
};
const RANK = {missing: 0, stale: 1, skipped: 2, degraded: 3, fresh: 4};

export async function mount(root) {
  const page = el("div", "page bpage");
  root.appendChild(page);

  if (!state.projectId) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 프로젝트가 없습니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("plus", 14), el("span", null, "새 발표 만들기"));
    b.onclick = () => navigate("/start");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  const hd = el("div", "deck-head");
  const sub = el("p", "deck-sub");
  hd.appendChild(sub);
  page.appendChild(hd);

  /* ★ 장 예산 — **적게 시작해서 늘린다.**
   * 장마다 문구·이미지·영상·음성 넷을 사람이 확정한다. 40장이면 확인만 160번이라
   * 끝까지 못 간다. 14장으로 끝까지 한 번 가 보고, 모자라면 늘려서 다시 짠다.
   * 참고로 부사장이 준 레퍼런스 덱도 17장이다. */
  const bud = el("div", "budget");
  page.appendChild(bud);

  const head = el("div", "mx-head");
  const mx = el("div", "mx");
  const bakeBox = el("div", "bwrap");
  page.append(head, mx, bakeBox);

  const more = el("details", "bmore");
  const sm = el("summary");
  // ★ 스테이지 화면을 없앤 뒤로 **여기가 유일한 실행기**다. 레포 다시 받기,
  //   기획서 다시 만들기가 전부 이 안에 있으므로 이름이 그렇게 읽혀야 한다.
  sm.textContent = "모든 단계 — 상태 보기 · 다시 돌리기";
  const table = el("div", "btable");
  more.append(sm, table);
  page.appendChild(more);

  let timer = null;
  let lastStages = [];        // 단계 → 사람이 읽는 이름 (runner 에 넘긴다)
  let onlyLeft = false;
  let bySec = false;
  await draw();
  page.addEventListener("x-unmount", () => clearInterval(timer));

  async function drawBudget(byKey, job, deck) {
    bud.textContent = "";
    /* ★ 캡처 기반 덱(s2c-capture)은 장수가 h2 경계로 이미 정해져 있다 —
     * "N장으로 다시 짜기" 는 S2b(AI 구조설계)를 부르는데, 이 덱은 S0-prd 를
     * 아예 안 거쳐서 그 단계가 돌지도 않는다. 참고자료 늘리려면 이미지를
     * 보고 그때 다시 캡처하면 되므로, 여기 예산 UI 는 그냥 숨긴다. */
    const capSt = byKey["s2c-capture"];
    if (capSt && capSt.state !== "missing") {
      // ★ .budget 이 display:flex 를 명시해서 [hidden] 속성이 안 먹는다 —
      //   style.display 로 직접 끈다.
      bud.style.display = "none";
      return;
    }
    bud.style.display = "";
    let cur = 14;
    try { cur = (await api(`/api/projects/${state.projectId}`)).slide_budget || 14; }
    catch { /* 기본값으로 간다 */ }

    bud.append(el("span", "budget-k", "장 예산"));
    const row = el("div", "budget-row");
    for (const n of [14, 20, 26, 32, 40]) {
      const b = el("button", "budget-b" + (n === cur ? " on" : ""));
      b.type = "button";
      b.textContent = n;
      b.disabled = !!(job && job.running);
      b.onclick = async () => {
        if (n === cur) return;
        try {
          await api(`/api/projects/${state.projectId}/budget`,
                    {method: "POST", body: {slide_budget: n}});
          invalidateStages();
          toast(`${n}장으로 바꿨습니다 — 구조 설계를 다시 돌려야 반영됩니다`);
          await draw();
        } catch (e) { toast("바꾸지 못했습니다: " + e.message, "err"); }
      };
      row.appendChild(b);
    }
    bud.appendChild(row);

    const st = byKey["s2b-outline"];
    const made = ((deck.ready && deck.slides) || []).length;
    const msg = el("span", "budget-msg");
    if (st && st.state === "stale" && made) {
      msg.textContent = `지금 덱은 ${made}장 — 다시 짜야 ${cur}장이 됩니다`;
      const b = el("button", "btn sm primary");
      b.type = "button";
      b.textContent = `${cur}장으로 다시 짜기`;
      b.disabled = !!(job && job.running);
      b.onclick = () => runAll(["s2b-outline"], b);
      bud.append(msg, b);
    } else {
      msg.textContent = made ? `지금 덱 ${made}장` : "장마다 문구·이미지·영상·음성을 확정합니다 — 적게 시작하세요";
      bud.appendChild(msg);
    }

    const dropped = ((st && st.warnings) || []).length;
    void dropped;
  }

  async function draw() {
    let data, deck = {};
    try {
      data = await getStages(true);
      deck = await api(`/api/projects/${state.projectId}/deck`);
    } catch (e) {
      mx.textContent = "";
      mx.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
      return;
    }
    lastStages = data.stages || [];
    const byKey = Object.fromEntries(lastStages.map((s) => [s.key, s]));
    // 뺀 장은 셈에서 빠진다 — 발표에 안 나가는 것을 "남은 일" 로 세면 안 된다
    const slides = ((deck.ready && deck.slides) || []).filter((s) => !s.drop);
    const nDrop = ((deck.ready && deck.slides) || []).length - slides.length;
    const job = data.job;
    const cost = (data.stages || []).reduce((n, s) => n + (s.cost_usd || 0), 0);

    clearInterval(timer);
    if (job && job.running) timer = setInterval(draw, 2000);

    await drawBudget(byKey, job, deck);

    if (!slides.length) {
      head.textContent = "";
      mx.textContent = "";
      sub.textContent = `아직 슬라이드가 없습니다 · 지금까지 $${cost.toFixed(2)}`
        + (job && job.running ? ` · 지금 ${job.label} 돌아가는 중` : "");
      mx.appendChild(seedBox(byKey, job));
      drawBake(byKey, job, 1);
      drawTable(data, job);
      return;
    }

    const tot = COLS.map((c) => {
      const mine = slides.filter(c.has);
      return {c, all: mine.length, ok: mine.filter(c.ok).length};
    });
    const okN = tot.reduce((n, t) => n + t.ok, 0);
    const allN = tot.reduce((n, t) => n + t.all, 0);
    const left = allN - okN;
    sub.textContent = `${slides.length}씬 · 확정 ${okN}/${allN}`
      + (left ? ` · 남은 칸 ${left}개` : " · 전부 확정")
      + (nDrop ? ` · 뺀 장 ${nDrop}개` : "")
      + ` · $${cost.toFixed(2)}`
      + (job && job.running ? ` · 지금 ${job.label} 돌아가는 중` : "");

    // ── 머리: 행별(=확정 단위) 진행 + 재료 만들기 ──
    head.textContent = "";
    const filt = el("div", "mx-filt");
    for (const t of tot) {
      const todo = t.c.make.map((k) => byKey[k])
        .filter((x) => x && x.implemented && x.state !== "fresh" && !x.blocked);
      if (!todo.length) continue;
      const b = el("button", "btn sm primary");
      b.type = "button";
      b.append(icon("wand", 11), el("span", null,
        `${t.c.short} 재료` + (todo.some((x) => x.kind === "claude") ? " (유료)" : "")));
      b.disabled = !!(job && job.running);
      b.onclick = () => runAll(todo.map((x) => x.key), b);
      filt.appendChild(b);
    }
    const only = el("button", "kind-chip" + (onlyLeft ? " on" : ""));
    only.type = "button";
    only.textContent = onlyLeft ? "남은 씬만 보는 중" : "남은 씬만 보기";
    only.onclick = () => { onlyLeft = !onlyLeft; draw(); };
    filt.appendChild(only);
    head.appendChild(filt);

    // ── 몸통: **4행 × 20열.** 표를 나눠 스크롤을 없앤다 ──
    const done = {};
    for (const t of tot) done[t.c.id] = t.all === 0 || t.ok === t.all;

    const sections = (deck.ready && deck.sections) || [];
    const secTitle = Object.fromEntries(sections.map((x) => [x.id, x.title]));
    const secIdx = Object.fromEntries(sections.map((x, i) => [x.id, i]));
    const LANE = ["#9a4d33", "#c0714f", "#7d6a55", "#5c6b62", "#8a7f9a", "#a8894f"];

    let show = slides;
    if (onlyLeft) {
      show = slides.filter((s) =>
        COLS.some((c) => c.has(s) && !c.ok(s)));
    }

    mx.textContent = "";
    if (!show.length) {
      mx.appendChild(el("div", "empty", "남은 칸이 없습니다. 이제 구우면 됩니다."));
    }

    /* ★ 한 표에 20씬. 37장이면 표 둘이 된다.
     * 세로로 37줄을 세우면 반드시 스크롤이 생기고, 스크롤이 생기면 "무엇이 남았나"
     * 를 한눈에 못 본다. 이 화면의 존재 이유가 바로 그 한눈이다. */
    const PER = 20;
    for (let off = 0; off < show.length; off += PER) {
      const chunk = show.slice(off, off + PER);
      const tbl = el("div", "gx");
      tbl.style.setProperty("--n", String(chunk.length));

      // 머리줄 — 씬 번호
      tbl.appendChild(el("div", "gx-lb", ""));
      for (const s of chunk) {
        const b = el("button", "gx-no");
        b.type = "button";
        b.textContent = String(s.no);
        b.style.setProperty("--lane", LANE[(secIdx[s.section] ?? 0) % LANE.length]);
        b.title = `${s.no}. ${s.title || ""}
${secTitle[s.section] || ""}`;
        b.onclick = () => goto(s.video_id ? "/video" : "/text", s.no);
        tbl.appendChild(b);
      }

      // 4행
      for (const t of tot) {
        const lb = el("div", "gx-lb");
        lb.append(el("b", null, t.c.short),
                  el("span", null, `${t.ok}/${t.all}`));
        tbl.appendChild(lb);
        for (const s of chunk) {
          if (!t.c.has(s)) { tbl.appendChild(el("div", "gx-c none", "")); continue; }
          const ok = t.c.ok(s);
          const blocked = !!(t.c.after && !done[t.c.after]);
          const b = el("button", `gx-c ${ok ? "ok" : blocked ? "wait" : "todo"}`);
          b.type = "button";
          b.textContent = ok ? "✓" : blocked ? "·" : "";
          b.title = `${t.c.title} · ${s.no}장 — ${s.title || ""}
`
            + (blocked ? `${COLS.find((c) => c.id === t.c.after).title} 를 먼저`
                       : ok ? "확정함 (눌러서 되돌리기는 아래 ✗)" : "누르면 고치러 갑니다");
          b.onclick = () => {
            if (ok && t.c.id !== "image") {
              unApprove(s.no, t.c.id === "video" ? "mute"
                            : t.c.id === "text" ? "slide" : "script");
            } else {
              goto(t.c.go, s.no);
            }
          };
          tbl.appendChild(b);
        }
      }
      mx.appendChild(tbl);
    }

    // 섹션 범례 — 번호 위 색이 무슨 갈래인지
    if (sections.length) {
      const lg = el("div", "gx-legend");
      sections.forEach((x, i) => {
        const c = el("span", "gx-lg");
        c.style.setProperty("--lane", LANE[i % LANE.length]);
        c.append(el("i", null, ""), el("span", null, x.title || x.id));
        lg.appendChild(c);
      });
      mx.appendChild(lg);
    }

    drawBake(byKey, job, left);
    drawTable(data, job);
  }

  /** 확정 취소 — 되돌릴 수 있어야 찍을 수 있다. */
  async function unApprove(no, key) {
    try {
      await api(`/api/projects/${state.projectId}/overrides`,
                {method: "POST",
                 body: {patch: {slides: {[String(no)]: {approve: {[key]: false}}}}}});
      await draw();
    } catch (e) { toast("되돌리지 못했습니다: " + e.message, "err"); }
  }

  /** 그 칸을 고치는 화면의 **그 장**으로.
   *
   * ★ 주소에 장 번호를 실어 보낸다. 이벤트를 시간차로 쏘던 방식은 화면이 뜨기
   *   전에 신호가 지나가 버렸다 — 8번을 눌러도 1번이 열렸다. 주소는 그런 게 없다.
   */
  function goto(where, no, kind) {
    const q = [no ? `n=${no}` : "", kind ? `kind=${kind}` : ""].filter(Boolean).join("&");
    navigate(q ? `${where}?${q}` : where);
    // 이미 그 화면에 있으면 라우터가 다시 mount 하지 않으므로 신호도 같이 보낸다
    setTimeout(() => dispatchEvent(new CustomEvent("deck:goto",
      {detail: {no, kind}})), 40);
  }

  function madeState(keys, byKey) {
    const ss = keys.map((k) => byKey[k]).filter(Boolean);
    if (!ss.length) return "missing";
    return ss.reduce((w, s) => (RANK[s.state] < RANK[w] ? s.state : w), "fresh");
  }

  function seedBox(byKey, job) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 구조가 없습니다. 재료부터 만듭니다."));
    const todo = SEED.map((k) => byKey[k])
      .filter((x) => x && x.implemented && x.state !== "fresh");
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "재료 만들기 (유료)"));
    b.disabled = !!(job && job.running) || !todo.length;
    b.onclick = () => runAll(todo.map((x) => x.key), b);
    box.appendChild(b);
    return box;
  }

  function drawBake(byKey, job, left) {
    bakeBox.textContent = "";
    const c = el("div", "bcard bcard-wrap" + (left ? " blocked" : ""));
    const h = el("div", "bcard-hd");
    h.append(icon("download", 17), el("h3", null, "덱 — 전체 플로우"));
    c.appendChild(h);
    const ul = el("div", "bsteps");
    for (const s of BAKE.map((k) => byKey[k]).filter(Boolean)) {
      const row = el("div", `bstep s-${s.state}`);
      const l = el("span", "bstep-l");
      l.append(el("i", "bdot"), el("span", null, s.label));
      row.append(l, el("span", "bstate", STATE_LABEL[s.state] || s.state));
      ul.appendChild(row);
    }
    c.appendChild(ul);
    const foot = el("div", "bcard-ft");
    if (left) {
      foot.appendChild(el("span", "bblock",
        `아직 확정 안 한 칸이 ${left}개 — 굽고 나서 고치면 다시 구워야 합니다`));
    }
    const b = el("button", "btn primary sm");
    b.type = "button";
    b.append(icon("wand", 13), el("span", null, "완성본 굽기"));
    b.disabled = !!(job && job.running);
    b.onclick = () => runAll(BAKE, b);
    foot.appendChild(b);
    const a = el("button", "btn sm ghost");
    a.type = "button";
    a.append(el("span", null, "덱 전체 보기"), icon("chevronRight", 12));
    a.onclick = () => navigate("/deck");
    foot.appendChild(a);
    c.appendChild(foot);
    bakeBox.appendChild(c);
  }

  function drawTable(data, job) {
    table.textContent = "";
    for (const s of data.stages || []) {
      const r = el("div", `brow s-${s.state}`);
      const l = el("span", "brow-l");
      l.append(el("i", "bdot"), el("b", null, s.label), el("span", "brow-key", s.key));
      r.appendChild(l);
      const rt = el("span", "brow-r");
      if (s.cost_usd) rt.appendChild(el("span", "bcost", "$" + s.cost_usd.toFixed(2)));
      rt.appendChild(el("span", "bstate", STATE_LABEL[s.state] || s.state));
      if (s.implemented && !s.blocked) {
        const b = el("button", "btn sm");
        b.type = "button";
        b.textContent = s.state === "fresh" ? "다시" : "실행";
        b.disabled = !!(job && job.running);
        b.onclick = () => runAll([s.key], b);
        rt.appendChild(b);
      }
      r.appendChild(rt);
      if ((s.warnings || []).length) r.title = s.warnings.join("\n");
      table.appendChild(r);
    }
  }

  /* ★ 실행은 전부 runner 를 지난다 — 누른 버튼이 시계가 되어 돈다.
   * 예전엔 여기만의 루프가 따로 있어서, 몇 분짜리 단계를 눌러 놓고도
   * 화면이 그대로였다. 사람이 다시 누르면 같은 단계가 두 번 돈다(돈이 두 배). */
  async function runAll(keys, btn) {
    const label = btn && btn.querySelector("span");
    const ok = await runSteps(keys, {
      btn, label,
      names: Object.fromEntries((lastStages || []).map((s) => [s.key, s.label])),
      onStep: (s) => { sub.textContent = s; },
    });
    // ★ 완성본까지 갔으면 그 폴더를 열어 준다 — 다음에 할 일이 거기 있다
    if (ok && keys.includes("s9-render")) {
      try {
        await api(`/api/projects/${state.projectId}/reveal`,
                  {method: "POST"});
      } catch { /* 못 열어도 굽기는 성공이다 */ }
    }
    invalidateStages();
    await draw();
  }
}
