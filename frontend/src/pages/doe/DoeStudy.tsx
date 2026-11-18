// 비드 DOE 새 연구·상세 한 화면(esl_bead_doe.md §3·§12.2). 시나리오 라디오 [① 같은 모델 ② 다른 모델(메시 있음) ③ 다른 모델(STEP만)]
// (자동 판별 + 표시), 주 버튼 1개 = 단계별 [입력 준비 | 미리보기 | DOE 실행 | 보고서 보기](비활성 사유 툴팁).
// 카드: ① 입력 · ② 비드·변수 + DOE 방식 · ③ 평면도(비드 번호·경계 경고) · ④ 미리보기 격자 · ⑤ 결과(순위·민감도·3D 비교·받기).
// 솔버 선택 칸 없음(선형만, 확정 6). 설정값은 모두 GET /doe/settings.
// v0.14.0 ④ 형상 직접 비교(esl_step_compare.md §7, SC-D-1): 주 버튼 [입력 준비] → (형상 표에 메시 요소 수·상태) → [비교 실행].
// ④ 는 ② 비드·변수 · ③ 평면도 · ④ 미리보기 카드를 숨기고, 결과는 같은 카드(이름 열 · 민감도 숨김 · 3D 기준 vs 선택 형상).
// v0.16.0 ④ 메시 옵션(esl_compare_mesh_options.md §8): ① 입력 카드 물성 칸 아래 '고급 설정'(접힘) = 메시 방식 [자동 | CAD | 재메시] + '실패 시 세분화 허용'.
// 재메시 미지원(remesh_available false)이면 비활성 + 사유 툴팁, 메시 형상만 있으면 숨김.
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { goneToList } from "../../components/ItemDeleteButton";
import { api } from "../../api/endpoints";
import { ApiError, downloadFile, errorText, request } from "../../api/client";
import type { CompareShapeIn, DoeBeadSource, DoeLoadTransferCfg, DoeLoadTransferDiag, DoeMeshMode, DoeMeshPart } from "../../api/types";
import {
  BEAD_SOURCE_NAME, MESH_MODE_HINT, MESH_MODE_NAME, NEW_RADIOS, NEW_RADIO_NAME, NEW_RADIO_NO, PHASE_NAME, SENS_REASON, autoScenario, buildSpec, compareErrorText, defaultRows, doe, doeBlockedReason, doePath,
  loadSelectAuto, partIdProblem, partsFromError, radioRequest, remeshUnavailableText, scenarioBlocked, selectSubBlocked, shapesProblem, studyRadio, warnText,
  LEGACY_STEP_LABEL, STEP_PREP_CODES, meshMethodName, radioBase, stepPrepGroups,
  isCrossMesh, isLinResult, ltChoiceLabel, ltKey, ltRequest, ltSummaryLine, ltVariantLabel,
  type NewRadio,
  type ParamRow, type SpecForm, RULES_OUTDATED_TEXT, BG_STALE_TEXT, isInfoWarn } from "../../api/doe";
import { BeadSelectCards, SelectDesign3D, autoNoticeText, selectMesh, useBeadSelect, type AutoSeedView, type StepInfoView } from "../../components/BeadSelectCard";
import { PartView } from "../../view3d/part/PartView";
import { legacyViewData, sceneLayers, selectScene, selectViewData } from "../../view3d/part/adapters";
import type { PartMesh, PlanVar } from "../../view3d/part/types";
import { fetchBinary, fileUrls } from "../../view3d/fetchFiles";
import { parseGlb } from "../../view3d/glb";
import { SectionMini } from "../../components/SectionMini";
import { STEP_LABEL } from "../../api/history";
import type { DoeCheckOut, DoeJigDiagEntryOut, DoeJigDiagOut, DoeJigRegionsFile, DoeMatrixOut, DoeResultOut, DoeSettingsOut, DoeSpec, DoeStudyOut, EntryOut, JobOut, RedropEntryOut, View3dOut } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell, MENU_LIBRARY } from "../../shell/Shell";
import { Badge, Card, Empty, ErrorLine, PrimaryButton, type CardFold } from "../../components/ui";
import { DoeInputs, DoeInputsSummary, EMPTY_INPUTS, propsProblem, rowSource, type InputsForm } from "../../components/DoeInputs";
import { DoeMethodInfo, DoeParamTable, DoeSpecRow } from "../../components/DoeParamTable";
import { DoeThumbGrid, previewSummary, valuesText } from "../../components/DoeThumbGrid";
import { BestCleanChip, ChipDetail, BestCleanMqChip, DoeRanking, JigLine, JigNoneChip } from "../../components/DoeRanking";
import { DoePerEslTable, perEslNote } from "../../components/DoePerEslTable";
import { Sensitivity } from "../../components/Sensitivity";
import { JobProgress } from "../../components/JobProgress";
import { BundleButton } from "../../components/BundleButton";
import { openReport } from "../../components/ReportLink";
import type { Range } from "../../components/ColorLegend";
import { View3DCard, type View3DOptions } from "../../view3d/View3DCard";
import type { LoadView } from "../../view3d/useLoadView";
import { buildArrow, nearestEnabledStage, stageEnabled, stageMode, type ArrowSpec } from "../../view3d/arrows";
import { reconcile, visibleKeys, type Selection } from "../../view3d/selection";
import type { V3 } from "../../view3d/pick";
import { usePolling } from "../../lib/usePolling";
import { libPath } from "../library/common";
import { scx } from "../../api/scx";
import { VD_BUTTON, eligibleDesigns, isActiveDrop, verify, verifyButtonReason } from "../../api/verify";
import type { VerifyDropOut, VerifyPlanOut } from "../../api/types";
import { VerifyDropDialog } from "../../components/VerifyDropDialog";
import { VerifyDropCard } from "../../components/VerifyDropCard";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { FixedViolNote } from "../../components/FixedViol";
import { JobFailBanner, isFailedJob, progressText } from "../../components/JobFailBanner";
import { BlockErr, MsgFold } from "../../components/MsgFold";
import { LOAD_SOURCES, sourceOf, tabResult, tabState, type ChipKind, type LoadSource, type LoadTab, type TabState, type View3dKind } from "./doeTabs";

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

/** 시나리오 라디오(자동 판별 표시). readOnly = 상세.
 * v0.16.2(esl_bead_auto.md AD-D-1·13): ①(같은 모델)·②(다른 모델 B 메시) = 시나리오 select, 그 아래 하위 라디오 "비드: ○ 자동 탐지 ○ 직접 선택"(bead_source).
 * same·mesh 는 새로 만들지 않음 — 기존 same·mesh 스터디(상세)는 ①·② 위치에 '이전 방식' 표시 */
function ScenarioRadio({ value, source, onChange, onSource, auto, st, readOnly, legacy }: {
  value: NewRadio;
  source: DoeBeadSource | null;
  onChange: (r: NewRadio) => void;
  onSource: (s: DoeBeadSource) => void;
  auto: NewRadio | null;
  st: DoeSettingsOut | null;
  readOnly: boolean;
  /** 기존 same·mesh 스터디 하위 문구 */
  legacy?: string | null;
}) {
  // v0.18.0: ③ 도 select(select_base step) — ①②③ 모두 하위 라디오 "비드"
  const base = radioBase(value) ?? "case";
  const isSel = value !== "compare";
  return (
    <div className="doe-scn" role="radiogroup" aria-label="시나리오">
      {NEW_RADIOS.map((r) => {
        // ①②③ 는 직접 선택(paicad 불필요)까지 막혔을 때만 막음(③ = gmsh 없음 — SG §6)
        const rb = radioBase(r);
        const why = st ? (rb ? selectSubBlocked(st, rb, "manual") : scenarioBlocked(st, "compare")) : null;
        return (
          <label key={r} className="check-field" title={why ?? undefined}>
            <input type="radio" name="doe-scenario" checked={value === r} disabled={readOnly || !!why} onChange={() => onChange(r)} />
            <span>
              {NEW_RADIO_NO[r]} {NEW_RADIO_NAME[r]}
            </span>
          </label>
        );
      })}
      {isSel && legacy && (
        <span className="small muted" data-testid="doe-legacy">
          {legacy}
        </span>
      )}
      {isSel && !legacy && (
        <span className="doe-sub" role="radiogroup" aria-label="비드 정의" data-testid="doe-beaddef">
          <span className="small muted">비드</span>
          {(["auto", "manual"] as const).map((k) => {
            const why = st ? selectSubBlocked(st, base, k) : null;
            return (
              <label key={k} className="check-field" title={why ?? (k === "auto" ? "메시 분류기가 비드 네트워크를 찾아 3D 선택을 채웁니다 — 고친 뒤 저장" : "3D 에서 비드 바닥을 직접 고릅니다")}>
                <input type="radio" name="doe-beaddef" checked={source === k} disabled={readOnly || !!why} onChange={() => onSource(k)} />
                <span>{BEAD_SOURCE_NAME[k]}</span>
              </label>
            );
          })}
        </span>
      )}
      {auto && !readOnly && (
        <span className="small muted" data-testid="doe-auto">
          자동 판별: {NEW_RADIO_NO[auto]} {NEW_RADIO_NAME[auto]}
          {auto !== value ? " (직접 바꿈)" : ""}
        </span>
      )}
    </div>
  );
}

