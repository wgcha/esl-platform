// 2D 지도(겹쳐보기·변위 컨투어) 공용: 좌표 변환, 단면 위치선·띠·추천 마커, 클릭 → 정규화 위치.
// 정규화 좌표 = 계약 §15.2 와 같은 (값 − 범위 최소)/(범위 최대 − 범위 최소). 범위는 서버 SectionOut.line 의 xi_range·eta_range.
import type { SectionAxis, SectionLine, SectionSuggest } from "../api/types";

export interface Geo {
  W: number;
  H: number;
  sx: (a: number) => number;
  sy: (b: number) => number;
  /** 화면 → 평면 좌표 */
  ia: (x: number) => number;
  ib: (y: number) => number;
  /** 평면 1 단위의 화면 픽셀 수 */
  scale: number;
  cell: number;
  ext: { amin: number; amax: number; bmin: number; bmax: number };
}

const PAD = 18;

interface PtsLike {
  cell?: number[] | null;
  points: ReadonlyArray<ReadonlyArray<unknown>>;
}

export function geometry(f: PtsLike, W: number): Geo {
  let amin = Infinity, amax = -Infinity, bmin = Infinity, bmax = -Infinity;
  for (const p of f.points) {
    const a = p[1] as number;
    const b = p[2] as number;
    if (a < amin) amin = a;
    if (a > amax) amax = a;
    if (b < bmin) bmin = b;
    if (b > bmax) bmax = b;
  }
  if (!Number.isFinite(amin)) (amin = 0), (amax = 1), (bmin = 0), (bmax = 1);
  const dx = amax - amin || 1;
  const dy = bmax - bmin || 1;
  const H = Math.round(Math.max(240, Math.min(560, typeof window !== "undefined" && window.innerHeight > 0 ? Math.max(300, window.innerHeight * 0.36) : 560, ((W - 2 * PAD) * dy) / dx + 2 * PAD)));
  const s = Math.min((W - 2 * PAD) / dx, (H - 2 * PAD) / dy);
  const ox = (W - s * dx) / 2;
  const oy = (H - s * dy) / 2;
  // 표시 칸 크기: 다운샘플 격자 칸(cell) 또는 평면 범위 ÷ 점 수(요소 크기 근사)
  const cellW = f.cell && f.cell.length === 2 ? Math.sqrt(f.cell[0] * f.cell[1]) * 1.04 : Math.sqrt((dx * dy) / Math.max(1, f.points.length)) * 1.08;
  return {
    W,
    H,
    sx: (a) => ox + (a - amin) * s,
    sy: (b) => H - oy - (b - bmin) * s,
    ia: (x) => amin + (x - ox) / s,
    ib: (y) => bmin + (H - oy - y) / s,
    scale: s,
    cell: Math.max(1.2, cellW * s),
    ext: { amin, amax, bmin, bmax },
  };
}

