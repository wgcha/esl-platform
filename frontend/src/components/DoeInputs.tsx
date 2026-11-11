// 비드 DOE ① 입력 카드(esl_bead_doe.md §3·§12.2): ESL 목록(같은 모델 ✓/✗ · 다른 모델 빼기) · STEP 끌어다 놓기(기존 청크 업로드) ·
// ② B 메시(rad + include/inc)·파트 제목·인치 · ③ 쉘 물성 3칸(t·E·ν, 서버 기본값)·평균 요소 크기 · 입력 검사 한 줄.
// v0.14.0 ④ 형상 직접 비교(esl_step_compare.md §3·§7): STEP 여러 개(놓을 때마다 업로드 세션 1개에 STEP 여러 개 — 형상마다 rel) ·
// 형상 표(기준 라디오 + '기준 없음(Case 메시)'·이름·빼기) · 물성 3칸 · 준비 후 메시 품질 요약(Fail 비율·상한 경고).
// v0.16.0 메시 옵션(esl_compare_mesh_options.md §8): 형상 행 [STEP | 메시] 토글(기본 = 확장자), 한 번에 놓은 rad/inc 묶음 = 메시 행 1개
// (주 파일 C2-D-2), 파트 ID 칸(check-inputs parts[] datalist, 하나면 자동 채움), 준비 후·결과 '메시 방식' 열(툴팁 충실도·시도·δ).
// v0.16.1(esl_select_relax.md §8): 메시 방식 "형상 단순화"(defeature) + 억제 목록 펼침(GET …/shapes/{did}/defeature, 상위 50행), 메시 입력 진단 글자.
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { CODE_TEXT, errorText } from "../api/client";
import {
  BEAD_SOURCE_NAME, DEFEATURE_KIND_NAME, diagText, doe, featureSizeText,
  MESH_METHOD_SHORT, MESH_MODE_NAME, SCENARIO_NAME, STATUS_NAME, STEP_EXT, defaultShapeName, meshMainCandidates, meshMethodKind, meshMethodLabel, meshMethodTip, partIdProblem, shapeFailText, shapeFailTip, shapeKindOf,
  shapeNameProblem, warnText, isInfoWarn,
} from "../api/doe";
import type { DoeBeadSource, DoeSelectBase, DoeDefeatureList, DoeCheckOut, DoeDesignStatus, DoeMeshMode, DoeMeshPart, DoePrepShape, DoeScenario, DoeSettingsOut, DoeStudyOut, EntryOut } from "../api/types";
import { entryKey } from "./ModeSelect";
import { Empty, ErrorLine, Field } from "./ui";
import { MsgFold, msgHead } from "./MsgFold";
import { Uploader, type UploadProgress } from "../lib/uploader";
import { bytes } from "../lib/format";

export interface UploadedSet {
  uploadId: string;
  names: string[];
  /** 올린 바이트(④ 형상 표 크기) */
  bytes?: number;
  /** ④ 업로드 안 파일 rel(한 세션 여러 STEP — 형상마다 요청 shapes[].rel) */
  rel?: string;
}

/** 파일 끌어다 놓기 + 청크 업로드(Uploader). 다 올리면 onDone(uploadId). split = 놓은 파일 전부를 업로드 세션 1개로 올린 뒤
 * 파일마다 onDone({uploadId, rel})(④ 형상 STEP — 한 세션에 STEP 여러 개, 동시 세션 한도와 무관) */
