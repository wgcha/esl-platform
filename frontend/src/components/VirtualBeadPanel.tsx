// v0.25.0 ③ 비드 목록·도구 — "추가 비드(평판에 새 비드)" 접힌 절(esl_virtual_bead.md §9·§19.7·§19.9.2).
// 입력: 선(3D 두 점 | ξ·η·길이·각도) + 단면(D·W·θ·끝·r 선택) + 체크 "방향 뒤집기" 1개 → [비드 추가]. 목록 행(상태·경고 배지·[삭제]) · 활성 행 = 깊이 슬라이더 + 변형 미리보기.
// 새 버튼은 [비드 추가]·[삭제] 뿐 — 라디오·슬라이더·체크는 버튼 아님. 계산은 서버(derive) — 이 화면은 입력 검사와 표시만.
import { useEffect, useMemo, useState } from "react";
import { VB_TEXT } from "../api/doe";
import type { DoeVbWarning, DoeVirtualBeadDerived } from "../api/types";
import { previewVar, buildVBead, emptyVbForm, fillFromPicks, formOf, nextVbId, vbProblem, vbRowText, vbStatus, type VbForm } from "../view3d/select/vbead";
import { MorphStage, RO_TIP, type BeadSelectCtrl } from "./BeadSelectCard";

const isInfo = (w: DoeVbWarning) => w.level === "info";
const wText = (w: DoeVbWarning) => w.text || w.code;

