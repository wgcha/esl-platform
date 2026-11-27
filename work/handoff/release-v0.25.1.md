# release/v0.25.1 C1 handoff (코어 — 낙하 씬별 3D 묶음 + C 기여도·차이·umax 핀)

계약 docs/contracts/esl_view3d_scene_legend.md(수정 금지), 결정 D-0.25.1-VL-1~12. C1 소유 = `esl/mech/cfield.py`(새)·`esl/view3d.py`·
`esl/doe/stages.py`·`esl/doe/__init__.py`(DEFAULTS)·`esl/mech/grid_map.py`(rcfs 보관 1곳 — VL-C1-2)·`tests/doe/test_view3d_scene.py`·
`tests/doe/golden_v0251_c1/`. 시험 환경 /tmp/rdenv_v0251c1.sh(= /tmp/rdenv_main.sh, REPO_ROOT=wt_v0251, PYTHONPATH += packages/beadgraph/src).
발견·최소 해석 = work/findings.md VL-C1-1~.

## B1(백엔드)·F1b(스터디 화면)가 쓸 인터페이스 — 파일 형식(계약 §2.2·§2.3 그대로, 코어 함수 호출 없음)

### 사이드카 `post/scene_view.json`
```
{"schema": "esl/doe_scene_view/1", "builder_version": 1, "source": "bd_post" | "regen", "created_at", "seconds",
 "entries": [{"entry_id", "kk"}],                                   # kk = 스냅샷 doe.entries 순번(0..)
 "packs": {"<src>": {"tag", "c_kind": "fu" | "mixed",
                     "designs": {"<did>": {"dir": "<tag>/<did>", "scenes": ["<entry_id>", …]}},   # 디스크 pack.json 이 원본
                     "skipped": [{"did": str | null, "entry_id": str | null, "code", "detail"}]}},
 "budget": {"max_mb", "est_mb", "n_scenes", "n_written"}, "warnings": ["…"]}
```
- `<src>` = 순위 보기 키 `full`·`jig`·`jig_disp`·`jig_spring`·`bforce`·`fint`(코어 `stages.SCENE_SOURCES` 행 = `RANK_SOURCES` 키).
  tag = `sv`(full)·`jig`·`jd`·`js`·`bf`·`fi`(= 기존 v3d_tag).
- skipped code ∈ `SCENE_BUDGET`·`SCENE_FAILED`·`SCENE_NO_SOURCE`·`SCENE_DIFF_NO_FRAME`(`stages.SCENE_SKIP_CODES`). `detail` = 자유 문자열
  (SCENE_FAILED = 오류 코드 또는 "baseline"). 응답 `skipped.text` 는 B1 이 resources/doe_messages.json 에서 code 로 만든다.
- `warnings` = 진단 문자열(`SCENE_FAILED: <src> <did> <code>`, `SCENE_C_MISMATCH: …`, `SCENE_PIN_MISMATCH: …` — 계약 밖 진단, VL-C1-8).
- 사이드카 없음(옛 스터디·`view3d.scene.enabled: false`) = `scene_view: null`.

### 묶음 `post/view3d_scene/<tag>/<did>/`
- `pack.json` = `{"schema": "esl/view3d_scene/1", "builder_version": 1, "key", "src", "did", "n_nodes", "n_elems", "n_tris", "bbox",
  "plate_normal", "geometry": {"name": "part.glb", "bytes"}, "lod": {name, bytes, n_vertices} | null,
  "scenes": [{"entry_id", "kk", "manifest": "e<kk>.json", "values": "e<kk>.bin"}], "created_at"}` — **마지막에 씀(없으면 미완성 묶음)**.
  API 파일 이름 화이트리스트 = pack.json 의 `geometry.name`·`lod.name`·`scenes[].values`(+ manifest).
- `part.glb`(·`part_lod.glb`) = `esl.view3d.write_glb` 같은 바이트 규칙(같은 메시면 `post/view3d/<did>/part.glb` 와 바이트 동일 — 시험 V-0251-9).
- `e<kk>.json` = 기존 view3d manifest 키 전부(schema `esl/view3d/1`, `geometry`·`lod` = 묶음 것 이름, `values.name` = `e<kk>.bin`,
  `esl_run_id` = entry_id, `key` = `doe/scene/<tag>/<did>/e<kk>`) + 새 키:
  - `c`: `{"kind": "fu"|"mixed", "sum": Σc(float64 — 양자화 전), "offset": C_pe − 합(fu 0.0, mixed E_0 − C_mix,0), "value": per_esl 저장 C,
    "parts": {"W_F", "W_v", "W_g"}, "unit": "N·mm"}` — `sum + offset == value`(상대 1e-9).
  - `dc`: 베이스라인 묶음 = `null`. 안 = `{"sum": Σdc, "base_sum": 기준 c.sum, "map": "identity"|"grid", "cell_mm"?, "moved_rel"?}`
    (`cell_mm`·`moved_rel` = grid 일 때만). 공통 좌표 없음 = `null` + skipped SCENE_DIFF_NO_FRAME. `sum == value_안 − value_기준`(1e-9).
  - `pins`: `{"umax": {"node_id", "vertex", "value", "kind": "ev"|"all"|"region"|"mask"} | null}` — `value` == 표의 umax_ev(있으면)
    또는 그 출처 umax(같은 값 ==).
  - `ranges.c` = `{min, max, p01, p99}`(p01·p99 = 값 ≠ 0 노드 — VL-C1-3, 없으면 null), `ranges.dc` = `{abs_max, abs_p99}` | null.
  - `values.arrays` 끝에 `{"key": "c", "dtype": "int16", "comps": 1, "offset", "scale"}`(항상)·`{"key": "dc", …}`(안 묶음만). 앞 4배열
    (pa·fn·fmag·u)은 기존 values.bin 과 같은 바이트(같은 F·u 이면). 복원 = q·scale(기존 규칙).
