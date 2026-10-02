/* 모션 리마스터 — 구운 mp4 를 **재료로** 다시 굽는다.
 *
 * ★ 이 화면은 **렌더링 다음이지만, 반드시 오는 곳은 아니다.** 렌더링에서 끝나는
 *   영상도 있다. 그래서 현황판의 스테이지 그리드에 칸을 만들지 않았다 — 거기
 *   있으면 영영 안 채워지는 칸이 하나 남고, 「다음 할 일」이 계속 조른다.
 *
 * ★ 흐름에 **사람이 끼는 자리가 딱 한 번** 있다 — 상자 찍기. 도구가 글자띠를
 *   찾아 기본 상자를 얹어 주지만, 굵은 제목이나 연표 글자는 통째로 놓치기도
 *   한다. 그래서 지정기를 열어 사람이 고치고, 내려받은 zones.json 을 여기
 *   «불러오기» 로 다시 넣는다. 목차 JSON 을 주고받는 것과 같은 단추다.
 *
 *      1  지정기 만들기  →  브라우저가 열린다
 *      2  사람이 상자·시간을 찍고 zones.json 을 내려받는다
 *      3  zones.json 불러오기
 *      4  시안 95초  ← **여기를 건너뛰지 않는다.** 전체는 30~40분이다
 *      5  전체
 *
 * ★ 유튜브 글이 렌더링 화면과 여기 둘 다 있다. 영상이 어디서 끝나느냐가
 *   프로젝트마다 다르고, **올리는 자리에 그 글이 있어야** 하기 때문이다.
 */
"use strict";

import { el, api, icon, toast } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";
import { runJob } from "./runner.js";
import { showYoutube } from "./mp4.js";

export const meta = {
  title: "모션",
  subtitle: "구운 영상을 재료로 글자가 떠오르고 빛이 훑는 판을 다시 굽습니다 · crf 24 로 굽습니다 — 76분 기준 487MB → 약 257MB(47%↓)",
};

const mb = (n) => `${Number(n || 0).toFixed(1)}MB`;

