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

# v0.24.9 C1 findings — 계약 보정 필요(esl_bead_pos_u.md)

- PU-C1-1 (§3·§5-13) U 기저는 선택 단위(select/<sha12>/basis.npz·basis.bin·basis.json·derived.npz)에 U 가능한 비드마다 들어간다(프런트 3D
  미리보기 basis.bin 이 U 를 보여야 하므로 — §4). 그래서 pos_u 블록이 있는 스냅샷은 U 변수 0개여도 이 선택 파일들과 params.json·derived.json
  이 달라진다(basis.json cfg_sha256 은 §3 `_sel_cfg_sha += pos_u` 로도 달라짐). 안·순위·결과·prep·3D·done input_sha256 은 골든과 같음(시험
  test_pos_u_golden — 선택 파일은 pos_u 키·U 행을 뺀 내용이 같은 세계와 같음). 계약 §5-13 문구를 "선택 단위 파일 + params.json" 으로 보정 필요.
- PU-C1-2 (§1.1·§1.2) graph.json segments 에 `closed` 필드가 없다 → U_CLOSED 판정 = 패키지 `morph.u_closed`(접합 없음 ∧ 골격 끝-시작 ≤ 2h).
- PU-C1-3 (§1.3) params U 행 dir{xi, eta} 는 그래프 판 평면 frame(e1·e2) 성분 — params_rows_v2 에는 ESL frame 이 없음. dir_text 의 곡선 판정 =
  골격 누적 회전 ≥ 30°(section.U_CURVE_DEG, 계약에 기준 없음).
- PU-C1-4 (§1.1) "W 규칙 그대로" 로는 H6 기본 범위 끝에서 뒤집힘(최대 86)·오목·가드 cascade(가드 노드 60 %·left 334)가 났다. U 는 W 의 2배
  이동(전 단면)이라 다음 장치로 바꿈(U_RULES 1 에 고정, D·W·DF·W1 바이트 불변):
  (a) 방향장 = 비드 골격 꼭짓점 왼쪽 법선을 가우스 평활(ρ_s = max(3h, 4·ext), 세그먼트 넘어) → 노드 가우스 평활(ρ = max(3h, ext)),
  (b) 여러 세그먼트 비드는 골격 진행 방향을 사슬로 통일(u_orient — H5 링 한 변이 반대 방향 세그먼트로 저장돼 서로 마주 움직였음),
  (c) 띠 = 가우스 혼합(최근접 기준 상대 거리) + 다른 형상 근처는 간격 비례 d_o/(d_o+d_e) 로 자름, 장애물 = 다른 구역·판 외곽·fixed·tie·
      묶인 섬, (d) 이웃 간격 κ = 이동 방향 ±45° 안 장애물까지 거리·부호별 끝(lo/hi)·램프 φ 반영, 침식 후 평활(raw 넘지 않음),
  (e) 품질 가드 = DF 기준(넓이 비·뒤집힘·Jacobian·오목·range guard 품질) 그대로, 줄임만 부드러운 bump(c ×= 1−0.2·exp(−(d/ρ)²), 지지 2ρ),
  (f) 자식·소유 섬 = 방향장 따라 이동(직선 = 강체), 걸친 섬 = BG-D-27 섬 규칙, (g) 조화 확장에서 J 는 Dirichlet 0 아님(φ 가 0 으로).
- PU-C1-5 (§1.3-4) 선택 기저가 선택 단위로 캐시되므로 BD_MATRIX guard_selection 은 "켜진 U" 가 아니라 U 행 전부를 점검(이후 행렬 재사용).
- PU-C1-6 (§1.2 U_HELD) tie 변위는 ψ = 0(ring 안)으로 구조적으로 0 — basis 때 tie_max > 1e-6 이면 BG_ACHIEVED_MISMATCH(행 제거 대신 오류).
  hold 비율 판정은 derive 에서 기하로(입구 노드 중 fixed∪tie 로부터 ring+blend 안 비율 > hold_frac_max).
- PU-C1-7 (§2.2 PU-16) spatial d000 = node 경로(_lt_eval 진단 포함) 1회 + spatial 1회 — 분해 공유 안 함(풀이 수 node 1 + spatial 1 은 같음).
- PU-C1-8 (§4·§5-13) matrix.json load_follow 는 pos_u 블록 있는 스냅샷이면 "node" 도 씀(§4 표). §5-13 "산출물 바이트 동일" 과 충돌.
- PU-C1-9 (§4) derive_v2 beads[].u_reason = {code, text}(U_OFF·pos_u 없음 = 키 없음), params.json beads[].u_reason = {code}.
- PU-C1-10 (§3) 하중 전달 스냅샷(doe.load_transfer) 없는 스터디의 spatial 셀 전달은 설정 load_transfer(work·cell_min_mm)로(_lt_method 대체).
