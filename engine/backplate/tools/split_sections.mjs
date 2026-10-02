/* 참고 자료(이론 요약 HTML)를 **찍지 않고 오려내어** 슬라이드 재료로 만든다.
 *
 * `tools/capture_sections.mjs` 의 쌍둥이다. 나누는 자리는 **완전히 같고**(h3 하나당
 * 한 장, h3 가 없는 h2 는 h2 자체), 그 자리에서 화면을 찍는 대신 그 구간의 **HTML 을
 * 그대로 오려 온다.** 결과는 납작한 그림이 아니라 살아 있는 글이라, 줄 하나씩
 * 시간에 맞춰 나타나게 할 수 있고 나중에 그 줄을 영상으로 갈아끼울 수도 있다.
 *
 *     node tools/split_sections.mjs _context/_newcontext/1summary_planning.html \
 *          --out _new-context/1과목2.html
 *
 * ★ 나가는 것은 **파일 하나뿐이다.** 장 목록·줄 목록·등장 시각(예전의 manifest.json)
 *   은 그 파일 안 `<script type="application/json" id="manifest">` 에 같이 들어간다.
 *   원본 옆에 부속 파일이 줄줄이 붙으면 어느 게 사람이 여는 것인지 흐려진다 —
 *   **사람이 여는 것과 기계가 읽는 것이 같은 파일 하나**여야 한다.
 *
 * ★ 들어오는 폴더(`_context/_newcontext`)와 나가는 폴더(`_new-context`)는 이름이
 *   붙임표 하나 차이다. 헷갈리기 쉬우니 경로를 늘 눈으로 확인할 것.
 *
 * ── 비율을 지키는 법 (이게 이 도구의 핵심이다) ────────────────────────────
 * 지금 캡처가 화면에 어떻게 앉는지 실측하면:
 *
 *     원본 문서를 960px 뷰포트에서 렌더 → body 의 테두리 상자는 **944px**
 *       (UA 기본값 `body{margin:8px}` 이 좌우로 8px 씩 먹는다)
 *     그 944px 을 deviceScaleFactor 2 로 찍어 **1888px** 짜리 PNG
 *     그 PNG 를 `.s-shots .m-shots{width:1536px}` 상자에 넣어 1920 프레임에 얹는다
 *     → 실효 배율 K = 1536 / 944 = 1.62712
 *
 * 그래서 살아 있는 HTML 도 **944px 폭으로 배치한 뒤 1.62712 배로 확대**하면
 * 픽셀이 캡처와 그대로 겹친다. 줄바꿈 위치도, 표 칸 너비도, SVG 크기도 같다 —
 * **배치가 캡처와 같은 폭에서 일어나기 때문이다.**
 *
 * `zoom` 이나 글자 크기 키우기로는 안 된다. `zoom` 은 1536px 폭에서 배치를 다시
 * 해서 줄바꿈이 달라지고, 글자 크기를 키우면 원본이 섞어 쓰는 `rem`(문서 기준)과
 * `em`(부모 기준)이 서로 다른 비율로 자라 비례가 깨진다. `transform: scale()` 만이
 * **배치 결과를 기하학적으로 확대**한다 — 그림을 늘린 것과 정의상 같다.
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, basename, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const src = argv.find((a) => !a.startsWith("--"));
if (!src) {
  console.error("사용법: node tools/split_sections.mjs <html경로> [--out 파일] "
    + "[--start 2] [--width 960] [--height N] [--cps 5.7]");
  process.exit(2);
}

const SRC = resolve(src);
const STEM = basename(SRC).replace(/\.html?$/i, "");
const OUT = resolve(opt("--out", join(dirname(SRC), `${STEM}2.html`)));

const WIDTH = parseInt(opt("--width", "960"), 10);
const START = parseInt(opt("--start", "2"), 10);   // 1번은 표지
// ★ 캡처가 한 장에 담던 높이. 여기서도 같은 자리에서 끊어야 장 수가 어긋나지 않는다.
const HEIGHT = parseInt(opt("--height", String(Math.round(WIDTH * 0.625))), 10);
// 초당 글자 수 — 등장 시각 자동 배분에 쓴다. 실제 음성이 붙으면 그쪽이 이긴다.
const CPS = parseFloat(opt("--cps", "5.7"));
// 제목 단계 — 앞이 묶음(섹션), 뒤가 장(슬라이드). 원고 꼴이 다르면 바꾼다.
const LEVELS = opt("--levels", "h2,h3").split(",").map((s) => s.trim());
// body 테두리 상자 폭 = 뷰포트 − UA `body{margin:8px}` 좌우
const SRC_W = WIDTH - 16;                          // 944
const BOX_W = 1536;                                // .s-shots .m-shots 와 같은 값
const K = BOX_W / SRC_W;                           // 1.62712…

mkdirSync(dirname(OUT), { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: WIDTH, height: 1200 });
await page.goto(pathToFileURL(SRC).href, { waitUntil: "load" });

// ★ 문서 실제 높이만큼 뷰포트를 키운다 — 스크롤 없이 좌표가 페이지 좌표와 맞아야
//   "한 화면 높이(600px)에서 끊는다" 는 판단이 캡처와 같은 결과를 낸다.
const fullHeight = await page.evaluate(() => document.documentElement.scrollHeight);
await page.setViewportSize({ width: WIDTH, height: Math.ceil(fullHeight) + 40 });

/* ── 원본 <style> 을 `.doc` 밑으로 가둔다 ────────────────────────────────
 * 원본은 `body{}`, `*{max-width:100%}` 같은 전역 규칙을 쓴다. 그대로 덱 페이지에
 * 부으면 덱 CSS 가 통째로 무너진다. 그렇다고 shadow DOM 에 넣으면 재생기·프레임
 * 촬영·인쇄가 전부 `.hb` 를 못 찾는다(평범한 querySelectorAll 로 닿아야 한다).
 *
 * ★ 정규식으로 셀렉터를 자르지 않는다. 브라우저의 **진짜 CSS 파서(CSSOM)** 를
 *   그대로 빌려 쓴다 — 의존성도 없고 따옴표·괄호에서 틀릴 일도 없다.
 */
