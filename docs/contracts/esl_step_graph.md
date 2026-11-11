# 계약: ③ 다른 모델(STEP만)을 공통 비드 그래프 메시 경로로 — STEP → 쉘 메시(④ 사다리) → beadgraph 분류 → select 흐름 (STEP_GRAPH, v0.18.0)

- 상태: **초안 → 구현 기준** (2026-11-11). D1·D2 = 사용자 확정(아래, 변경 금지). D3 = **잠정**(권장 기본값 — 사용자 확인은 O-SG-1). 그 밖 결정은 코드·실측 조사로 구체화. 사용자 결정이 더 필요한 항목 3개는 §10.1(권장안을 기본값으로 적음 — 답이 다르면 그 값만 바꿈, 구조 불변).
- 버전: **v0.18.0** (기준 main 6278842 = v0.17.1). 구현은 **v0.17.2 핫픽스(release/v0.17.2) 위로 rebase**(§11). migration **불필요**(§5.4).
- 관계: `esl_beadgraph.md`(BEADGRAPH, v0.17.0 — 이하 "BG")·`esl_bead_auto.md`(AD, v0.16.2)·`esl_select_relax.md`(SR)·`esl_compare_mesh_options.md`(C2, v0.16.3 사다리)·`esl_bead_doe.md`(BD, ③ 원 계약)의 **변경 계약**. SR-D-44·BG-D-5(모핑 코어는 메시 출처와 무관)를 ③ 에 적용하고 BG-D-45(③ 보류)를 해제한다. 이 문서에 없는 규칙은 BG → AD → SR → BD 순서로 따르고, 충돌 시 이 문서가 우선. **기존 ③(`scenario: step`, paicad) 스터디는 이 문서의 영향을 받지 않는다**(§5.3).
- 근거 자료: 이슈 #63 현장 진단(2026-11-11, 스터디 da9dc714 — 아래 G1·G2), BG H6 픽스처 삼각형 분할 실측(§0.1, 이 계약 작성 중 측정), BG §7·V-BG-13 성능.
- ID 규칙: 결정 `SG-D-n`, 시험 `V-SG-n`, 리스크 `R-SG-n`, 열린 항목 `O-SG-n`.

### 사용자 확정 (2026-11-11, 변경 금지)
1. **D1 ③ 은 공통 분류기를 쓴다**: STEP → 쉘 메시(④ 메시 사다리 cad/freeform/tria 재사용, **같은 설정**) → beadgraph 분류 → ①② 와 같은 select 화면·흐름(세그먼트 트리, 자동 seed, 편집, derive, 미리보기, 기저 모핑 실행).
2. **D2 결과 = 메시(rad/inc)만**: 새 ③ 스터디는 최적 안 STEP/BREP 내보내기를 하지 않는다.
3. **D3 고정점(잠정 — O-SG-1)**: A 모델 고정 노드(A Case fixed-scan → `prep/a_fixed`)를 B 메시로 기하 근접·투영으로 옮김(A·B 가 같은 좌표계일 때) / 아니면 자동 설정 없음 → 사용자가 표시(`fixed_user`, 기존) / 화면에서 항상 편집 가능. a_fixed 생성 방식·A↔B 정렬 유무는 조사(§0·§4).

## 0. 현황 (6278842, 근거 파일:행 · 실측)

| # | 항목 | 근거 | 현재 동작 | 이 계약에서 |
|---|---|---|---|---|
| G1 | ③ 비드 인식 | 이슈 #63 진단 7) | paicad extract 가 비드 6개(원형 엠보스)만 인식, **230건 제외**: 열린 비드 86·4링 아님 62·윗 필렛 없음 42·found 5 18·그 밖 22 | 메시 분류기 그래프(BG-D-1~14) — paicad 는 힌트만(BG §5.3) |
| G2 | ③ 안 형상 생성 | #63 진단 1)~2), `worker/esl_worker/doe_jobs.py` `_grid`:802·`_one_design`:964(update) | paicad `shell view grid`·`shell update` 가 B-rep 시트를 고침 → `occ_sheet.old_curve()` 가 **퇴화 모서리(degenerated edge, 3D 곡선 없음)**에도 3D 곡선을 요구해 셀 30개 중 29개 `GEOM_CAD_FAILED "edge E1927 has no 3D curve"`(시트에 같은 모서리 187개) | 새 ③ 은 grid·update 를 부르지 않음(기준 메시 기저 모핑) → 이 결함 경로 없음. paicad 결함 자체 수정은 paicad 쪽(범위 밖) |
| G3 | ③ 기준 메시 | `esl/doe/stages.py` `bd_mesh0`:284 | `scenario step` 만 gmsh(`bead_doe.mesh` 프로필, h = 입력 `mesh_size_mm`, 기본 A 메시 중앙값), 사다리 없음 | ④ 사다리(C2-D-9·18·26~31)를 같은 설정으로(SG-D-4) |
| G4 | ③ 안 메시·하중 | `stages._design_mesh`:541~560(TODO SR-D-44·BG-D-45), BD-D-3·4·10 | 안마다 BREP 재메시 → `design_target`(frame 고정, 안마다 auto 3-2-1) → 안마다 `entry_loads` 셀 매핑, 순위에 `noise_floor` | 기준 메시 1개를 기저 모핑(노드 ID 불변) → 하중·지지 1회(② 와 같음, SG-D-8·9) |
| G5 | A 고정점 | 워커 `_geom`:429~430(`_a_case` — ②③ 첫 ESL 의 A Case → `prep/a_assem_full/` 모델 사본 → `shell fixed-scan` → `prep/a_fixed/`), 코어 `_boundary`:371 | **경계 경고 전용**(BD-D-14 `BOUNDARY_FASTENER_FAR`): A 체결 클러스터 중심을 A frame (a,b) → 정규화 (ξ,η) → B frame (a,b)(`boundary.transfer`)로 옮겨 B 구멍 중심까지 거리 비교. ③ 모핑은 고정 없음(BD-D-11 `--fixed-dir ""`). ② select 도 A 고정 이전 안 함(D-0.16.2-MESHFIX, AD O-1) | 같은 정규화 이전 + B 구멍 스냅 → seed `fixed_user`(SG-D-12~15) |
| G6 | A↔B 정렬 | `esl/doe/boundary.py` `transfer`:36, `esl/doe/scenario.py` `template_base`:158(axis_ref = A ESL) | **③ 에는 A↔B 좌표 정렬 단계가 없다.** 유일한 대응은 두 frame(원점·e_xi·e_eta·L_xi·L_eta)의 정규화 좌표 대응. 같은 좌표계·같은 크기면 이 대응이 항등에 가까움(크기 규칙 ±5 % — BD-D-2) | 정규화 이전을 언제나 씀(같은 좌표계 여부 판단 불필요 — SG-D-12) |
| G7 | ③ 결과 받기 | BD-D-18, `esl/doe/export_mesh.py` `write`:26 | `ch_r.rad`·`ch_r.fem` + `sample.brep`·`sample.step` + `values.json` | 메시만(D2, SG-D-17) |
| G8 | ③ grid 실패 처리 | #63 진단 4)~6) | 셀 0개 성공인데 RESULT OK 로 등록, os.replace WinError 5, a_fixed 미전달 | **v0.17.2 핫픽스**(legacy ③ 전용, 병행 진행) — 이 계약은 손대지 않음 |

