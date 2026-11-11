// 경계 매핑 경고 접힘 표(라벨·거리·기준) — v0.9 BoundaryLegend 의 표 부분(범례는 PartView 층 칩이 맡음, VU-D-6).
// nWarn = 연구 prep.boundary.n_warn(서버 판정 경고 수). B 체결 후보가 0 이면 경고는 있어도 선(links)이 없다(§8.2 "B 후보 0 → 전부 경고")
import { linkThreshold } from "./planGeom";
import type { PartWarnings } from "./types";

const KIND_NAME: Record<string, string> = { fastener: "체결", load: "하중", support: "3-2-1" };

export function BoundaryWarnList({ w }: { w: PartWarnings }) {
  const warns = w.links.filter((l) => l.warn);
  const total = Math.max(warns.length, w.nWarn ?? 0);
  return (
    <details className="doe-warn-list" open={total > 0}>
      <summary className="small">
        경계 경고 <b data-testid="boundary-warn-n">{total}</b>
        <span className="muted"> · 차단 아님</span>
      </summary>
      {warns.length ? (
        <table className="table compact" aria-label="경계 경고">
          <thead>
            <tr>
              <th>A</th>
              <th>B 최근접</th>
              <th className="num">거리</th>
              {w.st && <th className="num">기준</th>}
            </tr>
          </thead>
          <tbody>
            {warns.map((l, i) => (
              <tr key={i}>
                <td>
                  {l.from} {l.kind && <span className="small muted">{KIND_NAME[l.kind]}</span>}
                </td>
                <td>{l.to}</td>
                <td className="num mono">{l.d_mm.toFixed(1)} mm</td>
                {w.st && <td className="num mono">&gt; {linkThreshold(l, w.st)} mm</td>}
              </tr>
            ))}
          </tbody>
        </table>
      ) : total > 0 ? (
        <div className="small warn-text" data-testid="boundary-no-cand">
          B 체결 후보(구멍·고정 클러스터)가 없어 A 체결점·하중 집중부 {total}개가 모두 경고입니다(잇는 선 없음)
        </div>
      ) : (
        <div className="small muted">경고 없음</div>
      )}
    </details>
  );
}
