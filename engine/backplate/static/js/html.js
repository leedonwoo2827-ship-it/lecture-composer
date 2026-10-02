/* 원고 HTML — 참고 원고의 한 항목을 **글 그대로** 얹은 장에서, 줄이 몇 초에
 * 뜰지를 정한다.
 *
 *   위     번호 탭 (원고 장만 · 손으로 맞춘 장은 진하게)
 *   좌 70  실물 면 — 그 시각에 화면이 실제로 어떻게 보이는지
 *   우 30  줄 목록 — 줄마다 시각 칸
 *
 * ★ 왼쪽 미리보기는 **고른 줄이 뜨는 순간**을 보여 준다(`?at=`). 목록에서 줄을
 *   누르면 그 시각의 화면이 그대로 뜬다 — 숫자만 고치고 결과를 상상하게 두면,
 *   실제로 어떻게 보이는지는 영상을 다 굽고 나서야 알게 된다.
 *
 * ★ 시각은 **초**로 저장하고 화면에는 `0:04.5` 로 보인다. 사람은 분:초로 생각하고
 *   기계는 초로 계산한다 — 그 번역을 사람에게 시키지 않는다.
 *
 * ★ 이 화면은 **혼자 선다.** 텍스트·이미지·영상 화면과 코드를 나눠 쓰지 않는다.
 */
"use strict";

import { el, api, icon, toast, debounce, fitFrame } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";

export const meta = {
  title: "원고 HTML",
  subtitle: "줄마다 몇 초에 뜰지 정합니다. 왼쪽은 그 순간의 실제 화면입니다",
  actions: () => {
    /* ★ 그림 지시문을 여기서 만든다 — **목차가 확정된 뒤**라야 하기 때문이다.
       그림 파일은 번호로 이름이 붙는다(`003.png` = 3번 장). 번호가 아직 흔들리는
       자리에 이 버튼을 두면, 만들어 둔 지시문이 다음 장 것이 되어 버린다.
       두 단계를 이어서 돈다 — 지시문을 원장에 채우고(S3a), 아홉 칸 JSON 으로
       내보낸다(S3b). 원고가 `data-img` 를 들고 왔으면 S3a 는 Claude 를 안 부른다. */
    const mk = el("button", "btn");
    mk.type = "button";
    mk.append(icon("image", 14), el("span", null, "이미지 JSON 만들기"));
    mk.onclick = () => makePrompts(mk);

    /* ★ **받는 버튼을 따로 둔다.** 예전에는 한 버튼이 내보내기와 받기를 겸했는데,
       그림을 만들어 놓고도 "뭘 눌러야 붙나" 를 매번 물어야 했다(2026-08-14).
       두 일은 시점이 다르다 — 내보내기는 그림 만들기 **전**, 받기는 **후**다. */
    const ld = el("button", "btn primary");
    ld.type = "button";
    ld.append(icon("download", 14), el("span", null, "만든 이미지 불러오기"));
    ld.onclick = () => loadImages(ld);

    /* ★ **그림 굽기 — 터미널 둘을 하나로 만든 자리.** 예전에는 이 버튼이
       없어서, 사람이 09_이미지/이미지프롬프트.json 을 들고 8765 포트의 다른
       앱으로 건너가 한 장씩 눌렀다. 그 앱을 imgstudio/ 로 들여왔으므로 이제
       여기서 바로 돈다(S3c → S3b → S8).
       ★ **구독 할당량을 쓴다.** 이어하기가 되므로(있는 번호는 건너뜀) 두세 장만
         먼저 굽고 눈으로 본 뒤 나머지를 돌리는 것이 정석이다. */
    const bake = el("button", "btn");
    bake.type = "button";
    bake.title = "이미지프롬프트.json 을 그대로 넣어 09_이미지/003.png 로 굽습니다"
               + " — 있는 번호는 건너뜁니다";
    bake.append(icon("wand", 14), el("span", null, "그림 굽기"));
    bake.onclick = () => bakeImages(bake);

    const a = el("a", "btn");
    a.href = "/preview/" + (state.projectId || 0);
    a.target = "_blank";
    a.rel = "noopener";
    a.append(icon("slide", 14), el("span", null, "슬라이드 보기"));
    return [mk, bake, ld, a];
  },
};

