// api.js — 백엔드 호출 래퍼
// ★ 이 앱은 쇼케이스 서버의 /imgstudio 아래에 얹혀 있다.
//   index.html 이 페이지 위치에서 뽑아 둔 기준점을 쓴다. 이걸 안 붙이면
//   "/api/..." 가 호스트(쇼케이스)의 API 를 때린다.
const B = (window.__IS_BASE__ || "");
async function jget(url) {
  const r = await fetch(B + url);
  if (!r.ok) throw await err(r);
  return r.json();
}
async function jsend(url, method, body) {
  const r = await fetch(B + url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw await err(r);
  return r.json();
}
async function err(r) {
  let msg = `HTTP ${r.status}`;
  try { const j = await r.json(); if (j.detail) msg = j.detail; } catch {}
  const e = new Error(msg); e.status = r.status; return e;
}

export const api = {
  authStatus: () => jget("/api/auth/status"),
  authLogin: () => jsend("/api/auth/login", "POST"),
  authLogout: () => jsend("/api/auth/logout", "POST"),
  getSettings: () => jget("/api/settings"),
  saveSettings: (patch) => jsend("/api/settings", "POST", patch),

  // 보관함(빌더에서 저장한 프롬프트) — 스튜디오 큐에서 가져오기
  listArchives: () => jget("/api/builder/archives"),
  getArchive: (id) => jget(`/api/builder/archives/${id}`),

  listProjects: () => jget("/api/projects"),
  createProject: (name) => jsend("/api/projects", "POST", { name }),
  renameProject: (id, name) => jsend(`/api/projects/${id}`, "PATCH", { name }),
  deleteProject: (id) => jsend(`/api/projects/${id}`, "DELETE"),

  listImages: (params = {}) => {
    const q = new URLSearchParams();
    if (params.project_id != null) q.set("project_id", params.project_id);
    if (params.favorite) q.set("favorite", "true");
    const s = q.toString();
    return jget("/api/images" + (s ? "?" + s : ""));
  },
  getImage: (id) => jget(`/api/images/${id}`),
  generate: (body) => jsend("/api/images/generate", "POST", body),
  edit: (id, body) => jsend(`/api/images/${id}/edit`, "POST", body),
  compose: (body) => jsend("/api/images/compose", "POST", body),
  // 슬라이드 JSON 일괄 생성
  batchParse: (text) => jsend("/api/batch/parse", "POST", { text }),
  batchInspect: (dir) => jsend("/api/batch/inspect", "POST", { dir }),
  batchReveal: (dir) => jsend("/api/batch/reveal", "POST", { dir }),
  batchStart: (body) => jsend("/api/batch/start", "POST", body),
  batchActive: () => jget("/api/batch/active"),
  batchJob: (id) => jget(`/api/batch/${id}`),
  batchStop: (id) => jsend(`/api/batch/${id}/stop`, "POST"),
  batchRetry: (id) => jsend(`/api/batch/${id}/retry`, "POST"),

  favorite: (id) => jsend(`/api/images/${id}/favorite`, "POST"),
  move: (id, project_id) => jsend(`/api/images/${id}/move`, "POST", { project_id }),
  remove: (id) => jsend(`/api/images/${id}`, "DELETE"),
};
