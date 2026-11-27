# v0.25.0 C1 findings — 계약 보정·메인 결정 필요(esl_virtual_bead.md, VB-C1-n)

- VB-C1-1 (§3.2) lance(cls 3) 요소는 VB_NOT_ON_PLATE 괄호와 VB_OVER_ISLAND 양쪽에 적혀 있음 → 더 구체적인 VB_OVER_ISLAND 로(섬·lance·
  cls 2/3·island ≥ 0). VB_NOT_ON_PLATE = H 아닌 요소 중 비드·섬·제외로 설명되지 않는 것(벽·다른 바닥) + 점 사영 거리 초과 + 발자국 요소 없음.
  "사유마다 위반 1개 → 그 코드만"(§12-3)을 지키려는 최소 해석.
- VB-C1-2 (§2.3) 그래프 비드 `b.n_hat` 은 모든 비드가 그래프 frame n0(같은 값) — 깊이 방향이 아님. 다수결은 비드 바닥 노드의 host 판 평면
  부호 거리 중앙값 부호로 함(실제 깊이 방향). side "+/−" 는 n_h 기준이고 n_h 는 그래프 frame n0 쪽으로 맞춤(n0 은 모형마다 ±z 어느 쪽일 수
  있음 — 합성 채널 세계는 n0 = −z). 화면·문서의 "+ = 판 법선 쪽" 설명은 n_h 기준임을 명시 필요.
- VB-C1-3 (§2.2·§8) `derive_obj_v2` 에 ESL frame 이 없음 → 키워드 `frame`(stages = prep/base.json frame, 백엔드 derive_v2 = inputs frame)
  추가. frame 없음 = 그래프 frame e1·e2·n0 대체. `vb_plan`(계획 열 vbead 값) 키워드 추가 — 기본 "plate"(select 는 늘 case/bmesh/step_once),
  stages 는 `_lt_plan(c)["vbead"]` 를 넘김. 지그 tie = `_pos_u_tie_ids`(PU-14 함수)를 pos_u 없이도 넘김(가상 비드 있을 때만).
- VB-C1-4 (§6.2) SH-28 한쪽 보정 = `range_guard.side_stuck`: 양쪽 범위는 지금 식 ¬(u_lo < v₀ < u_hi) 그대로(정확 비교 — 바이트 불변),
  한쪽 범위(폭 0 인 쪽 있음)만 계약의 1e-4 허용(usable_hi ≤ 0 + 1e-4 → blocked). `blocked` 는 그대로 두고 "모든 쪽 막힘" 판정을
  `all_blocked`(폭 > 0 인 쪽만)로 `single` 에서 씀. 기존 표 바이트 = 골든(test_vbead_golden::test_guard_tables_unchanged).
- VB-C1-5 (§6.1·§12-9·12, 메인 결정 필요 — 시험 완화 안 함) **warpage 기준 15°가 r = 0 가상 비드를 거의 다 막음.** 꺾인 선(깊이면
  가장자리·입구)이 요소 안을 비스듬히(끝 둥근 부분·비정렬 메시) 지나면 quad warpage ≈ 수십 °(꺾임 각 θ 에 비례, h 와 거의 무관 — δ/h ≈
  tanθ/√2). 측정: 합성 h 5 W 10 θ 45 d_max 6 → usable 0.75(blocked, warp 50.9°), θ 30 → blocked(26.5°), θ 15 → ok, r 5 → limited
  1.875, r 10 → limited 2.44, r 20 → ok. H6 위 띠(h 3) 계약 단면 → blocked usable 0.47(warp 40.6°, warp_bad_new 23), r 5 → limited 1.25;
  H6 평탄부(plateau, 비정렬) → blocked usable 0.16(warp 55.7°, 152 요소). 뒤집힘·jac·tri 새 위반은 모두 0. 선택지: (a) warp_max_deg
  기본 상향(예 45°) 또는 A 항목 warp 를 정보만, (b) r 기본 > 0(예 r = h), (c) 그대로(사용자가 r 을 줘야 함 — 화면 안내). 지금 코드 = 계약
  그대로(15°, A 만), 시험은 측정값 고정(test_vbead::test_guard_blocked_measured_v9, test_vbead_h6 측정 = work/vbead_h6.md).
