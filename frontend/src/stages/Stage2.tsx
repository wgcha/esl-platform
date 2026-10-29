import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import type { Metric } from "../api/types";
import { Card, Empty } from "../components/ui";
import { MaxHoldChart } from "../components/MaxHoldChart";
import { usePolling } from "../lib/usePolling";
import { METRIC_LABEL, fmt } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, useAction } from "./common";
import { cumText, hasCum } from "../components/Cumulative";
import { SupportSummary } from "../components/SupportSummary";
import { stepState } from "../shell/StageStepper";

const METRICS: Metric[] = ["max_strain", "plastic_strain"];

export function Stage2({ c, reload, allowed }: StageProps) {
  const ready = !!c.extract_summary;
  const tv = usePolling(() => (ready ? api.tstar(c.id) : Promise.resolve(null)), 0, [c.id, ready]);
  const [metric, setMetric] = useState<Metric>(c.tstar?.metric ?? "max_strain");
  const [frame, setFrame] = useState<number | null>(c.tstar?.frame_index ?? null);
  const act = useAction(reload);
  const blk = tv.data?.metrics[metric];
  const hotspots = blk?.hotspots ?? tv.data?.hotspots ?? [];
  // v0.8.0 누적 씬: 값 = 누적(이전 + 이번), 표에 이전·이번(증분) 열
  const cum = !!tv.data?.cumulative && hasCum(blk?.tstar);

  // 지표를 바꾸면 그 지표의 현재 t*(또는 자동값)를 기본 선택
  useEffect(() => {
    if (!tv.data) return;
    if (c.tstar && c.tstar.metric === metric) setFrame(c.tstar.frame_index);
    else setFrame(tv.data.metrics[metric]?.tstar?.frame_index ?? null);
  }, [metric, tv.data, c.tstar?.metric, c.tstar?.frame_index]);

  const unchanged = !!c.tstar && c.tstar.metric === metric && c.tstar.frame_index === frame;
  // §5.3: 지지 세트가 없으면 같은 t*라도 다시 확정 가능(자동 3-2-1 재시도)
  const hasSupport = !!c.current_support_set_id;
  const prereq = !ready ? "① 추출을 먼저 실행하세요" : frame === null ? "후보 시점을 고르세요" : unchanged && hasSupport ? "현재 확정된 t*와 같습니다" : null;

  const confirm = () => act.run(() => api.putTstar(c.id, { version: c.version, metric, frame_index: frame! }));

  return (
    <StageFrame
      title="② t*·지지점"
      status={stepState(c, 2)}
      error={act.error ?? tv.error}
      primary={{ label: "t* 확정", onClick: confirm, disabledReason: blockReason(allowed, c, 2, prereq), busy: act.busy }}
    >
      {!ready ? (
        <Empty>① 입력 단계에서 추출을 먼저 실행하세요</Empty>
      ) : !tv.data ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <div className="step2-grid">
          <Card
            title="max-hold 곡선"
            right={
              <div className="seg" role="radiogroup" aria-label="지표">
                {METRICS.map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={metric === m} className={metric === m ? "on" : ""} onClick={() => setMetric(m)}>
                    {METRIC_LABEL[m]}
                  </button>
                ))}
              </div>
            }
          >
            {c.tstar && (
              <div className="small muted" data-testid="current-tstar">
                현재 t*: {METRIC_LABEL[c.tstar.metric]} · 프레임 {c.tstar.frame_index} · {c.tstar.time.toFixed(3)} s · 요소 {c.tstar.elem_id} · {c.tstar.source === "auto" ? "자동" : "사용자 선택"}
              </div>
            )}
            {cum && blk?.tstar && (
              <div className="small" data-testid="cum-tstar">
                자동 t* 값: {cumText(blk.tstar)}
                {blk.cumulative && <span className="muted"> · 이전 손상만(이번 증가 없음) {blk.cumulative.n_excluded_no_increment.toLocaleString()}개 제외</span>}
              </div>
            )}
            {blk ? (
              <MaxHoldChart
                time={blk.history.time}
                value={blk.history.value}
                valueInc={cum ? blk.history.value_inc : undefined}
                candidates={blk.candidates}
                selectedFrame={frame}
                label={METRIC_LABEL[metric]}
              />
            ) : (
              <Empty>이 지표의 결과가 없습니다</Empty>
            )}
          </Card>
          <div className="contents step2-pair">
            <Card title="후보 시점">
              <div className="table-wrap scroll">
              <table className="table compact">
                <thead>
                  <tr>
                    <th />
                    <th>순위</th>
                    <th className="num">프레임</th>
                    <th className="num">시간 (s)</th>
                    <th>요소</th>
                    <th className="num">{cum ? "누적" : "값"}</th>
                    {cum && <th className="num">이전</th>}
                    {cum && <th className="num">이번(증분)</th>}
                    <th>변위(D)</th>
                  </tr>
                </thead>
                <tbody>
                  {blk?.candidates.map((k) => {
                    const pickable = allowed && k.in_D !== false;
                    return (
                      <tr key={k.frame_index} className={frame === k.frame_index ? "hl" : undefined} onClick={() => pickable && setFrame(k.frame_index)}>
                        <td>
                          <input
                            type="radio"
                            name="tstar"
                            aria-label={`프레임 ${k.frame_index}`}
                            checked={frame === k.frame_index}
                            disabled={!pickable}
                            onChange={() => setFrame(k.frame_index)}
                          />
                        </td>
                        <td>{k.rank}</td>
                        <td className="num">{k.frame_index}</td>
                        <td className="num">{k.time.toFixed(3)}</td>
                        <td>{k.elem_id}</td>
                        <td className="num">{fmt(k.value, 4)}</td>
                        {cum && <td className="num">{fmt(k.value_prev, 4)}</td>}
                        {cum && <td className="num">{fmt(k.value_inc, 4)}</td>}
                        <td>{k.in_D === false ? <span className="error-text" title="변위가 추출되지 않은 프레임 — t*로 고를 수 없음">없음</span> : "있음"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              </div>
            </Card>
            <Card title={`hotspot (t* 프레임 ${blk?.tstar?.frame_index ?? "–"}에서 상승 중 = 검증 대상)`}>
              <div className="table-wrap scroll">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>순위</th>
                    <th>요소</th>
                    <th className="num">{cum ? "누적" : "값"}</th>
                    {cum && <th className="num">이전</th>}
                    {cum && <th className="num">이번(증분)</th>}
                    <th>중심 좌표</th>
                    <th>상승 중</th>
                  </tr>
                </thead>
                <tbody>
                  {hotspots.map((h) => (
                    <tr key={h.elem_id}>
                      <td>{h.rank}</td>
                      <td>{h.elem_id}</td>
                      <td className="num">{fmt(h.value, 4)}</td>
                      {cum && <td className="num">{fmt(h.value_prev, 4)}</td>}
                      {cum && <td className="num">{fmt(h.value_inc, 4)}</td>}
                      <td className="mono small">{h.centroid ? h.centroid.map((v) => v.toFixed(1)).join(", ") : "–"}</td>
                      <td>
                        {h.rising === null ? (
                          "?"
                        ) : h.rising ? (
                          <span className="ok-text" title="t* 프레임에서 값이 오르는 중 — hold 값 = 순간값이라 검증에 쓴다">
                            상승 중
                          </span>
                        ) : (
                          <span className="muted" title="t* 이전에 이미 최대 도달 — 검증 비교에서 제외">
                            아님
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            </Card>
          </div>
          <div className="step2-support">
            <SupportSummary c={c} allowed={allowed} reload={reload} />
          </div>
        </div>
      )}
    </StageFrame>
  );
}
