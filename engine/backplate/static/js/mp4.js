/* 영상 렌더링 — 장마다 화면을 찍어 두고 **계산으로** mp4 한 편을 만든다(S12).
 *
 * ★ 예전에는 여기서 슬라이드를 통째로 재생하며 크롬이 그 탭을 스스로 받아 적게
 *   했다. 그 길은 버렸다(2026-08-14). 지지직 소리가 섞이고, 크롬이 mp4 안에
 *   opus 를 넣어 줘서 폰 갤러리·KMPlayer 가 검은 화면만 띄우고, 무엇보다
 *   **18분짜리를 얻으려면 18분을 실제로 재생해야 했다** — 그 사이 창을 한 번
 *   건드리면 그 회차가 통째로 날아간다.
 *
 * ★ 지금은 실시간이 아니라 계산이다. 장마다 줄이 뜨는 순간을 한 컷씩 찍어 두고,
 *   컷마다 다음 컷 시각까지 머무는 조각을 만들어 번호 순서로 잇는다. 조각 길이가
 *   곧 내레이션 길이라 **화면과 소리가 어긋날 자리가 없고**, 몇 번을 돌려도 같은
 *   파일이 나온다. 줄이 하나씩 뜨는 것도 그대로 담긴다(실측 4-2: 137장 → 571컷).
 *
 * ★ 이 화면이 하는 일은 두 가지뿐이다 — **미리 보고**, **굽는다.** 미리보기를
 *   1920 폭으로 그리는 것은 덱의 설계 해상도가 1920×1080 이기 때문이다. 더 좁게
 *   그리면 원고 상자의 줄바꿈이 달라져 여기서 본 것과 구운 것이 달라진다.
 */
"use strict";

import { el, api, icon, toast, fitFrame } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";
import { runSteps } from "./runner.js";
import { stepBadge, DECK } from "./steps.js";

export const meta = {
  title: "영상 렌더링",
  subtitle: "장마다 화면을 찍어 내레이션 길이만큼 이어 붙여 mp4 한 편을 만듭니다 · 음성은 모노 64k — 원본이 모노라 소리는 그대로고 76분 기준 253MB → 약 197MB(22%↓)",
};

const clock = (s) => {
  const v = Math.max(0, Math.round(s));
  const m = Math.floor(v / 60);
  return `${m}:${String(v % 60).padStart(2, "0")}`;
};

