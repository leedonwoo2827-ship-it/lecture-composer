/* 덱 — 편집 화면. 보기가 둘이다.
 *
 *   전체   37줄을 세로로 훑는다. 순서·누락을 보는 용도.
 *   번호   그 장 **하나만** 크게. 실제 슬라이드 면 + 자막 + 발음이 한 화면에 온다.
 *
 * 세로 한 판으로만 두면 10장 넘어가는 순간 관리가 안 된다(실측). 그래서 상단에
 * `전체 · 1 · 2 · … · 37` 번호 탭을 두고, 고칠 때는 한 장으로 들어간다.
 *
 * 레인(섹션)은 탭을 따로 만들지 않는다. 번호 칩의 색 점이 갈래를 말해 주고,
 * 발표는 어차피 1→37 순서로 흐르므로 **번호가 유일한 축**이다.
 *
 * 슬라이드 실물은 iframe 으로 `/preview/{pid}#{no}` 를 띄운다 — 렌더러가 하나뿐이라
 * 편집 화면에서 보는 것과 최종 산출물이 같은 코드에서 나온다. 미리보기용 축소판을
 * 따로 그리면 둘이 갈라지고, 갈라지면 여기서 OK 한 것이 산출물에서 깨진다.
 *
 * 여기가 바닥인 이유: 자막·발음 입력창이 있다. 패널은 Esc·스크림으로 닫히므로
 * 타이핑하던 내용이 날아간다 — 미저장 텍스트는 패널 금지.
 */
"use strict";


import { $, el, api, icon, toast, debounce, fitFrame } from "./util.js";
import { state } from "./store.js";
import { navigate } from "./shell.js";
import { videoEditor as ved } from "./videoedit.js";
import { runSteps } from "./runner.js";
import { stepBadge, DECK } from "./steps.js";
import { storyboard } from "./storyboard.js";
import { panel as dictPanel } from "./dict.js";

/* ★ 손편집의 키는 **원래 번호(src_no)** 다.
 *
 * 장을 하나 빼면 조립이 1부터 번호를 다시 매긴다. 그런데 오버라이드 파일은
 * 구조(S2b)가 매긴 원래 번호로 읽힌다 — 화면에 보이는 번호로 저장하면 뺀 장
 * 뒤부터 **한 칸씩 밀려서 엉뚱한 장이 고쳐진다.** 아직 아무도 안 뺐을 때만
 * 우연히 맞는다. 그래서 저장은 언제나 src_no 로 한다.
 */
const okey = (s) => String(s.src_no != null ? s.src_no : s.no);

export const meta = {
  title: "덱 — 음성 · 자막",
  subtitle: "맨 마지막에 음성과 자막을 한 번 더 봅니다. 문구·그림·영상은 각 화면에서",
  /* 실행기를 둘로 나눈다 —
   *   HTML 보기 : 지금 상태로 슬라이드 면을 연다. 미완성이어도 열린다.
   *   최종 굽기 : 음성 합성 + 자막 + 파일 빌드. 오래 걸리고 돈이 든다.
   * 둘을 한 버튼에 두면 "그냥 보고 싶을 뿐인데" 매번 굽게 된다. */
  actions: () => {
    /* ★ 슬라이드 보기 하나면 된다.
     *
     * 예전엔 "슬라이드 보기" 와 "전체 자동 재생" 두 개였다. 하는 일은 같고
     * ?auto=1 이 붙느냐만 달라서, 화면에서는 같은 버튼 두 개로 보였다.
     * 자동은 슬라이드 페이지 안의 단추로 켠다 — 거기서 켜는 게 맞다.
     * 보다가 "이제 자동으로 넘겨 보자" 가 되지, 열기 전에 정해지는 게 아니다. */
    const view = el("a", "btn");
    view.href = "/preview/" + (state.projectId || 0);
    view.target = "_blank";
    view.rel = "noopener";
    view.title = "새 탭에서 엽니다 — 왼쪽 아래 단추로 자동 재생을 켤 수 있습니다";
    view.append(icon("slide", 14), el("span", null, "슬라이드 보기"));

    /* ★ SME(전문가)에게 보낼 자료 — 장마다 [화면 | 읽는 말]을 표로 훑는
     * 인쇄본이다. 브라우저 인쇄(Ctrl+P)로 PDF 저장하면 그대로 보낼 수 있다.
     * 슬라이드 보기 옆에 둔다 — "이제 검토받으러 보내자" 가 되는 자리가 같다. */
    const print = el("a", "btn");
    print.href = "/print/" + (state.projectId || 0);
    print.target = "_blank";
    print.rel = "noopener";
    print.title = "새 탭에서 엽니다 — Ctrl+P 로 PDF 저장해 SME에게 보내세요";
    print.append(icon("printer", 14), el("span", null, "대본 인쇄본"));

    /* ★ 여기서 **실제로 굽는다.** 예전엔 이 버튼이 현황판을 열기만 했다 —
     * 이름은 "최종 굽기" 인데 아무것도 굽지 않으니 버튼을 못 찾은 것으로 읽혔다.
     * 대본 → 음성 → 자막 → 조립 → 렌더를 순서대로 돌린다. */
    /* ★ 두 걸음으로 나눈다 — 순서대로 누른다.
     *
     *   ① 발음대본 생성   글 → 읽는 말. 여기서 문장이 바뀐다(돈이 든다)
     *   ② 음성/자막 굽기  그 대본으로 음성·자막·완성본을 만든다
     *
     * 한 버튼에 묶어 두면 자막 오타 하나 고치려 해도 대본이 통째로 다시
     * 생성돼서 손본 문장이 날아간다. 실제로 그게 제일 아픈 사고다. */
    /* 배경음악 — 굽기 **전에** 정해지는 값이라 굽기 버튼 옆에 둔다.
     * 완성본 카드 안에 두면 한 번이라도 구운 프로젝트에서만 보여서, 정작
     * 처음 굽기 전에는 고를 수가 없다. */
    /* ★ 번호를 붙인다(2026-08-14). 버튼 이름은 **행동**을 말하고
     * (「발음대본 생성」) 오른쪽 이력은 **산출물**을 말해서(「내레이션 대본」),
     * 같은 일인지 다른 일인지가 안 읽혔다 — "지금이 3번 할 타이밍인가 4번 할
     * 타이밍인가" 가 늘 남았다. 이름은 그대로 두고 번호가 둘을 잇는다.
     * 번호표의 원본은 `core/steps.py` 다 — 이력 줄은 서버가 번호를 실어 보내고,
     * 여기 넷은 누르기 전이라 받아 올 이력이 없어 steps.js 의 DECK 를 쓴다. */
    const bgm = bgmButton();
    bgm.prepend(stepBadge(DECK.bgm, "배경음악 — 굽기 전에 정합니다. 안 넣어도 됩니다"));

    const [sBtn, sLab] = mkRun(DECK.script, "자막 대본 생성",
                               "화면에 보이는 원문 — 여기서 글이 정해집니다");

    /* ★ **자막과 발음을 가른다**(2026-08-17). 손이 가는 순서가 「자막을 읽고
     * 고친다 → 그 자막대로 발음을 만든다」이기 때문이다. 한 번에 만들면 자막을
     * 고쳐도 발음은 옛 자막에서 나온 채로 남는다 — 20장 2장에서 실제로 그랬다.
     * 스테이지가 아니라 창구를 부른다. Claude 를 안 부르는 결정론이라 공짜이고
     * 몇 초다 — 자막을 고칠 때마다 다시 눌러도 손해가 없다. */
    const [pBtn, pLab] = mkRun(DECK.speech, "발음 대본 생성",
                               "그 자막을 소리 나는 대로 — 괄호 · 어미 · 숫자 · 퍼센트");

    /* ★ 영문을 소리대로 — **덱 전체.** 「발음 대본 생성」과 갈라 두는 이유가 이
     * 버튼의 전부다: 그쪽은 자막에서 다시 만들어 손으로 고쳐 둔 발음을 지운다.
     * 여기는 지금 발음 칸에 있는 글에 영문 변환만 얹으므로 손편집이 살아남는다.
     * 표는 `voicewright/config/pronunciation_map.yaml` 하나다(`/dict` 화면에서 편집).
     * ★ 바꾼 뒤 **굽기까지 이어 돈다** — 발음이 바뀌면 음성은 어차피 다시 만들어야 한다. */
    /* ★ 사전을 여는 자리. 「영문을 소리대로」 **바로 앞**에 둔다 — 순서가 그렇다:
     * 사전을 채우고, 그다음 덱에 적용한다. 사전이 비어 있으면 적용해 봐야
     * `DECODE` 가 「디이씨오디이」로 나간다(2026-08-23 실측). */
    const dictBtn = el("a", "btn sm");
    dictBtn.href = "#/dict";
    dictBtn.target = "_blank";
    dictBtn.rel = "noopener";
    dictBtn.append(icon("book", 13), el("span", null, "발음 사전"));
    dictBtn.title = `영문을 한국어 소리로 읽는 표를 고칩니다
이 덱에 나오는데 사전에 없는 영문을 함께 보여 줍니다
넣고 저장한 뒤 «영문을 소리대로» 를 누르세요`;

    const eBtn = el("button", "btn sm");
    eBtn.type = "button";
    const eLab = el("span", null, "영문을 소리대로 (전체)");
    eBtn.append(icon("wand", 13), eLab);
    eBtn.title = `FROM → 프롬 · GROUP BY → 그룹 바이 · NULL → 널
손으로 고쳐 둔 발음은 그대로 둡니다 — 영문만 바꿉니다
바꾼 뒤 음성·자막·완성본까지 이어서 굽습니다`;

    const [bBtn, bLab] = mkRun(DECK.bake, "음성/자막 굽기", "음성 합성 · 자막 · 조립 · 파일 빌드");
    bBtn.classList.add("primary");

    const rBtn = el("button", "btn sm ghost");
    rBtn.type = "button";
    const rLab = el("span", null, "음성 빼고 굽기");
    rBtn.append(icon("refresh", 13), rLab);
    /* ★ 여러 줄 툴팁은 **역따옴표**로 쓴다. 큰따옴표 안의 `\n` 은 편집기·포매터가
       실제 줄바꿈으로 풀어 놓으면 그 자리에서 문법이 깨진다 — 2026-08-17 에
       덱 화면이 통째로 「Invalid or unexpected token」으로 안 떴다.
       역따옴표는 줄바꿈이 들어가도 그대로 유효하다. */
    rBtn.title = `자막 시각 · 덱 조립 · 완성본만 다시 만듭니다
장별로 «발음대로 다시 합성» 을 이미 눌러 두셨을 때 쓰세요
★ 음성을 안 건드립니다 — 듣고 OK 한 소리가 그대로 남습니다`;

    /* ★ **발음 교정표.** 장별듣기가 끝난 자리에 둔다 — 손편집이 다 끝난
     * 시점이 여기다. 더 앞에서 뽑으면 아직 안 고친 장이 빠지고, 더 뒤(영상을
     * 구운 뒤)에서 뽑으면 이미 늦어 다음 과목에 못 쓴다.
     *
     * 무엇을 위한 파일인가: 발음 규칙은 코드에 있지만(`core/honorific.py`)
     * **예외는 이 폴더에만** 있다(`Q1 → 큐원` · `m1 → 엠원`). 대본 쓰는 사람이
     * 그것을 모르면 다음 과목에서 같은 발음을 또 손으로 고치게 된다.
     *
     * 굽는 버튼들과 함께 잠그지 않는다 — 파일 하나 읽어 쓰는 일이라 잡과
     * 부딪히지 않고, 굽는 동안 표를 뽑아 보내고 싶을 때가 실제로 있다. */
    const dBtn = el("button", "btn sm ghost");
    dBtn.type = "button";
    const dLab = el("span", null, "발음 교정표");
    dBtn.append(icon("printer", 13), dLab);
    dBtn.title = `손으로 고친 발음만 낱말 표로 뽑아 08_자막 에 냅니다
대본·문제 쓰는 분께 넘기면 애초에 읽히는 대로 써 옵니다
★ 장별듣기를 끝낸 뒤에 누르세요 — 그때가 손편집이 다 끝난 시점입니다`;
    dBtn.onclick = () => pronounceReport(dBtn, dLab);

    /* ★ 7번(영상)은 **여기 두지 않는다**(2026-08-14). 영상 만들기는 화면이
     * 따로 있다(`/mp4`) — 거기서 장마다 찍어 mp4 로 굽는다(S12).
     * 여기 버튼을 남겨 두면 같은 일을 하는 자리가 둘이 되고, 무엇보다 **6번이
     * 끝나기 전에 눌러도 눌리는** 자리가 된다. 대신 6번이 끝났을 때 "이제 저기로
     * 가면 된다" 는 안내만 띄운다. */
    const next = el("button", "bakenext");
    next.type = "button";
    next.hidden = true;
    next.append(el("span", null, "완성본이 준비됐습니다 — 영상 렌더링으로"),
                icon("chevronRight", 13));
    next.onclick = () => navigate("/mp4");

    /* ★ 굽는 단계는 **한 번에 하나만.** 한 잡이 도는 동안 다른 버튼이 멀쩡히
     * 눌리면 같은 산출물에 잡 둘이 동시에 손을 대 꼬인다 — 실제로 겪은 사고다
     * (2026-08-13). 눌린 버튼만 시계를 보여 주고, 나머지 셋(배경음악 포함)은
     * 도는 동안 통째로 잠근다 — `disabled` 라 커서도 자동으로 손모양이 빠진다. */
    sBtn.onclick = () => runChain(SCRIPT, sBtn, sLab, [bgm, pBtn, bBtn],
                                  "자막 대본 생성", "자막이 나왔습니다");
    pBtn.onclick = () => pronounceAll(pBtn, pLab, [bgm, sBtn, bBtn]);
    eBtn.onclick = () => romanAll(eBtn, eLab, [bgm, sBtn, pBtn, bBtn], bBtn, bLab);
    bBtn.onclick = () => runChain(BAKE, bBtn, bLab, [bgm, sBtn, pBtn, rBtn],
                                  "음성/자막 굽기", "완성본이 나왔습니다");
    rBtn.onclick = () => runChain(RESUB, rBtn, rLab, [bgm, sBtn, pBtn, bBtn],
                                  "음성 빼고 굽기", "자막·완성본을 다시 만들었습니다");

    /* ★ **낡았는지를 버튼이 말해야 한다.** 슬라이드를 고쳐 놓고 안 구운 채로
     * 발표하러 가는 것이 이 앱에서 제일 비싼 실수다. */
    const chip = el("span", "bakechip");
    chip.hidden = true;
    const mark = () => markBake(chip, sBtn, sLab, pBtn, pLab, bBtn, bLab, next);
    mark();
    window.addEventListener("focus", mark);

    return [view, print, bgm, sBtn, pBtn, dictBtn, eBtn, chip, bBtn, rBtn, dBtn, next];
  },
};

