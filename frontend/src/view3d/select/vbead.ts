// v0.25.0 추가 비드(가상 비드, kind "A") 입력 규칙 — 순수 함수(esl_virtual_bead.md §2.1·§9·§19.4·§19.9.2).
// 입력 칸(문자열) → 검사 → VirtualBeadIn(요청 형식 그대로 저장), derive 응답 → 미리보기 BasisVar·3D 겹쳐 그리기.
import type { DoeSettingsOut, DoeVbFrame, DoeVirtualBeadDerived, VirtualBeadIn } from "../../api/types";
import type { BasisVar } from "./basis";
import type { GraphIndex } from "./graph";

type V3 = [number, number, number];

/** 설정 bead_doe.virtual_bead 의 칸 범위(옛 서버면 계약 기본값) */
export interface VbCfg {
  enabled: boolean;
  maxCount: number;
  thetaRange: [number, number];
  thetaDefault: number;
  dMaxLimit: number;
}
export function vbCfg(st: DoeSettingsOut | null | undefined): VbCfg {
  const v = st?.virtual_bead;
  return {
    enabled: !!v?.enabled,
    maxCount: v?.max_count ?? 4,
    thetaRange: v?.theta_range_deg ?? [15, 60],
    thetaDefault: v?.theta_default_deg ?? 45,
    dMaxLimit: v?.d_max_limit_mm ?? 30,
  };
}

/** 입력 칸(문자열). mode "pick" = 3D 에서 두 점, "coord" = ξ·η·길이·각도 */
export interface VbForm {
  mode: "pick" | "coord";
  xi: string;
  eta: string;
  length: string;
  angle: string;
  dMax: string;
  wTop: string;
  theta: string;
  /** 체크 칸 "방향 뒤집기" 1개(꺼짐 = 자동 방향 → 키 없음) */
  flip: boolean;
  end: "round" | "square";
  /** 비움 = 요소 크기 기본(키 없음), 0 이상 숫자 = 그 값(0 도 키 유지) */
  r: string;
}
export const emptyVbForm = (thetaDefault = 45): VbForm => ({ mode: "pick", xi: "", eta: "", length: "", angle: "", dMax: "", wTop: "", theta: String(thetaDefault), flip: false, end: "round", r: "" });

/** 3D 에서 찍은 두 점(모델 좌표). 길이 0~2 */
export type VbPicks = V3[];

/** 입력 칸 좌표계: ab = ((x − o)·ex, (x − o)·ey), 판 법선 n(역변환의 법선 쪽 값 dn = (판 위 점 − o)·n) */
export interface VbFrame {
  o: V3;
  ex: V3;
  ey: V3;
  n: V3;
  dn: number;
}
const dot = (a: ArrayLike<number>, b: ArrayLike<number>) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a: ArrayLike<number>, b: ArrayLike<number>): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const round = (v: number, d = 1e-4) => Math.round(v / d) * d;
const r4 = (v: number) => Math.round(v * 1e4) / 1e4;

export function toAb(fr: VbFrame, p: ArrayLike<number>): [number, number] {
  const q = sub(p, fr.o);
  return [dot(q, fr.ex), dot(q, fr.ey)];
}
export function toModel(fr: VbFrame, xi: number, eta: number): V3 {
  return [0, 1, 2].map((k) => fr.o[k] + xi * fr.ex[k] + eta * fr.ey[k] + fr.dn * fr.n[k]) as V3;
}

/** derive 의 vb_frame(있으면 — 코어와 같은 ξ'·η') 아니면 그래프 frame 으로 대신(첫 추가 비드 전). plateLevel = 판 법선 쪽 높이(노드 법선 성분 중앙값) */
export function vbFrameOf(vf: DoeVbFrame | null | undefined, gi: GraphIndex | null, plateLevel: number | null, refP0?: V3 | null): VbFrame | null {
  if (vf) {
    const fr: VbFrame = { o: vf.origin, ex: vf.e_xi, ey: vf.e_eta, n: vf.n_h, dn: 0 };
    if (refP0) fr.dn = dot(sub(refP0, vf.origin), vf.n_h);
    return fr;
  }
  const g = gi?.graph.frame;
  if (!g) return null;
  const o2 = g.origin ?? [0, 0];
  const L = plateLevel ?? 0;
  const o: V3 = [0, 1, 2].map((k) => o2[0] * g.e1[k] + o2[1] * g.e2[k] + L * g.n0[k]) as V3;
  return { o, ex: g.e1, ey: g.e2, n: g.n0, dn: 0 };
}

/** 노드 위치(평탄 배열) → 법선 n 방향 성분 중앙값(부모 바닥 높이 근사 — 그래프 frame 으로 ξ·η 를 모델 좌표로 되돌릴 때만) */
export function plateLevelOf(positions: ArrayLike<number>, n: ArrayLike<number>): number | null {
  const m = positions.length / 3;
  if (!m) return null;
  const step = Math.max(1, Math.floor(m / 4000));
  const h: number[] = [];
  for (let i = 0; i < m; i += step) h.push(positions[i * 3] * n[0] + positions[i * 3 + 1] * n[1] + positions[i * 3 + 2] * n[2]);
  h.sort((a, b) => a - b);
  return h[h.length >> 1];
}

