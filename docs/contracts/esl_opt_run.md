# 계약: 비드 최적화 서버 실행 (OPT_RUN, v0.7.0)

- 상태: **확정** (2026-10-28, 사용자 1차 확정 Q1~Q5 + 2차 확정(비드 금지 영역·비드 치수 기본값) + 3차 확정(하중 선정 전략 A/B/C 선택 — 기본 A 전부 넣기 + |MAC| 병합·군집, 모드는 표시·전략 B 용, 방법·출처 표시, 목표 기준 절대(기본)/상대), §17). 미결 없음. 구현 코드 없음.
- 버전: **v0.7.0** (v0.6.0은 `esl_upload_speed.md`가 사용).
- 대체 범위: `esl_p2_library.md` §4 "실행은 사용자 측(Windows/HPC)… 결과 회수·후처리는 P3", `esl_p3_ux.md` §7 "OptiStruct 비드 덱 실행은 P4" 중 **서버 워커 실행** 부분. HPC/PBS 제출은 여전히 범위 밖. 충돌 시 이 문서 우선. 종합분석(LIB_ANALYZE)의 덱 생성·하중 구성(§12.1 all/대표/최악)은 **그대로 유지**(PC 실행용) — OPT_RUN 의 하중 구성은 이 문서 §7.4.
- ID 규칙: 결정 `OR-D-n`, 요구 `OR-n`, 시험 `V-OR-n`, 리스크 `R-OR-n`.
- 사용자 확정 사항(2026-10-28, 변경 금지):
  1. 라이브러리에서 ESL 여러 개를 골라 비드 최적화에 넣는다(라이브러리·종합분석 화면 연결).
  2. 서버 워커에서 직접 실행(OPT_RUN, 기존 워커·작업 대기열 재사용, 사용자 PC 실행 아님).
  3. 시나리오 2개: **S1 기존 rad 형상 최적화**(케이스 대상 파트, 하중 노드 직접 적용, 같은 모델 ESL만), **S2 템플릿 최적화**(등록 템플릿 메시, 같은 크기 ESL, 정규화 좌표 (ξ,η) 24×14 셀 합력·합모멘트 매핑).
  4. S2 템플릿: `.fem` 또는 `.rad` 쉘 메시 등록(기존 청크 업로드), 모든 사용자에게 공개, 삭제는 등록자·관리자만, 실행이 참조 중이면 보관(soft delete). CAD/STEP 은 후속(§16).
  5. 크기(인치/치수)가 다른 ESL은 S2에서 사용 불가: 같은 인치 + 치수 ESL 간 ±2 %, 템플릿과 ±5 %. S1은 모델 동일성 판정으로 대체.
  6. 비드 방향 = 지금 덱과 같음(요소 법선 = +n 쪽, BOUNDS 0~1).
  7. 결과는 라이브러리에 넣지 않고 "최적화 실행" 목록에 보존.
  8. 라이선스 부족 = 3회 × 300 초 자동 재시도 후 실패.
  9. 저장소의 DTPG 덱 생성 코드(`esl/library/optdeck.py`)를 서버 실행으로 연결.
  10. UI 필수 버튼만, 2560×1440 기준(1920×1080 잘림 없음). 환경별 경로·솔버 경로는 설정 파일, 하드코딩 금지. **입력 폴더 쓰기 금지**.
  11. **비드 금지 영역** = 자동 제외(마운트 구멍 주변 반경, 가장자리 띠 폭 — 설정 mm) + 사용자 사각형 여러 개(가로·세로 mm, 기준 모서리 = ξη 평면 경계 4코너 중 하나, 그 모서리에서 X·Y 거리 mm). 2D 평면도 미리보기·드래그 이동 시 숫자 동기화. 사각형 세트는 S2 템플릿 또는 S1 모델(`topo_sha256`)에 저장해 다음 실행에서 불러오기. 덱에서 해당 요소는 비설계(DTPG 제외).
  12. **다중 ESL 목표**(3차 확정) = 실행 화면에서 하중 선정 전략 라디오 1그룹으로 선택, 기본 **A(추천 배지)**. 모든 전략에서 ESL 1개 = 하중 케이스 1개(각 ESL 은 이미 t* **단일 시점** — 시간 구간 전체를 넣지 않음), 목표는 min-max 컴플라이언스, 기준은 '목표 기준' 선택(§2 OR-D-15: 절대 기본·상대 옵션, 사용자 가중 없음). **A 전부 넣기**(KIT 비드 최적화 연구 방식): 선택 ESL 전부, 변위 형상 유사도 |MAC|(부호 무관 — F→−F 는 컴플라이언스가 같으므로 반대 방향 토션 자동 병합) ≥ `opt_run.loads.mac_merge`(0.95) 쌍은 초기 컴플라이언스 큰 쪽만, 남은 수 > `opt_run.loads.max_cases`(20)이면 |MAC| 거리 결정적 계층 군집(average linkage) 군집별 최악 1개. **B 모드별 최악**: 변형 모드(덴팅·뒤틀림·굽힘)별 초기 컴플라이언스 최악 1개, 최대 3개. **C 군집 대표 k개**: |MAC| 군집 k개(숫자 입력, 기본 5, 1..max_cases) 군집별 최악 1개. 전략값은 `opt_runs` 에 저장, 선정 표·보고서에 표시.
  13. **비드 치수** = 실행 화면 숫자 3칸, 기본 경사 45°, 폭 60 mm, 높이 10 mm(설정 키).
  14. (가정 확정) S1 법선 = 원 연결 유지·반대 법선은 경고만, 템플릿 인치 = 선택 입력.
  15. **변형 모드**(덴팅·뒤틀림·굽힘, w(ξ,η) 저차 다항식 적합 자동 분류 + 사용자 수정·저장)는 표시·보고서·라이브러리 분류/검색에 쓰고, 하중 선정에는 **전략 B 를 고른 경우에만** 쓴다.
  16. 하중 선정 결과 표 옆 출처 아이콘 ⓘ 1개 → 팝오버(방식 요약 2~3줄 + 전략별 한 줄 설명 + 출처 목록), 보고서 HTML 에 같은 "방법·출처" 절. 출처 문구·링크는 자료 파일 1곳(§9.1).

## 0. 현황 조사 (main f44c2c5, v0.5.9)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| DTPG 덱 생성 | `esl/library/optdeck.py write(target_mesh, load_cases, support_321, design, out_dir)` | `.fem`(GRID/CQUAD4/CTRIA3/PSHELL/MAT1 + SUBCASE별 FORCE·SPC1 + DTPG + DRESP1 COMP + DESOBJ(MINMAX)/DOBJREF(POS = `lc["ref"]` 기준 컴플라이언스) 또는 WCOMP) + `esl_loads.inc` + `run_optistruct.bat` + README. DTPG 방향 = 요소 법선, `bounds [0,1]`, SKIP=BC. 비설계 = `nondesign_pids`·`design_pids`·`nondesign_node_ids`+반경 → 별도 PSHELL. **DOPTPRM·OUTPUT 카드 없음**. 실행 검증 이력 없음 |
| 기준 컴플라이언스 | `esl/library/cli.py reference_compliance(mesh, supports, Fs, solver)` | 자체 쉘 솔버(`esl.mech.shell.ShellModel`)로 C_k = Σ F·u(3-2-1). 하중마다 `sm.solve` |
| 덱 실행 흐름 | `core_adapter.py _lib_optdeck` | 덱만 생성, **실행·회수 없음** |
| 대상·매핑 | `analysis.py run`, `mapping.py to_target` | 대상 = 라이브러리 항목, `mesh_sha256`(좌표 포함) 같으면 원본 F_eq, 아니면 셀 (24×14) 합력·합모멘트 최소노름 분배 + 평형 보정 |
| 정규화 좌표계 | `normalize.py frame()` | 면적 가중 PCA 평면 + `axis_ref`, `a_range`·`b_range`(mm)·`L_xi`·`L_eta`·`z_range` |
| 라이브러리 원본 | `entry.py` raw | node_id, x0, conn, elem_type, elem_pid, thickness, E, nu, **f(F_eq), u_rel**, 3-2-1 |
| 크기 정보 | `library_entries.model.inch`, `summary.frame.{L_xi,L_eta}` | DB에 있음 |
| 모델 동일성 | `results_csv._check_conn`·`canon_conn`, 결정 0.5.5 | 노드 ID 집합 + 요소 연결, 좌표 Kabsch 잔차 ≤ `coord_check.max_rel`·bbox |
| Case 입력 | `cases.rad_path`, `cases.part_title` | 업로드 폴더 또는 input_roots(읽기 전용), 낙하 씬 rad 수 GB 가능 |
| 업로드 | `services/uploads.py` | 청크·sha256. complete 검사는 Case 전용, `allowed_ext` 에 `.fem` 없음 |
| rad/fem | `parse_rad`, `write_rad` / – | fem 파서 **없음** |
| 외부 실행 | `h3d.py`, `executor._run_h3d` | LOCAL step, argv 템플릿, shell=False, 메타문자 거부, 트리 종료, DB 세마포어 `max_concurrent_hw` |
| 명령 규칙 원형 | `esl.md` §4.4 | `{optistruct}` → `altair.optistruct_path`, `os_solve` 정의만 |
| 작업·DB | `job_types.py`, migration 0001~0008 | 7종, stage 1~9. 0009 = MCP **예약** |
| 화면 | `pages/library/*` | 목록 행 선택 없음 |

## 1. 범위 / 비범위

