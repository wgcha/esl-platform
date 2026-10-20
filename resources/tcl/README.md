# HyperView h3d 추출 TCL (ESL 코어 입력)

> **미검증**: 이 두 스크립트는 HyperView 설치 없이 Altair hwi/poI* Tcl API 문서 기준으로 작성했다.
> 저장소 시험(`tests/io/test_tcl_mock.py`)은 가짜 `hwi`로 **문법·흐름·CSV 포맷만** 확인한다.
> 실제 h3d에는 **반드시 `esl_h3d_probe.tcl`을 먼저 실행**해 subcase·결과 유형·성분·layer 이름과
> 파트 선택 문자열이 맞는지 확인한 뒤 `request.txt`를 채운다.

계약: `docs/contracts/esl_core.md` §7.2(추출 3패스), 진단·공통 블록은 §3.2 그대로.

## 1. 실행 (Windows, HyperWorks 2022~2026)

### 1.1 Windows 설치·업데이트 (권장: 드래그&드롭)

1. 저장소 클론 폴더의 `update.bat` 더블클릭 → git 최신화(fast-forward만) 후 이 폴더의 TCL과 실행기를
   `%LOCALAPPDATA%\esl\app\versions\<git 해시>\`에 복사하고 활성 버전 파일 `...\app\current_version.txt`만 교체한다
   (폴더 rename 없음 — `current`를 탐색기로 열어 둔 채·실행 중에도 업데이트 가능, 최근 5개 + 활성 버전 유지).
   `...\app\current\`에는 런처(`ESL_probe.bat`, `ESL_extract.bat`, `ESL_upload.bat`, `esl_launch.ps1`)만 있고, 실행할 때마다
   `current_version.txt`가 가리키는 `versions` 폴더의 TCL을 쓴다. 예전 구조(`current`에 TCL이 직접 있음)는 첫 업데이트 때
   배포 산출물만 파일 단위로 정리한다(사용자 파일은 그대로).
2. 설정 파일 `%LOCALAPPDATA%\esl\esl_deploy.json`(처음 실행 시 생성): `hw_exe`, `work_root`(출력 루트 — 공유 SPDM 폴더 금지),
   `protected_roots`, `default_part`, `server_url`(ESL 서버 주소, §1.3)을 확인하고 `update.bat`을 다시 실행해 점검표가 모두 OK인지 본다.
3. `...\app\current\ESL_probe.bat` / `ESL_extract.bat` 위로 h3d를 끌어다 놓는다. 출력은
   `<work_root>\<h3d 이름>\probe` / `csv`, 다른 파트는 `ESL_extract.bat <h3d> <part>`. 끝나면 `probe.json`/`done.json`의
   `ok`·`failed_step`·`error`를 요약하고 출력 폴더를 연다. 콘솔 로그는 `*_console.log`.
   h3d 폴더·`protected_roots` 아래 출력과 `%`·`!`·`&`가 든 경로는 거부한다.
   **h3d를 배포 폴더(`...\app` 아래)에 복사하지 말 것**: 배포 폴더 안의 h3d는 거부한다.
   원본 위치의 h3d를 그대로 끌어다 놓는다(읽기 전용으로 사용). `update.bat`은 배포 산출물
   (`*.tcl`, `*.bat`, `*.ps1`, README, `VERSION.txt`) 이외 파일·하위 폴더를 지우거나 옮기지 않으며, 그런 파일이 있는 폴더는
   정리하지 않고 목록만 경고한다.

### 1.2 수동 실행

```bat
set HW="C:\Program Files\Altair\2026.1\hwdesktop\hw\bin\win64\hw.exe"
set TCL=C:\esl\resources\tcl

rem (1) probe: h3d 안의 component(=Radioss part) 목록·결과 유형·성분·layer → probe.json
%HW% -clientconfig hwpost.dat -b -tcl %TCL%\esl_h3d_probe.tcl -input D:\run\drop.h3d -output D:\run\probe

