# 계약: ④ ESL 3D 하중 보기 + 상태 서랍 (v0.5.8)

- 상태: **확정** (2026-10-28, 사용자 결정 2026-10-28). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 대체 범위: `esl.md` §9 레이아웃 "본문 + 우측 패널(대기열·워커 상태)" → 상단 바 상태 칩 + 오른쪽 서랍(§9), `esl.md` §9 ④ 행·`esl_platform_p1b.md` ④ 행에 3D 하중 보기 추가(§8). 충돌 시 이 문서 우선.
- 버전: **v0.5.8**. DB migration **없음**(파생 캐시 파일만, §3.4). MCP 예정 migration 번호(0009)는 영향 없음.
- **변경 메모 L3-C2 (2026-10-28, 사용자 확정: 화살표 시안 S3a)**: 화살표를 원기둥+원뿔(부피) 대신 **픽셀 고정 두께 선 + 가는 원뿔 머리**로 변경. 3-2-1 축 선분도 같은 선 렌더(2 px)로 통일. 반영: §6.2·§6.3·§8·V-L3-10. 충돌 시 이 항목 우선.
- **변경 메모 L3-C1 (2026-10-28, 사용자 미결 확정 Q1~Q3)**: (Q1) 표면 색 값 = **면압 p = |Fn|/A [MPa]**(노드 대표 면적 A_i = 인접 요소 면적 ÷ 요소 절점 수의 합, §3.5). 노드힘 Fn [N]은 툴팁·표용으로 함께 제공. 반영: §0-2·§3.4(LOD 대표 = 면압 최대)·§3.5(values.bin 배열 pa 추가)·§3.6(manifest 상위 행 `pa`·`ranges.pa`·`pressure_unit`)·§6.1(색·레전드)·§12·§14·§15 R1·§16. (Q2) 화살표 단계 100·50·20·10 → 군집 합력 5·4·3·2, 노드 모드 최소 10(임계) — §5·L3-10 그대로 확정. (Q3) 서랍 상태 = 브라우저별 localStorage — §9·L3-15 그대로 확정(서버 저장 안 함).
- 참고(읽기 전용): 형제 플랫폼 physicsai `release/v0.2.12`(51152cd) — 3D 뷰어(`frontend/src/stages/stage4/geomview/**`, 계약 geometry-view·contour3d-field: npm three 번들·CDN 금지, GLB mm·Z-up, 정점 색, 대형 메시 LOD, onDemand 렌더, jsdom 시험은 순수 함수 분리)와 레이아웃 A(`shell/RunStatus.tsx`·`panels/{DrawerSection,QueuePanel,WorkerResourcePanel}.tsx`: 상단 바 칩 2개 → 서랍, 폴링 1곳). 코드는 복사하지 않고 설계만 따른다(저장소 분리).

## 0. 사용자 결정 (2026-10-28)

1. ④ ESL: "F_eq 상위 노드" 표를 한 칸 아래로 내리고 그 자리에 **3D 부품 뷰**(부품 표면 + 하중 벡터 + 3-2-1 고정 표시).
2. 색: 면외(법선) 하중은 **푸른색 계열 표면 색**(값 = **면압 |Fn|/A [MPa]**, L3-C1), 상위 노드 하중 화살표는 **붉은색**.
3. 화살표 기본 **100개**(상위 |F|), 사용자가 줄일 수 있음. 임계 아래로 줄이면 **공간 군집 합력 화살표 최대 5개** 모드(군집 하중 중심, |F| 가중), 합모멘트는 수치로.
4. 변형 형상 토글(u_rel × 배율, ⑤ 단면과 같은 표기 "변형 확대 배율 ×k (실제 최대 X mm)", 실제 크기 토글).
5. 범위 = ④만(⑤·① 재사용은 후속).
6. 우측 워커·계산 대기열 패널 상시 표시 폐지 → 상단 바 상태 칩 + 오른쪽 서랍(열기/닫기, 상태 기억), **모든 화면**. 2560×1440에서 본문 폭 확보.
7. 기존 원칙 유지: 필수 UI만, 높이 제한·표 머리글 고정, 2560×1440 기준, 1920×1080 잘림 없음.

## 1. 현황 (main 90f47b7, v0.5.7)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| ④ 화면 | `frontend/src/stages/Stage4.tsx` | 카드 순서: 입력 요약(t*·지표·지지 노드·dof) → 결과(회전각·변형 RMS/max·ΣF·ΣM·평형 오차·잡음·하중 노드 수·경고) → **F_eq 상위 노드**(`api.forces(runId, 50)`, 열 노드·x·y·z·Fx·Fy·Fz·\|F\|·지지점 배지, `.table-wrap.scroll`). 과거 실행 `?run=` 읽기 전용(`PastFrame`), `availability ≠ full`이면 표 숨김 |
| 상위 노드 API | `routers/results.py` `GET /esl-runs/{id}/forces?top=1..1000`, `services/results.py forces` | `esl_source_dir`(runs 스냅샷 우선)의 `04_esl/f_eq.npz` + Case `01_extract/model.npz` x0. 정렬 `lexsort((nid, -mag))`, `is_support` = run.supports. 노드 불일치 500 `OUTPUT_INCONSISTENT`, 없음 409 `PREREQUISITE_MISSING`/`ESL_RUN_NOT_CURRENT` |
| 04_esl 산출물 | `esl/pipeline.py` S4(≈780–850행) | `f_eq.npz{node_id, f(N,3), is_bc}`, `u_rel.npz{node_id, u_rel, u_total, R, t, time, frame_index}`, `esl_summary.json{frame, kabsch{R,t,rot_deg,rms_def,max_def}, forces{sum_f, sum_abs_f, equilibrium_rel, moment_rel, moment_center, L_bbox, max_f, n_nodes_nonzero}, supports, noise, …, tag}`, csv 2개. `03_bc/support.json{supports[{node_id, dof "123"/"ij"/"k", flags, x0}]}` |
| 메시 | `01_extract/model.npz` | `node_id, x0(N,3) mm, elem_id, elem_type(3/4), conn(E,4 노드 위치 인덱스, 삼각형은 앞 3개), elem_pid, thickness…`. 법선·면 메시 파일 없음 |
| 실행 스냅샷 | `core/core_outputs.py` | `runs/<esl_run_id>/{03_bc,04_esl}` 하드링크 보존, `esl_source_dir`가 tag로 선택 |
| 우측 패널 | `shell/RightPanel.tsx`, `Shell.tsx` `.workgrid`(열 `minmax(0,1fr) var(--panel-w)`, `--panel-w: clamp(360px,22vw,560px)`) | 워커(동작/응답 없음·솔버·설정 오류), 계산 대기열(동시 실행 a/slots, 행), 보고서·내보내기 대기열(있을 때). `usePolling(api.queue, 5000)`·`usePolling(api.status, 5000)` — 이 컴포넌트 한 곳에서만 폴링. 2560 폭에서 560 px 상시 점유 |
| 상단 바 | `Shell.tsx TopBar` | 브랜드 · 경로 · (라이브러리) · 오른쪽: 사용 가이드 · 버전 칩 · 대시보드로 · 사용자/역할 |
| ⑤ 배율 표기 | `components/SectionChart.tsx` | "변형 확대 배율 ×k (실제 최대 면외 변위 X mm)", 슬라이더 지수 0~4(0.01), 기본 `k0 = clamp(0.05·span/wmax, 1, 1e4)`, "실제 크기(×1)" 토글. 레전드 `ColorLegend.tsx`(범위 편집·P99 자동) |
| 3D | — | three·WebGL 없음. 의존 react·react-dom·react-router-dom만 |
| 설정 | `core/config.py UiCfg` | `max_preview_points` 20000, `max_artifact_bytes` 20 MiB, `poll_queue_ms` 5000 |