- VB-C1-6 (§12-12, 메인 결정 필요) H6 의 부모 바닥(segment base)은 판 가장자리 띠뿐(아래 y 1..32 ≈ 31 mm, 위 y 634..674 ≈ 40 mm) — 넓은
  평탄부는 plateau(segment 11, 깊이 4, floor kind area — host 아님, Q-VB-2·R-VB-7). 계약 단면(W_top 15·θ 45·d_max 5) ξ 방향은 위 띠에
  들어가 ok, 30° 는 띠에 못 들어가 VB_PLATE_EDGE. 30°·평탄부 측정은 순수 장(host 판정만 plateau)으로 따로 함(뒤집힘 0). #88 처럼
  평탄부가 plateau 로 분류되는 모형이면 1차 범위에서 가상 비드를 거의 못 놓음 → Q-VB-2 대안(plateau host) 우선순위 재검토 필요.
- VB-C1-7 (§3.3·§7.1) θ > select.quality.flip_deg(60°)이면 사면 요소 법선 회전 > flip_deg = "뒤집힘"(design_state FAILED_MESH·guard
  inverted) — theta_range_deg 상한 75° 와 모순. 측정: 합성 θ 75 W 5 d_max 20 → guard blocked(inverted 78). 선택지: theta_range 상한 ≤
  flip_deg 로, 또는 가상 비드 평가의 뒤집힘 기준을 공칭 법선 대비가 아닌 다른 식으로. 지금 = 계약 그대로(15..75).
- VB-C1-8 (§8·§5.1) `acc_hint` 는 코어 params 행에서 고름(`bead_graph.vb_acc_hint`, 표 = resources/vbead_accuracy.json — 상대 거리 최소 칸,
  표 범위의 1/1.25..1.25 배 밖 = null). API·params.json 이 같은 값 — B1 은 그대로 전달만.
- VB-C1-9 (§2.2) host 평면 = p0 에 가장 가까운 host 요소(씨앗)의 floor 라벨과 같은 host 요소만(다른 바닥 조각 = VB_NOT_ON_PLATE), 반경
  L/2 + W_open/2 + margin 의 중심 = 입력 선분 중점(사영 전 — (b) 는 frame 축으로 임시 끝점). 점 사영 거리 기준의 h = 그래프 frame h_mm
  (발자국 h 는 그 뒤에 정해짐).
- VB-C1-10 (§6.1) 선택 range_guard.json A 항목 key = {kind "A", vbead "a<n>"}, 항목에 `crit{warp_max_deg}`(A 만 — 문서 머리 crit 불변).
  `guard_probe` 반환은 warp_max_deg 를 줄 때만 warp_bad_new·warp_max 키.
- VB-C1-11 (§8) derive preview vec·g 는 JSON 6 자리 반올림(1e-6 mm — V-BS-12 1e-4 기준 안). outline_ab 는 frame 있을 때만(d_move 윤곽,
  round = 반원 9점씩).
- VB-C1-12 (§12-11) 정확도 세계의 정의되지 않은 부분: 끝 = square(실제 메시도 같은 식 — 귀퉁이 대각 꺾임만 요소 안), 지지 = 네 변 z +
  면내 3-2-1, 지그 = tie 8점 병진(translation), 목표 g_z = 0.2·(x/400)·(y/300), 하중 = 균일 압력 1, spring α 1. h 1.5 칸은 superlu
  메모리 ≈ 3.9 GB·칸당 ≈ 135 s(pytest 에서 다시 풀지 않음 — 표 대조 시험은 h 5·3 칸만 재계산).
- VB-C1-13 (§7.2) 선택 basis.json `virtual_beads[]` 에 거부된 가상 비드도 행(reasons) — 재사용·진단용. `_sel_cfg_sha += virtual_bead`
  보기 = 해시 안 키 5개 + vb_rules.

