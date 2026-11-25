# 계약: 비드 깊이 단면 동작 선택(깊이면 폭 유지·사면 각 고정) + W 사용 불가 사유 (DM, v0.24.7)

- 상태: 초안 → 구현 기준(2026-11-25). 브랜치 `release/v0.24.7`(base main 1d71d983 = v0.24.6). 구현 코드 없음 — 이 문서가 원본.
- 관계: `esl_beadgraph.md` BG-D-22·24·25·26·30·32·33·34·BG-X-9(그래프 기저 — 계산 그대로, 조합만 추가), `esl_bead_shape_v021.md` SH-4~7·SH-13~16(S_W·range guard), `esl_bead_select.md` §5.3·5.4(선택 기저), `esl_bead_doe.md` BD-D-7(paicad 변수). 충돌하면 새 스냅샷(`depth_section` = floor_fixed)에서 이 문서가 우선.
- 패키지 `beadgraph`·paicad 무변경(GRAPH_ALGO·MORPH_RULES·RULES 그대로). DB migration 없음.
- ID: 결정 `D-0.24.7-DM-n`, 시험 `V-0247-DM-n`, 후속 `R-DM-n`, 미결 `Q-DM-n`.
- 용어: 화면·매뉴얼 = "깊이면(비드 윗면)"·"입구(판 쪽)". 코드 키·이 문서 내부 = floor(깊이면)·entry(입구). W_open = 입구 폭, W_top = 깊이면 폭, θ = 사면 각(판 평면 기준), **W_open = W_top + 2D·cotθ**.

### 사용자 요청 (원문, 변경 금지)
- "깊이 깊어짐에 따라 바닥면 간격도 넓어져서 대각사면 각도가 유지되어야하는데 지금은 그렇게 안되어잇지?? 폭이랑 위치는 안되나"
- 확정(2026-11-25):
  1. 깊이 동작에 "바닥 폭 유지(입구 확장), 사면 각 고정" 선택지 추가. 새 스터디 기본은 이 방식, 옛 스터디는 그대로. (사용자 질문 "사면 각도 고정이란 거지?" → 답: 현재 그래프 방식도 각은 유지하지만 입구 고정·바닥 축소이고, 새 방식은 각 고정 + 바닥 폭 고정 + 입구 확장)
  2. W 사용 불가 사유를 변수 표에 표시하고, 쓸 수 있으면 W를 기본으로 켠다.
  3. 위치 U/V는 다음 버전으로 따로(이번 범위 밖, 후속 R-로 기록).

