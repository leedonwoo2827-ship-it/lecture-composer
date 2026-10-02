# -*- coding: utf-8 -*-
"""이미지 스튜디오를 호스트(쇼케이스) FastAPI 앱에 얹는다.

★ 원래 이 폴더는 스스로 서버를 띄우는 독립 앱이었다(app.py, 8765 포트).
  합치면서 서버 노릇은 전부 버리고 **라우터와 정적 파일만** 내놓는다.
  버린 것: 자기 `GET /`·`/favicon.ico`(호스트 첫 화면과 충돌),
           `HOST`/`PORT`(호스트 것과 싸운다),
           맨 `load_dotenv()`(프로세스 작업폴더의 .env 를 몰래 읽는다),
           `app.mount("/", ...)`(호스트의 모든 URL 을 삼킨다).

★ 모든 경로는 PREFIX 아래로 들어간다. 프런트(js/css)도 같은 접두어를 쓴다.
"""
from __future__ import annotations

import mimetypes

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .core.constants import PRESETS_DIR, STATIC_DIR, URL_PREFIX
from .core.database import init_db

PREFIX = URL_PREFIX


def _routers():
    """라우터는 여기서만 불러온다 — 임포트 부작용을 마운트 시점으로 미룬다."""
    from .routes.auth_routes import router as auth
    from .routes.batch_routes import router as batch
    from .routes.builder_archive_routes import router as b_archive
    from .routes.builder_chat_routes import router as b_chat
    from .routes.builder_manuscript_routes import router as b_manu
    from .routes.builder_preset_routes import router as b_preset
    from .routes.image_routes import router as image
    from .routes.project_routes import router as project
    from .routes.settings_routes import router as settings
    return [auth, settings, project, image, batch, b_chat, b_preset, b_archive, b_manu]


def attach(app: FastAPI) -> None:
    """호스트 앱에 라우터 + 정적 파일을 건다. server.py 에서 한 번 부른다."""
    # Windows 일부 환경에서 .js MIME 매핑이 깨져 ES 모듈 로드가 실패하는 것을 막는다
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")

    init_db()

    for r in _routers():
        app.include_router(r, prefix=PREFIX)

    # 프리셋 커버 이미지 → /imgstudio/presets/...
    app.mount(f"{PREFIX}/presets", StaticFiles(directory=str(PRESETS_DIR)),
              name="imgstudio-presets")
    # css/js/fonts + index.html → /imgstudio/
    app.mount(PREFIX, StaticFiles(directory=str(STATIC_DIR), html=True),
              name="imgstudio-static")
