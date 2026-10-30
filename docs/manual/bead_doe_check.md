# 강성 평가 스터디(비드 형상, 이전 이름: 비드 DOE) — 실기 체크리스트 (v0.9.0)

계약 `docs/contracts/esl_bead_doe.md` §16 V-BD-R1. 클라우드 시험은 가짜 paicad(`tests/fake_paicad.py`)·합성 SM1 으로만 돌았으므로,
**Windows 운영 서버에서 처음 돌릴 때** 이 순서로 확인한다. 순서: **0 설치 확인 → R-③ STEP 만 → R-② 다른 모델 + B 메시 → R-① 같은 모델(실제 Ch/R 약 22만 요소)**
(가볍고 외부 요인이 적은 것부터 — 계약 §17 "실기(③ → ② → ①)").
결과(통과/실패·시간·메모)는 각 표 오른쪽 칸에 적고, 고친 값은 `config/esl_platform.yaml` 에만 반영한다(코드·하드코딩 수정 없음).
아래 `<런타임>` = 설치 폴더(git 폴더 설치는 `<git>\.runtime`), `<deploy>` = `<git>\deploy` 또는 묶음을 푼 폴더의 `deploy`.

## 0. 설치·형상 엔진 확인 (먼저)

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 0-1 | 설치 콘솔 | 설치·업데이트 끝 부분에 `강성 평가 스터디 형상 엔진: paicad 0.14.0 (OCP 7.8.…), gmsh 4.15.2 — …\paicad.exe (wheel: vendored)` 한 줄(v0.10.1 — `vendored` = 저장소 동봉 `deploy\wheels` 를 씀, physicsai 저장소·`paicad_wheels` 불필요. 그 앞 줄 `paicad 0.14.0 wheel: 저장소 동봉 …`). `강성 평가 스터디 비활성(다른 기능은 그대로): …` 경고면 사유를 적고 관리자 매뉴얼 §2.7.1 | |
| 0-2 | paicad 버전 | `& '<런타임>\venv\Scripts\paicad.exe' version --json` → `"paicad": "0.14.0"`(≥ 0.14.0), `"ocp"` 가 **null 이 아님**, python 3.12.x | |
| 0-3 | gmsh | `& '<런타임>\venv\Scripts\python.exe' -c "import gmsh; print(gmsh.__version__)"` → `4.15.2`. 실패하면 ③ 과 STEP 내보내기만 비활성(`GMSH_UNAVAILABLE`) | |
| 0-4 | 종합 점검 | `& '<런타임>\venv\Scripts\python.exe' '<deploy>\paicad_wheel.py' check --lock '<deploy>\paicad.lock' --exe '<런타임>\venv\Scripts\paicad.exe' --wheel '<deploy>\wheels\paicad-0.14.0-py3-none-any.whl'` → `"ok": true`, `problems: []`, `"wheel": {"ok": true, "sha256": …}`(= `deploy\paicad.lock` 의 sha256), `warnings` 에 `GMSH_UNAVAILABLE` 없음 | |
| 0-5 | 설정 자동 감지 | 설치 콘솔 `강성 평가 스터디 자동 설정: bead_doe.enabled = true, bead_doe.paicad.exe = "…/venv/Scripts/paicad.exe" 추가 (백업 …)`(처음 한 번). `config\esl_platform.yaml` 의 `bead_doe.paicad.exe` 가 실제 파일을 가리킴. 다시 업데이트해도 값이 바뀌지 않음 | |
| 0-6 | 업로드 확장자 | `upload.allowed_ext` 를 직접 적어 둔 설정이면 `.step`·`.stp` 가 한 번 보충됨(콘솔 `업로드 허용 확장자 보충: …`) | |
| 0-7 | 오프라인 묶음 | (폐쇄망 묶음일 때) 준비 PC 의 `collect-offline.ps1` 출력에 `paicad wheel: 저장소 동봉 …`(v0.10.1 — 빌드 없음)과 대조 `"ok": true`, `sha256` 이 `deploy\paicad.lock` 값과 같음. `-PhysicsaiRepo` 로 다시 빌드했다면 **Windows 준비 PC 에서 만든 sha256 이 lock 과 같은지** 기록(정규화로 같아야 함 — 다르면 묶음 중단, 보고) | |
| 0-7b | 동봉 wheel 불일치 | (선택) git 폴더에서 `deploy\wheels\paicad-0.14.0-py3-none-any.whl` 을 잠시 다른 파일로 바꾸고 `update-repo.ps1` → 콘솔 `강성 평가 스터디 비활성(다른 기능은 그대로): 실패: paicad wheel 대조 …` + `git checkout -- deploy/wheels` 안내, 업데이트 자체는 성공·다른 기능 정상. `git checkout -- deploy/wheels` 로 되돌리고 다시 실행 | |
| 0-8 | 비활성 화면 | (선택) `bead_doe.paicad.exe` 를 잠시 없는 경로로 바꾸고 워커 재시작 → 강성 평가 스터디 화면 상단 "형상 엔진(paicad)이 설치되지 않았습니다(관리자 문의)", 관리자 화면 사유 `PAICAD_NOT_FOUND`. 다른 화면(라이브러리·비드 최적화)은 정상. 값 되돌림 | |
| 0-9 | 워커 점검 | 워커 시작 후 `bead_doe.paicad.check_interval_s`(600 s) 이내 `GET /esl/api/doe/settings` → `enabled: true`, `paicad.ready: true`, `paicad.version: "0.14.0"`, `gmsh.ready: true` | |

