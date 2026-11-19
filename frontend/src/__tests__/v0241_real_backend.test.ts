// v0.24.1 통합: 실제 백엔드 응답(backend/tests 픽스처 Case run 1개 — GET /view3d/sources, ?src=bforce|fint 매니페스트·glb·values.bin,
// /view3d/recon?src=·recon.bin)을 그대로 저장한 fixtures/real_v0241.json 을 프런트 파서에 먹여 정점 순서·배열 이름·범위 키를 대조한다.
// 픽스처 재생성: 백엔드 시험 환경에서 Case run(synth_mesh 12x8)에 bforce·fint 를 심고 위 URL 응답을 JSON 으로 저장(TECH 메모 계약 §15).
import { describe, expect, it } from "vitest";
import real from "./fixtures/real_v0241.json";
import { parseGlb } from "../view3d/glb";
import { caseTabItems, defaultCaseSource, needsRecon, sourceRowOf } from "../view3d/sources";
import { decodeDisp, decodeValues, maxNorm3 } from "../view3d/values";
import { resolveFileUrl } from "../view3d/fetchFiles";
import type { View3dOut, View3dReconOut, View3dSourcesOut } from "../api/types";

const buf = (b64: string): ArrayBuffer => {
  const u = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength);
};
const R = real as unknown as Record<string, unknown>;
const sources = real.sources as unknown as View3dSourcesOut;

describe("v0.24.1 실제 백엔드 응답 ↔ 프런트 파서", () => {
  it("/view3d/sources: 행 키·순서·열이 탭 상태로 이어진다", () => {
    expect(sources.rows.map((r) => r.key)).toEqual(["jig", "full", "bforce", "fint"]);
    const items = caseTabItems(sources)!;
    expect(items.map((i) => i.key)).toEqual(sources.rows.map((r) => r.key));
    expect(items.map((i) => i.ok)).toEqual(sources.rows.map((r) => r.available));
    expect(items[0].ok).toBe(false);
    expect(items[0].why).toContain(sources.rows[0].reason!);
    expect(defaultCaseSource(sources)).toBe(sources.default);
    expect(sourceRowOf(sources, "bforce")!.resp).toBe(true);
    expect(sourceRowOf(sources, "full")!.rigid).toBe("linear");
  });

  for (const src of ["bforce", "fint"] as const) {
    it(`?src=${src}: 매니페스트·glb·values.bin·recon 정점 순서·배열·범위`, () => {
      const m = R[`view_${src}`] as View3dOut;
      expect(m.geometry_url).toContain(`?src=${src}`);
      expect(resolveFileUrl(m.esl_run_id, m.values_url, m.key).endsWith(`/esl-runs/${m.esl_run_id}/view3d/values.bin?src=${src}&key=${m.key}`)).toBe(true);
      const g = parseGlb(buf(R[`${src}_geometry_b64`] as string));
      const v = decodeValues(buf(R[`${src}_values_b64`] as string), m);
      expect(g.positions.length / 3).toBe(m.n_nodes);
      expect(v.n).toBe(m.n_nodes);
      expect(g.nodeIds ? g.nodeIds.length : m.n_nodes).toBe(m.n_nodes);
      const rc = R[`recon_${src}`] as View3dReconOut;
      expect(rc.src).toBe(src);
      expect(rc.n_nodes).toBe(m.n_nodes);                                      // 재현 정점 순서 = 하중 보기(같은 n·같은 순서)
      expect(rc.arrays.map((a) => a.key)).toEqual(["tgt", "fit", "err"]);
      expect(rc.values_url).toContain(`recon.bin?src=${src}`);
      const d = decodeDisp(buf(R[`recon_${src}_bin_b64`] as string), rc);
      expect(d.tgt!.length).toBe(3 * rc.n_nodes);
      expect(needsRecon("fit") && !!d.fit && !!d.err).toBe(true);
      // 범위 키: ranges.*_max = 복원 후 최대 크기(양자화 간격 이내) — values.u(목표 변위, mm)와 tgt 도 같은 정점 순서
      const q = (k: "tgt" | "fit" | "err") => Math.max(...rc.arrays.find((a) => a.key === k)!.scale) * 2;
      expect(Math.abs(maxNorm3(d.tgt!) - rc.ranges.tgt_max)).toBeLessThanOrEqual(q("tgt"));
      expect(Math.abs(maxNorm3(d.fit!) - rc.ranges.fit_max)).toBeLessThanOrEqual(q("fit"));
      expect(Math.abs(maxNorm3(d.err!) - rc.ranges.err_max)).toBeLessThanOrEqual(q("err"));
      expect(rc.umax_tgt).toBeCloseTo(rc.ranges.tgt_max, 9);
      if (v.u) for (let i = 0; i < v.u.length; i++) expect(Math.abs(v.u[i] - d.tgt![i])).toBeLessThanOrEqual(Math.max(v.scale.u[i % 3], rc.arrays[0].scale[i % 3]) * 2 + 1e-9);
    });
  }
});