## 개정 2·3 구현(dd3c3ada 계약, D-0.25.0-VB-21~28) — VB-C1-5·6·7 은 VB-21~25 로 종결
- VB-C1-14 (§19.4-4·§19.9.1-4) 발자국 d_move·검사 띠는 계약상 "입력 θ" 지만 장은 θ_f 로 계산 → θ = flip_deg 에서 장이 d_move 밖으로
  ≈ 1e-3 mm 넘침. 최소 해석: 발자국(이동·검사 띠·r 0 발자국 h)도 θ_f 로 계산(차 ≤ 0.01°). 해상도 판정(run·n_wall)·표시·저장은 입력 θ.
- VB-C1-15 (§19.3-2) 평탄부 바깥 테두리 transition(child = host floor)에 닿으면 VB_PLATE_EDGE, 그 너머 부모 floor 요소는 VB_NOT_ON_PLATE
  뿐 아니라 VB_OVER_BEAD 로도 세지 않음(H6 평탄부 floor 11 의 부모 = 링 비드 floor 4 라 "같은 원인" 원칙이 OVER_BEAD 에도 필요).
  host 아닌 다른 area·plateau floor 요소 = VB_OVER_BEAD(base host 의 개정 1 사유 그대로 — 평탄부도 그래프 비드).
- VB-C1-16 (§19.6-24) H6 위 띠 30°(700, 649) L 20: 개정 1 = [VB_PLATE_EDGE] → 지금 [VB_OVER_BEAD, VB_PLATE_EDGE](r 기본으로 발자국이
  1.25·r·tan(θ/2) ≈ 1.55 mm 넓어져 링 비드에도 닿음). 시험은 PLATE_EDGE 포함으로.
- VB-C1-17 (§19.6-23) H6 평탄부 계약 자리 (125, 300) ξ L 120·(250, 300) 30° L 100 은 보스·구멍·자식 비드에 닿아 거부(VB_OVER_BEAD·
  ISLAND·HOLE) — 30° L 100 은 평탄부 어디에도 빈자리 없음(25 mm 격자 탐색). 측정 자리 = (150, 180) ξ L 120 θ 45, (250, 180) 30° L 60
  θ 45, (200, 480) 30° L 60 θ 60 — 모두 ok·range guard ok usable [0, 5]·뒤집힘 0(work/vbead_h6.md).
- VB-C1-18 (§19.4-3) normalize_v2 는 스냅샷 블록을 받지 않음 → θ 상한 = min(지금 설정 theta_range_deg[1], flip_deg(스냅샷 range guard
  블록 값, 없으면 select.quality)). 블록 상한 75 인 옛 스냅샷 + θ 70 은 설정 상한 60 으로 422(key theta_deg) — 시험 V-25 통과.
- VB-C1-19 (§19.3-1) wall_islands floor 제외(→ VB_OVER_ISLAND) 구현(섬 크기 = select.graph.island.max_mm)했으나 합성 세계(벽에 먹힌
  보스)는 만들지 않음 — 시험 없음.
- VB-C1-20 (§19.5-6·지시 4) 정확도 재측정 실행 조건(정정 = 가용 ≥ 5 GB ∧ 다른 pytest/vitest 없음): 실행 직전 `free -m` 가용 7.17 GB,
  시스템 사용 856 MB(다른 무거운 프로세스 없음 — 이 작업의 pytest 도 돌리지 않음) 상태에서 단독 실행(h 1.5 칸 최대 ≈ 3.9 GB). ps 확인은
  하지 않았으나 사용 메모리로 보아 다른 시험 없음.
- VB-C1-21 (§19.5-5) acc_hint 준 r(0 아님): 고른 칸 r 의 1/1.25..1.25 배 밖이면 null. 행 acc_hint += r(칸 값).


# v0.25.1 C1 findings — 계약 보정·최소 해석(esl_view3d_scene_legend.md, VL-C1-n)

