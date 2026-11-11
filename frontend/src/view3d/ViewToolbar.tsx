// v0.15.1 3D 시점 툴바(비드 선택 3D · 안 3D 보기 · 3D 하중 보기 공통): 정면 ±X·±Y·±Z(같은 축 다시 = 반대 방향), 등각, 꽉 차게, 선택 영역 맞춤.
// 작은 아이콘 한 줄 — 3D 칸 오른쪽 위에 겹쳐 둔다(도구 줄 폭·주 버튼 규칙과 무관). 단축키(3D 칸에 초점): 1 = 정면(−Y), 3 = 오른쪽(+X), 7 = 위(+Z),
// 같은 키 다시 = 반대쪽, 0 = 등각, F = 꽉 차게.
import { useEffect, useRef, useState, type RefObject } from "react";
import type { SceneApi } from "./sceneApi";
import { nextSign, viewLabel, type Bbox, type ViewAxis, type ViewSign } from "./viewFit";

/** 단축키 → [축, 처음 방향] */
export const VIEW_KEYS: Record<string, [ViewAxis, ViewSign]> = { "1": ["y", -1], "3": ["x", 1], "7": ["z", 1], "0": ["iso", 1] };

export function ViewToolbar({
  scene,
  modelBbox,
  disabled,
  selectionBbox,
  keyTarget,
}: {
  /** 현재 장면(없으면 버튼 비활성) */
  scene: () => SceneApi | null;
  /** 모델 전체 bbox(꽉 차게 보기) */
  modelBbox: Bbox;
  disabled?: boolean;
  /** 선택 영역 bbox(없으면 '선택 맞춤' 버튼 숨김, null 반환 = 선택 없음 → 비활성) */
  selectionBbox?: () => Bbox | null;
  /** 단축키를 받을 3D 칸 */
  keyTarget?: RefObject<HTMLElement | null>;
}) {
  const [last, setLast] = useState<{ axis: ViewAxis; sign: ViewSign } | null>(null);
  const lastRef = useRef(last);
  lastRef.current = last;
  const view = (axis: ViewAxis, first?: ViewSign) => {
    const sc = scene();
    if (!sc || disabled) return;
    const l = lastRef.current;
    const sign = l && l.axis === axis ? nextSign(l, axis) : first ?? 1;
    sc.setView(axis, sign);
    setLast({ axis, sign });
  };
  const fitAll = () => {
    if (!disabled) scene()?.fit(modelBbox);
  };
  const fitSel = () => {
    const b = selectionBbox?.();
    if (!disabled && b) scene()?.fit(b);
  };
  const viewRef = useRef(view);
  viewRef.current = view;
  const fitRef = useRef(fitAll);
  fitRef.current = fitAll;

  useEffect(() => {
    const el = keyTarget?.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName)) return;
      const k = VIEW_KEYS[e.key];
      if (k) {
        e.preventDefault();
        viewRef.current(k[0], k[1]);
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        fitRef.current();
      }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [keyTarget]);

  const off = disabled || !scene();
  const axisBtn = (axis: "x" | "y" | "z") => {
    const on = last?.axis === axis;
    const sign: ViewSign = on ? last!.sign : 1;
    const nxt: ViewSign = on ? ((-sign) as ViewSign) : 1;
    return (
      <button
        key={axis}
        type="button"
        className={`btn small ghost icon v3d-vbtn${on ? " on" : ""}`}
        aria-label={`${axis.toUpperCase()} 보기`}
        aria-pressed={on}
        title={`${on ? `지금 ${viewLabel(axis, sign)} — 다시 누르면 ` : ""}${viewLabel(axis, nxt)}${axis === "x" ? " (단축키 3)" : axis === "y" ? " (단축키 1 = −Y)" : " (단축키 7)"}`}
        disabled={off}
        onClick={() => view(axis)}
      >
        {on ? `${sign > 0 ? "+" : "−"}${axis.toUpperCase()}` : axis.toUpperCase()}
      </button>
    );
  };
  const selB = selectionBbox ? selectionBbox() : null;
  return (
    <div className="v3d-view-bar" role="toolbar" aria-label="시점" data-testid="v3d-view-bar">
      {axisBtn("x")}
      {axisBtn("y")}
      {axisBtn("z")}
      <button type="button" className={`btn small ghost icon v3d-vbtn${last?.axis === "iso" ? " on" : ""}`} aria-label="등각 보기" title={`${viewLabel("iso", last?.axis === "iso" ? ((-last.sign) as ViewSign) : 1)} (단축키 0)`} disabled={off} onClick={() => view("iso")}>
        <IsoIcon />
      </button>
      <button type="button" className="btn small ghost icon v3d-vbtn" aria-label="꽉 차게 보기" title="모델 전체가 꽉 차게 — 지금 방향 그대로 (단축키 F)" disabled={off} onClick={fitAll}>
        <FitIcon />
      </button>
      {selectionBbox && (
        <button type="button" className="btn small ghost icon v3d-vbtn" aria-label="선택 영역에 맞추기" title={selB ? "선택한 비드 영역이 꽉 차게 — 지금 방향 그대로" : "선택한 요소가 없습니다"} disabled={off || !selB} onClick={fitSel}>
          <FitSelIcon />
        </button>
      )}
    </div>
  );
}

const svgProps = { width: 14, height: 14, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.4, "aria-hidden": true } as const;
function IsoIcon() {
  return (
    <svg {...svgProps}>
      <path d="M8 1.8 13.5 5v6L8 14.2 2.5 11V5z" />
      <path d="M2.5 5 8 8.2 13.5 5M8 8.2v6" />
    </svg>
  );
}
export function FitIcon() {
  return (
    <svg {...svgProps}>
      <path d="M2 5.5V2h3.5M10.5 2H14v3.5M14 10.5V14h-3.5M5.5 14H2v-3.5" />
      <rect x="5" y="5" width="6" height="6" rx="0.5" />
    </svg>
  );
}
export function FitSelIcon() {
  return (
    <svg {...svgProps}>
      <path d="M2 5.5V2h3.5M10.5 2H14v3.5M14 10.5V14h-3.5M5.5 14H2v-3.5" />
      <circle cx="8" cy="8" r="2.6" fill="currentColor" stroke="none" />
    </svg>
  );
}
