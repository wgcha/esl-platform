# handoff — release v0.20.0 마무리 (완료 시 삭제)

기준: 7acf788(계약 + v200-core·be·fe 병합). 목표: 결정 A(강성 지표는 같은 메시 안에서만) + 통합 문서 + 전체 시험.

## 설계(결정 A)
- 계획 표 sm 열: case_once base/(I,I)/rank metric; bmesh_once·step_once sm_ref base(베이스라인 work 하중 solve 해), (I,I), rank metric;
  step_per_design·compare_per_shape sm_ref none, sm_disp (none,none), sm_rank solve(다른 메시 — SM_CROSS_MESH).
- 새 열 sm_rank: metric | solve. post: rank(metric = 계획 sm_rank 따라) → result metric_effective·cross_mesh, 경고 SM_CROSS_MESH.
- base: K_A = K_t(같은 Ω) → 베이스라인 ρ = 1.
- build_disp·a_direct 지표 경로: 계획 표에서 비활성(코드·시험 유지).

## 진행
- [x] 코어  - [x] 코어 시험  - [x] backend  - [x] frontend  - [x] 문서·버전(AGENTS.md 신규)  - [ ] test-all  - [x] regress(none·cad·auto·sel·selreg = main 동일)  - [ ] 최종 커밋·push