const AUDIO_TYPES = "audio/mpeg,audio/mp4,audio/ogg,audio/wav,.mp3,.m4a,.ogg,.wav";

/** ♪ 배경음악 — 없으면 고르게 하고, 있으면 곡 이름을 보여 주고 다시 누르면 뺀다.
 *
 * ★ 파일은 **프로젝트 안으로 복사된다.** 그래야 폴더째 옮겨도 따라온다.
 *   넣고 나면 완성본 렌더가 낡으므로, 옆의 굽기 칩이 알아서 "다시 구우세요" 를
 *   띄운다 — 여기서 따로 안내하지 않는다. */
function bgmButton() {
  const b = el("button", "btn");
  b.type = "button";
  const lb = el("span", null, "배경음악");
  b.append(el("span", "bgm-note", "♪"), lb);

  const input = el("input");
  input.type = "file";
  input.accept = AUDIO_TYPES;
  input.hidden = true;
  b.appendChild(input);

  let cur = null;
  const paint = () => {
    const on = !!(cur && cur.ok);
    b.classList.toggle("on", on);
    lb.textContent = on ? (cur.name || "배경음악") : "배경음악";
    b.title = on
      ? `${cur.name} — 눌러서 바꾸기, 오래 누르면 빼기. 넣은 뒤 다시 구워야 완성본에 들어갑니다`
      : "완성본에 깔 배경음악을 고릅니다 (mp3·m4a·wav)";
  };
  paint();

  api(`/api/projects/${state.projectId}/bgm`)
    .then((r) => { cur = r; paint(); })
    .catch(() => { /* 아직 없음 */ });

  b.onclick = () => input.click();
  // 뺄 길이 하나는 있어야 한다 — 우클릭이 제일 안 걸리적거린다
  b.oncontextmenu = async (e) => {
    e.preventDefault();
    if (!(cur && cur.ok)) return;
    try {
      await api(`/api/projects/${state.projectId}/bgm`, {method: "DELETE"});
      cur = null; paint();
      toast("배경음악을 뺐습니다 — 다시 구우세요");
    } catch (err) { toast("빼지 못했습니다: " + err.message, "err"); }
  };

  input.onchange = async () => {
    const f = input.files[0];
    input.value = "";
    if (!f) return;
    if (f.size > 12e6) { toast("12MB 를 넘습니다", "err"); return; }
    b.disabled = true;
    try {
      const data_url = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result);
        r.onerror = rej;
        r.readAsDataURL(f);
      });
      const r = await api(`/api/projects/${state.projectId}/bgm`,
                          {method: "POST", body: {data_url, name: f.name}});
      cur = {ok: true, name: r.name}; paint();
      toast(`${r.name} — 다시 구우면 완성본에 깔립니다`);
    } catch (err) {
      toast("넣지 못했습니다: " + err.message, "err");
    } finally {
      b.disabled = false;
    }
  };
  return b;
}

/* 순서가 곧 규칙이다 — ① 대본을 만들고 ② 그 대본으로 굽는다. */
const SCRIPT = ["s6-script"];
const BAKE = ["s10-tts", "s11-audio", "s8-assemble", "s9-render"];
/* ★ **음성을 뺀 굽기.** 장별로 「발음대로 다시 합성」을 눌러 소리를 이미 다
 * 만들어 둔 뒤에 쓴다 — 그때 필요한 것은 자막 시각을 다시 잡고 다시 조립하는
 * 것뿐이다(`synth_one` 이 s10 캐시의 그 칸을 이미 고쳐 놨다).
 * 전체 굽기를 누르면 34장을 새로 합성하는데, TTS 는 같은 글도 매번 다르게
 * 읽어서(3.73 / 3.59 / 3.55초) **듣고 OK 한 소리가 다른 소리로 바뀐다.**
 * 예전에는 이 셋을 현황판에서 하나씩 눌러야 했다(2026-08-17). */
const RESUB = ["s11-audio", "s8-assemble", "s9-render"];
/* 7번(영상)은 이 화면에 없다 — `/mp4` 가 맡는다(S12). */
const BAKE_KO = {
  "s6-script": "발음대본", "s10-tts": "음성 합성", "s11-audio": "자막",
  "s8-assemble": "조립", "s9-render": "파일 빌드", "s12-video": "영상 렌더",
};

