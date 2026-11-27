# 계약: 강성 스터디 3D 낙하 씬별 보기 + 컴플라이언스(C 기여도·차이·umax 핀) 표시 + 컨투어 색·범례(HyperView 참조) (VL, v0.25.1)

- 상태: **초안 → 구현 기준**(2026-11-27). 브랜치 `release/v0.25.1`(main 97a0e358 v0.25.0 에서 분기). 구현 코드 없음 — 이 문서가 원본.
- 관계: `esl_3d_load.md`(view3d 형식·색·성능 §11), `esl_viewer_hv.md`(v0.24.6 뷰어 — 층·범례 구간·쌍 동기·계획 표 `VIEWER_PLANS`), `esl_view3d_sources.md`(출처 탭·자료 만들기), `esl_jig_view.md`(사이드카·3D 다시 만들기), `esl_jig_case.md`(지그 3방식 C_mix), `esl_jig_grid_map.md`(다른 메시 격자), `esl_stiffness_metric.md`·`esl_load_transfer.md`(④ LT-9 같은 ESL 기준). 충돌하면 이 문서 범위에서 이 문서가 우선.
- DB migration **없음**. 새 설정 블록 1개(`bead_doe.view3d.scene` — §7). 계산 결과(순위·per_esl·input_sha256) **불변** — 보기 자료만 추가.
- ID: 결정 `D-0.25.1-VL-n`, 시험 `V-0251-n`, 후속 `R-VL-n`, 미결 `Q-VL-n`, 현장 확인 `E-0251-n`.

### 사용자 요청 (원문, 변경 금지)
1. "강성스터디 결과에서 낙하씬 선택해도 하중씬 비교 3d형상비교가 업데이트안돼"
2. "컴플라이언스 좋아졌다하는데 왜 umax는 증가하는거야?? 컴플라이언스가 증가했다는걸 3d컨투어에서 어떻게 보여줘?"
3. (2026-11-27 결정) "그렇게 해. 거기다 컨투어 색 컨셉을 하이퍼뷰어 처럼 높은게 빨간색 낮은게 파란색. 컨투어 레전드도 편집도 벤치마킹해서 넣어바"

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

---

## 1. 범위 · 비범위 · 용어

### 1.1 범위
- **A. 씬별 3D**: 3D 비교 대상(베이스라인 + 순위 상위 k)마다 **모든 낙하 씬(ESL 엔트리)** 의 3D 자료, 결과 화면 씬 선택 3곳 ↔ 3D 연결. 전 노드·지그(고정·변위·스프링·격자)·경계력·내력·④ 형상 비교·다른 메시 모두 **같은 규칙 한 벌**.
- **B. 컴플라이언스 표시**: 색 모드 `C 기여도`·`차이` 추가(기존 `응답 변위`·`하중` 유지), umax 위치 핀(두 카드), 씬 요약 한 줄(C·umax 기준 → 안).
- **C. 색·범례**: 결과 3D 컨투어 색 = 레인보우(낮음 파랑 → 높음 빨강), 차이 = 0 중심 발산(− 파랑 · + 빨강), 범례 편집(§5.3), 공용 모듈 한 곳.
- **D. 호환**: 옛 결과·옛 view3d 자료로 화면이 깨지지 않음, 기존 결과 파일 바이트 불변.

### 1.2 비범위 (이번에 안 함)
| 항목 | 이유 | 후속 |
|---|---|---|
| ④ 검증 비교 2D 겹쳐 보기(viridis)·비드 편집 3D 의 높이 변화 색(빨강 = 얕아짐)·보고서 HTML·썸네일의 색 | 3D 결과 컨투어가 아님(다른 그리기 경로) — 최소 해석 | Q-VL-1 · R-VL-1 |
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

### 2.4 용량 한도 (D-0.25.1-VL-2)
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

## 5. C — 컨투어 색 · 범례 (모든 결과 3D 공통)

### 5.1 적용 대상
`View3DCard` 를 쓰는 보기 전부 = 계획 표 `VIEWER_PLANS` 5행(case_load·case_disp·study_design·study_jigdiag·study_recon): Case ③ 3D, 스터디 설계 비교, 지그 진단, 재현 진단. 한 곳(§5.5)만 고치면 모두 바뀐다. 비드 편집 3D·2D 겹쳐 보기는 비범위(§1.2).

