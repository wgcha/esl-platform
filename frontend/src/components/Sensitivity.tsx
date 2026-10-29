// 비드 DOE 민감도(esl_bead_doe.md §11): 변수별 SRC(표준화 회귀계수)·Spearman ρ 막대(−1~1), R², 풀 팩토리얼은 주효과 병기(툴팁).
// score 는 작을수록 좋음 → 음수(왼쪽) = 그 변수를 키우면 강성 개선.
import type { DoeParam, DoeResultOut } from "../api/types";
import { warnText } from "../api/doe";
import { shortName } from "./DoeThumbGrid";
import { Empty } from "./ui";

export function Sensitivity({ sens, params, warnings }: { sens: DoeResultOut["sensitivity"]; params: DoeParam[]; warnings: DoeResultOut["warnings"] }) {
  if (!sens) {
    const w = warnings.find((x) => x.code === "SENSITIVITY_TOO_FEW" || x.code === "NO_FEASIBLE_DESIGNS");
    return <Empty>{w ? warnText(w) : "민감도 없음"}</Empty>;
  }
  const rows = [...sens.params].sort((a, b) => Math.abs(b.src) - Math.abs(a.src) || a.name.localeCompare(b.name));
  const W = 640;
  const rowH = 30;
  const left = 110;
  const right = 16;
  const H = rows.length * rowH + 34;
  const x = (v: number) => left + ((Math.max(-1, Math.min(1, v)) + 1) / 2) * (W - left - right);
  return (
    <div className="chart doe-sens">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="민감도 막대(SRC·Spearman)">
        <line className="chart-axis" x1={x(0)} y1={4} x2={x(0)} y2={H - 26} />
        {[-1, -0.5, 0, 0.5, 1].map((v) => (
          <text key={v} className="chart-tick" x={x(v)} y={H - 10} textAnchor="middle">
            {v}
          </text>
        ))}
        {rows.map((p, i) => {
          const y = 6 + i * rowH;
          const bar = (v: number, dy: number, cls: string) => <rect className={cls} x={Math.min(x(0), x(v))} y={y + dy} width={Math.abs(x(v) - x(0))} height={10} />;
          return (
            <g key={p.name} data-testid={`sens-${p.name}`}>
              <text className="chart-tick" x={left - 8} y={y + 14} textAnchor="end">
                {shortName(params, p.name)}
              </text>
              {bar(p.src, 2, "doe-bar-src")}
              {bar(p.spearman, 13, "doe-bar-rho")}
              <title>{`${p.name} · SRC ${p.src.toFixed(3)} · ρ ${p.spearman.toFixed(3)}${p.main_effects ? ` · 주효과 ${p.main_effects.map((m) => `${m.level}:${m.mean.toFixed(3)}`).join(" ")}` : ""}`}</title>
            </g>
          );
        })}
      </svg>
      <div className="small muted doe-sens-legend">
        <span>
          <i className="lg-src" /> SRC
        </span>
        <span>
          <i className="lg-rho" /> Spearman ρ
        </span>
        <span data-testid="sens-r2">R² {sens.r2.toFixed(2)}</span>
        <span>음수 = 값을 키우면 score 감소(강성 개선)</span>
      </div>
    </div>
  );
}
