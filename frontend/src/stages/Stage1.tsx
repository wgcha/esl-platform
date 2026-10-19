import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { Card, Empty, Stat } from "../components/ui";
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
    ? "파트 title을 입력하세요."
    : rad.result && !rad.result.ok
      ? "rad 경로에 문제가 있습니다."
      : res.result && !(res.result.ok && res.result.done.ok)
        ? "결과 폴더(done.json)에 문제가 있습니다."
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
            <div className="ro">
              <span className="ro-label">rad 경로</span>
              <span className="mono">{c.rad_path}</span>
            </div>
            {rad.result ? <RadInspectView r={rad.result} partTitle={partTitle} /> : <div className="small muted">{rad.error ?? "확인 중…"}</div>}
            <div className="ro">
              <span className="ro-label">결과 폴더</span>
              <span className="mono">{c.results_dir}</span>
            </div>
            {res.result ? <ResultsInspectView r={res.result} /> : <div className="small muted">{res.error ?? "확인 중…"}</div>}
            <label>
              파트 title
              <input value={partTitle} disabled={!allowed} onChange={(e) => setPartTitle(e.target.value)} />
            </label>
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
                <Stat label="종료 시각" value={`${s.t_end} s`} />
              </div>
              <div className="small muted">단위 {s.units_label} · 파트 id {c.part_id ?? "–"}</div>
              <table className="tbl compact">
                <thead>
                  <tr>
                    <th>재료 id</th>
                    <th>law</th>
                    <th>E</th>
                    <th>ν</th>
                  </tr>
                </thead>
                <tbody>
                  {s.mat.map((m) => (
                    <tr key={m.id}>
                      <td>{m.id}</td>
                      <td>{m.law}</td>
                      <td>{m.E?.toLocaleString() ?? "–"}</td>
                      <td>{m.nu ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <Empty>아직 추출하지 않았습니다. 경로를 확인한 뒤 "추출 실행"을 누르세요.</Empty>
          )}
        </Card>
      </div>
    </StageFrame>
  );
}
