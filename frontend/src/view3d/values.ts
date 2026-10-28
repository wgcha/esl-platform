// values.bin 복원(계약 esl_3d_load.md §3.5). 머리 없음·little-endian·정점 순서, 배열마다 4바이트 정렬.
// 복원값 = 정수 q × 배율 s (오차 ≤ s/2). u 는 정점별 (x,y,z) 교차, 성분별 배율.
import type { View3dOut } from "../api/types";

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
  /** 배열별 배율(양자화 간격) — 표시 유효숫자 결정용 */
  scale: { fn: number; fmag: number; pa: number; u: [number, number, number] };
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
  const res: DecodedValues = { n, fn: null, fmag: null, pa: null, u: null, scale: { fn: 0, fmag: 0, pa: 0, u: [0, 0, 0] } };
  for (const a of manifest.values.arrays) {
    const arr = decodeOne(buf, a, n);
    const sc = Array.isArray(a.scale) ? a.scale : [a.scale];
    if (a.key === "fn") (res.fn = arr), (res.scale.fn = sc[0]);
    else if (a.key === "fmag") (res.fmag = arr), (res.scale.fmag = sc[0]);
    else if (a.key === "pa") (res.pa = arr), (res.scale.pa = sc[0]);
    else if (a.key === "u") (res.u = arr), (res.scale.u = [sc[0], sc[1] ?? sc[0], sc[2] ?? sc[0]]);
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
