# 계약: 비드 자동 탐지 → 직접 선택(select) 초기 선택 · ② B 메시 기준 select · 공통 코어 정리 (BEAD_AUTO, v0.16.2)

- **v0.17.0 변경 = `esl_beadgraph.md`**(BEADGRAPH — 선택 schema 2 스터디의 자동 seed 출처 = 메시 분류기. schema 1 스터디는 이 문서 그대로).
- 상태: **확정** (2026-11-08). 기본안(AD-D-1~12, API, V-AD-1~8, R-AD-1~5) = 사용자 승인안 그대로. ② `mesh` 의 select 전환(AD-D-13~23, V-AD-9~15, R-AD-6~10) = 사용자 선택(2026-11-08)을 코드 조사로 구체화. 막힌 항목은 §13 열린 항목(해법을 만들지 않음).
- 버전: **v0.16.2** (기준 main 4008821 = v0.16.1). migration **불필요**(§3.4).
- 관계: `esl_select_relax.md`(SELECT_RELAX, v0.16.1 — 이하 "SR")·`esl_bead_select.md`(BEAD_SELECT, v0.15.0 — 이하 "BS")의 **변경 계약**. ② 부분은 `esl_bead_doe.md`(BEAD_DOE — 이하 "BD") BD-D-3·4·12·14 와 `esl_step_compare.md`(이하 "SC") SC-D-6, `esl_compare_mesh_options.md`(이하 "C2") C2-D-2~7 을 **재사용**한다(새 매핑 없음). 이 문서에 없는 규칙은 SR → BS → BD 순서로 따르고, 충돌 시 이 문서가 우선.
- ID 규칙: 결정 `AD-D-n`, 시험 `V-AD-n`, 리스크 `R-AD-n`, 열린 항목 `O-n`.
- 구현 갱신(2026-11-08 v0.16.2 통합): 구현이 계약과 다르게 정한 4건을 수용 편차로 §14 에 기록(AD-X-1~4). §14 가 해당 문장(§4 2, AD-D-2·17, V-AD-2·10·13)보다 우선.

### 사용자 확정 (2026-11-08, 변경 금지)
1. **자동 탐지 = select 의 출발점**: 자동 탐지(paicad extract·tag)는 별도 시나리오가 아니라 시나리오 `select` 의 **초기 선택(seed) 출처**. 화면은 수동 직접 선택과 같고, seed 는 사용자가 고칠 수 있다.
2. **① 새 스터디는 `select` 만**: `same` 은 새로 만들지 않는다(기존 스터디는 실행·복제 계속). 최적 안 STEP 내보내기는 나중의 받기 옵션(이번 범위 아님).
3. **② `mesh` 도 같은 전환**: B 메시(다른 모델 메시, paicad 사용) 스터디도 자동 탐지 → `select`, 같은 화면. 기존 `mesh` 스터디는 그대로 실행.

## 0. 현황 (4008821, 근거 파일:행)

| # | 항목 | 근거 | 현재 동작 | 이 계약에서 |
|---|---|---|---|---|
| A1 | select 기준 메시 | `esl/doe/stages.py:2188-2212`(`_sel_input` → `sc.same_base`) | ① Case 메시 제자리 읽기만(S1, 같은 모델 필수) | `select_base: case | mesh` 분기(AD-D-15) |
| A2 | select 하중 | `stages.py:2215-2230`(`_sel_loads` → `sc.entry_loads(t, …)`) | `t.scenario` 로 S1 직접/S2 셀 매핑 분기 — 이미 S2 경로를 가짐 | 그대로(② 기준이면 S2 셀 매핑) |
| A3 | ② 기준 메시 | `stages.py:189-207`(`bd_input` mesh 분기: `copy_mesh_upload` → `load_mesh` → `template_base`), `esl/doe/scenario.py:158-168`, `esl/opt/target.py:160-171`(`build_template`: `nz.frame` → `align_normals` → `auto_supports`) | B 원 노드 ID 유지, frame = B, 지지 = B 자동 3-2-1 | 함수로 뽑아 select 와 공유(AD-D-15) |
| A4 | ④ 형상 하중·지지 | `scenario.py:376-381`(`compare_target` → `align_normals` → `design_target` → `auto_supports`), `stages.py:1826-1833`(`_cmp_design_mesh` → `entry_loads` S2) | 기준 frame 고정 셀 매핑 + 형상별 auto_supports | ②-select 와 **같은 함수**(V-AD-9) |
| A5 | ④ 메시 입력 번호 | `esl/doe/mesh_input.py:1-12`(`read_shape_mesh` → `mg.build_mesh` 1..N 재번호 + `id_map.npz`) | 원 ID 를 버리고 재번호 | ②-select 에는 쓰지 않음(AD-D-15 — paicad tag·fixed-scan·받기 include 가 원 ID) |
| A6 | ② 경계 경고 | `stages.py:321-361`(`_boundary`, `:340` `c.scn == "mesh"` 일 때만 `prep/fixed` 를 B 체결 후보로) | A 체결점(`prep/a_fixed`·ESL 3-2-1)을 (a,b) 로 투영해 **경고만** | `select_base == mesh` 도 같은 조건(AD-D-18) |
| A7 | ②·select 안 메시 | `stages.py:455-461`(select: 기저 좌표 + `loads.npz` + `t.supports`), `:462-479`(same·mesh: paicad out_files 좌표 + 같은 `loads.npz`·`t.supports` + `mcore.post_morph_warnings`) | 둘 다 "하중·지지 = 베이스라인 1회, 모든 안 재사용" | ②-select 도 같음(AD-D-19) |
| A8 | worker BD_GEOM | `worker/esl_worker/doe_jobs.py:287`(select → `_geom_select:514-` = assem_full + fixed-scan 만), `:410-423`(② assem = `input/mesh`, plan = `[a_fixed] + fixed + extract0 + extract + tag`) | select 는 extract·tag 없음 | select plan 확장(AD-D-2·17) |
| A9 | 받기 파일 | `stages.py:2466-2490`(`_sel_rad_files` = `D.base.rad_path` include 트리), `:2584`(`part_title = D.base.part_title`) | ① Case 전용 | `select_base == mesh` 면 `input/mesh` 사본(AD-D-20) |
| A10 | API select 검사 | `backend/esl_platform/api/services/doe.py:387-390`(select 에 step·mesh·part_title 오면 422), `:403`(select = 같은 모델 검사), `:1369`(select 는 업로드 입력 없음) | | `bead_source`·`select_base` 로 분기(§3.3) |
| A11 | DB CHECK | `backend/esl_platform/core/db/tables.py:573-577`(scenario IN 5종, `selection` 은 select 만, `base` NOT NULL 은 same 만) | select + base NULL 허용 | migration 불필요(§3.4) |
| A12 | 규칙 판·상수 | `esl/doe/bead_select.py:55`(`U_EPS`), `:58-59`(`ALGO = 2`·`RULES = 2`), `:920-922`(`_bridge_holes` → `esl.morph.core.bridge_holes`) | 상수 중복·구멍 건너 잇기 상한 없음 | AD-D-7·10·11 |