const num = (s: string): number => (s.trim() === "" ? NaN : Number(s));

/** 입력 검사(차단 사유 1줄, null = 통과). 서버 422 와 같은 규칙: length > 0 · angle ∈ (−180, 180] · W_top > 0 · θ ∈ 범위 · 0 < D_max ≤ 한도 · r ≥ 0 */
export function vbProblem(f: VbForm, cfg: VbCfg, picks: VbPicks, count: number): string | null {
  if (count >= cfg.maxCount) return `추가 비드는 ${cfg.maxCount}개까지입니다`;
  if (f.mode === "pick") {
    if (picks.length < 2) return "3D 에서 평판 위 두 점을 찍으세요";
    if (Math.hypot(picks[1][0] - picks[0][0], picks[1][1] - picks[0][1], picks[1][2] - picks[0][2]) < 1e-3) return "두 점이 같습니다 — 길이가 0 입니다";
  } else {
    const xi = num(f.xi);
    const eta = num(f.eta);
    const L = num(f.length);
    const a = num(f.angle);
    if (!Number.isFinite(xi) || !Number.isFinite(eta)) return "시작점 ξ·η 를 숫자로 입력하세요";
    if (!(L > 0)) return "길이는 0보다 커야 합니다";
    if (!(a > -180 && a <= 180)) return "각도는 −180 초과 180 이하입니다";
  }
  const w = num(f.wTop);
  const d = num(f.dMax);
  const th = num(f.theta);
  if (!(w > 0)) return "깊이면 폭 W 는 0보다 커야 합니다";
  if (!(d > 0)) return "최대 깊이 D 는 0보다 커야 합니다";
  if (d > cfg.dMaxLimit + 1e-9) return `최대 깊이는 ${cfg.dMaxLimit} mm 까지입니다`;
  if (!(th >= cfg.thetaRange[0] - 1e-9 && th <= cfg.thetaRange[1] + 1e-9)) return `사면 각 θ 는 ${cfg.thetaRange[0]}~${cfg.thetaRange[1]}° 입니다`;
  if (f.r.trim() !== "") {
    const r = num(f.r);
    if (!(r >= 0)) return "모서리 반경 r 은 0 이상입니다(비우면 요소 크기)";
  }
  return null;
}

/** 비어 있는 가장 작은 a1..a9(상한 max_count 개 — id 가 max 를 넘지 않게). 없으면 null */
export function nextVbId(list: readonly { id: string }[], max: number): string | null {
  for (let n = 1; n <= Math.min(9, max); n++) if (!list.some((x) => x.id === `a${n}`)) return `a${n}`;
  return null;
}

/** 입력 칸 → 요청 항목(계약 §2.1). 두 점 = (a) p0·p1, 좌표 = (b) p0·length·angle_deg. flip 은 true 만 키, r 은 준 값이면 0 도 키 */
export function buildVBead(f: VbForm, picks: VbPicks, fr: VbFrame | null, id: string): VirtualBeadIn | null {
  const out: VirtualBeadIn = { id, p0: [0, 0, 0], w_top: r4(num(f.wTop)), d_max: r4(num(f.dMax)) } as VirtualBeadIn;
  if (f.mode === "pick") {
    out.p0 = picks[0].map(r4) as V3;
    out.p1 = picks[1].map(r4) as V3;
  } else {
    if (!fr) return null;
    out.p0 = toModel(fr, num(f.xi), num(f.eta)).map(r4) as V3;
    out.length = r4(num(f.length));
    out.angle_deg = r4(num(f.angle));
  }
  const th = num(f.theta);
  out.theta_deg = r4(th);
  if (f.end === "square") out.end = "square";
  if (f.r.trim() !== "") out.r = r4(num(f.r));
  if (f.flip) out.flip = true;
  return out;
}

/** 저장된 항목 → 입력 칸(행 클릭 = 같은 값으로 채워 다시 추가할 수 있게, flip 복원). fr 없으면 좌표 칸은 비움 */
export function formOf(v: VirtualBeadIn, fr: VbFrame | null, thetaDefault: number): VbForm {
  const f = emptyVbForm(thetaDefault);
  f.dMax = String(v.d_max);
  f.wTop = String(v.w_top);
  f.theta = String(v.theta_deg ?? thetaDefault);
  f.flip = v.flip === true;
  f.end = v.end === "square" ? "square" : "round";
  f.r = v.r == null ? "" : String(v.r);
  f.mode = "coord";
  if (fr) {
    const [xi, eta] = toAb(fr, v.p0);
    f.xi = String(round(xi, 0.01));
    f.eta = String(round(eta, 0.01));
    if (v.p1) {
      const [x1, e1] = toAb(fr, v.p1);
      f.length = String(round(Math.hypot(x1 - xi, e1 - eta), 0.01));
      f.angle = String(round((Math.atan2(e1 - eta, x1 - xi) * 180) / Math.PI, 0.01));
    } else {
      f.length = v.length != null ? String(v.length) : "";
      f.angle = v.angle_deg != null ? String(v.angle_deg) : "";
    }
  }
  return f;
}

