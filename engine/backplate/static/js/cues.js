/* 말하는 순간 — 라벨이 **몇 번째 문장에서 뜨는가**를 맞춘다.
 *
 *   위     번호 탭 (라벨이 있는 장만)
 *   좌 46  라벨마다: 소제목 · 말하는 문장 고르개 · 그때가 몇 초인지 · 그 지점 듣기
 *   우 54  자막 문장 목록 (번호 · 시각 · 글) — 고르개가 가리키는 그 목록이다
 *
 * ★ **왜 음성 다음인가.** 뜨는 시각은 **실측 음성 길이**에서 나온다
 *   (`render/slides.cue_map`). 합성 전에는 가리킬 초가 아예 없어서, 여기를
 *   앞당겨 놓으면 빈 화면만 보게 된다. 그래서 절차상 「음성/자막 굽기」 뒤다.
 *
 * ★ **이 화면이 없던 동안 무슨 일이 있었나.** 라벨 시각이 영상 경로에 안 실려
 *   `i * 1.2초` 받침값으로 떨어졌고, 69초짜리 장의 라벨 여섯이 앞 6초에 다
 *   떴다(2026-09-18 실측). 그걸 고친 뒤에도 **맞는지 볼 자리가 없었다** —
 *   영상을 다 굽고 나서야 알았다. 여기가 그 자리다.
 *
 * ★ **`say_i` 는 1부터 센다.** 지시문 프롬프트가 LLM 에게 그렇게 시키고
 *   (`llm/prompts/imgprompt.md`), `s13b_order` 도 그 숫자를 「N번 문장」이라는
 *   글로 넘긴다. 화면에서 「문장 3」을 고르면 `say_i=3` 이 저장된다.
 *   ★ 받는 쪽(`render/slides.stamp_label_times`)이 이걸 0부터 세는 배열 자리로
 *     읽고 있어서 **모든 라벨이 한 문장씩 늦게 떴다**(2026-09-18 실측). 그쪽을
 *     고쳤다. 여기서 1부터로 저장하는 것이 그 규약이다 — 어기면 다시 밀린다.
 *
 * ★ 저장은 `deck.overrides.json` 이다 — 라벨 **배열을 통째로** 덮는다
 *   (`labels.js` 와 같은 규칙). 그래서 좌표·셀색도 같이 실어 보내야 한다.
 */
"use strict";

import { el, api, icon, toast, debounce } from "./util.js";
import { state } from "./store.js";
import { runSteps } from "./runner.js";

export const meta = {
  title: "말하는 순간",
  subtitle: "라벨이 몇 번째 문장에서 뜰지 맞춥니다",
  /* ── 점검 재설정 ──────────────────────────────────────────────────────
   * ★ **고르는 것과 싣는 것은 다른 일이다.** 고르개는 `deck.overrides.json` 에
   *   바로 저장되지만(오른쪽 «저장됨»), 영상과 점검이 읽는 것은 조립(s8)이
   *   만드는 `10_덱/deck.json` 이다. 그 사이를 안 이으면 다시 골라도 **옛
   *   시각으로 구워지고 점검도 옛것을 짚는다**(2026-09-18).
   * ★ 여기가 맨 윗줄인 이유: 고르고 나서 마지막에 누르는 단추라, 목록 한가운데
   *   있으면 다 고른 뒤에 스크롤해 찾아 올라와야 한다.
   * ★ 슬라이드 보기를 여기 두지 않는다 — 이 화면에서 볼 것은 그림이 아니라
   *   **시각**이고, 그건 아래 재생기로 귀로 확인한다.
   * ★ 둘 다 결정론이라 돈이 안 든다. */
  actions: () => {
    const b = el("button", "btn primary");
    b.type = "button";
    const lab = el("span", null, "점검 재설정");
    b.append(icon("refresh", 14), lab);
    b.title = "고른 문장을 덱에 싣고 점검을 다시 봅니다"
            + " — 미리보기·완성본·영상 렌더가 이 값을 씁니다";
    b.onclick = async () => {
      const ok = await runSteps(["s8-assemble", "s9-render"], {
        btn: b, label: lab,
        names: { "s8-assemble": "덱 조립", "s9-render": "완성본" },
      });
      if (!ok) { toast("싣지 못했습니다 — 현황판에서 무엇이 막혔는지 보세요", "err"); return; }
      // 실은 뒤에 **다시 재 본다.** 방금 고친 것이 반영된 점검이라야 뜻이 있다
      try {
        const r = await api(`/api/projects/${state.projectId}/check`);
        const n = ((r && r.items) || []).length;
        toast(n ? `덱에 실었습니다 — 점검 ${n}건 (영상 렌더링 화면에서 봅니다)`
                : "덱에 실었습니다 — 점검 통과", n ? "" : "ok");
      } catch (_) {
        toast("덱에 실었습니다");
      }
    };
    return [b];
  },
};

