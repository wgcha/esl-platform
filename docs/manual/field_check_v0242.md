# v0.24.2 현장 확인 — 덤프 방식 h3d 의 경계력·내력 원자료 ESL 때 보충 (2026-11-19)

계약 `docs/contracts/esl_bforce_ondemand.md`. 클라우드 시험은 가짜 HyperView(hwmock·가짜 hw)로만 돌았다 — 아래 순서로 **재해석 h3d**(Engine 에 `/H3D/NODA/CONT·CONT2·ACC·MASS·FINT` 추가, `field_check_v0240.md` ②)에서 확인하고 결과는 각 표 오른쪽 칸에 적는다. 고칠 것은 **설정만**(코드 수정 없음). 현장 #82 의 기존 h3d(CONT·ACC 만)로도 같은 순서가 되며 그때 기대 등급은 경계력 **contact**·내력 **none**("내력 출력 없음")이다.

## ① 서버 반영
| # | 할 일 | 확인 | 결과 |
|---|---|---|---|
| 1 | `E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1`(관리자 매뉴얼 §3.0) → 서비스 재시작 | 화면 오른쪽 위 버전 0.24.2 | |
| 2 | DB migration 없음 — 확인만 | 백엔드 로그에 migration 메시지 없음 | |
| 3 | 사용자 PC `update.bat` 은 PC 에서 TCL 을 직접 돌릴 때만(서버 h3d 추출이면 생략) | – | |

## ② 설정 확인 (기본값이면 손대지 않음)
| 위치 | 키 | 기본 | 확인 | 결과 |
|---|---|---|---|---|
| 코어 설정(esl.yaml — `esl_platform.yaml` 의 `core.config_path`) | `bforce.on_demand` | true(절이 없으면 true) | false 로 되어 있지 않은지 | |
| 플랫폼 설정 `.runtime\config\esl_platform.yaml` `altair:` | `bf_on_demand_timeout_s` | 1800 | 없으면 기본값 | |
| 같음 | `bf_on_demand_wait_s` | 600 | 없으면 기본값 | |
| 같음 | `max_concurrent_hw` | 2 | 라이선스 수와 맞는지 | |

## ③ 재해석 h3d — 추출(덤프 방식 확인) → ② → ③ ESL(보충)
1. 새 Case(h3d 입력, 대상 파트 chassis_rear) → **① 추출**. 끝나면 추출 로그에서 덤프 방식인지 본다.

| 볼 값 | 어디 | 기대 | 결과 |
|---|---|---|---|
| `strain source: strain_tensor (Strain, dump, …)` | ① 작업 로그 | 덤프 방식(Max_Strain·Plastic Strain 없음). `pass A start` 가 보이면 비덤프 — ⑦ 회귀 항목으로 기록 | |
| `GetDataTypeList` | `E:\VD_SIMULATION_WEB\esl-data\_h3d\<Case 폴더>\raw\done.json` 의 `api` | `Contact Forces` 외에 CONT2·MASS·FINT 표시명이 있는지(이름은 `field_check_v0240.md` ③ 표) | |
| ① 소요 시간 | 작업 목록 | v0.24.1 과 같은 수준(이번 수정은 추출을 바꾸지 않음) | |
| 경고 `BF_REQUEST_DEFAULTED` | ① 작업 경고 | **없어야 함**(있으면 코어 설정 오류 — 관리자에게) | |

2. **② t\*·지지점** 확정(평소대로). 고른 프레임 번호 f 를 적는다: f = ____
3. **③ ESL** 실행 → 작업 [로그 보기].

| 볼 값 | 어디 | 기대 | 결과 |
|---|---|---|---|
| `[esl-worker] 경계력 원자료 보충 시작: 프레임 f(t=…) 이 01_extract 에 없음 → HyperView bf 전용 추출 …` | ESL 로그 | 1번 | |
| `bf-only: part 21 (chassis_rear): … nodes, 61 frames, frames {f}` · `bforce: cont = Contact Forces {X Y Z}` … | ESL 로그(TCL 진행 줄) | 찾은 종류가 ①의 표시명과 같음 | |
| `[esl-worker] 경계력 원자료 보충 완료: 프레임 f, 종류 {…}, N s → 01_extract/bforce.* 병합(프레임 [] + [f])` | ESL 로그 | 보충 시간 N ≈ 180~240 s(15.6 GB h3d 기준 추정) | N = |
| 경계력 줄 `esl-bforce-line` | ③ 결과 카드 아래 | 재해석 h3d(CONT2 있음) = **등급 full**, 기존 h3d = contact(한계 문구 "tie 체결력 미포함") | |
| 내력 줄 `esl-fint-line` | 같음 | 재해석 h3d(FINT 있음) = `내력 ESL: F = ±FINT · Σ|F| … · 잔차 … · 재현 MAC …`, 기존 h3d = "자료 없음 — 내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가" | |
| 3D 출처 탭(v0.24.1) | ③ 3D 카드 머리 | [경계력 ESL]·[내력 ESL] 탭 활성(내력은 FINT 있을 때) | |
| 판정 기준 | `field_check_v0240.md` ⑥ 표 | 재현 MAC ≥ 0.9 등 | |