/* 그림 폴더를 다시 훑어 장에 붙이고, 덱까지 조립한다.
   ★ 조립까지 하는 이유: 붙이기만 하면 화면이 그대로라 "안 됐다" 로 보인다.
     둘 다 결정론이라 Claude 를 안 부르고 돈이 들지 않는다. */
async function loadImages(btn) {
  const pid = state.projectId;
  if (!pid) return;
  const was = btn.innerHTML;
  btn.disabled = true;
  try {
    for (const [key, what] of [["s3b-images", "그림 찾는 중"],
                               ["s8-assemble", "덱에 붙이는 중"]]) {
      btn.textContent = what + "…";
      let j = await api(`/api/projects/${pid}/stages/${key}/run`,
                        { method: "POST", body: { force: true } });
      while (j.status === "running" || j.status === "queued") {
        await new Promise((r) => setTimeout(r, 700));
        j = await api(`/api/jobs/${j.job_id}`);
      }
      if (j.status === "error") throw new Error((j.log || []).slice(-1)[0] || key);
    }
    const d = await api(`/api/projects/${pid}/stages/s3b-images`).catch(() => null);
    const got = Object.keys((d && d.data && d.data.images) || {}).length;
    const need = ((d && d.data && d.data.targets) || []).length;
    if (!got) {
      toast(`아직 그림이 없습니다 — 09_이미지 폴더에 002.png 처럼 넣어 주세요`);
    } else {
      toast(`그림 ${got}/${need}장이 붙었습니다 — «슬라이드 보기» 로 확인하세요`);
    }
  } catch (e) {
    toast("실패: " + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = was;
  }
}

/* 두 단계를 차례로 돌리고, 끝나면 **어디에 무엇이 생겼는지**를 말한다.
   파일 경로를 안 알려 주면 사람이 폴더를 뒤져야 한다 — 이 앱과 이미지 스튜디오의
   접점은 폴더 하나뿐이라, 그 폴더가 어디인지가 곧 사용법이다. */
/* 그림을 실제로 굽고, 붙이고, 조립까지 한다.
   ★ S3c 가 끝나면 바로 S3b(폴더 다시 훑기) → S8(조립) 로 이어야 한다.
     안 이으면 그림이 와 있는데도 화면이 그대로라 "안 됐다" 로 보인다. */
async function bakeImages(btn) {
  const pid = state.projectId;
  if (!pid) return;
  const was = btn.innerHTML;
  btn.disabled = true;
  try {
    for (const [key, what] of [["s3c-images-run", "그림 굽는 중"],
                               ["s3b-images", "붙이는 중"],
                               ["s8-assemble", "조립하는 중"]]) {
      btn.textContent = what + "…";
      const job = await api(`/api/projects/${pid}/stages/${key}/run`,
                            { method: "POST", body: {} });
      let j = job;
      while (j.status === "running" || j.status === "queued") {
        await new Promise((r) => setTimeout(r, 1500));
        j = await api(`/api/jobs/${j.job_id}`);
        // 진행 줄을 버튼에 그대로 비춘다 — 80장이면 오래 걸린다
        const last = (j.log || []).slice(-1)[0];
        if (last) btn.textContent = String(last).slice(0, 28);
      }
      if (j.status === "error") throw new Error((j.log || []).slice(-1)[0] || key);
    }
    toast("그림을 구웠습니다.");
    location.reload();
  } catch (e) {
    toast("실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = was;
  }
}

async function makePrompts(btn) {
  const pid = state.projectId;
  if (!pid) return;
  const was = btn.innerHTML;
  btn.disabled = true;
  try {
    /* ★ **판은 이제 고르지 않는다 — 전면(full) 하나다**(2026-09-18).
       지시문을 쓰기 **전에** 박아 둔다. s3a 가 `image_fit` 을 읽어 글자를
       그림에 인쇄할지 말지를 정하므로, 여기서 안 박으면 값이 없는 프로젝트가
       기본값 "frame"(액자) 지시문을 받아 버린다.
       ★ 지난 프로젝트를 열어 이 버튼을 누르면 배경판(plate)이든 액자든
         **전면으로 끌려온다.** 지시문을 다시 쓴다는 것은 그림을 다시
         굽는다는 뜻이니 그편이 맞다 — 굽지 않고 둔 지난 영상은 이 버튼을
         안 지나므로 그대로 남는다. */
    await api(`/api/projects/${pid}/image-swap`,
              { method: "POST", body: { image_swap: true, image_fit: "full" } });
    for (const [key, what] of [["s3a-imgprompt", "지시문 쓰는 중"],
                               ["s3b-images", "JSON 내보내는 중"]]) {
      btn.textContent = what + "…";
      const job = await api(`/api/projects/${pid}/stages/${key}/run`,
                            { method: "POST", body: {} });
      let j = job;
      while (j.status === "running" || j.status === "queued") {
        await new Promise((r) => setTimeout(r, 700));
        j = await api(`/api/jobs/${j.job_id}`);
      }
      if (j.status === "error") throw new Error((j.log || []).slice(-1)[0] || key);
    }
    const d = await api(`/api/projects/${pid}/stages/s3b-images`).catch(() => null);
    const n = (d && d.data && d.data.prompts) || 0;
    const dir = (d && d.data && d.data.dir) || "";
    /* ★ 이 버튼은 **내보내기만** 한다. 온 그림을 붙이는 것은 옆의 «만든 이미지
       불러오기» 다 — 한 버튼이 둘을 겸하니 "지금 누르면 무엇이 되나" 를 매번
       물어야 했다(2026-08-14). 시점이 다른 일은 버튼도 다른 게 맞다. */

    /* ★ 만들었다는 말만 하지 않고 **그 폴더를 열고, 경로를 클립보드에 담는다.**
       이미지 스튜디오는 「출력 폴더」에 경로를 **붙여넣어야** 한다 — 탐색기를
       띄워 주기만 하면 사람이 주소창에서 경로를 다시 복사해야 하고, 그 사이에
       엉뚱한 폴더(다른 앱의 assets)가 그대로 남아 그림이 딴 데로 간다.
       그림이 나오는 자리와 지시문이 나온 자리가 **같은 폴더**인 것이 이 앱과
       스튜디오의 유일한 접점이다. */
    if (dir) {
      try { await navigator.clipboard.writeText(dir); } catch { /* 권한 없으면 그냥 넘어간다 */ }
    }
    toast(`이미지 JSON ${n}개 · 폴더 경로를 복사했습니다 — 스튜디오의 «출력 폴더» 에 붙여넣으세요`);
    await api(`/api/projects/${pid}/reveal?step=images`, { method: "POST", body: {} })
      .catch(() => { /* 폴더를 못 열어도 경로는 이미 손에 있다 */ });
  } catch (e) {
    toast("실패: " + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = was;
  }
}

/* `0:04.5` ↔ 초. 사람이 `4.5` 로 쳐도 `0:04.5` 로 쳐도 받는다. */
const fmt = (s) => {
  const v = Math.max(0, Number(s) || 0);
  const m = Math.floor(v / 60);
  const r = v - m * 60;
  return `${m}:${(r < 10 ? "0" : "") + r.toFixed(1)}`;
};
const parse = (t) => {
  const s = String(t || "").trim();
  if (!s) return null;
  if (s.includes(":")) {
    const [m, r] = s.split(":");
    const v = (parseInt(m, 10) || 0) * 60 + (parseFloat(r) || 0);
    return Number.isFinite(v) ? Math.max(0, v) : null;
  }
  const v = parseFloat(s);
  return Number.isFinite(v) ? Math.max(0, v) : null;
};

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
    .filter((s) => s.media_kind === "html" && !s.drop);
  if (!slides.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "원고에서 온 장이 없습니다."));
    box.appendChild(el("p", null,
      "참고자료에 HTML 원고를 넣고 «원고 구조 읽기» 를 돌리면 여기에 나옵니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("layers", 14), el("span", null, "현황판 열기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  const hd = el("div", "deck-head");
  const sum = el("p", "deck-sub");
  const strip = el("div", "numstrip");
  hd.append(sum, strip);
  const stage = el("div", "vstage");
  page.append(hd, stage);

  const chips = {};
  // 손으로 맞춘 장인가 — `html_at` 에 값이 하나라도 있으면 그렇다
  const handOf = (s) => Object.keys(s.html_at || {}).length > 0;
  const want = Number((ctx && ctx.params && ctx.params.get("n")) || 0);
  let cur = slides.some((x) => x.no === want) ? want : slides[0].no;

  drawSum();
  drawStrip();
  show(cur);

  function drawSum() {
    const n = slides.filter(handOf).length;
    const lines = slides.reduce((a, s) => a + (s.html_blocks || 0), 0);
    sum.textContent = `${slides.length}장 · 줄 ${lines}개`
      + (n ? ` · 손으로 맞춘 장 ${n}` : " · 전부 자동 배분");
  }

  function drawStrip() {
    strip.textContent = "";
    for (const k of Object.keys(chips)) delete chips[k];
    for (const s of slides) {
      const c = el("button", "num-chip" + (s.no === cur ? " active" : "")
                             + (handOf(s) ? " done" : ""));
      c.type = "button";
      c.append(el("i", "num-dot"), el("span", null, String(s.no)));
      c.title = `${s.no}. ${s.title || ""} — 줄 ${s.html_blocks || 0}개`
        + (handOf(s) ? " · 손으로 맞춤" : "");
      c.onclick = () => show(s.no);
      strip.appendChild(c);
      chips[s.no] = c;
    }
  }

  function markStrip(no) {
    for (const [k, c] of Object.entries(chips)) {
      c.classList.toggle("active", Number(k) === no);
      const s = slides.find((x) => x.no === Number(k));
      if (s) c.classList.toggle("done", handOf(s));
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
    fr.title = `슬라이드 ${s.no}`;
    st.appendChild(fr);
    /* ★ 1920 폭으로 그리고 화면 폭에 맞춰 줄인다. 덱은 **설계 해상도가 1920×1080**
     * 이고(영상도 그 크기로 찍힌다), 원고 상자 폭이 1536px 로 못박혀 있다. 더 좁게
     * 그리면 그 상자가 잘려서, 여기서 본 것과 영상이 달라진다. */
    fitFrame(st, fr, 1920);

    // 그 시각의 화면을 보여 준다 — `at` 이 null 이면 다 뜬 상태
    let atNow = null;
    const reload = () => {
      const q = atNow == null ? "" : `&at=${atNow}`;
      fr.src = `/preview/${state.projectId}?n=${s.no}${q}&t=${Date.now()}#${s.no}`;
    };
    reload();

    // ── 우 30: 줄마다 시각 ──
    const side = el("div", "iside");
    const times = (s.html_times || []).slice();
    const texts = (s.html_text || []).slice();
    const n = s.html_blocks || times.length || texts.length;

    const lb = el("div", "fm-lb");
    side.appendChild(lb);
    const list = el("div", "hb-list");
    side.appendChild(list);

    function label() {
      const last = times.length ? times[times.length - 1] : 0;
      const dur = (s.audio && s.audio.sec) || (s.narration && s.narration.est_sec) || 0;
      lb.textContent = `줄 ${n}개 · 마지막 ${fmt(last)}`
        + (dur ? ` / 음성 ${fmt(dur)}` : " · 대본 전(어림값)");
    }

    function paint() {
      list.textContent = "";
      for (let k = 0; k < n; k++) {
        list.appendChild(row(k));
      }
      label();
    }

    function row(k) {
      const hand = (s.html_at || {})[String(k)] != null;
      const r = el("div", "hb-row" + (hand ? " hand" : "")
                          + (atNow != null && times[k] === atNow ? " on" : ""));

      const t = el("input", "hb-at");
      t.type = "text";
      t.value = fmt(times[k] || 0);
      t.title = hand ? "손으로 맞춘 값" : "자동 배분값 — 고치면 이 값이 이깁니다";
      t.onfocus = () => { atNow = times[k] || 0; reload(); paintOn(); };
      t.onchange = () => {
        const v = parse(t.value);
        if (v == null) { t.value = fmt(times[k] || 0); return; }
        setAt(k, v);
      };
      r.appendChild(t);

      const txt = el("div", "hb-text", texts[k] || "(빈 줄)");
      txt.onclick = () => { atNow = times[k] || 0; reload(); paintOn(); };
      r.appendChild(txt);

      if (hand) {
        const rm = el("button", "btn sm ghost hb-undo");
        rm.type = "button";
        rm.textContent = "자동";
        rm.title = "손으로 맞춘 값을 지우고 자동 배분으로 되돌립니다";
        rm.onclick = () => setAt(k, null);
        r.appendChild(rm);
      }
      return r;
    }

    function paintOn() {
      [...list.children].forEach((r, k) =>
        r.classList.toggle("on", atNow != null && times[k] === atNow));
    }

    /* 저장 — `html_at` 은 **번호를 키로 하는 객체**다. 오버라이드 병합이 객체는
       깊게 합치고 배열은 통째로 갈아치우므로, 배열이면 한 줄만 고쳐도 나머지를
       전부 같이 보내야 하고 그 사이에 다른 곳에서 고친 값이 날아간다.
       `null` 은 "자동으로 되돌려라" 는 뜻이다. */
    const save = debounce(async (patch) => {
      try {
        await api(`/api/projects/${state.projectId}/overrides`,
                  {method: "POST", body: {patch: {slides: {[s.no]: {html_at: patch}}}}});
        const d = await api(`/api/projects/${state.projectId}/deck`);
        const fresh = (d.slides || []).find((x) => x.no === s.no);
        if (fresh) {
          s.html_at = fresh.html_at || {};
          s.html_times = fresh.html_times || [];
          times.length = 0;
          times.push(...s.html_times);
        }
        paint(); markStrip(s.no); drawSum(); reload();
      } catch (e) {
        toast("저장하지 못했습니다: " + e.message, "err");
      }
    }, 350);

    function setAt(k, v) {
      s.html_at = s.html_at || {};
      if (v == null) delete s.html_at[String(k)];
      else s.html_at[String(k)] = v;
      if (v != null) times[k] = v;
      atNow = v;
      save({[String(k)]: v});
    }

    const bar = el("div", "imgdrop-bar");
    const all = el("button", "btn sm");
    all.type = "button";
    all.textContent = "전체 보기";
    all.title = "시각을 무시하고 다 뜬 상태로 봅니다";
    all.onclick = () => { atNow = null; reload(); paintOn(); };
    bar.appendChild(all);

    const reset = el("button", "btn sm ghost");
    reset.type = "button";
    reset.textContent = "전부 자동으로";
    reset.title = "이 장에서 손으로 맞춘 값을 모두 지웁니다";
    reset.onclick = () => {
      const patch = {};
      for (const k of Object.keys(s.html_at || {})) patch[k] = null;
      if (!Object.keys(patch).length) { toast("손으로 맞춘 값이 없습니다"); return; }
      s.html_at = {};
      save(patch);
    };
    bar.appendChild(reset);
    side.appendChild(bar);

    side.appendChild(el("div", "imgdrop-path",
      "왼쪽 화면은 고른 줄이 뜨는 그 순간입니다. "
      + "음성이 붙으면 그 길이에 맞춰 자동 배분이 다시 계산되고, "
      + "손으로 적은 값은 그 위에서 그대로 남습니다."));

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
