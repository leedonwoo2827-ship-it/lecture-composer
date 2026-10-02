/* 순서 번호 — 화면 쪽 거들기.
 *
 * ★ **번호표 자체는 `core/steps.py` 에 있다.** 여기 다시 적지 않는다.
 *   서버가 이력 줄마다 번호(`n`)를 실어 보내므로, 화면은 그것을 그리기만 한다.
 *
 * 번호를 붙이는 이유: 자리마다 이름이 다르다. 덱의 버튼은 행동을 말하고
 * (「발음대본 생성」) 오른쪽 이력은 산출물을 말한다(「내레이션 대본」). 같은
 * 일인지가 안 읽혀서 "지금이 3번 할 타이밍인가 4번 할 타이밍인가" 가 늘 남았다.
 * 이름은 그대로 두고 번호가 둘을 잇는다.
 */
"use strict";

/* 덱 화면의 네 버튼이 몇 번인가.
 * ★ `core/steps.py` 의 STEPS 와 **같은 값이어야 한다.** 번호를 바꾸려면 거기를
 *   고치고 여기도 같이 고칠 것 — 화면이 서버에서 번호를 받아 오는 다른 자리와
 *   달리, 이 넷은 누르기 전이라 받아 올 이력이 없어서 여기 적어 둔다. */
export const DECK = {bgm: 4, script: 5, speech: 6, bake: 7, video: 8};

/* 번호 배지 하나. 버튼에도 이력 줄에도 **같은 모양**으로 붙는다 — 모양이 다르면
   같은 번호인지 눈이 못 잇는다. 그게 배지를 만든 이유의 전부다. */
export function stepBadge(n, title) {
  const i = document.createElement("i");
  i.className = "stepn";
  i.textContent = String(n);
  if (title) i.title = title;
  return i;
}