| 범위 (v0.7.0) | 비범위 |
|---|---|
| S1 기존 rad 형상, S2 템플릿 최적화 | HPC/PBS 제출, 원격 실행 |
| 템플릿 등록·목록·상세·삭제(보관) — `.rad`·`.fem` 쉘 | CAD/STEP 템플릿(§16) |
| 비드 금지 영역: 자동(구멍 반경·가장자리 띠) + 사용자 사각형, 세트 저장·불러오기, 2D 평면도 | 임의 다각형·원형 금지 영역, 3D 위 직접 그리기 |
| 하중 선정 전략 A(전부 + |MAC| 병합 + 상한 군집, 기본·추천)/B(모드별 최악 ≤3)/C(군집 대표 k), min-max 목표(절대 기준 기본 / 상대 기준 옵션). 변형 모드 분류·수정·저장 | 시간 구간 전체 ESL(ESLSO 전 시점), 가중합·사용자 가중 목적 |
| OPT_RUN(SLOT): 준비 → 하중·선정 → 덱 → OptiStruct → 후처리 → 등록 | 비드 반영 모델의 검증 낙하 자동 실행, 형상·두께 최적화 |
| 결과: 비드 높이, 2D 맵 PNG, 수렴 이력, 비드 반영 메시(rad/fem), 보고서, 원본 h3d/out | 라이브러리 항목 등록(확정 7), 3D 비드 보기 |
| migration 0010, 시험, 가이드·CHANGELOG | 메타 편집(모델·인치·태그) — §16 |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| OR-D-1 | 작업 **`OPT_RUN`**(SLOT, stage **10**), 테이블 **`opt_runs`**(`scenario` S1/S2) | 덱만 만드는 분석과 솔버 실행은 수명·실패 양상이 달라 분리 |
| OR-D-2 | 하중·덱은 코어 재사용: 하중 = `analysis` 의 케이스별 하중 함수(S1 직접 / S2 `mapping.to_target`), 선정 = 신규 `esl.opt.select`, 덱 = `optdeck.write`. 대상 어댑터 S1 `CaseTarget`, S2 `TemplateTarget` | 매핑 알고리즘 변경 0(확정 3) |
| OR-D-3 | **S1 하중 = 노드 직접**: 원본 F_eq 를 node_id 로 대상 노드 순서에 재배열(셀 매핑·평형 보정 없음) | 확정 3 |
| OR-D-4 | **S1 모델 동일성** = 0.5.5 규칙(노드 ID + `canon_conn` + Kabsch 잔차), 빠른 판정 `topo_sha256`(정렬 node_id + 요소 ID별 canon 연결, 좌표 제외) | `mesh_sha256` 은 좌표 포함이라 버전 간 미세차에 과민 |
| OR-D-5 | **S1 다른 모델 ESL = 선택 불가**(자동 S2 전환 없음). 화면 "다른 모델" 표시 + [다른 모델 빼기] + 안내, 서버 422 `MODEL_MISMATCH` | 한 실행 = 한 하중 방식이 단순 |
| OR-D-6 | **S1 대상** = 기준 ESL Case 입력 rad 를 `parse_rad(case.part_title)` 로 **제자리 읽기**(복사 안 함), 대상 파트만 `_opt/<id>/target/target.npz` + 원본 sha256·크기·mtime 기록. 지지 = 기준 ESL 3-2-1 | 확정 10, 대형 rad |
| OR-D-7 | **S2 크기** = 같은 인치(양쪽 있을 때) AND `L_xi`·`L_eta` ESL 간 ≤ 0.02, 템플릿↔ESL 중앙값 ≤ 0.05. 세 곳 강제(422 `SIZE_MISMATCH`) | 확정 5 |
| OR-D-8 | **템플릿** = 전역 자원(모든 사용자 조회·사용), 등록 = power 이상, 삭제 = 등록자·전역 관리자, 참조 중이면 `ARCHIVED`, 미참조면 행 삭제 + 폴더 `_templates/_backup/` 이동 | 확정 4 |
| OR-D-9 | 템플릿 파일은 `_templates/<id>/input/` 로 복사(sha256). `.rad`(`parse_rad`) 또는 `.fem`(신규 `esl/opt/femread.py`: GRID·CQUAD4·CTRIA3·PSHELL·MAT1, 자유/소형/대형 필드, INCLUDE 미지원) | 확정 4·10 |
| OR-D-10 | 비드 방향(확정 6): DTPG 기본(요소 법선), `bounds [0,1]`. S2 는 템플릿 법선을 n 쪽으로 연결 순서 정렬(수 기록). **S1 은 원 연결 유지, 반대 법선 요소 수·위치 경고만**(가정 확정) | S1 결과 메시는 제품 모델에 그대로 들어감 |
| OR-D-11 | **비드 금지 영역** = 자동(구멍 반경·가장자리 띠) ∪ 사용자 사각형 → 요소 중심이 들어가면 비설계(별도 PSHELL, DTPG 제외). 사각형 좌표계 = 대상 frame 의 (a,b) mm 평면, 기준 모서리 4종 | 확정 11 |
| OR-D-12 | 금지 영역 세트 저장 = 테이블 `opt_keepouts`, 키 S2 `template_id` / S1 `topo_sha256`(전역, 모델당 1세트, 낙관적 잠금 `version`). 실행은 생성 시점 세트를 `opt_runs.design.keepout` 에 **스냅샷** | 확정 11, 이후 세트 수정이 과거 실행에 영향 없음 |
| OR-D-13 | **변형 모드 분류** = ESL 자신의 메시에서 w = u_rel·n 을 정규화 좌표 [−1,1]² 의 2차 르장드르 기저 최소자승 적합 → 굽힘·뒤틀림 에너지 비율, 잔차 국부 집중도 ≥ 기준이면 덴팅. **용도 = 표시·보고서·라이브러리 분류/검색 + 하중 선정 전략 B**(3차 확정). 결과는 `library_entries.deform_mode`(auto + user), 사용자 수정 우선 | 확정 12 |
| OR-D-14 | **하중 선정**(3차 확정) = 전략 `load_strategy` A|B|C(기본 A), 공통: ESL 1개 = 하중 케이스 1개(t* 단일 시점), 대상 초기 형상(비드 없음) 자체 쉘 솔버로 후보마다 u_k·C_k = F_k·u_k(3-2-1, 분해 1회·다중 RHS), 표시용 umax = max‖u_k‖. A = |MAC| ≥ `mac_merge` 탐욕 병합 → `max_cases` 초과 시 average linkage 군집 대표, B = 모드별 C 최대(≤3), C = average linkage 군집 k개 대표(병합 없음). 상세 §7.4 | 사용자 지시(A = KIT 비드 최적화 연구 방식, 추천). 부호 무관 MAC 로 반대 방향 하중 중복 제거, 결정적 |
| OR-D-15 | **목적 = minmax, 목표 기준 `objective_norm`**(실행 화면 선택 2개, 3차 확정): **`abs`(기본·추천)** = minimize max_i C_i, 스케일만 공통 기준값 C_ref = max_i C_i⁰ 로 나눔 → 덱 `DESOBJ(MINMAX)` + 모든 subcase `DOBJREF POS = C_ref`(같은 상수 — 하중 크기 비중 유지). **`rel`** = minimize max_i C_i/C_i⁰ → subcase별 `DOBJREF POS = C_i⁰`. C⁰ = 자체 쉘 솔버 초기 형상 컴플라이언스. 사용자 가중 방식 없음. OptiStruct 반복 0 의 C 와 자체 솔버 C⁰ 차이는 결과에 기록 | ESL F_eq = K_L·u_rel 은 물리 절대 하중이므로 큰 하중이 더 중요해야 함(abs). rel 은 하중 크기와 무관하게 모든 케이스를 같은 비율로 개선하고 싶을 때. 기존 POS=ref 경로 재사용 |
| OR-D-16 | 비드 치수 기본 = 경사 45°·폭 60 mm·높이 10 mm(`opt_run.bead_defaults`), 화면 숫자 3칸. `library.yaml optdeck.bead`(LIB_ANALYZE 기본)는 불변 | 확정 13 |
| OR-D-17 | OptiStruct = 워커 LOCAL step, `commands.os_check`·`os_solve`(argv[0] `{optistruct}`), shell=False, 메타문자 거부, 세마포어 `altair.max_concurrent_os`. `-check` 후 본 실행 | `esl.md` §4.4 |
| OR-D-18 | 라이선스 부족 = 3회 × 300 초 자동 재시도 후 `OS_LICENSE_UNAVAILABLE` | 확정 8 |
| OR-D-19 | 재시도 시 `solve/solve.json` 덱 sha256 동일 + 성공 표식 → OS_SOLVE **SKIPPED(재사용)** | 수 시간 해석 반복 방지 |
| OR-D-20 | 후처리 = HyperView 배치 TCL(`resources/tcl/esl_bead_post.tcl`) `<deck>_des.h3d` Shape Change → CSV → Python 비드 높이·PNG(zlib)·비드 반영 메시·보고서 | h3d 비공개 포맷 |
| OR-D-21 | 결과는 라이브러리 미등록, "최적화 실행" 탭·실행 이력에 보존 | 확정 7 |
| OR-D-22 | migration **0010**(0009 MCP 예약). 0009 부재 시 0010 `down_revision="0008"`, MCP 는 revision `"0009"`·`down_revision="0010"` | 두 migration 멱등 |

## 3. 사용 시나리오

### 3.1 S1 기존 rad 형상 최적화
1. 라이브러리 목록에서 ESL 체크(첫 행 = 기준). 목록 체크는 같은 크기 규칙만, 같은 모델 행은 ⓜ 표시. "모드" 열(덴팅/뒤틀림/굽힘, 자동 = 회색 글씨, 사용자 수정 = 굵게)을 행에서 바로 수정 가능(저장).
2. [선택한 ESL로 비드 최적화 (n)] → `/esl/p/:pid/opt/new?entries=…`, 탭 [기존 형상 | 템플릿]. 모두 같은 모델이면 기본 = 기존 형상.
3. ① 대상 카드: 기준 Case·대상 파트·노드·요소·rad 파일명, PID 표(설계 체크), 3-2-1(표시만), 법선 경고(있을 때).
4. ② 비드 금지 영역 카드: 2D 평면도(ξ,η mm 축, 외곽선·구멍·자동 금지 영역 회색 빗금·사용자 사각형 주황) + 사각형 표(이름·기준 모서리·X·Y·가로·세로 mm, [＋사각형] [삭제]) + 자동 값 표시(구멍 반경·가장자리 띠, 설정값). 이 모델(`topo_sha256`)에 저장된 세트가 있으면 자동으로 불러옴. 평면도에서 사각형 드래그 → X·Y 숫자 동기화, 숫자 입력 → 평면도 동기화. [이 모델에 저장].
5. ③ ESL 카드: 같은 모델 ✓/✗, 모드(표시·수정 — 전략 B 에서 사용), [다른 모델 빼기]. ④ 하중 선정 전략 라디오(§10.3).
6. ⑤ 비드 치수: 경사 [45]° 폭 [60] mm 높이 [10] mm, 제목(선택) → 주 버튼 [최적화 실행].

### 3.2 S2 템플릿 최적화
1. (최초 1회) 템플릿 탭 → [템플릿 등록] → `.rad`(+include)/`.fem` 끌어다 놓기 → 청크 업로드 → 자동 검사 → 제목·인치(선택)·설명 → [등록].
2. ESL 선택(같은 크기) → 새 최적화 화면 템플릿 탭: ① 템플릿 선택(크기 맞는 것만 활성) → PID 표·자동 3-2-1·품질 경고. ② 비드 금지 영역(S1 과 같은 카드, 세트는 이 템플릿에 저장·불러오기). ③ ESL 카드(크기 그룹·모드). ④ 비드 치수 → [최적화 실행].
3. 대안 진입: 종합분석 상세 "이 분석의 씬으로 비드 최적화"(크기 혼합이면 최다 그룹만 + 경고).

