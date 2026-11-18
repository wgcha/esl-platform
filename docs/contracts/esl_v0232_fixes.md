# 계약: v0.23.2 수정 — 복제 순위 설정 갱신 · 지그 칩 항상 표시 · 3D 비교 하중 조건·지그 응답 (FIX-0232)

- 상태: **확정**(2026-11-18, 메인 지시 + 사용자 정정 13:04). main d72d6a90(v0.23.1) 위 브랜치 `release/v0.23.2`.
- 버전: **v0.23.2**(패치). migration **없음**(새 값은 작업 spec JSONB·`post/` 파일·결과 응답 필드만).
- 관계: `esl_jig_rank.md`(v0.23.0 지그 순위)·`esl_doe_ui_tidy.md`(v0.23.1 화면)를 고친다. 충돌하면 이 문서가 우선(해당 항목 범위에서만).
- ID: 결정 `D-0.23.2-n`, 시험 `V-0232-n`.
- 근거(현장 2026-11-18): v0.23.1 배포 후 기존 스터디 `_doe/2e87283c`(75R9J chassis_rear, select case)를 복제·실행 → 순위 CSV `metric=solve`, `C_jig`·`umax_jig` 열 없음, 지그 칩 없음, 3D 비교는 3-2-1 지지 표시(전 노드 ESL 재풀이)만.

## 0. 조사 결과 (d72d6a90)

| 항목 | 위치 | 확인 |
|---|---|---|
| 복제 | `B/api/services/doe.py:clone()` | 옛 DOE_PREP 스냅샷 `old` 를 deep-copy, 제외 키 = `rev·spec·matrix_sha256·run·paicad_version·design·paicad·selection`. **`rank` 는 그대로 복사** → 원본이 rank schema 1(`metric solve`, `jig` 없음)이면 복제본도 지그 미계산. `cfg` 는 지금 설정(`_snapshot_cfg`), `load_transfer` 는 원 값 유지 + `diag` 만 지금 설정(LT-11) |
| 순위 스냅샷 | `rank_snapshot(c)` | 새 스터디(`create_study`·`_create_compare`)만 호출 — `jig` 블록 + schema 2 |
| rank 의 영향 범위 | 코어 `stages.py` | `_sm(c)`·`_jig(c)` = 평가(BD_EVAL `_sm_apply`·`_jig_apply`)·BD_POST(`_sm_post`·`_jig_post`)만. 행렬 생성 `bd_matrix` → `mx.generate(spec, tab, c.cfg)` 는 `cfg.doe`·`cfg.limits`·`max_designs` 만 읽음(rank 무관). `_cfg_hash` 는 rank 스냅샷 키 유무로 `stiffness`·`jig` 를 더함 — 이어하기 키이지만 복제본은 **새 스터디 폴더**라 이어할 안이 없음. 미리보기(`preview()`)·`_generate`·`_study_cfg` 도 rank 를 읽지 않음 |
| 옛 스냅샷(v0.20.0 이전) | `test_legacy_study_has_no_rank_key` | rank·load_transfer 키 없음 = legacy, 복제도 키 주입 안 함(LT-11·SM 시험) |
| 지그 칩 | `F/components/DoeRanking.tsx:JigLine`, `DoeStudy.tsx:StatusBand` | `result.jig` 있을 때만 칩. ok = `muted`, poor·fallback = `warn-text`, unsupported = `muted` |
| 3D 비교 | `stages.py:_view3d` → `post/view3d/<did>/`(`esl.view3d.build_view`: part.glb·values.bin·manifest.json, manifest `supports[]`·`esl_run_id`) — 안의 최악 ESL(`worst_entry_id`), 전 노드 ESL 하중, 지지 = `t.supports`(3-2-1). ④ 만 LT-9 `view3d_ref{entry_id: "d000_e<kk>"}`·`view3d_esl{did: entry_id}` | 지그 응답 변위장은 어디에도 저장되지 않음(`respond(keep_u)` 는 베이스라인 진단에만, `design_response` 는 u 버림) |
| 지그 재풀이 | `esl/doe/jig.py:design_response(mesh, jig_idx, loads, solver_cfg, *, umax_mask)`·`respond(h, loads, *, keep_u)`·`forces(basis, a, N)`, `stages.py:_jig_design`(jig.npz → F_i → K_d 재풀이) | 3D 용 변위는 같은 함수로 다시 얻을 수 있음 |
| 3D API | `services/doe.py:_view3d_dir` — `DID_RE ^[0-9a-z_]{1,64}$`, `post/view3d/<did>` 폴더면 제공(목록 검사 없음) | 새 폴더 이름도 같은 경로로 제공됨(API 코드 변경 없음) |
| 지지 마커 | `F/view3d/supports.ts`·`scene.ts:setSupports` — 지지점마다 글자 스프라이트 1개 | tie 노드 수천 개를 그대로 넘기면 무겁고 화면을 덮음 → 표시용 부분집합 필요 |

