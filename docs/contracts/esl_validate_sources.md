# 계약: ESL 출처 일반화 — ④ 검증 출처별 독립(P1) · Case 지그 ESL(P2) · 하위 작업 출처 선택(P3) (VAL, v0.24.3 / v0.24.4)

- 상태: **초안 → 구현 기준**(2026-11-20). 브랜치 `release/v0.24.3`(main 4c4753a1 = v0.24.2).
- 버전 분할(§1.2): **v0.24.3 = P1**(④ 검증 출처별 — 전 노드·경계력·내력 + 한계 표시), **v0.24.4 = P2·P3**(Case ③ 지그 ESL·④ 지그 행 · 하위 작업 출처 선택). P2·P3 절은 결정·인터페이스·비용을 고정하고, v0.24.4 착수 때 감사만 갱신해 이 문서 부록에 적는다(새 계약 문서 없음).
- DB migration **없음**(P1·P2·P3) — 새 값은 Case 폴더 파일(`05_val/<dir>/`·`05_val/sources.json`, P2 `04_esl/jig.*`·`01_extract/jig_*`), API 새 경로·선택 인자, 요청·스냅샷 새 선택 키, 설정 선택 키.
- 관계: `esl_disp_primary.md`(검증 지표 정의 §3 — 이 문서는 정의를 바꾸지 않고 출처마다 같은 정의로 적용), `esl_p2_library.md` §7(전 요소 비교), `esl_bforce.md`·`esl_fint.md`(노드 힘 출처·한계), `esl_bforce_ondemand.md` §5(사유 코드), `esl_view3d_sources.md`(출처 키·`SourceTabs`·사유 문구), `esl_jig_rank.md`·`esl_jig_view.md`(지그 계산), `esl_opt_run.md`(비드 최적화 하중). 충돌하면 이 문서 범위에서는 이 문서가 우선.
- ID: 결정 `D-0.24.3-VAL-n`, 시험 `V-0243-VAL-n`(P1)·`V-0244-VAL-n`(P2·P3), 후속 `R-VAL-n`.

### 사용자 요청 (원문, 변경 금지)
1. (2026-11-20) "검증은 전노드 esl만 하는건가?? 각 esl별로도 해야지."
2. (2026-11-20 10:21, 코디네이터 경유 범위 확장) "왜 지그 esl은 계산 안해,? 일단 다 하게 하고 다 검증 하게 하고 사용자가 선택해서 강성스터디 검토를 하던 비드최적화든 하지"

---

## 0. 감사 (v0.24.2 = 4c4753a1, 읽기만)

### 0.1 검증 항목 × 출처 (✓ 있음 · △ 다른 정의로 일부 · ✗ 없음 · – 해당 없음)

| 검증 항목 | 전 노드 `full` | 경계력 `bforce` | 내력 `fint` | 지그 `jig` |
|---|---|---|---|---|
| 응답 풀이 u_val(3-2-1) | ✓ `pipeline.py:1629` `sm.solve(F, spc)` — S5 rtol ≤ 1e-12(:1628), 6자유도·반력 R | △ ESL 단계 재현 `_nodal_recon` `:1221` — ESL rtol(설정값), **Kabsch 제거 3성분만 저장**(`:1222`·`:1300` bforce.npz `u_val`), 반력 벡터 미저장 | △ 같음(`:1387`·`:1394` fint.npz) | ✗ Case 산출 없음(`view3d_src.py:26-28` V3D_STUDY_ONLY, 스터디 `stages.py:3806-3940` 만) |
| 판정 4지표 disp_rms·disp_max·reaction·disp_noise | ✓ `:1631-1640`·`:1711-1712`, 판정 `:1766-1776` | ✗ ESL 재현 = MAC·umax_err 만(`mech/bforce.py:215-229`), 미달 = 경고 `BF_RECON_POOR`(`:1224-1232`) | ✗ 같음(`FINT_RECON_POOR`) | ✗ |
| 반력 정의 | ✓ `reaction_rel` = Σ‖R‖/Σ‖F‖(`:1638`), `reaction_sum_rel` = ‖ΣR‖/Σ‖F‖(`:1639`, info) | △ ESL `recon.reaction_rel` = **‖ΣR‖/Σ‖F‖**(`bforce.py:226`) — 이름은 같고 검증의 `reaction_sum_rel` 정의 | △ 같음 | ✗ |
| 강체 제거 | ✓ 양쪽 `remove_linear_rigid`(`:1631-1632`, `kabsch.py:86-91` — 선형 해의 미소 회전에 정확) | △ u_val 만 `remove_rigid`(Kabsch 유한 회전), u_rel 은 S3 Kabsch 그대로 | △ 같음 | ✗ |
| 변형률 참고(hotspot1·field max·P90·초과 요소·소성) | ✓ `:1641`·`:1657-1698`·`:1753-1764` | ✗ | ✗ | ✗ |
| hotspot 표 · 제외 요소 | ✓ `:1664-1677`(제외 = Radioss 쪽만 — 출처 무관 값) | ✗ | ✗ | ✗ |
| 전 요소 비교 field·단면 `compare_field.npz` | ✓ `_field_compare` `:1496-1599`, `:1788` | ✗ | ✗ | ✗ |
| `compare_disp.npz`·`compare.csv`·`validation.csv` | ✓ `:1789-1796` | ✗ | ✗ | ✗ |
| DB 행·이력 | ✓ `register.py:225-277` → `validations`(`tables.py:296-324`), 화면 이력 `Stage5.tsx:361-388` | ✗ | ✗ | ✗ |
| API | ✓ `/validations/{vid}`·`/field`·`/disp-field`·`/section`(`routers/results.py:162-207`, `services/results.py:60-312`) | ✗ | ✗ | ✗ |
| 화면 ④ | ✓ `Stage5.tsx:225-388`(판정·변위·변형률·hotspot·제외·이력) | ✗(③ `esl-bforce-line` 숫자 한 줄 — `Stage4.tsx:42`) | ✗(`esl-fint-line` `:79`) | ✗ |
| 07_report | ✓ 5절 `case_report.py:319-369` | ✗ | ✗ | ✗ |
| 06_export | ✓ F_eq·validation.csv(`pipeline.py:1854-1945`) | ✗(R-BF-2) | ✗ | ✗ |
| ③ 3D 응답(v0.24.1) | 05_val `compare_disp` d_val·d_rel, rigid linear(`view3d_src.py:29-32`) | ESL `u_val`, rigid kabsch(`:33-36`) | 같음(`:37-40`) | 비활성 |

### 0.2 지그 ESL 계산 감사 (P2 근거)

| 항목 | 지금 | 근거 |
|---|---|---|
| 계산 위치 | 강성 스터디 준비만(`stages._jig_baseline` → `prep/jig.json`·`jig.npz`), 기준 메시·목표 = `prep/sm_ref`(전 노드 ESL 응답), 모든 엔트리가 **같은 지그·같은 기저** | `stages.py:3806-3940`, D-0.23.0-JIG-7 |
| 순수 계산 | `esl/doe/jig.py` — 이미 독립(import = numpy·scipy·`esl.errors`·`esl.mech.*`)이지만 **`esl.doe` 패키지 안** | `jig.py:1-28` |
| tie(지그) 노드 | paicad `shell fixed-scan`(워커 BD_GEOM, `prep/assem_full` 사본 또는 Case 폴더 제자리) → `paicad_io.read_fixed`(`FIXED_KINDS` 비트) | `doe_jobs.py:476-492`, `paicad_io.py:20`(esl.doe import)·`:42`·`:339` |
| deck 표면(가압 후보) | `jig_surf.other_surfaces(rad, part, box)` — Case starter rad 읽기만, `esl.doe.assem_full`(ELEM_NODES·_faces·_clean) import | `jig_surf.py:18`·`:105-218`, `stages.py:3697-3740`, `assem_full.py:449-503` |
| 누적 씬 | deck 파서 `_Deck.scan` 이 상태 파일(.str/.sta) include 를 같은 좌표 우선 규칙으로 읽음(Case model.npz 와 같은 규칙) | `rad/parser.py:442-551` |
| 비용(현장) | deck 표면 **493만 삼각형·≈ 84 s 재읽기**(코디네이터 전달 v0.23.x 실측 — 이 저장소 문서에는 기록 없음), eigsh 수십 초~분(R-JIG-12), 기저 열 ≤ max_regions 8 × 3 + 체적력 3 + 모드 4 ≈ 31 해, 지그 분해 1(3-2-1 과 다른 구속) | `esl_jig_rank.md:433-439`, `doe/__init__.py:94-100` |

### 0.3 하위 작업이 쓰는 하중 (P3 근거)

| 소비자 | 쓰는 하중 | 근거 |
|---|---|---|
| 라이브러리 항목 | `raw.npz` `f` = **F_eq(전 노드)만**, 등록 게이트 = 전 노드 판정 PASS(422 VALIDATION_NOT_PASS), 하위 작업 게이트 = 같은 판정(422 ENTRY_NOT_ELIGIBLE) | `library/entry.py:32-33`·`:134-151`, `services/library.py:5-8`·`:195-200`·`:395-400` |
| 강성 스터디 | 네 출처 탭(v0.23.3~v0.24.1): full = 엔트리 F_eq, jig = 스터디 자체 지그, bforce·fint = **엔트리 Case 의 04_esl 에서 찾음**(`_ns_find`), 주 지표 = `rank.metric`(기본 jig, D-0.23.0-JIG-8) → `metric_effective` | `stages.py:4079-4091`(RANK_SOURCES)·`:4446`·`:4503` |
| 비드 최적화 | S1 = 엔트리 `raw["f"]`(F_eq) 노드 직접, S2 = summary 셀 매핑(F_eq 에서 만든 셀 합력), 지지 = 3-2-1 `auto_supports` | `opt/target.py:97`·`:188-213`, `esl_opt_run.md` OR-D-14 |
| 06_export | F_eq·3-2-1 | `pipeline.py:1874-1936` |
| 요청 키 | 스터디 `DoeCheckIn`·비드 최적화 `OptRunIn` 에 하중 출처 키 없음 | `schemas.py:1519-1527`·`:1765-1784` |

