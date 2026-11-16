# 계약: 재낙하 입력 묶음 받기 — 강성 평가 스터디 설계안 1개 → Radioss 입력 zip (REDROP, v0.22.0)

- 상태: **초안** (2026-11-16). 사용자 확정(아래) 반영, 결정 질문 2개(§12)는 기본안을 적용해 구현 가능.
- 버전: **v0.22.0** 제안 (main d809f31 = v0.21.0 기준 작성). migration **불필요**(DB 변경 없음 — §11).
- 관계: 검증 낙하(esl_scx_relay.md, `vd_patch`)와 **같은 원본 입력 폐포(`input_set`)·같은 노드 패치 코드(`esl/verify/patch.py`)** 를 쓴다. 다른 점은 좌표 출처(`best/<did>/include` 모핑 사본 → `run/designs/<did>/design.npz`), 순위 제한 없음, 플랫폼 제출 없음(zip 으로 내려받기만).
- ID 규칙: 결정 `D-0.22.0-RD-n`(decisions.md), 시험 `V-RD-n`, 리스크 `R-RD-n`.

### 사용자 확정 (2026-11-16, 변경 금지)
1. 사용자가 zip 을 받아 **직접 HPC 에 제출**한다. 플랫폼 제출은 이번 범위 아님.
2. 순위 1~`keep_files_top` 밖의 안(예: d020, d002, d025)도 받을 수 있다(`best/<did>/include` 에 의존하지 않음).
3. **SPDM·입력 폴더(input_roots·upload_root·Case 원본 폴더)에는 쓰지 않는다.** 쓰기는 `storage.esl_root` 아래만.
4. 값 하드코딩 금지: 기본값은 `esl/doe/__init__.py` DEFAULTS · backend pydantic · `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml` 에 같은 이름.
5. UI 는 필수 버튼 1개: 순위표에서 선택한 안에 대한 **"재낙하 입력 받기"**.
6. AGENTS.md 코드 구조 원칙(공용 계산 독립 모듈, 모드 차이는 계획 표 열, 시나리오 이름 분기 금지).

## 0. 조사 결과 (근거, main d809f31)

| 항목 | 위치·시그니처 | 이 계약에서 |
|---|---|---|
| 원본 입력 폐포 | `backend/esl_platform/api/services/verify_drop.py:input_set(settings, core, case) -> {rad, rad_dir, files[(rel, abs)], engines[], problems[(code, reason)]}` — starter rad + include 폐포(rad 폴더 상대) + 엔진 rad(`verify_drop.engine_globs`). problems: `VD_CUMULATIVE_EXCLUDED`(누적 Case·상태 include) · `VD_INCLUDE_LAYOUT`(절대경로·없음·rad 폴더 밖·링크·`include_path_map`) · `VD_ENGINE_MISSING` | 그대로 호출(수정 없음). problems 가 하나라도 있으면 거부 |
| 노드 패치 | `esl/verify/patch.py:patch_node_files(files, coords, out_dir, *, required=None, max_line=None, guard=None) -> {files[{rel, path, source orig\|patched, n_patched, size, sha256}], n_patched, found, missing[]}` — 바뀐 파일만 `out_dir/<rel>`, 바뀐 줄만 다시 씀(값이 같으면 바이트 그대로), `\r\n`/`\n` 보존, 누락 `VD_NODES_MISSING`(쓰기 전 판정), 비 ASCII 줄 `VD_PATCH_ENCODING` | 새 공용 함수 `patch_design` 이 감쌈(§5.1) |
| 검증낙하 패치 단계 | `esl/verify/stages.py:vd_patch(spec)` — `model.npz`(node_id, x0) + `nodes.morphed_coords(best_dir, best_rels, …)` → `coords` → `patch_node_files(required=nid)` → `morph.npz`·result json | `patch_design` 호출로 바꾸되 **산출 바이트 동일**(V-RD-12) |
| 안별 좌표 | `_doe/<sid>/run/designs/<did>/design.npz` = `node_id` int64 (N,), `x` (N,3) float64 (`esl/doe/evaluate.py:save_design`·`load_design`, `DESIGN_NPZ`). 평가 실패(`FAILED_MESH` 등)면 파일 없음 | 좌표 출처 |
| 기준 메시 | `_doe/<sid>/prep/base_mesh.npz`(`MESH_KEYS` — `node_id`, `x0` …) + `prep/base.json`(`esl/doe/scenario.py:load_base`, `BASE_NPZ`·`BASE_JSON`) | 노드 집합·이동량 기준 |
| 스터디 → 원 Case | `bead_does.base`(JSONB: `entry_id, case_id, case_title, part_title, rad_path, rad_file_name …` — `services/opt.py:_s1_base` → `services/doe.py` 의 `base_db`), `bead_does.entry_ids` → 라이브러리 항목 `case_id` | 기본 = `base.case_id` |
| 모드 표 | `esl/doe/transfer_plan.py:PLANS`/`PLAN_COLS`/`PLAN_OF`/`plan_for(scenario, select_base)` — `case_once`(same, select+case)만 원 Case 노드 ID 를 그대로 씀(`identity: topo`). `bmesh_once`·`step_once`·`step_per_design`·`compare_per_shape` 는 새 메시(새 노드 ID) | 새 열 `redrop`(§5.2) |
| select_base | 스터디 `inputs.select_base`(`"mesh"`\|`"step"`, ① = 키 없음 = `case`) | `plan_for` 인수 |
| zip 선례 | `api/routers/doe.py:doe_bundle` → `services/doe.py:bundle` → `{files[(abs, rel)], prefix, filename, size}` → `routers/results.py:zip_response` → `services/bundle.py:stream_zip(files, prefix)`; 크기 `bundle._check_size(ctx, files, where)` → 413 `BUNDLE_TOO_LARGE`(`ui.max_bundle_bytes`) | 같은 경로 재사용 |
| 쓰기 폴더 | `core/paths.py:esl_subdir(settings, *parts)`(루트 탈출·링크 검사), 상수 `EXPORTS_DIR="_exports"`·`VERIFY_DIR="_verify"`·`DOE_DIR="_doe"` | 새 상수 `REDROP_DIR="_redrop"` |
| 권한 | `services/doe.py:_viewable(ctx, principal, sid)` = `load_study`(404 `DOE_NOT_FOUND`) + `require_view` | 같은 함수 |
| 안 id 형식 | `services/doe.py:DID_RE = ^[0-9a-z_]{1,64}$` | 같은 정규식 |
| 프런트 | `F/components/DoeRanking.tsx`(`selected`·`onSelect`), `F/pages/doe/DoeStudy.tsx`(`pick` 상태, `Downloads extra=…`, `vdButton`), `F/components/BundleButton.tsx`(413 안내 내장, `label` prop), `F/api/doe.ts`(`bundleUrl`·`downloadUrl`) | 버튼 1개 |

