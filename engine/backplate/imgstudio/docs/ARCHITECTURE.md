# 시스템 구조 & API

통합 앱(프롬프트 빌더 + 이미지 스튜디오)의 내부 구조 메모.

## 디렉터리 구조

```
app.py                       # 통합 FastAPI 진입점 (단일 포트 8765, 단일 정적 마운트)
core/                        # 경로/설정/DB (이미지 스튜디오 + 빌더 경로 통합)
  constants.py               # 경로·포트·이미지 사이즈 + 빌더 자산 경로(PROMPTS/PRESETS/ARCHIVES)
  config.py                  # 기본 생성 옵션 — 크기·형식 (data/settings.json)
  database.py                # SQLite (Project / Image / EditEvent)
  atomic_io.py               # 원자적 JSON 저장
services/
  codex_auth.py              # ChatGPT OAuth 상태 + 로그인/로그아웃 콘솔 실행
  codex_image.py             # 이미지 생성/수정/병합 (Codex Responses API · SSE)
  codex_text.py              # 빌더 텍스트·비전 (codex_image 의 토큰/스트림 재사용) ← 신규
  prompt_spec.py             # 빌더 시스템 프롬프트 조립
  presets.py / archive.py / manuscript.py   # 프리셋 / 보관함 / 원고 추출
  batch_jobs.py              # 슬라이드 JSON 일괄 생성 (번호 파일명 · 동시실행 · 재시도 · 이어하기)
routes/
  auth · settings · project · image · batch_routes.py   # /api/*     (스튜디오)
  builder_chat · preset · archive · manuscript_routes.py   # /api/builder/* (빌더)
static/
  index.html                 # 워크스페이스 전환 셸 + 두 UI
  css/tokens.css · app.css   # Miro 디자인 토큰 + 통합 스타일
  js/shell.js · app.js · builder.js · api.js
  manual.html                # 앱 내 프롬프트 매뉴얼
prompts/ · presets/          # 빌더 자산 (브랜드 가이드 · 스타일 카탈로그 · 프리셋)
data/                        # 런타임 (app.db · images/ · settings.json · archives.json) — git 제외
```

## 워크스페이스 & API 네임스페이스

| 워크스페이스 | UI | API |
|---|---|---|
| ✍️ 프롬프트 빌더 (앞) | 자유 빌더(채팅) · 프롬프트 생성기 · 보관함 | `/api/builder/*` |
| 🎨 이미지 스튜디오 (뒤) | 갤러리 · 뷰어/편집 · 병합 · 큐 · 일괄 생성 | `/api/auth` · `/api/settings` · `/api/projects` · `/api/images` · `/api/batch` |

- 빌더 API는 모두 `/api/builder/*` 로 묶어 스튜디오 `/api/*` 와 충돌을 피했습니다.
- 정적 자산은 `/` 단일 마운트, 프리셋 커버는 `/presets` 마운트.

## 로그인(인증) — 하나로 통일

- **ChatGPT OAuth** (`~/.codex/auth.json`) 하나로 빌더의 텍스트·비전과 스튜디오의 이미지 생성이 모두 동작.
- 핵심: `services/codex_text.py` 가 `services/codex_image.py` 의 토큰 로드·401 자동 갱신·SSE 스트림 파싱을
  **재사용**해, 텍스트/비전도 같은 Codex Responses 엔드포인트로 호출합니다. (LiteLLM/별도 API 키 불필요)
- `codex_image.py` 의 엔드포인트는 Codex CLI 가 쓰는 **비공식 내부 엔드포인트**라 OpenAI 측 변경 시 영향받을 수 있습니다.

## 엔진

- **ChatGPT (Codex) 하나뿐입니다** — 키리스, 사용자의 구독 할당량으로 동작.
  - 대체 엔진(Gemini)은 2026-08-29 제거했습니다. 쓰지 않는데 설정·UI·의존성(httpx)만
    늘리고 있었고, 키가 없으면 어차피 동작하지 않았습니다.
