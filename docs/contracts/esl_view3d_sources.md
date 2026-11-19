# 계약: 3D 보기 하중 출처 일반화 — Case ③ ESL·강성 스터디가 같은 출처 표로 하중·응답·재현 3D (V3D, v0.24.1)

- 상태: **초안 → 구현 기준**(2026-11-19). 브랜치 `release/v0.24.1`(main 9d8b7168 = v0.24.0).
- 버전: **v0.24.1**. DB migration **없음** — 새 값은 Case 파생 캐시 새 폴더(`runs/<id>/view3d_<src>…`)·스터디 view3d 폴더 안 새 파일(`recon.json`·`recon.bin`)·사이드카 새 키·API 새 경로/선택 인자.
- 관계: `esl_3d_load.md`(Case 3D 형식·캐시·ETag) · `esl_jig_view.md`(하중 출처 표 RANK_SOURCES ↔ LOAD_SOURCES, 3D 다시 만들기 §3) · `esl_bforce.md`·`esl_fint.md`(노드 힘 출처·`04_esl/{bforce,fint}.npz`·추가 계산 §5.2) · `esl_disp_primary.md`(`05_val/compare_disp.npz`). 충돌하면 이 문서 범위에서는 이 문서가 우선.
- ID: 결정 `D-0.24.1-V3D-n`, 시험 `V-0241-V3D-n`, 후속 `R-V3D-n`.

### 사용자 요청 (원문, 변경 금지)
1. (2026-11-19) "3d컨투어가 전체esl만 되고 다른건 안되는데 범용적으로 개선"
2. (같은 날, 코디네이터 경유 범위 추가) "3D 다시 만들기"(지그 전용)도 출처 표 기반으로 일반화 — 옛 URL·동작 하위 호환, 버튼은 필요할 때만.

---

## 0. 감사 (v0.24.0, 읽기만)

### 0.1 화면 × 출처 → 현재 상태

열: **하중색** = 면압·법선·크기 컨투어, **화살표** = 상위 N·군집 합력, **응답** = 그 하중으로 정적 풀이한 변위 컨투어, **재현** = 목표 | 재현 | 오차. ✓ 있음 · ✗ 없음 · – 해당 없음.

| 화면 | 출처 | 하중색 | 화살표 | 응답 | 재현 | 원인(§0.2) |
|---|---|---|---|---|---|---|
| S1 Case ③ ESL 3D(`Stage4` View3DCard + LoadTable) | 전 노드 `full` | ✓ 면압(없으면 \|Fn\|) | ✓ | ✗(변형 = 목표 u_rel 만) | ✗(⑤ 검증 2D·단면에만) | C1·C6 |
| | 경계력 `bforce` | ✗ | ✗ | ✗ | ✗(숫자 한 줄 `esl-bforce-line` 만) | C1·C2·C3·C4·C5 |
| | 내력 `fint` | ✗ | ✗ | ✗ | ✗(숫자 한 줄 `esl-fint-line` 만) | C1·C2·C3·C4·C5 |
| | 지그 `jig` | ✗ | ✗ | ✗ | ✗ | C9(Case 산출 없음) |
| S2 스터디 설계 비교 3D(`Compare3D`, 탭 4개) | `full` | ✗(색 = 변위 고정) | ✓ | ✓ `post/view3d/<did>`·`d000[_e<kk>]` | –(목표 = 자기 응답) | C7 |
| | `jig` | ✗ | ✓ | ✓ `<did>_jig`·`d000_jig_e<kk>` | ✓ S3 | C7 |
| | `bforce` | ✗ | ✓ | ✓ `<did>_bf`·`d000_bf_e<kk>` | ✗ | C7·C8 |
| | `fint` | ✗ | ✓ | ✓ `<did>_fi`·`d000_fi_e<kk>` | ✗ | C7·C8 |
| S3 스터디 지그 진단 3D(`JigDiag`) | `jig` 만 | –(영역 색) | ✓ 영역 합력 | ✓ 맞춤 | ✓ 목표·맞춤·오차 3폴더 | 설계상 지그 전용 |
| S4 비드 선택·PartView 3D(`PartStage`) | – | – | – | – | – | 하중 출처 개념 없음(범위 밖) |

### 0.2 원인 (파일:행)

| # | 원인 | 근거 |
|---|---|---|
| C1 | Case 3D 백엔드 입력이 전 노드 ESL 파일로 고정 — `f_eq.npz`·`u_rel.npz` 만 읽음 | `backend/esl_platform/api/services/view3d.py:44-47`(Inputs), `:59-63`(키 문서 inputs 4파일), `:117-133`(_load) |
| C2 | 출처 인자 없음 — 라우터·클라이언트·훅이 run_id 만 | `routers/results.py:60-73`, `frontend/src/api/endpoints.ts:48`, `frontend/src/view3d/useLoadView.ts:30,49-50` |
| C3 | Case 화면이 카드 1개·출처 선택 없음 | `frontend/src/stages/Stage4.tsx:95`(useLoadView), `:154-163`(View3DCard·LoadTable) |
| C4 | manifest 실패 폴백이 `/forces?top=100`(전 노드 전용) — 다른 출처에 붙이면 틀린 표 | `useLoadView.ts:57-63`, `routers/results.py:28-31` |
| C5 | 파일 URL 에 이미 `?` 가 있으면 `key` 를 안 붙임 → 출처 쿼리를 달면 409 VIEW3D_STALE 감지가 사라짐 | `frontend/src/view3d/fetchFiles.ts:12` |
| C6 | Case 산출물의 응답 변위: 전 노드 = `04_esl` 에 없음(⑤ 검증 `05_val/compare_disp.npz` d_val·d_rel, 전체 풀이 시에만), 경계력·내력 = `04_esl/{bforce,fint}.npz` 의 `u_val`(ESL 단계 재현 풀이를 했을 때만 — `full_solve_decision`) | `esl/pipeline.py:1163-1187`(_nodal_recon), `:1244-1248`·`:1335-1339`(npz f·f_raw·m·u_val), `:1732-1734`(compare_disp), `esl/report/field.py:357`(arrays node_id·d_rel·d_val·e) |
| C7 | 스터디 3D 색이 변위로 고정 — values.bin 에 pa·fn·fmag 가 이미 있는데 하중 색을 고를 수 없음 | `frontend/src/pages/doe/DoeStudy.tsx:1008`(Compare3D opts), `:919`(JigDiag opts), `esl/view3d.py:490`(pack_values 4배열 항상) |
| C8 | 스터디 노드 힘 출처 3D 는 응답만 — 목표(sm_ref) 대비 재현 3D 없음(지그만 진단) | `esl/doe/stages.py:4786-4825`(_ns_view3d), 지그 대비 `:4205-4216`(tgt·fit·err) |
| C9 | 지그 ESL 은 스터디 기준 메시에서만 계산(`prep/jig.npz`) — Case 파이프라인에 지그 없음 | `esl/pipeline.py`("jig" 0회), `stages.py:3984-3999` |

### 0.3 자료 만들기(3D 다시 만들기·출처 계산) 감사

