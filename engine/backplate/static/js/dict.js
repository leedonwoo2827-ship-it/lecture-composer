/* 발음 사전 — 영문을 한국어 소리로 읽는 표를 **여기서 쌓는다.**
 *
 * 왜 화면이 필요한가. 사전은 파일 하나(`voicewright/config/pronunciation_map.yaml`)
 * 인데, 채울 것이 무엇인지는 **덱을 봐야** 안다. SQL 과목에서 `DECODE` 가
 * 「디이씨오디이」로 나온 것이 그 예다 — 사전에 없으니 글자 이름으로 읽은 것이고,
 * 파일만 열어 놓고는 무엇이 빠졌는지 알 길이 없다.
 *
 * 그래서 이 화면은 두 칸이다.
 *
 *   왼쪽  아직 없는 말   이 덱에 나오는데 사전에 없는 영문. 많이 나온 순.
 *   오른쪽 사전          이미 들어 있는 것. 고치고 지운다.
 *
 * ★ **바닥 화면이다**(패널이 아니다). 입력칸이 있는 화면은 Esc·스크림으로 닫히면
 *   안 된다 — 타이핑하던 것이 날아간다(`shell.js` 의 두 층 법칙).
 *
 * ★ 저장은 **한 번에.** 칸마다 저장하면 파일을 수십 번 다시 쓰고, 중간에 창을
 *   닫으면 반만 들어간 사전이 남는다. 서버가 저장 직전에 `.yaml.bak` 을 남긴다.
 */
"use strict";

import { el, api, icon, toast } from "./util.js";
import { state } from "./store.js";

export const meta = {
  title: "발음 사전",
  subtitle: "영문을 한국어 소리로 — 여기 넣으면 발음 대본에 그대로 반영됩니다",
  actions: () => {
    const save = el("button", "btn primary");
    save.type = "button";
    save.append(icon("check", 14), el("span", null, "사전 저장"));
    save.onclick = () => saveAll(save);

    const info = el("span", "dict-path");
    info.id = "dictPath";
    return [info, save];
  },
};

/* 화면이 들고 있는 표. 저장할 때 통째로 넘긴다. */
let RULES = {};
let MISSING = [];

export async function mount(root) {
  root.innerHTML = "";
  const wrap = el("div", "dictwrap");
  root.appendChild(wrap);
  await fill(wrap, state.projectId, true);
}

/* 사전 편집 한 덩어리 — **덱 화면 안에도 그대로 넣는다.**

   ★ 왜 인라인인가. 사전을 채우려면 바로 위 자막·발음 칸에서 낱말을 복사해야
     한다. 새 창으로 띄웠더니 창을 오가야 했고(2026-08-23), 같은 창에서
     넘어가면 보던 장을 놓친다. 붙여 넣을 자리가 **복사할 자리 바로 아래**에
     있는 것이 답이다.
   ★ 접어 둔다. 제목·본문처럼 늘 쓰는 칸이 아니고, 펴 두면 장을 넘길 때마다
     화면이 길어진다. */
export function panel(pid) {
  const box = el("details", "dictpanel");
  const sum = el("summary");
  /* ★ 화살표를 단다. 줄 전체가 누르는 자리인데 그렇게 안 보여서 "버튼이 어디
     있냐" 가 나왔다(2026-08-23). 펴지면 화살표가 아래를 본다. */
  const car = icon("chevronRight", 13);
  car.classList.add("dp-car");
  sum.append(car, icon("book", 13), el("span", null, "발음 사전"),
             el("span", "dp-hint", "눌러서 펼칩니다 — 영문이 이상하게 읽히면 여기에 넣습니다"));
  box.appendChild(sum);

  const body = el("div", "dictwrap");
  box.appendChild(body);

  let loaded = false;
  box.addEventListener("toggle", async () => {
    if (!box.open || loaded) return;
    loaded = true;                       // 펼 때 한 번만 읽는다
    body.appendChild(el("p", "muted", "불러오는 중…"));
    await fill(body, pid, false);
  });
  return box;
}

/* 표를 읽어 화면을 채운다. `withHeaderPath` 는 전용 화면일 때만. */
async function fill(host, pid, withHeaderPath) {
  host.innerHTML = "";
  let data;
  try {
    data = await api(`/api/pron-dict${pid ? `?pid=${pid}` : ""}`);
  } catch (e) {
    host.appendChild(el("p", "muted", "사전을 불러오지 못했습니다: " + e.message));
    return;
  }
  RULES = data.rules || {};
  MISSING = data.missing || [];

  if (withHeaderPath) {
    const p = document.getElementById("dictPath");
    if (p) p.textContent = `${data.count}개 · ${data.path}`;
  }

  const cols = el("div", "dictcols");
  cols.appendChild(missingCol());
  cols.appendChild(rulesCol());
  host.appendChild(cols);

  if (!withHeaderPath) {
    /* 인라인에는 저장 버튼이 안 딸려 온다(전용 화면은 제목 줄에 있다) */
    const foot = el("div", "dictfoot");
    const save = el("button", "btn sm primary");
    save.type = "button";
    save.append(icon("check", 12), el("span", null, "사전 저장"));
    save.onclick = () => saveAll(save);
    foot.append(el("span", "muted", `${data.count}개 · 저장하면 바로 반영됩니다`), save);
    host.appendChild(foot);
  }
}

