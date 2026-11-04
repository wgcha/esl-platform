# 계약: 강성 평가 스터디 시나리오 ④ 형상 직접 비교 (STEP_COMPARE, v0.14.0)

- 상태: **확정** (2026-11-04, 사용자 확정 기능 + 결정 SC-D-1·SC-D-2 권장안 확정). 미결 없음.
- 버전: **v0.14.0** (main 2191318 = v0.12.5 기준, 구현은 v0.13.0 일괄 실행 `impl/run-all-be` 위). migration **필요**(§9 — `0014_step_compare`).
- 관계: `esl_bead_doe.md`(BEAD_DOE, 시나리오 ①②③)의 **확장**. ③ `step` 의 gmsh 메싱(`esl/doe/mesh_gmsh.py`)·셀 매핑(`mapping.to_target`, frame 고정)·지지(`target.auto_supports`)·크기 규칙(`esl.opt.size.assert_ok`)·해석(`esl/doe/evaluate.py`)·순위·ESL별 지표(§11·§11.4)·작업 구조(`DOE_PREP`·`DOE_RUN`, BD_* step)·폴더 규칙(`_doe/<id>/`)·보안 규칙(§15)을 **그대로 재사용**한다. 이 문서에 없는 규칙은 BEAD_DOE 를 따른다. 충돌 시 ④ 범위에서 이 문서가 우선.
- ID 규칙: 결정 `SC-D-n`, 요구 `SC-n`, 시험 `V-SC-n`, 리스크 `R-SC-n`.

### 사용자 확정 (2026-11-04, 변경 금지)
1. 시나리오 ④ **형상 직접 비교**: 사용자가 STEP 여러 개를 올리고(각 이름, 그중 하나를 **기준**으로 지정), 라이브러리에서 고른 ESL(여러 씬)로 형상마다 선형 해석해 기준 대비 컴플라이언스를 비교한다.
2. **없는 것**: 비드 인식·모핑·DOE 안 생성·미리보기·paicad 사용.
3. **메싱** = 모든 STEP 동일 gmsh 설정, 낙하 메시 기준: 평균 요소 3 mm, 곡률 세분화 끔(`curvature_n` 0), 최소 크기 ≈ 목표 × 0.8, 작은 형상 무시(1차는 gmsh 설정만 — defeature 는 별도 후속). 영역별 성기게는 보류.
4. **하중** = 기준 STEP 메시 frame(셀 경계)을 고정한 채 형상마다 셀 매핑(`esl/library/mapping.to_target`, ③ BD-D-3 과 같은 규칙). **지지** = 형상마다 같은 정규화 규칙 `auto_supports`(③ BD-D-4).
5. 기준 STEP 미지정 → 기준 = 선택 ESL 의 Case 메시 + 경고(메싱 방식 차이).
6. **결과** = 기존 강성 평가 스터디 결과 화면 재사용(순위·개선율·ESL별 개선율·3D 비교). 민감도는 변수가 없으니 숨김, 대신 형상 이름 표.

## 0. 현황 (main 2191318, v0.12.5)

| 항목 | 위치 | 현재 | ④ 에서 |
|---|---|---|---|
| 시나리오 | `bead_does.scenario` String(4), CHECK `('same','mesh','step')`, `DoeScenarioLit` | 3종 | `compare`(7자) → 열 넓힘 + CHECK 교체(§9) |
| 활성 판정 | `api/services/doe.py settings()·require_enabled` | 전역 enabled = paicad 준비, `step` = + gmsh | `compare` = bead_doe.enabled ∧ compare.enabled ∧ gmsh — **paicad 무관**(SC-D-3) |
| gmsh 메싱 | `esl/doe/mesh_gmsh.py gmsh_options·run_isolated`(spawn 격리) | `bead_doe.mesh` 1벌 | `bead_doe.compare.mesh` 프로필 덮어쓰기(§4) |
| frame 고정 대상 | `esl/doe/scenario.py design_target(mesh, base_frame)` | ③ 안 메시 | 형상마다 그대로 |
| 작업 | `core/job_types.py` DOE_PREP·DOE_PREVIEW·DOE_RUN | stage 11 | **새 작업 종류 없음**, step 내부 분기만(§5) |
| 검증 낙하 | `api/services/verify*.py` | `same` 외 422 `VD_SCENARIO_UNSUPPORTED` | 그대로(④ 미지원) |
| migration HEAD | `migrations/versions/0013_run_all.py`(v0.13.0) | 0013 | **0014**(§9) |

## 1. 범위 / 비범위

