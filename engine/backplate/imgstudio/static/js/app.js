// app.js — 메인 컨트롤러 (사이드바 / 스튜디오 / 에디터 / 병합 / 설정)
import { api } from "/js/api.js";

const $ = (id) => document.getElementById(id);
const state = {
  view: "all",        // "all" | "fav" | <projectId>
  projects: [],
  images: [],
  current: null,      // 선택된 이미지 상세
  settings: {},
  queue: [],          // 보관함에서 가져온 프롬프트 대기열
  qi: 0,              // 현재 큐 위치
};

// ── 공통 UI ────────────────────────────────────────────────
let toastTimer;
function toast(msg, bad = false) {
  const t = $("toast");
  t.innerHTML = msg;
  t.className = "toast" + (bad ? " bad" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), bad ? 6000 : 2600);
}
function busy(btn, on, label) {
  if (on) { btn.dataset.label = btn.textContent; btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> ${label || "생성 중…"}`; }
  else { btn.disabled = false; btn.textContent = btn.dataset.label || btn.textContent; }
}

// ── 설정 / 크기 선택 ───────────────────────────────────────
const SIZE_LABELS = {
  "auto": "자동",
  "1024x1024": "1024×1024 (1:1 정사각)",
  "1536x1024": "1536×1024 (3:2 가로)",
  "1024x1536": "1024×1536 (2:3 세로)",
  "1536x864": "1536×864 (16:9 가로)",
  "864x1536": "864×1536 (9:16 세로)",
  "1408x1056": "1408×1056 (4:3 가로)",
  "1056x1408": "1056×1408 (3:4 세로)",
  "1344x576": "1344×576 (21:9 초광각)",
};
function fillSizeSelect(sel, sizes, val) {
  sel.innerHTML = "";
  sizes.forEach((s) => {
    const o = document.createElement("option");
    o.value = s; o.textContent = SIZE_LABELS[s] || s;
    if (s === val) o.selected = true;
    sel.appendChild(o);
  });
}
async function loadSettings() {
  state.settings = await api.getSettings();
  const sizes = state.settings.size_choices || ["auto"];
  fillSizeSelect($("sizeSelect"), sizes, state.settings.default_size);
  fillSizeSelect($("defSizeSelect"), sizes, state.settings.default_size);
}

async function refreshAuthChip() {
  try {
    const s = await api.authStatus();
    const chip = $("authChip");
    if (!s.installed) {
      chip.textContent = "codex 미설치"; chip.className = "auth-chip bad";
    } else if (!s.authenticated) {
      chip.textContent = "ChatGPT 로그인 필요"; chip.className = "auth-chip bad";
    } else {
      chip.textContent = (s.email || "ChatGPT") + " ✓"; chip.className = "auth-chip ok";
    }
    return s;
  } catch { return null; }
}

// ── 사이드바 (프로젝트) ────────────────────────────────────
async function loadProjects() {
  state.projects = await api.listProjects();
  renderProjects();
}
function renderProjects() {
  const list = $("projList");
  // 고정 항목 2개는 유지, 나머지 제거
  [...list.querySelectorAll(".proj-item.user")].forEach((n) => n.remove());
  state.projects.forEach((p) => {
    const div = document.createElement("div");
    div.className = "proj-item user" + (String(state.view) === String(p.id) ? " active" : "");
    div.dataset.pid = p.id;
    div.innerHTML = `<span class="proj-name">📂 ${escapeHtml(p.name)}</span>
      <span class="proj-actions">
        <span class="proj-badge">${p.count}</span>
        <button class="icon-btn" data-act="rename" title="이름변경">✎</button>
        <button class="icon-btn" data-act="del" title="삭제">🗑</button>
      </span>`;
    div.addEventListener("click", (e) => {
      const act = e.target.dataset?.act;
      if (act === "rename") { e.stopPropagation(); renameProject(p); }
      else if (act === "del") { e.stopPropagation(); delProject(p); }
      else selectView(p.id);
    });
    list.appendChild(div);
  });
  // 고정 항목 active 표시 갱신
  list.querySelectorAll(".proj-item:not(.user)").forEach((n) => {
    n.classList.toggle("active", n.dataset.pid === String(state.view));
  });
}
async function renameProject(p) {
  const name = prompt("리스트 이름", p.name);
  if (name == null) return;
  await api.renameProject(p.id, name);
  await loadProjects();
}
async function delProject(p) {
  if (!confirm(`'${p.name}' 리스트를 삭제할까요? (이미지는 전체 보관함에 남습니다)`)) return;
  await api.deleteProject(p.id);
  if (String(state.view) === String(p.id)) state.view = "all";
  await loadProjects(); await loadImages();
}

function selectView(pid) {
  state.view = pid;
  backToGallery();
  renderProjects();
  const titles = { all: "전체 이미지", fav: "⭐ 즐겨찾기" };
  const p = state.projects.find((x) => String(x.id) === String(pid));
  $("viewTitle").textContent = titles[pid] || (p ? `📂 ${p.name}` : "이미지");
  loadImages();
}

// ── 갤러리 (스튜디오) ──────────────────────────────────────
async function loadImages() {
  const params = {};
  if (state.view === "fav") params.favorite = true;
  else if (state.view !== "all") params.project_id = state.view;
  state.images = await api.listImages(params);
  renderGallery();
}
function renderGallery() {
  const g = $("gallery");
  if (!state.images.length) {
    g.innerHTML = `<div class="empty">아직 이미지가 없습니다.<br>아래 입력창에 설명을 적고 <b>생성</b>을 눌러보세요.</div>`;
    return;
  }
  g.innerHTML = "";
  state.images.forEach((img) => {
    const c = document.createElement("div");
    c.className = "card";
    const tag = { generate: "생성", edit: "수정", merge: "병합" }[img.kind] || "";
    c.innerHTML = `<img loading="lazy" src="${img.url}" alt="">
      <span class="tag">${tag}</span>${img.favorite ? '<span class="fav">⭐</span>' : ""}`;
    c.addEventListener("click", () => openImage(img.id));
    g.appendChild(c);
  });
}

// ── 단일 뷰어 + 에디터 ─────────────────────────────────────
async function openImage(id) {
  state.current = await api.getImage(id);
  $("gallery").hidden = true;
  $("viewer").hidden = false;
  $("headActions").hidden = false;
  $("viewTitle").textContent = ({ generate: "생성", edit: "수정", merge: "병합" }[state.current.kind] || "이미지") + ` #${id}`;
  $("viewerImg").src = state.current.url + "?t=" + Date.now();
  $("downloadBtn").href = state.current.url;
  $("downloadBtn").setAttribute("download", `image-${id}.png`);
  $("favBtn").textContent = state.current.favorite ? "⭐ 즐겨찾기됨" : "⭐ 즐겨찾기";
  $("editInstruction").value = "";
  resetMask();
  renderLineage();
}
function renderLineage() {
  const box = $("lineage");
  box.innerHTML = "";
  (state.current.lineage || []).forEach((n) => {
    const im = document.createElement("img");
    im.src = n.url; im.title = n.prompt || "";
    if (n.id === state.current.id) im.className = "cur";
    im.addEventListener("click", () => openImage(n.id));
    box.appendChild(im);
  });
}
function backToGallery() {
  state.current = null;
  $("viewer").hidden = true;
  $("gallery").hidden = false;
  $("headActions").hidden = true;
}

async function generate() {
  const prompt = $("promptInput").value.trim();
  if (!prompt) return;
  const btn = $("sendBtn");
  busy(btn, true);
  try {
    const img = await api.generate({
      prompt, size: $("sizeSelect").value,
      project_id: typeof state.view === "number" || /^\d+$/.test(state.view) ? Number(state.view) : null,
    });
    $("promptInput").value = ""; autoGrow($("promptInput"));
    toast("이미지를 생성했습니다 ✓");
    await loadProjects();
    if (state.current) backToGallery();
    await loadImages();
    openImage(img.id);
    advanceQueueAfterGenerate();   // 큐가 있으면 다음 프롬프트 자동 입력
  } catch (e) { toast(errMsg(e), true); }
  finally { busy(btn, false); }
}

// ── 프롬프트 큐 (보관함 → 한 장씩 자동 입력) ───────────────
function splitPromptBlocks(content, split) {
  if (!split) return [String(content || "").trim()].filter(Boolean);
  const blocks = [];
  String(content || "").split(/```/).forEach((part, i) => {
    if (i % 2 === 1) {
      const b = (/^\w+\n/.test(part) ? part.replace(/^\w+\n/, "") : part).trim();
      if (b) blocks.push(b);
    }
  });
  return blocks.length ? blocks : [String(content || "").trim()].filter(Boolean);
}
function renderQueueBar() {
  const bar = $("queueBar");
  if (!state.queue.length) { bar.hidden = true; return; }
  bar.hidden = false;
  const total = state.queue.length;
  if (state.qi >= total) {
    $("queueCount").textContent = `큐 완료 (${total}개)`;
    $("queueCurrent").textContent = "모든 프롬프트를 처리했습니다.";
    return;
  }
  $("queueCount").textContent = `큐 ${state.qi + 1}/${total}`;
  const cur = state.queue[state.qi] || "";
  const one = cur.replace(/\s+/g, " ").trim();
  $("queueCurrent").textContent = one.slice(0, 90) + (one.length > 90 ? "…" : "");
}
function fillCurrentQueue() {
  if (state.qi >= state.queue.length) { toast("큐의 모든 프롬프트를 처리했습니다 ✓"); renderQueueBar(); return; }
  const pi = $("promptInput");
  pi.value = state.queue[state.qi];
  autoGrow(pi); pi.focus();
  renderQueueBar();
}
function skipQueue() {
  if (state.qi < state.queue.length) state.qi++;
  if (state.qi >= state.queue.length) { toast("큐 끝까지 왔습니다."); renderQueueBar(); }
  else fillCurrentQueue();
}
function clearQueue() {
  state.queue = []; state.qi = 0;
  $("promptInput").value = ""; autoGrow($("promptInput"));
  renderQueueBar();
  toast("큐를 비웠습니다.");
}
function advanceQueueAfterGenerate() {
  if (!state.queue.length || state.qi >= state.queue.length) return;
  state.qi++;
  if (state.qi < state.queue.length) {
    fillCurrentQueue();
    toast(`다음 프롬프트(${state.qi + 1}/${state.queue.length})를 입력창에 넣었어요. 검토 후 ‘생성’ ↑`);
  } else {
    renderQueueBar();
    toast("큐의 마지막 프롬프트까지 생성 완료 ✓");
  }
}

// 보관함 → 큐 가져오기 모달
let archSel = [];
async function openArchivePicker() {
  archSel = [];
  $("archivePickCount").textContent = "선택: 0";
  $("archiveModal").hidden = false;
  await renderArchivePickList();
}
async function renderArchivePickList() {
  const wrap = $("archivePickList");
  wrap.innerHTML = '<p class="muted">불러오는 중…</p>';
  let items = [];
  try { items = (await api.listArchives()).archives || []; }
  catch (e) { wrap.innerHTML = `<p class="fail">${errMsg(e)}</p>`; return; }
  if (!items.length) {
    wrap.innerHTML = '<p class="muted">보관된 프롬프트가 없습니다. 프롬프트 빌더에서 「📌 보관」으로 저장하세요.</p>';
    return;
  }
  wrap.innerHTML = "";
  items.forEach((it) => {
    const row = document.createElement("label");
    row.className = "arch-pick-item";
    row.innerHTML = `<input type="checkbox" />
      <span class="api-title">${escapeHtml(it.title)}</span>
      <span class="api-meta">${escapeHtml(it.created)} · ${it.chars.toLocaleString()}자</span>
      <span class="api-prev">${escapeHtml(it.preview)}</span>`;
    row.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) archSel.push(it.id);
      else archSel = archSel.filter((x) => x !== it.id);
      $("archivePickCount").textContent = "선택: " + archSel.length;
    });
    wrap.appendChild(row);
  });
}
async function buildQueueFromSelection() {
  if (!archSel.length) { toast("프롬프트를 1개 이상 선택하세요.", true); return; }
  const split = $("archiveSplit").checked;
  const queue = [];
  for (const id of archSel) {
    try {
      const r = await api.getArchive(id);
      const content = r.ok && r.archive ? r.archive.content : "";
      splitPromptBlocks(content, split).forEach((b) => queue.push(b));
    } catch {}
  }
  if (!queue.length) { toast("가져올 프롬프트 내용이 없습니다.", true); return; }
  state.queue = queue; state.qi = 0;
  $("archiveModal").hidden = true;
  fillCurrentQueue();
  toast(`프롬프트 ${queue.length}개를 큐에 담았습니다. 첫 프롬프트를 입력창에 넣었어요 ✓`);
}

// ── 슬라이드 JSON 일괄 생성 (번호 파일명으로 폴더에 저장) ───
const batch = {
  parsed: null,        // {deck, suggested_size, items:[...]}
  sel: new Set(),      // 선택된 슬라이드 번호
  existing: {},        // {슬라이드번호: 이미 있는 파일명}
  jobId: null,
  timer: null,
  dirOk: "",           // 확인 완료된 출력 폴더
};

function switchQsrc(which) {
  document.querySelectorAll("#qsrcTabs .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.qsrc === which));
  document.querySelectorAll("[data-qsrc-pane]").forEach((p) =>
    p.classList.toggle("hidden", p.dataset.qsrcPane !== which));
}

function parseRangeSpec(spec) {
  const out = new Set();
  String(spec || "").split(/[,\s]+/).forEach((part) => {
    if (!part) return;
    const m = part.match(/^(\d+)\s*[-~]\s*(\d+)$/);
    if (m) {
      const a = Number(m[1]), b = Number(m[2]);
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) out.add(i);
    } else if (/^\d+$/.test(part)) out.add(Number(part));
  });
  return out;
}

// 기본 선택: place=true 만 / 이미 있는 번호 제외
function recomputeBatchSelection() {
  if (!batch.parsed) return;
  const placeOnly = $("batchPlaceOnly").checked;
  const skip = $("batchSkip").checked;
  const range = parseRangeSpec($("batchRange").value);
  batch.sel = new Set(
    batch.parsed.items
      .filter((it) => (!placeOnly || it.place)
        && (!range.size || range.has(it.n))
        && !(skip && batch.existing[it.n]))
      .map((it) => it.n)
  );
  renderBatchList();
}

function renderBatchList() {
  const wrap = $("batchList");
  if (!batch.parsed) { wrap.innerHTML = ""; $("batchCount").textContent = "선택: 0"; return; }
  const nameMode = $("batchNameMode").value;
  wrap.innerHTML = "";
  batch.parsed.items.forEach((it) => {
    const has = batch.existing[it.n];
    const row = document.createElement("label");
    row.className = "batch-row" + (has ? " has-file" : "");
    const fname = nameMode === "num_title"
      ? `${String(it.n).padStart(3, "0")}_${(it.title || "").replace(/[\\/:*?"<>|]/g, "").replace(/\s+/g, "_").slice(0, 28)}.png`
      : `${String(it.n).padStart(3, "0")}.png`;
    row.innerHTML = `<input type="checkbox" ${batch.sel.has(it.n) ? "checked" : ""} />
      <span class="br-n">${String(it.n).padStart(3, "0")}</span>
      <span class="br-title">${escapeHtml(it.title) || "<span class='muted'>(제목 없음)</span>"}</span>
      <span class="br-type">${escapeHtml(it.type)}${it.place ? " · place" : ""}</span>
      <span class="br-file">${has ? "이미 있음: " + escapeHtml(has) : escapeHtml(fname)}</span>`;
    row.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) batch.sel.add(it.n); else batch.sel.delete(it.n);
      updateBatchCount();
    });
    wrap.appendChild(row);
  });
  updateBatchCount();
}
function updateBatchCount() {
  const n = batch.sel.size;
  const dup = [...batch.sel].filter((x) => batch.existing[x]).length;
  $("batchCount").textContent = `선택: ${n}장` + (dup ? ` (덮어쓰기 ${dup}장 포함)` : "");
  $("batchStart").disabled = n === 0;
}

