// v0.23.3 하중 정의 탭(esl_jig_view.md §7.1·§2.1 — 사용자 결정 2026-11-18 15:47·16:26): 하중 출처 표 LOAD_SOURCES 한 곳.
// 순위표·ESL별 표·3D·민감도·칩은 출처 표의 행(열)만 읽는다 — 출처 이름으로 분기하지 않음(AGENTS.md 계획 표 원칙을 화면에도).
// 출처를 빼거나(예: 전 노드 ESL) 더할 때(예: 조립체 지그) 이 표의 행만 바꾼다. 백엔드 거울 = esl/doe/stages.py RANK_SOURCES.
import { JIG_CODE_TEXT } from "../../api/doe";
import type { DoeRankRow, DoeResultOut, DoeWarning } from "../../api/types";
import { jigNoneText } from "../../components/DoeRanking";

/** 하중 출처 키 = 백엔드 rank_views 키 */
export type LoadTab = string;
/** 상태 띠 칩 종류(StatusBand 가 이 이름으로 그림) */
export type ChipKind = "jig" | "lt" | "mq" | "best_clean_mq" | "best_clean" | "nodal";
/** 3D 보기 종류(Compare3D 가 이 값으로 고름): jig = [설계 비교(지그 응답) | 지그 진단], full = 전 노드 ESL 컨투어(3-2-1),
 *  pair = 출처 응답 쌍(기준 | 안 — pairKeys 의 view3d 키, v0.24.0 경계력 ESL) */
export type View3dKind = "jig" | "full" | "pair";
/** v0.24.0 응답 쌍 3D 키(결과의 view3d 사전 이름) + 조건 줄 하중 문구 */
export interface PairKeys {
  dir: "view3d_jig" | "view3d_bf" | "view3d_fi";
  esl: "view3d_jig_esl" | "view3d_bf_esl" | "view3d_fi_esl";
  ref: "view3d_jig_ref" | "view3d_bf_ref" | "view3d_fi_ref";
  load: string;
}

/** v0.24.0 노드 힘 출처 열(esl_fint.md §8 — 경계력·내력 공용): 칩·[계산] 버튼·비활성 사유·3D 조건 줄은 이 열만 읽는다(출처 이름 분기 없음) */
export interface NodalCols {
  /** 응답 블록 키(DoeBforceOut — 등급·엔트리·한계) */
  block: "bforce" | "fint";
  /** 추가 계산 가능 여부 키 */
  add: "bforce_add" | "fint_add";
  /** API 출처 인자(POST /doe/studies/{id}/sources/{src}) */
  src: string;
  /** 버튼 문구·testid */
  addLabel: string;
  addTestid: string;
  /** 칩 testid */
  chipTestid: string;
  /** 미계산 사유 안내(Case 쪽 조건) */
  addHint: string;
  /** 칩 줄에 엔트리 내력 잔차·공유 노드를 보임(블록 값이 있을 때만 — 내력) */
  showResidual: boolean;
}

export interface LoadSource {
  key: LoadTab;
  label: string;
  /** 탭 툴팁(가능할 때) */
  title: string;
  /** 이 출처가 기본 탭인 스터디 metric_effective 값들 */
  primaryFor: readonly string[];
  /** 순위 행·기준 행에서 숨길 다른 출처 키(백엔드 drop 열 거울 — 보기 없는 옛 결과 투영에도 씀) */
  drop: readonly string[];
  /** 보기 없는 결과에서 umax·εmax 를 "–" 로(주 결과 값이 다른 출처 해석값일 때) */
  blankUmax: boolean;
  /** 이 출처 경고 코드 접두(그 밖 출처 접두에 없는 코드 = 공통) */
  warnPrefixes: readonly string[];
  /** 투영 때 비울 결과 키(다른 출처 3D·진단·블록) */
  hide: readonly (keyof DoeResultOut)[];
  /** 상태 띠 칩(순서) */
  chips: readonly ChipKind[];
  /** 3D 보기 */
  view3d: View3dKind;
  /** 응답 쌍 3D 키(jig·pair — 없으면 null) */
  pairKeys: PairKeys | null;
  /** ESL별 개선율 표 값(per_esl 의 C — 정보: 백엔드 보기가 이 키로 C 를 채움) */
  perEslKey: string;
  /** 민감도 출처(정보: rank_views[key].sensitivity) */
  sensKey: string;
  /** 기본 정렬 열(순위표) */
  sort: "score";
  /** 보기가 없을 때 탭 사유(null = 다른 출처 문구 없음) */
  unavailable: (r: DoeResultOut) => string;
  /** v0.24.0 노드 힘 출처 열(경계력·내력 — 그 밖 null) */
  nodal: NodalCols | null;
}

