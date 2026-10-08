"""run.bat <단계> [--job <잡>] [--only L01,L02] [--sections N] [--force] [--dry-run] [--max N]

단계 (번호 = 이름, 둘 다 된다)
  pack           원천 모으기   요약노트·영상 원고·문항 → jobs/<job>/input/  (원천 PC에서 한 번)
  propose        기획 재료      강 수 후보표(배분·길이별 확장비) → proposals.json   ← 대화로 강 수를 정할 때
  decide         기획 결정      --per 3,7 --target 35 --note "이유" → 목표서 + brief.md 기록 + 편성
  examples       문항 반영      문항(mNN.json)이 들어오거나 바뀌었을 때 — 강 나누기는 그대로, 예시만 다시 고름
  s1 plan        편성          목표서(job.json)대로 강 나누기·예시 문항 고르기 → curriculum.json
  s2 compose     집필          집필 에이전트(Claude)가 목표 분량에 맞춰 강의 원고를 다시 씀 (+보강: 웹)
  s3 render      렌더          backplate-studio 로 섹션 mp4
  s4 stitch      잇기          섹션 → 강 한 편, −16 LUFS, 챕터, 합본 자막
  s5 meta        메타          유튜브 제목·설명·태그·썸네일
  login          로그인        유튜브 채널(처음 한 번, 전용 Chrome 프로필)
  s6 publish     게시          YouTube Studio 자동 업로드(일부공개)
  s7 register    등록          사이트 youtube_map · review.html · 기록(statements.jsonl)
  s8 textbook    교재          교재(종합본) 원고 작성 — 요약노트 형식 과목별 HTML(+ md·PNG, epub 선택)  별칭: book
  all            s1 → s7 (끝난 단계는 건너뜀. 책은 따로 s8)
  make           제작(무인)    강마다 집필 → 렌더 → 잇기, 끝나면 교재(s8). 메타·게시·등록은 하지 않음.
                               한 강이 실패해도 다음 강으로 넘어가고, 끝에 강별 결과를 정리한다(퇴근 후 돌리기용)
  claim          팀 분담       --only L03,L04 → 이 PC 사람(local.json me)이 맡는다 / release 로 놓기
  me             내 이름        --note "홍길동" → local.json (이 PC 를 쓰는 사람)
  status         강별 진행 상황
  redraw         도식 다시 그리기  영상 테마(backplate.theme) 스타일로 원고 도식 SVG 를 Claude 가 새로 그림(캐시)
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from longform.config import load_job

ALIAS = {"plan": "s1", "compose": "s2", "render": "s3", "stitch": "s4",
         "meta": "s5", "publish": "s6", "register": "s7", "book": "s8", "textbook": "s8",
         # 예전 이름도 받는다
         "curriculum": "s1", "manuscript": "s2", "upload": "s6"}


def _only(v: Optional[str]) -> Optional[List[str]]:
    if not v:
        return None
    out = []
    for x in v.split(","):
        x = x.strip().upper()
        out.append(x if x.startswith("L") else f"L{int(x):02d}")
    return out


def status(job) -> None:
    from longform.report import print_table
    print_table(job)


def make(job, only: Optional[List[str]], a) -> int:
    """제작(무인) — 강 단위로 집필 → 렌더 → 잇기, 마지막에 교재. 실패한 강은 건너뛰고 끝에 정리."""
    import time
    import traceback
    from longform import s1_curriculum, s2_manuscript, s3_render, s4_stitch, s8_textbook, team
    from longform.util import log, read_json, statement
    if not (job.dir / "curriculum.json").exists():
        s1_curriculum.run(job)
    cur = read_json(job.dir / "curriculum.json", {}) or {}
    ids = [L["id"] for L in cur.get("lectures", [])]
    scope = team.scope(job, only, ids, a.force) or (only or ids)
    if only == [] or scope == []:
        print("[info] 돌릴 강이 없습니다")
        return 0
    t0 = time.time()
    result = {}
    log(f"제작(무인) 시작 — {len(scope)}강: {', '.join(scope)}")
    from longform.llm_wait import wait_for_claude
    queue = list(scope)
    retried: set = set()
    while queue:
        lid = queue.pop(0)
        t = time.time()
        step = ""
        try:
            step = "집필"
            s2_manuscript.run(job, [lid], a.force, a.sections)
            step = "렌더"
            s3_render.run(job, [lid], a.force, a.sections)
            if not a.sections:
                step = "잇기"
                s4_stitch.run(job, [lid], a.force)
            result[lid] = ("성공", round((time.time() - t) / 60, 1), "")
            statement("made", f"{job.name}/{lid}", {"min": result[lid][1]})
        except BaseException as e:            # SystemExit 포함 — 한 강의 실패가 밤샘 작업 전체를 멈추지 않게
            if isinstance(e, KeyboardInterrupt):
                raise
            from longform.s3_render import CodexStopped
            if isinstance(e, CodexStopped):        # ★ codex 가 안 되면 다음 강으로 가지 않고 **전체를 멈춘다**
                result[lid] = ("중지", round((time.time() - t) / 60, 1), str(e)[:200])
                log(str(e))
                queue.clear()
                break
            msg = str(e).strip() or e.__class__.__name__
            traceback.print_exc()
            # ★ 엔진 안의 Claude(표지 문구·이미지 설계)가 한도에 걸려 실패했을 수 있다 → 확인하고, 풀리면 이 강을 한 번 더
            if lid not in retried:
                retried.add(lid)
                log(f"{lid} {step} 실패 — Claude 한도인지 확인합니다")
                if wait_for_claude(job):
                    log(f"{lid} 를 다시 시도합니다(끝난 단계는 건너뜀)")
                    queue.insert(0, lid)
                    continue
            result[lid] = ("실패", round((time.time() - t) / 60, 1), f"{step}: {msg[:160]}")
            log(f"[warn] {lid} {step} 실패 — 다음 강으로 넘어갑니다: {msg[:160]}")
        team.sync_from_state(job, [lid])
    ok = [l for l, r in result.items() if r[0] == "성공"]
    if ok and not a.sections:
        try:
            s8_textbook.run(job, None, a.force)        # 교재는 과목 단위라 전체를 다시 묶는다(쓴 절은 캐시)
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            log(f"[warn] 교재 만들기 실패: {e}")
    print()
    print("=" * 60)
    print(f"제작(무인) 결과 — {len(ok)}/{len(result)}강 성공 · 총 {round((time.time() - t0) / 3600, 1)}시간")
    for lid, (st, mins, why) in result.items():
        print(f"  {lid}  {st}  {mins}분  {why}")
    print("=" * 60)
    return 0 if len(ok) == len(result) else 1


def main(argv: Optional[List[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="run.bat", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd")
    ap.add_argument("--job", default="", help="잡 이름(jobs/ 아래 폴더). 하나뿐이면 생략")
    ap.add_argument("--only", help="L01,L02 또는 1,2")
    ap.add_argument("--sections", type=int, help="강마다 앞 N개 섹션만(시험용)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="업로드: 저장 직전에 멈춤")
    ap.add_argument("--max", type=int, help="업로드: 이번에 올릴 최대 편수")
    ap.add_argument("--per", help="decide: 과목별 강 수, 예: 3,7 또는 4+5+5+6")
    ap.add_argument("--target", type=int, help="decide: 강 길이(분)")
    ap.add_argument("--note", default="", help="decide: 이렇게 정한 이유(brief.md 에 남는다)")
    a = ap.parse_args(argv)

    from longform.config import default_job
    job = load_job(a.job or default_job())
    cmd = ALIAS.get(a.cmd, a.cmd)
    only = _only(a.only)

    if cmd == "pack":
        from longform import pack
        pack.run(job)
    elif cmd == "propose":
        from longform import propose
        propose.print_proposals(propose.propose(job))
    elif cmd == "decide":
        if not a.per:
            ap.error("decide 에는 --per 가 필요합니다 (예: --per 3,7)")
        from longform import propose
        propose.decide(job, a.per, a.target, a.note)
    elif cmd == "me":
        from longform import team
        if a.note:
            team.set_me(a.note)
        print(f"이 PC 의 사람: {team.me() or '(없음)'}")
    elif cmd in ("claim", "release"):
        from longform import team
        if not only:
            ap.error(f"{cmd} 에는 --only L01,L02 가 필요합니다")
        if cmd == "claim":
            team.claim(job, only, force=a.force)
        else:
            team.release(job, only, force=a.force)
    elif cmd == "examples":
        from longform import s1_curriculum
        s1_curriculum.refresh_examples(job)
    elif cmd == "redraw":
        from longform import redraw
        redraw.run(job, only)
    elif cmd == "status":
        status(job)
    elif cmd == "login":
        from longform import s6_upload
        s6_upload.login(job)
    elif cmd == "make":
        return make(job, only, a)
    elif cmd == "s8":
        from longform import s8_textbook
        s8_textbook.run(job, only, a.force)
    elif cmd in ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "all"):
        steps = ["s1", "s2", "s3", "s4", "s5", "s6", "s7"] if cmd == "all" else [cmd]
        # 팀 분담 — 남이 맡은 강은 이 PC 에서 돌리지 않는다
        from longform import team
        from longform.util import read_json as _rj
        _cur = _rj(job.dir / "curriculum.json", {}) or {}
        if _cur.get("lectures") and any(x in steps for x in ("s2", "s3", "s4", "s5", "s6")):
            only = team.scope(job, only, [L["id"] for L in _cur["lectures"]], a.force)
            if only == []:
                print("[info] 이 PC 에서 돌릴 담당 강이 없습니다 — 대시보드에서 「맡기」 또는 run.bat claim --only L01")
                return 0
        for st in steps:
            if st == "s1":
                from longform import s1_curriculum
                s1_curriculum.run(job, force=a.force and cmd == "s1")
            elif st == "s2":
                from longform import s2_manuscript
                s2_manuscript.run(job, only, a.force, a.sections)
            elif st == "s3":
                from longform import s3_render
                s3_render.run(job, only, a.force, a.sections)
            elif st == "s4":
                if a.sections:
                    print("[info] --sections 시험 모드에서는 이어붙이기를 건너뜁니다")
                    continue
                from longform import s4_stitch
                s4_stitch.run(job, only, a.force)
            elif st == "s5":
                from longform import s5_meta
                s5_meta.run(job, only, a.force)
            elif st == "s6":
                from longform import s6_upload
                s6_upload.run(job, only, a.dry_run, a.max, a.force)
            elif st == "s7":
                if a.dry_run:
                    continue
                from longform import s7_register
                s7_register.run(job)
        team.sync_from_state(job, only)
    else:
        ap.print_help()
        return 2
    return 0
