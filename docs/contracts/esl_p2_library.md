# 계약 초안: P2 — ESL 라이브러리 · 종합분석 · 비드 최적화 덱 · 보고서

- 상태: **확정** (2026-10-19). §0 가정 3개 사용자 승인.
- 목표: 모델(인치 파생)·낙하씬별 ESL을 DB에 쌓고, 설계 대상 모델 메시로 매핑·종합해 **강건 비드 설계용 OptiStruct topography(DTPG) 덱**과 근거 **보고서(HTML)**를 만든다.
- 사용자 확인(2026-10-19): ① OptiStruct 사용 중이나 낙하 하중을 근거로 쓴 적 없음 → 최적화 덱 + 보고서까지. ② 모델은 파생이지만 TV 인치가 다름. ③ 씬 메타는 폴더명=파일명 규칙(번호·규칙 포함), ISTA 6 규칙 참조.

## 0. 확인 질문(가정과 함께)
- Q1 파일명 규칙 해석(아래 §2 예시)이 맞는가? 특히 `CUMULATIVE`(연속 낙하 누적 시나리오 — 이전 낙하의 소성이 남은 상태)와 끝의 `_2nd` 의미.
- Q2 설계 영역: 가정 = 대상 파트 전체, 비설계 영역은 PID 목록 또는 마운트 노드 반경(설정). 비드 파라미터 기본값 가정 = 최소폭 10 mm, 높이 3 mm, 각도 60°, 대칭 없음.
- Q3 인치 간 하중 크기 정규화: 가정 = 절대값 저장 + 집계 시 선택(`none`|`mass`|`inch2`). 제품 질량은 rad에서 전체 질량 계산(가능 시) 또는 사용자 입력.

## 1. 라이브러리 등록 (P2-a)
- Case의 검증 PASS run(또는 FAIL을 사용자가 사유와 함께 "확정")을 `library_entries`로 등록. 등록 시 스냅샷(`runs/<id>/`) 고정, 수정 불가(정정 = 새 등록 + 이전 것 retired).
- 저장 3층:
  | 층 | 내용 | 저장 |
  |---|---|---|
  | 원본 | 절점 F_eq, u_rel, 3-2-1, 메시(node_id, x0, conn) | 파일(sha256), DB엔 경로 |
  | 정규화 요약 | 정규화 좌표 (ξ,η)∈[0,1]² (PCA 평면 + 바운딩, 축 방향 규약 고정: ξ=가로, η=세로, n=후면 바깥) 격자 `grid.nx×ny`(기본 24×14) 셀별 합력(3)·합모멘트(3, 셀 중심 기준), 전체 합력·합모멘트, 상위 절점력 50개(정규화 좌표), hotspot(정규화 좌표, ε), t* | DB JSONB + npz |
  | 메타·품질 | 모델(제품명, 인치, 버전, 날짜), 씬(§2), 검증 verdict·hotspot 오차·잡음, 솔버, 등록자 | DB 컬럼 |
- 축 방향 규약: 모델마다 PCA 부호가 뒤집히지 않도록 전역 좌표축과의 내적 부호로 고정(설정 `library.axis_ref`, 기본 ξ≈+X, η≈+Z).

## 2. 씬 메타 파싱
- 설정 정규식(named group)으로 경로·파일명에서 추출. 기본 규칙(예: `F:/Hyper_work/VD_25y/75QN80H/75QN80H_v072_260511/CUMULATIVE/17_Corner_Drop_2nd_Scene10_Corner146_2nd_comp.h3d`):
  - project `VD_25y`, model `75QN80H`, inch `75`(model 앞 숫자), version `v072`, date `260511`, scenario `CUMULATIVE`
  - seq `17`, drop_type `Corner`(Corner|Edge|Face), round `2nd`, scene `10`, orient `146`(ISTA 면 번호 조합: 꼭지점 = 면 3개, 모서리 = 2개, 면 = 1개), suffix `2nd`, variant `comp`
- ISTA 6 면 번호 정의(1~6)와 낙하 높이 표는 설정 파일(`config/ista6.yaml`)로 분리. 파싱 실패 필드는 null + 경고, 사용자가 UI에서 수정 가능.