- 이미지 모델은 **`gpt-image-2`** 입니다. 요청에 싣는 `gpt-5.5` 는 추론 모델이고,
  그림은 그 안의 `image_generation` 툴이 만듭니다. 응답에 이미지 모델 이름은 안 실립니다.
- **크기 규칙** — 가로·세로 모두 **16의 배수**, 비율 **1:3 ~ 3:1**, 최대 **3840×2160**.
  `codex_image._check_size()` 가 보내기 전에 걸러 한국어로 알립니다.
  - 2026-08-29 이전에는 이 파일이 "1024x1024·1536x1024·1024x1536 셋뿐"으로 알고 막았습니다.
    그건 구형 `gpt-image-1` 기준이라 **16:9 를 고르면 조용히 3:2 로 바뀌어 나갔습니다.**
    제20·21장이 3:2 로 나온 원인입니다.
  - 실측(2026-08-29) — `1536x864`→`1672x941`(16:9), `864x1536`→`941x1672`(9:16),
    `1408x1056`→`1448x1086`(4:3), `1536x656`→`1918x820`(21:9).
    **비율은 지키지만 해상도는 백엔드가 다시 잡습니다** — `size` 는 사실상 비율 지정입니다.

## 프롬프트 큐 (보관함 → 스튜디오)

- 빌더 「📌 보관」 → `data/archives.json`
- 스튜디오 `📋` → 보관 프롬프트 선택 → (옵션) 코드블록(컷) 단위로 분리해 큐 적재
- 한 장씩 자동 입력 → 생성 성공 시 다음 프롬프트 자동 입력 (일괄 동시 생성 아님)

## 슬라이드 JSON 일괄 생성 (`/api/batch`)

강의 슬라이드용 이미지 프롬프트 JSON을 넣으면 **슬라이드 번호에 맞춘 파일명**으로 폴더에 한꺼번에 만든다.
(PPT 합치기 도구가 파일명 앞 숫자로 슬라이드를 찾으므로 번호가 곧 계약.)

- 입력: `{"deck","style_hint","aspect","prompts":[{"n","title","type","place","prompt","negative"}]}`
  — `prompts` 대신 `items`/`scenes` 도 인식, 최상위가 배열이어도 됨.
- 프롬프트 조립: `prompt` + (프롬프트에 없으면) `style_hint` + `negative` → `Avoid: …` 문장.
  (Codex 이미지 툴에는 negative 파라미터가 없다.)
- 출력: `<출력폴더>/003.png` (옵션: `003_제목.png`) · `aspect: landscape` → `1536x1024` 자동 제안
- 실행: `services/batch_jobs.py` 가 asyncio 세마포어로 동시 N장(기본 3, 최대 6),
  항목별 재시도 + 지수 백오프(429 는 45초), **한 번에 한 작업만**(중단 처리 중에도 차단)
- 이어하기: 폴더에 이미 있는 `NNN*.png` 는 `skipped` — 중단 후 다시 돌리면 남은 것만 만든다.
- 401(로그인 만료)은 즉시 전체 중단 — 남은 구독 할당량을 헛되이 태우지 않는다.
- 진행 상태는 `data/batch_jobs/<job_id>.json` 에 계속 기록되어 브라우저를 닫아도 서버에서 진행.
  (단, 서버를 재시작하면 진행 중 작업은 사라진다 — 다시 시작하면 이어하기로 남은 장만 생성)
- API: `POST /parse` · `POST /inspect`(폴더 조회, 만들지는 않음) · `POST /reveal` ·
  `POST /start` · `GET /active` · `GET /{job_id}` · `POST /{job_id}/stop` · `POST /{job_id}/retry`

## 데이터/프라이버시

- 이미지·기록·설정·토큰은 전부 **로컬**(`data/`, `~/.codex/`)에만 저장. `data/` 와 `.env` 는 git 에서 제외.
