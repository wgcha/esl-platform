# 계약: ESL 기반 Ch/R 비드 형상 DOE (BEAD_DOE, v0.9.0)

- 상태: **확정** (2026-10-29, 사용자 확정 사항 + Q1~Q3 확정 §19). 미결 없음. **구현 반영(v0.9.0 통합, §21)** — 구현 중 정한 세부(점검 기록 위치·공칭 썸네일 경로·gmsh 키·격리·wheel 정규화·migration 0010 수정)는 본문에 반영하고 근거를 §21 에 둔다.
- 버전: **v0.9.0** (main 2341f4e = v0.8.0 기준).
- 근거 이슈: GitHub #37 "bead doe" — VoC "낙하해석 시간 때문에 Ch/R 비드 보완 소요 시간이 크고, 현재 강성해석은 낙하 하중 미반영이라 낙하 신뢰성과 갭". 대응 = ESL 기반 Ch/R 비드 형상 변화의 강성 개선 확인. 산출 = 낙하 하중을 고려해 강성이 좋아진 Ch/R 형상.
- 관계: v0.7.0 `esl_opt_run.md`(OPT_RUN, OptiStruct 비드 토포그래피)와 **별개 기능**. 하중 적용(S1 직접·S2 셀 매핑)·크기 규칙·3-2-1 자동 선택·목표 기준 정의·작업 실행 구조·`_opt` 쓰기 규칙을 **그대로 재사용**하고, 형상 엔진은 physicsai-platform 의 `paicad` 를 외부 명령으로 쓴다. 충돌 시 이 문서가 BEAD_DOE 범위에서 우선.
- ID 규칙: 결정 `BD-D-n`, 요구 `BD-n`, 시험 `V-BD-n`, 리스크 `R-BD-n`.

### 사용자 확정 (2026-10-29, 변경 금지)
1. **입력 CAD = 중립면(시트) STEP**. 형상 엔진 = physicsai-platform `packages/paicad`(읽기 전용, 수정 금지)를 **버전 고정 의존성**(≥ 0.14.0)으로 설치해 `paicad shell {fixed-scan, extract, tag, update, morph, check, run}` 과 `paicad shell view grid`(썸네일)를 쓴다. 노드·요소 ID 불변(/NODE 좌표만 모핑), tie·RBE2 고정 노드, 비드 파라미터 `<COMP>_BEAD_<D|U|V|W>_<k>`(깊이·위치 U/V·폭), feasible 범위, `GEOM_FEATURE_COLLISION`·`SHELL_FIXED_REGION_VIOLATION`. 배포 = 오프라인 설치(collect-offline 묶음에 paicad wheel·OCP·gmsh), 외부 명령은 워커만·shell=False·경로는 설정.
2. **시나리오 3가지**: ① 같은 모델(선택 ESL 의 Case rad Ch/R 메시 = 기준 메시, paicad 모핑, ESL 노드 직접 적용, 동일 모델 판정 = v0.7.0 S1 `topo_sha256`) ② 다른 모델 + B 메시(rad/inc) 있음(B 메시를 B STEP 으로 모핑, ESL 은 24×14 정규화 셀 매핑 — v0.7.0 S2 방식, 크기 = 같은 인치 + 치수 ±5 %) ③ 다른 모델 STEP 만(paicad update 로 안별 변형 시트 → 안마다 gmsh 쉘 메시(평균 요소 크기 설정, quad 위주) → 셀 매핑, 베이스라인도 같은 방식으로 메시해 비교 기준(메시 잡음 상쇄), 모핑 고정 노드 불필요).
3. **지지 = 3-2-1 공용(ESL 자기평형)**: ① 기준 ESL 지지 그대로, ②③ 정규화 좌표로 자동 선택(v0.7.0 S2 규칙).
4. **비드 파라미터**: paicad extract 가 인식한 비드별 D·U/V·W, 기본 범위 = feasible. 사용자는 포함 비드·파라미터·범위·DOE 방식(LHS·Halton·풀 팩토리얼)·안 수 선택. 실행 전 썸네일 격자 미리보기, 충돌·고정 침범 안은 스킵 표시.
5. **경계 매핑 경고(②③)**: A(ESL 원 모델) 체결 위치(RBE2·tie·3-2-1)를 정규화 좌표로 B 에 옮겨 B 체결 후보(구멍)와 비교 → 거리 > 설정값(예 10 mm) 경고(차단 아님), 평면도에 겹쳐 표시. A 하중 집중부가 B 의 체결부 없는 곳에 떨어지면 경고. 순위표·보고서에 경고 수.
6. **솔버 = 자체 선형 쉘 솔버만**(안마다 K 분해 1회 + 선택 ESL 전부 우변 `solve_many`). API 에 `solver` 필드(기본 `linear`, 다른 값 422)는 두되 **UI 에는 선택 칸 없음**(필수 UI 만). 탄소성은 후속(§18).
7. **지표**: 순위 = 컴플라이언스 절대 기준 min-max(선택 ESL 중 최악 — v0.7.0 OR-D-15 `abs` 와 같은 정의), 함께 표시 = 최대 변위·최대 변형률(선형)·베이스라인 대비 개선율. 결과 = 순위표·파라미터 민감도·3D 비교(기존 view3d 재사용)·최적 안 산출물(rad include 또는 메시 + paicad sample BREP/STEP)·보고서(방법·출처·한계).
8. UI 필수만, 2560×1440 기준(1920×1080 잘림·가로 스크롤 없음). 설정 키(하드코딩 금지). **입력 폴더 읽기만**, 쓰기는 `_doe/<id>/` 만.

## 0. 현황 조사 (main 2341f4e, v0.8.0)

| 항목 | 위치 | 현재 | 이 계약에서 |
|---|---|---|---|
| 동일 모델 판정 | `esl/opt/identity.py topo_sha256`, 0.5.5 규칙 | S1 용 | ① 그대로 |
| 크기 규칙 | `esl/opt/size.py check_entries·check_template·assert_ok` | ESL ±2 %, 템플릿 ±5 % | ②③ B 를 "템플릿" 자리로 그대로 |
| 대상 메시 | `esl/opt/target.py case_target·template_target·auto_supports·entry_load` | S1 rad 제자리 읽기, S2 셀 매핑 | ①② 그대로, ③ 안별 메시에 `entry_load` |
| 셀 매핑 | `esl/library/mapping.to_target`, `normalize.frame·cell_index` | 24×14 합력·합모멘트 + 평형 보정 | ②③ 그대로 |
| 쉘 솔버 | `esl/mech/shell.py ShellModel.factorize·solve_many·strains`, `mech/strain.eps_eq_max_layer` | 분해 1회 다중 RHS | 안마다 그대로 |
| 구멍·외곽 루프 | `esl/opt/keepout.boundary_loops` | 자유 모서리 루프 | B 체결 후보(구멍 중심) |
| 3D 보기 | `esl/view3d.build_view` + `frontend/src/view3d/View3DCard` | ESL 하중 보기 | 베이스라인·상위 안 비교 |
| 외부 실행 | `worker/esl_worker/localproc.py`(h3d·OptiStruct 공통) | argv 템플릿·shell=False·트리 종료 | paicad 도 여기로 |
| 작업 | `core/job_types.py` | stage 1~10, OPT_RUN | stage 11 신규 3종 |
| DB | migration HEAD **0010**(`down_revision 0008`), 0009 = MCP 예약(`down_revision 0010` 예정) | | **0011**(§13) |
| paicad | physicsai `packages/paicad` 0.14.0(2026-10-26), 의존 `cadquery-ocp==7.8.1.1.post1`, numpy <3, scipy <2. **gmsh 는 paicad test extra 에만**(런타임 의존 아님), PyPI 미배포 | CLI 종료코드 0/2/3/10/11/12/13/14/15/20, stdout `PAICAD PROGRESS n msg`·`PAICAD RESULT status code report`, `paicad version --json` | §6 |

paicad 0.14.0 에서 확인한 사실(소스 읽기만):
- `shell extract --cad --out-dir [--assem-dir --body-map --options --no-png --threads]` → `shell_features.json`(`beads[]{id,k,body,shape(linear|circular),sense,center,axis,normal,nominal{depth,width,length,…},fixed_overlap,fixed_clearance_mm}`, `features[]{name,type ∈ BEAD_DEPTH|BEAD_WIDTH|BEAD_POS_U|BEAD_POS_V, bead, body, nominal, unit, range, feasible, op, ref, group, use_default}`, `groups[]`(MIRROR), `warnings[]`(`BEAD_FIXED_OVERLAP`·`BEAD_NEAR_FIXED`·`FIXED_INFO_MISSING`)), `parameter_extracted.xml`, 비드 PNG. 비드 0 → 종료 13 `GEOM_EXTRACT_EMPTY`. 값 파일 키 = 그룹 대표 + 비그룹 이름(`shell.common.param_keys`).
- `shell fixed-scan --assem-dir --out-dir [--parts|--features --options --threads]` → `shell_scan.json`·`fixed_nodes.npz{node_id, part, kind_mask, cluster, xyz}`. 조립 폴더 아래 `*.rad`·`*.inc` **전부**를 읽는다(재귀).
  - (v0.12.1) ①·②③ A Case 의 `--assem-dir` = **모델 전체 사본** `prep/assem_full/`·`prep/a_assem_full/`(`esl.doe.assem_full`: starter include 트리 전체, Case 폴더 밖 include 는 `_ext/<공통 조상 기준 상대경로>`, 허용 루트 밖·링크 `PATH_OUTSIDE_ROOT`, 깊이 초과 `INCLUDE_TOO_DEEP`, 재생성 파생물 — 재준비 때 `_backup` 없이 삭제). 사본에서만 paicad 0.14.0 미지원 집합 카드를 같은 의미로 재작성(`bead_doe.fixed_scan`), run 모핑 사본 중 재작성 파일은 원본 + 모핑 `/NODE` 블록으로 복원.
  - Radioss 입력 형식(2024.1·2026.1): 2026 Starter 매뉴얼(help.altair.com) 확인 — `/SUBSET/<id>` 다음 title, 데이터 = 하위 subset ID(줄당 ≤10), 파트 소속 = `/PART` 셋째 칸 subset_ID; `/GRNOD/GENE` 데이터 = (first_ID, last_ID) 쌍 줄당 ≤5(증분 없음, 증분은 `/GRNOD/GEN_INCR`). 2024.1 은 사용자 제공 형식이 같음(2024.1 매뉴얼 페이지는 이 작업 중 열람 불가 — 실기 확인). `/SURF/PART|SUBSET[/EXT|ALL]`·`/SHELL`·`/SH3N`·`/BRICK`·`/TETRA4`·`/TETRA10`·`/PENTA6`·`/INTER/TYPE2` 의 esl 이 읽는 칸(ID·노드 정수 칸, TYPE2 첫 두 칸)은 두 버전 **동일**로 본다. `fixed_scan.subset_format` auto(기본: `/BEGIN` 둘째 줄 Invers 또는 `#RADIOSS STARTER … 20xx` 주석, 판정 불가 → 2024 규칙)·2024·2026·legacy(데이터 줄 파트 id 허용) — 판정은 `prep/assem_full.json` `subset_format`·작업 로그.
- `shell tag --cad --features --assem-dir --fixed-dir --out-dir`, `shell run --cad --features --values --assem-dir --tag-dir --fixed-dir --update-dir --morph-dir --check-dir --out-files-dir [--body-map --thickness --options --solver --threads]`(첫 실패 단계에서 중단, check PASS 일 때만 `--out-files-dir/<rel>` = **노드가 바뀐 파일만**, `/NODE` 좌표 필드만 교체한 사본).
- `shell update --cad --features --values --out-dir [--fixed-dir …]` → `sample.brep`·`shell_update.json`·`face_map.json`.
- `shell view grid --cad --features --cells --thumb-options --fixed-dir --out-dir [--options --view-options --threads]`: `--fixed-dir` 는 argparse 필수지만 `shell/view.py _fixed()` 가 빈 값이면 고정 없음으로 처리. 셀 상태 `OK`·`FAIL`(update 코드 그대로)·`ERROR`, `grid_manifest.json`, `cells/<id>/thumb.png`, 셀 id `[0-9a-z_]{1,64}`.
- 모든 명령: 출력 폴더가 이미 있으면 `GEOM_OUTPUT_EXISTS`(덮어쓰기 없음).

## 1. 범위 / 비범위

