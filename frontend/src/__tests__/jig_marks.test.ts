// V-0249-BM-4 (esl_bead_pos_u.md §10.3·§10.4): 지그 경계조건 표식 — kind 별 기호 선분·색·범례·탐침·옛 파일 대체. 시험은 목 픽스처(백엔드 B1 병행).
import { describe, expect, it } from "vitest";
import { buildSupportSpecs } from "../view3d/supports";
import { LEGACY_MARK_TIP, MARK_ORDER, MARK_SIZE_FRAC, MARK_TABLE, SPRING_BASE_LEN, dirVectors, markLegend, markProbe, markSegments, valAt } from "../view3d/supportMarks";
import { infoLine } from "../view3d/info";
import { JIG_MARK_KIND, jigMarkSupports, mockView3d } from "../mock/view3dmock";
import type { View3dOut, View3dSupport } from "../api/types";

const diag = 500;
const L = MARK_SIZE_FRAC * diag;
const P: [number, number, number] = [10, 20, 30];
const N: [number, number, number][] = [[0, 0, 1]];
const len = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const maxZ = (segs: [number[], number[]][]) => Math.max(...segs.flatMap(([a, b]) => [a[2], b[2]]));
const minZ = (segs: [number[], number[]][]) => Math.min(...segs.flatMap(([a, b]) => [a[2], b[2]]));

describe("자료 읽기", () => {
  it("dirs: 벡터는 정규화, 정수 1·2·3 = 전역 축, 그 밖은 버림", () => {
    expect(dirVectors([[0, 0, 2]])).toEqual([[0, 0, 1]]);
    expect(dirVectors([1, 3])).toEqual([[1, 0, 0], [0, 0, 1]]);
    expect(dirVectors([[0, 0, 0], 7, "x"])).toEqual([]);
    expect(dirVectors(null)).toEqual([]);
  });
  it("val: 숫자 = 공통, 배열 = 방향별", () => {
    expect(valAt(0.5, 3)).toBe(0.5);
    expect(valAt([1, 2], 1)).toBe(2);
    expect(valAt([1, 2], 5)).toBe(2);
    expect(valAt("x", 0)).toBeNull();
  });
});