rem (2) extract: 대상 파트를 title(또는 숫자 id)로 지정 → CSV 폴더 (클라우드 입력 <results_dir>)
%HW% -clientconfig hwpost.dat -b -tcl %TCL%\esl_h3d_extract.tcl -input D:\run\drop.h3d -part chassis_rear -output D:\run\esl_csv
rem    선택: -hot_k 200 (이력 요소 수) -top_n 5 (지표별 후보 프레임 수)
```

- `-part <title|id>`: 숫자면 component(part) id, 아니면 title. title은 **대소문자·공백·언더스코어를 무시**하고 비교한다(`Chassis Rear` = `chassis_rear`). 우선순위: `-part` 인자 > request.txt `part_id` > request.txt `part_title`.
- extract에서 파트를 정하지 못하면(지정 없음·이름 없음·여러 개 일치) `done.json`이 `ok:false`(`INPUT_INVALID`)이고 `components` 목록이 함께 기록된다 — 거기서 이름/ID를 골라 다시 실행.
- probe는 `-part` 없이도 component 목록(`id`, `name`, `n_elems`)과 모든 결과 유형을 기록한다. `-part`를 주면 선택 문자열 시험·샘플 질의도 한다.
- `-config <request.txt>`는 **선택**(고급 옵션, §2). 없거나 파일이 없으면 기본값으로 동작(파일이 없으면 `warnings`에 기록).
- 경로의 `\`는 스크립트 안에서 `/`로 바꾼다. 공백 있는 경로는 `"..."`로 감싼다.
- 인자가 hw에 전달되지 않는 설치본이면 환경변수 `ESL_INPUT`, `ESL_OUTPUT`, `ESL_PART`, `ESL_CONFIG`로 대신 줄 수 있다.
- 끝나면 `exit 0`(실패 시 `exit 1`)을 호출한다.

### 1.3 PC에서 추출해 ESL 서버로 올리기 (`ESL_extract.bat` 자동 올리기 · `ESL_upload.bat`)

계약: `docs/contracts/esl_p3_ux.md` §9. 대용량 h3d(수~수십 GB)를 서버로 올리는 대신, PC에서 추출한 결과 폴더(수백 MB)와
rad·include만 올린다. 브라우저 대신 PC 도구가 업로드 API(§1.1·§8)를 직접 부른다.

1. **처음 한 번 — PC 연결**: ESL 화면 새 Case → "PC에서 추출해 올리기" → "PC 연결 코드 만들기"(6자리, 15분, 현재 프로젝트에 묶임).
   도구를 처음 실행하면 서버 주소(설정 `server_url`, 예 `http://<대시보드 주소>/esl` — 비어 있으면 묻고 `esl_deploy.json`에 저장)와
   연결 코드를 묻는다. 받은 토큰은 DPAPI(현재 Windows 사용자 범위)로 암호화해 `%LOCALAPPDATA%\esl\client_token.bin`에 둔다
   (평문 저장 없음, 다른 사용자·다른 PC에서는 풀 수 없음). 토큰이 만료·폐기되면(서버 401) 코드를 다시 묻는다.
2. **h3d와 rad(`_0000.rad`)를 함께 `ESL_extract.bat` 위로 끌어다 놓는다**(h3d만 놓으면 rad 파일 선택 창, 취소 = 추출만):
   ① PC HyperView 추출(§1.1과 같음, 출력 `<work_root>\<h3d 이름>\csv`, h3d 폴더에는 쓰지 않음)
   ② rad의 `/INCLUDE`·`#include`를 재귀로 따라 include 수집(rad 폴더 기준 상대경로·절대경로, 서버와 같은 규칙).
      못 찾은 include(예: 이 PC에 없는 드라이브의 절대경로)·rad 폴더 밖 상대경로는 경고하고 계속할지 묻는다.
      rad 폴더 아래 include는 `rad/<상대경로>`, 절대경로 include는 `rad/<파일 이름>`으로 올린다(서버가 파일 이름으로 찾음).
   ③ 올리기: 결과 폴더(`results/csv/...`, `.log` 등 허용 확장자 밖은 제외) + rad + include. 서버 청크 크기(기본 16 MB)로
      FileStream에서 읽어 보내고(파일 전체를 메모리에 올리지 않음) 청크마다 sha256(`X-Chunk-Sha256`)을 붙인다.
      네트워크 오류·5xx는 지수 백오프로 5회 재시도, 409(`UPLOAD_OFFSET_MISMATCH`)면 서버가 받은 크기부터 이어 보낸다.
      콘솔에 진행률·속도·남은 시간을 표시한다.
   ④ 서버 검사(complete) → 서버가 누락 include를 알려 주면 이 PC에서 찾아 추가로 올리고 다시 검사 →
      브라우저로 `<server_url>/p/<프로젝트>/cases/new?upload=<id>`를 연다("Case 만들기"만 누르면 됨).
