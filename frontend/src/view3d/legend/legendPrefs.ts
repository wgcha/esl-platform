// v0.25.1 뷰어 기억 v2(계약 §5.6): localStorage["esl.v3d.viewer.v2"] = { legend: {...}, "<planKey>": {bc, load, ghost, marks} } — 키 1개.
// 범례 모양은 모든 3D 보기 공통 1벌. 범위 직접 입력값·로그 선택은 기억하지 않는다(값 종류·씬마다 뜻이 달라 다음에 잘못 적용됨).
// v1 → v2: 처음 읽을 때 v1 의 planKey 별 bc·load·ghost·marks 를 옮기고 levels 는 버린다(새 기본 9). v1 키는 지우지 않는다.
// 읽기·쓰기 모두 try/catch — 형식 오류·저장소 없음 = 기본값(오류 표시 없음).
import { LEGEND_DEFAULTS, normalizeLegend, type LegendSettings } from "./legendModel";

export const VIEWER_KEY_V1 = "esl.v3d.viewer.v1";
export const VIEWER_KEY_V2 = "esl.v3d.viewer.v2";
/** 보기별(planKey)로 기억하는 층 */
export type LayerMemo = { bc?: boolean; load?: boolean; ghost?: boolean; marks?: boolean };
const LAYER_KEYS = ["bc", "load", "ghost", "marks"] as const;
/** 기억하는 범례 필드(scale 은 제외) */
const LEGEND_KEYS = ["levels", "continuous", "format", "digits", "out", "reversed", "minMark", "upin"] as const;

function parseObj(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const o = JSON.parse(raw) as unknown;
    return o && typeof o === "object" && !Array.isArray(o) ? (o as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
function getItem(k: string): string | null {
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}

function pickLayers(o: unknown): LayerMemo {
  const out: LayerMemo = {};
  if (!o || typeof o !== "object") return out;
  for (const k of LAYER_KEYS) {
    const v = (o as Record<string, unknown>)[k];
    if (typeof v === "boolean") out[k] = v;
  }
  return out;
}

/** v2 전체(없으면 v1 에서 이행한 값, 둘 다 없으면 빈 객체). 저장은 하지 않는다 — 처음 쓸 때 저장 */
function readAllV2(): Record<string, unknown> {
  const v2 = parseObj(getItem(VIEWER_KEY_V2));
  if (v2) return v2;
  const v1 = parseObj(getItem(VIEWER_KEY_V1));
  if (!v1) return {};
  const out: Record<string, unknown> = {};
  for (const [pk, v] of Object.entries(v1)) if (pk !== "legend") out[pk] = pickLayers(v); // levels 는 버림
  return out;
}

export function readLegendPrefs(): LegendSettings {
  const l = readAllV2().legend;
  if (!l || typeof l !== "object") return { ...LEGEND_DEFAULTS };
  const o = l as Record<string, unknown>;
  const memo: Record<string, unknown> = {};
  for (const k of LEGEND_KEYS) if (k in o) memo[k] = o[k];
  return normalizeLegend(memo as Partial<Record<keyof LegendSettings, unknown>>); // scale 은 항상 선형으로 시작
}

export function readLayerPrefs(planKey: string): LayerMemo {
  return pickLayers(readAllV2()[planKey]);
}

function writeAll(all: Record<string, unknown>) {
  try {
    window.localStorage.setItem(VIEWER_KEY_V2, JSON.stringify(all));
  } catch {
    /* 저장소를 쓸 수 없어도 이번 화면에서만 유지 */
  }
}
export function writeLegendPrefs(s: LegendSettings): void {
  const all = readAllV2();
  const memo: Record<string, unknown> = {};
  for (const k of LEGEND_KEYS) memo[k] = s[k];
  all.legend = memo;
  writeAll(all);
}
export function writeLayerPrefs(planKey: string, l: Required<LayerMemo>): void {
  const all = readAllV2();
  all[planKey] = { bc: l.bc, load: l.load, ghost: l.ghost, marks: l.marks };
  writeAll(all);
}