| 범위 (v0.14.0) | 비범위 (후속) |
|---|---|
| STEP N개(≤ `compare.max_shapes`) 업로드·이름·기준 지정 | defeature 중 필렛 제거·비드 억제(작은 구멍 메움만 있음 — SC-D-13 `defeature`) |
| 동일 gmsh 프로필 메싱(형상별 병렬) | 영역별 성긴 메시(체결부 밀·그 밖 성김) |
| 기준 frame 고정 셀 매핑·형상별 auto_supports | 형상별 물성(t·E·ν 다르게) |
| 순위·개선율·ESL별 개선율·3D 비교·보고서·CSV | 민감도·DOE·미리보기, 검증 낙하(VD) |
| 기준 미지정 시 Case 메시 기준 + 경고 | 경계 매핑 경고(②③ §8.2) — ④ 는 계산 안 함 |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| SC-D-1 | **흐름 = [입력 준비] → [비교 실행] 2단계**(기존 phase·주 버튼 규칙). `compare` 는 `PREP → READY → RUN → DONE`; PREVIEW 단계 없음. `POST …/run` 은 `matrix_sha256` 없이 허용(④ 만), `…/matrix`·`…/preview` = 409 `SCENARIO_UNSUPPORTED`. **(결정 필요 1 — 권장안 확정)** 준비에서 모든 형상을 메시·크기 검사까지 끝내 실패 형상을 실행 전에 보여 준다 | 새 작업 종류·자동 연쇄 없이 기존 화면 단계 재사용, 메시 실패를 해석 전에 확인 |
| SC-D-2 | **기준 미지정**: 기준 = 첫 선택 ESL(`entry_ids[0]`)의 Case Ch/R 메시(① `same_base` 와 같은 읽기, 제자리 읽기만). 이 메시도 STEP 형상과 **같은 규칙**(frame = 그 메시 `normalize.frame`, 하중 = 셀 매핑 — 직접 노드 하중 아님, 지지 = `auto_supports` — ESL 3-2-1 아님)으로 평가. 경고 `COMPARE_REF_CASE_MESH`(준비·결과 머리·보고서: "기준이 낙하 메시(다른 메싱 방식)라 개선율에 메시 차이가 섞입니다"). **(결정 필요 2 — 권장안 확정)** | 모든 형상에 같은 하중·지지 규칙이어야 차이가 형상(+메시) 차이만 남음. Case 메시 = 기준 frame 출처 |
| SC-D-3 | 활성: `scenarios.compare = enabled_flag ∧ bead_doe.compare.enabled ∧ gmsh.ready`. paicad 없음·버전 낮음은 ④ 를 막지 않는다(`require_enabled(ctx, "compare")` 는 paicad 사유 무시). 비활성 사유 = `DOE_DISABLED`·`COMPARE_DISABLED`·`GMSH_UNAVAILABLE` | 확정 2(paicad 미사용) |
| SC-D-4 | **형상 id**: 기준 = `d000`, 나머지 = 요청 순서대로 `d001…`(기존 `design_id`·폴더·view3d·per-esl API 가 그대로 동작). 결과 행에 `shape{name, file}` 추가 | 결과 화면·파일 API 재사용 |
| SC-D-5 | **메시 프로필**(확정 3): `bead_doe.compare.mesh` = `bead_doe.mesh` 를 키별 덮어씀 — `size_mm 3.0`(h 고정, `auto` 아님), `curvature_n 0`, `min_size_factor 0.8`, `extend_from_boundary 0`(작은 모서리가 주변 크기를 끌어내리지 않게), `occ_fix_small 1`(gmsh `Geometry.OCCFixDegenerated·OCCFixSmallEdges·OCCFixSmallFaces` = 1 — 가져올 때 작은 모서리·면 정리). `mesh_gmsh.gmsh_options` 에 두 키를 **선택 키**로 추가(없으면 지금 값: ExtendFromBoundary 1·OCCFix* 기본) → ③ 결과 바이트 불변(V-SC-8). 화면에 크기 칸 없음 | 모든 STEP 동일 설정, 하드코딩 금지 |
| SC-D-6 | **하중·지지**(확정 4): 기준 메시에서 `normalize.frame(ref_mesh, axis_ref = 기준 ESL axis_ref)` 1회 → `prep/base.json.frame`. 형상마다 `scenario.design_target(mesh_d, ref_frame)`(지지 = 형상 메시 `auto_supports`, rank < 6 → `FAILED_SOLVE` `SUPPORT_DEGENERATE`) → `entry_loads`(S2 = `mapping.to_target` + 평형 보정). 기준 d000 도 같은 함수 | ③ BD-D-3·4 와 같은 코드 경로 |
| SC-D-7 | **크기·정렬 검사**: (a) 기준 vs ESL = `size.assert_ok(rows, opt_run.size, template = ref frame {L_xi, L_eta, inch})` → 실패 = 준비 실패 `SIZE_MISMATCH`. (b) 형상 d vs 기준: 형상 자신의 frame 으로 같은 `assert_ok(template = 형상 frame)` + 정렬(형상 frame 원점의 기준 frame (ξ,η) 차 ≤ `compare.align_tol`(0.05)·법선 각 ≤ `compare.align_deg`(5°)) → 실패 형상만 `FAILED_SIZE`(`SHAPE_SIZE_MISMATCH`·`SHAPE_MISALIGNED`), 나머지 진행 | 고정 frame 매핑은 같은 좌표계·같은 위치 STEP 이 전제 |
| SC-D-8 | **물성** = ③ 과 같음(§7.3: 기본 = 첫 ESL Ch/R 면적 가중 두께 중앙값·주 PID E·ν, 화면 3칸) — 모든 형상 같은 값 | 해석 필수 입력, ③ 칸 재사용 |
| SC-D-9 | **병렬**(확정 "기존 슬롯 규칙"): 준비의 형상 메싱·실행의 형상 해석 모두 작업 슬롯 1개 안에서 최대 `bead_doe.run.parallel`개 동시(BD-D-15 메모리 자동 축소 같음), 메시마다 spawn 자식(§7.1) | 기존 규칙 |
| SC-D-10 | **잡음**: ④ 는 paicad 가 없어 BREP 왕복 잡음 바닥(§7.2)을 재지 않는다 → `noise_floor = null`, tol = `rank.ratio_tol`, 결과·보고서 한계 절에 "형상마다 새 메시 — 작은 차이는 메시 차이일 수 있음" | 확정 2 |
| SC-D-11 | **산출물**: 형상별 메시 `ch_r.rad`·`ch_r.fem`(③ BD-D-18 메시 부분, `export_mesh`)만 — 상위 `paicad.keep_files_top` 와 무관하게 전 형상(메시 npz 는 작음). BREP/STEP·values.json 없음(입력 STEP 은 이미 사용자에게 있음) | 확정 6 |
| SC-D-12 | 같은 sha256 STEP 이 2개 이상 → 경고 `SHAPE_DUPLICATE_FILE`(차단 아님) | 실수 알림 |
| SC-D-13 | **메싱 기준 = 이슈 #53 HyperMesh BatchMesher param·criteria**(원문 `docs/reference/radioss_chr_3mm_batchmesh.md`) 근사 (구현 시 추가): element_size 3 → `size_mm 3`; min length good 2.4 → `min_size_factor 0.8`(gmsh MeshSizeMin); max length good 3.75 는 **품질 판정에만**(gmsh 는 크기를 [Min, Max] 로 자른 뒤 MeshSizeFactor 를 곱하므로 Max 3.75 로 두면 요소가 3.75 mm 가 됨 — 목표 3 유지 위해 MeshSizeMax = 3); element_type 2(mixed) = RecombineAll(tria 허용); feature_angle 10° = 기록만(gmsh OCC 가져오기에 대응 옵션 없음); 곡률 끔. **holes table → `bead_doe.compare.defeature`**: 면 내부 경계 면적 < `min_hole_area_mm2`(50.27 = π·4² — r<4 원형·eq_diam<8·width<1.9 & length<14 슬롯 대부분) 메움 = 평면 면은 외곽·큰 구멍 고리로 다시 만들어 작은 구멍 wire 삭제(OCP `ShapeUpgrade_RemoveInternalWires` 와 같은 결과, gmsh API 만 — OCP 불필요), 곡면은 막는 면 fragment(경계 모서리 남음); r 4~30 구멍 둘레 분할 = max(`hole_elems` 6, ceil(둘레/h)) transfinite(washer 층 없음 — v0.14.0 통합 수정: 예전 min(6, …) 은 큰 구멍 모서리가 길어져 max_length Fail); 비드 억제(minimal_beads_height 2) = `min_bead_height_mm 2` **기록만(미구현)**. 실패 → 경고 `DEFEATURE_SKIPPED` 후 그대로 메싱. **criteria 2D 표 → `bead_doe.compare.quality`**(기준별 warn·fail: min/max length, aspect, warpage, skew, jacobian, quad·tria 각, trias %) → 형상별 품질 요약 `quality{fail_elems, fail_ratio, warn_elems, warn_ratio, tria_pct, over_limit}`, Fail 비율 > `max_fail_ratio`(0.01) → 경고 `SHAPE_QUALITY_FAIL`(**차단 안 함**). 판정 정의는 HyperMesh 근사(`esl/doe/mesh_quality.py` 머리말) | 사용자 제공 낙하 메시 기준(이슈 #53) |

