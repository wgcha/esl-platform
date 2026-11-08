# 계약: 비드 직접 선택(select) 제약 완화 · 비드 안 형상(구멍·섬·체결 구멍) 처리 · 작은 형상 억제 메시 단계 · 공통 모듈 (SELECT_RELAX, v0.16.1)

- 상태: **확정** (2026-11-05). Q1~Q3 = 권장안 A 확정(사용자 2026-11-05, §14). 범위 A(④ 사다리 `defeature` 단계, §5A)·범위 B(공통 모듈, §5B) 추가(사용자 2026-11-05). 남은 질문 Q4·Q5(§14)는 권장안을 기본값으로 적었고, 답이 다르면 그 값만 바꾼다(구조 불변).
- 버전: **v0.16.1** (기준 main ef7545c = v0.16.0). migration **불필요**(§7.6).
- 관계: `esl_bead_select.md`(BEAD_SELECT, v0.15.0 — 이하 "BS")의 **변경 계약**. 이 문서에 없는 규칙은 BS 를 따르고, 충돌 시 이 문서가 우선. `docs/decisions.md` D-0.16-P2(고정 침범·품질 FAIL = 경고, 뒤집힘만 제외)를 구체화한다. §5A 는 `esl_compare_mesh_options.md`(이하 "C2")의 사다리(C2-D-18)·충실도(C2-D-13)·기록(C2-D-10)·`esl_step_compare.md` SC-D-5(작은 형상 처리)의 **변경 계약**.
- ID 규칙: 결정 `SR-D-n`, 시험 `V-SR-n`, 리스크 `R-SR-n`, 질문 `Q1~Q5`.
- 구현 갱신(2026-11-05 통합 release/v0.16.1): Core R1c 가 실제 Ch/R 사례로 더한 규칙과 통합 때 반영한 Core 제안을 SR-D-25~31, 실제 사례 그림 점검 결함 3건 수정을 SR-D-32~34 로 추가(§2 끝), V-SR-19 기준 갱신(§11), 설정 키 `select.island.ring_frac`·`compare.remesh.fidelity.warn_rel_cad`(§4.4), 정보 수준 경고(`level: "info"`)·새 코드(§10).
- 구현 갱신(2026-11-05 어려운 사례 H1~H4 수정, release/v0.16.1): 시험 엔지니어 H1~H4(X 교차·3단·근접·밀집+슬롯) 결함 9건 수정을 SR-D-35~43, 메시 출처 무관 공통 모핑 코어를 SR-D-44 로 추가(§2 끝), 설정 키(§4.4), 새 코드(§10), V-SR-28(§11). 재사용 문구 = "OK 만 재사용"(SR-D-31·§7.4).

### 사용자 확정 (2026-11-05, 변경 금지)
5. **Q1~Q3 = A**: 경고 안이 1위여도 순위 유지 + ⚠ + "경고 없는 최상위" 1줄 / 보스 링 ρ 3 mm·블렌딩 8 mm / 기본 범위는 넓히지 않음(feasible 만).
6. **"어떻게든 메시를 성공시키자"**: ④ 자동 사다리에 작은 형상 억제(defeature) 단계 — 순서 `cad → refine_local → refine_global → defeature → remesh`, `compare.mesh.ladder` 로 순서·사용 변경. BatchMesher 기준(holes table, beads_suppression `minimal_beads_height 2`, surface fillet, flanged_suppr)을 gmsh/OCC CAD 단계에서. 원 STEP 대비 편차(억제 영역 따로), `mesh_method = defeature`, 억제 목록, 경고 `MESH_DEFEATURED`. CAD 로 성공하는 형상은 바이트 불변.
7. **"이 기술이 전반적으로 통용돼서 쓰이도록"**: CAD 단계 억제·인식 = 공통 모듈 `esl/geom/defeature.py`(③ STEP 스터디 메싱·④ 형상 비교·향후 STEP 모핑), 메시 단계 섬·구멍 분류 = 공통 모듈 `esl/mesh/features.py`(select·v0.16.2 P3 자동 탐지 초기 선택·④ 메시 입력 진단). 기존 `mg.defeature` 는 얇은 래퍼(바이트 불변).

### 사용자 확정 (2026-11-04, 변경 금지)
1. **고정 침범**: 안 제외하지 않고 경고만. 고정 노드도 모핑대로 같이 움직인다. 안에 ⚠ 배지 + "고정 노드 n개, 최대 x mm 이동". 보고서·받기 rad 사본에 "체결 위치 어긋남" 경고. 설정 `select.fixed_policy: warn`(기본) | `skip`.
2. **품질 FAIL**: 경고만. 뒤집힘(INVERTED) 안만 제외.
3. **자유도 확대**: 범위 상한 완화, 막는 조건 축소 — 현재 막는 조건 전부를 목록으로 만들고 조건마다 유지/경고 전환을 결정표로(§3).
4. **비드 바닥 안 형상**(실제 Ch/R — 관통 구멍·딤플·버링·체결 구멍 다수):
   - 관통 구멍(자유 모서리): 비드 경계·열린 경계 판정에서 뺀다(지금은 W 가 꺼짐). 구멍 둘레는 바닥과 함께 이동.
   - 딤플·버링(선택 안 한 섬): 비드 경계에서 뺀다 — 경계는 바깥 고리만(지금은 W 가 딤플 둘레까지 오프셋). 섬은 바닥과 같은 변위로 강체 이동(지금은 바닥만 내려가 형상이 찢어짐). 클릭 확장 시 자동 포함.
   - 체결 구멍: 기본 = 바닥과 같이 이동 + 1번 경고. 비드별 옵션 "체결 구멍 둘레 고정" = 링(반경 설정값)은 제자리, 바깥은 블렌딩해 보스처럼 남김.

## 0. 현황 (ef7545c, 근거 파일:행)

| # | 항목 | 근거 | 현재 동작 | 문제 |
|---|---|---|---|---|
| C1 | 자유 모서리 → 열린 경계 | `esl/doe/bead_select.py:510`(`free = nin≥1 ∧ edge_count==1`), `:547`, `:780`(`bd.open = free ∨ 열린 고리 ∨ 고리 없음`) | 비드 요소가 자유 모서리를 **하나라도** 가지면 `SELECT_OPEN_BOUNDARY` | 바닥 관통 구멍 1개로 W 비활성(`:919` `w_enabled = not open`), 백엔드 표도 W 행 없음(`backend/esl_platform/api/services/doe_select.py:343-345`) |
| C2 | 사면 BFS 가 섬으로 샘 | `bead_select.py:707-720`(F 에서 비평행 이웃을 사면으로) | 딤플·버링 벽(비평행)이 사면 `S_auto` 로, 딤플 바닥(평행)은 멈춤 요소 → 비드 밖 | 딤플 바닥이 비드 밖이라 그 둘레가 **안쪽 경계 고리**가 됨(`:734-738`) |
| C3 | 안쪽 고리 = 경계 수준 0 | `_slope_levels` `:867`(앵커 0 = 경계 노드 전부), `_depth_basis` `:1172-1186` | 딤플 둘레 고정(0), 딤플 벽은 경계↔바닥 보간 | D 를 바꾸면 바닥만 내려가고 딤플 바닥은 제자리 → 벽이 늘어나 찢어짐 |
| C4 | 폭 기저·폭 측정이 모든 고리 | `_width` `:929-946`(ê 를 모든 고리에), `:955-961`(교차 선분 = 모든 고리), `_w_field` `:1105-1116`(kNN = 모든 고리 노드) | 안쪽 고리도 ê 방향 오프셋, 반직선이 딤플 고리에 맞아 w_j 가 짧게 측정 | W 를 바꾸면 딤플 둘레까지 오프셋, W_nom 왜곡 |
| C5 | 비드 안 고정 노드 → 기본 체크 해제 | `bead_select.py:841-846`(`SELECT_FIXED_IN_BEAD`), `params_table` `:1157`·`:1166`, 백엔드 `doe_select.py:321-329`·`:338`·`:348` | 체결 구멍이 바닥에 있으면 그 단 D·비드 W 기본 해제 | 실 Ch/R 거의 모든 비드가 해제 |
| C6 | 고정 침범 → 안 제외 | `design_state` `:1365-1382`(`:1374` 침범 우선 → `SKIPPED_FIXED`), `paicad_io.py:369-370`, `stages.py:504-516`(bd_eval 스킵 문서) | 침범 안 = 실행 안 함 | 확정 1 위반 |
| C7 | 품질 FAIL → 안 제외 | `design_state` `:1378-1379`, `mesh_quality.py:201`(`over_limit`) | 새 Fail 비율 > 0.01 → `FAILED_MESH` | 확정 2 위반 |
| C8 | 침범 원인 자료는 스킵 칸만 | `stages.py:2253-2255`(`fixed_viol` = `SKIPPED_FIXED` 칸만), 백엔드 `doe.py:732-744`(있으면 전달) | 경고 안에는 원인 자료 없음 | 배지 문구 근거 없음 |
| C9 | 블렌딩 반경 자동 자르기 | `_ranges_blend` `:1066-1084` | R_auto 를 고정 노드 앞에서 자름(`SELECT_BLEND_CLIPPED`) | 막지는 않음(완화책) |
| C10 | 기본 범위·feasible | `_ranges_blend` `:1039-1056`(D ±30 %, W ±20 %), `matrix.py:107-111`(lo ≤ 0 → 422, feasible 밖 → 경고만) | feasible = 기본 범위(같은 값) | 조금만 넓혀도 `RANGE_OUTSIDE_FEASIBLE` |
| C11 | 이어하기 해시 | `stages.py:421-426`(`_cfg_hash` 에 `select` 절 전체), `:2142-2147`(`_sel_cfg_sha`), `:2105-2109`(기저 재사용 조건), `:440-443`(안 sha = 선택 sha + 기저 sha) | 설정 키 1개만 늘어도 모든 select 안 해시 변경 | §7 대응 필요 |
| C12 | 선택 sha | `normalize_input` `:213-216`(비드 키를 기본값 채워 모두 씀), `selection_sha256` `:277` | 새 비드 키를 기본값으로 쓰면 기존 선택 sha 전부 변경 | §7 대응 필요 |
| C13 | 클릭 확장 | `frontend/src/view3d/select/grow.ts:16-41` | seed 법선 BFS 만 — 섬은 빈 구멍으로 남음 | 확정 4 "자동 포함" 없음 |
| C14 | 미리보기 배지 | `frontend/src/components/DoeThumbGrid.tsx:50`·`:70`(스킵·실패만 ⨯ 배지) | 경고 상태 없음 | 확정 1 배지 없음 |
| C15 | ④ 작은 형상 처리 = 구멍만 | `esl/doe/mesh_gmsh.py:269-401`(`defeature`: 면 내부 고리 중 `_is_hole` ∧ 넓이 < `min_hole_area_mm2` 메움 + 둘레 분할), 호출 `mesh_gmsh.py:776-778`(④ cad 세션)·`mesh_remesh.py:324-326`(재메시 R2) | 한 면에만 붙은 고리만, seam 을 지나는 구멍·여러 면에 걸친 구멍은 안 메움(v0.14.1 보수적). 필렛·비드·버링·좁은 띠 처리 없음 — `min_bead_height_mm` 은 기록만(`stages.py:854-855`, `report_doe.py:300`) | 확정 6 |
| C16 | 사다리 4단계 고정 | `mesh_refine.py:26`(`STAGES`), `backend/.../core/config.py:603`(`COMPARE_LADDER_STAGES`, `ladder max_length=4`), DEFAULTS `esl/doe/__init__.py:104`, `stages.py:1048`(`MESH_METHODS`), `:1119`(`LADDER_STAGE_LABEL`) | defeature 단계 없음 | 확정 6 |
| C17 | 해시·기록에 defeature 설정 전체 | `stages.py:1551-1552`(`prof_rec["defeature"]` = `compare.defeature` 전체 → base.json `profile`·`profile_sha256`), `_cmp_sha:1634-1652`(`profile` 이 keep 에) | 새 키를 기본값으로 넣기만 해도 모든 ④ 형상 해시·base.json 바이트 변경 | §7.7 대응 |
| C18 | 위상 도우미가 메싱 모듈 안 | `mesh_gmsh.py:191-266`(`_loop_info`·`_face_loops`·`_curve_points`·`_seam_points`·`_is_hole`·`_bbox_key`·`_key_near`), `bead_select.py:282-383`(`MeshIndex`·`mesh_index`), `:505`(`_loops`), `:567`(`_node_graph`) | ③·④·select 가 각자 모듈 내부 함수에 묶임 | 확정 7 |
| C19 | ③ 메싱 호출 | `stages.py:249`(③ 베이스라인 STEP), `:478`(③ 안 BREP) → `mg.run_isolated(..., c.cfg)` — `cfg["mesh"]` 에 `defeature` 키 없음 → 작은 형상 처리 안 함(`scenario.compare_cfg:314-316` 은 ④ 만 주입) | ③ 은 같은 세션 함수를 지나지만 꺼져 있음 | 확정 7(③ 기본 동작은 유지) |

## 1. 범위 / 비범위

