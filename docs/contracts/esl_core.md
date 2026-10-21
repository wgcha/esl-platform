# 계약: ESL 계산 코어 (P1a)

- 상태: 확정 (2026-10-19). `esl.md`(P0)를 아래 항목에서 **대체**한다. 충돌 시 이 문서 우선.
- 범위: 클라우드(Linux, Altair 없음)에서 도는 Python 계산 코어 + CLI + Windows용 h3d 추출 TCL. 플랫폼(API·DB·워커·인증·UI)은 P1b(`esl.md` §3~§5·§9 유지, 이 코어를 호출).
- 의존성: Python ≥3.11, numpy, scipy, pyyaml, pytest. pickle 금지, npz는 `allow_pickle=False`, `shell=True`/`os.system` 금지(이 범위엔 외부 실행 자체가 없음).

## 1. P0 대비 변경 요약

| 항목 | P0 | P1a |
|---|---|---|
| h3d 입력 | 서버에서 `hw -b -tcl` 실행 | 사용자가 **Windows에서 TCL 1회 실행 → CSV 폴더**를 클라우드 입력으로 줌 |
| 선형 해석 | OptiStruct | **자체 Python 선형 쉘 솔버**(§5). `.fem`은 내보내기(교차검증용)만 |
| 강체 제거 | BC 4점 Kabsch | **파트 전 노드** Kabsch(균등 가중) |
| BC | 4꼭지점 고정, zero/residual | **3-2-1 정정 구속**(6 자유도). 자유물체 하중은 자기평형 → 반력≈0. `bc_node_disp` 키 삭제 |
| F_eq | 비BC 노드 | **전 노드**(3-2-1 노드 포함) |
| ε_eq | HyperView 불변량 | TCL은 **텐서 성분**만 출력, 불변량은 Python에서 계산(§4) |

## 2. 패키지 구조·소유

```text
pyproject.toml, esl/__init__.py, esl/errors.py      # 메인(골격)
esl/rad/        rad 파서                              # Impl-A
esl/io/         TCL CSV → npz 패킹                    # Impl-A
resources/tcl/  esl_h3d_extract.tcl, esl_h3d_probe.tcl, README.md   # Impl-A
esl/mech/       strain.py, kabsch.py, supports.py, shell.py, tstar.py   # Impl-B
esl/config.py, esl/pipeline.py, esl/cli.py, esl/export/, config/esl.example.yaml   # Impl-C
tests/<영역>/test_*.py                                 # 각 소유자
```

- 모든 오류는 `esl.errors.EslError(code, message)`. code는 `esl.md` §4.3 목록 + `ID_RANGE_COLLISION`, `SOLVER_SINGULAR`, `SUPPORT_DEGENERATE`.
- 배열 인덱스 규약: 노드·요소는 `RadModel` 순서(행 i)로 정렬, ID는 별도 배열.

## 3. Impl-A 인터페이스

### 3.1 `esl.rad.parse_rad(path, part_title, match="exact_ci", max_include_depth=8, material_override=None) -> RadModel`

