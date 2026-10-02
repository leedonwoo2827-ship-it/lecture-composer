/* 상태 + API 캐시
 *
 * "지금 어느 프로젝트인가" 는 localStorage 에 산다. URL(해시)은 **화면만** 고른다.
 * 그래서 스테이지 화면을 열어 둔 채 프로젝트를 바꿔도 해시가 흔들리지 않는다.
 *
 * 서버 상태는 모듈 수준 캐시에 담고 invalidate() 로만 버린다. 화면끼리는
 * window CustomEvent 로 동기화한다 — import 사이클을 만들지 않으려고.
 */
"use strict";

import { api } from "./util.js";

const K_PROJECT = "sa.project";

export const state = {
  /* ★ 화면을 열면서 "이 줄을 짚어라" 고 넘기는 값. URL 에 담지 않는다 —
   * 해시에 뒤에 뭘 붙이면 라우터의 경로 매칭이 통째로 깨진다(실제로 깨졌다).
   * 받는 쪽이 읽고 바로 비운다. */
  focusProject: null,
  get projectId() {
    const v = Number(localStorage.getItem(K_PROJECT) || 0);
    return v > 0 ? v : null;
  },
  set projectId(v) {
    if (v) localStorage.setItem(K_PROJECT, String(v));
    else localStorage.removeItem(K_PROJECT);
    _project = null;
    _stages = null;
    announce("sa:project-changed", { id: v || null });
  },
};

let _settings = null;
let _projects = null;
let _project = null;
let _stages = null;

export async function getSettings(force = false) {
  if (!_settings || force) _settings = await api("/api/settings");
  return _settings;
}

export async function saveSettings(patch) {
  _settings = await api("/api/settings", { method: "POST", body: patch });
  announce("sa:settings-changed", _settings);
  return _settings;
}

export async function getProjects(force = false) {
  if (!_projects || force) _projects = await api("/api/projects");
  return _projects;
}

export async function getProject(force = false) {
  const id = state.projectId;
  if (!id) return null;
  if (_project && _project.id === id && !force) return _project;
  try {
    _project = await api(`/api/projects/${id}`);
  } catch (e) {
    _project = null;
    // ★ 404(정말 없어진 프로젝트)일 때만 선택을 놓아준다.
    //   모든 오류에서 놓아주면, 리로드로 요청이 취소되거나 서버가 한 박자
    //   늦기만 해도 고른 프로젝트가 사라진다 — IDA 에서 실제로 겪은 문제.
    if (!e || e.status !== 404) throw e;

    /* ★ 놓아주는 데서 끝내면 안 된다. 폴더를 지우거나 감추고 나면 브라우저는
     * 없어진 id 를 계속 들고 있고, 화면은 "프로젝트를 찾을 수 없습니다" 만
     * 띄운 채 멈춘다 — 사람은 뭘 눌러야 할지 모른다. 남은 것 중 하나로
     * **스스로 옮겨 간다.** 하나도 없으면 그때 비운다(시작 화면이 받는다). */
    const rest = await getProjects(true).catch(() => []);
    const next = rest.find((p) => p.id !== id) || null;
    state.projectId = next ? next.id : null;   // 이벤트가 화면을 다시 그린다
    if (!next) return null;
    _project = await api(`/api/projects/${next.id}`).catch(() => null);
    return _project;
  }
  return _project;
}

export async function getStages(force = false) {
  const id = state.projectId;
  if (!id) return null;
  if (_stages && _stages.project_id === id && !force) return _stages;
  _stages = await api(`/api/projects/${id}/stages`);
  return _stages;
}

export function invalidate() {
  _settings = null;
  _projects = null;
  _project = null;
  _stages = null;
}

export function invalidateStages() {
  _stages = null;
}

export function announce(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}
