# 계약: 목록 항목 삭제 — 강성 평가 스터디·비드 최적화·종합 분석·버전 비교 (ITEM_DELETE, v0.19.0)

- 상태: **확정** (2026-11-12). 사용자 확정 결정(아래) 반영, 결정 질문 2개(§10) 확정.
- 버전: **v0.19.0** (main d5ee4cb = v0.18.2 기준 작성). migration **필요**(§6 — `0016_deletions`, 직전 HEAD = `0015_bead_select`).
- 관계: 기존 삭제 선례는 `DELETE /opt/templates/{tid}`(`api/services/opt_templates.py` — 등록자·전역 관리자, 참조되면 보관, 아니면 행 삭제 + `_templates/_backup` 이동) 하나뿐. 이 계약은 권한 규칙(`NOT_TEMPLATE_OWNER` 와 같은 판정)과 `can_delete` 칸 모양을 따르되, 폴더는 백업이 아니라 **휴지통 → 워커 영구 삭제**로 처리한다.
- ID 규칙: 결정 `D-0.19.0-DEL-n`(decisions.md), 시험 `V-DEL-n`, 리스크 `R-DEL-n`.

### 사용자 확정 (2026-11-12, 변경 금지)
1. **범위 4종**: 강성 평가 스터디(`bead_does`, `_doe/<id>`, 자식 `verify_drops` 의 `_verify/<vid>`, `scx_submissions`), 비드 최적화(`opt_runs`, `_opt/<id>`), 종합 분석(`analysis_runs`, `_analysis/<id>`), 버전 비교(`comparisons`, `_compare/<id>`).
2. **종합 분석 삭제 시** 그 분석을 참조하는 `opt_runs.analysis_id` 는 **SET NULL**(참조만 끊고 최적화는 유지). 차단·연쇄 삭제 안은 채택하지 않는다.
3. **다중 선택 없음(v1)**. 행마다 작은 "삭제" 버튼 1개 — 공용 `ItemDeleteButton.tsx`, 행 안 확인(Templates.tsx 방식).
4. **DB + 폴더 완전 삭제**: 트랜잭션 안에서 `os.replace` 로 `<esl_root>/_trash/<UTC>_<KIND>_<id>` 이동 → 커밋, 실패하면 원래 자리로 복원. 영구 삭제는 워커 리퍼 `trash_purge.py`(DB 행이 없을 때만, 링크는 따라가지 않음).
5. **지키는 원칙(불변)**: SPDM·입력 폴더(input_roots·upload_root·Case 원본 폴더)와 SCX 드라이브(원격)에는 **쓰지도 지우지도 않는다**. 지우는 것은 esl_root 아래 그 항목의 작업 폴더와 DB 행뿐이다.

## 0. 조사 결과 (근거, main d5ee4cb)

| 목록(탭) | 테이블 | 폴더 (esl_root 기준) | 자식·참조 |
|---|---|---|---|
| 강성 평가 스터디 (`pages/doe/DoeList.tsx`, `GET /doe/studies`) | `bead_does` | `_doe/<id>` (`paths.doe_dir`) | `jobs.bead_doe_id`(DOE_*), `verify_drops.bead_doe_id`(NOT NULL FK, 폴더 `_verify/<vid>` = `paths.verify_dir`; `drive_dir_rel` = SCX 드라이브 원격 경로 — **건드리지 않음**), `jobs.verify_drop_id`(VERIFY_*), `scx_submissions.verify_drop_id`(NOT NULL FK) |
| 비드 최적화 (`pages/opt/OptList.tsx`, `GET /opt/runs`) | `opt_runs` | `_opt/<id>` (`paths.opt_run_dir`) | `jobs.opt_run_id`(OPT_RUN), `template_id` → `opt_templates`(보관 템플릿의 사용 수만 줄어듦) |
| 종합 분석 (`pages/library/LibraryList.tsx` 분석 탭, `GET /library/analyses`) | `analysis_runs` | `_analysis/<id>` (`paths.ANALYSIS_DIR`) | `jobs.analysis_id`(LIB_ANALYZE), **`opt_runs.analysis_id` FK**(생성 시 메타데이터 — `worker/esl_worker/opt_jobs.py` 는 읽지 않음) |
| 버전 비교 (같은 탭, `GET /library/comparisons`) | `comparisons` | `_compare/<id>` (`paths.COMPARE_DIR`) | `jobs.comparison_id`(LIB_COMPARE) |

