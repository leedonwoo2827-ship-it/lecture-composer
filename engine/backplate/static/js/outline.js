/* 목차 확인 — **비싼 단계로 내려가기 전의 문.**
 *
 * 구조 설계가 짠 목차를 사람이 보고 확정한다. 여기서 고치면 공짜고, 나중에
 * 고치면 판단·문구·대본·음성을 전부 다시 돌려야 한다. 그래서 순서가 이렇다:
 *
 *     설문 → 기획서 → 구조 설계 → **목차 확인(여기)** → 문구·대본·음성
 *
 * 할 수 있는 것 넷:
 *   제목 고치기 · 유형 바꾸기 · 빼기 · **빈 장 끼우기**
 *
 * ★ 한 판에 다 보여야 한다. 14~40줄을 스크롤로 훑으면 "전체가 어떻게 흐르나"
 *   를 못 본다 — 목차를 보는 이유가 그것인데. 그래서 한 줄을 한 행으로 눌러
 *   담고 섹션으로만 끊는다.
 *
 * 여기가 바닥(base)인 이유: 제목 입력칸이 있다. 미저장 텍스트는 패널 금지.
 */
"use strict";

import { el, api, icon, toast } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";

/* ★ `+원고` 가 목록에 **꼭 있어야 한다.** 없으면 이 화면의 <select> 가 그 값을
 *   못 고르고, 목차를 한 번 저장하는 순간 원고 장이 전부 "텍스트" 로 깎여
 *   사라진다(서버도 모르는 값은 text 로 되돌린다). 종류를 늘릴 때 여기를
 *   빠뜨리는 것이 가장 조용한 사고다. */
const MEDIA = [
  ["text", "텍스트"],
  ["html", "+원고"],
  ["text_image", "+이미지"],
  // 표지·마무리처럼 그림 한 장이 화면을 통째로 덮는 장
  ["thumb", "+썸네일"],
  ["video", "+영상"],
  ["code", "코드"],
];

export const meta = {
  title: "목차 확인",
  subtitle: "여기서 고치면 공짜입니다. 확정한 뒤에 문구·대본·음성이 만들어집니다",
};

