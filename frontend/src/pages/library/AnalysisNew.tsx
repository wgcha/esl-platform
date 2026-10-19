// 종합분석 만들기(계약 §3·§4·§11): 설계 대상 · 필터 · 옵션 최소(정규화·대표 수·목적), 나머지는 '고급'(접힘).
// 주 버튼 = "분석 실행"(POST /library/analyses → LIB_ANALYZE 작업) → 상세 화면.
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { errorText } from "../../api/client";
import type { AnalysisFilters, AnalysisOptions, EntryOut, Normalization, Objective } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Card, Empty, ErrorLine, Field, PrimaryButton } from "../../components/ui";
import { usePolling } from "../../lib/usePolling";
import { DROP_LABEL, DROP_TYPES, NORM_LABEL, OBJ_LABEL, VerdictBadge, entryLabel, libPath, matchEntries, sceneText, uniq } from "./common";

const NORM_HINT: Record<Normalization, string> = {
  none: "절대값 그대로",
  mass: "제품 질량 비로 스케일(항목·대상 모두 제품 질량 필요)",
  inch2: "인치² 비로 스케일(면적 비례 가정)",
};

export interface AnalysisForm {
  title: string;
  target: string;
  model: string;
  drops: string[];
  verdict: "" | "PASS" | "FAIL";
  normalization: Normalization;
  nRep: string;
  objective: Objective;
  svdEnergy: string;
  worstCase: boolean;
  scenario: string;
  /** 정규화 대상 값(설계 대상 항목에 메타가 없을 때) */
  targetMass: string;
  targetInch: string;
}

export const DEFAULT_FORM: AnalysisForm = {
  title: "",
  target: "",
  model: "",
  drops: [],
  verdict: "PASS",
  normalization: "none",
  nRep: "5",
  objective: "minmax",
  svdEnergy: "0.9",
  worstCase: false,
  scenario: "",
  targetMass: "",
  targetInch: "",
};

/** 폼 → filters(키마다 목록, 빈 키는 보내지 않음 = 전체) */
export function toFilters(f: AnalysisForm): AnalysisFilters {
  const out: AnalysisFilters = {};
  if (f.model) out.model = [f.model];
  if (f.drops.length) out.drop_type = [...f.drops];
  if (f.verdict) out.verdict = [f.verdict];
  if (f.scenario) out.scenario = [f.scenario];
  return out;
}

const posNum = (s: string) => (s.trim() === "" ? null : Number(s));

/** 폼 검증: 첫 번째 막는 사유(없으면 null) + 필드별 오류. 정규화 메타는 백엔드 _norm_check 와 같은 규칙
 *  (필터에 걸린 항목 모두 + 대상 값[고급 입력 또는 설계 대상 항목]). */
