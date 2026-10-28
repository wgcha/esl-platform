// 좌하단 정보 줄(툴팁) 문구(계약 §7). 표면 색은 면압 |Fn|/A(MPa)이고, 노드힘 |Fn| N 은 여기(툴팁)와 표 Fn 열에서 수치로 보인다.
import type { View3dOut } from "../api/types";
import { fmtQuant, type DecodedValues } from "./values";
import type { Selection } from "./selection";
import { supportSymbol } from "./supports";

const fmt = (v: number, d = 1) => (Number.isFinite(v) ? v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–");

export function infoLine(sel: Selection, manifest: View3dOut, vals: DecodedValues | null, nodeIds: ArrayLike<number> | null): string | null {
  if (!sel) return null;
  if (sel.kind === "support") {
    const s = manifest.supports[sel.index];
    return s ? `지지 ${s.node_id} · dof ${supportSymbol(s.dof).label}` : null;
  }
  if (sel.kind === "arrow") {
    const row = manifest.top.find((r) => String(r.rank) === sel.key);
    if (row) return vertexLine(row.node_id, row.vertex, vals, row.mag, row.fn, true);
    for (const c of Object.values(manifest.clusters ?? {})) {
      const r = c.rows.find((x) => x.label === sel.key);
      if (r) return `군집 ${r.label} · 노드 ${r.n_nodes.toLocaleString()} · |R| ${fmt(r.r_mag)} N · 상쇄율 ${fmt(r.cancel * 100, 0)} % · |M| ${fmt(r.m_mag, 0)} N·mm`;
    }
    return null;
  }
  const id = nodeIds ? nodeIds[sel.vertex] : manifest.top.find((r) => r.vertex === sel.vertex)?.node_id;
  return vertexLine(id ?? sel.vertex, sel.vertex, vals, vals?.fmag ? vals.fmag[sel.vertex] : null, vals?.fn ? vals.fn[sel.vertex] : null, false);
}

/** exact = manifest 정확값(상위 행), 아니면 양자화 복원값을 간격까지만 표기 */
function vertexLine(nodeId: number, vertex: number, v: DecodedValues | null, mag: number | null, fn: number | null, exact: boolean): string {
  const parts = [`노드 ${nodeId}`];
  if (v?.pa) parts.push(`면압 ${fmtQuant(v.pa[vertex], v.scale.pa)} MPa`);
  if (fn !== null && Number.isFinite(fn)) {
    const q = (x: number) => (exact || !v?.scale.fn ? fmt(x) : fmtQuant(x, v.scale.fn));
    parts.push(`|Fn| ${q(Math.abs(fn))} N (Fn ${q(fn)})`);
  }
  if (mag !== null && Number.isFinite(mag)) parts.push(`|F| ${exact || !v?.scale.fmag ? fmt(mag) : fmtQuant(mag, v.scale.fmag)} N`);
  return parts.join(" · ");
}
