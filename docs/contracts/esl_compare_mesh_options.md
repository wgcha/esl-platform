# 계약: 시나리오 ④ 형상 직접 비교 — 메시 성공률 향상 옵션 (COMPARE_MESH, v0.16.0)

- 상태: **확정** (2026-11-04 사용자, 20:33). 사용자 확정 방향(아래)과 §13 결정 Q1~Q3 을 반영했습니다. 세분화 폴백(확정 5, C2-D-18~25, §4A)을 포함합니다.
- 버전: **v0.16.0** (기준 main d01ab2f = v0.15.0). **착수 조건 = `fix/mesh-sphere`·`fix/winerror32` 가 main 에 병합된 뒤(v0.15.1)**. 같은 파일·블록(`mesh_gmsh.py`, `compare.mesh` 설정 블록, `stages._cmp_mesh*`, `atomic_replace`)을 고치기 때문입니다(§11). migration **불필요**(§6).
- 관계: `esl_step_compare.md`(④, SC-D-*)를 **확장**합니다. 업로드·검사·정렬/크기(SC-D-7)·기준 frame 고정 셀 매핑과 `auto_supports`(SC-D-6)·물성(SC-D-8)·병렬(SC-D-9)·품질(SC-D-13 `mesh_quality.summarize`)·순위·보고서는 그대로 재사용합니다. ② B 메시 읽기 규칙(`scenario.copy_mesh_upload`, purpose `doe_mesh`)과 rad 파서(`esl/rad/parser.py`)도 재사용합니다. 이 문서에 없는 규칙은 STEP_COMPARE 를 따르고, 충돌하면 이 문서가 우선합니다.
- 메시 기준: `docs/reference/radioss_chr_3mm_batchmesh.md`(목표 3 mm, min 2.4, quad 우선 mixed).
- ID 규칙: 결정 `C2-D-n`, 요구 `C2-n`, 시험 `V-C2-n`, 리스크 `R-C2-n`.

### 사용자 확정 (2026-11-04, 변경 금지)
1. ④ 가 최우선이다. 복잡한 Ch/R 중립면 STEP 을 gmsh 로 메시할 때 실패가 잦다.
2. **옵션 1 — 메시 입력**: 형상마다 STEP 대신 사용자가 만든 메시 파일(HyperMesh 등)을 올린다. gmsh 단계를 생략한다.
3. **옵션 2 — 삼각형 재메시**: CAD 면 구조를 버리고 OCC 삼각화(BRepMesh)를 만든 뒤 gmsh `classifySurfaces`(특징각) → `createGeometry` → 재메시(quad 우선, 목표 3 mm 유지)한다.
4. 모드는 `cad`(기존)·`remesh`·`auto` 셋이다. `auto` = CAD 메시가 실패하면 그 형상만 재메시. 특징각·삼각화 정밀도는 설정 키로 둔다.
5. (2026-11-04) 기본 규칙(3 mm, 약 20만 요소)으로 메시가 어려우면 요소를 더 잘게 짜서, 요소 수가 늘어나더라도 성공하게 한다(세분화 폴백).

## 0. 현황 (main d01ab2f v0.15.0 + 로컬 진행 중 브랜치)

| 항목 | 위치 | 현재 | v0.16.0 에서 |
|---|---|---|---|
| 형상 입력 | `api/schemas.py CompareShapeIn{upload_id, rel?, name, reference}` | STEP 만 | `source`·`part_id` 추가(§5) |
| 업로드 판정 | `api/services/uploads.py doe_source(kind step|mesh, rel?)` | mesh 는 주 파일 자동 선택, rel 지정 불가 | mesh 도 `rel` 로 주 파일 지정(다중 세션 규칙 동일) |
| BD_INPUT ④ | `esl/doe/stages.py _cmp_input` | STEP 복사·sha 재확인 | mesh 형상 = `copy_mesh_upload` 로 `input/shapes/<did>/` |
| BD_MESH0 ④ | `_cmp_mesh0` → `_cmp_mesh_one` → `mg.run_isolated`(spawn) | gmsh CAD + 면 폴백(v0.14.1/v0.15.1 split·fill·small) | 분기 함수 `_cmp_mesh_shape`(cad/remesh/auto/mesh_input) |
| 기준 Case 메시 | `scenario.case_ref_mesh`(parse_rad + 물성 덮어씀) | 있음 | 메시 입력이 같은 형식을 따름 |
| rad 파서 | `esl/rad/parser.parse_rad(path, part_title, …)` | title 로 고름, 물성·두께 필수 | `parse_rad_part(path, part_id, need_props=False)` **추가만** |
| 품질 | `esl/doe/mesh_quality.summarize` | ④ STEP | 모든 방식에 같은 함수 |
| 진행 중 | `fix/mesh-sphere`(로컬 worktree, 커밋 전) | mesh_gmsh 형상 폴백, `compare.mesh.fallback.{order,split,fill,small}` | 건드리지 않음. CAD 단계 안 폴백으로 그대로 둠 |
| 진행 중 | `fix/winerror32`(로컬, 커밋 전) | `os.replace` → `atomic_replace` | 새 코드는 `esl.fsutil.atomic_replace` 사용 |
| migration HEAD | `0015_bead_select` | – | 변경 없음 |

## 1. 범위 / 비범위

