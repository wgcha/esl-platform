// 선택용 순수 함수: 최근접 정점, 광선-선분 최소 거리(화살표 선택).
export type V3 = [number, number, number];

/** 점 p 에 가장 가까운 정점 번호. positions 길이 3n. 비어 있으면 -1 */
export function nearestVertex(positions: ArrayLike<number>, p: ArrayLike<number>, candidates?: ArrayLike<number> | null): number {
  let best = -1;
  let bd = Infinity;
  const n = candidates ? candidates.length : Math.floor(positions.length / 3);
  for (let k = 0; k < n; k++) {
    const i = candidates ? candidates[k] : k;
    const dx = positions[i * 3] - p[0];
    const dy = positions[i * 3 + 1] - p[1];
    const dz = positions[i * 3 + 2] - p[2];
    const d = dx * dx + dy * dy + dz * dz;
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return best;
}

const dot = (x: V3, y: V3) => x[0] * y[0] + x[1] * y[1] + x[2] * y[2];

/** 반직선(o, 단위 d, t ≥ 0)과 선분 [a, b] 사이 최소 거리와 광선 매개변수 t */
export function raySegmentDistance(o: V3, d: V3, a: V3, b: V3): { dist: number; t: number } {
  const v: V3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const w: V3 = [o[0] - a[0], o[1] - a[1], o[2] - a[2]];
  const A = dot(d, d);
  const B = dot(d, v);
  const C = dot(v, v);
  const D = dot(d, w);
  const E = dot(v, w);
  const den = A * C - B * B;
  // 선분 매개변수 q: 평행이면 시작점 기준
  let q = den > 1e-12 ? (A * E - B * D) / den : C > 1e-12 ? E / C : 0;
  q = Math.max(0, Math.min(1, q));
  const t = Math.max(0, (B * q - D) / (A || 1));
  const px = o[0] + d[0] * t - (a[0] + v[0] * q);
  const py = o[1] + d[1] * t - (a[1] + v[1] * q);
  const pz = o[2] + d[2] * t - (a[2] + v[2] * q);
  return { dist: Math.hypot(px, py, pz), t };
}

/** 광선에 가장 가까운(허용 거리 tol 이내, 같으면 카메라에 가까운) 선분 번호. 없으면 -1. tol 은 광선 매개변수 t 의 함수도 가능(원근) */
export function pickSegment(o: V3, d: V3, segs: { a: V3; b: V3 }[], tol: number | ((t: number) => number)): number {
  let best = -1;
  let bd = Infinity;
  let bt = Infinity;
  for (let i = 0; i < segs.length; i++) {
    const r = raySegmentDistance(o, d, segs[i].a, segs[i].b);
    const lim = typeof tol === "function" ? tol(r.t) : tol;
    if (r.dist <= lim && (r.dist < bd - 1e-9 || (Math.abs(r.dist - bd) <= 1e-9 && r.t < bt))) {
      best = i;
      bd = r.dist;
      bt = r.t;
    }
  }
  return best;
}

/** 화면 좌표(px, 오른쪽 x·아래 y) */
export type P2 = [number, number];

/** 점 c 와 화면 선분 [a, b] 사이 최소 거리(px) */
export function pointSegmentDistance2(c: P2, a: P2, b: P2): number {
  const vx = b[0] - a[0];
  const vy = b[1] - a[1];
  const L = vx * vx + vy * vy;
  let q = L > 1e-12 ? ((c[0] - a[0]) * vx + (c[1] - a[1]) * vy) / L : 0;
  q = Math.max(0, Math.min(1, q));
  return Math.hypot(c[0] - (a[0] + vx * q), c[1] - (a[1] + vy * q));
}

/** 화면에 투영한 화살표 선분: depth = NDC z(작을수록 카메라 쪽), tol = 이 화살표의 허용 거리(px) */
export interface ScreenSeg {
  a: P2;
  b: P2;
  depth: number;
  tol: number;
}

/**
 * 화면 공간 화살표 선택(v0.8.0): 클릭점에서 투영 선분까지 px 거리 ≤ tol 인 것 중 가장 가까운(같으면 카메라 쪽) 번호, 없으면 -1.
 * 원근·직교·줌과 무관하게 같은 px 허용으로 동작한다(투영은 호출 측 camera.project). null = 화면 밖(근/원 평면 밖)
 */
export function pickSegmentScreen(c: P2, segs: (ScreenSeg | null)[]): number {
  let best = -1;
  let bd = Infinity;
  let bz = Infinity;
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (!s) continue;
    const dd = pointSegmentDistance2(c, s.a, s.b);
    if (dd <= s.tol && (dd < bd - 1e-9 || (Math.abs(dd - bd) <= 1e-9 && s.depth < bz))) {
      best = i;
      bd = dd;
      bz = s.depth;
    }
  }
  return best;
}

/** NDC(x, y ∈ [-1, 1], y 위) → 캔버스 px(x 오른쪽, y 아래) */
export function ndcToPx(x: number, y: number, width: number, height: number): P2 {
  return [((x + 1) / 2) * width, ((1 - y) / 2) * height];
}