## 3. 입력 API (`/esl/api`, 기존 오류 형식, 비GET `X-ESL-Request: 1`)

- 업로드 = 기존 청크 업로드(`purpose: doe_step`, `.step`·`.stp`, `ISO-10303-21;` 머리, 파일당 ≤ `step_max_mb`). **한 업로드 세션에 STEP 여러 개**(형상마다 `rel` 로 지정 — `upload.max_concurrent_per_user` 동시 세션 한도와 무관하게 20개) 또는 형상마다 세션 1개(rel 생략). 크기 검사 = 각 파일 `STEP_INVALID`(detail `index`) + 합계 ≤ `compare.total_max_mb`(1000) 아니면 422 `SHAPES_TOO_LARGE`.
- `DoeCheckIn`·`DoeStudyIn` 에 `scenario: "compare"` 와 필드 추가:

```text
CompareShapeIn { upload_id, rel?: str(업로드 안 STEP 파일 — 한 세션에 STEP 여러 개면 필수), name: str(1..64, 앞뒤 공백 제거, 제어문자 금지), reference: bool = false }
DoeCheckIn(compare) { project_id, scenario:"compare", entry_ids(1..max_entries), shapes:[CompareShapeIn](1..compare.max_shapes),
                      inch?: int }        # step_upload_id·mesh_upload_id·part_title 금지(422 INVALID_PARAMS)
DoeStudyIn(compare) = DoeCheckIn(compare) + { title?, props?:{t, E, nu} }      # mesh_size_mm 금지(설정 고정)
DoeCheckOut(compare) += { shapes:[{index, name, file_name, sha256, size_mb, reference}], reference_source:"step"|"case",
                          base?:{entry_id, case_id, part_title, n_nodes, n_elems} (reference_source = case), props_default, warnings[] }
DoeStudyOut.inputs(compare) = { shapes:[{id:"d000"…, name, file_name, sha256, upload_id, rel, reference}], reference_source, inch, props }
DoeStudyOut.prep(compare) += { n_shapes, n_ready, failed:[{id, status, code}], reference_source, mesh:{size_mm, gmsh_version},
                               shapes:[{id, name, file_name, reference, source, status(READY|FAILED_MESH|FAILED_SIZE), code, message,
                                        n_nodes, n_elems, quad_ratio, quality:{fail_elems, fail_ratio, warn_elems, warn_ratio, tria_pct,
                                        over_limit, max_fail_ratio}}] }      # 구현 시 추가(프런트 형상 표 배지·요소 수·품질)
```