### 3.3 공통 진행·결과
- 상세 `/esl/p/:pid/opt/:id`: step 진행(6), **하중 선정 표**(전략·목표 기준·상태·씬·C⁰·최대 상대 변위·모드), OptiStruct 반복 n/DESMAX·목적값(abs: max C_k/C_ref, rel: max C_k/C_k⁰), 라이선스 대기, 로그, 취소. 완료 후 비드 맵, 수렴 그래프, 하중별 C^0 → C_final(비율), 다운로드, [보고서 보기].
- 안내: 비드 반영 메시로 낙하 해석 → 새 Case → 라이브러리 등록 → 버전 비교.

## 4. 데이터 흐름

```
S1: library_entries(같은 모델) + 기준 Case rad(제자리 읽기) ─┐
S2: library_entries(같은 크기) + opt_templates               ├─ POST /opt/runs (+opt_keepouts 스냅샷)
                                                             ┘   → opt_runs + OPT_RUN(QUEUED)
                                           ▼ 워커(SLOT), <esl_root>/_opt/<id>/
 1 OPT_PREP   (INTERNAL) 대상 메시(S1 parse_rad / S2 template.npz) → 동일성·크기 재검사 → 법선 → 3-2-1
                         → 금지 영역(자동 ∪ 사각형) 마스크 → target/target.npz, target.json, keepout.png
 2 OPT_LOAD   (INTERNAL) 후보 ESL별 하중(S1 직접 / S2 셀 매핑) → 자체 쉘 솔버 C_k·max‖u_k‖ (분해 1회)
                         → 전략 A(|MAC| 병합 → 상한 군집) | B(모드별 최악 ≤3) | C(군집 k 대표) → load/selection.json, load/loads.npz
 3 OPT_DECK   (INTERNAL) optdeck.write(minmax, POS=C^0, 비설계 = PID ∪ 금지 영역, +server 카드) → deck/
 4 OS_SOLVE   (LOCAL)    세마포어 → solve/ → -check → 본 실행(라이선스 재시도) → solve.json
 5 OPT_POST   (LOCAL+INTERNAL) hw TCL → post/* → report.html
 6 OPT_REGISTER (DB)     opt_runs.result·report_rel, artifacts, 알림
```
- 각 step 은 자기 하위 폴더를 `fresh_dir`(이전 내용 `_backup/<UTC>/`, 삭제 없음). 코어는 DB를 모름.
- 템플릿 폴더 `<esl_root>/_templates/<tid>/{input/, template.npz, template.json, preview.json}`.

## 5. API (접두 `/esl/api`, 기존 오류 형식, 비GET `X-ESL-Request: 1`)

### 5.1 엔드포인트

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `GET /opt/settings` | – | `OptSettingsOut` | – |
| `POST /opt/templates/check` | `{project_id, upload_id, part_title?}` | `MeshCheckOut` | 404 `UPLOAD_NOT_FOUND`, 409 `UPLOAD_NOT_READY`, 422 `MESH_INVALID`·`MESH_FORMAT_UNSUPPORTED`·`PART_NOT_FOUND`·`PART_AMBIGUOUS` |
| `POST /opt/templates` | `TemplateIn` | `201 TemplateOut` | 위 + 409 `PLATE_CHANGED`, 422 `INVALID_PARAMS` |
| `GET /opt/templates?status=&q=` · `GET /opt/templates/{tid}` | – | `[TemplateOut]` / `TemplateOut` | 404 `TEMPLATE_NOT_FOUND` |
| `DELETE /opt/templates/{tid}` | – | `{deleted, archived}` | 403 `NOT_TEMPLATE_OWNER`, 404 |
| `POST /opt/s1-check` | `{project_id, entry_ids}` | `S1CheckOut` | 422 `ENTRY_NOT_FOUND`, 409 `PREREQUISITE_MISSING` |
| `GET /opt/plan-view?template_id=` \| `?entry_id=` | – | `PlanViewOut`(평면도 자료) | 404, 413 `PLAN_VIEW_TOO_LARGE` |
| `GET /opt/keepouts?template_id=` \| `?topo=` | – | `KeepoutSetOut` \| 404 `KEEPOUT_NOT_FOUND`(세트 없음 — 화면은 빈 세트) | – |
| `PUT /opt/keepouts` | `KeepoutSetIn` | `KeepoutSetOut` | 409 `VERSION_CONFLICT`, 422 `KEEPOUT_INVALID` |
| `PATCH /library/entries/{id}` (기존 확장) | `{version, deform_mode: "dent"\|"twist"\|"bend"\|null}` (null = 자동으로 되돌림) | `EntryOut` | 기존 + 422 `INVALID_PARAMS` |
| `POST /opt/runs` | `OptRunIn` | `201 OptRunOut` | 422 `ENTRY_NOT_FOUND`·`MODEL_MISMATCH`·`SIZE_MISMATCH`·`TEMPLATE_NOT_FOUND`·`TEMPLATE_ARCHIVED`·`KEEPOUT_INVALID`·`NO_MODE_CANDIDATES`(전략 B)·`INVALID_PARAMS`, 409 `PREREQUISITE_MISSING`, 503 `SOLVER_NOT_CONFIGURED` |
| `GET /opt/runs?project_id=&scenario=` · `GET /opt/runs/{id}` | – | `[OptRunOut]` / `OptRunOut` | 404 `OPT_RUN_NOT_FOUND` |
| `GET /opt/runs/{id}/files` · `/download?rel=` · `/bundle?parts=` · `/report` · `/bead-map.png` | – | 목록 / 첨부 / zip / HTML / PNG | 404·413 |
| 기존 `POST /jobs/{id}/cancel`·`/retry`, 로그 | – | OPT_RUN 에도 적용 | – |
| 기존 `GET /library/entries` | – | `size:{inch, L_xi, L_eta}`, `topo_sha256`, `deform_mode:{auto, user, effective, metrics}` 추가 | – |

### 5.2 스키마

```text
OptSettingsOut { enabled, solver_ready, solver_reason|null, size:{tol_rel, plate_tol_rel, require_inch},
                 bead_defaults:{angle:45, min_width:60, height:10}, keepout_auto:{hole_radius_mm, edge_band_mm}, loads:{default_objective_norm, default_strategy, mac_merge, max_cases, default_k}, method_sources,
                 max_rects, max_entries, template_max_elems, template_ext:[".rad",".inc",".fem"] }

MeshCheckOut   { ok, sha256, format:"rad"|"fem", file_name, parts[], part_title|null,
                 mesh:{n_nodes, n_elems, n_quad, n_tria, unsupported{}}, pids:[{pid,title,n_elems,thickness,E,nu}],
                 frame:{L_xi, L_eta, z_range, warnings[]}, quality:{errors[], warnings[], metrics{}},
                 supports_auto:[{node_id, dof}] }
TemplateIn     { project_id, upload_id, sha256, part_title?, title(1..200), inch?: int, description?(≤2000) }
TemplateOut    { id, title, inch|null, description, format, file_name, part_title, sha256, n_nodes, n_elems,
                 L_xi, L_eta, z_range, pids, quality_warnings[], status, n_runs, created_by_name, created_at, can_delete }
S1CheckOut     { base:{entry_id, case_id, case_title, part_title, rad_file_name, n_nodes, n_elems, topo_sha256,
                 pids[], supports[]}, entries:[{entry_id, same_model, reason|null}] }

PlanViewOut    { frame:{a_range, b_range} (mm), outline:[[a,b],…], holes:[[[a,b],…],…],
                 elems:{n_total, decimated, points:[[a,b,pid]]} (≤ ui.max_preview_points, 표시용),
                 auto_keepout:{hole_radius_mm, edge_band_mm, polygons:[[[a,b],…]]} (자동 영역 근사 외곽) }
                 # S1 은 기준 ESL 항목 raw(같은 모델), S2 는 template.npz 로 만든 파생 캐시(preview.json)

Rect           { name(≤40), corner:"a0b0"|"a1b0"|"a0b1"|"a1b1", x_mm ≥0, y_mm ≥0, w_mm >0, h_mm >0 }
                 # corner: (a_min,b_min) 좌하 | (a_max,b_min) 우하 | (a_min,b_max) 좌상 | (a_max,b_max) 우상 (ξ 오른쪽, η 위)
                 # 사각형 = 모서리에서 안쪽으로 x_mm·y_mm 떨어진 점을 가까운 꼭지점으로, 안쪽으로 w×h
KeepoutSetIn   { template_id? | topo_sha256?, version? (갱신 시 필수), rects:[Rect] (0..max_rects),
                 auto:{hole: bool (기본 true), edge: bool (기본 true)} }
KeepoutSetOut  { id, key:{template_id|topo_sha256}, version, rects, auto, frame:{a_range,b_range},
                 updated_by_name, updated_at }

OptRunIn       { project_id, scenario:"S1"|"S2", title?, entry_ids (1..max_entries), analysis_id?, template_id?(S2),
                 design:{nondesign_pids?:[int], bead?:{angle, min_width, height},
                         keepout:{rects:[Rect], auto:{hole, edge}}},   # 화면 현재값(저장 여부 무관) — 실행에 스냅샷
                 options:{supports?:[{node_id,dof}] (S2만), objective_norm?: "abs"|"rel" (기본 abs), load_strategy?: "A"|"B"|"C" (기본 A), k?: int (C 만, 1..max_cases, 기본 5)} }
OptRunOut      { id, project_id, scenario, title, entry_ids, analysis_id, base|template, size, design, load_strategy, k|null, objective_norm, job|null, state,
                 created_by_name, created_at, result: OptResult|null, report_ready }
OptResult      { load_selection: LoadSelection,
                 objective_norm:"abs"|"rel", C_ref (abs), converged, iterations, desmax, objective:{initial, final, history[]}  # abs: max_k C_k/C_ref, rel: max_k C_k/C_k^0
                 subcases:[{label, entry_id, C0_self, C0_os, C_final, ratio}],
                 keepout:{n_elems_auto_hole, n_elems_auto_edge, n_elems_rects, n_design_elems},
                 bead:{height_max, area_frac}, normals_flipped|normals_opposite,
                 solve:{seconds, license_waits, reused}, warnings[] }
LoadSelection  { strategy:"A"|"B"|"C", objective_norm, C_ref, k|null, mac_merge (A), max_cases, n_selected_esl, n_cases,
                 rows:[{entry_id, scene, mode (effective), C0, pos (덱 DOBJREF POS 값: abs = C_ref, rel = C0), umax,
                        status:"included"|"merged"|"cluster_rep"|"clustered"|"mode_rep"|"not_selected",
                        merged_into|null, mac_to_target|null, sign: 1|-1|null (병합 대상과 반대 방향이면 -1), cluster|null, label|null}],
                 clusters:[{id, rep_entry_id, members:[entry_id], min_mac}] (A 상한 초과·C 만, 아니면 []),
                 excluded_modes:[mode] (B 만), sources_ref:"opt_method_sources/<version>" }
                 # OptRunOut.result.load_selection 으로 응답, OPT_LOAD 가 끝난 뒤부터 채움
```

