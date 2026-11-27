// v0.24.6 뷰어 기억 → v0.25.1 v2(계약 §5.6). 층(bc·load·ghost·marks)은 보기(planKey)별, 범례 모양은 공통 1벌 — 저장·이행은 legend/legendPrefs.ts.
// 읽기·쓰기 모두 try/catch. 형식이 틀리거나 저장소가 없으면 계획 표 기본값(오류 표시 없음).
import { readLayerPrefs, writeLayerPrefs, VIEWER_KEY_V2 } from "./legend/legendPrefs";
import { planOf, type ViewerState } from "./viewerPlan";

export const VIEWER_KEY = VIEWER_KEY_V2;

/** 기억값 + 계획 기본값. 필드마다 형식이 맞는 것만 쓴다 */
export function readViewerPrefs(planKey: string): ViewerState {
  const d = planOf(planKey).defaults;
  const m = readLayerPrefs(planKey);
  return { bc: m.bc ?? d.bc, load: m.load ?? d.load, ghost: m.ghost ?? d.ghost, marks: m.marks ?? d.marks };
}

export function writeViewerPrefs(planKey: string, s: ViewerState): void {
  planOf(planKey);
  writeLayerPrefs(planKey, { bc: s.bc, load: s.load, ghost: s.ghost, marks: s.marks });
}
