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

```bat
set HW="C:\Program Files\Altair\2024\hwdesktop\hw\bin\win64\hw.exe"
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

## 4. 실행

```bash
python -m esl run --config config/esl.yaml --rad /data/X_0000.rad --results /data/esl_csv --out /work/case01
#   [--stage extract|tstar|esl|validate|export|all]   기본 all, 하나만 주면 그 단계만(앞 단계 산출물로 재개)
#   [--frame N]                    t* 수동 지정(frame_index, 후보 목록 안에서만 → 아니면 FRAME_NOT_CANDIDATE)
#   [--support-nodes 101,202,303]  3-2-1 후보 노드 ID(3개 이상, 대상 파트 밖 → NODE_NOT_IN_PART)
```

- 콘솔: 단계별 1줄 요약(t*, ΣF·평형 오차, disp_rms_rel·hotspot 오차·PASS/FAIL, 내보내기 ID 범위).
- 종료코드 0 = 성공(검증 FAIL도 계산은 성공), 1 = 오류. 오류는 stderr 에 `CODE: message` 한 줄 + `run.json`.
- 입력 폴더에는 쓰지 않는다(`--out` 이 입력 폴더와 겹치면 `INPUT_INVALID`).
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
