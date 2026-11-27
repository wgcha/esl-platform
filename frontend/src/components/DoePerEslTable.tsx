// 강성 평가 스터디 'ESL별 개선율' 표(v0.10.0, esl_bead_doe.md §11.4): 행 = 순위 상위 N 안(+ 선택 안), 열 = ESL,
// 셀 = 개선율 1 − C_안,i / C_베이스라인,i(v0.25.1 L10: 색 = C 변화율 발산 — 파랑 개선 · 빨강 악화, 숫자는 개선율 그대로). 가로 스크롤은 표 안에서만(2560·1920 잘림 없음).
// v0.16.0 ④ 이름 옆 짧은 '메시 방식' 배지(DoeRanking 과 같음).
// 순위 행에 per_esl 이 없으면(안 수 × ESL 수 > 설정 상한) GET …/results/per-esl?design=… 로 보이는 행만 읽는다.
import { useEffect, useState } from "react";
import { doe, pctText } from "../api/doe";
import type { DoePerEsl, DoeResultOut, EntryOut } from "../api/types";
import { errorText } from "../api/client";
import { entryKey } from "./ModeSelect";
import { Empty, ErrorLine } from "./ui";
import { css, mapFor, srgb, textOn } from "../lib/colormap";
import { ShapeNameCell } from "./DoeInputs";

export const PER_ESL_TOP_N = 10;

/** 색 세기 기준: |C 변화율| 이 이 값일 때 색이 끝(파랑·빨강) — 한 곳(계약 §5.7 L10·L18) */
export const PER_ESL_HEAT_SPAN = 0.5;

/** 개선율 → 배경색. 색 값 = C 변화율(C_안/C_기준 − 1 = −개선율): 발산 지도(자원 colormaps.json) — − 파랑(개선) · 0 무색 · + 빨강(악화).
 *  글자 색 = 배경 상대 휘도로(textOn — 진한 칸 흰 글자, 보고서 report_doe._ratio_cell 과 같은 규칙) */
export function heatStyle(imp: number | null | undefined): { background?: string; color?: string } {
  if (imp == null || !Number.isFinite(imp) || imp === 0) return {};
  const map = mapFor("div");
  const t = (-imp / PER_ESL_HEAT_SPAN + 1) / 2;
  return { background: css(map, t), color: textOn(srgb(map, t)) };
}

/** v0.23.1 표 설명 1줄 — ⓘ 지표 정의 안으로 옮김(esl_doe_ui_tidy.md §4.1). ESL 열이 없으면 null */
export function perEslNote(result: DoeResultOut, pick: string | null, topN = PER_ESL_TOP_N): string | null {
  if (!(result.esl ?? []).length) return null;
  return `셀 = 개선율(1 − C_안 / C_베이스라인, 같은 ESL) · 파랑 개선(C 감소) · 빨강 악화(C 증가) · 상위 ${topN}개${pick && result.ranking.some((r) => r.id === pick) && !result.ranking.slice(0, topN).some((r) => r.id === pick) ? " + 선택 안" : ""}`;
}

const SCENE_HEAD_STYLE = { boxShadow: "inset 0 -3px 0 var(--accent)" } as const;
const SCENE_CELL_STYLE = { outline: "2px solid var(--accent)", outlineOffset: -2 } as const;

