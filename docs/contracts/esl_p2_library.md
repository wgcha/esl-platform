# 계약 초안: P2 — ESL 라이브러리 · 종합분석 · 비드 최적화 덱 · 보고서

- 상태: **초안** (2026-10-19). §0 확인 질문 답변 후 확정. 확정 전 구현 위임 금지.
- 목표: 모델(인치 파생)·낙하씬별 ESL을 DB에 쌓고, 설계 대상 모델 메시로 매핑·종합해 **강건 비드 설계용 OptiStruct topography(DTPG) 덱**과 근거 **보고서(PPTX/PDF)**를 만든다.
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
- PPTX(python-pptx, 고정 레시피) + PDF(서버 LibreOffice 변환, 설정 경로). 다운로드는 브라우저.
- Case 보고서(6장, 기존 P2 계획) + 종합분석 보고서: 표지, 대상·필터, 씬 표(메타·verdict), 포락 맵(정규화 격자 히트맵 + 대상 형상 위), 대표 케이스(모드 에너지, 선택 씬, 하중 그림), 비드 최적화 설정 요약, 한계(선형 ESL·소성·매핑 근사).

## 6. 리스크
- R-P2-1 인치 간 정규화 좌표 매핑은 기하 비례 가정 — 마운트·보스 위치가 비례하지 않으면 국부 하중 위치 오차. 대응: 대상 모델 자체 씬 우선, 이후 랜드마크(마운트 노드) 매핑 옵션.
- R-P2-2 CUMULATIVE 시나리오의 누적 소성 — 선형 ESL 오차 증가. verdict·hotspot 오차로 필터.
- R-P2-3 DTPG minmax 문법·버전 — 2026.1 매뉴얼 기준 확인 필요(덱은 골든 시험 + 사용자 실행 확인).
