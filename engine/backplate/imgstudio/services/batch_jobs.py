"""슬라이드 JSON 일괄 생성 — 프롬프트 목록 → 번호 파일명 이미지 배치.

강의 슬라이드용 이미지 프롬프트 JSON(`{"prompts": [{"n": 3, "prompt": "..."}]}`)을 받아
지정한 폴더에 `003.png` 처럼 **슬라이드 번호에 파일명을 맞춘** 이미지를 만든다.
(PPT 합치기 도구가 파일명 앞 숫자로 슬라이드를 찾기 때문에 번호가 곧 계약이다.)

80장 규모를 한 번에 돌리는 것을 전제로 설계했다.

  · 동시 실행 (기본 3, 최대 6) — codex 백엔드를 과하게 때리지 않는 범위
  · 항목별 재시도 + 지수 백오프 (429/과부하는 더 길게 대기)
  · 이어하기 — 이미 있는 번호 파일은 건너뜀. 중단했다가 다시 돌려도 남은 것만 만든다.
  · 진행 상태를 data/batch_jobs/<job_id>.json 에 계속 기록 → 브라우저를 닫아도 계속 진행
  · 로그인 만료(401)는 즉시 전체 중단 — 남은 구독 할당량을 헛되이 태우지 않는다.

한 번에 한 작업만 돌린다(같은 계정으로 두 배치가 동시에 돌면 429 만 늘어난다).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.atomic_io import atomic_write_json
from ..core.config import load_settings
from ..core.constants import DATA_DIR, IMAGES_DIR
from ..core.database import Image, Project, SessionLocal
from .codex_image import ImageEngineError, NotAuthenticated, generate_image

JOBS_DIR = DATA_DIR / "batch_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

MAX_ITEMS = 200                 # 한 배치 상한 (실수로 수백 장을 태우는 것 방지)
MAX_WORKERS = 6
DEFAULT_WORKERS = 3
DEFAULT_RETRIES = 2
BACKOFF_BASE = 6.0              # 초 — 실패 후 대기 (지수)
BACKOFF_RATE_LIMIT = 45.0       # 초 — 429/한도 초과는 길게 쉰다
KEEP_JOB_FILES = 40

_EXT = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp"}
_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_NUM_PREFIX = re.compile(r"^0*(\d+)")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 파일명 / 폴더 ─────────────────────────────────────────────────────────────
def slugify(title: str, limit: int = 28) -> str:
    """제목을 파일명에 붙일 수 있게 정리 (한글 유지, 공백→_)."""
    s = _ILLEGAL.sub("", str(title or "")).strip()
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._-")
    return s[:limit]


def build_filename(n: int, title: str, ext: str, with_title: bool) -> str:
    """`003.png` 또는 `003_뇌구조.png`. 앞 3자리 번호가 슬라이드 번호."""
    base = f"{int(n):03d}"
    if with_title:
        slug = slugify(title)
        if slug:
            base = f"{base}_{slug}"
    return base + ext


def scan_existing(out_dir: str) -> Dict[int, str]:
    """폴더에서 '번호로 시작하는 이미지 파일'을 찾아 {슬라이드번호: 파일명} 으로."""
    found: Dict[int, str] = {}
    try:
        entries = sorted(os.scandir(out_dir), key=lambda e: e.name)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return found
    for e in entries:
        if not e.is_file():
            continue
        if Path(e.name).suffix.lower() not in _IMAGE_EXTS:
            continue
        m = _NUM_PREFIX.match(e.name)
        if m:
            found.setdefault(int(m.group(1)), e.name)
    return found


def inspect_dir(raw: str) -> dict:
    """UI 의 '폴더 확인' — 이미 있는 번호 파일 목록. 폴더를 만들지는 않는다.

    (경로를 잘못 적었을 때 빈 폴더가 생기지 않도록, 실제 생성은 생성 시작 시점에만 한다.)
    """
    path = (raw or "").strip().strip('"')
    if not path:
        return {"ok": False, "error": "폴더 경로를 입력하세요."}
    p = Path(path).expanduser()
    if not p.is_absolute():
        return {"ok": False, "error": "전체 경로를 입력하세요. (예: D:\\작업\\assets)"}
    if p.exists() and not p.is_dir():
        return {"ok": False, "error": "같은 이름의 파일이 있습니다. 다른 경로를 쓰세요."}
    if p.is_dir() and not os.access(p, os.W_OK):
        return {"ok": False, "error": "쓰기 권한이 없는 폴더입니다."}
    existing = scan_existing(str(p)) if p.is_dir() else {}
    return {
        "ok": True, "dir": str(p), "exists": p.is_dir(),
        "existing": {str(k): v for k, v in sorted(existing.items())},
    }


def ensure_dir(raw: str) -> dict:
    """생성 시작 직전 — 없으면 폴더를 만들고 쓰기 가능한지 확인."""
    info = inspect_dir(raw)
    if not info.get("ok"):
        return info
    p = Path(info["dir"])
    if not p.is_dir():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"폴더를 만들 수 없습니다: {e}"}
        if not os.access(p, os.W_OK):
            return {"ok": False, "error": "쓰기 권한이 없는 폴더입니다."}
    return info


def reveal_dir(raw: str) -> dict:
    """탐색기/파인더로 폴더 열기."""
    p = Path((raw or "").strip().strip('"')).expanduser()
    if not p.is_dir():
        return {"ok": False, "error": "폴더가 없습니다."}
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 프롬프트 정규화 ───────────────────────────────────────────────────────────
# JSON 의 aspect → 크기. 16:9/9:16 은 모델이 직접 못 내지만 여백을 덧대 맞추므로
# 이제 요청한 그대로 준다. (예전에는 조용히 3:2 로 바꿔 줘서 16:9 를 적어도 3:2 가 왔다)
_ASPECT_SIZE = {
    "landscape": "1536x1024", "horizontal": "1536x1024",
    "portrait": "1024x1536", "vertical": "1024x1536",
    "square": "1024x1024", "1:1": "1024x1024",
    "16:9": "1536x864", "9:16": "864x1536",
    "4:3": "1408x1056", "3:4": "1056x1408", "21:9": "1344x576",
}


def size_for_aspect(aspect: str, fallback: str = "1536x1024") -> str:
    return _ASPECT_SIZE.get(str(aspect or "").strip().lower(), fallback)


# 배경색을 명시한 프롬프트인지 판별 — "배경: 밝은 아이보리(#F6F1E8)", "바탕은 반드시 …#F6F1E8"
_BG_SPEC_RE = re.compile(r"(배경|바탕)[^\n]{0,40}#[0-9A-Fa-f]{6}")

# 배경 대비 가드. 배경색을 지정한 프롬프트에만 맨 앞에 붙는다.
#
# 왜 필요한가: 색/톤 문장이 "진한 파랑(#1F4E79)…중심" 처럼 어두운 색으로 시작하면
# 이미지 모델이 그 색을 배경으로 받아들여 화면을 어둡게 칠하고, 뒤쪽에 적힌
# 배경색 지시("바탕은 반드시 밝은 아이보리")를 흘려버린다. 그러면 같은 계열로
# 지정된 글자색이 배경에 묻혀 슬라이드가 못 쓰게 된다. 배경 지시를 색/톤 문장보다
# 먼저 읽게 해서 막는다. 특정 색을 강요하지 않으므로 어두운 덱에도 그대로 쓸 수 있다.
_BG_GUARD = (
    "【배경 · 최우선】 아래에 바탕/배경 색이 지정돼 있으면 그 색을 화면 전체에 고르게 칠하라 "
    "— 네 귀퉁이와 가장자리까지 같은 밝기다. 지정된 배경색을 무시하고 다른 색으로 칠하지 말고, "
    "비네팅·어두운 그라데이션·발광(글로우)·야간 조명·스포트라이트로 배경의 밝기를 바꾸지 마라. "
    "글자는 배경과 명도 차이가 뚜렷한 색으로 써서 반드시 읽히게 하라. "
    "아래 장면·구도·라벨 위치·문구는 그대로 따른다.\n\n─────────────\n"
)


def compose_prompt(item: dict, style_hint: str = "") -> str:
    """프롬프트 본문 + (있으면) 스타일 힌트/네거티브를 한 문장으로 합친다.

    codex 이미지 툴에는 negative 파라미터가 없어 'Avoid:' 문장으로 붙인다.
    이미 프롬프트에 같은 문구가 들어 있으면 중복해서 붙이지 않는다.
    배경색을 명시한 프롬프트에는 앞에 배경 대비 가드를 세운다(_BG_GUARD 주석 참고).
    """
    prompt = str(item.get("prompt") or "").strip()
    hint = str(style_hint or "").strip()
    if hint and hint[:40].lower() not in prompt.lower():
        prompt = f"{prompt} {hint}" if prompt else hint
    neg = str(item.get("negative") or "").strip()
    if neg and "avoid:" not in prompt.lower():
        prompt = f"{prompt} Avoid: {neg}."
    prompt = prompt.strip()
    if prompt and _BG_SPEC_RE.search(prompt) and "【배경" not in prompt:
        prompt = _BG_GUARD + prompt
    return prompt


def normalize_payload(raw: Any) -> dict:
    """JSON(dict 또는 list) → {deck, style_hint, aspect, items:[{n,title,type,level,place,prompt}]}"""
    if isinstance(raw, list):
        raw = {"prompts": raw}
    if not isinstance(raw, dict):
        raise ValueError("JSON 형식이 아닙니다.")
    rows = raw.get("prompts") or raw.get("items") or raw.get("scenes") or []
    if not isinstance(rows, list) or not rows:
        raise ValueError("prompts 배열이 없습니다. (슬라이드 프롬프트 JSON 이 맞는지 확인하세요)")

    style_hint = str(raw.get("style_hint") or "").strip()
    aspect = str(raw.get("aspect") or "").strip()
    items: List[dict] = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        n = row.get("n", row.get("slide", row.get("no", i)))
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = i
        items.append({
            "n": n,
            "title": str(row.get("title") or "").strip(),
            "type": str(row.get("type") or "").strip(),
            "level": str(row.get("level") or "").strip(),
            "place": bool(row.get("place")),
            "prompt": compose_prompt(row, style_hint),
        })
    if not items:
        raise ValueError("프롬프트 문자열이 있는 항목이 없습니다.")
    return {
        "deck": str(raw.get("deck") or "").strip(),
        "style_hint": style_hint,
        "aspect": aspect,
        "suggested_size": size_for_aspect(aspect),
        "count": len(items),
        "items": items,
    }


# ── 작업(Job) ────────────────────────────────────────────────────────────────
class BatchJob:
    def __init__(self, *, deck: str, out_dir: str, size: str, workers: int, retries: int,
                 skip_existing: bool, with_title: bool, ext: str,
                 gallery_project_id: Optional[int], items: List[dict]):
        self.id = uuid.uuid4().hex[:12]
        self.deck = deck
        self.out_dir = out_dir
        self.size = size
        self.workers = workers
        self.retries = retries
        self.skip_existing = skip_existing
        self.with_title = with_title
        self.ext = ext
        self.gallery_project_id = gallery_project_id
        self.status = "running"          # running | done | stopped | error
        self.fatal = ""                  # 전체 중단 사유(로그인 만료 등)
        self.started = _now_iso()
        self.finished = ""
        self.stop_flag = False
        self.items: List[dict] = [
            {**it, "status": "pending", "file": "", "error": "", "attempts": 0,
             "image_id": None}
            for it in items
        ]
        self.lock = threading.Lock()

    # 진행 요약
    def counts(self) -> dict:
        c = {"total": len(self.items), "pending": 0, "running": 0,
             "done": 0, "skipped": 0, "failed": 0, "canceled": 0}
        for it in self.items:
            c[it["status"]] = c.get(it["status"], 0) + 1
        c["settled"] = c["done"] + c["skipped"] + c["failed"] + c["canceled"]
        return c

    def to_dict(self, *, with_prompts: bool = False) -> dict:
        running = [it["n"] for it in self.items if it["status"] == "running"]
        return {
            "id": self.id, "deck": self.deck, "out_dir": self.out_dir,
            "size": self.size, "workers": self.workers,
            "status": self.status, "fatal": self.fatal,
            "started": self.started, "finished": self.finished,
            "counts": self.counts(), "running_slides": sorted(running),
            "items": [
                {k: v for k, v in it.items() if with_prompts or k != "prompt"}
                for it in self.items
            ],
        }

    def persist(self) -> None:
        try:
            atomic_write_json(str(JOBS_DIR / f"{self.id}.json"), self.to_dict())
        except Exception:
            pass  # 기록 실패가 생성 자체를 막지 않도록


_jobs: Dict[str, BatchJob] = {}
_jobs_lock = threading.Lock()
_tasks: Dict[str, asyncio.Task] = {}


def active_job() -> Optional[BatchJob]:
    """진행 중(중단 처리 중 포함) 작업. 중단 중에도 마지막 장이 아직 생성 중일 수 있다."""
    with _jobs_lock:
        for job in _jobs.values():
            if job.status in ("running", "stopping"):
                return job
    return None


def get_job(job_id: str) -> Optional[BatchJob]:
    with _jobs_lock:
        return _jobs.get(job_id)


def list_jobs(limit: int = 12) -> List[dict]:
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.started, reverse=True)[:limit]
    return [{k: v for k, v in j.to_dict().items() if k != "items"} for j in jobs]


def _prune_job_files() -> None:
    try:
        files = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[KEEP_JOB_FILES:]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


# ── 갤러리 등록 (선택) ────────────────────────────────────────────────────────
def _add_to_gallery(data: bytes, prompt: str, size: str, meta: dict,
                    project_id: Optional[int], stem: str) -> Optional[int]:
    """스튜디오 갤러리에도 사본을 넣어 바로 보고/수정할 수 있게 한다."""
    try:
        name = f"batch_{uuid.uuid4().hex}.png"
        (IMAGES_DIR / name).write_bytes(data)
        db = SessionLocal()
        try:
            img = Image(project_id=project_id, prompt=f"[{stem}] {prompt}"[:4000],
                        engine=meta.get("engine", "codex"), model=meta.get("model", ""),
                        size=size, file_path=name, kind="generate")
            db.add(img)
            db.commit()
            return img.id
        finally:
            db.close()
    except Exception:
        return None


def ensure_project(name: str) -> Optional[int]:
    """배치 결과를 담을 사이드바 리스트를 만들거나 같은 이름을 재사용."""
    name = (name or "").strip()[:200] or "일괄 생성"
    db = SessionLocal()
    try:
        found = db.query(Project).filter(Project.name == name).first()
        if found:
            return found.id
        p = Project(name=name)
        db.add(p)
        db.commit()
        return p.id
    except Exception:
        return None
    finally:
        db.close()


# ── 실행 ─────────────────────────────────────────────────────────────────────
def _is_rate_limited(msg: str) -> bool:
    low = msg.lower()
    return ("429" in low or "rate limit" in low or "too many" in low
            or "usage limit" in low or "quota" in low or "한도" in msg)


async def _generate_one(job: BatchJob, item: dict, settings: dict) -> None:
    out_dir = Path(job.out_dir)
    fname = build_filename(item["n"], item["title"], job.ext, job.with_title)
    target = out_dir / fname

    for attempt in range(job.retries + 1):
        if job.stop_flag:
            item["status"] = "canceled"
            job.persist()
            return
        item["attempts"] = attempt + 1
        item["status"] = "running"
        try:
            data, meta = await asyncio.to_thread(
                generate_image, item["prompt"],
                size=job.size, refs=None, settings=settings,
            )
            await asyncio.to_thread(target.write_bytes, data)
            item["file"] = fname
            item["error"] = ""
            item["status"] = "done"
            if job.gallery_project_id is not None:
                item["image_id"] = await asyncio.to_thread(
                    _add_to_gallery, data, item["prompt"], job.size, meta,
                    job.gallery_project_id, f"{item['n']:03d} {item['title']}".strip(),
                )
            job.persist()
            return
        except NotAuthenticated as e:
            # 로그인 만료 — 남은 항목까지 다 실패시키지 말고 전체를 세운다.
            item["status"] = "failed"
            item["error"] = str(e)
            job.stop_flag = True
            job.fatal = str(e)
            job.persist()
            return
        except ImageEngineError as e:
            msg = str(e)
            item["error"] = msg
            if attempt >= job.retries or job.stop_flag:
                item["status"] = "failed"
                job.persist()
                return
            item["status"] = "pending"
            job.persist()
            wait = BACKOFF_RATE_LIMIT if _is_rate_limited(msg) else BACKOFF_BASE * (2 ** attempt)
            await asyncio.sleep(wait)
        except Exception as e:  # 디스크 쓰기 실패 등
            item["status"] = "failed"
            item["error"] = f"{type(e).__name__}: {e}"
            job.persist()
            return


async def _run_job(job: BatchJob) -> None:
    settings = load_settings()
    sem = asyncio.Semaphore(job.workers)

    async def worker(item: dict) -> None:
        async with sem:
            if job.stop_flag:
                if item["status"] == "pending":
                    item["status"] = "canceled"
                return
            await _generate_one(job, item, settings)

    try:
        targets = [it for it in job.items if it["status"] == "pending"]
        await asyncio.gather(*(worker(it) for it in targets))
    except asyncio.CancelledError:
        for it in job.items:
            if it["status"] in ("pending", "running"):
                it["status"] = "canceled"
        job.status = "stopped"
        raise
    finally:
        for it in job.items:
            if it["status"] in ("pending", "running"):
                it["status"] = "canceled"
        c = job.counts()
        if job.fatal:
            job.status = "error"
        elif job.stop_flag or c["canceled"]:
            job.status = "stopped"
        else:
            job.status = "done"
        job.finished = _now_iso()
        job.persist()
        _prune_job_files()


def build_job(*, items: List[dict], out_dir: str, size: str, deck: str = "",
              workers: int = DEFAULT_WORKERS, retries: int = DEFAULT_RETRIES,
              skip_existing: bool = True, with_title: bool = False,
              fmt: str = "png", to_gallery: bool = True) -> BatchJob:
    """작업을 **만들어 등록만** 한다. 돌리지는 않는다.

    ★ 왜 갈랐나. 예전에는 만들기와 돌리기가 한 함수였고, 돌리기가
      `asyncio.get_running_loop()` 을 써서 **이벤트 루프가 있는 곳에서만**
      부를 수 있었다. 웹 라우트는 루프 안이라 괜찮았지만, 파이프라인
      스테이지(`s3c-images-run`)는 쇼케이스가 **데몬 스레드**에서 돌린다 —
      거기엔 루프가 없어서 `RuntimeError: no running event loop` 로 죽었다
      (2026-09-18 실측). 만들기는 동기라, 돌리는 방법만 부르는 쪽이 고르게 한다.
    """
    running = active_job()
    if running:
        raise RuntimeError(
            f"이미 일괄 생성이 진행 중입니다 ({running.counts()['settled']}/"
            f"{running.counts()['total']}). 끝나거나 중단한 뒤 다시 시작하세요."
        )
    if not items:
        raise ValueError("생성할 항목이 없습니다.")
    if len(items) > MAX_ITEMS:
        raise ValueError(f"한 번에 최대 {MAX_ITEMS}장까지 가능합니다. (요청 {len(items)}장)")

    info = ensure_dir(out_dir)
    if not info.get("ok"):
        raise ValueError(info.get("error", "출력 폴더를 확인하세요."))
    resolved = info["dir"]
    existing = {int(k): v for k, v in info["existing"].items()}
    ext = _EXT.get(str(fmt or "png").lower(), ".png")

    workers = max(1, min(MAX_WORKERS, int(workers or DEFAULT_WORKERS)))
    retries = max(0, min(5, int(retries if retries is not None else DEFAULT_RETRIES)))

    project_id = ensure_project(f"🖼 {deck}" if deck else "🖼 일괄 생성") if to_gallery else None

    job = BatchJob(deck=deck, out_dir=resolved, size=size, workers=workers, retries=retries,
                   skip_existing=skip_existing, with_title=with_title, ext=ext,
                   gallery_project_id=project_id, items=items)

    if skip_existing:
        for it in job.items:
            if it["n"] in existing:
                it["status"] = "skipped"
                it["file"] = existing[it["n"]]

    with _jobs_lock:
        _jobs[job.id] = job
    job.persist()

    return job


def start_job(**kw) -> BatchJob:
    """만들어서 **이 루프에** 얹는다 — 웹 라우트용(루프 안에서 부른다)."""
    job = build_job(**kw)
    task = asyncio.get_running_loop().create_task(_run_job(job))
    _tasks[job.id] = task
    task.add_done_callback(lambda _t: _tasks.pop(job.id, None))
    return job


def start_job_in_thread(**kw) -> BatchJob:
    """만들어서 **제 스레드에서 제 루프로** 돌린다 — 파이프라인 스테이지용.

    호출한 쪽은 루프가 없어도 된다. 진행 상황은 `get_job(id)` 로 읽는다
    (job 객체를 스레드가 직접 갱신하므로 폴링이 그대로 먹는다).
    """
    job = build_job(**kw)

    def _go() -> None:
        try:
            asyncio.run(_run_job(job))
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.fatal = f"{type(e).__name__}: {e}"
            job.finished = _now_iso()
            job.persist()

    t = threading.Thread(target=_go, name=f"batch-{job.id}", daemon=True)
    t.start()
    return job


def stop_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "작업을 찾을 수 없습니다."}
    job.stop_flag = True
    if job.status == "running":
        job.status = "stopping"
    job.persist()
    return {"ok": True, "job": job.to_dict()}


def retry_failed(job_id: str) -> dict:
    """실패/중단된 항목만 다시 큐에 올려 같은 작업을 이어서 돌린다."""
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "작업을 찾을 수 없습니다."}
    if job.status in ("running", "stopping"):
        return {"ok": False, "error": "아직 진행 중입니다."}
    if active_job():
        return {"ok": False, "error": "다른 일괄 생성이 진행 중입니다."}
    again = [it for it in job.items if it["status"] in ("failed", "canceled")]
    if not again:
        return {"ok": False, "error": "다시 시도할 항목이 없습니다."}
    for it in again:
        it["status"] = "pending"
        it["error"] = ""
        it["attempts"] = 0
    job.stop_flag = False
    job.fatal = ""
    job.finished = ""
    job.status = "running"
    job.persist()
    task = asyncio.get_running_loop().create_task(_run_job(job))
    _tasks[job.id] = task
    task.add_done_callback(lambda _t: _tasks.pop(job.id, None))
    return {"ok": True, "job": job.to_dict(), "requeued": len(again)}