function mkRun(n, name, tip) {
  const b = el("button", "btn");
  b.type = "button";
  b.title = `${n}. ${tip} — 몇 분 걸립니다`;
  const l = el("span", null, `(전체) ${name}`);
  // 번호가 맨 앞이다 — 눈이 왼쪽에서 오른쪽으로 훑으며 순서를 읽는다.
  b.append(stepBadge(n, tip), icon("wand", 14), l);
  return [b, l];
}

/* 낡았는지를 **버튼 이름이** 말한다. 칩은 무엇 때문에 낡았는지를 말한다.
 *
 * ★ 오른쪽 서랍(최근 한 일)과 **같은 곳을 읽는다**(`/activity`). 예전에는 여기가
 *   스테이지 입력 해시(`/stages`)를 보고, 서랍은 시각을 봤다 — 그래서 한 화면
 *   안에서 칩은 "낡았습니다", 서랍은 "다시 할 것 0건" 이라고 서로 다른 말을 했다
 *   (2026-08-14 실측). 무엇을 믿어야 할지 알 수 없으면 둘 다 안 믿게 된다.
 *   판정은 한 곳에서만 한다 — 「덱보다 앞선 것이 지금 완성작보다 나중에 고쳐졌나」.
 */
async function markBake(chip, sBtn, sLab, pBtn, pLab, bBtn, bLab, next) {
  if (!state.projectId) return;
  let a = null;
  try { a = await api(`/api/projects/${state.projectId}/activity`); }
  catch { return; }

  const ran = new Set((a.done || []).map((r) => r.n).filter(Boolean));
  const old = new Map((a.todo || []).map((t) => [t.n, t]));

  const put = (btn, lab, name, n) => {
    btn.classList.remove("warn");
    if (!ran.has(n)) { lab.textContent = `(전체) ${name}`; return "안 함"; }
    // 이미 한 번 돌았으면 "다시" 다. 낡았으면 버튼이 주황으로 재촉한다.
    lab.textContent = `(전체) ${name} 다시`;
    const t = old.get(n);
    if (t) btn.classList.add("warn");
    return t ? `${n}. ${t.label}${t.why ? ` (${t.why} 뒤)` : ""}` : "";
  };

  const s5 = put(sBtn, sLab, "자막 대본 생성", DECK.script);
  const s6 = put(pBtn, pLab, "발음 대본 생성", DECK.speech);
  const s7 = put(bBtn, bLab, "음성/자막 굽기", DECK.bake);

  /* 6번이 **다 끝났을 때만** 다음 자리를 안내한다. 끝나기 전에 보이면 "지금
     눌러도 되나" 를 생각하게 되고, 눌러 보면 아직 아무것도 없다. */
  if (next) next.hidden = !(ran.has(DECK.bake) && !old.has(DECK.bake));

  chip.hidden = false;
  const stale = [s5, s6, s7].filter((x) => x && x !== "안 함");
  if (s5 === "안 함" || s7 === "안 함") {
    chip.className = "bakechip";
    chip.textContent = "아직 안 구웠습니다";
  } else if (stale.length) {
    chip.className = "bakechip old";
    chip.textContent = `${stale.join(" · ")} 이 낡았습니다`;
  } else {
    chip.className = "bakechip ok";
    chip.textContent = "완성본이 지금 슬라이드와 같습니다";
  }
}

/* 덱 전체의 발음 대본을 지금 자막에서 다시 만든다.
 *
 * ★ 스테이지가 아니라 창구다 — Claude 를 안 부르는 결정론이라 몇 초다.
 *   그래서 `runSteps` 의 시계·로그를 붙이지 않는다. 몇 분 걸리는 것과 몇 초
 *   걸리는 것에 같은 옷을 입히면, 사람이 「이것도 오래 걸리나」로 읽는다.
 *
 * ★ **덮기 전에 무엇이 사라지는지 말한다.** 손으로 고쳐 둔 발음이 있는 장을
 *   먼저 세어 보여 주고 묻는다. 이 앱에서 조용히 덮은 적이 있고(시각 186개),
 *   그 뒤로는 늘 먼저 말한다.
 */
/* 교정표를 내고 그 폴더를 연다.

   ★ **만들었다는 말만 하지 않고 폴더를 연다.** 산출물은 앱 밖에 살고 경로도
     길어서, 글로 알려 주면 사람이 탐색기를 직접 찾아 들어가야 한다
     (`이미지 JSON 만들기` 가 같은 이유로 그렇게 한다). */
async function pronounceReport(btn, label) {
  const was = label.textContent;
  btn.disabled = true;
  label.textContent = "뽑는 중…";
  try {
    const r = await api(`/api/projects/${state.projectId}/pronounce-report`,
                        {method: "POST"});
    toast(r.hand
      ? `손으로 고친 발음 ${r.hand}장 → 08_자막/발음교정표.txt`
      : "손으로 고친 발음이 없어 표가 비었습니다");
    await api(`/api/projects/${state.projectId}/reveal?step=subtitle`,
              {method: "POST", body: {}})
      .catch(() => { /* 폴더를 못 열어도 파일은 이미 나왔다 */ });
  } catch (e) {
    toast("뽑지 못했습니다: " + e.message, "err");
  } finally {
    label.textContent = was;
    btn.disabled = false;
  }
}

/* 덱 전체의 영문을 소리대로 바꾸고, 이어서 굽는다.

   ★ 먼저 **몇 장이 바뀌는지 보여 주고 묻는다.** 발음을 통째로 건드리는 일이라,
     누른 사람이 규모를 모르고 시작하면 안 된다(`pronounceAll` 과 같은 이유). */
async function romanAll(btn, label, group, bakeBtn, bakeLab) {
  const lock = (v) => { btn.disabled = v; group.forEach((g) => { g.disabled = v; }); };
  const was = label.textContent;
  lock(true);
  try {
    const p = await api(`/api/projects/${state.projectId}/speak-roman-all`,
                        {method: "POST"});
    if (!p.changed) { toast("바꿀 영문이 없습니다 — 이미 전부 소리대로입니다"); return; }
    /* ★ 줄바꿈은 **역따옴표 안의 실제 줄바꿈**으로 쓴다. 큰따옴표 안에 역슬래시 n 을
       쓰면, 이 파일을 스크립트로 고칠 때 그것이 실제 줄바꿈으로 풀려 문자열이 두 줄로
       갈라지고 덱 화면이 통째로 「Invalid or unexpected token」이 된다 — 2026-08-17 과
       08-23, 같은 자리에서 두 번 겪었다. 역따옴표 안에서는 줄바꿈이 그대로 유효하다. */
    const eg = (p.sample || []).map((s) => `  ${s.no}장  ${s.text}…`).join(`
`);
    const msg = `${p.n}장 가운데 ${p.changed}장의 영문이 소리로 바뀝니다.

${eg}

손으로 고쳐 둔 발음은 그대로 둡니다. 자막도 안 바뀝니다.
바꾼 뒤 음성·자막·완성본까지 이어서 굽습니다. 계속할까요?`;
    if (!confirm(msg)) return;
    label.textContent = "바꾸는 중…";
    const r = await api(
      `/api/projects/${state.projectId}/speak-roman-all?apply=true`, {method: "POST"});
    toast(`${r.changed}장의 영문을 소리대로 바꿨습니다 — 이제 굽습니다`);
    label.textContent = was;
    lock(false);
    // ★ 굽기는 **그 버튼에 맡긴다.** 잡을 돌리는 자리가 둘이 되면 진행 표시와
    //   잠금이 갈려서, 도는 동안 다른 버튼이 멀쩡히 눌린다(2026-08-13 사고).
    await runChain(BAKE, bakeBtn, bakeLab, group.concat([btn]), "음성/자막 굽기",
                   "완성본이 나왔습니다");
    return;
  } catch (e) {
    toast("바꾸지 못했습니다: " + e.message, "err");
  } finally {
    label.textContent = was;
    lock(false);
  }
}

async function pronounceAll(btn, label, group) {
  const lock = (v) => { btn.disabled = v; group.forEach((g) => { g.disabled = v; }); };
  const was = label.textContent;
  lock(true);
  try {
    const p = await api(`/api/projects/${state.projectId}/pronounce-all`,
                        {method: "POST"});
    if (!p.changed) { toast("이미 지금 자막대로입니다 — 바뀔 것이 없습니다"); return; }
    const lost = p.hand
      ? `\n\n★ 그중 ${p.hand}장은 손으로 고쳐 두신 발음입니다 — 덮입니다.`
      : "";
    const eg = (p.sample || []).map((s) => `  ${s.no}장  ${s.text}…`).join("\n");
    if (!confirm(`${p.n}장 가운데 ${p.changed}장의 발음이 바뀝니다.${lost}\n\n`
                 + `${eg}\n\n자막은 건드리지 않습니다. 계속할까요?`)) return;
    label.textContent = "만드는 중…";
    const r = await api(
      `/api/projects/${state.projectId}/pronounce-all?apply=true`, {method: "POST"});
    toast(`${r.changed}장의 발음 대본을 다시 만들었습니다`
          + (r.hand ? ` (손편집 ${r.hand}장 덮음)` : "")
          + " — 이제 «음성/자막 굽기»");
    location.reload();
  } catch (e) {
    toast("만들지 못했습니다: " + e.message, "err");
  } finally {
    label.textContent = was;
    lock(false);
  }
}