| 범위 (v0.16.1) | 비범위 |
|---|---|
| 고정 침범·품질 FAIL 경고화(정책 키 2개), 뒤집힘 제외 유지 | 섬 자체 변수(딤플 깊이·위치) |
| 막는 조건 결정표(§3)와 그대로 반영 | 열린 경계(판 가장자리에 닿는 비드)의 W(유지 — §3 B4) |
| 고리 분류(바깥/안쪽, 구멍/섬), 섬 강체 이동, 구멍 둘레 바닥과 이동 | 섬 회전 성분(평행 이동만 — SR-D-5) |
| 폭 기저·폭 측정 = 비드 경계 고리(섬 흡수 후 = 보통 바깥 고리 1개) | 체결 구멍 위치 자동 판별(paicad kind 사용) — 고정 노드 거리만 씀 |
| 비드별 옵션 `hold_fixed`(체결 구멍 둘레 링 고정 + 블렌딩 보스) | 검증 낙하(VD) 판정 변경 |
| feasible 범위 분리·확대(기본 범위·R_auto 불변) | 기본 범위(±30 %/±20 %) 변경 — Q3 |
| 경고 배지·보고서·받기 rad 주석, 이어하기 호환 | migration |
| **A** ④ 사다리 `defeature` 단계(§5A): 작은 구멍·슬롯(여러 면·seam 구멍 포함), 낮은 딤플·비드 평탄화, 낮은 버링 제거, 작은 필렛·좁은 띠 처리, 억제 목록·편차·`MESH_DEFEATURED` | ③ STEP 스터디의 사다리·defeature 폴백(③ 은 공통 모듈 호출 지점만 — 기본 꺼짐, Q4) |
| **B** 공통 모듈 `esl/geom/defeature.py`·`esl/mesh/features.py`(§5B) — 기존 함수 이동 + 래퍼(바이트 불변), 호출 지점 명시 | STEP 모핑(③ 전환, 보류)·v0.16.2 P3 의 실제 연결 — 시그니처·호출 지점만 예약 |
| ④ 메시 입력 품질 진단(작은 구멍 수·섬 수 — 보고만) | 진단 결과로 메시 입력을 고치는 것(억제는 CAD 단계만) |
| | 로고·나사산·플랜지 인식(BatchMesher `remove_logo 0`·`threads_removal 0`·`flange_recognition 0` — 원 기준도 끔) |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| SR-D-1 | **판정 3단 분리**: `design_state` 반환 = `{state, code, warnings[], fixed, quality}`. state 는 `READY`·`SKIPPED_FIXED`·`FAILED_MESH` 그대로, **`warnings`** 를 새로 둔다. 판정 순서 = 뒤집힘(항상 `FAILED_MESH`/`SELECT_MORPH_INVERTED`) → 고정(`fixed_policy`) → 품질(`quality.fail_policy`). 경고 코드 `SELECT_FIXED_MOVED{n, max_mm}`·`SELECT_QUALITY_WARN{new_fail, new_fail_ratio}` | 확정 1·2, D-0.16-P2. 뒤집힘을 맨 앞으로 — 경고 정책이어도 뒤집힌 안은 반드시 제외 |
| SR-D-2 | **정책 키**: `select.fixed_policy: warn|skip`(기본 warn), `select.quality.fail_policy: warn|skip`(기본 warn). `skip` = v0.16.0 동작 그대로(되돌림 경로) | 확정 1, 품질도 같은 형태로 되돌릴 수 있게 |
| SR-D-3 | **고정 노드는 누르지 않는다**(BS-D-10 유지): 모핑 결과 그대로. 경고 안의 침범 원인(`fixed_violation_detail`)은 **침범이 있는 모든 칸**에 기록(상태 무관) | 확정 1 "고정 노드도 같이 움직임", 배지 문구 근거 |
| SR-D-4 | **고리 분류는 사면 BFS 전에**: 섬 = 바닥 F 의 여집합 연결 성분 중 **한 단 바닥에만 둘러싸인 작은 성분**(§5.2). 섬은 비드 요소 집합에 흡수(BM = F ∪ S ∪ I) → 섬 둘레는 경계가 아니고, 사면 BFS 는 섬을 지나지 않는다. 구멍 = 비드(섬 포함) 요소의 자유 모서리 성분 중 경계 노드에 닿지 않는 것(§5.3) → 열린 경계 판정에서 제외 | 확정 4, 섬을 먼저 떼야 C2·C3 이 함께 풀림 |
| SR-D-5 | **섬 강체 이동 = 둘레 평균**: 모든 변수 v 에 대해 섬 내부 노드 B_v = 그 섬 둘레 노드(바닥과 공유) B_v 의 산술 평균 — 평행 이동(회전 없음). 둘레 노드는 바닥 값 그대로 | 선형·결정적, 평면 바닥이면 정확히 강체. 회전까지 넣으면 곡면 바닥에서만 이득, 구현·시험 비용 큼 |
| SR-D-6 | **구멍 둘레는 바닥 노드 그대로**: 관통 구멍 둘레 노드는 이미 바닥 노드(깊이 기저 n_i^k, 폭 f=1 이면 조화 확장의 자연 경계) — 기저 식 변경 없음, 판정만 바꿈 | 확정 4 "구멍 둘레는 바닥과 함께 이동" |
| SR-D-7 | **폭 = 비드 경계 고리만**: ê·w(x) kNN·국부 폭 교차 선분·단면 위치 = 섬 흡수 후의 경계 고리. 보통 바깥 고리 1개. 섬이 아닌 안쪽 고리(고리형 홈 비드의 안쪽 둔덕, 크기 상한 초과 섬, `exclude` 로 뺀 섬)는 **v0.16.0 그대로** 오프셋·고정 + 경고 `SELECT_INNER_LOOP{n}` | 확정 4 "바깥 고리 1개", 고리형 홈 비드 회귀 방지 |
| SR-D-8 | **체결 구멍 기본 = 바닥과 이동 + 경고**(`fixed_policy` 따름). 비드 안 고정 노드 경고 `SELECT_FIXED_IN_BEAD` 는 남기되 **`fixed_policy: warn` 이면 기본 체크 해제 안 함**(skip 이면 v0.16.0 대로 해제) | 확정 4·1, C5 |
| SR-D-9 | **비드별 옵션 `hold_fixed`(0|1, 기본 0)**: 1 이면 그 비드의 모든 변수 기저에 링 계수 φ(x) 곱 — 고정 노드에서 거리 ≤ ρ(`select.hold.ring_mm`) = 0(제자리), ρ..ρ+b(`select.hold.blend_mm`) Wendland 블렌딩, 그 밖 1(§5.5). 선형 유지(φ 는 변수 값과 무관) | 확정 4 보스 옵션, BS-D-9 선형 기저 유지 |
| SR-D-10 | **feasible 분리**: `feasible` = 기하 한계(D: 위 수준 + min_step ~ D_nom·(1 + `range.depth_max_rel`), W: 바닥 최소 폭 조건 ~ W_nom·(1 + `range.width_max_rel`)), `default_range` = v0.16.0 값 그대로. R_auto 는 default_range 기준 그대로 | 확정 3 상한 완화. 기본 범위·R 이 그대로라 기저 바이트 불변(§7) |
| SR-D-11 | **경고 안도 순위·받기 대상**: READY(경고 포함) 안은 실행·순위·민감도에 그대로 들어간다. 순위 행·결과 카드·보고서에 ⚠ 표시, 결과 요약에 "경고 없는 최상위 안" 1줄 추가(순위 자체는 바꾸지 않음) — **Q1 = A 확정** | 확정 1 "제외하지 않음", 확정 5 |
| SR-D-12 | **받기 rad 경고** = 고정 침범 안의 rad/include 사본에서 **첫 `/NODE` 줄 바로 앞**에 ASCII 주석 줄(`#` 시작) 삽입 + `ch_r.rad` 머리 주석 + `values.json.warnings`. 침범 없는 안은 v0.16.0 과 바이트 동일 | 확정 1 "rad 사본에 경고". Radioss 입력은 `#` 주석 허용, 비ASCII 는 솔버 판독 위험이라 영문 고정 문구 |
| SR-D-13 | **이어하기 호환 4규칙**(§7): (a) 새 비드 키는 기본값이면 정규화에서 생략 → 기존 선택 sha 불변, (b) 해시용 설정 사본에서 새 키가 기본값이면 생략 → `_cfg_hash`·`_sel_cfg_sha` 불변, (c) 기저 `algo: 2` 표지 → 기존 기저 1회 재계산(섬·구멍·hold 없으면 같은 바이트 → 안 해시 불변), (d) 안 재사용 시 판정을 다시 적용 | 기존 스터디를 깨지 않고 완화만 반영 |
| SR-D-14 | **클릭 확장 자동 포함**: 브라우저 `grow` 뒤에 `enclosedIslands`(같은 위상 규칙 — §5.2 의 1~3단계, 크기 상한 포함)로 섬을 즉시 표시. **저장 대상 아님**(입력 ElemSet 에 넣지 않음) — 서버 `derive` 가 같은 규칙으로 다시 정하고 응답의 `islands` 가 표시를 대체 | BS-D-5(서버가 원본) 유지 + 즉시 반응. 두 구현 일치는 픽스처 시험(V-SR-12) |
| SR-D-15 | **섬 끄기 = `exclude` 층**: 사용자가 섬 요소를 "제외" 층으로 칠하면 그 성분은 섬이 아님 → v0.16.0 동작(안쪽 고리) + `SELECT_INNER_LOOP`. 새 층 없음 | 화면 요소 최소(확정 "필수만") |
| SR-D-16 | **사다리 `defeature` 단계**: `mesh_refine.STAGES` += `defeature`, 기본 `compare.mesh.ladder = [cad, refine_local, refine_global, defeature, remesh]`. 규칙(cad 맨 앞·중복 금지·빼면 끔)은 C2-D-18 그대로, 순서는 cad 뒤 자유. 화면 "실패 시 세분화 허용" 끔은 `refine_*` 만 뺌(defeature 유지). 기존 스터디는 스냅샷 `mesh_ladder`(defeature 없음)를 그대로 써 동작·해시 불변 | 확정 6. 요소 수가 가장 적게 느는 세분화를 먼저, 형상을 바꾸는 억제는 그 뒤, 원 위상을 버리는 재메시는 마지막 |
| SR-D-17 | **억제는 CAD(OCC) 세션 안에서만**, 대상 6종 = `hole`(지름 ≤ `hole_max_d_mm` 8 — 등가 지름 4A/P, 여러 면·seam 에 걸친 자유 모서리 고리 포함), `slot`(폭 ≤ 1.9 ∧ 길이 ≤ 14), `flange`(구멍 둘레 버링 높이 ≤ `flange_max_h_mm` 1.5 → 벽 제거 후 구멍 규칙), `bead`(닫힌 둘레 고리 1개로 바탕 면에 붙은 면 묶음, 높이 < `min_bead_height_mm` 2 → 둘레 고리로 채운 평면/채움 면), `fillet`(반경 ≤ `fillet_max_r_mm`), `narrow`(폭 < `narrow_w_factor`·h). 순서 = flange → hole·slot → bead → fillet → narrow(앞 단계 결과 위상에서 다음 인식) | BatchMesher param 대응(§5A.2 표). 메시(요소) 단계 억제는 CAD 대응이 사라져 하중·frame 매핑과 충실도 계산이 어려움 |
| SR-D-18 | **필렛·좁은 띠 = 형상 제거 우선, 쉘은 메시 병합**: 그 면이 고체(dim 3)에 속하면 `gmsh.model.occ.defeature(vols, faces)`(= OCC `BRepAlgoAPI_Defeaturing`), 쉘(중립면 STEP — 대부분)이면 형상은 두고 `gmsh.model.mesh.setCompound(2, [면, 이웃 …])` 로 한 면처럼 메시. 병합 메시 실패 → 같은 단계 2번째 시도 = 병합 없이(억제 대상에서 fillet·narrow 만 뺌) | 쉘의 필렛 제거(날카로운 모서리 재구성)는 OCC 에 일반 도구가 없음. compound 는 형상 편차 0 |
| SR-D-19 | **충실도 = 원 STEP 기준, 억제 영역 분리**: 원 STEP 을 같은 자식 프로세스에서 정리 옵션 그대로 다시 가져와 OCC 삼각화 S0(C2-D-13 과 같은 `linear_deflection_mm`) → 메시 M 과 양방향 거리. 억제 영역 Ω_f = 특징 f 의 bbox 를 `region_pad_factor`·h 만큼 넓힌 상자. **바깥**(Ω 밖 샘플) = `outside{hausdorff_mm, …}`(C2-D-13 지표·warn/fail 그대로 — fail 이면 이 단계 실패 → 다음 단계), **억제 영역** = 특징별 `dev_mm` = Ω_f 안 양방향 최대 거리(판정 없음, 보고만), `suppressed_max_mm` = 그 최대 | 확정 6 "원 STEP 대비 편차, 억제 영역은 별도 집계". 억제 영역 편차는 의도된 차이(구멍 반지름·딤플 높이 수준)라 실패 판정에 넣으면 단계 의미가 없음 |
| SR-D-20 | **기록**: `mesh_method = "defeature"`(C2-D-10 열거 += defeature), `cad_error`, `attempts`(stage defeature), `mesh.json.defeature_stage = {counts{kind: n}, n, skipped_n, compound, fidelity{outside, suppressed_max_mm}, list_file}`, 전체 목록 `mesh/defeature.json`(특징 `{id, kind, center, bbox, size, area_mm2, faces_n, action, method, reason?, dev_mm}`, 결정적 순서 = kind → 중심 좌표(1e-3 반올림) 사전순, 행 ≤ `list_max` 500 — 넘으면 `truncated` + 개수만). 경고 `MESH_DEFEATURED{n, counts, suppressed_max_mm, outside_mm, first}` | 확정 6 "억제 목록(종류·위치·크기)" |
| SR-D-21 | **바이트 불변 3중 보장**: (a) defeature 단계는 cad·refine 이 실패한 형상에서만 실행(첫 cad 시도 경로 `_cmp_mesh_one` 불변), (b) 새 설정 키(§4.4 `compare.defeature` 의 v0.16.1 키)는 base.json `profile`·`profile_sha256` 에서 **항상** 제외하고 `_cmp_sha` 에는 `mesh_method == defeature` 형상에만 `defeature_cfg` 해시로 추가, (c) `gdf.holes`(=`mg.defeature` 본문)는 `collect` 인자를 줄 때만 목록을 모음 — cad 단계 `mesh.json.defeature` 불변 | 확정 6 "CAD 성공 형상 결과 불변", C17 |
| SR-D-22 | **공통 모듈 CAD 단계 `esl/geom/defeature.py`**(소유 Core): 인식(`find_features`)과 실행(`suppress`)을 나누고, v0.14.1 구멍 메움은 `holes` 로 이동(본문 그대로). `mesh_gmsh.defeature` = `gdf.holes` 호출 1줄, 위상 도우미(C18)는 이 모듈로 옮기고 `mesh_gmsh` 는 같은 이름으로 재노출. 호출 지점 = mesh_gmsh 세션(③ 베이스라인·③ 안 BREP·④ cad/refine/defeature) + 재메시 R2 + (예약) STEP 모핑 | 확정 7. 같은 기준·같은 결과를 한 곳에서 |
| SR-D-23 | **공통 모듈 메시 단계 `esl/mesh/features.py`**(소유 Core): `MeshIndex`·`mesh_index`·`node_graph`·`boundary_loops`(= `_loops`) 이동(bead_select 재노출), §5.2 섬 판정 = `enclosed_components`, §5.3 구멍 분류 = `free_edge_components`, 진단 = `diagnose`. 호출 지점 = select derive·(예약) v0.16.2 P3 paicad 영역 → 초기 선택·④ 메시 입력 진단. 브라우저 `grow.ts` `enclosedIslands` 는 `enclosed_components` 의 거울(V-SR-12) | 확정 7, SR-D-4 |
| SR-D-24 | **④ 메시 입력 진단 = 보고만**: `mesh_input.read_shape_mesh` 뒤 `features.diagnose` → 형상 행 `diag{holes_n, holes_small_n, islands_n, free_loops_n}`, 작은 구멍·섬이 있으면 정보 `MESH_INPUT_DIAG`. 메시·하중·해시 불변(`mesh_input` 설정 해시에서 `diag` 절 제외) | 확정 7. 메시 입력은 CAD 가 없어 억제 불가 — 사용자가 HyperMesh 에서 고칠 근거만 |
| SR-D-25 | **고리형 비드 안쪽 고리 = 정보**: 섬 판정에서 고리형 둔덕(SR-D-26)으로 뺀 성분 수 `ring` 이 안쪽 고리 수 `n` 과 같으면 `SELECT_INNER_LOOP{n, ring, level: "info"}`(⚠ 개수·선택 요약 `n_warnings` 에서 뺌, 화면 ⓘ + 문구 `SELECT_INNER_LOOP_RING`). ring < n 이면 지금처럼 경고 | 고리형 홈 비드의 안쪽 고리는 정상 경계 — 경고로 두면 실 Ch/R 마다 ⚠ 가 떠 진짜 딤플 경고가 묻힘 |
| SR-D-26 | **고리형 둔덕은 섬 아님(`select.island.ring_frac` 0.9)**: `enclosed_components(ring_frac=)` — 둘러싸인 성분이 주인 바닥에서 판 쪽으로 ≥ ring_frac·D(D = 주인 바닥 ↔ 최대 성분 평행(≤ 15°) 요소 높이 차 중앙값) 솟으면 섬 아님(`rings`, 크기 판정 전). 거울 키 = 코어 DEFAULTS·백엔드 `BeadDoeSelectIslandCfg.ring_frac`(gt 0)·yaml 2개·`GET /doe/settings select.island{max_mm, ring_frac}`·브라우저 `enclosedComponents(opts.ringFrac)`. 섬 판정 평면 법선 부호 = 면적 최대 요소 쪽(동률 = 최소 요소 번호 — 코어 `_mean_normal`, 프런트 `beadMeanNormal` 같게; 판정 결과는 부호와 무관) | 판 높이까지 솟은 둔덕(Ø14 처럼 크기로는 섬 상한 안)을 섬으로 흡수하면 W 가 2배로 틀어짐 |
| SR-D-27 | **바깥 충실도 경고 = cad 메시 현 편차 대비 상대**: defeature 단계 바깥·재메시 R8 의 경고 기준 = max(`fidelity.warn_mm`, `fidelity.warn_rel_cad` × chord), chord = `mesh_remesh.cad_chord_mm(S0, h, 2·angular_deflection_deg)` = S0 내부 모서리(이면각 0 < θ ≤ 2·각 편차)마다 R = ((A₀+A₁)/\|e\|)/θ, s = R(1 − cos(min(h/2R, π/4)))의 최대(곡률 세분 없는 h CAD 메시가 곡면에서 갖는 처짐, 상한 ≈ 0.19·h). 기본 `warn_rel_cad` 2.0, 0 = 절대 기준만(v0.16.0). fail_mm 은 절대 그대로. 기록 `fidelity{warn_mm(= 실제 기준), cad_chord_mm}`. **해시**: 경고 전용 키라 `_cmp_sha` 의 `keep["remesh"]` 에서 항상 제외(`stages.REMESH_HASH_SKIP_V0161`) — v0.16.0 스냅샷·cad 형상 해시 불변 | 0.3 mm 절대값이면 h 3 의 필렛·구면 딤플마다 CAD 메시 자체 처짐(0.4~0.6 mm)으로 `REMESH_FIDELITY_WARN` 이 떠 경고가 뜻이 없음 |
| SR-D-28 | **사면 탐색 높이 = 판 높이까지**: 첫 사면 BFS 가 새지 않았을 때(SELECT_SLOPE_LEAK 조건 거짓)만, 사면이 멈춘 평행 요소 높이(n̄ 방향 중심) 묶음(간격 > `plate_tol_mm` 에서 나눔) 중 요소 수 최대 묶음 = 판(멈춤 요소의 절반 이상일 때만), 판 쪽 끝 z_far 보다 바닥 반대쪽으로 `plate_tol_mm` 넘게 나간 요소를 사면 후보에서 빼고 BFS 1회 다시. 뺀 요소가 있으면 정보 `SELECT_SLOPE_ABOVE_PLATE{n_elems, level: "info"}`. 판 위로 나간 사면이 없으면 아무것도 바꾸지 않음(섬·교차 없는 선택 바이트 불변 — V-SR-1) | 개구 경계에 반쯤 걸친 보스에서 사면이 보스 벽을 타고 윗면까지 올라가 보스 윗면이 안쪽 고리로 남고 국부 폭이 튐(실 Ch/R 사례 5) |
| SR-D-29 | **비드 네트워크(T·L 교차)**(R1c): 다른 비드 바닥이 사면으로 이어지면 사면 요소는 측지 거리가 가까운 바닥의 비드 몫(Voronoi — `lose`), 교차부 경계 노드(이웃 비드 영역·바닥에 붙은 평행 비선택 요소)는 기준 평면 맞춤에서 뺌. 경계가 섬 상한보다 큰 바닥 높이 평행 영역(선택 안 한 이웃 비드 바닥)을 가로지르거나 다른 비드와 맞닿으면 경고 `SELECT_BEAD_NETWORK{n_elems, slope_split}`(화면 비드 목록 ⚠ 툴팁·`SelectDeriveWarnCode`). 맞닿음이 없으면 v0.16.0 과 같음 | 사다리 레일·가로대처럼 이어진 비드를 하나씩 고르면 사면이 이웃 바닥까지 번지거나 기준 평면이 기울어짐 |
| SR-D-30 | **보스 바닥 고리 구멍 = hole**(R1c, `gdf.find_features`): 자유 고리가 평면(≤ `plane_tol_mm`) 위에 있으면 높은 보스의 바닥·윗면 구멍도 hole 규칙(등가 지름) — 버링 관 끝(자유 고리가 원통 벽 끝)만 hole 에서 제외(flange 규칙). 보스 자체는 남김 | 실 Ch/R 사례 7: 체결 보스는 형상 유지, 가운데 구멍만 메움 |
| SR-D-32 | **W 기본 범위는 공칭을 포함**: floor_follow 1 의 바닥 최소 폭 조건으로 하한 lo > W_nom 이면(국부 폭 5 % 분위 W_min 이 보스·구멍·교차부 오탐) 바닥 폭을 `range.width_floor_q`(0.25) 분위 국부 폭으로 다시 계산, 그래도 lo > W_nom 이면 뒤집힌 범위(lo > hi)는 W_nom·(1 ± width_rel), 아니면 lo = W_nom(넓히기만) + 경고 `SELECT_W_RANGE_RESET{lo_mm, hi_mm, new_lo_mm, w_min_mm, q}`. feasible 하한도 같은 바닥 폭 기준. lo ≤ W_nom 인 v0.16.0 범위는 그대로(바이트 불변 — 단 v0.16.0 에서 lo > hi 로 쓸 수 없던 범위는 고쳐지므로 그 비드 R_auto·기저가 바뀜: 합성 h6wavy) | 실 사례 5: [50.29, 48.0] 처럼 하한 > 상한, 공칭 40 이 범위 밖 |
| SR-D-33 | **기본 범위 끝 뒤집힘 점검**(`bead_select.range_check`, BD_MATRIX 기저 직후): 변수마다 default_range 양 끝 단독 안을 `design_state` 로 판정, 뒤집힘이면 공칭 쪽으로 `range.check_steps`(5) 회 이분해 뒤집힘 없는 끝을 찾아 비드 경고 `SELECT_RANGE_INVERTS{var, lo_mm, hi_mm, usable[lo, hi], inverted[lo, hi]}`(params.json·derived.json·로그). 범위·기저는 바꾸지 않음(R_auto 순환 회피), 0 = 끔. 블렌딩 반경·이웃 거리로 상한을 정하는 규칙은 사례 2 에서 원인이 사면·블렌딩 경계 국부 왜곡(쓸 수 있는 ΔW ≈ ±4 %)이라 단순 식으로 맞지 않아 보류 — 실측 점검으로 대체 | 실 사례 2: 96·144 양 끝 뒤집힘 263·112, 쓸 수 있는 범위 ≈ 115.5~124.5 |
| SR-D-34 | **썸네일 시점 = 판 법선 쪽 위에서**(`select_render.view`·`view_normal`): 비드마다 n̂_b 를 판 법선(`view3d.plate_normal`) 쪽으로 맞춰 평균(볼록·오목 섞여도 상쇄 없음), 카메라 = 그 쪽 위에서 내려다봄(f = −cos t·n + sin t·η), 화면 오른쪽 = η × n, 위 ≈ +η — sense 무관. **모든 select 썸네일 PNG 바이트가 v0.16.0 과 다름**(표시만 — 해시·판정·결과 불변) | 오목 비드에서 상하·좌우가 뒤집힌 그림 |
| SR-D-31 | **select 워커 재사용 = OK 만**(`doe_jobs.SELECT_REUSE_STATES` 는 OK·FAILED_SOLVE 를 통과시키지만 FAILED_SOLVE 는 `ev.reusable` 이 재시도 대상(`RETRY_STATES`)으로 거르므로 실제 재사용 = OK 뿐): 같은 키 done.json 이어도 스킵 문서(v0.16.0 `SKIPPED_FIXED` 등)면 워커가 재사용하지 않고 코어 bd_eval 에 넘겨 SR-D-13d 재판정 | 워커가 코어보다 먼저 `ev.reusable` 로 재사용해 warn 정책에서 v0.16.0 스킵 안이 다시 실행되지 않던 경로를 막음 |
| SR-D-35 | **섬 포함 판정 = 단 바닥의 모든 조각·열린 고리**(H1·H2·H4 — Med#3·#4, High#1 근본 원인): `features.outer_polygons(ix, F_k, n)` = F_k 의 요소 연결 조각(최소 요소 순)마다 경계(조각 요소 1 ∧ (밖 요소 ≥ 1 ∨ 자유 모서리)) 고리 중 \|넓이\| 최대 닫힌 고리(없으면 그 조각 볼록 껍질) — §5.2(d) 는 어느 조각 안이면 통과, 바닥 조각 사이(섬이 조각을 가름)면 섬 노드에서 2h 안 조각 ≥ 2 의 고리 점 합 볼록 껍질 안. **판 가장자리 = 판 전체 외곽 자유 모서리만**(`features.plate_edge_nodes` = 메시 연결 성분마다 자유 고리 중 평면 투영 넓이 최대 — ix 캐시): 경계 노드에 닿는 구멍(비드 벽을 가로지르는 슬롯)은 관통 구멍(`touch`), 그 구멍이 끊은 경계 고리는 구멍을 건너 잇는다(`_bridge_holes` — 열린 고리 끝점이 같은 구멍 노드인 고리끼리 평면 거리 가까운 쪽, 가상 선분 1개, `bridged` 수). 조각 1개·자유 모서리 없음·판 외곽에만 닿는 자유 모서리면 v0.16.1 첫 판과 같음(바이트 불변) | 교차 비드가 바닥을 두 조각으로 가르거나 구멍이 바닥 가장자리를 끊으면 가장 큰 닫힌 고리 하나가 다른 조각·딤플 고리라 11~14 mm 딤플·보스가 `SELECT_ISLAND_TOO_LARGE` → 사면 보간으로 찢어짐. 벽을 가로지르는 슬롯 1개로 `SELECT_OPEN_BOUNDARY` → W 꺼짐 |
| SR-D-36 | **교차 비드 하나만 고를 때 기준 평면 = 판 쪽 경계 노드**(H1 High#2): 첫 맞춤 잔차 > `plane_rms_mm` 일 때만 `_plate_refit` — 비드에 닿은 밖 평행 요소 높이 묶음(간격 > `plate_tol_mm`) 중 최다 = 판(멈춤 요소의 절반 이상일 때만), 다른 묶음 중 판에서 이 비드 바닥 쪽 높이이고 판 영역과 평행으로 이어지지 않으며(벽으로만 이어짐) 섬 상한보다 큰 평행 영역 = 교차하는 다른 비드 바닥(증거). 증거가 있으면 밖 요소가 모두 판 높이 평행 요소인 바깥 고리 노드(J 제외)로 다시 맞춤 → 잔차 ≤ `plane_rms_mm` 이면 그 평면 + 정보 `SELECT_BASE_REFIT{n_excluded, rms_mm, level info}`, 아니면 **derive 오류 `SELECT_BASE_AMBIGUOUS{bead, rms_mm, n_plate}`**(422 — "교차하는 비드를 함께 선택"). 증거가 없으면(물결 판 등) v0.16.1 첫 판 그대로 `SELECT_NONPLANAR_BASE`. **영향**: 실 사례 1 레일 A 만 선택 = D 7.07 → 8.00(참값), NONPLANAR·TIER_MISSING → BASE_REFIT(2026-11-05 통합 판단 "정상" 을 대체) | S 만 고르면 D_nom 0.21(참값 15), Dp 만 21.8(참값 25) — 경계가 다른 비드 바닥(−25)·벽을 지나 평면이 기움 |
| SR-D-37 | **바닥이 움직이는데 붙은 피처가 안 움직이면 안 실패**(H4 High#1 안전망): derive 가 `bd.features` = (a) 섬이 못 된 둘러싸인 성분(`SELECT_ISLAND_TOO_LARGE` — 크기·다각형 탈락) {rim = 주인 바닥 노드, interior = 나머지}, (b) 안쪽 고리로 남은 피처(비드 밖 연결 성분 중 판 아닌 것 — 다른 비드·제외 없음, bbox ≤ `island.max_mm`, 가장 가까운 단 바닥 높이에서 `plate_tol_mm` 넘게 벗어나고 판 쪽으로 `ring_frac`·D 미만: 바닥 높이 요철·고리형 둔덕 제외) {rim = 그 단 바닥 노드 중 가장 가까운 고리(최소 거리 + 2h), interior = 성분 노드}. 안마다 u = x − x0, t = mean u(rim), dev = max ‖u(interior) − t‖ > max(`quality.distort_min_mm` 0.1, `quality.distort_rel` 0.25 × ‖t‖) → **FAILED_MESH `SELECT_FEATURE_DISTORTED{bead, k, dev_mm, floor_mm}`**(정책 무관, 뒤집힘 다음 순서). 자료 = `design_checks(D, B)` → `derived.npz` `chk_f*`(없으면 키 없음 — 바이트 불변), `design_state(..., checks=, values=)`(checks 없으면 검사 없음) | 슬롯·섬 판정 실패로 보스·루버가 사면/안쪽 고리로 남으면 D +1.5 에서 보스 +0.75·루버 0 인데 READY(경고만) |
| SR-D-38 | **다른 선택 비드 침범**(H3 Med#6): `design_checks.cross` = W 변수 v(비드 a)의 기저가 다른 선택 비드 b 의 경계·바닥 노드(a 자신의 경계·바닥 제외)에 주는 ‖B_v‖ > 0 인 노드·크기(`chk_c*`). 안에서 \|Δv\|·‖B_v‖ > `cross_bead_tol_mm`(0.1) 인 노드가 있으면 `SELECT_CROSS_BEAD_MOVE{n, max_mm, beads[[v, b]…]}` — `cross_bead_policy: warn`(기본) = READY + 안 경고(받기·순위 `warn` CROSS_BEAD_MOVE), `skip` = **SKIPPED_COLLISION `SELECT_CROSS_BEAD_VIOLATION`**(`paicad_io.SELECT_CELL_STATE`). 판정 순서 = 뒤집힘 → 피처 왜곡 → 고정(skip) → 침범(skip) → 품질(skip) | P 의 W 상한이 A 바닥을 4.2 mm·경계를 6 mm 움직여도 알림 없음 |
| SR-D-39 | **범위 = 조합 검증 + 다단·이웃 제약 경고**(H1·H2·H3 Med#5): (a) `range_check` 끝에 `_range_combo` — 변수별 usable 끝의 모서리 조합 표본(변수 n ≤ log2 m 이면 2^n 전부, 아니면 시드 0 난수 m = `range.combo_samples` 16 — 결정적)을 뒤집힘 판정(`mesh_quality.inverted_count` = affected_quality 의 뒤집힘과 같은 식, 품질 지표 생략)해 뒤집힌 조합이 있으면 공칭 쪽 같은 비율 s 를 `check_steps` 회 이분 → 선택 경고 `SELECT_RANGE_COMBO{vars, corners, inverted_n, scale, usable{var: [lo, hi]}}`(Derived.warnings·params.json warnings — 범위·기저 불변, 0 = 끔). (b) derive `SELECT_W_RANGE_LIMIT{by: tier\|neighbor, move_mm, lim_mm[, with]}` — W 기본 범위 끝 경계 이동 max\|W − 끝\|/2 가 다단 비드의 이웃 단 바닥 노드 사이 최소 평면 간격, 또는 맞닿지 않은(> h) 다른 선택 비드 경계까지 최소 거리의 절반보다 크면(경고만 — 단 간격을 범위 식에 넣는 것은 R_auto·기저 순환이라 보류) | 변수별 usable 끝을 따로 구해 조합 2^4 중 READY 4/16(H1)·2/8(H3), 3단 W 범위 끝 모두 뒤집힘(H2) |
| SR-D-40 | **요소별 극단값 = 안 단위 품질 경고**(H1 Med#7): 영향 요소의 넓이 비(안/공칭) 최소 < `quality.area_ratio_min` 0.2 또는 법선 회전 최대 > `quality.rot_warn_deg` 45°(≤ `flip_deg`)이면 새 Fail 비율과 무관하게 `SELECT_QUALITY_WARN{…, area_ratio_min, rot_max_deg}`(warn 정책만 — skip 정책은 v0.16.0 판정 그대로(V-SR-1), 극단값으로 제외하지 않음), 0 = 그 조건 끔. `quality` dict(result.json)는 그대로. **`flip_deg` 60° 유지**(검토): 45° 로 낮추면 H2 D3 하한(52.9°)·실 사례 5 D 하한(56.4°)처럼 넓이 비 ≥ 0.5 인 가파른 사면 정상 변형이 뒤집힘(실행 제외)이 됨 — 45~60° 는 경고(이 결정)로, 60° 초과·야코비안 ≤ 0 만 제외 | 넓이 비 0.11·법선 52~59° 요소가 경고 없이 READY |
| SR-D-41 | **④ defeature 목록 = 실제로 바뀐 것만**(H4 Low#8): `gdf.find_features` 에서 높이 hC ≤ `plane_tol_mm` 인 묶음(자유 고리 ≤ 1 — 바탕 면과 한 평면인 경계에 걸친 보스의 평평한 조각)은 bead·flange 아님(목록·억제 없음, 그 안 구멍은 hole 규칙). defeature 단계(cad·refine 실패 형상)에서만 쓰여 cad 성공 형상 바이트 불변 | 경계에 걸친 보스가 "bead h 0.0" 으로 적혀 `suppressed_max_mm` 2.11 이 그 행에도 붙음 |
| SR-D-42 | **벽에 붙은 섬**(H1 변형 Low#9): 원인 = 보스가 바닥을 두 조각으로 가름 → SR-D-35 조각 사이 규칙으로 섬(B2_D1 +3.7 READY). 바닥 둘레가 아예 끊겨(요소 1개 안) 벽 성분에 이어진 보스는 위상으로 떼지 못함(법선 골·발치 요소 분리 시도 — 구조 4각 메시에서 보스 벽·비드 벽 법선 차 60~80° 라 오탐/누락) → 섬으로 흡수하지 않고 SR-D-37 (b) 안전망이 FAILED_MESH 로 막음 | 보스 r_top 3.5 에서 섬 0·구멍 1 → D 변경 뒤집힘 |
| SR-D-43 | **Verifier Low 4건**: (a) 교차부 사면 Voronoi 거리 동률 = **비드 id 작은 쪽**(`derive_obj` 층 주인 번호 rank — 작은 id 이웃과 거리가 같으면 내줌, 전체·단일 비드 derive 같은 규칙), (b) 받기 rad `#ESL WARNING` 주석 줄 ≤ 100자(`stages.sel_warn_lines` — FIXED_NODES 줄당 ≤ 10개 ∧ ≤ 100자, 머리 줄이 넘으면 설명을 다음 줄로; 짧은 ID 는 첫 판과 같은 줄), (c) 재사용 문구 = "OK 만 재사용"(SR-D-31·§7.4), (d) 프런트 상단 바 버전 칩 = 빌드 시 저장소 루트 `VERSION`(`__APP_VERSION__` — vite define, 없으면 GET /version; 서버 판이 다르면 툴팁 "서버 v…") | 검증 지적 |
| SR-D-44 | **모핑 코어는 메시 출처와 무관하게 공통 적용**(사용자 지시 2026-11-05): SR-D-35~43 규칙은 select 전용이 아니라 공통 모듈 — 섬·구멍·바닥 조각 다각형·판 가장자리 = `esl/mesh/features.py`(`enclosed_components`·`free_edge_components`·`outer_polygons`·`plate_edge_nodes`·`_between_pieces`), 기준 평면·피처·안 판정 = 새 `esl/morph/core.py`(`plane_fit`·`plate_refit`·`bridge_holes`·`stuck_features`·`enclosed_features`·`w_limits`·`inverted_any`·`range_combo`·`cross_footprint`·`extremes`·`feature_distortion`·`cross_move`·`checks_arrays`·`checks_from_arrays`·`post_morph_warnings`). 입력 = 메시 노드·요소(MeshIndex/MESH_KEYS dict)·좌표·피처 라벨(요소 마스크)만, 출처(gmsh STEP 메시·사용자 .rad/.inc·재메시)를 모름. 호출: select(`bead_select` — 기준 메시가 STEP gmsh 이든 Case .rad/.inc 이든 같은 경로), 자동 탐지 기본 모핑(paicad same·mesh 안 좌표 → `post_morph_warnings` = 극단 요소 경고 `MORPH_EXTREME_ELEMENTS`, 해당 없으면 키 없음), ③ STEP 모핑(보류 — `stages._design_mesh` 에 호출 지점 TODO 1줄). 시험 = H1~H4 메모리 메시 ↔ .rad + `#include` .inc 왕복, H4 gmsh STEP 메시 ↔ .rad/.inc 왕복의 판정·경고 코드 동일 | 같은 비드라도 메시를 어디서 만들었는지에 따라 판정이 달라지면 안 됨 |

## 3. 막는 조건 결정표 (확정 3)

"막음" = 422/스킵/변수 비활성/기본 해제. 결정: **유지** / **경고** / **해소**(원인 제거) / **완화**(값 확대).

| # | 조건 | 위치 | 현재 | 결정 | 이유 |
|---|---|---|---|---|---|
| A1 | feature_angle 1..45 | `normalize_input:151` | 422 | 유지 | 확장 품질 범위, 실사용 15° |
| A2 | 비드 1..20, 단 1..6 연속 | `:154`·`:183` | 422 | 유지 | 화면·기저 크기 상한, 요청 없음 |
| A3 | 빈 단·묶음 규칙·id/이름 | `:172-211` | 422 | 유지 | 형식 오류 |
| A4 | 요소 겹침(한 요소 1 비드·1 층) | `:219-237` | 422 | 유지 | 기저 정의 불가 |
| A5 | 없는 요소 ID | `elems_of:408-411` | 422 | 유지 | 형식 오류 |
| A6 | blend_mm 0..200 | `:193` | 422 | 유지 | 설정 `blend.max_mm` 로 이미 조정 가능 |
| A7 | 선택 크기 4096 KB | `:239` | 413 | 유지 | DB 보호 |
| B1 | 자유 모서리 하나라도 → W 비활성 | `:510`·`:780` | W 없음 | **해소**(SR-D-4 구멍 분류) | 확정 4 |
| B2 | 섬 둘레 = 안쪽 고리(D 고정·W 오프셋) | `:734-738`·`:867`·`:929` | 찢어짐·오프셋 | **해소**(SR-D-4·5·7) | 확정 4 |
| B3 | 섬 → `SELECT_TIER_MISSING` 오경고 | `:823-834` | 경고 | **해소**(섬은 BM 안이라 멈춤 요소 아님) | 딤플을 빠진 단으로 오인 |
| B4 | 판 가장자리에 닿는 열린 경계 → W 비활성 | `:780`(열린 고리) | W 없음 | 유지 | 자유 끝단 오프셋 = 판 외곽 변경, 의도 불명 |
| B5 | 폭 측정 불가 → W 비활성 | `:990-993` | W 없음 | 유지 | 공칭 없음 |
| B6 | 비드 안 고정 → 기본 체크 해제 | `:841-846`, `params_table:1157·1166` | 해제 | **경고**(warn 이면 해제 안 함, SR-D-8) | 확정 1·4 |
| B7 | 블렌딩 안 고정 → 침범 스킵 | `:1094-1096` | 결국 스킵 | **경고**(C6 을 따름) | 확정 1 |
| B8 | R 자동 자르기 | `:1077-1084` | 자름 + 경고 | 유지 | 막지 않는 완화책, 바꾸면 기존 기저 변경 |
| B9 | 사면 누수 `slope_max_mm` 80 | `:716-725` | 경고 | 유지 | 이미 경고 |
| C1 | 고정 침범 → `SKIPPED_FIXED` | `design_state:1374` | 스킵 | **경고**(`fixed_policy`) | 확정 1 |
| C2 | 새 Fail 비율 > 0.01 → `FAILED_MESH` | `:1378` | 제외 | **경고**(`quality.fail_policy`) | 확정 2 |
| C3 | 뒤집힘(야코비안 ≤ 0 · 법선 > 60°) | `:1376` | 제외 | 유지 | 확정 2, 해석 무의미 |
| D1 | 기본 범위 D ±30 %, W ±20 % | `_ranges_blend:1045-1051` | 기본값 | 유지(Q3 = A 확정) | R_auto 가 이 값 기준 — 바꾸면 기저 변경 |
| D2 | feasible = 기본 범위 | `params_table:1159·1165` | 밖 → 경고 | **완화**(SR-D-10: D 하한 = 위 수준 + 1, 상한 ×2.0 · W 상한 ×1.6) | 확정 3 |
| D3 | lo ≤ 0 (D·W) | `matrix.py:107-108` | 422 | 유지 | 물리적 불가 |
| D4 | lo ≥ hi | `matrix.py:104-105` | 422 | 유지 | 형식 |

## 4. 데이터 모델 · 설정 키

### 4.1 `SelectionIn` 변경 (schema_version **1 유지**)
```text
BeadSel += { hold_fixed: 0 | 1 (기본 0) }      # SR-D-9. 정규화 결과에는 1 일 때만 키를 쓴다(SR-D-13a)
exclude: ElemSet  — 의미 확장: "사면 자동·섬 판정에서 뺄 요소"(SR-D-15). 형식 불변
```
- `normalize_input`(`bead_select.py:213`): `hold_fixed` 검증(0|1, bool 금지 → 422 `SELECT_EMPTY_TIER` 와 같은 형식 오류 코드 재사용 대신 **`SELECT_HOLD_INVALID`** 신규), 0 이면 out 딕셔너리에 넣지 않음.

### 4.2 `SelectionDerived` 추가 (BeadDerived)
```text
islands: [{ k, n_elems, n_nodes, elems: ElemSet, rim_n, size_mm (평면 bbox 대각), free_loops (섬 안 구멍 수) }]
holes:   { n, n_nodes }                         # 섬 밖 바닥·사면의 관통 구멍(자유 모서리 성분)
inner_loops_n: int                              # 섬 흡수 후 남은 안쪽 고리 수(SR-D-7)
hold_fixed: 0|1, hold: { n_ring_nodes, n_blend_nodes, n_fixed } | null
algo: 2                                         # SelectionDerived 최상위 — 계산 규칙 판(SR-D-13c)
```
- `boundary.loops` 에는 섬 둘레가 없다. `slope_suggested` 에 섬 요소 없음. derive 응답 `islands_suggested: {bead: ElemSet}`(화면 표시용, SR-D-14).

### 4.3 판정 결과(미리보기 셀·`result.json`)
```text
cell += warnings?: [{code: "SELECT_FIXED_MOVED", n, max_mm} | {code: "SELECT_QUALITY_WARN", new_fail, new_fail_ratio}]  # 비었으면 키 없음
cell.fixed_viol: 침범이 있으면 상태와 무관하게 기록(SR-D-3)                                                       # 없으면 키 없음
grid_manifest += rules: 2                     # 판정 규칙 판(§7.4)
result.json += warnings (같은 형식) · ranking 행 += warn: ["FIXED_MOVED"|"QUALITY_WARN", …] (비었으면 키 없음)
```

### 4.4 설정 키 (`DEFAULTS["select"]` = `BeadDoeSelectCfg` = `config/*.example.yaml` 거울, 하드코딩 금지)
```yaml
bead_doe:
  select:
    fixed_policy: warn            # warn | skip (SR-D-2)
    quality: {max_fail_ratio: 0.01, flip_deg: 60.0, fail_policy: warn}   # fail_policy warn | skip
    range: {depth_rel: 0.3, width_rel: 0.2, min_step_mm: 1.0, depth_max_rel: 1.0, width_max_rel: 0.6,  # *_max_rel = feasible 상한(SR-D-10)
            width_floor_q: 0.25, check_steps: 5,   # SR-D-32 바닥 폭 분위 · SR-D-33 범위 끝 점검(0 = 끔) — 기본값이면 해시 제외
            combo_samples: 16}                     # SR-D-39 usable 모서리 조합 표본(0 = 끔)
    # SR-D-40 요소 극단값 경고 · SR-D-37 비드 안 피처 왜곡(FAILED_MESH) — quality 절에 추가(기본값이면 해시 제외)
    #   quality: {…, rot_warn_deg: 45.0, area_ratio_min: 0.2, distort_rel: 0.25, distort_min_mm: 0.1}
    cross_bead_policy: warn        # SR-D-38 다른 선택 비드 침범: warn | skip(SKIPPED_COLLISION)
    cross_bead_tol_mm: 0.1
    island: {max_mm: 40.0, ring_frac: 0.9}   # 섬 평면 bbox 대각 상한(§5.2) · 고리형 둔덕 비율(SR-D-26)
    hold: {ring_mm: 3.0, blend_mm: 8.0}                                  # Q2 = A 확정
  compare:
    mesh:
      ladder: [cad, refine_local, refine_global, defeature, remesh]      # SR-D-16 (v0.16.0: defeature 없음)
    defeature:                    # 기존 키(enabled·min_hole_area_mm2·hole_elems·hole_r_mm·min_bead_height_mm) 의미 불변 — cad 단계
      min_bead_height_mm: 2.0     # v0.16.0 '기록만' → defeature 단계에서 bead 기준으로 적용(cad 단계는 여전히 안 읽음)
      # ↓ v0.16.1 새 키 — defeature 단계에서만 읽음(SR-D-21b: profile 해시 제외)
      kinds: [flange, hole, slot, bead, fillet, narrow]   # 빼면 그 종류 끔, 이 순서로 실행(SR-D-17)
      hole_max_d_mm: 8.0          # 등가 지름 4A/P ≤ (BatchMesher shape(1) rad<4·shape(62) eq_diam<8 action 1)
      slot_max_w_mm: 1.9          # shape(2) width<1.9 ∧ length<14 action 1
      slot_max_l_mm: 14.0
      flange_max_h_mm: 1.5        # appl_flanged_suppr 1 · flanged_suppr_height 1.5
      fillet_max_r_mm: 1.5        # Q5 (BatchMesher surface/edge fillet 인식 끔 — 0.5·h 권장)
      narrow_w_factor: 0.4        # × h  (narrow_surfs_merge_width Lmin·0.5, Lmin = min_size_factor 0.8 · h)
      feature_max_mm: 40.0        # bead·flange 특징 bbox 대각 상한(= select.island.max_mm 과 같은 값, 따로 둠)
      plane_tol_mm: 0.01          # 둘레 고리 평면 판정(넘으면 채움 면)
      compound: true              # 쉘 fillet·narrow 를 mesh.setCompound 로 병합(SR-D-18)
      region_pad_factor: 1.0      # 억제 영역 Ω_f = bbox ± 이 값 × h (SR-D-19)
      max_features: 2000          # 인식 상한(넘으면 앞 2000개만 + 경고 DEFEATURE_TOO_MANY)
      list_max: 500               # defeature.json 행 상한
    remesh:
      fidelity: {warn_rel_cad: 2.0}  # SR-D-27 경고 = max(warn_mm, 2 × cad 메시 현 편차) — 0 = 절대만, 해시 제외
    mesh_input:
      diag: {enabled: true, feature_angle_deg: 30.0}   # SR-D-24. 구멍·섬 크기 기준 = defeature.hole_max_d_mm · select.island.max_mm
```
- ③(`bead_doe.mesh`)에는 키를 추가하지 않는다. ③ 에서 작은 형상 처리를 켜려면 `bead_doe.mesh.defeature`(④ 와 같은 형식, DEFAULTS 에 없음 — 없으면 ③ 그대로)를 직접 쓰며, 그 경우 cad 세션의 `gdf.holes` 만 실행(사다리 없음 — Q4).
| 위치 | 추가 | pydantic 검사 |
|---|---|---|
| `esl/doe/__init__.py:130-140` DEFAULTS | `fixed_policy`, `quality.fail_policy`, `range.depth_max_rel`·`width_max_rel`, `island`, `hold` | – |
| `backend/esl_platform/core/config.py:818-862` | `BeadDoeSelectCfg.fixed_policy: Literal["warn","skip"]="warn"`, `BeadDoeSelectQualityCfg.fail_policy: Literal[...]="warn"`, `BeadDoeSelectRangeCfg.depth_max_rel: float(gt=0, le=5)=1.0`·`width_max_rel(gt=0, le=5)=0.6`(각 `*_max_rel ≥ *_rel` 검사), `BeadDoeSelectIslandCfg.max_mm(gt=0)=40`, `BeadDoeSelectHoldCfg.ring_mm(ge=0)=3`·`blend_mm(gt=0)=8` | 섹션 없으면 기본 |
| `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`(select 절이 있는 예시 2개) | 위 yaml 그대로 | – |
| `GET /doe/settings` `select` | `fixed_policy`, `quality_fail_policy`, `hold{ring_mm, blend_mm}`, `island{max_mm, ring_frac}`(SR-D-26 거울) | – |
| `esl/doe/__init__.py:104`·`:119-120` DEFAULTS compare | `mesh.ladder` += defeature, `defeature` 새 키, `mesh_input.diag` | – |
| `backend/.../core/config.py:603`·`:620`·`:748-754`·mesh_input 모델 | `COMPARE_LADDER_STAGES` += `"defeature"`, `ladder max_length=5`, `BeadDoeCompareDefeatureCfg` 새 칸(`kinds: list[Literal[…6종]]` 중복 금지, `*_mm gt=0`, `narrow_w_factor (0,1]`, `region_pad_factor ge=0`, `max_features ge=1`, `list_max ge=1`, `compound: bool`), `BeadDoeCompareMeshInputDiagCfg{enabled, feature_angle_deg (0,90]}`. `_doe_settings` 기본값 거울(`:1319-1326`)에 `defeature` 새 키·`mesh_input.diag` 추가 | 섹션 없으면 기본 |
| `config/*.example.yaml` 2개 | compare 절 위 yaml 그대로 | – |
| `GET /doe/settings` `compare` | `mesh.ladder`(defeature 포함), `defeature{hole_max_d_mm, min_bead_height_mm, fillet_max_r_mm, kinds}` | – |

## 5. 알고리즘 (`esl/doe/bead_select.py`)

기호는 BS §5 와 같음. F = ∪F_k, I = ∪ 섬, BM = F ∪ S ∪ I. "평면" = 단 평균 법선 n̄_b 에 수직인 평면(섬 판정 단계에서는 n̂_b 가 아직 없음).

### 5.1 처리 순서 (`_derive_bead`, 변경 부분만)
1. F, n̄_b (불변) → 2. **섬 판정 §5.2** → 3. 사면 BFS: `allowed &= ~I`(섬을 지나지 않음, `:710`) → 4. BM = F ∪ S ∪ I → 5. 경계·고리(`_loops(BM)`) + **구멍 분류 §5.3** → 6. 이하 v0.16.0 그대로(평면·n̂_b·단·사면 수준) → 7. 폭 §5.4 → 8. 블렌딩·고정 → 9. hold 영역 §5.5.
- 섬·구멍이 없으면 2·5 의 결과가 공집합/거짓 → 이후 모든 배열이 v0.16.0 과 같다(V-SR-1).

### 5.2 섬 판정 (바깥/안쪽 구분 — 섬)
- 구현 위치 = 공통 `esl.mesh.features.enclosed_components`(§5B.2). bead_select 는 아래 1의 후보·주인 표(owner = 단 번호)를 만들어 부른다.
1. 후보 Cand = ¬F ∧ ¬taken(다른 비드 층·자기 사면 add) ∧ ¬exclude ∧ (bead_owner < 0).
2. Cand 의 요소 인접(`ix.adj[Cand][:, Cand]`) 연결 성분 K_1..K_m(`csgraph.connected_components`, 성분 번호 = 최소 요소 번호 순으로 다시 매김 — 결정적).
3. 성분 K 가 단 k 의 **섬** ⇔ 아래를 모두 만족:
   - (a) 이웃 N(K) = K 밖 인접 요소가 모두 **한 단** F_k 에 속함(두 단에 닿으면 단 사이 사면, 다른 층·제외 요소에 닿으면 섬 아님).
   - (b) K 가 가장 큰 성분이 아님(요소 수 최대, 동률 = 최소 요소 번호) — 판 나머지는 항상 바깥.
   - (c) K 노드의 평면 bbox 대각 ≤ `island.max_mm`.
   - (d) K 요소 중심 평균이 F_k 바깥 고리 다각형 안(평면 투영, 짝홀 규칙). F_k 바깥 고리 = `_loops(F_k)` 닫힌 고리 중 |넓이| 최대, 닫힌 고리가 없으면 F_k 노드 볼록 껍질.
4. 섬 I_k = 만족한 성분들의 합, 섬 노드 구분: 둘레(rim) = 섬 노드 ∩ F_k 노드, 내부 = 그 밖 섬 노드.
5. (a)는 만족하지만 (c)·(d) 를 못 넘은 성분 → 섬 아님(v0.16.0 대로 사면/안쪽 고리) + 경고 `SELECT_ISLAND_TOO_LARGE{n_elems, size_mm}`.
- 비용: 22만 요소 연결 성분 1회/비드(≈ 50 ms) — BS §5.8 derive ≤ 3 s 안.

### 5.3 구멍 분류 (자유 모서리)
- 구현 위치 = 공통 `esl.mesh.features.free_edge_components`(§5B.2).
- 자유 모서리 Efree = BM 요소 1개만 쓰는 모서리(`edge_count == 1 ∧ nin == 1`). Efree 노드 그래프의 연결 성분 c 마다:
  - c 의 노드 중 경계 노드(BM·비BM 공유)가 있으면 → **판 가장자리**(열린 경계, B4 유지) → `bd.open = True`.
  - 없으면 → **관통 구멍**: 열린 경계 판정에서 제외, `holes.n += 1`(섬 안이면 그 섬 `free_loops += 1`).
- `bd.open = (판 가장자리 성분 있음) ∨ (열린 경계 고리 있음) ∨ (고리 없음)` — `:780` 의 `free` 를 "판 가장자리 성분 있음" 으로 바꾼다. `_loops` 반환 두 번째 값 의미 변경(호출자 `_loops_of_mask` 는 무시 — 영향 없음).

### 5.4 폭 기저는 비드 경계 고리에만 (SR-D-7)
- 섬은 BM 안이므로 `_loops(BM)` 에 섬 둘레가 없다 → `_width` 의 ê·교차 선분·`wtree`(`:929-996`)는 코드 변경 없이 경계 고리만 쓴다.
- 섬이 아닌 안쪽 고리(바깥 고리 = |평면 넓이| 최대 닫힌 고리, 나머지)가 있으면 v0.16.0 대로 그 고리도 오프셋하고 경고 `SELECT_INNER_LOOP{n}` — 고리형 홈 비드는 이것이 맞는 동작.
- 섬 내부 노드: 폭 기저도 SR-D-5 규칙(둘레 평균) — f = 1 이면 둘레 = 바닥 조화 확장 값이라 섬이 바닥과 함께 평면 이동, f = 0 이면 0.
- 조화 확장(`_floor_harmonic:1223`)은 바닥 그래프만 — 구멍 둘레는 자연 경계(노이만), 섬 둘레는 바닥 내부 노드로 취급(식 불변).

### 5.5 섬 강체 이동 기저 (SR-D-5) — `_island_fill(bd, idx, vec)` 신규
- 변수 v 의 기저를 v0.16.0 대로 다 만든 뒤(비드 면내 사영·블렌딩 포함, `_width_basis:1211` 사영 뒤), 섬 I 마다 t_v,I = mean_{r ∈ rim(I)} B_v[r](둘레 노드에 값이 없으면 0) → 내부 노드 B_v[i] = t_v,I. 깊이·폭 공통, 묶음은 합친 기저에 1회.
- 진단: `island_dev_mm` = max_r ‖B_v[r] − t_v,I‖ × (기본 범위 한쪽 최대 변화) — 곡면 바닥에서 둘레·내부 차. > `fixed_tol_mm`×100 이면 경고 `SELECT_ISLAND_SHEAR{bead, k, dev_mm}`(표시만).

### 5.6 체결 구멍 둘레 고정(보스) 기저 (SR-D-9) — `_hold_factor(bd, nodes)` 신규
- 대상 고정 노드 P = 고정 노드 ∩ (그 비드 bead_nodes ∪ blend_nodes). P 가 비면 φ ≡ 1(경고 `SELECT_HOLD_NO_FIXED`).
- d(x) = x 에서 P 까지 최소 3D 거리(cKDTree). ρ = `hold.ring_mm`, b = `hold.blend_mm`:
  φ(x) = 0 (d ≤ ρ), 1 − β((d − ρ)/b) (ρ < d < ρ + b), 1 (d ≥ ρ + b), β = BS §5.5 Wendland C².
  → φ(ρ) = 0, φ(ρ + b) = 1, 양 끝 기울기 0(C¹ 이상 연속).
- 그 비드의 **모든 변수** 기저 행에 B_v[x] ← φ(x)·B_v[x](섬 채움 §5.5 뒤, `_compact` 앞 — 0 행은 `_compact` 가 지움). φ = 1 인 행은 곱하지 않아 바이트 불변.
- 결과: 링(고정 노드 + ρ) 은 제자리, 바닥은 D 만큼 이동 → 높이 ΔD 의 보스, 벽 폭 = b. 링 안 고정 노드 침범 0. 다른 비드 블렌딩이 같은 노드를 움직이면 그 비드 규칙대로(경고).
- 설정값 근거(Q2 = A 확정 2026-11-05): ρ 3 mm = 와셔 접촉 여유, b 8 mm = ΔD 6.6 mm(22 × 30 %)에서 벽 각 ≈ 40° → 품질 경고 최소.

### 5.7 고정·품질 판정 (`design_state`, SR-D-1)
```text
q = affected_quality(...); fx = fixed_violation(...)
if q.inverted > 0:                       -> FAILED_MESH / SELECT_MORPH_INVERTED
elif fx.violated and fixed_policy=skip:  -> SKIPPED_FIXED / SELECT_FIXED_VIOLATION
elif q.over_limit and fail_policy=skip:  -> FAILED_MESH / SELECT_QUALITY_FAIL
else READY, warnings += FIXED_MOVED(fx) if fx.violated, QUALITY_WARN(q) if q.over_limit
```
- 순서 변경 영향: v0.16.0 은 고정 침범 + 뒤집힘 동시 안을 `SKIPPED_FIXED` 로, v0.16.1 은 `FAILED_MESH` 로 기록(둘 다 실행 안 함 — 개수 표만 다름, §7.4).

## 5A. ④ 사다리 `defeature` 단계 (범위 A, SR-D-16~21)

### 5A.1 실행 위치·흐름 (`stages._cmp_ladder`, `mesh_refine`)
- `mesh_refine.STAGES = ("cad", "refine_local", "refine_global", "defeature", "remesh")`. `mesh_refine.plan("defeature", pm, h, cfg, avail, elapsed_s)` → 시도 2개 `[{stage: defeature, kind: None, factor: None, h_mm: h, mesh_h: h, compound: cfg.compound}, {…, compound: False, only_if: "compound_failed"}]` — 두 번째는 첫 시도가 **compound 면에서** 실패했을 때만(실패 면 key 가 그 시도의 compound 묶음에 속함), 아니면 건너뜀(`reason: not_compound`). 첫 시도에 compound 대상이 없으면 두 번째 없음. `check_limits`(시간·요소 예측 = 기본 h 예측과 같음)·`attempt_timeout`·시도 폴더 `try_<n>/`·`_promote` 는 v0.16.0 그대로(D-0.16-BUDGET·TRIES).
- `_cmp_ladder` 분기: stage == `defeature` → `mg.run_isolated(src, td, h, mr.attempt_cfg(ccfg, a), props, kind="cad", fail_info=True, timeout_s=…)`. `attempt_cfg` 는 사본 `mesh.defeature_stage = {crit: gdf.criteria(compare.defeature, h), compound: a.compound}` 를 넣는다(키 없으면 세션은 v0.16.0 그대로 — 다른 단계 바이트 불변).
- 세션 순서(`mesh_gmsh._session`, 변경 부분만): 가져오기 → nofix_face → **`gdf.holes`(기존 cad 단계와 같은 호출, `collect=feats` 만 추가)** → **`feats += gdf.find_features(gmsh, crit, kinds=…)` → `gdf.suppress(gmsh, feats, crit, h, compound=…)`** → v0.15.1 형상 폴백(실패 면) → size_fields(없음) → 메싱(v0.14.1 면 단위 폴백도 그대로 동작) → 품질 → **`gdf.reference_tris(gmsh_new_session, src, rc)` + `gdf.fidelity_split(...)`**(§5A.4) → `mesh.json.defeature_stage`·`defeature.json`.
- 성공(READY ∧ 바깥 충실도 fail 아님) → `_promote(..., {"mesh_method": "defeature", "cad_error": …, "attempts": …})`, 형상 행 `mesh_method: defeature`, 경고 `MESH_DEFEATURED`. 실패 → 다음 단계(보통 remesh). 억제 대상이 0개면 메싱하지 않고 `SKIPPED`(`reason: no_feature`, 정보 `DEFEATURE_NO_FEATURE`) — 같은 형상을 다시 메시하는 시간 낭비 방지.
- 재메시 단계(R2)는 계속 `gdf.holes` 만(C2-D-12 그대로). defeature 단계 결과를 재메시에 넘기지 않는다(단계 독립 — 사다리 순서를 바꿔도 각 단계 결과가 같음).

### 5A.2 BatchMesher 기준 대응 (`docs/reference/radioss_chr_3mm_batchmesh.md`)

| BatchMesher | 값 | 대응 종류 | 설정 키 | 처리(gmsh/OCC) |
|---|---|---|---|---|
| holes `shape(1) rad(0,4) action(1)` · `shape(62) eq_diam(0,8) action(1)` | r < 4 · 등가 지름 < 8 | `hole` | `hole_max_d_mm` 8 | 자유 모서리 고리 → `addCurveLoop`(기존 곡선) + `addPlaneSurface`(평면 ≤ `plane_tol_mm`) 또는 `addSurfaceFilling` → `occ.fragment`(이웃과 곡선 공유) |
| holes `shape(2) width(0,1.9) length(0,14) action(1)` | 슬롯 | `slot` | `slot_max_w_mm` 1.9 · `slot_max_l_mm` 14 | hole 과 같음. 폭·길이 = t² − (P/2)t + A = 0 의 두 근(사각 근사) |
| `appl_flanged_suppr 1` · `flanged_suppr_height 1.5` | 버링 높이 ≤ 1.5 | `flange` | `flange_max_h_mm` 1.5 | 버링 벽 면 묶음 제거 → 남은 둘레가 자유 고리 → 같은 실행 안에서 hole 규칙 |
| `beads_suppression 1` · `minimal_beads_height 2` | 높이 < 2 | `bead`(딤플·비드·엠보) | `min_bead_height_mm` 2 | 면 묶음 제거 → 둘레 고리(기존 곡선)로 평면/채움 면 — 이웃 공유 곡선 그대로라 fragment 불필요 |
| `surface_fillet_table` · `max_fillet_radius 9`(인식 0 = 끔) | – | `fillet` | `fillet_max_r_mm` 1.5(Q5) | 고체 = `occ.defeature`, 쉘 = `mesh.setCompound`(SR-D-18) |
| `merge_narrow_surfs 1` · `narrow_surfs_merge_width Lmin·0.5` | 폭 < 0.5·Lmin | `narrow` | `narrow_w_factor` 0.4 (·h) | 쉘 = `mesh.setCompound`(가장 긴 공유 곡선 이웃 1개와), 고체 = `occ.defeature` |
| holes `rad(4,30) elems(6) washer(1)` | 둘레 분할 | (cad 단계 기존) | `hole_elems`·`hole_r_mm` | v0.14.1 `gdf.holes` 그대로(washer 층은 비범위) |

### 5A.3 인식 규칙 (`gdf.find_features`, 형상 불변)
- 공통: 면 인접 그래프 G(곡선 공유), 곡선별 인접 면 수 `getAdjacencies(1, c)`. 크기는 모두 mm, 좌표는 STEP 그대로. 결정적 순회 = 면·곡선 태그 오름차순.
- **hole·slot**: 자유 곡선(인접 면 1개)으로 이은 닫힌 고리들(쉘 전체 — 면 경계에 묶지 않음, seam 끝점·여러 면 통과 허용 → v0.14.1 이 남긴 구멍 포함). 쉘 바깥 경계 = 자유 고리 중 평면 투영 |넓이| 최대(연결 쉘 성분마다 1개)는 제외. A = Newell 투영 넓이, P = 곡선 길이 합, d_eq = 4A/P. `hole` ⇔ d_eq ≤ `hole_max_d_mm`, 아니면 `slot` 판정. 이미 cad 단계 `gdf.holes` 가 메운 고리는 `collect` 목록으로 들어오고(method `holes_v0141`) 다시 세지 않음.
- **flange**: 바탕 면 B 의 안쪽 고리 L 이 구멍이 아님(`is_hole` 거짓 — 이웃 면 공유) ∧ L 건너편 면 묶음 C(B 를 지나지 않는 G 의 BFS) 가 자유 고리를 정확히 1개 가짐 ∧ C 의 bbox 대각 ≤ `feature_max_mm`. 높이 h_C = C 각 면 bbox(`getBoundingBox`) 8 꼭짓점을 L 최소제곱 평면 법선 n_L 에 투영한 거리 최대(위쪽 근사 — n_L 이 축과 나란하면 정확, 기울면 크게 나옴 → 억제가 줄어드는 쪽, 경계값에서 결정적). ≤ `flange_max_h_mm` 이면 flange.
- **bead**: 위와 같은 C 가 자유 고리 0개(닫힌 둘레 L 하나로만 B 에 붙음) ∧ bbox 대각 ≤ `feature_max_mm` ∧ h_C < `min_bead_height_mm`. C 에 든 필렛 면(딤플 둘레 필렛)은 bead 의 일부(따로 fillet 으로 세지 않음). C 가 BFS 중 크기 상한을 넘으면 즉시 중단(비용 상한).
- **fillet**: 면 종류 Cylinder·Torus(또는 BSpline 이면서 주곡률 하나 ≈ 0) ∧ 반경 r = 1/max|κ|(면 매개 중앙 `getPrincipalCurvatures`) ≤ `fillet_max_r_mm` ∧ 정확히 두 이웃과 곡선 2개 이상 공유(띠 모양). 원통 구멍 벽·버링 벽(자유 고리 포함)은 제외.
- **narrow**: fillet 아님 ∧ 폭 w(사각 근사 작은 근) < `narrow_w_factor`·h ∧ 길이 > w.
- 특징 수 > `max_features` → 종류 순서·태그 순서로 앞에서 자르고 경고 `DEFEATURE_TOO_MANY{n, max}`.

### 5A.4 실행·충실도 (`gdf.suppress`, `gdf.reference_tris`, `gdf.fidelity_split`)
- 실행은 종류 순서(`kinds`), 특징마다 try → 실패하면 그 특징만 `action: skipped, reason` 하고 형상은 직전 상태(`occ` 작업 전에 대상 태그 목록만 확정, 실패 시 새로 만든 엔티티 제거) — 한 특징 실패가 단계 전체를 막지 않음. flange 제거 뒤 생긴 자유 고리는 같은 호출 안에서 hole 규칙으로 다시 판정.
- compound: 쉘 fillet·narrow 묶음을 `setCompound(2, tags)`(서로 겹치는 묶음은 합침). `compound=False` 면 fillet·narrow 는 모두 `skipped, reason: compound_off`.
- 충실도: 메싱 성공 뒤 같은 자식에서 `gmsh.clear()` 후 원 STEP 을 같은 정리 옵션으로 다시 가져와 OCC 삼각화(`mesh_remesh` R3 의 삼각화 함수를 `gdf.reference_tris` 가 호출 — 코드 1곳) → S0. `fidelity_split` = C2-D-13 `mesh_remesh.fidelity` 와 같은 샘플링·k=8 후보·정확한 점-삼각형 거리, 샘플을 Ω = ∪Ω_f 안/밖으로 나눔. 바깥 지표가 `remesh.fidelity.fail_mm` 초과 → 시도 실패 `DEFEATURE_FIDELITY`(다음 단계), warn 초과 → 경고 `REMESH_FIDELITY_WARN` 재사용. 특징별 `dev_mm` 은 Ω_f 샘플 최대(구멍 ≈ 반지름, 딤플 ≈ 높이). compound 면은 형상 그대로라 Ω 에 넣지 않음(바깥 지표에 포함).
- 시간: reference_tris + fidelity 는 시도 제한 시간 안. 넘으면 시도 실패(TIMEOUT) — 다음 단계.

### 5A.5 기록·표시
- `mesh/defeature.json`(SR-D-20), `mesh.json.defeature_stage`, 형상 행(`DoeStudyOut.prep(compare).shapes[]`·`ranking[].shape`) += `defeature?: {n, counts, skipped_n, suppressed_max_mm, outside_hausdorff_mm}`(defeature 형상만), ranking.csv `mesh_method` 열 값 `defeature`.
- `COMPARE_MESH_METHOD_MIXED`(D-0.16-MIXED): defeature 는 refine·remesh 와 같은 "비 cad" 방식으로 센다.
- 보고서(`report_doe.py`): 형상 표 메시 방식 "형상 단순화", 절 **"작은 형상 억제"**(형상별 종류별 개수·억제 영역 최대 편차·바깥 Hausdorff, 목록 상위 20행), 프로필 문단의 "비드 억제 기준 … (기록만 — 미적용)" → "(defeature 단계에서 적용)".
- 실패 문구(D-0.16-LADDER-MSG): `LADDER_STAGE_LABEL["defeature"] = "형상 단순화"`.

## 5B. 공통 모듈 (범위 B, SR-D-22~24)

### 5B.1 `esl/geom/defeature.py` — CAD 단계 인식·억제 (소유 **Impl-Core**)
gmsh 모듈을 인자로 받고 **현재 gmsh 세션** 안에서만 동작(초기화·종료는 호출자). 설정 dict 는 호출자가 넘김(DEFAULTS 직접 참조는 `criteria` 의 기본값 채움만).

```python
# 위상 도우미 — mesh_gmsh 에서 이동(본문 그대로), mesh_gmsh 는 같은 _이름으로 재노출
def loop_length(occ, curves: list[int]) -> float                        # = mesh_gmsh._loop_info
def face_loops(gmsh, s: int) -> list[list[int]]                         # = _face_loops
def curve_points(gmsh, c: int) -> set[int]                              # = _curve_points
def seam_points(gmsh, s: int) -> set[int]                               # = _seam_points
def is_hole(gmsh, s: int, cl: list[int], seam_pts: set[int]) -> bool    # = _is_hole (v0.14.1)
def bbox_key(gmsh, dim: int, tag: int) -> tuple                         # = _bbox_key
def key_near(a: tuple, b: tuple, tol: float = 1e-4) -> bool             # = _key_near

def criteria(df: dict, h: float) -> dict
    """compare.defeature(+기본값) → 절대 기준 {kinds, hole_max_d, slot_max_w, slot_max_l, flange_max_h, bead_min_h,
    fillet_max_r, narrow_w (= narrow_w_factor·h), feature_max, plane_tol, region_pad (= region_pad_factor·h),
    max_features, list_max}. 검증 실패 → EslError CONFIG_INVALID."""
def holes(gmsh, df: dict, h: float, skip_keys: tuple = (), *, collect: list | None = None) -> dict
    """v0.14.1 mesh_gmsh.defeature 본문 그대로(반환 {filled, filled_area_max, hole_sized, skipped, warnings, …}).
    collect 가 list 면 메운 고리마다 특징 dict(kind hole, method holes_v0141)를 덧붙임 — None 이면 동작·반환 바이트 불변."""
def find_features(gmsh, crit: dict, *, kinds: tuple[str, ...] | None = None) -> list[dict]
    """§5A.3 인식만(형상 불변). 특징 = {id, kind, faces, curves, base_face, key(bbox6), center[3], size{d_mm|w_mm,l_mm|h_mm|r_mm},
    area_mm2}. 순서 결정적(SR-D-20)."""
def suppress(gmsh, feats: list[dict], crit: dict, h: float, *, compound: bool = True) -> dict
    """§5A.4 실행. 반환 {features(+action suppressed|skipped, method plane|filling|removed+hole|occ_defeature|compound,
    reason?), counts{kind: n}, n, skipped_n, compound_groups[[tag…]], warnings}. occ.synchronize 포함."""
def reference_tris(gmsh, src: str, mc: dict, rc: dict) -> tuple[np.ndarray, np.ndarray]
    """원 STEP 을 mc 정리 옵션으로 다시 가져와 OCC 삼각화(S0) — mesh_remesh R3 와 같은 삼각화 함수."""
def fidelity_split(S_X, S_T, mesh: dict, h: float, rc: dict, feats: list[dict], pad_mm: float) -> dict
    """SR-D-19 {outside: C2-D-13 지표, per_feature: {id: dev_mm}, suppressed_max_mm}. 특징 dict 에 dev_mm 을 채움."""
```
| 호출 지점 | 사용 함수 | 기본 동작 |
|---|---|---|
| `mesh_gmsh.defeature(gmsh, df, h, skip_keys)` | `return gdf.holes(gmsh, df, h, skip_keys)` 1줄(래퍼 — 기존 호출자·시험 그대로) | 바이트 불변(V-SR-16) |
| `mesh_gmsh._session` ④ cad·refine(`compare_cfg` 가 `mesh.defeature` 주입) | `holes`(래퍼 경유) | 불변 |
| `mesh_gmsh._session` ④ defeature 단계(`mesh.defeature_stage` 있을 때만) | `holes(collect=)`·`criteria`·`find_features`·`suppress`·`reference_tris`·`fidelity_split` | 새 단계 |
| `mesh_gmsh._session` ③ 베이스라인 `stages.py:249`·③ 안 BREP `:478` | `holes`(`bead_doe.mesh.defeature` 가 있을 때만 — 기본 없음) | 불변(C19) |
| `mesh_remesh.remesh_file` R2 `:324-326` | `mg.defeature`(래퍼) → `holes` | 불변 |
| (예약) STEP 모핑(③ 전환, 보류) | `find_features`(모핑 대상에서 뺄 작은 형상·체결 구멍 인식) | 시그니처만 |

### 5B.2 `esl/mesh/features.py` — 메시 단계 섬·구멍 분류 (소유 **Impl-Core**)
numpy/scipy 만(gmsh 불필요). 노드·요소 **인덱스** 기반.

```python
class MeshIndex: ...                                     # bead_select 에서 이동(본문 그대로), bead_select 는 재노출
def mesh_index(mesh: dict) -> MeshIndex
def node_graph(ix: MeshIndex, emask: np.ndarray) -> sparse.csr_matrix          # = bead_select._node_graph
def boundary_loops(ix: MeshIndex, mask: np.ndarray, *, edge_nodes: np.ndarray | None = None) -> tuple[list[dict], bool]
    """= bead_select._loops. edge_nodes(판 가장자리 노드)를 주면 두 번째 반환 = '판 가장자리 자유 모서리 있음'(§5.3),
    None 이면 v0.16.0 의미(자유 모서리 하나라도) — 호출자별 의미 고정."""
def split_outer_inner(loops: list[dict], X: np.ndarray, n_ref: np.ndarray) -> tuple[int | None, list[int]]
    """바깥 고리 = 평면 |넓이| 최대 닫힌 고리, 나머지 = 안쪽(SR-D-7)."""
def free_edge_components(ix: MeshIndex, mask: np.ndarray, boundary_nodes: np.ndarray) -> dict
    """§5.3. {edge: [nodes…](경계 노드에 닿는 성분 = 판 가장자리), holes: [{nodes(순서), perim_mm, eq_d_mm, center[3]}]}."""
def enclosed_components(ix: MeshIndex, cand: np.ndarray, owner: np.ndarray, X: np.ndarray, n_ref: np.ndarray, *,
                        max_mm: float, outer_poly: dict[int, np.ndarray] | None = None) -> dict
    """§5.2 일반형. cand = 후보 요소 마스크, owner = 요소별 주인 번호(≥ 0 = 주인, −1 = 후보, −2 = 막힘).
    성분 K 가 섬 ⇔ 이웃 주인이 하나(≥0) ∧ 최대 성분 아님 ∧ bbox 대각 ≤ max_mm ∧ (outer_poly 있으면) 중심이 그 주인 다각형 안.
    반환 {islands: [{owner, elems, rim, interior, size_mm}], too_large: [{owner, n_elems, size_mm}]}, 성분 번호 = 최소 요소 순."""
def feature_segments(ix: MeshIndex, feature_angle_deg: float) -> np.ndarray      # 이면각 > 기준 모서리로 나눈 요소 영역 번호
def diagnose(mesh: dict, *, feature_angle_deg: float, hole_max_d_mm: float, island_max_mm: float,
             index: MeshIndex | None = None) -> dict
    """SR-D-24 {holes_n, holes_small_n, islands_n, free_loops_n, small_holes: [{center, eq_d_mm}] ≤ 50}. 섬 = feature_segments 중
    bbox 대각 ≤ island_max_mm 인 영역을 cand, 그보다 큰 영역 번호를 owner 로 한 enclosed_components."""
```
| 호출 지점 | 사용 함수 | 기본 동작 |
|---|---|---|
| `bead_select` 전역(`MeshIndex`·`mesh_index`·`_node_graph`·`_loops`) | 이동 + 재노출(`from esl.mesh.features import …`) | 바이트 불변(V-SR-1) |
| `bead_select._derive_bead` §5.2·§5.3 | `enclosed_components`(owner = 단 번호), `free_edge_components`, `boundary_loops(edge_nodes=)`, `split_outer_inner` | 새 규칙(섬·구멍 없으면 v0.16.0 과 같음) |
| (예약) v0.16.2 P3 '자동 탐지 → 같은 UI': paicad 비드 영역 → `SelectionIn` 초기 선택(`paicad_io.beads_table` 결과 → 단 바닥 요소) | `enclosed_components` 로 영역 안 섬을 F 에서 빼고 섬으로 둠(derive 와 같은 규칙) | 시그니처만 |
| `mesh_input.read_shape_mesh` 뒤(④ 메시 입력) | `diagnose` | 보고만(SR-D-24) |
| 브라우저 `view3d/select/grow.ts` `enclosedIslands` | 거울 구현(같은 위상 규칙) | V-SR-12 픽스처 동일성 |

- 의존 방향: `esl.mesh.features` ← `esl.doe.bead_select`·`esl.doe.mesh_input`(역방향 import 금지). `esl.geom.defeature` ← `esl.doe.mesh_gmsh`·`esl.doe.mesh_remesh`(역방향은 삼각화 함수 1개 — `reference_tris` 안에서 지연 import). 새 패키지 `esl/geom/__init__.py`·`esl/mesh/__init__.py` 는 비움.

## 6. 정책 변경의 영향

| 단계 | 변경 | 파일 |
|---|---|---|
| 미리보기 | 셀 `status OK` + `warnings`·`fixed_viol`, 상태 집계 `counts += warn`(경고 READY 수). 색 범위 V 는 READY(경고 포함) 안 기준 | `stages.py:2204-2269` |
| 실행 | 실행 대상 = 미리보기 READY(경고 포함). `bd_eval` 스킵 문서는 state ≠ READY 일 때만(`:504-516` 그대로), READY 면 `result.json.warnings` 기록 | `stages.py:488-516` |
| 순위·민감도 | 경고 안 포함(SR-D-11). 순위 행 `warn`, `post.json.summary.best_clean`(경고 없는 최상위 id 또는 null) | `stages.py` BD_POST, `esl/doe/rank.py`(행 키만) |
| 보고서 | 순위 표 ⚠ 열, 안 상태 표 "경고" 열, 절 **"체결 위치 어긋남"**(경고 안 id·n·최대 mm·원인 변수 상위 3), 1위가 경고 안이면 요약 상자 경고 문구 | `esl/doe/report_doe.py` |
| 받기 | 경고 안 `best/<did>/`: rad/include 사본 첫 `/NODE` 앞에 `#ESL WARNING FIXED_MOVED n=<n> max_mm=<x> : fastener positions moved, check RBE2/TIE` + `#ESL WARNING FIXED_NODES <id> …`(줄당 10개, 최대 50개) — 원본 줄바꿈 바이트(`\r\n`/`\n`) 따름. `ch_r.rad` header 에 같은 줄, `values.json.warnings`. 품질 경고는 `values.json` 만 | `stages.py:_sel_best`(2317-2339), `esl/doe/nodes.py`(`write_morphed(..., comment_lines=)` 인자 추가) |
| 검증 낙하 | 변경 없음(경고 사본도 같은 형식) | – |
| 화면 | §8 | 프런트 |

## 7. 이어하기 · sha 영향

### 7.1 선택 sha
- 기존 선택(키 `hold_fixed` 없음) → 정규화 결과 동일 → **sha 불변**. `hold_fixed: 1` 을 켜면 sha 변경(정상 — 선택 변경).

### 7.2 설정 해시 (`_cfg_hash` `stages.py:421`, `_sel_cfg_sha` `:2142`)
- `select_hash_view(cfg)` 신규(`bead_select.py`): `cfg["select"]` 깊은 사본에서 **v0.16.1 새 키**(`fixed_policy`, `quality.fail_policy`, `range.depth_max_rel`, `range.width_max_rel`, `island`, `hold`)가 기본값과 같으면 제거. 두 함수 모두 이 사본을 쓴다 → 기본 설정이면 v0.16.0 해시와 같음.
- 이 목록은 `bead_select.HASH_NEW_KEYS_V0161` 상수 1곳 — 이후 판에서 키를 추가할 때도 같은 방식.

### 7.3 기저
- `basis.json += algo: 2`. 재사용 조건(`stages.py:2105-2109`)에 `bj.get("algo", 1) == ALGO` 추가 → v0.16.0 기저는 다음 BD_MATRIX 에서 1회 재계산(≤ 30 s).
- 섬·구멍·hold 가 없는 선택 → 재계산 결과 **basis.npz 바이트 동일** → basis_sha 동일 → 안 input_sha256(`:440-443`) 동일 → 해석 결과 재사용.
- 섬·구멍이 있는 선택 → 기저 변경(의도된 결과 변경) → 그 스터디의 안 해시 변경 → 재해석. 구멍 때문에 W 가 없던 비드는 W 변수가 새로 생김(기존 matrix 에 W 가 없으면 형상에는 영향 없지만 기저 sha 가 바뀌어 재해석).

### 7.4 판정 규칙 판 (미리보기·실행)
- `grid_manifest.rules = 2`. 백엔드 `preview_cells` 는 `rules` 없는 미리보기에 `rules_outdated: true` 를 붙이고, 화면은 띠 1줄 "판정 규칙이 바뀌었습니다 — 다시 미리보기하면 경고 안도 실행됩니다"(실행은 막지 않음 — 그 미리보기의 READY 안만 실행).
- 안 재사용(SR-D-13d): select 의 `bd_eval` 은 재사용 전에 `design_state` 를 다시 계산. 현재 state ≠ READY → 스킵 문서(재사용 안 함). 현재 READY ∧ 이전 done 상태 OK → 재사용(OK 만 재사용 — FAILED_SOLVE 는 `ev.reusable` 이 재시도 대상으로 거름). 현재 READY ∧ 이전 `SKIPPED_FIXED` → 재사용 안 함(해석).

### 7.5 이미 끝난(DONE) 스터디
- 결과·보고서·받기 파일 변경 없음(자동 재생성 없음). 복제(`clone`)하면 선택 sha 그대로 복사, 새 규칙으로 미리보기부터.
- DB `selection.derived` 에 `algo` 가 없으면 `GET …/selection`·`params`·`plan-view` 때 서버가 다시 derive 해 DB 요약을 갱신(rev·sha·`version` 불변 — 계산 캐시 갱신이라 사용자 편집 충돌 없음).

### 7.6 버전
- `VERSION` 0.16.1, `CHANGELOG.md`, `openapi` info.version. migration 없음(`selection` JSONB 안 키 추가, 시나리오 CHECK 불변).

### 7.7 ④ defeature 단계 · 공통 모듈의 해시·바이트 (SR-D-21)
- **base.json `profile`**: `prof_rec["defeature"]` = `compare.defeature` 에서 `stages.DEFEAT_NEW_KEYS_V0161`(§4.4 새 키 목록 상수 1곳)을 **값과 무관하게** 뺀 사본 → base.json·`profile_sha256` 은 v0.16.0 과 바이트 동일, 새 키를 바꿔도 cad 성공 형상 해시 불변. `min_bead_height_mm`(기존 키)는 그대로 들어간다(값 변경 = v0.16.0 과 같은 해시 변경).
- **`_cmp_sha`**: 형상 행 `mesh_method == "defeature"` 일 때만 `keep["defeature_cfg"] = config_hash({k: compare.defeature[k] for k in DEFEAT_NEW_KEYS_V0161} | {min_bead_height_mm})`. 메시 sha(형상 mesh.npz)가 이미 keep 에 있어 억제 결과가 바뀌면 해시도 바뀐다 — 이 키는 설정만 바꾸고 메시가 우연히 같을 때를 위한 것.
- **사다리**: `keep["ladder"]`(mode ≠ cad 만)는 스냅샷 `mesh_ladder`. v0.16.0 스냅샷(defeature 없음) → 해시·동작 불변. 새 스터디는 기본 사다리에 defeature 포함 — 새 스터디라 비교 대상 해시 없음.
- **메시 입력**: `keep["mesh_input"] = config_hash(mi._mcfg(cfg))` 계산 전에 `diag` 절을 뺀다(`mesh_input.hash_view`) → 메시 입력 형상 해시 불변.
- **공통 모듈 이동**: 함수 본문 이동 + 재노출만 — 같은 입력에 같은 출력. mesh_gmsh·bead_select 의 기존 시험·픽스처 바이트 비교(V-SR-1·16)로 고정.
- **③**: `bead_doe.mesh` 에 키 추가 없음 → `_cfg_hash`(`stages.py:421`, `mesh` 절 포함) 불변.

## 8. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 필수만)

| 위치 | 추가 | 파일 |
|---|---|---|
| 미리보기 칸 | ⚠ 배지 + 1줄 "고정 노드 n개, 최대 x mm 이동"(침범 시), 품질 경고는 배지 툴팁 "새 Fail m (r %)". 뒤집힘 = 기존 ⨯ 배지 | `components/DoeThumbGrid.tsx`, `FixedViol.tsx`(경고 칸에도 표시) |
| 비드 목록 | 비드 행에 체크 1개 **[체결 구멍 둘레 고정]**(`hold_fixed`, 비드 안·블렌딩 안 고정 노드가 있을 때만 활성, 툴팁 "링 3 mm 제자리 · 8 mm 블렌딩") + 요약 글자 "섬 3 · 구멍 2" | `components/BeadList.tsx` |
| 3D 선택 | 섬 = 그 단 색의 밝은 단계(새 층 아님), 클릭 확장 직후 표시(SR-D-14) | `view3d/select/grow.ts`(`enclosedIslands`), `layers.ts`(`elemColors` 섬 색), `BeadSelectCard.tsx` |
| 결과 카드·순위 | 순위 행 ⚠, 요약 "경고 없는 최상위: d0xx"(1위가 경고 안일 때만) | `pages/doe/DoeStudy.tsx`, 기존 결과 컴포넌트 |
| 띠 | `rules_outdated` 1줄(§7.4) | `DoeStudy.tsx` |
| ④ 형상 표 | 메시 방식 "형상 단순화"(defeature), 툴팁 "구멍 a · 딤플 b · 필렛 c · … 억제, 억제 영역 최대 x mm, 그 밖 y mm" + 시도 목록(기존) | 기존 형상 표 컴포넌트(`pages/doe/` compare 준비 표), `api/types.ts` |
| ④ 형상 상세(펼침) | 억제 목록 표(종류·중심 xyz·크기·편차, 상위 50행 + "외 n개") — 새 API 없이 형상 행 `defeature` 요약 + `GET /doe/studies/{sid}/shapes/{did}/defeature`(§9) | 같은 컴포넌트, `api/doe.ts` |
| ④ 형상 표(메시 입력) | 진단 글자 "작은 구멍 n · 섬 m"(있을 때만) | 같은 컴포넌트 |

## 9. API 변경 (`/esl/api`)

| 경로 | 변경 |
|---|---|
| `POST …/select/derive`·`PUT …/selection` | 요청 `BeadSel.hold_fixed`, 응답 BeadDerived `islands`·`holes`·`inner_loops_n`·`hold`, `algo`, derive 응답 `islands_suggested`. 422 `SELECT_HOLD_INVALID` |
| `GET …/params`(select) | `feasible` = SR-D-10, `use_default` = SR-D-8(백엔드 `doe_select.params_table:300-357` 가 `fixed_policy` 읽음). W 행 조건 = 열린 경계 아님(구멍은 열린 경계 아님 — 코어 derived 의 `w_enabled` 를 그대로 사용하도록 `:343-345` 수정) |
| 미리보기 셀(`preview_cells` `doe.py:713-746`) | `warnings`(있을 때만), `fixed_viol`(침범 있으면 상태 무관), `rules_outdated` |
| `GET /doe/settings` | §4.4 |
| 결과(`result`·순위) | 행 `warn`, `summary.best_clean` |
| ④ 준비·결과 형상 행 | `mesh_method` Literal += `"defeature"`, `defeature?`(§5A.5), `diag?`(SR-D-24), attempts `stage` += `"defeature"`, `reason` += `"no_feature"`·`"not_compound"` |
| `GET /doe/studies/{sid}/shapes/{did}/defeature` (신규, 읽기, `routers/doe.py`) | `mesh/defeature.json` 그대로(없으면 404 `NOT_FOUND`). 권한 = 스터디 읽기와 같음 |
| `POST …/doe` compare 준비 | `mesh_ladder` 검증 단계 집합 += defeature(백엔드 `doe.py:540-548` — `mesh_refine: false` 는 `refine_*` 만 뺌) |
- 스키마: `backend/esl_platform/api/schemas.py`(`SelectBeadIn.hold_fixed: Literal[0, 1] | None`, `SelectionDerived` 칸, 셀·순위 칸 Optional), `frontend/src/api/types.ts` 거울, `openapi` 재생성(`check:api`).

## 10. 오류·경고 코드 (신규, 문구 원본 `resources/doe_messages.json`)

| 코드 | 종류 | 의미 |
|---|---|---|
| `SELECT_FIXED_MOVED` | 안 경고 | 고정 노드 n개 최대 x mm 이동(warn 정책) — 화면 "체결 위치 어긋남" |
| `SELECT_QUALITY_WARN` | 안 경고 | 새 Fail 비율 > 상한 또는 요소 극단값(넓이 비 < area_ratio_min ∨ 법선 회전 > rot_warn_deg — `area_ratio_min`·`rot_max_deg` 키, SR-D-40)(warn 정책) |
| `SELECT_INNER_LOOP` | derive 경고 | 섬이 아닌 안쪽 고리 n개 — v0.16.0 대로 처리. 모두 고리형 둔덕(ring = n)이면 `level: "info"`(SR-D-25, 문구 `SELECT_INNER_LOOP_RING`) |
| `SELECT_W_RANGE_RESET` | derive 경고 | W 기본 하한 > 공칭 → 분위값·공칭 기준으로 고침(SR-D-32) |
| `SELECT_RANGE_INVERTS` | 기저 경고(BD_MATRIX) | 기본 범위 끝 뒤집힘 + 쓸 수 있는 범위 `usable`(SR-D-33) |
| `SELECT_BEAD_NETWORK` | derive 경고 | 비드가 다른 비드와 이어짐(T·L 교차) — 교차부 사면 Voronoi 분할(SR-D-29) |
| `SELECT_SLOPE_ABOVE_PLATE` | derive 정보(`level: "info"`) | 판 높이 위로 나간 사면 요소 n개를 빼고 다시 탐색(SR-D-28) |
| `SELECT_BASE_AMBIGUOUS` | derive 오류(422) | 교차하는 비선택 비드 때문에 판 쪽 노드로도 기준 평면이 안 정해짐 — 교차 비드 함께 선택(SR-D-36) |
| `SELECT_BASE_REFIT` | derive 정보(`level: "info"`) | 판 쪽 경계 노드만으로 기준 평면 다시 맞춤{n_excluded, rms_mm}(SR-D-36) |
| `SELECT_FEATURE_DISTORTED` | 안 FAILED_MESH | 비드 안 비선택 피처 왜곡{bead, k, dev_mm, floor_mm}(SR-D-37) |
| `SELECT_CROSS_BEAD_MOVE` | 안 경고 | W 변화가 다른 선택 비드 경계·바닥 이동{n, max_mm, beads}(warn, SR-D-38) |
| `SELECT_CROSS_BEAD_VIOLATION` | 안 SKIPPED_COLLISION | 위와 같음, `cross_bead_policy: skip`(SR-D-38) |
| `SELECT_RANGE_COMBO` | 선택 경고(BD_MATRIX) | usable 끝 조합 뒤집힘 + 함께 쓸 범위{scale, usable}(SR-D-39) |
| `SELECT_W_RANGE_LIMIT` | derive 경고 | W 범위 끝 경계 이동 > 단 간격·이웃 거리 절반(SR-D-39) |
| `MORPH_EXTREME_ELEMENTS` | 안 경고(자동 탐지 기본 모핑) | 공통 모핑 코어 사후 점검 극단 요소{area_ratio_min, rot_max_deg}(SR-D-44) |
| `SELECT_ISLAND_TOO_LARGE` | derive 경고 | 둘러싸였지만 `island.max_mm` 초과 — 섬 아님 |
| `SELECT_ISLAND_SHEAR` | derive 경고 | 곡면 바닥에서 섬 평행 이동과 둘레 차(표시만) |
| `SELECT_HOLD_NO_FIXED` | derive 경고 | `hold_fixed` 1 인데 대상 고정 노드 없음 |
| `SELECT_HOLD_INVALID` | 422 | `hold_fixed` 형식 |
| `MESH_DEFEATURED` | 형상 경고 | "CAD 메시 실패 → 작은 형상 {n}개 억제({counts}), 억제 영역 최대 {suppressed_max_mm} mm · 그 밖 최대 {outside_mm} mm: {first}" |
| `DEFEATURE_FIDELITY` | 시도 실패 코드 | 억제 뒤 메시가 억제 영역 밖에서 원 STEP 과 `fail_mm` 초과 차이 → 다음 단계 |
| `DEFEATURE_NO_FEATURE` | 정보 | defeature 단계에 억제 대상 없음 — 건너뜀 |
| `DEFEATURE_TOO_MANY` | 형상 경고 | 특징 수 > `max_features` — 앞에서 자름 |
| `MESH_INPUT_DIAG` | 정보 | 메시 입력에 작은 구멍 n·섬 m(보고만) |
- derive 경고 dict 의 `level: "info"` = 정상 안내(⚠ 개수·`selection.n_warnings` 제외, 화면 ⓘ). 없으면 경고.
- 기존 `SELECT_FIXED_VIOLATION`·`SELECT_QUALITY_FAIL` 은 `skip` 정책에서만 나온다. `SELECT_OPEN_BOUNDARY` 는 판 가장자리 성분일 때만.

## 11. 시험 (V-SR-*)

**`tests/doe/synth_bead.py` 확장**: `generate(..., features: bool = False)` — 기본 False 는 메시·표지 **바이트 동일**. True 면 b1 단1 바닥(평면 구간)에 (1) Ø10 관통 구멍, (2) 딤플 3개(Ø16·깊이 3, 하나는 위로 볼록), (3) 버링 1개(Ø10 구멍 + 높이 4 칼라), (4) 체결 구멍 1개(Ø8 구멍 + 둘레 고정 노드 고리 → `fixed_ids` 에 추가). 정답 표지 `label` += `'b1i'`(섬)·`'hole'`, 반환 `islands`(섬별 요소·둘레 노드), `hole_rims`.

| ID | 시험 | 위치 |
|---|---|---|
| V-SR-1 | **무변경 회귀**: `features=False` 로 기존 V-BS-1~11 전부 통과 + derive 요약·basis.npz·basis.bin·썸네일 PNG·grid 셀(경고 없는 칸) **바이트 동일**(v0.16.0 커밋 기대값 픽스처 `tests/fixtures/bead_select/` 재사용), `select_hash_view` 기본 설정 = v0.16.0 dict | `tests/doe/test_bead_select_morph.py`·`test_select_render.py` |
| V-SR-2 | **섬 판정**: features 메시에서 섬 = 정답 4개(딤플 3·버링 1), 체결 구멍·관통 구멍은 섬 아님(요소 없음), 단 사이 벽(2단 포개짐)은 섬 아님, `max_mm` 10 으로 낮추면 `SELECT_ISLAND_TOO_LARGE` + v0.16.0 동작, 섬 요소를 `exclude` → `SELECT_INNER_LOOP` | `tests/doe/test_bead_select_derive.py` |
| V-SR-3 | **구멍**: 관통 구멍·버링 구멍 → `holes.n`·`free_loops`, `SELECT_OPEN_BOUNDARY` 없음, W 변수 존재. 판 가장자리 비드(`open_end`)는 그대로 열린 경계 | 같은 파일 |
| V-SR-4 | **경계 고리**: features 메시 b1 경계 고리 = features 없는 메시와 같은 노드 순서(바깥 고리 1개), `inner_loops_n` 0, W_nom·W_min·W_max = features 없는 값 ± 1e-9 | 같은 파일 |
| V-SR-5 | **섬 강체 이동**: D1 +3 → 섬 내부 노드 변위 = 둘레 평균(1e-12), 평면 바닥에서 = 바닥 변위(1e-9), 딤플 벽 길이·각 불변(1e-9), 위로 볼록 딤플도 같음. W +6(f=1) → 섬 평면 평행 이동, 면외 ≤ 1e-9 | `test_bead_select_morph.py` |
| V-SR-6 | **구멍 둘레**: 구멍 둘레 노드 변위 = 이웃 바닥과 같은 식(D: n_i^k, W f=1: 조화 확장 연속 — 이웃 변위 차 ≤ (ΔW/2)·(h/L)·c) | 같은 파일 |
| V-SR-7 | **폭 기저 = 바깥 고리**: W ±6 에서 딤플 둘레 상대 형상 불변(섬 내부 노드 쌍 거리 불변 1e-9), 국부 폭 변화 = ΔW ± 0.02h | 같은 파일 |
| V-SR-8 | **hold**: `hold_fixed` 1 → 고정 노드·ρ 안 노드 바이트 불변, d ≥ ρ + b 노드는 hold 0 결과와 바이트 동일, φ 연속(ρ·ρ+b 양쪽 첫 줄 차), 보스 높이 = ΔD ± 1e-9, `SELECT_FIXED_MOVED` 없음. hold 0 → `SELECT_FIXED_MOVED{n, max_mm}` 의 n·max = 정답 | 같은 파일 |
| V-SR-9 | **판정**: warn 정책 — 침범 안 READY + `SELECT_FIXED_MOVED`, 새 Fail 초과 안 READY + `SELECT_QUALITY_WARN`, 뒤집힘(W −40 %) `FAILED_MESH`, 침범+뒤집힘 동시 → `FAILED_MESH`. skip 정책 — v0.16.0 V-BS-4·7 기대값 그대로 | `test_bead_select_morph.py`·`test_mesh_quality.py` |
| V-SR-10 | **sha·이어하기**(구현: `worker/tests/test_doe_select_relax_jobs.py` — 상수 = ef7545c 트리 계산값): hold 없는 v0.16.0 선택 JSON → sha 동일, hold 1 → 다름; 기본 설정 `_cfg_hash`·`_sel_cfg_sha` = v0.16.0 값(상수 기대값); `algo` 없는 basis.json → 재계산 후 같은 바이트; v0.16.0 `SKIPPED_FIXED` done.json + warn → 재해석, OK done.json → 재사용 | `worker/tests/test_doe_select_jobs.py` |
| V-SR-11 | **받기·보고서**: 경고 안 rad 사본 = 원본과 "삽입 주석 줄 + /NODE 좌표 칸" 외 바이트 동일, 주석 ASCII·원본 줄바꿈, 경고 없는 안은 v0.16.0 V-BS-14 그대로, `ch_r.rad` 머리 주석, 보고서 "체결 위치 어긋남" 절·⚠ 열·`best_clean` | `worker/tests/test_doe_select_jobs.py`·`test_doe_select_e2e.py` |
| V-SR-12 | **브라우저 섬**: `enclosedIslands` 가 합성 소형 픽스처(features)에서 코어 `islands` 와 같은 요소 집합, 22만 요소에서 클릭 확장 + 섬 ≤ 150 ms, 섬은 `toSelectionIn` 출력에 없음 | `frontend/__tests__/bead_select.test.ts`, 픽스처 `tests/fixtures/bead_select/features/*`(코어 `make_fixture.py --features`) |
| V-SR-13 | **API**: `hold_fixed` 422, params `feasible`(SR-D-10)·`use_default`(warn 이면 체크), 구멍 비드 W 행 존재, 셀 `warnings`·`fixed_viol`(READY 칸)·`rules_outdated`, settings 키, `algo` 없는 derived 지연 갱신(version 불변) | `backend/tests/test_doe_select_api.py` |
| V-SR-14 | **UI**: ⚠ 배지·문구, 비드 행 체크 1개(고정 없으면 비활성), "섬 n · 구멍 m", 섬 색, 순위 ⚠·`best_clean`, 규칙 띠, 2560·1920 잘림 없음 | `frontend/__tests__/doe_select.test.tsx`, mock |
| V-SR-15 | **성능(slow)**: 22만 노드 + 섬 200·구멍 300 합성 — derive ≤ 3 s, 기저 ≤ 30 s(BS V-BS-11 기준 유지) | `tests/doe/test_bead_select_perf.py` |
| V-SR-R1 | **실기**: 실제 Ch/R — 비드별 섬·구멍 수 확인, W 변수 활성 비드 수(전/후), 경고 안 비율, hold 1 보스 품질, 순위 1 경고 여부 | `docs/manual/bead_doe_check.md` 절 추가 |

**defeature·공통 모듈 합성 형상** (`tests/doe/synth_compare.py`, 코드 추가 없이 spec 덮어쓰기만):
- `FEAT_SPEC = {"dimples": BEAD_FEATURES["dimples"] + [(120.0, 130.0, 10.0, 1.5)]}`(비드 바닥 x 60..240·y 50..150 안, 다른 딤플·버링과 20 mm 이상 떨어짐) — 기존 딤플 3개(깊이 2·5·8) + **작은 딤플 높이 1.5 mm**. Ø5·Ø10 관통 구멍, 버링(r 4, 길이 8), 비드 필렛 3, 딤플 둘레 필렛 1.5 는 기본 그대로.
- 정답(§4.4 기본 기준): 억제 = `hole` Ø5 1개(cad 단계 `holes` 가 이미 메움 → method `holes_v0141`), `bead` 1개(딤플 1.5 — 둘레 필렛 포함, 필렛 따로 안 셈), `fillet` = 깊이 2·5·8 딤플의 둘레 필렛 면(쉘 → compound). 억제 안 함 = Ø10(d 10 > 8), 버링(높이 8 > 1.5), 딤플 깊이 2(< 2 아님 — 경계값), 5·8, 비드 필렛 3(> 1.5), 비드 자체(bbox > 40).
- 단계 진입은 실패 주입(V-C2-13 방식, monkeypatch — cad·refine 시도에서 딤플 1.5 의 구면 bbox 면 실패, defeature 시도는 그 면이 없어 통과).

| ID | 시험 | 위치 |
|---|---|---|
| V-SR-16 | **래퍼·이동 무변경**: `mg.defeature(gmsh, df, h[, skip_keys])` 반환 = `gdf.holes(...)` 반환(dict 동일), `collect=None` 이면 v0.16.0 결과와 같음. 기존 ④ 합성 STEP(plate·boss·dimple·bead_with_features·fillet_corner) cad 메시 mesh.npz·mesh.json **바이트 동일**(v0.16.0 기대값), base.json `profile`·`profile_sha256` 동일(새 키 기본값·변경값 둘 다), `_cmp_sha` 동일(cad 형상, 새 키 변경 시에도). ③ 베이스라인·안 BREP 메시 바이트 동일. `mesh_gmsh._face_loops` 등 재노출 이름 존재 | `tests/doe/test_mesh_gmsh.py`·`test_step_compare.py`·`tests/geom/test_defeature.py`(신규) |
| V-SR-17 | **인식**: FEAT_SPEC 형상에서 `find_features` = 정답(종류·개수·중심 ± 0.01·크기 ± 0.05 mm — 딤플 h 1.5, 필렛 r 1.5), 형상 불변(전후 면 수·넓이 합 동일). `kinds` 에서 fillet 을 빼면 fillet 0. 경계값: `min_bead_height_mm` 2.1 → 깊이 2 딤플도 bead. `hole_max_d_mm` 12 → Ø10 도 hole. `feature_max_mm` 10 → 딤플 1.5(둘레 지름 2√(2Rd−d²) ≈ 10.5 + 필렛) 제외. 깊이 2 딤플은 h_C(bbox 위쪽 근사) = 2.0 ≥ 2 라 억제 안 됨(축 정렬 — 정확) | `tests/geom/test_defeature.py` |
| V-SR-18 | **단계 성공**: 실패 주입 → attempts = cad → refine_local(…) → refine_global(…) → defeature(READY), remesh 시도 없음, `mesh_method defeature`, `cad_error`, `MESH_DEFEATURED`(n·counts 정답), `mesh/defeature.json` = 정답 목록·결정적 순서(두 번 실행 바이트 동일), `defeature_stage.counts`. 주입 없이(cad 성공) 같은 형상 → defeature 단계 미진입·결과 V-SR-16 과 동일 | `tests/doe/test_step_compare.py`·`test_mesh_refine.py` |
| V-SR-19 | **편차**(2026-11-05 기준 갱신 — 실측: compound 필렛·구면 딤플의 h 3 현 처짐이 바깥에 들어가고, 메운 구멍 원판은 둘레 분할 메시라 중심만 r 에 가까움): 바깥 `outside.hausdorff_mm` ≤ 1.0 mm, 바깥 경고 기준 = max(0.3, 2 × `cad_chord_mm`)(SR-D-27 — 이 형상은 경고 없음), 딤플 1.5 `dev_mm` = 1.5 ± 0.15, Ø5 구멍 `dev_mm` ∈ [0.4 r, r + 0.15](r 2.5), `suppressed_max_mm` = 그 최대. 주입으로 바깥 편차 > fail_mm → `DEFEATURE_FIDELITY` → remesh 단계로 | `tests/geom/test_defeature.py`·`test_step_compare.py` |
| V-SR-20 | **사다리 설정**: 기본 ladder 5단계, `ladder` 에서 defeature 빼면 v0.16.0 순서, 순서 바꿈(`[cad, defeature, refine_local, …]`) 허용, 중복·cad 아님 맨 앞·알 수 없는 단계 → CONFIG_INVALID(코어)·422(백엔드), `mesh_refine: false` → refine 만 빠지고 defeature 유지, 억제 대상 0 → `SKIPPED no_feature`. compound 묶음 면 실패 주입 → 2번째 시도(compound 없음) 성공, 아니면 `not_compound` 건너뜀 | `tests/doe/test_mesh_refine.py`, `backend/tests/test_doe_compare_api.py` |
| V-SR-21 | **이어하기**: v0.16.0 스냅샷(`mesh_ladder` 4단계) 스터디 → `_cmp_sha` v0.16.0 상수 기대값과 같음, defeature 실행 안 함. 새 키 변경 → defeature 형상만 해시 변경. 메시 입력 `diag` 변경 → 해시 불변 | `tests/doe/test_step_compare.py`, `worker/tests/test_doe_compare_jobs.py` |
| V-SR-22 | **메시 공통 모듈**: `esl.mesh.features` 로 옮긴 뒤 V-SR-1 바이트 동일, `bead_select.MeshIndex is features.MeshIndex`. `enclosed_components`·`free_edge_components` 가 `synth_bead.generate(features=True)` 정답(섬 4·구멍)과 같음. `diagnose`: features 메시 → `holes_small_n`(Ø8 이하 구멍 수)·`islands_n` 4 정답, 매끈한 판 → 0 | `tests/mesh/test_features.py`(신규) |
| V-SR-23 | **메시 입력 진단**: 메시 입력 형상 행 `diag`·`MESH_INPUT_DIAG`, mesh.npz·loads 바이트 불변, `enabled: false` 면 키 없음 | `tests/doe/test_mesh_input.py` |
| V-SR-24 | **워커 E2E**: ④ 비교(기준 cad 성공 + 안 1개 FEAT_SPEC 실패 주입 형상 — 주입은 코어 시험에서만 가능(D-0.16-WORKER) → E2E 는 `compare.mesh.ladder = [cad, defeature]` + `refine.enabled` 무관, 설정만으로 cad 실패가 나는 형상 `fillet_corner_step`(정리 끔 Sphere 실패 재현)) → 형상 행 `mesh_method defeature`·`defeature` 요약, ranking.csv `defeature`, `COMPARE_MESH_METHOD_MIXED`, 보고서 "작은 형상 억제" 절, `GET …/shapes/{did}/defeature` 200 | `worker/tests/test_doe_compare_e2e.py`, `backend/tests/test_doe_compare_api.py` |
| V-SR-25 | **UI**: 메시 방식 "형상 단순화"·툴팁 문구, 억제 목록 표(50행 + 외 n), 메시 입력 진단 글자, 2560·1920 잘림 없음 | `frontend/__tests__/doe_compare.test.tsx`, mock |
| V-SR-26 | **통합 규칙(SR-D-25~31)**: 고리형 비드 R1·R2·R3 `SELECT_INNER_LOOP{n 1, ring 1, level info}`; 경계에 걸친 보스 `SELECT_SLOPE_ABOVE_PLATE` + 보스 윗면 고리 없음; `cad_chord_mm`(원통 R 10·h 3 = R(1 − cos(h/2R)) ± 5 %, 평면·90° 모서리 0), `warn_rel_cad 0` = 절대; 기본 설정 `_cmp_sha`·profile 해시 불변(regress); 워커 v0.16.0 SKIPPED_FIXED done → 재해석(SR-D-31) | `tests/doe/test_bead_select_real.py`·`test_mesh_remesh.py`, `worker/tests/test_doe_select_relax_jobs.py` |
| V-SR-27 | **결함 3건**: 사례 5 W 범위 공칭 포함 + `SELECT_W_RANGE_RESET`, 사례 2·5 `range_check` usable 양 끝 뒤집힘 없음·기본 범위 끝 FAILED_MESH(명시 경고), check_steps 0 = 끔; 볼록·오목 거울 메시 썸네일 시점 벡터 동일·전경 무게중심 ≤ 5 px; h6wavy golden = 뒤집힌 v0.16.0 범위만 예외 | `tests/doe/test_bead_select_real.py`·`test_select_render.py`·`tests/mesh/test_features.py` |
| V-SR-28 | **어려운 사례 H1~H4(SR-D-35~43)**: H1 둘 다 선택 S 섬 2·Dp 섬 1·TOO_LARGE 없음·D 변경 섬 강체 오차 < 1e-9; S 단독 D_nom = 15 ± 0.2·Dp 단독 25 ± 0.2(`SELECT_BASE_REFIT`), 판 요철 + plane_rms 0.2 → `SELECT_BASE_AMBIGUOUS`; 보스 r 3.5 변형 섬 1·B2_D1 +3.7 READY; H2 단 1·2·3 섬·구멍 1·W 켜짐·`SELECT_W_RANGE_LIMIT{tier}`; H3 B3_W 72 → `SELECT_CROSS_BEAD_MOVE`(skip = SKIPPED_COLLISION); H4 슬롯 있음 OPEN_BOUNDARY 없음·고리 닫힘(bridged 1)·W 켜짐·섬 4·D +1.5 섬 강체(+1.5), island.max_mm 8 → FAILED_MESH, 벽에 붙은 보스 → `SELECT_FEATURE_DISTORTED`; H1 usable 조합 2^4 → `SELECT_RANGE_COMBO` usable 조합 뒤집힘 0; READY 극단 요소 = QUALITY_WARN(극단값); 동률 규칙; `inverted_count` = affected_quality; ④ H4 STEP `find_features` 높이 0 bead·flange 없음; 받기 주석 줄 ≤ 100자. 회귀: 섬·구멍·교차 없는 합성(h5·h2·feat·open·wavy·openfeat)과 실 사례 7종 derive·기저·판정 상태 불변(조합 경고 `SELECT_RANGE_COMBO` 가 h5 params/derived 경고에 더해짐 — 판정·기저 불변), 정상 STEP ④·③·①② regress 바이트 동일. **v0.16.2 회귀 예외(esl_bead_auto.md AD-D-6)**: 판정(state)·기저 바이트가 같으면 `SELECT_RANGE_COMBO`·`SELECT_W_RANGE_LIMIT`·`SELECT_BASE_REFIT`·`SELECT_SLOPE_ABOVE_PLATE`·`SELECT_QUALITY_WARN`(극단값)·`SELECT_RANGE_INVERTS` 경고가 더해져도 회귀 실패 아님(사례 feat, edge_boss:G, 실 사례 1 전체 5(L), edge_boss B1_D1 7.0146, h5, 레일 A 단독) — 시험 상수 `REGRESS_WARN_EXCEPTIONS_V0162` | `tests/doe/test_bead_select_hard.py`(생성기 `tests/doe/synth_hard.py`), `tests/geom/test_defeature.py`, `tests/doe/test_select_render.py` |
| V-SR-R2 | **실기**: 이슈 #53 Ch/R STEP(사다리 v0.16.0 에서 remesh 까지 간 형상) — defeature 단계 성공 여부, 종류별 억제 수, 억제 영역 최대·바깥 편차, cad 성공 형상 결과 불변, 강성 지표 차(기준 대비 — 억제 영향 크기) | `docs/manual/bead_doe_check.md` 절 추가 |

## 12. 파일 소유권 · 작업 분해

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| R1 코어 | **Impl-Core** | `esl/doe/bead_select.py`(섬·구멍 §5.2·5.3, `_island_fill`, `_hold_factor`, `normalize_input` hold, `design_state` SR-D-1, `fixed_violation_detail` 상태 무관 호출용, `select_hash_view`·`HASH_NEW_KEYS_V0161`, `ALGO`, params_table feasible·use_default), `esl/doe/__init__.py`(DEFAULTS), `esl/doe/stages.py`(`_cfg_hash`·`_sel_cfg_sha` 해시 사본, 기저 재사용 algo, `bd_select_grid` 셀 warnings·rules·counts, `bd_eval` 재판정 재사용, `_sel_best` 주석·values.json, BD_POST `best_clean`·순위 warn), `esl/doe/nodes.py`(`write_morphed` `comment_lines`), `esl/doe/paicad_io.py`(`cell_state` 가 셀 `warnings` 통과), `esl/doe/report_doe.py`, `resources/doe_messages.json`, `tests/doe/synth_bead.py`·`test_bead_select_*.py`·`test_mesh_quality.py`·`test_select_render.py`, `tests/fixtures/bead_select/features/`·`make_fixture.py` | V-SR-1~9, 15 |
| R1b 코어 — 공통 모듈 | **Impl-Core** | **신규** `esl/geom/__init__.py`·`esl/geom/defeature.py`(§5B.1 전부), `esl/mesh/__init__.py`·`esl/mesh/features.py`(§5B.2 전부); 이동 원본 `esl/doe/mesh_gmsh.py`(위상 도우미 재노출, `defeature` 래퍼 1줄, `_session` 의 `mesh.defeature_stage` 분기 §5A.1), `esl/doe/bead_select.py`(`MeshIndex`·`mesh_index`·`_node_graph`·`_loops` 재노출, §5.2·5.3 호출 교체), `esl/doe/mesh_remesh.py`(R3 삼각화를 함수로 분리 — `reference_tris` 가 호출), `esl/doe/mesh_input.py`(`diagnose` 호출·`hash_view`), `tests/geom/test_defeature.py`·`tests/mesh/test_features.py`(신규) | V-SR-16, 17, 19, 22, 23 |
| R1c 코어 — 사다리 | **Impl-Core** | `esl/doe/mesh_refine.py`(`STAGES`·`plan("defeature")`·`attempt_cfg`), `esl/doe/stages.py`(`_cmp_ladder` defeature 분기·`MESH_METHODS`·`LADDER_STAGE_LABEL`·`DEFEAT_NEW_KEYS_V0161`·`prof_rec` 사본·`_cmp_sha` `defeature_cfg`·형상 행 `defeature`·`diag`·`mixed_methods`), `esl/doe/__init__.py`(DEFAULTS compare), `esl/doe/report_doe.py`("작은 형상 억제" 절·프로필 문구), `resources/doe_messages.json`(§10 새 코드), `tests/doe/test_mesh_refine.py`·`test_step_compare.py` | V-SR-18, 20, 21 |
| R2 백엔드 | **Impl-Backend** | `backend/esl_platform/core/config.py`(§4.4 — select·compare.defeature·ladder·mesh_input.diag, `_doe_settings` 거울), `api/schemas.py`(select 칸 + 형상 행 `mesh_method`·`defeature`·`diag`·attempts 칸), `api/services/doe_select.py`(hold 검증 전달, params_table W 조건·use_default·feasible, derived `algo` 지연 갱신), `api/services/doe.py`(`preview_cells` warnings·fixed_viol·rules_outdated, settings, 결과 `best_clean`, `mesh_ladder` 검증 집합, 형상 행 통과), `api/routers/doe.py`(`GET /doe/studies/{sid}/shapes/{did}/defeature`), `config/*.example.yaml` 2개, `openapi`, `backend/tests/test_doe_select_api.py`·`test_doe_compare_api.py` | V-SR-13, 20(백엔드), 24(API) |
| R3 워커 | **Impl-Worker** | `worker/esl_worker/register.py`(미리보기 요약 `warn` 수·`rules`, 비교 준비 요약에 defeature 형상 수), `worker/esl_worker/doe_jobs.py`(변경 최소 — 코어 단계 그대로, 이어하기 경로 확인), `worker/tests/test_doe_select_jobs.py`·`test_doe_select_e2e.py`·`test_doe_compare_jobs.py`·`test_doe_compare_e2e.py` | V-SR-10, 11, 21(워커), 24 |
| R4 프런트 | **Impl-Frontend** | `src/view3d/select/grow.ts`(`enclosedIslands` — `features.enclosed_components` 거울), `layers.ts`(섬 색·`hold_fixed` 상태·`toSelectionIn`/`fromSelectionIn`), `components/BeadList.tsx`, `BeadSelectCard.tsx`, `DoeThumbGrid.tsx`, `FixedViol.tsx`, `pages/doe/DoeStudy.tsx`, ④ 형상 표 컴포넌트(메시 방식 라벨·툴팁·억제 목록 펼침·진단 글자), `api/types.ts`·`api/doe.ts`(`getShapeDefeature`), `mock/doedata.ts`(defeature 형상·메시 입력 진단 예), `__tests__/bead_select.test.ts`·`doe_select.test.tsx`·`doe_compare.test.tsx` | V-SR-12, 14, 25 |
| R5 문서 | Plan/Impl | `VERSION`·`CHANGELOG.md` 0.16.1, `docs/decisions.md`(D-0.16.1-Q1·Q2·Q3·DEFEAT·COMMON — 이 커밋에서 기록), `docs/manual/user.md`(섬·구멍·hold·경고·형상 단순화 단계·억제 목록 보는 법), `docs/manual/bead_doe_check.md`(V-SR-R1·R2), `esl_bead_select.md`·`esl_compare_mesh_options.md`·`esl_step_compare.md` 머리에 "v0.16.1 변경 = esl_select_relax.md" 1줄 | – |

- **병렬**: R1 ∥ R2(스키마·설정은 §4 가 계약 — 코어 없이 시작) ∥ R4(mock + `select/*` 순수 모듈 먼저, 섬 픽스처는 R1 의 `make_fixture.py --features` 산출 후 V-SR-12 연결). R3 은 R1·R2 병합 후. E2E(V-SR-11) → 실기.
- R1 내부 순서: **R1b 이동(래퍼·재노출, V-SR-16·22 바이트 고정) 먼저** → synth features(V-SR-1 회귀 고정) → 섬·구멍 판정(`features` 사용) → 섬 채움·hold 기저 → 판정 정책 → 해시·이어하기 → 받기·보고서. R1c(사다리)는 R1b 의 `gdf` 시그니처 뒤 병렬 가능(같은 Impl-Core 가 순서대로 하거나 2명이면 R1b 병합 후 R1c).
- 공동 수정 파일: `stages.py`·`mesh_gmsh.py`·`bead_select.py`(R1 단독 소유 — 워커는 고치지 않음), `doe_messages.json`(R1), `schemas.py`(R2), `types.ts`(R4 — R2 스키마 확정 뒤 거울).

## 13. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-SR-1 | 큰 오목 형상(보강 리브 섬, 큰 개구)을 섬으로 잡아 통째 이동 | `island.max_mm` 40, 크기 초과 경고, `exclude` 로 끔(SR-D-15), 화면 섬 색으로 바로 보임 |
| R-SR-2 | 곡면 바닥에서 섬 평행 이동과 둘레 사이 전단 | `SELECT_ISLAND_SHEAR` 진단, 품질 판정(경고), 실기 확인 |
| R-SR-3 | 경고 안이 순위 1 → 체결부 어긋난 형상을 최적으로 오인 | ⚠·`best_clean`·보고서 절·rad 주석, Q1 = A |
| R-SR-4 | 품질 경고 안의 해석 결과 신뢰도(찌그러진 요소 강성) | 뒤집힘 제외 유지, 보고서에 새 Fail 수, 필요 시 `fail_policy: skip` |
| R-SR-5 | 해시 사본 규칙 실수로 기존 스터디 전량 재해석 | V-SR-10 상수 기대값(v0.16.0 실제 해시) 시험 |
| R-SR-6 | rad 주석 삽입이 하위 도구(HyperMesh 가져오기) 판독 방해 | `#` 줄은 Radioss 표준 주석, ASCII 만, 경고 안에만. 실기에서 HyperMesh 가져오기 1회 확인 |
| R-SR-7 | 브라우저·서버 섬 판정 불일치 | 서버가 원본(SR-D-14), 픽스처 동일성 시험, derive 응답으로 표시 대체 |
| R-SR-8 | hold 블렌딩 b 가 작아 보스 벽 품질 경고 다발 | 기본 8 mm, 설정 조정, Q2 = A |
| R-SR-9 | 억제가 강성을 바꿔(딤플 평탄화·구멍 메움) 비교 결과가 형상 차가 아니라 억제 차를 반영 | cad·refine 실패 형상에만 적용(SR-D-21a), `MESH_DEFEATURED`·`MIXED`·보고서 절·억제 목록·영역 편차로 드러냄, 기준 d000 이 defeature 면 수렴 점검 δ(C2-D-24)와 함께 표시. 실기 V-SR-R2 에서 억제 전후 강성 차 확인 |
| R-SR-10 | 인식 오탐(기능상 중요한 낮은 리브·체결 버링을 억제) | 기준을 BatchMesher 사내 값과 같게, `feature_max_mm` 상한, `kinds` 로 종류별 끔, 목록·위치 표시 |
| R-SR-11 | OCC 채움 면·제거가 위상을 깨 오히려 새 면 실패 | 특징별 try·실패 시 그 특징만 건너뜀, v0.14.1 면 폴백·v0.15.1 형상 폴백이 이 단계에서도 동작, 그래도 실패하면 다음 단계(remesh) |
| R-SR-12 | 쉘 compound 메싱 실패(재매개변수화 불가 — 구멍 있는 묶음 등) | 묶음은 fillet/narrow + 이웃만, 실패 시 compound 없는 2번째 시도(SR-D-18) |
| R-SR-13 | 공통 모듈 이동 중 미세 동작 변경(import 순서·부동소수 순서)으로 기존 결과 바이트 변화 | 이동을 첫 작업으로 분리하고 V-SR-1·16·22 바이트 비교 통과 후 기능 추가 |
| R-SR-14 | defeature 단계 시간(인식 BFS + 원 STEP 재삼각화)이 예산을 먹어 remesh 기회 상실 | 같은 `refine.total_timeout_s`·`attempt_timeout`, 억제 대상 0 이면 건너뜀, BFS 크기 상한, `max_features` |
| R-SR-15 | 새 설정 키로 ④ 해시 변경 → 기존 스터디 재메시·재해석 | SR-D-21b 사본 규칙, V-SR-16·21 상수 기대값 |

## 14. 결정 질문 (Q1~Q3 확정 2026-11-05 = A, Q4·Q5 = 남은 질문 — 권장안을 기본값으로 작성)

| # | 질문 | 선택지 | 권장 / 확정 |
|---|---|---|---|
| Q4 | ③ STEP 스터디 베이스라인 메시가 실패할 때도 같은 defeature(사다리) 폴백을 쓸지 | **A** v0.16.1 은 ④ 만, ③ 은 공통 모듈 호출 지점만 두고 꺼 둠(`bead_doe.mesh.defeature` 수동) / B ③ 베이스라인에도 cad 실패 시 defeature 1회 | **A** — ③ 은 paicad 가 같은 형상을 모핑해 안마다 BREP 을 다시 메시하므로 기준만 억제하면 안과 위상이 달라짐. ③ 전환(STEP 모핑) 때 `find_features` 로 함께 다룸 |
| Q5 | 작은 필렛 제거 기준 반경 | **A** 1.5 mm(= 0.5·h, 사면 필렛 3 mm 는 유지) / B BatchMesher `max_fillet_radius` 9 mm / C 끔(kinds 에서 fillet 제외) | **A** — 원 BatchMesher 는 필렛 인식을 꺼 두고 9 는 인식용 상한. 9 면 비드 사면 필렛까지 병합돼 형상 의미가 바뀜. 1.5 는 요소 1개 폭보다 좁은 띠만 |
| | **확정 (2026-11-05 사용자 — 아래 Q1~Q3 모두 A)** | | |
| Q1 | 경고 안(고정 어긋남·품질 경고)이 순위 1 이면? | **A** 순위 그대로 + ⚠ + "경고 없는 최상위" 1줄 병기 / B 받기·보고서 대표 안을 경고 없는 최상위로 자동 대체 / C 순위에서 경고 안을 뒤로 | **A 확정**(2026-11-05) — 확정 1 "제외하지 않음"과 같은 결, 판단은 사용자가 표시를 보고 |
| Q2 | 체결 구멍 둘레 고정 링 기준·기본값 | **A** 고정 노드(RBE2 등)에서 거리 ρ = 3 mm 제자리 + 블렌딩 8 mm / B 구멍 중심에서 반경 R(구멍 크기별 입력) | **A 확정**(2026-11-05) — 구멍 중심·반경을 따로 찾지 않아도 되고 fixed-scan 노드만으로 정의, 구멍 크기가 달라도 같은 여유 |
| Q3 | 기본 범위(D ±30 %, W ±20 %)도 넓힐지 | **A** 기본 범위·R_auto 그대로, feasible(경고 경계)만 D ×2.0·W ×1.6 / B 기본 범위도 D ±50 %·W ±40 % | **A 확정**(2026-11-05) — 기본 범위를 바꾸면 R_auto 가 바뀌어 기존 스터디 기저가 전부 바뀜(재해석). 넓은 범위는 표에서 직접 입력(경고만) |
