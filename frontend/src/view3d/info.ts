// 좌하단 정보 줄(툴팁) 문구(계약 §7). 표면 색은 면압 |Fn|/A(MPa)이고, 노드힘 |Fn| N 은 여기(툴팁)와 표 Fn 열에서 수치로 보인다.
import type { View3dOut } from "../api/types";
import { fmtQuant, type DecodedValues } from "./values";
import type { Selection } from "./selection";
import { supportSymbol } from "./supports";
import { markProbe } from "./supportMarks";
import { f3 } from "../lib/colormap";

const fmt = (v: number, d = 1) => (Number.isFinite(v) ? v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–");

/** v0.24.6 탐침 보강(§2.5): 색 필드 값(변위 보기 — 하중 보기는 면압·|Fn|·|F| 가 이미 색 필드) · u 성분 · 기준 좌표 */
export interface ProbeExtra {
  color?: { short: string; values: ArrayLike<number>; unit: string; /** 양자화 간격(values.bin) — null = recon float32 → f3 */ step: number | null } | null;
  /** 지금 보이는 u(3n) */
  u?: ArrayLike<number> | null;
  /** u 성분별 양자화 간격(values.bin) — null = f3 */
  uStep?: [number, number, number] | null;
  /** 기준 위치 x0(3n, 변형 전) */
  xyz?: ArrayLike<number> | null;
}

/** 색 범례 문구에서 단위 괄호를 뺀 짧은 이름: "목표 변위 |u_tgt| (mm)" → "목표 변위 |u_tgt|" */
export const shortFieldName = (label: string): string => label.replace(/\s*\([^)]*\)\s*$/, "").trim();

export function infoLine(sel: Selection, manifest: View3dOut, vals: DecodedValues | null, nodeIds: ArrayLike<number> | null, extra?: ProbeExtra | null): string | null {
  if (!sel) return null;
  if (sel.kind === "support") {
    const s = manifest.supports[sel.index];
    return s ? markProbe(s) ?? `지지 ${s.node_id} · dof ${supportSymbol(s.dof).label}` : null;
  }
  if (sel.kind === "arrow") {
    const row = manifest.top.find((r) => String(r.rank) === sel.key);
    if (row) return vertexLine(row.node_id, row.vertex, vals, row.mag, row.fn, true, extra);
    for (const c of Object.values(manifest.clusters ?? {})) {
      const r = c.rows.find((x) => x.label === sel.key);
      if (r) return `군집 ${r.label} · 노드 ${r.n_nodes.toLocaleString()} · |R| ${fmt(r.r_mag)} N · 상쇄율 ${fmt(r.cancel * 100, 0)} % · |M| ${fmt(r.m_mag, 0)} N·mm`;
    }
    return null;
  }
  const id = nodeIds ? nodeIds[sel.vertex] : manifest.top.find((r) => r.vertex === sel.vertex)?.node_id;
  return vertexLine(id ?? sel.vertex, sel.vertex, vals, vals?.fmag ? vals.fmag[sel.vertex] : null, vals?.fn ? vals.fn[sel.vertex] : null, false, extra);
}

/** exact = manifest 정확값(상위 행), 아니면 양자화 복원값을 간격까지만 표기 */
function vertexLine(nodeId: number, vertex: number, v: DecodedValues | null, mag: number | null, fn: number | null, exact: boolean, extra?: ProbeExtra | null): string {
  const parts = [`노드 ${nodeId}`];
  const c = extra?.color;
  if (c) {
    const x = c.values[vertex];
    parts.push(`${c.short} ${c.step ? fmtQuant(x, c.step) : f3(x)} ${c.unit}`);
  }
  const u = extra?.u;
  if (u && vertex * 3 + 2 < u.length) {
    const q = (i: number) => (extra?.uStep ? fmtQuant(u[vertex * 3 + i], extra.uStep[i]) : f3(u[vertex * 3 + i]));
    parts.push(`u (${q(0)}, ${q(1)}, ${q(2)}) mm`);
  }
  if (v?.pa) parts.push(`면압 ${fmtQuant(v.pa[vertex], v.scale.pa)} MPa`);
  if (fn !== null && Number.isFinite(fn)) {
    const q = (x: number) => (exact || !v?.scale.fn ? fmt(x) : fmtQuant(x, v.scale.fn));
    parts.push(`|Fn| ${q(Math.abs(fn))} N (Fn ${q(fn)})`);
  }
  if (mag !== null && Number.isFinite(mag)) parts.push(`|F| ${exact || !v?.scale.fmag ? fmt(mag) : fmtQuant(mag, v.scale.fmag)} N`);
  const p = extra?.xyz;
  if (p && vertex * 3 + 2 < p.length) parts.push(`(${fmt(p[vertex * 3])}, ${fmt(p[vertex * 3 + 1])}, ${fmt(p[vertex * 3 + 2])}) mm`);
  return parts.join(" · ");
}