배경(현장 #88): 그래프 방식 스터디, 변수 B1~B9_D 만(W 열 없음). 순위가 재낙하 소성 변형률 순서와 일치(스터디 유효). B8 깊이가 깊을수록 개선율 하락(−1.98 %/mm) — 지금 D 기저의 깊이면 축소 효과가 섞였을 가능성.

---

## 0. 감사 (main 1d71d983, 읽기만)

### 0.1 모드별 D·W 기저의 단면 동작

| 모드 | D 기저 | 입구 | 깊이면 폭 | 사면 각 | W 기저 | 근거(파일:행) |
|---|---|---|---|---|---|---|
| 그래프 세그먼트(src graph) | 벽 + 깊이면 가장자리 = 가장 가까운 입구 노드 x_e 중심 3D 닮음 u = (x − x_e)/D_ref(가장자리 D_ref = 실제 높이차, 벽 = D_nom), 깊이면 안 = 법선 ΔD + 평면 조화 확장, 입구 E = 0 | 고정 | 한쪽당 ΔD·cotθ 축소(45° 아니어도 실제 각) | 유지 | 입구·벽·가장자리 ΔW/2 평행 이동(골격 법선 평활), 깊이면 조화, 부모 바닥 블렌딩 띠 R_w | `packages/beadgraph/src/beadgraph/morph.py:243-255`(D), `:269-305`(W), `:325-328`·`:364-367`(E 0), `:227-229`(램프 L) |
| 코너 가드(그래프) | ±ΔD_ext 에서 넓이 비 < 0.35·뒤집힘 요소 노드의 평면 성분 × 0.8^k 고정 | 고정 | 코너에서 덜 줄어듦 | 코너 사면 가팔라짐 | – | `morph.py:121-180`·`:329-360`, BG-D-26 |
| 걸친 섬(보스) 옆 | 닮음 평면 성분이 섬에서 2·max(h, ext) 안에서 0 으로 | 고정 | 그 곳 안 줄어듦 | 가팔라짐 | 섬 강체 | `morph.py:337-348` |
| 네트워크 묶기 | 모든 세그먼트·접합 구역 D 1개(같은 닮음) | 고정 | 축소 | 유지 | **없음** | `esl/doe/bead_graph.py:589`·`:992`, BG-D-18 |
| 면형 바닥(area·plateau) | 같은 닮음(플래토 = 윗면이 깊이면 → 올리면 윗면 축소) | 고정 | 축소 | 유지 | **없음**(골격 없음 → entry_width null) | `absorb.py:293-295`, BG-D-16·20(d) |
| 입구 선 한쪽만(안쪽 플래토 고리 변 등) | 같은 닮음 | 고정 | 축소 | 유지 | 없음(양쪽 입구 노드 각 ≥ 3 일 때만), 새 스냅샷 w_partial = S_W 구간만 | `absorb.py:300-305`, `bead_graph.py:469-483`, BG-X-3·SH-4~7 |
| 선택 방식(src elems) | 단 k 깊이면 = 법선 n, 사면 = 높이 비 s × n, 경계 0 — **평면 성분 없음** | 고정 | **유지** | **가팔라짐**(tanθ' = (D+ΔD)/(D·cotθ)) | 경계 ½ê, 사면 (1 − s'(1−f))·w, f = floor_follow(기본 1 = 단면 평행 이동), 닫힌 경계만 | `bead_select.py:1416-1430`, `:1433-1462`, `:1141`, `esl_bead_select.md:143-161`, V-BS-1(`:361`) |
| paicad(옛 ③ step·① same·② mesh) | `shell update`(CAD 피처 BEAD_DEPTH) → `shell morph` | **미확인** | 미확인 | 미확인 | BEAD_WIDTH | `esl_bead_doe.md:10·36·66·69`, `paicad_io.py:271-292`(값 통과만). 원본·shell-morph 계약 이 세션 접근 불가 → R-DM-3 |
| ④ compare | 모핑 없음(사용자 형상) | – | – | – | – | `transfer_plan.py` compare_per_shape |

### 0.2 발견
1. 그래프 D 는 각을 지키나 입구 고정 → 깊이면이 한쪽당 ΔD·cotθ 줄어든다. 선택 D 는 깊이면을 지키나 사면이 가팔라진다. 어느 모드도 "입구 확장·각 고정·깊이면 유지"가 아니다.
2. #88 B8 의 −1.98 %/mm 에는 깊이 +1 mm 당 깊이면 −2cotθ mm 가 섞여 있다(깊이·폭 효과 분리 불가).
3. 단면 미니 그림이 그래프 D 를 틀리게 그린다: `bead_graph.py:900-903` `dz_dD = clip(z/D_nom)`(수직 늘임만 — 선택 방식 모양) → `SectionMini.tsx:16-24` 는 "깊이면 유지·사면 가팔라짐"으로 보이나 실제 기저는 깊이면 축소·각 유지.
4. feasible D 상한 (W_entry − W_floor_min)/2·W 하한 2·D_nom + W_floor_min 은 45° 가정(`bead_graph.py:1006-1017`, `doe_select.py:726-733` 거울).
5. W 행이 없을 때 사유 기록 없음(`bead_graph.py:479-483`·`:992`). W 가 가능하면 use_default 는 이미 true(`bead_graph.py:1096-1103` — BG_SEGMENT_SHORT·RG_VAR_BLOCKED 만 끔, elems `bead_select.py:1410` fixed skip, 행렬 기본 `doe.default_types [D, W]` `matrix.py:47-58`·`doe.ts:1072-1077`).

## 1. 새 동작

### 1.1 공통 키
- `depth_section: entry_fixed | floor_fixed` — 요청 `DoeStudyIn`·작업 스냅샷 `params.doe.depth_section`·`bead_does.inputs.depth_section`·`DoeStudyOut.inputs` 같은 이름, 모든 시나리오에 저장(적용 여부 = §1.5 계획 표).
- entry_fixed = 지금 모드별 동작(§0.1). floor_fixed = 깊이면 폭 유지 + 사면 각 고정 + 입구 넓어짐.
- 키 없음(옛 스냅샷) = 호환 상수 `LEGACY_DEPTH_SECTION = "entry_fixed"`(`esl/morph/section.py`, 값 고정이 목적 — D-0.24.5-VT-16 선례). 새 스터디 기본 = 설정 `bead_doe.depth_section`(floor_fixed). 복제 = 원 값(Q-DM-3).

### 1.2 floor_fixed 기저 = 조합(새 모핑 물리 없음)
B'_D = B_D + k·B_W*, k = 2·cotθ_b
- graph: B_D = 패키지 D 기저(코너 가드 끔 §2.3). B_W* = 패키지 W 기저(segs = S_W, 가상 범위 [W_nom − 2cotθ_b·ΔD_ext, W_nom + 2cotθ_b·ΔD_ext], ΔD_ext = D `range_basis` 끝 최대) → 램프·블렌딩이 입구 이동량으로 정해짐(BG-D-24·30 식 그대로).
- elems: B_D = `_depth_basis`(k = 1), B_W* = `_width_basis` 를 floor_follow 0 으로(경계 ½ê, 사면 (1 − s')·w, 깊이면 0, 블렌딩 Wendland) — 비드 칸 floor_follow 와 무관.
- 검산: 사면 노드(높이 비 t) 변위/ΔD = 법선 t + 평면 바깥 (1 − t)·cotθ → 입구 +cotθ, 깊이면 가장자리 평면 0, 새 run = (D+ΔD)·cotθ → θ 유지, W_top 그대로, W_open' = W_open + 2ΔD·cotθ.
- 이름 `B<n>_D` 그대로·vec 만 조합. 대칭 묶기(BG-D-21) = 구성 비드 조합의 합. 내부 항목 `B<n>_D~w` 는 행렬·결과·basis.bin 에 안 나감. 달성 깊이(BG-D-33)는 B_D 부분으로 점검(B_W* 는 평면 성분만).

### 1.3 θ 측정
- graph: s ∈ S_W 마다 run_s = (entry_width_s − floor_width_s)/2, θ_s = atan2(D_s, run_s)(graph.json 필드만 — derive·API·BD_MATRIX 같은 값). cotθ_b = Σ len_s·cot_s / Σ len_s(유효 세그먼트). 근거: 닮음 가장자리 평면 성분 = 입구→가장자리 현의 run/rise(`morph.py:246-251`), `slope_hints` flank 정의(`bead_graph.py:1461`)와 같음.
- elems: cotθ = run_med / D_1nom(`bead_select.py:1217-1226`).
- 실패(세그먼트): floor_width 없음, D_s ≤ min_step_mm, run_s < 0, θ_s < `theta_min_deg`(15). 일부 = 나머지 평균 + 정보 `DS_THETA_PARTIAL{bead, anchors}`, 전부 = entry_fixed + 경고 `DS_FALLBACK{bead, var, reason: THETA_UNMEASURED}`. 퍼짐 max|θ_s − θ_b| > `theta_spread_deg`(5) → 정보 `DS_THETA_SPREAD{bead, min_deg, max_deg}`.

### 1.4 W 기저가 없는 구간
| 경우 | 동작 | 경고 |
|---|---|---|
| S_W = S | 조합 | – |
| S_W ⊂ S(w_partial) | S_W 만 조합, 나머지 entry_fixed, 사이 접합에서 L_W 로 전환 | 정보 `DS_PARTIAL{bead, cover}` |
| S_W = ∅(입구 한쪽·면형·네트워크·옛 규칙 부분·merge) | entry_fixed | `DS_FALLBACK{bead, var, reason = §4 코드}` |
| elems 열린 경계·폭 미정·단 수 ≥ 2 | entry_fixed(지금 선택 동작) | `DS_FALLBACK{reason: W_OPEN_BOUNDARY\|W_WIDTH_UNDEFINED\|SELECT_MULTI_TIER}` |
| paicad | 적용 안 함 | 스터디 정보 1개 `DS_ENGINE_NATIVE`(floor_fixed 스냅샷만) |
| ④ compare | 해당 없음 | 없음 |

### 1.5 계획 표(AGENTS.md — 모드 차이는 열로)
신규 `esl/morph/section.py`(모드 무관, numpy 만, `esl.doe`·`beadgraph` import 금지, IO·설정 해석 금지) `SECTION_PLANS` — 키 = 변수 출처(행을 만드는 쪽이 아는 값):

| 행 | compose | theta | feasible | fig | na |
|---|---|---|---|---|---|
| graph | pkg_w | seg_fields | open_cap | homothety | none |
| elems | select_w_f0 | run_med | open_cap | stretch | none |
| paicad | none | none | none | none | DS_ENGINE_NATIVE |
| none | none | none | none | none | none |
- 모든 열 필수(빈 칸 = `CONFIG_INVALID`). 호출 쪽(`bead_graph`·`bead_select`·`paicad_io`·`stages`)은 열 값으로 공용 함수를 고르고 시나리오 이름으로 분기하지 않는다.
- 공용 함수: `resolve(value)`, `cot_from_segments(segs, rules)`, `cot_from_run(run_med, D, rules)`, `compose(d_idx, d_vec, w_idx, w_vec, k)`, `w_virtual_range(W_nom, dD_ext, cot)`, `feasible_open_cap(D_nom, W_nom, cot, depth_max_rel, width_max_rel)`, `fig_ds_dD(s, z, D_nom, cot, row, R_w)`, `w_reason(...)`, 상수 `DEPTH_SECTIONS`·`LEGACY_DEPTH_SECTION`·`SECTION_PLANS`.

## 2. 범위·판정(floor_fixed 만 — entry_fixed 는 지금 식·바이트)
### 2.1 feasible
- D: [지금 하한, min(D_nom(1+depth_max_rel), D_nom + W_nom·width_max_rel/(2cotθ_b))] — **입구 확장 상한** = W feasible 상한 W_nom(1+width_max_rel). (W_entry − W_floor_min)/2 항 없음.
- W: 하한 = W_nom − (W_top_nom − W_floor_min), W_top_nom = W_nom − 2D_nom·cotθ_b(45° 면 지금 식). 상한 그대로. 기본 범위 그대로. API 거울 `_graph_rows` 같은 식.
### 2.2 range_guard·combo·range_check
- 새 스냅샷: 준비 후보(`_candidate_bases`)·BD_MATRIX 보충이 조합 기저 사용. 표 머리 cfg_sha256·항목 key += ds(floor_fixed 만).
- combo: 같은 비드 D·W 가 영향 요소 공유 → `range_guard.interacting` 자동 묶음(입구 동시 확장 점검).
- shape_rules 없음: `range_check`·`clamp_w_ranges` 가 조합 기저로.
### 2.3 코너 가드
- floor_fixed B_D 는 코너 가드 끔(패키지 cfg `morph.corner.iters = 0` — 코드 무변경): 가드 대상(깊이면 축소에 따른 코너 붕괴)이 없고, 가드 계수가 남으면 코너 깊이면이 (1 − c)·cotθ·ΔD 넓어짐. `BG_CORNER_GUARD` 없음. 입구 코너(ΔD < 0)·안쪽 꺾임 뒤집힘은 §2.2 가 범위로 막음. 걸친 섬 감쇠(`morph.py:337-348`)는 그대로(잔차, R-DM-6).
### 2.4 침범
- 바깥 이동(BG-D-34·BG-X-9) 허용 = strict(D) ∪ strict(W*)(부모 바닥·블렌딩 띠 포함). 누출(BG-D-32)은 두 부분 각각 검사 후 조합.
- 다른 비드(SR-D-38)·체결부 hold ψ(BG-D-28)·섬(BG-D-29)·블렌딩 자름 = 기존 규칙. S_W 입구 노드에 ψ < 1 있으면 정보 `DS_HOLD_PINCH{bead, n}`.
### 2.5 블렌딩 R·램프
- graph: R_w = max(blend.min_mm, blend.k·cotθ_b·ΔD_ext, 3h), L_W = max(ramp_k·cotθ_b·ΔD_ext, 3h)(가상 범위 대입), L_D 지금 식 — 45° 에서 같음, 다르면 접합 근처 |L_W − L_D| 에서 잔차.
- elems: 비드 blend_mm 그대로. 닿으면 자름 + `SELECT_BLEND_CLIPPED`.
### 2.6 진단(실패 아님)
- `basis.json graph_vars[] += section{mode, cot, cover, floor_resid_mm, angle_resid_deg}`(floor_fixed 만, +ΔD_ext 에서 φ_D = φ_W = 1·ψ = 1·섬 아닌 달성 구역).

## 3. W·D 동시 켬
- W = 공칭 깊이 입구 폭(이름·공칭·범위·결과 열 `B<n>_W` 불변), ΔW = 단면 평행 이동.
- floor_fixed: W_top' = W_top + ΔW, W_open' = W_open + ΔW + 2ΔD·cotθ, θ 불변 — D = 깊이, W = 폭(선형 합, 서로 독립).
- 기저 행렬(변수 목록·순서·이름)·결과 열·matrix.json 형식 불변. W 행 툴팁: "공칭 깊이 기준 입구 폭 — 깊이를 바꾸면 입구가 2·ΔD·cotθ 더 넓어짐(깊이면 폭 유지)". Q-DM-2.

## 4. W 사용 불가 사유 · 기본 켬
### 4.1 코드(순수 `section.w_reason`, 첫 일치·순서 고정)
| 코드 | 조건 | 근거 | 화면 1줄 |
|---|---|---|---|
| W_USER_OFF | 선택 vars 에서 W 뺌 | `bead_graph.py:591-599` | 사용자가 W 를 뺌 |
| W_NETWORK | 네트워크 묶기 | BG-D-18 | 네트워크 묶기는 깊이만 |
| W_AREA | 모든 세그먼트 area·plateau | BG-D-16·20(d) | 면형 바닥 — 입구 선 없음 |
| W_EDIT_MERGED | S_W = ∅ ∧ merge 편집 세그먼트 | SH-9 | 합친 구간은 폭을 잴 수 없음 |
| W_ENTRY_ONE_SIDE | S_W = ∅(그 밖) | BG-X-3, `absorb.py:300-305` | 입구 선이 한쪽만 있음 |
| W_PARTIAL_OLD | S_W 일부 ∧ 옛 규칙(w_partial 없음) | SH-4 | 일부 구간만 폭(옛 규칙) — 새 스터디에서 가능 |
| W_OPEN_BOUNDARY | elems 열린 경계 | `bead_select.py:1141` | 경계가 판 가장자리에 닿음 |
| W_WIDTH_UNDEFINED | elems 폭 측정 실패 | `bead_select.py:1210-1213` | 폭을 잴 수 없음 |
| W_PAICAD_NONE | paicad 비드에 BEAD_WIDTH 없음 | BD-D-7 | 형상 엔진이 폭 변수를 내지 않음 |
- 기본 끔 사유(W 행 있음, 체크 해제): W_SHORT(BG_SEGMENT_SHORT), W_GUARD_BLOCKED(RG_VAR_BLOCKED), W_FIXED_SKIP(elems fixed_policy skip), W_PAICAD_DEFAULT_OFF.
- 문구 원본 `resources/doe_messages.json`(API 가 text 동봉, 화면 거울 없음).
### 4.2 기본 켬
- W 행이 있고 기본 끔 사유가 없으면 `use_default: true`(graph·elems 명문화 + 시험). paicad 는 paicad 값 그대로(끔이면 사유 표시). 행렬 기본 `doe.default_types [D, W]` 그대로.
### 4.3 위치
- 새 스냅샷: 코어 derive summary·`params.json beads[].w_reason{code}`. API(`DoeParamsOut.beads`·선택 derive 응답)는 옛 스터디도 응답 때 같은 함수로 계산(저장 안 함).
- 화면: 변수 표 비드 묶음 안 W 자리 1줄 — W 행 없음 = 회색 "W 사용 불가 · <문구>"(체크 칸 없음), 기본 끔 = W 행 체크 해제 + 줄 끝 사유. 새 버튼 0.

## 5. 하위 호환 · 해시 · 설정
- 키 없음·entry_fixed 명시: 지금 경로 → `prep/select/{graph.json, range_guard.json, w_clamp.json}`, `select/<sha12>/{basis.npz, basis.bin, basis.json, params.json, derived.json}`, matrix·design.npz·result.json·ranking.csv·보고서·view3d·input_sha256 main 1d71d983 바이트 동일. entry_fixed 는 어떤 문서·해시 보기에도 키를 쓰지 않음(기본값 키 생략 — BG-D-36 선례).
- floor_fixed: basis.json += depth_section·section_rules·graph_vars[].section, 기저 재사용 조건 += `bj.get("depth_section", "entry_fixed")` 일치, D 행 += `section{mode, cot_deg, applied, reason?}`, range_guard 표 머리·key += ds.
- 설정(같은 이름 4곳: `esl/doe/__init__.py` DEFAULTS·backend pydantic·`config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`): `bead_doe.depth_section: floor_fixed`, `bead_doe.depth_section_rules: {theta_min_deg: 15.0, theta_spread_deg: 5.0}` — 최상위 새 키(해시 대상 절 불변). 스냅샷 rules 복사는 floor_fixed 일 때만. `GET /doe/settings += depth_section`.

## 6. API · 스냅샷
| 위치 | 키 | 새 | 옛 |
|---|---|---|---|
| DoeStudyIn | `depth_section: Literal["entry_fixed","floor_fixed"] \| None`(없으면 설정) | – | – |
| params.doe·bead_does.inputs | depth_section(+ depth_section_rules) | 생성 때 고정, 복제 그대로 | 키 없음 |
| DoeStudyOut.inputs | depth_section | 값 | null(화면 "입구 고정(이전)") |
| DoeSettingsOut | depth_section | 설정값 | – |
| params[] D 행 | section{…} | floor_fixed 만 | 없음 |
| beads[](params·derive) | w_reason{code, text} | 응답 때 | 같음(표시만) |
| 단면 그림 section | ds_dD{tier: […]} | 그래프 항상·elems floor_fixed | 그래프도(그림 교정, DM-12) |
- 백엔드→코어: `derive_obj_v2(…, depth_section=, section_rules=)`, `bead_select.derive_obj(…, depth_section=)`, `range_guard_table(…, depth_section=)` — `_graph_call` 시그니처 키만(SH 선례).

## 7. 화면(2560×1440, 새 버튼 0)
- 새 스터디(`DoeStudy.tsx` NewStudy): select 시나리오일 때 기존 옵션 줄에 라디오 2개 "깊이 동작 ○ 입구 고정(깊이면 좁아짐) ● 깊이면 폭 유지(입구 넓어짐)", 기본 = 설정, paicad·④ 숨김. 툴팁: 선택(요소) 비드는 입구 고정에서 사면이 가팔라짐. 같은 줄 우선, 안 되면 +1줄 ≤ 28 px.
- 스터디 머리 칩 1개(load_source 칩 옆): "깊이면 폭 유지" | "입구 고정" | "입구 고정(이전)".
- 변수 표: D 행 DS_FALLBACK 배지 "입구 고정"(툴팁 사유), W 사유 1줄(§4.3).
- SectionMini: 깊이 점선 = (s + ΔD·ds_dD, z + ΔD·dz_dD), ds_dD 없으면 0.
- 3D 미리보기(basis.bin, `GET …/select/basis`): 형식 불변, D vec = 조합 → 입구 넓어짐이 바로 보임.

```
 W_open = W_top + 2·D·cotθ
 입구(판 쪽)
 ─────────┐                  ┌─────────  판(부모 바닥)
           \ θ              /
            \              /   D
             └────────────┘
               W_top = 깊이면(비드 윗면)

 floor_fixed, 깊이 +ΔD                 entry_fixed(그래프, 지금), 깊이 +ΔD
 ──────┐                    ┌──────   ─────────┐              ┌─────────
        \ θ                /                    \ θ           /
         \                /   D+ΔD               \           /   D+ΔD
          \              /                        \         /
           └────────────┘                          └───────┘
 입구 한쪽 +ΔD·cotθ, W_top 그대로        입구 그대로, W_top − 2·ΔD·cotθ
 선택(요소) 방식 지금: 입구·W_top 그대로, 사면 가팔라짐(θ' > θ)
```

## 8. 시험(V-0247-DM-n)
1. 합성 직선 사다리꼴 채널(정렬 quad, 판 600×300, D 10, W_open 40, θ 45°·60°, 필렛 없음, 그래프) floor_fixed ΔD ±3: 달성 깊이 ±1e-6, 직선 구간 깊이면 폭 변화 ≤ 1e-6 mm, 입구 폭 = W_open + 2ΔD·cotθ ±1e-3, 사면 각 θ ±0.05°, A_D ∪ A_W* 밖 max|u| ≤ 1e-9, 뒤집힘 0.
2. 같은 메시 entry_fixed: 입구 변화 ≤ 1e-9, 깊이면 폭 = W_top − 2ΔD·cotθ ±1e-6, 각 ±0.05°, 기저 바이트 = main.
3. 비정렬 H6 ch1 D +2 floor_fixed: 깊이면 폭 변화 ≤ 0.05h, 각 ±1°, 뒤집힘 0. (d) 포켓 C D +2: BG_CORNER_GUARD 없음·뒤집힘 0.
4. elems 1단(synth_bead 원형 D 6·W 40·60°) floor_fixed: 깊이면 노드 평면 이동 ≤ 1e-9, 경계 이동 cotθ·ΔD ±0.02h, 각 ±1°. 2단 경로형 = DS_FALLBACK SELECT_MULTI_TIER·기저 바이트 = entry_fixed.
5. D·W 동시: W_top' = W_top + ΔW ±1e-3, W_open' = W_open + ΔW + 2ΔD·cotθ ±1e-3, 각 ±0.05°, 두 기저 합 = 동시 모핑 ±1e-12.
6. θ: 45°·60° 섞인 묶음 → 길이 가중 + DS_THETA_SPREAD. floor_width 없음·θ < 15° → DS_THETA_PARTIAL, 전부 → DS_FALLBACK THETA_UNMEASURED.
7. W 사유: 코드마다 합성 1개 + 순서 고정. S_W 부분 → DS_PARTIAL·전환 구간 바깥 0.
8. 기본 켬: 사유 없으면 use_default true → default_params 에 B<n>_W(graph·elems). 기본 끔 4사유 = false + 사유.
9. 옛 바이트: main 1d71d983 골든(sel_regress·selreg ①②③, v0.24.6 그래프 스터디 1, ④ regress), 키 없음·entry_fixed 명시 두 스냅샷 — §5 파일 전부·input_sha256·hash_view 동일(다시 기록 금지).
10. 계획 표: 모든 행·열 채움(빈 칸 CONFIG_INVALID), 변이 시험(graph compose → none = entry_fixed 바이트), paicad = 계산 영향 0 + DS_ENGINE_NATIVE, 호출 쪽 시나리오 이름 분기 0건(정적).
11. feasible: floor_fixed 식, entry_fixed 식 바이트 불변, API 거울 `_graph_rows` = 코어 값.
12. range_guard: floor_fixed 후보 = 조합, 같은 비드 D·W combo 묶음, 표 머리 sha 다름. entry_fixed 표 바이트 = main.
13. 침범: 조합 변수 단독 안 BG_OUTSIDE_MOVED 없음, 블렌딩 자름 경고, 고정 노드 이동 ≤ 1e-12(hold 1), DS_HOLD_PINCH.
14. 설정 거울: DEFAULTS = pydantic = yaml 2, 키 없음 해시 불변.
15. API·화면: 모르는 값 422, 스냅샷 = inputs, 복제 = 원 값, 라디오 기본·요청·select 외 숨김, 칩, W 사유 줄, D 배지, SectionMini ds_dD, 2560·1920 새 스터디 scrollHeight 증가 ≤ 28 px, 스터디 화면 ±0.
16. 그림 교정: 그래프 entry_fixed ds_dD = 깊이면 축소 방향, elems entry_fixed = 0.
17. 비용: 합성 120×80(9,801 노드) 비드 5개 BD_MATRIX 기저 시간 floor_fixed/entry_fixed ≤ 1.7, range_guard 준비 비 기록.

## 9. 작업 분해(파일 소유 겹침 없음)
| 묶음 | 모델 | 파일 |
|---|---|---|
| C1 코어 | opus | `esl/morph/section.py`(신규), `esl/doe/bead_graph.py`, `esl/doe/bead_select.py`, `esl/doe/paicad_io.py`(사유·DS_ENGINE_NATIVE 만), `esl/doe/stages.py`, `esl/doe/__init__.py`, `resources/doe_messages.json`, `tests/doe/test_depth_section*.py`, `tests/morph/test_section.py`, 골든 `tests/doe/golden_v0247_c1/` |
| B1 백엔드 | sonnet | `backend/esl_platform/core/config.py`, `config/esl_platform.example.yaml`·`.prod.example.yaml`, `backend/esl_platform/api/schemas.py`, `api/services/doe.py`, `api/services/doe_select.py`, openapi, `backend/tests/test_doe_v0247_*.py` |
| F1 프런트 | sonnet | `frontend/src/api/types.ts`·`doe.ts`, `pages/doe/DoeStudy.tsx`, `components/DoeParamTable.tsx`, `components/SectionMini.tsx`, `mock/*.ts`, `__tests__/depth_section*.test.tsx`, Playwright |
- 순서: C1 이 section.py 시그니처·코드 표 첫 커밋 → B1·F1 병렬 → 통합(메인: CHANGELOG·user.md 깊이 동작 절·admin 설정 2키).

## 10. 미결(결과를 바꾸는 것만 — 기본 가정으로 진행)
- Q-DM-1 W 기저 없는 비드의 깊이면 폭 유지 — 기본: 입구 고정 대체 + DS_FALLBACK(그 비드 결과 = 지금). 대안: 한쪽 입구 평행 이동 기저(패키지 MORPH_RULES +1, R-DM-2).
- Q-DM-2 D·W 동시의 W 의미 — 기본: 공칭 깊이 입구 폭. 대안: floor_fixed 에서 W = 깊이면 폭(공칭·범위·결과 값 변경).
- Q-DM-3 옛 스터디 전환 — 기본: 새 스터디 만들기에서만 선택(복제 = 원 값). 대안: 복제 요청에 depth_section 허용.

## 11. 결정 요약 — 전문 `docs/decisions.md` 2026-11-25 D-0.24.7-DM-1~12.

## 12. 후속(R-DM-n)
- R-DM-1 위치 U/V(그래프·선택 — 사용자 확정 3).
- R-DM-2 W 기저 없는 비드 floor_fixed(한쪽 입구 평행 이동 — 패키지).
- R-DM-3 paicad 깊이 단면 규칙 확인(physicsai shell-morph, 읽기 전용) → 필요 시 요청.
- R-DM-4 선택 방식 다단 비드 floor_fixed.
- R-DM-5 세그먼트별 θ(접합 전환 처리 포함).
- R-DM-6 걸친 섬 옆 W* 감쇠(깊이면 국부 잔차 제거 — 패키지).