/** 지도에 보이는 단면 제어값(Stage5 공유 상태 + 서버 응답) */
export interface SectionMap {
  axis: SectionAxis;
  at: number;
  /** 서버가 준 단면선과 그 선이 속한 at (디바운스 중에는 at 과 다를 수 있다) */
  line: SectionLine | null;
  lineAt: number | null;
  suggest: SectionSuggest[];
  /** 지도 클릭: 현재 축의 고정 좌표(0~1) */
  onPick: (at: number) => void;
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

/** 정규화 기준 범위: 서버 line 의 xi_range·eta_range(요소 중심 범위). 아직 응답이 없으면 화면 점 범위로 대체 */
export function normRanges(g: Geo, line: SectionLine | null | undefined) {
  const ok = (r: number[] | undefined) => !!r && r.length === 2 && Number.isFinite(r[0]) && Number.isFinite(r[1]) && r[1] > r[0];
  return {
    xi: ok(line?.xi_range) ? ([line!.xi_range[0], line!.xi_range[1]] as [number, number]) : ([g.ext.amin, g.ext.amax] as [number, number]),
    eta: ok(line?.eta_range) ? ([line!.eta_range[0], line!.eta_range[1]] as [number, number]) : ([g.ext.bmin, g.ext.bmax] as [number, number]),
  };
}

/** 클릭 위치(지도 픽셀) → 현재 축의 고정 좌표 정규화값(xi_range·eta_range 기준, [0,1] 자름).
 *  axis=eta 는 η(폭 방향 b) 고정, axis=xi 는 ξ(길이 방향 a) 고정 */
export function pickAt(g: Geo, axis: SectionAxis, x: number, y: number, line?: SectionLine | null): number {
  const r = normRanges(g, line);
  return axis === "eta" ? clamp01((g.ib(y) - r.eta[0]) / (r.eta[1] - r.eta[0] || 1)) : clamp01((g.ia(x) - r.xi[0]) / (r.xi[1] - r.xi[0] || 1));
}

/** 서버 line 이 아직 없거나 at 이 다를 때(디바운스 중) 지도에 임시로 그릴 단면선 */
export function localLine(g: Geo, axis: SectionAxis, at: number, band: number, line?: SectionLine | null): Omit<SectionLine, "xi_range" | "eta_range"> {
  const { amin, amax, bmin, bmax } = g.ext;
  const r = normRanges(g, line);
  const fa = r.xi[0] + at * (r.xi[1] - r.xi[0]);
  const fb = r.eta[0] + at * (r.eta[1] - r.eta[0]);
  return axis === "eta" ? { a0: amin, b0: fb, a1: amax, b1: fb, band_abs: band } : { a0: fa, b0: bmin, a1: fa, b1: bmax, band_abs: band };
}

/** 정규화 (xi, eta) → 지도 좌표 */
export function suggestAB(g: Geo, s: SectionSuggest, line?: SectionLine | null): [number, number] {
  const r = normRanges(g, line);
  return [r.xi[0] + s.xi * (r.xi[1] - r.xi[0]), r.eta[0] + s.eta * (r.eta[1] - r.eta[0])];
}

/** 단면 위치선(점선) + 반투명 띠 + 추천 마커. 호출한 svg 안에 넣는다 */
export function SectionMarks({ g, sec }: { g: Geo; sec: SectionMap }) {
  const band = sec.line?.band_abs ?? 0;
  const useServer = sec.line !== null && sec.lineAt !== null && Math.abs(sec.lineAt - sec.at) < 0.005;
  const ln = useServer ? sec.line! : localLine(g, sec.axis, sec.at, band, sec.line);
  const x0 = g.sx(ln.a0), y0 = g.sy(ln.b0), x1 = g.sx(ln.a1), y1 = g.sy(ln.b1);
  return (
    <g className="sec-marks" data-testid="sec-marks" data-axis={sec.axis} data-at={sec.at.toFixed(2)}>
      {band > 0 && <line className="sec-band" x1={x0} y1={y0} x2={x1} y2={y1} style={{ strokeWidth: Math.max(2, 2 * band * g.scale) }} data-testid="sec-band" />}
      <line className="sec-halo" x1={x0} y1={y0} x2={x1} y2={y1} />
      <line className="sec-line" x1={x0} y1={y0} x2={x1} y2={y1} data-testid="sec-line" />
      {sec.suggest.map((s) => {
        const [a, b] = suggestAB(g, s, sec.line);
        const x = g.sx(a), y = g.sy(b);
        return (
          <g key={s.key} className="mk-sug" data-testid="sec-suggest-marker">
            <path d={`M${x},${y - 7}L${x + 7},${y}L${x},${y + 7}L${x - 7},${y}Z`} />
            <title>{`${s.label} — ${s.key === "hotspot1" ? "요소" : "노드"} ${s.id}`}</title>
          </g>
        );
      })}
    </g>
  );
}