## 2. 범위 / 비범위

| 범위 | 비범위 |
|---|---|
| ④ 3D 하중 보기(표면 면압 색, 상위 N 화살표, 군집 합력 ≤5, 3-2-1 기호, 변형 형상) | ⑤ 검증·① 입력 3D 재사용(후속), 3D 단면, 변형률 3D 컨투어 |
| 서버 파생 캐시(GLB·노드 값 바이너리·manifest) + API 4개 | 코어 파이프라인 S4 산출물 변경, 새 job_type, DB 변경 |
| 표↔3D 선택 연동, 표 행 수 = 화살표 수 | meshopt 압축·gzip 사전 압축(후속, §3.3) |
| 상단 바 상태 칩 2개 + 오른쪽 서랍(모든 Shell 화면), 폴링 1곳 | 워커 자원(CPU·RAM·GPU) 수치 — ESL `/status`에 없음, 후속 |
| 보고서 변경 없음 | Case 보고서 3D 그림 |

## 3. 서버 산출물 (파생 캐시)

### 3.1 생성 위치·시점 (L3-1)
- **API 요청 시 지연 생성 + 디스크 캐시**: 첫 `GET /esl-runs/{id}/view3d`가 만들고 이후 재사용. 위치 `<case_dir>/runs/<esl_run_id>/view3d/`(플랫폼 소유 runs 폴더, 코어 `04_esl`에는 쓰지 않음).
- 근거: (가) 과거 실행(v0.5.7 이전)도 스냅샷만 있으면 보인다 — 재계산·migration 없음, (나) 코어 S4·`fresh_dir`·스냅샷 규칙을 건드리지 않는다, (다) 계산은 numpy 벡터 연산으로 30만 노드 ≤ 3 s(§11), 외부 프로그램 실행 없음(API 서버 외부 명령 금지 규칙 유지). 기각: S4에서 생성(과거 실행 미지원, 코어 결합), 새 job_type(대기열·상태기계 증가 대비 이득 없음).
- 입력(읽기만): `esl_source_dir(run)/04_esl/{f_eq.npz,u_rel.npz}`, 같은 폴더 `03_bc/support.json`(없으면 run.supports), Case `01_extract/model.npz`. `f_eq.node_id ≠ model.node_id` 또는 `u_rel.node_id ≠ model.node_id` → 500 `OUTPUT_INCONSISTENT`.
- 동시성: 프로세스당 생성 세마포어 1개(메모리 상한). 대기 ≤ 60 s, 넘으면 503 `VIEW3D_BUSY` + `Retry-After: 5`. 쓰기는 `view3d.tmp-<uuid>/`에 모두 쓴 뒤 `os.replace`로 `view3d/`에 올린다. 이미 유효한 `view3d/`가 있으면 tmp를 버린다(결정적 출력이라 결과 동일).

### 3.2 캐시 키·무효화 (L3-2)
- `manifest.json.key = sha256(json{builder_version, view3d 설정(§10), 입력 4파일의 (상대경로, size, mtime_ns)})` 앞 16자. 요청마다 key를 다시 계산(stat만, 파일 해시 없음)해 다르면 재생성.
- 재생성 전 기존 `view3d/`는 `<case_dir>/_backup/<UTC ts>/runs/<id>/view3d`로 **이동**(삭제 금지 규칙 유지). `builder_version` 시작값 1.
- 응답 헤더 `ETag: "<key>"`, `Cache-Control: private, max-age=0, must-revalidate`, `If-None-Match` 일치 → 304.

### 3.3 부품 표면 GLB (L3-3)
- 파일 `part.glb`: glTF 2.0 바이너리, 메시 1개, 재질 없음(뷰어가 정함), 위치 단위 **mm**, 좌표 **model.npz 전역 좌표 그대로(Z-up)** — glTF Y-up 관례와 다르며 `asset.extras = {"units":"mm","up":"Z","generator":"esl view3d <builder_version>"}`로 표기(physicsai GV와 같은 규약).
- 정점 = model.npz 노드 **순서 그대로**(정점 i = 노드 i, 재배열 없음 — 값 바이너리와 같은 순서, 불변식).
- POSITION: `KHR_mesh_quantization` SHORT normalized ×3(+2 B 패딩, stride 8), 노드 `translation` = bbox 중심, `scale` = 반축 길이(0이면 1). accessor min/max 필수. 위치 오차 ≤ 축별 bbox 길이/65534/2(2 m 부품 ≈ 0.015 mm, 표시 전용).
- `_NODE_ID`: UNSIGNED_INT(5125) SCALAR, 무손실.
- 인덱스: UNSIGNED_INT. 사각형 (a,b,c,d) → (a,b,c),(a,c,d), 삼각형 (a,b,c). 요소 순서 = model.npz 순서. NORMAL 없음(뷰어가 로드 직후 1회 `computeVertexNormals`, 변형 중 재계산 없음).
- `extensionsUsed`·`extensionsRequired` = `["KHR_mesh_quantization"]`. meshopt·Draco 없음(디코더 불필요, 새 Python·npm 의존 없음). 압축은 후속 — 30만 노드 ≈ 11 MB, 사내망 기준 ≤ 1 s.
- GLB 작성기: numpy + struct 직접 구현(`esl/view3d.py`), 새 의존 없음.

### 3.4 LOD (L3-4)
- N > `view3d.lod_min_nodes`(500,000)이면 `part_lod.glb` 추가. 방법 = **대표 원 노드 격자 군집**(physicsai C3F-8과 같은 방식): bbox를 정육면체 셀로 나눠 정점 ≈ `lod_target_vertices`(100,000)가 되도록 셀 크기 이분 탐색 → 셀마다 대표 = 셀 안 **면압 p 최대** 원 노드(같으면 작은 정점 번호, 피크 보존) → 삼각형 정점을 대표로 치환, 퇴화 삼각형·중복 삼각형 제거. 속성 POSITION(양자화 동일)·`_SRC`(UNSIGNED_INT, 원 정점 번호). 값은 `_SRC`로 values.bin에서 그대로 모은다(보간·평균 없음).
- 뷰어: 첫 표시와 조작(회전·확대·이동·배율 슬라이더) 중 LOD, 조작이 끝나고 250 ms 뒤 전체 해상도. 화살표·지지 기호는 항상 정확 좌표.