### 0.1 삼각형 메시 실측 (BG H6 픽스처를 짧은 대각선으로 전부 삼각형 분할 — tria 사다리 메시의 대리, 2 코어 클라우드)

| 항목 | 4각 원본(104 438 요소, 삼각 3 903) | 전부 삼각(204 973 요소) | V-BG-1 기준 |
|---|---|---|---|
| classify 시간 | 3.7~4.3 s | 5.2 s | — |
| class 정확도 | 99.91 % | **99.82 %** | ≥ 99.0 % |
| 바닥 identity / tier | 99.96 / 99.92 % | 99.97 / 99.84 % | ≥ 99.5 % |
| 벽 소유 | 99.01 % | **98.00 %** | ≥ 98.5 % → **미달** |
| 세그먼트 라벨 | 99.22 % | 99.14 % | ≥ 98.5 % |
| 세그먼트 23/23 · 접합 16/16(종류) · 섬 97 · 랜스 16 · 걸침 4 · 구멍 78(고정 78) | 모두 일치 | **모두 일치** | 100 % |
| 모핑 레시피(V-BG-5) a·d·f·g | 통과 | **통과**(뒤집힘 0·바깥 0·달성 ± 1e-14) | — |
| 모핑 레시피 b(ch1 D +2)·e(ch1+ch2 D −2) | 통과 | **실패**: 바깥 이동 7·18 노드 최대 2.00 mm(걸친 보스 섬 23·24 — BG-D-27 접촉 띠), e 뒤집힘 2 | 바깥 ≤ 1e-9 |
| 모핑 레시피 c(ch1 W +3) | 통과 | **실패**: 같은 섬 노드 7 바깥 0.26 mm, 뒤집힘 7 | 뒤집힘 0 |

- 해석: 분류는 삼각형 메시에서도 동작(벽 소유만 0.5 %p 미달 — 경사 벽 삼각형이 두 전이에 걸침). 모핑 결함은 **벽에 걸친 보스(BG-D-27)의 남의 바닥 접촉 띠**가 삼각형 대각선 때문에 한 요소 더 넓게 잡히지 못해 생김 — 판정이 `BG_OUTSIDE_MOVED`(FAILED_MESH)·뒤집힘으로 **잡아내므로 조용히 틀린 결과는 없다**. 걸친 보스가 없는 세그먼트·면형·네트워크 변수는 정확.
- 크기 실측(같은 장비): 418k 요소(H6 중점 4분할, h 1.5) classify 11.9 s·최대 RSS 706 MB, 세그먼트·접합 수 원본과 같음.

## 1. 목적 · 범위

| 범위 (v0.18.0) | 비범위 |
|---|---|
| 새 ③ 스터디 = `select` + `inputs.select_base: "step"`(schema 2 고정) — v0.16.2 ② 전환(`select_base: "mesh"`)과 같은 방식 | 기존 `scenario: step` 스터디의 변경(실행·복제 그대로 — §5.3) |
| BD_MESH0: B STEP → ④ 사다리(cad → … → freeform → … → tria, `compare.mesh.mode`/`ladder`, ④ 프로필 h) → 기준 메시 + `template_base`(frame·3-2-1·크기 규칙) | 새 메시 방식·사다리 단계(④ 그대로) |
| BD_LOADS: 하중 셀 매핑 1회·경계 경고·beadgraph 분류·자동 seed — ② select 와 같은 함수 | beadgraph 패키지 변경(1.0.0 그대로 — O-SG-3) |
| A 고정점 이전(정규화 frame + B 구멍 스냅) → seed `fixed_user`(편집 가능) | ② select 의 A 고정 이전(AD O-1 그대로 — 필요하면 같은 함수로 다음 판) |
| 결과 받기 = 메시(`export_mesh`) + values | 최적 안 STEP/BREP 내보내기(D2) |
| 화면: ③ 라디오가 새 경로로, 입력 칸(STEP·인치·물성·메시 방식), 준비 요약(메시 방식·고정 이전) | 새 화면 |
| tria 사다리 메시 경고(O-SG-2)·600k 요소 한계·폴백 | paicad 퇴화 모서리 결함 수정(paicad 쪽) |

## 2. 흐름

```text
새 ③ 스터디 (scenario select, inputs.select_base "step", select_schema 2, bead_source auto|manual)
 ├ BD_INPUT  (INTERNAL) _sel_input: B STEP → input/step/<name>(sha 재확인), props·inch → prep/input.json {select_base "step"}
 ├ BD_MESH0  (INTERNAL) _sel_mesh0 = ④ _cmp_mesh_shape(row d000, h = ④ 프로필 size_mm, ccfg = compare_cfg, mode·ladder 스냅샷)
 │             → prep/mesh0/{mesh.npz, mesh.json(mesh_method, stage_times, …)} → sc.template_base(B = 템플릿, axis_ref = A ESL)
 │             → prep/base_mesh.npz·base.json (scenario "select") · 사다리 끝이 tria = 경고 STEP_GRAPH_TRIA(SG-D-6)
 ├ BD_GEOM   (LOCAL, 워커) _geom_select step plan = [a_fixed(A Case 있으면 — ②③ 그대로)] + (auto) extract0 → extract(힌트)
 │             (B 조립 없음 → fixed-scan 없음, grid·update 없음)
 ├ BD_LOADS  (INTERNAL) _sel_loads:
 │             하중 sc.entry_loads(t, …) 1회(S2 셀 매핑 + 평형 보정) → prep/loads.npz      ← ② select 와 같은 함수(SG-D-8)
 │             지지 = t.supports(template_base auto 3-2-1) 1회                          ← ② 와 같음(SG-D-9)
 │             경계 경고 _boundary(B 후보 = B 구멍만) → prep/boundary.json                  ← ③ 그대로
 │             고정 이전 step_graph.fixed_transfer(a_fixed, frame A→B, B 구멍) → prep/select/fixed_transfer.json (SG-D-12~15)
 │             분류 bead_graph.prep_graph(mesh, fixed = 이전 노드, cfg + step 상한) → graph.json·labels·graph.bin·w_clamp.json
 │             seed  auto_selection.json(auto = 그래프 seed + fixed_user, manual = 빈 비드 + fixed_user)
 ├ (화면)    같은 BeadSelectCard / 트리 / 편집 / derive / [선택 저장]
 ├ BD_MATRIX · 미리보기 bd_select_grid · BD_DESIGNS(bd_eval select 분기 — 기저 모핑, paicad 없음) · BD_POST (①② 와 같음)
 └ 받기      최적·상위 k: ch_r.rad·ch_r.fem(export_mesh, 기저 모핑 좌표) + values.json — STEP/BREP 없음(D2)
```

