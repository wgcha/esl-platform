# 계약: ESL 플랫폼 P1b (API·DB·워커·UI)

- 상태: 확정 (2026-10-19). 원본은 `esl.md` §2~§5·§9. 이 문서는 P1a 코어(`esl_core.md`, 특히 §7) 반영 **차이만** 적는다. 충돌 시 이 문서 우선.
- 운영 가정: physicsai-platform과 같은 사내 Windows 서버, Python 3.12, PostgreSQL, 대시보드 세션 introspection, 하위 경로 `/esl/`. 저장소 구조·패턴은 `/home/user/wgcha/physicsai-platform`(backend/, worker/, frontend/, migrations/, scripts/test-all) 참조(복사 금지, 규약만).
- 계산은 전부 `esl` 패키지(Python) 호출. **서버에서 외부 프로그램 실행 없음**(hw·OptiStruct 없음) → `esl.md`의 `altair`·`resources`·`commands` 설정, LOCAL step, argv 템플릿, V-CMD-1 삭제.

## 1. 입력·Case
- Case 입력 = `rad_path`(Radioss `_0000.rad`, include 포함) + `results_dir`(Windows TCL `esl_h3d_extract.tcl` 출력 CSV 폴더). h3d 경로는 받지 않음(표시용 `h3d_path`는 results_dir/done.json에서 읽어 기록).
- 둘 다 `storage.input_roots` 아래만 허용(읽기 전용), `esl_root`와 겹치면 거부. 업로드 엔드포인트 없음(유지).
- `POST /paths/inspect` purpose: `RAD` | `RESULTS`. RESULTS 응답: `{ok, problems[], done:{ok, part_id, part_spec, candidate_frames, hot_k, warnings}, n_frames, files:[...]}`.
- `part_title`은 Case별 값(기본 설정값). results_dir의 done.json `part_id`와 rad 파트 id 불일치 → 422 `PART_MISMATCH`.
- Case 산출물 폴더 = `<esl_root>/<case_folder>/` = 코어 파이프라인 `--out`. 폴더 스키마는 코어(`01_extract`~`06_export`, `run.json`)를 그대로 쓴다.

## 2. 작업 유형 (전부 INTERNAL, 워커가 코어 함수 호출)
| job_type | 코어 단계 | lane | 사전조건 |
|---|---|---|---|
| `CASE_EXTRACT` | extract + tstar(자동 t*) | SLOT | 입력 fingerprint |
| `ESL_SOLVE` | esl | SLOT | `cases.tstar`, `current_support_set_id` |
| `VALIDATE` | validate | SLOT | READY·비stale esl_run |
| `EXPORT` | export | LIGHT | READY esl_run |
- SLOT은 동시 1개(메모리: 22만 요소 솔버). 워커는 코어 호출을 **별도 프로세스**(multiprocessing spawn)로 실행해 취소 시 종료 가능하게 하고, 코어 콘솔 출력을 step 로그로 저장.
- 호출 인터페이스: `esl.pipeline.run(config_path_or_dict, rad, results, out, stage=..., frame=..., support_nodes=...)`(현 CLI와 같은 의미). 플랫폼은 코어 내부 모듈을 직접 부르지 않는다. 예외(동기 API용): `esl.config.load_config/validate_settings`, `esl.rad.list_parts/scan_includes`, `esl.mech.supports.pca_corners/pick_321`, `esl.mech.shell.available_backends/resolve_backend`(/status) — `worker/esl_worker/core_adapter.py` 한 곳에서만 import. 코어 설정은 플랫폼 설정 `core:` 블록(= `config/esl.example.yaml` 내용)을 Case 작업 시점에 스냅샷.
- 작업 결과 등록: 코어 `run.json`·각 단계 json을 읽어 DB 요약 컬럼(§3) 채움. 대용량 배열은 DB에 넣지 않음.

