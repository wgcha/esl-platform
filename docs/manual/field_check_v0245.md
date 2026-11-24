# v0.24.5 현장 확인 — ④ 판정 단계·MAC, 출처 숨김·계산 제외 (2026-11-24)

계약 `docs/contracts/esl_validate_tiers.md`(§11 화면 숨김·§12 계산 제외). 고칠 것은 **설정만**(코드 수정 없음). 결과는 각 표 오른쪽 칸에 적는다. 자세한 설명은 관리자 매뉴얼 §4.5.

## ① 서버 반영
| # | 할 일 | 확인 | 결과 |
|---|---|---|---|
| 1 | `E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1`(관리자 매뉴얼 §3.0) | 화면 오른쪽 위 버전 0.24.5 | |
| 2 | DB migration `0017_validation_tiers` 자동 적용 — 확인만 | 환경 점검(§10) DB 항목 OK, 옛 검증 결과는 "이전 판정 체계" 로 보임 | |

## ② 설정 고치기 — 업데이트는 있는 값을 그대로 둔다
v0.24.0~v0.24.4 예시로 만든 설정 파일에는 아래 값이 **명시**돼 있을 수 있다. 업데이트는 빠진 키만 채우므로 그대로 남고, 그러면 화면에서는 숨겨져도 **새 강성 스터디가 경계력·내력·지그 고정을 계속 계산**하고(시간만 더 듦) ④ 기준은 1 % 로 남는다.

| 파일(`E:\VD_SIMULATION_WEB\esl-platform\.runtime\config\`) | 키 | 예전 예시 값 | 고칠 값 | 효과 | 결과 |
|---|---|---|---|---|---|
| `esl.yaml` | `validation.disp_rms_rel_max` | `0.01` | `0.05` | ④ PASS ≤ 5 %·조건부 PASS ≤ 10 %(0.01 이면 PASS ≤ 1 %) | |
| `esl_platform.yaml` | `bead_doe.bforce: {enabled: …}` | `true` | `false` | 새 스터디 경계력 계산 안 함 | |
| 같음 | `bead_doe.fint: {enabled: …}` | `true` | `false` | 새 스터디 내력 계산 안 함 | |
| 같음 | `bead_doe.rank.jig.methods` | `[fixed, prescribed, spring]`(v0.24.4 부터) | `[prescribed, spring]` | 새 스터디 지그 고정 계산 안 함, 기본 순위 = 지그 변위 | |
| 같음 | `ui.hidden_sources` | (없음 — 업데이트가 채움) | `[bforce, fint, jig]` 그대로 | 화면 숨김(표시만) | |

PowerShell 로 확인 → 고침 → 다시 확인(관리자 매뉴얼 §4.5 와 같은 명령):

```powershell
$cfg = 'E:\VD_SIMULATION_WEB\esl-platform\.runtime\config'
# 1) 확인: 줄이 나오면 고칠 대상(주석 줄 #… 은 안 나옴)
Select-String -LiteralPath "$cfg\esl_platform.yaml","$cfg\esl.yaml" `
  -Pattern '^\s*(bforce|fint):\s*\{\s*enabled:\s*true\b', '^\s*methods:\s*\[\s*fixed\b', '^\s*disp_rms_rel_max:\s*0\.01\b' |
  Select-Object Filename, LineNumber, Line
Select-String -LiteralPath "$cfg\esl_platform.yaml" -Pattern '^\s*(bforce|fint):\s*$' -Context 0,1   # 블록 형식이면 메모장으로 enabled: false
# 2) 고침: 백업(.bak_v0245) 후 그 값만 바꿈, BOM 없는 UTF-8 로 저장
$enc = New-Object Text.UTF8Encoding($false)
foreach ($f in "$cfg\esl_platform.yaml", "$cfg\esl.yaml") {
  Copy-Item -LiteralPath $f -Destination "$f.bak_v0245"
  $t = [IO.File]::ReadAllText($f, $enc)
  $t = [regex]::Replace($t, '(?m)^(\s*(?:bforce|fint):\s*\{\s*enabled:\s*)true\b', '${1}false')
  $t = [regex]::Replace($t, '(?m)^(\s*methods:\s*)\[\s*fixed\s*,\s*prescribed\s*,\s*spring\s*\]', '${1}[prescribed, spring]')
  $t = [regex]::Replace($t, '(?m)^(\s*disp_rms_rel_max:\s*)0\.01\b', '${1}0.05')
  [IO.File]::WriteAllText($f, $t, $enc)
}
# 3) 1) 을 다시 실행 — 줄이 안 나오면 끝
```

| # | 할 일 | 기대 | 결과 |
|---|---|---|---|
| 1 | 위 1) 실행(고치기 전) | 나온 줄 수·줄 번호를 적음 | |
| 2 | 위 2)·3) 실행 | 3) 에서 줄 없음, `.bak_v0245` 2개 생김 | |
| 3 | `ESL-Backend`·`ESL-Worker` 재시작(관리자 매뉴얼 §4.2) | health OK | |
| 4 | `<런타임>\logs\backend.log` 시작 부분 | `설정 경고: ui.hidden_sources 에 모르는 출처 키 …` 줄 **없음**(있으면 키 오타 — 그 키는 무시되고 있음) | |

줄을 지워도 된다(지우면 기본값, 다음 업데이트가 새 예시 값으로 다시 채움). 되돌리기 = `.bak_v0245` 를 원래 이름으로 복사 후 재시작.

## ③ 화면·계산 확인
| 볼 값 | 어디 | 기대 | 결과 |
|---|---|---|---|
| 경계력·내력 줄 | 새로 계산한 Case ③ ESL 결과 카드 | **없음**(숨김). `ui.hidden_sources: []` 로 바꾸면 `경계력 ESL: 설정에서 꺼짐(bforce.enabled)`·`내력 ESL: 설정에서 꺼짐(bforce.enabled · bforce.fint.enabled)` — "다시 추출"·"/H3D/NODA/FINT 추가" 안내가 나오면 안 됨 | |
| ③ 3D 출처 탭 | ③ 3D 카드 머리 | [지그 ESL 변위·스프링]·[전 노드 ESL] 만 | |
| ④ 검증 | ④ [검증 다시 실행] 후 판정 카드 | 출처 탭 = 지그 변위·스프링·전 노드, 변위 RMS PASS ≤ 5 %·조건부 ≤ 10 %, MAC(검증) 칸 | |
| 새 스터디 | 하중 정의 탭 | 지그 변위·스프링·전 노드만, 기본 순위 = 지그 변위 | |
| 옛 스터디(v0.24.3 이전에 만든 것) 안 추가·이어하기 | 작업 로그 | 이미 끝난 안은 다시 평가하지 않음(새 안만) | |

## ④ 결과 보고
- ② 표 1번에서 나온 줄(고치기 전), ③ 표 전체, 이상이 있으면 `backend.log` 시작 부분과 해당 작업 로그.