## 1. API

| 메서드·경로 | 쿼리 | 응답 |
|---|---|---|
| `GET /doe/studies/{sid}/designs/{did}/redrop` | `case_id`(선택, 기본 = 스터디 `base.case_id`; 스터디 ESL 의 출처 Case 중 하나만) | 200 `application/zip` 스트리밍(`zip_response` — `Content-Disposition: attachment; filename="redrop_<did>_<sid 앞 8자>.zip"`, `X-Bundle-Files`, `X-Bundle-Bytes`). OpenAPI 는 `ZIP_RESPONSE` |

- **동기 스트리밍 + 임시 폴더**로 한다(D-0.22.0-RD-1). 근거: 결과 받기(`doe_bundle`)가 이미 동기 `stream_zip(files, prefix)` 이고 `stream_zip` 은 디스크 파일 목록만 받으므로, 패치 파일을 esl_root 아래 임시 폴더에 쓰고 원본 경로와 섞은 목록을 넘기는 것이 선례와 가장 덜 어긋난다(job·DB 행 추가 없음).
- 순서(전부 요청 안, 응답 시작 전): 권한 → 설정 → 안·계획 검사 → Case·`input_set` → 크기 사전 검사(원본 합계 + 메타 여유 `ui.max_bundle_bytes`) → 임시 폴더 생성 → `rd_prepare`(§5.3) → 파일 목록 확정 → 스트리밍. **응답이 시작된 뒤에는 오류 코드가 없다**(파일 목록·패치가 모두 끝난 뒤 스트리밍).
- 임시 폴더: `<esl_root>/_redrop/<token>/`(`token` = uuid4 hex, `esl_subdir(settings, REDROP_DIR, token)`). 내용 = 바뀐 파일(`input/<rel>`) + `redrop_manifest.json` + `REDROP_README.txt`.
  - 정리 ①: 스트리밍 제너레이터 `finally` 에서 `rmtree`(링크 따라가지 않음 — `esl_subdir` 로 다시 확인한 경로만).
  - 정리 ②: 요청마다 시작 시 `_redrop/*` 중 mtime 이 `bead_doe.redrop.tmp_ttl_s` 보다 오래된 항목을 지움(클라이언트 끊김으로 ① 이 안 돈 경우). 이름이 32자 hex 가 아니면 건드리지 않음.
  - 정리 ③: 오류(4xx) 로 끝나면 응답 전에 즉시 지움.
- 권한: 스터디 **읽기** 권한(`_viewable` — 결과 받기와 같음). 실행 권한은 요구하지 않음(제출하지 않으므로).
- 응답 순서·이름은 결정적(같은 입력 → 같은 zip 내용, 단 manifest `created_at`·`token` 제외).

**고정 필드명 (schemas.py ↔ types.ts, `check:api` 로 대조 — 이름 바꾸지 말 것)**

| 스키마 | 필드 |
|---|---|
| `DoeStudyOut` (추가) | `redrop_ok: bool`(계획 열·설정·base Case 기준 — 안별 검사는 요청 때), `redrop_blocked: str \| null`(불가 사유 한 줄, 가능하면 null) |

- `redrop_ok` = `bead_doe.redrop.enabled` ∧ 계획 열 `redrop == "node_id"` ∧ 스터디 `base.case_id` 있음. Case 상태·`input_set` 은 목록 응답이 느려지므로 **계산하지 않는다**(요청 때 판정).
- `redrop_blocked` 문구: 계획 불가 = "이 모드는 원 Case 노드 번호를 쓰지 않아 재낙하 입력을 만들 수 없습니다(① 같은 Case 기준만)", 꺼짐 = "재낙하 입력 받기가 꺼져 있습니다", base 없음 = "기준 Case 정보가 없습니다".

