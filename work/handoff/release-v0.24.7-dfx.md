# v0.24.7 DF 보강(dfx) 진행
- 기준선(1fb14fe4): H6 ch1 DF 범위 ±2.4 → ±2.4 뒤집힘 0/7, 오목 42/37, guard 610. 측정 스크립트 /tmp/dfx/meas.py
- [x] 1 띠 섬 = 장애물(DF·W1)  [x] 2 가드 오목(DF 래퍼 _df_entry_guard, 벽 노드 법선도)  [x] 3 entry_guard_left  [ ] 4 진단 키  [ ] 5 표  [ ] 계약·CHANGELOG  [ ] 전체 시험
- 1~3 후 H6 ch1 ±2.4 기저: 뒤집힘 0/0, 오목 0/0(현재 면·정지 법선 두 정의), left 0, 0.74 s. 패키지 87 pass, selftest PASS
- DM-35(추가 결정 필요했음): range guard 품질 기준(jac_min·tria_angle_min_deg 새 위반)을 DF 입구 가드에 넘김(DF 항목 guard_jac_min·guard_tri_angle_min_deg — esl _pkg_item, D.df_guard_q = range guard 켬일 때만). 없으면 rg floor D = [7.925,8.0] blocked(tri_angle −0.15 머리카락 요소). 있으면 [5.675, 8.0] limited(hi 8.0 = 91538 벽 바닥 quad jac 0.301 머리카락 — entry_fixed 도 hi 8.0 같은 요소).
- info entry_guard_left(뒤집힘·넓이·오목) / entry_guard_qual_left(품질 — 정보만)