/* ── 왼쪽: 아직 사전에 없는 말 ──────────────────────────────────────────── */
function missingCol() {
  const box = el("section", "dictcol");
  box.appendChild(el("h3", null, "아직 없는 말"));
  box.appendChild(el("p", "muted",
    MISSING.length
      ? "이 덱에 나오는데 사전에 없는 영문입니다. 많이 나온 순서입니다."
      : "이 덱에서 빠진 영문이 없습니다."));

  if (!MISSING.length) return box;

  /* ★ 제안값을 미리 채워 둔다 — 지금 그렇게 읽히고 있는 소리다. 맞으면 그대로
     두고 아니면 고친다. 빈칸을 주면 매번 처음부터 타이핑해야 한다. */
  const list = el("div", "dictlist");
  for (const m of MISSING) {
    const row = el("div", "dictrow");
    const k = el("span", "dk");
    k.textContent = m.word;
    const n = el("span", "dn");
    n.textContent = m.n + "회";
    const v = el("input", "di");
    v.type = "text";
    v.value = m.guess || "";
    v.placeholder = "읽는 소리";
    v.spellcheck = false;
    v.oninput = () => { RULES[m.word] = v.value.trim(); };
    RULES[m.word] = v.value.trim();          // 제안값도 저장 대상이다
    const rm = el("button", "dx");
    rm.type = "button";
    rm.textContent = "×";
    rm.title = "이 말은 사전에 넣지 않습니다";
    rm.onclick = () => { delete RULES[m.word]; row.remove(); };
    row.append(k, n, v, rm);
    list.appendChild(row);
  }
  box.appendChild(list);
  return box;
}

/* ── 오른쪽: 이미 들어 있는 사전 ────────────────────────────────────────── */
function rulesCol() {
  const box = el("section", "dictcol");
  box.appendChild(el("h3", null, "사전"));

  const find = el("input", "dictfind");
  find.type = "search";
  find.placeholder = "찾기 — 영문이나 한글로";
  find.spellcheck = false;
  box.appendChild(find);

  const list = el("div", "dictlist");
  box.appendChild(list);

  const draw = (q) => {
    list.innerHTML = "";
    const keys = Object.keys(RULES)
      .filter((k) => !MISSING.some((m) => m.word === k))
      .filter((k) => !q || k.toLowerCase().includes(q) || (RULES[k] || "").includes(q))
      .sort();
    for (const k of keys) list.appendChild(ruleRow(k, list));
    if (!keys.length) list.appendChild(el("p", "muted", "없습니다"));
  };
  find.oninput = () => draw(find.value.trim().toLowerCase());
  draw("");

  /* 새 줄 — 덱에 없는 말도 미리 넣어 둘 수 있어야 한다.
     ★ **목록 위에 둔다**(2026-09-06). 사전이 길어질수록 아래에
       두면 넣을 때마다 끝까지 내려야 한다 — 넣는 일은 목록을 다 본 뒤에 하는
       일이 아니라 아무 때나 하는 일이다. */
  const add = el("div", "dictadd");
  const nk = el("input", "di");
  nk.type = "text";
  nk.placeholder = "영문 (예: DECODE)";
  nk.spellcheck = false;
  const nv = el("input", "di");
  nv.type = "text";
  nv.placeholder = "읽는 소리 (예: 디코드)";
  nv.spellcheck = false;
  const ab = el("button", "btn sm");
  ab.type = "button";
  ab.append(icon("plus", 12), el("span", null, "넣기"));
  ab.onclick = () => {
    const k = nk.value.trim(), v = nv.value.trim();
    if (!k || !v) { toast("영문과 소리를 둘 다 적어 주세요"); return; }
    RULES[k] = v;
    nk.value = nv.value = "";
    draw(find.value.trim().toLowerCase());
    toast(`${k} → ${v} — «사전 저장» 을 눌러야 파일에 들어갑니다`);
  };
  add.append(nk, nv, ab);
  box.insertBefore(add, find);      // 제목 바로 아래 — 찾기·목록보다 먼저
  return box;
}

function ruleRow(k, list) {
  const row = el("div", "dictrow");
  const key = el("span", "dk");
  key.textContent = k;
  const v = el("input", "di");
  v.type = "text";
  v.value = RULES[k] || "";
  v.spellcheck = false;
  v.oninput = () => { RULES[k] = v.value.trim(); };
  const rm = el("button", "dx");
  rm.type = "button";
  rm.textContent = "×";
  rm.title = "사전에서 지웁니다";
  rm.onclick = () => {
    if (!confirm(`「${k}」 를 사전에서 지울까요?`)) return;
    delete RULES[k];
    row.remove();
  };
  row.append(key, v, rm);
  return row;
}

/* ── 저장 ──────────────────────────────────────────────────────────────── */
async function saveAll(btn) {
  const rules = {};
  for (const [k, v] of Object.entries(RULES)) {
    if (k && v && String(v).trim()) rules[k] = String(v).trim();
  }
  if (!Object.keys(rules).length) { toast("사전이 비어 있습니다", "err"); return; }
  btn.disabled = true;
  try {
    const r = await api("/api/pron-dict", {method: "POST", body: {rules}});
    toast(`사전 ${r.count}개를 저장했습니다 — 이제 «영문을 소리대로»`);
    const p = document.getElementById("dictPath");
    if (p) p.textContent = `${r.count}개 · ${r.file}`;
  } catch (e) {
    toast("저장하지 못했습니다: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}
