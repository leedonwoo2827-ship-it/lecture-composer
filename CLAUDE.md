# Lecture Composer — Claude Code 작업 안내

이 레포는 원고 HTML(요약노트·영상 원고)과 목표를 받아 롱폼 강의를 편성·집필·렌더·게시하는 **강의 편성 엔진**이다.
사용자는 웹앱(`run.bat` 더블클릭)과 이 대화(VSCode 의 Claude Code)를 함께 쓴다. 웹앱의 버튼과 대화는 **같은 CLI**를 부른다.

## 지켜야 할 것
- **레포 밖 경로에 의존하지 않는다.** 원천은 `jobs/<잡>/input/`, 결과는 `jobs/<잡>/` 안에만 둔다. 렌더 엔진은 `engine/backplate/`(vendored).
  다른 폴더·다른 레포를 읽거나 쓰는 코드를 넣지 않는다. PC 절대 경로를 목표서·코드에 적지 않는다(PC마다 다른 값은 job.local.json).
- **`.bat` 파일은 ASCII 영문 + CRLF 만.** 한국어 cmd(CP949)는 UTF-8 한글·LF 를 잘못 읽는다. 한글 안내는 파이썬에서 출력한다.
- 원고 HTML 속성 규칙(영상 원고 형식): h1 `data-say/data-read/data-outro-say/data-outro-read`, h3 `data-id/data-say/data-read`.
  backplate 는 `data-read` 와 h1 여는·닫는 말을 버리므로 렌더 단계가 덮어쓰기(narration)로 확정한다 — 이 경로를 깨지 않는다.
- 실제 YouTube 게시(`publish`)는 사용자가 명시적으로 요청할 때만 돌린다. dry-run 은 괜찮다.

## 명령 (run.bat 이 없으면 `.venv\Scripts\python -m longform ...`)
| 명령 | 하는 일 |
|---|---|
| `run.bat status --job J` | 강별 진행 상황 |
| `run.bat propose --job J` | **강 수 후보표** — 과목별 기존 내레이션(분)·출제 비중·후보별 확장비 → `jobs/J/proposals.json` |
| `run.bat decide --job J --per 4,6 --target 35 --note "이유"` | 강 수를 목표서에 적고 `jobs/J/brief.md` 에 이유를 남긴 뒤 편성(plan)을 새로 한다 |
| `run.bat textbook --job J` | 교재(종합본) 원고 작성 — 요약노트와 같은 HTML 형식(과목별), HWPX 변환은 요약노트와 같은 경로로 |
| `run.bat plan/compose/render/stitch/meta/publish/register --job J [--only L01] [--sections 1] [--force] [--dry-run]` | 각 단계 |

## 「강 수를 정하자」는 요청을 받으면 — **시장조사가 1순위, 확장비는 참고만**
사용자 지시(2026-10-01): "확장비는 상관없고, 시장조사에서 제1의 권고안을 내시길 바랍니다."
1. `run.bat status --job J` 와 원천(`jobs/J/input/`)을 보고 무엇이 들어 있는지 확인한다(요약노트·영상 원고·문항 회차 수).
2. **웹으로 시장조사**: 주요 자격증 인강 업체들의 그 과목 **이론 강의**
   강 수 · 총 시간 · 강당 길이 · 과목별 비중을 찾아 **출처 링크와 함께 표로** 보여 준다. 문제풀이·패키지 묶음은 따로 표시한다.
3. `run.bat propose --job J` 로 과목별 분량과 **회차당 문항 수(출제 비중)** 를 확인한다.
4. **제1 권고안 하나**를 낸다: 과목별 강 수 × 강 길이(분) = 총 시간. 근거는
   - 시장의 범위·중앙값(이론 총 시간)에 맞출 것 — 사용자가 기준으로 든 강의 수준이 있으면 그것(이 PC 메모: `docs/_local/`)
   - 과목 배분은 시험 출제 비중(과락이 있으면 과목 균형)과 시장의 과목별 비중
   - 자사 다른 과정과 포맷 일관(이미 만든 과정의 강 길이·구성)
   대안은 꼭 필요할 때 1개만. 확장비는 결과로만 한 줄 언급한다(높으면 보강 `enrich.web` 등 대응을 덧붙인다).
5. 사용자가 좋다고 하면 `run.bat decide ... --note "<시장조사 근거 요약>"` 로 적고, 편성 결과(강별 제목)를 짧게 보여 준다.
6. 섹션 경계를 손으로 옮기고 싶다고 하면 `jobs/J/curriculum.json` 을 고친다(그 뒤 plan 을 --force 로 돌리면 덮어쓰므로 돌리지 않는다).

## 문항·원천
문항은 별도 문항 앱이 과정별 **책 폴더**의 `_rounds/mNN.json` 에 만든다. 구조·가져오기 규칙은 `docs/원천-가져오기.md`, 이 PC의 실제 책 폴더 표는 `docs/_local/`(깃 제외).
문항이 미확정이면 예시 자리(14분)를 비워 두고 진행하고, 들어오면 `run.bat examples` → compose(집필 재사용) → render.

## 폴더
`longform/`(엔진·파이프라인·웹앱) · `engine/backplate/`(렌더 엔진) · `jobs/<잡>/`(목표서 job.json · brief.md · input · curriculum · manuscripts · out) · `_context/`(받아 둔 원천 — 기획 화면의 「가져올 폴더」로 input/ 에 복사해 쓴다) · `docs/`(매뉴얼)
