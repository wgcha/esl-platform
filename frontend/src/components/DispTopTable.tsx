// 변위 오차 상위 노드 표(r = e/U 내림차순). 머리글 고정, 높이는 .table-wrap.scroll(--tbl-max). 지지 노드는 "지지" 표시.
import type { DispTopRow } from "../api/types";
import { sci } from "../lib/format";
import { f3 } from "../lib/colormap";
import { Empty } from "./ui";

export function DispTopTable({ top }: { top: DispTopRow[] }) {
  if (!top.length) return <Empty>상위 노드 없음</Empty>;
  return (
    <div className="table-wrap scroll" data-testid="disp-top">
      <table className="table compact" aria-label="변위 오차 상위 노드">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>노드</th>
            <th className="num">e/U</th>
            <th className="num">e (mm)</th>
            <th className="num">‖d_rel‖ (mm)</th>
            <th className="num">위치 (a, b)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {top.map((r, i) => (
            <tr key={r.node_id}>
              <td className="num">{i + 1}</td>
              <td>{r.node_id}</td>
              <td className="num">{sci(r.r)}</td>
              <td className="num">{sci(r.e)}</td>
              <td className="num">{f3(r.u_rel_mag)}</td>
              <td className="num">
                {f3(r.a)}, {f3(r.b)}
              </td>
              <td>{r.is_support ? <span className="badge neutral">지지</span> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
