// 새 비드 최적화(esl_opt_run.md §3·§10.3): 탭 [기존 형상(S1) | 템플릿(S2)] · ① 대상 · ② 비드 금지 영역 · ③ ESL · ④ 하중 선정 전략(ⓘ) ·
// ⑤ 비드 치수·제목. 주 버튼 = "최적화 실행"(POST /opt/runs → OPT_RUN 작업) → 상세. 비활성 사유는 툴팁.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { errorText } from "../../api/client";
import { MISMATCH_REASON, MODES, MODE_LABEL, SCENARIO_LABEL, opt, optPath, sameSize, sizeOf, sizeText, templateMismatch } from "../../api/opt";
import type { DeformMode, EntryOut, OptPid, OptScenario, OptSettingsOut, S1CheckOut, TemplateOut } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Card, Empty, ErrorLine, Field, PrimaryButton, Stat } from "../../components/ui";
import { KeepoutEditor, type KeepoutValue } from "../../components/KeepoutPlan";
import { LoadStrategy, kProblem, type StrategyValue } from "../../components/LoadStrategy";
import { MethodInfo } from "../../components/MethodInfo";
import { ModeSelect, entryKey } from "../../components/ModeSelect";
import { usePolling } from "../../lib/usePolling";
import { libPath, sceneText } from "../library/common";

export interface BeadForm {
  angle: string;
  width: string;
  height: string;
}

/** 비드 치수 검사(경사 0~90°, 폭·높이 > 0) */
export function beadProblem(b: BeadForm): string | null {
  const a = Number(b.angle);
  const w = Number(b.width);
  const h = Number(b.height);
  if (!(b.angle.trim() && a > 0 && a < 90)) return "비드 경사는 0~90° 사이입니다";
  if (!(b.width.trim() && w > 0)) return "비드 폭은 0보다 커야 합니다";
  if (!(b.height.trim() && h > 0)) return "비드 높이는 0보다 커야 합니다";
  return null;
}

const supportsText = (s: { node_id: number; dof: string }[]) => s.map((x) => `${x.node_id}(${x.dof})`).join(" · ");