### 0.4 결론

검증은 전 노드 ESL 만 한다. 경계력·내력은 ESL 단계 재현(MAC·umax_err·다른 정의의 reaction_rel)만 있고, 저장 응답은 Kabsch 제거 3성분이라 검증 지표(선형 강체 제거·6자유도 변형률·반력 벡터)를 그대로 만들 수 없다. 지그 ESL 은 Case 에 없다. 하위 작업은 비드 최적화·라이브러리·내보내기가 F_eq 만 쓰고, 출처 선택 키가 없다.

---

## 1. 목표 · 범위 · 단계

### 1.1 목표

1. Case ④ 검증의 **모든 항목**(판정 변위 4지표·반력·변형률 참고·hotspot·field·제외 요소·이력·compare_disp)을 **출처마다 같은 정의·같은 기준값**으로 독립 수행·표시(P1). 출처 차이는 계획 표 `VAL_PLAN`(§2)의 열로만 — 출처 이름 분기 금지(AGENTS.md).
2. Case ③ ESL 이 네 출처(지그 포함)를 모두 계산하고(P2), ④ 가 네 출처를 모두 검증(P1 + P2 행).
3. 사용자가 검증 결과를 보고 하위 작업(강성 스터디·비드 최적화)에 쓸 출처를 고른다(P3) — 공통 요청·스냅샷 키 하나.
4. '비교용 아님'(tie 누락 등) 한계를 판정 옆에 같은 방식으로 보이고 선택 정책과 잇는다(§10, P1 표시·P3 선택).

### 1.2 단계 · 버전 분할

| 단계 | 내용 | 버전 | 선행 | 근거 |
|---|---|---|---|---|
| **P1** | ④ 검증 출처별(full·bforce·fint, jig 행은 계획 표에 자리만 — 비활성 사유), 한계 표시, API·화면·07_report 표 | **v0.24.3** | 없음 | 사용자 요청 1. 코어 검증·API·화면만 — 새 외부 도구 없음, 위험 작음 |
| **P2** | Case ③ ESL 지그 산출(공용 모듈 이동·워커 tie 준비·04_esl/jig.*), ③ 3D jig 탭 활성, ④ jig 행 활성 | **v0.24.4** | P1(검증 계획 표·지지 집합 묶음) | 요청 2 "다 하게". paicad·deck 읽기·모듈 이동이 커서 분리 |
| **P3** | 하위 작업 출처 선택 `load_source`(스터디·비드 최적화), 경고 정책 | **v0.24.4** | P1(출처 판정), P2(비드 최적화 jig) | 요청 2 "사용자가 선택". 시간이 모자라면 P3 의 비드 최적화 jig 만 R-VAL-6 으로 |

---

## 2. 출처 표 · 계획 표 `esl/val_src.VAL_PLAN` (새 모듈 — 선언 + 순수 함수만)

- 키·순서 = `esl/view3d_src.KEYS`(`jig`·`full`·`bforce`·`fint`)를 **import** — 셋(RANK_SOURCES·CASE_PLAN·SOURCE_ROWS)과 같음을 시험이 확인. 화면 이름 = `frontend/src/view3d/sources.ts:SOURCE_ROWS` 한 곳.
- `CASE_PLAN` 에 검증 열을 더하지 않는다(D-0.24.3-VAL-2): CASE_PLAN 열(dir·recon_dir·fallback·resp_na)은 3D 캐시·표시용이고 검증은 계산 열이 다르다. v0.24.1 표·시험(V-0241-V3D-4·5)은 바이트 그대로.
- 모든 행이 모든 열을 가진다(누락 = `CONFIG_INVALID`, 값 `None` = "이 출처에 없음"). `check_plan()` 이 import 때 검사: 열·키 순서·legacy 정확히 1행·`dir` 유일·`rigid` 전부 `linear`·`support` ∈ SUPPORTS·`reaction_role` ∈ {judge, info}.

### 2.1 열

| 열 | 뜻 | 호출부가 고르는 것 |
|---|---|---|
| `key` | 출처 키 | – |
| `legacy` | `True` = 05_val **루트**·DB 행·라이브러리 게이트·06_export·07_report 5절 기준(정확히 1행) | 쓰기 위치·DB 매핑 |
| `load` | 하중 `(위치, 파일, 배열)` — 위치 `esl` = Case `04_esl` | 하중 읽기 |
| `required` | load 가 없으면 단계 실패(`PREREQUISITE_MISSING` — 지금 `_require`) | 실패/비활성 |
| `load_frame` | 하중 기준 프레임 코드(표시·보고용 — 계산 분기 없음, §3.2) | 문구 |
| `balance` | 균형 방식: 고정 코드(`"self"` 구성상 자기평형 · `"jig"` 지그 지지가 받음) 또는 진단 json 안 키 경로(적용된 값을 읽음) | 문구 |
| `support` | 지지 집합 코드: `bc321` = `03_bc/support.json` 3-2-1, `jig` = `04_esl/jig.npz` 지그 노드 123(P2) | spc 함수 표 `SUPPORT_FN` |
| `reaction_role` | 반력 지표 역할: `judge`(정정 지지 — 반력 = 하중 불평형) \| `info`(과잉 구속 — 반력 = 지지력, §3.3) | 지표 role |
| `target` | 목표 변위 `(위치, 파일, 배열)` | – |
| `rigid` | 비교 강체 제거 규칙 — 전부 `linear`(§3.1) | – |
| `resp` | 응답 출처 — 전부 `solve`(검증 단계 풀이, D-0.24.3-VAL-3) | – |
| `fallback` | 전체 풀이를 못 할 때 변형률 참고용 변위: `u_rel_condensed`(지금 full 동작 `:1653`) \| `None`(변형률 참고도 생략) | 판정 불가 분기 |
| `noise_force` | S4 `noise.force_rel`(하중이 u_rel 에서 나온 출처만 의미) 기록 여부 | info 값 |
| `summary` | ESL 실행 요약 `forces.<summary>` 키(사유 code·reason) | 사유 |
| `doc` | 진단 json `(위치, 파일)`(사유·균형·한계) | 사유·한계 |
| `limits` | 진단 json 안 한계 코드 목록 키 경로 | 한계(§10) |
| `dir` | `05_val` 아래 폴더(`""` = 루트) | 쓰기 위치 |
| `na` | 기본 불가 사유 코드(요약·진단 code 가 있으면 그것 우선) | 사유 |
| `note` | 변위 비교 설명 코드(`NOTE_TEXT`) | 화면 문구 |

### 2.2 행 (P1 값 — P2 에서 jig 행만 채움)

| key | legacy | load | required | load_frame | balance | support | reaction_role | target | fallback | noise_force | summary | doc | limits | dir | na | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `jig` (P1) | F | None | F | None | None | None | None | None | None | F | None | None | None | None | `V3D_STUDY_ONLY` | None |
| `jig` (P2) | F | esl `jig.npz` f | F | `ref_basis` | `"jig"` | `jig` | `info` | esl `u_rel.npz` u_rel | None | F | `jig` | esl `jig.json` | `("limits",)` | `jig` | `JIG_NOT_RUN` | `VAL_NOTE_RECON` |
| `full` | **T** | esl `f_eq.npz` f | **T** | `ref_k0` | `"self"` | `bc321` | `judge` | esl `u_rel.npz` u_rel | `u_rel_condensed` | **T** | None | None | None | `""` | `PREREQUISITE_MISSING` | `VAL_NOTE_CONSISTENCY` |
| `bforce` | F | esl `bforce.npz` f | F | `ref_rot` | `("balance",)` | `bc321` | `judge` | esl `u_rel.npz` u_rel | None | F | `bforce` | esl `bforce.json` | `("limits",)` | `bforce` | `V3D_SRC_NOT_RUN` | `VAL_NOTE_RECON` |
| `fint` | F | esl `fint.npz` f | F | `ref_rot` | `("fint","balance_applied")` | `bc321` | `judge` | esl `u_rel.npz` u_rel | None | F | `fint` | esl `fint.json` | `("limits",)` | `fint` | `V3D_SRC_NOT_RUN` | `VAL_NOTE_RECON` |

- `bforce.npz` f = F_bal(관성 이완 후 기준 형상 하중, ESL 재현에 쓴 그 하중), `fint.npz` f = F_bal(균형 기본 none = F_ref 그대로) — `pipeline.py:1297`·`:1391`.
- 문구 표(한 곳 = `val_src`): `LOAD_FRAME_TEXT = {ref_k0: "기준 형상 F = K₀·u_rel", ref_rot: "기준 형상 F_ref = Rᵀ·F(낙하 프레임 → S3 Kabsch R)", ref_basis: "기준 형상 F = Σ a_k·기저(지그 맞춤)"}`, `BALANCE_TEXT = {self: "자기평형(구성상)", jig: "지그 지지(tie 노드 123)가 받음", inertia_relief: "관성 이완", none: "균형 보정 없음 — 불평형은 지지 반력으로"}`, `NOTE_TEXT = {VAL_NOTE_CONSISTENCY: "ESL 재해석 변위와 Radioss 변위의 차이 — 계산·경계조건·저장 정밀도의 수치 일관성을 봅니다(물리적 차이가 아닙니다)."(**지금 화면 문구 그대로** `Stage5.tsx:261`), VAL_NOTE_RECON: "이 하중으로 정적 풀이한 변위와 Radioss 변위(강체 제거)의 차이 — 하중이 낙하 변형을 얼마나 재현하는지(물리 차이 포함)를 봅니다."}`. 조건 한 줄 `cond_text` = `"하중 <load_frame> · 지지 <support> · 균형 <balance> · 목표 u_rel(S3 Kabsch) · 응답 = 검증 풀이"`.

### 2.3 상태 · 사유 코드

행 상태 `status` ∈ `done`(검증함 — 판정 PASS·FAIL·UNDETERMINED) · `unavailable`(하중 자료 없음) · `failed`(검증 계산 예외) · `disabled`(설정 끔) · `na`(계획 load None).

