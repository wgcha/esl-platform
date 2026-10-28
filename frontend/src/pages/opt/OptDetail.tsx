// 비드 최적화 상세(esl_opt_run.md §3.3·§10.4): 진행 6단계 · 하중 선정 표(ⓘ) · 결과(비드 맵·수렴·케이스별 C⁰→C·받기).
// 주 버튼 = "보고서 보기"(완료 후). 로그·취소·재시도는 JobProgress(기존 /jobs API, OPT_RUN 에도 적용).
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, downloadFile, errorText } from "../../api/client";
import { NORM_NAME, SCENARIO_LABEL, STRATEGY_NAME, opt, sci } from "../../api/opt";
import type { JobOut, OptResult, OptRunOut } from "../../api/types";
import { canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Badge, Card, Empty, ErrorLine, JobStatusBadge, PrimaryButton, Stat } from "../../components/ui";
import { JobProgress } from "../../components/JobProgress";
import { LoadSelectionTable, selectionSummary } from "../../components/LoadSelectionTable";
import { MethodInfo } from "../../components/MethodInfo";
import { BundleButton } from "../../components/BundleButton";
import { openReport } from "../../components/ReportLink";
import { CORNER_LABEL } from "../../components/KeepoutPlan";
import { usePolling } from "../../lib/usePolling";
import { dt } from "../../lib/format";
import { libPath } from "../library/common";

const ACTIVE = ["QUEUED", "RUNNING"];
export const OPT_STEP_LABEL: Record<string, string> = {
  OPT_PREP: "대상",
  OPT_LOAD: "하중·선정",
  OPT_DECK: "덱",
  OS_SOLVE: "OptiStruct",
  OPT_POST: "후처리",
  OPT_REGISTER: "등록",
};
const MARK: Record<string, string> = { SUCCEEDED: "✓", RUNNING: "●", FAILED: "✗", SKIPPED: "↷" };

function Steps({ job }: { job: JobOut | null }) {
  const steps = job?.steps ?? [];
  if (!steps.length) return null;
  return (
    <ol className="job-steps" aria-label="최적화 단계">
      {steps.map((s) => (
        <li key={s.step_no} className={s.state.toLowerCase()} aria-current={s.state === "RUNNING" ? "step" : undefined}>
          {MARK[s.state] ?? "○"} {OPT_STEP_LABEL[s.step_key] ?? s.step_key}
          {s.state === "RUNNING" && s.progress_pct ? ` ${Math.round(s.progress_pct)}%` : ""}
        </li>
      ))}
    </ol>
  );
}

/** 목적값 수렴 그래프(반복 0..n) */
export function ConvergenceChart({ history, norm }: { history: number[]; norm: string }) {
  if (history.length < 2) return <Empty>수렴 이력 없음</Empty>;
  // 표시 폭(약 800 px)에 맞춘 viewBox — 글자가 과하게 커지지 않게
  const W = 800;
  const H = 260;
  const pad = { l: 48, r: 14, t: 12, b: 30 };
  const lo = Math.min(...history, 0.5);
  const hi = Math.max(...history, 1);
  const x = (i: number) => pad.l + (i / (history.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="수렴 그래프">
        <line className="chart-axis" x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} />
        <line className="chart-axis" x1={pad.l} y1={pad.t} x2={pad.l} y2={H - pad.b} />
        {[lo, (lo + hi) / 2, hi].map((v) => (
          <text key={v} className="chart-tick" x={pad.l - 4} y={y(v) + 3} textAnchor="end">
            {v.toFixed(2)}
          </text>
        ))}
        <text className="chart-tick" x={x(0)} y={H - 8} textAnchor="middle">
          0
        </text>
        <text className="chart-tick" x={x(history.length - 1)} y={H - 8} textAnchor="middle">
          {history.length - 1}
        </text>
        <text className="chart-label" x={(W + pad.l) / 2} y={H - 8} textAnchor="middle">
          반복 · {norm}
        </text>
        <polyline className="chart-line" fill="none" points={history.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
      </svg>
    </div>
  );
}

/** 비드 맵 PNG — fetch 로 받아 blob URL(같은 출처 인증 쿠키, 목 서버도 통과) */
function BeadMap({ id }: { id: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    fetch(opt.beadMapUrl(id), { credentials: "same-origin" })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`비드 맵을 불러오지 못했습니다(${r.status})`))))
      .then((b) => {
        if (!alive || typeof URL.createObjectURL !== "function") return;
        url = URL.createObjectURL(b);
        setSrc(url);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id]);
  if (error) return <div className="small error-text">{error}</div>;
  return src ? <img className="bead-map" src={src} alt="비드 맵(비드 높이 평면도)" /> : <Empty>비드 맵 불러오는 중…</Empty>;
}

