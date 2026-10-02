/* 홈 — **시작 화면이자 첫 메뉴.**
 *
 * 여기에 시작 폼(영상 폴더 · 레포 · 라이브 URL)이 있다. 패널이 아니라 바닥에 두는
 * 이유는 규칙 때문이다: **입력창이 있는 화면은 패널에 두지 않는다.** 패널은 Esc 나
 * 스크림 클릭으로 닫히므로, 경로를 타이핑하다 한 번만 잘못 눌러도 날아간다.
 *
 * 앞으로 여기에 "무엇을 만들까" 를 묻는 부분이 더 붙는다. 그때도 자리는 바닥이다.
 */
"use strict";

import { el, api, icon, toast } from "./util.js";
import { state, getProjects, invalidate } from "./store.js";
import { navigate } from "./shell.js";

export const meta = {
  title: "일반영상 제작 에이전트",
  subtitle: "화면 영상 · 레포 · 라이브 URL 을 넣으면 슬라이드처럼 넘어가는 쇼케이스 한 장이 나옵니다",
};

function card(title, body) {
  const c = el("div", "card");
  c.appendChild(el("div", "card-title", title));
  if (body) c.appendChild(el("div", "card-body", body));
  return c;
}

function field(label, name, ph, note) {
  const f = el("div", "field");
  f.appendChild(el("label", null, label));
  const i = el("input");
  i.name = name;
  i.placeholder = ph || "";
  f.appendChild(i);
  if (note) f.appendChild(el("div", "field-note", note));
  return f;
}

function startForm() {
  const wrap = el("div", "start");
  const form = el("form", "form");
  form.appendChild(field("이름", "title", "예: CAIND ODA 전문가 경력관리"));
  form.appendChild(field("영상 폴더", "video_dir",
    "D:/00work/260808-jarang/_video-context",
    "폴더 안의 영상 파일이 곧 항목이 됩니다. 원본은 복사하지 않고 읽기만 합니다."));
  form.appendChild(field("라이브 URL", "live_url", "https://example.com",
    "선택 — 쇼케이스에서 '실제로 보러 가기' 링크가 됩니다."));
  form.appendChild(field("GitHub 레포", "repo", "owner/name",
    "선택 — 넣으면 기능↔코드 연결과 기술적 의사결정 서술이 가능해집니다."));

  const submit = el("button", "btn primary");
  submit.type = "submit";
  submit.append(icon("plus", 14), el("span", null, "만들기"));
  form.appendChild(submit);
  wrap.appendChild(form);

  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      title: (fd.get("title") || "").trim(),
      video_dir: (fd.get("video_dir") || "").trim(),
      live_url: (fd.get("live_url") || "").trim() || null,
      repo: (fd.get("repo") || "").trim() || null,
    };
    if (!body.title || !body.video_dir) {
      toast("이름과 영상 폴더는 필요합니다", "warn");
      return;
    }
    submit.disabled = true;
    try {
      const p = await api("/api/projects", { method: "POST", body });
      invalidate();
      toast(`${p.items.length}개 영상을 찾았습니다`);
      state.projectId = p.id;      // 탭이 다시 그려지고 이 프로젝트가 활성이 된다
    } catch (err) {
      toast(err.message, "err");
      submit.disabled = false;
    }
  };
  return wrap;
}

export async function mount(root) {
  const page = el("div", "page");
  root.appendChild(page);

  const projects = await getProjects(true).catch(() => []);

  // ── 프로젝트가 없으면: 시작 폼이 곧 첫 화면 ──
  if (!projects.length) {
    page.appendChild(el("h2", "sec-title", "시작"));
    page.appendChild(startForm());
  } else {
    page.appendChild(el("h2", "sec-title", "무엇이 나오나"));
    const out = el("div", "grid grid-3");
    out.append(
      card("슬라이드 웹페이지",
        "한 항목 = 한 장. ←/→ 로 넘기고, 장마다 내레이션 음성이 붙습니다. gh-pages 에 올리면 공개 URL."),
      card("단일 HTML 한 장",
        "외부 참조 0. 메일·USB 로 던져도 그대로 열립니다."),
      card("영상팀 인계 큐시트",
        "타임코드 · 자막 · 내레이션을 md / csv / srt 로."),
    );
    page.appendChild(out);

    page.appendChild(el("h2", "sec-title", "프로젝트 추가"));
    page.appendChild(startForm());
  }

  // ── 상태 ──
  page.appendChild(el("h2", "sec-title", "상태"));
  const status = el("div", "grid grid-3");
  page.appendChild(status);
  status.appendChild(el("div", "card", "확인 중…"));

  try {
    const h = await api("/api/health");
    status.innerHTML = "";

    const cli = el("div", "card");
    cli.appendChild(el("div", "card-title", "Claude Code 로그인"));
    cli.appendChild(el("span", "badge " + (h.claude_cli ? "ok" : "err"),
      h.claude_cli ? "연결됨" : "확인 필요"));
    cli.appendChild(el("div", "card-note", h.claude_cli
      ? "API 키 없이 이 PC 의 구독 인증으로 나갑니다."
      : "터미널에서 claude 를 한 번 실행해 로그인하세요."));
    status.appendChild(cli);

    const ws = el("div", "card");
    ws.appendChild(el("div", "card-title", "산출물 폴더"));
    ws.appendChild(el("div", "card-note", h.workspace.root));
    ws.appendChild(el("div", "card-note", h.workspace.from_env
      ? "SHOWCASE_WORKSPACE 로 지정됨"
      : "앱 폴더의 형제 폴더 (기본값) — git clean 이 산출물을 지울 수 없습니다."));
    status.appendChild(ws);

    const v = el("div", "card");
    v.appendChild(el("div", "card-title", "비전 모드"));
    v.appendChild(el("span", "badge brand", h.vision_mode));
    v.appendChild(el("div", "card-note", h.vision_mode === "inline"
      ? "프레임을 base64 로 직접 보냅니다 (검증 완료)."
      : "프레임을 디스크에 두고 Read 시킵니다 (폴백)."));
    status.appendChild(v);
  } catch (e) {
    status.innerHTML = "";
    status.appendChild(el("div", "card", "서버 상태를 읽지 못했습니다: " + e.message));
  }
}
