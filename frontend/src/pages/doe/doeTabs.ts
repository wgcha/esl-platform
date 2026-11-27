// v0.23.3 하중 정의 탭(esl_jig_view.md §7.1·§2.1 — 사용자 결정 2026-11-18 15:47·16:26): 하중 출처 표 LOAD_SOURCES 한 곳.
// 순위표·ESL별 표·3D·민감도·칩은 출처 표의 행(열)만 읽는다 — 출처 이름으로 분기하지 않음(AGENTS.md 계획 표 원칙을 화면에도).
// 출처를 빼거나(예: 전 노드 ESL) 더할 때(예: 조립체 지그) 이 표의 행만 바꾼다. 백엔드 거울 = esl/doe/stages.py RANK_SOURCES.
import { JIG_CODE_TEXT } from "../../api/doe";
import type { DoeCountItem, DoeRankRow, DoeResultOut, DoeWarning } from "../../api/types";
import { jigNoneText } from "../../components/DoeRanking";
import { SOURCE_ROWS, isHiddenSource } from "../../view3d/sources";

const SR = (key: string) => {
  const r = SOURCE_ROWS.find((x) => x.key === key);
  if (!r) throw new Error(`SOURCE_ROWS 에 ${key} 없음`);
  return r;
};

/** 하중 출처 키 = 백엔드 rank_views 키 */
export type LoadTab = string;
/** 상태 띠 칩 종류(StatusBand 가 이 이름으로 그림) */
export type ChipKind = "jig" | "lt" | "mq" | "best_clean_mq" | "best_clean" | "nodal";
/** 3D 보기 종류(Compare3D 가 이 값으로 고름): jig = [설계 비교(지그 응답) | 지그 진단], full = 전 노드 ESL 컨투어(3-2-1),
 *  pair = 출처 응답 쌍(기준 | 안 — pairKeys 의 view3d 키, v0.24.0 경계력 ESL) */
export type View3dKind = "jig" | "full" | "pair";
/** v0.24.0 응답 쌍 3D 키(결과의 view3d 사전 이름) + 조건 줄 하중 문구 */
export interface PairKeys {
  dir: "view3d_jig" | "view3d_bf" | "view3d_fi" | "view3d_jd" | "view3d_js";
  esl: "view3d_jig_esl" | "view3d_bf_esl" | "view3d_fi_esl" | "view3d_jd_esl" | "view3d_js_esl";
  ref: "view3d_jig_ref" | "view3d_bf_ref" | "view3d_fi_ref" | "view3d_jd_ref" | "view3d_js_ref";
  load: string;
  /** v0.24.6 3D 조건 줄 지지 문구 틀(§8.3) — {tie} = jig.tie_dofs 문구(TIE_DOFS_TEXT). 화면은 이 열만 읽음 */
  support: string;
  /** v0.24.6 3D 변위 색 라벨(§8.3) */
  disp: string;
}

/** 지그 tie 자유도 → 조건 줄 문구({tie} 자리) */
export const TIE_DOFS_TEXT: Record<string, string> = { normal: "법선", translation: "병진" };
/** 조건 줄 지지 문구 완성: {tie} 를 결과 jig.tie_dofs 로(없으면 "–") */
export const supportText = (tpl: string, tie: string | null | undefined): string => tpl.replace("{tie}", (tie && TIE_DOFS_TEXT[tie]) || "–");

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

/** v0.24.1 자료 만들기 열(esl_view3d_sources.md §2.4·§6.3): POST /doe/studies/{id}/sources/{src}. 가능 여부는 결과 source_add[key](옛 거울 legacy 키 폴백) */
export interface SourceAddCols {
  src: string;
  /** 버튼 문구·testid */
  label: string;
  testid: string;
  /** 미계산 사유 안내(탭 title·빈 칸 문구) */
  hint: string;
  /** 버튼 title(가능할 때) */
  title: string;
  /** 옛 거울 키(source_add 가 없는 응답 폴백 — 새 출처(v0.24.6 jd·js)는 옛 응답이 없으므로 null) */
  legacy: "view3d_regen" | "bforce_add" | "fint_add" | null;
}