```python
@dataclass
class RadModel:
    node_id: np.ndarray   # (N,) int64, 대상 파트 요소가 쓰는 노드만, 오름차순
    x0: np.ndarray        # (N,3) f8
    elem_id: np.ndarray   # (E,) int64 오름차순
    elem_type: np.ndarray # (E,) int8: 3=TRIA(/SH3N), 4=QUAD(/SHELL)
    conn: np.ndarray      # (E,4) int64 노드 '행 인덱스'(ID 아님), TRIA 4번째 -1
    elem_pid: np.ndarray  # (E,) int64
    thickness: np.ndarray # (E,) f8  (요소 카드 두께>0이면 우선, 아니면 /PROP/SHELL Thick)
    E: np.ndarray; nu: np.ndarray   # (E,) f8 요소별 재료
    part_id: int; part_title: str; units_label: str   # /BEGIN 단위 문자열, 없으면 ""
    mats: list[dict]      # {id, law, E, nu, rho, source:"rad"|"override"}
    max_ids: dict         # {"node","elem","part","prop","mat","func","grnod","load","bcs"}: 전체 모델 최대 ID
    includes: list[str]
```
- 지원: Radioss 블록 포맷(2017+), `#` 주석, `/INCLUDE "경로"`(rad 기준 상대, 깊이 제한), `/BEGIN`, `/NODE`, `/SHELL/<part_id>`, `/SH3N/<part_id>`, `/PART`, `/PROP/SHELL`(TYPE1), `/MAT/LAW1|ELAST`, `/MAT/LAW2|PLAS_JOHNS`, `/MAT/LAW36|PLAS_TAB`(E·ν만). 그 외 키워드는 건너뛰되 ID는 `max_ids`에 반영.
- 고정 열 폭: 10자(노드 좌표 등 실수 20자 필드는 Radioss 매뉴얼 규약). 참고 구현: `simdashboard/backend/app/parsers/radioss_deck_parser.py`(복사 금지, 규약만).
- title 비교: 공백·`_`·`-` 연속을 한 칸으로 보고 대소문자 무시(`exact_ci`) / 그대로(`exact`). 0개 `PART_NOT_FOUND`, 2개+ `PART_AMBIGUOUS`. 대상 파트에 /BRICK 등 비쉘 요소 → `UNSUPPORTED_ELEMENT`. E·ν 미해결 → `MATERIAL_UNRESOLVED`(override `{mat_id:{"E":..,"nu":..}}`로 해소).
- 읽기 범위(0.5.2): `parse_rad`는 대상 파트의 /SHELL·/SH3N 행, 그 요소가 참조하는 /NODE 좌표, 대상 파트의 /PROP·/MAT만 숫자 해석(다른 블록은 위치·행 수·최대 ID만), `list_parts`는 요소 행 수만 센다(주석·빈 행 규칙 동일, 결과 불변). **동작 변화**: 다른 파트 요소 행·미참조 노드 좌표·다른 /PROP·/MAT 카드의 형식 오류는 더 이상 `RAD_PARSE_ERROR`로 잡지 않고, 대상 파트 쪽 형식 오류는 파트 해석 뒤에 보고한다(오류 코드·메시지 불변).

### 3.2 TCL 출력 CSV (Windows → 클라우드 입력 폴더 `<results_dir>`)

| 파일 | 헤더 | 비고 |
|---|---|---|
| `frames.csv` | `frame_index,time` | |
| `model.csv` | `node_id,x0,y0,z0` | 대상 파트 노드(검증용) |
| `strain.csv` | `frame_index,elem_id,layer,exx,eyy,exy` | layer ∈ `bottom`,`top`(필수), `mid`(선택). **요소 국부계 면내 텐서, exy = 텐서 전단(γ/2)** |
| `disp.csv` | `frame_index,node_id,ux,uy,uz` | 전역계, u = x(t) − X0 |
| `done.json` | `{"ok":true,"n_frames","n_elems","n_nodes","h3d","warnings":[]}` | 없으면 `TOOL_OUTPUT_MISSING` |

- TCL은 HyperView 배치(`hw -clientconfig hwpost.dat -b -tcl esl_h3d_extract.tcl -input <h3d> -config <request.txt> -output <dir>`) 기준. `request.txt`는 `key<TAB>value` 줄(TCL에 JSON 파서 의존 없음): `part_id`, `subcase`(기본 1), `frame_stride`, `strain_type`(기본 `Strain`), `strain_comps`(기본 `XX YY XY`), `layer_bottom`/`layer_top`(HyperView layer 이름, 기본 `Lower`/`Upper`), `shear_is_engineering`(0/1, 1이면 TCL이 exy/2), `disp_type`(기본 `Displacement`).
- `esl_h3d_probe.tcl`: subcase·프레임 수·결과 유형·성분·layer 이름 목록을 `probe.json`으로 출력(이름 확인용).
- 이 환경에서 실행 불가 → 정적 검토만, 실제 동작은 사용자 E2E.

### 3.3 `esl.io.pack_results(results_dir, model, out_dir, frame_stride=1) -> dict`