export async function mount(root, ctx) {
  const page = el("div", "page vpage");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  const host = el("div");
  page.appendChild(host);
  await draw();

  async function draw() {
    host.textContent = "";
    let s;
    try {
      s = await api(`/api/projects/${state.projectId}/motion`);
    } catch (e) {
      host.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
      return;
    }

    // ── 도구가 없으면 여기서 끝 ──
    if (!s.tool_dir) {
      const box = el("div", "empty");
      box.appendChild(el("p", null, "모션 도구 폴더를 못 찾았습니다."));
      box.appendChild(el("div", "imgdrop-path",
        "showcase.config.local.json 의 motion.tool_dir 에 "
        + "motion-remaster 폴더 경로를 적어 주세요"));
      host.appendChild(box);
      return;
    }
    if (!s.mp4) {
      const box = el("div", "empty");
      box.appendChild(el("p", null, s.note || "아직 완성 mp4 가 없습니다."));
      const b = el("button", "btn primary");
      b.type = "button";
      b.append(icon("film", 14), el("span", null, "영상 렌더링으로"));
      b.onclick = () => navigate("/mp4");
      box.appendChild(b);
      host.appendChild(box);
      return;
    }

    // ── 재료 ──
    const hd = el("div", "deck-head");
    const sum = el("p", "deck-sub");
    sum.textContent = `재료 ${s.mp4.name} · ${mb(s.mp4.mb)}`
      + (s.mp4.sec ? ` · ${Math.round(s.mp4.sec / 60)}분` : "")
      + (s.slides ? ` · 슬라이드 ${s.slides}장 (씬 ${s.expect_scenes}개 예상)` : "");
    hd.appendChild(sum);
    host.appendChild(hd);
    if (!s.ffprobe) {
      host.appendChild(el("div", "onote",
        "ffprobe 를 PATH 에서 못 찾았습니다 — 길이 검증을 못 합니다."));
    }
    /* ★ 굽기 전에 말한다. 30분을 태우고 나서 «numpy 가 없습니다» 를 보는 것이
       이 화면에서 나올 수 있는 가장 비싼 실패다. */
    if (!s.deps) {
      host.appendChild(el("div", "onote",
        `${s.python} 에 numpy·Pillow 가 없습니다 — 그 둘이 있는 파이썬 경로를 `
        + "showcase.config.local.json 의 motion.python 에 적어 주세요."));
    }

    const note = el("span", "rec-note", "");
    const logbox = el("div", "rec-out");
    logbox.hidden = true;

    /* ── 0) 상자 자리 찾기 ────────────────────────────────────────────────
       ★ 이 단계가 **지정기보다 먼저**다. 그림을 만들 때 적어 둔 라벨(원장)을
         답지로 삼아 화면에서 그 글자를 찾고, 제대로 나왔는지까지 본다.
         실측: 예전 방식은 그림에 구운 라벨 130개 중 4개를 잡았고(3%), 이 단계는
         84개를 잡는다(65%). 찾은 상자는 딴 파일에 두므로 `zones.json` 은
         건드리지 않는다 — 아래 「지정기 만들기」가 그것을 밑그림으로 깐다. */
    const s0 = step("0", "상자 자리 찾기 (권함)",
      "그림을 만들 때 적어 둔 라벨을 화면에서 찾아 상자를 미리 놓습니다. "
      + "깨져 나온 글자도 같이 짚어 줍니다. Claude 를 부르므로 값이 듭니다");

    const bFind = el("button", "btn primary");
    bFind.type = "button";
    const lFind = el("span", null, "상자 자리 찾기");
    bFind.append(icon("target", 14), lFind);
    bFind.title = "zones.json 은 건드리지 않습니다 — 찾은 상자는 따로 두고, "
      + "지정기를 만들 때 밑그림으로 깔립니다";
    const findBar = el("div", "imgdrop-bar");
    findBar.append(bFind);
    s0.appendChild(findBar);
    if (s.gen) {
      s0.appendChild(el("div", "imgdrop-path",
        `찾아 둔 상자 ${s.gen.boxes}개 · ${s.gen.scenes}장`
        + (s.report ? `  ·  검수 보고: ${s.report}` : "")));
    }
    bFind.onclick = () => bake(
      `/api/projects/${state.projectId}/motion/zones/auto`,
      { btn: bFind, label: lFind, name: "상자 자리 찾기",
        group: [bPick, bNew, bZone, bPrev, bFull] });

    // ── 1) 지정기 ─────────────────────────────────────────────────────────
    const s1 = step("1", "마스크 지정기",
      "글자가 떠오를 자리를 상자로 찍습니다. 0번을 먼저 돌렸다면 그 상자가 "
      + "깔린 채로 열립니다 — 열어서 고쳐 주세요");

    const bPick = el("button", "btn primary");
    bPick.type = "button";
    const lPick = el("span", null, s.picker ? "지정기 다시 열기" : "지정기 만들고 열기");
    bPick.append(icon("target", 14), lPick);

    const bNew = el("button", "btn");
    bNew.type = "button";
    bNew.append(icon("refresh", 14), el("span", null, "새로 만들기"));
    bNew.title = "장면을 다시 찾아 기본 상자를 새로 얹습니다 — 찍어 둔 상자는 안 사라집니다"
      + "(zones.json 은 그대로 남습니다)";
    bNew.hidden = !s.picker;

    const pickBar = el("div", "imgdrop-bar");
    pickBar.append(bPick, bNew);
    s1.appendChild(pickBar);
    if (s.picker) {
      s1.appendChild(el("div", "imgdrop-path", s.picker.path));
    }

    const openPicker = (force) => bake(
      `/api/projects/${state.projectId}/motion/picker${force ? "?force=true" : ""}`,
      { btn: bPick, label: lPick, name: "지정기", group: [bNew, bZone, bPrev, bFull] });
    bPick.onclick = () => {
      // 이미 있으면 굳이 다시 만들지 않는다 — 서버가 그대로 열어 준다
      openPicker(false);
    };
    bNew.onclick = () => openPicker(true);

    // ── 2) zones.json ─────────────────────────────────────────────────────
    const s2 = step("2", "zones.json 불러오기",
      "지정기에서 «zones.json 내려받기» 를 누른 뒤, 그 파일을 여기로 넣으세요");

    /* ★ 목차 화면의 «JSON 불러오기» 와 **같은 단추**다(`outline.js`) — 숨은
       파일 입력 + 버튼. 다운로드 폴더를 코드로 뒤지지 않는 이유는 그림 폴더와
       같다: 남의 폴더를 훑다 잘못 집으면 되돌릴 방법이 없다. */
    const pickFile = el("input");
    pickFile.type = "file";
    pickFile.accept = "application/json,.json";
    pickFile.hidden = true;
    s2.appendChild(pickFile);

    const bZone = el("button", "btn");
    bZone.type = "button";
    bZone.append(icon("upload", 14), el("span", null, "zones.json 불러오기"));
    bZone.title = "지정기에서 내려받은 파일을 완성본 폴더로 들입니다";
    bZone.onclick = () => pickFile.click();

    const zoneBar = el("div", "imgdrop-bar");
    zoneBar.appendChild(bZone);
    s2.appendChild(zoneBar);

    if (s.zones) {
      const line = el("div", "fm-lb",
        `${s.zones.name} — 씬 ${s.zones.scenes}개 · 상자 ${s.zones.boxes}개`);
      s2.appendChild(line);
      s2.appendChild(el("div", "imgdrop-path", s.zones.path));
      if (s.expect_scenes && s.zones.scenes !== s.expect_scenes) {
        s2.appendChild(el("div", "onote",
          `씬 ${s.zones.scenes}개인데 슬라이드로 세면 ${s.expect_scenes}개입니다 — `
          + "표지 1장은 영상에 없으니 그림 수보다 하나 적은 것이 맞습니다."));
      }
    }

    pickFile.onchange = async () => {
      const f = pickFile.files && pickFile.files[0];
      pickFile.value = "";
      if (!f) return;
      bZone.disabled = true;
      try {
        const text = await f.text();
        const r = await api(`/api/projects/${state.projectId}/motion/zones`,
                            { method: "POST", body: { text } });
        toast(`받았습니다 — 씬 ${r.scenes}개 · 상자 ${r.boxes}개`);
        if (r.warn) toast(r.warn, "warn");
        await draw();
      } catch (e) {
        toast("불러오지 못했습니다: " + e.message, "err");
        bZone.disabled = false;
      }
    };

    // ── 3) 굽기 ───────────────────────────────────────────────────────────
    const s3 = step("3", "굽기",
      "전체를 바로 구워도 됩니다(원본 길이의 1.5~1.8배). "
      + "값을 바꿔 보고 싶을 때만 시안 95초를 먼저 구우세요 — 2분입니다");

    const bPrev = el("button", "btn primary");
    bPrev.type = "button";
    const lPrev = el("span", null, "시안 95초");
    bPrev.append(icon("film", 14), lPrev);
    bPrev.disabled = !s.zones;

    const bFull = el("button", "btn");
    bFull.type = "button";
    const lFull = el("span", null, "전체 굽기");
    bFull.append(icon("film", 14), lFull);
    // ★ 시안은 **조건이 아니다**(2026-08-16). 값이 확정된 뒤로는 시안이 확인해
    //   줄 것이 없어서, 매번 2분을 먼저 태우는 쪽이 더 비쌌다.
    bFull.disabled = !s.zones;
    bFull.title = s.zones ? "" : "zones.json 을 먼저 넣으세요";

    /* 값 — 사람이 말로 하는 것을 인자로 옮기는 자리. 비우면 확정값으로 굽는다. */
    const vals = el("input", "mo-vals");
    vals.type = "text";
    vals.placeholder = "값을 바꿀 때만 (예: --text-sheen-amp 0.55)";
    vals.title = "빛이 약하면 --text-sheen-amp 0.55 · 번쩍이면 0.32 와 --text-sheen-dur 3.0\n"
      + "글자가 빨리 뜨면 --text-dur 1.6 · 겹쳐 보이면 --out-dur 0.6";

    const bakeBar = el("div", "imgdrop-bar");
    bakeBar.append(bPrev, bFull, vals);
    s3.appendChild(bakeBar);

    /* ★ **굽는 동안 초가 올라가는 자리.** `runJob` 이 이미 버튼 글자에 시계를
     * 찍지만(`static/js/runner.js`), 화면이 다시 그려지면 그 버튼 노드가 떨어져
     * 나가 **초가 멈춘 것처럼 보인다**(2026-09-05). 전체 굽기는 30~40분이라
     * 그 사이 화면이
     * 한 번이라도 다시 그려지면 사람은 죽은 줄 안다.
     * 그래서 **칸에 붙은 줄**을 따로 둔다 — 버튼과 달리 여기는 안 사라진다.
     * ★ 끝나는 시각도 같이 적는다. 남은 시간을 사람이 암산하지 않게. */
    const timer = el("div", "onote mo-timer");
    timer.hidden = true;
    s3.appendChild(timer);

    const q = () => (vals.value.trim()
      ? `&vals=${encodeURIComponent(vals.value.trim())}` : "");
    bPrev.onclick = () => bake(
      `/api/projects/${state.projectId}/motion/bake?mode=시안${q()}`,
      { btn: bPrev, label: lPrev, name: "시안", group: [bPick, bNew, bZone, bFull] });
    bFull.onclick = () => bake(
      `/api/projects/${state.projectId}/motion/bake?mode=전체${q()}`,
      { btn: bFull, label: lFull, name: "전체", group: [bPick, bNew, bZone, bPrev] });

    // ── 구워 둔 것 ────────────────────────────────────────────────────────
    if ((s.bakes || []).length) {
      const s4 = step("", "구운 것", "");
      for (const b of s.bakes) {
        const row = el("div", "mo-row");
        row.append(el("span", "mo-name",
          `${b.name} · ${mb(b.mb)}${b.preview ? " · 시안" : ""}`));
        /* ★ 길이 두 값을 **그대로 보여 준다.** "통과" 만 찍으면 무엇을 보고
           판정했는지 사람이 확인할 수 없다.
           ★ 시안(`ok === null`)은 **판정하지 않는다.** --limit 은 영상만 정확히
             자르고 오디오는 복사본이라 패킷 경계에서 끝나서, 시안은 늘 두 값이
             다르다(실측 95.0 대 93.39). 거기에 경고를 달면 매번 틀린 경고가 뜨고
             전체판의 진짜 경고까지 같이 묻힌다. */
        const num = b.video == null ? "길이 못 잼"
          : `영상 ${b.video} / 오디오 ${b.audio}`;
        row.append(b.ok === null
          ? el("span", "mo-idle", num)
          : el("span", b.ok ? "mo-ok" : "mo-warn",
               `${num}${b.ok ? " 맞음" : " ⚠ 다름"}`));
        const play = el("button", "btn sm");
        play.type = "button";
        play.append(icon("external", 12), el("span", null, "열기"));
        play.onclick = () => window.open(b.url, "_blank");
        row.appendChild(play);
        s4.appendChild(row);
      }
      const open = el("button", "btn");
      open.type = "button";
      open.append(icon("folder", 14), el("span", null, "폴더 열기"));
      open.onclick = () =>
        api(`/api/projects/${state.projectId}/reveal`, { method: "POST" })
          .catch((e) => toast("폴더를 열지 못했습니다: " + e.message, "err"));
      const bar = el("div", "imgdrop-bar");
      bar.appendChild(open);
      s4.appendChild(bar);
    }

    /* ★ 흐르는 로그는 **한 자리에만** 둔다. 단계마다 로그 칸을 두면 어느 칸이
       지금 도는 것인지 눈으로 찾아야 한다 — 무엇을 눌렀든 여기가 움직인다. */
    host.append(note, logbox);

    // ── 유튜브 글 — 렌더링 화면과 같은 것 ────────────────────────────────
    const yt = el("div", "rec-out");
    yt.hidden = true;
    host.appendChild(yt);
    showYoutube(yt, { quiet: true });

    /* 한 덩이 — 번호 · 제목 · 설명 */
    function step(n, title, why) {
      const box = el("div", "rec-help");
      const h = el("b", null, n ? `${n}. ${title}` : title);
      box.appendChild(h);
      if (why) box.appendChild(el("p", "deck-sub", why));
      host.appendChild(box);
      return box;
    }

    /* 잡 하나 돌리기 — 버튼이 시계가 되고, 로그가 쌓인다 */
    async function bake(url, o) {
      logbox.hidden = false;
      logbox.textContent = "";
      note.textContent = "";
      const pre = el("pre", "mo-log");
      logbox.appendChild(pre);
      const lines = [];
      /* 얼마나 걸릴지 — 원본 길이의 1.5~1.8배(파일 머리말). 시안은 95초짜리다.
         모르면 안 적는다: 틀린 예상은 없는 것만 못하다. */
      const srcSec = o.name === "시안" ? 95 : Number((s.mp4 || {}).sec) || 0;
      const est = srcSec ? `${Math.round(srcSec * 1.5 / 60)}~${Math.round(srcSec * 1.8 / 60)}분` : "";
      const t0 = Date.now();
      timer.hidden = false;
      const tick = () => {
        const sec = Math.floor((Date.now() - t0) / 1000);
        const mm = `${Math.floor(sec / 60)}분 ${String(sec % 60).padStart(2, "0")}초`;
        timer.textContent = `${o.name} 굽는 중 — ${mm} 지났습니다`
          + (est ? ` · 보통 ${est} 걸립니다` : "")
          + ` · 시작 ${new Date(t0).toTimeString().slice(0, 5)}`;
      };
      tick();
      const iv = setInterval(tick, 1000);
      const ok = await runJob(url, {
        btn: o.btn, label: o.label, group: o.group, name: o.name,
        onLog: (ls) => {
          for (const l of ls) lines.push(String(l).replace(/^\d{2}:\d{2}:\d{2}\s+/, ""));
          // 꼬리만 보여 준다 — 다 쌓으면 화면이 로그로 덮인다
          pre.textContent = lines.slice(-14).join("\n");
          note.textContent = (lines[lines.length - 1] || "").slice(0, 90);
        },
      });
      clearInterval(iv);
      note.textContent = "";
      if (!ok) { timer.textContent = `${o.name} 굽기가 멈췄습니다`; return; }
      timer.hidden = true;
      toast(`${o.name} 이(가) 끝났습니다`);
      await draw();
    }
  }
}
