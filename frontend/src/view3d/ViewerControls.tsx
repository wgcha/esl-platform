// v0.24.6 시점 막대의 [경계조건][하중] 칩 + ⚙ 팝오버(esl_viewer_hv.md §2·§3).
// 칩 = 글자 토글(aria-pressed, 켬 = 지금 .on 색). ⚙ 팝오버는 막대 아래 절대 위치(레이아웃 영향 0) — Esc·바깥 클릭 닫힘, 키보드 순회.
import { useEffect, useId, useRef, useState } from "react";
import { LEVEL_CHOICES, planOf, type ViewerLayer } from "./viewerPlan";
import type { ViewerStore } from "./viewerSync";

export const NO_BC_TITLE = "이 보기에 경계조건 표식이 없습니다";
export const NO_LOAD_TITLE = "이 보기에 하중 화살표가 없습니다";
export const NO_GHOST_TITLE = "변형 형상을 켠 뒤에 쓸 수 있습니다";

export interface ViewerControlsProps {
  store: ViewerStore;
  /** 데이터가 있어 켤 수 있는 층(표식 0개·화살표 0개면 칩 비활성) */
  hasBc: boolean;
  hasLoad: boolean;
  /** 변형 형상 켜짐(원형 겹쳐 보기 활성 조건) */
  deformOn: boolean;
  /** 막대가 칸 폭의 60 % 를 넘으면 칩 글자를 줄임 */
  compact?: boolean;
  /** v0.24.9 [경계조건] 칩 툴팁 범례 줄(기호별 한 줄 뜻 — supportMarks.markLegend). 없으면 지금 툴팁 그대로 */
  bcLegend?: string[] | null;
}

export function ViewerChips({ store, hasBc, hasLoad, compact, bcLegend }: ViewerControlsProps) {
  const plan = planOf(store.planKey);
  const { state, set } = store;
  const chip = (layer: "bc" | "load", full: string, short: string, has: boolean, noTitle: string, key: string, legend?: string[] | null) => {
    if (!plan.layers.includes(layer as ViewerLayer)) return null;
    const on = state[layer] && has;
    return (
      <button
        key={layer}
        type="button"
        className={`btn small ghost v3d-vbtn v3d-chip${on ? " on" : ""}`}
        aria-pressed={on}
        aria-label={full}
        title={has ? `${full} 표식 ${on ? "끄기" : "켜기"} (단축키 ${key})${legend?.length ? `\n${legend.join("\n")}` : ""}` : noTitle}
        disabled={!has}
        data-testid={`v3d-layer-${layer}`}
        onClick={() => set({ [layer]: !state[layer] })}
      >
        {compact ? short : full}
      </button>
    );
  };
  return (
    <>
      {chip("bc", "경계조건", "경계", hasBc, NO_BC_TITLE, "B", bcLegend)}
      {chip("load", "하중", "하중", hasLoad, NO_LOAD_TITLE, "L")}
      <span className="v3d-bar-sep" aria-hidden="true" />
    </>
  );
}

const GearIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
    <circle cx="8" cy="8" r="2.2" />
    <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4" />
  </svg>
);

export function ViewerGear({ store, deformOn }: ViewerControlsProps) {
  const plan = planOf(store.planKey);
  const { state, set } = store;
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const first = pop.current?.querySelector<HTMLElement>("input:not(:disabled), button:not(:disabled)");
    first?.focus();
    const onDoc = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && open) {
      e.stopPropagation();
      setOpen(false);
      btn.current?.focus();
    }
  };
  const ghostOk = deformOn;
  return (
    <span className="v3d-gear" ref={wrap} onKeyDown={onKey}>
      <span className="v3d-bar-sep" aria-hidden="true" />
      <button
        ref={btn}
        type="button"
        className={`btn small ghost icon v3d-vbtn${open ? " on" : ""}`}
        aria-label="뷰어 설정"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        title="뷰어 설정 — 원형 겹쳐 보기 · 최대 표식 · 범례 구간"
        data-testid="v3d-gear"
        onClick={() => setOpen((x) => !x)}
      >
        <GearIcon />
      </button>
      {open && (
        <div ref={pop} id={id} className="v3d-viewer-pop" role="dialog" aria-label="뷰어 설정" data-testid="v3d-viewer-pop">
          {plan.layers.includes("ghost") && (
            <label className="check-field" title={ghostOk ? "변형 전 형상의 외곽선·접힘선을 회색으로 겹쳐 봅니다" : NO_GHOST_TITLE}>
              <input type="checkbox" checked={state.ghost && ghostOk} disabled={!ghostOk} onChange={(e) => set({ ghost: e.target.checked })} data-testid="v3d-opt-ghost" />
              <span>원형 겹쳐 보기</span>
            </label>
          )}
          {plan.layers.includes("marks") && (
            <label className="check-field" title="지금 칠한 값의 최대 위치·값·노드 ID 를 표시합니다">
              <input type="checkbox" checked={state.marks} onChange={(e) => set({ marks: e.target.checked })} data-testid="v3d-opt-marks" />
              <span>최대 표식</span>
            </label>
          )}
          <div className="v3d-pop-row">
            <span className="small">범례</span>
            <div className="seg" role="group" aria-label="범례 구간" data-testid="v3d-opt-levels">
              {LEVEL_CHOICES.map((l) => (
                <button key={l} type="button" className={state.levels === l ? "on" : ""} aria-pressed={state.levels === l} data-levels={l} onClick={() => set({ levels: l })}>
                  {l === 0 ? "연속" : l}
                </button>
              ))}
            </div>
          </div>
          <div className="small muted">이 브라우저에 기억됩니다</div>
        </div>
      )}
    </span>
  );
}
