// 라이브러리 화면 공통: 표기·필터·포락 미니맵.
import type { AnalysisFilters, EntryOut, OptdeckCases } from "../../api/types";
import { Badge } from "../../components/ui";
import { VIRIDIS, f3, gradient, lerp } from "../../lib/colormap";

export const DROP_TYPES = ["Corner", "Edge", "Face"] as const;
export const DROP_LABEL: Record<string, string> = { Corner: "꼭지점", Edge: "모서리", Face: "면" };
export const NORM_LABEL: Record<string, string> = { none: "없음", mass: "질량", inch2: "인치²" };
export const OBJ_LABEL: Record<string, string> = { minmax: "최악 최소화 (minmax)", weighted: "가중 합 (weighted)" };

export const libPath = (projectId: string) => `/p/${projectId}/library`;

/** §12.1 최적화 하중(덱 subcase) 구성 */
export const DECK_LABEL: Record<OptdeckCases, string> = { all: "모든 씬", representative: "대표", "representative+worst": "대표+최악" };

// ---------------------------------------------------------------- 설계 버전(§12.2)
const vkey = (v: string) => v.split(/(\d+)/).filter((p) => p !== "").map((p) => (/^\d+$/.test(p) ? [0, Number(p), ""] : [1, 0, p.toLowerCase()]) as [number, number, string]);

/** 서버(esl.library.compare.sort_versions)와 같은 자연 정렬: v2 < v10 */
export function sortVersions(vs: (string | null | undefined)[]): string[] {
  const u = [...new Set(vs.filter((v): v is string => !!v && !!v.trim()))];
  return u.sort((a, b) => {
    const x = vkey(a);
    const y = vkey(b);
    for (let i = 0; i < Math.min(x.length, y.length); i++)
      for (let k = 0; k < 3; k++) if (x[i][k] !== y[i][k]) return x[i][k] < y[i][k] ? -1 : 1;
    return x.length - y.length;
  });
}

export function prevVersion(vs: string[], v: string): string | null {
  const s = sortVersions([...vs, v]);
  const i = s.indexOf(v);
  return i > 0 ? s[i - 1] : null;
}

/** 짝 씬 키(서버 comparisons.scene_key 와 같은 필드·대소문자 무시) */
export function sceneKey(e: EntryOut) {
  const s = e.scene;
  return [s.scenario, s.seq, s.drop_type, s.round, s.scene_no, s.orient, s.suffix].map((x) => (x == null ? "" : String(x).trim().toLowerCase())).join("|");
}

/** 기준·비교 버전 항목 → 짝(같은 씬 키, 같은 키가 여럿이면 최근 등록) */
export function pairEntries(entries: EntryOut[], model: string, base: string, next: string) {
  const pick = (v: string) => {
    const m = new Map<string, EntryOut>();
    entries
      .filter((e) => e.status === "ACTIVE" && e.model.name === model && e.model.version === v)
      .sort((a, b) => a.registered_at.localeCompare(b.registered_at))
      .forEach((e) => m.set(sceneKey(e), e));
    return m;
  };
  const b = pick(base);
  const n = pick(next);
  const pairs = [...b.keys()].filter((k) => n.has(k)).map((k) => ({ key: k, base: b.get(k)!, next: n.get(k)! }));
  return { pairs, baseOnly: [...b.keys()].filter((k) => !n.has(k)).length, newOnly: [...n.keys()].filter((k) => !b.has(k)).length };
}

/** 제품별 활성 버전(2개 이상인 제품만 비교 가능) */
export function modelVersions(entries: EntryOut[]) {
  const m = new Map<string, string[]>();
  for (const e of entries) if (e.status === "ACTIVE" && e.model.name && e.model.version) m.set(e.model.name, [...(m.get(e.model.name) ?? []), e.model.version]);
  return [...m.entries()].map(([model, vs]) => ({ model, versions: sortVersions(vs) })).sort((a, b) => a.model.localeCompare(b.model));
}

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