## 1. 범위 / 비범위

| 범위 (v0.16.2) | 비범위 |
|---|---|
| ① 하위 라디오 "자동 탐지"/"수동" → `select`(`doe.bead_source`), 새 ① 스터디의 `same` 숨김 | 최적 안 STEP 내보내기(나중의 받기 옵션) |
| DOE_PREP 안 자동 탐지(paicad assem_full→fixed-scan→extract0→extract→tag) → `prep/select/auto_selection.json` | paicad 범위(ranges)·사면(flanks) 값 채우기(힌트만 — AD-D-12) |
| `esl/doe/bead_auto.py auto_selection`(1단/비드, 바닥 = tag FACE 노드, 섬 제외) | 다단 비드 자동 분리(R-AD-2 — 사용자가 단 추가) |
| seed = 화면 기본 상태(되돌리기·비드별/전체 초기화 기준), 저장 전 미저장 | 새 하중·구속 매핑 방식 |
| 자동 경로 공통 코어 점검(SR-D-37/38/33/39/40), 극단 요소 경고 노출, range_check·U_EPS·ALGO/RULES 정리, 구멍 건너 잇기 상한 | A 체결점의 B 고정 노드 이전(§13 O-1) |
| **② `select_base: mesh`**: B 메시(.rad/.inc + 파트) 기준 select, ② 셀 매핑 하중·자동 3-2-1·B fixed-scan 재사용, 경계 경고 유지 | STEP → gmsh B 메시 기준 select(§13 O-2), `.bdf/.fem`(D-0.16-Q2) |
| 기존 `same`·`mesh` 스터디 실행·복제 유지 | 기존 `same`/`mesh` 스터디 → `select` 자동 변환 |

## 2. 결정 — 자동 탐지 (사용자 승인 기본안)

