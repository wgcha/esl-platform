# release/v0.25.0 C1 진행 handoff (코어 — 가상 비드 "추가 비드", kind A)

계약 docs/contracts/esl_virtual_bead.md, 결정 D-0.25.0-VB-1~20. 시험 환경 /tmp/rdenv_v0250.sh(= /tmp/rdenv_main.sh, REPO_ROOT=wt_v0250,
PYTHONPATH += packages/beadgraph/src). pytest --basetemp=/tmp/c1_250_bt -o tmp_path_retention_policy=failed.
발견·보정 = work/findings.md VB-C1-1~13(메인 결정 필요: VB-C1-5 warp 15° 가 r 0 을 막음, VB-C1-6 H6 부모 바닥 = 띠뿐, VB-C1-7 θ > flip 60°).

## 계약면(B1·F1 이 맞출 것)
- 설정 `bead_doe.virtual_bead`(DEFAULTS 만 C1 — pydantic `BeadDoeVirtualBeadCfg`·yaml 2 는 B1, 같은 이름·값):
  `{enabled true, max_count 4, min_wall_elems 2.0, margin_mm 3.0, theta_default_deg 45.0, theta_range_deg [15.0, 75.0], d_max_limit_mm 30.0,
  default_on true, warp_max_deg 15.0, preview_max_nodes 50000}`. 해시 안 키 = `esl.morph.virtual_bead.HASH_KEYS`
  (min_wall_elems·margin_mm·theta_default_deg·theta_range_deg·warp_max_deg).
- 스냅샷(B1, 새 select 그래프 스터디·enabled 만): `doe.virtual_bead = {"schema": 1, <HASH_KEYS 값>}`. 복제 = 원 블록 그대로. 코어는
  `stages._vb(c)`(블록 없음 = VB_SCOPE), `_sel_cfg_sha += virtual_bead`(선택에 virtual_beads 있을 때만), basis.json `vb_rules`·`virtual_beads[]`.
- 선택 schema 2 키 `virtual_beads[{id a1..a9, name?, p0, p1 | length+angle_deg, w_top, theta_deg?, d_max, side? "+"|"-", end? round|square,
  r?}]` — 정규화 = `bead_graph.normalize_vbeads`(normalize_v2 안). 빈 목록·없음 = 키 없음(옛 sha 불변). 422 코드 VB_INPUT_INVALID·
  VB_MAX_COUNT(detail vbead·key). beads 0 + virtual ≥ 1 허용. 백엔드 `SelectionInV2.virtual_beads`(빈 목록은 dump 에서 뺌).
- derive(백엔드 → 코어): `derive_v2(mesh, norm, cfg, graph, labels, frame=…, fixed_scan=…, …, virtual_bead=<스냅샷 블록>,
  vb_plan=<transfer_plan.plan_for(...)["vbead"]> (기본 "plate"), tie_node_ids=<지그 tie 노드 ID>)` — 가상 비드 있을 때만 키 효과.
  응답 += `virtual_beads[{id, name, p0, p1_resolved, len_mm, angle_deg, side_resolved, ok, reasons[{code,text}], warnings[{code, level,
  vbead, …, text}], h, n_wall, n_top, stretch_max?, n_fp?, n_elems_fp?, outline_ab?[{a,b}], preview?{idx[], vec[[3]], g[], c}}]`,
  `vb_frame{origin, e_xi, e_eta, n_h}`(가상 비드 있을 때만). preview 상한 넘으면 생략 + warnings VB_PREVIEW_SKIPPED.
  derive 캐시 키: 선택 sha 가 virtual_beads 포함 → 추가 불필요, 블록 sha 만 += (블록 있을 때).
