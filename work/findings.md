# physicsai-platform 벤치마킹 결과 (2026-10-19, 원본: /home/claude/wgcha/physicsai-platform)

1. 설정: config/platform.example.yaml (+ platform.yaml git 제외). 로더 backend/physicsai_core/config.py (load_config/validate_settings/redacted_settings). profile dev|prod, PHYSICSAI_CONFIG/PHYSICSAI_PROFILE env. DB는 database.url_env(env 변수명만).
2. 백엔드: FastAPI + SQLAlchemy Core(psycopg3, PG). main.py create_app 접두 /physicsai/api. routers → services → physicsai_core/db/repositories. Alembic migrations.
3. 워커: DB 테이블 큐, worker_slot CAS lease(claim_slot/reap_expired). worker/__main__.py(lockfile, alembic head 검사), runtime.py, executor.py(step 체인, heartbeat). state_machine.py(T1~T16), job_types.py.
4. HyperView: TCL은 저장소 밖(resources.*_tcl 경로 설정). commands.contour_preview = `hw -clientconfig hwpost.dat -b -tcl ...` → worker steps/predict.py.
5. 외부 실행: physicsai_core/commands.py(render_argv, EXECUTABLE_PLACEHOLDERS 허용목록) → executor.run_local → limiter(windows_job/posix/null), shell=False. OptiStruct 래퍼 없음.
6. 프런트: React18+Vite5+TS, router base /physicsai/, UI킷 없음(styles.css, components/ui.tsx, Chart.tsx). 단계 /p/:projectId/s/:studyId/stage/:n, StageStepper/TopBar/RightPanel.
7. 대시보드 연동: 같은 origin 하위 경로 + 세션쿠키 analysis_canvas_session을 auth.py DashboardClient가 /api/auth/me, /api/projects로 검증. TopBar "대시보드로"(href="/"). 대시보드 측 등록은 외부.
- 규칙: docs/contracts/platform.md(계약 원본), AGENTS.md(하드코딩 금지, shell=False, pickle 금지, 업로드 엔드포인트 금지).

# v0.24.7 DM 구현 발견 (2026-11-25, 지휘 세션)

## 계약 보정 필요
- DM-C1-1 `packages/beadgraph/src/beadgraph/morph.py` `_one_df`(§1.2.1 벽·입구 행): 자기 interior 골격 투영이 없는 열(세그먼트 끝·고리 모서리·접합 옆)은 최근접 깊이면 가장자리까지 현(chord)으로 r 을 재는데, 깊이면 가장자리가 접합 구역에서 끝나면 r 이 4 배 이상(합성 고리 a: r 4.26 → 입구 12 mm 이동, 뒤집힘 6)으로 튄다. 보정: 그런 열의 r 을 interior 입구 열 r 최대값(벽은 ×(1 − t))으로 자름(`info.chord_capped_n`). 계약 §1.2.1 표에 "현 방향 열 r ≤ interior 입구 r 최대" 1줄 추가 필요.
- DM-C1-2 H5 네트워크(고리+T) DF +2 mm(공칭 8): 부모 판 띠 2요소 뒤집힘 — 서로 마주 보는 입구 선 사이 20 mm 판 띠에서 띠 규칙(최근접 E 복사, §1.2.1 "W 블록 그대로")이 이등분선에서 불연속. 계약 §8-29 "네트워크 뒤집힘 0" 불충족(측정값: inverted 2, ΔD −2 는 0). 허용 오차 완화 안 함 — 시험 `packages/beadgraph/tests/test_one_side.py::test_df_network_and_area_v29` xfail(strict). 보정안: DF·W1 띠만 최근접 복사 대신 반경 R_w 안 E 의 역거리 가중(연속) — DF_RULES 1 안에서 결정 필요(사용자/상위 세션).
- DM-C1-3 §8-18(c) "판 외곽을 따라가는 채널": 분류기(RULES 1)는 깊이면이 판 외곽에 닿으면 floor 를 area 로 분류(골격 없음) → one_side reason = AREA(W_AREA), W_ONE_SIDE_EDGE 는 합성으로 재현 안 됨. EDGE 판정은 `measure(edge_nodes=…)` 강제 마스크 단위 시험으로 대체.
- DM-C1-4 §2.1 feasible(그래프 floor_fixed)의 cot 는 계약상 DF info cot_med 이나 derive(API·params 행) 시점엔 기저가 없음 → `one_side` run/D(세그먼트 중앙값)로 추정해 feasible·D 행 section.cot_deg 에 씀. basis.json graph_vars[].section.cot_*_deg 는 DF info 값. 계약 §1.3·§2.1 에 "derive 단계 cot = one_side run/D" 1줄 필요.
- DM-C1-5 §4.4 W1 대칭 묶기의 "열린 쪽 방위 거울(cos 30°)" 검사는 미구현 — 종류 같음 + |W1_nom 차| ≤ 2·sym_tol 만(`bead_graph._tie_mixed`). n_out 평균 방위를 one_side 가 반환하지 않음.
- DM-C1-6 wall_no_entry_n = 비드 소유 벽 노드 중 J(바깥 요소 공유) 수로 근사(윗단 = J 판정 대신).
