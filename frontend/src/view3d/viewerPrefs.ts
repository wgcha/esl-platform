// v0.24.6 뷰어 기억(esl_viewer_hv.md §4): localStorage["esl.v3d.viewer.v1"] = { <planKey>: { bc, load, ghost, marks, levels } } — 키 1개.
// 읽기·쓰기 모두 try/catch. 형식이 틀리거나 저장소가 없으면 계획 표 기본값(오류 표시 없음).
import { LEVEL_CHOICES, planOf, type ViewerState } from "./viewerPlan";

export const VIEWER_KEY = "esl.v3d.viewer.v1";

function readAll(): Record<string, unknown> {
  try {
    const raw = window.localStorage.getItem(VIEWER_KEY);
    if (!raw) return {};
    const o = JSON.parse(raw) as unknown;
    return o && typeof o === "object" && !Array.isArray(o) ? (o as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** 기억값 + 계획 기본값. 필드마다 형식이 맞는 것만 쓴다 */
export function readViewerPrefs(planKey: string): ViewerState {
  const d = planOf(planKey).defaults;
  const s = readAll()[planKey];
  if (!s || typeof s !== "object") return { ...d };
  const o = s as Record<string, unknown>;
  const b = (k: "bc" | "load" | "ghost" | "marks") => (typeof o[k] === "boolean" ? (o[k] as boolean) : d[k]);
  const lv = typeof o.levels === "number" && (LEVEL_CHOICES as readonly number[]).includes(o.levels) ? o.levels : d.levels;
  return { bc: b("bc"), load: b("load"), ghost: b("ghost"), marks: b("marks"), levels: lv };
}

export function writeViewerPrefs(planKey: string, s: ViewerState): void {
  try {
    planOf(planKey);
    const all = readAll();
    all[planKey] = { bc: s.bc, load: s.load, ghost: s.ghost, marks: s.marks, levels: s.levels };
    window.localStorage.setItem(VIEWER_KEY, JSON.stringify(all));
  } catch {
    /* 저장소를 쓸 수 없어도 이번 화면에서만 유지 */
  }
}
