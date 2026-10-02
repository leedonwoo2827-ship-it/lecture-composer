// ★ 이 앱은 쇼케이스 서버의 /imgstudio 아래에 얹혀 있다.
//   index.html 이 페이지 위치에서 뽑아 둔 기준점을 쓴다. 이걸 안 붙이면
//   "/api/..." 가 호스트(쇼케이스)의 API 를 때린다.
const B = (window.__IS_BASE__ || "");
"use strict";
// builder.js — 프롬프트 빌더 워크스페이스 (자유 빌더 채팅 / 프롬프트 생성기 / 보관함)
// 텍스트·비전은 모두 /api/builder/* (Codex 백엔드 공용). 별도 설정/API 키 없음.

const $b = (id) => document.getElementById(id);

// ── 공통 유틸 ──────────────────────────────────────────
function escapeHtmlB(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function fileToDataURL(file) {
  return new Promise((res) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.readAsDataURL(file);
  });
}
function downloadMd(text, base) {
  let name = (base || "프롬프트").trim().replace(/[\\/:*?"<>|]+/g, "_").slice(0, 60) || "프롬프트";
  if (!name.endsWith(".md")) name += ".md";
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
// 텍스트를 일반/코드펜스로 나눠 렌더. 코드블록엔 복사·다운로드 버튼.
function renderContent(container, text) {
  text.split(/```/).forEach((part, i) => {
    if (i % 2 === 1) {
      const body = (/^\w+\n/.test(part) ? part.replace(/^\w+\n/, "") : part).trim();
      const actions = document.createElement("div");
      actions.className = "block-actions";
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn"; copyBtn.textContent = "복사";
      copyBtn.onclick = () => navigator.clipboard.writeText(body).then(() => {
        copyBtn.textContent = "복사됨!"; setTimeout(() => (copyBtn.textContent = "복사"), 1200);
      });
      const dlBtn = document.createElement("button");
      dlBtn.className = "btn"; dlBtn.textContent = ".md 다운로드";
      dlBtn.onclick = () => downloadMd(body);
      actions.append(copyBtn, dlBtn);
      const pre = document.createElement("pre");
      pre.textContent = body;
      container.append(actions, pre);
    } else if (part.trim()) {
      const div = document.createElement("div");
      div.innerHTML = escapeHtmlB(part).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
      container.append(div);
    }
  });
}

// ── 빌더 내부 탭 전환 ───────────────────────────────────
function showPanel(name) {
  document.querySelectorAll("#ws-builder .panel[data-panel]").forEach((p) =>
    p.classList.toggle("hidden", p.dataset.panel !== name));
  document.querySelectorAll("#ws-builder .tab[data-tab]").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name));
  if (name === "archive") loadArchives();
}
document.querySelectorAll("#ws-builder .tab[data-tab]").forEach((tab) =>
  tab.addEventListener("click", () => showPanel(tab.dataset.tab)));

// ════════════════════════════════════════════════════════
// 탭 1: 자유 빌더(채팅)
// ════════════════════════════════════════════════════════
const messages = [];
let pendingImages = [];

const chatEl = $b("chat"), inputEl = $b("input"), composerEl = $b("bldComposer");
const fileInput = $b("fileInput"), attachPreview = $b("attachPreview"), sendBtn = $b("bldSendBtn");

function addMessage(role, content, images = []) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role === "user" ? "user" : "bot"}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  renderContent(bubble, content);
  images.forEach((src) => {
    const img = document.createElement("img");
    img.className = "thumb"; img.src = src; bubble.append(img);
  });
  wrap.append(bubble);
  chatEl.append(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
  return bubble;
}

$b("attachBtn").onclick = () => fileInput.click();
fileInput.onchange = async () => {
  for (const f of fileInput.files) pendingImages.push(await fileToDataURL(f));
  fileInput.value = ""; renderAttachPreview();
};
function renderAttachPreview() {
  attachPreview.innerHTML = "";
  pendingImages.forEach((src, idx) => {
    const chip = document.createElement("div"); chip.className = "chip";
    const img = document.createElement("img"); img.src = src;
    const x = document.createElement("button");
    x.className = "x"; x.textContent = "×";
    x.onclick = () => { pendingImages.splice(idx, 1); renderAttachPreview(); };
    chip.append(img, x); attachPreview.append(chip);
  });
}

async function callChat(extra = {}) {
  const res = await fetch(B + "/api/builder/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, ...extra }),
  });
  return res.json();
}

async function send(text, images) {
  messages.push({ role: "user", content: text, images });
  addMessage("user", text || "(레퍼런스 이미지 첨부)", images);
  const typing = addMessage("bot", "");
  typing.innerHTML = '<span class="typing">생각 중…</span>';
  sendBtn.disabled = true;
  try {
    const data = await callChat();
    typing.innerHTML = "";
    if (data.ok) {
      renderContent(typing, data.reply);
      messages.push({ role: "assistant", content: data.reply, images: [] });
    } else {
      typing.innerHTML = `<span class="typing">⚠ ${escapeHtmlB(data.error || "오류")}</span>`;
    }
  } catch (err) {
    typing.innerHTML = `<span class="typing">⚠ 서버 연결 실패: ${escapeHtmlB(String(err))}</span>`;
  } finally {
    sendBtn.disabled = false; chatEl.scrollTop = chatEl.scrollHeight;
  }
}

composerEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text && pendingImages.length === 0) return;
  const images = pendingImages.slice();
  inputEl.value = ""; inputEl.style.height = "auto";
  pendingImages = []; renderAttachPreview();
  send(text, images);
});

$b("finalizeBtn").onclick = async () => {
  if (messages.length === 0) { alert("먼저 대화로 원하는 내용을 알려주세요."); return; }
  const typing = addMessage("bot", "");
  typing.innerHTML = '<span class="typing">최종 프롬프트 확정 중…</span>';
  try {
    const data = await callChat({ finalize: true });
    typing.innerHTML = "";
    if (data.ok) {
      renderContent(typing, data.reply);
      messages.push({ role: "assistant", content: data.reply, images: [] });
    } else {
      typing.innerHTML = `<span class="typing">⚠ ${escapeHtmlB(data.error || "오류")}</span>`;
    }
  } catch (err) {
    typing.innerHTML = `<span class="typing">⚠ ${escapeHtmlB(String(err))}</span>`;
  }
};

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); composerEl.requestSubmit(); }
});
$b("newChatBtn").onclick = () => {
  if (!confirm("현재 작업(대화 · 생성기 선택값 · 첨부)을 모두 비우고 새로 시작할까요?")) return;
  // 1) 자유 빌더(채팅) 초기화
  messages.length = 0;
  chatEl.querySelectorAll(".msg:not(:first-child)").forEach((n) => n.remove());
  pendingImages = []; renderAttachPreview();
  // 2) 프리셋 선택 해제
  document.querySelectorAll(".preset-side-item.selected").forEach((n) => n.classList.remove("selected"));
  // 3) 프롬프트 생성기 초기화
  resetGenerator();
};

// 프롬프트 생성기 탭의 모든 선택값/원고/결과를 비운다.
function resetGenerator() {
  gen.purpose = null; gen.tone = null; gen.color = null; gen.style = null;
  gen.cuts = null; gen.manuscripts = [];
  ["grpPurpose", "grpTone", "grpColor", "grpPreset", "grpCuts"].forEach((id) => {
    const el = $b(id);
    if (el) [...el.children].forEach((c) => c.classList.remove("selected"));
  });
  // 스타일 옵션은 첫 항목 "(없음)" 을 기본 선택 상태로
  const styleFirst = $b("grpPreset") && $b("grpPreset").firstElementChild;
  if (styleFirst) styleFirst.classList.add("selected");
  $b("genColorCustom").value = "";
  $b("genNote").value = "";
  $b("cutRecommend").textContent = "";
  $b("cutMsg").textContent = ""; $b("cutMsg").className = "cut-msg";
  $b("genFile").value = "";
  renderGenFiles();
  $b("genResult").innerHTML = '<p class="muted">옵션을 고르고 「확정」을 누르면 여기에 최종 프롬프트가 나옵니다.</p>';
}

// ── 프리셋(1번 탭 사이드) / 스타일(2번 탭 옵션) ─────────
let bundlePresets = [];
let stylePresets = [];

function switchTab(name) { showPanel(name); }
function styleShort(name) {
  if (!name) return "";
  return name.length > 4 ? name.slice(0, 4) + "…" : name;
}

async function loadPresets() {
  let all = [];
  try { all = (await (await fetch(B + "/api/builder/presets")).json()).presets || []; } catch { all = []; }
  bundlePresets = all.filter((p) => p.kind !== "style");
  stylePresets = all.filter((p) => p.kind === "style");
  renderPresetSidebar();
  renderStyleOptions();
}

function renderPresetSidebar() {
  document.querySelectorAll("#ws-builder .preset-side-list").forEach((list) => {
    list.innerHTML = "";
    if (bundlePresets.length === 0) {
      list.innerHTML = '<div class="hint">presets/ 폴더 또는 「프롬프트 생성기」에서 프리셋을 추가하세요.</div>';
      return;
    }
    bundlePresets.forEach((p) => {
      const label = p.style ? `${p.name}(${styleShort(p.style)})` : p.name;
      const item = document.createElement("div");
      item.className = "preset-side-item";
      item.innerHTML = `<div class="pname">${escapeHtmlB(label)}${p.builtin ? "" : " ✎"}</div>` +
        (p.description ? `<div class="pdesc">${escapeHtmlB(p.description)}</div>` : "");
      item.onclick = () => applyBundle(p, item);
      list.append(item);
    });
  });
}

function applyBundle(p, itemEl) {
  document.querySelectorAll(".preset-side-item.selected").forEach((n) => n.classList.remove("selected"));
  if (itemEl) itemEl.classList.add("selected");
  switchTab("generator");
  if (p.purpose) {
    const pu = PURPOSES.find((x) => x.key === p.purpose || x.label === p.purpose);
    if (pu) clickInGroup("grpPurpose", (b) => b.textContent === pu.label);
  }
  if (p.tone) clickInGroup("grpTone", (b) => b.textContent === p.tone);
  if (p.color) {
    if (COLORS.includes(p.color)) clickInGroup("grpColor", (b) => b.textContent === p.color);
    else $b("genColorCustom").value = p.color;
  }
  if (p.style) clickInGroup("grpPreset", (b) => b.textContent === p.style);
  if (p.cuts) clickInGroup("grpCuts", (b) => Number(b.dataset.cut) === Number(p.cuts));
}

function clickInGroup(groupId, predicate) {
  const btn = [...$b(groupId).children].find(predicate);
  if (btn) btn.click();
}

// 현재 생성기 옵션을 프리셋으로 저장
$b("presetForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $b("pName").value.trim();
  if (!name) { $b("presetFormMsg").textContent = "이름을 입력하세요."; return; }
  const fd = new FormData();
  fd.append("name", name);
  fd.append("description", $b("pDesc").value.trim());
  if (gen.purpose) fd.append("purpose", gen.purpose.key);
  if (gen.tone) fd.append("tone", gen.tone);
  fd.append("color", [gen.color, $b("genColorCustom").value.trim()].filter(Boolean).join(" / "));
  if (gen.style) { fd.append("style", gen.style.name); fd.append("keywords", (gen.style.keywords || []).join(", ")); }
  if (gen.cuts != null) fd.append("cuts", String(gen.cuts));
  if ($b("pCover").files[0]) fd.append("cover", $b("pCover").files[0]);
  $b("presetFormMsg").textContent = "저장 중…";
  try {
    const data = await (await fetch(B + "/api/builder/presets", { method: "POST", body: fd })).json();
    if (data.ok) { $b("presetFormMsg").textContent = "✔ 저장됨"; $b("presetForm").reset(); loadPresets(); }
    else $b("presetFormMsg").textContent = "⚠ " + (data.error || "실패");
  } catch (err) { $b("presetFormMsg").textContent = "⚠ " + String(err); }
});
document.querySelectorAll("#reloadPresets, .reloadPresets").forEach((b) => (b.onclick = loadPresets));

// ════════════════════════════════════════════════════════
// 탭 2: 프롬프트 생성기 (구조화)
// ════════════════════════════════════════════════════════
const PURPOSES = [
  { key: "sns", label: "SNS 카드뉴스", rec: 8, allow: [4, 6, 8, 10] },
  { key: "print", label: "인쇄 포스터", rec: 1, allow: [1, 2] },
  { key: "ppt", label: "PPT", rec: 4, allow: [1, 2, 4, 6, 8] },
  { key: "banner", label: "배너·썸네일", rec: 1, allow: [1, 2, 3] },
  { key: "cover", label: "책표지", rec: 1, allow: [1, 2] },
];
const TONES = ["후킹형", "정보형", "감성형", "신뢰·전문형"];
const COLORS = ["브랜드 색 사용", "밝고 따뜻하게", "차분·뉴트럴", "고대비·강렬"];
const CUTS = [1, 2, 3, 4, 6, 8, 10, 12];

const gen = { purpose: null, tone: null, color: null, style: null, cuts: null, manuscripts: [] };

function makeOptButtons(container, items, getLabel, onPick) {
  container.innerHTML = "";
  items.forEach((it) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "opt"; b.textContent = getLabel(it);
    b.onclick = () => {
      [...container.children].forEach((c) => c.classList.remove("selected"));
      b.classList.add("selected");
      onPick(it, b);
    };
    container.append(b);
  });
}

function initGenerator() {
  makeOptButtons($b("grpPurpose"), PURPOSES, (p) => p.label, (p) => {
    gen.purpose = p;
    $b("cutRecommend").textContent = `(추천: ${p.rec}컷)`;
    const recBtn = [...$b("grpCuts").children].find((c) => Number(c.dataset.cut) === p.rec);
    if (recBtn) recBtn.click();
    else validateCuts();
  });
  makeOptButtons($b("grpTone"), TONES, (t) => t, (t) => (gen.tone = t));
  makeOptButtons($b("grpColor"), COLORS, (c) => c, (c) => (gen.color = c));
  renderCutButtons();
}

function renderCutButtons() {
  const c = $b("grpCuts");
  c.innerHTML = "";
  CUTS.forEach((n) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "opt"; b.dataset.cut = n; b.textContent = `${n}컷`;
    b.onclick = () => {
      [...c.children].forEach((x) => x.classList.remove("selected"));
      b.classList.add("selected");
      gen.cuts = n; validateCuts();
    };
    c.append(b);
  });
}

function validateCuts() {
  const msg = $b("cutMsg");
  if (!gen.purpose || gen.cuts == null) { msg.textContent = ""; msg.className = "cut-msg"; return; }
  if (gen.purpose.allow.includes(gen.cuts)) {
    msg.textContent = "✔ 권장 범위입니다.";
    msg.className = "cut-msg ok";
  } else {
    msg.textContent = `⚠ '${gen.purpose.label}'에는 ${gen.cuts}컷이 권장되지 않습니다. 권장: ${gen.purpose.allow.join(", ")}컷 (추천 ${gen.purpose.rec}컷)`;
    msg.className = "cut-msg warn";
  }
}

function renderStyleOptions() {
  const grp = $b("grpPreset");
  const items = [{ name: "(없음)", _none: true }, ...stylePresets];
  makeOptButtons(grp, items, (p) => p.name, (p) => (gen.style = p._none ? null : p));
}

// 생성기 원고 파일 첨부 (드롭존) → 서버에서 텍스트 추출
const genDrop = $b("genDrop"), genFileEl = $b("genFile");
$b("genPick").onclick = () => genFileEl.click();
genFileEl.onchange = () => handleManuscripts(genFileEl.files);
genDrop.addEventListener("dragover", (e) => { e.preventDefault(); genDrop.classList.add("drag"); });
genDrop.addEventListener("dragleave", () => genDrop.classList.remove("drag"));
genDrop.addEventListener("drop", (e) => {
  e.preventDefault(); genDrop.classList.remove("drag");
  if (e.dataTransfer.files.length) handleManuscripts(e.dataTransfer.files);
});

async function handleManuscripts(fileList) {
  for (const f of fileList) {
    const entry = { name: f.name, text: "", chars: 0, status: "추출 중…", error: "" };
    gen.manuscripts.push(entry); renderGenFiles();
    try {
      const fd = new FormData(); fd.append("file", f);
      const r = await (await fetch(B + "/api/builder/extract-text", { method: "POST", body: fd })).json();
      if (r.ok) {
        entry.text = r.text; entry.chars = r.chars;
        entry.status = `${r.chars.toLocaleString()}자 추출${r.truncated ? " (앞 2만자만 사용)" : ""}`;
      } else {
        entry.error = r.note || "추출 실패"; entry.status = "";
      }
    } catch (err) {
      entry.error = String(err); entry.status = "";
    }
    renderGenFiles();
  }
  genFileEl.value = "";
}

function renderGenFiles() {
  const wrap = $b("genFileList"); wrap.innerHTML = "";
  gen.manuscripts.forEach((m, idx) => {
    const row = document.createElement("div");
    row.className = "file-item" + (m.error ? " err" : "");
    row.innerHTML = `<span>📄 ${escapeHtmlB(m.name)}</span>` +
      `<span class="fmeta">${escapeHtmlB(m.error || m.status)}</span>`;
    const x = document.createElement("button");
    x.className = "x"; x.textContent = "×";
    x.onclick = () => { gen.manuscripts.splice(idx, 1); renderGenFiles(); };
    row.append(x); wrap.append(row);
  });
}

$b("genConfirm").onclick = async () => {
  const result = $b("genResult");
  const fail = (m) => (result.innerHTML = `<p class="cut-msg warn">⚠ ${escapeHtmlB(m)}</p>`);

  const colorCustom = $b("genColorCustom").value.trim();
  const lines = ["[프롬프트 생성 요청]"];
  if (gen.purpose) lines.push(`용도: ${gen.purpose.label}`);
  if (gen.tone) lines.push(`톤: ${gen.tone}`);
  if (gen.color || colorCustom) lines.push(`색/톤앤매너: ${[gen.color, colorCustom].filter(Boolean).join(" / ")}`);
  if (gen.style) lines.push(`스타일: ${gen.style.name}${(gen.style.keywords || []).length ? ` (키워드: ${gen.style.keywords.join(", ")})` : ""}`);
  lines.push(`컷 수: ${gen.cuts ?? (gen.purpose ? gen.purpose.rec : 1)}`);
  const note = $b("genNote").value.trim();
  if (note) lines.push(`추가 메모: ${note}`);

  const manuscript = gen.manuscripts.filter((m) => m.text).map((m) => `# ${m.name}\n${m.text}`).join("\n\n");
  if (manuscript) lines.push("\n[원고 — 이 내용을 컷별로 배분]\n" + manuscript);
  lines.push("\n위 조건과 원고로 이미지 스튜디오에 바로 붙일 최종 프롬프트를 만들어줘.");

  result.innerHTML = '<p class="muted">생성 중… (모델 응답을 기다리는 중)</p>';
  try {
    const res = await fetch(B + "/api/builder/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: lines.join("\n"), images: [] }], finalize: true }),
    });
    if (!res.ok) return fail(`서버 오류 (HTTP ${res.status})`);
    const data = await res.json();
    if (!data.ok) return fail(data.error || "알 수 없는 오류");
    if (!data.reply || !data.reply.trim()) return fail("모델이 빈 응답을 반환했습니다. 다시 시도해 주세요.");
    renderGenResult(data.reply);
  } catch (err) {
    fail("서버 연결 실패: " + String(err));
  }
};

function genBaseName() {
  const m = gen.manuscripts.find((x) => x.text);
  if (m) return m.name.replace(/\.[^.]+$/, "");
  if (gen.style) return gen.style.name;
  return "프롬프트";
}
function toolbarBtn(label, fn) {
  const b = document.createElement("button");
  b.className = "btn"; b.textContent = label; b.onclick = fn; return b;
}
function renderGenResult(reply) {
  const result = $b("genResult"); result.innerHTML = "";
  const base = genBaseName();
  const bar = document.createElement("div");
  bar.className = "block-actions result-toolbar";
  bar.append(
    toolbarBtn("전체 복사", (e) => { navigator.clipboard.writeText(reply); flash(e.target, "복사됨!"); }),
    toolbarBtn("전체 .md 다운로드", () => downloadMd(reply, base)),
    toolbarBtn("📌 보관", async (e) => {
      e.target.disabled = true;
      const r = await saveArchive(base, reply);
      flash(e.target, r ? "보관됨 ✓" : "실패");
      e.target.disabled = false;
    }),
  );
  result.append(bar);
  renderContent(result, reply);
}
function flash(btn, text) {
  const old = btn.textContent; btn.textContent = text;
  setTimeout(() => (btn.textContent = old), 1200);
}

// ── 보관함(게시판) ─────────────────────────────────────
async function saveArchive(title, content) {
  try {
    const r = await (await fetch(B + "/api/builder/archives", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content }),
    })).json();
    return r.ok;
  } catch { return false; }
}