| 범위 (v0.9.0) | 비범위 (§18 후속) |
|---|---|
| 시나리오 ①②③, 라이브러리 ESL 여러 개 선택 | 비드 개수·종류 변경(추가·삭제), 리브·두께 파라미터 |
| STEP·B 메시 업로드(기존 청크 업로드) | 탄소성 정적(OptiStruct NLSTAT + MATS1) |
| paicad 연동(extract·fixed-scan·tag·run·update·view grid), gmsh 메싱(③) | 대리모델·최적화 탐색(DOE 결과로 다음 안 제안) |
| DOE 생성 LHS·Halton·풀 팩토리얼, 썸네일 미리보기 | OptiStruct 비드 토포그래피(= v0.7.0 OPT_RUN) |
| 안별 선형 해석, 순위·민감도·3D 비교·산출물·보고서 | 비드 반영 형상 검증 낙하 자동 실행, HPC |
| 경계 매핑 경고(②③) | 결과 라이브러리 등록 |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| BD-D-1 | 단위 = **비드 DOE 연구**(`bead_does` 1행) — 입력 준비 1회, DOE 설정·미리보기는 여러 번, 실행 1회(재실행 = 새 연구 복제). 작업 3종 `DOE_PREP`·`DOE_PREVIEW`·`DOE_RUN`(모두 SLOT, stage **11**) | 준비(paicad extract·tag, 대형 rad)는 비싸고 DOE 설정은 여러 번 바꿈 |
| BD-D-2 | 시나리오 키 `same`(①)·`mesh`(②)·`step`(③). ① 다른 모델 ESL = 422 `MODEL_MISMATCH`(v0.7.0 OR-D-5 와 같음), ②③ 크기 = `esl.opt.size.assert_ok(rows, cfg, template=B)`(B 를 템플릿 자리로) → 422 `SIZE_MISMATCH` | 확정 2, 코드 재사용 |
| BD-D-3 | **하중**: ① = 원본 F_eq 를 node_id 로 재배열(OR-D-3), 모핑해도 ID 불변이라 **모든 안에 같은 노드 하중**. ② = B **베이스라인 메시에서 1회** `mapping.to_target`(frame = B 베이스라인) → B 노드 하중을 모든 안에 그대로(ID 불변, 매핑 잡음 0). ③ = 안마다 `to_target`, frame 은 **베이스라인 메시 frame 고정**(셀 경계가 안마다 같게) | 안 간 차이를 형상 차이만으로 |
| BD-D-4 | **지지(3-2-1)**: ① 기준 ESL 3-2-1 node_id 그대로. ② B 베이스라인에서 `target.auto_supports` 1회 → 모든 안 같은 node_id. ③ 안마다 `auto_supports`(같은 정규화 규칙) | 확정 3 |
| BD-D-5 | **해석** = 안마다 `ShellModel(x_d, conn, type, t, E, ν).factorize(spc)` 1회 → 선택 ESL 전부 `solve` → C_{d,i} = Σ F_i·u[:, :3], umax_{d,i} = max‖u[:, :3]‖, εmax_{d,i} = max `eps_eq_max_layer(strains(u))`. 반력 합/Σ‖F‖ > `bead_doe.solve.reaction_warn`(0.01) 이면 안별 경고 `REACTION_RESIDUAL`(모핑으로 모멘트 평형이 조금 깨질 수 있음) | 확정 6 |
| BD-D-6 | **순위 지표**(확정 7): C_ref = max_i C_{0,i}(베이스라인 d000 의 선택 ESL 최악), score_d = max_i C_{d,i} / C_ref, 개선율 = 1 − score_d. 오름차순, 동률 = 안 id 사전순. 최악 ESL(argmax)·umax·εmax(최악 ESL 기준과 전 ESL 최대 둘 다) 표시. 스킵·실패 안은 순위 밖 | v0.7.0 OR-D-15 abs 와 같은 정의 |
| BD-D-7 | **DOE 변수** = paicad `param_keys`(MIRROR 그룹은 대표 1개 — 멤버는 paicad 가 같이 바꿈). 기본 포함 = `use_default: true` 인 D·W(위치 U/V 는 기본 제외, 사용자가 켬), 기본 범위 = `feasible`. 사용자 범위가 feasible 밖이면 **경고 배지만**(차단 아님, 미리보기가 실패 안을 거름), 물리 하한(D·W > 0)·lo < hi 위반은 422 | 확정 4, feasible 은 추정치(`source: estimate`) |
| BD-D-8 | **DOE 생성**(`esl.doe.matrix`, API·워커 같은 함수): `lhs` = Python 표준 `random.Random(seed)`(층 순열·층 안 균일, 변수 순서 행 우선 소비), `halton` = `scipy.stats.qmc.Halton(d, scramble=True, seed=numpy.random.default_rng(seed))`, `fullfact` = 변수별 등간격 수준(기본 3, 2..9) 곱. 값 반올림 `round_mm`(0.01) → 중복·공칭 동일 안 제거(먼저 나온 것 유지) → `d001…` 번호. 공칭 = `d000`(항상 포함). 안 수 > `max_designs`(200) → 422 `DOE_TOO_LARGE`. 행렬 sha256 = 정렬 키 JSON. physicsai doe-methods.md DM-C3 와 같은 구현 규칙 | 결정성·재현, 사용자 확정 방식 3종 |
| BD-D-9 | **미리보기 필수**: `DOE_RUN` 은 같은 `matrix_sha256` 의 미리보기가 성공한 뒤에만(409 `PREVIEW_STALE`). 미리보기 `FAIL` 셀 = `SKIPPED_COLLISION`(GEOM_FEATURE_COLLISION)·`SKIPPED_FIXED`(SHELL_FIXED_REGION_VIOLATION)·`SKIPPED_GEOM`(그 밖 update 실패)로 표시하고 실행에서 뺌 | 확정 4 "실행 전 미리보기, 스킵 표시" |
| BD-D-10 | **① 형상 경로** = paicad `shell run`(update→morph→check, 고정 노드 = 조립의 tie·RBE2 등) → `out_files/<rel>` 에서 대상 파트 노드 좌표만 읽어 x_d(ID·연결·PID 불변). **②** 같음(조립 = B 메시 사본). **③** = `shell update`(고정 없음) → `sample.brep` 를 gmsh 로 메시(§7). 베이스라인 ①② = 원 메시 그대로(모핑 없음), ③ = 공칭 STEP 을 같은 gmsh 설정으로 | 확정 2 |
| BD-D-11 | **③ 고정 노드 없음**: `shell view grid --fixed-dir ""`(paicad 0.14.0 `_fixed("")` = 없음 — V-BD-16 실검), `shell update` 는 `--fixed-dir` 생략 | 확정 2 "모핑 고정 노드 불필요" |
| BD-D-12 | **② B 메시**: 업로드한 rad/inc 를 `_doe/<id>/input/mesh/` 로 복사(sha256, include 는 업로드 폴더 안만 — v0.7.0 템플릿 규칙), paicad `--assem-dir` = 이 사본. B 에 tie·RBE2 가 있으면 고정, 없으면 고정 0(정보 `B_NO_FASTENERS`) | 입력 폴더 읽기만 + paicad 가 폴더 전체를 읽음 |
| BD-D-13 | **① 조립 폴더** = 기준 ESL Case 입력 폴더를 **제자리**(읽기만) `--assem-dir` 로. 시작 전 폴더 아래 `*.rad`·`*.inc` 합계 > `bead_doe.same.max_assem_mb`(설정, 기본 4096) 이면 422 `ASSEM_TOO_LARGE`(안내: ② 로 Ch/R 주변만 올리기). 상한은 설정 키(**Q1 A 확정**) | 확정 2(Case rad Ch/R = 기준), 대형 씬 비용(R-BD-1) |
| BD-D-14 | **경계 매핑 경고**(②③, §8): A 체결점 = A Case 에 paicad `shell fixed-scan`(Ch/R 파트) 클러스터 중심 + A ESL 3-2-1 노드, A 하중 집중 = `view3d.clusters`(|F| 가중 k-means, 합력 비율 ≥ `load_share_min`). (ξ,η) 정규화로 B 평면 (a,b) mm 에 옮겨 B 체결 후보(B fixed-scan 클러스터 ∪ B 구멍 중심)까지 거리 비교. 차단 없음 | 확정 5 |
| BD-D-15 | **병렬**: `DOE_RUN` 은 슬롯 1개를 쥐고 안 단위 하위 프로세스를 최대 `run.parallel`(2)개 동시 실행. 시작 시 `estimate_direct_bytes × parallel ≤ available_memory × run.memory_margin`(0.7) 이 되도록 자동 축소(로그). paicad `--threads` = `paicad.threads` | 22만 요소 분해 수 GB, 서버 512 GB |
| BD-D-16 | **재시도·이어하기**: 안 폴더 `run/designs/<id>/done.json{input_sha256, status}` — input_sha256 = (values, 기준 메시 sha, 하중 sha, 설정 해시, paicad 버전) 같으면 SKIPPED(재사용). 스킵 상태(충돌·고정)는 결정적이라 재시도 안 함, `FAILED_*` 만 다시 | 수 시간 반복 방지(v0.7.0 OR-D-19 와 같은 취지) |
| BD-D-17 | **결과 파일 정리**: paicad `morph/files/`·`out_files/`(대형 rad 사본일 수 있음)는 노드 좌표를 `design.npz` 로 옮긴 뒤 **순위 상위 `paicad.keep_files_top`(3) + 베이스라인만 남기고 지움**(BD_POST 끝). 워커가 실행 폴더 안에 스스로 만든 중간 파일이라 v0.7.0 `u_cand.npy` 결정과 같은 예외 | 디스크(R-BD-2) |
| BD-D-18 | **산출물(최적 안 = 순위 1, 상위 k 도)**: ①② = paicad check 사본 include(`out_files/<rel>`, 원 ID·`/NODE` 좌표만 바뀐 파일) + `values.json` + `sample.brep` + `sample.step`(gmsh OCC 내보내기). ③ = 메시 `ch_r.rad`(/NODE·/SHELL·/SH3N·/PART·/PROP/TYPE1·/MAT/LAW1, ID 1부터 — `esl.export` id 규칙) + `ch_r.fem`(GRID·CQUAD4·CTRIA3·PSHELL·MAT1) + `sample.brep`·`sample.step` + `values.json` | 확정 7 |
| BD-D-19 | **paicad 버전**: 배포 고정 = `deploy/paicad.lock`(version 0.14.0·physicsai 커밋·wheel sha256). 런타임 허용 = `paicad version --json` 의 paicad ≥ `paicad.min_version`(0.14.0) **그리고** `ocp` 가 null 아님. 고정과 다르면 경고(관리자 화면·결과에 기록), 낮거나 OCP 없음 → 기능 비활성(사유 §6.5) | 확정 1 |
| BD-D-20 | **gmsh** = Python 모듈(`gmsh` wheel)로 **코어 하위 프로세스 안에서** 호출(외부 명령 아님 — 메시마다 `multiprocessing` **spawn** 자식으로 격리·타임아웃, §7.1). 없으면 ③ 만 비활성(`GMSH_UNAVAILABLE`), STEP 내보내기(BD-D-18)도 gmsh 로 — 없으면 BREP 만 + 경고 | paicad 런타임 의존에 gmsh 없음 |
| BD-D-21 | migration **0011**(`down_revision "0010"`). MCP 예약 0009 는 구현 시점 HEAD 뒤에 붙인다(`revision "0009"`, `down_revision` = 그때 HEAD — 지금 기준 "0011"). esl_opt_run.md OR-D-22 의 "0009 → down 0010" 을 이 규칙으로 바꿈. **0010 수정**: 0010 이 CHECK 를 `tables.CK_JOBS_*`(현재 정의 — 0011 의 `bead_doe_id` 참조)로 다시 걸던 것을 0010 시점 고정 상수(`*_0010`)로 바꿔 0008 DB → 0011 업그레이드가 0010 단계에서 없는 열을 참조하지 않게 함(0004 와 같은 규칙, §21) | 단일 head 유지, 0008 운영 DB 업그레이드 가능 |
| BD-D-22 | ① 기준 Case 가 누적 씬이면 정보 경고 `BD_BASE_CUMULATIVE`("형상 = rad /NODE 공칭, ESL 은 누적 변형 상태 기준") — 실행 허용 | paicad 는 `.str` 을 읽지 않음, v0.8.0 S1 경고와 같은 취지 |

## 3. 사용 시나리오 (단계 흐름)

공통 진입: 라이브러리 목록에서 ESL 체크 → [선택한 ESL로 비드 DOE (n)] → `/esl/p/:pid/doe/new?entries=…`.

### 3.1 ① 같은 모델
1. 새 비드 DOE 화면, 시나리오 라디오 [● 같은 모델 ○ 다른 모델(메시 있음) ○ 다른 모델(STEP만)]. 모든 ESL 이 같은 모델이면 기본 ①. 기준 Case·대상 파트·노드/요소 수 표시(v0.7.0 s1-check 재사용), 다른 모델 ESL 은 ✗ + [다른 모델 빼기].
2. Ch/R 중립면 STEP 끌어다 놓기(청크 업로드) → [입력 준비](주) → `DOE_PREP`.
3. 준비 완료: 비드 표(비드 PNG·모양·sense·공칭 D/W/U/V·feasible·고정 겹침 경고), 평면도.
4. DOE 설정: 변수 체크·범위·방식·안 수 → [미리보기](주) → `DOE_PREVIEW` → 썸네일 격자(OK/스킵 표시).
5. [DOE 실행](주) → `DOE_RUN` → 순위·민감도·3D 비교·받기·보고서.

