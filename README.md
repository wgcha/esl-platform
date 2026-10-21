# ESL 계산 코어 (P1a)

Radioss 낙하해석 결과에서 대상 쉘 파트의 **등가정적하중(ESL, F_eq)** 을 계산하고, 자체 선형 쉘 솔버로
검증한 뒤 Radioss `/CLOAD`·`/BCS` include, OptiStruct `.fem`, CSV로 내보낸다.
계약: `docs/contracts/esl_core.md` (보조 `docs/contracts/esl.md`).

## 1. 설치

Python ≥ 3.11 (Linux·Windows).

```bash
pip install -e .[test]      # numpy, scipy, pyyaml (+ pytest)
python -m pytest -q         # 시험
```

## 2. 입력 준비 (Windows, HyperView TCL 1회)

h3d는 클라우드에서 읽지 않는다. Altair HyperView가 있는 Windows PC에서 TCL로 CSV 폴더를 만든다
(자세한 내용: `resources/tcl/README.md`).

### 2.1 Windows 설치·업데이트 (권장) — **사용자 PC**(HyperView TCL 배포)

> 이 절의 루트 `update.bat`은 **사용자 PC**용(HyperView TCL·`ESL_probe.bat`·`ESL_extract.bat`)이다.
> 서버(백엔드·워커·DB·화면) 설치·업데이트는 §6 `deploy\`(`deploy\setup.ps1`·`deploy\update-repo.ps1`·`deploy\install.bat`·`deploy\update.bat`)이며 서로 무관하다.

1. 저장소 클론 폴더(예: `Documents\GitHub\esl-platform`)의 **`update.bat` 더블클릭**.
   git 최신화(작업 트리 변경이 있으면 중단, fast-forward만) → TCL 배포 → 실행 래퍼 생성 → 점검표 출력.
   다시 실행하면 같은 방식으로 업데이트된다. 로그: `%LOCALAPPDATA%\esl\logs\update_<시각>.log`.
2. 처음 실행 시 설정 파일 `%LOCALAPPDATA%\esl\esl_deploy.json`이 `config/esl_deploy.example.json` 값으로 만들어진다.
   `hw_exe`(HyperWorks hw.exe), `work_root`(출력 폴더, **공유 SPDM 폴더 금지**, 기본 `%USERPROFILE%\esl_work`),
   `protected_roots`(쓰기 금지 폴더 목록, 예 `["F:/Hyper_work"]`), `default_part`, `branch`(빈 값 = 현재 브랜치)를
   확인·수정하고 `update.bat`을 다시 실행한다. 점검표의 FAIL이 없어야 한다.
3. 화면에 안내된 폴더(`%LOCALAPPDATA%\esl\app\current`)에서 h3d 파일을
   - `ESL_probe.bat` 위로 끌어다 놓기 → `<work_root>\<h3d 이름>\probe\probe.json`
   - `ESL_extract.bat` 위로 끌어다 놓기 → `<work_root>\<h3d 이름>\csv\` (파트 = `default_part`;
     다른 파트는 명령창에서 `ESL_extract.bat <h3d> <파트 이름|ID>`)
   여러 파일을 한 번에 놓아도 된다. 끝나면 `ok`·`failed_step`·`error` 요약을 보여 주고 출력 폴더를 연다.
   h3d가 있는 폴더·`protected_roots` 아래로는 출력하지 않으며(거부), 경로에 `%`·`!`·`&`가 있으면 거부한다.
   h3d는 **원본 위치의 파일을 그대로** 끌어다 놓는다(읽기 전용으로 사용). 배포 폴더(`%LOCALAPPDATA%\esl\app` 아래) 안의
   h3d는 거부한다. hw 콘솔 출력은 출력 폴더의 `probe_console.log` / `extract_console.log`.
4. 배포 구조(`deploy_dir`, 기본 `%LOCALAPPDATA%\esl\app`) — **폴더 이름 바꾸기(rename)를 하지 않으므로** `current` 폴더를
   탐색기로 열어 둔 채, 명령창이 그 폴더에 있는 채, ESL 실행 중에도 `update.bat`을 돌려도 된다.
   - `versions\<git 해시>\`: TCL·`esl_run.ps1`·README·`VERSION.txt`. 버전마다 새 폴더(같은 해시에 내용이 다르면 `<해시>-2`).
   - `current_version.txt`: 활성 버전 이름. 임시 파일을 쓴 뒤 파일 단위로 교체(잠겨 있으면 3회 재시도, 실패 시 이전 버전 유지).
   - `current\`: 고정 실행 폴더. 런처 `ESL_probe.bat`, `ESL_extract.bat`, `esl_launch.ps1`만 둔다. 런처는 실행할 때마다
     `current_version.txt`를 읽어 해당 `versions` 폴더의 실행기·TCL을 쓴다. 이미 시작한 작업은 자기 버전 폴더를 계속 쓴다.
     런처는 내용이 바뀐 경우에만 덮어쓰며, 잠겨 있으면 경고만 한다(런처는 버전과 무관).
   - 이전 구조(`current`에 TCL·`esl_run.ps1`이 직접 있던 설치)는 첫 업데이트 때 그 배포 산출물만 파일 단위로 정리한다
     (못 지우면 경고만, 동작에는 영향 없음). 예전 `<해시>`·`current.old.*` 폴더도 정리한다.
   - 오래된 `versions`는 최근 5개 + 활성 버전만 남긴다. 잠겨 있으면 건너뛰고 다음 업데이트에서 다시 시도한다.
   - 배포 산출물(`*.tcl`, `*.bat`, `*.ps1`, README, `VERSION.txt`) 이외의 파일(복사해 둔 h3d 등)과 하위 폴더는 지우거나 옮기지
     않는다. 그런 파일이 있는 폴더는 정리하지 않고 목록만 경고한다.

### 2.2 수동 실행

```bat
set HW="C:\Program Files\Altair\2026.1\hwdesktop\hw\bin\win64\hw.exe"
rem (1) 결과 이름 확인 → probe.json (기본 이름 Max_Strain/Plastic Strain/Mid 와 다를 때만 request.txt 작성)
%HW% -clientconfig hwpost.dat -b -tcl resources\tcl\esl_h3d_probe.tcl   -input D:\run\drop.h3d -output D:\run\probe
rem (2) 3패스 CSV 추출 → D:\run\esl_csv
rem     (frames, model, final, history, strain_frames, disp .csv + done.json; 진행률은 콘솔)
%HW% -clientconfig hwpost.dat -b -tcl resources\tcl\esl_h3d_extract.tcl -input D:\run\drop.h3d -part chassis_rear -output D:\run\esl_csv [-hot_k 200] [-top_n 5]
```

h3d 의 `Max_Strain`·`Plastic Strain` 은 요소별 누적 최대(max-hold)라서 t* = 최종값에 처음 도달한 프레임(first-reach).
TCL 은 마지막 프레임 전 요소(A) → 상위 요소 H 전 프레임 이력(B) → 후보 프레임 D 만 전 노드 변위·전 요소 변형률(C)을
뽑는다(22만 요소·D ≤ 10 에서 CSV 약 0.55 GB). 패스 C 는 D 의 각 f 에 대해 직전 프레임 f−1 의 전 요소 변형률도
`strain_frames.csv` 에 함께 쓴다(전 요소 "상승 중" 마스크용, `done.json` `prev_frames`; strain_frames.csv 가 최대 2배).
예전 TCL 출력(직전 프레임 없음)도 읽히지만 재현 정확도 비교는 H 요소만 가능(경고) — TCL 을 다시 실행할 것. `_0000.rad`(+ include)와 CSV 폴더를 계산 환경으로 옮긴다.

## 3. 설정

`config/esl.example.yaml` 을 `config/esl.yaml`(git 제외)로 복사해 고친다. `--config` 가 없으면 env
`ESL_CONFIG` 경로를 쓴다. 모든 키 필수(코드에 기본값 없음): 대상 파트 title, t* 탐색, 3-2-1 후보,
솔버, 판정 기준, ID 오프셋·서식, 단위 라벨. 잘못되면 `CONFIG_INVALID: <키>: <이유>`.

- `case.include_path_map`: rad 안 Windows 절대경로 include 를 로컬 경로로 치환(`{"D:/proj/cae": "/data/cae"}`).
- `tstar.metric`: `max_strain`(기본, Max_Strain 텐서의 ε_eq) | `plastic_strain`. 두 지표의 t*·후보·hotspot 은 항상
  `tstar.json` 에 함께 기록. `tstar.reach_rtol`(기본 1e-6) = first-reach 허용오차. hotspot = t* 에서 값이 상승 중인 H 요소.
  Python 이 history 로 TCL 의 후보 프레임 D 를 재계산해 다르면 경고(`tcl_check`).
- `extract.layers: [mid]`: 검증 ε_eq 층(h3d 는 Mid 만 → 솔버도 막 z=0 변형률). `extract.shear_convention: auto`:
  h3d XY 가 텐서/공학 전단인지 HyperView vonMises 와 비교해 판정(최대 불일치 > 5% 경고). `extract.hot_k`: TCL 값과 다르면 경고.
- `solver.backend`: `auto` | `cholmod` | `pardiso` | `superlu` | `iterative`(ShellModel 에 전달).
  `validation.full_solve`: `auto`(직접법 메모리 추정 ≤ 가용 메모리 80% 면 S5 전체 solve) | `always` | `never`.
  생략하면 S5 는 u_rel + 응축 회전으로 막 변형률 hotspot 만 비교하고 `disp_rms_rel`·반력은 `skipped`(판정은 hotspot 기준).
- `extract.disp_precision`: 변위 결과의 저장 정밀도(`float32` | `float64`, H3D 는 보통 float32).
  S4 가 이 정밀도의 잡음 바닥(δ = 0.5·ulp·max|X0+u|, 고정 시드 ±δ 섭동 `validation.noise_samples` 개)을
  추정해 `esl_summary.json`·`run.json`·콘솔에 `noise.force_rel`(rms(F_noise)/rms(F_eq)),
  `noise.hotspot_strain_rel`(평가 hotspot ε_eq 상대 변화)을 남긴다. `force_rel > validation.noise_force_rel_warn`
  이면 경고, `hotspot_strain_rel > validation.noise_strain_rel_max` 이면 검증 verdict FAIL(사유 `NOISE_FLOOR`).
  강체 대변위(좌표 수천 mm)에 비해 변형이 작으면 float32 변위로는 F_eq 가 잡음에 묻힌다 → TCL 출력을
  배정밀도로 받거나 판정 결과를 참고용으로만 쓴다.
- `compare`(ESL 재현 정확도 전 요소 비교, 계약 `esl_p2_library.md` §7.2): t* 에서 상승 중인 요소
  (`v[t*] > v[t*−1]·(1+tstar.reach_rtol)`, v = Max_Strain ε_eq)의 Radioss ε_rad 와 검증 해 막 변형률 ε_esl 을 비교,
  `rel_err = (ε_esl − ε_rad)/ε_rad`. valid = 상승 중 ∧ ε_rad ≥ `min_rel`·max ε_rad. 판정:
  최대변형률 요소(상승 요소 중 ε_rad 최대)의 |오차| ≤ `max_err_pct_max`(%, 기본 10, 아니면 `FIELD_MAX_ERR`),
  valid 요소 |오차| 90 분위 ≤ `p90_err_max`(%, 기본 20, 아니면 `FIELD_P90_ERR`). `full_solve: never` 에서도
  동작(u_rel + 응축 회전). **기존 `config/esl.yaml` 에는 `compare`·`report` 절을 예시에서 복사해 추가해야 한다**(모든 키 필수).
- `report.max_points`(기본 20000): 보고서 2D 컨투어 점 수 상한(초과 시 2D 셀 격자 다운샘플), `report.top_forces`.

## 4. 실행

```bash
python -m esl run --config config/esl.yaml --rad /data/X_0000.rad --results /data/esl_csv --out /work/case01
#   [--stage extract|tstar|esl|validate|export|report|all]   기본 all, 하나만 주면 그 단계만(앞 단계 산출물로 재개)
#   [--frame N]                    t* 수동 지정(frame_index, 후보 프레임 D 안에서만 → 아니면 FRAME_NOT_CANDIDATE)
#   [--support-nodes 101,202,303]  3-2-1 후보 노드 ID(3개 이상, 대상 파트 밖 → NODE_NOT_IN_PART)
#   [--export-targets radioss_inc,fem,csv]  export 단계에서 만들 대상(기본 전부)
```

- 콘솔: 단계별 1줄 요약(t*, ΣF·평형 오차, disp_rms_rel·hotspot 오차·PASS/FAIL, 내보내기 ID 범위).
- 종료코드 0 = 성공(검증 FAIL도 계산은 성공), 1 = 오류. 오류는 stderr 에 `CODE: message` 한 줄 + `run.json`.
- 입력 폴더에는 쓰지 않는다. `--out` 이 rad 폴더·rad 가 실제로 읽은 include 파일의 폴더·결과 CSV 폴더와
  겹치면(안이거나 포함) `INPUT_INVALID`. 판정은 심볼릭 링크를 푼 실제 경로(realpath) 기준이며, 모든 쓰기
  (백업 이동 포함) 직전에 대상 실제 경로가 출력 폴더 안인지 다시 확인한다(출력 안 링크가 밖을 가리켜도 거부).
- inc·fem 은 ASCII 전용(비 ASCII 문자는 `\uXXXX` 로 치환). ID 가 I10 칸을 넘으면 `ID_RANGE_COLLISION`.
- 다시 실행하면 그 단계 폴더의 기존 파일은 `_backup/<UTC 시각>/` 으로 **이동**한다(삭제 없음).
- `report` 단계(export 뒤): 있는 산출물로 `07_report/report.html` 을 만든다(없는 절은 "자료 없음").
  `--stage all` 에서 보고서가 실패해도 앞 단계 결과·종료코드 0 은 유지되고 `run.json` `stages.report` 가 `failed`.

## 5. 출력 폴더

| 폴더 | 내용 |
|---|---|
| `01_extract/` | `model.npz`, `model_meta.json`, `final.npz`, `history.npz`, `strain_frames.npz`(D 프레임 + `prev_frame_index`·`prev_vm_hv`·`prev_eps`·`prev_epsp`·`prev_available`: 각 f 의 직전 프레임, f=0 이면 −1·0), `disp.npz`(D 프레임만), `frames.json`(D, 직전 프레임, 전단 규약 판정) |
| `02_tstar/` | `tstar.json`(지표 2개의 first-reach t*·후보·hotspot·TCL 일치 확인, 선택 t*), `history.csv`(m(f) 지표별), `hotspots.csv`, `candidates.csv`(지표별) |
| `03_bc/` | `support.json`(3-2-1 노드 ID·dof, PCA 평면) |
| `04_esl/` | `u_rel.npz/csv`(강체 제거 변위), `f_eq.npz/csv`(전 노드 F_eq), `esl_summary.json`(평형·Kabsch) |
| `05_val/` | `validation.json`·`validation.csv`(지표·판정·기준값 스냅샷, 비교 제외 hotspot 과 이유, full_solve 판단, `field` = 전 요소 비교 요약: 최대변형률 비교·\|오차\| 분위수·≤5/10/20% 비율·상위 N·히스토그램), `compare_field.npz`(요소별 `elem_id`, `centroid2d`(PCA 평면 ξ,η 실좌표)·`centroid3d`, `eps_rad`, `eps_esl`, `rel_err`, `valid`, `rising`, `reason` i1(0 OK·1 HOLD·2 LOW·3 EXCLUDED·4 NO_PREV), 면외 `n0`·`w_rel`·`w_val`, 단면선 `sec_xi_*`·`sec_eta_*`, PCA 평면), `compare.csv`(전체 solve 때만) |
| `06_export/` | `esl_cload.inc`, `esl_bcs.inc`, `esl_force.fem`, `f_eq.csv`, `u_rel.csv`, `reactions_321.csv`, `tstar_candidates.csv`, `hotspots.csv`, `validation.csv` |
| `07_report/` | `report.html`: 자체 완결 Case 보고서(외부 의존 0, inline SVG·JSON·소량 JS, 라이트/다크) — 입력 요약, t* 곡선(두 지표), 지지점, F_eq 상위, 검증, 전 요소 재현 정확도, 겹쳐보기(Radioss ε/ESL ε/오차 % + 불투명도 슬라이더), 단면선 겹치기(배율 슬라이더), 상위 N 표, 히스토그램, 의미 주석 |
| `run.json` | 입력 경로·sha256, 설정 스냅샷, 단계별 요약·경고·소요시간, 실행 이력·오류 |
| `runs/<esl_run_id>/` | (플랫폼) ESL 실행별 `03_bc`·`04_esl` 복사본. 검증·내보내기 직전 04_esl 의 `tag`(ESL 작업 id)가 대상 실행과 다르면 여기서 되돌림 |

- export 대상: `radioss_inc` = `esl_cload.inc`·`esl_bcs.inc`, `fem` = `esl_force.fem`, `csv` = 나머지 csv.
  `validation.json` 의 `esl_ref` 가 현재 `esl_summary.json`(tag 또는 생성 시각)과 다르면 검증 결과를 쓰지 않는다.

생성 ID(/FUNCT, /GRNOD, /CLOAD, /BCS, PSHELL, SID)는 모두 `[id_offset, id_offset+999999]`.
rad 기존 최대 ID와 겹치면 `ID_RANGE_COLLISION`.

## 6. 서버 배포 (Windows Server — 대시보드·physicsai-platform과 같은 PC)

**처음 설치는 [docs/manual/install-quickstart.md](docs/manual/install-quickstart.md)(단계별 가이드), 이후 업데이트는 `deploy\update-repo.ps1`.**

ESL 플랫폼(백엔드 API·워커·PostgreSQL DB·웹 화면 `/esl/`)을 대시보드(simulation_workbench)·physicsai-platform과 **같은 서버·같은 실행 환경**
(Python 3.12.13, PostgreSQL 18 같은 인스턴스에 별도 DB `esl`·역할 `esl_app`, Node 22.23.2, 대시보드 주소의 하위 경로 `/esl/`, Windows 작업 스케줄러)에 설치한다.
physicsai의 `deploy\`와 같은 절차·옵션·메시지다. 자세한 내용: [관리자 매뉴얼](docs/manual/admin.md), 현장 확인: [E2E 체크리스트](docs/e2e-checklist.md).

| 용도 | 실행(일반 PowerShell, 관리자 권한 불필요) |
|---|---|
| 서버 설치 — git 폴더(권장, 인터넷·사내 프록시) | `<git>\deploy\setup.ps1 -DashboardRoot <대시보드>` |
| 서버 업데이트 — git 폴더(git pull 포함, 질문 없음) | `<git>\deploy\update-repo.ps1` |
| (공통) 실행 정책 오류(스크립트를 실행할 수 없습니다)가 나면 | `powershell -NoProfile -ExecutionPolicy Bypass -File …`로 실행(예: `powershell -NoProfile -ExecutionPolicy Bypass -File <git>\deploy\update-repo.ps1`) |
| 폐쇄망 묶음 만들기(준비 PC) | `deploy\collect-offline.ps1` 또는 `bash deploy/collect-offline.sh` → `dist/esl-offline-<ver>.zip` |
| 폐쇄망 설치 / 업데이트(묶음의 deploy 폴더, `deploy.json`) | `deploy\install.bat`(= `deploy\install.ps1`) / `deploy\update.bat`(= `deploy\update.ps1`) |
| 작업 등록 해제 | `deploy\uninstall-tasks.ps1` |
| 시연(Altair·대시보드 없이 합성 Case, 포트 8191) | `deploy\demo\start-demo.bat` / `stop-demo.bat` |
| 환경 점검(경로 쓰기·DB·migration·솔버 백엔드·pypardiso·설정 검증 표) | `<런타임>\venv\Scripts\python.exe <런타임>\app\esl_service.py check --runtime <런타임>` (개발: `python -m esl_platform.check`) |
| **사용자 PC** TCL 배포(서버와 무관) | 저장소 루트 `update.bat`(§2.1) |

- 런타임(git 폴더 설치 `<git>\.runtime`, 묶음 `install_root`): `venv`, `app`(코드 스냅샷 — 서비스는 git 폴더가 아니라 이 복사본을 실행), `frontend`, `config\esl_platform.yaml`
  (+ `esl.yaml`·`library.yaml`·`ista6.yaml`, 예시 `config/esl_platform.prod.example.yaml`), `secrets\database_url`(현재 사용자·SYSTEM만 읽기), `logs`, `state`, `_backup`.
- 작업 스케줄러 `ESL-Backend`·`ESL-Worker` = `venv\Scripts\python.exe <런타임>\app\esl_service.py backend|worker --runtime <런타임>`(실행기가 설정·DB 파일을
  자기 프로세스 환경에만 넣음 — 비밀값은 인자·로그에 없음). 실행 시간 제한 없음, `Interactive`(기본)·`Background`.
- 비밀번호(PostgreSQL 관리자·앱 역할·Background 실행 계정)는 화면 입력(`Read-Host -AsSecureString`) 또는 `-PasswordsFromEnv`
  (`ESL_INSTALL_PG_ADMIN_PASSWORD`·`ESL_INSTALL_DB_PASSWORD`·`ESL_INSTALL_SERVICE_PASSWORD`)로만 받는다.
- 솔버 의존성은 `deploy/requirements.lock`(physicsai와 겹치는 패키지는 같은 버전)에 pypardiso + MKL Windows 휠·pyamg·psutil 포함, scikit-sparse는 Windows 제외.
- 접속(기본 — physicsai와 같음): **대시보드 Vite 프록시 + 백엔드 정적 서빙**. 대시보드 `.env`의 `VITE_ESL_TARGET=http://127.0.0.1:8110`이면
  대시보드 Vite가 `/esl` 전체를 경로 그대로 ESL 백엔드로 넘기고, 백엔드가 `/esl/api/*`는 API로, 그 밖은 설정 `server.frontend_root`(git 폴더 설치
  `<git>\.runtime\frontend`)의 화면으로 응답한다. `SIMDASH_ESL_ENABLED=true`이면 대시보드 사이드바에 ESL 버튼. git 폴더 설치(`setup.ps1`·`update-repo.ps1`)는
  두 줄을 대시보드 `.env`에 **없을 때만** 추가하고(기존 값 보존, 바꾸기 전 `.runtime\_backup\<UTC>\dashboard.env`) "대시보드를 다시 시작하세요"를 안내한다.
  접속 `http://<대시보드 주소>/esl/`, 이 PC health `http://127.0.0.1:8110/esl/api/health`(관리자 매뉴얼 §2.6.1).
- 대안: 대시보드 앞에 Caddy를 쓰는 설치(폐쇄망 묶음 설치의 기준)는 Caddyfile catch-all 앞에 `deploy/caddy/esl.caddy`(`/esl/api/*` → `127.0.0.1:8110`,
  `/esl/*` → 프런트 빌드), Caddy 환경변수 `ESL_PORT`·`ESL_FRONTEND_ROOT`(§2.6.2).

### 6.1 대시보드 쪽 지원(이 저장소 밖)

대시보드 코드는 이 저장소에서 바꾸지 않는다. 대시보드 쪽이 physicsai(`VITE_PHYSICSAI_TARGET`·`SIMDASH_PHYSICSAI_ENABLED`)와 같은 방식으로
`VITE_ESL_TARGET`(`/esl` 경로 그대로 프록시)·`SIMDASH_ESL_ENABLED`(사이드바 ESL 버튼)를 지원하는 버전이어야 한다.
