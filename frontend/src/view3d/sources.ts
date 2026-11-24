// v0.24.1 3D 하중 출처 표(esl_view3d_sources.md §2.1) — 화면 쪽 한 곳. 키·순서·이름 = 코어 view3d_src.KEYS · RANK_SOURCES.
// Case ③ 출처 탭·스터디 하중 정의 탭(doeTabs.LOAD_SOURCES)이 이 표의 label·title 을 같이 쓴다. 호출부는 열만 읽고 출처 이름으로 분기하지 않는다(AGENTS.md).
import type { ValidationSourceRow, ValidationSourcesOut, ValidationStatus, View3dReconOut, View3dSourceRow, View3dSourcesOut } from "../api/types";

export interface SourceRow {
  key: string;
  /** 화면 이름(탭 글자) */
  label: string;
  /** 탭 툴팁(가능할 때) */
  title: string;
  /** true = `?src` 없는 옛 URL 이 이 행(정확히 1행 — Case 전 노드 ESL) */
  legacy: boolean;
  /** manifest 실패 시 `/forces?top=100` 표 폴백 허용(전 노드 전용 자료라 legacy 행만) */
  fallback: boolean;
  /** v0.24.4 짧은 이름(그룹 안 탭 글자 — 전체 이름 = label). 없으면 label */
  short?: string;
  /** v0.24.4 그룹 키(GROUPS) — 같은 값 ≥ 2 행이 응답에 있을 때만 그룹으로 그림. 없으면 단독 탭 */
  group?: string;
  /** v0.24.4 true = 옛 서버·옛 Case 응답에 이 행이 없으면 탭을 그리지 않음(화면 = 이전 버전과 같음) */
  optional?: boolean;
  /** v0.24.4 주의 표식 문구(탭에 ⚠ + 툴팁) — 이 출처 값의 뜻에 대한 한 줄 경고 */
  caution?: string;
  /** v0.24.4 P3 비드 최적화 불가 사유(열 — 있으면 최적화 생성 화면에서 선택 불가 + 이 사유). 지그 계열은 translation+fixed 만 지원(esl_jig_case.md §9) */
  optUnsupported?: string;
}

/** v0.24.4 그룹 표(esl_jig_case.md §2.1 — 화면 거울): 그룹 머리 글자·그룹이 하나뿐일 때(옛 응답) 쓰는 단독 탭 설명 */
export const GROUPS: Readonly<Record<string, { label: string; title: string }>> = {
  jig: { label: "지그 ESL", title: "지그 ESL: 체결부(tie) 고정 + 맞춤 가압 하중으로 비교한 순위·표·3D·민감도" },
};

export const SOURCE_ROWS: readonly SourceRow[] = [
  { key: "jig", label: "지그 고정", short: "고정", group: "jig", title: "지그 고정: 체결부(tie)를 고정(법선 구속 + 3-2-1 면내) + 맞춤 가압 하중으로 비교한 순위·표·3D·민감도", legacy: false, fallback: false },
  { key: "jig_disp", label: "지그 변위", short: "변위", group: "jig", optional: true, caution: "tie 변위를 낙하 결과에서 그대로 강제", optUnsupported: "비드 최적화는 지그 고정(병진 고정)만 지원 — 변위(prescribed) 강제는 후속", title: "지그 변위: 체결부(tie)에 낙하 결과의 변위(강체 제외 순수 변위)를 강제 + 맞춤 가압 하중으로 비교한 순위·표·3D·민감도 — tie 변위를 낙하 결과에서 그대로 강제", legacy: false, fallback: false },
  { key: "jig_spring", label: "지그 스프링", short: "스프링", group: "jig", optional: true, optUnsupported: "비드 최적화는 지그 고정(병진 고정)만 지원 — 스프링 지지는 후속", title: "지그 스프링: 체결부(tie)를 낙하 결과 변위를 바닥으로 하는 스프링으로 지지 + 맞춤 가압 하중으로 비교한 순위·표·3D·민감도", legacy: false, fallback: false },
  { key: "full", label: "전 노드 ESL", title: "전 노드 ESL(기존): 전 노드 ESL 하중·3-2-1 지지 재풀이로 비교한 순위·표·3D·민감도", legacy: true, fallback: true },
  { key: "bforce", label: "경계력 ESL", title: "경계력 ESL: 낙하 해석의 접촉력·관성(·tie 체결력)으로 만든 자기평형 하중, 3-2-1 지지 재풀이로 비교한 순위·표·3D·민감도", legacy: false, fallback: false },
  { key: "fint", label: "내력 ESL", title: "내력 ESL: 낙하 해석의 노드 내력(FINT — 부품 요소 내력, 자기평형)을 하중으로 3-2-1 지지 재풀이해 비교한 순위·표·3D·민감도", legacy: false, fallback: false },
];

