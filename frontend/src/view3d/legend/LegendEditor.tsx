// v0.25.1 범례 편집(계약 §5.3·§5.4) — 팝오버 내용. 범례를 누르면 뜨는 팝오버와 ⚙ 팝오버의 `범례` 절이 같은 컴포넌트(진입 2곳, 내용 1개).
// 순서: 레벨 수·연속 · 최대 · 최소 · 눈금 · 숫자 · 범위 밖 · 색 순서 뒤집기 · 표식(최대·최소·umax) · [기본값으로] · 기억 안내.
// 제어 컴포넌트 — 상태는 View3DCard 의 뷰어 저장소(쌍은 공유)에 있고, 여기는 화면만 그린다. three import 없음.
import { useEffect, useId, useRef } from "react";
import { NumInput } from "../../components/ColorLegend";
import { DIGITS_MAX, LEVELS_MAX, LEVELS_MIN, type ColorModeRow, type LegendSettings, type NumFormat, type OutMode, type Range } from "./legendModel";

export const LOG_WHY_SIGNED = "로그는 값이 양수인 모드(응답 변위·하중)에서만 쓸 수 있습니다 — C 기여도·차이는 부호가 있습니다";
export const LOG_WHY_RANGE = "로그는 최대 값이 0 보다 클 때만 쓸 수 있습니다";

export interface LegendEditorProps {
  settings: LegendSettings;
  onChange: (patch: Partial<LegendSettings>) => void;
  /** 지금 쓰는 범위(자동이면 자동값, 직접 입력이면 그 값) */
  range: Range;
  /** 직접 입력 여부(null = 자동) */
  manMin: number | null;
  manMax: number | null;
  /** 범위 직접 입력·자동으로 되돌림: null = 자동 */
  onRange: (r: { min?: number | null; max?: number | null }) => void;
  mode: ColorModeRow;
  /** 로그 가능(모드·범위) — 아니면 로그 버튼 비활성 + 사유 */
  logOk: boolean;
  /** 최대 표식 켬·끔(층 marks) */
  marksOn: boolean;
  onMarks: (on: boolean) => void;
  /** 표식 줄에서 보일 항목: all = 최대·최소·umax, extra = 최소·umax(⚙ 팝오버에는 최대 표식 체크가 따로 있음) */
  marksRow?: "all" | "extra";
  /** umax 핀 자료가 있어 켤 수 있음(없으면 체크 비활성) */
  hasPin: boolean;
  onReset: () => void;
  testPrefix?: string;
}

