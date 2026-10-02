"""라우트 공용 헬퍼 — DB 세션, 이미지 파일 저장/로드, base64 디코드."""
from __future__ import annotations

import base64
import uuid
from typing import Iterator

from ..core.constants import IMAGES_DIR
from ..core.database import Image, SessionLocal


def get_db() -> Iterator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def save_image_bytes(data: bytes) -> str:
    """PNG 바이트를 data/images 에 저장하고 파일명(상대경로)을 반환."""
    name = f"{uuid.uuid4().hex}.png"
    (IMAGES_DIR / name).write_bytes(data)
    return name


def read_image_file(img: Image) -> bytes:
    return (IMAGES_DIR / img.file_path).read_bytes()


def decode_data_url(s: str) -> bytes:
    """data URL("data:image/png;base64,....") 또는 순수 base64 문자열을 바이트로."""
    if not s:
        raise ValueError("empty image data")
    if s.startswith("data:"):
        s = s.split(",", 1)[1]
    return base64.b64decode(s)
