# 계약: t* 임의 프레임 선택 + 체결부 아닌 곳 지그 BC 강제 부여 + #96 표시 개선 (TM·JF·DS, v0.25.2)

- 상태: **개정 1 → 구현·통합 완료**(2026-11-27 — 사용자 답 Q-1 확정·Q-2 "거리 무관 무조건" 반영, §14). 구현 사실·통합 보정 = §15.1~§15.4(INT-n). 이 문서가 원본.
- 기준: `release/v0.25.1` 5d1971f4(읽기만 감사). **v0.25.1 은 구현 중** — 이 계약의 구현은 v0.25.1 이 `release/v0.25.1` 에 다 합쳐진 뒤 그 헤드에서 시작한다(§11 전제). 아래 줄 번호는 5d1971f4 기준.
- 결정 기록: `docs/decisions.md` 2026-11-27 D-0.25.2-1~26. 충돌하면 이 계약이 우선.
- 배경 이슈: #96 "다른 형상 step 에러 / NO_FEASIBLE_DESIGNS".

### 사용자 요청 (원문, 변경 금지 — 2026-11-27)

> "t 확정할때 현재는 최대 변형을 탐지하는거야. 이거에 사용자가 임의 t를 정하고 싶어해. 그러니 추가로 frame 별 t를 정하게 하기위해 현재 ui의 그래프에서 마우스 클릭하면 h3d에서 읽은 t를 선택하게 끔 한다던지 아니면 t 선택하는 고급사항을 추가 ui 만들던지 해줘."

> "체결부가 아니여도 강제로 그 위치에 스프링 요소나 타이 변위경계를 부여하는건 어때? 체결부가 아닌곳이 얼마이고 이러한 거는 경고로 참조하게 하는거지"

이슈 #96 (요약 — 원문은 이슈): ④ 형상 직접 비교, 기준 d000 = Case 메시(요소 193,362 · quad 0.986 · 품질 Fail 0.24 %), d001 = `75QN80H_chassis_rear_PV_ISTA.stp`(요소 380,033 · quad 0.78 · 품질 Fail 55.46 %). `JIG_GRID_TIE_MISS` 128/228(허용 `tie_miss_frac_max` 0.1) → d001 이 격자 지그 순위에서 빠짐 → `NO_FEASIBLE_DESIGNS`. 보고서 줄 "성공 0 · 실패 메시 0·크기/정렬 0·해석 0". `JIG_GRID_AREA_RATIO` 0.00939~0.95.

---

## 0. 감사 (5d1971f4, 읽기만)

### 0.1 t* — 지금 고를 수 있는 것과 자료

| 항목 | 지금 | 위치 |
|---|---|---|
| 자동 t* | 지표(max_strain·plastic_strain) max-hold 곡선에서 최종값 1위 요소가 그 값에 **처음 도달한 프레임**(first-reach). 후보 = 상위 `tstar.top_n_times` 개 | `esl/pipeline.py:716 stage_tstar` · `esl/mech/tstar.py` |
| 사용자 선택 | **후보 안에서만**, 그리고 변위가 있는 프레임(D)만. 그 밖 = 422 `FRAME_NOT_CANDIDATE` | 코어 `_select_frame`(`pipeline.py:702`) · 백엔드 `core/tstar_confirm.select_candidate` · `core/job_params.py:58` · CLI `--frame`("후보 안에서만") |
| 화면 | ② 곡선은 보기만(클릭 없음), 후보 표의 라디오로 선택. 곡선의 t* 세로선 위치는 `time[selectedFrame]`(프레임 번호 = 배열 위치 가정) | `frontend/src/stages/Stage2.tsx` · `components/MaxHoldChart.tsx:74` |
| 전 프레임에 있는 자료 | `01_extract/history.npz` — **모든 프레임 × hot 요소 H**(지표 곡선·프레임 시각). 곡선·시각은 이미 전 프레임 | TCL 패스 B |
| D 프레임에만 있는 자료 | `disp.npz`(전 노드 변위) · `strain_frames.npz`(전 요소 변형률, D ∪ 직전 프레임 P) · `bforce.*`(경계력 — v0.24.2 부터 ESL 때 그 프레임만 보충) | TCL 패스 C · `esl/io/bforce_ondemand.py` |
| D 의 크기 | 지표마다 first-reach 프레임 상위 `top_n`(기본 5) → 보통 5~10 프레임 | `resources/tcl/esl_h3d_extract.tcl` 머리말 |

**결론**: 임의 프레임에서 ESL(변위 → F_eq)·지그 목표 변위·hotspot 평가·④ 검증에 필요한 **전 노드 변위와 전 요소 변형률은 D 밖 프레임에는 없다.** 곡선 값과 시각만 있다. → D 밖 프레임을 고르면 그 프레임만 h3d 에서 한 번 더 읽어야 한다(§2.4). 전례 = v0.24.2 경계력 보충(`bf_only` — 같은 틀: 워커가 ESL 단계 전에 hw 1회, `01_extract` 병합, 재사용).

### 0.2 격자 지그 tie 잡기 (`esl/mech/grid_map.py:371 capture`)

- 단계 2개: **band**(형상 노드 → Case tie 골격 거리 ≤ `tie_capture_rel`·max(h_T, h_S) ∧ 법선 맞음 `tie_normal_deg`) → 띠가 0 인 묶음은 **snap**(법선 맞는 최근접 1노드, ≤ `tie_snap_rel`·max(h_T, h_S)) → 그래도 0 = **miss**.
- `run_shape:788`: 잡힌 노드 0 이거나 `n_miss/n_clusters > tie_miss_frac_max` 면 그 형상의 모든 지그 방식이 `failed · JIG_GRID_TIE_MISS` → per_esl `C_jd`·`C_js` = null → `rank.py:210` 이 `n_failed["jd"|"js"]` 로 세고 순위 밖.
- 스프링 k: `shape_spring_k` 가 **묶음 합 K_q 를 보존**(c_q = K_q / Σk̃). 강제 변위 값: 골격 보간(`sample_tie`).
- 설정 병합 `_jg_cfg`(`stages.py:6745`): `{**DEFAULTS, **스냅샷 원본}` — **새 키를 DEFAULTS 에 켬으로 넣으면 옛 스냅샷에도 적용된다.** → 새 기능은 "스냅샷 원본에 키 있을 때만" 규칙이 필요(§3.6).
- 해시 `grid_map.hash_view`: 스냅샷 원본 키만 → 키 없는 옛 스냅샷 해시 불변.

### 0.3 #96 표시 (코드 확인)

| 증상 | 원인 | 위치 |
|---|---|---|
| "성공 0 · 실패 메시 0·크기/정렬 0·해석 0" | `n_failed` 에는 `{"jd": 1}` 이 들어 있으나 줄이 `mesh`·`size`·`solve` 3키만 찍음 | `esl/doe/report_doe.py:525` |
| 화면 제목 "OK 0개 형상" 만 | 제외 수를 보여 주지 않음 | `pages/doe/DoeStudy.tsx:2020` |
| 지그 탭이 비면 순위가 없어 보임 | 기본 탭 = 주 출처(지그 변위). 전 노드 보기(`rank_views.full` — 재풀이 C)는 코드상 만들어지나(`_src_need` 격자 = ok 인 첫 방식의 need, 기준에 `C_jd` 있음) 기본 탭이 아니고 안내가 없음 | `doeTabs.ts tabState` · `stages.py:5076` |
| 보고서 "3. 순위" 가 빈 문구만 | 주 순위만 실음 | `report_doe.py:523` |
| 놓친 체결부 위치를 볼 수 없음 | 형상별 `jig_grid.json map.tie` 는 개수·면적비 요약뿐(묶음 위치 없음) | `grid_map._tie_diag` |
| STEP 이 판 앞뒷면 두 장이어도 경고 없음 | ④ 형상 검사에 해당 규칙 없음(`STEP_NOT_SHEET`·`STEP_BODY_COUNT` 는 ① paicad 경로) | `stages.py:2335 _cmp_mesh_notes` |

- #96 원인 후보(미확정 — 이 계약은 원인을 단정하지 않음): ⓐ STEP 이 중립면 한 장이 아니라 판 앞뒷면 표면 ⓑ 다른 모델이라 체결 위치가 다름 ⓒ 좌표 정렬 어긋남. **정황**: 요소 수 비 380,033 / 193,362 = 1.97(≈ 2 — ⓐ 와 맞음). §4.4 검사와 현장 확인 E-0252-9 로 가린다.

---

## 1. 범위 · 비범위 · 용어

### 1.1 범위

- **A (TM)** ② 에서 t* 를 **h3d 의 아무 프레임**으로 고르기: 곡선 클릭(가장 가까운 프레임으로 맞춤) + 직접 입력 1칸. D 밖 프레임은 ESL 때 그 프레임만 h3d 에서 읽어 채움.
- **B (JF)** 격자 지그에서 형상이 못 잡은 Case 체결부 묶음을 **가장 가까운 형상 면에 강제로** 붙임(강제 변위·스프링 공통) + 경고·"참고용" 표시.
- **C (DS)** #96 표시: 결과 개수 줄, 빈 지그 탭, 3D 에 놓친/강제 체결부 표시, 판 앞뒷면 두 장 경고.

### 1.2 비범위

- 한 Case 에 t* 여러 개 → ESL 여러 개(§2.1 — 사용자 확정).
- 덤프 방식(Strain 텐서 순간값) Case 의 D 밖 프레임 선택(§2.4 — R-TM-1).
- 결과 CSV 폴더로 만든 Case(h3d 없음)의 D 밖 프레임.
- 같은 메시 지그(①②③ — Case tie 노드를 그대로 씀)의 강제 부여: 놓칠 수 없어 해당 없음.
- 강제 부여 위치를 사용자가 손으로 고치기, 형상 자동 정렬(좌표 맞춤), 두 장 STEP 에서 중립면 자동 추출.
- #96 형상의 원인 확정·메시 품질(Fail 55 %) 개선.

### 1.3 용어

| 말 | 뜻 |
|---|---|
| 프레임 | h3d 출력 시점 1개(`frame_index`, 시각 `time`). "h3d 에서 읽은 t" = 이 시각 |
| D | 추출 때 변위·변형률을 받은 후보 프레임 집합(`frames.json frames_D`) |
| 채움(fill) | D 밖 프레임 1개의 변위·변형률을 h3d 에서 추가로 읽어 `01_extract` 에 덧붙이는 일 |
| 직접 고른 t* | 후보 표 밖 프레임을 고른 t*(`tstar.manual` 있음) |
| 묶음 | Case 지그 tie 점의 연결 성분(체결부 1곳, `skel.q`) |
| 강제 부여 | band·snap 으로 못 잡은 묶음을 조건을 풀어 최근접 형상 노드에 붙임(`via: "force"`) |
| 못 붙임 | 강제 단계 뒤에도 붙일 형상 노드가 없는 묶음(`via: "miss"`) — 개정 1: 거리 한도가 없으므로 형상에 남은 노드가 없을 때(또는 관리자가 준 한도·법선 조건 밖)뿐 |
| 참고용 | (강제 + 못 붙임) 묶음 비율이 `tie_miss_frac_max` 를 넘거나 먼 강제가 1곳이라도 있는 형상의 지그 순위 |
| 먼 강제 | 강제로 붙인 거리가 `tie_force_far_warn_mm`(기본 10 mm)를 넘는 묶음 — 붙이기는 하되 경고·3D 에서 따로 셈 |

---

## 2. A — t* 임의 프레임 (TM)

### 2.1 "frame 별 t" 의 해석 (D-0.25.2-1)

**한 Case 에 t* 는 하나, 그 하나를 h3d 의 아무 프레임으로 정할 수 있다.** 근거: 원문이 "그래프에서 마우스 클릭하면 h3d 에서 읽은 t 를 선택" — 고르는 단위가 h3d 프레임이라는 뜻이고, Case·ESL·지지 세트·라이브러리 엔트리가 모두 "Case 1 = t* 1 = ESL 1" 구조(`cases.tstar` 1개, `inputs_hash` 에 프레임 1개)다. 여러 시점의 ESL 이 필요하면 지금처럼 Case 를 복제해 각각 t* 를 고른다. **사용자 확정 2026-11-27**(D-0.25.2-23).

### 2.2 고를 수 있는 프레임

- 대상 = `history.npz` 에 있는 프레임 전부(추출 `frame_stride` 1 이면 h3d 전 프레임). 지표·누적 씬 여부와 무관.
- 세 부류: **후보**(지금 그대로) · **D 안의 비후보**(자료 있음 — 바로 가능) · **D 밖**(채움 필요 — §2.4 가능 판정).
- 시간 창(`tstar.time_window`)·제외 요소(`tstar.exclude_elem_ids`)는 자동 후보 계산에만 쓰고 직접 선택을 막지 않는다. 근거: 직접 선택은 자동 규칙을 벗어나려는 것.

### 2.3 직접 고른 t* 의 값 (코어 한 곳)

- 순수 함수 `esl.mech.tstar.point_at(series (F,H), frame_pos, exclude_mask) -> {elem_pos, value}`: 그 프레임에서 지표가 가장 큰 H 요소(동률 = 작은 인덱스, 제외 요소 뺌). 누적 씬 = 누적 계열(자동과 같은 계열).
- 파이프라인 래퍼 `esl.pipeline.frame_point(out_dir, cfg, metric, frame_index) -> {frame_index, time, elem_id, value, auto{frame_index, time, value}, ratio, rel, in_D, have}`
  - `ratio` = value / 자동 t* 값. `rel` = `"before"`(자동보다 앞) | `"at"` | `"after"`.
  - `in_D` = `frames_D` 포함, `have` = `disp.npz` 와 `strain_frames.npz` 에 그 프레임이 있음(D ∪ 이미 채운 프레임).