| 코드 | 상태 | 문구(사유 부분) 원본 |
|---|---|---|
| `V3D_STUDY_ONLY`·`V3D_SRC_NOT_RUN`·`BF_DISABLED`·`FINT_DISABLED` | na·unavailable | `view3d_src.REASON_TEXT`(재사용 — `reason_text()` 호출) |
| `BF_NO_DATA`·`FINT_NO_DATA`·`BF_FAILED`·`FINT_FAILED`·`BF_EXTRACT_FAILED`·`BF_EXTRACT_SKIPPED` | unavailable | ESL 요약·진단 json 의 `reason` 그대로(v0.24.1 §2.5·v0.24.2 §5 규칙) |
| `VAL_SRC_NOT_RUN`(새) | (백엔드 — sources.json 없음) | "이 검증에는 출처별 결과가 없습니다(v0.24.3 이전 검증) — ④ 검증을 다시 실행하면 생깁니다" |
| `VAL_SRC_FAILED`(새) | failed | "출처 검증 계산 실패(<오류 코드·메시지 ≤ 300자>) — 다른 출처 결과는 그대로" |
| `VAL_SRC_DISABLED`(새) | disabled | "설정에서 꺼짐(validation.sources.enabled)" |
| `VALIDATION_FILES_GONE`(기존 오류 코드 재사용) | (백엔드) | 기존 문구 "이 검증의 산출물이 이후 검증으로 바뀌었습니다(같은 ESL 결과로 다시 검증)" |
| `JIG_NOT_RUN`(새, P2)·`JIG_DISABLED`·`JIG_NO_TIE`·`JIG_FAILED`·`JIG_FIXED_FAILED`·`JIG_FIXED_SKIPPED`(P2) | unavailable | `JIG_NOT_RUN` = "이 ESL 결과에는 지그 ESL 이 없습니다(v0.24.4 이전 계산) — ③ ESL 을 다시 계산하면 생깁니다", 나머지 = ESL 요약 reason 그대로 |

새 문구는 `val_src.REASON_TEXT` 한 곳(형식 `unavailText(label, reason)` 공용, v0.24.1).

---

## 3. 공통 정의 (출처 무관 — `esl_disp_primary.md` §3 정의를 그대로 출처마다)

### 3.1 기호 · 지표

- 목표 = S3 `u_rel`(`04_esl/u_rel.npz`, 전 노드 Kabsch 강체 제거) — **모든 출처 같은 목표**. U = max_i ‖u_rel,i‖(모든 출처 같은 분모).
- 응답 `u_val^s` (N,6), 반력 `R^s` = `solve(F^s, spc^s)`(검증 단계, §4.1). `d_val^s = remove_linear_rigid(X0, u_val^s[:, :3])`, `d_rel = remove_linear_rigid(X0, u_rel)` — **양쪽 독립 선형 강체 제거**(지금 full 규칙). 근거: 응답은 선형 해라 강체 성분이 미소 회전이고(`kabsch.py:86-91` — Kabsch 는 O(ω²L) 잔차), 목표와 응답에 같은 연산을 해야 출처 간 수치가 같은 잣대.
- 판정(role judge): `disp_rms_rel^s = √(mean‖d_val^s − d_rel‖²)/U`, `disp_max_rel^s = max‖·‖/U`, `reaction_rel^s = Σ_s‖R^s‖/Σ_i‖F^s_i‖`(계획 열 reaction_role = judge 일 때만 판정), `disp_noise_rel = δ/U`(출처 무관 — 같은 값).
- 참고(role reference): `hotspot1_strain_rel_err`·`field_max_err_pct`·`field_p90_err_pct`·`noise_hotspot_strain_rel` — ε_val^s = `strains(u_val^s)` 막 변형률(extract.layers), ε_rad·상승 마스크·valid·제외 = Radioss 쪽(출처 무관 — 한 번 계산해 출처마다 같은 값).
- 정보(role info): `reaction_sum_rel^s = ‖ΣR^s‖/Σ‖F^s‖`, `u_rel_linear_rigid_rel`(목표만 — 같은 값), `noise_force_rel`(계획 열 noise_force 참인 출처만, 아니면 null).
- 변위 전 노드 분석(`_field.disp_analysis`)·단면(w_val^s)·`compare.csv` = 출처의 d_val^s·d_rel.

### 3.2 하중 기준 프레임 — 왜 계산 분기가 없나

full F = K₀·u_rel(기준 형상 X0 에서 만든 응축 하중), bforce·fint F_ref = Rᵀ·F_def(낙하 변형 프레임 힘을 **u_rel 을 만든 같은 S3 Kabsch R** 로 기준 형상에 돌린 것 — `esl_bforce.md` D-0.24.0-BF-3), jig(P2) F = 기준 형상 지그 기저 합. 즉 **모든 하중이 X0·K₀ 공간에 있고 목표 u_rel 도 같은 공간** → 같은 풀이·같은 비교로 공정하다. `load_frame` 열은 이 사실을 표·보고서에 밝히는 문구용이다.

### 3.3 반력 역할 (`reaction_role`)

3-2-1 은 정정 지지라 반력 = 하중 불평형의 척도(자기평형이면 ≈ 0) → judge. 지그(tie 노드 123, 수천 노드)는 과잉 구속이라 반력 = 부품을 붙잡는 지지력(물리량, 0 이 아님) → info(값·기준 표시, 판정·fail_reasons 제외, 판정 = 변위 3지표). 열 값으로 role 을 고른다(출처 이름 분기 없음). 미결 Q1(§17) = 균형 none 출처(fint 기본)의 반력 판정.

### 3.4 ESL 단계 재현과의 관계 (정의 충돌 정리)

ESL 단계 `bforce.json`·`fint.json` 의 `recon`(MAC·umax_err·`reaction_rel` = ‖ΣR‖/Σ‖F‖)은 **진단으로 그대로 둔다**(계산·파일 불변). 검증의 `reaction_rel` 은 Σ‖R‖/Σ‖F‖ 이고, ESL `recon.reaction_rel` 과 같은 정의는 검증의 `reaction_sum_rel` 이다(시험 V-0243-VAL-3 이 직접법에서 두 값 일치를 확인). 화면·보고서 문구는 검증 쪽 이름만 쓴다.

---

## 4. 핵심 결정 (근거)

### 4.1 ① 응답 = 검증 단계에서 같은 함수로 다시 풀이 (ESL u_val 재사용 안 함)

| 대안 | 비용(현장 194,233 노드·193,362 요소) | 일관성 | 판정 |
|---|---|---|---|
| ESL 단계 `u_val` 재사용 | 풀이 0 | ✗ Kabsch 제거 3성분만(선형 제거·6자유도 변형률 불가), 반력 벡터 없음, ESL rtol(반복법이면 S5 ≤ 1e-12 아님), v0.24.0 이전·재현 생략 Case 없음 | 안 함 |
| 출처마다 `sm.solve` | 분해 × 출처 수(직접법 분해가 지배) | ✓ | 안 함 |
| **지지 집합마다 분해 1회 + 출처마다 해 1회**(채택) | 3-2-1 묶음(full·bforce·fint) = 지금과 같은 분해 1회 + 해 2회 추가, jig(P2) = 분해 1회 추가 | ✓ 같은 K₀·같은 spc·같은 rtol(S5)·같은 강체 제거·같은 변형률 함수 | **채택** |

- 구현: `h = sm.factorize(spc)` 를 계획 열 `support` 값마다 1회(`SUPPORT_FN[support](ctx, model)` → spc), 묶음 안 첫 해 = legacy 행(full). `FactorizedSolve.solve` 는 `ShellModel.solve` 와 같은 산술(같은 분해·반복 개선 1회·같은 잔차·반력 식 — `shell.py:819-885` vs `:964-1006`) → full 결과 비트 동일(골든 V-0243-VAL-1 이 확인). 해를 모두 낸 뒤 `del h`(분해 메모리 = 지금 피크 그대로, 추가는 해 배열 194k×6×8 B ≈ 9 MB/출처).
- `full_solve_decision`(`:1448-1464`)은 **한 번** — 같은 K 크기라 메모리 판단이 같다. 생략이면 모든 출처 `UNDETERMINED(NO_FULL_SOLVE)`(full 은 지금처럼 fallback 변형률 참고, 나머지는 fallback None → 변형률 참고도 생략).
- 합성 측정(이 계약 작성 때, 2코어·SuperLU, 평판 32,761 노드·32,400 요소, `/tmp/bench_v0243` — 저장소 밖): K 조립 1.70 s, **분해 13.93 s**, 해 0.38 s·0.37 s(반복 개선 포함), 변형률 회복 1.01 s. 194k 노드 외삽(분해 ~N^1.5, 해·변형률 ~N): 분해 ≈ 200 s, 해 ≈ 2.5 s, 변형률 ≈ 6 s → 출처당 추가 ≈ 15~30 s(비교·npz 압축 포함 추정), 검증 전체 **+≈ 10~25 %**(P1, 출처 2개). 반복법(CG)은 출처마다 반복 전체라 출처당 ≈ full 해 시간. P2 jig = 분해 1회 추가(≈ 지금 검증 분해만큼). 현장 실측은 `sources.json solve`·run.json `elapsed_s` 로 확인(완료 기준).

### 4.2 ② 목표·강체 제거 공통 정의

§3.1·§3.2. full 의 "u_rel 선형 강체 제거"와 bforce·fint 의 "파트 Kabsch 회전(Rᵀ) 기준"은 서로 다른 단계의 다른 것이다: Rᵀ 는 **하중을 기준 형상으로 돌리는 것**(ESL 단계에서 이미 끝남, 목표 u_rel 과 같은 R), 강체 제거는 **비교 직전 응답·목표에서 미소 강체를 빼는 것**. 그래서 출처별 기준 프레임 열(`load_frame`)은 문구만, 비교 규칙은 하나(`rigid` 전부 linear — `check_plan` 이 강제).

### 4.3 ③ 판정 기준값 공통 (설정 한 벌)

`validation.*`·`compare.*` 를 모든 출처에 그대로(출처별 기준 키 없음). `criteria` 사전도 같은 값 — 출처 문서에만 `criteria.reaction_role`(judge|info) 키를 더해 화면이 반력 칸을 판정/정보로 그린다(full 문서는 키 없음 = judge, 바이트 불변).

### 4.4 ④ 자료 없는 출처 = 비활성 + 사유

