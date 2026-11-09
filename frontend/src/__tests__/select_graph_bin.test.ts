// v0.17.0 BEADGRAPH 단위 시험(esl_beadgraph.md V-BG-17 의 화면 밖 부분): graph.bin 디코드(형식·220k ≤ 200 ms) · 앵커 해석 ·
// 트리 ↔ 3D 대상 대응(targetOfElem ↔ targetMask) · 강조 색 · 그래프 편집(세그먼트 더하기/빼기·섬↔비드·병합·분할·대칭 묶기) · schema 2 직렬화 · seed 초기화.
import { describe, expect, it } from "vitest";
import { graphClick } from "../components/BeadSelectCard";
import { graphMesh, graphAutoSeed } from "../mock/graphmock";
import {
  buildTree, editView, graphColors, graphIndex, parseGraphBin, planXY, repOf, resolveRef, segOfAnchor, targetMask, targetOfElem, writeGraphBin, GRAPH_BIN_ARRAYS, type GraphLabels,
} from "../view3d/select/graph";
import {
  applyPatch, beadOfSeg, beadSegs, cloneState, deleteBead, emptyState, fromSelectionIn, groupNetwork, mergeSegs, resetAllTo, resetBeadTo, resetBead, splitSeg, toSelectionAny, toggleIsland, toggleSeg, toggleTie, addGraphBead, reresolve,
} from "../view3d/select/layers";
import { elemIndex } from "../view3d/select/ranges";
import type { DoeSelectionV2 } from "../api/types";

const lab = (n: number, f: (i: number) => number): GraphLabels => {
  const o = {} as GraphLabels;
  GRAPH_BIN_ARRAYS.forEach((k, j) => (o[k] = Int32Array.from({ length: n }, (_, i) => f(i) + j)));
  return o;
};

describe("graph.bin(§6.1)", () => {
  it("쓰기 ↔ 읽기 왕복(머리 길이 + 머리 JSON + int32 LE 6배열), 요소 수 다르면 오류", () => {
    const l = lab(37, (i) => (i % 5) - 1);
    const buf = writeGraphBin(l);
    const dv = new DataView(buf);
    const hl = dv.getUint32(0, true);
    const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl)));
    expect(head.n_elems).toBe(37);
    expect(head.arrays.map((a: { name: string }) => a.name)).toEqual(["cls", "segment", "junction_zone", "island", "floor", "tier"]);
    const r = parseGraphBin(buf, 37);
    for (const k of GRAPH_BIN_ARRAYS) expect([...r[k]]).toEqual([...l[k]]);
    expect(() => parseGraphBin(buf, 36)).toThrow(/요소 수/);
  });
  it("offset 이 머리 뒤(데이터 시작) 기준이어도 읽음", () => {
    const n = 5;
    const head = JSON.stringify({ n_elems: n, arrays: GRAPH_BIN_ARRAYS.map((name, k) => ({ name, offset: k * n * 4 })) });
    const hb = new TextEncoder().encode(head);
    const start = 4 + hb.length + ((4 - ((4 + hb.length) % 4)) % 4);
    const buf = new ArrayBuffer(start + 6 * n * 4);
    const dv = new DataView(buf);
    dv.setUint32(0, hb.length, true);
    new Uint8Array(buf, 4, hb.length).set(hb);
    for (let k = 0; k < 6; k++) for (let i = 0; i < n; i++) dv.setInt32(start + (k * n + i) * 4, k * 10 + i, true);
    const r = parseGraphBin(buf, n);
    expect([...r.island]).toEqual([30, 31, 32, 33, 34]);
  });
  it("220k 요소 디코드 ≤ 200 ms(§7)", () => {
    const buf = writeGraphBin(lab(220_000, (i) => i % 23));
    const t0 = performance.now();
    parseGraphBin(buf, 220_000);
    expect(performance.now() - t0).toBeLessThan(200);
  });
});

