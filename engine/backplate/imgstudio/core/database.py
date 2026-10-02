"""SQLite + SQLAlchemy 모델.

- Project : 사이드바 리스트/폴더
- Image   : 생성/편집/병합 결과 1건 (parent_id 로 편집 계보 연결)
- EditEvent: 수정 이력 (자연어 nl / 마스크 mask / 병합 merge)
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker,
)

from .constants import DB_PATH, URL_PREFIX

_engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)

    images: Mapped[list["Image"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(20), default="codex")
    model: Mapped[str] = mapped_column(String(60), default="")
    size: Mapped[str] = mapped_column(String(20), default="auto")
    file_path: Mapped[str] = mapped_column(String(400), default="")   # data/images 기준 상대경로
    kind: Mapped[str] = mapped_column(String(20), default="generate")  # generate|edit|merge
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Optional["Project"]] = relationship(back_populates="images")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "prompt": self.prompt,
            "engine": self.engine,
            "model": self.model,
            "size": self.size,
            "kind": self.kind,
            "parent_id": self.parent_id,
            "favorite": self.favorite,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "url": f"{URL_PREFIX}/api/images/{self.id}/file",
        }


class EditEvent(Base):
    __tablename__ = "edit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20), default="nl")  # nl|mask|merge
    instruction: Mapped[str] = mapped_column(Text, default="")
    source_image_ids: Mapped[str] = mapped_column(Text, default="")  # JSON list
    result_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "image_id": self.image_id,
            "type": self.type,
            "instruction": self.instruction,
            "source_image_ids": self.source_image_ids,
            "result_image_id": self.result_image_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def init_db() -> None:
    Base.metadata.create_all(_engine)