| 범위 (v0.16.0) | 비범위 |
|---|---|
| 형상별 `source: step|mesh`, 한 비교 안 혼합 | Nastran `.bdf`/`.fem`(Q2), Abaqus `.inp` |
| Radioss `.rad`/`.inc` + 업로드 안 include, 파트 ID 지정, SH4N/SH3N | 메시 입력 구멍 메움·재메시·기하 정리 |
| 재메시 `remesh`, `auto` 폴백(형상 단위) | 재메시 후 메시 단계 구멍 메움, 구멍 둘레 분할(transfinite) |
| 재메시 충실도(Hausdorff 근사) 경고·실패 | 영역별 크기, 필렛 제거·비드 억제 |
| 결과·보고서에 메시 방식·충실도 | ③ `step` 시나리오 적용(③ 는 바이트 불변) |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| C2-D-1 | **형상 출처** `source ∈ {step, mesh}`(기본 step). 기준 Case 메시는 기존대로 `source: case`. **한 비교 안 STEP·메시 혼합 허용**(Q1 권장). 방식이 둘 이상 섞이면(`mesh_method` 다름, case 포함) 경고 `COMPARE_MESH_METHOD_MIXED` "형상마다 메시 방식이 달라 개선율에 메시 차이가 섞입니다" | 기준만 HyperMesh 메시이고 나머지는 STEP 인 실제 흐름을 지원 |
| C2-D-2 | **메시 입력 형식** = `bead_doe.compare.mesh_input.formats` 기본 `[".rad", ".inc"]`. 주 파일 = 요청 `rel`(필수: 세션에 rad/inc 가 둘 이상일 때). 생략하면 `doe_source(kind mesh)` 규칙(`*_0000.rad` → `.rad` 1개 → `.inc` 1개). `.bdf/.fem` 은 422 `MESH_FORMAT_UNSUPPORTED`(Q2) | 기존 rad 파서 재사용, ② 와 같은 규칙 |
| C2-D-3 | **include**: 따라 읽음(`mesh_input.include: true`, 깊이 = `max_include_depth` 8). **업로드 폴더 안만** 허용(`copy_mesh_upload` = `scan_include_refs(follow=within root)`). 밖이면 `PATH_OUTSIDE_ROOT`, 못 찾으면 `MESH_INPUT_INVALID`, 링크면 `PATH_OUTSIDE_ROOT`. 복사본 sha256 재확인. `include_path_map` 은 쓰지 않음. 원본 업로드·SPDM·Case 폴더에는 쓰지 않음 | 기존 보안 규칙(BEAD_DOE §15) |
| C2-D-4 | **파트 선택** = `part_id`(int). 대상 파일에 쉘 파트가 하나면 생략 가능, 둘 이상이면 422 `MESH_INPUT_PART_REQUIRED`(check-inputs 가 `parts[]` 를 돌려줌). 없는 ID → `MESH_INPUT_PART_NOT_FOUND`. 파트 안 쉘이 아닌 요소 → `MESH_INPUT_UNSUPPORTED_ELEMENT`. `/PART` 카드 없이 `/SHELL/<id>`·`/SH3N/<id>` 블록만 있으면 허용하고 info `MESH_INPUT_PART_CARD_MISSING` | HyperMesh 부분 export(.inc) 대응 |
| C2-D-5 | **파서**: `esl/rad/parser.py` 에 `parse_rad_part(path, part_id, *, need_props=False, max_include_depth, max_line_bytes)` **추가**. `_Deck.scan`·`load_shells(part_id)`·`load_nodes` 를 공유하고, `need_props=False` 면 두께·재료를 풀지 않음(물성 = ④ props, SC-D-8). 누적 상태 파일(.str/.sta)이 include 에 있으면 `MESH_INPUT_INVALID`("상태 파일 포함 메시는 비교 입력 불가"). 기존 `parse_rad` 서명·동작 불변 | ①②③·Case 경로 바이트 불변 |
| C2-D-6 | **단위**: mm 로 봅니다. `/BEGIN` 입력 길이 단위가 있고 mm 가 아니면 그 형상 `FAILED_MESH` `MESH_INPUT_UNIT`. `/BEGIN` 이 없으면(.inc) mm 로 보고 info. unit_ID 는 기존처럼 경고 `UNIT_ID_IGNORED` | 변환하지 않음(사용자 결정) |
| C2-D-7 | **메시 입력 처리** = `esl/doe/mesh_input.py read_shape_mesh(dir, main_rel, part_id, props, cfg) → (mesh, meta)`. 노드·요소는 `mg.build_mesh(X, conn, et, props)` 로 만듦(gmsh 출력과 같은 dict·번호 규칙·법선 정렬). 원 ID ↔ 새 번호는 `id_map.npz`(node_id_orig, elem_id_orig). 참조되지 않는 노드는 버림. 품질 = `mq.summarize`. 정렬·크기(SC-D-7b)·기준 frame 셀 매핑·`auto_supports` 는 **그대로**. **구멍 메움·폴백 없음**. 요소 수 > `mesh.max_elems` → `MESH_TOO_LARGE`. gmsh 를 부르지 않으므로 in-process(파싱만), 스레드 풀 슬롯은 같은 규칙 | 메시 그대로 사용(사용자 결정) |
| C2-D-8 | **크기 차이 경고**: 형상 메시 모서리 길이 중앙값 `e50` 이 `[h / r, h × r]`(`mesh_input.size_warn_ratio` r = 1.5, h = `compare.mesh.size_mm`) 밖이거나, 기준 d000 `e50` 대비 비가 r 를 넘으면 경고 `MESH_INPUT_SIZE_DIFF`(차단 아님). 연결 성분이 2개 이상이면 경고 `MESH_INPUT_DISCONNECTED` | 메시 크기 차이가 강성 차이로 섞이는 것을 알림 |
| C2-D-9 | **메시 방식 모드** `bead_doe.compare.mesh.mode ∈ {cad, remesh, auto}`, 기본 **auto**(Q3). 요청 `mesh_mode?` 로 스터디마다 덮어쓰기 가능(고급 설정). 모든 STEP 형상에 같은 모드 적용, `mesh` 형상에는 해당 없음. `auto` = **폴백 사다리 `compare.mesh.ladder`(C2-D-18, 기본 cad → refine_local → refine_global → remesh)를 차례로 시도**하고 첫 성공에서 멈춤. cad 시도는 v0.14.1/v0.15.1 면 폴백 포함. 다음 단계로 넘어가는 조건·상한은 C2-D-18·21. cad 시도의 `MESH_TOO_LARGE`·`GMSH_UNAVAILABLE` 은 폴백하지 않음. 기준 d000 도 같은 규칙(어느 단계든 성공이면 진행) | 실패 형상만 바꾸고 성공 형상은 지금 바이트 그대로 |
| C2-D-10 | **결과 메타** `mesh_method ∈ {cad, refine, remesh, fallback, mesh_input}`(`refine` = C2-D-22)(Case 기준 = `mesh_input`, source 로 구분). `fallback` 이면 경고 `REMESH_USED`("CAD 메시 실패 → 삼각형 재메시: <첫 오류>"). `cad_error{code, message}` 기록 | 사용자 요구 5 |
| C2-D-11 | **재메시 알고리즘**(§4) = CAD 단계 단순화 → OCC 삼각화(gmsh `importStl`) → 병합 → classify → createGeometry → quad 우선 재메시. 실행은 기존 spawn 격리(`mg._spawn`), `job.kind = "remesh"` | ④ 격리 규칙 재사용 |
| C2-D-12 | **작은 구멍 메움 = 재메시 전 CAD 단계**에서 기존 `mg.defeature` 그대로(면적 < `defeature.min_hole_area_mm2`). 실패하면 `DEFEATURE_SKIPPED` 후 계속. 재메시 후 메시 단계 메움은 하지 않음. 구멍 둘레 분할(transfinite)은 재메시 곡선에 적용하지 않음 → info `REMESH_HOLE_SIZING_SKIPPED` | 이산 고리 메움은 복잡하고 실패가 잦음. CAD 단계는 이미 검증된 코드 |
| C2-D-13 | **충실도** = 단순화 후 CAD 의 OCC 삼각화 S(편차 `linear_deflection_mm`) 대비 재메시 M 의 양방향 거리. `d_MS` = M 노드 → S 삼각형, `d_SM` = S 꼭짓점·삼각형 중심 → M 요소(quad 는 삼각형 2개로). 둘 다 cKDTree 후보 k=8 + 정확한 점-삼각형 거리. 지표 `{hausdorff_mm = max(max d_MS, max d_SM), max_dev_mm = max d_MS, p95_mm, area_ratio = A_M/A_S, deflection_mm, samples}`. 샘플 > `fidelity.samples_max` 면 고정 간격 추출(결정적). `hausdorff_mm > warn_mm` → 경고 `REMESH_FIDELITY_WARN`, `> fail_mm`(null 이면 끔) → `FAILED_MESH` `REMESH_FIDELITY`. 원 CAD 대비 값은 `hausdorff_mm + deflection_mm` 이하(보고서 표기). 구멍 메움으로 바뀐 영역은 단순화 후 CAD 기준이라 지표에 들어가지 않음(메움은 `defeature.filled` 로 따로 표시) | 원 CAD 에 직접 최근접 계산을 하면 면 × 노드라 비쌈. 메움 영역 오탐 방지 |
| C2-D-14 | **결정성**: `General.NumThreads 1`, `Mesh.RandomSeed` 고정(gmsh 기본), 옵션·입력이 같고 **같은 gmsh·OCC 버전**이면 `mesh.npz` 바이트 동일(`save_npz_det`). 버전이 다르면 보장하지 않음. `mesh.json` 에 `gmsh_version`·`occ_version` 을 기록하고 이어하기 해시에 포함 | BRepMesh·classify 는 결정적이지만 버전 간 차이 가능 |
| C2-D-15 | **이어하기 해시**(BD-D-16): `mesh_mode`·`remesh` 설정 해시는 **mode ≠ cad 일 때만** `input_sha256` 에 넣음. mesh 형상은 (주·include sha256 목록, part_id, mesh_input 설정 해시). v0.15.x 스터디(`inputs.mesh_mode` 없음)는 `cad` 로 보며 해시 불변 | 기존 스터디 재사용 |
| C2-D-16 | **활성**: `scenarios.compare = enabled ∧ compare.enabled ∧ (gmsh.ready ∨ mesh_input.enabled)`. gmsh 가 없으면 STEP 형상은 check-inputs 에서 503 `GMSH_UNAVAILABLE`(index), 메시 형상만 있는 비교는 허용. `remesh` 는 gmsh `model.mesh.importStl` 이 없으면 `REMESH_UNAVAILABLE`(mode remesh → 422, auto → 사다리에서 remesh 만 빼고 진행, 경고 1회) | 메시 입력은 gmsh 없이도 쓸 수 있음 |
| C2-D-17 | **산출물**: mesh 형상도 `best/<did>/ch_r.rad·ch_r.fem`(SC-D-11, 새 번호). 원본 rad 는 복사본 `input/shapes/<did>/` 에만 둠(zip 에 넣지 않음) | 사용자에게 원본이 이미 있음 |
| C2-D-18 | **폴백 사다리** `bead_doe.compare.mesh.ladder` 기본 `[cad, refine_local, refine_global, remesh]`(빼면 그 단계 끔, 순서 변경 가능, 중복 금지). `mode: auto` 일 때만 사다리 전체를 쓰고, `cad` = `[cad]`, `remesh` = `[remesh]` 입니다. 실패 면 폴백(구면·periodic, `mesh.fallback`)은 `cad`·`refine_*` 시도 **안에서** 기존대로 동작합니다(따로 단계로 두지 않음 — mesh-sphere 코드는 변경 없음). 다음 단계로 넘어가는 조건 = 그 시도가 `FAILED_MESH`·`MESH_FAILED`(시간 초과·크래시 포함)일 때입니다. `MESH_TOO_LARGE`(사용자 상한)도 refine 단계에서는 다음 단계로 넘어갑니다 | 요소 수 증가가 작은 순서 |
| C2-D-19 | **국부 세분화** `refine_local`: 직전 시도 mesh.json 의 실패 면(`errors[].face` 의 `_bbox_key`, 없으면 이 단계 건너뜀 — info `REFINE_LOCAL_NO_FACE`) + 이웃 `neighbor_rings` 고리(같은 곡선을 공유하는 면, `getAdjacencies`)에 크기 h_l = max(f·h, `min_size_mm`)를 줍니다. f = `local.factors`(0.75 → 0.5 → 0.33). 면은 세션마다 bbox 키로 다시 찾습니다. 크기는 gmsh Field(`Constant` 면 목록 또는 `MathEval`+`Restrict`)를 `Min` 배경장으로 넣고, 그 시도에서만 `Mesh.MeshSizeMin = h_l × min_size_factor` 입니다. 단계마다 새로 실패한 면이 생기면 누적합니다(≤ `local.max_faces`) | 증가가 가장 작음 |
| C2-D-20 | **전역 세분화** `refine_global`: h_g = max(h × g, `min_size_mm`, `mesh.size_min_mm`), g = `global.factors`(0.8, 0.667 → 2.4, 2.0 mm). 프로필의 다른 값(min_size_factor·곡률 0·OCCFix·defeature·fallback)은 그대로입니다. 구멍 둘레 분할은 max(hole_elems, ceil(둘레/h_g)) | 기존 함수에 h 만 바꿔 호출 |
| C2-D-21 | **상한**(모두 설정): 단계를 실행하기 전에 예측합니다. N_est = Σ면적 / (h_eff²) × `elem_per_h2`(quad 1.0, 보정값 = 직전 실패 시도 전 cad 의 면적·요소 실측 비가 있으면 그 값). 국부 = N_h + A_local × (1/h_l² − 1/h²). 건너뛰는 조건: N_est > `refine.max_elems`(60만), 또는 `estimate_direct_bytes(6·N_est, …)` > 가용 메모리 × `run.memory_margin`(`evaluate.parallel_limit` 와 같은 식, 병렬 1 기준), 또는 형상 누적 메시 시간 + 직전 시도 시간 × (N_est/N_prev) > `refine.total_timeout_s`. 건너뛰면 info `REFINE_SKIPPED_LIMIT{stage, factor, n_est, bytes_est, reason}`. 시도마다 `mesh.timeout_s` 는 그대로 적용합니다. 세분화 시도에는 `mg.quality` 의 상한을 `refine.max_elems` 로 넘깁니다(cad 시도는 `mesh.max_elems` 그대로). 실행 단계의 병렬 수는 기존 BD-D-15 가 가장 큰 형상 n_nodes 기준으로 자동으로 줄입니다(doe_jobs 그대로) | 실패해도 해석은 돌아가야 함 |
| C2-D-22 | **기록**: `mesh.json.refine = {kind: local|global, stage_index, h_mm, factor, base_h_mm, faces:[{bbox_key, type, center, ring}], n_elems, n_est, elem_ratio_h (= n_elems / N_h 예측), elem_ratio_ref (= n_elems / d000 n_elems), attempts:[{stage, factor, h_mm, status, code, seconds, n_elems?, skipped?}]}`, `mesh_method = "refine"`. 형상 표·결과 shape·보고서·ranking.csv(`mesh_method`, `refine_h_mm`, `elem_ratio_ref`)에 표시 | 사용자 요구 5 |
| C2-D-23 | **경고 `MESH_REFINED`**: "<이름>: 기본 3 mm 메시에 실패해 {국부|전역} 세분화(h {h} mm{, 면 n개})로 메시했습니다. 요소 수 기준 대비 ×{r}. 요소 크기가 기준 메시와 달라 컴플라이언스에 메시 의존 오차가 섞입니다(작은 개선율은 해석 차이일 수 있음)" — prep·결과 머리·보고서 | 사용자 요구 6 |
| C2-D-24 | **수렴 점검(권장안, `refine.convergence.enabled: true`)**: 세분화 형상이 하나라도 있으면 그 형상들이 쓴 h_r 마다(국부는 최솟값 대신 **같은 면에 같은 Field 를 줄 수 없으므로 전역 h = h_l 의 대표값 = 세분화 형상의 평균 요소 크기**) 기준 d000 을 h_r 로 다시 메시·해석합니다(같은 하중·지지 규칙, 결과 캐시 `run/designs/d000_h<h>/`). δ_e = C_ref(h_r)/C_ref(h) − 1 (ESL별)를 그 형상의 **메시 편향 추정**으로 결과·보고서에 표시하고, max|δ_e| > `convergence.tol`(null = `rank.ratio_tol`)이면 경고 `MESH_REFINE_BIAS` 를 냅니다. 선택 옵션 `convergence.same_h_baseline: false` — true 면 그 형상의 개선율을 C_ref(h_r) 기준으로 계산하고 원래 값도 함께 표시합니다. d000 이 Case 메시 기준(`source: case`)이거나 메시 입력이면 다시 메시할 수 없으므로 점검을 생략하고 info `REFINE_CONVERGENCE_SKIPPED` | 같은 형상을 두 크기로 풀 수는 없어서(기본 h 에서 실패) 기준 형상으로 민감도를 잼 |
| C2-D-25 | **결정성·불변**: 세분화 시도도 같은 입력·버전이면 바이트가 같습니다(C2-D-14 같은 조건). 사다리에 들어가지 않은 형상은 코드 경로가 기존과 같고 `size_fields` 키도 없으므로 v0.15.x 와 바이트가 같습니다. 이어하기 해시는 `ladder`·`refine` 설정 해시를 mode ≠ cad 일 때만 포함합니다(C2-D-15) | V-C2-8 유지 |

