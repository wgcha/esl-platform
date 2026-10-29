// 라이브러리 항목 메타 수정 대화상자(v0.8.0): 모델(모델명·인치·버전·날짜·제품 질량)·씬(프로젝트·시나리오·순번·낙하 유형·라운드·
// 씬 번호·orient·접미사·변형)·메모 → PATCH /library/entries/{id}(바꾼 필드만, version 잠금). 권한 = power 이상 + 등록자 또는 관리자
// (서버 patch_entry 와 같은 규칙). 409 VERSION_CONFLICT 이면 오류 문구 + [최신 값 불러오기]. 폐기도 같은 권한.
import { useState } from "react";
import { api } from "../../api/endpoints";
import { ApiError, errorText } from "../../api/client";
import type { EntryOut, EntryPatch, Me } from "../../api/types";
import { NO_PERMISSION, canRun } from "../../app/AppContext";
import { entryKey } from "../../components/ModeSelect";
import { DROP_LABEL, DROP_TYPES } from "./common";

/** 메타 수정 불가 사유(null = 가능): 조회 권한 → NO_PERMISSION, 등록자·관리자 아님 → 등록자 안내 */
export function editBlock(me: Me | null, e: EntryOut): string | null {
  if (!canRun(me, e.project_id)) return NO_PERMISSION;
  if (me!.is_global_admin || me!.roles[e.project_id] === "admin" || me!.user_id === e.registered_by) return null;
  return `등록자(${e.registered_by_name}) 또는 관리자만 수정할 수 있습니다`;
}

const MODEL_F = ["name", "inch", "version", "date", "product_mass"] as const;
const SCENE_F = ["project", "scenario", "seq", "drop_type", "round", "scene_no", "orient", "suffix", "variant"] as const;
type ModelF = (typeof MODEL_F)[number];
type SceneF = (typeof SCENE_F)[number];
export type EditForm = Record<ModelF | SceneF | "note", string>;

const str = (v: unknown) => (v == null ? "" : String(v));
export function formOf(e: EntryOut): EditForm {
  const f = { note: str(e.note) } as EditForm;
  for (const k of MODEL_F) f[k] = str(e.model[k]);
  for (const k of SCENE_F) f[k] = str(e.scene[k]);
  return f;
}

// 서버 schemas.EntryModelPatch·EntryScenePatch 와 같은 제약(문자열 최대 길이, 정수·양수, orient 형식)
const MAXLEN: Partial<Record<keyof EditForm, number>> = { name: 200, version: 64, date: 32, project: 200, scenario: 200, round: 32, suffix: 32, variant: 64, note: 2000 };
const INT: Partial<Record<keyof EditForm, { min: number; max?: number; msg: string }>> = {
  inch: { min: 1, max: 1000, msg: "인치는 1~1000 정수" },
  seq: { min: 0, msg: "순번은 0 이상 정수" },
  scene_no: { min: 0, msg: "씬 번호는 0 이상 정수" },
};

/** 입력 검사 + 바꾼 필드만 담은 PATCH 본문. 반환 errors = 필드별 문구, patch = null 이면 바뀐 것 없음 */
export function buildPatch(e: EntryOut, f: EditForm, version: number): { errors: Partial<Record<keyof EditForm, string>>; patch: EntryPatch | null } {
  const errors: Partial<Record<keyof EditForm, string>> = {};
  const init = formOf(e);
  const val = (k: keyof EditForm): string | number | null => {
    const t = f[k].trim();
    if (t === "") return null;
    const lim = MAXLEN[k];
    if (lim && t.length > lim) errors[k] = `${lim}자 이하`;
    const ic = INT[k];
    if (ic) {
      const n = Number(t);
      if (!Number.isInteger(n) || n < ic.min || (ic.max != null && n > ic.max)) errors[k] = ic.msg;
      return n;
    }
    if (k === "product_mass") {
      const n = Number(t);
      if (!(Number.isFinite(n) && n > 0)) errors[k] = "제품 질량은 양수(kg)";
      return n;
    }
    if (k === "orient" && !/^[1-6]{1,3}$/.test(t)) errors[k] = "ISTA 면 번호 1~6, 1~3자리";
    return t;
  };
  const changed = (k: keyof EditForm) => f[k].trim() !== init[k].trim();
  if (!f.name.trim() && changed("name")) errors.name = "모델명은 비울 수 없습니다";
  const model: Record<string, unknown> = {};
  const scene: Record<string, unknown> = {};
  for (const k of MODEL_F) {
    const v = val(k);
    if (changed(k)) model[k] = v;
  }
  for (const k of SCENE_F) {
    const v = val(k);
    if (changed(k)) scene[k] = v;
  }
  const note = val("note");
  const body: EntryPatch = { version };
  if (Object.keys(model).length) body.model = model;
  if (Object.keys(scene).length) body.scene = scene as EntryPatch["scene"];
  if (changed("note")) body.note = note as string | null;
  const any = body.model || body.scene || "note" in body;
  return { errors, patch: any ? body : null };
}