### 3.2 ② 다른 모델 + B 메시
1. 시나리오 ② → B STEP + B 메시(rad + include 또는 inc) 업로드, B 파트 제목(기본 `chassis rear`, v0.5.1 exact_ci 규칙), 인치(선택) → [입력 검사] 결과(크기 차·메시 품질, `POST /doe/check-inputs`) → [입력 준비].
2. 준비 완료: 비드 표 + **경계 매핑 평면도**(A 체결점·하중 집중부 → B, B 구멍·고정 클러스터, 거리 초과 빨강 선) + 경고 수.
3. 이후 ①과 같음.

### 3.3 ③ 다른 모델 STEP 만
1. 시나리오 ③ → B STEP, 인치(선택), 쉘 물성(두께 t·E·ν — 기본값 §7.3, **Q2 A 확정**), 평균 요소 크기(기본 = A 메시 요소 크기 중앙값, 칸 1개) → [입력 준비].
2. 준비에서 베이스라인 gmsh 메시(품질 요약 표시) + 비드 표 + 경계 평면도.
3. 이후 같음(안마다 메싱 시간 포함 — 진행률에 표시).

## 4. 데이터 흐름 · 폴더

```
POST /doe/studies → bead_does + DOE_PREP
 DOE_PREP  (<esl_root>/_doe/<id>/)
  1 BD_INPUT  (INTERNAL) 입력 sha·복사(input/step/, ② input/mesh/) → ① Case rad parse_rad(대상 파트, 제자리) + topo 동일성 / ② B 메시 parse_rad
              → 크기 규칙 → prep/base_mesh.npz(node_id, x0, conn, type, pid, t, E, ν), prep/input.json
  2 BD_MESH0  (INTERNAL, ③만 — 그 밖 SKIPPED) gmsh(공칭 STEP) → prep/base_mesh.npz, prep/mesh0.json(품질)
  3 BD_GEOM   (LOCAL) paicad version → [②③ A Case 있으면 fixed-scan(A) → prep/a_fixed/]
              → [①② fixed-scan(조립) → prep/fixed/] → extract → prep/extract/ → [①② tag → prep/tag/]
  4 BD_LOADS  (INTERNAL) frame(① 기준 ESL meta.frame, ②③ base_mesh) → 지지 → 하중(①②: prep/loads.npz 전 ESL, ③: 매핑 요약만)
              → 경계 경고(②③) → prep/params.json(변수 표), prep/plan.json(평면도), prep/boundary.json
  5 BD_PREP_REGISTER (DB) bead_does.prep 요약
POST /doe/studies/{id}/preview → bead_does.doe(rev, spec, matrix_sha) + DOE_PREVIEW
  1 BD_MATRIX (INTERNAL) doe/<rev>/matrix.json(API 와 같은 함수·같은 sha 확인), cells.json, thumb_options.json
  2 BD_GRID   (LOCAL) paicad shell view grid → doe/<rev>/grid/
  3 BD_PREVIEW_REGISTER (DB) 셀 상태 요약
POST /doe/studies/{id}/run → DOE_RUN
  1 BD_BASELINE (INTERNAL) d000 평가 → run/designs/d000/
  2 BD_DESIGNS  (LOCAL+INTERNAL) 미리보기 OK 안마다: [①② paicad shell run | ③ paicad shell update → gmsh] → design.npz → 선형 해석 → result.json
  3 BD_POST     (INTERNAL) 순위·민감도 → post/, 상위 k view3d → post/view3d/<id>/, 산출물 → best/<id>/, report.html, 파일 정리(BD-D-17)
  4 BD_REGISTER (DB) bead_does.result, report_rel, artifacts, 알림
```

- 폴더: `<esl_root>/_doe/<id>/{input/, prep/, doe/<rev>/, run/designs/<did>/{paicad/{update,morph,check,out_files}|update/, mesh/, design.npz, result.json, done.json}, post/, best/<did>/, report.html, doe.json}`. 각 step 은 자기 하위 폴더를 `fresh_dir`(이전 내용 `_backup/<UTC>/`). paicad 출력 폴더는 **항상 존재하지 않는 새 경로**로 넘김(GEOM_OUTPUT_EXISTS 방지).
- 코어는 DB 를 모름. 쓰기는 `_doe/<id>/` 만(Case 입력·업로드 폴더 읽기만, V-BD-14).
- `design.npz` = node_id, x (N,3) float64(③ 은 + conn, type, pid), 공통 키 계약은 v0.7.0 `target.npz` 와 같은 dtype 규칙(allow_pickle=False).
- `result.json` = {id, status, values, paicad{code, seconds}, mesh{n_nodes, n_elems, quad_frac, quality}, solve{seconds, backend}, per_esl:[{entry_id, C, umax, epsmax}], score, worst_entry_id, warnings[]}.

## 5. DOE 생성·미리보기 (BD-1~3)

- 입력 `DoeSpec { method: "lhs"|"halton"|"fullfact", n?: int (lhs·halton, 2..max_designs, 기본 `doe.default_n` 30), levels?: int (fullfact 기본 3, 2..9), seed?: int (0..2^32−1, 기본 `doe.seed` 1), params:[{name, lo, hi}] (포함 변수만, 1개 이상) }`.
- 검증: name ∈ prep 변수 표(아니면 `DOE_PARAM_UNKNOWN`), lo < hi, D·W 의 lo > 0(`DOE_RANGE_INVALID`), feasible 밖 = 응답 `warnings[{code: RANGE_OUTSIDE_FEASIBLE, name}]`, 풀 팩토리얼 안 수 = levels^k, 결과 안 수 + 1 > `max_designs` → `DOE_TOO_LARGE`.
- 생성 값 = lo + u·(hi − lo), 포함 안 한 변수는 값 파일에 넣지 않음(= 공칭). 반올림·중복 제거는 BD-D-8.
- 미리보기 입력: `cells.json{schema_version:1, cells:[{id:"d001", values:{…}}…]}`(d000 제외 — 행렬 그대로). 워커 BD_GRID 는 paicad 에 넘길 `doe/<rev>/grid_cells.json` = cells + **공칭 셀 `{id:"nominal", values:{}}`** 로 만든다(paicad 0.14.0 grid 는 `grid_manifest.nominal = {bbox, view_sha256}` 만 쓰고 공칭 썸네일을 만들지 않음 → 공칭 셀의 `grid/cells/nominal/thumb.png` 가 d000 썸네일). `nominal` 셀은 안이 아니라 셀 상태·미리보기 요약·`preview.cells` 에 넣지 않는다. `thumb_options.json{schema_version:1, w, h, view_dir, margin, disp_range_mm, colormap:"turbo16", nominal_ghost:true, edges:false}` — view_dir `auto` = frame 법선 n 을 −η 쪽으로 `preview.tilt_deg`(20°) 기울임, disp_range_mm `auto` = [0, max(|hi−nominal|, |lo−nominal|) 의 D 최대, 최소 1 mm].
- 셀 결과 → 안 상태: OK → `READY`, FAIL → BD-D-9 스킵 상태, ERROR(`VIEW_*`) → `READY` + 썸네일 회색 경고(형상 갱신은 성공), ERROR(내부) → `SKIPPED_GEOM`.
- 썸네일 표시는 `doe/<rev>/grid/cells/<id>/thumb.png`(320×240 PNG ≈ 3 KiB) — `GET …/preview/thumb/{did}`. `did = d000` 은 `grid/cells/nominal/thumb.png`(백엔드 탐색 순서: `grid_manifest.nominal.thumb` → `nominal/thumb.png` → `cells/nominal/thumb.png` → `nominal.png` — 앞 두 개는 paicad 가 공칭 썸네일을 직접 쓰게 될 때 대비).

## 6. paicad 연동 규약 (BD-4~6)

### 6.1 호출 명령 (argv 템플릿 — `commands.*`, argv[0] `{paicad}` → `bead_doe.paicad.exe`)

| 키 | argv | 시나리오 | 출력 폴더 |
|---|---|---|---|
| `paicad_version` | `{paicad} version --json` | 공통(준비·`/doe/settings` 점검 캐시) | – (stdout JSON) |
| `paicad_fixed_scan` | `{paicad} shell fixed-scan --assem-dir {assem_dir} --parts {parts} --out-dir {out_dir} [--options {options?}] --threads {threads}` | ①② 조립, ②③ A Case | `prep/fixed/`, `prep/a_fixed/` |
| `paicad_extract` | `{paicad} shell extract --cad {cad} --out-dir {out_dir} [--assem-dir {assem_dir?}] [--body-map {body_map?}] [--options {options?}] --threads {threads}` | 공통(③ 조립 없음) | `prep/extract/` |
| `paicad_tag` | `{paicad} shell tag --cad {cad} --features {features} --assem-dir {assem_dir} --fixed-dir {fixed_dir} --out-dir {out_dir} [--body-map …] [--options …]` | ①② | `prep/tag/` |
| `paicad_grid` | `{paicad} shell view grid --cad {cad} --features {features} --cells {cells} --thumb-options {thumb} --fixed-dir {fixed_dir} --out-dir {out_dir} [--options …] --threads {threads}` | 공통(③ `fixed_dir` = 빈 문자열) | `doe/<rev>/grid/` |
| `paicad_run` | `{paicad} shell run --cad … --features … --values {values} --assem-dir … --tag-dir … --fixed-dir … --update-dir {d}/update --morph-dir {d}/morph --check-dir {d}/check --out-files-dir {d}/out_files [--body-map …] [--options …] --threads {threads}` | ①② 안마다 | `run/designs/<id>/paicad/` |
| `paicad_update` | `{paicad} shell update --cad … --features … --values … --out-dir {d}/update [--options …]` | ③ 안마다 | `run/designs/<id>/update/` |

- 선택 쌍 규칙: 값이 `{name?}` 인 자리표시자가 null 이면 **바로 앞 플래그와 함께 제거**(빈 문자열은 제거하지 않음 — ③ `--fixed-dir ""`). 그 밖 자리표시자가 null 이면 `CONFIG_INVALID`.
- 값 출처: 경로는 모두 서버 생성(`_doe/<id>/…`) 또는 검사 통과 입력 경로(realpath 가 input_roots·업로드 루트·`_doe/<id>/input` 안), `parts` = 대상 파트 id(정수 쉼표), `threads` = 설정 정수. 사용자 문자열(제목·파트 제목)은 argv 에 넣지 않는다(파트는 id 로 변환해 전달).
- `body_map.json`(①②) = `{schema_version:1, map:{<STEP 바디 이름>: "PART:<pid>"}}` — STEP 바디가 1개일 때 플랫폼이 extract 1차(조립 없이 `--no-png`, `prep/extract0/`)로 바디 이름을 얻어 만든다. 바디 ≠ 1 → `STEP_BODY_COUNT`(준비 실패).
- `options.json`: `bead_doe.paicad.options`(paicad shell options 스키마 그대로, 기본 `{}` → 인자 생략)를 `prep/paicad_options.json` 로 써서 모든 호출에 같은 파일.
- 실행: 워커 LOCAL step, `localproc.py`(shell=False, 메타문자 거부, 트리 종료, 타임아웃 `paicad.timeout_s.<명령>`), cwd = 출력 폴더의 부모, env = 기본 OS 키 + `worker.env_passthrough` + `paicad.env`(v0.7.0 OptiStruct 규칙과 같음). stdout 의 `PAICAD PROGRESS n msg` → step 진행률·로그, `PAICAD RESULT status code report` 마지막 줄 → 결과. `paicad.log` 는 출력 폴더에 남김(관리자 받기).

### 6.2 결과 판정
- 성공 = 종료 0 + `PAICAD RESULT OK` + 보고 JSON(`shell_*.json`·`grid_manifest.json`) 존재·`status` OK. 경고(`warnings[]`)는 준비/안 경고로 옮김.
- 종료 2(인자) = 플랫폼 결함 → `PAICAD_INTERNAL`(관리자용 argv 로그). 종료 20·130·타임아웃 = `PAICAD_FAILED`/`PAICAD_TIMEOUT`. 보고 JSON 없음 = `PAICAD_FAILED`.
- **준비 단계** 실패는 작업 실패(사용자 문구 §6.3). **안 단계** 실패는 그 안만 상태 기록하고 다음 안 진행(BD-D-9·§9.2). 베이스라인 실패는 작업 실패 `BASELINE_FAILED`.

### 6.3 실패 코드 → 사용자 문구 (원본 1곳 `resources/doe_messages.json`, 보고서·API 공용)