export const SOURCE_KEYS: readonly string[] = SOURCE_ROWS.map((r) => r.key);

// v0.24.5 화면 출처 숨김(사용자 결정 2026-11-24, esl_validate_tiers.md §11): 서버 설정 ui.hidden_sources(GET /version)를 AppProvider 가 넣는다.
// 표시만 거른다 — 계산·API·저장 산출물·보고서는 그대로(정보 삭제 없음). 값이 없으면(옛 서버·아직 못 받음) 숨김 없음 = v0.24.4 화면.
// 출처 이름 분기 없음: 어떤 키를 숨길지는 설정 한 곳, 거르는 곳은 이 표를 읽는 아래 함수들 한 곳.
let hiddenKeys: ReadonlySet<string> = new Set();
export function setHiddenSources(keys: readonly string[] | null | undefined): void {
  hiddenKeys = new Set((keys ?? []).filter((k) => SOURCE_ROWS.some((r) => r.key === k)));
}
export const isHiddenSource = (key: string | null | undefined): boolean => !!key && hiddenKeys.has(key);
/** 화면에 보이는 출처 키(표 순서) */
export const visibleSourceKeys = (): string[] => SOURCE_ROWS.filter((r) => !hiddenKeys.has(r.key)).map((r) => r.key);
/** 같은 숨김 집합이면 같은 문자열(AppProvider 가 바뀔 때만 화면을 다시 세우는 키) */
export const hiddenSourcesSig = (): string => [...hiddenKeys].sort().join(",");
export const sourceRow = (key: string | null | undefined): SourceRow | null => SOURCE_ROWS.find((r) => r.key === key) ?? null;
export const LEGACY_SOURCE: string = SOURCE_ROWS.find((r) => r.legacy)?.key ?? "full";
export const isLegacySource = (key: string | null | undefined): boolean => !key || !!sourceRow(key)?.legacy;

/** manifest 실패 시 `/forces` 표 폴백 허용: src 없음(legacy)·legacy 행만(열 `fallback`) */
export const fallbackAllowed = (key: string | null | undefined): boolean => isLegacySource(key) || !!sourceRow(key)?.fallback;

/** 비활성 사유 문구 `<이름> 불가 — <사유>`(Case·스터디 공용 형식) */
export function unavailText(label: string, why: string | null | undefined): string {
  return `${label} 불가 — ${why && why.trim() ? why : "사유 없음"}`;
}

/** 출처 탭 한 항목(SourceTabs 입력) */
export interface SourceTabItem {
  key: string;
  label: string;
  title: string;
  ok: boolean;
  /** 비활성 사유(ok 가 아닐 때) */
  why: string | null;
  /** true = 자료를 만들 수 있는 빈 탭 — 선택 가능(흐린 글자 + "+" 접미), title = why */
  add?: boolean;
  /** v0.24.4 그룹 키(GROUPS) — 있으면 SourceTabs 가 그룹으로 그림(≥2201px 한 줄 펼침 · 이하 접힘 + 팝오버). 없으면 DOM 이 v0.24.3 과 같음 */
  group?: string;
  /** v0.24.4 그룹 안 탭 글자(전체 이름 = label → aria-label) */
  short?: string;
  /** v0.24.4 주의 표식 문구(탭에 ⚠ — mark 가 있으면 mark 가 한계를 보임) */
  caution?: string;
  /** v0.24.3 ④ 검증: 탭 라벨 뒤 판정·한계 표식(선택 속성 — 없으면 DOM 이 v0.24.2 와 같음) */
  mark?: TabMark;
}

/** 탭 표식(④ 검증: 판정 + 한계) */
export interface TabMark {
  text: string;
  tone: "ok" | "bad" | "warn" | "muted";
}

/** 출처 탭 상태(순수 — Case ③·④ 검증 공용): 표 순서·이름 + 행의 가능 여부·사유. rows 없음 = null(탭을 그리지 않음) */
export function tabItemsOf(rows: readonly { key: string; available: boolean; reason: string | null }[] | null): SourceTabItem[] | null {
  if (!rows) return null;
  // optional 열 행은 응답에 없으면 그리지 않는다(옛 서버·옛 Case = 이전 화면). 그룹은 응답에 같은 group 이 ≥ 2 행일 때만(1 행 = 단독 탭, 이름 = 그룹 이름)
  const shown = SOURCE_ROWS.filter((r) => !hiddenKeys.has(r.key) && (!r.optional || rows.some((x) => x.key === r.key)));
  const count = (g: string) => shown.filter((r) => r.group === g).length;
  return shown.map((r) => {
    const row = rows.find((x) => x.key === r.key);
    const ok = !!row?.available;
    const grouped = !!r.group && count(r.group) >= 2;
    const g = r.group ? GROUPS[r.group] : undefined;
    const label = r.group && !grouped && g ? g.label : r.label;
    const title = r.group && !grouped && g ? g.title : r.title;
    const item: SourceTabItem = { key: r.key, label, title, ok, why: ok ? null : unavailText(label, row?.reason ?? "이 ESL 결과에서 출처 정보를 받지 못했습니다") };
    if (grouped) {
      item.group = r.group;
      item.short = r.short ?? r.label;
    }
    if (r.caution) item.caution = r.caution;
    return item;
  });
}

