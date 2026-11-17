# 계약: 강성 평가 스터디 화면 정리 (UI-TIDY, v0.23.1, 프런트 전용)

- 상태: **확정** (2026-11-17). 원본 = `docs/design/doe_study_ui_v0231.md`(구조 확정, 충돌하면 그 문서 우선). 이 계약은 파일·컴포넌트 수준 명세.
- 버전: **v0.23.1**(main 6ff0cd0 = v0.23.0 위, 패치 — 기존 화면 정리, 새 기능 없음). migration 없음, 백엔드·API·스키마·결과 파일 변경 없음(`check:api` 그대로).
- ID 규칙: 결정 `D-0.23.1-UI-n`, 시험 `V-UI-n`, 리스크 `R-UI-n`.
- 기준 화면 2560×1440(`:root` 17px). ≤2200px 는 기존 분기점에서 1열.

## 0. 조사 결과 (b930b838)

| 항목 | 위치 | 지금 | 이 계약에서 |
|---|---|---|---|
| Card | `F/components/ui.tsx:Card({title, children, right})` | 접기 없음 | 선택 속성 `fold`(§1) |
| 진행 표시 | `DoeStudy.tsx` ① 카드(PREP/FAILED·prep 없음) · 미리보기 카드(PREVIEW, `preview-progress` 1줄 포함) · 결과 카드(RUN/FAILED) 각각 `Steps`+`JobProgress` | 3곳 | 제목줄 아래 진행 띠 1곳(§3) |
| 미리보기 실패 | `JobFailBanner`(제목 = 작업·단계·코드) + 미리보기 카드 `BlockErr preview-failed`(같은 단계·코드 다시) | 2곳 | 배너 1곳 + 카드 안 안내 1줄(단계·코드 없음) |
| 결과 상단 | `mq-base-strip` 1줄 + `ul.reasons` 무제한 + DoeRanking 안 `best-clean`·`best-clean-mq`·`doe-metric-bar`(정렬 문구·보조 토글·ⓘ)·`JigLine` + 순위표 아래 `sm-verify-note`/`sm-cross-note` + `LoadTransferDiag`(요약 줄 + details) | 5~8줄 | 상태 띠 1줄(§4) |
| ESL별 표 | `DoePerEslTable` 아래 설명 줄 "셀 = 개선율 …" | 표 아래 | ⓘ 지표 정의 안 |
| 민감도·3D | `.doe-result-grid`(0.8fr/1.6fr) 또는 sens-hidden + 3D | 순위·ESL표 아래 | 결과 2열의 오른쪽 열 |
| 받기 | `Downloads`(받기 · 최적 dNNN · include/메시 파일 n · BREP/STEP · 순위 CSV · 결과 받기(zip) · 검증 낙하 · 재낙하) 결과 하단 1줄 + 하단 안내문 1줄 | 하단 | 두 묶음(§5) |
| 경계 경고 수 | ① right(②③ 선택 기준), ⑤/③ 평면도 right, 결과 right(`boundary_warnings_n`) | 최대 3곳 | ① right 1곳 |
| 요소·노드 수 | ① right(“x.x만 노드”), ② 비드 선택 right(“요소 N · 노드 M”) | 2곳 | ① right(정확 값은 같은 칸 title) |
| 새 스터디 | ① 카드 = `DoeInputs` 1열, 카드 아래 시나리오 설명 `small muted` 2~3문장 | | ① 안 2열 + 설명 ⓘ 접기(§7) |
| 목록 | `DoeList.tsx` 1행 주석 "…·최적 개선율" — 실제 열에 없음 | | 주석만 고침 |

## 1. Card 접기 속성 API (`F/components/ui.tsx`)