- 백엔드(확정 저장)·코어(`_select_frame`)·보고서가 이 함수만 쓴다(같은 값).
- `_select_frame(tj, frame)` 확장: 프레임이 **`disp.npz` 에 있으면** 허용(후보 여부 무관). 후보 프레임은 지금과 같은 레코드(바이트 불변), 비후보는 `frame_point` 값 + `"source": "user", "manual": {…}`. `disp.npz` 에 없으면 지금 코드 `FRAME_NOT_CANDIDATE` 유지(문구만 "변위가 추출되지 않은 프레임 — 채움 필요").
- CLI `--frame N` 도움말: "t* 수동 지정(frame_index — 변위가 있는 프레임)". 새 인자 없음(시간 → 프레임 맞춤은 화면이 함).

### 2.4 D 밖 프레임 채움 (D-0.25.2-3·4)

**언제**: [t* 확정] 때가 아니라 **③ ESL 단계 시작 전**(워커, 코어 자식 시작 전 — 경계력 보충 바로 앞). 근거: ② 화면은 프레임 자료가 필요 없고(지지점 자동 선택 = 모델만), API 프로세스는 hw 를 못 돌리며, 일괄 실행·재추출 뒤 재시도가 같은 경로로 풀린다.

**무엇을**: hw 1회로 그 프레임 f 의
- 전 노드 변위(`disp.csv`), 전 요소 변형률 f 와 f−1(`strain_frames.csv` — 상승 중 판정용, f = 0 이면 f 만),
- 경계력·내력 종류(`bf_<kind>.csv`, `bf_on 1` 일 때 — 같은 실행에서 함께 읽어 뒤따르는 경계력 보충이 "있음" 이 됨).

**TCL 새 모드** `fr_only 1` + `fr_frames "<f>"`(요청 키, 기본 0 = 지금 출력 그대로):
- 변형률 출처는 추출 때와 같은 것을 요청이 고정(`frames.json strain_source` → `strain_type` 등). 순위·H·D 계산 없음, `frames.csv`·`model.csv`·`elems.csv`·`final.csv`·`history.csv` 안 씀.
- `done.json {"ok": true, "mode": "fr_only", "n_frames", "n_nodes", "n_elems", "frames": [f], "prev_frames": [f−1], "frame_times": {…}, "strain_source", "bforce"?, "passes": {"FR": {…}}}`. 프레임 ≥ 프레임 수 = `H3D_MISSING_RESULT`. 실패 json 에 `"mode": "fr_only"`.
- `bf_only` 와 동시 지정 = `INPUT_INVALID`.

**병합** — 새 독립 모듈 `esl/io/frame_fill.py`(numpy · `esl.errors` · `esl.io.results_csv` · `esl.io.backup` 만 import, `esl.pipeline`·`esl.doe` 금지, 설정 해석 없음 — `bforce_ondemand.py` 와 같은 규칙):
- `merge(extract_dir, fill_out, frame) -> {frame, time, added: bool}`: 같은 h3d 확인(프레임 수 = `frames.json n_frames_h3d`, f·f−1 시각 = `history.npz` 시각 정확 일치 — 아니면 `FRAME_FILL_MISMATCH`, 아무것도 안 씀) → `disp.npz`·`strain_frames.npz` 에 **끝에 덧붙임**(기존 키·dtype·기존 행 위치 불변, 이미 있는 프레임은 건드리지 않음) → `frames.json` 에 새 키 `frames_fill: [{frame_index, time, at, job_id}]` 추가. **`frames_D`·`time_D`·`candidate_frames` 는 바꾸지 않는다**(자동 t* 재계산 결과 불변).
- 쓰기 = 임시 파일 → 이전 파일 사본을 `<Case>/_backup/<UTC>/01_extract/` → `os.replace`(npz 2개 → json 마지막).
- 시도 기록 `01_extract/frame_fill.json`(`esl/frame_fill/1`: `attempts[{frame, job_id, status ok|failed|blocked, cause, detail, seconds, at}]`) — 형식 소유는 이 모듈.
- **판정 표 `DECIDE`**(이 모듈 한 곳 — 워커와 백엔드가 같은 표를 읽음, 사실 `Facts` 는 호출부가 모음. 위에서부터 첫 일치):

| 행 | 조건 | 동작 | 사유 코드 | 화면 문구 |
|---|---|---|---|---|
| 1 | 그 프레임이 `disp.npz`·`strain_frames.npz` 에 있음 | have | – | – |
| 2 | Case 입력이 결과 CSV 폴더(h3d 없음) | block | `NO_H3D` | "이 Case 는 h3d 없이 만든 것이라 후보 프레임만 고를 수 있습니다" |
| 3 | 추출이 덤프 방식(`strain_fallback.mode = dump`) | block | `DUMP_MODE` | "변형률을 순간값으로 받은 Case(덤프 방식)는 후보 프레임만 고를 수 있습니다" |
| 4 | 입력 h3d 를 읽을 수 없음 | block | `H3D_UNREADABLE` | "입력 h3d 를 읽을 수 없습니다({name})" |
| 5 | 서버에 hw 실행 파일·TCL 없음 | block | `HW_UNAVAILABLE` | "서버 HyperWorks 를 쓸 수 없습니다(관리자 문의)" |
| 6 | 그 밖 | fill | – | – |

- 덤프 방식을 뺀 근거(행 3): 덤프는 max-hold 를 파이썬이 전 프레임에서 다시 만들어, 프레임 1개만 읽어서는 그 시점의 hold 값을 만들 수 없다(0..f 전부 필요 — 수십 분). 후속 R-TM-1.

**실패 처리**: 채움 실패(시간 초과·hw 실패·라이선스·`FRAME_FILL_MISMATCH`) = **ESL 단계 실패** `TSTAR_FRAME_FILL_FAILED`(사유 = 기록 `detail`). 경계력 보충과 달리 계속하지 않는다 — 변위가 없으면 ESL 을 계산할 수 없다. 다시 실행하면 재시도.

**비용**(추정 — 현장 E-0252-3 에서 실측): hw 시작·모델 로드 ≈ 0.5 분 + 선택·id·청크 준비 ≈ 2.5 분 + 노드 변위 ≈ 5 s/청크 + 요소 변형률 2 프레임. 요소 19 만 Case ≈ **3~6 분, 프레임마다 한 번만**(다음 ESL 부터 재사용). hw 동시 실행 한도(`altair.max_concurrent_hw`)를 1개 씀. 저장: 프레임당 변위 24 B/노드 + 변형률 ≈ 48 B/요소 × 2 → 19 만 요소 ≈ 25 MB.

**설정**(새 키 2개, 4곳 같은 이름 — pydantic `AltairCfg`·`config/esl_platform.example.yaml`·`.prod.example.yaml`·워커 읽기): `altair.frame_fill_timeout_s` 1800(≥ 60) · `altair.frame_fill_wait_s` 600(≥ 0, hw 한도 대기 — 넘으면 실패 `WAIT`). 근거: 경계력 보충 키를 같이 쓰면 이름과 뜻이 어긋남.

**재추출(①)** 하면 `01_extract` 전체가 백업으로 옮겨져 채운 프레임도 사라진다 → 직접 고른 t* 가 새 D 에 없으면 다음 ESL 때 자동으로 다시 채운다(판정 표 행 6). 사용자 조작 없음.

### 2.5 직접 고른 t* 가 뜻하는 것 · 경고

- ESL 은 **그 시점의 변위**로 만든다(순간값) — 자동 t* 와 같은 식(`stage_esl` 불변, 프레임만 다름).
- h3d 의 변형률은 max-hold(지나간 최대를 유지) → 자동 t* 뒤의 프레임에서는 변형률 값이 그 시점 값이 아니다. 그래서:
  - hotspot 평가(`_eval_hotspots`)는 지금 규칙 그대로 "그 프레임에 상승 중인 요소" 만 비교 → 직접 고른 프레임에 상승 중인 요소가 없으면 hotspot 0개, 변형률 비교 생략. ④ 판정은 변위 4지표라 영향 없음.
  - 경고·정보(문구 원본 `esl/io/messages.py` 한 곳, 화면 거울 `api/client.ts`):

| 코드 | 수준 | 조건 | 문구 |
|---|---|---|---|
| `TSTAR_MANUAL` | 정보 | 직접 고른 t* | "직접 고른 시점: 프레임 {f} · {t} s — 지표 값이 자동 t*(프레임 {fa} · {ta} s)의 {pct} % 입니다" |
| `TSTAR_MANUAL_LOW` | 경고 | `ratio < tstar.manual_ratio_warn`(기본 0.5) | "직접 고른 시점의 지표가 자동 t* 의 {pct} % 뿐입니다 — 하중이 최대에 한참 못 미친 시점의 ESL 입니다" |
| `TSTAR_MANUAL_AFTER` | 정보 | `rel = after` | "자동 t* 뒤 시점입니다 — 지표(max-hold)는 지나간 최대값이고, ESL 은 이 시점의 변위로 만듭니다" |
| `TSTAR_MANUAL_NO_RISING` | 정보 | 그 프레임에 상승 중 요소 0 | "이 시점에 변형률이 오르는 요소가 없어 변형률 hotspot 비교는 생략합니다(변위 검증은 그대로)" |

- 새 설정 `tstar.manual_ratio_warn` 0.5(0..1, 코어 `esl/config.py` DEFAULTS·`config/esl.example.yaml`·백엔드 코어 설정 통과 — 경고 임계만, 계산 불변).
- 기록: `04_esl/esl_summary.json` 에 `tstar_manual{auto_frame, auto_time, auto_value, ratio, rel, in_D, filled}` — **직접 고른 t* 일 때만 키가 생김**. Case 보고서(`case_report.py`) t* 줄 뒤에 위 `TSTAR_MANUAL` 문구 1줄(같은 조건).

### 2.6 다시 계산되는 범위

| 무엇 | t* 를 바꾸면 |
|---|---|
| ① 추출 · `02_tstar/tstar.json`(자동 후보) | 그대로(다시 안 돎). `01_extract` 는 채움 때 덧붙기만 |
| 지지 세트 | 그대로(`support_auto: KEPT` — 지금 규칙) |
| ③ ESL(F_eq·u_rel·잡음 바닥·Case 지그 목표 변위·경계력/내력 ESL) | **다시 실행 필요**(`inputs_hash` 에 프레임 — 지금의 "t* 바뀜" 표시 그대로) |
| ④ 검증 · ⑤ 내보내기 · 보고서 | ESL 뒤 다시 |
| 이미 등록한 라이브러리 엔트리 · 그걸 쓰는 강성 스터디 | 그대로(등록 사본·스냅샷). 이력 화면의 "t* 프레임" 차이 표시는 지금 기능 |
| 일괄 실행 | 자동 확정 규칙 불변. 직접 고른 t* = `source: user` → 지금의 `USER_TSTAR_CHANGED` 규칙 그대로 |

---

## 3. B — 체결부 아닌 곳 강제 부여 (JF)

### 3.1 잡기 단계 표 (선언형 — `grid_map.CAPTURE_STAGES`, D-0.25.2-8)

`capture` 가 이 표의 행을 위에서부터 돈다(단계 이름으로 분기하지 않음 — 열만 읽음). 앞 단계가 잡은 노드는 뒤 단계가 다시 쓰지 않는다.

| 단계(`via`) | 대상 묶음 | 거리 한도 | 법선 조건 | 고르는 노드 | 값 보간 | 켜는 조건 |
|---|---|---|---|---|---|---|
| `band` | 전부 | `tie_capture_rel`·max(h_T, h_S) | `tie_normal_deg` | 한도 안 전부 | 골격 보간 + 선형 외삽 | 항상 |
| `snap` | 띠 0 | `tie_snap_rel`·max(h_T, h_S) | `tie_normal_deg` | 최근접 1노드 | 그 골격 점 | 항상 |
| **`force`**(새) | snap 뒤에도 0 | **없음**(개정 1 — `tie_force.max_dist_mm` 기본 null. 관리자가 값을 주면 max(값, snap 한도)) | `tie_force.normal_deg`(기본 90 = 조건 없음) | **가까운 순으로 형상 노드 면적 합이 Case 묶음 면적에 닿을 때까지**(최소 1) | **골격 최근접점 값(외삽 없음)** | 스냅샷 `rank.jig_grid.tie_force.enabled` |
| `miss` | 그래도 0 | – | – | – | – | – |

행 1·2 는 지금 코드 그대로(값·순서·동률 규칙 불변). `VIA_FORCE = 3`, `VIA_NAMES[3] = "force"`.

### 3.2 강제 단계 규칙 (D-0.25.2-9)

snap 뒤에도 노드가 0 인 묶음 q 마다(묶음 번호 순 — 결정적):

