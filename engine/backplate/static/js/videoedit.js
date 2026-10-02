/* 무음 영상 편집기 — 덱의 한 장 보기와 전용 편집 화면이 **같은 코드**를 쓴다.
 *
 * 화면 녹화는 그대로 못 쓴다. 앞뒤가 늘어지고, 중간에 로딩을 기다리는 구간이 있고,
 * 어디는 뿌옇다. 그래서 세 가지만 준다 — **자르기 · 배속 · 들어내기.**
 *
 *   구간   in/out. 앞뒤 군더더기를 뗀다
 *   배속   1x · 1.5x · 2x · 3x. 기다리는 구간에 쓴다
 *   삭제   중간을 통째로 건너뛴다. 여러 개 가능
 *
 * ★ **다시 인코딩하지 않는다.** 재생기가 currentTime 을 조작해 건너뛴다.
 *   고치는 즉시 확인되고, 미리보기와 최종 산출물이 같은 코드로 돈다. 진짜로 잘린
 *   파일이 필요하면 큐시트에 구간이 적혀 나가므로 편집 프로그램에서 재현된다.
 *
 * ★ 편집의 목표는 예쁘게 만드는 게 아니라 **대본 길이에 맞추는 것**이다. 그래서
 *   "편집 후 몇 초"와 "대본이 몇 초"를 항상 나란히 보여 준다.
 */
"use strict";

import { el, toast } from "./util.js";

export const SPEEDS = [1, 1.5, 2, 3];

export function clipOf(s) {
  const dur = Number(s.video_duration) || 0;
  const c = {start: 0, end: dur, speed: 1, cuts: [], ...(s.clip || {})};
  if (!c.end || c.end > dur) c.end = dur;
  if (!Array.isArray(c.cuts)) c.cuts = [];
  return c;
}

/** 편집 뒤 실제 재생 길이(초). 대본 길이와 맞춰야 하는 숫자다. */
export function outSec(clip) {
  const cut = clip.cuts.reduce((n, [a, b]) =>
    n + Math.max(0, Math.min(b, clip.end) - Math.max(a, clip.start)), 0);
  return Math.max(0, clip.end - clip.start - cut) / (clip.speed || 1);
}

export function needSec(s) {
  return (s.audio || {}).sec || (s.narration || {}).est_sec || 0;
}

/**
 * @param s        슬라이드 (video_id · video_duration · clip · narration · audio)
 * @param opts.src 영상 URL
 * @param opts.onChange(clip)  바뀔 때마다 호출 — 저장은 부르는 쪽이 한다
 * @param opts.big  전용 화면용 큰 배치
 */
