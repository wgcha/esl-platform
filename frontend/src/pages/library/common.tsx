// 라이브러리 화면 공통: 표기·필터·포락 미니맵.
import type { AnalysisFilters, EntryOut } from "../../api/types";
import { Badge } from "../../components/ui";
import { VIRIDIS, f3, gradient, lerp } from "../../lib/colormap";

export const DROP_TYPES = ["Corner", "Edge", "Face"] as const;
export const DROP_LABEL: Record<string, string> = { Corner: "꼭지점", Edge: "모서리", Face: "면" };
export const NORM_LABEL: Record<string, string> = { none: "없음", mass: "질량", inch2: "인치²" };
export const OBJ_LABEL: Record<string, string> = { minmax: "최악 최소화 (minmax)", weighted: "가중 합 (weighted)" };

export const libPath = (projectId: string) => `/p/${projectId}/library`;

export function VerdictBadge({ v }: { v: string | null | undefined }) {
  if (!v) return <span className="muted">–</span>;
  return v === "PASS" ? <Badge kind="ok">PASS</Badge> : <Badge kind="bad">FAIL</Badge>;
}

export const dropText = (d: string | null | undefined) => (d ? DROP_LABEL[d] ?? d : "?");

export function sceneText(e: { scene: EntryOut["scene"] }) {
  const s = e.scene;
  return `${dropText(s.drop_type)}${s.scene_no != null ? ` · Scene ${s.scene_no}` : ""}`;
}

export function entryLabel(e: EntryOut) {
  return `${e.model.name ?? "?"}${e.model.inch ? ` (${e.model.inch}")` : ""} · ${sceneText(e)}${e.scene.orient ? ` · ${e.scene.orient}` : ""}`;
}

const inList = (xs: (string | number)[] | null | undefined, v: string | number | null | undefined) => !xs?.length || (v != null && xs.includes(v));

/** 서버 필터(POST /library/analyses filters: 키마다 목록, 비우면 전체)와 같은 규칙으로 미리 거른다 */
export function matchEntries(entries: EntryOut[], f: AnalysisFilters) {
  return entries.filter(
    (e) =>
      e.status === "ACTIVE" &&
      (f.entry_ids?.length
        ? f.entry_ids.includes(e.id)
        : inList(f.model, e.model.name) &&
          inList(f.inch, e.model.inch) &&
          inList(f.drop_type, e.scene.drop_type) &&
          inList(f.orient, e.scene.orient) &&
          inList(f.scenario, e.scene.scenario) &&
          inList(f.verdict, e.quality.verdict)),
  );
}

export function filtersText(f: AnalysisFilters) {
  if (f.entry_ids?.length) return `항목 ${f.entry_ids.length}개 지정`;
  const out = [
    f.model?.length ? `모델 ${f.model.join("·")}` : "모든 모델",
    f.drop_type?.length ? f.drop_type.map(dropText).join("·") : "모든 씬 유형",
    f.verdict?.length ? `${f.verdict.join("·")}만` : "PASS·FAIL",
  ];
  if (f.scenario?.length) out.push(f.scenario.join("·"));
  return out.join(" · ");
}

export const uniq = (xs: (string | null | undefined)[]) => [...new Set(xs.filter((x): x is string => !!x))].sort();

export interface EnvelopeGrid {
  nx: number;
  ny: number;
  /** [i][j] 셀 합력 최대 |F| */
  mag: number[][];
  max: number;
}

/** envelope.csv(i,j,…,max_abs_f,…) → 격자 */
export function parseEnvelopeCsv(text: string): EnvelopeGrid | null {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return null;
  const head = lines[0].split(",");
  const ci = head.indexOf("i");
  const cj = head.indexOf("j");
  const cm = head.indexOf("max_abs_f");
  if (ci < 0 || cj < 0 || cm < 0) return null;
  const rows = lines.slice(1).map((l) => l.split(",")).map((c) => [Number(c[ci]), Number(c[cj]), Number(c[cm])]);
  const nx = Math.max(...rows.map((r) => r[0])) + 1;
  const ny = Math.max(...rows.map((r) => r[1])) + 1;
  if (!(nx > 0 && ny > 0)) return null;
  const mag = Array.from({ length: nx }, () => new Array<number>(ny).fill(0));
  let max = 0;
  for (const [i, j, m] of rows)
    if (Number.isFinite(m)) {
      mag[i][j] = m;
      max = Math.max(max, m);
    }
  return { nx, ny, mag, max };
}

/** 셀 합력 포락 미니맵(정규화 격자 nx×ny, ξ 가로 · η 세로, η 위쪽) */
export function EnvelopeMap({ env }: { env: EnvelopeGrid }) {
  const c = 18;
  const W = env.nx * c;
  const H = env.ny * c;
  return (
    <div className="env-map">
      <svg viewBox={`0 0 ${W} ${H}`} width={Math.min(W, 520)} role="img" aria-label="셀 합력 포락 미니맵">
        {env.mag.map((col, i) =>
          col.map((v, j) => (
            <rect key={`${i}-${j}`} x={i * c} y={H - (j + 1) * c} width={c} height={c} fill={lerp(VIRIDIS, v / (env.max || 1))}>
              <title>{`셀 (${i}, ${j}): ${f3(v)} N`}</title>
            </rect>
          )),
        )}
        <rect className="outline" x={0.5} y={0.5} width={W - 1} height={H - 1} />
      </svg>
      <div className="legend small">
        <span>셀 합력 최대 |F| (N)</span>
        <span className="mono">0</span>
        <span className="ramp" style={{ background: gradient(VIRIDIS) }} />
        <span className="mono">{f3(env.max)}</span>
        <span className="muted">
          격자 {env.nx}×{env.ny} (ξ 가로 · η 세로)
        </span>
      </div>
    </div>
  );
}
