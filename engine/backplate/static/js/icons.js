/* 아이콘 — 손으로 그린 한 세트. 24×24 viewBox, fill 없음, stroke=currentColor.
 *
 * 이모지를 쓰지 않는다: OS 마다 모양·크기·색이 달라 디자인 시스템이 성립하지 않고,
 * 색을 currentColor 로 물려받지 못해 활성/비활성 상태를 표현할 수 없다.
 *
 * 마크업: <span data-icon="file" data-icon-size="16"></span>
 * 그 다음 hydrateIcons(root) 가 SVG 로 채운다.
 */
"use strict";

const P = {
  file: '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 5v14"/><path d="M9 7h6M9 11h6"/>',
  slide: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
  check: '<path d="m5 13 4 4L19 7"/>',
  arrowRight: '<path d="M5 12h13"/><path d="m12 5 7 7-7 7"/>',
  upload: '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/><path d="M4 21h16"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  chevronUp: '<path d="m6 15 6-6 6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  chevronRight: '<path d="m9 6 6 6-6 6"/>',
  chevronLeft: '<path d="m15 6-6 6 6 6"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
  panelLeft: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
  plug: '<path d="M9 2v6M15 2v6"/><path d="M7 8h10v3a5 5 0 0 1-10 0z"/><path d="M12 16v6"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
  download: '<path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/>',
  edit: '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="m14 6 4 4"/>',
  wand: '<path d="M5 19 17 7"/><path d="M14 4l1.2 2.8L18 8l-2.8 1.2L14 12l-1.2-2.8L10 8l2.8-1.2z"/>',
  clipboard: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 10h6M9 14h4"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
  printer: '<path d="M7 9V3h10v6"/><path d="M7 19H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M7 15h10v6H7z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
};

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((n) => {
    const path = P[n.dataset.icon];
    if (!path) { n.remove(); return; }
    const size = n.dataset.iconSize || 16;
    n.classList.add("i");
    n.innerHTML =
      `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" ` +
      `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" ` +
      `stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
    delete n.dataset.icon;
  });
  return root;
}
