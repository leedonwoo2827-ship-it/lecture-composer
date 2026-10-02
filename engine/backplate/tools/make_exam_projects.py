# -*- coding: utf-8 -*-
"""`_context` 의 시험별 이론 HTML을 과목별 프로젝트로 한 번에 만든다.

여기서 하는 일은 딱 둘 — **프로젝트 생성 + 목표 길이(brief) 저장**. 둘 다
공짜다(Claude 를 안 쓴다). 질문 답변 · 목차 확정 · 판단 · 문구 · 대본 · 음성처럼
Claude 를 쓰거나 사람이 봐야 하는 단계는 일부러 여기서 자동으로 돌리지 않는다 —
그건 이 앱의 승인 게이트 설계(1차 화면 · 2차 대본 · 4차 음성)를 건너뛰는 것이라
"주사위를 굴려 좋은 결과가 나오길 바라는" 상황을 만든다. 이 스크립트는 반복되는
6번의 "새 발표" 입력만 대신해 준다.

서버가 떠 있어야 한다(run.bat). 표준 라이브러리만 쓴다.

    .venv-app\\Scripts\\python.exe tools\\make_exam_projects.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
CTX = APP / "_context"

# (참고자료 경로, 제목, 목표 길이(분), 청중, 목표)
#
# ★ 빅데이터분석기사는 4과목이 시험 배점상 비슷한 비중이라 30분씩 동일하게 뒀다.
# ★ SQLD는 공식 문항 배분이 1과목(데이터 모델링의 이해) 10문항 · 2과목(SQL 기본
#   및 활용) 40문항으로 4:1이다 — 그 비율로 목표 길이를 나눴다. 실제 준비 상황에
#   맞게 이 표의 숫자만 고쳐서 다시 실행하면 된다(이미 만든 프로젝트는 새로
#   만들지 않고 건너뛴다).
SUBJECTS = [
    ("bigdata/summary_planning.html", "빅데이터분석기사 · 1과목 분석 기획", 30,
     "빅데이터분석기사 준비생", "1과목(빅데이터 분석 기획) 시험 이론 복습"),
    ("bigdata/summary_explore.html", "빅데이터분석기사 · 2과목 데이터 탐색", 30,
     "빅데이터분석기사 준비생", "2과목(빅데이터 탐색) 시험 이론 복습"),
    ("bigdata/summary_modeling.html", "빅데이터분석기사 · 3과목 데이터 모델링", 30,
     "빅데이터분석기사 준비생", "3과목(빅데이터 모델링) 시험 이론 복습"),
    ("bigdata/summary_interpret.html", "빅데이터분석기사 · 4과목 결과 해석", 30,
     "빅데이터분석기사 준비생", "4과목(빅데이터 결과 해석) 시험 이론 복습"),
    ("sqld/summary_데이터모델링.html", "SQLD · 1과목 데이터 모델링의 이해", 8,
     "SQLD 준비생", "1과목(데이터 모델링의 이해, 10문항) 시험 이론 복습"),
    ("sqld/summary_SQL.html", "SQLD · 2과목 SQL 기본 및 활용", 32,
     "SQLD 준비생", "2과목(SQL 기본 및 활용, 40문항) 시험 이론 복습"),
]


def call(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body if body is not None else {}).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"{method} {path} -> {e.code}: {e.read().decode('utf-8', 'replace')}") from e


def base_url() -> str:
    port = 5178
    cfg_path = APP / "showcase.config.json"
    if cfg_path.is_file():
        try:
            port = json.loads(cfg_path.read_text(encoding="utf-8-sig")).get("port", port)
        except Exception:  # noqa: BLE001
            pass
    return f"http://127.0.0.1:{port}"


def existing_titles(base: str) -> set[str]:
    try:
        return {p.get("title") for p in call(base, "GET", "/api/projects")}  # type: ignore[misc]
    except Exception:  # noqa: BLE001
        return set()


def main() -> None:
    base = base_url()
    try:
        call(base, "GET", "/api/health")
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 서버에 연결할 수 없습니다({base}) — 먼저 run.bat 을 실행하세요.\n  {e}")
        sys.exit(1)

    have = existing_titles(base)
    for rel, title, target_min, audience, goal in SUBJECTS:
        if title in have:
            print(f"[SKIP] 이미 있음: {title}")
            continue
        html = CTX / rel
        if not html.is_file():
            print(f"[SKIP] 파일 없음: {html}")
            continue
        doc = call(base, "POST", "/api/projects", {"title": title, "refs": [str(html)]})
        pid = doc["id"]
        call(base, "POST", f"/api/projects/{pid}/brief",
             {"answers": {"target_min": target_min, "audience": audience, "goal": goal}})
        print(f"[OK] #{pid}  {title}  (목표 {target_min}분)  refs={rel}")

    print(f"\n{base} 을 열어 각 프로젝트에서 질문 답변 → 기획서 → 목차 확정 → "
          "판단/문구/대본 → 음성 순으로 직접 진행하세요.")


if __name__ == "__main__":
    main()