type Spec = { k: keyof EditForm; label: string; type?: "number" | "text"; mono?: boolean; hint?: string; placeholder?: string };
const MODEL_UI: Spec[] = [
  { k: "name", label: "모델명" },
  { k: "inch", label: "인치", type: "number", hint: "바꾸면 비드 최적화 '같은 크기' 판정이 새 인치로" },
  { k: "version", label: "모델 버전" },
  { k: "date", label: "날짜", placeholder: "YYYY-MM-DD" },
  { k: "product_mass", label: "제품 질량 (kg)", type: "number", hint: "종합분석 질량 정규화에 사용" },
];
const SCENE_UI: Spec[] = [
  { k: "project", label: "프로젝트" },
  { k: "scenario", label: "시나리오" },
  { k: "seq", label: "순번", type: "number" },
  { k: "round", label: "라운드" },
  { k: "scene_no", label: "씬 번호", type: "number" },
  { k: "orient", label: "orient", mono: true, hint: "ISTA 면 번호 1~6, 1~3자리" },
  { k: "suffix", label: "접미사" },
  { k: "variant", label: "변형" },
];

export function EntryEditDialog({ e, onClose, onSaved, reload }: { e: EntryOut; onClose: () => void; onSaved: (out: EntryOut | null, before: EntryOut) => void; reload: () => Promise<EntryOut | null> }) {
  const [base, setBase] = useState(e);
  const [f, setF] = useState<EditForm>(() => formOf(e));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [confirmRetire, setConfirmRetire] = useState(false);
  const { errors, patch } = buildPatch(base, f, base.version);
  const bad = Object.keys(errors).length > 0;
  const set = (k: keyof EditForm, v: string) => setF((o) => ({ ...o, [k]: v }));

  async function run(fn: () => Promise<EntryOut>, retire = false) {
    setBusy(true);
    setError(null);
    try {
      const out = await fn();
      onSaved(retire ? null : out, base);
    } catch (x) {
      setStale(x instanceof ApiError && x.code === "VERSION_CONFLICT");
      setError(errorText(x));
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    const fresh = await reload();
    setBusy(false);
    if (!fresh) return setError("항목을 다시 불러오지 못했습니다");
    setBase(fresh);
    setF(formOf(fresh));
    setStale(false);
    setError(null);
  }
  const input = (s: Spec) => (
    <label className="field" key={s.k}>
      <span className="field-label">{s.label}</span>
      <input
        aria-label={s.label}
        type={s.type ?? "text"}
        className={s.mono ? "mono" : undefined}
        step={s.k === "product_mass" ? "0.1" : s.type === "number" ? "1" : undefined}
        value={f[s.k]}
        placeholder={s.placeholder}
        maxLength={MAXLEN[s.k]}
        aria-invalid={!!errors[s.k]}
        onChange={(x) => set(s.k, x.target.value)}
      />
      {errors[s.k] ? <span className="field-hint error-text">{errors[s.k]}</span> : s.hint && <span className="field-hint">{s.hint}</span>}
    </label>
  );

  return (
    <div className="modal-backdrop" onClick={(x) => x.target === x.currentTarget && !busy && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-labelledby="entry-edit-title" data-testid="entry-edit">
        <h3 id="entry-edit-title">라이브러리 항목 수정 — {entryKey(base)}</h3>
        <fieldset className="form-grid tight">
          <legend className="field-label">모델</legend>
          {MODEL_UI.map(input)}
        </fieldset>
        <fieldset className="form-grid tight">
          <legend className="field-label">씬</legend>
          {SCENE_UI.slice(0, 3).map(input)}
          <label className="field">
            <span className="field-label">낙하 유형</span>
            <select aria-label="낙하 유형" value={f.drop_type} onChange={(x) => set("drop_type", x.target.value)}>
              <option value="">?</option>
              {DROP_TYPES.map((d) => (
                <option key={d} value={d}>
                  {DROP_LABEL[d]}
                </option>
              ))}
            </select>
            <span className="field-hint">orient·낙하 유형을 바꾸면 분류(drop_class)를 다시 계산</span>
          </label>
          {SCENE_UI.slice(3).map(input)}
        </fieldset>
        <label className="field">
          <span className="field-label">메모</span>
          <textarea aria-label="메모" rows={2} value={f.note} maxLength={MAXLEN.note} onChange={(x) => set("note", x.target.value)} />
        </label>
        <div className="small muted">항목 폴더(entry.json)는 등록 때 그대로 두고 서버 DB 메타만 바뀝니다 · 등록 {base.registered_by_name}</div>
        {error && (
          <div className="error-text small" role="alert">
            {error}
            {stale && (
              <>
                {" "}
                <button type="button" className="link small" disabled={busy} onClick={() => void refresh()}>
                  최신 값 불러오기
                </button>
              </>
            )}
          </div>
        )}
        <div className="actions modal-actions">
          {confirmRetire ? (
            <>
              <span className="small error-text">폐기할까요?</span>
              <button type="button" className="btn small danger" disabled={busy} onClick={() => void run(() => api.retireEntry(base.id), true)}>
                폐기
              </button>
              <button type="button" className="btn small ghost" onClick={() => setConfirmRetire(false)}>
                아니오
              </button>
            </>
          ) : (
            <>
              <button type="button" className="link small error-text" onClick={() => setConfirmRetire(true)} title="분석에서 빼고 보관(정정 = 새로 등록 + 이전 것 폐기)">
                폐기…
              </button>
              <span className="spacer" />
              <button type="button" className="btn ghost" disabled={busy} onClick={onClose}>
                취소
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy || bad || !patch || stale}
                title={bad ? Object.values(errors)[0] : !patch ? "바뀐 값이 없습니다" : undefined}
                onClick={() => patch && void run(() => api.patchEntry(base.id, patch))}
              >
                저장
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

