# 계약: 비드 깊이 단면 동작 선택(깊이면 폭 유지·사면 각 고정) + 한쪽 입구 W + W 사용 불가 사유 + 복제 전환 (DM, v0.24.7)

- 상태: 구현 기준(2026-11-25), **개정 1**(사용자 결정 Q-DM-1·Q-DM-3 확정, Q-DM-2 기본 유지, 현장 확인 항목), **개정 2**(검토 — 그래프 floor_fixed = 패키지 kind DF, W1 = 변수 전용, DM-21·22 — 본문 반영됨, §14). 브랜치 `release/v0.24.7`(base main 1d71d983 = v0.24.6). 구현 코드 없음 — 이 문서가 원본.
- 관계: `esl_beadgraph.md` BG-D-16·22·24·25·26·30·32·33·34·BG-X-3·9, §2.5(graph.json 머리)·§8.3(판 정책 — §5.1 이 보강), `esl_bead_shape_v021.md` SH-4~9·SH-13~16·SH-27(S_W·range guard·판), `esl_bead_select.md` §5.3·5.4(선택 기저), `esl_bead_doe.md` BD-D-7(paicad 변수). 충돌하면 새 스냅샷(`depth_section` = floor_fixed)에서 이 문서가 우선.
- 패키지 `beadgraph` **1.1.0 → 1.2.0**(새 기저 종류 DF·W1·측정 함수 `one_side` 추가 — 분류 출력·기존 D·W 기저 바이트 불변, `RULES` 1·`MORPH_RULES` 2 그대로, §5.1). paicad 무변경. `GRAPH_ALGO` 1 그대로. DB migration 없음.
- ID: 결정 `D-0.24.7-DM-n`, 시험 `V-0247-DM-n`, 후속 `R-DM-n`, 미결 `Q-DM-n`, 현장 `F-DM-n`.
- 용어: 화면·매뉴얼 = "깊이면(비드 윗면)"·"입구(판 쪽)". 코드 키·이 문서 내부 = floor(깊이면)·entry(입구). W_open = 입구 폭, W_top = 깊이면 폭, θ = 사면 각(판 평면 기준), **W_open = W_top + 2D·cotθ**. 한쪽 입구 세그먼트: 열린 쪽(o) = 입구 선이 있는 쪽, 고정 쪽(f) = 반대쪽, W1 = 한쪽 폭(§1.6).

### 사용자 요청 (원문, 변경 금지)
- "깊이 깊어짐에 따라 바닥면 간격도 넓어져서 대각사면 각도가 유지되어야하는데 지금은 그렇게 안되어잇지?? 폭이랑 위치는 안되나"
- 확정(2026-11-25):
  1. 깊이 동작에 "바닥 폭 유지(입구 확장), 사면 각 고정" 선택지 추가. 새 스터디 기본은 이 방식, 옛 스터디는 그대로. (사용자 질문 "사면 각도 고정이란 거지?" → 답: 현재 그래프 방식도 각은 유지하지만 입구 고정·바닥 축소이고, 새 방식은 각 고정 + 바닥 폭 고정 + 입구 확장)
  2. W 사용 불가 사유를 변수 표에 표시하고, 쓸 수 있으면 W를 기본으로 켠다.
  3. 위치 U/V는 다음 버전으로 따로(이번 범위 밖, 후속 R-로 기록).
- 확정 2차(2026-11-25, 제안 설명에 대한 원문 "그래"):
  4. Q-DM-1 → **한쪽 입구 이동 W 기저를 이번 버전에 넣는다**(R-DM-2 를 본문으로, 패키지 수정 허용 — 판 규칙 준수). 합의한 효과: #88 처럼 W 기저가 없는 비드에서도 "깊이면 폭 유지"가 동작하고 그 비드들에 W 변수도 생긴다. 대가 = 입구가 한쪽만 벌어져 비드 중심선이 치우침.
  5. Q-DM-3 → **복제 요청에 depth_section 허용**. 복제 창에 같은 라디오 2개, 기본 = 원 스터디 값(옛 스터디 = 입구 고정). 목적 = "#88 을 복제해 깊이 동작 하나만 바꿔 비교" — 나머지 입력 보존, 규칙상 달라지는 것은 화면 1줄.
  6. Q-DM-2 는 기본 그대로: W = 공칭 깊이 입구 폭.
  7. 현장: #88 비드별 W 불가 사유는 서버 LLM 진단 결과로 확인(현장 확인표 항목 — §13).

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
| 입구 선 한쪽만(안쪽 플래토 고리 변 등) | 같은 닮음(열린 쪽만 입구 — 고정 쪽은 §0.3) | 고정 | 열린 쪽만 축소 | 열린 쪽 유지 | 없음(양쪽 입구 노드 각 ≥ 3 일 때만), 새 스냅샷 w_partial = S_W 구간만 | `absorb.py:300-305`, `bead_graph.py:469-483`, BG-X-3·SH-4~7 |
| 선택 방식(src elems) | 단 k 깊이면 = 법선 n, 사면 = 높이 비 s × n, 경계 0 — **평면 성분 없음** | 고정 | **유지** | **가팔라짐**(tanθ' = (D+ΔD)/(D·cotθ)) | 경계 ½ê, 사면 (1 − s'(1−f))·w, f = floor_follow(기본 1 = 단면 평행 이동), 닫힌 경계만 | `bead_select.py:1416-1430`, `:1433-1462`, `:1141`, `esl_bead_select.md:143-161`, V-BS-1(`:361`) |
| paicad(옛 ③ step·① same·② mesh) | `shell update`(CAD 피처 BEAD_DEPTH) → `shell morph` | **미확인** | 미확인 | 미확인 | BEAD_WIDTH | `esl_bead_doe.md:10·36·66·69`, `paicad_io.py:271-292`(값 통과만). 원본·shell-morph 계약 이 세션 접근 불가 → R-DM-3 |
| ④ compare | 모핑 없음(사용자 형상) | – | – | – | – | `transfer_plan.py` compare_per_shape |

### 0.2 발견
1. 그래프 D 는 각을 지키나 입구 고정 → 깊이면이 한쪽당 ΔD·cotθ 줄어든다. 선택 D 는 깊이면을 지키나 사면이 가팔라진다. 어느 모드도 "입구 확장·각 고정·깊이면 유지"가 아니다.
2. #88 B8 의 −1.98 %/mm 에는 깊이 +1 mm 당 깊이면 −2cotθ mm 가 섞여 있다(깊이·폭 효과 분리 불가).
3. 단면 미니 그림이 그래프 D 를 틀리게 그린다: `bead_graph.py:900-903` `dz_dD = clip(z/D_nom)`(수직 늘임만 — 선택 방식 모양) → `SectionMini.tsx:16-24` 는 "깊이면 유지·사면 가팔라짐"으로 보이나 실제 기저는 깊이면 축소·각 유지.
4. feasible D 상한 (W_entry − W_floor_min)/2·W 하한 2·D_nom + W_floor_min 은 45° 가정(`bead_graph.py:1006-1017`, `doe_select.py:726-733` 거울).
5. W 행이 없을 때 사유 기록 없음(`bead_graph.py:479-483`·`:992`). W 가 가능하면 use_default 는 이미 true(`bead_graph.py:1096-1103` — BG_SEGMENT_SHORT·RG_VAR_BLOCKED 만 끔, elems `bead_select.py:1410` fixed skip, 행렬 기본 `doe.default_types [D, W]` `matrix.py:47-58`·`doe.ts:1072-1077`).

### 0.3 한쪽 입구 세그먼트 · 판 기록 · 복제 (개정 1 보강 — W1·복제 근거)

| 항목 | 지금 동작 | 근거(파일:행) |
|---|---|---|
| 입구 노드 | 세그먼트 벽 노드 ∩ 부모 바닥 노드. 골격까지 평면 거리·쪽(side ±, 진행 방향 왼쪽 +)·골격 끝 투영 제외(interior) | `absorb.py:296-303`, `absorb.py:31-71`(`polyline_dist`·`interior_mask`) |
| entry_width | 입구 노드 < 6 이면 null, 양쪽 interior 각 ≥ 3 일 때만 2·median(d) — 한쪽만이면 null | `absorb.py:300-305`, BG-X-3 |
| 골격 = 깊이면 중심선 | floor_w = 2·median(거리 변환) → 골격에서 양쪽 깊이면 가장자리 거리가 같음(래스터) | `skeleton.py:507` |
| W 기저 | entry_width null 세그먼트가 있으면 ValueError → esl 은 그 비드에 W 를 만들지 않음 | `morph.py:221-224`, `bead_graph.py:479-483` |
| W 이동 | 이동 노드 = E ∪ 벽 ∪ 깊이면 가장자리(양쪽), u = ½·n_out(대칭), 램프 ext_eff = ½·ext, R_w = k·ext/2 | `morph.py:228`·`:270-279` |
| W 구역 | E = Z_W 노드 ∩ 부모 바닥 노드, J = 비드 밖 요소와 공유(W 는 배타 자식 Z_C 를 바깥으로 안 봄), A_W = Z_F ∪ Z_W ∪ Z_I(+ 부모 바닥 띠) | `zones.py:176-188` |
| 고정 쪽 경계 — 깊이면 조화 확장 | Dirichlet = 배타 자식(nC)·공유 자식 벽(nSC)·섬·J·바깥 요소 노드. **판 외곽 자유 모서리는 Dirichlet 아님**(자연 경계 → 깊이면과 함께 평면 이동) | `morph.py:308-309` |
| 고정 쪽이 공유 자식 벽(고리 안 플래토) | D: 벽 높이 비 선형(깊이면 1 → 자식 0), 평면 0 → **고정 쪽 사면 가팔라짐**(지금도) | `morph.py:259-266`, BG-D-23 |
| 고정 쪽이 배타 자식 | D: 자식 부분 트리 강체 s·ΔD·n0 → 고정 쪽 벽 평행 이동(각·폭 유지) | `morph.py:257`, BG-D-23 |
| 고정 쪽 비드 소유 벽(self·other 전이) | D 닮음 중심 = 평면 최근접 입구 = **건너편 입구** → 평면 성분 ≈ (폭/D)·ΔD(드묾, 지금 동작) | `morph.py:239-251` |
| 달성 W | 입구 노드 골격 거리 중앙값 변화 × 2 = ΔW | `checks.py:172-193` |
| merge 편집 | 합친 세그먼트 entry_width null | `edits.py:234-235`, SH-9 |
| 판 기록 | graph.json 머리 `version`(= `__version__`)·`morph_rules`·병합 cfg 전체 → graph sha(선택 sha 에 포함), `prep/input.json graph.beadgraph_version`, `basis.json beadgraph_version·morph_rules`, 기저 재사용 = `morph_rules` 같음 | `classify.py:483-485`, `bead_graph.py:162-163`·`:197`, `stages.py:6789-6790`·`:6853-6854`, SH-27 |
| 복제 | 본문 키 `title` 만(그 밖 422), 스냅샷 `doe` 에서 rev·**spec**·matrix_sha256·run·design·paicad·selection 제외(변수·범위·방법·seed 안 남음), 선택 = 원 문서 복사(원 준비 메시와 맞을 때 — 같은 sha), cfg = 지금 설정, rank = 지금 설정(RANK_REFRESHED), 준비 다시 | `backend/.../services/doe.py:1707-1711`·`:1767-1791`, `doe_select.py:1185-1197` |
| 복제 화면 | [복제] = 창 없이 즉시. 변수 표 = `s.doe.spec` 있으면 그 변수만 체크·범위 미리 채움, 없으면 서버 기본 | `DoeStudy.tsx:1829-1833`·`:1739`, `:1576-1590` |