## 3. 종합분석 (P2-b)
- 입력: 설계 대상 모델(라이브러리 항목의 메시 하나) + 필터(모델·씬·verdict·시나리오).
- 매핑: 각 항목의 셀 합력·합모멘트를 대상 메시의 해당 셀 노드들에 분배(셀 내 노드에 대한 최소노름 해: 합력·합모멘트 보존). 대상 모델 자신의 항목은 원본 절점 F_eq 그대로. 결과 = 대상 메시 위 하중 케이스 집합 {F_k}.
- 정규화: §0 Q3 옵션.
- 분석: (a) 셀별 포락(최대 |F|, 방향), (b) 대표 케이스: {F_k}를 SVD → 누적 에너지 `analysis.svd_energy`(기본 0.9)까지 모드 + k-medoids로 실제 씬 `analysis.n_representative`(기본 5)개 선택(합성 하중이 아닌 실제 씬을 대표로), (c) 최악 케이스: 각 대표 클러스터 내 합력 최대 씬 포함 옵션.
- 산출: `analysis_runs`(DB) + 폴더 `<esl_root>/_analysis/<id>/`(mapped_loads.npz, envelope.csv, representatives.csv).

## 4. 비드 최적화 덱 (P2-c)
- OptiStruct `.fem`(자유형식): 대상 파트 쉘 bulk(GRID/CQUAD4/CTRIA3/PSHELL/MAT1) + 하중 케이스별 SUBCASE(FORCE + 3-2-1 SPC1, 자기평형) + `DTPG`(설계 PID, 비드 폭·높이·각도·방향 = 쉘 법선, `BEADFRAC` 선택) + 응답 `DRESP1 COMP`(subcase별) + 목적 `minmax` 컴플라이언스(`DOBJREF` + `DESOBJ(MIN)`/MINMAX 형식은 OptiStruct 버전 문법 확인 후 고정) 또는 `weighted`(설정).
- 비설계 영역: 설정 PID/노드 반경 → DTPG 제외.
- 실행은 사용자 측(Windows/HPC). 덱·하중 inc·실행 배치 파일·README를 `_analysis/<id>/opt/`에 생성. 결과(h3d) 회수·후처리는 P3.

## 5. 보고서
- **HTML 단일 파일**(자체 완결: CSS·그림 inline SVG·데이터 inline, 외부 CDN·스크립트 의존 없음, 오프라인 열람). 플랫폼 UI에서 바로 보기 + 다운로드. PDF·LibreOffice 변환 없음(2026-10-19 사용자 지시). PPTX는 선택 옵션(`report.pptx: false` 기본).
- Case 보고서: 입력·t* 곡선·지지점·F_eq 상위·검증 표.
- 종합분석 보고서: 표지, 대상·필터, 씬 표(메타·verdict, 정렬 가능), 포락 맵(정규화 격자 히트맵 + 대상 형상 위), 대표 케이스(모드 에너지, 선택 씬, 하중 그림), 비드 최적화 설정 요약, 한계(선형 ESL·소성·매핑 근사).
- 생성은 Python(템플릿 엔진 없이 고정 레시피 또는 표준 라이브러리 `string.Template`), 저장 `<esl_root>/_analysis/<id>/report.html`, Case는 `<case>/07_report/report.html`.

## 6. 리스크
- R-P2-1 인치 간 정규화 좌표 매핑은 기하 비례 가정 — 마운트·보스 위치가 비례하지 않으면 국부 하중 위치 오차. 대응: 대상 모델 자체 씬 우선, 이후 랜드마크(마운트 노드) 매핑 옵션.
- R-P2-2 CUMULATIVE 시나리오의 누적 소성 — 선형 ESL 오차 증가. verdict·hotspot 오차로 필터.
- R-P2-3 DTPG minmax 문법·버전 — 2026.1 매뉴얼 기준 확인 필요(덱은 골든 시험 + 사용자 실행 확인).

