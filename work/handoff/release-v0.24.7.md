# 핸드오프 release/v0.24.7 (지휘 세션 → 다음 세션)

## 끝난 일(커밋)
- 22e7a4b3 골든(main 코드로 기록 — 다시 기록 금지): tests/doe/golden_v0247_c1/{golden.py,golden.json}, tests/doe/test_depth_section_golden.py (키 없음·entry_fixed 명시 × graph/elems × legacy/rules + 패키지 D·W 기저 60개) — 9 pass
- ddfb12ea 패키지 beadgraph 1.2.0: kind DF·W1, one_side(oneside.py), OUTPUT_VERSION 1.1.0, DF_RULES·W1_RULES, _band·_islands 공용, checks DF·W1, synth_oneside.py, selftest V-0247-DM, README, tests/test_one_side.py (78 pass, 1 xfail strict = DM-C1-2)
- b8d90b1a esl: esl/morph/section.py, bead_graph floor_fixed(derive_obj_v2(depth_section=, section_rules=), _floor_fixed_bead, _tie_mixed, w_reason_of, params 행 section·w_side, basis_v2 DF/W1), stages(_ds, 재사용 조건, basis.json 키, graph_vars.section, params.json beads.w_reason, _sel_cfg_sha hash_view), DEFAULTS, doe_messages.json
- (이번 커밋) graph_section ds_dD(DM-12 그림 교정), tests/morph/test_section.py(25), tests/doe/test_depth_section.py(4), config yaml 2개 + pydantic BeadDoeCfg.depth_section·depth_section_rules(_fill_missing)

## 남은 일 (순서)
### C1 — 완료(2026-11-25, 커밋 c5288343·3bf7c142·7a5d1fd6·(문서))
- 1~6 전부 구현·시험. DM-C1-1~6 계약 본문·§15 구현 메모·decisions DM-23~29 반영. findings 옮김.
- 남은 결정 1건: 시험 3 H6 ch1 DF +2 뒤집힘 68·entry_wave 0.472 mm(xfail strict, 계약 §15) — 메인/사용자.
- B1 에 필요: `bead_select.derive(…, depth_section=, section_rules=)`·`bead_graph.derive_v2(…, depth_section=, section_rules=)` 키(floor_fixed 스냅샷만 넘김), 응답 beads[].w_reason{code,text}(이미 코어가 채움), paicad `paicad_io.w_reasons(doc)`·`section_info(ds)`. DS_ONE_SIDE += open_side_deg, DS_HOLD_PINCH{bead, var, n}.
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
- 패키지 83 pass/2 skip/1 xfail(시험 3 ch1), selftest PASS, tests/doe/test_depth_section*·tests/morph 51 pass.

## 다음 명령
- source /tmp/rdenv_v0247.sh (REPO_ROOT=/home/claude/wt_v0247, PYTHONPATH += packages/beadgraph/src)
- $PY -m pytest -q tests/doe/test_depth_section*.py tests/morph/test_section.py -p no:cacheprovider --basetemp=/tmp/bt_ds
