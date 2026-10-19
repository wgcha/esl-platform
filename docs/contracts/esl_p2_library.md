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