3. **중단·실패 후**: 같은 파일로 다시 실행하면 서버 세션을 이어 간다(`%LOCALAPPDATA%\esl\uploads.json`: h3d 경로·크기·수정 시각 →
   upload_id). 추출 없이 올리기만: csv 폴더와 rad를 `ESL_upload.bat` 위로 끌어다 놓기(`ESL_upload.bat <결과 폴더> [<rad>]`).
   결과 파일이 바뀌었으면(다시 추출) 이전 미완료 세션은 취소하고(서버 `_backup`으로 이동, 삭제 없음) 새로 올린다.
4. **네트워크**: 사내 서버 주소는 Windows 시스템 프록시 설정을 따르고(현재 사용자 자격 증명), 루프백(`localhost`, `127.*`)은
   프록시를 쓰지 않는다. 요청 제한 시간 15분(청크 하나 기준).

## 2. 고급 옵션: request.txt (`key<TAB>value`, `#` 줄은 주석, 선택)

기본값은 실데이터 probe(HyperWorks 2026.1) 이름이다. 바꿀 키만 적으면 된다.

```text
# 키와 값 사이는 반드시 TAB 한 개
part_title	chassis_rear
strain_type	Max_Strain
strain_comps	XX YY ZZ XY
vm_comp	vonMises
strain_layer	Mid
epsp_type	Plastic Strain
epsp_comp	Scalar value
epsp_layer	Mid
hot_k	200
top_n	5
reach_rtol	1e-6
chunk	50000
```

| 키 | 기본값 | 설명 |
|---|---|---|
| `part_id` / `part_title` | (빈 값) | 대상 파트. `-part` 인자가 우선, title은 대소문자·공백·언더스코어 무시 |
| `subcase` | `1` | subcase ID |
| `strain_type` | `Max_Strain` | 요소별 max-hold 변형률 텐서 결과 유형 |
| `strain_comps` | `XX YY ZZ XY` | exx, eyy, ezz, exy 순서 성분 이름 4개. **XY는 h3d 값 그대로** 출력(텐서/공학 전단은 Python이 `vonMises`와 비교해 판정, 설정 `extract.shear_convention`) |
| `vm_comp` | `vonMises` | HyperView 등가변형률 성분(전단 규약 판정·H 선택·후보 프레임용) |
| `strain_layer` | `Mid` | 변형률 layer(실데이터는 Mid만 있음) |
| `epsp_type` / `epsp_comp` / `epsp_layer` | `Plastic Strain` / `Scalar value` / `Mid` | 소성 변형률(max-hold). `epsp_type`을 비우면 소성 0 + 경고 |
| `disp_type` / `disp_comps` | `Displacement` / `X Y Z` | 변위 결과 유형·성분 |
| `hot_k` | `200` | H = 최종 vonMises 상위 hot_k ∪ 최종 소성 상위 hot_k(값 > 0). 상한 없음(1000 초과 시 경고). `-hot_k`가 우선 |
| `top_n` | `5` | 지표별 후보 프레임 수. `-top_n`이 우선 |
| `reach_rtol` | `1e-6` | first-reach 허용오차: `v[f] ≥ v_last·(1−rtol)`인 첫 프레임 |
| `chunk` | `50000` | 요소·노드 질의 청크 크기(id 범위 선택 집합을 청크마다 한 번 만들어 재사용, 행은 바로 파일로) |
| `strain_system` | `elemental` | 텐서 결과 좌표계 `elemental`/`analysis`/`global`/`none`. **미검증**: `SetResolvedIn` → `SetResultSystem` → `SetSystemType` → `SetSystem` 순으로 시도, 모두 실패하면 기본계 + `warnings` 1회. 성공한 호출은 `done.json` `strain_system_call` |
| `elem_selection` / `node_selection` | (빈 값) | 파트 선택 문자열 직접 지정(예: `component 12`). 비우면 `component N` → `comp N` → `part N` → `all`(다른 파트 행은 Python이 버림) |

