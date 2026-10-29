// 비드 DOE ① 입력 카드(esl_bead_doe.md §3·§12.2): ESL 목록(같은 모델 ✓/✗ · 다른 모델 빼기) · STEP 끌어다 놓기(기존 청크 업로드) ·
// ② B 메시(rad + include/inc)·파트 제목·인치 · ③ 쉘 물성 3칸(t·E·ν, 서버 기본값)·평균 요소 크기 · 입력 검사 한 줄.
import { useRef, useState } from "react";
import { errorText } from "../api/client";
import { SCENARIO_NAME, warnText } from "../api/doe";
import type { DoeCheckOut, DoeScenario, DoeSettingsOut, DoeStudyOut, EntryOut } from "../api/types";
import { entryKey } from "./ModeSelect";
import { Empty, ErrorLine, Field } from "./ui";
import { Uploader, type UploadProgress } from "../lib/uploader";
import { bytes } from "../lib/format";

export interface UploadedSet {
  uploadId: string;
  names: string[];
}

/** 파일 끌어다 놓기 + 청크 업로드(Uploader). 다 올리면 onDone(uploadId) */
export function UploadDrop({ projectId, label, hint, ext, validate, name, value, onDone, onClear, disabled, testId }: {
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
        <span className="dropzone-title">{value ? value.names.join(", ") : label}</span>
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
}

export const EMPTY_INPUTS: InputsForm = { step: null, mesh: null, partTitle: "", inch: "", t: "", E: "", nu: "", meshSize: "", title: "" };

/** ③ 물성·요소 크기 검사(t>0, E>0, 0≤ν<0.5, 크기 설정 범위) */
export function propsProblem(f: InputsForm, st: DoeSettingsOut): string | null {
  const t = Number(f.t);
  const E = Number(f.E);
  const nu = Number(f.nu);
  if (!(f.t.trim() && t > 0)) return "두께는 0보다 커야 합니다";
  if (!(f.E.trim() && E > 0)) return "E 는 0보다 커야 합니다";
  if (!(f.nu.trim() && nu >= 0 && nu < 0.5)) return "ν 는 0 이상 0.5 미만입니다";
  const h = Number(f.meshSize);
  if (!(f.meshSize.trim() && h >= st.mesh.size_min_mm && h <= st.mesh.size_max_mm)) return `요소 크기는 ${st.mesh.size_min_mm}~${st.mesh.size_max_mm} mm 입니다`;
  return null;
}

const relText = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)} %`;

/** 입력 검사 결과 한 줄 */
function CheckLine({ check, scenario }: { check: DoeCheckOut; scenario: DoeScenario }) {
  return (
    <div className="small" data-testid="doe-check">
      {check.base && scenario === "same" && (
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
      {check.warnings.length > 0 && (
        <ul className="reasons warn-text">
          {check.warnings.map((w, i) => (
            <li key={i}>{warnText(w)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DoeInputs({ projectId, scenario, st, entries, ids, onIds, mismatched, form, setForm, check, checkError, checking, allowed }: {
  projectId: string;
  scenario: DoeScenario;
  st: DoeSettingsOut;
  entries: EntryOut[];
  ids: string[];
  onIds: (ids: string[]) => void;
  /** 다른 모델 ESL(① 에서 ✗) */
  mismatched: string[];
  form: InputsForm;
  setForm: (f: InputsForm) => void;
  check: DoeCheckOut | null;
  checkError: string | null;
  checking: boolean;
  allowed: boolean;
}) {
  const byId = new Map(entries.map((e) => [e.id, e]));
  const set = (k: keyof InputsForm, v: string) => setForm({ ...form, [k]: v });
  const stepOnly = (fs: File[]) => (fs.length !== 1 ? "STEP 파일 1개를 고르세요" : fs[0].size > st.step_max_mb * 1024 ** 2 ? `STEP 은 최대 ${st.step_max_mb} MB 입니다` : null);
  const meshOk = (fs: File[]) => (fs.some((f) => /\.(rad|inc)$/i.test(f.name)) ? null : ".rad(+ include) 또는 .inc 파일이 있어야 합니다");
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
              const bad = scenario === "same" && mismatched.includes(id);
              return (
                <li key={id} className={`chip${bad ? " bad" : ""}`}>
                  {e ? entryKey(e) : id} {scenario === "same" && (bad ? <span className="error-text" title="다른 모델(노드 ID·요소 연결 다름)">✗</span> : <span className="ok-text">✓</span>)}
                </li>
              );
            })}
          </ul>
        )}
        {scenario === "same" && mismatched.length > 0 && (
          <button type="button" className="btn small" onClick={() => onIds(ids.filter((x) => !mismatched.includes(x)))}>
            다른 모델 빼기
          </button>
        )}
      </div>
      <div className="doe-files">
        <UploadDrop
          projectId={projectId}
          label="Ch/R 중립면 STEP 끌어다 놓기"
          hint={`시트(중립면) STEP · 최대 ${st.step_max_mb} MB`}
          ext={[".step", ".stp"]}
          validate={stepOnly}
          name={(fs) => `doe_step_${fs[0].name.replace(/\.[^.]+$/, "")}`}
          value={form.step}
          onDone={(v) => setForm({ ...form, step: v })}
          onClear={() => setForm({ ...form, step: null })}
          disabled={!allowed}
          testId="doe-step-drop"
        />
        {scenario === "mesh" && (
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
      <div className="form-grid tight doe-fields">
        {scenario === "mesh" && (
          <Field label="B 파트 제목">
            <input aria-label="B 파트 제목" value={form.partTitle} placeholder={st.part_title ?? ""} onChange={(e) => set("partTitle", e.target.value)} />
          </Field>
        )}
        {scenario !== "same" && (
          <Field label="인치(선택)">
            <input type="number" aria-label="인치" min={1} value={form.inch} onChange={(e) => set("inch", e.target.value)} />
          </Field>
        )}
        {scenario === "step" && (
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
            <Field label="요소 크기 (mm)" hint={check?.mesh_size_default_mm != null ? `자동: A 중앙값 ${check.mesh_size_default_mm}` : undefined}>
              <input type="number" aria-label="요소 크기 (mm)" step="0.5" min={st.mesh.size_min_mm} max={st.mesh.size_max_mm} value={form.meshSize} onChange={(e) => set("meshSize", e.target.value)} />
            </Field>
          </>
        )}
        <Field label="제목(선택)">
          <input aria-label="제목" maxLength={200} value={form.title} placeholder={`예: 75형 Ch/R ${SCENARIO_NAME[scenario]} 1차`} onChange={(e) => set("title", e.target.value)} />
        </Field>
      </div>
      {checking && <div className="small muted">입력 검사 중…</div>}
      <ErrorLine text={checkError} />
      {check && <CheckLine check={check} scenario={scenario} />}
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
      <div className="small" data-testid="doe-input-summary">
        STEP {i.step.file_name}
        {i.mesh ? ` · B 메시 ${i.mesh.file_name}` : ""}
        {i.part_title ? ` · 파트 ${i.part_title}` : ""}
        {i.inch ? ` · ${i.inch}형` : ""}
        {i.props ? ` · t ${i.props.t} mm · E ${i.props.E.toLocaleString()} MPa · ν ${i.props.nu}` : ""}
        {i.mesh_size_mm ? ` · 요소 ${i.mesh_size_mm} mm` : ""}
      </div>
    </div>
  );
}
