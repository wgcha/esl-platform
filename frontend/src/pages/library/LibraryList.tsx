// 라이브러리 목록(계약 §11·§12 UI): 항목 표 + 필터 + 메타 수정(인라인 최소) + 폐기. 주 버튼 = "종합분석 만들기",
// 보조 진입 "버전 비교"(설계 버전 비교 만들기) + 비교 목록.
// v0.7.0(esl_opt_run.md §10.1): 탭 [항목 | 종합분석 | 버전 비교 | 최적화 실행 | 템플릿], 항목 행 선택(같은 크기만, 첫 행 = 기준)·크기·ⓜ(같은 모델)·
// 모드 열(드롭다운 저장) → [선택한 ESL로 비드 최적화 (n)]. 템플릿 탭은 자기 주 버튼(템플릿 등록)을 갖고, 그때 '종합분석 만들기'는 숨김.
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
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
import { MODES, MODE_LABEL, optPath, optSettingsCached, sameSize, sizeOf, sizeText } from "../../api/opt";
import { ModeSelect, entryKey, modeText } from "../../components/ModeSelect";
import { OptList } from "../opt/OptList";
import { Templates } from "../opt/Templates";

export type LibTab = "items" | "analyses" | "comparisons" | "opt" | "templates";
const TABS: { id: LibTab; label: string }[] = [
  { id: "items", label: "항목" },
  { id: "analyses", label: "종합분석" },
  { id: "comparisons", label: "버전 비교" },
  { id: "opt", label: "최적화 실행" },
  { id: "templates", label: "템플릿" },
];

interface Filters {
  model: string;
  mode: string;
  drop_type: string;
  orient: string;
  verdict: string;
  retired: boolean;
}

const EMPTY: Filters = { model: "", mode: "", drop_type: "", orient: "", verdict: "", retired: false };
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
      <td />
      <td>{e.model.name}</td>
      <td className="num">{e.model.inch ?? "–"}</td>
      <td className="num small">{sizeText({ ...sizeOf(e), inch: null })}</td>
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
      <td className="small">{modeText(e)}</td>
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

/** 행 선택 규칙: 첫 선택 = 기준, 같은 크기(인치 + 치수 ± tol — 서버 /opt/settings size.tol_rel)만 더 고를 수 있다.
 * tol = null(설정 불러오는 중)이면 기준 외 행은 잠시 비활성. 반환 = 비활성 사유 또는 null */
export function pickBlock(e: EntryOut, base: EntryOut | undefined, tol: number | null): string | null {
  if (e.status !== "ACTIVE") return "폐기된 항목";
  if (!e.size?.L_xi && e.model.inch == null) return "크기 정보 없음";
  if (base && base.id !== e.id) {
    if (tol == null) return "크기 허용값 불러오는 중…";
    if (!sameSize(sizeOf(e), sizeOf(base), tol)) return `크기 다름(기준 ${sizeText(sizeOf(base))})`;
  }
  return null;
}

