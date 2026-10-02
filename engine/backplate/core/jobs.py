# -*- coding: utf-8 -*-
"""잡 레지스트리 — 백그라운드 실행 + 폴링.

사내 배치 앱의 잡 레지스트리를 스테이지 파이프라인용으로 옮겼다. 원칙은 같다:

  - 잡은 **메모리**에 산다. 브라우저는 폴링으로 상태를 읽는다.
  - 부분 결과가 실시간으로 쌓인다 — 6개 항목 중 3개가 끝났으면 3개가 보인다.
  - 로그는 파일에도 append 한다. 브라우저를 새로고침해도 tail 을 다시 그린다.

프로젝트당 동시에 하나만 돈다. 같은 캐시 파일을 두 스테이지가 함께 쓰면
input_hash 가 꼬이고, 무엇보다 Claude 호출이 두 배로 나간다.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

LOG_TAIL = 300


def _now() -> datetime:
    return datetime.now()


@dataclass
class Job:
    job_id: str
    project_id: int
    stage: str                      # "s3-caption"
    label: str                      # "프레임 캡션"
    status: str = "queued"          # queued | running | done | error | canceled
    step: str = ""                  # 사람이 읽는 현재 단계
    completed: int = 0
    total: int = 0
    cost_usd: float = 0.0
    log: List[str] = field(default_factory=list)
    partial: Dict[str, Any] = field(default_factory=dict)   # 항목별 부분 결과
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=_now)
    finished_at: Optional[datetime] = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    # ── 워커가 부르는 것 ──
    def add_log(self, line: str) -> None:
        ts = _now().strftime("%H:%M:%S")
        self.log.append(f"{ts}  {line}")
        del self.log[:-LOG_TAIL]

    def progress(self, completed: int, total: int, step: str = "") -> None:
        self.completed, self.total = int(completed), int(total)
        if step:
            self.step = step

    @property
    def canceled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    # ── 클라이언트가 읽는 것 ──
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "stage": self.stage,
            "label": self.label,
            "status": self.status,
            "step": self.step,
            "completed": self.completed,
            "total": self.total,
            "cost_usd": round(self.cost_usd, 4),
            "log": self.log[-120:],
            "partial": self.partial,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds") if self.finished_at else None,
            "running": self.status in ("queued", "running"),
            "died": self.status == "error",
        }


class Registry:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._by_project: Dict[int, str] = {}      # 프로젝트당 현재 잡
        self._lock = threading.Lock()

    def running_for(self, project_id: int) -> Optional[Job]:
        with self._lock:
            jid = self._by_project.get(int(project_id))
            j = self._jobs.get(jid) if jid else None
        return j if (j and j.status in ("queued", "running")) else None

    def any_running(self) -> Optional[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        for j in sorted(jobs, key=lambda x: x.started_at, reverse=True):
            if j.status in ("queued", "running"):
                return j
        return None

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def latest(self, project_id: int) -> Optional[Job]:
        with self._lock:
            jid = self._by_project.get(int(project_id))
        return self._jobs.get(jid) if jid else None

    def start(self, *, project_id: int, stage: str, label: str,
              work: Callable[[Job], Any], total: int = 0) -> Job:
        """워커를 스레드로 띄운다. 이미 도는 잡이 있으면 거절한다."""
        if (cur := self.running_for(project_id)) is not None:
            raise RuntimeError(f"이미 실행 중입니다: {cur.label} ({cur.stage})")

        job = Job(job_id=uuid.uuid4().hex[:12], project_id=int(project_id),
                  stage=stage, label=label, total=int(total))
        with self._lock:
            self._jobs[job.job_id] = job
            self._by_project[int(project_id)] = job.job_id
            # 오래된 잡 정리 — 메모리에 무한정 쌓이지 않게
            if len(self._jobs) > 40:
                old = sorted(self._jobs.values(), key=lambda x: x.started_at)
                for o in old[:10]:
                    if o.status not in ("queued", "running"):
                        self._jobs.pop(o.job_id, None)

        def runner() -> None:
            job.status = "running"
            job.add_log(f"시작 — {label}")
            try:
                job.result = work(job)
                job.status = "canceled" if job.canceled else "done"
                job.add_log("취소됨" if job.canceled else "완료")
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = f"{type(e).__name__}: {e}"
                job.add_log(f"실패 — {job.error}")
                for line in traceback.format_exc().splitlines()[-8:]:
                    job.add_log("  " + line)
            finally:
                job.finished_at = _now()

        threading.Thread(target=runner, daemon=True, name=f"job-{stage}").start()
        return job


_registry = Registry()


def get_registry() -> Registry:
    return _registry
