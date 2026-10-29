// 강성 평가 스터디 'ESL별 개선율' 표(v0.10.0, esl_bead_doe.md §11.4): 행 = 순위 상위 N 안(+ 선택 안), 열 = ESL,
// 셀 = 개선율 1 − C_안,i / C_베이스라인,i(개선 초록 · 악화 빨강 히트맵). 가로 스크롤은 표 안에서만(2560·1920 잘림 없음).
// 순위 행에 per_esl 이 없으면(안 수 × ESL 수 > 설정 상한) GET …/results/per-esl?design=… 로 보이는 행만 읽는다.
import { useEffect, useState } from "react";
import { doe, pctText } from "../api/doe";
import type { DoePerEsl, DoeResultOut, EntryOut } from "../api/types";
import { errorText } from "../api/client";
import { entryKey } from "./ModeSelect";
import { Empty, ErrorLine } from "./ui";

export const PER_ESL_TOP_N = 10;

/** 개선율 → 배경색(세기 = |개선율| 50 % 에서 최대) */
export function heatStyle(imp: number | null | undefined): { background?: string } {
  if (imp == null || !Number.isFinite(imp) || imp === 0) return {};
  const a = Math.min(Math.abs(imp) / 0.5, 1) * 0.55 + 0.08;
  return { background: imp > 0 ? `rgba(22, 163, 74, ${a.toFixed(2)})` : `rgba(220, 38, 38, ${a.toFixed(2)})` };
}

export function DoePerEslTable({ studyId, result, entries, pick, topN = PER_ESL_TOP_N }: {
  studyId: string;
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
  const need = inline ? [] : ids.filter((i) => !(i in fetched));
  useEffect(() => {
    if (!need.length) return;
    let alive = true;
    doe
      .perEsl(studyId, need)
      .then((o) => alive && setFetched((f) => ({ ...f, ...Object.fromEntries(o.designs.map((d) => [d.id, d.per_esl])) })))
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
  if (!cols.length) return <Empty>ESL별 지표가 없습니다(v0.10.0 이전 실행 — 복제해 다시 실행하면 보입니다)</Empty>;
  return (
    <div className="doe-per-esl">
      <ErrorLine text={error} />
      <div className="table-wrap scroll doe-per-esl-wrap" data-testid="per-esl-wrap">
        <table className="table compact" aria-label="ESL별 개선율">
          <thead>
            <tr>
              <th>안</th>
              {cols.map((c) => (
                <th key={c.id} className="num" title={c.id}>
                  {c.label}
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
                  {cols.map((c) => {
                    const p = m.get(c.id);
                    const imp = p ? 1 - p.ratio : null;
                    return (
                      <td key={c.id} className="num mono heat" style={heatStyle(imp)} title={p ? `C ${p.C.toPrecision(4)} · 비율 ${p.ratio.toFixed(3)} · umax ${p.umax.toFixed(2)} mm` : undefined}>
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
      <div className="small muted">셀 = 개선율(1 − C_안 / C_베이스라인, 같은 ESL) · 초록 개선 · 빨강 악화 · 상위 {topN}개{pick && !result.ranking.slice(0, topN).some((r) => r.id === pick) ? " + 선택 안" : ""}</div>
    </div>
  );
}