```ts
export interface CardFold {
  /** sessionStorage 키 뒷부분(esl.cardfold.<storeKey>) — 스터디 id + 카드 번호 */
  storeKey: string;
  /** 사용자가 바꾸지 않았을 때의 기본(단계 초점 §2 의 결과) */
  defaultOpen: boolean;
  /** true = 항상 펼침(실행 중·실패 단계) — 접기 단추 없음, 저장값 무시 */
  locked?: boolean;
}
Card({ title, children, right, fold?: CardFold | null })
```
- `fold` 없음(또는 null) = 기존과 **바이트 동일한 DOM**(다른 화면 영향 0, V-UI-1).
- `fold` 있음·`locked` 아님: 머리 `h3` 안에 `<button type="button" class="card-fold-btn" aria-expanded>` = `<span aria-hidden>▸|▾</span> {title}` (heading 이름 = title 그대로). 머리 끝에 기존 `right`(요약) 그대로 — 접힌 막대 = 제목 + 기존 right + 펼치기.
- 접힘: `section.card.folded`, 본문 `<div class="card-body" hidden>` — **언마운트하지 않는다**(3D·입력 상태 보존, 다시 열 때 재요청 없음). 접힌 사본도 DOM 1개(중복 규칙 §6 는 DOM 기준).
- 저장: 사용자가 누를 때만 `sessionStorage["esl.cardfold.<storeKey>"] = "1"|"0"`(try/catch — MsgFold 와 같은 방식). 읽기: 저장값 있으면 그것, 없으면 `defaultOpen`. 단계가 바뀌어 `defaultOpen` 이 바뀌면 저장값이 없는 카드만 따라간다.
- 색·폰트 새로 없음: 단추 = 머리 글꼴 상속, 배경 없음.

## 2. 단계 초점 (StudyDetail)

**단계 판정식** (기존 변수만 사용):
```
stage = ranStage ? "result" : hasPreview ? "preview" : "setup"
  ranStage   = phase∈{RUN,DONE} ∨ (phase=FAILED ∧ (isCompare ? prep : doe.preview))   // 기존 식
  hasPreview = !!doe.preview ∨ phase=PREVIEW                                         // 기존 식
```
| 카드 | 카드 단계 | storeKey | locked(항상 펼침) |
|---|---|---|---|
| ① 입력 | setup | `<id>:c1` | phase=PREP ∨ (phase=FAILED ∧ !prep) |
| ② 비드 선택 · ③ 비드 목록·도구 (select) | setup | `<id>:c2`·`<id>:c3` | – |
| ④ 변수 · ⑤ 평면도·단면 (select) / ② 비드·변수 · ③ 평면도 (이전 방식) | setup | `<id>:c4`·`<id>:c5` | – |
| 미리보기(⑥/④) | preview | `<id>:pv` | phase=PREVIEW ∨ 마지막 작업이 실패한 `DOE_PREVIEW` |
| 결과 | result | – (fold 없음) | – |
| VerifyDropCard · 3D 보기(SelectDesign3D) | – | fold 없음 | – |

- `defaultOpen = (카드 단계 == stage)`. 비교(④)는 ① + 결과뿐.
- 근거(D-0.23.1-UI-2): 설계 §4 "지난 단계는 한 줄". 미리보기 단계에서도 ②~⑤ 는 편집 가능하지만 설계 취지(지금 단계만)를 따르고 한 번 펼치면 세션 동안 유지된다.

## 3. 진행 띠 (StudyDetail, 제목줄 아래)

- 위치: 제목줄 → 막힘 상자 → paicad 경고 → `JobFailBanner` → 오류 줄 → **진행 띠** → 카드들.
- 표시 조건과 내용(이전에 각 카드가 그리던 것을 그대로 옮김):

| 조건 | 내용 |
|---|---|
| `job` ∧ (phase=PREP ∨ (phase=FAILED ∧ !prep)) | `Steps` + `JobProgress compact` (전 ① 카드) |
| `job` ∧ phase=PREVIEW | `preview-progress` 1줄 "미리보기 진행 중 · {progressText}" + `Steps` + `JobProgress compact` (전 미리보기 카드) |
| `job` ∧ (phase=RUN ∨ (phase=FAILED ∧ ranStage)) | `Steps` + (jobActive ∨ FAILED 이면) `JobProgress`(전 결과 카드) |

- 요소 `<div class="doe-progress" data-testid="doe-progress">`. 위 셋은 서로 배타 → 화면에 `Steps`(`ol[aria-label="DOE 단계"]`) 최대 1개.
- 미리보기 실패: 카드 안 `BlockErr preview-failed`(단계·코드 반복)는 없애고 같은 testid 의 안내 1줄(`small warn-text`) "미리보기가 끝나지 못했습니다 — 위 실패 줄 [자세히] → [로그 보기]에서 원인을 확인하고 다시 [미리보기] (아래는 이전 미리보기)"(뒷 괄호는 pv 있을 때만). 단계·코드는 `JobFailBanner` 1곳(D-0.23.1-UI-3).

