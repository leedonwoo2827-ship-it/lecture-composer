# backplate-showcase — 운영 지침

원고 한 장(HTML)을 넣으면 **배경 그림 + 웹 텍스트**로 된 16:9 강의 영상이 나온다.
개발은 Claude Code, **운영은 이 문서만 보고** Codex CLI로 한다.

---

## 0. 이 레포가 다른 점 한 줄

**글자를 그림에 굽지 않는다.** 그림은 배경만 만들고, 글자는 화면이 진짜 텍스트로
얹는다. 그래서 한글이 깨지지 않고, 모션이 DOM 요소를 직접 움직이므로 마스크 상자를
지정할 일이 없다.

저자 지적(2026-09-14)이 출발점이었다 — *"한글이 조금 깨지는 문제를 제외하고는
괜찮다."* 실제로 9장 31번의 「모른다는 답」 설명줄이 `오육먹 쇌므과 모찰메아…`로
깨져 있었다. 그 글을 그림에서 빼는 것이 이 레포의 전부다.

---

## 1. 준비 (새 PC에서 한 번)

```
setup.bat            venv 둘 + npm + 폰트 + 음성모델(396MB) + 진단까지 한 번에
```

로그인 둘은 **사람마다 따로** 해야 한다. `setup.bat`이 대신 못 한다:

```
claude               한 번 실행해 구독 로그인    (대본·지시문 작성)
codex login          한 번 실행해 ChatGPT 로그인 (그림 생성)
```

막히면 진단을 먼저 본다. **무엇이 없어서 안 되는지 이름으로** 알려 준다:

```
.venv-app\Scripts\python tools\doctor.py
```

> **주의:** `codex`의 `auth.json`이 파일로는 멀쩡해도 세션이 죽어 있을 수 있다.
> 그때 배치가 `token_revoked`로 즉시 전체 중단한다 — **할당량 소진이 아니다.**
> `codex login`을 다시 하면 된다. 할당량 문제는 `429`나 `insufficient_quota`로 온다.

## 2. 실행

```
run.bat              →  http://localhost:5178
```

한 서버에 화면 둘이 붙어 있다. 예전에는 터미널이 둘이었다:

| 주소 | 무엇 |
|---|---|
| `localhost:5178` | 원고 → 목차 → 지시문 → 덱 → 음성 → 영상 |
| `localhost:5178/imgstudio` | 그림 생성(Codex OAuth) · 프롬프트 빌더 |

**파이썬을 고쳤는데 그대로면** `run.bat`에 `--reload`가 없어서다. 서버를 껐다 켠다.

---

## 3. 한 장을 끝까지 — 웹 없이 CLI로

작업 폴더는 레포 **밖**이다: `..\showcase-out-260918\{pid}_{slug}\`

```
set PY=.venv-app\Scripts\python

%PY% tools\run_stage.py <pid> s2c-capture        원고 구조 읽기
%PY% tools\run_stage.py <pid> s2b-outline        구조 설계        ← 돈(Claude)
   ■ 사람이 개입: 웹에서 목차 확인 · 제목과 순서 확정
%PY% tools\run_stage.py <pid> s3a-imgprompt      그림 지시문      ← 돈(Claude)
%PY% tools\run_stage.py <pid> s3b-images         지시문 JSON 내보내기
%PY% tools\run_stage.py <pid> s3c-images-run     그림 굽기        ← 돈(구독 할당량)
   ■ 사람이 개입: 그림 두세 장을 눈으로 본다. 톤이 어긋나면 여기서 멈춘다
%PY% tools\run_stage.py <pid> s6-script          내레이션 대본    ← 돈(Claude)
%PY% tools\run_stage.py <pid> s10-tts s11-audio  음성 · 자막
%PY% tools\run_stage.py <pid> s8-assemble        덱 조립
   ■ 사람이 개입: 「라벨 자리」 화면에서 글이 그림을 가리면 끌어서 옮긴다