- VL-C1-1 (§3.2 공통 좌표) provider `frame` = 스터디 대상 frame(`t.frame` — ①②③ design_target·④ compare_target 모두 frame 고정 = 기준)
  + 메시 좌표 그대로. 배치(A → 대상)는 모든 메시에 같은 사상(dst_frame = t.frame)이라 상대 위치는 같고, A ESL frame 으로 되돌리면(unplace)
  A 메시보다 넓은 형상 노드가 가장자리 셀로 눌림(vox_key clip). 셀 키·격자 = `grid_map.grid_frame(t.frame, cell)`·`vox_key` 그대로.
- VL-C1-2 (§2.6) `esl/mech/grid_map.py` 는 C1 파일 목록 밖이지만 계약 §2.6 "격자 경로 `_jg_shape(keep_u)` 반환에 rc·fs 추가"에 필요 —
  `run_shape` keep_u 일 때 `rcfs{src:{eid:{bc, rc, fs}}}` 보관만(계산·파일 불변). 기존 `bc{src}` 는 첫 엔트리 BC 라 엔트리 값(bc_val·sp_g)이
  다름 → 씬 C 기여도·씬 지지 표식은 엔트리 BC(rcfs) 사용(기존 jd·js 3D 폴더 표식 = 그대로 첫 엔트리 BC — 바이트 불변).
- VL-C1-3 (§2.3 ranges) `ranges.c.p01·p99`·`ranges.dc.abs_p99` = 값 ≠ 0 노드의 백분위(np.percentile 선형) — 하중 없는 노드는 c = 0 이라 전
  노드 백분위는 0 에 붙음(pa·fn p99 가 하중 노드만 쓰는 것과 같은 규칙). 값이 모두 0 이면 null.
- VL-C1-4 (§2.1·§8 인수분해 재사용) 기존 3D 함수가 같은 provider 본체(`_scn_full_p`·`_scn_jig_p`·`_scn_nodal_p`·`_scn_jig_grid_p`)로 자기
  폴더를 쓰고 그 provider(열린 분해)를 실행기에 넘김(`_scn_feed`) → 씬 묶음 = 후진대입만(H5 실측: 분해 수 씬 끔 12 = 켬 12, 시험
  `test_v0251_factorization_reused`). `_view3d` 의 `ev.evaluate` 는 같은 지지 점검·쉘 모델·분해·풀이 함수로 바뀜(같은 u — 골든 바이트 동일).
  기존 3D 가 만들지 않은 (출처, 안)만 실행기가 provider 를 직접(분해 +1 — 보충 실행·옛 스터디).
- VL-C1-5 (§2.1 차이 순서) 기존 지그·노드 힘·격자 3D 는 안을 기준(d000)보다 먼저 만든다 → 그 안 묶음은 c 만 쓰고 pack.json 을 미룸, 기준이
  오면 차이를 더함(`view3d.patch_scene_dc` — e<kk>.bin 끝·e<kk>.json, 결과 바이트 = 처음부터 dc 를 넣어 쓴 것과 같음) 뒤 pack.json.
  기준 실패 = 차이 없이 pack.json(dc null) + skipped SCENE_FAILED(detail "baseline").
- VL-C1-6 (§2.4 한도) 씬 = (출처, 엔트리) — 그 출처의 모든 표시 안에 같이 넣거나 같이 뺌(같은 씬 비교). 필수 = 표시 안마다 그 출처 C 최악
  엔트리 + (보충) 이미 있는 씬. 나머지 = 출처마다 베이스라인 C 큰 순 순번 → 표 행 순으로 한도 안에서. 비용 = Σ_안(베이스라인 14·N, 안 16·N
  + 40 KB), 형상 36·N 은 묶음마다 먼저 셈. `est_mb` = 계약 식 그대로(빠진 씬 포함 전부, MiB).
