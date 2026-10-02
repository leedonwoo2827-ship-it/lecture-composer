/* 시작 — **좌표를 넣으면, 재료를 읽고, 물어볼 것이 생긴다.**
 *
 *   ① 좌표   레포 · 화면녹화 폴더 · 라이브 URL        "재료가 어디 있나"
 *      ↓     S1 프레임 · S2 레포 (결정론 · 공짜 · 수 초)
 *   ② 설문   **레포를 읽고 만든 질문** + 추천          "무엇을 팔 건가"
 *      ↓
 *   ③ 기획서 00_기획/prd.md
 *
 * ★ ②는 고정 목록이 아니다. 물어볼 것은 프로젝트마다 다르다 — 결제가 뼈대만 있는
 *   레포에는 "결제를 발표에 넣을까요" 를 물어야 한다. 그래서 좌표를 먼저 받고,
 *   재료를 읽은 다음에 질문을 만든다.
 *
 * ★ 질문마다 **추천과 그 이유**가 붙는다. 빈 화면에서 고르라고 하면 아무도 못 고른다.
 *   레포를 읽은 쪽이 먼저 의견을 내고, 사람은 고치기만 하면 된다.
 *
 * 여기가 바닥(base)인 이유: 미저장 입력이 가득하다. 패널은 Esc 로 닫힌다.
 */
"use strict";

import { $, el, api, icon, toast, fmtBytes } from "./util.js";
import { state, invalidate } from "./store.js";
import { navigate } from "./shell.js";
import { runSteps } from "./runner.js";

export const meta = {
  title: "시작",
  subtitle: "재료가 어디 있는지 넣으면, 읽어 보고 물어볼 것을 만듭니다",
};

const POLL = 1500;