- 공통: `jobs`(state QUEUED/RUNNING/종료, 자기 FK `retry_of_job_id`), `job_steps.job_id`(FK), `notifications.job_id`(FK 없음), `worker_slot.holder_job_id`(FK 없음, RUNNING 일 때만), `run_alls.cur_job_id`(Case job 전용 — 무관). `esl_runs`·`validations`·`artifacts` 의 `job_id` 는 Case job 전용(`cases_repo` 만 씀)이라 대상 job 집합과 겹치지 않는다(겹치면 FK 위반 → §2 규칙대로 409).
- 모든 항목 테이블에 `project_id`·`dir_rel`·`created_by`(+`created_by_name`)가 있고 id 는 UUID.
- 입력: 업로드(`upload_root` ⊂ input_roots)와 Case 폴더는 읽기만. 스터디 복제(`doe.clone`)는 원본 prep job params 의 업로드 경로만 다시 쓰고 원본 `_doe` 폴더를 읽지 않음 → 원본 삭제가 복제본에 영향 없음.
- 잠금 재시도: `esl.fsutil.atomic_replace`·`is_lock_error`(WinError 5/32), 설정 `worker.fs_retry`(`FsRetryCfg`, 백엔드도 같은 값). 링크 판정 `core/uploads.is_link_like`, 경로 검사 `core/paths.esl_subdir`, 겹침 `core/config.overlaps`.
- 없음 코드(기존): 스터디 `DOE_NOT_FOUND`, 최적화 `OPT_RUN_NOT_FOUND`, 분석 `ANALYSIS_NOT_FOUND`, 비교 `COMPARISON_NOT_FOUND`.

## 1. API

| 메서드·경로 | 설명 |
|---|---|
| `GET /doe/studies/{sid}/delete-check`, `GET /opt/runs/{rid}/delete-check`, `GET /library/analyses/{aid}/delete-check`, `GET /library/comparisons/{cid}/delete-check` | 200 `DeleteCheckOut` (아래). 크기 계산은 하지 않음(느림) |
| `DELETE /doe/studies/{sid}`, `DELETE /opt/runs/{rid}`, `DELETE /library/analyses/{aid}`, `DELETE /library/comparisons/{cid}` | 200 `DeleteOut` (아래) |

**고정 필드명 (schemas.py ↔ types.ts, `check:api` 로 대조 — 이름 바꾸지 말 것)**

| 스키마 | 필드 |
|---|---|
| `DeleteKind` | `"DOE" \| "OPT" \| "ANALYSIS" \| "COMPARE"` |
| `DeleteBlockOut` | `code: str`, `message: str`, `job_id: str\|null`, `job_type: str\|null`, `state: str\|null`, `verify_drop_id: str\|null` |
| `DeleteFolderOut` | `rel: str`, `exists: bool` |
| `DeleteCheckOut` | `kind: DeleteKind`, `id: str`, `title: str`, `can_delete: bool`, `blocked: DeleteBlockOut[]`, `n_jobs: int`, `n_verify_drops: int`, `n_opt_unlinked: int`, `folders: DeleteFolderOut[]` |
| `DeleteOut` | `deleted: bool`(항상 true), `kind: DeleteKind`, `id: str`, `purge: "PENDING" \| "ABSENT"`, `deletion_id: str`, `n_jobs: int`, `n_verify_drops: int`, `n_opt_unlinked: int` |
| `DoeStudyOut`·`OptRunOut`·`AnalysisOut`·`ComparisonOut` (추가) | `can_delete: bool`(권한만 반영), `delete_blocked: str\|null`(비종료 job·검증 낙하·SCX 제출이 있을 때 짧은 사유, 없으면 null) |

