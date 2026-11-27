# release/v0.25.2 이어받기 · 접점 (C1 코어 — 계약 docs/contracts/esl_tstar_manual_jig_force.md 개정 1)

C1 소유(계약 §11): `esl/**`(pipeline·cli·config·mech/tstar·io/frame_fill★·io/messages·report/case_report·mech/grid_map·
doe/stages·doe/rank·doe/report_doe·doe/__init__·mesh/double_sheet★·view3d) · `resources/tcl/esl_h3d_extract.tcl` ·
`resources/doe_messages.json`(이번만 C1) · `config/esl.example.yaml` · `tests/**`. B1·F1 은 아래 접점만 읽는다.

## 1. 접점 (C1 → B1·F1 — 시그니처 고정, 첫 커밋 = 껍데기)

### 1.1 `esl/io/frame_fill.py` (워커·백엔드 공용, 독립 모듈)

```python
EXTRACT = "01_extract"; RECORD = "frame_fill.json"; RECORD_SCHEMA = "esl/frame_fill/1"
STATUSES = ("ok", "failed", "blocked"); FILL_MODE = "fr_only"; FILL_KEY = "frames_fill"
DECIDE = ({row, when, action: have|block|fill, code, text}, ...)   # 계약 §2.4 표 그대로(행 1~6, 문구 원본 = 이 표)

@dataclass(frozen=True)
class Facts:  have: bool; csv_input=False; dump_mode=False; h3d_readable=True; hw_available=True; h3d_name=""
decide(facts: Facts) -> {"row": int, "action": "have"|"block"|"fill", "code": str|None, "text": str|None}
have_frame(extract_dir, frame) -> bool              # disp.npz ∧ strain_frames.npz 에 있음 (행 1)
frames_have(extract_dir) -> list[int]               # API GET /tstar frames_have
extract_facts(extract_dir, frame) -> {"have", "dump_mode"}   # 01_extract 로 알 수 있는 2개(나머지는 호출부)
fill_frames(frame) -> ([f], [f-1] | [])
request_keys(meta: frames.json dict, frame) -> {"fr_only": "1", "fr_frames": "<f>", "strain_sources": "<추출 source>"}
merge(extract_dir, fill_out, frame, *, job_id=None) -> {"frame", "time", "added": bool}
    # 오류 EslError: FRAME_FILL_OUTPUT · FRAME_FILL_MISMATCH(아무것도 안 씀) · FRAME_FILL_MERGE
read_record(extract_dir) -> dict|None; attempts(extract_dir) -> list
record(extract_dir, {frame, job_id, status ok|failed|blocked, cause, detail, seconds, at?})
last_attempt(extract_dir, frame, job_id=None) -> dict|None
fill_entry(extract_dir, frame) -> dict|None         # frames.json frames_fill 항목(채운 프레임인지)
```

- 워커 흐름(B1): ESL 단계 전(경계력 보충 훅 바로 앞, 같은 hw 세마포어) — `decide(Facts(...))` → fill 이면 request.txt 에
  추출 때 키 + `request_keys(meta, f)` + (bf_on 이면 추출 때 bf 키) → hw → `merge(<Case>/01_extract, fill_out, f, job_id=job)` →
  `record(...)`. 실패 = ESL 단계 실패 `TSTAR_FRAME_FILL_FAILED`(detail = 기록 detail). 이미 있음(행 1) = hw 0.
- 경계력: fr_only 실행이 `bf_on 1` 이면 같은 실행에서 bf_<kind>.csv·done.json `bforce` 를 쓴다 → 워커가 같은 fill_out 으로
  `esl.io.bforce_ondemand.merge(case_dir, fill_out, [f], tag=job, names=...)` 를 부르면 경계력 보충이 "있음"(C1 이 bforce_ondemand 가
  done.json mode `fr_only` 도 받게 함 — TM-C1-1).

### 1.2 TCL `fr_only` (resources/tcl/esl_h3d_extract.tcl)

- 요청 키: `fr_only 0|1`(기본 0 = 지금 출력 그대로) · `fr_frames "<f>"`(정수 ≥ 0, 공백 구분, 중복 금지). `bf_only 1` 과 같이 = INPUT_INVALID.
  변형률 출처 = 요청이 고정(`strain_sources <추출 source 하나>` — 또는 옛 방식 `strain_type`(Max_Strain 고정)). 덤프 source = INPUT_INVALID.