export async function mount(root, ctx) {
  const page = el("div", "page vpage");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let deck;
  try {
    deck = await api(`/api/projects/${state.projectId}/deck`);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }
  const slides = ((deck.ready && deck.slides) || []).filter((s) => !s.drop);
  if (!slides.length) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 장이 없습니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("layers", 14), el("span", null, "현황판 열기"));
    b.onclick = () => navigate("/board");
    box.appendChild(b);
    page.appendChild(box);
    return;
  }

  // 나올 영상의 길이는 **이미 정해져 있다** — 내레이션 길이의 합이 그대로 영상 길이다
  const totalSec = slides.reduce((a, s) =>
    a + ((s.audio && s.audio.sec) || (s.narration && s.narration.est_sec) || 0), 0);
  const nAudio = slides.filter((s) => s.audio && s.audio.file).length;

  const hd = el("div", "deck-head");
  const sum = el("p", "deck-sub");
  sum.textContent = `${slides.length}장 · 영상 ${clock(totalSec)}`
    + (nAudio === slides.length ? " · 음성 전부 있음"
       : ` · 음성 ${nAudio}/${slides.length}장 (없는 장은 무음으로 지나갑니다)`);
  hd.appendChild(sum);
  page.appendChild(hd);

  /* ── 최종 점검 ─────────────────────────────────────────────────────────
   * ★ **굽기 직전이 제일 싼 자리다.** 영상 한 편이 몇 십 분이라, 다 굽고 나서
   *   "라벨이 제목에 걸렸네" 를 알면 그 시간이 통째로 버려진다. 실제로 그렇게
   *   잃었다(2026-09-18: 라벨 다섯이 제목과 겹쳐 있었는데 구운 뒤에 봤다).
   * ★ **막지 않는다.** 일부러 그렇게 둔 장도 있다. 경고를 띄우고 버튼은 그대로
   *   둔다 — 막으면 사람이 점검을 끄는 길부터 찾는다.
   * ★ 점검이 안 돌아도 렌더는 돼야 한다. 그래서 실패를 삼킨다. */
  const chk = el("div", "chk");
  page.appendChild(chk);
  api(`/api/projects/${state.projectId}/check`).then((r) => {
    const items = (r && r.items) || [];
    if (!items.length) {
      chk.className = "chk ok";
      chk.append(icon("check", 13), el("span", null, "점검 통과 — 걸리는 데가 없습니다"));
      return;
    }
    chk.appendChild(el("div", "chk-h",
      `점검 ${items.length}건 — 굽기 전에 보세요 (막지는 않습니다)`));
    for (const it of items) {
      const r2 = el("div", "chk-i " + (it.level || "warn"));
      r2.append(el("span", "chk-w", it.where || ""),
                el("span", "chk-x", it.what || ""),
                el("span", "chk-f", it.fix || ""));
      chk.appendChild(r2);
    }
  }).catch(() => { chk.remove(); });

  // ── 미리보기 ──────────────────────────────────────────────────────────
  const stage = el("div", "rec-stage");
  const fr = el("iframe", "focus-frame");
  fr.title = "슬라이드 전체 재생";
  fr.allow = "autoplay; fullscreen";
  stage.appendChild(fr);
  page.appendChild(stage);
  fitFrame(stage, fr, 1920);

  const src = () => `/preview/${state.projectId}?auto=1&bare=1&t=${Date.now()}#1`;
  fr.src = src();

  // ── 조작 ──────────────────────────────────────────────────────────────
  const bar = el("div", "rec-bar");
  page.appendChild(bar);

  const btn = el("button", "btn primary lg");
  btn.type = "button";
  const bLab = el("span", null, "(전체) 영상 렌더");
  btn.append(stepBadge(DECK.video, "영상 렌더링"), icon("film", 15), bLab);
  bar.appendChild(btn);

  /* ★ 「미리보기 처음부터」를 **검수지로 갈음했다**(2026-09-20). 미리보기는
       바로 위에 이미 떠 있어서 되감기 단추가 한 자리를 차지할 값이 없었다.
       검수지는 여기가 제자리다 — 굽기 직전이 「보낼 것이 맞는지」 보는 때다.
     ★ 새 창으로 연다. 이 화면은 렌더가 돌면 몇 십 분을 지키고 있어야 하는
       자리라, 같은 창에서 갈아치우면 돌아올 데를 잃는다. */
  const rev = el("a", "btn");
  rev.href = `/review/${state.projectId}`;
  rev.target = "_blank";
  rev.rel = "noopener";
  rev.title = "씬마다 A4 한 장 — 슬라이드·캡션·자막·발음."
            + " 고칠 수 있고, 바뀐 것만 따로 저장됩니다";
  rev.append(icon("printer", 14), el("span", null, "검수지"));
  bar.appendChild(rev);

  const note = el("span", "rec-note", "");
  bar.appendChild(note);

  const out = el("div", "rec-out");
  out.hidden = true;
  page.appendChild(out);

  // ── 안내 ──────────────────────────────────────────────────────────────
  const help = el("div", "rec-help");
  help.appendChild(el("b", null, "누르고 자리를 뜨셔도 됩니다"));
  const ul = el("ul");
  for (const [t1, t2] of [
    ["재생하지 않습니다 — 계산해서 만듭니다",
     "장마다 화면을 사진으로 찍고, 이미 만들어 둔 내레이션 길이만큼 그 사진을 "
     + "보여 주는 조각을 만들어 번호 순서로 잇습니다. 재생 시간보다 빨리 끝납니다"],
    ["줄이 하나씩 뜨는 것도 담깁니다",
     "한 장을 줄이 뜨는 순간마다 여러 컷으로 나눠 찍습니다 — 내레이션이 그 줄을 "
     + "읽는 순간에 그 줄이 뜹니다"],
    ["화면과 소리가 어긋나지 않습니다",
     "조각 길이를 재생 타이밍이 아니라 내레이션 길이라는 숫자로 정하기 때문입니다. "
     + "몇 번을 돌려도 같은 파일이 나옵니다"],
    ["폰에서도 그냥 열립니다",
     "h264 / aac 로 굽고 색인을 파일 맨 앞에 둡니다 — 옮겨서 바로 재생됩니다"],
  ]) {
    const li = el("li");
    li.append(el("b", null, t1), el("span", null, t2));
    ul.appendChild(li);
  }
  help.appendChild(ul);
  page.appendChild(help);

  // ── 굽기 ──────────────────────────────────────────────────────────────
  /* 끝나면 **파일이 어디 있는지**와 **폴더 열기** 하나만 남긴다. 다음에 할 일이
     그것뿐이기 때문이다(내려받기는 두지 않는다 — 브라우저 기본 폴더에 떨어뜨리면
     나중에 "그 영상 어디 갔지" 가 되고, 이 앱은 산출물을 한 자리에 모아 왔다). */
  btn.onclick = async () => {
    // 검수지는 링크라 잠글 것이 없다 — 굽는 동안에도 열어 볼 수 있어야 한다
    out.hidden = true;
    out.textContent = "";
    note.textContent = "";
    note.className = "rec-note";

    /* 결과는 **스테이지가 이미 남기는 로그**에서 줍는다(`영상 완료 …` / `파일: …`).
       `/stages` 는 상태만 싣고 값을 안 실어 주므로, 값을 보자고 서버에 창구를 하나
       더 뚫는 것보다 이쪽이 낫다 — 로그는 어차피 사람이 보라고 찍고 있는 것이다. */
    const logs = [];
    /* ★ **판에 따라 다른 굽개를 쓴다.**
         액자(frame)   스틸을 찍어 이어붙인다(s12-video). 글자가 그림 안에 있어
                       모션은 나중에 픽셀에서 상자를 되찾아 얹어야 한다
                       (s13c-zones). 옛 프로젝트 보수용이다.
         전면·배경판   글자가 DOM 이라 GSAP 이 직접 움직인다(s12h-hyper).
                       상자를 되찾을 일이 없고, 소리까지 −16 LUFS 로 맞춰 나온다.
       버튼을 둘로 늘리지 않는다 — 사람이 고를 일이 아니라 프로젝트가 정한 것이다.
       ★ **전면(full)이 이쪽으로 넘어왔다**(2026-09-18). 전에는 전면이 글자를
         그림에 구웠으므로 s12-video 가 맞았다. 이제 안 굽는다 — 그대로 두면
         픽셀에서 찾을 글자가 없어 상자가 하나도 안 잡히고 모션이 죽는다. */
    const plate = ["full", "plate"].includes(deck?.project?.image_fit || "");
    const key = plate ? "s12h-hyper" : "s12-video";
    /* ★ **조립을 앞에 붙인다**(2026-09-18). 굽개는 `10_덱/deck.json` 을 읽는데
         그 파일은 조립(s8)이 만든다. 손편집은 `deck.overrides.json` 에만 들어가
         있으므로, 조립을 안 지나면 **화면에서 고친 것이 영상에 안 실린다** —
         「말하는 순간」에서 문장을 다시 골라도 옛 시각으로 구워졌다.
       ★ 조립은 결정론이고 돈이 안 든다. 늘 돌려도 잃을 게 없고, 「적용 버튼을
         눌렀던가」를 사람이 기억할 일이 없어진다. */
    const ok = await runSteps(["s8-assemble", key], {
      btn, label: bLab,
      names: {"s8-assemble": "덱 조립",
              "s12-video": "영상 렌더", "s12h-hyper": "모션 영상"},
      // ★ 한 줄이 아니라 **새로 늘어난 줄들**이 온다(runner.js) — 풀어서 담는다
      onLog: (lines) => {
        for (const l of lines) logs.push(String(l));
        note.textContent = (logs[logs.length - 1] || "").slice(0, 90);
      },
    });
    toast(ok ? "영상이 나왔습니다" : "영상 렌더를 끝내지 못했습니다", ok ? "ok" : "err");
    if (!ok) return;

    note.textContent = "";
    // 로그는 앞에 시각이 붙어 온다(`14:01:12  영상 완료 …`) — 떼고 본다
    const bare = logs.map((l) => l.replace(/^\d{2}:\d{2}:\d{2}\s+/, ""));
    const done = bare.filter((l) => l.startsWith("영상 완료")).pop() || "영상이 나왔습니다";
    const file = bare.filter((l) => l.startsWith("파일:")).pop() || "";

    out.hidden = false;
    out.appendChild(el("div", "fm-lb", done));
    if (file) out.appendChild(el("div", "imgdrop-path", file.replace(/^파일:\s*/, "")));

    const row = el("div", "imgdrop-bar");
    const open = el("button", "btn primary");
    open.type = "button";
    open.append(icon("folder", 14), el("span", null, "폴더 열기"));
    open.onclick = () =>
      api(`/api/projects/${state.projectId}/reveal`, {method: "POST"})
        .catch((e) => toast("폴더를 열지 못했습니다: " + e.message, "err"));
    row.appendChild(open);
    out.appendChild(row);
    showYoutube(out);
  };

  // 이미 구워 둔 프로젝트면 들어오자마자 보여 준다
  showYoutube(out, {quiet: true});
}

