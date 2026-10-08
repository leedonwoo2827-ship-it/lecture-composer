# Lecture Composer — 강의 편성 엔진

> **원고 HTML과 목표를 넣으면, LLM이 그 목표에 맞게 강의를 다시 짜고 → 영상으로 굽고 → YouTube에 올리고 → 사이트에 등록한다.**
> 같은 원고에서 **교재(종합본) 원고**도 만든다.

자격증 이론 강의처럼 "요약노트 + 문항 은행"이 있는 과정을 롱폼 강의 시리즈(예: 20강 × 35분)로 만드는 도구입니다.
렌더 엔진은 [backplate-studio](https://github.com/leedonwoo2827-ship-it/backplate-studio)(이 레포의 `engine/backplate/`에 포함), 원고 형식은 [summaryhtml2videoscripthtml](https://github.com/leedonwoo2827-ship-it/summaryhtml2videoscripthtml)과 같습니다.

---

## 용어

| 용어 | 뜻 | 이 레포에서 |
|---|---|---|
| **패키지** | 이 레포 전체. 설치해서 쓰는 단위 | `setup.bat` · `run.bat` |
| **엔진** | 목표를 받아 강의 원고로 바꾸는 핵심. **편성 + 집필** | `s1 plan` + `s2 compose` |
| **에이전트** | 엔진 안에서 LLM(Claude)이 맡는 역할. 판단과 글쓰기만 하고, 순서와 검증은 코드가 쥔다 | 집필(s2) · 교재(s8) |
| **파이프라인** | 원천에서 게시·등록·교재까지 이어지는 단계 전체 | `s1`~`s8` |
| **잡(job)** | 과정 하나를 처리하는 단위. 폴더 하나 | `jobs/<잡>/` (예시: `jobs/example/`) |
| **목표서** | 잡의 목표와 설정. 과정 이름, 강 수, 강 길이, 그림 방식, 보강 여부, 채널, 공개 범위 | `jobs/<잡>/job.json` |
| **원천** | 엔진에 넣는 재료 — 요약노트(구조·문항 근거), 영상 원고(검수된 내레이션·발음·도식), 문항(기출 맛보기) | `jobs/<잡>/input/` |
| **편성표** | 강을 어떻게 나눌지, 강마다 어떤 예시 문항을 쓸지 정한 표. 사람이 고쳐도 된다 | `curriculum.json` |
| **강의 원고** | 집필 결과. 섹션 하나에 HTML 하나 | `manuscripts/Lxx/<섹션>.html/.json` |
| 강 / 섹션 / 소주제 / 장 | 영상 한 편 / 노트 h2 / 노트 h3 / 슬라이드 한 장 | `L01` / `s1-02` / `s1-02-03` / `L01-s1-02-007` |
| **보강** | (선택) 웹 검색으로 사례·경향을 덧붙이는 일. 원천이 늘 우선 | `enrich.web` |

### 원고 HTML 속성 (영상 원고 형식 그대로)

| 위치 | 속성 | 뜻 | backplate에 넘기는 방법 |
|---|---|---|---|
| h1 | `data-say` / `data-read` | 표지에서 할 여는 말 / 그 발음 | 표지 장의 덮어쓰기 `narration` |
| h1 | `data-outro-say` / `data-outro-read` | 마무리에서 할 닫는 말 / 그 발음 | 맺음 장의 덮어쓰기 `narration` |
| h3 | `data-id` | 장의 이름표. 그림이 여기 매달린다 | backplate 이미지 원장 키 |
| h3 | `data-say` | 자막이자 내레이션 | `narration.srt_text` |
| h3 | `data-read` | 소리 나는 대로 적은 발음(다를 때만, 예: 2번 → 이 번, KDD → 케이디디) | `narration.text` = TTS 입력 |
| h3 | `data-src` / `data-fig` | 근거가 된 기존 원고 id / 이 장의 도식 번호 | — / PNG로 구워 장 그림으로 |

⚠ backplate는 원래 `data-read`와 h1의 여는 말·닫는 말을 읽지 않습니다. 그래서 렌더 단계가 장마다 **덮어쓰기(`deck.overrides.json`)로 자막·발음을 확정**합니다.

---

## 단계

```
 원천 ─┬ 요약노트 ──┐
       ├ 영상 원고 ─┼─ s1 편성 ─▶ 편성표 ─ s2 집필 ─▶ 강의 원고 ─ s3 렌더 ─ s4 잇기 ─ s5 메타 ─ s6 게시 ─ s7 등록
       └ 문항 ─────┘                        (에이전트, +보강)   (backplate)                         (YouTube)
                                                         └─ s8 교재 ─▶ 과목별 HTML(+ md·PNG, EPUB 선택)
```

| 단계 | 이름 | 하는 일 | 결과물 |
|---|---|---|---|
| `propose` · `decide` | 기획 | 강 수 후보표(분량·출제 비중) / 정한 강 수를 목표서와 `brief.md`에 기록 | `proposals.json`, `brief.md` |
| `s1` | `plan` 편성 | 섹션을 과목 순서대로 묶어 강을 나눔. 강마다 예시 문항을 노트 근거로 고름 | `curriculum.json` (사람이 고쳐도 됨) |
| `examples` | 문항 반영 | 문항이 나중에 들어오거나 바뀌면 강 나누기는 그대로 두고 예시만 다시 고름 | `curriculum.json` |
| `s2` | `compose` 집필 | 섹션마다 집필 에이전트가 목표 분량으로 원고를 씀(검수된 내레이션을 뼈대로). 기출 맛보기(문제 카드 + 풀이)는 문항 데이터로 | `manuscripts/` |
| `s3` | `render` 렌더 | 섹션마다 backplate 프로젝트: 구조 → 자막·발음 확정 → 배경(codex)·도식·문제 카드 PNG → TTS → 자막 → 모션 | `out/Lxx/parts/*.mp4` |
| `s4` | `stitch` 잇기 | 섹션을 무손실로 잇고 −16 LUFS, 챕터, 합본 SRT | `out/Lxx/Lxx.mp4/.srt` |
| `s5` | `meta` 메타 | 제목, 설명(챕터·사이트 링크), 태그, 썸네일(HTML로 그림) | `meta/` |
| `s6` | `publish` 게시 | YouTube Studio 자동 업로드(Playwright): 재생목록, 아동용 아님, 일부공개, 영상 ID 기록 | `out/youtube_ids.json` |
| `s7` | `register` 등록 | 사이트용 영상 맵, 강 목록을 넣은 리뷰 페이지 사본, 기록 | `out/register/` |
| `s8` | `textbook` 교재 | 교재(종합본) 원고를 새로 씀(요약노트=사실, 강의 원고=설명 흐름). 요약노트와 같은 형식의 과목별 HTML | `out/textbook/` |
| `make` | 제작(무인) | 강마다 집필 → 렌더 → 잇기, 끝나면 교재. 게시는 하지 않음. 실패한 강은 건너뛰고 끝에 강별 결과 정리 | — |

모든 단계는 **입력 해시로 재시작**할 수 있습니다. 같은 명령을 다시 실행하면 끝난 것은 건너뜁니다.

- **Claude 사용 한도**(5시간 창·주간)에 걸리면 재설정 시각까지 기다렸다가 이어서 합니다(`llm.limit_wait_hours`).
- **codex(배경 그림)**가 한도에 걸리면 다른 계정 칸으로 넘어가고, 칸이 없거나 모두 막히면 **작업을 멈춥니다**(그림 없이 넘어가지 않음, `accounts.codex_wait_hours`).
- 문항이 아직 확정되지 않았으면 기출 맛보기 자리(`curriculum.examples_budget_min`, 기본 14분)를 비워 둔 채 진행하고, 들어오면 `examples` → `compose`(저장된 집필 재사용) → `render`.

## 강 수는 대화로 정합니다

강 수는 정답이 없는 결정이라, 코드는 **후보와 근거**(분량·출제 비중)까지만 냅니다. 기준은 **시장조사가 1순위**(경쟁 인강의 강 수·총 시간·과목 비중)입니다.
VSCode의 Claude Code에서 "jobs/<잡>의 강 수를 정하자"라고 하면 `CLAUDE.md` 절차대로 진행합니다. 기획 화면에 그 프롬프트가 준비되어 있습니다.

## 설치 · 실행

준비물(PATH): Windows, Python 3.11–3.13, Node 22+, git + git-lfs, ffmpeg, Google Chrome, `claude` CLI(로그인), `codex` CLI(로그인 — 배경 그림).

```bat
setup.bat        :: .venv · Playwright · FastAPI · 렌더 엔진(engine/backplate) 설치 · 점검
run.bat          :: (더블클릭) 웹앱 → http://127.0.0.1:5190
```

**웹앱**은 CLI를 대신 눌러 주는 리모컨입니다. 실제 일은 같은 `python -m longform <단계>` 하위 프로세스가 합니다.

| 탭 | 하는 일 |
|---|---|
| 대시보드 | 실행 옵션 + 단계 카드(하나씩 실행) + 강별 진행표(행마다 버튼) + 실시간 로그 |
| 원고·결과 보기 | 섹션 원고 HTML 미리보기, 섹션/완성 mp4, 썸네일, 교재 |
| 목표서 | `job.json` · `job.local.json` · `curriculum.json` 편집(검증 후 저장) |
| 기획(새 IP·강 수) | ① 새 잡 + 가져올 폴더 → ② 원천 파일(끌어다 놓기, 자동 판별) → ③ Claude Code에 할 말 → ④ 강 수 후보표·직접 정하기 |
| 계정·로그인 | 내 이름(팀 분담), Claude, YouTube, **codex 계정 칸**(여러 개 등록·자동 전환·칸별 사용량) |

```bat
run.bat make --job <잡>                       :: 제작(무인): 집필 → 렌더 → 잇기 → 교재
run.bat all --job <잡> --only L01 --sections 1  :: 1강의 첫 섹션만 시험
run.bat publish --job <잡> --only L01 --dry-run :: 게시 저장 직전에서 멈춤
```

- `.bat` 파일에는 **ASCII 영문과 CRLF 줄바꿈만** 씁니다(한국어 Windows cmd가 UTF-8 한글·LF를 잘못 읽음). `.gitattributes`가 CRLF를 고정합니다.
- 잡이 하나면 `--job`을 생략할 수 있습니다. 새 과정은 `jobs/example/job.json`을 복사하거나 기획 화면의 「새 IP」로 만듭니다.
- PC마다 다른 값은 `jobs/<잡>/job.local.json`에 덮어쓸 것만 적습니다(깃 제외).
- **이 레포는 다른 폴더나 다른 레포에 기대지 않습니다.** 원천은 `jobs/<잡>/input/`, 결과는 `jobs/<잡>/` 안에 생깁니다. `jobs/` 아래 실제 잡(원천·원고·영상)은 깃에 올리지 않습니다.

## 목표서(job.json)의 주요 칸

| 칸 | 뜻 |
|---|---|
| `course.role` · `short` · `exam` · `series` · `full` | 과정 이름들 — 집필 지시문, 여는 말, 유튜브 제목·설명·썸네일 |
| `curriculum.lectures_per_subject` · `target_min` | 과목별 강 수(비우면 분량으로 자동) · 강 길이(분) |
| `curriculum.examples_per_lecture` · `examples_budget_min` | 강당 예시 문항 수 · 기출 맛보기 시간 예산(분) |
| `manuscript.figs_per_lecture` | 강당 도식 목표. 모자라면 집필 에이전트가 노트 내용으로 SVG를 그림 |
| `enrich.web` | 보강(웹 검색). 원천이 우선, 정의·공식은 바꾸지 않음, 출처를 남김 |
| `backplate.image_mode` · `bg_per_section` | 배경 그림 방식: `section`(섹션마다 N장, 기본) · `shared` · `per-slide` · `backplate`(엔진 방식) · `none` |
| `subtitles.reserve_bottom` · `burn_in` | 하단 자막 자리 비우기(SRT를 mp4와 함께 올리는 경우) · 영상에 굽기 |
| `youtube.*` | 채널, 공개 범위(기본 일부공개), 재생목록, 사이트 링크, 태그 |
| `book_export.*` | 교재 문체(prose/lecture), EPUB 여부 |
| `llm.limit_wait_hours` · `accounts.codex_wait_hours` | Claude 한도 대기 시간 · codex 한도 대기(0이면 바로 멈춤) |

## 그림

- **배경:** codex가 섹션마다 `bg_per_section`장(기본 3)을 그리고, 같은 덩이의 슬라이드가 공유합니다. 화면 변화는 라벨 애니메이션과 도식이 맡습니다.
- **도식·표·문제 카드:** codex 없이 Playwright로 PNG를 굽습니다(흰 카드 · 표 스타일 · SQL 코드 상자 · ①②③④ 보기).
- **화면 글자(라벨):** 원고의 판서를 그대로 쓰고, 등장·빛 효과는 글자에만 걸립니다. 아래 14%는 자막 자리로 비웁니다.

### 영상 테마 — 「단정 스케치북」(`backplate.theme: "danjeong"`)
SUIT 굵은 글꼴 · 덩이마다 바뀌는 바탕 · 유기적 덩어리 · 종이 결 · 먹선 손그림 사물(codex 투명 PNG) · 그어지는 낙서 장식 · 테마 스타일로 **다시 그린 도식** · **말소리(STT)에 맞춰 타이핑되는 라벨**.
미리보기 `tools/theme_preview.py`, 자세한 것은 [docs/테마-단정.md](docs/테마-단정.md). 비우면 기존 아이보리 룩 그대로.

## 게시

- 구글은 Playwright가 띄운 브라우저의 로그인을 막으므로, **진짜 Chrome을 전용 프로필로 띄우고 CDP로 붙습니다.** 로그인은 처음 한 번.
- 파일 → 제목·설명 → 썸네일 → 재생목록 → 아동용 아님 → 다음 ×3 → 일부공개 → 업로드 완료 대기 → 저장 → ID 기록.
- 단계마다 스크린샷을 `logs/upload/`에 남깁니다. Studio 화면이 바뀌면 `longform/s6_upload.py`의 `SEL` 표만 고칩니다.

## 폴더

```
setup.bat · run.bat        설치 / 실행
longform/                  엔진과 파이프라인 (cli, s1~s8, notes 파서, raster, accounts, team, propose)
longform/web/              웹앱 (server.py = FastAPI, static/index.html)
longform/prompts/          집필·교재 에이전트 지시문
jobs/example/              예시 목표서 (실제 잡은 jobs/<잡>/ — 깃 제외)
engine/backplate/          렌더 엔진 backplate-studio 사본 (VENDORED.md)
docs/                      매뉴얼 (원천 가져오기)
profiles/ · logs/          로그인 프로필 · 기록 (깃 제외)
```