| 동작 | URL | 가능 조건 | 만드는 것 | 버튼 위치 | 문제 |
|---|---|---|---|---|---|
| 3D 다시 만들기 | `POST /doe/studies/{sid}/view3d/regenerate` | 지그 블록 ok·poor(`services/doe.py:1914-1917`, 아니면 409 VIEW3D_REGEN_UNAVAILABLE `:2007-2009`) | 지그 응답 3D(없을 때)·지그 진단·rank_views{jig, full}(`stages.py:4400-4430`) | 지그 탭 3D 머리 **또는** rank_views 없으면 **어느 탭이든**(`DoeStudy.tsx:1022-1026`, D-0.23.3-8 ②) | 지그 전용 이름·경로, 전 노드 탭에도 지그 버튼 |
| 경계력/내력 ESL 계산 | `POST /doe/studies/{sid}/sources/{src}`(src ∈ NODAL_SOURCES, 모르면 404 SOURCE_NOT_FOUND `:2032-2035`) | 계획 열 bf = base | `prep/<file>*`·안 사이드카·`post/<file>_view.json`·3D | **모든 탭** 3D 머리에 빠진 출처마다 1개(`DoeStudy.tsx:1027-1029`) | 한 화면에 버튼 최대 3개, 활성 탭과 무관 |

두 경로는 같은 큐·같은 권한(`_regen_block`)·같은 resume(BD_POST)이고 다른 것은 `params.kind`·`doe.post_mode` 뿐 → **출처 인자 하나로 합칠 수 있다**(§5.2).

---

## 1. 목표 · 범위

1. 모든 3D 보기가 **하나의 하중 출처 키 집합** `jig | full | bforce | fint`(§2.1)로 출처를 고른다. Case 계획 표·스터디 출처 표·화면 표가 같은 키·같은 순서·같은 이름. 호출부는 **표의 열만 읽고 출처 이름으로 분기하지 않는다**(AGENTS.md). 새 출처 = 각 표에 행 추가만으로 3D 가 붙는다.
2. 출처마다 같은 3D 구성(§2.2) — 출처가 가진 값만 보이고, 없는 값은 비활성 + 사유.
3. Case ③ ESL 3D 카드에 출처 탭(P1 — 사용자 요청의 핵심). 스터디는 빠진 하중 색·노드 힘 출처 재현을 같은 방식으로 채움(P2·P3). 자료 만들기 일반화(P2).
4. 범위 밖: 내보내기 하중 출처(R-BF-2), 설계안 분해 공유(R-BF-3), Case 에서 지그 계산(R-V3D-1).

## 2. 출처 표

### 2.1 키·순서·이름 (한 곳씩, 시험이 셋이 같음을 확인)

| 순서 | key | 화면 이름 | 코어 Case 계획 | 코어 스터디 | 화면 |
|---|---|---|---|---|---|
| 1 | `jig` | 지그 ESL | `esl/view3d_src.py:CASE_PLAN` | `esl/doe/stages.py:RANK_SOURCES` | `frontend/src/view3d/sources.ts:SOURCE_ROWS` |
| 2 | `full` | 전 노드 ESL | 〃 | 〃 | 〃 |
| 3 | `bforce` | 경계력 ESL | 〃 | 〃 | 〃 |
| 4 | `fint` | 내력 ESL | 〃 | 〃 | 〃 |

- `esl/view3d_src.KEYS = ("jig", "full", "bforce", "fint")` = `tuple(r["key"] for r in RANK_SOURCES)` = `SOURCE_ROWS.map(r => r.key)`. 화면 이름·탭 툴팁은 `SOURCE_ROWS` 한 곳 — `doeTabs.LOAD_SOURCES` 의 `label`·`title` 은 `SOURCE_ROWS` 에서 가져온다(값 동일, 중복 제거).
- 비활성 사유 형식은 공용 순수 함수 `unavailText(label, why) = "<이름> 불가 — <사유>"`(지금 `nodalUnavailable` 형식) — Case·스터디 같은 문구 형식.

### 2.2 출처 3D 구성 (보기 4개 — 모든 출처 같은 구성)

| 보기 | 색 | 변형 | 화살표 | 값 출처 |
|---|---|---|---|---|
| **하중** | 하중 성분 선택: 면압 \|Fn\|/A(기본 — 지금 colorField) · 법선 \|Fn\| · 크기 \|F\| | 하중 보기 u(Case = 목표 u_rel, 스터디 = 그 폴더 응답) | 상위 N·군집(지금 그대로) | `values.bin` pa·fn·fmag(이미 있음) |
| **목표** | \|u_tgt\| | u_tgt | 같은 하중 화살표 | 재현 파일 tgt(없으면 Case = values.bin u = u_rel) |
| **응답** | \|u_fit\| | u_fit | 〃 | 재현 파일 fit(Case) / 응답 폴더 values.bin u(스터디) |
| **오차** | \|u_fit − u_tgt\| | 오차 | 〃 | 재현 파일 err |

- 목표·응답 = 같은 색 범위(자동 = max(tgt_max, fit_max)), 오차 = 자기 범위(err_max), 하중 = 지금 p99 규칙. 수동 범위는 묶음(하중 | 목표·응답 | 오차)별.
- 재현 수치 한 줄: `재현 MAC 0.934 · umax 오차 −4.1 % · 강체 제거 <rigid>` — 정의는 `esl/mech/bforce.py:mac`·`recon_report` 그대로(§3).
- 값이 없으면 그 보기 버튼 비활성 + 사유(§2.5). 출처 자체가 없으면 탭 비활성 + 사유.

### 2.3 Case 계획 표 `esl/view3d_src.CASE_PLAN` (새 모듈 — 선언 + 순수 함수만)

열(모든 행이 모든 열을 가짐 — 키 누락 = `CONFIG_INVALID`, 값 `None` = "이 출처에 없음"):

| 열 | 뜻 |
|---|---|
| `key` | 출처 키 |
| `legacy` | `True` = `?src` 없는 옛 URL 이 이 행(정확히 1행). 키 문서에 `src` 를 넣지 않고 폴더·URL 도 옛것 → 바이트 동일 |
| `load` | 하중 `(위치, 파일, 배열)` |
| `target` | 하중 보기 u(변형·군집) `(위치, 파일, 배열)` |
| `resp` | 응답 변위 `(위치, 파일, 배열)` |
| `recon_tgt` | 재현 오차 기준(목표) `(위치, 파일, 배열)` — resp 와 같은 강체 제거 규칙의 짝 |
| `rigid` | 재현 쌍 강체 제거 규칙(문구·시험용): `kabsch`(S4 remove_rigid) \| `linear`(검증 remove_linear_rigid) |
| `support` | 지지 표시: `bc` = `03_bc/support.json`(없으면 run.supports — 지금 `_supports`) |
| `summary` | ESL 실행 `forces.<summary>` 요약 키(code·reason·recon 상태) — `None` = 요약 없음(파일 존재로만 판정) |
| `doc` | 응답 생략 사유를 읽을 진단 json `(위치, 파일)`(`recon.reason`) |
| `dir` · `recon_dir` | 파생 캐시 `runs/<id>/<dir>/`(하중 보기) · `runs/<id>/<recon_dir>/`(재현) |
| `na` · `resp_na` | 출처 없음 · 응답 없음 기본 사유 코드(요약 code 가 있으면 요약 우선) |
| `fallback` | manifest 실패 시 `/forces?top=100` 표 폴백 허용(C4 — 전 노드 전용 자료라 legacy 행만 `True`) |