- 검증(400·422, 순서대로): 형상 수 0 → `SHAPES_EMPTY`; > `max_shapes` → `SHAPES_TOO_MANY`; `reference: true` 2개 이상 → `REFERENCE_MULTIPLE`; 기준 STEP 이 있으면 형상 ≥ 2, 없으면 ≥ 1(아니면 `SHAPES_TOO_FEW`); 이름 규칙 → `SHAPE_NAME_INVALID`(index); 이름 대소문자 무시 중복 → `SHAPE_NAME_DUPLICATE`; 같은 upload_id 중복 → `INVALID_PARAMS`; 업로드 = 본인·READY(`UPLOAD_NOT_FOUND`·`UPLOAD_NOT_READY`); ESL = 프로젝트 활성 항목(`ENTRY_NOT_FOUND`); 기준 미지정이면 첫 ESL Case 입력 필요(409 `PREREQUISITE_MISSING`) + 경고 `COMPARE_REF_CASE_MESH`.
- 크기 비교(SC-D-7)는 메시 후라 check-inputs 에서는 `size: null`(③ 과 같음), 준비에서 확정.
- `GET /doe/settings` += `scenarios.compare`, `compare_reason`, `compare:{enabled, reason, max_shapes, total_max_mb, mesh_size_mm}`.
- `POST /doe/studies/{id}/run`(compare) = `{version, solver?}` — phase READY 아니면 409 `PREP_NOT_READY`, 실행됨 409 `ALREADY_RUN`. `matrix`·`preview`·`preview/thumb`·`params`·`plan-view`·`beads/*.png` = 409 `SCENARIO_UNSUPPORTED`. `clone` = 모든 형상 업로드가 남아 있어야(`PREREQUISITE_MISSING`, missing=[index…]).
- 이름은 DB·결과 JSON·보고서(HTML 이스케이프)에만 — argv·경로에 넣지 않는다(폴더는 id).

## 4. 설정 키 (`config/*.example.yaml`, 하드코딩 금지)