6. 한쪽 입구 세그먼트는 W 기저가 없다(고리 변(안쪽 플래토)·이웃 단차 옆 채널) → W 변수는 W1(§1.6). 깊이는 개정 2 DF(§1.2)가 입구 쪽 수와 무관하게 처리.
7. 판 외곽 자유 모서리는 D 조화 확장의 자연 경계라 W1 평행 이동으로 고정 쪽을 붙잡을 수 없다 → W1 변수 불가(W_ONE_SIDE_EDGE). DF 는 깊이면 평면 0 이라 영향 없음.
8. 패키지 판을 올리면 graph.json 머리 `version` 이 바뀌어 graph sha → 선택 sha·`select/<sha12>` → 옛 스냅샷 바이트와 `BG_GRAPH_STALE`(복제·준비 다시 = 선택 재확인)가 깨진다(SH-27 이 판을 안 올린 이유). → §5.1 출력 판 고정.
9. 복제는 변수·범위를 남기지 않는다 → "깊이 동작 하나만 바꿔 비교"하려면 원 spec 을 미리 채워야 한다(§6.1).

## 1. 새 동작

### 1.1 공통 키
- `depth_section: entry_fixed | floor_fixed` — 요청 `DoeStudyIn`·복제 요청·작업 스냅샷 `params.doe.depth_section`·`bead_does.inputs.depth_section`·`DoeStudyOut.inputs` 같은 이름, 모든 시나리오에 저장(적용 여부 = §1.5 계획 표).
- entry_fixed = 지금 모드별 동작(§0.1). floor_fixed = 깊이면 폭 유지 + 사면 각 고정 + 입구 넓어짐(그래프 = 패키지 kind DF §1.2.1, elems = 조합 §1.2.2) + 한쪽 입구 W1 변수(§1.6).
- 키 없음(옛 스냅샷) = 호환 상수 `LEGACY_DEPTH_SECTION = "entry_fixed"`(`esl/morph/section.py`, 값 고정이 목적 — D-0.24.5-VT-16 선례). 새 스터디 기본 = 설정 `bead_doe.depth_section`(floor_fixed). 복제 = 요청 값, 없으면 원 값(§6.1).

### 1.2 floor_fixed 깊이 기저
#### 1.2.1 그래프 = 패키지 kind `DF`(깊이면 가장자리 중심 닮음 — DM-21)
`basis()` 항목 `{name, kind: "DF", segs, zones?, hold}`. `morph._one`(D 갈래 `morph.py:243-268`·`:325-367`)의 거울, 변수 ΔD 당 변위 — 아래 순서로 계산:

| 단계 | 규칙(근거) |
|---|---|
| 구역 | `bead_zones(M, segs, zones, "D")`(ZC·ZSC·공유 자식 J 를 D 와 같게 — `zones.py:176`·`:189-200`). 노드 집합 = D 와 같은 `edge = nF & nW & ~E`·`walln = nW & ~E & ~nF`(`morph.py:239-240`), E·J 그대로. 허용 요소 A_DF = D `allowed_el` ∪ 부모 바닥 ∪ 부모의 걸치지 않은 섬(W `A_el` 추가분 `:320-321`), `mov = movable_nodes(M, A_DF)` |
| 깊이면 | nF ∪ (nC 중 벽·입구 아닌 것) = s·n0(`:255`·`:257`), **평면 0** — 조화 확장(`:307-314`)·코너 가드(`:329-360`) 없음 |
| 벽·입구 | x ∈ walln ∪ E 마다 `cKDTree(M.P[edge])` 평면 최근접 깊이면 가장자리 x_f, h = |(x − x_f)·n0|, D_col = h(x ∈ E, ≤ 1e-6 이면 D_nom)·D_nom(벽) — `:246-250` 의 거울. 법선 s·(1 − clip(h/D_col, 0, 1))·n0(입구 0), 평면 = r·n_out, r = (x − x_f)_평면·n_out / D_col. 결과: 벽(높이 비 t, 깊이면 1) 법선 t·s, 평면 (1 − t)·cotθ_local 바깥, 입구 평면 cotθ_local. 자기 골격 interior 투영이 없는 입구·벽 기둥(현 방향)의 r 상한 = interior 입구 r 의 최댓값(벽은 ×(1 − t)) — 깊이면 가장자리가 접합 구역에서 끝나는 곳의 현 과대 방지(DM-C1-1, `info.chord_capped_n`) |
| 방향 n_out | mv = E ∪ edge ∪ walln. 노드의 자기 세그먼트 = 그 노드를 포함한 Z_W ∪ Z_F 요소의 `labels["segment"]` 값 ≥ 0(접합 구역·섬 요소 = −1, `classify.py:368-371`). nref = 최근접 골격(`_skeleton_dist(M, S, ·)` — 최근접 세그먼트 id 도 반환하게, W 호출 바이트 불변)이 **자기 세그먼트 것이고 `interior_mask` 참**이면 그 바깥 법선, 그 밖(골격 없음·끝단 투영·접합 구역·네트워크에서 남의 세그먼트 골격이 최근접)은 현 (x − x_f)_평면 정규화. 평활은 두 경우 공통 `_smooth_dirs(M, ZW \| ZF, mv, idx, nref, w_smooth_iters)`(`:270-273`). 근거: 비정렬 메시에서 짝이 비스듬하면 입구 선이 cotθ·ΔD·sin(어긋남) 만큼 물결 |
| 공유 자식 벽 | `:259-268` 그대로(ZSC 높이 선형·평면 0 — 벽 규칙 뒤에 덮어씀, BG_SHARED_CHILD) |
| 걸친 섬 옆 | `:337-348` 의 κ 를 walln ∪ E 평면 성분에 곱함(띠 복사 전, 잔차 R-DM-6) |
| 부모 바닥 띠 | W 블록 `:277-305` 그대로(pf·others·SELECT_BLEND_CLIPPED·band_islands), 값 = **거리 가중 혼합**(DM-C1-2): 띠 노드 x 에 R_w 안 입구 노드 k(가까운 순 최대 8개)로 u(x) = [Σ_k w_k·u_k / Σ_k w_k] × (1 − smoothstep(d_min/R_w)) × smoothstep(d_o/R_w)(다른 형상 근처 자름 그대로), w_k = 1/(d_k² + (0.1h)²) — 한 입구 선만 가까우면 최근접 복사와 거의 같고 마주 보는 두 입구 선 사이에서 연속(E 법선 0 → 평면만). W(기존 kind) 띠는 최근접 복사 그대로(D·W 기저 바이트 불변). R_w = max(`blend.min_mm`, `blend.k`·ext·r_max, 3h), r_max = max r(E) |
| 램프·hold | L = D 식(ext_eff = ext, `:227-229`), ψ = `_hold`, φ = `_ramp(J, allowed_n)`, Uv ×= φψ, Uv[J] = 0. **Uv[E] = 0 안 함**(`:328`·`:367` 은 D 만) |
| 섬·바깥 0 | `:368-410` 그대로(rim_src = nF ∪ 띠), allowed_n = nmask(A_DF) ∪ 띠, Uv[~(allowed_n & mov)] = 0 |
| 달성 | D 와 같은 법선 점검 ach = nF & φ ≥ 1 & ψ ≥ 1 & ~섬 & ~E(`:414`, c 없음)·BG_SEGMENT_SHORT. `checks.achieved`(법선)·`allowed_elements`(A_DF) 가 kind DF 처리 |
| info | D 키 + `blend_mm`·`band_n`·`cot_min/med/max`(φ = ψ = 1 인 E 의 r)·`entry_wave_mm`·`wall_no_entry_n`(§2.6) |
- 성질: 노드 기둥마다 실제 각 유지(θ 측정·평균 없음), 깊이면 평면 0(구성), 입구 = 그 벽의 cotθ_local·ΔD — 양쪽·한쪽·벽마다 다른 각 모두. 판 외곽에 닿은 깊이면도 평면 0.
- 적용: E ≠ ∅ 인 모든 그래프 비드 — 세그먼트(양쪽·한쪽)·**네트워크 묶기·면형 바닥·merge 구간** 포함. E = ∅ 만 entry_fixed + `DS_FALLBACK{reason: W_ENTRY_NONE}`.
- 이름 `B<n>_D` 그대로(basis.json `graph_vars[].kind` = "D" + `section.mode = floor_fixed`), 대칭 묶기(BG-D-21) = 구성 비드 DF 의 합. 띠·허용 구역 코드는 W·DF·W1 공용 내부 함수 1개(§9 — D·W 바이트 불변).

#### 1.2.2 elems = 조합(esl 코드, 패키지 무관)
- B'_D = B_D + 2cotθ·B_W(f=0): B_D = `_depth_basis`(k = 1), B_W(f=0) = `_width_basis` 를 floor_follow 0 으로(경계 ½ê, 사면 (1 − s')·w, 깊이면 0, 블렌딩 Wendland — 비드 칸 floor_follow 와 무관), cotθ = §1.3. 내부 항목 `B<n>_D~w` 는 행렬·결과·basis.bin 에 안 나감, 달성 깊이는 B_D 부분으로 점검.
- 검산: 사면 노드(높이 비 t) 변위/ΔD = 법선 t + 평면 바깥 (1 − t)·cotθ → 입구 +cotθ, 깊이면 평면 0, run' = (D+ΔD)·cotθ → θ 유지, W_open' = W_open + 2ΔD·cotθ. W1 없음(R-DM-10), DF 식 전환 = R-DM-11.