export function LegendEditor({ settings: s, onChange, range, manMin, manMax, onRange, mode, logOk, marksOn, onMarks, marksRow = "all", hasPin, onReset, testPrefix = "v3d-leg" }: LegendEditorProps) {
  const t = (k: string) => `${testPrefix}-${k}`;
  const seg = <T extends string>(key: string, label: string, items: { v: T; text: string; off?: boolean; title?: string }[], cur: T, set: (v: T) => void) => (
    <div className="seg" role="group" aria-label={label} data-testid={t(key)}>
      {items.map((i) => (
        <button key={i.v} type="button" className={cur === i.v ? "on" : ""} aria-pressed={cur === i.v} disabled={i.off} title={i.title} data-v={i.v} onClick={() => set(i.v)}>
          {i.text}
        </button>
      ))}
    </div>
  );
  const maxLabel = mode.sym ? "범위 ±R" : "범위 최대";
  return (
    <div className="v3d-leg-ed" data-testid={t("ed")}>
      <div className="v3d-pop-row">
        <span className="small">레벨</span>
        <NumInput
          label="레벨 수"
          value={s.levels}
          testId={t("levels")}
          onCommit={(v) => {
            if (!Number.isInteger(v) || v < LEVELS_MIN || v > LEVELS_MAX) return false;
            onChange({ levels: v });
            return true;
          }}
        />
        <label className="check-field" title="체크 = 색을 계단 없이 이어서 칠함(레벨 수 무시)">
          <input type="checkbox" checked={s.continuous} onChange={(e) => onChange({ continuous: e.target.checked })} data-testid={t("cont")} />
          <span>연속</span>
        </label>
      </div>
      <div className="v3d-pop-row">
        <span className="small">최대</span>
        <NumInput
          label={maxLabel}
          value={range.max}
          testId={t("max")}
          onCommit={(v) => {
            if (mode.sym) {
              if (!(v > 0)) return false;
              onRange({ max: v });
              return true;
            }
            if (!(v > range.min)) return false;
            onRange({ max: v });
            return true;
          }}
        />
        <button type="button" className="btn small ghost" disabled={manMax === null} onClick={() => onRange({ max: null })} title="자동 범위로 되돌립니다" data-testid={t("max-auto")}>
          자동
        </button>
      </div>
      {!mode.sym && (
        <div className="v3d-pop-row">
          <span className="small">최소</span>
          <NumInput
            label="범위 최소"
            value={range.min}
            testId={t("min")}
            onCommit={(v) => {
              if (!(v < range.max)) return false;
              onRange({ min: v });
              return true;
            }}
          />
          <button type="button" className="btn small ghost" disabled={manMin === null} onClick={() => onRange({ min: null })} title="자동 범위로 되돌립니다" data-testid={t("min-auto")}>
            자동
          </button>
        </div>
      )}
      <div className="v3d-pop-row">
        <span className="small">눈금</span>
        {seg(
          "scale",
          "눈금 종류",
          [
            { v: "linear", text: "선형" },
            { v: "log", text: "로그", off: !logOk, title: !logOk ? (mode.logOk ? LOG_WHY_RANGE : LOG_WHY_SIGNED) : "로그 눈금(최소가 0 이하면 최대/10^3 으로 잡음)" },
          ],
          s.scale === "log" && logOk ? "log" : "linear",
          (v) => onChange({ scale: v }),
        )}
      </div>
      <div className="v3d-pop-row">
        <span className="small">숫자</span>
        {seg<NumFormat>("format", "숫자 형식", [{ v: "auto", text: "자동" }, { v: "fixed", text: "고정" }, { v: "exp", text: "지수" }], s.format, (v) => onChange({ format: v }))}
        <span className="small muted">자릿수</span>
        <NumInput
          label="자릿수"
          value={s.digits}
          testId={t("digits")}
          onCommit={(v) => {
            if (!Number.isInteger(v) || v < 0 || v > DIGITS_MAX) return false;
            onChange({ digits: v });
            return true;
          }}
        />
      </div>
      <div className="v3d-pop-row">
        <span className="small">범위 밖</span>
        {seg<OutMode>("out", "범위 밖 값 색", [{ v: "clamp", text: "끝색" }, { v: "gray", text: "회색" }], s.out, (v) => onChange({ out: v }))}
      </div>
      <label className="check-field" title="체크 = 높음이 파랑, 낮음이 빨강(기본 = 높음 빨강)">
        <input type="checkbox" checked={s.reversed} onChange={(e) => onChange({ reversed: e.target.checked })} data-testid={t("rev")} />
        <span>색 순서 뒤집기</span>
      </label>
      <div className="v3d-pop-row v3d-pop-wrap">
        {marksRow === "all" && (
          <label className="check-field" title="지금 칠한 값의 최대 위치·값·노드 ID">
            <input type="checkbox" checked={marksOn} onChange={(e) => onMarks(e.target.checked)} data-testid={t("maxmark")} />
            <span>최대 표식</span>
          </label>
        )}
        <label className="check-field" title="지금 칠한 값의 최소 위치·값·노드 ID">
          <input type="checkbox" checked={s.minMark} onChange={(e) => onChange({ minMark: e.target.checked })} data-testid={t("minmark")} />
          <span>최소 표식</span>
        </label>
        <label className="check-field" title={hasPin ? "순위·ESL 표의 umax 가 난 노드를 표시합니다" : "이 3D 자료에는 umax 위치가 없습니다"}>
          <input type="checkbox" checked={s.upin && hasPin} disabled={!hasPin} onChange={(e) => onChange({ upin: e.target.checked })} data-testid={t("pin")} />
          <span>umax 위치</span>
        </label>
      </div>
      <div className="v3d-pop-row">
        <button type="button" className="btn small ghost" onClick={onReset} data-testid={t("reset")} title="레벨·범위·눈금·숫자·범위 밖·뒤집기·표식을 처음 값으로">
          기본값으로
        </button>
        <span className="small muted">이 브라우저에 기억됩니다</span>
      </div>
    </div>
  );
}

/** 범례 클릭 팝오버: 범례 아래 겹침 · Esc·바깥 클릭 닫힘 · 처음 입력칸에 초점 */
export function LegendPopover({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    const first = ref.current?.querySelector<HTMLElement>("input:not(:disabled), button:not(:disabled)");
    first?.focus();
    const onDoc = (e: MouseEvent) => {
      const wrap = ref.current?.closest(".v3d-legend-wrap");
      if (wrap && !wrap.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div
      ref={ref}
      id={id}
      className="v3d-legend-pop"
      role="dialog"
      aria-label="범례 편집"
      data-testid="v3d-legend-pop"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      {children}
    </div>
  );
}
