// 3-2-1 지지점 기호(계약 §6.3): 3성분 ▲(채움), 2성분 ◭(반 채움), 1성분 △(빈) + 구속 축 선분 + dofText 라벨.
import type { View3dSupport } from "../api/types";
import { dofText } from "../stages/Stage3";
import type { V3 } from "./pick";

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
}

export function buildSupportSpecs(supports: View3dSupport[], u: ArrayLike<number> | null, kscale: number, diag: number): SupportSpec[] {
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
    return { nodeId: s.node_id, vertex: s.vertex, position: p, symbol, segments };
  });
}