## 4. 결과 카드 상태 띠

`<div class="doe-status" data-testid="doe-status">` — 결과 카드 본문 맨 위 1줄(flex-wrap). 칩 = `<span class="doe-chip {muted|warn-text}">`, 기존 색 클래스만. 칩의 testid 는 **이전 줄의 testid 를 그대로** 쓰고, 이전 줄 전체 문구는 칩 `title`(툴팁)에 그대로 둔다.

| 순서 | 칩 | 조건 | 보이는 값(짧게) | 색 | 상세(title / 펼침) — 출처 |
|---|---|---|---|---|---|
| 1 | `jig-line` (`data-status` 유지) | `result.jig` | ok·poor: "기준 재현(지그) MAC ≥ {fit_mac_min} · umax 오차 ≤ {…}" + `jig-cancel` ⚠(있을 때, 칩 안 1개 — D-JIG-19 그대로) · fallback·unsupported: "지그 순위 불가" | poor·fallback = warn-text, 그 밖 muted | title = 이전 JigLine 줄 전체 문구 + 이전 title(extra·엔트리별) — `DoeRanking.tsx:JigLine` |
| 2 | `lt-block` 안 `details#lt-details` 의 summary `lt-summary` | `result.load_transfer` | "하중 전달 {주 방식}" ▾ | muted | summary title = `ltSummaryLine`+(모델 차 포함)+다른 방식 순위+경고 n(이전 요약 줄 전체). 펼치면 띠 아래 전폭으로 진단 표(이전 details 내용 그대로) — `DoeStudy.tsx:LoadTransferDiag` |
| 3 | `mq-base-strip` | 기준 메시 품질 경고(scope base) | "⚠ 기준 메시 품질 미달" | warn-text | title = `⚠ warnText(mqBase)` |
| 3' | `best-clean-mq` | 품질 미달 행 ≥ 1 | "⚠ 품질 미달 {n}개 · 통과 최상위 {id}" | warn-text | title = 이전 줄 전체 |
| 4 | `best-clean` | 1위가 경고 안 | "⚠ 1위 경고 안 · 경고 없는 최상위 {id}" | warn-text | title = 이전 줄 전체 |
| 5 | `MsgFold testId="result-warn"` | 스터디 수준 경고 ≥ 1 | MsgFold 요약 "⚠ 경고 n건 · …" | 기존 MsgFold | 펼치면 띠 아래 전폭 목록. 항목 = 이전 `ul.reasons`(SENSITIVITY_TOO_FEW·SM_CROSS_MESH·base MQ 제외 그대로) + 다른 메시 비교일 때 이전 `sm-cross-note` 문구 1항목 |

- 칩이 0개면 띠를 그리지 않는다. 띠 안 펼침 상세(LT details·MsgFold 목록)는 CSS 로 띠 아래 전폭 줄로 내려간다(`order`·`flex-basis:100%`).
- 1위가 경고 안이 아닐 때 "경고 없음" 칩은 만들지 않는다(새 정보 금지 — 이전에도 줄 없음).
- `sm-cross-note`: 경고 MsgFold 항목으로 옮김(경고색 유지, D-0.23.1-UI-4). testid `sm-cross-note` 는 없어짐 → 시험은 `result-warn` 목록으로 갱신.
- `sm-verify-note`·하단 안내문: §5 검증 낙하 툴팁 + VerifyDropCard 머리말 / ④ 는 ⓘ 지표 정의.

### 4.1 ⓘ 지표 정의(순위표 위 `doe-metric-bar`)
- `doe-metric-bar` = [보조 열 보기 토글] [ⓘ 지표 정의]. "정렬: …" span 은 bar 에서 빼고 `metric-defs` 첫 항목 `<li data-testid="rank-sort">정렬: …</li>` 로(같은 문구).
- `metric-defs` 끝에 ESL별 표 설명 `<li data-testid="per-esl-note">셀 = 개선율(…) · 상위 N개[ + 선택 안]</li>`(문구 동일, `DoePerEslTable.tsx` 의 새 export `perEslNote(result, pick, topN)` 가 만들고 표 아래 줄은 없앰; ESL 열이 없으면 null).
- ④(compare) 결과 하단 안내문(“선형 강성 상대 비교입니다 — 형상마다 새 메시…”)은 `metric-defs` 끝 `<li data-testid="result-note">` 로(검증 낙하 버튼이 없는 모드라서 — D-0.23.1-UI-5).