## 3. 데이터 모델

```text
CompareShapeIn += { source: "step"|"mesh" = "step", part_id?: int(1..2^31-1) }   # rel = STEP 파일 또는 메시 주 파일
DoeCheckIn(compare) += { mesh_mode?: "cad"|"remesh"|"auto" }       # 없으면 설정값
DoeCheckOut(compare).shapes[] += { source, part_id, main_rel, files:[{rel, sha256, size_mb}] (mesh), parts?:[{id, title, n_shells}] (≤50, mesh) }
DoeCheckOut(compare) += { mesh_mode, remesh_available: bool }
DoeStudyOut.inputs(compare).shapes[] += { source, part_id }; inputs += { mesh_mode }
DoeStudyOut.prep(compare).shapes[] += { source, mesh_method, cad_error?:{code,message},
     fidelity?:{hausdorff_mm, max_dev_mm, p95_mm, area_ratio, deflection_mm, warn_mm, fail_mm, over_warn},
     edge_median_mm, n_components }
DoeResultOut.ranking[].shape / baseline.shape / excluded[].shape += { source, mesh_method, fidelity? }
```
- 폴더: `input/shapes/<did>.step`(STEP) | `input/shapes/<did>/<rel…>`(메시: 주 파일 + include, 업로드 상대경로 유지). `prep/shapes/<did>/mesh/{mesh.npz, mesh.json, id_map.npz?, remesh_stl.npz?}`. `remesh_stl.npz` 는 `remesh.keep_stl: false` 면 만들지 않음.
- 이름·rel 은 argv·경로 조합에 그대로 쓰지 않음. 경로는 `U.target_path`·`is_within` 검사 후 사용.