- 쓰기: `out_dir/strain_tensor.npz` {`time(F,)f8`, `frame_index(F,)i4`, `elem_id(E,)i8`, `eps(F,E,2,3)f4`(layer 0=bottom,1=top; 성분 exx,eyy,exy)}, `out_dir/disp.npz` {`time(F,)f8`, `frame_index(F,)i4`, `node_id(N,)i8`, `u(F,N,3)f8`}, `out_dir/frames.json`.
- CSV에 다른 파트 행이 있어도 무시. 대상 파트 요소·노드가 하나라도 없거나 model.csv 좌표가 rad와 `1e-6·bbox` 넘게 다르면 `ID_MISMATCH`. 결과 유형 누락 `H3D_MISSING_RESULT`. 반환: `{n_frames,n_elems,n_nodes,warnings}`.
- 대용량 대비: CSV는 청크 읽기(`numpy`/`csv` 스트리밍), 전체 텍스트를 한 번에 메모리에 올리지 않음.

## 4. Impl-B 인터페이스 (`esl.mech`)

- `strain.eps_eq(eps) -> ndarray`: `eps[...,3]`(exx,eyy,exy 텐서) → `(2/√3)·sqrt(exx²+eyy²+exx·eyy+exy²)` (비압축 von Mises 등가변형률). `strain.eps_eq_max_layer(eps(...,L,3)) -> (...)` = layer 최대.
- `kabsch.fit(X0, x, allow_reflection=False) -> (R(3,3), t(3,), info)`: `min Σ|R X0_i + t − x_i|²`. 점 3개 미만·공선(특이값 비 <1e-9) → `KABSCH_DEGENERATE`.
- `kabsch.remove_rigid(X0, u) -> (u_rel, R, t, info)`: 전 노드 적합, `u_rel = Rᵀ(X0+u−t) − X0`. info `{rms_def, max_def, rot_deg}`.
- `supports.pca_corners(X0) -> {"idx":[4], "plane":{origin,e1,e2,n}}` (`esl.md` §6.6 규칙).
- `supports.pick_321(X0, cand_idx) -> [(node_idx, "123"), (node_idx, "ij"), (node_idx, "k")]`: 후보(≥3) 중 삼각형 면적 최대 3점 → 첫 점 xyz, 둘째 2성분, 셋째 1성분을 전역 dof 조합 9가지 중 강체 6모드 구속행렬 6×6의 최소 특이값 최대로 선택. 최소 특이값/최대 <1e-6 → `SUPPORT_DEGENERATE`.
- `shell.ShellModel(x0, conn, elem_type, thickness, E, nu, drill_factor=1e-4)`:
  - 노드당 6 dof(병진 3, 회전 3), 요소 국부 평면 투영(뒤틀림 무시). QUAD: 막 = 비적합 모드 Q4(QM6 계열), 굽힘·전단 = MITC4. TRIA: 막 CST + 굽힘 DKT(또는 MITC3). 회전 드릴링 강성 = `drill_factor·E·t·A`.
  - `K() -> scipy.sparse.csr (6N,6N)` 대칭.
  - `condensed_forces(u_t(N,3)) -> F(N,3)`: 전 노드 병진 강제, 회전 자유 → Schur 보수 `F = (K_tt − K_tr K_rr⁻¹ K_rt) u_t`.
  - `solve(F(N,3), spc=[(node_idx,"dofs")]) -> (u(N,6), R(N,3))`: 병진 하중만, spc는 병진 dof. 특이 → `SOLVER_SINGULAR`.
  - `strains(u(N,6)) -> eps(E,2,3)`: 요소 중심, layer 0=bottom(z=−t/2), 1=top(+t/2), `ε = ε_m + z·κ`, 요소 국부계 텐서 성분. 국부계 x축 = 노드1→2 방향(투영면), Radioss 쉘 국부계와 동일 규약.
- `tstar.scan(time, eps_eq(F,E), centroids(E,3), top_n, top_k, min_dist, time_window=(None,None), exclude_mask=None) -> {"tstar":{frame_pos,time,elem_pos,eps_eq}, "candidates":[...], "hotspots":[...], "history":{time,eps_max,eps_hotspot1}}` (`esl.md` §6.4 규칙).