하중 파일·배열 없음(또는 node_id 불일치 = failed) → 행 `unavailable`, code·reason = 진단 json code(있으면) → ESL 요약 `forces.<summary>` code·reason → 행 `na` 순(§2.3, v0.24.1 `case_status` 와 같은 우선순위 — 순수 함수 `val_src.row_status`). 05_val/<dir>/ 를 만들지 않는다. 화면 탭 비활성 + `unavailText`.

### 4.5 ⑤ 산출물 위치 · 하위 소비

- **full = 05_val 루트, 바이트 동일**(validation.json `created_at` 제외·validation.csv·compare.csv·compare_field.npz·compare_disp.npz). 출처 = `05_val/<dir>/` 에 **같은 파일 세트·같은 스키마**(`esl/validation/3` + 끝에 `src` 블록 §6.3), 인덱스 `05_val/sources.json`(마지막에 씀).
- DB 행·라이브러리 등록 게이트·재검증 전환·06_export·07_report 5절 기존 내용 = **full 그대로**.
- 07_report: 5절 끝에 **출처별 판정 요약 표 1개 추가**(sources.json 이 있을 때만 — 없으면 HTML 이 생성 시각·버전 외 v0.24.2 와 같음). 근거: 보고서가 공유 산출물이라 출처 비교가 남아야 하고, 표 1개라 기존 절을 바꾸지 않음.
- 06_export 경계력·내력·지그 하중 내보내기 = **후속 R-VAL-1**(R-BF-2 와 합침) — 근거: 내보내기는 라이브러리 경로(EXPORT origin library)와 ID 계획을 같이 바꿔야 하고, 하위 작업 선택(P3)이 먼저 정해져야 어떤 출처를 내보낼지 정해진다.

---

## 5. 공용 모듈 · 독립성

| 모듈 | 내용 | 규칙 |
|---|---|---|
| `esl/val_src.py`(새) | `VAL_PLAN`·`COLUMNS`·`SUPPORTS`·`check_plan()`·`plan(key)`(모르는 키 → `EslError("SOURCE_NOT_FOUND")`)·`legacy_key()`·`row_status(row, have_load, doc, summary) -> {status, code, reason}`·`REASON_TEXT`·`LOAD_FRAME_TEXT`·`BALANCE_TEXT`·`NOTE_TEXT`·`cond_text(row, doc)`·`LIMIT_CLASS`·`limit_info(codes) -> {limits, limit_text, comparable}` | 선언 + 순수 함수. import 허용 = `esl.errors`·`esl.view3d_src`(KEYS·reason_text)·`esl.mech.bforce`(LIMIT_TEXT 만) |
| `esl/val_metrics.py`(새) | 검증 지표 계산을 출처 무관 순수 함수로(§5.1) | 파일 IO·설정 해석·`ctx.warnings` 없음, 값은 인수. import 허용 = numpy·`esl.errors`·`esl.mech.kabsch`·`esl.report.field`(순수) |
| `esl/pipeline.py` | `stage_validate` = IO(파일·설정·경고)·계획 열 읽기·순서·쓰기만. `_field_compare` 를 Radioss 쪽 `_field_base(ctx, model, frame_index, eps_rad)`(IO·경고 1회)와 순수 `val_metrics.field_compare` 로 나눔 | full 산출 바이트 불변 |
| `worker/esl_worker/core_adapter.py` | `val_src_plan()`(행·문구 사본)·`val_row_status(**kw)` 래퍼(`_attr` 패턴) | 백엔드는 코어를 어댑터로만 |

**import 금지**: `esl/val_src.py`·`esl/val_metrics.py` → `esl.doe`·`esl.pipeline`·`esl_platform`·`esl_worker` 금지(시험 V-0243-VAL-4 가 import 그래프 확인). `esl.pipeline` 이 두 모듈을 import(역방향 아님).

### 5.1 `val_metrics` 함수 (서명 고정)

```
disp_metrics(X0, u_rel, u_val6, R, F, spc_idx, U, node_id, *, top_n, hist_bins) -> {
    d_rel, d_val, dn, disp_rms_rel, disp_max_rel, reaction_rel, reaction_sum_rel, lin_rigid_rel, disp_an}
hotspot_rows(hs, eps_rad, eps_val) -> (hots, excluded)            # 지금 :1664-1677 그대로
field_compare(base, eps_esl, d_rel, d_val, *, model_arrays, ccfg, esl_layers_text) -> (arrays, summary)
metric_rows(values, crit, ccfg, *, reaction_role, strain_skipped) -> list[dict]   # judged/ref/info, :1725-1752
verdict_of(metrics, undetermined_reason) -> (verdict, fail_reasons)               # :1766-1776
validation_doc(*, frame, verdict, ..., created_at) -> dict          # 키 순서 = 지금 val 사전(:1778-1784)
```
`reaction_role = "info"` → 반력 지표 role info(criterion 없음). full 경로 호출은 지금과 같은 인수·같은 순서 → 같은 바이트(골든).

---

## 6. 코어 흐름 `stage_validate` (P1)

### 6.1 순서

1. 지금 그대로: 필수 파일(`_require` — legacy 행 required), model·u_rel·esl_summary·support, U, `fs = full_solve_decision(...)`.
2. 출처 행 준비: 설정 `validation.sources.enabled` 거짓 → legacy 외 행 `disabled`. 아니면 행마다 `row_status`(load 있음·node_id 일치·진단 code·ESL 요약 `ctx.record["stages"]["esl"]["summary"][summary]`) → done 후보 / unavailable / na.
3. 풀이(solved 일 때): 계획 열 `support` 값마다 `h = sm.factorize(spc)` → **legacy 행 해 먼저**, 같은 묶음의 출처 해를 차례로(출처 해 예외 = 그 행 `failed`, 계속). 묶음 끝에 `del h`. 단계 요약 `solver` = **legacy 해 직후 `solver_stats` 사본에서 `n_factorizations` 를 뺀 것**(지금과 같은 키·값), 출처 풀이 통계는 sources.json `solve`.
4. Radioss 쪽 한 번: hotspot(`_eval_hotspots`), `_field_base`, noise·δ(`_disp_noise_delta`), 누적 소성 요약 — 경고는 지금처럼 1회.
5. **legacy 행 지표·문서·파일 쓰기**(지금 :1786-1796 과 같은 순서·같은 경고·같은 echo) — 이 시점에 full 결과가 디스크에 완결.
6. 출처 행마다 `try`: `val_metrics` 로 같은 계산 → `05_val/<dir>/` 에 validation.json·validation.csv·compare_field.npz·(풀이 있으면) compare_disp.npz·compare.csv → 행 `done` + 요약. 파일은 `05_val/<dir>.tmp/` 에 쓰고 성공 때 `<dir>` 로 `atomic_replace`(05_val 은 이번 단계의 새 폴더라 이전 출처 결과 없음). `except Exception` → tmp 폴더 정리, 행 `failed` + `VAL_SRC_FAILED` + 단계 경고 1줄 `VAL_SRC_FAILED: <key> <코드>`.
7. `05_val/sources.json` 마지막에 씀(§6.2). echo 한 줄/출처: `[validate] <key>: 변위 RMS … → <verdict>` 또는 `<key>: 불가 <code>`.

- 쓰기는 전부 `ctx.f`·`ctx.guard`(05_val 안) — 입력·SPDM 쓰기 없음. `ctx.fresh_dir(D_VAL)` 가 이전 05_val 전체(하위 폴더 포함)를 `_backup` 으로(지금 규칙).
- 판정 불가: full = 지금. 출처 = 같은 `undetermined_reason`, 판정 지표 중 `disp_noise_rel` 만 값, 참고·hotspot·field·disp = null/빈 목록, compare_* 파일 없음.
- 응력 대체(`strain_source == max_stress`): 출처도 같은 규칙(변형률 참고 전부 생략).

### 6.2 `05_val/sources.json` (`esl/val_sources/1`)

```
{schema, esl_ref, default: <legacy key>, enabled: bool,
 solve: {groups: [{support, keys: [..], factor_s, solve_s: {key: s}}], decision: {mode, run, reason}},
 rows: [{key, status, code, reason, dir, verdict, fail_reasons, undetermined_reason,
         metrics: {disp_rms_rel, disp_max_rel, reaction_rel, disp_noise_rel, reaction_sum_rel,
                   hotspot1_strain_rel_err, field_p90_err_pct},
         reaction_role, cond: {load_frame, balance, support, rigid, resp}, cond_text, note,
         limits: [code], limit_text: [str], comparable: bool}],
 created_at}
```
행 순서 = KEYS. legacy 행도 기록(dir `""`, 값 = 루트 validation.json 과 같음). 상태가 done 이 아니면 verdict 이하 null·빈 값.

### 6.3 출처 `validation.json`

루트 문서와 같은 키·같은 순서 + 끝에 `"src": {key, load: "04_esl/<file>", sum_abs_f, load_frame, balance, support, rigid, resp, cond_text, note, limits, limit_text, comparable}`, `criteria` 끝에 `reaction_role`. `esl_ref`·`frame`·`noise`·`noise_source`·`full_solve`·`strain_source` = 루트와 같은 값.

### 6.4 단계 요약 (run.json `stages.validate.summary`)

기존 키·값 그대로 + 새 키 `sources: {key: {status, verdict, fail_reasons, undetermined_reason, code, disp_rms_rel, disp_max_rel, reaction_rel}}`(legacy 제외). 워커 `register_validation` 반환·DB 는 그대로(§7.4).

---

## 7. API · 스키마 (P1)

### 7.1 경로

