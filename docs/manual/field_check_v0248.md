# v0.24.8 현장 확인 — ④·옛 ③ 격자 지그 ESL (2026-11-26)

계약 `docs/contracts/esl_jig_grid_map.md`(§3·§5·§6·§8). DB migration 없음. 설정 `bead_doe.rank.jig_grid` 는 없으면 기본값(관리자 매뉴얼 §4.8). 결과는 각 표 오른쪽 칸에 적는다. 전제: 엔트리 Case 의 `04_esl` 에 지그 변위·스프링 결과(③ ESL v0.24.4 이후 실행)가 있다.

## ① 서버 반영
| # | 할 일 | 확인 | 결과 |
|---|---|---|---|
| 1 | `E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1`(관리자 매뉴얼 §3.0) | 화면 오른쪽 위 버전 0.24.8 | |
| 2 | `ESL-Backend`·`ESL-Worker` 재시작(§4.2) | health OK, 환경 점검 OK | |

## ② F-JG-1 — ④ 새 스터디: 지그 탭·3D·순위 문구
Case 에 지그 결과가 있는 엔트리로 ④ 새 스터디(기준 형상 + 형상 2~3개)를 만들어 실행한다.

| 볼 것 | 기대 | 결과 |
|---|---|---|
| [하중 정의] 탭 | 지그 변위·지그 스프링 탭이 있고 활성(옛 ④ 에는 탭 없음) | |
| 3D 비교(지그 변위·스프링) | 기준 | 고른 형상 3D 가 열리고 조건 줄에 "격자 3 mm" | |
| 순위 정의 문구 | "형상마다 Case 지그를 3 mm 격자로 매핑(기준 d000)" + "차이 n % 이내는 매핑 오차 범위" | |
| 순위 기준 | 지그 변위(jd). 오차 범위(3 % 이하·격자 민감도 중 큰 값) 안 행에 "오차 범위" 표식 | |
| 경고 줄 | 정보(ⓘ) `JIG_GRID_RANK` 1줄, 문구에 코드 머리·영문 꼬리가 없음 | |

## ③ F-JG-2 — 결과의 격자 진단
결과 카드(또는 GET `/doe/studies/{id}/results` 의 `jig.grid`·`jig.methods.*.grid`)에서 값을 적는다. 사내 서버 LLM 에 묻는 질문은 아래를 **그대로** 붙여 넣는다.

```
읽기 전용 진단 — 파일 쓰기·수정 금지, 계산이 필요하면 임시 폴더에서만.
esl-platform 서버의 ④ 형상 직접 비교 스터디 #<번호> 에 대해 GET /doe/studies/<번호>/results 응답의 jig.grid 와 jig.methods.*.grid 를 표로 정리하세요.
- jig.grid: cell_mm, n_shapes, n_shapes_failed, tie_miss_max, tie_area_ratio_min·max, k_scale_min·max, noise_floor, corr_rel_max, sample_outside_max, warnings.
- 방식별 grid: n_ok, n_failed, recon_mac_d000, recon_umax_err_d000, conv[{cell_mm, dpi_max, dumax_max, mac_min}], alpha.
- 응답 warnings 중 code 가 JIG_GRID_ 로 시작하는 항목의 code 와 message 를 모두 적으세요.
- 기존 스터디 데이터·설정·DB 는 바꾸지 마세요.
```

| 항목 | 기대 | 결과 |
|---|---|---|
| tie miss(`tie_miss_max`) | `tie_miss_frac_max` 0.1 미만(형상마다 표시) | |
| 면적비(`tie_area_ratio_min`·`max`) | 0.5~2 안(밖이면 `JIG_GRID_AREA_RATIO` 정보) | |
| d000 재현 MAC(`recon_mac_d000`) | 0.99 이상 권장 — 값을 적음 | |
| 수렴 ΔΠ(5 mm·10 mm, `conv`) | ΔΠ_5 ≤ 0.05(초과 시 `JIG_GRID_CONV` 정보) — 값을 적음 | |
| `noise_floor` | 0.03 이상(= max(ΔΠ_5, 0.03)) — 순위 오차 범위 % 와 같음 | |
| 합성 감각 점검 | 기준과 같은 형상을 다른 크기로 메시한 형상은 "오차 범위" 표식 | |

## ④ F-JG-3 — Case 에 지그 결과가 없을 때
지그 변위·스프링 결과가 없는 Case(③ ESL 을 v0.24.4 이전에 실행했거나 지그 꺼짐)의 엔트리로 ④ 스터디를 실행한다.

| 볼 것 | 기대 | 결과 |
|---|---|---|
| 경고 | `JIG_GRID_SOURCE_MISSING` — 엔트리·방식·사유가 들어 있고 "그 Case 에서 ③ ESL 을 다시 실행(v0.24.4 이후)한 뒤 스터디를 복제하세요" | |
| 순위 | 재풀이(solve) 순위, 스터디는 실패 없이 끝남 | |
| 조치 | 그 Case 에서 ③ ESL 을 다시 실행 → 스터디 복제 → 지그 탭·격자 순위가 생김 | |

## ⑤ F-JG-4 — 옛 ④·옛 ③ 스터디
| 볼 것 | 기대 | 결과 |
|---|---|---|
| 옛 ④ 스터디(v0.24.7 이전) 결과 | 지그 탭 없음, 경고 줄에 정보 "이 스터디는 지그 ESL 없이 계산됐습니다 — 복제하면 Case 지그를 격자 매핑해 계산합니다" 1줄 | |
| 옛 ③(안마다 메시) 스터디 | 같은 줄 1줄, 지그 탭은 "계산하지 않았습니다(v0.24.8 이전 스냅샷) … 복제하면 …" 사유 | |
| 순위·3D | 이전과 같음(결과 파일 바이트 불변) | |
| 복제 | 복제본은 지그 탭·격자 순위(위 ② 와 같음) | |

## ⑥ F-JG-5 — 평가 시간 실측(형상당)
계약 §8 외삽(50k/100k/150k 노드 ≈ 50/120/220 s, 분해 2회 추가)을 실측으로 확인한다. BD_EVAL 작업 로그의 형상별 시간과 `jig.factor.seconds`(분해)를 적는다.

| 형상 | 노드 수 | 격자 지그 추가 시간 | 형상당 평가 전체 | 피크 메모리 | 메모 |
|---|---|---|---|---|---|
| | | | | | |
| | | | | | |
| | | | | | |

## ⑦ 결과 보고
- ②~⑥ 표 전체, 스터디 실행 시간, 이상이 있으면 작업 로그와 `backend.log`.
