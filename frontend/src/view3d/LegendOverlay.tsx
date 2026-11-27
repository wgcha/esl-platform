// 겹침 범례(왼쪽 위, v0.24.6 → v0.25.1 계약 §5.4): **항상 표시**. 연속 = 매끄러운 세로 띠 + 눈금 5개, 레벨 = L 칸 + 경계값 L+1 개.
// 제목(문구 + 단위) · 범위 밖 ▲/▼ 개수 · 최대·최소 표식 줄. 클릭(또는 Enter) = 범례 편집 팝오버(children — ⚙ 팝오버의 범례 절과 같은 LegendEditor).
// 칸 위 겹침(absolute)이라 레이아웃 영향 0. 색 = lib/colormap(자원 역할) — 이 파일에 색 정점 없음.
import type { KeyboardEvent, ReactNode } from "react";
import { css, mapFor, specialCss, cssGradient, type ColorRole } from "../lib/colormap";
import { boundaries, formatValue, ticks, type LegendScale, type NumFormat, type Range } from "./legend/legendModel";

/** 경계값 간격이 이 값(rem) 미만이면 한 칸 걸러 표시 */
export const MIN_LABEL_GAP_REM = 0.9;
/** 칸 한 개 높이 상한(rem) */
export const BAND_MAX_REM = 1.5;
/** 범례 막대가 칸 높이에서 쓸 수 있는 비율(제목·줄 여유 제외) */
const HEIGHT_SHARE = 0.55;
/** 연속 띠 높이 상한(rem) */
const BAR_MAX_REM = 11;

/** 보일 경계값 번호(0 = 최소 … L = 최대). 간격이 모자라면 한 칸 걸러(최대·최소는 항상) */
export function boundaryIndices(levels: number, bandPx: number, remPx: number): number[] {
  const all = Array.from({ length: levels + 1 }, (_, i) => i);
  if (bandPx >= MIN_LABEL_GAP_REM * remPx) return all;
  return all.filter((i) => i === 0 || i === levels || i % 2 === 0);
}

export interface LegendOverlayProps {
  /** 0 = 연속 */
  levels: number;
  range: Range;
  title: string;
  /** 눈금 종류(기본 선형) — 범위는 effectiveRange 를 거친 것 */
  scale?: LegendScale;
  /** 색 역할(기본 seq) */
  role?: ColorRole;
  reversed?: boolean;
  format?: NumFormat;
  digits?: number;
  above?: number;
  below?: number;
  /** 범위 밖을 회색으로 칠하는 중이면 ▲▼ 옆에 회색 견본 */
  outGray?: boolean;
  /** "최대 v @N id" · "최소 v @N id" (표식이 켜졌을 때) */
  maxLine?: string | null;
  minLine?: string | null;
  /** 3D 칸 높이(px) — 칸이 낮으면 칸 높이를 줄이고 경계값을 거른다 */
  hostHeight: number;
  remPx?: number;
  /** 눌렀을 때(범례 편집 열기·닫기). 없으면 눌러지지 않는 표시만 */
  onOpen?: () => void;
  open?: boolean;
  /** 팝오버(LegendEditor) — 범례 아래에 겹침 */
  children?: ReactNode;
}