export function UploadDrop({ projectId, label, hint, ext, validate, name, value, onDone, onClear, disabled, testId, split, display, onBatch }: {
  projectId: string;
  label: string;
  hint: string;
  ext: string[];
  /** 고른 파일 검사(사유 = 막음) */
  validate: (files: File[]) => string | null;
  /** 업로드 세션 이름 */
  name: (files: File[]) => string;
  value: UploadedSet | null;
  onDone: (v: UploadedSet) => void;
  onClear: () => void;
  disabled?: boolean;
  testId: string;
  /** 한 세션으로 올려 파일마다 onDone(값 표시 없음, onClear 안 부름) */
  split?: boolean;
  /** 제목 대신 보일 문구(예: 상한 도달 '최대 20개') */
  display?: string;
  /** split 일 때 파일마다 onDone 대신 한 번에(v0.16.0 ④ — rad/inc 묶음을 행 1개로) */
  onBatch?: (uploadId: string, files: { name: string; size: number; rel: string }[]) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [prog, setProg] = useState<UploadProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(picked: File[]) {
    if (!picked.length || busy || disabled) return;
    const bad = picked.filter((f) => !ext.some((x) => f.name.toLowerCase().endsWith(x)));
    const why = bad.length ? `${bad.map((f) => f.name).join(", ")}: ${ext.join("·")} 만 올릴 수 있습니다` : validate(picked);
    if (why) {
      setError(why);
      return;
    }
    setError(null);
    setBusy(true);
    if (split) {
      try {
        const files = picked.map((f) => ({ file: f, rel: `rad/${f.name}` }));
        const up = new Uploader(projectId, name(picked), files, setProg);
        const done = await up.run();
        if (!done || !up.uploadId) throw new Error(up.progress.error ?? "업로드가 멈췄습니다");
        if (onBatch) onBatch(up.uploadId, files.map((x) => ({ name: x.file.name, size: x.file.size, rel: x.rel })));
        else for (const x of files) onDone({ uploadId: up.uploadId, names: [x.file.name], bytes: x.file.size, rel: x.rel });
        setProg(null);
      } catch (x) {
        setError(errorText(x));
      } finally {
        setBusy(false);
      }
      return;
    }
    onClear();
    try {
      // 기존 업로드 rel 규칙(rad/ 아래) 그대로 — 서버가 check-inputs 에서 STEP·메시를 판정
      const up = new Uploader(projectId, name(picked), picked.map((f) => ({ file: f, rel: `rad/${f.name}` })), setProg);
      const done = await up.run();
      if (!done || !up.uploadId) throw new Error(up.progress.error ?? "업로드가 멈췄습니다");
      onDone({ uploadId: up.uploadId, names: picked.map((f) => f.name) });
    } catch (x) {
      setError(errorText(x));
    } finally {
      setBusy(false);
    }
  }
  const pct = prog && prog.total ? Math.round((prog.sent / prog.total) * 100) : value ? 100 : 0;
  return (
    <div className="doe-drop" data-testid={testId}>
      <div
        className={`dropzone compact${over ? " over" : ""}${value ? " has" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void start([...e.dataTransfer.files]);
        }}
      >
        <span className="dropzone-title">{display ?? (value ? value.names.join(", ") : label)}</span>
        <span className="small muted">{hint}</span>
        <button type="button" className="btn small" disabled={busy || disabled} onClick={() => ref.current?.click()}>
          파일 고르기
        </button>
        <input ref={ref} type="file" multiple hidden accept={ext.join(",")} aria-label={label} onChange={(e) => void start([...(e.target.files ?? [])])} />
      </div>
      {(prog || value) && (
        <div className="upload-progress">
          <div className="progress" role="progressbar" aria-label={`${label} 업로드`} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="small muted">{prog ? `${pct}% · ${bytes(prog.sent)} / ${bytes(prog.total)}` : "100%"}</span>
        </div>
      )}
      <ErrorLine text={error} />
    </div>
  );
}

/** ④ 형상 표 1행(key = uploadId + rel — 한 업로드 세션에 STEP 여러 개) */
export interface ShapeRow {
  key: string;
  uploadId: string;
  /** 업로드 안 STEP rel 또는 메시 주 파일 rel(요청 shapes[].rel) */
  rel: string;
  fileName: string;
  bytes: number;
  name: string;
  /** v0.16.0 파일 종류(확장자) — 토글 기본값. 없으면 step(옛 행) */
  kind?: "step" | "mesh";
  /** v0.16.0 요청 source(기본 = kind) */
  source?: "step" | "mesh";
  /** 메시 묶음 rel 전부(주 + include) */
  meshFiles?: string[];
  /** 주 파일 후보(2개 이상이면 화면에서 고름) */
  mainCandidates?: string[];
  /** 파트 ID 칸(빈 칸 = 서버 판정) */
  partId?: string;
  /** check-inputs parts[](datalist) */
  parts?: DoeMeshPart[] | null;
}
export const rowSource = (x: ShapeRow): "step" | "mesh" => x.source ?? x.kind ?? "step";
const baseName = (rel: string) => rel.split("/").pop() ?? rel;

export interface InputsForm {
  step: UploadedSet | null;
  mesh: UploadedSet | null;
  partTitle: string;
  inch: string;
  t: string;
  E: string;
  nu: string;
  meshSize: string;
  title: string;
  /** ④ 형상 표 */
  shapes: ShapeRow[];
  /** ④ 기준 형상 key(null = 기준 없음 → 첫 ESL Case 메시) */
  refId: string | null;
  /** v0.16.0 ④ 고급 설정 메시 방식(null = 서버 설정값 — 요청에 안 넣음) */
  meshMode?: DoeMeshMode | null;
  /** v0.16.0 ④ 실패 시 세분화 허용(null = 설정값, 기본 켬) */
  meshRefine?: boolean | null;
}

export const EMPTY_INPUTS: InputsForm = { step: null, mesh: null, partTitle: "", inch: "", t: "", E: "", nu: "", meshSize: "", title: "", shapes: [], refId: null, meshMode: null, meshRefine: null };

/** ③ 물성·요소 크기 검사(t>0, E>0, 0≤ν<0.5, 크기 설정 범위). ④ 는 meshSize=false(크기 설정 고정) */
export function propsProblem(f: InputsForm, st: DoeSettingsOut, meshSize = true): string | null {
  const t = Number(f.t);
  const E = Number(f.E);
  const nu = Number(f.nu);
  if (!(f.t.trim() && t > 0)) return "두께는 0보다 커야 합니다";
  if (!(f.E.trim() && E > 0)) return "E 는 0보다 커야 합니다";
  if (!(f.nu.trim() && nu >= 0 && nu < 0.5)) return "ν 는 0 이상 0.5 미만입니다";
  if (!meshSize) return null;
  const h = Number(f.meshSize);
  if (!(f.meshSize.trim() && h >= st.mesh.size_min_mm && h <= st.mesh.size_max_mm)) return `요소 크기는 ${st.mesh.size_min_mm}~${st.mesh.size_max_mm} mm 입니다`;
  return null;
}

const relText = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)} %`;

/** 입력 검사 결과 한 줄 */
function CheckLine({ check, scenario, stepBase }: { check: DoeCheckOut; scenario: DoeScenario; stepBase?: boolean }) {
  return (
    <div className="small" data-testid="doe-check">
      {scenario === "compare" && check.shapes && (
        <span>
          형상 {check.shapes.length}개 · 합계 {check.shapes.reduce((a, x) => a + x.size_mb, 0).toFixed(1)} MB <span className="ok-text">✓</span> · 기준{" "}
          {check.reference_source === "case"
            ? `Case 메시${check.base ? ` (${check.base.case_title ?? check.base.case_id} · 요소 ${check.base.n_elems.toLocaleString()})` : ""}`
            : `STEP ${check.shapes.find((x) => x.reference)?.name ?? "?"}`}{" "}
          (메시·크기·정렬 검사는 입력 준비에서)
        </span>
      )}
      {scenario === "select" && check.step && (
        <span>
          STEP {check.step.file_name}
          {stepBase ? ` · ${check.step.size_mb.toFixed(2)} MB` : ""} <span className="ok-text">✓</span> {stepBase ? "(메시·크기 검사는 입력 준비에서)" : "(자동 탐지 참고 힌트) ·"}{" "}
        </span>
      )}
      {scenario === "step" && check.step && (
        <span>
          STEP {check.step.file_name} · {check.step.size_mb.toFixed(2)} MB <span className="ok-text">✓</span> (크기 검사는 입력 준비에서)
        </span>
      )}
      {check.base && (scenario === "same" || (scenario === "select" && !check.mesh && !stepBase)) && (
        <span>
          기준 Case {check.base.case_title ?? check.base.case_id} · 파트 {check.base.part_title} · 노드 {check.base.n_nodes.toLocaleString()} · 요소 {check.base.n_elems.toLocaleString()}
        </span>
      )}
      {check.mesh && (
        <span>
          B 메시 {check.mesh.file_name} · 파트 {check.mesh.part_title ?? "?"} · 요소 {check.mesh.mesh.n_elems.toLocaleString()}
        </span>
      )}
      {check.size && (
        <span>
          {" "}
          · 크기 검사: ξ {relText(check.size.rel_xi)} η {relText(check.size.rel_eta)} <span className="ok-text">✓</span>
        </span>
      )}
      <MsgFold items={check.warnings.map((w) => ({ text: warnText(w), info: isInfoWarn(w) }))} storeKey="new:check" testId="doe-check-warn" />
    </div>
  );
}

export function DoeInputs({ projectId, scenario, selectBase, beadSource, st, entries, ids, onIds, mismatched, form, setForm, check, checkError, checking, allowed, advanced }: {
  projectId: string;
  scenario: DoeScenario;
  /** v0.16.2 select 기준(① case · ② mesh — AD-D-13). v0.18.0 ③ step = STEP 필수 · 인치 · 쉘 물성 · 메시 방식(고급) — 요소 크기 칸 없음(④ 프로필) */
  selectBase?: DoeSelectBase | null;
  /** v0.16.2 select 하위 라디오(auto = STEP 칸 · manual = STEP 없음, AD-D-1·14). v0.17.0 auto 의 STEP 은 선택(BG §5.3) */
  beadSource?: DoeBeadSource | null;
  st: DoeSettingsOut;
  entries: EntryOut[];
  ids: string[];
  onIds: (ids: string[]) => void;
  /** 다른 모델 ESL(① 에서 ✗) */
  mismatched: string[];
  form: InputsForm;
  setForm: (f: InputsForm | ((p: InputsForm) => InputsForm)) => void;
  check: DoeCheckOut | null;
  checkError: string | null;
  checking: boolean;
  allowed: boolean;
  /** v0.16.0 ④ 고급 설정(물성 칸 아래, DoeStudy 가 만듦) */
  advanced?: ReactNode;
}) {
  const byId = new Map(entries.map((e) => [e.id, e]));
  const set = (k: keyof InputsForm, v: string) => setForm({ ...form, [k]: v });
  const stepOnly = (fs: File[]) => (fs.length !== 1 ? "STEP 파일 1개를 고르세요" : fs[0].size > st.step_max_mb * 1024 ** 2 ? `STEP 은 최대 ${st.step_max_mb} MB 입니다` : null);
  const meshOk = (fs: File[]) => (fs.some((f) => /\.(rad|inc)$/i.test(f.name)) ? null : ".rad(+ include) 또는 .inc 파일이 있어야 합니다");
  const isSel = scenario === "select";
  /** v0.18.0 ③ STEP 기준 select */
  const stepBase = isSel && selectBase === "step";
  /** 같은 모델 검사(✓/✗·다른 모델 빼기): ① same·select(case) */
  const sameModel = scenario === "same" || (isSel && selectBase !== "mesh" && !stepBase);
  /** B 메시 칸(② mesh·select(mesh)) */
  const needMesh = scenario === "mesh" || (isSel && selectBase === "mesh");
  /** STEP 칸(same·mesh·step, select 는 자동 탐지만) */
  const needStep = isSel ? beadSource === "auto" || stepBase : scenario !== "compare";
  /** STEP 이 참고 힌트일 뿐(① 자동 탐지) */
  const stepHint = isSel && !stepBase;
  return (
    <div className="doe-inputs">
      <div className="doe-esl" aria-label="선택한 ESL">
        <span className="field-label">ESL ({ids.length})</span>
        {!ids.length ? (
          <Empty>선택한 ESL 이 없습니다 — 라이브러리에서 체크하세요</Empty>
        ) : (
          <ul className="chip-list">
            {ids.map((id) => {
              const e = byId.get(id);
              const bad = sameModel && mismatched.includes(id);
              return (
                <li key={id} className={`chip${bad ? " bad" : ""}`}>
                  {e ? entryKey(e) : id} {sameModel && (bad ? <span className="error-text" title="다른 모델(노드 ID·요소 연결 다름)">✗</span> : <span className="ok-text">✓</span>)}
                </li>
              );
            })}
          </ul>
        )}
        {sameModel && mismatched.length > 0 && (
          <button type="button" className="btn small" onClick={() => onIds(ids.filter((x) => !mismatched.includes(x)))}>
            다른 모델 빼기
          </button>
        )}
      </div>
      {scenario === "compare" ? (
        <CompareShapes projectId={projectId} st={st} form={form} setForm={setForm} allowed={allowed} />
      ) : isSel && !needStep && !needMesh ? (
        <div className="small muted" data-testid="doe-select-note">
          STEP 없이 기준 Case 의 낙하 메시(노드·요소 ID 그대로)에서 비드를 직접 고릅니다 — 입력 준비 후 3D 에서 선택
        </div>
      ) : (
      <div className="doe-files">
        {needStep && (
        <UploadDrop
          projectId={projectId}
          label={stepHint ? "(선택) Ch/R 중립면 STEP 끌어다 놓기" : "Ch/R 중립면 STEP 끌어다 놓기"}
          hint={stepHint ? `없어도 됩니다 — 메시 분류기가 비드를 찾고, STEP 은 참고 힌트만 · 최대 ${st.step_max_mb} MB` : stepBase ? `시트(중립면) STEP · ④ 와 같은 설정으로 메시 · 최대 ${st.step_max_mb} MB` : `시트(중립면) STEP · 최대 ${st.step_max_mb} MB`}
          ext={[".step", ".stp"]}
          validate={stepOnly}
          name={(fs) => `doe_step_${fs[0].name.replace(/\.[^.]+$/, "")}`}
          value={form.step}
          onDone={(v) => setForm({ ...form, step: v })}
          onClear={() => setForm({ ...form, step: null })}
          disabled={!allowed}
          testId="doe-step-drop"
        />
        )}
        {needMesh && (
          <UploadDrop
            projectId={projectId}
            label="B 메시(.rad + include 또는 .inc) 끌어다 놓기"
            hint="Ch/R 주변만 올려도 됩니다(체결 tie·RBE2 포함 권장)"
            ext={[".rad", ".inc"]}
            validate={meshOk}
            name={(fs) => `doe_mesh_${(fs.find((f) => /\.rad$/i.test(f.name)) ?? fs[0]).name.replace(/\.[^.]+$/, "")}`}
            value={form.mesh}
            onDone={(v) => setForm({ ...form, mesh: v })}
            onClear={() => setForm({ ...form, mesh: null })}
            disabled={!allowed}
            testId="doe-mesh-drop"
          />
        )}
      </div>
      )}
      <div className="form-grid tight doe-fields">
        {needMesh && (
          <Field label="B 파트 제목">
            <input aria-label="B 파트 제목" value={form.partTitle} placeholder={st.part_title ?? ""} onChange={(e) => set("partTitle", e.target.value)} />
          </Field>
        )}
        {!sameModel && (
          <Field label="인치(선택)">
            <input type="number" aria-label="인치" min={1} value={form.inch} onChange={(e) => set("inch", e.target.value)} />
          </Field>
        )}
        {(scenario === "step" || scenario === "compare" || stepBase) && (
          <>
            <Field label="두께 t (mm)">
              <input type="number" aria-label="두께 t (mm)" step="0.1" min={0} value={form.t} onChange={(e) => set("t", e.target.value)} />
            </Field>
            <Field label="E (MPa)">
              <input type="number" aria-label="E (MPa)" min={0} value={form.E} onChange={(e) => set("E", e.target.value)} />
            </Field>
            <Field label="ν">
              <input type="number" aria-label="ν" step="0.01" min={0} max={0.49} value={form.nu} onChange={(e) => set("nu", e.target.value)} />
            </Field>
            {scenario === "step" && (
              <Field label="요소 크기 (mm)" hint={check?.mesh_size_default_mm != null ? `자동: A 중앙값 ${check.mesh_size_default_mm}` : undefined}>
                <input type="number" aria-label="요소 크기 (mm)" step="0.5" min={st.mesh.size_min_mm} max={st.mesh.size_max_mm} value={form.meshSize} onChange={(e) => set("meshSize", e.target.value)} />
              </Field>
            )}
          </>
        )}
        {stepBase && (
          <span className="small muted doe-mesh-note" data-testid="step-mesh-note">
            메시: ④ 와 같은 설정 · 요소 {st.compare?.mesh_size_mm ?? 3} mm
          </span>
        )}
        {scenario === "compare" && (
          <span className="small muted doe-mesh-note" data-testid="compare-mesh-note">
            메시: 모든 STEP 같은 설정 · 요소 {st.compare?.mesh_size_mm ?? 3} mm(서버 설정)
          </span>
        )}
        <Field label="제목(선택)" className="doe-title">
          <input aria-label="제목" maxLength={200} value={form.title} placeholder={`예: 75형 Ch/R ${isSel ? (selectBase === "mesh" ? "다른 모델 비드 선택" : stepBase ? "STEP 비드 선택" : "비드 선택") : SCENARIO_NAME[scenario]} 1차`} onChange={(e) => set("title", e.target.value)} />
        </Field>
      </div>
      {(scenario === "compare" || stepBase) && advanced}
      {checking && <div className="small muted">입력 검사 중…</div>}
      <ErrorLine text={checkError} />
      {check && <CheckLine check={check} scenario={scenario} stepBase={stepBase} />}
    </div>
  );
}

/** 상세 화면: 입력 요약(읽기만) */
export function DoeInputsSummary({ study, entries }: { study: DoeStudyOut; entries: EntryOut[] }) {
  const byId = new Map(entries.map((e) => [e.id, e]));
  const i = study.inputs;
  return (
    <div className="doe-inputs">
      <div className="doe-esl" aria-label="선택한 ESL">
        <span className="field-label">ESL ({study.entry_ids.length})</span>
        <ul className="chip-list">
          {study.entry_ids.map((id) => (
            <li key={id} className="chip">
              {byId.get(id) ? entryKey(byId.get(id)!) : id}
            </li>
          ))}
        </ul>
      </div>
      {study.scenario === "compare" ? (
        <CompareShapeSummary study={study} />
      ) : study.scenario === "select" ? (
        <div className="small" data-testid="doe-input-summary">
          비드 선택({BEAD_SOURCE_NAME[i.bead_source ?? "manual"]})
          {i.select_base === "mesh" && (
            <>
              {" "}
              <span className="badge info" data-testid="doe-base-chip" title="다른 모델 — 하중은 셀 매핑, 지지는 B 메시 자동 3-2-1">
                기준 B 메시 · 셀 매핑
              </span>
            </>
          )}
          {i.select_base === "step" && (
            <>
              {" "}
              <span className="badge info" data-testid="doe-base-chip" title="STEP → ④ 메시 사다리 → 비드 분류 — 하중은 셀 매핑, 지지는 자동 3-2-1, 결과는 메시만">
                기준 STEP 메시 · 셀 매핑
              </span>
            </>
          )}
          {i.select_base === "mesh" && i.mesh ? ` · B 메시 ${i.mesh.file_name}` : ""}
          {(i.bead_source === "auto" || i.select_base === "step") && i.step ? ` · STEP ${i.step.file_name}` : ""}
          {i.part_title ? ` · 파트 ${i.part_title}` : ""}
          {(i.select_base === "mesh" || i.select_base === "step") && i.inch ? ` · ${i.inch}형` : ""}
          {i.select_base === "step" && i.props ? ` · t ${i.props.t} mm · E ${i.props.E.toLocaleString()} MPa · ν ${i.props.nu}` : ""}
          {i.select_base === "step" && i.mesh_mode ? ` · 메시 방식 ${MESH_MODE_NAME[i.mesh_mode]}` : ""}
          {study.prep?.n_elems ? ` · 요소 ${study.prep.n_elems.toLocaleString()} · 노드 ${(study.prep.n_nodes ?? 0).toLocaleString()}` : ""}
          {study.selection ? ` · 선택 rev ${study.selection.rev}` : " · 선택 미저장"}
        </div>
      ) : (
      <div className="small" data-testid="doe-input-summary">
        STEP {i.step?.file_name ?? "–"}
        {i.mesh ? ` · B 메시 ${i.mesh.file_name}` : ""}
        {i.part_title ? ` · 파트 ${i.part_title}` : ""}
        {i.inch ? ` · ${i.inch}형` : ""}
        {i.props ? ` · t ${i.props.t} mm · E ${i.props.E.toLocaleString()} MPa · ν ${i.props.nu}` : ""}
        {i.mesh_size_mm ? ` · 요소 ${i.mesh_size_mm} mm` : ""}
      </div>
      )}
    </div>
  );
}

// ================================================================ ④ 형상 직접 비교
const mb = (b: number) => b / 1024 ** 2;

/** ④ 형상 표(새 연구): 끌어다 놓기(여러 파일, 한 세션) → 행마다 [기준 ◉][STEP | 메시][이름][파일·크기][파트 ID(메시)][✕]. 맨 위 '기준 없음(Case 메시)'.
 *  한 번에 놓은 STEP 은 파일마다 행 1개, rad/inc 묶음은 메시 행 1개(주 파일 C2-D-2 — 못 정하면 행에서 고름) */
export function CompareShapes({ projectId, st, form, setForm, allowed }: {
  projectId: string;
  st: DoeSettingsOut;
  form: InputsForm;
  setForm: (f: InputsForm | ((p: InputsForm) => InputsForm)) => void;
  allowed: boolean;
}) {
  const max = st.compare?.max_shapes ?? 20;
  const totalMax = st.compare?.total_max_mb ?? 1000;
  const mi = st.compare?.mesh_input;
  const meshOn = !!mi?.enabled;
  const meshFormats = meshOn ? mi!.formats : [];
  const shapes = form.shapes;
  const full = shapes.length >= max;
  const names = shapes.map((x) => x.name);
  const anyMesh = shapes.some((x) => rowSource(x) === "mesh");
  const validate = (fs: File[]) => {
    const steps = fs.filter((f) => shapeKindOf(f.name, meshFormats) === "step");
    const meshes = fs.filter((f) => shapeKindOf(f.name, meshFormats) === "mesh");
    if (!meshOn && fs.some((f) => /\.(rad|inc)$/i.test(f.name))) return "메시 입력이 서버에서 꺼져 있습니다 — STEP 만 올릴 수 있습니다";
    const nNew = steps.length + (meshes.length ? 1 : 0);
    if (shapes.length + nNew > max) return meshOn ? `형상은 최대 ${max}개입니다(지금 ${shapes.length}개)` : `STEP 은 최대 ${max}개입니다(지금 ${shapes.length}개)`;
    const dupName = fs.find((f, i) => fs.findIndex((g) => g.name === f.name) !== i);
    if (dupName) return `${dupName.name}: 같은 이름의 파일을 한 번에 올릴 수 없습니다`;
    const big = steps.find((f) => f.size > st.step_max_mb * 1024 ** 2);
    if (big) return `${big.name}: STEP 은 파일당 최대 ${st.step_max_mb} MB 입니다`;
    if (meshes.length && mi && mb(meshes.reduce((a, f) => a + f.size, 0)) > mi.max_mb) return `메시 파일(주 + include) 합계는 최대 ${mi.max_mb} MB 입니다`;
    if (meshes.length && !meshMainCandidates(meshes.map((f) => f.name)).length) return "메시 주 파일(.rad 또는 .inc)이 없습니다";
    const total = mb(shapes.reduce((a, x) => a + x.bytes, 0) + fs.reduce((a, f) => a + f.size, 0));
    if (total > totalMax) return meshOn ? `형상 파일 합계는 최대 ${totalMax} MB 입니다` : `STEP 합계는 최대 ${totalMax} MB 입니다`;
    return null;
  };
  const addBatch = (uploadId: string, files: { name: string; size: number; rel: string }[]) =>
    setForm((f) => {
      const rows: ShapeRow[] = files
        .filter((x) => shapeKindOf(x.name, meshFormats) === "step")
        .map((x) => ({ key: `${uploadId}:${x.rel}`, uploadId, rel: x.rel, fileName: x.name, bytes: x.size, name: defaultShapeName(x.name), kind: "step", source: "step" }));
      const meshes = files.filter((x) => shapeKindOf(x.name, meshFormats) === "mesh");
      if (meshes.length) {
        const cand = meshMainCandidates(meshes.map((x) => x.name)).map((n) => meshes.find((x) => x.name === n)!.rel);
        const main = cand[0];
        rows.push({
          key: `${uploadId}:${main}`,
          uploadId,
          rel: main,
          fileName: baseName(main),
          bytes: meshes.reduce((a, x) => a + x.size, 0),
          name: defaultShapeName(baseName(main)),
          kind: "mesh",
          source: "mesh",
          meshFiles: meshes.map((x) => x.rel),
          mainCandidates: cand,
          partId: "",
          parts: null,
        });
      }
      // 첫 형상이 들어오면 기준으로(기준 지정 권장 — 바꾸려면 라디오)
      return { ...f, shapes: [...f.shapes, ...rows], refId: f.shapes.length === 0 && rows.length ? rows[0].key : f.refId };
    });
  const patch = (id: string, p: Partial<ShapeRow>) => setForm((f) => ({ ...f, shapes: f.shapes.map((x) => (x.key === id ? { ...x, ...p } : x)) }));
  const remove = (id: string) => setForm((f) => ({ ...f, shapes: f.shapes.filter((x) => x.key !== id), refId: f.refId === id ? null : f.refId }));
  const setRef = (id: string | null) => setForm((f) => ({ ...f, refId: id }));
  const ext = [...STEP_EXT, ...meshFormats];
  return (
    <div className="doe-shapes">
      <UploadDrop
        projectId={projectId}
        label={meshOn ? "비교할 STEP·메시 끌어다 놓기(여러 개)" : "비교할 STEP 끌어다 놓기(여러 개)"}
        display={full ? `최대 ${max}개` : undefined}
        hint={
          meshOn
            ? `STEP 은 파일마다 1행 · .rad/.inc 묶음(주 + include)은 메시 1행 · 최대 ${max}개 · STEP 파일당 ${st.step_max_mb} MB · 메시 ${mi!.max_mb} MB · 같은 좌표계`
            : `여러 파일을 한 번에 놓을 수 있음 · 최대 ${max}개 · 파일당 ${st.step_max_mb} MB · 같은 좌표계로 내보낸 STEP`
        }
        ext={ext}
        validate={validate}
        name={(fs) => `doe_compare_${defaultShapeName(fs[0].name)}`}
        value={null}
        onDone={() => undefined}
        onBatch={addBatch}
        onClear={() => undefined}
        disabled={!allowed || full}
        testId="doe-shapes-drop"
        split
      />
      <div className="table-wrap">
        <table className="table compact doe-shape-table" aria-label="형상 표">
          <thead>
            <tr>
              <th className="doe-ref-col">기준</th>
              {meshOn && <th className="doe-src-col">출처</th>}
              <th>이름</th>
              <th>파일</th>
              {anyMesh && <th className="doe-part-col">파트 ID</th>}
              <th className="num">크기</th>
              <th className="doe-x-col" />
            </tr>
          </thead>
          <tbody>
            <tr className="doe-ref-none">
              <td className="doe-ref-col">
                <input type="radio" name="doe-ref" aria-label="기준 없음(Case 메시)" checked={form.refId === null} onChange={() => setRef(null)} disabled={!allowed} />
              </td>
              <td colSpan={4 + (meshOn ? 1 : 0) + (anyMesh ? 1 : 0)} className="small muted">
                기준 없음(Case 메시) — 첫 ESL 의 낙하 메시를 기준으로
              </td>
            </tr>
            {shapes.map((x, i) => {
              const why = shapeNameProblem(x.name, names, i);
              const src = rowSource(x);
              const kind = x.kind ?? "step";
              const partWhy = src === "mesh" ? partIdProblem(x.partId ?? "") : null;
              const nInc = (x.meshFiles?.length ?? 1) - 1;
              const listId = `doe-parts-${i + 1}`;
              return (
                <tr key={x.key} data-testid={`shape-row-${i + 1}`} className={form.refId === x.key ? "hl" : undefined}>
                  <td className="doe-ref-col">
                    <input type="radio" name="doe-ref" aria-label={`형상 ${i + 1} 기준`} checked={form.refId === x.key} onChange={() => setRef(x.key)} disabled={!allowed} />
                  </td>
                  {meshOn && (
                    <td className="doe-src-col">
                      <div className="seg doe-src-seg" role="group" aria-label={`형상 ${i + 1} 출처`}>
                        {(["step", "mesh"] as const).map((k) => (
                          <button
                            key={k}
                            type="button"
                            className={src === k ? "on" : undefined}
                            aria-pressed={src === k}
                            disabled={!allowed || k !== kind}
                            title={k !== kind ? (kind === "step" ? "STEP 파일은 메시로 읽을 수 없습니다" : "메시 파일은 STEP 으로 읽을 수 없습니다") : undefined}
                            onClick={() => patch(x.key, { source: k })}
                          >
                            {k === "step" ? "STEP" : "메시"}
                          </button>
                        ))}
                      </div>
                    </td>
                  )}
                  <td>
                    <input className="doe-shape-name" aria-label={`형상 ${i + 1} 이름`} aria-invalid={!!why} value={x.name} maxLength={80} onChange={(e) => patch(x.key, { name: e.target.value })} disabled={!allowed} />
                    {why && <div className="small error-text">{why}</div>}
                  </td>
                  <td className="small mono doe-shape-file" title={src === "mesh" ? (x.meshFiles ?? [x.rel]).map(baseName).join("\n") : x.fileName}>
                    {src === "mesh" && (x.mainCandidates?.length ?? 0) > 1 ? (
                      <select aria-label={`형상 ${i + 1} 주 파일`} value={x.rel} disabled={!allowed} onChange={(e) => patch(x.key, { rel: e.target.value, fileName: baseName(e.target.value) })}>
                        {x.mainCandidates!.map((r) => (
                          <option key={r} value={r}>
                            {baseName(r)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      x.fileName
                    )}
                    {src === "mesh" && <span className="muted"> 주 파일{nInc > 0 ? ` + include ${nInc}개` : ""}</span>}
                  </td>
                  {anyMesh && (
                    <td className="doe-part-col">
                      {src === "mesh" && (
                        <>
                          <input
                            type="number"
                            className="doe-part-id"
                            aria-label={`형상 ${i + 1} 파트 ID`}
                            aria-invalid={!!partWhy}
                            min={1}
                            step={1}
                            list={x.parts?.length ? listId : undefined}
                            placeholder={x.parts?.length ? "고르기" : "자동"}
                            value={x.partId ?? ""}
                            onChange={(e) => patch(x.key, { partId: e.target.value })}
                            disabled={!allowed}
                          />
                          {!!x.parts?.length && (
                            <datalist id={listId} data-testid={`parts-${i + 1}`}>
                              {x.parts.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {`${p.title} · 쉘 ${p.n_shells.toLocaleString()}`}
                                </option>
                              ))}
                            </datalist>
                          )}
                          {partWhy && <div className="small error-text">{partWhy}</div>}
                        </>
                      )}
                    </td>
                  )}
                  <td className="num small">{bytes(x.bytes)}</td>
                  <td className="doe-x-col">
                    <button type="button" className="btn small ghost" aria-label={`형상 ${i + 1} 빼기`} onClick={() => remove(x.key)} disabled={!allowed}>
                      ✕
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="small muted" data-testid="shape-count">
        {shapes.length} / {max}개{full ? ` — 최대 ${max}개` : ""}
      </div>
      {form.refId === null && (
        <div className="small warn-text" data-testid="ref-case-warn">
          {CODE_TEXT.COMPARE_REF_CASE_MESH} — 가능하면 기준 STEP 을 고르세요
        </div>
      )}
    </div>
  );
}

/** v0.17.1 형상 실패 칸: 빨간 1줄(머리말 — 앞 "[단계별: …]" 은 뺌) + [자세히] → 전체 문구·시도 목록(높이 고정 스크롤) */
function FailCell({ id, text, tip }: { id: string; text: string; tip: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <span className="fail-cell">
        <span className="small error-text one-line" title={tip || undefined} data-testid={`prep-fail-${id}`}>
          <span className="sr-only">{text}</span>
          <span aria-hidden>{msgHead(text)}</span>
        </span>
        <button type="button" className="msg-fold-more link-btn small" aria-expanded={open} aria-label={`${id} 실패 ${open ? "접기" : "자세히"}`} onClick={() => setOpen((x) => !x)}>
          {open ? "접기" : "자세히"}
        </button>
      </span>
      {open && <div className="msg-fold-body" data-testid={`prep-fail-body-${id}`}>{tip || text}</div>}
    </>
  );
}

/** '메시 방식' 셀 내용(형상 표 열 = 긴 문구, 순위표·ESL별 표 = 짧은 배지) */
export function MeshMethodBadge({ shape, partId, short, testId }: { shape: Parameters<typeof meshMethodLabel>[0]; partId?: number | null; short?: boolean; testId?: string }) {
  if (!shape.mesh_method) return null;
  const tip = meshMethodTip(shape, partId);
  const kind = meshMethodKind(shape);
  const label = short ? MESH_METHOD_SHORT[shape.mesh_method] : meshMethodLabel(shape);
  return (
    <span className={`badge ${kind} doe-mm-badge`} title={tip || undefined} data-testid={testId}>
      {label}
    </span>
  );
}

/** 순위표·ESL별 표 이름 칸: 이름 + 짧은 '메시 방식' 배지(CAD 는 기본이라 생략, §8) */
export function ShapeNameCell({ name, shape, testId }: { name: string; shape?: Parameters<typeof meshMethodLabel>[0] | null; testId?: string }) {
  const show = !!shape?.mesh_method && shape.mesh_method !== "cad";
  return (
    <>
      <span className="doe-name-text">{name}</span>
      {show && (
        <>
          {" "}
          <MeshMethodBadge shape={shape!} short testId={testId} />
        </>
      )}
    </>
  );
}

const pct = (v: number) => `${(v * 100).toFixed(2)} %`;
/** 억제 목록 표 행 상한(§8) */
export const DEFEATURE_ROWS = 50;
const n2 = (v: number) => Number(v.toFixed(2)).toString();

/** ④ 형상 상세 펼침: 억제 목록(종류·중심 xyz·크기·편차, 상위 50행 + "외 n개") */
export function DefeatureList({ studyId, did }: { studyId: string; did: string }) {
  const [data, setData] = useState<DoeDefeatureList | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    doe
      .shapeDefeature(studyId, did)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [studyId, did]);
  if (error) return <ErrorLine text={error} />;
  if (!data) return <span className="small muted">불러오는 중…</span>;
  const rows = data.features.slice(0, DEFEATURE_ROWS);
  const total = Math.max(data.n ?? data.features.length, data.features.length);
  const more = total - rows.length;
  return (
    <div data-testid={`defeat-list-${did}`}>
      <table className="table compact doe-defeat-table" aria-label={`${did} 억제 목록`}>
        <thead>
          <tr>
            <th>종류</th>
            <th>중심 x, y, z (mm)</th>
            <th>크기 (mm)</th>
            <th className="num" title="억제 영역 안 원 STEP 과의 최대 거리">편차 (mm)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f, i) => (
            <tr key={`${f.id}-${i}`}>
              <td>{DEFEATURE_KIND_NAME[f.kind] ?? f.kind}</td>
              <td className="mono">{f.center.map((v) => v.toFixed(1)).join(", ")}</td>
              <td className="mono">{featureSizeText(f)}</td>
              <td className="num mono" title={f.action === "skipped" ? f.reason ?? undefined : undefined}>
                {f.action === "skipped" ? "건너뜀" : f.dev_mm != null ? n2(f.dev_mm) : "–"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {more > 0 && <div className="small muted">외 {more.toLocaleString()}개{data.truncated ? " (목록 상한 — 개수만 기록)" : ""}</div>}
    </div>
  );
}
const statusKind = (s: DoeDesignStatus) => (s === "READY" || s === "OK" ? "ok" : s === "RUNNING" ? "info" : "bad");

/** ④ 상세: 형상 표(준비 결과 — 메시 요소 수·상태·실패 사유). prep.shapes 가 없으면 inputs.shapes + prep.failed */
export function CompareShapeSummary({ study }: { study: DoeStudyOut }) {
  const i = study.inputs;
  const prep = study.prep;
  const failed = new Map((prep?.failed ?? []).map((f) => [f.id, f]));
  const pending: DoeDesignStatus = prep ? "READY" : "RUNNING";
  const rows: DoePrepShape[] =
    prep?.shapes && prep.shapes.length
      ? prep.shapes
      : [
          ...(i.reference_source === "case" ? [{ id: "d000", name: "Case 메시", file_name: null, reference: true, source: "case" as const, status: pending }] : []),
          ...(i.shapes ?? []).map((x) => ({
            id: x.id,
            name: x.name,
            file_name: x.file_name,
            reference: x.reference,
            source: x.source ?? ("step" as const),
            status: failed.get(x.id)?.status ?? pending,
            code: failed.get(x.id)?.code ?? null,
          })),
        ];
  const withQ = rows.filter((r) => r.quality);
  const over = withQ.filter((r) => r.quality!.over_limit);
  const maxFail = withQ[0]?.quality?.max_fail_ratio ?? null;
  const partOf = new Map((i.shapes ?? []).map((x) => [x.id, x.part_id ?? null]));
  const showMethod = rows.some((r) => r.mesh_method);
  const [openDf, setOpenDf] = useState<string | null>(null);
  const nCols = 8 + (showMethod ? 1 : 0);
  return (
    <div className="doe-shape-summary">
      <div className="small" data-testid="doe-input-summary">
        형상 {rows.length}개 · 기준 {i.reference_source === "case" ? "Case 메시" : rows.find((r) => r.reference)?.name ?? "?"}
        {i.inch ? ` · ${i.inch}형` : ""}
        {i.props ? ` · t ${i.props.t} mm · E ${i.props.E.toLocaleString()} MPa · ν ${i.props.nu}` : ""}
        {prep?.mesh?.size_mm != null ? ` · 메시 ${prep.mesh.size_mm} mm` : ""}
        {i.mesh_mode ? ` · 메시 방식 ${MESH_MODE_NAME[i.mesh_mode]}${i.mesh_mode === "auto" && i.mesh_refine === false ? "(세분화 끔)" : ""}` : ""}
        {prep?.mesh?.gmsh_version ? ` (gmsh ${prep.mesh.gmsh_version})` : ""}
      </div>
      {withQ.length > 0 && (
        <div className={`small one-line ${over.length ? "warn-text" : "muted"}`} data-testid="doe-quality-summary" title={over.length ? over.map((r) => r.name).join(", ") : undefined}>
          메시 품질(이슈 #53 기준): Fail 비율 최대 {pct(Math.max(...withQ.map((r) => r.quality!.fail_ratio)))}
          {maxFail != null ? ` · 상한 ${pct(maxFail)}` : ""}
          {over.length
            ? ` — 상한 초과 ${over.length}개(${over.map((r) => r.name).join(", ")}): 결과에 메시 품질 차이가 섞일 수 있습니다(차단 아님)`
            : " — 모든 형상 상한 이내"}
        </div>
      )}
      <div className="table-wrap">
        <table className="table compact doe-shape-table" aria-label="형상 표">
          <thead>
            <tr>
              <th>id</th>
              <th>이름</th>
              <th>파일</th>
              <th className="num">요소</th>
              <th className="num">quad</th>
              <th className="num" title="품질 Fail 요소 비율(Warn 비율)">Fail</th>
              <th className="num" title="삼각형 요소 비율">tria</th>
              {showMethod && <th className="doe-mm-col">메시 방식</th>}
              <th>상태</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.id}>
              <tr data-testid={`prep-shape-${r.id}`}>
                <td className="mono">{r.id}</td>
                <td>
                  {r.name} {r.reference && <span className="badge info">기준</span>}
                  {diagText(r.diag) && (
                    <span className="small muted" title="메시 입력 진단(보고만 — 메시는 그대로). 필요하면 HyperMesh 에서 고치세요" data-testid={`prep-diag-${r.id}`}>
                      {" "}
                      {diagText(r.diag)}
                    </span>
                  )}
                </td>
                <td className="small mono doe-shape-file" title={r.file_name ?? undefined}>
                  {r.file_name ?? "(낙하 메시)"}
                  {r.source === "mesh" && <span className="badge neutral">메시</span>}
                </td>
                <td className="num mono">{r.n_elems != null ? r.n_elems.toLocaleString() : "–"}</td>
                <td className="num mono">{r.quad_ratio != null ? `${(r.quad_ratio * 100).toFixed(0)} %` : "–"}</td>
                <td className="num mono" data-testid={`prep-quality-${r.id}`} title={r.quality ? `Fail ${r.quality.fail_elems.toLocaleString()} · Warn ${r.quality.warn_elems.toLocaleString()} (${pct(r.quality.warn_ratio)})` : undefined}>
                  {r.quality ? (
                    <>
                      {pct(r.quality.fail_ratio)}
                      {r.quality.over_limit && (
                        <span className="badge warn" title={CODE_TEXT.SHAPE_QUALITY_FAIL}>
                          {" "}
                          상한 초과
                        </span>
                      )}
                    </>
                  ) : (
                    "–"
                  )}
                </td>
                <td className="num mono">{r.quality ? `${r.quality.tria_pct.toFixed(1)} %` : "–"}</td>
                {showMethod && (
                  <td className="doe-mm-col" data-testid={`prep-method-${r.id}`}>
                    <MeshMethodBadge shape={r} partId={partOf.get(r.id)} />
                    {r.mesh_method === "defeature" && (
                      <button
                        type="button"
                        className="btn small ghost"
                        aria-expanded={openDf === r.id}
                        aria-label={`${r.id} 억제 목록 ${openDf === r.id ? "접기" : "펼치기"}`}
                        title="억제한 작은 형상 목록(종류·위치·크기·편차)"
                        onClick={() => setOpenDf((x) => (x === r.id ? null : r.id))}
                      >
                        {openDf === r.id ? "▾" : "▸"}
                      </button>
                    )}
                  </td>
                )}
                <td>
                  <span className={`badge ${statusKind(r.status)}`} title={r.code ?? undefined}>
                    {r.status === "READY" ? "준비됨" : r.status === "RUNNING" ? "준비 중" : STATUS_NAME[r.status]}
                  </span>
                  {r.code && r.status !== "READY" && <FailCell id={r.id} text={shapeFailText(r)} tip={shapeFailTip(r)} />}
                </td>
              </tr>
              {openDf === r.id && (
                <tr className="doe-defeat-row">
                  <td colSpan={nCols}>
                    <DefeatureList studyId={study.id} did={r.id} />
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

