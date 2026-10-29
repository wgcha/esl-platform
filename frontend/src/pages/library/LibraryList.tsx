// ESL 라이브러리(v0.10.0, esl_menu_restructure.md §8): 탭 [ESL 목록 | 강성 평가 스터디 | 비드 최적화 | 종합분석·버전 비교 | 템플릿].
// ESL 목록 = 필터 + 선택 체크(폐기만 불가) + 선택 줄 [내보내기 (n)](주) [강성 평가 스터디 (n)] [비드 최적화 (n)] [종합분석 (n)] [선택 해제].
// 동작별 비활성 사유: 강성 평가·비드 최적화·종합분석 = 부적격(LEGACY·FAIL·판정 불가) 선택 시, 강성 평가·비드 최적화 = 같은 크기 규칙,
// 내보내기 = 최대 개수 초과만. LEGACY 행 = 배지 + [재검증](VALIDATE origin library_revalidate) → 진행 칩 → 결과 안내.
// (이전: v0.7.0 esl_opt_run.md §10.1 선택 줄·모드 열, v0.9.0 esl_bead_doe.md §12.1 비드 DOE 탭 — 이 문서가 대체)
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { p3 } from "../../api/p3";
import { errorText } from "../../api/client";
import { library, type RevalidateResult } from "../../api/library";
import type { EntryOut, EntryStatus, JobState, Me } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { MENU_LIBRARY, Shell } from "../../shell/Shell";
import { Badge, Card, Empty, ErrorLine, Field, JobStatusBadge } from "../../components/ui";
import { usePolling } from "../../lib/usePolling";
import { dt } from "../../lib/format";
import { DROP_LABEL, DROP_TYPES, NORM_LABEL, EligibilityBadge, entryLabel, ineligibleOf, isEligible, legacyBlockText, modelVersions, sceneText, uniq } from "./common";
import { ComparisonVerdictBadge } from "./ComparisonDetail";
import { MODES, MODE_LABEL, optPath, optSettingsCached, sameSize, sizeOf, sizeText } from "../../api/opt";
import { ModeSelect, entryKey, modeText } from "../../components/ModeSelect";
import { EntryEditDialog, editBlock } from "./EntryEdit";
import { OptList } from "../opt/OptList";
import { Templates } from "../opt/Templates";
import { DoeList } from "../doe/DoeList";
import { doePath } from "../../api/doe";
import { ExportDialog } from "../../components/ExportDialog";

export type LibTab = "items" | "study" | "opt" | "analyses" | "templates";
export const LIB_TABS: { id: LibTab; label: string }[] = [
  { id: "items", label: "ESL 목록" },
  { id: "study", label: "강성 평가 스터디" },
  { id: "opt", label: "비드 최적화" },
  { id: "analyses", label: "종합분석·버전 비교" },
  { id: "templates", label: "템플릿" },
];
/** 한 번에 내보낼 수 있는 ESL 수는 서버 설정 library_export.max_entries(GET /version ui.library_export_max_entries)로 받는다.
 *  받기 전·못 받으면 화면 검사는 하지 않고 서버 422 TOO_MANY_ENTRIES 가 최종 판정 */
export async function exportMaxEntries(): Promise<number | null> {
  const v = await p3.version();
  const n = v.ui?.library_export_max_entries;
  return typeof n === "number" && n > 0 ? n : null;
}
export const PROMOTED_TEXT = "현재 기준 PASS — 정상 항목으로 전환";

/** 판정 필터: PASS / LEGACY / FAIL·판정 불가(Q1 A — 셋 다 부적격, 재검증 대상) */
type VerdictFilter = "" | "PASS" | "LEGACY" | "FAIL_UND";

interface Filters {
  model: string;
  mode: string;
  drop_type: string;
  orient: string;
  verdict: VerdictFilter;
  retired: boolean;
}

const EMPTY: Filters = { model: "", mode: "", drop_type: "", orient: "", verdict: "", retired: false };

