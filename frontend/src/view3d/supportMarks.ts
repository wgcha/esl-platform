// v0.24.9 지그 경계조건 표식(esl_bead_pos_u.md §10) — 순수 계산. 표식 자료 kind·dirs·val → 방식별 기호 선분 · 범례 · 탐침 문구.
// 기호 색·문구는 이 표(MARK_TABLE) 한 곳. 옛 파일(kind 없음)은 supports.ts 의 dof 문자열 기호 그대로.
import type { View3dSupport, View3dTieMark } from "../api/types";
import type { V3 } from "./pick";

export type MarkKind = "tie_fixed" | "tie_disp" | "tie_spring" | "aux_inplane" | "support321";

/** 기호 크기: 모델 대각 길이 비례(기존 3-2-1 표식 0.04·diag 와 같은 규칙) */
export const MARK_SIZE_FRAC = 0.04;
/** 화살표·스프링 최소 길이(기호 크기 L 의 배수) — g 가 0 에 가까워도 기호·부호가 보이게 */
export const MARK_MIN_LEN = 0.25;
/** 스프링 기본 길이(L 의 배수 — 받침 위치 = −기본 길이 + g × 표시 배율) */
export const SPRING_BASE_LEN = 1.2;
/** 스프링 지그재그 꼭짓점 수·진폭(L 의 배수) */
export const SPRING_ZIGS = 6;
export const SPRING_AMP = 0.14;

export interface MarkRow {
  /** 기호 색(표 한 곳) */
  color: string;
  /** 탐침·범례에 쓰는 방식 이름 */
  name: string;
  /** 방향 이름(탐침 "방향 …" 앞말) */
  dirName: string;
  /** 범례(경계조건 칩 툴팁) 한 줄 뜻 */
  legend: string;
}

export const MARK_TABLE: Record<MarkKind, MarkRow> = {
  tie_fixed: { color: "#7f7f7f", name: "지그 고정", dirName: "법선", legend: "회색 막대+빗금 = tie 법선 고정(변위 0)" },
  tie_disp: { color: "#0f9aa8", name: "지그 강제 변위", dirName: "법선", legend: "청록 화살표 = tie 법선 강제 변위 g (길이 = g × 표시 배율)" },
  tie_spring: { color: "#e8870e", name: "지그 스프링", dirName: "법선", legend: "주황 스프링 = tie 법선만 스프링(면내 자유) · 받침 = 낙하 변위 g" },
  aux_inplane: { color: "#7b3fb0", name: "면내 지지", dirName: "면내", legend: "보라 양방향 화살표 + 삼각 = 3-2-1 면내 강체 지지(n₁ 2방향 · n₂ 1방향)" },
  support321: { color: "#1b9e77", name: "3-2-1 지지", dirName: "dof", legend: "녹색 삼각 = 3-2-1 지지(구속 dof 표기)" },
};
/** v0.25.2 §4.3 강제 부여 표식(표 한 곳 — 색은 표식 색, 연속값 색 지도 colormaps.json 대상 아님) */
export type TieKind = "force" | "ring" | "far" | "miss";
export const TIE_TABLE: Record<TieKind, { color: string; legend: (farMm?: number | null) => string }> = {
  force: { color: "#c2188f", legend: () => "자홍 테두리 = 체결부가 아닌 곳에 강제로 붙인 지지" },
  ring: { color: "#c2188f", legend: (far) => `빈 고리 = Case 체결부 자리(선 = 옮겨 붙인 거리 · 빨강 = ${far != null ? `${num(far)} mm 넘음` : "먼 곳"})` },
  far: { color: "#d4272b", legend: () => "" },
  miss: { color: "#d4272b", legend: () => "✕ = 붙일 면이 없어 뺀 체결부" },
};
/** 강제 표식 선 굵기(px): 지지 테두리 여분 · 옮긴 거리 선 · 먼 강제 선 · 고리·✕ */
export const TIE_PX = { outlinePad: 4, line: 1.5, far: 4, ring: 2 };
/** 고리 반지름·✕ 반폭(기호 크기 L 의 배수) · 고리 꼭짓점 수 */
export const TIE_RING_R = 0.5;
export const TIE_RING_N = 20;
/** 탐침(고리·✕ 클릭) 한 줄 */
export const tieProbe = (m: Pick<View3dTieMark, "q" | "dist" | "via" | "far">) =>
  `체결부 q${m.q} · ${m.via === "miss" ? "붙일 면 없음" : `거리 ${m.dist == null ? "–" : num(m.dist)} mm${m.far ? " · 먼 곳" : ""}`}`;

