// v0.25.1 목 씬 3D(계약 §2.3·§6): 씬 manifest(c·dc·pins·ranges.c·ranges.dc) + 값 파일(c·dc int16 배열 덧붙임).
// 시험·시연 전용 — 같은 메시·값 위에 씬(엔트리)·안마다 다른 배율을 곱해 숫자가 바뀌는 것을 보게 한다.
import type { DoeResultOut, DoeScenePackOut, View3dSceneOut } from "../api/types";
import { decodeValues } from "../view3d/values";
import { mockView3d } from "./view3dmock";

const pad4 = (x: number) => (x + 3) & ~3;
const hash = (s: string) => [...s].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7);
/** 안 did 의 C 변화율(−개선율) — 결정적: d001 = −20 %(개선) … 일부는 +(악화) */
export const sceneRate = (did: string, eid: string): number => (((hash(did + eid) % 100) - 55) / 100) * 0.9;
/** 씬(엔트리) 기준 C0 */
export const sceneC0 = (eid: string): number => 1000 * (1 + (hash(eid) % 7) / 10);

const cache = new Map<string, { buf: ArrayBuffer; arrays: View3dSceneOut["values"]["arrays"]; c: Float32Array; dc: Float32Array | null }>();
function values(did: string, eid: string) {
  const key = `${did}|${eid}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const v = mockView3d();
  const m0 = v.manifest("x");
  const dv = decodeValues(v.values, m0);
  const n = m0.n_nodes;
  const base = new Float32Array(n);
  let mx = 0;
  for (let i = 0; i < n; i++) {
    const ux = Math.hypot(dv.u![i * 3], dv.u![i * 3 + 1], dv.u![i * 3 + 2]);
    base[i] = (dv.fn![i] ?? 0) * ux * 0.01 * (hash(eid) % 3 === 0 ? -0.4 : 1);
    mx = Math.max(mx, Math.abs(base[i]));
  }
  const rate = did === "d000" ? 0 : sceneRate(did, eid);
  const c = new Float32Array(n);
  const dcv = did === "d000" ? null : new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const wave = 1 + rate * (0.6 + 0.8 * Math.sin(i / 37));
    c[i] = base[i] * wave;
    if (dcv) dcv[i] = c[i] - base[i];
  }
  const q16 = (a: Float32Array) => {
    let m = 0;
    for (const x of a) m = Math.max(m, Math.abs(x));
    return m / 32767;
  };
  const sc = q16(c);
  const sd = dcv ? q16(dcv) : 0;
  const o0 = v.values.byteLength;
  const o1 = o0 + pad4(n * 2);
  const buf = new ArrayBuffer(o1 + (dcv ? pad4(n * 2) : 0));
  new Uint8Array(buf).set(new Uint8Array(v.values));
  const dvw = new DataView(buf);
  for (let i = 0; i < n; i++) {
    dvw.setInt16(o0 + i * 2, sc ? Math.round(c[i] / sc) : 0, true);
    if (dcv) dvw.setInt16(o1 + i * 2, sd ? Math.round(dcv[i] / sd) : 0, true);
  }
  const arrays = [...m0.values.arrays, { key: "c", dtype: "int16", comps: 1, offset: o0, scale: sc }, ...(dcv ? [{ key: "dc", dtype: "int16", comps: 1, offset: o1, scale: sd }] : [])] as View3dSceneOut["values"]["arrays"];
  const out = { buf, arrays, c, dc: dcv };
  cache.set(key, out);
  void mx;
  return out;
}

export function sceneBin(did: string, eid: string): ArrayBuffer {
  return values(did, eid).buf;
}

const pct = (a: Float32Array, p: number) => {
  const s = Array.from(a).filter((x) => x !== 0).sort((x, y) => x - y);
  return s.length ? s[Math.min(s.length - 1, Math.max(0, Math.floor(p * s.length)))] : 0;
};

/** 씬 manifest. kk = 엔트리 순번(파일 이름 e<kk>.bin) */
export function sceneManifest(studyId: string, src: string, did: string, eid: string, kk: number, uRatio = 1): View3dSceneOut {
  const m0 = mockView3d().manifest(eid);
  const v = values(did, eid);
  const c0 = sceneC0(eid);
  const cd = c0 * (1 + (did === "d000" ? 0 : sceneRate(did, eid)));
  const sum = Array.from(v.c).reduce((a, x) => a + x, 0);
  const umax = m0.ranges.u_max * uRatio;
  const dir = `/doe/studies/${studyId}/view3d-scene/${src}/${did}`;
  return {
    ...m0,
    key: `doe/scene/${src}/${did}/e${kk}`,
    esl_run_id: eid,
    values: { name: `e${String(kk).padStart(2, "0")}.bin`, bytes: v.buf.byteLength, arrays: v.arrays },
    ranges: {
      ...m0.ranges,
      u_max: umax,
      c: { min: Math.min(...v.c), max: Math.max(...v.c), p01: pct(v.c, 0.01), p99: pct(v.c, 0.99) },
      dc: v.dc ? { abs_max: Math.max(...Array.from(v.dc).map(Math.abs)), abs_p99: pct(Float32Array.from(Array.from(v.dc).map(Math.abs)), 0.99) } : null,
    },
    c: { kind: "fu", sum, offset: cd - sum, value: cd, parts: { W_F: cd }, unit: "N·mm" },
    dc: v.dc ? { sum: Array.from(v.dc).reduce((a, x) => a + x, 0), base_sum: c0, map: "identity" } : null,
    pins: { umax: { node_id: 1000 + (hash(did + eid) % 50), vertex: 5, value: +umax.toFixed(4), kind: "ev" } },
    geometry_url: `${dir}/part.glb`,
    values_url: `${dir}/e${String(kk).padStart(2, "0")}.bin`,
  };
}

/** 결과에 씬 사이드카 요약을 더한다: 모든 출처 키 × 보이는 안(+d000) × 엔트리 순서. skipLast = 마지막 엔트리를 한도로 뺌 */
export function withScene(res: DoeResultOut, srcKeys: string[], opts: { skipLast?: boolean; addOk?: boolean; addBlocked?: string | null } = {}): DoeResultOut {
  const eids = (res.esl ?? []).map((e) => e.entry_id);
  const used = opts.skipLast ? eids.slice(0, -1) : eids;
  const dids = ["d000", ...res.view3d.filter((d) => d !== "d000")];
  const packs: Record<string, DoeScenePackOut> = {};
  for (const k of srcKeys)
    packs[k] = {
      c_kind: "fu",
      designs: Object.fromEntries(dids.map((d) => [d, used])),
      skipped: opts.skipLast ? [{ did: null, entry_id: eids[eids.length - 1], code: "SCENE_BUDGET", text: "저장 한도(설정 bead_doe.view3d.scene.max_mb)로 만들지 않았습니다" }] : [],
    };
  return { ...res, scene_view: { entries: eids.map((entry_id, kk) => ({ entry_id, kk })), packs, budget: { max_mb: 1024, est_mb: 30 } }, scene_add: { ok: opts.addOk ?? true, blocked: opts.addBlocked ?? null } };
}
