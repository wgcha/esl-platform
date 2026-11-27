# 계약: 강성 스터디 3D 낙하 씬별 보기 + 컴플라이언스(C 기여도·차이·umax 핀) 표시 + 컨투어 색·범례(HyperView 참조) (VL, v0.25.1)

- 상태: **초안 → 구현 기준**(2026-11-27). 브랜치 `release/v0.25.1`(main 97a0e358 v0.25.0 에서 분기). 이 문서가 원본.
- **개정 1(2026-11-27, 사용자 답)**: Q-VL-1 = "전부 통일"(연속값 색을 쓰는 모든 곳 — §0.5·§5.7~§5.9), Q-VL-2 = 스터디당 1 GB(`max_mb` 1024 확정). 구현 분할에 C2·F1c 추가(§10), 시험 V-0251-37~48(§9.5), 결정 D-0.25.1-VL-13~19, B1 구현 사실(§15.1). 개정 전 문장과 다르면 개정 1 이 우선.
- 관계: `esl_3d_load.md`(view3d 형식·색·성능 §11), `esl_viewer_hv.md`(v0.24.6 뷰어 — 층·범례 구간·쌍 동기·계획 표 `VIEWER_PLANS`), `esl_view3d_sources.md`(출처 탭·자료 만들기), `esl_jig_view.md`(사이드카·3D 다시 만들기), `esl_jig_case.md`(지그 3방식 C_mix), `esl_jig_grid_map.md`(다른 메시 격자), `esl_stiffness_metric.md`·`esl_load_transfer.md`(④ LT-9 같은 ESL 기준). 충돌하면 이 문서 범위에서 이 문서가 우선.
- DB migration **없음**. 새 설정 블록 1개(`bead_doe.view3d.scene` — §7). 새 공용 자원 1개(`resources/colormaps.json` — §5.8). 계산 결과(순위·per_esl·input_sha256) **불변** — 보기 자료·그림 색만 바뀜.
- ID: 결정 `D-0.25.1-VL-n`, 시험 `V-0251-n`, 후속 `R-VL-n`, 미결 `Q-VL-n`, 현장 확인 `E-0251-n`.

### 사용자 요청 (원문, 변경 금지)
1. "강성스터디 결과에서 낙하씬 선택해도 하중씬 비교 3d형상비교가 업데이트안돼"
2. "컴플라이언스 좋아졌다하는데 왜 umax는 증가하는거야?? 컴플라이언스가 증가했다는걸 3d컨투어에서 어떻게 보여줘?"
3. (2026-11-27 결정) "그렇게 해. 거기다 컨투어 색 컨셉을 하이퍼뷰어 처럼 높은게 빨간색 낮은게 파란색. 컨투어 레전드도 편집도 벤치마킹해서 넣어바"
4. (2026-11-27 답) Q-VL-1 = "전부 통일" — 높음 = 빨강·낮음 = 파랑을 3D 결과 컨투어뿐 아니라 ④ 검증 비교 2D·비드 높이 변화 색·보고서·썸네일·그 밖에 연속값 색을 쓰는 모든 곳에. Q-VL-2 = 스터디당 1 GB.

사용자 원칙(공통): 사용성 > 유연성 · 필수 요소만 · 정보 삭제 금지 · 2560×1440·1920×1080 세로 높이 증가 없음 · 하드코딩 금지 · 같은 기능은 공용 모듈 하나 · 서버 결과 기존 파일 바이트 불변(새 파일 추가는 허용) · SPDM·입력 폴더 쓰기 금지.

---

## 0. 감사 (97a0e358, 읽기만)

### 0.1 씬 선택과 3D 가 끊긴 이유

| 항목 | 지금 | 위치 |
|---|---|---|
| 안 3D | 안마다 **최악 ESL 하나만** 풀어 `post/view3d/<did>/` | `esl/doe/stages.py:867` `_view3d`(`worst_entry_id`, `keep_u=[한 개]`) |
| ④ 기준 3D | 표시 형상의 최악 ESL 마다 `d000_e<kk>/`, 키 `view3d_ref`·`view3d_esl` | `stages.py:3392` `_lt_view3d_ref` |
| 지그 출처 3D | 안 = 순위 행 worst 엔트리 1개(`rk._agg`), 기준 = 쓰인 엔트리만 | `stages.py:4712` `_jig_v3d_build`, 격자 `:6815` `_jg_view3d_src`, 노드 힘 `:5637` `_ns_view3d` |
| 화면 | `Compare3D` 는 `view3d_esl[did]`·`pairKeys.esl[did]` 만 읽음 — 씬 상태·선택 칸 없음 | `frontend/src/pages/doe/DoeStudy.tsx:1080-1104` |
| 씬이 보이는 다른 곳 | ESL별 개선율 표(열 = ESL), 순위표 "최악 ESL" 칸 — 클릭 동작 없음 | `components/DoePerEslTable.tsx`, `DoeRanking.tsx:244` |

결론: 자료(씬별 3D)도 없고 화면 연결도 없다. 둘 다 필요.

### 0.2 C·umax 정의 (코드 확인)

| 출처(순위 보기 키) | 지지 | C 저장값 | umax | 위치 |
|---|---|---|---|---|
| 전 노드 `full`(재풀이) · 경계력 `bforce` · 내력 `fint` | 3-2-1(값 0) | `C = Σ_n F_n·u_n`(병진 3성분) | 전 노드(선택 step 은 영역) 최대 ‖u‖, 새 스냅샷 `umax_ev` = 평가 영역 최대 | `esl/doe/evaluate.py:60-79`·`umax_in:87` |
| 지그 고정 `jig`(옛 npz) | tie 병진 고정 | `C_jig = Σ F·u` | `umax_mask`·`umax_ev` | `esl/mech/jig.py:915` `respond` |
| 지그 변위 `jig_disp` · 스프링 `jig_spring`(BC 배열 npz, 격자 지그 포함) | 지정 변위 v_c · 스프링(k_s, 바닥 g_s) · 3-2-1 면내 | `C_mix = FᵀU − Σ_c v_c r_c − Σ_s g_s f_s`, per_esl `C_<pe> = E_0 + (C_mix,d − C_mix,0)` | 같은 규칙 | `esl/mech/jig_bc.py:558` `mixed_compliance`·`:584` `per_esl_C` |

C 는 "하중이 한 일(하중 가중 변위)", umax 는 "한 점의 최대 변위"라 서로 반대로 움직일 수 있다 — 화면이 이것을 보여 줘야 한다(§4.3).

### 0.3 색·범례 (지금)

| 항목 | 지금 | 위치 |
|---|---|---|
| 결과 3D 표면 색 | **ColorBrewer Blues 9**(옅음 → 진함) — 레인보우 **아님** | `frontend/src/view3d/colors.ts:5-9`, 셰이더 색표 `scene.ts:205-244` |
| 발산 | RdBu 11 — **빨강 = −, 파랑 = +**(비드 높이 변화 전용) | `colors.ts:92-117` |
| 범례 구간 | 연속(기본)·6·9·12, 겹침 범례는 구간일 때만 | `viewerPlan.ts:5`, `LegendOverlay.tsx` |
| 범위 | 0~최대(최대 입력)·[자동]·범위 밖 ▲▼ 개수(끝색으로 칠함) | `components/ColorLegend.tsx` |
| 기억 | `localStorage["esl.v3d.viewer.v1"]`{planKey: {bc, load, ghost, marks, levels}} | `viewerPrefs.ts` |
| 쌍 공유 | 시점·변형·층·레벨(`useViewerSync`) + 범위(호출부) | `viewerSync.ts`, `DoeStudy.tsx:1091` |
| 색 다시 칠하기 | GPU(정점 값 + 색표 텍스처 + uniform `uMin·uMax·uLevels`) | `scene.ts:205-244·763·982` |

### 0.4 view3d 파일 크기 (형식에서 계산 — `esl/view3d.py:331·400`)

| 파일 | 내용 | 노드당 바이트(사각형 메시, 요소 수 ≈ 노드 수) |
|---|---|---|
| `part.glb` | 위치 int16×3 + 패딩(8) · 노드 ID uint32(4) · 삼각형 인덱스 uint32×3 × 2개(24) | **36** |
| `values.bin` | pa uint16 · fn int16 · fmag uint16 · u int16×3 | **12** |
| `manifest.json` | 상위 100행·군집·지지(≤ 64)·범위 | 20~60 KB(노드 수 무관) |

한 폴더 ≈ 48 B/노드: 3만 노드 1.5 MB · 10만 4.8 MB · 30만 14.4 MB. 형상(36)은 씬과 무관하고 씬마다 달라지는 것은 값(12)뿐 → §2.2 묶음 형식의 근거.

### 0.5 연속값 색을 쓰는 곳 전수 (개정 1 — 97a0e358 grep: `viridis|Blues|RdBu|DIVERGING|lerp|gradient|colorMap|heat|_SEQ|diverging|--seq|--pos|--neg|rgba(`)

| # | 곳 (파일:줄) | 값 | 지금 색 | 지금 뜻 |
|---|---|---|---|---|
| L1 | 결과 3D 표면 — `view3d/colors.ts:5`(BLUES9) → `scene.ts:205-244`, 범례 `LegendOverlay.tsx:47`·`View3DCard.tsx:466` | ‖u‖·면압(·새 C 기여도) | Blues 9 | 진할수록 큼 |
| L2 | 결과 3D 차이(새 — §4.3) | dc = 안 − 기준 | (새) | — |
| L3 | 3D 하중 영역 — `pages/doe/DoeStudy.tsx:864·932` `regionField` | **분류**(접촉 0.62~1.0·패치 0.2~0.42·밖 NaN)를 Blues 색표에 얹음 | Blues | 진한 파랑 접촉·옅은 파랑 패치 |
| L4 | 2D 변위 겹쳐 보기 — `components/DispOverlay.tsx:28·184` | 변위 크기(min~max) | viridis 10 | 노랑 = 큼 |
| L5 | ④ 검증 비교 2D ε — `components/FieldOverlay.tsx:38·338` | ε_eq(0~공통 최대) | viridis 10 | 노랑 = 큼 |
| L6 | ④ 검증 비교 2D 오차 — `FieldOverlay.tsx:36·336` | 오차 % (ESL − Radioss)/Radioss, ±R | 발산 7점(`lib/colormap.ts:8`) | 파랑 = 과소(−)·빨강 = 과대(+) |
| L7 | 라이브러리 셀 포락 지도 — `pages/library/common.tsx:200·210` | 셀 max\|F\|(0~최대) | viridis 10 | 노랑 = 큼 |
| L8 | 비드 설계 3D 높이 변화 — `view3d/part/adapters.ts:158`(`colorMap: "diverging"`) → `colors.ts:95-117`(RDBU11) | c = (x_d − x0)·n̂_b, **깊어짐 +**, ±V | RdBu 11 | **빨강 = 얕아짐(−)**·파랑 = 깊어짐(+) |
| L9 | 높이 변화 범례 — `components/BeadSelectCard.tsx:1533-1541` `HeightLegend`(미리보기 카드 `:1518`·`DoeThumbGrid.tsx:104`), 목 `mock/selectmock.ts:736` | 같음 | `DIVERGING_GRADIENT` | 문구 "빨강 = 얕아짐 · 파랑 = 깊어짐" |
| L10 | ESL별 개선율 표 칸 — `components/DoePerEslTable.tsx:16-20` `heatStyle`(문구 `:25`) | 개선율 1 − C_안/C_기준(부호 있음, 세기 \|x\|/0.5) | 초록·빨강 투명도 | 초록 = 개선·빨강 = 악화 |
| L11 | 비드 단(tier) 색 — `view3d/part/PartPlan.tsx:152`·`view3d/select/layers.ts:507` | **순서 단계**(단 번호) | 파랑 명도 단계 | 1 = 가장 진함 |
| L12 | 최적화 평면도 PNG `bead_map.png` — `esl/opt/png.py:18`(`_SEQ`)·`:59`·`:193`·`:225`, 호출 `esl/opt/post.py:128` | 비드 높이 \|h\|(0~vmax) | viridis 근사 5점 | 노랑 = 큼 |
| L13 | 비드 선택 썸네일 PNG — `esl/doe/select_render.py:22-33`(`diverging`)·`:196`, 범위 `stages.py:8528` `color{v_max, unit}` | L8 과 같은 c, ±V | 파랑·흰·빨강 3점 | **빨강 = 얕아짐(−)**·파랑 = 깊어짐(+) |
| L14 | Case 보고서 지도 ε — `esl/report/case_report.py:637`(JS `VIR`)·`:654` | ε(0~vmax) | viridis 10 | 노랑 = 큼 |
| L15 | Case 보고서 지도 오차 — `case_report.py:638`(JS `DIV`)·`:653` | 오차, ±errR | 발산 7점 | 파랑 = 과소·빨강 = 과대 |
| L16 | 보고서 격자 지도(순차) — `esl/library/report_analysis.py:226` `heatmap(mode="seq")`: 분석 보고서 `:577·639`, 버전 비교 `esl/library/compare.py:568`, 최적화 보고서 `esl/opt/report_opt.py:221` | 셀 포락 max\|F\|·비드 높이 \|h\|(0~최대) | 한 색(`--seq` 파랑) 투명도 | 진할수록 큼 |
| L17 | 보고서 격자 지도(발산) — `heatmap(mode="div")`: 모드 형상 `report_analysis.py:611`, 버전 차이 `compare.py:566`(문구 `:565`·`report_analysis.py:142`) | 부호 있는 값(모드 성분·신 − 구) | `--pos` 파랑·`--neg` 주황 투명도 | **파랑 = 증가(+)**·주황 = 감소(−) |
| L18 | 스터디 보고서 ESL별 개선율 칸 — `esl/doe/report_doe.py:54-61` `_ratio_cell` | L10 과 같음 | 초록·빨강 투명도 | 초록 = 개선·빨강 = 악화 |
| L19 | ① paicad 미리보기 썸네일 — `esl/doe/matrix.py:255` `thumb_options.colormap: "turbo16"` | 변위 크기 `disp_range_mm` | turbo 16(paicad 가 그림) | 파랑 = 작음·빨강 = 큼(이미 같은 방향) |

- 연속값 색이 **아닌 것**(대상 아님 — 확인만): 계열·상태 색(`--c1..8`·`--s1..4`·`--ok`·`--bad`·`--pass`·`--fail`, 민감도 막대 SRC 파랑·ρ 주황 `report_doe.py:85`), 세그먼트 12색(`select/graph.ts:210`), 강조 점·핀·경고선, 평면도 빗금·지지 기호(`png.py` 회색·주황·초록).
- matplotlib·d3-scale 사용 **없음**(파이썬 그림 = 순수 numpy PNG `esl/opt/png.py` + 손으로 쓴 SVG·inline JS).

---

## 1. 범위 · 비범위 · 용어

