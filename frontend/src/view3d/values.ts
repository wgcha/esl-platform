// values.bin 복원(계약 esl_3d_load.md §3.5). 머리 없음·little-endian·정점 순서, 배열마다 4바이트 정렬.
// 복원값 = 정수 q × 배율 s (오차 ≤ s/2). u 는 정점별 (x,y,z) 교차, 성분별 배율.
import type { View3dOut, View3dReconOut } from "../api/types";
import type { LoadComp } from "./sources";

export interface DecodedValues {
  n: number;
  /** 면외 하중 Fn (N, 부호 있음) */
  fn: Float32Array | null;
  /** |F| (N) */
  fmag: Float32Array | null;
  /** 면압 |Fn|/A (MPa, 크기) — 표면 색(사용자 결정 2026-10-28). 서버가 안 주면 null → |Fn| 로 폴백 */
  pa: Float32Array | null;
  /** u_rel (mm), 길이 3n */
  u: Float32Array | null;
  /** v0.25.1 C 기여도 c_n (N·mm, 부호 있음) — 씬 묶음 값 파일에만 있다(옛 자료 = null) */
  c: Float32Array | null;
  /** v0.25.1 C 기여도 차이 dc_n = 안 − 기준(N·mm) — 안 묶음에만 있다 */
  dc: Float32Array | null;
  /** 배열별 배율(양자화 간격) — 표시 유효숫자 결정용 */
  scale: { fn: number; fmag: number; pa: number; u: [number, number, number]; c: number; dc: number };
}

const BYTES: Record<string, number> = { int16: 2, uint16: 2 };

function view(buf: ArrayBuffer, offset: number, count: number, dtype: string): Int16Array | Uint16Array {
  const ctor = dtype === "int16" ? Int16Array : Uint16Array;
  if (offset % 2 === 0) return new ctor(buf, offset, count);
  return new ctor(buf.slice(offset, offset + count * 2)); // 정렬 위반 시 복사(계약상 4바이트 정렬이라 드묾)
}

/** 배열 하나를 float32 로 복원. 범위 밖이면 오류 */
function decodeOne(buf: ArrayBuffer, a: View3dOut["values"]["arrays"][number], n: number): Float32Array {
  const bytes = BYTES[a.dtype];
  if (!bytes) throw new Error(`values.bin: 알 수 없는 dtype ${a.dtype}`);
  const count = n * a.comps;
  if (a.offset < 0 || a.offset + count * bytes > buf.byteLength) throw new Error(`values.bin: ${a.key} 범위 초과 (offset ${a.offset}, ${count}개)`);
  const q = view(buf, a.offset, count, a.dtype);
  const out = new Float32Array(count);
  if (a.comps === 1) {
    const s = Array.isArray(a.scale) ? a.scale[0] : a.scale;
    for (let i = 0; i < count; i++) out[i] = q[i] * s;
  } else {
    const sc = Array.isArray(a.scale) ? a.scale : new Array(a.comps).fill(a.scale);
    for (let i = 0; i < n; i++) for (let c = 0; c < a.comps; c++) out[i * a.comps + c] = q[i * a.comps + c] * sc[c];
  }
  return out;
}

export function decodeValues(buf: ArrayBuffer, manifest: Pick<View3dOut, "n_nodes" | "values">): DecodedValues {
  const n = manifest.n_nodes;
  const res: DecodedValues = { n, fn: null, fmag: null, pa: null, u: null, c: null, dc: null, scale: { fn: 0, fmag: 0, pa: 0, u: [0, 0, 0], c: 0, dc: 0 } };
  for (const a0 of manifest.values.arrays) {
    const a = a0 as View3dOut["values"]["arrays"][number] & { key: string }; // 씬 묶음은 c·dc 키를 더한다(types.ts 는 F1b 몫 — 모르는 키는 무시)
    const arr = decodeOne(buf, a, n);
    const sc = Array.isArray(a.scale) ? a.scale : [a.scale];
    if (a.key === "fn") (res.fn = arr), (res.scale.fn = sc[0]);
    else if (a.key === "fmag") (res.fmag = arr), (res.scale.fmag = sc[0]);
    else if (a.key === "pa") (res.pa = arr), (res.scale.pa = sc[0]);
    else if (a.key === "u") (res.u = arr), (res.scale.u = [sc[0], sc[1] ?? sc[0], sc[2] ?? sc[0]]);
    else if (a.key === "c") (res.c = arr), (res.scale.c = sc[0]);
    else if (a.key === "dc") (res.dc = arr), (res.scale.dc = sc[0]);
  }
  return res;
}

