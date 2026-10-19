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

### 2.1 Windows 설치·업데이트 (권장)

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
   h3d는 **원본 위치의 파일을 그대로** 끌어다 놓는다(읽기 전용으로 사용). 배포 폴더(`...\app\current`) 안의 h3d는
   거부한다 — update 때 지워질 수 있다. `update.bat`은 교체·정리할 배포 폴더에 배포 산출물 이외 파일이 있으면 중단한다.
   hw 콘솔 출력은 출력 폴더의 `probe_console.log` / `extract_console.log`.

### 2.2 수동 실행

```bat
set HW="C:\Program Files\Altair\2026.1\hwdesktop\hw\bin\win64\hw.exe"
rem (1) 결과 이름 확인 → probe.json 을 보고 request.txt 작성
%HW% -clientconfig hwpost.dat -b -tcl resources\tcl\esl_h3d_probe.tcl   -input D:\run\drop.h3d -config D:\run\request.txt -output D:\run\probe
rem (2) CSV 추출 → D:\run\esl_csv (frames.csv, model.csv, strain.csv, disp.csv, done.json)
%HW% -clientconfig hwpost.dat -b -tcl resources\tcl\esl_h3d_extract.tcl -input D:\run\drop.h3d -config D:\run\request.txt -output D:\run\esl_csv
```

`_0000.rad`(+ include)와 CSV 폴더를 계산 환경으로 옮긴다.

## 3. 설정

`config/esl.example.yaml` 을 `config/esl.yaml`(git 제외)로 복사해 고친다. `--config` 가 없으면 env
`ESL_CONFIG` 경로를 쓴다. 모든 키 필수(코드에 기본값 없음): 대상 파트 title, t* 탐색, 3-2-1 후보,
솔버, 판정 기준, ID 오프셋·서식, 단위 라벨. 잘못되면 `CONFIG_INVALID: <키>: <이유>`.

- `case.include_path_map`: rad 안 Windows 절대경로 include 를 로컬 경로로 치환(`{"D:/proj/cae": "/data/cae"}`).
- `extract.disp_precision`: 변위 결과의 저장 정밀도(`float32` | `float64`, H3D 는 보통 float32).
  S4 가 이 정밀도의 잡음 바닥(δ = 0.5·ulp·max|X0+u|, 고정 시드 ±δ 섭동 `validation.noise_samples` 개)을
  추정해 `esl_summary.json`·`run.json`·콘솔에 `noise.force_rel`(rms(F_noise)/rms(F_eq)),
  `noise.hotspot_strain_rel`(평가 hotspot ε_eq 상대 변화)을 남긴다. `force_rel > validation.noise_force_rel_warn`
  이면 경고, `hotspot_strain_rel > validation.noise_strain_rel_max` 이면 검증 verdict FAIL(사유 `NOISE_FLOOR`).
  강체 대변위(좌표 수천 mm)에 비해 변형이 작으면 float32 변위로는 F_eq 가 잡음에 묻힌다 → TCL 출력을
  배정밀도로 받거나 판정 결과를 참고용으로만 쓴다.

## 4. 실행

```bash
python -m esl run --config config/esl.yaml --rad /data/X_0000.rad --results /data/esl_csv --out /work/case01
#   [--stage extract|tstar|esl|validate|export|all]   기본 all, 하나만 주면 그 단계만(앞 단계 산출물로 재개)
#   [--frame N]                    t* 수동 지정(frame_index, 후보 목록 안에서만 → 아니면 FRAME_NOT_CANDIDATE)
#   [--support-nodes 101,202,303]  3-2-1 후보 노드 ID(3개 이상, 대상 파트 밖 → NODE_NOT_IN_PART)
```

- 콘솔: 단계별 1줄 요약(t*, ΣF·평형 오차, disp_rms_rel·hotspot 오차·PASS/FAIL, 내보내기 ID 범위).
- 종료코드 0 = 성공(검증 FAIL도 계산은 성공), 1 = 오류. 오류는 stderr 에 `CODE: message` 한 줄 + `run.json`.
- 입력 폴더에는 쓰지 않는다. `--out` 이 rad 폴더·rad 가 실제로 읽은 include 파일의 폴더·결과 CSV 폴더와
  겹치면(안이거나 포함) `INPUT_INVALID`. 판정은 심볼릭 링크를 푼 실제 경로(realpath) 기준이며, 모든 쓰기
  (백업 이동 포함) 직전에 대상 실제 경로가 출력 폴더 안인지 다시 확인한다(출력 안 링크가 밖을 가리켜도 거부).
- inc·fem 은 ASCII 전용(비 ASCII 문자는 `\uXXXX` 로 치환). ID 가 I10 칸을 넘으면 `ID_RANGE_COLLISION`.
- 다시 실행하면 그 단계 폴더의 기존 파일은 `_backup/<UTC 시각>/` 으로 **이동**한다(삭제 없음).

## 5. 출력 폴더

| 폴더 | 내용 |
|---|---|
| `01_extract/` | `model.npz`, `model_meta.json`, `strain_tensor.npz`, `disp.npz`, `frames.json` |
| `02_tstar/` | `tstar.json`(자동·선택 t*, 후보, hotspot), `history.csv`, `hotspots.csv`, `candidates.csv` |
| `03_bc/` | `support.json`(3-2-1 노드 ID·dof, PCA 평면) |
| `04_esl/` | `u_rel.npz/csv`(강체 제거 변위), `f_eq.npz/csv`(전 노드 F_eq), `esl_summary.json`(평형·Kabsch) |
| `05_val/` | `validation.json`·`validation.csv`(지표·판정·기준값 스냅샷), `compare.csv` |
| `06_export/` | `esl_cload.inc`, `esl_bcs.inc`, `esl_force.fem`, `f_eq.csv`, `u_rel.csv`, `reactions_321.csv`, `tstar_candidates.csv`, `hotspots.csv`, `validation.csv` |
| `run.json` | 입력 경로·sha256, 설정 스냅샷, 단계별 요약·경고·소요시간, 실행 이력·오류 |

생성 ID(/FUNCT, /GRNOD, /CLOAD, /BCS, PSHELL, SID)는 모두 `[id_offset, id_offset+999999]`.
rad 기존 최대 ID와 겹치면 `ID_RANGE_COLLISION`.