## 4. 재메시 알고리즘 (`esl/doe/mesh_remesh.py remesh_file(src, h, cfg, props, *, out_dir) → (mesh, meta)`)

| 단계 | 내용 | 실패 코드 |
|---|---|---|
| R1 | gmsh 초기화, `General.NumThreads 1`, `geometry_options(profile)`(OCCFix*), `importShapes(STEP)`, 면 수·면적 기록 | `REMESH_FAILED`(가져오기) |
| R2 | `defeature.enabled` 면 `mg.defeature(gmsh, df, h)`(C2-D-12) | 경고 `DEFEATURE_SKIPPED` |
| R3 | `Mesh.StlLinearDeflection = linear_deflection_mm`, `…Relative 0`, `Mesh.StlAngularDeflection = radians(angular_deflection_deg)`, `gmsh.model.mesh.importStl()` → 노드·삼각형 추출. 0개 → 실패, > `stl_max_tris` → 실패 | `REMESH_STL_EMPTY`, `REMESH_FAILED` |
| R4 | `gmsh.clear()`, 이산 면 1개 `addDiscreteEntity(2)` + 삼각형, `Geometry.Tolerance = merge_tol_mm`, `removeDuplicateNodes()` | `REMESH_FAILED` |
| R5 | `classifySurfaces(radians(feature_angle_deg), boundary=True, forReparametrization=True, curveAngle=radians(curve_angle_deg))` → `createGeometry()` → synchronize. 패치 수 기록 | `REMESH_CLASSIFY_FAILED` |
| R6 | `gmsh_options(h, profile)` 그대로(3 mm·Min 2.4·곡률 0·ExtendFromBoundary 0), `Mesh.RecombineAll = recombine`, `Mesh.Algorithm` = `algorithms` 를 차례로 **모델 전체** 재시도(면 폴백 없음) → `generate(2)` | `REMESH_FAILED`(마지막 오류 문구) |
| R7 | `mg._extract` → `mg.build_mesh` → `mq.summarize` | – |
| R8 | 충실도(C2-D-13) | `REMESH_FIDELITY` |
- 사용자 문구(`resources/doe_messages.json`): `REMESH_FAILED` "삼각형 재메시에 실패했습니다: {첫 오류}. 특징각(remesh.feature_angle_deg)을 키우거나 메시 파일로 올리세요" / `REMESH_CLASSIFY_FAILED` "면 분류(특징각 {deg}°)에 실패했습니다" / `REMESH_STL_EMPTY` "STEP 에서 삼각화를 만들지 못했습니다(면 없음)" / `REMESH_FIDELITY` "재메시가 원 형상과 최대 {mm} mm 다릅니다(> {fail} mm)" / `REMESH_UNAVAILABLE` "이 gmsh 버전({ver})은 삼각형 재메시를 지원하지 않습니다".
- 실패는 모두 형상 상태 `FAILED_MESH` + code 입니다. auto 에서 재메시까지 실패하면 code = 재메시 코드이고 `cad_error` 를 함께 남깁니다.
- 연결: `mg._child` 에 `if job.get("kind") == "remesh": mesh_remesh.remesh_file(...)` 몇 줄, `run_isolated(..., kind="cad")` 키워드 추가. mesh-sphere 가 건드리지 않는 함수입니다.