```yaml
bead_doe:
  compare:
    enabled: true
    max_shapes: 20             # 사용자 확정 기본 20
    total_max_mb: 1000
    align_tol: 0.05            # 형상 frame 원점 차(ξ,η) 허용
    align_deg: 5.0             # 법선 각 허용
    mesh:                      # bead_doe.mesh 를 키별 덮어씀(SC-D-5)
      size_mm: 3.0
      curvature_n: 0
      min_size_factor: 0.8
      extend_from_boundary: 0
      occ_fix_small: 1
      feature_angle: 10.0      # 기록만(SC-D-13)
      fallback: {enabled: true, algorithms: [6, 5, 1], relax: true, max_faces: 20,   # v0.14.1 실패 면만 2D 알고리즘 재시도 → 제약 해제(MESH_FACE_FALLBACK)
                 order: [algorithms, relax, split, fill, small],                     # v0.15.1 형상 폴백 순서(빼면 끔)
                 periodic_types: [Sphere], periodic_order: [split, fill, small, algorithms, relax],
                 split: {planes: 2},                                                 # bbox 중심 평면으로 그 면만 나눔
                 fill: {tol_factor: 0.5, points: 8, samples: 10},                    # 경계 고리 BSpline 채움, 편차 ≤ 0.5 h 만
                 small: {area_mm2: 50.27, tol_factor: 1.0, samples: 10}}             # 작은 면 경계만 채움
                 # mesh.json mesh_fallback.faces[]: id·failed_id·type·center·stage(algorithm|relax|split|fill|small)·stage_name·deviation_mm·new_ids·errors
    defeature: {enabled: true, min_hole_area_mm2: 50.27, hole_elems: 6, hole_r_mm: [4.0, 30.0], min_bead_height_mm: 2.0}   # SC-D-13
    quality:                   # SC-D-13 이슈 #53 criteria(warn·fail), Fail 비율 상한 → 경고만
      max_fail_ratio: 0.01
      min_length: {warn: 1.8, fail: 1.2}
      max_length: {warn: 4.5, fail: 5.25}
      aspect: {warn: 4.4, fail: 5.0}
      warpage: {warn: 13.0, fail: 15.0}
      skew: {warn: 34.0, fail: 40.0}
      jacobian: {warn: 0.7, fail: 0.6}
      quad_min_angle: {warn: 46.0, fail: 40.0}
      quad_max_angle: {warn: 134.0, fail: 140.0}
      tria_min_angle: {warn: 34.0, fail: 30.0}
      tria_max_angle: {warn: 112.0, fail: 120.0}
      tria_pct: {warn: 10.0, fail: 15.0}
```
- `BeadDoeCfg.compare`(pydantic): `max_shapes` 1..200, `size_mm` = `mesh.size_min_mm..size_max_mm`, `min_size_factor` (0,1], `curvature_n` ≥ 0, `extend_from_boundary`·`occ_fix_small` ∈ {0,1}. 섹션 없으면 기본값(enabled true).

## 5. 파이프라인 (③ step 재사용, paicad 단계 건너뜀)

```
POST /doe/studies(compare) → bead_does(scenario compare) + DOE_PREP
 DOE_PREP (<esl_root>/_doe/<id>/)
  1 BD_INPUT  STEP 들을 input/shapes/<did>.step 로 복사(sha256 재확인) → prep/shapes.json{did, name, file_name, sha256, reference}
              (기준 미지정: 첫 ESL Case rad parse_rad(제자리) → 기준 메시 = d000)
  2 BD_MESH0  compare 프로필로 형상마다 run_isolated(spawn, 병렬 SC-D-9) → prep/shapes/<did>/mesh/{mesh.npz, mesh.json}
              기준(d000) 메시·크기(SC-D-7a) 실패 → 작업 실패(MESH_FAILED·MESH_TOO_LARGE·SIZE_MISMATCH)
              그 밖 형상 실패 → 형상 상태 FAILED_MESH / FAILED_SIZE(진행)
  3 BD_GEOM   compare = SKIPPED(paicad 호출 없음 — version 점검도 안 함)
  4 BD_LOADS  기준 frame → prep/base.json(frame·d000 지지), 형상별 정렬 검사(SC-D-7b), 매핑 요약(셀당 노드 경고) → prep/compare.json
  5 BD_PREP_REGISTER  prep 요약 {n_shapes, n_ready, failed[{id, status, code}], reference_source, warnings}
POST /doe/studies/{id}/run → DOE_RUN
  1 BD_BASELINE d000 평가(=bd_eval, 메시는 prep 것 재사용) → run/designs/d000/
  2 BD_DESIGNS  READY 형상마다 bd_eval(LOCAL paicad 단계 없음, 메시 재사용 → design_target → 하중 → 해석) — 스레드 풀 run.parallel
  3 BD_POST     순위·ESL별 지표(§11·§11.4 그대로), 민감도 생략, 상위 view3d, 메시 산출물(SC-D-11), report.html
  4 BD_REGISTER 그대로
```
- 진행률 가중 = 기존 표(BD_GEOM 몫은 SKIPPED 로 바로 채움). 로그 예 `[d003 브래킷 B안] mesh 3.0 mm 41 s 182k 요소 · solve 12 ESL 9.2 s · score 0.93`(이름은 로그 표시만).
- 이어하기(BD-D-16): `done.json.input_sha256` = (STEP sha, 메시 프로필 해시, 기준 frame sha, 하중 sha, 물성, 설정 해시) — 같으면 재사용, `FAILED_*` 만 재실행.
- 형상 상태 = `READY` → `RUNNING` → `OK` | `FAILED_MESH` | `FAILED_SIZE` | `FAILED_SOLVE` | `CANCELED`(SKIPPED_* 없음). OK 0개(d000 제외) → SUCCEEDED + `NO_FEASIBLE_DESIGNS`. 기준 실패 → `BASELINE_FAILED`.
- 폴더: `_doe/<id>/{input/shapes/, prep/{shapes/<did>/mesh/, base.json, base_mesh.npz, compare.json}, run/designs/<did>/, post/, best/<did>/, report.html}`. 쓰기는 `_doe/<id>/` 만, Case·업로드 폴더 읽기만(BEAD_DOE §15).