export function validateForm(f: AnalysisForm, entries: EntryOut[] | null) {
  const fieldErr: Partial<Record<"nRep" | "svdEnergy" | "normalization" | "targetMass" | "targetInch", string>> = {};
  const n = Number(f.nRep);
  if (!/^\d+$/.test(f.nRep.trim()) || n < 1 || n > 50) fieldErr.nRep = "1~50 사이 정수";
  const e = Number(f.svdEnergy);
  if (!(Number.isFinite(e) && e > 0 && e <= 1)) fieldErr.svdEnergy = "0 초과 1 이하";
  const tm = posNum(f.targetMass);
  const ti = posNum(f.targetInch);
  if (tm !== null && !(tm > 0)) fieldErr.targetMass = "양수(kg)";
  if (ti !== null && !(ti > 0)) fieldErr.targetInch = "양수";
  const matched = entries ? matchEntries(entries, toFilters(f)) : [];
  const target = entries?.find((x) => x.id === f.target);
  if (f.normalization === "mass" || f.normalization === "inch2") {
    const mass = f.normalization === "mass";
    const miss = matched.filter((x) => !(mass ? x.model.product_mass : x.model.inch));
    const tval = (mass ? tm : ti) ?? (mass ? target?.model.product_mass : target?.model.inch);
    if (miss.length) fieldErr.normalization = `${mass ? "제품 질량" : "인치"}이 없는 항목 ${miss.length}개 — 라이브러리 목록에서 입력하세요`;
    else if (!tval) fieldErr.normalization = `대상 ${mass ? "제품 질량" : "인치"}이 필요합니다 — ${mass ? "질량" : "인치"}이 있는 설계 대상을 고르거나 고급 설정에 입력하세요`;
  }
  const reason = !entries
    ? "불러오는 중…"
    : matched.length === 0
      ? "필터에 맞는 항목이 없습니다"
      : fieldErr.nRep
        ? `대표 케이스 수: ${fieldErr.nRep}`
        : fieldErr.svdEnergy
          ? `SVD 누적 에너지: ${fieldErr.svdEnergy}`
          : fieldErr.targetMass || fieldErr.targetInch
            ? `대상 값: ${fieldErr.targetMass ?? fieldErr.targetInch}`
            : fieldErr.normalization
              ? `정규화: ${fieldErr.normalization}`
              : null;
  return { reason, fieldErr, matched };
}

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.v} type="button" className={value === o.v ? "on" : ""} aria-pressed={value === o.v} onClick={() => onChange(o.v)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function AnalysisNew() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const entries = usePolling(() => api.libraryEntries({ project_id: projectId, status: "ACTIVE" }), 0, [projectId]);
  const [f, setF] = useState<AnalysisForm>(DEFAULT_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof AnalysisForm>(k: K, v: AnalysisForm[K]) => setF((o) => ({ ...o, [k]: v }));
  const list = entries.data ?? [];
  const { reason, fieldErr, matched } = validateForm(f, entries.data);
  const nRep = Number(f.nRep);

  async function submit() {
    setBusy(true);
    setError(null);
    const options: AnalysisOptions = {
      normalization: f.normalization,
      n_representative: nRep,
      objective: f.objective,
      svd_energy: Number(f.svdEnergy),
      worst_case: f.worstCase,
    };
    if (posNum(f.targetMass) !== null) options.target_mass = posNum(f.targetMass);
    if (posNum(f.targetInch) !== null) options.target_inch = posNum(f.targetInch);
    try {
      const a = await api.createAnalysis({
        project_id: projectId,
        title: f.title.trim() || null,
        target_entry_id: f.target || null,
        filters: toFilters(f),
        options,
      });
      nav(`/p/${projectId}/library/analyses/${a.id}`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Shell
      crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "라이브러리", to: libPath(projectId) }, { label: "새 종합분석" }]}
      projectId={projectId}
    >
      <div className="page-title-row">
        <h1 className="page-title">새 종합분석</h1>
        <span className="spacer" />
        <PrimaryButton label="분석 실행" onClick={submit} disabledReason={!allowed ? NO_PERMISSION : reason} busy={busy} />
      </div>
      <ErrorLine text={error ?? entries.error} />
      <div className="grid2">
        <Card title="대상·필터">
          <Field label="제목 (선택)">
            <input aria-label="제목" value={f.title} placeholder="예: QN80H 꼭지점·모서리 강건 비드" onChange={(e) => set("title", e.target.value)} />
          </Field>
          <Field label="설계 대상 모델" hint={f.target ? "이 모델 메시로 하중을 옮겨 비드 최적화 덱(OptiStruct)을 만듭니다" : "없으면 정규화 격자 기준 통계만(최적화 덱 없음)"}>
            <select aria-label="설계 대상 모델" value={f.target} onChange={(e) => set("target", e.target.value)}>
              <option value="">없음 — 정규화 격자 기준</option>
              {list.map((e) => (
                <option key={e.id} value={e.id}>
                  {entryLabel(e)}
                </option>
              ))}
            </select>
          </Field>
          <div className="form-grid">
            <Field label="모델">
              <select aria-label="필터 모델" value={f.model} onChange={(e) => set("model", e.target.value)}>
                <option value="">전체</option>
                {uniq(list.map((e) => e.model.name)).map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </Field>
            <Field label="판정">
              <select aria-label="필터 판정" value={f.verdict} onChange={(e) => set("verdict", e.target.value as AnalysisForm["verdict"])}>
                <option value="PASS">PASS만</option>
                <option value="">전체(확정 FAIL 포함)</option>
              </select>
            </Field>
          </div>
          <Field label="씬 유형">
            <div className="checks">
              {DROP_TYPES.map((d) => (
                <label key={d} className="check">
                  <input
                    type="checkbox"
                    checked={f.drops.length === 0 || f.drops.includes(d)}
                    onChange={(e) => {
                      const cur = f.drops.length === 0 ? [...DROP_TYPES] : f.drops;
                      const next = e.target.checked ? [...cur, d] : cur.filter((x) => x !== d);
                      set("drops", next.length === DROP_TYPES.length ? [] : next);
                    }}
                  />
                  {DROP_LABEL[d]}
                </label>
              ))}
            </div>
          </Field>
        </Card>
        <Card title="옵션">
          <Field label="정규화 (인치 간 하중 크기)" hint={fieldErr.normalization ? <span className="error-text">{fieldErr.normalization}</span> : NORM_HINT[f.normalization]}>
            <Seg label="정규화" value={f.normalization} onChange={(v) => set("normalization", v)} options={(["none", "mass", "inch2"] as Normalization[]).map((v) => ({ v, label: NORM_LABEL[v] }))} />
          </Field>
          <Field
            label="대표 케이스 수"
            hint={
              fieldErr.nRep ? (
                <span className="error-text">{fieldErr.nRep}</span>
              ) : matched.length && nRep > matched.length ? (
                <span className="warn-text">항목 {matched.length}개보다 많아 {matched.length}개로 줄어듭니다</span>
              ) : (
                "SVD + k-medoids 로 실제 씬 중에서 고릅니다"
              )
            }
          >
            <input type="number" aria-label="대표 케이스 수" min={1} max={50} step={1} value={f.nRep} aria-invalid={!!fieldErr.nRep} onChange={(e) => set("nRep", e.target.value)} style={{ width: "7rem" }} />
          </Field>
          <Field label="최적화 목적" hint={f.target ? undefined : "설계 대상이 있을 때만 덱을 만듭니다"}>
            <Seg label="최적화 목적" value={f.objective} onChange={(v) => set("objective", v)} options={(["minmax", "weighted"] as Objective[]).map((v) => ({ v, label: OBJ_LABEL[v] }))} />
          </Field>
        </Card>
      </div>
      <details className="card adv">
        <summary>고급 설정</summary>
        <div className="card-body">
          <div className="form-grid">
            <Field label="SVD 누적 에너지" hint={fieldErr.svdEnergy ? <span className="error-text">{fieldErr.svdEnergy}</span> : "모드 수 = 누적 에너지 도달까지(기본 0.9)"}>
              <input type="number" aria-label="SVD 누적 에너지" min={0.5} max={1} step={0.01} value={f.svdEnergy} aria-invalid={!!fieldErr.svdEnergy} onChange={(e) => set("svdEnergy", e.target.value)} />
            </Field>
            <Field label="시나리오">
              <select aria-label="시나리오" value={f.scenario} onChange={(e) => set("scenario", e.target.value)}>
                <option value="">전체</option>
                {uniq(list.map((e) => e.scene.scenario)).map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
            <Field label="대상 제품 질량 (kg)" hint={fieldErr.targetMass ? <span className="error-text">{fieldErr.targetMass}</span> : "질량 정규화 — 비우면 설계 대상 항목 값"}>
              <input type="number" aria-label="대상 제품 질량" min={0} step="0.1" value={f.targetMass} aria-invalid={!!fieldErr.targetMass} onChange={(e) => set("targetMass", e.target.value)} />
            </Field>
            <Field label="대상 인치" hint={fieldErr.targetInch ? <span className="error-text">{fieldErr.targetInch}</span> : "인치² 정규화 — 비우면 설계 대상 항목 값"}>
              <input type="number" aria-label="대상 인치" min={0} step="1" value={f.targetInch} aria-invalid={!!fieldErr.targetInch} onChange={(e) => set("targetInch", e.target.value)} />
            </Field>
          </div>
          <label className="check">
            <input type="checkbox" checked={f.worstCase} onChange={(e) => set("worstCase", e.target.checked)} /> 군집별 최악(합력 최대) 씬도 하중 케이스로
          </label>
          <div className="small muted">대표 특징·거리·평형 보정·덱 카드 형식은 서버 설정(library)을 따릅니다.</div>
        </div>
      </details>
      <Card title={`포함 항목 ${matched.length}개`}>
        {!entries.data ? (
          <Empty>불러오는 중…</Empty>
        ) : matched.length === 0 ? (
          <Empty>필터에 맞는 항목이 없습니다</Empty>
        ) : (
          <div className="table-wrap scroll">
            <table className="table compact" aria-label="포함 항목">
              <thead>
                <tr>
                  <th>모델</th>
                  <th className="num">인치</th>
                  <th>씬</th>
                  <th>orient</th>
                  <th>판정</th>
                  <th className="num">제품 질량</th>
                </tr>
              </thead>
              <tbody>
                {matched.map((e) => (
                  <tr key={e.id} className={e.id === f.target ? "hl" : undefined}>
                    <td>{e.model.name}</td>
                    <td className="num">{e.model.inch ?? "–"}</td>
                    <td>{sceneText(e)}</td>
                    <td className="mono">{e.scene.orient ?? "–"}</td>
                    <td>
                      <VerdictBadge v={e.quality.verdict} />
                    </td>
                    <td className="num">{e.model.product_mass != null ? `${e.model.product_mass} kg` : <span className={f.normalization === "mass" ? "error-text" : "muted"}>없음</span>}</td>
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