function DownloadLink({ id, rel, label }: { id: string; rel: string; label: string }) {
  const [error, setError] = useState<string | null>(null);
  const url = opt.downloadUrl(id, rel);
  return (
    <span>
      <a
        className="btn small"
        href={url}
        download
        onClick={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await downloadFile(url, rel.split("/").pop() ?? "download");
          } catch (x) {
            setError(x instanceof ApiError && x.status === 413 ? "파일이 커서 받을 수 없습니다 — zip 대신 폴더에서 복사하세요" : errorText(x));
          }
        }}
      >
        {label}
      </a>
      {error && <span className="small error-text"> {error}</span>}
    </span>
  );
}

function Result({ r, run }: { r: OptResult; run: OptRunOut }) {
  const objLabel = r.objective_norm === "abs" ? "max C/C_ref" : "max C/C⁰";
  return (
    <Card title="결과">
      <div className="stats">
        <Stat label={`목적(${NORM_NAME[r.objective_norm]}) ${objLabel}`} value={`${r.objective.initial?.toFixed(2) ?? "–"} → ${r.objective.final?.toFixed(2) ?? "–"}`} sub={r.objective_norm === "abs" ? `C_ref ${sci(r.C_ref)}` : undefined} tone="ok" />
        <Stat label="반복" value={`${r.iterations}/${r.desmax}`} sub={r.converged ? "수렴" : "미수렴(DESMAX 도달)"} tone={r.converged ? undefined : "bad"} />
        <Stat label="비드 면적" value={`${Math.round(r.bead.area_frac * 100)}%`} sub={`최대 높이 ${r.bead.height_max} mm`} />
        <Stat label="설계 요소" value={r.keepout.n_design_elems.toLocaleString()} sub={`금지: 구멍 ${r.keepout.n_elems_auto_hole.toLocaleString()} · 가장자리 ${r.keepout.n_elems_auto_edge.toLocaleString()} · 사각형 ${r.keepout.n_elems_rects.toLocaleString()}`} />
        <Stat label="해석 시간" value={r.solve.seconds != null ? `${Math.round(r.solve.seconds / 60)}분` : "–"} sub={`라이선스 대기 ${r.solve.license_waits}회${r.solve.reused ? " · 재사용" : ""}`} />
      </div>
      {r.warnings.length > 0 && (
        <ul className="reasons small warn-text">
          {r.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <div className="opt-result-grid">
        <div>
          <div className="sub-title">비드 맵</div>
          <BeadMap id={run.id} />
        </div>
        <div>
          <div className="sub-title">수렴</div>
          <ConvergenceChart history={r.objective.history} norm={objLabel} />
          <div className="sub-title">케이스별 컴플라이언스</div>
          <table className="table compact" aria-label="케이스별 컴플라이언스">
            <thead>
              <tr>
                <th>케이스</th>
                <th className="num">C⁰ (OptiStruct)</th>
                <th className="num">C 최종</th>
                <th className="num">비율</th>
              </tr>
            </thead>
            <tbody>
              {r.subcases.map((s) => (
                <tr key={s.label}>
                  <td className="mono">{s.label}</td>
                  <td className="num mono" title={`자체 솔버 C⁰ ${sci(s.C0_self)}`}>
                    {sci(s.C0_os ?? s.C0_self)}
                  </td>
                  <td className="num mono">{sci(s.C_final)}</td>
                  <td className="num">{s.ratio != null ? s.ratio.toFixed(2) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="inline-actions">
        <span className="small muted">받기</span>
        <DownloadLink id={run.id} rel="post/bead_mesh.rad" label=".rad" />
        <DownloadLink id={run.id} rel="post/bead_mesh.fem" label=".fem" />
        <BundleButton url={opt.bundleUrl(run.id)} filename={`opt_${run.id}.zip`} />
      </div>
      <div className="small muted">다음: 비드 반영 메시({run.scenario === "S1" ? "대상 파트 교체" : "템플릿 형상"})로 낙하 해석 → 새 Case → 라이브러리 등록 → 버전 비교</div>
    </Card>
  );
}

export function OptDetail() {
  const { projectId = "", optId = "" } = useParams();
  const { me, projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const [poll, setPoll] = useState(3000);
  const run = usePolling(() => opt.run(optId), poll, [optId]);
  const settings = usePolling(() => opt.settings(), 0, []);
  const r = run.data;
  const done = r?.state === "SUCCEEDED";
  useEffect(() => {
    if (r && !ACTIVE.includes(r.state)) setPoll(0);
  }, [r]);
  const sel = r?.result?.load_selection ?? null;
  const reason = !r ? "불러오는 중…" : r.report_ready ? null : ACTIVE.includes(r.state) ? "최적화가 끝나면 볼 수 있습니다" : "최적화가 끝나지 않았습니다 — 보고서 없음";
  const os = r?.job?.steps?.find((s) => s.step_key === "OS_SOLVE");
  const ko = r?.design.keepout;

  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "라이브러리", to: `${libPath(projectId)}?tab=opt` }, { label: r?.title || "비드 최적화" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">비드 최적화</h1>
        {r && <Badge kind="info">{`${r.scenario} ${SCENARIO_LABEL[r.scenario]}`}</Badge>}
        {r?.title && <span className="muted">{r.title}</span>}
        {r && <JobStatusBadge state={r.state} />}
        {os?.state === "RUNNING" && <span className="small muted">OptiStruct {Math.round(os.progress_pct ?? 0)}%</span>}
        <span className="spacer" />
        <PrimaryButton label="보고서 보기" onClick={() => openReport(opt.reportUrl(optId))} disabledReason={reason} />
      </div>
      <ErrorLine text={run.error} />
      {r && (
        <Card title="진행">
          <Steps job={r.job} />
          {r.job && !done && <JobProgress jobId={r.job.id} allowed={allowed} onDone={() => void run.reload()} />}
          {done && r.result && (
            <div className="small muted">
              목적({NORM_NAME[r.objective_norm]}) {r.result.objective.initial?.toFixed(2)} → {r.result.objective.final?.toFixed(2)} · 라이선스 대기 {r.result.solve.license_waits}회
            </div>
          )}
        </Card>
      )}
      {r && (
        <Card title="설정">
          <div className="stats">
            <Stat label="대상" value={r.scenario === "S1" ? r.base?.part_title ?? "–" : r.template?.title ?? "–"} sub={r.scenario === "S1" ? r.base?.case_title ?? undefined : r.template ? `${Math.round(r.template.L_xi)}×${Math.round(r.template.L_eta)} mm` : undefined} />
            <Stat label="ESL" value={`${r.entry_ids.length}개`} />
            <Stat label="하중 선정" value={STRATEGY_NAME[r.load_strategy]} sub={r.load_strategy === "C" ? `k ${r.k}` : undefined} />
            <Stat label="목표 기준" value={NORM_NAME[r.objective_norm]} />
            <Stat label="비드" value={r.design.bead ? `${r.design.bead.angle}° · ${r.design.bead.min_width} · ${r.design.bead.height} mm` : "–"} sub="경사 · 폭 · 높이" />
            <Stat
              label="금지 영역"
              value={`사각형 ${ko?.rects.length ?? 0}`}
              sub={[ko?.auto.hole ? "구멍" : null, ko?.auto.edge ? "가장자리" : null].filter(Boolean).join("·") || "자동 없음"}
            />
            <Stat label="만든 사람" value={r.created_by_name} sub={dt(r.created_at)} />
          </div>
          {ko && ko.rects.length > 0 && <div className="small muted">사각형: {ko.rects.map((x) => `${x.name}(${CORNER_LABEL[x.corner]} ${x.x_mm},${x.y_mm} · ${x.w_mm}×${x.h_mm})`).join(" · ")}</div>}
        </Card>
      )}
      {r && (
        <Card title="하중 선정" right={<MethodInfo src={settings.data?.method_sources} strategy={r.load_strategy} norm={r.objective_norm} />}>
          {sel ? (
            <>
              <div className="small" data-testid="selection-summary">
                {selectionSummary(sel)}
              </div>
              <LoadSelectionTable sel={sel} />
            </>
          ) : (
            <Empty>하중·선정 단계가 끝나면 보입니다</Empty>
          )}
        </Card>
      )}
      {done && r?.result && <Result r={r.result} run={r} />}
    </Shell>
  );
}