### 1.3 θ
- 그래프: 측정·평균 없음(DF 가 노드마다 실제 각). 표시·feasible 용 `section.cot_deg` = atan(1/cot_med)(DF info), 진단 cot_min/max_deg.
- derive 시점(API·params 행 — 기저 전)의 cotθ(feasible·`section.cot_deg`)는 추정값: `one_side` run/D 세그먼트 중앙값(양쪽 입구는 (entry_width − floor_width)/2/D). 기저가 생긴 뒤 basis.json 진단 cot_min/med/max 가 실제 값(DM-C1-4).
- elems: cotθ = run_med / D_1nom(`bead_select.py:1217-1226`). run_med ≤ 0 ∨ θ < `theta_min_deg`(15) → entry_fixed + `DS_FALLBACK{reason: THETA_UNMEASURED}`, 경계 거리(dd) 5·95 백분위로 잰 θ 차 > `theta_spread_deg`(5) → 정보 `DS_THETA_SPREAD{bead, min_deg, max_deg}`. 두 규칙은 elems 에만.

### 1.4 적용·대체
| 경우 | 동작 | 경고 |
|---|---|---|
| 그래프 E ≠ ∅(양쪽·한쪽·네트워크·면형·merge·판 외곽 옆) | DF | 한쪽 세그먼트가 있으면 정보 `DS_ONE_SIDE`(§1.6.3) |
| 그래프 E = ∅ | entry_fixed | `DS_FALLBACK{bead, var, reason: W_ENTRY_NONE}` |
| elems 열린 경계·폭 미정·단 수 ≥ 2·θ 실패 | entry_fixed(지금 선택 동작) | `DS_FALLBACK{reason: W_OPEN_BOUNDARY\|W_WIDTH_UNDEFINED\|SELECT_MULTI_TIER\|THETA_UNMEASURED}` |
| paicad | 적용 안 함 | 스터디 정보 1개 `DS_ENGINE_NATIVE`(floor_fixed 스냅샷만) |
| ④ compare | 해당 없음 | 없음 |
- DF·elems 조합은 `shape_rules.w_partial` 과 무관 — w_partial 은 W **변수** 구간에만(§1.6.1).

### 1.5 계획 표(AGENTS.md — 모드 차이는 열로)
신규 `esl/morph/section.py`(모드 무관, numpy 만, `esl.doe`·`beadgraph` import 금지, IO·설정 해석 금지) `SECTION_PLANS` — 키 = 변수 출처(행을 만드는 쪽이 아는 값):

| 행 | compose | one_side | theta | feasible | fig | na |
|---|---|---|---|---|---|---|
| graph | pkg_df | pkg_w1 | none | open_cap | floor_center | none |
| elems | select_w_f0 | none | run_med | open_cap | stretch | none |
| paicad | none | none | none | none | none | DS_ENGINE_NATIVE |
| none | none | none | none | none | none | none |
- 모든 열 필수(빈 칸 = `CONFIG_INVALID`). 호출 쪽(`bead_graph`·`bead_select`·`paicad_io`·`stages`)은 열 값으로 공용 함수를 고르고 시나리오 이름으로 분기하지 않는다. `compose = none` 이면 entry_fixed, `one_side = none` 이면 W1 변수 없음(변이 시험). one_side 는 **W1 변수·사유 판정 전용**.
- 공용 함수: `resolve(value)`, `cot_from_run(run_med, D, rules)`·`cot_from_df(info)`(cot_min/med/max → 도), `compose(d_idx, d_vec, parts=[(w_idx, w_vec, k)…])`·`w_virtual_range(W_nom, dD_ext, cot)`(둘 다 elems 전용), `feasible_open_cap(D_nom, parts=[(W_ref, m)…], cot, depth_max_rel, width_max_rel)`(parts 빈 = D_nom(1+depth_max_rel)), `w1_feasible(W1_nom, F_nom, W_floor_min, width_max_rel)`, `fig_ds_dD(s, z, D_nom, cot, row, R_w, side=None)`, `w_reason(...)`, `clone_depth(orig, req)`(§6.1), `hash_view(ds, rules, has_elems)`, 상수 `DEPTH_SECTIONS`·`LEGACY_DEPTH_SECTION`·`SECTION_PLANS`.

### 1.6 한쪽 입구 W 변수 W1 (사용자 확정 4 — DM-13~16·22, floor_fixed 그래프 스냅샷만, **변수 전용**)

#### 1.6.1 구간 분류(세그먼트 s ∈ S, 순수 — `section` 이 `one_side` 측정값으로)
| 집합 | 조건 | W 변수(`B<n>_W`) |
|---|---|---|
| S_2 | entry_width 있음(양쪽 interior 각 ≥ 3) | 지금 규칙: w_partial 이면 S_2 ≥ 1, 옛 규칙이면 S_2 = S(SH-4) |
| S_1 | entry_width null ∧ area·plateau·merge 결과 아님 ∧ 한쪽 interior 입구 노드 ≥ n_min ∧ 반대쪽 < n_min ∧ 고정 쪽 판 외곽 자유 모서리 노드 < n_min | **S_2 = ∅ 일 때만** W1: w_partial 이면 S_1 ≥ 1(부분 = `BG_W_PARTIAL`), 옛 규칙이면 S_1 = S |
| S_0 | 나머지 | – |
- n_min = `bead_doe.depth_section_rules.one_side_min_nodes`(3 — BG-X-3 과 같은 값, 설정 키는 §5.2. `select.graph` 키를 늘리지 않음 = graph.json cfg 블록·graph sha 불변).
- "S_2 = ∅ 일 때만" — 이미 W 가 있는 비드의 W 변수 뜻을 바꾸지 않는다(복제 비교 보존, §6.1). 깊이는 S 구분 없이 DF(§1.2.1).
- 네트워크 묶기(BG-D-18)는 지금처럼 W 없음(W_NETWORK), 깊이 = DF.

#### 1.6.2 측정 — 패키지 `beadgraph.one_side(graph, labels, nodes, elems, segs, *, min_nodes)` (신규 공개 함수, 결정적, 1e-3 반올림)
- s 의 입구 노드 E_s(§0.3 과 같은 집합), `polyline_dist`·`interior_mask` 로 쪽 σ·거리 d. n+ / n− = interior 쪽별 수. 열린 쪽 σ_o = 큰 쪽(같으면 +).
- d_o = median d(열린 쪽 interior E_s), d_eo = median d(열린 쪽 깊이면 가장자리 노드 = Z_F ∩ Z_W 노드 − E, interior), d_f = median d(고정 쪽 깊이면 경계 노드 = Z_F 노드 중 Z_F 밖 요소와 공유하거나 자유 모서리에 있는 것, interior).
- 반환 `{seg: {side, n_open, n_other, d_open, d_edge_open, d_fixed, width = d_o + d_f, floor = d_eo + d_f, run = d_o − d_eo(진단), fixed: {child, shared, junction, edge, own_wall}, ok, reason: null|NONE|EDGE|TWO_SIDED|AREA|MERGED}}` — fixed = 고정 쪽 경계 노드가 닿는 것별 수(배타 자식 nC·공유 자식 벽 nSC·J·판 외곽 자유 모서리(구멍 고리 제외 — BG-D-10)·비드 소유 벽 nW).
- **W1 공칭** W1_nom = Σ len·width / Σ len(S_1) = "열린 쪽 입구 선 ~ 반대쪽 깊이면 가장자리" 폭. 깊이면 폭 F_nom = Σ len·floor / Σ len.
- 호출 = esl derive(API·BD_MATRIX 같은 코드, floor_fixed 그래프 스냅샷·`one_side = pkg_w1`, entry_width null 세그먼트만 — 편집(split) 뒤 세그먼트도 같은 식). 캐시 파일 없음(비용 V-0247-DM-27).

#### 1.6.3 W1 기저 — 패키지 `basis()` 항목 `{name, kind: "W1", segs: S_1, hold, ramp: "end", min_nodes}`
| 부분 | 규칙 |
|---|---|
| 열린 쪽 이동 | (E ∪ 벽 ∪ 깊이면 가장자리) 노드 중 골격 쪽 = σ_o 인 것: u = **ΔW·n_out**(W 의 ½ → 1, 같은 바깥 방향장 `_smooth_dirs`) — 입구·벽·가장자리 평행 이동(열린 쪽 사면 각 유지) |
| 고정 쪽 | Z_F ∪ Z_W 노드 중 쪽 = −σ_o 인 벽·가장자리·경계 노드 = **0**(Dirichlet) |
| 깊이면 안 | 평면 조화 확장(Dirichlet: 열린 쪽 값, 고정 쪽 0, 자식·공유 자식 벽·섬 둘레·J = 0 — W 와 같은 연산자·자유 집합) → 직선 구간 선형으로 늘어남, 법선 성분 0 |
| 램프 | `ramp: "end"`(유일 값) = J 중 **고정 쪽 interior 투영 노드는 램프 원점에서 뺌**(Dirichlet 0 만 — 이웃 비드가 옆으로 붙어도 열린 쪽이 ΔW 에 닿음). L = max(`ramp_k`·ext, `ramp_k`·h), ext_eff = ext(한쪽 이동량 = ΔW) |
| 블렌딩 띠 | 열린 쪽 E 에서만, R_w = max(`blend.min_mm`, `blend.k`·ext, 3h) — W 식의 한쪽 이동량 ½ext → ext. 값 = DF 와 같은 거리 가중 혼합(§1.2.1 띠 행, DM-C1-2) |
| hold·섬·바깥 0 | ψ(BG-D-28)·섬 강체·걸친 섬(BG-D-27·47)·`movable_nodes`·A_W1 = A_W(BG-X-9 `allowed_elements(S_1, "W")`)·`BG_BASIS_LEAK` = W 규칙 그대로 |
| 달성 | φ = ψ = 1·직선 표본 열린 쪽 E 의 골격 거리 중앙값 변화 = ΔW ± 1e-3(W 의 ×2 → ×1). `checks.achieved` 가 kind W1 처리 |
- 효과(사용자 합의): ΔW 에 깊이면 폭 +ΔW·W1 +ΔW, 고정 쪽 불변, **깊이면·입구 중심선이 열린 쪽으로 ΔW/2 치우침**. 변수 행 표시 "한쪽 입구만 이동"(§4).
- 정보 `DS_ONE_SIDE{bead, segs:[앵커], open_side_deg(n_out 평균 방위), fixed:{child, shared, junction, own_wall}, steep_deg:[θ_f, θ_f']|null}` — W1 변수가 있거나 DF 비드에 한쪽 세그먼트가 있을 때 1개.