/** OK 0개 사유별 개수(고정 침범·품질 실패·뒤집힘·그 밖) */
export function zeroOkText(cells: { status: string; code?: string | null }[]): string {
  const n = (f: (c: { status: string; code?: string | null }) => boolean) => cells.filter(f).length;
  const parts: [string, number][] = [
    ["고정 침범", n((c) => c.code === "SELECT_FIXED_VIOLATION" || c.status === "SKIPPED_FIXED")],
    ["품질 실패", n((c) => c.code === "SELECT_QUALITY_FAIL")],
    ["뒤집힘", n((c) => c.code === "SELECT_MORPH_INVERTED")],
    ["충돌", n((c) => c.status === "SKIPPED_COLLISION")],
  ];
  const known = parts.reduce((a, [, v]) => a + v, 0);
  const other = cells.filter((c) => c.status !== "READY").length - known;
  return [...parts.filter(([, v]) => v > 0).map(([k, v]) => `${k} ${v}`), ...(other > 0 ? [`그 밖 ${other}`] : [])].join(" · ") || "사유 없음";
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
  const [chosen, setChosen] = useState<NewRadio | null>(null);
  /** v0.16.2 ①② 하위 라디오(기본 직접 선택 — AD-D-1) */
  const [source, setSource] = useState<DoeBeadSource>("manual");
  const autoS = all.data ? autoScenario(sel, !!form.mesh) : null;
  const auto: NewRadio | null = autoS ? studyRadio(autoS) : null;
  const radio: NewRadio = chosen ?? auto ?? "case";
  const { scenario, selectBase } = radioRequest(radio);
  const topo0 = sel[0]?.topo_sha256 ?? null;
  const [check, setCheck] = useState<DoeCheckOut | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = st ? doeBlockedReason(st, scenario) : null;
  const isCompare = scenario === "compare";
  const isSelect = scenario === "select";
  /** ② B 메시 기준 select */
  const meshBase = isSelect && selectBase === "mesh";
  /** v0.18.0 ③ STEP 기준 select(esl_step_graph.md SG-D-1·3) */
  const stepBase = isSelect && selectBase === "step";
  /** 자동 탐지(v0.17.0 메시 분류기 — STEP 선택, 있으면 paicad 힌트만) */
  const isAuto = isSelect && source === "auto";
  /** 같은 모델 검사(①) */
  const sameModel = isSelect && !meshBase && !stepBase;
  const mismatched = sameModel ? sel.filter((e) => e.topo_sha256 !== topo0 || check?.entries.some((r) => r.entry_id === e.id && !r.ok)).map((e) => e.id) : [];
  const maxShapes = st?.compare?.max_shapes ?? 20;
  /** ④ 요청 형상(기준 = refId). v0.16.0 메시 행만 source·part_id(STEP 행 요청은 v0.15 와 같음) */
  const compareShapes: CompareShapeIn[] = form.shapes.map((x) => {
    const base: CompareShapeIn = { upload_id: x.uploadId, rel: x.rel, name: x.name.trim(), reference: x.key === form.refId };
    if (rowSource(x) !== "mesh") return base;
    const pid = (x.partId ?? "").trim();
    return { ...base, source: "mesh", ...(pid && !partIdProblem(pid) ? { part_id: Number(pid) } : {}) };
  });
  /** v0.16.0 메시 방식(사용자가 바꾼 경우만 — 없으면 서버 설정값). STEP 형상이 없으면 보내지 않음 */
  const hasStep = form.shapes.some((x) => rowSource(x) === "step");
  const meshOpts = (isCompare && hasStep) || stepBase ? { ...(form.meshMode ? { mesh_mode: form.meshMode } : {}), ...(form.meshRefine != null ? { mesh_refine: form.meshRefine } : {}) } : {};
  /** v0.20.0 하중 전달(사용자가 기본과 다르게 고른 경우만 요청에 넣음 — LT-11) */
  const ltOpts = ltRequest(st?.load_transfer, form.ltChoice);
  const shapesKey = isCompare ? JSON.stringify([compareShapes, meshOpts, ltOpts]) : "";
  const partBad = isCompare
    ? form.shapes.map((x, i) => (rowSource(x) === "mesh" && partIdProblem(x.partId ?? "") ? `형상 ${i + 1}: ${partIdProblem(x.partId ?? "")}` : null)).find(Boolean) ?? null
    : null;
  const shapesBad = isCompare ? shapesProblem(form.shapes, form.refId !== null, maxShapes) ?? partBad : null;
  const inchOn = scenario === "step" || isCompare || meshBase || stepBase;
  const inchVal = inchOn && form.inch.trim() && Number.isInteger(Number(form.inch)) && Number(form.inch) > 0 ? Number(form.inch) : null;

  // 입력 검사: 필요한 업로드가 끝나면 자동(POST /doe/check-inputs). ④ 는 이름 입력 중 0.3 s 모아서
  const stepId = form.step?.uploadId ?? null;
  const meshId = form.mesh?.uploadId ?? null;
  /** select 요청 칸(AD-D-1·13·14): bead_source 항상, select_base 는 mesh·step 일 때만, STEP 은 auto(힌트)·③(필수), B 메시는 ② 만.
   *  v0.18.0 ③(SG-D-3): select_base step + step_upload_id + inch·mesh_mode·mesh_refine(바꾼 경우만) — part_title·mesh_size_mm 은 보내지 않음(422) */
  const selectBody = () => ({
    bead_source: source,
    ...(meshBase ? { select_base: "mesh" as const, mesh_upload_id: meshId } : {}),
    ...(stepBase ? { select_base: "step" as const, step_upload_id: stepId, inch: inchVal, ...meshOpts } : {}),
    ...(isAuto && !stepBase && stepId ? { step_upload_id: stepId } : {}),
    ...ltOpts,
  });
  useEffect(() => {
    setCheck(null);
    setCheckError(null);
    setChecking(false);
    if (!ids.length || blocked) return;
    if (isCompare ? !!shapesBad : isSelect ? (meshBase && !meshId) || (stepBase && !stepId) : !stepId) return;
    let alive = true;
    const go = () => {
      setChecking(true);
      doe
        .checkInputs(
          isCompare
            ? { project_id: projectId, scenario, entry_ids: ids, shapes: compareShapes, inch: inchVal, ...meshOpts, ...ltOpts }
            : isSelect
              ? { project_id: projectId, scenario, entry_ids: ids, ...selectBody() }
              : { project_id: projectId, scenario, entry_ids: ids, step_upload_id: stepId, ...ltOpts },
        )
        .then((c) => {
          if (!alive) return;
          setCheck(c);
          if (isCompare) applyParts((c.shapes ?? []).map((x) => [x.index, x.parts ?? null] as const));
        })
        .catch((e) => {
          if (!alive) return;
          setCheckError(compareErrorText(e));
          const pe = isCompare ? partsFromError(e) : null;
          if (pe) applyParts([[pe.index, pe.parts]]);
        })
        .finally(() => alive && setChecking(false));
    };
    const t = isCompare ? setTimeout(go, 300) : null;
    if (!t) go();
    return () => {
      alive = false;
      if (t) clearTimeout(t);
    };
  }, [projectId, scenario, selectBase, source, idsKey, stepId, meshId, blocked, shapesKey, shapesBad, (stepBase ? `${inchVal}:${JSON.stringify(meshOpts)}` : "") + JSON.stringify(ltOpts)]); // eslint-disable-line react-hooks/exhaustive-deps

  /** v0.16.0 check-inputs parts[] → 메시 행 datalist, 파트가 하나면 빈 칸 자동 채움(C2-D-4·§8) */
  function applyParts(list: readonly (readonly [number, DoeMeshPart[] | null])[]) {
    const byIdx = new Map(list.filter(([, p]) => !!p).map(([i, p]) => [i, p!]));
    if (!byIdx.size) return;
    setForm((f) => {
      let changed = false;
      const shapes = f.shapes.map((x, i) => {
        const parts = byIdx.get(i);
        if (!parts || rowSource(x) !== "mesh") return x;
        const same = JSON.stringify(parts) === JSON.stringify(x.parts ?? null);
        const fill = parts.length === 1 && !(x.partId ?? "").trim();
        if (same && !fill) return x;
        changed = true;
        return { ...x, parts, partId: fill ? String(parts[0].id) : x.partId };
      });
      return changed ? { ...f, shapes } : f;
    });
  }

  // ③④ 쉘 물성(③ 은 요소 크기도) 기본값(서버 props_default·mesh_size_default_mm)
  useEffect(() => {
    if (!check || (scenario !== "step" && scenario !== "compare" && !stepBase)) return;
    setForm((f) => ({
      ...f,
      t: f.t || (check.props_default ? String(check.props_default.t) : ""),
      E: f.E || (check.props_default ? String(check.props_default.E) : ""),
      nu: f.nu || (check.props_default ? String(check.props_default.nu) : ""),
      meshSize: scenario === "step" ? f.meshSize || (check.mesh_size_default_mm != null ? String(check.mesh_size_default_mm) : "") : f.meshSize,
    }));
  }, [check, scenario, stepBase]);
  useEffect(() => {
    if (st?.part_title) setForm((f) => (f.partTitle ? f : { ...f, partTitle: st.part_title ?? "" }));
  }, [st]);
  // 자동 탐지를 못 쓰면(paicad 없음) 직접 선택으로
  useEffect(() => {
    if (st && isSelect && source === "auto" && selectSubBlocked(st, selectBase ?? "case", "auto")) setSource("manual");
  }, [st, isSelect, source, selectBase]);

  const setIds = (next: string[]) => {
    const q = new URLSearchParams(sp);
    q.set("entries", next.join(","));
    setSp(q, { replace: true });
  };

  function reason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !all.data) return "불러오는 중…";
    if (blocked) return blocked;
    const sb = isSelect ? selectSubBlocked(st, selectBase ?? "case", source) : scenarioBlocked(st, scenario);
    if (sb) return sb;
    if (!ids.length) return "ESL 을 고르세요 — ESL 라이브러리 › ESL 목록에서 체크한 뒤 '강성 평가 스터디'";
    if (sel.length !== ids.length) return "라이브러리에 없는 항목이 있습니다";
    if (ids.length > st.max_entries) return `ESL 은 최대 ${st.max_entries}개입니다`;
    if (isCompare) {
      if (shapesBad) return shapesBad;
      if (form.inch.trim() && !inchVal) return "인치는 양의 정수입니다";
      if (checking) return "입력 검사 중…";
      if (checkError) return checkError;
      if (!check) return "입력 검사 대기 중…";
      if (!check.ok) return "입력 검사에 실패한 항목이 있습니다";
      return propsProblem(form, st, false);
    }
    if (sameModel && mismatched.length) return `다른 모델 ESL ${mismatched.length}개 — '다른 모델 빼기' 또는 ② 다른 모델(B 메시)`;
    if (meshBase && !form.mesh) return "B 메시(.rad/.inc)를 올리세요";
    if ((scenario === "step" || stepBase) && !form.step) return "Ch/R 중립면 STEP 을 올리세요";
    if (inchOn && form.inch.trim() && !inchVal) return "인치는 양의 정수입니다";
    if (checking) return "입력 검사 중…";
    if (checkError) return checkError;
    if (!check) return "입력 검사 대기 중…";
    if (!check.ok) return "입력 검사에 실패한 항목이 있습니다";
    if (scenario === "step") return propsProblem(form, st);
    if (stepBase) return propsProblem(form, st, false);
    return null;
  }

  async function prepare() {
    setBusy(true);
    setError(null);
    try {
      const title = form.title.trim() || null;
      const r = isCompare
        ? await doe.createStudy({ project_id: projectId, scenario, entry_ids: ids, shapes: compareShapes, inch: inchVal, ...meshOpts, ...ltOpts, title, props: { t: Number(form.t), E: Number(form.E), nu: Number(form.nu) } })
        : isSelect
          ? await doe.createStudy({
              project_id: projectId,
              scenario,
              entry_ids: ids,
              ...selectBody(),
              ...(meshBase ? { part_title: form.partTitle.trim() || null, inch: inchVal } : {}),
              ...(stepBase ? { props: { t: Number(form.t), E: Number(form.E), nu: Number(form.nu) } } : {}),
              title,
            })
          : await doe.createStudy({
              project_id: projectId,
              scenario,
              entry_ids: ids,
              step_upload_id: stepId,
              inch: inchVal,
              ...ltOpts,
              title,
              props: { t: Number(form.t), E: Number(form.E), nu: Number(form.nu) },
              mesh_size_mm: Number(form.meshSize),
            });
      nav(doePath(projectId, r.id));
    } catch (e) {
      setError(isCompare ? compareErrorText(e) : errorText(e));
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-title-row">
        <h1 className="page-title">새 강성 평가 스터디</h1>
        <ScenarioRadio value={radio} source={source} onChange={setChosen} onSource={setSource} auto={auto} st={st} readOnly={false} />
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
            selectBase={selectBase}
            beadSource={isSelect ? source : null}
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
            advanced={(() => {
              // 메시 방식 줄은 ④(STEP 형상이 있거나 아직 없음)·③(STEP 기준)만, 하중 전달 select 는 ①②③④ 공통(§13.8)
              const showMesh = !!st.compare?.mesh_mode && ((isCompare && (hasStep || !form.shapes.length)) || stepBase);
              return showMesh || st.load_transfer ? <CompareMeshAdvanced st={st} check={check} form={form} setForm={setForm} allowed={allowed} showMesh={showMesh} sameModel={isSelect && selectBase === "case"} /> : null;
            })()}
          />
        ) : (
          <Empty>불러오는 중…</Empty>
        )}
      </Card>
      {(() => {
        // v0.23.1 긴 글(esl_doe_ui_tidy.md §7): 첫 문장(다음 동작)만 상시, 나머지는 ⓘ 접기. 라이브러리 링크(ESL 미선택)는 그대로
        const [lead, ...rest] = isCompare
          ? ["입력 준비에서 형상마다 같은 설정으로 메시를 만들고 크기·정렬을 검사합니다(비드 인식·미리보기 없음).", "준비 결과를 확인한 뒤 '비교 실행'."]
          : stepBase
            ? ["입력 준비에서 STEP 을 ④ 와 같은 설정으로 메시한 뒤 메시 분류기가 비드 네트워크를 찾고, A 모델 고정점을 옮겨 고정 층을 채웁니다 — 고친 뒤 '선택 저장'.", "결과는 메시(ch_r.rad)만 받습니다."]
            : isAuto
              ? ["입력 준비에서 메시 분류기가 비드 네트워크(세그먼트·접합)를 찾아 3D 선택을 채웁니다 — 고친 뒤 '선택 저장'.", "STEP 은 없어도 됩니다(있으면 참고 힌트).", "분류가 실패해도 직접 칠할 수 있습니다."]
              : isSelect
                ? ["입력 준비가 끝나면 3D 에서 비드 바닥을 클릭해 고르고(같은 법선 자동 확장), 사면·경계를 자동으로 잡은 뒤 '선택 저장'."]
                : ["입력 준비가 끝나면 비드·변수 표와 평면도가 열립니다(형상 엔진 paicad 가 STEP 에서 비드를 인식)."];
        const more = [...rest, ...(meshBase || stepBase ? [`하중은 셀 매핑, 지지는 ${stepBase ? "STEP 메시" : "B 메시"} 자동 3-2-1 입니다.`] : []), "입력 폴더는 읽기만 합니다."].join(" ");
        return (
          <div className="small muted" data-testid="new-note">
            {lead}{" "}
            <details className="doe-note-more" data-testid="new-note-more">
              <summary aria-label="자세한 안내">ⓘ</summary> {more}
            </details>
            {!ids.length && (
              <>
                {" "}
                <Link to={libPath(projectId)}>라이브러리</Link>에서 ESL 을 고르세요.
              </>
            )}
          </div>
        );
      })()}
    </>
  );
}

// ================================================================ v0.16.0 ④ 고급 설정(메시 방식)
/** 물성 칸 아래 접힘 칸: 메시 방식 [자동(기본) | CAD | 재메시] + '실패 시 세분화 허용'(자동일 때만). 재메시 미지원이면 비활성·사유 툴팁 */
/** v0.20.0 하중 전달 select 1개(모든 모드 공용, §13.8): 일 등가(권장) | 셀 … — 기본과 같으면 요청 생략(form.ltChoice = null). ① 에서 셀 = 비교용 안내 */
function LoadTransferField({ cfg, form, setForm, allowed, sameModel }: {
  cfg: DoeLoadTransferCfg;
  form: InputsForm;
  setForm: (f: InputsForm | ((p: InputsForm) => InputsForm)) => void;
  allowed: boolean;
  sameModel?: boolean;
}) {
  const def = ltKey(cfg.method, cfg.cell_size_mm);
  const cur = form.ltChoice ?? def;
  const sizeOf = (k: string) => (k === "work" || k === "cell:legacy" ? null : Number(k.slice(5)));
  const opts = ["work", ...cfg.cell_choices_mm.map((c) => ltKey("cell", c))];
  // 기본이 선택지에 없으면(설정 불일치) 맨 앞에 추가
  if (!opts.includes(def)) opts.unshift(def);
  return (
    <div className="doe-adv-row">
      <label className="field-label" htmlFor="lt-select">하중 전달</label>
      <select id="lt-select" aria-label="하중 전달" data-testid="lt-select" value={cur} disabled={!allowed} onChange={(e) => setForm((f) => ({ ...f, ltChoice: e.target.value === def ? null : e.target.value }))}>
        {opts.map((k) => (
          <option key={k} value={k}>
            {ltChoiceLabel(k === "work" ? "work" : "cell", sizeOf(k), { def: k === def })}
          </option>
        ))}
      </select>
      <span className="small muted" data-testid="lt-hint">
        {cur === "work" ? "ESL 하중을 일 등가로 대상 메시에 옮깁니다(같은 규칙을 모든 안에)" : "ESL 하중을 셀 합력으로 나눠 옮깁니다(셀이 작을수록 원본에 가까움)"}
      </span>
      {sameModel && cur !== "work" && (
        <span className="small warn-text" data-testid="lt-same-note">
          같은 모델 — 일 등가 = 노드 직접. 셀은 비교용
        </span>
      )}
    </div>
  );
}

