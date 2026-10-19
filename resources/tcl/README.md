# HyperView h3d 추출 TCL (ESL 코어 입력)

> **미검증**: 이 두 스크립트는 HyperView 설치 없이 Altair hwi/poI* Tcl API 문서 기준으로 작성했다.
> 저장소 시험(`tests/io/test_tcl_mock.py`)은 가짜 `hwi`로 **문법·흐름·CSV 포맷만** 확인한다.
> 실제 h3d에는 **반드시 `esl_h3d_probe.tcl`을 먼저 실행**해 subcase·결과 유형·성분·layer 이름과
> 파트 선택 문자열이 맞는지 확인한 뒤 `request.txt`를 채운다.

계약: `docs/contracts/esl_core.md` §3.2.

## 1. 실행 (Windows, HyperWorks 2022~2026)

```bat
set HW="C:\Program Files\Altair\2024\hwdesktop\hw\bin\win64\hw.exe"
set TCL=C:\esl\resources\tcl

rem (1) probe: 이름 확인용 probe.json
%HW% -clientconfig hwpost.dat -b -tcl %TCL%\esl_h3d_probe.tcl -input D:\run\drop.h3d -config D:\run\request.txt -output D:\run\probe

rem (2) extract: CSV 폴더 (클라우드 입력 <results_dir>)
%HW% -clientconfig hwpost.dat -b -tcl %TCL%\esl_h3d_extract.tcl -input D:\run\drop.h3d -config D:\run\request.txt -output D:\run\esl_csv
```

- 경로의 `\`는 스크립트 안에서 `/`로 바꾼다. 공백 있는 경로는 `"..."`로 감싼다.
- 인자가 hw에 전달되지 않는 설치본이면 환경변수 `ESL_INPUT`, `ESL_CONFIG`, `ESL_OUTPUT`으로 대신 줄 수 있다.
- 끝나면 `exit 0`(실패 시 `exit 1`)을 호출한다.

## 2. request.txt (`key<TAB>value`, `#` 줄은 주석)

```text
# 키와 값 사이는 반드시 TAB 한 개
part_id	12
subcase	1
frame_stride	1
strain_type	Strain
strain_comps	XX YY XY
layer_bottom	Lower
layer_top	Upper
shear_is_engineering	0
disp_type	Displacement
```

| 키 | 기본값 | 설명 |
|---|---|---|
| `part_id` | (필수) | 대상 Radioss part ID (HyperView component ID) |
| `subcase` | `1` | subcase ID |
| `frame_stride` | `1` | simulation 인덱스 0, s, 2s, … 만 출력 |
| `strain_type` | `Strain` | 변형률 텐서 결과 유형 이름(probe의 `data_types[].name`) |
| `strain_comps` | `XX YY XY` | exx, eyy, exy 순서의 성분 이름 3개 |
| `layer_bottom` / `layer_top` | `Lower` / `Upper` | HyperView layer 이름(probe의 `layers`) |
| `layer_mid` | (빈 값=생략) | 지정 시 `mid` 행도 출력(선택) |
| `shear_is_engineering` | `0` | `1`이면 h3d XY가 공학전단 γ로 보고 TCL이 exy = XY/2로 출력 |
| `disp_type` / `disp_comps` | `Displacement` / `X Y Z` | 변위 결과 유형·성분 |
| `elem_selection` / `node_selection` | (빈 값) | 선택 문자열 직접 지정(예: `component 12`). 비우면 `component N` → `comp N` → `part N` 순으로 시도하고, 모두 실패하면 `all`(다른 파트 행은 Python이 버림, 경고 기록) |

## 3. 출력 (`-output` 폴더)

| 파일 | 헤더 | 비고 |
|---|---|---|
| `frames.csv` | `frame_index,time` | frame_index = subcase 안 simulation 인덱스(0부터). time = simulation 라벨의 `=` 뒤 숫자(없으면 마지막 숫자, 그것도 없으면 인덱스 + 경고) |
| `model.csv` | `node_id,x0,y0,z0` | 첫 출력 프레임의 `node.coords`(프레임 0 = 비변형 가정). Python이 rad 좌표와 `1e-6·bbox` 비교 |
| `strain.csv` | `frame_index,elem_id,layer,exx,eyy,exy` | layer = `bottom`,`top`(필수), `mid`(선택). 요소 국부계 텐서(h3d 저장계 그대로, 평균 없음) |
| `disp.csv` | `frame_index,node_id,ux,uy,uz` | 전역계 변위 |
| `done.json` | | 성공 `{"ok":true,"n_frames","n_elems","n_nodes","h3d","subcase","elem_selection","node_selection","warnings":[]}` / 실패 `{"ok":false,"code","error","h3d","warnings"}` |

- 실패 code: `H3D_MISSING_RESULT`(subcase·결과 유형·layer 없음), `INPUT_INVALID`(인자·request.txt 오류), `TOOL_OUTPUT_MISSING`(h3d 없음), 그 외 Tcl 오류는 `TOOL_LOG_ERROR`.
- 시작 시 이전 `done.json`을 지우고 마지막에 쓴다. `done.json`이 없으면 Python은 `TOOL_OUTPUT_MISSING`.
- 클라우드 쪽: `esl.io.pack_results(<폴더>, model, out_dir)`.

## 4. probe.json

`subcases[]`(id, label, n_simulations, 처음·끝 simulation 라벨, data_types[name, components, layers]),
`selection`(-config에 part_id가 있을 때: 요소·노드 선택 문자열별 크기, 요소 query 샘플, `node.coords` 샘플), `api`(호출 성공 여부).

## 5. 미검증 항목 (실제 HyperView에서 확인 필요)

1. 스크립트 인자 전달: `hw ... -tcl script -input ...`의 추가 인자가 Tcl `$argv`로 들어오는지(안 되면 환경변수 사용).
2. 파트 선택 문자열(`component N` 등)과 `poISelectionSet Clear/GetSize` 이름.
3. `poIContourCtrl SetLayer`, `SetAverageMode none` 이름·값, 요소 중심값이 `element.id contour.value` 한 행으로 나오는지(코너값이면 여러 행).
4. 텐서 성분 이름(`XX YY XY`)과 h3d XY가 텐서 전단인지 공학 전단인지(Radioss 쉘 변형률 — `shear_is_engineering`로 조정).
5. 결과 좌표계: 기본(analysis/저장계)이 요소 국부계라고 가정. 다른 계로 바뀌어 있으면 HyperView 설정 확인.
6. simulation 라벨에서 시간 추출 형식, `SetCurrentSimulation` 후 `Draw` 필요 여부.
7. `node.coords`가 원좌표인지 현재 변형좌표인지(프레임 0이면 같음).
8. 배치 모드 종료 시 `exit` 동작.