| 경로 | 동작 |
|---|---|
| `GET /validations/{vid}` (`?src=` 선택) | `src` 없음·legacy 키 = **지금 코드 경로 그대로**(DB 행, 응답 JSON 바이트 동일). 그 밖 = 그 검증 폴더(`locate_validation_dir` — 스냅샷 표식 → Case 05_val → `_backup` 표식)의 `<dir>/validation.json` 을 `co.validation_fields`(§7.4)로 매핑한 `ValidationOut` — `id`·`esl_run_id`·`case_id`·`job_id`·`created_at`·`stale` = 부모 DB 행, `dir_rel = "05_val/<dir>"`, `status` = verdict(출처 문서는 scheme 항상 있음). |
| `GET /validations/{vid}/sources` (새) | `ValidationSourcesOut` — 행 = KEYS 순서. sources.json 있으면 그 행, 없으면 legacy 행 = DB(LEGACY 포함 `validation_status`), 나머지 = `VAL_SRC_NOT_RUN`(jig = `V3D_STUDY_ONLY`), 폴더 없음 = 비legacy 행 `VALIDATION_FILES_GONE`. 파일을 쓰지 않음. |
| `GET /validations/{vid}/field·/disp-field·/section` (`?src=` 선택) | `_val_npz(…, src)` → `<loc>/<dir>/compare_*.npz`. `src` 없음 = 지금 바이트. |
| `GET /cases/{case_id}/validations/sources` (새, 이력) | `ValidationSourcesHistOut` — `/cases/{id}/validations` 와 같은 순서·개수의 검증마다 행 목록(위 규칙). |

오류: 모르는 src = **404 `SOURCE_NOT_FOUND`**{src, keys}(v0.24.1 과 같은 코드). 아는 출처지만 결과 없음 = **409 `VAL_SOURCE_UNAVAILABLE`**{src, reason_code, reason}(detail.code = 오류 코드, 출처 사유 = `reason_code` — D-0.24.1-V3D-11 규칙). 폴더 없음 = 409 `VALIDATION_FILES_GONE`(지금).

### 7.2 스키마 (`schemas.py` ↔ `frontend/src/api/types.ts`, `check:api`)

```
ValidationSourceRow { key: str, available: bool, code: str|null, reason: str|null,
  status: "PASS"|"FAIL"|"UNDETERMINED"|"LEGACY"|null, fail_reasons: list[str], undetermined_reason: str|null,
  reaction_role: "judge"|"info"|null, cond_text: str|null, note: str|null,
  limits: list[str], limit_text: list[str], comparable: bool|null }
ValidationSourcesOut { validation_id: str, default: str, rows: list[ValidationSourceRow] }
ValidationSourcesHistItem { validation_id: str, rows: list[ValidationSourceRow] }
ValidationSourcesHistOut { case_id: str, items: list[ValidationSourcesHistItem] }
```
`ValidationOut` **불변**(새 필드 없음 — 옛 응답 바이트·OpenAPI 스키마 그대로). `default` = 계획 legacy 키(설정 아님 — 등록·DB 기준이 full 이라 고정). `docs/contracts/openapi_p1b.json` 은 `scripts/dump_openapi.py` 로 다시 뽑음.

### 7.3 권한

기존 검증 조회와 같음(`get_principal`). 새 경로도 Case 읽기 권한 규칙 그대로.

### 7.4 매핑 한 곳

`esl_platform/core/core_outputs.py:validation_fields(doc) -> dict`(hotspots·excluded·verdict·scheme·undetermined_reason·disp_* ·reaction_rel·fail_reasons·criteria·field·disp·strain_ref — 지금 `register.py:232-262` 의 변환). 워커 `register_validation` 이 이 함수를 쓰도록 바꾸고(리팩터 — DB 값 불변, 기존 시험 무수정 통과), 백엔드 출처 `ValidationOut` 도 같은 함수.

---

## 8. 화면 ④ 검증 (`Stage5.tsx`, P1) — 2560×1440 세로 높이 불변, 정보 삭제 없음

- **출처 탭**: 판정 카드 머리(`right` 앞, 지금 줄 — 새 줄 없음)에 `SourceTabs`(v0.24.1 같은 컴포넌트·같은 순서·이름·사유 형식), prefix `val-src`, testid `val-src-tab`·사유 `val-src-tab-why`. 항목 = `tabItemsOf(rows)`(새 순수 함수 — `caseTabItems` 와 같은 규칙, available·reason), 기본 탭 = 응답 `default`. `/validations/{vid}/sources` 가 실패하면(옛 서버) 탭 없이 v0.24.2 화면 그대로.
- **탭 판정 표시**(필수 요소 1개): `SourceTabItem.mark?: {text, tone}`(선택 속성 — 없으면 DOM 동일, Case ③·스터디 영향 없음) = `STATUS_LABEL[status]`(PASS·FAIL·판정 불가) + 한계(§10) 표식. 출처 간 판정을 한눈에 비교하는 유일한 새 요소.
- **조건**(하중 프레임·지지·균형·응답): 탭 `title`(툴팁) = `cond_text` — 새 줄 없음.
- **탭마다 같은 카드**: 판정(`JudgeStat` 4칸 — `criteria.reaction_role == "info"` 이면 반력 칸은 기준·색 없이 sub "정보 — 지지 반력"), 변위 비교(설명 줄 = 행 `note` — legacy 는 지금 문구 그대로, `DispOverlay`·히스토그램·상위 노드·단면), 변형률(참고), 상위 요소, hotspot, 제외 요소, 이력. 선택 탭의 `ValidationOut`(legacy = 지금 `api.validation(vid)`, 그 밖 `?src=`)과 `src` 를 `DispOverlay`·`FieldOverlay`·`useSectionCtl`(캐시 키에 src) 에 넘긴다.
- **판정 불가 출처**: 변형률 카드에 field 가 없고 `undetermined_reason` 이 있으면 안내 1줄 "전체 재해석이 없어 변형률 비교를 표시할 수 없습니다"(지금 `disp-note` 와 같은 자리 규칙 — 옛 검증 안내 `warn-box` 와 구별, 데이터 규칙이지 출처 이름 분기 아님).
- **이력 카드**: 행·순서 그대로, 판정 열 = 선택 탭이 legacy 면 지금 `StatusBadge(h)`, 아니면 `/cases/{id}/validations/sources` 의 그 키 상태(없음 = "–" + title 사유). 분기 기준 = `isLegacySource(tab)`(계획 열).
- **결과 없는 출처 탭**(`VAL_SRC_NOT_RUN`, 현재 실행 화면·`allowed`): 탭 선택 가능(v0.24.1 D-V3D-9 모양 — 흐린 글자 + "+"), 본문 = 사유 1줄 + [검증 다시 실행] 버튼 1개(같은 VALIDATE 작업). 과거 실행(`?val=`)은 버튼 없음. 화면 버튼 추가 ≤ 1.
- **주 버튼·등록**: `useRegistration` 은 legacy(full) 검증으로만(탭과 무관 — DB·라이브러리 기준), 출처 탭의 `StatusBadge` title = "이 출처 판정 — 라이브러리 등록·내보내기 기준은 전 노드 ESL 판정".
- 머리 줄 폭: 2201px 이상에서 판정 카드 머리 1줄(탭 4 + 표식 + 판정 배지 + 보고서 + 등록) — 넘치면 탭 라벨 말줄임(전체 = title). DOM 측정 시험.

---

## 9. 실행 흐름 · 소요 시간

- [검증 실행] 1번 = 같은 `VALIDATE` 작업(step VALIDATE·VAL_REGISTER 그대로)이 **가능한 모든 출처를 한 번에**(사용성 우선 — 출처별 버튼 없음). 일괄 실행(run_all)·라이브러리 재검증(origin library_revalidate)도 같은 작업이라 출처를 함께 검증(끄려면 설정).
- 소요(§4.1): P1 = 검증 +≈ 10~25 %(분해 공유), P2 jig 행 = 분해 1회 추가. 디스크: 출처당 05_val 루트와 같은 크기(추정 compare.csv 194k 행 ≈ 20 MB + npz 수십 MB), run 스냅샷(`runs/<id>/05_val`)·백업에도 같이 복사됨.
- 실패 격리: §6.1-6 — 출처 예외는 그 행 `failed` 뿐, full 판정·DB 등록·자동 보고서(CASE_REPORT)·라이브러리 게이트 무영향. 출처 해 OOM 은 `_oom_guard` → EslError → 그 행만. 프로세스 강제 종료(한도 초과)는 지금과 같이 작업 실패 — 분해 피크가 지금과 같아 새 위험 없음.

---

## 10. 한계('비교용 아님') 표시 정책 (P1 표시 · P3 선택)

- 출처 진단의 한계 코드(계획 열 `limits` — `bforce.json limits`·`fint.json limits`·P2 `jig.json limits`)를 검증 행에 그대로 싣고, 등급 표 `val_src.LIMIT_CLASS` 한 곳으로 분류:

| 코드 | 등급 | 문구 원본 |
|---|---|---|
| `BF_TIE_MISSING`(경계력 contact 등급) | `not_comparable` — "비교용 아님" | `bforce.LIMIT_TEXT` "tie 체결력 미포함 — 조립 부품 하중 누락" |
| `FINT_ROT_LINKS` | `caution` | `bforce.LIMIT_TEXT` |
| `JIG_REGION_FALLBACK`(P2 — 접촉 영역 0, 전부 패치) | `caution` | P2 `jig.json` 경고 문구 |

- **판정과의 관계**: 판정(PASS·FAIL·판정 불가)은 정의대로 계산하고 바꾸지 않는다(같은 정의 원칙). 표시 = 판정 + 한계 표식: 탭 `mark` = "FAIL · 비교용 아님"(not_comparable, 경고색) 또는 "PASS ⚠"(caution), 탭 title 에 한계 문구. `comparable = not any(not_comparable)`.
- 07_report 출처 표에 한계 열. P3 선택: not_comparable·caution·검증 미통과 모두 **경고 + 확인**(차단 안 함 — §12.2).

---

## 11. 설정 (하드코딩 금지)