- `n_verify_drops` 는 DOE 외 0, `n_opt_unlinked` 는 ANALYSIS 외 0. `folders` 는 지워질 폴더(`_doe/<id>`, 각 `_verify/<vid>` …)와 현재 존재 여부.
- `purge`: 옮긴 폴더가 하나라도 있으면 `PENDING`, 하나도 없으면 `ABSENT`.

| 오류 | 의미 |
|---|---|
| 404 `DOE_NOT_FOUND`/`OPT_RUN_NOT_FOUND`/`ANALYSIS_NOT_FOUND`/`COMPARISON_NOT_FOUND` | 없음 (기존 코드 재사용) |
| 404 `ITEM_DELETED` | `deletions` 에 (kind, id) 기록이 있음. 프런트는 성공으로 처리(멱등) |
| 403 `NOT_ITEM_OWNER` | 등록자도 전역 관리자도 아님 (`require_execute` 실패는 기존 403 그대로) |
| 409 `ITEM_BUSY` | 비종료 job·verify_drop·SCX 제출이 있음, 또는 동시 생성과 경합(FK 위반·40P01). `details.blocked[]` = `DeleteBlockOut[]` |
| 409 `FILE_LOCKED` | 폴더 이동이 재시도 끝까지 잠금에 막힘. `details.path` 는 마스킹한 표시 경로 |
| 422 `PATH_UNSAFE` | 링크·junction, 루트 탈출, 보호 루트와 겹침, 형식이 다른 id, `dir_rel` 불일치 |
| 503 `CONFIG_INVALID` | `require_config_ok` |
| 503 `ITEM_DELETE_DISABLED` | `item_delete.enabled = false` (§11) |

## 2. 차단·연쇄 규칙

- **차단 (모든 종류)**: 항목의 job 중 `state IN (QUEUED, RUNNING)` 이 하나라도 있으면 막는다. 취소를 요청한 RUNNING job 도 워커가 종료할 때까지 막는다.
- **스터디 추가 차단**: `verify_drops.phase ∉ {DONE, FAILED, CANCELED}`, 그 drop 의 job 이 비종료, `scx_submissions.state ∈ {SUBMITTING, SUBMITTED, UNKNOWN}`(원격 SCX 잡 고아 방지). 화면 안내 "검증 낙하를 먼저 취소·포기하세요".
- **잠금 순서** (`api/services/jobs.py` retry 와 같은 순서): ① `SELECT jobs WHERE <subj>=id FOR UPDATE`(스터디는 그 verify_drops 의 job 까지) → ② 항목 행 `FOR UPDATE` → ③ (스터디) verify_drops `FOR UPDATE` → ④ 차단 검사 → ⑤ 폴더 이동(§3) → ⑥ 자식 삭제 → ⑦ 항목 행 삭제 → ⑧ `deletions` 기록 → 커밋.
- **삭제 순서**: notifications(job_id ∈ S) → job_steps → jobs(자기 FK 는 같은 집합 안이라 한 문장) → [스터디] scx_submissions → verify_drops → [분석] `UPDATE opt_runs SET analysis_id = NULL WHERE analysis_id = :id` → 항목 행.
- **ON DELETE CASCADE 를 추가하지 않는다.** ①과 ⑦ 사이에 다른 트랜잭션(retry·preview)이 새 job 을 넣으면 ⑦에서 FK 위반이 나고 → 409 `ITEM_BUSY`, 폴더는 `restore`. 남겨 둔 FK 가 최후 안전장치다.
- **분석 ↔ 최적화 (확정 A)**: SET NULL. `OptRunOut.analysis_id` 와 OptDetail 은 null 을 받아들인다(이미 nullable). 확인창에 "이 분석으로 만든 비드 최적화 {n}건은 남고 연결만 끊깁니다".
- 라이브러리 항목(`entry_ids` JSON)과 템플릿은 소비자를 지울 때 바뀌지 않는다.
- 메모리 캐시: 스터디 삭제 커밋 뒤 `api/services/doe_select.reset_caches()` 를 호출(기존 함수 그대로, 파일 수정 없음).

## 3. 폴더 안전장치 (`core/trash.py` — 백엔드 소유, 워커는 import 만)