### 1.1 범위
- **A. 씬별 3D**: 3D 비교 대상(베이스라인 + 순위 상위 k)마다 **모든 낙하 씬(ESL 엔트리)** 의 3D 자료, 결과 화면 씬 선택 3곳 ↔ 3D 연결. 전 노드·지그(고정·변위·스프링·격자)·경계력·내력·④ 형상 비교·다른 메시 모두 **같은 규칙 한 벌**.
- **B. 컴플라이언스 표시**: 색 모드 `C 기여도`·`차이` 추가(기존 `응답 변위`·`하중` 유지), umax 위치 핀(두 카드), 씬 요약 한 줄(C·umax 기준 → 안).
- **C. 색·범례**: 연속값 색 **전부**(§5.7 표 19곳 중 16곳 적용·3곳 예외) = 레인보우(낮음 파랑 → 높음 빨강), 부호 있는 값 = 0 중심 발산(− 파랑 · + 빨강). 색 정점 원본 = `resources/colormaps.json` 한 곳, 읽는 모듈 = TS 1개·파이썬 1개(§5.8). 범례 편집(§5.3)은 결과 3D.
- **D. 호환**: 옛 결과·옛 view3d 자료로 화면이 깨지지 않음, 기존 결과 파일 바이트 불변.

### 1.2 비범위 (이번에 안 함)
| 항목 | 이유 | 후속 |
|---|---|---|
| 분류·순서 단계 색(하중 영역 L3·비드 단 L11)·paicad 가 그리는 ① 썸네일(L19) | 값의 크기 색이 아님 / 외부 엔진 그림(이미 파랑 → 빨강) — §5.7 예외 | — |
| 이미 저장된 그림(옛 보고서·옛 썸네일·옛 `bead_map.png`) 다시 만들기 | 옛 결과 바이트 불변 — 새로 만드는 것만 새 색(§5.9) | — |
| 2D·보고서·썸네일의 범례 편집(레벨 수·로그 등) | 범례 편집은 결과 3D 만(§5.3) — 색 의미 통일만 요청됨 | R-VL-6 |
| 순위 상위 k 밖 안의 3D | 지금도 없음(`view3d.top_k`) — 불변 | — |
| 변위 차이(Δ‖u‖)·변형 에너지 밀도 컨투어 | C 기여도·umax 핀으로 질문 2 에 답함 — 필수 아님 | R-VL-2 |
| 범례 설정 서버 저장(사용자 계정별) | 브라우저 기억으로 충분, DB migration 필요 | R-VL-3 |
| 요청 즉시 생성(API 프로세스 안 재풀이) | §2.1 결정 | — |

### 1.3 용어
| 화면 용어 | 뜻 | 내부 |
|---|---|---|
| 낙하 씬 | 스터디에 넣은 ESL 엔트리 1개 | `entry_id`, 순서 = 스냅샷 `doe.entries` |
| 자동(최악 ESL) | 선택 안의 그 탭 출처 순위 행 최악 엔트리 — 지금 동작 | `scene = null` |
| C 기여도 | 노드별 값 c_n, 합이 그 씬의 C | §3.1 |
| 차이 | 같은 씬에서 (안 − 기준) C 기여도, 합 = ΔC | §3.2 |
| umax 위치 | 표에 나오는 umax 값이 난 노드 | §3.3 |
| 씬 묶음 | (출처, 안) 한 쌍의 형상 1개 + 씬별 값 파일 | §2.2 |

---

## 2. A — 씬별 3D 자료

### 2.1 생성 정책 (D-0.25.1-VL-1) — **미리 생성: 3D 비교 대상 × 전 씬**

BD_POST 가 3D 비교 대상(베이스라인 + 상위 `view3d.top_k`)마다 모든 씬을 풀어 씬 묶음으로 쓴다.

| 안 | 내용 | 판정 |
|---|---|---|
| **미리 생성(채택)** | 안마다 인수분해는 지금도 1회 — 씬 추가는 후진대입만(추가 계산 작음). 씬을 고르면 **즉시** 바뀜 | 사용자 증상("선택해도 업데이트 안 돼")에 바로 답함. 용량은 §2.2 형식 + §2.4 한도로 막음 |
| 고를 때 요청 생성 | 재풀이가 필요해 API 프로세스에서 못 함 → 작업 큐(워커 기동·인수분해 수십 초~분), 권한 = 관리자·작성자뿐(`_regen_owner`) | 고를 때마다 기다림·조회 권한 사용자는 못 봄 — 기각 |
| 기존 폴더 형식으로 전 씬 | 형상 36 B/노드를 씬마다 중복 — 용량 3배 | 기각 |

옛 스터디·한도로 빠진 씬은 **기존 3D 다시 만들기 작업 경로**(§2.5)로 채운다(정책이 둘이 아님 — 같은 생성 함수의 보충 실행).

### 2.2 씬 묶음 형식 (새 파일만 — 기존 `post/view3d/**`·result.json 은 지금 그대로 계속 씀)

```
post/view3d_scene/<tag>/<did>/
  pack.json            # {schema "esl/view3d_scene/1", builder_version 1, key, src, did, n_nodes, n_elems, n_tris, bbox, plate_normal,
                       #  geometry{name, bytes}, lod|null, scenes[{entry_id, kk, manifest, values}], created_at}
  part.glb             # esl.view3d.write_glb 와 같은 바이트 규칙(같은 메시면 기존 <did>/part.glb 와 바이트 동일)
  part_lod.glb         # n_nodes > lod_min_nodes 일 때만 — 대표 정점 선택 값 p = 씬별 면압의 노드별 최댓값(결정적)
  e<kk>.json           # 씬 manifest = 기존 view3d manifest 키 전부 + 새 키(§2.3). geometry·lod 는 pack 것을 가리킴
  e<kk>.bin            # 기존 values.bin 배열(pa·fn·fmag·u) + c(int16) + dc(int16 — 베이스라인 묶음에는 없음)
post/scene_view.json   # 사이드카(§2.3)
```
- `<tag>` = 출처 꼬리표: 전 노드 `sv`, 그 밖은 기존 `v3d_tag`(jig·jd·js·bf·fi). `<did>` = `d000` 또는 안 id. `kk` = 스냅샷 엔트리 순번 2자리.
- 씬 e<kk>.bin 노드당: 베이스라인 14 B, 안 16 B.
- 양자화: c·dc = int16, 배율 = max|값|/32767(전부 0 이면 0) — 표시용. **합·핀 값은 manifest 의 float64 원값**(양자화 전).

### 2.3 씬 manifest 새 키 · 사이드카

씬 manifest(`e<kk>.json`) 추가 키(기존 키·뜻 불변):
```
"c":    {"kind": "fu" | "mixed", "sum": <Σc_n, float64>, "offset": <C_pe − sum, fu = 0.0>, "value": <per_esl 저장 C>,
         "parts": {"W_F": …, "W_v": …, "W_g": …}, "unit": "N·mm"},
"dc":   {"sum": <Σdc_n>, "base_sum": <기준 c.sum>, "map": "identity" | "grid", "cell_mm": <격자일 때>, "moved_rel": <격자일 때 §3.2>} | null,
"pins": {"umax": {"node_id", "vertex", "value", "kind": "ev" | "all" | "region" | "mask"}},
"ranges": {… 기존 …, "c": {"min", "max", "p01", "p99"}, "dc": {"abs_max", "abs_p99"} | null}
```
`values.arrays` 에 `{"key": "c"|"dc", "dtype": "int16", "comps": 1, "offset", "scale"}` 추가.

사이드카 `post/scene_view.json`(`esl/doe_scene_view/1`):
```
{"schema", "builder_version": 1, "source": "bd_post" | "regen", "created_at", "seconds",
 "entries": [{"entry_id", "kk"}],
 "packs": {"<src>": {"tag", "c_kind", "designs": {"<did>": {"dir": "<tag>/<did>", "scenes": ["<entry_id>", …]}},
                     "skipped": [{"did"?, "entry_id"?, "code": "SCENE_BUDGET" | "SCENE_FAILED" | "SCENE_NO_SOURCE", "detail"?}]}},
 "budget": {"max_mb", "est_mb", "n_scenes", "n_written"}, "warnings": []}
```
- `<src>` = 순위 보기 키(`full`·`jig`·`jig_disp`·`jig_spring`·`bforce`·`fint`) — 출처 표 `RANK_SOURCES` 행과 같은 키.
- result.json·ranking.csv·per_esl.json·jig_view.json·`post/view3d/**` 는 **바이트 불변**(시험 V-0251-10).

### 2.4 용량 한도 (D-0.25.1-VL-2 · **확정** D-0.25.1-VL-17: 스터디당 1 GB = `max_mb` 1024, 사용자 답 2026-11-27)
- 추정 = Σ_묶음 (36·N + E·16·N) + 씬 수 × 40 KB. `view3d.scene.max_mb`(기본 1024) 초과면: 씬을 **베이스라인 C 큰 순**(동률 = 엔트리 순번)으로 넣되 각 표시 안의 최악 ESL 은 항상 포함, 한도 안에서 들어가는 만큼만. 빠진 씬 = `skipped SCENE_BUDGET`(화면 안내 §4.4).
- 근거: 실제 스터디 크기에서 기본값으로는 한도에 닿지 않고(§8), 큰 메시·씬 50개에서만 디스크를 지킴.

### 2.5 옛 스터디·보충 — 기존 작업 경로 (D-0.25.1-VL-3)
- 새 작업 종류 없음: 기존 `DOE_RUN` 큐 + `post_mode: "scene"`(코어 dispatch 에 한 가지 추가, `resume = BD_POST`, DB 무변경, phase DONE 그대로 — `add_source` 와 같은 틀). 쓰는 것 = `post/view3d_scene/**`·`post/scene_view.json` 만.
- 멱등: 이미 있는 (묶음, 씬)은 다시 만들지 않음(pack.json `builder_version` 같을 때). 실패한 안·씬만 `SCENE_FAILED`(BD_POST·작업 실패 금지 — 기존 `VIEW3D_FAILED` 관례).
- 기존 `post_mode: "view3d"`(지그 3D 다시 만들기)도 끝에 같은 함수를 부른다(한 번 누르면 빠진 3D 가 모두 생김 — v0.24.6 §8.2 "빠진 것 모두" 관례).

### 2.6 공용 실행기·계획 표·독립성 (AGENTS.md)

| 모듈 | 내용 | import 허용 | import 금지 |
|---|---|---|---|
| ★`esl/mech/cfield.py`(순수) | `nodal_c(F, u3, bc=None, rc=None, fs=None) → {c, sum, W_F, W_v, W_g}` · `umax_pin(u3, mask=None) → {index, value}` · `conserve_map(c_src, X_src, X_dst, GF) → (c_dst, info)` · `diff(c_d, c_0_on_d) → dc` | numpy, `esl.mech.grid_map`(`grid_frame`·`vox_key` 만), `esl.errors` | `esl.doe`, `esl.view3d`, 파일 IO, 설정 해석, 시나리오·출처 이름 |
| `esl/view3d.py` | ★`build_scene_pack(out_dir, *, node_id, x0, conn, elem_type, scenes, cfg, key, src, did)` — `build_view` 의 내부 함수(`write_glb`·`pack_values`·`top_rows`·`clusters`) 재사용. `build_view` 출력 **바이트 불변** | numpy, 기존 | `esl.doe` |
| `esl/doe/stages.py` | ★`SCENE_SOURCES`(계획 표) + ★`_scene_packs(c, t, results, shown)`(실행기 1개) + 사이드카 쓰기. 기존 3D 함수는 "입력 얻기"와 "쓰기"를 나눠 실행기가 **같은 입력 함수**를 부름(메시·지지·하중 = 그 모드 실행 함수 — 별도 규칙 금지) | 기존 | — |

`SCENE_SOURCES` — 행 = 출처, 모든 열 필수(빈 칸 = 시험 실패). 호출부는 열만 읽음(출처 이름 분기 없음):

| key | tag | provider(메시·지지·하중·응답을 주는 기존 함수) | c_kind | C 키 | umax 핀 키(있으면 앞의 것) | 조건 |
|---|---|---|---|---|---|---|
| full | sv | `_view3d` 입력부(④ LT = `_lt_design`·`_cmp_design_mesh`) + `ev.evaluate(keep_u = 전 씬)` | fu | `C` | `umax_ev` → `umax` | 항상 |
| jig | jig | `_jig_v3d_build` 입력부(`_jig_resp_rows`) | BC 배열 있으면 mixed, 옛 npz = fu | `C_jig` | `umax_jig_ev` → `umax_jig` | 지그 계산됨 ∧ `view3d.jig` |
| jig_disp | jd | 같음(같은 메시) / `_jg_shape(keep_u)`(격자) | mixed | `C_jd` | `umax_jd_ev` → `umax_jd` | `_jig_src_ready`·`_jg_ready` |
| jig_spring | js | 같음 | mixed | `C_js` | `umax_js_ev` → `umax_js` | 같음 |
| bforce | bf | `_ns_view3d` 입력부 | fu | `C_bf` | `umax_bf_ev` → `umax_bf` | 출처 사이드카 있음 ∧ 설정 켬 |
| fint | fi | 같음 | fu | `C_fi` | `umax_fi_ev` → `umax_fi` | 같음 |

- provider 가 돌려주는 것(공통 모양): `mesh`, `support_rows`, `[(entry_id, F (N,3), u_raw (N,3), u_view (N,3), bc|None, rc|None, fs|None)]`, `ev_mask|None`, `frame`(공통 좌표 변환 — 차이 격자용).
- `u_raw` = 평가와 같은 풀이 변위(C·핀 계산용), `u_view` = 지금 화면에 쓰는 변위(`_sm_view_u` 강체 제거 등 — 기존 `u` 배열 그대로).
- 지그 변위·스프링은 `jig_bc.respond` 가 이미 돌려주는 `rc`·`fs` 를 버리지 않고 넘긴다(격자 경로 `_jg_shape(keep_u)` 반환에 `rc`·`fs` 추가 — 계산 불변).

---

## 3. B — 컴플라이언스 계산 (코어 한 곳 `esl/mech/cfield.py`)

### 3.1 C 기여도 (D-0.25.1-VL-4) — 노드 일(F·u) + 지지 일, 합 = C

```
c_n = F_n · u_n                                   (병진 3성분, u = u_raw)
      − Σ_{c: 지정 변위 행, 노드 n} v_c · r_c       (bc 있을 때 — jig_bc BC["bc_node"·"bc_val"], 반력 rc)
      − Σ_{s: 스프링 행, 노드 n} g_s · f_s          (BC["sp_node"·"sp_g"], 스프링 힘 fs)
```
| c_kind | 합 | 표의 C 와의 관계 | 검증(상대 1e-9) |
|---|---|---|---|
| fu(전 노드·경계력·내력·옛 지그 고정) | Σc = FᵀU | = per_esl `C`(·`C_jig`·`C_bf`·`C_fi`) — offset 0 | `|Σc − C| ≤ 1e-9·|C|` |
| mixed(지그 고정 BC·변위·스프링·격자) | Σc = C_mix(`mixed_compliance` 와 같은 값) | per_esl `C_<pe> = E_0 + (C_mix,d − C_mix,0)` → `offset = E_0 − C_mix,0`(평가 때 쓴 **같은 저장값** — 다시 계산 금지), `Σc + offset = C_<pe>` | `|Σc − C_mix| ≤ 1e-9·max(|W_F|,|W_g|)`, `|Σc + offset − C_<pe>| ≤ 1e-9·|C_<pe>|` |

