// v0.24.6 원형 외곽선용 특징선(esl_viewer_hv.md §2.2): 자유 경계 모서리(인접 삼각형 1개) + 이면각 > deg 모서리 + 비다양체(3개 이상).
// 순수 함수. 타입 배열 해시(Map 금지 — 30만 노드·≈60만 삼각형에서 ≤ 300 ms 목표). 면 방향이 뒤집혀도 같도록 법선 내적의 절댓값을 쓴다.

/** 특징 모서리 이면각 기준(도) — 한 곳 */
export const FEATURE_DEG = 30;

/** 반환 = 정점 쌍(a0,b0,a1,b1,…) */
export function featureEdges(positions: ArrayLike<number>, indices: ArrayLike<number>, deg: number = FEATURE_DEG): Uint32Array {
  const nT = Math.floor(indices.length / 3);
  if (nT === 0) return new Uint32Array(0);
  // 삼각형 단위 법선
  const nrm = new Float32Array(nT * 3);
  for (let t = 0; t < nT; t++) {
    const a = indices[t * 3] * 3;
    const b = indices[t * 3 + 1] * 3;
    const c = indices[t * 3 + 2] * 3;
    const ux = positions[b] - positions[a];
    const uy = positions[b + 1] - positions[a + 1];
    const uz = positions[b + 2] - positions[a + 2];
    const vx = positions[c] - positions[a];
    const vy = positions[c + 1] - positions[a + 1];
    const vz = positions[c + 2] - positions[a + 2];
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const L = Math.hypot(nx, ny, nz);
    if (L > 0) {
      nx /= L;
      ny /= L;
      nz /= L;
    }
    nrm[t * 3] = nx;
    nrm[t * 3 + 1] = ny;
    nrm[t * 3 + 2] = nz;
  }
  // 열린 주소 해시: 키 = (lo, hi) 정점 쌍
  let cap = 16;
  while (cap < nT * 3 * 2) cap <<= 1;
  const mask = cap - 1;
  const kLo = new Int32Array(cap).fill(-1);
  const kHi = new Int32Array(cap);
  const t0 = new Int32Array(cap);
  const t1 = new Int32Array(cap).fill(-1);
  const cnt = new Uint8Array(cap);
  for (let t = 0; t < nT; t++) {
    for (let e = 0; e < 3; e++) {
      const p = indices[t * 3 + e];
      const q = indices[t * 3 + ((e + 1) % 3)];
      const lo = p < q ? p : q;
      const hi = p < q ? q : p;
      let h = (Math.imul(lo, 0x9e3779b1) ^ Math.imul(hi, 0x85ebca6b)) & mask;
      while (kLo[h] !== -1 && !(kLo[h] === lo && kHi[h] === hi)) h = (h + 1) & mask;
      if (kLo[h] === -1) {
        kLo[h] = lo;
        kHi[h] = hi;
        t0[h] = t;
        cnt[h] = 1;
      } else {
        if (cnt[h] === 1) t1[h] = t;
        if (cnt[h] < 255) cnt[h]++;
      }
    }
  }
  const cosLim = Math.cos((deg * Math.PI) / 180);
  const out: number[] = [];
  for (let h = 0; h < cap; h++) {
    if (kLo[h] === -1) continue;
    let feat = false;
    if (cnt[h] === 1 || cnt[h] > 2) feat = true;
    else {
      const a = t0[h] * 3;
      const b = t1[h] * 3;
      const d = Math.abs(nrm[a] * nrm[b] + nrm[a + 1] * nrm[b + 1] + nrm[a + 2] * nrm[b + 2]);
      feat = d < cosLim - 1e-6;
    }
    if (feat) out.push(kLo[h], kHi[h]);
  }
  return Uint32Array.from(out);
}