describe("H6 목 그래프: 앵커·트리·트리 ↔ 3D", () => {
  const m = graphMesh();
  const gi = graphIndex(m.graph, m.labels);
  it("세그먼트·접합 구역·섬 수, 앵커 = 그 세그먼트 최소 요소, 고리 4변", () => {
    expect(m.graph.segments.length).toBe(19);
    expect(m.graph.junction_zones.length).toBe(15);
    for (const s of m.graph.segments) {
      expect(m.labels.segment[s.anchor]).toBe(s.id);
      expect(m.labels.segment.indexOf(s.id)).toBe(s.anchor);
      expect(segOfAnchor(gi, s.anchor)).toBe(s.id);
    }
    expect(new Set(m.graph.segments.filter((s) => s.type === "ring").map((s) => s.side))).toEqual(new Set(["top", "bottom", "left", "right"]));
    const net = m.graph.segments.find((s) => s.type === "ring")!.network;
    const na = Math.min(...m.graph.networks[net].segments.map((id) => gi.segById.get(id)!.anchor));
    expect(resolveRef(gi, { network: na }).sort()).toEqual([...m.graph.networks[net].segments].sort());
  });
  it("트리: 플랜지 → 고리 띠 → 플래토 → 채널·포켓, 접합 구역은 네트워크 아래", () => {
    const t = buildTree(gi)!;
    expect(t.name).toBe("플랜지");
    expect(t.holes).toBeGreaterThan(0);
    const band = t.children.find((c) => c.name === "고리 띠")!;
    expect(band.segs.filter((s) => s.type === "ring")).toHaveLength(6);
    expect(band.zones.length).toBeGreaterThan(0);
    const plat = band.children.find((c) => c.name === "플래토")!;
    expect(plat.children.map((c) => c.name).sort()).toEqual(["채널", "채널", "포켓", "포켓", "포켓"]);
  });
  it("트리 행 → 3D(targetMask) ↔ 3D 클릭(targetOfElem) → 같은 트리 행", () => {
    for (const s of m.graph.segments) {
      const mask = targetMask(gi, { kind: "seg", id: s.id });
      let any = false;
      for (let e = 0; e < mask.length; e++)
        if (mask[e]) {
          any = true;
          expect(targetOfElem(gi, e)).toEqual({ kind: "seg", id: s.id });
        }
      expect(any).toBe(true);
    }
    const z = m.graph.junction_zones[0];
    expect(targetOfElem(gi, z.anchor)).toEqual({ kind: "zone", id: z.id });
    const il = m.graph.islands[0];
    expect(targetOfElem(gi, il.anchor)).toEqual({ kind: "island", id: il.id });
  });
  it("강조 색: 강조 마스크 요소만 노랑 쪽으로, 세그먼트 색 모드 ↔ tier 모드", () => {
    const v = editView(gi, null);
    const s = m.graph.segments.find((x) => x.type === "channel")!;
    const hl = targetMask(gi, { kind: "seg", id: s.id });
    const plain = graphColors(gi, v, "segment", { active: new Set(), other: new Set(), highlight: null });
    const lit = graphColors(gi, v, "segment", { active: new Set(), other: new Set(), highlight: hl });
    const e = s.anchor;
    expect(lit[e * 4]).toBeGreaterThan(plain[e * 4] - 1);
    expect(lit[e * 4 + 2]).toBeLessThan(plain[e * 4 + 2]); // 노랑 = 파랑 성분 줄어듦
    const other = m.graph.segments.find((x) => x.type === "pocket")!.anchor;
    expect([...lit.slice(other * 4, other * 4 + 4)]).toEqual([...plain.slice(other * 4, other * 4 + 4)]);
    const tier = graphColors(gi, v, "tier", { active: new Set(), other: new Set(), highlight: null });
    expect([...tier.slice(e * 4, e * 4 + 3)]).not.toEqual([...plain.slice(e * 4, e * 4 + 3)]);
  });
  it("3D 클릭(graphClick): 강조 + 선택 도구 = 세그먼트 더하기, 분할 도구 = 평면 좌표로 분할, 접합 구역 = 강조만", () => {
    const calls: string[] = [];
    const ctrl = {
      setHighlight: (t: unknown) => calls.push(`hl:${JSON.stringify(t)}`),
      toggleSeg: (id: number) => calls.push(`seg:${id}`),
      toggleIslandRef: (id: number) => calls.push(`isl:${id}`),
      split: (id: number, at: [number, number]) => calls.push(`split:${id}:${at.join(",")}`),
      editV: editView(gi, null),
    };
    const s = m.graph.segments.find((x) => x.type === "channel")!;
    graphClick(ctrl, gi, { elem: s.anchor, point: [100, 200, -3] }, "pick", true);
    expect(calls).toEqual([`hl:{"kind":"seg","id":${s.id}}`, `seg:${s.id}`]);
    calls.length = 0;
    graphClick(ctrl, gi, { elem: s.anchor, point: [100.12345, 200, -3] }, "split", true);
    expect(calls[1]).toBe(`split:${s.id}:100.123,200`);
    calls.length = 0;
    const z = m.graph.junction_zones[0];
    graphClick(ctrl, gi, { elem: z.anchor, point: [0, 0, 0] }, "pick", true);
    expect(calls).toEqual([`hl:{"kind":"zone","id":${z.id}}`]);
    calls.length = 0;
    graphClick(ctrl, gi, { elem: s.anchor, point: [0, 0, 0] }, "pick", false); // 읽기 전용 = 강조만
    expect(calls).toHaveLength(1);
    expect(planXY(gi, [1, 2, 3])).toEqual([1, 2]);
  });
});