/** 스터디 하중 정의 탭용(항상 SOURCE_ROWS 전체): 표 행 → 그룹·짧은 이름·주의 속성(열만 읽음) */
export function groupFieldsOf(key: string, keys: readonly string[] = visibleSourceKeys()): Pick<SourceTabItem, "group" | "short" | "caution"> {
  const r = SOURCE_ROWS.find((x) => x.key === key);
  if (!r) return {};
  const grouped = !!r.group && SOURCE_ROWS.filter((x) => x.group === r.group && keys.includes(x.key) && !hiddenKeys.has(x.key)).length >= 2;
  return { ...(grouped ? { group: r.group, short: r.short ?? r.label } : {}), ...(r.caution ? { caution: r.caution } : {}) };
}

/** Case 출처 탭 상태(순수): 표 순서·이름 + 응답 행의 가능 여부·사유. sources 없음 = null(탭을 그리지 않음) */
export function caseTabItems(sources: View3dSourcesOut | null): SourceTabItem[] | null {
  return tabItemsOf(sources?.rows ?? null);
}

/** ④ 검증 결과가 없는 이 검증(v0.24.3 이전)의 출처 사유 코드 — 탭은 선택 가능(본문의 [검증 다시 실행]) */
export const VAL_NOT_RUN_CODE = "VAL_SRC_NOT_RUN";

const MARK_STATUS_TEXT: Record<ValidationStatus, string> = { PASS: "PASS", CONDITIONAL: "조건부 PASS", FAIL: "FAIL", UNDETERMINED: "판정 불가", LEGACY: "이전 판정" };
const MARK_STATUS_TONE: Record<ValidationStatus, TabMark["tone"]> = { PASS: "ok", CONDITIONAL: "warn", FAIL: "bad", UNDETERMINED: "muted", LEGACY: "muted" };
/** 판정 체계가 단계 판정(조건부 PASS·MAC)인가 — 새 결과 "disp_primary/2". 없음·이전 체계 = 옛 단일 기준(esl_validate_tiers.md §3.2) */
export const TIER_SCHEME = "disp_primary/2";
export const isTierScheme = (s: string | null | undefined): boolean => s === TIER_SCHEME;
const MARK_LIMIT_NOT_COMPARABLE = "비교용 아님";
const MARK_LIMIT_CAUTION = "⚠";

/** ④ 검증 탭 표식(순수): 판정 + 한계. comparable === false → "<판정> · 비교용 아님"(경고색), 한계는 있으나 비교용 → "<판정> ⚠". 결과 없음 = null */
export function markOf(row: Pick<ValidationSourceRow, "available" | "status" | "limits" | "comparable"> | null | undefined): TabMark | null {
  if (!row?.available || !row.status) return null;
  const base = MARK_STATUS_TEXT[row.status];
  if (row.comparable === false) return { text: `${base} · ${MARK_LIMIT_NOT_COMPARABLE}`, tone: "warn" };
  if (row.limits.length > 0) return { text: `${base} ${MARK_LIMIT_CAUTION}`, tone: MARK_STATUS_TONE[row.status] };
  return { text: base, tone: MARK_STATUS_TONE[row.status] };
}

/** 반력 허용치 문구(순수): 출처별 설정을 쓰는 행만 — "반력 허용치 ≤ 10 % · 주의 > 5 %"(판정에 쓴 값). 없으면 null */
export function reactionTolText(row: Pick<ValidationSourceRow, "reaction_role" | "reaction_tol" | "reaction_tol_key" | "reaction_warn"> & { scheme?: string | null } | null | undefined): string | null {
  if (!row || row.reaction_role !== "judge" || row.reaction_tol == null || !row.reaction_tol_key) return null;
  const p = (x: number) => `${Number((x * 100).toPrecision(3))} %`;
  // 새 체계(v0.24.5 §4.5): 반력 PASS ≤ 주의 문턱 · 조건부 ≤ 허용치. 옛 행 = 지금 문구 그대로
  if (isTierScheme(row.scheme) && row.reaction_warn != null) return `반력 PASS ≤ ${p(row.reaction_warn)} · 조건부 ≤ ${p(row.reaction_tol)}`;
  return `반력 허용치 ≤ ${p(row.reaction_tol)}${row.reaction_warn != null ? ` · 주의 > ${p(row.reaction_warn)}` : ""}`;
}

