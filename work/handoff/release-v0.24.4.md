# 이어받기 — release/v0.24.4 P2c(S2 스터디 지그 3방식) + P3 A3(load_source 코어)

- 계약: docs/contracts/esl_jig_case.md §7(P2c)·§9(P3)·§13 V-0244-JIG-6·11·14. 범위 = esl/doe/stages.py·tests/doe/test_jig_methods.py(새)·
  esl/library/source_load.py(새)·esl/opt/target.py. worker/**·backend/**·frontend/** 금지(W3+B3 = wip/v0.24.4-p3wb 3ebbf843, C3 따로).
- 시험 환경: /tmp/rdenv_p2c.sh(= rdenv_main, REPO_ROOT 교체). PG 는 pytest 와 같은 백그라운드 명령 안에서 켤 것.

## 진행
1. [x] stages 지그 구조: _jig_stage(공유 단계 — TIE_DOFS 열로 분해 고름: xyz·면내 없음 = 옛 jig.factor, 그 밖 jig_bc.factorize)
   + _jig_fit_legacy(옛 맞춤·파일) = _jig_baseline(옛 흐름 그대로, 골든 41 파일 통과). _jig_modes 는 BcSolve(fixed_t) 면 jig_bc.modes.
2. [x] 새 스냅샷(_jig_plan: 스냅샷 rank.jig 원본 tie_dofs·methods, 키 없음 = LEGACY_ABSENT, load_source 지그 계열 방식 보장):
   _jig_apply_multi → 베이스라인 _jig_methods_base(방식마다 격리, 옛 경로 방식 먼저) · 안 _jig_design_multi(패턴 sha 묶음 분해 1회).
   prep/<src>.{json,npz}(npz = 옛 jig.npz 이름 + bc 패턴·bc_val/sp_g (K×행)·Cmix_ref·E_ref·WF_ref·Wg_ref·method·tie_dofs·pattern_sha).
   per_esl 키 = C_<pe>·umax_<pe>·WF_<pe>·Wg_<pe>(·umax_<pe>_ev), pe = RANK_SOURCES need 열(jig·jd·js). 옛 경로 fixed = C_jig·umax_jig.
   d000 result.json sm.jig += methods{src: {status, code}}(새 스냅샷만).
3. [x] post: _rank_views 행마다 need(옛 _jig_ref 조건과 같음), _jig_extras 는 고정 실패여도 다른 방식 준비면 보기, _jig_post 블록 +
   tie_dofs·methods(새 스냅샷만), ranking.csv 끝 열 C_jd·umax_jd·C_js·umax_js(_jig_csv_arg), 지그 3D·진단 = 저장 BC 재풀이(새 npz).
4. [x] tests/doe/test_jig_stages.py jcfg() = 옛 키 집합(새 키 제외 — 이 파일들은 v0.23 지그 시험, 의도 변경 §12-3).
5. [ ] tests/doe/test_jig_methods.py(합성 비드 판 ×0.5·1·1.5 Π 단조·바이트·k 재사용·격리·CSV·보기)
6. [ ] A3: esl/library/source_load.py find(key, meta, raw) → (dir, doc, f, bc, why) — bc_node·sp_node = 노드 ID(W3 가정),
   stages._ns_find 위임(바이트 동일), esl/opt/target.py 지그 지지, stages load_source → metric(_sm_post·bd_post).
7. [ ] 전체 pytest, 계약 부록 A.5, decisions, 커밋.
