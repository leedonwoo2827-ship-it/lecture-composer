/* 프레임 — **바닥(편집기)**. 추출된 프레임을 보고, 대표 컷(✓)을 고르고, 캡션을 고친다.
 *
 * 여기가 바닥인 이유: 캡션 입력창이 있다. 패널은 Esc·스크림으로 닫히므로
 * 타이핑하던 내용이 날아간다 — 미저장 텍스트는 패널 금지.
 *
 * 실행("다시 뽑기 / 캡션 새로 달기")은 여기가 아니라 떠 있는 창이 맡는다.
 *
 * 손편집은 deck.overrides.json 으로 따로 저장된다. S1/S3 를 다시 돌려도
 * 고쳐 놓은 캡션과 ✓ 는 살아남는다 — 이게 없으면 "좋은 캡션 나올 때까지
 * 주사위 굴리기" 가 된다.
 */
"use strict";

import { el, api, icon, toast, debounce } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";

export const meta = {
  title: "프레임",
  subtitle: "대표 컷을 고르고(✓) 캡션을 다듬습니다. 고친 내용은 다시 돌려도 남습니다",
  actions: () => {
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "실행기 열기"));
    b.onclick = () => navigate("/board");
    return [b];
  },
};

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export async function mount(root) {
  const page = el("div", "page");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let data;
  try {
    data = await api(`/api/projects/${state.projectId}/frames`);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }

  if (!data.items.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 프레임이 없습니다."));
    box.appendChild(el("p", null, "실행기에서 '프레임 추출' 을 돌리세요."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "실행기 열기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  // 손편집 저장 — 타이핑마다 보내지 않고 묶어서 한 번에.
  const pending = { items: {} };
  const flush = debounce(async () => {
    const patch = { items: pending.items };
    pending.items = {};
    try {
      await api(`/api/projects/${state.projectId}/overrides`,
                { method: "POST", body: { patch } });
    } catch (e) { toast("저장 실패: " + e.message, "err"); }
  }, 600);

  function edit(iid, fid, key, value) {
    const it = (pending.items[iid] ||= { frames: {} });
    (it.frames[fid] ||= {})[key] = value;
    flush();
  }

  for (const item of data.items) {
    const sec = el("section", "frame-sec");
    const head = el("div", "frame-sec-head");
    head.appendChild(el("h2", null, item.title));
    head.appendChild(el("span", "chip", `${fmt(item.duration_sec)} · ${item.frames.length}장`));
    if (item.pick_method) head.appendChild(el("span", "chip", item.pick_method));
    sec.appendChild(head);

    /* 영상 미리보기 — 프레임을 누르면 그 시각부터 재생된다.
       스틸만 보고 ✓ 를 찍으면 "이 순간이 맞나" 를 확인할 수 없다.
       원본은 복사하지 않고 서버가 mp4 로 리먹스해 스트리밍한다(무손실·수 초). */
    const vid = el("video", "frame-video");
    vid.controls = true;
    vid.preload = "none";
    vid.playsInline = true;
    vid.hidden = true;
    sec.appendChild(vid);

    let loaded = false;
    const seekTo = (t) => {
      if (!loaded) {
        vid.src = `/api/projects/${state.projectId}/video/${item.id}`;
        loaded = true;
      }
      vid.hidden = false;
      const go = () => { vid.currentTime = Math.max(0, t - 0.6); vid.play().catch(() => {}); };
      if (vid.readyState >= 1) go();
      else vid.addEventListener("loadedmetadata", go, { once: true });
      vid.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };

    const grid = el("div", "frame-grid");
    for (const f of item.frames) {
      const card = el("figure", "frame" + (f.selected ? " picked" : ""));

      const shot = el("button", "frame-shot");
      shot.type = "button";
      shot.title = `${fmt(f.t_sec)} 부터 영상 보기`;
      const img = el("img");
      img.loading = "lazy";
      img.decoding = "async";
      img.alt = f.alt || f.caption || `${item.title} ${fmt(f.t_sec)}`;
      img.src = `/api/projects/${state.projectId}/img/frames/${f.id}.webp`;
      shot.appendChild(img);
      shot.appendChild(el("span", "frame-play", "▶"));
      shot.onclick = () => seekTo(f.t_sec);
      card.appendChild(shot);

      const bar = el("div", "frame-bar");
      bar.appendChild(el("span", "frame-t", fmt(f.t_sec)));

      // ✓ = 이 장면이 이 항목의 얼굴이 된다(정적 우선 설계에서 카드 대표 이미지).
      const pick = el("button", "frame-pick");
      pick.type = "button";
      pick.title = "대표 컷으로";
      pick.setAttribute("aria-pressed", String(!!f.selected));
      pick.appendChild(icon("check", 13));
      pick.onclick = () => {
        const on = !card.classList.contains("picked");
        card.classList.toggle("picked", on);
        pick.setAttribute("aria-pressed", String(on));
        edit(item.id, f.id, "selected", on);
      };
      bar.appendChild(pick);
      card.appendChild(bar);

      const cap = el("textarea", "frame-cap");
      cap.rows = 2;
      cap.placeholder = data.has_captions ? "캡션 없음" : "캡션은 '쓸 컷 고르기' 단계에서 생성됩니다";
      cap.value = f.caption || "";
      cap.oninput = () => edit(item.id, f.id, "caption", cap.value);
      card.appendChild(cap);

      grid.appendChild(card);
    }
    sec.appendChild(grid);
    page.appendChild(sec);
  }
}