- params[] A 행: `{name "A<n>_A", type "A", bead "a<n>", tier null, form "hinge", nominal 0.0, unit "mm", feasible [0, d_max],
  feasible_source "user", default_range [0, d_max | usable_hi], use_default (default_on ∧ ¬blocked), group_members [name],
  label "추가 비드 n · 깊이", wall_elems, vb{w_top, theta_deg, side, n_wall, n_top, len_mm, angle_deg, d_max}, acc_hint{h, d, theta,
  c_err_pct, pi_err_pct}|null, guard?}`. beads[] kind "virtual" 행 `{id, name, kind, warnings, vb_reason?{code, text}}`(params.json 은 같은
  행 — vb_reason 에 text 포함).
- 기저(basis.npz·basis.bin·basis.json): hinge 변수가 있을 때만 npz `form`(U6)·`g`(f64, idx 와 같은 ptr, linear 구간 0)·`c`(f64/변수),
  bin = 그 변수 vec 뒤 `[g:f32×n]` 꼬리, basis.json vars[] 그 변수 `form:"hinge"`·`c`. 없으면 바이트 그대로.
- **브라우저 `basis.ts` 동등 규칙(F1)**: `BasisVar += form?: "hinge"; g?: Float32Array; c?: number`; `parseBasis` 는 meta var.form ===
  "hinge" 이면 vec 뒤 n 개 f32 g 를 읽고 끝 길이 엄격(남음·모자람 = 오류). 항 함수 `termAt(v, x, i)`:
  linear = (x − nominal)·vec_i, hinge = vec_i·[ramp(x − g_i, c) − ramp(nominal − g_i, c)], `ramp(t, c)` = c ≤ 0 ? max(0, t) :
  (t ≤ −c ? 0 : t ≥ c ? t : (t + c)²/(4c)) — 코어 `esl.morph.virtual_bead.ramp` 와 같은 식(V-0250-VB-8: float32 morph 차 ≤ 1e-4 mm,
  파이썬 에뮬레이터 tests/doe/test_vbead.py::_ts_morph). derive preview → `BasisVar{form:"hinge", idx, vec, g, c, nominal 0}`.
- 문구(resources/doe_messages.json): VB_SCOPE·VB_INPUT_INVALID·VB_MAX_COUNT·VB_NOT_ON_PLATE·VB_OVER_BEAD·VB_OVER_ISLAND·VB_OVER_HOLE·
  VB_PLATE_EDGE·VB_FIXED·VB_OVER_VBEAD·VB_EXCLUDED·VB_MESH_COARSE·VB_WALL_COARSE({n_wall})·VB_TOP_NARROW·VB_EDGE_SMEAR({h})·
  VB_BAND_OVERLAP·VB_PREVIEW_SKIPPED·VB_VERIFY_HINT·VB_LIST_TIP·A_RANGE_INVALID.
- 범위 규칙(422): type A lo < 0 → DOE_RANGE_INVALID "추가 비드 깊이 하한은 0 이상"(matrix._NOMINAL_RULES 표 — U 와 같은 분기).
  default_params 조건 = use_default ∧ (type ∈ default_types ∨ form == "hinge"). 썸네일 색 범위 A |hi| 포함.
- 결과: BD_POST result.json warnings += "VB_VERIFY_HINT: …"(행렬에 A<n>_A 변수 있을 때만).
- 계획 표: transfer_plan.PLANS 열 `vbead`(case/bmesh/step_once plate, 그 밖 none), section.SECTION_PLANS 열 `form`·`vb_host` + 행
  `virtual`, 판정 `section.vb_allowed(plan_vbead, host_row)`.
- 정확도 표 resources/vbead_accuracy.json(schema esl/vbead_accuracy/1, cells[{h, d, theta, wall_elems, status, *_err_pct, c_err_pct,
  pi_err_pct}]) — tests/doe/vbead_accuracy.md 같은 값.