const mmss = (v) => {
  const t = Math.max(0, Number(v) || 0);
  return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}.${Math.floor((t % 1) * 10)}`;
};

export async function mount(root) {
  const page = el("div", "page vpage");
  root.appendChild(page);
  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let deck, cues;
  try {
    [deck, cues] = await Promise.all([
      api(`/api/projects/${state.projectId}/deck`),
      api(`/api/projects/${state.projectId}/cues`),
    ]);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }

  const cueOf = (no) => (cues && cues.cues && cues.cues[String(no)]) || [];
  const slides = ((deck.ready && deck.slides) || [])
    .filter((s) => !s.drop && (s.labels || []).length);

  if (!slides.length) {
    page.appendChild(el("div", "empty", "라벨이 있는 장이 없습니다."));
    return;
  }

  /* ★ **음성이 없으면 여기서 멈춘다.** 고르개만 띄워 놓으면 사람이 번호를
       골라 놓고 "왜 초가 안 보이지" 를 묻게 된다. 무엇이 없어서 못 하는지
       이름으로 말해 준다 — 이 레포의 `doctor.py` 와 같은 태도다. */
  const withCues = slides.filter((s) => cueOf(s.no).length);
  if (!withCues.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 음성이 없습니다."));
    box.appendChild(el("p", null,
      "뜨는 시각은 실측 음성 길이에서 나옵니다 — 덱 화면의 «음성/자막 굽기» 를 먼저 돌리세요."));
    page.appendChild(box);
    return;
  }

  // ── 저장 ──────────────────────────────────────────────────────────────
  const pending = {};
  const flush = debounce(async () => {
    const keys = Object.keys(pending);
    if (!keys.length) return;
    const patch = { slides: {} };
    for (const k of keys) { patch.slides[k] = pending[k]; delete pending[k]; }
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
    // 배열 통째로 — 서버 병합이 dict 만 얕게 합치고 배열은 갈아끼운다
    pending[String(s.src_no ?? s.no)] = { labels: s.labels };
    dirty.textContent = "저장 중…";
    dirty.className = "lb-save";
    flush();
  }

  // ── 뼈대 ──────────────────────────────────────────────────────────────
  const tabs = el("div", "lb-tabs");
  const dirty = el("span", "lb-save ok", "저장됨");
  const wrap = el("div", "cu-wrap");
  page.append(tabs, wrap);

  let cur = withCues[0];
  withCues.forEach((s) => {
    const b = el("button", "lb-tab", String(s.no));
    b.title = s.title || "";
    b.onclick = () => { cur = s; draw(); };
    s._tab = b;
    tabs.appendChild(b);
  });
  tabs.appendChild(dirty);

  function draw() {
    withCues.forEach((s) => s._tab.classList.toggle("on", s === cur));
    wrap.replaceChildren();

    const cl = cueOf(cur.no);
    const left = el("div", "cu-left");
    const right = el("div", "cu-right");
    wrap.append(left, right);

    // ── 재생기 ──────────────────────────────────────────────────────────
    const head = el("div", "cu-head");
    head.append(el("strong", null, `${cur.no}. ${cur.title || ""}`),
                el("span", "muted", `라벨 ${cur.labels.length}개 · 문장 ${cl.length}개`));
    left.appendChild(head);

    const aud = el("audio");
    aud.controls = true;
    aud.preload = "none";
    aud.className = "cu-audio";
    const hasAudio = !!(cur.audio && cur.audio.file);
    if (hasAudio) {
      aud.src = `/api/projects/${state.projectId}/audio/${cur.no}`;
      left.appendChild(aud);
    }

    /* 그 지점부터 듣기 — 고른 문장이 진짜 그 말인지 **귀로** 확인하는 길.
       숫자만 보고 맞추면 문장 쪼개기가 한 칸 어긋난 것을 못 잡는다. */
    const playAt = (t) => {
      if (!hasAudio) { toast("이 장은 음성이 없습니다"); return; }
      try { aud.currentTime = Math.max(0, t); aud.play(); } catch (_) {}
    };

    // ── 라벨마다 고르개 ─────────────────────────────────────────────────
    cur.labels.forEach((l, i) => {
      const row = el("div", "cu-row");
      row.appendChild(el("span", "lb-n", String(i + 1)));

      const name = el("div", "cu-name");
      name.append(el("b", null, l.head || ""), el("span", null, l.sub || ""));
      row.appendChild(name);

      const pick = el("select", "cu-pick");
      cl.forEach((c, k) => {
        const o = el("option", null, `문장 ${k + 1} · ${mmss(c[0])}`);
        o.value = String(k + 1);          // 1부터 — say_i 규약
        pick.appendChild(o);
      });
      /* say_i(1부터) → 배열 자리(0부터). 0 은 「못 정함」이라 첫 문장으로 본다.
         범위를 넘으면 마지막에 붙인다 — `stamp_label_times` 와 같은 규칙이다. */
      const idx = () => {
        const i = Math.max(0, Number(l.say_i) || 0);
        return Math.min(i > 0 ? i - 1 : 0, Math.max(0, cl.length - 1));
      };
      pick.value = String(idx() + 1);

      const at = el("span", "cu-at");
      const showAt = () => {
        const c = cl[idx()];
        at.textContent = c ? mmss(c[0]) : "—";
        line.textContent = c ? c[2] : "";
        hi();
      };
      pick.onchange = () => {
        l.say_i = Number(pick.value);
        showAt();
        save(cur);
      };

      const go = el("button", "btn cu-go");
      go.type = "button";
      go.textContent = "여기부터";
      go.onclick = () => { const c = cl[idx()]; if (c) playAt(c[0]); };

      const line = el("div", "cu-line");
      row.append(pick, at, go, line);
      showAt();
      left.appendChild(row);
    });

    // ── 자막 문장 목록 ──────────────────────────────────────────────────
    right.appendChild(el("div", "cu-head", "자막 문장"));
    cl.forEach((c, k) => {
      const r = el("div", "cu-cue");
      r.dataset.k = String(k);
      r.append(el("span", "cu-k", String(k + 1)),
               el("span", "cu-t", mmss(c[0])),
               el("span", "cu-x", c[2]));
      r.title = "누르면 이 지점부터 듣습니다";
      r.onclick = () => playAt(c[0]);
      right.appendChild(r);
    });

    /* 고른 문장에 표시 — 어떤 문장이 **아직 아무 라벨도 안 가리키는지**가
       한눈에 보여야 한다. 그게 비어 있는 구간이 곧 글자 없이 흐르는 구간이다. */
    function hi() {
      const used = new Set(cur.labels.map((l) => {
        const i = Math.max(0, Number(l.say_i) || 0);
        return Math.min(i > 0 ? i - 1 : 0, Math.max(0, cl.length - 1));
      }));
      right.querySelectorAll(".cu-cue").forEach((r) =>
        r.classList.toggle("on", used.has(Number(r.dataset.k))));
    }
    hi();
  }

  draw();
}
