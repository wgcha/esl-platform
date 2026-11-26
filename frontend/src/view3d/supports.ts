// 3-2-1 지지점 기호(계약 §6.3): 3성분 ▲(채움), 2성분 ◭(반 채움), 1성분 △(빈) + 구속 축 선분 + dofText 라벨.
import type { View3dSupport } from "../api/types";
import { dofText } from "../lib/format";
import type { V3 } from "./pick";
import { MARK_TABLE, dirVectors, isMarkKind, markSegments, type MarkKind } from "./supportMarks";

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
    if (mk) {
      const markSegs = markSegments(mk, p, dirVectors(s.dirs), mk === "tie_spring" || mk === "tie_disp" || mk === "aux_inplane" ? s.val : null, diag, gscale);
      return { nodeId: s.node_id, vertex: s.vertex, position: p, symbol, segments: [], markKind: mk, markSegs, markColor: MARK_TABLE[mk].color };
    }
    return { nodeId: s.node_id, vertex: s.vertex, position: p, symbol, segments, markKind: isMarkKind(s.kind) ? s.kind : null };
  });
}