| ID | 결정 | 근거 |
|---|---|---|
| AD-D-1 | **① 하위 라디오** "자동 탐지" = `select` 생성 + `doe.bead_source: "auto"`, "수동" = `"manual"`(기본). 새 ① 스터디는 `same` 을 만들지 않는다 — 화면 새 스터디 목록에서 `same` 숨김. 기존 `same` 스터디는 그대로 실행·복제(복제본도 `same`). 최적 안 STEP 내보내기는 나중의 받기 옵션(범위 밖) | 확정 1·2 |
| AD-D-2 | **DOE_PREP**(BD_GEOM, select·auto)는 기존 paicad 순서 `assem_full → fixed-scan → extract0 → extract → tag` 를 그대로 실행(②: assem = `input/mesh`, AD-D-17). 실패해도 준비는 **READY** 유지 + 경고 `AUTO_DETECT_FAILED{step, code}` + 빈 seed(선택 0, 수동 계속). fixed-scan 실패는 BS-D-8 그대로 `FIXED_INFO_MISSING`. worker 는 결과를 `prep/auto_detect.json` = `{schema:"esl/doe_auto_detect/1", ok, step|null, code|null, paicad_version}` 로 남기고, 코어 BD_LOADS 가 읽는다 | 자동 탐지 실패가 수동 선택을 막으면 안 됨 |
| AD-D-3 | **신규 `esl/doe/bead_auto.py`** `auto_selection(mesh, extract_doc, tag_npz, cfg) -> {selection, map, warnings}`. `selection` = SelectionIn **schema 1**(BS §4.1 그대로). 바닥 = 그 비드 bottom face 에 tag 된(FACE) 노드가 **모두** 들어가는 요소, 여기서 `esl.mesh.features.enclosed_components` 섬을 뺌. 비드당 **1단**, `slope: auto`, `blend: auto`, `hold_fixed: 0`. id = `b1..bn`(paicad 비드 순서). 경고 `AUTO_TOO_MANY_BEADS`(> `select.max_beads`, 앞에서부터 자름), `AUTO_GROUP_DROPPED`(info — paicad 묶음 해제), `AUTO_BEAD_UNMAPPED`(바닥 요소 0). 출력 `prep/select/auto_selection.json`, **결정적 바이트**(정렬 키·`write_json` 고정) | 공통 모듈 SR-D-23 의 예약 호출 지점 |
| AD-D-4 | **화면 seed**: seed 를 기본 상태로 불러옴. 되돌리기·비드별 초기화·전체 초기화 = seed 로. [선택 저장] 전에는 미저장(배지 "자동 탐지 결과 — 수정 후 저장"). paicad 범위(ranges)는 가져오지 않음(범위 = SR 기본 범위) | 수동 경로와 같은 화면·같은 저장 |
| AD-D-5 | 자동 경로도 **전체 코어 점검**(SR-D-37 피처 왜곡 / 38 다른 비드 침범 / 33 범위 끝 뒤집힘 / 39 조합 / 40 극단 요소)을 `esl/morph/core.py` 로 — 메시 출처 무관(SR-D-44) | 저장된 선택은 수동과 같은 select 이므로 같은 판정 |
| AD-D-6 | **V-SR-28 예외 목록**: 판정(state)·기저 바이트가 같을 때 경고가 더해지는 것은 허용 — `SELECT_RANGE_COMBO`, `SELECT_W_RANGE_LIMIT`, `SELECT_BASE_REFIT`, `SELECT_SLOPE_ABOVE_PLATE`, `SELECT_QUALITY_WARN`(극단값), `SELECT_RANGE_INVERTS`. 사례: feat, edge_boss:G, 실 사례 1 전체 5(L), edge_boss B1_D1 7.0146, h5, 레일 A 단독. 시험 상수 = `tests/doe/test_bead_select_hard.py` `REGRESS_WARN_EXCEPTIONS_V0162`(6개 고정, `SELECT_BRIDGE_SKIPPED` 는 넣지 않음 — V-AD-5 가 따로 검사). `esl_select_relax.md` V-SR-28 회귀 문장도 이 목록을 따른다 | AD-D-9·SR-D-39 로 늘어난 경고가 회귀 실패로 잡히지 않게 |
| AD-D-7 | `select.hole.bridge_max_mm` = **20**. 등가 지름이 이보다 큰 구멍은 건너 잇지 않고 경고 `SELECT_BRIDGE_SKIPPED{eq_d_mm, gap_mm}`. 키를 `HASH_NEW_KEYS_V0162` 에 넣고(기본값이면 해시 제외) 모든 설정 거울(DEFAULTS·pydantic·yaml 2개·`GET /doe/settings`·브라우저)에 | 큰 개구를 건너 이으면 경계가 판을 가로지름 |
| AD-D-8 | `MORPH_EXTREME_ELEMENTS` 를 `result.json.warnings`·순위 ⚠·보고서에 노출 | 지금은 info 에만 있어 사용자가 못 봄 |
| AD-D-9 | `range_check` 는 `check_steps = 0` 이어도 일찍 끝나지 않는다. 조합 점검은 `combo_samples > 0` 으로만 결정 | 설정 하나로 다른 점검이 꺼지던 결함 |
| AD-D-10 | `U_EPS` 를 `esl/morph/core.py` 로 옮김(bead_select 는 재노출). 중복된 리터럴 기본값을 지우고 DEFAULTS 병합 cfg 를 씀 | 같은 값을 한 곳에서 |
| AD-D-11 | `ALGO` 2→**3**, `RULES` 2→**3**. 선택 sha·기저 바이트는 그대로(옛 기저는 SR-D-13c 규칙으로 1회 재계산 — 결과 동일) | AD-D-7·9 가 판정에 영향 |
| AD-D-12 | paicad 사면(flanks)은 **힌트만**: 유도 사면 대비 20 % 넘게 다르면 info `AUTO_SLOPE_DIFF`. 미리 채우지 않음 | paicad 는 1단 4면만 인식(BS 확정 1) |

## 2A. 결정 — ② B 메시 기준 select (사용자 선택 2026-11-08)