### 오류 코드

| HTTP | 코드 | 조건 | detail |
|---|---|---|---|
| 404 | `DOE_NOT_FOUND` | 스터디 없음(기존) | – |
| 403 | (기존 `require_view`) | 읽기 권한 없음 | – |
| 422 | `INVALID_PARAMS` | `did` 가 `DID_RE` 불일치, `case_id` 형식 오류 | – |
| 503 | `REDROP_DISABLED` | `bead_doe.redrop.enabled = false` | – |
| 422 | `REDROP_UNSUPPORTED` | 계획 열 `redrop == "none"` | `plan`(계획 id) |
| 404 | `REDROP_DESIGN_NOT_FOUND` | `run/designs/<did>/` 폴더 없음(그런 안 없음) | `design_id` |
| 409 | `REDROP_DESIGN_NOT_READY` | 폴더는 있으나 `design.npz` 없음(평가 실패·미평가) | `design_id`, `status`(result.json 의 status, 없으면 null) |
| 422 | `REDROP_CASE_NOT_IN_STUDY` | `case_id` 가 스터디 ESL 의 출처 Case 가 아님 | `case_id` |
| 409 | `REDROP_CASE_NOT_READY` | Case 없음·보관됨·다른 프로젝트, rad 파일 없음 | `case_id` |
| 422 | `VD_CUMULATIVE_EXCLUDED` · `VD_INCLUDE_LAYOUT` · `VD_ENGINE_MISSING` | `input_set` problems(첫 항목 코드) | `problems[{code, reason}]` 전부(경로 마스킹) |
| 409 | `REDROP_NODESET_MISMATCH` | design.npz `node_id` 집합 ≠ base_mesh `node_id` 집합, 또는 중복 ID | `n_base`, `n_design`, `n_only_base`, `n_only_design` |
| 422 | `VD_NODES_MISSING` | 대상 노드가 입력 폐포 `/NODE` 에 없음(코어 오류 그대로) | 메시지에 개수·상위 10 |
| 409 | `REDROP_BASE_CHANGED` | 원본 파일의 대상 노드 좌표가 base_mesh `x0` 와 `base_coord_tol_mm` 넘게 다름(스터디 뒤 Case 입력이 바뀜) | `n_changed`, `max_diff` |
| 422 | `RAD_PARSE_ERROR` | 같은 노드 ID 가 폐포 여러 파일에 다른 좌표로 있음 | – |
| 422 | `VD_PATCH_ENCODING` | 고칠 노드 줄에 비 ASCII(코어 오류 그대로) | – |
| 413 | `BUNDLE_TOO_LARGE` | 원본 합계 > `ui.max_bundle_bytes`(기존 `_check_size`, `path` = rad 폴더 표시 경로) | `size`, `limit`, `path` |

- 모든 메시지·detail 경로는 기존 `pathmask.masks_paths`/`scx_mask` 로 마스킹. 새 코드 문구는 서비스 안 문자열(기존 `DOE_NOT_FOUND` 방식). `resources/scx_messages.json` 은 고치지 않는다(VD_ 코드는 기존 문구 재사용).

## 2. zip 구성

```
redrop_<did>_<sid8>/
  REDROP_README.txt
  redrop_manifest.json
  input/
    <starter>.rad                 # rad 폴더 기준 상대 배치 그대로
    <stem>_0001.rad …             # 엔진 rad(input_set engines) — 포함
    <include rel path> …          # include 폐포 전부(하위 폴더 보존)
```

- `input/` 아래 = `input_set().files` 의 모든 `(rel, abs)` 를 **같은 rel** 로. 바뀐 파일은 임시 폴더의 패치본, 나머지는 원본 경로에서 직접 읽어 넣음(원본 복사 없음).
- 엔진 rad **포함**(HPC 제출에 필요, `input_set` 이 이미 폐포에 넣음). 엔진 rad 에 `/NODE` 가 없으면 원본 그대로.
- 결과 파일(h3d·`A001`·`.out`·`.sta`·`.str`·T01 등)은 **들어가지 않는다**: zip 은 `input_set` 폐포와 메타 2개만으로 만든다(폴더 통째 수집 없음). 상태 include 가 있으면 애초에 `VD_CUMULATIVE_EXCLUDED` 거부.
- 메타 파일을 `input/` 밖에 두어 입력 파일 이름과 충돌하지 않는다. 사용자는 `input/` 폴더를 그대로 HPC 로 올린다.

### 2.1 `redrop_manifest.json` (schema 1, 고정 키)