## 3. 3패스 추출과 출력 (`-output` 폴더)

h3d의 `Max_Strain`·`Plastic Strain`은 **요소별 누적 최대(max-hold)**다(한 번 최대에 도달하면 그 값을 유지).
그래서 t*는 "최종값에 처음 도달한 프레임(first-reach)"이고, 전 요소 × 전 프레임을 뽑지 않고 3패스로 줄인다.

| 패스 | 대상 | 파일 | 헤더 |
|---|---|---|---|
| — | 전 프레임 시간 | `frames.csv` | `frame_index,time` |
| — | 프레임 0 파트 노드 좌표 | `model.csv` | `node_id,x0,y0,z0` |
| A | 마지막 프레임, 파트 전 요소(청크) | `final.csv` | `elem_id,vm_hv,exx,eyy,ezz,exy,epsp` |
| B | 전 프레임, 집합 H(≤ 400 요소, id 선택 집합 1개) | `history.csv` | `frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp` |
| C | 후보 프레임 D, 파트 전 요소·전 노드(청크) + 직전 프레임 P, 파트 전 요소 | `strain_frames.csv`, `disp.csv` | 위와 같음 / `frame_index,node_id,ux,uy,uz` |

- **H**: 패스 A에서 청크마다 상위 hot_k를 갱신(값 내림차순, 동률은 낮은 id). 
- **D**: 지표(vonMises, 소성)마다 H를 최종값 내림차순으로 훑으며 first-reach 프레임 `min{f : v[f] ≥ v_last·(1−reach_rtol)}`을
  서로 다른 것만 `top_n`개 모은 합집합(≤ 2·top_n). rank 1 = 최종값 1위 요소의 first-reach. 후보가 없으면 D = 마지막 프레임 + 경고.
  Python(`esl.mech.tstar.candidate_frames`)이 history로 같은 규칙을 재계산해 일치를 확인한다.
- **직전 프레임 P**(계약 `esl_p2_library.md` §7.1): D 의 각 f 에 대해 f−1(≥ 0). D 에 이미 있는 프레임은 한 번만 쓴다.
  P 프레임은 전 요소 Max_Strain·Plastic 만(변위 없음) `strain_frames.csv` 에 같은 형식으로 추가(frame_index 로 구분) →
  클라우드에서 전 요소 "상승 중" 마스크 `v[f] > v[f−1]·(1+rtol)`(f=0 이면 v>0)를 만든다. 패스 C 질의량은 최대 2배.
  진행률 줄에 `(prev)` 표시. `done.json` `prev_frames`(P), `strain_frames`(D ∪ P), `passes.C.prev_frames`.
- **패스 B 선택 집합**(미검증): `id a-b c ...` → `element a-b c ...` → 콤마 형식 → id마다 `Add "id N"`/`"element N"`, 크기(`GetSize`, 없으면 질의 개수)로 확인.
  모두 실패하면 파트 전 요소 청크를 프레임마다 질의해 H만 남긴다(느림, 경고·`passes.B.hot_selection`).
  청크 선택도 같은 방법이며 실패하면 파트 전체 집합 한 번 질의(메모리 큼, 경고·`chunks`).