## 0b. 클라우드에서 확인하지 못한 항목 (D3 워커·D5 배포 — Windows 실기 필수)

클라우드 시험(Linux, 가짜 paicad, 합성 메시)으로는 아래를 확인할 수 없다. 처음 설치한 Windows 서버에서 0 다음에 확인한다.

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 0b-1 | **OCP DLL 경로·env** | 워커가 paicad 를 부를 때 env 는 최소(OS 기본 키 + `worker.env_passthrough` + `bead_doe.paicad.env` + `PYTHONUTF8=1`)라, venv 밖 PATH 에 기대면 OCP(`OCP.cp312-win_amd64.pyd`)의 DLL 로드가 실패할 수 있다. 미리보기 1회가 `PAICAD_FAILED`·`PAICAD_OCP_MISSING` 없이 끝나는지, 실패면 `_doe/<id>/doe/<rev>/grid/paicad.log` 에 `DLL load failed` 가 있는지. 필요하면 `bead_doe.paicad.env`(예 `{PATH: "<런타임>\venv\Lib\site-packages\OCP;C:\Windows\System32"}`)로 설정만 보충(코드 수정 없음)하고 값을 기록. 관리자 콘솔(설치 단계 `paicad version --json`)과 워커(서비스 계정) 결과가 같은지도 | |
| 0b-2 | **22만 요소 ① 시간·메모리** | R-① 를 돌리며 단계별 시간(작업 상세: BD_INPUT · BD_GEOM fixed-scan/extract/tag · BD_GRID · BD_DESIGNS 안당 `paicad run`+해석 · BD_POST)과 워커·paicad·코어 자식의 최대 메모리(작업 관리자 '최대 작업 집합'), `run.parallel` 2 의 메모리 자동 축소 로그 유무. 타임아웃(`bead_doe.paicad.timeout_s.*`) 대비 여유가 50 % 미만이면 설정 조정 | |
| 0b-3 | **공칭(nominal) 셀 렌더** | 미리보기 격자 첫 칸 'd000 공칭' 썸네일이 실제 공칭 형상(비드 위치·깊이)으로 보이는지. `_doe/<id>/doe/<rev>/grid/cells/nominal/thumb.png` 존재·320×240, `grid_manifest.json` 의 `nominal` 셀 상태 OK. 회색('썸네일 없음')이면 grid paicad.log 의 `VIEW_*` 코드 기록 | |
| 0b-4 | **`--fixed-dir ""` 실동작(③)** | 실제 paicad 0.14.0 에서 ③ 미리보기 `shell view grid --fixed-dir ""` 가 인자 오류(종료 2 → `PAICAD_INTERNAL`) 없이 '고정 없음'으로 끝나는지(V-BD-16·R-BD-7). Windows 인자 전달에서 빈 문자열이 사라지지 않는지도 — 실패하면 작업 로그 argv 와 paicad.log 를 보고(대체안 = 베이스라인 rad 로 fixed-scan, 계약 R-BD-7) | |
| 0b-5 | **정규화 wheel sha256 Windows 일치** | Windows 준비 PC 에서 `collect-offline.ps1`(또는 `python deploy\paicad_wheel.py collect --lock deploy\paicad.lock --out-dir <폴더>`) 결과 `"ok": true`, sha256 = `deploy\paicad.lock` 값(`a23cc6dc…`). 다르면 `python deploy\paicad_wheel.py digest --wheel <wheel>` 값, setuptools 버전(lock `build_requires` 80.9.0 과 같은지), 저장소 줄 끝 설정(autocrlf)을 기록해 보고(묶음 중단) | |
| 0b-6 | **PowerShell 5.1 설치** | `install.bat`·`update.bat`(Windows PowerShell 5.1)로 설치할 때 paicad 단계(`Install-EslBeadDoe`)가 자식 stderr 오류 레코드로 중단되지 않고 끝 줄 `강성 평가 스터디 형상 엔진: …` 출력. pwsh 7 창에서 실행해도 같은 결과, 한글 경로(설치 폴더·사용자 이름)에서도 확인 | |

## R-③ — 다른 모델, STEP 만 (먼저)

