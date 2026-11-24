// v0.24.6 3D 뷰어 계획 표(esl_viewer_hv.md §6.2): 보기 종류 → 선언. 카드는 이 열만 읽는다(보기 이름 분기 없음).
// 표시 기본값은 이 표 한 곳(하드코딩 금지). 새 3D 보기를 더할 때는 행 하나를 더한다(모든 열 채움).

/** 범례 구간 선택지. 0 = 연속 */
export const LEVEL_CHOICES = [0, 6, 9, 12] as const;

export type ViewerLayer = "bc" | "load" | "ghost" | "marks";

/** 사용자가 켜고 끄는 값(보기 종류별로 이 브라우저에 기억) */
export interface ViewerState {
  bc: boolean;
  load: boolean;
  ghost: boolean;
  marks: boolean;
  levels: number;
}

export interface ViewerPlan {
  /** 쓸 수 있는 층 */
  layers: readonly ViewerLayer[];
  /** pair = 2카드 보기(시점·변형·층·레벨 공유), none = 카드 하나 */
  sync: "none" | "pair";
  defaults: ViewerState;
}

const ALL: readonly ViewerLayer[] = ["bc", "load", "ghost", "marks"];
/** Q-VW-3 기본 가정: 경계조건·하중 켬(지금 그림 그대로) · 원형 끔 · 최대 표식 켬 · 범례 연속 */
const DEFAULT_STATE: ViewerState = { bc: true, load: true, ghost: false, marks: true, levels: 0 };

export const VIEWER_PLANS: Record<string, ViewerPlan> = {
  case_load: { layers: ALL, sync: "none", defaults: DEFAULT_STATE },
  case_disp: { layers: ALL, sync: "none", defaults: DEFAULT_STATE },
  study_design: { layers: ALL, sync: "pair", defaults: DEFAULT_STATE },
  study_jigdiag: { layers: ALL, sync: "pair", defaults: DEFAULT_STATE },
  study_recon: { layers: ALL, sync: "pair", defaults: DEFAULT_STATE },
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