### 5.3 오류 코드 (신규)

| 코드 | HTTP/작업 | 의미 |
|---|---|---|
| `MODEL_MISMATCH` | 422 / OPT_PREP | S1 다른 모델(`reason`: NODE_IDS·CONNECTIVITY·COORDS) |
| `SIZE_MISMATCH` | 422 / OPT_PREP | S2 크기 불일치 |
| `MESH_INVALID` / `MESH_FORMAT_UNSUPPORTED` | 422 | 템플릿 검사 오류 / 형식 |
| `PLATE_CHANGED` / `UPLOAD_NOT_READY` | 409 | check 이후 업로드 변경 / 업로드 미완료 |
| `TEMPLATE_NOT_FOUND` / `TEMPLATE_ARCHIVED` / `NOT_TEMPLATE_OWNER` | 404·422·403 | 템플릿 |
| `KEEPOUT_INVALID` | 422 | 사각형 값 범위(음수·0·대상 경계 밖 완전 이탈·개수 초과) |
| `KEEPOUT_ALL` | 422 / OPT_PREP | 금지 영역·비설계 PID 제외 후 설계 요소 0 |
| `VERSION_CONFLICT` | 409 | 금지 영역 세트 동시 수정 |
| `NO_MODE_CANDIDATES` | 422 / OPT_LOAD | 전략 B: 세 모드 모두 후보 0(분류 실패 포함) |
| `NO_LOAD_CASES` | 작업 / OPT_LOAD | 모든 후보의 C ≤ 0(하중 0) |
| `SOLVER_NOT_CONFIGURED` | 503 | OptiStruct 미설정 |
| `INPUT_CHANGED` | 작업(경고) | S1 재시도 시 Case rad sha256 변경(동일성 재검사 후 진행) |
| `OS_DECK_INVALID` / `OS_LICENSE_UNAVAILABLE` / `OS_SOLVE_FAILED` / `OS_TIMEOUT` / `BEAD_POST_FAILED` | 작업 | §8·§9 |
| 기존 재사용 | | `ENTRY_NOT_FOUND`, `SUPPORT_DEGENERATE`, `MAPPING_DEGENERATE`, `GRID_MISMATCH`, `SOLVER_OUT_OF_MEMORY`, `PREREQUISITE_MISSING`, `CONFIG_INVALID` |

- 미수렴(DESMAX 도달)은 실패 아님: SUCCEEDED + `converged=false` + 경고.

## 6. 작업 종류 · 워커 단계 · 진행률/로그

### 6.1 `job_types.py`
```python
"OPT_RUN": JobTypeDef("OPT_RUN", 10, "SLOT", (
    StepDef("OPT_PREP", "opt_prep"), StepDef("OPT_LOAD", "opt_load"), StepDef("OPT_DECK", "opt_deck"),
    StepDef("OS_SOLVE", None, kind="LOCAL"), StepDef("OPT_POST", "opt_post", kind="LOCAL"),
    StepDef("OPT_REGISTER", None))),
```
- 작업 대상 = `jobs.opt_run_id`. 활성 작업 중 retry 409 `JOB_ACTIVE`(기존).

### 6.2 단계별 요구
- OR-1 **OPT_PREP**: S1 = 기준 Case rad 제자리 `parse_rad` → 동일성(기준 ESL raw·선택 ESL 전부) → 지지 = 기준 ESL 3-2-1. S2 = `template.npz` → 크기 재검사 → 법선 정렬 → 3-2-1(지정 또는 자동). 공통 → frame(S1 은 기준 ESL `meta.frame`, S2 는 템플릿 frame — 평면도·사각형과 같은 좌표계) → 금지 영역 마스크(§7.5) → 비설계 PID → `target.npz`(…, design, keepout_reason(요소별 0/1구멍/2가장자리/3사각형)) + `target.json` + `keepout.png`(보고서용).
- OR-2 **OPT_LOAD**: 후보 = 선택 ESL 전부(각 ESL = t* 단일 시점 하중 1개, 시간 구간 다중 하중 아님). 대상 쉘 모델 1회 조립·분해(`ShellModel`, 3-2-1) → 후보마다 하중(S1 직접 / S2 셀 매핑 + 평형 보정) → `u_k = solve`, `C_k = Σ F·u[:, :3]`, `umax_k`. 전략 A·C 는 u_k(병진, float32)를 `load/u_cand.npy`(memmap)에 쌓아 MAC 계산(22만 노드 × 200 ≈ 0.5 GB, 메모리에는 하중 1개만). 선정 = 실행 스냅샷의 `load_strategy`·`k` 로 §7.4. 산출 `load/selection.json`(LoadSelection), `load/loads.npz`(선정 하중만, node_id 순서).
- OR-3 **OPT_DECK**: `optdeck.write(mesh, load_cases(ref=C^0), supports, design{objective:"minmax", bead, nondesign = PID ∪ 금지 영역 요소, server})`. subcase 라벨 `L01`…(선정 순서 = C 내림차순), 덱 주석에 entry_id·전략. `run_optistruct.bat`·README 도 생성.
- OR-4 **OS_SOLVE**: §8. OR-5 **OPT_POST**: §9.
- OR-6 **OPT_REGISTER**: `opt_runs.result`, `report_rel`, artifacts, 알림.

### 6.3 진행률·로그

| step | 진행률 | 로그 |
|---|---|---|
| OPT_PREP | 파싱 60·검사 30·저장 10 | 노드·요소·동일성/크기·법선·금지 영역 요소 수(구멍·가장자리·사각형별) |
| OPT_LOAD | 분해 20 + 후보 k/K × 80 | 후보별 모드·C·umax, 선정 결과, 제외 모드 |
| OPT_DECK | 0→100 | subcase(모드)·POS·설계/비설계 요소 |
| OS_SOLVE | check 5 % + 반복 n/DESMAX × 95 % | argv(관리자만), `.out` 중계, 세마포어·라이선스 대기 |
| OPT_POST | hw 50·후처리 50 | Shape Change 노드 수·비드 최대 높이 |

- 작업 progress 가중 1·4·1·82·10·2 %.

## 7. 입력 검증 · 하중 선정 · 금지 영역

### 7.1 S2 크기 일치 (OR-7)
- 기준 = 선택 첫 ESL. 같은 인치(양쪽 있을 때, 한쪽 null → 치수만 + 경고 `INCH_UNKNOWN`) + `L_xi`·`L_eta` ≤ `tol_rel`.
- 템플릿: ESL 치수 중앙값 대비 ξ·η ≤ `plate_tol_rel`. 템플릿 인치는 **선택 입력**(가정 확정) — 있으면 같아야 함, 없으면 치수만.
- 격자 다르면 `GRID_MISMATCH`. 검사 시점: 화면 / `POST /opt/runs`(DB) / OPT_PREP(항목 파일).

### 7.2 메시 검사 (공통 `esl.opt.mesh_check`) (OR-8)

| 검사 | 오류 | 경고 |
|---|---|---|
| 형식 | `.rad` 0/2개 이상·include 누락·파싱 실패, `.fem` INCLUDE·파싱 실패 | 파트 2개 이상, fem 비지원 카드 무시 수 |
| 요소 | QUAD4/TRIA3 외, 요소 수 > `template.max_elems`(500 000, S2) | TRIA3 > 20 % |
| 재료·두께 | 두께 ≤ 0, E·ν 해석 불가 | – |
| 연결 | 요소 0 | 연결 성분 > 1, 일치 노드 |
| 평탄도 | – | S2 `z_range/max(L)` > 0.02 |
| 법선 | – | S2 자동 정렬 수 / S1 반대 법선 요소 수·위치(원 연결 유지) |
| 요소 크기 | – | 비드 폭 < 2 × 요소 크기 중앙값 |
| 매핑 해상도 | – | S2 셀당 노드 중앙값 < 64 |
| 형상 | – | 종횡비 > 10, 뒤틀림 > 15° |
| 3-2-1 | rank < 6 | 지지 노드가 금지 영역 밖(지지 주변은 비드가 생겨도 됨 — 정보) |

- 템플릿 check 결과는 `uploads.result.purpose="template"` 로 저장, 업로드 COMPLETED. 업로드 폴더에 쓰지 않음.

### 7.3 S1 모델 동일성 (OR-9)
- `topo_sha256` 1차(목록·s1-check·금지 영역 세트 키), OPT_PREP 에서 전체 규칙 확정.
- `library_entries.topo_sha256`: 새 등록 시 계산, 기존 항목은 첫 조회 때 raw 로 지연 백필(실패 → null → S1 불가 + "모델 정보 없음").
- 기준 Case 입력 없음·읽기 실패 → `PREREQUISITE_MISSING`(안내: Case 입력 다시 올리기 또는 템플릿 최적화).

### 7.4 변형 모드 분류 · 하중 선정 전략 (OR-10)
- 분류 — 표시·보고서·라이브러리 필터(모드 열·검색 `?mode=`) + 전략 B 입력(ESL 자신의 raw, `esl.opt.modes.classify`):
  - w_i = u_rel,i · n (frame n), 좌표 s = 2(a−a_min)/L_xi − 1, t = 2(b−b_min)/L_eta − 1 ∈ [−1,1].
  - 기저(르장드르 2차): 1, s, t, P2(s), P2(t), s·t. 노드 면적 가중 최소자승(`node_areas`). 강체·평면 성분(1, s, t)은 에너지 계산에서 제외.
  - 에너지 E_bend = ‖c_P2(s)·P2(s) + c_P2(t)·P2(t)‖²_A, E_twist = ‖c_st·s t‖²_A, 잔차 r = w − 적합, E_res = ‖r‖²_A, E_tot = E_bend + E_twist + E_res.
  - 국부 집중도 κ = (잔차 에너지 상위 `dent_area_frac`(0.05) 면적이 차지하는 비율). **덴팅** = E_res/E_tot ≥ `dent_resid_min`(0.5) AND κ ≥ `dent_conc_min`(0.6). 아니면 E_bend ≥ E_twist → **굽힘**, 아니면 **뒤틀림**. E_tot < `min_energy_rel`·(max|w|²·A) 이면 분류 불가(null, 경고).
  - 저장 `library_entries.deform_mode = {auto, metrics:{bend, twist, resid, kappa}, user, user_by, user_at, rule_version}`, effective = user ?? auto. 새 등록 시 워커가 계산, 기존 항목은 첫 조회 때 API 가 raw 로 지연 계산(u_rel N×3, 6열 최소자승 — 22만 노드 < 1 s).
  - 사용자 수정: 라이브러리 목록·새 최적화 ESL 카드의 모드 드롭다운 → `PATCH /library/entries/{id}`(power, 메타 수정과 같은 권한·`version` 잠금). 기준값 변경(`rule_version` 증가) 시 auto 만 재계산, user 유지.