위치 토큰: `esl` = `co.esl_source_dir(cdir, run)/04_esl`(스냅샷 우선 — 지금과 같음), `val` = 그 ESL 실행의 최신 검증 05_val(`services/results.locate_validation_dir` 재사용 — 스냅샷 표식 → Case 05_val → `_backup` 표식).

| key | legacy | load | target | resp | recon_tgt | rigid | support | summary | doc | dir / recon_dir | na | resp_na | fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `jig` | F | None | None | None | None | None | None | None | None | None / None | `V3D_STUDY_ONLY` | `V3D_STUDY_ONLY` | F |
| `full` | **T** | esl `f_eq.npz` f | esl `u_rel.npz` u_rel | val `compare_disp.npz` d_val | val `compare_disp.npz` d_rel | linear | bc | None | None | `view3d` / `view3d_recon` | `PREREQUISITE_MISSING`(지금 409 그대로) | `V3D_RESP_NEED_VAL` | T |
| `bforce` | F | esl `bforce.npz` f | esl `u_rel.npz` u_rel | esl `bforce.npz` u_val | esl `u_rel.npz` u_rel | kabsch | bc | `bforce` | esl `bforce.json` | `view3d_bforce` / `view3d_bforce_recon` | `V3D_SRC_NOT_RUN` | `V3D_RESP_SKIPPED` | F |
| `fint` | F | esl `fint.npz` f | esl `u_rel.npz` u_rel | esl `fint.npz` u_val | esl `u_rel.npz` u_rel | kabsch | bc | `fint` | esl `fint.json` | `view3d_fint` / `view3d_fint_recon` | `V3D_SRC_NOT_RUN` | `V3D_RESP_SKIPPED` | F |

- `bforce.npz` f = F_bal(기준계 풀이 하중 — S4 Kabsch 회전 후, 3-2-1 재현에 쓴 그 하중), u_val = 같은 3-2-1 해 Kabsch 강체 제거(`pipeline.py:1172-1173`) → 짝 u_rel(같은 규칙)과 오차·MAC 이 `bforce.json recon` 과 같아야 함(V-0241-V3D-11).
- 순수 함수 `case_status(row, summary: dict|None, have: dict[str,bool], doc_reason: str|None) -> {available, code, reason, resp, resp_code, resp_reason}` — 파일 IO 없음(호출부가 존재 여부·요약을 넘김). 규칙: load 파일·배열 없음 → 요약 code(BF_DISABLED·BF_NO_DATA·BF_FAILED·FINT_* — Case 가 쓴 reason 그대로) 있으면 그것, 없으면 행 `na`. resp 없음 → 요약 recon = skipped 이면 `resp_na` + doc 의 `recon.reason`, 그 밖 `resp_na`.

### 2.4 스터디 열 추가

| 표 | 새 열 | 값 |
|---|---|---|
| 화면 `doeTabs.LOAD_SOURCES` | `recon` | jig `{kind: "jigdiag"}`(지금 JigDiag 그대로) · full `null`(사유 `V3D_RECON_NA`) · bforce `{kind: "sidecar", key: "view3d_bf_recon"}` · fint `{kind: "sidecar", key: "view3d_fi_recon"}` |
| 〃 | `add` | jig `{src: "jig", label: "지그 3D 다시 만들기", testid: "v3d-regen", hint: REGEN_HINT_JIG}` · full `null` · bforce·fint = 지금 NodalCols 의 src·addLabel·addTestid·addHint 를 옮김(값·testid 동일) |
| 백엔드 `services/doe.py:SOURCE_ADD`(새, NODAL_SOURCES 옆) | 행 = 자료 만들기 가능한 출처 | jig `{kind: "VIEW3D", post_mode: "view3d", cfg: None, need: "jig_ok", code: "VIEW3D_REGEN", name: "지그 3D", legacy: "view3d_regen"}` · bforce `{kind: "BFORCE", post_mode: "bforce", cfg: "bforce", need: "plan", code: "BF", name: "경계력 ESL", legacy: "bforce_add"}` · fint `{… "FINT", "fint", "fint", "plan", "FINT", "내력 ESL", "fint_add"}` |
| 백엔드 `NODAL_SOURCES[*].v3d` | 4번째 키 | `view3d_bf_recon` · `view3d_fi_recon`(사이드카 통과 — 지금 루프 그대로) |
| 코어 `RANK_SOURCES` | (열 추가 없음) | 코어 dispatch(`bd_post` post_mode view3d·NODAL_BY_KEY)는 지금 그대로 — 새 열을 읽는 코드가 없으면 열을 만들지 않는다 |

`need` 값 → 조건 함수 표 `NEED = {"jig_ok": 지그 블록 ok|poor, "plan": 계획 열 ns["plan"] == base}`(열 값으로 함수 선택 — AGENTS.md).

### 2.5 사유 코드 (Case 문구 = 백엔드 `esl/view3d_src.REASON_TEXT` 한 곳, 응답에 문구 포함)

| 코드 | 문구(사유 부분) |
|---|---|
| `V3D_STUDY_ONLY` | 강성 평가 스터디에서만 계산됩니다(Case 산출물 없음) |
| `V3D_SRC_NOT_RUN` | 이 ESL 결과에는 없습니다(v0.24.0 이전 계산) — ESL 을 다시 계산하면 생깁니다 |
| `BF_DISABLED` · `FINT_DISABLED` | 설정에서 꺼짐(bforce.enabled · bforce.fint.enabled) |
| `BF_NO_DATA` · `FINT_NO_DATA` · `*_FAILED` | Case 요약 `reason` 그대로(예: FINT_NO_DATA_TEXT) |
| `V3D_RESP_NEED_VAL` | 응답 변위 없음 — ⑤ 검증에서 전체 풀이(validation.full_solve)를 하면 보입니다 |
| `V3D_RESP_SKIPPED` | 응답 변위 없음 — ESL 단계 재현 풀이 생략(<recon.reason>) |
| `V3D_RECON_NA`(스터디 full) | 목표 변위(sm_ref)가 이 하중의 응답 자체 — 재현 비교 해당 없음 |
| `V3D_RECON_NONE`(스터디 사이드카 없음) | 재현 진단 없음 — [<add.label>]로 다시 계산하면 생깁니다 |

스터디 문구는 지금처럼 `doeTabs.ts`(REGEN_HINT_* 옆) — 형식은 `unavailText` 공용.

## 3. 공용 계산 · 독립성