describe("기호 선분", () => {
  it("tie_fixed: 법선 막대(길이 L) + 바닥 막대 + 빗금 3 — 노드 아래쪽(−법선)", () => {
    const s = markSegments("tie_fixed", P, N, 0, diag, 1);
    expect(s.length).toBe(1 + 1 + 3);
    expect(len(s[0][0], s[0][1])).toBeCloseTo(L, 9);
    expect(maxZ(s)).toBeCloseTo(P[2], 9);
    expect(minZ(s)).toBeLessThan(P[2] - L);
  });
  it("tie_disp: 화살표 길이 = |g| × 표시 배율, 방향 = g 부호, 끝 막대", () => {
    const up = markSegments("tie_disp", P, N, 2, diag, 10);
    expect(len(up[0][0], up[0][1])).toBeCloseTo(20, 9);
    expect(up[0][1][2]).toBeCloseTo(P[2] + 20, 9);
    const dn = markSegments("tie_disp", P, N, -2, diag, 10);
    expect(dn[0][1][2]).toBeCloseTo(P[2] - 20, 9);
    expect(up.length).toBe(1 + 2 + 1);
    // 배율 연동: 두 배 → 두 배
    expect(len(markSegments("tie_disp", P, N, 2, diag, 20)[0][0], markSegments("tie_disp", P, N, 2, diag, 20)[0][1])).toBeCloseTo(40, 9);
    // g 가 0 에 가까워도 최소 길이로 보임
    expect(len(markSegments("tie_disp", P, N, 0, diag, 10)[0][0], markSegments("tie_disp", P, N, 0, diag, 10)[0][1])).toBeGreaterThan(0);
  });
  it("tie_spring: 지그재그 + 끝 받침 막대, 받침 위치 = −기본 길이 + g × 배율(g 로 이동)", () => {
    const s0 = markSegments("tie_spring", P, N, { k: 1000, g: 0 }, diag, 10);
    const s1 = markSegments("tie_spring", P, N, { k: 1000, g: 1 }, diag, 10);
    const anchor = (s: [number[], number[]][]) => s[s.length - 2][1]; // 마지막 선분 = 받침 막대, 그 앞 선분 끝 = 받침 위치
    expect(anchor(s0)[2]).toBeCloseTo(P[2] - SPRING_BASE_LEN * L, 9);
    expect(anchor(s1)[2]).toBeCloseTo(P[2] - SPRING_BASE_LEN * L + 10, 9);
    expect(s0.length).toBeGreaterThan(8); // 지그재그
    // 지그재그는 법선에서 좌우로 벗어남(진폭 > 0)
    const off = s0.flatMap(([a, b]) => [a, b]).filter((p) => Math.abs(p[0] - P[0]) + Math.abs(p[1] - P[1]) > 1e-6);
    expect(off.length).toBeGreaterThan(4);
    // g 배열 = 방향별
    expect(markSegments("tie_spring", P, [[0, 0, 1], [1, 0, 0]], { k: 5, g: [1, 2] }, diag, 10).length).toBe(s1.length * 2 + 0);
  });
  it("aux_inplane: 방향마다 양방향 화살표(몸통 2L + 촉 4) + 삼각 3, n₁(2방향) > n₂(1방향)", () => {
    const n1 = markSegments("aux_inplane", P, [[1, 0, 0], [0, 1, 0]], [0, 0], diag, 1);
    const n2 = markSegments("aux_inplane", P, [[1, 0, 0]], 0, diag, 1);
    expect(n1.length).toBe(2 * 5 + 3);
    expect(n2.length).toBe(1 * 5 + 3);
    expect(len(n2[0][0], n2[0][1])).toBeCloseTo(2 * L, 9);
    // 삼각 받침은 면내 방향 평면 밖(법선 z 쪽)으로 내려감
    expect(minZ(n1)).toBeLessThan(P[2]);
  });
  it("support321·방향 없음 = 선분 없음", () => {
    expect(markSegments("support321", P, N, null, diag, 1)).toEqual([]);
    expect(markSegments("tie_fixed", P, [], 0, diag, 1)).toEqual([]);
  });
  it("꺾인 노드(법선 2개) = 방향마다 기호 하나씩", () => {
    const bent: [number, number, number][] = [[0, 0, 1], [0.7071, 0, 0.7071]];
    expect(markSegments("tie_fixed", P, bent, 0, diag, 1).length).toBe(5 * 2);
  });
});

describe("표 한 곳: 색·이름·범례", () => {
  it("모든 kind 가 모든 열을 채움, 색은 서로 다름", () => {
    for (const k of MARK_ORDER) for (const c of ["color", "name", "dirName", "legend"] as const) expect(MARK_TABLE[k][c], `${k}.${c}`).toBeTruthy();
    expect(new Set(MARK_ORDER.map((k) => MARK_TABLE[k].color)).size).toBe(MARK_ORDER.length);
  });
  it("범례: 있는 kind 의 한 줄 뜻만(표 순서) + kind 없는 표식이 있으면 옛 형식 안내", () => {
    expect(markLegend([{ kind: "tie_spring" }, { kind: "aux_inplane" }, { kind: "tie_spring" }])).toEqual([MARK_TABLE.tie_spring.legend, MARK_TABLE.aux_inplane.legend]);
    expect(MARK_TABLE.tie_spring.legend).toContain("tie 법선만 스프링(면내 자유)");
    expect(MARK_TABLE.tie_spring.legend).toContain("받침 = 낙하 변위 g");
    expect(markLegend([{}, { kind: "tie_fixed" }])).toEqual([MARK_TABLE.tie_fixed.legend, LEGACY_MARK_TIP]);
    expect(LEGACY_MARK_TIP).toBe("이전 형식 — 다시 만들기를 누르면 방식별 기호로 표시");
    expect(markLegend([{ kind: null }])).toEqual([LEGACY_MARK_TIP]);
  });
});

const sup = (over: Partial<View3dSupport>): View3dSupport => ({ node_id: 77, vertex: 0, dof: "123", x0: [0, 0, 0], ...over });