export function VirtualBeadPanel({ ctrl, editable }: { ctrl: BeadSelectCtrl; editable: boolean }) {
  const vb = ctrl.vb;
  const cfg = vb.cfg;
  const ro = !editable;
  const [form, setForm] = useState<VbForm>(() => emptyVbForm(cfg.thetaDefault));
  const [open, setOpen] = useState(false);
  const set = (p: Partial<VbForm>) => setForm((f) => ({ ...f, ...p }));
  const frame = vb.frame;
  // 3D 에서 찍은 점 → 좌표·길이·각도 칸(같은 상태)
  useEffect(() => {
    if (vb.pickOn) setForm((f) => fillFromPicks(f, vb.picks, frame));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vb.picks]);
  const pickMode = form.mode === "pick";
  const problem = vbProblem(form, cfg, vb.picks, vb.list.length);
  const id = nextVbId(vb.list, cfg.maxCount);
  const coordEdit = (p: Partial<VbForm>) => {
    // 칸을 직접 고치면 좌표 입력으로 전환(찍은 점은 비움)
    if (pickMode) {
      vb.setPickOn(false);
      set({ ...p, mode: "coord" });
    } else set(p);
  };
  const derivedOf = (i: string): DoeVirtualBeadDerived | null => vb.derived.find((d) => d.id === i) ?? null;
  const act = vb.active ? derivedOf(vb.active) : null;
  const actIn = vb.active ? vb.list.find((x) => x.id === vb.active) ?? null : null;
  const [depth, setDepth] = useState<number | null>(null);
  useEffect(() => setDepth(null), [vb.active]);
  const dMax = actIn?.d_max ?? 1;
  const dVal = depth ?? dMax;
  const pv = useMemo(() => (act ? previewVar(act) : null), [act]);
  const pvVars = useMemo(() => (pv ? [pv] : null), [pv]);
  const pvValues = useMemo(() => (pv ? { [pv.name]: dVal } : {}), [pv, dVal]);
  const skipped = act?.warnings.find((w) => w.code === "VB_PREVIEW_SKIPPED");
  const add = () => {
    if (problem || !id) return;
    const v = buildVBead(form, vb.picks, frame, id);
    if (!v) return;
    vb.add(v);
  };
  const num = (key: keyof VbForm, label: string, extra?: { min?: number; max?: number; step?: number; ph?: string; title?: string }) => (
    <label className="field-inline" title={extra?.title}>
      <span>{label}</span>
      <input type="number" className="doe-num short" aria-label={label} value={String(form[key])} min={extra?.min} max={extra?.max} step={extra?.step ?? "any"} placeholder={extra?.ph} disabled={ro} onChange={(e) => (key === "xi" || key === "eta" || key === "length" || key === "angle" ? coordEdit({ [key]: e.target.value }) : set({ [key]: e.target.value }))} />
    </label>
  );
  return (
    <details className="bs-vb" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)} data-testid="bs-vb">
      <summary title={VB_TEXT.tip} data-testid="bs-vb-summary">
        {VB_TEXT.section}
        {vb.list.length > 0 && <span className="small muted"> · {vb.list.length}개</span>}
      </summary>
      <div className="bs-vb-body small">
        <div className="bs-vb-line" data-testid="bs-vb-line">
          <span className="seg" role="radiogroup" aria-label="입력 방식">
            <label className="check-field">
              <input type="radio" name="bs-vb-mode" checked={pickMode} disabled={ro} onChange={() => (set({ mode: "pick" }), vb.setPickOn(true))} data-testid="bs-vb-mode-pick" />
              <span>3D 에서 두 점</span>
            </label>
            <label className="check-field">
              <input type="radio" name="bs-vb-mode" checked={!pickMode} disabled={ro} onChange={() => (set({ mode: "coord" }), vb.setPickOn(false))} data-testid="bs-vb-mode-coord" />
              <span>좌표·길이·각도</span>
            </label>
          </span>
          {num("xi", "ξ", { title: "시작점 ξ(mm) — 판의 ESL frame" })}
          {num("eta", "η", { title: "시작점 η(mm)" })}
          {num("length", "길이", { min: 0, title: "길이(mm)" })}
          {num("angle", "각도", { min: -180, max: 180, title: "각도(°) — +ξ 기준, +η 쪽이 +" })}
          {pickMode && (
            <span className="muted" data-testid="bs-vb-pickhint">
              평판 위 두 점을 찍으세요({Math.min(vb.picks.length, 2)}/2)
            </span>
          )}
        </div>
        <div className="bs-vb-line" data-testid="bs-vb-section">
          {num("dMax", "D 최대", { min: 0, max: cfg.dMaxLimit, title: `최대 깊이(mm, ≤ ${cfg.dMaxLimit}) — 변수 값 = 실제 깊이` })}
          {num("wTop", "W", { min: 0, title: "깊이면 폭(mm)" })}
          {num("theta", "θ", { min: cfg.thetaRange[0], max: cfg.thetaRange[1], title: `사면 각(°, ${cfg.thetaRange[0]}~${cfg.thetaRange[1]})` })}
          <label className="field-inline">
            <span>끝</span>
            <select aria-label="끝 모양" value={form.end} disabled={ro} onChange={(e) => set({ end: e.target.value as "round" | "square" })}>
              <option value="round">반원</option>
              <option value="square">사각</option>
            </select>
          </label>
          {num("r", "r", { min: 0, ph: "요소 크기", title: "모서리 반경(mm) — 비우면 요소 크기, 0 = 각진 모서리" })}
          <label className="check-field" title="기본은 자동 방향(평탄부가 들어간 쪽·기존 비드 다수 쪽). 켜면 반대쪽으로 누릅니다">
            <input type="checkbox" checked={form.flip} disabled={ro} onChange={(e) => set({ flip: e.target.checked })} data-testid="bs-vb-flip" />
            <span>방향 뒤집기</span>
          </label>
          <button type="button" className="btn small" disabled={ro || !!problem || !id} title={ro ? RO_TIP : problem ?? undefined} onClick={add} data-testid="bs-vb-add">
            비드 추가
          </button>
        </div>
        {problem && !ro && (vb.picks.length > 0 || form.xi || form.dMax) && (
          <div className="muted" data-testid="bs-vb-problem">
            {problem}
          </div>
        )}
        {vb.list.map((v) => {
          const d = derivedOf(v.id);
          const st = vbStatus(d);
          const ws = (d?.warnings ?? []).filter((w) => !isInfo(w) && w.code !== "VB_PREVIEW_SKIPPED");
          const on = vb.active === v.id;
          return (
            <div key={v.id} className={`bs-vb-row${on ? " on" : ""}`} role="button" tabIndex={0} aria-pressed={on} data-testid={`bs-vb-row-${v.id}`} onClick={() => (vb.setActive(on ? null : v.id), !on && (vb.setPickOn(false), setForm(formOf(v, frame, cfg.thetaDefault))))} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), vb.setActive(on ? null : v.id))}>
              <span className="mono">{vbRowText(v, d, cfg.thetaDefault)}</span>
              {v.flip && <span className="badge neutral" title="자동 방향의 반대쪽">뒤집음</span>}
              {st && (
                <span className={`badge ${st.ok ? "info" : "neutral"}`} title={st.tip || undefined} data-testid={`bs-vb-status-${v.id}`} data-ok={st.ok}>
                  {st.text}
                </span>
              )}
              {!st && ctrl.deriving && <span className="muted">계산 중…</span>}
              {ws.length > 0 && (
                <span className="badge warn" title={ws.map(wText).join("\n")} data-testid={`bs-vb-warn-${v.id}`}>
                  ⚠{ws.length}
                </span>
              )}
              {d?.r_resolved != null && d.ok && (
                <span className="muted" title="모서리 반경 r(mm) — 비우면 요소 크기">
                  r {+d.r_resolved.toFixed(2)}
                  {d.r_source === "default" ? "(기본)" : ""}
                </span>
              )}
              {d?.host && d.host !== "base" && <span className="muted">평탄부</span>}
              <button
                type="button"
                className="btn small ghost icon bs-del"
                aria-label={`${v.id.toUpperCase()} 삭제`}
                disabled={ro}
                title={ro ? RO_TIP : "이 추가 비드를 지웁니다(실행 취소 가능)"}
                onClick={(e) => {
                  e.stopPropagation();
                  vb.remove(v.id);
                }}
              >
                ✕
              </button>
            </div>
          );
        })}
        {act && actIn && (
          <div className="bs-vb-preview" data-testid="bs-vb-preview">
            <label className="range-field">
              <span>깊이</span>
              <input type="range" min={0} max={dMax} step={dMax / 100} value={dVal} aria-label="미리보기 깊이(mm)" onChange={(e) => setDepth(Number(e.target.value))} />
              <span className="mono small range-val">{+dVal.toFixed(2)} mm</span>
            </label>
            {pvVars && ctrl.data ? (
              <MorphStage did={act.id.toUpperCase()} glb={ctrl.data.glb} vars={pvVars} values={pvValues} vmax={dMax} testId="pv-vbead" designLabel="추가 비드" />
            ) : (
              <div className="muted" data-testid="bs-vb-nopreview">
                {skipped ? wText(skipped) : act.ok ? "미리보기 자료 없음" : "추가할 수 없는 자리라 미리보기가 없습니다"}
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
