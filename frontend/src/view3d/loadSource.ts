// v0.24.4 P3 하위 작업 하중 출처 선택(esl_jig_case.md §9) — 순수 논리(화면 부품·시험 공용).
// 출처 표 = SOURCE_ROWS(view3d/sources.ts) 한 곳. 호출부는 열(label·optional·optUnsupported)만 읽고 출처 이름으로 분기하지 않는다.
// ④ 판정 표식은 markOf 재사용(PASS/FAIL·판정 불가·비교용 아님·⚠). 선택 항목들의 같은 출처 행 중 최악 1개를 보인다.
import type { EntrySourceRow, EntrySourcesItem, LoadGrade, LoadSourceCheck, ValidationStatus } from "../api/types";
import { ApiError, errorText } from "../api/client";
import { SOURCE_ROWS, VAL_NOT_RUN_CODE, isHiddenSource, markOf, sourceRow, unavailText, type TabMark } from "./sources";

export type LoadSourceCtx = "doe" | "opt";

export interface LoadSourceOption {
  key: string;
  label: string;
  /** true = 선택 불가(사유 = why) */
  disabled: boolean;
  why: string | null;
  /** 최악 판정 표식(없으면 null — 판정 정보 없음) */
  mark: TabMark | null;
  /** 경고 + 확인이 필요한 출처(검증 미통과·판정 불가·검증 전·비교용 아님·한계) — 서버 422 와 같은 기준의 안내용 */
  warn: boolean;
  /** 드롭다운 글자 */
  text: string;
  /** 툴팁(항목별 상세) */
  title: string;
}

const MARK_NOT_RUN: TabMark = { text: "검증 전", tone: "muted" };

/** 항목 1개 × 출처 1행의 상태(순수): 불가·판정 표식·심각도(클수록 나쁨) */
interface Cell {
  entryId: string;
  blocked: string | null;
  mark: TabMark | null;
  sev: number;
}

const SEV_FAIL = 5;
const SEV_UNDET = 4;
const SEV_NOT_COMP = 3;
const SEV_CAUTION = 2;

function cellOf(item: EntrySourcesItem, key: string, label: string, ctx: LoadSourceCtx): Cell {
  const entryId = item.entry_id;
  const row: EntrySourceRow | undefined = item.rows.find((r) => r.key === key);
  // 검증 자체가 없는 항목(rows 비어 있음) = 결과 없음 → 경고(차단 아님)
  if (!item.rows.length) return { entryId, blocked: null, mark: MARK_NOT_RUN, sev: SEV_UNDET };
  if (!row) return { entryId, blocked: unavailText(label, "이 ESL 결과에서 출처 정보를 받지 못했습니다"), mark: null, sev: 0 };
  // 서버가 본 출처 하중 존재(B3 load_available) — 없으면 선택 불가(서버 422 LOAD_SOURCE_UNAVAILABLE 과 같은 기준)
  if (row.load_available === false) return { entryId, blocked: unavailText(label, row.load_reason ?? row.reason ?? row.load_code ?? "하중 없음"), mark: null, sev: 0 };
  // 비드 최적화로 전달 불가(서버가 미리 알림: opt_code) — 선택 불가, 사유 = 서버 문구(생성 때 422 UNSUPPORTED 와 같은 규칙)
  if (ctx === "opt" && row.opt_code) return { entryId, blocked: unavailText(label, row.opt_reason ?? row.opt_code), mark: null, sev: 0 };
  if (!row.available) {
    if (row.code === VAL_NOT_RUN_CODE) return { entryId, blocked: null, mark: MARK_NOT_RUN, sev: SEV_UNDET };
    return { entryId, blocked: unavailText(label, row.reason), mark: null, sev: 0 };
  }
  const mark = markOf(row);
  const sev = row.status === "FAIL" ? SEV_FAIL : row.status === "UNDETERMINED" ? SEV_UNDET : row.comparable === false ? SEV_NOT_COMP : row.limits.length > 0 ? SEV_CAUTION : row.status === "LEGACY" ? 1 : 0;
  return { entryId, blocked: null, mark: mark ?? { text: "판정 불가", tone: "muted" }, sev: mark ? sev : SEV_UNDET };
}