#### 1.6.4 DF 한쪽 단면 검산
- 열린 쪽: 입구 +cotθ·ΔD 바깥, 깊이면 가장자리 평면 0·법선 ΔD, 깊이면 안·고정 쪽 깊이면 경계 평면 0·법선 ΔD → run' = (D+ΔD)·cotθ(**θ 유지**), W_top' = W_top(**깊이면 폭 유지**), W1' = W1 + cotθ·ΔD, 입구 중심선 cotθ·ΔD/2 치우침.
- 고정 쪽 단면은 반대쪽 종류에 따라(D 갈래 동작 그대로):

| 고정 쪽 | DF 결과 | 각 | 깊이면 폭 | 처리 |
|---|---|---|---|---|
| 배타 자식(Z_C) | 자식 강체 s·n0 하강(BG-D-23) → 고정 쪽 벽 평행 이동 | 유지 | 유지 | – |
| 공유 자식 벽(Z_SC — 고리 안 플래토) | 벽 높이 선형: 발 ΔD 하강·위 고정, 평면 0 | **가팔라짐** tanθ_f' = (h_f + ΔD)/r_f | 유지 | DS_ONE_SIDE steep_deg(+ΔD_ext 값), Q-DM-4 |
| 이웃 비드·접합 구역(J, step 벽) | J 0, 램프가 L 안에서 깊이를 줄임(지금 그대로) | 유지(램프 밖) | 유지(램프 밖) | 잔차 = §2.6 |
| 비드 소유 벽(self·other 전이) | DF 벽 규칙(자기 깊이면 가장자리 중심), 윗단 = J 에서 0·램프 φ 로 이어짐 | J 행과 같음 | 유지 | DS_ONE_SIDE `own_wall`, 진단 `wall_no_entry_n`, F-DM-3 |
- 판 외곽 자유 모서리 쪽: DF 는 깊이면 평면 0 이라 정상. W1 변수만 불가(W_ONE_SIDE_EDGE, Q-DM-6 — 조화 확장의 자연 경계).

## 2. 범위·판정(floor_fixed 만 — entry_fixed 는 지금 식·바이트)
### 2.1 feasible
- D: [지금 하한, min(D_nom(1+depth_max_rel), D_nom + W_ref·width_max_rel/(m·cot))] — **입구 확장 상한**. 그래프: entry_width 있는 비드 m = 2·W_ref = S_2 entry_width 길이 가중, S_2 = ∅ ∧ W1_nom 있는 비드 m = 1·W_ref = W1_nom, cot = cot_med(DF — derive 시점은 §1.3 추정값, DM-C1-4). 둘 다 없는 비드(면형·네트워크·merge) = D_nom(1+depth_max_rel) 만(나머지는 range guard §2.2). elems: m = 2, W_ref = W_nom, cot = §1.3. (W_entry − W_floor_min)/2 항 없음.
- W(양쪽): 하한 = W_nom − (W_top_nom − W_floor_min), W_top_nom = W_nom − 2D_nom·cot(45° 면 지금 식). 상한 그대로. 기본 범위 그대로.
- **W1**: 하한 = W1_nom − (F_nom − W_floor_min), 상한 = W1_nom·(1 + width_max_rel), 기본 범위 = W1_nom·(1 ± `select.range` W 비율). API 거울 `_graph_rows` 같은 식(`section` 함수 공용).
### 2.2 range_guard·combo·range_check
- 새 스냅샷: 준비 후보(`_candidate_bases`)·BD_MATRIX 보충이 floor_fixed 깊이 기저(DF·elems 조합) 사용. 단일 세그먼트 후보에 S_1 세그먼트의 W1 추가(항목 key kind `W1`). 표 머리 cfg_sha256·항목 key += ds(floor_fixed 만). 부모 쪽 오목 코너·이웃 비드 사이 압축·입구 코너(ΔD < 0) 뒤집힘은 여기서 범위로 막는다(뒤집힘·넓이 비 기준 그대로, 막지 않고 표에 표시).
- combo: 같은 비드 D·W(W1) 가 영향 요소 공유 → `range_guard.interacting` 자동 묶음(입구 동시 확장 점검).
- shape_rules 없음: `range_check`·`clamp_w_ranges`·`w_clamp` 후보가 floor_fixed 깊이 기저·W1 도 같은 W 경로로.
### 2.3 코너 가드
- DF 갈래에 코너 가드 없음(깊이면 강체 — 가드 대상 없음, cfg 대입 불필요, `BG_CORNER_GUARD` 없음). entry_fixed D 는 그대로. 걸친 섬 감쇠는 §1.2.1(잔차, R-DM-6).
### 2.4 침범
- 바깥 이동(BG-D-34·BG-X-9) 허용: DF = A_DF 1개(§1.2.1, strict 노드 규칙 BG-D-47), elems = strict(D) ∪ strict(W f0), W1 = A_W. 누출(BG-D-32)은 기저마다.
- 다른 비드(SR-D-38)·체결부 hold ψ(BG-D-28)·섬(BG-D-29)·블렌딩 자름 = 기존 규칙. DF·W1 입구 노드에 ψ < 1 있으면 정보 `DS_HOLD_PINCH{bead, n}`.
### 2.5 블렌딩 R·램프
- DF: R_w·L = §1.2.1. W1: §1.6.3.
- elems: 비드 blend_mm 그대로. 닿으면 자름 + `SELECT_BLEND_CLIPPED`.
### 2.6 진단(실패 아님)
- `basis.json graph_vars[] += section{mode, cot_min_deg, cot_med_deg, cot_max_deg, floor_plan_max_mm(기대 0 — ψ·φ 로만 생김), entry_wave_mm(직선(nout = nref)·φ = ψ = 1 입구 노드 평면 이동량의 표준편차, +ΔD_ext), band_clipped, wall_no_entry_n(윗단이 입구 아닌 비드 소유 벽 노드 수 — J 에서 0, φ 로 이어짐), one_side?{segs, fixed, steep_deg, center_shift_mm}}`(floor_fixed 만).

## 3. W·D 동시 켬
- W = 공칭 깊이 입구 폭(사용자 확정 6 — 이름·공칭·범위·결과 열 `B<n>_W` 불변), ΔW = 단면 평행 이동.
- floor_fixed 양쪽: W_top' = W_top + ΔW, W_open' = W_open + ΔW + 2ΔD·cotθ(벽마다 실제 θ — DF), θ 불변 — D = 깊이, W = 폭(선형 합, 서로 독립).
- floor_fixed 한쪽(W1 비드): W_top' = W_top + ΔW, W1' = W1 + ΔW + cotθ·ΔD, 열린 쪽 θ 불변, 고정 쪽은 §1.6.4 표 그대로(ΔW 무관), 중심선 치우침 = ΔW/2 + cotθ·ΔD/2(DF 한쪽 + W1).
- 기저 행렬(변수 목록·순서·이름)·결과 열·matrix.json 형식 불변. W 행 툴팁: 양쪽 "공칭 깊이 기준 입구 폭 — 깊이를 바꾸면 입구가 2·ΔD·cotθ 더 넓어짐(깊이면 폭 유지)", 한쪽 "한쪽 입구만 이동 — 열린 쪽 입구·벽·깊이면 가장자리가 ΔW 이동, 반대쪽 고정(중심선 ΔW/2 치우침)".