async function loadBatchJson(text) {
  try {
    const r = await api.batchParse(text);
    batch.parsed = r;
    const sizes = state.settings.size_choices || ["auto"];
    fillSizeSelect($("batchSize"), sizes, r.suggested_size);
    const nums = r.items.map((i) => i.n);
    const dupNums = [...new Set(nums.filter((n, i) => nums.indexOf(n) !== i))];
    $("batchSummary").innerHTML =
      `✓ <b>${escapeHtml(r.deck) || "프롬프트"}</b> — 프롬프트 ${r.count}개 인식`
      + (r.aspect ? ` · 비율 ${escapeHtml(r.aspect)} → ${escapeHtml(r.suggested_size)}` : "")
      + ` · place=true ${r.items.filter((i) => i.place).length}개`
      + (dupNums.length ? ` <span class="fail">· ⚠ 번호 중복 ${dupNums.join(", ")}`
        + ` — 같은 파일명에 덮어써집니다</span>` : "");
    if ($("batchDir").value.trim()) await checkBatchDir(true);
    recomputeBatchSelection();
  } catch (e) {
    batch.parsed = null;
    $("batchSummary").innerHTML = `<span class="fail">${errMsg(e)}</span>`;
    renderBatchList();
  }
}

async function checkBatchDir(quiet = false) {
  const dir = $("batchDir").value.trim();
  if (!dir) { if (!quiet) toast("출력 폴더 경로를 입력하세요.", true); return false; }
  try {
    const r = await api.batchInspect(dir);
    if (!r.ok) { batch.dirOk = ""; toast(r.error, true); return false; }
    batch.dirOk = r.dir;
    batch.existing = {};
    Object.entries(r.existing || {}).forEach(([k, v]) => (batch.existing[Number(k)] = v));
    localStorage.setItem("batchDir", r.dir);
    const cnt = Object.keys(batch.existing).length;
    if (!quiet) {
      toast("폴더 확인 ✓ " + (!r.exists ? "아직 없는 폴더 — 생성 시작할 때 만듭니다."
        : cnt ? `이미 있는 번호 파일 ${cnt}개 (건너뛰기 대상)` : "비어 있음"));
    }
    recomputeBatchSelection();
    return true;
  } catch (e) { toast(errMsg(e), true); return false; }
}