1. **후보** = 아직 안 잡힌 형상 노드 중 묶음 q 골격(점·변·면)까지의 정확 거리 d 로 줄 세움 — **거리 한도 없음**(개정 1, D-0.25.2-24: `max_dist_mm` null = 형상 전체가 후보. 값이 있으면 d ≤ max(값, snap 한도)만). 구현 = 묶음 골격 점에서 KD 트리 최근접 질의를 넓혀 가며(k 배증) 필요한 면적이 찰 때까지 — 형상 전체를 정렬하지 않음. `normal_deg < 90` 이면 `_proj_ok` 와 같은 판정으로 거름.
2. **고르기** = (d, 노드 인덱스) 오름차순으로 형상 노드 면적 a_S 를 더해 Σa_S ≥ A_q(Case 묶음 면적)가 되는 첫 노드까지. 후보가 모자라면 있는 만큼(면적비 < 1 로 기록). 최소 1노드.
3. **보간 점** = 골격 위 최근접점(면 = 무게중심 좌표, 변 = 선형, 점 = 그 점 — 클립). 외삽하지 않는다. 근거: 멀리 떨어진 노드에 선형 외삽을 쓰면 값이 커질 수 있음.
4. 후보 0 = **못 붙임**(`miss`) — 한도 없음(기본)에서는 형상의 노드가 앞선 묶음들에 다 쓰였을 때뿐(실제로는 안 생김). 한도·법선 조건을 준 설정에서만 의미 있음.
5. **먼 강제**: `dist > tie_force_far_warn_mm` 인 묶음을 `far` 로 셈(붙이는 규칙은 같음 — 표시·판정용).

묶음 기록(`cap.clusters[q]` 에 추가): `via: "force"`, `dist`(강제 노드 최대 거리), `shift`(면적 가중 중심 이동 ‖x̄_S − x̄_A‖), `area_s/area_a`.

### 3.3 붙이는 BC — 방식 표 그대로 (D-0.25.2-10)

`jig_bc.METHODS` 에 **새 열 없음**. 강제 노드도 잡힌 노드와 같은 행 규칙:

| 방식 | 구속 방향 | 값 | 강성 |
|---|---|---|---|
| 강제 변위(`prescribed`) | 형상 자기 법선 부분공간(`tie_rows`) | 골격 최근접점의 Case 변위(R_pl 회전) | – |
| 스프링(`spring`) | 같음 | 같음(받침 변위 g) | k̃ = κ(최근접점)·a_S / r_n 에 **묶음 합 보존** c_q = K_q/Σk̃ → **Σk = K_q**(지금 `shape_spring_k` 일반 가지 그대로) |
| 고정(`fixed` — 켠 스냅샷만) | 같음 | 0 | – |

**보존되는 것**: 묶음마다 스프링 강성 합 K_q(정확), 면적(≈ — 규칙 2), 변위 값(Case 그 체결부의 값). **보존되지 않는 것**: 위치(이동 `shift` — 한도가 없어 클 수 있음, 경고에 거리 분포로 표시). 모멘트 팔이 `shift` 만큼 바뀌므로 그 묶음 반력의 모멘트 차 ≤ |R_q|·shift(시험 V-0252-14).

### 3.4 형상 제외 · 참고용 (D-0.25.2-11)

- **제외**(지금 규칙에 못 붙임 수를 넣음): 잡힌 노드 0 이거나 `n_miss/n_clusters > tie_miss_frac_max` → `JIG_GRID_TIE_MISS`(코드 유지). 강제로 붙은 묶음은 miss 가 아니다. 개정 1: 거리 한도가 없으므로 **기본 설정에서는 체결부를 못 찾았다는 이유로 형상이 빠지지 않는다**(형상 메시가 비었거나 한도·법선 조건을 준 경우만).
- **참고용**(D-0.25.2-25): `(n_force + n_miss)/n_clusters > tie_miss_frac_max` **또는 먼 강제 `n_far ≥ 1`** → `map.tie.ref = true`. 즉 지금까지라면 순위에서 빠졌을 형상, 그리고 한 곳이라도 멀리 옮겨 붙인 형상이 참고용. 순위 값·정렬은 그대로 계산하고 표시만 붙인다(§4.1·§7.2).
- #96 형상에 적용하면(128/228 = 56 %): 128곳이 모두 가장 가까운 면에 붙고 d001 이 순위에 들어가며 **참고용**. 경고에 128/228·거리 분포(가장 가까운·중앙·가장 먼 거리, 10 mm 넘는 곳 수)가 나온다.

### 3.5 경고 (문구 원본 `resources/doe_messages.json`)

| 코드 | 수준 | 어디 | 문구 |
|---|---|---|---|
| `JIG_GRID_TIE_FORCED` | 경고(형상) | 형상 result 경고 · 스터디 요약(최악 형상 1건) | "형상 {did}: Case 지그 체결부 {n_force}/{n_clusters}곳({pct} %)이 형상의 체결부 자리가 아니어서 가장 가까운 면에 강제로 붙였습니다(옮긴 거리 최소 {dmin} · 중앙 {dmed} · 최대 {dmax} mm, {far} mm 넘는 곳 {n_far}곳 · 면적비 {lo}~{hi}{kscale}){ref}" — `{kscale}` = " · 스프링 배율 a~b"(스프링 방식 있을 때), `{ref}` = " — 지그 순위는 참고용입니다" |
| `JIG_GRID_TIE_FAR` | 경고(형상) | 같음(`n_far ≥ 1` 일 때) | "형상 {did}: 체결부 {n_far}곳은 {far} mm 넘게 떨어진 면에 붙였습니다(먼 순 상위 5곳: {list} mm) — 다른 모델이거나 좌표가 어긋났을 수 있습니다. 3D 지그 보기의 선 길이를 확인하세요" |
| `JIG_GRID_TIE_UNPLACED` | 경고(형상) | 같음 | "형상 {did}: 체결부 {n_miss}/{n_clusters}곳은 붙일 면이 없어 뺐습니다{limit}{fail}" — `{limit}` = "(거리 한도 {dmax} mm)"(한도를 준 설정만) — `{fail}` = " — 이 형상은 격자 지그 순위에서 빠집니다" |
| `JIG_GRID_TIE_HINT` | 정보(스터디) | 참고용 형상이 1개 이상일 때 1건 | "체결부를 많이 못 찾은 형상은 Case 와 다른 모델이거나, 좌표가 어긋났거나, STEP 이 중립면이 아닐 수 있습니다 — 3D 지그 보기에서 위치를 확인하세요" |

- 기존 `JIG_GRID_TIE_MISS`·`JIG_GRID_TIE_SNAP*`·`JIG_GRID_AREA_RATIO` 문구·조건은 옛 스냅샷에서 그대로. 새 스냅샷에서 못 붙임은 `JIG_GRID_TIE_UNPLACED` 로 낸다(`TIE_MISS` 문구 "구멍·와셔 면이 없거나 법선이 다름" 은 강제 단계 뒤에는 맞지 않음).
- `JIG_GRID_AREA_RATIO`(정보)는 강제 묶음도 포함해 지금 식 그대로.

### 3.6 설정 · 스냅샷 · 해시 (D-0.25.2-12)

- 새 블록 `bead_doe.rank.jig_grid.tie_force{enabled true, max_dist_mm null, normal_deg 90.0}` — 4곳 같은 이름(코어 `esl/doe/__init__.py` DEFAULTS · pydantic `BeadDoeRankJigGridCfg` 안 새 `BeadDoeRankJigGridForceCfg` · yaml 2개). 범위: `max_dist_mm` null(= 한도 없음, 기본) 또는 > 0, `normal_deg` (0, 90].
- **거리 한도 키는 남기되 기본 없음**(개정 1, D-0.25.2-24): 사용자 답 "거리 무관 무조건" = 기본 동작. 키를 남기는 근거: 현장에서 "너무 먼 곳은 붙이지 말라" 가 필요해지면 코드 변경 없이 관리자가 값을 줄 수 있고, 스냅샷에 null 이 남아 그 스터디가 한도 없이 계산됐음이 기록됨.
- 새 키 `bead_doe.rank.jig_grid.tie_force_far_warn_mm` 10.0(> 0) — **먼 강제 표시 임계**(붙이는 규칙과 무관 — 경고·참고용·3D 색만). `grid_map.HASH_EXCLUDE` 에 추가(해시 밖 — 블록 최상위 키라 기존 규칙 그대로).
- **기본 켬**(새 스터디). 근거: 사용자 의도 = 강제 부여 + 경고 참조.
- 새 스터디 스냅샷 `doe.rank.jig_grid.tie_force` 로 고정(백엔드 `rank_snapshot` 이 블록을 통째로 복사 — 코드 변경 없음, 값만 따라옴). **해시 안**(계산 결과를 바꿈 — `hash_view` 가 스냅샷 원본 키를 그대로 읽음).
- **옛 스냅샷(블록에 `tie_force` 키 없음) = 끔**: `_jg_cfg` 가 이 키만은 DEFAULTS 에서 채우지 않는다(코드 상수 `grid_map.LEGACY_ABSENT = {"tie_force": None}` 한 곳 — `jig_bc.LEGACY_ABSENT` 와 같은 관례). → 옛 스터디 이어하기·다시 만들기·3D 재생성 결과 바이트 불변, 해시 불변.
- 복제 = 지금 스냅샷 규칙 그대로(새로 만드는 스터디 → 현재 설정으로 `tie_force` 가 들어감). 옛 스터디를 복제하면 강제 부여가 켜진다(안내: §7.2 복제 안내 문구에 덧붙이지 않음 — 결과 경고로 드러남).

### 3.7 계획 표 — 지그 종류 × 모드 × 방식 (공통)

지그 종류는 `transfer_plan.jig_kind`(한 곳)가 정한다. 새 열·새 분기 없음 — 강제 부여는 "격자 잡기(`capture`)를 쓰는 곳" 에만 있고, 그건 `jig_fix grid` 계획뿐이다.

| 지그 종류 | 모드(계획) | tie 노드 출처 | 강제 변위 | 스프링 | 고정 | 강제 부여 |
|---|---|---|---|---|---|---|
| base | ①②③ 같은 메시(`case_once`·`bmesh_once`·`step_once`) · Case ③ 지그 | Case tie 노드 그대로 | ○ | ○ | ○(켠 경우) | **해당 없음**(놓칠 수 없음) |
| grid | ④ 형상 직접 비교(`compare_per_shape`) | 형상마다 `capture` | ○ | ○ | ○(켠 경우) | **적용**(3방식 같은 노드 집합) |
| grid | 옛 ③ 안마다 다시 메시(`step_per_design`) | 안마다 `capture` | ○ | ○ | ○(켠 경우) | **적용** |
| none | 옛 스냅샷·설정 끔 | – | – | – | – | – |

- `capture` 는 형상 1개에 1번, 세 방식이 같은 잡힌 노드 집합을 쓴다(지금 구조) → 강제 노드도 방식 공통.
- d000(기준): ④ 기준이 Case 메시면 항등(강제 0). 기준이 STEP 이면 기준에도 같은 규칙 — 기준이 참고용이면 스터디 경고 `JIG_GRID_TIE_FORCED`(did = d000)로 드러난다.

---

## 4. C — #96 표시 개선 (DS)

### 4.1 결과 개수 줄 (D-0.25.2-14)

- 코어 공용 함수 `rank.count_items(R) -> [{key, label, n}]`: `n_ok` + `n_skipped`·`n_failed` 의 **0 이 아닌 모든 키** + `n_ref`(참고용 형상 수 — > 0 일 때만). 라벨 표 `rank.COUNT_LABELS` 한 곳:

| 키 | 라벨 | | 키 | 라벨 |
|---|---|---|---|---|
| `mesh` | 메시 | | `jig`·`jd`·`js` | 지그 매핑 제외 |
| `size` | 크기/정렬 | | `bf` | 경계력 없음 |
| `solve` | 해석 | | `fi` | 내력 없음 |
| `morph` | 모핑 | | `sm` | 강성 지표 없음 |
| `collision`·`fixed`·`geom` | 스킵(충돌·고정·형상) | | `ref` | 참고용 |

- 보고서 줄(`report_doe.py:525`): 지금 줄 뒤에 0 이 아닌 나머지 키를 덧붙임 — 예 "성공 0 · 실패 메시 0·크기/정렬 0·해석 0 **· 지그 매핑 제외 1**". 덧붙일 키가 없으면 지금 줄과 글자까지 같다.
- 결과에 `n_ref` 키는 > 0 일 때만 생긴다(`rank_views` 보기에도 같은 규칙).
- 순위 행: 참고용 형상에 `jig_ref: true`(참일 때만 키).

### 4.2 지그 순위가 비어도 다른 출처 순위 보이기 (D-0.25.2-15)

