/* 프로젝트 탭 — 바닥 **상단에 항상** 있다.
 *
 * 카인드 / 엑스잼 / … 프로젝트를 오가는 스위치다. 개수가 고정이 아니라
 * 워크스페이스에 있는 만큼 그때그때 만들어진다.
 *
 * 셸이 그린다(각 화면이 아니라). 그래야 프레임·대본·덱 어느 화면에 있어도
 * 같은 자리에 같은 탭이 있고, 화면을 오갈 때 탭이 사라졌다 나타나지 않는다.
 *
 * ★ 탭을 눌러도 지금 보고 있는 **화면 종류는 유지**된다. 대본을 고치다
 *   엑스잼으로 넘어가면 엑스잼의 대본 화면이 나온다 — 홈으로 튕기지 않는다.
 *
 * ★ 지우기는 여기 없다. 레일의 최근 프로젝트 줄에 휴지통 하나로 둔다 —
 *   탭은 오가는 스위치라, 옮겨 다니는 손 밑에 파괴 버튼을 두지 않는다.
 */
"use strict";

import { el } from "./util.js";

/**
 * @param {Array}  projects [{id, title, slug, items}]
 * @param {number} activeId 현재 프로젝트 id
 * @param {Function} onPick (id) => void
 */
export function projectTabs(projects, activeId, onPick) {
  const bar = el("div", "tabs");
  bar.setAttribute("role", "tablist");

  for (const p of projects) {
    const on = p.id === activeId;
    const b = el("button", "tab" + (on ? " active" : ""));
    b.type = "button";
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(on));
    b.title = p.title || p.slug;

    b.appendChild(el("span", "tab-name", p.title || p.slug));
    if (p.items) b.appendChild(el("span", "tab-badge", String(p.items)));

    b.onclick = () => { if (!on) onPick(p.id); };
    bar.appendChild(b);
  }

  const add = el("button", "tab tab-add");
  add.type = "button";
  add.title = "프로젝트 추가";
  add.textContent = "+";
  add.onclick = () => onPick(null);          // null = 새로 만들기
  bar.appendChild(add);

  return bar;
}
