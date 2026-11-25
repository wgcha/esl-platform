# 핸드오프 release/v0.24.7 (지휘 세션 → 다음 세션)

## 끝난 일(커밋)
- 22e7a4b3 골든(main 코드로 기록 — 다시 기록 금지): tests/doe/golden_v0247_c1/{golden.py,golden.json}, tests/doe/test_depth_section_golden.py (키 없음·entry_fixed 명시 × graph/elems × legacy/rules + 패키지 D·W 기저 60개) — 9 pass
- ddfb12ea 패키지 beadgraph 1.2.0: kind DF·W1, one_side(oneside.py), OUTPUT_VERSION 1.1.0, DF_RULES·W1_RULES, _band·_islands 공용, checks DF·W1, synth_oneside.py, selftest V-0247-DM, README, tests/test_one_side.py (78 pass, 1 xfail strict = DM-C1-2)
- b8d90b1a esl: esl/morph/section.py, bead_graph floor_fixed(derive_obj_v2(depth_section=, section_rules=), _floor_fixed_bead, _tie_mixed, w_reason_of, params 행 section·w_side, basis_v2 DF/W1), stages(_ds, 재사용 조건, basis.json 키, graph_vars.section, params.json beads.w_reason, _sel_cfg_sha hash_view), DEFAULTS, doe_messages.json
- (이번 커밋) graph_section ds_dD(DM-12 그림 교정), tests/morph/test_section.py(25), tests/doe/test_depth_section.py(4), config yaml 2개 + pydantic BeadDoeCfg.depth_section·depth_section_rules(_fill_missing)

## 남은 일 (순서)
### C1 나머지
1. elems floor_fixed(§1.2.2·§1.3): `bead_select.derive_obj(…, depth_section=)` → 1단·닫힌 경계·폭 있음·θ(section.cot_from_run(run_med = bead_select.py:1217-1226 값))이면 B'_D = section.compose(B_D, [(B_W(f=0), 2cot)]) (`_width_basis` floor_follow 0), 아니면 DS_FALLBACK{W_OPEN_BOUNDARY|W_WIDTH_UNDEFINED|SELECT_MULTI_TIER|THETA_UNMEASURED}, DS_THETA_SPREAD; feasible open_cap(m=2); D 행 section; W 사유(src elems). stages BD_MATRIX 의 bsel.derive_obj 호출에 floor_fixed 만 키 전달(derive_obj_v2 안의 elems d1 호출도).
2. range_guard_table(…, depth_section=)(bead_graph.py ~1480~ `_candidate_bases`)·BD_LOADS·w_clamp: floor_fixed 후보 = DF + W1, 표 머리 cfg_sha·key += ds(floor_fixed 만). stages BD_LOADS 의 range_guard_table 호출에 floor_fixed 만 키.
3. paicad_io: floor_fixed 스냅샷이면 스터디 정보 DS_ENGINE_NATIVE 1개(계획 열 na), W_PAICAD_NONE 사유.
4. derive_v2(API 진입)에 depth_section·section_rules 통과 + doc["beads"][].w_reason{code,text}(옛 스터디도 w_reason_of).
5. 경고 보강: DS_HOLD_PINCH(info.hold_pinch_n > 0), DS_ONE_SIDE.steep_deg ← DF info steep_deg(basis 후), W1 그림 ds_dW(section.fig_ds_dW1 — 열린 쪽 방향 필요).
6. 시험 3(H6 ch1 DF), 4(elems), 6, 12(range_guard), 13, 17·27(비용), 22(ties), 30(평행 채널 — synth_oneside.parallel 있음).
### B1 (backend)
- schemas.py: DoeStudyIn.depth_section Literal|None, 복제 본문 모델 {title?, depth_section?}(extra 422), DoeStudyOut.inputs.depth_section·spec_prefill, DoeSettingsOut.depth_section, params 행 section·w_side, beads w_reason{code,text}
- services/doe.py create: select 시나리오 스냅샷 params.doe.depth_section(+rules) = 요청 or 설정(entry_fixed 면 키 생략 — BG-D-36 선례? 계약 §5 "entry_fixed 는 어떤 문서에도 키를 쓰지 않음"), clone(): section.clone_depth + spec_prefill(원 doe.spec) + DS_CLONE_NOTE; select 밖 depth_section 422 INVALID_PARAMS
- services/doe_select.py: derive 호출에 스냅샷 depth_section 통과, w_reason 응답
- openapi 재생성(scripts/dump_openapi.py), deploy/requirements.lock beadgraph==1.2.0, tests/deploy/test_bead_doe_deploy.py 판 대조, backend/tests/test_doe_v0247_*.py
### F1 (frontend) — 계약 §7 전부(라디오·복제 창·칩·W 사유 줄·W1 꼬리표·D 배지·SectionMini ds_dD), mock, vitest
### 통합
- 버전 0.24.7(VERSION·기존 표기 위치 전부 grep "0.24.6"), CHANGELOG [0.24.7](beadgraph 1.2.0 절), docs/manual/user.md·admin.md, docs/manual/field_check_v0247.md(§13 F-DM-1~5, #88 W 사유 서버 LLM 진단 질문), decisions·계약 구현 메모, findings DM-C1-1~6 반영, 핸드오프 삭제
- 전체 시험 순서(동시 금지): pytest tests/ → packages/beadgraph + selftest → backend → worker → vitest → typecheck·build·check:api·dump_openapi --check

## 시험 상태
- 패키지 78 pass/1 xfail, 골든 9 pass, section 25 pass, depth_section 4 pass. 전체 스위트 미실행.

## 다음 명령
- source /tmp/rdenv_v0247.sh (REPO_ROOT=/home/claude/wt_v0247, PYTHONPATH += packages/beadgraph/src)
- $PY -m pytest -q tests/doe/test_depth_section*.py tests/morph/test_section.py -p no:cacheprovider --basetemp=/tmp/bt_ds