| 키 | 값 |
|---|---|
| `schema` | `"esl/redrop/1"` |
| `platform_version` | `esl_platform.__version__` |
| `created_at` | UTC ISO8601 |
| `study` | `{id, title, scenario, select_base, plan}` (`plan` = 계획 id, 예 `case_once`) |
| `design` | `{id, rank \| null, status \| null, values{변수: 값}}` — values·status = `run/designs/<did>/result.json`, rank = `post/result.json` ranking 행(없으면 null) |
| `case` | `{id, title, part_title, rad_file_name}` (절대경로 넣지 않음) |
| `files` | `[{rel, source: "orig" \| "patched", n_patched, size, sha256}]` — `input/` 기준 rel, 패치 함수 반환 그대로(원본 행의 sha256 = 원본 파일) |
| `changed` | `source == "patched"` 인 rel 목록 |
| `nodes` | `{n_target, n_moved, n_patched_lines, max_disp, max_disp_node_id, units: "model"}` — `n_target` = base_mesh 노드 수, `n_moved` = ‖x_design − x0‖ > 0 인 노드 수, `max_disp` = 그 최댓값 |
| `checks` | `{nodeset_equal: true, base_max_diff, base_coord_tol_mm}` |

### 2.2 `REDROP_README.txt`
한국어 평문(UTF-8, `\n`). 스터디·안·Case·변수 값·바뀐 파일·노드 수·최대 이동량 요약 + "input/ 폴더를 그대로 HPC 에 올려 starter rad 로 제출 / 원본 결과와 비교하려면 같은 엔진·버전 / 이 파일은 플랫폼이 만들었고 원본 폴더는 바꾸지 않았음". 본문은 `esl/verify/redrop.py:readme_text(manifest)` 가 manifest 만으로 만든다.

## 3. 허용 조건 (모두 만족해야 200)

1. 스터디 읽기 권한, `bead_doe.redrop.enabled`.
2. 계획 열 `redrop == "node_id"`(§5.2) — **시나리오 이름으로 판정하지 않는다**.
3. `run/designs/<did>/design.npz` 존재. 순위·`keep_files_top`·`best/` 와 **무관**(순위 밖 안 허용, 사용자 확정 2). 스터디 phase 가 DONE 이 아니어도 그 안의 design.npz 가 있으면 허용.
4. Case: 기본 `base.case_id`, 또는 스터디 ESL 의 출처 Case 중 `case_id`. ACTIVE·같은 프로젝트·rad 존재. 추출(model.npz) 최신 여부는 **요구하지 않음**(좌표는 design.npz·base_mesh 에서).
5. `input_set` problems 없음(누적 씬·include 배치·엔진 rad 없음은 거부).
6. 노드 불변식(§4 I-1·I-2) 통과, 크기 ≤ `ui.max_bundle_bytes`.

## 4. 불변식

- **I-1 노드 집합**: design.npz `node_id` 집합 = base_mesh `node_id` 집합(중복 없음, 크기 같음). 패치 `required` = 이 집합 전체, `coords` 키 = 이 집합 정확히. 다르면 `REDROP_NODESET_MISMATCH`.
- **I-2 기준 일치**: 원본 폐포에서 읽은 대상 노드 좌표 `x_file` 과 base_mesh `x0` 의 최대 성분 차 ≤ `base_coord_tol_mm`(기본 0 = 정확히 같음). 넘으면 `REDROP_BASE_CHANGED`.
- **I-3 바뀌는 줄**: 패치 좌표 = `x_design`(‖x_design − x0‖ > 0 인 노드) / `x_file`(그 밖). 따라서 움직이지 않은 대상 노드 줄, 대상 파트 밖 노드 줄, `/NODE` 밖 모든 카드(요소·파트·접촉·tie·재질 …)·주석·빈 줄은 **바이트 동일**. 바뀐 줄도 ID 필드(앞 10자)와 70자 뒤 나머지는 그대로(patch.py 규칙).
- **I-4 줄바꿈·인코딩**: 줄마다 원래 줄바꿈(`\r\n`/`\n`) 보존, 바이트 단위 처리(디코딩 후 재인코딩 없음 — 바뀐 줄만 ASCII).
- **I-5 기준안**: `d000`(모핑 0) → `changed = []`, zip 의 `input/` 아래 모든 파일이 원본과 바이트 동일, 임시 폴더에는 메타 2개만.
- **I-6 무쓰기**: input_roots·upload_root·Case 원본 폴더·`_doe/<sid>` 에 쓰지 않는다. 쓰기는 `<esl_root>/_redrop/<token>/` 뿐이고 응답 뒤 남지 않는다(정리 ①②③).
- **I-7 폐포 일치**: zip `input/` 의 rel 집합 = `input_set().files` 의 rel 집합(그 밖 파일 0개).

## 5. 구조 — 공용 모듈 / 계획 표 / 독립성

### 5.1 공용 계산 (모드 무관, `esl/verify/`)

