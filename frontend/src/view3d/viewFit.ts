// v0.15.1 시점 버튼(정면 ±X·±Y·±Z, 등각, 꽉 차게) — 카메라 방향·up·맞춤 거리 계산. three 에 의존하지 않는다(scene.ts 가 결과만 적용).
// 맞춤: 현재 시선 방향에서 bbox 8 꼭짓점을 화면 오른쪽·위 축에 투영해 반너비·반높이를 구하고, 화면비를 반영해 꽉 차게(여백 FIT_MARGIN).
import type { V3 } from "./pick";
import { PERSP_FOV, type Projection } from "./projection";

export type ViewAxis = "x" | "y" | "z" | "iso";
export type ViewSign = 1 | -1;
export interface Bbox {
  min: number[];
  max: number[];
}

/** 꽉 차게 보기 여백(보이는 반높이 = 필요 반높이 × 이 값) */
export const FIT_MARGIN = 1.08;

const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};

/**
 * 시점: eye = 타깃 → 카메라 단위 벡터(카메라가 있는 쪽), up = 화면 위.
 * "+X 보기" = 카메라가 +X 쪽에서 −X 방향으로 봄(+X 면이 보임). X·Y 보기 up = +Z, Z 보기 up = +Y. 등각 = (±1, ±1, 1)/√3, up = +Z.
 */
export function viewBasis(axis: ViewAxis, sign: ViewSign = 1): { eye: V3; up: V3 } {
  if (axis === "x") return { eye: [sign, 0, 0], up: [0, 0, 1] };
  if (axis === "y") return { eye: [0, sign, 0], up: [0, 0, 1] };
  if (axis === "z") return { eye: [0, 0, sign], up: [0, 1, 0] };
  return { eye: norm([sign, sign, 1]), up: [0, 0, 1] };
}

/** 표시 이름(버튼 title·안내) */
export function viewLabel(axis: ViewAxis, sign: ViewSign): string {
  if (axis === "iso") return sign > 0 ? "등각(+X+Y+Z)" : "등각(−X−Y+Z)";
  return `${sign > 0 ? "+" : "−"}${axis.toUpperCase()} 보기`;
}

export function bboxCenter(b: Bbox): V3 {
  return [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2];
}

export function validBbox(b: Bbox | null | undefined): b is Bbox {
  return !!b && b.min.length >= 3 && b.max.length >= 3 && [0, 1, 2].every((i) => Number.isFinite(b.min[i]) && Number.isFinite(b.max[i]) && b.max[i] >= b.min[i]);
}

export interface FitResult {
  target: V3;
  position: V3;
  up: V3;
  /** 직교 frustum 반높이(zoom 1) — 원근에서도 같은 값(보이는 반높이) */
  halfH: number;
}

/**
 * 시선 eye·up 그대로 bbox 를 꽉 차게: 타깃 = bbox 중심.
 * - 직교: 반높이 = max(반높이, 반너비/화면비) × 여백, 카메라 = 타깃 + eye × (bbox 대각선) (근/원은 scene 이 모델 중심 기준으로 잡는다)
 * - 원근: 가장 앞 꼭짓점 면에서 그 반높이가 보이도록 거리 = 반높이 / tan(FOV/2) + 시선 방향 반깊이
 * 크기 0 인 bbox 는 최소 반높이 minHalf(기본 1 mm).
 */
export function fitView(b: Bbox, eye: V3, up: V3, aspect: number, proj: Projection, fovDeg = PERSP_FOV, margin = FIT_MARGIN, minHalf = 1): FitResult {
  const e = norm(eye);
  const right = norm(cross(up, e));
  const u = cross(e, right);
  const c = bboxCenter(b);
  let hw = 0;
  let hh = 0;
  let hd = 0;
  for (let i = 0; i < 8; i++) {
    const p: V3 = [(i & 1 ? b.max[0] : b.min[0]) - c[0], (i & 2 ? b.max[1] : b.min[1]) - c[1], (i & 4 ? b.max[2] : b.min[2]) - c[2]];
    hw = Math.max(hw, Math.abs(dot(p, right)));
    hh = Math.max(hh, Math.abs(dot(p, u)));
    hd = Math.max(hd, Math.abs(dot(p, e)));
  }
  const a = aspect > 0 && Number.isFinite(aspect) ? aspect : 1;
  const halfH = Math.max(hh, hw / a, minHalf) * margin;
  const diag = Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]);
  const dist = proj === "ortho" ? Math.max(diag, halfH * 2) : halfH / Math.tan((fovDeg * Math.PI) / 360) + hd;
  return { target: c, position: [c[0] + e[0] * dist, c[1] + e[1] * dist, c[2] + e[2] * dist], up: u, halfH };
}

/** 같은 축 버튼을 다시 누르면 반대 방향(토글), 다른 축이면 + 부터 */
export function nextSign(last: { axis: ViewAxis; sign: ViewSign } | null, axis: ViewAxis): ViewSign {
  return last && last.axis === axis ? ((-last.sign) as ViewSign) : 1;
}

/** 요소 집합의 bbox(삼각형 t 의 요소 tri2elem[t] 가 inSel 이면 그 꼭짓점 포함). 없으면 null */
export function elemsBbox(positions: Float32Array, indices: Uint32Array, tri2elem: Uint32Array, inSel: (e: number) => boolean): Bbox | null {
  const mn = [Infinity, Infinity, Infinity];
  const mx = [-Infinity, -Infinity, -Infinity];
  let any = false;
  for (let t = 0; t < tri2elem.length; t++) {
    if (!inSel(tri2elem[t])) continue;
    any = true;
    for (let j = 0; j < 3; j++) {
      const v = indices[t * 3 + j] * 3;
      for (let k = 0; k < 3; k++) {
        const x = positions[v + k];
        if (x < mn[k]) mn[k] = x;
        if (x > mx[k]) mx[k] = x;
      }
    }
  }
  return any ? { min: mn, max: mx } : null;
}

/** 위치 배열 전체 bbox */
export function positionsBbox(p: Float32Array): Bbox {
  const mn = [Infinity, Infinity, Infinity];
  const mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) (mn[k] = Math.min(mn[k], p[i + k])), (mx[k] = Math.max(mx[k], p[i + k]));
  return { min: mn, max: mx };
}