### 5.2 색 지도 (D-0.25.1-VL-8)
| 이름 | 정의 | 쓰임 |
|---|---|---|
| `rainbow` | sRGB 정점 5개 선형 보간: t 0 파랑(0,0,255) → 0.25 청록(0,255,255) → 0.5 초록(0,255,0) → 0.75 노랑(255,255,0) → 1 빨강(255,0,0). **낮음 = 파랑, 높음 = 빨강** | 모든 크기·값 컨투어(기본) |
| `diverge` | 기존 RdBu 11 을 **뒤집은 순서**: −V 파랑 → 0 흰색(247,247,247) → +V 빨강 | 차이(0 중심, 범위 대칭 ±V) |
| NaN(계산 불가) | 회색(154,161,171) — 지금 그대로 | — |
| 범위 밖(선택) | 짙은 회색(90,96,106) | §5.3 |

- 기존 Blues 는 결과 3D 에서 쓰지 않는다. `colors.ts` 의 `RDBU11`·`LUT_DIV_LINEAR`(비드 높이 변화)는 그대로 둔다.
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
- 계획 표 `VIEWER_PLANS` 열 추가(모든 행 필수): `layers` 에 `upin`(핀 자료가 있는 보기만 의미), `legendSync: "pair" | "none"`(study_* = pair). 색 모드 표 `COLOR_MODES`(한 곳): 행 = 모드(disp·load·c·dc·field) × 열 `map`(rainbow|diverge)·`signed`·`logOk`·`sym`·`pairRange`(차이 = false).

### 5.5 공용 모듈 (프런트 — 새 = ★)
| 파일 | 내용 | 금지 |
|---|---|---|
| ★`view3d/legend/colormaps.ts` | `rainbowSrgb`·`divergeSrgb`·`buildLut(map, reversed, linear)`·`bandedCss` | three·api·React import |
| ★`view3d/legend/legendModel.ts` | 순수 함수: `toT(v, range, scale)`(선형·로그)·`ticks`·`formatValue(fmt, digits)`·`countOut`·`effectiveRange`(로그 최소 보정)·`COLOR_MODES`·`LEGEND_DEFAULTS` | 같음 |
| ★`view3d/legend/legendPrefs.ts` | 읽기·쓰기·v1 이행(§5.6) | three |
| ★`view3d/legend/LegendEditor.tsx` | 팝오버 내용 | three |
| `LegendOverlay.tsx`·`ViewerControls.tsx`·`View3DCard.tsx`·`viewerPlan.ts`·`viewerSync.ts`·`scene.ts`·`colors.ts`·`values.ts`·`marks.ts` | 위 모듈만 사용하도록 고침. `scene.ts` uniform 추가 `uLog`·`uOutMode`·`uOutColor`(범례 변경 = uniform·색표 교체만) | 결과 3D 경로에서 `bluesSrgb`·`BLUES_GRADIENT` 직접 사용 |

표시 기본값(`LEGEND_DEFAULTS` = {levels 9, scale linear, format auto, digits 3, out clamp, reversed false, minMark false, upin true, logDecades 3})은 **이 표 한 곳**(v0.24.6 `VIEWER_PLANS` 관례 — 프런트 표시 기본은 서버 설정이 아님, D-0.25.1-VL-10).

### 5.6 기억 (D-0.25.1-VL-10)
- `localStorage["esl.v3d.viewer.v2"]` = `{ "legend": {levels, continuous, scale, format, digits, out, reversed, minMark, upin}, "<planKey>": {bc, load, ghost, marks} }`. **범례 모양은 모든 3D 보기 공통 1벌**(보기마다 따로 맞추지 않게), 층 켬·끔은 지금처럼 보기별.
- v1 → v2: 처음 읽을 때 v1 의 planKey 별 bc·load·ghost·marks 를 옮기고, levels 는 버린다(새 기본 9). v1 키는 지우지 않음(이전 버전으로 되돌려도 동작).
- 범위 직접 입력값·로그 선택은 **기억하지 않음**(값 종류·씬마다 뜻이 달라 다음에 잘못 적용됨 — 화면을 떠나면 자동).
- 형식 오류·저장소 없음 = 기본값(오류 표시 없음 — 기존 규칙).

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
- OpenAPI: `View3dOut` 선택 필드·새 스키마 `DoeSceneViewOut`·`DoeSceneAddOut`·새 경로 3개를 `schemas.py` 에 선언(`response_model`) — 생성 OpenAPI 와 `types.ts` 가 `check:api` 로 일치. `skipped.text` 문구 원본 = `resources/doe_messages.json`(새 코드 `SCENE_BUDGET`·`SCENE_FAILED`·`SCENE_NO_SOURCE`·`SCENE_DIFF_NO_FRAME`).

---

## 7. 설정 · 해시 · 하위 호환

### 7.1 설정 `bead_doe.view3d.scene`(4곳 같은 이름 — 코어 `esl/doe/__init__.py` DEFAULTS · pydantic `BeadDoeView3dCfg` 안 새 `BeadDoeView3dSceneCfg` · `config/esl_platform.example.yaml` · `.prod.example.yaml`)