| 함수 | 위치 | 시그니처·책임 | 쓰는 쪽 |
|---|---|---|---|
| `patch_design` | `esl/verify/patch.py`(추가) | `patch_design(files, node_id, x, out_dir, *, max_line=None, guard=None) -> dict` — `coords = {node_id[i]: x[i]}`, `patch_node_files(files, coords, out_dir, required=node_id, max_line, guard)` 결과 그대로 반환. **검증낙하·재낙하 공통 패치 입구** | `vd_patch`, `rd_prepare` |
| `read_node_coords` | `esl/verify/patch.py`(추가) | `read_node_coords(files, node_id, *, max_line=None) -> (X (N,3) float64 NaN=없음, found bool (N,))` — `_scan` 과 같은 `/NODE` 해석(`_is_node_header`·`_parse`·`bounded_readline`). 같은 ID 가 다른 좌표로 두 번 → `RAD_PARSE_ERROR` | `rd_prepare` |
| `check_nodeset` | `esl/verify/redrop.py`(신규) | `check_nodeset(base_nid, design_nid) -> None` 또는 `EslError("REDROP_NODESET_MISMATCH")`(detail 수치 포함) | `rd_prepare` |
| `merge_coords` | 〃 | `merge_coords(node_id, x_design, x0, x_file, tol) -> (x_patch, stats)` — I-2 판정(`REDROP_BASE_CHANGED`), I-3 합성, stats `{n_moved, max_disp, max_disp_node_id, base_max_diff}`. `design` 을 base 순서로 맞추는 정렬 포함 | `rd_prepare` |
| `manifest` / `readme_text` | 〃 | 순수 dict/str 생성(§2.1·§2.2), 입력은 인수로만 | `rd_prepare` |

- `esl/verify/redrop.py` 는 **numpy·`esl.errors` 만 import**. `esl.doe`·`esl_platform`·`esl_worker` import 금지, 파일 IO·설정 해석 없음(AGENTS.md 독립 모듈 규칙).
- `esl/verify/patch.py` 는 기존처럼 `esl.errors`·`esl.fsutil`·`esl.rad.parser` 만 import(`esl.doe` 금지 유지).
- **`vd_patch` 회귀**: `coords = {…}` + `patch_node_files(…, required=nid.tolist(), …)` 두 줄을 `patch_design(spec["files"], nid, X, spec["out"], max_line=…)` 한 줄로 바꾼다. 그 밖(morphed_coords·morph.npz·echo·result json)은 그대로. 산출 파일·result json 바이트 동일(V-RD-12). `required` 를 리스트 대신 배열로 넘겨도 `set(int(x) …)` 이라 동일.
- 패치 계산을 재낙하 쪽에서 새로 구현하지 않는다(줄 해석·포맷 `FIX_FMT`·임시 `.vdtmp`·`atomic_replace` 모두 patch.py 한 곳).

### 5.2 모드별 계획 표 (`esl/doe/transfer_plan.py`)

새 열 `redrop` — 재낙하 입력 좌표 치환 방식. 값 `node_id`(원 Case 노드 ID 그대로 → `/NODE` 패치) | `none`(새 메시·새 ID → 불가).

| 계획 행 | `redrop` | 이유 |
|---|---|---|
| `case_once` (same, select+case) | `node_id` | 기준 메시 = 원 Case 파트, ID 유지(`identity: topo`) |
| `bmesh_once` (mesh, select+mesh) | `none` | B 메시 업로드 ID |
| `step_once` (select+step) | `none` | STEP 사다리 메시 |
| `step_per_design` (step) | `none` | 안마다 새 메시 |
| `compare_per_shape` (compare) | `none` | 형상마다 새 메시 |

- `PLAN_COLS` 에 `"redrop"` 추가, 모든 행 채움(빈 칸 = `CONFIG_INVALID` — 기존 `plan_for` 검사). 값 검사 `RD_VALUES = ("node_id", "none")` 를 `BS_VALUES` 처럼 `plan_for` 에서 확인.
- `identity` 열을 재사용하지 않는다: `identity` 는 "work 전달의 같은 메시 판정 키"라 의미가 다르다(D-0.22.0-RD-2).
- `PLAN_VERSION` 은 올리지 않는다(`hash_view` 는 계획 행이 아니라 해석된 lt 설정을 해시 → 이어하기 해시 불변).
- 백엔드는 `core/opt_core` 어댑터(`doe_transfer_plan`)로 `plan_for(s["scenario"], select_base)` 를 부르고 `row["redrop"]` 만 본다. `select_base` = 스터디 `inputs.select_base`(없으면 `"case"`, select 외 시나리오는 None). **시나리오 이름 분기 금지** — 기존 검증낙하의 `scenario not in ("same","select")` 검사는 이번에 바꾸지 않는다(범위 밖, R-RD-5).

### 5.3 단계 함수 (IO 담당, `esl/verify/stages.py` 추가)

`rd_prepare(spec, echo=print) -> dict` — spec 키(고정): `base_npz`, `design_npz`, `files[(rel, abs)]`, `out`(= `<token>/input`), `meta_out`(= `<token>`), `max_line`, `base_coord_tol_mm`, `manifest_extra`(study·design·case·platform_version·created_at). 흐름: npz 2개 로드(`allow_pickle=False`) → `check_nodeset` → `read_node_coords` → `merge_coords` → `patch_design` → `manifest`·`readme_text` 를 `meta_out` 에 원자적 쓰기 → manifest dict 반환. `run_stage`·`STAGES`(워커 단계 목록)에는 넣지 않는다(백엔드 동기 호출 전용).
- 백엔드는 어댑터 `core/opt_core.py` 에 `"verify_stages": "esl.verify.stages"` 를 추가해 부른다(코어 직접 import 대신 기존 어댑터 경로).
- `max_line` = 기존 검증낙하와 같이 core `case.rad_max_line_kb`×1024(없으면 None).

### 5.4 백엔드 서비스 (`backend/esl_platform/api/services/redrop.py`, 신규)