async function runChain(keys, btn, label, group, name, doneMsg) {
  const ok = await runSteps(keys, {
    btn, label, group, names: BAKE_KO,
    onDone: async () => {
      toast(doneMsg);
      // ★ 다 구웠으면 **그 폴더를 열어 준다.** 경로가 길어서 글로 알려 주면
      //   사람이 복사해 붙여넣어야 한다. 로컬 앱이라 할 수 있는 일이다.
      if (keys === BAKE) await openDist(true);
      location.reload();      // 자막·음성이 붙은 상태로 다시 그린다
    },
  });
  if (!ok) toast(`${name} 을(를) 끝내지 못했습니다`, "err");
}

const MEDIA_LABEL = {
  text: "텍스트", text_image: "화면 캡처", html: "원고 HTML",
  video: "영상", code: "코드",
};
const KIND_LABEL = {
  cover: "표지", context: "배경", feature: "기능", architecture: "구조",
  decision: "판단", metric: "수치", ops: "운영", note: "", closing: "맺음",
};
const LANE_COLORS = ["#9a4d33", "#c0714f", "#7d6a55", "#5c6b62", "#8a7f9a", "#a8894f"];
const fmt = (s) => (s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);

/** 내용만큼 늘어나는 입력칸 — 스크롤바가 생기면 전체가 안 보인다 */
function autoSize(t) {
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight + 2, 320) + "px";
}

