// ④ 3D 투영 방식(원근/직교) — 기본값·브라우저별 기억·전환 수식. three 에 의존하지 않는다(three 는 scene.ts 한 곳).
// 전환 규칙: 카메라 위치·타깃·방향 보존. 직교의 보이는 높이 = 원근에서 타깃 거리 d 의 보이는 높이 2·d·tan(FOV/2) → 전환 전후 모델 크기 같음.
import type { V3 } from "./pick";

export type Projection = "persp" | "ortho";

/** 기본 = 직교(CAE 관례, 원근 치수 왜곡 없음) — 기본값은 여기 한 곳 */
export const DEFAULT_PROJECTION: Projection = "ortho";
/** 원근 세로 시야각(도) */
export const PERSP_FOV = 40;
/** 직교 근/원 클리핑: 시선 방향 모델 중심 거리 ± 이 배수 × bbox 대각선(변형 확대 여유 포함) */
export const ORTHO_CLIP_DIAG = 2;
/** localStorage 키(브라우저별, esl.<이름>.v1 규칙) */
export const PROJ_KEY = "esl.v3d.projection.v1";

export function readProjection(): Projection {
  try {
    const v = localStorage.getItem(PROJ_KEY);
    return v === "persp" || v === "ortho" ? v : DEFAULT_PROJECTION;
  } catch {
    return DEFAULT_PROJECTION;
  }
}
export function writeProjection(p: Projection) {
  try {
    localStorage.setItem(PROJ_KEY, p);
  } catch {
    /* 저장소 없음 — 이번 화면에서만 유지 */
  }
}

const tanHalf = (fovDeg: number) => Math.tan((fovDeg * Math.PI) / 360);
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const len = (a: V3) => Math.hypot(a[0], a[1], a[2]);

/** 원근에서 거리 d 의 보이는 높이 2·d·tan(FOV/2) */
export function perspVisibleHeight(d: number, fovDeg = PERSP_FOV): number {
  return 2 * d * tanHalf(fovDeg);
}

/** 원근 → 직교: 위치·타깃 그대로, 직교 frustum 반높이(zoom = 1) */
export function orthoHalfHeightFromPersp(position: V3, target: V3, fovDeg = PERSP_FOV): number {
  return perspVisibleHeight(len(sub(position, target)), fovDeg) / 2;
}

/** 직교 → 원근: 타깃·방향 그대로, 보이는 높이(2·halfH/zoom)가 같아지도록 타깃 거리만 조정한 위치 */
export function perspPositionFromOrtho(position: V3, target: V3, halfH: number, zoom: number, fovDeg = PERSP_FOV): V3 {
  const v = sub(position, target);
  const l = len(v) || 1;
  const d = (2 * halfH) / Math.max(zoom, 1e-12) / (2 * tanHalf(fovDeg));
  return [target[0] + (v[0] / l) * d, target[1] + (v[1] / l) * d, target[2] + (v[2] / l) * d];
}

/** 직교 근/원: 시선 방향 모델 중심 거리 c ± k·diag (c 가 작으면 near 음수 — 직교에서는 허용) */
export function orthoClip(position: V3, viewDir: V3, center: V3, diag: number): { near: number; far: number } {
  const c = sub(center, position);
  const along = c[0] * viewDir[0] + c[1] * viewDir[1] + c[2] * viewDir[2];
  const m = ORTHO_CLIP_DIAG * diag;
  return { near: along - m, far: along + m };
}

/** 1 px 의 월드 길이: 원근 = 거리 t 에 비례, 직교 = 보이는 높이 / 화면 높이(거리 무관) */
export function pxWorld(p: Projection, t: number, heightPx: number, orthoVisibleH: number, fovDeg = PERSP_FOV): number {
  const h = Math.max(1, heightPx);
  return p === "ortho" ? orthoVisibleH / h : perspVisibleHeight(t, fovDeg) / h;
}