- 출력: `disp.csv`(frame_index,node_id,ux,uy,uz — f 만) · `strain_frames.csv`(frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp — f, f−1) ·
  `bf_<kind>.csv`(bf_on 1 일 때, f) · `done.json`. frames/model/elems/final/history.csv 안 씀.
- done.json `{"ok":true,"mode":"fr_only","n_frames","n_nodes","n_elems","frames":[f],"prev_frames":[f−1],
  "frame_times":{"<f>": t, "<f−1>": t},"strain_source","bforce"?,"passes":{"FR":{...}},...}`. 프레임 ≥ n_frames = H3D_MISSING_RESULT.
  실패 json 에 `"mode":"fr_only"`.

### 1.3 `esl.pipeline.frame_point(out_dir, cfg, metric, frame_index) -> dict`

`{frame_index, time, elem_id, value, auto{frame_index, time, value}, ratio(value/자동 값 | None), rel("before"|"at"|"after"),
in_D, have}` — 자동 = `02_tstar/tstar.json metrics[metric].tstar`. 오류 FRAME_NOT_FOUND(history.npz 에 없음)·PREREQUISITE_MISSING.
순수 값 함수 `esl.mech.tstar.point_at(series (F,H), frame_pos, exclude_mask) -> {elem_pos, value}`.

- 코어 `--frame N`(stage tstar·esl): `disp.npz` 에 있으면 허용. 후보 ∧ D = 지금 레코드(바이트 불변). 그 밖 = frame_point 값 +
  `"source":"user","manual":{auto_frame, auto_time, auto_value, ratio, rel, in_D, have}`. 없으면 FRAME_NOT_CANDIDATE
  ("변위가 추출되지 않은 프레임 — 채움 필요").
- `04_esl/esl_summary.json` `tstar_manual{auto_frame, auto_time, auto_value, ratio, rel, in_D, filled, notes:[{code, level, text}]}`
  (직접 고른 t* 일 때만). 문구 코드 TSTAR_MANUAL(정보)·TSTAR_MANUAL_LOW(경고)·TSTAR_MANUAL_AFTER(정보)·TSTAR_MANUAL_NO_RISING(정보)
  = resources/doe_messages.json(읽기 `esl.io.messages.text`).

### 1.4 설정 이름·기본값 (4곳 같은 이름 — pydantic·yaml 은 B1)

| 키 | 기본 | 범위 | 해시 |
|---|---|---|---|
| 코어 `tstar.manual_ratio_warn` (esl/config.py 선택 키 — cfg 에 주입 안 함) | 0.5 | [0, 1] | 밖 |
| `altair.frame_fill_timeout_s` (B1) | 1800 | ≥ 60 | – |
| `altair.frame_fill_wait_s` (B1) | 600 | ≥ 0 | – |
| `bead_doe.rank.jig_grid.tie_force.enabled` (pydantic `BeadDoeRankJigGridForceCfg`) | true | bool | 안(스냅샷) |
| `bead_doe.rank.jig_grid.tie_force.max_dist_mm` | null | null 또는 > 0 | 안 |
| `bead_doe.rank.jig_grid.tie_force.normal_deg` | 90.0 | (0, 90] | 안 |
| `bead_doe.rank.jig_grid.tie_force_far_warn_mm` | 10.0 | > 0 | 밖(HASH_EXCLUDE) |
| `bead_doe.view3d.jig_force_marks_max` | 512 | ≥ 1 정수 | 밖 |
| `bead_doe.compare.double_sheet.{enabled, gap_min_t, gap_max_t, normal_deg, frac_warn, sample_max}` | true, 0.3, 3.0, 15.0, 0.5, 2000 | gap_min_t > 0, gap_max_t > gap_min_t, normal_deg (0, 90), frac_warn (0, 1], sample_max ≥ 1 | 밖 |

- 옛 스냅샷(rank.jig_grid 에 `tie_force` 키 없음) = 끔(`grid_map.LEGACY_ABSENT`). 백엔드 `rank_snapshot` 은 블록 통째 복사(변경 없음).

### 1.5 스터디 결과 키 (§6.3 — B1 통과·F1 표시)