/** 두 점을 찍으면 좌표·길이·각도 칸을 같이 채움(같은 상태 — §9). fr 없으면 변경 없음 */
export function fillFromPicks(f: VbForm, picks: VbPicks, fr: VbFrame | null): VbForm {
  if (!fr || !picks.length) return f;
  const [xi, eta] = toAb(fr, picks[0]);
  const g = { ...f, xi: String(round(xi, 0.01)), eta: String(round(eta, 0.01)) };
  if (picks.length > 1) {
    const [x1, e1] = toAb(fr, picks[1]);
    g.length = String(round(Math.hypot(x1 - xi, e1 - eta), 0.01));
    g.angle = String(round((Math.atan2(e1 - eta, x1 - xi) * 180) / Math.PI, 0.01));
  }
  return g;
}

/** 목록 행 요약: `A1 추가 비드 1 · L 120 mm · 30° · D≤5 W 20 θ45` (L·각도는 derive 가 풀어 준 값, 없으면 입력값) */
export function vbRowText(v: VirtualBeadIn, d?: DoeVirtualBeadDerived | null, thetaDefault = 45): string {
  const n = v.id.slice(1);
  const name = v.name || `추가 비드 ${n}`;
  const L = d?.len_mm ?? v.length ?? (v.p1 ? Math.hypot(v.p1[0] - v.p0[0], v.p1[1] - v.p0[1], v.p1[2] - v.p0[2]) : null);
  const a = d?.angle_deg ?? v.angle_deg ?? null;
  const parts = [`${v.id.toUpperCase()} ${name}`];
  if (L != null) parts.push(`L ${+Number(L).toFixed(1)} mm`);
  if (a != null) parts.push(`${+Number(a).toFixed(1)}°`);
  parts.push(`D≤${v.d_max} W ${v.w_top} θ${v.theta_deg ?? thetaDefault}`);
  return parts.join(" · ");
}

/** 변수 표 묶음 머리: `A1 추가 비드 1 · W 20 · θ 45° · L 120` */
export function vbHeadText(id: string, name: string, vb: { w_top: number; theta_deg: number; len_mm: number | null } | null | undefined): string {
  const t = [`${id.toUpperCase()} ${name}`];
  if (vb) {
    t.push(`W ${+vb.w_top.toFixed(2)}`, `θ ${+vb.theta_deg.toFixed(1)}°`);
    if (vb.len_mm != null) t.push(`L ${+vb.len_mm.toFixed(1)}`);
  }
  return t.join(" · ");
}

/** derive preview → 브라우저 BasisVar(hinge — 워커와 같은 식으로 morph·heightChange). 노드 수 0·형식 오류면 null */
export function previewVar(d: DoeVirtualBeadDerived): BasisVar | null {
  const p = d.preview;
  if (!d.ok || !p || !p.idx.length || p.vec.length !== p.idx.length || p.g.length !== p.idx.length) return null;
  const n = p.idx.length;
  const vec = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) vec[i * 3 + k] = p.vec[i][k];
  return { name: `A${d.id.slice(1)}_A`, bead: d.id, type: "A", nominal: 0, idx: Uint32Array.from(p.idx), vec, form: "hinge", g: Float32Array.from(p.g), c: p.c };
}

/** 3D 겹쳐 그리기 선분(쌍마다 6 float): 발자국 윤곽(outline_ab → 모델 좌표) + 중심선 p0→p1. 판 법선 쪽 높이는 p0 기준 */
export function vbOverlayLines(d: DoeVirtualBeadDerived, fr: VbFrame | null): Float32Array | null {
  if (!fr) return null;
  const dn = dot(sub(d.p0, fr.o), fr.n);
  const f2 = { ...fr, dn };
  const segs: number[] = [];
  const pts = (d.outline_ab ?? []).map((q) => toModel(f2, q.a, q.b));
  for (let i = 0; i + 1 < pts.length; i++) segs.push(...pts[i], ...pts[i + 1]);
  if (d.p1_resolved) segs.push(...d.p0, ...d.p1_resolved);
  return segs.length ? Float32Array.from(segs) : null;
}

/** 목록 상태 배지: OK | 첫 사유 문구(툴팁 = 전부) */
export function vbStatus(d: DoeVirtualBeadDerived | null | undefined): { ok: boolean; text: string; tip: string } | null {
  if (!d) return null;
  if (d.ok) return { ok: true, text: "OK", tip: "" };
  const rs = d.reasons ?? [];
  return { ok: false, text: rs[0]?.text ?? rs[0]?.code ?? "추가 불가", tip: rs.map((r) => r.text || r.code).join("\n") };
}