/** 행 체크: 폐기만 불가(v0.10.0 — 크기·적격 규칙은 동작 버튼에서) */
export function pickBlock(e: EntryOut): string | null {
  return e.status !== "ACTIVE" ? "폐기된 항목" : null;
}

/** 선택 → 동작별 비활성 사유(권한 제외). tol = 크기 허용값(null = 불러오는 중), maxExport = 서버 내보내기 상한(null = 모름 → 서버 판정) */
export function actionBlocks(sel: EntryOut[], tol: number | null, maxExport: number | null = null) {
  const nBad = sel.filter((e) => !isEligible(e)).length;
  const base = sel[0];
  let size: string | null = null;
  if (base) {
    if (!base.size?.L_xi && base.model.inch == null) size = "크기 정보 없음(기준)";
    else if (tol == null) size = "크기 허용값 불러오는 중…";
    else {
      const diff = sel.find((e) => e !== base && (!e.size?.L_xi && e.model.inch == null ? true : !sameSize(sizeOf(e), sizeOf(base), tol)));
      if (diff) size = `크기 다름(기준 ${sizeText(sizeOf(base))})`;
    }
  }
  const legacy = nBad ? legacyBlockText(nBad) : null;
  return {
    nBad,
    export: maxExport != null && sel.length > maxExport ? `최대 ${maxExport}개까지 내보낼 수 있습니다` : null,
    study: legacy ?? size,
    opt: legacy ?? size,
    analysis: legacy,
  };
}

const TERMINAL: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

