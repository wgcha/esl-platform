// 비드 DOE 새 연구·상세 한 화면(esl_bead_doe.md §3·§12.2). 시나리오 라디오 [① 같은 모델 ② 다른 모델(메시 있음) ③ 다른 모델(STEP만)]
// (자동 판별 + 표시), 주 버튼 1개 = 단계별 [입력 준비 | 미리보기 | DOE 실행 | 보고서 보기](비활성 사유 툴팁).
// 카드: ① 입력 · ② 비드·변수 + DOE 방식 · ③ 평면도(비드 번호·경계 경고) · ④ 미리보기 격자 · ⑤ 결과(순위·민감도·3D 비교·받기).
// 솔버 선택 칸 없음(선형만, 확정 6). 설정값은 모두 GET /doe/settings.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { ApiError, downloadFile, errorText, request } from "../../api/client";
import {
  PHASE_NAME, SCENARIOS, SCENARIO_NAME, SCENARIO_NO, autoScenario, buildSpec, defaultRows, doe, doeBlockedReason, doePath, scenarioBlocked, warnText,
  type ParamRow, type SpecForm,
} from "../../api/doe";
import { STEP_LABEL } from "../../api/history";
import type { DoeCheckOut, DoeMatrixOut, DoeResultOut, DoeScenario, DoeSettingsOut, DoeSpec, DoeStudyOut, EntryOut, JobOut, View3dOut } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Badge, Card, Empty, ErrorLine, PrimaryButton } from "../../components/ui";
import { DoeInputs, DoeInputsSummary, EMPTY_INPUTS, propsProblem, type InputsForm } from "../../components/DoeInputs";
import { DoeMethodInfo, DoeParamTable, DoeSpecRow } from "../../components/DoeParamTable";
import { DoeThumbGrid, previewSummary } from "../../components/DoeThumbGrid";
import { BoundaryLegend, BoundaryPlan } from "../../components/BoundaryPlan";
import { DoeRanking } from "../../components/DoeRanking";
import { Sensitivity } from "../../components/Sensitivity";
import { JobProgress } from "../../components/JobProgress";
import { BundleButton } from "../../components/BundleButton";
import { openReport } from "../../components/ReportLink";
import type { Range } from "../../components/ColorLegend";
import { View3DCard } from "../../view3d/View3DCard";
import type { LoadView } from "../../view3d/useLoadView";
import { nearestEnabledStage, stageEnabled, stageMode } from "../../view3d/arrows";
import { reconcile, visibleKeys, type Selection } from "../../view3d/selection";
import type { V3 } from "../../view3d/pick";
import { usePolling } from "../../lib/usePolling";
import { libPath } from "../library/common";

const ACTIVE_PHASE = ["PREP", "PREVIEW", "RUN"];
const MARK: Record<string, string> = { SUCCEEDED: "✓", RUNNING: "●", FAILED: "✗", SKIPPED: "↷" };

function Steps({ job }: { job: JobOut | null | undefined }) {
  const steps = job?.steps ?? [];
  if (!steps.length) return null;
  return (
    <ol className="job-steps" aria-label="DOE 단계">
      {steps.map((s) => (
        <li key={s.step_no} className={s.state.toLowerCase()} aria-current={s.state === "RUNNING" ? "step" : undefined}>
          {MARK[s.state] ?? "○"} {STEP_LABEL[s.step_key] ?? s.step_key}
          {s.state === "RUNNING" && s.progress_pct ? ` ${Math.round(s.progress_pct)}%` : ""}
        </li>
      ))}
    </ol>
  );
}

/** 시나리오 라디오(자동 판별 표시). readOnly = 상세 */
function ScenarioRadio({ value, onChange, auto, st, readOnly }: { value: DoeScenario; onChange: (s: DoeScenario) => void; auto: DoeScenario | null; st: DoeSettingsOut | null; readOnly: boolean }) {
  return (
    <div className="doe-scn" role="radiogroup" aria-label="시나리오">
      {SCENARIOS.map((s) => {
        const why = st ? scenarioBlocked(st, s) : null;
        return (
          <label key={s} className="check-field" title={why ?? undefined}>
            <input type="radio" name="doe-scenario" checked={value === s} disabled={readOnly || !!why} onChange={() => onChange(s)} />
            <span>
              {SCENARIO_NO[s]} {SCENARIO_NAME[s]}
            </span>
          </label>
        );
      })}
      {auto && !readOnly && (
        <span className="small muted" data-testid="doe-auto">
          자동 판별: {SCENARIO_NO[auto]} {SCENARIO_NAME[auto]}
          {auto !== value ? " (직접 바꿈)" : ""}
        </span>
      )}
    </div>
  );
}

