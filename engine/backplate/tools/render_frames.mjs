/* 덱의 각 장을 정지 화면으로 캡처한다 — 영상 렌더(S12)의 재료.
 *
 * `/preview/{pid}?n={no}` 는 그 장 하나만 시작 문 없이 그려 준다(server.py 의
 * `/preview` 참고) — 편집 화면의 iframe 이 이미 이 자리를 쓰고 있다. 영상은
 * 소리가 따로(오디오 파일을 안다) 필요 없으니 스크린샷만 뜨면 된다.
 *
 *     node tools/render_frames.mjs --pid 1 --out <폴더> [--base http://127.0.0.1:5178]
 *
 * 결과: <out>/001.png … (뺀 장은 건너뛴다)
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };

const PID = opt("--pid");
const OUT = opt("--out");
const BASE = (opt("--base", "http://127.0.0.1:5178")).replace(/\/$/, "");
const WIDTH = parseInt(opt("--width", "1920"), 10);
const HEIGHT = parseInt(opt("--height", "1080"), 10);

if (!PID || !OUT) {
  console.error("사용법: node tools/render_frames.mjs --pid <id> --out <폴더> [--base url]");
  process.exit(2);
}

mkdirSync(OUT, { recursive: true });

const deckRes = await fetch(`${BASE}/api/projects/${PID}/deck`);
if (!deckRes.ok) {
  console.error(`덱을 못 읽었습니다: ${deckRes.status} ${await deckRes.text()}`);
  process.exit(1);
}
const deck = await deckRes.json();
const slides = (deck.slides || []).filter((s) => !s.drop);
if (!slides.length) {
  console.error("장이 없습니다 — 목차부터 확정하세요");
  process.exit(1);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });

/* ★ 한 장이 여러 컷이 된다 — **줄이 뜨는 순간마다 한 장씩.**
 *
 * 정지 화면 한 장으로는 "차례로 나타나는 것" 을 담을 수 없다. 그래서 그 장의
 * 줄 등장 시각(`.m-html` 의 `data-at`)을 읽어, 그 시각마다 화면을 한 번씩 찍는다.
 * 이어 붙일 때 각 컷이 다음 컷 시각까지 머물면 실제 재생과 같은 순서가 된다.
 *
 * ★ 컷마다 페이지를 다시 읽지 않는다. 한 번 읽고 **그 안에서 상태만 바꿔** 찍는다
 *   — 90장 × 4컷이면 360번을 다시 읽어야 하는데, 그것만으로 몇 분이 더 든다.
 */
async function cutTimes(page, sec) {
  const ats = await page.evaluate(() => {
    const box = document.querySelector(".s.on .m-html");
    if (!box) return null;
    try { return JSON.parse(box.dataset.at || "[]"); } catch { return []; }
  });
  if (!ats || !ats.length) return null;          // 원고 장이 아니면 한 컷
  // 같은 초에 여러 줄이 뜨면 컷은 하나다. 0초는 반드시 넣는다.
  const uniq = [...new Set([0, ...ats.map((x) => Math.max(0, +x || 0))])]
    .sort((a, b) => a - b)
    .filter((t) => !sec || t < sec - 0.2);       // 장이 끝난 뒤에 뜨는 컷은 버린다
  return uniq.length > 1 ? uniq : null;
}

