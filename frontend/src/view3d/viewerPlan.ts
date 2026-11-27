// v0.24.6 3D 뷰어 계획 표(esl_viewer_hv.md §6.2): 보기 종류 → 선언. 카드는 이 열만 읽는다(보기 이름 분기 없음).
// 표시 기본값은 이 표 한 곳(하드코딩 금지). 새 3D 보기를 더할 때는 행 하나를 더한다(모든 열 채움).

// v0.25.1: 범례 모양(레벨 수·연속·범위 밖 색 …)은 보기마다 따로가 아니라 모든 3D 보기 공통 1벌 — view3d/legend/legendModel.ts.
// upin(umax 위치 핀)은 층이지만 켬·끔은 범례 기억(legend.upin)에 있다 — 계획 열 layers 는 "이 보기에서 쓸 수 있는가"만 말한다.

export type ViewerLayer = "bc" | "load" | "ghost" | "marks" | "upin";

/** 사용자가 켜고 끄는 값(보기 종류별로 이 브라우저에 기억) */
export interface ViewerState {
  bc: boolean;
  load: boolean;
  ghost: boolean;
  marks: boolean;
}

export interface ViewerPlan {
  /** 쓸 수 있는 층 */
  layers: readonly ViewerLayer[];
  /** pair = 2카드 보기(시점·변형·층 공유), none = 카드 하나 */
  sync: "none" | "pair";
  /** v0.25.1 pair = 두 카드가 범례 설정·범위를 공유, none = 카드마다(계약 §5.4) */
  legendSync: "none" | "pair";
  defaults: ViewerState;
}

const ALL: readonly ViewerLayer[] = ["bc", "load", "ghost", "marks", "upin"];
/** Q-VW-3 기본 가정: 경계조건·하중 켬(지금 그림 그대로) · 원형 끔 · 최대 표식 켬 */
const DEFAULT_STATE: ViewerState = { bc: true, load: true, ghost: false, marks: true };

export const VIEWER_PLANS: Record<string, ViewerPlan> = {
  case_load: { layers: ALL, sync: "none", legendSync: "none", defaults: DEFAULT_STATE },
  case_disp: { layers: ALL, sync: "none", legendSync: "none", defaults: DEFAULT_STATE },
  study_design: { layers: ALL, sync: "pair", legendSync: "pair", defaults: DEFAULT_STATE },
  study_jigdiag: { layers: ALL, sync: "pair", legendSync: "pair", defaults: DEFAULT_STATE },
  study_recon: { layers: ALL, sync: "pair", legendSync: "pair", defaults: DEFAULT_STATE },
};

export type ViewerPlanKey = keyof typeof VIEWER_PLANS;

/** 계획 행. 알 수 없는 키 = 오류(조용히 기본값으로 넘기지 않는다) */
export function planOf(key: string): ViewerPlan {
  const p = Object.prototype.hasOwnProperty.call(VIEWER_PLANS, key) ? VIEWER_PLANS[key] : undefined;
  if (!p) throw new Error(`알 수 없는 3D 뷰어 계획 키: ${key}`);
  return p;
}

/** 계획을 안 준 카드(옛 호출부)의 계획 키: 색 종류만 보고 고른다 */
export function defaultPlanKey(colorBy: "load" | "disp"): string {
  return colorBy === "disp" ? "case_disp" : "case_load";
}

/** 계획 열 해석(카드·칩이 같이 씀): 쌍 상태를 공유하는가 = 열 sync */
export function usesPairSync(planKey: string): boolean {
  return planOf(planKey).sync === "pair";
}

/** 계획 열 legendSync 해석: 범례 설정·범위를 쌍이 공유하는가 */
export function usesLegendSync(planKey: string): boolean {
  return planOf(planKey).legendSync === "pair";
}

/** 계획 열 layers 를 적용한 층 켬 상태: 쓸 수 없는 층은 사용자가 켜 둔 값이어도 꺼진 것(장면·칩·표식·선택 모두 이 값).
 *  upin 켬·끔은 state.legend.upin(범례 기억)에서 온다 */
export function effectiveLayers(planKey: string, state: Pick<ViewerState, "bc" | "load" | "ghost" | "marks"> & { legend?: { upin: boolean } }): Record<ViewerLayer, boolean> {
  const p = planOf(planKey);
  const on = (l: "bc" | "load" | "ghost" | "marks") => p.layers.includes(l) && state[l];
  return { bc: on("bc"), load: on("load"), ghost: on("ghost"), marks: on("marks"), upin: p.layers.includes("upin") && (state.legend ? state.legend.upin : true) };
}