| paicad 코드 (종료) | 단계 | 플랫폼 코드 | 사용자 문구 |
|---|---|---|---|
| `SHELL_BODY_NOT_SHEET` (12) | 준비 | `STEP_NOT_SHEET` | STEP 이 중립면(시트)이 아니라 솔리드입니다. 중립면 STEP 을 올려 주세요. |
| `GEOM_EXTRACT_EMPTY` (13) | 준비 | `NO_BEADS` | STEP 에서 비드를 찾지 못했습니다(평면 위 오목·볼록 비드만 인식). |
| `GEOM_BODY_MAP_FAILED` (12) | 준비 | `BODY_MAP_FAILED` | STEP 바디와 메시 파트를 짝짓지 못했습니다(바디 이름·파트 확인). |
| `GEOM_BASELINE_MISMATCH` (12) | 준비 | `STEP_MESH_MISMATCH` | STEP 과 메시 형상이 다릅니다(다른 모델·위치 이동·단위 차이). |
| `SHELL_PART_NOT_FOUND` (3) | 준비 | `PART_NOT_FOUND` | 메시에서 Ch/R 파트를 찾지 못했습니다. |
| `SHELL_UNSUPPORTED_ELEMENT` (12) | 준비 | `MESH_INVALID` | Ch/R 에 4각·3각 쉘 외 요소가 있습니다. |
| `SHELL_FIXED_PARSE_FAILED` (12) | 준비 | `FIXED_PARSE_FAILED` | 체결 카드(tie·RBE2 등)를 해석하지 못했습니다. |
| `GEOM_TAG_FAILED`·`GEOM_INPUT_INVALID` (12·3) | 준비 | `PAICAD_INPUT` | 형상 엔진이 입력을 받지 못했습니다(STEP·메시 확인). 상세는 로그. |
| `GEOM_FEATURE_COLLISION` (10) | 미리보기·안 | 안 `SKIPPED_COLLISION` | 비드가 다른 비드·구멍·가장자리와 겹쳐 건너뜁니다. |
| `SHELL_FIXED_REGION_VIOLATION` (10·11) | 미리보기·안 | 안 `SKIPPED_FIXED` | 비드가 체결 고정 영역을 침범해 건너뜁니다. |
| `GEOM_CAD_FAILED`·`GEOM_TOPOLOGY_CHANGED` (10) | 미리보기·안 | 안 `SKIPPED_GEOM` | 이 값으로는 형상을 만들 수 없어 건너뜁니다. |
| `GEOM_MORPH_FAILED`·`GEOM_QUALITY`·`GEOM_DEVIATION`·`GEOM_PARAM_MISMATCH`·`GEOM_INTERFERENCE`·`GEOM_TIE_PROJECTION` (11) | 안 | 안 `FAILED_MORPH` | 메시 모핑·품질 검사에 실패했습니다(코드 표시). |
| `VIEW_TOO_LARGE`·`VIEW_TESSELLATION_FAILED` (14) | 미리보기 | 경고 `THUMB_UNAVAILABLE` | 썸네일을 만들지 못했습니다(형상 변경은 성공). |
| `GEOM_OUTPUT_EXISTS`·종료 2 | 전부 | `PAICAD_INTERNAL` | 내부 오류입니다(관리자 문의). |
| `GEOM_INTERNAL`·종료 20 | 전부 | `PAICAD_FAILED` | 형상 엔진 내부 오류입니다. 로그를 관리자에게 보내 주세요. |
| 타임아웃 | 전부 | `PAICAD_TIMEOUT` | 형상 엔진이 제한 시간(설정) 안에 끝나지 않았습니다. |

- 모르는 paicad 코드 = 종료코드 범주(10 → SKIPPED_GEOM, 11 → FAILED_MORPH, 3·12·13 → PAICAD_INPUT, 그 밖 PAICAD_FAILED)로 분류하고 원 코드 병기.

### 6.4 버전 고정·설치 (BD-D-19)
- `deploy/paicad.lock`: `{version: "0.14.0", source: "wgcha/physicsai-platform", commit: <40자>, wheel: "paicad-0.14.0-py3-none-any.whl", sha256: <64자>, branch, subdir, build_requires: ["setuptools==…"], console_script, runtime_requires}`. collect-offline 은 그 커밋의 `packages/paicad` 를 줄 끝 변환 없이 꺼내 `pip wheel --no-deps` → **정규화**(`deploy/paicad_wheel.py`: 같은 항목·내용을 무압축 ZIP_STORED·시각 1980-01-01·권한 0644·이름 순(.dist-info 끝, RECORD 맨 끝)으로 다시 씀, RECORD 불변) → 버전·**정규화 sha256** 대조(불일치 중단) → `wheels/` 에 넣음. 정규화로 빌드 OS·시각·umask·zlib 판과 무관하게 같은 바이트가 되어 lock 의 sha256 하나로 Windows·Linux 준비 PC 결과를 대조한다(lock 갱신 = `paicad_wheel.py digest`). `deploy/requirements.lock` 에 `cadquery-ocp==7.8.1.1.post1`(paicad 고정과 같음)·`gmsh==<고정>`(cp312 win_amd64 휠 있는 버전, lock 갱신 시 확인) 추가. install 은 같은 wheels 에서 `--no-index` 설치.
- `setup_config.py`: `bead_doe.paicad.exe` 가 비었고 `<런타임 venv>/Scripts/paicad.exe` 가 **실제 있을 때만** 채움(v0.8.0 OptiStruct 자동 감지와 같은 규칙, 기존 값 불변, `_backup`, 콘솔 1줄). `upload.allowed_ext` 에 `.step`·`.stp` 1회 보충.
- 배포 코드 목록(`$EslAppItems`·collect-offline)에 `resources/doe_messages.json`·`resources/doe_method_sources.json` 추가(v0.7.2 누락 사고 재발 방지 — V-BD-18).

### 6.5 없을 때 비활성 사유 (`GET /doe/settings`)
`enabled:false` 이유 코드: `DOE_DISABLED`(설정 꺼짐), `PAICAD_NOT_CONFIGURED`(exe 없음), `PAICAD_NOT_FOUND`(경로 없음), `PAICAD_VERSION_LOW`(< min), `PAICAD_OCP_MISSING`(version JSON `ocp` null), `PAICAD_CHECK_FAILED`(실행 실패). ③ 만: `GMSH_UNAVAILABLE`. 화면 상단 경고 띠 "형상 엔진(paicad)이 설치되지 않았습니다(관리자 문의)", 서버 경로·상세는 전역 관리자에게만. 점검 결과는 백엔드가 `bead_doe.settings_cache_s`(300) 캐시 — 백엔드는 paicad 를 **실행하지 않고** 워커가 주기(`bead_doe.paicad.check_interval_s`) 점검해 DB **`worker_heartbeats.info.paicad`**(`{ready, version, ocp, pinned, warning, reason, checked_at}`)·`info.gmsh`(`{ready, version}`)에 heartbeat 와 함께 기록한 값(가장 최근 heartbeat)을 읽는다(외부 명령은 워커만). 기록이 없으면 `PAICAD_CHECK_FAILED`.

## 7. gmsh 메싱 사양 (③, `esl/doe/mesh_gmsh.py`, BD-7)

### 7.1 설정·절차
- 입력 `sample.brep`(안) / 공칭 STEP(베이스라인). 단일 프로세스·단일 스레드: `gmsh.initialize(["-noenv"], readConfigFiles=False)`, `General.Terminal 0`, `General.NumThreads 1`, `Geometry.OCCSewFaces = bead_doe.mesh.occ_sew_faces`(**기본 0**, 0|1 — 면 공유 정보가 없는 STEP(예 gmsh 가 다시 쓴 STEP)은 1), `occ.importShapes` → `synchronize`.
- 크기: `Mesh.MeshSizeMax = h`, `Mesh.MeshSizeMin = h × mesh.min_size_factor(0.2)`, `Mesh.MeshSizeFromCurvature = mesh.curvature_n(12)`(필렛·비드 곡면에 원주당 요소 수), `Mesh.MeshSizeExtendFromBoundary 1`. h = 입력값(기본 `auto` = A ESL 메시 요소 모서리 길이 중앙값, 범위 `mesh.size_min_mm`..`size_max_mm` 1..20).
- quad 위주: `Mesh.Algorithm = mesh.algorithm(8 Frontal-Delaunay for quads)`, `Mesh.RecombineAll 1`, `Mesh.RecombinationAlgorithm 1`(blossom), `Mesh.SubdivisionAlgorithm 0`, `Mesh.ElementOrder 1`, `Mesh.Smoothing 3`. `generate(2)`.
- 출력: 노드 1..N(gmsh 태그 순 재번호), 요소 CQUAD4/CTRIA3(면적 ≤ 1e-12·중복 노드 요소 제거), 바디 법선 쪽으로 연결 순서 정렬(v0.7.0 `align_normals`), PID 1개, t·E·ν = §7.3. `mesh.npz` + `mesh.json{gmsh_version, options, h, n_nodes, n_elems, quad_frac, quality(esl.opt.mesh_check 지표), seconds}`.
- 품질: `esl.opt.mesh_check`(요소·연결·종횡비·뒤틀림) 오류 → 안 `FAILED_MESH`, quad_frac < `mesh.min_quad_frac`(0.8) 경고. 요소 수 > `mesh.max_elems`(500 000) → `FAILED_MESH`(베이스라인이면 준비 실패 `MESH_TOO_LARGE`).
- 타임아웃 `mesh.timeout_s`(1800), 메시마다 `multiprocessing.get_context("spawn")` 자식 프로세스로 격리(fd 1·2 → `mesh.log`, 실패 = `mesh_error.json` + 종료코드 3, 타임아웃·크래시 = `FAILED_MESH`). spawn 이라 부모(코어 자식)의 gmsh 상태·스레드를 물려받지 않고 Windows·Linux 가 같게 동작.
- STEP 내보내기(BD-D-18): 같은 gmsh 세션에서 `gmsh.write("sample.step")`(OCC 형상, 메시 없음).

### 7.2 메시 잡음 상쇄
- 베이스라인 = 공칭 STEP 을 **같은 h·같은 옵션**으로 메시 → 비교 기준. 결과 표·보고서에 "③ 은 안마다 새 메시 — 동일 형상 반복 메시 차이(잡음 바닥)"를 V-BD-6 측정값으로 표시(`noise_floor`: 공칭 STEP 을 BREP 왕복(`shell update` 공칭값) 후 다시 메시한 score 차). |개선율| < noise_floor 인 안은 순위표에 "잡음 이내" 표시.

### 7.3 ③ 쉘 물성 기본값 (Q2 A 확정)
- 기본 = A(선택 ESL 기준 항목) Ch/R 의 면적 가중 두께 중앙값·주 PID 의 E·ν(`entry.json` raw thickness·E·nu), 화면 숫자 3칸(t mm·E MPa·ν)으로 수정.

## 8. 셀 매핑·지지 재사용, 경계 매핑 경고 (BD-8·9)

### 8.1 재사용
- 크기: `esl.opt.size.assert_ok(rows, bead_doe.size ← opt_run.size 와 같은 키, template = {L_xi, L_eta, inch} of B base_mesh frame)`.
- frame: ① 기준 ESL `meta.frame`, ②③ `normalize.frame(B base_mesh, axis_ref = 기준 ESL axis_ref)`(v0.7.0 S2 `build_template` 과 같음).
- 하중: ① `target.entry_load`(직접), ②③ `target.entry_load`(S2 경로 = `mapping.to_target` + 평형 보정). 셀당 노드 중앙값 < 64 경고 그대로.
- 지지: ② `target.auto_supports(base_mesh)`, ③ `auto_supports(design mesh)`, `support_check` rank < 6 → `SUPPORT_DEGENERATE`(안 `FAILED_SOLVE`).

### 8.2 경계 매핑 경고 (②③, `esl/doe/boundary.py`)
- 좌표: 점 p 의 A 정규화 (ξ,η) = ((a−a_min)/L_xi, (b−b_min)/L_eta)_A → B 평면 (a,b) = (a_min + ξ·L_xi, b_min + η·L_eta)_B. 거리 = B 평면 (a,b) 유클리드 mm.
- **A 체결점** = `prep/a_fixed/fixed_nodes.npz` 클러스터별 노드 평균(종류 RBE2·RBE3·RBODY·INTER_TYPE2·BCS, `kind_mask` 로 라벨) ∪ A ESL 3-2-1 노드(라벨 `S321`). A Case 입력이 없거나 fixed-scan 실패 → 3-2-1 만 + 정보 `A_FASTENERS_UNKNOWN`.
- **B 체결 후보** = ② `prep/fixed/` 클러스터 중심 ∪ B 구멍 중심(`keepout.boundary_loops` 의 외곽 아닌 루프, 둘레 ≥ `keepout.hole_min_perimeter_mm`) / ③ B 구멍 중심만.
- 규칙: (1) A 체결점마다 최근접 B 후보 거리 d > `boundary.fastener_warn_mm`(10) → `BOUNDARY_FASTENER_FAR{label, d_mm}`. B 후보 0 → 전부 경고. (2) A 하중 집중 = 선택 ESL 마다 `view3d.clusters`(K ≤ 5) 중 합력 비율 ≥ `boundary.load_share_min`(0.2) 인 군집 중심 → B 로 옮겨 최근접 B 후보 거리 > `boundary.load_warn_mm`(20) → `BOUNDARY_LOAD_UNSUPPORTED{entry_id, share, d_mm}`. (3) 3-2-1: B 자동 지지 3점과 옮긴 A 3-2-1 의 대응 거리 > fastener_warn_mm → 정보 `SUPPORT_SHIFT`.
- 표시: 평면도(v0.7.0 `KeepoutPlan` SVG 렌더러 재사용) B 외곽·구멍(회색), B 고정 클러스터(파랑 점), A 체결점(주황 ×), A 하중 집중(빨강 원, 크기 ∝ 비율), 경고 쌍은 빨강 점선. 표: 라벨·d·기준. 경고 수 = 순위표 머리·보고서. **차단 없음**.