async function loadArchives() {
  const list = $b("archiveList");
  list.innerHTML = '<p class="archive-empty">불러오는 중…</p>';
  let items = [];
  try { items = (await (await fetch(B + "/api/builder/archives")).json()).archives || []; } catch {}
  if (items.length === 0) {
    list.innerHTML = '<p class="archive-empty">아직 보관된 프롬프트가 없습니다. 생성기에서 「📌 보관」을 눌러 추가하세요.</p>';
    return;
  }
  list.innerHTML = "";
  items.forEach((it) => list.append(renderArchiveItem(it)));
}

function renderArchiveItem(it) {
  const item = document.createElement("div");
  item.className = "archive-item";
  const row = document.createElement("div");
  row.className = "archive-row";
  row.innerHTML =
    `<span class="a-title">${escapeHtmlB(it.title)}</span>` +
    `<span class="a-meta">${escapeHtmlB(it.created)} · ${it.chars.toLocaleString()}자</span>` +
    `<span class="a-preview">${escapeHtmlB(it.preview)}</span>`;
  const actions = document.createElement("div");
  actions.className = "a-actions";
  const openBtn = toolbarBtn("열기", () => toggleArchive(item, it.id));
  const delBtn = toolbarBtn("삭제", async () => {
    if (!confirm(`'${it.title}' 을(를) 삭제할까요?`)) return;
    await fetch(B + `/api/builder/archives/${it.id}`, { method: "DELETE" });
    loadArchives();
  });
  actions.append(openBtn, delBtn);
  row.append(actions);
  row.onclick = (e) => { if (!e.target.closest(".a-actions")) toggleArchive(item, it.id); };
  const body = document.createElement("div");
  body.className = "archive-body";
  item.append(row, body);
  return item;
}

async function toggleArchive(item, id) {
  const body = item.querySelector(".archive-body");
  if (item.classList.contains("open")) { item.classList.remove("open"); return; }
  if (!body.dataset.loaded) {
    body.innerHTML = '<p class="muted">불러오는 중…</p>';
    const r = await (await fetch(B + `/api/builder/archives/${id}`)).json();
    const content = r.ok ? r.archive.content : "(불러오지 못함)";
    body.innerHTML = "";
    const bar = document.createElement("div");
    bar.className = "block-actions";
    bar.append(
      toolbarBtn("복사", (e) => { navigator.clipboard.writeText(content); flash(e.target, "복사됨!"); }),
      toolbarBtn(".md 다운로드", () => downloadMd(content, r.ok ? r.archive.title : "프롬프트")),
    );
    const pre = document.createElement("pre");
    pre.textContent = content.replace(/```[a-zA-Z]*\n?/g, "");
    body.append(bar, pre);
    body.dataset.loaded = "1";
  }
  item.classList.add("open");
}
$b("reloadArchives").onclick = loadArchives;

// ── 초기화 ─────────────────────────────────────────────
initGenerator();
loadPresets();
showPanel("builder");