### 3.5 노드 값 바이너리 `values.bin` (L3-5, L3-C1)
- 머리 없음, little-endian, 정점 순서(§3.3). 배열은 순서대로(**pa, fn, fmag, u**) 4바이트 정렬(패딩 0). 오프셋·배율은 manifest `values.arrays`에(`key`·`dtype`·`comps`·`offset`·`scale`). 복원 = q·s (성분별).

| 배열 key | dtype | 의미 | 배율 s | 오차 상한 |
|---|---|---|---|---|
| `pa` | uint16 | **면압 p = \|Fn\|/A [MPa]** (표면 색 값, 크기만) | max p/65535 | s/2 |
| `fn` | int16 | 면외 하중 Fn [N] (부호 있음, 툴팁·표) | max\|Fn\|/32767 | s/2 |
| `fmag` | uint16 | \|F\| [N] | max\|F\|/65535 | s/2 |
| `u` | int16×3 (정점별 x,y,z 교차) | u_rel [mm] | 성분별 max\|u_c\|/32767 | s_c/2 |

- 배율 0(전부 0)이면 q 전부 0, s = 0. 30만 노드 ≈ 3.6 MB(p·fn·fmag 각 2 B + u 6 B = 12 B/노드).
- **법선·Fn·면압 정의**: 요소 법선 n_e = 단위 (사각형: (x_c−x_a)×(x_d−x_b), 삼각형: (x_b−x_a)×(x_c−x_a)), **방향 통일**: 판 기준 법선 n_p(X0 PCA 최소 분산 축, 부호는 성분 최대 절대값이 +)와 n_e·n_p < 0이면 뒤집음. 노드 법선 n_i = 정규화(Σ_{e∋i} A_e·n_e), ‖·‖ < 1e-12면 n_p. **Fn_i = F_i·n_i** [N].
- **노드 대표 면적 A_i = Σ_{e∋i} A_e / n_e** (A_e = |외적|/2 요소 면적, n_e = 요소 절점 수: 사각형 4, 삼각형 3 — 요소 면적을 절점에 균등 분배). 요소에 안 쓰이는 고립 노드 A_i = 0.
- **면압 p_i = |Fn_i| / A_i** [force/length² = MPa(N·mm)], A_i = 0이면 p_i = 0. 메시 크기에 의존하지 않는 값(조밀한 곳이 작아 보이는 문제 해소, 구 R1). 표면 색은 p만 쓰므로(크기, 부호 없음) 방향 통일은 Fn 부호(툴팁)에만 영향.

### 3.6 manifest·상위 N·군집 (L3-6, 서버 계산)
- **서버가 계산**해 `manifest.json`에 넣는다(상위 행 ≤ `view3d.top_max` 100, 군집 K = 2..`cluster_k_max` 5 전부). 근거: 정확한 float 값(표·툴팁이 양자화에 의존 안 함), 결정성을 Python 단위 시험 한 곳에서 보장, 클라이언트가 전 노드 F 벡터(12 B/노드)를 받을 필요 없음, 화살표 개수 변경은 manifest 잘라 쓰기라 왕복 없음. 기각: 클라이언트 k-means(JS·numpy 결과 일치 시험 이중화, 100만 노드 주 스레드 부담).
- **상위 N**: 전 노드(지지점 포함) 정렬 = `/forces`와 동일 `lexsort((node_id, −|F|))`. 행 `{rank, node_id, vertex, x, y, z, fx, fy, fz, mag, fn(N, 부호 있음), pa(면압 MPa), is_support}`.
- **군집 (L3-7, 결정적 가중 k-means)**:
  - 대상 = \|F_i\| > 0 노드 전부(지지점 포함), 좌표 = X0(mm, 유클리드), 가중 w_i = \|F_i\|.
  - 초기화(난수 없음, 가중 최원점): c₁ = argmax w(같으면 작은 node_id), c_j = argmax_i w_i·min_l‖x_i − c_l‖²(같으면 작은 node_id).
  - Lloyd: 가장 가까운 중심에 배정(같으면 작은 군집 번호) → 중심 = Σw x/Σw. 배정이 안 바뀌거나 `kmeans_max_iter`(50)회면 종료. 빈 군집은 argmax w·d² 노드로 다시 심음(최대 3회), 그래도 비면 K를 줄이고 `k_actual` 기록.
  - 군집 k 값: 노드 수 n_k, **합력 R_k = Σ F_i**, Σ\|F\|_k, **하중 중심 c_k = Σ\|F_i\| x_i / Σ\|F_i\|**(= 최종 Lloyd 중심), **c_k 기준 합모멘트 M_k = Σ (x_i − c_k) × F_i**, **상쇄율 η_k = 1 − ‖R_k‖/Σ\|F\|_k**, 변형 표시용 u_k = Σ\|F_i\| u_i/Σ\|F_i\|.
  - 정렬 ‖R_k‖ 내림차순(같으면 군집 최소 node_id) → 이름 C1..CK. 노드별 소속은 manifest에 넣지 않는다(크기). 표·툴팁용 값만.
  - **자기평형 명시**: 자유물체 F_eq는 ΣF ≈ 0, ΣM ≈ 0(평형 오차 = esl_summary). 따라서 K = 1은 의미 없어 제공하지 않고, K = 2면 R₁ ≈ −R₂(우력 + 모멘트). 군집 화살표는 "그 영역이 나머지 부품과 주고받는 순 하중"이며 군집 안에서 반대 방향 노드 하중(굽힘 짝힘 등)은 R_k에서 **상쇄**되어 M_k와 η_k로만 남는다. 불변식(시험): Σ_k R_k = ΣF, Σ_k [(c_k − c₀)×R_k + M_k] = Σ_i (x_i − c₀)×F_i (c₀ = esl_summary moment_center).

manifest 형태:

```json
{"schema":"esl/view3d/1","builder_version":1,"key":"ab12cd34ef567890","esl_run_id":"…",
 "n_nodes":223415,"n_elems":223415,"n_tris":440120,"units":"mm","force_unit":"N","pressure_unit":"MPa","up":"Z",
 "bbox":{"min":[…],"max":[…],"diag":1234.5},"plate_normal":[0,0,1],
 "geometry":{"name":"part.glb","bytes":11234567},
 "lod":null | {"name":"part_lod.glb","bytes":1500000,"n_vertices":99876},
 "values":{"name":"values.bin","bytes":2234150,
   "arrays":[{"key":"pa","dtype":"uint16","comps":1,"offset":0,"scale":0.00031},
             {"key":"fn","dtype":"int16","comps":1,"offset":446832,"scale":0.0123},
             {"key":"fmag","dtype":"uint16","comps":1,"offset":893664,"scale":0.0061},
             {"key":"u","dtype":"int16","comps":3,"offset":1340496,"scale":[1e-4,2e-4,3e-4]}]},
 "ranges":{"pa":{"max":20.4,"p99":4.6},"fn_abs":{"max":402.1,"p99":88.3},"fmag_max":410.0,"u_max":2.81},
 "sum_f":[…],"sum_m":[…],"moment_center":[…],
 "supports":[{"node_id":101,"vertex":5,"dof":"123","x0":[…]},{"node_id":202,"vertex":9,"dof":"13","x0":[…]},{"node_id":303,"vertex":77,"dof":"3","x0":[…]}],
 "top":[{"rank":1,"node_id":…,"vertex":…,"x":…,"y":…,"z":…,"fx":…,"fy":…,"fz":…,"mag":…,"fn":…,"pa":…,"is_support":false}],
 "clusters":{"2":{"k_actual":2,"rows":[{"label":"C1","n_nodes":…,"center":[…],"u_center":[…],"r":[…],"r_mag":…,"sum_abs":…,"cancel":0.93,"m":[…],"m_mag":…,"min_node_id":…}]},"3":{…},"4":{…},"5":{…}},
 "created_at":"…"}
```

- `ranges.pa.p99` = \|F\|>0 노드의 면압 p 99 분위(⑤ DP-10 `robust_range(…,"zero")`와 같은 함수, 유효숫자 2자리 올림; 해당 노드가 없으면 null) — **표면 색 기본 범위 [0, p.p99]**. `ranges.fn_abs.p99`는 \|Fn\|(N) 같은 정의(툴팁 참고용). u_max = max‖u_rel‖. `units`=길이, `force_unit`·`pressure_unit` = 코어 설정 `units.force`·`units.stress`(기본 N·MPa; 면압 단위는 힘/길이² 일관 단위 가정).

### 3.7 크기 상한 (L3-8)
- N > `view3d.max_nodes`(2,000,000) 또는 part.glb + part_lod.glb > `view3d.max_glb_bytes`(64 MiB) → 413 `VIEW3D_TOO_LARGE`(`limits`·실제값 포함), 이 결과는 캐시하지 않음(설정을 올리면 바로 다시 시도). values.bin 상한 = `max_glb_bytes`(같은 키). `ui.max_artifact_bytes`(20 MiB)는 view3d 파일에 적용하지 않는다(physicsai F5 숨은 실패 회피).

## 4. API (Impl-Backend, `routers/results.py`)

| 메서드·경로 | 응답 | 비고 |
|---|---|---|
| `GET /esl-runs/{run_id}/view3d` | 200 `View3dOut`(= manifest §3.6 + `geometry_url`·`lod_url`(없으면 null)·`values_url`) | 없으면 생성(§3.1). ETag/304. URL은 API 루트 기준 경로(`/esl-runs/{id}/view3d/part.glb` 등, `api.forces`와 같은 형태) |
| `GET /esl-runs/{run_id}/view3d/part.glb` | `model/gltf-binary` | FileResponse, ETag, Range 불필요 |
| `GET /esl-runs/{run_id}/view3d/part_lod.glb` | `model/gltf-binary` | lod 없으면 404 `VIEW3D_LOD_NONE` |
| `GET /esl-runs/{run_id}/view3d/values.bin` | `application/octet-stream` | 세 파일 모두 선택 쿼리 `?key=<manifest.key>` — 현재 입력의 key와 다르면 409 `VIEW3D_STALE` |

- 권한: 기존 결과 조회와 같음(`get_principal`, 프로젝트 viewer 이상). 파일 이름은 위 3개 고정 경로만(경로 매개변수 없음 → 경로 순회 불가).
- 파일 엔드포인트는 manifest가 유효할 때만 제공. 캐시가 없거나 key가 다르면 409 `VIEW3D_STALE`(manifest를 먼저 받으라는 뜻, 프런트는 manifest 재요청 1회).
- 생성 중 대기 초과 503 `VIEW3D_BUSY`는 `Retry-After: 5` 헤더 포함. 오류: run FAILED 409 `ESL_RUN_FAILED`, 산출물 없음 409 `PREREQUISITE_MISSING`(missing=["esl"]), 다른 실행으로 바뀜 409 `ESL_RUN_NOT_CURRENT`(forces와 같은 판정), 413 `VIEW3D_TOO_LARGE`, 503 `VIEW3D_BUSY`, 설정 `view3d.enabled=false` → 404 `VIEW3D_DISABLED`. 문구 한국어.
- `/esl-runs/{id}/forces`는 그대로 유지(호환·폴백). `docs/contracts/openapi_p1b.json` 재생성, 프런트 `check:api` 통과. esl_mcp_ready 구현 시 manifest는 도구 후보, 바이너리 3개는 제외 사유 "브라우저 3D 전용 바이너리".

## 5. 화면 배치 (Impl-Frontend, 기준 2560×1440)

```
┌ 상단 바 ─────────────────────────────────────────────────────────────────────────────┐
│ E ESL  등가정적하중 › 프로젝트 › Case › ④ ESL   라이브러리      [● 계산 1/2 · 대기 3] [● 워커 동작 중] 사용 가이드 v0.5.8 대시보드로 사용자 │
├ 스텝퍼 ①②③④⑤⑥ ───────────────────────────────────────────────────────────────────────┤
│ 입력 요약  (t* · 지표 · 지지 노드 · dof)                                               │
│ 결과       (회전각 · 변형 RMS/max · ΣF · ΣM · 평형 오차 · 잡음 · 하중 노드 수)          │
│ ┌ 3D 하중 보기 ─────────────────────────────────────────────────────────────────────┐ │
│ │ 화살표 [100 노드 ━━●━━━━━━ 군집 2]  [변형 형상]  변형 확대 배율 ×k (실제 최대 X mm) [━●━] [실제 크기(×1)]  [맞춤] │
│ │ ┌ 캔버스 clamp(320px, 52vh, 760px) ───────────────────────────────┐ ┌레전드┐     │ │
│ │ │  부품 표면(면압 푸른색) · 붉은 화살표 · 초록 3-2-1 기호           │ │면압 │     │ │
│ │ │                                    선택 노드 정보(좌하단 한 줄)   │ │ 편집 │     │ │
│ │ └───────────────────────────────────────────────────────────────────┘ └──────┘     │ │
│ │ 화살표 최대 = F_ref N · 길이 ∝ |F| (최소 길이 제한)  ·  군집 모드: ΣF ≈ 0 (자기평형) │ │
│ └───────────────────────────────────────────────────────────────────────────────────┘ │
│ F_eq 상위 노드 (N행, 머리글 고정, --tbl-max)  ← 군집 모드면 "군집 합력" 표           │
└──────────────────────────────────────────────────────────────── [서랍: 닫힘 기본] ─────┘
```