`bundle(ctx, principal, sid, did, case_id) -> {files, prefix, filename, size, cleanup}` + `sweep(ctx)`. `_viewable` → 설정 → `DID_RE` → 계획 열 → 안 폴더/npz → Case(§3-4) → `verify_drop.input_set` → `bundle._check_size` → `esl_subdir(REDROP_DIR, token)` → `rd_prepare` → 파일 목록 `[(abs, "input/<rel>")…] + [(manifest, "redrop_manifest.json"), (readme, "REDROP_README.txt")]`. `EslError` → `DomainError`(§1 표 HTTP). 라우터는 `zip_response` 와 같은 헤더로 `StreamingResponse(_with_cleanup(stream_zip(...), tmp))`.
- `zip_response` 를 고치지 않기 위해 라우터에서 정리 제너레이터로 감싼 뒤 `StreamingResponse` 를 직접 만든다(헤더 3개 동일).
- `study_out`(services/doe.py)에 `redrop_ok`·`redrop_blocked` 두 칸만 추가(계산 = `redrop.flags(ctx, s)`).

## 6. 설정 (`bead_doe.redrop:` — 섹션 없으면 기본값)

| 키 | 기본 | 의미 |
|---|---|---|
| `enabled` | `true` | false → 503 `REDROP_DISABLED`, `redrop_ok` false |
| `tmp_ttl_s` | `3600` | `_redrop/<token>` 잔여 폴더 정리 기준(초, 1..86400) |
| `base_coord_tol_mm` | `0.0` | I-2 허용 차(≥ 0). 0 = 정확히 같아야 함 |

- 같은 이름 3곳: `esl/doe/__init__.py` `DEFAULTS["redrop"]` ↔ `backend/esl_platform/core/config.py` `BeadDoeRedropCfg`(`BeadDoeCfg.redrop`) ↔ 두 예시 yaml 의 `bead_doe.redrop` 블록. 크기 상한은 새 키 없이 `ui.max_bundle_bytes`, 엔진 rad 규칙은 `verify_drop.engine_globs`, 줄 길이는 core `case.rad_max_line_kb` 를 그대로 쓴다.

## 7. UI (frontend)

- `DoeStudy.tsx` 의 `Downloads extra` 자리(검증 낙하 버튼 옆)에 `BundleButton` 1개: `label="재낙하 입력 받기"`, `url = doe.redropUrl(study.id, pick)`, `filename = redrop_<pick>_<id 앞 8자>.zip`, title "선택한 안의 모핑 좌표를 원 낙하 입력(rad·include)에 넣은 zip — 받아서 HPC 에 직접 제출".
- 비활성: `!study.redrop_ok`(툴팁 = `redrop_blocked`) 또는 `pick` 없음. 비교(④) 화면에도 같은 규칙(서버 플래그로만 판정 — 프런트 시나리오 분기 없음).
- 413 은 `BundleButton` 기존 안내, 그 밖 4xx 는 `errorText`(서버 메시지) 그대로. 새 대화상자·Case 선택 UI 없음(`case_id` 쿼리는 API 전용).
- `api/doe.ts`: `redropUrl(id, did, caseId?)` = `${API_PREFIX}/doe/studies/${id}/designs/${encodeURIComponent(did)}/redrop` (+ `?case_id=`).
- mock: `mock/doedata.ts`(`redrop_ok`·`redrop_blocked` 채움), `mock/server.ts`(GET redrop → 작은 zip blob, did `d999` → 409 `REDROP_DESIGN_NOT_READY`).

## 8. 시험 (V-RD-n)

합성 픽스처 `tests/fixtures/redrop/`(신규): starter `m_0000.rad`(include 2개 — 하나는 하위 폴더, `\r\n` 파일 1개·`\n` 파일 1개), 엔진 `m_0001.rad`, 대상 파트 노드는 include A·B 에 나눠 있음, 대상 밖 노드·`/SHELL`·`/PART`·`/INTER`·`/RBODY` 카드 포함, 고정폭·쉼표 자유형식 줄 각 1개.