/** v0.24.1 재현 진단 열: jigdiag = 지그 진단(JigDiag) · sidecar = 범용 ReconDiag(결과 키 = 엔트리 → 폴더) · null = 해당 없음(V3D_RECON_NA) */
export type ReconCols = { kind: "jigdiag" } | { kind: "sidecar"; key: "view3d_bf_recon" | "view3d_fi_recon" } | null;

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
  /** v0.24.1 재현 진단 열 */
  recon: ReconCols;
  /** v0.24.1 자료 만들기 열(그 밖 null) */
  add: SourceAddCols | null;
  /** v0.24.6 지그 방식 열: true = 탭 사유·사유 줄을 jigMethodState(응답 jig.methods)로 고름(§9) */
  jigMethod: boolean;
}

/** v0.24.4 지그 방식 행(jig_disp·jig_spring)이 순위·진단에서 숨길 키(다른 출처 값 — 백엔드 VIEW_DROP_JIG 거울) */
const JIG_VIEW_DROP = ["C", "C_solve", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "umax_jig", "basis", "sm_warn"] as const;
const JIG_VIEW_HIDE: readonly (keyof DoeResultOut)[] = ["load_transfer", "jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref"];
/** v0.24.6 지그 방식 탭 상태 4가지(esl_viewer_hv.md §9.1): 화면 문구는 이 표 한 곳(JIG_STATE_TEXT) — 다른 곳에 글자를 두지 않는다 */
export type JigMethodStateKind = "no_jig" | "not_planned" | "failed" | "no_view";
export const JIG_DETAIL_MAX = 120;
export const JIG_STATE_TEXT = {
  /** r.jig 없음 — 지그를 계산하지 않은 스터디(복제하면 계산하는지는 jig_on_clone) */
  no_jig: { why: "이 스터디는 지그를 계산하지 않았습니다", clone: " — 복제하면 지그를 계산합니다" },
  /** 옛 단일 경로(고정만)·방식 목록에 없음 = 현재 설정으로 복제 / 모드가 지그 ESL 을 계산하지 않음(계획 열 jig_plan = none — 복제해도 같음, v0.24.5 #88 후속) */
  not_planned: {
    why: (label: string) => `이 스터디에서 계산하지 않은 방식입니다: ${label} — 복제(현재 설정 rank.jig.methods)로 다시 계산`,
    /** jig_plan none: onClone 없음(null — 옛 서버) = 옛 문구 / v0.24.8 응답 jig_on_clone 참 = 복제하면 격자 매핑 계산 · 거짓 = 설정 rank.jig_grid 꺼짐(esl_jig_grid_map.md §5) */
    whyMode: (label: string, onClone?: boolean | null) =>
      onClone == null
        ? `이 모드는 지그 ESL 을 계산하지 않습니다: ${label} — 안·형상마다 다른 메시를 비교하는 모드라 복제해도 같습니다`
        : `이 스터디는 이 모드에서 지그 ESL 을 계산하지 않았습니다(v0.24.8 이전 스냅샷): ${label} — ${onClone ? "복제하면 Case 지그를 격자 매핑해 계산합니다" : "설정 bead_doe.rank.jig_grid 가 꺼져 있어 복제해도 계산하지 않습니다"}`,
  },
  /** 계산했지만 실패(methods[key].status ≠ ok) — 마우스 없이 보이는 줄에 다음 행동을 덧붙임 */
  failed: {
    why: (label: string, code: string, detail: string) => `${label} 계산 실패: ${code}${detail ? ` — ${detail}` : ""}`,
    next: " — 3D 다시 만들기로는 고칠 수 없습니다. 원인을 고친 뒤 복제로 다시 계산",
  },
  /** 계산은 됐는데 순위 보기가 없음(기준 d000 의 C 값 없음) */
  no_view: {
    why: (label: string, col: string, warn: string) => `${label}: 계산됐지만 기준(d000) 값 ${col} 가 없어 순위를 만들지 못했습니다${warn ? ` — ${warn}` : ""}`,
  },
} as const;

