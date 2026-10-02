/* 참고 자료(이론 요약 HTML)를 **화면 캡처로 잘라** 슬라이드 재료로 만든다.
 *
 * 이 프로젝트의 참고 자료는 화면 녹화가 아니라 정적 HTML 이다 — 찍을 "화면"이
 * 없다. 대신 그 HTML 자체가 이미 항목별로 정리돼 있다(h3 = "1.1 지도학습과…").
 * 그 경계를 그대로 슬라이드 경계로 써서, h3 하나당 캡처 한 장을 뽑는다.
 * (h2 는 더 커서 한 장에 여러 화면 분량이 들어가 버린다 — 2026-08-13 지시로
 * h3 단위로 내렸다.) h3 가 하나도 없는 h2(그 자체가 최하위 항목)는 h2 를
 * 대신 캡처한다.
 *
 * 1번 장은 표지(제목만, 캡처 없음) — 나머지는 전부 캡처 한 장씩.
 *
 * ★ 캡처에는 그 항목의 **제목을 넣지 않는다.** 제목은 덱 쪽 h2 로 화면 위에
 *   이미 따로 떠 있다(render/slides.py) — 캡처에도 찍으면 같은 글자가 화면에
 *   두 번 보인다. 그래서 그 제목 요소의 **아래쪽**부터 잘라, 본문·표·그림만
 *   담는다.
 *
 * 캡처 높이는 **한 화면 높이로 고정한다**(2026-08-13 지시) — 항목마다 내용
 * 길이가 달라 다음 항목 시작 전까지 다 담으면 슬라이드마다 세로 길이가
 * 들쭉날쭉해진다. 내용이 그 높이보다 짧으면 아래가 흰 배경으로 남아도
 * 상관없다(길게 늘여 억지로 채우지 않는다) — 화면 쪽(.m-shots)도 그 남는
 * 자리를 페이지 배경과 같은 색으로 두고 이미지는 위에 붙여, 슬라이드마다
 * 남는 자리 크기만 다를 뿐 이미지 시작 위치는 항상 같다.
 *
 *     node tools/capture_sections.mjs <html경로> [--out 폴더] [--start 2]
 *                                      [--width 960] [--scale 2] [--height N]
 *
 * 결과: <out>/002.png … 과 <out>/manifest.json(제목·번호·파일명 목록 —
 * draft/import 에 붙일 원고 JSON의 뼈대로 그대로 쓸 수 있다).
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, basename, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const src = argv.find((a) => !a.startsWith("--"));
if (!src) {
  console.error("사용법: node tools/capture_sections.mjs <html경로> [--out 폴더] "
    + "[--start 2] [--width 960] [--scale 2] [--height N]");
  process.exit(2);
}

const OUT = resolve(opt("--out",
  join(dirname(src), "captures", basename(src).replace(/\.html?$/i, ""))));
const WIDTH = parseInt(opt("--width", "960"), 10);
const SCALE = parseFloat(opt("--scale", "2"));
const START = parseInt(opt("--start", "2"), 10); // 1번은 표지라 캡처는 2번부터
// ★ render/slides.py 의 .m-shots 박스 비율(padding-top:62.5%)과 맞춘다 —
//   캡처 높이가 그 박스와 같으면 화면에서 letterbox(여백) 자체가 안 생긴다.
const HEIGHT = parseInt(opt("--height", String(Math.round(WIDTH * 0.625))), 10);

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: SCALE });
await page.setViewportSize({ width: WIDTH, height: 1200 });
await page.goto(pathToFileURL(resolve(src)).href, { waitUntil: "load" });

// ★ 문서 실제 높이만큼 뷰포트를 키운다 — 그래야 스크롤 없이 클립 좌표가
//   페이지 좌표와 그대로 맞는다(스크롤 중이면 clip 이 어긋난다).
const fullHeight = await page.evaluate(() => document.documentElement.scrollHeight);
await page.setViewportSize({ width: WIDTH, height: Math.ceil(fullHeight) + 40 });

// ★ 제목에서 근거 문번 배지(.q — 체크박스로 접어 둔 "모의 N회 M번…")를 뺀다.
//   `textContent` 는 CSS `display:none` 이어도 감춘 글자를 그대로 읽어 온다 —
//   접힌 배지가 제목 뒤에 그대로 딸려 나오는 사고가 실제로 있었다(2026-08-13).
const h1 = (await page.evaluate(() => {
  const cleanTitle = (el) => {
    const clone = el.cloneNode(true);
    clone.querySelectorAll(".q").forEach((n) => n.remove());
    return clone.textContent.trim();
  };
  const el = document.querySelector("h1");
  return el ? cleanTitle(el) : "";
})) || basename(src);

// 캡처 항목 경계 — h3 하나당 한 장(h3 가 없는 h2 는 h2 자체를 대신 캡처).
// top 은 그 제목의 위치, bottom 은 고정 높이 또는 다음 항목 시작 전 중 더 짧은 쪽.
const sections = await page.evaluate(() => {
  const cleanTitle = (el) => {
    const clone = el.cloneNode(true);
    clone.querySelectorAll(".q").forEach((n) => n.remove());
    return clone.textContent.trim();
  };
  const wrap = document.querySelector(".wrap") || document.body;
  const wrapRect = wrap.getBoundingClientRect();
  const heads = Array.from(document.querySelectorAll("h2, h3"));
  const items = [];
  for (let i = 0; i < heads.length; i++) {
    const h = heads[i];
    if (h.tagName === "H2") {
      // 다음 h2 전까지 h3 가 하나라도 있으면, 이 h2 는 캡처하지 않는다
      // (h3 들이 그 안의 실제 항목이다).
      let hasChild = false;
      for (let j = i + 1; j < heads.length; j++) {
        if (heads[j].tagName === "H2") break;
        hasChild = true;
        break;
      }
      if (hasChild) continue;
    }
    const next = heads[i + 1];
    items.push({
      title: cleanTitle(h),
      // ★ 제목 자체는 찍지 않는다 — 그 제목은 덱의 h2 로 이미 화면 위쪽에
      //   따로 떠 있다(render/slides.py `_slide`). 캡처에도 넣으면 같은
      //   글자가 화면에 두 번 보인다(2026-08-13 지적). 그래서 이 제목의
      //   **아래쪽**부터 자른다 — 본문·표·그림만 캡처에 담는다.
      bodyTop: h.getBoundingClientRect().bottom + window.scrollY,
      nextTop: next ? next.getBoundingClientRect().top + window.scrollY : null,
    });
  }
  return items.map((s) => ({
    title: s.title,
    x: wrapRect.left + window.scrollX,
    y: s.bodyTop,
    width: wrapRect.width,
    nextTop: s.nextTop,
  }));
});

const manifest = {
  source: resolve(src), deck_title: h1,
  slides: [{ no: 1, kind: "cover", title: h1, media_kind: "text", image: null }],
};

let no = START;
const TOP_GAP = 6; // 제목 아래 살짝 띄우고 시작 — 본문 첫 줄이 상단에 붙지 않게
const GAP = 10; // 다음 항목이 있으면 그 제목 글자가 안 걸리게 그 앞에서 멈춘다
for (const s of sections) {
  const top = Math.max(0, Math.round(s.y + TOP_GAP));
  const boundaryBottom = s.nextTop != null
    ? Math.round(s.nextTop - GAP)
    : Math.round(top + HEIGHT);
  // 고정 높이가 원칙 — 다음 항목이 그보다 가까이 있으면 그 앞에서만 멈춘다.
  const bottom = Math.min(top + HEIGHT, Math.max(top, boundaryBottom));
  const clip = {
    x: Math.max(0, Math.round(s.x)),
    y: top,
    width: Math.round(s.width),
    height: Math.max(1, bottom - top),
  };
  const name = `${String(no).padStart(3, "0")}.png`;
  await page.screenshot({ path: join(OUT, name), clip });
  manifest.slides.push({ no, kind: "section", title: s.title, media_kind: "text_image", image: name });
  console.log(`[${no}] ${s.title}  (${clip.width}x${clip.height})`);
  no += 1;
}

writeFileSync(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2), "utf-8");
await browser.close();
console.log(`\n완료 — 표지 1장 + 캡처 ${manifest.slides.length - 1}장 → ${OUT}`);