| 키 | 기본 | 위치 | 해시 영향 |
|---|---|---|---|
| `validation.sources.enabled`(P1, 코어) | `true` | `esl/config.py` `VALIDATION_SOURCES_DEFAULTS`(값 단일 출처)·SCHEMA `validation.sources: {enabled: bool}`·`OPTIONAL_KEYS`(`"validation.sources"`)·접근자 `validation_sources_settings(cfg)`, `config/esl.example.yaml`(주석 줄) | 키가 없으면 cfg 에 주입하지 않음 → run.json `config.sha256`·VALIDATE 작업 `params.settings` 사본·이력 지문(`history.py:330` — 이 키 없음) **불변** |
| `jig.*`(P2, 코어 선택 절) | `esl/mech/jig.py:JIG_DEFAULTS`(= 지금 `bead_doe.rank.jig` 값 — `esl/doe/__init__.py` DEFAULTS 도 이 사전을 참조, 값 동일) + Case 만 `enabled: true` | `esl/config.py` `OPTIONAL_SECTIONS += {"jig"}`·`jig_settings(cfg)`, `esl.example.yaml` | 절이 없으면 주입 없음 |
| `bead_doe.case_jig.{enabled, timeout_s}`(P2, 플랫폼) | `true`, `null`(= `bead_doe.paicad.timeout_s.fixed_scan`) | `esl/doe/__init__.py` DEFAULTS·pydantic `BeadDoe*Cfg`·`config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml` | – |
| `bead_doe.load_source_default`·`opt_run.load_source_default`(P3, 플랫폼) | `null`(= 지금 규칙: `rank.metric` → metric_effective) · `full` | DEFAULTS·pydantic·yaml 2개 | 새 스냅샷만 |

검증 화면 기본 탭은 설정이 아니라 계획 legacy 행(등록·DB 기준이 full 이라 고정 — `view3d.case_src_default` 와 독립).

---

## 12. P2 · P3 (v0.24.4)

### 12.1 P2 — Case ③ ESL 지그 산출

| 항목 | 결정 |
|---|---|
| tie 노드 | 워커가 **ESL_SOLVE 의 ESL step 안, 코어 자식 시작 전**(v0.24.2 bf 보충과 같은 자리 — 새 작업 유형·step 없음)에 판정 표 `worker/esl_worker/jig_prep.py:DECIDE`: `bead_doe.case_jig.enabled` ∧ 코어 `jig.enabled` ∧ paicad 준비됨 ∧ 캐시 없음 → paicad `fixed-scan`(대상 파트) → `<case>/01_extract/jig_fixed/`(`shell_scan.json`·`fixed_nodes.npz`). assem_dir = Case 폴더 제자리(include 가 모두 안에 있을 때 — `doe_jobs.py:477` A Case 방식) 아니면 `<case>/_jig/assem_full/` 사본(`assem_full` 기존 함수 — 원본은 읽기만, 입력·SPDM 쓰기 없음). 캐시 키 = assem 매니페스트 sha256(파일 sha) + part id + `fix_kinds`. paicad 없음·실패·시간 초과 = `JIG_FIXED_SKIPPED`·`JIG_FIXED_FAILED`(ESL 계속, 지그 = unavailable). |
| deck 표면 | 코어가 `ctx.rad`(Case starter, 읽기만)·`case.include_path_map`·depth 로 `esl/rad/surface.other_surfaces` → 캐시 `01_extract/jig_surf.npz`(키 = include 트리 stat(size·mtime_ns) + part id + 상자 + pad + `max_surf_tris`) — 다른 프레임 ESL 재계산 때 ≈ 84 s 재읽기 없음. 누적 씬 = 파서의 상태 파일 좌표 규칙 그대로(model.npz x0 와 같은 규칙). 실패·상한 초과 = 패치 + `JIG_REGION_FALLBACK`(지금 규칙). |
| 계산 | `stage_esl` 끝에 `_jig_esl(ctx, model, d, sel, u_rel, sm)`(bforce·fint 다음) — 지그 노드(fixed-scan) → `target_disp(X0, u_rel, jidx, fit=전 노드)` → `select_regions`·`load_basis`·`factor`·`basis_response`·`jig_modes`·`fit_loads`·`forces`·`respond(keep_u)` — 스터디 `_jig_baseline` 과 **같은 순수 함수·같은 설정 이름**, 엔트리 1개(이 Case). 산출 `04_esl/jig.json`(`esl/doe_jig/1` 과 같은 키 — status·code·regions·fit 보고·limits·seconds)·`jig.npz`(node_id·`f` = F_jig 기준 형상·`jig_idx`·`a`·`u_val` = Kabsch 제거 응답(3D 용, bforce 와 같은 규칙)). |
| 공용 모듈 이동 | `esl/doe/jig.py` → **`esl/mech/jig.py`**, `esl/doe/jig_surf.py` → **`esl/rad/surface.py`**, `assem_full` 의 `ELEM_NODES`·`ELEM_TOTAL`·`_faces`·`_clean`(면 계산 순수 부분) → **`esl/rad/solid_faces.py`**, `paicad_io.read_fixed`·`FIXED_KINDS`·`SCAN_JSON` → **`esl/io/fixed_scan.py`**. 옛 경로 = 재수출 심(같은 객체 — `esl.doe.jig.X is esl.mech.jig.X`), `stages.py` import 불변, 스터디 결과 바이트 동일. `esl.pipeline` → `esl.doe` import 0(시험). |
| 실패 격리 | `_jig_esl` 모든 예외 = `jig.json` code `JIG_FAILED` + 요약 code·reason, ESL 단계·다른 출처 무영향(`_bforce_esl` 과 같은 규칙). tie 0 = `JIG_NO_TIE`(unavailable). |
| 스터디 | **지금처럼 자체 계산**(바이트 동일). 근거: 스터디 지그는 기준 메시 위 **모든 엔트리 공유 기저**·목표 sm_ref(D-JIG-7)이고 Case 지그는 Case 마다 다른 영역·기저. 재사용(같은 메시·같은 deck sha·단일 기저 조건) = R-VAL-3. |
| ③ 3D | `CASE_PLAN` jig 행 채움: load esl `jig.npz` f, target u_rel, resp esl `jig.npz` u_val, recon_tgt u_rel, rigid kabsch, support **`jig`**(새 값 — 백엔드 `SUPPORT_FILES` 에 지그 노드 표본 `support_sample(…, view3d.jig_support_max)`), summary `jig`, doc esl `jig.json`, dir `view3d_jig`·recon_dir `view3d_jig_recon`, na `JIG_NOT_RUN`. V-0241-V3D-4·5 의 jig 기대값만 갱신(의도된 변경). ③ 결과 카드에 `esl-jig-line`(경계력 줄과 같은 형식 — 지그 노드 수·영역 수(접촉/패치)·재현 MAC·umax 오차·한계). |
| ④ | `VAL_PLAN` jig 행(§2.2 P2) — 지지 `jig` 묶음 분해 1회, 반력 info. |
| 비용(현장 추정) | fixed-scan 첫 ESL 1회(캐시, 한도 3600 s) + deck 표면 ≈ 84 s(첫 1회, 캐시) + 지그 분해 ≈ 1 회(≈ 검증 분해만큼) + 기저 해 ≈ 31 + eigsh 수십 초~분 → 첫 ESL **+≈ 6~10 분**, 같은 Case 다른 프레임 ≈ +4~6 분. 메모리 피크 = 분해 1개(지금 ESL 과 같음). |

### 12.2 P3 — 하위 작업 출처 선택

| 항목 | 결정 |
|---|---|
| 공통 키 | 요청 `load_source: "jig"\|"full"\|"bforce"\|"fint" \| null`(값 = KEYS) — `DoeCheckIn`(스터디)·`OptRunIn`(비드 최적화). 스냅샷 `doe.load_source`·opt 실행 스냅샷 `load_source` + `load_source_check{key, entries:[{entry_id, status, comparable, validation_id}], worst}` |
| 선택 시점 | 작업 생성 때 **1개**(스터디 탭·순위는 출처마다 하나여야 함 — 항목별 혼합 금지). 생성 화면에 선택 항목들의 출처별 판정 요약(최악) 표시 — 출처 판정 = 각 항목 `validation_id` 의 `/validations/{vid}/sources`(묶음 경로 `/library/entries/sources?ids=`) |
| 기본(없을 때) | 지금 동작 그대로: 스터디 = `rank.metric` → `metric_effective`(jig 우선, D-0.23.0-JIG-8), 비드 최적화 = `full`(설정 `*.load_source_default`) — 근거: 하위 호환·옛 스냅샷 해시 불변 |
| 경고 정책 | 검증 미통과(FAIL·판정 불가·결과 없음)·`not_comparable`·`caution` = **경고 + 확인(차단 안 함)** — 사용자 선택 원칙(요청 2). 확인은 요청 `load_source_ack: true`(없으면 422 `LOAD_SOURCE_UNCONFIRMED`{entries, worst} — 화면이 확인 대화 후 다시 보냄). 결과 화면 칩 "하중 출처 <이름> · <최악 판정>". 차단은 하중이 **없을 때만**: 422 `LOAD_SOURCE_UNAVAILABLE`{entry_ids, reasons}. 라이브러리 등록·적격 게이트(full PASS)는 그대로 — full 판정은 같은 K 수치 일관성이라 ESL 계산 건전성 게이트로 유지 |
| 스터디 | `load_source` → 기본 탭·report.html·ranking.csv 기준 = `RANK_SOURCES[key].metric`(bf·fi 를 주 지표로 쓸 수 있게 `rank.rank` 주 지표 허용 — D-0.24.0-BF-8 개정, 옛 스냅샷 바이트 동일) |
| 비드 최적화 | 출처 하중 = 엔트리 Case 에서 찾기(`stages._ns_find` 를 **`esl/library/source_load.py`** 로 옮겨 스터디·비드 최적화 공용 — 라이브러리 항목 불변). S1: full·bforce·fint = 노드 직접 + 3-2-1, jig = 노드 직접 + **지그 지지**(SPC = jig.npz 지그 노드 ID, 템플릿 지지 대신). S2(셀 매핑): full·bforce·fint 는 출처 하중으로 셀 요약을 다시 만듦, jig = 422 `LOAD_SOURCE_UNSUPPORTED`(지지 매핑 없음) |

---

## 13. 하위 호환