/**
 * 출처 옵션 목록(순수). data = 선택 항목들의 묶음 판정(null = 아직 못 받음·실패 → 표식 없이 모두 선택 가능, 서버가 최종 판정).
 * optional 열 행은 어느 항목의 응답에도 없으면 그리지 않는다(옛 서버 = 이전 화면). 불가 사유가 있는 행은 disabled.
 */
export function loadSourceOptions(data: readonly EntrySourcesItem[] | null, ctx: LoadSourceCtx): LoadSourceOption[] {
  const shown = SOURCE_ROWS.filter((r) => !isHiddenSource(r.key) && (!r.optional || !data || data.some((it) => it.rows.some((x) => x.key === r.key))));
  return shown.map((r) => {
    const base = { key: r.key, label: r.label };
    const colWhy = ctx === "opt" && r.optUnsupported ? unavailText(r.label, r.optUnsupported) : null;
    if (colWhy) return { ...base, disabled: true, why: colWhy, mark: null, warn: false, text: `${r.label} — 선택 불가: ${r.optUnsupported}`, title: colWhy };
    if (!data) return { ...base, disabled: false, why: null, mark: null, warn: false, text: r.label, title: r.title };
    const cells = data.map((it) => cellOf(it, r.key, r.label, ctx));
    const blocked = cells.filter((c) => c.blocked);
    if (blocked.length) {
      const why = blocked[0].blocked!;
      const more = blocked.length > 1 ? ` 외 ${blocked.length - 1}개 항목` : "";
      const reason = why.replace(`${r.label} 불가 — `, "");
      return { ...base, disabled: true, why: why + more, mark: null, warn: false, text: `${r.label} — 선택 불가: ${reason}${more}`, title: why + more };
    }
    const worst = cells.reduce<Cell | null>((a, c) => (!a || c.sev > a.sev ? c : a), null);
    const mark = worst?.mark ?? null;
    const warn = !!worst && worst.sev > 0;
    const offenders = cells.filter((c) => c.sev > 0 && c.mark).map((c) => `${c.entryId}: ${c.mark!.text}`);
    return { ...base, disabled: false, why: null, mark, warn, text: mark ? `${r.label} · ${mark.text}` : r.label, title: offenders.length ? `${r.title}\n${offenders.join("\n")}` : r.title };
  });
}

/** 요청에 넣을 칸(선택 안 함 = 필드 생략 → 지금과 같은 요청). ack = 경고 확인 뒤 재요청에만 */
export function loadSourceBody(value: string, ack = false): { load_source?: string; load_source_ack?: true } {
  if (!value) return {};
  return { load_source: value, ...(ack ? { load_source_ack: true as const } : {}) };
}

export const UNCONFIRMED_CODE = "LOAD_SOURCE_UNCONFIRMED";
export const UNAVAILABLE_CODE = "LOAD_SOURCE_UNAVAILABLE";
export const UNSUPPORTED_CODE = "LOAD_SOURCE_UNSUPPORTED";

/** 422 확인 요청 본문(esl_jig_case.md §9: {entries, worst}) */
export interface UnconfirmedDetail {
  entries: { entry_id: string; status: ValidationStatus | null; comparable: boolean | null; validation_id?: string | null; grade?: LoadGrade; flags?: LoadGrade[]; limits?: string[] }[];
  worst: LoadGrade | null;
}

/** 서버 확인 요청이면 그 본문, 아니면 null */
export function unconfirmedOf(e: unknown): UnconfirmedDetail | null {
  if (!(e instanceof ApiError) || e.code !== UNCONFIRMED_CODE) return null;
  const d = e.detail as Record<string, unknown>;
  return { entries: Array.isArray(d.entries) ? (d.entries as UnconfirmedDetail["entries"]) : [], worst: typeof d.worst === "string" ? (d.worst as LoadGrade) : null };
}