const style = await page.evaluate(() => {
  const scope = (sel) => {
    const s = sel.trim();
    if (!s) return s;
    // body/html 규칙은 `.doc` 그 자체가 물려받는다 — `.doc` 이 body 를 대신한다.
    if (/^(html|body)\b/i.test(s)) {
      const rest = s.replace(/^(html|body)/i, "");
      return ".doc" + rest;
    }
    if (s === "*") return ".doc *";
    return ".doc " + s;
  };
  const walk = (rules) => [...rules].map((r) => {
    if (r.type === CSSRule.STYLE_RULE) {
      return r.selectorText.split(",").map(scope).join(",")
        + "{" + r.style.cssText + "}";
    }
    if (r.type === CSSRule.MEDIA_RULE) {
      return "@media " + r.conditionText + "{" + walk(r.cssRules) + "}";
    }
    return r.cssText;                      // @font-face · @keyframes 는 그대로
  }).join("\n");
  return [...document.styleSheets]
    .map((ss) => { try { return walk(ss.cssRules); } catch { return ""; } })
    .join("\n");
});

/* 표지 두 줄 — `h1` 과 **그 바로 아래 `<p>`**.
   ★ 원고가 `h1` 밑에 책 이름을 한 줄 넣어 보낸다("표지 부제로 쓰시면 됩니다").
     예전엔 그걸 버리고 **파일 이름**(`01-19`)을 부제 자리에 넣었다 — 그래서
     완성본과 유튜브 글에 제목이 `19_원고` 로 나갔다(2026-08-15 지적). */
const head = await page.evaluate(() => {
  const clean = (el) => {
    const c = el.cloneNode(true);
    c.querySelectorAll(".q").forEach((n) => n.remove());
    return c.textContent.trim();
  };
  const el = document.querySelector("h1");
  if (!el) return { title: "", sub: "" };
  const nx = el.nextElementSibling;
  return {
    title: clean(el),
    sub: nx && nx.tagName === "P" ? clean(nx).slice(0, 80) : "",
  };
});
const h1 = head.title || STEM;
const subTitle = head.sub;

/* ── 나누기 ────────────────────────────────────────────────────────────
 * 경계 판단은 `capture_sections.mjs:80-121` 과 **글자 그대로 같다.** 규칙이 둘로
 * 갈라지면 어느 장은 그림이고 어느 장은 글인 덱이 나온다.
 */
