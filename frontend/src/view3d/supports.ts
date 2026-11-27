// 3-2-1 지지점 기호(계약 §6.3): 3성분 ▲(채움), 2성분 ◭(반 채움), 1성분 △(빈) + 구속 축 선분 + dofText 라벨.
import type { View3dSupport, View3dTieMark } from "../api/types";
import { dofText } from "../lib/format";
import type { V3 } from "./pick";
import { MARK_TABLE, TIE_PX, TIE_RING_N, TIE_RING_R, TIE_TABLE, dirVectors, isMarkKind, markSegments, perpOf, type MarkKind } from "./supportMarks";

export const SUPPORT_COLOR = "#1b9e77";
export type SymbolKind = "filled" | "half" | "empty";
export const SYMBOL_GLYPH: Record<SymbolKind, string> = { filled: "▲", half: "◭", empty: "△" };

export interface SupportSymbol {
  kind: SymbolKind;
  /** 구속된 전역 축 번호(0=x, 1=y, 2=z). dof 가 숫자가 아니면(예 "ij") 빈 배열 */
  axes: number[];
  count: number;
  label: string;
}

export function supportSymbol(dof: string): SupportSymbol {
  const digits = /^[123]+$/.test(dof);
  const axes = digits ? [...new Set(dof.split("").map((c) => Number(c) - 1))].sort() : [];
  const count = digits ? axes.length : dof.length;
  const kind: SymbolKind = count >= 3 ? "filled" : count === 2 ? "half" : "empty";
  return { kind, axes, count, label: dofText(dof) };
}

export interface SupportSpec {
  nodeId: number;
  vertex: number;
  position: V3;
  symbol: SupportSymbol;
  /** 구속 축 선분 (노드 양쪽, 길이 0.04·diag 씩) */
  segments: [V3, V3][];
  /** v0.23.3 기호 색(없으면 SUPPORT_COLOR) — 지그 진단의 상대 부품별 색 */
  color?: string;
  /** v0.24.9 방식별 기호 종류(없음 = 옛 파일 dof 기호). support321 은 기존 기호 그대로 */
  markKind?: MarkKind | null;
  /** 방식별 기호 선분(markKind 가 tie_*·aux_inplane 일 때만) — 기호 색 = markColor */
  markSegs?: [V3, V3][];
  markColor?: string;
  /** v0.25.2 §4.3 강제로 붙인 지지(via force) — 테두리 색(없으면 일반 표식) */
  outline?: string;
}

export function buildSupportSpecs(supports: View3dSupport[], u: ArrayLike<number> | null, kscale: number, diag: number, gscale = 1): SupportSpec[] {
  return supports.map((s) => {
    const k = u && kscale ? kscale : 0;
    const p: V3 = [s.x0[0] + k * (u?.[s.vertex * 3] ?? 0), s.x0[1] + k * (u?.[s.vertex * 3 + 1] ?? 0), s.x0[2] + k * (u?.[s.vertex * 3 + 2] ?? 0)];
    const symbol = supportSymbol(s.dof);
    const L = 0.04 * diag;
    const segments = symbol.axes.map((ax): [V3, V3] => {
      const a: V3 = [...p];
      const b: V3 = [...p];
      a[ax] -= L;
      b[ax] += L;
      return [a, b];
    });
    const mk = isMarkKind(s.kind) && s.kind !== "support321" ? s.kind : null;
    const outline = s.via === "force" ? TIE_TABLE.force.color : undefined;
    if (mk) {
      const markSegs = markSegments(mk, p, dirVectors(s.dirs), mk === "tie_spring" || mk === "tie_disp" || mk === "aux_inplane" ? s.val : null, diag, gscale);
      return { nodeId: s.node_id, vertex: s.vertex, position: p, symbol, segments: [], markKind: mk, markSegs, markColor: MARK_TABLE[mk].color, ...(outline ? { outline } : {}) };
    }
    return { nodeId: s.node_id, vertex: s.vertex, position: p, symbol, segments, markKind: isMarkKind(s.kind) ? s.kind : null, ...(outline ? { outline } : {}) };
  });
}