function PidTable({ pids, nondesign, onToggle }: { pids: OptPid[]; nondesign: Set<number>; onToggle: (pid: number) => void }) {
  return (
    <table className="table compact" aria-label="PID 설계 영역">
      <thead>
        <tr>
          <th>설계</th>
          <th className="num">PID</th>
          <th>이름</th>
          <th className="num">요소</th>
          <th className="num">두께</th>
        </tr>
      </thead>
      <tbody>
        {pids.map((p) => (
          <tr key={p.pid}>
            <td>
              <input type="checkbox" aria-label={`PID ${p.pid} 설계`} checked={!nondesign.has(p.pid)} onChange={() => onToggle(p.pid)} />
            </td>
            <td className="num">{p.pid}</td>
            <td>{p.title}</td>
            <td className="num">{p.n_elems.toLocaleString()}</td>
            <td className="num">{p.thickness != null ? `${p.thickness} mm` : "–"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TargetS1({ s1, error, nondesign, onToggle }: { s1: S1CheckOut | null; error: string | null; nondesign: Set<number>; onToggle: (pid: number) => void }) {
  if (error) return <ErrorLine text={error} />;
  if (!s1) return <Empty>모델 확인 중…</Empty>;
  const b = s1.base;
  return (
    <div className="target-grid">
      <div className="stats">
        <Stat label="기준 Case" value={b.case_title ?? b.case_id} sub={b.rad_file_name ?? undefined} />
        <Stat label="대상 파트" value={b.part_title ?? "–"} />
        <Stat label="노드 · 요소" value={`${b.n_nodes?.toLocaleString() ?? "?"} · ${b.n_elems?.toLocaleString() ?? "?"}`} />
        <Stat label="3-2-1 지지" value={<span className="mono small">{supportsText(b.supports ?? [])}</span>} sub="기준 ESL 과 같음(표시만)" />
      </div>
      <PidTable pids={b.pids ?? []} nondesign={nondesign} onToggle={onToggle} />
    </div>
  );
}

function TargetS2({ templates, tid, setTid, sizes, plateTol, nondesign, onToggle, projectId }: {
  templates: TemplateOut[] | null;
  tid: string;
  setTid: (id: string) => void;
  sizes: ReturnType<typeof sizeOf>[];
  plateTol: number;
  nondesign: Set<number>;
  onToggle: (pid: number) => void;
  projectId: string;
}) {
  if (!templates) return <Empty>템플릿 불러오는 중…</Empty>;
  if (!templates.length)
    return (
      <Empty>
        등록된 템플릿이 없습니다 — <Link to={`${libPath(projectId)}?tab=templates`}>라이브러리 › 템플릿</Link>에서 등록하세요
      </Empty>
    );
  const t = templates.find((x) => x.id === tid);
  const bad = t ? templateMismatch(t, sizes, plateTol) : null;
  return (
    <div className="target-grid">
      <div>
        <Field label="템플릿">
          <select aria-label="템플릿" value={tid} onChange={(e) => setTid(e.target.value)}>
            <option value="">고르세요</option>
            {templates.map((x) => {
              const why = templateMismatch(x, sizes, plateTol);
              return (
                <option key={x.id} value={x.id} disabled={!!why}>
                  {x.title} · {x.inch ? `${x.inch}형 ` : ""}
                  {Math.round(x.L_xi)}×{Math.round(x.L_eta)}
                  {why ? ` — ${why}` : ""}
                </option>
              );
            })}
          </select>
        </Field>
        {t && (
          <div className="stats">
            <Stat label="크기" value={`${Math.round(t.L_xi)}×${Math.round(t.L_eta)} mm`} sub={bad ?? "ESL 과 크기 맞음"} tone={bad ? "bad" : undefined} />
            <Stat label="형식 · 파일" value={t.format} sub={t.file_name} />
            <Stat label="노드 · 요소" value={`${t.n_nodes.toLocaleString()} · ${t.n_elems.toLocaleString()}`} />
            <Stat label="3-2-1 지지" value="자동" sub="서버가 템플릿에서 고름" />
          </div>
        )}
        {t?.quality_warnings?.length ? (
          <ul className="reasons small warn-text">
            {t.quality_warnings.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {t && <PidTable pids={t.pids} nondesign={nondesign} onToggle={onToggle} />}
    </div>
  );
}

export function OptNew() {
  const { projectId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const { me, projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const ids = useMemo(() => (sp.get("entries") ?? "").split(",").filter(Boolean), [sp]);
  const idsKey = ids.join(",");
  const analysisId = sp.get("analysis");
  const settings = usePolling(() => opt.settings(), 0, []);
  const all = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const s1 = usePolling(() => (ids.length ? opt.s1Check({ project_id: projectId, entry_ids: ids }) : Promise.resolve(null)), 0, [projectId, idsKey]);
  const templates = usePolling(() => opt.templates({ status: "ACTIVE" }), 0, []);
  const st: OptSettingsOut | null = settings.data;

  const [scenario, setScenario] = useState<OptScenario | null>((sp.get("tab") as OptScenario | null) ?? null);
  const [tid, setTid] = useState("");
  const [nondesign, setNondesign] = useState<Set<number>>(new Set());
  const [keepout, setKeepout] = useState<KeepoutValue>({ rects: [], auto: { hole: true, edge: true } });
  const [koProblem, setKoProblem] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyValue | null>(null);
  const [bead, setBead] = useState<BeadForm | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onKoProblem = useCallback((p: string | null) => setKoProblem(p), []);

  // 서버 설정값으로 기본값 채우기(전략 A·목표 절대·k 5, 비드 45°·60·10 mm)
  useEffect(() => {
    if (!st) return;
    setStrategy((s) => s ?? { strategy: st.loads.default_strategy, k: String(st.loads.default_k), norm: st.loads.default_objective_norm });
    setBead((b) => b ?? { angle: String(st.bead_defaults.angle), width: String(st.bead_defaults.min_width), height: String(st.bead_defaults.height) });
  }, [st]);

  const byId = new Map((all.data ?? []).map((e) => [e.id, e]));
  const sel = ids.map((id) => byId.get(id)).filter((e): e is EntryOut => !!e);
  const s1Rows = new Map((s1.data?.entries ?? []).map((r) => [r.entry_id, r]));
  const mismatched = s1.data ? s1.data.entries.filter((r) => !r.same_model).map((r) => r.entry_id) : [];

  // 기본 탭: 모두 같은 모델이면 기존 형상(S1), 아니면 템플릿(S2)
  useEffect(() => {
    if (scenario || !s1.data) return;
    setScenario(s1.data.entries.every((r) => r.same_model) ? "S1" : "S2");
  }, [s1.data, scenario]);
  useEffect(() => {
    if (scenario || !s1.error) return;
    setScenario("S2");
  }, [s1.error, scenario]);

  const sizes = sel.map(sizeOf);
  const base = sizes[0];
  // 크기 허용은 서버 /opt/settings 값만(로드 전에는 크기 판정 보류 — 표에 "확인 중")
  const sizeBad = st ? sel.filter((e, i) => i > 0 && !sameSize(sizeOf(e), base, st.size.tol_rel)).map((e) => e.id) : [];
  const tpls = templates.data ?? null;
  const tpl = tpls?.find((t) => t.id === tid);
  // 템플릿 기본 = 크기 맞는 첫 템플릿
  useEffect(() => {
    if (scenario !== "S2" || tid || !tpls || !st || !sizes.length) return;
    const ok = tpls.find((t) => !templateMismatch(t, sizes, st.size.plate_tol_rel));
    if (ok) setTid(ok.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, tpls, st, idsKey, all.data]);
  // 대상이 바뀌면 설계 PID 초기화
  const targetKey = scenario === "S1" ? `S1:${s1.data?.base.topo_sha256 ?? ""}` : `S2:${tid}`;
  useEffect(() => setNondesign(new Set()), [targetKey]);

  const counts = Object.fromEntries(MODES.map((m) => [m, sel.filter((e) => e.deform_mode?.effective === m).length])) as Record<DeformMode, number>;
  const modeSummary = MODES.filter((m) => counts[m]).map((m) => `${MODE_LABEL[m]} ${counts[m]}`).join(" · ");

  const setIds = (next: string[]) => {
    const q = new URLSearchParams(sp);
    q.set("entries", next.join(","));
    if (scenario) q.set("tab", scenario);
    setSp(q, { replace: true });
  };
  const toggle = (pid: number) =>
    setNondesign((s) => {
      const n = new Set(s);
      if (n.has(pid)) n.delete(pid);
      else n.add(pid);
      return n;
    });
  const pids = scenario === "S1" ? s1.data?.base.pids ?? [] : tpl?.pids ?? [];

  const keepoutSrc =
    scenario === "S1"
      ? s1.data && { plan: { entry_id: s1.data.base.entry_id }, set: { topo: s1.data.base.topo_sha256 ?? undefined }, saveLabel: "이 모델에 저장" }
      : tpl && { plan: { template_id: tpl.id }, set: { template_id: tpl.id }, saveLabel: "이 템플릿에 저장" };

  function reason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !all.data || !strategy || !bead) return "불러오는 중…";
    if (!st.enabled) return "비드 최적화가 서버에 설정되지 않았습니다(관리자 문의)";
    if (!st.solver_ready) return "서버 OptiStruct 경로가 설정되지 않았습니다(관리자 문의)";
    if (!ids.length) return "ESL 을 고르세요 — 라이브러리 항목에서 체크한 뒤 '선택한 ESL로 비드 최적화'";
    if (sel.length !== ids.length) return "라이브러리에 없는 항목이 있습니다";
    if (ids.length > st.max_entries) return `ESL 은 최대 ${st.max_entries}개입니다`;
    if (scenario === "S1") {
      if (s1.error) return s1.error;
      if (!s1.data) return "모델 확인 중…";
      if (mismatched.length) return `다른 모델 ESL ${mismatched.length}개 — '다른 모델 빼기' 또는 템플릿 최적화`;
    } else {
      if (sizeBad.length) return `크기가 다른 ESL ${sizeBad.length}개 — 같은 크기만 고르세요`;
      if (!tpl) return "템플릿을 고르세요";
      const why = templateMismatch(tpl, sizes, st.size.plate_tol_rel);
      if (why) return `템플릿 크기 불일치: ${why}`;
    }
    if (pids.length && pids.every((p) => nondesign.has(p.pid))) return "설계 PID 가 없습니다 — 하나 이상 체크하세요";
    if (koProblem) return koProblem;
    const kb = kProblem(strategy, st.loads.max_cases);
    if (kb) return kb;
    if (strategy.strategy === "B" && !MODES.some((m) => counts[m])) return "전략 B: 모드가 분류된 ESL 이 없습니다";
    return beadProblem(bead);
  }

  async function run() {
    if (!strategy || !bead || !scenario) return;
    setBusy(true);
    setError(null);
    try {
      const r = await opt.createRun({
        project_id: projectId,
        scenario,
        title: title.trim() || null,
        entry_ids: ids,
        analysis_id: analysisId,
        template_id: scenario === "S2" ? tid : null,
        design: { nondesign_pids: [...nondesign].sort((a, b) => a - b), bead: { angle: Number(bead.angle), min_width: Number(bead.width), height: Number(bead.height) }, keepout },
        options: { load_strategy: strategy.strategy, objective_norm: strategy.norm, ...(strategy.strategy === "C" ? { k: Number(strategy.k) } : {}) },
      });
      nav(optPath(projectId, r.id));
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "라이브러리", to: libPath(projectId) }, { label: "새 비드 최적화" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">새 비드 최적화</h1>
        <div className="tabs" role="tablist" aria-label="시나리오">
          {(["S1", "S2"] as OptScenario[]).map((s) => (
            <button key={s} type="button" role="tab" aria-selected={scenario === s} className={`tab${scenario === s ? " on" : ""}`} onClick={() => setScenario(s)}>
              {SCENARIO_LABEL[s]}({s})
            </button>
          ))}
        </div>
        <span className="spacer" />
        <PrimaryButton label="최적화 실행" onClick={run} disabledReason={reason()} busy={busy} />
      </div>
      {st && !st.solver_ready && <div className="warn-box" role="alert">서버 OptiStruct 경로가 설정되지 않았습니다(관리자 문의){st.solver_reason ? ` — ${st.solver_reason}` : ""}</div>}
      <ErrorLine text={error ?? settings.error ?? all.error} />
      <Card title={`① 대상 — ${scenario === "S2" ? "템플릿" : "기존 rad 형상"}`}>
        {scenario === "S2" ? (
          st ? (
            <TargetS2 templates={tpls} tid={tid} setTid={setTid} sizes={sizes} plateTol={st.size.plate_tol_rel} nondesign={nondesign} onToggle={toggle} projectId={projectId} />
          ) : (
            <Empty>설정 불러오는 중…</Empty>
          )
        ) : (
          <TargetS1 s1={s1.data} error={s1.error} nondesign={nondesign} onToggle={toggle} />
        )}
      </Card>
      <Card title="② 비드 금지 영역">
        {keepoutSrc && st ? (
          <KeepoutEditor src={keepoutSrc} value={keepout} onChange={setKeepout} auto={st.keepout_auto} maxRects={st.max_rects} allowed={allowed} onProblem={onKoProblem} />
        ) : (
          <Empty>{scenario === "S2" ? "템플릿을 고르면 평면도가 보입니다" : "대상 확인 중…"}</Empty>
        )}
      </Card>
      <div className="opt-grid">
        <Card title={`③ ESL (${sel.length})${modeSummary ? ` · 모드: ${modeSummary}` : ""}`}>
          {!all.data ? (
            <Empty>불러오는 중…</Empty>
          ) : !ids.length ? (
            <Empty>
              선택한 ESL 이 없습니다 — <Link to={libPath(projectId)}>라이브러리</Link>에서 체크하세요
            </Empty>
          ) : (
            <>
              <div className="table-wrap scroll">
                <table className="table compact" aria-label="선택한 ESL">
                  <thead>
                    <tr>
                      <th>모델</th>
                      <th>씬</th>
                      <th>크기</th>
                      <th>모드</th>
                      <th>{scenario === "S1" ? "같은 모델" : "크기"}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {sel.map((e, i) => {
                      const m = s1Rows.get(e.id);
                      const bad = scenario === "S1" ? m && !m.same_model : sizeBad.includes(e.id);
                      return (
                        <tr key={e.id} className={bad ? "bad-row" : undefined}>
                          <td>
                            {e.model.name} <span className="muted small">{e.model.version}</span>
                            {i === 0 && <span className="small muted"> · 기준</span>}
                          </td>
                          <td>
                            {e.scene.seq ?? ""} {sceneText(e)} <span className="mono small">{e.scene.orient}</span>
                          </td>
                          <td className="small">{sizeText(sizeOf(e))}</td>
                          <td>
                            <ModeSelect e={e} allowed={allowed} onSaved={() => void all.reload()} />
                          </td>
                          <td>
                            {scenario === "S1" ? (
                              !m ? (
                                <span className="muted small">확인 중</span>
                              ) : m.same_model ? (
                                <span className="ok-text">같은 모델 ✓</span>
                              ) : (
                                <span className="error-text" title={m.reason ? MISMATCH_REASON[m.reason] ?? m.reason : undefined}>
                                  다른 모델 ✗
                                </span>
                              )
                            ) : !st ? (
                              <span className="muted small">확인 중</span>
                            ) : bad ? (
                              <span className="error-text">크기 다름 ✗</span>
                            ) : (
                              <span className="ok-text">✓</span>
                            )}
                          </td>
                          <td>
                            <button type="button" className="btn small ghost" aria-label={`${entryKey(e)} 빼기`} onClick={() => setIds(ids.filter((x) => x !== e.id))}>
                              빼기
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {scenario === "S1" && mismatched.length > 0 && (
                <div className="inline-actions">
                  <button type="button" className="btn small" onClick={() => setIds(ids.filter((x) => !mismatched.includes(x)))}>
                    다른 모델 빼기
                  </button>
                  <span className="small muted">
                    다른 모델 ESL 은 같은 크기면{" "}
                    <button type="button" className="link small" onClick={() => setScenario("S2")}>
                      템플릿 최적화
                    </button>
                    로 함께 쓸 수 있습니다
                  </span>
                </div>
              )}
            </>
          )}
        </Card>
        <Card title="④ 하중 선정 전략" right={<MethodInfo src={st?.method_sources} strategy={strategy?.strategy} norm={strategy?.norm} />}>
          {st && strategy ? <LoadStrategy value={strategy} onChange={setStrategy} settings={st} modeCounts={counts} /> : <Empty>불러오는 중…</Empty>}
        </Card>
      </div>
      <Card title="⑤ 비드 치수 · 제목">
        {bead ? (
          <div className="form-grid bead-form">
            <Field label="경사 (°)">
              <input type="number" aria-label="비드 경사 (°)" min={1} max={89} value={bead.angle} onChange={(e) => setBead({ ...bead, angle: e.target.value })} />
            </Field>
            <Field label="폭 (mm)">
              <input type="number" aria-label="비드 폭 (mm)" min={1} value={bead.width} onChange={(e) => setBead({ ...bead, width: e.target.value })} />
            </Field>
            <Field label="높이 (mm)">
              <input type="number" aria-label="비드 높이 (mm)" min={0.1} step="0.5" value={bead.height} onChange={(e) => setBead({ ...bead, height: e.target.value })} />
            </Field>
            <Field label="제목 (선택)">
              <input aria-label="제목" maxLength={200} value={title} placeholder="예: 75형 강건 비드 1차" onChange={(e) => setTitle(e.target.value)} />
            </Field>
            {beadProblem(bead) && <div className="small error-text">{beadProblem(bead)}</div>}
          </div>
        ) : (
          <Empty>불러오는 중…</Empty>
        )}
        <div className="small muted">비드 방향 = 요소 법선(+n) 쪽, 높이 0~최대. 결과는 라이브러리에 넣지 않고 '최적화 실행' 목록에 남습니다.</div>
      </Card>
    </Shell>
  );
}

