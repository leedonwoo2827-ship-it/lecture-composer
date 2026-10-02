# -*- coding: utf-8 -*-
"""리졸버 — 같은 덱을 두 가지 방식으로 내보낸다.

    폴더    dist/index.html + assets/…   ← gh-pages push · 영상 포함
    단일    dist/<slug>.html             ← 외부 참조 0 · 파일 하나로 전달

렌더러(`slides.py`)는 리졸버가 무엇을 하는지 모른다. `asset(rel)` 이 URL 을 주면
그걸 쓸 뿐이다. 그래서 렌더 코드가 두 벌이 되지 않는다.

★ 단일 파일에는 **영상을 넣지 않는다.** 23MB 짜리 mkv 여섯 개를 base64 로 박으면
  파일이 40MB 를 넘고 브라우저가 파싱하다 멈춘다. 대신 대표 프레임을 넣는다 —
  발표에서 실제로 트는 건 폴더 빌드거나 이 페이지를 녹화한 영상이다.
"""
from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from render import ff

MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".mp4": "video/mp4",
        ".m4a": "audio/mp4", ".opus": "audio/ogg", ".wav": "audio/wav",
        # ★ mp3 가 빠져 있으면 data: URI 가 application/octet-stream 으로 나가고
        #   브라우저가 재생하지 않는다. 배경음악은 대개 mp3 로 들어온다.
        ".mp3": "audio/mpeg",
        ".woff2": "font/woff2",
        # ★ html 이 빠져 있으면 브라우저가 페이지로 안 열고 다운로드로 받는다.
        #   완성본을 앱에서 바로 열어 보는 길이 여기다.
        ".html": "text/html; charset=utf-8",
        ".zip": "application/zip", ".md": "text/markdown; charset=utf-8",
        ".csv": "text/csv; charset=utf-8", ".srt": "text/plain; charset=utf-8",
        ".txt": "text/plain; charset=utf-8", ".json": "application/json"}


class FolderResolver:
    """assets/ 로 **복사**하고 상대 경로를 준다. 음성은 aac, 영상은 mp4 로 옮긴다."""

    def __init__(self, root: Path, out: Path) -> None:
        self.root, self.out = root, out
        self.assets = out / "assets"
        self.assets.mkdir(parents=True, exist_ok=True)
        self.map: Dict[str, str] = {}
        self.notes: List[str] = []
        self.videos: Dict[str, str] = {}

    def asset(self, rel: str) -> str:
        if not rel:
            return ""
        if rel in self.map:
            return self.map[rel]
        src = self.root / rel
        if not src.is_file():
            self.notes.append(f"없음: {rel}")
            self.map[rel] = ""
            return ""
        # 파생 파일명은 ascii — 한글 파일명이 URL·zip 을 깨는 것을 원천 차단
        name = f"{len(self.map):03d}{src.suffix.lower()}"
        if src.suffix.lower() == ".wav":
            m4a = self.assets / f"{len(self.map):03d}.m4a"
            ok, err = ff.to_aac(src, m4a)
            if ok:
                self.map[rel] = f"assets/{m4a.name}"
                return self.map[rel]
            self.notes.append(f"aac 변환 실패({rel}): {err[:80]} — wav 그대로")
        shutil.copy2(src, self.assets / name)
        self.map[rel] = f"assets/{name}"
        return self.map[rel]

    def video(self, s: Dict[str, Any]) -> str:
        vid = s.get("video_id")
        if not vid:
            return ""
        if vid in self.videos:
            return self.videos[vid]
        src = self._src(vid)
        if not src:
            self.videos[vid] = ""
            return ""
        dst = self.assets / f"{vid}.mp4"
        if src.suffix.lower() == ".mp4":
            shutil.copy2(src, dst)
        else:
            ok, err = ff.remux_mp4(src, dst)
            if not ok:
                self.notes.append(f"{vid} mp4 변환 실패: {err[:80]}")
                self.videos[vid] = ""
                return ""
        self.videos[vid] = f"assets/{dst.name}"
        return self.videos[vid]

    # 원본 영상 위치는 프로젝트가 안다 — 생성 시 주입한다
    src_lookup = None

    def _src(self, vid: str) -> Optional[Path]:
        return self.src_lookup(vid) if self.src_lookup else None

    def bgm(self, rel: str) -> str:
        """배경음악 — 폴더본은 그냥 복사한다. 정적 호스팅이 mp3 를 알아서 낸다."""
        return self.asset(rel)


class SingleFileResolver:
    """전부 `data:` URI 로 박는다. **외부 참조 0** 이 이 빌드의 계약이다."""

    def __init__(self, root: Path, *, audio_kbps: int = 32, bgm_kbps: int = 64,
                 tmp: Optional[Path] = None) -> None:
        self.root = root
        self.tmp = tmp or (root / "_tmp_single")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.kbps = audio_kbps
        # ★ 음악은 말보다 후하게 준다. 32k 는 말소리엔 충분해도 음악에서는
        #   금속성이 확 올라온다. 3분짜리가 64k 면 1.4MB 안팎이다.
        self.bgm_kbps = bgm_kbps
        self.map: Dict[str, str] = {}
        self.notes: List[str] = []
        self.bytes = 0

    def asset(self, rel: str) -> str:
        if not rel:
            return ""
        if rel in self.map:
            return self.map[rel]
        src = self.root / rel
        if not src.is_file():
            self.map[rel] = ""
            return ""
        if src.suffix.lower() == ".wav":
            op = self.tmp / (src.stem + ".opus")
            ok, err = ff.to_opus(src, op, kbps=self.kbps)
            if ok:
                src = op
            else:
                self.notes.append(f"opus 변환 실패({rel}): {err[:60]}")
        self.map[rel] = data_uri(src)
        self.bytes += len(self.map[rel])
        return self.map[rel]

    def bgm(self, rel: str) -> str:
        """배경음악 — **다시 떠서 넣는다.**

        단일 파일은 메일·USB 로 건네는 한 장이라 크기가 곧 쓸모다. mp3 원본을
        base64 로 박으면 1.33 배로 부는데, opus 로 다시 뜨면 오히려 원본보다 작아진다.
        """
        if not rel:
            return ""
        src = self.root / rel
        if not src.is_file():
            self.notes.append(f"배경음악 없음: {rel}")
            return ""
        op = self.tmp / "bgm.opus"
        ok, err = ff.to_opus(src, op, kbps=self.bgm_kbps)
        if not ok:
            # ffmpeg 이 없는 PC 도 있다 — 원본을 그대로 넣고 커진 것을 알린다
            self.notes.append(f"배경음악 opus 변환 실패: {err[:60]} — 원본 그대로")
            op = src
        uri = data_uri(op)
        self.bytes += len(uri)
        return uri

    def video(self, s: Dict[str, Any]) -> str:
        return ""      # 단일 파일에는 영상을 넣지 않는다 — 대표 프레임이 대신한다


def data_uri(p: Path) -> str:
    mt = MIME.get(p.suffix.lower(), "application/octet-stream")
    return f"data:{mt};base64," + base64.b64encode(p.read_bytes()).decode()