| 키 | 기본 | 범위 | 뜻 |
|---|---|---|---|
| `enabled` | true | bool | 끄면 씬 묶음·사이드카를 만들지 않음(= v0.25.0 과 같은 파일 집합) |
| `max_mb` | 1024 | 0~65536 | 스터디당 씬 묶음 추정 용량 한도(§2.4). 0 = 한도 없음 |
| `diff_cell_h_mult` | 2.0 | 0.5~8 | 차이 격자 셀 = max(`rank.jig_grid.cell_mm`, 이 값 × 변 길이 중앙값) |

- 해시 밖: `view3d` 블록은 지금도 `_cfg_hash` 에 없음 → `input_sha256`·이어하기 캐시 불변(V-0251-12). 스냅샷에 넣지 않음(보기 설정 — 실행 시점 설정 사용).

### 7.2 하위 호환
| 대상 | 동작 |
|---|---|
| 옛 스터디(사이드카 없음) | 결과 화면 = 지금과 같음 + 씬 선택 칸(자동만 자료 있음) + 안내·[씬 3D 만들기](§4.4). API `scene_view: null` |
| 옛 view3d 폴더(c 배열 없음) | 그대로 읽힘(프런트는 모르는 배열 키 무시 — 지금 규칙). C 기여도·차이 비활성 + 사유 |
| 옛 프런트 캐시 + 새 서버 | 새 키는 모두 선택 키 — 옛 화면 동작 불변 |
| 기존 파일 | result.json·ranking.csv·per_esl.json·jig_view.json·bforce/fint 사이드카·`post/view3d/**`·report.html **바이트 불변**(같은 입력, 시간 키 제외 — 기존 골든 규칙). 새 파일 = `post/view3d_scene/**`·`post/scene_view.json` 만 |
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
| 10 | 기존 파일 바이트 불변 | main 97a0e358 과 같은 입력으로 ① same·select·③ step·④ compare(LT)·격자 지그: §7.2 목록 파일 바이트 동일(시간 키 제외), 새 파일은 `post/view3d_scene/**`·`post/scene_view.json` 뿐 |
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
| 20 | 레인보우: t 0·0.25·0.5·0.75·1 = 파랑·청록·초록·노랑·빨강(정확한 RGB), 띠 색 = 띠 중앙, 뒤집기, 선형 색표 변환 |
| 21 | 발산: 0 = 흰색, −V 파랑·+V 빨강, 대칭 |
| 22 | `legendModel`: 선형·로그 `toT`, 로그 최소 보정·부호 모드 비활성, 눈금, 숫자 형식(자동·고정·지수 × 자릿수), 범위 밖 끝색/회색·개수 |
| 23 | 기억: v1 → v2 이행, 깨진 JSON = 기본값, 범위·로그는 저장 안 함 |
| 24 | 쌍 동기: 한 카드에서 범례 편집 → 상대 카드 같은 값. 차이 모드 = 범위 따로 |
| 25 | 씬 연결: 3D 바 선택 칸·ESL 표 열 머리·셀·순위표 최악 ESL 칸 → 두 카드가 요청하는 URL 의 씬이 바뀜, 자동 = 선택 안의 최악, 직접 고른 씬은 안을 바꿔도 유지, 출처 탭 6종 같은 규칙 |
| 26 | 옛 결과: `scene_view` null → 자동일 때 DOM·요청 URL 이 v0.25.0 과 같음. 자료 없는 씬 → 안내 + 버튼(작성자)/문구만(조회자) |
| 27 | C 기여도·차이 비활성 사유(배열 없음·`dc` null) |
| 28 | umax 핀: 라벨·두 카드·끄기·최대 표식과 같은 정점일 때 겹침 규칙 |
| 29 | 높이: 2560×1440·1920×1080 에서 3D 바 1줄, 3D 칸·카드 높이 = v0.25.0(픽셀 차 0), 범례 팝오버는 겹침(레이아웃 영향 0) |
| 30 | 공용 확인(정적): 결과 3D 경로(`View3DCard`·`LegendOverlay`·`scene.ts`)에 `bluesSrgb`·`BLUES_GRADIENT` import 없음, `VIEWER_PLANS`·`COLOR_MODES` 모든 열 채움 |
| 31 | 성능: 범례 편집 때 `fillVertexColors`(CPU 루프) 호출 0, 30만 정점 mock |
| 32 | 옛 view3d 자료(`tests/fixtures/view3d/small`) 렌더 — c 없음 |