export const REGEN_HINT_FULL = "3D 다시 만들기로 전 노드 순위를 만들 수 있습니다";
export const REGEN_HINT_JIG = "3D 다시 만들기로 지그 탭 자료(순위·진단)를 만들 수 있습니다";

export const BF_GRADE_TEXT: Record<string, string> = { full: "full(접촉+tie−관성)", fint: "fint(내력)", contact: "contact(접촉−관성)", none: "none(자료 없음)" };
export const BF_ADD_HINT = "Case 에서 h3d 추출·ESL 을 다시 실행한 뒤 3D 머리의 [경계력 ESL 계산]으로 만들 수 있습니다";
export const FI_ADD_HINT = "낙하 Engine 에 /H3D/NODA/FINT 를 더해 재해석 → Case 에서 h3d 추출·ESL 을 다시 실행한 뒤 3D 머리의 [내력 ESL 계산]으로 만들 수 있습니다";

/** 노드 힘 출처 열 값(경계력·내력) — LOAD_SOURCES 행이 참조 */
export const NODAL_BF: NodalCols = { block: "bforce", add: "bforce_add", src: "bforce", addLabel: "경계력 ESL 계산", addTestid: "v3d-bf-add", chipTestid: "bf-chip", addHint: BF_ADD_HINT, showResidual: false };
export const NODAL_FI: NodalCols = { block: "fint", add: "fint_add", src: "fint", addLabel: "내력 ESL 계산", addTestid: "v3d-fi-add", chipTestid: "nodal-chip-fint", addHint: FI_ADD_HINT, showResidual: true };

