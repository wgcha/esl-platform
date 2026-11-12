# 계약: 시나리오 ④ 형상 직접 비교 — 메시 성공률 향상 옵션 (COMPARE_MESH, v0.16.0)

- **v0.16.1 변경 = `esl_select_relax.md`**(SELECT_RELAX — 이 문서와 충돌하면 그 문서가 우선).
- **v0.16.3 변경(2026-11-10, 이슈 #53 실서버 보고)**: C2-D-26~31(freeform·면 실패 판정·OCC 삼각형 폴백·단계 시간 몫·단계별 문구·STEP 라벨), 설정 §5 끝, 시험 V-C2-26~31. 기본 사다리 `cad → refine_local → refine_global → freeform → defeature → tria`(remesh 단계는 예전 스터디 스냅샷용으로 남음).
- **v0.17.4 변경(2026-11-11, 실 STEP 약 2800 면 — ③ 은 되고 ④ 는 실패·지연)**: C2-D-32~42(cad_relaxed·대형 모델·자식 제한·시간 초과 면 실패·경로 기록 + 이슈 #63 현장 진단: 구멍 메움 되돌림·nofix 대응·진행 줄·시도 로그·형상 실패 차단·freeform 삼각화 편차), 설정 §5 끝, 시험 V-C2-32~42. `bead_doe.select.graph.limits.max_elems` 250,000 → 600,000. CAD 가 성공하는 정상 STEP 은 결과 바이트 불변(실패 경로만 바뀜).
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
| C2-D-1 | **형상 출처** `source ∈ {step, mesh}`(기본 step). 기준 Case 메시는 기존대로 `source: case`. **한 비교 안 STEP·메시 혼합 허용**(Q1 권장). 경고 `COMPARE_MESH_METHOD_MIXED` "형상마다 메시 방식이 달라 개선율에 메시 차이가 섞입니다" 는 READY 형상의 방식 집합(Case 기준 메시 = `case`, 사용자 메시 입력 = `mesh_input`)이 둘 이상이고 **refine·remesh·fallback·메시 입력(source=mesh) 중 하나가 섞일 때만** 냅니다. {cad, case} 만이면 `COMPARE_REF_CASE_MESH` 와 내용이 겹치므로 내지 않습니다(v0.16.0 검증 수정) | 기준만 HyperMesh 메시이고 나머지는 STEP 인 실제 흐름을 지원 |
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
| C2-D-21 | **상한**(모두 설정): 단계를 실행하기 전에 예측합니다. N_est = Σ면적 / (h_eff²) × `elem_per_h2`(quad 1.0, 보정값 = 직전 실패 시도 전 cad 의 면적·요소 실측 비가 있으면 그 값). 국부 = N_h + A_local × (1/h_l² − 1/h²). 건너뛰는 조건: N_est > `refine.max_elems`(60만), 또는 `estimate_direct_bytes(6·N_est, …)` > 가용 메모리 × `run.memory_margin`(`evaluate.parallel_limit` 와 같은 식, 병렬 1 기준), 또는 형상 누적 메시 시간 + 직전 시도 시간 × (N_est/N_prev) > `refine.total_timeout_s`. **누적 시간(cad 시도 포함)이 `refine.total_timeout_s` 이상이면 N_est 가 없어도(cad 시간 초과·크래시로 넓이 모름) reason time** 으로 건너뜁니다. remesh 단계도 같은 형상 누적 예산을 적용해, 남은 시간이 없으면 `REFINE_SKIPPED_LIMIT`(stage remesh, reason time)로 건너뜁니다. 건너뛰면 info `REFINE_SKIPPED_LIMIT{stage, factor, n_est, bytes_est, reason}`(remesh 는 factor·n_est "—"). **auto 의 시도마다 제한 시간 = min(단계 제한 시간, 남은 예산)**(단계 제한 시간 = cad·세분화 `mesh.timeout_s`, remesh `remesh.timeout_s`(null 이면 `mesh.timeout_s`)) — 형상 1개 사다리 총 시간이 예산 안에 듭니다(v0.16.0 검증 수정). 세분화 시도에는 `mg.quality` 의 상한을 `refine.max_elems` 로 넘깁니다(cad 시도는 `mesh.max_elems` 그대로). 실행 단계의 병렬 수는 기존 BD-D-15 가 가장 큰 형상 n_nodes 기준으로 자동으로 줄입니다(doe_jobs 그대로) | 실패해도 해석은 돌아가야 함 |
| C2-D-22 | **기록**: `mesh.json.refine = {kind: local|global, stage_index, h_mm, factor, base_h_mm, faces:[{bbox_key, type, center, ring}], n_elems, n_est, elem_ratio_h (= n_elems / N_h 예측), elem_ratio_ref (= n_elems / d000 n_elems), attempts:[{stage, factor, h_mm, status, code, seconds, n_elems?, skipped?}]}`, `mesh_method = "refine"`. 형상 표·결과 shape·보고서·ranking.csv(`mesh_method`, `refine_h_mm`, `elem_ratio_ref`)에 표시 | 사용자 요구 5 |
| C2-D-23 | **경고 `MESH_REFINED`**: "<이름>: 기본 3 mm 메시에 실패해 {국부|전역} 세분화(h {h} mm{, 면 n개})로 메시했습니다. 요소 수 기준 대비 ×{r}. 요소 크기가 기준 메시와 달라 컴플라이언스에 메시 의존 오차가 섞입니다(작은 개선율은 해석 차이일 수 있음)" — prep·결과 머리·보고서 | 사용자 요구 6 |
| C2-D-24 | **수렴 점검(권장안, `refine.convergence.enabled: true`)**: 세분화 형상이 하나라도 있으면 그 형상들이 쓴 h_r 마다(국부는 최솟값 대신 **같은 면에 같은 Field 를 줄 수 없으므로 전역 h = h_l 의 대표값 = 세분화 형상의 평균 요소 크기**) 기준 d000 을 h_r 로 다시 메시·해석합니다(같은 하중·지지 규칙, 결과 캐시 `run/designs/d000_h<h>/` — 캐시 키에 gmsh·OCC 버전 포함(버전이 바뀌면 다시 메시·해석)). δ_e = C_ref(h_r)/C_ref(h) − 1 (ESL별)를 그 형상의 **메시 편향 추정**으로 결과·보고서에 표시하고, max|δ_e| > `convergence.tol`(null = `rank.ratio_tol`)이면 경고 `MESH_REFINE_BIAS` 를 냅니다. 선택 옵션 `convergence.same_h_baseline: false` — true 면 그 형상의 개선율을 C_ref(h_r) 기준으로 계산하고 원래 값도 함께 표시합니다. d000 이 Case 메시 기준(`source: case`)이거나 메시 입력이면 다시 메시할 수 없으므로 점검을 생략하고 info `REFINE_CONVERGENCE_SKIPPED` | 같은 형상을 두 크기로 풀 수는 없어서(기본 h 에서 실패) 기준 형상으로 민감도를 잼 |
| C2-D-25 | **결정성·불변**: 세분화 시도도 같은 입력·버전이면 바이트가 같습니다(C2-D-14 같은 조건). 사다리에 들어가지 않은 형상은 코드 경로가 기존과 같고 `size_fields` 키도 없으므로 v0.15.x 와 바이트가 같습니다. 이어하기 해시는 `ladder`·`refine` 설정 해시를 mode ≠ cad 일 때만 포함합니다(C2-D-15) | V-C2-8 유지 |
| C2-D-26 | **(v0.16.3) freeform** = CAD 면 경계를 따르지 않는 이산 재메시: OCC BRepMesh 삼각화(`remesh.linear_deflection_mm`) → `classifySurfaces`(`remesh.feature_angle_deg`·`curve_angle_deg` 60 — 날카로운 모서리·비드 접힘 유지) → `createGeometry` → 4각 우세 재메시(h). **gmsh OCC 면 메싱(면 매개변수화)을 쓰지 않음** — periodic·퇴화 면이 막지 못함. `remesh_file(freeform=True)` = 재메시 R2(CAD 단계 구멍 메움)를 끔(`compare.freeform.hole_fill` false). 경고 `MESH_FREEFORM`(원 형상 대비 최대 편차, 지름 < `small_hole_factor` × h 구멍 수, 메시에서 사라진 구멍 수 = 경계 고리 수 차이). 모드 `compare.mesh.mode: freeform`(요청 `mesh_mode`) = cad 없이 `[freeform, tria]`, 성공 `mesh_method = remesh`. auto 사다리에서 성공 = `fallback`(+ `fallback_stage`) | 사용자 2026-11-09 지시 |
| C2-D-27 | **(v0.16.3) 면 실패 판정**: cad 실패 기록에 실패 면(`face.key`)이 있고 (면 종류 ∈ `compare.mesh.face_fail.types` [Sphere] 또는 오류 문구에 `patterns` [periodic surface, closed loop, degenerate]) 이면 **면 실패** — 요소를 잘게 해도 같은 면 매개변수화가 실패하므로 `face_fail.skip`(refine_local·refine_global)을 건너뜀(`SKIPPED reason face_fail`, info `MESH_FACE_FAIL`). 시간 초과·크래시(면 기록 없음)·면 기록은 있으나 종류·문구가 안 맞는 실패(크기·품질 문제)는 예전대로 세분화. defeature 단계는 면 실패일 때 **실패 면 표적**(`defeature_stage.targets` = 실패 면 bbox 키)을 추가: 실패 면을 품은 닫힌 묶음(딤플·구 캡, bbox 대각 ≤ `feature_max_mm`)은 기존 기준과 무관하게 평탄화(`target: true`). 그 밖은 기존 `compare.defeature` 기준 그대로. **이슈 #53 BatchMesher param 의 수치(eq_diam < 8·flanged 1.5 등)는 쓰지 않음**(사용자 2026-11-09) | 실측: v0.16.2 는 같은 면 실패를 세분화 5회로 되풀이 |
| C2-D-28 | **(v0.16.3) tria = OCC 삼각형 폴백(사다리 마지막)** `esl/doe/mesh_tria.py tria_file`: BRepMesh 삼각화(편차 `tria.deflection_factor` × h = 0.9 mm ≈ 3 mm CAD 메시 자체 현 편차, 각 45°) → 노드 병합(`merge_tol_mm`) → 적합 최장 변 분할(변 ≤ `split_factor` × h) ↔ 같은 평면 안 Delaunay 뒤집기 → 짧은 변 붕괴(< `collapse_factor` × h, 둘레 법선 산포 ≤ `collapse_deg` 인 매끈한 면 안 노드만) → 평면 안 접선 평활 → 재분할. gmsh 2D 메싱·이산 재메시 **모두 쓰지 않음**. 충실도 = C2-D-13 지표(S = 같은 BRepMesh). 경고 `MESH_TRIA_FALLBACK` 항상. 삼각화 없는 면 = 정리 끄고 재시도 → `allow_missing_faces` 면 경고 `MESH_TRIA_HOLES`(면 id) 후 계속, 그 때문에 메시가 끊기거나 끄면 `CAD_INVALID`(면 id). 요소 상한 = `refine.max_elems`. 기본 순서: 면 실패 → `cad → freeform → (freeform 이 REMESH_FIDELITY 일 때만) defeature → tria` | 사용자 2026-11-09 "마지막 단계는 사실상 실패하지 않게" |
| C2-D-29 | **(v0.16.3) 단계 시간 몫**: 단계 상한 = 남은 예산(`refine.total_timeout_s` − 누적) − Σ(뒤에 실제로 돌 단계의 `refine.stage_share` × 예산). 앞 단계가 몫을 덜 쓰면 뒤로 넘어가고, 어떤 단계도 뒤 단계 몫을 먹지 못함. 시도 제한 시간 = min(단계 제한 시간, 단계 상한 − 그 단계에서 쓴 시간). 남은 단계 몫 < `min_attempt_s` 면 그 시도·단계는 `SKIPPED reason stage_time`. cad 시도도 자기 몫(기본 0.3 × 3600 = 1080 s, 이전 1800 s)까지만. tria 는 단계 몫 판정 없이 남은 예산 전체(시간 초과 = 예산 소진 시만). 새 키 `stage_share`·`min_attempt_s` 는 이어하기 해시에서 뺌 | v0.16.2 실측: 세분화가 3003 s 를 써 마지막 재메시가 596.563 s 에서 끊김 |
| C2-D-30 | **(v0.16.3) 단계별 기록·문구**: 형상 행·mesh.json `stage_times = [{stage, outcome READY|FAILED_MESH|SKIPPED, seconds, tries, reason?, code?, timed_out?}]`(시도 순서, 같은 단계 묶음). 사다리 실패 문구 = `[단계별: cad 실패 412.3 s → refine_local 건너뜀(면 실패 — 세분화로 풀리지 않음) → freeform 실패(시간 초과) 720.0 s → tria 실패 58.1 s]` + 기존 `MESH_LADDER_FAILED`(작업 실패 문구 500자 상한에 잘리지 않도록 앞에) | 어디서 멈췄는지 사용자가 바로 봄 |
| C2-D-31 | **(v0.16.3) STEP 라벨 안 읽음** `compare.mesh.occ_import_labels: 0`(④ 프로필만, gmsh `Geometry.OCCImportLabels`): gmsh 4.13 의 STEP XCAF 라벨 처리가 면 수에 초선형(합성 1915 면 234 s → 5.4 s, 266 면 2.1 s). 세션·면 폴백·사다리 시도마다 STEP 을 다시 읽으므로 큰 형상에서 누적됨. 형상·태그·mesh.npz 는 같음(regress 바이트 동일), mesh.json `options` 에 기록하지 않음(③ 은 키 없음 → 그대로) | 실측 |
| C2-D-32 | **(v0.17.4) cad_relaxed** = cad 첫 gmsh 세션이 면 실패(_FaceFail)면 **면 폴백(면마다 최대 12단계, 단계마다 STEP 재가져오기) 전에** 모델 전체를 ③ 옵션으로 **1세션** 다시: `compare.mesh.cad_relaxed` 의 `occ_fix_small 0`·`curvature_n 12`·`min_size_factor 0.2`(= `bead_doe.mesh` 기본) + **구멍 메움 끔**(`defeature: false` — 이슈 #63 실측: 정리 끔 + 구멍 메움 끔 = 228,857 요소 1 성분 120 s, 구멍 메움 켬 = 4 성분). 나머지 ④ 프로필 키는 그대로, 면 폴백 없음. 채택 = 품질 오류 없음(`MESH_DISCONNECTED` 포함) ∧ (`fidelity` true 면) 같은 가져오기 옵션의 원 STEP OCC 삼각화 대비 hausdorff ≤ `remesh.fidelity.fail_mm`. 채택 → 형상 행 `mesh_method cad`·`mesh_path cad_relaxed`·`cad_relaxed{overrides, face, first_error, fidelity, seconds, cad_seconds}`·`stage_times [cad 실패, cad_relaxed 성공]`, mesh.json `cad_relaxed`·`options` = 실제 쓴 옵션, 경고 `MESH_CAD_RELAXED`. 실패 → 기존 면 폴백·사다리 그대로(`stage_times` 에 cad_relaxed 실패 줄). cad 가 **시간 초과**로 끝났고(자식이 cad_relaxed 에 못 감) C2-D-35 로 면 실패면 부모가 같은 시도를 1회(`direct` — 그 세션만, 제한 = min(mesh.timeout_s, 남은 예산 − 뒤에 실제로 돌 단계 몫), `cad_relaxed.after_timeout`). | 실 STEP: ③(정리 끔·곡률 12·최소 0.2 h) 단일 세션은 성공, ④ 의 OCCFix 가 Sphere 극점 퇴화 모서리를 지움 |
| C2-D-33 | **(v0.17.4) 대형 모델** = STEP 본문의 `ADVANCED_FACE`·`FACE_SURFACE` 수 > `compare.mesh.large_faces`(1000) 또는 `large.periodic_types`(Sphere → `SPHERICAL_SURFACE`) 면이 있음(gmsh 없이 셈 — 결정적, BREP 은 판정 안 함). 대형이면 (1) cad 자식의 면 폴백 세션 수 ≤ `large.fallback_sessions`(3, 0 = 상한 없음) — 넘으면 FAILED_MESH(실패 면 기록 → face_fail), (2) auto cad 제한 ≤ `large.cad_share`(0.15) × `refine.total_timeout_s`(남은 시간은 C2-D-29 대로 freeform·tria 로). **세션 재사용(재가져오기 없이 면만 다시 메시)은 하지 않음**: periodic 순서의 앞 단계(nofix·split·fill·small)와 relax 는 모두 메싱 전에 OCC 모델(정리·작은 형상 처리·면 대체)을 바꾸고 gmsh 에는 되돌리기가 없어 재가져오기만이 원 모델을 돌려줌; 재가져오기 없이 되는 알고리즘 단계는 periodic 순서의 맨 뒤라 줄일 시간이 거의 없음; 새 세션은 태그·노드 번호가 결정적이라 v0.14.1~ 면 폴백 결과 바이트를 지킴 → 상한으로 대신함. 행 `large{reason, n_faces, periodic}`·경고 `MESH_LARGE_MODEL`(사다리·cad_relaxed 행에만). | 실측 최악 47~60 분/형상 |
| C2-D-34 | **(v0.17.4) 자식 제한**: kind cad ∧ `compare.mesh.child_margin_s`(30, ④ 프로필) → job `child_timeout_s` = spawn 제한 − min(여유, 10 %), `loop_timeout_s` = spawn 제한 − 2 × 여유(면 폴백 반복 상한, mesh.timeout_s 보다 작으면 그 값). 자식 감시 타이머가 `child_timeout_s` 에 mesh_error.json(시간 초과 문구, 실패 면 = 첫 실패 면 → mesh.log 마지막 gmsh 'Meshing surface N (종류' — 첫 가져오기 면 목록으로 bbox key) + `progress{sessions, n_faces}`·`cad_relaxed` 를 쓰고 종료코드 3 — gmsh 2D 가 한 면에서 멈춰도 부모 spawn 이 죽이기 전에 기록. 감시 자식만 gmsh Terminal 1(mesh.log). 정상 결과 무관 | 이전: spawn 1080 s < 자식 1800 s → 기록 없이 죽어 face_fail 이 안 켜지고 refine_global 이 720 s 몫을 다 씀 |
| C2-D-35 | **(v0.17.4) 시간 초과도 면 실패**: cad 실패가 시간 초과이고 C2-D-27 이 못 정하면, 부분 기록(`face`·`log_face`) 또는 mesh.log 마지막 면의 종류 ∈ `face_fail.types` ∪ `fallback.periodic_types` 이거나 로그·문구에 `face_fail.patterns` → 면 실패(`reason timeout`) → 세분화 건너뜀. 근거 없음 → 예전처럼 세분화 | 같은 실측 |
| C2-D-36 | **(v0.17.4) 경로 기록**: `stage_times` 에 단계 `cad_relaxed`(자식 안 실패 = cad 초에서 뺀 별도 줄), 경고 1줄 `MESH_CAD_RELAXED`/`MESH_LARGE_MODEL` 끝에 `[단계별: …]`. 워커 `COMPARE_SHAPE_KEYS` 는 이 판에서 안 바꿈(v0.17.2 소유) — API 는 `stage_times`·경고로 경로를 봄, 새 행 키(`mesh_path`·`cad_relaxed`·`large`)는 compare.json 에만 | 소유권 |
| C2-D-37 | **(v0.17.4, 이슈 #63) 구멍 메움 트랜잭션**: `_session` 이 구멍 메움 전 OCC 서명(차원별 개수 + 면 bbox 키)을 잡고, `DEFEATURE_SKIPPED`(처리 중 예외)인데 서명이 바뀌었으면 STEP 을 다시 가져와(nofix_face 다시 적용) 구멍 메움 없이 메시 — `defeature.reverted`·`DEFEATURE_REVERTED`. 예외 전 변경이 없으면 그대로(정상 경로 바이트 불변). **nofix_all 은 구멍 메움 없이**. `MESH_DISCONNECTED` 안내 = 원인별(구멍 메움 실패·되돌림 → `compare.defeature.enabled false`, OCC 정리 켬 → `occ_fix_small 0`, 그 밖 = 예전 `occ_sew_faces 1`) | 실측: "Curve loop is not closed" 로 실패하며 4 성분, 안내가 원인과 다름 |
| C2-D-38 | **(v0.17.4, 이슈 #63) nofix_face 대응**: 정리 뒤 bbox·넓이 엄격 대응 후보 0개면, 같은 종류 ∧ 정리 뒤 bbox(± bbox_tol) 안 ∧ 넓이 ∈ [넓이 / `nofix.area_grow_max`(1000), 넓이] 후보가 정확히 1개일 때 그 면(정리가 키운 조각) | 실측: 면 2824 0.08 mm² → 63.53 mm²(완전한 구) — 후보 0개 |
| C2-D-39 | **(v0.17.4) 진행 줄**: BD_MESH0 단계 로그에 사다리 단계마다 `[d001 이름] 사다리 <단계> 시작|건너뜀(면 실패) · 누적 N s`, 하위 프로세스(cad·세분화·cad_relaxed) 대기 중 `compare.mesh.heartbeat_s`(60) 마다 `… <단계> 진행 중 N s — <mesh.log 마지막 [mesh_fallback]·[cad_relaxed] 줄>` | 실측: 44 분 무출력 |
| C2-D-40 | **(v0.17.4) 시도 로그 보관**: keep_tries false 라도 지우는 시도 폴더의 `mesh.log`·`mesh_error.json` 과 cad 의 것을 `mesh/attempt_logs/<try_n|cad>.<파일>` 에 남김(형상 시작 때 이전 실행분 삭제) | 실측: freeform 1504 s 시간 초과 기록이 지워짐 |
| C2-D-41 | **(v0.17.4) 형상 실패 차단**: 비교 형상(기준 제외) 중 READY 가 `compare.min_ready_shapes`(1, 0 = 안 막음)보다 적으면 compare.json·input.json 을 쓴 뒤 BD_MESH0 실패 `COMPARE_NO_SHAPES`(첫 실패 형상 단계별 문구). 일부만 실패면 READY + 경고 맨 앞 `COMPARE_SHAPES_FAILED: 비교 형상 k/n개 메시 실패 — 비교에서 빠짐: <id 이름 코드>…` | 실측: n_failed 1 인데 ok — 비교 대상 1/2 로 READY |
| C2-D-42 | **(v0.17.4) freeform 삼각화 편차** `compare.freeform.angular_deflection_deg`(20, null = remesh 값)·`linear_deflection_mm`(null = remesh 0.05). remesh 의 각 5° 는 곡면(구·원통·토러스·BSpline)이 많은 STEP 에서 BRepMesh 삼각형이 폭증하고 `classifySurfaces` 가 초선형 — 합성 105 면 판: 5° = 26.4만 개·분류 36 s·freeform 70.5 s·hausdorff 0.550 mm·패치 179 / 20° = 3.8만 개·1.6 s·16.7 s·0.389 mm·94·quad 1.0. 합성 1915 면 판 5° = 메모리 초과(2.3 GB 에서 강제 종료). 현장(4,832 면, Sphere 99·Cylinder 1,504·Torus 640·BSpline 1,185)의 freeform 1,504 s 시간 초과와 같은 원인으로 판단. 충실도 기준 S 도 같은 삼각화(선 편차 0.05 mm 유지) | 이슈 #63 ⑤ |
| C2-D-43 | **(v0.18.2, 이슈 #63 2026-11-12 진단) cad_relaxed 파라미터 재검토 — 기본값 유지**(`occ_fix_small 0`·`curvature_n 12`·`min_size_factor 0.2`·`defeature false`): 현장 요소 552,349 개(h 3 mm 예상 ~20만의 2.7배)는 곡률 세분(12/2π)이 작은 반경 필렛·원통(Cylinder 1,504·Torus 640)에서 최소 0.2 h(0.6 mm)까지 내려간 결과로 보이나, 그 경로가 현장에서 2D 를 끝낸 **유일한 성공 후보**(201 s)였고 실 STEP 없이 바꾸면 그 성공을 잃을 수 있음. 합성 면 공유 다딤플 고체(390 면, 구 384, R 8)에서는 0.2/12 = 57,633 요소(면적/h² 추정 ≈ 53.8k 의 1.07배), 0.5 = 57,633, 곡률 6 = 57,551, 곡률 0·0.8 = 57,551 — 차이 없음(작은 반경이 없음). 실제 병목은 요소 수가 아니라 후처리(충실도) 비용이었음(C2-D-45·46: 1,094.7 s → 22.1 s). 현장 요소가 계속 문제면 설정으로 `min_size_factor 0.5` 를 먼저 시험(키는 그대로 거울) | 실측(scratchpad rxparam) |
| C2-D-44 | **(v0.18.2) freeform 면별 이산 면** `compare.freeform.surfaces`: `occ_faces`(기본) = OCC 삼각화(importStl)를 **OCC 면마다 별도 이산 면**으로, OCC 모서리 선분(importStl 1D)을 **이산 곡선**(공유 경계)으로, 곡선 끝 노드를 이산 꼭짓점으로 넣고 `createGeometry` — `classifySurfaces` 를 부르지 않음(비다양체 모서리 'one edge is incident to 3 triangles' 없음). 노드 병합 = `merge_rep`(merge_nodes 와 같은 대표 — 충실도 기준 S_X 와 같은 노드 순서). 한 면 안쪽에만 있는 곡선(원통 이음선)은 경계에서 뺌. 모서리 자료가 삼각화와 안 맞으면(선분 노드가 삼각형에 없음·한 선분이 다른 두 모서리·사슬 갈래·모서리 안 노드가 다른 모서리 끝·면 경계 선분이 어느 모서리에도 없음) `topology mesh`(gmsh `createTopology` 가 면 인접으로 곡선), 면별 모델 자체가 실패하면 `[freeform] … → 면 분류` 로그 뒤 v0.18.1 면 분류(`remesh.surfaces classify`, `occ_faces_error`). `classify` = v0.18.1 그대로. mesh.json `remesh` += `surfaces`·`topology`(·`topology_why`)·`n_curves`, `n_patches` = OCC 면 수. 경고 `MESH_FREEFORM` 문구는 'CAD 면 경계를 따르는 freeform …'. **성공 사례 출력 변경 근거**: 면 경계를 따르므로 요소 배치가 예전(특징각 30° 패치)과 다름 — 합성 아치 판(비다양체): 예전 5 패치·5,582 요소·hausdorff 0.044 mm → 4 면·5,595·0.046, T 판 4,514 → 4,491, 기존 사다리 시험(test_mesh_ladder_v0163·test_mesh_remesh) 그대로 통과. 합성 1915 면 판: 예전 freeform `REMESH_CLASSIFY_FAILED`(72.9 s) → 성공 225.8 s·97,817 요소·quad 1.0·hausdorff 0.427 mm·1 성분(tria 234,721 삼각형 대신 4각) | 이슈 #63 진단 ③ |
| C2-D-45 | **(v0.18.2) cad_relaxed 분리** `compare.mesh.cad_relaxed.isolate`(true)·`timeout_s`(900, null = mesh.timeout_s)·`fidelity_samples`(20000): 첫 cad 시도(사본 설정 `cad_relaxed.defer`)의 자식은 첫 면 실패에서 cad_relaxed 를 돌리지 않고 `mesh_error.json` `cad_relaxed: {deferred, first_error, face, cad_seconds}` 만 남긴 뒤 면 폴백을 계속 → cad 가 실패하면 **부모가 자기 하위 프로세스·자기 시도 폴더**로 1회(direct, 제한 = min(timeout_s, 남은 예산, 남은 예산 − 뒤 단계 몫)) — auto 사다리와 mode cad 모두. 성공 행 `cad_relaxed.isolated` true, `after_timeout` = cad 가 시간 초과였는가, mesh.json `cad_relaxed` 는 자식 기록(ok·overrides·first_error·face·fidelity…) 유지. 세분화·defeature 시도의 cad 자식은 예전처럼(정의 안 바뀜). **끊김 기록**: isolate false(예전 경로)에서 감시 타이머가 cad_relaxed 후처리 중 자식을 끝내면 `_run_record` 가 `interrupted`·`seconds`(시작부터)·`cad_seconds` 를 적고, 부모는 cad_relaxed 행을 `FAILED_MESH`·`timed_out`·`interrupted`·실제 초(없으면 cad 초 − 첫 세션 초)로 적은 뒤 **부모에서 다시 1회** — v0.18.1 의 '0.0 s 실패'(tried 만 보고 재시도 안 함) 없음. 같은 단계가 재시도 끝에 성공하면 `stage_times` 성공 줄에 `timed_out` 을 남기지 않음(attempts 에 있음). **충실도 표본**: cad_relaxed 충실도의 양방향 표본 = min(remesh.fidelity.samples_max, fidelity_samples) 고정 간격 — 정확도 기준: 표본 최대 거리는 전체 최대의 하한이므로 채택 판정(hausdorff ≤ fail_mm 1.5)은 표본 간격 안 국소 돌출을 놓칠 수 있음; 합성 390 면 고체에서 20,000(×2) 표본 hausdorff 0.538932 mm = 전체(257,156 점) 0.538932 mm(같음), p95 0.37 vs 0.19(표본이 성김 — 판정에 안 씀) | 이슈 #63 진단 ② |
| C2-D-46 | **(v0.18.2) 충실도 정확화·tria 상한**: (1) `mesh_remesh._dist_to_tris` 정확화 반경을 전체 최대 r 하나 대신 삼각형 r_t 크기 묶음(중앙값 × 2^j)마다 따로 찾아 묶어서 계산 — 같은 후보 상위 집합(진짜 최근접 포함)·같은 식이라 **결과 비트 동일**(아치·T·390 면 고체 × 분할 상한 2종 `np.array_equal`), 덜 나뉜 큰 삼각형(표본 상한이 분할 상한 4 × 표본을 낮춤)이 있을 때 점마다 O(M) Python 반복이 사라짐: 390 면 고체 1,013.9 s → 1.1 s(cad_relaxed 전체 1,094.7 → 22.1 s) — 현장 cad_relaxed 후처리 지연의 원인으로 판단. (2) tria 300 s: 합성 1915 면 판 tria 73~91 s 중 `collapse_short` 43 s·`flip_planar` 19 s(Python 반복, 출력 바이트를 바꾸지 않고 줄이기 어려움), 충실도 4.5 s — 현장(4,832 면)은 누적 ~550 s 에서 tria 고정 상한 300 s 에 끊겼고 예산은 ~3,000 s 남아 있었음 → **대형 모델(C2-D-33)만** `compare.mesh.large.tria_timeout_s`(900, null = tria.timeout_s) 로 tria 제한 = max(tria.timeout_s, 이 값)(여전히 남은 예산 안). 대형 아님 = 300 s 그대로 | 이슈 #63 진단 표(tria 300.1 s) |

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
| R5′ | (v0.18.2 C2-D-44, freeform `surfaces occ_faces`) R5 대신 OCC 면별 이산 면·OCC 모서리 이산 곡선 → `createGeometry`(실패 시 R5) | `REMESH_CLASSIFY_FAILED` |
| R5 | `classifySurfaces(radians(feature_angle_deg), boundary=True, forReparametrization=True, curveAngle=radians(curve_angle_deg))` → `createGeometry()` → synchronize. 패치 수 기록 | `REMESH_CLASSIFY_FAILED` |
| R6 | `gmsh_options(h, profile)` 그대로(3 mm·Min 2.4·곡률 0·ExtendFromBoundary 0), `Mesh.RecombineAll = recombine`, `Mesh.Algorithm` = `algorithms` 를 차례로 **모델 전체** 재시도(면 폴백 없음) → `generate(2)` | `REMESH_FAILED`(마지막 오류 문구) |
| R7 | `mg._extract` → `mg.build_mesh` → `mq.summarize` | – |
| R8 | 충실도(C2-D-13) | `REMESH_FIDELITY` |
- 사용자 문구(`resources/doe_messages.json`): `REMESH_FAILED` "삼각형 재메시에 실패했습니다: {첫 오류}. 특징각(remesh.feature_angle_deg)을 키우거나 메시 파일로 올리세요" / `REMESH_CLASSIFY_FAILED` "면 분류(특징각 {deg}°)에 실패했습니다" / `REMESH_STL_EMPTY` "STEP 에서 삼각화를 만들지 못했습니다(면 없음)" / `REMESH_FIDELITY` "재메시가 원 형상과 최대 {mm} mm 다릅니다(> {fail} mm)" / `REMESH_UNAVAILABLE` "이 gmsh 버전({ver})은 삼각형 재메시를 지원하지 않습니다".
- 실패는 모두 형상 상태 `FAILED_MESH` + code 입니다. auto 에서 재메시까지 실패하면 code = 재메시 코드이고 `cad_error` 를 함께 남깁니다. 사용자 문구는 원래 CAD 오류를 함께 보입니다: `MESH_LADDER_FAILED` "CAD 메시 실패: {cad} → {세분화·재메시}도 실패: {마지막 오류}"(시도한 단계만), 모두 건너뛰었으면 `MESH_LADDER_SKIPPED` "CAD 메시 실패: {cad} → 세분화·재메시는 건너뜀({사유})". 기준 d000 실패 시 작업 failure 메시지 = "기준 형상 메시 실패: " + 이 문구, 형상 표 실패 행 문구·툴팁(시도 목록 포함)도 같은 틀(v0.16.0 검증 수정).
- 연결: `mg._child` 에 `if job.get("kind") == "remesh": mesh_remesh.remesh_file(...)` 몇 줄, `run_isolated(..., kind="cad")` 키워드 추가. mesh-sphere 가 건드리지 않는 함수입니다.

## 4A. 세분화 폴백 구현 위치 (C2-D-18~25)

- **Core 신규** `esl/doe/mesh_refine.py`: `plan(stage, prev_meta, h, cfg, avail_bytes) → [attempt…]`(예측·건너뜀 판정), `neighbor_faces(gmsh, keys, rings)`, `estimate_elems(face_areas, h, local_keys, h_l)`.
- **Core 추가** `esl/doe/mesh_gmsh.py`: 선택 cfg 키 `mesh.size_fields: [{keys:[bbox_key…], size_mm}]` 를 `_session` 에서 OCC 동기화 직후에 Field 로 적용(키가 없으면 아무것도 하지 않음), `quality()` 는 `mc["max_elems"]` 를 그대로 읽음(호출자가 refine 상한을 넣은 cfg 사본을 넘김). **mesh-sphere 병합 뒤에** `_session` 몇 줄만 추가합니다(충돌 영역이므로 선행 조건 유지).
- **Worker** `esl/doe/stages.py _cmp_mesh_shape`: 사다리 실행기(시도마다 `run_isolated`, 시도 폴더 `prep/shapes/<did>/mesh/try_<n>/`, 성공본을 `mesh/` 로 `atomic_replace` — mesh.json 은 맨 마지막에 옮김(중간에 멈추면 새 mesh.json 이 없어 성공으로 읽히지 않음). 시도 폴더는 성공이면 모두 지우고, 모두 실패하면 마지막 시도만 남김. `compare.mesh.keep_tries: true` 면 모두 남김(진단용, 기본 false)), `_cmp_refine_bias`(BD_BASELINE 뒤 d000 h_r 재해석, BD_POST 에서 δ 계산), `report_doe.py` 열·경고.
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
      keep_tries: false          # true = 시도 폴더 try_<n>/ 모두 남김(false = 실패 시 마지막 시도만)
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

**v0.16.3 추가 키**(C2-D-26~31, DEFAULTS·pydantic·yaml 2개 거울):

```yaml
bead_doe:
  compare:
    mesh:
      mode: auto                 # += freeform
      ladder: [cad, refine_local, refine_global, freeform, defeature, tria]
      face_fail: {enabled: true, types: [Sphere], patterns: [periodic surface, closed loop, degenerate], skip: [refine_local, refine_global]}
      occ_import_labels: 0
    refine:
      stage_share: {cad: 0.3, refine_local: 0.1, refine_global: 0.1, freeform: 0.2, defeature: 0.15, remesh: 0.2, tria: 0.15}
      min_attempt_s: 5.0
    freeform: {enabled: true, hole_fill: false, small_hole_factor: 1.0, timeout_s: null}
    tria: {enabled: true, deflection_factor: 0.3, angular_deflection_deg: 45.0, merge_tol_mm: 0.01, split_factor: 1.333,
           max_split_iters: 24, max_tris: 2000000, coplanar_deg: 1.0, flip_passes: 6, collapse_factor: 0.6, collapse_passes: 6,
           collapse_deg: 20.0, smooth_rounds: 4, smooth_iters: 5, allow_missing_faces: true, timeout_s: 300}
```
- 시험 전용 고장 주입 = 환경 변수 `ESL_TEST_MESH_FAIL`(cad·defeature·remesh·fidelity, spawn 자식에서만 — 설정 키 아님).

**v0.17.4 추가 키**(C2-D-32~34, DEFAULTS·pydantic·yaml 2개 거울, 이어하기 해시·base.json profile 밖 — 정상 결과 무관):

```yaml
bead_doe:
  compare:
    mesh:
      cad_relaxed: {enabled: true, occ_fix_small: 0, curvature_n: 12, min_size_factor: 0.2, fidelity: true}
      large_faces: 1000
      large: {periodic_types: [Sphere], fallback_sessions: 3, cad_share: 0.15}
      child_margin_s: 30.0
      heartbeat_s: 60.0          # C2-D-39
      cad_relaxed.defeature: false
      cad_relaxed: {isolate: true, timeout_s: 900.0, fidelity_samples: 20000}   # v0.18.2 C2-D-45
      large.tria_timeout_s: 900.0                # v0.18.2 C2-D-46
      fallback.nofix.area_grow_max: 1000.0   # C2-D-38
    freeform: {linear_deflection_mm: null, angular_deflection_deg: 20.0}   # C2-D-42
    freeform.surfaces: occ_faces   # v0.18.2 C2-D-44 (occ_faces | classify)
    min_ready_shapes: 1          # C2-D-41
  select:
    graph:
      limits: {max_elems: 600000}   # 250,000 → 600,000(beadgraph 계약 성능 상한 600k/300 s — 현장 ① 메시 267,470 요소가 TOO_LARGE, 분류 16 s·396 MB 실측). timeout_s 180 유지
```
- 시험 주입 += `hang`(cad 시도에서 OCCFixDegenerated 1 이면 첫 Sphere 면에서 gmsh 형식 한 줄을 찍고 멈춤).
- 시험 주입 += `relaxed_slow`(v0.18.2 — cad 자식 안 cad_relaxed(direct 아님)의 충실도 비교에서 멈춤).

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
| V-C2-7 | **메시 입력 E2E**: STEP 3개 ④ 실행 → 각 `best/<did>/ch_r.rad` 를 메시 형상으로 다시 올려 ④ 실행 → 순위·score·ESL별 ratio 가 1e-9 안에서 같음. 혼합(기준 메시 + STEP 2) 실행·`COMPARE_MESH_METHOD_MIXED` 발생(cad vs 메시 입력 — 경고 존재 확인). Case 기준 + STEP(cad)만이면 미발생(`test_case_reference`) | `worker/tests/test_doe_compare_e2e.py` |
| V-C2-8 | 회귀: ③ `step` 메시·결과 바이트 불변, 기존 ④(mode cad, 그리고 cad 가 성공하는 auto) `mesh.npz`·`loads.npz`·순위 수치 불변(JSON 은 새 키 제외 비교), v0.15 스터디 이어하기 `input_sha256` 불변, ①②·select 시험 통과 | 기존 `tests/doe/*`, `worker/tests/test_doe_*` |
| V-C2-9 | API: source·part_id 검증, mesh rel 지정, 형식·크기·include·파트 오류, gmsh 없음 + 메시만 → 활성, STEP 포함 → 503, `mesh_mode` 값·`REMESH_UNAVAILABLE`, clone 업로드 누락 | `backend/tests/test_doe_compare_api.py` |
| V-C2-10 | 설정 거울: DEFAULTS = pydantic = example yaml 2개, 잘못된 값 거부 | `tests/pipeline/test_config.py` |
| V-C2-11 | 보고서: 메시 방식·충실도 열, 경고, 한계 절, HTML 이스케이프 | `tests/doe/test_report_doe.py` |
| V-C2-12 | UI: 토글·파트 ID 칸·datalist·확장자 기본값·묶음 놓기, 고급 설정 모드(비활성 사유), 결과 '메시 방식' 열·툴팁, 2560×1440·1920×1080 잘림 없음 | `frontend/__tests__/doe_compare_mesh.test.tsx`, mock |
| V-C2-13 | 실패 주입(monkeypatch: h > 2.5 면 특정 bbox 면 실패) → refine_local 0.75 에서 성공, `mesh_method refine`·`refine.kind local`·faces·elem_ratio, `MESH_REFINED`. local 을 끄면 global 2.4 에서 성공. 국부 성공의 요소 수 < 전역 | `tests/doe/test_mesh_refine.py`, `tests/doe/test_step_compare.py` |
| V-C2-14 | 상한: `refine.max_elems` 를 작게 → 해당 단계 `REFINE_SKIPPED_LIMIT`(reason elems) 후 다음 단계·remesh. 가용 메모리 monkeypatch → reason memory. `total_timeout_s` → reason time. cad 시간 초과 주입(넓이 없음) → 시도 제한 시간이 남은 예산으로 줄고 remesh 는 reason time, 총 시간 ≤ 예산(`test_ladder_time_budget_without_area`). 예측식 단위 시험(평판 면적/h²) | 같은 파일 |
| V-C2-15 | 정상 형상: 사다리 미진입, `size_fields` 없음 → gmsh 옵션 dict·`mesh.npz` 바이트가 v0.15.x 와 동일(V-C2-8 확장). 세분화 시도 2회 실행 → 바이트 동일 | `tests/doe/test_mesh_gmsh.py` |
| V-C2-16 | 수렴 점검: 합성 평판 d000 을 h 와 h_r 로 풀어 δ 기록, tol 경계에서 `MESH_REFINE_BIAS`, same_h_baseline 개선율, Case 기준이면 생략 info, 캐시 재사용 | `tests/doe/test_step_compare.py`(통합 2026-11-04: 세분화 형상을 만들려면 cad 시도 실패 주입이 필요한데 워커 E2E 는 코어 단계를 spawn 자식에서 돌려 monkeypatch 가 닿지 않음 — 코어 단계 직접 실행으로 이동) |
| V-C2-17 | 설정 거울·검증(ladder 순서·factors·상한 관계) | `tests/pipeline/test_config.py` |
| V-C2-26 | (v0.16.3) 면 실패 → 세분화 건너뜀 → freeform 성공(합성 다딤플 판, 실패 주입 `ESL_TEST_MESH_FAIL=cad` — 그 판은 주입 없이도 cad 가 실패), `MESH_FREEFORM`·충실도·품질 지표; mode freeform(cad 없음) | `tests/doe/test_mesh_ladder_v0163.py` |
| V-C2-27 | (v0.16.3) 면 실패 판정 단위, freeform 충실도 실패(주입) → 실패 면 표적 defeature 성공 | 같은 파일 |
| V-C2-28 | (v0.16.3) gmsh 면 메싱·이산 재메시 모두 실패(주입) → tria 가 메시(READY, `MESH_TRIA_FALLBACK`), tria 적합·연결·충실도 | 같은 파일 |
| V-C2-29 | (v0.16.3) 단계 몫: 모든 시도 시간 초과 주입 → cad 제한 = 예산 × (1 − 뒤 몫 합), tria 몫 보장, 총 ≤ 예산, 문구 단계별 초 | 같은 파일, `test_step_compare.py`(v0.16.2 사다리 = 몫 0 이면 이전과 같음) |
| V-C2-30 | (v0.16.3) 정상 경로 바이트 불변: regress(mode 없음·cad·auto) 메시·하중·순위 동일 — auto 의 이어하기 해시만 기본 사다리 변경으로 다름(스냅샷 `mesh_ladder` 가 있는 기존 스터디는 같음) | `scripts/regress.py`(작업 폴더) |
| V-C2-31 | (v0.16.3, 수동 `ESL_TEST_BIG=1`) 약 1900 면 판: tria < 120 s·충실도 | 같은 파일 |
| V-C2-32 | (v0.17.4) 면 공유 다딤플 판(실제 gmsh — OCCFix 1 이면 Sphere 면 실패): cad_relaxed 1세션 성공·품질·충실도·`MESH_CAD_RELAXED`, 끄면 FAILED; 면 공유 없는 판은 `MESH_DISCONNECTED` 로 채택 안 함; 파이프라인 행 `mesh_path`·`stage_times` | `tests/doe/test_mesh_relaxed_v0174.py` |
| V-C2-33 | (v0.17.4) STEP 세기·대형 판정, 면 폴백 세션 상한, 대형 cad 제한 = cad_share × 예산 | 같은 파일 |
| V-C2-34 | (v0.17.4) 2D 멈춤 주입(hang): 자식이 spawn 전에 mesh_error.json(시간 초과 + 로그 면 Sphere) → 면 실패 → 세분화 건너뜀, 부모 cad_relaxed 성공 | 같은 파일 |
| V-C2-35 | (v0.17.4) 정상 경로 바이트 불변: regress(mode 없음·cad·auto) main 과 동일 | `scripts/regress.py`(작업 폴더) |
| V-C2-36 | (v0.17.4, 수동) 합성 1915 면 판(synth_many) 첫 성공 메시까지 시간 main 대비 | decisions.md |
| V-C2-37 | (v0.17.4) 구멍 메움이 형상을 바꾼 뒤 실패(주입) → 되돌림·1 성분·DEFEATURE_REVERTED, MESH_DISCONNECTED 원인별 안내 | `tests/doe/test_mesh_relaxed_v0174.py` |
| V-C2-38 | (v0.17.4) nofix_face 키운 면 대응(조각 0.08 → 구 63.53 mm²) | 같은 파일 |
| V-C2-39·40 | (v0.17.4) heartbeat·사다리 단계 줄, attempt_logs/cad.mesh_error.json | 같은 파일 |
| V-C2-42 | (v0.17.4) freeform 편차 설정 거울(DEFAULTS·pydantic·yaml) | `tests/pipeline/test_config.py`(_C2_KEYS freeform) |
| V-C2-41 | (v0.17.4) 비교 형상 전부 실패 → COMPARE_NO_SHAPES, min_ready_shapes 0 → 경고 맨 앞 COMPARE_SHAPES_FAILED | 같은 파일 |
| V-C2-43 | (v0.18.2 C2-D-45) 새 키 DEFAULTS·사본 defer, 끊긴 cad_relaxed 기록 → 시간 초과·실제 초(0.0 s 아님), 감시 타이머 모의 → mesh_error.json interrupted·seconds·cad_seconds | `tests/doe/test_mesh_v0182.py` |
| V-C2-44 | (v0.18.2 C2-D-45) isolate 파이프라인: cad 자식 deferred → 부모 cad_relaxed 성공(isolated, mesh.json 자식 기록 유지), mode cad 도 부모 1회, isolate false + 후처리 멈춤 주입(`relaxed_slow`) → 끊김 기록 + 부모 재실행 성공 | 같은 파일 |
| V-C2-45 | (v0.18.2 C2-D-44) 비다양체 모서리(아치 끝 세 면 공유) freeform: classifySurfaces 실패 모의에도 occ_faces 성공(4 면·OCC 모서리 곡선·품질 오류 없음), classify = REMESH_CLASSIFY_FAILED; face_model 공유 곡선 세 면·S_X 같음 | 같은 파일 |
| V-C2-46 | (v0.18.2 C2-D-46) 대형 모델 tria 제한 900 s, 대형 아님 300 s / 정확화 묶음 결과 비트 동일(수동 — decisions) | 같은 파일 |
| V-C2-47 | (v0.18.2, 수동) 합성 1915 면 판 사다리 시간 main 대비, regress(mode 없음·cad·auto)·sel_regress 바이트 동일 | decisions.md |

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