- 하중 선정(`esl.opt.select`, 모든 전략 결정적):
  0. 공통: 후보 정렬 = C_k 내림차순, 동률 entry_id 사전순. C_k ≤ 0 후보는 제외(경고), 모두 제외 → `NO_LOAD_CASES`. MAC: mac_ij = (u_i·u_j)² / ((u_i·u_i)(u_j·u_j)) ∈ [0,1] — 제곱이라 **부호 무관**(F→−F 는 C 가 같으므로 반대 방향 토션·굽힘은 같은 하중). u 는 대상 전 노드 병진 성분. 군집 = 거리 d = 1 − mac, `scipy.cluster.hierarchy.linkage(method="average")` + `fcluster(criterion="maxclust")`, 입력 순서 = 정렬 순서, 군집 번호는 대표 C 내림차순으로 다시 매김. 선정 1개여도 진행(단일 컴플라이언스 최소화).
  **A 전부 넣기(기본·추천)**: 정렬 순서로 보며 이미 남긴 케이스 중 mac ≥ `mac_merge`(0.95)가 있으면 `merged`(merged_into = mac 최대, 동률은 먼저 남긴 것, sign = sgn(u_i·u_target)), 없으면 남김. 남은 수 M ≤ `max_cases`(20) → 전부 `included`, M > max_cases → 남은 것만 군집 max_cases 개 → 군집별 C 최대 `cluster_rep`, 나머지 `clustered`.
  **B 모드별 최악**: effective 모드별 C 최대 1개 `mode_rep`(≤3), 나머지 `not_selected`, 후보 0 모드는 `excluded_modes`. 세 모드 모두 0 → `NO_MODE_CANDIDATES`. 병합·군집 없음(표에 mac 은 표시하지 않음).
  **C 군집 대표 k개**: 병합 없이 전 후보를 군집 min(k, 후보 수) 개 → 군집별 C 최대 `cluster_rep`, 나머지 `clustered`. k 범위 1..`max_cases`(벗어나면 422 `INVALID_PARAMS`).
- 화면·보고서는 전략 이름 + 후보 전체 행(상태·병합 대상·부호·mac·군집·C⁰·umax·모드)을 보여준다.
- 목적: OR-D-15. abs: `DOBJREF POS = C_ref = max_i C_i⁰`(선정 케이스 중 최대, 모든 subcase 같은 값) → 반복 0 목적 = 1 근처. rel: `DOBJREF POS = C_i⁰` → 반복 0 각 정규화 값 1 근처. |C_os^0/C_self^0 − 1| > `opt_run.loads.c0_tol`(0.05) 이면 경고(요소 정식화 차이) — 결과 표시는 OptiStruct 값 기준. 덱 헤더 주석에 `objective_norm`·C_ref 기록.

### 7.5 비드 금지 영역 (OR-11)
- 좌표계: 대상 frame 의 (a, b) mm(a = ξ 방향, b = η 방향), 경계 `a_range`·`b_range`. 요소 판정점 = 요소 중심 투영.
- 자동 구멍: 메시 자유 모서리 루프 중 외곽(최대 둘레/면적) 이외 루프 = 구멍. 구멍 루프 노드에서 3D 거리 ≤ `keepout.hole_radius_mm`(기본 15) 인 노드를 쓰는 요소 → 금지. 설정 `keepout.hole_min_perimeter_mm`(기본 5) 미만 루프는 무시(메시 결함).
- 자동 가장자리: 외곽 루프 노드에서 3D 거리 ≤ `keepout.edge_band_mm`(기본 10) 인 노드를 쓰는 요소 → 금지.
- 사각형: Rect → 모서리 `a0b0` 이면 [a_min + x, a_min + x + w] × [b_min + y, b_min + y + h], `a1b0` 이면 [a_max − x − w, a_max − x] × [b_min + y, …], `a0b1`·`a1b1` 대칭. 경계 밖으로 일부 나가면 잘라서 적용(경고), 완전히 밖이면 `KEEPOUT_INVALID`. 개수 ≤ `keepout.max_rects`(20).
- 결과 마스크 = 자동(on/off 각각) ∪ 사각형 → `optdeck` 비설계 요소 목록으로 전달(별도 PSHELL, DTPG 제외). 설계 요소 0 → `KEEPOUT_ALL`.
- 세트 저장: OR-D-12. 세트 frame(a_range·b_range)을 함께 저장하고, 불러올 때 현재 대상 frame 과 1 mm 이상 다르면 경고("모델 경계가 달라짐 — 위치 확인").
- 평면도 자료(`PlanViewOut`)와 워커 마스크는 같은 함수(`esl.opt.keepout`)로 만든다(화면 미리보기 = 실행 결과).

## 8. 솔버 실행 (OS_SOLVE)

### 8.1 실행 규칙 (OR-12)
- `solve/` fresh_dir 후 `deck/` 의 `esl_bead.fem`·`esl_loads.inc` 복사, 스크래치 `solve/tmp/`.
- argv: `commands.os_check` → 성공 시 `commands.os_solve`. argv[0] = `{optistruct}`, placeholder `optistruct, fem, fem_fwd, nt, work_dir, scratch, mem_mb`. 공통 `localproc.py`(h3d.py 와 같은 검사·트리 종료·작업 제한기).
- `cwd = solve/`, env = `worker.env_passthrough` + `opt_run.solve.env`(허용 키 `ALTAIR_LICENSE_PATH`·`ALTAIR_HOME`·`OMP_*`). argv 를 `job_steps.command`에 저장.
- 세마포어 `acquire_os`(advisory lock 신규 키, outputs `os_acquired`, `max_concurrent_os` 기본 1).
- 성공: 종료코드 0 + `error_patterns` 불일치 + `<deck>.out`·`<deck>_des.h3d` 존재. 수렴 = `converged_patterns`, 반복 = 마지막 `ITERATION n`.
- `solve/solve.json` `{deck_sha256, argv, exit_code, seconds, iterations, converged, license_waits, ok}`. `solve/tmp/` 는 다음 fresh_dir 때 `_backup`(삭제 없음).

### 8.2 덱 서버 카드 (OR-13, `optdeck.write(design={"server": {...}})`)
- `server` 있을 때만: `DOPTPRM, DESMAX, <desmax>`(30) [확신도 상], `OUTPUT, H3D, ALL` [중상 — V-OR-R1], 헤더 `opt_run <id> <scenario>`. S2 법선 정렬 연결 순서. `server` 없으면 기존 LIB_ANALYZE 덱 바이트 불변.

### 8.3 라이선스·실패·재시도 (OR-14)
- 라이선스: 종료코드≠0 + `license_patterns` 일치 → 3회 × 300 초(대기 중 세마포어 반납, 취소 즉시), 소진 `OS_LICENSE_UNAVAILABLE`.
- `-check` 실패 `OS_DECK_INVALID`, 그 밖 `OS_SOLVE_FAILED`, `timeout_h`(12) `OS_TIMEOUT`, 메모리 `SOLVER_OUT_OF_MEMORY`.
- 사용자 재시도 = `POST /jobs/{id}/retry`(power), OR-D-19 재사용. 재시도는 실행 스냅샷(금지 영역·모드 선정 결과 포함)을 그대로 씀 — 모드 수정·세트 수정을 반영하려면 새 실행.

## 9. 결과물 (OPT_POST) (OR-15)
- `commands.bead_post`(argv[0] `{hw}`) → `post/shape.csv`(node_id, dx, dy, dz)·`done.json`. hw 세마포어 공유. node_id 불일치 → `BEAD_POST_FAILED`.

| 파일 | 내용 |
|---|---|
| `post/bead.npz` | node_id, shape (N,3), h = shape·노드 법선, design, keepout_reason |
| `post/bead_nodes.csv` | node_id, x0, y0, z0, h, dx, dy, dz |
| `post/bead_map.png` | (a,b) mm 평면도, 요소 평균 h(0→높이, 순차 색), 비설계·금지 영역 회색 빗금(사각형 외곽선 주황), 3-2-1 기호, 범례. `png_px`(1600×900), 순수 Python + zlib |
| `target/keepout.png` | 실행 전 금지 영역 평면도(같은 렌더러) |
| `post/history.csv` | iteration, 목적값(abs: max C_k/C_ref, rel: max C_k/C_k⁰), 케이스별 C_k·C_k/C_k^0 |
| `post/bead_mesh.rad` / `.fem` | x0 + shape, 원 ID·PID·두께·재료 유지(S1 은 제품 모델 대상 파트 교체용) |
| `report.html` | 시나리오·입력 ESL·하중 선정 전략·목표 기준(C_ref)과 선정 표(상태·병합 대상·군집·C⁰·umax·모드)·대상·동일성/크기·품질·금지 영역 평면도·덱 설정·수렴(SVG)·비드 맵(SVG)·케이스별 C^0→C_final·**방법·출처 절**(§9.1)·한계 |
| `opt.json` | OptResult 원본 |

- 다운로드 목록: 위 + `load/selection.json` + `deck/*` + `solve/<deck>.out·.h3d·_des.h3d·.hist·.stat`. `solve/` 원본 불변. 라이브러리 반영 없음.

