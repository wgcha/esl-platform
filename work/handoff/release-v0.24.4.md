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
5. [x] tests/doe/test_jig_methods.py 8(비드 ×0.5·1·1.5 Π 단조 — s fixed 2.445·1·0.597, prescribed 2.396·1·0.608, spring 2.391·1·0.610,
   스터디 ≈ 2.2 s; 파일·보기·CSV; 분해 공유 = 묶음 2 × (1 + 안 수) + 진단·3D, spring_k 1회; translation 새 스냅샷 fixed = 옛 바이트;
   spring 베이스라인·안 묶음 실패 격리; load_source jig_disp → metric jd·bforce 미준비 → LOAD_SOURCE_FALLBACK). rank._ALT_KEYS += C_jd·C_js.
6. [x] A3: esl/library/source_load.py find(key, meta, raw, *, code, name, load) → (dir, doc, f, bc, why) — bc_node·sp_node = 노드 ID
   (W3 3ebbf843 가정과 같음), summary_for_mapping(entry, f). stages._ns_find 위임(문구 같음). esl/opt/target.py source_entry_load·
   jig_support_reason·jig_supports·source_supports. stages _sm_post load_source·metric_default, _ls_rank_input(노드 힘 사이드카 합침·
   준비 안 됨 = LOAD_SOURCE_FALLBACK), result.json load_source·metric_default(새 스냅샷만), 보고서 SM_METRIC_KO jd·js·bf·fi.
   tests/opt/test_load_source.py 8.
7. [ ] 전체 pytest, 계약 부록 A.5, decisions, 커밋.