/** 표면 색에 쓰는 값: 면압(있으면) 아니면 |Fn|. 단위 문자열도 함께 */
export function colorField(v: DecodedValues): { values: Float32Array; unit: "MPa" | "N" } | null {
  if (v.pa) return { values: v.pa, unit: "MPa" };
  if (v.fn) {
    const out = new Float32Array(v.fn.length);
    for (let i = 0; i < out.length; i++) out[i] = Math.abs(v.fn[i]);
    return { values: out, unit: "N" };
  }
  return null;
}

/** 양자화 간격까지만 유효숫자를 남긴 문자열(툴팁). 간격 0(전부 0)이면 그대로 */
export function fmtQuant(v: number, step: number): string {
  if (!Number.isFinite(v)) return "–";
  if (!(step > 0)) return String(v);
  const dec = Math.max(0, Math.min(8, Math.ceil(-Math.log10(step))));
  return v.toFixed(dec);
}

/** 하중 성분 선택(v0.24.1 §2.2): pa = 면압 |Fn|/A(MPa) · fn = 법선 |Fn|(N) · fmag = 크기 |F|(N). null = 지금 colorField(면압, 없으면 |Fn|).
 *  선택 성분이 values.bin 에 없으면 null(호출부가 비활성 처리) */
export function loadFieldOf(v: DecodedValues, comp: LoadComp | null): { values: Float32Array; unit: "MPa" | "N" } | null {
  if (!comp) return colorField(v);
  if (comp === "pa") return v.pa ? { values: v.pa, unit: "MPa" } : null;
  if (comp === "fmag") return v.fmag ? { values: v.fmag, unit: "N" } : null;
  if (!v.fn) return null;
  const out = new Float32Array(v.fn.length);
  for (let i = 0; i < out.length; i++) out[i] = Math.abs(v.fn[i]);
  return { values: out, unit: "N" };
}

/** 하중 색 자동 범위 상단: p99(없으면 max) — 지금 규칙. 성분은 단위로 고름(MPa = 면압, N = |Fn|; fmag 는 fmag_max) */
export function loadRangeTop(ranges: View3dOut["ranges"], comp: LoadComp | null, unit: "MPa" | "N"): number {
  if (comp === "fmag") return ranges.fmag_max > 0 ? ranges.fmag_max : 1;
  const r = unit === "MPa" ? ranges.pa : ranges.fn_abs;
  return r && r.p99 != null && r.p99 > 0 ? r.p99 : r && r.max > 0 ? r.max : 1;
}

/** values.bin 에 면압이 있으면 MPa 계열, 없으면 |Fn|(N)로 폴백(colorField 와 같은 규칙) — 매니페스트만으로 단위 판정 */
export function loadUnitOf(manifest: Pick<View3dOut, "values">): "MPa" | "N" {
  return manifest.values.arrays.some((a) => a.key === "pa") ? "MPa" : "N";
}

export interface DecodedDisp {
  n: number;
  /** 각 3n(mm), 정점별 (x,y,z) 교차 */
  tgt: Float32Array | null;
  fit: Float32Array | null;
  err: Float32Array | null;
}

/** recon.bin 복원(§3 pack_disp): int16×3, 성분별 배율, 배열마다 4바이트 정렬 — values.bin u 와 같은 규칙 */
export function decodeDisp(buf: ArrayBuffer, recon: Pick<View3dReconOut, "n_nodes" | "arrays">): DecodedDisp {
  const n = recon.n_nodes;
  const res: DecodedDisp = { n, tgt: null, fit: null, err: null };
  for (const a of recon.arrays) {
    if (a.dtype !== "int16") throw new Error(`recon.bin: 알 수 없는 dtype ${a.dtype}`);
    const count = n * a.comps;
    if (a.offset < 0 || a.offset + count * 2 > buf.byteLength) throw new Error(`recon.bin: ${a.key} 범위 초과 (offset ${a.offset}, ${count}개)`);
    const q = a.offset % 2 === 0 ? new Int16Array(buf, a.offset, count) : new Int16Array(buf.slice(a.offset, a.offset + count * 2));
    const out = new Float32Array(count);
    for (let i = 0; i < n; i++) for (let c = 0; c < a.comps; c++) out[i * a.comps + c] = q[i * a.comps + c] * (a.scale[c] ?? a.scale[0] ?? 0);
    res[a.key] = out;
  }
  return res;
}

/** u(3n) 최대 크기(mm) */
export function maxNorm3(u: Float32Array): number {
  let m = 0;
  for (let i = 0; i + 2 < u.length; i += 3) m = Math.max(m, Math.hypot(u[i], u[i + 1], u[i + 2]));
  return m;
}