- 선택 근거: (1) 합이 **모든 출처에서 정확히** 순위의 C(또는 그 차이)와 같다. (2) 저장 자료(F·u·BC·반력)만으로 나온다. (3) 요소 변형 에너지는 값 0 지지에서만 2U = C 이고 지정 변위·스프링에서는 2U_tot = E ≠ C_mix 라 "합 = C" 가 깨진다 → 기각(R-VL-2).
- 부호: 음수 가능(하중 반대 방향 변위·지지 일). 그대로 표시.
- 지정 변위·스프링 항은 그 지지 노드에 준다(`_dot_rows` 와 같은 행 → 노드 대응). 3-2-1 면내 보조 행은 v = 0 이라 기여 0.

### 3.2 차이 (D-0.25.1-VL-5) — 같은 씬, 안 − 기준, 합 = ΔC

```
dc_n = c^안_n − ĉ^기준_n          (안 메시 노드에 놓음)
```
| 메시 | ĉ^기준 | 합 |
|---|---|---|
| 노드 ID 배열이 같음(`np.array_equal`) | 노드 그대로(항등) — `map: identity` | Σdc = Σc^안 − Σc^기준 (부동소수 오차만) |
| 다름(④·다른 메시) | **보존 격자 사상** `conserve_map` — `map: grid` | 사상이 합을 보존 → Σdc = ΔC(상대 1e-9) |

- `conserve_map`: 두 메시를 같은 공통 좌표(그 모드 하중 전달·격자 지그가 쓰는 A 기준 프레임 — provider `frame`)에 놓고, v0.24.8 `grid_map.grid_frame`·`vox_key` 로 셀 키를 만든다. 기준 노드 값을 셀에 **더하고**(합 보존), 셀 값을 그 셀 안 안 노드에 **똑같이 나눈다**. 안 노드가 없는 셀은 가장 가까운 안 노드 1개에 준다(`moved_rel` = 그렇게 옮긴 |값| 합 / 전체 |값| 합 — 정보). 결정적(정렬 키·동률 = 작은 인덱스).
- 셀 크기 = max(`rank.jig_grid.cell_mm`, `view3d.scene.diff_cell_h_mult` × 안 메시 변 길이 중앙값) — 셀에 노드가 1개도 안 드는 얼룩을 줄임.
- 재사용 범위: 격자 좌표계·셀 키만. `sample_field`(변위 보간)·tie 골격은 쓰지 않는다 — 보간은 합을 보존하지 않아 "합 = ΔC" 가 깨짐.
- 공통 좌표를 못 얻으면 `dc = null` + `skipped`/경고 `SCENE_DIFF_NO_FRAME`(화면: 차이 버튼 비활성 + 사유).
- ΔC 와 표: `Σdc = C^안_<pe> − C^기준_<pe>`(mixed 도 offset 이 상쇄되어 성립).

### 3.3 umax 위치 핀 (D-0.25.1-VL-6)
- 핀 = **순위·ESL 표가 보여 주는 umax 값이 난 노드**. `umax_pin(u_raw, mask)` — mask·u 는 평가와 같은 것: 평가 영역(`umax_ev` 가 있는 스냅샷) → `kind: ev`, 없으면 그 출처의 umax 정의(전 노드 `all` / 선택 step 영역 `region` / 지그 `umax_mask` `mask`).
- 값 = 같은 배열·같은 함수(`ev.umax_in` 규칙)로 계산 → per_esl 저장값과 **같아야 함**(V-0251-7). 동률 = 가장 작은 인덱스.
- 핀은 "지금 칠한 값의 최대 표식"(v0.24.6)과 다른 것: 색 모드가 무엇이든 같은 자리.

### 3.4 모드별 계획 (요약)

| 모드 | 메시(안 vs 기준) | 씬 묶음 | C 기여도 | 차이 사상 |
|---|---|---|---|---|
| ① same · select(같은 메시) | 같음 | ○ | fu / mixed | identity |
| ② mesh · select(B 메시) | 안끼리 같음(기준과 노드 ID 같으면 identity) | ○ | 같음 | 노드 ID 비교로 판정 |
| ③ step(옛·새) | 다를 수 있음 | ○ | 같음 | 판정 → grid |
| ④ compare(LT) | 다름 | ○(기준 = `_lt_design` 같은 하중) | 같음 | grid |
| 격자 지그(④·옛 ③) | 다름 | ○(`_jg_shape`) | mixed | grid |

판정은 "노드 ID 배열이 같은가" 한 가지(모드 이름 분기 없음).

---

## 4. 화면 — 강성 스터디 결과 (`DoeStudy.tsx` `Compare3D`·`DoePerEslTable`·`DoeRanking`)

### 4.1 씬 선택 (D-0.25.1-VL-7)
- 상태 `scene: string | null`(결과 화면 한 곳, `pick` 옆). `null` = 자동(최악 ESL) = 지금 동작.
- 선택 지점 3곳 — 모두 같은 상태:

| 곳 | 동작 |
|---|---|
| 3D 바 `낙하 씬` 선택 칸(새 select 1개, `aria-label="3D 낙하 씬"`) | 첫 항목 `자동 — 최악 ESL(<라벨>)`, 이어서 엔트리 순서대로 라벨. 자료 없는 씬은 꼬리표 ` · 자료 없음`(고를 수 있음 → §4.4) |
| ESL별 개선율 표 | 열 머리(ESL) 클릭 = 그 씬. 셀 클릭 = 그 안 + 그 씬. 선택 열 강조. 선택된 열 머리를 다시 누르면 자동 |
| 순위표 `최악 ESL` 칸 | 클릭 = 그 안 + 그 씬(칸은 버튼 역할 — 키보드 Enter) |

- 씬을 직접 고르면 안을 바꿔도 **그 씬 유지**(같은 씬에서 안끼리 비교). 하중 정의 탭을 바꿔도 유지(엔트리는 같음). 스터디가 바뀌면 자동으로.
- 두 카드 = 같은 씬의 기준(d000)과 안. 제목 꼬리 ` · ESL <라벨>` 그대로, 조건 문구의 "(선택 형상의 최악)" → 직접 고른 씬이면 "(선택한 씬)".
- 자료 고르는 순서: 씬 묶음(사이드카에 있음) → 없고 자동이면 **기존 폴더**(`view3d`·`view3d_ref`·`pairKeys` — 지금 그대로) → 없으면 §4.4.
- 재현 진단·지그 진단 세그먼트의 엔트리 선택 칸은 그대로(다른 자료) — 기본값만 `scene` 을 따른다.

### 4.2 3D 바 배치 (새 줄 없음 — 2560·1920 높이 증가 0)
```
[비교 안 ▾] [낙하 씬 ▾] [설계 비교|지그 진단] [응답 변위|하중|C 기여도|차이] <씬 요약 한 줄 … 말줄임>
```
- 새 요소 = 선택 칸 1개 + 색 버튼 2개. 기존 조건 문구·설명 문구는 **한 줄 말줄임**(`flex: 1 1 0; min-width: 0`, 전문은 `title`) — 정보 삭제 없음, 줄 수 불변.
- 높이: 1920×1080(1열 배치)·2560×1440 모두 3D 바 1줄 유지 → 카드·칸 높이 변화 0 px(시험 V-0251-29 가 측정).

### 4.3 색 모드 · 씬 요약 (질문 2 의 답)

| 버튼 | 색 값 | 색 지도 | 자동 범위(두 카드 같음) | 범례 문구 |
|---|---|---|---|---|
| 응답 변위(기존) | ‖u‖ | 레인보우 | 0 ~ 두 카드 최대 | 지금 문구 그대로 |
| 하중(기존) | 면압 \|Fn\|/A | 레인보우 | 0 ~ p99 | 그대로 |
| **C 기여도** | c_n | 레인보우 | [min(p01, 0), max(p99, 0)] 두 카드 포함 | `C 기여도 F·u (N·mm) — 합 = C` |
| **차이** | 안 카드 = dc_n · 기준 카드 = 기준 c_n(참고) | 안 = 발산(0 중심) · 기준 = 레인보우 | 안 = ±abs_p99 | `C 기여도 차이 안 − 기준 (N·mm) — 합 = ΔC` |

- 차이 모드에서 기준 카드 제목 꼬리 ` — 기준 C 기여도(참고)`. 두 카드의 값이 달라 범위·범례 동기는 이 모드에서만 끔(계획 표 열 — §5.4).
- 씬 요약(바 오른쪽 한 줄, 모든 색 모드): `ESL <라벨> · C 기준 <C0> → 안 <Cd> (<±x %>) · umax 기준 <u0> → 안 <ud> (<±y %>) mm`. 값 = 순위·ESL 표와 같은 per_esl 값(씬 manifest `c.value`·`pins.umax.value`). C 가 좋아지고 umax 가 늘었으면 그대로 두 숫자가 나란히 보인다.
- `C 기여도`·`차이` 버튼 `title`: "C = Σ F·u — 하중이 한 일. 하중이 큰 곳의 변위가 줄면 C 가 좋아집니다. umax 는 한 점의 최대 변위라 하중이 작은 곳에서 늘 수 있습니다 — 핀이 그 위치입니다."
- **umax 핀**: 두 카드에 핀 기호 + 라벨 `umax <값> mm @N <노드 ID>`(변형 형상 켜면 변형 위치). ⚙ 설정 `umax 위치`(기본 켬, 계획 표 층 `upin`). 최대 표식과 같은 정점이면 최대 표식 라벨을 숨김(겹침 방지).
- 탐침(클릭) 정보 줄에 C 기여도·차이 값 추가(있을 때).

### 4.4 자료 없음 안내 (옛 결과 포함)
| 상황 | 화면 |
|---|---|
| 사이드카 없음(옛 스터디) + 씬 = 자동 | **지금 화면 그대로**(기존 폴더) — `C 기여도`·`차이` 비활성, title "이 3D 자료에는 C 기여도가 없습니다 — 씬 3D 를 만들면 볼 수 있습니다" |
| 고른 씬의 자료 없음 | 3D 칸 자리에 `ESL <라벨> 의 3D 자료가 없습니다` + 버튼 **[씬 3D 만들기]**(관리자·작성자만 — 그 밖은 "관리자 또는 스터디 작성자가 만들 수 있습니다"). 화면에 버튼 최대 1개(D-0.24.1-V3D-9 유지) |
| 한도로 빠짐(`SCENE_BUDGET`) | `… 저장 한도(설정 view3d.scene.max_mb)로 만들지 않았습니다` + 같은 버튼(한도는 그대로라 다시 빠질 수 있음을 title 로) |
| 그 안만 실패(`SCENE_FAILED`) | `… 3D 를 만들지 못했습니다(<코드>)` |
| 작업 대기·실행 중 | 버튼 비활성 "만드는 중…" — 끝나면 결과 다시 읽기(기존 `onRegen`) |

---

## 5. C — 색 지도(모든 연속값 색) · 범례 편집(결과 3D)

### 5.1 적용 대상
- **색 지도**(§5.2·§5.7·§5.8): 연속값 색을 쓰는 모든 곳 — 프런트 3D·2D·표·썸네일 범례, 파이썬이 만드는 PNG·보고서(§5.7 표).
- **범례 편집**(§5.3~§5.6): `View3DCard` 를 쓰는 보기 전부 = 계획 표 `VIEWER_PLANS` 5행(case_load·case_disp·study_design·study_jigdiag·study_recon): Case ③ 3D, 스터디 설계 비교, 지그 진단, 재현 진단. 한 곳(§5.5)만 고치면 모두 바뀐다.

### 5.2 색 지도 (D-0.25.1-VL-8 · 개정 1 D-0.25.1-VL-13·14) — 정점 원본 = `resources/colormaps.json`(§5.8)
| 이름 | 정의 | 쓰임 |
|---|---|---|
| `rainbow` | sRGB 정점 5개 선형 보간: t 0 파랑(0,0,255) → 0.25 청록(0,255,255) → 0.5 초록(0,255,0) → 0.75 노랑(255,255,0) → 1 빨강(255,0,0). **낮음 = 파랑, 높음 = 빨강** | 크기·양(부호 없는 값, 또는 0 이 특별하지 않은 값) — 순차 |
| `diverge` | 기존 RdBu 11 을 **뒤집은 순서**: −V 파랑(5,48,97) → 0 흰색(247,247,247) → +V 빨강(103,0,31). t = 0.5 + v/(2V) | **부호 있는 값 전부**(0 중심, 범위 대칭 ±V) — **값이 클수록(+) 빨강** |
| `blues` | 기존 Blues 9 그대로 | **분류 표시 전용**(하중 영역 L3) — 값 컨투어에 쓰지 않음 |
| NaN(계산 불가) | 회색(154,161,171) — 지금 그대로 | — |
| 범위 밖(선택) | 짙은 회색(90,96,106) | §5.3 |

- 기존 Blues 는 값 컨투어에서 쓰지 않는다(분류 L3 만). `colors.ts` 의 `BLUES9`·`RDBU11`·`LUT_*`·`*_GRADIENT`, `lib/colormap.ts` 의 `VIRIDIS`·`DIVERGING` 상수는 **없앤다** — 정점은 자원 파일에서만 온다(§5.8). (개정 전 "RDBU11 은 그대로" 는 폐기 — 비드 높이 변화도 `diverge`.)
- **부호 규칙(모든 곳 공통)**: 화면·보고서가 말하는 값 정의 그대로 **+ = 빨강, − = 파랑**. 값 정의의 부호를 색에 맞추려고 뒤집지 않는다 — 뜻이 뒤집히는 곳은 범례 문구를 바꾼다(§5.7 `문구` 열).
- 띠(레벨) 색 = 띠 중앙값의 색(지금 규칙 `bandT`). 셰이더는 색표 텍스처만 바꿔 끼운다(GPU 경로 유지).

### 5.3 범례 편집 — 넣는 것 / 안 넣는 것 (D-0.25.1-VL-9)