## 개정 2·3 계약면 변화(dd3c3ada §19 — D-0.25.0-VB-21~28, B1·F1 이 맞출 것; 위 절보다 우선)
- 설정 11키: `theta_range_deg` 기본 **[15, 60]**, 새 키 **`r_default_h_mult` 1.0**(0..4, 해시 안 — HASH_KEYS 에 포함), `warp_max_deg` =
  정보 세는 기준. 검증(코어 `esl.doe.check_virtual_bead` — settings() 가 부름, pydantic 같은 식): 1 ≤ lo < hi ≤ 89, default ∈ [lo, hi],
  **hi ≤ select.quality.flip_deg** → `CONFIG_INVALID`, 문구 `VB_THETA_FLIP`({theta_hi}, {flip}), detail {key
  "bead_doe.virtual_bead.theta_range_deg", theta_hi, flip_deg}.
- 스냅샷 블록 `doe.virtual_bead` += `r_default_h_mult`(코어: 블록에 키 없으면 0.0). `GET /doe/settings` += r_default_h_mult.
- 선택 문서: **`flip: true`**(false·None = 키 없음 — B1 은 코어에 넘기지 않음), **`side` 키 삭제(주면 422 key side)**, `r` 은 준 값이면 0
  도 키 유지(None = dump 에서 빠짐), 준 r > r_cap + 1e-4 → 422 VB_INPUT_INVALID detail {vbead, key "r", r_max}, θ > min(설정 상한,
  flip_deg) → 422 key theta_deg. `flip` 이 bool 아님 → 422 key flip.
- derive `virtual_beads[]` += `r_resolved`·`r_source`("default"|"user")·`host`("base"|"area"|"plateau")·`host_floor`; warnings +=
  `VB_R_CLAMPED{r, r_h}`(info), 모든 warnings 에 text(자리표시 채움). `side_resolved` = 적용 방향(자동 × flip). `depth_max_mm` 없음.
  preview 형식 그대로(g·c — 보상은 평가 식).
- params A 행 `vb` += `r`·`r_source`·`host`(`vb.side` = 적용 방향), `guard.warp{limit_deg, n, max_deg, at}`(range guard 켬일 때 —
  n > 0 이면 B1 이 `text` = VB_WARP_INFO 문구 동봉), `acc_hint` += `r`(칸 값 — 고르기: r 생략 → cells, 준 r 0 → cells_r0, 그 밖 준 r →
  칸 r 의 1/1.25..1.25 배 안일 때만). 비드 warnings += `VB_WARP_INFO{n, max, d}`(info).
- 선택 `range_guard.json` A 항목: `crit` 없음, `warp{limit_deg, n, max_deg, at}` 있음. D·W·U 항목 불변.
- basis.json `vb_rules` **3**, `virtual_beads[]` += `r`·`host`. basis.npz·bin 형식 그대로.
- **브라우저 `basis.ts` 동등 규칙(F1, 개정 3)**: `depthEff(v, c)` = c ≤ 0 ∨ v ≤ 0 ? v : (v ≥ 0.75c ? v + c/4 : c·(√(1 + 4v/c) − 1));
  `termAt` hinge = vec_i·[ramp(depthEff(x, c) − g_i, c) − ramp(depthEff(nominal, c) − g_i, c)], `ramp` 그대로(코어
  `virtual_bead.depth_eff`·`hinge` — 파이썬 에뮬레이터 tests/doe/test_vbead.py::_ts_morph, 차 ≤ 1e-4 mm).
- 문구: 새 VB_WARP_INFO·VB_R_CLAMPED·VB_THETA_FLIP, 바뀜 VB_PLATE_EDGE("판·평탄부 가장자리에 닿음").
- 화면(F1): r 칸 비움 = 기본(자리 표시 "요소 크기"), 방향 = 체크 칸 "방향 뒤집기" 1개(라디오 없음 → flip), θ 칸 15~60, "평판 위를
  찍으세요" 판정에 평탄부(host area·plateau) 포함, A 행 회색 정보 꼬리표 "뒤틀림 n"(guard.warp.n > 0).
- 정확도 표 resources/vbead_accuracy.json schema 2: `cells`(r 기본 — 열 += r·warp_n·warp_max_deg)·`cells_r0`(f238144d 보존).

