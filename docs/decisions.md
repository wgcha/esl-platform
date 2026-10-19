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
