# HyperView h3d 추출 TCL (ESL 코어 입력)

> **미검증**: 이 두 스크립트는 HyperView 설치 없이 Altair hwi/poI* Tcl API 문서 기준으로 작성했다.
> 저장소 시험(`tests/io/test_tcl_mock.py`)은 가짜 `hwi`로 **문법·흐름·CSV 포맷만** 확인한다.
> 실제 h3d에는 **반드시 `esl_h3d_probe.tcl`을 먼저 실행**해 subcase·결과 유형·성분·layer 이름과
> 파트 선택 문자열이 맞는지 확인한 뒤 `request.txt`를 채운다.

계약: `docs/contracts/esl_core.md` §3.2.

## 1. 실행 (Windows, HyperWorks 2022~2026)

```bat
set HW="C:\Program Files\Altair\2026.1\hwdesktop\hw\bin\win64\hw.exe"
set TCL=C:\esl\resources\tcl

rem (1) probe: h3d 안의 component(=Radioss part) 목록·결과 유형·성분·layer → probe.json
%HW% -clientconfig hwpost.dat -b -tcl %TCL%\esl_h3d_probe.tcl -input D:\run\drop.h3d -output D:\run\probe

rem (2) extract: 대상 파트를 title(또는 숫자 id)로 지정 → CSV 폴더 (클라우드 입력 <results_dir>)
%HW% -clientconfig hwpost.dat -b -tcl %TCL%\esl_h3d_extract.tcl -input D:\run\drop.h3d -part chassis_rear -output D:\run\esl_csv
```

- `-part <title|id>`: 숫자면 component(part) id, 아니면 title. title은 **대소문자·공백·언더스코어를 무시**하고 비교한다(`Chassis Rear` = `chassis_rear`). 우선순위: `-part` 인자 > request.txt `part_id` > request.txt `part_title`.
- extract에서 파트를 정하지 못하면(지정 없음·이름 없음·여러 개 일치) `done.json`이 `ok:false`(`INPUT_INVALID`)이고 `components` 목록이 함께 기록된다 — 거기서 이름/ID를 골라 다시 실행.
- probe는 `-part` 없이도 component 목록(`id`, `name`, `n_elems`)과 모든 결과 유형을 기록한다. `-part`를 주면 선택 문자열 시험·샘플 질의도 한다.
- `-config <request.txt>`는 **선택**(고급 옵션, §2). 없거나 파일이 없으면 기본값으로 동작(파일이 없으면 `warnings`에 기록).
- 경로의 `\`는 스크립트 안에서 `/`로 바꾼다. 공백 있는 경로는 `"..."`로 감싼다.
- 인자가 hw에 전달되지 않는 설치본이면 환경변수 `ESL_INPUT`, `ESL_OUTPUT`, `ESL_PART`, `ESL_CONFIG`로 대신 줄 수 있다.
- 끝나면 `exit 0`(실패 시 `exit 1`)을 호출한다.

## 2. 고급 옵션: request.txt (`key<TAB>value`, `#` 줄은 주석, 선택)

기본값으로 충분하면 만들 필요 없다. 바꿀 키만 적으면 된다.

```text
# 키와 값 사이는 반드시 TAB 한 개
part_title	chassis_rear
subcase	1
frame_stride	1
strain_type	Strain
strain_comps	XX YY XY
layer_bottom	Lower
layer_top	Upper
shear_is_engineering	0
disp_type	Displacement
strain_system	elemental
```

| 키 | 기본값 | 설명 |
|---|---|---|
| `part_id` | (빈 값) | 대상 Radioss part ID (HyperView component ID). `-part` 인자가 우선 |
| `part_title` | (빈 값) | part_id가 없을 때 title로 찾음(대소문자·공백·언더스코어 무시) |
| `subcase` | `1` | subcase ID |
| `frame_stride` | `1` | simulation 인덱스 0, s, 2s, … 만 출력 |
| `strain_type` | `Strain` | 변형률 텐서 결과 유형 이름(probe의 `data_types[].name`) |
| `strain_comps` | `XX YY XY` | exx, eyy, exy 순서의 성분 이름 3개 |
| `layer_bottom` / `layer_top` | `Lower` / `Upper` | HyperView layer 이름(probe의 `layers`) |
| `layer_mid` | (빈 값=생략) | 지정 시 `mid` 행도 출력(선택) |
| `shear_is_engineering` | `0` | `1`이면 h3d XY가 공학전단 γ로 보고 TCL이 exy = XY/2로 출력 |
| `disp_type` / `disp_comps` | `Displacement` / `X Y Z` | 변위 결과 유형·성분 |
| `strain_system` | `elemental` | 변형률 텐서를 풀어낼 결과 좌표계: `elemental`(요소 국부계, 계약 기준) / `analysis` / `global` / `none`(호출 안 함). **미검증**: `SetResolvedIn` → `SetResultSystem` → `SetSystemType` → `SetSystem` 순으로 `"Elemental System"`·`Elemental` 등을 시도하고, 모두 실패하면 HyperView 기본계를 그대로 쓰며 `done.json` `warnings`에 1회 기록(계속 진행). 성공한 호출은 `done.json` `strain_system_call` |
| `elem_selection` / `node_selection` | (빈 값) | 선택 문자열 직접 지정(예: `component 12`). 비우면 `component N` → `comp N` → `part N` 순으로 시도하고, 모두 실패하면 `all`(다른 파트 행은 Python이 버림, 경고 기록) |

