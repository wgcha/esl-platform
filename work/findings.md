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