- `e<kk>.bin` 노드당 = 베이스라인 14 B·안 16 B(+ 4바이트 정렬 패딩).

### 작업(B1) — 씬 3D 보충 `POST …/view3d/scenes`
- 코어 dispatch: 스펙 `doe.post_mode == "scene"` → `stages._post_scene`(쓰는 것 = `post/view3d_scene/**`·`post/scene_view.json` 만, 멱등 —
  새로 만든 씬이 없으면 아무것도 쓰지 않고 `files: []`). 반환 `{"files": ["post/scene_view.json"] | [], "warnings", "result": None}`.
  post/result.json 없음 = `RESULT_NOT_READY`.
- **워커 변경 없이** 쓰려면 작업 params `kind: "VIEW3D"`(worker `doe_jobs.POST_ONLY_KINDS` — 등록 = DB 무변경 `register_doe_view3d`) +
  `doe.post_mode: "scene"`, resume BD_POST(기존 `SOURCE_ADD` jig 행과 같은 틀).
- 기존 `post_mode: "view3d"`(3D 다시 만들기)도 끝에 같은 실행기를 불러 빠진 씬을 채운다(반환 files 에 `post/scene_view.json` 추가될 수 있음).
- 설정: `bead_doe.view3d.scene = {enabled: true, max_mb: 1024, diff_cell_h_mult: 2.0}` — 코어 DEFAULTS·검증
  `esl.doe.check_view3d_scene`(settings() 가 부름 — enabled bool, max_mb 0..65536, diff_cell_h_mult 0.5..8, 밖 = CONFIG_INVALID
  detail {key, value}). pydantic `BeadDoeView3dSceneCfg`·yaml 2개 = B1(같은 이름·값 — 코어 시험 `test_v0251_15_settings_mirrors` 가 B1
  통합 뒤 자동 확인, 지금은 skip). `_cfg_hash` 밖(input_sha256 불변 — 시험).
- 결과 받기 zip 에서 `post/view3d_scene/**`·`post/scene_view.json` 제외(B1).

### F1b — 자료 고르기
- 씬 묶음 있음 = `scene_view.packs[<탭 출처 키>].designs[<did>]` 에 entry_id 가 있으면 그 manifest(새 API). 기준 카드 = `d000` 같은 씬.
- 색 모드 `c`·`dc` 가능 여부 = manifest `values.arrays` 에 c/dc 키 존재(dc 는 안 카드만 — 기준 묶음엔 없음), 범위 = `ranges.c`·`ranges.dc`.
- 씬 요약 값 = manifest `c.value`(C)·`pins.umax.value`(umax) — 표 값과 같음.

## 코어 구조(통합·독립 검증용)
- 순수 계산 `esl/mech/cfield.py`: `nodal_c(F, u3, bc, rc, fs)`·`umax_pin(u3, mask)`·`conserve_map(c_src, X_src, X_dst, GF)`·`diff` (import =
  numpy·grid_map(grid_frame·vox_key)·errors — 정적 시험 V-0251-14).
- 파일 `esl/view3d.py`: `build_scene_pack(…, scenes=반복자, existing=옛 pack, write_pack)`·`write_pack_json`·`patch_scene_dc`·
  `pack_scene_values`·`scene_ranges`·`scene_files(kk)`. `build_view` 는 같은 내부 함수(`_part`·`_support_rows`·`_load_fields`)로 나눔 — 바이트
  불변(tests/test_view3d_golden.py).
- 실행기 `esl/doe/stages.py`: 계획 표 `SCENE_SOURCES`(열 key·tag·provider·ready·c_kind·c_key·pin·values) + `_scn_begin`(계획·한도) →
  기존 3D 함수가 provider 를 넘김 `_scn_feed`(`_view3d`·`_jig_v3d_build`·`_ns_view3d`·`_jg_view3d_src` — 같은 분해, 후진대입만) →
  `_scn_finish`(넘겨받지 못한 (출처, 안) provider 직접·늦은 차이 patch·사이드카). BD_POST·④ BD_POST·`post_mode view3d`·`post_mode scene`
  모두 이 한 벌. provider 본체 `_scn_full_p`·`_scn_jig_p`·`_scn_jig_grid_p`·`_scn_nodal_p`(+ 직접 호출 `_scn_full`·`_scn_jig`·`_scn_nodal`).