## 3. 결정

### 3.1 시나리오 · 입력

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-1 | **시나리오 키 = `select`, 기준 출처 `inputs.select_base: "step"`**(값 추가: `case`\|`mesh`\|**`step`**). 새 시나리오 키·DB CHECK 변경 없음. v0.16.2 ② 전환(D-0.16.2-MESHSEL)과 같은 방식 | migration 없음, ①②③ 가 같은 select 코드 경로 |
| SG-D-2 | **step 기준은 schema 2 고정**: `select_base: step` + `select_schema` ≠ 2 = 422 `INVALID_PARAMS`. 새 select 스터디는 v0.17.0 부터 이미 schema 2 | 그래프 없이는 ③ 자동 seed 가 없음 |
| SG-D-3 | **입력**(DoeCheckIn/DoeStudyIn, `select_base: "step"`): `step_upload_id` **필수**(auto·manual 모두 — 기준 메시 원천), `props{t, E, nu}` 필수(③ 기본값 §7.3 그대로 `props_default`), `inch?`(크기 규칙), `mesh_mode?`(④ 와 같은 값·의미 — 없으면 `compare.mesh.mode`), `mesh_refine?`(④ 와 같음). 금지 = `mesh_upload_id`·`part_title`·`mesh_size_mm`(h 는 ④ 프로필 — SG-D-4) → 422 `INVALID_PARAMS`. `bead_source` auto\|manual(기본 manual — AD 그대로) | ③ 입력 그대로 + ④ 메시 방식 |
| SG-D-4 | **메시 = ④ 사다리, 같은 설정**(D1): h = `sc.compare_profile(cfg)["size_mm"]`(기본 3 mm = 낙하 메시 기준, `mg.check_h`), gmsh 설정 = `sc.compare_cfg(cfg)`, 모드·사다리 = ④ `_cmp_mode` 규칙(스냅샷 `doe.mesh_mode`·`doe.mesh_ladder` → 없으면 설정), 단계 시간 몫·예산·시도 폴더·`keep_tries`·면 실패 판정·단계별 문구 = C2-D-18~31 그대로. 형상 행 id = `d000`, 폴더 = `prep/mesh0/`(시도 = `prep/mesh0/try_<n>/`). ③ 의 `bead_doe.mesh` 프로필·`mesh_size_mm` 은 새 ③ 에서 쓰지 않음 | 사용자 D1 "같은 설정", ④ 실서버 성공률(v0.16.3) |
| SG-D-5 | **④ 사다리 함수 재사용 방식**: `_cmp_mesh_shape`·`_cmp_ladder`·`_cmp_mesh_one`·`_cmp_defeature_stage`·`_cmp_remesh_one` 에 키워드 `mesh_dir=None`(None = 지금 `_cmp_mesh_dir(c, did)`)만 추가. ④ 호출은 인자 없이 그대로 → **④ 바이트 불변**(V-SG-9). 사다리 전부 실패 = 작업 실패 `MESH_FAILED`(문구 `MESH_LADDER_FAILED` 그대로 — 기준 d000 실패 규칙 C2-D-9), `MESH_TOO_LARGE`·`GMSH_UNAVAILABLE` 은 ④ 와 같음 | 코드 1벌 |
| SG-D-6 | **tria 로 끝난 메시 = 경고, 막지 않음**(O-SG-2 권장): `mesh_method` 가 tria(또는 삼각형 비율 > `select.step_graph.tria_warn_frac` 0.5)이면 준비 경고 `STEP_GRAPH_TRIA{mesh_method, tri_frac}`("삼각형 메시 — 걸친 보스가 있는 채널의 D·W 안은 바깥 이동으로 실패할 수 있음") + ④ 경고 `MESH_TRIA_FALLBACK` 그대로. 분류·모핑은 진행, 안 판정은 BG-D-34·뒤집힘이 그대로 막음(§0.1). `tria_policy: block` 이면 준비 실패 `STEP_GRAPH_TRIA_BLOCKED` | §0.1: 분류 정상, 모핑 실패는 판정이 잡음 — 막으면 사다리가 살린 형상을 다시 버림 |
| SG-D-7 | **기준 메시 = template_base**(③ BD_MESH0 와 같은 함수): frame = B 메시(`axis_ref` = 첫 ESL), 법선 정렬, 자동 3-2-1, 크기 규칙 B = 템플릿(±5 %, `SIZE_MISMATCH`), `save_base(scenario "select", extra {props, h, mesh_method, gmsh_version})`. 노드 ID = 사다리 메시 번호(1부터) | 같은 함수 |