1. 옛 Case 05_val(sources.json 없음): 파일 그대로, `/validations/{vid}`·field·disp-field·section 응답 바이트 동일, sources 경로 = legacy 행 + `VAL_SRC_NOT_RUN`. 화면 = 탭(legacy 활성 + 나머지 "+" 탭)·나머지 카드 v0.24.2 와 같은 DOM.
2. 새 검증의 full = 루트 파일 v0.24.2 출력과 바이트 동일(V-0243-VAL-1). 06_export 파일 = 같음(헤더 생성 시각 줄 제외). 07_report = sources.json 없으면 생성 시각·버전 외 같음.
3. DB migration 없음. `validations` 행 값·라이브러리 quality·재검증 전환 불변.
4. 설정 키가 없으면 설정 스냅샷·해시 불변. v0.24.1 Case ③ 3D·스터디 결과 바이트 불변(P1). P2 는 CASE_PLAN jig 행 기대값만 의도 변경.
5. 결과 받기(zip, summary) 는 05_val 을 재귀로 담으므로 새 검증에서 출처 폴더 json·csv 가 늘어남(옛 Case 그대로).

---

## 14. 시험

### 14.1 P1 (V-0243-VAL-n)

| # | 단위 | 내용 |
|---|---|---|
| 1 | 골든 | 합성 Case 3종(① bforce·fint 자료 있음 ② 없음 ③ `full_solve: never`) + 응력 대체 1종, SuperLU: 05_val 루트 validation.json(created_at 제외)·validation.csv·compare.csv·compare_field.npz·compare_disp.npz sha256 = **v0.24.2 코드 기록값** — 골든은 이 계약 커밋(코드 = v0.24.2)에서 `ESL_GOLDEN_RECORD=1` 로 `tests/fixtures/val_src/golden_v0242.json` 에 먼저 기록. 단계 요약 기존 키 값 동일 |
| 2 | 모듈 | `val_metrics`: u_val = u_rel + 미소 강체 → disp 지표 ≈ 0(1e-12), 회전 섞인 경우 선형 제거, reaction 두 정의, `reaction_role` info → 판정 제외·fail_reasons 없음; full 인수로 부른 결과 = 지금 인라인 계산(골든과 같은 값) |
| 3 | 정의 | 출처 bforce(직접법): 검증 `reaction_sum_rel` = `bforce.json recon.reaction_rel`(1e-9 상대), `remove_rigid(X0, u_val6)[0]` = `bforce.npz u_val`(1e-12), `disp_noise_rel`·`u_rel_linear_rigid_rel`·`hotspots_excluded`·U = full 과 같음, `noise_force_rel` null |
| 4 | 계획 | `VAL_PLAN` 모든 행 모든 열·키 순서 = `view3d_src.KEYS` = RANK_SOURCES·legacy 1행·dir 유일·rigid 전부 linear(어기면 CONFIG_INVALID); `esl.val_src`·`esl.val_metrics` 가 esl.doe·esl.pipeline·esl_platform·esl_worker 를 import 하지 않음 |
| 5 | 사유 | `row_status` 표: ESL 요약 BF_DISABLED·BF_NO_DATA·BF_EXTRACT_FAILED·BF_EXTRACT_SKIPPED·BF_FAILED(진단 json)·FINT_NO_DATA·옛 ESL(파일·요약 없음 → V3D_SRC_NOT_RUN)·jig(V3D_STUDY_ONLY) → sources.json status·code·reason, 그 출처 폴더 없음 |
| 6 | 격리 | 출처 하중 node_id 불일치·NaN 하중·두 번째 `FactorizedSolve.solve` 예외 주입(monkeypatch)·출처 쓰기 예외 → full 파일 골든 동일·verdict 동일·행 failed `VAL_SRC_FAILED`·단계 done·경고 1줄·`<dir>.tmp` 남지 않음 |
| 7 | 분해 | 3-2-1 묶음 분해 1회(`sources.json solve.groups[0]`), full 해 = `sm.solve` 비트 동일, 단계 요약 `solver` 키 = v0.24.2 |
| 8 | 설정 | `validation.sources` 없음 → 설정 스냅샷·sha 불변; `enabled: false` → 출처 풀이 0·행 disabled; 모르는 키 → CONFIG_INVALID |
| 9 | 판정 불가 | never·ZERO_DISP → 출처 문서 UNDETERMINED(같은 사유)·field null·compare 파일 없음·disp_noise_rel 값 있음 |
| 10 | 보고서 | sources.json 없음 → v0.24.2 보고서와(생성 시각·버전 제외) 같은 HTML·`missing` 목록 불변; 있음 → 5절 끝 표 1개(행 순서 KEYS 중 load 있는 행, 한계 열) |
| 11 | 내보내기 | 출처 결과가 있어도 06_export 파일 바이트(생성 시각 줄 제외) 동일 |
| 12 | API | `/validations/{vid}`(src 없음·`?src=full`) JSON 바이트 = 변경 전; `?src=bforce` = `co.validation_fields(05_val/bforce/validation.json)` + 부모 필드·dir_rel; 404·409 VAL_SOURCE_UNAVAILABLE(reason_code)·409 VALIDATION_FILES_GONE; 스냅샷·`_backup` 표식에서도 읽힘 |
| 13 | API | field·disp-field·section `?src=` → `<dir>/compare_*.npz`, src 없음 바이트 동일 |
| 14 | API | `/validations/{vid}/sources`·`/cases/{cid}/validations/sources`: 검증 4종(옛·새·LEGACY·파일 없음) 기대표, 호출 뒤 Case 폴더 새 파일 0 |
| 15 | 워커 | `register_validation` 이 `co.validation_fields` 사용 — DB 행 값 = 변경 전(기존 시험 무수정) |
| 16 | 스키마 | OpenAPI 새 경로·스키마 4개, `ValidationOut` 스키마 불변, `check:api` 통과 |
| 17 | vitest | 탭 항목 = sources 응답(순서·이름·`unavailText`), mark 문구·한계 표식, 기본 탭 = default, legacy 탭 API URL 문자열 = 지금, 다른 탭 `?src=`; 출처 이름 문자열 비교 없음(소스 grep 시험) |
| 18 | vitest | `VAL_SRC_NOT_RUN` 탭 선택 가능·본문 버튼 1개(화면 추가 버튼 ≤ 1), `?val=` 버튼 없음; 탭을 바꿔도 주 버튼·등록 = full 기준 |
| 19 | vitest | 변위 설명 = 행 note(legacy = 지금 문구), reaction_role info → 반력 칸 기준·색 없음, 판정 불가 출처 안내 1줄, 이력 판정 열 = 출처 상태 |
| 20 | vitest | `SourceTabs` mark 없으면 DOM 동일(Case ③·스터디 시험 무수정), 옛 서버(sources 404) = v0.24.2 DOM |
| 21 | 화면 | 판정 카드 머리 1줄(2201px+ DOM 측정), 새 블록 줄 0, 2560×1440 스크린샷 높이 = v0.24.2 |

### 14.2 P2·P3 (V-0244-VAL-n — v0.24.4 착수 때 세부 확정)

| # | 내용 |
|---|---|
| 1 | 모듈 이동: `esl.doe.jig.X is esl.mech.jig.X`(전 공개·사용 이름), 스터디 지그 시험(V-JIG-*)·deck 표면 시험 무수정 통과, `esl.pipeline` import 그래프에 esl.doe 없음 |
| 2 | Case 지그 합성(인접 쉘·tie 픽스처 fixed-scan 출력): `04_esl/jig.*` 스키마, 같은 입력의 스터디 `_jig_baseline`(엔트리 1개·같은 메시) 과 a·F_jig 같음(1e-9) |
| 3 | 캐시: 두 번째 ESL(다른 프레임) fixed-scan·deck 표면 재실행 0, include stat 바뀌면 재계산 |
| 4 | 격리: paicad 없음·fixed-scan 실패·지그 예외 → ESL done, 다른 출처 파일 바이트 동일, 요약 code |
| 5 | ③ 3D jig 탭: 하중·응답·재현·지그 지지 표식, 옛 Case = `JIG_NOT_RUN` |
| 6 | ④ jig 행: 지그 묶음 분해 1회·반력 info·판정 = 변위 3지표 |
| 7 | P3 API: `load_source` 없음 → 스냅샷·해시 v0.24.3 과 같음; 미통과·not_comparable → 422 `LOAD_SOURCE_UNCONFIRMED` → ack 후 202; 하중 없음 → 422 `LOAD_SOURCE_UNAVAILABLE`; S2 jig → 422 `LOAD_SOURCE_UNSUPPORTED` |
| 8 | P3 비드 최적화: S1 bforce 하중 = 엔트리 Case bforce.npz(노드 ID 정렬), jig = 지그 지지 SPC 덱, `source_load` 공용(스터디 `_ns_find` 결과 바이트 동일) |

---

## 15. 완료 기준 (P1)

- §14.1 전부 + 기존 시험 무수정 통과(의도 변경 없음), ruff·mypy·tsc·eslint·`check:api` 깨끗, `dump_openapi.py --check` 통과.
- 골든(V-1) 파일이 코어 변경 **전** 커밋에 있음.
- 합성 Case 수동 확인 스크린샷 `work/screens/v0243_val_{full,bforce,fint,old}.png`(4탭·표식·조건 툴팁·이력).
- 현장 확인 안내(통합): 194k 노드 Case 에서 `sources.json solve` 시간·05_val 크기 기록 → 이 문서 부록.
- `docs/decisions.md` D-0.24.3-VAL-1~17 반영, 계약과 다른 구현은 부록.

## 16. 작업 분해 (파일 소유권 겹침 없음)

### 16.1 P1 (v0.24.3)

