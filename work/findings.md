# physicsai-platform 벤치마킹 결과 (2026-10-19, 원본: /home/claude/wgcha/physicsai-platform)

1. 설정: config/platform.example.yaml (+ platform.yaml git 제외). 로더 backend/physicsai_core/config.py (load_config/validate_settings/redacted_settings). profile dev|prod, PHYSICSAI_CONFIG/PHYSICSAI_PROFILE env. DB는 database.url_env(env 변수명만).
2. 백엔드: FastAPI + SQLAlchemy Core(psycopg3, PG). main.py create_app 접두 /physicsai/api. routers → services → physicsai_core/db/repositories. Alembic migrations.
3. 워커: DB 테이블 큐, worker_slot CAS lease(claim_slot/reap_expired). worker/__main__.py(lockfile, alembic head 검사), runtime.py, executor.py(step 체인, heartbeat). state_machine.py(T1~T16), job_types.py.
4. HyperView: TCL은 저장소 밖(resources.*_tcl 경로 설정). commands.contour_preview = `hw -clientconfig hwpost.dat -b -tcl ...` → worker steps/predict.py.
5. 외부 실행: physicsai_core/commands.py(render_argv, EXECUTABLE_PLACEHOLDERS 허용목록) → executor.run_local → limiter(windows_job/posix/null), shell=False. OptiStruct 래퍼 없음.
6. 프런트: React18+Vite5+TS, router base /physicsai/, UI킷 없음(styles.css, components/ui.tsx, Chart.tsx). 단계 /p/:projectId/s/:studyId/stage/:n, StageStepper/TopBar/RightPanel.
7. 대시보드 연동: 같은 origin 하위 경로 + 세션쿠키 analysis_canvas_session을 auth.py DashboardClient가 /api/auth/me, /api/projects로 검증. TopBar "대시보드로"(href="/"). 대시보드 측 등록은 외부.
- 규칙: docs/contracts/platform.md(계약 원본), AGENTS.md(하드코딩 금지, shell=False, pickle 금지, 업로드 엔드포인트 금지).
