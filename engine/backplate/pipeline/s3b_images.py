# -*- coding: utf-8 -*-
"""S3b 슬라이드 이미지 — **파일로만 주고받는다.**

그림이 들어가는 장에 그림이 들어간다. 그 그림은 이 앱이 만들지 않는다.
이미지 스튜디오(`codex-prompt-img-studio` · `260628-로컬이미지_앞에프롬프트필더`)가
ChatGPT OAuth 로 만들고, 여기는 **Claude 구독 OAuth** 를 쓴다. 둘을 코드로 잇지 않는다.

    이 앱  →  09_이미지/이미지프롬프트.json   (지시문 목록)
              ↓  사람이 이미지 앱에 넣고 돌린다
    이 앱  ←  09_이미지/005.png              (번호가 곧 슬라이드 번호)

★ 브릿지를 만들지 않는 이유는 취향이 아니라 사고 예방이다. 두 앱은 인증 주체가
  다르고, 프로세스를 이어 붙이면 한쪽 세션이 다른 쪽 계정으로 도는 사고가 난다.
  **접점은 폴더 하나**고, 그 폴더는 사람이 눈으로 볼 수 있다.

── 두 레인 ──────────────────────────────────────────────────────────────
`html`        원고 장. 그림이 **몸통을 통째로 대신한다**(제목만 위에 남는다).
              작가 에이전트에서 온 장이 전부 이 레인이다.
`text_image`  예전 캡처 레인. 글 옆에 그림이 붙는다.

★ 예전에는 `text_image` 하나뿐이었다. 그래서 원고 장(`html`)에는 **그림 자리가
  아예 안 생겼다** — 지시문을 아무리 잘 써도 붙을 데가 없었다.

── 이 단계가 하는 일 ────────────────────────────────────────────────────
지시문을 **만들지 않는다**(그건 S3a 다). 원장에서 꺼내 번호를 매겨 내보내고,
돌아온 그림을 번호로 집는다. 그래서 **결정론**이고, 그림 한 장을 넣을 때마다
다시 돌려도 돈이 들지 않는다.

    이미지프롬프트.json         전부. 이미지 스튜디오에 통째로 넣는 것
    이미지프롬프트_부족분.json   새로 생겼거나 몸통이 바뀐 장만 — 없으면 파일이 없다
    이름바꾸기.txt              번호만 밀린 그림 — 없으면 파일이 없다

★ **부족분과 이름 바꾸기가 이 단계의 값이다.** 원고를 고쳐 앞에 장이 하나
  끼어들면 번호가 전부 밀려서 이미 그린 `005.png` 가 남의 장 그림이 된다.
  원장(`core/ledger.py`)이 프롬프트를 **번호가 아니라 이름표**에 매달아 두므로,
  여기서 「무엇이 몇 번에서 몇 번으로 갔는지」를 표로 낼 수 있다. 그 장들은
  내용이 그대로다 — 다시 그리는 게 아니라 이름만 바꾸면 된다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import config, ledger as lg, workspace as ws
from pipeline.s3a_imgprompt import labels_of
from pipeline.registry import STAGES, cached_data, write_cache
from pipeline.s3a_imgprompt import WANT_MEDIA, is_full, slide_id

# 맛보기 파일에 담을 장 수. **지금은 안 쓴다** — 맛보기를 내지 않기로 했다
# (2026-08-17, 아래 내보내기 자리 참고). 되살릴 때 쓰라고 값만 남겨 둔다.
# 프롬프트 결을 보는 데는 셋이면 됐다 — 첫 장(도입)·둘째·셋째면 배치 갈래도
# 두세 가지가 섞여 나온다.
TRY_N = 3

FILE_NAMING = ("생성한 이미지는 images/ 폴더에 '슬라이드번호'로 저장하세요. "
               "예: 003.png → 3번 슬라이드. 파일명 앞 숫자만 맞으면 되고 "
               "확장자·뒤 설명은 자유입니다(003_저축함수.png).")


def bundle(*, deck: str, cfg: Dict[str, Any], rows: List[Dict[str, Any]],
           deck_slides: int, full: bool = False) -> Dict[str, Any]:
    """이미지 스튜디오가 먹는 봉투 하나.

    ★ 모양은 받은 표본(`교육방법 및 교육공학_4주차_슬라이드_이미지프롬프트.json`,
      34개)과 같은 아홉 칸이다. 그 앱이 실제로 읽는 것은 `prompts[].prompt` 하나
      뿐이지만, 사람이 두 파일을 나란히 놓고 볼 것이고 그 표본이 사실상의 표준이다.
    """
    return {
        "deck": deck,
        # ★ **장마다 다른 글을 여기 넣으면 안 된다.** 스튜디오는 이 칸을 「모든
        #   프롬프트에 공통으로 붙는 문체」로 보고 전 장에 덧붙인다. 예전엔 첫 행
        #   프롬프트에서 문체를 잘라 썼는데(영어 한 줄이라 그게 통했다), 한국어
        #   다섯 칸으로 바꾸면서 **1번 장의 헤드라인·서브카피가 통째로 실려** 갔다
        #   — 27장이 전부 "같은 경제, 다른 렌즈" 를 이고 나왔다(2026-08-14 실측).
        #   그래서 여기는 **색·문체만** 적는다. 장마다 다른 것은 절대 넣지 않는다.
        "style_hint": (
            f"진한 파랑({cfg['image']['accent_a']})과 "
            f"밝은 파랑({cfg['image']['accent_b']}) 중심, 슬레이트(#334155) 글자, "
            "플랫 벡터에 은은한 입체감, 균일한 선 굵기, 넉넉한 여백"),
        # ★ **판마다 비율이 다르다**(2026-08-29).
        #   전면 판 — 그림을 **16:9(1920×1080)로 받는다.** 화면과 비율이 같아
        #     잘리는 데가 없다. 예전에는 3:2 밖에 못 내는 스튜디오를 쓰느라 아래
        #     15.6% 를 잘라야 했고, 그 자리를 비워 달라고 두 판(8·9판)을 썼지만
        #     15장 전부가 넘겼다. 그리는 쪽이 16:9 를 내주면 그 싸움이 없어진다.
        #   액자 판 — 3:2 그대로다. 옛 프로젝트의 그림이 그 비율로 그려져 있다.
        "aspect": "16:9" if full else cfg["image"]["aspect"],
        "target_box": (
            "16:9 (1920×1080) — 두 칸으로 나뉜 판이다. 1칸 제목칸 y=0~108 은 "
            "아이보리 단색으로 비우고(발표 화면의 제목이 얹힌다), 2칸 그림칸 "
            "y=108~1080 에 장면과 글자를 네 가장자리까지 채운다. 발표 화면과 "
            "비율이 같아 **한 픽셀도 잘리지 않는다**"
            if full else
            "wide horizontal panel (3:2), cropped to 16:9 to fill the slide"),
        "count": len(rows),
        "deck_slides": deck_slides,
        "photos_found": 0,
        "file_naming": FILE_NAMING,
        "prompts": rows,
    }


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s3b-images"]
    cfg = config.load()
    full = is_full(project)      # 전면 판인가 — 봉투의 `target_box` 가 갈린다

    outline = cached_data(pid, slug, "s2b-outline") or {}
    slides = outline.get("slides") or []
    if not slides:
        raise RuntimeError("구조 설계(s2b-outline)를 먼저 돌리세요")

    targets = [s for s in slides if s.get("media_kind") in WANT_MEDIA]
    d = ws.step_dir(pid, slug, "images")

    # ★ 그림 번호는 **목차 번호**를 그대로 쓴다. 사람이 표지를 빼도 바꾸지 않는다 —
    #   그림은 목차가 굳은 시점에 그 번호로 만들어졌고, 뺀 장은 렌더러가 화면에서만
    #   지운다. 여기서 「보이는 순서」로 다시 세면 이미 붙어 있던 그림이 통째로
    #   한 칸 밀린다(2026-08-15 에 그렇게 고쳤다가 되돌렸다).

    # ── 번호를 매긴다 ────────────────────────────────────────────────────────
    # ★ 번호는 **덱이 안다.** 세지 않고 받는다 — 그림 장이 띄엄띄엄한 덱(영상·글이
    #   섞인 덱)에서 세면 통째로 밀린다. 표지가 1번이라 원고 첫 장이 2번이고,
    #   그래서 `003.png` 가 3번 장에 그대로 붙는다.
    book = ws.load_ledger(pid, slug)
    by_id: Dict[str, Any] = book.get("by_id") or {}
    pairs = [(slide_id(slug, s), int(s["no"])) for s in targets]
    plan = lg.number_at(book, pairs)
    n_of, renames, fresh = plan["n_of"], plan["renames"], plan["fresh"]
    # ★ 부족분은 **새 장 + 지시문이 다시 만들어진 장**이다. 번호만 밀린 장은 여기
    #   안 들어간다 — 그건 이름만 바꾸면 되는 장이고, 다시 그리라고 하면 이 앱이
    #   막으려던 바로 그 낭비가 된다.
    need = set(fresh) | set(plan["dirty"])

    # ★ **썸네일은 본문 파일에 넣지 않는다.** 봉투가 다르다 — 본문 그림은 3:2
    #   플랫 벡터이고 썸네일은 16:9 클레이메이션이라, 같은 목록에 섞으면 스튜디오가
    #   표지를 본문 결로 그린다(2026-08-19: 22장에서 `001.png`·`034.png` 가 본문
    #   지시문으로 나왔다 — 본문은 2~33장이라 `002` 부터여야 한다).
    # ★ 번호는 그대로 매긴다. 썸네일도 `001.png`·`034.png` 자리를 가지므로,
    #   받은 그림을 그 이름으로 넣으면 여기가 알아서 집는다.
    thumb_ids = {slide_id(slug, s) for s in targets
                 if s.get("media_kind") == "thumb"}

    rows: List[Dict[str, Any]] = []
    gap: List[Dict[str, Any]] = []
    miss: List[str] = []
    for did, n in pairs:
        if did in thumb_ids:
            continue                 # 「썸네일프롬프트.json」으로만 나간다
        e = by_id.get(did) or {}
        prompt = (e.get("prompt") or "").strip()
        if not prompt:
            miss.append(did)
            continue
        row = {
            "n": n,
            "title": e.get("title") or "",
            "type": e.get("type") or "photo",
            "level": e.get("level") or "이해",
            "prompt": prompt,
            "negative": cfg["image"]["negative"],
            "keywords": e.get("keywords") or [],
            "place": True,
            # ★ 규격 밖의 칸 둘. 스튜디오는 안 읽고 **사람이 읽는다.**
            #   file    한 장만 다시 뽑을 때 어떤 이름으로 저장할지 — 번호를
            #           세 자리로 맞추는 일을 사람에게 시키지 않는다
            #   data_id 번호만 있는 JSON 을 나중에 열면 어느 장인지 알 수 없다
            "file": f"{n:03d}.png",
            "data_id": did,
        }
        # ★ 11판: 그림이 **비운 자리**에 화면이 얹을 글. 스튜디오는 안 읽지만
        #   사람이 JSON 을 열었을 때 "이 장에 무슨 글이 붙는지" 보여야 하고,
        #   그림을 다시 뽑을 때 자리가 맞는지 대조할 수 있어야 한다.
        _lb = labels_of(e)
        if _lb:
            row["labels"] = _lb
        rows.append(row)
        if did in need:
            gap.append(row)

    deck = project.get("title") or slug
    total = len(slides)

    # ★ 이 폴더는 **사람이 여는 자리**다 — 이미지 스튜디오와의 유일한 접점이고,
    #   열었을 때 집어야 할 파일이 **하나로 보여야 한다**(2026-08-14) — 처음
    #   보는 사람은 여럿 중 무엇을 집을지 모른다. 기계가 읽는 것은 `bak/` 으로 내린다.
    bak = d / ws.BAK
    if rows:
        p_all = ws.write_json(d / "이미지프롬프트.json",
                              bundle(deck=deck, cfg=cfg, rows=rows,
                                     deck_slides=total, full=full))
        # 예전 이름 — 이미 이 파일명을 아는 이미지 앱이 있다. 같은 행을 그대로 쓴다.
        ws.write_json(bak / "slides.json", {
            "schema": "codex-studio-slides@1", "project": deck,
            "count": len(rows), "prompts": rows,
        })
        (d / "slides.json").unlink(missing_ok=True)      # 옛 자리에 두 벌로 남기지 않는다
        job.add_log(f"지시문 {len(rows)}개 "
                    f"(본문 {len(targets) - len(thumb_ids)}장 중) → {p_all}")

        # ★ **맛보기 파일은 안 낸다**(2026-08-17).
        #   프롬프트 꼴이 자주 바뀌던 때는 세 장만 먼저 뽑아 결을 보는 값이 있었다.
        #   지금은 꼴이 앉았고, 사람은 전체를 한 번에 돌린다. 그러면 이 파일은
        #   **집어야 할 파일이 둘로 보이게** 만들 뿐이다 — 이 폴더는 열었을 때
        #   하나만 보여야 한다(아래 「사람이 여는 자리」 규칙과 같은 이유).
        #   되살리려면 이 자리에 다시 쓰면 된다(`TRY_N` 은 남겨 둔다).
        (d / "이미지프롬프트_맛보기.json").unlink(missing_ok=True)

        # ★ **썸네일 지시문도 여기서 낸다** — 스튜디오가 바로 먹는 꼴로 두 벌.
        #   예전에는 원고 한 장(`유튜브썸네일-원고.txt`)을 내고 사람이 그것을
        #   「프롬프트 생성기」에 넣어 프롬프트를 다시 짓게 했다. 한 다리를 더
        #   건너는 만큼 결이 그때그때 달라졌다 — 그래서 이미지 JSON 을 낼 때
        #   썸네일 JSON 도 같이 낸다(2026-08-17).
        # ★ 봉투를 **따로** 낸다. 슬라이드 그림은 3:2 플랫 벡터이고 썸네일은
        #   16:9 클레이메이션이라, 한 봉투에 섞으면 `style_hint` 가 전 장에
        #   덧붙어 슬라이드까지 점토로 나온다.
        try:
            from render import thumbnail
            # `_headline` 이 읽는 두 칸만 있으면 된다 — 이름표와 제목
            # 썸네일 제목거리는 **본문에서** 뽑는다 — 표지·마무리를 넣으면
            # 「제22장」·「마무리」가 소재로 올라와 후킹이 흐려진다
            th_deck = {"slides": [{"data_id": did, "title": (by_id.get(did) or {}).get("title") or ""}
                                  for did, _ in pairs if did not in thumb_ids]}
            p_th = ws.write_json(d / "썸네일프롬프트.json",
                                 thumbnail.bundle(th_deck, title=deck, cfg=cfg,
                                                  led=by_id, full=full,
                                                  book=str(project.get("book") or "")))
            job.add_log(f"썸네일 지시문 2벌(후킹형·차분형) → {p_th}")
        except Exception as e:                      # noqa: BLE001
            # 그림 지시문은 이미 나왔다 — 곁다리가 실패해도 그것까지 버리지 않는다
            job.add_log(f"썸네일 지시문은 못 만들었습니다: {type(e).__name__}: {e}")
    else:
        job.add_log("지시문이 하나도 없습니다 — 그림 지시문(s3a-imgprompt)을 먼저 돌리세요")

    # ★ 부족분은 **다시 그릴 장만** 추린 것이다(새 장 + 몸통이 바뀐 장). 원고를
    #   고쳤을 때 스물일곱 장을 다 다시 그리지 않게 하려고 있다.
    #   ★ 그런데 **처음 만들 때는 전부 새 장**이라 전체 파일과 글자 하나 안 다르다.
    #     같은 것이 이름만 달리해 둘이면 사람은 "무엇이 다른가" 를 찾느라 시간을
    #     쓴다. 진짜 부분집합일 때만 낸다(2026-08-14: "부족분이 뭐에요?").
    gap_file = d / "이미지프롬프트_부족분.json"
    if gap and len(gap) < len(rows):
        p_gap = ws.write_json(gap_file, bundle(deck=deck + " (부족분)", cfg=cfg, full=full,
                                               rows=gap, deck_slides=total))
        job.add_log(f"부족분 {len(gap)}개 (새 장 {len(fresh)}개 · 몸통이 바뀐 장 "
                    f"{len(plan['dirty'])}개) → {p_gap}")
    else:
        # ★ 없으면 **지운다.** 지난번 부족분이 남아 있으면 사람이 그것을 집어
        #   이미 그린 그림을 다시 그린다 — 이 앱이 막으려던 바로 그 일이다.
        gap_file.unlink(missing_ok=True)
        if rows and gap:
            job.add_log(f"전부 새 장({len(gap)}개)이라 부족분을 따로 안 냅니다 — "
                        "이미지프롬프트.json 하나면 됩니다")
        elif rows:
            job.add_log("부족분 없음 — 지난번에 만든 그림을 그대로 쓰면 됩니다")

    # 이름 바꾸기 표 — 사람이 탐색기에서 보고 옮긴다. 자동으로 옮기지 않는다:
    # 그림 폴더는 사람이 이미지 앱에서 받아 오는 자리고, 남의 폴더를 건드리는
    # 코드는 잘못 돌았을 때 되돌릴 방법이 없다.
    ren_file = d / "이름바꾸기.txt"
    if renames:
        lines = ["번호가 밀린 그림입니다. 이미지 폴더에서 아래대로 이름을 바꾸세요.",
                 "★ 이 장들은 **내용이 그대로**입니다 — 다시 그리지 말고 이름만 바꾸세요.",
                 "★ 뒤에서부터 바꾸세요 — 앞에서부터 하면 아직 안 바꾼 파일을 덮어씁니다.",
                 ""]
        # ★ 뒤에서부터. `-r[1]` 은 **새 번호** 내림차순이다.
        for old, new, did in sorted(renames, key=lambda r: -r[1]):
            lines.append(f"{old:03d}.png  →  {new:03d}.png    {did}  "
                         f"{(by_id.get(did) or {}).get('title') or ''}")
        p_ren = ws.write_text(ren_file, "\n".join(lines) + "\n")
        job.add_log(f"번호만 밀린 그림 {len(renames)}개 → {p_ren}")
        job.add_log("★ 이 장들은 내용이 그대로입니다. 다시 그리지 말고 이름만 바꾸세요")
    else:
        ren_file.unlink(missing_ok=True)

    # ── 돌아온 그림을 번호로 집는다 ──────────────────────────────────────────
    # ★ 그림은 **두 곳**에서 온다. 규칙은 하나 — 파일명이 번호로 시작하면 그 장이다.
    #     09_이미지/       이미지 스튜디오가 낸 것
    #     00_기획/참고/    기획서가 "이 캡처가 필요합니다" 해서 사람이 찍어 넣은 것
    #   요청(기획서)과 납품(참고 폴더)이 한 자리에 있어야 잊히지 않는다.
    ref_dir = ws.sub_dir(pid, slug, "prd", "참고", create=False)

    # ★ 한 장에 **여러 그림**을 넣을 수 있다. 멘토링처럼 신청 화면과 수락 화면이
    #   따로 있는 메뉴는 한 컷으로 안 된다. 규칙은 번호 뒤에 `-2`, `-3`:
    #       005.png · 005-2.png · 005-3.png
    #   순서는 파일명 순이고, 발표에서 대본 시간을 나눠 차례로 넘어간다.
    found: Dict[str, Any] = {}
    missing: List[int] = []
    EXT = (".png", ".webp", ".jpg", ".jpeg")
    for s in targets:
        no = s["no"]
        shots: List[Dict[str, Any]] = []

        def add(f: Path, step: str) -> None:
            shots.append({"file": f"{step}/{f.name}", "name": f.name,
                          "bytes": f.stat().st_size,
                          "from": "참고" if step.endswith("참고") else "이미지"})

        for base, step in ((d, ws.STEPS["images"][0]),
                           (ref_dir, f"{ws.STEPS['prd'][0]}/참고")):
            if not base.is_dir():
                continue
            for f in sorted(base.iterdir()):
                if not (f.is_file() and f.suffix.lower() in EXT):
                    continue
                stem = re.sub(r"^\d{2}-", "", f.stem)       # 참고 폴더의 복사 접두 제거
                m = re.match(r"^0*(\d{1,3})(?:-(\d+))?$", stem)
                if m and int(m.group(1)) == no:
                    add(f, step)
        if shots:
            found[str(no)] = {**shots[0], "shots": shots, "count": len(shots)}
        else:
            missing.append(no)

    multi = [k for k, v in found.items() if v.get("count", 1) > 1]
    if multi:
        job.add_log("그림 여러 장인 슬라이드: "
                    + ", ".join(f"{k}({found[k]['count']}장)" for k in sorted(multi, key=int)))
    n_ref = sum(1 for v in found.values() if v.get("from") == "참고")
    job.add_log(f"이미지가 필요한 장 {len(targets)}개 → 도착 {len(found)}개"
                + (f" (참고 폴더에서 {n_ref}개)" if n_ref else ""))
    if missing:
        job.add_log(f"아직 없는 그림: {missing[:20]}{' …' if len(missing) > 20 else ''}")
        job.add_log(f"번호로 넣으면 붙습니다 — {d}")
        job.add_log(f"  또는 직접 찍은 캡처를 {ref_dir} 에 005.png 처럼")

    # ★ 파일을 다 쓴 **뒤에** 번호를 원장에 찍는다. 쓰다 실패했는데 번호를 찍으면
    #   다음 내보내기가 「바뀐 것 없음」 이라 말하고 이름바꾸기 표가 영영 안 나온다.
    if rows:
        ws.save_ledger(pid, slug, lg.stamp(book, n_of))

    warn: List[str] = []
    if miss:
        warn.append(f"지시문이 없는 장 {len(miss)}개")
        job.add_log(f"지시문이 없어 뺀 장: {', '.join(miss[:10])}")
    if missing:
        warn.append(f"그림이 없는 장 {len(missing)}개")

    return write_cache(pid, slug, "s3b-images",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"dir": str(d), "targets": [s["no"] for s in targets],
                             "images": found, "missing": missing,
                             "prompts": len(rows), "gap": len(gap),
                             "renames": [[o, n, i] for o, n, i in renames],
                             "no_prompt": miss},
                       code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s3b-images"].run = run