## 4. W 사용 불가 사유 · 기본 켬
### 4.1 코드(순수 `section.w_reason`, 첫 일치·순서 고정)
| 코드 | 조건 | 근거 | 화면 1줄 |
|---|---|---|---|
| W_USER_OFF | 선택 vars 에서 W 뺌 | `bead_graph.py:591-599` | 사용자가 W 를 뺌 |
| W_NETWORK | 네트워크 묶기 | BG-D-18 | 네트워크 묶기는 깊이만 |
| W_AREA | 모든 세그먼트 area·plateau | BG-D-16·20(d) | 면형 바닥 — 입구 선 없음 |
| W_EDIT_MERGED | S_2 ∪ S_1 = ∅ ∧ merge 편집 세그먼트 | SH-9 | 합친 구간은 폭을 잴 수 없음 |
| W_TIE_MIXED (신규) | floor_fixed: 대칭 묶음 구성원의 W 종류(양쪽·한쪽·없음)가 다르거나 W1 열린 쪽이 거울이 아님 — **422 아님**, D 는 묶음 | §4.4 | 대칭 묶음의 폭 종류가 달라 깊이만 묶음 |
| W_ONE_SIDE_EDGE (신규) | floor_fixed: S_2 = ∅ ∧ 한쪽 후보가 모두 고정 쪽 판 외곽 — **W1 변수 사유만**(깊이는 DF 적용) | §1.6.1·Q-DM-6 | 반대쪽이 판 가장자리 — 한쪽 이동 불가 |
| W_ENTRY_NONE (신규) | floor_fixed: S_2 = S_1 = ∅ ∧ 어느 쪽도 입구 노드 ≥ n_min 아님(E = ∅ 이면 깊이도 DS_FALLBACK 같은 코드 §1.4) | §1.6.2 | 입구 선을 찾지 못함 |
| W_ENTRY_ONE_SIDE | entry_fixed·키 없음 스냅샷: S_W = ∅(그 밖) | BG-X-3, `absorb.py:300-305` | 입구 선이 한쪽만 있음 — '깊이면 폭 유지' 스터디에서 한쪽 W 가능 |
| W_PARTIAL_OLD | S_2(또는 W1 후보 S_1) 일부 ∧ 옛 규칙(w_partial 없음) | SH-4 | 일부 구간만 폭(옛 규칙) — 새 스터디에서 가능 |
| W_OPEN_BOUNDARY | elems 열린 경계 | `bead_select.py:1141` | 경계가 판 가장자리에 닿음 |
| W_WIDTH_UNDEFINED | elems 폭 측정 실패 | `bead_select.py:1210-1213` | 폭을 잴 수 없음 |
| W_PAICAD_NONE | paicad 비드에 BEAD_WIDTH 없음 | BD-D-7 | 형상 엔진이 폭 변수를 내지 않음 |
- W 행 표시(가능 — 사유 아님): **W_ONE_SIDE** = W 행이 W1(§1.6) — "한쪽 입구만 이동"(툴팁 §3). 행 `w_side: "one"`.
- 기본 끔 사유(W 행 있음, 체크 해제): W_SHORT(BG_SEGMENT_SHORT), W_GUARD_BLOCKED(RG_VAR_BLOCKED), W_FIXED_SKIP(elems fixed_policy skip), W_PAICAD_DEFAULT_OFF. W1 행에도 같음.
- entry_fixed·옛 스터디 응답은 `one_side` 측정 없이 지금 조건으로(W_ENTRY_ONE_SIDE 가 입구 없음도 포함 — 문구만 바뀜). floor_fixed 만 W_ENTRY_NONE·W_ONE_SIDE_EDGE 로 나눔.
- 문구 원본 `resources/doe_messages.json`(API 가 text 동봉, 화면 거울 없음).
### 4.2 기본 켬
- W 행이 있고 기본 끔 사유가 없으면 `use_default: true`(graph·elems 명문화 + 시험) — **W1 행 포함**(사용자 확정 2). paicad 는 paicad 값 그대로(끔이면 사유 표시). 행렬 기본 `doe.default_types [D, W]` 그대로. 복제 화면은 원 spec 미리 채움이 우선(§6.1 — W1 행은 꺼진 채).
### 4.3 위치
- 새 스냅샷: 코어 derive summary·`params.json beads[].w_reason{code}`. API(`DoeParamsOut.beads`·선택 derive 응답)는 옛 스터디도 응답 때 같은 함수로 계산(저장 안 함).
- 화면: 변수 표 비드 묶음 안 W 자리 1줄 — W 행 없음 = 회색 "W 사용 불가 · <문구>"(체크 칸 없음), 기본 끔 = W 행 체크 해제 + 줄 끝 사유, W1 행 = 이름 옆 꼬리표 "한쪽"(툴팁 "한쪽 입구만 이동"). 새 버튼 0.
### 4.4 대칭 묶기(DM-15)
- floor_fixed: 422 `BG_TIE_NOMINAL` 의 "같은 W 유무"는 S_2 기준(W1 이전 — 원 선택이 그대로 유효). W1 은 구성원 모두 W1 ∧ 열린 쪽 방위가 대칭 축 거울(아래 정의) ∧ |W1_nom 차| ≤ 2·`sym_tol_mm` 일 때만 묶음 W 1개(합), 아니면 그 묶음 W 없음 + W_TIE_MIXED. D 묶음은 그대로.
- 거울 연산(DM-C1-5, `section.tie_mirror_ok`): 비드마다 c = S_1 골격 점의 길이 가중 도심(판 평면), v = 열린 쪽 평균 바깥 방향(골격 선분 왼쪽 법선 × σ_o 의 길이 가중 합, 정규화 — 합 0 이면 없음). 대표(묶음 첫 비드)와 구성원 쌍마다 대칭면 법선 m = (c_m − c_대표)/‖·‖, 거울(v) = v − 2(v·m)m, 거울(v_대표)·v_m ≥ cos 30° 이면 통과. 도심 거리 < h 또는 방향 없음 = 판정 불가 → W_TIE_MIXED. DS_ONE_SIDE `open_side_deg` = atan2(v) (판 평면 e1 기준).