## 3. 출력 (`-output` 폴더)

| 파일 | 헤더 | 비고 |
|---|---|---|
| `frames.csv` | `frame_index,time` | frame_index = subcase 안 simulation 인덱스(0부터). time = simulation 라벨의 `=` 뒤 숫자(없으면 마지막 숫자, 그것도 없으면 인덱스 + 경고) |
| `model.csv` | `node_id,x0,y0,z0` | 첫 출력 프레임의 `node.coords`(프레임 0 = 비변형 가정). Python이 rad 좌표와 `max(1e-6·bbox, 2·eps_f32·max\|x\|·√3)` 허용오차로 비교(h3d float32 좌표 고려) |
| `strain.csv` | `frame_index,elem_id,layer,exx,eyy,exy` | layer = `bottom`,`top`(필수), `mid`(선택). 요소 국부계 텐서(h3d 저장계 그대로, 평균 없음) |
| `disp.csv` | `frame_index,node_id,ux,uy,uz` | 전역계 변위 |
| `done.json` | | 성공 `{"ok":true,"part_id","part_title","part_spec","n_frames","n_elems","n_nodes","h3d","subcase","elem_selection","node_selection","disp_value_format":"%.17g","value_format":"%.17g","strain_system","strain_system_call","backup_dir","warnings":[]}` / 실패 `{"ok":false,"code","error","failed_step","errorCode","errorInfo","h3d","part_spec","part_id",...}`. 성공·실패 모두 `steps_done`,`api`,`traces`,`env`,`components` 포함(§6) |

- 실패 code: `H3D_MISSING_RESULT`(subcase·결과 유형·layer 없음), `INPUT_INVALID`(인자·request.txt 오류, 파트 미지정·이름 불일치), `TOOL_OUTPUT_MISSING`(h3d 없음), 그 외 Tcl 오류는 `TOOL_LOG_ERROR`.
- 시작 시 출력 폴더에 이전 산출물(`done.json`, `*.csv`)이 있으면 **삭제하지 않고** `<output>/_backup/<YYYYmmdd_HHMMSS>[_N]/`로 `file rename` 한 뒤 새로 쓴다(그 외 파일은 그대로). 이동 사실은 `warnings`와 `backup_dir`에 남는다. `done.json`은 마지막에 쓰며, 없으면 Python은 `TOOL_OUTPUT_MISSING`.
- 수치 출력: 질의 결과 문자열을 그대로 쓰지 않고 모든 시간·좌표·변형률·변위를 `format %.17g`로 쓴다(double 왕복 무손실). `done.json`의 `disp_value_format`에 기록.
- **정밀도 주의**: h3d 변위는 float32로 저장될 수 있다(유효숫자 ~7자리). `disp.csv`는 대상 파트 기준 상대좌표가 아니라 **전역 변위**이므로, 원점에서 멀거나 강체 이동이 큰 파트는 변형 성분이 float32 잡음에 묻혀 F_eq(등가 하중)에 잡음이 생길 수 있다. `%.17g`는 저장된 값을 손실 없이 옮길 뿐 h3d 자체 정밀도를 높이지 못한다.
- 클라우드 쪽: `esl.io.pack_results(<폴더>, model, out_dir)`.

## 4. probe.json

성공 `ok:true`: `components[]`(id, name, n_elems — rad 없이 title로 part_id 확인), `subcases[]`(id, label, n_simulations, 처음·끝 simulation 라벨, data_types[name, components, layers]),
`selection`(`-part`/part_id/part_title이 있을 때: 요소·노드 선택 문자열별 크기, 요소 query 샘플, `node.coords` 샘플), `part_id`, 그리고 §6의 진단 항목.
실패 `ok:false`: §6 진단 항목 + 실패 전까지 얻은 `components`·`subcases`. **probe.json은 오류가 나도 항상 써진다.**
출력 폴더를 만들거나 쓸 수 없으면 내용을 stderr(hw 콘솔)에 찍고 스크립트 폴더에 `esl_probe_fallback.json`
(extract는 `esl_extract_done_fallback.json`)으로 남긴다.

## 5. 미검증 항목 (실제 HyperView에서 확인 필요)

