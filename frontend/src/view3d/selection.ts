// 표 행 ↔ 3D 선택 연동의 순수 부분(계약 §7). 선택은 화면 상태(URL 없음).
import type { View3dOut, View3dTopRow } from "../api/types";
import type { ArrowMode } from "./arrows";
import type { PickEvent } from "./sceneApi";

export type Selection =
  | { kind: "arrow"; key: string } // 노드 모드 = rank, 군집 모드 = 라벨
  | { kind: "vertex"; vertex: number }
  | { kind: "support"; index: number }
  | null;

/** 현재 모드에서 보이는 화살표 키(= 표 행 키) */
export function visibleKeys(src: Pick<View3dOut, "top" | "clusters">, mode: ArrowMode): string[] {
  if (mode.kind === "nodes") return src.top.slice(0, mode.n).map((r) => String(r.rank));
  return (src.clusters?.[String(mode.k)]?.rows ?? []).map((r) => r.label);
}

/** 화살표 개수가 바뀌어 사라진 화살표 선택은 해제 */
export function reconcile(sel: Selection, keys: string[]): Selection {
  if (sel && sel.kind === "arrow" && !keys.includes(sel.key)) return null;
  return sel;
}

/** 3D 에서 온 선택 → 선택 상태. 화살표 번호는 현재 화살표 배열 기준 */
export function selectionFromPick(e: PickEvent, arrowKeys: string[]): Selection {
  if (e.type === "arrow") return arrowKeys[e.index] !== undefined ? { kind: "arrow", key: arrowKeys[e.index] } : null;
  if (e.type === "vertex") return { kind: "vertex", vertex: e.vertex };
  if (e.type === "support") return { kind: "support", index: e.index };
  return null;
}

/** 노드 모드 표 행이 선택 상태인가 — 화살표 선택이거나, 표면에서 고른 정점이 이 행의 노드일 때 */
export function nodeRowSelected(sel: Selection, row: Pick<View3dTopRow, "rank" | "vertex">): boolean {
  if (!sel) return false;
  if (sel.kind === "arrow") return sel.key === String(row.rank);
  if (sel.kind === "vertex") return sel.vertex === row.vertex;
  return false;
}
export function clusterRowSelected(sel: Selection, label: string): boolean {
  return !!sel && sel.kind === "arrow" && sel.key === label;
}

/** 장면에 넘길 선택 강조: 화살표 번호 + 노드 표식 정점 */
export function sceneSelection(
  sel: Selection,
  arrows: { key: string; vertex: number | null }[],
  supports: { vertex: number }[],
  top: View3dTopRow[],
): { arrowIndex: number | null; vertex: number | null } {
  if (!sel) return { arrowIndex: null, vertex: null };
  if (sel.kind === "arrow") {
    const i = arrows.findIndex((a) => a.key === sel.key);
    return { arrowIndex: i >= 0 ? i : null, vertex: i >= 0 ? arrows[i].vertex : null };
  }
  if (sel.kind === "vertex") {
    const i = top.length ? arrows.findIndex((a) => a.vertex === sel.vertex) : -1;
    return { arrowIndex: i >= 0 ? i : null, vertex: sel.vertex };
  }
  return { arrowIndex: null, vertex: supports[sel.index]?.vertex ?? null };
}