// ================================================================ 새 연구
function NewStudy({ projectId, st, stError }: { projectId: string; st: DoeSettingsOut | null; stError: string | null }) {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const { me } = useApp();
  const allowed = canRun(me, projectId);
  const ids = useMemo(() => (sp.get("entries") ?? "").split(",").filter(Boolean), [sp]);
  const idsKey = ids.join(",");
  const all = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const byId = new Map((all.data ?? []).map((e) => [e.id, e]));
  const sel = ids.map((id) => byId.get(id)).filter((e): e is EntryOut => !!e);
  const [form, setForm] = useState<InputsForm>(EMPTY_INPUTS);
  const [chosen, setChosen] = useState<DoeScenario | null>(null);
  const auto = all.data ? autoScenario(sel, !!form.mesh) : null;
  const scenario: DoeScenario = chosen ?? auto ?? "same";
  const topo0 = sel[0]?.topo_sha256 ?? null;
  const [check, setCheck] = useState<DoeCheckOut | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mismatched = sel.filter((e) => e.topo_sha256 !== topo0 || check?.entries.some((r) => r.entry_id === e.id && !r.ok)).map((e) => e.id);
  const blocked = st ? doeBlockedReason(st) : null;

  // 입력 검사: STEP(②는 B 메시도) 업로드가 끝나면 자동(POST /doe/check-inputs)
  const stepId = form.step?.uploadId ?? null;
  const meshId = form.mesh?.uploadId ?? null;
  useEffect(() => {
    setCheck(null);
    setCheckError(null);
    if (!stepId || !ids.length || (scenario === "mesh" && !meshId) || blocked) return;
    let alive = true;
    setChecking(true);
    doe
      .checkInputs({ project_id: projectId, scenario, entry_ids: ids, step_upload_id: stepId, mesh_upload_id: scenario === "mesh" ? meshId : null })
      .then((c) => alive && setCheck(c))
      .catch((e) => alive && setCheckError(errorText(e)))
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, [projectId, scenario, idsKey, stepId, meshId, blocked]); // eslint-disable-line react-hooks/exhaustive-deps

  // ③ 쉘 물성·요소 크기 기본값(서버 props_default·mesh_size_default_mm)
  useEffect(() => {
    if (!check || scenario !== "step") return;
    setForm((f) => ({
      ...f,
      t: f.t || (check.props_default ? String(check.props_default.t) : ""),
      E: f.E || (check.props_default ? String(check.props_default.E) : ""),
      nu: f.nu || (check.props_default ? String(check.props_default.nu) : ""),
      meshSize: f.meshSize || (check.mesh_size_default_mm != null ? String(check.mesh_size_default_mm) : ""),
    }));
  }, [check, scenario]);
  useEffect(() => {
    if (st?.part_title) setForm((f) => (f.partTitle ? f : { ...f, partTitle: st.part_title ?? "" }));
  }, [st]);

  const setIds = (next: string[]) => {
    const q = new URLSearchParams(sp);
    q.set("entries", next.join(","));
    setSp(q, { replace: true });
  };

  function reason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !all.data) return "불러오는 중…";
    if (blocked) return blocked;
    const sb = scenarioBlocked(st, scenario);
    if (sb) return sb;
    if (!ids.length) return "ESL 을 고르세요 — 라이브러리 항목에서 체크한 뒤 '선택한 ESL로 비드 DOE'";
    if (sel.length !== ids.length) return "라이브러리에 없는 항목이 있습니다";
    if (ids.length > st.max_entries) return `ESL 은 최대 ${st.max_entries}개입니다`;
    if (scenario === "same" && mismatched.length) return `다른 모델 ESL ${mismatched.length}개 — '다른 모델 빼기' 또는 다른 모델 시나리오`;
    if (!form.step) return "Ch/R 중립면 STEP 을 올리세요";
    if (scenario === "mesh" && !form.mesh) return "B 메시(.rad/.inc)를 올리세요";
    if (scenario !== "same" && form.inch.trim() && !(Number.isInteger(Number(form.inch)) && Number(form.inch) > 0)) return "인치는 양의 정수입니다";
    if (checking) return "입력 검사 중…";
    if (checkError) return checkError;
    if (!check) return "입력 검사 대기 중…";
    if (!check.ok) return "입력 검사에 실패한 항목이 있습니다";
    if (scenario === "step") return propsProblem(form, st);
    return null;
  }

  async function prepare() {
    if (!form.step) return;
    setBusy(true);
    setError(null);
    try {
      const r = await doe.createStudy({
        project_id: projectId,
        scenario,
        entry_ids: ids,
        step_upload_id: form.step.uploadId,
        mesh_upload_id: scenario === "mesh" ? form.mesh?.uploadId ?? null : null,
        part_title: scenario === "mesh" ? form.partTitle.trim() || null : null,
        inch: scenario !== "same" && form.inch.trim() ? Number(form.inch) : null,
        title: form.title.trim() || null,
        ...(scenario === "step" ? { props: { t: Number(form.t), E: Number(form.E), nu: Number(form.nu) }, mesh_size_mm: Number(form.meshSize) } : {}),
      });
      nav(doePath(projectId, r.id));
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-title-row">
        <h1 className="page-title">새 비드 DOE</h1>
        <ScenarioRadio value={scenario} onChange={setChosen} auto={auto} st={st} readOnly={false} />
        <span className="spacer" />
        <PrimaryButton label="입력 준비" onClick={prepare} disabledReason={reason()} busy={busy} />
      </div>
      {blocked && (
        <div className="warn-box" role="alert" data-testid="doe-blocked">
          {blocked}
        </div>
      )}
      <ErrorLine text={error ?? stError ?? all.error} />
      <Card title="① 입력">
        {st && all.data ? (
          <DoeInputs
            projectId={projectId}
            scenario={scenario}
            st={st}
            entries={all.data}
            ids={ids}
            onIds={setIds}
            mismatched={mismatched}
            form={form}
            setForm={setForm}
            check={check}
            checkError={checkError}
            checking={checking}
            allowed={allowed}
          />
        ) : (
          <Empty>불러오는 중…</Empty>
        )}
      </Card>
      <div className="small muted">
        입력 준비가 끝나면 비드·변수 표와 평면도가 열립니다(형상 엔진 paicad 가 STEP 에서 비드를 인식). 입력 폴더는 읽기만 합니다.
        {!ids.length && (
          <>
            {" "}
            <Link to={libPath(projectId)}>라이브러리</Link>에서 ESL 을 고르세요.
          </>
        )}
      </div>
    </>
  );
}