- `run/designs/<did>/jig_grid.json map.tie`(스냅샷에 tie_force 있을 때만): `n_force`, `n_far`,
  `force{dist_min_mm, dist_med_mm, dist_max_mm, shift_max_mm, far_mm, limit_mm(null)}`, `ref`(bool), `marks[{q, via:"force"|"miss",
  x:[3](Case 체결부 중심 — 형상 전역 좌표), dist, n, far}]`, `marks_truncated?`(true 일 때만).
- `result.json jig.grid`: `n_forced_shapes`, `n_ref_shapes`(같은 조건). 순위 행·rank_views 행: `jig_ref: true`(참일 때만).
- 결과·보기 최상위: `n_ref`(> 0 일 때만), `counts[{key, label, n}]`(= `esl.doe.rank.count_items` — 새 결과만).
  라벨 거울(F1 `COUNT_LABELS`, API counts 없을 때만): ok 성공 · mesh 메시 · size 크기/정렬 · solve 해석 · morph 모핑 ·
  collision 스킵(충돌) · fixed 스킵(고정) · geom 스킵(형상) · jig/jd/js 지그 매핑 제외 · bf 경계력 없음 · fi 내력 없음 ·
  sm 강성 지표 없음 · ref 참고용.
- `prep/compare.json` 형상 행: `double_sheet{frac, gap_mm}`(경고 날 때만). 경고 코드 `SHAPE_DOUBLE_SHEET`.
- 3D manifest(지그 응답 3D): `supports[].via`("force" — 강제 노드만), `tie_marks`(= map.tie.marks).
- 경고 코드(doe_messages.json): JIG_GRID_TIE_FORCED · JIG_GRID_TIE_FAR · JIG_GRID_TIE_UNPLACED · JIG_GRID_TIE_HINT · SHAPE_DOUBLE_SHEET.
  결과 warnings(grid) 행 = {code, message, + 필드}(기존 _jg_warn_rows 규칙). 스터디 요약은 최악 형상 1건씩 + HINT(참고용 형상 ≥ 1).
- 구현 사실(접점 보충): marks 항목에 `to`(force 만 — 붙인 노드 면적 가중 중심, 형상 전역) 추가 — 3D 선 = x → to.
  `counts`·`n_ref` = 격자 지그 ∧ 스냅샷 rank.jig_grid 에 tie_force 있을 때만(TM-C1-2 — ①②③ base 모드는 jig_grid 블록을 무시하는
  v0.24.8 불변 때문). 그 밖 결과는 화면이 n_failed + COUNT_LABELS 거울로 같은 표시를 계산. 보고서 개수 줄은 모든 결과에 count_items.
  RANK_SOURCES 새 열 `label`(지그 고정·지그 변위·지그 스프링·전 노드·경계력·내력 — 보고서 "다른 하중 출처 순위: {label}").

## 2. 진행 (C1)

- [x] 접점 껍데기(이 커밋)
- [x] 골든(release/v0.25.1 393789a8 코드 — git archive 로 /tmp/g0252src 에 풀어 기록 → tests/doe/golden_v0252_c1/golden.json,
  비교 = tests/doe/test_v0252_golden.py: 파이프라인 자동·후보 2 + 스터디 세계 6(옛 스냅샷 — tie_force 없음))
- [x] A(4737a446): frame_fill.merge · TCL fr_only · _select_frame/stage_esl · 경고·보고서 · 시험 1~9
  (tests/pipeline/test_tstar_manual.py · tests/io/test_tcl_fr_only.py)
- [x] B: CAPTURE_STAGES·force · LEGACY_ABSENT · 경고·map.tie · 3D via·tie_marks · 시험 10~18(tests/mech/test_grid_force.py)
- [x] C: count_items 보고서 · 다른 출처 순위 · double_sheet · 시험 19~23 · #96 재현(tests/doe/test_v0252_c.py · synth_tm.py)
- [ ] tests/ 전체 · packages/beadgraph

## 3. 발견 (TM-C1-n — work/findings.md 에도)

- TM-C1-1 경계력 보충 병합(`esl/io/bforce_ondemand.py` — 계약 §11 소유표에 없음, 코어라 C1)이 done.json mode `bf_only` 만 받음 →
  fr_only 실행의 bf_<kind>.csv 를 "같은 실행에서 함께 읽어 있음" 으로 만들려면 `fr_only` 도 받아야 함. 최소 해석: FILL_MODE 허용 목록에 추가.