## ④ 재사용 · 다른 프레임
| # | 할 일 | 기대 | 결과 |
|---|---|---|---|
| 1 | 같은 Case·같은 프레임으로 ③ ESL 다시 | 로그 `경계력 원자료: 프레임 f 은 01_extract 에 있음 — 보충 안 함`, HyperView 실행 없음, ESL 시간 = v0.24.1 수준, 경계력·내력 값 ③ 과 같음 | |
| 2 | ② 에서 다른 후보 프레임 g 로 바꾸고 ③ ESL | 보충 1번 더(`프레임 [f] + [g]`) | |
| 3 | 파일: `E:\VD_SIMULATION_WEB\esl-data\<Case 폴더>\01_extract\bforce.json` | `frames` = [f, g](오름차순), `fills` 2개, `kinds.cont.frames` | |
| 4 | 파일: `…\01_extract\bforce_ondemand.json` | `attempts` 2개(status ok, job_id = 각 ESL 작업) | |
| 5 | 파일: `…\<Case 폴더>\_backup\<UTC>\01_extract\bforce.json`·`bforce.npz` | 두 번째 보충 때 옮겨진 첫 번째 파일(삭제 아님) | |
| 6 | 파일: `E:\VD_SIMULATION_WEB\esl-data\_h3d\<Case 폴더>\bf_ondemand\raw\done.json` | `"mode": "bf_only"`, `frames` = [g], `n_frames` 61, `frame_times` | |

## ⑤ 실패 경로 (선택 — 확인 후 설정 되돌리기)
| # | 할 일 | 기대 | 결과 |
|---|---|---|---|
| 1 | `altair.bf_on_demand_timeout_s: 60` → 워커 재시작 → 아직 보충 안 한 프레임으로 ③ ESL | ESL **성공**, 로그 `보충 실패(TIMEOUT)`, 경계력 줄 = `경계력 ESL: 자료 없음 — 경계력 원자료 보충 실패 — 프레임 h: 시간 초과 60 s(altair.bf_on_demand_timeout_s). ③ ESL 을 다시 계산하면 다시 시도합니다`, 내력 줄 같은 사유, 3D 경계력·내력 탭 비활성 사유 같은 문구, 작업 경고 `BF_EXTRACT_FAILED: …` 1건 | |
| 2 | 설정 되돌리기(1800) → 같은 프레임 ③ ESL | 다시 시도해 보충 완료 | |
| 3 | (라이선스 점검 시간에만) 라이선스 서버를 막을 수 있으면 ③ ESL | `보충 실패(LICENSE)` 또는 `(HW_FAILED)` + hw 로그 요약 — ESL 은 성공 | |

## ⑥ 강성 스터디 — 경계력·내력 버튼
1. 이 Case 를 엔트리로 쓰는 스터디(같은 메시 방식 ①·②·③)를 열거나 새로 만든다.
2. 3D 머리 [경계력 ESL 계산]·[내력 ESL 계산](필요한 탭에만 1개) → 작업 완료 → 탭 [경계력 ESL]·[내력 ESL].

| 볼 값 | 기대 | 결과 |
|---|---|---|
| 탭 비활성 사유 | v0.24.1 의 `BF_NOT_FOUND`(경계력 자료 없음) 사유가 사라짐 | |
| 칩 `bf-chip`·`nodal-chip-fint` | ③ 등급과 같음(full·contact / 내력 값) | |
| 순위표 주 열 경계력 C·내력 C | 값이 채워짐 | |

## ⑦ 회귀 · 쓰기 금지 확인
| # | 할 일 | 기대 | 결과 |
|---|---|---|---|
| 1 | v0.24.0 이후 **비덤프**로 추출한 기존 Case(경계력 자료 있음)에서 ③ ESL | 로그 "있음 — 보충 안 함", HyperView 실행 없음, 경계력·내력 값이 v0.24.1 결과와 같음 | |
| 2 | 결과 폴더 입력 Case(PC 추출)에서 ③ ESL | 보충 줄 없음, v0.24.1 과 같음 | |
| 3 | 입력 폴더 `E:\VD_SIMULATION_WEB\esl-input\…\*.h3d`·rad 수정 시각 | ③ 전후 같음(읽기만) | |
| 4 | SPDM·입력 폴더에 새 파일 | 없음(쓰는 곳은 `esl-data\<Case>\01_extract`·`_backup`·`esl-data\_h3d\<Case>\bf_ondemand` 만) | |
| 5 | 같은 Case 를 **① 다시 추출** | `esl-data\<Case>\_backup\<UTC>\01_extract\` 에 보충된 bforce.*·bforce_ondemand.json 이 함께 옮겨짐, 새 01_extract 에는 (덤프면) bforce 없음 → 다음 ③ ESL 때 다시 보충 | |

## ⑧ 결과 보고 (이슈 #82 코멘트)
- ③ 표 전체, ④-3·4·6 파일 내용(앞부분), 보충 시간 N, ⑥ 칩 문구, 이상이 있으면 ESL 로그 전체(`esl-data\<Case>\logs\<작업 id>\step_01_ESL.log`)와 `_h3d\<Case>\bf_ondemand\raw\done.json`·`progress.log`.