- 카드 순서(L3-9): 입력 요약 → 결과 → **3D 하중 보기** → **F_eq 상위 노드**(한 칸 아래). 과거 실행(`?run=`)도 같은 순서, `availability ≠ full`이면 3D·표 모두 숨김(현행 규칙).
- 2560×1440 첫 화면(스크롤 없이)에 결과 카드 + 3D 캔버스 전체. 1920×1080: 가로 스크롤 없음, 도구 줄은 줄바꿈 허용(잘림 없음), 캔버스 ≥ 320 px.
- 컨트롤은 위 한 줄뿐(필수 UI만): 화살표 단계 슬라이더, 변형 형상 토글, 배율 슬라이더 + 실제 크기 토글(변형 형상 켤 때만 활성), 맞춤(카메라 bbox 맞춤, 기본 등각 시점 +X+Y+Z 방향에서, up = +Z). 마우스: 회전·확대·이동(OrbitControls), 클릭 = 선택.
- 화살표 단계(L3-10): `[100, 50, 20, 10]` 노드 → `[군집 5, 4, 3, 2]`. 슬라이더 왼쪽 끝 = 100. 노드 단계 표 행 수 = 화살표 수. 군집 K < `k_actual` 최댓값이면 그 단계 비활성.
- WebGL 없음·three 청크 로드 실패 → 캔버스 자리에 "이 브라우저에서 3D 보기를 쓸 수 없습니다" + 표는 그대로. manifest 413/409/503 → 사유 한 줄 + 표는 `/forces?top=100` 폴백.

## 6. 색·크기 규칙

