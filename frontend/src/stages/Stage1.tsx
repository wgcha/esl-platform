import { useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { InspectH3dResult } from "../api/types";
import { bytes } from "../lib/format";
import { Card, Empty, Field, Stat } from "../components/ui";
import { RadInspectView, ResultsInspectView, usePathInspect } from "../components/PathInspect";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";

export function Stage1({ c, reload, allowed }: StageProps) {
  const rad = usePathInspect("RAD", c.rad_path);
  const res = usePathInspect("RESULTS", c.results_dir);
  // §6: h3d 입력 Case — 서버가 h3d 에서 추출(첫 step H3D_EXTRACT). 결과 폴더는 추출 전엔 없으므로 h3d 를 확인한다
  const isH3d = c.input_kind === "H3D" && !!c.h3d_path;
  const [h3d, setH3d] = useState<{ r: InspectH3dResult | null; error: string | null } | null>(null);
  const [partTitle, setPartTitle] = useState(c.part_title);
  const act = useAction(reload);
  const s = c.extract_summary;

  useEffect(() => {
    void rad.inspect(c.rad_path, c.part_title);
    if (isH3d)
      api.inspectH3d(c.h3d_path!).then(
        (r) => setH3d({ r, error: null }),
        (e) => setH3d({ r: null, error: errorText(e) }),
      );
    else void res.inspect(c.results_dir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.id]);

  // 파트 title 을 바꾸면 그 값으로 rad 를 다시 확인(설정 기본값이 아니라 입력값으로 판정)
  const [titlePending, setTitlePending] = useState(false);
  const firstTitle = useRef(true);
  useEffect(() => {
    if (firstTitle.current) {
      firstTitle.current = false;
      return;
    }
    setTitlePending(true);
    const t = setTimeout(() => void rad.inspect(c.rad_path, partTitle).finally(() => setTitlePending(false)), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partTitle]);

  const prereq = !partTitle.trim()
    ? "파트 title을 입력하세요"
    : rad.error
      ? "rad 확인에 실패했습니다"
      : !rad.result || rad.busy || titlePending || (isH3d ? !h3d : !res.result && !res.error)
        ? "rad·h3d 확인 중…"
        : !rad.result.ok
          ? "rad 경로에 문제가 있습니다"
          : isH3d
            ? h3d?.error || !h3d?.r?.ok
              ? "h3d 파일에 문제가 있습니다"
              : null
            : res.error || !(res.result?.ok && res.result.done?.ok)
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
            {rad.result ? <RadInspectView r={rad.result} partTitle={partTitle} onPickPart={allowed ? setPartTitle : undefined} /> : <div className="small muted">{rad.error ?? "확인 중…"}</div>}
            {isH3d && (
              <>
                <Field label="h3d 파일" hint="서버에서 HyperView로 추출합니다(h3d는 읽기만)">
                  <span className="mono readonly-path">{c.h3d_path}</span>
                </Field>
                {h3d?.r ? (
                  <div className={h3d.r.ok ? "inspect ok small" : "inspect bad small"} aria-label="h3d 확인 결과">
                    {h3d.r.ok ? `h3d 확인됨 · ${bytes(h3d.r.size)}` : h3d.r.problems.join(", ")}
                  </div>
                ) : (
                  <div className="small muted">{h3d?.error ?? "확인 중…"}</div>
                )}
              </>
            )}
            <Field label={isH3d ? "추출 결과 폴더(서버가 만듦)" : "결과 폴더"}>
              <span className="mono readonly-path">{c.results_dir}</span>
            </Field>
            {isH3d ? (
              <div className="small muted" data-testid="h3d-stage-note">
                {c.extract_summary
                  ? "서버 추출을 마쳤습니다. 다시 실행하면 이전 추출 결과는 _backup 으로 옮기고 새로 추출합니다."
                  : '"추출 실행"을 누르면 서버에서 추출 중(HyperView) → 정리 → t* 후보 순서로 진행합니다. 진행·로그는 위 작업 줄에 보입니다.'}
              </div>
            ) : res.result ? (
              <ResultsInspectView r={res.result} />
            ) : (
              <div className="small muted">{res.error ?? "확인 중…"}</div>
            )}
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