## 7. ESL 재현 정확도 비교 · 겹쳐보기 (P2-0, 다른 P2보다 먼저)
목적: "정해진 등가하중이 낙하 최대변형률을 맞히는가"를 전 요소 수준에서 % 오차로 보이고, 겹쳐 본다.

### 7.1 데이터
- TCL 패스 C에 각 후보 프레임 f의 **직전 프레임 f−1**을 추가(전 요소 Max_Strain·Plastic). → 전 요소 "상승 중" 마스크 `rising(e) = v[f,e] > v[f−1,e]·(1+rtol)`(f=0이면 v>0). strain_frames.npz에 `prev_*` 배열 추가.
- 비교 대상 Radioss 값: t*에서 상승 중인 요소의 Max_Strain(= 순간값). 상승 중 아님 → 비교 불가(회색, 사유 `HOLD`).

### 7.2 지표 (`05_val/compare_field.npz` + validation.json `field`)
- 요소별 `eps_rad`, `eps_esl`(S5 막 변형률 ε_eq, 같은 공식), `rel_err = (eps_esl − eps_rad)/eps_rad`, `valid`(rising ∧ eps_rad ≥ `compare.min_rel`·max eps_rad, 기본 0.1).
- 요약: **최대변형률 비교** `max_rad`(t* 전체 상승 요소 중 최대), `max_esl`(같은 요소의 ESL 값과 ESL 전체 최대 둘 다), `max_err_pct`; valid 요소의 |rel_err| 평균·P50·P90·P95·최대, 오차 ≤5%/≤10%/≤20% 요소 비율, 상위 N(기본 20) 요소 표, 히스토그램(20 bin).
- 판정 기준에 `compare.max_err_pct_max`(최대변형률 오차, 기본 10%)·`compare.p90_err_max`(기본 20%) 추가(설정, 임시값).
- 의미 주석(보고서·UI): F_eq는 u_rel(강체 제거 변위장)을 선형 탄성 모델에서 재현하는 하중이므로 변형률(운동학량)은 요소 정식화·회전 자유도 차이만큼만 어긋나고, 응력은 소성 영역에서 탄성 과대평가된다.

### 7.3 겹쳐보기 (UI ⑤ + Case HTML 보고서)
- 2D 투영(PCA 평면) 요소 컨투어: 레이어 `Radioss ε` / `ESL ε` / `오차 %` 전환 + **겹치기 모드**(두 장 불투명도 슬라이더 또는 좌우 스와이프), 공통 색 범위, 비교 불가 요소 회색, hotspot 표시.
- 변형 형상 겹치기: 초기 외곽선 + u_rel(Radioss) 외곽선 + u_val(ESL) 외곽선, 변형 배율 슬라이더(면외 성분을 2D에 표시하는 단면선 옵션: ξ 또는 η 고정 단면 1개).
- 표: 상위 N 요소(요소 ID, ε_rad, ε_esl, 오차 %), 히스토그램.
- 데이터 API: `GET /validations/{id}/field?layer=rad|esl|err&max_points=` (요소 중심 2D 좌표 + 값, 2D 셀 격자 다운샘플링으로 ≤ `ui.max_preview_points`; 원본 개수 반환), `GET /validations/{id}/section?axis=xi|eta&at=0.5`.
- 3D 뷰는 제안(비필수).

## 8. 전체(전 라이브러리) 분석
- §3 종합분석은 필터를 비우면 라이브러리 전체 대상. 추가로 **통계 뷰**: 씬 유형(Corner/Edge/Face·orient)별, 인치별 합력·셀 포락 분포, 검증 오차 분포, 씬 간 하중 패턴 유사도(SVD 계수 산점) — 대상 모델 없이도 가능(정규화 격자 기준).

## 9. 구현 순서
1. P2-0(§7) 코어+TCL → 플랫폼·UI.
2. P2-a/b/c 코어(`esl/library/`: 메타 파싱·정규화 요약·매핑·SVD/k-medoids·DTPG 덱·HTML 보고서) — 순수 함수 + CLI.
3. 플랫폼: 라이브러리 테이블·API·분석 작업·UI(라이브러리 목록, 분석 생성, 보고서 보기).

