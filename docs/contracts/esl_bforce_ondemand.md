# 계약: 경계력 원자료 ESL 때 보충 — 덤프 방식 추출의 선택 프레임만 bf 전용 추출 (BFD, v0.24.2)

- 상태: **확정 → 구현 기준**(2026-11-19). 브랜치 `release/v0.24.2`(main dbdec88d = v0.24.1).
- 버전: **v0.24.2**(버그 수정). DB migration **없음** — 새 값은 Case 폴더 파일(`01_extract/bforce.*` 병합·`01_extract/bforce_ondemand.json`), `<esl_root>/_h3d/<Case 폴더>/bf_ondemand/` 새 폴더, ESL step outputs·작업 result JSON 새 키, ESL 요약 `forces.bforce`·`forces.fint` 의 새 code 값, request.txt 새 키, 설정 새 키 3개. 새 작업 유형·새 step·API 변경 없음.
- 관계: `esl_bforce.md`(TCL 패스 C 경계력 덤프 §1·pack §2·ESL 단계 §4 — 이 문서가 §1 의 "dump 모드 범위 밖(R-BF-5)"을 닫는다), `esl_fint.md` §3(내력 ESL 단계), `esl_view3d_sources.md` §2.5(Case 출처 사유 = 요약 reason 그대로), `esl_p3_ux.md` §6(서버 h3d 추출·hw 세마포어·제한기), `esl_strain_fallback.md`(덤프 방식). 충돌하면 이 문서 범위에서는 이 문서가 우선.
- ID: 결정 `D-0.24.2-BFD-n`, 시험 `V-0242-BFD-n`, 후속 `R-BFD-n`.

### 사용자 결정 (변경 금지)
1. (2026-11-19) **B안 — ESL 계산 때 고른 프레임만 추출.** ③ ESL(ESL_SOLVE 작업)에서 선택 프레임(t*)의 경계력 원자료가 01_extract 에 없으면, 워커가 그 프레임만 h3d 에서 읽어(HyperWorks TCL "bf 전용" 모드) Case 01_extract 의 bforce 자료에 병합·저장하고(다음 ESL 부터 재사용) ESL 을 계속한다.
2. 추출(H3D_EXTRACT) 시간은 그대로. 덤프·비덤프 공통 규칙: **선택 프레임이 없으면 보충**.

---

## 0. 원인 · 현장 증거

### 0.1 원인 (파일:행, v0.24.1 = dbdec88d)

