// v0.24.6 구간 겹침 범례(esl_viewer_hv.md §2.4): 3D 칸 왼쪽 위에 겹친다. 연속(levels 0)이면 렌더 없음.
// 제목(문구 + 단위) · 위 = 최대 → 아래 = 최소 순 L 칸 · 경계값 L+1 개(f3) · 범위 밖 ▲/▼ 개수 · 최대 표식 한 줄. pointer-events 없음.
import { f3 } from "../lib/colormap";
import { bluesSrgb } from "./colors";
import type { Range } from "../components/ColorLegend";

/** 경계값 간격이 이 값(rem) 미만이면 한 칸 걸러 표시 */
export const MIN_LABEL_GAP_REM = 0.9;
/** 칸 한 개 높이 상한(rem) */
export const BAND_MAX_REM = 1.5;
/** 범례 막대가 칸 높이에서 쓸 수 있는 비율(제목·줄 여유 제외) */
const HEIGHT_SHARE = 0.55;

/** 보일 경계값 번호(0 = 최소 … L = 최대). 간격이 모자라면 한 칸 걸러(최대·최소는 항상) */
export function boundaryIndices(levels: number, bandPx: number, remPx: number): number[] {
  const all = Array.from({ length: levels + 1 }, (_, i) => i);
  if (bandPx >= MIN_LABEL_GAP_REM * remPx) return all;
  return all.filter((i) => i === 0 || i === levels || i % 2 === 0);
}

export function LegendOverlay({
  levels,
  range,
  title,
  above = 0,
  below = 0,
  maxLine,
  hostHeight,
  remPx = 16,
}: {
  levels: number;
  range: Range;
  title: string;
  above?: number;
  below?: number;
  /** 최대 표식이 켜졌을 때 "최대 v @N id" */
  maxLine?: string | null;
  /** 3D 칸 높이(px) — 칸이 낮으면 칸 높이를 줄이고 경계값을 거른다 */
  hostHeight: number;
  remPx?: number;
}) {
  if (!(levels > 0)) return null;
  const bandPx = Math.max(2, Math.min(BAND_MAX_REM * remPx, (hostHeight * HEIGHT_SHARE) / levels));
  const shown = new Set(boundaryIndices(levels, bandPx, remPx));
  const value = (i: number) => range.min + ((range.max - range.min) * i) / levels;
  const rows = Array.from({ length: levels }, (_, k) => levels - 1 - k); // 위 = 최대
  const c = (b: number) => bluesSrgb((b + 0.5) / levels).map(Math.round).join(",");
  return (
    <div className="v3d-legend-ov mono small" data-testid="v3d-legend-ov" data-levels={levels} aria-hidden="true">
      <div className="v3d-legend-ov-title">{title}</div>
      {above > 0 && <div className="v3d-legend-ov-out" data-testid="v3d-legend-ov-above">▲ {above.toLocaleString()}</div>}
      <div className="v3d-legend-ov-bar">
        {rows.map((b) => (
          <div key={b} className="v3d-legend-ov-band" style={{ height: bandPx }} data-band={b}>
            <span className="v3d-legend-ov-sw" style={{ background: `rgb(${c(b)})` }} />
            <span className="v3d-legend-ov-val" data-testid={shown.has(b + 1) ? "v3d-legend-ov-tick" : undefined}>
              {shown.has(b + 1) ? f3(value(b + 1)) : ""}
            </span>
          </div>
        ))}
        <div className="v3d-legend-ov-band v3d-legend-ov-last" style={{ height: 0 }}>
          <span className="v3d-legend-ov-sw" style={{ background: "transparent" }} />
          <span className="v3d-legend-ov-val" data-testid="v3d-legend-ov-tick">
            {f3(value(0))}
          </span>
        </div>
      </div>
      {below > 0 && <div className="v3d-legend-ov-out" data-testid="v3d-legend-ov-below">▼ {below.toLocaleString()}</div>}
      {maxLine && <div className="v3d-legend-ov-max" data-testid="v3d-legend-ov-max">{maxLine}</div>}
    </div>
  );
}