## 5. Impl-C 파이프라인·CLI·내보내기

- CLI: `python -m esl run --config cfg.yaml --rad X_0000.rad --results <csv_dir> --out <case_dir> [--frame N] [--support-nodes id1,id2,id3] [--stage extract|tstar|esl|validate|export|all]`. 각 단계는 앞 단계 산출물을 읽어 재개 가능. 입력 폴더에는 쓰지 않음, 출력 폴더 기존 파일 덮어쓰기 시 `_backup/<timestamp>/`로 이동.
- 출력 폴더(`esl.md` §3.1 준용): `01_extract/`(model.npz, model_meta.json, strain_tensor.npz, disp.npz), `02_tstar/`(tstar.json, history.csv, hotspots.csv, candidates.csv), `03_bc/support.json`(3-2-1 노드 ID·dof, pca 평면), `04_esl/`(u_rel.npz/csv, f_eq.npz/csv, esl_summary.json), `05_val/`(compare.csv, validation.json), `06_export/`(esl_cload.inc, esl_bcs.inc, esl_force.fem, f_eq.csv, u_rel.csv, reactions_321.csv, tstar_candidates.csv, hotspots.csv, validation.csv), `run.json`(입력 경로·sha256·설정 스냅샷·단계별 요약).
- S4: t* 프레임 `u` → `remove_rigid` → `F_eq = condensed_forces(u_rel)`. 평형: `|ΣF|/Σ|F|`, 합모멘트(중심 기준)/(Σ|F|·L_bbox) 기록, `> 1e-6`이면 경고.
- S5: `solve(F_eq, 321)` → u_val; `u_val`에서 최소제곱 미소 강체(또는 kabsch.fit) 제거 후 `u_rel`과 비교 → `disp_rms_rel = RMS(Δ)/max|u_rel|`, 반력 합 `|R|/Σ|F|`. hotspot: `strains(u_val)` ε_eq(layer max) vs Radioss t* ε_eq, 상위 `hotspot_eval_count`. 판정 기준은 설정.
- 내보내기: `esl.md` §8 규약, 단 `/CLOAD`·FORCE = **전 노드** 비영 성분(`force_zero_tol_rel`), `esl_bcs.inc` = 노드별 `/GRNOD/NODE` + `/BCS`(3-2-1 dof 플래그, 회전 000). `.fem` = 쉘 bulk(GRID, CQUAD4/CTRIA3, (PID,t) 조합별 PSHELL, MAT1) + FORCE + SPC1(3-2-1), SUBCASE DISP/SPCF/STRAIN 출력. ID ∈ `[id_offset, id_offset+999999]`를 off+1부터 순차 배정(esl.md §8의 고정 오프셋 대체), `max_ids`(func·grnod·load·bcs·prop) 중 하나라도 ≥ id_offset이면 `ID_RANGE_COLLISION`. inc·fem은 ASCII 전용. validation.csv hotspot 열은 `eps_rad,eps_val,rel_err`(자체 솔버 값).
- 설정(`config/esl.example.yaml`): `esl.md` §2에서 `case`, `extract`(frame_stride, eq 모드), `tstar`, `support`(candidates: pca4, `node_ids` 수동), `solver`(drill_factor), `validation`, `export`, `units`만. 판정 기준·오프셋은 설정에서만 읽음.

## 6. 검증 항목 (Verifier)