/** 탭 툴팁: 조건 한 줄(cond_text) + 한계 문구. 없으면 표의 정적 설명 */
function valTitle(row: ValidationSourceRow | undefined, fallback: string): string {
  const lines = [row?.cond_text, reactionTolText(row), ...(row?.limit_text ?? [])].filter((x): x is string => !!x && x.trim() !== "");
  return lines.length ? lines.join("\n") : fallback;
}

/** ④ 검증 탭 항목(순수): 표 순서·이름·사유 = tabItemsOf, + 판정·한계 표식(mark)·조건 툴팁(title). `canRun` 이면 결과 없는 탭(VAL_SRC_NOT_RUN)은 선택 가능(add) */
export function valTabItems(sources: ValidationSourcesOut | null, canRun: boolean): SourceTabItem[] | null {
  const items = tabItemsOf(sources?.rows ?? null);
  if (!items || !sources) return null;
  return items.map((it) => {
    const row = sources.rows.find((x) => x.key === it.key);
    const out: SourceTabItem = { ...it, title: valTitle(row, it.title) };
    const mark = markOf(row);
    if (mark) out.mark = mark;
    if (!it.ok && canRun && row?.code === VAL_NOT_RUN_CODE) out.add = true;
    return out;
  });
}

/** ④ 검증 기본 탭: 응답 default(가능할 때) → 가능한 첫 탭 → null */
export function defaultValSource(sources: ValidationSourcesOut | null): string | null {
  const items = tabItemsOf(sources?.rows ?? null);
  if (!items || !sources) return null;
  if (items.some((i) => i.key === sources.default && i.ok)) return sources.default;
  return items.find((i) => i.ok)?.key ?? null;
}

export function valRowOf(sources: ValidationSourcesOut | null, key: string | null): ValidationSourceRow | null {
  return (key && sources?.rows.find((r) => r.key === key)) || null;
}

/** 기본 탭: 응답 default(가능할 때) → 가능한 첫 탭 → null */
export function defaultCaseSource(sources: View3dSourcesOut | null): string | null {
  const items = caseTabItems(sources);
  if (!items || !sources) return null;
  if (items.some((i) => i.key === sources.default && i.ok)) return sources.default;
  return items.find((i) => i.ok)?.key ?? null;
}

export function sourceRowOf(sources: View3dSourcesOut | null, key: string | null): View3dSourceRow | null {
  return (key && sources?.rows.find((r) => r.key === key)) || null;
}

/** 3D 보기 4종(§2.2) */
export type ViewMode = "load" | "tgt" | "fit" | "err";
export const VIEW_MODES: readonly { key: ViewMode; label: string; title: string }[] = [
  { key: "load", label: "하중", title: "하중 색(면압·법선·크기) + 하중 화살표 — 변형 = 목표 변위" },
  { key: "tgt", label: "목표", title: "목표 변위 |u_tgt| (낙하 해석에서 강체 제거한 변형)" },
  { key: "fit", label: "응답", title: "이 하중으로 정적 풀이한 변위 |u_fit|" },
  { key: "err", label: "오차", title: "오차 |u_fit − u_tgt|" },
];
/** 응답·오차는 재현 파일이 있어야 함 */
export const needsRecon = (m: ViewMode): boolean => m === "fit" || m === "err";

export type LoadComp = "pa" | "fn" | "fmag";
export const LOAD_COMPS: readonly { key: LoadComp; label: string }[] = [
  { key: "pa", label: "면압" },
  { key: "fn", label: "법선" },
  { key: "fmag", label: "크기" },
];

const RIGID_TEXT: Record<string, string> = { kabsch: "Kabsch(S4)", linear: "선형(검증)" };

/** 재현 수치 한 줄 `재현 MAC 0.934 · umax 오차 −4.1 % · 강체 제거 <rigid>`(순수 — 시험용) */
export function reconLineText(r: Pick<View3dReconOut, "mac" | "umax_err" | "rigid">): string {
  const mac = r.mac == null ? "–" : r.mac.toFixed(3);
  const e = r.umax_err == null ? "–" : `${r.umax_err < 0 ? "−" : r.umax_err > 0 ? "+" : ""}${Math.abs(r.umax_err * 100).toFixed(1)} %`;
  return `재현 MAC ${mac} · umax 오차 ${e} · 강체 제거 ${RIGID_TEXT[r.rigid] ?? r.rigid}`;
}