export interface JigMethodState {
  /** 4상태 + ok(계산됨·보기 있음 — 탭 가능, 사유 없음) */
  state: JigMethodStateKind | "ok";
  /** 탭 사유(탭 title·sr-only·초점 줄·팝오버 — detail 은 120자) */
  why: string;
  /** 전체 문구(title — detail 전체) */
  title: string;
  /** 마우스 없이 보이는 줄(failed·no_view 만, 그 밖 null) */
  note: string | null;
}

/** 지그 방식 탭 상태(응답만 읽음 — 모드·출처 이름 비교 없음). 판정 순서: 계획 열 none → r.jig 없음 → methods 없음/키 없음 → 실패 → 보기 없음 */
export function jigMethodState(r: DoeResultOut, key: string): JigMethodState {
  const label = SR(key).label;
  const plain = (state: JigMethodStateKind, why: string): JigMethodState => ({ state, why, title: why, note: null });
  const T = JIG_STATE_TEXT;
  if (r.jig_plan === "none") return plain("not_planned", T.not_planned.whyMode(label, r.jig_on_clone));
  if (!r.jig) return plain("no_jig", T.no_jig.why + (r.jig_on_clone ? T.no_jig.clone : ""));
  const m = r.jig.methods?.[key] ?? null;
  if (!m) return plain("not_planned", T.not_planned.why(label));
  if (m.status !== "ok") {
    const detail = (m.detail ?? "").trim();
    const full = T.failed.why(label, m.code ?? "–", detail);
    const why = detail.length > JIG_DETAIL_MAX ? T.failed.why(label, m.code ?? "–", `${detail.slice(0, JIG_DETAIL_MAX)}…`) : full;
    return { state: "failed", why, title: full, note: why + T.failed.next };
  }
  const views = (r.rank_views ?? {}) as Record<string, unknown>;
  if (!views[key]) {
    const why = T.no_view.why(label, sourceOf(key)?.perEslKey ?? key, (m.warnings ?? [])[0] ?? "");
    return { state: "no_view", why, title: why, note: why };
  }
  return { state: "ok", why: "", title: "", note: null };
}

/** v0.24.6 검증 수정: 지그 방식 행이 계산됐는데 순위 보기가 없음(no_view) = 3D 다시 만들기가 보기를 만들 수 없음. 탭 add 와 3D 행 버튼이 같은 이 판정 하나를 쓴다 */
export function sourceNoView(r: DoeResultOut, s: LoadSource): boolean {
  return !!s.jigMethod && jigMethodState(r, s.key).state === "no_view";
}

/** 지그 방식 사유 줄(열 jigMethod 가 참인 출처만 — failed·no_view). 전체 문구 = title */
export function jigMethodNote(r: DoeResultOut, s: LoadSource): { text: string; title: string; state: JigMethodState["state"] } | null {
  if (!s.jigMethod) return null;
  const st = jigMethodState(r, s.key);
  return st.note ? { text: st.note, title: st.title, state: st.state } : null;
}
/** 지그 방식 탭 사유 — 보기가 없을 때(응답 jig·jig.methods·jig_plan 으로 고름) */
const jigMethodUnavailable = (r: DoeResultOut, key: string): string => jigMethodState(r, key).why;

/** 지그 3D 다시 만들기 버튼 문구 — 문구 표 한 곳(지그 행·지그 변위·스프링 행 공용) */
export const JIG_REGEN_LABEL = "지그 3D 다시 만들기";
export const REGEN_HINT_FULL = "3D 다시 만들기로 전 노드 순위를 만들 수 있습니다";
export const REGEN_HINT_JIG = "3D 다시 만들기로 지그 탭 자료(순위·진단)를 만들 수 있습니다";

