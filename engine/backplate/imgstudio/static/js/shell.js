// shell.js — 워크스페이스 전환 (프롬프트 빌더 ⇄ 이미지 스튜디오)
const wsBuilder = document.getElementById("ws-builder");
const wsStudio = document.getElementById("ws-studio");

function showWorkspace(ws) {
  document.querySelectorAll(".ws-tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.ws === ws));
  wsBuilder.hidden = ws !== "builder";
  wsStudio.hidden = ws !== "studio";
}

document.getElementById("wsTabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".ws-tab");
  if (btn) showWorkspace(btn.dataset.ws);
});

// 기본: 프롬프트 빌더(앞 탭)
showWorkspace("builder");
