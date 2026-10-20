// 설계 버전 비교 상세(계약 §12.2): 진행 · 판정 배지(수렴/추가 반복 권장) · 집계 · 씬 표 · 보고서 보기(주 버튼).
// 요약 = ComparisonOut.result(워커 _compare_summary).
import { useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import type { ComparisonResolution, ComparisonResult, ComparisonVerdict, JobState } from "../../api/types";
import { useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Badge, Card, Empty, ErrorLine, JobStatusBadge, PrimaryButton, Stat } from "../../components/ui";
import { JobProgress } from "../../components/JobProgress";
import { openReport } from "../../components/ReportLink";
import { CopyPath } from "../../stages/Stage6";
import { usePolling } from "../../lib/usePolling";
import { dt, pv } from "../../lib/format";
import { VerdictBadge, libPath } from "./common";

const ACTIVE: string[] = ["QUEUED", "RUNNING"];
export const VERDICT_TEXT: Record<ComparisonVerdict, string> = { CONVERGED: "수렴(반복 불필요)", ITERATE: "추가 반복 권장" };

export function ComparisonVerdictBadge({ v }: { v: ComparisonVerdict }) {
  return <Badge kind={v === "CONVERGED" ? "ok" : "warn"}>{VERDICT_TEXT[v]}</Badge>;
}

/** 셀당 노드 해상도 경고 배지(§12.4) — 충분하면 표시하지 않음 */
export function ReliabilityBadge({ rs }: { rs: ComparisonResolution | null | undefined }) {
  if (!rs || rs.level === "ok") return null;
  const npc = rs.nodes_per_cell_min;
  const tip =
    npc == null
      ? "항목에 셀당 노드 수 정보가 없습니다"
      : `셀당 노드 중앙값 ${npc} < ${rs.min_nodes_per_cell}${rs.coarsen_applied ? " (2×2 묶음)" : ""} — 메시가 격자에 비해 성겨 같은 패턴도 cos 가 낮게 나올 수 있습니다`;
  return (
    <span title={tip} data-testid="reliability">
      <Badge kind={rs.level === "low" ? "bad" : "warn"}>{rs.label}</Badge>
    </span>
  );
}

const n3 = (v: number | null | undefined, d = 3) => (v == null || !Number.isFinite(v) ? "–" : v.toFixed(d));
const range = (r: { min: number | null; max: number | null }) => (r.min == null || r.max == null ? "–" : `${n3(r.min, 2)} – ${n3(r.max, 2)}`);

function SceneTable({ r }: { r: ComparisonResult }) {
  const cmin = r.criteria.cos_min;
  return (
    <div className="table-wrap scroll">
      <table className="table compact" aria-label="씬별 비교">
        <thead>
          <tr>
            <th>씬</th>
            <th className="num" title="하중 패턴 유사도(셀 합력·합모멘트, 단위 노름)">cos</th>
            <th className="num" title="Σ|f| 신/구">합력비</th>
            <th className="num" title="hotspot1 정규화 좌표 거리">hotspot 이동</th>
            <th className="num" title="최대변형률 신/구">ε_max 비</th>
            <th>검증 구 → 신</th>
            <th>변경 사유</th>
          </tr>
        </thead>
        <tbody>
          {r.scenes.map((s) => (
            <tr key={s.label} className={s.changed ? "hl" : undefined}>
              <td>{s.label}</td>
              <td className={`num${s.cos < cmin ? " error-text" : ""}`}>{n3(s.cos, 4)}</td>
              <td className="num">{n3(s.force_ratio)}</td>
              <td className="num">{n3(s.hotspot_shift)}</td>
              <td className="num">{n3(s.eps_ratio)}</td>
              <td>
                <VerdictBadge v={s.quality_base.verdict} /> → <VerdictBadge v={s.quality_new.verdict} />
              </td>
              <td className="small">{s.reasons.length ? s.reasons.join("; ") : <span className="muted">–</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ComparisonDetail() {
  const { projectId = "", comparisonId = "" } = useParams();
  const { projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const cp = usePolling(() => api.comparison(comparisonId), 0, [comparisonId]);
  const c = cp.data;
  const done = c?.status === "SUCCEEDED";
  const r = c?.result;
  const reason = !c ? "불러오는 중…" : done ? null : ACTIVE.includes(c.status) ? "비교가 끝나면 볼 수 있습니다" : "비교가 끝나지 않았습니다 — 보고서 없음";
  const cv = r?.convergence;

  return (
    <Shell
      crumbs={[
        { label: project?.name ?? projectId, to: `/p/${projectId}` },
        { label: "라이브러리", to: libPath(projectId) },
        { label: c?.title || "버전 비교" },
      ]}
      projectId={projectId}
    >
      <div className="page-title-row">
        <h1 className="page-title">버전 비교</h1>
        {c && c.status !== "NONE" && <JobStatusBadge state={c.status as JobState} />}
        {c && (
          <span className="muted">
            {c.model} · {c.base_version} → {c.new_version}
          </span>
        )}
        <span className="spacer" />
        <PrimaryButton label="보고서 보기" onClick={() => openReport(api.comparisonReportUrl(comparisonId))} disabledReason={reason} />
      </div>
      <ErrorLine text={cp.error} />
      {c?.job_id && !done && <JobProgress jobId={c.job_id} onDone={() => void cp.reload()} />}
      {done && !r && <Empty>요약이 없습니다</Empty>}
      {r && cv && (
        <Card title="판정">
          <div className="verdict-row" data-testid="verdict">
            <ComparisonVerdictBadge v={cv.verdict} />
            <ReliabilityBadge rs={r.resolution} />
            <span className="small muted">
              기준: 씬 cos 최소 ≥ {cv.criteria.cos_min}
              {cv.criteria.rep_same ? " · 대표 케이스 동일(짝 medoid cos ≥ 기준)" : ""}
            </span>
          </div>
          {cv.reasons.length > 0 ? (
            <ul className="reasons small warn-text">
              {cv.reasons.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          ) : (
            <div className="small muted">모든 짝 씬의 하중 패턴이 기준 이상으로 같고 대표 케이스가 그대로입니다 — 추가 비드 최적화 반복이 필요 없습니다.</div>
          )}
          <div className="stats">
            <Stat label="짝 씬" value={r.n_paired} sub={`기준 ${r.n_base} · 비교 ${r.n_new}`} />
            <Stat label="cos 최소" value={n3(r.aggregate.cos_min, 4)} sub={r.aggregate.argmin_cos} tone={r.aggregate.cos_min < cv.criteria.cos_min ? "bad" : "ok"} />
            <Stat label="cos 평균" value={n3(r.aggregate.cos_mean, 4)} />
            <Stat label="대표 동일" value={r.representatives.rep_same ? "예" : "아니오"} sub={`k = ${r.representatives.k} · 멤버 일치 ${pv(100 * r.representatives.partition_agreement)}`} tone={r.representatives.rep_same ? "ok" : "bad"} />
            <Stat label="합력비" value={range(r.aggregate.force_ratio)} />
            <Stat label="ε_max 비 최대" value={n3(r.aggregate.eps_ratio.max)} />
          </div>
        </Card>
      )}
      {r && (
        <Card title={`씬별 비교 ${r.scenes.length}개`} right={r.aggregate.n_changed ? <span className="small warn-text">바뀐 씬 {r.aggregate.n_changed}개</span> : undefined}>
          <SceneTable r={r} />
          {r.unpaired && r.unpaired.base_only.length + r.unpaired.new_only.length > 0 && (
            <div className="small muted">
              짝 없는 씬(비교 제외): 기준에만 {r.unpaired.base_only.length} · 비교에만 {r.unpaired.new_only.length}
            </div>
          )}
        </Card>
      )}
      {c && (
        <Card title="설정">
          <div className="stats">
            <Stat label="제품" value={c.model} />
            <Stat label="기준 → 비교" value={`${c.base_version} → ${c.new_version}`} sub={`항목 ${c.base_entry_ids.length} · ${c.new_entry_ids.length}`} />
            <Stat label="만든 사람" value={c.created_by_name} sub={dt(c.created_at)} />
          </div>
          <CopyPath path={c.folder_path} />
        </Card>
      )}
    </Shell>
  );
}