export function videoEditor(s, opts) {
  const {src, onChange, big = false} = opts;
  const dur = Number(s.video_duration) || 0;
  const clip = clipOf(s);
  let cutFrom = null;

  const box = el("div", "ved" + (big ? " ved-big" : ""));

  const v = el("video", "ved-v");
  v.preload = "metadata";
  v.muted = true;            // 무음 영상이다 — 소리는 내레이션 트랙이 낸다
  v.playsInline = true;
  v.src = src;
  box.appendChild(v);

  const pct = (t) => (dur ? Math.max(0, Math.min(100, (t / dur) * 100)) : 0);

  /* ★ 쓰는 법을 화면이 말해 준다. 버튼만 있으면 어디를 누르는지 모른다(실제로 그랬다).
   *   ① 막대를 눌러 그 시각으로 이동  ② 여기부터/여기까지로 구간을 정함
   *   ③ 삭제 시작→삭제 끝으로 중간을 들어냄 */
  const howto = el("div", "ved-howto");
  howto.append(
    el("b", null, "쓰는 법"),
    el("span", null, "① 아래 막대를 눌러 위치 이동 (또는 ← → 0.2초, Shift 1초)"),
    el("span", null, "② 그 위치에서 여기부터 / 여기까지 — 앞뒤가 잘립니다"),
    el("span", null, "③ 삭제 시작 → 삭제 끝 — 중간이 통째로 건너뛰어집니다"));
  box.appendChild(howto);

  const tl = el("div", "ved-tl");
  const keep = el("i", "ved-keep");
  const head = el("i", "ved-head");
  tl.append(keep, head);
  tl.onclick = (e) => {
    const r = tl.getBoundingClientRect();
    v.currentTime = ((e.clientX - r.left) / r.width) * dur;
  };
  box.appendChild(tl);

  // 재생 중에 구간·삭제·배속을 실제로 적용한다 — 눈으로 봐야 고칠 수 있다
  v.addEventListener("loadedmetadata", () => { v.playbackRate = clip.speed; draw(); });
  v.addEventListener("timeupdate", () => {
    if (v.currentTime < clip.start - 0.05) v.currentTime = clip.start;
    // ★ 끝나면 **마지막 프레임에서 선다.** 되감지 않는다 — 영상이 음성보다
    //   짧으면 남은 말이 끝날 때까지 그 화면이 서 있어야 한다.
    if (v.currentTime >= clip.end) {
      v.pause();
      v.currentTime = Math.max(clip.start, clip.end - 0.05);
      return;
    }
    for (const [a, b] of clip.cuts) {
      if (v.currentTime >= a && v.currentTime < b) { v.currentTime = b; break; }
    }
    head.style.left = pct(v.currentTime) + "%";
    if (now) now.textContent = v.currentTime.toFixed(1) + "s";
  });

  const commit = () => { onChange && onChange(clip); draw(); };

  const bar = el("div", "ved-bar");
  const mk = (label, title, fn, cls) => {
    const b = el("button", "ved-btn" + (cls ? " " + cls : ""));
    b.type = "button"; b.textContent = label; b.title = title; b.onclick = fn;
    return b;
  };
  const btnCutStart = mk("삭제 시작", "여기부터 건너뛴다", () => {
    cutFrom = round(v.currentTime); draw();
  }, "cut");
  bar.append(
    mk("여기부터", "현재 위치를 시작점으로 (I)", () => {
      clip.start = round(v.currentTime);
      if (clip.start >= clip.end) clip.end = dur;
      commit();
    }),
    mk("여기까지", "현재 위치를 끝점으로 (O)", () => {
      clip.end = round(v.currentTime);
      if (clip.end <= clip.start) clip.start = 0;
      commit();
    }),
    btnCutStart,
    mk("삭제 끝", "여기까지 건너뛴다", () => {
      if (cutFrom == null) { toast("먼저 '삭제 시작' 을 누르세요"); return; }
      const a = Math.min(cutFrom, v.currentTime), b = Math.max(cutFrom, v.currentTime);
      if (b - a > 0.2) clip.cuts.push([round(a), round(b)]);
      clip.cuts.sort((x, y) => x[0] - y[0]);
      cutFrom = null;
      commit();
    }, "cut"),
    mk("되돌리기", "구간·배속·삭제를 모두 지운다", () => {
      clip.start = 0; clip.end = dur; clip.speed = 1; clip.cuts = [];
      cutFrom = null; commit();
    }, "ghost"),
  );
  box.appendChild(bar);

  const sp = el("div", "ved-speed");
  sp.appendChild(el("span", "ved-lb", "배속"));
  for (const x of SPEEDS) {
    const b = el("button", "ved-sp");
    b.type = "button"; b.textContent = x + "x";
    b.onclick = () => { clip.speed = x; v.playbackRate = x; commit(); };
    sp.appendChild(b);
  }
  const now = el("span", "ved-now", "0.0s");
  sp.appendChild(now);
  box.appendChild(sp);

  // 지금 구간이 몇 초부터 몇 초까지인지 — 숫자가 있어야 손으로 맞출 수 있다
  const span = el("div", "ved-span");
  box.appendChild(span);

  const info = el("div", "ved-info");
  box.appendChild(info);

  function round(t) { return Math.round(t * 10) / 10; }

  function draw() {
    span.textContent = "";
    span.append(el("b", null, `${clip.start.toFixed(1)}s`),
                el("span", null, " 부터 "),
                el("b", null, `${clip.end.toFixed(1)}s`),
                el("span", null, " 까지"),
                el("span", "ved-span-x",
                   clip.cuts.length ? `  ·  중간 ${clip.cuts.length}군데 삭제` : ""));
    keep.style.left = pct(clip.start) + "%";
    keep.style.width = (pct(clip.end) - pct(clip.start)) + "%";
    tl.querySelectorAll(".ved-cut").forEach((n) => n.remove());
    for (const [a, b] of clip.cuts) {
      const c = el("i", "ved-cut");
      c.style.left = pct(a) + "%";
      c.style.width = (pct(b) - pct(a)) + "%";
      c.title = `${a.toFixed(1)}s ~ ${b.toFixed(1)}s 삭제 — 눌러서 취소`;
      c.onclick = (e) => {
        e.stopPropagation();
        clip.cuts = clip.cuts.filter((x) => x[0] !== a || x[1] !== b);
        commit();
      };
      tl.appendChild(c);
    }
    sp.querySelectorAll(".ved-sp").forEach((b, i) =>
      b.classList.toggle("on", SPEEDS[i] === clip.speed));
    btnCutStart.classList.toggle("armed", cutFrom != null);

    const out = outSec(clip);
    const cut = clip.cuts.reduce((n, [a, b]) =>
      n + Math.max(0, Math.min(b, clip.end) - Math.max(a, clip.start)), 0);
    info.textContent = "";
    info.append(el("b", null, `편집 후 ${out.toFixed(1)}초`),
                el("span", "ved-src", ` 원본 ${dur.toFixed(1)}초`
                   + (cut ? ` · 삭제 ${cut.toFixed(1)}초` : "")
                   + (clip.speed !== 1 ? ` · ${clip.speed}배속` : "")));
    const need = needSec(s);
    if (need) {
      const gap = need - out;
      const t = el("span", "ved-gap" + (gap > 0.5 ? " short" : " ok"));
      t.textContent = gap > 0.5
        ? `대본 ${need.toFixed(1)}초 — ${gap.toFixed(1)}초 모자랍니다 (마지막 프레임 정지)`
        : `대본 ${need.toFixed(1)}초 — 영상 안에 들어갑니다`;
      info.appendChild(t);
    }
  }

  // 단축키는 전용 화면에서만 — 덱에서는 ←/→ 가 장 넘김이라 충돌한다
  box.onKey = (e) => {
    if (e.key === " ") { e.preventDefault(); v.paused ? v.play() : v.pause(); }
    if (e.key === "ArrowLeft") { e.preventDefault(); v.currentTime -= e.shiftKey ? 1 : 0.2; }
    if (e.key === "ArrowRight") { e.preventDefault(); v.currentTime += e.shiftKey ? 1 : 0.2; }
    if (e.key === "i" || e.key === "I") { clip.start = round(v.currentTime); commit(); }
    if (e.key === "o" || e.key === "O") { clip.end = round(v.currentTime); commit(); }
  };
  box.video = v;
  draw();
  return box;
}
