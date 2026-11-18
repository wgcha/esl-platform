# v0.24.0 현장 확인 — 경계력 ESL · 내력 ESL (2026-11-19)

계약 `docs/contracts/esl_bforce.md`(경계력)·`docs/contracts/esl_fint.md`(내력·평가 영역·소성). 클라우드 시험은 합성 자료로만 돌았다 — 아래 순서로 실제 모델에서 확인하고, 결과는 각 표 오른쪽 칸에 적는다. 고칠 것은 **설정만**(코드 수정 없음).

## ① 서버 반영
| # | 할 일 | 확인 | 결과 |
|---|---|---|---|
| 1 | `E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1`(관리자 매뉴얼 §3.0 — git pull·빌드 포함) → 서비스 재시작 | 화면 오른쪽 위 버전 0.24.0 | |
| 2 | 사용자 PC 루트 `update.bat`(HyperView TCL 배포 — 서버 h3d 추출을 쓰면 생략) | `ESL_extract.bat` 날짜 갱신 | |
| 3 | DB migration 없음 — 확인만 | 백엔드 로그에 migration 메시지 없음 | |

## ② 낙하 Engine 출력 카드(재해석할 기준 모델 `<run>_0001.rad`)
```text
/H3D/DT
#       Tstart     Tfreq
        0.0        0.001
/H3D/NODA/DISP
/H3D/NODA/ACC
/H3D/NODA/CONT
/H3D/NODA/CONT2          ← tie 체결력(경계력 full 등급)
/H3D/NODA/MASS           ← 노드 질량(질량 스케일링 포함 — 관성 항 정확)
/H3D/NODA/FINT           ← 노드 내력(내력 ESL)
/H3D/PART
#  part_ID1  part_ID2 ...    (대상 파트 chassis_rear id — 한 줄 10개까지, 전 부품이면 이 카드 생략)
        10
```
- **Radioss 2024.1 동작 여부 확인 필요**: `CONT2`·`MASS`·`FINT` 는 2026 Reference Guide 기준 철자다. 2024.1 Starter 가 키워드를 모른다는 경고(또는 h3d 에 결과 유형이 없음)면 그 줄만 빼고 다시 돌린다 — 없는 종류는 '없음'으로 기록될 뿐 추출은 실패하지 않는다.
- 이미 있는 DISP·ACC·CONT 는 그대로 둔다. `/H3D/PART` 로 대상 파트만 쓰면 h3d 크기가 줄어든다.

## ③ HyperView 결과 유형 표시명 확인 · 설정 위치
1. 새 h3d 를 HyperView 에서 연다 → Contour 패널 → Result type 목록에서 이름을 그대로 적는다(예 `Contact Forces`, `Acceleration`, `Internal Forces`?).
2. 표시명이 기본 목록과 다르면 **코어 설정 파일**(서버 `.runtime\config\esl_platform.yaml` 의 `core.config_path` 가 가리키는 esl.yaml)의 `bforce.result_names` 에 앞쪽으로 더한다(대소문자·공백·밑줄은 무시하고 찾음):
```yaml
bforce:
  result_names:
    fint: [Internal Forces, Internal Force, FINT]      # ← 여기에 HyperView 표시명 추가
    cont2: [Tied Contact Forces, Contact Forces (TYPE2), CONT2]
    mass: [Nodal Mass, Mass, MASS]
```
3. 저장 후 워커 재시작(관리자 매뉴얼 §4). 코드 수정 없음.

| 종류 | 기본 첫 이름 | 현장 표시명 | 결과 |
|---|---|---|---|
| CONT | Contact Forces(확인됨) | | |
| ACC | Acceleration(확인됨) | | |
| CONT2 | Tied Contact Forces | | |
| MASS | Nodal Mass | | |
| FINT | Internal Forces | | |

## ④ Case ESL 다시 생성 → 요약 줄
Case 에서 **h3d 추출 → t* → ESL** 을 다시 실행한다(추출을 다시 해야 새 결과 유형이 들어감). ESL 화면 결과 카드 아래 세 줄을 본다.

