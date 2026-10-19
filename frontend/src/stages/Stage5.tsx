import { api } from "../api/endpoints";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { dt, fmt, pct, sci } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";

/** 코어 validation fail_reasons 코드 → 설명 */
export const FAIL_REASON_LABEL: Record<string, string> = {
  DISP_RMS: "변위 RMS 오차가 기준 초과",
  HOTSPOT_STRAIN: "hotspot 1위 ε_eq 오차가 기준 초과",
  REACTION: "3-2-1 반력이 기준 초과(자기평형 아님)",
  NOISE_FLOOR: "변위 정밀도 잡음 바닥이 기준 초과",
};

const num = (x: unknown) => (typeof x === "number" ? x : undefined);
const critText = (x: unknown) => (typeof x === "number" ? String(x) : Array.isArray(x) ? x.join(",") : x == null ? "–" : String(x));

export function Stage5({ c, reload, allowed }: StageProps) {
  const runId = c.current_esl_run_id;
  const st5 = c.stage_status?.["5"];
  // 검증 완료는 Case version 을 바꾸지 않으므로 ⑤ 상태(job_id·state)가 바뀌면 다시 읽는다
  const run = usePolling(() => (runId ? api.eslRun(runId) : Promise.resolve(null)), 0, [runId, c.version, st5?.state, st5?.job_id]);
  const vid = run.data?.latest_validation_id ?? null;
  const val = usePolling(() => (vid ? api.validation(vid) : Promise.resolve(null)), 0, [vid]);
  const history = usePolling(() => api.validations(c.id), 0, [c.id, vid, c.version, st5?.state]);
  const act = useAction(reload);
  const v = val.data;

  const prereq = !runId ? "④ ESL을 먼저 계산하세요" : run.data?.stale ? "④ ESL을 다시 계산하세요(입력이 바뀜)" : null;
  const crit = v?.criteria ?? {};
  const hsMax = num(crit.hotspot_strain_rel_err_max);
  const dispMax = num(crit.disp_rms_rel_max);
  const reacMax = num(crit.reaction_rel_max);

  return (
    <StageFrame
      title="⑤ 검증"
      status={c.stage_status?.["5"]}
      error={act.error ?? run.error ?? val.error}
      onJobDone={() => void reload()}
      primary={{
        label: "검증 실행",
        onClick: () => act.run(() => submitJob(c, "VALIDATE", { esl_run_id: runId })),
        disabledReason: blockReason(allowed, c, 5, prereq),
        busy: act.busy,
      }}
    >
      {!v ? (
        <Empty>{runId ? "아직 검증하지 않았습니다" : "④ ESL을 먼저 계산하세요"}</Empty>
      ) : (
        <>
          <Card title="판정" right={v.verdict === "PASS" ? <Badge kind="ok">PASS</Badge> : <Badge kind="bad">FAIL</Badge>}>
            <div className="stats">
              <Stat
                label="변위 RMS (상대)"
                value={v.disp_rms_rel === null ? "생략" : sci(v.disp_rms_rel)}
                hint={v.disp_rms_rel === null ? "전체 재해석 생략(validation.full_solve)" : dispMax !== undefined ? `기준 ≤ ${sci(dispMax)}` : undefined}
              />
              <Stat label="반력 (상대)" value={v.reaction_rel === null ? "생략" : sci(v.reaction_rel)} hint={reacMax !== undefined ? `기준 ≤ ${sci(reacMax)}` : undefined} />
              <Stat
                label="hotspot 1위 오차"
                value={v.hotspots.length ? pct(v.hotspots[0].rel_err) : "–"}
                hint={hsMax !== undefined ? `기준 ≤ ${pct(hsMax)}` : undefined}
              />
            </div>
            {Object.keys(crit).length > 0 && (
              <div className="small muted">
                기준:{" "}
                {Object.entries(crit)
                  .map(([k, x]) => `${k} = ${critText(x)}`)
                  .join(" · ")}
              </div>
            )}
            {v.fail_reasons.length > 0 && (
              <ul className="reasons">
                {v.fail_reasons.map((f) => (
                  <li key={f} className="error-text">
                    {f}
                    {FAIL_REASON_LABEL[f] ? ` — ${FAIL_REASON_LABEL[f]}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <div className="grid2">
            <Card title="hotspot ε_eq 오차">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>요소</th>
                    <th className="num">ε (Radioss)</th>
                    <th className="num">ε (검증)</th>
                    <th className="num">오차</th>
                  </tr>
                </thead>
                <tbody>
                  {v.hotspots.map((h) => {
                    const over = hsMax !== undefined && h.rel_err > hsMax;
                    return (
                      <tr key={h.elem_id} className={over ? "bad-row" : undefined}>
                        <td>{h.elem_id}</td>
                        <td className="num">{fmt(h.eps_rad, 4)}</td>
                        <td className="num">{fmt(h.eps_val, 4)}</td>
                        <td className="num">{pct(h.rel_err)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
            <Card title="제외 요소">
              {v.excluded.length ? (
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>요소</th>
                      <th>사유</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.excluded.map((x) => (
                      <tr key={x.elem_id}>
                        <td>{x.elem_id}</td>
                        <td>{x.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>없음</Empty>
              )}
            </Card>
          </div>
          {history.data && history.data.length > 1 && (
            <Card title="검증 이력">
              <table className="table compact">
                <thead>
                  <tr>
                    <th className="num">시각</th>
                    <th>판정</th>
                    <th>ESL 결과</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {history.data.map((h) => (
                    <tr key={h.id} className={h.id === v.id ? "hl" : undefined}>
                      <td className="num">{dt(h.created_at)}</td>
                      <td>{h.verdict}</td>
                      <td className="mono small">{h.esl_run_id}</td>
                      <td>{h.stale ? <span className="muted">이전 입력</span> : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </StageFrame>
  );
}
