# 결정 기록

## 2026-10-19
- ESL은 physicsai와 별도 repo·별도 플랫폼으로 만들고, 같은 스택(Python 3.12, FastAPI, SQLAlchemy Core+PG, Alembic, DB 큐 워커, React+Vite+TS)을 쓴다.
- 인증은 대시보드 세션쿠키(analysis_canvas_session) introspection, 진입은 대시보드 링크의 하위 경로 `/esl/`(API `/esl/api`).
- 입력은 Radioss starter `_0000.rad` + 결과 h3d, 서버 측 공유경로(`storage.input_roots`) 선택만 허용하고 업로드 엔드포인트는 만들지 않는다.
- 대상 파트 기본값은 /PART title "chassis rear"(설정·Case별 변경 가능, 대소문자 무시 정확 일치).
- h3d 처리는 HyperView 배치(`hw -b -tcl`, TCL 경로는 설정)로 하며, Radioss·OptiStruct h3d에 같은 TCL·같은 불변량을 쓴다.
- 지표는 요소 von Mises 등가 총변형률(소성 유무 무관), 쉘은 층별 최대값이 기본.
- 중간 배열은 npz(allow_pickle=False, 숫자 dtype만) + JSON 메타, pickle 금지. 불가 시 .npy/CSV로 같은 키 계약 유지.
- t* = 시간×요소 max ε_eq의 시점, 상위 N 후보 시점과 거리 필터 hotspot을 함께 제시하고 사용자가 후보 중에서 확정한다.
- 강체 제거는 BC 노드 기준 Kabsch(반사 금지) → u_rel = Rᵀ(x−t)−X0, BC 잔차를 품질지표(경고·실패 임계는 설정)로 쓴다.
- BC 옵션 단계: A 4꼭지점(면내 PCA 극점 자동탐지 + 사용자 수정) P1, B 체결점 P2, C 스프링 P3.
- S4는 OptiStruct 선형정적, 전 노드 SPC1 + 비BC 노드 SPCD(u_rel) → SPCF: 비BC = F_eq, BC = 지지반력. 비선형 정적은 P3.
- S5는 F_eq(FORCE)+BC 고정 재해석으로 변위 RMS(수치 일관성)와 hotspot ε_eq 오차(물리 등가성)를 설정 기준으로 판정한다.
- S6 하중 축약(패치 합력·모멘트)은 P3.
- 출력은 Radioss /CLOAD·/BCS inc(ID 오프셋 설정), OptiStruct .fem, CSV. 요약 PPTX는 P2(미결 확인).
- 외부 실행은 워커에서만, argv 템플릿(argv[0]은 {hw}/{optistruct} 허용목록) + shell=False. 경로·실행파일·판정 기준은 설정 파일에서만 읽는다.
- 좌표는 Radioss 전역계, 단위 변환 없음, 힘 부호는 OptiStruct SPCF 그대로(구조물에 가해지는 외력).
- P1 요소 범위는 쉘(QUAD4/TRIA3) + 재료 LAW1/2/36 E·ν(미지원은 설정 override), 솔리드는 P2.
- (P1a) 계산은 클라우드(Linux, Altair 없음)에서 한다. h3d는 사용자가 Windows에서 HyperView TCL로 1회 CSV 변환해 입력으로 준다(근거: h3d 비공개 포맷, 클라우드에 Altair 없음).
- (P1a) S4·S5 선형정적은 자체 Python 쉘 솔버(QM6 막 + MITC4/DKT 굽힘)로 하고, OptiStruct .fem은 교차검증용 내보내기로만 만든다.
- (P1a) 대상 파트는 조립체에서 떼어 낸 자유물체로 본다: 전 노드 Kabsch로 강체 제거, 전 노드 F_eq(자기평형), 3-2-1 정정 구속(반력≈0). zero/residual 옵션은 폐기(근거: 사용자 확인 — BC점은 임의점, 실제 정적 고정 없음).
- (P1a) ε_eq는 TCL이 내보낸 면내 텐서로 Python이 계산: 비압축 von Mises (2/√3)·sqrt(exx²+eyy²+exx·eyy+exy²), layer 최대. 판정 기준 임시값 유지(사용자 확인 1번).
- (P1a) 플랫폼(API·DB·워커·UI)은 P1b로 미루고, 계산 코어 + CLI를 먼저 만든다.
- (P1a) 변위 정밀도 잡음은 감지만 한다(잡음 바닥 추정 → 경고·NOISE_FLOOR FAIL). 정규화 필터는 실제 h3d로 잡음 수준 측정 후 결정(근거: Verifier float32 정량화, 2 mm 변형에서 절점력 잡음 13배·hotspot 1.8%).
- (P1a-2, 2026-10-19) h3d에는 순간 총변형률이 없고 Max_Strain·Plastic Strain(요소별 max-hold, Mid layer)만 있다 → t* = 최종 최대값에 처음 도달한 프레임(first-reach). 기본 지표 Max_Strain, Plastic Strain 결과도 병기(근거: #1 probe, 사용자 지시).
- (P1a-2) TCL은 3패스(최종 프레임 전 요소 → 상위 요소 전 프레임 이력 → 후보 프레임만 전 노드 변위·전 요소 변형률)로 CSV 크기를 줄인다(근거: 22만 요소×126 프레임 전량 추출은 수 GB).
- (P1a-2) 22만 요소 대응으로 CHOLMOD(scikit-sparse) 백엔드를 추가한다(근거: SuperLU 10만 요소 7.3 GB, 클라우드 15 GB).