describe("그래프 편집(layers, 실행 취소 가능)", () => {
  const m = graphMesh();
  const gi = graphIndex(m.graph, m.labels);
  const idx = elemIndex(m.elemId, m.elemType);
  const n = m.elemId.length;
  const seg = (t: string, k = 0) => m.graph.segments.filter((s) => s.type === t)[k];
  const fresh = () => emptyState(n, 2, { sha256: m.sha256, rules: 1 });

  it("세그먼트 더하기/빼기 · 다른 비드 것은 거부 · 실행 취소", () => {
    const s = fresh();
    const b1 = addGraphBead(s)!;
    const b2 = addGraphBead(s)!;
    expect(s.beads.map((b) => [b.id, b.src, b.holdFixed])).toEqual([["b1", "graph", 1], ["b2", "graph", 1]]);
    const ch = seg("channel");
    const p = toggleSeg(s, gi, b1.bead, ch.id);
    expect(p.patch).toBeTruthy();
    expect(beadOfSeg(s, gi, ch.id)).toBe(0);
    expect(toggleSeg(s, gi, b2.bead, ch.id)).toEqual({ patch: null, reason: "B1 에 들어 있습니다" });
    expect(toggleSeg(s, gi, b1.bead, seg("base").id).reason).toMatch(/플랜지/);
    applyPatch(s, p.patch!, "undo");
    expect(beadOfSeg(s, gi, ch.id)).toBe(-1);
    applyPatch(s, p.patch!, "redo");
    expect(beadOfSeg(s, gi, ch.id)).toBe(0);
    toggleSeg(s, gi, 0, ch.id);
    expect(s.beads[0].segs).toEqual([]);
  });
  it("네트워크 전체로 묶기 → {network} 1개, 그 중 하나를 빼면 나머지 앵커로 풂", () => {
    const s = fresh();
    addGraphBead(s);
    const ring = seg("ring");
    groupNetwork(s, gi, 0, ring.id);
    expect(s.beads[0].segs).toHaveLength(1);
    expect("network" in s.beads[0].segs![0]).toBe(true);
    const all = beadSegs(s, gi, 0);
    expect(all.size).toBe(m.graph.networks[ring.network].segments.length);
    toggleSeg(s, gi, 0, ring.id);
    expect(beadSegs(s, gi, 0).size).toBe(all.size - 1);
    expect(s.beads[0].segs!.every((r) => "anchor" in r)).toBe(true);
  });
  it("병합: 같은 바닥 이웃만, 비드 참조는 대표(최소 앵커)로 · editView 그룹", () => {
    const s = fresh();
    addGraphBead(s);
    const ch = seg("channel");
    const fl = m.graph.segments.find((x) => x.type === "flare" && x.floor === ch.floor)!;
    toggleSeg(s, gi, 0, fl.id);
    expect(mergeSegs(s, gi, ch.id, seg("pocket").id)).toBeNull(); // 다른 바닥
    const p = mergeSegs(s, gi, ch.id, fl.id)!;
    const rep = Math.min(ch.anchor, fl.anchor);
    expect(s.edits!.merge).toEqual([[{ anchor: Math.min(ch.anchor, fl.anchor) }, { anchor: Math.max(ch.anchor, fl.anchor) }]]);
    expect(s.beads[0].segs).toEqual([{ anchor: rep }]);
    const v = editView(gi, s.edits);
    expect(repOf(v, ch.id)).toBe(repOf(v, fl.id));
    expect(beadSegs(s, gi, 0)).toEqual(new Set([ch.id, fl.id]));
    applyPatch(s, p, "undo");
    expect(s.edits!.merge).toEqual([]);
    expect(s.beads[0].segs).toEqual([{ anchor: fl.anchor }]);
  });
  it("분할 · 섬 ↔ 비드 전환(원래대로 되돌리면 항목 삭제) · 섬으로 바꾸면 비드에서 빠짐", () => {
    const s = fresh();
    addGraphBead(s);
    const ch = seg("channel");
    splitSeg(s, ch.anchor, [450, 300]);
    expect(splitSeg(s, ch.anchor, [450, 300])).toBeNull(); // 같은 점 중복 없음
    expect(s.edits!.split).toEqual([{ anchor: ch.anchor, at: [450, 300] }]);
    const il = m.graph.islands.find((x) => !x.lance)!;
    toggleIsland(s, il.anchor, "bead", "island");
    expect(s.edits!.toggle).toEqual([{ anchor: il.anchor, as: "bead" }]);
    expect(editView(gi, s.edits).islandAsBead.has(il.id)).toBe(true);
    toggleIsland(s, il.anchor, "island", "island");
    expect(s.edits!.toggle).toEqual([]);
    toggleSeg(s, gi, 0, ch.id);
    toggleIsland(s, ch.anchor, "island", "bead");
    expect(s.edits!.toggle).toEqual([{ anchor: ch.anchor, as: "island" }]);
    expect(s.beads[0].segs).toEqual([]);
  });
  it("대칭 묶기 켜기/끄기 · 비드 삭제 시 묶기 번호 정리", () => {
    const s = fresh();
    for (let i = 0; i < 4; i++) addGraphBead(s);
    toggleTie(s, ["b3", "b4"]);
    toggleTie(s, ["b2", "b4"]); // b4 는 새 묶음으로 옮김 → b3 혼자 = 사라짐
    expect(s.ties).toEqual([["b2", "b4"]]);
    deleteBead(s, 0);
    expect(s.beads.map((b) => b.id)).toEqual(["b1", "b2", "b3"]);
    expect(s.ties).toEqual([["b1", "b3"]]);
    toggleTie(s, ["b3", "b1"]);
    expect(s.ties).toEqual([]);
  });
  it("schema 2 직렬화: 앵커 정렬·hold_fixed 0 만·그래프 sha·편집 정규화 → 읽기 왕복 같음, 그래프 없으면 graph 키 없음", () => {
    const s = fresh();
    addGraphBead(s);
    const a = seg("leg", 1);
    const b = seg("leg", 0);
    toggleSeg(s, gi, 0, a.id);
    toggleSeg(s, gi, 0, b.id);
    splitSeg(s, a.anchor, [5, 1]);
    splitSeg(s, a.anchor, [1, 1]);
    s.beads[0].holdFixed = 0;
    const out = toSelectionAny(s, m.elemId, m.elemType, 15) as DoeSelectionV2;
    expect(out.schema_version).toBe(2);
    expect(out.graph!.sha256).toBe(m.sha256);
    expect(out.beads[0]).toEqual({ id: "b1", name: "B1", src: "graph", segs: [{ anchor: Math.min(a.anchor, b.anchor) }, { anchor: Math.max(a.anchor, b.anchor) }], hold_fixed: 0 });
    expect(out.graph!.edits.split.map((x) => x.at)).toEqual([[1, 1], [5, 1]]);
    const back = fromSelectionIn(out, idx, n).state;
    expect(JSON.stringify(toSelectionAny(back, m.elemId, m.elemType, 15))).toBe(JSON.stringify(out));
    const noG = emptyState(n, 2, null);
    expect("graph" in toSelectionAny(noG, m.elemId, m.elemType, 15)).toBe(false);
  });
  it("seed(자동 분류): 비드 = 고리 4변 + 다리 4 + 채널 2(나팔 포함) + 포켓 + 플래토, 초기화 = seed(세그먼트·편집·묶기)", () => {
    const auto = graphAutoSeed();
    const sel = auto.selection as DoeSelectionV2;
    expect(auto.source).toBe("graph");
    const names = sel.beads.map((b) => b.name);
    expect(names.filter((x) => x?.startsWith("고리"))).toHaveLength(4);
    expect(names.filter((x) => x?.startsWith("다리"))).toHaveLength(4);
    expect(names.filter((x) => x?.startsWith("채널"))).toHaveLength(2);
    expect(names).toContain("플래토");
    const bottom = sel.beads.find((b) => b.name === "고리 아래")!;
    expect(bottom.src === "graph" && bottom.segs.length).toBe(3); // 아래 변 = 세그먼트 3개(T 접합 포함)
    const seed = fromSelectionIn(sel, idx, n).state;
    const s = cloneState(seed);
    const bi = s.beads.findIndex((b) => b.name === "채널 1");
    const ch = [...beadSegs(s, gi, bi)][0];
    toggleSeg(s, gi, bi, ch);
    toggleTie(s, ["b1", "b2"]);
    splitSeg(s, gi.segById.get(ch)!.anchor, [1, 2]);
    const p = resetBeadTo(s, bi, seed)!;
    expect(s.beads[bi].segs).toEqual(seed.beads[bi].segs);
    expect(s.ties).toEqual([["b1", "b2"]]); // 비드 초기화는 묶기·편집을 건드리지 않음
    applyPatch(s, p, "undo");
    expect(s.beads[bi].segs!.length).toBe(seed.beads[bi].segs!.length - 1);
    resetAllTo(s, seed);
    expect(JSON.stringify(toSelectionAny(s, m.elemId, m.elemType, 15))).toBe(JSON.stringify(toSelectionAny(seed, m.elemId, m.elemType, 15)));
    // seed 없는 비드 초기화 = 세그먼트 비움
    const q = fresh();
    addGraphBead(q);
    toggleSeg(q, gi, 0, ch);
    resetBead(q, 0);
    expect(q.beads[0].segs).toEqual([]);
  });
  it("BG_GRAPH_STALE 재해석: 앵커가 다른 요소여도 그 요소의 세그먼트 앵커로, 못 찾으면 unknown", () => {
    const s = emptyState(n, 2, { sha256: "old", rules: 0 });
    addGraphBead(s);
    const ch = seg("channel");
    s.beads[0].segs = [{ anchor: ch.anchor + 1 }, { anchor: n + 5 }];
    const r = reresolve(s, gi, m.sha256, 1);
    expect(r.unknown).toEqual([n + 5]);
    expect(s.graphRef).toEqual({ sha256: m.sha256, rules: 1 });
    expect(s.beads[0].segs).toContainEqual({ anchor: ch.anchor });
  });
});
