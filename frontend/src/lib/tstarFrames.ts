// v0.25.2 §7.1 — ② t* 임의 프레임: 곡선 점 ↔ 프레임 번호·시간 맞춤, "직접" 칸 해석, 변위 칸 상태, 자동 대비 문구.
// 서버가 같은 값을 다시 계산한다(point_at·frame_point) — 여기는 확정 전 표시용(curve 값 = history.value).
import { TSTAR_MANUAL_TEXT } from "../api/client";
import type { TStarManual, TstarFill, TstarMetricBlock, TstarView } from "../api/types";

export interface CurvePt {
  frame: number;
  time: number;
  value: number;
}

/** 곡선 점 목록. 프레임 번호 = history.frame_index → view.frames → 배열 위치(옛 서버) 순으로 */
export function curvePoints(blk: TstarMetricBlock | undefined, view: TstarView | null | undefined): CurvePt[] {
  if (!blk) return [];
  const { time, value, frame_index } = blk.history;
  const fr = view?.frames;
  return time.map((t, i) => ({ frame: frame_index?.[i] ?? (fr && fr.length === time.length ? fr[i].frame_index : i), time: t, value: value[i] }));
}

/** 시각 t 에서 가장 가까운 점의 위치(동률 = 앞 프레임) */
export function nearestPos(pts: CurvePt[], t: number): number {
  let best = 0;
  let bd = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const d = Math.abs(pts[i].time - t);
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return best;
}

export type ManualParse = { ok: true; frame: number } | { ok: false; reason: "empty" | "range" | "format" };

/** 직접 칸: 정수만 = 프레임 번호, 소수점이 있거나 끝에 s = 시간(가장 가까운 프레임). 범위 밖 = range */
export function parseManual(text: string, pts: CurvePt[]): ManualParse {
  const t = text.trim();
  if (!t) return { ok: false, reason: "empty" };
  if (/^\d+$/.test(t)) {
    const n = Number(t);
    return pts.some((p) => p.frame === n) ? { ok: true, frame: n } : { ok: false, reason: "range" };
  }
  const m = /^(\d*\.?\d+(?:e[+-]?\d+)?)\s*s?$/i.exec(t);
  if (!m || !pts.length) return { ok: false, reason: "format" };
  const sec = Number(m[1]);
  const t0 = pts[0].time;
  const t1 = pts[pts.length - 1].time;
  const tol = pts.length > 1 ? (t1 - t0) / (pts.length - 1) / 2 : 0;
  if (sec < t0 - tol || sec > t1 + tol) return { ok: false, reason: "range" };
  return { ok: true, frame: pts[nearestPos(pts, sec)].frame };
}

/** 변위 칸: 있음 · ESL 때 읽음(D 밖 + 채움 가능) · 불가(사유 = fill.text) */
export type DispState = "have" | "fill" | "blocked";
export function dispState(frame: number, view: TstarView | null | undefined): DispState {
  const have = view?.frames_have ?? view?.frames_D ?? [];
  if (have.includes(frame)) return "have";
  const fill: TstarFill | undefined = view?.fill;
  // 옛 서버(fill 키 없음)는 후보 밖을 고를 수 없다
  return fill?.available ? "fill" : "blocked";
}

export const pctText = (ratio: number | null | undefined) => (ratio === null || ratio === undefined ? "–" : `${Math.round(ratio * 100)}`);

/** 자동 대비 %(확정 전 계산 — 값 = 곡선 값 / 자동 t* 값) */
export function manualFromCurve(pts: CurvePt[], frame: number, autoFrame: number | null | undefined): Pick<TStarManual, "auto_frame" | "auto_time" | "auto_value" | "ratio" | "rel"> | null {
  const p = pts.find((x) => x.frame === frame);
  const a = pts.find((x) => x.frame === autoFrame);
  if (!p || !a) return null;
  return { auto_frame: a.frame, auto_time: a.time, auto_value: a.value, ratio: a.value > 0 ? p.value / a.value : null, rel: frame < a.frame ? "before" : frame > a.frame ? "after" : "at" };
}

const fill = (tpl: string, v: Record<string, string>) => tpl.replace(/\{(\w+)\}/g, (_, k) => v[k] ?? "");

/** 확정 전 경고·정보(TSTAR_MANUAL·LOW·AFTER). NO_RISING 은 ESL 뒤에야 알 수 있어 여기선 안 냄. warn = tstar.manual_ratio_warn(없으면 LOW 생략) */
export function manualNotes(m: Pick<TStarManual, "auto_frame" | "auto_time" | "ratio" | "rel">, f: number, t: number, warn: number | null | undefined) {
  const v = { f: String(f), t: t.toFixed(3), fa: String(m.auto_frame), ta: m.auto_time.toFixed(3), pct: pctText(m.ratio) };
  const out: { code: keyof typeof TSTAR_MANUAL_TEXT; level: "info" | "warn"; text: string }[] = [];
  if (m.rel === "at") return out;
  out.push({ code: "TSTAR_MANUAL", level: "info", text: fill(TSTAR_MANUAL_TEXT.TSTAR_MANUAL, v) });
  if (warn !== undefined && warn !== null && m.ratio !== null && m.ratio < warn) out.push({ code: "TSTAR_MANUAL_LOW", level: "warn", text: fill(TSTAR_MANUAL_TEXT.TSTAR_MANUAL_LOW, v) });
  if (m.rel === "after") out.push({ code: "TSTAR_MANUAL_AFTER", level: "info", text: fill(TSTAR_MANUAL_TEXT.TSTAR_MANUAL_AFTER, v) });
  return out;
}