### 9.1 방법·출처 자료 (OR-16)
- 원본 1곳: `resources/opt_method_sources.json` `{version, summary_ko:[2~3줄], strategies:{A,B,C: 한 줄}, objective_norms:{abs, rel: 한 줄}, sources:[{title, authors?, url?, note?}]}`. 백엔드는 `GET /opt/settings` 의 `method_sources` 로 내려주고, 보고서(`report_opt.py`)가 같은 파일로 "방법·출처" 절(실행 전략 강조)을 만든다. 프런트는 API 값을 렌더링(가이드 `content.ts` 처럼 표시 구성만 프런트 — 문구·링크는 이 파일). 링크 `target="_blank" rel="noopener noreferrer"`, 보고서는 HTML 이스케이프.
- 초기 내용:
  - 요약: "각 ESL(t* 한 시점)을 하중 케이스 1개로 씁니다." / "초기 형상에서 계산한 컴플라이언스로 하중을 고르고, 가장 큰 컴플라이언스를 최소화(min-max)합니다." / "형상 유사도 |MAC| 는 부호와 무관해 반대 방향 하중을 같은 하중으로 봅니다."
  - 목표 기준: abs = "절대 기준(추천): 가장 큰 컴플라이언스를 줄임, 공통 상수로만 나눠 큰 하중의 비중 유지" / rel = "상대 기준: 각 하중을 자기 초기값 대비 같은 비율로 개선".
  - 전략: A = "KIT 식: 선택 ESL 전부, 형상이 거의 같은 하중(|MAC| ≥ 0.95)만 병합, 20개 초과 시 군집 대표" / B = "모드 대표: 덴팅·뒤틀림·굽힘별 최악 1개(최대 3개)" / C = "군집 대표: 형상 유사도로 k개 묶음, 묶음별 최악 1개".
  - 출처: ① Altair OptiStruct — Equivalent Static Load Method(ESLM) https://help.altair.com/2024/hwsolvers/os/topics/solvers/os/opt_composite_equiv_static_load_method_c.htm ② Park, G.J., Kang, B.S. 계열 "Structural optimization using equivalent static loads at all time intervals"(서지만) ③ KIT 비드/토포그래피 최적화 문헌 https://publikationen.bibliothek.kit.edu/1000137417/126578473
- 자료 version 을 LoadSelection.sources_ref 에 기록.

## 10. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 화면당 주 버튼 1개)

### 10.1 라이브러리 (변경)
```
[라이브러리]  탭: [항목 | 종합분석 | 버전 비교 | 최적화 실행 | 템플릿]
필터: 모델[▼] 크기[75형 1662×948 ▼] 씬유형[…] 판정[PASS만▼]
선택 3개 · 기준 75형 1662×948 · 같은 모델 3/3     [선택한 ESL로 비드 최적화 (3)]  [종합분석 만들기](주)
┌☐┬모델──────┬인치┬크기(mm)──┬씬──────────────┬모드──────┬판정┐
│☑│75QN80H ⓜ │75 │1662×948 │17 Corner 146 2nd│[굽힘 ▼] │PASS│  자동=회색, 수정=굵게
│☐̸│65QN80H   │65 │1452×826 │… (비활성: 크기 다름)             │
```
### 10.2 템플릿 탭
```
템플릿 (모든 사용자 공개)                                                   [템플릿 등록](주)
│75형 평판 v1 │fem│75│1660×950│48 210/47 600│차완기│사용 3│[삭제]│  (등록자·관리자만, 사용 중이면 "보관됨")
등록 패널: [.rad/.fem 끌어다 놓기] ███ 100% · 검사 오류 0 경고 1 · 제목[ ] 인치(선택)[ ] 설명[ ]  [등록]
```
### 10.3 새 비드 최적화 `/opt/new`
```
새 비드 최적화   탭 [● 기존 형상(S1) | ○ 템플릿(S2)]                       [최적화 실행](주, 비활성 사유 툴팁)
┌① 대상 (S1: Case·파트·노드/요소·PID 표·3-2-1 / S2: 템플릿 [▼]·크기 차·PID 표·3-2-1)──────────────┐
┌② 비드 금지 영역──────────────────────────────────────────────────────────────────────────────┐
│ ┌평면도 (a,b mm)────────────────────────────┐  자동: ☑구멍 주변 15 mm  ☑가장자리 10 mm (설정값)│
│ │ ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ (가장자리 띠)       │  사각형                                     │
│ │ ▒  ○▒      ┌──────┐            ▒        │  이름   기준모서리 X   Y   가로 세로        │
│ │ ▒          │ PCB  │ ← 드래그    ▒        │  PCB    [좌하▼]   120 80  300  200 [삭제]   │
│ │ ▒▒▒▒▒▒▒▒▒▒▒└──────┘▒▒▒▒▒▒▒▒▒▒▒▒         │  [＋사각형]                                 │
│ └ 0 ────────────────────────────── 1662 ───┘  저장된 세트 불러옴(2026-10-28 차완기) [이 모델에 저장]│
└────────────────────────────────────────────────────────────────────────────────────────────┘
┌③ ESL (3) · 모드: 굽힘 2 · 뒤틀림 1──────────────────────┐┌④ 비드 치수──────────────────────────┐
│ 75QN80H v072 17 Corner 146  [굽힘 ▼]  같은 모델 ✓       ││ ⑤ 경사 [45]°  폭 [60] mm  높이 [10] mm│
│ 75QN80H v073 05 Edge 12     [뒤틀림 ▼] 다른 모델 ✗       ││ 제목 [                    ]         │
│ [다른 모델 빼기] 다른 모델은 템플릿 최적화로              │└─────────────────────────────────────┘
└─────────────────────────────────────────────────────────┘
┌④ 하중 선정 전략 ⓘ─────────────────────────────────────────────────────────────────────────────┐
│ ● A 전부 넣기 [추천]  선택 ESL 모두, 거의 같은 형상(|MAC| ≥ 0.95)만 병합, 20개 초과 시 군집 대표   │
│ ○ B 모드별 최악       덴팅·뒤틀림·굽힘별 초기 컴플라이언스 최악 1개(최대 3개, 현재 2개)          │
│ ○ C 군집 대표 k개     k [5] (1~20)                                                             │
│ 목표 기준: ● 절대 [추천] 가장 큰 컴플라이언스 최소화(공통 상수 C_ref 로만 나눔)   ○ 상대 (C/C⁰ 최대 최소화) │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
솔버 미설정 시 상단 경고 띠 "서버 OptiStruct 경로가 설정되지 않았습니다(관리자 문의)"
```
- 목표 기준 라디오(④ 카드 아래 줄): 기본 절대(추천 배지), 상대. 전략과 독립.
- 전략 라디오: 기본 A(추천 배지), C 선택 시에만 k 입력 활성(정수 1..max_cases), B 는 모드별 후보 수 표시(0 이면 "(제외)"), 세 모드 모두 0 이면 B 비활성. ⓘ 은 ④ 제목과 상세 하중 선정 표에 같은 팝오버.
- 평면도: SVG, 대상 외곽·구멍·자동 영역(회색 빗금)·사각형(주황, 선택 시 핸들 없이 이동만), 드래그 → 가장 가까운 기준 모서리 유지한 채 X·Y 갱신(1 mm 반올림), 숫자 입력 → 즉시 이동. 1920 폭에서는 평면도 위·표 아래로 접힘.
- "이 모델에 저장" = `PUT /opt/keepouts`(S1 topo / S2 template). 저장하지 않고 실행해도 실행 스냅샷에는 현재 값이 들어감.

### 10.4 최적화 상세 `/opt/:id`
```
비드 최적화 · S1 · 75형 강건 비드 1차   상태 실행 중 (반복 12/30)              [보고서 보기](주, 완료 후)
┌진행: ✓대상 ✓하중·선정 ✓덱 ●OptiStruct ○후처리 ○등록 · 목적(절대) max C/C_ref 1.00→0.71 · 라이선스 대기 0 [로그][취소]┐
┌하중 선정 ⓘ  전략 A 전부 넣기 · 목표 절대(C_ref 1.23e4) · ESL 12 → 케이스 7 (병합 5, 군집 없음)                              ┐
│상태        씬                    C⁰       umax    모드    비고                                         │
│포함 L01    17 Corner 146 2nd     1.23e4   4.1 mm  굽힘                                                 │
│병합됨      21 Corner 146 2nd     1.19e4   4.0 mm  굽힘    → L01 (MAC 0.98)                             │
│병합됨      05 Edge 12            8.70e3   3.2 mm  뒤틀림  → L02 (MAC 0.97, 반대 방향)                  │
│(B: 모드 대표/미선정, C·A 상한 초과: 군집 대표/군집 멤버)                                               │
└ⓘ 팝오버: 방식 요약 3줄 + 전략별 한 줄(A·B·C) + 목표 기준 한 줄(절대·상대, 실행값 굵게) + 출처 3개(새 탭) — /opt/settings.method_sources┘
┌결과: [bead_map.png] 수렴 그래프 · 케이스별 C⁰→C (비율) · 비드 면적 34 % · 받기 [.rad] [.fem] [zip]┐
```
- 실패 시 오류 코드·메시지 + [다시 시도](power 이상).

## 11. 설정 키 (하드코딩 금지)

```yaml
altair:
  optistruct_path: "C:/Program Files/Altair/2026.1/hwsolvers/scripts/optistruct.bat"   # 예시, 없으면 503
  max_concurrent_os: 1
commands:
  os_check: ["{optistruct}", "{fem}", "-check", "-tmpdir", "{scratch}"]
  os_solve: ["{optistruct}", "{fem}", "-nt", "{nt}", "-tmpdir", "{scratch}"]
  bead_post: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{post_tcl_fwd}", "-input", "{h3d_fwd}", "-output", "{out_dir_fwd}", "-config", "{request_fwd}"]
opt_run:                                # 섹션 없으면 enabled: false
  enabled: true
  max_entries: 200
  size: {tol_rel: 0.02, plate_tol_rel: 0.05, require_inch: true}
  template: {max_elems: 500000, flat_tol_rel: 0.02, max_tria_frac: 0.2}
  bead_defaults: {angle: 45.0, min_width: 60.0, height: 10.0}      # 화면 기본값(deg, mm, mm)
  keepout: {hole_radius_mm: 15.0, edge_band_mm: 10.0, hole_min_perimeter_mm: 5.0, max_rects: 20}
  loads: {default_strategy: A, mac_merge: 0.95, max_cases: 20, default_k: 5, default_objective_norm: abs, linkage: average, c0_tol: 0.05}   # 하중 선정(§7.4)
  mode:                                 # 변형 모드 분류(§7.4) — 값 변경 시 rule_version 올림
    rule_version: 1
    dent_resid_min: 0.5
    dent_conc_min: 0.6
    dent_area_frac: 0.05
    min_energy_rel: 1.0e-6
  solver: {drill_factor: 1.0e-4, backend: auto}                    # 초기 컴플라이언스 자체 솔버
  solve:
    nt: 4
    desmax: 30
    timeout_h: 12
    log_tail_lines: 2000
    error_patterns: ["(?m)^\\s*\\*\\*\\* ERROR"]
    converged_patterns: ["OPTIMIZATION HAS CONVERGED"]
    license_patterns: ["(?i)license.*(not available|checkout failed|insufficient|exceeded)", "(?i)ALM_\\w+_ERROR"]
    license_retry: {max: 3, wait_s: 300}
    env: {}
  post: {png_px: [1600, 900]}
upload:
  allowed_ext: [..., .fem]
```
- `id_offset`·`card_format`·`num_format` 은 기존 `library.yaml optdeck`. OPT_RUN 은 `optdeck.objective`·`cases`·`max_cases`·`bead` 를 쓰지 않음(minmax·모드 선정·`opt_run.bead_defaults` 고정). 동일성 좌표 허용은 기존 `coord_check.max_rel`.
- 환경 점검(`check.py`): `optistruct_path`, `esl_bead_post.tcl`, `_templates` 쓰기 가능.

