# 이어받기 — release/v0.24.4 P2a (A2a 코어 공용)

- 계약: docs/contracts/esl_jig_case.md (계약 커밋 413620c1). 범위 = P2a 만(P2b·P2c·P3 밖).
- 시험 환경: /tmp/rdenv_v0244.sh (REPO_ROOT=/home/claude/wt_v0244), PG 54329 — PG 는 시험과 **같은 백그라운드 명령 안에서** 띄울 것
  (따로 띄운 PG 프로세스가 도중에 사라짐).

## 진행
1. [x] 골든 먼저 — tests/doe/test_jig_move.py + tests/fixtures/jig_case/golden_v0243.json (study 41 파일, case 36 파일, 413620c1 코드로 기록)
2. [x] 모듈 이동(esl/mech/jig.py·esl/rad/surface.py·esl/rad/solid_faces.py·esl/io/fixed_scan.py·esl/io/messages.py + 심 = sys.modules 별칭) — 골든 통과
3. [x] ShellModel 확장(FactorizedSolve.solve(F, values)·factorize_bc·BcSolve) + esl/mech/jig_bc.py
4. [x] 시험 tests/mech/test_shell_bc.py(10)·tests/mech/test_jig_bc.py(20)·tests/doe/test_jig_move.py(6)
5. [x] 전체 pytest tests/: 1506 passed · 192 skipped · 3 failed(허용 3건만) — 이후 mixed-rank 시험 1개 추가(통과)

## P2b 가 쓸 API (esl/mech/jig_bc.py — 계약 §4.2 + 추가)
- 표: METHODS·TIE_DOFS·LEGACY_ABSENT·check_plan()·factor_groups(methods)·tie_dofs_of(cfg)·methods_of(cfg)·check_cfg(cfg)
- 공유: tie_rows(mesh, J, tie_dofs, *, kink_deg, valid_elem=None) → {node, dir, normals}
        aux_rows(X0, sup321, tie, tie_dofs, *, dup_deg) → {node, dir, rows, nodes, n_dup, plane}
        node_frames(mesh, nodes, *, kink_deg, valid_elem=None) · aux321_inplane(X0, sup321, tie_dirs, *, dup_deg)
- 방식: target(frame, X0, u_part, J, fit) → {u_tgt, tie_rel, rot_deg} · build_bc(METHODS[m], tie, aux, u_tgt, *, k=None) → BC
        spring_k(K0(ShellModel|희소), tie, *, mode, alpha=1.0, value=None) · factorize(sm, BC) → SpcSolve|BcSolve
        modes(h, weights, n_modes, rho_t, *, sigma=0, tol, maxiter) → {phi(전역), lam, hz, g, …}
        run_method(h, basis, U, u_tgt, BC, fit, weights, *, jig_idx, ridge, w_inplane, reg_force, reg_modes, active_tol, nomodes=True)
          → {a, F, u, u_fit, u_g, R, rc, fs, fit, report, energy, aux_reaction_rel}
        respond(h, F, BC) → {u, R, rc, fs, energy} · solve(h, F, BC, *, homogeneous=False) · needs_ground(BC)
        flags(method, report, *, aux_rel, th) → {warnings, info, limits}
- 지표: mixed_compliance(F, u, BC, rc, fs) → {C_mix, E, W_F, W_g, R_sum} · score(C_d, C_0, E_0) · per_esl_C(C_d, C_0, E_0)
        aux_reaction_rel(F, BC, rc) · rigid_free(X0, components(mesh), BC) → {rigid_free, per_comp}
- 저장: save_bc(BC) → 배열 dict · load_bc(npz) · pattern_sha(BC) · BC_KEYS
- 쉘: ShellModel.factorize_bc((node, dir), *, springs=(node, dir, k)) → BcSolve; BcSolve.solve(F, values=None, ground=None)
      → (u, R, rc, fs); K_t·free_t·fixed_t·to_local·to_global·solve_t. FactorizedSolve.solve(F, values=None).
- 기타: esl.mech.jig.JIG_DEFAULTS·JIG_NEW_KEYS·HASH_EXCLUDE_V0244, esl.io.messages.text(code, **kw)·template·messages,
        esl.io.fixed_scan.read_fixed·FIXED_KINDS·SCAN_JSON·FIXED_NPZ·read_json_limited, esl.rad.surface.other_surfaces.

## 결정·계약과 다른 점(반환에 명시)
- DEFAULTS["rank"]["jig"] 는 JIG_DEFAULTS 를 import 하지 않고 **거울**(같은 이름·값 시험) — esl.doe 가 scipy 를 끌어오지 않게(백엔드 API
  프로세스는 지금 scipy 를 안 씀). 새 키(JIG_NEW_KEYS)는 DEFAULTS·pydantic BeadDoeRankJigCfg·yaml 2·backend 시험 RANK_DEFAULT 에 B2 가
  함께 더함(지금 DEFAULTS 에 더하면 backend test_rank_defaults_mirror 가 깨짐).
- HASH_EXCLUDE 확장은 P2c(기존 test_hash_view_drops_thresholds 기대값) — 값은 jig.HASH_EXCLUDE_V0244.
- 심 = 모듈 별칭(esl.doe.jig is esl.mech.jig) — monkeypatch 시험 무수정 통과.
- 분해 경로는 자료로 고름: 축 방향 구속만·스프링 없음 = SpcSolve(옛 sm.factorize), 그 밖 factorize_bc. (계약 "normal 은 세 방식 모두
  factorize_bc" — 축 정렬 평판 normal 은 spc 경로, 해는 비트 동일 확인.)
- esl.doe.paicad_io 가 esl.io.fixed_scan 을 import → esl/io/__init__(results_csv → esl.mech) 때문에 paicad_io import 가 scipy 를 끌어옴
  (백엔드는 doe_select 지연 import 경로에서만).
- 발견: k_auto(α=1) = 노드 자기 강성 → 패널 전체 강성보다 훨씬 커서 spring ≈ prescribed(‖Δu‖/‖u‖ 2.4e-5). α ≲ 1e-2 에서야 차이(Q-JIGC-1).
- 발견: 평판(선형) 조립에서는 normal ≈ translation(굽힘·막 분리), 곡면에서 normal ≫ translation.
