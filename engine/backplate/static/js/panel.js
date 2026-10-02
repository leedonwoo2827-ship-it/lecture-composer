/* 부유 패널 (Layer 1) — 목록은 여기, 작업은 바탕.
 *
 * 패널을 열어도 바탕은 언마운트되지 않는다. 그래서 몇 분 걸리는 생성이 진행되는
 * 중에도, 편집기에 미저장 텍스트가 있어도 그 위로 목록을 열 수 있다.
 *
 * 그 대가로 지켜야 할 규칙: **미저장 텍스트를 든 화면을 패널에 두지 않는다.**
 * 패널은 Esc·스크림 클릭으로 닫히므로 편집이 날아간다.
 */
"use strict";

import { $, el, icon } from "./util.js";
import { hydrateIcons } from "./icons.js";

const layer = $("#panel-layer");
let host = null;          // { root, body, rail, head, setHead, focusBody }
let lastFocus = null;
let closeHandler = null;

export const isOpen = () => !!host;
export function setCloseHandler(fn) { closeHandler = fn; }

/* 닫기는 직접 닫지 않고 셸에 위임한다. 셸이 바탕 라우트로 되돌리며 닫는다.
 * history.back() 을 쓰면 안 된다 — 이너 레일로 옮겨 다녔다면 바로 이전 기록도
 * 또 다른 패널이라서, 닫히는 대신 한 칸 되돌아간 것처럼 보인다. */
function requestClose() {
  if (closeHandler) closeHandler();
  else closePanel();
}

function onKey(e) {
  if (e.key === "Escape" && host) { e.preventDefault(); requestClose(); }
}

export function openPanel({ railed = true } = {}) {
  if (host) {
    // 이미 열려 있으면 내용만 갈아 끼운다 — rise 애니메이션을 다시 재생하지 않는다.
    host.root.classList.toggle("no-rail", !railed);
    host.rail.innerHTML = "";
    host.actions.innerHTML = "";
    return host;
  }
  lastFocus = document.activeElement;

  const scrim = el("div", "panel-scrim");
  scrim.dataset.panelDismiss = "1";

  const root = el("div", "panel" + (railed ? "" : " no-rail"));
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-labelledby", "panel-title");

  const rail = el("div", "panel-rail");
  const main = el("div", "panel-main");
  const head = el("div", "panel-head");
  const headLeft = el("div");
  const h2 = el("h2");
  h2.id = "panel-title";
  const sub = el("p");
  sub.hidden = true;
  headLeft.append(h2, sub);
  const actions = el("div", "panel-actions");
  const close = el("button", "panel-close");
  close.type = "button";
  close.title = "닫기 (Esc)";
  close.setAttribute("aria-label", "닫기");
  close.append(icon("x", 17));
  close.addEventListener("click", requestClose);
  head.append(headLeft, actions, close);

  const body = el("div", "panel-body");
  body.id = "panel-body";
  body.tabIndex = -1;
  main.append(head, body);
  root.append(rail, main);

  layer.innerHTML = "";
  layer.append(scrim, root);
  layer.hidden = false;

  layer.addEventListener("click", (e) => {
    if (e.target.closest("[data-panel-dismiss]")) requestClose();
  });
  document.addEventListener("keydown", onKey);

  /* 바탕 전체를 inert 로 만든다. Tab 트랩을 손으로 구현하지 않는 이유:
   * Chrome 은 tabindex 없는 스크롤 가능 div 에도 포커스를 주므로 "마지막 포커스
   * 가능 요소"를 신뢰성 있게 계산할 수 없다. inert 는 브라우저가 처리한다. */
  $(".app")?.setAttribute("inert", "");
  document.body.style.overflow = "hidden";

  host = {
    root, body, rail, actions,
    setHead(title, subtitle) {
      h2.textContent = title || "";
      sub.textContent = subtitle || "";
      sub.hidden = !subtitle;
    },
    focusBody() { body.focus({ preventScroll: true }); },
  };
  return host;
}

export function closePanel() {
  if (!host) return;
  document.removeEventListener("keydown", onKey);
  layer.hidden = true;
  layer.innerHTML = "";
  host = null;
  document.body.style.overflow = "";
  // ★ 순서가 중요하다 — inert 를 먼저 벗겨야 포커스 복원이 먹는다.
  $(".app")?.removeAttribute("inert");
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  lastFocus = null;
}

/** 패널 머리 우측 액션 버튼들. [] 를 주면 비운다. */
export function setActions(nodes) {
  if (!host) return;
  host.actions.innerHTML = "";
  (nodes || []).filter(Boolean).forEach((n) => host.actions.appendChild(n));
  hydrateIcons(host.actions);
}

/**
 * 패널 머리에 쓸 액션 버튼.
 *
 * ✕ 아이콘만 두면 "나가는 방법이 없다" 고 읽힌다(실제 피드백). 라벨이 있는
 * 버튼을 함께 두고, 고른 뒤 이어서 할 일을 1순위 액션으로 노출한다.
 */
export function actionBtn(label, { primary = false, iconName, onClick } = {}) {
  const b = el("button", "btn" + (primary ? " primary" : ""));
  b.type = "button";
  if (iconName) b.appendChild(icon(iconName, 14));
  b.appendChild(el("span", null, label));
  if (onClick) b.addEventListener("click", onClick);
  return b;
}

/** 패널을 닫는 버튼(라벨 있는 버전). 닫기 동작은 셸에 위임한다. */
export function closeActionBtn(label = "닫기") {
  return actionBtn(label, { iconName: "x", onClick: requestClose });
}
