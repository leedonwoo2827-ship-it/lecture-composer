/* 프로젝트 — 패널(고르는 곳). **목록 전용.**
 *
 * 만들기 폼은 여기 없다. 입력창이 있는 화면은 패널에 두지 않는다는 규칙 때문에
 * 바닥(home.js)의 "시작" 으로 옮겼다. 패널은 Esc·스크림으로 닫히므로 경로를
 * 타이핑하다 한 번 잘못 누르면 날아간다.
 */
"use strict";

import { el, icon } from "./util.js";
import { state, getProjects } from "./store.js";
import { closePanel } from "./panel.js";
import { navigate } from "./shell.js";

export const meta = { title: "프로젝트", subtitle: "쇼케이스로 만들 대상" };

export async function mount(root) {
  const list = el("div", "co-list");
  root.appendChild(list);

  const projects = await getProjects(true).catch(() => []);
  if (!projects.length) {
    const empty = el("div", "empty");
    empty.appendChild(el("p", null, "아직 프로젝트가 없습니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("plus", 14), el("span", null, "시작 화면으로"));
    b.onclick = () => { closePanel(); navigate("/home"); };
    empty.appendChild(b);
    list.appendChild(empty);
    return;
  }

  for (const p of projects) {
    const row = el("button", "co-row" + (p.id === state.projectId ? " active" : ""));
    row.type = "button";
    row.append(el("span", "co-name", p.title || p.slug),
               el("span", "co-meta", `${p.items || 0}개 항목`),
               icon("chevronRight", 14));
    row.onclick = () => { state.projectId = p.id; closePanel(); };
    list.appendChild(row);
  }
}
