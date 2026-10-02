# 화면 캡처 — `tools/shots.mjs`

사이트를 라우트 목록대로 돌며 스크린샷을 뜬다. **파일명 = 사이드바 순서 = 발표 설명 순서.**

```
cp tools/shots.example.json tools/shots.<사이트>.json
node tools/shots.mjs tools/shots.<사이트>.json
```

| 옵션 | 하는 일 |
|---|---|
| (없음) | 이미 있는 파일은 건너뜀 — 실패한 것·새로 넣은 것만 채워진다 |
| `--force` | 있어도 다시 찍는다 |
| `--role personal` | 한 역할만 |
| `--only profile,career` | 슬러그 몇 개만 |
| `--headed` | 창을 띄워 눈으로 확인 (로그인이 안 될 때) |
| `--prune` | 목록에서 뺀 화면의 옛 파일을 지운다 |

나오는 것:

```
<out>/personal/personal-03-career.png    1440×900 @2x — 슬라이드에 그대로 얹는 것
<out>/personal/전체/personal-03-career.png  스크롤 전체 — 참고용
<out>/공통/공통-consulting.png           역할 공용 화면 (아래 참고)
<out>/shots.json                         목록 · 순서 · 그룹 · 어느 역할 메뉴였는지
```

---

## JSON 채우는 법

`shots.example.json` 을 복사해 `shots.<사이트>.json` 으로 쓴다. **빈 틀로 시작한다.**

> 만든 config 는 배포본에 나가지 않는다(gitignore). 사이트 주소·계정·내 PC 의 산출
> 경로가 들어가기 때문이다. 나가는 것은 빈 틀 하나뿐이다.

### 1. 뼈대

```jsonc
{
  "base": "https://example.com",         // 끝 슬래시 없이
  "out":  "D:/…/01b_캡처",                // 산출 폴더
  "viewport": { "width": 1440, "height": 900, "scale": 2 },
  "settle_ms": 1200,                      // 페이지가 그려질 때까지 더 기다릴 시간
  "full_page": true,                      // 전체/ 폴더에 스크롤 전체본도 남길지
  "hide": ["button:has-text('오류 신고')"],// 장마다 걸리적거리는 것 (CSS 아님, Playwright 셀렉터)
  "common": ["/consulting"],              // ↓ 3번
  "roles": [ … ]                          // ↓ 2번
}
```

### 2. `roles` — 역할 하나 = 로그인 하나

```jsonc
{
  "id": "personal",                 // 폴더 이름 · 파일 앞머리. ascii 로.
  "label": "개인회원(전문가)",
  "user": "…",                      // 없으면 로그인 안 하고 찍는다(공개 페이지)
  "login_done": "**/admin**",       // 로그인 후 도착지가 /dashboard 가 아닐 때만
  "shots": [
    { "slug": "career", "label": "내 경력", "path": "/career", "group": "경력·이력" }
  ]
}
```

- `shots` 의 **배열 순서가 곧 번호**다(`personal-03-career.png`). 사이드바 순서 그대로 넣는다.
- `slug` 은 파일명, `label` 은 발표에서 부를 이름, `group` 은 사이드바 구획명.
- 라우트 목록을 손으로 뒤지지 말 것 — Next.js 면 `src/app/**/page.tsx`, 메뉴 순서는
  사이드바 컴포넌트(`components/Sidebar.tsx` 등)에 배열로 들어 있다. **거기가 정답지다.**

### 3. `common` — 역할끼리 겹치는 화면

```jsonc
"common": ["/consulting", "/inquiries", "/messages", "/settings"]
```

여기 적힌 라우트는 **처음 만난 역할에서 한 번만** 찍혀 `공통/` 으로 가고, 뒤 역할은 건너뛴다.
`shots.json` 에 `roles: ["personal","corporate"]` 로 "누구 메뉴에 걸려 있었는지" 가 남으므로,
발표에서 공통 섹션으로 모을 때 판단이 아니라 사실로 쓸 수 있다.

> ★ **역할마다 다르게 보이는 화면을 넣으면 안 된다.** `/dashboard` 는 개인·기업이 주소는 같지만
> 내용이 다르다 — 그래서 `common` 에 없다. 넣었다가 한쪽 화면이 통째로 사라진다.

### 4. 비밀번호

config 에 쓰지 않는다. 옆에 `shots.<사이트>.local.json` 을 두면 그걸 읽는다(gitignore 대상):

```json
{ "pass": { "personal": "…", "corporate": "…", "admin": "…" } }
```

없으면 `SHOTS_PW_PERSONAL` 같은 환경변수를 본다.

---

## 안 될 때

| 증상 | 이유 |
|---|---|
| 전부 "로그인 실패 — /login 에 머물렀습니다" | 하이드레이션 전에 눌렀다. `settle_ms` 를 올리거나 `--headed` 로 본다 |
| "로그인으로 튕김 (권한 없음?)" | 그 역할에 권한이 없는 라우트다. 다른 역할로 옮긴다 |
| `HTTP 404` | 레포 스냅샷이 라이브보다 낡았다. 라이브 네비게이션에서 주소를 다시 딴다 |
| 차트·이미지가 빈 채로 찍힘 | `settle_ms` 를 올린다 |