## 9. 작업 종류 · 단계 · 진행률 (BD-10~13)

### 9.1 `job_types.py`
```python
"DOE_PREP": JobTypeDef("DOE_PREP", 11, "SLOT", (
    StepDef("BD_INPUT", "bd_input"), StepDef("BD_MESH0", "bd_mesh0"), StepDef("BD_GEOM", None, kind="LOCAL"),
    StepDef("BD_LOADS", "bd_loads"), StepDef("BD_PREP_REGISTER", None))),
"DOE_PREVIEW": JobTypeDef("DOE_PREVIEW", 11, "SLOT", (
    StepDef("BD_MATRIX", "bd_matrix"), StepDef("BD_GRID", None, kind="LOCAL"), StepDef("BD_PREVIEW_REGISTER", None))),
"DOE_RUN": JobTypeDef("DOE_RUN", 11, "SLOT", (
    StepDef("BD_BASELINE", "bd_eval"), StepDef("BD_DESIGNS", None, kind="LOCAL"),
    StepDef("BD_POST", "bd_post"), StepDef("BD_REGISTER", None))),
```
- 작업 대상 = `jobs.bead_doe_id`. 연구당 비종료 작업 1개(`ux_jobs_bead_doe_active`), 활성 중 새 요청 409 `JOB_ACTIVE`. 순서 강제: PREVIEW 는 prep 성공 후(409 `PREP_NOT_READY`), RUN 은 BD-D-9.
- `BD_DESIGNS`: 워커가 안마다 [LOCAL paicad(①② `paicad_run` / ③ `paicad_update`)] → [INTERNAL 코어 하위 프로세스 `bd_eval --design <id>`: 노드 읽기(①②) 또는 gmsh(③) → 하중·지지 → 해석 → result.json·done.json] 을 하나의 안 작업으로 묶어 스레드 풀(`run.parallel`, BD-D-15)로 실행. 안 순서 = id 순(결과는 순서 무관).

### 9.2 안 상태
`READY`(미리보기 OK) → `RUNNING` → `OK` | `SKIPPED_COLLISION` | `SKIPPED_FIXED` | `SKIPPED_GEOM` | `FAILED_MORPH` | `FAILED_MESH` | `FAILED_SOLVE` | `CANCELED`. OK 0개(베이스라인 제외) → 작업 SUCCEEDED + 경고 `NO_FEASIBLE_DESIGNS`(순위 없음). 베이스라인 실패 → 작업 FAILED `BASELINE_FAILED`.

### 9.3 진행률·로그

| step | 진행률 | 로그 |
|---|---|---|
| BD_INPUT | 파싱 70·검사 30 | 노드·요소·동일성/크기·누적 씬 |
| BD_MESH0 | gmsh 100 | h·요소 수·quad 비율·품질 |
| BD_GEOM | 명령별 균등 × PAICAD PROGRESS | 명령·종료코드·초·비드 수·고정 노드 수(클러스터) |
| BD_LOADS | 하중 80·경계 20 | ESL 수·셀당 노드·경고 수 |
| BD_GRID | PAICAD PROGRESS | 셀 OK/FAIL 수 |
| BD_DESIGNS | 끝난 안 / 대상 안 | `[d012] paicad 34 s OK · solve 12 ESL 8.1 s · score 0.91` |
| BD_POST | 순위 20·view3d 40·산출물 30·보고서 10 | 상위 안·정리한 바이트 |

- 작업 progress 가중: PREP 10·5·60·20·5, PREVIEW 5·90·5, RUN 5·85·9·1.
- 취소: 실행 중 하위 프로세스 트리 종료(localproc), 끝난 안 유지, 진행 중 안 `CANCELED`. 재시도 = `POST /jobs/{id}/retry`(power), BD-D-16 이어하기. 재시도는 연구 스냅샷(prep·doe rev·run 옵션)을 그대로 씀.

## 10. API (접두 `/esl/api`, 기존 오류 형식, 비GET `X-ESL-Request: 1`)

### 10.1 엔드포인트

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `GET /doe/settings` | – | `DoeSettingsOut` | – |
| `POST /doe/check-inputs` | `DoeCheckIn` | `DoeCheckOut` | 404 `UPLOAD_NOT_FOUND`, 409 `UPLOAD_NOT_READY`, 422 `STEP_INVALID`·`MESH_INVALID`·`PART_NOT_FOUND`·`PART_AMBIGUOUS`·`SIZE_MISMATCH`·`MODEL_MISMATCH`·`ENTRY_NOT_FOUND`·`ASSEM_TOO_LARGE`, 503 비활성 사유 |
| `POST /doe/studies` | `DoeStudyIn` | `201 DoeStudyOut`(+ DOE_PREP 작업) | 위 + 422 `INVALID_PARAMS`, 409 `PREREQUISITE_MISSING`(① Case 입력 없음) |
| `GET /doe/studies?project_id=` · `GET /doe/studies/{id}` | – | `[DoeStudyOut]` / `DoeStudyOut` | 404 `DOE_NOT_FOUND` |
| `GET /doe/studies/{id}/params` | – | `DoeParamsOut` | 409 `PREP_NOT_READY` |
| `GET /doe/studies/{id}/plan-view` | – | `DoePlanOut` | 409, 413 `PLAN_VIEW_TOO_LARGE` |
| `GET /doe/studies/{id}/beads/{bead}.png` | – | PNG(extract 비드 그림) | 404 |
| `POST /doe/studies/{id}/matrix` | `{version, spec: DoeSpec}` | `DoeMatrixOut`(생성만, 저장 안 함 — 화면 안 수·경고 즉시 표시) | 422 `DOE_PARAM_UNKNOWN`·`DOE_RANGE_INVALID`·`DOE_TOO_LARGE`·`DOE_NO_PARAMS` |
| `POST /doe/studies/{id}/preview` | `{version, spec}` | `202 DoeStudyOut`(doe.rev+1, DOE_PREVIEW) | 위 + 409 `PREP_NOT_READY`·`JOB_ACTIVE`·`VERSION_CONFLICT` |
| `GET /doe/studies/{id}/preview/thumb/{did}` | – | PNG | 404 |
| `POST /doe/studies/{id}/run` | `{version, matrix_sha256, solver?: "linear"}` | `202 DoeStudyOut`(DOE_RUN) | 409 `PREVIEW_STALE`·`JOB_ACTIVE`·`VERSION_CONFLICT`·`ALREADY_RUN`, 422 `SOLVER_UNSUPPORTED`(linear 외) |
| `POST /doe/studies/{id}/clone` | `{title?}` | `201 DoeStudyOut`(입력·prep 재사용 참조 없이 새 연구 + DOE_PREP) | 404 |
| `GET /doe/studies/{id}/results` | – | `DoeResultOut` | 409 `RESULT_NOT_READY` |
| `GET /doe/studies/{id}/files` · `/download?rel=` · `/bundle?parts=` · `/report` | – | 목록 / 첨부 / zip / HTML | 404·413 |
| `GET /doe/studies/{id}/view3d/{did}/{file}` | – | GLB·values.bin·manifest(기존 view3d 파일 API 규칙) | 404 |
| 기존 `POST /jobs/{id}/cancel`·`/retry`, 로그 | – | 3종에 적용 | – |

### 10.2 스키마

```text
DoeSettingsOut { enabled, reason|null, paicad:{ready, version|null, pinned, warning|null}, gmsh:{ready, version|null},
                 scenarios:{same, mesh, step: bool}, max_entries, max_designs,
                 doe:{methods:["lhs","halton","fullfact"], default_method, default_n, seed, levels_default, levels_max},
                 mesh:{size_auto: true, size_min_mm, size_max_mm}, boundary:{fastener_warn_mm, load_warn_mm, load_share_min},
                 step_max_mb, method_sources }
DoeCheckIn    { project_id, scenario:"same"|"mesh"|"step", entry_ids(1..max_entries), step_upload_id,
                mesh_upload_id? (mesh), part_title? (mesh, 기본 설정 part_title), inch?: int }
DoeCheckOut   { ok, step:{file_name, sha256, size_mb}, base?:{entry_id, case_id, part_title, n_nodes, n_elems, topo_sha256} (same),
                mesh?: MeshCheckOut (mesh — v0.7.0 스키마 그대로), entries:[{entry_id, ok, reason|null}],
                size?:{L_xi, L_eta, inch, rel_xi, rel_eta} (mesh·step: step 은 준비 전이라 null → 준비에서 확정),
                props_default?:{t, E, nu} (step), mesh_size_default_mm? (step), warnings[] }
DoeStudyIn    = DoeCheckIn + { title?(≤200), props?:{t>0, E>0, 0≤nu<0.5} (step), mesh_size_mm? (step, 1..20) }
DoeStudyOut   { id, project_id, scenario, title, entry_ids, inputs:{step{file_name, sha256}, mesh?{…}, part_title, inch, props?, mesh_size_mm?},
                phase:"PREP"|"READY"|"PREVIEW"|"PREVIEW_READY"|"RUN"|"DONE"|"FAILED", version,
                prep:{n_beads, n_params, paicad_version, warnings[], boundary:{n_warn, n_info}}|null,
                doe:{rev, spec, matrix_sha256, n_designs, preview:{rev, matrix_sha256, ok, skipped:{collision, fixed, geom}}|null}|null,
                job|null, result_ready, created_by_name, created_at }
DoeParamsOut  { beads:[{id, k, shape, sense, center_ab:[a,b], nominal{depth,width,length}, fixed_overlap, png}],
                params:[{name, type:"D"|"W"|"U"|"V", bead, nominal, feasible:[lo,hi], feasible_source:"estimate"|"sweep",
                         default_range:[lo,hi], use_default, group_members:[name]}], warnings[] }
DoePlanOut    = v0.7.0 PlanViewOut 형식(frame·outline·holes·elems) + { beads:[{id, ring:[[a,b]…]}],
                fixed:[{label, kind, a, b}] (B), a_points:[{label, a, b}] (②③), load_points:[{entry_id, share, a, b}],
                links:[{from, to, d_mm, warn}] }
DoeMatrixOut  { spec(정규화), matrix_sha256, designs:[{id, values{name: v}}] (d000 포함), n_designs, dropped_duplicates, warnings[] }
DoeResultOut  { C_ref, baseline:{id:"d000", score:1, umax, epsmax}, n_ok, n_skipped{…}, n_failed{…},
                ranking:[{rank, id, values, score, improvement, worst_entry_id, umax, epsmax, umax_all, epsmax_all,
                          noise (③: bool), warnings_n}],
                sensitivity:{method:"src+spearman", r2, params:[{name, src, spearman, main_effects?[{level, mean}] (fullfact)}]}|null (OK < k+2 → null + 사유),
                boundary_warnings_n, view3d:[did], best:{id, files[]}, warnings[] }
```

### 10.3 오류 코드 (신규)

