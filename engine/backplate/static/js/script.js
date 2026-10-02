/* 대본 — **바닥(편집기)**. 미저장 텍스트가 사는 곳이라 절대 패널에 두지 않는다.
 *
 * 실행("무엇을 다시 돌릴까")은 여기가 아니라 떠 있는 창이 맡는다.
 * 헤드의 버튼이 그 창을 이 화면에 맞는 범위로 연다 — #/board
 *
 * 아직 스테이지 구현 전이라 화면은 비어 있다. s6-script · s10-tts · s11-audio 가 붙으면 채운다.
 */
"use strict";

import { el, icon } from "./util.js";
import { navigate } from "./shell.js";

export const meta = {
  title: "대본",
  subtitle: "내레이션 문장과 발음(발음기호)을 고칩니다",
  actions: () => {
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "실행기 열기"));
    b.onclick = () => navigate("/board");
    return [b];
  },
};

export async function mount(root) {
  const page = el("div", "page");
  const box = el("div", "empty");
  box.appendChild(el("p", null, "아직 이 화면의 스테이지가 구현되지 않았습니다."));
  box.appendChild(el("p", null, "필요한 단계: s6-script · s10-tts · s11-audio"));
  page.appendChild(box);
  root.appendChild(page);
}
