// 종합분석 상세(계약 §11 UI): 진행 상태 · 요약(대표 케이스 표, 포락 미니맵) · 보고서 보기(주 버튼) · 덱 파일 다운로드.
// 요약 = AnalysisOut.result(워커 _analysis_summary). 포락 격자는 result 에 없어 envelope.csv(다운로드 API)를 읽는다.
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { ApiError, downloadFile } from "../../api/client";
import type { AnalysisFileOut, AnalysisResult, JobState } from "../../api/types";
import { useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Card, Empty, ErrorLine, JobStatusBadge, PrimaryButton, Stat } from "../../components/ui";
import { JobProgress } from "../../components/JobProgress";
import { openReport } from "../../components/ReportLink";
import { CopyPath, TOO_LARGE_TEXT } from "../../stages/Stage6";
import { usePolling } from "../../lib/usePolling";
import { bytes, dt } from "../../lib/format";
import { f3 } from "../../lib/colormap";
import { EnvelopeMap, NORM_LABEL, OBJ_LABEL, VerdictBadge, dropText, entryLabel, filtersText, libPath, parseEnvelopeCsv } from "./common";

const ACTIVE: string[] = ["QUEUED", "RUNNING"];
const KIND_LABEL: Record<string, string> = { optdeck: "최적화 덱", report: "보고서", analysis: "분석 자료", log: "로그", other: "기타" };

function FileRow({ aid, f }: { aid: string; f: AnalysisFileOut }) {
  const [tooLarge, setTooLarge] = useState(!f.downloadable);
  const [error, setError] = useState<string | null>(null);
  const url = api.analysisDownloadUrl(aid, f.rel);
  return (
    <tr>
      <td className="mono">{f.rel}</td>
      <td>{KIND_LABEL[f.kind] ?? f.kind}</td>
      <td className="num">{bytes(f.size)}</td>
      <td>
        {tooLarge ? (
          <div className="too-large" data-testid="too-large">
            <div className="small warn-text">{TOO_LARGE_TEXT}</div>
            <CopyPath path={f.path} />
          </div>
        ) : (
          <>
            <a
              href={url}
              download
              onClick={async (e) => {
                e.preventDefault();
                setError(null);
                try {
                  await downloadFile(url, f.rel.split("/").pop() ?? "download");
                } catch (x) {
                  if (x instanceof ApiError && x.status === 413) setTooLarge(true);
                  else setError(x instanceof Error ? x.message : String(x));
                }
              }}
            >
              다운로드
            </a>
            {error && <div className="small error-text">{error}</div>}
          </>
        )}
      </td>
    </tr>
  );
}