| 코드 | HTTP/작업 | 의미 |
|---|---|---|
| `DOE_DISABLED`·`PAICAD_*`(§6.5)·`GMSH_UNAVAILABLE` | 503 | 비활성 |
| `STEP_INVALID` | 422 | 확장자·`ISO-10303-21;` 머리·크기 > `step_max_mb` |
| `STEP_BODY_COUNT`·`STEP_NOT_SHEET`·`NO_BEADS`·`BODY_MAP_FAILED`·`STEP_MESH_MISMATCH`·`FIXED_PARSE_FAILED`·`PAICAD_INPUT` | 작업 / BD_GEOM | §6.3 |
| `ASSEM_TOO_LARGE` | 422 | ① Case 폴더 rad/inc 합계 초과(BD-D-13) |
| `MESH_TOO_LARGE`·`MESH_FAILED` | 작업 / BD_MESH0 | ③ 베이스라인 메시 |
| `DOE_PARAM_UNKNOWN`·`DOE_RANGE_INVALID`·`DOE_TOO_LARGE`·`DOE_NO_PARAMS` | 422 | §5 |
| `PREP_NOT_READY`·`PREVIEW_STALE`·`ALREADY_RUN`·`RESULT_NOT_READY` | 409 | 순서 |
| `SOLVER_UNSUPPORTED` | 422 | solver ≠ linear |
| `BASELINE_FAILED`·`PAICAD_FAILED`·`PAICAD_TIMEOUT`·`PAICAD_INTERNAL` | 작업 | §6.2 |
| `DOE_NOT_FOUND` | 404 | |
| 재사용 | | `MODEL_MISMATCH`, `SIZE_MISMATCH`, `ENTRY_NOT_FOUND`, `PART_NOT_FOUND`, `PART_AMBIGUOUS`, `MESH_INVALID`, `UPLOAD_*`, `PREREQUISITE_MISSING`, `SUPPORT_DEGENERATE`, `MAPPING_DEGENERATE`, `SOLVER_OUT_OF_MEMORY`, `VERSION_CONFLICT`, `JOB_ACTIVE`, `CONFIG_INVALID`, `PATH_OUTSIDE_ROOT` |

## 11. 결과 처리 (BD_POST, BD-14)
- 순위: BD-D-6. `post/ranking.csv`(id, rank, status, 값들, score, improvement, worst, umax, epsmax, C_i…), `post/designs.json`(전 안 상태).
- 민감도(`esl.doe.rank.sensitivity`): OK 안(베이스라인 포함)의 변수를 [lo,hi] → [0,1] 정규화, score 에 최소자승 선형 회귀 → **SRC**(표준화 회귀계수 = β_j·σ_xj/σ_y)·R², **Spearman ρ**(동률 평균 순위). fullfact 은 수준별 평균(주효과) 병기. OK 수 < 변수 수 + 2 → null + `SENSITIVITY_TOO_FEW`. 결정적.
- 3D 비교: 베이스라인 + 순위 상위 `view3d.top_k`(3) 안에 대해 각자의 최악 ESL 로 `view3d.build_view(post/view3d/<did>/, node_id, x0 = 그 안 좌표, conn, type, f, u_rel = u[:, :3], supports)`. 화면은 기존 `View3DCard` 2개(베이스라인 | 선택 안) 나란히, 같은 색 범위 고정 옵션.
- 산출물: BD-D-18 → `best/<did>/`(순위 1 + 상위 k), zip `parts=best,report,ranking`.
- `report.html`(자체 완결 HTML, `esl/doe/report_doe.py`): 시나리오·입력(STEP·메시·ESL 목록·출처 Case)·paicad 버전·gmsh 버전(③)·변수 표·DOE 방식·seed·행렬 sha·미리보기 스킵 표·순위표(상위 20 + 전체 CSV 링크)·민감도 막대(SVG)·경계 경고 표 + 평면도(SVG)·최적 안 값·**방법·출처 절**(원본 `resources/doe_method_sources.json`: ESL 선형 정의 K_L·u, Park·Kang ESL 계열, Altair ESLM 문서, LHS(McKay 1979)·Halton·SRC/Spearman, paicad 형상 엔진 계약 shell-morph.md) + **한계 절**(선형 강성 비교 — 낙하 응답 재현 아님, ESL 은 원 형상에서 정의돼 형상 변화 후 하중 재분배 미반영, ③ 메시 잡음, feasible 추정, 탄소성 미지원).
- 표시 문구·출처 원본은 자료 파일 1곳(v0.7.0 §9.1 방식), `/doe/settings.method_sources`.

### 11.4 ESL별 개선 지표 (v0.10.0, 사용자 확정 2026-10-29)
근거: score(최악 ESL 절대 컴플라이언스 max)만으로는 한 씬의 문제가 다른 씬으로 옮겨가는 상황(한 ESL 크게 개선·다른 ESL 악화)을 못 본다. 순위(rank·score 정의)는 그대로 두고 지표를 더한다(`esl.doe.rank`, 결정적).

| 키 | 정의 |
|---|---|
| `per_esl[i].ratio` | r_{d,i} = C_{d,i} / C_{d000,i}(베이스라인 같은 ESL 대비). 베이스라인 C ≤ 0 인 ESL 은 빼고 경고 `BASELINE_ESL_ZERO` |
| `worst_ratio` | max_i r_{d,i} — 가장 덜 개선된(또는 가장 악화된) 씬 |
| `min_improvement` | 1 − worst_ratio |
| `all_improved` | worst_ratio < 1 − tol |
| `n_improved`·`n_worsened`·`n_unchanged` | r < 1 − tol · r > 1 + tol · 그 사이(변화 없음) 개수 |
| `geo_mean_improvement` | 1 − (Π_i r_{d,i})^(1/n) |
| `pareto` | 베이스라인(전부 1)·다른 OK 안 어느 것에도 지배당하지 않음(지배 = 모든 i 에서 r ≤, 하나 이상 <) |

- tol = 설정 `bead_doe.rank.ratio_tol`(기본 1e-6), ③ 은 max(ratio_tol, noise_floor). 응답 `ratio_tol`.
- `per_esl` = [{entry_id, label, C, ratio, umax, epsmax}] (ESL 열 순서 = 응답 `esl`). 안 수 × ESL 수 ≤ `bead_doe.rank.per_esl_inline_max`(2000)일 때만 순위 행에(`per_esl_inline: true`), 전부는 `post/per_esl.json` → **`GET /doe/studies/{id}/results/per-esl?design=d001,d002`**(없으면 전부, 최대 max_designs, 없는 안 404 `DESIGN_NOT_FOUND`).
- `GET /doe/studies/{id}/results?sort=score|worst_ratio|geo_mean_improvement|n_worsened|pareto`(기본 score, 그 외 422 `INVALID_PARAMS`). `rank` 필드는 언제나 score 순위.
- `post/ranking.csv` 에 worst_ratio·min_improvement·all_improved·n_improved·n_worsened·geo_mean_improvement·pareto·ratio_<entry> 열. 보고서 순위표에 같은 열 + 'ESL별 개선율' 히트맵(상위 20) + 지표 정의 줄.
- 화면: 순위표 열 [전 씬 개선 ✓/✗] [최소 개선율] [개선/악화 씬 수] [기하평균 개선율] [Pareto ●], 열 머리 클릭 정렬(기본 score), ⓘ 지표 정의. 'ESL별 개선율' 표(행 = 순위 상위 10 + 선택 안, 열 = ESL, 셀 = 개선율 %, 개선 초록·악화 빨강, 가로 스크롤은 표 안에서만).
- v0.10.0 이전 실행 결과에는 지표가 없다(열 '–', 표 대신 "복제해 다시 실행" 안내).

## 12. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 화면당 주 버튼 1개)

### 12.1 라이브러리 (변경)
- 선택 줄에 [선택한 ESL로 비드 DOE (n)] 버튼 1개 추가(기존 [선택한 ESL로 비드 최적화] 옆), 탭에 [비드 DOE] 목록 추가.

### 12.2 새 비드 DOE `/doe/new` · 상세 `/doe/:id` (한 화면, phase 에 따라 카드가 열림)
```
비드 DOE · 75형 Ch/R 1차    [● 같은 모델 ○ 다른 모델(메시 있음) ○ 다른 모델(STEP만)]       [입력 준비 | 미리보기 | DOE 실행](주, 단계별 1개, 비활성 사유 툴팁)
┌① 입력──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ESL (3) 75QN80H v072 17 Corner ✓ … [다른 모델 빼기]   STEP [chassis_mid.step ▓▓▓ 100%]  (②) 메시 [B.rad+3 inc] 파트[chassis rear]│
│ (③) 두께 [1.2] mm  E [205000] MPa  ν [0.3]  요소 크기 [5.0] mm(자동: A 중앙값)   크기 검사: ξ +1.2 % η −0.8 % ✓       │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
┌② 비드·변수 (준비 후)──────────────────────────┐┌③ 평면도 (비드 번호·경계 경고 — ②③)────────────────────┐
│☑ B1 선형 오목  D [3.0–6.0] 공칭 4.0 (feasible 2.1–6.4) ││  ┌───────────────────────────────┐ 경고 2               │
│☑      W [10–16]  공칭 12                            ││  │ ×A RBE2 ─ ─ ○B 구멍 14 mm ⚠   │ ×A 체결 ○B 구멍 ●하중 │
│☐      U [ … ]  (위치 — 기본 제외)                  ││  └───────────────────────────────┘                     │
│ B5 원형  ⚠ 고정 겹침(기본 제외)                     │└──────────────────────────────────────────────────────┘
│ 방식 [LHS ▼]  안 수 [30]   (풀 팩토리얼: 수준 [3] → 안 9)  → 실제 31안(공칭 포함, 중복 0) │
└────────────────────────────────────────────────────┘
┌④ 미리보기 (31) OK 27 · 충돌 3 · 고정 침범 1─────────────────────────────────────────────────────────┐
│ [d000 공칭][d001][d002 ⨯충돌][d003] … 썸네일 8열 격자(320×240 축소 표시), 스킵 = 회색+사유 배지, 클릭 = 값 툴팁     │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
┌⑤ 결과 (실행 후) 진행 ✓베이스라인 ● 안 18/27 · [로그][취소]──────────────────────────────────────────┐
│ 순위  안    score  개선율  최악 ESL      umax   εmax    B1_D  B1_W  …  경고        경계 경고 2 (머리)     │
│ 1    d014  0.81  +19 %  17 Corner 146  3.4mm  0.21 %  5.2   14.1        ⓘ                              │
│ 민감도 막대(SRC·ρ)   |  3D 비교 [베이스라인 | d014 ▼] (View3DCard 2개, 색 범위 같게)                     │
│ 받기 [최적 안 include/메시] [BREP/STEP] [순위 CSV] [zip]  [보고서 보기]                                  │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
- 1920 폭: ②·③ 위아래로 접힘, 썸네일 6열, 순위표 변수 열은 가로 스크롤 대신 접힘(값은 행 펼치기).
- 솔버 선택 칸 없음(확정 6). seed 는 ④ 머리에 표시만(바꾸려면 API — 필수 UI 아님).
- 경계 경고 표는 ③ 아래 접힘 목록(라벨·거리·기준).

## 13. DB 변경 — migration `0011_bead_doe`
- 번호·체인: BD-D-21. 멱등(0001 create_all 대비 checkfirst·IF NOT EXISTS·제약 DROP IF EXISTS 후 재추가), downgrade 미지원.
- **`bead_does`**: `id`, `project_id` FK, `scenario` varchar(4) CHECK IN ('same','mesh','step'), `title`(200), `entry_ids` JSONB(≥1), `base` JSONB NULL(① 기준 entry·case·part — 서버 경로 없음, 경로는 작업 params 에만), `inputs` JSONB(step·mesh upload_id·sha256·file_name, part_title, inch, props, mesh_size_mm), `phase` varchar(16) CHECK, `version` bigint ≥1(낙관적 잠금), `prep` JSONB NULL, `doe` JSONB NULL(rev, spec, matrix_sha256, n_designs, preview 요약), `run` JSONB NULL(solver, parallel), `result` JSONB NULL(DoeResultOut 요약 — ranking 은 max_designs 행 이내), `report_rel`, `dir_rel`(`_doe/<id>`), `paicad_version` varchar(32) NULL, `created_by(_name)`, `created_at`, `updated_at`. CHECK `scenario <> 'same' OR base IS NOT NULL`. Index `(project_id, created_at desc)`.
- `jobs.bead_doe_id` FK NULL + `ix_jobs_bead_doe` + `ux_jobs_bead_doe_active`(비종료 1개). CHECK 교체: `ck_jobs_job_type`(+DOE_PREP·DOE_PREVIEW·DOE_RUN), `ck_jobs_stage` 1~11, `ck_jobs_subject`(DOE 3종 분기 = bead_doe_id NOT NULL·나머지 NULL, 기존 분기에 `bead_doe_id IS NULL`). `ck_artifacts_kind` += `DOE_RESULT`.
- `uploads` 변경 없음(`purpose` 값 `doe_step`·`doe_mesh` 는 기존 JSONB).

## 14. 설정 키 (하드코딩 금지, `config/esl_platform.example.yaml`·prod 예시)

```yaml
commands:
  paicad_version: ["{paicad}", "version", "--json"]
  paicad_fixed_scan: ["{paicad}", "shell", "fixed-scan", "--assem-dir", "{assem_dir}", "--parts", "{parts}", "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"]
  paicad_extract: ["{paicad}", "shell", "extract", "--cad", "{cad}", "--out-dir", "{out_dir}", "--assem-dir", "{assem_dir?}", "--body-map", "{body_map?}", "--options", "{options?}", "--threads", "{threads}"]
  paicad_tag: ["{paicad}", "shell", "tag", "--cad", "{cad}", "--features", "{features}", "--assem-dir", "{assem_dir}", "--fixed-dir", "{fixed_dir}", "--out-dir", "{out_dir}", "--body-map", "{body_map?}", "--options", "{options?}", "--threads", "{threads}"]
  paicad_grid: ["{paicad}", "shell", "view", "grid", "--cad", "{cad}", "--features", "{features}", "--cells", "{cells}", "--thumb-options", "{thumb}", "--fixed-dir", "{fixed_dir}", "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"]
  paicad_run: ["{paicad}", "shell", "run", "--cad", "{cad}", "--features", "{features}", "--values", "{values}", "--assem-dir", "{assem_dir}", "--tag-dir", "{tag_dir}", "--fixed-dir", "{fixed_dir}", "--update-dir", "{update_dir}", "--morph-dir", "{morph_dir}", "--check-dir", "{check_dir}", "--out-files-dir", "{out_files_dir}", "--body-map", "{body_map?}", "--options", "{options?}", "--threads", "{threads}"]
  paicad_update: ["{paicad}", "shell", "update", "--cad", "{cad}", "--features", "{features}", "--values", "{values}", "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"]