## 10. 구현 반영 (2026-10-19, 코어 f4ff26f)
- 대표 선택 특징: 기본 `analysis.svd_feature: cell`(대상 격자 셀 합력·합모멘트, 케이스별 단위 노름 정규화) — 절점력 특징은 원본/매핑 해상도 차이로 같은 패턴 유사도가 붕괴(cos 0.05)하므로. `nodal`은 옵션. 크기는 최악 케이스 옵션·minmax가 담당.
- 매핑 후 최소노름 평형 보정(기본 켬, 보정량 기록).
- DTPG SKIP=BC 고정(전 노드 FORCE이므로 LOAD/BOTH 금지). 덱은 사용자 측 `optistruct -check`로 문법 확인 필요. `card_format: free|fixed`.
- 저장: `mapped_loads.npz`는 대표·최악 케이스만 저장(전체 K×N×3은 필요 시 재계산) — 규모(22만×수백 씬) 대응.
  형식: `mapped_F` (L,N,3) + `load_case_index` (L,)·`load_case_entry_id` (L,) (L = 대표+최악 수, `load_cases` 순서). 분석은 케이스별로 하중을 만들어 셀 합·절점 포락·Σ|f|만 누적(nodal 특징만 K×3N 메모리), 선택 케이스는 재계산. 꺼내기: `analysis.load_case_forces(result, arrays)`.
- 덱: `optdeck.write`는 3-2-1 지지의 강체 6모드 구속 행렬 rank 6·σmin/σmax ≥ 1e-6 아니면 `SUPPORT_DEGENERATE`(optdeck.json `support_check`).
- 보고서 inline JSON(Case·분석 공통 `esl.report.html.json_text`): `</`·`<!--`·`<script`의 `<` → `\u003c`.
- 제품 질량(`mass` 정규화): 기본값(파트 질량)은 제품 질량이 아니므로 `mass` 모드는 항목 메타 `product_mass`가 있을 때만 허용, 없으면 `NORMALIZATION_META_MISSING`. 사용자 입력(UI) 또는 rad 전체 질량 계산 옵션.

## 11. 플랫폼 계약 (P2 UI·API)
### DB (Alembic 0003)
- `library_entries`: id, case_id, esl_run_id, validation_id, status(`ACTIVE`|`RETIRED`), retired_by_id, model{name, inch, version, date, product_mass?}, scene{project, scenario, seq, drop_type, round, scene_no, orient, suffix, variant, raw}, quality{verdict, field_max_err_pct, field_p90_err_pct, noise}, tstar, summary_rel(npz 경로), sha256, registered_by/at, note. unique(esl_run_id) WHERE ACTIVE.
- `analysis_runs`: id, project_id, target_entry_id, filters JSONB, options JSONB, status(job 연동), result_rel, report_rel, optdeck_rel, created_by/at.
### 작업 유형 추가
- `CASE_REPORT`(LIGHT): 코어 `report` 단계 → `07_report/report.html`. VALIDATE 성공 시 자동 큐(설정 `report.auto`, 기본 true).
- `LIB_ANALYZE`(SLOT): esl.library analyze + optdeck + report → `<esl_root>/_analysis/<id>/`.
### API
- `GET /validations/{id}/field?layer=rad|esl|err&max_points=` → `{n_total, n_returned, decimated, plane:{origin,e1,e2}, color_range:{min,max}, points:[[elem_id, a, b, value, reason]]}`; `GET /validations/{id}/section?axis=xi|eta&at=0.5` → `{s[], w_rad[], w_esl[], w0[]}`; validation 응답에 `field` 요약.
- `GET /cases/{id}/report` → HTML(`Content-Type: text/html`, CSP `default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:`), `?download=1`이면 첨부.
- `POST /library/entries` `{esl_run_id, validation_id?, note?, force_reason?}`(FAIL은 force_reason 필수, power 이상) → 201; `POST /library/entries/{id}/retire`; `PATCH /library/entries/{id}` `{version, model.product_mass?, scene.*}`(메타 수정만); `GET /library/entries?project_id=&model=&drop_type=&orient=&verdict=&status=`.
- `POST /library/analyses` `{project_id, target_entry_id?, filters, options}` → 201 + LIB_ANALYZE 작업; `GET /library/analyses`, `GET /library/analyses/{id}`(요약: 대표·포락·통계), `GET /library/analyses/{id}/report`(HTML, 위 CSP), `GET /library/analyses/{id}/files`(optdeck 등 다운로드 목록).
- 오류 코드 추가: ENTRY_EXISTS, VALIDATION_NOT_PASS, MAPPING_DEGENERATE, GRID_MISMATCH, NORMALIZATION_META_MISSING.
### UI
- ⑤ 검증: 기존 표 + **겹쳐보기 카드**(레이어 전환 Radioss/ESL/오차, 불투명도 슬라이더, 공통 색범위, 회색=비교불가, hotspot 표시) + 단면선 카드(배율 슬라이더) + 최대변형률 비교 수치·분위수·히스토그램 + "보고서 보기"(새 탭) + "라이브러리 등록"(주 버튼은 '검증 실행' 유지, 등록은 결과 카드 안 보조 버튼).
- 상단 경로바 옆 전역 메뉴 1개 "라이브러리": `/esl/p/:projectId/library`(항목 표: 모델·인치·씬·verdict·오차, 필터, 메타 수정) → `/esl/p/:projectId/library/analyses/new`(대상 선택·필터·옵션 최소: 정규화 모드, 대표 수, 목적 minmax|weighted) → `/esl/p/:projectId/library/analyses/:id`(진행·요약·보고서 보기·덱 다운로드). 화면당 주 버튼 1개.