export const BF_GRADE_TEXT: Record<string, string> = { full: "full(접촉+tie−관성)", fint: "fint(내력)", contact: "contact(접촉−관성)", none: "none(자료 없음)" };
export const BF_ADD_HINT = "Case 에서 h3d 추출·ESL 을 다시 실행한 뒤 3D 머리의 [경계력 ESL 계산]으로 만들 수 있습니다";
export const FI_ADD_HINT = "낙하 Engine 에 /H3D/NODA/FINT 를 더해 재해석 → Case 에서 h3d 추출·ESL 을 다시 실행한 뒤 3D 머리의 [내력 ESL 계산]으로 만들 수 있습니다";

/** 노드 힘 출처 열 값(경계력·내력) — LOAD_SOURCES 행이 참조 */
export const NODAL_BF: NodalCols = { block: "bforce", add: "bforce_add", src: "bforce", addLabel: "경계력 ESL 계산", addTestid: "v3d-bf-add", chipTestid: "bf-chip", addHint: BF_ADD_HINT, showResidual: false };
export const NODAL_FI: NodalCols = { block: "fint", add: "fint_add", src: "fint", addLabel: "내력 ESL 계산", addTestid: "v3d-fi-add", chipTestid: "nodal-chip-fint", addHint: FI_ADD_HINT, showResidual: true };

export const V3D_RECON_NA_TEXT = "목표 변위(sm_ref)가 이 하중의 응답 자체 — 재현 비교 해당 없음";
export const V3D_RECON_NONE_TEXT = (addLabel: string | null) => `재현 진단 없음${addLabel ? ` — [${addLabel}]로 다시 계산하면 생깁니다` : ""}`;

/** 노드 힘 출처 자료 만들기 열 값 — NodalCols 의 값을 그대로 옮김(testid·문구 동일) */
const addOfNodal = (n: NodalCols): SourceAddCols => ({
  src: n.src,
  label: n.addLabel,
  testid: n.addTestid,
  hint: n.addHint,
  title: `형상 생성 없이 안마다 ${n.addLabel.replace(/ 계산$/, "")} 하중으로 선형 풀이해 [${n.addLabel.replace(/ 계산$/, "")}] 탭 자료를 만듭니다(기존 결과 파일 그대로). ${n.addHint}`,
  legacy: n.add,
});
/** v0.24.6 지그 변위·스프링 3D 다시 만들기(§8.2 — 지그 행과 같은 작업, 한 작업이 빠진 방식 3D 를 모두 만든다) */
const addOfJigMethod = (src: "jig_disp" | "jig_spring", testid: string): SourceAddCols => ({
  src,
  label: JIG_REGEN_LABEL,
  testid,
  hint: "3D 다시 만들기로 지그 변위·스프링 3D 를 만들 수 있습니다",
  title: "계산된 지그 방식의 응답 3D 만 다시 만듭니다(순위·결과 파일 그대로, 기존 작업 큐). 한 번에 빠진 방식 3D 를 모두 만듭니다",
  legacy: null,
});
const ADD_JIG: SourceAddCols = { src: "jig", label: JIG_REGEN_LABEL, testid: "v3d-regen", hint: REGEN_HINT_JIG, title: "지그 응답 3D·지그 진단 3D·하중 정의 탭 자료만 다시 만듭니다(순위·결과 파일 그대로, 기존 작업 큐)", legacy: "view3d_regen" };