**고정 시그니처 (병렬 구현 접점 — 바꾸지 말 것)**

```python
# backend/esl_platform/core/trash.py
TRASH_DIR = "_trash"
KIND_DIR: dict[str, str] = {"DOE": "_doe", "OPT": "_opt", "ANALYSIS": "_analysis", "COMPARE": "_compare", "VERIFY": "_verify"}
DEFAULTS: dict[str, Any]          # §11 item_delete 기본값 단일 출처(ItemDeleteCfg 와 같음 — 시험이 확인)

@dataclass(frozen=True)
class TrashMove:   src: str; dst: str; kind: str; item_id: str; trash_name: str
@dataclass(frozen=True)
class PurgeResult: ok: bool; removed_files: int; skipped_links: int; error: str | None

class PathUnsafe(Exception): ...  # 서비스가 422 PATH_UNSAFE 로
class FileLocked(Exception): ...  # 서비스가 409 FILE_LOCKED 로

def item_dir(settings: Settings, kind: str, item_id: str, dir_rel: str | None = None) -> str
def move_to_trash(settings: Settings, kind: str, item_id: str, dir_rel: str | None = None) -> TrashMove | None   # None = 폴더 없음
def restore(settings: Settings, mv: TrashMove) -> bool
def purge_entry(settings: Settings, trash_name: str) -> PurgeResult
def parse_trash_name(name: str) -> tuple[str, str, str] | None   # (stamp, kind, item_id)
```

- 경로 검사 (`item_dir`, 모두 통과해야 함 — 실패 = `PathUnsafe`):
  - (a) `item_id` 는 UUID 정규식, `kind ∈ KIND_DIR`.
  - (b) `dir_rel` 이 주어지면 `f"{KIND_DIR[kind]}/{item_id}"` 와 정확히 같아야 한다(DB 값을 믿지 않고 경로는 항상 다시 만든다).
  - (c) `esl_subdir(settings, KIND_DIR[kind], item_id)` — 성분 링크·realpath 탈출 거부.
  - (d) `is_link_like` 로 항목 폴더 자체, `<esl_root>/<KIND_DIR>`, `<esl_root>/_trash` 가 링크·junction 이 아님을 확인.
  - (e) `realpath(dir)` 의 부모 == `realpath(esl_root)/<KIND_DIR>`(깊이 1).
  - (f) `overlaps(dir, r)` 가 input_roots(upload_root 포함)·spdm_roots 어느 것과도 거짓. (SCX 드라이브 `scx_drive.roots` 는 릴레이 원격 상대경로라 로컬 겹침 대상이 아니다 — 삭제 흐름은 릴레이를 **호출하지 않는다**.)
  - (g) dir ≠ esl_root, dir ≠ `<esl_root>/<KIND_DIR>`.
- 이동: `os.replace(dir, <esl_root>/_trash/<UTC %Y%m%d-%H%M%S>_<KIND>_<id>)` — esl_root 바로 아래라 같은 볼륨, 원자적. `_trash` 가 없으면 만든다(링크 검사 후). WinError 5/32 = 하위 핸들 열림 → `worker.fs_retry`(attempts·base_s·max_wait_s) 백오프, 끝내 실패 = `FileLocked` → 롤백(아무것도 지워지지 않은 상태).
- 스터디는 `_doe/<id>` → 각 `_verify/<vid>` 순서로 이동. 도중 실패하면 이미 옮긴 것을 역순 `restore` 후 롤백.
- 커밋 실패(DB 예외): 옮긴 것을 모두 `restore`. 되돌리기도 실패하면 로그만 — 휴지통 항목에 DB 행이 남아 있으므로 리퍼가 되돌린다.
- **순서 근거**: "같은 트랜잭션 안에서 휴지통 이동 → 커밋". DB 먼저 지우면 행 없는 고아 폴더, 폴더 먼저 지우면 반쯤 지워진 폴더 + 살아 있는 행이 남는다. 이동은 원자적이고 영구 삭제는 커밋 뒤에만 일어난다.
- **영구 삭제** (워커 리퍼 `worker/esl_worker/trash_purge.py`, `item_delete.purge_interval_s` 주기):
  - `_trash/*` 를 본다(한 주기 최대 `item_delete.purge_batch` 개). `parse_trash_name` 실패 = 건드리지 않고 경고.
  - 해당 kind·id 의 DB 항목 행이 **있으면** 지우지 않는다(롤백 잔여): 원래 자리가 비었으면 `os.replace` 로 되돌리고, 아니면 경고.
  - 행이 없으면 `purge_entry`: 자체 순회(`os.scandir`), 링크·junction 은 링크 객체만 지우고 대상은 따라가지 않음(경고). 파일 단위 PermissionError 는 `chmod(S_IWRITE)` 후 `fs_retry` 백오프로 재시도.
  - 결과는 `deletions.purge_state` = PURGED 또는 FAILED(`purge_attempts`+1, `purge_error` 200자 마스킹). FAILED 는 다음 주기 재시도. `purge_attempts ≥ item_delete.purge_max_attempts` 이면 재시도를 멈추고 `check.py` 가 WARN.
