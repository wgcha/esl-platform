# Handoff — feat/v0180-frontend (v0.18.0 ③ select_base "step" UI)

Worktree: /tmp/claude-0/-home-claude/b31e30b1-6347-515a-8f7b-a9260713e285/scratchpad/wt-fe180 (base 134ecfb). frontend/node_modules = symlink to main checkout (do not commit).

## Done (wip commit 1)
- types.ts: DoeSelectBase += step, DoeFixedXferMethod, DoeRegionMode, DoePrepMesh, DoePrepFixedXfer, DoePrepRegion, prep.fixed.xfer/region, settings scenarios.select_step + select.step_graph, plan fixed[].src + region_ab (보강, not in contract §4.2).
- api/doe.ts: radioRequest step → select+step, studyRadio, radioBase, LEGACY_STEP_LABEL, selectSubBlocked step (gmsh), studyScenarioLabel (③ select / legacy), loadSelectAuto accepts fixed-only seed (seedHasFixed), STEP_GRAPH_*/FIXED_XFER_* texts, xferText, regionText, meshMethodName, STEP_PREP_CODES, stepPrepGroups.
- PartView: layer "region" (주 시트 영역), fixed xfer marker; adapters selectPlan/selectViewData stepBase.
- BeadSelectCard: fixed-only seed, StepInfoBar (3 MsgFolds: bs-step-tria / bs-step-xfer / bs-step-region).
- DoeInputs: step base fields (STEP 필수, 인치, t/E/ν, mesh note, advanced mesh mode), summary chip.
- DoeStudy: ③ radio → select step, request body (no part_title — contract SG-D-3 forbids), detail summary, step info, legacy label.

## Todo
- mocks: settings select_step/step_graph, checkSelect step, create, sync prep (mesh/fixed.xfer/region/warnings), select/auto for step, plan-view region_ab + fixed src, demoStepSel (doe-15 auto saved, doe-16 manual).
- fix doe.test.tsx ③ new-study test (now select step — props default from check), 1 other failing test.
- new test src/__tests__/doe_step_graph.test.tsx; typecheck, build, screenshots → /home/claude/screens/v0180/ (script screenshots-v0180.mjs).
- final: remove this file, push, remove worktree.