- 화면 기본 탭 규칙(`doeTabs.tabState.def`): 주 출처 탭의 순위가 0 행이고 다른 탭 중 순위가 1 행 이상인 것이 있으면 **출처 표 순서에서 처음 그런 탭**을 기본으로. 그 밖은 지금 그대로.
- 빈 탭 본문(지금 "실행 가능한 안이 없어 순위를 만들지 못했습니다." 자리, 같은 1줄): "이 하중 출처에는 순위에 든 형상이 없습니다(지그 매핑 제외 1) — [전 노드] 탭에는 순위가 있습니다". 대괄호 = 그 탭으로 가는 링크.
- 보고서 "3. 순위": 주 순위가 비고 `rank_views` 에 순위가 있는 보기가 있으면, 빈 문구 아래에 **출처 표 순서 첫 보기**의 순위 표 1개 + 제목 "다른 하중 출처 순위: {출처 이름}". 그 밖은 지금 그대로.
- 코어 `rank_views` 생성 조건은 바꾸지 않는다(감사: 전 노드 보기는 이미 만들어짐 — 시험 V-0252-22 가 #96 조건에서 확인).

### 4.3 3D 에 놓친/강제 체결부 표시 (v0.25.1 공용 뷰어 위 — D-0.25.2-16)

- 자료: 형상별 `run/designs/<did>/jig_grid.json` `map.tie` 에 새 키(§6.3) `force{…}` 와 `marks[{q, via: "force"|"miss", x: [3](Case 체결부 중심 — 형상 전역 좌표), dist, n, far}]`(강제·못 붙임 묶음만, 최대 `view3d.jig_force_marks_max` 512개 — 넘으면 dist 큰 순, `marks_truncated: true`).
- 지그 응답 3D(스터디 설계 비교의 지그 탭 — `View3DCard`) manifest: 지지 표식 행에 선택 키 `via: "force"`(강제 노드만), manifest 에 선택 키 `tie_marks`(위 `marks` 그대로).
- 그리기(공용 `view3d/supportMarks.ts` 표에 행 추가 — 새 컴포넌트 없음):

| 표식 | 모양 | 범례 문구 |
|---|---|---|
| 강제로 붙인 지지 | 그 방식 표식(스프링·막대) 그대로 + **자홍 테두리** | "자홍 테두리 = 체결부가 아닌 곳에 강제로 붙인 지지" |
| Case 체결부 자리(강제) | 자홍 빈 고리 + 붙인 곳까지 가는 선(먼 강제 = **빨강 굵은 선** — 거리 한도가 없어 선이 길 수 있음, 선 길이 = 옮긴 거리 그대로) | "빈 고리 = Case 체결부 자리(선 = 옮겨 붙인 거리 · 빨강 = {far} mm 넘음)" |
| 못 붙인 체결부 | 빨강 ✕ | "✕ = 붙일 면이 없어 뺀 체결부" |

- 켬·끔: 기존 지지 표식 층(`지지`)에 딸림 — 새 버튼·새 줄 없음. 고리·✕ 위에 마우스 = "체결부 q{n} · 거리 {d} mm".
- 3D 가 없는 형상(순위에서 빠져 3D 비교 대상이 아님 — #96 d001): 형상 표(②·결과의 형상 행) 경고 칸 툴팁에 `JIG_GRID_TIE_UNPLACED`·`TIE_FORCED` 문구. 빠진 형상의 3D 를 따로 만드는 것은 비범위(R-JF-2).
- 색(자홍·빨강)은 표식 색 — v0.25.1 색 지도(`resources/colormaps.json`, 연속값 전용) 대상이 아님. 표식 색은 `supportMarks.ts` 표 한 곳.

### 4.4 판 앞뒷면 두 장 경고 (D-0.25.2-17)

- **메시로 감지**(STEP 커널 불필요 — STEP·메시 입력 공통): 새 독립 순수 모듈 `esl/mesh/double_sheet.py`(numpy · scipy.spatial 만, `esl.doe` 금지, IO·설정 해석 없음) `detect(mesh, t, *, gap_min_t, gap_max_t, normal_deg, sample_max) -> {frac, gap_mm, n_sample}`.
- 규칙: 요소를 인덱스 등간격으로 최대 `sample_max` 개 뽑음(결정적). 표본 요소(중심 c, 단위 법선 n, 변 길이 h)에 **짝**이 있다 = 다른 요소 중 ① 법선 평행 |n·n′| ≥ cos(`normal_deg`) ② 법선 방향 간격 g = |(c′−c)·n| ∈ [`gap_min_t`·t, `gap_max_t`·t] ③ 면내 어긋남 ≤ h 인 것이 있음. `frac` = 짝 있는 표본 비율, `gap_mm` = 간격 중앙값.
- 판정: `frac ≥ frac_warn` → 형상 경고 `SHAPE_DOUBLE_SHEET`(형상은 **계속 실행** — 경고만): "{name}: 판 앞뒷면 표면이 둘 다 들어 있는 것 같습니다(마주 보는 면 {pct} % · 간격 {gap} mm ≈ 두께 {t} mm 의 {r}배) — 두께가 두 번 계산되고 지그 체결부를 못 찾을 수 있습니다. 중립면 한 장으로 올려 주세요." 리브·헤밍처럼 일부만 겹친 형상은 frac 이 작아 안 걸린다.
- 호출: `_cmp_mesh_notes`(④ BD_MESH0, 형상 source = step·mesh — Case 메시 기준 형상 제외). 형상 행에 `double_sheet{frac, gap_mm}` 은 **경고가 날 때만** 씀(안 걸린 형상의 `prep/compare.json` 바이트 불변).
- 설정 `bead_doe.compare.double_sheet{enabled true, gap_min_t 0.3, gap_max_t 3.0, normal_deg 15.0, frac_warn 0.5, sample_max 2000}` 4곳 같은 이름. **해시·스냅샷 밖**(경고만 — 계산 결과 불변). 끄면 호출 0.
- 화면: ④ 형상 표 코드 칸·경고 목록(기존 자리). 새 요소 없음.

---

## 5. 공용 모듈 · 계획 표 · 독립성 (AGENTS.md D-0.20.0-CODE)

| 모듈 | 새/변경 | 쓰는 곳 | import 제한 |
|---|---|---|---|
| `esl/mech/tstar.py` `point_at` | 추가 | 코어 `_select_frame`·`frame_point`, 백엔드(코어 어댑터) | 지금 그대로(numpy) |
| ★`esl/io/frame_fill.py`(`DECIDE`·`merge`·기록) | 새 | 워커(채움), 백엔드(가능 판정), 코어 ESL 단계(기록 읽기) | numpy·`esl.errors`·`esl.io.results_csv`·`esl.io.backup` |
| `esl/mech/grid_map.py` `CAPTURE_STAGES`·`capture(force=)` | 변경 | ④·옛 ③ 평가·3D·다시 만들기(공용 실행기 `run_shape` 1곳) | 지금 그대로(`esl.doe` 금지) |
| `esl/doe/rank.py` `count_items`·`COUNT_LABELS` | 추가 | 보고서·결과 문서(화면은 API 로 받음) | 지금 그대로 |
| ★`esl/mesh/double_sheet.py` | 새 | ④ 형상 검사(뒤에 다른 모드가 써도 그대로) | numpy·scipy.spatial |
| `frontend/src/view3d/supportMarks.ts` 표 | 행 추가 | 모든 `View3DCard`(공용) | – |

- 모드 차이는 표로: 잡기 단계 = `CAPTURE_STAGES`(§3.1), 지그 종류 = `transfer_plan.jig_kind`(§3.7 — 변경 없음), 채움 가능 = `frame_fill.DECIDE`(§2.4), 개수 라벨 = `COUNT_LABELS`(§4.1). 호출부(`stages.py`·`executor.py`·`cases.py`)는 표의 결과만 읽고 시나리오·입력 종류 이름으로 분기하지 않는다.
- 값 하드코딩 금지: 새 숫자는 전부 §8.1 설정 키. 코드 상수는 형식 이름·`LEGACY_ABSENT`·`VIA_FORCE` 뿐.
- 진단·결과 스키마는 모드 공통 1개(`jig_grid.json map.tie` — ④·옛 ③ 같음).

---

## 6. 데이터 · API 계약

### 6.1 Case t* (고정 필드명 — `schemas.py` ↔ `api/types.ts`, `check:api`)

`GET /cases/{id}/tstar` — 추가 키(기존 키 불변):

| 키 | 형 | 뜻 |
|---|---|---|
| `frames` | `[{frame_index, time}]` | 고를 수 있는 프레임 전부(`history.npz` 순서) |
| `frames_have` | `int[]` | 변위·변형률이 있는 프레임(D ∪ 채운 프레임) |
| `fill` | `{available: bool, code: str\|null, text: str\|null}` | D 밖 프레임 채움 가능 여부(`frame_fill.DECIDE` 결과 — 행 2~5 면 false + 문구) |
| `metrics[m].history.frame_index` | `int[]` | 곡선 점의 프레임 번호(지금은 time·value 만) |

`PUT /cases/{id}/tstar` — 요청 형식 불변 `{version, metric, frame_index}`. 서버 동작:

1. 후보 프레임이면 지금 경로 그대로(저장 값·응답 바이트 불변).
2. 후보가 아니고 `frames` 에 있으면: `frames_have` 에 있거나 `fill.available` → 저장. 아니면 422 `FRAME_NOT_EXTRACTABLE`(`text` = 판정 문구).
3. `frames` 에 없으면 422 `FRAME_NOT_FOUND`("h3d 에 없는 프레임입니다").
4. 저장 값 `cases.tstar` = 지금 키(`metric, frame_index, time, elem_id, value, source: "user", support_auto`) + **`manual{auto_frame, auto_time, auto_value, ratio, rel, in_D, have}`**(직접 고른 t* 일 때만). DB 스키마 변경 없음(JSON 칸).

ESL 작업 생성(`job_params.esl_solve_params`): 프레임이 `disp.npz` 에 없어도 `tstar.manual` 이 있고 `fill.available` 이면 통과(지금은 409 `PREREQUISITE_MISSING: disp_frame`). 작업 결과에 `frame_fill{status, frame, seconds, cause?, detail?}`(채움을 시도했을 때만). ESL step 로그 문구는 워커 `frame_fill.LOG` 한 곳(시작·대기·진행·완료·실패 — 경계력 보충 로그와 같은 모양).

오류 코드(화면 문구 `api/client.ts`): `FRAME_NOT_EXTRACTABLE` · `FRAME_NOT_FOUND` · `TSTAR_FRAME_FILL_FAILED`("직접 고른 시점을 h3d 에서 읽지 못했습니다: {detail} — 다시 실행하거나 ② 에서 다른 시점을 고르세요").

### 6.2 코어 파일

| 파일 | 변경 |
|---|---|
| `01_extract/disp.npz`·`strain_frames.npz` | 채움 때 끝에 프레임 추가(기존 행 불변) |
| `01_extract/frames.json` | 새 키 `frames_fill`(채웠을 때만) |
| `01_extract/frame_fill.json` | 새 파일(시도했을 때만) |
| `02_tstar/tstar.json` | 형식 불변. `--frame` 이 비후보면 `selected` 에 `manual` |
| `04_esl/esl_summary.json` | `tstar_manual`(직접 고른 t* 일 때만) |
| `07_report/report.html` | t* 줄 뒤 1줄(같은 조건) |

### 6.3 스터디 결과

| 곳 | 새 키(조건) |
|---|---|
| `run/designs/<did>/jig_grid.json` `map.tie` | `n_force`, `n_far`, `force{dist_min_mm, dist_med_mm, dist_max_mm, shift_max_mm, far_mm, limit_mm(null = 없음)}`, `ref`, `marks[]`, `marks_truncated?` — **스냅샷에 `tie_force` 가 있을 때만**. `n_miss` = 못 붙임 수(뜻 유지). `RUN_SCHEMA` 값 불변(키 추가만) |
| `result.json` `jig.grid` | `n_forced_shapes`, `n_ref_shapes`(같은 조건) |
| 순위 행 · `rank_views` 행 | `jig_ref: true`(참일 때만) |
| 결과·보기 최상위 | `n_ref`(> 0 일 때만), `counts[{key, label, n}]`(= `count_items` — 새 결과만) |
| `prep/compare.json` 형상 행 | `double_sheet{frac, gap_mm}`(경고 날 때만) |
| 3D manifest | `supports[].via?`, `tie_marks?`(§4.3) |
| API `DoeResultOut`·`View3dOut` | 위 키를 선택 필드로 통과(`schemas.py` ↔ `types.ts`) |

---

## 7. 화면 계약 (문구 한국어 · 필수 요소만)

### 7.1 ② t*·지지점 (`Stage2.tsx`·`MaxHoldChart.tsx`)

**기본 조작 = 곡선 클릭**(D-0.25.2-5). 근거: 원문 첫째 안이고, 프레임 시각을 눈으로 보고 고르는 것이 숫자 입력보다 빠름. 직접 입력은 후보 표 안 1행.

- 곡선: 실행 권한이 있으면 그림 영역 클릭 → **x 가 가장 가까운 프레임**(시각 차 최소, 동률 = 앞 프레임)으로 선택. 마우스를 올리면 세로 안내선 + 그림 안 왼쪽 위 글자 "프레임 {f} · {t} s · {값}"(그림 안이라 높이 변화 없음). 후보 점 클릭 = 그 후보(지금 표 선택과 같음). 권한 없으면 지금처럼 보기만.
- t* 세로선: `frames` 의 시각으로 그린다(지금의 `time[selectedFrame]` 가정 제거 — `frame_stride > 1` 에서도 맞음).
- 후보 표 맨 아래 **1행 "직접"**(표의 스크롤 영역 안): 라디오 + 입력 1칸(자리 표시 "프레임 번호 또는 시간(s)") + 프레임·시간·요소("–")·값·변위 칸.
  - 입력 규칙: 정수만 = 프레임 번호, 소수점이 있거나 끝에 `s` = 시간 → 가장 가까운 프레임. Enter 또는 칸을 벗어나면 적용. 범위 밖 = 칸 아래가 아니라 칸 `title` + 빨간 테두리("h3d 에 없는 프레임").
  - 곡선을 클릭하면 이 행이 선택되고 칸에 프레임 번호가 들어간다(두 조작이 같은 상태).
  - 변위 칸: `있음` | `ESL 때 읽음`(D 밖·채움 가능 — title "③ ESL 실행 때 이 프레임을 h3d 에서 한 번 읽습니다(몇 분)") | `불가`(title = `fill.text`, 라디오 비활성).
- [t* 확정] 비활성 사유에 추가: "이 시점은 고를 수 없습니다 — {fill.text}".
- "현재 t*" 줄(지금 1줄 그대로, 넘치면 말줄임 + title): 직접 고른 t* 면 끝의 "사용자 선택" 을 "**직접 고름 · 자동 대비 {pct} %**" 로, `ratio < manual_ratio_warn` 이면 경고색.
- hotspot 카드 제목은 지금 그대로(자동 t* 기준 표). 직접 고른 프레임의 hotspot 은 ③ ESL 뒤 ④ 에 나온다 — 카드 머리 title 에 한 줄 추가("직접 고른 시점의 hotspot 은 ESL 뒤 ④ 검증에 표시").
- 새 버튼 0, 새 카드 0, 새 줄 0(표 1행은 스크롤 안). **2560×1440·1920×1080 에서 ② 화면 높이 증가 0**(V-0252-28).

### 7.2 강성 스터디 결과 (`pages/doe/**`)

- 결과 카드 제목(지금 "② 결과 · OK n개 형상"): 뒤에 0 이 아닌 제외·참고 개수 — "② 결과 · OK 0개 형상 · 지그 매핑 제외 1" / "… OK 1개 형상 · 참고용 1". 한 줄, 넘치면 말줄임 + title.
- 빈 탭 안내·기본 탭 = §4.2.
- 순위표: 참고용 형상의 이름 옆 회색 꼬리표 "참고"(title = `JIG_GRID_TIE_FORCED` 문구). 정렬·순위 번호 불변. 지그 출처 탭에서만 보인다(전 노드·경계력·내력 탭은 지그 매핑과 무관).
- 경고 목록: §3.5 코드는 `JIG_GRID_` 접두 → 기존 규칙으로 지그 탭에 묶임(`warnTab`).
- 3D 표식·범례 = §4.3(지지 층에 딸림).
- **2560·1920 높이 증가 0**: 새 줄 없음(제목 뒤 글자·꼬리표·기존 빈 문구 자리·범례 항목).

### 7.3 ④ 형상 표

- `SHAPE_DOUBLE_SHEET` 는 기존 코드 칸·경고 목록에. 새 요소 없음.

---

## 8. 설정 · 해시 · 하위 호환

### 8.1 새 설정 (전부 여기 — 4곳 같은 이름·값)

| 키 | 기본 | 해시 | 뜻 |
|---|---|---|---|
| `tstar.manual_ratio_warn`(코어 설정) | 0.5 | 밖 | 직접 고른 t* 경고 임계 |
| `altair.frame_fill_timeout_s` | 1800 | – | 채움 hw 시간 한도 |
| `altair.frame_fill_wait_s` | 600 | – | hw 동시 실행 한도 대기 |
| `bead_doe.rank.jig_grid.tie_force.enabled` | true | **안**(스냅샷) | 강제 부여 |
| `…tie_force.max_dist_mm` | **null** | 안 | 강제 거리 한도 — null = 없음(사용자 결정), 관리자 선택 |
| `bead_doe.rank.jig_grid.tie_force_far_warn_mm` | 10.0 | 밖 | 먼 강제 표시 임계(경고·참고용·3D) |
| `…tie_force.normal_deg` | 90.0 | 안 | 강제 단계 법선 조건(90 = 없음) |
| `bead_doe.view3d.jig_force_marks_max` | 512 | 밖 | 3D 표식 상한 |
| `bead_doe.compare.double_sheet.{enabled, gap_min_t, gap_max_t, normal_deg, frac_warn, sample_max}` | true, 0.3, 3.0, 15.0, 0.5, 2000 | 밖 | 두 장 경고 |

### 8.2 하위 호환 (바이트 불변 목록)

- **A**: 자동 t*·후보 선택 경로의 `tstar.json`·`cases.tstar`·`04_esl/**`·`05_val/**`·`06_export/**`·보고서 = 불변(같은 입력). 채우지 않은 Case 의 `01_extract/**` 불변. TCL 은 `fr_only` 없으면 출력 불변. 옛 Case(v0.25.1 이전 추출)도 그대로 열리고 직접 선택 가능(`history.npz` 만 있으면 됨 — 형식 변경 없음). DB migration 없음.
- **B**: `tie_force` 키 없는 스냅샷(= v0.25.1 까지의 모든 스터디) → `capture(force=None)` = 지금 코드 경로, `jig_grid.json`·`result.json`·`ranking.csv`·`per_esl.json`·사이드카·3D·보고서 불변, 이어하기 해시 불변. 강제 묶음이 0 인 새 스터디 형상: 계산 값은 옛 결과와 같고(`map.tie` 에 `n_force: 0` 등 키만 추가).
- **C**: 보고서 줄·화면 제목은 덧붙일 개수가 0 이면 지금과 같은 글자. `count_items`·`counts` 는 새 결과에만. 옛 결과(키 없음) 화면 = `n_failed` 로 같은 표시를 계산(프런트 `COUNT_LABELS` 거울 — API `counts` 없을 때만). `double_sheet` 는 경고 날 때만 형상 행에 씀.
- 저장된 옛 보고서·옛 3D 는 다시 만들지 않는다.

---

## 9. 성능 (추정 — 구현 때 실측해 §15 에)

| 항목 | 추정 |
|---|---|
| 프레임 채움 | 3~6 분/프레임(hw 1회), 한 번만. ESL 단계 앞에 붙음 |
| `GET /tstar` `frames` | 프레임 수 × 2 숫자(수백 개) — 무시 가능 |
| 강제 단계 | 못 잡은 묶음마다 KD 트리 최근접 질의(k 배증 — 한도 없음이어도 형상 전체 정렬 안 함) — 형상당 < 1 s(228 묶음) |
| 두 장 감지 | 표본 2000 × 공 질의 — 형상당 < 1 s |
| 3D 표식 | ≤ 512 개 선·고리 — 무시 가능 |

---

## 10. 시험 (V-0252-n)

### 10.1 A 코어·물리

| # | 시험 |
|---|---|
| 1 | `point_at`: 합성 계열에서 최대 요소·값·동률(작은 인덱스)·제외 요소 |
| 2 | **바이트 불변**: 합성 Case 를 자동 t*·후보 선택으로 끝까지 → `02_tstar`·`04_esl`·`05_val`·`06_export` 파일이 구현 직전 헤드 골든과 같음 |
| 3 | `frame_fill.merge`: 끝에 덧붙음·기존 행 위치/값 불변·`frames_D` 불변·백업 남음·두 번 병합 = 한 번(멱등)·프레임 수/시각 다르면 `FRAME_FILL_MISMATCH` 에 쓰기 0 |
| 4 | **임의 프레임 ESL 재현(물리)**: 합성 Case(알려진 변위 이력)에서 D 밖 프레임 f 를 채워 ESL → ① K·u_rel(f) = F_eq 잔차 상대 ≤ 1e-9 ② F_eq 로 3-2-1 전체 풀이 → u_rel(f) 재현(변위 4지표 통과, MAC ≥ 0.999) ③ 힘·모멘트 평형 오차 ≤ `equilibrium_warn_rel` |
| 5 | **채움 = 처음부터 추출과 같음**: 같은 합성 결과를 `top_n` 을 키워 f 가 D 에 들게 추출한 Case 의 `04_esl/f_eq.npz`·`u_rel.npz` 배열 == 채움 경로 배열(정확 일치) |
| 6 | D 안 비후보 프레임을 고르면 채움 0, ESL 결과 = 그 프레임 변위의 ESL(시험 5 와 같은 대조) |
| 7 | 경고: `ratio`·`rel` 계산, `TSTAR_MANUAL`·`_LOW`·`_AFTER`·`_NO_RISING` 조건(상승 요소 0 인 프레임에서 hotspot 0·ESL 성공·④ 판정 가능) |
| 8 | 누적 씬 합성: 직접 고른 프레임의 값 = 누적 계열, ESL = 이번 낙하분(자동과 같은 규칙) |
| 9 | `DECIDE` 표: 행 1~6 각각(순수 — `Facts` 조합) · TCL 정적 확인(`fr_only` 없을 때 분기 불변 — 문자열 검사, hw 실행 없음) |

### 10.2 B 코어·물리

| # | 시험 |
|---|---|
| 10 | **바이트 불변**: `tie_force` 키 없는 스냅샷 ④ 스터디(기존 골든) → `jig_grid.json`·`result.json`·`ranking.csv`·사이드카·해시 같음 |
| 11 | 항등: 형상 = A 메시, 강제 켬 → `n_force` 0, 값이 강제 끔과 같음 |
| 12 | 강제 단계 규칙: 체결부 자리에 구멍이 없는 합성 판 → via force, 고른 노드 = 거리순·면적 합 ≥ A_q 첫 노드까지, `dist`·`shift`·면적비 기록, 결정적(두 번 실행 같은 노드) |
| 13 | **스프링 강성 합 보존(물리)**: 강제 묶음마다 Σk = K_q(상대 1e-12), 전 묶음 합 = Case 스프링 합 |
| 14 | **합력·모멘트 보존(물리)**: 합성 평판 + 체결부 4곳, 형상 = 체결부 면을 δ(3·8 mm) 옮긴 판. 강제 켬 → ① 전체 평형: 지지 반력 합 + 하중 합 = 0, 모멘트 합 = 0(상대 1e-9) ② 옮기지 않은 형상 대비 반력 합력 차 ≤ 1 %(초안 — 측정 후 확정) ③ 판 중심 기준 반력 모멘트 차 ≤ Σ|R_q|·δ_q + 1 % ④ C_mix 차를 표로 기록(δ 3·8 mm × 강제 변위·스프링) |
| 15 | **거리 무관**(개정 1): 체결부 면을 50·200 mm 옮긴 형상, 기본 설정(`max_dist_mm` null) → 전부 force(miss 0), 형상이 순위에 들어감, `n_far`·`dist_min/med/max`·`JIG_GRID_TIE_FAR` 먼 순 목록. 관리자 한도 `max_dist_mm 20` 스냅샷 → 그 밖은 miss·`JIG_GRID_TIE_UNPLACED`(한도 문구)·비율 > `tie_miss_frac_max` 면 형상 제외(`JIG_GRID_TIE_MISS` 코드) |
| 16 | 참고용 판정: (force + miss)/n > 0.1 **또는 n_far ≥ 1** → `ref` 참·행 `jig_ref`·`n_ref`·경고 `{ref}` 꼬리, 둘 다 아니면 꼬리 없음. `tie_force_far_warn_mm` 을 바꿔도 해시·계산 값 불변(표시만) |
| 17 | 설정: `tie_force` 범위 밖 = `CONFIG_INVALID`, 4곳 거울 같은 값, 해시 = 키 있으면 포함·`max_dist_mm`(null ↔ 값) 바꾸면 해시 바뀜, null 허용·0 이하 거부 |
| 18 | 옛 ③(`step_per_design`)에서도 같은 함수·같은 키(계획 표 §3.7 두 grid 행) |

### 10.3 C

| # | 시험 |
|---|---|
| 19 | `count_items`: #96 꼴(`n_failed {"jd": 1}`) → "지그 매핑 제외 1" 포함. 덧붙일 키 없으면 보고서 줄 = 지금 글자(골든) |
| 20 | 보고서: 주 순위 비고 전 노드 보기 있음 → "다른 하중 출처 순위: 전 노드" 표 |
| 21 | `double_sheet.detect`: 한 장 판 frac ≈ 0 · 간격 t 인 두 장 frac ≥ 0.9, gap ≈ t · 리브 있는 한 장 frac < 0.5 · 간격 5t 두 장 = 안 걸림 · 결정적 |
| 22 | #96 재현 합성(④, 형상이 체결부 과반 놓침, 강제 **끔** 스냅샷): 주 순위 0·`n_failed.jd` 1·`rank_views.full` 순위 1 행 |
| 23 | 같은 합성, 강제 **켬**: 형상이 지그 순위에 들어가고 참고용, `marks` 에 강제 묶음 위치 |

### 10.4 백엔드·워커

| # | 시험 |
|---|---|
| 24 | `GET /tstar` 새 키(`frames`·`frames_have`·`fill`·`history.frame_index`), 옛 Case 산출물에서도 채워짐 |
| 25 | `PUT /tstar`: 후보 = 저장 값 불변(골든) · D 안 비후보 = `manual` 저장 · D 밖 + 가능 = 저장 · D 밖 + 불가 = 422 `FRAME_NOT_EXTRACTABLE` · 없는 프레임 = 422 `FRAME_NOT_FOUND` · 권한·버전 충돌 규칙 그대로 |
| 26 | ESL 작업: D 밖 프레임 → 가짜 hw(시험용 `fr_only` 출력)로 채움 → 코어 ESL 성공·결과 `frame_fill.status ok`·두 번째 실행 hw 0 · 채움 실패 → 단계 실패 `TSTAR_FRAME_FILL_FAILED` · 재추출 뒤 다시 채움 · hw 세마포어 반납 |
| 27 | 스터디 API: `counts`·`n_ref`·`jig_ref`·`tie_marks` 통과, 설정 거울(`tie_force`·`double_sheet`·`frame_fill_*`) = 코어 DEFAULTS, OpenAPI 스냅샷 |

### 10.5 프런트·e2e

| # | 시험 |
|---|---|
| 28 | ②: 곡선 클릭 → 가장 가까운 프레임 선택·세로선·"직접" 행 값 · 입력 "12"(프레임)·"0.012"·"12s"(시간) · 변위 칸 3가지 · 불가 프레임 = 확정 비활성 + 사유 · 권한 없으면 클릭 무시 · **2560×1440·1920×1080 화면 높이 = 구현 전과 같음** |
| 29 | ②: "현재 t*" 줄 문구(직접 고름 · 자동 대비 %)·경고색, `frame_stride 2` 목 자료에서 세로선 위치 |
| 30 | 스터디: 제목 개수 글자 · 빈 주 탭 → 기본 탭 = 순위 있는 탭 · 빈 탭 안내 + 링크 · "참고" 꼬리표 · 옛 결과(`counts` 없음) 같은 표시 · 높이 증가 0 |
| 31 | 3D: 강제 지지 자홍 테두리·빈 고리 + 선·✕·범례 항목·툴팁, `tie_marks` 없는 옛 manifest = 지금 그림 |
| 32 | e2e: Case ② 곡선 클릭 → 확정 → ③(목 서버 채움) → ④ / 스터디 #96 꼴 결과 화면 |

---

## 11. 구현 분할 (파일 소유 겹침 0 — **전제: v0.25.1 이 `release/v0.25.1` 에 모두 합쳐진 뒤, 그 헤드에서 `release/v0.25.2` 를 다시 맞추고 시작**)

| 묶음 | 모델 | 소유 파일 | 내용 | 시험 |
|---|---|---|---|---|
| **C1 코어** | opus | `esl/pipeline.py` · `esl/cli.py` · `esl/config.py` · `esl/mech/tstar.py` · ★`esl/io/frame_fill.py` · `esl/io/messages.py` · `resources/tcl/esl_h3d_extract.tcl` · `esl/report/case_report.py` · `esl/mech/grid_map.py` · `esl/doe/stages.py` · `esl/doe/rank.py` · `esl/doe/report_doe.py` · `esl/doe/__init__.py` · ★`esl/mesh/double_sheet.py` · `esl/view3d.py` · `resources/doe_messages.json` · `config/esl.example.yaml` · `tests/**` | §2.3~§2.5 코어 · §3 전부 · §4.1·§4.2 보고서·§4.3 자료·§4.4 · §6.2·§6.3 파일. 커밋 순서 A → B → C(각각 불변 시험 2·10 먼저) | 1~23 |
| **B1 백엔드·워커** | sonnet | `backend/esl_platform/**` · `worker/esl_worker/**`(★`frame_fill.py` — 요청 키·hw 실행·평가·`LOG`, `executor.py` 훅, `core_adapter.py`) · `config/esl_platform.example.yaml`·`.prod.example.yaml` · `backend/tests/**` · `worker/tests/**` · OpenAPI 스냅샷 | §6.1 API · ESL 전 채움(§2.4 — 경계력 보충 훅 바로 앞, 같은 세마포어) · §8.1 pydantic 거울 · §6.3 통과 필드 | 24~27 |
| **F1 프런트** | sonnet | `frontend/src/stages/Stage2.tsx` · `components/MaxHoldChart.tsx` · `api/endpoints.ts`·`types.ts`·`client.ts`·`doe.ts` · `pages/doe/**` · `view3d/supportMarks.ts`·`supports.ts` · `mock/**` · `__tests__/**` · `scripts/e2e_*.mjs` | §7 전부 · §4.2 화면 · §4.3 그리기 | 28~32 |

- 접점(이 문서가 원본, 먼저 고정): **C1↔B1** = `frame_fill.DECIDE`·`merge`·`Facts` 시그니처, TCL `fr_only` 요청 키·`done.json`(§2.4), `frame_point` 반환(§2.3), §6.2·§6.3 키. **B1↔F1** = §6.1·§6.3 API 키. C1 은 접점 함수 껍데기(시그니처 + 독스트링)를 첫 커밋으로 올려 B1 이 병행할 수 있게 한다.
- 순서: C1 첫 커밋(접점) → {C1 ∥ B1 ∥ F1(목 자료)} → 통합.
- 겹침 0 확인: `stages.py`·`grid_map.py`·`doe_messages.json` = C1 만, `worker/**`·`backend/**`·`esl_platform*.yaml` = B1 만, `frontend/**` = F1 만. `resources/doe_messages.json` 은 v0.25.1 에서 B1 소유였으나 이번에는 코어 시험이 새 문구를 읽어야 해 C1 소유(B1 읽기만).
- 통합(메인): `VERSION` 0.25.2 · `CHANGELOG.md` · `docs/e2e-checklist.md`(§12) · 사용자 매뉴얼(② 직접 선택 · 강제 부여와 참고용 뜻 · 두 장 경고) · 독립 검증(불변 2·10 + 물리 4·5·13·14 재실행).

---

## 12. 현장 확인표 (E-0252-n — 배포 뒤 `docs/e2e-checklist.md` 로)

| # | 확인 |
|---|---|
| 1 | ② 곡선을 클릭하면 가장 가까운 프레임이 잡히고, 표의 "직접" 행·세로선·프레임 번호가 같이 바뀌는가 |
| 2 | "직접" 칸에 프레임 번호, 시간(0.012 또는 12s)을 넣어도 같은가 |
| 3 | D 밖 프레임을 확정하고 ③ ESL 을 돌리면 로그에 채움 시작·완료가 보이고 ESL 이 끝나는가. **걸린 시간(분)과 `01_extract` 늘어난 크기를 적어 §9 추정과 비교**(실제 HyperView — TCL `fr_only` 는 CI 에서 못 돌림) |
| 4 | 같은 프레임으로 ESL 을 다시 돌리면 hw 를 다시 띄우지 않는가 |
| 5 | 직접 고른 시점의 ④ 변위 검증이 통과하는가. "현재 t*" 줄·보고서에 "자동 대비 %" 가 보이는가 |
| 6 | 자동 t* 로 다시 확정하면 결과가 예전과 같은가(같은 Case 의 예전 F_eq 와 비교) |
| 7 | 덤프 방식·CSV 폴더 Case 에서 D 밖 프레임이 "불가" 와 사유로 보이는가 |
| 8 | 2560×1440·1920×1080 에서 ②·스터디 결과 화면 세로 길이가 늘지 않았는가 |
| 9 | **#96 Case 를 복제해 다시 실행**: ④ 형상 표에 `75QN80H_chassis_rear_PV_ISTA` 가 "판 앞뒷면 두 장" 경고를 받는가(마주 보는 면 %·간격 mm 를 적음 — 원인 후보 ⓐ 확인) |
| 10 | 같은 스터디: d001 이 지그 탭 순위에 "참고" 로 들어오는가, 경고에 강제 몇 곳/228·옮긴 거리 최소·중앙·최대·10 mm 넘는 곳 수·면적비가 나오는가(값을 적음) |
| 11 | 3D 지그 보기에서 강제 지지(자홍 테두리)·Case 체결부 자리(빈 고리 + 선)가 보이고, 선 길이로 "위치가 통째로 어긋났는지(전부 같은 방향·같은 길이 = 좌표 어긋남 ⓒ) / 몇 곳만 다른지(다른 모델 ⓑ)" 를 가릴 수 있는가 |
| 12 | 결과 제목·보고서 개수 줄에 "지그 매핑 제외"·"참고용" 수가 맞게 나오는가 |
| 13 | 강제 부여 전(v0.25.1) 스터디를 열면 화면·순위·3D 가 그대로인가 |
| 14 | 체결부가 잘 맞는 형상(이전에 문제없던 ④ 스터디 복제)에서 강제 0곳, 순위가 예전과 같은가 |
| 15 | 거리 한도 없이 붙인 결과가 쓸 만한가: 먼 강제(빨강 선)가 엉뚱한 면(다른 벽·반대편)에 붙지 않았는지, 먼 강제 임계 10 mm 가 현장 모델에 맞는지 — 필요하면 `tie_force_far_warn_mm`·`tie_force.max_dist_mm` 값 기록 |

---

## 13. 결정 근거 (요약 — 전문 `docs/decisions.md` 2026-11-27 D-0.25.2-1~26)

| # | 결정 | 근거 1줄 |
|---|---|---|
| 1 | "frame 별 t" = Case 1개에 t* 1개를 아무 h3d 프레임으로 | 원문이 고르는 단위를 h3d 프레임으로 말했고 Case·ESL·라이브러리가 t* 1개 구조 |
| 2 | 고를 수 있는 프레임 = `history.npz` 전 프레임, 시간 창·제외 요소는 직접 선택을 안 막음 | 직접 선택은 자동 규칙을 벗어나려는 것 |
| 3 | D 밖 프레임은 ESL 단계 앞에서 hw 1회로 채움(`fr_only`) | 변위·변형률이 D 에만 있고, v0.24.2 경계력 보충과 같은 틀이 이미 있음 |
| 4 | 채움 실패 = ESL 단계 실패(계속 안 함), 덤프·CSV Case 는 불가 + 사유 | 변위 없이는 ESL 을 못 만들고, 덤프는 프레임 1개로 hold 값을 못 만듦 |
| 5 | 기본 조작 = 곡선 클릭, 직접 입력은 후보 표 안 1행(프레임 번호 또는 시간 한 칸) | 원문 첫째 안·눈으로 고르기가 빠름, 새 카드·버튼 없이 들어감 |
| 6 | 직접 고른 t* 표시 = "자동 대비 %" + 경고 4종, 임계 `manual_ratio_warn` 0.5 | 사용자가 그 시점 하중이 최대의 몇 % 인지 알아야 함 |
| 7 | `frames_D` 는 안 바꾸고 `frames_fill` 새 키, npz 는 끝에 덧붙임 | 자동 t* 재계산·옛 읽는 코드의 위치 가정 불변 |
| 8 | 잡기 단계를 선언형 표 `CAPTURE_STAGES` 로, 강제 = 셋째 행 | AGENTS.md — 단계 차이를 표 한 곳에 |
| 9 | 강제 = 거리순으로 면적이 Case 묶음 면적에 닿을 때까지, 값 = 골격 최근접점(외삽 없음) | 면적·스프링 배율을 지키고 먼 노드에서 값이 커지지 않게 |
| 10 | 방식 표에 새 열 없음 — 강제 노드도 같은 행 규칙, 스프링 Σk = K_q | 강제 변위·스프링·고정이 같은 노드 집합을 쓰는 지금 구조 그대로 |
| 11 | 제외 = 못 붙임 비율 > `tie_miss_frac_max`, 참고용 = (강제 + 못 붙임) 비율 > 같은 값 **또는 먼 강제 ≥ 1**(개정 1) | "예전이면 빠졌을 형상 = 참고용", 멀리 옮긴 지지는 한 곳이어도 지그 조건이 달라짐 |
| 12 | 기본 켬, 스냅샷 키 `tie_force`(해시 안), 키 없는 옛 스냅샷 = 끔(`LEGACY_ABSENT`) | 사용자 의도 = 강제 + 경고, 옛 결과 바이트 불변 |
| 13 | ~~거리 한도 기본 10 mm~~ → **개정 1: 한도 없음**(`max_dist_mm` null, 키는 관리자 선택으로 남김), 10 mm 는 먼 강제 **표시** 임계 `tie_force_far_warn_mm` 로. 법선 조건 기본 없음 | 사용자 답 "거리 무관 무조건" — 붙이되 얼마나 먼지는 경고로 |
| 14 | 개수 줄 = 0 아닌 모든 키(`count_items`·라벨 표 한 곳) | #96 — 제외가 개수에 안 잡혀 "성공 0 · 실패 0" 으로 보임 |
| 15 | 주 탭이 비면 순위 있는 첫 탭을 기본으로 + 안내 링크, 보고서에도 그 표 | 전 노드 순위는 이미 계산돼 있는데 안 보였음 |
| 16 | 3D 표식 = 공용 지지 표식 표에 행 추가(자홍 테두리·빈 고리 + 선·✕) | v0.25.1 공용 뷰어 위 — 새 컴포넌트·버튼 없이 |
| 17 | 두 장 감지는 메시로(마주 보는 평행 요소, 간격 0.3~3 t, 비율 ≥ 0.5), 경고만 | STEP 커널 없이 STEP·메시 입력 공통, 리브·헤밍 오탐을 비율로 거름 |
| 18 | 두 장 설정은 해시·스냅샷 밖, 형상 행 키는 경고 날 때만 | 경고만이라 계산 불변, 안 걸린 형상 파일 바이트 불변 |
| 19 | 채움 설정 키를 경계력 보충과 따로(`frame_fill_*`) | 이름과 뜻이 어긋나지 않게 |
| 20 | 강제 부여는 격자 지그(④·옛 ③)만, 같은 메시 지그는 해당 없음 | 같은 메시는 Case tie 노드를 그대로 써 놓칠 수 없음 |
| 21 | `doe_messages.json` 소유 = C1(이번만) | 코어 시험이 새 문구를 읽음 |
| 22 | #96 원인은 확정하지 않고 검사(§4.4)와 현장 확인(E-9·11)으로 가림 | 요소 수 비 1.97 은 정황일 뿐 |

---

## 14. 질문에 대한 결정 (2026-11-27 사용자 답 — 남은 질문 없음)

| 질문 | 사용자 답 | 반영 |
|---|---|---|
| Q-1 "frame 별 t" 해석 | **"Case 당 t* 1개"** — 가정 확정 | §2.1 그대로(D-0.25.2-23). 여러 시점 ESL = Case 복제 |
| Q-2 강제 부여 거리 한도 | **"거리 무관 무조건"** | 거리 한도 없음: snap 뒤에도 0 인 묶음은 거리와 상관없이 가장 가까운 형상 노드(들)에 붙임(면적 채움·골격 최근접점 값·Σk 보존 규칙 그대로). `tie_force.max_dist_mm` 기본 null(키는 관리자 선택으로 남김 — D-0.25.2-24). "못 붙임" = 붙일 노드가 정말 없을 때뿐 → 기본 설정에서는 체결부 때문에 형상이 빠지지 않음. 참고용 = 비율 초과 또는 먼 강제 ≥ 1(D-0.25.2-25). 거리는 경고에 반드시: 강제 수/전체·비율·옮긴 거리 최소·중앙·최대·10 mm 넘는 곳 수 + 먼 곳 목록 `JIG_GRID_TIE_FAR`, 3D 는 선 길이·빨강 선(D-0.25.2-26). §1.3·§3.1~§3.6·§4.3·§6.3·§8.1·§10.2(15·16·17)·§12(10·15)·§13(11·13) 개정 |

- 사용자 의도 원문("체결부가 아닌곳이 얼마이고 이러한 거는 경고로 참조")과의 대응: "얼마" = `n_force/n_clusters`·% + 거리 분포, "경고로 참조" = `JIG_GRID_TIE_FORCED`·`TIE_FAR` + 순위표 "참고" 꼬리표.
- 한도가 없어 생기는 위험(계약이 막지 않고 **드러내는** 것): 형상이 다른 모델이거나 좌표가 통째로 어긋나면 모든 체결부가 엉뚱한 면에 붙어도 순위가 나온다 → 참고용 표시·먼 강제 경고·3D 빨강 선·`JIG_GRID_TIE_HINT` 로 알림. 형상 크기·정렬 자체가 허용 밖이면 기존 `SHAPE_SIZE_MISMATCH`·`SHAPE_MISALIGNED` 가 먼저 그 형상을 뺀다(불변).

---

## 15. 후속 (R-n) · 구현 메모

- R-TM-1 덤프 방식 Case 의 D 밖 프레임(원자료를 남긴 경우 파이썬 재구성).
- R-TM-2 직접 고른 프레임의 hotspot 을 ② 에서 미리 보기(채움 뒤).
- R-JF-1 강제 부여 위치를 3D 에서 손으로 옮기기.
- R-JF-2 순위에서 빠진 형상의 지그 3D(못 붙인 자리만 보기).
- R-DS-1 두 장 감지를 ①·③ STEP 입력에도.
- 구현 메모: 아래 §15.1~§15.4(구현 사실·계약과 다르게 된 점·실측 — 인계 메모 `work/handoff/*v0.25.2*`·`work/findings.md` TM-C1 절에서 옮김).

### 15.1 C1 코어 구현 사실 (release/v0.25.2 dc8cb725 → 4737a446 → be5ab88d → c32255b4 — 계약 보정·최소 해석 TM-C1-1~12)

- 골든 = release/v0.25.1 393789a8 코드로 기록(`tests/doe/golden_v0252_c1/golden.json`, 비교 `tests/doe/test_v0252_golden.py`: 파이프라인 자동·후보 2 + 스터디 세계 6 — 옛 스냅샷 tie_force 없음). 시험 V-0252-1~9 `tests/pipeline/test_tstar_manual.py`·`tests/io/test_tcl_fr_only.py`, 10~18 `tests/mech/test_grid_force.py`, 19~23·#96 재현 `tests/doe/test_v0252_c.py`(합성 `synth_tm.py`).
- `RANK_SOURCES` 새 열 `label`(지그 고정·지그 변위·지그 스프링·전 노드·경계력·내력 — 보고서 "다른 하중 출처 순위: {label}").
- 물리 실측: V-0252-4 임의 프레임(D 밖 5 채움) F_eq = 알려진 하중 상대 < 1e-6·평형 ≤ 1e-6·④ PASS(MAC 1.0, RMS 2.8e-12), V-0252-5 채움 = 처음부터 추출(u_rel·f_eq 배열 정확 일치), V-0252-13 Σk/K_q − 1 ≤ 4.4e-16, V-0252-14 평형 ≤ 2e-13·ΔΣR ≤ 2.5e-11·ΔM 4e-7 ≪ 한계, V-0252-15 50·200 mm 전부 force·순위 진입·한도 20 = 전부 miss.

- TM-C1-1 (§2.4·§11) 경계력 보충 병합 `esl/io/bforce_ondemand.py`(§11 소유표에 없음 — 코어라 C1)가 done.json mode `bf_only` 만 받음 →
  "fr_only 와 같은 실행에서 함께 읽은 경계력이 보충에서 '있음'" 이 되려면 `fr_only` 도 받아야 함. 최소 해석: `FILL_MODES = (bf_only,
  fr_only)` + frame_times 가 dict(`{"<f>": t}` — fr_only 형식)여도 읽음. 옛 bf_only 경로 불변(기존 시험 통과).
- TM-C1-2 (§4.1·§6.3·§8.2) `counts` 는 "새 결과만" 인데 v0.25.2 새 결과를 가리는 표식이 계약에 없음. ①②③ base 모드는 스냅샷 jig_grid
  블록을 무시해야 하는 v0.24.8 불변(test_base_mode_ignores_grid)이 있어, 표식 = **격자 지그 ∧ 스냅샷 rank.jig_grid 에 tie_force 키**
  (`stages._jg_force_on` + `_jg_kind == grid`)일 때만 `counts`·`n_ref` 를 씀. 그 밖 결과(①②③·옛 ④)는 화면이 n_failed + COUNT_LABELS
  거울로 같은 표시를 계산(계약 §8.2 C 의 옛 결과 경로). 보고서 개수 줄은 모든 결과에 `count_items` 로 덧붙임(덧붙일 키 없으면 글자 불변).
- TM-C1-3 (§10.2-14 ②) 합성 세계의 Case 맞춤 하중은 자기평형(ΣF ≈ 0)이라 "반력 합력 차 / 반력 합력" 은 0/0 에 가까움 → 분모를
  옮기지 않은 형상의 반력 크기 합 Σ‖R_n‖ 로(스프링 방식은 반력 = 구속 반력 + 스프링 힘 f_s·d̂). 측정(구멍 반지름 = 와셔 9 + snap 3.75
  + 요소 3 + δ, 강제 거리 14.1~14.4·18.7~19.1 mm): ① 평형 F ≤ 2e-13·M ≤ 6e-14 ② ΔΣR ≤ 2.5e-11 ③ ΔM ≤ 4e-7 ≪ 한계 Σ|R_q|·δ_q(1.5e4~1.6e5)
  ④ C_mix 차(옮기지 않은 판 대비): 강제 변위 δ3 −272.8 %·δ8 −361.7 %, 스프링 δ3 −40.2 %·δ8 −52.2 %. **강제 변위 방식은 멀리 옮긴
  지지에서 C_mix 가 크게 바뀜**(구멍 + 지지 이동 효과 섞임) — 참고용 표시가 필요한 근거. 1 % 초안 문턱(②)은 평형 때문에 항상 성립.
- TM-C1-4 (§10.2-14) "체결부 면을 δ 옮긴 판" 을 평판 세계에서 만들 수 없어(판이 어디나 면이라 band 가 잡음) 볼트 둘레 요소를 뺀 판
  (구멍 = snap 밖)으로 대신함. δ = 구멍 반지름 추가분, 실제 옮긴 거리는 시험 출력(GRIDFORCE phys)에 기록. V-0252-15(50·200 mm)는
  "좌표 통째 어긋남" 꼴(형상 A 좌표를 판 법선으로 δ) — 전부 force·dist ∈ [δ, √(δ²+(2h)²)]·한도 20 mm = 전부 miss·형상 제외 확인.
- TM-C1-5 (§4.3) marks.x(Case 체결부 중심 — 형상 전역 좌표): A 좌표 → 형상 좌표 = 가장 가까운 형상 노드 n0 기준 X_S[n0] + (x_A −
  ŷ[n0])·R_plᵀ(배치가 강체면 정확, frame 정규화 배치는 근사). 3D 선 끝점용으로 marks(force)에 `to`(붙인 노드 면적 가중 중심 — 형상
  전역) 키를 더함(계약 키 목록 밖 추가 — F1 선 그리기용).
- TM-C1-6 (§3.1) tie_force.normal_deg 90 = "조건 없음" 을 _proj_ok(cos 90° ≈ 6e-17)로 하면 법선 0 노드(고립)를 거름 → normal_deg ≥ 90 이면
  법선 판정을 아예 하지 않음(< 90 일 때만 band 와 같은 _proj_ok).
- TM-C1-7 (§2.3) D 안 비후보 프레임(--frame)의 옛 레코드(elem_id·value null)가 직접 고른 t* 레코드(frame_point 값 + manual)로 바뀜(계약
  의도). 후보 ∧ D = 옛 레코드 그대로(골든 pipe_cand). 후보인데 D 밖(채운 프레임) = 직접 고른 t* 레코드(D 시각이 없어 옛 레코드 불가).
- TM-C1-8 (§2.5) 경고 4종 중 TSTAR_MANUAL_LOW 만 run.json 단계 warnings(경고 수준), 나머지(정보)는 echo + esl_summary.tstar_manual.notes
  [{code, level, text}]. ESL 단계 요약(run.json stages.esl.summary)에도 tstar_manual(notes 제외) — B1 작업 결과용.
- TM-C1-9 (§2.4) TCL fr_only 의 변형률 출처 고정 = 요청 키 `strain_sources <추출 source 하나>`(frame_fill.request_keys) 또는 옛
  `strain_type`(Max_Strain 고정). 덤프 source 가 골라지면 INPUT_INVALID(판정 표 행 3 이 먼저 막음). done.json frame_times = {"<f>": t}.
  fr_only 블록은 `# >>> v0.25.2 fr_only` 표식 구간 — 빼면 393789a8 파일과 같은 글자(정적 시험 sha 고정).
- TM-C1-10 (#96 재현 합성) 비대칭으로 구멍을 내면 PCA frame 이 기울어 SHAPE_SIZE_MISMATCH(6 % > 5 %)가 먼저 빼므로 네 모서리 볼트
  자리(대칭)에 구멍. 두 장 형상은 band 가 두 장 다 잡아 잡힌 면적비 = 2.0(두께 두 번 — 정황이 JIG_GRID_AREA_RATIO 경계값에도 드러남).
  요소 수 비 1.96(#96 1.97). 강제 켬 결과: 4/6 강제, 거리 7.14 mm, 참고용, score 0.971.
- TM-C1-11 (§4.3, 범위 판단) v0.25.1 씬 3D 묶음(post/view3d_scene — `_scn_jig_grid_p`)의 지지 행에는 via·tie_marks 를 넣지 않음(계약은
  지그 응답 3D manifest 만 지정). 필요하면 후속.
- TM-C1-12 (§9 성능 실측 — 합성) 형상 노드 112,601(h 0.5 mm 판)·묶음 6: 구멍 4곳 강제 0.63 s · 30 mm 어긋남 전부 강제 0.81 s · 200 mm 0.66→
  1.66 s(형상 전체 capture). 먼 묶음은 완결 조건(k 번째 이웃 거리 > 고른 거리 + L_q + ρ) 때문에 KD 질의 반경이 옮긴 거리만큼 커져 묶음당
  비용이 거리에 비례(정확 거리 메모·묶음 중심 1점 질의·첫 k = 면적 어림 ×2 로 줄임). 228 묶음이 모두 수백 mm 어긋난 극단은 형상당 수십 초
  가능 — 현장 E-0252-10 에서 실측 필요.

### 15.2 B1 백엔드·워커 구현 사실 (wip/v0.25.2-b1 a2f45b84)

- 설정 pydantic `AltairCfg.frame_fill_timeout_s·frame_fill_wait_s`, `BeadDoeRankJigGridForceCfg`(`tie_force`)·`tie_force_far_warn_mm`, `view3d.jig_force_marks_max`, `compare.double_sheet` + yaml 2개(§8.1 값). 스냅샷 `rank_snapshot` 은 블록 통째 복사(변경 없음 — 키 없으면 따라오지 않음).
- `worker/esl_worker/frame_fill.py`(사실 `facts`·`fill_state`·요청 `request_extra`·평가 `evaluate`·문구 `LOG`·`CAUSE_TEXT` — 원인 `WAIT`·`TIMEOUT`·`LICENSE`·`HW_FAILED`·`MISMATCH`·`MERGE`·`SETTINGS`), `core_adapter.frame_fill_*`·`frame_point` 래퍼, `executor._frame_fill`(경계력 보충 바로 앞·같은 hw 세마포어 — 작업 폴더 `<esl_root>/_h3d/<Case 폴더>/frame_fill/raw`, 단계 outputs·작업 결과 `frame_fill`, 실패 = 단계 실패 `TSTAR_FRAME_FILL_FAILED`·막힘 = 기록 status `blocked`, 같은 실행 bforce 키가 있으면 같은 fill_out 으로 경계력 병합 — 실패해도 채움 성공).
- API: `GET /tstar` `frames`(history.npz)·`frames_have`(코어 `frames_have`, 못 부르면 변위 프레임)·`fill`(행 2~5 — `have` 무관)·`history.frame_index`(곡선 점 수 = 프레임 수일 때만 — 어긋난 옛 산출물은 키 없음). `PUT`: 후보 ∧ in_D 면 지금 경로(저장 값 바이트 불변), 그 밖 = 코어 `frame_point` + `manual`(`tstar_confirm.manual_tstar`), 프레임 목록을 못 읽는 옛 산출물 = 지금 규칙(후보만). ESL 작업 사전 점검 `job_params._fill_ok`(manual ∧ 그 프레임 ∧ DECIDE ≠ block).
- 결과 스키마 선택 키(`n_ref`·`counts`·`via`·`tie_marks`·`n_forced_shapes`·`n_ref_shapes`) — None 이면 직렬화에서 키를 뺌(옛 응답 바이트 불변). OpenAPI 재생성. 옛 시험 `test_p1b_e2e` 의 없는 프레임 422 코드 `FRAME_NOT_CANDIDATE` → `FRAME_NOT_FOUND`(§6.1 3).
- 시험 `backend/tests/test_v0252_b1_api.py`(V-0252-24·25·27 — 손으로 심은 산출물 + 코어 `frame_point` 가짜, 판정·frames_have 는 실제 코어), `worker/tests/test_frame_fill.py`(V-0252-26 — 통합에서 실제 코어로, §15.4 INT-3).

### 15.3 F1 프런트 구현 사실 (wip/v0.25.2-f1 63de3332)

- A: `Stage2.tsx`·`MaxHoldChart.tsx`(곡선 클릭·안내선·그림 안 읽기 글자, 세로선 = `frames` 시각)·`lib/tstarFrames.ts`(가장 가까운 프레임·입력 해석·변위 칸·확정 전 경고). B: `view3d/supportMarks.ts` `TIE_TABLE`·`supports.buildTieMarks`·`scene.setTieMarks`·탐침 kind `tie`·범례 `markLegend`. C: `doeTabs.countItems·countTail·tabState`(빈 주 탭 → 순위 있는 첫 탭)·빈 탭 링크·`참고` 꼬리표(title = `JIG_GRID_TIE_FORCED` 경고를 `did` 로 찾음)·`SHAPE_DOUBLE_SHEET` 배지. 목 자료·시험 `tstar_manual_v0252.test.tsx`·`doe_v0252.test.tsx`.
- 높이 측정 `scripts/screenshots-v0252-f1.mjs` — 2560×1440·1920×1080 ②·스터디 결과 높이 증가 0(V-0252-28·30). 경고 필드 이름(`did`·`n_force`·`pct`·`dmin`·… — 서버 `message` 가 없을 때 대체 문구용) 가정.
- 계약 밖 제안 키 2개(`GET /tstar` `manual_ratio_warn`, 3D manifest `tie_far_mm`)와 `types.ts` 손 맞춤 11키는 통합에서 처리(§15.4 INT-4·5).

### 15.4 통합 보정 (release/v0.25.2 통합 — INT-n)

| # | 내용 | 근거 · 시험 |
|---|---|---|
| INT-1 | 병합 wip/v0.25.2-b1(a2f45b84) → wip/v0.25.2-f1(63de3332) — 글자 충돌 0 → release/v0.25.1 d578b0df(v0.25.1 독립 검증 수정 INT-10~12) — 충돌 2곳(`docs/decisions.md`·`resources/doe_messages.json` 끝 덧붙임) 양쪽 보존(문구 키 중복 0) → release/v0.25.1 b94df804(INT-13 Compare3D 훅 순서 — `DoeStudy.tsx` 자동 병합) → 2fe514f5(INT-14~16 씬 요약 umax 정의·approx 견고화 — decisions 끝 충돌 양쪽 보존). `schemas.py` 자동 병합(v0.25.1 `View3dSceneOut.geometry_key`·`DoeScenePackOut.approx` + v0.25.2 `View3dOut.tie_marks`) | JSON 키 중복 검사, 아래 시험 |
| INT-2 | B1 이 C1 껍데기 시점에 둔 설정 거울 분기(`test_doe_config` — 코어 DEFAULTS 에 새 키가 없으면 빼고 대조) 제거 → 새 키(`tie_force`·`tie_force_far_warn_mm`·`jig_force_marks_max`·`double_sheet`)가 코어 DEFAULTS 에 있음을 단언 + 전체 대조 | `backend/tests/test_doe_config.py` |
| INT-3 | 워커 채움 시험의 가짜 `merge`·코어 ESL 가로채기(`TEST_STOP`) 제거 → **실제 코어** `frame_fill.merge`·`_select_frame`·ESL. 가짜 hw `fr_only` 출력 = `FAKE_HW_FR_SRC`(같은 합성 결과를 전 프레임 D 로 쓴 CSV)의 f·f−1 행·시각·프레임 수(실제 병합의 같은 h3d 확인 통과), 다른 h3d = `FAKE_HW_FR_NFRAMES` 로 실제 `FRAME_FILL_MISMATCH`(01_extract 바이트 불변 확인). 채움 → 코어 ESL 성공·`frames_fill[job_id]`·`disp.npz` 끝 프레임·`esl_summary.tstar_manual.filled`·단계 outputs `frame_fill`, 두 번째 실행 hw 0, 재시도·재추출 뒤 다시 채움도 ESL 성공 | `worker/tests/test_frame_fill.py` 17(+ `backend/tests/test_doe_config.py`) |
| INT-4 | `check:api` 11건 → 0: B1 스키마가 9키(`n_forced_shapes`·`n_ref_shapes`·`counts`(결과·보기)·`tie_marks`·`via` …)를 이미 가짐, `n_ref`(결과·보기) = 스키마 선택·null 허용 ↔ TS `number` → TS `number \| null`(서버는 None 이면 키를 안 냄), `tie_far_mm` = INT-5 | `npm run check:api` 통과(스키마 267) |
| INT-5 | F1 제안 키 2개 — 계약 밖이지만 **설정 값을 그대로 내보내는 것**(계약 본문 설계 변경 아님): (a) `GET /cases/{id}/tstar` 최상위 `manual_ratio_warn` = 코어 `esl.config.tstar_manual_settings(core cfg)`(새 래퍼 `core_adapter.tstar_manual_settings`, 코어를 못 부르면 키 없음 — 화면은 경고색 판정 생략) (b) 지그 응답 3D manifest `tie_far_mm` = 그 형상 `map.tie.force.far_mm`(실행 때 `tie_force_far_warn_mm` 기록 값 — `marks[].far` 를 정한 값과 같음, 설정을 나중에 바꿔도 범례·표식이 어긋나지 않게). `build_view(tie_far_mm=)` 는 `tie_marks` 가 있을 때만 씀(옛 manifest 바이트 불변 — `test_view3d_golden`), `View3dOut.tie_far_mm` 선택 키(None = 키 없음) | `test_v0252_b1_api::test_get_tstar_new_keys_results_case`·`test_manifest_tie_far_mm_passthrough`(실제 `build_view`), `tests/doe/test_v0252_c.py`(#96 켬 `man["tie_far_mm"] == tie["force"]["far_mm"]`) |
| INT-6 | C1 구현 사실 `marks[].to`(TM-C1-5 — 붙인 노드 면적 가중 중심) ↔ 화면: F1 은 선 끝을 "가장 가까운 강제 지지 표식" 으로 그려 이웃 체결부 쪽으로 갈 수 있었음 → `to` 가 있으면 선 끝 = `to`(없으면 지금 규칙). TS `View3dTieMark.to?`·`dist: number \| null`(miss = null — 코어 그대로), 탐침 null 처리 | vitest `doe_v0252` "코어 marks[].to" |
| INT-7 | `counts` 조건(TM-C1-2 — 격자 지그 ∧ 스냅샷 `tie_force` 일 때만 API `counts`·`n_ref`) ↔ 화면: 그 밖 결과는 화면 `countItems` 가 계산하는데 규칙이 코어 `count_items` 와 달랐음(같은 키 합 없음·n_skipped→n_failed 삽입 순서) → 코어와 같게(같은 키 합·`COUNT_LABELS` 표 순서·표에 없는 키는 뒤 이름순). 결과 제목 = 보고서 개수 줄 | vitest `doe_v0252` 기대값 = 코어 `count_items` 출력 |
| INT-8 | 문서·버전: CHANGELOG [0.25.2]·`user.md`(② 직접 고르기·③ 채움 로그·강제 부여·참고·3D 표식·결과 개수·두 장 경고)·`admin.md` §4.12(새 설정 표·채움·API)·`docs/manual/field_check_v0252.md`(E-0252-1~15·#96 재시도 절차)·VERSION 0.25.2·OpenAPI info·버전 시험 2곳(`test_menu_deploy`·`test_p3_ux_hardening`), 인계 메모 3개·findings TM-C1 절 → 이 절·decisions 로 옮기고 삭제 | `test_menu_deploy`·`test_p3_ux_hardening`·`p3.test.tsx`(user.md) |
| INT-9 | 통합 시험(2026-11-28, 실행기 `/tmp/int252/run_all.sh`): tests/ 2028 passed·192 skipped·실패 3 = 허용 3(test_large_model_cad_share·test_v0160_bytes_skip_policy[h8]·[h5open]), vt_12·vt_16 통과(2fe514f5 병합 전 수집 → 바뀐 `tests/doe/test_view3d_scene.py` 단독 36 통과). `pytest packages/beadgraph`(저장소 루트) 117 passed·2 skipped. backend 1차 1355 passed·11 failed = 옛 시험의 손 기대 dict(`test_doe_rank_metric_api` 설정 거울·스냅샷·view3d 거울, `test_doe_v0248_b1_api` jig_grid 거울·스냅샷·OpenAPI 키 집합)에 v0.25.2 키(`tie_force`·`tie_force_far_warn_mm`·`jig_force_marks_max`·선택 키 `n_forced_shapes`·`n_ref_shapes`)가 없던 것 — B1 이 /tmp 게이트로 전체 시험을 못 돌려 남김 → 기대 dict 에 계약 §8.1 값 추가(같음 비교 유지) → 2차 1366 passed. worker 432 passed·6 skipped·1 failed = `test_scx_fetch::test_hash_mismatch_retry_and_fail_then_resume_from_h3d`(스레드가 받은 파일 수를 보고 실패 주입을 켜는 시간 경쟁 — 이번 판 변경 없음, 단독 2회 통과). frontend typecheck·build·check:api 통과, vitest 84 파일 1046 passed. /tmp 여유 21.9 GB(정리 없음), 다른 시험과 겹치지 않게 단계마다 대기 | 로그 `/tmp/int252/*.log` |
| INT-10 | **메인 결정 D-0.25.2-INT-10(사용자 부재 — 되돌리기 쉬운 쪽, 사용자 확인 대기)**: 독립 검증에서 참고(`jig_ref`) 형상이 강제 부여 때문에 1위·`result.best`(H5 8.7 mm 강제 d002). → (a) `ranking.csv` 맨 끝 열 `jig_ref`(순위 행 True/False, 기준·순위 밖 빈 칸)·보고서 순위표 "참고" 열 — 강제 부여 스냅샷 격자 지그 결과(`counts` 있는 결과 = TM-C1-2 조건)만, (b) `best`(산출물 대상) = `rank.best_order`(참고 아닌 행 순위 순 → 참고 행) 첫째, 모두 참고면 최상위 참고 + 결과 경고 `BEST_IS_REF`, 1위를 건너뛰면 보고서 최적 절에 `BEST_SKIPS_REF` 한 줄. ①②③ `best_all`(keep_files_top) 도 같은 순서. 순위 값·번호·정렬 불변. 옛 스냅샷(tie_force 없음)은 jig_ref 가 없어 순서·파일 바이트 불변 | `tests/doe/test_v0252_int.py`(INT-10 순수·혼합·전부 참고·옛 스냅샷), 골든 `test_v0252_golden` |
| INT-11 | **(현장 위험) 작은 통째 어긋남**: 원인 확인 — 정렬 검사(`scenario.align_check`, SC-D-7b)는 형상 frame 원점의 기준 frame (ξ,η) 차 ≤ `compare.align_tol`(0.05)·법선 ≤ 5° 만 본다 → H6(1240×695 mm) 면내 300 mm 이동은 Δξ 0.24 로 **`SHAPE_MISALIGNED` 가 잡음**(검증의 300 mm 시나리오는 `grid_map.capture` 를 직접 불러 정렬 검사를 거치지 않았음). 못 잡는 곳 = 허용 안의 이동(H6: ξ ≤ 62 mm·η ≤ 35 mm)과 법선 방향 이동(법선 이동은 강제·먼 강제 경고가 잡음). 그 범위에서 band 잡기는 판이 이어져 있어 "잡힘" 이고, 잡힌 묶음의 중심 이동 중앙값은 0.1 ~ 0.5 mm(어긋남 2 ~ 60 mm — 측정)라 제안된 "잡힌 묶음 이동 벡터" 판정으로는 안 보임 → **구멍 가장자리 비교** `grid_map.rim_shift`(Case 골격 점 ∩ A 자유 변 = 구멍 가장자리, 묶음마다 그 중심에서 묶음 반지름 안 형상 자유 변 노드 중심과의 차, 판 법선 성분 뺌, 형상 쪽 3노드 미만 = 그 묶음 뺌 — 구멍 메움·와셔 면만 = 거짓 경보 없음, 묶음 중앙값). 임계 = 기존 `frame_shift_warn × cell_mm`(1.5 mm, 해시 밖 — 새 키 없음). 넘으면 `map.tie.shift{mm, vec, n, n_rim, tol_mm, over}`·`ref` 참·형상/스터디 경고 `JIG_GRID_TIE_SHIFT`(문구 `doe_messages.json`, 화면 거울 `JIG_CODE_TEXT`, `참고` 꼬리표 title 대체). 강제 부여 스냅샷만(옛 결과 불변). 측정(H6 77 묶음 중 73 비교): 2·3·5·10 mm → 2.0·3.0·5.0·8.9 mm, 20 mm → 4.8(18곳), 40 mm → 0(13곳 — 한계), 메시 흔듦 ±1.5 mm → 0.04, 구멍 메움 → None | `tests/doe/test_v0252_int.py`(순수·정렬 검사 범위·스터디 경고·참고), `tests/mech`·`test_v0252_c`(구멍 없는 합성 세계 = 진단 없음) |
| INT-12 | **(독립 검증 Fail)** 워커 `register.COMPARE_SHAPE_KEYS` 에 `double_sheet` 없음 → 준비 요약 형상 행에서 빠져 `DoeInputs` "앞뒷면 두 장?" 배지가 실서버에서 안 뜸(코어 compare.json 만 본 시험이 못 잡음) → 목록에 추가, dict 아닌 행은 키 제거(route·mq 와 같은 규칙 — 옛 요약 불변) | `worker/tests/test_v0252_int_jobs.py`(실제 코어 ④ 준비 → 실제 워커 등록 → API GET = 프런트 fixture `prep_double_sheet_v0252.json`), vitest `doe_v0252` INT-12(그 fixture 로 배지·툴팁) |