### 3.2 하중 · 지지 · 평가 일관성

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-8 | **하중 = ② select 와 같은 함수 1회**: `stages._sel_loads` → `sc.entry_loads(t, ents, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"], (grid nx, ny))` — `t.scenario == "S2"` 이므로 ESL 마다 `tg.entry_load(t, None, e.summary_for_mapping(), mapping_opts)` = **`esl.library.mapping.to_target`(24×14 셀 합력·합모멘트) + 평형 보정**, frame = B 기준 메시. 결과 `prep/loads.npz`(B 노드 ID) → **모든 안에 같은 노드 하중**(모핑은 ID 불변). 셀당 노드 경고 그대로 | D-0.16.2-MESHMAP(AD-D-15·18·19)과 같은 경로 — 매핑 잡음 0 |
| SG-D-9 | **지지 = template_base 의 `auto_supports` 1회**(B 기준 메시), 모든 안 같은 node_id(② BD-D-4). `support_check` rank < 6 = 준비 실패 `SUPPORT_DEGENERATE`(기존) | ② 와 같음 |
| SG-D-10 | **평가 일관성**: d000 = 사다리 기준 메시 + 위 하중·지지(`_design_mesh` BASELINE 분기 그대로), 안 = 같은 메시 + 기저 모핑 좌표(`_design_mesh` select 분기 그대로 — 코드 변경 없음), 해석 = `ev.evaluate` 같은 해석기 설정, 점수 = 안 최악 C / d000 최악 C(`rank` 그대로). 안 메시가 d000 과 위상이 같아 **메시 잡음 없음** → `noise_floor` 계산·"잡음 이내" 표시 없음(② 와 같음). `keep_mesh`(design.npz 에 메시) = 아니오(select 와 같음) | 같은 메시에서 형상만 다름 |
| SG-D-11 | **기존 ③ 과의 비교**: 같은 B STEP 이라도 새 ③ d000 은 기존 ③ d000 과 **바이트·수치가 같지 않다**(메시 프로필 ④ 3 mm vs ③ `mesh_size_mm`, 안 하중 재매핑 없음). 같은 스터디 안 비교만 보장. 보고서 방법 절에 "③ 그래프(기준 메시 기저 모핑, 메시 방식 <method>)" 1줄 | 사용자에게 다른 방식임을 드러냄 |

### 3.3 고정점 (D3 — 잠정, O-SG-1)

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-12 | **A 고정점 출처 = 지금의 `prep/a_fixed/`**(워커 `_a_case` — 첫 ESL 의 A Case 입력 → `prep/a_assem_full/` 모델 사본 → `shell fixed-scan --parts <A part>` → `fixed_scan.json`·노드 표 {node_id, xyz, cluster, kind_mask}). A Case 없음·fixed-scan 실패 = 이전 없음 + 정보 `FIXED_XFER_NONE{reason: A_CASE_MISSING\|A_SCAN_FAILED}`(준비 READY) | 새 paicad 호출 없음 |
| SG-D-13 | **이전 = 정규화 frame + B 구멍 스냅**(같은 좌표계 여부를 가정하지 않음 — G6): A 클러스터 중심(`pio.fixed_points`) → `project_ab(frame_A)` → `boundary.transfer(frame_A, frame_B)` → B 평면 (a,b). B 구멍 = `boundary.hole_centers`(B 기준 메시, `keepout.hole_min_perimeter_mm`, 자유 모서리 고리)와 평면 거리 d. d ≤ `select.step_graph.fixed_transfer.snap_mm`(null = `boundary.fastener_warn_mm` 10)인 가장 가까운 구멍 1개에 스냅(동률 = 작은 구멍 번호, 한 구멍에 여러 A 클러스터 = 1회). 그 구멍 **둘레 노드**(고리 노드) = 이전 고정 노드. 스냅 실패 = 이전 안 함 + 정보 `FIXED_XFER_UNMATCHED{label, d_mm}`(BD-D-14 `BOUNDARY_FASTENER_FAR` 경고와 같은 대상). A·B 가 같은 좌표계·같은 크기면 이 이전은 항등에 가깝고(크기 규칙 ±5 %), 다르면 정규화가 맞춤 | 경계 경고가 이미 같은 대응을 씀 — 하나의 규칙. 구멍 없는 곳에 고정 노드를 만들지 않음 |
| SG-D-14 | **이전 결과의 쓰임**: (a) 분류 입력 `fixed`(BG-D-5 — 구멍·섬 `fixed` 표지, graph sha 에 포함), (b) **seed `fixed_user`** = 각 이전 구멍 고리 노드를 2개 이상 가진 요소(첫 요소 고리) ElemSet → 화면 고정 층에 미리 칠해짐 → **추가·지우기 모두 기존 칠하기 도구로**(D3 "항상 편집"). B fixed-scan 이 없으므로 `fixed_scan` = 빈 집합(derive·manifest `fixed.source = "a_transfer"`, `scan_n` 0, `xfer_n`) — 즉 이전 고정은 **사용자 선택의 일부**이고 저장 후에는 선택 sha 에 들어감 | 고정 출처를 편집 불가한 scan 으로 두면 D3 위반 |
| SG-D-15 | **파일** `prep/select/fixed_transfer.json` = `{schema "esl/doe_fixed_transfer/1", method "ab_hole_snap", snap_mm, frame_a_sha, frame_b_sha, matches[{a_label, kind, a_ab[2], b_ab[2], hole, d_mm, n_nodes}], unmatched[{a_label, kind, b_ab[2], d_mm\|null}], node_id[], elems(ElemSet)}`(결정적 바이트 — 키 정렬·1e-3 반올림). `fixed_transfer.enabled: false` = 파일 없음 + `FIXED_XFER_NONE{reason: DISABLED}` | 화면 요약·시험 근거 |