## 12. DB 변경 — migration `0010_opt_runs`

- 번호·체인: OR-D-22. 멱등, downgrade 미지원.
- **`opt_templates`**(전역): `id`, `title`(200), `description`(2000), `inch` NULL, `format`(rad|fem), `file_name`, `part_title`, `sha256`, `n_nodes`, `n_elems`, `L_xi`, `L_eta`, `z_range`, `pids` JSONB, `quality` JSONB, `dir_rel`(`_templates/<id>`), `status`(ACTIVE|ARCHIVED), `origin_project_id`, `created_by(_name)`, `created_at`, `archived_by`, `archived_at`(CHECK 짝), `updated_at`. Index `(status, created_at desc)`.
- **`opt_keepouts`**: `id`, `template_id` FK NULL, `topo_sha256` char(64) NULL, CHECK 정확히 하나, unique(`template_id`) WHERE NOT NULL, unique(`topo_sha256`) WHERE NOT NULL, `rects` JSONB(배열), `auto` JSONB, `frame` JSONB(a_range·b_range), `version` bigint ≥1, `updated_by(_name)`, `updated_at`. 템플릿 행 삭제 시 함께 삭제(ARCHIVED 는 유지).
- **`opt_runs`**: `id`, `project_id`, `scenario`(S1|S2), `title`, `entry_ids` JSONB(≥1), `analysis_id` FK NULL, `base` JSONB NULL(S1), `template_id` FK NULL, `size` JSONB NULL, `design` JSONB(bead·nondesign_pids·keepout 스냅샷), `options` JSONB, `load_strategy` char(1) NOT NULL DEFAULT 'A' CHECK IN ('A','B','C'), `objective_norm` varchar(3) NOT NULL DEFAULT 'abs' CHECK IN ('abs','rel'), `k` smallint NULL(CHECK `load_strategy <> 'C' OR k >= 1`), `job_id`, `result` JSONB, `report_rel`, `dir_rel`(`_opt/<id>`), `created_by(_name)`, `created_at`, `updated_at`. CHECK 시나리오별 base/template_id. Index `(project_id, created_at desc)`, `(template_id)`.
- `library_entries`: `topo_sha256` char(64) NULL + Index, `deform_mode` JSONB NULL(§7.4, 지연 백필).
- `jobs.opt_run_id` FK NULL + Index. 제약 교체: `ck_jobs_job_type`(+OPT_RUN), `ck_jobs_stage` 1~10, `ck_jobs_subject`(OPT_RUN 분기, 기존 분기에 `opt_run_id IS NULL`).
- `ARTIFACT_KINDS` += `opt_result`, `opt_solve`. `uploads` 변경 없음.

## 13. 보안 · 권한

- 조회: ACTIVE 로그인 + 프로젝트 조회 권한(opt_runs). 템플릿·템플릿 금지 영역 세트는 ACTIVE 로그인 누구나 조회.
- 쓰기 = power 이상: 실행·retry·cancel, 템플릿 check/등록, 금지 영역 세트 저장(S2 = 아무 프로젝트 power, S1 = 그 모델 ESL 이 있는 프로젝트의 power), 모드 수정(항목 프로젝트 power). 템플릿 삭제 = 등록자·전역 관리자. 판정 순서 401→404→403→409.
- S1: 선택 ESL·기준 Case 모두 요청 프로젝트 소속(아니면 404). Case 입력 경로는 기존 `check_includes`·input_roots 검사 통과분만 읽음. `plan-view?entry_id=` 는 항목 프로젝트 조회 권한.
- 입력 보호: 업로드·Case 입력 폴더 **읽기만**. 쓰기는 `_opt/<id>/`·`_templates/<id>/` 만.
- 업로드: 본인 것만, 본인 폴더 격리·`_backup`·심링크 거부, 템플릿 업로드 밖 include 거부.
- 외부 실행: LOCAL step, argv 템플릿·허용 argv[0]·메타문자 거부·shell=False. 덱 이름·경로는 서버 생성값만(제목·사각형 이름은 덱에 쓰지 않음, 보고서는 HTML 이스케이프).
- 다운로드 `rel` = files 목록 + realpath `_opt/<id>/` 안. `job_steps.command` 는 전역 관리자만. 디스크 여유 부족 507. 보고서 CSP·마스킹 기존 규칙.

## 14. 검증 계획

| ID | 시험 | 위치 |
|---|---|---|
| V-OR-1 | S2 크기 규칙(±2 %·±5 % 경계, 인치 null 경고, 템플릿 인치 없음/있음), 화면·API·OPT_PREP 일치 | `tests/opt/test_size.py`, `backend/tests/test_opt_api.py`, `frontend/__tests__/opt.test.tsx` |
| V-OR-2 | S1 동일성(topo 같음/노드 ID·연결 다름/회전·반전 동치/좌표 큰 이동), 지연 백필, `MODEL_MISMATCH`·`PREREQUISITE_MISSING` | `tests/opt/test_identity.py`, `backend/tests/test_opt_api.py` |
| V-OR-3 | S1 직접 적용(노드 순서 다른 같은 모델 → 노드별 정확 일치, 매핑 미호출), S2 매핑(셀 합력·합모멘트 보존 1e-9) | `tests/opt/test_load.py` |
| V-OR-4 | 모드 분류(전략 A·C 결과는 모드 변경과 무관함도 확인): 합성 w = P2(s)(굽힘)·s t(뒤틀림)·국부 가우시안 범프(덴팅)·혼합 경계·0 변위(null) → 기대 모드, 기준값 경계, rule_version 변경 시 auto 만 재계산·user 유지, PATCH 권한·version 충돌 | `tests/opt/test_modes.py`, `backend/tests/test_opt_api.py` |
| V-OR-5 | 하중 선정 전략별: 후보 C·umax 독립 계산 일치(1e-9), 분해 1회. **A**: 같은 형상 2개(크기 다름) → 큰 C 남김, mac 경계(0.95 ± ε), **부호 반전**(F·−F, 반대 방향 토션 합성) → 병합·sign −1, 병합 후 25개·max_cases 20 → 군집 20 대표 / 19개 → 군집 안 함. **B**: 모드별 C 최대·빈 모드 제외·`NO_MODE_CANDIDATES`·모드 수정 반영. **C**: k=1·5·후보 수 초과(=후보 수)·범위 밖 422. **결정성**: 전략마다 입력 순서 섞기·반복 10회 → LoadSelection 바이트 동일, C 동률 entry_id 규칙. C ≤ 0 제외·`NO_LOAD_CASES` | `tests/opt/test_select.py` |
| V-OR-6 | 금지 영역: 구멍 루프 검출(구멍 2개 판·결함 루프 무시), 반경·띠 경계 요소, 사각형 4 기준 모서리 좌표 변환, 경계 밖 잘림·완전 이탈 오류, 합집합 마스크, `KEEPOUT_ALL`, 평면도 자료와 워커 마스크 동일 | `tests/opt/test_keepout.py` |
| V-OR-7 | 금지 영역 세트 API: 템플릿/topo 키 저장·불러오기, version 충돌 409, frame 차이 경고, 실행 스냅샷이 이후 세트 수정에 영향 없음, 템플릿 삭제 시 세트 삭제·보관 시 유지 | `backend/tests/test_opt_keepouts.py` |
| V-OR-8 | 메시 검사 rad·fem(비지원 요소·두께·상한·연결·평탄도·법선·비드 폭/요소 크기·셀당 노드·3-2-1), fem 필드 형식·INCLUDE 거부 | `tests/opt/test_mesh_check.py`, `test_femread.py` |
| V-OR-9 | 템플릿 API: 등록 복사·공개 목록·삭제 권한·사용 중 ARCHIVED·미사용 삭제 + `_backup`·보관 템플릿 새 실행 거부·retry 허용·`PLATE_CHANGED` | `backend/tests/test_opt_templates.py` |
| V-OR-10 | 덱: `server` 없으면 기존 골든 불변, OPT_RUN 덱 골든(subcase L01…(C 내림차순), 목표 기준별 DOBJREF POS(abs = 모든 subcase C_ref = max C⁰ 같은 값, rel = subcase별 C_i⁰), 헤더 objective_norm·C_ref, 금지 영역 요소 비설계 PSHELL·DTPG 목록 제외, DOPTPRM·OUTPUT, 비드 45°·60·10) | `tests/library/test_optdeck*.py`, `tests/opt/test_deck.py` |
| V-OR-11 | OS_SOLVE 가짜 솔버(정상·check 실패·라이선스 2회 후 성공·소진·종료코드 1·타임아웃·취소), argv 검사, 세마포어(PG) | `worker/tests/test_opt_solve.py` |
| V-OR-12 | 재시도 재사용(OS_SOLVE SKIPPED), 덱 sha 다르면 재실행, S1 `INPUT_CHANGED` 경고, 재시도는 실행 스냅샷 사용 | `worker/tests/test_opt_e2e.py` |
| V-OR-13 | 후처리: 가짜 shape.csv → bead.npz·csv·PNG(결정적 바이트)·bead_mesh.rad 재파싱(좌표·ID)·.fem, `c0_tol` 경고 | `tests/opt/test_post.py` |
| V-OR-14 | 입력 보호: S1 Case 입력·S2 업로드 폴더 실행 전후 불변, 업로드 stale 이동 후에도 실행·retry 성공 | `worker/tests/test_opt_e2e.py` |
| V-OR-15 | API 공통 권한·`SOLVER_NOT_CONFIGURED`·다운로드 탈출·bundle 상한·CSP·`plan-view` 크기 상한 | `backend/tests/test_opt_api.py` |
| V-OR-16 | migration 0010(빈·0008 DB, 멱등, tables.py 일치, 기존 행 제약, 0009 존재/부재 두 체인) | `backend/tests/test_migrations.py` |
| V-OR-17 | E2E(가짜 솔버·hw): S1(같은 모델 ESL 3개, 모드 2종, 사각형 1개) / S2(템플릿 등록 → 세트 저장 → 실행) → 선정·덱·결과·이력·알림 | `worker/tests/test_opt_e2e.py` |
| V-OR-18 | UI: 행 선택·크기 비활성·ⓜ·모드 드롭다운 저장, S1/S2 탭, 다른 모델 빼기, 평면도 드래그 ↔ 숫자 동기화(4 기준 모서리), 세트 불러오기/저장·충돌 메시지, 비드 3칸 기본값 45·60·10, 목표 기준 라디오(기본 절대·추천 배지), 전략 라디오(기본 A·추천 배지·C 만 k 활성·B 비활성 조건), 하중 선정 표(상태별·병합 대상·반대 방향 표기·전략 표시)·ⓘ 팝오버(요약·전략별 줄·출처 링크 새 탭·키보드 닫기), 주 버튼 비활성 사유, 상세 선정 하중 표, 2560×1440·1920×1080 잘림 없음(Playwright) | `frontend/__tests__/opt.test.tsx`, `keepout.test.tsx`, mock |
| V-OR-19 | 환경 점검 ↔ `/opt/settings.solver_ready` | `backend/tests/test_check.py` |
| V-OR-20 | 방법·출처·전략 저장: `opt_method_sources.json` 스키마, `/opt/settings.method_sources` = 파일, 보고서 "방법·출처" 절 = 같은 문구·링크(이스케이프)·실행 전략 표시, `opt_runs.load_strategy`·`k` 저장·응답·retry 시 유지, 잘못된 전략·k 422 | `tests/opt/test_report.py`, `backend/tests/test_opt_api.py` |
| V-OR-21 | 목표 기준: 기본 abs 저장·응답, rel 선택 저장·retry 유지, 잘못된 값 422, C_ref = 선정 케이스 C⁰ 최대(병합·군집 후 기준), 합성 2하중(크기 10배 차) 덱에서 abs 는 POS 동일·rel 은 각자, 보고서·선정 표·팝오버 표시 | `tests/opt/test_deck.py`, `backend/tests/test_opt_api.py`, `frontend/__tests__/opt.test.tsx` |
| V-OR-R1 | **실기**: S2 작은 평판·ESL 3개(모드 3종), S1 실제 chassis rear(22만 요소)·사각형 금지 영역 → `-check`·수렴·Shape Change·비드 맵 = HyperView, 금지 영역에 비드 없음, C_os^0 ≈ C_self^0. DTPG·DOBJREF·OUTPUT 확신도 해소 | `docs/manual/opt_run_check.md` |
| V-OR-R2 | 실기: 실제 모델 ESL 모드 자동 분류를 사용자가 확인(오분류율 기록 → 기준값 조정), 라이선스 부족 메시지 패턴 | 수동 |