async function startBatch() {
  if (!batch.parsed) { toast("먼저 JSON 을 넣어 주세요.", true); return; }
  if (!batch.sel.size) { toast("생성할 슬라이드를 1개 이상 선택하세요.", true); return; }
  if (!(await checkBatchDir(true))) return;
  const items = batch.parsed.items
    .filter((it) => batch.sel.has(it.n))
    .map((it) => ({ n: it.n, title: it.title, prompt: it.prompt }));
  const dup = items.filter((it) => batch.existing[it.n]).length;
  const skip = $("batchSkip").checked;
  const msg = `${items.length}장을 생성합니다.\n\n저장 폴더: ${batch.dirOk}\n`
    + (dup && !skip ? `\n⚠ 이미 있는 번호 ${dup}장을 덮어씁니다.\n` : "")
    + `\n구독 할당량이 ${items.length}장만큼 사용됩니다. 진행할까요?`;
  if (!confirm(msg)) return;

  const btn = $("batchStart");
  busy(btn, true, "시작 중…");
  try {
    const r = await api.batchStart({
      items,
      out_dir: batch.dirOk,
      size: $("batchSize").value,
      deck: batch.parsed.deck || "",
      workers: Number($("batchWorkers").value),
      retries: Number($("batchRetries").value),
      skip_existing: skip,
      with_title: $("batchNameMode").value === "num_title",
      to_gallery: $("batchGallery").checked,
    });
    $("archiveModal").hidden = true;
    attachBatchJob(r.job);
    toast(`일괄 생성을 시작했습니다 (${items.length}장) — 창을 닫아도 계속 진행됩니다 ✓`);
  } catch (e) { toast(errMsg(e), true); }
  finally { busy(btn, false); }
}