function ItemsTab({ projectId, allowed, rows, entries, f, set, filtered, setF, reload, picked, setPicked }: {
  projectId: string;
  allowed: boolean;
  rows: ReturnType<typeof usePolling<EntryOut[]>>;
  entries: EntryOut[];
  f: Filters;
  set: (k: keyof Filters, v: string | boolean) => void;
  filtered: boolean;
  setF: (fn: (o: Filters) => Filters) => void;
  reload: () => void;
  picked: string[];
  setPicked: (ids: string[]) => void;
}) {
  const nav = useNavigate();
  const [editing, setEditing] = useState<string | null>(null);
  const optSt = usePolling(() => optSettingsCached(), 0, []);
  const sizeTol = optSt.data?.size.tol_rel ?? null;
  const byId = new Map(entries.map((e) => [e.id, e]));
  const base = picked.length ? byId.get(picked[0]) : undefined;
  const same = base ? picked.filter((id) => byId.get(id)?.topo_sha256 && byId.get(id)?.topo_sha256 === base.topo_sha256).length : 0;
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  return (
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
      {picked.length > 0 && base && (
        <div className="pick-bar" data-testid="pick-bar">
          <span className="small">
            선택 {picked.length}개 · 기준 {sizeText(sizeOf(base))} · 같은 모델 {same}/{picked.length}
          </span>
          <span className="primary-wrap" title={allowed ? undefined : NO_PERMISSION}>
            <button type="button" className="btn" disabled={!allowed} onClick={() => nav(`${optPath(projectId)}?entries=${picked.join(",")}`)}>
              선택한 ESL로 비드 최적화 ({picked.length})
            </button>
          </span>
          <button type="button" className="btn small ghost" onClick={() => setPicked([])}>
            선택 해제
          </button>
        </div>
      )}
      {!rows.data ? (
        <Empty>{rows.error ? "" : "불러오는 중…"}</Empty>
      ) : rows.data.length === 0 ? (
        <Empty>{filtered ? "조건에 맞는 항목이 없습니다" : "아직 등록된 항목이 없습니다 — Case ⑤ 검증 결과에서 '라이브러리 등록'"}</Empty>
      ) : (
        <div className="table-wrap scroll">
          <table className="table" aria-label="라이브러리 항목">
            <thead>
              <tr>
                <th className="chk" title="비드 최적화에 넣을 ESL(첫 선택 = 기준, 같은 크기만)">선택</th>
                <th>모델</th>
                <th className="num">인치</th>
                <th className="num">크기(mm)</th>
                <th>씬 유형</th>
                <th>orient</th>
                <th>모드</th>
                <th>판정</th>
                <th className="num">최대오차</th>
                <th className="num">제품 질량</th>
                <th className="num">등록일</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((e) => {
                if (editing === e.id)
                  return (
                    <EditRow
                      key={e.id}
                      e={e}
                      onDone={(changed) => {
                        setEditing(null);
                        if (changed) reload();
                      }}
                    />
                  );
                const on = picked.includes(e.id);
                const block = on ? null : pickBlock(e, base, sizeTol);
                const sameModel = !!base && !!e.topo_sha256 && e.topo_sha256 === base.topo_sha256;
                return (
                  <tr key={e.id} className={[e.status === "RETIRED" ? "retired" : "", on ? "sel" : "", block && base ? "dim-row" : ""].filter(Boolean).join(" ") || undefined} aria-selected={on}>
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
                    <td className="num">{e.model.inch ?? "–"}</td>
                    <td className="num small">{e.size?.L_xi != null && e.size.L_eta != null ? `${Math.round(e.size.L_xi)}×${Math.round(e.size.L_eta)}` : "–"}</td>
                    <td>
                      {sceneText(e)}
                      {e.scene.scenario && <span className="muted small"> · {e.scene.scenario}</span>}
                    </td>
                    <td className="mono">{e.scene.orient ?? "–"}</td>
                    <td>{e.status === "ACTIVE" ? <ModeSelect e={e} allowed={allowed} onSaved={reload} /> : <span className="small muted">{modeText(e)}</span>}</td>
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
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function LibraryList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const tab = (TABS.some((t) => t.id === sp.get("tab")) ? sp.get("tab") : "items") as LibTab;
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
        verdict: f.verdict || undefined,
        mode: f.mode || undefined,
        status,
      }),
    0,
    [projectId, f.model, f.drop_type, f.orient, f.verdict, f.mode, status],
  );
  const analyses = usePolling(() => api.analyses(projectId), 10000, [projectId]);
  const comparisons = usePolling(() => api.comparisons(projectId), 10000, [projectId]);
  const entries = all.data ?? [];
  const set = (k: keyof Filters, v: string | boolean) => setF((o) => ({ ...o, [k]: v }));
  const filtered = Object.entries(f).some(([k, v]) => (k === "retired" ? false : !!v));
  const byId = new Map(entries.map((e) => [e.id, e]));
  const setTab = (t: LibTab) => {
    const q = new URLSearchParams(sp);
    if (t === "items") q.delete("tab");
    else q.set("tab", t);
    setSp(q, { replace: true });
  };

  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "라이브러리" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">라이브러리</h1>
        <span className="muted small">검증한 ESL 하중을 모델·낙하 씬별로 모아 종합분석·비드 최적화에 씁니다</span>
        <span className="spacer" />
        <Link
          className="btn"
          to={`/p/${projectId}/library/comparisons/new`}
          title={all.data && !modelVersions(entries).some((m) => m.versions.length > 1) ? "버전이 2개 이상인 제품이 아직 없습니다" : "비드 반영 설계의 검증 낙하를 이전 버전과 비교(수렴 판정)"}
        >
          버전 비교
        </Link>
        {tab !== "templates" && (
          <PrimaryButton
            label="종합분석 만들기"
            onClick={() => nav(`/p/${projectId}/library/analyses/new`)}
            disabledReason={!allowed ? NO_PERMISSION : all.data && !entries.some((e) => e.status === "ACTIVE") ? "등록된 항목이 없습니다 — ⑤ 검증에서 '라이브러리 등록'" : null}
          />
        )}
      </div>
      <div className="tabs" role="tablist" aria-label="라이브러리 탭">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={`tab${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <ErrorLine text={rows.error ?? all.error} />
      {tab === "items" && (
        <ItemsTab
          projectId={projectId}
          allowed={allowed}
          rows={rows}
          entries={entries}
          f={f}
          set={set}
          filtered={filtered}
          setF={setF}
          reload={() => void Promise.all([rows.reload(), all.reload()])}
          picked={picked}
          setPicked={setPicked}
        />
      )}
      {tab === "analyses" && (
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
      )}
      {tab === "comparisons" && (
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
      )}
      {tab === "opt" && <OptList projectId={projectId} />}
      {tab === "templates" && <Templates projectId={projectId} />}
    </Shell>
  );
}

