// 라이브러리 목록(계약 §11·§12 UI): 항목 표 + 필터 + 메타 수정(인라인 최소) + 폐기. 주 버튼 = "종합분석 만들기",
// 보조 진입 "버전 비교"(설계 버전 비교 만들기) + 비교 목록.
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { errorText } from "../../api/client";
import type { DropType, EntryOut, EntryStatus } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Badge, Card, Empty, ErrorLine, Field, JobStatusBadge, PrimaryButton } from "../../components/ui";
import { usePolling } from "../../lib/usePolling";
import { dt, pv } from "../../lib/format";
import { DROP_LABEL, DROP_TYPES, NORM_LABEL, EntryVerdict, entryLabel, modelVersions, sceneText, uniq } from "./common";
import { ComparisonVerdictBadge } from "./ComparisonDetail";

interface Filters {
  model: string;
  drop_type: string;
  orient: string;
  verdict: string;
  retired: boolean;
}

const EMPTY: Filters = { model: "", drop_type: "", orient: "", verdict: "", retired: false };
const forceReason = (e: EntryOut) => e.force_reason ?? e.quality.confirmed_fail?.reason ?? null;

function EditRow({ e, onDone }: { e: EntryOut; onDone: (changed: boolean) => void }) {
  const [mass, setMass] = useState(e.model.product_mass != null ? String(e.model.product_mass) : "");
  const [drop, setDrop] = useState(e.scene.drop_type ?? "");
  const [orient, setOrient] = useState(e.scene.orient ?? "");
  const [confirmRetire, setConfirmRetire] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const massNum = mass.trim() === "" ? null : Number(mass);
  const massBad = massNum !== null && !(Number.isFinite(massNum) && massNum > 0);
  const orientBad = orient !== "" && !/^[1-6]{1,3}$/.test(orient);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone(true);
    } catch (x) {
      setError(errorText(x));
      setBusy(false);
    }
  }
  const save = () =>
    run(() =>
      api.patchEntry(e.id, {
        version: e.version,
        model: { product_mass: massNum },
        scene: { drop_type: (drop || null) as DropType | null, orient: orient || null },
      }),
    );

  return (
    <tr className="hl" data-testid="edit-row">
      <td>{e.model.name}</td>
      <td className="num">{e.model.inch ?? "–"}</td>
      <td>
        <select aria-label="씬 유형" value={drop} onChange={(x) => setDrop(x.target.value)}>
          <option value="">?</option>
          {DROP_TYPES.map((d) => (
            <option key={d} value={d}>
              {DROP_LABEL[d]}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input aria-label="orient" className="mono" value={orient} aria-invalid={orientBad} title="ISTA 면 번호 1~6, 1~3자리" onChange={(x) => setOrient(x.target.value.trim())} />
      </td>
      <td>
        <EntryVerdict e={e} />
      </td>
      <td className="num">{pv(e.quality.field_max_err_pct)}</td>
      <td className="num">
        <input type="number" aria-label="제품 질량 (kg)" min={0} step="0.1" value={mass} aria-invalid={massBad} placeholder="kg" onChange={(x) => setMass(x.target.value)} />
      </td>
      <td className="num">{dt(e.registered_at)}</td>
      <td>
        <div className="actions">
          {confirmRetire ? (
            <>
              <span className="small error-text">폐기할까요?</span>
              <button type="button" className="btn small danger" disabled={busy} onClick={() => run(() => api.retireEntry(e.id))}>
                폐기
              </button>
              <button type="button" className="btn small ghost" onClick={() => setConfirmRetire(false)}>
                아니오
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn small" disabled={busy || massBad || orientBad} onClick={save}>
                저장
              </button>
              <button type="button" className="btn small ghost" onClick={() => onDone(false)}>
                취소
              </button>
              <button type="button" className="link small error-text" onClick={() => setConfirmRetire(true)} title="분석에서 빼고 보관(정정 = 새로 등록 + 이전 것 폐기)">
                폐기…
              </button>
            </>
          )}
        </div>
        {error && <div className="small error-text">{error}</div>}
      </td>
    </tr>
  );
}

export function LibraryList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const [f, setF] = useState<Filters>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const status: EntryStatus | undefined = f.retired ? undefined : "ACTIVE";
  const all = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const rows = usePolling(
    () =>
      api.libraryEntries({
        project_id: projectId,
        model: f.model || undefined,
        drop_type: f.drop_type || undefined,
        orient: f.orient || undefined,
        verdict: f.verdict || undefined,
        status,
      }),
    0,
    [projectId, f.model, f.drop_type, f.orient, f.verdict, status],
  );
  const analyses = usePolling(() => api.analyses(projectId), 10000, [projectId]);
  const comparisons = usePolling(() => api.comparisons(projectId), 10000, [projectId]);
  const entries = all.data ?? [];
  const set = (k: keyof Filters, v: string | boolean) => setF((o) => ({ ...o, [k]: v }));
  const filtered = Object.entries(f).some(([k, v]) => (k === "retired" ? false : !!v));
  const byId = new Map(entries.map((e) => [e.id, e]));

  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "라이브러리" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">라이브러리</h1>
        <span className="muted small">검증한 ESL 하중을 모델·낙하 씬별로 모아 종합분석에 씁니다</span>
        <span className="spacer" />
        <Link
          className="btn"
          to={`/p/${projectId}/library/comparisons/new`}
          title={all.data && !modelVersions(entries).some((m) => m.versions.length > 1) ? "버전이 2개 이상인 제품이 아직 없습니다" : "비드 반영 설계의 검증 낙하를 이전 버전과 비교(수렴 판정)"}
        >
          버전 비교
        </Link>
        <PrimaryButton
          label="종합분석 만들기"
          onClick={() => nav(`/p/${projectId}/library/analyses/new`)}
          disabledReason={!allowed ? NO_PERMISSION : all.data && !entries.some((e) => e.status === "ACTIVE") ? "등록된 항목이 없습니다 — ⑤ 검증에서 '라이브러리 등록'" : null}
        />
      </div>
      <ErrorLine text={rows.error ?? all.error} />
      <Card title="항목">
        <div className="filters" role="search" aria-label="항목 필터">
          <Field label="모델">
            <select aria-label="모델" value={f.model} onChange={(e) => set("model", e.target.value)}>
              <option value="">전체</option>
              {uniq(entries.map((e) => e.model.name)).map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </Field>
          <Field label="씬 유형">
            <select aria-label="씬 유형" value={f.drop_type} onChange={(e) => set("drop_type", e.target.value)}>
              <option value="">전체</option>
              {DROP_TYPES.map((d) => (
                <option key={d} value={d}>
                  {DROP_LABEL[d]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="orient">
            <select aria-label="orient" value={f.orient} onChange={(e) => set("orient", e.target.value)}>
              <option value="">전체</option>
              {uniq(entries.map((e) => e.scene.orient)).map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </Field>
          <Field label="판정">
            <select aria-label="판정" value={f.verdict} onChange={(e) => set("verdict", e.target.value)}>
              <option value="">전체</option>
              <option value="PASS">PASS</option>
              <option value="FAIL">FAIL</option>
              <option value="UNDETERMINED">판정 불가</option>
              <option value="LEGACY">이전 판정 체계</option>
            </select>
          </Field>
          <label className="check small">
            <input type="checkbox" checked={f.retired} onChange={(e) => set("retired", e.target.checked)} /> 폐기 포함
          </label>
          {filtered && (
            <button type="button" className="btn small ghost" onClick={() => setF((o) => ({ ...EMPTY, retired: o.retired }))}>
              필터 지우기
            </button>
          )}
          <span className="spacer" />
          {rows.data && <span className="small muted" data-testid="entry-count">{rows.data.length}개</span>}
        </div>
        {!rows.data ? (
          <Empty>{rows.error ? "" : "불러오는 중…"}</Empty>
        ) : rows.data.length === 0 ? (
          <Empty>{filtered ? "조건에 맞는 항목이 없습니다" : "아직 등록된 항목이 없습니다 — Case ⑤ 검증 결과에서 '라이브러리 등록'"}</Empty>
        ) : (
          <div className="table-wrap scroll">
            <table className="table" aria-label="라이브러리 항목">
              <thead>
                <tr>
                  <th>모델</th>
                  <th className="num">인치</th>
                  <th>씬 유형</th>
                  <th>orient</th>
                  <th>판정</th>
                  <th className="num">최대오차</th>
                  <th className="num">제품 질량</th>
                  <th className="num">등록일</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.data.map((e) =>
                  editing === e.id ? (
                    <EditRow
                      key={e.id}
                      e={e}
                      onDone={(changed) => {
                        setEditing(null);
                        if (changed) void Promise.all([rows.reload(), all.reload()]);
                      }}
                    />
                  ) : (
                    <tr key={e.id} className={e.status === "RETIRED" ? "retired" : undefined}>
                      <td>
                        <span title={e.scene.raw ?? undefined}>{e.model.name ?? "–"}</span>
                        {e.model.version && <span className="muted small"> {e.model.version}</span>}
                        {e.status === "RETIRED" && (
                          <>
                            {" "}
                            <Badge kind="warn">폐기</Badge>
                          </>
                        )}
                      </td>
                      <td className="num">{e.model.inch ?? "–"}</td>
                      <td>
                        {sceneText(e)}
                        {e.scene.scenario && <span className="muted small"> · {e.scene.scenario}</span>}
                      </td>
                      <td className="mono">{e.scene.orient ?? "–"}</td>
                      <td title={forceReason(e) ? `확정 사유: ${forceReason(e)}` : undefined}>
                        <EntryVerdict e={e} />
                        {forceReason(e) && <span className="muted small"> 확정</span>}
                      </td>
                      <td className="num" title={`P90 ${pv(e.quality.field_p90_err_pct)}`}>
                        {pv(e.quality.field_max_err_pct)}
                      </td>
                      <td className="num">{e.model.product_mass != null ? `${e.model.product_mass} kg` : <span className="muted">–</span>}</td>
                      <td className="num">{dt(e.registered_at)}</td>
                      <td>
                        {e.status === "ACTIVE" && (
                          <span className="primary-wrap" title={allowed ? "제품 질량·씬 메타 수정, 폐기" : NO_PERMISSION}>
                            <button type="button" className="btn small ghost" disabled={!allowed || editing !== null} onClick={() => setEditing(e.id)}>
                              수정
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="종합분석">
        {!analyses.data ? (
          <Empty>{analyses.error ?? "불러오는 중…"}</Empty>
        ) : analyses.data.length === 0 ? (
          <Empty>아직 종합분석이 없습니다</Empty>
        ) : (
          <div className="table-wrap scroll">
          <table className="table compact" aria-label="종합분석 목록">
            <thead>
              <tr>
                <th className="num">만든 시각</th>
                <th>제목 · 설계 대상</th>
                <th>정규화</th>
                <th className="num">항목</th>
                <th className="num">대표 수</th>
                <th>상태</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {analyses.data.map((a) => {
                const t = a.target_entry_id ? byId.get(a.target_entry_id) : undefined;
                return (
                  <tr key={a.id}>
                    <td className="num">{dt(a.created_at)}</td>
                    <td>
                      {a.title && <div>{a.title}</div>}
                      <span className={a.title ? "small muted" : undefined}>{t ? entryLabel(t) : a.target_entry_id ? a.target_entry_id : "대상 없음(정규화 격자)"}</span>
                    </td>
                    <td>{NORM_LABEL[a.options.normalization ?? "none"]}</td>
                    <td className="num">{a.n_entries}</td>
                    <td className="num">{a.options.n_representative ?? "–"}</td>
                    <td>{a.status === "NONE" ? <span className="muted">–</span> : <JobStatusBadge state={a.status} />}</td>
                    <td>
                      <Link to={`/p/${projectId}/library/analyses/${a.id}`}>열기</Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        )}
      </Card>
      <Card title="버전 비교">
        {!comparisons.data ? (
          <Empty>{comparisons.error ?? "불러오는 중…"}</Empty>
        ) : comparisons.data.length === 0 ? (
          <Empty>아직 버전 비교가 없습니다 — 비드 반영 설계의 검증 낙하를 등록한 뒤 '버전 비교'</Empty>
        ) : (
          <div className="table-wrap scroll">
          <table className="table compact" aria-label="버전 비교 목록">
            <thead>
              <tr>
                <th className="num">만든 시각</th>
                <th>제품 · 버전</th>
                <th className="num">짝 씬</th>
                <th>판정</th>
                <th>상태</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {comparisons.data.map((c) => (
                <tr key={c.id}>
                  <td className="num">{dt(c.created_at)}</td>
                  <td>
                    {c.title && <div>{c.title}</div>}
                    <span className={c.title ? "small muted" : undefined}>
                      {c.model} · {c.base_version} → {c.new_version}
                    </span>
                  </td>
                  <td className="num">{c.n_paired}</td>
                  <td>{c.verdict ? <ComparisonVerdictBadge v={c.verdict} /> : <span className="muted">–</span>}</td>
                  <td>{c.status === "NONE" ? <span className="muted">–</span> : <JobStatusBadge state={c.status} />}</td>
                  <td>
                    <Link to={`/p/${projectId}/library/comparisons/${c.id}`}>열기</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </Card>
    </Shell>
  );
}
