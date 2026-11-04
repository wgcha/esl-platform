// 클릭 + 확장(esl_bead_select.md 확정 3·§3-3-2·R-BS-1): seed 요소 법선 기준 BFS — 이웃 누적이 아니라 seed 법선과의 각으로 판정해
// 필렛·곡면에서 조금씩 새는 것을 막는다. 각 ≤ θ(기본 select.feature_angle_deg) 인 연결 요소만. 법선 부호(요소 연결 순서)는 무시(|cos|).
import { neighbors, type MeshTopo } from "./adjacency";

/** 두 단위 법선 사이 각(°, 부호 무시 0..90) */
export function normalAngleDeg(t: MeshTopo, a: number, b: number): number {
  const n = t.normals;
  const d = Math.abs(n[a * 3] * n[b * 3] + n[a * 3 + 1] * n[b * 3 + 1] + n[a * 3 + 2] * n[b * 3 + 2]);
  return (Math.acos(Math.min(1, d)) * 180) / Math.PI;
}

/**
 * seed 에서 연결·같은 법선(각 ≤ thetaDeg) 요소 집합(오름차순 요소 번호). blocked(e) = true 인 요소는 넣지도 지나가지도 않는다(다른 비드 층 등).
 * seed 가 blocked 면 빈 배열.
 */
export function grow(t: MeshTopo, seed: number, thetaDeg: number, blocked?: (e: number) => boolean): number[] {
  if (seed < 0 || seed >= t.nElems || blocked?.(seed)) return [];
  const cosT = Math.cos((thetaDeg * Math.PI) / 180);
  const n = t.normals;
  const sx = n[seed * 3];
  const sy = n[seed * 3 + 1];
  const sz = n[seed * 3 + 2];
  const seen = new Uint8Array(t.nElems);
  const queue = new Uint32Array(t.nElems);
  let head = 0;
  let tail = 0;
  queue[tail++] = seed;
  seen[seed] = 1;
  while (head < tail) {
    const e = queue[head++];
    for (const f of neighbors(t, e)) {
      if (seen[f]) continue;
      seen[f] = 1;
      if (blocked?.(f)) continue;
      // 각 ≤ θ ⇔ |cos| ≥ cos θ (작은 수치 여유 1e-12)
      if (Math.abs(sx * n[f * 3] + sy * n[f * 3 + 1] + sz * n[f * 3 + 2]) + 1e-12 < cosT) continue;
      queue[tail++] = f;
    }
  }
  return Array.from(queue.subarray(0, tail)).sort((a, b) => a - b);
}