## 15. 단계적 구현 분해 (파일 소유권)

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| O1 코어 | Impl-Core | `esl/opt/__init__.py`, `mesh_check.py`, `femread.py`, `identity.py`(topo·동일성), `size.py`, `target.py`(CaseTarget·TemplateTarget), `keepout.py`(구멍·가장자리·사각형·평면도 자료), `modes.py`(분류), `select.py`(초기 컴플라이언스, 전략 A 병합·군집 / B 모드 대표 / C 군집 k, ShellModel 1회 분해), `osout.py`, `post.py`, `png.py`(평면도 렌더러 공용), `report_opt.py`; `esl/library/optdeck.py`(`server` 옵션·비설계 요소 목록 입력·subcase 라벨), `esl/library/entry.py`(등록 시 topo·deform_mode 메타), `esl/mech/shell.py`(분해 재사용 API 가 없으면 `factorize()`/`solve_many` 추가만); `resources/tcl/esl_bead_post.tcl`, `resources/opt_method_sources.json`; `tests/opt/*` | V-OR-1~6, 8, 10, 13, 20 |
| O2 백엔드 | Impl-Backend | `migrations/versions/0010_opt_runs.py`, `core/db/tables.py`, `core/job_types.py`, `core/config.py`(OptRunCfg·altair·commands), `core/paths.py`(`OPT_DIR`·`TEMPLATE_DIR`), `core/repositories/opt.py`(runs·templates·keepouts), `core/repositories/jobs.py`(`acquire_os`), `api/routers/opt.py`, `api/services/opt.py`(runs·s1-check·plan-view), `api/services/opt_templates.py`, `api/services/opt_keepouts.py`, `api/schemas.py`, `api/services/library.py`(size·topo·deform_mode 지연 백필, PATCH deform_mode), `api/services/uploads.py`, `api/services/history.py`, `check.py`, `config/*.example.yaml`, `backend/tests/test_opt_*.py`·`test_migrations.py` | V-OR-2·4(API), 7, 9, 15, 16, 19 |
| O3 워커 | Impl-Worker | `worker/esl_worker/localproc.py`(h3d 공통화), `os_solve.py`, `opt_jobs.py`, `executor.py`, `core_adapter.py`(opt_prep/opt_load/opt_deck/opt_post), `register.py`(OPT_REGISTER, 등록 시 deform_mode 계산 포함), `worker/tests/test_opt_*.py`, `tests/fake_optistruct.py` | V-OR-11, 12, 14, 17 |
| O4 프런트 | Impl-Frontend | `api/opt.ts`, `api/types.ts`, `api/history.ts`, `pages/opt/OptNew.tsx`, `OptDetail.tsx`, `OptList.tsx`, `Templates.tsx`, `components/KeepoutPlan.tsx`(SVG 평면도·드래그·숫자 동기화), `components/ModeSelect.tsx`, `components/LoadStrategy.tsx`(라디오·k), `components/LoadSelectionTable.tsx`, `components/MethodInfo.tsx`(ⓘ 팝오버), `pages/library/LibraryList.tsx`(행 선택·크기·ⓜ·모드 열·탭), `pages/library/AnalysisDetail.tsx`, `app/App.tsx`, `mock/optdata.ts`, `__tests__/opt.test.tsx`·`keepout.test.tsx`, `pages/guide/*` | V-OR-18 |
| O5 문서 | Plan/Impl | `CHANGELOG.md`·`VERSION` 0.7.0, `docs/decisions.md`, `docs/manual/user.md`, `docs/manual/opt_run_check.md` | V-OR-R1·R2 체크리스트 |

- 순서: O1 → (O2 ∥ O3, O3 는 O2 의 job_types·tables·config 선행) → O4(mock 병행) → 통합 E2E → 실기(S2 → S1).
- 경계: 백엔드는 코어 `esl.opt.size`·`identity`·`mesh_check`·`femread`·`keepout`(평면도)·`modes`(지연 분류)만 import(모두 수 초 이내). 쉘 솔버·대형 rad 파싱은 워커에서만.

## 16. 후속 (v0.7.0 범위 밖)
- **CAD/STEP 템플릿**: STEP 업로드 → 서버 메싱(HyperMesh 배치 또는 별도 메셔, argv 템플릿) → 쉘 메시 템플릿 등록. 별도 계약.
- 메타 편집(Case 단계 모델·인치 편집, 태그): 사용자 확인 후 결정.
- 3D 비드 보기(view3d GLB 재사용), 임의 다각형 금지 영역, HPC 제출, 비드 반영 메시 자동 검증 낙하.

## 17. 확정 사항 (2026-10-28, 사용자)

| 항목 | 확정 | 반영 |
|---|---|---|
| 1차 Q1 평판 형식 | 시나리오 2개: S1 Case rad 대상 파트, S2 템플릿 `.rad`·`.fem`(CAD/STEP 후속) | §3, OR-D-3~9 |
| 1차 Q2 같은 크기 | 같은 인치 + ESL 간 ±2 %, 템플릿 ±5 %(S2), S1 은 모델 동일성 | OR-D-4·7, §7.1 |
| 1차 Q3 비드 방향 | 지금 덱과 같음(+n, BOUNDS 0~1) | OR-D-10 |
| 1차 Q4 라이브러리 반영 | 넣지 않음, "최적화 실행" 목록 | OR-D-21 |
| 1차 Q5 라이선스 | 3회 × 300 초 자동 재시도 후 실패 | OR-D-18 |
| 템플릿 공개·삭제 | 모든 사용자, 등록자·관리자 삭제, 사용 중 보관 | OR-D-8 |
| S1 다른 모델 ESL | 선택 불가 + 템플릿 안내(계약 결정) | OR-D-5 |
| 2차 비드 금지 영역 | 자동(구멍 반경·가장자리 띠) + 사용자 사각형(기준 모서리·X·Y·가로·세로 mm), 평면도 드래그 동기화, 템플릿/모델별 저장 | OR-D-11·12, §7.5, §10.3 |
| 2차 다중 ESL 목표 | 모드별 최악 ≤3 → 3차에서 전략 B 로 유지(기본 아님) | §7.4 |
| 2차 비드 치수 | 화면 3칸, 기본 45°·60 mm·10 mm | OR-D-16 |
| 2차 §18 Q1 S1 법선 | **가정 확정**: 원 연결 유지, 반대 법선 경고만 | OR-D-10 |
| 2차 §18 Q2 템플릿 인치 | **가정 확정**: 선택 입력 | §7.1 |
| 3차 하중 선정 | ESL 1개 = 케이스 1개(t* 단일 시점). 전략 라디오 A 전부 넣기(기본·추천: |MAC| 부호 무관 ≥ 0.95 병합, 20 초과 시 average linkage 군집 대표) / B 모드별 최악 ≤3 / C 군집 대표 k(기본 5). 목표 min-max(기준은 '3차 목표 기준'), `opt_runs.load_strategy`·`k` 저장 | OR-D-14, §7.4, §10.3 |
| 3차 모드 용도 | 표시·보고서·라이브러리 분류/검색 + 전략 B, 저장·수정 유지 | OR-D-13 |
| 3차 방법·출처 | 선정 표 옆 ⓘ 팝오버(요약·전략별 한 줄·출처) + 보고서 "방법·출처" 절, 자료 파일 1곳 | §9.1, §10.4 |
| 3차 목표 기준 | 절대(기본·추천): min max C_i, 공통 C_ref = max C_i⁰ 로만 나눔(DOBJREF POS = C_ref 전부) / 상대 옵션: max C_i/C_i⁰(POS = C_i⁰). `opt_runs.objective_norm` 저장, 사용자 가중 없음 | OR-D-15, §7.4, §10.3 |
| 메타 편집 | 보류(§16 한 줄) | §16 |

## 18. 미결 질문
- 없음. (분류 기준값 `opt_run.mode.*`·자동 금지 영역 기본값 15/10 mm 은 설정 임시값 — 실기 V-OR-R2 에서 사용자 확인 후 조정.)