## 1. 복제 시 순위 설정 갱신 (D-0.23.2-1)

- `clone()`: 옛 스냅샷에 `rank`(dict)가 **있으면** `d["rank"] = rank_snapshot(cfg(ctx))`(지금 설정 — 새 스터디와 같은 함수), `inputs.rank_metric` 도 새 값. 옛 스냅샷에 `rank` 가 **없으면**(v0.20.0 이전 legacy) 지금처럼 주입하지 않음(load_transfer legacy 와 짝 — legacy 해시·경로 보존, 기존 시험 그대로).
- 값이 실제로 바뀌면(`old["rank"] != 새 rank`) 준비 작업 경고 1줄 `{"code": "RANK_REFRESHED", "message": "순위 설정을 지금 설정으로 갱신했습니다(원 스터디 순위 지표 {old metric} → {new metric}{, 지그 계산 추가})"}` — 기존 `SELECTION_DROPPED` 와 같은 경로(`params.warnings`·작업 warnings). inputs 에 별도 기록은 하지 않음(필요 최소).
- **설계안 생성·이어하기 해시 무영향 근거**(§0): rank 는 평가·후처리만 읽는다. 행렬(`mx.generate`)·미리보기(`_generate`, `_study_cfg`)·`selection`·`load_transfer`·`shape_rules`·`cfg` 처리는 바뀌지 않는다. 복제본은 새 폴더라 `_cfg_hash` 로 재사용할 안 결과가 없다.
- 다른 복제 정책(load_transfer 유지 + diag 갱신, selection 복사, 업로드 소유 검사, 제목 "(복제)")은 그대로.
- 기존 시험 `test_snapshot_follows_config_and_clone` 의 "복제 = 원 스터디 값 유지"는 이 결정으로 **바뀐다**(지금 설정으로 갱신).

## 2. 복제 설계안 동일성 — **해당 없음(사용자 의도)** (D-0.23.2-2)

- 2026-11-18 13:04 사용자 정정: 복제본의 20안·다른 LHS 는 사용자가 복제 후 샘플 수 20 으로 새로 샘플링한 **의도된 결과**(버그 아님). 범위에서 철회 — 복제의 설계안 생성 동작은 바꾸지 않는다(코드 변경 없음).
- 참고(조사 기록): 복제는 `spec`·`rev`·`matrix_sha256` 을 옮기지 않고 스터디 `doe` 열도 비워 두므로, 복제본의 DOE 설정 칸은 설정 기본(`bead_doe.doe.default_*`·`default_types`)에서 시작하고 사용자가 고친 값으로 미리보기 때 새 행렬이 만들어진다. 같은 spec·같은 변수 표면 `mx.generate` 는 결정적이라 같은 id↔값을 만든다.

## 3. 지그 칩 항상 표시 (D-0.23.2-3)

상태 띠 첫 칩(`data-testid="jig-line"`, `ChipDetail` 그대로)은 결과가 있으면 **항상** 그린다.