| # | 원인 | 근거 |
|---|---|---|
| C1 | 덤프 방식(`strain_mode dump` — Max_Strain·Plastic Strain 없음 → strain_tensor 전 프레임 덤프)은 `dump_pass` 뒤 done.json 을 쓰고 **return** — 경계력 덤프가 있는 패스 C 에 도달하지 않는다 | `resources/tcl/esl_h3d_extract.tcl:1755-1807`(`if {$smode eq "dump"} { … dump_pass … write_done … return }`), `dump_pass` 정의 `:1055-1136`(strain_raw.csv·disp.csv 만) |
| C2 | 경계력 결과 유형 찾기·덤프·done.json `bforce` 는 비덤프 패스 C 안에만 있다 | `bf_resolve` 정의 `:1019-1051`, 호출 `:1940`, bf CSV 열기 `:1943-1949`, 청크별 질의 `:1978-1989`, 닫기·종류 기록 `:1994-2004`, done.json `bforce` `:2005-2009` |
| C3 | 계약이 덤프를 범위 밖으로 두었다 | `esl_bforce.md` §1 끝 줄 "dump 모드(strain_tensor 원시 덤프 경로)는 이번 범위 밖(R-BF-5)", §12 R-BF-5 |
| C4 | done.json 에 `bforce` 가 없으면 pack 이 아무것도 쓰지 않고 → ESL 경계력·내력 = none | `esl/io/bforce_csv.py:36-41`(`pack_bforce` → None), `esl/pipeline.py:598`(호출), `:1200-1204`(BF_NO_DATA, 사유 "v0.24.0 이전 추출이거나 bf_on 0" — **실제 원인과 다른 문구**), `:1284-1288`(FINT_NO_DATA 같은 문구) |
| C5 | 강성 스터디는 Case `04_esl/bforce.npz`·`fint.npz` 에서 하중을 찾는다 → 없음 = BF_NOT_FOUND·FINT_NOT_FOUND → 스터디 경계력·내력 계산 불가 | `esl_bforce.md` §5.2, `esl_fint.md` §5 |
| C6 | (잠재 — #82 원인 아님) 워커 `bforce_request` 가 `CoreError` 를 조용히 `{}` 로 삼킴 → request.txt 에 bf 키 없음 → TCL 기본 `bf_on 0` → 경고 없이 경계력 자료 없음 | `worker/esl_worker/h3d.py:216-229`(223-224 `except core_adapter.CoreError: return {}`), 호출 `worker/esl_worker/executor.py:611` |

### 0.2 현장 증거 (#82 2026-11-19 코멘트 사본 `/tmp/c82_field_20261119.txt`)

| 항목 | 값 | 사본 행 |
|---|---|---|
| request.txt | `bf_on 1`, `bf_names_cont Contact Forces\|Contact Force\|CONT` … `bf_names_fint …`, `bf_vec_comps X Y Z` — **정상**(C6 아님) | 19-25 |
| done.json | ok true, `strain_mode "dump"`, `strain_source strain_tensor`(strain_tried: max_strain·plastic_strain "result type not in subcase"), `passes {"DUMP": {frames 61, layers 3, rows_strain 23,590,164, rows_disp 11,846,749, seconds 4995.422}}`, **`bforce` 키 없음** | 28 |
| GetDataTypeList | `Displacement Acceleration {Contact Forces} Velocity Max_Stress Min_Stress Strain Stress {Erosion Status} {Mass Change}` — CONT·ACC 있음, CONT2·MASS·FINT 없음 → 보충되면 경계력 등급 **contact**, 내력 none(FINT 없음) | 28(api) |
| 규모 | h3d 15,613,734,368 B(15.6 GB), 파트 21 chassis_rear: 요소 193,362, 노드 194,233(model.csv)·선택 194,209, 61 프레임 | 28·56·60 |
| 시간 | 모델 로드(AddModel) 28.6 s, 시작 → 질의 준비(선택·id·청크 세트) 2 분 28 초(13:57:45 → 14:00:13), 노드 청크 질의 ≈ 5 s/청크(변위 3성분), 덤프 4,995 s, hw 전체 5,211.5 s | 33-60·555-558 |
| 자원 제한 | `windows_job`: 우선순위 below_normal, 메모리 64 GB, CPU 4/64 코어, 워커 종료 시 강제 종료 | 32 |
| 증상 | Case ③ 경계력 줄 "추출물에 경계력 결과 없음(v0.24.0 이전 추출이거나 bf_on 0)", 스터디 경계력·내력 계산 불가(사용자 보고) | – |

### 0.3 왜 B안인가 (참고 — 결정은 사용자 확정 1)

| 안 | 내용 | 추출 시간(현장 h3d) | ESL 시간 |
|---|---|---|---|
| A | 덤프 경로에 전 프레임 경계력 덤프 추가 | +≈ 41 분(61 프레임 × 노드 청크 4 × 종류 2 × ≈ 5 s), 재해석 h3d(5종류) +≈ 100 분 | 불변 |
| **B** | ESL 때 선택 프레임만 bf 전용 추출 → 01_extract 병합·재사용 | **불변** | 프레임당 처음 1회 +≈ 3~4 분(§8), 같은 프레임 다시 = 0 |

---

## 1. 흐름

### 1.1 순서 (ESL_SOLVE 작업, step 목록 `ESL`·`ESL_REGISTER` 그대로)

```text
claim → 입력 지문 확인(기존: h3d 바뀜·없음 = INPUT_CHANGED 로 작업 실패 — 변경 없음)
step ESL RUNNING
 ├─ [보충 단계 — 워커, 코어 자식 시작 전]  bf_ondemand.decide(§1.2)
 │    none → 그대로 코어로(기록·로그 없음, 판정 4 만 로그 1줄)
 │    skip → 기록(skipped) → 코어로
 │    fill → request.txt(bf_only·bf_frames) → hw 세마포어(대기 한도) → hw(TCL bf 전용, §2)
 │           → 평가(§3.4) → 병합(§4: 01_extract/bforce.* 갱신) → 기록(ok|failed) → hw 해제 → 코어로
 ├─ 코어 자식 esl(기존): _bforce_esl·_fint_esl 이 01_extract/bforce.* 와 기록(§4.6)을 읽음(§5)
 └─ 산출물 등록(기존 03_bc·04_esl·run.json·로그 + 보충했으면 01_extract/bforce.*·bforce_ondemand.json)
step ESL_REGISTER(기존 — forces.bforce·forces.fint 에 code·reason 그대로)
```

- 새 작업 유형·새 step 없음(D-0.24.2-BFD-2). 보충은 ESL step 안, 로그는 ESL step 로그(`logs/<job>/step_01_ESL.log`).
- 같은 Case·같은 프레임은 한 번 보충되면 다음 ESL 부터 재사용(판정 4).

### 1.2 판정 표 `worker/esl_worker/bf_ondemand.py:DECIDE` (위에서부터 첫 일치, 호출부는 결과만 읽음)

| # | 조건(술어) | 동작 | 원인 cause | 기록 | 작업 로그 |
|---|---|---|---|---|---|
| 1 | 설정 `bforce.enabled` false | none | – | 없음 | 없음 |
| 2 | 설정 `bforce.on_demand` false | none | – | 없음 | 없음 |
| 3 | Case `input_kind` ≠ `H3D`(결과 폴더 입력) | none | – | 없음 | 없음 |
| 4 | `bforce_csv.has_frame(01_extract, f)`(§1.3) | none(재사용) | – | 없음 | `있음 — 보충 안 함` |
| 5 | 이 Case 의 이전 보충(status ok)이 **지금과 같은** 이름 후보·벡터 성분·스칼라 성분으로 종류를 하나도 못 찾음(`bforce_ondemand.no_types_before`) | skip | `NO_TYPES` | skipped | 생략 줄 |
| 6 | `case.h3d_path` 파일 없음·읽기 불가 | skip | `H3D_UNREADABLE` | skipped | 생략 줄 |
| 7 | `altair.hw_exe_path` 없음·파일 없음, 또는 추출 TCL(`default_extract_tcl()`) 없음 | skip | `HW_UNAVAILABLE` | skipped | 생략 줄 |
| 8 | 경계력 요청 키를 만들 수 없음(코어 설정 CoreError — §3.7) | skip | `SETTINGS` | skipped | 생략 줄 |
| 9 | 그 밖 | **fill** | – | 결과(§1.4) | 시작 줄 |

- f = 작업 params `frame_index`(ESL 이 쓰는 선택 프레임 — `esl_solve_params` 가 01_extract `disp.npz` 프레임 안임을 이미 보장).
- 덤프·비덤프를 나누는 행은 없다 — 규칙은 "그 프레임이 있나" 하나(사용자 확정 2). 비덤프(v0.24.0 이후, bf_on 1) 추출은 t* ∈ D = bforce 프레임이라 항상 판정 4.

### 1.3 "프레임 있음" 정의 (`esl/io/bforce_csv.py:has_frame(extract_dir, frame) -> bool`)

`01_extract/bforce.json` 이 있고 `on` 이 참이고 `frames` 에 f 가 있으면 참. 종류를 하나도 못 찾은 프레임(npz 없음·kinds 전부 null)도 "있음"(같은 프레임을 다시 보충하지 않음 — ESL 은 기존 규칙대로 등급 none "접촉력 결과 유형이 h3d 에 없음"). 파일 읽기 오류 = 없음.

### 1.4 보충 결과 → 기록 → 코어 요약

| 결과 | 기록 status | cause | 코어 요약 code(경계력·내력 공통) |
|---|---|---|---|
| 병합 성공(§4) | ok | – | 없음 — 자료가 생겼으므로 기존 계산(contact·full·none-종류없음, 내력 FINT 있으면 계산) |
| 병합 시 같은 프레임이 이미 있음(동시성 방어) | ok | – | 위와 같음(기존 자료 그대로, 경고 `dup`) |
| 판정 5~8 | skipped | NO_TYPES·H3D_UNREADABLE·HW_UNAVAILABLE·SETTINGS | `BF_EXTRACT_SKIPPED` |
| hw 차례를 `altair.bf_on_demand_wait_s` 동안 못 잡음 | skipped | `WAIT` | `BF_EXTRACT_SKIPPED` |
| hw 시간 초과(`altair.bf_on_demand_timeout_s`) → 프로세스 트리 종료 | failed | `TIMEOUT` | `BF_EXTRACT_FAILED` |
| hw 실패 + 라이선스 흔적(§3.4) | failed | `LICENSE` | `BF_EXTRACT_FAILED` |
| 그 밖 hw 실패(종료코드 ≠ 0·done.json 없음·ok false·bf 전용 출력 아님·요청 프레임 없음) | failed | `HW_FAILED` | `BF_EXTRACT_FAILED` |
| 같은 h3d 아님(§4.3) | failed | `MISMATCH` | `BF_EXTRACT_FAILED` |
| 병합·쓰기 오류(EslError·OSError) | failed | `MERGE` | `BF_EXTRACT_FAILED` |
| 사용자 취소 · lease 상실 | (기록 없음) | – | 작업 CANCELED · LEASE_LOST(기존 규칙, hw 트리 종료) |

- **ESL 은 어떤 보충 결과에도 실패하지 않는다**(전 노드 ESL 결과 그대로). 실패한 보충은 기록만 남고 다음 ESL 때 다시 시도한다(판정 5 의 종류 없음만 예외).

---

## 2. TCL bf 전용 모드 (`resources/tcl/esl_h3d_extract.tcl`)

### 2.1 request.txt 새 키

| 키 | TCL 기본 | 값 | 검증(실패 = done.json ok false) |
|---|---|---|---|
| `bf_only` | `0` | `0` \| `1` | 그 밖 = `INPUT_INVALID "bf_only must be 0 or 1"`; `1` 인데 `bf_on` ≠ 1 = `INPUT_INVALID "bf_only needs bf_on 1"` |
| `bf_frames` | `""` | 공백 구분 0 이상 정수(중복 금지, 순서 무관 — 오름차순으로 처리) | `bf_only 1` 인데 비었거나 정수 아님·중복 = `INPUT_INVALID`; 값 ≥ 프레임 수 = `H3D_MISSING_RESULT "bf_frames: frame <f> not in subcase <s> (<n> frames)"` |

- bf 전용 모드가 쓰는 기존 키: `part_title`/`part_id`(또는 `-part`), `subcase`, `chunk`, `node_selection`, `bf_on`, `bf_names_<k>`, `bf_vec_comps`, `scalar_comps`(mass 성분 후보). 그 밖 키(strain_*·names_*·comp_*·vm_comps·layer_*·dump_*·hot_k·top_n·reach_rtol·prev_file·frame0_pass·cum_min_incr·elem_selection·disp_*)는 읽기 검증만 기존대로, 쓰지 않는다. `-hot_k`·`-top_n` 인자도 무시.

### 2.2 실행 순서 (bf_only 1)

| 하는 것(기존 그대로) | 생략하는 것 |
|---|---|
| 인자·출력 폴더·이전 산출물 백업(`<out>/_backup/<ts>/`)·progress.log·check_input·read_request | 변형률 원천 고르기(`pick_source`·`pick_epsp`·`check_result` 변형률·변위) |
| `open_model`(AddModel·SetResult·Draw·핸들) · 컴포넌트 목록·파트 해석 | 요소 선택·요소 id·요소 청크 세트 |
| GetSubcaseList·SetCurrentSubcase·GetSimulationList·GetDataTypeList · `bf_frames` 범위 확인 | frames.csv·model.csv·elems.csv |
| GetContourCtrlHandle · **노드** 선택(`select_part` — 추출과 같은 규칙)·노드 id·노드 청크 세트(`make_chunks`) | 패스 A·B·C·DUMP·F0, 랭킹·후보 프레임, 누적 씬 |
| `bf_resolve`(기존) → 요청 프레임마다 `set_sim` → 노드 청크마다 공용 proc `::esl::bf_chunk`(§2.6) → CloseStack → done.json | |

### 2.3 출력 (`-output` 폴더)
- `bf_<k>.csv`(찾은 종류만, 형식 = `esl_bforce.md` §1 그대로: 벡터 `frame_index,node_id,x,y,z`, 스칼라 `frame_index,node_id,v`, 값 `%.17g`, frame_index = h3d 프레임 번호), `done.json`, `progress.log`. 그 밖 CSV 없음.
- 없는 유형·쿼리 실패 = 실패 아님(type null + reason, 쿼리 실패 종류는 CSV 삭제) — 기존 규칙. 종류를 하나도 못 찾아도 ok true.

### 2.4 done.json (bf 전용, 성공)
```text
{ "ok": true, "h3d": "<h3d>", "mode": "bf_only",
  "part_id": 21, "part_title": "chassis_rear", "part_spec": "chassis_rear", "subcase": "1",
  "n_frames": 61,                       # 서브케이스 전체 프레임 수(같은 h3d 확인용 — §4.3)
  "n_nodes": 194209,                    # 선택된 대상 파트 노드 수
  "node_selection": "component 21", "chunk": 50000, "chunks": {"node": "4 chunks, per_id: id"},
  "frames": [37], "frame_times": [0.037],          # 요청 프레임(오름차순)과 그 시간(sim_time, %.17g)
  "bforce": {"on": true, "frames": [37], "kinds": {"cont": {"type", "comps", "rows"}, "cont2": {"type": null, "reason"}, …}},
  "passes": {"BF": {"frames": [37], "node_chunks": 4, "rows": 388418, "seconds": 41.2}},
  "backup_dir": "...", "steps_done": [...], "api": {...}, "traces": {...}, "env": {...}, "warnings": [...] }
```
- 실패 done.json = 기존 형식(`ok false, code, failed_step, error, errorInfo, steps_done, api, …`) + request 를 읽은 뒤면 `"mode": "bf_only"`.
- 변형률 관련 멤버(strain_source·strain_mode·frames_D·candidate_frames·hot_k …)는 쓰지 않는다.

### 2.5 진행 로그 (`<out>/progress.log`, ASCII — TCL 파일은 ASCII 전용)
```text
extract start: <h3d 이름> -> <out>                                  (기존)
open session and load model/results … / model load start|done (… s) (기존)
bf-only: part <pid> (<title>): <n> nodes, <nsim> frames, frames {<f …>}
bforce: <k> = <type> {<comps>}                                      (기존 문구 재사용)
bf-only frame <f> (<k>/<K>) nodes chunk <c>/<C>
bf-only done (<s> s, <rows> rows)
extract done: bf-only mode (frames {<f …>}), <n> nodes
FAILED at step '<step>': <code>: <msg>                              (기존 실패 줄)
```

### 2.6 공용 proc · 바이트 동일
- 패스 C 의 "노드 청크 1개 × 경계력 종류" 루프(`:1978-1989`)를 공용 proc `::esl::bf_chunk`(upvar 로 파일 핸들·죽은 종류·행 수 갱신)로 빼고 패스 C 와 bf 전용 모드가 같이 쓴다. 패스 C 행 순서(프레임 → 노드 청크 → disp → 종류 순)는 그대로 — **패스 C 출력 바이트 동일**.
- `bf_only` 키가 없거나 0 = 기존 경로 그대로(done.json·CSV 바이트 동일 — V-CI-B1, `tests/io/test_tcl_bforce.py`).
- 파일 머리 주석(request 키 목록·출력 목록)에 bf 전용 모드를 추가한다(ASCII).

---

## 3. 워커 (`worker/esl_worker/bf_ondemand.py` 새 모듈 + `executor.py` 훅)

### 3.1 폴더 · argv
- 작업 폴더 `work = <esl_root>/_h3d/<Case 폴더>/bf_ondemand/`(hw cwd·request.txt) = `core.paths.h3d_work_dir(settings, folder)` + `bf_ondemand`, TCL 출력 `out = work/raw/`. 사용자 입력이 아닌 계산 경로(esl_subdir 안전 규칙).
- 실행 전 `h3d.backup_previous(out)`(기존 함수 — 이전 done.json·CSV·progress.log → `out/_backup/<UTC>/`, 삭제 없음), request.txt 는 덮어씀(H3D_EXTRACT 와 같음).
- argv = 설정 `commands.h3d_extract` 템플릿 그대로(새 템플릿 없음): `hw`=`altair.hw_exe_path`, `extract_tcl`=`default_extract_tcl()`, `h3d`=`case.h3d_path`(읽기만), `request`, `out_dir`=out, `part`=`case.part_title`, `hot_k`=1, `top_n`=1(템플릿 자리 채움 — bf 전용 모드에서 무시). env `ESL_INPUT·ESL_OUTPUT·ESL_PART·ESL_CONFIG` 같음. 치환값 메타문자 거부 규칙 그대로(`localproc.build_argv`).

### 3.2 요청 작성 (순수 함수)
- `bf_ondemand.request_keys(core_settings: dict, frames: list[int]) -> dict[str, str]` = `{"bf_only": "1", "bf_frames": "37", "bf_on": "1", bf_names_<k>…, "bf_vec_comps": …, "scalar_comps": …}` — 이름 후보는 `h3d.bforce_request` 와 같은 함수 결과(설정 `bforce.result_names`·`vec_comps`), `scalar_comps` = `core_adapter.extract_source_settings(...)["scalar_comps"]`. 설정 = **작업 params.settings**(ESL 작업 생성 때 사본 — 재현).
- `h3d.write_request(work/request.txt, part=case.part_title, hot_k=1, top_n=1, extra=keys)`.

### 3.3 hw 실행 (`executor` 공용 세션)
- `_run_h3d` 의 "세마포어 대기 → command 기록 → start → 제한기 부착 → progress.log 옮기기·하트비트·취소·lease → 트리 정리"를 공용 메서드(예 `_hw_session(argv, *, work, out_dir, step_no, wait_s, timeout_s, write_pct, label)`)로 빼고 H3D_EXTRACT(`wait_s=None, timeout_s=None, write_pct=True` — **동작·로그 문구 불변**)와 보충이 같이 쓴다.
- **hw 세마포어**: `jobs_repo.HW_STEP_KEYS` 에 `"ESL"` 추가, `acquire_hw(conn, job, token, ESL step_no, altair.max_concurrent_hw)`. 보충이 끝나면(성공·실패·시간 초과 모두) 새 함수 `jobs_repo.release_hw(conn, job_id, token, step_no)`(step outputs `hw_acquired` false, 다른 키 유지)로 즉시 해제 — 코어 풀이 동안 다른 Case 추출이 hw 를 쓸 수 있다. 평소 ESL step 은 `hw_acquired` 를 쓰지 않으므로 세마포어 수에 들어가지 않는다.
- 대기 한도 `altair.bf_on_demand_wait_s`(0 = 한 번만 시도): 넘으면 hw 를 띄우지 않고 skipped `WAIT`. 대기 중 lease 갱신·취소 확인 계속(기존 `_wait_tick`).
- 제한기: 작업별 제한기 `self.lim`(H3D_EXTRACT 와 같은 `limiter.for_job` — Windows Job Object 우선순위·메모리·CPU 상한·워커 종료 시 강제 종료, POSIX preexec) 그대로. 같은 작업에서 hw → 코어 자식 순 재사용은 CASE_EXTRACT(H3D_EXTRACT → EXTRACT)와 같은 기존 패턴.
- 시간 한도 `altair.bf_on_demand_timeout_s`: hw 시작부터 단조 시계, 넘으면 `h3d.kill_tree`(제한기 포함) → failed `TIMEOUT`. H3D_EXTRACT 는 지금처럼 한도 없음.
- 진행: TCL progress.log 새 줄을 ESL step 로그에 그대로 옮긴다. **step progress_pct 는 쓰지 않는다**(코어 자식 진행률과 섞이지 않게 — 0 유지). 하트비트 문구 §3.5.

### 3.4 평가 (순수 함수)
`bf_ondemand.evaluate(exit_code, out_dir, frames, hw_text) -> (ok: bool, cause: str|None, detail: str, done: dict|None)`
- ok = 종료코드 0 ∧ done.json ok ∧ `mode == "bf_only"` ∧ `bforce` dict ∧ 요청 프레임 ⊂ `bforce.frames`.
- 아니면 cause = `LICENSE`(done.json `error`·`errorInfo` 또는 이번 hw 실행 출력 `hw_text` 에 정규식 `(?i)licen[cs]e` — 추정, 문구에 "의심") | `HW_FAILED`. detail = `h3d.evaluate` 와 같은 요약(종료코드·failed_step·code·error, 300자 이내).

### 3.5 작업 로그 문구 (ESL step 로그, 한 곳 = `bf_ondemand.LOG`)
```text
[esl-worker] 경계력 원자료: 프레임 37 은 01_extract 에 있음 — 보충 안 함                        (판정 4)
[esl-worker] 경계력 원자료 보충 시작: 프레임 37(t=0.037) 이 01_extract 에 없음 → HyperView bf 전용 추출 <h3d> → <out>
[esl-worker] 경계력 원자료 보충: hw 동시 실행 한도 2개(altair.max_concurrent_hw) — 최대 600 s 기다립니다
[esl-worker] argv: [...]                                                                       (기존 형식)
[esl-worker] 경계력 원자료 보충: hw pid 1234 시작, 자원 제한 <applied>, 시간 한도 1800 s
<TCL progress.log 줄 그대로>
[esl-worker] 경계력 원자료 보충 진행 중… 경과 2.1분, 마지막 단계 <step>                           (하트비트)
[esl-worker] 경계력 원자료 보충 완료: 프레임 37, 종류 {cont: Contact Forces, acc: Acceleration}, 212.4 s → 01_extract/bforce.* 병합(프레임 [] + [37])
[esl-worker] 경계력 원자료 보충 실패(TIMEOUT): <detail> — ESL 은 계속(경계력·내력 등급 none, BF_EXTRACT_FAILED)
[esl-worker] 경계력 원자료 보충 생략(HW_UNAVAILABLE): <detail> — ESL 은 계속(BF_EXTRACT_SKIPPED)
```

### 3.6 step outputs · 작업 result · 경고 · 산출물 등록
- 보충 중 ESL step outputs = `{"bf_ondemand": {"state": "running", "frame": f}, "hw_acquired", "pid", "limiter"}` → 끝나면 `{"bf_ondemand": summary}`(hw_acquired false) → 코어 시작 step_update 와 마지막 outputs 에도 `bf_ondemand: summary` 를 함께 쓴다(`_run_core(..., extra_outputs)`).
- summary = `{frame, status: ok|failed|skipped, cause, detail, seconds, kinds: {k: type|null}|null, added: [f]|[], dup: [f]|[]}`; 작업 result `{"bf_ondemand": summary}`(patch_result).
- 작업 경고: 코어 ESL 단계 경고(§5 — `BF_EXTRACT_FAILED: …` 1회)로만 남는다(워커는 같은 문구를 따로 넣지 않음). 예외: 기록 파일 쓰기 실패 = 워커 경고 `BF_ONDEMAND_RECORD_FAILED: …`(이때 코어는 기록을 못 보므로 기존 BF_NO_DATA).
- 산출물 등록: 기록을 남긴 경우(status 무관) ESL 성공 후 rels 에 있는 것만 `01_extract/bforce.npz`·`01_extract/bforce.json`·`01_extract/bforce_ondemand.json` 추가(artifacts upsert — job_id = 이 ESL 작업). 코어가 실패해도 병합된 자료는 남는다(다음 ESL 재사용).

### 3.7 `h3d.bforce_request` CoreError 경고 (C6 수정)
- 서명 `bforce_request(core_settings, warn: list[str] | None = None) -> dict`. CoreError → `warn` 에 `BF_REQUEST_DEFAULTED: 경계력 설정을 읽지 못해 bf 키 없이 추출합니다(bf_on 0 — 경계력·내력 자료 없음): <code>: <message>` 를 넣고 `{}` 반환(추출은 계속 — 기존 동작).
- H3D_EXTRACT(`executor._run_h3d`)는 그 문구를 `[esl-worker] 경고: …` 로 step 로그에 쓰고 작업 경고(`add_warnings`)에 넣는다. 보충 요청 작성에서 같은 오류 = 판정 8(skipped `SETTINGS`).

---

## 4. 병합 (`esl/io/bforce_ondemand.py` 새 독립 IO 모듈)

### 4.1 함수
| 함수 | 입출력 |
|---|---|
| `merge(case_dir, fill_out, frames, *, tag, names) -> dict` | fill_out = `bf_ondemand/raw`. 반환 `{frames_before, frames_after, added, dup, kinds: {k: type\|null}, rows: {k: n}, backup: <case 기준 상대경로>\|null, warnings}`. 오류 = `EslError`(`BF_FILL_OUTPUT` done.json 이 bf 전용 성공이 아님, `BF_FILL_MISMATCH` 같은 h3d 아님) — 이때 01_extract 에 아무것도 쓰지 않음 |
| `record(extract_dir, attempt: dict) -> None` | §4.6 기록 1건 추가(원자적 교체) |
| `note(extract_dir, frame, tag) -> dict \| None` | 이 작업(tag)·이 프레임의 마지막 시도가 failed·skipped 면 `{code, cause, detail}`, 아니면 None |
| `no_types_before(extract_dir, names) -> dict \| None` | 판정 5: status ok·kinds 전부 null·names 가 같은 이전 시도(가장 최근) |
| `bforce_csv.has_frame(extract_dir, frame) -> bool` | §1.3 (bforce_csv 에 추가) |
| `bforce_csv._pack_kinds(results_dir, nid, frames, bfd) -> (kinds_doc, arrays)` | `pack_bforce` 의 CSV → 배열 부분을 공용화(pack_bforce 산출물 **바이트 동일**), merge 가 같이 씀 |

- `names` = `{"result_names": {k: [...]}, "vec_comps": [...], "scalar_comps": [...]}`(워커가 넘김 — 모듈은 설정을 해석하지 않음).

### 4.2 규칙
- **프레임**: frames_after = 기존 `bforce.json frames` ∪ 새 프레임, 오름차순. 기존 npz 에서는 `bforce.json frames` 에 있는 프레임만 읽는다(그 밖 행은 무시).
- **같은 프레임 = 덮어쓰지 않음**: 새 프레임이 이미 있으면 기존 자료 유지(추출 자료 > 먼저 보충한 자료), `dup` 에 넣고 경고. 바꾸려면 다시 추출.
- **노드**: `01_extract/model.npz node_id`(오름차순, model 순서). 대상 파트 밖 노드·모르는 프레임 행 무시, 값 없는 노드 0 + `n_missing` — pack 과 같은 규칙(같은 공용 함수).
- **종류**: 배열 `cont|cont2|acc|fint (D',N,3) f8`, `mass (D',N) f8` — 그 종류 자료가 있는 프레임이 하나라도 있으면 저장(없는 프레임 칸 = 0). json `kinds[k]` = `{type, comps, rows(합), n_missing(합), frames: [그 종류 자료가 있는 프레임]}`(type·comps = 가장 최근 non-null), 어느 프레임에도 없으면 `{type: null, reason}`.
- `frame_data`(기존 읽기 함수)는 `kinds[k].frames` 가 있으면 그 밖 프레임에서 그 종류 = None(키가 없으면 지금처럼 전 프레임 — 비덤프 추출물 동작 불변).

### 4.3 같은 h3d 확인 (MISMATCH)
- 보충 done.json `n_frames` == `01_extract/frames.json n_frames_h3d`, 그리고 요청 프레임 f 의 `frame_times` == `frames.json time_D[frames_D.index(f)]`(둘 다 같은 TCL `sim_time` 의 `%.17g` → **정확히 같음**, 허용오차 상수 없음). 다르면 `BF_FILL_MISMATCH`(예 "h3d 프레임 61 ≠ 추출 60", "프레임 37 시간 0.037 ≠ 0.036").
- 입력 h3d 크기·mtime 은 작업 시작 시 입력 지문으로 이미 확인됨(바뀌면 ESL 작업 자체가 INPUT_CHANGED — 기존).

### 4.4 쓰기 순서 · 백업
1. 새 `bforce.npz`·`bforce.json` 을 같은 폴더 임시 이름(`bforce.npz.tmp-<pid>` 등)으로 쓴다(`savez_stream`).
2. 쓰기 직전 `bforce.json` 을 다시 읽어 프레임 집합이 1단계 기준과 다르면 1단계부터 다시(동시성 방어 — §8).
3. 기존 `bforce.npz`·`bforce.json` 을 `<case>/_backup/<UTC ts>/01_extract/` 로 **이동**(삭제 없음, 이름이 있으면 `.1`… — pipeline `_backup_target` 과 같은 규칙). ts 형식 = pipeline 과 같은 `%Y%m%dT%H%M%S_%fZ` — 형식 문자열은 새 공용 상수 `esl/io/backup.py:BACKUP_TS_FMT`(pipeline 도 이것을 import, 값 동일).
4. `os.replace` 로 npz → json 순 교체(json 의 frames 가 "있음" 판정 기준이라 마지막). 중간 실패 = json 이 옛 프레임 → 다음 ESL 이 다시 보충·병합(남은 tmp 는 무시·덮어씀).
- 종류를 하나도 못 찾으면 npz 없이 json 만(새 프레임 포함 — 같은 프레임 재보충 없음). 기존 npz 가 있었으면 그대로 둔다(옛 프레임 자료).

### 4.5 병합 후 `01_extract/bforce.json` (스키마 문자열 `esl/bforce_extract/1` 그대로, 선택 키 추가)
```text
{ schema: "esl/bforce_extract/1", on: true, frames: [12, 30, 37],
  kinds: {cont: {type: "Contact Forces", comps: ["X","Y","Z"], rows, n_missing, frames: [12, 30, 37]},
          cont2: {type: null, reason: "not in h3d: …"}, …},
  fills: [{frames: [37], job_id: "<ESL 작업>", at: "<UTC>", kinds: {k: type|null}, h3d: "<path>"}] }
```
- `kinds[k].frames`·`fills` 는 보충 병합 때만 생긴다(추출 pack 산출물은 지금과 바이트 동일).

### 4.6 시도 기록 `01_extract/bforce_ondemand.json` (`esl/bforce_ondemand/1`)
```text
{ schema: "esl/bforce_ondemand/1",
  attempts: [ { frame_index: 37, job_id: "<ESL_SOLVE 작업 id = 코어 tag>", status: "ok"|"failed"|"skipped",
                code: null|"BF_EXTRACT_FAILED"|"BF_EXTRACT_SKIPPED", cause: null|"WAIT"|…, detail: "<원인 상세 문구>",
                at: "<UTC>", seconds: 212.4|null, h3d: "<path>", out_dir: "_h3d/<폴더>/bf_ondemand/raw",
                names: {result_names, vec_comps, scalar_comps}, kinds: {k: type|null}|null,
                merge: {added, dup, backup}|null } ] }
```
- 누적(이전 시도 보존) — 교체는 tmp → `os.replace`, 백업 없음(정보가 파일 안에 남음). 쓰는 쪽 = 워커(이 모듈 `record`), 읽는 쪽 = 코어(`note`)·워커(`no_types_before`) — 형식 소유 = 이 모듈 한 곳.

---

## 5. 코어 ESL 단계 (`esl/pipeline.py:_bforce_esl`·`_fint_esl`)

- 선택 프레임 자료가 없을 때(`has_frame` 거짓)만 `bforce_ondemand.note(01_extract, f, ctx.tag)` 를 본다. 기록이 있으면:
  - 요약 `{grade: "none", code: <BF_EXTRACT_FAILED|BF_EXTRACT_SKIPPED>, reason: <문구>}` — **경계력·내력 같은 code·같은 reason**(원인이 같은 원자료).
  - 04_esl 에 bforce·fint 파일을 쓰지 않는다(BF_NO_DATA 와 같은 산출물 집합).
  - 경고 `_bf_text(code, …)`(앞에 `CODE: `) 를 `_bforce_esl` 이 ctx.warnings 에 1번만(내력은 넣지 않음).
- 기록이 없으면 지금 그대로(BF_NO_DATA·FINT_NO_DATA 문구·바이트 동일). bforce.enabled false = BF_DISABLED·FINT_DISABLED 그대로.
- 문구(`_bf_text` 표 한 곳, 요약 reason = `CODE: ` 를 뺀 본문):

| code | 본문 |
|---|---|
| `BF_EXTRACT_FAILED` | `경계력 원자료 보충 실패 — 프레임 {frame}: {detail}. ③ ESL 을 다시 계산하면 다시 시도합니다` |
| `BF_EXTRACT_SKIPPED` | `경계력 원자료 보충 생략 — 프레임 {frame}: {detail}` |

- 원인 상세 `{detail}` 표 = 워커 `bf_ondemand.CAUSE_TEXT` 한 곳(기록에 문구로 저장):

| cause | detail |
|---|---|
| NO_TYPES | `이 h3d 에 경계력·내력 결과 유형 없음(이전 보충 {at} — 이름 후보 bforce.result_names 확인)` |
| H3D_UNREADABLE | `입력 h3d 를 읽을 수 없음({name})` |
| HW_UNAVAILABLE | `서버 HyperWorks 실행 파일 또는 추출 TCL 없음(altair.hw_exe_path)` |
| SETTINGS | `경계력 설정을 읽지 못함({code})` |
| WAIT | `HyperWorks 동시 실행 한도 {limit}개가 {wait:g} s 동안 비지 않음(altair.bf_on_demand_wait_s)` |
| TIMEOUT | `시간 초과 {timeout:g} s(altair.bf_on_demand_timeout_s)` |
| LICENSE | `HyperWorks 라이선스 확인 실패 의심({msg})` |
| HW_FAILED | `HyperView 추출 실패({msg})` |
| MISMATCH | `h3d 가 추출 때와 다름({msg}) — ① 추출부터 다시` |
| MERGE | `01_extract 병합 실패({msg})` |

예: `경계력 원자료 보충 실패 — 프레임 37: 시간 초과 1800 s(altair.bf_on_demand_timeout_s). ③ ESL 을 다시 계산하면 다시 시도합니다`.

## 6. 화면
- **Case ③ 경계력 줄**(`Stage4.tsx:bforceLineText`, `esl-bforce-line`): 등급 none 이고 code 가 있고 `BF_NO_DATA` 가 아니고 reason 이 있으면 `경계력 ESL: 자료 없음 — <reason>`(warn false). 화면에 code 목록·문구 표를 두지 않는다(D-0.24.0-BF-11). BF_NO_DATA 문구·그 밖 분기는 그대로.
- **내력 줄**(`fintLineText`): 지금도 등급 none 이면 `내력 ESL: 자료 없음 — <reason>` — 변경 없음.
- **v0.24.1 출처 탭 사유**: `view3d_src.case_status` 가 요약 code 가 있으면 `reason_text(code, reason)` → 표에 없는 code 는 reason 그대로 — 변경 없음(`unavailText("경계력 ESL", reason)`).
- 작업 진행(JobProgress): 변경 없음 — 보충 줄은 [로그 보기]에 보인다(진행률 표시는 R-BFD-3).

## 7. 01_extract 쓰기 규칙 · 쓰기 금지

| 위치 | 이번 기능의 쓰기 | 규칙 |
|---|---|---|
| `<esl_root>/<Case>/01_extract/bforce.npz`·`bforce.json` | 병합 결과로 교체 | 이전 것 → `<Case>/_backup/<UTC>/01_extract/`(이동, §4.4), tmp → replace |
| `<Case>/01_extract/bforce_ondemand.json` | 시도 기록 누적 | tmp → replace(내용 누적, §4.6) |
| `<Case>/01_extract/` 그 밖(model·disp·strain_frames·frames.json …) | **없음** | 바이트 동일 |
| `<esl_root>/_h3d/<Case 폴더>/bf_ondemand/`(request.txt, raw/) | hw 출력 | raw/ 이전 산출물 → `raw/_backup/<UTC>/`(워커 `backup_previous` + TCL `backup_outputs` 기존 규칙) |
| `<esl_root>/_h3d/<Case 폴더>/raw/`(Case results_dir — 추출 원자료) | **없음** | 추출 산출물 불변 |
| 입력 h3d·rad·include(입력 루트), SPDM | **없음**(h3d 는 `-input` 읽기만) | 쓰기 금지 원칙 |
| `<Case>/04_esl`·`runs/` | 기존 코어·등록 규칙 | 보충 실패면 bforce·fint 파일 없음 |

- **다시 추출**(CASE_EXTRACT): H3D_EXTRACT 는 `_h3d/<폴더>/raw` 만 백업하고, 이어지는 EXTRACT 단계 `ctx.fresh_dir("01_extract")` 가 **01_extract 전체(보충된 bforce.*·bforce_ondemand.json 포함)를 `<Case>/_backup/<UTC>/01_extract/` 로 옮긴다** → 보충분도 함께 백업되고 새 추출부터 다시(덤프면 bforce 없음 → 다음 ESL 때 다시 보충). H3D_EXTRACT 가 실패해 작업이 끝나면 01_extract(보충분 포함)는 그대로 — Case 의 현재 추출과 짝이 맞다. `_h3d/<폴더>/bf_ondemand/` 는 추출이 건드리지 않는다(다음 보충 때 백업 규칙).

## 8. 비용 · 자원 · 동시 실행

| 구간(현장 #82 h3d 기준 추정) | 시간 |
|---|---|
| hw 시작 + 모델 로드 | ≈ 0.5 분(AddModel 28.6 s) |
| 노드 선택·id·노드 청크 세트(요소 쪽 생략) | ≈ 1~2 분(추출 때 요소+노드 2 분 28 초의 일부) |
| 프레임 1개 × 노드 청크 4 × 찾은 종류(현장 2: CONT·ACC / 재해석 최대 5) × ≈ 5 s | ≈ 40 s ~ 100 s |
| **보충 1회(프레임 1개)** | **≈ 3~4 분** + 병합(배열 194k × 종류 — 수 초) |
| 같은 프레임 다시 | 0(재사용) |

- 자원: 작업별 제한기 그대로(H3D_EXTRACT 와 같은 `windows_job`), hw 세마포어 `altair.max_concurrent_hw` 공유(§3.3 — 보충 동안만 1개 차지). 새 시간 한도·대기 한도는 §9 설정.
- 디스크: bf CSV ≈ 노드 194k × ≈ 90 B ≈ 17 MB/종류/프레임(`bf_ondemand/raw`), npz ≈ 4.7 MB/벡터 종류/프레임.
- **동시 실행**: 같은 Case 는 DB 가 막는다 — 같은 종류 비종료 작업 1개(`CASE_JOB_BUSY`) + Case 당 RUNNING 1개(부분 unique `ux_jobs_case_running`) → 같은 Case ESL 중복·ESL 과 재추출이 겹치지 않음 → **파일 잠금을 새로 두지 않는다**. 방어로 병합 직전 bforce.json 재확인(§4.4-2)·같은 프레임 덮어쓰지 않음(§4.2). 다른 Case 는 폴더가 분리되고 hw 세마포어만 공유. 강성 스터디(DOE)는 Case `04_esl`·`runs/` 만 읽는다(01_extract 를 읽지 않음).

## 9. 설정 (하드코딩 금지 — 같은 이름)

| 위치 | 키 | 기본 | 뜻 |
|---|---|---|---|
| 코어 `esl/config.py:BFORCE_DEFAULTS` + 스키마(`_bool`) + `config/esl.example.yaml` `bforce:` 주석 줄 | `bforce.on_demand` | `true` | ③ ESL 때 선택 프레임의 경계력 원자료가 01_extract 에 없으면 h3d 에서 보충(h3d 입력 Case). false = v0.24.1 동작 |
| 플랫폼 pydantic `AltairCfg` + `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml` `altair:` | `bf_on_demand_timeout_s` | `1800`(≥ 60) | 보충 hw 1회 시간 한도(초) |
| 같음 | `bf_on_demand_wait_s` | `600`(≥ 0) | hw 동시 실행 한도 대기 한도(초, 0 = 한 번만 시도) |

- 나눈 이유: `on_demand` 는 결과(등급)를 바꾸는 Case 정책 → 코어 설정(작업 params.settings 사본으로 재현, 선택 절이라 cfg 주입 없음·설정 해시 불변). 시간·대기 한도는 hw 운영값 → `altair.max_concurrent_hw` 옆(워커 설정).
- 코어 `OPTIONAL_KEYS` 는 `bforce.{k}` 로 자동 포함. 설정 거울 시험(V-0242-BFD-10).

## 10. 하위 호환
- 비덤프(v0.24.0 이후 bf_on 1) 추출 Case·이미 프레임이 있는 Case: 판정 4 → hw 호출 0, 01_extract·04_esl·run.json·esl_summary.json **바이트 동일**(시간·태그 제외 기존 기준).
- `bforce.enabled` false: 아무것도 안 함(BF_DISABLED·FINT_DISABLED 그대로). `bforce.on_demand` false·결과 폴더 입력 Case: v0.24.1 그대로.
- 옛 ESL 결과(`runs/<id>`·DB forces·04_esl 스냅샷): 바뀌지 않는다 — 새 ESL 계산 때만 01_extract 를 보충.
- TCL: `bf_only` 없는 request = done.json·CSV 바이트 동일. `pack_bforce` 산출물 바이트 동일(공용화 후). bforce.json 스키마 문자열 불변.
- ESL_SOLVE step 목록·번호, API·스키마(schemas.py ↔ types.ts), 일괄 실행·재시도 경로 불변. 요약 code 값 2개만 추가.
- DB migration 없음(새 테이블·열 없음 — step outputs·작업 result JSON 키, 코드 상수 `HW_STEP_KEYS`).
- 업그레이드 전에 큐에 있던 ESL_SOLVE 도 새 워커가 실행하면 같은 경로(step 이 같으므로).

## 11. 공용 모듈 · 계획 표 · 독립성 (AGENTS.md)
- **공용**: TCL `::esl::bf_chunk`(패스 C·bf 전용), `bforce_csv._pack_kinds`(추출 pack·병합), `executor._hw_session`(H3D_EXTRACT·보충), `h3d.backup_previous`·`write_request`·`build_argv`·`kill_tree`, `limiter.for_job`, `acquire_hw`/`release_hw`, `esl/io/backup.BACKUP_TS_FMT`(pipeline·병합).
- **계획 표**: 판정 표 `bf_ondemand.DECIDE`(행 = 조건 술어·동작·cause — §1.2), 원인 문구 `CAUSE_TEXT`, 로그 문구 `LOG` 각 한 곳. executor 는 판정 결과(action·cause)만 읽고 덤프/비덤프·Case 종류로 분기하지 않는다. 사유 문구 = 코어 `_bf_text` 한 곳.
- **독립성**: `esl/io/bforce_ondemand.py` 는 numpy·`esl.errors`·`esl.io.bforce_csv`·`esl.io.results_csv`(savez_stream 등)·`esl.io.backup` 만 import — `esl.pipeline`·`esl.doe` import 금지, 설정 해석 없음(names 인수). `worker/esl_worker/bf_ondemand.py` 는 DB·프로세스를 다루지 않는 순수 함수(판정·요청·평가·문구) — DB(세마포어·outputs)·hw 실행은 executor, 코어 호출은 `core_adapter` 래퍼(`bforce_has_frame`·`bforce_merge`·`bforce_record`·`bforce_no_types_before`)로 inproc 작업 스레드에서.

## 12. 시험 (V-0242-BFD-n — 실제 HyperWorks 없음)

| id | 내용 | 위치 |
|---|---|---|
| 1 | TCL bf 전용(tclsh + 가짜 hwi `hwmock.tcl`): request `bf_on 1·bf_only 1·bf_frames "f"` → `bf_cont.csv`·`bf_acc.csv`(요청 프레임 행만, 값 %.17g 비트 보존)·done.json(mode bf_only·frames·frame_times·n_frames·bforce kinds, 없는 종류 type null)·progress.log 만, frames/model/elems/strain/disp CSV 없음; hwmock 호출 기록에 요소 선택·변형률 SetDataType 없음 | `tests/io/test_tcl_bforce_only.py`(새) |
| 2 | TCL 검증: bf_only 1 + bf_on 0 = INPUT_INVALID, bf_frames 비거나 중복 = INPUT_INVALID, 범위 밖 = H3D_MISSING_RESULT(실패 done.json mode bf_only) | 같은 파일 |
| 3 | TCL 회귀: bf_only 없음 = 기존 출력 바이트 동일(패스 C bf CSV 포함 — `::esl::bf_chunk` 공용화 전후 비교), 기존 `test_tcl_bforce.py` 그대로 통과 | 같은 파일 + 기존 |
| 4 | 병합: (a) bforce 없음 → 새 json/npz frames [f] (b) 비덤프 D + f∉D → 합집합 오름차순, 기존 프레임 배열 비트 동일, 이전 파일 `_backup/<ts>/01_extract/` 로 이동 (c) f ∈ 기존 → 덮어쓰지 않음·dup (d) 종류 집합이 다름 → kinds[k].frames, `frame_data` 가 그 밖 프레임에서 None (e) n_frames·시간 불일치 → BF_FILL_MISMATCH·아무것도 안 씀 (f) 남은 tmp 무시 (g) record/note: 같은 tag·프레임의 failed 만, no_types_before 이름 일치 | `tests/io/test_bforce_ondemand.py`(새) |
| 5 | 파이프라인: 덤프 방식 합성 추출(bforce 없음) + 보충 병합 → `stage_esl` 경계력 등급 contact(CONT+ACC)·full(CONT+CONT2+MASS), 내력 계산(FINT); 같은 프레임 자료를 비덤프 pack 으로 만든 Case 와 `04_esl/bforce.npz`·`fint.npz` 비트 동일 | `tests/pipeline/test_bforce_ondemand_stage.py`(새) |
| 6 | 파이프라인 실패 기록: note failed → 요약 경계력·내력 code BF_EXTRACT_FAILED·같은 reason, 04_esl 에 bforce·fint 파일 없음, 경고 1건, esl_summary.json 바이트 동일; 기록 없음 → BF_NO_DATA 바이트 동일(v0.24.1) | 같은 파일 |
| 7 | 워커 E2E(가짜 hw `FAKE_HW_MODE` 에 bf 전용 흉내 추가 — request 의 bf_only·bf_frames 를 읽어 `FAKE_HW_BF_SRC` 에서 그 프레임 행만 쓰고 done.json mode bf_only): h3d Case 추출(bforce 없음) → ESL → 가짜 hw 1회(argv `-output …/bf_ondemand/raw`, request bf_only 1·bf_frames t*) → ESL 성공, forces.bforce grade contact, artifacts 01_extract/bforce.* job_id = ESL 작업, step outputs bf_ondemand.status ok | `worker/tests/test_bf_ondemand.py`(새), `backend/tests/h3d_support.py` |
| 8 | 워커 재사용·생략: 같은 프레임 두 번째 ESL = 가짜 hw 호출 0(`bf_ondemand/argv_*.json` 수 불변)·로그 "있음"; 결과 폴더 입력·`on_demand` false·`enabled` false = 호출 0, v0.24.1 요약 그대로; hw_exe 없음 = SKIPPED HW_UNAVAILABLE; 세마포어 점유(max_concurrent_hw 1 을 다른 작업이 잡음) + wait_s 작게 = SKIPPED WAIT | 같은 파일 |
| 9 | 워커 실패: 가짜 hw fail → ESL SUCCEEDED·code BF_EXTRACT_FAILED(HW_FAILED)·내력 같은 code; license 문구 출력 → LICENSE; hang + timeout_s 작게 → 트리 종료·TIMEOUT; 실행 중 취소 → CANCELED·트리 종료·기록 없음; 보충 중 세마포어 수 1 → 끝나면 0(코어 단계 동안 다른 H3D_EXTRACT 가 hw 를 잡음); 기존 `test_h3d_extract.py` 통과(공용 세션 후 동작·로그 불변) | 같은 파일 + 기존 |
| 10 | 워커 CoreError 경고: `core_adapter.bforce_settings` 가 CoreError → H3D_EXTRACT 로그 `[esl-worker] 경고: BF_REQUEST_DEFAULTED…`, 작업 경고 1건, request.txt 에 bf 키 없음, 추출 계속 | `worker/tests/test_bf_ondemand.py` |
| 11 | 회귀 바이트: 비덤프(bf 있음) Case ESL → hw 호출 0, 01_extract·04_esl 해시 v0.24.1 과 같음; 옛 ESL run 스냅샷 불변 | 같은 파일 |
| 12 | 설정 거울: `BFORCE_DEFAULTS.on_demand`·스키마·esl.example.yaml 주석, `AltairCfg.bf_on_demand_timeout_s`·`bf_on_demand_wait_s` = yaml 2개 같은 이름·값, 범위 검증 | `tests/mech/test_bforce.py`(코어 설정 시험 옆)·`backend/tests/test_config.py`(기존 altair 시험 옆) |
| 13 | 화면 vitest: `bforceLineText` code BF_EXTRACT_FAILED·SKIPPED → "경계력 ESL: 자료 없음 — <reason>", BF_NO_DATA 문구 불변, `fintLineText` none → reason 그대로 | `frontend/src/__tests__/esl_v0242.test.tsx`(새) |
| 14 | 현장 확인(수동) | `docs/manual/field_check_v0242.md` |

## 13. 작업 분해 (소유 파일 겹침 없음)

| 묶음 | 내용 | 소유 파일 |
|---|---|---|
| **A** TCL·코어 | §2 bf 전용 모드·`bf_chunk`, §4 병합·기록·has_frame·frame_data, §5 요약 code·문구, §9 코어 키, 시험 1~6·12(코어) | `resources/tcl/esl_h3d_extract.tcl`, `esl/io/bforce_csv.py`, `esl/io/bforce_ondemand.py`(새), `esl/io/backup.py`(새), `esl/pipeline.py`, `esl/config.py`, `config/esl.example.yaml`, `tests/io/fixtures/hwmock.tcl`(호출 기록 추가만), `tests/io/test_tcl_bforce_only.py`(새), `tests/io/test_bforce_ondemand.py`(새), `tests/pipeline/test_bforce_ondemand_stage.py`(새), `tests/mech/test_bforce.py`(설정 시험 추가만) |
| **B** 워커·플랫폼 설정 | §1.2 판정·§3 실행·평가·로그·outputs·등록, §3.7 CoreError 경고, 세마포어 키·해제, §9 플랫폼 키, 시험 7~11·12(플랫폼) | `worker/esl_worker/bf_ondemand.py`(새), `worker/esl_worker/executor.py`, `worker/esl_worker/h3d.py`, `worker/esl_worker/core_adapter.py`, `backend/esl_platform/core/repositories/jobs.py`, `backend/esl_platform/core/config.py`, `config/esl_platform.example.yaml`, `config/esl_platform.prod.example.yaml`, `backend/tests/h3d_support.py`, `worker/tests/test_bf_ondemand.py`(새), `backend/tests/test_config.py`(altair 키 시험 추가만) |
| **C** 화면 | §6 경계력 줄, 시험 13 | `frontend/src/stages/Stage4.tsx`, `frontend/src/__tests__/esl_v0242.test.tsx`(새) |
| (코디네이터) | VERSION·CHANGELOG·통합 시험·현장 문서 결과 칸 | `VERSION`, `CHANGELOG.md`, `docs/manual/field_check_v0242.md` |

- 의존: B 는 A 의 §4.1 함수 서명·§2 done.json 형식을 계약대로 가정하고 병행(통합 시험 7~11 은 A 반영 후). C 는 독립.

## 14. 결정 (decisions.md D-0.24.2-BFD-n)

| ID | 결정 |
|---|---|
| BFD-1 | 원인 = TCL 덤프 경로가 패스 C(경계력) 전에 return. 해결 = 사용자 B안: ESL 때 선택 프레임만 bf 전용 추출 → 01_extract 병합·재사용. 추출 시간·덤프 경로 불변. R-BF-5 를 이 방식으로 닫음 |
| BFD-2 | 보충 위치 = ESL_SOLVE 의 ESL step 안, 코어 자식 시작 전(워커). 새 작업 유형·새 step 없음(step 목록·번호를 쓰는 화면·일괄 실행·재시도·시험 불변, `insert_job(h3d=…)` 호출부 불일치 회피). hw 세마포어 = `HW_STEP_KEYS` + "ESL", 보충 끝나면 `release_hw` |
| BFD-3 | 판정 = 선언형 표 `DECIDE`(enabled ∧ on_demand ∧ h3d 입력 ∧ 프레임 없음 → fill), "있음" = `bforce.json frames`(종류 0 포함), 종류 없음 확인된 h3d·같은 이름 후보면 생략. 덤프/비덤프 분기 없음 |
| BFD-4 | TCL bf 전용 모드 = request `bf_only`·`bf_frames`, 노드 선택·경계력 질의만(변형률·변위·요소·랭킹·덤프 생략), done.json `mode bf_only`·`n_frames`·`frame_times`. 패스 C 경계력 루프 공용 proc(바이트 동일), bf_only 없음 = 바이트 동일 |
| BFD-5 | 병합 = 독립 IO 모듈 `esl/io/bforce_ondemand.py`: 프레임 합집합 오름차순·노드 = model 순서·기존 프레임 우선(덮어쓰지 않음)·종류별 frames 목록, 같은 h3d 확인(n_frames·시간 정확 일치), 이전 파일 Case `_backup` 이동 → tmp → replace(npz → json) |
| BFD-6 | 실패 = ESL 계속: 경계력·내력 등급 none + 같은 code `BF_EXTRACT_FAILED`·`BF_EXTRACT_SKIPPED`·같은 reason, 기록 `01_extract/bforce_ondemand.json`(작업 tag) → 코어가 읽어 요약, 사유 문구 = 코어 `_bf_text`, 원인 상세 = 워커 `CAUSE_TEXT` 각 한 곳. 화면 경계력 줄은 reason 그대로(코드 목록 없음), 출처 탭은 기존 경로 |
| BFD-7 | 설정 = 코어 `bforce.on_demand`(true) + 플랫폼 `altair.bf_on_demand_timeout_s`(1800)·`bf_on_demand_wait_s`(600). 자원 제한 = 작업 제한기 그대로 |
| BFD-8 | 워커 `bforce_request` CoreError = 경고(로그 + 작업 경고 `BF_REQUEST_DEFAULTED`) 후 빈 dict(추출 계속 — 기존 동작) |
| BFD-9 | 하위 호환: DB migration 없음, 옛 ESL 결과 불변, 01_extract 는 보충 때 bforce.*·기록만, 재추출 = 01_extract 전체 백업(보충분 포함), 동시성 = 기존 DB 규칙(파일 잠금 없음) |

## 15. 미결 (결과를 바꾸는 것만 — 기본 가정대로 진행 가능)

1. **보충 대상 범위** — 덤프 방식 Case 뿐 아니라 경계력 자료가 **아예 없는 옛 비덤프 추출**(v0.24.0 이전·bf_on 0) h3d Case 도 ESL 때 보충할지. **기본 가정: 한다**(사용자 확정 2 "덤프·비덤프 공통 규칙"). 결과 변화: 그런 Case 의 새 ESL 이 경계력 none → contact 등. 반대로 정하면 `DECIDE` 에 행 1개("frames.json strain_fallback.mode ≠ dump ∧ bforce.json 없음 → none")만 추가.
2. **hw 대기 한도** — 다른 추출(덤프 85 분 등)이 hw 한도를 모두 잡고 있을 때. **기본 가정: 600 s 기다린 뒤 생략**(BF_EXTRACT_SKIPPED, ESL 은 바로 계속 — 다시 계산하면 재시도). 대안 = 무제한 대기(H3D_EXTRACT 와 같음 — 결과는 항상 채우지만 ESL 이 오래 걸림) = 설정값만 크게.

- 그 밖 기본 가정(결과 불변): 시간 한도 1800 s, 실패 후 다음 ESL 때 재시도(종류 없음 확인만 예외), 보충 중 step 진행률 0 유지.

## 16. 후속 (R-BFD-n)
- R-BFD-1 결과 폴더 입력 Case(PC TCL 추출) 보충 — PC 에서 bf 전용 request 로 실행·업로드하는 경로.
- R-BFD-2 덤프 추출 직후 후보 프레임 D 전체를 bf 전용으로 미리 보충(선택 — 추출 시간 +수 분, 사용자 결정 1 과 달라 별도 결정 필요).
- R-BFD-3 작업 진행 화면에 "경계력 원자료 보충 중(HyperView)" 표시(step outputs `bf_ondemand.state` 사용).
- R-BFD-4 Case `extract_summary.bforce`(결과 유형) 를 보충 결과로 갱신(지금은 추출 때 값 그대로).

## 17. 구현 메모(2026-11-19)

통합(release/v0.24.2)에서 양쪽 인계 파일의 '계약과 다른 점'을 옮긴 표. 본문(§1~16)은 계약 원안 — 아래가 구현 사실이다.

### 17.1 묶음 A(TCL·코어)

| 항목 | 계약 | 구현 |
|---|---|---|
| `merge` 오류 코드 | `BF_FILL_OUTPUT`·`BF_FILL_MISMATCH` | `BF_FILL_MERGE` 추가(01_extract frames.json·model.npz 읽기 실패, 병합 중 bforce.json 이 계속 바뀜). 워커는 `BF_FILL_MISMATCH` = cause MISMATCH, 그 밖 모두 = MERGE(통합 시험 확인) |
| 프레임이 이미 있음(dup 만) | 기존 자료 유지·dup·경고 | 아무것도 쓰지 않고 반환(`added []`, npz·json·백업 없음). 시도 기록은 워커가 남김 |
| 병합 이전 파일 백업 | `_backup/<UTC>/01_extract/` 로 이동 후 replace | 이동 대신 하드 링크(안 되면 복사)로 남기고 tmp → replace — 원래 자리에 늘 완전한 파일(중간 실패 시 옛 자료 유지). 결과 상태는 이동과 같음 |
| `record` 의 `code` | attempt 에 code 포함 | `code` 가 없으면 status 로 정함(failed → BF_EXTRACT_FAILED, skipped → BF_EXTRACT_SKIPPED, ok → null), `at` 없으면 지금. 깨진 기존 기록 파일은 `<Case>/_backup/<UTC>/01_extract/` 로 옮기고 새로 |
| `note` | `note(extract_dir, frame, tag)` | 같음 — `str(job_id) == str(tag)` 비교, tag None = None(워커는 직접 부르지 않음 — 코어 ESL 단계가 부름) |
| `no_types_before` 반환 | "시도" | 가장 최근 ok 시도 dict 전체(`at` 포함 — 워커가 NO_TYPES 문구에 사용). 이름 비교 = 정렬 json |
| TCL request | `bf_on 1`·`bf_only 1`·`bf_frames` | 같음(`bf_frames "37 …"` 공백 구분) |
| done.json | §2.4 | `value_format` 추가. 실패 json 은 기존 형식 + `mode "bf_only"`(`bf_only` 를 읽은 뒤). 범위 밖 프레임 = `failed_step check_frames` |
| 덤프 Case 기록 없음 사유 | BF_NO_DATA 문구 v0.24.1 그대로 | 코드 `BF_NO_DATA`·`FINT_NO_DATA` 유지, reason 만 원인에 맞게: 덤프 방식 = "덤프 방식 추출(변형률 텐서 전 프레임)에는 경계력 결과가 없음 — … 보충(bforce.on_demand)", 병합 뒤 다른 프레임 = "선택 프레임 f 의 경계력 결과가 추출물에 없음(있는 프레임 […])". 비덤프 옛 추출 = v0.24.1 문구 그대로 |

### 17.2 묶음 B·C(워커·플랫폼·화면)

| 항목 | 계약 | 구현 |
|---|---|---|
| DECIDE 행 4a | (표에 없음) | 코어 `has_frame` 가 CoreError = 보충 없이 v0.24.1 동작(hw 0·기록 없음·로그 1줄 `unknown`). 실제 `has_frame` 은 읽기 오류를 False 로 삼키므로 현실에서는 코어 import 실패 때만 |
| 산출물 등록 | 기록을 남기면 rels 에 있는 것만 | 실제 코어 병합에서는 `bforce.npz`·`bforce.json`·`bforce_ondemand.json` 3개가 이 ESL 작업 job_id 로 등록(통합 시험 7). 종류가 0 이면 npz 없이 json 만 |
| hw 평가 ok 조건 | §3.4 | 같음 + 병합 오류 매핑: MISMATCH·MERGE(위 17.1) |
| 시험용 가짜 hw | `FAKE_HW_MODE` 에 bf 전용 흉내 | `FAKE_HW_TCL_DATA` 가 있으면 실제 `esl_h3d_extract.tcl` 을 tclsh + hwmock 으로 실행(`h3d_support.write_tcl_bf_env`) — 출력이 실제 TCL 형식. 없으면 단순 흉내(done.json 에 `n_nodes`·`value_format`·`passes` 추가) |

### 17.3 통합에서 고친 것

| 항목 | 내용 |
|---|---|
| 서명·반환 키·오류 코드 | 어긋남 없음 — 실제 A 함수(`bforce_csv.has_frame`·`bforce_ondemand.merge`·`record`·`no_types_before`)와 B 래퍼·executor·판정이 그대로 맞물림(코드 수정 없음) |
| 통합 시험 7 | `worker/tests/test_bf_ondemand_integration.py`(새): 덤프 Case → ESL → hw 1회(실제 TCL) → 실제 병합·등록 → 경계력 등급 contact·내력 none(사유) → 같은 ESL 재실행 hw 0. 값 비트 동일(%.17g) 확인 |
| 통합 시험 8·9·11 보강 | 실제 TCL 실패(done.json ok false·mode bf_only → HW_FAILED), 라이선스, 시간 초과, 생략(HW_UNAVAILABLE), 프레임 수 다른 h3d(MISMATCH, 01_extract 쓰기 없음), 종류 없음(ok·kinds 전부 null → 다음 ESL hw 0), NO_TYPES 왕복, 행 4a, 비덤프 + 경계력 있음(hw 0·04_esl 바이트가 on_demand false 와 같음), 다시 추출 = 보충분 백업 |