const manifest = [];
for (const s of slides) {
  /* ★ `?n=` 은 **원래 번호(`src_no`)** 다 — 조립이 다시 매긴 순번이 아니다
     (render/slides.py 의 `_bySrc` 주석). 뺀 장이 있으면 조립이 1부터 다시
     번호를 매기는데, 그 순번으로 부르면 **뺀 장 수만큼 앞엣 화면이 찍힌다.**
     2026-08-15 실측: 표지를 뺀 덱에서 8번 장 음성 위에 7번 그림이 깔렸다.
     소리는 맞고 그림만 한 장 앞서 보이던 원인이 여기였다. */
  const want = s.src_no || s.no;
  const url = `${BASE}/preview/${PID}?n=${want}&t=${Date.now()}`;
  await page.goto(url, { waitUntil: "load" });
  // 폰트·미디어가 자리 잡을 시간 — 짧게 고정. 페이지 자체가 의존성 0(외부 요청 없음)이라
  // networkidle 을 기다릴 필요가 없다.
  await page.waitForTimeout(400);
  // ★ 한 장만 보는 자리(`?n=`)는 시작 문(#gate)이 없다(render/slides.py 참고) —
  //   그래서 `started` 플래그가 영영 true 가 안 되고, 이미지 확대(.vplay)를
  //   스케줄하는 armShots() 안의 `if(!started)return` 에 걸려 확대가 아예 안
  //   돈다. 재생 상태를 진짜로 흉내 낼 필요는 없으니, 확대 클래스만 직접 얹는다.
  await page.evaluate(() => {
    document.querySelector("section.on")?.classList.add("vplay");
    // ★ `?n=` 화면은 오디오가 없으니 재생 중이 아닌데도 그 장 첫 자막 줄을
    //   미리 띄워 둔다(render/slides.py `go()` — 정지 화면에서 훑어볼 때
    //   쓰라고 넣은 것이다). 그런데 이 스크린샷이 영상(S12)의 프레임 그대로
    //   쓰이니, 그 자막 말풍선이 장 전체 길이만큼 **영상에 구워져 버린다**
    //   (2026-08-13 지적: "번인" — Windows 실시간 캡션이 아니라 이거였다).
    //   실제 재생 중 자막은 덱 화면(오디오 재생 중)에서만 뜨면 되므로, 영상
    //   재료로 찍을 때는 지운다.
    const cc = document.getElementById("cc");
    if (cc) cc.style.display = "none";
    // ★ 이게 진짜 범인이었다(2026-08-14 재확인 — 렌더된 mp4에서 여전히
    //   보임). `#cc`와는 별개로 `.cc-st`(_cc_static, render/slides.py)가
    //   있다 — `body.one`(=`?n=` 모드) 에서는 `subs` 값과 무관하게 **항상**
    //   자막 원문을 화면 하단에 깔아 둔다. "편집 화면 iframe에서 자막을
    //   고쳤는데 화면이 그대로면 저장이 안 된 줄 안다"는 별개 문제를 풀려고
    //   넣은 장치인데, 영상 프레임 캡처도 같은 `?n=` 모드를 타는 바람에 이
    //   장치가 그대로 영상에 구워졌다. `#cc`만 지운 지난 수정으로는 이걸
    //   못 잡았다 — 화면에 없던 게 아니라 이쪽이 진짜 소스였다.
    //   ★ 장마다 하나씩(총 슬라이드 수만큼) DOM에 이미 다 들어 있다 —
    //   `.querySelector`(첫 번째 하나만)로는 지금 보이는 장 것을 못 잡을
    //   때가 많다(엉뚱하게 1번 장 것만 지워짐). 전부 지운다.
    document.querySelectorAll(".cc-st").forEach((el) => { el.style.display = "none"; });
    /* 일단 다 띄워 둔다 — 줄이 없는 장(그림·텍스트)은 이 상태 그대로 한 장 찍고,
       원고 장은 아래에서 컷마다 `toggle` 로 그 시각 상태를 다시 만든다.
       `?n=` 모드가 이미 다 띄우지만(render/slides.py `armHtml` 의 `_one` 갈래),
       그쪽이 바뀌어도 영상이 조용히 반쯤 빈 화면을 굽지 않도록 여기서도 못박는다. */
    document.querySelectorAll(".m-html .hb").forEach((el) => { el.classList.add("on"); });
  });
  // grid-template-columns 전환에 .55s 걸린다 — 최종 배치가 자리 잡을 시간을 준다.
  await page.waitForTimeout(700);

  const pad = String(s.no).padStart(3, "0");
  const sec = (s.audio || {}).sec || 0;
  const times = await cutTimes(page, sec);

  if (!times) {
    // 원고 장이 아니거나 줄이 하나뿐 — 예전처럼 한 장이면 된다
    const name = `${pad}.png`;
    await page.screenshot({ path: join(OUT, name), type: "png" });
    manifest.push({ no: s.no, title: s.title, image: name,
                    cuts: [{ image: name, at: 0 }],
                    audio: (s.audio || {}).file || null, sec });
    console.log(`[${s.no}] ${s.title || ""}`);
    continue;
  }

  const cuts = [];
  for (let k = 0; k < times.length; k++) {
    const t = times[k];
    // 그 시각의 상태로 굳힌다 — `toggle` 이라 앞 컷에서 켠 줄도 정확히 되돌아간다
    await page.evaluate((t) => {
      const box = document.querySelector(".s.on .m-html");
      if (!box) return;
      let ats = [];
      try { ats = JSON.parse(box.dataset.at || "[]"); } catch { /* 없으면 전부 끈다 */ }
      box.querySelectorAll(".hb").forEach((b, i) => {
        b.classList.toggle("on", (+ats[i] || 0) <= t);
      });
    }, t);
    // 줄이 뜨는 애니메이션(.34s)이 끝나야 흐릿하지 않게 찍힌다
    await page.waitForTimeout(420);
    const name = `${pad}-${String(k).padStart(2, "0")}.png`;
    await page.screenshot({ path: join(OUT, name), type: "png" });
    cuts.push({ image: name, at: t });
  }
  manifest.push({ no: s.no, title: s.title, image: cuts[cuts.length - 1].image,
                  cuts, audio: (s.audio || {}).file || null, sec });
  console.log(`[${s.no}] ${s.title || ""}  — 컷 ${cuts.length}`);
}
await browser.close();

writeFileSync(join(OUT, "frames.json"), JSON.stringify(manifest, null, 2), "utf-8");
console.log(`\n완료 — ${manifest.length}장 → ${OUT}`);