| HyperView 범례 기능 | 판정 | 내용 |
|---|---|---|
| 레벨 수 | **넣음** | 2~20 숫자 칸 + `연속` 체크. **기본 9**(지금 기본 연속 → 변경) |
| 최대·최소 값 | **넣음** | 각각 자동/직접 입력(지금 최대만 → 최소 추가). [자동] 으로 되돌림 |
| 선형/로그 | **넣음** | 로그는 값이 양수인 모드(변위·하중)만 — 최소가 0 이하면 최소 = 최대/10^`logDecades`(기본 3). 부호 있는 모드(C 기여도·차이)에서는 비활성 + 사유 |
| 숫자 형식 | **넣음** | 자동(지금 유효 4자리) · 고정 · 지수 + 자릿수 0~6(기본 3) |
| 최대·최소 표시 | **넣음** | 최대 표식(기존) + **최소 표식** 체크(기본 끔). 범례 아래 `최대 v @N id` · `최소 v @N id` |
| 범위 밖 값 색 | **넣음** | `끝색`(기본 — 지금 동작) · `회색`. ▲▼ 개수는 그대로 |
| 색 순서 뒤집기 | **넣음** | 체크(기본 끔 = 높음 빨강) |
| 두 카드 범례 맞춤 | **넣음** | 쌍 보기는 범례 설정·범위를 항상 공유(`useViewerSync` 확장 — 지금 레벨만). 끄는 버튼 없음(필수 아님) |
| 설정 기억 | **넣음** | 이 브라우저(§5.6). 서버 저장 없음 |
| 범례 위치·크기 옮기기 | 안 넣음 | 왼쪽 위 고정(v0.24.6) — 3D 칸을 가리지 않게 이미 맞춤 |
| 글꼴·글자색·배경 | 안 넣음 | 필수 아님 |
| 띠별 색·경계값 직접 지정, 사용자 색 지도 파일 | 안 넣음 | 유연성 기능 — 레벨 수·범위로 충분 |
| 색 지도 종류 고르기 | 안 넣음 | 레인보우 한 가지(사용자 결정) — 색각 보정 지도는 R-VL-4 |
| 머리말·꼬리말 문구 편집 | 안 넣음 | 제목 = 값 이름·단위 자동 |
| 평균 방식·결과 종류 고르기 | 안 넣음 | 값은 서버가 정함 |
| 범례 설정 파일 저장·불러오기 | 안 넣음 | 브라우저 기억으로 대체 |

### 5.4 범례 화면
- 겹침 범례(왼쪽 위)는 **항상 표시**(연속이면 매끄러운 띠 + 눈금 5개). 범례를 **클릭**하면 `범례 편집` 팝오버(⚙ 팝오버의 `범례` 절과 같은 컴포넌트 — 진입 2곳, 내용 1개). 새 막대 버튼 없음 → 높이 영향 0.
- 팝오버 항목(위에서 아래): `레벨 [9] □연속` · `최대 [자동|값]` · `최소 [자동|값]` · `눈금 (선형|로그)` · `숫자 (자동|고정|지수) 자릿수 [3]` · `범위 밖 (끝색|회색)` · `□색 순서 뒤집기` · `□최대 표식 □최소 표식 □umax 위치` · `[기본값으로]` · "이 브라우저에 기억됩니다". Esc·바깥 클릭 닫힘(기존 팝오버 규칙).
- 도구 줄의 기존 범위 입력(`ColorLegend`)은 그대로 두고 같은 상태를 본다(정보·조작 삭제 없음).
- 계획 표 `VIEWER_PLANS` 열 추가(모든 행 필수): `layers` 에 `upin`(핀 자료가 있는 보기만 의미), `legendSync: "pair" | "none"`(study_* = pair). 색 모드 표 `COLOR_MODES`(한 곳): 행 = 모드(disp·load·c·dc·field) × 열 `role`(자원 `roles` 키 — seq|div|region)·`signed`·`logOk`·`sym`·`pairRange`(차이 = false). 행 `region`(하중 영역 L3) 추가 — role `region`, 범례 편집 비활성(분류).

### 5.5 공용 모듈 (프런트 — 새 = ★)
| 파일 | 내용 | 금지 |
|---|---|---|
| `lib/colormap.ts`(기존 파일 — **TS 쪽 색 지도 모듈 1개**, §5.8. 개정 전 `view3d/legend/colormaps.ts` 는 만들지 않음) | `mapFor(role)`·`srgb(map, t)`·`css(map, t)`·`cssGradient(map, {reversed, levels})`·`buildLut(map, {reversed, linear})`·`special(name)` + 기존 `f3` | three·api·React import, RGB 숫자 리터럴(정점) |
| ★`view3d/legend/legendModel.ts` | 순수 함수: `toT(v, range, scale)`(선형·로그)·`ticks`·`formatValue(fmt, digits)`·`countOut`·`effectiveRange`(로그 최소 보정)·`COLOR_MODES`·`LEGEND_DEFAULTS` | 같음 |
| ★`view3d/legend/legendPrefs.ts` | 읽기·쓰기·v1 이행(§5.6) | three |
| ★`view3d/legend/LegendEditor.tsx` | 팝오버 내용 | three |
| `LegendOverlay.tsx`·`ViewerControls.tsx`·`View3DCard.tsx`·`viewerPlan.ts`·`viewerSync.ts`·`scene.ts`·`colors.ts`·`values.ts`·`marks.ts`·`part/*`(`colorMap` 값 = 자원 역할 이름) | 위 모듈만 사용하도록 고침. `scene.ts` uniform 추가 `uLog`·`uOutMode`·`uOutColor`(범례 변경 = uniform·색표 교체만). `colors.ts` 는 색표 보조(`normalize`·`bandT`·`srgbToLinear`·`luminance`)만 남김 | 정점 상수(`BLUES9`·`RDBU11` 등)·`bluesSrgb`·`BLUES_GRADIENT`·`DIVERGING_GRADIENT` |

표시 기본값(`LEGEND_DEFAULTS` = {levels 9, scale linear, format auto, digits 3, out clamp, reversed false, minMark false, upin true, logDecades 3})은 **이 표 한 곳**(v0.24.6 `VIEWER_PLANS` 관례 — 프런트 표시 기본은 서버 설정이 아님, D-0.25.1-VL-10).

### 5.6 기억 (D-0.25.1-VL-10)
- `localStorage["esl.v3d.viewer.v2"]` = `{ "legend": {levels, continuous, scale, format, digits, out, reversed, minMark, upin}, "<planKey>": {bc, load, ghost, marks} }`. **범례 모양은 모든 3D 보기 공통 1벌**(보기마다 따로 맞추지 않게), 층 켬·끔은 지금처럼 보기별.
- v1 → v2: 처음 읽을 때 v1 의 planKey 별 bc·load·ghost·marks 를 옮기고, levels 는 버린다(새 기본 9). v1 키는 지우지 않음(이전 버전으로 되돌려도 동작).
- 범위 직접 입력값·로그 선택은 **기억하지 않음**(값 종류·씬마다 뜻이 달라 다음에 잘못 적용됨 — 화면을 떠나면 자동).
- 형식 오류·저장소 없음 = 기본값(오류 표시 없음 — 기존 규칙).

### 5.7 색 적용 위치 확정 표 (개정 1, D-0.25.1-VL-13·14·15·16) — 번호 = §0.5

| # | 곳 | 값 뜻(큰 값이) | 부호 | **지도** | 범위 | 범례 문구(바뀌면 **굵게**) | 묶음 |
|---|---|---|---|---|---|---|---|
| L1 | 결과 3D 값(변위·하중·C 기여도) | 큼 = 나쁨(변위)·중립(하중·기여도) | 없음(C 기여도는 음수 가능 — 0 이 중심 아님) | `rainbow` | §4.3 | §4.3 | F1a |
| L2 | 결과 3D 차이 dc | + = 나빠짐(C 증가) | 있음 | `diverge` | ±abs_p99 | §4.3 | F1a |
| L3 | 3D 하중 영역 | 분류(접촉·패치) | — | **예외** `blues`(분류) | 0~1 고정 | 그대로("진한 파랑 접촉 · 옅은 파랑 패치") | F1a(색표)·F1b(문구 불변) |
| L4 | 2D 변위 겹쳐 보기 | 큼 = 나쁨 | 없음 | `rainbow` | 지금 그대로(min~max) | 값 이름 그대로 | F1c |
| L5 | ④ 검증 비교 2D ε_eq | 큼 = 나쁨 | 없음 | `rainbow` | 그대로 | 그대로 | F1c |
| L6 | ④ 검증 비교 2D 오차 % | + = 과대 | 있음 | `diverge` | ±R 그대로 | 그대로(이미 파랑 과소·빨강 과대) — 가운데 색만 노랑 → 흰 | F1c |
| L7 | 라이브러리 셀 포락 max\|F\| | 큼 = 하중 큼 | 없음 | `rainbow` | 0~최대 | 그대로 | F1c |
| L8 | 비드 설계 3D 높이 변화 | + = 깊어짐(중립) | 있음 | `diverge` — **뜻 뒤집힘** | ±V 그대로 | (범례 = L9) | F1a |
| L9 | 높이 변화 범례 `HeightLegend` + 목 썸네일 | 같음 | 있음 | `diverge` | ±V | **"빨강 = 깊어짐 · 파랑 = 얕아짐"**(왼쪽 −V 파랑 → 오른쪽 +V 빨강). 옛 썸네일(`color.map` 없음 — §5.9)은 옛 띠·옛 문구 "빨강 = 얕아짐 · 파랑 = 깊어짐" | F1c |
| L10 | ESL별 개선율 표 칸 | 색 값 = **C 변화율** C_안/C_기준 − 1(= −개선율): + = 악화 | 있음 | `diverge` | ±0.5(지금 세기 기준 그대로 — `PER_ESL_HEAT_SPAN` 한 곳) | 칸 숫자는 개선율 그대로. 표 설명 **"파랑 개선(C 감소) · 빨강 악화(C 증가)"** | F1b |
| L11 | 비드 단 색 | 순서 단계 | — | **예외**(그대로) | — | 그대로 | — |
| L12 | `bead_map.png` 비드 높이 \|h\| | 큼 = 높음 | 없음 | `rainbow` | 0~vmax 그대로 | PNG 안 색 막대(숫자 그대로) | C2 |
| L13 | 비드 선택 썸네일 PNG | + = 깊어짐 | 있음 | `diverge` — **뜻 뒤집힘** | ±V | L9 + manifest `color.map: "diverge"`(§5.9) | C2 |
| L14 | Case 보고서 지도 ε | 큼 = 나쁨 | 없음 | `rainbow` | 그대로 | 그대로 | C2 |
| L15 | Case 보고서 지도 오차 | + = 과대 | 있음 | `diverge` | ±errR | 그대로 | C2 |
| L16 | 보고서 격자 지도(순차) | 큼 = 큼 | 없음 | `rainbow`(투명도 → 불투명 색) | 0~최대 | 색 막대 그대로(0 … 최대) | C2 |
| L17 | 보고서 격자 지도(발산) | + = 증가 | 있음 | `diverge` — **뜻 뒤집힘** | ±최대 | **"차이 = 신 − 구 (빨강 증가, 파랑 감소)"**(`compare.py:565`)·**"빨강 = 늘어남, 파랑 = 줄어듦"**(`report_analysis.py:142`) | C2 |
| L18 | 스터디 보고서 개선율 칸 | L10 과 같음 | 있음 | `diverge` | ±0.5 | 표 머리 설명 L10 과 같은 문구 | C2 |
| L19 | paicad ① 썸네일(`turbo16`) | 큼 = 큼 | 없음 | **예외**(외부 엔진 — 정점은 못 맞춤, 방향은 이미 파랑 → 빨강) | — | 그대로 | — |

요약: **19곳 = 순차 7(L1·4·5·7·12·14·16) + 발산 9(L2·6·8·9·10·13·15·17·18) + 예외 3(L3·11·19)**. 뜻이 뒤집히는 곳 = L8·L9·L13(높이 변화: 빨강 = 얕아짐 → **빨강 = 깊어짐**), L17(파랑 = 증가 → **빨강 = 증가**), L10·L18(초록 = 개선 → **파랑 = 개선**, 빨강 = 악화는 그대로).

- 순차/발산 판정 규칙(새 곳이 생겨도 같은 규칙): 값 정의에 부호가 있고 0 이 "변화 없음·오차 없음" 이면 `diverge`(범위 ±V 대칭), 그 밖은 `rainbow`. C 기여도처럼 음수가 나올 수 있어도 0 이 기준점이 아니면 `rainbow`.
- L10·L18 은 색에 쓰는 값만 C 변화율로 바꾼다(3D `차이` 와 같은 뜻 — 파랑 = C 감소 = 개선). 표에 적는 숫자·정렬·`per_esl.json` 은 불변.
- 문서 문구(통합 때 메인): `docs/manual/user.md:307`(썸네일 "파랑 깊어짐·빨강 얕아짐" → 반대)·`docs/manual/bead_doe_check.md:91`("깊어짐 파랑" → "깊어짐 빨강").

### 5.8 색 지도 공용 자원 · 읽는 모듈 (D-0.25.1-VL-14) — 정의 한 곳

`resources/colormaps.json`(새 — **아래 내용 그대로**, 원본 1곳. 기존 `resources/doe_messages.json` 과 같은 읽기 관례):
```json
{
  "schema": "esl/colormaps/1",
  "interp": "srgb-linear",
  "maps": {
    "rainbow": {"kind": "seq", "stops": [[0,0,255],[0,255,255],[0,255,0],[255,255,0],[255,0,0]],
                "check": "3ccedddc80e5c02cae9b0bd7932fbadd3d94ebf77d7da56ee46b30e0c2ffa74a"},
    "diverge": {"kind": "div", "center": 0.5,
                "stops": [[5,48,97],[33,102,172],[67,147,195],[146,197,222],[209,229,240],[247,247,247],[253,219,199],[244,165,130],[214,96,77],[178,24,43],[103,0,31]],
                "check": "30ef5f031ef175840578d6c6df9182497fb061db9b3b731d1c2afd081620237c"},
    "blues":   {"kind": "class", "stops": [[247,251,255],[222,235,247],[198,219,239],[158,202,225],[107,174,214],[66,146,198],[33,113,181],[8,81,156],[8,48,107]],
                "check": "8cd7426282dd1ba6dd6674e855af43d958f33fff292392fbd378d8af97eb15e6"}
  },
  "roles": {"seq": "rainbow", "div": "diverge", "region": "blues"},
  "special": {"nan": [154,161,171], "out": [90,96,106], "none": [200,200,200]},
  "text": {"dark_lum": 0.179, "on_dark": [255,255,255], "on_light": [26,30,36]}
}
```
- (통합 INT-5) `text` = 색 칸 위 글자 대비: 배경 상대 휘도(WCAG 2) < `dark_lum` 이면 `on_dark`(흰), 아니면 `on_light`. 0.179 = 흰·검정 글자 대비가 같아지는 휘도(√(1.05·0.05) − 0.05). 읽는 곳 = 같은 두 모듈(TS `relLuminance`·`textOn`, 파이썬 `luminance`·`text_on`) — 필수 블록(없거나 형식 오류 = 파이썬 `CONFIG_INVALID`·TS 빌드 시험 실패). 지도 `check` 와 무관.
- 정점 = 같은 간격(i/(n−1)). `kind: div` 는 `center`(0.5) 에 정점이 있어야 함(정점 수 홀수 — 읽을 때 검사).
- **보간 규칙(TS·파이썬 같은 식 — 반올림까지)**: `s = t·(n−1)`(t 를 [0,1] 로 자름, NaN = 0), `i = min(floor(s), n−2)`, `f = s − i`, 채널 `= floor(a + (b − a)·f + 0.5)`. (파이썬 `round` 는 짝수 반올림이라 쓰지 않음.)
- `check` = t = k/255(k = 0…255) 256색 × RGB uint8 768바이트의 sha256 — 두 언어 모듈이 각자 계산해 이 값과 같아야 함(V-0251-38). 정점을 바꾸면 `check` 도 같이 바꿈.
- `roles` = 호출부가 쓰는 이름(seq·div·region). 호출부는 **역할**로 고르고 지도 이름·정점을 적지 않는다 → 나중에 지도를 바꿔도 자원 1줄.
- `special`: nan = 계산 불가, out = 범위 밖(§5.3 회색), none = 영향 없음(썸네일 회색 — 지금 `select_render.GRAY`).