const sections = await page.evaluate(({ HEIGHT, START, LEVELS }) => {
  /* ★ 규칙 하나로 줄인다: **보이는 것만 가져온다.**
   *
   * 원고가 늘 이 이론 요약 꼴은 아니다(2026-08-14 지시). 어떤 문서는 `.q` 배지로,
   * 어떤 문서는 `<details>` 로, 어떤 문서는 그냥 `hidden` 으로 접어 둔다. 그 관습을
   * 하나씩 따라다니며 예외를 붙이면 새 문서마다 이 파일이 늘어난다.
   *
   * 대신 문서 종류에 안 기대는 기준을 쓴다 — **지금 화면에 안 보이면 안 가져온다.**
   * 발표 영상에는 누를 손이 없어서 접힌 것을 펼 수단 자체가 없다. 그러니 "접혀
   * 있다" 는 곧 "영원히 안 보인다" 는 뜻이고, 그런 글자가 조각에 남으면 화면에는
   * 없는데 `textContent` 에는 잡혀 제목·글자 수·등장 시각을 전부 오염시킨다
   * (실제로 그런 사고가 있었다 — 2026-08-13 `.q` 배지가 제목 뒤에 딸려 나왔다).
   *
   * 그래서 clone 하기 전에 **원본에서** 안 보이는 것을 표시해 둔다. computed style
   * 은 배치가 끝난 살아 있는 문서에서만 읽을 수 있어서, clone 뒤에는 못 잰다. */
  const HIDE = "data-x-hide";
  for (const n of document.body.querySelectorAll("*")) {
    const cs = getComputedStyle(n);
    if (cs.display === "none" || cs.visibility === "hidden"
        || (cs.opacity === "0" && cs.position !== "absolute")) {
      n.setAttribute(HIDE, "1");
    }
  }
  // 접힌 `<details>` 는 `display:none` 이 아니라 브라우저가 따로 감춘다 — 따로 본다.
  for (const d of document.querySelectorAll("details:not([open])")) {
    for (const c of d.children) {
      if (c.tagName !== "SUMMARY") c.setAttribute(HIDE, "1");
    }
  }
  // 눌러야 뭔가 일어나는 것들 — 영상에서는 누를 수 없으므로 껍데기다.
  const CLICKY = "label,button,input,select,textarea,summary,[role=button]";

  const cleanTitle = (el) => {
    const clone = el.cloneNode(true);
    clone.querySelectorAll(`[${HIDE}],${CLICKY}`).forEach((n) => n.remove());
    return clone.textContent.replace(/\s+/g, " ").trim();
  };

  /* 오려 온 조각을 씻는다. 그림은 실행될 수 없지만 HTML 은 실행된다 —
     이 조각은 덱 페이지와 `dist/` 배포본에 그대로 들어가므로 여기서 막는다. */
  const sanitize = (root) => {
    root.querySelectorAll("script,style,link,iframe,object,embed,form").forEach((n) => n.remove());
    root.querySelectorAll(`[${HIDE}]`).forEach((n) => n.remove());
    root.querySelectorAll(CLICKY).forEach((n) => n.remove());
    root.querySelectorAll("*").forEach((n) => {
      n.removeAttribute(HIDE);
      for (const a of [...n.attributes]) {
        if (/^on/i.test(a.name)) n.removeAttribute(a.name);
        if (/^(href|src|xlink:href)$/i.test(a.name)
            && /^\s*javascript:/i.test(a.value)) n.removeAttribute(a.name);
      }
    });
  };

  /* 줄 단위로 표시한다 — 한 번에 나타나는 최소 덩어리.
     ★ `<div>` 로 감싸지 않고 **있는 요소에 표시만 붙인다.** 감싸면 문단 여백
       상쇄(margin collapsing)가 깨지고 원본 CSS 의 `ul > li`·`th, td` 같은
       자손 셀렉터가 어긋난다 — 둘 다 배치를 바꾸므로 "같은 비율" 이 깨진다. */
  const markBlocks = (host, no) => {
    const out = [];
    let idx = 0;
    const push = (el, tag) => {
      el.classList.add("hb");
      el.setAttribute("data-b", `${no}.${idx}`);
      const text = (el.textContent || "").replace(/\s+/g, " ").trim();
      out.push({
        b: `${no}.${idx}`, tag,
        chars: text.replace(/\s/g, "").length,
        text: (tag === "svg" ? "[그림] " : "") + text.slice(0, 80),
      });
      idx += 1;
    };
    for (const node of [...host.children]) {
      const t = node.tagName.toLowerCase();
      if (t === "ul" || t === "ol") {
        const lis = [...node.children].filter((c) => c.tagName === "LI");
        if (lis.length) { lis.forEach((li) => push(li, "li")); continue; }
      }
      if (t === "table") {
        const rows = [...node.querySelectorAll("tr")];
        if (rows.length) { rows.forEach((tr) => push(tr, "tr")); continue; }
      }
      push(node, t);
    }
    return out;
  };

  /* 제목 단계 — 기본은 h2(묶음) · h3(장). 문서에 h3 가 아예 없으면 h2 가 곧 장이
     되므로 아래 규칙이 저절로 맞는다. 다른 꼴의 원고를 위해 `--levels` 로 바꿀 수
     있다(예: 표지가 h2 인 문서면 `--levels h3,h4`). */
  const OUTER = LEVELS[0].toUpperCase();     // 묶음 — 덱의 섹션
  const INNER = LEVELS[1].toUpperCase();     // 장 — 슬라이드 한 판
  const INNER_N = parseInt(INNER.slice(1), 10);
  // 몸통을 어디서 끊나 — 이 단계 이상(더 굵은) 제목을 만나면 끊는다.
  const STOP = new RegExp(`^H[1-${INNER_N}]$`);

  const heads = Array.from(document.querySelectorAll(`${OUTER}, ${INNER}`));
  const items = [];
  let group = "";                      // 그 장이 속한 묶음 — 덱의 "섹션" 이 된다
  let no = START;

  for (let i = 0; i < heads.length; i++) {
    const h = heads[i];
    if (h.tagName === OUTER) {
      group = cleanTitle(h);
      // 다음 묶음 전까지 장 제목이 하나라도 있으면 이 묶음은 장이 아니다
      // (그 안의 장들이 진짜 장이다). 하나도 없으면 이 묶음 자체가 장이 된다.
      let hasChild = false;
      for (let j = i + 1; j < heads.length; j++) {
        if (heads[j].tagName === OUTER) break;
        hasChild = true;
        break;
      }
      if (hasChild) continue;
    }

    // 몸통 — 이 제목 다음 형제부터 다음 제목 직전까지.
    // ★ 제목 자체는 담지 않는다. 덱이 그 제목을 h2 로 화면 위에 따로 띄우므로
    //   몸통에도 넣으면 같은 글자가 두 번 보인다(캡처도 같은 이유로 제목 아래부터
    //   잘랐다). 덤으로 `.q` 근거 배지가 제목에만 있어 저절로 빠진다.
    const host = document.createElement("div");
    host.className = "doc";
    const top = h.getBoundingClientRect().bottom;
    // ★ `nextElementSibling` 은 **그 제목의 부모 안에서** 다음 형제를 준다. 그래서
    //   본문이 `<body>` 바로 밑이든 `<div class="wrap">` 안이든 똑같이 돈다 —
    //   제목과 본문이 서로 형제이기만 하면 된다. 본문이 제목보다 더 깊이 들어가
    //   있는 문서만 안 된다(그때는 빈 장으로 잡혀 아래 경고에 걸린다).
    let el = h.nextElementSibling;
    let overflow = false;
    let n = 0;
    while (el && !STOP.test(el.tagName)) {
      host.appendChild(el.cloneNode(true));
      n += 1;
      // 캡처는 600px 에서 **요소 중간이라도** 잘랐다. DOM 은 요소 경계에서만
      // 끊을 수 있으니 걸친 요소는 **버리지 않고 담고** 넘쳤다고 적어 둔다 —
      // 화면 쪽에서 그만큼 배율을 낮춰 넣으므로 잘려 나가는 내용이 없다.
      if (el.getBoundingClientRect().bottom - top >= HEIGHT) { overflow = true; break; }
      el = el.nextElementSibling;
    }
    sanitize(host);
    const blocks = markBlocks(host, no);
    /* 근거 문번 횟수 — **이 원고 갈래만의 관습**이다(`.q > b` 에 문항 수).
       있으면 제목 옆에 숫자 하나로 달고, 없는 문서면 그냥 안 단다. 위 살균이 이미
       `.q` 를 통째로 걷어냈으므로(안 보이는 것 + 누르는 것), 여기서 숫자를 따로
       빼 오지 않으면 그 정보는 사라진다. 긴 목록은 애초에 안 가져오니 영상에서
       늘어설 방법이 없다(2026-08-14 지시). */
    const qn = h.querySelector(".q > b");
    /* 원고가 제목에 붙여 보낸 이름표 셋 — **여기서 안 집으면 영영 사라진다.**
       제목은 몸통에 안 담기므로(위 주석) 속성도 같이 안 담긴다.
         data-id   안 바뀌는 장 이름표(`sam19-03`). 그림 프롬프트를 번호가 아니라
                   여기에 매단다 — 앞에 장이 끼어들어도 그림이 안 어긋난다
         data-say  그 장에서 말할 문장. 화면 문구가 아니라 화면에 안 적힌 연결이다
         data-img  그 장 그림의 영어 지시문. 있으면 조립하지 않고 그대로 쓴다
         data-read 소리 나는 대로 적은 발음 대본. 숫자·약어가 이미 풀려 있다.
                   있으면 이것이 TTS 입력이 되고, `data-say` 는 자막으로 남는다 */
    items.push({
      no, title: cleanTitle(h), group: h.tagName === "H2" ? "" : group,
      q: qn ? parseInt(qn.textContent.trim(), 10) || 0 : 0,
      did: h.getAttribute("data-id") || "",
      say: h.getAttribute("data-say") || "",
      img: h.getAttribute("data-img") || "",
      read: h.getAttribute("data-read") || "",
      html: host.innerHTML, blocks, overflow, empty: n === 0,
    });
    no += 1;
  }
  return items;
}, { HEIGHT, START, LEVELS });

