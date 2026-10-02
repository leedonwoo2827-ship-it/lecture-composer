# -*- coding: utf-8 -*-
"""S3c 그림 굽기 — `이미지프롬프트.json` → `09_이미지/003.png`.

★ **이 스테이지가 터미널 둘을 하나로 만든다.** 예전에는 이 앱이 지시문 JSON 을
  뱉으면 사람이 그 파일을 들고 8765 포트의 다른 앱으로 건너가 한 장씩 눌렀다.
  그 앱을 `imgstudio/` 로 들여왔으므로 이제 같은 프로세스 안에서 부른다.

★ **큐는 이미 저쪽에 있다.** 동시 3(최대 6) · 항목별 재시도 + 지수 백오프 ·
  이어하기(있는 번호는 건너뜀) · 진행 상태를 파일에 기록 · 401 이면 즉시 전체
  중단(남은 구독 할당량을 헛되이 태우지 않는다). 여기서는 **붙이기만** 한다.

★ 파일명은 **슬라이드 번호**다(`003.png`). 지시문 JSON 의 `file` 칸이 정한
  이름과 같다 — 번호가 곧 계약이라 사람이 자리를 맞출 일이 없다.

★ 썸네일은 따로 돈다. `썸네일프롬프트.json` 은 화풍(스톱모션 퍼핏)도 파일명도
  다르고, 원래부터 글자를 안 넣는 판이라 11판에서도 바뀌는 것이 없다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from core import workspace as ws
from pipeline.registry import STAGES, write_cache

POLL_SEC = 3.0
# 한 장이 30~60초쯤 걸린다. 80장이면 동시 3으로 30분 안팎 — 넉넉히 둔다.
MAX_WAIT_SEC = 4 * 3600


def _payload(p: Path) -> Dict[str, Any]:
    from imgstudio.services import batch_jobs
    return batch_jobs.normalize_payload(json.loads(p.read_text(encoding="utf-8")))


def _bake(job, *, items: List[Dict[str, Any]], out_dir: Path, size: str,
          deck: str, st: Dict[str, Any], force: bool, what: str) -> Dict[str, Any]:
    """한 묶음을 굽고 끝날 때까지 지켜본다. 본문과 썸네일이 같은 것을 쓴다.

    ★ `start_job` 이 아니라 `start_job_in_thread` 다 — 쇼케이스는 스테이지를
      이벤트 루프가 없는 데몬 스레드에서 돌린다(2026-09-18 실측:
      RuntimeError: no running event loop).
    ★ 배치는 **한 번에 하나만** 돈다(저쪽 active_job 가드). 그래서 본문을
      끝내고 나서 썸네일을 돈다 — 동시에 못 돌린다.
    """
    from imgstudio.services import batch_jobs

    bj = batch_jobs.start_job_in_thread(
        items=items, out_dir=str(out_dir), size=size, deck=deck,
        workers=int(st.get("batch_workers") or batch_jobs.DEFAULT_WORKERS),
        retries=batch_jobs.DEFAULT_RETRIES,
        skip_existing=not force, with_title=False,
        fmt=st.get("default_format", "png"), to_gallery=False)
    job.add_log(f"{what} 굽는 중 — 작업 {bj.id}")

    waited, last = 0.0, -1
    cur = None
    while True:
        time.sleep(POLL_SEC)
        waited += POLL_SEC
        cur = batch_jobs.get_job(bj.id)
        if cur is None:
            raise RuntimeError("작업이 사라졌습니다(서버 재시작?)")
        c = cur.to_dict()["counts"]
        done = int(c.get("done", 0)) + int(c.get("skipped", 0))
        if done != last:
            last = done
            job.progress(done, len(items),
                         f"{what} · 실패 {c.get('failed', 0)}"
                         if c.get("failed") else what)
        if cur.status != "running":
            break
        if getattr(job, "canceled", False):
            batch_jobs.stop_job(bj.id)
            raise RuntimeError("사람이 멈췄습니다")
        if waited > MAX_WAIT_SEC:
            batch_jobs.stop_job(bj.id)
            raise RuntimeError("너무 오래 걸려 멈췄습니다")

    final = cur.to_dict()
    c = final["counts"]
    warn: List[str] = []
    if final.get("fatal"):
        # 로그인 만료가 여기로 온다. **이름을 그대로 남긴다** — "실패"만 적으면
        # 할당량 소진인지 로그인 문제인지 사람이 알 수 없다.
        warn.append(f"{what} 전체 중단: {final['fatal']}")
    for it in final.get("items", []):
        if it.get("status") == "failed" and it.get("error"):
            warn.append(f"{what} {it['n']}번: {it['error']}")
    job.add_log(f"{what}: 만듦 {c.get('done', 0)} · 건너뜀 {c.get('skipped', 0)} "
                f"· 실패 {c.get('failed', 0)}")
    return {"job": bj.id, "made": c.get("done", 0),
            "skipped": c.get("skipped", 0), "failed": c.get("failed", 0),
            "warn": warn}


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s3c-images-run"]
    from imgstudio.core.config import load_settings
    from imgstudio.services import batch_jobs

    d = ws.step_dir(pid, slug, "images")
    src = d / "이미지프롬프트.json"
    if not src.is_file():
        raise RuntimeError("이미지프롬프트.json 이 없습니다 — 먼저 지시문(s3a)을 만드세요.")

    norm = _payload(src)
    items = norm["items"]
    job.add_log(f"{len(items)}장 · 비율 {norm.get('aspect') or '기본'} "
                f"→ {norm.get('suggested_size')}")

    # ★ 이미 있는 번호는 저쪽 `skip_existing` 이 건너뛴다. 여기서도 미리 세어
    #   사람에게 알려 준다 — 「몇 장이 새로 구워지는가」가 곧 비용이다.
    have = batch_jobs.scan_existing(str(d))
    todo = [it for it in items if int(it["n"]) not in have]
    job.add_log(f"이미 있음 {len(have)}장 · 새로 구움 {len(todo)}장")
    st = load_settings()
    size = norm.get("suggested_size") or st.get("default_size", "auto")
    deck_name = norm.get("deck") or project.get("title") or slug

    # ★ **여기서 일찍 빠져나가지 않는다.** 예전에는 본문이 다 있으면 곧장
    #   돌아갔는데, 그러면 **썸네일을 영영 안 굽는다** — 썸네일은 본문과
    #   딴 폴더(bak/)에 살아서 「본문이 다 있다」와 아무 상관이 없다
    #   (2026-09-18 실측: 1장 본문 11장을 다 굽고도 썸네일이 안 나왔다).
    if todo or force:
        r = _bake(job, items=items, out_dir=d, size=size, deck=deck_name,
                  st=st, force=force, what="본문")
    else:
        job.add_log(f"본문 {len(have)}장이 이미 있습니다 — 건너뜁니다")
        r = {"job": "", "made": 0, "skipped": len(have), "failed": 0, "warn": []}
    warn: List[str] = list(r["warn"])

    # ── 썸네일 ────────────────────────────────────────────────────────────
    # ★ **bak/ 에 굽는다.** 썸네일은 후보 두 장(후킹형·차분형)이고 번호가
    #   1·2 다. 본문과 같은 폴더에 두면 `001.png`·`002.png` 가 본문 그림과
    #   부딪힌다 — 그래서 사람이 전부터 bak/ 에 따로 모아 왔다. 그 관행을
    #   그대로 따른다(9장 bak/001.png·002.png 가 그것이다).
    # ★ 화풍이 본문과 **일부러 다르다**(스톱모션 퍼핏). 그래서 지시문도
    #   파일도 따로다 — 여기서 섞지 않는다.
    th_src = d / "썸네일프롬프트.json"
    th = {"made": 0, "skipped": 0, "failed": 0}
    if th_src.is_file():
        try:
            th_norm = _payload(th_src)
        except Exception as e:  # noqa: BLE001
            warn.append(f"썸네일 지시문을 읽지 못했습니다: {e}")
            th_norm = None
        if th_norm and th_norm.get("items"):
            bak = d / "bak"
            bak.mkdir(parents=True, exist_ok=True)
            th = _bake(job, items=th_norm["items"], out_dir=bak,
                       size=th_norm.get("suggested_size") or size,
                       deck=f"{deck_name} (썸네일)", st=st, force=force,
                       what="썸네일")
            warn += th.pop("warn", [])
            job.add_log(f"썸네일은 {bak.name}/001.png · 002.png "
                        f"— 둘을 견줘 하나를 고릅니다")

    return write_cache(pid, slug, "s3c-images-run",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"job": r["job"], "made": r["made"],
                             "skipped": r["skipped"], "failed": r["failed"],
                             "thumb": {k: th.get(k, 0)
                                       for k in ("made", "skipped", "failed")},
                             "size": size, "dir": str(d)},
                       code_version=stage.code_version, cost_usd=0.0,
                       status="degraded" if warn else "ok", warnings=warn[:10])


STAGES["s3c-images-run"].run = run