- 프레임 루프는 `SetCurrentSimulation` → `Draw` → 질의. 진행률(패스·프레임·청크)을 콘솔에 `ESL extract HH:MM:SS pass B frame 12/126 ...`으로 찍는다.
- `done.json` 성공: `{"ok":true,"part_id","part_title","n_frames","n_elems","n_nodes","n_hot","hot_k","top_n","reach_rtol",
  "candidate_frames":{"max_strain":[..],"plastic_strain":[..]},"candidate_elems":{...},"frames_D":[..],"prev_frames":[..],"strain_frames":[..],
  "passes":{"A":{"frame","rows","chunks","seconds"},"B":{"frames","n_hot","rows","hot_selection","seconds"},"C":{"frames","prev_frames","strain_frames","rows_strain","rows_disp","elem_chunks","node_chunks","seconds"}},
  "chunk","chunks","strain_type","strain_layer","strain_comps","vm_comp","epsp_type","epsp_layer","disp_type","exy":"raw (as stored in h3d)",
  "value_format":"%.17g","strain_system","strain_system_call","backup_dir","warnings":[]}` + §6 진단 항목. 실패 `{"ok":false,"code","error","failed_step",...}`.
- 실패 code: `H3D_MISSING_RESULT`(subcase·결과 유형·성분·layer 없음 — 가능하면 `GetDataComponentList`/`GetLayerList`로 미리 확인, 값 없음),
  `INPUT_INVALID`(인자·request.txt 오류, 파트 미지정·이름 불일치), `TOOL_OUTPUT_MISSING`(h3d 없음), 그 외 Tcl 오류는 `TOOL_LOG_ERROR`.
- 시작 시 출력 폴더의 이전 산출물(`done.json`, `*.csv`)은 **삭제하지 않고** `<output>/_backup/<YYYYmmdd_HHMMSS>[_N]/`로 옮긴다(그 외 파일은 그대로).
- 수치는 모두 `format %.17g`(double 왕복 무손실). h3d 변위는 float32일 수 있다 — `%.17g`는 저장값을 옮길 뿐 정밀도를 높이지 못한다(클라우드 S4 잡음 바닥 추정).
- **CSV 크기 추정**(22만 요소·노드, D ≤ 10, 126 프레임, %.17g): `strain_frames.csv` ≈ 150 B/행 × 220만 행 ≈ 330 MB
  (직전 프레임 P 포함 시 최대 약 2배 ≈ 660 MB),
  `disp.csv` ≈ 80 B/행 × 220만 행 ≈ 180 MB, `final.csv` ≈ 30 MB, `history.csv` ≈ 400 × 126 행 ≈ 8 MB → 합계 약 0.55 GB(전량 추출 시 수 GB).
- 클라우드 쪽: `esl.io.pack_results(<폴더>, model, out_dir)` → `final.npz`, `history.npz`, `strain_frames.npz`(+ `prev_*`), `disp.npz`(§7.3).

## 4. probe.json

성공 `ok:true`: `components[]`(id, name, n_elems — rad 없이 title로 part_id 확인), `subcases[]`(id, label, n_simulations, 처음·끝 simulation 라벨, data_types[name, components, layers]),
`selection`(`-part`/part_id/part_title이 있을 때: 요소·노드 선택 문자열별 크기, 요소 query 샘플, `node.coords` 샘플), `part_id`, 그리고 §6의 진단 항목.
실패 `ok:false`: §6 진단 항목 + 실패 전까지 얻은 `components`·`subcases`. **probe.json은 오류가 나도 항상 써진다.**
출력 폴더를 만들거나 쓸 수 없으면 내용을 stderr(hw 콘솔)에 찍고 스크립트 폴더에 `esl_probe_fallback.json`
(extract는 `esl_extract_done_fallback.json`)으로 남긴다.

## 5. 미검증 항목 (실제 HyperView에서 확인 필요)

