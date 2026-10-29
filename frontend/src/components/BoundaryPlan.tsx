// 비드 DOE ③ 평면도(esl_bead_doe.md §8.2·§12.2): 비드 번호 + 경계 매핑 경고(②③). KeepoutPlan 과 같은 좌표·스타일(ko-*):
// B 외곽·구멍(회색), B 고정 클러스터(파랑 점), A 체결점(주황 ×), A 하중 집중(빨강 원, 크기 ∝ 비율), 경고 쌍(빨강 점선). 차단 없음.
import type { DoePlanLink, DoePlanOut, DoeSettingsOut, XY } from "../api/types";

const KIND_NAME: Record<string, string> = { fastener: "체결", load: "하중", support: "3-2-1" };

export function linkThreshold(l: DoePlanLink, st: DoeSettingsOut): number {
  return l.kind === "load" ? st.boundary.load_warn_mm : st.boundary.fastener_warn_mm;
}

export function BoundaryPlan({ plan, showLinks }: { plan: DoePlanOut; showLinks: boolean }) {
  const f = plan.frame;
  const [a0, a1] = f.a_range;
  const [b0, b1] = f.b_range;
  const Lx = a1 - a0;
  const Hy = b1 - b0;
  const S = Math.max(Lx, Hy);
  const pad = S * 0.035;
  const vb = { x: -pad, y: -pad * 0.6, w: Lx + pad * 1.6, h: Hy + pad * 1.9 };
  const X = (a: number) => a - a0;
  const Y = (b: number) => b1 - b;
  const poly = (pts: XY[]) => `M${pts.map(([a, b]) => `${X(a).toFixed(1)},${Y(b).toFixed(1)}`).join("L")}Z`;
  const cx = (pts: XY[]) => [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length] as XY;
  const fs = S / 55;
  const xs = S / 120;
  return (
    <svg className="keepout-svg doe-plan" viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} role="img" aria-label="비드·경계 평면도">
      <path d={poly(plan.outline)} className="ko-outline" />
      <g className="ko-points" aria-hidden="true">
        {plan.elems.points.map(([a, b, pid], i) => (
          <circle key={i} cx={X(a)} cy={Y(b)} r={S / 700} className={pid % 2 ? "p1" : "p2"} />
        ))}
      </g>
      {plan.holes.map((h, i) => (
        <path key={i} d={poly(h)} className="ko-hole" />
      ))}
      {plan.beads.map((b) => {
        const [ca, cb] = cx(b.ring);
        return (
          <g key={b.id} className="doe-bead" data-testid={`plan-bead-${b.id}`}>
            <path d={poly(b.ring)} />
            <text x={X(ca)} y={Y(cb)} textAnchor="middle" dominantBaseline="middle" fontSize={fs}>
              {b.id}
            </text>
          </g>
        );
      })}
      {plan.fixed.map((p) => (
        <circle key={p.label} cx={X(p.a)} cy={Y(p.b)} r={S / 160} className="doe-fixed">
          <title>{`${p.label} (${p.kind})`}</title>
        </circle>
      ))}
      {showLinks &&
        plan.links
          .filter((l) => l.warn && l.from_ab && l.to_ab)
          .map((l, i) => <line key={i} x1={X(l.from_ab![0])} y1={Y(l.from_ab![1])} x2={X(l.to_ab![0])} y2={Y(l.to_ab![1])} className="doe-link warn" data-testid="plan-warn-link" strokeWidth={S / 500} strokeDasharray={`${S / 120} ${S / 200}`} />)}
      {plan.load_points.map((p, i) => (
        <circle key={i} cx={X(p.a)} cy={Y(p.b)} r={(S / 60) * Math.sqrt(Math.max(0.05, p.share))} className="doe-load">
          <title>{`하중 집중 ${p.entry_id} · ${Math.round(p.share * 100)}%`}</title>
        </circle>
      ))}
      {plan.a_points.map((p) => (
        <g key={p.label} className="doe-apt">
          <path d={`M${X(p.a) - xs},${Y(p.b) - xs}L${X(p.a) + xs},${Y(p.b) + xs}M${X(p.a) - xs},${Y(p.b) + xs}L${X(p.a) + xs},${Y(p.b) - xs}`} strokeWidth={S / 450} />
          <title>{`A ${p.label}`}</title>
        </g>
      ))}
      <g className="ko-axis" fontSize={S / 75}>
        <text x={0} y={Hy + pad * 0.9} textAnchor="start">
          0
        </text>
        <text x={Lx} y={Hy + pad * 0.9} textAnchor="end">
          {Math.round(Lx)} mm (ξ)
        </text>
        <text x={-pad * 0.15} y={0} textAnchor="end" dominantBaseline="hanging">
          {Math.round(Hy)}
        </text>
        <text x={-pad * 0.15} y={Hy} textAnchor="end">
          0 (η)
        </text>
      </g>
    </svg>
  );
}

/** 평면도 범례 + 경계 경고 접힘 목록(라벨·거리·기준) */
/** nWarn = 연구 prep.boundary.n_warn(서버 판정 경고 수). B 체결 후보가 0 이면 경고는 있어도 선(links)이 없다(§8.2 "B 후보 0 → 전부 경고") */
export function BoundaryLegend({ plan, st, showLinks, nWarn }: { plan: DoePlanOut; st: DoeSettingsOut; showLinks: boolean; nWarn?: number | null }) {
  const warns = plan.links.filter((l) => l.warn);
  const total = Math.max(warns.length, nWarn ?? 0);
  return (
    <div className="doe-plan-side">
      <div className="doe-legend small">
        <span>
          <i className="lg-bead" /> 비드
        </span>
        {plan.fixed.length > 0 && (
          <span>
            <i className="lg-fixed" /> B 고정
          </span>
        )}
        <span>
          <i className="lg-hole" /> B 구멍
        </span>
        {showLinks && (
          <>
            <span>
              <i className="lg-apt">×</i> A 체결
            </span>
            <span>
              <i className="lg-load" /> A 하중 집중
            </span>
          </>
        )}
      </div>
      {showLinks && (
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
                  <th className="num">기준</th>
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
                    <td className="num mono">&gt; {linkThreshold(l, st)} mm</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : total > 0 ? (
            <div className="small warn-text" data-testid="boundary-no-cand">B 체결 후보(구멍·고정 클러스터)가 없어 A 체결점·하중 집중부 {total}개가 모두 경고입니다(잇는 선 없음)</div>
          ) : (
            <div className="small muted">경고 없음</div>
          )}
        </details>
      )}
    </div>
  );
}