export function LegendOverlay({ levels, range, title, scale = "linear", role = "seq", reversed = false, format = "auto", digits = 3, above = 0, below = 0, outGray = false, maxLine, minLine, hostHeight, remPx = 16, onOpen, open, children }: LegendOverlayProps) {
  const map = mapFor(role);
  const fmt = (v: number) => formatValue(v, format, digits);
  const col = (t: number) => css(map, reversed ? 1 - t : t);
  const interactive = !!onOpen;
  const onKey = (e: KeyboardEvent) => {
    if (interactive && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onOpen!();
    }
  };
  let body: ReactNode;
  if (levels > 0) {
    const bandPx = Math.max(2, Math.min(BAND_MAX_REM * remPx, (hostHeight * HEIGHT_SHARE) / levels));
    const shown = new Set(boundaryIndices(levels, bandPx, remPx));
    const bounds = boundaries(range, scale, levels);
    const rows = Array.from({ length: levels }, (_, k) => levels - 1 - k); // 위 = 최대
    body = (
      <div className="v3d-legend-ov-bar">
        {rows.map((b) => (
          <div key={b} className="v3d-legend-ov-band" style={{ height: bandPx }} data-band={b}>
            <span className="v3d-legend-ov-sw" style={{ background: col((b + 0.5) / levels) }} />
            <span className="v3d-legend-ov-val" data-testid={shown.has(b + 1) ? "v3d-legend-ov-tick" : undefined}>
              {shown.has(b + 1) ? fmt(bounds[b + 1]) : ""}
            </span>
          </div>
        ))}
        <div className="v3d-legend-ov-band v3d-legend-ov-last" style={{ height: 0 }}>
          <span className="v3d-legend-ov-sw" style={{ background: "transparent" }} />
          <span className="v3d-legend-ov-val" data-testid="v3d-legend-ov-tick">
            {fmt(bounds[0])}
          </span>
        </div>
      </div>
    );
  } else {
    const barPx = Math.max(60, Math.min(BAR_MAX_REM * remPx, hostHeight * HEIGHT_SHARE));
    const tk = ticks(range, scale, 5);
    body = (
      <div className="v3d-legend-ov-bar">
        <div className="v3d-legend-ov-cont" style={{ height: barPx }} data-testid="v3d-legend-ov-cont">
          <span className="v3d-legend-ov-sw" style={{ background: cssGradient(map, { reversed, angle: 0 }), height: "100%" }} />
          <div className="v3d-legend-ov-ticks">
            {tk.map((v, i) => (
              <span key={i} className="v3d-legend-ov-val v3d-legend-ov-tickpos" style={{ bottom: `${(i / (tk.length - 1)) * 100}%` }} data-testid="v3d-legend-ov-tick">
                {fmt(v)}
              </span>
            ))}
          </div>
        </div>
      </div>
    );
  }
  const outSw = outGray ? <span className="v3d-legend-ov-outsw" style={{ background: specialCss("out") }} aria-hidden="true" /> : null;
  return (
    <div className="v3d-legend-wrap" data-testid="v3d-legend-wrap">
      <div
        className={`v3d-legend-ov mono small${interactive ? " clickable" : ""}${open ? " open" : ""}`}
        data-testid="v3d-legend-ov"
        data-levels={levels}
        data-role={role}
        role={interactive ? "button" : undefined}
        tabIndex={interactive ? 0 : undefined}
        aria-label={interactive ? `범례 편집 — ${title}` : undefined}
        aria-haspopup={interactive ? "dialog" : undefined}
        aria-expanded={interactive ? !!open : undefined}
        title={interactive ? "눌러서 범례 편집(레벨 수·최대·최소·눈금·숫자 형식·범위 밖 색·뒤집기)" : undefined}
        onClick={interactive ? onOpen : undefined}
        onKeyDown={onKey}
      >
        <div className="v3d-legend-ov-title">{title}</div>
        {above > 0 && (
          <div className="v3d-legend-ov-out" data-testid="v3d-legend-ov-above">
            ▲ {above.toLocaleString()} {outSw}
          </div>
        )}
        {body}
        {below > 0 && (
          <div className="v3d-legend-ov-out" data-testid="v3d-legend-ov-below">
            ▼ {below.toLocaleString()} {outSw}
          </div>
        )}
        {maxLine && <div className="v3d-legend-ov-max" data-testid="v3d-legend-ov-max">{maxLine}</div>}
        {minLine && <div className="v3d-legend-ov-max" data-testid="v3d-legend-ov-min">{minLine}</div>}
      </div>
      {children}
    </div>
  );
}