export async function mount(root, ctx) {
  const page = el("div", "page");
  root.appendChild(page);

  if (!state.projectId) {
    page.appendChild(el("div", "empty", "먼저 프로젝트를 고르세요."));
    return;
  }

  let d;
  try {
    d = await api(`/api/projects/${state.projectId}/deck`);
  } catch (e) {
    page.appendChild(el("div", "empty", "읽지 못했습니다: " + e.message));
    return;
  }

  if (!d.ready) {
    const box = el("div", "empty");
    box.appendChild(el("p", null, "아직 덱 구조가 없습니다."));
    box.appendChild(el("p", null, "현황판에서 '구조 설계' 를 돌리면 장 예산만큼 짜입니다."));
    const b = el("button", "btn primary");
    b.type = "button";
    b.append(icon("wand", 14), el("span", null, "현황판 열기"));
    b.onclick = () => navigate("/board");
    page.appendChild(box);
    return;
  }

  // 뺀 장은 발표에 안 나가므로 여기서도 안 보인다
  const slides = (d.slides || []).filter((s) => !s.drop);
  const sections = d.sections || [];
  const laneIdx = Object.fromEntries(sections.map((s, i) => [s.id, i]));
  const laneName = Object.fromEntries(sections.map((s) => [s.id, s.title]));
  const laneColor = (s) => LANE_COLORS[(laneIdx[s.section] ?? 0) % LANE_COLORS.length];
  const byNo = Object.fromEntries(slides.map((s) => [s.no, s]));

  // ── 손편집 저장 ──
  const pending = { slides: {} };
  const flush = debounce(async () => {
    const patch = { slides: pending.slides };
    pending.slides = {};
    try {
      await api(`/api/projects/${state.projectId}/overrides`,
                { method: "POST", body: { patch } });
    } catch (e) { toast("저장 실패: " + e.message, "err"); }
  }, 600);

  function edit(no, path, value) {
    const s = (pending.slides[String(no)] ||= {});
    if (path.length === 1) s[path[0]] = value;
    else (s[path[0]] ||= {})[path[1]] = value;
    flush();
  }

  await distCard(page);

  // ── 머리 ──
  const hd = el("div", "deck-head");
  hd.appendChild(el("h2", null, d.deck_title || ""));
  if (d.deck_subtitle) hd.appendChild(el("p", "deck-sub", d.deck_subtitle));

  /* 번호 탭 — 전체 + 1..N. 색 점이 레인이다.
   * 레인별 탭을 따로 두지 않는 이유: 발표는 1→N 한 줄로 흐르고, 고칠 때 찾는 기준도
   * "몇 번째 장" 이지 "무슨 갈래" 가 아니다. 갈래는 점 색으로 충분하다. */
  const strip = el("div", "numstrip");
  const allChip = el("button", "num-chip all");
  allChip.type = "button";
  allChip.textContent = "전체";
  allChip.onclick = () => show(null);
  strip.appendChild(allChip);

  /* ★ 유형 필터 — 사이드바의 유형과 **같은 축**이다.
   * "그림 넣을 장만 훑기" 같은 일이 실제로 많다. 유형을 고르면 번호 탭도 그 유형만 남는다. */
  const KINDS = [["text", "텍스트"], ["html", "+원고"], ["text_image", "+이미지"],
               ["thumb", "+썸네일"],
                 ["video", "+영상"], ["code", "+코드"]];
  const kindRow = el("div", "kindrow");
  let kindFilter = null;
  const kindChips = [];
  const allKind = el("button", "kind-chip on");
  allKind.type = "button";
  allKind.textContent = "모든 유형";
  allKind.onclick = () => setKind(null);
  kindRow.appendChild(allKind);
  kindChips.push([null, allKind]);
  for (const [k, label] of KINDS) {
    const n = slides.filter((s) => s.media_kind === k).length;
    if (!n) continue;
    const c = el("button", "kind-chip");
    c.type = "button";
    c.append(el("span", null, label), el("b", null, String(n)));
    c.onclick = () => setKind(k);
    kindRow.appendChild(c);
    kindChips.push([k, c]);
  }
  if (kindChips.length > 2) hd.appendChild(kindRow);

  function setKind(k) {
    kindFilter = k;
    for (const [key, c] of kindChips) c.classList.toggle("on", key === k);
    for (const [no, chip] of Object.entries(numChips)) {
      chip.hidden = !!k && byNo[no].media_kind !== k;
    }
    // 유형을 걸면 번호 탭이 그 유형만 남는다 — 37개 중 8개를 눈으로 찾지 않는다
    const n = k ? slides.filter((s) => s.media_kind === k).length : slides.length;
    allKind.textContent = k ? `${n}장만 보는 중 · 전체로` : "모든 유형";
    if (cur == null) show(null);
    else if (k && byNo[cur] && byNo[cur].media_kind !== k) {
      const first = slides.find((s) => s.media_kind === k);
      if (first) show(first.no);
    }
  }

  const numChips = {};
  for (const s of slides) {
    const c = el("button", "num-chip");
    c.type = "button";
    c.dataset.no = String(s.no);
    c.style.setProperty("--lane", laneColor(s));
    c.append(el("i", "num-dot"), el("span", null, String(s.no)));
    c.title = `${s.no}. ${s.title || ""}\n${laneName[s.section] || ""}`;
    c.onclick = () => show(s.no);
    strip.appendChild(c);
    numChips[s.no] = c;
  }
  hd.appendChild(strip);
  page.appendChild(hd);

  /* 승인 게이트 3단 — 어디까지 봤는지를 슬라이드마다 남긴다.
   *
   *   1차 화면   슬라이드 면이 이대로 나가도 되는가
   *   2차 대본   자막·발음이 이대로 읽혀도 되는가
   *   3차 무음   (영상 장만) 원본 소리를 죽이고 내레이션만 얹어도 되는가
   *
   * 37장을 한 번에 다 볼 수 없으니 어디까지 봤는지가 남아야 한다. 저장은
   * 오버라이드 파일이라 스테이지를 다시 돌려도 살아남는다. */
  const GATES = [["slide", "화면"], ["script", "대본"], ["mute", "무음"]];

  /* ★ 전체가 몇 분인지 — 발표에서 이게 제일 먼저 묻는 질문이다.
   *
   * 실제 wav 길이가 있으면 그것을, 없으면 대본 추정치를 쓴다. 둘을 구분해서
   * 보여 준다 — "7분" 이 실측인지 추정인지 모르면 그 숫자를 못 믿는다.
   * 목표 길이를 정해 두면 남거나 모자란 만큼을 바로 보여 준다.
   */
  // ★ 15 분 — 강의 한 편이 **15분 이상 20분 이하**로 나와야 하는 판이 있다
  //   (2026-08-17). 10 과 20 사이가 비어 있어 목표를 못 짚었다.
  const LENGTHS = [10, 15, 20, 30, 40, 60, 120];
  const totals = () => {
    let real = 0, est = 0, nReal = 0;
    for (const s of slides) {
      const n = s.narration || {}, a = s.audio || {};
      if (a.sec) { real += a.sec; nReal++; } else { est += n.est_sec || 0; }
    }
    return {sec: real + est, real, est, nReal};
  };
  const mmss = (s) => `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초`;

  const clock = el("div", "clock");
  hd.appendChild(clock);
  const gauge = el("div", "gate-gauge");

  let target = Number(d.target_min || 0);

  function drawClock() {
    const t = totals();
    clock.textContent = "";
    const big = el("div", "clock-big");
    big.append(el("b", null, mmss(t.sec)),
               el("span", "clock-sub",
                  `${slides.length}장 · 실측 ${t.nReal}장` +
                  (t.nReal < slides.length ? ` · 추정 ${slides.length - t.nReal}장` : "")));
    clock.appendChild(big);

    const pick = el("div", "clock-target");
    pick.appendChild(el("span", "clock-lb", "목표"));
    for (const m of LENGTHS) {
      const b = el("button", "len-chip" + (target === m ? " on" : ""));
      b.type = "button";
      b.textContent = `${m}분`;
      b.onclick = async () => {
        target = target === m ? 0 : m;
        try {
          await api(`/api/projects/${state.projectId}/overrides`,
                    {method: "POST", body: {patch: {target_min: target}}});
        } catch (e) { toast("저장 실패: " + e.message, "err"); }
        drawClock();
      };
      pick.appendChild(b);
    }
    if (target) {
      const diff = t.sec - target * 60;
      const over = diff > 0;
      const tag = el("span", "clock-diff" + (Math.abs(diff) > 60 ? (over ? " over" : " under") : " ok"));
      tag.textContent = Math.abs(diff) < 30 ? "딱 맞습니다"
        : (over ? `${mmss(diff)} 넘습니다` : `${mmss(-diff)} 모자랍니다`);
      pick.appendChild(tag);
    }
    clock.appendChild(pick);
  }
  hd.appendChild(gauge);

  function countGates() {
    const n = {slide: 0, script: 0, mute: 0}, d = {slide: 0, script: 0, mute: 0};
    for (const s of slides) {
      const a = s.approve || {};
      d.slide++; d.script++;
      if (s.video_id) d.mute++;
      for (const [k] of GATES) if (a[k]) n[k]++;
    }
    return {n, d};
  }
  function drawGauge() {
    const {n, d} = countGates();
    gauge.textContent = "";
    for (const [k, label] of GATES) {
      if (!d[k]) continue;
      const done = n[k] >= d[k];
      const c = el("span", "gate-pill" + (done ? " done" : ""));
      c.append(el("b", null, label), el("span", null, `${n[k]}/${d[k]}`));
      gauge.appendChild(c);
    }
  }

  const body = el("div", "deck-body");
  page.appendChild(body);

  let cur = null;   // null = 전체

  function show(no) {
    cur = no;
    allChip.classList.toggle("active", no == null);
    for (const [k, c] of Object.entries(numChips)) c.classList.toggle("active", String(no) === k);
    body.textContent = "";
    body.appendChild(no == null ? tableView() : focusView(byNo[no]));
    if (no != null) {
      const c = numChips[no];
      if (c) c.scrollIntoView({ block: "nearest", inline: "center" });
    }
    body.scrollIntoView({ block: "nearest" });
  }

  // ── 보기 1 · 전체 (세로 훑기) ─────────────────────────────
  /* 여기서는 고치지 않는다. 순서·누락·레인 분포를 보는 용도다.
   * 줄을 누르면 그 장의 편집 화면으로 들어간다. */
  function tableView() {
    const tbl = el("div", "deck-table");
    const hrow = el("div", "deck-row deck-th");
    hrow.append(el("span", null, "슬라이드"), el("span", null, "시각 · 길이"),
                el("span", null, "자막"), el("span", null, "미디어"));
    tbl.appendChild(hrow);

    let run = 0;
    for (const s of slides) {
      if (kindFilter && s.media_kind !== kindFilter) continue;
      const row = el("div", "deck-row deck-row-link");
      row.id = `slide-${s.no}`;
      row.style.setProperty("--lane", laneColor(s));
      row.tabIndex = 0;
      row.onclick = () => show(s.no);
      row.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(s.no); } };

      const c1 = el("div", "dc dc-slide");
      const top = el("div", "dc-top");
      top.append(el("span", "slide-no", String(s.no)),
                 el("span", "chip", KIND_LABEL[s.kind] || s.kind || ""));
      c1.appendChild(top);
      c1.appendChild(el("div", "slide-title", s.title || ""));
      row.appendChild(c1);

      const c2 = el("div", "dc dc-audio");
      // 누적 시각 — "이 장이 발표 몇 분째에 나오는가". 길이만으론 감이 안 온다.
      c2.appendChild(el("div", "dc-at", fmt(run)));
      const sec = (s.audio && s.audio.sec) || (s.narration && s.narration.est_sec) || 0;
      run += sec;
      if (s.audio && s.audio.file) c2.appendChild(el("div", "dc-meta", `+${fmt(sec)} 실측`));
      else if (sec) c2.appendChild(el("div", "dc-muted", `+${fmt(sec)} 추정`));
      else c2.appendChild(el("div", "dc-muted", "—"));
      row.appendChild(c2);

      const c3 = el("div", "dc dc-text");
      const t = (s.narration && s.narration.srt_text) || "";
      c3.appendChild(t ? el("div", "dc-peek", t)
                       : el("div", "dc-muted", "대본 전"));
      row.appendChild(c3);

      const c4 = el("div", "dc dc-media");
      c4.appendChild(el("div", "dc-meta", MEDIA_LABEL[s.media_kind] || "—"));
      if (s.video_id) c4.appendChild(el("div", "dc-muted", `${s.video_id} · ${fmt(s.video_duration)}`));
      const marks = el("div", "gate-marks");
      for (const [k, label] of GATES) {
        if (k === "mute" && !s.video_id) continue;
        const m = el("span", "gm" + ((s.approve || {})[k] ? " on" : ""));
        m.textContent = label;
        marks.appendChild(m);
      }
      c4.appendChild(marks);
      row.appendChild(c4);

      tbl.appendChild(row);
    }

    /* ★ 목록 **끝**에 다음 자리로 가는 문을 둔다(2026-08-14).
     * 여기까지 훑고 나면 남은 일은 하나뿐이다 — mp4 한 편으로 굽는 것. 그런데 그 자리가 화면 맨 위 버튼 줄에만 있어서, 90줄을 다 내려온 사람은
     * 다시 위로 올라가야 했다. 끝난 자리에서 바로 이어지는 게 맞다. */
    const tail = el("div", "deck-tail");
    tail.appendChild(el("span", "deck-tail-t", `${slides.length}장 · 여기까지입니다`));
    const go = el("button", "btn primary");
    go.type = "button";
    go.append(stepBadge(DECK.video, "장마다 찍어 mp4 한 편으로"),
              icon("film", 14), el("span", null, "영상 렌더링"));
    go.onclick = () => navigate("/mp4");
    tail.appendChild(go);
    tbl.appendChild(tail);
    return tbl;
  }

  /* 무음 영상 편집기는 전용 화면(`/video`)과 **같은 모듈**을 쓴다.
   * 여기서 자른 구간이 거기서도 그대로 보여야 하고, 코드가 두 벌이면 반드시 갈라진다. */
  function videoEditor(s) {
    return ved(s, {
      src: `/api/projects/${state.projectId}/video/${s.video_id}`,
      onChange: (clip) => { s.clip = clip; edit(okey(s), ["clip"], clip); },
    });
  }

  /* ── 그림 넣기 ────────────────────────────────────────────────
   * 이미지 앱이 낸 `005.png` 든 직접 찍은 캡처든 **같은 자리, 같은 이름**으로 앉는다.
   * 규칙이 하나여야 어디에 넣을지 헷갈리지 않는다. */
  function imageDrop(s) {
    const box = el("div", "imgdrop" + (s.image ? " ok" : ""));
    const view = el("div", "imgdrop-view");
    const info = el("div", "imgdrop-info");
    const fileInput = el("input");
    fileInput.type = "file";
    fileInput.accept = "image/png,image/jpeg,image/webp,image/gif";
    fileInput.hidden = true;

    function paint() {
      view.textContent = "";
      if (s.image) {
        const im = el("img");
        im.src = `/api/projects/${state.projectId}/file/${encodeURI(s.image)}?t=${Date.now()}`;
        im.alt = "";
        view.appendChild(im);
      } else {
        view.appendChild(el("span", "imgdrop-ph",
          "끌어다 놓거나 눌러서 그림을 넣으세요"));
      }
      info.textContent = "";
      info.append(el("b", null, `${String(s.no).padStart(3, "0")}.png`),
                  el("span", null, s.image ? " 붙어 있음" : " 아직 없음"));
      box.classList.toggle("ok", !!s.image);
    }

    async function send(file) {
      if (!file) return;
      if (file.size > 12e6) { toast("12MB 를 넘습니다", "err"); return; }
      box.classList.add("busy");
      try {
        const data_url = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = rej;
          r.readAsDataURL(file);
        });
        const r = await api(`/api/projects/${state.projectId}/slide-image/${s.no}`,
                            {method: "POST", body: {data_url, name: file.name}});
        s.image = r.file;
        paint();
        toast(`${r.name} 넣었습니다`);
        fr.src = `/preview/${state.projectId}?n=${s.no}&t=${Date.now()}#${s.no}`;
      } catch (e) {
        toast("넣지 못했습니다: " + e.message, "err");
      } finally {
        box.classList.remove("busy");
      }
    }

    view.onclick = () => fileInput.click();
    fileInput.onchange = () => send(fileInput.files[0]);
    view.ondragover = (e) => { e.preventDefault(); box.classList.add("over"); };
    view.ondragleave = () => box.classList.remove("over");
    view.ondrop = (e) => {
      e.preventDefault();
      box.classList.remove("over");
      send(e.dataTransfer.files[0]);
    };

    const bar = el("div", "imgdrop-bar");
    const pick = el("button", "btn sm");
    pick.type = "button";
    pick.append(icon("image", 12), el("span", null, s.image ? "바꾸기" : "그림 넣기"));
    pick.onclick = () => fileInput.click();
    bar.appendChild(pick);
    if (s.image) {
      const rm = el("button", "btn sm ghost");
      rm.type = "button";
      rm.textContent = "빼기";
      rm.onclick = async () => {
        try {
          await api(`/api/projects/${state.projectId}/slide-image/${s.no}`,
                    {method: "DELETE"});
          s.image = "";
          paint();
          bar.replaceWith(el("div", "imgdrop-bar"));
          fr.src = `/preview/${state.projectId}?n=${s.no}&t=${Date.now()}#${s.no}`;
        } catch (e) { toast("빼지 못했습니다: " + e.message, "err"); }
      };
      bar.appendChild(rm);
    }
    const hint = el("div", "imgdrop-path");
    hint.textContent = "폴더에 직접 넣어도 됩니다 — 00_기획/참고/";
    box.append(view, info, bar, hint, fileInput);
    paint();
    return box;
  }

  // ── 보기 2 · 한 장 (편집) ────────────────────────────────
  function focusView(s) {
    if (!s) return el("div", "empty", "없는 장입니다.");
    const wrap = el("div", "focus");
    wrap.style.setProperty("--lane", laneColor(s));

    // 머리 — 어디쯤인지 + 앞뒤 이동
    const fh = el("div", "focus-head");
    const ttl = el("div", "focus-ttl");
    ttl.append(el("span", "slide-no", String(s.no)),
               el("span", "of", `/ ${slides.length}`),
               el("span", "chip", KIND_LABEL[s.kind] || s.kind || ""),
               el("span", "lane-tag", laneName[s.section] || ""));
    fh.appendChild(ttl);

    const nav = el("div", "focus-nav");
    const i = slides.findIndex((x) => x.no === s.no);
    const prev = el("button", "btn ghost"); prev.type = "button";
    prev.append(icon("chevronLeft", 14), el("span", null, "이전"));
    prev.disabled = i <= 0;
    prev.onclick = () => show(slides[i - 1].no);
    // ★ `nx` 표는 스토리보드가 찾는다 — 「정리됨·저장」이 곧 다음 장으로 넘김이다
    const next = el("button", "btn ghost nx"); next.type = "button";
    next.append(el("span", null, "다음"), icon("chevronRight", 14));
    next.disabled = i >= slides.length - 1;
    next.onclick = () => show(slides[i + 1].no);
    nav.append(prev, next);
    fh.appendChild(nav);
    wrap.appendChild(fh);

    // ★ 슬라이드 실물 — 최종 렌더러와 같은 코드. 여기서 OK 한 면이 그대로 나간다.
    const stage = el("div", "focus-stage");
    stage.dataset.no = `${s.no} / ${slides.length}`;
    const fr = el("iframe", "focus-frame");
    /* ★ `&t=` 를 붙인다(2026-09-05). 이 자리만 빠져 있어서 **덱 화면이 옛 화면을
       그대로 물고 있었다** — 원고 HTML 화면(`html.js`)에는 새 그림이 뜨는데 덱에서는
       옛 그림이 떠서 "그림이 안 바뀐다" 로 보였다. 그림을 갈아 끼우면 주소가
       같은 채로 내용만 달라지므로, 주소를 매번 다르게 해야 다시 받아 온다.
       같은 파일의 다른 자리(858·893·1038)는 이미 그렇게 하고 있다. */
    fr.src = `/preview/${state.projectId}?n=${s.no}&t=${Date.now()}#${s.no}`;
    fr.loading = "lazy";
    fr.title = `슬라이드 ${s.no}`;
    stage.appendChild(fr);
    // 영상과 같은 픽셀로 그린다 — 여기서 본 것이 곧 영상이다(1920x1080)
    fitFrame(stage, fr, 1920);
    const open = el("a", "focus-open");
    open.href = `/preview/${state.projectId}?n=${s.no}#${s.no}`;
    open.target = "_blank";
    open.rel = "noopener";
    open.append(el("span", null, "새 창에서 크게"), icon("external", 12));
    stage.appendChild(open);
    wrap.appendChild(stage);

    // 승인 — 이 장을 어디까지 봤는가
    const gbar = el("div", "gate-bar");
    gbar.appendChild(el("span", "gate-lb", "확인"));
    for (const [k, label] of GATES) {
      if (k === "mute" && !s.video_id) continue;
      const b = el("button", "gate-btn" + ((s.approve || {})[k] ? " on" : ""));
      b.type = "button";
      b.append(icon("check", 13), el("span", null, label));
      b.title = {slide: "슬라이드 면이 이대로 나가도 된다",
                 script: "자막·발음이 이대로 읽혀도 된다",
                 mute: "원본 소리를 죽이고 내레이션만 얹어도 된다"}[k];
      b.onclick = () => {
        s.approve = {...(s.approve || {})};
        s.approve[k] = !s.approve[k];
        b.classList.toggle("on", !!s.approve[k]);
        edit(okey(s), ["approve", k], s.approve[k]);
        drawGauge();
      };
      gbar.appendChild(b);
    }
    // ★ 영상보다 대본이 길면 2차 게이트에서 눈에 띄어야 한다.
    const over = (s.narration || {}).over_sec;
    if (over > 0.5) {
      const w = el("span", "gate-warn");
      w.textContent = `영상보다 대본이 ${over.toFixed(1)}초 깁니다 — 줄이거나 마지막 프레임을 홀드`;
      gbar.appendChild(w);
    }
    wrap.appendChild(gbar);

    /* ★ 슬라이드 문구 — **여기서 바로 고친다.**
     * 화면에 박히는 글이고 음성대본과 별개다. 읽기만 되면 결국 다시 굽게 되는데,
     * 한 글자 고치자고 $0.73 을 쓰는 건 말이 안 된다. 손으로 고친 것은
     * 오버라이드에 남아 문구 단계를 다시 돌려도 살아남는다. */
    const meta2 = el("div", "focus-meta");
    meta2.appendChild(el("label", "fm-lb", "슬라이드 제목 — 화면에 박히는 글"));
    const tin = el("textarea", "fm-title");
    tin.rows = 1;
    tin.value = s.title || "";
    tin.placeholder = "제목";
    tin.oninput = () => {
      s.title = tin.value;
      edit(okey(s), ["title"], tin.value);
      autoSize(tin);
      bump();
    };
    meta2.appendChild(tin);

    meta2.appendChild(el("label", "fm-lb", "본문 — 두세 줄. 나머지는 입으로 말합니다"));
    const bin = el("textarea", "fm-body");
    bin.rows = 3;
    bin.value = s.note || "";
    bin.placeholder = "본문 (비워도 됩니다)";
    bin.oninput = () => {
      s.note = bin.value;
      edit(okey(s), ["note"], bin.value);
      autoSize(bin);
      bump();
    };
    meta2.appendChild(bin);

    const len = el("div", "fm-len");
    const showLen = () => {
      const n = (bin.value || "").replace(/\s/g, "").length;
      len.textContent = `제목 ${(tin.value || "").length}자 · 본문 ${n}자`
        + (n > 130 ? " — 화면이 문서가 되고 있습니다" : "");
      len.classList.toggle("over", n > 130);
    };
    tin.addEventListener("input", showLen);
    bin.addEventListener("input", showLen);
    showLen();
    meta2.appendChild(len);

    if (s.evidence_hint) {
      const ev = el("div", "slide-ev");
      ev.append(icon("file", 11), el("span", null, s.evidence_hint));
      meta2.appendChild(ev);
    }
    /* ★ 제목·본문은 **맨 아래**로 내렸다(2026-08-16). 손이 가는 순서가
       듣기 → 발음 고치기 → 차례 정하기이고, 제목·본문은 그 전에 이미 확정된
       것이라 맨 위에 있을 이유가 없었다. 아래쪽에서 append 한다. */
    setTimeout(() => { autoSize(tin); autoSize(bin); }, 0);

    /* 고친 글이 실제 면에 어떻게 앉는지 보려면 미리보기를 다시 읽어야 한다.
     * 타이핑마다 새로 읽으면 깜빡이므로 **손을 멈춘 뒤** 한 번만. */
    const bump = debounce(() => {
      fr.src = `/preview/${state.projectId}?n=${s.no}&t=${Date.now()}#${s.no}`;
    }, 1200);

    // 편집 — 음성 / 자막 / 발음 / 미디어
    const grid = el("div", "focus-grid");

    // 자막 — 눈으로 읽는 원문
    const g1 = el("div", "fg");
    g1.appendChild(el("label", null, "자막 (화면에 보이는 원문)"));
    const srt = el("textarea", "dc-ta");
    srt.rows = 4;
    srt.value = (s.narration && s.narration.srt_text) || "";
    srt.placeholder = "대본을 돌리면 채워집니다";
    srt.oninput = () => edit(okey(s), ["narration", "srt_text"], srt.value);
    g1.appendChild(srt);
    grid.appendChild(g1);

    // 발음 — TTS 가 읽는 글. "27km" 를 자막엔 두고 여기만 "이십칠 킬로미터" 로.
    const g2 = el("div", "fg");
    g2.appendChild(el("label", null, "발음 (TTS 입력 · 실제로 읽는 텍스트)"));
    const pron = el("textarea", "dc-ta dc-pron");
    pron.rows = 4;
    pron.value = (s.narration && s.narration.text) || "";
    pron.placeholder = "비우면 자막을 그대로 읽습니다";
    /* ★ 맞춤법 검사를 끈다. 이 칸은 **일부러 맞춤법을 안 지키는 자리**다 —
       「대가」를 「대까」로, 「GDP」를 「지디피」로 적는다. 검사기는 그걸 전부
       틀렸다고 표시해서, 정작 눈으로 잡아야 할 것이 빨간 줄에 묻힌다. */
    pron.spellcheck = false;
    pron.oninput = () => edit(okey(s), ["narration", "text"], pron.value);
    g2.appendChild(pron);

    /* ★ 숫자를 소리대로 — **이 칸 안에서만** 바꾼다. 자막에서 다시 만들지
       않는다: 발음 칸에는 문체를 비롯해 손으로 고친 것이 이미 얹혀 있어서,
       다시 만들면 그게 통째로 날아간다.
       ★ 왜 필요한가 — TTS 가 숫자를 글자로 읽다가 씹는다(2026-08-16:
       "여러 번 나오면 씹히네요 발음이"). 한 장에 열 군데씩 나오면 손으로는
       반드시 몇 개를 놓친다(실제로 `1965년` 두 군데가 남아 있었다). */
    const nb = el("button", "btn sm");
    nb.type = "button";
    nb.append(icon("wand", 12), el("span", null, "숫자를 소리대로"));
    nb.title = "1960년대 → 천구백육십 년대 · 2.0퍼센트 → 이 쩜 영 퍼센트"
      + "\n숫자만 바꿉니다 — 문체는 건드리지 않습니다";
    nb.onclick = async () => {
      const before = pron.value;
      if (!/\d/.test(before)) { toast("바꿀 숫자가 없습니다"); return; }
      nb.disabled = true;
      try {
        const r = await api("/api/speak-numbers",
                            {method: "POST", body: {text: before}});
        if (r.text === before) { toast("바꿀 숫자가 없습니다"); return; }
        pron.value = r.text;
        edit(okey(s), ["narration", "text"], pron.value);   // 저장은 같은 길로
        toast("숫자를 소리대로 바꿨습니다 — 읽어 보고 «다시 합성»");
      } catch (e) {
        toast("바꾸지 못했습니다: " + e.message, "err");
      } finally {
        nb.disabled = false;
      }
    };
    g2.appendChild(nb);

    /* ★ 영문을 소리대로 — 「숫자를 소리대로」와 같은 자리, 같은 방식이다.
       ★ 왜 필요한가 — 모델은 한글 자모로 학습돼 영문에서 흔들린다. `FROM` 이
         「에프알오엠」으로도 뭉개진 소리로도 나온다. 2과목 SQL 은 한 덱에 `NULL`
         176번·`WHERE` 48번이라 손으로는 반드시 몇 개를 놓친다.
       ★ **자막은 안 건드린다.** 화면에는 `SELECT` 라고 떠야 한다 — 그게 배우는
         내용이다. 소리만 「셀렉트」가 되면 된다.
       ★ 표는 `voicewright/config/pronunciation_map.yaml` 하나다. 새 용어는 거기
         한 줄 넣으면 여기까지 따라온다(voicewright 의 `/dict` 화면에서 편집).
       ★ 「발음 대본 생성」이 이미 이 변환을 한다. 이 버튼은 **그 뒤에 자막을 고쳤을
         때** 그 칸만 다시 맞추는 자리다 — 전체를 다시 만들면 손편집이 날아간다. */
    const rb = el("button", "btn sm");
    rb.type = "button";
    rb.append(icon("wand", 12), el("span", null, "영문을 소리대로"));
    rb.title = `FROM → 프롬 · GROUP BY → 그룹 바이 · NULL → 널
표에 없는 영문은 글자 이름으로 읽습니다(ABC → 에이비씨)
자막은 건드리지 않습니다 — 화면에는 영문 그대로 남습니다`;
    rb.onclick = async () => {
      const before = pron.value;
      if (!/[A-Za-z]{2}/.test(before)) { toast("바꿀 영문이 없습니다"); return; }
      rb.disabled = true;
      try {
        const r = await api("/api/speak-roman",
                            {method: "POST", body: {text: before}});
        if (r.text === before) { toast("바꿀 영문이 없습니다"); return; }
        pron.value = r.text;
        edit(okey(s), ["narration", "text"], pron.value);   // 저장은 같은 길로
        toast("영문을 소리대로 바꿨습니다 — 읽어 보고 «다시 합성»");
      } catch (e) {
        toast("바꾸지 못했습니다: " + e.message, "err");
      } finally {
        rb.disabled = false;
      }
    };
    g2.appendChild(rb);

    grid.appendChild(g2);
    wrap.appendChild(grid);

    // 음성 + 미디어 한 줄
    const bar = el("div", "focus-bar");

    const ab = el("div", "fb");
    ab.appendChild(el("label", null, "음성"));
    /* ★ 발음을 고치면 **여기서 다시 만들고 여기서 듣는다.** 전체 합성은 31장에
       몇 분이라, 발음 한 군데 고칠 때마다 그걸 돌리면 검수가 끝나지 않는다
       (2026-08-16). */
    const aud = el("audio");
    aud.controls = true;
    // ★ `preload="none"` 이면 누르기 전까지 `0:00 / 0:00` 이라 "안 나온다" 로 읽힌다
    aud.preload = "metadata";
    const meta = el("div", "dc-meta");
    const has = !!(s.audio && s.audio.file);

    const setSrc = (bust) => {
      aud.src = `/api/projects/${state.projectId}/audio/${s.no}`
        + (bust ? `?v=${Date.now()}` : "");
      aud.load();
    };
    if (has) {
      setSrc(false);
      meta.textContent = `${s.audio.source} · ${fmt(s.audio.sec)}`;
      ab.append(aud, meta);
    } else if (s.narration && s.narration.est_sec) {
      ab.appendChild(el("div", "dc-muted", `합성 전 · 예상 ${fmt(s.narration.est_sec)}`));
    } else {
      ab.appendChild(el("div", "dc-muted", "대본 전"));
    }

    /* ★ 자막에서 발음 대본을 **이 장만** 다시 만든다.
       왜 필요한가 — 발음 칸은 오버라이드에 얹히고 손편집이 항상 이긴다. 그래서
       대본을 전체로 다시 구워도 **한 번 열어 본 장은 옛 글을 붙들고 있다**
       (2026-08-17: 변환기 버그를 고치고 34장을 다시 구웠는데 2장만 옛 글이
       남아 있었다 — 그 장을 열었을 때 오버라이드가 생겼기 때문이다).
       전체를 다시 굽는 대신 여기서 그 한 장을 맞춘다.
       ★ 대본 단계와 **같은 변환**을 쓴다(`/api/to-polite`). 규칙이 두 벌이면
       언젠가 서로 다르게 읽는다. */
    if (s.narration && s.narration.srt_text) {
      const mk = el("button", "btn sm ghost");
      mk.type = "button";
      mk.append(icon("wand", 12), el("span", null, "자막에서 발음 만들기"));
      mk.title = "자막 원문의 문장 끝을 하십시오체로 바꿔 발음 칸에 넣습니다"
        + "\n숫자는 안 건드립니다 — «숫자를 소리대로» 를 따로 누르세요";
      mk.onclick = async () => {
        const src = srt.value.trim();
        if (!src) { toast("자막이 비어 있습니다"); return; }
        mk.disabled = true;
        try {
          const r = await api("/api/pronounce", {method: "POST", body: {text: src}});
          const cur = pron.value.trim();
          if (cur === r.text) { toast("이미 이 글입니다"); return; }
          // ★ 손으로 고친 발음을 조용히 덮지 않는다 — 무엇이 사라지는지 보여 준다
          if (cur && !confirm(
              "지금 발음 칸의 글을 버리고 자막에서 다시 만듭니다.\n\n"
              + "지금:  " + cur.slice(0, 90) + (cur.length > 90 ? "…" : "")
              + "\n새로:  " + r.text.slice(0, 90) + (r.text.length > 90 ? "…" : "")
              + "\n\n숫자 읽기는 다시 눌러야 합니다.")) return;
          pron.value = r.text;
          edit(okey(s), ["narration", "text"], pron.value);
          toast("발음 대본을 다시 만들었습니다 — 읽어 보고 «발음대로 다시 합성»");
        } catch (e) {
          toast("만들지 못했습니다: " + e.message, "err");
        } finally { mk.disabled = false; }
      };
      ab.appendChild(mk);
    }

    // 대본이 있으면 — 음성이 아직 없어도 — 다시 만들 수 있어야 한다
    if (s.narration && (s.narration.text || s.narration.srt_text)) {
      const rv = el("button", "btn sm");
      rv.type = "button";
      const rl = el("span", null, has ? "발음대로 다시 합성" : "이 장 합성");
      rv.append(icon("refresh", 12), rl);
      rv.title = "지금 발음 칸에 적힌 대로 이 장만 다시 만듭니다";
      rv.onclick = async () => {
        rv.disabled = true;
        const was = rl.textContent;
        /* 초가 올라가는 것이 "살아 있다" 의 유일한 증거다 — 합성은 몇십 초 걸린다.
           ★ `clock` 이라는 이름은 이 파일에서 이미 다른 것이라 쓰지 않는다. */
        const t0 = Date.now();
        const tick = () => {
          const v = Math.floor((Date.now() - t0) / 1000);
          rl.textContent = `합성 중 · ${Math.floor(v / 60)}:`
            + String(v % 60).padStart(2, "0");
        };
        tick();
        const iv = setInterval(tick, 1000);
        try {
          const r = await api(
            `/api/projects/${state.projectId}/revoice/${s.no}`, {method: "POST"});
          if (!has) { ab.textContent = ""; ab.append(el("label", null, "음성"), aud, meta); }
          // ★ 같은 이름에 다른 소리다 — 꼬리표를 붙여야 옛 소리가 다시 안 난다
          setSrc(true);
          meta.textContent = `tts · ${fmt(r.sec)} · 방금 다시 만듦`;
          toast(`${s.no}장 음성을 다시 만들었습니다 — 들어 보세요`);
          aud.play().catch(() => { /* 자동재생을 막는 브라우저면 누르면 된다 */ });
          /* ★ 길이가 달라지면 **자막 시각이 밀린다.** 조용히 두면 어긋난 자막이
             그대로 영상에 실려 나간다 — 자막은 공짜니 다시 돌리면 그만이다. */
          if (r.subtitle_stale) {
            let note = ab.querySelector(".dc-restale");
            if (!note) {
              note = el("div", "dc-meta dc-restale");
              ab.appendChild(note);
            }
            note.textContent = `길이가 ${fmt(r.was)} → ${fmt(r.sec)} 로 바뀌었습니다`
              + " — 내보내기 전에 «자막» 을 다시 돌리세요";
          }
        } catch (e) {
          toast("다시 만들지 못했습니다: " + e.message, "err");
        } finally {
          clearInterval(iv);
          rl.textContent = was;
          rv.disabled = false;
        }
      };
      ab.appendChild(rv);
    }

    bar.appendChild(ab);

    const mb = el("div", "fb");
    mb.appendChild(el("label", null, "미디어"));
    const sel = el("select", "dc-sel");
    for (const [k, label] of Object.entries(MEDIA_LABEL)) {
      const o = el("option", null, label);
      o.value = k;
      if (k === s.media_kind) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = () => { edit(okey(s), ["media_kind"], sel.value); s.media_kind = sel.value; };
    mb.appendChild(sel);

    if (s.video_id) {
      mb.appendChild(videoEditor(s));
      mb.appendChild(el("div", "dc-meta",
        `${s.video_id} · ${s.video_title || ""} · ${fmt(s.video_duration)}`));
      const cands = s.frame_candidates || [];
      if (cands.length) {
        const st = el("div", "dc-strip");
        for (const fid of cands.slice(0, 6)) {
          const im = el("img");
          im.loading = "lazy";
          im.src = `/api/projects/${state.projectId}/img/frames/${fid}.webp`;
          im.alt = fid;
          st.appendChild(im);
        }
        mb.appendChild(st);
      } else {
        mb.appendChild(el("div", "dc-muted", "✓ 고른 컷 없음"));
      }
    } else if (s.media_kind === "text_image") {
      /* ★ 그림도 **여기서 바꾼다.** 확정 단위마다 그걸 고치는 자리가 있어야 한다.
       * 끌어다 놓거나 눌러서 고르면 그 장의 번호로 저장된다 — 파일명 규칙은 하나. */
      mb.appendChild(imageDrop(s));
    } else if (s.media_kind === "html") {
      /* 원고 장 — 줄이 몇 초에 뜨는지 **여기서도 보인다.** 표는 "이 장이 발표 몇
       * 분째인가" 를 보여 주는 자리인데, 원고 장은 그 안에서 또 시간이 흐른다.
       * 고치는 것은 /html 화면이고 여기서는 확인만 한다. */
      const ats = s.html_times || [];
      mb.appendChild(el("div", "dc-meta", `줄 ${s.html_blocks || 0}개`));
      if (ats.length) {
        mb.appendChild(el("div", "dc-muted",
          ats.slice(0, 8).map(fmt).join(" · ") + (ats.length > 8 ? " …" : "")));
      }
      const go = el("button", "btn sm ghost");
      go.type = "button";
      go.textContent = "시각 맞추기";
      go.onclick = () => {
        navigate(`/html?n=${s.no}`);
        setTimeout(() => dispatchEvent(new CustomEvent("deck:goto",
          {detail: {no: s.no, kind: "html"}})), 40);
      };
      mb.appendChild(go);
    }
    bar.appendChild(mb);
    wrap.appendChild(bar);

    /* ★ 발음 사전 — **음성 줄과 제목 칸 사이.** 사전을 채우려면 바로 위
       자막·발음 칸에서 낱말을 복사해야 하는데, 새 창이나 다른 화면으로 가면
       그 글을 놓친다(2026-08-23). 붙여 넣을 자리가 복사할 자리 바로
       아래에 있어야 한다. 접어 두므로 안 쓸 때는 한 줄만 차지한다. */
    wrap.appendChild(dictPanel(state.projectId));

    /* ── 스토리보드 정리 — 말하는 차례와 글자 뜨는 차례를 맞춘다 ─────────
       ★ 스틸은 위 슬라이드 자리에, 순서 표는 음성 바로 아래에 붙는다.
         영상을 아직 안 구웠으면 아무것도 안 붙고 화면은 예전 그대로다. */
    const sbStage = el("div", "sb-host");
    stage.parentNode.insertBefore(sbStage, stage);
    const sbRows = el("div");
    wrap.appendChild(sbRows);
    // ★ 자막을 문장별로 펼치는 자리는 **자막 칸 바로 밑**이다(g1) — 거기서
    //   "몇 초에 무슨 말" 을 보고 상자에 넣을 초를 정한다.
    storyboard(sbStage, sbRows, g1, s.no).then((ok) => {
      // 스틸이 곧 그 장의 영상 프레임이다 — 미리보기를 두 개 둘 이유가 없다
      if (ok) stage.hidden = true;
    });

    wrap.appendChild(meta2);

    return wrap;
  }

  /* 키보드 — 한 장 보기에서 ←/→ 로 넘긴다. 입력창 안에서는 커서 이동이 우선이다. */
  const onKey = (e) => {
    if (cur == null) return;
    const t = e.target;
    if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.tagName === "SELECT")) return;
    const i = slides.findIndex((x) => x.no === cur);
    if (e.key === "ArrowRight" && i < slides.length - 1) { e.preventDefault(); show(slides[i + 1].no); }
    if (e.key === "ArrowLeft" && i > 0) { e.preventDefault(); show(slides[i - 1].no); }
    if (e.key === "Escape") { e.preventDefault(); show(null); }
  };
  addEventListener("keydown", onKey);
  page.addEventListener("x-unmount", () => removeEventListener("keydown", onKey));

  /* 사이드바에서 섹션을 누르면 그 구간 첫 장으로 들어간다.
   * 화면을 갈아치우지 않는다 — 덱은 하나의 연속 수열이다. */
  const onGoto = (e) => {
    const {no, kind} = e.detail || {};
    if (kind) setKind(kind);
    if (byNo[no]) show(no);
  };
  addEventListener("deck:goto", onGoto);
  page.addEventListener("x-unmount", () => removeEventListener("deck:goto", onGoto));

  drawClock();
  drawGauge();
  // 주소에 장이 실려 오면 그 장으로 연다 (`#/deck?n=8`)
  const want = Number((ctx && ctx.params && ctx.params.get("n")) || 0);
  const wantKind = (ctx && ctx.params && ctx.params.get("kind")) || null;
  if (wantKind) setKind(wantKind);
  show(byNo[want] ? want : null);
}