준비: B 모델 Ch/R **중립면(시트) STEP**(비드 3~8개), A = 라이브러리의 ESL 3개 이상(다른 모델). 평균 요소 크기 h = 3 mm, 5 mm 두 번.

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| ③-1 | 입력 준비 | 시나리오 ③ → STEP 업로드·인치·쉘 물성(t·E·ν 기본값) → [입력 준비] 완료. 베이스라인 gmsh 메시 품질 요약(quad 비율 ≥ 0.8) | |
| ③-2 | 메시 시간 | h 3 mm·5 mm 각각 베이스라인 메시 시간·요소 수(`prep/mesh0.json` seconds·n_elems) | |
| ③-3 | 비드 인식 | 비드 표의 개수·모양(linear/circular)이 STEP 과 같음, 공칭 D/W 가 CAD 측정값과 ±0.1 mm | |
| ③-4 | 경계 경고 | 평면도에 A 체결점·하중 집중부 → B 옮김, B 구멍 표시. 거리 > 10 mm 빨강 선 수 = 경고 수 | |
| ③-5 | 미리보기 | 안 30개 LHS → 썸네일 격자, `grid` 시간, 충돌·고정 침범 안 스킵 배지 | |
| ③-6 | 실행 | [DOE 실행] → 안별 `paicad update`+gmsh+해석 시간(로그 `[dNNN] paicad … s · solve … s`), 총 시간 | |
| ③-7 | 잡음 바닥 | 결과 '메시 잡음 이내' 표시와 잡음 바닥 값(공칭 왕복 재메시 score 차) 기록 — h 3 mm 와 5 mm 비교 | |
| ③-8 | 산출물 | 최적 안 `ch_r.rad`·`ch_r.fem`·`sample.brep`·`sample.step` 을 받아 HyperMesh 에서 열림(ID 1부터, PID 1개) | |

## R-② — 다른 모델 + B 메시

준비: 다른 인치 B 모델의 STEP + B 메시(rad + include, tie·RBE2 포함), ESL 3개 이상(A 모델).

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| ②-1 | 입력 검사 | [입력 검사] 크기 차(같은 인치 ±5 %)·메시 품질. 파트 제목 `chassis rear` 일치 | |
| ②-2 | 준비 시간 | `fixed-scan`·`extract`·`tag` 시간·메모리(작업 로그 step 3), `prep/fixed` 고정 노드 수 | |
| ②-3 | 고정 노드 | B 의 tie·RBE2 노드가 모든 안에서 좌표 불변(최적 안 include 와 원 메시 비교) | |
| ②-4 | 실행·결과 | 안 30개 총 시간, 안별 `paicad run` 시간, `out_files` 크기, 순위·민감도·3D 비교 | |
| ②-5 | 입력 보호 | 업로드 폴더(`input/mesh` 원본)의 파일 목록·수정 시각이 실행 전후 같음 | |

## R-① — 같은 모델 (실제 Ch/R, 약 22만 요소)

준비: ESL 이 만들어진 Case(rad + include, Ch/R 약 22만 요소)와 같은 모델 중립면 STEP, ESL 3개 이상.

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| ①-1 | 동일 모델 | 시나리오 ① 기본 선택, 기준 Case·파트·노드/요소 수 표시. 누적 씬이면 `BD_BASE_CUMULATIVE` 정보 | |
| ①-2 | Case 폴더 크기 | Case 폴더 rad/inc 합계(`bead_doe.same.max_assem_mb` 4096 MB 이하) 기록 | |
| ①-3 | paicad 시간·메모리 | `fixed-scan`·`tag`·안별 `run` 시간과 최대 메모리(작업 관리자) — 타임아웃(`bead_doe.paicad.timeout_s.*`) 대비 여유 | |
| ①-4 | 노드 ID 불변 | 최적 안 include(`best/<id>/`)의 `/NODE` 만 바뀌고 ID·연결·PID 불변(원본과 diff) | |
| ①-5 | 총 시간 | 안 30개(`run.parallel` 2) 총 시간, 메모리 자동 축소 로그 유무 | |
| ①-6 | 썸네일 | 미리보기 격자 썸네일이 실제 비드 위치·깊이 변화를 보여 줌 | |
| ①-7 | 디스크 정리 | 끝난 뒤 `run/designs/*/paicad/out_files` 는 상위 3개 + 베이스라인만 남음(BD-D-17), `_doe/<id>/` 전체 크기 | |
| ①-8 | 입력 보호 | Case 폴더 파일 목록·수정 시각·sha 가 실행 전후 같음(paicad 출력이 `_doe/<id>/` 밖으로 안 감) | |

## 문제 해결 메모

- `PAICAD_OCP_MISSING`: `paicad version --json` 의 `ocp` 가 null — `cadquery-ocp` 설치 실패 또는 VC++ 재배포 런타임 없음. `pip show cadquery-ocp`(설치 venv) 확인.
- `PAICAD_VERSION_LOW`: venv 에 다른 paicad 가 설치됨 — 업데이트 스크립트를 다시 실행(묶음 wheels 또는 deploy.json `paicad_wheels`·`physicsai_root`).
- 고정 버전과 다른 paicad 경고: 결과·관리자 화면에 기록만(동작은 함). 실기 결과 보고에는 실제 버전을 적는다.
- 시간이 타임아웃에 가까우면 `bead_doe.paicad.timeout_s.<명령>`·`bead_doe.mesh.timeout_s` 를 늘리고 워커 재시작.