/* 유튜브에 올릴 글 — 제목·설명·타임스탬프·태그.
   ★ 영상 파일만 주면 그다음이 막힌다. 올리기 화면이 요구하는 칸을 여기서
     다 채워 두고, 버튼 하나로 복사되게 한다(2026-08-15).

   ★ **모션 화면도 이걸 그대로 쓴다**(`motion.js`). 영상이 어디서 끝나느냐가
     프로젝트마다 다르기 때문이다 — 렌더링에서 끝나는 것도 있고 모션까지 가는
     것도 있고, **올리는 자리에 유튜브 글이 있어야** 한다. 그래서 글이 두 화면에
     보인다. 만드는 곳은 서버 한 군데(`render/youtube.py`)라 내용은 늘 같다. */
export async function showYoutube(out, opt = {}) {
  const pid = state.projectId;
  if (!pid) return;
  let r;
  try {
    r = await api(`/api/projects/${pid}/youtube`);
  } catch (e) {
    if (!opt.quiet) toast("유튜브 글을 만들지 못했습니다: " + e.message, "err");
    return;
  }
  if (!r || !r.text) return;
  if (opt.quiet) out.hidden = false;

  const box = el("div", "yt-box");
  const hd = el("div", "yt-hd");
  hd.appendChild(el("strong", null, "유튜브에 올릴 글"));
  const cp = el("button", "btn sm");
  cp.type = "button";
  cp.append(icon("clipboard", 12), el("span", null, "전체 복사"));
  cp.onclick = async () => {
    try {
      await navigator.clipboard.writeText(r.text);
      toast("복사했습니다 — 유튜브 올리기 화면에 붙여 넣으세요");
    } catch {
      toast("복사하지 못했습니다 — 아래 글을 직접 선택해 주세요", "err");
    }
  };
  hd.appendChild(cp);
  box.appendChild(hd);

  const ta = el("textarea", "yt-text");
  ta.readOnly = true;
  ta.rows = 16;
  ta.value = r.text;
  box.appendChild(ta);
  if (r.file) box.appendChild(el("div", "imgdrop-path", r.file));

  /* ★ 썸네일 **고르기.** 지시문을 두 벌 내므로(`render/thumbnail.py`) 그림도 두 장
     온다 — 후킹형과 차분형. 어느 쪽이 나은지는 장마다 달라 기계가 고를 일이
     아니다(2026-08-17: "썸네일 이미지를 고를 수 있게 해주세요").
     고르면 완성본 폴더에 `썸네일.png` 로 앉는다 — 옮기지 않고 복사하므로
     나중에 다른 쪽으로 바꿀 수 있다. */
  const bar = el("div", "imgdrop-bar");
  box.appendChild(bar);
  const shelf = el("div", "yt-thumbs");
  box.appendChild(shelf);

  async function drawThumbs() {
    let t;
    try { t = await api(`/api/projects/${pid}/youtube/thumbs`); } catch { return; }
    shelf.textContent = "";
    if (!(t.thumbs || []).length) {
      shelf.appendChild(el("div", "dc-muted",
        "썸네일이 아직 없습니다 — 09_이미지/썸네일프롬프트.json 을 스튜디오에 넣고 "
        + "받은 그림을 같은 폴더에 «썸네일-후킹형.png» 처럼 넣으세요"));
      return;
    }
    shelf.appendChild(el("div", "sb-cues-h",
      `썸네일 ${t.thumbs.length}장 — 눌러서 고르세요`
      + (t.picked ? ` · 지금 «${t.picked}»` : "")));
    for (const x of t.thumbs) {
      const c = el("button", "yt-th" + (t.picked && x.name === t.picked ? " on" : ""));
      c.type = "button";
      const im = el("img");
      im.loading = "lazy"; im.src = x.url; im.alt = x.kind;
      c.append(im, el("span", "yt-th-k", `${x.kind} · ${x.mb}MB`));
      c.onclick = async () => {
        try {
          await api(`/api/projects/${pid}/youtube/thumb/pick?name=${encodeURIComponent(x.name)}`,
                    {method: "POST"});
          toast(`«${x.kind}» 을 썸네일로 정했습니다 — 완성본 폴더에 썸네일.png`);
          drawThumbs();
        } catch (e) { toast("고르지 못했습니다: " + e.message, "err"); }
      };
      shelf.appendChild(c);
    }
  }
  drawThumbs();

  const open = el("button", "btn sm");
  open.type = "button";
  open.append(icon("folder", 12), el("span", null, "그림 폴더 열기"));
  open.onclick = () => api(`/api/projects/${pid}/reveal?step=images`, {method: "POST", body: {}})
    .catch((e) => toast("열지 못했습니다: " + e.message, "err"));
  bar.appendChild(open);
  out.appendChild(box);
}