## 6. 결과 스키마 차이 (`DoeResultOut`)

- `ranking[]` 의 `values` = `{}`, **추가** `shape:{name, file_name, reference:false}`. `baseline` += `shape:{name, file_name}`(Case 기준이면 `{name:"Case 메시", file_name:null, source:"case"}`).
- `sensitivity = null`, `sensitivity_reason = "COMPARE_NO_PARAMS"`. `noise_floor = null`(SC-D-10), `ranking[].noise = false`.
- `excluded[]` = 실패 형상 `{id, status, code, shape}`. `boundary_warnings_n = 0`.
- `scenario: "compare"`, `reference_source`. 나머지(score·improvement·worst_entry_id·umax·epsmax·per_esl·worst_ratio·pareto·sort) **불변**.
- `post/ranking.csv`: 변수 열 대신 `name`·`file_name` 열. `GET …/results/per-esl` 행에 `name`.
- 보고서: 시나리오 ④, 형상 표(id·이름·파일·sha256·요소 수·quad 비율·상태), 메시 프로필, 기준 출처(+ `COMPARE_REF_CASE_MESH`), 한계 절(+ 메시 차이·같은 좌표계 전제·작은 구멍 메움만 있음, 필렛 제거·비드 억제 없음).

## 7. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 필수만)

- 시나리오 라디오에 **④ 형상 직접 비교** 추가(`scenarios.compare` false → 비활성 + 사유 툴팁).
- ④ 입력 카드(필수만): ESL 목록(기존), **형상 표** = 끌어다 놓기(여러 파일, 청크 업로드 진행 막대) → 행마다 [기준 ◉ 라디오] [이름 입력(기본 = 파일 이름 확장자 제외)] [파일 이름·크기] [✕ 빼기]. 기준 라디오는 "기준 없음(Case 메시)" 선택지 1개를 맨 위에 둠 — 선택 시 경고 문구 1줄. 상한 도달 시 놓기 칸 비활성 "최대 20개". 물성 3칸(③ 재사용). 메시 크기 칸 없음(설정값 "요소 3 mm" 표시만).
- 주 버튼: [입력 준비] → (준비 후 형상 표에 메시 요소 수·상태 배지·실패 사유) → [비교 실행]. ②비드·③평면도·④미리보기 카드 숨김.
- 결과 카드 = 기존 `DoeRanking`·`DoePerEslTable`·3D 비교 재사용: 변수 열 자리에 **이름** 열(행 머리), 민감도 숨김, 3D 비교 왼쪽 라벨 "기준: <이름>", 받기 = [메시 rad/fem] [순위 CSV] [zip] [보고서].

## 8. 오류 코드 (신규)

| 코드 | HTTP/작업 | 의미 |
|---|---|---|
| `COMPARE_DISABLED` | 503 | `bead_doe.compare.enabled` false |
| 경고 `SHAPE_QUALITY_FAIL`·`DEFEATURE_SKIPPED` | 준비 | SC-D-13 (차단 아님) |
| `SHAPES_EMPTY`·`SHAPES_TOO_FEW`·`SHAPES_TOO_MANY`·`SHAPES_TOO_LARGE` | 422 | §3 개수·합계 크기 |
| `SHAPE_NAME_INVALID`·`SHAPE_NAME_DUPLICATE`·`REFERENCE_MULTIPLE` | 422 | §3 |
| `SCENARIO_UNSUPPORTED` | 409 | ④ 에서 matrix·preview·params·plan-view 등 |
| `SHAPE_SIZE_MISMATCH`·`SHAPE_MISALIGNED` | 형상 상태 `FAILED_SIZE` | SC-D-7b |
| 경고 `COMPARE_REF_CASE_MESH`·`SHAPE_DUPLICATE_FILE` | 응답·prep·결과 | SC-D-2·12 |
| 재사용 | | `STEP_INVALID`, `MESH_FAILED`, `MESH_TOO_LARGE`, `SIZE_MISMATCH`, `GMSH_UNAVAILABLE`, `ENTRY_NOT_FOUND`, `PREREQUISITE_MISSING`, `PREP_NOT_READY`, `ALREADY_RUN`, `BASELINE_FAILED`, `NO_FEASIBLE_DESIGNS`, `SUPPORT_DEGENERATE`, `UPLOAD_*`, `VERSION_CONFLICT`, `JOB_ACTIVE`, `VD_SCENARIO_UNSUPPORTED` |