| 상태 | 조건 | 보이는 값 | 색 |
|---|---|---|---|
| 계산됨 ok | `result.jig.status == "ok"` | 기존 "기준 재현(지그) MAC ≥ … · umax 오차 ≤ …" | **기본 글자색**(이전 muted) |
| 계산됨 poor | `status == "poor"` | 기존 | warn-text(유지) |
| fallback | `status == "fallback"` | 기존 "지그 순위 불가 · 재풀이 C" | warn-text(유지) |
| unsupported | `status == "unsupported"` | 기존 | 기본 글자색(이전 muted) |
| **미계산** | `result.jig == null` ∧ `result.jig_on_clone == true` | "지그: 미계산(이전 설정 스터디 — 복제하면 계산)" | 기본 글자색 |
| **미계산·불가** | `result.jig == null` ∧ `jig_on_clone != true` | "지그: 미계산(이전 설정 스터디 — 이 방식은 지그 순위 없음)" | 기본 글자색 |

- 칩 `data-status` = `jig.status` 또는 `"none"`(미계산 두 상태). title·펼침 전체 문구 = 보이는 값 + 근거 한 줄("이 스터디는 지그 순위 도입(v0.23.0) 전 순위 설정으로 만들어져 지그 C 를 계산하지 않았습니다 …").
- 새 응답 필드 `DoeResultOut.jig_on_clone: bool | null` — 결과에 `jig` 블록이 **없을 때만** 채움: 이 스터디를 복제하면 지그가 계산되는가 = (준비 스냅샷에 `rank` 있음 — §1 갱신 대상) ∧ (계획 표 `plan_for(scenario, select_base).sm_jig == "base"`). jig 블록이 있으면 null. 화면은 시나리오 이름으로 분기하지 않는다.
- 색: "눈에 잘 띄게" — 중립 상태는 `muted` 를 빼 기본 글자색, 경고 상태색(warn-text)은 유지. 새 색·폰트 없음.
- 옛 스터디 결과 파일·응답의 기존 키는 그대로(새 키 `jig_on_clone` 만 추가).

## 4. 3D 비교 하중 조건 라벨 + 지그 응답 (D-0.23.2-4)

### 4.1 저장 방식(코어 BD_POST — 요청 시 계산 아님)
- 평가(BD_EVAL) 때 안마다 3D 변위를 저장하지 않는다(안 수 × 엔트리 × N×3 — 대형 모델에서 수 GB). 대신 **BD_POST 의 3D 비교 대상(베이스라인 + 상위 k, 기존 `view3d.top_k`)에 대해서만** 지그 응답을 다시 풀어 기존 3D 결과 파일 형식(`build_view`)으로 쓴다. 비용 = 표시 안마다 분해 1회 + 풀이 1회(기존 view3d 와 같은 규모).
- 조건: 스냅샷 지그가 계산됨(`prep/jig.json` status ok, `prep/jig.npz` 있음) ∧ 설정 `bead_doe.view3d.jig` 참. 아니면 아무것도 쓰지 않음 → 옛 스터디·지그 없는 스터디 결과 바이트 동일.
- 안 d 의 엔트리 e_d = argmax_i C_jig,d,i / C_ref,i(jig.npz `C_ref`, 동률 = 엔트리 순서 앞) — 지그 기준 최악 ESL(metric jig 이면 순위 행 `worst_entry_id` 와 같음). C_jig 가 없으면 지그 3D 없음(그 안만).
- 파일: 안 `post/view3d/<did>_jig/`, 베이스라인은 쓰인 엔트리마다 `post/view3d/d000_jig_e<kk>/`(kk = 스냅샷 엔트리 순서 2자리, LT-9 `d000_e<kk>` 와 같은 규칙). 내용 = `build_view(node_id, x0 = 안 좌표, conn, elem_type, f = F_e(지그 맞춤 하중, `jig.forces`), u_rel = 지그 응답 u(강체 제거 없음 — tie 고정이라 강체 성분 없음), supports = tie 노드 표시용 부분집합(dof "123"), esl_run_id = e)`.
- tie 표시 부분집합: 지그 노드 J 에서 최원점 샘플링(첫 점 = J 중 가장 작은 인덱스, 이후 이미 고른 점까지 거리 최대, 동률 = 작은 인덱스)으로 `min(|J|, view3d.jig_support_max)` 점. 전체 수는 결과 `jig.n_jig`.
- 결과 `post/result.json` 새 키(지그 3D 를 하나라도 썼을 때만): `view3d_jig{did: dir}`, `view3d_jig_esl{did: entry_id}`, `view3d_jig_ref{entry_id: "d000_jig_e<kk>"}`. 실패(예외)는 경고 `VIEW3D_FAILED: <did>_jig <code>` 1줄, 그 안만 빠짐(순위·기존 3D 영향 없음).
- 공용 계산: `esl/doe/jig.py` 에 `design_response(..., keep_u=False)` 키워드(가산 — 기본 동작·결과 불변)와 `support_sample(x, jig_idx, m)`(순수 함수) 추가. 호출 측(`stages.py`)은 계획 표 열 `sm_jig` 과 jig.json 상태만 읽음(시나리오 분기 없음).

