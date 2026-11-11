# 계약: ③ 다른 모델(STEP만)을 공통 비드 그래프 메시 경로로 — STEP → 쉘 메시(④ 사다리) → beadgraph 분류 → select 흐름 (STEP_GRAPH, v0.18.0)

- 상태: **구현 기준** (2026-11-11). D1·D2·D3 = 사용자 확정(아래, 변경 금지). O-SG-1~3 **해소**(사용자 2026-11-11 "18.0은 권장대로" + 이슈 #63 실서버 확인 2026-11-11T10:16Z — §10.1). 그 밖 결정은 코드·실측 조사로 구체화.
- 버전: **v0.18.0** (계약 작성 기준 main 6278842 = v0.17.1). 구현은 **v0.17.2·v0.17.3·v0.17.4 위로 rebase**(§11 — v0.17.4 = ④ 사다리 OCCFix 구 조각 수정 + 그래프 `max_elems` 600k, 진행 중). migration **불필요**(§5.4).
- 관계: `esl_beadgraph.md`(BEADGRAPH, v0.17.0 — 이하 "BG")·`esl_bead_auto.md`(AD, v0.16.2)·`esl_select_relax.md`(SR)·`esl_compare_mesh_options.md`(C2, v0.16.3 사다리)·`esl_bead_doe.md`(BD, ③ 원 계약)의 **변경 계약**. SR-D-44·BG-D-5(모핑 코어는 메시 출처와 무관)를 ③ 에 적용하고 BG-D-45(③ 보류)를 해제한다. 이 문서에 없는 규칙은 BG → AD → SR → BD 순서로 따르고, 충돌 시 이 문서가 우선. **기존 ③(`scenario: step`, paicad) 스터디는 이 문서의 영향을 받지 않는다**(§5.3).
- 근거 자료: 이슈 #63 현장 진단(2026-11-11, 스터디 da9dc714 — 아래 G1·G2), 이슈 #63 실서버 확인(2026-11-11T10:16Z 코멘트 — §0.2: A↔B 좌표계·추가 형상·STEP 위상·beadgraph 실부품), BG H6 픽스처 삼각형 분할 실측(§0.1, 이 계약 작성 중 측정), BG §7·V-BG-13 성능.
- ID 규칙: 결정 `SG-D-n`, 시험 `V-SG-n`, 리스크 `R-SG-n`, 열린 항목 `O-SG-n`.

### 사용자 확정 (2026-11-11, 변경 금지)
1. **D1 ③ 은 공통 분류기를 쓴다**: STEP → 쉘 메시(④ 메시 사다리 cad/freeform/tria 재사용, **같은 설정**) → beadgraph 분류 → ①② 와 같은 select 화면·흐름(세그먼트 트리, 자동 seed, 편집, derive, 미리보기, 기저 모핑 실행).
2. **D2 결과 = 메시(rad/inc)만**: 새 ③ 스터디는 최적 안 STEP/BREP 내보내기를 하지 않는다.
3. **D3 고정점**: A 모델 고정 노드(A Case fixed-scan → `prep/a_fixed`)를 B 메시로 기하 근접·투영으로 옮김(A·B 가 같은 좌표계일 때) / 아니면 자동 설정 없음 → 사용자가 표시(`fixed_user`, 기존) / 화면에서 항상 편집 가능. a_fixed 생성 방식·A↔B 정렬 유무는 조사(§0·§4).
4. **D3 세부 확정(2026-11-11, "18.0은 권장대로" — O-SG-1 해소)**: 1순위 = frame 일치(원점 ≤ 5 mm·축 ≤ 2°, 자동 판정)면 A 고정 노드 → B 최근접 노드 ≤ h(구멍 없는 RBE2 패드 포함), 2순위 = 정규화 frame + B 구멍 스냅 ≤ 10 mm, 둘 다 안 되면 자동 설정 없음 + info. 결과는 seed `fixed_user`(편집 가능) — SG-D-12~15. 근거 = 이슈 #63 [3]: da9dc714 A(Case part 21)·B(STEP) 원점·X 축 일치, Y/Z bbox 차이는 추가 형상(오프셋 아님).

## 0. 현황 (6278842, 근거 파일:행 · 실측)

| # | 항목 | 근거 | 현재 동작 | 이 계약에서 |
|---|---|---|---|---|
| G1 | ③ 비드 인식 | 이슈 #63 진단 7) | paicad extract 가 비드 6개(원형 엠보스)만 인식, **230건 제외**: 열린 비드 86·4링 아님 62·윗 필렛 없음 42·found 5 18·그 밖 22 | 메시 분류기 그래프(BG-D-1~14) — paicad 는 힌트만(BG §5.3) |
| G2 | ③ 안 형상 생성 | #63 진단 1)~2), `worker/esl_worker/doe_jobs.py` `_grid`:802·`_one_design`:964(update) | paicad `shell view grid`·`shell update` 가 B-rep 시트를 고침 → `occ_sheet.old_curve()` 가 **퇴화 모서리(degenerated edge, 3D 곡선 없음)**에도 3D 곡선을 요구해 셀 30개 중 29개 `GEOM_CAD_FAILED "edge E1927 has no 3D curve"`(시트에 같은 모서리 187개) | 새 ③ 은 grid·update 를 부르지 않음(기준 메시 기저 모핑) → 이 결함 경로 없음. paicad 결함 자체 수정은 paicad 쪽(범위 밖) |
| G3 | ③ 기준 메시 | `esl/doe/stages.py` `bd_mesh0`:284 | `scenario step` 만 gmsh(`bead_doe.mesh` 프로필, h = 입력 `mesh_size_mm`, 기본 A 메시 중앙값), 사다리 없음 | ④ 사다리(C2-D-9·18·26~31)를 같은 설정으로(SG-D-4) |
| G4 | ③ 안 메시·하중 | `stages._design_mesh`:541~560(TODO SR-D-44·BG-D-45), BD-D-3·4·10 | 안마다 BREP 재메시 → `design_target`(frame 고정, 안마다 auto 3-2-1) → 안마다 `entry_loads` 셀 매핑, 순위에 `noise_floor` | 기준 메시 1개를 기저 모핑(노드 ID 불변) → 하중·지지 1회(② 와 같음, SG-D-8·9) |
| G5 | A 고정점 | 워커 `_geom`:429~430(`_a_case` — ②③ 첫 ESL 의 A Case → `prep/a_assem_full/` 모델 사본 → `shell fixed-scan` → `prep/a_fixed/`), 코어 `_boundary`:371 | **경계 경고 전용**(BD-D-14 `BOUNDARY_FASTENER_FAR`): A 체결 클러스터 중심을 A frame (a,b) → 정규화 (ξ,η) → B frame (a,b)(`boundary.transfer`)로 옮겨 B 구멍 중심까지 거리 비교. ③ 모핑은 고정 없음(BD-D-11 `--fixed-dir ""`). ② select 도 A 고정 이전 안 함(D-0.16.2-MESHFIX, AD O-1) | frame 일치면 A 노드 → B 최근접 노드(≤ h), 아니면 정규화 이전 + B 구멍 스냅 → seed `fixed_user`(SG-D-12~15) |
| G6 | A↔B 정렬 | `esl/doe/boundary.py` `transfer`:36, `esl/doe/scenario.py` `template_base`:158(axis_ref = A ESL) | **③ 에는 A↔B 좌표 정렬 단계가 없다.** 유일한 대응은 두 frame(원점·e_xi·e_eta·L_xi·L_eta)의 정규화 좌표 대응. 같은 좌표계·같은 크기면 이 대응이 항등에 가까움(크기 규칙 ±5 % — BD-D-2) | frame 일치 자동 판정(part 21 기준 원점·주축) → 일치면 날 좌표 근접, 아니면 정규화 이전(SG-D-13). 실서버 da9dc714 = 일치(§0.2) |
| G7 | ③ 결과 받기 | BD-D-18, `esl/doe/export_mesh.py` `write`:26 | `ch_r.rad`·`ch_r.fem` + `sample.brep`·`sample.step` + `values.json` | 메시만(D2, SG-D-17) |
| G8 | ③ grid 실패 처리 | #63 진단 4)~6) | 셀 0개 성공인데 RESULT OK 로 등록, os.replace WinError 5, a_fixed 미전달 | **v0.17.2 핫픽스**(legacy ③ 전용, 병행 진행) — 이 계약은 손대지 않음 |
| G9 | ③ 평가 영역 | `scenario.template_base`:158(`tg.build_template` → `normalize.frame`:67 = **메시 전체** 면적 모멘트·주축·L_xi/L_eta), `entry_loads`:208(셀 매핑 = frame 전체 24×14), `boundary.hole_centers`:52(전체 자유 모서리 고리), `evaluate.evaluate`:36(전체 메시 C·umax·epsmax), `_sel_loads`:2419·`bead_graph.prep_graph`(전체 분류·seed), `mesh_gmsh` 검사:192(연결 성분 > 1 = `MESH_DISCONNECTED` 오류 — 성분 수만 봄) | **영역 제한이 없다**: B 메시 전체가 frame·크기 규칙·하중 셀 매핑·지지·구멍 후보·비드 후보·평가에 들어감. 추가 형상이 주 시트와 이어져 있으면(1 shell) 검사도 통과 | 평가 영역 = 주 시트(SG-D-19·20) |
| G10 | ④ 사다리 실 STEP | 이슈 #63 [3] | OCCFix 가 구 조각을 완전한 구로 만들어 사다리 실패 | **v0.17.4**(진행 중)에서 수정 + 그래프 `max_elems` 600k — 새 ③ BD_MESH0 는 v0.17.4 사다리 사용(SG-D-4) |

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

### 0.2 실서버 확인 (이슈 #63 코멘트 2026-11-11T10:16Z, 스터디 da9dc714)

| # | 항목 | 실측 | 이 계약에서 |
|---|---|---|---|
| E1 | A(Case part 21)↔B(STEP) 좌표계 | 원점 일치·X 축 일치. Y/Z bbox 차이 = **추가 형상**(오프셋 아님) | 고정점 1순위 = 날 좌표 근접(SG-D-13), O-SG-1 해소 |
| E2 | B STEP 메시 추가 형상 | B 메시 257 818 노드 vs A part 21 194 203 노드 → part 21 밖 **약 64k 노드**, z 16.7~29.6 mm 에 몰림 | 평가 영역 = 주 시트(SG-D-19·20, R-SG-7) |
| E3 | 실 STEP 위상 | 면 4 832(Plane 1028 / Cylinder 1504 / Cone 376 / Sphere 99 / Torus 640 / BSpline 1185), 퇴화 모서리 187, shell 1, 자유 모서리 0 | 추가 형상이 주 시트와 **한 shell 로 이어짐** → 최대 연결 성분만으로는 못 가름(SG-D-19 의 A bbox 규칙이 실효) |
| E4 | ④ 사다리 | 근본 원인 = OCCFix 가 구 조각(Sphere 99)을 완전한 구로 만듦 | 수정 + 그래프 `max_elems` 600k = **v0.17.4**(진행 중). BD_MESH0 = v0.17.4 사다리(SG-D-4) |
| E5 | beadgraph 1.0.0 실부품 분류 | 267 470 요소 · **16 s** · 396 MB · tier 12 · 세그먼트 111 · 접합 101 · 경고 0 | §7 600k 상한·300 s 여유 확인(실부품 선형 외삽 600k ≈ 36 s·≈ 0.9 GB), O-SG-3 = 1.0.0 그대로 |

## 1. 목적 · 범위

| 범위 (v0.18.0) | 비범위 |
|---|---|
| 새 ③ 스터디 = `select` + `inputs.select_base: "step"`(schema 2 고정) — v0.16.2 ② 전환(`select_base: "mesh"`)과 같은 방식 | 기존 `scenario: step` 스터디의 변경(실행·복제 그대로 — §5.3) |
| BD_MESH0: B STEP → ④ 사다리(cad → … → freeform → … → tria, `compare.mesh.mode`/`ladder`, ④ 프로필 h) → 기준 메시 + `template_base`(frame·3-2-1·크기 규칙) | 새 메시 방식·사다리 단계(④ 그대로) |
| BD_LOADS: 하중 셀 매핑 1회·경계 경고·beadgraph 분류·자동 seed — ② select 와 같은 함수 | beadgraph 패키지 변경(1.0.0 그대로 — O-SG-3) |
| A 고정점 이전(frame 일치 = 날 좌표 근접, 아니면 정규화 frame + B 구멍 스냅) → seed `fixed_user`(편집 가능) | ② select 의 A 고정 이전(AD O-1 그대로 — 필요하면 같은 함수로 다음 판) |
| 결과 받기 = 메시(`export_mesh`) + values | 최적 안 STEP/BREP 내보내기(D2) |
| 화면: ③ 라디오가 새 경로로, 입력 칸(STEP·인치·물성·메시 방식), 준비 요약(메시 방식·고정 이전·평가 영역) | 새 화면 |
| STEP 추가 형상: 전체 분류 + 평가·비교·비드 후보 = 주 시트 영역(SG-D-19·20) | 추가 형상 자동 삭제·형상 편집 |
| tria 사다리 메시 경고(O-SG-2)·600k 요소 한계·폴백 | paicad 퇴화 모서리 결함 수정(paicad 쪽) |

## 2. 흐름

```text
새 ③ 스터디 (scenario select, inputs.select_base "step", select_schema 2, bead_source auto|manual)
 ├ BD_INPUT  (INTERNAL) _sel_input: B STEP → input/step/<name>(sha 재확인), props·inch → prep/input.json {select_base "step"}
 ├ BD_MESH0  (INTERNAL) _sel_mesh0 = ④ _cmp_mesh_shape(row d000, h = ④ 프로필 size_mm, ccfg = compare_cfg, mode·ladder 스냅샷)
 │             → prep/mesh0/{mesh.npz, mesh.json(mesh_method, stage_times, …)} → sc.template_base(B = 템플릿, axis_ref = A ESL)
 │             → 평가 영역 step_graph.region(주 시트 — SG-D-19) → template_base 는 영역 요소로 frame·크기·3-2-1
             → prep/base_mesh.npz·base.json (scenario "select", region 마스크) · 사다리 끝이 tria = 경고 STEP_GRAPH_TRIA(SG-D-6)
 ├ BD_GEOM   (LOCAL, 워커) _geom_select step plan = [a_fixed(A Case 있으면 — ②③ 그대로)] + (auto) extract0 → extract(힌트)
 │             (B 조립 없음 → fixed-scan 없음, grid·update 없음)
 ├ BD_LOADS  (INTERNAL) _sel_loads:
 │             하중 sc.entry_loads(t, …) 1회(S2 셀 매핑 + 평형 보정, 영역 노드만) → prep/loads.npz ← ② select 와 같은 함수(SG-D-8·20)
 │             지지 = t.supports(template_base auto 3-2-1) 1회                          ← ② 와 같음(SG-D-9)
 │             경계 경고 _boundary(B 후보 = B 구멍만) → prep/boundary.json                  ← ③ 그대로
 │             고정 이전 step_graph.fixed_transfer(a_fixed, frame 판정 → xyz_nearest | ab_hole_snap | none) → prep/select/fixed_transfer.json (SG-D-12~15)
 │             분류 bead_graph.prep_graph(mesh 전체, fixed = 이전 노드, cfg + step 상한) → graph.json·labels·graph.bin·w_clamp.json
             영역 밖 세그먼트·섬 = 후보 제외 표지(SG-D-20)
 │             seed  auto_selection.json(auto = 영역 안 그래프 seed + fixed_user, manual = 빈 비드 + fixed_user)
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
| SG-D-4 | **메시 = ④ 사다리, 같은 설정**(D1): h = `sc.compare_profile(cfg)["size_mm"]`(기본 3 mm = 낙하 메시 기준, `mg.check_h`), gmsh 설정 = `sc.compare_cfg(cfg)`, 모드·사다리 = ④ `_cmp_mode` 규칙(스냅샷 `doe.mesh_mode`·`doe.mesh_ladder` → 없으면 설정), 단계 시간 몫·예산·시도 폴더·`keep_tries`·면 실패 판정·단계별 문구 = C2-D-18~31 그대로. 형상 행 id = `d000`, 폴더 = `prep/mesh0/`(시도 = `prep/mesh0/try_<n>/`). ③ 의 `bead_doe.mesh` 프로필·`mesh_size_mm` 은 새 ③ 에서 쓰지 않음. **사다리 = v0.17.4 수정판**(OCCFix 구 조각 → 완전한 구 결함 수정 — §0.2 E4) — v0.17.4 이전 사다리로는 실 STEP(da9dc714)이 실패하므로 V-SG-R1 은 v0.17.4 rebase 뒤에만 의미 | 사용자 D1 "같은 설정", ④ 실서버 성공률(v0.16.3), 이슈 #63 [3] |
| SG-D-5 | **④ 사다리 함수 재사용 방식**: `_cmp_mesh_shape`·`_cmp_ladder`·`_cmp_mesh_one`·`_cmp_defeature_stage`·`_cmp_remesh_one` 에 키워드 `mesh_dir=None`(None = 지금 `_cmp_mesh_dir(c, did)`)만 추가. ④ 호출은 인자 없이 그대로 → **④ 바이트 불변**(V-SG-9). 사다리 전부 실패 = 작업 실패 `MESH_FAILED`(문구 `MESH_LADDER_FAILED` 그대로 — 기준 d000 실패 규칙 C2-D-9), `MESH_TOO_LARGE`·`GMSH_UNAVAILABLE` 은 ④ 와 같음 | 코드 1벌 |
| SG-D-6 | **tria 로 끝난 메시 = 경고, 막지 않음**(O-SG-2 확정 — `tria_policy: warn` 기본): `mesh_method` 가 tria(또는 삼각형 비율 > `select.step_graph.tria_warn_frac` 0.5)이면 준비 경고 `STEP_GRAPH_TRIA{mesh_method, tri_frac}`("삼각형 메시 — 걸친 보스가 있는 채널의 D·W 안은 바깥 이동으로 실패할 수 있음") + ④ 경고 `MESH_TRIA_FALLBACK` 그대로. 분류·모핑은 진행, 안 판정은 BG-D-34·뒤집힘이 그대로 막음(§0.1). `tria_policy: block` 이면 준비 실패 `STEP_GRAPH_TRIA_BLOCKED` | §0.1: 분류 정상, 모핑 실패는 판정이 잡음 — 막으면 사다리가 살린 형상을 다시 버림 |
| SG-D-7 | **기준 메시 = template_base**(③ BD_MESH0 와 같은 함수): frame = B 메시 **평가 영역 요소**(SG-D-19 — `region.mode: all` 이면 전체, 지금 동작)(`axis_ref` = 첫 ESL), 법선 정렬, 자동 3-2-1, 크기 규칙 B = 템플릿(±5 %, `SIZE_MISMATCH`), `save_base(scenario "select", extra {props, h, mesh_method, gmsh_version})`. 노드 ID = 사다리 메시 번호(1부터) | 같은 함수 |

### 3.2 하중 · 지지 · 평가 일관성

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-8 | **하중 = ② select 와 같은 함수 1회**: `stages._sel_loads` → `sc.entry_loads(t, ents, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"], (grid nx, ny))` — `t.scenario == "S2"` 이므로 ESL 마다 `tg.entry_load(t, None, e.summary_for_mapping(), mapping_opts)` = **`esl.library.mapping.to_target`(24×14 셀 합력·합모멘트) + 평형 보정**, frame = B 기준 메시. 결과 `prep/loads.npz`(B 노드 ID) → **모든 안에 같은 노드 하중**(모핑은 ID 불변). 셀당 노드 경고 그대로 | D-0.16.2-MESHMAP(AD-D-15·18·19)과 같은 경로 — 매핑 잡음 0 |
| SG-D-9 | **지지 = template_base 의 `auto_supports` 1회**(B 기준 메시), 모든 안 같은 node_id(② BD-D-4). `support_check` rank < 6 = 준비 실패 `SUPPORT_DEGENERATE`(기존) | ② 와 같음 |
| SG-D-10 | **평가 일관성**: d000 = 사다리 기준 메시 + 위 하중·지지(`_design_mesh` BASELINE 분기 그대로), 안 = 같은 메시 + 기저 모핑 좌표(`_design_mesh` select 분기 그대로 — 코드 변경 없음), 해석 = `ev.evaluate` 같은 해석기 설정, 점수 = 안 최악 C / d000 최악 C(`rank` 그대로). 안 메시가 d000 과 위상이 같아 **메시 잡음 없음** → `noise_floor` 계산·"잡음 이내" 표시 없음(② 와 같음). `keep_mesh`(design.npz 에 메시) = 아니오(select 와 같음) | 같은 메시에서 형상만 다름 |
| SG-D-11 | **기존 ③ 과의 비교**: 같은 B STEP 이라도 새 ③ d000 은 기존 ③ d000 과 **바이트·수치가 같지 않다**(메시 프로필 ④ 3 mm vs ③ `mesh_size_mm`, 안 하중 재매핑 없음). 같은 스터디 안 비교만 보장. 보고서 방법 절에 "③ 그래프(기준 메시 기저 모핑, 메시 방식 <method>)" 1줄 | 사용자에게 다른 방식임을 드러냄 |

### 3.3 고정점 (D3 — 확정 2026-11-11, O-SG-1 해소)

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-12 | **A 고정점 출처 = 지금의 `prep/a_fixed/`**(워커 `_a_case` — 첫 ESL 의 A Case 입력 → `prep/a_assem_full/` 모델 사본 → `shell fixed-scan --parts <A part>` → `fixed_scan.json`·노드 표 {node_id, xyz, cluster, kind_mask}). A Case 없음·fixed-scan 실패 = 이전 없음 + 정보 `FIXED_XFER_NONE{reason: A_CASE_MISSING\|A_SCAN_FAILED}`(준비 READY) | 새 paicad 호출 없음 |
| SG-D-13 | **이전 규칙 = 3단 (순서 고정)**. **(0) frame 일치 판정**(자동): A frame = A part(첫 ESL 의 A part — da9dc714 = part 21) 노드의 bbox 중심·면적 모멘트 주축, B frame = B 기준 메시 **평가 영역**(SG-D-19)의 같은 값. 일치 = 원점 거리 ≤ `fixed_transfer.origin_tol_mm` 5 mm **그리고** 세 축 각도 모두 ≤ `axis_tol_deg` 2°(축 부호 무시) — 날 좌표(전역 좌표계) 그대로 비교, 변환 없음. 판정 값은 `frame_check{d_origin_mm, angle_deg[3], ok}` 로 기록. **(1) 1순위 `xyz_nearest`**(일치일 때 — 옵션 (c)): A 고정 노드 xyz(`prep/a_fixed` 클러스터 노드 전부) 마다 B 메시 최근접 노드(KD-tree, 평가 영역 안)를 찾아 거리 ≤ `tol_mm`(null = 기준 메시 h)이면 그 노드를 이전(같은 B 노드 = 1회). 구멍 없는 고정(RBE2 패드·면 접촉)도 옮김. 클러스터 노드가 하나도 안 맞으면 그 클러스터 = `FIXED_XFER_UNMATCHED{label, d_mm(최소)}`. **(2) 2순위 `ab_hole_snap`**(불일치일 때): A 클러스터 중심(`pio.fixed_points`) → `project_ab(frame_A)` → `boundary.transfer(frame_A, frame_B)` → B 평면 (a,b), B 구멍 = `boundary.hole_centers`(평가 영역, `keepout.hole_min_perimeter_mm`, 자유 모서리 고리)와 평면 거리 d ≤ `snap_mm`(null = `boundary.fastener_warn_mm` 10)인 가장 가까운 구멍 1개에 스냅(동률 = 작은 구멍 번호, 한 구멍에 여러 A 클러스터 = 1회) → 구멍 **둘레 노드** = 이전 노드. 스냅 실패 = `FIXED_XFER_UNMATCHED{label, d_mm}`(BD-D-14 `BOUNDARY_FASTENER_FAR` 와 같은 대상). **(3) 최후**: 두 방법 모두 이전 노드 0개 = 자동 설정 없음 + 정보 `FIXED_XFER_NONE{reason: NO_MATCH}`. `fixed_transfer.mode` = `auto`(위 순서, 기본) \| `xyz` \| `hole` 로 고정 가능 | 이슈 #63 [3]: da9dc714 A·B 원점·X 축 일치, Y/Z bbox 차이 = 추가 형상(§0.2 E1) → 실 사례는 1순위. B frame 을 평가 영역으로 잡아야 추가 형상이 판정을 흔들지 않음. 구멍 없는 곳에는 2순위에서 고정 노드를 만들지 않음 |
| SG-D-14 | **이전 결과의 쓰임**: (a) 분류 입력 `fixed`(BG-D-5 — 구멍·섬 `fixed` 표지, graph sha 에 포함), (b) **seed `fixed_user`** = ElemSet: `ab_hole_snap` = 각 이전 구멍 고리 노드를 2개 이상 가진 요소(첫 요소 고리), `xyz_nearest` = 이전 노드를 2개 이상 가진 요소 ∪ (이전 노드 1개뿐인 클러스터의 그 노드를 가진 요소) → 화면 고정 층에 미리 칠해짐 → **추가·지우기 모두 기존 칠하기 도구로**(D3 "항상 편집"). B fixed-scan 이 없으므로 `fixed_scan` = 빈 집합(derive·manifest `fixed.source = "a_transfer"`, `scan_n` 0, `xfer_n`, `xfer_method`) — 즉 이전 고정은 **사용자 선택의 일부**이고 저장 후에는 선택 sha 에 들어감 | 고정 출처를 편집 불가한 scan 으로 두면 D3 위반 |
| SG-D-15 | **파일** `prep/select/fixed_transfer.json` = `{schema "esl/doe_fixed_transfer/2", method "xyz_nearest"\|"ab_hole_snap"\|"none", mode, frame_check{d_origin_mm, angle_deg[3], ok, origin_tol_mm, axis_tol_deg}, tol_mm, snap_mm, frame_a_sha, frame_b_sha, matches[{a_label, kind, n_a, n_nodes, d_max_mm, hole\|null, a_ab[2]\|null, b_ab[2]\|null, d_mm\|null}], unmatched[{a_label, kind, d_mm\|null}], node_id[], elems(ElemSet)}`(결정적 바이트 — 키 정렬·1e-3 반올림). `fixed_transfer.enabled: false` = 파일 없음 + `FIXED_XFER_NONE{reason: DISABLED}` | 화면 요약·시험 근거 |

### 3.3a 추가 형상 · 평가 영역 (이슈 #63 [3] E2 — 사용자 2026-11-11 "권장대로")

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-19 | **평가 영역 = 주 시트, 분류는 전체**. BD_MESH0 에서 B 기준 메시 요소 마스크 `region` 을 정해 `base.json`·`prep/input.json` 에 기록. `select.step_graph.region.mode`: **`auto`(기본)** = A part bbox(첫 ESL A part 노드, 날 좌표, 각 변 `pad_mm` null = 2h 만큼 넓힘)와 **겹치는 요소**(중심이 안)가 있으면 그 요소들의 연결 성분 중 최대 성분, A part 정보가 없으면(A Case 없음) 메시 **최대 연결 성분**(면적 기준) \| `a_bbox` \| `largest` \| `all`(= 제한 없음, 지금 동작). 영역 = 전체이면 표시 없음, 아니면 정보 `STEP_GRAPH_REGION{n_in, n_out, out_bbox, mode}`("주 시트 밖 형상 n 요소 — 평가·비드 후보에서 제외"). 영역 요소 < 전체의 `min_frac` 0.5 = 경고 `STEP_GRAPH_REGION_SMALL`(계속 진행) | da9dc714: B 257 818 노드 중 약 64k 가 part 21 밖(z 16.7~29.6 mm), shell 1 개로 이어져 **최대 연결 성분 규칙만으로는 = 전체**(E3) → A bbox 규칙이 실효. 규칙 1개·설정 1묶음 |
| SG-D-20 | **영역의 쓰임(단순 — 해석 메시는 전체)**: (a) frame·크기 규칙·자동 3-2-1 = 영역 요소·노드로(`template_base(…, region=mask)` — 마스크 없으면 바이트 불변), (b) 하중 셀 매핑 대상 노드 = 영역 노드(영역 밖 하중 0), (c) 구멍 후보(`hole_centers`)·고정 이전 대상 = 영역, (d) 분류 `prep_graph` = **메시 전체**(위상·벽 소유가 끊기지 않게), 그 뒤 세그먼트·섬·랜스 중 요소의 50 % 초과가 영역 밖인 것 = `out_of_region` 표지 → 자동 seed·트리 후보에서 제외(화면은 회색, 직접 칠하기는 허용), (e) 해석 = 전체 메시(추가 형상의 강성 포함 — 물리적), C = F·u 는 하중이 영역에만 있어 자동으로 영역 값, `umax`·`epsmax` = 영역 노드·요소만(`evaluate(…, region=mask)` 선택 인자 — 없으면 바이트 불변), (f) 받기 `ch_r.rad` = 전체 메시. ①② 와 ④ 는 `region` 을 넘기지 않음 → 바이트 불변(V-SG-9) | 비교·평가는 A 와 같은 부품끼리, 추가 형상은 정보로만 |

### 3.4 분류 · 선택 · 결과

| ID | 결정 | 근거 |
|---|---|---|
| SG-D-16 | **분류·선택·모핑·판정 = BG 그대로**: `_sel_graph`(prep_graph) → `_sel_w_clamp` → `_sel_auto_v2`(seed) → derive_v2·basis_v2·design_checks_v2. 다른 점은 (i) 요소 상한 = max(`select.graph.limits.max_elems`, `select.step_graph.max_elems` 600 000)(v0.17.4 가 `select.graph.limits.max_elems` 를 600k 로 올리므로 rebase 뒤 두 값이 같음 — step 키는 독립 조정용으로 유지), 시간 상한 = max(`limits.timeout_s`, `step_graph.timeout_s` 300)(§7), (ii) seed 에 `fixed_user`(SG-D-14)·영역 밖 후보 제외(SG-D-20), (iii) **manual 도 seed 파일을 씀**(빈 비드 + fixed_user, `source: "fixed_transfer"`) — `GET …/select/auto` 는 step 기준이면 bead_source 와 무관하게 돌려줌. `GRAPH_FAILED` = BG-D-40 그대로(준비 READY, `src: elems` 비드로 계속) | ①② 와 같은 화면·같은 판정 |
| SG-D-17 | **받기 = 메시만**(D2): 최적·상위 k 안 = `esl.doe.export_mesh.write(dir, mesh(x = 기저 모핑 좌표), part_title = STEP 파일 이름 줄기)` → `ch_r.rad`(/NODE·/SHELL·/SH3N·/PART·/PROP·/MAT, ID = 기준 메시 번호) + `ch_r.fem` + `values.json` + select 주석(`_sel_fixed_comment` 그대로). `sample.brep`·`sample.step` 없음. `_sel_best` 에 step 분기 1개(①=Case include 사본, ②=B rad 사본, ③=export_mesh) | 기준 메시에 원 rad 가 없음 — ③ 기존 export 함수 재사용 |
| SG-D-18 | **paicad 의 역할**(새 ③): auto + STEP 이면 `extract0 → extract` **힌트만**(`AUTO_SLOPE_DIFF`, BG §5.3 — tag·grid·update 없음). 힌트 실패(#63 같은 B-rep 결함 포함) = 정보 `AUTO_HINT_UNAVAILABLE`. paicad 없음 = 힌트 없이 진행 — **새 ③ 은 paicad 가 없어도 동작**(`scenarios.select_step` 은 gmsh·select 만 봄). A 고정점은 paicad fixed-scan(G5)이라 paicad 없으면 `FIXED_XFER_NONE{A_SCAN_FAILED}` | D1, paicad 는 힌트·legacy 용으로 설치 유지 |

## 4. 데이터 · API 변경 (최소)

### 4.1 저장 자료
- `studies.inputs`(JSONB) += `select_base: "step"`(값 추가), 기존 키 재사용: `select_schema: 2`, `step{file_name, sha256}`, `props`, `inch`, `mesh_mode`, `bead_source`. 스냅샷 `doe` += `select_base: "step"`, `mesh_mode`, `mesh_ladder`(④ 와 같은 이름·의미).
- `prep/input.json` += `select_base: "step"`, `mesh{method, n_nodes, n_elems, tri_frac, stage_times}`, `fixed{source: "a_transfer"|"none", n, xfer: {method, matched, unmatched, frame_ok}}`, `region{mode, n_in, n_out}`. `base_mesh.npz` += `region`(bool, 요소별 — 영역 = 전체이면 키 없음).
- 새 파일: `prep/mesh0/**`(④ 형식 그대로), `prep/select/fixed_transfer.json`. 그 밖 `prep/select/*` 는 BG 그대로.
- 이어하기 해시(`input_sha256`): step 기준 = (STEP sha, props, inch, 메시 모드·사다리·④ 프로필 해시 — C2-D-15 규칙 그대로, `compare_profile` sha, region 마스크 sha). ①② 해시 식 불변.

### 4.2 API (`/esl/api`)
```
DoeCheckIn/DoeStudyIn(select)   select_base: "case"|"mesh"|"step"  (+ SG-D-3 검사)
                                 mesh_mode?·mesh_refine? = compare 또는 select_base step 에서만(그 밖 422 MESH_MODE_COMPARE_ONLY 그대로)
DoeCheckOut(select, step)        += step{file_name, sha256}, props_default, size, mesh_mode, remesh_available (④ 와 같은 필드)
GET  /doe/settings               scenarios += select_step (= select 가능 ∧ gmsh ready; paicad 무관), select.step_graph{tria_policy}
GET  /doe/studies/{sid}/select/auto   select_base step = bead_source 무관하게 seed(SG-D-16), 없으면 404 그대로
DoeStudyOut.prep                 += mesh{method, tri_frac, stage_times}, fixed{source, n, xfer{method, matched, unmatched, frame_ok}}, region{mode, n_in, n_out}
POST /doe/studies (scenario step) 계속 받음(스크립트 호환 — AD-D-23 과 같음), 화면만 숨김
```
- 새 오류·경고 코드(문구 원본 `resources/doe_messages.json`): `STEP_GRAPH_TRIA`(경고)·`STEP_GRAPH_TRIA_BLOCKED`(준비 실패 — block 정책일 때만)·`FIXED_XFER_NONE{reason}`(info)·`FIXED_XFER_UNMATCHED{label, d_mm}`(info)·`STEP_GRAPH_REGION{n_in, n_out, out_bbox, mode}`(info)·`STEP_GRAPH_REGION_SMALL`(경고). 그 밖은 BG·C2·BD 코드 그대로.

### 4.3 설정 키 (`DEFAULTS["select"]["step_graph"]` = pydantic `BeadDoeSelectStepGraphCfg` = `config/*.example.yaml` 2개 거울)
```yaml
bead_doe:
  select:
    step_graph:                     # v0.18.0 STEP_GRAPH — select_base step 스터디만 읽음
      max_elems: 600000             # 분류 요소 상한(= ④ refine.max_elems 기본) — §7
      timeout_s: 300                # 분류 시간 상한
      tria_warn_frac: 0.5           # SG-D-6
      tria_policy: warn             # warn | block (O-SG-2 확정 = warn)
      fixed_transfer:               # SG-D-13 (O-SG-1 확정)
        enabled: true
        mode: auto                  # auto(xyz → hole → none) | xyz | hole
        origin_tol_mm: 5            # frame 일치: 원점
        axis_tol_deg: 2             # frame 일치: 축
        tol_mm: null                # xyz_nearest 거리, null = 기준 메시 h
        snap_mm: null               # ab_hole_snap, null = boundary.fastener_warn_mm
      region:                       # SG-D-19·20 (추가 형상)
        mode: auto                  # auto | a_bbox | largest | all
        pad_mm: null                # a_bbox 여유, null = 2h
        min_frac: 0.5               # 영역 비율 < 이 값 = STEP_GRAPH_REGION_SMALL
```
- 해시: `select_hash_view` 는 `step_graph` 를 **select_base step 스터디에서만, 기본값이 아닐 때만** 넣음(`HASH_NEW_KEYS_V0180 = ("step_graph",)`) → ①② schema 1·2 `_cfg_hash`·`_sel_cfg_sha` = rebase 기준판(v0.17.4)과 같음(V-SG-10).
- 검사: `max_elems` 1..2e6, `timeout_s` gt 0, `tria_warn_frac` (0, 1], `tria_policy` ∈ {warn, block}, `fixed_transfer.mode` ∈ {auto, xyz, hole}, `origin_tol_mm`·`axis_tol_deg` gt 0, `tol_mm`·`snap_mm`·`region.pad_mm` null 또는 gt 0, `region.mode` ∈ {auto, a_bbox, largest, all}, `min_frac` (0, 1].

## 5. 이전 · 호환

### 5.1 새 ③
- 화면 ③ 라디오 = `radioRequest("step") → {scenario: "select", selectBase: "step"}`. 새 ③ 스터디는 `scenario: step` 을 만들지 않는다.

### 5.2 판 · 바이트
- `bead_select.ALGO`·`RULES`(3)·`GRAPH_ALGO`(1)·`graph_rules`(1)·beadgraph 1.0.0(RULES 1·MORPH_RULES 1) **그대로**. 새 ③ 은 같은 판을 기록.
- ①② select(schema 1·2)·④ compare: 준비·기저·판정·결과·해시 바이트 불변(V-SG-9·10 — 기준 = rebase 뒤 v0.17.4).

### 5.3 기존 ③ (`scenario: step`, paicad)
- 그대로 실행·복제(복제본도 `step`): 워커 `_geom`·`_grid`·`_one_design`(update) 경로, 코어 `bd_mesh0`·`_design_mesh` ③ 분기·`noise_floor`·BREP/STEP 내보내기 불변. **v0.17.2 핫픽스 결과가 기준**(grid 전부 실패 = 단계 실패, a_fixed 전달 등). 화면은 기존 ③ 스터디를 "③ 다른 모델(STEP만) — 이전 방식(paicad)"으로 표시(읽기·실행·복제 버튼 그대로).
- paicad 는 계속 설치·점검(`scenarios.step` 은 지금 규칙 그대로 — legacy 실행용). `_design_mesh` 의 TODO(SR-D-44·BG-D-45) 줄은 "새 ③ = select_base step 으로 해소" 주석으로 바꿈(동작 변경 없음).

### 5.4 migration
- **없음**: `inputs`·스냅샷은 JSONB, 시나리오 값·CHECK 불변, 새 테이블 없음. `VERSION` 0.18.0·`CHANGELOG.md`·openapi info.version 만.

## 6. 화면 (새 화면 없음, 2560×1440 기준·1920×1080 잘림 없음)
- **새 스터디 라디오**: ③ "다른 모델(STEP만)" → select step. 하위 "비드" auto/manual(①② 와 같은 하위 라디오). 막힘 사유 = `scenarios.select_step`(gmsh 없음 → `GMSH_UNAVAILABLE` 문구).
- **입력**(`DoeInputs`): STEP 칸(필수), 인치, 쉘 물성(t·E·ν — ③ 그대로), 메시 방식(④ 의 고급 설정 칸 재사용 — 기본 접힘). "평균 요소 크기" 칸 없음(h = ④ 프로필, 요약에 "요소 크기 3 mm(④ 설정)" 표시).
- **준비 요약**: 메시 방식 칩(cad / 폴백 freeform / 삼각형 폴백) + 단계별 시간(④ 문구), `STEP_GRAPH_TRIA` 경고, 고정 이전 1줄 "A 고정 n개 중 m개를 옮김(좌표 일치 — 최근접 노드 | 좌표 불일치 — B 구멍 스냅) — 고정 층에서 수정"(+ 못 옮긴 목록), 평가 영역 1줄 "주 시트 밖 형상 n 요소 — 평가·비드 후보 제외" — 모두 v0.17.1 접힘 규칙(D-0.17.1-FOLD).
- **평면도**(`BoundaryPlan`): 기존 A 체결점 → B 대응 선 위에 이전된 구멍을 고정 색으로 표시(스냅 안 된 것은 지금 경고 표시 그대로).
- **선택 카드**: BeadSelectCard / 트리 / 3D = BG §6.2 그대로. 고정 층이 seed `fixed_user` 로 미리 칠해짐(되돌리기·초기화 = seed 로 — AD-D-4). 영역 밖 요소·세그먼트 = 회색(트리에 "영역 밖" 묶음, 접힘).
- **결과 받기**: 링크 이름 "메시 ch_r.rad"(③ 과 같은 문구), STEP/BREP 링크 없음.

## 7. 성능 한계 · 폴백

| 항목 | 한계 | 근거 · 장치 |
|---|---|---|
| 메시 요소 | 사다리 `refine.max_elems` 600 000(④ 그대로), cad 시도 `MESH_TOO_LARGE` = 폴백 없음(C2-D-9) | ④ |
| 분류 classify | 600 000 요소 ≤ 300 s·RSS ≤ 1.5 GB | 실측(2 코어): 104k 4 s·231 MB, 205k(삼각) 5 s, 418k 12 s·706 MB → 600k ≈ 17 s·≈ 1.0 GB. 서버 실측 220k 20~48 s(사용자) → 600k 선형 외삽 55~130 s — 180 s 기본은 빠듯해 step 만 300 s. **실부품(이슈 #63 [3], da9dc714 B STEP): 267 470 요소 16 s·396 MB·tier 12·세그먼트 111·접합 101·경고 0**(§0.2 E5) → 600k ≈ 36 s·≈ 0.9 GB |
| 그래프 요소 상한(①②) | `select.graph.limits.max_elems` 250k → **600k = v0.17.4** | 실부품 267k 가 250k 를 넘음 — v0.17.4 rebase 전제 |
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
| V-SG-4 | **고정 이전**: (a) 같은 좌표계: A = H6 픽스처(+ `fixed`), B = H6 STEP 메시 → `frame_check.ok`, method `xyz_nearest`, A 고정 노드 전부 이전(거리 ≤ h), 고정 구멍 78 전부 포함. (a') A 에 구멍 없는 RBE2 패드 고정 1개 추가 → 1순위에서 이전됨(2순위면 UNMATCHED). (a'') B 에 A bbox 밖 추가 형상(평면에서 z +20 mm 리브)을 붙여도 frame 판정 ok(평가 영역 기준). (b) B 를 1.03 배·회전 5°·평행 이동 10 mm → `frame_check.ok = false` → method `ab_hole_snap`, 같은 매칭 ≥ 95 %. (c) (b) 에서 B 에 없는 구멍 1개 → `FIXED_XFER_UNMATCHED` + `BOUNDARY_FASTENER_FAR` 같은 라벨. (d) A Case 없음 → `FIXED_XFER_NONE{A_CASE_MISSING}`, seed fixed_user 빈 집합. (d') 두 방법 모두 0개 → `FIXED_XFER_NONE{NO_MATCH}`. (e) 사용자가 seed 고정을 지우고 저장 → 기저 hold 없음(ψ = 1), 다시 칠하면 hold. (f) 결정적 바이트 2회 동일. (g) `mode: hole` 강제 → (a) 에서도 2순위 | `tests/doe/test_step_graph_fixed.py` |
| V-SG-4b | **평가 영역**: H6 STEP + 주 시트와 이어진 추가 형상(z +17~30 mm, 요소 ≈ 25 %) → (a) `auto` 영역 = 주 시트(추가 형상 요소 0 % 포함), `largest` = 전체(이어져 있으므로), `all` = 전체, (b) frame·L_xi/L_eta·3-2-1 = 추가 형상 없는 H6 STEP 과 ± 1e-9(영역 기준), (c) 하중 영역 밖 노드 0, (d) 추가 형상 세그먼트 `out_of_region` → 자동 seed 제외, (e) 분류 세그먼트·접합 수(영역 안) = V-SG-1, (f) `STEP_GRAPH_REGION` info, 영역 < 50 % = `STEP_GRAPH_REGION_SMALL`, (g) `region` 인자 없음 = `template_base`·`evaluate` 바이트 불변 | `tests/doe/test_step_graph_region.py` |
| V-SG-5 | **하중·지지·평가 일관성**: step 기준 하중 = 같은 메시를 ② select(`select_base mesh`, rad 왕복)로 넣은 하중과 노드별 ± 1e-12, 지지 node_id 동일, d000 결과 동일. 모든 안의 loads.npz sha = d000. `noise_floor` 키 없음 | 같은 파일 |
| V-SG-6 | **API**: select_base step 검사(STEP 필수·props·금지 칸 422·schema 1 422·mesh_mode 허용), settings `select_step`(paicad 없음 + gmsh 있음 = true), `GET select/auto` manual seed, `scenario: step` 생성 계속 허용, 복제(step 기준·legacy step 각각), pydantic `step_graph` 검사 | `backend/tests/test_doe_step_graph_api.py` |
| V-SG-7 | **워커 E2E**: H5 STEP, A Case 있음(paicad 대역 — 기존 워커 시험 방식) → BD_INPUT·BD_MESH0(사다리)·BD_GEOM(a_fixed + 힌트, fixed·grid·update 호출 없음)·BD_LOADS(그래프·seed·이전) → seed 저장 → 미리보기 → 실행 → 순위·보고서·받기(ch_r.rad·ch_r.fem·values.json, sample.step/brep 없음). `GRAPH_FAILED` 주입 → elems 비드로 실행. paicad 없음 → 힌트·이전 없이 실행 | `worker/tests/test_doe_step_graph_jobs.py` |
| V-SG-8 | **화면**: ③ 라디오 → 요청 본문(select + step), 입력 칸(요소 크기 칸 없음·메시 방식 칸), 준비 요약(방식 칩·TRIA 경고·이전 1줄 접힘), 고정 층 seed, legacy ③ 표시, 받기 링크, 2560·1920 잘림 없음, 600k graph.bin 디코드 ≤ 500 ms | `frontend/src/__tests__/doe_step_graph.test.tsx`, mock |
| V-SG-9 | **④·①·② 바이트 불변**(기준 = v0.17.4 rebase 뒤): `regress.py`(작업 폴더 — V-C2-30 과 같은 방식) ④(mode 없음·cad·auto, 형상 h5·h3 × step·case) mesh·loads·순위 바이트 동일(mesh_dir 인자 리팩터), ① case·② mesh select(schema 1·2) 준비·기저·판정·결과 바이트 동일, V-BG-* 전부 통과 | `tests/doe/*`, 작업 폴더 regress |
| V-SG-10 | **해시**: 기본 설정에서 ①② `_cfg_hash`·`_sel_cfg_sha` = v0.17.4 상수, `step_graph` 를 바꿔도 ①② 해시 불변, step 기준 스터디만 변함 | `tests/doe/test_bead_graph_cfg.py` 추가 |
| V-SG-11 | **legacy ③ 회귀**: 기존 `scenario: step` 스터디(픽스처) 준비·grid·안 평가·받기 = v0.17.2 결과와 바이트 동일, 복제본 `step` | `worker/tests/test_doe_jobs*.py`, `tests/doe/test_bead_doe*.py` |
| V-SG-12 | **성능(slow, perf)**: 600k 요소(H6 중점 분할 + 타일) classify ≤ 300 s·RSS ≤ 1.5 GB, derive ≤ 8 s, 600 001 → `GRAPH_FAILED{TOO_LARGE}` + elems 비드 경로 | `tests/doe/test_step_graph_perf.py` |
| V-SG-R1 | **실기**(v0.17.4 사다리 필수): 이슈 #63 실제 B STEP(da9dc714 입력) — 메시 방식, 세그먼트·접합 수(beadgraph 단독 실측 111·101 — §0.2 E5 와 비교), paicad 가 버린 230건 중 그래프가 세그먼트로 잡은 수, `frame_check.ok`(기대 = 참 — E1)·method `xyz_nearest`·이전 고정 노드 수, 평가 영역(기대: 밖 ≈ 64k 노드, z 16.7~29.6 mm), 자동 seed 안 판정(뒤집힘·바깥 0) | `docs/manual/bead_doe_check.md` 절 추가 |

## 9. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-SG-1 | tria 메시에서 걸친 보스 채널 D·W 안이 바깥 이동으로 실패(§0.1) | `STEP_GRAPH_TRIA` 경고, 판정이 막음(조용한 오류 없음), 그 비드를 섬 전환·`src: elems` 로 우회, 근본 수정 = beadgraph 1.1.0(O-SG-3 확정) |
| R-SG-2 | (2순위) 정규화 이전이 비대칭·크기 다른 B 에서 엉뚱한 구멍에 스냅 / (1순위) frame 판정 경계 근처(원점 4~6 mm)에서 h 안 엉뚱한 노드 | 1순위는 frame 일치일 때만(원점 5 mm·축 2°), 2순위 스냅 반경 = 경계 경고 10 mm, 판정 값·방법을 요약에 표시, 평면도 표시, seed 라 사용자가 지움, `mode` 로 강제 가능 |
| R-SG-3 | 사다리 cad 메시(④ 프로필 3 mm, OCC 작은 형상 정리·defeature)가 작은 비드·엠보스를 지움 → 분류 대상이 사라짐 | ④ 충실도 경고(`MESH_DEFEATURED`·`MESH_FREEFORM`) 준비 요약 노출, V-SG-R1 에서 확인 |
| R-SG-4 | 600k 근처에서 분류·기저·화면이 느림 | 상한·시간 상한·폴백(§7), 요소 크기 안내 |
| R-SG-5 | 새 ③ 과 기존 ③ 결과가 같은 STEP 에서 다름(SG-D-11) | 보고서 방법 줄, legacy 표시 |
| R-SG-6 | v0.17.2·v0.17.3·v0.17.4 와 파일 충돌(워커·`stages.py` 사다리·그래프 상한) | §11 rebase 규칙, Backend·Core 가 v0.17.4 병합 뒤 착수 |
| R-SG-7 | **③ STEP 의 추가 형상**(da9dc714: part 21 밖 ≈ 64k 노드, z 16.7~29.6 mm, 주 시트와 한 shell)이 frame·크기 규칙·하중 셀 매핑·지지·구멍 후보·비드 후보·umax/epsmax 를 오염 — 지금 ③ 경로에는 영역 제한이 없음(G9) | 평가 영역 = 주 시트(SG-D-19·20): 분류는 전체, 평가·비교·후보는 영역, 밖은 info. 연결돼 있어 최대 성분 규칙이 안 먹으므로 A bbox 규칙이 기본(`auto`). A bbox 가 추가 형상과 겹치는 다른 모델은 `region.mode`·`pad_mm` 로 조정, V-SG-R1 에서 확인 |
| R-SG-8 | v0.17.4(진행 중)가 늦거나 사다리 수정이 실 STEP 에서 부족 | V-SG-R1 을 v0.17.4 뒤로, 그때까지 합성 STEP(V-SG-1~4b)으로 진행. 사다리 실패 = `MESH_LADDER_FAILED` 그대로(조용한 오류 없음) |

## 10. 열린 항목

### 10.1 해소된 항목 (사용자 2026-11-11 "18.0은 권장대로")

| ID | 항목 | 결정 | 근거 |
|---|---|---|---|
| O-SG-1 | D3 고정점 기본값 | **해소**: 1순위 frame 일치(원점 ≤ 5 mm·축 ≤ 2°, part 21 bbox·주축 자동 판정) → A 고정 노드 → B 최근접 노드 ≤ h(옵션 (c) — 구멍 없는 RBE2 패드 포함), 2순위 불일치 → 정규화 frame + B 구멍 스냅 ≤ 10 mm, 최후 → 자동 설정 없음 + info. 결과 = seed `fixed_user`(편집 가능). SG-D-12~15 | 이슈 #63 코멘트 2026-11-11T10:16Z [3]: da9dc714 A·B 원점·X 축 일치, Y/Z bbox 차이 = 추가 형상 |
| O-SG-2 | tria 사다리 끝 = 경고 vs 막음 | **해소: 경고**(`tria_policy: warn` 기본, `block` 은 설정으로만). SG-D-6 | §0.1 — 분류 정상, 실패 안은 판정이 잡음 |
| O-SG-3 | beadgraph 삼각형 걸친 보스 수정 시점 | **해소: v0.18.0 = beadgraph 1.0.0 그대로**(①② 바이트·physicsai 고정판 불변). 걸친 보스 접촉 띠 수정은 이후 **beadgraph 1.1.0**(MORPH_RULES 2 — 그래프 스터디 기저 재계산 동반) | 실부품 1.0.0 분류 경고 0(§0.2 E5) |

### 10.2 열린 항목
- 없음(사용자 결정 필요 항목 0). 평가 영역 `auto` 규칙의 실부품 적합성은 V-SG-R1 에서 확인 — 다르면 `region` 설정 기본값만 바꿈(구조 불변).

## 11. 파일 소유권 · 작업 분해 (겹침 없음)

**rebase 규칙**: v0.18.0 구현 브랜치는 **v0.17.2·v0.17.3·v0.17.4 가 main 에 병합된 뒤 그 위로 rebase** 한다. v0.17.2(release/v0.17.2 — legacy ③ grid 전부 실패 처리·`--fixed-dir` 전달·os.replace 재시도)는 `worker/esl_worker/doe_jobs.py`·`worker/esl_worker/paicad_proc.py` 를, v0.17.4(진행 중 — ④ 사다리 OCCFix 구 조각 → 완전한 구 결함 수정, `select.graph.limits.max_elems` 600k)는 사다리·그래프 상한을 고친다. Backend 는 `_grid`·`_geom`·`_one_design`·`paicad_proc.py` 의 핫픽스 줄을 건드리지 않고(새 ③ 분기는 `_geom_select`·`run_step` 에만), Core 는 v0.17.4 사다리를 `mesh_dir` 인자 추가 외에 고치지 않는다(③ BD_MESH0 = v0.17.4 사다리 그대로). V-SG-9·10 기준 = v0.17.4, V-SG-11 기준 = v0.17.2 이후 legacy ③ 결과.

| 담당 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Core** | 신규 `esl/doe/step_graph.py`(`mesh0`(사다리 어댑터 → region → template_base·save_base), `region_mask(mesh, a_part_xyz, cfg, h)`, `frame_check(a_part, t_b, cfg)`, `fixed_transfer(a_fixed_doc, frame_a, t_b, cfg)`(xyz_nearest → ab_hole_snap → none), `seed_fixed_user(mesh, nodes)`, `tria_check(mesh, meta, cfg)`, `export_best(…)`); `esl/doe/stages.py`(`select_base` 값 step·`_sel_input` step 분기·`bd_mesh0` step 분기·`_sel_loads` 고정 출처·이전·seed·step 상한 전달·`_sel_auto_v2` fixed_user·`_sel_best` step 분기·`_cmp_mesh_shape`/`_cmp_ladder`/`_cmp_mesh_one`/`_cmp_defeature_stage`/`_cmp_remesh_one` `mesh_dir` 인자·`_design_mesh` TODO 주석·`select_prep_info` step_rel); `esl/doe/bead_graph.py`(`prep_graph` 상한 인자·auto 문서 `fixed_user`·manual seed·`out_of_region` 표지); `esl/doe/scenario.py`(`template_base` 선택 인자 `region`); `esl/doe/evaluate.py`(`evaluate` 선택 인자 `region` — umax·epsmax); `esl/doe/bead_select.py`(`HASH_NEW_KEYS_V0180`·`select_hash_view` step 조건만); `esl/doe/report_doe.py`(방법 줄); `esl/doe/__init__.py`(DEFAULTS `select.step_graph`); `resources/doe_messages.json`; 신규 `tests/doe/synth_step_graph.py`·`test_step_graph.py`·`test_step_graph_fixed.py`·`test_step_graph_perf.py`·`test_step_graph_region.py`, `tests/doe/test_bead_graph_cfg.py`(추가) | V-SG-1~5·4b·9·10·12 |
| **Impl-Backend** (`backend/**`, `worker/**`, `config/*.yaml`) | `backend/esl_platform/core/config.py`(`BeadDoeSelectStepGraphCfg`·settings 거울·`scenarios.select_step`); `api/schemas.py`(`select_base` Literal += step·DoeCheckOut step 필드·prep mesh/fixed 요약); `api/services/doe.py`(check/create/clone 검사·스냅샷 `select_base`·`mesh_mode`·`mesh_ladder`·settings); `api/services/doe_select.py`(`GET select/auto` step 규칙); `worker/esl_worker/doe_jobs.py`(**`_geom_select` step plan·`run_step` BD_MESH0 건너뜀 문구 분기만** — 핫픽스 함수 불변); `worker/esl_worker/register.py`(준비 요약 mesh·fixed); `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`; `backend/tests/test_doe_step_graph_api.py`·`worker/tests/test_doe_step_graph_jobs.py` + 기존 회귀 | V-SG-6·7·11 |
| **Impl-Frontend** (`frontend/**`) | `src/api/doe.ts`(`radioRequest`·`studyRadio`·legacy ③ 이름·`selectSubBlocked` step·seed 로드 조건); `src/api/types.ts`; `src/pages/doe/DoeStudy.tsx`(③ 라디오·입력 검사·준비 요약·받기 링크); `src/components/DoeInputs.tsx`(step 기준 칸·요약); `src/components/BoundaryPlan.tsx`(이전 고정 표시); `src/components/BeadSelectCard.tsx`(manual seed 고정 층 — 같은 seed 경로); `src/mock/doedata.ts`·`src/mock/server.ts`·`src/mock/graphmock.ts`; 신규 `src/__tests__/doe_step_graph.test.tsx` | V-SG-8 |

- 순서: Core(`step_graph` 시그니처·`fixed_transfer.json` 형식 §3.3 고정) ∥ Backend(스키마 §4 고정, v0.17.2 rebase 후) ∥ Frontend(mock) → 통합 E2E(V-SG-7) → 실기(V-SG-R1).
- 공동 수정 금지: `stages.py`·`bead_graph.py`·`bead_select.py` = Core 단독, `packages/beadgraph/**` = 변경 없음(O-SG-3 이 다르게 정해지면 Core 단독), `schemas.py`·`config.py`·`config/*.yaml`·`worker/**` = Backend 단독, `types.ts` = Frontend(Backend 스키마 거울). `VERSION`·`CHANGELOG.md`·`docs/**` = 통합 담당.

## 12. 통합 v0.18.0 (2026-11-12) — 수용한 편차 · 통합 보강

### 12.1 수용한 편차(accepted deviations)

| ID | 편차 | 근거 · 처리 |
|---|---|---|
| SG-X-1 | **step 기준 paicad 힌트 plan = extract 만**(extract0 없음). §2·V-SG-7 의 "BD_GEOM(a_fixed + 힌트)" 중 힌트는 B STEP 사본에 `extract` 1회 | extract0 는 조립 파트 대응(`--assem-dir`·body_map·part_id)용 1차 추출인데 step 기준에는 B 조립·part_id 가 없다 — 기존 ③(legacy, paicad) 과 같음(D-0.17.2-AFIXED). 힌트 실패·paicad 없음 = 정보 `AUTO_HINT_UNAVAILABLE`(seed 무관) |
| SG-X-2 | **합성 H6-STEP 은 엄격 V-BG-1(V-SG-1)을 만족하지 않음**: class 정확도 97.3 %(기준 99.0 %), 세그먼트 19/23 — 벽에 걸친 큰 보스 2개(`wboss_448_175`·`wboss_752_175`)가 벽으로 분류됨. 그 밖 기준(바닥·tier ≥ 99.5 %, 벽 소유·세그먼트 라벨 ≥ 98.5 %, 접합 16/16, 랜스 16, 걸침, 구멍)은 통과 | 원인 = 합성 STEP 생성기: 경사면을 OCC 경계 채움(`addSurfaceFilling`)으로 만들면 꼭짓점 많은 고리에서 비정상 종료(segfault)해 평면 삼각형 조각(facet)으로 만듦 → 사다리 cad 메시가 조각마다 작은 삼각형(≈ 11 %)을 가짐. 시험(`tests/doe/test_step_graph.py::test_h6_step_classify`, `H6_STEP_KNOWN_MISS`)은 **측정 상태를 고정**(class ≥ 97 %, 세그먼트 ≥ 19, 놓친 섬 ⊆ 2 보스). 엄격 기준 확인은 실부품 V-SG-R1(이슈 #63)으로 넘김 |
| SG-X-3 | Core 가 §11 소유 목록 밖 파일을 고침: `esl/doe/scenario.py`(`template_base` 선택 인자 `region`), `esl/doe/evaluate.py`(`evaluate` 선택 인자 `region` — umax·epsmax), `esl/doe/report_doe.py`(방법 줄) | §11 표의 Impl-Core 행에 이미 적힌 범위(선택 인자·방법 줄)와 같고, **`region` 인자 없음 = 바이트 동일**(V-SG-4b (g), V-SG-9 regress) |
| SG-X-4 | 화면에 part-title 칸 없음 | SG-D-3: step 기준은 `part_title` 금지(422) — B STEP 은 파트가 하나라 고를 것이 없음 |

### 12.2 통합 보강(추가만)
- **plan-view(`GET …/plan-view`, select_base step)**: `fixed[].src` = `"a_transfer"`(`prep/select/fixed_transfer.json` `node_id` 의 B 노드) | `"user"`(그 밖 — 화면에서 칠한 고정), `region_ab` = 평가 영역(`base_mesh.npz` `region`) 바깥 고리 (a,b) mm(코어 `keepout.region_rings` — 구멍 고리 제외, 영역 = 전체이면 null). `DoePlanOut.region_ab` 를 openapi 에 넣음(①② 응답 = null, 다른 필드 불변). 화면 PartView 의 "주 시트 영역" 층·A 이전 고정 표시가 이 값을 씀.
- **openapi**: `DoeCheckOut.step_graph`(dict — 화면 types `DoeCheckStepGraph{size_mm, ladder, tria_policy, fixed_transfer{enabled, mode}, region{mode}}`), info.version 0.18.0.
- **설정 거울**: `DEFAULTS["select"]["step_graph"]` = `BeadDoeSelectStepGraphCfg` = yaml 2개 = §4.3(키 `size_mm` 없음 — h 는 ④ 프로필, settings 응답에만 `size_mm`) — `backend/tests/test_doe_select_api.py::test_select_defaults_mirror_contract` 가 생략 없이 직접 대조.
- **V-SG-7**: 워커 E2E 가 건너뛰지 않고 실행 — A Case = H5 시트 메시(h 10 mm, B STEP 과 같은 형상), 선택 schema 2(`select_schema2` 표지), 준비 → seed 저장 → 미리보기 → 실행 → 받기(ch_r.rad·ch_r.fem·values.json, best 에 STEP/BREP 없음) → plan-view `fixed[].src`. `GRAPH_FAILED` 주입·paicad 없음 변형은 단위 시험(`_geom_select`)·코어 시험이 맡음.