## 5. 버튼 두 묶음

| 묶음 | 위치 | 구성(순서) |
|---|---|---|
| 스터디 받기 `data-testid="doe-downloads"` | 결과 카드 머리 `right` | [결과 받기(zip)] [순위 CSV] [`details.doe-files-menu` summary "파일 ▾" 안: "최적 {best.id}" 라벨 + include/메시 파일 n개 + BREP/STEP] — 파일 0개면 details 없음(“최적 …” 라벨은 순위 CSV 앞 muted 로) |
| 선택 안 작업 `data-testid="doe-pick-actions"` | 결과 오른쪽 열 머리 | [재낙하 엔트리 select + 재낙하 입력 받기] [검증 낙하](compare 는 없음 — 기존 규칙) |

- 오른쪽 열 머리 왼쪽: `<span data-testid="doe-pick-head">` = "선택 안 {did}"(+ 형상 이름 또는 변수값 `valuesText`), 고른 안이 없으면 "순위표에서 안을 고르세요"(재낙하 비활성 사유와 같은 문구).
- 검증 낙하 툴팁: `vd.reason ?? 기존 기본 문구` 뒤에 줄바꿈 + 권고 문구(lin = 이전 `sm-verify-note` 문구, 그 밖 = 이전 하단 안내문 "선형 강성 상대 비교입니다(낙하 응답 재현 아님) — 최적 안은 검증 낙하 1회로 확인하세요. 방법·출처·한계는 보고서에."). 이전 `sm-verify-note`·하단 안내문 줄은 없앰.
- `VerifyDropCard` 머리 right 앞에 같은 권고 1줄 — 새 선택 prop `note?: string`(없으면 기존 DOM). 카드가 그려질 때만(검증 낙하 기록 있음).
- 버튼·링크 개수·라벨·URL·파일명 불변(새 버튼 0).

## 6. 결과 2열 (`.doe-result-2col`)

```
결과 카드 머리: 제목 | 스터디 받기
상태 띠
.doe-result-2col
  .doe-result-left : DoeRanking(metric-bar·순위표) · sub-title "ESL별 개선율" · DoePerEslTable
  .doe-result-right: 선택 안 머리(§5) · sub-title "3D 비교" · Compare3D · sub-title "민감도" · Sensitivity | sens-hidden 줄
```
- 오른쪽은 항상 3D 비교(자료 없으면 기존 Empty)가 있어 "둘 다 없음"은 생기지 않음 — 그래도 `.doe-result-2col.solo`(왼쪽 전폭) 규칙은 둔다(view3d 0개 ∧ 민감도 숨김일 때).
- 이전 `.doe-result-grid`(민감도|3D)는 결과에서 쓰지 않음(클래스는 남김 — 다른 곳 0, 삭제는 하지 않음).
- 2560: `grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr)`; ≤2200px: 1열(기존 `.doe-grid` 와 같은 media 블록).

### 6.1 높이 예산 (2560×1440, 결과 단계)
```
--doe-chrome: 접힌 막대들 + 제목줄 + 진행 띠 (목표 ≤ 200px, 측정 보고)
.doe-result-2col { --doe-res-h: calc(100vh - var(--topbar-h) - 21rem); }        /* ≈ 1440 − 54 − 357 ≈ 1030px */
.doe-result-left  .doe-rank-wrap    { --tbl-max: calc(var(--doe-res-h) - 17rem); }  /* 순위표가 남는 높이 */
.doe-result-left  .doe-per-esl-wrap { --tbl-max: 12rem; }                           /* ESL별 고정 상한 */
.doe-result-right .doe-compare-grid .v3d-host { height: calc(var(--doe-res-h) * 0.45); }
.doe-result-right .doe-sens svg { max-height: calc(var(--doe-res-h) * 0.3); }
```
- ≤2200px 에서는 이 재정의를 적용하지 않음(기존 clamp 값 그대로 — 1열 세로 흐름).
- 목표: 결과 단계에서 결과 카드 아래 끝 ≤ 뷰포트 + VerifyDropCard. 렌더 측정값은 검증 보고에 적고, 넘으면 사용자 현장 확인 항목.