function attachBatchJob(job) {
  batch.jobId = job.id;
  renderBatchBar(job);
  if (batch.timer) clearInterval(batch.timer);
  batch.timer = setInterval(pollBatch, 2000);
}

let lastBatchDone = -1;
async function pollBatch() {
  if (!batch.jobId) return;
  try {
    const r = await api.batchJob(batch.jobId);
    renderBatchBar(r.job);
    const c = r.job.counts;
    if (c.done !== lastBatchDone) {          // 새로 만들어진 게 있으면 갤러리 갱신
      lastBatchDone = c.done;
      await loadImages();
    }
    if (r.job.status !== "running" && r.job.status !== "stopping") {
      clearInterval(batch.timer); batch.timer = null;
      await loadProjects();
      const tail = c.failed ? `실패 ${c.failed}장` : "전부 완료";
      toast(`일괄 생성 종료 — 성공 ${c.done} · 건너뜀 ${c.skipped} · ${tail}`, c.failed > 0);
    }
  } catch (e) {
    clearInterval(batch.timer); batch.timer = null;
    $("batchBarCurrent").textContent = errMsg(e);
  }
}

function renderBatchBar(job) {
  const bar = $("batchBar");
  bar.hidden = false;
  const c = job.counts;
  const pct = c.total ? Math.round((c.settled / c.total) * 100) : 0;
  $("batchBarFill").style.width = pct + "%";
  const label = { running: "일괄 생성 중", stopping: "중단 중", done: "완료",
                  stopped: "중단됨", error: "오류로 중단" }[job.status] || job.status;
  $("batchBarCount").textContent =
    `${label} ${c.settled}/${c.total} · 성공 ${c.done}` +
    (c.skipped ? ` · 건너뜀 ${c.skipped}` : "") +
    (c.failed ? ` · 실패 ${c.failed}` : "");
  const failed = job.items.filter((i) => i.status === "failed");
  if (job.fatal) {
    $("batchBarCurrent").innerHTML = `<span class="fail">${escapeHtml(job.fatal)}</span>`;
  } else if (job.running_slides.length) {
    $("batchBarCurrent").textContent =
      "생성 중: " + job.running_slides.map((n) => String(n).padStart(3, "0")).join(", ");
  } else if (failed.length) {
    $("batchBarCurrent").innerHTML = `<span class="fail">실패 ${failed
      .map((i) => String(i.n).padStart(3, "0")).join(", ")} — ${escapeHtml(failed[0].error || "")}</span>`;
  } else {
    $("batchBarCurrent").textContent = job.out_dir;
  }
  const busyNow = job.status === "running" || job.status === "stopping";
  $("batchStopBtn").hidden = !busyNow;
  $("batchHideBtn").hidden = busyNow;
  $("batchRetryBtn").hidden = busyNow || !failed.length;
  batch.dirOk = job.out_dir || batch.dirOk;
}