- 사용자 문구 원본 = `resources/doe_messages.json`(신규 코드 추가).

## 9. DB · 버전

- **migration `0014_step_compare`**(`down_revision "0013"` = v0.13.0 `0013_run_all` — 구현 시점 HEAD 뒤, BD-D-21 규칙): `bead_does.scenario` `String(4)` → `String(8)`(ALTER TYPE, 데이터 불변), `ck_bead_does_scenario` DROP IF EXISTS 후 `IN ('same','mesh','step','compare')`. 그 밖 열·jobs CHECK 변경 없음(`inputs`·`prep`·`result` JSONB 에 담음). 멱등, downgrade 미지원, 이전 migration 은 고정 상수 유지(0004·0010 규칙). `tables.py DOE_SCENARIOS` 에 `compare`.
- 마이그레이션 판단 근거: 열 길이 4 에 `compare` 가 들어가지 않고 CHECK 가 막음 → 필수.
- `VERSION`·`CHANGELOG.md` 0.14.0.

## 10. 시험 (V-SC-*)

| ID | 시험 | 위치 |
|---|---|---|
| V-SC-1 | **합성 STEP 3개**(gmsh OCC 로 시험 중 생성: 400×300 평판 t 기준 / 같은 판 + 직선 비드 1 / 같은 판 + 비드 2) + 합성 자기평형 ESL 2개 → ④ E2E: 순위 = 비드 2 < 비드 1 < 기준(score 단조), 개선율·ESL별 ratio·pareto, `shape.name` 이 행에 | `worker/tests/test_doe_compare_e2e.py` |
| V-SC-12 | 해 잔차 판정(D-0.14-RESID): 합성 평판 400×300 · 3 mm · t 0.8 이 ‖r‖/‖F‖ > 1e-8 이어도 후방 오차 η < 1e-14 로 통과, η 허용을 조이면 SOLVER_SINGULAR, `_check_resid` 단위 시험(CG 는 예전 기준) | `tests/doe/test_step_compare.py`, `tests/mech/test_shell.py` |
| V-SC-11 | 이슈 #53: 작은 구멍(Ø2·Ø6) 메움·최소 모서리, 구멍 둘레 분할 max(6, ceil(둘레/h))(r 4.2·12·28, 둘레 요소 max_length Fail 0), 품질 기준(정사각형 0 Fail·찌그러진 요소 기준별 Fail·tria % ·상한 경고), 준비 결과 quality | `tests/doe/test_step_compare.py`, `worker/tests/test_doe_compare_e2e.py` |
| V-SC-2 | **frame 고정**: 모든 형상 `design_target.frame` == `prep/base.json.frame`(바이트 동일), 셀 경계 같음, 형상별 셀 합력·합모멘트 = ESL 셀 값 1e-9, 지지 = 형상별 auto_supports(정규화 위치 같은 규칙) | `tests/doe/test_step_compare.py` |
| V-SC-3 | **기준 미지정**: 첫 ESL Case 메시가 d000, 하중 = 셀 매핑(직접 노드 아님)·지지 auto_supports, 경고 `COMPARE_REF_CASE_MESH` 가 check-inputs·prep·결과·보고서에 | `tests/doe/test_step_compare.py`, `backend/tests/test_doe_compare_api.py` |
| V-SC-4 | 입력 API: 0·1(기준 있음)·max_shapes+1 개, 기준 2개, 이름 빈·64자 초과·제어문자·대소문자 중복, 같은 upload 2번, 합계 크기, ③ 전용 필드 거부, matrix/preview 409 `SCENARIO_UNSUPPORTED`, run 이 matrix_sha 없이 동작, paicad 비활성이어도 ④ 활성·gmsh 없으면 비활성 | `backend/tests/test_doe_compare_api.py` |
| V-SC-5 | 크기·정렬: 형상 L ±5 % 경계(4.9/5.1 %), 원점 이동 0.05 경계, 법선 5° 경계 → `FAILED_SIZE` 형상만 제외·나머지 진행, 기준 크기 불일치 → 준비 실패 | `tests/doe/test_step_compare.py` |
| V-SC-6 | 메시 프로필: compare 옵션이 gmsh 에 그대로(MeshSizeMax 3·Min 2.4·FromCurvature 0·ExtendFromBoundary 0·OCCFix* 1), 작은 구멍(Ø2) 평판에서 최소 모서리 ≥ 0.8h×(1−허용) 확인, 같은 STEP 2회 → mesh.npz 바이트 동일 | `tests/doe/test_mesh_gmsh.py`(gmsh 없으면 skip) |
| V-SC-7 | 작업: BD_GEOM SKIPPED·paicad 미호출(가짜 paicad 호출 0), 병렬 상한·메모리 축소, 형상 메시 실패 1개 → 나머지 OK, 기준 실패 → 작업 실패, 취소·이어하기(done.json 재사용), 업로드 폴더 불변 | `worker/tests/test_doe_compare_jobs.py` |
| V-SC-8 | 회귀: ③ `gmsh_options`(선택 키 없음) 결과 dict·메시 바이트 불변, ①②③ 기존 시험 통과 | 기존 `tests/doe/*`, `worker/tests/test_doe_*` |
| V-SC-9 | migration 0014: 빈·0013 DB, 멱등, 기존 행 보존, 'compare' 행 삽입, `tables.py` 일치, 단일 head, downgrade 거부 | `backend/tests/test_migrations.py` |
| V-SC-10 | UI: ④ 라디오(비활성 사유), 형상 표 추가·빼기·이름 편집·기준 라디오(+ 기준 없음 경고)·20개 상한, 준비 후 상태 배지, 비드·평면도·미리보기 카드 숨김, 결과 이름 열·민감도 숨김·3D 라벨, 2560×1440·1920×1080 잘림 없음 | `frontend/__tests__/doe_compare.test.tsx`, mock |