await browser.close();

/* ── 이 원고가 이 방식에 맞는가 ────────────────────────────────────────
 * 원고가 늘 같은 꼴로 오지 않으므로, 안 맞으면 **조용히 이상한 결과를 내놓지 말고
 * 여기서 멈춘다.** 빈 파일 90장을 만들어 놓고 나중에 화면에서 발견하는 것보다,
 * 지금 무엇을 고치면 되는지 알려 주는 편이 싸다. */
if (!sections.length) {
  console.error(`제목을 못 찾았습니다 — ${LEVELS[0]}/${LEVELS[1]} 이 하나도 없습니다.`);
  console.error(`  이 원고의 제목 단계가 다르면 --levels 로 알려 주세요 (예: --levels h1,h2)`);
  process.exit(3);
}
const emptyN = sections.filter((s) => s.empty).length;
if (emptyN === sections.length) {
  console.error(`장 ${sections.length}개가 전부 몸통이 비었습니다.`);
  console.error(`  제목과 본문이 서로 형제가 아닌 것 같습니다 — 본문이 제목보다 깊이`);
  console.error(`  들어가 있으면(예: 제목만 밖에 있고 본문은 <div> 안) 못 가져옵니다.`);
  process.exit(3);
}

/* ── 등장 시각 자동 배분 ────────────────────────────────────────────────
 * 대본·음성이 아직 없는 단계다. 글자 수를 초당 글자 수로 나눈 값을 쌓아 리듬만
 * 잡아 둔다 — 파이프라인에 태우면(B단계) 그 장의 실제 음성 길이로 다시 계산되고,
 * 사람이 손으로 적은 값은 그 위에서 이긴다.
 */
