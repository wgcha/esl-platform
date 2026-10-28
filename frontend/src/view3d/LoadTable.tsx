// ④ F_eq 상위 노드 표 / 군집 합력 표(계약 §7). 표 행 수 = 화살표 수. 행 클릭 = 화살표·노드 강조, 더블클릭 = 카메라 중심 이동.
// 3D 에서 고른 항목은 aria-selected 행으로 표시하고 scrollIntoView({block:"nearest"}).
import { useEffect, useRef } from "react";
import type { ForcesOut, View3dTopRow } from "../api/types";
import { Badge, Card, Empty } from "../components/ui";
import { vec } from "../lib/format";
import { clusterOf, nodeCount } from "./arrows";
import { clusterRowSelected, nodeRowSelected } from "./selection";
import type { LoadView } from "./useLoadView";

const f1 = (v: number) => (Number.isFinite(v) ? v.toFixed(1) : "–");

function fallbackRows(f: ForcesOut): View3dTopRow[] {
  return f.rows.map((r, i) => ({ ...r, rank: i + 1, vertex: -1, fn: NaN, pa: NaN }));
}

export function LoadTable({ view }: { view: LoadView }) {
  const { manifest, fallback, selection, mode } = view;
  const selRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    selRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selection]);

  const cluster = manifest && mode.kind === "cluster" ? clusterOf(manifest, mode.k) : null;
  const rows: View3dTopRow[] = manifest ? manifest.top.slice(0, nodeCount(manifest, mode.kind === "nodes" ? mode.n : 0)) : fallback ? fallbackRows(fallback) : [];

  if (cluster && manifest) {
    return (
      <Card title="군집 합력" right={<span className="small muted">{cluster.rows.length}개 군집</span>}>
        <div className="table-wrap scroll">
          <table className="table compact" data-testid="load-table" data-mode="cluster">
            <thead>
              <tr>
                <th>군집</th>
                <th className="num">노드 수</th>
                <th className="num">중심 x</th>
                <th className="num">중심 y</th>
                <th className="num">중심 z</th>
                <th className="num">Rx</th>
                <th className="num">Ry</th>
                <th className="num">Rz</th>
                <th className="num">|R|</th>
                <th className="num">Σ|F|</th>
                <th className="num">상쇄율</th>
                <th className="num" title="군집 중심 기준 합모멘트(N·mm)">
                  |M_c|
                </th>
              </tr>
            </thead>
            <tbody>
              {cluster.rows.map((r) => {
                const sel = clusterRowSelected(selection, r.label);
                return (
                  <tr
                    key={r.label}
                    ref={sel ? selRef : undefined}
                    aria-selected={sel}
                    className={sel ? "sel" : undefined}
                    data-key={r.label}
                    onClick={() => view.setSelection(sel ? null : { kind: "arrow", key: r.label })}
                    onDoubleClick={() => view.requestFocus([r.center[0], r.center[1], r.center[2]])}
                  >
                    <td>
                      <strong>{r.label}</strong>
                    </td>
                    <td className="num">{r.n_nodes.toLocaleString()}</td>
                    <td className="num">{f1(r.center[0])}</td>
                    <td className="num">{f1(r.center[1])}</td>
                    <td className="num">{f1(r.center[2])}</td>
                    <td className="num">{f1(r.r[0])}</td>
                    <td className="num">{f1(r.r[1])}</td>
                    <td className="num">{f1(r.r[2])}</td>
                    <td className="num">
                      <strong>{f1(r.r_mag)}</strong>
                    </td>
                    <td className="num">{f1(r.sum_abs)}</td>
                    <td className="num">{(r.cancel * 100).toFixed(1)} %</td>
                    <td className="num">{r.m_mag.toExponential(3)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="small muted" data-testid="load-sum-line">
          ΣF = <span className="mono">{vec(manifest.sum_f)}</span> · ΣM = <span className="mono">{vec(manifest.sum_m)}</span> (자기평형, 군집 합력의 합 = ΣF)
        </div>
      </Card>
    );
  }

  return (
    <Card title="F_eq 상위 노드" right={manifest || fallback ? <span className="small muted">{rows.length}행</span> : undefined}>
      {manifest || fallback ? (
        <div className="table-wrap scroll">
          <table className="table compact" data-testid="load-table" data-mode="nodes">
            <thead>
              <tr>
                <th className="num">순위</th>
                <th>노드</th>
                <th className="num">x</th>
                <th className="num">y</th>
                <th className="num">z</th>
                <th className="num">Fx</th>
                <th className="num">Fy</th>
                <th className="num">Fz</th>
                <th className="num">|F|</th>
                <th className="num" title="면외(법선) 하중 성분, + = 판 기준 법선 쪽">
                  Fn
                </th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const sel = manifest ? nodeRowSelected(selection, f) : false;
                return (
                  <tr
                    key={f.rank}
                    ref={sel ? selRef : undefined}
                    aria-selected={sel}
                    className={sel ? "sel" : undefined}
                    data-key={f.rank}
                    onClick={() => manifest && view.setSelection(sel && selection?.kind === "arrow" ? null : { kind: "arrow", key: String(f.rank) })}
                    onDoubleClick={() => manifest && view.requestFocus([f.x, f.y, f.z])}
                  >
                    <td className="num">{f.rank}</td>
                    <td>{f.node_id}</td>
                    <td className="num">{f1(f.x)}</td>
                    <td className="num">{f1(f.y)}</td>
                    <td className="num">{f1(f.z)}</td>
                    <td className="num">{f1(f.fx)}</td>
                    <td className="num">{f1(f.fy)}</td>
                    <td className="num">{f1(f.fz)}</td>
                    <td className="num">
                      <strong>{f1(f.mag)}</strong>
                    </td>
                    <td className="num">{f1(f.fn)}</td>
                    <td>{f.is_support && <Badge kind="info">지지점</Badge>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>{view.loading ? "불러오는 중…" : "표를 불러오지 못했습니다"}</Empty>
      )}
    </Card>
  );
}
