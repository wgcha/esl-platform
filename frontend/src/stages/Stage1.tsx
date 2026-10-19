import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { Card, Empty, Field, Stat } from "../components/ui";
import { RadInspectView, ResultsInspectView, usePathInspect } from "../components/PathInspect";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";

export function Stage1({ c, reload, allowed }: StageProps) {
  const rad = usePathInspect("RAD", c.rad_path);
  const res = usePathInspect("RESULTS", c.results_dir);
  const [partTitle, setPartTitle] = useState(c.part_title);
  const act = useAction(reload);
  const s = c.extract_summary;

  useEffect(() => {
    void rad.inspect(c.rad_path);
    void res.inspect(c.results_dir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.id]);

  const prereq = !partTitle.trim()
    ? "파트 title을 입력하세요"
    : rad.result && !rad.result.ok
      ? "rad 경로에 문제가 있습니다"
      : res.result && !(res.result.ok && res.result.done?.ok)
        ? "결과 폴더(done.json)에 문제가 있습니다"
        : null;

  const run = () =>
    act.run(async () => {
      if (partTitle.trim() !== c.part_title) await api.patchCase(c.id, { version: c.version, part_title: partTitle.trim() });
      await submitJob(c, "CASE_EXTRACT");
    });

  return (
    <StageFrame
      title="① 입력"
      status={c.stage_status?.["1"]}
      error={act.error}
      onJobDone={() => void reload()}
      primary={{ label: "추출 실행", onClick: run, disabledReason: blockReason(allowed, c, 1, prereq), busy: act.busy }}
    >
      <div className="grid2">
        <Card title="입력 경로">
          <div className="form">
            <Field label="rad 경로">
              <span className="mono readonly-path">{c.rad_path}</span>
            </Field>
            {rad.result ? <RadInspectView r={rad.result} partTitle={partTitle} /> : <div className="small muted">{rad.error ?? "확인 중…"}</div>}
            <Field label="결과 폴더">
              <span className="mono readonly-path">{c.results_dir}</span>
            </Field>
            {res.result ? <ResultsInspectView r={res.result} /> : <div className="small muted">{res.error ?? "확인 중…"}</div>}
            <Field label="파트 title">
              <input value={partTitle} disabled={!allowed} onChange={(e) => setPartTitle(e.target.value)} />
            </Field>
            {partTitle.trim() !== c.part_title && <div className="small warn-text">바꾸면 이후 단계가 모두 다시 계산 대상이 됩니다.</div>}
          </div>
        </Card>
        <Card title="추출 결과">
          {s ? (
            <>
              <div className="stats">
                <Stat label="노드" value={s.n_nodes.toLocaleString()} />
                <Stat label="요소" value={s.n_elems.toLocaleString()} />
                <Stat label="프레임" value={s.n_frames} />
                <Stat label="후보 프레임(D)" value={s.disp_frames.length} hint={s.disp_frames.join(", ")} />
              </div>
              <div className="small muted">
                QUAD {s.n_quad?.toLocaleString() ?? "–"} · TRIA {s.n_tria?.toLocaleString() ?? "–"} · 단위 {s.units_label || "–"} · 파트 id {c.part_id ?? "–"}
                {c.h3d_path ? ` · h3d ${c.h3d_path}` : ""}
              </div>
              {s.warnings.length > 0 && (
                <ul className="reasons">
                  {s.warnings.map((w) => (
                    <li key={w} className="small warn-text">
                      {w}
                    </li>
                  ))}
                </ul>
              )}
              <table className="table compact">
                <thead>
                  <tr>
                    <th>재료 id</th>
                    <th>law</th>
                    <th className="num">E</th>
                    <th className="num">ν</th>
                  </tr>
                </thead>
                <tbody>
                  {s.mats.map((m) => (
                    <tr key={m.id}>
                      <td>{m.id}</td>
                      <td>{m.law}</td>
                      <td className="num">{m.E?.toLocaleString() ?? "–"}</td>
                      <td className="num">{m.nu ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <Empty>아직 추출하지 않았습니다. 경로를 확인한 뒤 "추출 실행"을 누르세요</Empty>
          )}
        </Card>
      </div>
    </StageFrame>
  );
}