## 4A. 세분화 폴백 구현 위치 (C2-D-18~25)

- **Core 신규** `esl/doe/mesh_refine.py`: `plan(stage, prev_meta, h, cfg, avail_bytes) → [attempt…]`(예측·건너뜀 판정), `neighbor_faces(gmsh, keys, rings)`, `estimate_elems(face_areas, h, local_keys, h_l)`.
- **Core 추가** `esl/doe/mesh_gmsh.py`: 선택 cfg 키 `mesh.size_fields: [{keys:[bbox_key…], size_mm}]` 를 `_session` 에서 OCC 동기화 직후에 Field 로 적용(키가 없으면 아무것도 하지 않음), `quality()` 는 `mc["max_elems"]` 를 그대로 읽음(호출자가 refine 상한을 넣은 cfg 사본을 넘김). **mesh-sphere 병합 뒤에** `_session` 몇 줄만 추가합니다(충돌 영역이므로 선행 조건 유지).
- **Worker** `esl/doe/stages.py _cmp_mesh_shape`: 사다리 실행기(시도마다 `run_isolated`, 시도 폴더 `prep/shapes/<did>/mesh/try_<n>/`, 성공본을 `mesh/` 로 `atomic_replace`), `_cmp_refine_bias`(BD_BASELINE 뒤 d000 h_r 재해석, BD_POST 에서 δ 계산), `report_doe.py` 열·경고.
  - (통합 2026-11-04 구현) auto 의 첫 cad 시도는 기존 경로 그대로 `mesh/` 에서(성공이면 시도 폴더 없음 — 바이트 불변), 실패한 뒤의 시도만 `try_<n>/`(n = 1부터). d000 h_r 재해석은 BD_POST 시작 부분에서 실행(별도 작업 단계 없음, 캐시 `run/designs/d000_h<h>/` — done.json 해시가 같으면 재사용). 결과 shape `refine.faces[].bbox_key` 는 문자열(bbox 6값 쉼표 연결 — 프런트 타입). 메시 입력 기준의 `reference_source` 는 `step`(Literal step|case 유지).
- 메시지(`resources/doe_messages.json`): `MESH_REFINED`, `MESH_REFINE_BIAS`, `REFINE_SKIPPED_LIMIT`, `REFINE_LOCAL_NO_FACE`, `REFINE_CONVERGENCE_SKIPPED`.

## 5. 설정 키 (거울 규칙: `esl/doe/__init__.DEFAULTS["compare"]` = `core/config.py` pydantic 기본값 = `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`, `tests/pipeline/test_config.py` 거울 시험)

```yaml
bead_doe:
  compare:
    mesh:
      mode: auto                 # cad | remesh | auto (C2-D-9) — 기존 키는 그대로(fallback 은 v0.15.1)
    remesh:                      # C2-D-11~14
      enabled: true
      feature_angle_deg: 30.0    # classifySurfaces 특징각(1..89)
      curve_angle_deg: 60.0      # 곡선 분할각(통합 2026-11-04: 180 → 60 — 180 이면 판 모서리가 0.79 mm 깎이고 60 이면 0.13 mm)
      linear_deflection_mm: 0.05 # OCC 삼각화 선형 편차(>0, ≤ fidelity.warn_mm)
      angular_deflection_deg: 5.0
      merge_tol_mm: 0.001
      stl_max_tris: 5000000
      algorithms: [6, 5, 1]      # 모델 전체 재시도 순서
      recombine: true            # quad 우선
      keep_stl: false
      timeout_s: null            # null = mesh.timeout_s
      fidelity: {warn_mm: 0.3, fail_mm: 1.5, samples_max: 200000}
    mesh_input:                  # C2-D-2~8
      enabled: true
      formats: [".rad", ".inc"]
      max_mb: 500                # 주 + include 합계, 형상당
      include: true
      max_include_depth: 8
      size_warn_ratio: 1.5
```
- pydantic(`BeadDoeCompareRemeshCfg`, `BeadDoeCompareMeshInputCfg`, `BeadDoeCompareMeshCfg.mode: Literal`): 각도 (0,90)/(0,180], 편차 > 0, `fail_mm` null 또는 ≥ `warn_mm`, `formats` ⊆ {.rad,.inc}(Q2 로 넓힘), `algorithms` = 기존 검사기. 섹션이 없으면 기본값.
- 하드코딩 금지. 테스트용 고장 주입은 설정 키가 아니라 테스트 monkeypatch 로만.

**세분화 폴백 추가 키**(C2-D-18~24, DEFAULTS·pydantic·yaml 2개 거울):

```yaml
bead_doe:
  compare:
    mesh:
      ladder: [cad, refine_local, refine_global, remesh]   # auto 일 때 순서(빼면 끔)
    refine:
      enabled: true
      min_size_mm: 0.5
      max_elems: 600000          # 세분화 시도 요소 상한(mesh.max_elems 와 별개)
      total_timeout_s: 3600      # 형상 1개 사다리 전체 시간 예산
      elem_per_h2: 1.0           # 예측 보정 기본(quad)
      local: {factors: [0.75, 0.5, 0.33], neighbor_rings: 1, max_faces: 20}
      global: {factors: [0.8, 0.667]}   # 3 → 2.4 → 2.0 mm
      convergence: {enabled: true, tol: null, same_h_baseline: false}
```
- pydantic: factors 는 (0,1) 범위에서 내림차순, `min_size_mm` > 0, `max_elems` ≥ `mesh.max_elems`, ladder ⊆ {cad, refine_local, refine_global, remesh} 이고 cad 가 맨 앞. `mesh.size_min_mm` 과 `min_size_mm` 의 대소 검증은 하지 않습니다(기본값 1.0 > 0.5 와 충돌) — 세분화 시도만 하한을 `refine.min_size_mm` 으로 낮춥니다(attempt_cfg — `mesh_refine.attempt_cfg` 가 `check_h` 하한을 내림, 통합 2026-11-04).