| id | 내용 | 위치 |
|---|---|---|
| 1 | 바이트 동일: 패치 결과에서 바뀐 노드 줄의 좌표 3칸 외 모든 바이트(대상 밖 노드·다른 카드·주석·줄바꿈)가 원본과 같음, 움직이지 않은 대상 노드 줄도 같음 | `tests/verify/test_redrop.py` |
| 2 | 기준안 d000(x = x0) → `changed=[]`, 모든 파일 sha256 원본과 같음, out 폴더에 입력 파일 0개 | 〃 |
| 3 | 노드 누락: 대상 노드 1개를 include 에서 지운 픽스처 → `VD_NODES_MISSING`, out 폴더 비어 있음(부분 산출물 없음) | 〃 |
| 4 | 노드 집합 불일치(design 에 1개 더/덜, 중복) → `REDROP_NODESET_MISMATCH` | 〃 |
| 5 | 기준 변경: 원본 노드 1개 좌표를 바꿈 → tol 0 이면 `REDROP_BASE_CHANGED`, tol 이 차보다 크면 통과하고 그 노드는 원본 줄 그대로 | 〃 |
| 6 | 같은 ID 다른 좌표 두 파일 → `RAD_PARSE_ERROR` | 〃 |
| 7 | 계획 열: 모든 `PLANS` 행에 `redrop` 이 있고 값 ∈ `RD_VALUES`, `case_once` 만 `node_id`. 열 지우면 `plan_for` → `CONFIG_INVALID` | `tests/doe/test_transfer_plan.py` |
| 8 | API identity 거부: mesh·step·compare 스터디 → 422 `REDROP_UNSUPPORTED`, `redrop_ok=false`·`redrop_blocked` 문구. 서비스 코드에 시나리오 이름 문자열 비교 없음(정적 grep) | `backend/tests/test_doe_redrop_api.py` |
| 9 | 순위 밖 안: keep_files_top=3, `best/` 에 없는 d020 → 200, manifest `design.rank` = 순위 행 값, `best/d020` 미생성 | 〃 |
| 10 | zip 구조: 최상위 `redrop_<did>_<sid8>/`, `input/` rel 집합 = `input_set` rel 집합(I-7), 엔진 rad 포함, h3d·`A001`·`.out` 이 Case 폴더에 있어도 zip 에 없음, manifest 고정 키·`changed`·`nodes.max_disp` 가 numpy 계산과 일치, README 존재 | 〃 |
| 11 | 입력 폴더 무쓰기: 요청 전후 Case 폴더·upload_root·`_doe/<sid>` 트리(이름·mtime·sha256) 동일 | 〃 |
| 12 | `vd_patch` 회귀: 기존 `tests/verify/test_vd_patch.py` 전부 통과 + 같은 spec 로 리팩터 전후 산출 파일·result json 바이트 동일(골든 sha256) | `tests/verify/test_vd_patch.py`(추가 1건) |
| 13 | 임시 폴더 정리: 정상 완료 → `_redrop/` 비어 있음. 스트림 도중 제너레이터 close → 비어 있음. 4xx(노드 누락) → 비어 있음. ttl 지난 잔여 폴더는 다음 요청에서 지워지고, 32-hex 가 아닌 이름·링크는 건드리지 않음 | `backend/tests/test_doe_redrop_api.py` |
| 14 | 거부 코드: design.npz 없음 409 `REDROP_DESIGN_NOT_READY`, 없는 안 404, 잘못된 did 422, 누적 Case 422 `VD_CUMULATIVE_EXCLUDED`(problems[] 포함), 절대경로 include 422 `VD_INCLUDE_LAYOUT`, 엔진 없음 422, 스터디 밖 case_id 422, 보관 Case 409, `enabled=false` 503, 크기 상한 413(임시 폴더 생성 전) | 〃 |
| 15 | 권한: 프로젝트 viewer 200, 프로젝트 밖 사용자 403, 없는 스터디 404 | 〃 |
| 16 | 설정 동기: `DEFAULTS["redrop"]` == `BeadDoeRedropCfg()` == 두 예시 yaml 블록 | `backend/tests/test_doe_config.py`(추가) |
| 17 | 프런트: 버튼 비활성(redrop_ok false → 툴팁, pick 없음), 활성 시 URL·파일명, 409 메시지 표시, 413 안내, `check:api` 통과 | `frontend/src/__tests__/doe_redrop.test.tsx` |

## 9. 리스크

- R-RD-1 대용량 입력(수백 MB include): 요청 안에서 두 번 읽기(좌표 읽기 + 패치 스캔) + 한 번 쓰기 → 수십 초. 프록시 타임아웃이 짧으면 실패할 수 있다. 크기 상한(`ui.max_bundle_bytes`) 안에서는 결과 받기와 같은 수준. 문제가 되면 이후 job 방식으로 옮김(이번 범위 밖).
- R-RD-2 동시 요청이 많으면 `_redrop` 디스크 사용이 바뀐 파일 크기 × 요청 수로 늘어남. 정리 ①②로 상한은 `tmp_ttl_s` 동안만.
- R-RD-3 스터디 뒤 Case 입력이 바뀐 경우 I-2 가 막는다(`base_coord_tol_mm` 0). 단위·좌표계가 같다고 가정(case_once 는 `placement: global`).
- R-RD-4 비 ASCII 노드 줄은 `VD_PATCH_ENCODING` 으로 실패(검증낙하와 같음).
- R-RD-5 검증낙하의 `scenario not in ("same","select")` 이름 검사는 그대로 남는다(이번에 고치지 않음 — 별도 정리 후보).
- R-RD-6 design.npz 좌표는 평가 메시 좌표(paicad 모핑 결과를 읽은 값). `best/<did>/include` 사본과 마지막 자리까지 같다는 보장은 없다(검증낙하와 재낙하 zip 이 상위 안에서 1e-13 상대 수준으로 다를 수 있음) — 자릿수는 `FIX_FMT %20.13E` 로 같다.

## 10. 제약

- **입력·SPDM 무쓰기**: 쓰는 경로는 `<esl_root>/_redrop/<token>/` 하나(I-6, V-RD-11·13). Case 원본은 `open(…, "rb")` 읽기만.
- **하드코딩 금지**: §6 키만. 폴더 이름 상수 `REDROP_DIR`, manifest 파일명·schema 문자열은 코드 상수.
- 계약 외 파일 수정 금지(§13 소유권 밖은 고치지 않는다). `verify_drop.py`·`bundle.py`·`results.py:zip_response` 는 import 만.

