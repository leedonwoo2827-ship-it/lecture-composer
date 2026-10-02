/* 매뉴얼에 넣을 화면 캡처.
 *
 * ★ **누르지 않는다.** 화면 이동과 탭 클릭만 한다 — 굽기 단추를 잘못 누르면
 *   돈이 나가거나 몇 분짜리 잡이 돈다.
 * ★ 파일 이름은 매뉴얼의 캡처 자리 이름과 같다. 사람이 보고 갈아 끼울 수 있게.
 *
 *   node tools/shots.mjs [프로젝트탭이름]      기본 "제20장"
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const BASE = "http://localhost:5178";
const OUT = join(process.cwd(), "docs", "그림");
const TAB = process.argv[2] || "제20장";

mkdirSync(OUT, { recursive: true });

const shots = [];
const note = (f, t) => { shots.push(`${f}  ${t}`); console.log(`  ${f}  ${t}`); };

const page = await (await chromium.launch()).newPage({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});

let shut = async () => {};
const go = async (hash) => {
  await page.goto(`${BASE}/#/${hash}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1400);
  await shut();
};

const shot = async (name, title, sel) => {
  const t = sel ? page.locator(sel).first() : page;
  try {
    await t.screenshot({ path: join(OUT, `${name}.png`) });
    note(`${name}.png`, title);
  } catch (e) {
    console.log(`  ✗ ${name}  ${String(e.message).slice(0, 70)}`);
  }
};

// ── 프로젝트 고르기 ────────────────────────────────────────────────────────
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
/* ★ 뜬 패널을 먼저 닫는다 — 위층 스크림이 클릭을 통째로 먹는다. */
shut = async () => {
  for (let i = 0; i < 4; i++) {
    if (!(await page.locator("#panel-layer .panel-scrim").count())) return;
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
  }
};
await shut();
const tab = page.getByText(TAB, { exact: true }).first();
if (await tab.count()) {
  await tab.click({ timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(1500);
}
console.log(`프로젝트: ${TAB}`);

// ── 걸음마다 한 장 ────────────────────────────────────────────────────────
await go("html");
await shot("01-원고html", "1 · 원고 HTML 넣기");

await go("outline");
await shot("02-목차", "2 · 목차 — 순서·제목 확정");

await go("deck");
await shot("05-덱-단추줄", "덱 상단 단추 지도", ".page-head");
await shot("05b-덱-전체", "덱 — 전체 보기");
await shot("06-번호탭", "덱 — 장 번호 탭", ".numstrip");

/* 장별 화면 — **번호 탭만** 누른다. 굽는 단추는 건드리지 않는다. */
const num = page.locator('.num-chip[data-no="2"]').first();
if (await num.count()) {
  await num.click({ timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(3000);
  await shot("07-장별화면", "7.2 · 장별로 듣기 — 한 판");
  const g = page.locator(".focus-bar").first();
  if (await g.count()) await shot("07b-음성줄", "7.2 · 음성 줄 단추", ".focus-bar");
  const sb = page.locator(".sb").first();
  if (await sb.count()) {
    await sb.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(600);
    await shot("08-스토리보드", "7.3 · 스토리보드", ".sb");
  }
  const need = page.locator(".sb-need").first();
  if (await need.count()) await shot("08b-지정기안내", "7.3 · 지정기 안내 줄", ".sb-need");
} else {
  console.log("  ✗ 번호 탭을 못 찾았습니다");
}

await go("mp4");
await shot("09-영상렌더링", "7 · 영상 렌더링");

await go("motion");
await shot("10-모션", "8 · 모션 전체 굽기");

console.log(`\n${shots.length}장 → docs/그림/`);
await page.context().browser().close();