| ID | 결정 | 근거 |
|---|---|---|
| AD-D-13 | **② 새 스터디 = 시나리오 `select` + `inputs.select_base: "mesh"`**(① = `"case"`, 키가 없으면 `"case"`). ② 라디오 아래 같은 하위 라디오(자동 탐지/수동, AD-D-1). 새 스터디 목록에서 `mesh` 숨김. DB 는 `scenario = 'select'`, `base` NULL, `inputs.mesh` 있음 — 기존 CHECK 그대로 통과 | 확정 3, A11 |
| AD-D-14 | **② 입력 = 지금 ② 입력 그대로**: B 메시 `.rad`/`.inc` 업로드(purpose `doe_mesh`, include 는 업로드 폴더 안만 — BD-D-12·C2-D-3), 파트 제목(기본 설정 `part_title` "chassis rear", exact_ci), 인치(선택). `bead_source: auto` 면 B STEP(`step_upload_id`) **필수**(paicad extract·tag 입력), `manual` 이면 STEP 을 받지 않음(지정 시 422 `INVALID_PARAMS` — 현 select 규칙과 같음). ESL 검사 = ② 규칙(다른 모델 허용, `size.assert_ok(B = 템플릿)` → `SIZE_MISMATCH`), 같은 모델 검사는 하지 않음. `MeshCheckOut` 스키마 그대로. STEP→gmsh B 메시는 넣지 않음(§13 O-2) | ② 입력 보존 |
| AD-D-15 | **기준 메시·하중·지지 = 기존 함수 재사용(새 매핑 없음)**. BD_INPUT: `stages.py:189-207` ② 분기를 `_mesh_base(c)`(copy_mesh_upload → load_mesh → `sc.template_base` → `save_base`)로 뽑아 ② 와 `_sel_input`(select_base mesh)이 같이 호출. 노드 ID = **B 원 ID**(paicad fixed-scan·tag·받기 include 와 같은 ID). base.json `scenario = "select"`, `target = "S2"`, input.json `select_base: "mesh"`·`assem: "input/mesh"`·`mesh{main, files}`·`part_id`·`size`. BD_LOADS: `_sel_loads` 그대로 — `sc.entry_loads` 가 S2 이므로 `tg.entry_load` S2(= `mapping.to_target` + 평형 보정, BD-D-3 ②·SC-D-6 과 같은 함수). 지지 = `build_template` 의 `auto_supports`(BD-D-4 ② = SC-D-6 `design_target` 의 `auto_supports` 와 같은 함수). ④ `mesh_input` 의 1..N 재번호·`id_map` 은 쓰지 않음 — 재사용 단위는 **함수**(`nz.frame`·`align_normals`·`auto_supports`·`entry_load` S2)이고 ④ 단계(`_cmp_*`)가 아님. ② 는 B 자신이 기준이라 frame = `nz.frame(B, axis_ref = 기준 ESL axis_ref)` = ④ 에서 B 를 d000 로 둔 frame 과 같다(V-AD-9) | 사용자 요구 1(④ 매핑 재사용) |
| AD-D-16 | **구속·고정의 뜻을 나눔**. (a) 평가 구속 = ESL 자기평형 + 3-2-1 지지(BD 확정 3) — A 의 구속을 B 로 옮길 대상이 없고 B 자동 3-2-1(AD-D-15). (b) 모핑 고정 노드(체결) = **B 자신의 fixed-scan**(BD-D-12: assem = `input/mesh`, parts = B part_id) → `prep/fixed/` → `_sel_fixed_ids` 그대로. fixed-scan 실패·paicad 없음 → BS-D-8 `FIXED_INFO_MISSING`(준비 계속, `fixed_user` 수동 지정) — ② 의 준비 실패(`_paicad_fail`)가 아니라 select 규칙. B 에 tie·RBE2 가 없으면 고정 0 + `FIXED_INFO_MISSING`. A 체결점은 고정 노드에 넣지 않음(셀 매핑은 힘만 옮김 — §13 O-1) | 사용자 요구 1·6 |
| AD-D-17 | **BD_GEOM(worker `_geom_select`, select_base mesh)**: assem = `input/mesh`(assem_full 사본 없음 — ② 와 같음, `doe_assem_check` 상한 1e12 = ② 와 같음). plan = `[a_fixed](A Case 있으면, ② 그대로)` + `fixed` + (auto 만) `extract0 → extract → tag`. 실패 처리: a_fixed = ② 그대로(`A_FASTENERS_UNKNOWN`), fixed = `FIXED_INFO_MISSING`, extract0·extract·tag = `AUTO_DETECT_FAILED{step, code}`(AD-D-2). paicad 없음 + auto = `AUTO_DETECT_FAILED{step:"version"}` + `FIXED_INFO_MISSING`, 준비 READY. ① select(case) plan 은 `assem_full → fixed → (auto) extract0 → extract → tag` | ② plan(`doe_jobs.py:410-423`) 재사용 |
| AD-D-18 | **경계 경고 유지**: select_base mesh 도 ② `_boundary`(BD-D-14) 실행 → `prep/boundary.json`, `plan.json` 에 `result`. `stages.py:340` 조건 `c.scn == "mesh"` → `_is_mesh_base(c)`(scn = mesh 또는 select_base = mesh). 평면도 링크·경고 수 표시 그대로 | ② 평가와 같은 정보 |
| AD-D-19 | **평가 일관성(② 와 같음)**: 안 = select 기저 모핑 좌표(B 노드 ID·연결 불변), 하중 = `prep/loads.npz`(B 베이스라인 1회, 모든 안 재사용 — BD-D-3 ②), 지지 = `base.json.supports`(BD-D-4 ②), frame = B. d000 = B 원 메시 → legacy ② d000 와 mesh·loads·supports·해석 결과 **바이트 동일**(V-AD-11). 판정·품질 = select 규칙(SR-D-1·37~40, 공통 코어). 다른 점은 형상 변화 방식뿐(② = paicad run, select = 선형 기저) | 사용자 요구 2 |
| AD-D-20 | **받기·보고서**: `_sel_rad_files` = select_base mesh 면 `prep/input.json.mesh.files`(`input/mesh` 사본, rel = 업로드 상대경로) 중 B 파트 `/NODE` 를 가진 파일, 원본 = 사본(sha 확인). `export_mesh.write` 의 part_title = `inputs.part_title`(B). 보고서 머리 "기준 = B 메시(다른 모델 — 하중 셀 매핑, 지지 자동 3-2-1)" + 기존 select 절 | ① 전용 코드(A9) |
| AD-D-21 | **auto_selection on B**: `prep/tag/` 는 assem = `input/mesh` 로 돌아 B 원 노드 ID — AD-D-3 그대로. STEP 과 B 메시가 어긋나 tag 가 비면 `AUTO_BEAD_UNMAPPED`(비드별) 또는 `AUTO_DETECT_FAILED{step:"tag"}` | R-AD-6 |
| AD-D-22 | **이어하기·sha**: select(case) 스터디의 input.json·스냅샷·해시 불변 — `select_base` 키는 `"mesh"` 일 때만 쓴다. `design_sha` 식(BS-D-13: 값 + mesh_sha + loads sha + cfg 해시 + `select:<sel>:<basis>`) 그대로 — mesh_sha·loads sha 가 B 로 정해져 ① 와 섞이지 않음. `bead_source` 는 seed 출처일 뿐 해시에 넣지 않음(저장 선택 sha 가 같으면 같은 안) | V-AD-2·10 |
| AD-D-23 | **기존 `mesh` 스터디**: 그대로 실행(paicad run 경로 `stages.py:462-479`·`doe_jobs.py:825` 불변), 복제 = `mesh` 유지. API 는 `scenario: "mesh"`·`"same"` 생성을 계속 받음(스크립트 호환), 화면만 숨김 | 사용자 요구 4 |

