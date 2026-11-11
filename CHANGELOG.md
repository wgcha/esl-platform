# 업데이트 내역

사용자에게 보이는 변경만 적는다. 최신 버전이 위.

## [0.17.4] - 2026-11-11
### 수정
- **④ 면이 수천 개이고 구면(Sphere) 딤플이 있는 STEP 이 ③ 에서는 메시되는데 ④ 에서는 실패하거나 한 형상에 47~60 분 걸리던 문제**: ④ 의 OCC 작은 모서리·면 정리가 구면 극점의 퇴화 모서리를 지워 그 면을 메시할 수 없게 만든 것. 이제 CAD 메시가 면에서 실패하면 면별 재시도(면마다 STEP 을 다시 읽음) 전에 **모델 전체를 ③ 옵션(정리 끔·곡률 세분화·최소 0.2 h)으로 한 번** 다시 메시하고, 품질·원 형상 대비 편차가 기준 안이면 채택(`MESH_CAD_RELAXED` — 형상 행·경고에 단계별 초)
- CAD 메시 하위 프로세스가 제한 시간보다 먼저 스스로 끝나며 실패 면을 기록 — 시간 초과도 구면·periodic 면 실패로 판정되어 소용없는 세분화를 건너뜀(예전에는 기록 없이 끊겨 전역 세분화가 720 s 몫을 다 씀)
- 큰 형상(STEP 면 > 1000 또는 구면 면 있음): 면별 재시도 세션 수 상한(3)·CAD 시간 몫을 줄여 freeform·삼각형 폴백에 시간을 남김(`MESH_LARGE_MODEL`)
- (이슈 #63 현장 진단) ③ 옵션 재시도는 OCC 정리 끔 + **작은 구멍 메움 끔**(현장 STEP 이 이 조건에서 1 성분 120 s). 구멍 메움이 실패하며 형상을 끊으면 원 형상으로 되돌리고, 'OCC 정리 끔(전체)' 폴백은 구멍 메움 없이. 연결 끊김 안내가 실제 원인(구멍 메움·OCC 정리·봉합)을 가리킴. 'OCC 정리 끔(그 면만)' 이 정리 때문에 커진 면(작은 구 조각 → 완전한 구)도 찾음
- **비교 형상이 모두 메시 실패하면 준비 실패**(`COMPARE_NO_SHAPES` — 예전에는 비교 대상 1/2 로 준비 완료), 일부만 실패면 경고 맨 앞 `COMPARE_SHAPES_FAILED`(실패 형상 목록). 설정 `bead_doe.compare.min_ready_shapes`(1, 0 = 안 막음)
- 메시 준비 로그: 사다리 단계마다 한 줄, 하위 프로세스 대기 중 60 초마다 진행 줄(마지막 폴백 단계). 시도 폴더를 지워도 로그·실패 기록은 `mesh/attempt_logs/` 에 남음
- freeform 재메시 삼각화 각 편차 5° → 20°(`compare.freeform.angular_deflection_deg`): 곡면이 많은 STEP 에서 삼각형 폭증으로 느리거나 메모리 초과되던 것(합성 105 면 70.5 s → 16.7 s, 편차 0.550 → 0.389 mm)
- 비드 네트워크 분류 요소 상한 `bead_doe.select.graph.limits.max_elems` 250,000 → 600,000(현장 ① 메시 267,470 요소가 TOO_LARGE 로 건너뛰어지던 것 — 분류 16 s·396 MB 실측)
- 설정 `bead_doe.compare.mesh.cad_relaxed`·`large_faces`·`large`·`child_margin_s`·`heartbeat_s`, `compare.min_ready_shapes`, `compare.freeform.*_deflection_*`. CAD 가 성공하는 형상은 결과 바이트 그대로. DB migration 없음

## [0.17.1] - 2026-11-11
### 수정
- **강성 평가 입력·준비 화면의 긴 주황 경고 접기**: ③ 다른 모델(STEP만) 메싱 뒤 등 준비 경고(`[단계별: …]` 사다리 문구, `MESH_FREEFORM`·`MESH_TRIA_FALLBACK`, `AUTO_*`·`BG_*`)·입력 검사 경고·자동 탐지 경고·변수 표 고정 경고를 요약 1줄 "⚠ 경고 N건 · 정보 M건 · 가장 중요한 항목 — 자세히"로. 누르면 목록(항목마다 접기, 긴 글은 높이 고정 스크롤 상자). 펼침 상태는 스터디마다 이 탭에서 기억
- 막는 실패(준비·미리보기 작업 실패, 변수 없음, ④ 형상 메시 실패 칸)는 빨간 1줄(짧은 제목) + [자세히] — 전체 문구·[로그 보기]는 펼쳐서

## [0.17.0] - 2026-11-10
### 추가
- **비드 네트워크 자동 분류(메시 분류기)**: ①② 비드 직접 선택의 새 스터디는 준비 때 메시에서 바닥·벽·고리 변·다리·채널·포켓·플래토·접합 구역·섬·랜스·구멍을 나눈다(STEP 불필요). 자동 탐지 초기 선택 = 이 분류 결과(고리 4변·다리·채널 각각 비드, 접합 구역은 변수 없음), paicad 인식은 참고 힌트만 — STEP 없이도 ① 자동 가능
- **세그먼트 모핑**: 깊이 D 는 부모 바닥 대비 상대값(자식 바닥은 강체로 따라감), 사면 45°·입구 폭 고정, 접합부는 매끄러운 램프, 바뀐 세그먼트 밖이 움직이면 그 안은 실패(`BG_OUTSIDE_MOVED`), 좁은 바닥 코너는 사면만 가파르게(ⓘ `BG_CORNER_GUARD`), 벽에 걸친 보스는 채널을 따라감(체결 노드만 제자리)
- 선택 화면 **목록 | 트리** 토글: 바닥 위계 아래 세그먼트(종류·변·D·W)·접합 구역·섬, 행 클릭 = 3D 강조, 체크로 비드에 더하기/빼기, 우클릭 섬 ↔ 비드·인접 병합·네트워크 전체 묶기, 대칭 묶기 제안. 3D 는 세그먼트별 색
- 분류가 실패하면(시간·요소 수 상한 등) 준비는 끝나고 "자동 분류 실패 — 직접 칠하기(요소 비드)로 계속" 띠(`GRAPH_FAILED`)
- 공통 패키지 `beadgraph` 1.0.0(physicsai-platform 과 같이 씀) — 설치 스크립트가 저장소/묶음에서 함께 설치
### 변경
- 그래프 비드의 W 기본 범위 끝에서 요소가 뒤집히면 뒤집힘 없는 범위로 줄임(ⓘ `BG_RANGE_CLAMPED`). 기존(v0.16.x) 스터디는 결과·범위·해시 그대로
- 설정 `bead_doe.select.graph.*`(분류·모핑, 기본값이면 해시 제외). DB migration 없음
### 수정(검증)
- 세그먼트 밖 이동 점검을 분류 라벨 기준으로(공유 자식 벽 경계 노드가 움직이던 것 — 고리 왼쪽·오른쪽 변), 그래프 비드와 칠하기 비드를 함께 바꾼 안이 잘못 실패하던 것, 3D [분할] 클릭 좌표가 어긋나던 것
- W 기본 범위 줄임을 준비 직후부터 적용(첫 행렬부터 뒤집히는 W 안 없음), 시연 모드 저장소 설치에서 beadgraph 설치 실패, `beadgraph` API 오류 형식 `BeadgraphError(code, detail)`
- 새 스터디 제목 칸 폭, 분류 실패 문구가 두 번 보이던 것

## [0.16.3] - 2026-11-10
### 수정
- **④ 특정 CAD 면에서 메시가 실패하는 형상(이슈 #53: 면 2824 Sphere, "Impossible to mesh periodic surface")**: 요소를 잘게 해도 풀리지 않는 면 실패면 세분화를 건너뛰고(`MESH_FACE_FAIL`) 곧바로 **freeform 재메시**(OCC 삼각화 → 면 분류 → 4각 우세 재메시, CAD 면 경계를 따르지 않음 — `MESH_FREEFORM` 에 원 형상 대비 최대 편차·작은 구멍 수) → 그래도 실패하면 **OCC 삼각형 폴백**(BRepMesh 삼각화를 크기만 맞춰 삼각형 쉘로 — `MESH_TRIA_FALLBACK`). freeform 이 충실도로만 실패하면 그 사이에 실패 면만 평탄화하는 형상 단순화를 시도. 기본 사다리 `CAD → 국부 세분화 → 전역 세분화 → freeform → 형상 단순화 → 삼각형 폴백`
- **사다리 시간 배분**: 단계마다 형상 예산(3600 s)의 몫(`compare.refine.stage_share`)을 두어 앞 단계가 뒤 단계 몫을 먹지 못함(v0.16.2 는 세분화가 예산을 다 써 마지막 재메시가 남은 596 s 에서 끊김). 실패 문구 맨 앞·형상 행에 단계별 결과와 초(`[단계별: cad 실패 412.3 s → refine_local 건너뜀(면 실패 …) → …]`)
- 면이 수천 개인 STEP 의 가져오기 시간: ④ 는 STEP 이름표(라벨)를 읽지 않음(`compare.mesh.occ_import_labels: 0` — 합성 1915 면 234 s → 5 s). 메시 결과는 같음
### 추가
- 메시 방식 **freeform**(`compare.mesh.mode: freeform`, 화면 고급 설정): CAD 메시를 생략하고 모든 STEP 을 freeform 재메시(실패하면 삼각형 폴백)
- 설정 `compare.mesh.face_fail`·`compare.freeform`·`compare.tria`·`compare.refine.stage_share`·`min_attempt_s`. CAD 메시가 성공하는 형상은 결과 그대로

## [0.16.2] - 2026-11-08
### 추가
- **비드 자동 탐지 → 직접 선택 초기 선택**: ①② 스터디 아래 하위 라디오 "자동 탐지 / 직접 선택". 자동 탐지는 STEP 에서 비드를 찾아 선택 화면에 미리 채움(배지 "자동 탐지 결과 — 수정 후 저장", 되돌리기·초기화 = 자동 탐지 결과). 탐지가 실패해도 준비는 끝나고 빈 선택에서 직접 고름(`AUTO_DETECT_FAILED`)
- **② 다른 모델(B 메시)도 비드 직접 선택**: B rad/inc + 파트 + 인치 입력 그대로, 하중 = 셀 매핑·지지 = 자동 3-2-1(기존 ② 와 같음), 모핑 고정 = B 자신의 체결 스캔, 경계 경고 수 표시. 기존 ①·② 스터디는 그대로 실행·복제
### 변경
- 큰 구멍(등가 지름 > 20 mm, `select.hole.bridge_max_mm`)은 경계 고리를 건너 잇지 않음(`SELECT_BRIDGE_SKIPPED`), 극단 요소가 있는 안은 순위표 ⚠(`MORPH_EXTREME_ELEMENTS`)
- 스터디 목록에서 ② B 메시 기준 직접 선택 스터디를 "② 다른 모델(B 메시)"로 표시

## [0.16.1] - 2026-11-05
### 변경
- **비드 직접 선택: 고정 침범·품질 FAIL 은 경고만**(빼지 않고 실행): 미리보기 칸 ⚠ 배지 + "고정 노드 n개, 최대 x mm 이동"·"새 Fail m (r %)", 순위표 ⚠ 열, 1위가 경고 안이면 "경고 없는 최상위: d0xx", 보고서 절 "체결 위치 어긋남", 받기 rad/include 사본 첫 `/NODE` 앞·`ch_r.rad` 머리에 `#ESL WARNING FIXED_MOVED` 주석. 요소가 뒤집힌 안만 계속 제외. 되돌리기 `bead_doe.select.fixed_policy`·`select.quality.fail_policy: skip`. 예전 미리보기는 "판정 규칙이 바뀌었습니다" 띠
- 비드 직접 선택 범위 경고 경계(feasible) 확대(깊이 ×2.0·폭 ×1.6 — 기본 범위 ±30 %/±20 % 는 그대로), 비드 안 고정 노드가 있어도 변수 기본 해제 안 함
- 비드 직접 선택 W 기본 범위가 공칭을 포함하도록 고침(보스·구멍 근처 국부 폭 오탐으로 하한 > 상한이 되던 문제, `SELECT_W_RANGE_RESET`), 미리보기 준비 때 기본 범위 끝에서 요소가 뒤집히면 쓸 수 있는 범위를 알림(`SELECT_RANGE_INVERTS`)
- 비드 직접 선택 미리보기 썸네일을 항상 판 위쪽에서 같은 방향(오른쪽 = 판 x, 위 = 판 y 쪽)으로 그림 — 오목 비드에서 상하·좌우가 뒤집혀 보이던 문제
- ④ 재메시·형상 단순화 바깥 충실도 경고 기준 = max(0.3 mm, 2 × 같은 크기 CAD 메시가 곡면에서 갖는 처짐)(`compare.remesh.fidelity.warn_rel_cad`, 0 = 이전 절대 기준) — 필렛·구면 딤플마다 `REMESH_FIDELITY_WARN` 이 뜨던 문제. 실패 기준 1.5 mm 는 그대로
### 추가
- **비드 바닥 안 형상 처리**: 딤플·버링(바닥에 둘러싸인 ≤ 40 mm 영역) = **섬** — 클릭 확장 때 자동 포함·밝은 색 표시, D·W 를 바꾸면 바닥과 함께 평행 이동(찢어지지 않음). 관통 구멍은 열린 경계로 보지 않아 폭 W 변수가 켜짐. 비드 목록 "섬 n · 구멍 m", 섬 끄기 = 제외 층. 고리형 비드 안쪽 둔덕은 섬이 아닌 경계(`select.island.ring_frac`, 안내 ⓘ). 이어진 비드(T·L 교차)는 교차부 사면을 가까운 바닥 비드로 나누고 ⚠ `SELECT_BEAD_NETWORK`, 경계에 걸친 보스는 사면을 판 높이까지만(ⓘ `SELECT_SLOPE_ABOVE_PLATE`)
- **체결 구멍 둘레 고정**(비드 행 체크): 고정 노드 3 mm 링 제자리 + 8 mm 블렌딩 = 보스처럼 남김(`select.hold.*`)
- **④ 형상 단순화(작은 형상 억제)** 단계: 자동 사다리 `CAD → 국부 세분화 → 전역 세분화 → 형상 단순화 → 재메시`. CAD·세분화가 실패한 형상만 원 STEP 에서 작은 구멍(등가 지름 ≤ 8)·슬롯(1.9×14)·낮은 버링(≤ 1.5)·낮은 딤플/비드(< 2)·작은 필렛(≤ 1.5)·좁은 띠(< 0.4 h)를 억제(BatchMesher 기준). 메시 방식 '형상 단순화'·억제 목록(형상 행 펼침, `GET …/shapes/{did}/defeature`)·억제 영역 편차·경고 `MESH_DEFEATURED`·보고서 절 "작은 형상 억제". 설정 `compare.mesh.ladder`·`compare.defeature.*`. CAD 메시가 성공하는 형상과 v0.16.0 스터디는 결과 그대로
- ④ 메시 파일 형상의 입력 진단(작은 구멍·섬 수, 보고만)
- 작은 형상 인식 공통 모듈(`esl/geom/defeature.py`·`esl/mesh/features.py`) — ③·④·비드 직접 선택이 같은 기준을 씀. DB migration 없음
### 수정
- **비드 직접 선택: 복잡한 비드(교차·다단·밀집) 처리**: 교차 비드가 바닥을 둘로 가르거나 구멍이 바닥 가장자리를 끊어도 딤플·보스가 섬으로 들어감, 비드 벽을 가로지르는 슬롯이 있어도 폭(W) 변수를 씀, 교차 비드 하나만 골라도 깊이 공칭이 맞음(못 정하면 "교차하는 비드를 함께 선택" 오류)
- 바닥이 움직이는데 섬으로 보지 못한 보스·루버가 제자리에 남는 안은 '형상 찢어짐'으로 제외(`SELECT_FEATURE_DISTORTED`), 한 비드의 폭 변화가 다른 선택 비드를 움직이면 안에 ⚠(`select.cross_bead_policy` warn | skip)
- 변수를 함께 바꾸면 뒤집히는 조합 경고(함께 쓸 수 있는 범위 표시), 다단·이웃 비드 폭 범위 경고, 넓이 비 < 0.2·법선 회전 > 45° 요소가 있는 안에 품질 ⚠
- ④ 형상 단순화 억제 목록에 실제로 바뀌지 않는 높이 0 형상이 적히던 문제, 받기 rad 경고 주석 줄을 100자 이하로, 상단 바 버전 칩 = 배포 판(VERSION)

## [0.16.0] - 2026-11-04
### 추가
- **④ 형상 직접 비교: 메시 옵션** — 복잡한 Ch/R 중립면 STEP 의 메시 실패를 줄인다
  - **메시 파일로 올리기**: 형상 표 행마다 [STEP | 메시] 토글. Radioss `.rad`/`.inc`(주 + include, 업로드 폴더 안만)를 올리고 파트 ID 를 고르면 gmsh 없이 그 메시를 그대로 쓴다(단위 mm, 크기 차이·조각난 메시는 경고 `MESH_INPUT_SIZE_DIFF`·`MESH_INPUT_DISCONNECTED`). STEP 과 한 비교에 섞을 수 있고 방식이 섞이면 `COMPARE_MESH_METHOD_MIXED`. gmsh 가 없는 서버도 메시 형상만으로 비교 가능
  - **자동 폴백**(기본 메시 방식 '자동'): CAD 메시가 실패한 형상만 국부 세분화(실패 면 + 이웃, ×0.75 → 0.5 → 0.33) → 전역 세분화(2.4 → 2.0 mm) → 삼각형 재메시(OCC 삼각화 → 면 분류 → quad 우선 3 mm) 순으로 시도. 요소 수·메모리·시간 상한을 미리 예측해 넘는 시도는 건너뜀(`REFINE_SKIPPED_LIMIT`). CAD 메시가 성공한 형상은 지금과 메시가 같다
  - 세분화 형상은 경고 `MESH_REFINED`(요소 크기 차이로 메시 의존 오차) + **수렴 점검**: 기준 형상을 같은 크기로 다시 풀어 ESL별 편향 δ 를 표시, 허용치를 넘으면 `MESH_REFINE_BIAS`(Case·메시 기준이면 생략)
  - 재메시 형상은 원 형상 대비 최대 편차·면적비(경고 `REMESH_FIDELITY_WARN` 0.3 mm, 실패 1.5 mm), CAD 실패 후 재메시면 `REMESH_USED`
  - 고급 설정 '메시 방식'(자동 | CAD | 재메시)·'실패 시 세분화 허용'. 준비·결과 형상 표와 순위표에 '메시 방식' 열(툴팁: 시도 목록·건너뛴 사유·δ·편차), 보고서에 메시 방식 상세·수렴 점검 표·한계, ranking.csv 끝 열 `source`·`mesh_method`·`hausdorff_mm`·`refine_h_mm`·`elem_ratio_ref`
  - 설정 `bead_doe.compare.mesh.mode`·`ladder`, `compare.remesh.*`(곡선 분할각 기본 60° — 판 모서리 깎임 0.13 mm), `compare.mesh_input.*`, `compare.refine.*`. 워커 점검 기록에 `gmsh.remesh`(재메시 지원 여부). DB migration 없음
  - 자동 폴백이 모두 실패하면 형상 표·작업 실패 메시지에 원래 CAD 오류를 함께 표시("CAD 메시 실패: … → 세분화·재메시도 실패: …"). 형상 1개 폴백 전체가 `compare.refine.total_timeout_s` 안에 끝남(시도마다 남은 시간으로 제한). 경고 '메시 방식 섞임'은 세분화·재메시·메시 입력이 섞일 때만(기준이 Case 메시뿐이면 기존 경고만). 시도 폴더는 실패 시 마지막 것만 남김(`compare.mesh.keep_tries`)
- 알려진 한계: 필렛이 접선으로 이어진 비드는 재메시 면 분류가 실패할 수 있음(`REMESH_CLASSIFY_FAILED`) — 자동 폴백은 세분화를 먼저 시도하므로 영향이 줄어들고, 남으면 메시 파일로 올린다

## [0.15.1] - 2026-11-04
### 수정
- **비드 직접 선택: [선택 저장] 해도 변수 표가 안 뜨던 문제**: 처음 저장할 때 화면이 저장 전 조회 결과(선택 없음)를 '기준 메시가 바뀌어 저장 선택을 쓸 수 없음'으로 잘못 판정해 변수 표·평면도를 숨겼다. 저장 직후 바로 변수 표(`B1_D1`·`B1_W`…)가 열린다. 저장 전에는 변수 표 자리에 다음 단계 안내, 변수가 0개면(폭 측정 불가 등) 그 사유를 보인다
- **미리보기가 실패하면 아무 표시 없이 '미리보기를 실행하면…' 으로 돌아가던 문제**: 최신 작업이 실패·취소·중단이면 화면 위에 배너(작업·단계명·사유 코드·사용자 문구·[로그 보기] — 단계 로그 끝부분)를 계속 보인다. 미리보기 칸에도 실패 안내, 진행 중에는 "단계 k/N · 이름", OK 안이 0개면 사유별 개수(고정 침범·품질 실패·뒤집힘), 썸네일만 없으면 칸마다 '그림 없음'
- **오류 표시가 금방 사라지던 문제**: 작업이 끝나 화면 갱신 주기가 바뀔 때 화면 전체를 한 번 비웠다 다시 그려 오류 줄·열어 둔 로그가 지워졌다. 이제 동작 오류는 [✕]로 닫거나 같은 동작을 다시 할 때만 지워진다
- **Windows 서버에서 준비 중 `PermissionError [WinError 32]`(다른 프로세스가 파일을 사용 중)로 작업이 INTERNAL_ERROR 로 실패**(이슈 #53): 파일 교체가 백신·검색 인덱서·탐색기 미리보기의 잠깐 잠금에 걸리면 잠시 기다렸다 다시 시도하고, 끝내 안 되면 파일 이름을 담은 `FILE_LOCKED` 로 알림(서버 절대 경로는 서버 로그에만). 설정 `worker.fs_retry {attempts, max_wait_s, base_s}`(선택, 기본 8회·10 s)
- **④ 형상 비교: 구면(Sphere) 면이 있는 STEP 의 메시 실패 수정**(이슈 #53 `Impossible to mesh periodic surface`, 중립면 딤플·세 필렛 코너): 실패한 면만 형상 폴백 — OCC 정리 끔(그 면만 정리 없이 다시 가져와 대체 → 안 되면 전체 정리 끔, 다른 면이 새로 실패하면 쓰지 않음) → 면 분할(bbox 중심 평면) → 채움 면 대체(경계 고리 BSpline, 원 면 대비 편차 ≤ 0.5 × 요소 크기일 때만) → 작은 면(< 50.27 mm²) 평면 채움. 순서·on/off 는 설정 `bead_doe.compare.mesh.fallback.order`·`periodic_types`·`periodic_order`·`nofix`·`split`·`fill`·`small`, 쓰인 단계와 편차는 경고 `MESH_FACE_FALLBACK`·`mesh.json mesh_fallback`·보고서 형상 표에 표시. 정상 STEP 과 ③ 의 메시는 그대로
### 추가
- **3D 시점 툴바**(비드 선택 3D · 안 3D 보기 · 3D 하중 보기 공통, 3D 칸 오른쪽 위): 정면 X·Y·Z(같은 축을 다시 누르면 반대 방향), 등각, 꽉 차게 보기(지금 방향 그대로 화면비에 맞춤), 선택 영역에 맞추기(비드 선택 · 안 3D). 단축키(3D 칸 초점): 1 = −Y · 3 = +X · 7 = +Z(다시 = 반대), 0 = 등각, F = 꽉 차게. 직교·원근 모두. 하중 보기의 [맞춤] 버튼은 툴바로 옮김
- **지우기**: [지우개] 토글(켜면 클릭·끌기가 빼기 — Alt 와 같음), [층 비우기](지금 단 바닥·사면·고정·제외 층, 확인 후), 비드 목록 행마다 [✕] 비드 삭제(확인 후, 뒤 비드 번호·기본 이름 당김, 묶음·블렌딩 함께), 마지막 단 [단 k 삭제], [이 비드 초기화](요소만 비움·이름 유지), [전체 초기화](비드·고정·제외 모두, 확인 후). 모두 실행 취소(Ctrl+Z) 가능, 저장된 선택은 [선택 저장] 전까지 서버 그대로('저장 안 한 변경'). 저장 선택이 있으면 '선택 변경됨'·미리보기 무효
- **비드 편집**: 비드 목록 행을 누르면 그 비드가 활성(3D 에서 단·사면·경계 강조), 이름 바꾸기, 단·사면 행 [편집]으로 그 층 고르기(3D 더하기·빼기), [사면 다시 계산]. 저장된 선택도 편집 가능(바꾸면 '선택 변경됨'·미리보기 무효). 실행 뒤에는 편집·삭제·초기화 버튼이 꺼지고 툴팁 '복제해서 편집'
- **고정 침범 원인 표시**(비드 직접 선택 미리보기): OK 안이 0개면 사유별 개수와 함께 원인 변수 줄 — 예 "B1 W 를 바꾸면 고정 노드 37개가 최대 0.8 mm 움직임 → B1 W 해제 또는 블렌딩 반경 축소". 고정 침범 안을 3D 로 열면 움직인 고정 노드를 빨간 점으로 강조. 선택 저장 경고 `SELECT_FIXED_IN_BEAD`·`SELECT_FIXED_IN_BLEND` 를 변수 표 위에도 표시. 미리보기 셀(고정 침범 칸만)에 `fixed_viol{n, max_mm, bead_vars[{name, bead, n, max_mm}], node_idx}`(코어 `bd_select_grid` 기록 — 다른 칸·다른 시나리오 결과는 그대로). 침범 안을 스킵하는 정책은 그대로
- API: `GET /jobs/{id}/log?tail=true`(끝부분 — 완결된 줄부터, 기존 권한·경로·크기 상한·마스킹 그대로)

## [0.15.0] - 2026-11-04
### 추가
- **강성 평가 스터디 ① 비드 직접 선택(메시)**: ① 같은 모델에서 "비드 정의 ○ 자동 탐지(STEP) ● 직접 선택(메시)" 을 고르면 STEP 없이 낙하 Radioss 메시(Ch/R) 위에서 비드를 직접 골라 깊이·폭 DOE 를 한다. 형상 엔진(paicad)이 없어도 쓸 수 있다(있으면 체결 고정 노드만 fixed-scan 으로 가져옴, 없으면 경고 `FIXED_INFO_MISSING` + "고정" 층을 직접 칠함). 기본값은 지금처럼 자동 탐지
- 3D 선택 카드: 클릭 + 같은 법선 자동 확장(feature angle 기본 15°)·브러시·사각·올가미, 보이는 면만, Shift 더하기·Alt 빼기, 실행 취소. 층 = 단 k 바닥·사면·고정·제외. 다단 비드 [+ 단], 단 묶기
- [사면·경계 자동]: 서버가 사면 요소·경계선·공칭 깊이 D_k·폭 W(최소~최대)·블렌딩 반경을 계산하고 경고(빠진 단·새는 사면·열린 경계·고정 겹침·폭 측정 불가 등)를 낸다. [경계 +1줄]/[−1줄]로 사면 수정. [선택 저장] 시 서버가 다시 계산해 저장(rev)
- 변수: 단별 깊이 `B1_D1`… (깊어짐 +)·비드별 폭 `B1_W`(양쪽 ΔW/2, 바닥도 같이 넓어짐 — 사면 각 유지). 경계 밖은 블렌딩 반경 안에서 매끈하게 감쇠(자동 반경은 체결 고정 노드 앞에서 잘림). 평면도에 라벨 칩·폭 최소/최대 점선·깊이 단면 미니 그림
- 미리보기: 서버(워커)가 안마다 모핑 → 고정 침범(`SKIPPED_FIXED`)·품질(이슈 #53 criteria 새 Fail 비율 > 1 %, 뒤집힘 → `FAILED_MESH`) 판정 → 3D 음영 + 깊이 변화 색(파랑 깊어짐·빨강 얕아짐, 모든 칸 같은 범위) 썸네일. 썸네일 클릭 → 안 3D 보기(공칭 ↔ 안, 크게 보기)
- 실행·결과·검증 낙하는 ① 과 같다. 받기 = `/NODE` 좌표만 바뀐 include 사본 + `ch_r.rad`·`ch_r.fem` + `values.json`·`selection.json`(BREP/STEP 없음)
- API: `scenario: "select"`, `GET …/select/view/{part.glb|select.bin|select_manifest.json}`, `POST …/select/derive`, `GET|PUT …/selection`, `GET …/select/basis[?meta=1]`. 설정 `bead_doe.select.*`. DB migration 0015(`bead_does.selection`, 시나리오 CHECK 에 `select`)

## [0.14.1] - 2026-11-04
### 수정
- **④ 형상 비교: 보스·버링·관(원통·원뿔 periodic 면)이 있는 STEP 의 메시 실패**(이슈 #53 `Impossible to mesh periodic surface`): 작은 구멍 메움·구멍 둘레 분할이 periodic 면의 양 끝 원(gmsh 경계 조회가 이음선을 지워 따로 떨어진 고리로 보임)과 판의 보스 이음 원(이웃 벽과 공유하는 모서리)까지 구멍으로 보고 메우던 문제 — 이제 구멍 = 자유 모서리로만 된 고리이면서 이음선 끝점을 지나지 않는 고리. 판·구멍·비드뿐인 STEP 과 ③ 의 메시는 바이트 그대로
- 면 단위 폴백(설정 `bead_doe.compare.mesh.fallback`, 기본 켬): 2D 메싱이 실패한 **면만** 다른 2D 알고리즘(기본 6 Frontal-Delaunay → 5 Delaunay → 1 MeshAdapt)으로, 그래도 실패하면 그 면의 작은 형상 처리·구멍 둘레 분할을 풀고 다시 메시. 폴백이 쓰인 면 수·면 id 는 경고 `MESH_FACE_FALLBACK`(준비 결과·보고서), 형상 품질 요약 `quality.fallback_faces`·`fallback_face_ids`, 형상 `mesh.json` 의 `mesh_fallback`
- 끝내 메시가 안 되면 실패 문구에 면 id·면 종류·위치(bbox 중심 mm)와 시도한 알고리즘을 표시

## [0.14.0] - 2026-11-04
### 추가
- **강성 평가 스터디 ④ 형상 직접 비교**: STEP 여러 개(최대 20, 한 업로드에 여러 파일 가능)에 이름을 붙여 올리고 하나를 기준으로 지정 → 라이브러리 ESL(여러 씬)로 형상마다 선형 해석해 기준 대비 컴플라이언스·개선율·ESL별 개선율·Pareto·3D 비교. 비드 인식·DOE·미리보기·paicad 없이 **gmsh 만**으로 동작(paicad 가 없어도 ④ 는 켜짐)
- 흐름 [입력 준비] → [비교 실행]: 준비에서 모든 형상을 같은 gmsh 설정(요소 3 mm·곡률 세분화 끔·최소 2.4 mm, 이슈 #53 Radioss Ch/R 3 mm 낙하 메시 기준 근사)으로 병렬 메시하고 크기(±5 %)·정렬(기준 frame 원점 0.05·법선 5°) 검사 — 어긋난 형상만 `FAILED_SIZE`, 메시 실패 형상만 `FAILED_MESH`(나머지 진행). 형상마다 요소 수·4각 비율·품질 요약(이슈 #53 criteria 표: Fail·Warn 요소 수·비율 — Fail 비율 1 % 초과 시 경고 `SHAPE_QUALITY_FAIL`, 차단 안 함). 준비 결과 화면 형상 표에 Fail 비율·tria 비율 열과 "상한 초과" 배지, 표 위 품질 요약 한 줄
- 작은 형상 처리: 면적 < π·4² mm² 구멍(r<4 원형·좁은 슬롯) 메움, r 4~30 구멍 둘레 분할 = max(6, ceil(둘레/요소 크기)) — 큰 구멍도 둘레 요소가 요소 크기 이하(이슈 #53 holes table 근사). 높이 2 mm 미만 비드 억제는 기준만 기록(미적용)
- 하중 = 기준 형상 frame 을 고정한 셀 매핑, 지지 = 형상마다 같은 규칙 auto 3-2-1. 기준 STEP 을 지정하지 않으면 첫 ESL 의 Case 메시가 기준(경고 `COMPARE_REF_CASE_MESH` — 메싱 방식 차이가 섞임)
- 결과: 순위표 이름 열·민감도 숨김(`COMPARE_NO_PARAMS`), 형상별 메시 `ch_r.rad`·`ch_r.fem`(전 성공 형상), 순위 CSV(이름·파일 열), 보고서(형상 표·메시 프로필·한계)
- API: `scenario: "compare"` + `shapes[{upload_id, rel?, name, reference}]`(check-inputs·studies), `POST …/run` 은 `matrix_sha256` 없이, `matrix`·`preview`·`params`·`plan-view`·썸네일·비드 그림 = 409 `SCENARIO_UNSUPPORTED`, `GET /doe/settings` 의 `scenarios.compare`·`compare_reason`·`compare{enabled, reason, max_shapes, total_max_mb, mesh_size_mm}`, check-inputs `shapes[{index, name, file_name, sha256, size_mb, reference}]`·`reference_source`·`base`, 준비 요약 `prep.{n_shapes, n_ready, failed, reference_source, mesh{size_mm, gmsh_version}, shapes[{…, status, n_elems, quad_ratio, quality}]}`, 결과 `scenario`·`reference_source`·`sensitivity_reason`·행 `shape{name, file_name}`·ESL별 지표 행 `name`. 화면은 한 번에 놓은 STEP 들을 업로드 세션 1개로 올리고 형상마다 `rel` 로 지정
- 설정 `bead_doe.compare.*`(enabled·max_shapes·total_max_mb·align_tol·align_deg·mesh·defeature·quality). 키가 없으면 기본값(③ 결과는 바이트 그대로)
- DB migration 0014: `bead_does.scenario` 길이 8·CHECK 에 `compare`
### 수정
- 자체 쉘 솔버 해 잔차 판정: 얇은 판·3점 지지·3 mm 메시처럼 조건수가 큰 정상 해가 `SOLVER_SINGULAR`(‖Ku−F‖/‖F‖ 1.1e-8 > 1e-8)로 실패하던 문제 — 직접법은 예전 기준(‖r‖/‖F‖ ≤ 1e-8) 또는 노름 후방 오차 ‖r‖/(‖K‖·‖u‖+‖F‖) ≤ 1e-9 면 수용(예전에 통과한 해는 그대로 — ①②③ 결과 불변). 해 통계에 `solve_backward_err` 추가

## [0.13.0] - 2026-11-04
### 추가
- **ESL 생성 일괄 실행**: 새 Case 의 '생성 후 일괄 실행' 또는 Case 화면 [일괄 실행]으로 ①입력 → ②t*·지지점 → ③ESL → ④검증을 이어서 실행. 끝난 단계는 건너뛰고(stale·실패·없음은 다시), 이미 실행 중인 같은 단계 작업은 기다림
- ② 자동 확정: 추천 t*(1순위)가 변위 추출 프레임 안이고 조정·지표 오류가 없으며 직접 고른 t* 와 같을 때만 체인이 확정(t* 에 "일괄 실행으로 확정" 기록, 지지점 3-2-1 자동). 아니면 ②에서 멈춤
- 멈춤·사유 표시: t* 확인 필요, 지지점 자동 선택 실패·오류, 앞 단계 필요, 작업 실패·중단, 검증 FAIL·판정 불가, Case 변경·보관 — 고친 뒤 [이어서 실행](새 시도로 기록). ④ PASS 로 끝나도 라이브러리 등록은 사람이 ④에서
- [일괄 취소](시작한 사람 또는 전역 관리자): 체인이 만든 대기·실행 중 작업도 취소(사람이 만든 작업은 그대로). 일괄 실행 중에는 그 Case 의 단계 실행·t* 확정·지지점 지정·파트 변경·보관·재시도가 409 `RUN_ALL_ACTIVE`(보고서·결과 받기·조회는 허용)
- API: `POST /cases/{id}/run-all {from?}`·`GET /cases/{id}/run-all`(최신, `?all=1` 기록 최대 50)·`POST /cases/{id}/run-all/cancel`, `POST /cases` 의 `run_all`, `CaseOut.run_all`·`run_all_error`, 작업·이력·작업 검토의 `run_all_id`('일괄' 배지)
- DB migration 0013: `run_alls`(시도 1회 = 1행, Case 당 실행 중 1개), `jobs.run_all_id`. 워커가 작업 종료와 같은 트랜잭션에서 다음 단계를 큐에 넣고, 끊김(작업은 끝났는데 체인이 그대로)은 리퍼 주기마다 복구

## [0.12.5] - 2026-11-04
### 수정
- **업로드한 파일 일부가 0 으로 채워진 채 완료되던 문제**(#50): Windows 서버에서 `.part` 사전 할당(0 채우기)과 다른 청크 쓰기가 겹쳐 먼저 쓴 청크가 덮이던 경합 — 파일별 잠금으로 직렬화하고 `upload.preallocate` 기본값을 `false` 로 바꿈(기존 설정 파일에 `preallocate: true` 가 적혀 있으면 `false` 로 고칠 것)
- 업로드 검증 강화: 서버가 청크마다 받은 본문 sha256 을 기록하고 쓴 직후 디스크와 대조(`CHUNK_VERIFY_FAILED` → 그 청크만 재시도), 마무리 때 전체 재해시로 청크별 대조(`UPLOAD_CHUNK_CORRUPT` → 그 청크만 자동 재전송, 같은 청크 3번째는 `UPLOAD_CORRUPT`). 브라우저·PC 업로드 도구 모두
- 이미 올라간 파일의 손상 탐지 명령 `esl_service.py upload-holes --runtime .`(읽기 전용, 청크 경계부터 0 구간·DB sha256 대조). **배포 직후 1회 실행** — 보고된 파일은 원본으로 다시 올림(관리자 매뉴얼 §3.0·§13)
- **Case 목록 진행 표시**(#49): 진행 칸에 ①~④ 단계 점(스텝퍼와 같은 색 규칙, 실패 단계는 툴팁에 사유)과 "라이브러리 등록됨 N"/"라이브러리 없음" 배지. `GET /cases` 가 `step_status`·`library` 를 함께 줌(Case 수와 무관한 묶음 조회)
### 추가
- **3D 뷰어 자유 회전**: 극점 제한 없이 상하·좌우로 계속 회전(TrackballControls), 팬은 커서를 따라감, 맞춤 보기에서 위쪽(+Z) 복원
- **보고서 화면 안 보기**: 종합분석·버전 비교 상세에서 보고서를 화면 안에 바로 표시(sandbox iframe — 보고서 스크립트는 앱 쿠키·API 에 접근 불가), [보고서 받기]·[새 탭에서 열기]. HTML 보고서 CSP 에 `frame-ancestors 'self'` 추가(같은 출처 화면에만 끼워 넣기)
- **종합분석 보고서 읽기 쉽게**: 씬 표의 항목(해시) 열을 행 툴팁으로 옮기고 합력·변형 모드 열을 앞으로, 절마다 쉬운 설명 상자(분석·버전 비교 보고서 공통)

## [0.12.4] - 2026-11-02
### 수정
- **paicad 0.14.1(tag 메모리 수정)**: 강성 평가 스터디 준비의 `paicad tag` 가 큰 모델(예 22만 노드 × 7천 CAD 꼭짓점)에서 노드×꼭짓점 거리 행렬을 통째로 만들어 메모리가 폭증하던 문제 — physicsai `release/v0.2.15`(be21319) paicad 0.14.1 로 교체(k-d tree·블록 처리, 메모리 O(노드+꼭짓점)). 동봉 wheel·`deploy/paicad.lock`·설정 기본값 `bead_doe.paicad.min_version`·`pinned_version` = 0.14.1

## [0.12.3] - 2026-11-02
### 수정
- **강성 평가 스터디 준비(DOE_PREP)가 시작 2~3분 뒤 `WORKER_LOST`("lease 를 잃었습니다")로 끝나던 문제**(#44): 큰 모델(예 22만 요소)의 모델 전체 사본 `prep/assem_full/`·스캔 정규화가 워커 안에서 lease 갱신 없이 `worker.lease_ttl_s` 보다 오래 걸렸음. 이제 별도 스레드에서 실행하고 그동안 lease 갱신·취소 확인을 계속함. 취소하면 다음 파일 쓰기 전에 멈춘 뒤 CANCELED
- 같은 방식으로 워커 안 긴 파일 작업 전부: 조립 폴더 검사(기준·A Case), A Case 모델 사본·파트 목록, include 스캔(Case 추출·최적화 준비·SCX 내려받기), 누적 씬 판정, ESL 스냅샷 복원, 산출물 sha256(등록 트랜잭션 밖에서 미리), history 보존 사본, OptiStruct 덱 sha256·사본, SCX 내려받기·검증 낙하 결과의 sha256 재확인, 모핑 사본 복원(취소 시 중단)
- 긴 파일 작업 중 DB 오류·lease 상실이 나도 파일 작업이 끝난 뒤에 실패 처리(그동안 같은 Case 의 다음 작업이 시작되지 않음). 대기 상한 설정 `worker.inproc_join_max_s`(선택, 기본 3600 s)
- 긴 파일 작업 중에도 워커 상태가 "응답 없음"으로 바뀌지 않음(워커 heartbeat 유지 확인)
- 작업 로그에 모델 사본 단계 시작·끝(경과 시간·파일 수)과 오래 걸릴 때 30초마다 진행 중 줄(경과·쓴 파일 수)

## [0.12.2] - 2026-11-02
### 수정
- **강성 평가 스터디 체결 스캔 정규화 대상 한정**(#45): 스캔 사본에서 체결 정의(`/INTER/TYPE2`·`/RBE2`·`/RBE3`·`/RBODY`·`/BCS`)가 직접·간접 참조하는 집합만 정규화하고, 참조되지 않는 집합 카드는 원문 그대로 둠(`/INIVEL`·`/GRAV` 등 의미 보존). `/GRNOD/GENE`·`GEN_INCR` 은 모델 `/NODE` 전체 id 와의 교집합으로 펼침(상한 5,000,000 은 교집합에 적용) — 넓은 범위 GENE(예 100001..999999999)에서 막히던 문제 해소
- **서버 h3d 추출 Strain 텐서 층 선택·값 없음 내성**(#46): `Strain` 텐서는 우선 층(기본 `Lower`·`Upper`, 대소문자·공백 무시) 중 있는 층만 내보내고, 하나도 없으면 전 층 − `tensor_layer_exclude`. 선택 근거는 추출 결과 `strain_layer_basis`. 값이 없는 (프레임, 층)(예 frame 0)은 0 이 아니라 건너뜀(경고 `STRAIN_DUMP_PARTIAL`), 한 프레임도 값 없는 요소는 0 으로 기록(`strain_fallback.no_value_elems`), 전부 없을 때만 `H3D_MISSING_RESULT`. HyperView 쿼리 오류는 그대로 실패
- 설정 `extract.tensor_layer_prefer`(선택, 기본 `[Lower, Upper]`, 빈 목록 = 전 층 − exclude) 추가 — 서버 추출 요청에 그대로 전달

## [0.12.1] - 2026-10-30
### 수정
- **서버 h3d 추출이 `Max_Strain` 없는 덱에서 막히던 문제**(`H3D_MISSING_RESULT: result type 'Max_Strain' not in subcase 1`): 변형률 결과를 순서대로 대체 — `Max_Strain` → `Plastic Strain` → `Strain`(층별 순간 텐서) → `Max_Stress`. 순서·결과/성분 이름 후보는 설정 `extract.strain_sources`·`result_names`·`tensor_comps`·`vm_comps`·`scalar_comps`·`tensor_layer_exclude`(선택, 없으면 기본값)
- `Strain` 텐서 대체: 추출이 전 프레임 × 층(예 Lower·Upper, Max·Min 제외) 원자료를 내고 코어가 프레임별 등가 변형률 → 층 최대 → 시간 누적 최대로 TMAX 를 재현(출력 프레임 표본이라 ε 과소평가·t* 양자화 가능 — 경고 `STRAIN_TMAX_SAMPLED`, 덱에 `/H3D/SHELL/TENS/STRAIN/TMAX` 권장). ESL 검증 해 ε 도 외피 층(bottom·top) 최대로 비교. 추출 시간·용량은 프레임 수에 비례해 늘어남
- Strain 텐서 원자료는 스트리밍으로 처리(메모리 요소 수에 비례, 22만 요소 × 200 프레임 × 2층 합성에서 피크 약 165 MiB), 변환 후 서버 추출 폴더에서 삭제(`extract.dump_keep: true` 면 보존), 크기 상한 `extract.dump_max_bytes`(기본 40 GiB)·디스크 여유를 추출 전에 추정해 넘으면 `STRAIN_DUMP_TOO_LARGE`·`INSUFFICIENT_STORAGE`. 입력 지문은 원자료 크기·수정 시각만
- 소성 변형률 결과가 없으면 실패 대신 0 + 경고 `H3D_NO_EPSP`(소성 영역 정보는 미상으로 표시). 대체 결과가 하나도 없으면 `H3D_NO_STRAIN_SOURCE`("h3d 에 변형률·응력 결과가 없음 — 덱 /H3D 출력 확인")
- 응력 대체(`Max_Stress`)는 순위·t* 만 응력으로 정하고 변형률 참고 지표(hotspot·전 요소 ε 비교·잡음 바닥 ε)는 생략 + 경고 `STRAIN_FROM_STRESS`. 판정(변위 주지표)은 그대로
- 어떤 결과를 썼는지(`strain_source`: max_strain | plastic_strain | strain_tensor | max_stress)를 추출 결과·ESL 요약·검증·라이브러리 품질·검증 낙하 비교(양쪽, 다르면 경고 `VD_STRAIN_SOURCE_MISMATCH`)에 기록. 대체일 때 Case 보고서 입력 표에 한 줄. 이전 자료는 max_strain 으로 봄
- request.txt 에 `strain_type`·`epsp_type` 을 직접 적은 수동 실행은 예전처럼 `Max_Strain` 만 봄(대체 없음)
- **강성 평가 스터디 체결 스캔이 모델 일부만 보던 문제**: paicad `--assem-dir` 에 기준 starter include 트리 전체(Case 폴더 밖 상위·형제 include 포함, 순환 방지) 사본 `prep/assem_full/`(②③ A Case = `prep/a_assem_full/`)을 넘김. 원본은 읽기만, 링크·허용 루트 밖은 `PATH_OUTSIDE_ROOT`, 엔진 rad 는 `bead_doe.same.engine_rad` 일 때만, 상한 `bead_doe.same.max_assem_mb`
- 체결 스캔 사본만 paicad 0.14.0 미지원 집합 카드 정규화(`bead_doe.fixed_scan`): `/SURF/PART/EXT|ALL` → `/SURF/PART`, `/SURF·GRNOD/SUBSET` → 파트 목록, `/GRNOD/GENE`(first·last 쌍)·`/GRNOD/GEN_INCR` → `/GRNOD/NODE`, 솔리드 포함 `/SURF` → `/SURF/SEG`(외곽 면 = 같은 /SURF 안 솔리드 파트 전체에서 맞닿은 면 제외·모든 면). Radioss 2024.1·2026.1 입력 형식 지원 — 설정 `bead_doe.fixed_scan.subset_format`(`auto`|`2024`|`2026`|`legacy`, 기본 `auto` = starter `/BEGIN`·머리 주석으로 판정, 매니페스트·로그에 기록). TETRA10·BRIC20 여러 줄 요소 카드 지원, include 깊이 초과는 `INCLUDE_TOO_DEEP`, `prep/assem_full`·`a_assem_full` 은 재생성 파생물(백업 없이 작업 폴더 안에서만 삭제). run 모핑 사본 중 재작성 파일은 원본 + 모핑 `/NODE` 로 복원(결과 파일은 예전과 같음). `FIXED_PARSE_FAILED` 안내에 읽은 파일 수·솔리드 면 tie 미지원 표시

## [0.12.0] - 2026-10-30
### 추가
- **Radioss 검증 낙하(서버)**: 강성 평가 스터디 ① 같은 모델·완료 결과에서 모핑 사본이 남은 안(순위 1~`paicad.keep_files_top`)을 골라 원 낙하 씬을 SCX 에서 다시 실행하고 원 낙하와 비교합니다. 씬 선택 = **가장 나쁜 씬 N개**(ESL별 개선 비 r 큰 순, 기본 `verify_drop.default_worst_n`) 또는 **고른 ESL 전부**, 한 번에 `verify_drop.max_scenes` 건까지. 제출 전 대화상자용 계획(`POST /verify-drops/plan` — 씬·제외 사유·제출 건수·예상 시간·고를 수 있는 안·Radioss 기본값)
- 씬마다 원 Case 입력(rad + include + 엔진 rad) 사본에 **노드 ID 기준으로 /NODE 좌표 줄만** 고쳐(바뀐 줄·바뀐 파일만, 원본 불변) SCX 드라이브 새 폴더 `<drive_base>/<프로젝트>/VD<번호>_<UTC>` 에 올리고 Radioss 제출 → 상태 폴링 → h3d·out 회수 → 서버 추출 → **비교 표**(최대 ε_eq·상위 요소 ε_eq·최대 상대 변위·t* 값, 원 낙하 대비 비, ESL 선형 예측 비, 개선/악화/비슷, 방향 일치) + CSV. PASS/FAIL 판정은 없습니다
- 제출 결과를 모를 때(대시보드 응답 없음)는 자동으로 다시 내지 않고 멈춤 — **[잡 ID 연결]**(SCX 화면의 잡 ID → 서버가 폴링부터 새 작업을 자동으로 큐, [재시도] 불필요) 또는 **[포기]**(뒤 [재시도]는 새 제출). 작업 취소는 실행 중인 SCX 잡을 한 번 종료 요청
- 제외(경고): 누적 씬(이전 런 상태 파일 .sta/.str), include 가 rad 폴더 밖·절대경로·`include_path_map`, 엔진 rad 없음, 원 Case 가 없거나 추출 없음(`VD_CASE_NOT_READY`), 같은 안·씬 진행 중. ②③ 스터디는 거부
- **검증 낙하 화면**: 스터디 받기 줄 **[검증 낙하]**(① 같은 모델·완료·모핑 사본이 남은 안만 — 아니면 비활성 사유) → 대화상자(안·씬 선택 '가장 나쁜 씬 N개 | 고른 ESL 전부'·씬 표·제외 사유·제출 건수·예상 시간·상한·고급 Radioss 버전/ncpu) → 카드(묶음별 씬 진행 칸 업로드·대기·실행·회수·비교, SCX 잡 ID, 드라이브 폴더 경로 복사, 취소 확인 창, 결과 모름 [잡 ID 연결]·[포기], 완료 비교 표·CSV)
- 설정 `verify_drop.*`(enabled·max_scenes·default_worst_n·max_running …)·드라이브 폴더 규칙은 관리자 매뉴얼 §2.7.3, 실기 체크리스트 `docs/manual/scx_check.md` §7
- 환경 점검 `scx_drive.enabled`(켜짐/꺼짐 · roots 개수)
- `hpc.scx.secret_file: ""` = **대시보드 비밀 파일 따라가기**: env `SIMDASH_SCX_RELAY_SECRET_FILE` → 새 키 `hpc.scx.dashboard_root` 의 `.env`·`backend/.env`(그 키 줄만) → `<런타임>/secrets/scx_relay_key` 순. 설치·업데이트가 대시보드 폴더(esl 설치 폴더의 형제)를 찾아 `dashboard_root` 를 채움, 환경 점검에 출처 표시(값 미출력)
- 검증 낙하 제출 폴더 분리: `hpc.scx.drive_base: "~"`(공유 홈 자체)이면 검증 낙하만 비활성 `VD_DRIVE_BASE_SHARED` + 설정 경고 — `"~/<전용 폴더>"`(권장 `~/esl`)
### 수정
- 환경 점검 `scx.relay`: `scx_drive`·`verify_drop` 이 둘 다 꺼져 릴레이를 시험하지 않았을 때 'VD_DISABLED' 경고 대신 **SKIP**("SCX 드라이브·검증 낙하 모두 꺼짐"). 하나라도 켜져 있으면 켜진 쪽의 실제 원인(`SCX_RELAY_UNREACHABLE` 등)을 표시(`*_DISABLED` 아님)
- `hpc:`(또는 `hpc.scx:`) 밑에 최상위 키(`scx_drive`·`verify_drop`·`worker` 등)를 들여쓰면 조용히 무시되던 것을 설정 검증(설치 콘솔·백엔드 로그)·환경 점검 `config.valid` 에서 경고 "hpc.scx_drive 는 최상위 키입니다 — 들여쓰기를 없애세요"(physicsai 공용 키는 계속 무시)
- SCX 드라이브 조회: SPDM 루트의 상위 폴더(예 `SharedWithMe` ⊃ `SharedWithMe/SPDM`)를 루트로 둔 목록이 '프로젝트 폴더가 SPDM 루트이거나 그 상위 폴더'로 거부되던 문제 — 읽기(목록·고르기·내려받기)의 SPDM 판정은 대시보드 relay 에 맡김(막히면 "대시보드가 SPDM 폴더 읽기를 막고 있습니다"), 검증 낙하 쓰기 폴더 규칙은 그대로
- 검증 낙하: 엔진 rad 가 링크이거나 rad 폴더 밖이면 그 씬 제외(업로드 직전 다시 확인), /NODE 줄의 ASCII 아닌 문자는 `VD_PATCH_ENCODING`, 결과 파일 이름 검사
- 대시보드 `.env` 가 UTF-8 이 아니면(cp949 도 아니면) 상태·환경 점검이 멈추지 않고 `SCX_SECRET_INVALID`(인코딩 오류)로, 루트 `.env` 값이 비면 `backend/.env` 를 계속 봄
- 경로 검사 오류(`/paths/inspect`·작업 생성·비드 최적화·강성 평가 입력 검사)에서 서버 절대경로를 일반 사용자에게 가림(전역 관리자는 원문)
- 단면 그래프: 첫 자료가 온 순간 기본 배율로 바로 그림(한 박자 뒤 배율이 바뀌며 방금 고친 축 입력이 덮어써지던 경우)
- `hpc.scx.secret_file` 상대경로는 설정 오류(절대경로만, SCX 기능만 비활성)
- SCX 내려받기 도중 연결이 끊기면 '해시 불일치' 대신 **전송 중단**(`SCX_TRANSFER_INTERRUPTED`, 자동 재시도)으로 표시
- 너무 큰 파일 안내가 실제로 막은 설정(`upload.max_file_bytes`·`hpc.scx.max_download_bytes`·대시보드 `SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES`)을 가리킴
- Case 생성의 'include 가 입력 루트 밖' 오류에서 서버 절대경로를 일반 사용자에게 가림(전역 관리자는 원문)
- e2e(`scripts/e2e_scx.mjs`)가 SCX 상태를 받은 뒤 탭을 확인

## [0.11.0] - 2026-10-30
### 추가
- **새 케이스 'SCX 드라이브에서 고르기'**(4번째 탭): 대시보드 SCX 릴레이를 거쳐 SCX 드라이브(관리자가 정한 공유 폴더 `scx_drive.roots` 안)에서 rad 와 h3d 를 고르면 서버가 직접 내려받아 업로드 세션을 만들고 기존 검사(파트·누락 include) 뒤 그대로 **Case 만들기**. include(상대·`../`·하위 폴더·상태 파일 .sta/.str)와 같은 폴더 엔진 rad(`<이름>_0001.rad` …)는 자동으로 함께 받습니다. 드라이브에 쓰지 않습니다
- 내려받기는 작업으로 진행(진행률 "h3d 12.3 / 30.0 GB", 첫 바이트 전 "대시보드가 SCX에서 받는 중"), [취소]·[재시도] — 재시도는 sha256 이 확인된 파일을 건너뜁니다(파일 단위 이어받기). 받은 파일은 sha256 대조, 끊기거나 해시가 다르면 자동으로 다시 받습니다
- 받지 못한 include(절대경로·공유 폴더 밖·드라이브에 없음·허용되지 않는 확장자)는 사유와 함께 표시 — 결과 표의 **[추가로 올리기]**로 같은 세션에 추가
- 파일별 진행률: h3d 를 받는 동안 파일 표에 받은 양/크기·진행 막대(서버 `GET /uploads/{id}` 의 그 파일 `received`). 다 받은 파일은 sha256 확인 표시, 같은 세션을 다시 열면 배지 'SCX에서 받음'
- starter 는 `<이름>_0000.rad` 만 고를 수 있습니다(같은 폴더 엔진 rad 탐색 기준). 다른 이름을 API 로 직접 주면 엔진 rad 를 찾지 않고 작업 경고로 알림
- 대시보드가 꺼져 있거나 릴레이가 꺼짐·SCX 재로그인 필요 등이면 이 탭만 비활성 + 사유(다른 탭은 그대로). 관리자에게는 사유 코드·릴레이 상태·어댑터 버전
- 시작 전 검사 문구: 릴레이 내려받기 상한 초과(422 `SCX_FILE_TOO_LARGE` — 파일·상한 크기), 업로드 폴더 여유 부족(507 — 필요·현재 여유·남겨 둘 여유), 사용자당 동시 업로드 한도(429 `UPLOAD_LIMIT`)
- 관리자 매뉴얼 §2.7.2 SCX 릴레이 설정(대시보드 `SIMDASH_SCX_RELAY_*`·esl `hpc.scx`·`scx_drive`·`worker.xfer_lanes`·비밀 파일 권한), 실기 체크리스트 `docs/manual/scx_check.md`
### 변경
- 작업 레인 XFER 추가(SCX 전송·원격 대기 전용 — 추출·ESL 계산 대기열을 막지 않음, 설정 `worker.xfer_lanes`)
- 배포: SCX 릴레이 어댑터(physicsai simdash_adapters, 커밋 고정 `deploy\simdash_adapters.lock`) wheel 동봉 — 설치 실패 시 SCX 기능만 비활성. 관리자 설정 `hpc.scx`(physicsai 와 같은 키 + `client_name`)·`scx_drive`·`verify_drop`(검증 낙하 — v0.12.0, v0.11.0 은 켜도 비활성 `VD_NOT_AVAILABLE`), 환경 점검 scx.adapter·hpc.scx·hpc.scx.secret_file·scx.relay·worker.xfer_lanes
- DB migration `0012_scx_relay`(jobs.upload_id·verify_drop_id, XFER 레인, 검증 낙하용 표 verify_drops·scx_submissions — 표만)

## [0.10.1] - 2026-10-30
### 수정
- **배포: 형상 엔진 paicad wheel 을 저장소에 동봉**(`deploy\wheels\paicad-0.14.0-py3-none-any.whl`, `deploy\paicad.lock` 의 커밋·정규화 sha256 그대로). git 폴더 설치·`update-repo.ps1`·오프라인 묶음 설치가 **physicsai 저장소·wheel 폴더 없이** paicad 를 설치합니다(설치 전 sha256 대조 — 다르면 강성 평가 스터디 만 비활성 + 사유, 다른 기능은 그대로). `deploy.json` 의 `paicad_wheels`·`physicsai_root` 는 동봉 wheel 이 없을 때만 쓰는 예비 경로
- 오프라인 묶음(`collect-offline`)은 동봉 wheel 을 빌드 없이 그대로 넣습니다(GitHub·git 불필요). 설치 확인 `paicad_wheel.py check --wheel <동봉 wheel>` 로 파일 대조도 가능

## [0.10.0] - 2026-10-29
### 변경
- **상단 메뉴 2개 [ESL 생성] · [ESL 라이브러리]**: ESL 생성 = 케이스 목록 + 새 케이스, ESL 라이브러리 = ESL 목록과 그 ESL 로 하는 일(내보내기·강성 평가 스터디·비드 최적화·종합분석). 라이브러리 탭 **ESL 목록 | 강성 평가 스터디 | 비드 최적화 | 종합분석·버전 비교 | 템플릿**
- **케이스 4단계 ①입력 ②t*·지지점 ③ESL ④검증**: 예전 ③ 지지점·⑥ 내보내기 단계 폐지. 주소가 `/stage/n` → `/step/n` 으로 바뀌고 옛 주소(북마크·메신저 링크)는 새 단계로 자동 이동(`/stage/3` → ②, `/stage/6` → ④ + "내보내기는 ESL 라이브러리로 옮겨졌습니다" 안내). Case 상단 **결과 받기(zip)** 는 그대로(FAIL 원인 조사용)
- **지지점 3-2-1 자동**: ② **t* 확정** 때 지지점을 자동으로 정하고 카드에 노드·dof·품질 지표(면적비·최소 거리·조건비)만 보여 줍니다(편집 UI 없음). 세 점이 거의 한 줄·너무 가까움·구속 약함이면 ②에서 멈추고 사유(값·기준)를 보이며, 이때만 접힌 **고급 — 지지 노드 직접 지정**으로 노드 3개를 넣을 수 있습니다(같은 품질 검사). 이전 버전에서 직접 고친 지지점은 그대로 유지(배지 '사용자 지정')
- **라이브러리 등록 = 변위 기준 PASS 만**: ④ 최신 검증이 PASS 면 주 버튼이 **라이브러리에 등록**(사유 입력 없음). FAIL·판정 불가·이전 판정 체계는 등록 버튼 비활성 + 사유
- '비드 DOE' 이름을 **강성 평가 스터디**로(화면·가이드·보고서·작업 이름. 보고서에는 v0.10.x 동안 "(이전 이름: 비드 DOE)" 부제). 주소·API·설정·폴더 이름(`doe`)은 그대로
### 추가
- **라이브러리 내보내기(여러 ESL 한 번에, 기본 숨김 — 관리자 설정 `ui.library_export_enabled: true` 일 때만)**: ESL 목록에서 체크 → **내보내기 (n)** → 형식(Radioss inc `/CLOAD`·`/BCS` · OptiStruct fem · CSV)·ID 시작(자동/지정) → 같은 창에서 항목별 진행·ID 범위 → **zip 받기**(manifest·README + ESL 별 폴더). 같은 모델 ESL 은 생성 ID 가 겹치지 않게 이어서 배정(다른 모델은 각자). 하중 원본은 등록 당시 라이브러리 항목(Case 가 다시 계산돼도 그대로), 창을 닫아도 계속되고 **최근 내보내기**에서 다시 받기. 한 번 최대 개수는 서버 설정 `library_export.max_entries`(기본 50)
- **LEGACY 배지 · 재검증**: 이전 판정 체계로 등록된 항목과 사유와 함께 등록된 FAIL·판정 불가 항목은 **LEGACY** 배지 — 내보내기는 되지만 강성 평가 스터디·비드 최적화·종합분석에는 쓸 수 없습니다(서버도 거부 `ENTRY_NOT_ELIGIBLE`). 행의 **재검증** → 현재 기준으로 다시 검증 → PASS 면 정상 항목으로 전환, FAIL 이면 사유(예 DISP_MAX)와 함께 LEGACY 유지·폐기 안내. 재검증할 수 없으면(추출 바뀜·스냅샷 없음·Case 보관) 버튼 비활성 + 사유
- **강성 평가 스터디 ESL별 개선 지표**: 순위표에 [전 씬 개선 ✓/✗]·최소 개선율·개선/악화 씬 수·기하평균 개선율·Pareto ● 열(열 머리 클릭 정렬, ⓘ 정의)과 'ESL별 개선율' 히트맵 표(안 × ESL) — 최악 ESL 기준 점수만으로는 안 보이던 '한 씬은 좋아지고 다른 씬은 나빠지는' 안을 바로 구분. 보고서·순위 CSV 에도
- 라이브러리 선택 줄: `선택 n개 · LEGACY k · 기준 크기` + 동작별 비활성 사유(LEGACY·크기 다름·최대 개수)
- 강성 평가 스터디 복제·재시도, 비드 최적화·종합분석 재시도도 LEGACY·FAIL 항목이 있으면 거부(재검증 후 사용). 실패한 라이브러리 내보내기 [재시도]는 처음(내보내기 단계)부터 다시
- 관리자 설정: 코어 `support.auto_check.*`(지지 자동 선택 기준, 임시값), 플랫폼 `library_export.max_entries`·`max_bundle_bytes`·`wait_s`. 내보내기 출력 `<esl_root>/_exports/<묶음>/`

## [0.9.0] - 2026-10-29
### 추가
- **비드 형상 DOE**(이슈 #37): 라이브러리에서 고른 ESL(낙하 하중)로 Ch/R 비드 깊이·폭·위치를 바꾼 여러 안의 **선형 강성**을 비교해 순위를 매깁니다. 라이브러리 항목 체크 → **선택한 ESL로 비드 DOE (n)**, 라이브러리 **비드 DOE** 탭에 연구 목록
- 시나리오 3가지(자동 판별, 바꿀 수 있음): **① 같은 모델**(ESL 원 Case 메시를 모핑 — 노드 ID 불변, 하중 그대로) · **② 다른 모델 + B 메시**(B rad/inc 를 모핑, 하중은 24×14 셀 매핑) · **③ 다른 모델 STEP 만**(안마다 새 쉘 메시, 쉘 물성 t·E·ν 기본값 = A 모델 Ch/R)
- 형상 엔진 **paicad**(physicsai, 버전 고정 0.14.0): 중립면(시트) STEP 에서 비드를 인식해 비드 표(모양·공칭 D/W/U/V·feasible 추정 범위·고정 겹침 경고)와 평면도를 보여 주고, 안마다 형상을 바꿉니다. 미리보기 썸네일 격자(공칭 d000 포함)에서 충돌·고정 침범·형상 불가 안은 회색 + 사유 배지로 빠집니다
- DOE 방식 LHS·Halton·풀 팩토리얼(시드·반올림·중복 제거로 같은 설정 = 같은 안), 실제 안 수 즉시 표시. 같은 설정의 미리보기가 끝나야 **DOE 실행**이 켜집니다
- **gmsh** 쉘 메싱(③ — quad 위주, 평균 요소 크기 설정, 베이스라인도 같은 규칙으로 메시해 비교 기준). 메시 잡음 바닥을 재서 그보다 작은 개선은 '잡음 이내' 표시
- 결과: **순위**(컴플라이언스 절대 기준 — 선택 ESL 중 최악, 개선율·최대 변위·변형률, 순위 밖 안 상태), **파라미터 민감도**(SRC·Spearman, 풀 팩토리얼은 주효과), **3D 비교**(베이스라인 | 선택 안, 같은 색 범위), 최적 안 받기(①② 바뀐 include · ③ `ch_r.rad`/`ch_r.fem` · BREP/STEP)·순위 CSV·zip·**보고서**(방법·출처·한계)
- **경계 매핑 경고**(②③): A 모델 체결점·하중 집중부를 B 평면에 옮겨 B 구멍·고정부와 거리가 멀면 평면도 빨강 점선·경고 수(차단 아님). B 체결 후보가 없으면 그 사실과 경고 수를 표시
- 작업 종류 '비드 DOE 준비·미리보기·실행'(대기열·실행 이력·작업 상세에 같은 단계 이름), 안 단위 이어하기 재시도, 취소, 재실행 = **복제**
- 배포: 설치·업데이트·오프라인 묶음이 paicad wheel(lock 의 커밋·**정규화 sha256** 대조)·cadquery-ocp·gmsh 를 함께 설치. 설치된 `paicad.exe` 를 찾으면 설정 `bead_doe.enabled`·`bead_doe.paicad.exe` 를 자동으로 채우고(기존 값 불변·백업·콘솔 1줄), 업로드 허용 확장자에 `.step`·`.stp` 1회 보충. 설치에 실패해도 다른 기능은 그대로(비드 DOE 만 비활성 + 사유)
- 관리자: 환경 점검에 paicad·gmsh·`_doe` 쓰기 확인, 실기 체크리스트 `docs/manual/bead_doe_check.md`
### 수정
- 0.8.0 이하 DB 를 올릴 때 migration 0010 이 이후 버전의 작업 제약을 참조하던 문제(0010 시점 정의로 고정 — 0008 → 0011 업그레이드 가능)

## [0.8.0] - 2026-10-29
### 추가
- **누적 낙하 씬 입력**: rad 가 이전 낙하 해석의 상태 파일(`.str` 변형 형상·두께, `.sta` 초기 소성 변형률)을 `#include` 하면 그대로 읽습니다. 계산 형상·두께(K_L) = 이전 런 변형 상태, 모델 동일성 확인도 그 좌표로
- 누적 씬 t*: 순위 = 누적 변형률(이전 + 이번), 시점 = 이번 낙하 증분이 최종값에 처음 도달한 프레임. 이번 낙하에서 늘지 않은 요소(이전 손상만)는 후보에서 빼고 개수만 표시
- h3d 소성 변형률이 이미 누적값인지 frame 0 값으로 자동 판정(불확실하면 이전 값을 더함 — 보수적). 설정 `cumulative.*` 로 강제·원두께 교차검증 가능
- 화면: Case 상단 '누적 씬' 배지, ① '누적 입력' 카드(상태 파일·좌표 출처·두께 변화 t/t₀·이전 소성·h3d 판정), ② `누적 (이전 + 이번)` 값과 표 열·증분 곡선 토글, ⑤ 변형률 참고 비교 '(이번 낙하 증분 기준)', 보고서 '누적 낙하 입력' 절
- 업로드 허용 확장자에 `.sta`·`.str`(기존 서버 설정이 목록을 적어 두었으면 업데이트 때 1회 보충). 상태 파일 include 가 빠지면 '이전 런 상태' 표시와 `STATE_INCLUDE_MISSING`
- 업데이트·설치 시 `altair.hw_exe_path` 와 같은 Altair 설치에 `hwsolvers/scripts/optistruct.bat` 이 실제 있으면 `altair.optistruct_path`·`opt_run.enabled: true` 를 자동으로 추가(기존 값·`enabled: false` 는 그대로, 수정 전 설정 백업, 콘솔 1줄)
- OptiStruct 오류 상세: 실패 메시지에 오류 번호·상세 줄·카드(예 `DTPG,9000006 연속 줄 1`)·덱 줄 번호·인용 덱 줄을 넣고(.out 끝 요약의 같은 오류는 한 번만), 전체 블록은 `solve/os_errors.txt`·작업 로그에 남깁니다. 설정 `opt_run.solve.error_detail_lines`(4)·`error_context_lines`(8)·`error_context_pattern`·`error_card_pattern`·`error_code_pattern`·`error_message_max`(480)
- 비드 최적화 상세가 실패면 **실패 확인 파일** 카드: 덱(.fem·.inc)·`.out`·`os_errors.txt`·`solve.json` 받기 + 덱·OptiStruct zip
- 라이브러리 설정 `optdeck.dtpg.*`(bead_flag·bead_fields·draw·pid_cont_col): OptiStruct 버전별 DTPG 비드 줄 칸 차이를 설정으로 맞춤(없으면 공식 형식 기본값)
- 실기 체크리스트 `docs/manual/opt_run_check.md` §2.5 '-check 실패 시 확인'(파일 위치·보내 줄 줄 범위)
### 수정
- 상태 파일처럼 ID 를 10자 칸에 오른쪽 정렬한 블록 헤더(`/SHELL/         2`)를 읽지 못하던 문제
- 설정 파일 자동 보충 시 CRLF 줄 끝·BOM 이 사라지던 문제(이제 그대로 유지)
- **라이브러리 항목 [수정]에서 모델명·인치를 고칠 수 없던 문제**: 수정 대화상자에서 모델(모델명·인치·버전·날짜·제품 질량)·씬(프로젝트·시나리오·순번·낙하 유형·라운드·씬 번호·orient·접미사·변형)·메모를 고쳐 저장하면 목록·필터·종합분석·비드 최적화 크기 판정에 바로 반영됩니다. 수정·폐기는 등록자 또는 관리자만(다른 사용자는 [수정] 비활성 + 사유), 다른 사람이 먼저 고쳤으면 오류 문구와 [최신 값 불러오기]
- **비드 최적화 `-check` 실패(OS_DECK_INVALID, ERROR # 1485)**: DTPG 비드 줄을 OptiStruct Reference Guide 형식(`+, MW, ANG, BF, HGT, NORM, , , SKIP` — `BEAD` 라벨 없음)으로 씁니다. 이전 덱의 `+,BEAD,60.,45.,10.,YES,BC` 는 OptiStruct 2026.1 이 "Field 0 contains unrecognized/unexpected label" 로 거부했습니다(이슈 #35). PID 가 7개 이상이면 연속 줄은 3번째 칸부터 씁니다
- 비드 최적화 덱의 min-max 목적 카드를 OptiStruct Reference Guide 형식으로 정정: `DESOBJ(MINMAX) = ID` → `MINMAX = ID`(DESOBJ 의 type 은 MIN/MAX/MINP/MAXP), `DOBJREF` 칸 순서 `DOID, RID, SID, NEGREF, POSREF`(이전 덱은 SID 칸을 비우고 기준 컴플라이언스를 NEGREF 칸에, subcase 번호를 POSREF 칸에 썼음)
- ④ 3D 하중 보기에서 화살표를 눌러도 선택되지 않던 문제(v0.7.1 직교 기본 이후 — 짧게 보이는 화살표를 거의 못 누름): 화살표 선택을 화면 기준 12 px(머리가 더 크면 머리 반지름 + 2 px)로 넓혀 원근·직교·확대 상태 모두 같게 동작
- 줄바꿈 없는 거대 파일(예 200 MB 한 줄)을 업로드·include 하면 그 줄을 통째로 메모리에 올리던 문제: 업로드 상태 파일 판정은 앞 `upload.state_scan_kb`(4096 KB)까지만, rad·include·상태 파일 해석은 한 줄 `case.rad_max_line_kb`(선택, 기본 1024 KB)를 넘으면 `RAD_PARSE_ERROR`/`STATE_PARSE_ERROR`
- 상태 파일 `/INISHE/EPSP_F` 헤더 NPT 가 매우 크면(예 40000) 내부 오류가 나던 문제: NPT ≤ `cumulative.max_npt`(100)·NPG ≤ `cumulative.max_npg`(64) 를 넘으면 `STATE_PARSE_ERROR`
- 상태 파일 숫자에 NaN·Inf 나 칸 폭 이상(20자 칸 경계에 공백 없음·붙은 실수)이 있으면 경고 `STATE_NUMBER_SUSPECT`(개수, 값 사용 규칙은 그대로)

## [0.7.2] - 2026-10-29
### 수정
- **새 비드 최적화 화면이 비던 문제**: v0.6.0 에서 업데이트한 서버는 코드 스냅샷에 방법·출처 자료(`resources/opt_method_sources.json`)가 빠져, 라이브러리에서 '선택한 ESL로 비드 최적화'를 누르면 화면이 비었습니다. 배포가 이 파일을 함께 복사하고, 자료가 없어도 화면은 정상(ⓘ 만 비활성)입니다
- 비드 최적화가 꺼져 있거나(설정 `opt_run` 없음) OptiStruct 경로가 없으면 화면은 그대로 보이고 '최적화 실행'만 비활성 + 사유 한 줄(설정 키·서버 경로는 관리자에게만)
- 이전 버전에 등록한 라이브러리 항목의 모델 정보 계산이 실패해도 그 항목만 '모델 정보 없음'으로 두고 목록·대상 확인은 정상(서버 경고 로그)
### 추가
- 화면 렌더 오류가 나면 빈 화면 대신 "화면 오류: <메시지> [다시 시도]" 한 줄
- 업데이트(update-repo·설치) 시 설정에 비드 최적화가 꺼져 있으면 "비드 최적화를 쓰려면 opt_run.enabled·altair.optistruct_path 설정" 안내 1줄(설정 파일은 바꾸지 않음). 환경 점검에 방법·출처 자료 확인

## [0.7.1] - 2026-10-29
### 추가
- ④ 3D 하중 보기 툴바에 **원근** 체크(해제 = 직교, 기본): 같은 시점·같은 크기로 전환되고 선택은 브라우저별로 기억합니다

## [0.7.0] - 2026-10-29
### 추가
- **비드 최적화 서버 실행**: 라이브러리에서 고른 ESL 여러 개로 서버 워커가 OptiStruct 비드(DTPG) 최적화를 직접 돌립니다(작업 `OPT_RUN`: 대상 준비 → 하중·선정 → 덱 생성 → OptiStruct `-check`·본 실행 → HyperView 후처리 → 등록). 결과는 라이브러리에 넣지 않고 라이브러리 '최적화 실행' 탭과 실행 이력에 남습니다
  - **S1 기존 형상**: 기준 ESL 의 Case 입력 rad 대상 파트를 그대로(복사 없이) 읽고 하중을 노드에 직접 적용. 같은 모델(노드 ID + 요소 연결) ESL 만 넣을 수 있고, 다른 모델은 '다른 모델 빼기' 또는 템플릿 최적화 안내
  - **S2 템플릿**: 등록한 평판 쉘 메시(.rad + include 또는 .fem)에 같은 크기 ESL 을 셀(24×14) 합력·합모멘트로 옮겨 최적화. 크기 = 같은 인치 + 치수 ESL 간 ±2 %, 템플릿과 ±5 %(서버가 `SIZE_MISMATCH` 로 막음)
- **템플릿**(라이브러리 '템플릿' 탭): 끌어다 놓기 → 청크 업로드 → 자동 검사(요소 종류·두께·평탄도·법선·셀당 노드·3-2-1 등) → 제목·인치(선택)·설명 → 등록. 모든 사용자에게 공개, 삭제는 등록자·관리자, 이전 실행이 참조 중이면 보관(숨김)
- **비드 금지 영역**: 자동(구멍 주변 반경·가장자리 띠, 설정값 15·10 mm) + 사용자 사각형(기준 모서리 4종·X·Y·가로·세로 mm). 평면도에서 드래그·방향키로 옮기면 숫자가 같이 바뀌고, 세트를 템플릿·모델별로 저장해 다음 실행에서 자동으로 불러옵니다. 평면도의 자동 영역은 구멍·가장자리를 따로 표시(켜고 끄기)
- **변형 모드**(덴팅·뒤틀림·굽힘): 각 ESL 변위를 자동 분류해 라이브러리 '모드' 열·필터(`?mode=`)에 보이고, 행에서 바로 고칠 수 있습니다(사용자 수정 = 굵게, '자동으로' 되돌림)
- **하중 선정 전략**(라디오): A 전부 넣기(추천 — 형상이 거의 같은 하중 |MAC| ≥ 0.95 만 병합, 20개 초과 시 군집 대표) / B 모드별 최악(최대 3개) / C 군집 대표 k개(기본 5). **목표 기준**: 절대(추천 — 가장 큰 컴플라이언스 최소화, 큰 하중 비중 유지) / 상대(C/C⁰). 상세의 하중 선정 표에 상태·병합 대상·반대 방향·군집·C⁰·최대 변위·모드 표시
- **방법·출처 ⓘ**: 하중 선정 카드·표 옆 ⓘ 팝오버(방식 요약·전략별 한 줄·목표 기준·출처 링크), 보고서에도 같은 '방법·출처' 절
- 비드 치수 입력(경사 45°·폭 60 mm·높이 10 mm 기본), 최적화 상세(진행 6단계·수렴 그래프·비드 맵·케이스별 C⁰→C·보고서), 결과 받기(비드 반영 메시 .rad/.fem, zip = 보고서·결과·덱 기본, OptiStruct 원본은 `parts=solve`)
- 대기열·실행 이력에 '비드 최적화'와 단계(대상 준비·하중·선정·덱 생성·OptiStruct·후처리·등록) 표시. 라이선스 부족은 300 초 간격 3회 자동 재시도, 재시도 시 덱이 같으면 해석 결과 재사용
- 설정 `opt_run.*`(크기 허용·비드 기본값·자동 금지 영역·하중 선정·모드 분류 기준·솔버 패턴), `altair.optistruct_path`·`max_concurrent_os`, `commands.os_check`·`os_solve`·`bead_post`, 업로드 허용 확장자 `.fem`. 환경 점검에 OptiStruct·후처리 TCL 확인
- 실기 체크리스트 `docs/manual/opt_run_check.md`(OptiStruct·HyperView 서버에서 처음 돌릴 때)
- DB migration **0010**(`opt_runs`·`opt_templates`·`opt_keepouts`, 라이브러리 항목 `topo_sha256`·`deform_mode`, 작업 `opt_run_id`)
### 변경
- 라이브러리 항목 표: 행 체크(첫 행 = 기준, 같은 크기만 — 허용 오차는 서버 설정값), 크기·ⓜ(같은 모델)·모드 열, 탭 [항목 | 종합분석 | 버전 비교 | 최적화 실행 | 템플릿]

## [0.6.0] - 2026-10-28
### 변경
- 대용량 h3d 업로드가 빨라집니다(업로드 프로토콜 2): 청크가 16 MB → 64 MB 로 커지고 한 파일의 청크를 동시에 최대 4개까지 순서와 상관없이 보냅니다. 서버는 받는 대로 디스크의 제 자리에 바로 쓰며(청크 전체를 메모리에 모으지 않음) 파일 전체 sha256 은 앞에서부터 따라가며 계산합니다. 이미 받은 청크를 다시 받으면 쓰지 않고 `duplicate` 로 응답합니다
- 올리기를 끝내기(complete) 전에 서버가 누락을 검사합니다: 덜 받은 파일이 있으면 어느 청크 범위가 비었는지 알려 줍니다(`UPLOAD_INCOMPLETE`)
- 업로드 목록 응답이 파일별로 받은 청크 범위(`chunks`)·연속 받은 바이트(`received`)·합계(`received_total`)를 줍니다. 이어 올리기는 받은 청크 범위 기준입니다
- 진행 중인 업로드 세션 한도(사용자당 2개)에 걸리면 어떤 세션이 열려 있는지(이름·진행량·문제 수)를 함께 알려 주고, complete 검사에 실패해 남은 세션도 목록에서 문제 수와 함께 보입니다
- 업그레이드 전에 만든 진행 중 업로드와 현재 PC 도구·브라우저의 순차 올리기는 그대로 동작합니다
- ④ 3D 하중 화살표: 부피 있는 원기둥 대신 화면 픽셀 고정 두께의 선 몸통과 뾰족한 가는 원뿔 머리(시안 S3a)가 기본입니다. 3-2-1 지지 축 선분도 같은 선으로 그립니다
### 추가
- 업로드에 파일별 정보(`meta`)를 붙일 수 있습니다: PC 도구가 만든 압축 모드 h3d(대상 파트·결과만 남긴 h3d)의 원본 크기·hvtrans 시간·남긴 결과 등. complete 결과(`h3d_meta`)와 Case(`input_h3d_meta`)에서 볼 수 있습니다
- 압축 모드 h3d 로 만든 Case 에 다른 파트를 지정하면 `SLIM_PART_MISMATCH` 로 막고 "다른 파트는 원본 h3d로 올리세요"라고 안내합니다. 서버 추출이 압축 모드 h3d 에서 실패하면 원본으로 다시 올리라는 힌트가 붙습니다
- 업로드에서 파일 하나 빼기 `DELETE /uploads/{id}/files/{index}`: 받은 부분은 `_backup` 으로 옮기고(삭제 없음) 목록에는 `removed` 로 남습니다. 완료된 업로드도 그 업로드로 만든 Case 가 없으면 뺄 수 있고 다시 올리는 상태로 돌아갑니다
- 설정 `upload.parallel`(기본 4)·`upload.write_buffer_kb`(1024)·`upload.preallocate`(true), `ui.upload_slim_hint_gb`(기본 5, `GET /version` 의 `ui` 로 전달), `upload.chunk_mb` 기본 16 → 64
- 새 오류 코드: `LENGTH_REQUIRED`(411)·`CHUNK_LENGTH_MISMATCH`(422)·`CHUNK_IN_FLIGHT`(409)·`UPLOAD_PARALLEL_LIMIT`(429, `Retry-After`)·`UPLOAD_FILE_REMOVED`·`UPLOAD_FILE_BUSY`·`UPLOAD_IN_USE`(409)·`UPLOAD_SIZE_MISMATCH`(422)·`UPLOAD_META_INVALID`(422)·`SLIM_PART_MISMATCH`(422)
- 웹 업로드: 청크를 동시에 여러 개 보내고(서버 `chunk_size`·`max_parallel` 기준), 올릴 목록에서 파일을 골라 빼기(올리는 중이면 서버에서도 빼기), 큰 h3d 에 압축 모드 안내, 다른 화면으로 가도 올리기가 이어지고 상단에 진행 칩이 보입니다. `?upload=` 화면은 PC 도구가 올린 것("PC에서 올림")과 브라우저에서 올린 것("브라우저에서 올림")을 구분합니다(업로드 응답 `client`)
- PC 도구: 병렬 업로드(프로토콜 2)와 압축 모드(hvtrans 로 대상 파트·필요한 결과만 남긴 h3d 를 만들어 올림, 기본 ON, `/original` 로 원본)
- 서버 운영 스크립트 `deploy\esl-start.bat`·`esl-stop.bat`·`esl-restart.bat`(더블클릭, health 확인까지 대기, 실행 중 작업 경고 후 Y/N, `-Only backend|worker`)
- DB migration 없음

## [0.5.9] - 2026-10-28
### 변경
- ⑤ 단면 그래프: 스케일이 달라 오히려 차이가 크게 보이던 Δw 곡선과 오른쪽 보조 축을 뺐습니다(Δw 최대·RMS 수치 줄은 그대로)
### 추가
- 단면 그래프 축 편집(면외·단면 위치 최소·최대 입력, "자동"으로 복귀, 검증·방향별 기억)과 범례 클릭으로 계열 표시/숨김(최소 1개 유지, 자동 범위는 보이는 계열 기준)

## [0.5.8] - 2026-10-28
### 추가
- ④ ESL 3D 하중 보기(서버 자료): 부품 표면 3D 모델(`part.glb`, 대형 부품은 저해상도 `part_lod.glb` 추가), 노드 값(`values.bin`: 면압·면외 하중·|F|·상대 변위), 상위 노드 100행과 공간 군집 합력(2~5개, 합력·하중 중심·합모멘트·상쇄율)을 담은 manifest. 표면 색 값은 **면압 |Fn|/A [MPa]**(노드 대표 면적 A = 인접 요소 면적/절점 수의 합), 노드힘 |Fn| N은 툴팁용으로 함께 제공
- API: `GET /esl-runs/{id}/view3d`(manifest, 첫 요청 때 `runs/<id>/view3d/` 에 생성·캐시, 입력이 바뀌면 이전 폴더를 `_backup` 으로 옮기고 재생성), `…/view3d/part.glb`·`part_lod.glb`·`values.bin`(ETag·304). 오류 `VIEW3D_TOO_LARGE`(413)·`VIEW3D_BUSY`(503)·`VIEW3D_STALE`(409)·`VIEW3D_LOD_NONE`(404)·`VIEW3D_DISABLED`(404)
- 설정 `view3d.*`(기본값으로 동작, 섹션 없어도 됨): `enabled`·`max_nodes`·`max_glb_bytes`·`lod_min_nodes`·`lod_target_vertices`·`top_max`·`cluster_k_max`·`kmeans_max_iter`·`build_wait_s`
- DB migration 없음(파생 캐시 파일만)

## [0.5.7] - 2026-10-28
### 변경
- ⑤ 검증의 판정 기준을 변위로 바꿈: 변위 RMS·변위 최대 오차·반력·변위 잡음 바닥 4개가 모두 기준 이내면 PASS. 변형률 지표(hotspot·최대변형률·P90·잡음 hotspot)는 판정에서 빠지고 "참고"로만 표시됩니다(소성 힌지처럼 선형 변형률로 맞출 수 없는 부위 때문에 FAIL 나던 문제 해결)
- 전체 재해석을 생략한 검증은 변형률로 대신 PASS 하지 않고 "판정 불가"(UNDETERMINED)로 표시. 예전에 만든 검증은 다시 계산하지 않고 "이전 판정 체계"로 표시
### 추가
- 변형률 참고: 기준 초과 요소 수·비율, |오차| P99, 소성 영역(epsp>0) 요소 수, 겹쳐보기용 초과·소성 표시 값
- 변위 전 노드 분석: 노드별 오차 컨투어 자료(compare_disp.npz, `GET /validations/{id}/disp-field`), 로그 히스토그램, 상위 노드 표
- 컨투어 레전드의 견고한 자동 범위(P99, 유효숫자 2자리 올림) `color_range_robust`
- 단면선: 임의 위치(`at`)·기본 길이 방향 단면, Δw 곡선과 통계, 지도에 그릴 단면선, 추천 단면(최대 변위 오차 노드·hotspot 1위)
- 라이브러리: 판정 불가 결과는 사유를 적어 등록할 수 있음, 목록 필터에 판정 불가·이전 판정 체계 추가
- DB migration 0008, validation.json schema `esl/validation/3`, 설정 키 `validation.disp_max_rel_max`·`disp_noise_rel_max`·`disp_top_n`·`disp_hist_bins`

## [0.5.6] - 2026-10-28
### 수정
- 화면·응답의 경로 표기가 `E:/.../esl-data\Case`처럼 / 와 \ 가 섞이던 문제: Windows 서버에서는 Case 폴더·결과·추출 폴더·내보내기 파일·이력·보고서 경로를 모두 역슬래시로 통일해 표시
- 큰 파트 내보내기가 `ID_RANGE_COLLISION — 생성 ID … 범위 폭 999999 를 넘음`으로 실패하던 문제: 생성 ID 범위 폭 제한을 없애고 필요한 개수만큼 배정(rad 기존 ID와 겹치면 오류, 설정 `export.radioss.id_offset: auto`가 기본이며 겹치면 자동으로 10의 거듭제곱 위로 올림)

## [0.5.5] - 2026-10-27
### 수정
- rad와 h3d가 같은 모델인지 노드·요소 연결로 확인하고 좌표는 대략만 비교 — 압축 h3d 등 좌표 미세 차이로 정리가 실패하던 문제 해결

## [0.5.4] - 2026-10-23
### 수정
- 낙하 해석 h3d에서 서버 추출 정리가 전 노드 좌표 차이(ID_MISMATCH)로 실패하던 문제: h3d 초기 좌표를 프레임 0 좌표에서 프레임 0 변위를 빼서 구하고, 그래도 다르면 오류 메시지에 평균 편차·강체 이동 여부 등 진단을 표시

## [0.5.3] - 2026-10-22
### 수정
- 서버 h3d 추출 후 정리 단계가 소수 노드의 초기 좌표 차이(Radioss 초기 관통 보정 등)로 ID_MISMATCH 실패하던 문제: 소수 노드(기본 1% 이하, 최대 편차 bbox의 1% 이하)만 다르면 경고(COORD_DEVIATION, 노드 목록 기록)로 계속 진행(계산은 rad 좌표 사용)

## [0.5.2] - 2026-10-21
### 개선
- 긴 표·로그·목록(① 파트 표, 업로드 파일, 결과 표, 실행 이력·작업 로그, 내보낸 파일)이 화면 높이 기준으로 제한되고 안에서 스크롤됩니다(표 머리글 고정). 넓은 화면(2K 이상)에서는 ⑤ 검증·작업 상세 카드를 2열로 배치해 한 화면에 더 들어옵니다.
### 수정
- 큰 모델에서 rad 확인(① 파트 목록)과 ESL 준비가 빨라짐: 대상 파트만 읽음(합성 100만 요소 기준 파트 목록 약 12배, ESL 준비 약 3배)
- 서버 추출 중 진행 상황이 작업 로그에 보이도록(진행 로그 progress.log 전달, 60초 무변화 시 하트비트) 하고, 추출 단계 진행률이 단계별로 차오르도록

## [0.5.1] - 2026-10-21
### 수정
- ① 입력에서 파트 title의 공백·_·-·대소문자 차이로 "PART_NOT_FOUND"가 나던 문제 수정(예: 'chassis rear' = 'chassis_rear'). 못 찾았을 때는 파트 표의 행을 눌러 title을 채울 수 있음
- ① 입력: Case에 저장된 파트 title로 rad를 확인(설정 기본값 대신), 확인 중에는 '추출 실행'을 막고, 같은 rad를 다시 열면 즉시 표시(파트 목록 캐시)

## [0.5.0] - 2026-10-21
### 추가
- 실행 이력: Case 메뉴 '실행 이력'과 프로젝트 '실행 이력' 페이지에서 지난 작업의 입력값·오류·소요 시간·로그를 다시 보고, "그때 결과 열기"로 과거 ESL 결과와 검증을 읽기 전용으로 확인(현재와 다른 점 표시)

## [0.4.0] - 2026-10-20
### 추가
- 새 Case에서 입력을 브라우저로 고르기: 내 PC에서 올리기(rad·include·결과 폴더, 이어 올리기), 서버 폴더 찾아보기
- 결과 받기(zip): 내보내기 파일·보고서를 한 번에 내려받기
- 상단 바 버전 표기와 업데이트 내역, 사용 가이드 화면
- h3d를 올리면 서버가 직접 추출(HyperView), 작업 동시 실행(기본 2개)
- PC에서 ESL_extract.bat으로 추출해 자동 올리기(PC 연결 코드), ESL_upload.bat
- 새 Case "PC에서 추출해 올리기" 탭(연결 코드 만들기·연결된 PC 목록과 폐기), ① "서버에서 추출 중(HyperView)" 단계 표시, 대기열 동시 실행 수
### 수정
- 회사 PC 프록시 환경에서 "대시보드 계정이 활성 상태가 아닙니다"가 나던 문제
- PC 연결 코드 잘못 입력 잠금: PC를 구분할 수 있으면 PC별 5회, 구분할 수 없으면 서버 전체 30회(15분)
- 보안 강화: 연결 코드 잠금 우회(X-Forwarded-For) 차단, 업로드 폴더 격리(본인 폴더만·백업 숨김), PC 도구는 rad 폴더 밖 include를 확인 후에만 올림

## [0.3.0] - 2026-10-20
### 추가
- 대시보드 사이드바 "등가정적하중" 연결(대시보드 Vite 프록시), 설치 단계별 가이드
- ESL 라이브러리·종합분석·비드 최적화 덱(모든 씬 minmax)·설계 버전 비교
- 전 요소 ESL 재현 오차 비교·겹쳐보기, Case HTML 보고서

## [0.2.0] - 2026-10-19
### 추가
- 플랫폼(API·DB·워커·6단계 화면), Windows 서버 설치·업데이트

## [0.1.0] - 2026-10-19
### 추가
- 계산 코어(rad 파서, 쉘 솔버, t*, ESL, 검증, 내보내기), HyperView 추출 TCL