/** 옛 파일(kind 없음) 대체 표시 안내 — 범례 툴팁·탐침 */
export const LEGACY_MARK_TIP = "이전 형식 — 다시 만들기를 누르면 방식별 기호로 표시";
/** 범례 줄 순서(표에 있는 순서 그대로) */
export const MARK_ORDER = Object.keys(MARK_TABLE) as MarkKind[];
/** 탐침 값 문구 조각(단위·이름은 이 표 한 곳) */
export const MARK_VAL_TEXT = {
  k: (v: string) => `k ${v} N/mm`,
  g: (v: string) => `g ${v} mm`,
  fixed: "고정 0",
  value: (v: string) => `지정값 ${v} mm`,
  dirs: (n: number) => `${n}방향`,
};

export const isMarkKind = (k: unknown): k is MarkKind => typeof k === "string" && Object.prototype.hasOwnProperty.call(MARK_TABLE, k);

// ---- 벡터 보조
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a: V3, s: number): V3 => [a[0] * s, a[1] * s, a[2] * s];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a: V3) => Math.hypot(a[0], a[1], a[2]);
const unit = (a: V3): V3 | null => {
  const n = len(a);
  return n > 1e-12 ? [a[0] / n, a[1] / n, a[2] / n] : null;
};
/** d 에 수직인 단위 벡터(결정적) */
export function perpOf(d: V3): V3 {
  const ref: V3 = Math.abs(d[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
  return unit(cross(d, ref)) ?? [0, 0, 1];
}

/** 자료 dirs(통합 형식 INT-1 — 코어 support_marks_full 그대로: 행 방향 단위 벡터 [[x,y,z],…]) → 단위 벡터 목록. 그 밖 원소는 버림 */
export function dirVectors(dirs: unknown): V3[] {
  if (!Array.isArray(dirs)) return [];
  const out: V3[] = [];
  for (const d of dirs) {
    if (Array.isArray(d) && d.length === 3 && d.every((x) => typeof x === "number" && Number.isFinite(x))) {
      const u = unit([d[0], d[1], d[2]]);
      if (u) out.push(u);
    }
  }
  return out;
}

/** 방향 i 의 값(INT-1): 배열 = 방향별(dirs 와 같은 순서·길이), 숫자 = tie_fixed 의 0(모든 방향). 숫자가 아니면 null */
export function valAt(v: unknown, i: number): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (Array.isArray(v) && v.length) {
    const x = v[Math.min(i, v.length - 1)];
    return typeof x === "number" && Number.isFinite(x) ? x : null;
  }
  return null;
}
/** tie_spring val(INT-1) = {k: [방향별 N/mm], g: [방향별 mm]} — 스프링 행마다(dirs 와 같은 순서) */
interface SpringVal {
  k: unknown;
  g: unknown;
}
const springOf = (v: unknown): SpringVal => {
  const o = v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  return { k: o.k, g: o.g };
};

type Seg = [V3, V3];
const poly = (pts: V3[]): Seg[] => pts.slice(1).map((q, i) => [pts[i], q]);
const barAt = (c: V3, t: V3, half: number): Seg => [add(c, mul(t, -half)), add(c, mul(t, half))];
/** 화살촉 두 날개(끝점 e, 진행 방향 d) */
function headBarbs(e: V3, d: V3, t: V3, L: number): Seg[] {
  const back = add(e, mul(d, -0.28 * L));
  return [[e, add(back, mul(t, 0.14 * L))], [e, add(back, mul(t, -0.14 * L))]];
}

/** 표식 1개의 기호 선분(월드 좌표). p = 변형 반영된 노드 위치, gscale = g 의 표시 배율(변형 켬 = 변형 배율, 끔 = 1) */
export function markSegments(kind: MarkKind, p: V3, dirs: V3[], val: unknown, diag: number, gscale: number): Seg[] {
  const L = MARK_SIZE_FRAC * diag;
  const out: Seg[] = [];
  if (kind === "support321" || !dirs.length) return out;
  if (kind === "tie_fixed") {
    for (const d of dirs) {
      const t = perpOf(d);
      const e = add(p, mul(d, -L));
      out.push([p, e], barAt(e, t, 0.6 * L));
      for (let i = -1; i <= 1; i++) {
        const h = add(e, mul(t, 0.4 * L * i));
        out.push([h, add(add(h, mul(d, -0.3 * L)), mul(t, -0.2 * L))]);
      }
    }
  } else if (kind === "tie_disp") {
    dirs.forEach((d, i) => {
      const t = perpOf(d);
      const g = valAt(val, i) ?? 0;
      const sgn = g < 0 ? -1 : 1;
      const l = Math.max(Math.abs(g) * gscale, MARK_MIN_LEN * L) * sgn;
      const head = add(p, mul(d, l));
      out.push([p, head], ...headBarbs(head, mul(d, sgn), t, L), barAt(head, t, 0.45 * L));
    });
  } else if (kind === "tie_spring") {
    const sv = springOf(val);
    dirs.forEach((d, i) => {
      const t = perpOf(d);
      const g = valAt(sv.g, i) ?? 0;
      let off = -SPRING_BASE_LEN * L + g * gscale; // 받침 위치(노드에서 법선 방향 오프셋)
      if (Math.abs(off) < MARK_MIN_LEN * L) off = (off < 0 ? -1 : 1) * MARK_MIN_LEN * L;
      const a = add(p, mul(d, off));
      const sgn = off < 0 ? -1 : 1;
      const lead = 0.15 * Math.abs(off);
      const body = Math.abs(off) - 2 * lead;
      const pts: V3[] = [p, add(p, mul(d, sgn * lead))];
      for (let j = 1; j <= SPRING_ZIGS; j++) {
        const s = lead + (body * (j - 0.5)) / SPRING_ZIGS;
        pts.push(add(add(p, mul(d, sgn * s)), mul(t, (j % 2 ? 1 : -1) * SPRING_AMP * L)));
      }
      pts.push(add(p, mul(d, sgn * (Math.abs(off) - lead))), a);
      out.push(...poly(pts), barAt(a, t, 0.5 * L));
    });
  } else if (kind === "aux_inplane") {
    for (const d of dirs) {
      const t = perpOf(d);
      const a = add(p, mul(d, -L));
      const b = add(p, mul(d, L));
      out.push([a, b], ...headBarbs(b, d, t, L), ...headBarbs(a, mul(d, -1), t, L));
    }
    const w = dirs.length >= 2 ? unit(cross(dirs[0], dirs[1])) ?? perpOf(dirs[0]) : perpOf(dirs[0]);
    const q = add(p, mul(w, -0.5 * L));
    const b1 = add(q, mul(dirs[0], 0.3 * L));
    const b2 = add(q, mul(dirs[0], -0.3 * L));
    out.push([p, b1], [b1, b2], [b2, p]);
  }
  return out;
}

/** 옛 지그 파일의 면내 지지 dof 문자열(esl.mech.jig_bc.MARK_AUX — 지그 표식만 쓰는 값, 3-2-1 dof 는 숫자) */
export const LEGACY_JIG_AUX_DOF = "ij";
/** 범례(경계조건 칩 툴팁에 붙는 줄): 이 표식 목록에 있는 kind 의 한 줄 뜻(표 순서) + 옛 지그 파일 표식이 있으면 대체 안내.
 *  옛 지그 파일 판정(INT-3) = kind 없는 행이 있고 (jigView — 출처 표 group jig 인 Case 보기 — 또는 kind 없는 면내 지지 dof "ij" 행이 있음).
 *  전 노드 ESL 등 지그 아닌 출처의 3-2-1 지지(kind 없음)에는 "다시 만들기" 안내를 붙이지 않는다(다시 만들어도 기호가 같음). */
export function markLegend(supports: Partial<Pick<View3dSupport, "kind" | "dof" | "via">>[], jigView = false, tieMarks?: Pick<View3dTieMark, "via">[] | null, farMm?: number | null): string[] {
  const kinds = new Set<MarkKind>();
  let bare = false;
  let jigBare = false;
  for (const s of supports) {
    if (isMarkKind(s.kind)) kinds.add(s.kind);
    else {
      bare = true;
      if (s.dof === LEGACY_JIG_AUX_DOF) jigBare = true;
    }
  }
  const legacy = bare && (jigView || jigBare);
  const lines = MARK_ORDER.filter((k) => kinds.has(k)).map((k) => MARK_TABLE[k].legend);
  if (legacy) lines.push(LEGACY_MARK_TIP);
  // v0.25.2: 강제 부여 항목(있을 때만 — 옛 manifest 는 지금 그대로)
  if (supports.some((s) => s.via === "force")) lines.push(TIE_TABLE.force.legend());
  if (tieMarks?.some((m) => m.via === "force")) lines.push(TIE_TABLE.ring.legend(farMm));
  if (tieMarks?.some((m) => m.via === "miss")) lines.push(TIE_TABLE.miss.legend());
  return lines;
}

const num = (x: number) => (Math.abs(x) >= 1e6 || (Math.abs(x) < 0.01 && x !== 0) ? x.toExponential(2) : String(+x.toFixed(3)));
const dirText = (d: V3) => `(${d.map((x) => (+x.toFixed(2) || 0).toFixed(2)).join(", ")})`;

/** 탐침 한 줄: "지지 노드 · 방식 이름 · 방향 법선 (x, y, z) · 값" — kind 가 표에 없으면 null(옛 형식 줄을 쓴다) */
export function markProbe(s: View3dSupport): string | null {
  if (!isMarkKind(s.kind) || s.kind === "support321") return null;
  const row = MARK_TABLE[s.kind];
  const dirs = dirVectors(s.dirs);
  const parts = [`지지 ${s.node_id}`, row.name];
  if (dirs.length) parts.push(`방향 ${row.dirName} ${dirs.map(dirText).join(" · ")}`);
  const g = (v: unknown) => {
    const xs = dirs.length > 1 && Array.isArray(v) ? dirs.map((_, i) => valAt(v, i)) : [valAt(v, 0)];
    return xs.map((x) => (x == null ? "–" : num(x))).join(" / ");
  };
  if (s.kind === "tie_fixed") parts.push(MARK_VAL_TEXT.fixed);
  else if (s.kind === "tie_disp") parts.push(MARK_VAL_TEXT.g(g(s.val)));
  else if (s.kind === "tie_spring") {
    const sv = springOf(s.val);
    parts.push(MARK_VAL_TEXT.k(g(sv.k)), MARK_VAL_TEXT.g(g(sv.g)));
  } else if (s.kind === "aux_inplane") parts.push(s.val == null ? MARK_VAL_TEXT.dirs(dirs.length) : MARK_VAL_TEXT.value(g(s.val)));
  return parts.join(" · ");
}