async function stopBatch() {
  if (!batch.jobId) return;
  if (!confirm("진행 중인 일괄 생성을 중단할까요? (이미 만든 파일은 그대로 남습니다)")) return;
  try { renderBatchBar((await api.batchStop(batch.jobId)).job); toast("중단을 요청했습니다. 진행 중인 장은 끝까지 만듭니다."); }
  catch (e) { toast(errMsg(e), true); }
}
async function retryBatch() {
  if (!batch.jobId) return;
  try {
    const r = await api.batchRetry(batch.jobId);
    attachBatchJob(r.job);
    toast(`실패 ${r.requeued}장을 다시 시도합니다.`);
  } catch (e) { toast(errMsg(e), true); }
}
async function revealBatchDir() {
  const dir = batch.dirOk || $("batchDir").value.trim();
  if (!dir) { toast("폴더 경로가 없습니다.", true); return; }
  try { const r = await api.batchReveal(dir); if (!r.ok) toast(r.error, true); }
  catch (e) { toast(errMsg(e), true); }
}

// 서버에서 이미 돌고 있는 배치가 있으면 새로고침 후에도 다시 붙는다.
async function resumeBatch() {
  try {
    const r = await api.batchActive();
    if (r.job) attachBatchJob(r.job);
  } catch {}
}

async function readBatchFiles(fileList) {
  const f = [...(fileList || [])][0];
  if (!f) return;
  const text = await f.text();
  $("batchPaste").value = "";
  await loadBatchJson(text);
}

async function applyEdit() {
  if (!state.current) return;
  const instruction = $("editInstruction").value.trim();
  if (!instruction) { toast("수정 지시문을 입력하세요.", true); return; }
  const btn = $("applyEditBtn");
  busy(btn, true);
  try {
    const body = { instruction, size: state.current.size };
    if ($("maskToggle").checked && hasMaskStrokes()) {
      body.type = "mask";
      body.mask_image = buildMaskComposite();
    } else {
      body.type = "nl";
    }
    const img = await api.edit(state.current.id, body);
    toast("수정본을 생성했습니다 ✓");
    await loadImages();
    openImage(img.id);
  } catch (e) { toast(errMsg(e), true); }
  finally { busy(btn, false); }
}