## 끝난 일
- 골든 c35b8ac1(b1e52fad 코드로 기록 — 4 스터디 세계·guard 표·정규화 sha·morph/basis 바이트), 코어 51f39eb7, 시험 d29704fd.
- 시험: test_vbead_golden 12(옛·블록 + 가상 비드 0 바이트 동일), tests/morph/test_virtual_bead 12, tests/doe/test_vbead 37,
  test_vbead_e2e 3, test_vbead_h6 4. H6 측정 = work/vbead_h6.md.

- 정확도 표 f238144d: resources/vbead_accuracy.json = tests/doe/vbead_accuracy.md(12칸, 불가 4칸 = VB_MESH_COARSE). 최대 |차|
  2.17 %(h 5·D 6·θ 45 C 집중), h 3 최대 1.44 %, h 1.5 최대 0.59 % — h 1.5 ≤ h 3(수렴 방향), h 3 ≤ 5 % 통과. 실제 메시 대비 가상 비드가
  약간 강함(C 음수). 재생성 = python tests/doe/synth_vbead.py OUT.json(h 1.5 칸 superlu ≈ 3.9 GB·135 s — 다른 무거운 작업과 동시 금지).
- 비용(V-0250-VB-18, 9,801 노드): 가상 비드 1개 derive 17 ms·기저 < 1 ms·guard 0.04 s(7 평가)·morph 0.06 ms·npz 4.6 KB,
  4개 derive 40 ms·guard 0.22 s(28)·morph 0.19 ms·npz 10.2 KB.

- 전체 시험: tests/ 1837 passed·192 skipped·실패 3(허용: test_large_model_cad_share, test_v0160_bytes_skip_policy[h8]·[h5open]),
  packages/beadgraph 117 passed·2 skipped. (첫 전체 실행에서 test_jig_grid_plan 정적 시험 2건 = VB_VERIFY_HINT 의 c.scn 비교 →
  시나리오 조건 없이 A<n>_A 변수 유무만으로 고침.)

- 개정 2·3(dd3c3ada): merge v0.24.9 05a2c0dc(b58c3d1f — 충돌 decisions.md·work/findings.md 만, 둘 다 보존), 구현 8762b627,
  H6·findings·handoff 8a799bf7, 정확도 표 97970690. H6(r = h): 띠 ξ·평탄부 ξ·30° θ45·30° θ60 모두 ok·guard ok usable [0, 5]·
  뒤집힘 0·밖 이동 0(warp 정보 n 23~106). 정확도(cells, r 기본): 최대 |차| 4.41 %(h5 D6 θ45), h3 최대 3.28 %, h1.5 최대 1.60 %.
  findings VB-C1-14~21.
- 개정 2·3 전체 시험: tests/ 1872 passed·192 skipped·실패 3(허용 3건만 — 첫 실행의 test_vbead_cost 는 r 기본으로 발자국이 넓어져
  가상 비드끼리 겹침 → r 생략으로 고쳐 단독 재실행 통과), beadgraph 117 passed·2 skipped. 가상 비드 0개 골든(c35b8ac1) 바이트 동일.
  비용(r = h): 1개 derive 20 ms·guard 0.012 s(2 평가 + warp 측정 1)·morph 0.06 ms, 4개 derive 40 ms·guard 0.044 s(8).

## 남은 일
- 메인 결정: VB-C1-5(warp 15° → r 0 blocked), VB-C1-6(H6 부모 바닥 = 띠), VB-C1-7(θ > flip 60°).
- B1: 설정 거울·스냅샷 블록·SelectionInV2·derive 인수·settings 응답. F1: basis.ts hinge·VirtualBeadPanel·DoeParamTable kind virtual.

## 다음 명령
source /tmp/rdenv_v0250.sh; cd /home/claude/wt_v0250; $PY -m pytest -q tests/ --basetemp=/tmp/c1_250_bt -o tmp_path_retention_policy=failed