## 12. 최적화 하중 구성 변경 · 설계 버전 비교 (2026-10-19 확정)
### 12.1 덱 하중 케이스
- 설정 `optdeck.cases: all | representative | representative+worst`, **기본 `all`**: 필터에 걸린 모든 씬 ESL(대상 메시로 매핑)을 각각 subcase로 넣고 minmax 컴플라이언스.
- `optdeck.max_cases`(기본 60): `all`에서 씬 수가 이를 넘으면 `representative+worst`로 자동 축소하고 경고 + 보고서에 "제외된 씬과 사유" 표. 상한으로 거부하지 않는다(축소만).
- 같은 K이므로 subcase 수는 해석 비용에 거의 영향 없음(분해 1회, 다중 RHS) — 보고서에 subcase 수·축소 여부 명시.
- 대표 케이스(k-medoids)는 덱 구성이 아니라 **보고서의 하중 패턴 설명용**으로 유지.
- 저장(`mapped_loads.npz`): 덱에 들어간 케이스 전부(= all이면 전 씬). 규모 경고는 유지.
- API·UI: 분석 생성 옵션에 "최적화 하중: 모든 씬(기본) / 대표 / 대표+최악" 1개 추가, 상세 화면에 subcase 수·축소 여부 표시.

### 12.2 설계 버전 비교(ESLSO 수렴 판정)
- 목적: 비드 반영 설계의 **검증 낙하** 결과를 이전 설계와 비교해 추가 반복 필요 여부를 판단.
- 짝 지정: 같은 `model`(제품명)·같은 씬 키(`scenario, seq, drop_type, round, scene_no, orient, suffix`)에서 `version`이 다른 라이브러리 항목. 기준/비교 버전은 사용자가 선택(기본: 직전 버전).
- 지표(씬별): 하중 패턴 유사도 `cos`(대상 격자 셀 합력·합모멘트, 단위 노름), 합력 크기 비, hotspot 위치 이동(정규화 좌표 거리), 최대변형률 비(ε_max 신/구), 검증 품질 변화. 집계: 씬 cos 최소·평균, 대표 케이스 동일 여부(같은 k로 재군집 후 매칭).
- 판정(설정, 임시값): `convergence.cos_min: 0.9`, `convergence.rep_same: true` 만족 → "수렴(반복 불필요)", 아니면 "추가 반복 권장" + 바뀐 씬 목록.
- 산출: `<esl_root>/_compare/<id>/`(compare.json, report.html — 씬별 표, 셀 포락 차이 히트맵, 수렴 판정). 작업 `LIB_COMPARE`(LIGHT).
- API: `POST /library/comparisons` `{project_id, model, base_version, new_version, filters?}`, `GET /library/comparisons[/{id}[/report]]`. 오류 `NO_PAIRED_SCENES`.
- UI: 라이브러리 목록에 "버전 비교" 진입(주 버튼은 기존 유지, 보조), 비교 상세 화면(판정 배지·씬 표·보고서 보기).

