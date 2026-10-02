"""앱 전역 경로/상수."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "app.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

# 프롬프트 빌더(앞 탭) 자산/저장 경로
PROMPTS_DIR = BASE_DIR / "prompts"      # brand_guide.md, style_catalog.md
PRESETS_DIR = BASE_DIR / "presets"      # 프리셋 폴더 + 커버 이미지
ARCHIVES_PATH = DATA_DIR / "archives.json"  # 보관함 인덱스

APP_TITLE = "Codex Studio — 프롬프트 빌더 & 이미지 스튜디오"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))

# image_generation 툴이 네이티브로 지원하는 크기 3종 + 자동. (프론트에서 비율 라벨로 표시)
# 규칙에 어긋나는 값은 codex_image._check_size() 가 보내기 전에 걸러 준다.
# 전부 네이티브로 생성된다(2026-08-29 실측). 가로·세로 모두 16의 배수여야 하고
# 비율은 1:3~3:1 사이면 되므로, 여기 없는 크기도 규칙만 지키면 쓸 수 있다.
# 다만 해상도는 백엔드가 다시 잡으므로 실제 픽셀은 조금 달라진다 — 비율만 지켜진다.
SIZE_CHOICES = [
    "auto",
    "1024x1024",   # 1:1
    "1536x1024",   # 3:2 가로
    "1024x1536",   # 2:3 세로
    "1536x864",    # 16:9 가로 — 슬라이드·유튜브
    "864x1536",    # 9:16 세로 — 쇼츠·릴스
    "1408x1056",   # 4:3 가로
    "1056x1408",   # 3:4 세로
    "1344x576",    # 21:9 초광각
]

# 디렉토리 보장
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PRESETS_DIR.mkdir(parents=True, exist_ok=True)

# ── URL 접두어 ────────────────────────────────────────────────────────────
# 이 앱은 더 이상 혼자 서지 않는다. 쇼케이스 서버에 얹혀 /imgstudio 아래로 들어간다.
# 서버가 만들어 내보내는 URL(이미지 url, 프리셋 커버)도 같은 접두어를 써야 한다.
# ★ 여기 한 곳만 고치면 프런트·백엔드가 같이 따라온다.
URL_PREFIX = "/imgstudio"