### 4.2 설정 (DEFAULTS · `BeadDoeView3dCfg` · yaml 2 — 같은 이름)
| 키 | 기본 | 범위 | 뜻 |
|---|---|---|---|
| `bead_doe.view3d.jig` | `true` | bool | 지그 계산된 스터디의 3D 비교에 지그 응답 변위장도 만듦 |
| `bead_doe.view3d.jig_support_max` | `64` | 1..2000 | 지그 3D 의 tie 고정 마커 최대 수(표시만) |

### 4.3 API
- `DoeResultOut` += `view3d_jig`·`view3d_jig_esl`·`view3d_jig_ref: dict[str,str] | null`(코어 값 통과 — 없으면 null), `jig_on_clone`(§3). 3D 파일 엔드포인트는 그대로(`/view3d/<did>_jig`).

### 4.4 화면 (`DoeStudy.tsx:Compare3D`)
- 머리 한 줄(`data-testid="v3d-cond"`) = `하중: {전 노드 ESL 재풀이 | 지그 하중} · 지지: {3-2-1 | tie 고정({n_jig}점)} · 엔트리: {이름}`. 엔트리 이름 = 두 그림 manifest `esl_run_id` → `result.esl` 라벨(같으면 1개, 다르면 "기준 A · 안 B").
- 지그 3D 가 있으면(`view3d_jig[did]` 존재) 기본 = 지그 응답: 왼쪽 = `view3d_jig_ref[e_d]`, 오른쪽 = `view3d_jig[did]`. 세그먼트 토글 1개(`.seg`, `data-testid="v3d-mode"`, [지그 하중 | 전 노드 ESL])로 기존 컨투어 선택. 토글은 지그 3D 가 있을 때만(새 버튼 = 이 토글 1개).
- 지그 모드 지지 마커 = manifest supports(tie 부분집합 "123" — 기존 기호 렌더 그대로), 색 라벨 "변위 |u| (mm) — 지그 고정(강체 성분 없음)".
- 옛 스터디·지그 3D 없음 = 기존 그대로 + 조건 라벨(하중: 전 노드 ESL 재풀이 · 지지: 3-2-1 · 엔트리).

## 5. 계획 표 · 모드 차이

| 계획(PLANS) | sm_jig | 복제 rank 갱신 | jig_on_clone | 지그 3D |
|---|---|---|---|---|
| case_once(①·select case) | base | rank 있으면 | true | jig ok 일 때 |
| bmesh_once(②·select mesh) | base | 〃 | true | 〃 |
| step_once(새 ③) | base | 〃 | true | 〃 |
| step_per_design(옛 ③) | none | 〃(지그 unsupported) | false | 없음 |
| compare_per_shape(④) | none | 〃(지그 unsupported) | false | 없음 |

새 계획 열 없음(기존 `sm_jig` 만 읽음).

## 6. 시험 (V-0232-n)

