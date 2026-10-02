# 상세 설치 & 문제 해결 가이드

Windows / macOS / Linux 설치와, 자주 막히는 부분(특히 macOS 권한·보안격리)을 한곳에 모았습니다.
간단 설치는 [메인 README](../README.md) 를 먼저 보세요.

---

## 공통 요건

- **Python 3.10+**
- **Node.js** (codex CLI 설치용)
- **ChatGPT 구독 계정** (이미지/텍스트 생성 할당량 사용)
- 인터넷 연결

설치 후 첫 실행 시 `codex login` 으로 ChatGPT 계정에 로그인합니다. 자격증명은 `~/.codex/auth.json`
(Windows 는 `%USERPROFILE%\.codex\auth.json`)에 저장되고, 토큰 만료 시 자동 갱신됩니다.

---

## Windows

1. [Python](https://www.python.org/downloads/windows/) 설치 시 **“Add python.exe to PATH”** 체크
2. [Node.js](https://nodejs.org/) 설치
3. 저장소 ZIP 다운로드 후 압축 풀기
4. **`setup.bat`** 더블클릭 — 가상환경 + 의존성 설치 + `codex login`
5. **`run.bat`** 더블클릭 — 브라우저에서 `http://127.0.0.1:8765/` 자동 열림

> `.bat` 이 켜자마자 닫히면, 명령 프롬프트(cmd)에서 폴더로 이동해 `setup.bat` 을 실행하면 오류 메시지를 볼 수 있습니다.

---

## macOS (Apple)

준비물(각 설치파일 더블클릭): [Python 3](https://www.python.org/downloads/macos/) · [Node.js](https://nodejs.org/)

### 방법 A — git clone (권장: 권한 문제 없음)

터미널에 붙여넣기:
```bash
git clone https://github.com/leedonwoo2827-ship-it/codex-prompt-img-studio.git
cd codex-prompt-img-studio
./setup.sh     # 또는 Finder 에서 setup.command 더블클릭
./run.sh       # 또는 run.command 더블클릭
```
git clone 은 실행권한이 보존되고 보안격리도 걸리지 않아 가장 매끄럽습니다.
(git 이 없으면 첫 실행 시 macOS 가 자동으로 설치 안내를 띄웁니다.)

### 방법 B — ZIP 다운로드

GitHub **Code → Download ZIP** 로 받으면 **실행권한이 사라지고 보안격리가 걸립니다.**
**최초 1회만** 터미널에서 아래를 실행해 풀어주세요:
```bash
cd ~/Downloads/codex-prompt-img-studio-master   # 압축 푼 폴더 (경로는 폴더를 터미널로 드래그하면 자동 입력)
xattr -dr com.apple.quarantine .                # 보안 격리 해제
chmod +x setup.command run.command setup.sh run.sh
```
그다음 **`setup.command` → `run.command`** 순서로 더블클릭.

### “확인되지 않은 개발자” 경고가 뜰 때

- 파일을 **우클릭(또는 Control+클릭) → 열기** → 다시 **열기**
- 그래도 막히면: **시스템 설정 → 개인정보 보호 및 보안** 화면 하단의
  “… 차단되었습니다” 항목에서 **“확인 없이 열기”** 클릭

---

## Linux

```bash
git clone https://github.com/leedonwoo2827-ship-it/codex-prompt-img-studio.git
cd codex-prompt-img-studio
chmod +x setup.sh run.sh   # git clone 시엔 보통 이미 실행권한 있음
./setup.sh                 # 가상환경 + 의존성 + codex login
./run.sh                   # 서버 실행 → http://127.0.0.1:8765/
```
codex CLI 가 없으면 `npm i -g @openai/codex` 후 `codex login`.

---

## 로그인 / 계정 변경 / 로그아웃

앱 우상단 **⚙️ 설정**에서:
- **🔑 로그인 / 계정 변경** — 새 터미널 창에서 `codex login` (다른 ChatGPT 계정으로 로그인 = 계정 변경)
- **로그아웃** — 새 터미널 창에서 `codex logout`
- **↻ 상태 새로고침** — 로그인 칩/상태 갱신

터미널에서 직접 할 수도 있습니다: `codex login` / `codex logout`.

---

## 자주 막히는 문제 (FAQ)

| 증상 | 해결 |
|---|---|
| `codex` 명령을 찾을 수 없음 | Node.js 설치 후 `npm i -g @openai/codex` |
| 로그인했는데 “로그인 필요”로 표시 | 우상단 ⚖️ ↻ 상태 새로고침, 또는 `codex login` 재실행 |
| `8765 포트 사용 중` | 이미 실행 중입니다. 기존 창을 닫거나 브라우저에서 `http://127.0.0.1:8765/` 접속 |
| 이미지가 안 만들어짐 / 401 | 토큰 만료 — `codex login` 으로 재로그인 |
| 텍스트는 되는데 이미지만 실패 | ChatGPT 이미지 생성 할당량 소진 가능 — 할당량이 회복될 때까지 기다리세요 |
| macOS 더블클릭이 안 됨 | 위 **방법 B** 의 `xattr`·`chmod` 한 번 실행, 또는 **방법 A(git clone)** 사용 |

> 포트는 `.env` 의 `PORT` 로 바꿀 수 있습니다(기본 8765).