| 쪽 | 모듈(1개씩) | 읽는 법 | 내보냄 | 금지 |
|---|---|---|---|---|
| TS | `frontend/src/lib/colormap.ts`(기존 파일을 바꿈) | `import CM from "../../../resources/colormaps.json"`(빌드에 포함 — 기존 `mock/graphmock.ts:9` 와 같은 방식, `resolveJsonModule`) | §5.5 표 | 다른 TS 파일이 자원을 직접 import, RGB 정점 리터럴 |
| 파이썬 | ★`esl/io/colormaps.py`(순수 — `esl/io/messages.py` 옆, 같은 `RESOURCES` 경로 규칙) | 처음 쓸 때 1회 읽고 검사(스키마·정점 수·`center`) — 실패 = `CONFIG_INVALID` | `map_for(role)`·`rgb(map, t) → (…, 3) uint8`(numpy 배열 입력)·`css(map, t) → "rgb(r,g,b)"`·`table(map, n=256)`·`special(name)`·`as_json(roles)`(보고서 JS 에 넣을 정점 묶음) | `esl.doe`·`esl.view3d` import, 정점 리터럴 |

- 파이썬 호출부: `esl/opt/png.py`(`_SEQ` 삭제 → `rgb(map_for("seq"), …)`), `esl/doe/select_render.py`(`BLUE`·`RED`·`WHITE`·`GRAY` 삭제 → div·`special("none")`), `esl/report/case_report.py`(JS 의 `VIR`·`DIV` 리터럴 삭제 → 보고서 데이터 JSON 에 `as_json` 을 넣고 JS 는 그것을 읽음 — 보고서는 지금처럼 파일 1개로 독립), `esl/library/report_analysis.py` `heatmap`(칸·색 막대 `fill` = `css(…)`, 투명도 램프 삭제. `--seq`·`--pos`·`--neg` 변수는 선 그래프용으로 남김), `esl/doe/report_doe.py` `_ratio_cell`.
- 배포: `resources/` 는 지금도 코어·백엔드가 읽는 폴더 — ~~설치 스크립트 변경 없음~~ → **(통합 INT-3) 설치·묶음 스크립트의 자원 목록이 파일별이라 추가 필요**: `deploy/install-common.ps1` `$EslAppItems`·`collect-offline.ps1`·`collect-offline.sh` 에 `resources/colormaps.json`, 시험 `tests/deploy/test_bead_doe_deploy.py`·`test_deploy_collect.py`(V-0251-37). 빠지면 서버에서 `bead_map.png`·썸네일·보고서가 `CONFIG_INVALID`.
- 어두운 화면(보고서 `prefers-color-scheme`): 지도 색은 밝은·어두운 화면 같은 값(값 ↔ 색 대응이 바뀌면 안 됨).

### 5.9 옛 산출물 · 새 산출물 (D-0.25.1-VL-15)

| 산출물 | 옛 결과(이미 저장됨) | 새로 만드는 것 |
|---|---|---|
| `report.html`(Case·스터디·최적화·라이브러리 분석·버전 비교) | **다시 만들지 않음** — 파일 그대로(옛 색·옛 문구가 파일 안에 같이 있어 스스로 맞음) | 새 색·새 문구 |
| `bead_map.png` | 그대로(색 막대가 그림 안에 있음) | 새 색 |
| 비드 선택 썸네일 PNG | 그대로 — 화면 범례가 따로라 **표지 필요**: manifest `color` 에 `map` 키 없음 = 옛 그림 → 범례를 옛 띠(`diverge` 뒤집기)·옛 문구로 | manifest `color: {v_max, unit, map: "diverge"}` → 새 범례 |
| 프런트가 그리는 것(3D·2D·표) | 옛 결과를 열어도 **새 색**(자료는 값이고 색은 화면이 칠함) | 새 색 |

- **옛 결과 바이트 불변 원칙과 충돌 없음**: 저장된 파일을 고치거나 다시 쓰지 않는다. 바뀌는 것은 "v0.25.1 로 **새로 실행·생성**한 그림의 바이트" 뿐 — §7.2 의 "같은 입력 → 같은 바이트" 목록에서 그림 3종(`report.html`·`bead_map.png`·썸네일 PNG)은 뺀다(V-0251-10 개정, 색 외 내용 불변은 V-0251-43).
- 썸네일 표지: `select_render.color_meta() → {"map": <div 역할의 지도 이름>}` 를 `stages.py:8528` 의 `color` dict 에 합친다(1줄 — 통합 때 메인, §10). API 는 `preview.color` 를 지금도 dict 그대로 넘김(스키마 변경 없음), `types.ts` `color?: {v_max; unit; map?: string}`. (통합 INT-2·INT-6: 넣음 — `bd_select_grid` manifest `color = {v_max, unit, **sr.color_meta()}`, 시험 `test_select_stage_flow` `map == "diverge"`. 화면 옛 판별 = `map` 키 없음(`DoeThumbGrid` `legacy = !color.map` — 지도 이름 비교 없음, 캐스트 제거).)
- **(통합 INT-4) 바이트 골든 목록 보충**: 아래 갱신 목록 밖의 "같은 입력 → 같은 바이트" 골든 19건이 새로 만든 `report.html` 만 달라 실패(다른 파일은 바이트 동일 — C2 확인) — V-0251-10 개정과 같은 뜻으로 그 시험들의 바이트 비교 집합에서 `report.html` 을 뺌(파일 목록 단언·다른 파일 바이트 비교는 그대로, 골든 다시 기록 없음): `tests/cumulative/test_cumulative_e2e.py::test_b1_noncumulative_outputs_identical_to_v072`, `tests/doe/test_jig_grid_golden.py::test_old_snapshot_bytes`(3), `tests/doe/test_jig_move.py::test_v0244_jig_1_golden_bytes`(study·case_old_plan — 의도 차이 목록 `CASE_PLAN_CHANGED` 단언은 불변), `tests/doe/test_pos_u_golden.py`(4), `tests/doe/test_vbead_golden.py::test_no_virtual_beads_bytes`(6), `tests/pipeline/test_validate_sources.py::test_v0243_val_1_golden_full_bytes`. 보고서가 시험 주제인 `tests/pipeline/test_validate_tiers.py` V-0245-VT-6·VT-8(3)은 빼지 않고 Case 보고서 색 코드만 v0.25.0 글자로 되돌려(`vt_compat.back_color_v0250` — 데이터 JSON `cmap` 삭제 + JS 색 줄 되돌림, 새 색 코드가 정확히 한 번씩 있어야 함) 옛 골든과 **바이트 비교 유지**(통과 = Case 보고서의 차이가 색 코드뿐).
- 골든 갱신 범위(아래 중 색 값·그림 바이트·색 문구를 실제로 고정한 단언만 — 계산·표 숫자 골든은 건드리지 않음): `tests/doe/test_select_render.py`·`tests/opt/test_post.py`(PNG 색·바이트), `tests/report/test_case_report.py`·`tests/doe/test_report_doe.py`·`tests/library/test_analysis.py`·`test_compare.py`·`tests/library/golden/**`(색 문자열·범례 문구), `tests/fake_paicad.py`(썸네일 색을 본다면), 프런트 `__tests__/view3d.test.ts`·`doe.test.tsx`·`doe_select.test.tsx`·`select_save_vars.test.tsx`(색·문구 단언). `tests/test_view3d_golden.py`(view3d 자료)는 **불변**(색이 파일에 없음).

---

## 6. 데이터 계약 — API (고정 필드명 `schemas.py` ↔ `api/types.ts`, `check:api`)

| 메서드·경로 | 내용 | 오류 |
|---|---|---|
| `GET /doe/studies/{sid}/results`(기존) | 응답에 선택 키 `scene_view`(사이드카 요약 — 아래) · `scene_add: {ok: bool, blocked: str|null}` 추가. 사이드카 없음 = `scene_view: null` | 기존 그대로 |
| ★`GET /doe/studies/{sid}/view3d-scene/{src}/{did}/{entry_id}/manifest.json` | 씬 manifest(`View3dOut` + 선택 키 `c`·`dc`·`pins`·`ranges.c`·`ranges.dc`) + `geometry_url`·`lod_url`·`values_url` | 404 `VIEW3D_SCENE_NOT_FOUND`(src·did·entry 형식 오류, 묶음·씬 없음, 링크) |
| ★`GET /doe/studies/{sid}/view3d-scene/{src}/{did}/{name}` | 파일(`part.glb`·`part_lod.glb`·`e<kk>.bin`) — 이름은 pack.json 에 적힌 것만, 경로 고정·링크 거부(`safe_case_file`) | 404 같음 |
| ★`POST /doe/studies/{sid}/view3d/scenes` | 씬 3D 만들기(§2.5) — 202 `DoeStudyOut`. 권한·막힘 규칙 = 기존 `_regen_owner`·`_regen_block` | 403 · 409 `JOB_ACTIVE` · 409 `VIEW3D_SCENE_UNAVAILABLE`(끝나지 않은 스터디·성공한 실행 없음·설정 끔) |

`scene_view` 응답 모양(고정):
```
{"entries": [{"entry_id", "kk"}],
 "packs": {"<src>": {"c_kind": "fu"|"mixed", "designs": {"<did>": ["<entry_id>", …]},
                     "skipped": [{"did": str|null, "entry_id": str|null, "code": str, "text": str}]}},
 "budget": {"max_mb": number, "est_mb": number}}
```
- `src` = 화이트리스트(출처 표 키), `did` = 기존 `DID_RE`, `entry_id` = 스냅샷 엔트리에 있는 것만 → 서버가 `kk` 로 바꿈(클라이언트는 파일 이름을 만들지 않음).
- 권한: 읽기 = 스터디 조회 권한(기존 `_viewable`), 만들기 = 실행 권한 ∧ (관리자 ∨ 작성자).
- OpenAPI: `View3dOut` 선택 필드·새 스키마 `DoeSceneViewOut`·`DoeSceneAddOut`·새 경로 3개를 `schemas.py` 에 선언(`response_model`) — 생성 OpenAPI 와 `types.ts` 가 `check:api` 로 일치. `skipped.text` 문구 원본 = `resources/doe_messages.json`(새 코드 `SCENE_BUDGET`·`SCENE_FAILED`·`SCENE_NO_SOURCE`·`SCENE_DIFF_NO_FRAME` + B1 추가 `SCENE_VIEW_INVALID`·`SCENE_UNAVAILABLE_DISABLED`). B1 구현이 이 절과 다르게 한 점 = §15.1(그쪽이 우선).

---

## 7. 설정 · 해시 · 하위 호환

### 7.1 설정 `bead_doe.view3d.scene`(4곳 같은 이름 — 코어 `esl/doe/__init__.py` DEFAULTS · pydantic `BeadDoeView3dCfg` 안 새 `BeadDoeView3dSceneCfg` · `config/esl_platform.example.yaml` · `.prod.example.yaml`)

| 키 | 기본 | 범위 | 뜻 |
|---|---|---|---|
| `enabled` | true | bool | 끄면 씬 묶음·사이드카를 만들지 않음(= v0.25.0 과 같은 파일 집합) |
| `max_mb` | 1024(**확정** — 사용자 결정 2026-11-27, D-0.25.1-VL-17) | 0~65536 | 스터디당 씬 묶음 추정 용량 한도(§2.4). 0 = 한도 없음 |
| `diff_cell_h_mult` | 2.0 | 0.5~8 | 차이 격자 셀 = max(`rank.jig_grid.cell_mm`, 이 값 × 변 길이 중앙값) |

- 해시 밖: `view3d` 블록은 지금도 `_cfg_hash` 에 없음 → `input_sha256`·이어하기 캐시 불변(V-0251-12). 스냅샷에 넣지 않음(보기 설정 — 실행 시점 설정 사용).

### 7.2 하위 호환
| 대상 | 동작 |
|---|---|
| 옛 스터디(사이드카 없음) | 결과 화면 = 지금과 같음 + 씬 선택 칸(자동만 자료 있음) + 안내·[씬 3D 만들기](§4.4). API `scene_view: null` |
| 옛 view3d 폴더(c 배열 없음) | 그대로 읽힘(프런트는 모르는 배열 키 무시 — 지금 규칙). C 기여도·차이 비활성 + 사유 |
| 옛 프런트 캐시 + 새 서버 | 새 키는 모두 선택 키 — 옛 화면 동작 불변 |
| 기존 파일 | **저장된 옛 결과 파일은 어떤 것도 다시 쓰지 않음.** 같은 입력으로 새로 실행하면 result.json·ranking.csv·per_esl.json·jig_view.json·bforce/fint 사이드카·`post/view3d/**` **바이트 불변**(시간 키 제외 — 기존 골든 규칙). 그림 3종(report.html·`bead_map.png`·비드 선택 썸네일 PNG + 그 manifest `color.map`)은 **새 실행에서 색·범례 문구만 바뀜**(§5.9 — 개정 1). 새 파일 = `post/view3d_scene/**`·`post/scene_view.json` 만 |
| 결과 받기(zip) | 새 폴더는 묶음에 **넣지 않음**(보기 파생 자료 — 용량). 기존 묶음 목록 불변 |
| 스터디 삭제·복제 | 삭제 = 스터디 폴더째(기존). 복제 = 사본에 씬 묶음 없음(실행하면 생김) |
| SPDM·입력 폴더 | 쓰기 없음 — 모든 쓰기는 `c.writer`(스터디 `post/` 안, 기존 guard) |
| 브라우저 기억 | v1 → v2 이행(§5.6) |

---

## 8. 성능 · 저장 용량 (추정 — 구현 때 실측해 §15 에 기록)

가정: 사각형 위주 메시(요소 수 ≈ 노드 수), 상위 k = 3(+ 베이스라인 = 묶음 4개), 출처 3개(전 노드 + 지그 변위 + 지그 스프링 — v0.24.5 기본 방식), 씬 manifest 40 KB.

| 노드 N | 씬 E | 지금(v0.25.0, 출처 3 — 폴더 약 5~7개/출처 × 48·N) | **씬 묶음(채택)** = 3 × [4 × 36·N + (E·14·N + 3·E·16·N) + 4·E·40 KB] | 기존 폴더 형식으로 전 씬(기각) | 요청 생성(기각) |
|---|---|---|---|---|---|
| 3만 | 6 | 22~30 MB | ≈ **50 MB** | 104 MB | 0(고를 때마다 +) |
| 10만 | 8 | 72~100 MB | ≈ **195 MB** | 461 MB | 0 |
| 30만 | 8 | 216~302 MB | ≈ **580 MB** | 1.38 GB | 0 |
| 30만 | 20 | 같음 | ≈ **1.25 GB → 한도 1024 MB 로 일부 씬 생략** | 3.5 GB | 0 |