### 12.3 구현 반영 (2026-10-20)
- 설정: `optdeck.cases`·`optdeck.max_cases`·`convergence.{cos_min, rep_same}` 는 없으면 기본값(all·60·0.9·true)으로 채운다(설치본 library.yaml 은 업데이트 때 덮어쓰지 않으므로). 그 밖의 키는 여전히 필수.
- 분석 결과 `deck`: `{requested, mode, reduced, max_cases, n_cases, n_subcases, cases[{label, case_index, entry_id, role}], excluded[{case_index, entry_id, scene, reason}]}`. all 의 subcase 라벨 `S###`(씬 순서), 대표/최악은 `REP#`/`WORST#`. `mapped_loads.npz` = 덱 케이스 전부 + 보고서 대표·최악(합집합, 덱 순서 먼저). 덱 작성은 `analysis.optdeck_load_cases`. 분석 옵션 `optdeck_cases`(API·CLI `--optdeck-cases`), 상한은 설정만.
- 비교 특징 = 각 항목 정규화 격자 셀 합력·합모멘트(§8 과 같은 특징, 같은 nx×ny 필요 — GRID_MISMATCH). 합력비 = Σ|f_i| 신/구, ε_max = t* eps_max(없으면 hotspot1 eps_rad), hotspot 이동 = hotspot1 (ξ,η) 거리. 대표 동일 = 짝 씬만 버전별 같은 k(설정 analysis.n_representative, 옵션으로 변경) k-medoids(거리 √(2−2cos)) → 멤버 겹침 최대 매칭(헝가리안) → 모든 쌍의 medoid 씬이 같음.
- 같은 버전에 같은 씬 키가 여럿이면 최근 등록 항목. 기준 버전 기본 = 비교 버전 직전(자연 정렬 v2 < v10). API: `new_version` 필수, `base_version`·`filters`(inch·drop_type·drop_class·orient·scenario·verdict)·`options`(cos_min·n_representative)·`title` 선택. 오류: `VERSION_NOT_FOUND`(422), `NO_PAIRED_SCENES`(422, 생성 시점 DB 메타 기준), `GRID_MISMATCH`, 같은 버전 `INVALID_PARAMS`.
- DB 0004: `comparisons`(verdict CONVERGED|ITERATE, result 요약), `jobs.comparison_id`(작업 대상 = Case | 분석 | 비교 중 하나), stage 9 = 버전 비교. 보고서 CSP·경로 보호는 분석 보고서와 같음.
- 합성 시험 메시(가로 24~30 요소)는 격자 24×14 와 해상도가 비슷해 셀 합이 계단져 같은 패턴도 cos ≈ 0.85 — 실제 모델(수십만 요소)에는 해당 없음. E2E 는 cos_min 0.8 옵션으로 시험.

### 12.4 검증 반영 (2026-10-20, Verifier HEAD 7906d23)
- `convergence.cos_min` 기본 **0.95**(실모델 셀당 노드 ≥64 기준, 같은 패턴 ≥0.99 여유). 셀당 노드 중앙값 `convergence.min_nodes_per_cell`(기본 64) 미만이면 경고 + 보고서 표시(16 미만이면 "판정 신뢰 낮음"). 옵션 `convergence.coarsen: false|half`(기본 false, 12×7 이하 격자에서는 무시).
- `rep_same` 완화: 버전별 medoid를 헝가리안 매칭한 뒤, 짝 medoid 간 cos ≥ cos_min이면 같은 대표로 본다(medoid ID 동일 요구 폐기).
- 버전 자연 정렬 동률(v100·v0100)은 원문 사전순으로 결정적 처리.
- 자동 축소 후 subcase 수는 max_cases를 넘지 않는다(대표 수 자동 조정 + 경고).
