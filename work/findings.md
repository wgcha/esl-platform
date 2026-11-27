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

# v0.25.2 C1 findings — 계약 보정·메인 결정 필요(esl_tstar_manual_jig_force.md 개정 1, TM-C1-n)

- TM-C1-1 (§2.4·§11) 경계력 보충 병합 `esl/io/bforce_ondemand.py`(§11 소유표에 없음 — 코어라 C1)가 done.json mode `bf_only` 만 받음 →
  "fr_only 와 같은 실행에서 함께 읽은 경계력이 보충에서 '있음'" 이 되려면 `fr_only` 도 받아야 함. 최소 해석: `FILL_MODES = (bf_only,
  fr_only)` + frame_times 가 dict(`{"<f>": t}` — fr_only 형식)여도 읽음. 옛 bf_only 경로 불변(기존 시험 통과).
- TM-C1-2 (§4.1·§6.3·§8.2) `counts` 는 "새 결과만" 인데 v0.25.2 새 결과를 가리는 표식이 계약에 없음. ①②③ base 모드는 스냅샷 jig_grid
  블록을 무시해야 하는 v0.24.8 불변(test_base_mode_ignores_grid)이 있어, 표식 = **격자 지그 ∧ 스냅샷 rank.jig_grid 에 tie_force 키**
  (`stages._jg_force_on` + `_jg_kind == grid`)일 때만 `counts`·`n_ref` 를 씀. 그 밖 결과(①②③·옛 ④)는 화면이 n_failed + COUNT_LABELS
  거울로 같은 표시를 계산(계약 §8.2 C 의 옛 결과 경로). 보고서 개수 줄은 모든 결과에 `count_items` 로 덧붙임(덧붙일 키 없으면 글자 불변).
- TM-C1-3 (§10.2-14 ②) 합성 세계의 Case 맞춤 하중은 자기평형(ΣF ≈ 0)이라 "반력 합력 차 / 반력 합력" 은 0/0 에 가까움 → 분모를
  옮기지 않은 형상의 반력 크기 합 Σ‖R_n‖ 로(스프링 방식은 반력 = 구속 반력 + 스프링 힘 f_s·d̂). 측정(구멍 반지름 = 와셔 9 + snap 3.75
  + 요소 3 + δ, 강제 거리 14.1~14.4·18.7~19.1 mm): ① 평형 F ≤ 2e-13·M ≤ 6e-14 ② ΔΣR ≤ 2.5e-11 ③ ΔM ≤ 4e-7 ≪ 한계 Σ|R_q|·δ_q(1.5e4~1.6e5)
  ④ C_mix 차(옮기지 않은 판 대비): 강제 변위 δ3 −272.8 %·δ8 −361.7 %, 스프링 δ3 −40.2 %·δ8 −52.2 %. **강제 변위 방식은 멀리 옮긴
  지지에서 C_mix 가 크게 바뀜**(구멍 + 지지 이동 효과 섞임) — 참고용 표시가 필요한 근거. 1 % 초안 문턱(②)은 평형 때문에 항상 성립.
- TM-C1-4 (§10.2-14) "체결부 면을 δ 옮긴 판" 을 평판 세계에서 만들 수 없어(판이 어디나 면이라 band 가 잡음) 볼트 둘레 요소를 뺀 판
  (구멍 = snap 밖)으로 대신함. δ = 구멍 반지름 추가분, 실제 옮긴 거리는 시험 출력(GRIDFORCE phys)에 기록. V-0252-15(50·200 mm)는
  "좌표 통째 어긋남" 꼴(형상 A 좌표를 판 법선으로 δ) — 전부 force·dist ∈ [δ, √(δ²+(2h)²)]·한도 20 mm = 전부 miss·형상 제외 확인.
- TM-C1-5 (§4.3) marks.x(Case 체결부 중심 — 형상 전역 좌표): A 좌표 → 형상 좌표 = 가장 가까운 형상 노드 n0 기준 X_S[n0] + (x_A −
  ŷ[n0])·R_plᵀ(배치가 강체면 정확, frame 정규화 배치는 근사). 3D 선 끝점용으로 marks(force)에 `to`(붙인 노드 면적 가중 중심 — 형상
  전역) 키를 더함(계약 키 목록 밖 추가 — F1 선 그리기용).
- TM-C1-6 (§3.1) tie_force.normal_deg 90 = "조건 없음" 을 _proj_ok(cos 90° ≈ 6e-17)로 하면 법선 0 노드(고립)를 거름 → normal_deg ≥ 90 이면
  법선 판정을 아예 하지 않음(< 90 일 때만 band 와 같은 _proj_ok).
- TM-C1-7 (§2.3) D 안 비후보 프레임(--frame)의 옛 레코드(elem_id·value null)가 직접 고른 t* 레코드(frame_point 값 + manual)로 바뀜(계약
  의도). 후보 ∧ D = 옛 레코드 그대로(골든 pipe_cand). 후보인데 D 밖(채운 프레임) = 직접 고른 t* 레코드(D 시각이 없어 옛 레코드 불가).
- TM-C1-8 (§2.5) 경고 4종 중 TSTAR_MANUAL_LOW 만 run.json 단계 warnings(경고 수준), 나머지(정보)는 echo + esl_summary.tstar_manual.notes
  [{code, level, text}]. ESL 단계 요약(run.json stages.esl.summary)에도 tstar_manual(notes 제외) — B1 작업 결과용.
- TM-C1-9 (§2.4) TCL fr_only 의 변형률 출처 고정 = 요청 키 `strain_sources <추출 source 하나>`(frame_fill.request_keys) 또는 옛
  `strain_type`(Max_Strain 고정). 덤프 source 가 골라지면 INPUT_INVALID(판정 표 행 3 이 먼저 막음). done.json frame_times = {"<f>": t}.
  fr_only 블록은 `# >>> v0.25.2 fr_only` 표식 구간 — 빼면 393789a8 파일과 같은 글자(정적 시험 sha 고정).
- TM-C1-10 (#96 재현 합성) 비대칭으로 구멍을 내면 PCA frame 이 기울어 SHAPE_SIZE_MISMATCH(6 % > 5 %)가 먼저 빼므로 네 모서리 볼트
  자리(대칭)에 구멍. 두 장 형상은 band 가 두 장 다 잡아 잡힌 면적비 = 2.0(두께 두 번 — 정황이 JIG_GRID_AREA_RATIO 경계값에도 드러남).
  요소 수 비 1.96(#96 1.97). 강제 켬 결과: 4/6 강제, 거리 7.14 mm, 참고용, score 0.971.
- TM-C1-11 (§4.3, 범위 판단) v0.25.1 씬 3D 묶음(post/view3d_scene — `_scn_jig_grid_p`)의 지지 행에는 via·tie_marks 를 넣지 않음(계약은
  지그 응답 3D manifest 만 지정). 필요하면 후속.
- TM-C1-12 (§9 성능 실측 — 합성) 형상 노드 112,601(h 0.5 mm 판)·묶음 6: 구멍 4곳 강제 0.63 s · 30 mm 어긋남 전부 강제 0.81 s · 200 mm 0.66→
  1.66 s(형상 전체 capture). 먼 묶음은 완결 조건(k 번째 이웃 거리 > 고른 거리 + L_q + ρ) 때문에 KD 질의 반경이 옮긴 거리만큼 커져 묶음당
  비용이 거리에 비례(정확 거리 메모·묶음 중심 1점 질의·첫 k = 면적 어림 ×2 로 줄임). 228 묶음이 모두 수백 mm 어긋난 극단은 형상당 수십 초
  가능 — 현장 E-0252-10 에서 실측 필요.
