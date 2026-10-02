/* 산출물 화면 공통부 — 스트리밍 본문 · 수정 · 정렬 점검 · 직접 편집 · 다운로드.
 *
 * 강의계획서/교재/슬라이드 개요가 전부 "긴 마크다운 하나"라 같은 부품을 쓴다.
 *
 * ★ 생성은 화면을 떠나도 계속된다. sse() 의 abort 는 브라우저 쪽 연결만 끊고
 *   서버 워커는 끝까지 돌아 파일로 저장한다. 그래서 스트림 중 패널을 열거나
 *   다른 주차를 봐도 산출물을 잃지 않는다.
 */
"use strict";

import { el, icon, api, toast, md, sse } from "./util.js";
import { hydrateIcons } from "./icons.js";

/** 진행 표시줄 — 상태 문장 + 스피너 + (선택) 진행 바 */
export function statusLine() {
  const box = el("div", "status-line");
  box.hidden = true;
  const sp = el("span", "spinner");
  const txt = el("span", null, "");
  box.append(sp, txt);
  const bar = el("div", "bar");
  bar.style.flex = "0 0 120px";
  bar.hidden = true;
  const fill = el("i");
  bar.appendChild(fill);
  box.appendChild(bar);
  return {
    node: box,
    show(msg) { box.hidden = false; txt.textContent = msg || "작업 중…"; },
    progress(v) {
      if (v == null) { bar.hidden = true; return; }
      bar.hidden = false;
      fill.style.width = Math.round(v * 100) + "%";
    },
    hide() { box.hidden = true; bar.hidden = true; },
  };
}

/**
 * 스트리밍 본문 영역.
 *   render(md)         저장된 마크다운을 그린다
 *   start()/append()   스트림 시작·델타
 *   finish()           커서 제거
 */
export function docBody(placeholder) {
  const box = el("div", "doc");
  let buf = "";
  const draw = () => { box.innerHTML = md(buf); };
  const api_ = {
    node: box,
    render(text) {
      buf = text || "";
      box.classList.remove("streaming");
      if (buf.trim()) draw();
      else box.innerHTML = `<div class="empty">${placeholder}</div>`;
    },
    start() { buf = ""; box.classList.add("streaming"); box.innerHTML = ""; },
    append(delta) {
      buf += delta;
      draw();
      // 스트림 중에는 아래를 따라간다(사용자가 위로 올렸으면 방해하지 않는다)
      if (window.scrollY + window.innerHeight > document.body.scrollHeight - 300) {
        window.scrollTo({ top: document.body.scrollHeight });
      }
    },
    finish() { box.classList.remove("streaming"); },
    get text() { return buf; },
  };
  return api_;
}

/** 다운로드 버튼 하나 */
export function dlBtn(label, href, iconName = "download") {
  const a = el("a", "btn sm");
  a.href = href;
  a.append(icon(iconName, 13), el("span", null, label));
  return a;
}

/**
 * 수정 · 정렬 점검 · 직접 편집 묶음.
 * onRefine(text) / onCheck() / onSave(text) 를 준다.
 */
export function editControls({ getText, onRefine, onCheck, onSave, busy }) {
  const box = el("div", "card");
  box.style.marginTop = "16px";

  const row = el("div", "btn-row");
  const req = el("input");
  req.type = "text";
  req.placeholder = "수정 요청 — 예: 사례를 더 추가해줘 / 분량을 줄여줘";
  req.className = "grow";
  const rb = el("button", "btn primary");
  rb.type = "button";
  rb.append(icon("wand", 14), el("span", null, "수정 요청"));
  rb.addEventListener("click", () => {
    const v = req.value.trim();
    if (!v) { toast("수정 요청을 입력하세요."); return; }
    req.value = "";
    onRefine(v);
  });
  req.addEventListener("keydown", (e) => { if (e.key === "Enter") rb.click(); });
  const cb = el("button", "btn");
  cb.type = "button";
  cb.append(icon("target", 14), el("span", null, "정렬 점검"));
  cb.addEventListener("click", onCheck);
  row.append(req, rb, cb);
  box.appendChild(row);

  const eb = el("button", "btn sm");
  eb.type = "button";
  eb.style.marginTop = "12px";
  eb.append(icon("edit", 13), el("span", null, "직접 편집 (마크다운)"));
  const wrap = el("div");
  wrap.hidden = true;
  wrap.style.marginTop = "12px";
  const ta = el("textarea");
  ta.style.minHeight = "360px";
  ta.style.fontFamily = "ui-monospace, Consolas, monospace";
  ta.style.fontSize = "12.5px";
  const sb = el("button", "btn primary sm");
  sb.type = "button";
  sb.style.marginTop = "10px";
  sb.append(icon("check", 13), el("span", null, "편집 저장"));
  sb.addEventListener("click", () => onSave(ta.value));
  wrap.append(ta, sb);
  eb.addEventListener("click", () => {
    wrap.hidden = !wrap.hidden;
    if (!wrap.hidden) ta.value = getText();
  });
  box.append(eb, wrap);

  return {
    node: box,
    setBusy(on) { [req, rb, cb, eb, sb].forEach((n) => { n.disabled = on; }); },
  };
}

/**
 * 생성 실행 헬퍼 — SSE 를 열고 status/delta/done/error 를 배선한다.
 * 반환: { abort }
 */
export function runStream(path, body, { status, body: doc, onDone, setBusy }) {
  setBusy?.(true);
  status.show("시작하는 중…");
  doc.start();
  let failed = false;
  const h = sse(path, body, {
    status: (d) => { status.show(d.message); status.progress(d.progress ?? null); },
    delta: (d) => doc.append(typeof d === "string" ? d : String(d ?? "")),
    error: (d) => {
      failed = true;
      status.hide();
      toast(d.message || "생성에 실패했습니다.", "err");
    },
    done: (d) => { status.hide(); onDone?.(d); },
    close: () => {
      status.hide();
      doc.finish();
      setBusy?.(false);
      if (failed) doc.render(doc.text);
    },
  });
  return h;
}