- `_view3d` 의 `ev.evaluate` → `_scn_full_p`(같은 지지 점검·쉘 모델·분해 — 같은 u), `_jig_resp_rows(…, keep=)`(연 분해를 남김, 옛 npz =
  `jig.factor`+`jig.respond` = design_response), `_ns_view3d` 는 씬이 원하면 `_ns_design(keep_u = 전 씬)`. `_view3d_input` = 입력부.
- `esl/mech/grid_map.run_shape` keep_u 일 때 `rcfs{src:{eid:{bc, rc, fs}}}` 보관(VL-C1-2).
- 옛 골든 시험(golden_v0247·0248·0249 tree_sha)은 새 씬 파일을 비교에서 뺌(`SCENE_NEW` — 새 파일 확인은 V-0251-10).

## 진행 상태
- [x] 골든 기록(main 97a0e358 코드) tests/doe/golden_v0251_c1 — 세계 6(same_lt·same_all6·sel_case_jig·step_old·cmp_lt·cmp_grid)
- [x] cfield.py · view3d.build_scene_pack · stages 실행기(begin/feed/finish)·provider·사이드카·post_mode scene·_post_view3d 보충·_cmp_post
- [x] DEFAULTS view3d.scene + check_view3d_scene
- [x] 시험 V-0251-1~15 + 분해 재사용(tests/doe/test_view3d_scene.py — 15 의 거울 확인은 B1 뒤 skip 해제)
- [x] 실측(H5 15,477 노드 — H6 은 superlu 메모리 초과): 묶음 33.4 MB(96 씬), BD_POST +20.3 s(사이드카 seconds 21.2), 분해 수 불변(12)
      → 10만 노드 ≈ 196 MB(계약 195 MB), 시간 ≈ 2.5~3 분 추정(VL-C1-11)
- [x] tests/ 전체 1회 + pytest packages/beadgraph — 결과는 아래 "결과"
- [x] 계약 개정 1(origin/wip/v0.25.1-contract2 e9745958) merge — 4ab332da

## 결과
- tests/ 전체(1530df46): 1925 passed · 193 skipped · 4 failed = 허용 3(test_large_model_cad_share·test_v0160_bytes_skip_policy[h8]·
  [h5open]) + `test_transfer_plan::test_stages_single_load_site`(정적 시험이 `_view3d` 에서 하중 함수 호출을 찾음 → 입력부 `_view3d_input`
  으로 옮겨 보정, 07d33359 — 다시 돌려 통과). 보정 뒤 test_transfer_plan + test_view3d_scene 41 passed·1 skip(거울 — B1 뒤), tests/deploy·
  메시지·정적 203 passed. `pytest packages/beadgraph`(저장소 루트) 117 passed·2 skipped.
- 물리(V-0251-1~7 — 합성·스터디 세계 전부): Σc vs C 상대 ≤ 1e-9(fu·mixed·격자), Σdc vs ΔC 1e-9(항등·격자), conserve_map 합 1e-12, 핀 값 ==
  표 값(출처 6행·kind ev/all/region/mask). 분해 수 씬 끔 = 켬.
- 실측: VL-C1-11(H5 — 묶음 33.4 MB/96 씬, BD_POST +20.3 s, 분해 12 = 12, 10만 노드 ≈ 196 MB·2.5~3 분 추정).

## 계약 개정 1 반영(C1 범위만 — 색 작업 없음)
- §15.1 #2 사이드카 `entries` = 스냅샷 `doe.entries` 전부·같은 순서(이미 그렇게 씀 — 시험 단언 추가 V-0251-11·12).
- §15.1 #3 `skipped.detail` = 짧은 사유만: `"<c_key> 없음"`·`"view3d.scene.max_mb <값>"`·`"baseline"`·오류 코드(EslError code 또는 예외
  클래스 이름)·`"공통 좌표 없음"` — 경로·예외 원문 없음(시험 단언). 진단 원문은 사이드카 `warnings` 에만(코드·출처·안·엔트리·수치).
- §15.1 #5 코어 dispatch: 스펙 `doe.post_mode` 값으로 `"view3d"`(3D 다시 만들기 + 빠진 씬 보충)·`"scene"`(씬 보충만) 구분 — 작업 kind 와
  무관(VIEW3D 그대로).
- V-0251-10 개정: 그림 3종(report.html·*.png·select grid_manifest.json color)은 비교에서 뺌(`golden_vl.is_picture`) — C2 색 변경 뒤에도
  통과. `stages.py` 의 select 썸네일 `color` 줄(color_meta 합치기)은 손대지 않음(통합 때 메인).
- B1(2475896d) 설정 거울 `BeadDoeView3dSceneCfg{enabled bool, max_mb float 1024 [0, 65536], diff_cell_h_mult 2.0 [0.5, 8]}`·yaml 2개와
  코어 DEFAULTS 이름·값 같음(max_mb 1024 == 1024.0) — 통합 뒤 `test_v0251_15_settings_mirrors` 가 skip 대신 확인.