## 3. 데이터 모델 · 설정 키 · API

### 3.1 저장 위치
- `bead_does.inputs`(JSONB): `bead_source: "auto"|"manual"`(select 만), `select_base: "mesh"`(② 만, ① 은 키 없음), ② 면 기존 ② 칸(`mesh{upload_id, file_name, sha256, rel}`, `part_title`, `inch`) + auto 면 `step{…}`.
- `bead_does.doe.bead_source` 거울(AD-D-1 표기). `DoeStudyOut.inputs.bead_source`·`inputs.select_base`.
- 준비 산출물: `prep/auto_detect.json`(AD-D-2), `prep/select/auto_selection.json`(AD-D-3), ② 면 `prep/boundary.json`(AD-D-18).

### 3.2 설정 키 (DEFAULTS = `BeadDoeSelectCfg` = `config/*.example.yaml` 2개 거울)
```yaml
bead_doe:
  select:
    hole: {bridge_max_mm: 20.0}      # AD-D-7, HASH_NEW_KEYS_V0162
    auto: {slope_diff_rel: 0.2}      # AD-D-12 정보 기준(보고만 — 해시 제외)
```
- `GET /doe/settings`: `select.hole.bridge_max_mm`, `scenarios.select_auto`(= select 가능 ∧ paicad 준비됨), `scenarios.select_mesh`(= select 가능 — 수동은 paicad 불필요).

### 3.3 API (`/esl/api`)
```
DoeCheckIn(select)  + bead_source?: "auto"|"manual" (기본 manual), select_base?: "case"|"mesh" (기본 case)
                      case: step_upload_id = auto 면 필수·manual 이면 금지, mesh_upload_id·part_title 금지
                      mesh: mesh_upload_id 필수, part_title?, inch?, step_upload_id = auto 면 필수·manual 이면 금지
DoeCheckOut(select, mesh) = ② 응답 그대로(mesh: MeshCheckOut, size, entries[ok = 크기 규칙], warnings)
DoeStudyIn(select)  = DoeCheckIn(select) + title?
DoeStudyOut.inputs  + bead_source, select_base?
GET /doe/studies/{id}/select/auto → {selection, sha256, map, warnings, paicad_version}
     404 AUTO_NOT_AVAILABLE (manual 이거나 auto_selection.json 없음), 409 PREP_NOT_READY
```

### 3.4 migration
- 불필요: scenario 값 추가 없음, 새 칸은 모두 `inputs`·`doe` JSONB. `ck_bead_does_base`(same 만 base 필수)·`ck_bead_does_selection`(select 만) 그대로 통과.

## 4. 알고리즘 — `esl/doe/bead_auto.py`

1. `extract_doc` 비드 목록(paicad 순서) → 비드 k 의 bottom face id 집합. `tag_npz` = 노드별 (kind, face_id) — FACE kind 만 사용.
2. 바닥 후보 = 요소의 모든 노드가 FACE-tag 이고 그 face 가 모두 비드 k 의 bottom 인 요소. 0 개 → `AUTO_BEAD_UNMAPPED{bead}`.
3. 섬 제외 = `features.enclosed_components(ix, cand, owner, X, n_ref, …)` 결과를 후보에서 뺌(SR-D-35 규칙 그대로).
4. 비드 i → `{"id": "b<i>", "tiers": [{"k": 1, "floor": <elem ids 정렬>}], "slope": "auto", "blend": "auto", "hold_fixed": 0}`. 묶음(group)은 풀고 `AUTO_GROUP_DROPPED`(info). `max_beads` 초과분은 버리고 `AUTO_TOO_MANY_BEADS{n, max}`.
5. 유도 사면(derive)과 paicad flank 폭 차 > `select.auto.slope_diff_rel` → `AUTO_SLOPE_DIFF{bead, rel}`(info).
6. `map` = `[{bead:"b<i>", paicad_id, n_floor}]`. `selection` 은 `bsel.normalize` 를 통과해야 함(sha 계산 = 수동과 같음).

## 5. ② select_base mesh 흐름 (BD 단계 그대로, 바뀐 곳만)

```
DOE_PREP
  1 BD_INPUT  (코어) _mesh_base: input/mesh 복사·sha → load_mesh(B 파트) → template_base(frame = B, 법선 정렬, auto 3-2-1, 크기 규칙)
              → prep/base_mesh.npz·base.json(scenario select, target S2)·input.json(select_base mesh)
  2 BD_MESH0  SKIPPED
  3 BD_GEOM   (worker) [a_fixed(A Case)] → fixed(B, assem = input/mesh) → (auto) extract0 → extract → tag → prep/auto_detect.json
  4 BD_LOADS  (코어 _sel_loads) entry_loads S2(셀 매핑) → loads.npz · _boundary → boundary.json · plan.json
              · 선택 보기(part.glb·select.bin — B 원 node_id) · (auto, tag 있음) auto_selection → prep/select/auto_selection.json
DOE_PREVIEW / DOE_RUN = select 그대로(_sel_prepare → basis → bd_eval: x = 기저 좌표, loads.npz·base supports 재사용)
```

