# TTS (음성 내레이션)

`setup.bat` 이 `voicewright`(Supertonic-3 기반 로컬 한국어 TTS,
[leedonwoo2827-ship-it/voicewright](https://github.com/leedonwoo2827-ship-it/voicewright))
를 **이 프로젝트 폴더 안에** `./voicewright/` 로 clone 하고 설치까지 시도한다.

```
setup.bat
  ├─ .venv-app 만들고 이 앱(fastapi 등) 설치        [1/3]
  ├─ ./voicewright 없으면 git clone                [2/3]
  │    있는데 설치가 안 됐으면 voicewright\install.bat 을
  │    한 번 실행하라고 안내(자동 실행 안 함 — GPU 감지·
  │    ~250MB 모델 다운로드·확인 pause 가 있어서 사람이
  │    직접 보는 게 안전하다)
  │    설치돼 있으면(← .venv + assets\onnx\vocoder.onnx)
  │    tools\wire_tts.py 가 showcase.config.local.json 에
  │    자동으로 경로를 채운다
  └─ Claude 로그인 확인                             [3/3]
```

## 처음 설치할 때

```
setup.bat                         # voicewright 를 clone 만 해 둔다
voicewright\install.bat           # 이걸 한 번 직접 실행 (5~10분)
setup.bat                         # 다시 실행 — 이제 자동으로 연결된다
```

## 왜 이 프로젝트 폴더 안에 따로 두나

이 PC 에는 프로젝트마다 `voicewright` 를 각자 clone 해서 쓰는 관행이 있다. 그걸
따르되, **다른 프로젝트의 절대경로를 이 레포 안에 남기지 않는다.** `setup.bat`
이 항상 `./voicewright` 를 기준으로 새로 잡기 때문에, 이 레포를 다른 PC에
새로 clone 해도 그 PC 안에서 다시 자기 완결적으로 셋업된다.

`voicewright/` 는 `.gitignore` 대상이다(자기 `.git`을 가진 별도 레포이고,
모델 가중치가 커서 커밋하면 안 된다).

## 확인

```
tools\wire_tts.py 가 출력한 메시지로 확인하거나,
showcase.config.local.json 의 "tts" 블록을 직접 봐도 된다.
```

`tts.engine` 이 `"voicewright"` 면 연결된 것이고, `"none"` 이면 음성 없이
덱·자막·큐시트만 나온다(파이프라인은 그래도 끝까지 돈다).