### 9.4 e2e
| # | 내용 |
|---|---|
| 33 | 합성 스터디 실행 → 결과에서 씬을 차례로 선택: 두 카드 제목·`data-esl`·씬 요약이 바뀌고 요약의 C·umax == ESL 표 값. 전 노드·지그 변위·지그 스프링 탭 |
| 34 | ④ 형상 비교(다른 메시): 씬 전환 + 차이 모드(`map grid`) 표시, `Σdc` 표시값 == 표 ΔC |
| 35 | 옛 결과 회귀: v0.25.0 으로 만든 스터디 폴더를 그대로 열어 화면 정상 → [씬 3D 만들기] → 끝난 뒤 씬 전환 동작, 기존 파일 해시 불변 |
| 36 | Case ③ 3D·지그 진단·재현 진단이 레인보우·같은 범례 편집(공용 확인) |

---

## 10. 구현 분할 (파일 소유 겹침 없음 — 병행 후 통합)

| 묶음 | 모델 | 소유 파일 | 내용 | 시험 |
|---|---|---|---|---|
| **C1 코어** | opus | `esl/mech/cfield.py`(새) · `esl/view3d.py` · `esl/doe/stages.py` · `esl/doe/__init__.py`(DEFAULTS) · `tests/**`(코어) | §2·§3·§7.1 코어 기본값. 기존 3D 함수의 입력부 분리(바이트 불변), 실행기·계획 표·사이드카, post_mode scene | 1~15 |
| **B1 백엔드** | sonnet | `backend/esl_platform/**`(config pydantic·services/doe.py·routers/doe.py·schemas.py) · `config/*.yaml` 2개 · `resources/doe_messages.json` · `backend/tests/**` · OpenAPI 스냅샷 | §6·§7.1 거울. C1 의 사이드카·묶음 **형식(§2.2·§2.3)만** 읽음 — 코어 함수 호출 없음 | 16~19 |
| **F1a 프런트 공용 뷰어** | sonnet | `frontend/src/view3d/**`(legend/* 새 4개 포함) · `components/ColorLegend.tsx` · 뷰어 스타일 · 해당 단위 시험 | §5 전부 + 색 모드 c·dc·umax 핀 그리기(`View3DOptions` 확장) | 20~24·28·30~32·36 |
| **F1b 프런트 스터디 화면** | sonnet | `frontend/src/pages/doe/**` · `components/DoePerEslTable.tsx`·`DoeRanking.tsx` · `api/types.ts`·`api/doe.ts` · e2e | §4 — 씬 상태·선택 3곳·3D 바·요약·안내. F1a 가 정한 `View3DOptions` 만 사용 | 25~27·29·33~35 |

- 접점(먼저 고정 — 이 문서가 원본): C1↔B1 = §2.2·§2.3 파일 형식, B1↔F1b = §6 응답 키, F1a↔F1b = `View3DOptions` 새 선택 키 `colorMode: "disp"|"load"|"c"|"dc"`·`pins`·`legendSync`. F1a 는 F1b 보다 먼저 접점 타입을 올린다.
- 통합(메인): `VERSION`·`CHANGELOG.md`·`docs/e2e-checklist.md`(§11 항목)·사용자 매뉴얼 한 절, 독립 검증(불변 시험 10·물리 1~7 재실행).

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

---

## 12. 결정 근거 (요약 — 전문 `docs/decisions.md` 2026-11-27 D-0.25.1-VL-1~12)

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
| VL-12 | 적용 = `View3DCard` 결과 3D 전부, 2D·비드 편집·보고서 색은 비범위 | 최소 해석(Q-VL-1) |

## 13. 미결 (기본 가정으로 진행 — 답이 오면 개정)
- **Q-VL-1** 레인보우 적용 범위: 가정 = 3D 결과 컨투어만. ④ 검증 비교 2D(viridis)·비드 높이 변화 색(지금 빨강 = 얕아짐)·보고서·썸네일도 "높음 = 빨강"으로 맞출까?
- **Q-VL-2** 저장 용량: 가정 = 상위 3안 × 전 씬 미리 생성, 스터디당 약 0.2 GB(10만 노드·8씬·출처 3) 증가·한도 1 GB. 디스크가 부담이면 한도를 낮추거나 전 노드 출처만 미리 만들 수 있음.

## 14. 후속 (R-VL-n)
- R-VL-1 2D 겹쳐 보기·비드 편집·보고서 색 통일(Q-VL-1 답에 따라). R-VL-2 변위 차이·변형 에너지 밀도 컨투어. R-VL-3 범례 설정 서버 저장(계정별). R-VL-4 색각 보정 색 지도 선택. R-VL-5 상위 k 밖 안의 씬 3D 요청 생성.

## 15. 구현 메모
(구현 때 채움 — 실측 용량·시간, 접점 불일치, 독립 검증 결과)