## 6. 이어하기 · sha
- 선택 sha: 자동 seed 를 고치지 않고 저장해도 수동으로 같은 선택을 저장한 것과 같은 sha(V-AD-1).
- `HASH_NEW_KEYS_V0162 = ("hole.bridge_max_mm",)`: 기본값이면 `select_hash_view` 에서 빠짐 → v0.16.1 select 해시 불변. `select.auto.*` 는 보고만이라 항상 제외.
- ALGO 3: 옛 `basis.json.algo = 2` 는 BD_MATRIX 에서 1회 재계산, 기저 바이트 동일 기대(V-AD-8). RULES 3: 옛 미리보기는 SR §7.4 띠 표시.
- ② select: `design_sha` = BS-D-13 식(AD-D-22). legacy ② 해시 불변.

## 7. 화면 (2560×1440 기준, 1920×1080 잘림 없음)
- 새 스터디: 시나리오 라디오 ①(같은 모델)·②(다른 모델 + B 메시)·③·④, ①② 아래 하위 라디오 "자동 탐지 / 수동". `same`·`mesh` 항목 없음. ② 입력 칸 = 지금 ② 칸(B 메시·파트·인치) + auto 면 STEP 칸.
- 선택 카드: auto 면 seed 로드, 배지 "자동 탐지 결과 — 수정 후 저장", 되돌리기·초기화 = seed. `AUTO_DETECT_FAILED` 면 띠 문구 + 빈 선택으로 수동.
- ② select: 평면도 경계 경고 링크·경고 수(② 와 같음), 머리 칩 "기준 B 메시 · 셀 매핑".
- 순위 ⚠ 에 `MORPH_EXTREME_ELEMENTS`(AD-D-8).

## 8. 오류·경고 코드 (문구 원본 `resources/doe_messages.json`)

| 코드 | 수준 | 위치 |
|---|---|---|
| `AUTO_DETECT_FAILED{step, code}` | 경고 | 준비(AD-D-2·17) |
| `AUTO_TOO_MANY_BEADS{n, max}` | 경고 | auto_selection |
| `AUTO_GROUP_DROPPED` | info | auto_selection |
| `AUTO_BEAD_UNMAPPED{bead}` | 경고 | auto_selection |
| `AUTO_SLOPE_DIFF{bead, rel}` | info | auto_selection |
| `SELECT_BRIDGE_SKIPPED{eq_d_mm, gap_mm}` | 경고 | derive |
| `MORPH_EXTREME_ELEMENTS` | 경고 | result.json·순위·보고서 |
| `AUTO_NOT_AVAILABLE` | 404 | `GET …/select/auto` |
| `PREP_NOT_READY` | 409 | `GET …/select/auto` |

## 9. 시험 (V-AD-*)

| ID | 시험 | 위치 |
|---|---|---|
| V-AD-1 | seed 결정성·등가: 같은 입력 2회 → `auto_selection.json` 바이트 동일, seed 를 그대로 저장한 sha = 같은 선택 수동 저장 sha | `tests/doe/test_bead_auto.py` |
| V-AD-2 | E2E: seed 편집 후 저장한 auto 스터디 = 같은 선택의 수동 스터디 — 결과·순위·보고서 바이트 동일(타임스탬프 제외) | `worker/tests/test_doe_select_e2e.py` |
| V-AD-3 | 자동 경로 코어 점검: SR-D-37/38/33/39/40 이 auto seed 선택에서도 같은 코드·상태 | `tests/doe/test_bead_auto.py` |
| V-AD-4 | paicad 없음/실패: 준비 READY + `AUTO_DETECT_FAILED{step}` + 빈 seed, 수동 저장·실행 가능 | `worker/tests/test_doe_select_jobs.py` |
| V-AD-5 | 건너 잇기 상한: 등가 지름 > 20 구멍 → `SELECT_BRIDGE_SKIPPED`, ≤ 20 은 v0.16.1 바이트 동일 | `tests/doe/test_bead_select_hard.py` |
| V-AD-6 | `check_steps = 0` 이어도 `combo_samples > 0` 이면 조합 점검 실행 | `tests/doe/test_bead_select_relax.py` |
| V-AD-7 | legacy `same` 경고(극단 요소 등)가 result.json·순위·보고서에 보임 | `tests/doe/test_report_doe.py`, `worker/tests/test_doe_e2e.py` |
| V-AD-8 | ALGO 3 재계산: 옛 algo 2 기저 → 1회 재계산, 선택 sha·basis 바이트 동일, AD-D-6 예외 외 regress 불변 | `tests/doe/test_bead_select_morph.py` |
| V-AD-9 | **매핑 재사용 = ④**: 합성 B 메시로 select(mesh) BD_INPUT+BD_LOADS 의 `base.json.frame`·supports·`loads.npz` 가 (a) 같은 B 의 legacy ② `bd_input`+`bd_loads` 와 바이트 동일, (b) ④ `compare_target(B, frame_B)` + `entry_loads`(B 를 메시 입력 d000 으로 읽고 `id_map` 으로 원 ID 환원)와 F 차 ≤ 1e-12·지지 좌표 동일·frame dict 동일 | `tests/doe/test_mesh_scn.py` |
| V-AD-10 | ② E2E(가짜 paicad extract·tag on B, 실 솔버): auto seed → 편집 → 저장 → 미리보기 → 실행 = 같은 선택의 수동 select(mesh) 스터디와 바이트 동일(타임스탬프 제외) | `worker/tests/test_doe_select_e2e.py` |
| V-AD-11 | ② 평가 일관성: select(mesh) d000 의 per_esl C·umax·epsmax = legacy ② d000 바이트 동일, 모든 안 loads sha·supports 같음 | `worker/tests/test_doe_select_e2e.py` |
| V-AD-12 | ② 고정: B tie/RBE2 있음 → `prep/fixed` 사용·hold_fixed 동작, fixed-scan 실패·paicad 없음 → `FIXED_INFO_MISSING` + 준비 READY + `fixed_user` 지정 가능, A 체결점은 고정 노드에 없음(O-1 고정) | `worker/tests/test_doe_select_jobs.py`, `tests/doe/test_bead_auto.py` |
| V-AD-13 | ② 입력 검사: mesh_upload_id 없음 422, auto + STEP 없음 422, manual + STEP 422, 다른 인치 `SIZE_MISMATCH`, include 업로드 밖 `PATH_OUTSIDE_ROOT`, 파트 없음 `MESH_INVALID`, 같은 모델 검사 안 함 | `backend/tests/test_doe_select_api.py` |
| V-AD-14 | legacy 회귀: v0.16.1 `mesh`·`same` 스터디 prep·run·result·보고서 바이트 동일, 복제 = 원 시나리오, 화면 새 목록에 `same`·`mesh` 없음 | `worker/tests/test_doe_e2e.py`, `frontend/src/__tests__/doe_select.test.tsx` |
| V-AD-15 | ② 받기·경계: best include = `input/mesh` 사본 기준 `/NODE` 만 바뀜, ch_r.rad part_title = B 파트, `boundary.json` = 같은 입력 legacy ② 와 바이트 동일 | `tests/doe/test_select_rad_files.py`, `tests/doe/test_boundary.py` |