/** 재검증: 작업 등록 → 2초 폴링 → 끝나면 결과(jobs.result.revalidate)·목록 다시 읽기 */
function useRevalidate(reload: () => Promise<unknown>) {
  const [jobs, setJobs] = useState<Record<string, { job_id: string; state: JobState }>>({});
  const [outcome, setOutcome] = useState<Record<string, RevalidateResult | { outcome: "FAILED"; message: string }>>({});
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const live = Object.entries(jobs).filter(([, j]) => !TERMINAL.includes(j.state));
  useEffect(() => {
    if (!live.length) return;
    const t = setInterval(async () => {
      for (const [eid, j] of live) {
        try {
          const nj = await api.getJob(j.job_id);
          if (nj.state === j.state) continue;
          setJobs((o) => ({ ...o, [eid]: { job_id: nj.id, state: nj.state } }));
          if (TERMINAL.includes(nj.state)) {
            const r = (nj.result?.revalidate ?? null) as RevalidateResult | null;
            if (nj.state === "SUCCEEDED" && r) {
              setOutcome((o) => ({ ...o, [eid]: r }));
              if (r.outcome === "PROMOTED") setToast(PROMOTED_TEXT);
            } else setOutcome((o) => ({ ...o, [eid]: { outcome: "FAILED", message: nj.failure_message ?? nj.failure_code ?? "재검증 실패" } }));
            void reload();
          }
        } catch (e) {
          setError(errorText(e));
        }
      }
    }, 2000);
    return () => clearInterval(t);
  }, [live.map(([k, j]) => `${k}:${j.state}`).join(","), reload]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);
  const start = useCallback(async (eid: string) => {
    setError(null);
    setOutcome((o) => {
      const n = { ...o };
      delete n[eid];
      return n;
    });
    try {
      const j = await library.revalidate(eid);
      setJobs((o) => ({ ...o, [eid]: { job_id: j.id, state: j.state } }));
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  return { jobs, outcome, toast, error, start };
}

/** 재검증 진행·결과 칩 */
function RevalidateCell({ e, allowed, rv }: { e: EntryOut; allowed: boolean; rv: ReturnType<typeof useRevalidate> }) {
  const j = rv.jobs[e.id] ?? e.revalidate_job ?? null;
  const running = !!j && !TERMINAL.includes(j.state);
  if (running) return <span className={`st-chip ${j!.state === "RUNNING" ? "run" : "wait"}`} data-testid="reval-chip">{j!.state === "RUNNING" ? "재검증 중" : "재검증 대기"}</span>;
  const why = !allowed ? NO_PERMISSION : e.revalidate_block ? e.revalidate_block.message || e.revalidate_block.reason : null;
  return (
    <span className="primary-wrap" title={why ?? "현재 판정 기준으로 검증을 다시 실행 — PASS면 정상 항목으로 전환"}>
      <button type="button" className="btn small" disabled={!!why} onClick={() => void rv.start(e.id)}>
        재검증
      </button>
    </span>
  );
}

const keptText = (r: RevalidateResult) => {
  const st = r.status === "UNDETERMINED" ? "판정 불가" : r.status ?? "FAIL";
  const why = r.fail_reasons?.length ? `(${r.fail_reasons.join("·")})` : "";
  return `현재 기준 ${st}${why} — LEGACY로 유지하거나 폐기하세요`;
};

function ItemsTab({ projectId, me, allowed, rows, entries, f, set, filtered, setF, reload, picked, setPicked }: {
  projectId: string;
  me: Me | null;
  allowed: boolean;
  rows: EntryOut[] | null;
  entries: EntryOut[];
  f: Filters;
  set: (k: keyof Filters, v: string | boolean) => void;
  filtered: boolean;
  setF: (fn: (o: Filters) => Filters) => void;
  reload: () => Promise<unknown>;
  picked: string[];
  setPicked: (ids: string[]) => void;
}) {
  const nav = useNavigate();
  const [editing, setEditing] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const rv = useRevalidate(reload);
  const optSt = usePolling(() => optSettingsCached(), 0, []);
  const sizeTol = optSt.data?.size.tol_rel ?? null;
  const maxSt = usePolling(() => exportMaxEntries(), 0, []);
  const byId = new Map(entries.map((e) => [e.id, e]));
  const sel = picked.map((id) => byId.get(id)).filter((e): e is EntryOut => !!e);
  const base = sel[0];
  const same = base ? sel.filter((e) => e.topo_sha256 && e.topo_sha256 === base.topo_sha256).length : 0;
  const blk = actionBlocks(sel, sizeTol, maxSt.data ?? null);
  const perm = allowed ? null : NO_PERMISSION;
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const visibleActive = (rows ?? []).filter((e) => !pickBlock(e)).map((e) => e.id);
  const allOn = visibleActive.length > 0 && visibleActive.every((id) => picked.includes(id));
  const toggleAll = () => setPicked(allOn ? picked.filter((id) => !visibleActive.includes(id)) : [...picked, ...visibleActive.filter((id) => !picked.includes(id))]);
  const editE = editing ? rows?.find((e) => e.id === editing) ?? byId.get(editing) : undefined;
  /** 저장·폐기 후: 목록 다시 읽기. 폐기됐거나 인치가 바뀐 항목은 선택에서 뺀다 */
  const afterSave = (out: EntryOut | null, before: EntryOut) => {
    setEditing(null);
    void reload();
    if (picked.includes(before.id) && (!out || out.status !== "ACTIVE" || out.model.inch !== before.model.inch)) setPicked(picked.filter((x) => x !== before.id));
  };
  const q = picked.join(",");
  const reasons = [...new Set([blk.study, blk.opt, blk.analysis].filter(Boolean))];
  return (
    <Card title="ESL 목록">
      <div className="filters" role="search" aria-label="ESL 필터">
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
        <Field label="모드">
          <select aria-label="모드 필터" value={f.mode} onChange={(e) => set("mode", e.target.value)}>
            <option value="">전체</option>
            {MODES.map((m) => (
              <option key={m} value={m}>
                {MODE_LABEL[m]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="판정">
          <select aria-label="판정" value={f.verdict} onChange={(e) => set("verdict", e.target.value)}>
            <option value="">전체</option>
            <option value="PASS">PASS</option>
            <option value="LEGACY">LEGACY</option>
            <option value="FAIL_UND">FAIL·판정 불가</option>
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
        {rows && <span className="small muted" data-testid="entry-count">{rows.length}개</span>}
      </div>
      {sel.length > 0 && base && (
        <div className="pick-bar" data-testid="pick-bar">
          <span className="small pick-sum">
            선택 {sel.length}개{blk.nBad ? ` · LEGACY ${blk.nBad}` : ""} · 기준 {sizeText(sizeOf(base))} · 같은 모델 {same}/{sel.length}
          </span>
          <span className="pick-actions">
            <span className="primary-wrap" title={perm ?? blk.export ?? undefined}>
              <button type="button" className="btn primary" data-primary="true" disabled={!!(perm ?? blk.export)} onClick={() => setExporting(true)}>
                내보내기 ({sel.length})
              </button>
            </span>
            <span className="primary-wrap" title={perm ?? blk.study ?? undefined}>
              <button type="button" className="btn" disabled={!!(perm ?? blk.study)} onClick={() => nav(`${doePath(projectId)}?entries=${q}`)}>
                강성 평가 스터디 ({sel.length})
              </button>
            </span>
            <span className="primary-wrap" title={perm ?? blk.opt ?? undefined}>
              <button type="button" className="btn" disabled={!!(perm ?? blk.opt)} onClick={() => nav(`${optPath(projectId)}?entries=${q}`)}>
                비드 최적화 ({sel.length})
              </button>
            </span>
            <span className="primary-wrap" title={perm ?? blk.analysis ?? undefined}>
              <button type="button" className="btn" disabled={!!(perm ?? blk.analysis)} onClick={() => nav(`/p/${projectId}/library/analyses/new?entries=${q}`)}>
                종합분석 ({sel.length})
              </button>
            </span>
            <button type="button" className="btn small ghost" onClick={() => setPicked([])}>
              선택 해제
            </button>
          </span>
          {reasons.length > 0 && (
            <span className="small muted pick-why" data-testid="pick-why">
              비활성: {reasons.join(" · ")}
            </span>
          )}
        </div>
      )}
      <ErrorLine text={rv.error} />
      {rv.toast && (
        <div className="info-box" role="status" data-testid="reval-toast">
          {rv.toast}
        </div>
      )}
      {!rows ? (
        <Empty>불러오는 중…</Empty>
      ) : rows.length === 0 ? (
        <Empty>{filtered ? "조건에 맞는 항목이 없습니다" : "아직 등록된 ESL이 없습니다 — ESL 생성 › Case ④ 검증에서 '라이브러리에 등록'"}</Empty>
      ) : (
        <div className="table-wrap scroll lib-table">
          <table className="table" aria-label="라이브러리 항목">
            <thead>
              <tr>
                <th className="chk">
                  <input type="checkbox" aria-label="보이는 항목 모두 선택" checked={allOn} disabled={!visibleActive.length} onChange={toggleAll} />
                </th>
                <th>모델</th>
                <th className="num">인치/크기</th>
                <th>씬</th>
                <th>모드</th>
                <th>판정</th>
                <th>등록</th>
                <th>동작</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const on = picked.includes(e.id);
                const block = pickBlock(e);
                const sameModel = !!base && !!e.topo_sha256 && e.topo_sha256 === base.topo_sha256;
                const bad = e.status === "ACTIVE" && !!ineligibleOf(e);
                const out = rv.outcome[e.id];
                return (
                  <tr key={e.id} className={[e.status === "RETIRED" ? "retired" : "", on ? "sel" : ""].filter(Boolean).join(" ") || undefined} aria-selected={on}>
                    <td className="chk">
                      <input type="checkbox" aria-label={`${entryKey(e)} 선택`} checked={on} disabled={!!block} title={block ?? (picked[0] === e.id ? "기준" : undefined)} onChange={() => toggle(e.id)} />
                    </td>
                    <td>
                      <span title={e.scene.raw ?? undefined}>{e.model.name ?? "–"}</span>
                      {e.model.version && <span className="muted small"> {e.model.version}</span>}
                      {sameModel && (
                        <span className="mm-mark" title="기준과 같은 모델(기존 형상 최적화 가능)">
                          {" "}
                          ⓜ
                        </span>
                      )}
                      {e.status === "RETIRED" && (
                        <>
                          {" "}
                          <Badge kind="warn">폐기</Badge>
                        </>
                      )}
                    </td>
                    <td className="num small">
                      {e.model.inch ?? "–"}
                      {e.size?.L_xi != null && e.size.L_eta != null ? ` ${Math.round(e.size.L_xi)}×${Math.round(e.size.L_eta)}` : ""}
                    </td>
                    <td>
                      {sceneText(e)}
                      {e.scene.orient && <span className="mono small"> {e.scene.orient}</span>}
                      {e.scene.scenario && <span className="muted small"> · {e.scene.scenario}</span>}
                    </td>
                    <td>{e.status === "ACTIVE" ? <ModeSelect e={e} allowed={allowed} onSaved={reload} /> : <span className="small muted">{modeText(e)}</span>}</td>
                    <td title={e.force_reason ? `등록 당시 사유: ${e.force_reason}` : undefined}>
                      <EligibilityBadge e={e} />
                      {out && out.outcome === "KEPT_LEGACY" && (
                        <div className="small warn-text" data-testid="reval-kept">
                          {keptText(out)}{" "}
                          <button type="button" className="btn small ghost" disabled={!!editBlock(me, e)} onClick={() => setEditing(e.id)}>
                            폐기
                          </button>
                        </div>
                      )}
                      {out && out.outcome === "ENTRY_CHANGED" && <div className="small warn-text">항목이 그사이 바뀌어 전환하지 않았습니다</div>}
                      {out && out.outcome === "FAILED" && <div className="small error-text">{out.message}</div>}
                    </td>
                    <td className="small">
                      <span className="nowrap">{e.registered_by_name}</span> <span className="muted nowrap">{dt(e.registered_at)}</span>
                    </td>
                    <td>
                      {e.status === "ACTIVE" && (
                        <span className="inline-actions">
                          <span className="primary-wrap" title={editBlock(me, e) ?? "모델·씬·메모 수정, 폐기"}>
                            <button type="button" className="btn small ghost" disabled={!!editBlock(me, e) || editing !== null} onClick={() => setEditing(e.id)}>
                              수정
                            </button>
                          </span>
                          {bad && <RevalidateCell e={e} allowed={allowed} rv={rv} />}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {editE && (
        <EntryEditDialog
          key={editE.id}
          e={editE}
          onClose={() => setEditing(null)}
          onSaved={afterSave}
          reload={async () => {
            void reload();
            try {
              return await api.libraryEntry(editE.id);
            } catch {
              return null;
            }
          }}
        />
      )}
      {exporting && <ExportDialog projectId={projectId} entries={sel} onClose={() => setExporting(false)} />}
    </Card>
  );
}

function AnalysesTab({ projectId, entries, allowed }: { projectId: string; entries: EntryOut[]; allowed: boolean }) {
  const analyses = usePolling(() => api.analyses(projectId), 10000, [projectId]);
  const comparisons = usePolling(() => api.comparisons(projectId), 10000, [projectId]);
  const byId = new Map(entries.map((e) => [e.id, e]));
  const noVersions = entries.length > 0 && !modelVersions(entries).some((m) => m.versions.length > 1);
  return (
    <>
      <Card title="종합분석">
        {!analyses.data ? (
          <Empty>{analyses.error ?? "불러오는 중…"}</Empty>
        ) : analyses.data.length === 0 ? (
          <Empty>아직 종합분석이 없습니다 — ESL 목록에서 ESL을 고르고 '종합분석'</Empty>
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
      <section id="comparisons" className="anchor-section">
        <Card
          title="버전 비교"
          right={
            allowed ? (
              <Link className="btn small" to={`/p/${projectId}/library/comparisons/new`} title={noVersions ? "버전이 2개 이상인 제품이 아직 없습니다" : "비드 반영 설계의 검증 낙하를 이전 버전과 비교(수렴 판정)"}>
                버전 비교 만들기
              </Link>
            ) : undefined
          }
        >
          {!comparisons.data ? (
            <Empty>{comparisons.error ?? "불러오는 중…"}</Empty>
          ) : comparisons.data.length === 0 ? (
            <Empty>아직 버전 비교가 없습니다 — 비드 반영 설계의 검증 낙하를 등록한 뒤 '버전 비교 만들기'</Empty>
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
      </section>
    </>
  );
}

/** 판정 필터 → 서버 verdict(FAIL·판정 불가는 서버 값이 둘이라 받은 뒤 거른다) */
const serverVerdict = (v: VerdictFilter) => (v === "PASS" || v === "LEGACY" ? v : undefined);
const matchVerdict = (e: EntryOut, v: VerdictFilter) => {
  if (!v) return true;
  const r = ineligibleOf(e);
  return v === "PASS" ? !r : v === "LEGACY" ? r === "LEGACY" : r === "FAIL" || r === "UNDETERMINED";
};

export function LibraryList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const [sp, setSp] = useSearchParams();
  const tab = (LIB_TABS.some((t) => t.id === sp.get("tab")) ? sp.get("tab") : "items") as LibTab;
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const [f, setF] = useState<Filters>(EMPTY);
  const [picked, setPicked] = useState<string[]>([]);
  const status: EntryStatus | undefined = f.retired ? undefined : "ACTIVE";
  const all = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const rows = usePolling(
    () =>
      api.libraryEntries({
        project_id: projectId,
        model: f.model || undefined,
        drop_type: f.drop_type || undefined,
        orient: f.orient || undefined,
        verdict: serverVerdict(f.verdict),
        mode: f.mode || undefined,
        status,
      }),
    0,
    [projectId, f.model, f.drop_type, f.orient, f.verdict, f.mode, status],
  );
  const entries = all.data ?? [];
  const set = (k: keyof Filters, v: string | boolean) => setF((o) => ({ ...o, [k]: v }));
  const filtered = Object.entries(f).some(([k, v]) => (k === "retired" ? false : !!v));
  const setTab = (t: LibTab) => {
    const q = new URLSearchParams(sp);
    if (t === "items") q.delete("tab");
    else q.set("tab", t);
    setSp(q, { replace: true });
  };
  const rowsReload = rows.reload;
  const allReload = all.reload;
  const reload = useCallback(() => Promise.all([rowsReload(), allReload()]), [rowsReload, allReload]);
  const tabLabel = LIB_TABS.find((t) => t.id === tab)?.label ?? "";
  // 폐기된 항목은 선택에서 뺀다
  useEffect(() => {
    if (!all.data) return;
    const live = new Set(all.data.filter((e) => e.status === "ACTIVE").map((e) => e.id));
    if (picked.some((id) => !live.has(id))) setPicked(picked.filter((id) => live.has(id)));
  }, [all.data]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: MENU_LIBRARY, to: `/p/${projectId}/library` }, { label: tabLabel }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">{MENU_LIBRARY}</h1>
        <span className="muted small">검증 PASS 한 ESL 하중을 모아 내보내기·강성 평가·비드 최적화·종합분석에 씁니다</span>
      </div>
      <div className="tabs" role="tablist" aria-label="라이브러리 탭">
        {LIB_TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={`tab${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <ErrorLine text={rows.error ?? all.error} />
      {tab === "items" && (
        <ItemsTab
          projectId={projectId}
          me={me}
          allowed={allowed}
          rows={rows.data ? rows.data.filter((e) => matchVerdict(e, f.verdict)) : null}
          entries={entries}
          f={f}
          set={set}
          filtered={filtered}
          setF={setF}
          reload={reload}
          picked={picked}
          setPicked={setPicked}
        />
      )}
      {tab === "analyses" && <AnalysesTab projectId={projectId} entries={entries} allowed={allowed} />}
      {tab === "opt" && <OptList projectId={projectId} />}
      {tab === "templates" && <Templates projectId={projectId} />}
      {tab === "study" && <DoeList projectId={projectId} />}
    </Shell>
  );
}