## 6. API · 스키마 · DB

- 업로드: 메시 형상 = 기존 청크 업로드, 같은 세션에 주 + include. 다중 STEP 세션 규칙(rel)을 메시에도 적용: `doe_source(kind="mesh", rel=…)` 는 rel 이 세션의 살아 있는 `.rad/.inc` 와 정확히 같아야 합니다. 확장자 검사 = `mesh_input.formats`, 크기 = 주 + include 합계 ≤ `max_mb`(422 `MESH_INPUT_TOO_LARGE`). 결과는 `save_doe_check(purpose doe_mesh)`.
- check-inputs 검증 순서(기존 §3 뒤에 추가): `source` 값 → `INVALID_PARAMS`. step 에 `part_id` 가 있음 → `INVALID_PARAMS`. mesh: 형식 → `MESH_FORMAT_UNSUPPORTED`, include 경로 → `PATH_OUTSIDE_ROOT`/`MESH_INPUT_INVALID`, 파트 → `MESH_INPUT_PART_REQUIRED`/`MESH_INPUT_PART_NOT_FOUND`(`deck.scan` 만 — 숫자 블록은 읽지 않음), `mesh_mode=remesh` + 미지원 → `REMESH_UNAVAILABLE`. 같은 (upload_id, rel) 중복 → `INVALID_PARAMS`. 같은 sha 의 메시 → `SHAPE_DUPLICATE_FILE`(경고).
- `GET /doe/settings` `compare` += `{mesh_mode, remesh_available, mesh_input:{enabled, formats, max_mb}, step_ready}`.
- **migration 불필요**: `bead_does.scenario` 그대로(`compare`). 새 필드는 모두 `inputs`·`prep`·`result` JSONB 입니다. 업로드 purpose `doe_mesh` 는 이미 있습니다. `tables.py` 변경 없음.
- clone: 메시 형상은 주 + include 업로드가 모두 남아 있어야 합니다(`PREREQUISITE_MISSING`, missing=[index]).

## 7. 파이프라인 차이 (STEP_COMPARE §5)

```
BD_INPUT  step → 기존. mesh → copy_mesh_upload(main, upload_root, input/shapes/<did>/) + sha 확인, shapes.json 행 {source:"mesh", main_rel, part_id, files[]}
BD_MESH0  _cmp_mesh0 의 submit 대상만 _cmp_mesh_shape 로 바꿈:
            mesh   → mesh_input.read_shape_mesh (in-process, 슬롯 같음) → mesh_method mesh_input
            cad    → _cmp_mesh_one (기존, 변경 없음)
            remesh → _cmp_remesh_one (run_isolated kind remesh)
            auto   → 사다리 실행기(C2-D-18, §4A): cad → refine_local → refine_global → remesh, 시도 폴더 try_<n>/,
                     method cad | refine | fallback(remesh)
          shapes[] 에 source·mesh_method·fidelity·edge_median_mm·n_components, 경고 C2-D-1·8·10·13 추가
          gmsh 확인(mg.available)은 STEP 형상이 있을 때만(기존 그대로)
BD_LOADS·BD_*·BD_POST  변경 없음(메시 dict 형식 같음). ranking.csv 에 source·mesh_method·hausdorff_mm 열 추가
```

## 8. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 필수만)

- **형상 표 행**: [기준 ◉] [STEP | 메시] 토글 [이름] [파일 이름·크기(메시면 "주 파일 + include n개")] [파트 ID 숫자 칸 — 메시일 때만, check-inputs `parts[]` 를 datalist 로, 하나뿐이면 자동 채움] [✕]. 놓기 칸은 `.step/.stp/.rad/.inc` 를 받습니다. 한 번에 놓은 STEP 은 파일마다 행 1개, 한 번에 놓은 rad/inc 묶음은 메시 행 1개(주 파일 규칙 C2-D-2). 토글 기본값 = 확장자.
- **고급 설정**(접힘, 기존 물성 칸 아래): 메시 방식 [자동(기본) | CAD | 재메시]. `remesh_available` 가 false 면 재메시를 비활성하고 툴팁에 사유. 메시 형상만 있으면 숨김.
- **준비 후·결과 형상 표**: '메시 방식' 열 = CAD / 재메시 / 재메시(폴백) / 메시 입력. 재메시 계열은 툴팁에 "최대 편차 x.xx mm · 면적비 1.00x", 경고 넘으면 주황 배지. 메시 입력 행 툴팁에 파트 ID·요소 크기 중앙값.
- 결과 순위표(`DoeRanking`)·ESL별 표 이름 열 옆에 같은 '메시 방식' 짧은 배지.
- 고급 설정 메시 방식 옆에 "실패 시 세분화 허용" 체크(= ladder 에 refine_* 포함 여부, 기본 켬)를 둡니다.
- '메시 방식' 열 = "세분화(국부 ×0.5 · 1.5 mm · 면 3 · 요소 ×1.4)" / "세분화(전역 2.4 mm · 요소 ×1.6)". 툴팁에 시도 목록(건너뛴 사유 포함)과 수렴 점검 δ 를 보여 줍니다.

## 9. 보고서 (`esl/doe/report_doe.py`)

- 형상 표에 열 추가: 출처(STEP/메시/Case), 메시 방식, 파트 ID, 충실도(Hausdorff mm·면적비, 원 CAD 대비 ≤ +편차 mm 표기), 요소 크기 중앙값.
- 머리 경고에 `COMPARE_MESH_METHOD_MIXED`·`REMESH_USED`·`REMESH_FIDELITY_WARN`·`MESH_INPUT_SIZE_DIFF`.
- 형상 표에 h·배율·세분화 면 수·요소 배수 열, 수렴 점검 표(ESL별 δ_e, same_h_baseline 이면 두 개선율).
- 한계 절에 "세분화 형상은 요소 크기가 달라 메시 의존 오차 포함 — δ 참고".
- 한계 절 추가: "재메시는 CAD 면 구조를 버린 근사(단순화 후 CAD 대비 편차 표시), 구멍 둘레 분할 미적용", "메시 입력은 그대로 사용 — 크기·품질은 사용자 메시 책임".

## 10. 시험 (V-C2-*)