function CompareMeshAdvanced({ st, check, form, setForm, allowed, showMesh, sameModel }: {
  st: DoeSettingsOut;
  check: DoeCheckOut | null;
  form: InputsForm;
  setForm: (f: InputsForm | ((p: InputsForm) => InputsForm)) => void;
  allowed: boolean;
  /** 메시 방식 줄(STEP 형상이 없으면 숨김 — 하중 전달 select 는 형상 출처와 무관) */
  showMesh: boolean;
  /** ① 같은 모델(select_base case) — 셀 선택 안내용 */
  sameModel?: boolean;
}) {
  const lt = st.load_transfer ?? null;
  const ltName = lt ? ltVariantLabel(form.ltChoice ?? ltKey(lt.method, lt.cell_size_mm)) : "";
  const def: DoeMeshMode = st.compare?.mesh_mode ?? "auto";
  const mode: DoeMeshMode = form.meshMode ?? def;
  const remeshOk = check?.remesh_available ?? st.compare?.remesh_available ?? false;
  const remeshWhy = remeshOk ? null : remeshUnavailableText(st.gmsh.version);
  const refine = form.meshRefine ?? true;
  const set = (m: DoeMeshMode) => setForm((f) => ({ ...f, meshMode: m === def ? null : m }));
  return (
    <details className="adv-input doe-adv" data-testid="compare-adv">
      <summary>
        고급 설정 <span className="muted small">{showMesh ? <>· 메시 방식 {MESH_MODE_NAME[mode]}{mode === "auto" && !refine ? "(세분화 끔)" : ""}</> : null}{lt ? <>{showMesh ? " " : ""}· 하중 {ltName}</> : null}</span>
      </summary>
      <div className="adv-body doe-adv-body">
        {lt && <LoadTransferField cfg={lt} form={form} setForm={setForm} allowed={allowed} sameModel={sameModel} />}
        {showMesh && (<>
        <div className="doe-adv-row">
          <span className="field-label">메시 방식</span>
          <div className="seg" role="radiogroup" aria-label="메시 방식">
            {(["auto", "cad", "remesh", "freeform"] as const).map((m) => {
              const off = !allowed || ((m === "remesh" || m === "freeform") && !remeshOk);
              return (
                <span key={m} title={(m === "remesh" || m === "freeform") && remeshWhy ? remeshWhy : MESH_MODE_HINT[m]}>
                  <button type="button" role="radio" aria-checked={mode === m} className={mode === m ? "on" : undefined} disabled={off} onClick={() => set(m)}>
                    {MESH_MODE_NAME[m]}
                    {m === def ? "(기본)" : ""}
                  </button>
                </span>
              );
            })}
          </div>
          <label className="check" title={mode === "auto" ? "CAD 메시가 실패하면 요소를 더 잘게(국부 → 전역) 다시 시도 — 요소 수가 늘어남" : "자동일 때만 씁니다"}>
            <input
              type="checkbox"
              aria-label="실패 시 세분화 허용"
              checked={refine}
              disabled={!allowed || mode !== "auto"}
              onChange={(e) => setForm((f) => ({ ...f, meshRefine: e.target.checked ? null : false }))}
            />{" "}
            실패 시 세분화 허용
          </label>
        </div>
        <div className="small muted" data-testid="compare-adv-hint">
          {MESH_MODE_HINT[mode]}
          {remeshWhy ? ` · 재메시 불가: ${remeshWhy}` : ""}
        </div>
        </>)}
      </div>
    </details>
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

// ================================================================ v0.20.0 ④ 하중 전달 진단(esl_load_transfer.md §7)
const fx = (x: number | null | undefined, d = 2) => (x == null || !Number.isFinite(x) ? "–" : x.toFixed(d));
const pct = (x: number) => `${(x * 100).toFixed(x > 0 && x < 0.001 ? 2 : 1)} %`;
/** 상태 띠 칩(v0.23.1 esl_doe_ui_tidy.md §4 칩 2): 칩 = details summary(짧은 값, title = 이전 요약 줄 전체) → 펼치면 띠 아래 접힘 표 2개(d000 참값 대비 · 형상별). 새 결과(load_transfer 있음)만 */
function LoadTransferDiag({ studyId, result }: { studyId: string; result: DoeResultOut }) {
  const lt = result.load_transfer;
  const [diag, setDiag] = useState<DoeLoadTransferDiag | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  if (!lt) return null;
  const load = () => {
    if (state !== "idle") return;
    setState("loading");
    doe
      .loadTransferDiag(studyId)
      .then(setDiag)
      .catch(() => setDiag(null))
      .finally(() => setState("done"));
  };
  const eslLabel = (id: string, label?: string | null) => label ?? result.esl?.find((e) => e.entry_id === id)?.label ?? id.slice(0, 8);
  const nameOf = (id: string) => result.ranking.find((r) => r.id === id)?.shape?.name ?? "";
  const full = `${ltSummaryLine(lt)}${result.scenario !== "compare" && lt.truth === "a_direct" ? " (모델 차 포함)" : ""}${lt.rank_alt_same != null ? ` · 다른 방식 순위 ${lt.rank_alt_same ? "같음" : "다름"}` : ""}${lt.warnings_n ? ` · 경고 ${lt.warnings_n}` : ""}`;
  return (
    <span className="doe-lt" data-testid="lt-block">
      <details className="doe-chip-detail" data-testid="lt-details" onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && load()}>
        <summary className="doe-chip muted" data-testid="lt-summary" title={full}>
          하중 전달 {ltVariantLabel(ltKey(lt.method, lt.cell_size_mm))}{lt.warnings_n ? ` · 경고 ${lt.warnings_n}` : ""} · 진단 표
        </summary>
        <div className="small" data-testid="lt-full">{full}</div>
        {state === "loading" && <div className="small muted">불러오는 중…</div>}
        {state === "done" && !diag && <div className="small muted" data-testid="lt-nodiag">진단 자료가 없습니다(진단 끔 또는 진단 단계 건너뜀)</div>}
        {diag && (
          <>
            <div className="small muted">
              베이스라인(d000) 참값 대비 — 참값 = {diag.d000.truth === "direct_nodal" ? "① 직접 하중" : diag.d000.truth === "a_direct" ? "A 메시 직접 풀이" : "없음"}
              {diag.reference.identity ? "" : " (상관·MAC 은 같은 메시일 때만)"}
            </div>
            <div className="table-wrap scroll">
              <table className="table compact" aria-label="하중 전달 베이스라인 참값 대비">
                <thead>
                  <tr><th>방식</th><th>ESL</th><th>하중 상관</th><th>umax ×</th><th>C ×</th><th>MAC</th></tr>
                </thead>
                <tbody>
                  {diag.d000.rows.map((r, i) => (
                    <tr key={i}>
                      <td>{ltVariantLabel(r.variant)}</td>
                      <td>{eslLabel(r.entry_id, r.label)}</td>
                      <td>{fx(r.load_corr, 3)}</td>
                      <td>{fx(r.umax_ratio)}</td>
                      <td>{fx(r.C_ratio)}</td>
                      <td>{fx(r.mac, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {diag.shapes.length >= 2 && (
            <div className="table-wrap scroll" style={{ marginTop: "0.75rem" }}>
              <table className="table compact" aria-label="하중 전달 형상별">
                <thead>
                  <tr><th>형상</th><th>점수</th><th>점수(다른 방식)</th><th>먼 노드 최대</th><th>지지</th></tr>
                </thead>
                <tbody>
                  {diag.shapes.map((sh) => {
                    const row = result.ranking.find((r) => r.id === sh.id);
                    const far = Math.max(0, ...sh.per_esl.map((p) => p.primary.far_frac ?? 0));
                    return (
                      <tr key={sh.id}>
                        <td>{sh.id} {nameOf(sh.id)}</td>
                        <td>{fx(row?.score, 3)}</td>
                        <td>{fx(sh.score_alt, 3)}</td>
                        <td>{pct(far)}</td>
                        <td>{!sh.supports ? "–" : sh.supports.mode === "transfer" ? "이전" : sh.supports.mode === "fallback" ? "자동(이전 실패)" : "자동"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            )}
          </>
        )}
      </details>
    </span>
  );
}

/** v0.23.2 3D 비교 하중 조건 한 줄(esl_v0232_fixes.md §4.4): 하중 · 지지 · 엔트리 */
export function v3dCondText(jigMode: boolean, nJig: number | null, eslNames: (string | null)[]): string {
  const names = [...new Set(eslNames.filter((x): x is string => !!x))];
  const ent = names.length === 0 ? "–" : names.length === 1 ? names[0] : `기준 ${eslNames[0] ?? "–"} · 안 ${eslNames[1] ?? "–"}`;
  return `하중: ${jigMode ? "지그 하중" : "전 노드 ESL 재풀이"} · 지지: ${jigMode ? `tie 고정(${nJig ?? "?"}점)` : "3-2-1"} · 엔트리: ${ent}`;
}

/** v0.23.3 지그 탭 3D 다시 만들기 버튼(esl_jig_view.md §3·§7.2) — available 일 때만, allowed 아니면 비활성 + 이유 */
function RegenButton({ studyId, result, onQueued }: { studyId: string; result: DoeResultOut; onQueued?: () => void }) {
  const rg = result.view3d_regen ?? null;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!rg?.available) return null;
  const why = rg.allowed ? null : rg.reason ?? "3D 를 다시 만들 수 없습니다";
  return (
    <span className="primary-wrap" title={why ?? "지그 응답 3D·지그 진단 3D·하중 정의 탭 자료만 다시 만듭니다(순위·결과 파일 그대로, 기존 작업 큐)"}>
      <button
        type="button"
        className="btn small"
        data-testid="v3d-regen"
        disabled={!!why || busy}
        aria-disabled={!!why || busy}
        onClick={async () => {
          setBusy(true);
          setErr(null);
          try {
            await doe.regenerateView3d(studyId);
            onQueued?.();
          } catch (e) {
            setErr(errorText(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        3D 다시 만들기
      </button>
      {err && <span className="small error-text"> {err}</span>}
    </span>
  );
}

/** v0.23.3 지그 진단 3D 보기 종류(목표·맞춤 | 오차 | 영역) */
type DiagView = "tf" | "err" | "reg";
const DIAG_VIEW_LABEL: Record<DiagView, string> = { tf: "목표·맞춤", err: "오차", reg: "영역" };
const fmt3 = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));

/** 진단 한 줄 문구·툴팁(순수 — 시험용) */
export function jigDiagText(e: DoeJigDiagEntryOut, d: DoeJigDiagOut): { line: string; title: string; coef: string } {
  const nm = e.mac_nomodes != null ? `(모드 제외 ${e.mac_nomodes.toFixed(3)})` : "";
  const line = `${e.label} · MAC ${e.mac.toFixed(3)}${nm} · umax 오차 ${(e.umax_err * 100).toFixed(1)} % · work_eff ${e.work_eff.toFixed(2)} · tie_rel ${e.tie_rel.toFixed(3)}`;
  const cb = (k: string) => (e.contrib[k] ?? 0).toFixed(2);
  const rname = (id: number) => {
    const g = d.regions.find((r) => r.id === id);
    return g?.part != null ? ` part ${g.part}${g.part_title ? ` ${g.part_title}` : ""}` : "";
  };
  const forces = e.forces.map((f) => `R${f.region + 1}(${f.kind === "contact" ? "접촉" : "패치"}${rname(f.region)}) ${fmt3(f.F_mag)} N`).join(", ");
  const groups = (d.tie_groups ?? []).map((g, i) => `${tieGroupName(g)} ${g.n_nodes}노드·클러스터 ${g.n_clusters}·지름 ≤ ${g.cluster_dmax_mm.toFixed(0)} mm${g.kinds.length ? `·${g.kinds.join("/")}` : ""} · tie_rel ${(e.tie_rel_groups?.[i] ?? 0).toFixed(3)}`);
  const title = [
    `지그 노드 기준 강체 회전 ${e.rot_deg.toFixed(2)}° · 지그 노드 ${d.n_jig}개 · tie_spread ${d.tie_spread == null ? "–" : d.tie_spread.toFixed(3)}`,
    `하중 영역 ${d.regions.length}개(접촉 ${d.n_contact} · 패치 ${d.n_patch})${forces ? ` — ${forces}` : ""}`,
    `맞춤 응답 기여(변위 노름 비): 영역 ${cb("region")} · 체적력 ${cb("body")} · 모드 ${cb("mode")}`,
    `목표 변형 에너지: 면외 ${(e.tgt_out_frac * 100).toFixed(0)} % · 면내 ${((1 - e.tgt_out_frac) * 100).toFixed(0)} %`,
    `umax 목표 ${e.umax_tgt.toFixed(2)} mm · 맞춤 ${e.umax_fit.toFixed(2)} mm · 오차 최대 ${e.err_max.toFixed(2)} mm`,
    e.umax_err_nomodes != null ? `모드 제외 umax 오차 ${(e.umax_err_nomodes * 100).toFixed(1)} %` : "",
    groups.length ? `체결(tie) 상대 부품별:\n  ${groups.join("\n  ")}` : "",
  ].filter(Boolean).join("\n");
  const body = e.body ? `체적력 (${e.body.map(fmt3).join(", ")}) N` : "체적력 없음";
  const modes = e.modes.length ? ` · 모드 ${e.modes.map((m) => `a${Number(m.k) + 1} ${fmt3(Number(m.a))}`).join(" ")} N` : "";
  return { line, title, coef: body + modes };
}

/** v0.23.3 지그 노드 상대 부품 그룹 색(§1.6 — 범례와 같은 순서, 모름 = 회색) */
export const TIE_GROUP_COLORS = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#1f78b4"];
export const tieGroupColor = (g: { other_part_id?: number | null }, i: number) => (g.other_part_id == null ? "#6b7280" : TIE_GROUP_COLORS[i % TIE_GROUP_COLORS.length]);
export const tieGroupName = (g: { other_part_id?: number | null; other_part_title?: string | null }) =>
  g.other_part_id == null ? "상대 부품 모름" : `part ${g.other_part_id}${g.other_part_title ? ` ${g.other_part_title}` : ""}`;

/** 영역 색 값(정점별): 접촉 = 0.62~1.0(진한 파랑), 패치 = 0.2~0.42(옅은 파랑), 영역 밖 = NaN(회색) */
export function regionField(n: number, regs: DoeJigRegionsFile["regions"]): Float32Array {
  const v = new Float32Array(n).fill(NaN);
  regs.forEach((g, i) => {
    const val = g.kind === "contact" ? 0.62 + 0.19 * (i % 3) : 0.2 + 0.11 * (i % 3);
    for (const k of g.vertices) if (k >= 0 && k < n) v[k] = val;
  });
  return v;
}

/** 영역 합력 화살표(기존 화살표 — 길이 ∝ |F|) */
export function regionArrows(e: DoeJigDiagEntryOut, d: DoeJigDiagOut, diag: number): ArrowSpec[] {
  const fref = e.forces.reduce((a, f) => Math.max(a, f.F_mag), 0);
  const out: ArrowSpec[] = [];
  for (const f of e.forces) {
    const g = d.regions.find((r) => r.id === f.region);
    if (!g || !(f.F_mag > 0)) continue;
    const a = buildArrow(`R${f.region + 1}`, "cluster", [g.center[0], g.center[1], g.center[2]], f.F, f.F_mag, fref, diag, null, `R${f.region + 1} ${f.kind === "contact" ? `접촉${g.part_title ? ` ${g.part_title}` : g.part != null ? ` part ${g.part}` : ""}` : "패치"} ${fmt3(f.F_mag)} N`);
    if (a) out.push(a);
  }
  return out;
}

function JigDiag({ studyId, result, lead, pick }: { studyId: string; result: DoeResultOut; lead: ReactNode; pick: string | null }) {
  const d = result.jig_diag ?? null;
  const ents = d?.entries ?? [];
  const def = (pick && result.view3d_jig_esl?.[pick]) || (pick && result.ranking.find((r) => r.id === pick)?.worst_entry_id) || ents[0]?.entry_id || null;
  const [chosen, setChosen] = useState<string | null>(null);
  const cur = ents.find((x) => x.entry_id === (chosen ?? def)) ?? ents[0] ?? null;
  const [view, setView] = useState<DiagView>("tf");
  const left = useDoeView(studyId, cur ? (view === "err" ? cur.dirs.err : view === "reg" ? cur.dirs.fit : cur.dirs.tgt) : null);
  const right = useDoeView(studyId, cur ? cur.dirs.fit : null);
  const [regs, setRegs] = useState<DoeJigRegionsFile | null>(null);
  const fitDir = cur?.dirs.fit ?? null;
  useEffect(() => {
    setRegs(null);
    if (!fitDir) return;
    let alive = true;
    doe.jigRegions(studyId, fitDir).then((r) => alive && setRegs(r)).catch(() => alive && setRegs(null));
    return () => {
      alive = false;
    };
  }, [studyId, fitDir]);
  const [ds, setDs] = useState<{ on: boolean; kexp: number | null; real: boolean }>({ on: false, kexp: null, real: false });
  const sync = { ...ds, set: (p: Partial<typeof ds>) => setDs((x) => ({ ...x, ...p })) };
  const [manual, setManual] = useState<Range | null>(null);
  const [manualErr, setManualErr] = useState<Range | null>(null);
  if (!d || !cur) return <Empty>지그 진단 3D 가 없습니다{result.view3d_regen?.available ? " — [3D 다시 만들기]로 만드세요" : ""}</Empty>;
  const txt = jigDiagText(cur, d);
  const th = result.jig?.th;
  const poor = !!th && (cur.mac < th.mac_min || cur.umax_err > th.umax_err_max);
  // 목표·맞춤·영역 = 두 그림 같은 범위(목표·맞춤 u_max 중 큰 값). 오차 보기 = 오차 그림은 err manifest 자체 범위(목표·맞춤과 안 섞음), 맞춤 그림은 맞춤 자체 범위(계약 §7.2)
  const errView = view === "err";
  const umax = errView
    ? Math.max(cur.umax_fit, right?.manifest?.ranges.u_max ?? 0)
    : Math.max(cur.umax_tgt, cur.umax_fit, left?.manifest?.ranges.u_max ?? 0, right?.manifest?.ranges.u_max ?? 0);
  const range: Range | null = manual ?? (umax > 0 ? { min: 0, max: umax } : null);
  const errMax = left?.manifest?.ranges.u_max ?? 0;
  const rangeErr: Range | null = manualErr ?? (errMax > 0 ? { min: 0, max: errMax } : null);
  const arrows = right?.manifest ? regionArrows(cur, d, right.manifest.bbox.diag) : null;
  const n = right?.manifest?.n_nodes ?? 0;
  const fo = view === "reg" && regs && n ? { values: regionField(n, regs.regions), min: 0, max: 1, label: "하중 영역 — 진한 파랑 접촉 · 옅은 파랑 패치 · 회색 영역 밖" } : null;
  const tgs = d.tie_groups ?? [];
  const vg = new Map<number, number>((regs?.jig_vertices ?? []).map((v, i) => [v, regs?.jig_groups?.[i] ?? -1]));
  const supportColor = (v: number) => {
    const g = vg.get(v);
    return g == null || g < 0 || !tgs[g] ? null : tieGroupColor(tgs[g], g);
  };
  const opts = (title: string, extra: Partial<View3DOptions> = {}) => ({ title, colorBy: "disp" as const, range, rangeManual: !!manual, onRangeChange: setManual, deformSync: sync, supportColor, ...extra });
  return (
    <div className="doe-compare" data-testid="jig-diag">
      <div className="inline-actions">
        {lead}
        <select className="select small" aria-label="지그 진단 엔트리" data-testid="jig-diag-entry" value={cur.entry_id} onChange={(e) => setChosen(e.target.value)}>
          {ents.map((x) => (
            <option key={x.entry_id} value={x.entry_id}>
              {x.label}
            </option>
          ))}
        </select>
        <div className="seg" role="group" aria-label="지그 진단 보기" data-testid="jig-diag-view">
          {(Object.keys(DIAG_VIEW_LABEL) as DiagView[]).map((k) => (
            <button key={k} type="button" className={view === k ? "on" : ""} aria-pressed={view === k} data-view={k} onClick={() => setView(k)}>
              {DIAG_VIEW_LABEL[k]}
            </button>
          ))}
        </div>
        <span className={`small${poor ? " warn-text" : ""}`} data-testid="jig-diag-line" title={txt.title} style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
          {txt.line}
        </span>
        {/* 계수·tie 범례 = 한 줄(넘치면 말줄임, 전체 = title) — 3D 머리 2줄 유지(설계 비교와 같은 높이) */}
        <span style={{ display: "flex", gap: 12, flex: "1 1 100%", minWidth: 0, overflow: "hidden", whiteSpace: "nowrap" }}>
        <span className="small muted" data-testid="jig-diag-coef" title={txt.title} style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
          {txt.coef}
        </span>
        {tgs.length > 0 && (
          <span className="small" data-testid="jig-tie-legend" title={txt.title} style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            tie:{" "}
            {tgs.slice(0, 5).map((g, i) => (
              <span key={i} style={{ color: tieGroupColor(g, i), marginRight: 6 }} data-testid="jig-tie-group">
                ▲ {tieGroupName(g)} ({g.n_nodes})
              </span>
            ))}
            {tgs.length > 5 ? `+${tgs.length - 5}` : ""}
          </span>
        )}
        </span>
      </div>
      <div className="doe-compare-grid">
        {left && (
          <View3DCard
            view={left}
            options={
              view === "tf"
                ? opts(`목표 u_tgt · ${cur.label} — 지그 노드 기준 강체 제거한 낙하 변형`, { dispLabel: "목표 변위 |u_tgt| (mm)" })
                : view === "err"
                  ? opts(`오차 |u_fit − u_tgt| · ${cur.label}`, { dispLabel: "오차 |u_fit − u_tgt| (mm)", range: rangeErr, rangeManual: !!manualErr, onRangeChange: setManualErr })
                  : opts(`하중 영역 · ${cur.label}`, { fieldOverride: fo, arrowsOverride: arrows })
            }
          />
        )}
        {right && <View3DCard view={right} options={opts(`지그 맞춤 응답 u_fit · ${cur.label}`, { dispLabel: "맞춤 변위 |u_fit| (mm) — tie 고정", arrowsOverride: arrows })} />}
      </div>
    </div>
  );
}

function Compare3D({ studyId, result, pick, setPick, kind = null, onRegen }: { studyId: string; result: DoeResultOut; pick: string | null; setPick: (id: string) => void; kind?: View3dKind | null; onRegen?: () => void }) {
  const others = result.view3d.filter((d) => d !== "d000");
  // ④ 형상 비교: 라벨 = 기준 이름 vs 선택 형상 이름
  const named = result.scenario === "compare" || result.ranking.some((r) => !!r.shape);
  const nameOf = (d: string) => result.ranking.find((r) => r.id === d)?.shape?.name ?? null;
  const did = pick && others.includes(pick) ? pick : others[0] ?? null;
  // v0.23.3 하중 정의 탭(D-0.23.3-4): 지그 탭 = [설계 비교(지그 응답) | 지그 진단], 전 노드 탭 = 기존 전 노드 ESL 컨투어(v0.23.2 토글 제거)
  const jigTab = kind === "jig";                 // 출처 표 열 view3d(출처 이름 아님)
  const jigDir = did ? result.view3d_jig?.[did] ?? null : null;
  const jigEsl = did ? result.view3d_jig_esl?.[did] ?? null : null;
  const jigRef = jigEsl ? result.view3d_jig_ref?.[jigEsl] ?? null : null;
  const jigAvail = jigTab && !!jigDir && !!jigRef;
  const [jmode, setJmode] = useState<"design" | "diag">("design");
  const jigMode = jigAvail && jmode === "design";
  // v0.20.0(LT-9): 좌측 = 선택 형상 최악 ESL 의 기준 view3d_ref, 없으면(legacy) d000
  const eslId = did ? result.view3d_esl?.[did] ?? null : null;
  const refId = eslId ? result.view3d_ref?.[eslId] ?? null : null;
  const labelOf = (e: string | null | undefined) => (e ? result.esl?.find((x) => x.entry_id === e)?.label ?? e.slice(0, 8) : null);
  const eslLabel = jigMode ? labelOf(jigEsl) : refId && eslId ? labelOf(eslId) : null;
  const showFull = !jigTab;
  const base = useDoeView(studyId, jigMode ? jigRef : showFull ? refId ?? (result.view3d.includes("d000") ? "d000" : null) : null);
  const cand = useDoeView(studyId, jigMode ? jigDir : showFull ? did : null);
  const [manual, setManual] = useState<Range | null>(null);
  const autoMax = Math.max(base?.manifest?.ranges.u_max ?? 0, cand?.manifest?.ranges.u_max ?? 0);
  const range: Range | null = manual ?? (autoMax > 0 ? { min: 0, max: autoMax } : null);
  const linMode = isLinResult(result) || isCrossMesh(result) || result.rank?.metric_effective != null; // 새 스냅샷 3D = 강체 제거(주 지표 무관)
  const dispLabel = jigMode ? "변위 |u| (mm) — 지그 고정(강체 성분 없음)" : linMode ? "변위 |u| (mm) — 강체 제거" : null;
  const opts = (title: string) => ({ title, colorBy: "disp" as const, range, rangeManual: !!manual, onRangeChange: setManual, ...(dispLabel ? { dispLabel } : {}) });
  if (!others.length && !jigTab) return <Empty>3D 비교 자료가 없습니다</Empty>;
  const cond = v3dCondText(jigMode, result.jig?.n_jig ?? null, [labelOf(base?.manifest?.esl_run_id), labelOf(cand?.manifest?.esl_run_id)]);
  const modeSeg = jigTab ? (
    <div className="seg" role="group" aria-label="지그 3D 보기" data-testid="v3d-jig-mode">
      {([["design", "설계 비교"], ["diag", "지그 진단"]] as const).map(([k, l]) => (
        <button key={k} type="button" className={jmode === k ? "on" : ""} aria-pressed={jmode === k} data-mode={k} onClick={() => setJmode(k)}>
          {l}
        </button>
      ))}
    </div>
  ) : null;
  // 다시 만들기 필요: 지그 탭 = 진단·보기·선택 안 지그 응답 중 하나 없음, 그 밖 탭 = 사이드카(rank_views) 없음 → 탭이 비활성이어도 눌러 만들 수 있게 활성 탭과 무관(§7.2)
  const needRegen = jigTab ? !result.jig_diag || !result.rank_views || (!!did && !jigDir) : !result.rank_views;
  const regen = needRegen ? <RegenButton studyId={studyId} result={result} onQueued={onRegen} /> : null;
  if (jigTab && jmode === "diag")
    return (
      <JigDiag
        studyId={studyId}
        result={result}
        pick={did}
        lead={
          <>
            {modeSeg}
            {regen}
          </>
        }
      />
    );
  return (
    <div className="doe-compare">
      <div className="inline-actions">
        <span className="small muted">{named ? "비교 형상" : "비교 안"}</span>
        <select aria-label="3D 비교 안" value={did ?? ""} onChange={(e) => setPick(e.target.value)}>
          {others.map((d) => (
            <option key={d} value={d}>
              {d}
              {nameOf(d) ? ` ${nameOf(d)}` : ""}
              {result.ranking.find((r) => r.id === d) ? ` · ${result.ranking.find((r) => r.id === d)!.rank}위` : ""}
            </option>
          ))}
        </select>
        {modeSeg}
        {regen}
        {(!jigTab || jigMode) && <span className="small" data-testid="v3d-cond">{cond}</span>}
        <span className="small muted">{(() => {
          if (jigTab && !jigMode) return "";
          if (jigMode) return `색 = 변위 |u| · ESL ${eslLabel ?? "–"}(지그 기준 최악), 두 그림 같은 지그·같은 하중·같은 범위`;
          const base = eslLabel ? `색 = 변위 |u| · ESL ${eslLabel}(선택 형상의 최악), 두 그림 같은 범위` : "색 = 변위 |u|(최악 ESL), 두 그림 같은 범위";
          return linMode ? `${base} · 강체 제거, 해석값(순위와 무관)` : base;
        })()}</span>
      </div>
      {jigTab && !jigAvail ? (
        <Empty>지그 응답 3D 가 없습니다{result.view3d_regen?.available ? " — [3D 다시 만들기]로 만드세요" : ""}</Empty>
      ) : (
        <div className="doe-compare-grid">
          {base && <View3DCard view={base} options={opts(`${named ? `기준: ${result.baseline.shape?.name ?? "d000"}` : "베이스라인 d000"}${eslLabel ? ` · ESL ${eslLabel}` : ""}`)} />}
          {cand && <View3DCard view={cand} options={opts(`${named ? `${did} ${nameOf(did ?? "") ?? ""}`.trim() : `안 ${did}`}${eslLabel ? ` · ESL ${eslLabel}` : ""}`)} />}
        </div>
      )}
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

// ================================================================ v0.22.0 재낙하 입력 받기(esl_redrop_bundle.md §7)
export const REDROP_LABEL = "재낙하 입력 받기";
const REDROP_TITLE = "선택한 안의 모핑 좌표를 선택한 엔트리의 원 낙하 입력(rad·include)에 넣은 zip — 받아서 HPC 에 직접 제출";
/** 기본 선택 = is_base 엔트리, 불가면 첫 ok 엔트리(없으면 null) */
export function redropDefault(entries: RedropEntryOut[] | null | undefined): string | null {
  const list = entries ?? [];
  return (list.find((e) => e.is_base && e.ok) ?? list.find((e) => e.ok))?.entry_id ?? null;
}
/** 엔트리 선택칸 1개 + 버튼 1개. 판정은 서버 플래그(redrop_ok·entries[].ok)만 — 시나리오 분기 없음 */
function RedropControl({ study, pick }: { study: DoeStudyOut; pick: string | null }) {
  const entries = study.redrop_entries ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const def = redropDefault(entries);
  const cur = chosen && entries.some((e) => e.entry_id === chosen) ? chosen : def;
  const ent = entries.find((e) => e.entry_id === cur) ?? null;
  const reason = !study.redrop_ok
    ? study.redrop_blocked ?? "재낙하 입력을 만들 수 없습니다"
    : entries.length === 0
      ? "재낙하 입력을 만들 수 있는 엔트리가 없습니다"
      : !pick
        ? "순위표에서 안을 고르세요"
        : !ent || !ent.ok
          ? ent?.blocked ?? "재낙하 입력을 만들 수 있는 엔트리가 없습니다"
          : null;
  return (
    <span className="redrop" data-testid="redrop">
      {entries.length > 0 && (
        <select className="select small" style={{ marginRight: 6 }} aria-label="재낙하 엔트리" data-testid="redrop-entry" value={cur ?? ""} onChange={(e) => setChosen(e.target.value)}>
          {cur === null && <option value="" disabled>—</option>}
          {entries.map((e) => (
            <option key={e.entry_id} value={e.entry_id} disabled={!e.ok} title={e.blocked ?? undefined}>
              {e.label}
              {e.is_base ? " (기준)" : ""}
            </option>
          ))}
        </select>
      )}
      {reason || !pick || !cur ? (
        <span className="primary-wrap" title={reason ?? undefined}>
          <button type="button" className="btn small" disabled aria-disabled="true" data-testid="redrop-btn">
            {REDROP_LABEL}
          </button>
          {reason && <span className="sr-only">{reason}</span>}
        </span>
      ) : (
        <span data-testid="redrop-btn">
          <BundleButton key={`${pick}|${cur}`} url={doe.redropUrl(study.id, pick, cur)} filename={`redrop_${pick}_${cur.slice(0, 8)}.zip`} label={REDROP_LABEL} title={REDROP_TITLE} />
        </span>
      )}
    </span>
  );
}

/** v0.23.1 "스터디 받기" 묶음(esl_doe_ui_tidy.md §5) — 결과 카드 머리. [결과 받기(zip)] [순위 CSV] [파일 ▾ = 최적 안 파일 링크] */
function Downloads({ study, result }: { study: DoeStudyOut; result: DoeResultOut }) {
  const files = result.best?.files ?? [];
  const mesh = files.filter((f) => /\.(inc|rad|fem)$/i.test(f.rel));
  const geom = files.filter((f) => /\.(brep|step|stp)$/i.test(f.rel));
  const name = (rel: string) => rel.split("/").pop() ?? rel;
  const best = result.best ? `최적 ${result.best.id}` : null;
  return (
    <span className="inline-actions doe-dl" data-testid="doe-downloads">
      <BundleButton url={doe.bundleUrl(study.id)} filename={`doe_${study.id}.zip`} />
      <DownloadLink id={study.id} rel="post/ranking.csv" label="순위 CSV" />
      {mesh.length + geom.length > 0 ? (
        <details className="doe-files-menu" data-testid="doe-files-menu">
          <summary className="btn small">파일 ▾</summary>
          <div className="doe-files-pop inline-actions">
            {best && <span className="small muted">받기 · {best}</span>}
            {mesh.map((f) => (
              <DownloadLink key={f.rel} id={study.id} rel={f.rel} label={`${study.scenario === "step" || study.scenario === "compare" || study.inputs.select_base === "step" ? "메시" : "include"} ${name(f.rel)}`} />
            ))}
            {geom.map((f) => (
              <DownloadLink key={f.rel} id={study.id} rel={f.rel} label={name(f.rel).split(".").pop()!.toUpperCase()} />
            ))}
          </div>
        </details>
      ) : (
        best && <span className="small muted">받기 · {best}</span>
      )}
    </span>
  );
}

// ================================================================ v0.12.0 검증 낙하(esl_scx_relay.md §10.2)
/** [검증 낙하] 버튼·대화상자·카드 상태. 버튼 활성 = ① 같은 모델 · DONE · SCX 검증 사용 가능 · 고른 안이 best/ 가 남은 안(순위 1~keep_files_top) */
function useVerifyDrop(projectId: string, study: DoeStudyOut | null, result: DoeResultOut | null, pick: string | null, allowed: boolean, isAdmin: boolean) {
  const done = study?.phase === "DONE";
  // v0.16.2: ② B 메시 기준 select 는 다른 모델 — 검증 낙하 대상 아님(① 만)
  const same = study?.scenario === "same" || (study?.scenario === "select" && study.inputs.select_base !== "mesh" && study.inputs.select_base !== "step");
  const sid = study?.id ?? "";
  const status = usePolling(() => (done && same ? scx.status(projectId) : Promise.resolve(null)), 0, [projectId, done, same]);
  const avail = status.data?.verify ?? null;
  const best = result?.best?.id ?? null;
  const [plan, setPlan] = useState<VerifyPlanOut | null>(null);
  const [planError, setPlanError] = useState<{ code: string; message: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  // 안 목록·기본 N·누적 씬 판정: 최적 안 worst 기본으로 계획 1회(저장 안 함)
  useEffect(() => {
    setPlan(null);
    setPlanError(null);
    if (!done || !same || !avail?.enabled || !best || !allowed) return;
    let alive = true;
    verify
      .plan({ bead_doe_id: sid, design_id: best, mode: "worst" })
      .then((p) => alive && setPlan(p))
      .catch((e) => alive && setPlanError(e instanceof ApiError ? { code: e.code, message: e.message } : { code: "ERROR", message: errorText(e) }));
    return () => {
      alive = false;
    };
  }, [sid, done, same, avail?.enabled, best, allowed, nonce]);
  const [poll, setPoll] = useState(0);
  const list = usePolling(() => (done ? verify.list(sid) : Promise.resolve([] as VerifyDropOut[])), poll, [sid, done]);
  const [drops, setDrops] = useState<VerifyDropOut[]>([]);
  useEffect(() => {
    if (!list.data) return;
    setDrops(list.data);
    setPoll(list.data.some(isActiveDrop) ? 4000 : 0);
  }, [list.data]);
  const designs = eligibleDesigns(result, plan);
  const reason = verifyButtonReason({
    allowed, noPermission: NO_PERMISSION, study, result, avail, availError: status.error, designs, pick, planError, isAdmin,
  });
  const initialDesign = pick && designs.some((d) => d.id === pick) ? pick : designs[0]?.id ?? best ?? "";
  const reload = () => {
    void list.reload();
    setNonce((n) => n + 1);
  };
  return { reason, designs, initialDesign, plan, drops, reload, listError: list.error };
}

// ================================================================ v0.15.0 ④ 변수 · ⑤ 평면도 + 단면(select)
/** v0.15.1 변수 표 옆 고정 경고(SELECT_FIXED_IN_BEAD·SELECT_FIXED_IN_BLEND — 전에는 비드 목록 ⚠ 툴팁에만) */
const FIXED_WARN = ["SELECT_FIXED_IN_BEAD", "SELECT_FIXED_IN_BLEND"];
function FixedWarnings({ pd, storeKey }: { pd: { beads: { id: string; name?: string | null; warnings?: { code: string; message?: string | null }[] | null }[] }; storeKey?: string }) {
  const ws = pd.beads.flatMap((b) => (b.warnings ?? []).filter((w) => FIXED_WARN.includes(w.code)).map((w) => ({ b, w })));
  if (!ws.length) return null;
  // v0.17.1 요약 1줄(기본 접힘)
  return <MsgFold items={ws.map(({ b, w }) => ({ text: `${b.name || b.id.toUpperCase()}: ${warnText(w)}` }))} storeKey={storeKey} testId="vars-fixed-warn" />;
}

/** select 변수 0개 사유: 비드·전체 경고 문구(없으면 일반 안내) */
export function noVarsReason(pd: { beads: { id: string; name?: string | null; warnings?: { code: string; message?: string | null }[] | null }[]; warnings: { code: string; message?: string | null }[] }): string {
  const ws = [
    ...pd.beads.flatMap((b) => (b.warnings ?? []).map((w) => `${b.name || b.id.toUpperCase()}: ${warnText(w)}`)),
    ...pd.warnings.map((w) => warnText(w)),
  ];
  return ws.length ? [...new Set(ws)].join(" · ") : "비드의 바닥·사면을 다시 고르고 [사면·경계 자동] 로 공칭 깊이·폭을 확인한 뒤 다시 저장하세요";
}

function SelectVarsPlan(p: {
  ready: boolean;
  pd: import("../../api/types").DoeParamsOut | null;
  rows: ParamRow[] | null;
  setRows: (r: ParamRow[]) => void;
  form: SpecForm | null;
  setForm: (f: SpecForm) => void;
  st: DoeSettingsOut | null;
  matrix: DoeMatrixOut | null;
  matrixError: string | null;
  editable: boolean;
  plan: import("../../api/types").DoePlanOut | null;
  planError: string | null;
  ctrl: ReturnType<typeof useBeadSelect>;
  activeVar: string | null;
  setActiveVar: (v: string) => void;
  /** v0.16.2 ② B 메시 기준(경계 경고·A 체결·하중 층) */
  meshBase: boolean;
  /** v0.18.0 ③ STEP 기준(② 경계 층 + A 고정 이전 표시 + 주 시트 영역) */
  stepBase?: boolean;
  nWarn: number | null;
  beadPngUrl: (b: string) => string;
  /** v0.17.1 접기 상태 키(스터디 id) */
  foldKey?: string;
  /** v0.21.0 스터디 스냅샷 형상 규칙(없으면 v0.20.0 화면) */
  shapeRules?: import("../../api/types").DoeShapeRules | null;
  /** v0.23.1 단계 초점 접기(esl_doe_ui_tidy.md §2) */
  fold4?: CardFold | null;
  fold5?: CardFold | null;
}) {
  const { pd, rows, form, st, plan } = p;
  const params = pd?.params ?? [];
  const av = params.find((x) => x.name === p.activeVar) ?? null;
  const row = av ? rows?.find((r) => r.name === av.name) : null;
  const planVar: PlanVar | null = av && (av.type === "D" || av.type === "W")
    ? { name: av.name, type: av.type, bead: av.bead, tier: av.tier ?? null, nominal: av.nominal, lo: Number(row?.lo ?? av.default_range[0]), hi: Number(row?.hi ?? av.default_range[1]) }
    : null;
  const secBead = av?.bead ?? pd?.beads[0]?.id ?? null;
  const chips = Object.fromEntries(
    (pd?.beads ?? []).map((b) => [
      b.id,
      [b.id.toUpperCase(), ...params.filter((x) => x.bead === b.id).map((x) => `${x.type === "D" ? `D${x.tier ?? ""}` : "W"} ${x.nominal.toFixed(1)}`)].join(" · "),
    ]),
  );
  const mesh = useMemo(() => selectMesh(p.ctrl.data), [p.ctrl.data]);
  const c = p.ctrl;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const scene = useMemo(() => (mesh ? selectScene(c, mesh, null) : null), [mesh, c.tick, c.state, c.graph, c.editV, c.colorMode, c.islandMask, c.graphMode]);
  const view = plan ? selectViewData({ plan, chips, active: planVar, meshBase: p.meshBase, stepBase: p.stepBase, st, nWarn: p.nWarn, scene, sceneLayers: sceneLayers(p.ctrl) }) : null;
  return (
    <div className="doe-grid">
      <Card title="④ 변수" fold={p.fold4} right={<DoeMethodInfo src={st?.method_sources} method={form?.method} />}>
        {!p.ready ? (
          <div className="empty small" data-testid="vars-next">
            {p.ctrl.state?.beads.length ? "비드를 고르고 [사면·경계 자동] → [선택 저장] 하면 변수 표가 나옵니다" : "[+ 비드] → 바닥 클릭 → [사면·경계 자동] → [선택 저장] 하면 변수 표가 나옵니다"}
          </div>
        ) : pd && !pd.params.length ? (
          <BlockErr title="변수가 없습니다" detail={noVarsReason(pd)} testId="vars-empty" />
        ) : pd && rows && form && st ? (
          <>
            <FixedWarnings pd={pd} storeKey={p.foldKey ? `${p.foldKey}:fixed` : undefined} />
            <DoeParamTable
              data={pd}
              rows={rows}
              setRows={p.setRows}
              readOnly={!p.editable}
              beadPngUrl={p.beadPngUrl}
              shapeRules={p.shapeRules}
              select={{ blendOf: p.ctrl.blendOf, setBlend: p.ctrl.setBlend, kBlend: st.select?.blend.k ?? null, blendMax: st.select?.blend.max_mm ?? 200, active: p.activeVar, onActive: p.setActiveVar }}
            />
            <DoeSpecRow st={st} form={form} setForm={p.setForm} matrix={p.matrix} matrixError={p.matrixError} readOnly={!p.editable} k={rows.filter((r) => r.on).length} />
          </>
        ) : (
          <Empty>{p.planError ?? "불러오는 중…"}</Empty>
        )}
      </Card>
      <Card title="⑤ 평면도 · 단면" fold={p.fold5}>
        {!p.ready ? (
          <Empty>비드 선택을 저장하면 평면도가 열립니다</Empty>
        ) : view ? (
          <PartView
            data={view}
            testId="pv-select"
            side={
              <>
                {secBead && <SectionMini sec={plan!.beads.find((b) => b.id === secBead)?.section} v={planVar && planVar.bead === secBead ? planVar : null} title={(pd?.beads.find((b) => b.id === secBead)?.name ?? secBead).toString()} />}
                <div className="small muted">{av ? `${av.name} 범위를 그림에 표시(폭 = 최소·최대 윤곽 점선, 깊이 = 단면 점선)` : "변수 행을 고르면 범위를 그림에 표시합니다"}</div>
              </>
            }
          />
        ) : (
          <Empty>{p.planError ?? "불러오는 중…"}</Empty>
        )}
      </Card>
    </div>
  );
}

/** v0.17.3 이전 방식(same·mesh·step) 3D: 실행 뒤 결과 d000(기준 형상) — 준비 단계에는 3D 형상 파일이 없어 평면도만(VU-F-1) */
function useD000Mesh(studyId: string, on: boolean): PartMesh | null {
  const [mesh, setMesh] = useState<PartMesh | null>(null);
  useEffect(() => {
    setMesh(null);
    if (!on) return;
    let alive = true;
    request<View3dOut>("GET", doe.view3dPath(studyId, "d000"))
      .then((m) => fetchBinary(fileUrls(m).geometry))
      .then((b) => {
        const g = parseGlb(b);
        if (alive) setMesh({ positions: g.positions, indices: g.indices });
      })
      .catch(() => undefined); // 3D 없음 = 평면도만(오류 아님)
    return () => {
      alive = false;
    };
  }, [studyId, on]);
  return mesh;
}

// ================================================================ 상세
function StudyDetail({ projectId, id, st, stError }: { projectId: string; id: string; st: DoeSettingsOut | null; stError: string | null }) {
  const nav = useNavigate();
  const { me } = useApp();
  const allowed = canRun(me, projectId);
  const [poll, setPoll] = useState(3000);
  const study = usePolling(() => doe.study(id).catch(goneToList(nav, `/p/${projectId}/library?tab=study`)), poll, [id]);
  const s = study.data;
  const phase = s?.phase ?? null;
  const prepDone = !!s?.prep && phase !== "PREP";
  const isCompare = s?.scenario === "compare";
  const isSelect = s?.scenario === "select";
  /** ②③④ 카드(비드·평면도·미리보기) — ④ 형상 비교는 없음 */
  const beadPrep = prepDone && !!s && !isCompare;
  // v0.15.0 비드 직접 선택: 저장 선택(sha)이 있어야 변수·평면도(409 SELECTION_MISSING)
  // 기준 메시가 바뀌어 저장 선택이 무효면 서버가 409 SELECTION_MISSING(reason SELECTION_DROPPED) — 선택 없음으로 보고 다시 고르게 한다
  const [selDropped, setSelDropped] = useState(false);
  const rawSha = s?.selection?.sha256 ?? null;
  // 응답에 요청 당시 요약 sha 를 붙인다 — 저장 직후(요약 sha 가 막 생김) 아직 남아 있는 이전 응답({v: null})을 '무효 선택'으로 오판하지 않게(v0.15.1)
  const selFull = usePolling(() => (isSelect && prepDone ? doe.selection(id).then((v) => ({ v, sha: rawSha })) : Promise.resolve(null)), 0, [id, isSelect, prepDone, rawSha]);
  useEffect(() => setSelDropped(false), [rawSha]);
  useEffect(() => {
    // 요약은 있는데 (그 요약 sha 로 요청한) GET selection 이 null = 무효 선택(기준 메시 바뀜)
    if (isSelect && rawSha && selFull.data && selFull.data.sha === rawSha && selFull.data.v === null) setSelDropped(true);
  }, [isSelect, rawSha, selFull.data]);
  const selSha = selDropped ? null : rawSha;
  // v0.16.2 자동 탐지 seed(esl_bead_auto.md AD-D-4): auto 스터디는 GET …/select/auto 를 기본 상태로(404·빈 seed = 직접 선택 도구로)
  const isAuto = !!isSelect && s?.inputs.bead_source === "auto";
  const meshBaseSel = !!isSelect && s?.inputs.select_base === "mesh";
  /** v0.18.0 ③ STEP 기준 select — seed 는 bead_source 와 무관(manual = 빈 비드 + A 고정 이전, SG-D-16) */
  const stepBaseSel = !!isSelect && s?.inputs.select_base === "step";
  const seedOn = isAuto || stepBaseSel;
  const autoSeed = usePolling(() => (seedOn && prepDone ? loadSelectAuto(id) : Promise.resolve(null)), 0, [id, seedOn, prepDone]);
  const seedSel = !seedOn ? null : autoSeed.data ? autoSeed.data.seed?.selection ?? null : autoSeed.error ? null : undefined;
  const ctrl = useBeadSelect(id, !!isSelect && prepDone, selDropped ? null : selFull.data?.v ?? null, st, seedSel, { schema: s?.inputs.select_schema ?? null, prepWarnings: s?.prep?.warnings ?? null });
  const varsReady = beadPrep && (!isSelect || !!selSha);
  /** select 변수·평면도: 409 SELECTION_MISSING 은 오류 대신 '선택 없음'(SELECTION_DROPPED 면 안내) */
  const selGuard = <T,>(p: Promise<T>): Promise<T | null> =>
    p.catch((e) => {
      if (isSelect && e instanceof ApiError && e.code === "SELECTION_MISSING") {
        if (e.detail.reason === "SELECTION_DROPPED") setSelDropped(true);
        return null;
      }
      throw e;
    });
  useEffect(() => {
    if (s) setPoll(ACTIVE_PHASE.includes(s.phase) ? 3000 : 0);
  }, [s]);
  const all = usePolling(() => api.libraryEntries({ project_id: projectId }), 0, [projectId]);
  const params = usePolling(() => (varsReady ? selGuard(doe.params(id)) : Promise.resolve(null)), 0, [id, varsReady, selSha]);
  const plan = usePolling(() => (varsReady ? selGuard(doe.planView(id)) : Promise.resolve(null)), 0, [id, varsReady, selSha]);
  const done = phase === "DONE";
  const result = usePolling(() => (done ? doe.results(id) : Promise.resolve(null)), 0, [id, done]);
  // v0.23.3 하중 정의 탭(D-0.23.3-4): 기본 = metric_effective, 탭마다 투영 결과만 화면에
  const tabs = useMemo(() => (result.data && !isCompare ? tabState(result.data, LOAD_SOURCES) : null), [result.data, isCompare]);
  const [ltab, setLtab] = useState<LoadTab | null>(null);
  const curTab: LoadTab = tabs ? (ltab && tabs.ok[ltab] ? ltab : tabs.def ?? "") : "";
  const curSrc = tabs && curTab ? sourceOf(curTab, LOAD_SOURCES) : null;
  const tabR = useMemo(() => (result.data ? (curSrc ? tabResult(result.data, curTab, LOAD_SOURCES) : result.data) : null), [result.data, curSrc, curTab]);
  /** 불가 출처의 첫 칩(사유 — v0.23.2 지그 미계산·불가 칩 유지)을 현재 탭 띠 앞에(원 결과로). 탭 없음(curSrc null) = 띠 기본 칩 전부 */
  const reasonChips = tabs && curSrc && result.data
    ? LOAD_SOURCES.filter((x) => !tabs.ok[x.key] && x.chips.length).map((x) => <StatusChipOnly key={x.key} result={result.data!} kind={x.chips[0]} />)
    : null;

  const [rows, setRows] = useState<ParamRow[] | null>(null);
  const [form, setForm] = useState<SpecForm | null>(null);
  const [matrix, setMatrix] = useState<DoeMatrixOut | null>(null);
  const [matrixError, setMatrixError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [vdOpen, setVdOpen] = useState(false);
  const [activeVar, setActiveVar] = useState<string | null>(null);
  const [openDid, setOpenDid] = useState<string | null>(null);
  // 선택이 바뀌면(새 rev) 변수 이름·공칭이 바뀔 수 있어 표를 다시 만든다
  const prevSha = useRef(selSha);
  useEffect(() => {
    if (prevSha.current !== selSha) {
      prevSha.current = selSha;
      setRows(null);
    }
  }, [selSha]);

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
  /** select: 미리보기 뒤 선택이 바뀜(저장된 sha 다름 또는 화면 편집) — BS-D-3 */
  const selStale = !!isSelect && !!pv && ((!!pv.selection_sha256 && pv.selection_sha256 !== selSha) || ctrl.dirty);
  const fresh = !!pv && !!matrix && pv.matrix_sha256 === matrix.matrix_sha256 && s?.doe?.matrix_sha256 === matrix.matrix_sha256 && !selStale;
  const hasPreview = !!pv || phase === "PREVIEW";

  function previewReason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !s) return "불러오는 중…";
    const b = doeBlockedReason(st, s.scenario);
    if (b) return b;
    if (phase === "PREVIEW") return "미리보기 진행 중…";
    if (!editable) return phase === "PREP" ? "입력 준비 중…" : "이미 실행했습니다 — 복제해서 새 연구로";
    if (isSelect && !selSha) return "비드 선택을 먼저 저장하세요";
    if (isSelect && ctrl.dirty) return "저장 안 한 선택 변경이 있습니다 — 먼저 '선택 저장'";
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
    if (selStale) return "비드 선택이 미리보기 뒤에 바뀌었습니다 — 미리보기를 다시 실행하세요";
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
  /** ④ 비교 실행(SC-D-1: matrix 없이 READY → RUN) */
  function compareRunReason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !s) return "불러오는 중…";
    const b = doeBlockedReason(st, "compare") ?? scenarioBlocked(st, "compare");
    if (b) return b;
    if (phase !== "READY") return "이미 실행했습니다 — 복제해서 새 연구로";
    // 기준 외 준비된 형상 수(prep.shapes 가 없으면 서버 판정에 맡김)
    const others = s.prep?.shapes ? s.prep.shapes.filter((x) => !x.reference && x.status === "READY").length : 1;
    if (others < 1) return "비교할 수 있는 형상이 없습니다(준비 실패) — 형상 표의 사유를 확인하고 복제해 다시";
    return null;
  }
  async function runCompare() {
    setBusy(true);
    setError(null);
    try {
      const r = await doe.runCompare(id, version);
      study.setData(r);
      setPoll(3000);
    } catch (e) {
      setError(compareErrorText(e));
    } finally {
      setBusy(false);
    }
  }
  /** select: [선택 저장](PUT …/selection — 서버 재계산·검증 후 rev+1) */
  function saveReason(): string | null {
    if (!allowed) return NO_PERMISSION;
    if (!st || !s) return "불러오는 중…";
    const b = doeBlockedReason(st, "select");
    if (b) return b;
    if (phase === "PREVIEW") return "미리보기 진행 중…";
    if (!editable) return "이미 실행했습니다 — 복제해서 새 연구로";
    if (ctrl.problem) return ctrl.problem;
    if (!ctrl.dirty && selSha) return "바뀐 선택이 없습니다";
    return null;
  }
  async function saveSelection() {
    const input = ctrl.input();
    if (!input) return;
    setBusy(true);
    setError(null);
    try {
      const r = await doe.saveSelection(id, version, input);
      study.setData(r);
    } catch (e) {
      // v0.17.0 409 BG_GRAPH_STALE: 그래프를 다시 받고 앵커로 다시 해석(띠) — 확인 후 다시 저장
      setError(ctrl.onSaveError(e) ? BG_STALE_TEXT : errorText(e));
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
  const ranStage = phase === "RUN" || phase === "DONE" || (phase === "FAILED" && (isCompare ? !!s?.prep : !!s?.doe?.preview));
  if (!s || phase === "PREP") primary = { label: "입력 준비", onClick: () => undefined, reason: s ? "입력 준비 중…" : "불러오는 중…" };
  else if (ranStage) primary = { label: "보고서 보기", onClick: () => openReport(doe.reportUrl(id)), reason: done && s.result_ready ? null : phase === "RUN" ? "실행이 끝나면 볼 수 있습니다" : "보고서가 없습니다" };
  else if (phase === "FAILED") primary = { label: "입력 준비", onClick: () => undefined, reason: "입력 준비에 실패했습니다 — 아래 진행·로그를 확인하고 복제해 다시" };
  else if (isCompare) primary = { label: "비교 실행", onClick: runCompare, reason: compareRunReason() };
  else if (isSelect && (phase === "READY" || phase === "PREVIEW_READY") && (!selSha || ctrl.dirty)) primary = { label: "선택 저장", onClick: saveSelection, reason: saveReason() };
  else if (!hasPreview) primary = { label: "미리보기", onClick: preview, reason: previewReason() };
  else primary = { label: "강성 평가 실행", onClick: run, reason: runReason() };

  const entries = all.data ?? [];
  const varNames = s?.doe?.spec.params.map((p) => p.name) ?? [];
  const showLinks = s?.scenario === "mesh" || s?.scenario === "step";
  const d000Mesh = useD000Mesh(id, !!s && !isSelect && !isCompare && !!result.data?.view3d.includes("d000"));
  const prepAutoFailed = !!s?.prep?.warnings.some((w) => w.code === "AUTO_DETECT_FAILED");
  /** 준비 경고 목록 — GRAPH_FAILED 는 ② 비드 선택의 띠(bs-graph-failed)에만 1번(Verifier fix v0.17.0: 두 번 보이던 것) */
  // v0.18.0 ③: 고정 이전·평가 영역·삼각형 메시는 ② 비드 선택 카드 요약(주제별 1줄)에만 — 여기서는 뺌
  const prepWarns = (s?.prep?.warnings ?? []).filter((w) => !(w.code === "GRAPH_FAILED" && ctrl.graphFailText) && !(stepBaseSel && STEP_PREP_CODES.has(w.code)));
  const stepGroups = stepBaseSel ? stepPrepGroups(s?.prep) : null;
  const stepInfo: StepInfoView | null = stepGroups ? { ...stepGroups, foldKey: id } : null;
  /** v0.16.2 자동 탐지 표시: 미저장 배지(seed 를 불러왔고 저장 선택 없음) · seed 없음 안내 1줄 · AUTO_* 경고 */
  const autoView: AutoSeedView | null = isAuto
    ? {
        unsaved: ctrl.hasSeed && !selSha && !selFull.data?.v,
        notice: autoSeed.data && !autoSeed.data.seed && !selSha ? autoNoticeText(prepAutoFailed ? "AUTO_DETECT_FAILED" : autoSeed.data.code) : autoSeed.error && !selSha ? autoNoticeText("AUTO_NOT_AVAILABLE") : null,
        warnings: autoSeed.data?.seed?.warnings ?? [],
        foldKey: id,
      }
    : null;
  const blocked = st ? doeBlockedReason(st, s?.scenario) : null;
  const job = s?.job ?? null;
  const jobActive = !!job && (job.state === "QUEUED" || job.state === "RUNNING");
  const vd = useVerifyDrop(projectId, s, result.data, pick, allowed, !!me?.is_global_admin);
  const lin = !!result.data && isLinResult(result.data);
  /** v0.23.1 검증 권고(§5): 검증 낙하 툴팁 + VerifyDropCard 머리말 — 이전 sm-verify-note·결과 하단 안내문 */
  const vdAdvice = [lin ? SM_VERIFY_NOTE : null, RESULT_NOTE].filter(Boolean).join("\n");
  const vdButton = (
    <span className="primary-wrap" title={`${vd.reason ?? "고른 안을 SCX 에서 Radioss 낙하로 다시 돌려 원 낙하와 비교"}\n${vdAdvice}`}>
      <button type="button" className="btn small" disabled={!!vd.reason} aria-disabled={!!vd.reason} onClick={() => setVdOpen(true)} data-testid="vd-open">
        {VD_BUTTON}
      </button>
      {vd.reason && <span className="sr-only">{vd.reason}</span>}
    </span>
  );

  // v0.23.1 단계 초점(esl_doe_ui_tidy.md §2): 지금 단계 카드만 기본 펼침, 실행 중·실패 단계 카드는 locked
  const stage: "setup" | "preview" | "result" = ranStage ? "result" : hasPreview ? "preview" : "setup";
  const pvFailed = isFailedJob(job) && job.job_type === "DOE_PREVIEW";
  const foldOf = (k: string, cardStage: typeof stage, locked = false): CardFold => ({ storeKey: `${id}:${k}`, defaultOpen: cardStage === stage, locked });
  // §3 진행 띠(현재 작업 1개)
  const progPrep = !!job && (phase === "PREP" || (phase === "FAILED" && !s?.prep));
  const progPreview = !!job && phase === "PREVIEW";
  const progRun = !!job && (phase === "RUN" || (phase === "FAILED" && ranStage) || (phase === "DONE" && jobActive));   // v0.23.3 3D 다시 만들기 작업(DONE 유지)
  // §8 #17·18·19: 경계 경고 수·요소·노드 수는 ① 머리 1곳
  const bPrep = s?.prep?.boundary?.n_warn ?? null;
  const bRes = result.data && (showLinks || meshBaseSel) ? result.data.boundary_warnings_n : null;
  const bShown = !!s?.prep?.boundary && (stepBaseSel || meshBaseSel || showLinks);
  const bTail = bRes == null ? "" : !bShown ? ` · 경계 경고 ${bRes}` : bRes !== bPrep ? `(결과 ${bRes})` : "";
  const exactNodes = isSelect && ctrl.data ? `요소 ${ctrl.data.manifest.n_elems.toLocaleString()} · 노드 ${ctrl.data.manifest.n_nodes.toLocaleString()}` : undefined;
  // §6 결과 오른쪽 열 머리: 선택 안
  const pickRow = pick && result.data ? result.data.ranking.find((r) => r.id === pick) ?? null : null;
  const pickHead = !result.data ? null : !pick ? "순위표에서 안을 고르세요" : `선택 안 ${pick}${pickRow?.shape?.name ? ` ${pickRow.shape.name}` : pickRow && Object.keys(pickRow.values ?? {}).length ? ` · ${valuesText(pd?.params ?? [], pickRow.values)}` : ""}`;

  return (
    <>
      <div className="page-title-row">
        <h1 className="page-title">강성 평가 스터디</h1>
        {s && <span className="muted">{s.title}</span>}
        {s && (
          <ScenarioRadio
            value={studyRadio(s.scenario, s.inputs.select_base)}
            source={s.scenario === "select" ? s.inputs.bead_source ?? "manual" : null}
            onChange={() => undefined}
            onSource={() => undefined}
            auto={null}
            st={st}
            readOnly
            legacy={s.scenario === "same" ? "비드: STEP 인식(이전 방식)" : s.scenario === "mesh" ? "비드: STEP 인식 · B 메시(이전 방식)" : s.scenario === "step" ? `비드: STEP 인식 · ${LEGACY_STEP_LABEL}` : null}
          />
        )}
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
      {st?.paicad.warning && !isCompare && !isSelect && <div className="small warn-text">{st.paicad.warning}</div>}
      <JobFailBanner job={s?.job} compact />
      {error ? <ErrorLine text={error} onClose={() => setError(null)} /> : <ErrorLine text={study.error ?? stError} />}
      {job && (progPrep || progPreview || progRun) && (
        <div className="doe-progress" data-testid="doe-progress">
          {progPreview && (
            <div className="small" data-testid="preview-progress">
              미리보기 진행 중 · {progressText(job) ?? "대기 중"}
            </div>
          )}
          <Steps job={job} />
          {progRun ? (jobActive || phase === "FAILED") && <JobProgress jobId={job.id} allowed={allowed} onDone={() => { void study.reload(); void result.reload(); }} /> : <JobProgress jobId={job.id} allowed={allowed} onDone={() => void study.reload()} compact />}
        </div>
      )}
      {s && (
        <Card
          title="① 입력"
          fold={foldOf("c1", "setup", phase === "PREP" || (phase === "FAILED" && !s.prep))}
          right={
            s.prep ? (
              <span className="small muted" data-testid="input-head" title={exactNodes}>
                {isCompare
                  ? `형상 ${s.prep.n_shapes ?? s.inputs.shapes?.length ?? "?"} · 준비됨 ${s.prep.n_ready ?? "?"} · 요소 ${st?.compare?.mesh_size_mm ?? 3} mm`
                  : stepBaseSel
                    ? `STEP 메시 ${((s.prep.n_nodes ?? 0) / 1e4).toFixed(1)}만 노드 ✓${s.prep.mesh?.method ? ` · 메시 ${meshMethodName(s.prep.mesh.method)}${s.prep.mesh.route?.path === "cad_relaxed" ? "(완화 직행)" : ""}` : ""} · 고정: ${s.prep.fixed?.source === "a_transfer" && s.prep.fixed.n > 0 ? `A 이전 ${s.prep.fixed.n} 노드 ✓` : "없음 ⚠"}${s.prep.boundary ? ` · 경계 경고 ${s.prep.boundary.n_warn}` : ""}`
                  : isSelect
                    ? `${meshBaseSel ? "B 메시" : "Ch/R"} ${((s.prep.n_nodes ?? 0) / 1e4).toFixed(1)}만 노드 ✓ · 고정: ${s.prep.fixed?.source === "none" || !s.prep.fixed ? "없음 ⚠" : `fixed-scan ${s.prep.fixed.n} 노드 ✓`}${meshBaseSel && s.prep.boundary ? ` · 경계 경고 ${s.prep.boundary.n_warn}` : ""}`
                    : `비드 ${s.prep.n_beads ?? "?"} · 변수 ${s.prep.n_params ?? "?"} · paicad ${s.prep.paicad_version ?? "?"}${showLinks && s.prep.boundary ? ` · 경계 경고 ${s.prep.boundary.n_warn}` : ""}`}
                {bTail}
              </span>
            ) : undefined
          }
        >
          <DoeInputsSummary study={s} entries={entries} />
          <MsgFold items={prepWarns.map((w) => ({ text: warnText(w), info: isInfoWarn(w) }))} storeKey={`${id}:prep`} testId="prep-warn" />
        </Card>
      )}
      {beadPrep && isSelect && selDropped && (
        <div className="warn-box" role="alert" data-testid="selection-dropped">
          {warnText({ code: "SELECTION_DROPPED" })}
        </div>
      )}
      {beadPrep && isSelect && <BeadSelectCards ctrl={ctrl} editable={editable} st={st} fixedMissing={!stepBaseSel && s?.prep?.fixed?.source === "none"} auto={autoView} stepInfo={stepInfo} shapeRules={s?.inputs.shape_rules ?? null} fold2={foldOf("c2", "setup")} fold3={foldOf("c3", "setup")} />}
      {beadPrep && isSelect && (
        <SelectVarsPlan
          ready={!!selSha}
          pd={pd}
          rows={rows}
          setRows={setRows}
          form={form}
          setForm={setForm}
          st={st}
          matrix={matrix}
          matrixError={matrixError}
          editable={editable}
          plan={plan.data}
          planError={plan.error ?? params.error}
          ctrl={ctrl}
          activeVar={activeVar}
          setActiveVar={setActiveVar}
          meshBase={meshBaseSel}
          stepBase={stepBaseSel}
          nWarn={s?.prep?.boundary?.n_warn ?? null}
          beadPngUrl={(b) => doe.beadPngUrl(id, b)}
          foldKey={id}
          shapeRules={s?.inputs.shape_rules ?? null}
          fold4={foldOf("c4", "setup")}
          fold5={foldOf("c5", "setup")}
        />
      )}
      {beadPrep && !isSelect && (
        <div className="doe-grid">
          <Card title="② 비드·변수" fold={foldOf("c4", "setup")} right={<DoeMethodInfo src={st?.method_sources} method={form?.method} />}>
            {pd && rows && form && st ? (
              <>
                <DoeParamTable data={pd} rows={rows} setRows={setRows} readOnly={!editable} beadPngUrl={(b) => doe.beadPngUrl(id, b)} />
                <DoeSpecRow st={st} form={form} setForm={setForm} matrix={matrix} matrixError={matrixError} readOnly={!editable} k={rows.filter((r) => r.on).length} />
              </>
            ) : (
              <Empty>{params.error ?? "불러오는 중…"}</Empty>
            )}
          </Card>
          <Card title={showLinks ? "③ 평면도 · 경계 매핑" : "③ 평면도"} fold={foldOf("c5", "setup")}>
            {plan.data && st ? (
              <PartView data={legacyViewData({ plan: plan.data, showLinks, st, nWarn: s?.prep?.boundary?.n_warn ?? null, mesh: d000Mesh })} testId="pv-legacy" />
            ) : (
              <Empty>{plan.error ?? "불러오는 중…"}</Empty>
            )}
          </Card>
        </div>
      )}
      {beadPrep && s && (
        <Card
          title={`${isSelect ? "⑥" : "④"} 미리보기 ${pv ? previewSummary(pv, (pv.cells?.length ?? 0) + 1) : s.doe ? `(${s.doe.n_designs})` : ""}`}
          fold={foldOf("pv", "preview", phase === "PREVIEW" || pvFailed)}
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
          {pv && selStale && editable && (
            <div className="small warn-text" data-testid="selection-stale">
              <span className="badge warn">선택 변경됨 — 다시 미리보기</span>
            </div>
          )}
          {pv && matrix && !fresh && !selStale && editable && <div className="small warn-text" data-testid="preview-stale">DOE 설정이 이 미리보기와 다릅니다 — 실행하려면 미리보기를 다시 하세요</div>}
          {phase !== "PREVIEW" && pvFailed && (
            <div className="small warn-text" data-testid="preview-failed">
              미리보기가 끝나지 못했습니다 — 위 실패 줄의 [자세히] → [로그 보기]에서 원인을 확인하고 다시 [미리보기]{pv ? " (아래는 이전 미리보기)" : ""}
            </div>
          )}
          {phase !== "PREVIEW" && pv && pv.ok === 0 && (pv.cells?.length ?? 0) > 0 && (
            <div className="warn-box small" role="alert" data-testid="preview-zero-ok">
              쓸 수 있는 안(OK)이 0개입니다 — {zeroOkText(pv.cells ?? [])}. 범위를 줄이거나 선택(고정·사면)을 고친 뒤 다시 미리보기
              <FixedViolNote cells={pv.cells ?? []} title="고정 침범 원인" />
            </div>
          )}
          {phase !== "PREVIEW" && pv?.rules_outdated && (
            <div className="small warn-text" data-testid="rules-outdated">
              <span className="badge warn">{RULES_OUTDATED_TEXT}</span>
            </div>
          )}
          {phase !== "PREVIEW" && pv && pv.ok > 0 && (
            <FixedViolNote cells={(pv.cells ?? []).filter((c) => c.status === "READY" || c.status === "OK")} title="체결 위치 어긋남(경고 안 — 실행함)" testId="fixed-moved" />
          )}
          {phase !== "PREVIEW" && (
            <DoeThumbGrid
              preview={pv}
              params={pd?.params ?? []}
              thumbUrl={(d) => doe.thumbUrl(id, d)}
              select={isSelect}
              onOpen={isSelect && pv ? (d) => setOpenDid(d) : undefined}
            />
          )}
          {isSelect && openDid && pv && (
            <SelectDesign3D
              studyId={id}
              rev={s.selection?.rev ?? 0}
              did={openDid}
              values={openDid === "d000" ? Object.fromEntries((pd?.params ?? []).map((p) => [p.name, p.nominal])) : pv.cells?.find((c) => c.id === openDid)?.values ?? {}}
              vmax={pv.color?.v_max ?? 1}
              onClose={() => setOpenDid(null)}
              fixedViol={pv.cells?.find((c) => c.id === openDid)?.fixed_viol ?? null}
            />
          )}
        </Card>
      )}
      {ranStage && s && (
        <Card
          title={`${isCompare ? "② 결과" : isSelect ? "⑦ 결과" : "⑤ 결과"}${result.data ? ` · OK ${(tabR ?? result.data).n_ok}${isCompare ? "개 형상" : "안"}` : ""}`}
          right={
            result.data ? (
              <span className="inline-actions">
                {tabs && <LoadTabSeg ts={tabs} tab={curTab} setTab={setLtab} sources={LOAD_SOURCES} />}
                <Downloads study={s} result={result.data} />
              </span>
            ) : undefined
          }
        >
          <ErrorLine text={result.error} />
          {result.data && tabR && (
            <>
              <StatusBand studyId={id} result={tabR} src={curSrc} lead={reasonChips} />
              {(() => {
                const r = tabR;
                const sensShown = !(isCompare || r.sensitivity_reason);
                const solo = r.view3d.filter((d) => d !== "d000").length === 0 && !sensShown;
                return (
                  <div className={`doe-result-2col${solo ? " solo" : ""}`} data-testid="doe-result-2col" id="doe-load-panel" role="tabpanel" aria-label="하중 정의 결과">
                    <div className="doe-result-left">
                      <DoeRanking
                        key={`rank-${curTab}`}
                        result={r}
                        params={pd?.params ?? []}
                        entries={entries}
                        selected={pick}
                        onSelect={setPick}
                        varNames={varNames}
                        rankCfg={st}
                        shapeRules={s?.inputs.shape_rules ?? null}
                        perEslNote={perEslNote(r, pick)}
                        resultNote={isCompare ? COMPARE_NOTE : null}
                      />
                      <div className="sub-title">ESL별 개선율</div>
                      <DoePerEslTable key={`pe-${curTab}`} studyId={id} result={r} entries={entries} pick={pick} view={curSrc && (result.data?.rank_views as Record<string, unknown> | null | undefined)?.[curTab] ? curTab : null} />
                    </div>
                    <div className="doe-result-right">
                      <div className="inline-actions doe-pick-bar">
                        <span className="small" data-testid="doe-pick-head">{pickHead}</span>
                        <span className="spacer" />
                        <span className="inline-actions" data-testid="doe-pick-actions">
                          <RedropControl study={s} pick={pick} />
                          {isCompare ? null : vdButton}
                        </span>
                      </div>
                      <div className="sub-title">3D 비교</div>
                      <Compare3D key={`v3d-${curTab}`} studyId={id} result={r} pick={pick} setPick={setPick} kind={curSrc?.view3d ?? null} onRegen={() => void study.reload()} />
                      {sensShown ? (
                        <div>
                          <div className="sub-title">민감도</div>
                          <Sensitivity sens={r.sensitivity} params={pd?.params ?? []} warnings={r.warnings} />
                        </div>
                      ) : (
                        <div className="small muted" data-testid="sens-hidden">
                          민감도: {SENS_REASON[r.sensitivity_reason ?? "COMPARE_NO_PARAMS"] ?? r.sensitivity_reason}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}
            </>
          )}
        </Card>
      )}
      {done && !isCompare && (
        <ErrorBoundary>
          <ErrorLine text={vd.listError} />
          <VerifyDropCard drops={vd.drops} entries={entries} allowed={allowed} onChanged={vd.reload} note={vdAdvice.replace(/\n/g, " ")} />
        </ErrorBoundary>
      )}
      {vdOpen && s && (
        <VerifyDropDialog
          studyId={s.id}
          designs={vd.designs}
          initialDesign={vd.initialDesign}
          initialPlan={vd.plan}
          entries={entries}
          onClose={() => setVdOpen(false)}
          onCreated={() => {
            setVdOpen(false);
            vd.reload();
          }}
        />
      )}
    </>
  );
}

// ================================================================ v0.23.1 결과 상태 띠(esl_doe_ui_tidy.md §4)
const SM_VERIFY_NOTE = "1차 강성 지표 순위입니다(재풀이 없음) — 상위 안은 산출물로 Radioss 검증 낙하를 돌려 확인하세요.";
const SM_CROSS_NOTE = "다른 메시 비교(정밀도 낮음) — 형상마다 메시가 달라 1차 강성 지표 대신 재풀이 C 로 순위를 매겼습니다. 상위 안은 Radioss 검증 낙하로 확인하세요.";
const RESULT_NOTE = "선형 강성 상대 비교입니다(낙하 응답 재현 아님) — 최적 안은 검증 낙하 1회로 확인하세요. 방법·출처·한계는 보고서에.";
const COMPARE_NOTE = "선형 강성 상대 비교입니다 — 형상마다 새 메시라 작은 차이는 메시 차이일 수 있고, 같은 좌표계 STEP 을 전제합니다(작은 형상 억제는 CAD 메시가 실패한 형상만 — 형상 표 '형상 단순화'). 방법·한계는 보고서에.";

/** 칩 1줄: 지그 · 하중 전달 · 메시 품질 · 1위 경고 · 경고 n. 칩 testid = 이전 줄 testid, 이전 줄 전체 = title */
/** v0.23.3 불가 출처 사유 칩 1개(원 결과로 — 지그 미계산·지그 불가) */
function StatusChipOnly({ result, kind }: { result: DoeResultOut; kind: ChipKind }) {
  if (kind !== "jig") return null;
  const jig = result.jig ?? null;
  return jig ? <JigLine jig={jig} /> : <JigNoneChip onClone={result.jig_on_clone} />;
}

function StatusBand({ studyId, result, src = null, lead = null }: { studyId: string; result: DoeResultOut; src?: LoadSource | null; lead?: ReactNode }) {
  // v0.21.0 ③ 기준 메시 품질 미달(모든 안이 같은 메시 — 행 표시 없음). 목록에서는 뺌
  const mqBase = result.warnings.find((w) => w.code === "MESH_QUALITY_RANK" && w.scope === "base");
  const rest = result.warnings.filter((w) => w.code !== "SENSITIVITY_TOO_FEW" && w.code !== "SM_CROSS_MESH" && w !== mqBase);
  const items = [...(!isLinResult(result) && isCrossMesh(result) ? [{ text: SM_CROSS_NOTE }] : []), ...rest.map((w) => ({ text: warnText(w) }))];
  const jig = result.jig ?? null;
  // v0.23.3 출처 표(LOAD_SOURCES.chips)의 칩만 그림 — 출처 이름 분기 없음. src 없음(④·탭 없음) = 기존 전부
  const kinds: readonly ChipKind[] = src ? src.chips : ["jig", "lt", "mq", "best_clean_mq", "best_clean"];
  const chip: Record<ChipKind, ReactNode> = {
    // v0.23.2 D-0.23.2-3: 지그 칩(계산됨 = 기존, 미계산 = 복제 안내)
    jig: jig ? <JigLine key="jig" jig={jig} /> : <JigNoneChip key="jig" onClone={result.jig_on_clone} />,
    lt: result.load_transfer && <LoadTransferDiag key="lt" studyId={studyId} result={result} />,
    mq: mqBase && (
      <ChipDetail key="mq" testid="mq-base-strip" className="doe-chip warn-text" title={`⚠ ${warnText(mqBase)}`} full={`⚠ ${warnText(mqBase)}`}>
        ⚠ 기준 메시 품질 미달
      </ChipDetail>
    ),
    best_clean_mq: <BestCleanMqChip key="bcmq" result={result} />,
    best_clean: <BestCleanChip key="bc" result={result} />,
  };
  return (
    <div className="doe-status" data-testid="doe-status">
      {lead}
      {kinds.map((k) => chip[k])}
      <MsgFold items={items} storeKey={`${studyId}:result-warn`} testId="result-warn" />
    </div>
  );
}

/** v0.23.3 하중 정의 탭 세그먼트(결과 카드 머리 — 높이 불변). 출처 표 행마다 버튼 1개, 불가 = 비활성 + title 사유 */
function LoadTabSeg({ ts, tab, setTab, sources }: { ts: TabState; tab: LoadTab; setTab: (t: LoadTab) => void; sources: readonly LoadSource[] }) {
  const [focus, setFocus] = useState<LoadTab | null>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  /** 좌우 화살표(·Home·End) = 포커스만 이동(가능 여부와 무관 — 비활성 탭도 사유를 읽을 수 있게), Enter·Space = 선택 */
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = sources.length;
    const j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    refs.current[sources[j].key]?.focus();
  };
  const focusReason = focus && !ts.ok[focus] ? ts.reason[focus] : null;
  return (
    <div className="seg" role="tablist" aria-label="하중 정의" data-testid="doe-load-tab" style={{ position: "relative" }}>
      {sources.map((s, i) => {
        const ok = ts.ok[s.key];
        const why = ts.reason[s.key];
        return (
          <Fragment key={s.key}>
          <button
            ref={(el) => {
              refs.current[s.key] = el;
            }}
            id={`doe-load-tab-${s.key}`}
            type="button"
            role="tab"
            data-tab={s.key}
            className={tab === s.key ? "on" : ""}
            aria-selected={tab === s.key}
            aria-controls="doe-load-panel"
            aria-disabled={!ok}
            aria-describedby={!ok && why ? `doe-load-why-${s.key}` : undefined}
            tabIndex={tab === s.key || (!ts.ok[tab] && i === 0) ? 0 : -1}
            title={ok ? s.title : why ?? undefined}
            onFocus={() => setFocus(s.key)}
            onBlur={() => setFocus((f) => (f === s.key ? null : f))}
            onKeyDown={(e) => onKey(e, i)}
            onClick={() => ok && setTab(s.key)}
          >
            {s.label}
          </button>
          {!ok && why && (
            <span id={`doe-load-why-${s.key}`} className="sr-only">
              {why}
            </span>
          )}
          </Fragment>
        );
      })}
      {/* 키보드 포커스 사유(비활성 탭) — 절대 위치, 높이 불변 */}
      {focusReason && (
        <span className="small warn-text" data-testid="doe-load-tab-why" role="status" style={{ position: "absolute", top: "100%", left: 0, zIndex: 5, whiteSpace: "nowrap", background: "var(--surface)", border: "1px solid var(--line-strong)", borderRadius: 4, padding: "0 0.4rem" }}>
          {focusReason}
        </span>
      )}
    </div>
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
      crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: MENU_LIBRARY, to: `${libPath(projectId)}?tab=study` }, { label: isNew ? "새 강성 평가 스터디" : "강성 평가 스터디" }]}
      projectId={projectId}
    >
      {isNew ? <NewStudy projectId={projectId} st={settings.data} stError={settings.error} /> : <StudyDetail key={doeId} projectId={projectId} id={doeId} st={settings.data} stError={settings.error} />}
    </Shell>
  );
}