export function DoePerEslTable({ studyId, result, entries, pick, topN = PER_ESL_TOP_N, view = null, scene = null, onScene }: {
  /** v0.25.1 선택된 낙하 씬(entry_id, null = 자동) — 그 열 강조 */
  scene?: string | null;
  /** v0.25.1 씬 선택(계약 §4.1): 열 머리 = (eid, null) → 호출부가 토글, 셀 = (eid, 안 id) → 그 안 + 그 씬. 없으면 클릭 동작 없음(옛 결과) */
  onScene?: (eid: string, did: string | null) => void;
  studyId: string;
  /** v0.23.3 하중 정의 탭 보기(인라인이 아닐 때 ?view= 로 읽음 — esl_jig_view.md §2). null = 기존 */
  view?: string | null;
  result: DoeResultOut;
  entries: EntryOut[];
  pick: string | null;
  topN?: number;
}) {
  const ids = result.ranking.slice(0, topN).map((r) => r.id);
  if (pick && !ids.includes(pick) && result.ranking.some((r) => r.id === pick)) ids.push(pick);
  const inline = !!result.per_esl_inline;
  const [fetched, setFetched] = useState<Record<string, DoePerEsl[]>>({});
  const [error, setError] = useState<string | null>(null);
  /** ④ GET …/results/per-esl 행 name(순위 행 shape 가 없을 때) */
  const [names, setNames] = useState<Record<string, string>>({});
  const need = inline ? [] : ids.filter((i) => !(i in fetched));
  useEffect(() => {
    if (!need.length) return;
    let alive = true;
    doe
      .perEsl(studyId, need, view)
      .then((o) => {
        if (!alive) return;
        setFetched((f) => ({ ...f, ...Object.fromEntries(o.designs.map((d) => [d.id, d.per_esl])) }));
        setNames((n) => ({ ...n, ...Object.fromEntries(o.designs.filter((d) => d.name).map((d) => [d.id, d.name as string])) }));
      })
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [studyId, need.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const byEntry = new Map(entries.map((e) => [e.id, e]));
  const cols0 = (result.esl ?? []).map((e) => ({ id: e.entry_id, label: byEntry.get(e.entry_id) ? entryKey(byEntry.get(e.entry_id)!) : e.label || e.entry_id.slice(0, 8) }));
  // 같은 이름(같은 모델·orient 없음)이면 #1·#2… 를 붙여 열을 구분
  const cnt = new Map<string, number>();
  for (const c of cols0) cnt.set(c.label, (cnt.get(c.label) ?? 0) + 1);
  const seen = new Map<string, number>();
  const cols = cols0.map((c) => {
    if ((cnt.get(c.label) ?? 0) < 2) return c;
    const k = (seen.get(c.label) ?? 0) + 1;
    seen.set(c.label, k);
    return { ...c, label: `${c.label} #${k}` };
  });
  const perOf = (id: string): DoePerEsl[] | undefined => (inline ? result.ranking.find((r) => r.id === id)?.per_esl : fetched[id]);
  // v0.14.0 ④ 형상 비교: 안 옆에 형상 이름 열
  const named = result.scenario === "compare" || result.ranking.some((r) => !!r.shape);
  const shapeOf = (id: string) => result.ranking.find((r) => r.id === id)?.shape ?? (id === "d000" ? result.baseline.shape : null) ?? null;
  const nameOf = (id: string) => result.ranking.find((r) => r.id === id)?.shape?.name ?? names[id] ?? (id === "d000" ? result.baseline.shape?.name : null) ?? "–";
  if (!cols.length) return <Empty>ESL별 지표가 없습니다(v0.10.0 이전 실행 — 복제해 다시 실행하면 보입니다)</Empty>;
  return (
    <div className="doe-per-esl">
      <ErrorLine text={error} />
      <div className="table-wrap scroll doe-per-esl-wrap" data-testid="per-esl-wrap">
        <table className="table compact" aria-label="ESL별 개선율">
          <thead>
            <tr>
              <th>안</th>
              {named && <th className="doe-name-col">이름</th>}
              {cols.map((c) => (
                <th key={c.id} className={`num${scene === c.id ? " scene-on" : ""}`} title={c.id} style={scene === c.id ? SCENE_HEAD_STYLE : undefined}>
                  {onScene ? (
                    <button type="button" className="link-btn" aria-pressed={scene === c.id} data-testid={`per-esl-col-${c.id}`} style={{ font: "inherit", padding: 0, background: "none", border: 0, cursor: "pointer", color: "inherit", fontWeight: scene === c.id ? 700 : undefined }} onClick={() => onScene(c.id, null)}>
                      {c.label}
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => {
              const per = perOf(id);
              const m = new Map((per ?? []).map((p) => [p.entry_id, p]));
              return (
                <tr key={id} className={pick === id ? "hl" : undefined} data-testid={`per-esl-${id}`}>
                  <td className="mono">{id}</td>
                  {named && (
                    <th scope="row" className="doe-name-col">
                      <ShapeNameCell name={nameOf(id)} shape={shapeOf(id)} testId={`per-esl-method-${id}`} />
                    </th>
                  )}
                  {cols.map((c) => {
                    const p = m.get(c.id);
                    const imp = p ? 1 - p.ratio : null;
                    return (
                      <td key={c.id} className="num mono heat" style={{ ...heatStyle(imp), ...(scene === c.id ? SCENE_CELL_STYLE : null), ...(onScene ? { cursor: "pointer" } : null) }} onClick={onScene ? () => onScene(c.id, id) : undefined} data-testid={`per-esl-cell-${id}-${c.id}`} title={p ? (result.metric === "lin" ? `C(지표) ${p.C.toPrecision(4)} · 비율 ${p.ratio.toFixed(3)}${p.C_solve != null ? ` · 재풀이 C ${p.C_solve.toPrecision(4)}` : ""}${p.rho != null ? ` · ρ ${p.rho.toFixed(2)}` : ""}` : `C ${p.C.toPrecision(4)} · 비율 ${p.ratio.toFixed(3)} · umax ${p.umax.toFixed(2)} mm`) : undefined}>
                        {per ? pctText(imp, 1) : "…"}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