| ID | 시험 | 위치 |
|---|---|---|
| V-C2-1 | **합성 복잡 STEP**(시험 중 gmsh OCC 생성 — 새 파일 `tests/doe/synth_complex.py`, mesh-sphere 의 `synth_compare.py` 는 건드리지 않음): 400×300 판 + 폭 0.3 mm 띠 면·쐐기 면 다수 + 구면 코너(구 캡 비드) + Ø2 구멍 → remesh 성공, quad 비율 ≥ 0.9, 모서리 중앙값 h ± 15 %, 품질 over_limit false, hausdorff < warn | `tests/doe/test_mesh_remesh.py`(gmsh 없으면 skip) |
| V-C2-2 | 결정성: 같은 STEP 을 spawn 2회 remesh → `mesh.npz` 바이트 동일, `mesh.json`(wall 시간 제외) 동일 | 같은 파일 |
| V-C2-3 | auto: monkeypatch 로 cad `MESH_FAILED` 주입 → method `fallback`·경고 `REMESH_USED`·`cad_error`. `MESH_TOO_LARGE` 주입 → 폴백 없음. cad 성공 → method `cad`, `mesh.npz` 가 mode cad 결과와 바이트 동일 | `tests/doe/test_step_compare.py`(추가) |
| V-C2-4 | 충실도: 작은 구멍 메움 영역이 지표에 안 들어감, 특징각 89°·편차 2 mm 로 일부러 거칠게 → `REMESH_FIDELITY_WARN`/`REMESH_FIDELITY` 경계, `fail_mm null` 이면 실패 없음, 점-삼각형 거리 단위 시험 | `tests/doe/test_mesh_remesh.py` |
| V-C2-5 | 메시 입력 파서: 파트 2개 rad + include 2단, part_id 선택, SH4N+SH3N 혼합, /PART 없는 .inc, 쉘 아닌 요소 → 실패, /BEGIN 단위 m → `MESH_INPUT_UNIT`, include 업로드 밖·링크 → `PATH_OUTSIDE_ROOT`, 파트 여럿 + ID 없음 → `MESH_INPUT_PART_REQUIRED`, 상태 파일 include → 실패, 원본 파일 sha 전후 불변, `parse_rad` 기존 시험 통과 | `tests/rad/test_rad_parser.py`(추가), `tests/doe/test_mesh_input.py` |
| V-C2-6 | 크기 차이·성분: 6 mm 메시 → `MESH_INPUT_SIZE_DIFF`, 두 조각 → `MESH_INPUT_DISCONNECTED` | `tests/doe/test_mesh_input.py` |
| V-C2-7 | **메시 입력 E2E**: STEP 3개 ④ 실행 → 각 `best/<did>/ch_r.rad` 를 메시 형상으로 다시 올려 ④ 실행 → 순위·score·ESL별 ratio 가 1e-9 안에서 같음. 혼합(기준 메시 + STEP 2) 실행·`COMPARE_MESH_METHOD_MIXED` 미발생(둘 다 같은 메시면 cad vs mesh_input 이므로 발생 — 경고 존재 확인) | `worker/tests/test_doe_compare_e2e.py` |
| V-C2-8 | 회귀: ③ `step` 메시·결과 바이트 불변, 기존 ④(mode cad, 그리고 cad 가 성공하는 auto) `mesh.npz`·`loads.npz`·순위 수치 불변(JSON 은 새 키 제외 비교), v0.15 스터디 이어하기 `input_sha256` 불변, ①②·select 시험 통과 | 기존 `tests/doe/*`, `worker/tests/test_doe_*` |
| V-C2-9 | API: source·part_id 검증, mesh rel 지정, 형식·크기·include·파트 오류, gmsh 없음 + 메시만 → 활성, STEP 포함 → 503, `mesh_mode` 값·`REMESH_UNAVAILABLE`, clone 업로드 누락 | `backend/tests/test_doe_compare_api.py` |
| V-C2-10 | 설정 거울: DEFAULTS = pydantic = example yaml 2개, 잘못된 값 거부 | `tests/pipeline/test_config.py` |
| V-C2-11 | 보고서: 메시 방식·충실도 열, 경고, 한계 절, HTML 이스케이프 | `tests/doe/test_report_doe.py` |
| V-C2-12 | UI: 토글·파트 ID 칸·datalist·확장자 기본값·묶음 놓기, 고급 설정 모드(비활성 사유), 결과 '메시 방식' 열·툴팁, 2560×1440·1920×1080 잘림 없음 | `frontend/__tests__/doe_compare_mesh.test.tsx`, mock |
| V-C2-13 | 실패 주입(monkeypatch: h > 2.5 면 특정 bbox 면 실패) → refine_local 0.75 에서 성공, `mesh_method refine`·`refine.kind local`·faces·elem_ratio, `MESH_REFINED`. local 을 끄면 global 2.4 에서 성공. 국부 성공의 요소 수 < 전역 | `tests/doe/test_mesh_refine.py`, `tests/doe/test_step_compare.py` |
| V-C2-14 | 상한: `refine.max_elems` 를 작게 → 해당 단계 `REFINE_SKIPPED_LIMIT`(reason elems) 후 다음 단계·remesh. 가용 메모리 monkeypatch → reason memory. `total_timeout_s` → reason time. 예측식 단위 시험(평판 면적/h²) | 같은 파일 |
| V-C2-15 | 정상 형상: 사다리 미진입, `size_fields` 없음 → gmsh 옵션 dict·`mesh.npz` 바이트가 v0.15.x 와 동일(V-C2-8 확장). 세분화 시도 2회 실행 → 바이트 동일 | `tests/doe/test_mesh_gmsh.py` |
| V-C2-16 | 수렴 점검: 합성 평판 d000 을 h 와 h_r 로 풀어 δ 기록, tol 경계에서 `MESH_REFINE_BIAS`, same_h_baseline 개선율, Case 기준이면 생략 info, 캐시 재사용 | `tests/doe/test_step_compare.py`(통합 2026-11-04: 세분화 형상을 만들려면 cad 시도 실패 주입이 필요한데 워커 E2E 는 코어 단계를 spawn 자식에서 돌려 monkeypatch 가 닿지 않음 — 코어 단계 직접 실행으로 이동) |
| V-C2-17 | 설정 거울·검증(ladder 순서·factors·상한 관계) | `tests/pipeline/test_config.py` |

## 11. 파일 소유권과 작업 단계

