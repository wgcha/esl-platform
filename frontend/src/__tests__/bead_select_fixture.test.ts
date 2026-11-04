// V-BS-FMT(프런트): 코어가 실제로 만든 픽스처(tests/fixtures/bead_select — make_fixture.py: bead_select.view_files·basis_bin·basis_meta)를
// view.ts·basis.ts 가 같은 형식으로 읽는지. n_elems 3925·n_nodes 4029(4의 배수 아님) → select.bin 섹션 4바이트 채움을 bin.layout 으로 따라가는지.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { DoeBasisMeta, DoeSelectViewManifest } from "../api/types";
import { beadDirections, heightChange, maxAbs, morph, parseBasis } from "../view3d/select/basis";
import { parseSelectBin, writeSelectBin } from "../view3d/select/view";

const DIR = path.resolve(__dirname, "../../../tests/fixtures/bead_select");
const bin = (name: string): ArrayBuffer => {
  const b = readFileSync(path.join(DIR, name));
  const out = new ArrayBuffer(b.byteLength);
  new Uint8Array(out).set(b);
  return out;
};
const json = <T,>(name: string): T => JSON.parse(readFileSync(path.join(DIR, name), "utf8")) as T;
const mf = json<Pick<DoeSelectViewManifest, "n_nodes" | "n_elems" | "n_tris" | "bin">>("select_manifest.json");
const meta = json<DoeBasisMeta>("basis.json");
const exp = json<{
  elem_id_first: number;
  elem_id_last: number;
  elem_id_sum: number;
  n_sh3n: number;
  fixed_n: number;
  tri2elem_last: number;
  values: Record<string, number>;
  u_max_abs: number;
  u_sum: number[];
  n_hat: Record<string, number[]>;
}>("expected.json");

describe("V-BS-FMT select.bin(코어 view_files 픽스처)", () => {
  it("n_elems·n_nodes 가 4의 배수가 아님 — 섹션 사이 채움이 있고 bin.layout 오프셋으로 읽는다", () => {
    expect(mf.n_elems % 4).not.toBe(0);
    expect(mf.n_nodes % 4).not.toBe(0);
    const L = Object.fromEntries(mf.bin.layout.map((x) => [x.name, x]));
    expect(L.fixed.offset).toBeGreaterThan(L.elem_type.offset + mf.n_elems); // 채움 존재
    const raw = bin("select.bin");
    expect(raw.byteLength).toBe(mf.bin.bytes);
    const b = parseSelectBin(raw, mf);
    expect(b.tri2elem.length).toBe(mf.n_tris);
    expect(b.tri2elem[mf.n_tris - 1]).toBe(exp.tri2elem_last);
    expect(b.elemId[0]).toBe(exp.elem_id_first);
    expect(b.elemId[mf.n_elems - 1]).toBe(exp.elem_id_last);
    expect(b.elemId.reduce((s, v) => s + v, 0)).toBe(exp.elem_id_sum);
    expect(b.elemType.filter((t) => t === 3).length).toBe(exp.n_sh3n);
    expect(b.elemType.every((t) => t === 3 || t === 4)).toBe(true);
    expect(b.fixed.reduce((s, v) => s + v, 0)).toBe(exp.fixed_n);
    // 쓰기 = 코어와 같은 바이트·같은 layout
    const w = writeSelectBin(b);
    expect(w.bin.layout).toEqual(mf.bin.layout);
    expect(new Uint8Array(w.buf)).toEqual(new Uint8Array(raw));
  });

  it("layout 이 없거나 길이·개수가 다르면 거부", () => {
    const raw = bin("select.bin");
    expect(() => parseSelectBin(raw.slice(0, raw.byteLength - 4), mf)).toThrow(/길이/);
    expect(() => parseSelectBin(raw, { ...mf, n_nodes: mf.n_nodes + 1 })).toThrow(/개수/);
    expect(() => parseSelectBin(raw, { ...mf, bin: { ...mf.bin, layout: undefined as never } })).toThrow(/layout/);
  });
});

describe("V-BS-FMT basis.json·basis.bin(코어 basis_meta·basis_bin 픽스처)", () => {
  it("키 vars[{name,type,bead,nominal,n,R_mm}] — n̂_b 없이 basis.bin 3D 벡터로 모핑·색", () => {
    expect(Object.keys(meta)).not.toContain("beads");
    for (const v of meta.vars) expect(Object.keys(v).sort()).toEqual(["R_mm", "bead", "n", "name", "nominal", "type"]);
    expect(meta.vars.filter((v) => v.type === "W").every((v) => (v.R_mm ?? 0) > 0)).toBe(true);
    const vars = parseBasis(bin("basis.bin"), meta);
    expect(vars.map((v) => v.name)).toEqual(meta.vars.map((v) => v.name));
    const n = mf.n_nodes;
    expect(meta.n_nodes).toBe(n);
    // idx < n_nodes 검사: 가장 큰 idx 이하 노드 수 → 거부, 검사 없이(undefined) 는 통과
    const maxIdx = Math.max(...vars.map((v) => Math.max(...v.idx)));
    expect(() => parseBasis(bin("basis.bin"), { ...meta, n_nodes: maxIdx })).toThrow(/노드 번호/);
    expect(() => parseBasis(bin("basis.bin"), meta, maxIdx + 1)).not.toThrow();
    const u = morph(vars, exp.values, n);
    expect(Math.abs(maxAbs(u) - exp.u_max_abs)).toBeLessThan(1e-4);
    const s = [0, 0, 0];
    for (let i = 0; i < n; i++) for (let c = 0; c < 3; c++) s[c] += u[i * 3 + c];
    for (let c = 0; c < 3; c++) expect(Math.abs(s[c] - exp.u_sum[c])).toBeLessThan(1e-2);
    // 비드 방향(깊이 기저 합) ≈ 코어 n̂_b
    const dirs = beadDirections(vars);
    for (const [b, nh] of Object.entries(exp.n_hat)) {
      const d = dirs.get(b)!;
      expect(d[0] * nh[0] + d[1] * nh[1] + d[2] * nh[2]).toBeGreaterThan(0.999);
    }
    // 깊이 +1.5 → 색 양수(깊어짐 +)
    const dOnly = Object.fromEntries(meta.vars.filter((v) => v.type === "D").map((v) => [v.name, exp.values[v.name]]));
    const c = heightChange(vars, dOnly, n);
    expect(maxAbs(c)).toBeGreaterThan(1);
    expect(Math.min(...c)).toBeGreaterThanOrEqual(-1e-4);
  });
});