| 줄(testid) | 볼 값 | 기대 / 판단 | 결과 |
|---|---|---|---|
| 경계력 ESL(`esl-bforce-line`) | 등급 | CONT2 가 생겼으면 **full**, 아니면 contact(한계 문구 "tie 체결력 미포함") | |
| | 관성 이완 ā(g)·보정 % | full 이면 ā·보정이 작아야 함(자기평형) | |
| | 재현 MAC · umax 오차 | 표 ⑥ 기준 | |
| | ⚠ CONT 부호 의심 | 나오면 `bforce.signs.cont: -1` 로 바꿔 ESL 다시(결과 비교) | |
| 내력 ESL(`esl-fint-line`) | F = FINT / −FINT | 부호는 자동(일 양수) — 정보만 | |
| | 잔차 힘·모멘트 | 1e-3 이하가 정상. 넘으면 ⚠ 불평형(FINT_UNBALANCED) → 공유 노드·추출 누락 확인 | |
| | 공유 노드 n(회전 연결 m) | 0 이 이상적. n > 0 이면 그 노드 내력에 다른 부품 힘이 섞임(값은 그대로 사용 — 위치는 Case `04_esl/fint.json` 의 `fint.shared_nodes`(bbox·node_ids·by_part)) | |
| | 재현 MAC · umax 오차 · 반력 | 표 ⑥ 기준 | |
| 소성(`esl-plastic-line`) | 면적 % · 최대 εᵖ | 면적이 크면(예 > 5 %) 선형 ESL 로는 재현이 어려움 — 해석 판단에 참고. '없음' = h3d 에 소성 변형률 없음 | |

## ⑤ 강성 스터디 — 추가 계산 · 4개 탭 비교
1. 끝난 스터디(같은 메시 방식 ①·②·새 ③)를 연다 → 3D 머리의 **[경계력 ESL 계산]**·**[내력 ESL 계산]**(보기가 없는 출처마다 버튼)을 누른다(작성자·관리자, 기존 작업 큐 — 형상 생성 없이 선형 풀이만, 기존 순위·CSV·보고서 그대로).
2. 작업이 끝나면 탭 [지그 ESL | 전 노드 ESL | 경계력 ESL | 내력 ESL] 를 차례로 본다.

| 볼 값 | 어디 | 판단 | 결과 |
|---|---|---|---|
| 탭 활성/사유 | 탭에 마우스(또는 키보드 포커스) | 내력 탭 비활성 사유 "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가" = ② 미반영 | |
| 칩 | 경계력 `bf-chip` · 내력 `nodal-chip-fint` | 등급·재현 MAC·umax 오차·(내력) 잔차·공유 노드·소성 % | |
| 주 순위(컴플라이언스 비) | 순위표 주 열(지그 C · 재풀이 C · 경계력 C · 내력 C) | 상위 3안이 탭끼리 얼마나 같은지(경계력 ↔ 내력이 비슷하면 하중 정의가 안정) | |
| umax(평가 영역) | 순위표 열 · ⓘ 지표 정의의 영역 문구 | 새 스터디만 값이 있음. 자유 경계 영향이 크면 설정 `bead_doe.rank.eval_region: exclude_free_edges` 로 새 스터디 | |
| 3D | 기준 | 안 응답 컨투어 + 하중 화살표 | 화살표가 접촉·체결 위치에 모이는지(경계력), 부품 전체에 분포하는지(내력) | |

## ⑥ 판정 기준
| 항목 | 통과 | 주의 | 실패(원인 확인) |
|---|---|---|---|
| 기준 재현 MAC(경계력·내력) | ≥ 0.9 | 0.8 ~ 0.9 | < 0.8 |
| 재현 umax 오차 | ≤ 20 % | 20 ~ 40 % | > 40 % |
| 3-2-1 반력 비(재현) | ≤ 1e-3 | ≤ 1e-2 | > 1e-2(하중 불평형) |
| 내력 잔차 ‖ΣF‖/Σ‖F‖(변형 형상) | ≤ 1e-3 | ≤ 1e-2 | > 1e-2(공유 노드·추출 누락) |
| 공유 노드 수 | 0 | 대상 노드의 1 % 미만 | 그 이상(부품 경계 모델링 확인) |
| 경계력 관성 이완 보정(full 등급) | ≤ 5 % | ≤ 20 % | > 20 %(CONT2·MASS 이름·부호 확인) |
| 소성 면적 비율 | ≤ 1 % | 1 ~ 5 % | > 5 %(선형 ESL 한계 — 결과 해석 주의) |
| 탭 간 상위 3안 일치 | 2안 이상 같음 | 1안 | 0안(하중 정의 민감 — 검증 낙하로 확인) |

- 기준 재현 MAC·umax 오차 경고 기준은 설정 `bforce.recon_mac_min`(0.9)·`recon_umax_err_max`(0.2), 내력 잔차 허용치는 `bforce.fint.unbalanced_force_rel`·`unbalanced_moment_rel`(1e-3), 소성 문턱은 `bforce.plastic_eps_min`(0.002).
- 한계: 내력 ESL 은 병진 내력만 쓴다(노드 모멘트 미사용) — RBODY·스프링·빔 연결 노드는 "회전 연결 노드" 로 표시된다.