### 6.1 표면 색 (L3-11, L3-C1)
- 값 = **면압 p = |Fn|/A [MPa]**(노드 값, 정점 색 보간; 정의 §3.5). **단일 색조 푸른색 순차 표**: ColorBrewer Blues 9단계(#f7fbff → #08306b) 선형 보간 256칸, 0 = 가장 옅음, 범위 위 = 가장 진함, NaN = 회색. three 정점 색은 선형 공간 표 사용(physicsai colormap 주석과 같은 이유).
- **부호 처리**: 색은 크기만(법선 방향 규약이 국소적으로 불안정 — 판 굽힘부·플랜지). 부호는 툴팁·표 `Fn` 열에 수치로(+ = 판 기준 법선 n_p 쪽, §3.5). 방향은 화살표가 보여 준다.
- 범위 기본 [0, `ranges.pa.p99`], `ColorLegend` 범위 편집·"자동"(⑤ DP-10과 같은 동작). 레전드 제목 "면압 |Fn|/A (MPa)". 툴팁: 면압 p, 노드힘 |Fn|·Fn(N), |F|(N).
- 배경 중립 회색(라이트 #dfe3e8, 다크 #23272e)으로 옅은 파랑 면이 묻히지 않게. 재질 MeshLambert, 양면(DoubleSide), 조명 반구광 + 카메라 방향광.

### 6.2 화살표 (L3-12)
- 색: 노드 화살표 **#d62728**, 선택 #ff7f0e(선·머리 모두). 군집 화살표 **#a50f15** + 라벨 "C1 |R| N". 군집 꼬리 구는 두지 않는다.
- 위치: 꼬리 = 노드(군집은 하중 중심 c_k), 방향 = F(R_k). 변형 형상이면 꼬리도 x + k·u(군집은 c_k + k·u_k).
- 길이 스케일(선형): L_max = 0.10·bbox.diag, F_ref = 보이는 화살표 중 최대 \|F\|(군집 모드는 max ‖R_k‖), 길이 = L_max·\|F\|/F_ref, **최소 길이 노드 0.15·L_max, 군집 0.3·L_max**(점처럼 보이는 것 방지, 레전드 문구에 "최소 길이 제한" 명시).
- 몸통(L3-C2): **화면 픽셀 고정 두께 선**(three examples `LineSegments2`/`LineMaterial`, `worldUnits=false`) — 노드 **2 px**, 군집 **3.5 px**. 선은 끝점까지 그린다.
- 머리: 작은 원뿔(InstancedMesh 1개). 높이 = 기본 머리 길이 min(0.25·길이, 0.04·diag) × 0.35 를 **화면 9~26 px 로 제한**(군집은 1.8배), 반지름 = 높이 × 0.3(가늘고 뾰족). 제한 때문에 카메라 거리에 따라 매 렌더 재계산한다.
- 개수 변경은 인스턴스 수만 바꿈(재요청 없음).

### 6.3 3-2-1 지지점 기호 (L3-13)
- 색 **#1b9e77**(초록, 파랑·빨강과 구분). 화면 크기 고정 스프라이트 + 고정 방향 축 선분(L3-C2: 같은 선 렌더 `LineSegments2` 2 px).

| dof | 기호 | 라벨 | 축 선분 |
|---|---|---|---|
| 3성분 `123` | 채운 삼각형 ▲ | `123 (x·y·z)` | x·y·z 세 방향 |
| 2성분 (예 `13`) | 반 채운 삼각형 ◭ | `13 (x·z)` | 구속된 두 축 |
| 1성분 (예 `3`) | 빈 삼각형 △ | `3 (z)` | 구속된 한 축 |

- 라벨 문구는 `Stage3.dofText`와 같은 함수. 축 선분 길이 0.04·diag, 노드 양쪽으로. 표 `지지점` 배지와 같은 노드.

## 7. 표 ↔ 3D 선택 연동 (L3-14)

- 노드 모드 표 열: 순위 · 노드 · x · y · z · Fx · Fy · Fz · \|F\| · Fn · 면압 p · (지지점 배지). 군집 모드 표("군집 합력"): 군집 · 노드 수 · 중심 x·y·z · Rx · Ry · Rz · \|R\| · Σ\|F\| · 상쇄율 · \|M_c\| (N·mm). 표 아래 한 줄: "ΣF = … · ΣM = … (자기평형, 군집 합력의 합 = ΣF)".
- 행 클릭 → 해당 화살표 강조 + 노드 표식 + 좌하단 정보 줄(카메라는 안 움직임). 행 더블클릭 → 그 점으로 카메라 중심 이동.
- 3D 클릭: 화살표 레이캐스트 우선 → 그 행 선택(`aria-selected`) + 표 안에서 `scrollIntoView({block:"nearest"})`. 표면 클릭 → 가장 가까운 정점: 정보 줄 "노드 {id} · |F| {fmaĝ} N · Fn {fn̂} N"(양자화 복원값, 유효숫자는 양자화 간격까지), 그 노드가 표에 있으면 행 선택.
- 지지점 기호 클릭 → 정보 줄 "지지 {node} · dof {dofText}".
- 선택 상태는 화면 상태(URL 없음), 화살표 개수 바뀌어 사라지면 해제.

## 8. 3D 뷰어 구현 규칙 (Impl-Frontend)

- 의존: npm `three@0.186.1`(정확 버전, physicsai와 동일) 1개 추가. CDN·외부 파일 금지. `GLTFLoader`·`OrbitControls`는 `three/examples/jsm`(같은 패키지). DRACOLoader·웹 워커 금지.
- 지연 적재: `view3d/loadThree.ts`가 `import("./scene")` 동적 import → 별도 청크. ④ 화면에서 3D 카드가 마운트될 때만. 메인 청크에 three 없음(시험).
- 렌더: **onDemand** — 카메라·상태 변경 때만 `requestAnimationFrame` 1회(연속 루프 없음). ResizeObserver로 캔버스 크기, 서랍 열림·닫힘도 반영. 언마운트 시 geometry·material·renderer dispose.
- 순수 함수 분리(jsdom 시험): `view3d/values.ts`(values.bin 복원), `colors.ts`(Blues 표·정점 색 채우기), `arrows.ts`(단계→모드·개수, 길이 스케일, 인스턴스 행렬 입력값), `supports.ts`(dof→기호·축), `deform.ts`(위치 = base + k·û, 기본 k, 표기 문자열), `pick.ts`(최근접 정점). three 장면은 `scene.ts` 하나, 시험에서는 mock.
- 변형: 기본 k = 10^round(log10(clamp(0.05·diag/u_max, 1, 1e4)), 2), 슬라이더 지수 0~4(0.01). 표기 **"변형 확대 배율 ×{k} (실제 최대 {u_max} mm)"**, 토글 **"실제 크기(×1)"**(⑤ SectionChart와 같은 문구·동작). 변형 형상 기본 꺼짐. 배율은 표시용이며 값에 영향 없음(툴팁).
- GLB 로드는 `GLTFLoader.parseAsync`, 양자화 위치는 1회 float32 mm로 복원(physicsai contourGlb와 같은 방식).

## 9. 상태 서랍 (모든 화면, L3-15)

- `shell/RightPanel.tsx` 삭제, `.workgrid`는 본문 1열(`--panel-w` 폐지). 2560 폭에서 본문이 전체 폭 사용.
- **폴링 1곳**: `shell/RunStatus.tsx`의 `RunStatusProvider`(앱 루트, Shell 바깥 1회)가 `api.queue`·`api.status`를 `ui.poll_queue_ms`(현행 5000, 프런트 상수 유지)로 폴링. 칩·서랍은 `useRunStatus()`만 읽는다. 화면 숨김 시 건너뜀(현행 usePolling 규칙).
- 상단 바 오른쪽(사용 가이드 앞) **칩 2개**:
  - 대기열 칩: `계산 {running}/{slots} · 대기 {queued}`, 보고서·내보내기 대기열이 있으면 ` · 보고서 {n}` 추가. 실행 중이면 점 깜빡임(`running`), 내 작업 실행 중이면 강조(`mine`, 툴팁 "내 작업이 실행 중입니다").
  - 워커 칩: `워커 동작 중 · 솔버 {backend}` / `워커 응답 없음`(빨강) / 설정 오류 있으면 `설정 오류 {n}`(빨강).
  - 불러오는 중 `대기열 불러오는 중…`, 오류는 칩 툴팁에 오류 문구.
- **서랍**: 어느 칩을 눌러도 같은 서랍 열기/닫기(토글). 오른쪽 고정(상단 바 아래 ~ 화면 아래, 자체 스크롤), 폭 `--drawer-w: clamp(320px, 18vw, 420px)`. **비모달**(scrim·포커스 가둠 없음, `role="complementary"`, `aria-label="실행 상태"`), 열면 본문 `.page.drawer-open .workgrid { padding-right: var(--drawer-w) }`로 **밀어냄**(본문이 가려지지 않음). 머리 "실행 상태" + 닫기 버튼(✕). Esc는 포커스가 서랍 안일 때 닫고 여는 칩으로 포커스 복귀. 칩 `aria-expanded`·`aria-controls`.
- 내용: `panels/DrawerSection.tsx`(구획 머리 + 본문) 안에 `panels/QueuePanel.tsx`(계산 대기열: 동시 실행 a/slots, 실행·대기 행 — 현 RightPanel JobRow 그대로, 보고서·내보내기 대기열) · `panels/WorkerPanel.tsx`(워커 상태·솔버·사용 가능 백엔드·설정 오류). 워커 칩으로 열면 워커 구획으로 스크롤.
- **상태 기억**: `localStorage["esl.statusDrawer"] = "open"|"closed"`, 기본 닫힘. 모든 화면·새로고침에서 유지(브라우저별). 읽기·쓰기 try/catch, 실패 시 닫힘으로 동작.
- 1920×1080에서 서랍 열림 + 본문 가로 스크롤 없음(본문 최소 폭은 기존 panel 열 있을 때와 같은 수준).

## 10. 설정 (Impl-Backend, `core/config.py` 새 `View3dCfg`, 예시 yaml 2개)

```yaml
view3d:
  enabled: true
  max_nodes: 2000000
  max_glb_bytes: 67108864        # 64 MiB — part.glb+part_lod.glb, values.bin 각각
  lod_min_nodes: 500000
  lod_target_vertices: 100000
  top_max: 100                   # manifest 상위 행 수(= 화살표 최대)
  cluster_k_max: 5
  kmeans_max_iter: 50
  build_wait_s: 60
```
기본값은 `View3dCfg` 한 곳, 섹션이 없어도 기본값으로 동작.

## 11. 성능 목표

| 항목 | 목표 | 조건 |
|---|---|---|
| 첫 생성(GLB+values+군집 K=2..5) | ≤ 3 s / ≤ 12 s, 추가 메모리 ≤ 1.5 GB | 30만 / 110만 노드, 운영 서버 |
| 캐시 적중 manifest | ≤ 100 ms | stat 4회 + json |
| 첫 표시(manifest+GLB+values 받기·파싱·첫 렌더) | ≤ 2 s / LOD로 ≤ 3 s | 30만 / 110만 노드, 사내망 100 Mbps 이상 |
| 조작 | ≥ 30 fps | 30만 노드 전체 해상도, 50만 초과는 조작 중 LOD |
| 화살표 단계 변경 | ≤ 50 ms, 네트워크 0회 | |
| 배율 슬라이더 1단계 | ≤ 30 ms | 30만 정점 위치 갱신 |
| 브라우저 메모리(GPU 포함) | ≤ 300 MB | 110만 노드 |
| three 청크 | ④ 진입 전 0 B 적재 | 동적 import |

## 12. 시험

| ID | 기준 | 방법 |
|---|---|---|
| V-L3-1 | 법선·Fn·면압: XY 평판 + 임의 F → Fn = F_z(1e-12), 요소 일부 연결 순서 반전해도 같은 n_i·A_i, 고립 노드 n_p 대체·A=0·p=0, p = \|Fn\|/A (A = Σ요소 면적/절점 수, 사각형 안쪽 노드 h²) | 단위(`tests/test_view3d.py`) |
| V-L3-2 | 상위 행: 순서·값이 `/forces?top=100` rows와 동일(동률 node_id), vertex·fn·is_support 정확 | 단위 + API |
| V-L3-3 | 군집 결정성: 같은 입력 2회 바이트 동일 manifest, 노드 순서 섞은 입력 → 같은 군집(node_id 기준), 분리된 두 덩어리 합성 → K=2가 덩어리별, 빈 군집 재심기, 하중 노드 < K → k_actual 감소 | 단위 |
| V-L3-4 | 군집 불변식: Σ_k R_k = ΣF, Σ_k[(c_k−c₀)×R_k + M_k] = ΣM(rel 1e-9), η_k ∈ [0,1], c_k = \|F\| 가중 중심 | 단위 |
| V-L3-5 | GLB: glTF 2.0 헤더·청크 정렬, accessor min/max, `extensionsRequired=[KHR_mesh_quantization]`, 삼각형 수 = 2·n_quad + n_tria, `_NODE_ID` 왕복, 위치 오차 ≤ 상한, asset.extras units/up | 단위 + 프런트 `GLTFLoader.parseAsync` 고정 fixture(`tests/fixtures/view3d/small/*`, 생성 스크립트 `scripts/gen_view3d_fixture.py`, < 100 KB) |
| V-L3-6 | values.bin(pa·fn·fmag·u): 오프셋 4바이트 정렬, 복원 오차 ≤ s/2(성분별), 전부 0 → s=0, 프런트 `values.ts` 복원이 Python 복원과 같음(같은 fixture) | 단위 + 프런트 |
| V-L3-7 | LOD: N ≤ lod_min_nodes면 없음(lod null, 404 VIEW3D_LOD_NONE), 설정 낮추면 생성, `_SRC` 범위 유효, 정점 ≤ 1.2·target, 셀 대표 = 면압 최대, 결정적 | 단위 + API |
| V-L3-8 | 캐시: 두 번째 요청 생성 0회(빌더 호출 계수), 입력 mtime 변경·builder_version·설정 변경 → 재생성 + 이전 폴더 `_backup` 이동(삭제 없음), ETag/304, 동시 2요청 → 생성 1회·둘 다 200, 대기 초과 503 | API(PG) |
| V-L3-9 | 오류: FAILED 409, 산출물 없음 409 PREREQUISITE_MISSING, 다른 실행 409 ESL_RUN_NOT_CURRENT, max_nodes 낮추면 413 VIEW3D_TOO_LARGE(캐시 안 됨), 노드 불일치 500, enabled=false 404, 키 다른 파일 요청 409 VIEW3D_STALE, 과거 실행 스냅샷으로 200, 인증 없음 401 | API |
| V-L3-10 | 프런트 순수 함수: 단계 [100,50,20,10,C5..C2] ↔ 모드·개수, 길이 = L_max·\|F\|/F_ref(최소 노드 0.15·군집 0.3), Blues 표 끝값·밝기 단조 감소, dof→기호(3/2/1)·라벨 = dofText, 기본 k·표기 문자열 "변형 확대 배율 ×k (실제 최대 X mm)", 최근접 정점 | vitest |
| V-L3-11 | ④ 화면(scene mock): 카드 순서 결과 → 3D → 표, 표 행 수 = 화살표 수(기본 100), 군집 단계 → "군집 합력" 표 열·ΣF 줄, 행 클릭 → scene.select(vertex), scene 선택 콜백 → 행 `aria-selected`, 배율 컨트롤은 변형 형상 켤 때만 활성, 실제 크기 토글 k=1, WebGL 없음 → 안내 + 표 유지, manifest 413 → 사유 + `/forces?top=100` 폴백, `?run=` 읽기 전용 동일 배치 | vitest(jsdom) |
| V-L3-12 | 상태 서랍: 모든 Shell 화면에 칩 2개·RightPanel 없음, `api.queue`·`api.status` 호출이 간격당 각 1회(칩·서랍 열림 무관), 칩 문구(실행/slots·대기·보고서·워커 오프라인·설정 오류), 토글·닫기·Esc·포커스 복귀, localStorage 기억(다시 마운트 시 열림 유지), localStorage 예외 → 닫힘·오류 없음, 열림 시 `.drawer-open` | vitest |
| V-L3-13 | 번들: package.json `three` 정확 버전 1개 추가, 빌드 메인 청크에 three 없음·별도 청크 있음, dist에 외부 http(s) script/link 없음 | 정적(프런트 시험) |
| V-L3-14 | 성능: 합성 30만 노드 생성 ≤ 3 s(CI 표식 `perf`, 실패 시 경고 + 측정값 기록), 정점 위치 갱신 함수 30만 ≤ 30 ms | 단위(perf) |
| V-L3-15 | 화면 증적: 2560×1440 첫 화면에 결과 + 3D 캔버스 전체, 1920×1080 가로 스크롤·잘림 없음(서랍 열림·닫힘 각각), 군집 모드·변형 형상 스크린샷 | `scripts/screenshots*.mjs`(mock) |
| V-L3-E2E | (사용자) 실모델 chassis_rear 223,415 요소: 첫 표시 ≤ 2 s, 상위 100 화살표·3-2-1 기호 위치가 표·③과 일치, 군집 5 합력 합 ≈ ΣF, 서랍 상태 기억 | 수동 증적 |

기존 시험 중 우측 패널(`aside[aria-label="대기열·워커"]`)을 기대하는 것은 칩·서랍 기준으로 고친다.

## 13. 파일 소유 (병렬)

| 소유 | 파일 |
|---|---|
| **Impl-Backend** | 신규 `esl/view3d.py`(순수 numpy: node_normals·fn, top_rows, kmeans_weighted·clusters, lod_grid, write_glb, pack_values, build_view), 신규 `backend/esl_platform/api/services/view3d.py`(입력 해석·캐시 키·세마포어·tmp→replace·_backup 이동), `api/routers/results.py`(경로 4개), `api/schemas.py`(`View3dOut`·`View3dTopRow`·`View3dCluster`·`View3dValuesArray`…), `core/config.py`(`View3dCfg`), `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`, `worker/esl_worker/core_adapter.py`(래퍼 필요 시), `tests/test_view3d.py`, `backend/tests/test_view3d_api.py`, `tests/fixtures/view3d/small/*` + `scripts/gen_view3d_fixture.py`, `docs/contracts/openapi_p1b.json`(재생성), `VERSION`(0.5.8)·`CHANGELOG.md` |
| **Impl-Frontend** | `package.json`·`package-lock.json`(three 0.186.1), `src/stages/Stage4.tsx`, 신규 `src/view3d/{View3DCard.tsx, loadThree.ts, scene.ts, glb.ts, values.ts, colors.ts, arrows.ts, supports.ts, deform.ts, pick.ts, webgl.ts}`, `src/shell/Shell.tsx`, 신규 `src/shell/RunStatus.tsx`, `src/shell/RightPanel.tsx`(삭제), 신규 `src/panels/{DrawerSection,QueuePanel,WorkerPanel}.tsx`, `src/app/*`(Provider 장착), `src/components/ColorLegend.tsx`(팔레트 매개변수 추가만), `src/api/{types,endpoints}.ts`, `src/mock/**`, `src/styles.css`, `src/__tests__/{view3d.test.ts, stage4_3d.test.tsx, run_status.test.tsx}` + 기존 ui 시험 수정, `scripts/screenshots*.mjs` |

- 접점은 §3.5 values 배치·§3.6 manifest·§4 경로뿐. 프런트는 mock + 공유 fixture로 먼저 구현한다. `Stage3.dofText`는 프런트 소유 그대로 재사용.

## 14. 결정

- L3-1 3D 자료는 API 지연 생성 파생 캐시 `runs/<run>/view3d/`(코어·DB·job_type 변경 없음, 과거 실행 지원).
- L3-2 캐시 키 = builder_version + 설정 + 입력 4파일 (size, mtime_ns), 무효화 시 `_backup` 이동, ETag.
- L3-3 표면 = GLB(mm, Z-up, 노드 순서 정점, `KHR_mesh_quantization` int16 위치, `_NODE_ID`, uint32 인덱스, 법선 없음), meshopt·Draco 없음.
- L3-4 LOD = N > 50만일 때 대표 원 노드 격자 군집(면압 최대 대표, `_SRC`), 조작 중 LOD·250 ms 뒤 전체.
- L3-5 노드 값 = `values.bin` p uint16(면압)·fn int16·fmag uint16·u int16×3, 오차 ≤ s/2. Fn = F·n_i(면적 가중 노드 법선, PCA 판 법선으로 방향 통일), p = \|Fn\|/A_i.
- L3-6 상위 N·군집은 서버 계산(manifest, 정확 float), 화살표 개수 변경은 클라이언트 잘라 쓰기.
- L3-7 군집 = \|F\| 가중 k-means(X0 mm, 가중 최원점 초기화·난수 없음, Lloyd ≤50), K = 2..5, R_k·c_k·M_k(c_k 기준)·η_k, 자기평형 불변식.
- L3-8 상한 max_nodes 200만·max_glb_bytes 64 MiB, 초과 413(캐시 안 함).
- L3-9 ④ 카드 순서 입력 요약 → 결과 → 3D → 상위 표.
- L3-10 화살표 단계 100·50·20·10 노드 → 군집 5·4·3·2(K=1 없음: ΣF≈0).
- L3-11 표면 색 = 면압 p = \|Fn\|/A [MPa] 단일 색조 Blues, 부호는 수치로만, 범위 [0, P99] + 편집.
- L3-12 화살표 붉은색(#d62728, 군집 #a50f15), 선형 길이 L_max = 0.1·diag, 최소 노드 0.15·군집 0.3·L_max(L3-C2), 꼬리 = 작용점.
- L3-13 지지 기호 초록, ▲123 / ◭2성분 / △1성분 + 구속 축 선분 + dofText 라벨.
- L3-14 표 행 수 = 화살표 수, 행↔화살표·정점 양방향 선택.
- L3-15 우측 패널 폐지 → 상단 바 칩 2개 + 비모달 밀어내기 서랍(localStorage 기억, 기본 닫힘), 폴링 1곳.
- L3-16 three@0.186.1 npm 1개, 동적 import 청크, onDemand 렌더, 순수 함수 분리 시험.
- L3-17 v0.5.8, DB migration 없음.
- L3-C1 (2026-10-28, Q1~Q3 확정) 표면 색 값 = 면압 |Fn|/A [MPa](A_i = 인접 요소 면적/절점 수 합), 노드힘 Fn N은 툴팁용 병행 제공 · 화살표 단계 100·50·20·10 → 군집 5·4·3·2(임계 10) · 서랍 상태 = 브라우저별 localStorage.

## 15. 리스크

| ID | 내용 | 대응 |
|---|---|---|
| R1 | (해소, L3-C1) 노드 Fn은 메시 크기에 의존 → 표면 색을 면압 \|Fn\|/A로 확정 | 면압 사용, Fn(N)은 툴팁. 남는 한계: A_i는 요소 면적 균등 분배(절점 기여면적 근사), 저면적 노드(퇴화 요소)에서 p가 커질 수 있음 → 범위 P99 + 편집 |
| R2 | 변위 저장 정밀도 잡음이 F_eq를 흔들면 표면 색이 잡음 지도처럼 보임 | 기본 범위 P99, 결과 카드 잡음 지표 그대로, 범위 편집 |
| R3 | 자기평형이라 군집 합력이 작게 나와 "하중 없음"으로 오해 | 상쇄율 η·\|M_c\| 표, "ΣF ≈ 0 (자기평형)" 문구, K=1 미제공 |
| R4 | 굽은 부품에서 하중 중심 c_k가 부품 밖 | 화살표 꼬리에 작은 구 표식, 표에 좌표 |
| R5 | API 프로세스에서 100만 노드 생성 시 메모리·지연 | 세마포어 1, 상한 413, 캐시, 성능 시험 |
| R6 | GLB Z-up이 일반 glTF 뷰어에서 눕혀 보임 | asset.extras 표기, 뷰어 전용 파일(내려받기 메뉴 없음) |
| R7 | 서랍 밀어내기 시 3D 캔버스 크기 변경 | ResizeObserver 재렌더 1회, 시험 |
| R8 | three 청크(약 600 KB) 첫 진입 지연 | ④ 3D 카드에서만 적재, 이후 재사용 |

## 16. 미결 → 확정 (L3-C1, 2026-10-28)

- Q1 표면 색 양: **면압 |Fn|/A [MPa]**로 확정(§3.5·§6.1). 노드힘 |Fn| N은 툴팁용.
- Q2 화살표 단계 `[100, 50, 20, 10] → 군집 [5, 4, 3, 2]`, 노드 모드 최소 10(임계): 확정.
- Q3 서랍 상태 기억: 브라우저별 localStorage: 확정(서버 저장·API 없음).
- 남은 미결 없음.