export const LOAD_SOURCES: readonly LoadSource[] = [
  {
    key: "jig",
    label: SR("jig").label,
    title: SR("jig").title,
    primaryFor: ["jig"],
    drop: ["C", "C_solve", "C_jig", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["JIG_"],
    hide: ["load_transfer", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref", "view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref"],
    chips: ["jig", "best_clean"],
    view3d: "jig",
    pairKeys: { dir: "view3d_jig", esl: "view3d_jig_esl", ref: "view3d_jig_ref", load: "지그 하중", support: "tie 고정", disp: "변위 |u| (mm) — 지그 고정(강체 성분 없음)" },
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
    recon: { kind: "jigdiag" },
    add: ADD_JIG,
    jigMethod: false,
  },
  {
    // v0.24.4 지그 강제 변위(esl_jig_case.md §6.1): 스터디 계산 = P2c(새 스냅샷만 rank_views.jig_disp). 3D 칸 = 후속(R-JIGC-2)
    key: "jig_disp",
    label: SR("jig_disp").label,
    title: SR("jig_disp").title,
    primaryFor: ["jd"],
    drop: [...JIG_VIEW_DROP, "C_jig", "umax_jig", "C_js", "umax_js"],
    blankUmax: true,
    warnPrefixes: [],
    hide: [...JIG_VIEW_HIDE, "view3d_js", "view3d_js_esl", "view3d_js_ref"],
    chips: ["best_clean"],
    view3d: "pair",
    pairKeys: { dir: "view3d_jd", esl: "view3d_jd_esl", ref: "view3d_jd_ref", load: "지그 변위", support: "지그 tie {tie} 강제 변위 + 3-2-1 면내", disp: "변위 |u| (mm) — 지그 강제 변위 + 3-2-1 면내" },
    perEslKey: "C_jd",
    sensKey: "rank_views.jig_disp.sensitivity",
    sort: "score",
    unavailable: (r) => jigMethodUnavailable(r, "jig_disp"),
    nodal: null,
    recon: null,
    add: addOfJigMethod("jig_disp", "v3d-regen-jd"),
    jigMethod: true,
  },
  {
    // v0.24.4 지그 스프링(§6.1) — 위와 같은 규칙(키 js)
    key: "jig_spring",
    label: SR("jig_spring").label,
    title: SR("jig_spring").title,
    primaryFor: ["js"],
    drop: [...JIG_VIEW_DROP, "C_jig", "umax_jig", "C_jd", "umax_jd"],
    blankUmax: true,
    warnPrefixes: [],
    hide: [...JIG_VIEW_HIDE, "view3d_jd", "view3d_jd_esl", "view3d_jd_ref"],
    chips: ["best_clean"],
    view3d: "pair",
    pairKeys: { dir: "view3d_js", esl: "view3d_js_esl", ref: "view3d_js_ref", load: "지그 스프링", support: "지그 tie {tie} 스프링 + 3-2-1 면내", disp: "변위 |u| (mm) — 지그 스프링 + 3-2-1 면내" },
    perEslKey: "C_js",
    sensKey: "rank_views.jig_spring.sensitivity",
    sort: "score",
    unavailable: (r) => jigMethodUnavailable(r, "jig_spring"),
    nodal: null,
    recon: null,
    add: addOfJigMethod("jig_spring", "v3d-regen-js"),
    jigMethod: true,
  },
  {
    key: "full",
    label: SR("full").label,
    title: SR("full").title,
    primaryFor: ["solve", "lin"],
    drop: ["C", "C_jig", "score_jig", "umax_jig"],
    blankUmax: false,
    warnPrefixes: ["SM_", "LT_", "MESH_QUALITY"],
    hide: ["jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref", "view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref"],
    chips: ["lt", "mq", "best_clean_mq", "best_clean"],
    view3d: "full",
    pairKeys: null,
    perEslKey: "C",
    sensKey: "rank_views.full.sensitivity",
    sort: "score",
    unavailable: () => REGEN_HINT_FULL,
    nodal: null,
    recon: null,
    add: null,
    jigMethod: false,
  },
  {
    // v0.24.0 경계력 ESL(esl_bforce.md §8): 낙하 해석이 계산한 노드 힘(접촉력 − 관성, 관성 이완) — 같은 3-2-1 로 설계안 재풀이
    key: "bforce",
    label: SR("bforce").label,
    title: SR("bforce").title,
    primaryFor: [],
    drop: ["C", "C_solve", "C_jig", "C_bf", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "umax_jig", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["BF_"],
    hide: ["load_transfer", "jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "fint", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref", "view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref"],
    chips: ["nodal", "best_clean"],
    view3d: "pair",
    pairKeys: { dir: "view3d_bf", esl: "view3d_bf_esl", ref: "view3d_bf_ref", load: "경계력 ESL", support: "3-2-1", disp: "변위 |u| (mm) — 3-2-1(자기평형 하중)" },
    perEslKey: "C_bf",
    sensKey: "rank_views.bforce.sensitivity",
    sort: "score",
    unavailable: (r) => nodalUnavailable(r, NODAL_BF, "경계력 ESL"),
    nodal: NODAL_BF,
    recon: { kind: "sidecar", key: "view3d_bf_recon" },
    add: addOfNodal(NODAL_BF),
    jigMethod: false,
  },
  {
    // v0.24.0 보완 내력 ESL(esl_fint.md §8): 낙하 해석 노드 내력 FINT(자기평형) — 같은 3-2-1 로 설계안 재풀이
    key: "fint",
    label: SR("fint").label,
    title: SR("fint").title,
    primaryFor: [],
    drop: ["C", "C_solve", "C_jig", "C_bf", "C_fi", "score_solve", "score_jig", "score_lin", "imbalance_max", "rho_min", "rho_max", "umax_def", "umax_jig", "basis", "sm_warn"],
    blankUmax: true,
    warnPrefixes: ["FINT_"],
    hide: ["load_transfer", "jig", "view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_diag", "bforce", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref", "view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref"],
    chips: ["nodal", "best_clean"],
    view3d: "pair",
    pairKeys: { dir: "view3d_fi", esl: "view3d_fi_esl", ref: "view3d_fi_ref", load: "내력 ESL", support: "3-2-1", disp: "변위 |u| (mm) — 3-2-1(자기평형 하중)" },
    perEslKey: "C_fi",
    sensKey: "rank_views.fint.sensitivity",
    sort: "score",
    unavailable: (r) => nodalUnavailable(r, NODAL_FI, "내력 ESL"),
    nodal: NODAL_FI,
    recon: { kind: "sidecar", key: "view3d_fi_recon" },
    add: addOfNodal(NODAL_FI),
    jigMethod: false,
  },
];

/** v0.24.5 화면에 보이는 하중 출처(설정 ui.hidden_sources 가 거른 것) — 탭·순위·3D·칩·사유 줄은 이것만 읽는다 */
export const visibleLoadSources = (): readonly LoadSource[] => LOAD_SOURCES.filter((s) => !isHiddenSource(s.key));
/** 주 출처(순위 기준)가 숨긴 출처이면 그 행(없으면 null) — 화면이 한 줄 알림을 낸다 */
export const hiddenPrimaryOf = (r: DoeResultOut): LoadSource | null => {
  const me = metricEff(r);
  return LOAD_SOURCES.find((s) => isHiddenSource(s.key) && s.primaryFor.includes(me)) ?? null;
};

/** 자료 만들기 가능 여부(행 add 열): 결과 source_add[key], 없으면 옛 거울 키(응답 폴백) */
export function sourceAddOf(r: DoeResultOut, s: LoadSource): { available: boolean; allowed: boolean; reason?: string | null } | null {
  if (!s.add) return null;
  return r.source_add?.[s.key] ?? (s.add.legacy ? r[s.add.legacy] : null) ?? null;
}

/** 노드 힘 출처 탭 비활성 사유(블록 사유·데이터 등급 → 문구) — 열만 읽음 */
export function nodalUnavailable(r: DoeResultOut, n: NodalCols, label: string): string {
  const b = r[n.block] ?? null;
  if (!b) return r[n.add]?.available ? `${label} 미계산 — ${n.addHint}` : `이 방식(다른 메시 비교)은 ${label} 을 지원하지 않습니다`;
  const bad = (b.entries ?? []).filter((e) => e.reason);
  const why = bad.length ? `${bad[0].label}: 등급 ${BF_GRADE_TEXT[bad[0].grade] ?? bad[0].grade} — ${bad[0].reason}` : b.reason ?? b.status;
  return `${label} 불가 — ${why}`;
}

/** v0.24.1 현장 피드백: 노드 힘 출처 블록(result.bforce·fint)이 있는데 status 가 ok 가 아니면(예: BF_NOT_FOUND) 마우스 없이 보이는 한 줄 —
 *  nodalUnavailable 문구 + 다음 행동. 블록 없음·ok = null(열 nodal·add 만 읽음) */
export function nodalNote(r: DoeResultOut, s: LoadSource): string | null {
  const n = s.nodal;
  const b = n ? r[n.block] ?? null : null;
  if (!n || !b || b.status === "ok") return null;
  const sa = sourceAddOf(r, s);
  const denied = !!sa && sa.allowed === false;
  const lab = s.add?.label ?? "";
  const last = lab.charCodeAt(lab.length - 1) - 0xac00;
  const josa = last >= 0 && last < 11172 && last % 28 === 0 ? "를" : "을";
  // 권한 없음: "다시 누르세요" 대신 작성자·관리자 요청 안내 + 서버 사유(권한은 source_add[키].allowed — 옛 거울 키 폴백)
  const next = !s.add
    ? ""
    : denied
      ? ` → Case ③ 에서 h3d 추출부터 ESL 을 다시 실행한 뒤 작성자·관리자에게 [${lab}]${josa} 요청하세요${sa?.reason ? ` (${sa.reason})` : ""}`
      : ` → Case ③ 에서 h3d 추출부터 ESL 을 다시 실행한 뒤 [${lab}] 다시 누르세요`;
  return nodalUnavailable(r, n, s.label) + next;
}

/** 경계력 탭 비활성 사유(호환) */
export function bfUnavailable(r: DoeResultOut): string {
  return nodalUnavailable(r, NODAL_BF, "경계력 ESL");
}

/** v0.25.2 §4.1 결과 개수 라벨 — 서버 esl.doe.rank.COUNT_LABELS 거울(API counts 가 없는 옛 결과에서만 씀). 모르는 키는 키 그대로 */
export const COUNT_LABELS: Record<string, string> = {
  ok: "성공",
  mesh: "메시",
  size: "크기/정렬",
  solve: "해석",
  morph: "모핑",
  collision: "스킵(충돌)",
  fixed: "스킵(고정)",
  geom: "스킵(형상)",
  jig: "지그 매핑 제외",
  jd: "지그 매핑 제외",
  js: "지그 매핑 제외",
  bf: "경계력 없음",
  fi: "내력 없음",
  sm: "강성 지표 없음",
  ref: "참고용",
};
/** 결과 개수 항목: API counts(새 결과) 그대로, 없으면 n_ok + n_skipped·n_failed 의 0 아닌 키 + n_ref(> 0) 로 같은 표시를 계산(옛 결과) */
export function countItems(r: Pick<DoeResultOut, "n_ok" | "n_skipped" | "n_failed"> & { counts?: DoeCountItem[] | null; n_ref?: number | null }): DoeCountItem[] {
  if (r.counts?.length) return r.counts;
  const out: DoeCountItem[] = [{ key: "ok", label: COUNT_LABELS.ok, n: r.n_ok }];
  for (const [k, n] of [...Object.entries(r.n_skipped ?? {}), ...Object.entries(r.n_failed ?? {})]) if (n) out.push({ key: k, label: COUNT_LABELS[k] ?? k, n });
  if (r.n_ref) out.push({ key: "ref", label: COUNT_LABELS.ref, n: r.n_ref });
  return out;
}
/** 결과 카드 제목 꼬리: " · 지그 매핑 제외 1 · 참고용 1"(성공 뺀 0 아닌 항목 — 없으면 "" = 지금과 같은 글자) */
export function countTail(r: Parameters<typeof countItems>[0]): string {
  return countItems(r)
    .filter((x) => x.key !== "ok" && x.n > 0)
    .map((x) => ` · ${x.label} ${x.n}`)
    .join("");
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
  /** v0.24.1 보기 없음 ∧ 자료 만들기 가능(available) ∧ allowed — 선택 가능한 빈 탭(본문 = 사유 + 버튼 1개) */
  add: Record<LoadTab, boolean>;
}

/** 탭 가능 여부·기본 탭: 주 출처 = metric_effective 를 primaryFor 로 가진 행(없으면 없음). 보기(rank_views)가 없으면 주 출처만 가능 */
export function tabState(r: DoeResultOut, sources: readonly LoadSource[] = LOAD_SOURCES): TabState {
  const me = metricEff(r);
  const primary = sources.find((s) => s.primaryFor.includes(me))?.key ?? null;
  const views = (r.rank_views ?? {}) as Record<string, unknown>;
  const ok: Record<string, boolean> = {};
  const reason: Record<string, string | null> = {};
  const add: Record<string, boolean> = {};
  for (const s of sources) {
    ok[s.key] = !!views[s.key] || s.key === primary;
    reason[s.key] = ok[s.key] ? null : s.unavailable(r);
    const sa = sourceAddOf(r, s);
    // v0.24.6 통합: 지그 방식 행이 계산됐는데 순위 보기(rank_views)가 없으면(no_view — 예: view3d.jig_diag 끔) 3D 다시 만들기는 보기를
    // 만들 수 없다(코어 _jig_extras 는 그 조건에서 아무것도 쓰지 않음) — 빈 탭의 [다시 만들기] 버튼을 두지 않고 사유 줄만 보인다
    const noView = sourceNoView(r, s);
    add[s.key] = !ok[s.key] && !noView && !!sa?.available && sa.allowed;
    // 만들 수 있는데 권한이 없거나 작업 중이면 탭 비활성 + 그 사유를 덧붙임(정보 삭제 없음)
    if (!ok[s.key] && sa?.available && !sa.allowed && sa.reason) reason[s.key] = `${reason[s.key]} (${sa.reason})`;
  }
  let def = primary && ok[primary] ? primary : sources.find((s) => ok[s.key])?.key ?? null;
  // v0.25.2 §4.2: 주 출처 탭의 순위가 0 행이고 다른 탭에 순위가 있으면 출처 표 순서에서 처음 그런 탭을 기본으로(안내는 빈 탭 본문)
  if (def && def === primary && rankRows(r, def, primary) === 0) def = sources.find((s) => s.key !== primary && ok[s.key] && rankRows(r, s.key, primary) > 0)?.key ?? def;
  return { def, keys: sources.map((s) => s.key), ok, reason, add };
}

/** 한 탭의 순위 행 수: 보기(rank_views[key]) 가 있으면 그 순위, 없으면 주 출처 = 주 결과 순위, 그 밖 = 0 */
export function rankRows(r: DoeResultOut, key: LoadTab, primary: LoadTab | null): number {
  const v = ((r.rank_views ?? {}) as Record<string, { ranking?: unknown[] } | null | undefined>)[key];
  return v ? v.ranking?.length ?? 0 : key === primary ? r.ranking.length : 0;
}

/** v0.25.2 §4.2 빈 탭 안내: 이 탭 순위가 0 행이고 순위 있는 다른 탭이 있으면 그 탭(출처 표 순서 처음). 없으면 null */
export function otherRankedTab(r: DoeResultOut, cur: LoadTab, sources: readonly LoadSource[] = LOAD_SOURCES): LoadSource | null {
  const primary = sources.find((s) => s.primaryFor.includes(metricEff(r)))?.key ?? null;
  if (rankRows(r, cur, primary) > 0) return null;
  const ts = tabState(r, sources);
  return sources.find((s) => s.key !== cur && ts.ok[s.key] && rankRows(r, s.key, primary) > 0) ?? null;
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
    // v0.25.2: 보기마다 자기 개수(counts·n_ref)를 가짐 — 주 결과의 것이 새지 않게 명시(없으면 undefined = n_failed 로 계산)
    counts: v.counts,
    n_ref: v.n_ref,
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