| id | 내용 | 위치 |
|---|---|---|
| 1 | 복제: 원 rank schema 1(solve, jig 없음) → 복제 작업 spec `rank == rank_snapshot(지금 설정)`(schema 2·jig), `inputs.rank_metric` 새 값, 경고 `RANK_REFRESHED` 1개; 같은 설정이면 경고 없음; legacy(rank 없음)는 주입 없음(기존 시험); load_transfer 유지·diag 갱신 그대로; 복제본 `doe` 없음(설계안 동작 불변) | `backend/tests/test_doe_rank_metric_api.py` |
| 2 | `jig_on_clone`: jig 블록 없는 결과 + rank 있음 + same/select → true, ④ → false, rank 없음 → false, jig 블록 있으면 null | 같은 파일 |
| 3 | 코어: 지그 ok 합성 스터디(V-JIG-12 픽스처) BD_POST → `post/view3d/<did>_jig/manifest.json`·`d000_jig_e00`, supports dof 123·개수 ≤ jig_support_max, esl_run_id = argmax 엔트리, values = 같은 하중·같은 지그 재풀이 u(`design_response(keep_u)` 와 일치), result `view3d_jig*`; `view3d.jig false` → 키·폴더 없음; 지그 없는 스냅샷 결과 키 불변 | `tests/doe/test_jig_stages.py` |
| 4 | `support_sample` 결정적·최원점·m ≥ |J| 이면 전부; `design_response(keep_u=True)` u 모양·기본 호출 결과 불변 | `tests/doe/test_jig.py` |
| 5 | 설정 거울: `DEFAULTS["view3d"]` == `BeadDoeView3dCfg()` == yaml 2, 범위 거부 | `backend/tests/test_doe_config.py`(또는 rank 시험 파일) |
| 6 | 칩 3상태: ok 기본 글자색(muted 없음)·poor/fallback warn-text·미계산(jig_on_clone true/false 문구)·`data-status="none"` | `F/__tests__/doe_v0232.test.tsx` |
| 7 | 3D: 조건 라벨(옛 = 전 노드 ESL·3-2-1, 지그 = 지그 하중·tie 고정(n점)), 지그 3D 있으면 기본 지그·토글로 전 노드 ESL, 없으면 토글 없음 | 같은 파일 |
| 8 | 회귀: backend·tests·deploy·worker pytest, vitest·typecheck·build·check:api, openapi `--check` | – |

## 7. 결정 (decisions.md)

| ID | 결정 |
|---|---|
| D-0.23.2-1 | 복제는 원 스냅샷에 rank 가 있으면 지금 설정 `rank_snapshot` 으로 교체(+ inputs.rank_metric, 바뀌면 경고 RANK_REFRESHED 1줄). legacy(rank 없음)는 주입 없음. rank 는 평가·후처리 전용이라 설계안 생성·미리보기·selection 무영향, 복제본은 새 폴더라 이어하기 해시 무관 |
| D-0.23.2-2 | 복제 설계안 동일성 — 해당 없음(사용자 의도: 복제 후 새 샘플링). 복제의 설계안 생성 동작 불변 |
| D-0.23.2-3 | 지그 칩은 결과마다 항상 첫 칩: 계산됨(기존)·미계산(jig_on_clone 로 "복제하면 계산"/"이 방식은 없음")·fallback(경고). 중립 상태 = 기본 글자색, 경고색 유지. 응답 `jig_on_clone` = rank 있음 ∧ 계획 sm_jig base |
| D-0.23.2-4 | 지그 3D = BD_POST 에서 3D 비교 대상(베이스라인 + 상위 k)만 지그 응답 재풀이, 기존 view3d 형식 `<did>_jig`·`d000_jig_e<kk>`, 결과 `view3d_jig{,_esl,_ref}`, tie 마커 = 최원점 부분집합(`view3d.jig_support_max`). 설정 `view3d.jig`. 화면 = 조건 한 줄 + 세그먼트 토글 1개(지그 하중 기본) |
