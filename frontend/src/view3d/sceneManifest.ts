// v0.25.1 씬 manifest 새 키(계약 §2.3) 읽기 — 순수. api/types.ts 에 의존하지 않고(F1b 가 View3dSceneOut 으로 받음) 구조만 본다.
// 새 키가 없는 옛 view3d 자료는 모두 null — 화면이 깨지지 않는다(V-0251-32).
import type { Range } from "./legend/legendModel";

export interface ScenePin {
  node_id: number;
  vertex: number;
  value: number;
  kind: string;
}
export interface SceneExtras {
  /** C 기여도 합 등(범례 제목의 "합 = C") */
  c: { kind: string; sum: number; offset: number; value: number; unit: string } | null;
  dc: { sum: number; base_sum: number; map: string } | null;
  umaxPin: ScenePin | null;
  /** 자동 범위(서버 값): c = [min(p01, 0), max(p99, 0)] 의 재료, dc = ±abs_p99 */
  cRange: { min: number; max: number; p01: number; p99: number } | null;
  dcRange: { abs_max: number; abs_p99: number } | null;
}

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

export function sceneExtras(manifest: unknown): SceneExtras {
  const m = obj(manifest) ?? {};
  const c = obj(m.c);
  const dc = obj(m.dc);
  const pins = obj(m.pins);
  const pin = obj(pins?.umax);
  const ranges = obj(m.ranges);
  const rc = obj(ranges?.c);
  const rdc = obj(ranges?.dc);
  return {
    c: c && num(c.sum) ? { kind: String(c.kind ?? ""), sum: c.sum, offset: num(c.offset) ? c.offset : 0, value: num(c.value) ? c.value : c.sum, unit: typeof c.unit === "string" ? c.unit : "N·mm" } : null,
    dc: dc && num(dc.sum) ? { sum: dc.sum, base_sum: num(dc.base_sum) ? dc.base_sum : NaN, map: String(dc.map ?? "") } : null,
    umaxPin: pin && num(pin.vertex) && num(pin.value) ? { node_id: num(pin.node_id) ? pin.node_id : pin.vertex, vertex: pin.vertex, value: pin.value, kind: String(pin.kind ?? "") } : null,
    cRange: rc && num(rc.min) && num(rc.max) ? { min: rc.min, max: rc.max, p01: num(rc.p01) ? rc.p01 : rc.min, p99: num(rc.p99) ? rc.p99 : rc.max } : null,
    dcRange: rdc && num(rdc.abs_max) ? { abs_max: rdc.abs_max, abs_p99: num(rdc.abs_p99) ? rdc.abs_p99 : rdc.abs_max } : null,
  };
}

/** C 기여도 자동 범위(계약 §4.3): [min(p01, 0), max(p99, 0)]. 퇴화(둘 다 0)면 [−1, 1] 대신 null */
export function cAutoRange(x: SceneExtras): Range | null {
  const r = x.cRange;
  if (!r) return null;
  const min = Math.min(r.p01, 0);
  const max = Math.max(r.p99, 0);
  return max > min ? { min, max } : null;
}
/** 차이 자동 범위: ±abs_p99(없으면 ±abs_max) */
export function dcAutoRange(x: SceneExtras): Range | null {
  const r = x.dcRange;
  if (!r) return null;
  const V = r.abs_p99 > 0 ? r.abs_p99 : r.abs_max;
  return V > 0 ? { min: -V, max: V } : null;
}