export async function mount(root) {
  const page = el("div", "page opage");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let d;
  try {
    d = await api(`/api/projects/${state.projectId}/outline`);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }

  if (!d.ready) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 목차가 없습니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "현황판에서 구조 설계 돌리기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  /* 화면이 들고 있는 것 — 저장 전까지는 여기서만 산다 */
  const rows = d.slides.map((s) => ({ ...s }));
  const secTitle = Object.fromEntries(
    (d.sections || []).map((s) => [s.id, s.title]));
  const secIds = (d.sections || []).map((s) => s.id);

  // ── 머리 ──
  const hd = el("div", "ohead");
  const cnt = el("span", "ocount");
  const save = el("button", "btn primary");
  save.type = "button";
  const sl = el("span", null, "이 목차로 확정");
  save.append(icon("check", 14), sl);
  save.onclick = commit;

  /* ★ JSON 으로 나갔다 들어온다.
   *
   * 목차는 이 앱에서 사람이 가장 많이 손대는 물건이다. 화면에서 한 줄씩 고치는
   * 것보다 편집기에서 통째로 다시 쓰는 편이 빠른 경우가 있고, 다른 발표의
   * 목차를 뼈대로 삼고 싶을 때도 있다. 구조 설계를 다시 돌리면 $1 이 들지만
   * 이 길은 공짜다. */
  const out = el("button", "btn");
  out.type = "button";
  out.append(icon("download", 14), el("span", null, "JSON 내보내기"));
  out.title = "지금 화면의 목차를 파일로 — 고쳐서 다시 불러올 수 있습니다";
  out.onclick = exportJson;

  const pick = el("input");
  pick.type = "file";
  pick.accept = "application/json,.json";
  pick.hidden = true;
  pick.onchange = importJson;
  page.appendChild(pick);

  const inp = el("button", "btn");
  inp.type = "button";
  inp.append(icon("upload", 14), el("span", null, "JSON 불러오기"));
  inp.title = "파일의 목차로 갈아 끼웁니다 — 화면에서 보고 확정합니다";
  inp.onclick = () => pick.click();

  const again = el("button", "btn");
  again.type = "button";
  again.append(icon("refresh", 14), el("span", null, "다시 짜기"));
  again.title = "구조 설계를 다시 돌립니다 — 여기서 고친 것은 사라집니다";
  again.onclick = () => navigate("/board");

  hd.append(cnt, out, inp, again, save);
  page.appendChild(hd);

  if (d.confirmed_at) {
    page.appendChild(el("div", "onote",
      `${d.confirmed_at.replace("T", " ")} 에 확정했습니다. 고치면 다시 확정하세요.`));
  }

  const list = el("div", "olist");
  page.appendChild(list);

  /* ★ 예산에 못 담아 버린 것 — 늘릴 때 이것부터 넣는다.
   * 접어 두되 개수는 밖에 보인다. 안 보이면 무엇을 잃었는지 모른다. */
  if ((d.dropped || []).length) {
    const det = el("details", "odrop");
    const sm = el("summary");
    sm.textContent = `예산 ${d.budget}장에 못 담아 버린 것 ${d.dropped.length}건`;
    det.appendChild(sm);
    const ul = el("div", "odrop-list");
    for (const x of d.dropped) ul.appendChild(el("div", "odrop-i", x));
    det.appendChild(ul);
    page.appendChild(det);
  }

  draw();

  function draw() {
    list.textContent = "";
    let lastSec = null;
    let n = 0;

    rows.forEach((s, i) => {
      if (s.section !== lastSec) {
        lastSec = s.section;
        list.appendChild(el("div", "osec",
          secTitle[s.section] || s.section || "섹션 없음"));
      }
      if (!s.drop) n += 1;

      const r = el("div", "orow" + (s.drop ? " out" : "") + (s.no ? "" : " neu"));
      r.appendChild(el("span", "ono", s.drop ? "—" : String(n)));

      const t = el("input", "otitle");
      t.type = "text";
      t.value = s.title || "";
      t.placeholder = s.no ? "제목" : "새 장 — 제목을 쓰세요";
      t.disabled = !!s.drop;
      t.oninput = () => { s.title = t.value; };
      r.appendChild(t);

      const sel = el("select", "okind");
      for (const [v, lb] of MEDIA) {
        const o = el("option", null, lb);
        o.value = v;
        if (v === (s.media_kind || "text")) o.selected = true;
        sel.appendChild(o);
      }
      sel.disabled = !!s.drop;
      sel.onchange = () => { s.media_kind = sel.value; };
      r.appendChild(sel);

      const acts = el("span", "oacts");

      const up = mini("chevronUp", "위로");
      up.disabled = i === 0;
      up.onclick = () => { move(i, -1); };
      const dn = mini("chevronDown", "아래로");
      dn.disabled = i === rows.length - 1;
      dn.onclick = () => { move(i, 1); };

      const add = mini("plus", "이 아래에 빈 장 끼우기");
      add.onclick = () => {
        rows.splice(i + 1, 0, {
          no: 0, section: s.section, kind: "note", title: "",
          note: "", media_kind: "text", video_id: null, evidence_hint: "",
        });
        draw();
      };

      const del = mini(s.drop ? "refresh" : "trash", s.drop ? "되살리기" : "빼기");
      del.onclick = () => {
        if (!s.no && !s.drop) rows.splice(i, 1);   // 새로 끼운 장은 그냥 없앤다
        else s.drop = !s.drop;
        draw();
      };

      acts.append(up, dn, add, del);
      r.appendChild(acts);
      list.appendChild(r);
    });

    const live = rows.filter((x) => !x.drop).length;
    const added = rows.filter((x) => !x.no && !x.drop).length;
    const cut = rows.filter((x) => x.drop).length;
    cnt.textContent = `${live}장`
      + (added ? ` · 끼운 것 ${added}` : "")
      + (cut ? ` · 뺀 것 ${cut}` : "")
      + (d.budget ? ` · 예산 ${d.budget}장` : "");
  }

  function mini(ic, tip) {
    const b = el("button", "omini");
    b.type = "button";
    b.title = tip;
    b.appendChild(icon(ic, 14));
    return b;
  }

  function move(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= rows.length) return;
    [rows[i], rows[j]] = [rows[j], rows[i]];
    // 옮기면 그 자리 섹션을 따라간다 — 안 그러면 섹션 머리가 어긋난다
    rows[j].section = rows[i].section = rows[Math.min(i, j)].section;
    draw();
  }

  /* ★ 파일은 **한 종류다.**
   *
   * 목차에서 뽑든 초안에서 뽑든 같은 모양이 나온다. 칸(body · narration)은
   * 항상 다 있고, 아직 안 만든 것은 빈 문자열이다. 종류가 둘이면 "어느 걸
   * 고쳐야 하나" 를 매번 물어야 하고, 칸이 없으면 밖에서 채워 올 수도 없다.
   *
   * 그래서 여기서도 서버의 전체 내보내기를 그대로 쓴다 — 화면에서 방금 고친
   * 것까지 나가게 하려고, 저장되지 않은 제목·유형만 위에 덮어씌운다.
   */
  async function exportJson() {
    let doc;
    try { doc = await api(`/api/projects/${state.projectId}/draft`); }
    catch (e) { toast("내보내지 못했습니다: " + e.message, "err"); return; }

    const byNo = Object.fromEntries((doc.slides || []).map((s) => [s.no, s]));
    const keep = rows.filter((s) => !s.drop).map((s, i) => {
      const old = s.no ? byNo[s.no] : null;
      return {
        no: i + 1,
        section: s.section, kind: s.kind, title: s.title,
        note: s.note || "", media_kind: s.media_kind || "text",
        video_id: s.video_id || null, evidence_hint: s.evidence_hint || "",
        // 아직 안 만든 것은 **빈 칸으로 나간다** — 밖에서 채워 넣으라고
        body: (old && old.body) || "",
        narration: {srt_text: (old && old.narration.srt_text) || "",
                    text: (old && old.narration.text) || ""},
      };
    });
    const out = {
      // 설명은 서버가 얹어 준 것을 그대로 맨 위에 — 파일은 한 종류다
      _읽는법: doc["_읽는법"],
      deck_title: doc.deck_title || d.deck_title || "",
      deck_subtitle: doc.deck_subtitle || "",
      sections: (d.sections || []).map((x) => ({
        id: x.id, title: x.title, kind: x.kind || "text", summary: x.summary || "",
      })),
      slides: keep, dropped: d.dropped || [], tone: doc.tone || "",
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(out, null, 2)], {type: "application/json"}));
    const a = el("a");
    a.href = url;
    a.download = `${(out.deck_title || "발표").slice(0, 30)}-원고.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    const filled = keep.filter((s) => s.narration.srt_text).length;
    toast(`${keep.length}장을 내보냈습니다 — 대본이 든 장 ${filled}`);
  }

  /** 파일의 목차로 갈아 끼운다. **저장은 안 한다** — 보고 확정하게 둔다. */
  async function importJson(e) {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f) return;
    let j;
    try {
      j = JSON.parse(await f.text());
    } catch (err) {
      toast("JSON 을 읽지 못했습니다: " + err.message, "err");
      return;
    }
    const list = Array.isArray(j) ? j : (j.slides || []);
    if (!list.length) { toast("slides 가 없습니다", "err"); return; }

    /* ★ 파일이 뼈대만인지 살까지 있는지는 **파일이 안다.** 사람에게 "어느
     * 화면에서 넣어야 하냐" 를 묻게 하지 않는다. 문구나 대본이 하나라도 들어
     * 있으면 통째로 넣고, 뼈대뿐이면 화면에 올려 보고 확정하게 둔다. */
    const rich = list.filter((s) => (s.body || "").trim()
                             || ((s.narration || {}).srt_text || "").trim()).length;
    if (rich) {
      const say = [
        `${list.length}장 중 ${rich}장에 문구·대본이 들어 있습니다.`,
        "",
        "통째로 넣습니다 — 지금의 목차·문구·대본과 손편집이 덮어써집니다.",
        "계속할까요?",
      ].join("\n");
      if (!confirm(say)) return;
      try {
        const r = await api(`/api/projects/${state.projectId}/draft/import`,
                            {method: "POST", body: {...j, slides: list}});
        toast(`넣었습니다 — ${r.slides}장 · 문구 ${r.copy} · 대본 ${r.script}`);
        location.reload();
      } catch (err) { toast("넣지 못했습니다: " + err.message, "err"); }
      return;
    }

    // 섹션 이름표를 먼저 갈아 끼워야 머리글이 맞는다
    for (const s of (j.sections || [])) {
      if (s && s.id) secTitle[s.id] = s.title || s.id;
    }
    rows.length = 0;
    for (const s of list) {
      rows.push({
        no: 0,                      // 전부 새 장으로 본다 — 옛 손편집과 안 엮인다
        section: String(s.section || ""),
        kind: String(s.kind || "note"),
        title: String(s.title || ""),
        note: String(s.note || ""),
        media_kind: String(s.media_kind || "text"),
        video_id: s.video_id || null,
        evidence_hint: String(s.evidence_hint || ""),
      });
    }
    d.dropped = j.dropped || [];
    draw();
    toast(`${rows.length}장을 불러왔습니다 — 보고 나서 확정을 누르세요`);
  }

  async function commit() {
    const keep = rows.filter((s) => !s.drop);
    if (!keep.length) { toast("장이 하나도 없습니다", "err"); return; }
    const blank = keep.filter((s) => !(s.title || "").trim());
    if (blank.length) { toast(`제목이 빈 장이 ${blank.length}개 있습니다`, "err"); return; }

    save.disabled = true;
    sl.textContent = "확정하는 중…";
    try {
      const r = await api(`/api/projects/${state.projectId}/outline`,
                          { method: "POST", body: { slides: keep } });
      toast(`목차 확정 — ${r.slides}장 · ${r.sections}섹션`);
      navigate("/board");
    } catch (e) {
      toast("확정하지 못했습니다: " + e.message, "err");
      save.disabled = false;
      sl.textContent = "이 목차로 확정";
    }
  }
}