// ── 마스크 그리기 ──────────────────────────────────────────
let drawing = false, strokes = false;
const canvas = $("maskCanvas"), cctx = canvas.getContext("2d");

function syncMaskCanvas() {
  const img = $("viewerImg");
  const wrap = $("canvasWrap");
  const r = img.getBoundingClientRect();
  const wr = wrap.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(r.width));
  canvas.height = Math.max(1, Math.round(r.height));
  canvas.style.left = (r.left - wr.left + wrap.scrollLeft) + "px";
  canvas.style.top = (r.top - wr.top + wrap.scrollTop) + "px";
  canvas.style.width = r.width + "px";
  canvas.style.height = r.height + "px";
}
function resetMask() {
  $("maskToggle").checked = false;
  $("maskTools").hidden = true; $("maskHint").hidden = true;
  canvas.style.display = "none";
  cctx.clearRect(0, 0, canvas.width, canvas.height);
  strokes = false;
}
function clearMask() { cctx.clearRect(0, 0, canvas.width, canvas.height); strokes = false; }
function hasMaskStrokes() { return strokes; }
function paintAt(e) {
  const r = canvas.getBoundingClientRect();
  const x = (e.clientX - r.left) * (canvas.width / r.width);
  const y = (e.clientY - r.top) * (canvas.height / r.height);
  cctx.fillStyle = "rgba(255,46,46,0.55)";
  cctx.beginPath();
  cctx.arc(x, y, Number($("brushSize").value) / 2, 0, Math.PI * 2);
  cctx.fill();
  strokes = true;
}
function buildMaskComposite() {
  // 원본(자연 해상도) 위에 칠한 영역을 강조해 합성한 PNG data URL.
  const img = $("viewerImg");
  const off = document.createElement("canvas");
  off.width = img.naturalWidth || canvas.width;
  off.height = img.naturalHeight || canvas.height;
  const o = off.getContext("2d");
  o.drawImage(img, 0, 0, off.width, off.height);
  o.drawImage(canvas, 0, 0, off.width, off.height);
  return off.toDataURL("image/png");
}

// ── 병합 모달 ──────────────────────────────────────────────
let mergeSel = [];
let mergeUploads = []; // PC에서 추가한 이미지(data URL 문자열)
function openMerge() {
  mergeSel = [];
  mergeUploads = [];
  renderUploads();
  const picker = $("mergePicker");
  picker.innerHTML = "";
  state.images.forEach((img) => {
    const d = document.createElement("div");
    d.className = "pick"; d.dataset.id = img.id;
    d.innerHTML = `<img src="${img.url}"><span class="order"></span>`;
    d.addEventListener("click", () => {
      const i = mergeSel.indexOf(img.id);
      if (i >= 0) mergeSel.splice(i, 1); else mergeSel.push(img.id);
      d.classList.toggle("sel", mergeSel.includes(img.id));
      refreshMergeOrders();
    });
    picker.appendChild(d);
  });
  // 현재 보고 있는 이미지를 기본 선택
  if (state.current) {
    mergeSel = [state.current.id];
    const d = picker.querySelector(`.pick[data-id="${state.current.id}"]`);
    if (d) d.classList.add("sel");
  }
  refreshMergeOrders();
  $("mergePrompt").value = "";
  $("mergeModal").hidden = false;
}
function refreshMergeOrders() {
  $("mergePicker").querySelectorAll(".pick").forEach((d) => {
    const idx = mergeSel.indexOf(Number(d.dataset.id));
    d.querySelector(".order").textContent = idx >= 0 ? idx + 1 : "";
  });
  $("mergeCount").textContent =
    "선택: " + mergeSel.length + (mergeUploads.length ? ` · PC ${mergeUploads.length}` : "");
}

// PC에서 추가한 이미지: 스튜디오 선택(파란 번호 뱃지)과 다르게 오렌지 'PC' 뱃지 + 제거 버튼으로 표식
function renderUploads() {
  const list = $("mergeUploadList");
  if (!list) return;
  list.innerHTML = "";
  list.hidden = mergeUploads.length === 0;
  mergeUploads.forEach((url, i) => {
    const d = document.createElement("div");
    d.className = "pick upload";
    d.innerHTML = `<img src="${url}"><span class="badge-pc">PC</span><button class="rm" title="제거">✕</button>`;
    d.querySelector(".rm").addEventListener("click", () => {
      mergeUploads.splice(i, 1);
      renderUploads();
      refreshMergeOrders();
    });
    list.appendChild(d);
  });
}
function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(new Error("파일 읽기 실패"));
    fr.readAsDataURL(file);
  });
}
async function handleMergeFiles(fileList) {
  const files = Array.from(fileList || []).filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  for (const f of files) {
    try { mergeUploads.push(await readFileAsDataURL(f)); }
    catch { toast(`${f.name} 읽기 실패`, true); }
  }
  renderUploads();
  refreshMergeOrders();
}
async function runMerge() {
  const prompt = $("mergePrompt").value.trim();
  if (!prompt) { toast("병합 지시문을 입력하세요.", true); return; }
  if (!mergeSel.length && !mergeUploads.length) {
    toast("이미지를 1장 이상 선택하거나 PC에서 추가하세요.", true); return;
  }
  const btn = $("mergeRun");
  busy(btn, true);
  try {
    const img = await api.compose({
      prompt, source_ids: mergeSel, extra_images: mergeUploads,
      project_id: /^\d+$/.test(state.view) ? Number(state.view) : null,
    });
    $("mergeModal").hidden = true;
    toast("병합 이미지를 생성했습니다 ✓");
    await loadImages();
    openImage(img.id);
  } catch (e) { toast(errMsg(e), true); }
  finally { busy(btn, false); }
}