## 10. 파일 소유권 (겹침 없음)

| 담당 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Core** (`esl/**`, `tests/doe`, `resources`) | 신규 `esl/doe/bead_auto.py`; `esl/doe/bead_select.py`(U_EPS 재노출, ALGO/RULES 3, `bridge_max_mm`·`SELECT_BRIDGE_SKIPPED`, `HASH_NEW_KEYS_V0162`, `range_check` AD-D-9); `esl/morph/core.py`(U_EPS, `bridge_holes` 상한, DEFAULTS 병합 cfg); `esl/mesh/features.py`(필요 시 호출 인자만); `esl/doe/stages.py`(`_mesh_base`·`_is_mesh_base`, `_sel_input` mesh 분기, `_sel_loads` auto_selection·boundary, `_boundary` 조건, `_sel_rad_files`·`_sel_best` B 경로·part_title, `MORPH_EXTREME_ELEMENTS` → result.json warnings·순위 ⚠); `esl/doe/paicad_io.py`(tag 읽기); `esl/doe/report_doe.py`; `esl/doe/__init__.py`(DEFAULTS); `resources/doe_messages.json`; `tests/doe/*`(신규 `test_bead_auto.py`, synth 확장) | V-AD-1, 3, 5~9, 15 |
| **Impl-Backend** (`backend/**`, `worker/**`, `config/*.yaml`) | `backend/esl_platform/core/config.py`(select.hole·auto, scenarios 거울), `api/schemas.py`(bead_source·select_base·`DoeStudyOut.inputs`·auto 응답), `api/services/doe.py`(check-inputs·studies 분기, settings), `api/services/doe_select.py`(seed 읽기·auto 응답), `api/routers/doe.py`(`GET …/select/auto`), `worker/esl_worker/doe_jobs.py`(`_geom_select` case/mesh plan·`prep/auto_detect.json`), `worker/esl_worker/register.py`(준비 요약 auto·select_base), `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`, `backend/tests/*`, `worker/tests/*` | V-AD-2, 4, 10~14(API·워커) |
| **Impl-Frontend** (`frontend/**`) | `src/components/DoeInputs.tsx`(하위 라디오·② 칸·same/mesh 숨김), `src/pages/doe/DoeStudy.tsx`, `src/components/BeadSelectCard.tsx`·`BeadList.tsx`(seed 배지·초기화), `src/view3d/select/layers.ts`(seed 기준 상태·`fromSelectionIn`), `src/components/DoeRanking.tsx`(⚠), `src/api/types.ts`·`src/api/doe.ts`(`getSelectAuto`), `src/mock/doedata.ts`·`src/mock/server.ts`, `src/__tests__/*` | V-AD-14(화면) |

- 순서: Core(`bead_auto`·`_mesh_base` 시그니처 먼저) ∥ Backend(스키마·`auto_detect.json` 형식은 §2·§3 고정) ∥ Frontend(mock) → 통합 E2E(V-AD-2·10·11).
- 공동 수정 금지: `stages.py`·`bead_select.py` = Core 단독, `schemas.py` = Backend 단독, `types.ts` = Frontend(Backend 스키마 거울).