bead_doe:                                # 섹션 없으면 enabled: false
  enabled: true
  part_title: "chassis rear"            # ② B 메시 기본 파트 제목(case.part_title 과 같은 규칙)
  max_entries: 50
  max_designs: 200
  step_max_mb: 200
  same: {max_assem_mb: 4096}            # ① Case 폴더 rad/inc 합계 상한(BD-D-13)
  paicad:
    exe: null                           # setup_config 자동 감지(<런타임 venv>/Scripts/paicad.exe 있을 때만)
    min_version: "0.14.0"
    pinned_version: "0.14.0"
    threads: 4
    timeout_s: {version: 60, fixed_scan: 3600, extract: 3600, tag: 3600, grid: 7200, run: 3600, update: 1800}
    options: {}                         # paicad shell options.json 내용(선택)
    env: {}
    keep_files_top: 3
    check_interval_s: 600               # 워커 paicad/gmsh 점검 주기
  mesh: {size_min_mm: 1.0, size_max_mm: 20.0, min_size_factor: 0.2, curvature_n: 12, algorithm: 8, min_quad_frac: 0.8, max_elems: 500000, timeout_s: 1800, occ_sew_faces: 0}
  doe: {default_method: lhs, default_n: 30, seed: 1, levels_default: 3, levels_max: 9, round_mm: 0.01, default_types: [D, W]}
  preview: {w: 320, h: 240, view_dir: auto, tilt_deg: 20, margin: 1.15, disp_range_mm: auto}
  run: {parallel: 2, memory_margin: 0.7}
  solve: {reaction_warn: 0.01}           # 솔버 drill_factor·backend 는 opt_run.solver 재사용
  boundary: {fastener_warn_mm: 10.0, load_warn_mm: 20.0, load_share_min: 0.2}
  view3d: {top_k: 3}
  settings_cache_s: 300
upload:
  allowed_ext: [..., .step, .stp]