/** v0.25.2 §4.3 Case 체결부 자리(강제) 빈 고리 + 붙인 곳까지 가는 선(먼 강제 = 빨강 굵은 선) · 못 붙인 체결부 ✕ — 선 층 목록과 클릭 탐침 자리 */
export interface TieLayer {
  color: string;
  widthPx: number;
  segs: [V3, V3][];
}
export interface TieMarkSpec {
  layers: TieLayer[];
  /** 탐침(클릭) 자리: marks 배열 위치 → 고리·✕ 중심 */
  picks: { index: number; pos: V3 }[];
}

const sub3 = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dist3 = (a: V3, b: V3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** marks = manifest.tie_marks. 선의 끝 = 그 고리에서 가장 가까운 "강제" 지지 노드(지금 보이는 위치 — 변형 켬이면 변형 반영). 법선 n = 판 법선(고리·✕ 면) */
export function buildTieMarks(marks: View3dTieMark[], specs: SupportSpec[], diag: number, normal: ArrayLike<number> | null | undefined): TieMarkSpec {
  const L = 0.04 * diag;
  const nn: V3 = normal && normal.length >= 3 && Math.hypot(normal[0], normal[1], normal[2]) > 1e-9 ? [normal[0], normal[1], normal[2]] : [0, 0, 1];
  const u = perpOf(nn);
  const w: V3 = [nn[1] * u[2] - nn[2] * u[1], nn[2] * u[0] - nn[0] * u[2], nn[0] * u[1] - nn[1] * u[0]];
  const ptAt = (c: V3, a: number, r: number): V3 => [c[0] + r * (Math.cos(a) * u[0] + Math.sin(a) * w[0]), c[1] + r * (Math.cos(a) * u[1] + Math.sin(a) * w[1]), c[2] + r * (Math.cos(a) * u[2] + Math.sin(a) * w[2])];
  const forced = specs.filter((s) => s.outline);
  const ring: TieLayer = { color: TIE_TABLE.ring.color, widthPx: TIE_PX.ring, segs: [] };
  const line: TieLayer = { color: TIE_TABLE.ring.color, widthPx: TIE_PX.line, segs: [] };
  const far: TieLayer = { color: TIE_TABLE.far.color, widthPx: TIE_PX.far, segs: [] };
  const miss: TieLayer = { color: TIE_TABLE.miss.color, widthPx: TIE_PX.ring, segs: [] };
  const picks: TieMarkSpec["picks"] = [];
  marks.forEach((m, index) => {
    if (m.x.length < 3) return;
    const c: V3 = [m.x[0], m.x[1], m.x[2]];
    picks.push({ index, pos: c });
    const r = TIE_RING_R * L;
    if (m.via === "miss") {
      miss.segs.push([ptAt(c, Math.PI / 4, r * 1.2), ptAt(c, (5 * Math.PI) / 4, r * 1.2)], [ptAt(c, (3 * Math.PI) / 4, r * 1.2), ptAt(c, (7 * Math.PI) / 4, r * 1.2)]);
      return;
    }
    for (let i = 0; i < TIE_RING_N; i++) ring.segs.push([ptAt(c, (2 * Math.PI * i) / TIE_RING_N, r), ptAt(c, (2 * Math.PI * (i + 1)) / TIE_RING_N, r)]);
    let best: SupportSpec | null = null;
    let bd = Infinity;
    for (const s of forced) {
      const d = dist3(s.position, c);
      if (d < bd) {
        bd = d;
        best = s;
      }
    }
    if (best && bd > r) {
      // 고리 가장자리에서 시작 — 선 길이 = 옮긴 거리 그대로(중심 ~ 붙인 곳)
      const dir = sub3(best.position, c);
      const k = r / bd;
      (m.far ? far : line).segs.push([[c[0] + dir[0] * k, c[1] + dir[1] * k, c[2] + dir[2] * k], best.position]);
    }
  });
  return { layers: [line, far, ring, miss].filter((l) => l.segs.length), picks };
}