/* ★ 그림 줄은 글자 수로 재지 않는다 — `core/htmldoc.py` 의 `auto_ats()` 와 **짝**이다.
 *   `<svg>` 의 textContent 는 라벨을 다 세므로 책 원고에서는 그림 한 줄이 글줄보다
 *   글자가 많다(실측: 그림 중앙값 81~93자 · 글줄 34자). 비례로 나누면 그림 하나가
 *   그 장 시간의 40% 를 가져간다. 그림은 읽는 게 아니라 보는 것이라 글자 수와
 *   상관이 없으니, 고정 시간으로 뺀다. 두 값을 양쪽에서 같게 유지할 것. */
const MIN_STEP = 0.8;
const FIG_TAGS = new Set(["svg", "figure", "img", "picture"]);
const FIG_SEC = 3.0;
for (const s of sections) {
  let t = 0;
  for (const b of s.blocks) {
    b.at = Math.round(t * 10) / 10;
    t += FIG_TAGS.has(b.tag) ? FIG_SEC : Math.max(MIN_STEP, b.chars / CPS);
  }
  s.sec = Math.round(t * 10) / 10;
}

const esc = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/* ── 화면 CSS ──────────────────────────────────────────────────────────
 * `render/slides.py` 의 `.s-shots` 배치를 1920×1080 설계 해상도로 그대로 옮긴 것.
 * 이 파일을 그냥 브라우저에서 열면 덱에서 보게 될 것과 같은 자리·같은 크기로
 * 보여야 한다 — 그게 이 단계의 합격 기준이다.
 */