export async function mount(root) {
  const page = el("div", "page spage");
  root.appendChild(page);

  const hd = el("div", "deck-head");
  hd.appendChild(el("h2", null, "새 발표 만들기"));
  const sub = el("p", "deck-sub", "재료가 어디 있는지 넣으면, 읽어 보고 물어볼 것을 만듭니다.");
  hd.appendChild(sub);
  page.appendChild(hd);

  const body = el("div");
  page.appendChild(body);

  let pid = null;
  const answers = {};

  phase1();

  /* ── ① 좌표 ─────────────────────────────────────────────── */
  function phase1() {
    body.textContent = "";
    const s = section("1", "좌표", "재료가 어디 있는지");
    const form = {};
    const g = el("div", "sform");
    const field = (key, label, ph, hint) => {
      const w = el("label", "sfield");
      w.appendChild(el("span", "sfield-lb", label));
      const i = el("input");
      i.type = "text";
      i.placeholder = ph;
      i.autocomplete = "off";
      i.onkeydown = (e) => { if (e.key === "Enter") go.click(); };
      form[key] = i;
      w.appendChild(i);
      if (hint) w.appendChild(el("span", "sfield-hint", hint));
      return w;
    };
    g.append(field("title", "발표 제목", "비워도 됩니다 — 레포 이름에서 따옵니다"));
    s.appendChild(g);

    /* ★ 레포와 라이브 URL은 **쌍**이다. 레포마다 사이트가 있을 수도, 없을 수도 있다
     * (로컬 앱·플러그인처럼). 한 발표가 레포 하나로 끝나지 않는 경우도 많아서
     * 줄을 늘릴 수 있게 뒀다 — 최대 5줄. */
    const MAX_SRC = 5;
    const srcWrap = el("div", "srcs");
    s.appendChild(el("span", "sfield-lb sfield-lb-top", "레포와 사이트"));
    s.appendChild(srcWrap);
    const rows = [];

    function addRow(repo = "", url = "") {
      if (rows.length >= MAX_SRC) return;
      const row = el("div", "srcrow");
      const n = el("span", "srcrow-n", String(rows.length + 1));
      const r = el("input", "src-repo");
      r.type = "text";
      r.placeholder = rows.length ? "owner/name (선택)" : "owner/name 또는 깃허브 주소";
      r.autocomplete = "off";
      const u = el("input", "src-url");
      u.type = "text";
      u.placeholder = "라이브 URL (없으면 비워 두세요)";
      u.autocomplete = "off";
      const x = el("button", "src-x");
      x.type = "button";
      x.textContent = "×";
      x.title = "이 줄 지우기";
      x.onclick = () => {
        const i = rows.indexOf(rec);
        if (i >= 0) rows.splice(i, 1);
        row.remove();
        renumber();
      };
      r.value = repo; u.value = url;
      r.onkeydown = u.onkeydown = (e) => { if (e.key === "Enter") go.click(); };
      row.append(n, r, u, x);
      srcWrap.appendChild(row);
      const rec = {repo: r, url: u, row, n};
      rows.push(rec);
      renumber();
    }

    function renumber() {
      rows.forEach((x, i) => {
        x.n.textContent = String(i + 1);
        x.row.querySelector(".src-x").hidden = rows.length <= 1;
      });
      more.hidden = rows.length >= MAX_SRC;
      more.textContent = `+ 레포 한 줄 더  (${rows.length}/${MAX_SRC})`;
    }

    // 버튼과 안내글을 한 줄에 나란히 — 따로 두면 서로 겹친다
    const moreRow = el("div", "src-morerow");
    const more = el("button", "btn sm src-more");
    more.type = "button";
    more.onclick = () => addRow();
    moreRow.append(more, el("span", "sfield-hint",
      "gh 로 얕게 받아옵니다. 비공개도 됩니다. 사이트가 없으면 URL 칸을, 사이트만 있으면 레포 칸을 비우세요 — 한 레포에 사이트가 둘이면 두 번째 줄은 URL 만 적습니다"));
    s.appendChild(moreRow);
    addRow();

    const g2 = el("div", "sform");
    g2.append(field("video_dir", "화면녹화 폴더", "D:\...\_video-context",
                    "mkv · mp4 를 훑어 항목을 만듭니다. 없으면 비워 두세요"));
    s.appendChild(g2);

    /* ★ 참고 자료 — 레포에도 영상에도 없는 재료(이론 요약 HTML, 기획 메모,
     * 캡처 이미지 같은 것). 브라우저는 로컬 경로를 안 주므로 바이트를 읽어
     * 올려보낸다 — 서버가 00_기획/참고/ 에 원본 그대로 복사해 둔다. */
    const refFiles = [];   // [{name, size, dataUrl}]
    s.appendChild(el("span", "sfield-lb sfield-lb-top", "참고 자료"));
    const refBox = el("div", "refdrop");
    const zone = el("div", "refdrop-zone");
    zone.append(icon("upload", 20),
      el("b", null, "여기로 파일을 끌어다 놓으세요"),
      el("span", null, "이론 요약 HTML · 기획 메모 · 캡처 이미지 — 여러 개 가능, 눌러서 선택도 됩니다"));
    const refInput = el("input");
    refInput.type = "file";
    refInput.multiple = true;
    refInput.hidden = true;
    const refList = el("div", "reflist");

    function drawRefs() {
      refList.textContent = "";
      refFiles.forEach((f, i) => {
        const row = el("div", "refitem");
        row.append(el("span", "refitem-n", String(i + 1)),
                   el("span", "refitem-name", f.name),
                   el("span", "refitem-size", fmtBytes(f.size)));
        const x = el("button", "refitem-x");
        x.type = "button";
        x.textContent = "×";
        x.title = "빼기";
        x.onclick = () => { refFiles.splice(i, 1); drawRefs(); };
        row.appendChild(x);
        refList.appendChild(row);
      });
    }

    async function addRefFiles(fileList) {
      for (const f of Array.from(fileList)) {
        const dataUrl = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = rej;
          r.readAsDataURL(f);
        });
        refFiles.push({name: f.name, size: f.size, dataUrl});
      }
      drawRefs();
    }

    zone.onclick = () => refInput.click();
    refInput.onchange = () => { addRefFiles(refInput.files); refInput.value = ""; };
    zone.ondragover = (e) => { e.preventDefault(); refBox.classList.add("over"); };
    zone.ondragleave = () => refBox.classList.remove("over");
    zone.ondrop = (e) => {
      e.preventDefault();
      refBox.classList.remove("over");
      if (e.dataTransfer.files.length) addRefFiles(e.dataTransfer.files);
    };
    refBox.append(zone, refList, refInput);
    s.appendChild(refBox);
    s.appendChild(el("span", "sfield-hint",
      "레포·영상이 없어도 참고 자료만으로 발표를 만들 수 있습니다"));
    body.appendChild(s);

    const foot = el("div", "sfoot");
    foot.appendChild(el("div", "sfoot-note",
      "넣으면 프레임과 레포를 먼저 읽습니다. 돈은 안 듭니다."));
    const go = el("button", "btn primary lg");
    go.type = "button";
    go.append(icon("wand", 15), el("span", null, "재료 읽고 질문 받기"));
    go.onclick = async () => {
      // ★ 레포 칸이 비고 **주소만** 있는 줄도 보낸다. 한 레포에 사이트가 둘인
      //   경우(릴레이 서버 등)가 실제로 있다 — 여기서 걸러 버리면 그 주소는
      //   서버에 닿지도 못한다. 서버가 "사이트만" 으로 갈라 처리한다.
      const sources = rows
        .map((x) => ({repo: x.repo.value.trim(), url: x.url.value.trim()}))
        .filter((x) => x.repo || x.url);
      if (!form.video_dir.value.trim() && !sources.some((x) => x.repo) && !refFiles.length) {
        toast("레포 · 화면녹화 폴더 · 참고 자료 중 하나는 있어야 합니다", "err");
        rows[0].repo.focus();
        return;
      }
      go.disabled = true;
      go.querySelector("span").textContent = "만드는 중…";
      try {
        const p = await api("/api/projects", {
          method: "POST",
          body: {
            title: form.title.value.trim() || null,
            video_dir: form.video_dir.value.trim(),
            sources,
            ref_uploads: refFiles.map((f) => ({name: f.name, data_url: f.dataUrl})),
          },
        });
        pid = p.id;
        state.projectId = pid;
        invalidate();
        // ★ HTML 참고자료는 이미 장별로(h2) 정리돼 있다 — AI 구조설계가 필요
        //   없다. 있으면 캡처 문으로 바로 가서 설문·기획서·구조설계를 건너뛴다.
        const hasHtmlRef = ((p.refs || {}).items || []).some((it) => it.kind === "html");
        if (hasHtmlRef) {
          askKind();
        } else {
          phase2();
        }
      } catch (e) {
        toast("만들지 못했습니다: " + e.message, "err");
        go.disabled = false;
        go.querySelector("span").textContent = "재료 읽고 질문 받기";
      }
    };
    foot.appendChild(go);
    body.appendChild(foot);
    rows[0].repo.focus();
  }

  /* ── HTML 참고자료 → 화면 캡처로 씬 바로 확정 ──────────────
   * 설문·기획서·AI 구조설계를 전부 건너뛴다 — h2 경계가 이미 그 판단이다.
   * S2c(s2c-capture) 한 단계만 돌고 바로 현황판으로 간다. */
  /* ── 어느 종류의 원고인가 — **문 앞에서 정한다** ──────────────────────
   * 원고를 넣자마자 묻는 이유: 그림 파일은 **번호로** 이름이 붙는다(`003.png` =
   * 3번 장). 나중에 정하면 번호가 이미 흔들린 뒤라 만들어 둔 그림이 남의 장
   * 것이 된다. 여기서 정하면 목차가 서는 순간 번호도 같이 선다.
   *
   * ★ 「영상 섞기」는 여기 없다. 영상은 **덱이 아니라 장의 성질**이라, 목차가
   *   선 뒤에 그 장에만 붙인다(현황판의 «영상» 칸). 여기에 세 번째 버튼을 두면
   *   고르는 순간엔 아무것도 안 달라지고, 나중에 또 장마다 붙여야 한다.
   */
  function askKind() {
    body.textContent = "";
    const s = section("2", "어떤 원고인가요", "누르면 장을 나눕니다");
    const box = el("div", "kind-pick");

    /* ★ **고르는 자리였는데 한 장만 남았다**(2026-09-18). 액자(3:2)도 html 원고도
     *   이제 안 쓴다 — 전면 한 판으로만 굽는다. 그런데도 버튼을 없애지 않은 것은,
     *   여기를 누르는 순간 **번호가 선다**는 것을 눈으로 보고 넘어가야 하기
     *   때문이다(위 주석).
     *   ★ 지난 프로젝트는 제 값을 그대로 들고 있다 — 서버는 `image_fit` 을
     *     안 보내면 안 건드리고, 보수는 이 문을 지나지 않는다(새 발표만 지난다).
     *     그래서 여기서 갈래를 지워도 지난 영상이 달라지지 않는다. */
    const b = el("button", "btn kind-card primary");
    b.type = "button";
    b.append(el("strong", null, "이미지 원고 · 전면"),
             el("span", null,
                "장마다 그림 한 판이 글을 대신하고, 그림이 화면을 꽉 채웁니다. " +
                "제목은 맨 위에 따로 뜹니다."));
    b.onclick = () => { b.disabled = true; captureFlow(); };
    box.appendChild(b);
    s.appendChild(box);

    const tip = el("p", "kind-tip");
    tip.textContent = "영상은 여기서 안 고릅니다 — 목차가 선 뒤에 장마다 붙입니다.";
    s.appendChild(tip);
    body.appendChild(s);
  }

  async function captureFlow() {
    body.textContent = "";
    const s = section("2", "씬 만드는 중", "참고자료를 장별로 캡처해 씬을 확정합니다");
    const log = el("div", "srun");
    s.appendChild(log);
    body.appendChild(s);

    const line = (t, cls) => {
      const d = el("div", "srun-line" + (cls ? " " + cls : ""));
      d.appendChild(el("span", "srun-txt", t));
      log.appendChild(d);
      return d;
    };

    const ln = line("… 화면 캡처로 씬 만들기", "run");
    const tail = el("div", "srun-tail");
    log.appendChild(tail);
    try {
      // ★ 장을 나누기 **전에** 종류를 박는다. 조립(s8)이 이 값을 읽어 장마다
      //   `image_swap` 을 세우고, 현황판이 그것으로 «그림으로 갈 원고» 칸을 만든다.
      // ★ 갈래는 **전면(full) 하나**다. 그래도 값을 꼬박꼬박 보내는 이유: 안 보내면
      //   서버가 안 건드리고, 조립(s8)이 제 기본값 "frame" 으로 앉혀 버린다.
      await api(`/api/projects/${pid}/image-swap`, {
        method: "POST", body: {image_swap: true, image_fit: "full"},
      });
      const ok = await runSteps(["s2c-capture"], {
        onLog: (lines) => {
          for (const x of lines) tail.appendChild(el("div", "srun-t", x));
          while (tail.children.length > 6) tail.removeChild(tail.firstChild);
          tail.scrollTop = tail.scrollHeight;
        },
      });
      if (!ok) throw new Error("씬을 만들지 못했습니다");
      ln.className = "srun-line done";
      ln.textContent = "✓ 씬 만들기";
      tail.remove();
      toast("씬이 확정됐습니다 — 이어서 문구·대본을 채우세요");
      navigate("/board");
    } catch (e) {
      line("실패: " + e.message, "err");
      const b = el("button", "btn");
      b.type = "button";
      b.append(el("span", null, "실행기에서 보기"));
      b.onclick = () => navigate("/board");
      body.appendChild(b);
    }
  }

  /* ── 재료 읽기 → 질문 만들기 ────────────────────────────── */
  async function phase2() {
    body.textContent = "";
    const s = section("2", "재료 읽는 중", "프레임 · 레포 · 그다음 물어볼 것");
    const log = el("div", "srun");
    s.appendChild(log);
    body.appendChild(s);

    // 줄 = [글자][막대]. 글자를 따로 담아 둬야 막대를 지우지 않고 고쳐 쓴다.
    const line = (t, cls) => {
      const d = el("div", "srun-line" + (cls ? " " + cls : ""));
      d.appendChild(el("span", "srun-txt", t));
      log.appendChild(d);
      return d;
    };

    try {
      for (const [key, label] of [["s1-frames", "화면녹화에서 프레임 뽑기"],
                                  ["s2-repo", "레포 받아 읽기"],
                                  ["s0a-ask", "무엇을 물어볼지 정하기"]]) {
        const ln = line(`… ${label}`, "run");
        /* 막대는 **아는 만큼만** 정직하게 그린다.
         *   total 이 있으면  → 채워지는 막대 (3/6)
         *   모르면          → 흐르는 막대 (진행 중이라는 사실만) */
        const bar = el("div", "srun-bar indet");
        const fill = el("i");
        bar.appendChild(fill);
        ln.appendChild(bar);
        // ★ 줄 자체가 시계이고, 그 밑에 서버 로그가 쌓인다.
        //   "눌렀는데 아무 일도 없다" 가 이 화면의 가장 큰 문제였다.
        const tail = el("div", "srun-tail");
        log.appendChild(tail);
        const ok = await runSteps([key], {
          onStep: (s, a) => {
            ln.firstChild.textContent = `… ${label} — ${s}`
              + (a.total ? `  (${a.completed}/${a.total})` : "");
            const known = a.total > 0;
            bar.classList.toggle("indet", !known);
            fill.style.width = known
              ? `${Math.round((a.completed / a.total) * 100)}%` : "";
          },
          onLog: (lines) => {
            for (const x of lines) tail.appendChild(el("div", "srun-t", x));
            while (tail.children.length > 6) tail.removeChild(tail.firstChild);
            tail.scrollTop = tail.scrollHeight;
          },
        });
        if (!ok) throw new Error(label);
        ln.className = "srun-line done";
        ln.textContent = `✓ ${label}`;   // 막대까지 같이 걷힌다
        tail.remove();                   // 끝난 단계의 로그도 걷는다
      }
      await phase3();
    } catch (e) {
      line("실패: " + e.message, "err");
      const b = el("button", "btn");
      b.type = "button";
      b.append(el("span", null, "실행기에서 보기"));
      b.onclick = () => navigate("/board");
      body.appendChild(b);
    }
  }

  /* ★ 오래 걸리는 단계는 **시계가 돌아야** 산 것으로 보인다.
   * 레포를 읽는 단계는 2~3분씩 간다. 그동안 글자가 안 바뀌면 멈춘 걸로 읽힌다.
   * 그래서 (지금 무엇을 하는지 + 흐른 시간) 을 같이 보여 준다. */
  function ticker(set) {
    const t0 = Date.now();
    let note = "시작하는 중";
    const draw = () => {
      const s = Math.floor((Date.now() - t0) / 1000);
      set(`${note} · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
    };
    const iv = setInterval(draw, 1000);
    draw();
    return { say: (n) => { if (n) { note = n; draw(); } },
             stop: () => clearInterval(iv) };
  }


  /* ── ② 설문 (생성된 것) ─────────────────────────────────── */
  async function phase3() {
    const d = await api(`/api/projects/${pid}/ask`);
    const qs = d.questions || [];
    body.textContent = "";

    const s = section("2", "설문", "레포를 읽고 만든 질문입니다 — 추천이 미리 골라져 있습니다");
    if (!qs.length) {
      s.appendChild(el("div", "empty", "질문을 만들지 못했습니다. 그냥 진행해도 됩니다."));
    }
    for (const q of qs) {
      answers[q.key] = q.recommended;      // ★ 추천을 미리 고른 상태로 연다
      const box = el("div", "squest");
      const lb = el("div", "squest-lb");
      lb.textContent = q.label;
      box.appendChild(lb);
      if (q.hint) box.appendChild(el("div", "squest-hint", q.hint));

      const row = el("div", "sopts");
      /* ★ 고르면 어떻게 되는지를 바로 아래 보여 준다.
       * "20분" 만 있으면 못 고른다. "20분 — 약 40장 · 영상 6개 전부" 여야 고른다. */
      const eff = el("div", "sopt-eff");
      const showEff = (o) => {
        eff.textContent = "";
        if (!o || !o.effect) { eff.hidden = true; return; }
        eff.hidden = false;
        eff.append(icon("arrowRight", 11), el("span", null, o.effect));
      };
      for (const o of q.options) {
        const b = el("button", "sopt" + (o.value === q.recommended ? " on" : ""));
        b.type = "button";
        b.append(el("span", null, o.label));
        if (o.value === q.recommended) b.appendChild(el("i", "sopt-rec", "추천"));
        b.onmouseenter = () => showEff(o);
        b.onmouseleave = () => showEff(q.options.find((x) => x.value === answers[q.key]));
        b.onclick = () => {
          answers[q.key] = o.value;
          row.querySelectorAll(".sopt").forEach((x, i) =>
            x.classList.toggle("on", q.options[i].value === o.value));
          showEff(o);
          drawFoot();
        };
        row.appendChild(b);
      }
      box.appendChild(row);
      box.appendChild(eff);
      showEff(q.options.find((x) => x.value === q.recommended));

      // ★ 왜 그걸 추천하는지 — 레포에서 가져온 근거. 이게 없으면 그냥 기본값이다.
      if (q.why) {
        const w = el("div", "squest-why");
        w.append(icon("check", 11), el("span", null, q.why));
        box.appendChild(w);
      }

      const free = el("input", "sfree");
      free.type = "text";
      free.placeholder = "보기에 없으면 직접 쓰세요";
      free.oninput = () => {
        if (free.value.trim()) {
          answers[q.key] = free.value.trim();
          row.querySelectorAll(".sopt").forEach((x) => x.classList.remove("on"));
        } else {
          answers[q.key] = q.recommended;
          row.querySelectorAll(".sopt").forEach((x, i) =>
            x.classList.toggle("on", q.options[i].value === q.recommended));
        }
        drawFoot();
      };
      box.appendChild(free);
      s.appendChild(box);
    }
    body.appendChild(s);

    const foot = el("div", "sfoot");
    const note = el("div", "sfoot-note");
    const go = el("button", "btn primary lg");
    go.type = "button";
    go.append(icon("wand", 15), el("span", null, "이대로 기획서 만들기"));
    go.onclick = finish;
    foot.append(note, go);
    body.appendChild(foot);

    function drawFoot() {
      const changed = qs.filter((q) => answers[q.key] !== q.recommended).length;
      note.textContent = changed
        ? `${changed}개 고쳤습니다.`
        : "추천 그대로 갑니다. 마음에 안 드는 것만 눌러 바꾸세요.";
    }
    drawFoot();

    async function finish() {
      go.disabled = true;
      const lb = go.querySelector("span");
      const tk = ticker((s) => { lb.textContent = s; });
      note.textContent = "레포를 읽고 기획서를 씁니다 — 2~3분 걸립니다. 창을 닫아도 계속 돕니다.";
      try {
        await api(`/api/projects/${pid}/brief`, {method: "POST", body: {answers}});
        tk.stop();          // 아래 runner 가 시계를 이어받는다
        const ok = await runSteps(["s0-prd"], {btn: go, label: lb,
                                              names: {"s0-prd": "기획서"}});
        if (!ok) throw new Error("기획서를 만들지 못했습니다");
        toast("기획서가 나왔습니다. 00_기획/prd.md 를 고치면 그게 이깁니다.");
        navigate("/board");
      } catch (e) {
        tk.stop();
        toast("기획서를 만들지 못했습니다: " + e.message, "err");
        go.disabled = false;
        lb.textContent = "이대로 기획서 만들기";
        drawFoot();
      }
    }
  }

  function section(n, title, sub) {
    const s = el("section", "ssec");
    const h = el("div", "ssec-hd");
    h.append(el("span", "ssec-n", n), el("h3", null, title),
             el("span", "ssec-sub", sub));
    s.appendChild(h);
    return s;
  }
}
