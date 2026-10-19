import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import type { Metric } from "../api/types";
import { Card, Empty } from "../components/ui";
import { MaxHoldChart } from "../components/MaxHoldChart";
import { usePolling } from "../lib/usePolling";
import { METRIC_LABEL, fmt } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, useAction } from "./common";

const METRICS: Metric[] = ["max_strain", "plastic_strain"];

export function Stage2({ c, reload, allowed }: StageProps) {
  const ready = !!c.extract_summary;
  const tv = usePolling(() => (ready ? api.tstar(c.id) : Promise.resolve(null)), 0, [c.id, ready]);
  const [metric, setMetric] = useState<Metric>(c.tstar?.metric ?? "max_strain");
  const [frame, setFrame] = useState<number | null>(c.tstar?.frame_index ?? null);
  const act = useAction(reload);
  const blk = tv.data?.metrics[metric];

  // 지표를 바꾸면 그 지표의 현재 t*(또는 자동값)를 기본 선택
  useEffect(() => {
    if (!tv.data) return;
    if (c.tstar && c.tstar.metric === metric) setFrame(c.tstar.frame_index);
    else setFrame(tv.data.metrics[metric]?.tstar.frame_index ?? null);
  }, [metric, tv.data, c.tstar?.metric, c.tstar?.frame_index]);

  const unchanged = !!c.tstar && c.tstar.metric === metric && c.tstar.frame_index === frame;
  const prereq = !ready ? "① 추출을 먼저 실행하세요." : frame === null ? "후보 시점을 고르세요." : unchanged ? "현재 확정된 t*와 같습니다." : null;

  const confirm = () => act.run(() => api.putTstar(c.id, { version: c.version, metric, frame_index: frame! }));

  return (
    <StageFrame
      title="② t*"
      status={c.stage_status?.["2"]}
      error={act.error ?? tv.error}
      primary={{ label: "t* 확정", onClick: confirm, disabledReason: blockReason(allowed, c, 2, prereq), busy: act.busy }}
    >
      {!ready ? (
        <Empty>① 입력 단계에서 추출을 먼저 실행하세요.</Empty>
      ) : !tv.data ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <>
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
              <div className="small muted">
                현재 t*: {METRIC_LABEL[c.tstar.metric]} · 프레임 {c.tstar.frame_index} · {c.tstar.time.toFixed(3)} s · 요소 {c.tstar.elem_id} · {c.tstar.source === "auto" ? "자동" : "사용자 선택"}
              </div>
            )}
            {blk ? <MaxHoldChart time={blk.history.time} value={blk.history.value} candidates={blk.candidates} selectedFrame={frame} label={METRIC_LABEL[metric]} /> : <Empty>이 지표의 결과가 없습니다.</Empty>}
          </Card>
          <div className="grid2">
            <Card title="후보 시점">
              <table className="tbl compact">
                <thead>
                  <tr>
                    <th />
                    <th>순위</th>
                    <th>프레임</th>
                    <th>시간 (s)</th>
                    <th>요소</th>
                    <th>값</th>
                  </tr>
                </thead>
                <tbody>
                  {blk?.candidates.map((k) => (
                    <tr key={k.frame_index} className={frame === k.frame_index ? "hl" : undefined} onClick={() => allowed && setFrame(k.frame_index)}>
                      <td>
                        <input
                          type="radio"
                          name="tstar"
                          aria-label={`프레임 ${k.frame_index}`}
                          checked={frame === k.frame_index}
                          disabled={!allowed}
                          onChange={() => setFrame(k.frame_index)}
                        />
                      </td>
                      <td>{k.rank}</td>
                      <td>{k.frame_index}</td>
                      <td>{k.time.toFixed(3)}</td>
                      <td>{k.elem_id}</td>
                      <td>{fmt(k.value, 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="hotspot">
              <table className="tbl compact">
                <thead>
                  <tr>
                    <th>순위</th>
                    <th>요소</th>
                    <th>값</th>
                    <th>중심 좌표</th>
                    <th>상승 중</th>
                  </tr>
                </thead>
                <tbody>
                  {tv.data.hotspots.map((h) => (
                    <tr key={h.elem_id}>
                      <td>{h.rank}</td>
                      <td>{h.elem_id}</td>
                      <td>{fmt(h.value, 4)}</td>
                      <td className="mono small">{h.centroid.map((v) => v.toFixed(1)).join(", ")}</td>
                      <td>{h.rising ? <span className="warn-text" title="t* 이후에도 값이 커지는 요소">상승 중</span> : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </>
      )}
    </StageFrame>
  );
}