/** 하중 출처 오류 문구(없으면 null → 호출부 기존 문구): 하중 없음 = 항목·사유, 미지원 = 사유 */
export function loadSourceErrorText(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const d = e.detail as Record<string, unknown>;
  if (e.code === UNAVAILABLE_CODE) {
    const ids = Array.isArray(d.entry_ids) ? (d.entry_ids as string[]) : [];
    // reasons = {entry_id: 사유}(B3) — 배열로 와도 읽음
    const rs = Array.isArray(d.reasons) ? (d.reasons as unknown[]).map(String) : d.reasons && typeof d.reasons === "object" ? Object.values(d.reasons as Record<string, unknown>).map(String) : [];
    return `하중 출처를 쓸 수 없습니다 — ${rs.length ? rs.join(" / ") : e.message}${ids.length ? ` (항목 ${ids.join(", ")})` : ""}`;
  }
  if (e.code === UNSUPPORTED_CODE) return `이 하중 출처는 비드 최적화에서 지원하지 않습니다 — ${typeof d.reason === "string" ? d.reason : e.message}`;
  return null;
}
export const loadSourceOrErrorText = (e: unknown): string => loadSourceErrorText(e) ?? errorText(e);

/** 판정 상태·비교 여부 → 표식(스냅샷 load_source_check 항목용) */
export function checkEntryMark(x: { status: ValidationStatus | null; comparable: boolean | null }): TabMark {
  if (!x.status) return { text: "판정 불가", tone: "muted" };
  return markOf({ available: true, status: x.status, limits: [], comparable: x.comparable }) ?? { text: "판정 불가", tone: "muted" };
}

/** 최악 등급(B3·스냅샷 worst) → 표식(markOf 재사용): caution = "PASS ⚠", not_comparable = "<판정> · 비교용 아님", FAIL·UNDETERMINED, NO_RESULT = 검증 전. 판정은 최악 항목 상태를 따름 */
export function gradeMark(grade: LoadGrade, entries: readonly { status: ValidationStatus | null; comparable: boolean | null }[] = []): TabMark {
  if (grade === "NO_RESULT") return MARK_NOT_RUN;
  const nc = entries.find((x) => x.comparable === false);
  const status: ValidationStatus = grade === "FAIL" ? "FAIL" : grade === "UNDETERMINED" ? "UNDETERMINED" : grade === "CONDITIONAL" ? "CONDITIONAL" : grade === "not_comparable" ? nc?.status ?? "PASS" : "PASS";
  return markOf({ available: true, status, limits: grade === "caution" ? ["caution"] : [], comparable: grade === "not_comparable" || ((grade === "FAIL" || grade === "UNDETERMINED") && !!nc) ? false : true }) ?? { text: "판정 불가", tone: "muted" };
}

/** 결과 칩(순수): "하중 출처 <이름> · <최악 표식>" — 스냅샷 없으면 null(옛 작업 = 칩 없음). 최악은 load_source_check.worst(caution·not_comparable 포함), 없으면 항목에서 계산 */
export function loadSourceChipOf(key: string | null | undefined, check: LoadSourceCheck | null | undefined): { text: string; short: string; tone: TabMark["tone"] | "none"; title: string } | null {
  if (!key || isHiddenSource(key)) return null;     // v0.24.5: 숨긴 출처의 칩은 화면에 없음(스냅샷 값은 그대로)
  const label = sourceRow(key)?.label ?? key;
  const entries = check?.entries ?? [];
  const sev = (x: { status: ValidationStatus | null; comparable: boolean | null }) => (x.status === "FAIL" ? 5 : !x.status || x.status === "UNDETERMINED" ? 4 : x.comparable === false ? 3 : x.status === "LEGACY" ? 1 : x.status === "CONDITIONAL" ? 0.5 : 0);
  const worst = entries.reduce<LoadSourceCheck["entries"][number] | null>((a, x) => (!a || sev(x) > sev(a) ? x : a), null);
  const mark = check?.worst ? gradeMark(check.worst, entries) : worst ? checkEntryMark(worst) : null;
  const lines = entries.map((x) => `${x.entry_id}: ${checkEntryMark(x).text}`);
  const short = mark ? `${label} · ${mark.text}` : label;
  return { text: `하중 출처 ${short}`, short, tone: mark?.tone ?? "none", title: lines.length ? `만들 때의 ④ 판정(최악 기준)\n${lines.join("\n")}` : "하중 출처" };
}