| ID | 기준 |
|---|---|
| T-RAD-1~2 | `esl.md` V-RAD-1·2 (fixture: include 2단, /PART 3개, title 대소문자·공백, LAW1/2/36, 미지원 law+override, 요소 두께 우선) |
| T-IO-1 | CSV→npz shape·dtype·순서, 다른 파트 행 무시, 누락 → `ID_MISMATCH`, done.json 없음 → `TOOL_OUTPUT_MISSING`, 로드 allow_pickle=False |
| T-SH-1 | K 대칭, 강체 6모드 `‖K·r‖/‖K‖‖r‖ < 1e-10`(평판), 막 patch test 정확(1e-10), 굽힘 patch(상수 곡률) 정확 |
| T-SH-2 | 외팔보 판(쿼드·트라이 각각) 끝단 처짐 vs 보 이론 ±3%, 막 면내 굽힘 ±3%(QM6) |
| T-SH-3 | `solve(condensed_forces(u))` = u + 강체(제거 후 RMS 1e-9), 회전 강체 변위장에서 `strains`≈0 |
| T-KB-1~2 | `esl.md` V-KB-1·2(전 노드 기준). 잔차 경고/실패 임계는 폐기(전 노드 적합에서 잔차 = 변형 자체) |
| T-SUP-1 | 기울어진 판에서 pca 4꼭지점 정확, pick_321 비특이, 공선 후보 → `SUPPORT_DEGENERATE` |
| T-TS-1 | `esl.md` V-TS-1 |
| T-E2E-1 | 합성 사례: 판 메시 + 3-2-1 지지 하중 F_app로 변형 u_d → 프레임별 대회전·병진 강체운동 합성 → CSV(TCL 포맷) + rad fixture → `run --stage all` → F_eq(비지지 노드) = F_app (rel 1e-6), `disp_rms_rel < 1e-8`, 반력≈0, 내보내기 파일 생성·ID 범위 |
| T-EXP-1 | inc·fem 골든(소형 메시): /CLOAD 수 = 비영 성분 수, /BCS 플래그, FORCE·SPC1, 두께별 PID |
| T-NOISE-1 | 변위 정밀도(`extract.disp_precision`) 잡음 바닥 추정: `noise.force_rel` 경고, `noise.hotspot_strain_rel > noise_strain_rel_max` → FAIL(`NOISE_FLOOR`). float32 합성 사례에서 검출 |
| T-FS-1 | 출력 경로 겹침 검사는 realpath 기준(심링크 우회 불가), 보호 대상 = rad 폴더·include 폴더·CSV 폴더 |
| T-SEC-1 | 정적: `pickle`, `allow_pickle=True`, `shell=True`, `os.system`, 하드코딩 절대경로 0건 |

---

## 7. 실데이터 반영 (P1a-2, 2026-10-19) — §3.2·§3.3·§4 tstar·§5 S2/S5를 대체

근거: #1 probe(HyperWorks 2026.1, Tcl 8.5.9). h3d 결과 유형 = `Displacement`, `Max_Strain`(텐서 XX YY ZZ XY YZ ZX + 불변량 vonMises 등, layer `Mid`만), `Plastic Strain`(스칼라, `Mid`), `Von Mises`, `Velocity`, `Contact Forces`. 프레임 126개(0~0.125 s, 1 ms). chassis_rear = component id 10, 223,415 요소.

### 7.1 지표 의미
- `Max_Strain`, `Plastic Strain`은 **요소별 누적 최대(max-hold)** 값이다: 한 번 최대에 도달하면 이후 그 값을 유지. 순간 총변형률은 h3d에 없다.
- 따라서 t*는 "값이 처음 최대에 도달한 프레임(first-reach)"이다. `first_reach(e) = min{f : v[f,e] ≥ v[F-1,e]·(1−rtol)}`, rtol = 설정 `tstar.reach_rtol`(기본 1e-6).
- 지표 선택 `tstar.metric`: `max_strain`(기본, Max_Strain 텐서로 계산한 ε_eq) | `plastic_strain`. 두 지표 결과는 항상 둘 다 tstar.json에 기록.
- 층: `Mid`만 존재 → ε_eq는 막(중립면) 변형률 기준. 솔버 비교도 z=0(막) 변형률. `extract.layers: [mid]`.
- ε_eq 공식은 §4 그대로(비압축 in-plane, exx·eyy·exy). 전단 규약(`extract.shear_convention: auto|tensor|engineering`) — auto는 HyperView `vonMises`와 가장 잘 맞는 쪽을 고르고 최대 상대 불일치를 extract 요약에 기록(> 5%면 경고).