- VL-C1-7 (§2.6 경계력·내력 provider) `_ns_design` 은 안 사이드카(run/designs/<did>/bforce.json·fint.json — solve.seconds 시간 키)를 다시
  쓰므로 실행기 직접 경로는 부르지 않고 같은 모델·지지·영역으로 풂(BD_POST 는 기존 `_ns_view3d` 가 `_ns_design(keep_u = 전 씬)` — 이미 풀던
  전 씬 변위를 남기기만, 추가 풀이 없음).
- VL-C1-8 (§2.3 사이드카 warnings) 진단 문자열 `SCENE_C_MISMATCH`(|Σc + offset − value| > 1e-6 상대)·`SCENE_PIN_MISMATCH`(핀 값 ≠ 표 값)·
  `SCENE_FAILED: <src> <did> <code>` — 계약 skipped 코드 밖(정보). 알려진 원인: (a) v0.24.9 하중 공간 고정(spatial) 스터디의 안은 평가가
  `_lf_ctx` 하중·지그 `_lf_jig_force` 를 쓰지만 기존 `_view3d` 입력부·지그 3D 는 노드 하중(sc.load_loads·npz a) — 씬도 같은 입력이라 Σc ≠ 표 C
  (기존 자동 3D 와 같은 한계, 지그 offset 은 prep/load_follow.json jig_ref 로 맞춤). (b) 평가 영역이 빈 격자 지그: 저장 umax_ev = 0, 핀은
  `umax_in` 규칙(전 노드). (c) 하중 전달 없는 옛 ④: `_view3d` 입력부 design_target vs 평가 compare_target(기존 그대로).
- VL-C1-9 (§2.2 manifest) 씬 manifest schema = 기존 `esl/view3d/1`(키 전부 + c·dc·pins·ranges.c·dc), `key` = `doe/scene/<tag>/<did>/e<kk>`,
  `esl_run_id` = entry_id, `lod` = 묶음 lod. 핀 kind: 전 노드·노드 힘 = ev | all | region, 같은 메시 지그 = ev | mask(omega), 격자 = ev | mask
  | all. `pins.umax` = null 은 노드 없음만.
- VL-C1-10 (§9.1-15) 설정 거울(pydantic `BeadDoeView3dSceneCfg`·yaml 2개)은 B1 소유 — 코어 시험 `test_v0251_15_settings_mirrors` 는 B1
  통합 전 skip, 통합 뒤 자동 확인. 코어 범위 검증 = `esl.doe.check_view3d_scene`(settings() — 어기면 CONFIG_INVALID, detail {key, value}).
- VL-C1-11 (§8 실측 — E-0251-9 대체) H6(103,930 노드)은 이 기계(7 GB·superlu 만)에서 분해 메모리 초과(예상 6.2 GB)로 못 풂 → H5(15,477
  노드) ① same 스터디(엔트리 8·지그 2방식·상위 3 + 기준 = 묶음 4 × 출처 3)로 실측: 씬 묶음 33.4 MB(96 씬), BD_POST 73.4 → 93.7 s(+20.3 s,
  사이드카 seconds 21.2 s), 분해 수 같음(12). 노드당 1,920 B + 씬당 ≈ 38 KB → 10만 노드 ≈ 196 MB(계약 추정 195 MB 와 일치), 시간은 씬당
  0.22 s(H5) → 10만 노드 약 1.5~2 s/씬(후진대입·k-means 군집 선형 증가 가정) ≈ 2.5~3 분(계약 추정 0.5~1.5 분보다 김 — 지그 BC 풀이 0.18 s/씬
  ·군집 0.044 s/씬이 큼). 현장 실측 E-0251-9 로 확정 필요.
- VL-C1-12 (§2.5·§7.2 BD_POST 다시 실행) 옛 `post/view3d_scene` 은 백업(_backup/<ts>)하지 않고 지운 뒤 새로 씀 — 보기 파생 자료(같은 실행이
  다시 만듦)이고 크기가 기존 3D 의 약 3배라 백업이 쌓이면 디스크 부담(기존 `_prune_view3d_backups` 는 post/view3d 백업만 정리). 쓰기는 모두
  `c.writer.guard` 안(스터디 post/).