// ── 설정 모달 ──────────────────────────────────────────────
async function openSettings() {
  const s = state.settings;
  fillSizeSelect($("defSizeSelect"), s.size_choices || ["auto"], s.default_size);
  const st = await refreshAuthChip();
  $("authStatus").innerHTML = authStatusHtml(st);
  $("settingsMsg").textContent = "";
  $("settingsModal").hidden = false;
}
function authStatusHtml(s) {
  if (!s) return "상태 확인 실패";
  if (!s.installed) return "❌ codex CLI 미설치 — <code>npm i -g @openai/codex</code> 후 <code>codex login</code>";
  if (!s.authenticated) return "⚠️ ChatGPT 미로그인 — 터미널에서 <code>codex login</code> 실행";
  return `✅ ChatGPT 로그인됨${s.email ? " — " + s.email : ""} (키 없이 구독 할당량 사용)`;
}
async function saveSettings() {
  const patch = { default_size: $("defSizeSelect").value };
  const btn = $("settingsSave");
  busy(btn, true, "저장 중…");
  try {
    state.settings = await api.saveSettings(patch);
    try { fillSizeSelect($("sizeSelect"), state.settings.size_choices, state.settings.default_size); } catch {}
    $("settingsModal").hidden = true;      // 저장 즉시 닫기
    toast("설정을 저장했습니다 ✓");
    refreshAuthChip();                      // 비차단 갱신
    loadImages();
  } catch (e) {
    $("settingsMsg").textContent = errMsg(e);
  } finally { busy(btn, false); }
}