| 묶음 | 소유 파일 | 선행 |
|---|---|---|
| **A 코어** | `esl/val_src.py`(새), `esl/val_metrics.py`(새), `esl/pipeline.py`(stage_validate·_field_compare 분리만), `esl/report/case_report.py`(출처 표 1개 — sources.json 선택 읽기, `missing` 에 넣지 않음), `esl/config.py`(VALIDATION_SOURCES_DEFAULTS·SCHEMA·OPTIONAL_KEYS·접근자), `config/esl.example.yaml`, `worker/esl_worker/core_adapter.py`(래퍼 2개), `tests/test_val_src.py`·`tests/pipeline/test_validate_sources.py`·`tests/report/test_report_val_src.py`(새), `tests/fixtures/val_src/golden_v0242.json`(V-1 — **먼저 기록**) | 없음 |
| **B 백엔드** | `backend/esl_platform/api/services/results.py`, `api/routers/results.py`, `api/schemas.py`, `core/core_outputs.py`(validation_fields·출처 폴더 도우미), `worker/esl_worker/register.py`(validation_fields 사용 — 리팩터만), `docs/contracts/openapi_p1b.json`(덤프), `backend/tests/test_val_src_api.py`(새) | A 의 val_src 행·sources.json 형식 고정(§6.2 — 병행 가능) |
| **C 프런트** | `frontend/src/stages/Stage5.tsx`, `view3d/sources.ts`(tabItemsOf·markOf), `view3d/SourceTabs.tsx`(mark 선택 속성), `components/{DispOverlay,FieldOverlay,SectionChart}.tsx`(src 인자), `api/{endpoints.ts,types.ts}`, `mock/server.ts`, `__tests__/val_src.test.tsx`(새) | §7.2 필드 고정(B 와 병행) |
| 통합 | `CHANGELOG.md`·`VERSION`·`docs/manual/user.md`(④ 검증 절 한 단락)·이 문서 부록 | A·B·C 뒤 |

### 16.2 P2·P3 (v0.24.4, 초안)

| 묶음 | 소유 파일 |
|---|---|
| A2 코어 | `esl/mech/jig.py`·`esl/rad/surface.py`·`esl/rad/solid_faces.py`·`esl/io/fixed_scan.py`(이동) + 심 `esl/doe/{jig,jig_surf,paicad_io,assem_full}.py`, `esl/pipeline.py`(_jig_esl), `esl/view3d_src.py`·`esl/val_src.py`(jig 행), `esl/config.py`(jig 절) |
| W2 워커 | `worker/esl_worker/jig_prep.py`(새 — DECIDE), `executor.py`(ESL step 훅), `doe_jobs.py`(fixed-scan 공용 함수 추출만) |
| B2 백엔드 | `services/view3d.py`(support jig), `core/config.py`(case_jig), yaml 2개 |
| C2 프런트 | `stages/Stage4.tsx`(esl-jig-line) |
| A3 코어 | `esl/library/source_load.py`(새 — `_ns_find` 이동), `esl/doe/stages.py`(load_source → metric_effective), `esl/opt/target.py`(출처 하중·지그 지지) |
| B3 백엔드 | `schemas.py`(load_source·ack), `services/doe.py`·`services/opt.py`(검사·스냅샷), `services/library.py`(항목 출처 판정 묶음 경로) |
| C3 프런트 | 스터디·비드 최적화 생성 화면(출처 선택·확인 대화), 결과 칩 |

순서: P1 = A(골든 → 모듈) → B·C 병행 → 통합. v0.24.4 = A2·W2 → B2·C2 → A3 → B3·C3 → 통합(시간이 모자라면 P3 비드 최적화 jig 를 R-VAL-6 으로).

## 17. 미결 (결과를 바꾸는 것만 — 가정대로 진행 가능)

- **Q1** 3-2-1 지지에서 균형 보정이 없는 출처(내력 ESL 기본 `bforce.fint.balance: none`, 경계력 `balance: none` 설정 시)의 반력 판정 — **가정: 공통 기준 그대로 판정**(사용자 "같은 기준"; 불평형 ‖ΣF‖/Σ‖F‖ ≈ 1e-3 이면 `REACTION` FAIL 로 드러남). 대안 = 계획 열 `reaction_role` 을 적용된 균형 방식으로 고르게(none → info). 바꾸면 내력 ESL 판정이 PASS·FAIL 사이에서 바뀜.
- **Q2** 하위 작업 출처 선택 위치 — **가정: 작업 생성 때 1개**(스터디 탭·순위·비드 최적화 하중 케이스가 출처 하나로 일관). 대안 = Case ④ 검증 화면에서 항목별 '선호 출처'를 저장해 항목마다 다른 출처 혼합. 바꾸면 한 스터디·최적화 안에 출처가 섞임(P3 만 영향, P1·P2 불변).

## 18. 결정 (요약 — 전문은 `docs/decisions.md` 2026-11-20)

D-0.24.3-VAL-1 범위·단계 · -2 별도 계획 표 VAL_PLAN · -3 검증 단계 재풀이·지지 집합당 분해 1회 · -4 공통 정의 · -5 반력 역할 열 · -6 기준값 공통 · -7 비활성 사유 · -8 산출물 위치·하위 소비·07_report 표 · -9 실패 격리 · -10 공용 순수 모듈 · -11 API · -12 화면 · -13 실행·설정 · -14 한계 표시 정책 · -15 P2 Case 지그 · -16 P3 출처 선택 · -17 하위 호환.

## 19. 후속 (R-VAL-n)

- R-VAL-1 06_export 출처 하중 내보내기(R-BF-2 와 합침 — P3 선택 키 사용).
- R-VAL-2 ③ 3D 응답을 05_val/<dir>/compare_disp(선형 제거)로 통일(지금 bforce·fint = ESL u_val Kabsch — 수치 줄이 ④ 와 다를 수 있음).
- R-VAL-3 스터디가 Case 지그 결과 재사용(같은 메시·같은 deck sha·단일 기저 조건).
- R-VAL-4 ESL 단계 bforce·fint 재현 풀이 분해 공유(지금 `_nodal_recon` 마다 `sm.solve` — 같은 3-2-1 분해 2회, ESL ≈ −1 분해).
- R-VAL-5 출처 05_val 디스크 — 현장 크기가 크면 출처 `compare.csv` 선택 설정 검토.
- R-VAL-6 (P3 가 밀리면) 비드 최적화 jig(지그 지지 덱).

## 구현 메모 (2026-11-20, v0.24.3 P1 통합)

계약과 다른 점·통합에서 고친 것. 계약 본문은 그대로 두고 여기에 기록한다.

| 묶음 | 계약 | 구현 · 이유 |
|---|---|---|
| A | §4.1 `sm.factorize` 로 분해 1회 | `ShellModel.solve` 그대로 + `esl/mech/shell.py` `keep_factor`/`kept_factor`(선택, 기본 끔 — **소유 밖 파일, 기록**)로 그 분해를 출처 해에 재사용. 기존 `tests/pipeline/test_disp_primary.py` 가 `ShellModel.solve` 를 monkeypatch 하므로 무수정 통과. 출처 해 = 따로 푼 `sm.solve` 와 비트 동일(V-3). 단계 요약 solver 키 그대로(`n_factorizations` 없음) |
| A | §6.2 행 | 상태가 done 이 아니면 `dir` = null(폴더 없음). `solve.groups[].assembly_s`, `solve.eval_s{key}` 추가(legacy `solve_s` = 전체 − factor_s − assembly_s, `eval_s` = 변형률 회복 + 지표 + 파일 쓰기) |
| A | §6.2 행 `note` | 코드가 아니라 문구(`NOTE_TEXT`). 화면은 그대로 표시 |
| A | §6.3 판정 불가 출처(fallback 없음) | 파일 = `validation.json`·`validation.csv` 만(compare 파일 없음). `noise_hotspot_strain_rel` 은 S4 공통 값, hotspot·제외·field·strain_ref·disp = 빈 목록/null. `validation.json` 끝 `src` 블록·`criteria.reaction_role` |
| A | V-3 `hotspots_excluded` "full 과 같음" | 제외 요소·사유·ε_rad 같음(ε_val 은 출처 응답 값) |
| A | "기존 시험 무수정" | `tests/cumulative/golden_util.py`: v0.7.2 골든 비교에서 v0.24.3 추가 산출물(`sources.json`·`05_val/<출처>/`·07_report 출처 표 블록) 제외(v0.12.1 `ADDED_KEYS` 와 같은 원칙) — 메인 승인 |
| B | §2.2 표를 직접 복제한 임시 `esl.val_src` 로 시험 | 통합: `results.py` `_val_plan` 이 어댑터 `core_adapter.val_src_plan()`, 사유 문구는 `val_reason_text` 로 교체(문구 사본 제거), `backend/tests/test_val_src_api.py` 임시 모듈 제거 = 실제 코어 |
| B | sources.json 행에 `code` 없음 가정 → na/VAL_SRC_NOT_RUN | 실제 코어 행은 항상 `code`·`reason`(문구)을 가진다. 백엔드는 행 `code`·`reason` 우선, 행이 없거나 code 가 없을 때만 계획 열(`load` None → 열 `na`, 아니면 `VAL_SRC_NOT_RUN`) |
| B | §7.1 compare 파일 없음 | 판정 불가 출처의 `?src=` field·disp-field = 409 `PREREQUISITE_MISSING`(legacy 와 같은 코드), 출처 validation 응답의 `field`·`disp` = null — 화면이 이 값으로 해당 카드를 끄고 안내 문구를 보인다(실측: `worker/tests/test_val_src_e2e.py`, `full_solve: never`) |
| C | 목 서버 `?demoValSrc` | 기본 `old`(옛 서버 = 404 → 탭 없음), `ok`·`notrun` 은 시연 전용. 실제 응답과의 차이(경계력 반력 역할 info·내력 한계 등)는 목 데이터 값일 뿐 형식은 같음 |
| C | `styles.css` | `.val-src-tabwrap .seg button` 패딩 4줄(+주석) — 판정 카드 머리 줄 높이 불변 |
| C | §14.1 시험 21(DOM 높이 측정 vitest) | **미작성** — jsdom 은 레이아웃이 없어 측정 불가. 2560×1440 Playwright 로 v0.24.2·v0.24.3 높이를 B 가 확인(`/home/claude/shots/pw_v0243.mjs`, 높이 동일). 통합 때 실제 응답 스크린샷은 만들지 않고 아래 vitest 로 대체 |
| 통합 | 실연동 시험 | `worker/tests/test_val_src_e2e.py`(실제 코어·워커 등록·API: 전부 done / 자료 없음 / 옛 검증 / full_solve never 판정 불가), 프런트 `v0243_real_backend.test.ts` ← `fixtures/real_v0243.json`(실제 응답 저장, 재생성 방법은 시험 머리말) |

측정(A, 합성 평판 21,901 노드·2코어): 검증 출처 끔 9.5 s → 켬 12.2~12.4 s(+29~30 %), 05_val 5.2 MB → 15.5 MB.