/** 산출물 폴더를 탐색기에서 연다. quiet 면 실패해도 조용히 넘어간다. */
async function openDist(quiet) {
  try {
    await api(`/api/projects/${state.projectId}/reveal`,
              {method: "POST"});
  } catch (e) {
    if (!quiet) toast("폴더를 열지 못했습니다: " + e.message, "err");
  }
}

/* ── 완성본 ─────────────────────────────────────────────────────────────────
 *
 * 답해야 하는 질문은 하나다 — **무엇을 올리나.**
 * 그래서 폴더 하나를 크게 놓고, 나머지는 밑에 작게 붙인다.
 *
 * ★ 폴더 안은 외부 참조가 0 이다. 정적 파일만 얹히면 되는 곳이면 어디서든
 *   똑같이 돈다 — GitHub Pages · nginx · VPS · 카페24. 서버 프로그램이 없다.
 */
async function distCard(page) {
  let d;
  try { d = await api(`/api/projects/${state.projectId}/dist`); } catch { return; }
  if (!d.web && !(d.extras || []).length) return;

  const box = el("div", "dist");
  const h = el("div", "dist-hd");
  const open = el("button", "btn sm");
  open.type = "button";
  open.append(icon("folder", 13), el("span", null, "폴더 열기"));
  open.title = d.dir;
  open.onclick = () => openDist(false);
  h.append(icon("download", 16), el("h3", null, "완성본"),
           el("span", "dist-dir", d.dir), open);
  box.appendChild(h);

  if (d.web) {
    const w = el("div", "dist-web");
    w.appendChild(el("div", "dw-k", "이 폴더를 통째로 올리세요"));
    const nm = el("div", "dw-n");
    nm.append(icon("folder", 16), el("b", null, d.web.name + "/"));
    w.appendChild(nm);
    w.appendChild(el("div", "dw-b",
      `${d.web.files}개 파일 · ${(d.web.bytes / 1e6).toFixed(1)}MB`));
    w.appendChild(el("div", "dw-w",
      "안에 페이지·음성·폰트 라이선스가 다 있습니다. 밖으로 나가는 주소가 0건이라 "
      + "정적 호스팅이면 어디서든 돕니다 — GitHub Pages · nginx · VPS · 카페24. "
      + "주소는 …/" + d.web.name + "/ 로 들어가면 index.html 이 열립니다."));
    const row = el("div", "dist-row");
    const go = el("a", "btn sm primary");
    go.href = d.web.url;
    go.target = "_blank";
    go.rel = "noopener";
    go.textContent = "웹에서처럼 열어 보기";
    row.appendChild(go);
    w.appendChild(row);
    box.appendChild(w);
  }

  if ((d.extras || []).length) {
    const g = el("div", "dist-grid");
    for (const f of d.extras) {
      const c = el("div", "dist-i");
      c.append(el("span", "dist-n", f.name),
               el("span", "dist-b", `${Math.round(f.bytes / 1024).toLocaleString()} KB`),
               el("span", "dist-w", f.why));
      if (f.url) {
        const row = el("div", "dist-row");
        const dl = el("a", "btn sm");
        dl.href = f.url;
        dl.download = f.name;
        dl.textContent = "내려받기";
        row.appendChild(dl);
        c.appendChild(row);
      }
      g.appendChild(c);
    }
    box.appendChild(g);
  }
  page.appendChild(box);
}