## 7. 새 스터디 / 긴 글 / 목록

- **① 입력 2열**(`DoeInputs.tsx`): `.doe-inputs` 안을 `.doe-inputs-cols` 두 열로 — 왼쪽 `.doe-inputs-left` = ESL 칩·다른 모델 빼기 + 업로드(STEP·B 메시) / select 안내 줄, 오른쪽 `.doe-inputs-right` = 형상 표(④)·필드(파트 제목·인치·물성·요소·제목) + 고급 설정 + 검사 줄. ④(compare)는 형상 표가 넓어 **왼쪽 = ESL, 오른쪽 = 형상 표 + 필드**. 2560: `minmax(0,1fr) minmax(0,1fr)`, ≤2200px: 1열. `72rem` 상한은 열 안에서 그대로(열이 좁으면 열 폭).
- **새 스터디 시나리오 설명**(카드 아래 2~3문장): 첫 문장(“입력 준비에서/가 끝나면 … ”) 한 줄은 유지, 나머지(하중·지지 문장, "입력 폴더는 읽기만 합니다.")는 같은 줄 끝 `<details class="doe-note-more"><summary>ⓘ</summary>…</details>`. 라이브러리 링크 문장은 ESL 미선택 때 그대로 보임(핵심 안내).
  - 근거(D-0.23.1-UI-6): 설계 §5 "2문장 이상 → ⓘ details, 한 줄 핵심 유지". 첫 문장을 남기는 이유 = 시나리오별 다음 동작 안내.
- DoeInputs 도움말: 2문장 이상인 상시 문구는 `doe-select-note` 1개뿐(1문장 + 대시) → 유지. UploadDrop hint 는 1줄 → 유지.
- **목록**(`DoeList.tsx`): 1행 주석 "…·상태·최적 개선율" → 실제 열("만든 시각·제목·시나리오·ESL·DOE·미리보기·상태")로. 코드 변경 없음.

## 8. 정보 보존 대조표 (정리 전 → 정리 후)

| # | 정리 전 | 정리 후 | 보는 법 |
|---|---|---|---|
| 1 | ① 카드 Steps+JobProgress(PREP) | 진행 띠 | 그대로 보임 |
| 2 | 미리보기 카드 `preview-progress`+Steps+JobProgress | 진행 띠 | 그대로 |
| 3 | 결과 카드 Steps+JobProgress(RUN/FAILED) | 진행 띠 | 그대로 |
| 4 | `preview-failed` BlockErr(단계·코드·안내) | 단계·코드 = JobFailBanner, 안내 = 미리보기 카드 1줄 | 그대로 |
| 5 | `mq-base-strip` 줄 | 칩 3 | 툴팁 |
| 6 | `ul.reasons` 경고 목록 | 칩 5 MsgFold | 1클릭 |
| 7 | `best-clean`·`best-clean-mq` 줄 | 칩 4·3' | 값 보임 + 툴팁 전체 |
| 8 | `JigLine` 줄(+title) | 칩 1 | 값 보임 + 툴팁 전체 |
| 9 | "정렬: …" | ⓘ 지표 정의 첫 항목(+ 열 머리 ▲ 그대로) | 1클릭 |
| 10 | `sm-verify-note` | 검증 낙하 툴팁 + VerifyDropCard 머리말 | 툴팁 |
| 11 | `sm-cross-note` | 칩 5 MsgFold 항목 | 1클릭 |
| 12 | LT 요약 줄 + details | 칩 2(summary, title = 요약 줄) + 같은 details | 툴팁 / 1클릭 |
| 13 | ESL별 표 아래 설명 | ⓘ 지표 정의 항목 | 1클릭 |
| 14 | 결과 하단 안내문(①②③) | 검증 낙하 툴팁 + VerifyDropCard 머리말 | 툴팁 |
| 15 | 결과 하단 안내문(④) | ⓘ 지표 정의 항목 | 1클릭 |
| 16 | 받기 줄 "받기 · 최적 dNNN" + 파일 링크 | 스터디 받기 묶음, 파일 링크는 "파일 ▾" | 1클릭 |
| 17 | 결과 right "경계 경고 n" | ① right(값이 prep 과 다르면 "(결과 m)") | 그대로(접힌 막대에도) |
| 18 | ③/⑤ 평면도 right 경계 경고 | ① right | 그대로 |
| 19 | ② 비드 선택 right "요소 N · 노드 M" | ① right 노드 칸 title | 툴팁 |
| 20 | 지난 단계 카드 본문 | 접힌 카드(hidden) | 1클릭(펼치기) |
| 21 | 새 스터디 설명 2·3문장 | ⓘ details | 1클릭 |