### 3.4 분류 · 선택 · 결과

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-16 | **분류·선택·모핑·판정 = BG 그대로**: `_sel_graph`(prep_graph) → `_sel_w_clamp` → `_sel_auto_v2`(seed) → derive_v2·basis_v2·design_checks_v2. 다른 점은 (i) 요소 상한 = max(`select.graph.limits.max_elems`, `select.step_graph.max_elems` 600 000), 시간 상한 = max(`limits.timeout_s`, `step_graph.timeout_s` 300)(§7), (ii) seed 에 `fixed_user`(SG-D-14), (iii) **manual 도 seed 파일을 씀**(빈 비드 + fixed_user, `source: "fixed_transfer"`) — `GET …/select/auto` 는 step 기준이면 bead_source 와 무관하게 돌려줌. `GRAPH_FAILED` = BG-D-40 그대로(준비 READY, `src: elems` 비드로 계속) | ①② 와 같은 화면·같은 판정 |
| SG-D-17 | **받기 = 메시만**(D2): 최적·상위 k 안 = `esl.doe.export_mesh.write(dir, mesh(x = 기저 모핑 좌표), part_title = STEP 파일 이름 줄기)` → `ch_r.rad`(/NODE·/SHELL·/SH3N·/PART·/PROP·/MAT, ID = 기준 메시 번호) + `ch_r.fem` + `values.json` + select 주석(`_sel_fixed_comment` 그대로). `sample.brep`·`sample.step` 없음. `_sel_best` 에 step 분기 1개(①=Case include 사본, ②=B rad 사본, ③=export_mesh) | 기준 메시에 원 rad 가 없음 — ③ 기존 export 함수 재사용 |
| SG-D-18 | **paicad 의 역할**(새 ③): auto + STEP 이면 `extract0 → extract` **힌트만**(`AUTO_SLOPE_DIFF`, BG §5.3 — tag·grid·update 없음). 힌트 실패(#63 같은 B-rep 결함 포함) = 정보 `AUTO_HINT_UNAVAILABLE`. paicad 없음 = 힌트 없이 진행 — **새 ③ 은 paicad 가 없어도 동작**(`scenarios.select_step` 은 gmsh·select 만 봄). A 고정점은 paicad fixed-scan(G5)이라 paicad 없으면 `FIXED_XFER_NONE{A_SCAN_FAILED}` | D1, paicad 는 힌트·legacy 용으로 설치 유지 |

## 4. 데이터 · API 변경 (최소)

### 4.1 저장 자료
- `studies.inputs`(JSONB) += `select_base: "step"`(값 추가), 기존 키 재사용: `select_schema: 2`, `step{file_name, sha256}`, `props`, `inch`, `mesh_mode`, `bead_source`. 스냅샷 `doe` += `select_base: "step"`, `mesh_mode`, `mesh_ladder`(④ 와 같은 이름·의미).
- `prep/input.json` += `select_base: "step"`, `mesh{method, n_nodes, n_elems, tri_frac, stage_times}`, `fixed{source: "a_transfer"|"none", n, xfer: {matched, unmatched}}`.
- 새 파일: `prep/mesh0/**`(④ 형식 그대로), `prep/select/fixed_transfer.json`. 그 밖 `prep/select/*` 는 BG 그대로.
- 이어하기 해시(`input_sha256`): step 기준 = (STEP sha, props, inch, 메시 모드·사다리·④ 프로필 해시 — C2-D-15 규칙 그대로, `compare_profile` sha). ①② 해시 식 불변.

### 4.2 API (`/esl/api`)
```
DoeCheckIn/DoeStudyIn(select)   select_base: "case"|"mesh"|"step"  (+ SG-D-3 검사)
                                 mesh_mode?·mesh_refine? = compare 또는 select_base step 에서만(그 밖 422 MESH_MODE_COMPARE_ONLY 그대로)
DoeCheckOut(select, step)        += step{file_name, sha256}, props_default, size, mesh_mode, remesh_available (④ 와 같은 필드)
GET  /doe/settings               scenarios += select_step (= select 가능 ∧ gmsh ready; paicad 무관), select.step_graph{tria_policy}
GET  /doe/studies/{sid}/select/auto   select_base step = bead_source 무관하게 seed(SG-D-16), 없으면 404 그대로
DoeStudyOut.prep                 += mesh{method, tri_frac, stage_times}, fixed{source, n, xfer{matched, unmatched}}
POST /doe/studies (scenario step) 계속 받음(스크립트 호환 — AD-D-23 과 같음), 화면만 숨김
```
- 새 오류·경고 코드(문구 원본 `resources/doe_messages.json`): `STEP_GRAPH_TRIA`(경고)·`STEP_GRAPH_TRIA_BLOCKED`(준비 실패 — block 정책일 때만)·`FIXED_XFER_NONE{reason}`(info)·`FIXED_XFER_UNMATCHED{label, d_mm}`(info). 그 밖은 BG·C2·BD 코드 그대로.

### 4.3 설정 키 (`DEFAULTS["select"]["step_graph"]` = pydantic `BeadDoeSelectStepGraphCfg` = `config/*.example.yaml` 2개 거울)
```yaml
bead_doe:
  select:
    step_graph:                     # v0.18.0 STEP_GRAPH — select_base step 스터디만 읽음
      max_elems: 600000             # 분류 요소 상한(= ④ refine.max_elems 기본) — §7
      timeout_s: 300                # 분류 시간 상한
      tria_warn_frac: 0.5           # SG-D-6
      tria_policy: warn             # warn | block (O-SG-2)
      fixed_transfer: {enabled: true, snap_mm: null}   # null = boundary.fastener_warn_mm (SG-D-13)
```
- 해시: `select_hash_view` 는 `step_graph` 를 **select_base step 스터디에서만, 기본값이 아닐 때만** 넣음(`HASH_NEW_KEYS_V0180 = ("step_graph",)`) → ①② schema 1·2 `_cfg_hash`·`_sel_cfg_sha` = v0.17.1 과 같음(V-SG-10).
- 검사: `max_elems` 1..2e6, `timeout_s` gt 0, `tria_warn_frac` (0, 1], `tria_policy` ∈ {warn, block}, `snap_mm` null 또는 gt 0.

## 5. 이전 · 호환

### 5.1 새 ③
- 화면 ③ 라디오 = `radioRequest("step") → {scenario: "select", selectBase: "step"}`. 새 ③ 스터디는 `scenario: step` 을 만들지 않는다.

### 5.2 판 · 바이트
- `bead_select.ALGO`·`RULES`(3)·`GRAPH_ALGO`(1)·`graph_rules`(1)·beadgraph 1.0.0(RULES 1·MORPH_RULES 1) **그대로**. 새 ③ 은 같은 판을 기록.
- ①② select(schema 1·2)·④ compare: 준비·기저·판정·결과·해시 바이트 불변(V-SG-9·10).

### 5.3 기존 ③ (`scenario: step`, paicad)
- 그대로 실행·복제(복제본도 `step`): 워커 `_geom`·`_grid`·`_one_design`(update) 경로, 코어 `bd_mesh0`·`_design_mesh` ③ 분기·`noise_floor`·BREP/STEP 내보내기 불변. **v0.17.2 핫픽스 결과가 기준**(grid 전부 실패 = 단계 실패, a_fixed 전달 등). 화면은 기존 ③ 스터디를 "③ 다른 모델(STEP만) — 이전 방식(paicad)"으로 표시(읽기·실행·복제 버튼 그대로).
- paicad 는 계속 설치·점검(`scenarios.step` 은 지금 규칙 그대로 — legacy 실행용). `_design_mesh` 의 TODO(SR-D-44·BG-D-45) 줄은 "새 ③ = select_base step 으로 해소" 주석으로 바꿈(동작 변경 없음).

### 5.4 migration
- **없음**: `inputs`·스냅샷은 JSONB, 시나리오 값·CHECK 불변, 새 테이블 없음. `VERSION` 0.18.0·`CHANGELOG.md`·openapi info.version 만.

## 6. 화면 (새 화면 없음, 2560×1440 기준·1920×1080 잘림 없음)
- **새 스터디 라디오**: ③ "다른 모델(STEP만)" → select step. 하위 "비드" auto/manual(①② 와 같은 하위 라디오). 막힘 사유 = `scenarios.select_step`(gmsh 없음 → `GMSH_UNAVAILABLE` 문구).
- **입력**(`DoeInputs`): STEP 칸(필수), 인치, 쉘 물성(t·E·ν — ③ 그대로), 메시 방식(④ 의 고급 설정 칸 재사용 — 기본 접힘). "평균 요소 크기" 칸 없음(h = ④ 프로필, 요약에 "요소 크기 3 mm(④ 설정)" 표시).
- **준비 요약**: 메시 방식 칩(cad / 폴백 freeform / 삼각형 폴백) + 단계별 시간(④ 문구), `STEP_GRAPH_TRIA` 경고, 고정 이전 1줄 "A 체결점 n개 중 m개를 B 구멍으로 옮김 — 고정 층에서 수정"(+ 못 옮긴 목록) — 모두 v0.17.1 접힘 규칙(D-0.17.1-FOLD).
- **평면도**(`BoundaryPlan`): 기존 A 체결점 → B 대응 선 위에 이전된 구멍을 고정 색으로 표시(스냅 안 된 것은 지금 경고 표시 그대로).
- **선택 카드**: BeadSelectCard / 트리 / 3D = BG §6.2 그대로. 고정 층이 seed `fixed_user` 로 미리 칠해짐(되돌리기·초기화 = seed 로 — AD-D-4).
- **결과 받기**: 링크 이름 "메시 ch_r.rad"(③ 과 같은 문구), STEP/BREP 링크 없음.

## 7. 성능 한계 · 폴백

| 항목 | 한계 | 근거 · 장치 |
|---|---|---|
| 메시 요소 | 사다리 `refine.max_elems` 600 000(④ 그대로), cad 시도 `MESH_TOO_LARGE` = 폴백 없음(C2-D-9) | ④ |
| 분류 classify | 600 000 요소 ≤ 300 s·RSS ≤ 1.5 GB | 실측(2 코어): 104k 4 s·231 MB, 205k(삼각) 5 s, 418k 12 s·706 MB → 600k ≈ 17 s·≈ 1.0 GB. 서버 실측 220k 20~48 s(사용자) → 600k 선형 외삽 55~130 s — 180 s 기본은 빠듯해 step 만 300 s |
| 상한 초과 | > `step_graph.max_elems` = `GRAPH_FAILED{TOO_LARGE}`, 시간 초과 = `GRAPH_FAILED{TIMEOUT}` → 준비 READY + `src: elems` 비드(직접 칠하기)로 계속(BG-D-40). 문구에 "④ 메시 크기 설정(size_mm)을 키우면 분류 가능" 안내 | 막지 않는 폴백 |
| derive(schema 2) | 600k ≤ 8 s(그래프·labels 캐시 읽기), `derive_timeout_s` 20 안 | BG 3 s(220k) 선형 |
| 기저 | 변수당 ≤ 15 s(세그먼트 바닥 크기 비례 — 600k 는 h 가 작아 바닥 노드 ≈ 2.7×), 20 변수 ≤ 180 s | BG §7 × 2.7 |
| 브라우저 | graph.bin 600k × 6 × 4 B = 14.4 MB, select.bin·part.glb 는 ② 큰 B 메시와 같은 규모 | 디코드 ≤ 500 ms 목표(V-SG-8) |

## 8. 시험 (V-SG-*)

**합성 STEP**: 신규 `tests/doe/synth_step_graph.py` — `beadgraph.testing.synth_h6`(·`synth_h5`)의 평면 형상 나무(`build_tree`·`domain_and_creases`·`faces_of`)를 `evaluate` 로 높이를 올려 OCC 면으로(같은 평면이면 평면 면, 아니면 경계 `addSurfaceFilling`) → 봉합 → `h6_sheet.step`·`h5_sheet.step`(gmsh 필요 — 없으면 skip, 생성 STEP sha 는 gmsh lock 판에서만 고정). 정답 = `synth_h6.ground_truth(mesh, root)`(형상 기준 라벨 — **어떤 메시에도** 적용). 삼각형 대리 = 사다리 메시를 짧은 대각선으로 분할(§0.1 식).

| ID | 시험 | 위치 |
|---|---|---|
| V-SG-1 | **H6 STEP → cad 메시 → 분류**: V-BG-1 기준 그대로(class ≥ 99.0 %·각 재현율/정밀도 ≥ 98.5 %, 바닥·tier ≥ 99.5 %, 벽 소유 ≥ 98.5 %, 세그먼트 라벨 ≥ 98.5 %, 세그먼트 23/23·접합 16/16·섬 97·랜스 16·걸침 4·구멍 78) | `tests/doe/test_step_graph.py` |
| V-SG-2 | **H6 STEP 모핑**: V-BG-5 레시피 (a)~(g) 를 사다리 cad 메시에서 — 뒤집힘 0, 바깥 ≤ 1e-9, 달성 D ± 1e-6·W ± 1e-3, 섬 잔차 ≤ 1e-9, 고정 이동 ≤ 1e-12(이전 고정 노드, hold 1), (f) `BG_SHARED_CHILD`, (d) `BG_CORNER_GUARD`. H5 STEP 레시피 = V-BG-6 기준 | 같은 파일 |
| V-SG-3 | **삼각형 메시**: (a) 주입 `ESL_TEST_MESH_FAIL=cad,freeform` 으로 사다리가 tria 로 끝남 → 준비 READY + `MESH_TRIA_FALLBACK`·`STEP_GRAPH_TRIA`, 그래프 생성. (b) 삼각형 대리(H6 분할) 분류 = class ≥ 99.0 %, **벽 소유 ≥ 97.5 %**(실측 98.00), 세그먼트·접합·섬·구멍 수 V-SG-1 과 같음. (c) 레시피 a·d·f·g 는 V-SG-2 기준 통과, b·c·e 는 **판정이 잡음**(안 상태 FAILED_MESH `BG_OUTSIDE_MOVED` 또는 뒤집힘 제외 — READY 로 새지 않음, 현재 수치 n 7·18 / 2.0 mm 고정). (d) `tria_policy: block` → `STEP_GRAPH_TRIA_BLOCKED` | 같은 파일 |
| V-SG-4 | **고정 이전**: (a) 같은 좌표계: A = H6 픽스처(+ `fixed`), B = H6 STEP 메시 → A 고정 구멍 전부 매칭(d ≤ 1 mm), 이전 노드 = 그 구멍 고리 노드, seed `fixed_user` 요소 = 첫 고리. (b) B 를 1.03 배·회전·평행 이동 → 정규화 이전으로 같은 매칭 ≥ 95 %. (c) B 에 없는 구멍 1개 → `FIXED_XFER_UNMATCHED` + `BOUNDARY_FASTENER_FAR` 같은 라벨. (d) A Case 없음 → `FIXED_XFER_NONE{A_CASE_MISSING}`, seed fixed_user 빈 집합. (e) 사용자가 seed 고정을 지우고 저장 → 기저 hold 없음(ψ = 1), 다시 칠하면 hold. (f) 결정적 바이트 2회 동일 | `tests/doe/test_step_graph_fixed.py` |
| V-SG-5 | **하중·지지·평가 일관성**: step 기준 하중 = 같은 메시를 ② select(`select_base mesh`, rad 왕복)로 넣은 하중과 노드별 ± 1e-12, 지지 node_id 동일, d000 결과 동일. 모든 안의 loads.npz sha = d000. `noise_floor` 키 없음 | 같은 파일 |
| V-SG-6 | **API**: select_base step 검사(STEP 필수·props·금지 칸 422·schema 1 422·mesh_mode 허용), settings `select_step`(paicad 없음 + gmsh 있음 = true), `GET select/auto` manual seed, `scenario: step` 생성 계속 허용, 복제(step 기준·legacy step 각각), pydantic `step_graph` 검사 | `backend/tests/test_doe_step_graph_api.py` |
| V-SG-7 | **워커 E2E**: H5 STEP, A Case 있음(paicad 대역 — 기존 워커 시험 방식) → BD_INPUT·BD_MESH0(사다리)·BD_GEOM(a_fixed + 힌트, fixed·grid·update 호출 없음)·BD_LOADS(그래프·seed·이전) → seed 저장 → 미리보기 → 실행 → 순위·보고서·받기(ch_r.rad·ch_r.fem·values.json, sample.step/brep 없음). `GRAPH_FAILED` 주입 → elems 비드로 실행. paicad 없음 → 힌트·이전 없이 실행 | `worker/tests/test_doe_step_graph_jobs.py` |
| V-SG-8 | **화면**: ③ 라디오 → 요청 본문(select + step), 입력 칸(요소 크기 칸 없음·메시 방식 칸), 준비 요약(방식 칩·TRIA 경고·이전 1줄 접힘), 고정 층 seed, legacy ③ 표시, 받기 링크, 2560·1920 잘림 없음, 600k graph.bin 디코드 ≤ 500 ms | `frontend/src/__tests__/doe_step_graph.test.tsx`, mock |
| V-SG-9 | **④·①·② 바이트 불변**: `regress.py`(작업 폴더 — V-C2-30 과 같은 방식) ④(mode 없음·cad·auto, 형상 h5·h3 × step·case) mesh·loads·순위 바이트 동일(mesh_dir 인자 리팩터), ① case·② mesh select(schema 1·2) 준비·기저·판정·결과 바이트 동일, V-BG-* 전부 통과 | `tests/doe/*`, 작업 폴더 regress |
| V-SG-10 | **해시**: 기본 설정에서 ①② `_cfg_hash`·`_sel_cfg_sha` = v0.17.1 상수, `step_graph` 를 바꿔도 ①② 해시 불변, step 기준 스터디만 변함 | `tests/doe/test_bead_graph_cfg.py` 추가 |
| V-SG-11 | **legacy ③ 회귀**: 기존 `scenario: step` 스터디(픽스처) 준비·grid·안 평가·받기 = v0.17.2 결과와 바이트 동일, 복제본 `step` | `worker/tests/test_doe_jobs*.py`, `tests/doe/test_bead_doe*.py` |
| V-SG-12 | **성능(slow, perf)**: 600k 요소(H6 중점 분할 + 타일) classify ≤ 300 s·RSS ≤ 1.5 GB, derive ≤ 8 s, 600 001 → `GRAPH_FAILED{TOO_LARGE}` + elems 비드 경로 | `tests/doe/test_step_graph_perf.py` |
| V-SG-R1 | **실기**: 이슈 #63 실제 B STEP(da9dc714 입력) — 메시 방식, 세그먼트·접합 수, paicad 가 버린 230건 중 그래프가 세그먼트로 잡은 수, 이전 고정 매칭 수, 자동 seed 안 판정(뒤집힘·바깥 0) | `docs/manual/bead_doe_check.md` 절 추가 |

## 9. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-SG-1 | tria 메시에서 걸친 보스 채널 D·W 안이 바깥 이동으로 실패(§0.1) | `STEP_GRAPH_TRIA` 경고, 판정이 막음(조용한 오류 없음), 그 비드를 섬 전환·`src: elems` 로 우회, O-SG-3 |
| R-SG-2 | 정규화 이전이 비대칭·크기 다른 B 에서 엉뚱한 구멍에 스냅 | 스냅 반경 = 경계 경고 10 mm, 평면도 표시, seed 라 사용자가 지움, 이전 목록·거리 요약 |
| R-SG-3 | 사다리 cad 메시(④ 프로필 3 mm, OCC 작은 형상 정리·defeature)가 작은 비드·엠보스를 지움 → 분류 대상이 사라짐 | ④ 충실도 경고(`MESH_DEFEATURED`·`MESH_FREEFORM`) 준비 요약 노출, V-SG-R1 에서 확인 |
| R-SG-4 | 600k 근처에서 분류·기저·화면이 느림 | 상한·시간 상한·폴백(§7), 요소 크기 안내 |
| R-SG-5 | 새 ③ 과 기존 ③ 결과가 같은 STEP 에서 다름(SG-D-11) | 보고서 방법 줄, legacy 표시 |
| R-SG-6 | v0.17.2 핫픽스와 워커 파일 충돌 | §11 rebase 규칙, Backend 가 핫픽스 병합 뒤 착수 |

## 10. 열린 항목

### 10.1 열린 항목 (사용자 결정 필요 — 권장안을 기본값으로 작성, 최대 3)

| ID | 항목 | 권장안(현재 계약 값) | 다른 답이면 |
|---|---|---|---|
| O-SG-1 | **D3 고정점 기본값 확인** — 조사 결과 ③ 에는 A↔B 좌표 정렬이 없고(G6) a_fixed 는 A 메시 노드 ID 라 그대로 못 씀 | **정규화 frame 이전 + B 구멍 스냅(≤ 10 mm) → seed `fixed_user`(편집 가능)**, 못 옮긴 점은 없음 + info(SG-D-12~15). 같은 좌표계면 사실상 같은 위치 | (b) 자동 설정 없음: `fixed_transfer.enabled: false` 기본(사용자가 모두 칠함) · (c) 날 좌표 근접: frame 이 일치(원점 ≤ 5 mm·축 ≤ 2°)할 때만 A 노드 xyz 에서 B 최근접 노드 ≤ h — 구멍이 없는 고정(RBE2 패드)도 옮김 |
| O-SG-2 | **사다리가 tria 로 끝나면 경고 vs 막음** | **경고**(`tria_policy: warn`): 분류는 정상, 실패하는 안은 판정이 FAILED_MESH 로 잡음 — 막으면 ④ 사다리가 살린 형상을 다시 버림 | `block`: 준비 실패 `STEP_GRAPH_TRIA_BLOCKED` — 사용자가 STEP 정리·메시 방식 변경 후 재준비 |
| O-SG-3 | **beadgraph 삼각형 걸친 보스 접촉 띠 수정 시점** | **v0.18.0 은 패키지 1.0.0 그대로**(①② 바이트·physicsai 고정판 불변), 수정은 beadgraph 1.1.0(MORPH_RULES 2 — 그래프 스터디 기저 재계산 동반)로 별도 판 | v0.18.0 에 포함: Core 가 `zones`/`morph` 접촉 띠를 요소 고리 대신 노드 거리(≥ h)로 정의 → MORPH_RULES 2, V-BG-5 기대값·physicsai 인계 갱신 |

## 11. 파일 소유권 · 작업 분해 (겹침 없음)

**rebase 규칙**: 병행 핫픽스 **v0.17.2**(release/v0.17.2 — legacy ③ grid 전부 실패 처리·`--fixed-dir` 전달·os.replace 재시도)가 `worker/esl_worker/doe_jobs.py`·`worker/esl_worker/paicad_proc.py` 를 고친다. v0.18.0 구현 브랜치는 **v0.17.2 가 main 에 병합된 뒤 그 위로 rebase** 하고, Backend 는 `_grid`·`_geom`·`_one_design`·`paicad_proc.py` 의 핫픽스 줄을 건드리지 않는다(새 ③ 분기는 `_geom_select`·`run_step` 에만). V-SG-11 기준 = v0.17.2.

| 담당 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Core** | 신규 `esl/doe/step_graph.py`(`mesh0`(사다리 어댑터 → template_base·save_base), `fixed_transfer(a_fixed_doc, frame_a, t_b, cfg)`, `seed_fixed_user(mesh, nodes)`, `tria_check(mesh, meta, cfg)`, `export_best(…)`); `esl/doe/stages.py`(`select_base` 값 step·`_sel_input` step 분기·`bd_mesh0` step 분기·`_sel_loads` 고정 출처·이전·seed·step 상한 전달·`_sel_auto_v2` fixed_user·`_sel_best` step 분기·`_cmp_mesh_shape`/`_cmp_ladder`/`_cmp_mesh_one`/`_cmp_defeature_stage`/`_cmp_remesh_one` `mesh_dir` 인자·`_design_mesh` TODO 주석·`select_prep_info` step_rel); `esl/doe/bead_graph.py`(`prep_graph` 상한 인자·auto 문서 `fixed_user`·manual seed); `esl/doe/bead_select.py`(`HASH_NEW_KEYS_V0180`·`select_hash_view` step 조건만); `esl/doe/report_doe.py`(방법 줄); `esl/doe/__init__.py`(DEFAULTS `select.step_graph`); `resources/doe_messages.json`; 신규 `tests/doe/synth_step_graph.py`·`test_step_graph.py`·`test_step_graph_fixed.py`·`test_step_graph_perf.py`, `tests/doe/test_bead_graph_cfg.py`(추가) | V-SG-1~5·9·10·12 |
| **Impl-Backend** (`backend/**`, `worker/**`, `config/*.yaml`) | `backend/esl_platform/core/config.py`(`BeadDoeSelectStepGraphCfg`·settings 거울·`scenarios.select_step`); `api/schemas.py`(`select_base` Literal += step·DoeCheckOut step 필드·prep mesh/fixed 요약); `api/services/doe.py`(check/create/clone 검사·스냅샷 `select_base`·`mesh_mode`·`mesh_ladder`·settings); `api/services/doe_select.py`(`GET select/auto` step 규칙); `worker/esl_worker/doe_jobs.py`(**`_geom_select` step plan·`run_step` BD_MESH0 건너뜀 문구 분기만** — 핫픽스 함수 불변); `worker/esl_worker/register.py`(준비 요약 mesh·fixed); `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`; `backend/tests/test_doe_step_graph_api.py`·`worker/tests/test_doe_step_graph_jobs.py` + 기존 회귀 | V-SG-6·7·11 |
| **Impl-Frontend** (`frontend/**`) | `src/api/doe.ts`(`radioRequest`·`studyRadio`·legacy ③ 이름·`selectSubBlocked` step·seed 로드 조건); `src/api/types.ts`; `src/pages/doe/DoeStudy.tsx`(③ 라디오·입력 검사·준비 요약·받기 링크); `src/components/DoeInputs.tsx`(step 기준 칸·요약); `src/components/BoundaryPlan.tsx`(이전 고정 표시); `src/components/BeadSelectCard.tsx`(manual seed 고정 층 — 같은 seed 경로); `src/mock/doedata.ts`·`src/mock/server.ts`·`src/mock/graphmock.ts`; 신규 `src/__tests__/doe_step_graph.test.tsx` | V-SG-8 |

- 순서: Core(`step_graph` 시그니처·`fixed_transfer.json` 형식 §3.3 고정) ∥ Backend(스키마 §4 고정, v0.17.2 rebase 후) ∥ Frontend(mock) → 통합 E2E(V-SG-7) → 실기(V-SG-R1).
- 공동 수정 금지: `stages.py`·`bead_graph.py`·`bead_select.py` = Core 단독, `packages/beadgraph/**` = 변경 없음(O-SG-3 이 다르게 정해지면 Core 단독), `schemas.py`·`config.py`·`config/*.yaml`·`worker/**` = Backend 단독, `types.ts` = Frontend(Backend 스키마 거울). `VERSION`·`CHANGELOG.md`·`docs/**` = 통합 담당.
