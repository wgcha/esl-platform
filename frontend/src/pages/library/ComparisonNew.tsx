// 설계 버전 비교 만들기(계약 §12.2): 제품 · 비교 버전(기본 최신) · 기준 버전(기본 직전) → 짝 씬 미리보기.
// 주 버튼 = "비교 실행"(POST /library/comparisons → LIB_COMPARE 작업) → 비교 상세.
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { errorText } from "../../api/client";
import type { EntryOut } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell, MENU_LIBRARY } from "../../shell/Shell";
import { Card, Empty, ErrorLine, Field, PrimaryButton } from "../../components/ui";
import { usePolling } from "../../lib/usePolling";
import { EntryVerdict, libPath, modelVersions, pairEntries, prevVersion, sceneText } from "./common";

export interface ComparisonForm {
  model: string;
  base: string;
  next: string;
}

/** 폼 → 실제 선택(빈 값은 기본: 첫 제품 · 최신 버전 · 그 직전 버전) + 막는 사유 */
export function resolveForm(f: ComparisonForm, entries: EntryOut[] | null) {
  if (!entries) return { model: "", base: "", next: "", versions: [] as string[], models: [], pairs: [], baseOnly: 0, newOnly: 0, reason: "불러오는 중…" };
  const models = modelVersions(entries).filter((m) => m.versions.length > 1);
  const mv = models.find((m) => m.model === f.model) ?? models[0];
  if (!mv) return { model: "", base: "", next: "", versions: [], models, pairs: [], baseOnly: 0, newOnly: 0, reason: "버전이 2개 이상인 제품이 없습니다 — 비드 반영 설계의 검증 낙하를 등록하세요" };
  const versions = mv.versions;
  const next = versions.includes(f.next) ? f.next : versions[versions.length - 1];
  const base = f.base && f.base !== next && versions.includes(f.base) ? f.base : prevVersion(versions, next) ?? versions.find((v) => v !== next)!;
  const { pairs, baseOnly, newOnly } = pairEntries(entries, mv.model, base, next);
  const reason = pairs.length === 0 ? "같은 씬(시나리오·seq·유형·scene·orient)의 짝이 없습니다" : null;
  return { model: mv.model, base, next, versions, models, pairs, baseOnly, newOnly, reason };
}

export function ComparisonNew() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const entries = usePolling(() => api.libraryEntries({ project_id: projectId, status: "ACTIVE" }), 0, [projectId]);
  const [f, setF] = useState<ComparisonForm>({ model: "", base: "", next: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const r = useMemo(() => resolveForm(f, entries.data), [f, entries.data]);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const c = await api.createComparison({ project_id: projectId, model: r.model, base_version: r.base, new_version: r.next });
      nav(`/p/${projectId}/library/comparisons/${c.id}`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Shell
      crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: MENU_LIBRARY, to: libPath(projectId) }, { label: "새 버전 비교" }]}
      projectId={projectId}
    >
      <div className="page-title-row">
        <h1 className="page-title">새 버전 비교</h1>
        <span className="muted small">비드 반영 설계의 검증 낙하 ESL 을 이전 설계와 씬별로 비교해 추가 반복이 필요한지 판정합니다</span>
        <span className="spacer" />
        <PrimaryButton label="비교 실행" onClick={submit} disabledReason={!allowed ? NO_PERMISSION : r.reason} busy={busy} />
      </div>
      <ErrorLine text={error ?? entries.error} />
      <Card title="제품·버전">
        {r.models.length === 0 ? (
          <Empty>{r.reason}</Empty>
        ) : (
          <div className="form-grid">
            <Field label="제품">
              <select aria-label="제품" value={r.model} onChange={(e) => setF({ model: e.target.value, base: "", next: "" })}>
                {r.models.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.model} ({m.versions.length}개 버전)
                  </option>
                ))}
              </select>
            </Field>
            <Field label="비교 버전 (새 설계)" hint="기본: 최신">
              <select aria-label="비교 버전" value={r.next} onChange={(e) => setF((o) => ({ ...o, model: r.model, next: e.target.value, base: "" }))}>
                {r.versions.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </Field>
            <Field label="기준 버전 (이전 설계)" hint="기본: 비교 버전 직전">
              <select aria-label="기준 버전" value={r.base} onChange={(e) => setF((o) => ({ ...o, model: r.model, next: r.next, base: e.target.value }))}>
                {r.versions
                  .filter((v) => v !== r.next)
                  .map((v) => (
                    <option key={v}>{v}</option>
                  ))}
              </select>
            </Field>
          </div>
        )}
      </Card>
      <Card title={`짝 씬 ${r.pairs.length}개`} right={r.baseOnly + r.newOnly > 0 ? <span className="small muted">짝 없음: 기준에만 {r.baseOnly} · 비교에만 {r.newOnly} (비교 제외)</span> : undefined}>
        {!entries.data ? (
          <Empty>불러오는 중…</Empty>
        ) : r.pairs.length === 0 ? (
          <Empty>{r.reason ?? "짝 씬이 없습니다"}</Empty>
        ) : (
          <div className="table-wrap scroll">
            <table className="table compact" aria-label="짝 씬">
              <thead>
                <tr>
                  <th>시나리오</th>
                  <th>씬</th>
                  <th>orient</th>
                  <th>기준 {r.base}</th>
                  <th>비교 {r.next}</th>
                </tr>
              </thead>
              <tbody>
                {r.pairs.map((p) => (
                  <tr key={p.key}>
                    <td>{p.next.scene.scenario ?? "–"}</td>
                    <td>{sceneText(p.next)}</td>
                    <td className="mono">{p.next.scene.orient ?? "–"}</td>
                    <td>
                      <EntryVerdict e={p.base} />
                    </td>
                    <td>
                      <EntryVerdict e={p.next} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="small muted">판정 기준·재군집 수는 서버 설정(library convergence: cos 최소, 대표 동일)을 따릅니다.</div>
      </Card>
    </Shell>
  );
}