```
- 크기 허용(`opt_run.size`)·구멍 루프(`opt_run.keepout.hole_min_perimeter_mm`)·솔버(`opt_run.solver`)·셀 매핑(`library.yaml` mapping)은 기존 키 재사용(새 키 만들지 않음). 환경 점검(`check.py`): paicad exe·버전·OCP, gmsh import, `_doe` 쓰기 가능.

## 15. 보안 · 권한
- 조회 = ACTIVE 로그인 + 프로젝트 조회 권한. 쓰기(연구 생성·미리보기·실행·복제·취소·재시도) = 프로젝트 power 이상(다른 사용자 작업 취소·재시도는 전역 관리자 — 기존 `_can_touch`). 판정 순서 401→404→403→409.
- 선택 ESL 은 요청 프로젝트의 활성 항목(아니면 422 `ENTRY_NOT_FOUND`), ① 기준 Case 도 같은 프로젝트(409 `PREREQUISITE_MISSING`). 업로드는 본인 것만(본인 폴더 격리·`_backup` 차단·심링크 거부).
- **입력 폴더 읽기만**: Case 입력(① paicad `--assem-dir` 제자리)·업로드 폴더에 쓰지 않음. paicad 는 `--out-dir` 류에만 쓰며 플랫폼이 넘기는 출력 경로는 모두 `_doe/<id>/` 안(realpath 검사 후 호출). ① Case 폴더는 `check_includes`·input_roots 검사 통과분만, include 가 루트 밖이면 `PATH_OUTSIDE_ROOT`(v0.7.0 결정 77). 폴더 안 심링크·정션이 있으면 거부(`PATH_OUTSIDE_ROOT`) — paicad 재귀 수집이 링크를 따라가지 않게.
- ② B 메시 복사: 업로드 밖 include 거부, 복사 후 sha256 재확인.
- 외부 실행: 워커 LOCAL step 만, argv 템플릿(argv[0] `{paicad}` 허용목록), shell=False, 메타문자 거부, env 최소, 타임아웃·트리 종료. gmsh 는 코어 하위 프로세스(외부 명령 아님) — 입력은 `_doe/<id>/` 안 BREP/STEP 만.
- 응답·로그에 서버 절대경로 없음(일반 사용자). argv·paicad.log 받기는 전역 관리자만. 다운로드 `rel` = 파일 목록 + realpath `_doe/<id>/` 안. 보고서 HTML 이스케이프·CSP 기존 규칙. 디스크 여유 부족 507.
- npz `allow_pickle=False`, paicad JSON 은 크기 상한(`ui.max_json_mb`) 후 파싱, PNG 는 머리 검사 후 그대로 전달.

## 16. 검증 계획 (V-BD-*)

| ID | 시험 | 위치 |
|---|---|---|
| V-BD-1 | DOE 생성: lhs·halton·fullfact 범위·층 성질(LHS 각 변수 층당 1점), 같은 (spec, seed) → 같은 행렬 sha(10회·입력 순서 섞기), 반올림·중복·공칭 제거, max_designs 경계, D·W 하한·lo≥hi 422, feasible 밖 경고, API 와 워커 행렬 sha 동일 | `tests/doe/test_matrix.py`, `backend/tests/test_doe_api.py` |
| V-BD-2 | paicad argv: 선택 쌍 제거·빈 문자열 유지(③ fixed-dir), null 필수 자리 CONFIG_INVALID, 경로 realpath 검사, 사용자 문자열 미포함, env 최소, shell=False | `worker/tests/test_paicad_proc.py` |
| V-BD-3 | 가짜 paicad(`tests/fake_paicad.py`: 정상·종료 2/3/10/11/12/13/14/20·타임아웃·보고 없음·PROGRESS 중계·취소) → 코드 매핑 표 §6.3·모르는 코드 범주 분류·`doe_messages.json` 스키마·버전 점검(낮음·OCP null·고정 불일치 경고) | `worker/tests/test_paicad_proc.py`, `tests/doe/test_messages.py` |
| V-BD-4 | ① 동일성(topo)·다른 모델 422, 모핑 노드 읽기(바뀐 파일만·ID 불변·누락 노드 오류·좌표 필드만), 노드 직접 하중이 모든 안에 같음, `BD_BASE_CUMULATIVE`, `ASSEM_TOO_LARGE` 경계 | `tests/doe/test_same.py` |
| V-BD-5 | ② 크기 ±5 %·인치, B 베이스라인 1회 매핑·지지가 모든 안 동일(ID 불변), 셀 합력·합모멘트 보존 1e-9, `B_NO_FASTENERS` | `tests/doe/test_mesh_scn.py` |
| V-BD-6 | ③ gmsh: 평판·비드 BREP → quad_frac ≥ 0.8, h 반영(모서리 중앙값 ±20 %), 같은 입력 2회 → mesh.npz 바이트 동일(단일 스레드), 법선 정렬, 품질 오류 FAILED_MESH, max_elems, 타임아웃, STEP 내보내기; 잡음 바닥 측정(공칭 BREP 왕복 재메시 score 차) 기록 | `tests/doe/test_mesh_gmsh.py`(gmsh 없으면 skip — CI 레인은 gmsh 설치 필수) |
| V-BD-7 | 해석: 분해 1회(stats n_factorizations = 1/안), C·umax·εmax 가 개별 `solve` 와 1e-9 일치, 반력 잔차 경고, 지지 퇴화 FAILED_SOLVE | `tests/doe/test_eval.py` |
| V-BD-8 | 순위: C_ref = 베이스라인 최악, score·개선율·동률 id 순, 스킵·실패 제외, OK 0 → NO_FEASIBLE_DESIGNS, ③ 잡음 이내 표시 | `tests/doe/test_rank.py` |
| V-BD-9 | 민감도: 합성 선형 응답 → SRC 정확(1e-9)·R²=1, 단조 비선형 → ρ=1, fullfact 주효과, 표본 부족 null | `tests/doe/test_rank.py` |
| V-BD-10 | 경계 경고: 합성 A 체결점·B 구멍(거리 9.9/10.1 mm), 하중 집중 비율 경계, B 후보 0, A Case 없음 → A_FASTENERS_UNKNOWN, 정규화 옮김 식, 평면도 자료 = 워커 판정 같은 함수 | `tests/doe/test_boundary.py` |
| V-BD-11 | 작업: PREP/PREVIEW/RUN step·진행률, 순서 409, 병렬 상한·메모리 자동 축소, 취소 트리 종료·끝난 안 유지, 재시도 이어하기(done.json 같으면 SKIPPED, FAILED 만 재실행), 베이스라인 실패, 파일 정리(상위 k·베이스라인만 남김) | `worker/tests/test_doe_jobs.py` |
| V-BD-12 | API: 권한·오류 표 §10.3·`PREVIEW_STALE`·`VERSION_CONFLICT`·solver ≠ linear 422·비활성 사유·`/doe/settings` 관리자만 경로·다운로드 탈출·bundle 상한 | `backend/tests/test_doe_api.py` |
| V-BD-13 | migration 0011(빈·0010 DB, 멱등, tables.py 일치, 기존 행 제약, MCP 0009 를 0011 뒤에 붙인 체인 단일 head) | `backend/tests/test_migrations.py` |
| V-BD-14 | 입력 보호: ① Case 폴더·② 업로드 폴더 실행 전후 파일 목록·mtime·sha 불변, 심링크 폴더 거부, paicad 출력이 `_doe/<id>/` 밖으로 안 감 | `worker/tests/test_doe_e2e.py` |
| V-BD-15 | E2E(가짜 paicad·실 gmsh·실 솔버): ① 합성 평판 ESL 3개 / ② 다른 크기 내 B 메시 / ③ STEP 만 → 순위·민감도·view3d·산출물·보고서·이력·알림 | `worker/tests/test_doe_e2e.py` |
| V-BD-16 | **실 paicad 통합(SM1)**: paicad `tests/data/make_synthetic_shell.py OUT` 로 SM1(400×300 판금·비드 5·구멍 6·RBE2×6·tie 2) 생성 → SM1 메시에 합성 자기평형 ESL 3개 등록 → ① extract 비드 5(B5 `BEAD_FIXED_OVERLAP` use_default false·B4 `BEAD_NEAR_FIXED`)·tag·grid(충돌 안 FAIL 표시)·run → 노드 ID 불변·고정 노드 줄 불변 / ③ `--fixed-dir ""` grid·update + gmsh 메시. **가능**: 생성기는 paicad `test` extra(build123d 0.10.0·ocp_gordon 0.1.18·gmsh)가 필요 → CI 에 별도 레인 `ESL_TEST_PAICAD=1`(lock 의 paicad wheel + test extra), 생성물은 커밋하지 않고 레인 캐시. 기본 레인은 가짜 paicad | `tests/doe/test_paicad_sm1.py` |
| V-BD-17 | UI: 시나리오 라디오·입력 카드(시나리오별 칸)·준비 후 비드 표(체크·범위·feasible 밖 배지)·방식 드롭다운(fullfact 수준·실제 안 수)·미리보기 격자(스킵 배지)·주 버튼 단계 전환·비활성 사유·순위표·민감도·3D 비교 2개·받기, 솔버 칸 없음, 2560×1440·1920×1080 잘림 없음(Playwright) | `frontend/__tests__/doe.test.tsx`, mock |
| V-BD-18 | 배포: `deploy/paicad.lock` 형식·sha 대조, requirements.lock 에 OCP·gmsh, `$EslAppItems`·collect-offline 에 `resources/doe_*.json`, setup_config 자동 감지(파일 있을 때만·기존 값 불변·BOM/CRLF 유지), allowed_ext 보충 | `tests/deploy/test_bead_doe_deploy.py` |
| V-BD-R1 | **실기**: 실제 Ch/R(22만 요소) ① — Case 폴더 크기·paicad fixed-scan/tag/run 시간·메모리·`out_files` 크기, 안 30개 총 시간, 썸네일. ② 다른 인치 B 메시, ③ STEP 만(h 3·5 mm 메시 시간·잡음 바닥) | `docs/manual/bead_doe_check.md` |

## 17. 구현 분해 (파일 소유권)

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| D1 코어 | Impl-Core | `esl/doe/__init__.py`, `matrix.py`(lhs·halton·fullfact·sha), `paicad_io.py`(paicad 보고 JSON 파싱·변수 표·셀 결과·코드 분류 — 실행 없음), `nodes.py`(모핑 사본 `/NODE` 읽기, readline 상한), `mesh_gmsh.py`(§7), `scenario.py`(①②③ 기준 메시·frame·지지·하중 — `esl.opt.target`·`size`·`identity` 재사용), `boundary.py`(§8.2), `evaluate.py`(안 해석 — `ShellModel.factorize`), `rank.py`(순위·민감도), `report_doe.py`, `export_mesh.py`(③ rad·fem 쓰기), `stages.py`(bd_input·bd_mesh0·bd_loads·bd_matrix·bd_eval·bd_post 진입점); `resources/doe_messages.json`·`doe_method_sources.json`; `tests/doe/*` | V-BD-1, 4~10, 16(코어분) |
| D2 백엔드 | Impl-Backend | `migrations/versions/0011_bead_doe.py`, `core/db/tables.py`, `core/job_types.py`, `core/config.py`(BeadDoeCfg·commands paicad_*), `core/paths.py`(`DOE_DIR="_doe"`), `core/repositories/doe.py`, `api/routers/doe.py`, `api/services/doe.py`(check-inputs·studies·matrix·preview·run·results·files), `api/schemas.py`, `api/services/uploads.py`(.step 머리·purpose), `api/services/history.py`, `check.py`, `config/*.example.yaml`, `backend/tests/test_doe_*.py`·`test_migrations.py` | V-BD-12, 13 |
| D3 워커 | Impl-Worker | `worker/esl_worker/paicad_proc.py`(argv·선택 쌍·env·PROGRESS/RESULT·버전 점검·`worker_heartbeats.info.paicad` 기록), `doe_jobs.py`(PREP/PREVIEW/RUN 조립·안 스레드 풀·이어하기·정리), `executor.py`, `core_adapter.py`(bd_* 단계), `register.py`(BD_*_REGISTER), `worker/tests/test_doe_*.py`·`test_paicad_proc.py`, `tests/fake_paicad.py` | V-BD-2, 3, 11, 14, 15 |
| D4 프런트 | Impl-Frontend | `api/doe.ts`, `api/types.ts`, `pages/doe/DoeStudy.tsx`(새·상세 한 화면), `DoeList.tsx`, `components/DoeInputs.tsx`, `DoeParamTable.tsx`, `DoeThumbGrid.tsx`, `DoeRanking.tsx`, `Sensitivity.tsx`, `BoundaryPlan.tsx`(KeepoutPlan 렌더러 재사용), `view3d/View3DCard.tsx`(색 범위 고정·변위 값 선택 옵션만 추가), `pages/library/LibraryList.tsx`(버튼·탭), `app/App.tsx`, `mock/doedata.ts`, `__tests__/doe.test.tsx`, `pages/guide/*` | V-BD-17 |
| D5 배포 | Impl-Backend(deploy) | `deploy/paicad.lock`, `deploy/requirements.lock`(+cadquery-ocp·gmsh), `deploy/collect-offline.sh`·`.ps1`(paicad wheel 빌드·대조), `deploy/install*.ps1`, `deploy/setup_config.py`, `deploy/RESOURCES.txt`, `tests/deploy/test_bead_doe_deploy.py` | V-BD-18 |
| D6 문서 | Plan/Impl | `CHANGELOG.md`·`VERSION` 0.9.0, `docs/decisions.md`, `docs/manual/user.md`, `docs/manual/admin.md`(paicad 설치·버전), `docs/manual/bead_doe_check.md` | V-BD-R1 체크리스트 |

- 순서: D1(matrix·rank·boundary·mesh_gmsh 먼저) → (D2 ∥ D3, D3 은 D2 job_types·tables·config 선행) → D4(mock 병행) → D5 → 통합 E2E → SM1 레인 → 실기(③ → ② → ①).
- 경계: 백엔드는 코어 `esl.doe.matrix`·`paicad_io`(준비 결과 읽기)·`esl.opt.size`·`identity`·`mesh_check` 만 import(수 초 이내). gmsh·쉘 솔버·대형 rad·paicad 실행은 워커에서만. paicad 소스는 import 하지 않는다(외부 명령으로만).
- physicsai 쪽 개선 후보 2건(`shell view grid --fixed-dir` 선택 인자화 — BD-D-11, `shell run` 노드 좌표 npz 출력 — R-BD-2)은 **사용자 판단 사항**이며, v0.9.0 은 요청 없이 동작한다.

## 18. 후속 (v0.9.0 범위 밖)
- **탄소성 정적**(OptiStruct NLSTAT + MATS1, Radioss 재료 `/MAT/LAW36` → MATS1 변환): API `solver` 값 추가로 연다. **근거 기록**: ESL 은 F_eq = K_L·u_drop(선형 강성 × 낙하 변위)으로 정의되므로, 이를 탄소성 정적에 그대로 넣으면 낙하 응답(변위·소성)을 재현하지 못하는 왜곡이 생긴다 — 같은 하중에서 소성 연화로 변위가 과대해짐. 따라서 탄소성은 **상대 비교·잔류 변형 확인 용도**로만 쓰고, 선형 순위 상위 k 개만 재평가하는 **2단계**(1단계 선형 DOE → 2단계 상위 k 탄소성)로 설계한다.
- 비드 개수·종류 변경(비드 추가·삭제, 위상 변경 — paicad 위상 보존 모핑 밖), 리브·두께 파라미터.
- 대리모델·순차 탐색(DOE → 다음 안 제안), 다목적(무게·제조성).
- 최적 안의 검증 낙하 자동 실행·라이브러리 등록, 연구 간 비교.
- ① 대형 씬 축소 조립(Ch/R + 체결 상대만 자동 추출) — v0.9.0 은 Q1 A(상한 초과 시 거부·② 안내).

## 19. 확정 사항 (2026-10-29, 사용자)

| 항목 | 확정 | 반영 |
|---|---|---|
| Q1 ① 조립 폴더(대형 낙하 씬) | **A**: 기준 ESL Case 입력 폴더를 제자리로 그대로 사용(읽기만). rad/inc 합계 > `bead_doe.same.max_assem_mb`(기본 4096, 설정 키)면 422 `ASSEM_TOO_LARGE` + ② 로 안내 | BD-D-13, §10.3, §14, R-BD-1 |
| Q2 ③ 쉘 물성 | **A**: A 모델 Ch/R 면적 가중 두께 중앙값·주 PID E·ν 를 기본값으로 채우고 화면 3칸(t·E·ν)에서 수정 | §3.3, §7.3, `DoeCheckOut.props_default` |
| Q3 미리보기 | **A**: 같은 `matrix_sha256` 미리보기가 성공해야 [DOE 실행] 활성(서버 409 `PREVIEW_STALE`) | BD-D-9, §10.1, R-BD-5 |
| physicsai 쪽 개선 후보 2건 | 노드 좌표 npz 출력·`--fixed-dir` 선택 인자 = **사용자 판단 사항**, v0.9.0 은 요청 없이 동작 | §17, R-BD-2·7 |

## 20. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-BD-1 | ① 대형 낙하 씬에서 paicad fixed-scan·tag·run 시간·메모리(paicad 실측은 SM1·쿠션 수준) | 상한 설정 키(BD-D-13, Q1 A)·② 안내, V-BD-R1 실측 후 상한 조정, 타임아웃 설정 |
| R-BD-2 | 안마다 바뀐 rad 파일 사본(수 GB) 디스크·I/O | 상위 k 외 삭제(BD-D-17), max_designs (physicsai 노드 npz 출력은 사용자 판단 사항 — v0.9.0 은 요청 없이 동작) |
| R-BD-3 | ESL 은 원 형상 K_L 로 정의 — 비드 변경 후 같은 하중을 쓰면 하중 재분배 미반영(선형 상대 비교 한계) | 보고서 한계 절, 개선 확인은 검증 낙하 1회 권장 안내 |
| R-BD-4 | ③ 안별 재메시 잡음이 작은 개선을 가림 | 베이스라인 같은 메시 규칙·잡음 바닥 측정·"잡음 이내" 표시(§7.2) |
| R-BD-5 | feasible 은 추정 — 범위 안에서도 morph/check 실패 | 미리보기 필수(Q3 A), 안별 스킵·실패 기록 |
| R-BD-6 | paicad 버전 변화로 보고 JSON 키 변경 | 버전 고정 lock·min_version, `paicad_io` 키 검사·스키마 시험(V-BD-3·16) |
| R-BD-7 | `--fixed-dir ""` 의존(③) | SM1 실검(V-BD-16), 실패 시 대체 = 베이스라인 rad 로 fixed-scan(빈 고정) (physicsai 선택 인자화는 사용자 판단 사항 — v0.9.0 은 요청 없이 동작) |
| R-BD-8 | 오프라인 묶음에 OCP·gmsh(수백 MB) 추가, gmsh 라이선스(GPL + 예외) | 사내 설치 용도·THIRD_PARTY 표기, 묶음 크기 기록 |
| R-BD-9 | 모핑 후 ESL 모멘트 평형 약간 깨짐 → 3-2-1 반력 | 반력 잔차 경고(BD-D-5) |

## 21. 구현 반영 (v0.9.0 통합, 2026-10-29)

계약 확정 뒤 구현(D1~D5)에서 정한 세부. 본문은 이 표대로 고쳤다.

| 항목 | 반영 | 근거 |
|---|---|---|
| paicad 점검 기록 위치 | §6.5 `worker_status.extra.paicad` → **`worker_heartbeats.info.paicad`**·`info.gmsh` | `worker_status` 테이블은 없음 — 워커 상태는 기존 `worker_heartbeats.info`(JSONB, `claims_paused` 등) 한 곳. 백엔드는 가장 최근 heartbeat 를 읽기만 |
| 공칭 d000 썸네일 | §5 워커가 grid 셀에 `nominal`(values {}) 추가 → `grid/cells/nominal/thumb.png`, `GET …/preview/thumb/d000` 이 그 경로 | paicad 0.14.0 `shell view grid` 는 `grid_manifest.nominal` 에 bbox·view_sha256 만 쓰고 공칭 그림을 만들지 않음(소스 확인). 셀 id 규칙 `[0-9a-z_]{1,64}` 안 |
| gmsh 면 봉합 | §7.1·§14 `bead_doe.mesh.occ_sew_faces`(기본 0, 0·1) | 계약 기본(0)은 유지, 면 공유가 없는 STEP(gmsh 가 다시 쓴 STEP 등)은 1 이 필요해 설정 키로(하드코딩 금지) |
| gmsh 격리 | §7.1 메시마다 `multiprocessing` spawn 자식 | gmsh 는 프로세스 전역 상태·시그널 처리기를 가져 같은 프로세스 반복 호출·타임아웃 강제 종료가 불안정. spawn = Windows 기본과 같은 방식, 크래시·타임아웃을 안 1개 `FAILED_MESH` 로 가둠 |
| paicad wheel sha256 | §6.4 **정규화 sha256**(`deploy/paicad_wheel.py`) | `pip wheel` 결과 zip 은 빌드 시각·압축 구현·권한에 따라 바이트가 달라 lock sha256 하나로 대조할 수 없음 — 내용은 같고 바이트만 다른 차이를 정규화로 없앰. RECORD(파일별 해시)는 그대로라 설치 검증 영향 없음 |
| migration 0010 수정 | BD-D-21 — 0010 CHECK 를 0010 시점 고정 상수로 | 0010 이 `tables.CK_JOBS_SUBJECT`(0011 의 `bead_doe_id` 참조)를 쓰면 0008 운영 DB 를 0011 로 올릴 때 0010 단계에서 없는 열을 참조해 실패. 0004 와 같은 '마이그레이션은 그 시점 정의를 고정' 규칙. 새 DB(0001 create_all)·0008·0010 DB 모두 같은 결과(V-BD-13) |
| 화면 보강 칸 | §10.2 `DoeStudyOut.doe.preview.cells[{id, values, status, code, thumb}]`, `DoeResultOut.excluded[{id, status, code, values}]`·`noise_floor`, `DoePlanOut.links[].from_ab·to_ab·kind`(②③), `DoeSettingsOut.doe.default_types`·`part_title`, `best.files[{rel, size, downloadable}]` | 썸네일 배지·순위 밖 안·선 긋기·기본 변수 종류에 필요(계약 요약 칸만으로는 안별 표시 불가). 백엔드 응답 = 프런트 types.ts(check:api + 실서버 E2E `scripts/e2e_doe.mjs` 대조) |