// ── 유틸 ───────────────────────────────────────────────────
function escapeHtml(s) { return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function errMsg(e) {
  if (e.status === 401) return "로그인이 필요합니다 — 터미널에서 <b>codex login</b> 후 다시 시도하세요.";
  return e.message || "오류가 발생했습니다.";
}
function autoGrow(el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; }

// ── 이벤트 바인딩 ──────────────────────────────────────────
function wire() {
  $("collapseBtn").addEventListener("click", () => $("app").classList.toggle("collapsed"));
  $("expandBtn").addEventListener("click", () => $("app").classList.remove("collapsed"));
  $("newProjectBtn").addEventListener("click", async () => {
    const name = prompt("새 리스트 이름", "새 리스트");
    if (name == null) return;
    const p = await api.createProject(name);
    await loadProjects(); selectView(p.id);
  });
  document.querySelectorAll('.proj-item:not(.user)').forEach((n) =>
    n.addEventListener("click", () => selectView(n.dataset.pid)));

  // 입력창
  const pi = $("promptInput");
  pi.addEventListener("input", () => autoGrow(pi));
  pi.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); generate(); }
  });
  $("sendBtn").addEventListener("click", generate);
  $("sizeSelect").addEventListener("change", () => {});

  // 뷰어/에디터
  $("backToGallery").addEventListener("click", backToGallery);
  $("applyEditBtn").addEventListener("click", applyEdit);
  $("favBtn").addEventListener("click", async () => {
    if (!state.current) return;
    const r = await api.favorite(state.current.id);
    state.current.favorite = r.favorite;
    $("favBtn").textContent = r.favorite ? "⭐ 즐겨찾기됨" : "⭐ 즐겨찾기";
    loadImages();
  });
  $("deleteBtn").addEventListener("click", async () => {
    if (!state.current || !confirm("이 이미지를 삭제할까요?")) return;
    await api.remove(state.current.id);
    backToGallery(); loadProjects(); loadImages();
    toast("삭제했습니다");
  });

  // 마스크
  $("maskToggle").addEventListener("change", (e) => {
    const on = e.target.checked;
    $("maskTools").hidden = !on; $("maskHint").hidden = !on;
    canvas.style.display = on ? "block" : "none";
    if (on) syncMaskCanvas();
  });
  $("clearMask").addEventListener("click", clearMask);
  canvas.addEventListener("pointerdown", (e) => { drawing = true; canvas.setPointerCapture(e.pointerId); paintAt(e); });
  canvas.addEventListener("pointermove", (e) => { if (drawing) paintAt(e); });
  canvas.addEventListener("pointerup", () => (drawing = false));
  window.addEventListener("resize", () => { if ($("maskToggle").checked) syncMaskCanvas(); });

  // 병합
  $("plusBtn").addEventListener("click", openMerge);
  $("mergeClose").addEventListener("click", () => ($("mergeModal").hidden = true));
  $("mergeRun").addEventListener("click", runMerge);
  $("mergeUploadBtn").addEventListener("click", () => $("mergeFileInput").click());
  $("mergeFileInput").addEventListener("change", (e) => {
    handleMergeFiles(e.target.files);
    e.target.value = ""; // 같은 파일 다시 선택 가능하도록 초기화
  });

  // 매뉴얼 (새 탭)
  $("manualBtn").addEventListener("click", () => window.open("/manual.html", "_blank"));

  // 설정
  $("settingsBtn").addEventListener("click", openSettings);
  $("settingsClose").addEventListener("click", () => ($("settingsModal").hidden = true));
  $("settingsSave").addEventListener("click", saveSettings);

  // 로그인 / 계정변경 / 로그아웃 (새 cmd 창에서 codex 실행)
  $("loginBtn").addEventListener("click", async () => {
    try { const r = await api.authLogin(); toast(r.ok ? r.message : (r.error || "실패"), !r.ok); }
    catch (e) { toast(errMsg(e), true); }
  });
  $("logoutBtn").addEventListener("click", async () => {
    if (!confirm("현재 ChatGPT 계정에서 로그아웃할까요? (새 창에서 진행)")) return;
    try { const r = await api.authLogout(); toast(r.ok ? r.message : (r.error || "실패"), !r.ok); }
    catch (e) { toast(errMsg(e), true); }
  });
  $("authRefreshBtn").addEventListener("click", async () => {
    const st = await refreshAuthChip();
    $("authStatus").innerHTML = authStatusHtml(st);
  });

  // 프롬프트 큐 (보관함에서 가져와 한 장씩 자동 입력)
  $("queueBtn").addEventListener("click", openArchivePicker);
  $("archiveModalClose").addEventListener("click", () => ($("archiveModal").hidden = true));
  $("archiveReload").addEventListener("click", renderArchivePickList);
  $("archiveToQueue").addEventListener("click", buildQueueFromSelection);
  $("queueFillBtn").addEventListener("click", fillCurrentQueue);
  $("queueSkipBtn").addEventListener("click", skipQueue);
  $("queueClearBtn").addEventListener("click", clearQueue);

  // 슬라이드 JSON 일괄 생성
  $("qsrcTabs").addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t) switchQsrc(t.dataset.qsrc);
  });
  $("batchPick").addEventListener("click", () => $("batchFile").click());
  $("batchFile").addEventListener("change", async (e) => {
    await readBatchFiles(e.target.files);
    e.target.value = "";
  });
  const bdrop = $("batchDrop");
  ["dragenter", "dragover"].forEach((ev) => bdrop.addEventListener(ev, (e) => {
    e.preventDefault(); bdrop.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((ev) => bdrop.addEventListener(ev, (e) => {
    e.preventDefault(); bdrop.classList.remove("drag");
  }));
  bdrop.addEventListener("drop", (e) => readBatchFiles(e.dataTransfer.files));
  $("batchPasteToggle").addEventListener("click", () =>
    $("batchPasteWrap").classList.toggle("hidden"));
  $("batchPasteRead").addEventListener("click", () => loadBatchJson($("batchPaste").value));
  $("batchDirCheck").addEventListener("click", () => checkBatchDir());
  $("batchDirOpen").addEventListener("click", revealBatchDir);
  $("batchDir").addEventListener("change", () => checkBatchDir());
  $("batchNameMode").addEventListener("change", renderBatchList);
  ["batchSkip", "batchPlaceOnly"].forEach((id) =>
    $(id).addEventListener("change", recomputeBatchSelection));
  $("batchRangeApply").addEventListener("click", recomputeBatchSelection);
  $("batchSelectAll").addEventListener("click", () => {
    if (!batch.parsed) return;
    batch.sel = new Set(batch.parsed.items.map((i) => i.n));
    renderBatchList();
  });
  $("batchSelectNone").addEventListener("click", () => { batch.sel = new Set(); renderBatchList(); });
  $("batchStart").addEventListener("click", startBatch);
  $("batchStopBtn").addEventListener("click", stopBatch);
  $("batchRetryBtn").addEventListener("click", retryBatch);
  $("batchOpenDirBtn").addEventListener("click", revealBatchDir);
  $("batchHideBtn").addEventListener("click", () => { $("batchBar").hidden = true; });

  // 모달 바깥 클릭 닫기
  document.querySelectorAll(".modal").forEach((m) =>
    m.addEventListener("click", (e) => { if (e.target === m) m.hidden = true; }));
}

// ── 시작 ───────────────────────────────────────────────────
(async function init() {
  wire();
  await loadSettings();
  fillSizeSelect($("batchSize"), state.settings.size_choices || ["auto"], "1536x1024");
  $("batchDir").value = localStorage.getItem("batchDir") || "";
  await refreshAuthChip();
  await loadProjects();
  await loadImages();
  await resumeBatch();   // 서버에서 돌고 있는 일괄 생성이 있으면 진행바 복구
})();