## 11. 파일 소유권

| 담당 | 파일(소유) | 완료 조건 |
|---|---|---|
| Impl-Backend | `migrations/versions/0014_step_compare.py`, `core/db/tables.py`(DOE_SCENARIOS·열 길이), `core/config.py`(`BeadDoeCompareCfg`), `api/schemas.py`(`DoeScenarioLit`·`CompareShapeIn`·응답 칸), `api/services/doe.py`(settings·require_enabled·check-inputs·studies·run·clone·409 분기), `api/services/uploads.py`(다중 doe_step), `resources/doe_messages.json`(신규 코드), `config/*.example.yaml`, `backend/tests/test_doe_compare_api.py`·`test_migrations.py` | V-SC-4, 9 |
| Impl-Worker(코어 포함) | `esl/doe/mesh_gmsh.py`(선택 키 2개), `esl/doe/scenario.py`(compare 기준·정렬 검사), `esl/doe/stages.py`(bd_input·bd_mesh0·bd_loads·bd_eval·bd_post compare 분기), `esl/doe/rank.py`(민감도 생략·이름), `esl/doe/report_doe.py`, `worker/esl_worker/doe_jobs.py`(BD_GEOM SKIPPED·형상 메시 병렬·BD_DESIGNS paicad 생략), `worker/esl_worker/register.py`, `tests/doe/test_step_compare.py`·`test_mesh_gmsh.py`, `worker/tests/test_doe_compare_*.py` | V-SC-1~3, 5~8 |
| Impl-Frontend | `frontend/src/api/types.ts`·`api/doe.ts`, `pages/doe/DoeStudy.tsx`(라디오·카드 표시 분기·주 버튼), `components/DoeInputs.tsx`(형상 표), `components/DoeRanking.tsx`·`DoePerEslTable.tsx`(이름 열·민감도 숨김), `mock/doedata.ts`, `__tests__/doe_compare.test.tsx`, `pages/guide/*` | V-SC-10 |
| Plan/Impl | `VERSION`·`CHANGELOG.md` 0.14.0, `docs/manual/user.md`(④ 사용법·한계) | – |

- 순서: Backend(스키마·migration·config) ∥ Worker(mesh_gmsh 선택 키 → stages) → Frontend(mock 병행) → E2E(V-SC-1).

## 12. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-SC-1 | 형상마다 다른 메시 → 작은 개선이 메시 차이에 묻힘(잡음 바닥 미측정) | 같은 프로필·곡률 끔·한계 절 명시(SC-D-10), 후속 defeature |
| R-SC-2 | STEP 좌표계·위치가 서로 달라 고정 frame 매핑이 틀어짐 | 정렬 검사 → `FAILED_SIZE`(SC-D-7b) |
| R-SC-3 | 기준 = Case 메시일 때 메싱 방식 차이가 개선율에 섞임 | 경고 `COMPARE_REF_CASE_MESH`(확정 5), 기준 STEP 지정 권장 문구 |
| R-SC-4 | 3 mm 메시 × 20 형상 메싱 시간·메모리 | 병렬 상한·메모리 축소(SC-D-9), `mesh.max_elems`·`timeout_s` 그대로 |