## 9. 한 정보 한 자리 — DOM 기준 판정(V-UI-4)

| 정보 | 판정 |
|---|---|
| 진행 | `ol[aria-label="DOE 단계"]` ≤ 1, `JobProgress` 루트 ≤ 1 |
| 미리보기 실패 단계·코드 | 문자열 "단계 n {label} · {code}" 는 `job-fail-banner` 안에만 |
| 스터디 경고 | 결과 경고 문구는 `result-warn` 안에만(`ul.reasons` 0) |
| 정렬 설명 | "정렬:" 문자열 1개(metric-defs 안) |
| ESL별 설명 | "셀 = 개선율" 1개 |
| 검증 권고 | `sm-verify-note` 0, 권고 문구는 vd 툴팁(+VerifyDropCard 있으면 머리말) |
| 경계 경고 수 | "경계 경고" 문자열을 가진 카드 right = ① 1개 |
| 검증 낙하 버튼 | `vd-open` ≤ 1 |

## 10. 파일 소유 (구현 갈래 — Agent 도구 없음: 메인이 A → B → C 순차, 겹침 없음)

| 갈래 | 파일 |
|---|---|
| A 뼈대 | `F/components/ui.tsx`(Card fold), `F/styles.css`(공용: `.card-fold-btn`·`.card.folded`·`.doe-progress`·`.doe-status`·`.doe-chip`·`.doe-result-2col`·`.doe-inputs-cols`·`.doe-files-menu`·`.doe-note-more`·높이 식), `F/pages/doe/DoeStudy.tsx`(StudyDetail 단계 초점·진행 띠·preview-failed), `F/components/BeadSelectCard.tsx`(`BeadSelectCards` 에 `fold2`·`fold3` prop, ② right 제거) |
| B 결과 | `F/pages/doe/DoeStudy.tsx`(결과 카드·상태 띠·LoadTransferDiag·Downloads·RedropControl 배치·vd 툴팁), `F/components/DoeRanking.tsx`(JigLine 칩·best-clean 칩 export, 정렬 문구 이동, per-esl/결과 안내 li), `F/components/DoePerEslTable.tsx`(`perEslNote`), `F/components/VerifyDropCard.tsx`(`note` prop) |
| C 새 스터디 | `F/components/DoeInputs.tsx`(2열), `F/pages/doe/DoeStudy.tsx`(NewStudy 설명 접기), `F/pages/doe/DoeList.tsx`(주석) |
| 시험 | `F/__tests__/doe_ui_tidy.test.tsx`(신규) + 기존 시험 의미 동일 갱신 |
| 통합 | `VERSION`, 버전 시험 2곳, `CHANGELOG.md`, `docs/decisions.md`, 이 계약 |

`MsgFold.tsx` 는 고치지 않는다(재사용만).

## 11. 시험 (V-UI-n)

