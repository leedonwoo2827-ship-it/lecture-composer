/* 공용 유틸 — DOM · API · 토스트 · SSE · 마크다운 */
"use strict";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** el("div", "card", "본문") — className·textContent 는 선택. */
export function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export function icon(name, size = 16) {
  const s = el("span");
  s.dataset.icon = name;
  s.dataset.iconSize = String(size);
  return s;
}

/* ── API ────────────────────────────────────────────
 * 오류를 조용히 삼키지 않는다. 로컬 앱이라 콘솔을 잘 안 보므로 메시지를 던져
 * 호출자가 토스트로 띄우게 한다. */
export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* 본문이 JSON 이 아니면 상태 코드로 */ }
    // status 를 실어 보낸다 — 호출자가 '정말 없어졌다(404)' 와 '일시적 실패' 를
    // 구별해야 한다. 구별하지 않으면 요청이 한 번 끊긴 것만으로 선택을 날린다.
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

let toastTimer = null;
export function toast(msg, kind = "") {
  const box = $("#toast");
  if (!box) return;
  box.textContent = msg;
  box.className = "toast" + (kind ? " " + kind : "");
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, kind === "err" ? 6500 : 3200);
}

/* ── SSE (POST) ─────────────────────────────────────
 * EventSource 는 GET 만 되므로 fetch 스트림을 직접 파싱한다. 반환한 abort() 를
 * 부르면 요청만 끊긴다 — 서버 워커는 끝까지 돌아 파일 저장이 완료된다.
 * 화면을 떠나도 생성이 유실되지 않는 건 그 덕이다. */
export function sse(path, body, handlers = {}) {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        // 이벤트는 빈 줄로 끝난다. 마지막 조각은 다음 청크와 이어붙인다.
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const raw of parts) {
          let ev = "message", data = "";
          for (const line of raw.split("\n")) {
            if (line.startsWith("event:")) ev = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          let payload;
          try { payload = JSON.parse(data); } catch { payload = data; }
          handlers[ev]?.(payload);
        }
      }
      handlers.close?.();
    } catch (e) {
      if (e.name !== "AbortError") handlers.error?.({ message: e.message });
      handlers.close?.();
    }
  })();
  return { abort: () => ctrl.abort() };
}

/* ── 마크다운 (표·목록·인용까지. 라이브러리 없이) ─────
 * 스트리밍 중 매 델타마다 다시 그리므로 가볍게 유지한다. */
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

export function md(src) {
  const lines = String(src || "").split("\n");
  const out = [];
  let i = 0, listTag = null;

  const closeList = () => { if (listTag) { out.push(`</${listTag}>`); listTag = null; } };

  while (i < lines.length) {
    const ln = lines[i];

    // 표 — | a | b | 다음 줄이 구분선
    if (/^\s*\|/.test(ln) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      closeList();
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(ln);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push("<table><thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>");
      for (const r of rows) out.push("<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
      out.push("</tbody></table>");
      continue;
    }

    const h = ln.match(/^(#{1,4})\s+(.*)$/);
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(ln)) { closeList(); out.push("<hr>"); i++; continue; }

    const bq = ln.match(/^>\s?(.*)$/);
    if (bq) { closeList(); out.push(`<blockquote>${inline(bq[1])}</blockquote>`); i++; continue; }

    const ul = ln.match(/^\s*[-*+]\s+(.*)$/);
    const ol = ln.match(/^\s*(\d+)[.)]\s+(.*)$/);
    if (ul || ol) {
      const want = ul ? "ul" : "ol";
      if (listTag !== want) { closeList(); out.push(`<${want}>`); listTag = want; }
      out.push(`<li>${inline(ul ? ul[1] : ol[2])}</li>`);
      i++; continue;
    }

    if (!ln.trim()) { closeList(); i++; continue; }
    closeList();
    out.push(`<p>${inline(ln)}</p>`);
    i++;
  }
  closeList();
  return out.join("\n");
}

export const fmtBytes = (n) =>
  n >= 1048576 ? (n / 1048576).toFixed(1) + "MB" : Math.max(1, Math.round(n / 1024)) + "KB";

export function debounce(fn, ms = 400) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* 미리보기 iframe 을 **넓게 그린 뒤 축소한다.**
 *
 * ★ iframe 을 그냥 좁히면 그 안의 렌더러가 좁은 화면용 배치로 갈아탄다 —
 *   그림이 글 아래로 내려가고, 편집 화면에서 보는 면과 발표에서 나가는 면이
 *   달라진다. 그러면 "이 면이 이렇게 잘리는가" 를 여기서 판단할 수 없다.
 *
 * 그래서 항상 1280 폭으로 그리고 transform 으로 줄인다. 글자는 작아서 안 읽히지만
 * **배치는 실물 그대로**다. 읽을 글은 어차피 오른쪽 편집 칸에 크게 있다.
 *
 * 스스로 정리한다 — 장을 넘길 때마다 stage 가 새로 만들어지므로, 떨어져 나간
 * 것을 보고 있으면 관찰자가 쌓인다.
 */
export function fitFrame(stage, frame, base = 1280) {
  const H = Math.round(base * 9 / 16);
  frame.style.width = base + "px";
  frame.style.height = H + "px";
  frame.style.transformOrigin = "top left";

  // ★ 만들어 놓고 나중에 붙이는 자리가 있다 — 처음부터 "안 붙어 있으니 그만"
  //   하면 관찰자가 시작도 못 하고 죽는다. **한 번 붙은 뒤에** 떨어진 것만 접는다.
  let attached = false;
  const apply = () => {
    if (!stage.isConnected) { if (attached) ro.disconnect(); return; }
    attached = true;
    const cs = getComputedStyle(stage);
    const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    const w = stage.clientWidth - pad;
    if (w <= 0) return;
    const z = w / base;
    frame.style.transform = `scale(${z})`;
    stage.style.height = Math.round(H * z + parseFloat(cs.paddingTop)
                                    + parseFloat(cs.paddingBottom)) + "px";
  };
  const ro = new ResizeObserver(apply);
  ro.observe(stage);
  apply();
  return () => ro.disconnect();
}