1. 스크립트 인자 전달: `hw ... -tcl script -input ...`의 추가 인자가 Tcl `$argv`로 들어오는지(안 되면 환경변수 사용).
2. 파트 선택 문자열(`component N` 등)과 `poISelectionSet Clear/GetSize` 이름.
3. `poIContourCtrl SetLayer`, `SetAverageMode none` 이름·값, 요소 중심값이 `element.id contour.value` 한 행으로 나오는지(코너값이면 첫 행만 사용).
4. h3d XY가 텐서 전단인지 공학 전단인지 — Python이 `vonMises`와 비교해 자동 판정(`extract.shear_convention: auto`), 최대 불일치 > 5%면 경고.
4a. **id 선택 문자열**(`id a-b c`, `element a-b`, 콤마 형식, `Add "id N"` 반복)과 `poISelectionSet GetList`/`GetSize`, `node.id`/`element.id`만 있는 질의.
4b. `Max_Strain`의 텐서 성분이 vonMises와 같은 프레임 값으로 hold되는지(성분별 hold면 hold 텐서의 ε_eq ≠ vonMises — 전단 판정 불일치로 드러남).
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
- 결과 로드: `AddModel`은 모델만 읽는다. `GetModelHandle` 뒤 `poIModel SetResult <h3d>`(실패 시 `file nativename` 경로)
  → `poIPost Draw` → `GetResultCtrlHandle`. SetResult 없이 `GetResultCtrlHandle`을 부르면 HyperWorks 2026.1에서
  `2051` / GetError `ERROR:No results loaded.  (poIModel::GetResultCtrlHandle)`로 실패했다(실기). SetResult 실패는
  `api.SetResult`(GetError 포함)·`warnings`에 남고 `GetResultCtrlHandle` 오류 문구에 덧붙는다.
- component 목록: component(또는 part) 선택 집합 질의 `component.id component.name` → `part.id part.name` → `component.id component.label` → `GetComponentHandle`/`GetPartHandle` + `GetLabel`/`GetName`.

**Tcl 버전**: HyperWorks 2026.1의 내장 Tcl은 8.5.9(실기 `env.tcl_patchLevel`)이다. 두 TCL은 Tcl 8.5 문법만 쓴다
(`lmap`·`try`/`throw`·`string cat`·`file tempfile`·`zlib`·`oo::`·`-stride` 등 8.6 전용 기능 금지, `tests/io/test_tcl_mock.py` 정적 검사).
`ESL_TCLSH85=<tclsh8.5 경로>`를 주면 mock 시험을 Tcl 8.5로도 돌린다.

**숫자 오류(예: `"2051"`)**: hwi/poI 메서드는 실패 시 숫자 오류 코드를 Tcl 오류로 던진다(문서: "Returns Success (0) or an error code").
번호별 의미는 Altair가 공개하지 않았다 — `api`의 `GetError:` 메시지(hwISession GetError)와 `failed_step`이 실제 원인을 알려 준다.
알려진 후보: `GetResultCtrlHandle`에서 "No results loaded"(SetResult 전 호출 — 수정됨), 배치(-b) 모드에서 활성 page/window 없음, 클라이언트 타입 문자열 불일치, AddModel 실패(0 반환) 뒤 `GetModelHandle 0`, handle 이름 충돌.

### 이슈에 붙일 것

1. `probe.json`(또는 `done.json`) **전체**. 출력 폴더에 없으면 스크립트 폴더의 `esl_probe_fallback.json` / `esl_extract_done_fallback.json`.
2. hw 콘솔 출력 전체(`ESL probe failed at step '...'` 줄 포함). 콘솔이 안 보이면 `hw ... > hwlog.txt 2>&1`로 리디렉션.
3. HyperWorks 로그: 실행 폴더의 `hwx.log`/`hw.log`류 파일, `%USERPROFILE%\Documents\Altair` 아래 로그(설치본마다 다름), 그리고 `command.tcl`(hwc 기록)이 있으면 함께.
4. 실행한 명령 한 줄과 HyperWorks 버전(예: 2026.1), 입력 h3d 파일 크기·이름(`*_comp.h3d` 여부).