- DB 행이 없는 `_doe|_opt|_analysis|_compare|_verify/<uuid>` 폴더(이전 버전 고아)는 **자동으로 지우지 않는다**. `check.py` 새 항목 `storage.orphans` 가 개수·크기만 보고.

## 4. 권한

- `require_execute(principal, item.project_id)` 이고, 그 위에 `item.created_by == principal.user_id` 또는 `principal.is_global_admin`. 템플릿 삭제(`NOT_TEMPLATE_OWNER`)·job 취소와 같은 판정. 실패 = 403 `NOT_ITEM_OWNER`.
- `can_delete` = 위 판정 결과(권한만). `delete_blocked` = §2 차단 사유 요약(목록 조회에서 계산; 행마다 job 상태 집계 1회 쿼리로).

## 5. UI (frontend)

- 각 행 마지막 열에 **"삭제" 버튼 하나**(btn small ghost):
  - `can_delete=false` → "–" 표시, 툴팁 "등록자·관리자만 삭제할 수 있습니다".
  - `delete_blocked` 있음 → 버튼 비활성, 사유를 툴팁으로.
- 공용 컴포넌트 `components/ItemDeleteButton.tsx`(props: `kind`, `id`, `title`, `canDelete`, `deleteBlocked`, `onDeleted`) — Templates.tsx 의 행 안 확인 방식. 클릭 → delete-check 호출 → 확인 줄 펼침: [영구 삭제] [취소].
- 확인 문구 (스터디 예): "'{title}'을(를) 영구 삭제합니다. 실행 이력 {n_jobs}건·검증 낙하 {n_verify_drops}건과 esl 작업 폴더(_doe/…{id 앞 8자리})가 지워지며 되돌릴 수 없습니다. 올린 입력 파일·SPDM·SCX 드라이브 파일은 그대로 둡니다."
  - 분석에는 "이 분석으로 만든 비드 최적화 {n_opt_unlinked}건은 남고 연결만 끊깁니다"를 덧붙인다.
  - delete-check 의 `blocked` 가 비어 있지 않으면 확인 버튼 없이 사유와 job 링크만.
- 결과: 성공 또는 404 `ITEM_DELETED` → 목록 다시 불러오기 + 토스트 "'{title}' 삭제됨". 409 `FILE_LOCKED` → "파일이 열려 있습니다(보고서·3D 보기 창을 닫고 다시)". 409 `ITEM_BUSY` → 사유 목록.
- 상세 페이지(DoeStudy·OptDetail·AnalysisDetail·ComparisonDetail)에서 404 가 나면 해당 목록 탭으로 이동. v1 에서는 상세 페이지에 삭제 버튼을 두지 않는다.
- **다중 선택 없음(v1).** 후속 판에서 넣는다면 `POST /items/delete {kind, ids[]}` 로 항목별 결과를 돌려주는 방식.

## 6. 감사·기록