| id | 내용 | 위치 |
|---|---|---|
| 1 | Card: fold 없으면 기존 마크업(머리 h3 텍스트, 단추 없음); fold → 단추 aria-expanded, 접힘 = body hidden·DOM 유지, 누르면 sessionStorage 저장·복원, locked = 단추 없음·항상 펼침 | `doe_ui_tidy.test.tsx` |
| 2 | 단계 초점: doe-1(DONE) ①·②·③·미리보기 접힘, 결과 펼침; doe-5(READY) ① 펼침; doe-6(PREVIEW_READY) 미리보기 펼침·① 접힘; 펼친 뒤 재렌더(같은 세션) 유지 | 〃 |
| 3 | 진행 띠: PREP·PREVIEW·RUN 각각 `doe-progress` 1개, `DOE 단계` 목록 1개 | 〃 |
| 4 | 중복 0: §9 표(doe-1·doe-20·doe-40·doe-41) | 〃 |
| 5 | 상태 띠: 칩 순서·title 에 이전 문구 전체(jig·lt·best-clean·mq), jig-cancel ⚠ 1개 | 〃 + doe_jig·doe_shape_rules·doe_select 갱신 |
| 6 | 버튼 묶음: `doe-downloads` 가 결과 카드 머리에, 파일 링크는 "파일 ▾" 안, `doe-pick-actions` 에 재낙하·검증 낙하, `vd-open` 1개, vd title 에 권고 문구 | 〃 + doe·doe_compare·verify 갱신 |
| 7 | ⓘ 지표 정의에 rank-sort·per-esl-note(·④ result-note) | 〃 |
| 8 | 새 스터디: `.doe-inputs-cols` 두 열, 설명 첫 문장 보임·나머지 ⓘ details | 〃 |
| 9 | 회귀: vitest 전부·typecheck·build·check:api | – |
| 10 | 렌더(2560×1440, mock): 정리 전·후 정보 목록 대조(문구·title·버튼), 결과 단계 높이 | 검증 보고(사람·스크립트) |

## 12. 리스크

- R-UI-1 접힌 카드 안 3D 뷰어(hidden)는 펼칠 때 크기 0 → 뷰어 ResizeObserver 에 의존. 다시 열었을 때 빈 캔버스면 창 크기 바꾸기로 복구 — 현장 확인.
- R-UI-2 높이 예산은 순위 행 수·ESL 수·브라우저 확대율에 따라 넘칠 수 있다(내부 스크롤로 흡수). select 는 접힌 막대 4줄(①, ②|③, ④|⑤, ⑥) ≈ 250px 로 200px 목표를 넘을 수 있음 — 측정 보고.
- R-UI-3 칩 문구를 짧게 하면서 이전 줄 전체는 title 로만 보임(터치 기기는 툴팁 불편). 사내 데스크톱 기준.
- R-UI-4 `details name` 배타 펼침은 쓰지 않음(MsgFold 와 섞임) — 두 상세가 동시에 열릴 수 있음.

## 13. 결정 (decisions.md)

| ID | 결정 |
|---|---|
| D-0.23.1-UI-1 | Card 선택 속성 `fold{storeKey, defaultOpen, locked}` — 접힘 = hidden(언마운트 안 함), 사용자 조작만 sessionStorage, 속성 없으면 기존 DOM |
| D-0.23.1-UI-2 | 단계 = result(ranStage) / preview(hasPreview) / setup, 지난·다음 단계 카드 기본 접힘, 실행 중·실패 단계 locked |
| D-0.23.1-UI-3 | 진행(Steps+JobProgress)은 제목줄 아래 진행 띠 1곳, 미리보기 실패 단계·코드는 JobFailBanner 1곳(카드 안 = 안내 1줄) |
| D-0.23.1-UI-4 | 결과 상태 띠 칩 = 지그·하중 전달·메시 품질·1위 경고·경고 MsgFold, 칩 testid = 이전 줄 testid, 이전 줄 전체 = title. 다른 메시 비교 문구는 경고 MsgFold 항목 |
| D-0.23.1-UI-5 | 정렬 문구·ESL별 표 설명·④ 결과 안내문은 ⓘ 지표 정의 안, ①②③ 검증 권고는 검증 낙하 툴팁 + VerifyDropCard 머리말 |
| D-0.23.1-UI-6 | 버튼 두 묶음(스터디 받기 = 결과 머리, 선택 안 작업 = 오른쪽 열 머리), 파일 링크는 "파일 ▾", 결과 2열(≤2200px 1열)·높이 식은 2201px 이상만 |
| D-0.23.1-UI-7 | 새 스터디 ① 2열(≤2200px 1열), 카드 아래 설명은 첫 문장만 상시·나머지 ⓘ, 경계 경고·요소·노드 수는 ① right 1곳 |
