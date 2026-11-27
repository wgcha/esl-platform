import { useEffect, useMemo, useRef, useState } from "react";
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
import { curvePoints, dispState, manualFromCurve, manualNotes, parseManual, pctText } from "../lib/tstarFrames";

const METRICS: Metric[] = ["max_strain", "plastic_strain"];

export function Stage2({ c, reload, allowed }: StageProps) {
  const ready = !!c.extract_summary;
  const tv = usePolling(() => (ready ? api.tstar(c.id) : Promise.resolve(null)), 0, [c.id, ready]);
  const [metric, setMetric] = useState<Metric>(c.tstar?.metric ?? "max_strain");
  const [frame, setFrame] = useState<number | null>(c.tstar?.frame_index ?? null);
  const act = useAction(reload);
  const blk = tv.data?.metrics[metric];
  // v0.25.2 §7.1: "직접" 행 = 후보 밖 프레임(곡선 클릭 또는 입력 칸 — 같은 상태)
  const [manualFrame, setManualFrame] = useState<number | null>(null);
  const [manualText, setManualText] = useState("");
  const [manualBad, setManualBad] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pts = useMemo(() => curvePoints(blk, tv.data), [blk, tv.data]);
  const hotspots = blk?.hotspots ?? tv.data?.hotspots ?? [];
  // v0.8.0 누적 씬: 값 = 누적(이전 + 이번), 표에 이전·이번(증분) 열
  const cum = !!tv.data?.cumulative && hasCum(blk?.tstar);

  // 지표를 바꾸면 그 지표의 현재 t*(또는 자동값)를 기본 선택
  useEffect(() => {
    if (!tv.data) return;
    const f = c.tstar && c.tstar.metric === metric ? c.tstar.frame_index : tv.data.metrics[metric]?.tstar?.frame_index ?? null;
    setFrame(f);
    // 저장된 t* 가 후보 밖(직접 고름)이면 "직접" 칸에 채움
    const isCand = f !== null && !!tv.data.metrics[metric]?.candidates.some((k) => k.frame_index === f);
    setManualFrame(f !== null && !isCand ? f : null);
    setManualText(f !== null && !isCand ? String(f) : "");
    setManualBad(false);
  }, [metric, tv.data, c.tstar?.metric, c.tstar?.frame_index]);

  const cands = blk?.candidates ?? [];
  const isCand = frame !== null && cands.some((k) => k.frame_index === frame);
  const warnRatio = tv.data?.manual_ratio_warn;
  const autoFrame = blk?.tstar?.frame_index;
  const pickFrame = (f: number) => {
    setFrame(f);
    setManualBad(false);
    if (!cands.some((k) => k.frame_index === f)) {
      setManualFrame(f);
      setManualText(String(f));
    }
  };
  const commitManual = () => {
    const r = parseManual(manualText, pts);
    if (r.ok) pickFrame(r.frame);
    else setManualBad(r.reason !== "empty");
  };
  const mp = manualFrame === null ? undefined : pts.find((p) => p.frame === manualFrame);
  const mDisp = manualFrame === null ? null : dispState(manualFrame, tv.data);
  const mCmp = mp ? manualFromCurve(pts, mp.frame, autoFrame) : null;
  const mNotes = mp && mCmp ? manualNotes(mCmp, mp.frame, mp.time, warnRatio) : [];
  const mLow = mNotes.some((n) => n.code === "TSTAR_MANUAL_LOW");
  const fillText = tv.data?.fill?.text ?? "";
  const frameState = frame !== null && !isCand ? dispState(frame, tv.data) : "have";

  const unchanged = !!c.tstar && c.tstar.metric === metric && c.tstar.frame_index === frame;
  // §5.3: 지지 세트가 없으면 같은 t*라도 다시 확정 가능(자동 3-2-1 재시도)
  const hasSupport = !!c.current_support_set_id;
  const prereq = !ready
    ? "① 추출을 먼저 실행하세요"
    : frame === null
      ? "후보 시점을 고르세요"
      : frameState === "blocked"
        ? `이 시점은 고를 수 없습니다 — ${fillText || "변위를 읽을 수 없는 프레임입니다"}`
        : unchanged && hasSupport
          ? "현재 확정된 t*와 같습니다"
          : null;

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
            {c.tstar && (() => {
              const man = c.tstar.manual;
              const low = !!man && man.ratio !== null && warnRatio !== undefined && man.ratio < warnRatio;
              const notes = man ? manualNotes(man, c.tstar.frame_index, c.tstar.time, warnRatio) : [];
              return (
                <div
                  className={`small ${low ? "warn-text" : "muted"} ellipsis`}
                  data-testid="current-tstar"
                  title={notes.length ? notes.map((n) => n.text).join("\n") : undefined}
                >
                  현재 t*: {METRIC_LABEL[c.tstar.metric]} · 프레임 {c.tstar.frame_index} · {c.tstar.time.toFixed(3)} s · 요소 {c.tstar.elem_id} ·{" "}
                  {c.tstar.source === "auto" ? "자동" : man ? `직접 고름 · 자동 대비 ${pctText(man.ratio)} %` : "사용자 선택"}
                </div>
              );
            })()}
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
                frames={pts.map((p) => p.frame)}
                onPick={allowed ? pickFrame : undefined}
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
                  {cands.map((k) => {
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
                  {blk && (
                    <tr
                      data-testid="manual-row"
                      className={frame !== null && !isCand && frame === manualFrame ? "hl" : undefined}
                      onClick={() => {
                        if (allowed && manualFrame !== null && frame !== manualFrame) pickFrame(manualFrame);
                      }}
                    >
                      <td colSpan={2}>
                        <span className="tstar-manual-cell">
                          <input
                            type="radio"
                            name="tstar"
                            aria-label="직접"
                            checked={frame !== null && !isCand && frame === manualFrame}
                            disabled={!allowed || mDisp === "blocked"}
                            title={mDisp === "blocked" ? fillText : undefined}
                            onChange={() => (manualFrame !== null ? pickFrame(manualFrame) : inputRef.current?.focus())}
                          />
                          <input
                            ref={inputRef}
                            type="text"
                            className={manualBad ? "tstar-manual-in bad" : "tstar-manual-in"}
                            data-testid="manual-input"
                            aria-label="직접 시점"
                            placeholder="프레임 번호 또는 시간(s)"
                            value={manualText}
                            disabled={!allowed}
                            aria-invalid={manualBad}
                            title={manualBad ? "h3d 에 없는 프레임" : "정수 = 프레임 번호, 소수점 또는 끝에 s = 시간(가장 가까운 프레임)"}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              setManualText(e.target.value);
                              setManualBad(false);
                            }}
                            onBlur={commitManual}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitManual();
                            }}
                          />
                        </span>
                      </td>
                      <td className="num">{mp ? mp.frame : "–"}</td>
                      <td className="num">{mp ? mp.time.toFixed(3) : "–"}</td>
                      <td>–</td>
                      <td className="num" title={mNotes.map((n) => n.text).join("\n") || undefined}>
                        {mp ? (
                          <span className={mLow ? "warn-text" : undefined} data-testid="manual-value">
                            {fmt(mp.value, 4)}
                            {mCmp && mCmp.rel !== "at" && <span className="muted"> ({pctText(mCmp.ratio)} %)</span>}
                          </span>
                        ) : (
                          "–"
                        )}
                      </td>
                      {cum && <td className="num">–</td>}
                      {cum && <td className="num">–</td>}
                      <td data-testid="manual-disp">
                        {mDisp === null ? (
                          "–"
                        ) : mDisp === "have" ? (
                          "있음"
                        ) : mDisp === "fill" ? (
                          <span className="muted" title="③ ESL 실행 때 이 프레임을 h3d 에서 한 번 읽습니다(몇 분)">
                            ESL 때 읽음
                          </span>
                        ) : (
                          <span className="error-text" title={fillText}>
                            불가
                          </span>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              </div>
            </Card>
            <Card
              title={`hotspot (t* 프레임 ${blk?.tstar?.frame_index ?? "–"}에서 상승 중 = 검증 대상)`}
              hint="직접 고른 시점의 hotspot 은 ESL 뒤 ④ 검증에 표시"
            >
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