| 모듈 | 새 것 | 규칙 |
|---|---|---|
| `esl/view3d.py` | `RECON_SCHEMA = "esl/view3d_recon/1"`, `RECON_VERSION = 1`, `recon_fields(u_tgt, u_fit) -> {err, tgt_max, fit_max, err_max, mac, umax_tgt, umax_fit, umax_err}`(순수), `pack_disp(named) -> (bytes, arrays)`(int16×3 성분별 배율 = pack_values 의 u 규칙, 4바이트 정렬), `build_recon(out_dir, *, node_id, u_tgt, u_fit, key, src, rigid, esl_run_id) -> dict`(recon.bin 먼저, recon.json 마지막 — build_view 와 같은 "출력 폴더에 쓰는 빌더" 계열) | `pack_values`·`build_view` **수정 금지**(바이트 동일 — 회귀 시험 해시). mac·umax_err = `esl.mech.bforce.mac`·`recon_report` 정의 호출(식 복제 금지) |
| `esl/view3d_src.py`(새) | `KEYS`·`CASE_PLAN`·`REASON_TEXT`·`plan(key)`(모르는 키 → `EslError("SOURCE_NOT_FOUND")`)·`case_status(...)`·`check_plan()`(열 누락 = CONFIG_INVALID) | 선언 + 순수 함수만. 파일 IO·설정 해석 없음 |
| `worker/esl_worker/core_adapter.py` | `view3d_recon_build(out_dir, **kw)`·`view3d_src_plan()`·`view3d_case_status(**kw)` 래퍼(`_attr` 패턴) | 백엔드는 코어를 어댑터로만 |

**import 금지**: `esl/view3d.py`·`esl/view3d_src.py` → `esl.doe`·`esl.pipeline`·`esl_platform`·`esl_worker` 금지(허용: numpy, `esl.errors`, `esl.mech.bforce`). `stages.py` 는 `esl.view3d.build_recon` 을 import(역방향 아님). 시험이 모듈 import 그래프를 확인(V-0241-V3D-4).

## 4. 응답 변위 — 어디서 만드나 (결정 D-0.24.1-V3D-4)

**새로 풀지 않는다.** 이미 있는 해만 쓴다: 경계력·내력 = ESL 단계 `u_val`(`04_esl/*.npz`, 지금 저장됨), 전 노드 = ⑤ 검증 `compare_disp.npz`(d_rel·d_val). 없으면 응답·오차 보기 비활성 + 사유(`V3D_RESP_NEED_VAL`·`V3D_RESP_SKIPPED`).

| 대안 | 비용(현장 30만 노드급) | 판단 |
|---|---|---|
| 첫 요청 시 API 프로세스에서 3-2-1 풀이 | 직접법 `DIRECT_BYTES_PER_ELEM` 80 KB/요소 × 30만 ≈ **24 GB**(`pipeline.py:1364`), 수십 초 — 생성 세마포어 1개·`build_wait_s` 60 s 넘김 | **불가** |
| ESL 단계에서 전 노드 ESL 응답 풀이 추가 | ESL 시간 ≈ ⑤ 검증 전체 풀이만큼 증가, ⑤ 와 같은 풀이 중복 | 안 함(미결 Q1) |
| 저장된 해 + 첫 요청 파생 캐시(채택) | 산술·양자화만 O(N) — recon.bin 18 B/노드 ≈ **5.4 MB**, 하중 보기 폴더 ≈ glb 36 B/노드(위치 8 + ID 4 + 사각 요소 삼각형 2×12) + values 12 B/노드 ≈ **14 MB**(추정) | 채택. 출처 탭을 열 때만 생김 → 실행당 최대 ≈ 3×14 + 3×5.4 ≈ 58 MB |

- 재현 캐시는 하중 보기와 **다른 폴더·다른 키**(`recon_dir`) — 검증을 나중에 해도(compare_disp 생김) 재현만 새로 만들고 하중 보기·legacy 폴더는 그대로.
- 재현 키 문서 `{"recon_version", "esl_run_id", "src", "inputs": [stat(recon_tgt 파일), stat(resp 파일), stat(model.npz)]}`(상대경로·size·mtime_ns — 지금 `_stat` 그대로). 노드 ID 가 model 순서와 다르면 ID 로 재정렬, 집합이 다르면 500 `OUTPUT_INCONSISTENT`(지금 규칙).

## 5. API

### 5.1 Case (`routers/results.py`, `services/view3d.py`)

| 경로 | 동작 |
|---|---|
| `GET /esl-runs/{id}/view3d?src=<key>` | `src` 없음 = legacy 행(`full`) — **지금 코드 경로 그대로**(Inputs·키 문서·폴더 `view3d/`·URL·ETag·응답 JSON 바이트 동일). `?src=full`(= legacy) 도 같은 응답. 그 밖 행: Inputs 를 행 열로(load·target·support·model), 키 문서에 `"src": key` 추가, 폴더 = 행 `dir`, 파일 URL = `/esl-runs/{id}/view3d/<name>?src=<key>`. 응답 스키마 `View3dOut` **변경 없음**(새 필드 없음 — legacy JSON 바이트 보존). |
| `GET /esl-runs/{id}/view3d/{part.glb,part_lod.glb,values.bin}?src=&key=` | 같은 규칙으로 행 폴더. key 다르면 409 VIEW3D_STALE(지금). |
| `GET /esl-runs/{id}/view3d/sources`(새) | `View3dSourcesOut` — 출처 표 순서 행마다 상태(§2.3 `case_status`). stat·요약·작은 json 만 읽음(파일 안 씀). 오류 판정은 manifest 와 같음(VIEW3D_DISABLED·ESL_RUN_NOT_FOUND·ESL_RUN_FAILED·ESL_RUN_NOT_CURRENT). |
| `GET /esl-runs/{id}/view3d/recon?src=`(새) | `View3dReconOut`(recon.json + `values_url`), 첫 요청이 `runs/<id>/<recon_dir>/` 생성(tmp → atomic_replace, 이전 폴더 `_backup` 이동 — 지금 규칙), ETag = 재현 키, 304. `src` 없음 = legacy 행. |
| `GET /esl-runs/{id}/view3d/recon.bin?src=&key=`(새) | 재현 배열. key 다르면 409 VIEW3D_STALE. |

오류: 모르는 src = **404 `SOURCE_NOT_FOUND`**{src, keys}(스터디 add_source 와 같은 코드). 아는 출처지만 이 실행에 산출 없음 = **409 `V3D_SOURCE_UNAVAILABLE`**{src, code, reason}(full 은 지금처럼 409 PREREQUISITE_MISSING). 응답 없음 = **409 `V3D_RECON_UNAVAILABLE`**{src, code, reason}. 크기 초과 = 지금 413 VIEW3D_TOO_LARGE(출처마다 같은 한도).

`EslRunOut` 은 바꾸지 않는다 — 출처 목록을 manifest 에 넣으면 같은 ETag 의 304 로 옛 JSON(목록 없음)이 재사용될 수 있어 별도 경로(D-0.24.1-V3D-3).

### 5.2 스터디 — 자료 만들기 일반화 (`services/doe.py`, `routers/doe.py`)

