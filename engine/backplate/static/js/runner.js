/* 단계 실행 — 누른 버튼이 **시계가 되어 돈다.**
 *
 * 이 앱은 누르면 몇 분씩 가는 단계가 많다. 그동안 화면이 한 글자도 안 바뀌면
 * 사람은 멈춘 것으로 읽고, 콘솔을 열어 보거나 다시 누른다(같은 단계가 두 번
 * 돌면 돈이 두 배로 나간다). 그래서 규칙 하나를 둔다:
 *
 *   **실행하는 버튼은 예외 없이 (지금 무엇을 · 몇 분 몇 초) 를 보여 준다.**
 *
 * 초가 올라가는 것이 "살아 있다" 의 유일한 증거다. 무엇을 하는지는 서버가
 * 보내 주는 step 을 그대로 쓴다 — 레포를 읽는 단계는 파일 이름까지 올라온다
 * ("adm/exam_qna_form.php 읽는 중 · 1:23").
 *
 * 한 곳에 모아 둔 이유: 덱·현황판·시작 화면이 저마다 같은 루프를 따로 갖고
 * 있었고, 고칠 때마다 한 군데씩 빠뜨렸다.
 */
"use strict";

import { api, toast } from "./util.js";
import { state } from "./store.js";

const POLL = 1500;

/** 흐른 시간 — 0:07 · 1:23 */
export function clock(t0) {
  const s = Math.max(0, Math.floor((Date.now() - t0) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * 단계를 순서대로 돌린다. 앞이 실패하면 거기서 멈춘다 — 뒤가 앞을 못 지어낸다.
 *
 * @param {string[]} keys   ["s10-tts", "s11-audio", …]
 * @param {object}   o
 *   o.label   글자를 바꿔 줄 노드(보통 버튼 안의 span)
 *   o.btn     돌아가는 동안 잠글 버튼 — 시계(진행)를 보여 줄 그 버튼
 *   o.group   돌아가는 동안 **같이** 잠글 다른 버튼들(배열) — 시계는 안 보여
 *             주고 그냥 잠그기만 한다. 한 단계가 도는 동안 다른 단계 버튼을
 *             눌러 겹쳐 돌리면 같은 산출물에 두 잡이 동시에 손대 꼬인다
 *             (2026-08-13).
 *   o.names   {스테이지키: "사람이 읽는 이름"}
 *   o.onStep  (text, at) => void — at = {completed, total, step, sec}
 *                                버튼 말고 다른 곳에도 뿌리고 싶을 때
 *   o.onLog   (lines) => void — 서버가 쌓은 로그 전문. 흐르는 것을 보여 줄 때
 *   o.onDone  (result) => void — result = 마지막 잡이 남긴 값(없으면 null)
 * @returns {Promise<boolean>} 끝까지 갔으면 true
 */
export async function runSteps(keys, o = {}) {
  if (!state.projectId || !keys.length) return false;
  return runJobs(keys.map((k) => ({
    url: `/api/projects/${state.projectId}/stages/${k}/run`,
    name: (o.names || {})[k] || k,
  })), o);
}

/**
 * 잡 하나를 돌린다 — **스테이지가 아닌 것도.**
 *
 * ★ 뽑아낸 이유: 모션 리마스터는 레지스트리 스테이지가 아니라서
 *   `/stages/{k}/run` 이 아닌 제 창구를 쓴다(`pipeline/s13_motion.py` 머리말).
 *   그렇다고 이 폴링 루프를 한 벌 더 쓰면, 「버튼이 시계가 되어 돈다」는 규칙을
 *   고칠 때 또 한 군데를 빠뜨린다. 위 runSteps 도 이제 이걸 부른다.
 *
 * @param {string} url  POST 하면 {job_id} 를 주는 주소
 */
export function runJob(url, o = {}) {
  return runJobs([{ url, name: o.name || "" }], o);
}

async function runJobs(jobs, o = {}) {
  if (!state.projectId || !jobs.length) return false;
  const { label, btn, group = [], onStep, onLog, onDone } = o;
  let seen = 0;                        // 새로 늘어난 줄만 넘긴다
  /* 마지막 잡이 남긴 값. ★ 반환값으로 내보내지 않고 `onDone` 으로만 준다 —
     여기 돌아오는 것이 boolean 이라고 믿는 화면이 이미 여럿이다. */
  let last = null;
  const was = label ? label.textContent : "";
  const t0 = Date.now();
  let step = jobs[0].name || "실행";
  /* ★ 몇 개 중 몇 개인지는 서버만 안다(프레임 6개 중 3개, 장 40개 중 12개).
   * 알 수 없는 단계도 있다 — 그때는 total 이 0 이고, 화면은 **흐르는 막대**로
   * 바꿔 그린다. "모르니까 아무것도 안 그린다" 가 제일 나쁘다. */
  let at = { completed: 0, total: 0 };

  const paint = () => {
    const sec = Math.max(0, Math.floor((Date.now() - t0) / 1000));
    const s = `${step} · ${clock(t0)}`;
    if (label) label.textContent = s;
    if (onStep) onStep(s, { ...at, step, sec });
  };
  if (btn) btn.disabled = true;
  for (const b of group) if (b) b.disabled = true;
  const iv = setInterval(paint, 1000);
  paint();

  try {
    for (const k of jobs) {
      step = k.name || step;
      seen = 0;
      at = { completed: 0, total: 0 };
      paint();
      const r = await api(k.url, { method: "POST" });
      for (;;) {
        await new Promise((z) => setTimeout(z, POLL));
        const j = await api(`/api/jobs/${r.job_id}`);
        // 서버가 지금 무엇을 하는지 — 이게 있으면 그것을 보여 준다
        if (j.step) step = j.step;
        at = { completed: Number(j.completed) || 0, total: Number(j.total) || 0 };
        /* ★ 로그를 그대로 흘린다. 한 줄짜리 요약만 바꿔서는 "돌고 있다" 가
         * 잘 안 읽힌다 — 줄이 **쌓이는** 것이 사람에게는 진행이다. */
        if (onLog && Array.isArray(j.log) && j.log.length > seen) {
          onLog(j.log.slice(seen));
          seen = j.log.length;
        }
        if (!j.running) {
          if (j.error) throw new Error(k.name ? `${k.name}: ${j.error}` : j.error);
          last = j.result || null;
          break;
        }
      }
    }
    if (onDone) onDone(last);
    return true;
  } catch (e) {
    toast(String(e.message || e), "err");
    return false;
  } finally {
    clearInterval(iv);
    if (label) label.textContent = was;
    if (btn) btn.disabled = false;
    for (const b of group) if (b) b.disabled = false;
  }
}