- 기준 메시 크기는 뷰어 성능 목표(30만 노드, `esl_viewer_hv.md` §5)와 낙하 메시 부품 크기 범위로 잡았다 — 실제 스터디 1개(현장)에서 재서 확정(E-0251-9).
- BD_POST 시간: 안당 인수분해 수는 **불변**(출처마다 지금도 1회). 추가 = 씬당 후진대입 1회 + 파일 쓰기. 추정 씬당 0.3~1 s(10만~30만 노드) → 4 묶음 × 8 씬 × 3 출처 ≈ 0.5~1.5 분. 사이드카 `seconds` 로 기록, BD_POST 진행 문구 `[bd_post scene] <src> <n>/<총>`.
- 메모리: 씬 변위를 한꺼번에 들지 않고 씬 단위로 풀고 쓴다(지금 `keep_u` 전 씬 = N×3×8 B×E — 30만·20씬 144 MB 는 허용하되 격자 지그는 형상 단위로 해제).
- 화면: 씬 전환 = 값 파일(14~16 B/노드) + manifest 만 새로 받음 — 형상(`part.glb`)은 같은 묶음이라 **다시 받지 않음**(URL 같음 → 브라우저 캐시). 10만 노드 1.6 MB.
- 범례 편집 = uniform·색표(256칸) 교체만 — CPU 정점 루프 없음(30만 노드에서도 1프레임). 색 모드 전환 = 정점 값 버퍼 1개 다시 올림(기존 경로).
- 조회 API 는 재풀이 없음(파일 읽기만) — 기존 Case `VIEW3D_BUSY` 세마포어와 무관.

---

## 9. 시험 (V-0251-n)

### 9.1 물리·코어
| # | 내용 | 기준 |
|---|---|---|
| 1 | `nodal_c` fu: 합성 평판 + 3-2-1, 여러 씬 | `|Σc − FᵀU| ≤ 1e-9·|C|`, = `ev.evaluate` per_esl C |
| 2 | mixed 지정 변위(지그 변위) | `Σc = mixed_compliance.C_mix`(상대 1e-9), `Σc + offset = per_esl C_jd`(1e-9) |
| 3 | mixed 스프링(바닥 g ≠ 0 포함) | 같음(`C_js`) |
| 4 | 옛 지그 고정(BC 배열 없는 npz) | `Σc = C_jig`(1e-9) |
| 5 | 차이 같은 메시 | `dc == c_d − c_0`(비트 동일), `|Σdc − (C_d − C_0)| ≤ 1e-9·max(|C_d|,|C_0|)` — fu·mixed 각각 |
| 6 | 차이 다른 메시(`conserve_map`) | 사상 전후 합 상대 1e-12, `Σdc = ΔC` 1e-9, 같은 메시를 넣으면 identity 와 같은 합, 두 번 실행 바이트 동일(결정성), 빈 셀 → 최근접·`moved_rel` 기록 |
| 7 | umax 핀 | 값 == per_esl `umax_ev`(없으면 그 출처 umax) **같은 값**(==), 핀 노드 ∈ 평가 영역, 동률 = 작은 인덱스, 출처 6행 모두 |
| 8 | 양자화 | 복원 오차 ≤ scale/2, manifest `c.sum` = 양자화 전 float64 |
| 9 | `build_view` 불변 | 기존 골든(`tests/test_view3d_golden.py`) 그대로 통과, 씬 묶음 `part.glb` == 같은 메시 `build_view` 의 `part.glb` 바이트 |
| 10 | 기존 파일 바이트 불변 | main 97a0e358 과 같은 입력으로 ① same·select·③ step·④ compare(LT)·격자 지그: §7.2 목록 파일 바이트 동일(시간 키 제외 — 개정 1: 그림 3종 report.html·`bead_map.png`·썸네일 PNG·manifest `color.map` 은 목록에서 빼고 V-0251-43 이 봄), 새 파일은 `post/view3d_scene/**`·`post/scene_view.json` 뿐 |
| 11 | 한도 | `max_mb` 작게 → 베이스라인 C 큰 순·각 안 최악 포함·`SCENE_BUDGET` 기록·`budget` 값 |
| 12 | 보충 실행(post_mode scene) | 옛 스터디 사본: 새 파일만 생김, 두 번째 실행은 다시 쓰지 않음, `input_sha256`·이어하기 캐시 적중, 기존 `post_mode view3d` 도 씬 묶음을 만듦 |
| 13 | `enabled: false` | 새 파일 0(파일 집합 = main) |
| 14 | 독립성(정적) | `cfield.py` import = numpy·`esl.mech.grid_map`·`esl.errors` 뿐, `esl.doe`·`esl.view3d`·`open(` 없음. `SCENE_SOURCES` 모든 열 채움, 호출부에 출처 이름 문자열 분기 없음 |
| 15 | 설정 4곳 | 이름·기본값 일치, 범위 밖 = `CONFIG_INVALID` |

### 9.2 백엔드
| # | 내용 |
|---|---|
| 16 | `results.scene_view`: 사이드카 → 요약, 없음 = null, 깨진 사이드카 = null + 경고(500 아님) |
| 17 | 씬 manifest·파일: URL, src 화이트리스트·did 정규식·엔트리 검증, 링크·경로 탈출 거부, 404 코드 |
| 18 | `POST …/view3d/scenes`: 202·작업 params(`post_mode scene`, resume BD_POST)·403·409 `JOB_ACTIVE`·409 `VIEW3D_SCENE_UNAVAILABLE` |
| 19 | 고정 필드: `schemas.py` ↔ `types.ts` `check:api`, OpenAPI 에 새 경로 3개·스키마 |

### 9.3 프런트 단위
| # | 내용 |
|---|---|
| 20 | 레인보우: t 0·0.25·0.5·0.75·1 = 파랑·청록·초록·노랑·빨강(정확한 RGB — 기대값은 자원 파일에서 읽음), 띠 색 = 띠 중앙, 뒤집기, 선형 색표 변환 |
| 21 | 발산: 0 = 흰색, −V 파랑·+V 빨강, 대칭 |
| 22 | `legendModel`: 선형·로그 `toT`, 로그 최소 보정·부호 모드 비활성, 눈금, 숫자 형식(자동·고정·지수 × 자릿수), 범위 밖 끝색/회색·개수 |
| 23 | 기억: v1 → v2 이행, 깨진 JSON = 기본값, 범위·로그는 저장 안 함 |
| 24 | 쌍 동기: 한 카드에서 범례 편집 → 상대 카드 같은 값. 차이 모드 = 범위 따로 |
| 25 | 씬 연결: 3D 바 선택 칸·ESL 표 열 머리·셀·순위표 최악 ESL 칸 → 두 카드가 요청하는 URL 의 씬이 바뀜, 자동 = 선택 안의 최악, 직접 고른 씬은 안을 바꿔도 유지, 출처 탭 6종 같은 규칙 |
| 26 | 옛 결과: `scene_view` null → 자동일 때 DOM·요청 URL 이 v0.25.0 과 같음. 자료 없는 씬 → 안내 + 버튼(작성자)/문구만(조회자) |
| 27 | C 기여도·차이 비활성 사유(배열 없음·`dc` null) |
| 28 | umax 핀: 라벨·두 카드·끄기·최대 표식과 같은 정점일 때 겹침 규칙 |
| 29 | 높이: 2560×1440·1920×1080 에서 3D 바 1줄, 3D 칸·카드 높이 = v0.25.0(픽셀 차 0), 범례 팝오버는 겹침(레이아웃 영향 0) |
| 30 | 공용 확인(정적): `frontend/src/view3d/**` 에 `bluesSrgb`·`BLUES_GRADIENT`·`BLUES9`·`RDBU11`·`DIVERGING_GRADIENT` 없음(Blues 는 `COLOR_MODES` 행 `region` 의 role 로만), `VIEWER_PLANS`·`COLOR_MODES` 모든 열 채움 |
| 31 | 성능: 범례 편집 때 `fillVertexColors`(CPU 루프) 호출 0, 30만 정점 mock |
| 32 | 옛 view3d 자료(`tests/fixtures/view3d/small`) 렌더 — c 없음 |

### 9.4 e2e
| # | 내용 |
|---|---|
| 33 | 합성 스터디 실행 → 결과에서 씬을 차례로 선택: 두 카드 제목·`data-esl`·씬 요약이 바뀌고 요약의 C·umax == ESL 표 값. 전 노드·지그 변위·지그 스프링 탭 |
| 34 | ④ 형상 비교(다른 메시): 씬 전환 + 차이 모드(`map grid`) 표시, `Σdc` 표시값 == 표 ΔC |
| 35 | 옛 결과 회귀: v0.25.0 으로 만든 스터디 폴더를 그대로 열어 화면 정상 → [씬 3D 만들기] → 끝난 뒤 씬 전환 동작, 기존 파일 해시 불변 |
| 36 | Case ③ 3D·지그 진단·재현 진단이 레인보우·같은 범례 편집(공용 확인) |

### 9.5 색 통일 (개정 1)
| # | 묶음 | 내용 | 기준 |
|---|---|---|---|
| 37 | C2·F1a | **자원 하나에서 읽음(정적)**: 저장소 전체에서 색 정점을 가진 곳 = `resources/colormaps.json` 뿐. 파이썬 `esl/**`·`backend/**`·`worker/**` 에 `_SEQ`·`VIR=`·`DIV=`·`BLUE =`·`RED =`·viridis 정점 리터럴 없음, 자원을 여는 곳 = `esl/io/colormaps.py` 1개. TS `frontend/src/**`(시험·목 제외) 에 `VIRIDIS`·`DIVERGING`·`BLUES9`·`RDBU11` 없음, `colormaps.json` import = `lib/colormap.ts` 1개 | grep 0건 / 1건. 배포 묶음 목록에 `resources/colormaps.json` 있음 |
| 38 | C2·F1a | **정점 일치 TS = 파이썬**: 각 모듈이 `table(map, 256)` 768바이트 sha256 을 계산 → 자원의 `check` 와 같음(지도 3개 × 언어 2개). 같은 `check` 를 두 쪽이 통과 = 두 쪽 색이 바이트로 같음 | == |
| 39 | C2·F1a | 보간 규칙: t = 0·0.5·1 정확한 정점, `diverge` t 0.5 = (247,247,247), 범위 밖 t 자름, NaN = t 0, 반올림 = floor(x + 0.5)(경계값 x.5 사례 포함), `kind div` 인데 정점 짝수·`center` 없음 = 파이썬 `CONFIG_INVALID`·TS 는 빌드 시험 실패 | 값 일치 |
| 40 | F1a | 비드 설계 3D 높이 변화(L8): c > 0(깊어짐) 정점 = 빨강 쪽, c < 0 = 파랑 쪽, 0 = 흰. `part/*` 의 `colorMap` 이 역할 이름 | 색표 값 |
| 41 | F1c | 2D(L4·L5·L7): 최소값 칸 = `rainbow` t 0(파랑), 최대값 칸 = t 1(빨강), 범례 띠 = `cssGradient(seq)`. L6 오차: −R 파랑·0 흰·+R 빨강, 범례 문구 불변 | fill·style 값 |
| 42 | F1c | 높이 변화 범례(L9): `color.map == "diverge"` → 띠 왼쪽 −V 파랑·오른쪽 +V 빨강, 문구 "빨강 = 깊어짐 · 파랑 = 얕아짐". `color.map` 없음(옛 썸네일) → 옛 띠·문구 "빨강 = 얕아짐 · 파랑 = 깊어짐". 미리보기 카드·`DoeThumbGrid` 둘 다. 목 썸네일 색 = 새 뜻 | DOM 문구·띠 |
| 43 | C2 | 파이썬 그림 **색만 바뀜**: 썸네일 PNG — c > 0 삼각형 픽셀 = 빨강 쪽(R > B), c < 0 = 파랑 쪽, 영향 없음 = `special none` 음영, 크기·시점·경계선 픽셀은 main 과 같음. `bead_map.png` — 값 0 칸 = 파랑·vmax 칸 = 빨강, 색 막대 위 = 빨강, 빗금·기호·글자 픽셀 main 과 같음. 두 번 실행 바이트 동일(결정성). `color_meta()` = `{"map": "diverge"}` | 픽셀 비교 |
| 44 | C2 | 보고서: Case 보고서 데이터 JSON 에 정점 묶음이 있고 JS 본문에 정점 리터럴 없음, ε = seq·오차 = div. 격자 지도 `heatmap` seq = 최소 칸 파랑·최대 칸 빨강(투명도 램프 없음), div = + 빨강·− 파랑·0 흰, 색 막대 같은 지도. 문구 "빨강 증가, 파랑 감소"·"빨강 = 늘어남, 파랑 = 줄어듦". 색·문구 밖의 HTML(표 숫자·구조)은 main 과 같음(색 문자열을 지운 뒤 비교) | 문자열 |
| 45 | C2·F1b | ESL별 개선율 칸(L10·L18): 개선(C 감소) = 파랑 쪽·악화 = 빨강 쪽·0 = 무색, 세기 기준 ±0.5, 화면과 보고서가 **같은 색**(같은 입력 → 같은 rgb — 자원 `check` 경유), 칸 숫자 불변, 설명 문구 "파랑 개선(C 감소) · 빨강 악화(C 증가)" | 색·문구 |
| 46 | F1a·F1b | 하중 영역(L3): 색 = `blues`(v0.25.0 과 같은 색), 문구 불변, 범례 편집 비활성 | 색표 값 |
| 47 | 통합 | 옛 결과 회귀: v0.25.0 으로 만든 스터디·Case 폴더를 열어 화면 정상(3D·2D 새 색, 옛 썸네일 + 옛 범례), **폴더 안 파일 해시 불변**(report.html·PNG 포함 — 다시 만들지 않음) | 해시 |
| 48 | 통합(e2e) | 화면 범례 문구 한 바퀴: Case ③ 3D·④ 검증 비교 2D(ε·오차)·변위 겹쳐 보기·라이브러리 포락·비드 미리보기 썸네일·설계 3D·스터디 결과 ESL 표 — 각 화면에서 가장 큰 값 칸이 빨강 쪽·가장 작은 값이 파랑 쪽이고 범례 문구가 §5.7 과 같음 | 화면별 1 단언 |

---

## 10. 구현 분할 (파일 소유 겹침 없음 — 병행 후 통합)