- `POST /doe/studies/{sid}/sources/{src}`: `src` ∈ `SOURCE_ADD` → jig 도 받음(kind VIEW3D·post_mode view3d — 지금 regenerate 와 같은 작업 params). `full` 등 행 없음 = 404 SOURCE_NOT_FOUND. 조건 = 행 `need`, 실패 코드 = 행 `code` 접두(jig = **VIEW3D_REGEN_UNAVAILABLE 그대로**, 노드 힘 = `<code>_UNSUPPORTED`·`<code>_ADD_UNAVAILABLE` 그대로). 노드 힘 행은 `doe.<cfg>_cfg` 사본(지금), jig 행은 없음(cfg None).
- `POST /doe/studies/{sid}/view3d/regenerate` = **별칭**(`add_source(src="jig")` 호출) — 요청·202 응답·409 코드·작업 params 바이트 동일.
- `DoeResultOut` 새 키 `source_add: {key: DoeView3dRegenOut}`(SOURCE_ADD 한 루프 — 가능 여부·허용·사유). 옛 키 `view3d_regen`·`bforce_add`·`fint_add` 는 같은 값 거울(행 `legacy` 열) — 화면은 새 키만 읽음.
- `DoeResultOut` 새 키 `view3d_bf_recon`·`view3d_fi_recon: {entry_id: dir} | null`(사이드카 `post/<file>_view.json` 에 있을 때만).
- `VIEW3D_FILES`(`services/doe.py:70`) += `recon.json`(application/json)·`recon.bin`(octet-stream) — 지금 `/doe/studies/{sid}/view3d/{did}/{name}` 경로 그대로.

코어(`stages._ns_view3d`): 기준 `d000_<pe>_e<kk>/` 를 쓴 뒤, 설정 `bead_doe.view3d.recon` 이 켜져 있고 `prep/sm_ref.npz` 에 `u`·`node_id`(once 형식 — `stages.py:3544-3545`; per_target 형식 `u_a_<k>` 만 있으면 재현 없음)와 그 엔트리가 있으면 `build_recon(od, …)` — tgt = sm_ref `u[엔트리]`(노드 ID 정렬, `[:, :3]` — 지그 진단 `:4181-4182` 과 같은 읽기), fit = 같은 폴더 응답 u, **둘 다 `esl.mech.kabsch.remove_rigid(X, ·)[0]`**(Case 재현과 같은 규칙, rigid "kabsch"), 결과 `view3d_<pe>_recon[entry] = 폴더`. 실패 = 경고 `VIEW3D_FAILED: <폴더> recon <code>`(실행 실패 아님). 같은 폴더의 기존 파일(manifest·glb·values)은 v0.24.0 과 같은 입력·같은 빌더 → 같은 바이트(created_at 제외). 기존 스터디는 [<출처> 계산]을 다시 누르면(`_post_nodal` 경유) 생김.

### 5.3 고정 필드 (`schemas.py` ↔ `frontend/src/api/types.ts`)

```
View3dSourcesOut { esl_run_id: str, default: str,
  rows: [{ key: str, available: bool, code: str|null, reason: str|null,
           resp: bool, resp_code: str|null, resp_reason: str|null, rigid: "kabsch"|"linear"|null }] }
View3dReconOut { schema: "esl/view3d_recon/1", recon_version: int, key: str, src: str, esl_run_id: str,
  n_nodes: int, rigid: str, bytes: int,
  arrays: [{ key: "tgt"|"fit"|"err", dtype: "int16", comps: 3, offset: int, scale: [float,float,float] }],
  ranges: { tgt_max: float, fit_max: float, err_max: float },
  mac: float|null, umax_tgt: float, umax_fit: float, umax_err: float|null, values_url: str }
DoeResultOut += source_add: {str: DoeView3dRegenOut}|null, view3d_bf_recon|view3d_fi_recon: {str: str}|null
```
스터디 `recon.json` = `View3dReconOut` 에서 `values_url` 만 없음(같은 빌더).

## 6. 화면

### 6.1 Case ③ ESL (`Stage4.tsx`) — 2560×1440 세로 높이 불변

- **카드 머리 줄**(지금 제목 줄 — 새 줄 없음): 오른쪽에 출처 탭 `SourceTabs`(스터디 `LoadTabSeg` 를 `frontend/src/view3d/SourceTabs.tsx` 로 옮긴 범용 — 같은 DOM·testid 규칙, tablist/tab/aria·화살표 키·비활성 사유 = 절대 위치 줄). 항목 = `SOURCE_ROWS` 순서·이름, 가능 = `sources.rows[].available`, 사유 = `unavailText(label, reason)`. 기본 탭 = 응답 `default`(설정 `view3d.case_src_default`). testid `v3d-src-tab`.
- **도구 줄**(지금 줄 — 앞에 붙임): 보기 세그먼트 [하중 | 목표 | 응답 | 오차](testid `v3d-mode`; 응답·오차 비활성 + 사유 = `resp_reason`), 하중 보기에서만 하중 색 선택(작은 select: 면압 · 법선 · 크기, testid `v3d-load-field`), 끝에 재현 한 줄(말줄임, 전체 = title, testid `v3d-recon-line`).
- **표**(`LoadTable`): 선택 출처 manifest 상위 행(지금 컴포넌트 그대로). manifest 실패 시 `/forces` 폴백은 행 `fallback` 이 참일 때만, 아니면 사유 한 줄만.
- 그대로 둠: 결과 카드 통계·`esl-bforce-line`·`esl-fint-line`·`esl-plastic-line`·경고·`v3d-state-note`·과거 실행(?run=) 규칙.
- `View3DCard` 선택 속성(안 주면 지금 동작): `headRight`(카드 머리 오른쪽), `toolsLead`·`toolsTail`(도구 줄 앞·끝), `dispOverride: {u: Float32Array, label: string} | null`(변위 색·변형에 이 u), `loadField: "pa"|"fn"|"fmag"|null`(null = 지금 colorField). 범위 기억 키 = `LoadView.rangeKey`(legacy = 지금 runId 그대로 → 저장된 범위 유지, 그 밖 `runId:src`).
- `useLoadView(runId, enabled, src?)`(src 없음 = legacy), `useRecon(runId, src, enabled)`(새), `resolveFileUrl` = URL 에 `?` 가 있으면 `&key=`(C5 — legacy URL 문자열은 지금과 같음).

### 6.2 강성 스터디 (`DoeStudy.tsx`·`doeTabs.ts`)

- **하중 색**: Compare3D 머리(지금 inline-actions 줄)에 [응답 변위 | 하중] 세그먼트(testid `v3d-color`) — 모든 출처, 두 카드 공통. 하중 범위 = 두 manifest 선택 성분 p99(없으면 max) 중 큰 값(같은 범위). 지그 진단 보기에는 없음(영역 색 유지).
- **재현 진단**: 행 `recon.kind == "sidecar"` 이면 [설계 비교 | 재현 진단] 세그먼트(지그 탭 [설계 비교 | 지그 진단]과 같은 자리·모양). 재현 진단 = 범용 `ReconDiag`: 엔트리 선택(`view3d_<pe>_recon` 키) + [목표·재현 | 오차] + 두 카드(왼쪽 목표 또는 오차, 오른쪽 재현 — JigDiag 와 같은 배치·같은 변형 공유 `deformSync`), 데이터 = 그 폴더 manifest·glb·values + recon.bin(`dispOverride`), 수치 한 줄(MAC·umax 오차·강체 제거). `kind == "jigdiag"` = 지금 JigDiag 그대로. `null` = 세그먼트 없음(툴팁 사유 `V3D_RECON_NA`).
- 응답 쌍 `view3d: "pair"`·조건 줄·설명 문구 그대로.

