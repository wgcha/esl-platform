// 사각·올가미·브러시 판정(esl_bead_select.md §11.2): 화면 px 좌표. 보이는 면만 = ID 버퍼(요소 번호 + 1, 0 = 배경) 의 픽셀 판정,
// 관통 선택 = 요소 중심 투영(projectCentroids) 판정. three 비의존.

export type Pt = [number, number];

/** 짝-홀 규칙 점-다각형 판정(경계 위 점은 어느 쪽이든 — 래스터 판정이라 무관) */
export function pointInPolygon(x: number, y: number, poly: ArrayLike<Pt> | Pt[]): boolean {
  let inside = false;
  const n = poly.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
/** 두 점 → 정규화 사각(폭·높이 ≥ 0) */
export function rectOf(a: Pt, b: Pt): Rect {
  return { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(a[0] - b[0]), h: Math.abs(a[1] - b[1]) };
}
/** 다각형 bbox(정수 px, 바깥으로) */
export function polyBounds(poly: Pt[]): Rect {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [x, y] of poly) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  return { x: Math.floor(x0), y: Math.floor(y0), w: Math.ceil(x1) - Math.floor(x0) + 1, h: Math.ceil(y1) - Math.floor(y0) + 1 };
}

/** 원(브러시) 판정 */
export const inCircle = (x: number, y: number, cx: number, cy: number, r: number) => (x - cx) ** 2 + (y - cy) ** 2 <= r * r;

/** ID 버퍼 조각(rect 위치의 w×h, 행 0 = 위) */
export interface IdPatch {
  rect: Rect;
  /** 요소 번호 + 1(0 = 배경), 길이 w·h, 행 우선(위 → 아래) */
  ids: Uint32Array;
}

/** ID 버퍼에서 판정 함수를 만족하는 픽셀의 요소(오름차순, 중복 없음) */
export function idsInMask(p: IdPatch, test: (x: number, y: number) => boolean): number[] {
  const set = new Set<number>();
  const { x, y, w, h } = p.rect;
  for (let j = 0; j < h; j++)
    for (let i = 0; i < w; i++) {
      const id = p.ids[j * w + i];
      if (id && test(x + i + 0.5, y + j + 0.5)) set.add(id - 1);
    }
  return [...set].sort((a, b) => a - b);
}

/** 중심 투영(2·n, 화면 밖·카메라 뒤 = NaN) 에서 판정 함수를 만족하는 요소 */
export function centroidsInMask(px: Float32Array, test: (x: number, y: number) => boolean): number[] {
  const out: number[] = [];
  for (let e = 0; e < px.length / 2; e++) {
    const x = px[e * 2];
    const y = px[e * 2 + 1];
    if (Number.isFinite(x) && Number.isFinite(y) && test(x, y)) out.push(e);
  }
  return out;
}

/** 요소 번호 → ID 색(24비트, 0 = 배경이라 +1) */
export function idToRgb(e: number): [number, number, number] {
  const v = e + 1;
  return [v & 255, (v >> 8) & 255, (v >> 16) & 255];
}
export const rgbToId = (r: number, g: number, b: number): number => r | (g << 8) | (b << 16);