- migration `migrations/versions/0016_deletions.py`(down_revision `0015_bead_select`) — `deletions` 테이블:
  - `id`(UUID PK), `kind`(CHECK `DOE|OPT|ANALYSIS|COMPARE`), `item_id`, `project_id`, `title`
  - `item_created_by_name`, `deleted_by`, `deleted_by_name`, `deleted_at`
  - `summary` JSONB `{scenario?, phase?, n_jobs, n_verify_drops, n_opt_unlinked, job_ids[≤ item_delete.summary_job_ids_max]}`
  - `dirs` JSONB `[{rel, trash_name}]`
  - `purge_state`(CHECK `ABSENT|PENDING|PURGED|FAILED`), `purge_attempts`, `purge_error`(≤200자, 마스킹), `purged_at`
  - 인덱스 `(project_id, deleted_at desc)`, unique `(kind, item_id)`
- 로그: `logging.getLogger("esl_platform.audit").info("DELETE kind=%s id=%s project=%s by=%s jobs=%d dirs=%s")`, 서버 경로는 마스킹.
- 데이터는 `core/repositories/deletions.py`(insert·get_by_item·list_pending·mark_purge)로만 접근.

## 7. 시험 (V-DEL-n)

| id | 내용 | 위치 |
|---|---|---|
| 1 | 스터디 DONE 삭제 → bead_does·jobs·job_steps·notifications·verify_drops(종료)·scx_submissions(종료) 행 0, `_doe/<id>`·`_verify/<vid>` 가 `_trash` 로 이동, deletions 1행 PENDING | backend |
| 2 | 최적화·분석·비교도 같은 방식으로 삭제. 분석 삭제 → 참조하던 `opt_runs.analysis_id` NULL, 최적화 행·폴더 그대로(확정 A), `n_opt_unlinked` 일치 | backend |
| 3 | QUEUED·RUNNING job → 409 ITEM_BUSY(`blocked[]`), 행·폴더 변화 없음. 취소 요청 후 RUNNING 도 막힘 | backend |
| 4 | 비종료 verify_drop 또는 SCX 제출 UNKNOWN → 스터디 409 | backend |
| 5 | 경합: job 선택 뒤 다른 트랜잭션이 새 job 삽입 → FK 위반이 409 ITEM_BUSY, 폴더 restore 로 원래 자리 | backend |
| 6 | 권한: 다른 사용자 403 NOT_ITEM_OWNER, 전역 관리자 200, viewer 403 | backend |
| 7 | 두 번째 DELETE = 404 ITEM_DELETED, 없는 id = 404 `*_NOT_FOUND` | backend |
| 8 | `dir_rel` 변조(`_doe/../x`, 다른 id) → 422 PATH_UNSAFE | backend |
| 9 | 항목 폴더·`_doe`·`_trash` 가 심볼릭 링크 또는 junction(`is_link_like` 모의) → 422, 대상 무손상 | backend |
| 10 | esl_root 아래 항목 경로가 input_roots·upload_root·spdm_roots 와 겹치도록 설정 → 422 | backend |
| 11 | 잠금: `os.replace` 가 WinError 32 를 n−1번 → 성공, 모두 → 409 FILE_LOCKED 이고 DB 롤백(행 존재) | backend |
| 12 | 스터디 다중 폴더 이동 중 두 번째 실패 → 첫 번째 restore, 롤백 | backend |
| 13 | 폴더 없는 항목(PREP 직후 실패) → 200, purge ABSENT | backend |
| 14 | 워커 영구 삭제: DB 행 없음 → PURGED. 내부 링크는 링크만 지우고 대상 파일은 남음 | worker |
| 15 | 워커: 휴지통 항목에 DB 행 있음 → 지우지 않고 restore. 이름 형식이 다르면 건드리지 않음 | worker |
| 16 | 워커: 영구 삭제 중 잠금 실패 → FAILED·attempts 증가, 다음 주기 PURGED. 상한 도달 → 재시도 중지 | worker |
| 17 | 입력 업로드 파일과 Case 폴더의 sha256 이 삭제 전후 같음(입력·SPDM 무손상 회귀). 릴레이 호출 0회 | backend |
| 18 | 프런트: 버튼 3상태(–/비활성+툴팁/활성), 확인 문구 개수 반영, 성공·ITEM_DELETED 후 목록 갱신, FILE_LOCKED 문구, `check:api`(openapi ↔ types) 통과 | frontend |
| (+) | 실행 이력에서 삭제 항목의 job 이 사라지고 오류 없음. 알림 링크가 404 여도 화면이 깨지지 않음. `ItemDeleteCfg` 기본값 == `core/trash.DEFAULTS` | backend·frontend |