## 11. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-AD-1 | tag 허용오차로 바닥 노드 누락·과다 | "모든 노드 FACE" 규칙 + `AUTO_BEAD_UNMAPPED`, seed 는 고칠 수 있음 |
| R-AD-2 | paicad seed 가 다단 비드를 1단으로 잡음 | 1단/비드 고정, 사용자가 단 추가(SR-D-36 경고가 신호) |
| R-AD-3 | 준비 시간 증가(extract·tag) | auto 일 때만 실행, 실패해도 READY |
| R-AD-4 | ALGO 3 재계산 비용 | 1회만, 기저 바이트 동일 확인(V-AD-8) |
| R-AD-5 | 초기화 의미 혼동(seed vs 빈 선택) | 배지·버튼 툴팁 "자동 탐지 결과로" |
| R-AD-6 | B STEP 과 B 메시의 위치·좌표계 어긋남 → tag 매핑 실패 | `AUTO_BEAD_UNMAPPED`/`AUTO_DETECT_FAILED{step:"tag"}`, 수동 계속 |
| R-AD-7 | B 에 체결(tie·RBE2) 없음 → 고정 정보 없음 | `FIXED_INFO_MISSING` + `fixed_user`, §13 O-1 |
| R-AD-8 | 셀 매핑 하중은 ① 직접 하중과 절대값이 다름 | ② 와 같은 성질, `MAPPING_RESOLUTION` 경고 유지, 보고서 머리 표기 |
| R-AD-9 | 큰 B 메시의 선택 보기(glb·select.bin)·derive 시간 | 기존 상한(`max_selection_kb`·`derive_timeout_s`·업로드 상한) 그대로 |
| R-AD-10 | legacy ② 와 select(mesh) 결과를 직접 비교(변수 정의가 다름: paicad 변수 vs D/W) | 보고서에 기준·변수 출처 표기, 비교 기능 없음 |

## 12. 버전
- VERSION 0.16.2, 버전 칩 = VERSION(SR-D-43). migration 없음.

## 13. 열린 항목 (해법을 만들지 않음 — 사용자 결정 필요)

| ID | 항목 | 현재 사실 | 이번 동작 |
|---|---|---|---|
| O-1 | **A 체결점(고정)을 B 고정 노드로 옮기기** | ②·④ 하중 매핑(`mapping.to_target`)은 셀 합력·합모멘트만 옮기고 구속·고정을 옮기지 않음. ④ 에는 모핑 고정 개념이 없음(`auto_supports` 만). `boundary.py` 는 A 체결점을 (a,b) 로 투영해 **경고만** 냄 | B 자신의 fixed-scan 만 사용(AD-D-16), 없으면 `FIXED_INFO_MISSING` + 수동 `fixed_user` |
| O-2 | **STEP → gmsh B 메시 기준 select** | ② 는 rad/inc 만 받음, gmsh 메시는 ③ 경로이고 체결(tie·RBE2)이 없어 fixed-scan·tag(assem rad 필요)를 쓸 수 없음 | 범위 밖(② 입력 = rad/inc 만) |

## 14. 수용된 구현 편차 (2026-11-08, v0.16.2 통합)

계약 문장과 구현이 다르지만 근거가 있어 **수용**한 항목. 이 표가 해당 계약 문장보다 우선한다.

| ID | 계약 문장 | 구현(수용) | 근거 |
|---|---|---|---|
| AD-X-1 | §4 2 / AD-D-3: 바닥 후보 = 요소의 **모든** 노드가 비드 k bottom 에 FACE-tag | 바닥 = (모든 노드 FACE-bottom 인 요소) ∪ (노드가 FACE-bottom 또는 EDGE·VERTEX-tag 이고, FACE-bottom 노드가 **1개 이상**이며, 요소 법선이 앞 집합 평균 법선과 `select.feature_angle_deg` 안에서 평행한 요소). 다른 면에 FACE-tag 된 노드가 하나라도 있으면 제외 | paicad tag 는 B-rep 모서리·꼭짓점 위 노드를 EDGE·VERTEX 로 분류 — CAD 를 따르는 메시는 바닥 가장자리 요소 줄이 "모든 노드 FACE" 에서 빠져 바닥이 한 줄 안쪽에서 멈춤(`esl/doe/bead_auto.py` 머리 주석) |
| AD-X-2 | V-AD-2·10: auto 스터디 보고서 = 같은 선택 수동 스터디 보고서 바이트 동일(타임스탬프 제외) | 보고서 **입력 CAD 행**은 auto 쪽에 "자동 탐지 초기 선택 입력" STEP 이름이 있어 다름 — 비교에서 id·생성 시각과 함께 이 행을 뺌. 결과·순위·ESL별 지표는 바이트 동일 | 입력 출처 표기일 뿐 결과가 아님(`worker/tests/test_doe_select_e2e.py` `_report`) |
| AD-X-3 | V-AD-13: ② include 업로드 밖 = `PATH_OUTSIDE_ROOT` | ② select 검사 = `MESH_INVALID`(템플릿 메시 검사가 거부) | AD-D-14 "② 입력 그대로" — legacy ② 와 같은 판정(`backend/tests/test_doe_select_api.py`) |
| AD-X-4 | AD-D-2·17: fixed-scan 실패 = `FIXED_INFO_MISSING`(별도 경고) | auto 스터디에서 fixed-scan 실패로 tag 를 못 하면 `AUTO_DETECT_FAILED{step:"tag", detail:"FIXED_INFO_MISSING"}`(준비 READY·빈 seed·수동 `fixed_user` 그대로). 경고 모양 = `{code, message, step, detail}` — `detail` = 안쪽 paicad·코어 코드(경고 자신의 code 와 겹치지 않게), 화면은 `detail` 을 읽음 | tag 단계가 fixed-scan 결과(조립·파트 해석)에 의존 — 실패 단계를 tag 로, 원인을 detail 로 한 경고에 모음(`worker/esl_worker/register.py` `_select_auto_prep`) |

- AD-D-18 화면(평면도 링크): ② select 의 `GET …/plan-view` 는 `prep/plan.json` 위에 코어 `plan_data` 를 덮어써 `links`·`a_points`·`load_points` = `[]`, `fixed` = `{a, b}`(label 없음)로 나간다 — 링크 좌표가 API 에 없어 v0.16.2 평면도(SelectPlan)는 **경고 수만** 표시(준비 요약 "경계 경고 n", 결과 카드). 링크 선 그리기는 API 가 링크를 넘길 때(다음 판).