1. 스크립트 인자 전달: `hw ... -tcl script -input ...`의 추가 인자가 Tcl `$argv`로 들어오는지(안 되면 환경변수 사용).
2. 파트 선택 문자열(`component N` 등)과 `poISelectionSet Clear/GetSize` 이름.
3. `poIContourCtrl SetLayer`, `SetAverageMode none` 이름·값, 요소 중심값이 `element.id contour.value` 한 행으로 나오는지(코너값이면 여러 행).
4. 텐서 성분 이름(`XX YY XY`)과 h3d XY가 텐서 전단인지 공학 전단인지(Radioss 쉘 변형률 — `shear_is_engineering`로 조정).
5. 결과 좌표계(**미검증**): `strain_system=elemental`이면 contour에 요소 국부계("Elemental System")를 명시 설정하려 시도한다. API 이름(`SetResolvedIn` 등)·값 문자열이 버전마다 다를 수 있어, 실패 시 경고만 남기고 기본계로 계속한다 — `done.json` `strain_system_call`이 비어 있으면 HyperView에서 결과계를 직접 확인할 것.
6. simulation 라벨에서 시간 추출 형식, `SetCurrentSimulation` 후 `Draw` 필요 여부.
7. `node.coords`가 원좌표인지 현재 변형좌표인지(프레임 0이면 같음).
8. 배치 모드 종료 시 `exit` 동작.

## 6. 오류 진단 (probe.json / done.json)

모든 HyperView 호출은 이름 붙은 **단계**로 실행되고 결과가 기록된다.

| 키 | 내용 |
|---|---|
| `failed_step` | 실패한 단계 이름(예 `SetClientType`, `AddModel`, `GetModelHandle`). `after X`는 X는 성공했고 그 뒤 Tcl 처리에서 실패 |
| `error` / `errorCode` / `errorInfo` | Tcl 오류 메시지, `$::errorCode`, `$::errorInfo` 전체(호출 위치 스택) |
| `steps_done` | 성공한 단계 목록. `이름[대체경로]`는 어느 대체 시도가 성공했는지 |
| `api` | 단계별 `ok: 결과` / `error: 메시지 \| GetError: <hwISession GetError 메시지>`. 대체 시도 실패는 `<단계>.failed` |
| `traces` | 실패한 단계·대체 시도별 errorInfo |
| `env` | `tcl_version`, `tcl_patchLevel`, `executable`(`info nameofexecutable`), `argv`, OS, `hw_version.*`(얻을 수 있는 API만), `ALTAIR_HOME` 등 환경변수, `hw_commands`, 입력 파일 `input_ext`·`input_size`·`input_mtime`·`input_head_hex`(앞 16바이트) |

**자동 대체 경로**(성공한 쪽이 `api`에 기록됨):
- handle 이름에 `<pid>_<clock>` 접미사 → 같은 hw 세션 재실행 시 "object with this name already exists" 충돌 회피.
- `GetPageHandle`: 활성 페이지 → 페이지 1. `GetWindowHandle`: 활성 창 → 창 1 → 창 0 → `hwIProject GetWindowHandle`.
- `SetClientType`: `GetClientType`이 이미 Animation이면 생략, 아니면 `Animation` → `animation` → `HyperView` → `hwc client animation`.
- `AddModel`: 반환값 0(Null_ID = 로드 실패)도 실패로 처리 → `file nativename` 경로로 재시도 → `hwc open animation modelandresult <h3d> <h3d>` → `hwc open animation model <h3d>` (모델 id는 `GetActiveModel`/`GetModelList`).
- component 목록: component(또는 part) 선택 집합 질의 `component.id component.name` → `part.id part.name` → `component.id component.label` → `GetComponentHandle`/`GetPartHandle` + `GetLabel`/`GetName`.

**숫자 오류(예: `"2051"`)**: hwi/poI 메서드는 실패 시 숫자 오류 코드를 Tcl 오류로 던진다(문서: "Returns Success (0) or an error code").
번호별 의미는 Altair가 공개하지 않았다 — `api`의 `GetError:` 메시지(hwISession GetError)와 `failed_step`이 실제 원인을 알려 준다.
알려진 후보: 배치(-b) 모드에서 활성 page/window 없음, 클라이언트 타입 문자열 불일치, AddModel 실패(0 반환) 뒤 `GetModelHandle 0`, handle 이름 충돌.

### 이슈에 붙일 것

1. `probe.json`(또는 `done.json`) **전체**. 출력 폴더에 없으면 스크립트 폴더의 `esl_probe_fallback.json` / `esl_extract_done_fallback.json`.
2. hw 콘솔 출력 전체(`ESL probe failed at step '...'` 줄 포함). 콘솔이 안 보이면 `hw ... > hwlog.txt 2>&1`로 리디렉션.
3. HyperWorks 로그: 실행 폴더의 `hwx.log`/`hw.log`류 파일, `%USERPROFILE%\Documents\Altair` 아래 로그(설치본마다 다름), 그리고 `command.tcl`(hwc 기록)이 있으면 함께.
4. 실행한 명령 한 줄과 HyperWorks 버전(예: 2026.1), 입력 h3d 파일 크기·이름(`*_comp.h3d` 여부).