## 8. 리스크

- R-DEL-1 실행 이력 소실: jobs 를 지우면 "실행 이력"에서 그 항목의 job 도 없어진다. 사용자 결정(DB 영구 삭제)과 일치, `deletions.summary.job_ids` 로만 추적.
- R-DEL-2 Windows 백신·인덱서·열린 보고서·3D FileResponse 가 핸들을 잡으면 이동 실패 → 409 로 안전하게 실패, 사용자가 다시 누름.
- R-DEL-3 `_trash` 는 esl_root 바로 아래라 같은 볼륨(원자적). 영구 삭제 전까지 디스크 공간은 회수되지 않음.
- R-DEL-4 이전 버전 고아 폴더는 자동 정리하지 않음(보고만).

## 9. 제약

- **SPDM·입력 폴더 쓰기 금지 원칙 유지**: 삭제 흐름이 쓰거나 옮기거나 지우는 경로는 `<esl_root>/{_doe,_opt,_analysis,_compare,_verify}/<uuid>` 와 `<esl_root>/_trash/*` 뿐이다. input_roots·upload_root·spdm_roots·Case 원본·SCX 드라이브는 대상이 아니며 §3 (f) 와 V-DEL-10·17 로 확인한다.
- **하드코딩 금지**: 주기·상한·개수는 §11 설정 키로만(기본값 단일 출처 `core/trash.DEFAULTS` = pydantic `ItemDeleteCfg` = 두 예시 yaml). 폴더 이름 상수(`TRASH_DIR`·`KIND_DIR`)는 `paths.py` 의 기존 상수와 같은 성격의 코드 상수.
- 계약 외 파일 수정 금지(§12 소유권 밖은 고치지 않는다).

## 10. 확정 결정 (decisions.md 연결)

| ID | 결정 | 근거 |
|---|---|---|
| D-0.19.0-DEL-1 | 영구 삭제 범위 = DB 행과 esl 작업 폴더만. 입력·SPDM·SCX 드라이브 제외. 범위 4종에 버전 비교 포함 | 사용자 확정 1·5, 같은 탭 일관성 |
| D-0.19.0-DEL-2 | 비종료 job·검증 낙하·SCX 제출이 있으면 409 ITEM_BUSY 로 차단 | 원격 잡 고아 방지, 워커가 쓰는 폴더 보호 |
| D-0.19.0-DEL-3 | 종합 분석 삭제 시 `opt_runs.analysis_id` SET NULL(확정 A) — 차단·연쇄 삭제 없음 | 사용자 확정 2, 최적화 실행은 분석 파일을 읽지 않음 |
| D-0.19.0-DEL-4 | 트랜잭션 안 휴지통 이동(`os.replace`) 후 커밋, 실패 시 restore. 영구 삭제는 워커 리퍼(DB 행 없을 때만, 링크 미추적) | 사용자 확정 4, 원자성 |
| D-0.19.0-DEL-5 | 권한 = 실행 권한 + (등록자 또는 전역 관리자) | 템플릿 삭제·job 취소와 같은 규칙 |
| D-0.19.0-DEL-6 | 다중 선택 v1 제외(행마다 버튼 1개), 이전 버전 고아 폴더는 보고만 | 사용자 확정 3, 부분 실패 표시 복잡도 |

## 11. 설정 (`item_delete:` — 섹션 없으면 기본값)

| 키 | 기본 | 의미 |
|---|---|---|
| `enabled` | `true` | false → DELETE·delete-check 503 `ITEM_DELETE_DISABLED`, `can_delete` 항상 false |
| `purge_interval_s` | `60` | 워커 리퍼 영구 삭제 주기 |
| `purge_batch` | `20` | 한 주기 최대 휴지통 항목 수 |
| `purge_max_attempts` | `20` | 영구 삭제 재시도 상한(넘으면 중지 + check WARN) |
| `summary_job_ids_max` | `50` | `deletions.summary.job_ids` 최대 개수 |