### 6.3 자료 만들기 버튼 — 필요할 때만, 화면에 최대 1개 (D-0.24.1-V3D-9)

- `tabState` 에 `add: Record<key, boolean>` = 보기 없음 ∧ `source_add[key].available` ∧ `allowed`. 그런 탭은 **선택 가능**(모양 = 흐린 글자 + "+" 접미, title = 사유), 본문 = 사유 한 줄 + 행 `add` 버튼 1개(`SourceAddPanel`) — 순위표·ESL별 표·3D 대신.
- 보기가 있는 탭에서 그 출처 3D 일부가 없을 때(지그: 진단·rank_views·선택 안 지그 응답 — 지금 needRegen 지그 분기, 노드 힘: 재현 사이드카) → **그 탭** 3D 의 빈 칸(Empty) 안에 그 행 버튼.
- 다른 출처의 버튼을 활성 탭 3D 머리에 두지 않는다(`DoeStudy.tsx:1022-1031` 의 비지그 탭 RegenButton·전 탭 NodalAddButton 루프 제거 — 버튼은 위 두 자리로 이동, 기능 삭제 없음). D-0.23.3-8 ② 개정.
- `allowed` 아님(권한·작업 중) = 탭 비활성 + 그 사유(지금 문구).

## 7. 설정 (DEFAULTS · pydantic · yaml 2개 — 같은 이름)

| 키 | 기본 | 위치 |
|---|---|---|
| `view3d.case_src_default` | `full` | `backend/esl_platform/core/config.py:View3dCfg`(검증: KEYS 중 load 가 있는 행, 아니면 CONFIG_INVALID) · `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml` `view3d:` |
| `bead_doe.view3d.recon` | `true` | `esl/doe/__init__.py` DEFAULTS `view3d` · DOE pydantic · yaml 2개 `bead_doe.view3d` 줄 |

캐시 한도(`max_nodes`·`max_glb_bytes`·`build_wait_s`)·생성 세마포어는 지금 키를 출처마다 같게 적용(새 키 없음). 하드코딩 금지: 화면 기본 탭은 응답 `default`, 재현 MAC 경고 기준은 Case 요약 `recon_mac_min`(D-0.24.0-BF-11 ③), 스터디 지그 기준은 `jig.th`.

## 8. 하위 호환