export const LOAD_SOURCES: readonly LoadSource[] = [
  {
    key: "jig",
    label: "지그 ESL",
    title: "지그 ESL: 체결부(tie) 고정 + 맞춤 가압 하중으로 비교한 순위·표·3D·민감도",
    primaryFor: ["jig"],
    drop: ["C", "C_solve", "C_jig", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["JIG_"],
    hide: ["load_transfer", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref"],
    chips: ["jig", "best_clean"],
    view3d: "jig",
    pairKeys: { dir: "view3d_jig", esl: "view3d_jig_esl", ref: "view3d_jig_ref", load: "지그 하중" },
    perEslKey: "C_jig",
    sensKey: "rank_views.jig.sensitivity",
    sort: "score",
    unavailable: (r) => {
      const jig = r.jig ?? null;
      if (!jig) return jigNoneText(r.jig_on_clone).full;
      if (jig.status === "fallback" || jig.status === "unsupported") return `지그 순위 불가 — ${(jig.code && JIG_CODE_TEXT[jig.code]) || jig.code || jig.status}`;
      return REGEN_HINT_JIG;
    },
    nodal: null,
  },
  {
    key: "full",
    label: "전 노드 ESL",
    title: "전 노드 ESL(기존): 전 노드 ESL 하중·3-2-1 지지 재풀이로 비교한 순위·표·3D·민감도",
    primaryFor: ["solve", "lin"],
    drop: ["C", "C_jig", "score_jig", "umax_jig"],
    blankUmax: false,
    warnPrefixes: ["SM_", "LT_", "MESH_QUALITY"],
    hide: ["jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref"],
    chips: ["lt", "mq", "best_clean_mq", "best_clean"],
    view3d: "full",
    pairKeys: null,
    perEslKey: "C",
    sensKey: "rank_views.full.sensitivity",
    sort: "score",
    unavailable: () => REGEN_HINT_FULL,
    nodal: null,
  },
  {
    // v0.24.0 경계력 ESL(esl_bforce.md §8): 낙하 해석이 계산한 노드 힘(접촉력 − 관성, 관성 이완) — 같은 3-2-1 로 설계안 재풀이
    key: "bforce",
    label: "경계력 ESL",
    title: "경계력 ESL: 낙하 해석의 접촉력·관성(·tie 체결력)으로 만든 자기평형 하중, 3-2-1 지지 재풀이로 비교한 순위·표·3D·민감도",
    primaryFor: [],
    drop: ["C", "C_solve", "C_jig", "C_bf", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "umax_jig", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["BF_"],
    hide: ["load_transfer", "jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref"],
    chips: ["nodal", "best_clean"],
    view3d: "pair",
    pairKeys: { dir: "view3d_bf", esl: "view3d_bf_esl", ref: "view3d_bf_ref", load: "경계력 ESL" },
    perEslKey: "C_bf",
    sensKey: "rank_views.bforce.sensitivity",
    sort: "score",
    unavailable: (r) => nodalUnavailable(r, NODAL_BF, "경계력 ESL"),
    nodal: NODAL_BF,
  },
  {
    // v0.24.0 보완 내력 ESL(esl_fint.md §8): 낙하 해석 노드 내력 FINT(자기평형) — 같은 3-2-1 로 설계안 재풀이
    key: "fint",
    label: "내력 ESL",
    title: "내력 ESL: 낙하 해석의 노드 내력(FINT — 부품 요소 내력, 자기평형)을 하중으로 3-2-1 지지 재풀이해 비교한 순위·표·3D·민감도",
    primaryFor: [],
    drop: ["C", "C_solve", "C_jig", "C_bf", "C_fi", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "umax_jig", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["FINT_"],
    hide: ["load_transfer", "jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref"],
    chips: ["nodal", "best_clean"],
    view3d: "pair",
    pairKeys: { dir: "view3d_fi", esl: "view3d_fi_esl", ref: "view3d_fi_ref", load: "내력 ESL" },
    perEslKey: "C_fi",
    sensKey: "rank_views.fint.sensitivity",
    sort: "score",
    unavailable: (r) => nodalUnavailable(r, NODAL_FI, "내력 ESL"),
    nodal: NODAL_FI,
  },
];

/** 노드 힘 출처 탭 비활성 사유(블록 사유·데이터 등급 → 문구) — 열만 읽음 */
export function nodalUnavailable(r: DoeResultOut, n: NodalCols, label: string): string {
  const b = r[n.block] ?? null;
  if (!b) return r[n.add]?.available ? `${label} 미계산 — ${n.addHint}` : `이 방식(다른 메시 비교)은 ${label} 을 지원하지 않습니다`;
  const bad = (b.entries ?? []).filter((e) => e.reason);
  const why = bad.length ? `${bad[0].label}: 등급 ${BF_GRADE_TEXT[bad[0].grade] ?? bad[0].grade} — ${bad[0].reason}` : b.reason ?? b.status;
  return `${label} 불가 — ${why}`;
}

/** 경계력 탭 비활성 사유(호환) */
export function bfUnavailable(r: DoeResultOut): string {
  return nodalUnavailable(r, NODAL_BF, "경계력 ESL");
}

const metricEff = (r: DoeResultOut) => r.rank?.metric_effective ?? r.metric_effective ?? r.metric ?? "solve";
export const sourceOf = (key: LoadTab, sources: readonly LoadSource[] = LOAD_SOURCES) => sources.find((s) => s.key === key) ?? null;

export interface TabState {
  /** 기본 탭(가능한 탭이 없으면 null — 화면은 투영 없이 주 결과) */
  def: LoadTab | null;
  /** 표의 출처 순서 그대로 */
  keys: LoadTab[];
  ok: Record<LoadTab, boolean>;
  reason: Record<LoadTab, string | null>;
}

/** 탭 가능 여부·기본 탭: 주 출처 = metric_effective 를 primaryFor 로 가진 행(없으면 없음). 보기(rank_views)가 없으면 주 출처만 가능 */
export function tabState(r: DoeResultOut, sources: readonly LoadSource[] = LOAD_SOURCES): TabState {
  const me = metricEff(r);
  const primary = sources.find((s) => s.primaryFor.includes(me))?.key ?? null;
  const views = (r.rank_views ?? {}) as Record<string, unknown>;
  const ok: Record<string, boolean> = {};
  const reason: Record<string, string | null> = {};
  for (const s of sources) {
    ok[s.key] = !!views[s.key] || s.key === primary;
    reason[s.key] = ok[s.key] ? null : s.unavailable(r);
  }
  const def = primary && ok[primary] ? primary : sources.find((s) => ok[s.key])?.key ?? null;
  return { def, keys: sources.map((s) => s.key), ok, reason };
}

/** 경고 코드 → 출처 키(접두가 맞는 첫 행), 없으면 "common" */
export function warnTab(code: string, sources: readonly LoadSource[] = LOAD_SOURCES): LoadTab | "common" {
  return sources.find((s) => s.warnPrefixes.some((p) => code.startsWith(p)))?.key ?? "common";
}

const strip = (x: object, keys: readonly string[]): Record<string, unknown> => {
  const o: Record<string, unknown> = { ...(x as Record<string, unknown>) };
  for (const k of keys) delete o[k];
  return o;
};

/** 탭 투영: 그 출처 보기의 순위·기준·민감도·경고만 남긴 결과(출처 행의 drop·hide 열만 읽음) */
export function tabResult(r: DoeResultOut, tab: LoadTab, sources: readonly LoadSource[] = LOAD_SOURCES): DoeResultOut {
  const src = sourceOf(tab, sources);
  if (!src) return r;
  const v = ((r.rank_views ?? {}) as Record<string, NonNullable<DoeResultOut["rank_views"]>["jig"]>)[tab] ?? null;
  const warnings = r.warnings.filter((w: DoeWarning) => {
    const t = warnTab(String(w.code ?? ""), sources);
    return t === "common" || t === tab;
  });
  const hidden = Object.fromEntries(src.hide.map((k) => [k, null])) as Partial<DoeResultOut>;
  if (!v) {
    // 보기 없음(옛 사이드카 없는 결과) = 주 결과 그대로 + 다른 출처 키만 숨김(blankUmax 면 umax·εmax "–")
    const blank = src.blankUmax ? { umax: null, umax_all: null, epsmax: null, epsmax_all: null, umax_ev: null, umax_ev_all: null } : {};
    const ranking = r.ranking.map((x) => ({ ...strip(x, src.drop), ...blank }) as unknown as DoeRankRow);
    const baseline = { ...strip(r.baseline, src.drop), ...(src.blankUmax ? { umax: null, epsmax: null, umax_ev: null, umax_ev_all: null } : {}) };
    return { ...r, ...hidden, ranking, baseline: baseline as unknown as DoeResultOut["baseline"], warnings };
  }
  const me = v.metric;
  return {
    ...r,
    ...hidden,
    C_ref: v.C_ref,
    baseline: { ...(v.baseline as object), id: "d000" } as DoeResultOut["baseline"],
    n_ok: v.n_ok,
    n_skipped: v.n_skipped,
    n_failed: v.n_failed,
    ranking: v.ranking as unknown as DoeRankRow[],
    per_esl_inline: v.per_esl_inline,
    sensitivity: (v.sensitivity ?? null) as DoeResultOut["sensitivity"],
    sensitivity_reason: v.sensitivity_reason ?? null,
    metric_effective: me as DoeResultOut["metric_effective"],
    rank: r.rank ? { ...r.rank, metric_effective: me as NonNullable<DoeResultOut["rank"]>["metric_effective"] } : r.rank,
    ...(r.summary ? { summary: { ...r.summary, best_clean: v.best_clean ?? null } } : {}),
    warnings,
  };
}