- 잠금 재시도는 새 키를 만들지 않고 기존 `worker.fs_retry` 를 쓴다.
- 기본값 단일 출처 `core/trash.DEFAULTS` ↔ `core/config.ItemDeleteCfg`(Settings 필드 `item_delete: ItemDeleteCfg = ItemDeleteCfg()`) ↔ `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`(주석 블록).

## 12. 파일 소유권 (겹침 0)

경로는 저장소 루트 기준. `B = backend/esl_platform`, `F = frontend/src`.

| 갈래 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Backend** | `migrations/versions/0016_deletions.py`(신규), `B/core/db/tables.py`(deletions), `B/core/config.py`(`ItemDeleteCfg`·Settings 필드), `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`(`item_delete` 블록), `B/core/trash.py`(신규, §3 시그니처), `B/core/repositories/deletions.py`(신규), `B/api/services/item_delete.py`(신규: 공통 흐름 + kind별 자식 삭제·delete-check), `B/api/routers/doe.py`·`opt.py`·`library.py`(DELETE·delete-check — 비교 경로도 `library.py`), `B/api/schemas.py`(DeleteKind·DeleteBlockOut·DeleteFolderOut·DeleteCheckOut·DeleteOut, Out 4종 2칸), `B/api/services/doe.py`(`study_out`)·`opt.py`(`run_out`)·`library.py`(`analysis_out`)·`comparisons.py`(`comparison_out`) — out 직렬화만, `B/check.py`(storage.orphans·purge FAILED 상한 WARN), `backend/tests/test_item_delete.py`(신규), `docs/contracts/openapi_p1b.json`(`scripts/dump_openapi.py` 로 재생성) | V-DEL-1~13, 17 |
| **Impl-Worker** | `worker/esl_worker/trash_purge.py`(신규), `worker/esl_worker/runtime.py`(리퍼 루프에서 `item_delete.purge_interval_s` 마다 호출 — 추가만), `worker/tests/test_trash_purge.py`(신규) | V-DEL-14~16 |
| **Impl-Frontend** | `F/api/doe.ts`(스터디)·`F/api/opt.ts`(최적화)·`F/api/endpoints.ts`(분석·비교 — 기존 analyses·comparisons 호출이 여기 있음), `F/api/types.ts`(§1 고정 필드), `F/components/ItemDeleteButton.tsx`(신규), `F/pages/doe/DoeList.tsx`·`DoeStudy.tsx`, `F/pages/opt/OptList.tsx`·`OptDetail.tsx`, `F/pages/library/LibraryList.tsx`·`AnalysisDetail.tsx`·`ComparisonDetail.tsx`, `F/mock/*`(server.ts·doedata.ts·optdata.ts·p2data.ts 등 해당 목록 mock), `F/__tests__/item_delete.test.tsx`(신규) | V-DEL-18 |
| **통합(메인)** | `VERSION`(0.19.0), `CHANGELOG.md`, `docs/decisions.md`(D-0.19.0-DEL-1~6), `F/pages/guide/content.ts`(FAQ 한 줄), 이 계약 문서 | – |

- **고정 접점 2개**:
  1. `B/core/trash.py` 함수 시그니처·상수(§3 코드 블록) — 백엔드 소유, 워커는 import 만. 워커는 백엔드 구현 전에도 시그니처 모의로 작업 가능.
  2. `B/api/schemas.py` ↔ `F/api/types.ts` 필드명(§1 표: `can_delete`, `delete_blocked`, `DeleteCheckOut`·`DeleteOut`·`DeleteBlockOut`·`DeleteFolderOut`·`DeleteKind`) — `npm run check:api` 로 대조.
- 이 밖에 두 갈래가 같은 파일을 고치는 곳은 없다. `api/services/doe_select.py` 는 고치지 않고 `reset_caches()` 만 호출.
- 순서: Backend(스키마·trash.py 먼저) ∥ Worker(모의) ∥ Frontend(mock) → openapi 재생성 → check:api → 통합.