const CSS = `
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;height:100%;background:#2b2825;overflow:hidden}
body{font-family:"Pretendard","Malgun Gothic","맑은 고딕",system-ui,sans-serif;
  color:#2e2b27;line-height:1.62;word-break:keep-all;-webkit-font-smoothing:antialiased}
/* 설계 해상도 — 영상이 찍히는 크기(render_frames.mjs)와 같다.
   창 크기에 맞춰 통째로 줄이기만 한다. 안을 반응형으로 만들지 않는다. */
#frame{position:absolute;left:50%;top:50%;width:1920px;height:1080px;
  transform-origin:center;background:#fff;overflow:hidden}
/* .s-shots{padding:2vh 7vw 2vh 0.5vw} 를 1920×1080 실수로 푼 값 */
#stage{position:absolute;inset:0;padding:21.6px 134.4px 21.6px 9.6px}
.hs{display:none}
.hs.on{display:block}
.hs-t{margin:0 0 6px;font-size:34px;font-weight:700;letter-spacing:-.025em;
  line-height:1.28;color:#1f1d1a}
.hs-t::after{content:"";display:block;width:52px;height:3px;margin-top:6px;background:#9a4d33}
/* 근거 문번 횟수 — 그 개념이 몇 문항에서 나왔나. 숫자 하나뿐이라 늘어날 수 없다. */
.qb{display:inline-block;margin-left:10px;padding:2px 10px;border-radius:999px;
  background:#e8f4f2;border:1px solid #bfe0da;color:#0f766e;
  font-size:.5em;font-weight:600;vertical-align:middle;line-height:1.6}
.m-html{position:relative;margin:0;background:#fff;width:${BOX_W}px;max-width:none;
  overflow:hidden}
/* ★ 여기가 비율의 전부다 — 944px 폭으로 배치하고 통째로 확대한다.
   transform 은 배치 높이에 기여하지 않으므로(화면엔 보이는데 좌표를 재면 0이다)
   바깥 상자 높이를 아래 스크립트가 직접 재어 넣는다. */
.doc{width:${SRC_W}px;transform-origin:top left;box-sizing:border-box}
/* ★ 원본 \`body\` 의 **좌우** 여백(4px)은 남기고 **위아래**(8px·40px)는 뺀다.
   그 여백은 문서의 처음과 끝에 두라고 준 것인데, 조각은 문서 중간이다. 그대로
   두면 장마다 위 8px·아래 40px 이 덤으로 붙어 캡처보다 48px 씩 길어진다
   (실측: 캡처 507px vs 조각 538px). 좌우는 반대로 **꼭 남겨야** 한다 —
   캡처의 944px 안에 그 4px 이 들어 있어서, 빼면 본문 폭이 936→944 로 벌어져
   줄바꿈 위치가 달라진다. */
.doc{padding-top:5px;padding-bottom:0}
/* ★ 첫 줄·끝 줄의 바깥 여백을 없애 **모든 장이 같은 높이에서 시작**하게 한다.
   캡처는 제목 아래 6px 에서 잘랐는데, 그 6px 안에 첫 요소의 위 여백이 얼마나
   들어오는지가 요소 종류마다 달랐다(표 11.2px → 5.2px 들어옴, 문단 6.4px →
   0.4px). 그래서 장을 넘길 때마다 본문이 5px 씩 위아래로 흔들렸다. 여기서는
   여백을 걷고 위 padding 5px 로 못박아 늘 같은 자리에서 시작한다. */
.doc > *:first-child{margin-top:0}
.doc > *:last-child{margin-bottom:0}
/* 조각 안은 원본의 상자 계산(content-box)을 그대로 쓴다 — 위 전역 reset 이
   border-box 로 바꿔 버리면 표 칸 여백만큼 배치가 어긋난다. */
.doc *{box-sizing:content-box}
/* 줄 등장 — display 가 아니라 opacity 다. display 로 감추면 줄이 뜰 때마다
   아래 내용이 밀려 글이 튄다. 자리는 처음부터 잡아 두고 보이기만 바꾼다. */
.doc .hb{opacity:0;transition:opacity .34s}
.doc .hb.on{opacity:1}
@media print{.doc .hb{opacity:1}}

/* 표지·마무리 */
.hs-cover{display:none;padding-top:120px}
.hs.on.hs-cover{display:block}
.hs-cover h1{margin:0 0 20px;font-size:54px;font-weight:700;letter-spacing:-.03em;
  line-height:1.18;color:#1f1d1a}
.hs-cover p{margin:0;font-size:19px;color:#6b6660}

/* ★ 재생·자막 단추는 **우상단**이다(2026-08-14 지시). 우하단은 아바타 자리다. */
#ui{position:absolute;top:18px;right:18px;z-index:8;display:grid;gap:8px;justify-items:end}
#ui button{padding:6px 14px;border:0;border-radius:99px;background:rgb(31 29 26/.62);
  color:#fff;font-family:inherit;font-size:12px;font-weight:700;cursor:pointer}
#ui button:hover{background:rgb(31 29 26/.86)}
#ui button.on{background:#9a4d33}
#hud{font-size:11px;color:#948e86;font-variant-numeric:tabular-nums}
/* 아바타 자리 — 지금은 비워만 둔다. 나중에 말하는 사람이 여기 들어온다. */
#av{position:absolute;right:0;bottom:0;width:20%;aspect-ratio:3/4;z-index:7;
  pointer-events:none}
#bar{position:absolute;left:0;right:0;bottom:0;height:3px;display:flex;gap:1px;
  background:#efebe4;z-index:8}
#bar i{flex:1;background:#e0dad1;cursor:pointer;transition:background .15s}
#bar i.done{background:#9a4d33}
`;

/* ── 혼자 서는 재생기 ──────────────────────────────────────────────────
 * 확인용이다. 덱에 붙일 때(B단계)는 `render/slides.py` 의 재생기가 이 일을 맡고
 * 시계는 그 장의 음성(`audio.currentTime`)이 된다. 여기서는 음성이 없으므로
 * 장을 연 시각을 0 으로 잡는 자체 시계를 쓴다.
 */
