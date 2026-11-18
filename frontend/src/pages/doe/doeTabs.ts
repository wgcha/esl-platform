// v0.23.3 하중 정의 탭(esl_jig_view.md §7.1·§2.1 — 사용자 결정 2026-11-18 15:47·16:26): 하중 출처 표 LOAD_SOURCES 한 곳.
// 순위표·ESL별 표·3D·민감도·칩은 출처 표의 행(열)만 읽는다 — 출처 이름으로 분기하지 않음(AGENTS.md 계획 표 원칙을 화면에도).
// 출처를 빼거나(예: 전 노드 ESL) 더할 때(예: 조립체 지그) 이 표의 행만 바꾼다. 백엔드 거울 = esl/doe/stages.py RANK_SOURCES.
import { JIG_CODE_TEXT } from "../../api/doe";
import type { DoeRankRow, DoeResultOut, DoeWarning } from "../../api/types";
import { jigNoneText } from "../../components/DoeRanking";

/** 하중 출처 키 = 백엔드 rank_views 키 */
export type LoadTab = string;
/** 상태 띠 칩 종류(StatusBand 가 이 이름으로 그림) */
export type ChipKind = "jig" | "lt" | "mq" | "best_clean_mq" | "best_clean";
/** 3D 보기 종류(Compare3D 가 이 값으로 고름): jig = [설계 비교(지그 응답) | 지그 진단], full = 전 노드 ESL 컨투어(3-2-1) */
export type View3dKind = "jig" | "full";

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
  /** ESL별 개선율 표 값(per_esl 의 C — 정보: 백엔드 보기가 이 키로 C 를 채움) */
  perEslKey: string;
  /** 민감도 출처(정보: rank_views[key].sensitivity) */
  sensKey: string;
  /** 기본 정렬 열(순위표) */
  sort: "score";
  /** 보기가 없을 때 탭 사유(null = 다른 출처 문구 없음) */
  unavailable: (r: DoeResultOut) => string;
}

export const REGEN_HINT_FULL = "3D 다시 만들기로 전 노드 순위를 만들 수 있습니다";
export const REGEN_HINT_JIG = "3D 다시 만들기로 지그 탭 자료(순위·진단)를 만들 수 있습니다";

export const LOAD_SOURCES: readonly LoadSource[] = [
  {
    key: "jig",
    label: "지그 ESL",
    title: "지그 ESL: 체결부(tie) 고정 + 맞춤 가압 하중으로 비교한 순위·표·3D·민감도",
    primaryFor: ["jig"],
    drop: ["C", "C_solve", "C_jig", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["JIG_"],
    hide: ["load_transfer"],
    chips: ["jig", "best_clean"],
    view3d: "jig",
    perEslKey: "C_jig",
    sensKey: "rank_views.jig.sensitivity",
    sort: "score",
    unavailable: (r) => {
      const jig = r.jig ?? null;
      if (!jig) return jigNoneText(r.jig_on_clone).full;
      if (jig.status === "fallback" || jig.status === "unsupported") return `지그 순위 불가 — ${(jig.code && JIG_CODE_TEXT[jig.code]) || jig.code || jig.status}`;
      return REGEN_HINT_JIG;
    },
  },
  {
    key: "full",
    label: "전 노드 ESL",
    title: "전 노드 ESL(기존): 전 노드 ESL 하중·3-2-1 지지 재풀이로 비교한 순위·표·3D·민감도",
    primaryFor: ["solve", "lin"],
    drop: ["C", "C_jig", "score_jig", "umax_jig"],
    blankUmax: false,
    warnPrefixes: ["SM_", "LT_", "MESH_QUALITY"],
    hide: ["jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag"],
    chips: ["lt", "mq", "best_clean_mq", "best_clean"],
    view3d: "full",
    perEslKey: "C",
    sensKey: "rank_views.full.sensitivity",
    sort: "score",
    unavailable: () => REGEN_HINT_FULL,
  },
];

const metricEff = (r: DoeResultOut) => r.rank?.metric_effective ?? r.metric_effective ?? null;
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
  const me = metricEff(r) ?? "";
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
    const blank = src.blankUmax ? { umax: null, umax_all: null, epsmax: null, epsmax_all: null } : {};
    const ranking = r.ranking.map((x) => ({ ...strip(x, src.drop), ...blank }) as unknown as DoeRankRow);
    const baseline = { ...strip(r.baseline, src.drop), ...(src.blankUmax ? { umax: null, epsmax: null } : {}) };
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