### 7.2 TCL 추출(1회 실행, 3 패스) — 출력 CSV
| 패스 | 대상 | 파일 | 헤더 |
|---|---|---|---|
| — | 전 프레임 시간 | `frames.csv` | `frame_index,time` |
| — | 파트 노드 초기좌표 | `model.csv` | `node_id,x0,y0,z0` |
| A | 마지막 프레임, 파트 전 요소 | `final.csv` | `elem_id,vm_hv,exx,eyy,ezz,exy,epsp` |
| B | 전 프레임, 집합 H만 | `history.csv` | `frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp` |
| C | 후보 프레임 D, 파트 전 노드·전 요소 | `disp.csv`, `strain_frames.csv` | `frame_index,node_id,ux,uy,uz` / `frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp` |
- H = (final vm_hv 상위 `hot_k`) ∪ (final epsp 상위 `hot_k`), `hot_k` 기본 200.
- D = 각 지표(vm_hv, epsp)에 대해 H를 최종값 내림차순으로 훑으며 first-reach 프레임을 서로 다른 것만 `top_n_times`(기본 5)개까지 모은 합집합(≤10). rank 1 = 최종값 1위 요소의 first-reach.
- TCL 인자: `-part`(필수 또는 request.txt), 선택 `-hot_k`, `-top_n`. 결과 유형·성분·layer 이름 기본값은 위 probe 값. done.json에 `candidate_frames:{max_strain:[...],plastic_strain:[...]}`, `hot_k`, `reach_rtol`, 패스별 행 수·소요시간.
- 수치 `%.17g`, Tcl 8.5 호환 유지.

### 7.3 Python 패킹(`pack_results`) — npz
`final.npz`{elem_id(E,), vm_hv(E,)f4, eps(E,3)f4[exx,eyy,exy], ezz(E,)f4, epsp(E,)f4}, `history.npz`{time(F,), frame_index(F,), elem_id(H,), vm_hv(F,H), eps(F,H,3), ezz(F,H), epsp(F,H)}, `strain_frames.npz`{frame_index(D,), time(D,), elem_id(E,), vm_hv(D,E), eps(D,E,3), ezz(D,E), epsp(D,E)}, `disp.npz`{frame_index(D,), time(D,), node_id(N,), u(D,N,3)f8}. 기존 strain_tensor.npz 형식은 폐기(합성 E2E도 새 형식으로).

### 7.4 S2·S5 규칙
- tstar.json: 지표별 `{tstar:{frame_index,time,elem_id,value}, candidates:[{rank,frame_index,time,elem_id,value}], history:{time, m(f)=max_{e∈H} v[f,e]}}`. Python이 history.npz로 first-reach를 재계산해 TCL의 D와 일치 확인(불일치 경고).
- hotspot(검증 대상) = t*에서 "상승 중"인 H 요소: `v[t*,e] > v[t*−1,e]·(1+rtol)` (t*=0이면 v>0). 이들의 hold 값은 t*의 순간값과 같다. 거리 필터(`hotspot_min_dist`, 요소 중심) 후 상위 `top_k_hotspots`. rank 1(최종값 1위)은 정의상 포함.
- S5: 솔버 막 변형률 ε_eq vs 위 hotspot의 Radioss ε_eq(같은 공식). 상승 중이 아닌 요소는 비교 제외(이유 기록).

### 7.5 솔버 규모
- `solver.backend: auto|cholmod|pardiso|superlu|iterative`. auto = cholmod → pardiso → superlu, 예상 직접법 메모리 > 가용×0.95면 경고 후 iterative. 규모 상한 없음. `solver.iter_rtol`(기본 1e-10, S5 전체계는 1e-12 권장), `solver.iter_maxiter`.
- 실패 코드 추가: `SOLVER_NOT_CONVERGED`(반복법 미수렴).
- 실측(4코어): 22만 요소 pardiso 약 2분·9.8 GB, 30만 요소 약 3분·13 GB. 100만 요소 추정 40–45 GB(운영 512 GB 서버 기준 직접법 가능).
- 큰 얇은 패널의 왕복 RMS는 조건수 때문에 1e-8~1e-7 수준(백엔드 무관) — 검증 기준(`disp_rms_rel_max`)보다 충분히 작음.