const JS = `
const K=${K};
const secs=[...document.querySelectorAll('.hs')];
const frame=document.getElementById('frame');
const bar=document.getElementById('bar'),hud=document.getElementById('hud'),
      pz=document.getElementById('pz');
let i=0,auto=false,timers=[],hold=null;

function fit(){
  const z=Math.min(innerWidth/1920,innerHeight/1080);
  frame.style.transform='translate(-50%,-50%) scale('+z+')';
}
addEventListener('resize',()=>{fit();fitDoc(secs[i]);});
fit();

/* ★ transform 은 배치 높이에 기여하지 않는다 — 상자 높이를 직접 재어 넣는다.
   안 넣으면 화면엔 멀쩡히 보이는데 좌표를 재면 height:0 이다. */
function fitDoc(sec){
  if(!sec)return;
  const box=sec.querySelector('.m-html'),doc=box&&box.firstElementChild;
  if(!doc)return;
  doc.style.transform='none';
  box.style.height='auto';
  const nat=doc.scrollHeight;                 // 944px 폭에서의 실제 높이
  // #frame 이 offsetParent 라 offsetTop 이 곧 설계 좌표(1920×1080)다.
  const room=1080-box.offsetTop-21.6;
  // 기본은 캡처와 같은 배율. 한 화면을 넘칠 때만 줄인다 — 자르지 않는다.
  const k=Math.min(K, room/Math.max(nat,1));
  doc.style.transform='scale('+k+')';
  box.style.height=Math.ceil(nat*k)+'px';
  box.dataset.k=k.toFixed(4);
}

function clear(){timers.forEach(clearTimeout);timers=[];clearTimeout(hold);}

function go(n){
  clear();
  i=Math.max(0,Math.min(secs.length-1,n));
  secs.forEach((s,k)=>s.classList.toggle('on',k===i));
  [...bar.children].forEach((t,k)=>t.classList.toggle('done',k<=i));
  const sec=secs[i];
  fitDoc(sec);
  const bs=[...sec.querySelectorAll('.hb')];
  bs.forEach(b=>b.classList.remove('on'));
  if(!auto){bs.forEach(b=>b.classList.add('on'));}
  else{
    bs.forEach(b=>{
      const at=parseFloat(b.dataset.at||0);
      if(at<=0)b.classList.add('on');
      else timers.push(setTimeout(()=>b.classList.add('on'),at*1000));
    });
    const last=bs.length?parseFloat(bs[bs.length-1].dataset.at||0):0;
    if(i<secs.length-1) hold=setTimeout(()=>go(i+1),(last+2.4)*1000);
  }
  hud.textContent=(i+1)+' / '+secs.length+'  ·  '+(sec.dataset.title||'');
  location.replace('#'+(i+1));
}

secs.forEach((s,k)=>{const b=document.createElement('i');b.onclick=()=>go(k);bar.appendChild(b);});
pz.onclick=()=>{auto=!auto;pz.textContent=auto?'❚❚ 멈춤':'▶ 자동 재생';
  pz.classList.toggle('on',auto);go(i);};
addEventListener('keydown',e=>{
  if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();go(i+1);}
  if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();go(i-1);}
  if(e.key==='Home')go(0);
  if(e.key==='End')go(secs.length-1);
  if(e.key==='a'||e.key==='A')pz.click();
});
go(Math.max(0,(parseInt(location.hash.slice(1))||1)-1));
`;

// ── 파일 조립 ──────────────────────────────────────────────────────────
const body = [];
body.push(
  `<section class="hs hs-cover" data-no="1" data-kind="cover" data-title="${esc(h1)}">`
  + `<h1>${esc(h1)}</h1>`
  + (subTitle ? `<p>${esc(subTitle)}</p>` : "") + `</section>`);

for (const s of sections) {
  body.push(
    `<section class="hs" data-no="${s.no}" data-kind="section"`
    + ` data-group="${esc(s.group)}" data-title="${esc(s.title)}"`
    + ` data-sec="${s.sec}"${s.q ? ` data-q="${s.q}"` : ""}`
    // 원고가 준 이름표 셋 — **있을 때만** 붙인다(`data-q` 와 같은 규칙).
    // 기계는 아래 `#manifest` 를 읽는다. 여기 두는 것은 이 파일을 열어 본 사람이
    // 장 하나를 짚어 「이게 어느 이름표였나」를 바로 볼 수 있게 하기 위해서다.
    + `${s.did ? ` data-id="${esc(s.did)}"` : ""}`
    + `${s.say ? ` data-say="${esc(s.say)}"` : ""}`
    + `${s.img ? ` data-img="${esc(s.img)}"` : ""}`
    + `${s.read ? ` data-read="${esc(s.read)}"` : ""}`
    + `${s.overflow ? " data-overflow=\"1\"" : ""}>`
    + `<h2 class="hs-t">${esc(s.title)}`
    + `${s.q ? `<i class="qb">${s.q}</i>` : ""}</h2>`
    + `<figure class="m-html"><div class="doc">${s.html}</div></figure>`
    + `</section>`);
}
const lastNo = (sections.length ? sections[sections.length - 1].no : 1) + 1;
body.push(
  `<section class="hs hs-cover" data-no="${lastNo}" data-kind="closing" data-title="마무리">`
  + `<h1>마무리</h1><p>${esc(h1)}</p></section>`);