## 3. 데이터 모델 차이 (`esl.md` §3 기준)
- `cases`: `h3d_path` → `results_dir`, `input_fingerprint` = `{rad:{size,mtime,sha256}, includes:[...], results:{done_json_sha256, files:{name:{size,mtime}}}}`. `tstar` JSONB = `{metric, frame_index, time, elem_id, value, source:"auto"|"user"}`. `current_bc_set_id` → `current_support_set_id`.
- `bc_sets` → `support_sets`: `{id, case_id, node_ids:[3], dofs:["123","ij","k"], source:"auto"|"user", plane JSONB, created_by/at}` 불변.
- `esl_runs.kabsch` = `{rot_deg, rms_def, max_def}`, `forces` = `{n_nodes_loaded, sum_f:[3], sum_m:[3], equilibrium_rel, max_f:{node_id,mag}, noise:{force_rel, hotspot_strain_rel}}`.
- `validations` = `{disp_rms_rel, reaction_rel, hotspots:[{elem_id, eps_rad, eps_val, rel_err}], excluded:[{elem_id, reason}], verdict, fail_reasons[], criteria}`.
- 최신성: tstar·support_set·part_title 변경 → 이후 단계 stale(`esl.md` 규칙 유지).

## 4. API 차이 (`esl.md` §5 기준)
- `GET /cases/{id}/tstar` → `{selected, metrics:{max_strain:{tstar, candidates[], history:{time[], value[]}}, plastic_strain:{...}}, hotspots:[{rank, elem_id, value, centroid, rising}]}`.
- `PUT /cases/{id}/tstar` `{version, metric, frame_index}` — frame은 해당 metric 후보 안에서만(422 `FRAME_NOT_CANDIDATE`).
- `POST /cases/{id}/support-sets/suggest` `{}` → `{node_ids:[3], dofs:[...], coords, plane, corners:[4]}`(저장 안 함). `POST /cases/{id}/support-sets` `{node_ids:[3]}` → dofs 자동(pick_321), 422 `NODE_NOT_IN_PART`|`SUPPORT_DEGENERATE`. `GET /cases/{id}/support-sets`.
- `GET /cases/{id}/preview?frame_index=` 유지(값 = |u_rel| 또는 |u|, 3-2-1 노드 표시).
- `GET /esl-runs/{id}/forces?top=50` 행에 `is_support`. 나머지는 `esl.md` 그대로.
- `GET /status`의 tools → `{solver_backend, solver_backends_available[]}`.

## 5. UI (React+Vite+TS, `esl.md` §9 레이아웃·원칙 유지: 단계당 주 버튼 1개, 고급 접힘)
| 단계 | 필수 입력·표시 | 주 버튼 |
|---|---|---|
| ① 입력 | rad 경로·결과 폴더 경로(확인→inspect 요약: 파트, done.json 상태·후보 프레임), 파트 title | 추출 실행 |
| ② t* | 지표 토글(Max_Strain/Plastic), max-hold 곡선(t* 표시), 후보 표(라디오), hotspot 표(상승 중 여부) | t* 확정 |
| ③ 지지점 | PCA 평면 2D 산점, 3-2-1 노드 3개 입력칸(자동값), dof 표시 | 지지점 저장 |
| ④ ESL | t*·지지점 요약, 강체 회전각, ΣF·ΣM·평형 오차, 잡음 지표, F_eq 상위 표 | ESL 계산 |
| ⑤ 검증 | 변위 RMS·반력·hotspot 오차 표(제외 요소와 사유), PASS/FAIL + fail_reasons | 검증 실행 |
| ⑥ 내보내기 | 대상 체크(inc·fem·csv), 결과 폴더 경로(복사), 파일 목록·다운로드(06_export 우선 표시, 기타 단계 산출물은 별도 묶음; API `/cases/{id}/artifacts`는 Case 폴더 전체를 반환), 크기 초과 시 경로 복사 | 내보내기 |

## 6. 검증 (Verifier)
- `esl.md` §10의 V-CFG·V-SEC·V-AUTH·V-DB·V-SM·V-LS·V-STALE·V-UI 유지(외부 실행 관련 V-CMD 삭제). 추가:
  - V-P1B-1: 합성 Case(코어 합성 E2E 데이터)로 API만 써서 ①~⑥ 완주, DB 요약 = 코어 json 값.
  - V-P1B-2: 작업 취소 시 코어 프로세스 종료, 출력 폴더 일관(부분 산출물은 다음 실행 때 `_backup/`).
  - V-P1B-3: input_roots 밖·esl_root 겹침·심링크 경로 거부(코어 보호와 이중).
- 완료 = `scripts/test-all`(Linux, PG 있음) 통과.