1. Case legacy(`src` 없음·`full`): 키 문서·폴더·manifest.json·part.glb·part_lod.glb·values.bin·응답 JSON·ETag **바이트 동일**. `/forces` 불변. `EslRunOut` 불변.
2. 스터디 옛 결과: result.json·ranking.csv·per_esl.json·report.html·post/*_view.json·post/view3d/* 불변(읽기만). 새 키는 null, 옛 키(view3d_regen·bforce_add·fint_add) 값 동일.
3. 새 스터디 실행: 기존 이름 폴더의 기존 파일은 v0.24.0 빌더 출력과 같은 바이트(created_at 제외), 새 파일만 더함.
4. `POST …/view3d/regenerate` 요청·응답·코드 동일. `POST …/sources/{bforce|fint}` 동일.
5. DB migration 없음. 작업 유형·큐·`POST_ONLY_KINDS` 그대로(VIEW3D·BFORCE·FINT).
6. 정보 삭제 없음 — 지금 보이는 요소는 모두 남고 버튼은 자리만 옮김(§6.3).

## 9. 시험 (V-0241-V3D-n)

| # | 단위 | 내용 |
|---|---|---|
| 1 | 모듈 | `recon_fields` 합성: fit = tgt → err 0·mac 1·umax_err 0; fit = 2·tgt → mac 1·umax_err 1; 직교 → mac 0; 영 → mac None. 무작위 배열에서 mac·umax_err = `bforce.recon_report` 와 같음(1e-12) |
| 2 | 모듈 | `pack_disp`·`build_recon` 왕복: 복원 오차 ≤ s/2, offset 4바이트 정렬, 전부 0 → scale 0, recon.json 이 recon.bin 뒤에 쓰임(부분 쓰기 시 json 없음) |
| 3 | 회귀 | 고정 합성 입력의 `build_view` part.glb·values.bin·manifest(created_at 제외) sha256 = v0.24.0(main 9d8b7168) 값 — 골든을 변경 전에 기록 |
| 4 | 계획 | `KEYS` = RANK_SOURCES 키 순서; CASE_PLAN 모든 행 모든 열(누락 → CONFIG_INVALID); legacy 행 정확히 1개·dir "view3d"; `fallback` 참 = legacy 행만; `esl.view3d`·`esl.view3d_src` 가 esl.doe·esl.pipeline·esl_platform 을 import 하지 않음 |
| 5 | 계획 | `case_status` 표: (load 있음/없음 × 요약 code 없음/BF_DISABLED/BF_NO_DATA/BF_FAILED × u_val 있음/없음·recon skipped) → available·code·reason·resp 기대표; jig → V3D_STUDY_ONLY; 옛 실행(요약 없음·npz 없음) → V3D_SRC_NOT_RUN |
| 6 | API | v0.24.0 형식 Case 고정본: `GET /view3d`(src 없음) 응답 JSON·ETag·세 파일 바이트 = 변경 전 골든, `?src=full` 같음, `runs/<id>/` 아래 새 폴더 0 |
| 7 | API | `?src=bforce`: `view3d_bforce/` 생성, manifest top = bforce.npz f 의 \|F\| 내림차순(`/forces` 와 같은 lexsort 규칙), ETag ≠ full, 파일 URL `?src=bforce`, 다른 key → 409 VIEW3D_STALE, legacy 폴더 mtime·바이트 불변 |
| 8 | API | `?src=xyz` 404 SOURCE_NOT_FOUND · `?src=jig` 409 V3D_SOURCE_UNAVAILABLE code V3D_STUDY_ONLY · bforce.npz 없음(옛 실행) code V3D_SRC_NOT_RUN · 요약 BF_NO_DATA → code·reason 그대로 |
| 9 | API | `/view3d/sources`: 행 순서 = KEYS, 고정본 변형 4종(옛·bforce만·fint만·검증 있음)별 기대값, 호출 뒤 Case 폴더에 새 파일 0 |
| 10 | API | `/view3d/recon?src=full`: 검증 없음 → 409 V3D_RECON_UNAVAILABLE code V3D_RESP_NEED_VAL; compare_disp 고정본 → err = d_val − d_rel(양자화 내), rigid linear; 나중에 compare_disp 를 만들면 재현 키만 바뀌고 하중 보기 폴더 불변 |
| 11 | API | `/view3d/recon?src=bforce`: 복원 err ≈ u_val − u_rel, mac = bforce.json recon.mac(1e-9); u_val 없음 → V3D_RESP_SKIPPED + recon.reason |
| 12 | API | 출처 폴더 키 변경 시 이전 폴더 `_backup/<ts>/runs/<id>/<dir>` 로 이동(삭제 없음), 세마포어 대기 초과 503 VIEW3D_BUSY(출처 무관 같은 규칙) |
| 13 | 스터디 | `_ns_view3d`: d000_<pe>_e<kk>/ 에 recon.json·recon.bin, 기존 파일 바이트 = v0.24.0(created_at 제외), `view3d_<pe>_recon` 사이드카 키; `bead_doe.view3d.recon: false` → 새 파일 0; sm_ref 없음 → 키 없음·경고 없음 |
| 14 | 스터디 | `POST /sources/jig` ≡ `/view3d/regenerate`(작업 params·202 본문·409 코드 같음); `/sources/full` 404; `source_add` = 옛 키 거울; 옛 결과 DoeResultOut 옛 키 값 동일 |
| 15 | vitest | `SOURCE_ROWS` 키·순서·이름 = LOAD_SOURCES; `unavailText` 형식; Case 탭 상태·사유 = sources 응답; 기본 탭 = default |
| 16 | vitest | `resolveFileUrl`: legacy URL 문자열 지금과 같음, `?src=` 있으면 `&key=` |
| 17 | vitest | `useLoadView`: `/forces` 폴백은 legacy 행만; src 바꾸면 선택·단계 초기화; rangeKey legacy = runId |
| 18 | vitest | `View3DCard`: 새 속성 없으면 지금 렌더(필드 선택·범례 단위) 같음; loadField pa·fn·fmag 범위 = manifest ranges; 목표·응답 같은 범위·오차 자기 범위 |
| 19 | vitest | `tabState.add`·`SourceAddPanel`: 화면의 자료 만들기 버튼 수 ≤ 1(탭 4개 × 상태 조합), 지그 testid `v3d-regen`·경계력 `v3d-bf-add`·내력 `v3d-fi-add` 유지 |
| 20 | vitest | Compare3D `v3d-color` 토글·하중 공통 범위; `ReconDiag`(sidecar 행)·JigDiag(jigdiag 행) 선택이 열 값으로만(출처 이름 문자열 비교 없음 — 소스 grep 시험) |
| 21 | 화면 | Case 3D 카드: 탭 = card-head 안, 보기·하중 색·재현 줄 = v3d-tools 안(새 블록 줄 0 — DOM 시험), 2560×1440 스크린샷에서 카드 높이 = v0.24.0 |

## 10. 완료 기준

- §9 전부 통과 + 기존 시험 무수정 통과(옛 기대값 그대로), ruff·mypy·tsc·eslint 깨끗.
- Case 고정본에서 4탭: full(하중·목표 가능, 검증 고정본이면 응답·오차까지), bforce·fint(npz 있으면 하중·목표·응답·오차), jig 비활성 사유 — 수동 확인 스크린샷 `work/screens/v0241_case_v3d_*.png`.
- legacy 바이트 비교(V-3·6) 골든 파일이 커밋에 포함.
- `docs/decisions.md` D-0.24.1-V3D-1~10 반영, 계약과 다른 구현은 이 문서 부록에 기록.

## 11. 작업 분해 (파일 소유권 겹침 없음)

| 묶음 | 소유 파일 | 선행 |
|---|---|---|
| **A 코어** | `esl/view3d.py`(recon_fields·pack_disp·build_recon만 추가), `esl/view3d_src.py`(새), `esl/doe/stages.py`(`_ns_view3d` 재현만), `esl/doe/__init__.py`(DEFAULTS view3d.recon), `worker/esl_worker/core_adapter.py`(래퍼 3개), `tests/` 코어 시험(V-1~5·13) + 골든(V-3) | 없음 — 골든 먼저 기록 |
| **B 백엔드** | `backend/esl_platform/api/services/view3d.py`, `routers/results.py`, `services/doe.py`(SOURCE_ADD·add_source·regenerate 별칭·source_add·recon 키·VIEW3D_FILES), `routers/doe.py`, `api/schemas.py`, `core/config.py`(View3dCfg·DOE view3d.recon), `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`, `backend/tests/*`(V-6~12·14) | A(어댑터 이름·스키마 고정 후 병행 가능) |
| **C 프런트** | `frontend/src/view3d/{sources.ts,SourceTabs.tsx,useRecon.ts}`(새), `View3DCard.tsx`, `useLoadView.ts`, `fetchFiles.ts`, `values.ts`(decodeDisp), `stages/Stage4.tsx`, `api/{endpoints.ts,types.ts,doe.ts}`, `pages/doe/{doeTabs.ts,DoeStudy.tsx}`, `components/DoeRanking.tsx`(필요 시 SourceAddPanel 자리), vitest(V-15~21) | §5.3 필드 고정(B 와 병행), 통합 확인은 B 뒤 |
| 통합 | `CHANGELOG.md`·`VERSION`·이 문서 부록 | A·B·C 뒤(코디네이터) |

순서: A(골든 기록 → 모듈) → B·C 병행 → 통합(바이트 비교·스크린샷). 우선순위 P1 = Case 출처 탭(A의 view3d_src·B 의 5.1·C 의 6.1), P2 = 스터디 하중 색·자료 만들기 일반화, P3 = 스터디 재현 진단 — 시간이 모자라면 P3 를 R-V3D-2 로 미룸(계약 나머지는 그대로 성립).

## 12. 결정

- D-0.24.1-V3D-1 출처 키 하나(jig·full·bforce·fint, 순서 = RANK_SOURCES) — 코어 `view3d_src.CASE_PLAN`·`RANK_SOURCES`·화면 `SOURCE_ROWS`, 호출부 열만 읽음.
- D-0.24.1-V3D-2 출처 3D 구성 = 보기 4개 [하중(면압·법선·크기)|목표|응답|오차] + 화살표 — 가진 값만, 없으면 비활성 + 사유 코드(Case 문구 = REASON_TEXT 한 곳).
- D-0.24.1-V3D-3 Case API `?src=`(없음 = legacy 행 → 바이트·키·ETag 동일), 출처 폴더 = 행 dir, 키 문서 src, 404 SOURCE_NOT_FOUND / 409 V3D_SOURCE_UNAVAILABLE, 목록 = `/view3d/sources`(EslRunOut·View3dOut 불변).
- D-0.24.1-V3D-4 응답 변위는 새로 풀지 않음(저장된 u_val·compare_disp), 재현 = 첫 요청 파생 캐시(별도 폴더·키).
- D-0.24.1-V3D-5 재현 형식 공용 `build_recon`(recon.json + recon.bin tgt·fit·err int16×3) — Case·스터디 같은 스키마, 수치 = bforce.mac·recon_report 정의.
- D-0.24.1-V3D-6 Case 화면 = 카드 머리 출처 탭 + 도구 줄 보기·하중 색·재현 줄(세로 불변), `/forces` 폴백 legacy 행만.
- D-0.24.1-V3D-7 스터디 = 하중 색 토글(모든 출처) + 노드 힘 출처 재현 진단(목표 = sm_ref, 둘 다 Kabsch 강체 제거), full 재현 해당 없음.
- D-0.24.1-V3D-8 자료 만들기 = `POST …/sources/{src}`(SOURCE_ADD 행: jig·bforce·fint), regenerate = sources/jig 별칭, `source_add` + 옛 키 거울.
- D-0.24.1-V3D-9 버튼 = 계산 가능한 빈 탭은 선택 가능(본문 버튼) + 부분 누락은 그 탭 3D 빈 칸 — 화면 최대 1개(D-0.23.3-8 ② 개정).
- D-0.24.1-V3D-10 설정 `view3d.case_src_default`(full)·`bead_doe.view3d.recon`(true), migration 없음.

## 13. 후속 (R-V3D-n)

- R-V3D-1 Case 지그 ESL(엔트리 Case 에서 지그 분해 — 지금은 스터디 기준 메시 전용).
- R-V3D-2 (P3 를 미루면) 스터디 노드 힘 재현 진단.
- R-V3D-3 출처별 캐시 백업 정리(지금 legacy 와 같이 `_backup` 누적 — `regen_keep_backups` 같은 상한 검토). **후속 유지.** 실측(v0.24.1 검증): 실행당 파생 캐시 최대 약 58 MB, 30만 노드 하중 보기 첫 요청 약 2 s·RSS +약 90 MB.
- R-V3D-4 하중 보기 geometry 공유(LOD 가 하중 p 에 의존하므로 LOD 없는 부품만 — 디스크 절약).
- R-V3D-5 백엔드 응답 형식이 바뀌면 `frontend/src/__tests__/fixtures/real_v0241.json` 재생성(§15.3).

## 14. 미결 (가정대로 진행 가능)

- **Q1** 전 노드 ESL 의 응답·재현을 ⑤ 검증 없이도 보이게 ESL 단계에서 3-2-1 풀이를 추가할까? — **가정: 안 함**(검증 compare_disp 사용 — ESL 시간 증가·⑤ 와 중복 회피). 하면 full 행 resp 위치만 `esl` 로 바뀌고 나머지 계약은 그대로.
- **Q2** 스터디 재현 진단의 목표를 sm_ref(기준 메시 전 노드 ESL 응답 — 지그 진단과 같은 기준) 대신 Case 낙하 변위 u_rel 을 기준 메시로 옮긴 값으로 할까? — **가정: sm_ref**(지그 진단과 같은 목표 — 출처 간 수치 비교 가능). 바꾸면 MAC·오차 수치가 달라짐(구조 불변).

## 15. 구현 메모(2026-11-19)

통합(release/v0.24.1)에서 양쪽 인계 파일의 '계약과 다른 점'을 옮긴 표. 본문(§1~14)은 계약 원안 — 아래가 구현 사실이다.

### 15.1 백엔드·코어

| 항목 | 계약 | 구현 |
|---|---|---|
| 409 V3D_SOURCE_UNAVAILABLE·V3D_RECON_UNAVAILABLE detail | `{code(출처 사유), message, src, reason}` | `{code(오류 코드), message, src, reason_code, reason}` — detail.code 가 오류 코드라 출처 사유 코드는 `reason_code`. 화면은 `message`/`reason` 만 읽는다 |
| SOURCE_ADD 표 열 | key·kind·need 등 | 열 3개 추가: `plan`(계획 열 이름 — need plan 용), `block`(막힘 코드 접미 `_UNAVAILABLE`\|`_ADD_UNAVAILABLE`), `verb`(문구 동사구) |
| NEED 표 | — | (판정 함수, need 실패 접미 `_UNAVAILABLE`\|`_UNSUPPORTED`, 문구) |
| `DoeResultOut.source_add` | 행 전부 | need 를 만족하는 행만, 없으면 `null` — 옛 키(view3d_regen·bforce_add·fint_add)와 정확한 거울 |
| 404 SOURCE_NOT_FOUND 문구 | 가능 목록 | 목록 = SOURCE_ADD 키(jig 포함) |
| recon.json | created_at 포함 가능 | `created_at` 없음(재현 키·바이트 결정적) |
| 코어 공개 함수 | build_recon 등 | 추가: `view3d.unpack_disp`(시험·검증용), `view3d_src.reason_text·has_load·legacy_key·COLUMNS` |

### 15.2 프런트

| 항목 | 내용 |
|---|---|
| 머리 버튼 → 빈 탭 본문 이동 | D-0.24.1-V3D-9 에 따라 v0.24.0 의 3D 머리 버튼 위치가 바뀌어 옛 시험 4건의 조회 위치를 수정(기능 삭제 없음) |
| 옛 거울 키 폴백 | `view3d_regen`·`bforce_add`·`fint_add` 는 `source_add` 가 없는 옛 서버 응답용으로 유지 |
| 권한 없음 사유 | `source_add[src].allowed=false`(없으면 옛 거울 키)일 때: 버튼은 비활성 그대로 두고 그 옆에 서버 사유를 한 줄(`data-testid=source-add-why`, `small muted`)로 항상 보인다(마우스·포커스 불필요). 불가 사유 줄(`nodal-unavail-note`)은 "…다시 실행한 뒤 작성자·관리자에게 [버튼 라벨]을 요청하세요 (서버 사유)" 로 바뀌고 "다시 누르세요" 는 allowed 일 때만 |
| Case ③ 3D 도구 줄 높이 | 하중 색 `<select>` 가 줄을 36px 로 키우던 것을 `.v3d-tools select`(box-sizing·height 2rem = 같은 줄 check-field 높이)로 범위 한정해 v0.24.0 높이(34px)로 유지(V-21) |
| 옛 서버 폴백 | `/view3d/sources` 404 등 → 출처 탭 없이 v0.24.0 화면 그대로(`useCaseSources.failed`) |
| recon 로딩 중 | 응답·오차 보기를 여는 동안 0장(빈 화면) — 로딩 표시만, 이전 보기 값을 섞지 않음 |
| nodal-unavail-note | 현장 피드백으로 추가한 불가 사유 가시 줄(`data-testid=nodal-unavail-note`, 출처별) |

### 15.3 통합에서 맞춘 불일치

- `types.ts`: `View3dReconRanges` interface 추가(`View3dReconOut.ranges` 가 사용) → `check:api` 통과.
- 프런트 목 서버(`mock/server.ts`) 409 detail 의 출처 사유 키 `code` → `reason_code`(실제 백엔드와 동일). 화면 코드는 detail.code 를 출처 사유로 읽지 않음(확인).
- 실제 백엔드 응답 대조: `frontend/src/__tests__/fixtures/real_v0241.json`(Case run 1개 — /view3d/sources, ?src=bforce·fint 매니페스트·glb·values.bin, /view3d/recon·recon.bin) 을 `v0241_real_backend.test.ts` 가 프런트 파서(caseTabItems·defaultCaseSource·parseGlb·decodeValues·decodeDisp)에 먹여 정점 수·순서(재현 n_nodes = 하중 n_nodes = glb 정점 수, values.u ≈ recon.tgt)·배열 이름(tgt·fit·err)·범위 키(ranges.*_max = 복원 최대 크기)를 확인한다.