// ================================================================ 3D 비교(기존 view3d 재사용)
function useDoeView(studyId: string, did: string | null): LoadView | null {
  const [manifest, setManifest] = useState<View3dOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStageRaw] = useState(0);
  const [selection, setSelectionRaw] = useState<Selection>(null);
  const [nonce, setNonce] = useState(0);
  const [focusReq, setFocusReq] = useState<LoadView["focusReq"]>(null);
  useEffect(() => {
    setManifest(null);
    setError(null);
    setSelectionRaw(null);
    setStageRaw(0);
    if (!did) return;
    let alive = true;
    setLoading(true);
    request<View3dOut>("GET", doe.view3dPath(studyId, did))
      .then((m) => {
        if (!alive) return;
        setManifest(m);
        const s = nearestEnabledStage(m, 0);
        setStageRaw(s < 0 ? 0 : s);
      })
      .catch((e) => alive && setError(errorText(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [studyId, did, nonce]);
  const mode = useMemo(() => stageMode(stage), [stage]);
  const setStage = useCallback(
    (i: number) => {
      if (!manifest) return;
      const j = stageEnabled(manifest, i) ? i : nearestEnabledStage(manifest, i);
      if (j < 0) return;
      setStageRaw(j);
      setSelectionRaw((s) => reconcile(s, visibleKeys(manifest, stageMode(j))));
    },
    [manifest],
  );
  const setSelection = useCallback((s: Selection) => setSelectionRaw(s), []);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const requestFocus = useCallback((p: V3) => setFocusReq((r) => ({ point: p, seq: (r?.seq ?? 0) + 1 })), []);
  const runId = did ? `doe:${studyId}:${did}` : null;
  return useMemo(
    () => (runId ? { runId, manifest, error, fallback: null, loading, stage, setStage, mode, selection, setSelection, focusReq, requestFocus, reload } : null),
    [runId, manifest, error, loading, stage, setStage, mode, selection, setSelection, focusReq, requestFocus, reload],
  );
}

function Compare3D({ studyId, result, pick, setPick }: { studyId: string; result: DoeResultOut; pick: string | null; setPick: (id: string) => void }) {
  const others = result.view3d.filter((d) => d !== "d000");
  const did = pick && others.includes(pick) ? pick : others[0] ?? null;
  const base = useDoeView(studyId, result.view3d.includes("d000") ? "d000" : null);
  const cand = useDoeView(studyId, did);
  const [manual, setManual] = useState<Range | null>(null);
  const autoMax = Math.max(base?.manifest?.ranges.u_max ?? 0, cand?.manifest?.ranges.u_max ?? 0);
  const range: Range | null = manual ?? (autoMax > 0 ? { min: 0, max: autoMax } : null);
  const opts = (title: string) => ({ title, colorBy: "disp" as const, range, rangeManual: !!manual, onRangeChange: setManual });
  if (!others.length) return <Empty>3D 비교 자료가 없습니다</Empty>;
  return (
    <div className="doe-compare">
      <div className="inline-actions">
        <span className="small muted">비교 안</span>
        <select aria-label="3D 비교 안" value={did ?? ""} onChange={(e) => setPick(e.target.value)}>
          {others.map((d) => (
            <option key={d} value={d}>
              {d}
              {result.ranking.find((r) => r.id === d) ? ` · ${result.ranking.find((r) => r.id === d)!.rank}위` : ""}
            </option>
          ))}
        </select>
        <span className="small muted">색 = 변위 |u|(최악 ESL), 두 그림 같은 범위</span>
      </div>
      <div className="doe-compare-grid">
        {base && <View3DCard view={base} options={opts("베이스라인 d000")} />}
        {cand && <View3DCard view={cand} options={opts(`안 ${did}`)} />}
      </div>
    </div>
  );
}

// ================================================================ 받기
function DownloadLink({ id, rel, label }: { id: string; rel: string; label: string }) {
  const [error, setError] = useState<string | null>(null);
  const url = doe.downloadUrl(id, rel);
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

function Downloads({ study, result }: { study: DoeStudyOut; result: DoeResultOut }) {
  const files = result.best?.files ?? [];
  const mesh = files.filter((f) => /\.(inc|rad|fem)$/i.test(f.rel));
  const geom = files.filter((f) => /\.(brep|step|stp)$/i.test(f.rel));
  const name = (rel: string) => rel.split("/").pop() ?? rel;
  return (
    <div className="inline-actions" data-testid="doe-downloads">
      <span className="small muted">받기{result.best ? ` · 최적 ${result.best.id}` : ""}</span>
      {mesh.map((f) => (
        <DownloadLink key={f.rel} id={study.id} rel={f.rel} label={`${study.scenario === "step" ? "메시" : "include"} ${name(f.rel)}`} />
      ))}
      {geom.map((f) => (
        <DownloadLink key={f.rel} id={study.id} rel={f.rel} label={name(f.rel).split(".").pop()!.toUpperCase()} />
      ))}
      <DownloadLink id={study.id} rel="post/ranking.csv" label="순위 CSV" />
      <BundleButton url={doe.bundleUrl(study.id)} filename={`doe_${study.id}.zip`} />
    </div>
  );
}

// ================================================================ 상세
function StudyDetail({ projectId, id, st, stError }: { projectId: string; id: string; st: DoeSettingsOut | null; stError: string | null }) {
  const nav = useNavigate();
  const { me } = useApp();
  const allowed = canRun(me, projectId);
  const [poll, setPoll] = useState(3000);
  const study = usePolling(() => doe.study(id), poll, [id]);
  const s = study.data;
  const phase = s?.phase ?? null;
  const prepDone = !!s?.prep && phase !== "PREP";
  useEffect(() => {
    if (s) setPoll(ACTIVE_PHASE.includes(s.phase) ? 3000 : 0);
  }, [s]);
  const all = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const params = usePolling(() => (prepDone ? doe.params(id) : Promise.resolve(null)), 0, [id, prepDone]);
  const plan = usePolling(() => (prepDone ? doe.planView(id) : Promise.resolve(null)), 0, [id, prepDone]);
  const done = phase === "DONE";
  const result = usePolling(() => (done ? doe.results(id) : Promise.resolve(null)), 0, [id, done]);

  const [rows, setRows] = useState<ParamRow[] | null>(null);
  const [form, setForm] = useState<SpecForm | null>(null);
  const [matrix, setMatrix] = useState<DoeMatrixOut | null>(null);
  const [matrixError, setMatrixError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<string | null>(null);

  // 변수 행·DOE 설정 기본값: 저장된 spec(있으면) 아니면 서버 기본(use_default D·W, feasible, 설정 doe.*)
  const pd = params.data;
  useEffect(() => {
    if (!pd || !st || !s || rows) return;
    const spec = s.doe?.spec ?? null;
    const base = defaultRows(pd.params, st.doe.default_types ?? ["D", "W"]);
    setRows(spec ? base.map((r) => {
      const x = spec.params.find((q) => q.name === r.name);
      return x ? { ...r, on: true, lo: String(x.lo), hi: String(x.hi) } : { ...r, on: false };
    }) : base);
    setForm({
      method: spec?.method ?? st.doe.default_method,
      n: String(spec?.n ?? st.doe.default_n),
      levels: String(spec?.levels ?? st.doe.levels_default),
      seed: String(spec?.seed ?? st.doe.seed),
    });
  }, [pd, st, s, rows]);

  const built = useMemo(() => (pd && rows && form && st ? buildSpec(form, pd.params, rows, st) : { spec: null as DoeSpec | null, problem: "불러오는 중…" }), [pd, rows, form, st]);
  const specKey = built.spec ? JSON.stringify(built.spec) : "";
  const version = s?.version ?? 0;
  const editable = !!s && allowed && (phase === "READY" || phase === "PREVIEW_READY");

  // 실제 안 수·sha(POST /matrix — 저장 안 함)
  const tm = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (tm.current) clearTimeout(tm.current);
    setMatrixError(null);
    if (!built.spec || !prepDone) {
      setMatrix(null);
      if (built.problem && rows) setMatrixError(built.problem);
      return;
    }
    let alive = true;
    tm.current = setTimeout(() => {
      doe
        .matrix(id, version, built.spec!)
        .then((m) => alive && setMatrix(m))
        .catch((e) => {
          if (!alive) return;
          setMatrix(null);
          setMatrixError(errorText(e));
        });
    }, 250);
    return () => {
      alive = false;
    };
  }, [id, specKey, prepDone]); // eslint-disable-line react-hooks/exhaustive-deps

  const pv = s?.doe?.preview ?? null;
  const fresh = !!pv && !!matrix && pv.matrix_sha256 === matrix.matrix_sha256 && s?.doe?.matrix_sha256 === matrix.matrix_sha256;
  const hasPreview = !!pv || phase === "PREVIEW";

  function previewReason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !s) return "불러오는 중…";
    const b = doeBlockedReason(st);
    if (b) return b;
    if (phase === "PREVIEW") return "미리보기 진행 중…";
    if (!editable) return phase === "PREP" ? "입력 준비 중…" : "이미 실행했습니다 — 복제해서 새 연구로";
    if (built.problem) return built.problem;
    if (matrixError) return matrixError;
    if (!matrix) return "안 수 계산 중…";
    return null;
  }
  function runReason(): string | null {
    const p = previewReason();
    if (phase === "PREVIEW") return "미리보기 진행 중…";
    if (p) return p;
    if (!pv) return "미리보기를 먼저 실행하세요";
    if (!fresh) return "DOE 설정이 미리보기 뒤에 바뀌었습니다 — 미리보기를 다시 실행하세요";
    if (pv.ok <= 0) return "미리보기 OK 안이 없습니다 — 범위를 바꾸세요";
    return null;
  }

  async function preview() {
    if (!built.spec) return;
    setBusy(true);
    setError(null);
    try {
      const r = await doe.preview(id, version, built.spec);
      study.setData(r);
      setPoll(3000);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function run() {
    if (!matrix) return;
    setBusy(true);
    setError(null);
    try {
      const r = await doe.run(id, version, matrix.matrix_sha256);
      study.setData(r);
      setPoll(3000);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function clone() {
    setBusy(true);
    setError(null);
    try {
      const r = await doe.clone(id);
      nav(doePath(projectId, r.id));
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  // 주 버튼(단계별 1개)
  let primary: { label: string; onClick: () => void; reason: string | null };
  if (!s || phase === "PREP") primary = { label: "입력 준비", onClick: () => undefined, reason: s ? "입력 준비 중…" : "불러오는 중…" };
  else if (phase === "RUN" || phase === "DONE" || (phase === "FAILED" && s.doe?.preview)) primary = { label: "보고서 보기", onClick: () => openReport(doe.reportUrl(id)), reason: done && s.result_ready ? null : phase === "RUN" ? "실행이 끝나면 볼 수 있습니다" : "보고서가 없습니다" };
  else if (phase === "FAILED") primary = { label: "입력 준비", onClick: () => undefined, reason: "입력 준비에 실패했습니다 — 아래 진행·로그를 확인하고 복제해 다시" };
  else if (!hasPreview) primary = { label: "미리보기", onClick: preview, reason: previewReason() };
  else primary = { label: "DOE 실행", onClick: run, reason: runReason() };

  const entries = all.data ?? [];
  const varNames = s?.doe?.spec.params.map((p) => p.name) ?? [];
  const showLinks = s?.scenario !== "same";
  const blocked = st ? doeBlockedReason(st) : null;
  const job = s?.job ?? null;
  const jobActive = !!job && (job.state === "QUEUED" || job.state === "RUNNING");

  return (
    <>
      <div className="page-title-row">
        <h1 className="page-title">비드 DOE</h1>
        {s && <span className="muted">{s.title}</span>}
        {s && <ScenarioRadio value={s.scenario} onChange={() => undefined} auto={null} st={st} readOnly />}
        {s && <Badge kind={phase === "FAILED" ? "bad" : phase === "DONE" ? "ok" : "info"}>{PHASE_NAME[s.phase]}</Badge>}
        <span className="spacer" />
        {(phase === "DONE" || phase === "FAILED") && allowed && (
          <button type="button" className="btn small ghost" disabled={busy} onClick={clone} title="같은 입력으로 새 연구(재실행)">
            복제
          </button>
        )}
        <PrimaryButton label={primary.label} onClick={primary.onClick} disabledReason={primary.reason} busy={busy} />
      </div>
      {blocked && (
        <div className="warn-box" role="alert" data-testid="doe-blocked">
          {blocked}
        </div>
      )}
      {st?.paicad.warning && <div className="small warn-text">{st.paicad.warning}</div>}
      <ErrorLine text={error ?? study.error ?? stError} />
      {s && (
        <Card title="① 입력" right={s.prep ? <span className="small muted">비드 {s.prep.n_beads} · 변수 {s.prep.n_params} · paicad {s.prep.paicad_version ?? "?"}</span> : undefined}>
          <DoeInputsSummary study={s} entries={entries} />
          {(phase === "PREP" || (phase === "FAILED" && !s.prep)) && job && (
            <>
              <Steps job={job} />
              <JobProgress jobId={job.id} allowed={allowed} onDone={() => void study.reload()} />
            </>
          )}
          {s.prep && s.prep.warnings.length > 0 && (
            <ul className="reasons small warn-text">
              {s.prep.warnings.map((w, i) => (
                <li key={i}>{warnText(w)}</li>
              ))}
            </ul>
          )}
        </Card>
      )}
      {prepDone && (
        <div className="doe-grid">
          <Card title="② 비드·변수" right={<DoeMethodInfo src={st?.method_sources} method={form?.method} />}>
            {pd && rows && form && st ? (
              <>
                <DoeParamTable data={pd} rows={rows} setRows={setRows} readOnly={!editable} beadPngUrl={(b) => doe.beadPngUrl(id, b)} />
                <DoeSpecRow st={st} form={form} setForm={setForm} matrix={matrix} matrixError={matrixError} readOnly={!editable} k={rows.filter((r) => r.on).length} />
              </>
            ) : (
              <Empty>{params.error ?? "불러오는 중…"}</Empty>
            )}
          </Card>
          <Card title={showLinks ? "③ 평면도 · 경계 매핑" : "③ 평면도"} right={showLinks && s?.prep ? <span className="small">경고 {s.prep.boundary.n_warn}</span> : undefined}>
            {plan.data && st ? (
              <div className="doe-plan-grid">
                <BoundaryPlan plan={plan.data} showLinks={showLinks} />
                <BoundaryLegend plan={plan.data} st={st} showLinks={showLinks} nWarn={s?.prep?.boundary.n_warn ?? null} />
              </div>
            ) : (
              <Empty>{plan.error ?? "불러오는 중…"}</Empty>
            )}
          </Card>
        </div>
      )}
      {prepDone && s && (
        <Card
          title={`④ 미리보기 ${pv ? previewSummary(pv, (pv.cells?.length ?? 0) + 1) : s.doe ? `(${s.doe.n_designs})` : ""}`}
          right={
            <span className="inline-actions">
              {s.doe && <span className="small muted">seed {s.doe.spec.seed ?? "–"} · {s.doe.spec.method}</span>}
              {hasPreview && editable && (
                <span className="primary-wrap" title={previewReason() ?? undefined}>
                  <button type="button" className="btn small" disabled={!!previewReason() || busy} onClick={preview}>
                    {fresh ? "미리보기 다시" : "미리보기"}
                  </button>
                </span>
              )}
            </span>
          }
        >
          {phase === "PREVIEW" && job && (
            <>
              <Steps job={job} />
              <JobProgress jobId={job.id} allowed={allowed} onDone={() => void study.reload()} />
            </>
          )}
          {pv && matrix && !fresh && editable && <div className="small warn-text" data-testid="preview-stale">DOE 설정이 이 미리보기와 다릅니다 — 실행하려면 미리보기를 다시 하세요</div>}
          {phase !== "PREVIEW" && <DoeThumbGrid preview={pv} params={pd?.params ?? []} thumbUrl={(d) => doe.thumbUrl(id, d)} />}
        </Card>
      )}
      {(phase === "RUN" || phase === "DONE" || (phase === "FAILED" && s?.doe?.preview)) && s && (
        <Card title={`⑤ 결과${result.data ? ` · OK ${result.data.n_ok}안` : ""}`} right={result.data && showLinks ? <span className="small">경계 경고 {result.data.boundary_warnings_n}</span> : undefined}>
          {job && (phase === "RUN" || phase === "FAILED") && (
            <>
              <Steps job={job} />
              {(jobActive || phase === "FAILED") && <JobProgress jobId={job.id} allowed={allowed} onDone={() => void study.reload()} />}
            </>
          )}
          <ErrorLine text={result.error} />
          {result.data && (
            <>
              {result.data.warnings.filter((w) => w.code !== "SENSITIVITY_TOO_FEW").length > 0 && (
                <ul className="reasons small warn-text">
                  {result.data.warnings
                    .filter((w) => w.code !== "SENSITIVITY_TOO_FEW")
                    .map((w, i) => (
                      <li key={i}>{warnText(w)}</li>
                    ))}
                </ul>
              )}
              <DoeRanking result={result.data} params={pd?.params ?? []} entries={entries} selected={pick} onSelect={setPick} varNames={varNames} />
              <div className="doe-result-grid">
                <div>
                  <div className="sub-title">민감도</div>
                  <Sensitivity sens={result.data.sensitivity} params={pd?.params ?? []} warnings={result.data.warnings} />
                </div>
                <div>
                  <div className="sub-title">3D 비교</div>
                  <Compare3D studyId={id} result={result.data} pick={pick} setPick={setPick} />
                </div>
              </div>
              <Downloads study={s} result={result.data} />
              <div className="small muted">선형 강성 상대 비교입니다(낙하 응답 재현 아님) — 최적 안은 검증 낙하 1회로 확인하세요. 방법·출처·한계는 보고서에.</div>
            </>
          )}
        </Card>
      )}
    </>
  );
}

export function DoeStudy() {
  const { projectId = "", doeId = "new" } = useParams();
  const { projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const settings = usePolling(() => doe.settings(), 0, []);
  const isNew = doeId === "new";
  return (
    <Shell
      crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "라이브러리", to: `${libPath(projectId)}?tab=doe` }, { label: isNew ? "새 비드 DOE" : "비드 DOE" }]}
      projectId={projectId}
    >
      {isNew ? <NewStudy projectId={projectId} st={settings.data} stError={settings.error} /> : <StudyDetail key={doeId} projectId={projectId} id={doeId} st={settings.data} stError={settings.error} />}
    </Shell>
  );
}