// 등장 시각을 각 줄에 심는다 — 손으로 고칠 때 이 값이 바뀐다.
let out = body.join("\n");
for (const s of sections) {
  for (const b of s.blocks) {
    out = out.replace(`data-b="${b.b}"`, `data-b="${b.b}" data-at="${b.at}"`);
  }
}

/* ── 장·줄 목록 ────────────────────────────────────────────────────────
 * 예전에는 이걸 옆에 `*.manifest.json` 으로 따로 뒀는데, 파일 하나짜리 산출물에
 * 부속 파일이 붙으면 어느 게 진짜인지 흐려진다. **같은 파일 안에** 넣는다 —
 * 사람은 열어서 보고, 기계는 `#manifest` 를 읽으면 된다.
 * ★ 스코핑한 CSS 는 여기 넣지 않는다. 이미 `<style id="src-css">` 에 그대로
 *   있으므로, 넣으면 4KB 짜리가 파일 안에 두 벌이 된다. */
const manifest = {
  source: SRC,
  html: basename(OUT),
  deck_title: h1,
  deck_subtitle: subTitle,
  geometry: { src_width: SRC_W, box_width: BOX_W, k: Math.round(K * 100000) / 100000,
              cap_height: HEIGHT },
  slides: [
    { no: 1, kind: "cover", title: h1, media_kind: "text", sec: null, blocks: [] },
    ...sections.map((s) => ({
      no: s.no, kind: "section", title: s.title, section: s.group,
      // ★ 이름은 snake_case 다 — 원장(`core/ledger.py`)이 `data_id` 를 키로 쓰고,
      //   여기서 이름이 갈리면 옮겨 담는 코드가 한 겹 더 생긴다.
      //   원고가 안 보내면 빈 문자열이다(문제집 원고에는 셋 다 없다).
      data_id: s.did, say: s.say, img: s.img, read: s.read,
      media_kind: "html", sec: s.no, overflow: s.overflow, empty: s.empty,
      est_sec: s.sec,
      blocks: s.blocks.map((b) => ({ b: b.b, tag: b.tag, chars: b.chars,
                                     at: b.at, text: b.text })),
    })),
    { no: lastNo, kind: "closing", title: "마무리", media_kind: "text",
      sec: null, blocks: [] },
  ],
};
// `</script>` 가 본문 글자에 섞여 들어와도 태그가 일찍 닫히지 않게 `<` 를 이스케이프
const manifestJson = JSON.stringify(manifest, null, 2).replace(/</g, "\\u003c");

const html = `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(h1)}</title>
<!-- ★ 원본 문서의 스타일 — 전부 \`.doc\` 밑으로 가둬 두었다(전역 규칙이
     덱 CSS 를 무너뜨리지 않게). 손대지 말 것: 여기가 비율의 근거다. -->
<style id="src-css">
${style}
</style>
<style id="deck-css">${CSS}</style>
</head>
<body>
<div id="frame">
  <div id="stage">
${out}
  </div>
  <div id="ui">
    <button id="pz" type="button">▶ 자동 재생</button>
    <div id="hud"></div>
  </div>
  <div id="av"></div>
  <div id="bar"></div>
</div>
<!-- 장·줄 목록 — 파이프라인(s2c)이 이걸 읽어 목차를 세운다. 사람이 볼 것은 위 화면이다. -->
<script type="application/json" id="manifest">
${manifestJson}
</script>
<script>${JS}</script>
</body>
</html>
`;

writeFileSync(OUT, html, "utf-8");

const nb = sections.reduce((a, s) => a + s.blocks.length, 0);
const over = sections.filter((s) => s.overflow).length;
const empty = sections.filter((s) => s.empty).length;
for (const s of sections) {
  console.log(`[${String(s.no).padStart(3, "0")}] ${s.title}  `
    + `(줄 ${s.blocks.length} · ${s.sec}초${s.overflow ? " · 넘침" : ""}`
    + `${s.empty ? " · 몸통없음" : ""})`);
}
console.log(`\n완료 — 표지 1 + 본문 ${sections.length} + 마무리 1 = ${sections.length + 2}장, `
  + `줄 ${nb}개${over ? ` · 넘친 장 ${over}` : ""}${empty ? ` · 빈 장 ${empty}` : ""}`);
console.log(`  → ${OUT}   (장·줄 목록은 이 파일 안 #manifest 에 들어 있다)`);
console.log(`  배율 K = ${BOX_W} / ${SRC_W} = ${K.toFixed(5)}`);