describe("탐침 문구", () => {
  it("노드 번호·방식 이름·방향·값(k·g / g / 고정 0 / 지정값)", () => {
    expect(markProbe(sup({ kind: "tie_spring", dirs: [[0, 0, 1]], val: { k: 1200, g: 0.6 } }))).toBe("지지 77 · 지그 스프링 · 방향 법선 (0.00, 0.00, 1.00) · k 1200 N/mm · g 0.6 mm");
    expect(markProbe(sup({ kind: "tie_disp", dirs: [[0, 0, 1], [1, 0, 0]], val: [0.6, 0.4] }))).toBe("지지 77 · 지그 강제 변위 · 방향 법선 (0.00, 0.00, 1.00) · (1.00, 0.00, 0.00) · g 0.6 / 0.4 mm");
    expect(markProbe(sup({ kind: "tie_fixed", dirs: [3] }))).toContain("고정 0");
    expect(markProbe(sup({ kind: "aux_inplane", dirs: [[1, 0, 0]], val: 0 }))).toBe("지지 77 · 면내 지지 · 방향 면내 (1.00, 0.00, 0.00) · 지정값 0 mm");
    expect(markProbe(sup({}))).toBeNull();
    expect(markProbe(sup({ kind: "support321" }))).toBeNull();
  });
  it("infoLine: 새 표식 = 위 문구, 옛 표식 = 지금 문구 그대로", () => {
    const m = mockView3d().manifest("e", "jig_spring") as View3dOut;
    const old = mockView3d().manifest("e") as View3dOut;
    expect(infoLine({ kind: "support", index: 0 }, m, null, null)).toContain("지그 스프링");
    expect(infoLine({ kind: "support", index: 0 }, old, null, null)).toBe("지지 " + old.supports[0].node_id + " · dof 123 (x·y·z)");
  });
});

describe("buildSupportSpecs", () => {
  const m = mockView3d().manifest("e", "jig_spring") as View3dOut;
  it("새 kind = markSegs·색(표), 글자 기호용 선분 없음 / 옛(kind 없음) = 지금 그대로", () => {
    const specs = buildSupportSpecs(m.supports, null, 0, m.bbox.diag, 1);
    expect(specs.map((s) => s.markKind)).toEqual(m.supports.map((s) => s.kind));
    for (const s of specs) {
      expect(s.markSegs!.length).toBeGreaterThan(0);
      expect(s.segments).toEqual([]);
      expect(s.markColor).toBe(MARK_TABLE[s.markKind!].color);
    }
    const old = mockView3d().manifest("e") as View3dOut;
    const os = buildSupportSpecs(old.supports, null, 0, old.bbox.diag);
    expect(os.every((s) => !s.markKind && !s.markSegs)).toBe(true);
    expect(os.map((s) => s.segments.length)).toEqual([3, 2, 1]);
  });
  it("표시 배율(gscale) 연동: 받침 위치가 g × 배율만큼 이동", () => {
    const one = [m.supports.find((s) => s.kind === "tie_spring")!];
    const a = buildSupportSpecs(one, null, 0, m.bbox.diag, 1)[0].markSegs!;
    const b = buildSupportSpecs(one, null, 0, m.bbox.diag, 11)[0].markSegs!;
    expect(a.length).toBe(b.length);
    const d = Math.hypot(...[0, 1, 2].map((i) => b[b.length - 2][1][i] - a[a.length - 2][1][i]));
    expect(d).toBeGreaterThan(0);
  });
});

describe("목 픽스처: 지그 3방식 × 꺾인 노드 · 면내 지지", () => {
  it("방식 키 → tie 기호 종류, 꺾인 노드(법선 2)·평평한 노드·n₁(2)·n₂(1) 포함", () => {
    expect(JIG_MARK_KIND).toMatchObject({ jig: "tie_fixed", jig_disp: "tie_disp", jig_spring: "tie_spring", jd: "tie_disp", js: "tie_spring" });
    for (const [key, kind] of Object.entries({ jig: "tie_fixed", jig_disp: "tie_disp", jig_spring: "tie_spring" })) {
      const sp = (mockView3d().manifest("e", key) as View3dOut).supports;
      expect(sp.filter((s) => s.kind === kind).map((s) => s.dirs!.length)).toEqual([1, 2, 1]);
      expect(sp.filter((s) => s.kind === "aux_inplane").map((s) => s.dirs!.length)).toEqual([2, 1]);
      expect(sp.every((s) => typeof s.dof === "string")).toBe(true); // 옛 dof 필드 그대로 남음
    }
    expect(jigMarkSupports([], "none", () => [0], () => 0, 0)).toEqual([]);
  });
});