function RepTable({ r }: { r: AnalysisResult }) {
  return (
    <div className="table-wrap">
      <table className="table compact" aria-label="대표 케이스">
        <thead>
          <tr>
            <th>하중 케이스</th>
            <th>씬</th>
            <th>orient</th>
            <th className="num">군집 크기</th>
            <th className="num">Σ|F| (N)</th>
            <th>판정</th>
          </tr>
        </thead>
        <tbody>
          {r.load_cases.map((lc) => {
            const c = r.cases[lc.case_index];
            const cl = r.clusters.find((x) => x.id === lc.cluster);
            return (
              <tr key={lc.label}>
                <td>
                  <b>{lc.label}</b> <span className="muted small">{lc.role === "medoid" ? "대표" : "최악"}</span>
                </td>
                <td>
                  {c?.product ?? "?"}
                  {c?.inch ? ` (${c.inch}")` : ""} · {dropText(c?.drop_class)}
                  {c?.scene != null ? ` · Scene ${c.scene}` : ""}
                  {c?.scenario && <span className="muted small"> · {c.scenario}</span>}
                </td>
                <td className="mono">{c?.orient ?? "–"}</td>
                <td className="num">{cl?.size ?? "–"}</td>
                <td className="num">{f3(c?.sum_abs_f)}</td>
                <td>
                  <VerdictBadge v={c?.verdict} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AnalysisDetail() {
  const { projectId = "", analysisId = "" } = useParams();
  const { projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const an = usePolling(() => api.analysis(analysisId), 0, [analysisId]);
  const a = an.data;
  const done = a?.status === "SUCCEEDED";
  const files = usePolling(() => (done ? api.analysisFiles(analysisId) : Promise.resolve([] as AnalysisFileOut[])), 0, [analysisId, done]);
  const hasEnv = !!files.data?.some((f) => f.rel === "envelope.csv" && f.downloadable);
  const env = usePolling(
    () =>
      hasEnv
        ? fetch(api.analysisDownloadUrl(analysisId, "envelope.csv"), { credentials: "same-origin" }).then((r) => (r.ok ? r.text().then(parseEnvelopeCsv) : null))
        : Promise.resolve(null),
    0,
    [analysisId, hasEnv],
  );
  const entries = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const target = a?.target_entry_id ? entries.data?.find((e) => e.id === a.target_entry_id) : undefined;
  const r = a?.result;

  const reason = !a ? "불러오는 중…" : done ? null : ACTIVE.includes(a.status) ? "분석이 끝나면 볼 수 있습니다" : "분석이 끝나지 않았습니다 — 보고서 없음";
  const nRep = r ? r.load_cases.filter((x) => x.role === "medoid").length : 0;

  return (
    <Shell
      crumbs={[
        { label: project?.name ?? projectId, to: `/p/${projectId}` },
        { label: "라이브러리", to: libPath(projectId) },
        { label: a?.title || "종합분석" },
      ]}
      projectId={projectId}
    >
      <div className="page-title-row">
        <h1 className="page-title">종합분석</h1>
        {a && a.status !== "NONE" && <JobStatusBadge state={a.status as JobState} />}
        {a?.title && <span className="muted">{a.title}</span>}
        <span className="spacer" />
        <PrimaryButton label="보고서 보기" onClick={() => openReport(api.analysisReportUrl(analysisId))} disabledReason={reason} />
      </div>
      <ErrorLine text={an.error} />
      {a?.job_id && !done && <JobProgress jobId={a.job_id} onDone={() => void an.reload()} />}
      {a && (
        <Card title="설정">
          <div className="stats">
            <Stat label="설계 대상" value={target ? entryLabel(target) : a.target_entry_id ?? "없음(정규화 격자)"} />
            <Stat label="필터" value={filtersText(a.filters)} sub={`항목 ${a.n_entries}개`} />
            <Stat label="정규화" value={NORM_LABEL[a.options.normalization ?? "none"]} />
            <Stat label="목적" value={OBJ_LABEL[a.options.objective ?? "minmax"]} />
            <Stat label="만든 사람" value={a.created_by_name} sub={dt(a.created_at)} />
          </div>
          <CopyPath path={a.folder_path} />
        </Card>
      )}
      {done && !r && <Empty>요약이 없습니다</Empty>}
      {r && (
        <>
          <Card title="요약">
            <div className="stats">
              <Stat label="항목 수" value={r.n_cases} />
              <Stat label="대표 케이스" value={nRep} sub={r.load_cases.length > nRep ? `최악 케이스 ${r.load_cases.length - nRep}개 포함` : undefined} />
              <Stat label="SVD 모드" value={r.svd.n_modes} sub={r.svd.cum_energy_at_r != null ? `누적 에너지 ${Math.round(r.svd.cum_energy_at_r * 100)}%` : undefined} />
              <Stat label="최대 셀 합력" value={r.envelope ? `${f3(r.envelope.max)} N` : "–"} sub={r.envelope ? `셀 (${r.envelope.argmax_cell.join(", ")})` : undefined} />
              {r.optdeck && <Stat label="최적화 덱" value={r.optdeck.deck} sub={`subcase ${r.optdeck.n_subcases} · 설계 요소 ${r.optdeck.n_design_elems.toLocaleString()}`} />}
            </div>
            {r.warnings.length > 0 && (
              <ul className="reasons small warn-text">
                {r.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
          </Card>
          <div className="grid-main">
            <Card title="대표 케이스">
              <RepTable r={r} />
            </Card>
            <Card title="셀 합력 포락">{env.data ? <EnvelopeMap env={env.data} /> : <Empty>{hasEnv || !files.data ? "불러오는 중…" : "포락 자료(envelope.csv) 없음"}</Empty>}</Card>
          </div>
        </>
      )}
      {done && (
        <Card title="파일 (최적화 덱·보고서)">
          {!files.data ? (
            <Empty>{files.error ?? "불러오는 중…"}</Empty>
          ) : files.data.length === 0 ? (
            <Empty>파일이 없습니다</Empty>
          ) : (
            <div className="table-wrap">
              <table className="table compact" aria-label="분석 파일">
                <thead>
                  <tr>
                    <th>파일</th>
                    <th>종류</th>
                    <th className="num">크기</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {files.data.map((f) => (
                    <FileRow key={f.rel} aid={analysisId} f={f} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {a?.optdeck_rel && <div className="small muted">덱은 사용자 측(Windows/HPC)에서 OptiStruct로 실행합니다 — 먼저 optistruct -check 로 문법을 확인하세요(opt/README 참고).</div>}
        </Card>
      )}
    </Shell>
  );
}
