# 계약: 비드 직접 선택(select) 제약 완화 · 비드 안 형상(구멍·섬·체결 구멍) 처리 (SELECT_RELAX, v0.16.1)

- 상태: **초안** (2026-11-05). 사용자 확정 사항(아래, 2026-11-04) 반영. 결정 질문 3개(§14) 미확정 — 권장안으로 작성, 확정 시 해당 절만 갱신.
- 버전: **v0.16.1** (기준 main ef7545c = v0.16.0). migration **불필요**(§7.6).
- 관계: `esl_bead_select.md`(BEAD_SELECT, v0.15.0 — 이하 "BS")의 **변경 계약**. 이 문서에 없는 규칙은 BS 를 따르고, 충돌 시 이 문서가 우선. `docs/decisions.md` D-0.16-P2(고정 침범·품질 FAIL = 경고, 뒤집힘만 제외)를 구체화한다.
- ID 규칙: 결정 `SR-D-n`, 시험 `V-SR-n`, 리스크 `R-SR-n`, 질문 `Q1~Q3`.

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
| SR-D-11 | **경고 안도 순위·받기 대상**: READY(경고 포함) 안은 실행·순위·민감도에 그대로 들어간다. 순위 행·결과 카드·보고서에 ⚠ 표시, 결과 요약에 "경고 없는 최상위 안" 1줄 추가(순위 자체는 바꾸지 않음) — **Q1** | 확정 1 "제외하지 않음" |
| SR-D-12 | **받기 rad 경고** = 고정 침범 안의 rad/include 사본에서 **첫 `/NODE` 줄 바로 앞**에 ASCII 주석 줄(`#` 시작) 삽입 + `ch_r.rad` 머리 주석 + `values.json.warnings`. 침범 없는 안은 v0.16.0 과 바이트 동일 | 확정 1 "rad 사본에 경고". Radioss 입력은 `#` 주석 허용, 비ASCII 는 솔버 판독 위험이라 영문 고정 문구 |
| SR-D-13 | **이어하기 호환 4규칙**(§7): (a) 새 비드 키는 기본값이면 정규화에서 생략 → 기존 선택 sha 불변, (b) 해시용 설정 사본에서 새 키가 기본값이면 생략 → `_cfg_hash`·`_sel_cfg_sha` 불변, (c) 기저 `algo: 2` 표지 → 기존 기저 1회 재계산(섬·구멍·hold 없으면 같은 바이트 → 안 해시 불변), (d) 안 재사용 시 판정을 다시 적용 | 기존 스터디를 깨지 않고 완화만 반영 |
| SR-D-14 | **클릭 확장 자동 포함**: 브라우저 `grow` 뒤에 `enclosedIslands`(같은 위상 규칙 — §5.2 의 1~3단계, 크기 상한 포함)로 섬을 즉시 표시. **저장 대상 아님**(입력 ElemSet 에 넣지 않음) — 서버 `derive` 가 같은 규칙으로 다시 정하고 응답의 `islands` 가 표시를 대체 | BS-D-5(서버가 원본) 유지 + 즉시 반응. 두 구현 일치는 픽스처 시험(V-SR-12) |
| SR-D-15 | **섬 끄기 = `exclude` 층**: 사용자가 섬 요소를 "제외" 층으로 칠하면 그 성분은 섬이 아님 → v0.16.0 동작(안쪽 고리) + `SELECT_INNER_LOOP`. 새 층 없음 | 화면 요소 최소(확정 "필수만") |

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
| D1 | 기본 범위 D ±30 %, W ±20 % | `_ranges_blend:1045-1051` | 기본값 | 유지(Q3) | R_auto 가 이 값 기준 — 바꾸면 기저 변경 |
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
    range: {depth_rel: 0.3, width_rel: 0.2, min_step_mm: 1.0, depth_max_rel: 1.0, width_max_rel: 0.6}  # *_max_rel = feasible 상한(SR-D-10)
    island: {max_mm: 40.0}        # 섬 평면 bbox 대각 상한(§5.2)
    hold: {ring_mm: 3.0, blend_mm: 8.0}                                  # Q2