| 묶음 | 모델 | 소유 파일 | 내용 | 시험 |
|---|---|---|---|---|
| **C1 코어**(진행 중 — 범위 **불변**) | opus | `esl/mech/cfield.py`(새) · `esl/view3d.py` · `esl/doe/stages.py` · `esl/doe/__init__.py`(DEFAULTS) · `tests/**` 중 씬·cfield·view3d 시험 | §2·§3·§7.1 코어 기본값. 기존 3D 함수의 입력부 분리(바이트 불변), 실행기·계획 표·사이드카, post_mode scene. **색 작업 없음** | 1~15 |
| **C2 파이썬 그림 색**(새 — C1 과 파일 겹침 0) | sonnet | ★`esl/io/colormaps.py` · `esl/opt/png.py` · `esl/doe/select_render.py` · `esl/report/case_report.py` · `esl/library/report_analysis.py` · `esl/library/compare.py`(문구) · `esl/doe/report_doe.py` · 그 시험(`tests/io/test_colormaps.py` 새 · §5.9 골든 목록의 파이썬 쪽) | §5.7 L12~L18 · §5.8 파이썬 모듈 · §5.9. `stages.py`·`esl/view3d.py`·`esl/opt/post.py`·`report_opt.py` 는 **안 건드림**(호출 모양 불변 — `heatmap`·`render_plan`·`render` 인수 그대로) | 37~39(파이썬 쪽)·43·44·45(보고서 쪽) |
| **B1 백엔드** | sonnet | `backend/esl_platform/**`(config pydantic·services/doe.py·routers/doe.py·schemas.py) · `config/*.yaml` 2개 · `resources/doe_messages.json` · `backend/tests/**` · OpenAPI 스냅샷 | §6·§7.1 거울. C1 의 사이드카·묶음 **형식(§2.2·§2.3)만** 읽음 — 코어 함수 호출 없음 | 16~19 |
| **F1a 프런트 공용 뷰어 + 색 모듈** | sonnet | `frontend/src/lib/colormap.ts` · `frontend/src/view3d/**`(legend/* 새 3개 — `legendModel`·`legendPrefs`·`LegendEditor`, `part/*` 포함) · `components/ColorLegend.tsx` · 뷰어 스타일 · 해당 단위 시험(`view3d.test.ts` 등) | §5.2~§5.6 + §5.8 TS 모듈 + L1·L2·L3(색표)·L8 + 색 모드 c·dc·umax 핀 그리기(`View3DOptions` 확장). `lib/colormap.ts` 에서 `VIRIDIS`·`DIVERGING` 을 없애므로 **F1c 가 쓰는 새 내보내기(§5.5)를 먼저 올림** — 옛 상수는 F1c 병합 때까지 `@deprecated` 로 남겨도 됨(통합 때 V-0251-37 이 0건 확인) | 20~24·28·30~32·36·37~39(TS 쪽)·40·46(색표) |
| **F1b 프런트 스터디 화면** | sonnet | `frontend/src/pages/doe/**` · `components/DoePerEslTable.tsx`·`DoeRanking.tsx` · `api/types.ts`·`api/doe.ts` · e2e · `__tests__/doe.test.tsx` | §4 — 씬 상태·선택 3곳·3D 바·요약·안내. F1a 가 정한 `View3DOptions` 만 사용. + L10(개선율 칸 색·설명 문구) · `types.ts` `color.map?` | 25~27·29·33~35·45(화면 쪽)·46(문구) |
| **F1c 프런트 2D·썸네일 색**(새 — F1a 의 `lib/colormap.ts` 새 내보내기가 올라온 뒤) | sonnet | `components/DispOverlay.tsx` · `components/FieldOverlay.tsx` · `components/BeadSelectCard.tsx`(`HeightLegend` 와 그 호출부만) · `components/DoeThumbGrid.tsx` · `pages/library/common.tsx` · `mock/selectmock.ts` · `__tests__/doe_select.test.tsx`·`select_save_vars.test.tsx` 와 2D 시험 | L4~L7·L9 — 상수 `VIRIDIS`·`DIVERGING`·`DIVERGING_GRADIENT` 사용을 `lib/colormap.ts` 역할 호출로 바꿈, 높이 변화 범례 문구·옛 썸네일 분기 | 41·42 |

- 접점(먼저 고정 — 이 문서가 원본): C1↔B1 = §2.2·§2.3 파일 형식(+ §15.1), B1↔F1b = §6 응답 키, F1a↔F1b = `View3DOptions` 새 선택 키 `colorMode: "disp"|"load"|"c"|"dc"`·`pins`·`legendSync`. F1a 는 F1b 보다 먼저 접점 타입을 올린다. **C2↔F1a = `resources/colormaps.json`(§5.8 내용 그대로)**, F1a↔F1c = `lib/colormap.ts` 내보내기(§5.5), C2↔F1c = manifest `color.map`(§5.9).
- **선행 커밋(메인, 구현 전에 `release/v0.25.1` 에)**: `resources/colormaps.json` 을 §5.8 내용 그대로 1개 커밋 — C2·F1a 가 같은 파일을 각자 만들지 않게(두 묶음 다 **읽기만**, 정점을 바꿔야 하면 계약 개정).
- 순서: 선행 커밋 → {C1(진행 중) ∥ C2 ∥ F1a} → {F1b ∥ F1c}. 파일 소유 겹침 0: `stages.py` = C1 만, `lib/colormap.ts`·`view3d/**` = F1a 만, `BeadSelectCard.tsx`·`DoeThumbGrid.tsx` = F1c 만, `DoePerEslTable.tsx`·`pages/doe/**`·`types.ts` = F1b 만. B1 = 완료(색 작업 없음 — `preview.color` 는 dict 통과).
- 통합(메인): `VERSION`·`CHANGELOG.md`·`docs/e2e-checklist.md`(§11 항목)·사용자 매뉴얼 한 절 + §5.7 문서 문구 2곳, 독립 검증(불변 시험 10·물리 1~7 재실행 + 37·38·47·48). **`stages.py:8528` 1줄**(`color` 에 `select_render.color_meta()` 합치기)은 C1·C2 병합 뒤 메인이 넣음(C1 작업 중 파일이라 C2 가 건드리지 않음) — 빠지면 새 썸네일에 옛 범례가 붙음(V-0251-42·43 이 잡음).

---

## 11. 현장 확인표 항목 (E-0251-n — 배포 뒤 `docs/e2e-checklist.md` 에 옮김)

| # | 확인 |
|---|---|
| 1 | 강성 스터디 결과에서 3D 바 `낙하 씬` 을 바꾸면 기준·안 두 그림이 그 씬으로 바뀌는가(전 노드·지그 변위·지그 스프링 탭 각각) |
| 2 | ESL별 개선율 표의 열 머리·칸, 순위표 `최악 ESL` 칸을 눌러도 같은가. 안을 바꿔도 고른 씬이 유지되는가 |
| 3 | 씬 요약의 C·umax 숫자가 순위표·ESL 표와 같은가 |
| 4 | `C 기여도`: 하중이 큰 자리가 빨강, 범례 제목의 합 = C. `차이`: 좋아진 자리 파랑·나빠진 자리 빨강, 합 = ΔC |
| 5 | umax 핀이 두 그림에 보이고, C 는 좋아졌는데 umax 가 는 안에서 핀 자리가 하중이 작은 곳인지 눈으로 확인 |
| 6 | 색: 높은 값 빨강·낮은 값 파랑(Case ③ 3D·스터디·지그 진단·재현 진단 모두) |
| 7 | 범례 편집: 레벨 수·최대·최소·로그·숫자 형식·범위 밖 회색·뒤집기가 두 그림에 같이 적용되고, 새로 고침 뒤에도 남는가 |
| 8 | v0.25.0 이전에 만든 스터디: 화면이 그대로 열리고, [씬 3D 만들기] 뒤 씬 전환이 되는가. 기존 결과 받기(zip) 내용이 달라지지 않는가 |
| 9 | 실제 스터디 1개의 `post/view3d_scene` 폴더 크기·BD_POST 추가 시간(사이드카 `seconds`)을 적어 §8 추정과 비교 |
| 10 | 2560×1440·1920×1080 에서 결과 화면 세로 길이가 늘지 않았는가(3D 바 1줄) |
| 11 | ④ 형상 비교(다른 메시)에서 차이 그림이 나오고 얼룩이 심하지 않은가(심하면 `diff_cell_h_mult` 조정) |
| 12 | (개정 1) ④ 검증 비교 2D·변위 겹쳐 보기·라이브러리 포락: 큰 값 빨강·작은 값 파랑, 오차는 과소 파랑·과대 빨강 |
| 13 | (개정 1) 비드 미리보기 썸네일·설계 3D: **깊어진 곳 빨강·얕아진 곳 파랑**, 범례 문구가 그렇게 적혀 있는가. v0.25.0 때 만든 미리보기를 열면 옛 그림 + 옛 문구(빨강 = 얕아짐)로 서로 맞는가 |
| 14 | (개정 1) 새로 만든 보고서(Case·스터디·최적화·라이브러리)·`bead_map.png` 가 같은 색 규칙인가. ESL별 개선율 표: 개선 파랑·악화 빨강(화면 = 보고서). 예전에 만든 보고서 파일은 그대로인가 |

---

## 12. 결정 근거 (요약 — 전문 `docs/decisions.md` 2026-11-27 D-0.25.1-VL-1~19)

| # | 결정 | 근거 1줄 |
|---|---|---|
| VL-1 | 씬 3D = 상위 k × 전 씬 미리 생성 | 인수분해는 이미 안당 1회라 추가 계산이 작고, 고르는 즉시 바뀌어야 증상이 풀림 |
| VL-2 | 씬 묶음 형식(형상 1 + 씬별 값) + `max_mb` 한도 | 형상 36 B/노드를 씬마다 중복하지 않아 용량 약 1/3 |
| VL-3 | 옛 스터디·빠진 씬 = 기존 작업 큐 `post_mode scene` | 재풀이는 API 프로세스에서 하지 않음, 새 작업 종류·DB 변경 없음 |
| VL-4 | C 기여도 = 노드 F·u − 지정 변위·스프링 지지 일 | 모든 출처에서 합이 순위의 C(C_mix)와 정확히 같음 — 요소 에너지는 지정 변위·스프링에서 깨짐 |
| VL-5 | 차이 = 안 − 기준, 다른 메시는 보존 격자 사상(격자 좌표·셀 키만 v0.24.8 재사용) | 보간은 합을 보존하지 않음 — "합 = ΔC" 를 지킴 |
| VL-6 | umax 핀 = 표의 umax 가 난 노드(평가 영역 우선) | 표 숫자와 그림 위치가 같아야 질문 2 에 답이 됨 |
| VL-7 | 씬 상태 1개, 선택 3곳, 직접 고른 씬은 안을 바꿔도 유지 | 같은 씬에서 안끼리 비교가 목적 |
| VL-8 | 레인보우(파랑 → 빨강), 차이 = 파랑 − / 흰 0 / 빨강 + | 사용자 결정 "높은게 빨간색 낮은게 파란색" |
| VL-9 | 범례 기능 9개 넣음 · 7개 안 넣음(§5.3) | 사용성 > 유연성, 필수만 |
| VL-10 | 범례 모양 = 브라우저 기억 1벌(모든 3D 공통), 서버 저장 없음, 기본 레벨 9 | DB 변경 없이 충분, 보기마다 다시 맞추지 않게 |
| VL-11 | 기존 파일 바이트 불변 — 새 자료는 새 폴더·사이드카, zip 묶음 제외 | 서버 결과 불변 원칙 |
| VL-12 | 범례 **편집** 적용 = `View3DCard` 결과 3D 전부. (색 적용 범위 부분은 VL-13 이 대체) | 최소 해석 → 사용자 답으로 개정 |
| VL-13 | (사용자 결정 — Q-VL-1 답 "전부 통일") 연속값 색 19곳 중 16곳 = 순차 `rainbow` 7 · 발산 `diverge` 9, 예외 3(분류 L3·단계 L11·paicad L19) | 화면마다 색 뜻이 다르면 읽을 때마다 범례를 다시 봐야 함 |
| VL-14 | 정점 원본 = `resources/colormaps.json` 1개, 읽는 모듈 = TS `lib/colormap.ts`·파이썬 `esl/io/colormaps.py` 1개씩, 호출부는 역할(seq·div·region)로 고름, `check` 해시로 두 언어 일치 검증 | 하드코딩 금지·같은 기능 공용 모듈 하나 — 지금은 정점이 5곳에 흩어져 있음 |
| VL-15 | 부호 있는 값 = **+ 빨강·− 파랑**(값 정의는 그대로, 뜻이 뒤집히는 곳은 문구를 바꿈): 높이 변화 빨강 = 깊어짐, 보고서 차이 빨강 = 증가 | "높은 게 빨강" 을 부호 있는 값에 그대로 적용 — 값 부호를 색에 맞춰 뒤집으면 표 숫자와 어긋남 |
| VL-16 | ESL별 개선율 칸 색 = C 변화율 발산(파랑 개선·빨강 악화), 숫자는 개선율 그대로 | 3D `차이`(파랑 = C 감소)와 같은 뜻 — 초록·빨강을 남기면 "전부 통일" 에 어긋남(확인 Q-VL-3) |
| VL-17 | (사용자 결정 — Q-VL-2 답) 씬 3D 저장 한도 = 스터디당 1 GB(`max_mb` 1024) | 가정 그대로 확정 |
| VL-18 | 옛 그림은 다시 만들지 않음 — 새로 만드는 보고서·PNG 만 새 색. 옛 썸네일은 manifest `color.map` 없음으로 가려 옛 범례 | 옛 결과 바이트 불변 원칙 유지 + 그림과 범례가 어긋나지 않게 |
| VL-19 | 구현 분할: 파이썬 그림 색 = 새 C2, 프런트 2D·썸네일 = 새 F1c, 색 모듈·3D = F1a, 개선율 칸 = F1b. C1·B1 범위 불변, 자원 파일은 메인 선행 커밋 | C1 진행 중·B1 완료 — 파일 소유 겹침 0 |

## 13. 질문에 대한 결정 (2026-11-27 사용자 답) · 남은 확인

| 질문 | 답 | 결정 | 반영 |
|---|---|---|---|
| Q-VL-1 레인보우 적용 범위 | **"전부 통일"** — 3D 결과 컨투어 + ④ 검증 비교 2D + 비드 높이 변화 색 + 보고서 + 썸네일 + 그 밖에 연속값 색을 쓰는 모든 곳 | D-0.25.1-VL-13·14·15·16·18·19 | §0.5·§5.2·§5.7~§5.9·§9.5·§10 |
| Q-VL-2 저장 용량 | **스터디당 1 GB** | D-0.25.1-VL-17 — `bead_doe.view3d.scene.max_mb` = 1024(계약 가정 그대로 — 코드·설정 변경 없음) | §2.4·§7.1 |

남은 확인(가정대로 진행 — 답이 다르면 L10·L18 두 곳만 되돌림):
- **Q-VL-3** ESL별 개선율 표 칸 색: 가정 = **파랑 개선·빨강 악화**(3D `차이` 와 같은 뜻). 지금의 초록 개선·빨강 악화(좋음·나쁨 판정 색)를 이 표에서만 남길까?

## 14. 후속 (R-VL-n)
- R-VL-2 변위 차이·변형 에너지 밀도 컨투어. R-VL-3 범례 설정 서버 저장(계정별). R-VL-4 색각 보정 색 지도 선택(자원 `roles` 1줄로 바꿀 수 있게 됨). R-VL-5 상위 k 밖 안의 씬 3D 요청 생성. R-VL-6 2D·보고서 그림의 범례 편집. (R-VL-1 색 통일 = 개정 1 로 이번 범위에 들어옴.)

## 15. 구현 메모
(구현 때 채움 — 실측 용량·시간, 접점 불일치, 독립 검증 결과)

### 15.1 B1 구현 사실 (wip/v0.25.1-b1 2475896d — 완료, 시험 V-0251-16~19 `backend/tests/test_doe_v0251_b1_api.py`)

§6 과 다르게 구현된 점 — **구현이 기준**(계약을 여기에 맞춤, 다른 묶음은 이 표를 따름):

| # | 계약(§6·§2) | B1 구현 | 판정 · 다른 묶음이 지킬 것 |
|---|---|---|---|
| 1 | 씬 manifest = `View3dOut` + 선택 키 | `View3dOut` 의 **하위형 `View3dSceneOut`**(새 키 c·dc·pins·ranges.c·ranges.dc 는 하위형에만) | 수용 — 기존 `View3dOut` 응답 스키마 불변이라 더 안전. F1b `types.ts` 는 `View3dSceneOut` 이름으로 받음(`check:api`) |
| 2 | `entry_id` = 스냅샷 엔트리에 있는 것만 | **사이드카 `entries`** 로 검사 → `kk` | 수용. **C1 이 지킬 것**: 사이드카 `entries` 에 스냅샷 `doe.entries` **전부**를 같은 순서로 적는다(자료를 못 만든 씬도 — 빠지면 그 씬이 "자료 없음" 이 아니라 형식 오류 404 가 됨). V-0251-12·17 에 단언 추가 |
| 3 | `skipped[].text` = 코드 문구 | `text` = **코드 문구 + 상세**(사이드카 `detail`) | 수용 — 화면은 `text` 를 그대로 보임(§4.4). C1 의 `detail` 은 사용자에게 보이는 글이 됨 → 경로·예외 원문을 넣지 않고 짧은 사유만 |
| 4 | 새 문구 4개 | + `SCENE_VIEW_INVALID`(사이드카를 못 읽음 → `scene_view: null` + 경고)·`SCENE_UNAVAILABLE_DISABLED`(설정 끔 → 409 `VIEW3D_SCENE_UNAVAILABLE` 사유) | 수용 — §6·V-0251-16·18 에 반영 |
| 5 | `DOE_RUN` 큐 + `post_mode: "scene"` | 작업 `params.kind = "VIEW3D"`(워커 `POST_ONLY_KINDS` 그대로) + `doe.post_mode = "scene"`, resume `BD_POST` | 수용(기존 3D 다시 만들기와 같은 kind). **C1 이 지킬 것**: 코어 dispatch 가 kind `VIEW3D` 에서 `post_mode` 값 `"view3d"`·`"scene"` 을 구분 |

B1 이 C1 에 요구하는 형식(인수 메모 그대로): 사이드카 필수 키 `schema`·`entries[{entry_id, kk}]`·`packs[src]{tag, c_kind, designs{did: {dir, scenes[]}}, skipped[]}`·`budget{max_mb, est_mb}` / `pack.json` 필수 키 `geometry{name}`·`lod|null{name}`·`scenes[{entry_id, kk, manifest, values}]`(manifest·values = 파일 이름 문자열) / 씬 manifest 에 `values{name, …}` / 코어 `DEFAULTS["view3d"]["scene"]`.

**설계 변경 필요 지적(고치지는 않음)**: (a) #2 — 계약 §2.3 은 `entries` 를 "전부" 라고 못 박지 않았다 → 위 C1 규칙으로 보완. (b) #3 — `detail` 이 화면에 나가므로 C1 의 실패 상세가 내부 경로를 담으면 노출됨 → C1 검토 항목. (c) 색 통일(개정 1)은 B1 에 추가 작업 없음 — `preview.color.map` 은 dict 통과, 새 API·스키마 없음. 그 밖 설계 변경 필요 없음.

### 15.2 C1 코어 구현 사실 (release/v0.25.1 5d1971f4 — 계약 보정·최소 해석 VL-C1-1~12, 원문 `work/findings.md` 에서 옮김)

| # | 계약 | 구현 · 판정 |
|---|---|---|
| VL-C1-1 | §3.2 공통 좌표 | provider `frame` = 스터디 대상 frame(`t.frame` — ①②③ design_target·④ compare_target 모두 기준) + 메시 좌표 그대로(A ESL frame 으로 되돌리면 넓은 형상 노드가 가장자리 셀로 눌림). 셀 키 = `grid_map.grid_frame`·`vox_key` 그대로 |
| VL-C1-2 | §2.6·§10 파일 목록 | `esl/mech/grid_map.py`(목록 밖) `run_shape` keep_u 일 때 `rcfs{src:{eid:{bc, rc, fs}}}` 보관만(계산·파일 불변). 씬 C 기여도·씬 지지 표식 = 엔트리 BC, 기존 jd·js 폴더 = 첫 엔트리 BC 그대로(바이트 불변) |
| VL-C1-3 | §2.3 ranges | `ranges.c.p01·p99`·`ranges.dc.abs_p99` = 값 ≠ 0 노드 백분위(np.percentile 선형), 모두 0 = null |
| VL-C1-4 | §2.1·§8 분해 재사용 | 기존 3D 함수가 같은 provider 본체로 자기 폴더를 쓰고 열린 분해를 실행기에 넘김 → 씬 = 후진대입만(H5 분해 수 끔 12 = 켬 12, 시험 `test_v0251_factorization_reused`). 기존 3D 가 만들지 않은 (출처, 안)만 직접(분해 +1) |
| VL-C1-5 | §2.1 차이 순서 | 안이 기준보다 먼저 만들어지는 출처는 안 묶음 pack.json 을 미루고 기준이 오면 `view3d.patch_scene_dc`(결과 바이트 = 처음부터 dc 를 넣은 것). 기준 실패 = dc null + `SCENE_FAILED`(detail "baseline") |
| VL-C1-6 | §2.4 한도 | 씬 = (출처, 엔트리) 단위로 그 출처의 모든 표시 안에 같이 넣거나 뺌. 필수 = 안마다 최악 엔트리 + 이미 있는 씬, 나머지 = 베이스라인 C 큰 순. `est_mb` = 계약 식(빠진 씬 포함, MiB) |
| VL-C1-7 | §2.6 경계력·내력 | 실행기 직접 경로는 `_ns_design` 을 부르지 않고(안 사이드카 재기록 방지) 같은 모델·지지·영역으로 풂. BD_POST 는 기존 `_ns_view3d` 가 keep_u 로 넘김(추가 풀이 없음) |
| VL-C1-8 | §2.3 warnings | 진단 문자열 `SCENE_C_MISMATCH`·`SCENE_PIN_MISMATCH`·`SCENE_FAILED: <src> <did> <code>`(skipped 코드 밖 — 정보). 알려진 원인: v0.24.9 하중 공간 고정 스터디(기존 자동 3D 와 같은 한계), 평가 영역이 빈 격자 지그 핀, 하중 전달 없는 옛 ④ |
| VL-C1-9 | §2.2 manifest | 씬 manifest schema = 기존 `esl/view3d/1`, `key` = `doe/scene/<tag>/<did>/e<kk>`, `esl_run_id` = entry_id. 핀 kind = ev·all·region·mask, `pins.umax` null = 노드 없음만 |
| VL-C1-10 | §9.1-15 | 설정 거울 시험 `test_v0251_15_settings_mirrors` — B1 통합 뒤 skip 해제(통합 후 통과) |
| VL-C1-11 | §8 실측 | H6(103,930 노드)는 이 기계(7 GB·superlu)에서 분해 메모리 초과 → H5(15,477 노드) ① same(엔트리 8·지그 2방식·묶음 4 × 출처 3): 묶음 33.4 MB(96 씬), BD_POST +20.3 s(사이드카 seconds 21.2), 분해 수 같음. 10만 노드 ≈ 196 MB(추정 195 MB 일치), 시간 ≈ 2.5 ~ 3 분(추정 0.5 ~ 1.5 분보다 김 — 지그 BC 풀이·군집). 현장 E-0251-9 로 확정 |
| VL-C1-12 | §2.5·§7.2 | BD_POST 다시 실행 때 옛 `post/view3d_scene` 은 백업 없이 지우고 새로 씀(보기 파생 자료·크기 — 기존 백업 정리는 post/view3d 만). 쓰기는 `c.writer.guard` 안 |

### 15.3 C2 파이썬 그림 색 구현 사실 (wip/v0.25.1-c2 eb5c8614)
- 범위 = §5.7 L12~L18·§5.8 파이썬 모듈 `esl/io/colormaps.py`(load·map_for·rgb·css·table·special·as_json, 검사 = `CONFIG_INVALID`). Case 보고서 JS 는 데이터 JSON `cmap` 만 읽고 보간을 §5.8 규칙(floor(x + 0.5)·NaN = t 0)으로 — v0.25.0 JS(Math.round) 와 같은 값이 아닌 것은 의도(정점이 바뀜).
- 계약과 다르게 된 점: (1) §5.8 "설치 스크립트 변경 없음" 이 틀림 → 통합 INT-3. (2) §5.9 골든 갱신 목록에 바이트 골든 19건이 빠짐 → 통합 INT-4. (3) `stages.py` 썸네일 `color_meta` 1줄은 C1 소유라 넣지 않음 → 통합 INT-2.
- 독립 비교(저장소 밖 스크립트, e9745958 트리 대비): `keepout.png`·공칭 썸네일 바이트 동일, `bead_map.png`·썸네일은 크기·구조 픽셀(바탕·외곽선·빗금·기호·글자) 라벨 마스크 동일하고 바뀐 픽셀은 색 칸뿐(깊어짐 R > B 4038 px·B > R 0, 얕아짐 반대). HTML 은 색 문자열·§5.7 문구를 지우면 문자열 동일. Case 보고서 JS lerp 를 node 로 실행 = 파이썬 `css` 256색 일치(V-0251-44, node 있을 때).

### 15.4 F1a·F1b·F1c 프런트 구현 사실 (wip/v0.25.1-f1a f740aa09 · f1b f29217ce · f1c 23a4b3da)
- **F1a**: `View3DOptions` 새 키 `colorMode`(주면 `colorBy` 보다 앞섬)·`colorLabel`·`pins`(안 주면 씬 manifest `pins.umax` 를 읽음 — 호출부는 manifest 만 넘김)·`fieldOverride.role`(기본 `region` — 옛 하중 영역 호출 그대로). `range` 를 안 주면 저장소(`useViewerSync`)가 쌍 자동 범위 합집합 + 직접 입력 공유로 정함(§5.3 "두 카드 맞춤"의 구현 방식 — 옛 호출부의 `range` 는 그대로 동작). 값 파일에 c/dc 배열이 없으면 칠하지 않고 안내(`v3d-no-c`), 버튼 비활성은 호출부 몫(`sceneExtras`). `@deprecated` 옛 상수(VIRIDIS·DIVERGING·NA_COLOR·lerp·gradient·DIVERGING_GRADIENT)는 F1c 병합에서 삭제(V-0251-37 TS 0건).
- **F1b**: `api/types.ts` 는 §15.1 #1 대로 `View3dSceneOut`·`DoeSceneViewOut`·`DoeSceneAddOut`(`check:api` 통과). 씬 상태는 결과 화면 1곳(스터디 id 가 바뀌면 자동), 문구 표 `SCENE_TEXT`·버튼 표 `COLOR_SEL_BUTTONS` 한 곳(`pages/doe/doeScene.ts`). c·dc 범위는 `range` 를 넘기지 않고 저장소가 정함(F1a 방식). 개선율 칸 색 `css(mapFor("div"), …)`·`PER_ESL_HEAT_SPAN` 0.5. 높이 측정 스크립트 `scripts/screenshots-v0251-f1b.mjs`(V-0251-29 — 실측은 e2e). 계약과 다른 점 없음.
- **F1c**: DispOverlay·FieldOverlay·library/common = `css`/`cssGradient(mapFor(seq|div))`, NaN = `specialCss("nan")`. `HeightLegend` legacy = 옛 문구 + 반전 띠. 계약과 다른 점: `DoeThumbGrid` 옛 판별을 `color.map !== "diverge"`(지도 이름 비교)로 했음 → 통합 INT-6 에서 §5.9 규칙(`map` 키 없음)으로.

### 15.5 통합 보정 (release/v0.25.1 통합 — INT-n)

| # | 내용 | 근거 · 시험 |
|---|---|---|
| INT-1 | 병합 b1 → c2 → f1a → f1c → f1b(f1b 는 b1·f1a·release 를 품음) — 글자 충돌 0. 의미 충돌 점검: F1b 는 F1c 전 F1a 위에서 만들었지만 삭제된 옛 상수를 쓰지 않음(V-0251-37 TS 0건), 인수 메모(handoff 6개)는 이 절·decisions 로 옮기고 삭제 | `view3d_v0251_color.test.ts` 37 |
| INT-2 | `stages.py` select 썸네일 manifest `color` 에 `color_meta()` 합침(§5.9) | `test_select_stage_flow` `map == "diverge"` |
| INT-3 | 배포 묶음 자원 목록에 `resources/colormaps.json`(§5.8 보정) | `test_bead_doe_deploy`·`test_deploy_collect` |
| INT-4 | 바이트 골든 19건 비교 집합에서 `report.html` 제외 + VT-6·8 색 코드 되돌림 바이트 비교(§5.9 보정) | 19건 통과 |
| INT-5 | 진한 색 칸 글자 대비 — 자원 `text{dark_lum 0.179, on_dark, on_light}`(§5.8 보정), 파이썬 `luminance`·`text_on`, TS `relLuminance`·`textOn`(`view3d/colors.luminance` 는 위임 — 식 한 곳). 화면 `heatStyle` → `{background, color}`, 보고서 `_ratio_cell` span `color:`. 옅은 칸도 글자 색을 명시(보고서 어두운 테마에서 `--fg` 가 밝아 옅은 칸 글자가 안 보이던 것 방지). 0 칸(무색) = 기본 글자 | `test_report_doe::test_v0251_45`·`doe_v0251_scene.test.tsx` — 같은 (개선율, 기대) 표 8개 + 지도 2개 256칸 전부 규칙 일치, 자원 검사(`test_colormaps` 39·`view3d_v0251_color` 39) |
| INT-6 | `api/types.ts` `DoePreviewOut.color.map?`, `DoeThumbGrid` 캐스트 제거·옛 판별 `!color.map`(지도 이름 하드코딩 제거) | `color_f1c.test.tsx`·typecheck |
| INT-7 | 문서·버전: `user.md`(결과 3D 절 — 씬 선택 3곳·C 기여도·차이·umax 핀·범례 편집·색 의미 표, 썸네일 문구 :307)·`bead_doe_check.md:91`·`admin.md` §4.11(`view3d.scene`·colormaps.json 배포)·CHANGELOG [0.25.1]·`field_check_v0251.md`(E-0251-1~14)·VERSION 0.25.1·OpenAPI info·버전 시험 2곳 | `test_menu_deploy`·`test_p3_ux_hardening` |
| INT-8 | (남음 — 고치지 않음) 개선율 칸 세기 기준 `PER_ESL_HEAT_SPAN` 0.5 는 화면(`DoePerEslTable.tsx`)·보고서(`report_doe.py`) 언어마다 1개 — 두 시험이 각각 0.5 를 단언. 색 지도 값이 아니라 표 표시 기준이라 자원으로 옮기지 않음(바꿀 때 두 곳 + 두 시험) | — |