| 담당 | 파일(소유) | 완료 조건 |
|---|---|---|
| Core | **신규** `esl/doe/mesh_remesh.py`, `esl/doe/mesh_input.py`, `tests/doe/synth_complex.py`·`test_mesh_remesh.py`·`test_mesh_input.py`. **추가만** `esl/rad/parser.py`(`parse_rad_part`), `esl/doe/mesh_gmsh.py`(`_child` 분기·`run_isolated(kind=)` — mesh-sphere 가 고치지 않는 함수만), `esl/doe/__init__.py` DEFAULTS(`compare.mesh.mode`·`remesh`·`mesh_input`) | V-C2-1, 2, 4, 5, 6 |
| Worker | `esl/doe/stages.py`(`_cmp_input` mesh 분기, `_cmp_mesh_shape`·`_cmp_remesh_one` 신규, `_cmp_mesh0` 의 submit 한 줄·doc 필드·경고, `_cmp_sha`, `_cmp_ranking_csv`), `esl/doe/report_doe.py`, `worker/esl_worker/doe_jobs.py`(gmsh 확인 조건), `worker/tests/test_doe_compare_e2e.py` | V-C2-3, 7, 8, 11 |
| Backend | `api/schemas.py`, `api/services/doe.py`(검증·settings·활성·clone), `api/services/uploads.py`(`doe_source` mesh rel·파트 스캔), `core/config.py`(pydantic), `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`, `resources/doe_messages.json`, `backend/tests/test_doe_compare_api.py`, `tests/pipeline/test_config.py` | V-C2-9, 10 |
| Frontend | `api/types.ts`·`api/doe.ts`, `components/DoeInputs.tsx`(`CompareShapes` 행·`CompareShapeSummary`), `pages/doe/DoeStudy.tsx`(고급 설정), `components/DoeRanking.tsx`·`DoePerEslTable.tsx`(배지), `mock/doedata.ts`, `__tests__/doe_compare_mesh.test.tsx` | V-C2-12 |
| Plan/Impl | `VERSION`·`CHANGELOG.md` 0.16.0, `docs/manual/user.md`(④ 메시 옵션), `docs/decisions.md` | – |

- **세분화 폴백 소유권**(C2-D-18~25):
  - Core: `esl/doe/mesh_refine.py`(신규), `mesh_gmsh._session` 의 `size_fields` 몇 줄(mesh-sphere 병합 뒤), DEFAULTS, `tests/doe/test_mesh_refine.py`.
  - Worker: `stages._cmp_mesh_shape` 사다리 실행기·`_cmp_refine_bias`, `report_doe.py`, E2E.
  - Backend: pydantic·yaml·메시지. Frontend: 체크·열 표기.
  - 병렬 범위는 같습니다(Core 인터페이스 `plan()`·`size_fields` 형식은 이 절로 고정).
- **선행 조건**: `fix/mesh-sphere`·`fix/winerror32` 를 main 에 병합(v0.15.1)한 뒤 그 main 에서 `impl/c2-*` 브랜치를 만듭니다. 겹치는 곳은 `compare.mesh` yaml flow 블록·DEFAULTS·pydantic, `mesh_gmsh.py`, `stages._cmp_mesh*`, `synth_compare.py`, `uploads.py` 입니다.
- **병렬**: Core ∥ Backend ∥ Frontend(mock). 인터페이스는 이 계약의 §3·§4·§5 로 고정합니다. Worker 는 Core 의 `remesh_file`·`read_shape_mesh` 서명이 정해지면 시작합니다(같은 브랜치 위 또는 stub). 통합 순서: Core → Worker → Backend → Frontend → E2E(V-C2-7·8).
- Core·Worker 는 `stages.py`·`mesh_gmsh.py` 를 나눠 갖습니다(Core 는 `_child`·`run_isolated` 만, Worker 는 stages 만).

## 12. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-C2-1 | 배포 gmsh 에 `model.mesh.importStl` 이 없거나 OCC STL 옵션 이름이 다름 | 시작 시 `hasattr` 확인 → `remesh_available`, 미지원이면 auto 는 cad 만(C2-D-16). 구현 첫 작업으로 배포 gmsh 버전에서 R3 확인 |
| R-C2-2 | classify 가 비드 측벽·작은 필렛을 아주 작은 패치로 쪼개 재메시가 실패하거나 요소가 나빠짐. **알려진 한계(통합 2026-11-04)**: 필렛이 접선으로 이어진 비드(측벽–필렛–바닥이 G1 연속)는 특징각으로 경계를 못 찾아 `REMESH_CLASSIFY_FAILED` 로 실패할 수 있음 | 특징각 설정 키, `algorithms` 재시도, 실패 문구로 메시 입력 안내. `auto` 사다리는 cad → refine_local → refine_global → remesh 순이라 이런 형상은 세분화가 먼저 시도되어(대개 CAD 면 구조로 성공) 영향이 줄어듦. 남는 경우는 메시 입력(옵션 1) 권장(user.md ④ 메시 옵션) |
| R-C2-3 | 재메시가 날카로운 비드 모서리를 둥글게 만들어 강성이 달라짐 | 충실도 지표·경고, 방식 혼합 경고, 보고서 한계 절 |
| R-C2-4 | 메시 입력 크기·품질이 STEP 메시와 달라 개선율에 메시 차이가 섞임 | `MESH_INPUT_SIZE_DIFF`, 품질 요약, 혼합 경고, V-C2-7 등가 시험 |
| R-C2-5 | 큰 rad(수백 MB, 파트 많음)의 check-inputs 스캔 시간 | `deck.scan` 만(숫자 블록 위치만), `max_mb` 상한 |
| R-C2-6 | mesh-sphere 와 병합 충돌 | 선행 조건(§11), 새 모듈 위주, 기존 함수는 호출부 한 줄만 |
| R-C2-7 | 충실도 계산 메모리(수백만 삼각형) | `samples_max` 고정 간격 추출, cKDTree k=8 |
| R-C2-8 | 세분화해도 형상 결함(퇴화 모서리)이면 계속 실패하고 시간만 듦 | 시간 예산·예측으로 건너뜀, 다음 단계 remesh |
| R-C2-9 | 국부 세분화 경계에서 크기 급변 → 품질 Fail 증가 | 이웃 고리 1, 품질 요약 그대로(경고만), 0.33 하한 |
| R-C2-10 | 요소 수가 늘어 실행 병렬 수가 줄고 시간이 늘어남 | BD-D-15 자동 축소, `refine.max_elems` |
| R-C2-11 | 수렴 점검 추가 해석 비용 | h_r 마다 1회 캐시, 끌 수 있음 |

## 13. 결정 (확정 2026-11-04 사용자)

- 상태: **확정 (2026-11-04 사용자)**. 권장안을 모두 채택했습니다.
- **Q1. 한 비교 안 STEP·메시 혼합** → **허용**. 방식이 섞이면 경고 `COMPARE_MESH_METHOD_MIXED`(C2-D-1).
- **Q2. Nastran `.bdf`/`.fem`** → **v0.16.0 제외, v0.16.x 에서 다룸**(GRID·CQUAD4·CTRIA3, small·large·free field, PSHELL PID 를 파트 ID 로). 이번에는 `mesh_input.formats` 키와 오류 코드 `MESH_FORMAT_UNSUPPORTED` 만 준비(C2-D-2).
- **Q3. 기본 메시 방식** → **`auto`**, 사다리 `[cad, refine_local, refine_global, remesh]`, 수렴 점검 켬(`refine.convergence.enabled: true`)(C2-D-9·18·24). CAD 가 성공한 형상은 지금과 바이트가 같고(V-C2-3·8·15), 실패한 형상만 요소 수가 가장 적게 느는 순서로 폴백하며, 메시 편향은 δ 로 드러납니다.