## 5. 하위 호환 · 해시 · 설정 · 판
- 키 없음·entry_fixed 명시: 지금 경로 → `prep/select/{graph.json, range_guard.json, w_clamp.json}`, `prep/input.json`, `select/<sha12>/{basis.npz, basis.bin, basis.json, params.json, derived.json}`, matrix·design.npz·result.json·ranking.csv·보고서·view3d·input_sha256 main 1d71d983 바이트 동일. entry_fixed 는 어떤 문서·해시 보기에도 키를 쓰지 않음(기본값 키 생략 — BG-D-36 선례). W1·`one_side` 는 호출되지 않음.
- floor_fixed: basis.json += depth_section·section_rules·graph_vars[].section·(DF 있으면) `df_rules`·(W1 있으면) `w1_rules`·`beadgraph_package`, graph_vars[].kind = "D"(DF 기저도)·"W1"(W1 변수), 기저 재사용 조건 += `bj.get("depth_section", "entry_fixed")` 일치 ∧ `df_rules`·`w1_rules` 일치(키 있을 때), D 행 += `section{mode, cot_deg, applied, reason?}`, W1 행 += `w_side: "one"`, range_guard 표 머리·key += ds. `_sel_cfg_sha` += `section.hash_view`(floor_fixed 만 — ds·one_side_min_nodes, theta_min_deg·theta_spread_deg 는 elems 비드가 있을 때만).
### 5.1 패키지 판(esl_beadgraph.md §2.5·§8.3 보강 — DM-17)
| 식별자 | 값 | 쓰는 곳 | 오르는 때 |
|---|---|---|---|
| `__version__` | **1.2.0**(MINOR — 새 kind DF·W1·새 함수 `one_side`) | 휠·`python -m beadgraph version`·selftest 보고·floor_fixed basis.json `beadgraph_package`·`deploy/requirements.lock`·루트 `pyproject.toml` | semver(§8.3) |
| `RULES` | 1 그대로 | graph.json·expected.json | 분류 출력 변경 |
| `MORPH_RULES` | 2 그대로(D·W 기저 바이트 불변) | graph.json 머리·basis.json·기저 재사용 | 기존 kind(D·W) 수치 변경 |
| `DF_RULES`(신규) | 1 | floor_fixed basis.json `df_rules`·기저 재사용 | DF 수치 변경 |
| `W1_RULES`(신규) | 1 | floor_fixed basis.json `w1_rules`·기저 재사용 | W1 수치 변경 |
| `OUTPUT_VERSION`(신규) | **"1.1.0"** | graph.json 머리 `version`(classify.py:485), esl `prep/input.json graph.beadgraph_version`·basis.json `beadgraph_version`(`bg.__version__` → `bg.OUTPUT_VERSION`) | RULES 또는 MORPH_RULES 가 오를 때 그 판의 `__version__` 으로 |
- 근거: graph.json 은 머리 판까지 sha 에 들어가 선택 sha·폴더·`BG_GRAPH_STALE` 을 좌우(§0.3-8, SH-27). 분류·기존 기저가 그대로인 MINOR 는 기존 출력 바이트를 바꾸지 않는다 → 옛 스냅샷 바이트 동일, 복제·준비 다시에서도 같은 graph sha(#88 복제 선택 그대로). `expected.json` 의 version = OUTPUT_VERSION 그대로(graph sha 비교 불변).
- `GRAPH_ALGO` 1 그대로(esl 그래프 기저 중 기존 경로 불변 — 새 경로는 depth_section·df_rules·w1_rules 키로 식별, BG-D-39 올림 정책과 같은 뜻).
- physicsai: 1.2.0 휠은 1.1.0 과 같은 graph.json·D·W 기저 → 고정 판 올림은 선택(DF·W1 이 필요할 때). `python -m beadgraph version` += `output_version`·`df_rules`·`w1_rules`.
### 5.2 설정
- 같은 이름 4곳(`esl/doe/__init__.py` DEFAULTS·backend pydantic·`config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`): `bead_doe.depth_section: floor_fixed`, `bead_doe.depth_section_rules: {theta_min_deg: 15.0, theta_spread_deg: 5.0, one_side_min_nodes: 3}`(1..20, theta 2키는 elems 만) — 최상위 새 키(해시 대상 절 불변). 스냅샷 rules 복사는 floor_fixed 일 때만. `GET /doe/settings += depth_section`.

## 6. API · 스냅샷
| 위치 | 키 | 새 | 옛 |
|---|---|---|---|
| DoeStudyIn | `depth_section: Literal["entry_fixed","floor_fixed"] \| None`(없으면 설정) | – | – |
| 복제 `POST /doe/studies/{sid}/clone` | 본문 `{title?, depth_section?}` — §6.1 | – | – |
| params.doe·bead_does.inputs | depth_section(+ depth_section_rules) | 생성 때 고정, 복제 = §6.1 | 키 없음 |
| bead_does.inputs | `spec_prefill`(select 복제만 — 원 `doe.spec`, §6.1) | 복제 때 | 없음 |
| DoeStudyOut.inputs | depth_section·spec_prefill | 값 | null(화면 "입구 고정(이전)") |
| DoeSettingsOut | depth_section | 설정값 | – |
| params[] D 행 | section{…} | floor_fixed 만 | 없음 |
| params[] W 행 | `w_side: "one"`(W1 만) | floor_fixed 만 | 없음 |
| beads[](params·derive) | w_reason{code, text} | 응답 때 | 같음(표시만) |
| 단면 그림 section | ds_dD{tier: […]}, W1 = ds_dW 열린 쪽 +1·고정 쪽 0 | 그래프 항상·elems floor_fixed | 그래프도(그림 교정, DM-12) |
- 백엔드→코어: `derive_obj_v2(…, depth_section=, section_rules=)`, `bead_select.derive_obj(…, depth_section=)`, `range_guard_table(…, depth_section=)` — `_graph_call` 시그니처 키만(SH 선례).

### 6.1 복제 규칙(사용자 확정 5 — DM-18)
- 본문 `depth_section`: select 시나리오만(그 밖 = 422 `INVALID_PARAMS`), 값 = `DEPTH_SECTIONS` 밖이면 422. 없으면 원 값.
- 스냅샷 키 = `section.clone_depth(orig, req)`(순수): 원 키 없음 + 요청 없음·entry_fixed = **키 없음**(지금 복제와 바이트 같음), floor_fixed = `depth_section: floor_fixed` + `depth_section_rules`(지금 설정), 원 floor_fixed + entry_fixed = 두 키 삭제, 같은 값 = 원 블록 그대로.
- **보존**(깊이 동작만 바뀌게):

| 입력 | 규칙 |
|---|---|
| 비드 선택·편집·ties·fixed_user·exclude | 원 문서 그대로(`clone_selection` — 같은 sha). 분류·패키지 출력 판 불변(§5.1)이라 준비를 다시 해도 graph sha 같음 → `BG_GRAPH_STALE` 없음. floor_fixed 에서도 S_2 기준 tie 검사(§4.4)라 422 없음 |
| 변수·범위·방법·n·levels·seed | **원 `doe.spec` → `inputs.spec_prefill`**(복제된 스터디의 변수 표 초기값 — `s.doe.spec` 없을 때 이것, 화면 규칙 `DoeStudy.tsx:1576-1590` 그대로: spec 에 있는 변수만 체크·원 lo/hi). spec 이 없던 스터디 = 키 없음(서버 기본). 같은 spec·seed → 같은 안 값(D 열 비교 가능) |
| ESL(entry_ids)·하중 출처·지그(load_source) | 원 값 그대로(지금 복제) |
| 규칙 블록 shape_rules(w_partial·range_guard)·load_transfer | 원 블록 그대로 — 옛 스냅샷에 w_partial 등을 **주입하지 않음**(W 변수 구간이 바뀌지 않게). DF·조합은 w_partial 무관(§1.4) |
| rank·cfg | 지금 복제 규칙 그대로(rank = 지금 설정 + RANK_REFRESHED, cfg = 지금 설정) — 바뀌면 기존 경고 1줄 |
- **규칙상 달라지는 것**(바꾼 복제만, 1줄 경고 `DS_CLONE_NOTE{from, to, dropped[]}` — 문구 `doe_messages.json`, 복제 창과 새 스터디 경고 줄에 같은 문구):
  - entry → floor: D 기저(그래프 DF·elems 조합) — 모든 비드에 적용, 대체(§1.4)가 있으면 그 비드만 DS_FALLBACK. W 가 없던 한쪽 입구 비드에 W1 행이 생김(spec 에 없으므로 꺼진 채). D 원 범위가 floor_fixed feasible 상한(§2.1)·guard usable 밖이면 기존 경고(`RANGE_OUTSIDE_FEASIBLE`·`RG_OUTSIDE_GUARD`)로 알림(막지 않음). 문구: "깊이 동작만 바뀝니다 — 변수·범위·선택은 원 스터디 그대로(한쪽 입구 W 행은 꺼진 채 추가)".
  - floor → entry: W1 변수는 entry_fixed 에 없음 → spec_prefill 에서 빼고 `dropped` 에 이름. 문구: "입구 고정에는 한쪽 입구 W 가 없어 변수 n개(B3_W …)가 빠집니다".
- 순수 함수 `clone_depth` = 키 결정·dropped 계산(원 spec 변수 중 원 params.json 행 `w_side = one` 인 W) — 백엔드 `clone()` 은 그 결과만 씀.

## 7. 화면(2560×1440, 새 버튼 0 — 복제 창의 [복제]·[취소] 는 사용자 지시 "복제 창")
- 새 스터디(`DoeStudy.tsx` NewStudy): select 시나리오일 때 기존 옵션 줄에 라디오 2개 "깊이 동작 ○ 입구 고정(깊이면 좁아짐) ● 깊이면 폭 유지(입구 넓어짐)", 기본 = 설정, paicad·④ 숨김. 툴팁: 선택(요소) 비드는 입구 고정에서 사면이 가팔라짐 · 한쪽 입구 비드는 입구가 한쪽만 넓어짐(중심선 치우침). 같은 줄 우선, 안 되면 +1줄 ≤ 28 px.
- **복제 창**(select 스터디만 — 그 밖 시나리오는 지금처럼 즉시 복제): 헤더 [복제] → 버튼 아래 작은 창(≤ 3줄, 가로 스크롤 없음): 1줄 = 같은 라디오 2개(기본 = 원 값, 키 없음 = 입구 고정), 2줄 = 원 값과 다르게 고르면 `DS_CLONE_NOTE` 문구 1줄(같으면 없음), 3줄 = [복제] [취소]. 요청 = `doe.clone(id, {depth_section})`(`api/doe.ts:269` 시그니처 += 선택 키).
- 복제된 스터디 변수 표: `s.doe?.spec ?? s.inputs.spec_prefill` 로 행 미리 채움(지금 식).
- 스터디 머리 칩 1개(load_source 칩 옆): "깊이면 폭 유지" | "입구 고정" | "입구 고정(이전)".
- 변수 표: D 행 DS_FALLBACK 배지 "입구 고정"(툴팁 사유), W 사유 1줄·W1 꼬리표(§4.3).
- SectionMini: 깊이 점선 = (s + ΔD·ds_dD, z + ΔD·dz_dD), ds_dD 없으면 0. 한쪽 비드는 열린 쪽만 벌어진 그림(fig side).
- 3D 미리보기(basis.bin, `GET …/select/basis`): 형식 불변, D vec = DF(그래프)·조합(elems) → 입구 넓어짐(한쪽 비드는 한쪽만)이 바로 보임.

```
 W_open = W_top + 2·D·cotθ
 입구(판 쪽)
 ─────────┐                  ┌─────────  판(부모 바닥)
           \ θ              /
            \              /   D
             └────────────┘
               W_top = 깊이면(비드 윗면)

 floor_fixed(벽마다 자기 θ), 깊이 +ΔD  entry_fixed(그래프, 지금), 깊이 +ΔD
 ──────┐                    ┌──────   ─────────┐              ┌─────────
        \ θ                /                    \ θ           /
         \                /   D+ΔD               \           /   D+ΔD
          \              /                        \         /
           └────────────┘                          └───────┘
 입구 한쪽 +ΔD·cotθ, W_top 그대로        입구 그대로, W_top − 2·ΔD·cotθ
 선택(요소) 방식 지금: 입구·W_top 그대로, 사면 가팔라짐(θ' > θ)

 한쪽 입구(고리 변, 고정 쪽 = 공유 자식 플래토) floor_fixed, 깊이 +ΔD
 열린 쪽(o)                     고정 쪽(f)
 ──────┐                     ┌──── 플래토(제자리)
        \ θ                  │  ← 고정 쪽 사면 가팔라짐(θ_f')
         \                   │
          └──────────────────┘
 입구(o) +ΔD·cotθ, W_top 그대로, 입구 중심선 cotθ·ΔD/2 치우침
```

## 8. 시험(V-0247-DM-n, 1~30)
1. 합성 직선 사다리꼴 채널(정렬 quad, 판 600×300, D 10, W_open 40, θ 45°·60°, 필렛 없음, 그래프) floor_fixed ΔD ±3: 달성 깊이 ±1e-6, **깊이면 전 노드 평면 변위 ≤ 1e-12**(φ = ψ = 1 구역), 입구 폭 = W_open + 2ΔD·cotθ ±1e-3, 사면 각 θ ±0.05°, A_DF 밖 max|u| ≤ 1e-9, 뒤집힘 0.
2. 같은 메시 entry_fixed: 입구 변화 ≤ 1e-9, 깊이면 폭 = W_top − 2ΔD·cotθ ±1e-6, 각 ±0.05°, 기저 바이트 = main.
3. 비정렬 입구 선 H6 ch1 D +2 floor_fixed: 깊이면 평면 ≤ 1e-9(φ = ψ = 1), `entry_wave_mm` ≤ 0.05h, 각 ±1°, 뒤집힘 0. (d) 포켓 C D +2: BG_CORNER_GUARD 없음·뒤집힘 0.
4. elems 1단(synth_bead 원형 D 6·W 40·60°) floor_fixed: 깊이면 노드 평면 이동 ≤ 1e-9, 경계 이동 cotθ·ΔD ±0.02h, 각 ±1°. 2단 경로형 = DS_FALLBACK SELECT_MULTI_TIER·기저 바이트 = entry_fixed.
5. D·W 동시: W_top' = W_top + ΔW ±1e-3, W_open' = W_open + ΔW + 2ΔD·cotθ ±1e-3, 각 ±0.05°, 두 기저 합 = 동시 모핑 ±1e-12.
6. θ: 그래프 45°·60° 섞인 묶음 → DS_THETA_* 없음, `section.cot_min/med/max_deg` = 해석값 ±0.1°. elems θ < 15° → DS_FALLBACK THETA_UNMEASURED, 퍼짐 → DS_THETA_SPREAD.
7. W 사유: 코드마다 합성 1개 + 순서 고정. W 변수 부분(w_partial)이어도 DF 는 비드 전체·DS_PARTIAL 없음.
8. 기본 켬: 사유 없으면 use_default true → default_params 에 B<n>_W(graph 양쪽·W1·elems). 기본 끔 4사유 = false + 사유.
9. 옛 바이트: main 1d71d983 골든(sel_regress·selreg ①②③, v0.24.6 그래프 스터디 1, ④ regress), 키 없음·entry_fixed 명시 두 스냅샷 — §5 파일 전부(`prep/input.json` 포함)·input_sha256·hash_view 동일(다시 기록 금지). 패키지 1.2.0 설치 상태에서.
10. 계획 표: 모든 행·열 채움(빈 칸 CONFIG_INVALID), 변이 시험(graph compose → none = entry_fixed 바이트, graph one_side → none = W1 행 없음·D 불변), paicad = 계산 영향 0 + DS_ENGINE_NATIVE, 호출 쪽 시나리오 이름 분기 0건(정적).
11. feasible: floor_fixed 식(entry_width 비드·W1_nom 비드·둘 다 없는 비드·elems, W1), entry_fixed 식 바이트 불변, API 거울 `_graph_rows` = 코어 값.
12. range_guard: floor_fixed 후보 = DF·elems 조합 + W1, 같은 비드 D·W combo 묶음, 표 머리 sha 다름. entry_fixed 표 바이트 = main.
13. 침범: DF 단독 BG_OUTSIDE_MOVED 없음, 블렌딩 자름 경고, 고정 노드 이동 ≤ 1e-12(hold 1), DS_HOLD_PINCH.
14. 설정 거울: DEFAULTS = pydantic = yaml 2(one_side_min_nodes 포함), 키 없음 해시 불변, theta 2키는 elems 비드 있을 때만 hash_view, `select.graph` 키 수 = main(graph.json cfg 불변).
15. API·화면: 모르는 값 422, 스냅샷 = inputs, 복제 = §6.1(V-0247-DM-24), 라디오 기본·요청·select 외 숨김, 칩, W 사유 줄·W1 꼬리표, D 배지, SectionMini ds_dD, 2560·1920 새 스터디 scrollHeight 증가 ≤ 28 px, 스터디 화면 ±0.
16. 그림: 그래프 floor_fixed(floor_center) ds_dD = 깊이면 0·입구 cotθ, 그래프 entry_fixed = 깊이면 축소 방향, elems entry_fixed = 0, W1 ds_dW 열린 쪽 +1·고정 쪽 0.
17. 비용: DF 기저 시간 ≤ W 기저 시간 × 1.2(같은 띠·조화 없음), 합성 120×80(9,801 노드) 비드 5개 BD_MATRIX·range_guard 준비 비 기록.
18. **W1 합성**(패키지 `beadgraph.testing.synth_oneside` — 정렬 quad, gmsh 없음, 결정적): (a) 고리 띠(바닥 −10, 플랜지 0) 안 공유 자식 플래토(−4), θ 45°·60°, (b) 채널 옆 형제 포켓(step 접합 구역 — 이웃 비드), (c) 판 외곽을 따라가는 채널, (d) 배타 자식 플래토. W1 ΔW ±4(a·b·d): 열린 쪽 입구·벽·가장자리 이동 = ΔW ±1e-3(직선·φ = 1), **고정 쪽 노드 |u| ≤ 1e-12**, 깊이면 폭 변화 = ΔW ±1e-3, 열린 쪽 사면 각 ±0.05°, 고정 쪽 사면 변화 0(1e-9), 달성 W1 ≤ 1e-3, A_W 밖 ≤ 1e-9·누출 0·뒤집힘 0, (b) 열린 쪽 φ = 1(고정 쪽 J 가 램프 원점 아님). (c) W1 없음 + W_ONE_SIDE_EDGE(깊이는 29) — 합성 판 외곽 채널은 분류기(RULES 1)가 깊이면을 area 로 두어(골격 없음 → AREA) 재현 불가 → `oneside.measure(edge_nodes=…)` 강제 외곽 마스크 단위 시험으로 대체(DM-C1-3). 측정 `one_side`: side·d_o·d_eo·d_f = 해석값 ±0.5h, fixed 분류 = (a) shared·(b) junction·(c) edge·(d) child.
19. **DF 한쪽**(18 의 a·b·d, ΔD ±3): 달성 깊이 ±1e-6, 깊이면 평면 ≤ 1e-12(φ = ψ = 1), 열린 쪽 입구 이동 = ΔD·cotθ ±1e-3, 열린 쪽 θ ±0.05°, (d) 고정 쪽 θ ±0.05°, (a) 고정 쪽 θ' = atan((h_f + ΔD)/r_f) ±0.05° + DS_ONE_SIDE steep_deg, (b) 램프 밖 깊이면 폭 ≤ 1e-6·잔차는 section 진단에만, 뒤집힘 0.
20. D·W1 동시: W_top' = W_top + ΔW, W1' = W1 + ΔW + cotθ·ΔD ±1e-3, 두 기저 합 = 동시 모핑 ±1e-12.
21. 구간·변수: S_2·S_1·S_0 섞인 비드 → W 변수 = S_2 만(W1 없음); S_2 = ∅ 비드 → `B<n>_W` = W1·`w_side: one`·use_default true·W_ONE_SIDE 꼬리표; 옛 규칙(w_partial 없음) S_1 ⊂ S → W 없음 W_PARTIAL_OLD; 세 경우 모두 D = DF 전 구간.
22. 대칭 묶기: 거울 W1 비드 2개 → W 1개(구성원 합), W1 + 양쪽 W·열린 쪽 거울 아님 → 422 없음·W 없음·W_TIE_MIXED·D 묶음 유지, S_2 유무 다름 = 지금처럼 422.
23. **판 불변**: graph.json(H5·H6·stepboss·synth_oneside) 바이트 = `expected.json`(version = OUTPUT_VERSION 1.1.0), D·W 기저 바이트 = 1.1.0(main 골든 H5·H6 전 변수), `python -m beadgraph version` = {version 1.2.0, output_version 1.1.0, rules 1, morph_rules 2, df_rules 1, w1_rules 1}, 옛 스냅샷 prep/input.json·basis.json `beadgraph_version` 1.1.0, 옛 스냅샷 새 행렬 = 기저 재계산 없음(재사용 조건), V-BG-14 DEFAULTS 일치·import 순수성, selftest 0.
24. **복제**: (i) 본문 검사 — 모르는 키·값 422, select 밖 depth_section 422; (ii) 원 키 없음 + 요청 없음·entry_fixed → 스냅샷·inputs 키 없음(지금 복제와 바이트 같음, spec_prefill 만 추가); (iii) floor_fixed → depth_section + rules(지금 설정), 선택 문서·sha 원과 같음, 준비 뒤 graph sha 같음(BG_GRAPH_STALE 없음), shape_rules·load_transfer 원 블록 그대로(w_partial 주입 없음), ties 422 없음; (iv) spec_prefill = 원 spec, 그 spec 으로 만든 행렬의 D 열 안 값 = 원 행렬 값(같은 seed·방법); (v) floor → entry: W1 변수 dropped·DS_CLONE_NOTE; (vi) rank 갱신 규칙·RANK_REFRESHED 그대로; (vii) `clone_depth` 순수 표(4 경우).
25. **복제 창(화면)**: select 만 창, 그 밖 즉시 복제, 라디오 기본 = 원 값(키 없음 = 입구 고정), 바꾸면 1줄 문구·같으면 없음, 요청 본문, 복제 스터디 변수 표 = spec_prefill(원 변수만 체크·원 범위·W1 행 꺼짐), 2560·1920 잘림·가로 스크롤 없음, mock.
26. W 사유 갱신: W_ONE_SIDE 꼬리표, W_ENTRY_NONE·W_ONE_SIDE_EDGE·W_TIE_MIXED 합성 1개씩, entry_fixed·옛 스터디 W_ENTRY_ONE_SIDE 새 문구, 순서 고정(첫 일치).
27. 비용: H6 derive 에 `one_side` 추가 ≤ 0.3 s(전 세그먼트), synth_oneside W1 기저 ≤ W 기저 시간 × 1.2.
28. **비대칭 벽**: 한쪽 45°·반대쪽 60° 채널 — 각 벽이 자기 각 ±0.05°, 입구 이동 = 벽마다 cotθ·ΔD ±1e-3. 변이 대조: 평균 θ 조합식(B_D + 2cotθ_b·B_W)은 깊이면 평면 변위로 실패.
29. **적용 범위**: 네트워크 묶기(H5 고리 + T), 면형 바닥 포켓(H6 (d)), merge 구간, 판 외곽을 따라가는 채널(18c), 한쪽 입구(18 a·b·d) — 모두 DS_FALLBACK 없음, 깊이면 평면 ≤ 1e-9, 각 ±0.5°(직선 구간), 뒤집힘 0, 네트워크 T 접합 근처 `entry_wave_mm` ≤ 0.1h·뒤집힘 0. 입구 노드 0 인 합성 = W_ENTRY_NONE + entry_fixed 바이트.
30. **이웃 압축**: 간격 20 mm 평행 채널 2개 동시 +ΔD_ext — SELECT_BLEND_CLIPPED, range guard 가 usable 상한을 줄임(뒤집힘·넓이 비 기준 그대로), 막지 않고 표에 표시.

## 9. 작업 분해(파일 소유 겹침 없음)
| 묶음 | 모델 | 파일 |
|---|---|---|
| C1 코어 + 패키지 | opus | **`packages/beadgraph/**`**(`morph.py` DF·W1 갈래 + 띠·허용 구역 **공용 내부 함수 1개**(W·DF·W1 — D·W 바이트 불변, v0.24.9 kind U 재사용), 신규 `oneside.py`(`one_side` — `absorb.polyline_dist`·`interior_mask`·`zones.bead_zones` 재사용), `checks.py` DF 달성(법선)·W1 달성·`allowed_elements` DF(A_DF)·W1(W 규칙), `classify.py` 머리 `version` = OUTPUT_VERSION, `__init__.py` `__version__` 1.2.0·`OUTPUT_VERSION`·`DF_RULES`·`W1_RULES`·`one_side` 내보내기, `__main__.py` version 출력, `testing/synth_oneside.py`·`conformance.py`(DF·W1 점검·selftest), `README.md`, `tests/test_one_side.py`, expected.json 불변), 루트 `pyproject.toml`(`beadgraph==1.2.0`), `esl/morph/section.py`(신규), `esl/doe/bead_graph.py`(+ `bg.OUTPUT_VERSION` 기록), `esl/doe/bead_select.py`, `esl/doe/paicad_io.py`(사유·DS_ENGINE_NATIVE 만), `esl/doe/stages.py`(+ basis.json 판 키), `esl/doe/__init__.py`, `resources/doe_messages.json`(DS_CLONE_NOTE·W 사유 문구 포함), `tests/doe/test_depth_section*.py`, `tests/morph/test_section.py`, 골든 `tests/doe/golden_v0247_c1/` |
| B1 백엔드 | sonnet | `backend/esl_platform/core/config.py`, `config/esl_platform.example.yaml`·`.prod.example.yaml`, `backend/esl_platform/api/schemas.py`(복제 본문 모델·inputs.spec_prefill·w_side), `api/services/doe.py`(`clone()` — `section.clone_depth` 사용), `api/services/doe_select.py`, openapi, `deploy/requirements.lock`(`beadgraph==1.2.0`), `tests/deploy/test_bead_doe_deploy.py`(판 대조), `backend/tests/test_doe_v0247_*.py` |
| F1 프런트 | sonnet | `frontend/src/api/types.ts`·`doe.ts`(clone 본문), `pages/doe/DoeStudy.tsx`(라디오·복제 창·spec_prefill), `components/DoeParamTable.tsx`(W1 꼬리표), `components/SectionMini.tsx`, `mock/*.ts`, `__tests__/depth_section*.test.tsx`·`clone_depth*.test.tsx`, Playwright |
- 순서: C1 이 패키지 API(`one_side` 반환 형식·DF·W1 항목 키)·section.py 시그니처·코드 표 첫 커밋 → B1·F1 병렬 → 통합(메인: CHANGELOG(beadgraph 1.2.0 절 포함)·user.md 깊이 동작·복제 절·admin 설정 3키·`esl_beadgraph.md` 상호참조 확인·`docs/manual/field_check_v0247.md`(§13)).

## 10. 미결(결과를 바꾸는 것만 — 기본 가정으로 진행)
- Q-DM-4 한쪽 비드의 고정 쪽이 공유 자식 벽(고리 안 플래토)일 때 — 기본: **깊이면 폭 우선**(고정 쪽 사면 가팔라짐 = 지금 동작, DS_ONE_SIDE steep_deg 표시). 대안: 고정 쪽 각 유지(그쪽 깊이면이 cotθ_f·ΔD 줄어듦 — 패키지 DF 갈래 규칙 추가).
- Q-DM-5 복제의 변수·범위 미리 채움 범위 — 기본: **모든 select 복제**에서 원 spec 을 미리 채움(깊이 동작을 안 바꾼 복제 포함 — "같은 입력"). 대안: depth_section 을 바꾼 복제만(나머지는 지금처럼 서버 기본).
- Q-DM-6 고정 쪽이 판 외곽 자유 모서리 — **W1 변수에만 해당**(깊이는 DF 가 처리). 기본: 한쪽 W 불가(W_ONE_SIDE_EDGE). 대안: 판 외곽을 고정점으로 W1 허용.

## 11. 결정 요약 — 전문 `docs/decisions.md` 2026-11-25 D-0.24.7-DM-1~12(초안), DM-13~20(개정 1 — Q-DM-1·3 사용자 확정, Q-DM-2 기본 유지), DM-21·22(개정 2 — 그래프 floor_fixed = kind DF, W1 변수 전용).

## 12. 후속(R-DM-n)
- R-DM-1 위치 U/V(그래프·선택 — 사용자 확정 3).
- ~~R-DM-2 W 기저 없는 비드 floor_fixed~~ → 본문 §1.6·§1.2.1.
- R-DM-3 paicad 깊이 단면 규칙 확인(physicsai shell-morph, 읽기 전용) → 필요 시 요청.
- R-DM-4 선택 방식 다단 비드 floor_fixed.
- ~~R-DM-5 세그먼트별 θ~~ → DF 가 해결(DM-21).
- R-DM-6 걸친 섬 옆 DF 평면 감쇠(입구 국부 덜 넓어짐·사면 가팔라짐 잔차 제거 — 패키지).
- R-DM-7 entry_fixed 새 스터디의 한쪽 W1 변수(지금 = floor_fixed 스냅샷만 — entry_fixed 는 main 바이트).
- R-DM-8 entry_fixed D 의 고정 쪽 비드 소유 벽 닮음 중심(건너편 입구 — §0.3) 교정: 패키지 MORPH_RULES +1 때(옛 기저 재계산 동반 — 사용자 확인 후).
- R-DM-9 merge 한 구간의 한쪽 측정(지금 W_EDIT_MERGED — 깊이는 DF 적용).
- R-DM-10 선택(요소) 방식 열린 경계의 한쪽 W(W_OPEN_BOUNDARY).
- R-DM-11 elems 도 DF 식으로(지금 조합 — run_med 평균 θ).
- R-DM-12 DF 를 새 entry_fixed 의 대체로 쓸지(그림·문구 통일).

## 13. 현장 확인(F-DM-n — `docs/manual/field_check_v0247.md` 는 통합 때 작성, 여기는 목록만)
- F-DM-1 #88 비드 B1~B9 의 W 불가 사유 — **서버 LLM 진단**(옛 스터디 응답 계산 `w_reason`)으로 코드·문구 기록. 기대: 한쪽 입구 비드 = W_ENTRY_ONE_SIDE. (깊이면 폭 유지는 사유와 무관하게 DF 로 적용 — E = ∅ 비드만 예외.)
- F-DM-2 #88 을 "깊이면 폭 유지"로 복제: 경고 1줄 DS_CLONE_NOTE, 선택 sha 같음·BG_GRAPH_STALE 없음, 변수 표 = 원 B1~B9_D 만 체크·원 범위, W1 행 꺼짐, 같은 seed 행렬 D 열 = 원.
- F-DM-3 복제 스터디 비드별 W1 대상(S_1) 세그먼트 수, 고정 쪽 종류(child·shared·junction·edge·own_wall n — `DS_ONE_SIDE`·서버 LLM 진단), W 사유(W_ONE_SIDE·W_ONE_SIDE_EDGE·W_ENTRY_NONE), DS_FALLBACK 목록(기대: 없음 또는 W_ENTRY_NONE 만).
- F-DM-4 section 진단 floor_plan_max_mm·entry_wave_mm·cot_min/med/max_deg·steep_deg(한쪽 비드), 3D 미리보기로 입구만 넓어짐(한쪽 비드는 한쪽)·깊이면 제자리 눈 확인(B_D 끝값·W1 끝값).
- F-DM-5 B8 깊이 기울기(%/mm) 원 −1.98 대비 복제 값, 순위와 재낙하 소성 변형률 순서 일치 여부.

## 14. 검토 개정 2 — 본문 반영됨(2026-11-25, 결정 DM-21·22)
- 그래프 floor_fixed 를 조합식(B_D + 2cotθ_b·B_W* + cotθ_b·B_W1*)에서 패키지 kind DF(깊이면 가장자리 중심 닮음)로 — §1.2.1. elems 는 조합 그대로(§1.2.2).
- 이유: 조합은 W 기저 있는 구간만·비드 평균 θ·가상 범위/θ 규칙/DS_THETA_*·DS_PARTIAL 장치 과다. DF 는 노드마다 실제 각, 깊이면 평면 0, 네트워크·면형·merge·한쪽·판 외곽 모두 적용(E = ∅ 만 대체).
- W1 = 변수 전용(`ramp: "end"` 만, 조합·가상 범위 삭제), one_side 는 W1 변수·사유 판정 전용 — §1.6. W_ONE_SIDE_EDGE·Q-DM-6 은 W1 변수에만.
- 허용 구역 A_DF = D allowed_el ∪ 부모 바닥 ∪ 부모의 걸치지 않은 섬(구역 계산 `bead_zones(…, "D")`). 판: `DF_RULES = 1` 신규(§5.1), RULES·MORPH_RULES·OUTPUT_VERSION·GRAPH_ALGO 불변. 띠·허용 구역은 W·DF·W1 공용 내부 함수 1개(§9 — v0.24.9 위치 U(kind U)가 그대로 사용, 부모 바닥 띠 노드 하중 따라감은 v0.24.9 `load_follow`).
- 시험 1·3·6·7·10~13·16·17·19·21 교체, 28~30 추가(§8), 후속 R-DM-5 삭제·R-DM-11·12 추가(§12).

## 15. 구현 메모(C1, 2026-11-25 — work/findings.md 에서 옮김, 결정 D-0.24.7-DM-23~29)
- DM-C1-1(§1.2.1 벽·입구): 자기 interior 골격 투영이 없는 열(세그먼트 끝·고리 모서리·접합 옆)은 최근접 깊이면 가장자리까지 현으로 r 을 재는데 가장자리가 접합 구역에서 끝나면 r 이 4 배 이상 튐(합성 고리 a: 입구 12 mm 이동·뒤집힘 6) → r ≤ interior 입구 r 최대(벽 ×(1 − t)), `info.chord_capped_n`.
- DM-C1-2(§1.2.1·§1.6.3 띠): H5 네트워크(고리 + T) DF +2 에서 마주 보는 입구 선 사이 20 mm 판 띠의 최근접 복사가 이등분선에서 불연속(뒤집힘 2) → DF·W1 띠 = 거리 가중 혼합(K = 8, ε = 0.1h — `beadgraph.morph.BAND_MIX_K·BAND_MIX_EPS_H`, DF_RULES·W1_RULES 1 정의의 일부). 측정: H5 네트워크 DF ±2 뒤집힘 0(시험 29 통과), ±3 = 1·2(range guard 영역). W 띠 = 최근접 복사(골든 바이트 동일).
- DM-C1-3(§8-18c): W_ONE_SIDE_EDGE 는 강제 외곽 마스크 단위 시험(`tests/doe/test_depth_section_c1.py::test_one_side_edge_forced_mask_v18c`, 패키지 `test_w1_rejects_two_sided_and_edge`).
- DM-C1-4(§1.3·§2.1): derive 시점 cot = one_side run/D 추정값(basis.json 진단이 실제 값).
- DM-C1-5(§4.4): W1 대칭 거울 검사 구현(위 정의). 상수 `section.W1_TIE_MIRROR_DEG = 30`(계약 규칙 값 — 설정 아님).
- DM-C1-6(§2.6): `wall_no_entry_n` = 비드 소유 벽 노드 ∩ J 수(윗단 = J 판정 대신 근사).
- elems 조합(§1.2.2): `bead_select.derive_obj(depth_section=, section_rules=)`, 적용 판정 순서 열린 경계 → 폭 미정 → 단 수 ≥ 2 → θ, B'_D 는 `_post_basis`(섬·hold) 전에 합성, D feasible 상한 = 입구 확장 상한(m = 2), 그림 `section.ds_dD` = 조합 기저의 평면 성분(floor_fixed 비드만 키). 합성 원형 비드(60°): 경계 이동 1.2025 vs 해석 1.1547(±0.02h = 0.1 안 — run_med 3.608 이 다각형 근사), 사면 각 변화 ≤ 1°.
- range guard·w_clamp(§2.2): floor_fixed 만 `depth_section`·`section_rules` 키 전달 → 후보 D = DF, S_1 단일·seed 비드 W1(`one_side` 측정 공용 `_w1_possible`), 항목 key += `ds`·kind `W1`, 머리 cfg_sha256 += `ds`(= `section.hash_view`) — entry_fixed 표 바이트 불변.
- 패키지 `zones.Mesh.nmask` = 직접 색인(같은 불리언 — D·W 골든 바이트 동일) — H6 `one_side` 전 세그먼트 0.36 → 0.25 s(시험 27 ≤ 0.3 s).
- **미충족(보고)** 시험 3 H6 ch1(channel + flare) DF: +2 뒤집힘 68(−2: 35, ±1: 0), `entry_wave_mm` 0.472 > 0.05h(0.148; ±1 에서도 0.236). 원인: (1) 부모 바닥 필렛 sliver 삼각형(변 0.2 mm) 위에서 입구 노드끼리 평면 이동이 0.3 mm 씩 달라 뒤집힘 — 띠는 다른 형상 근처에서 자르지만 입구 노드 자체(DF 규칙)는 자르지 않음, 채널 끝·flare 의 cot 최대 3.586(15.6°) → 입구 5 mm 이동; (2) `entry_wave_mm`(직선 입구 평면 이동 표준편차)는 flare 벽 각 차이(cot 0.689~3.586)를 그대로 재므로 물결 지표로 맞지 않음. 시험은 완화하지 않고 xfail(strict) — `packages/beadgraph/tests/test_one_side.py::test_df_h6_unaligned_v3`. 포켓 (d) 부분은 통과. 결정 필요(R-DM-13 후보: 입구 평면 이동의 다른 형상 근처 자름 또는 sliver 국부 평활, entry_wave 정의를 세그먼트·각 구간별로).