```
| 위치 | 추가 | pydantic 검사 |
|---|---|---|
| `esl/doe/__init__.py:130-140` DEFAULTS | `fixed_policy`, `quality.fail_policy`, `range.depth_max_rel`·`width_max_rel`, `island`, `hold` | – |
| `backend/esl_platform/core/config.py:818-862` | `BeadDoeSelectCfg.fixed_policy: Literal["warn","skip"]="warn"`, `BeadDoeSelectQualityCfg.fail_policy: Literal[...]="warn"`, `BeadDoeSelectRangeCfg.depth_max_rel: float(gt=0, le=5)=1.0`·`width_max_rel(gt=0, le=5)=0.6`(각 `*_max_rel ≥ *_rel` 검사), `BeadDoeSelectIslandCfg.max_mm(gt=0)=40`, `BeadDoeSelectHoldCfg.ring_mm(ge=0)=3`·`blend_mm(gt=0)=8` | 섹션 없으면 기본 |
| `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`(select 절이 있는 예시 2개) | 위 yaml 그대로 | – |
| `GET /doe/settings` `select` | `fixed_policy`, `quality_fail_policy`, `hold{ring_mm, blend_mm}` | – |

## 5. 알고리즘 (`esl/doe/bead_select.py`)

기호는 BS §5 와 같음. F = ∪F_k, I = ∪ 섬, BM = F ∪ S ∪ I. "평면" = 단 평균 법선 n̄_b 에 수직인 평면(섬 판정 단계에서는 n̂_b 가 아직 없음).

### 5.1 처리 순서 (`_derive_bead`, 변경 부분만)
1. F, n̄_b (불변) → 2. **섬 판정 §5.2** → 3. 사면 BFS: `allowed &= ~I`(섬을 지나지 않음, `:710`) → 4. BM = F ∪ S ∪ I → 5. 경계·고리(`_loops(BM)`) + **구멍 분류 §5.3** → 6. 이하 v0.16.0 그대로(평면·n̂_b·단·사면 수준) → 7. 폭 §5.4 → 8. 블렌딩·고정 → 9. hold 영역 §5.5.
- 섬·구멍이 없으면 2·5 의 결과가 공집합/거짓 → 이후 모든 배열이 v0.16.0 과 같다(V-SR-1).

### 5.2 섬 판정 (바깥/안쪽 구분 — 섬)
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
- 설정값 근거(Q2): ρ 3 mm = 와셔 접촉 여유, b 8 mm = ΔD 6.6 mm(22 × 30 %)에서 벽 각 ≈ 40° → 품질 경고 최소.

### 5.7 고정·품질 판정 (`design_state`, SR-D-1)
```text
q = affected_quality(...); fx = fixed_violation(...)
if q.inverted > 0:                       -> FAILED_MESH / SELECT_MORPH_INVERTED
elif fx.violated and fixed_policy=skip:  -> SKIPPED_FIXED / SELECT_FIXED_VIOLATION
elif q.over_limit and fail_policy=skip:  -> FAILED_MESH / SELECT_QUALITY_FAIL
else READY, warnings += FIXED_MOVED(fx) if fx.violated, QUALITY_WARN(q) if q.over_limit
```
- 순서 변경 영향: v0.16.0 은 고정 침범 + 뒤집힘 동시 안을 `SKIPPED_FIXED` 로, v0.16.1 은 `FAILED_MESH` 로 기록(둘 다 실행 안 함 — 개수 표만 다름, §7.4).

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
- 안 재사용(SR-D-13d): select 의 `bd_eval` 은 재사용 전에 `design_state` 를 다시 계산. 현재 state ≠ READY → 스킵 문서(재사용 안 함). 현재 READY ∧ 이전 done 상태 ∈ {OK, FAILED_SOLVE} → 재사용. 현재 READY ∧ 이전 `SKIPPED_FIXED` → 재사용 안 함(해석).

### 7.5 이미 끝난(DONE) 스터디
- 결과·보고서·받기 파일 변경 없음(자동 재생성 없음). 복제(`clone`)하면 선택 sha 그대로 복사, 새 규칙으로 미리보기부터.
- DB `selection.derived` 에 `algo` 가 없으면 `GET …/selection`·`params`·`plan-view` 때 서버가 다시 derive 해 DB 요약을 갱신(rev·sha·`version` 불변 — 계산 캐시 갱신이라 사용자 편집 충돌 없음).

### 7.6 버전
- `VERSION` 0.16.1, `CHANGELOG.md`, `openapi` info.version. migration 없음(`selection` JSONB 안 키 추가, 시나리오 CHECK 불변).

## 8. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 필수만)

| 위치 | 추가 | 파일 |
|---|---|---|
| 미리보기 칸 | ⚠ 배지 + 1줄 "고정 노드 n개, 최대 x mm 이동"(침범 시), 품질 경고는 배지 툴팁 "새 Fail m (r %)". 뒤집힘 = 기존 ⨯ 배지 | `components/DoeThumbGrid.tsx`, `FixedViol.tsx`(경고 칸에도 표시) |
| 비드 목록 | 비드 행에 체크 1개 **[체결 구멍 둘레 고정]**(`hold_fixed`, 비드 안·블렌딩 안 고정 노드가 있을 때만 활성, 툴팁 "링 3 mm 제자리 · 8 mm 블렌딩") + 요약 글자 "섬 3 · 구멍 2" | `components/BeadList.tsx` |
| 3D 선택 | 섬 = 그 단 색의 밝은 단계(새 층 아님), 클릭 확장 직후 표시(SR-D-14) | `view3d/select/grow.ts`(`enclosedIslands`), `layers.ts`(`elemColors` 섬 색), `BeadSelectCard.tsx` |
| 결과 카드·순위 | 순위 행 ⚠, 요약 "경고 없는 최상위: d0xx"(1위가 경고 안일 때만) | `pages/doe/DoeStudy.tsx`, 기존 결과 컴포넌트 |
| 띠 | `rules_outdated` 1줄(§7.4) | `DoeStudy.tsx` |

## 9. API 변경 (`/esl/api`)

| 경로 | 변경 |
|---|---|
| `POST …/select/derive`·`PUT …/selection` | 요청 `BeadSel.hold_fixed`, 응답 BeadDerived `islands`·`holes`·`inner_loops_n`·`hold`, `algo`, derive 응답 `islands_suggested`. 422 `SELECT_HOLD_INVALID` |
| `GET …/params`(select) | `feasible` = SR-D-10, `use_default` = SR-D-8(백엔드 `doe_select.params_table:300-357` 가 `fixed_policy` 읽음). W 행 조건 = 열린 경계 아님(구멍은 열린 경계 아님 — 코어 derived 의 `w_enabled` 를 그대로 사용하도록 `:343-345` 수정) |
| 미리보기 셀(`preview_cells` `doe.py:713-746`) | `warnings`(있을 때만), `fixed_viol`(침범 있으면 상태 무관), `rules_outdated` |
| `GET /doe/settings` | §4.4 |
| 결과(`result`·순위) | 행 `warn`, `summary.best_clean` |
- 스키마: `backend/esl_platform/api/schemas.py`(`SelectBeadIn.hold_fixed: Literal[0, 1] | None`, `SelectionDerived` 칸, 셀·순위 칸 Optional), `frontend/src/api/types.ts` 거울, `openapi` 재생성(`check:api`).

## 10. 오류·경고 코드 (신규, 문구 원본 `resources/doe_messages.json`)

| 코드 | 종류 | 의미 |
|---|---|---|
| `SELECT_FIXED_MOVED` | 안 경고 | 고정 노드 n개 최대 x mm 이동(warn 정책) — 화면 "체결 위치 어긋남" |
| `SELECT_QUALITY_WARN` | 안 경고 | 새 Fail 비율 > 상한(warn 정책) |
| `SELECT_INNER_LOOP` | derive 경고 | 섬이 아닌 안쪽 고리 n개 — v0.16.0 대로 처리 |
| `SELECT_ISLAND_TOO_LARGE` | derive 경고 | 둘러싸였지만 `island.max_mm` 초과 — 섬 아님 |
| `SELECT_ISLAND_SHEAR` | derive 경고 | 곡면 바닥에서 섬 평행 이동과 둘레 차(표시만) |
| `SELECT_HOLD_NO_FIXED` | derive 경고 | `hold_fixed` 1 인데 대상 고정 노드 없음 |
| `SELECT_HOLD_INVALID` | 422 | `hold_fixed` 형식 |
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
| V-SR-10 | **sha·이어하기**: hold 없는 v0.16.0 선택 JSON → sha 동일, hold 1 → 다름; 기본 설정 `_cfg_hash`·`_sel_cfg_sha` = v0.16.0 값(상수 기대값); `algo` 없는 basis.json → 재계산 후 같은 바이트; v0.16.0 `SKIPPED_FIXED` done.json + warn → 재해석, OK done.json → 재사용 | `worker/tests/test_doe_select_jobs.py` |
| V-SR-11 | **받기·보고서**: 경고 안 rad 사본 = 원본과 "삽입 주석 줄 + /NODE 좌표 칸" 외 바이트 동일, 주석 ASCII·원본 줄바꿈, 경고 없는 안은 v0.16.0 V-BS-14 그대로, `ch_r.rad` 머리 주석, 보고서 "체결 위치 어긋남" 절·⚠ 열·`best_clean` | `worker/tests/test_doe_select_jobs.py`·`test_doe_select_e2e.py` |
| V-SR-12 | **브라우저 섬**: `enclosedIslands` 가 합성 소형 픽스처(features)에서 코어 `islands` 와 같은 요소 집합, 22만 요소에서 클릭 확장 + 섬 ≤ 150 ms, 섬은 `toSelectionIn` 출력에 없음 | `frontend/__tests__/bead_select.test.ts`, 픽스처 `tests/fixtures/bead_select/features/*`(코어 `make_fixture.py --features`) |
| V-SR-13 | **API**: `hold_fixed` 422, params `feasible`(SR-D-10)·`use_default`(warn 이면 체크), 구멍 비드 W 행 존재, 셀 `warnings`·`fixed_viol`(READY 칸)·`rules_outdated`, settings 키, `algo` 없는 derived 지연 갱신(version 불변) | `backend/tests/test_doe_select_api.py` |
| V-SR-14 | **UI**: ⚠ 배지·문구, 비드 행 체크 1개(고정 없으면 비활성), "섬 n · 구멍 m", 섬 색, 순위 ⚠·`best_clean`, 규칙 띠, 2560·1920 잘림 없음 | `frontend/__tests__/doe_select.test.tsx`, mock |
| V-SR-15 | **성능(slow)**: 22만 노드 + 섬 200·구멍 300 합성 — derive ≤ 3 s, 기저 ≤ 30 s(BS V-BS-11 기준 유지) | `tests/doe/test_bead_select_perf.py` |
| V-SR-R1 | **실기**: 실제 Ch/R — 비드별 섬·구멍 수 확인, W 변수 활성 비드 수(전/후), 경고 안 비율, hold 1 보스 품질, 순위 1 경고 여부 | `docs/manual/bead_doe_check.md` 절 추가 |

## 12. 파일 소유권 · 작업 분해

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| R1 코어 | **Impl-Core** | `esl/doe/bead_select.py`(섬·구멍 §5.2·5.3, `_island_fill`, `_hold_factor`, `normalize_input` hold, `design_state` SR-D-1, `fixed_violation_detail` 상태 무관 호출용, `select_hash_view`·`HASH_NEW_KEYS_V0161`, `ALGO`, params_table feasible·use_default), `esl/doe/__init__.py`(DEFAULTS), `esl/doe/stages.py`(`_cfg_hash`·`_sel_cfg_sha` 해시 사본, 기저 재사용 algo, `bd_select_grid` 셀 warnings·rules·counts, `bd_eval` 재판정 재사용, `_sel_best` 주석·values.json, BD_POST `best_clean`·순위 warn), `esl/doe/nodes.py`(`write_morphed` `comment_lines`), `esl/doe/paicad_io.py`(`cell_state` 가 셀 `warnings` 통과), `esl/doe/report_doe.py`, `resources/doe_messages.json`, `tests/doe/synth_bead.py`·`test_bead_select_*.py`·`test_mesh_quality.py`·`test_select_render.py`, `tests/fixtures/bead_select/features/`·`make_fixture.py` | V-SR-1~9, 15 |
| R2 백엔드 | **Impl-Backend** | `backend/esl_platform/core/config.py`(§4.4), `api/schemas.py`, `api/services/doe_select.py`(hold 검증 전달, params_table W 조건·use_default·feasible, derived `algo` 지연 갱신), `api/services/doe.py`(`preview_cells` warnings·fixed_viol·rules_outdated, settings, 결과 `best_clean`), `config/*.example.yaml` 2개, `openapi`, `backend/tests/test_doe_select_api.py` | V-SR-13 |
| R3 워커 | **Impl-Worker** | `worker/esl_worker/register.py`(미리보기 요약 `warn` 수·`rules`), `worker/esl_worker/doe_jobs.py`(변경 최소 — 코어 단계 그대로, 이어하기 경로 확인), `worker/tests/test_doe_select_jobs.py`·`test_doe_select_e2e.py` | V-SR-10, 11 |
| R4 프런트 | **Impl-Frontend** | `src/view3d/select/grow.ts`(`enclosedIslands`), `layers.ts`(섬 색·`hold_fixed` 상태·`toSelectionIn`/`fromSelectionIn`), `components/BeadList.tsx`, `BeadSelectCard.tsx`, `DoeThumbGrid.tsx`, `FixedViol.tsx`, `pages/doe/DoeStudy.tsx`, `api/types.ts`·`api/doe.ts`, `mock/doedata.ts`, `__tests__/bead_select.test.ts`·`doe_select.test.tsx` | V-SR-12, 14 |
| R5 문서 | Plan/Impl | `VERSION`·`CHANGELOG.md` 0.16.1, `docs/decisions.md`(SR 확정분), `docs/manual/user.md`(섬·구멍·hold·경고), `docs/manual/bead_doe_check.md`(V-SR-R1), `esl_bead_select.md` 머리에 "v0.16.1 변경 = esl_select_relax.md" 1줄 | – |

- **병렬**: R1 ∥ R2(스키마·설정은 §4 가 계약 — 코어 없이 시작) ∥ R4(mock + `select/*` 순수 모듈 먼저, 섬 픽스처는 R1 의 `make_fixture.py --features` 산출 후 V-SR-12 연결). R3 은 R1·R2 병합 후. E2E(V-SR-11) → 실기.
- R1 내부 순서: synth features(V-SR-1 회귀 먼저 고정) → 섬·구멍 판정 → 섬 채움·hold 기저 → 판정 정책 → 해시·이어하기 → 받기·보고서.
- 공동 수정 파일: `stages.py`(R1 단독 소유 — 워커는 고치지 않음), `doe_messages.json`(R1), `schemas.py`(R2), `types.ts`(R4 — R2 스키마 확정 뒤 거울).

## 13. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-SR-1 | 큰 오목 형상(보강 리브 섬, 큰 개구)을 섬으로 잡아 통째 이동 | `island.max_mm` 40, 크기 초과 경고, `exclude` 로 끔(SR-D-15), 화면 섬 색으로 바로 보임 |
| R-SR-2 | 곡면 바닥에서 섬 평행 이동과 둘레 사이 전단 | `SELECT_ISLAND_SHEAR` 진단, 품질 판정(경고), 실기 확인 |
| R-SR-3 | 경고 안이 순위 1 → 체결부 어긋난 형상을 최적으로 오인 | ⚠·`best_clean`·보고서 절·rad 주석, Q1 |
| R-SR-4 | 품질 경고 안의 해석 결과 신뢰도(찌그러진 요소 강성) | 뒤집힘 제외 유지, 보고서에 새 Fail 수, 필요 시 `fail_policy: skip` |
| R-SR-5 | 해시 사본 규칙 실수로 기존 스터디 전량 재해석 | V-SR-10 상수 기대값(v0.16.0 실제 해시) 시험 |
| R-SR-6 | rad 주석 삽입이 하위 도구(HyperMesh 가져오기) 판독 방해 | `#` 줄은 Radioss 표준 주석, ASCII 만, 경고 안에만. 실기에서 HyperMesh 가져오기 1회 확인 |
| R-SR-7 | 브라우저·서버 섬 판정 불일치 | 서버가 원본(SR-D-14), 픽스처 동일성 시험, derive 응답으로 표시 대체 |
| R-SR-8 | hold 블렌딩 b 가 작아 보스 벽 품질 경고 다발 | 기본 8 mm, 설정 조정, Q2 |

## 14. 결정 질문 (권장안 포함)

| # | 질문 | 선택지 | 권장 |
|---|---|---|---|
| Q1 | 경고 안(고정 어긋남·품질 경고)이 순위 1 이면? | **A** 순위 그대로 + ⚠ + "경고 없는 최상위" 1줄 병기 / B 받기·보고서 대표 안을 경고 없는 최상위로 자동 대체 / C 순위에서 경고 안을 뒤로 | **A** — 확정 1 "제외하지 않음"과 같은 결, 판단은 사용자가 표시를 보고 |
| Q2 | 체결 구멍 둘레 고정 링 기준·기본값 | **A** 고정 노드(RBE2 등)에서 거리 ρ = 3 mm 제자리 + 블렌딩 8 mm / B 구멍 중심에서 반경 R(구멍 크기별 입력) | **A** — 구멍 중심·반경을 따로 찾지 않아도 되고 fixed-scan 노드만으로 정의, 구멍 크기가 달라도 같은 여유 |
| Q3 | 기본 범위(D ±30 %, W ±20 %)도 넓힐지 | **A** 기본 범위·R_auto 그대로, feasible(경고 경계)만 D ×2.0·W ×1.6 / B 기본 범위도 D ±50 %·W ±40 % | **A** — 기본 범위를 바꾸면 R_auto 가 바뀌어 기존 스터디 기저가 전부 바뀜(재해석). 넓은 범위는 표에서 직접 입력(경고만) |