## 11. 버전 제안

- **v0.22.0**: 새 API·새 화면 버튼·계획 표 새 열·새 설정 절(사용자 기능 추가) — 이전 관례(v0.19.0 삭제, v0.21.0 형상 규칙)와 같은 마이너 올림. 패치 버전(v0.21.1)은 기존 기능 수정 관례라 맞지 않음.
- **migration 불필요**: DB 테이블·열 변경 없음(manifest·임시 폴더만, 이력 행 없음). 직전 HEAD revision 그대로.
- 결정 후보(decisions.md):

| ID | 결정 |
|---|---|
| D-0.22.0-RD-1 | 동기 스트리밍 + `<esl_root>/_redrop/<token>` 임시 폴더(완료·오류·ttl 정리). job·DB 행 없음 |
| D-0.22.0-RD-2 | 허용 판정 = 계획 표 새 열 `redrop`(`node_id`\|`none`), `identity` 열 재사용 안 함 |
| D-0.22.0-RD-3 | 좌표 출처 = `design.npz`(순위·`best/` 무관), 노드 집합 = base_mesh 와 정확히 일치, 원본 좌표 = base `x0`(tol 0) |
| D-0.22.0-RD-4 | 패치는 `esl/verify/patch.py:patch_design` 한 곳(검증낙하 공용), `vd_patch` 산출 바이트 동일 |
| D-0.22.0-RD-5 | zip = `input/`(폐포 전체 + 엔진 rad, 결과 파일 없음) + manifest + README, 권한 = 스터디 읽기 |

## 12. 결정 질문 (기본안 적용 상태로 구현 가능)

1. **씬(Case) 범위** — 스터디 ESL 이 여러 Case(낙하 씬)에서 왔을 때 zip 에 무엇을 넣나? **기본안: 기준 Case(`base.case_id`) 1개**, 다른 씬은 API `case_id` 쿼리로만(UI 없음). 대안: 씬마다 `input_<case 이름>/` 을 한 zip 에 모두.
2. **엔진 rad 없음** — `VD_ENGINE_MISSING` 을 거부할까? **기본안: 거부**(검증낙하와 같은 `input_set` 규칙, 제출 불가 묶음 방지). 대안: 경고만 manifest `warnings[]` 에 남기고 starter + include 만 넣음.

## 13. 파일 소유권 (겹침 0)

경로는 저장소 루트 기준. `B = backend/esl_platform`, `F = frontend/src`.

| 갈래 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Backend** | `esl/verify/patch.py`(`patch_design`·`read_node_coords` 추가), `esl/verify/redrop.py`(신규), `esl/verify/stages.py`(`vd_patch` 한 줄 교체 + `rd_prepare` 추가), `esl/doe/transfer_plan.py`(`redrop` 열·`RD_VALUES`), `esl/doe/__init__.py`(`DEFAULTS["redrop"]`), `B/core/config.py`(`BeadDoeRedropCfg`·`BeadDoeCfg.redrop`), `B/core/paths.py`(`REDROP_DIR`), `B/core/opt_core.py`(`verify_stages` 어댑터 항목), `B/api/services/redrop.py`(신규), `B/api/services/doe.py`(`study_out` 2칸만), `B/api/routers/doe.py`(GET redrop), `B/api/schemas.py`(`DoeStudyOut.redrop_ok`·`redrop_blocked`), `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`(`bead_doe.redrop` 블록), `docs/contracts/openapi_p1b.json`(재생성), `tests/fixtures/redrop/*`(신규), `tests/verify/test_redrop.py`(신규), `tests/verify/test_vd_patch.py`(회귀 1건 추가), `tests/doe/test_transfer_plan.py`(열 검사 추가), `backend/tests/test_doe_redrop_api.py`(신규), `backend/tests/test_doe_config.py`(동기 검사 추가) | V-RD-1~16 |
| **Impl-Frontend** | `F/api/doe.ts`(`redropUrl`), `F/api/types.ts`(`DoeStudyOut` 2칸), `F/pages/doe/DoeStudy.tsx`(버튼 1개), `F/mock/doedata.ts`·`F/mock/server.ts`, `F/__tests__/doe_redrop.test.tsx`(신규) | V-RD-17 |
| **통합(메인)** | `VERSION`(0.22.0), `CHANGELOG.md`, `docs/decisions.md`(D-0.22.0-RD-1~5), 이 계약 문서 | – |

- **고정 접점 2개**: ① `DoeStudyOut.redrop_ok`·`redrop_blocked`(schemas.py ↔ types.ts, `npm run check:api`), ② 경로 `GET /doe/studies/{sid}/designs/{did}/redrop`(+`case_id`)와 §1 오류 코드.
- `F/components/BundleButton.tsx`·`DoeRanking.tsx` 는 고치지 않는다(기존 `label`·`selected` 사용). `B/api/services/verify_drop.py`·`bundle.py`·`B/api/routers/results.py` 는 import 만.
- 순서: Backend(transfer_plan 열·patch_design 먼저, vd_patch 회귀 확인) ∥ Frontend(mock) → openapi 재생성 → check:api → 통합.