%PY% tools\run_stage.py <pid> s12h-hyper         모션 영상 + −16 LUFS
```

`--force`를 붙이면 캐시를 무시하고 다시 돌린다. **돈이 드는 단계에는 함부로 붙이지
않는다.**

### 돈이 드는 단계만 따로

| 스테이지 | 무엇에 | 대략 |
|---|---|---|
| `s2b-outline` · `s6-script` · `s3a-imgprompt` | Claude 구독 | 장당 $1~2 |
| `s3c-images-run` | ChatGPT 구독 할당량 | 그림 장수만큼 |

`s3c`는 **이어하기**가 된다. 있는 번호는 건너뛰므로 중간에 끊겨도 남은 것만 굽는다.
그래서 **두세 장만 먼저 굽고 눈으로 본 뒤** 나머지를 돌리는 것이 정석이다.

---

## 4. 판(fmt)을 고르는 일 — 제일 중요한 결정

`project.json`의 `image_fit` 한 칸이 정한다.

| 값 | 이름 | 글자가 어디에 | 쓰는 데 |
|---|---|---|---|
| `full` | **전면** | **화면이 얹는다** | 지금 만드는 것은 전부 이것 |
| `plate` | 배경판 | **화면이 얹는다** | `full` 과 같다 — 옛 이름이다 |
| `frame` | 액자 | **그림 안에** 구워진다 | 옛 프로젝트 보수용. 새로 만들지 않는다 |

**2026-09-18에 `full` 이 글자를 안 굽는 쪽으로 넘어왔다.** 그전까지 `full` 은
라벨을 그림에 인쇄시켰는데, 문에서 판 고르기를 걷어내고 `full` 하나만 남기면서
글자 억제가 `plate` 에만 걸린 채로 남았다. 원장은 판과 무관하게 라벨을 적고
화면은 그것을 그대로 얹으므로 **글자가 두 겹으로 나왔다**(1장 002 실측).
이제 `full` 과 `plate` 는 지시문이 **같다** — 갈래를 되살리지 마라.

### 규칙 둘 — 어기면 다시 구워야 한다

1. **한 장 안에서 섞지 않는다.** 섞으면 어떤 슬라이드는 글자가 빽빽하고 어떤 건
   헐거워 보인다.
2. **이미 구운 장을 11판으로 바꾸면 그 장 그림을 전부 다시 굽는다.**

### 톤이 연해 보이는 것은 정상이다

배경판은 구조적으로 원본보다 연하다 — 진한 파랑 라벨이 빠지면 화면의 잉크가 줄기
때문이다. 다만 **맨 PNG는 아무도 안 본다.** 나가는 것은 배경판 + 웹 텍스트 합성이고
거기서 잉크가 돌아온다. 중간 산물을 보고 판단하지 말 것.

### 기존 장을 11판으로 옮기기

```
%PY% tools\plate_migrate.py <프로젝트폴더>            미리보기
%PY% tools\plate_migrate.py <프로젝트폴더> --apply    적용
%PY% tools\run_stage.py <pid> s8-assemble --force    덱에 라벨 싣기
```

10판 지시문 안에 라벨이 이미 한 줄씩 적혀 있으므로 **읽어 내면 된다** — `s3a`를 다시
부르지 않는다(장당 돈이 든다).

---

## 5. 산출물 규격 (④)

`showcase.config.json`의 `video` 블록이 정한다. 재서 대조하는 법:

```
ffprobe -v error -show_entries stream=codec_name,profile,level,width,height,r_frame_rate,sample_rate,channels,bit_rate -of default=noprint_wrappers=1 out.mp4
ffmpeg -i out.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=summary -f null -
```

| 요구 | 실측(9장 3장 합본) |
|---|---|
| 1920×1080 | 1920×1080 |
| 30fps | 30/1 |
| H.264 | h264 High L4.0 |
| AAC 192k | aac LC 187k (VBR이라 공칭보다 약간 아래) |
| −16 LUFS | −16.0 · TP −1.5 dBTP |

- **번인 자막은 만들지 않는다.** SRT는 `08_자막/NNN.srt` 사이드카로만 나간다.
- 라우드니스는 **합본에** 건다. 장마다 걸면 장이 바뀔 때마다 소리가 출렁인다.
- 순서는 렌더 → 정규화다. 반대로 하면 다시 인코딩하면서 이득이 풀린다.

---

## 6. 손편집은 언제나 이긴다

`10_덱/deck.overrides.json`이 스테이지 출력을 덮는다. 다시 돌려도 산다.

예전에 이 규칙을 안 지켜서 사고가 있었다 — s10/s11이 s6 캐시만 읽어서 **사람이 고쳐
쓴 발음이 한 번도 소리로 안 나갔다**(`registry.narration_of()`의 주석). 새 코드도 이
규칙을 지켜야 한다.

라벨은 **배열을 통째로** 덮는다. 한 번 손대면 그 장의 라벨은 사람이 가져간다.
되돌리려면 「라벨 자리」 화면의 **원래대로**.

---

## 7. 막혔을 때

| 증상 | 원인 | 할 일 |
|---|---|---|
| 그림이 `token_revoked`로 전부 실패 | Codex 세션 만료 | `codex login` |
| 그림이 `429` / `insufficient_quota` | 구독 할당량 소진 | 결제일까지 대기 |
| 음성이 안 나온다 | 가중치 없음 | `tools\doctor.py`가 받는 법을 알려 준다 |
| 라벨이 편집기에 안 보인다 | 10판 원장이다 | `plate_migrate.py` → `s8-assemble --force` |
| 글자가 두 겹으로 보인다 | 그림이 옛 지시문으로 구워졌다 | `s3a` 부터 다시 — 지시문·그림·덱을 지우고 「이미지 JSON 만들기」 |
| 린트가 렌더를 막는다 | 컴포지션 문제 | 메시지 그대로가 원인이다. 고치고 다시 |
| 파이썬 수정이 안 먹는다 | `--reload`가 없다 | 서버를 껐다 켠다 |
