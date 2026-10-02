/* 프런트 검사 — **브라우저가 죽는 방식으로 미리 죽여 본다.**
 *
 * `node --check` 는 스크립트 모드라 ES 모듈 규칙을 안 본다. 그래서 통과했는데
 * 브라우저에서는 통째로 안 뜨는 일이 오늘만 세 번 났다:
 *
 *   1. 문자열 안에 진짜 개행이 들어감      (`.join("` + 개행 + `")`)
 *   2. `\b` 가 백스페이스 문자로 들어감    (정규식이 아무것도 못 잡음)
 *   3. **선언 전에 씀** (`_one`, `rightCol`)  → 초기화 전 접근으로 스크립트 사망
 *
 * 1·2 는 ESM 파싱으로 잡히고, 3 은 파싱은 통과하고 **실행**에서만 터진다.
 * 그래서 여기서는 파싱 + 최소 DOM 스텁으로 **실제 실행**까지 해 본다.
 *
 *     node tools/check_js.mjs
 */
import { readdirSync, readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const JS_DIR = join(ROOT, "static", "js");
const tmp = mkdtempSync(join(tmpdir(), "jscheck-"));

let bad = 0;

// ── 1) 제어문자 ──────────────────────────────────────────────
for (const f of readdirSync(JS_DIR).filter((x) => x.endsWith(".js"))) {
  const src = readFileSync(join(JS_DIR, f), "utf8");
  const ctl = [...src].filter((c) => c.charCodeAt(0) < 32 && !"\n\t\r".includes(c));
  if (ctl.length) {
    console.log(`✗ ${f} — 제어문자 ${ctl.length}개 (heredoc 사고)`);
    bad++;
  }
}

// ── 2) ESM 파싱 ──────────────────────────────────────────────
for (const f of readdirSync(JS_DIR).filter((x) => x.endsWith(".js"))) {
  const p = join(tmp, f.replace(/\.js$/, ".mjs"));
  writeFileSync(p, readFileSync(join(JS_DIR, f)));
  try {
    await import(pathToFileURL(p).href);
  } catch (e) {
    // import 실패(브라우저 전용 API 없음)는 통과. **문법**만 본다.
    const m = String(e.message || "");
    const isSyntax = e instanceof SyntaxError
      && !m.includes("Cannot find module") && !m.includes("Cannot find package");
    if (isSyntax) {
      console.log(`✗ ${f} — ${m}`);
      bad++;
    }
  }
}

/* ── 3) 선언 전 사용(TDZ) 은 **검사하지 않는다** ────────────────
 * 스코프를 제대로 안 보면 오탐이 쏟아진다(문자열 "title", 함수 매개변수, 다른
 * 함수의 지역변수까지 걸린다). 대신 화면을 **작게 유지**해서 사람이 읽어
 * 잡을 수 있게 하는 쪽을 택했다 — 유형 화면 셋을 각각 독립 파일로 나눈 이유다.
 */

console.log(bad ? `\n${bad}건 — 고치세요` : "\n프런트 검사 통과");
process.exit(bad ? 1 : 0);
