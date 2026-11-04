// v0.15.1 지우기(esl_bead_select.md §11.2 확장): 층 비우기 · 비드 삭제(번호·이름 정리, 묶음 함께) · 마지막 단 삭제 — 모두 History 패치 1개로 되돌림·다시.
import { describe, expect, it } from "vitest";
import { History } from "../view3d/select/history";
import { addBead, addTier, applyPatch, clearLayer, deleteBead, deleteLastTier, resetAll, resetBead, emptyState, effectiveSlope, ownerCode, paint, toggleLink, type LayerName } from "../view3d/select/layers";

const undo = (s: ReturnType<typeof emptyState>, h: History<LayerName>) => {
  const p = h.undo()!;
  applyPatch(s, { ...p, changes: [...p.changes].reverse() }, "undo");
};
const redo = (s: ReturnType<typeof emptyState>, h: History<LayerName>) => applyPatch(s, h.redo()!, "redo");

function three() {
  const s = emptyState(30);
  for (let i = 0; i < 3; i++) addBead(s, 20, 1);
  paint(s, [0, 1, 2], { kind: "tier", bead: 0, k: 1 }, "add");
  paint(s, [10, 11], { kind: "tier", bead: 1, k: 1 }, "add");
  addTier(s, 1, 6);
  paint(s, [12], { kind: "tier", bead: 1, k: 2 }, "add");
  toggleLink(s.beads[1], 1, 2);
  paint(s, [20, 21], { kind: "tier", bead: 2, k: 1 }, "add");
  paint(s, [22], { kind: "slope", bead: 2 }, "add");
  s.remove[23] = 2;
  s.beads[2].name = "원형";
  return s;
}

describe("지우기", () => {
  it("비드 삭제: 그 요소 비움 · 뒤 비드 번호 당김(id·기본 이름) · 묶음 함께 · 실행 취소·다시", () => {
    const s = three();
    const h = new History<LayerName>();
    const before = { owner: s.owner.slice(), remove: s.remove.slice(), beads: JSON.stringify(s.beads) };
    h.push(deleteBead(s, 1)!);
    expect(s.beads.map((b) => [b.id, b.name])).toEqual([["b1", "B1"], ["b2", "원형"]]);
    expect(s.beads.every((b) => b.links.length === 0)).toBe(true);
    expect([s.owner[10], s.owner[11], s.owner[12]]).toEqual([-1, -1, -1]);
    expect(s.owner[20]).toBe(ownerCode(1, 1));
    expect(s.owner[22]).toBe(ownerCode(1, 0));
    expect(s.remove[23]).toBe(1);
    expect(s.owner[0]).toBe(ownerCode(0, 1));
    undo(s, h);
    expect([...s.owner]).toEqual([...before.owner]);
    expect([...s.remove]).toEqual([...before.remove]);
    expect(JSON.stringify(s.beads)).toBe(before.beads);
    redo(s, h);
    expect(s.beads.map((b) => b.id)).toEqual(["b1", "b2"]);
    // 첫 비드 삭제 → B2(기본 이름) 가 B1 로
    const t = three();
    deleteBead(t, 0);
    expect(t.beads.map((b) => [b.id, b.name])).toEqual([["b1", "B1"], ["b2", "원형"]]);
  });

  it("마지막 단 삭제: 바닥 비움·묶음에서 빠짐, 단 1 개면 불가", () => {
    const s = three();
    const h = new History<LayerName>();
    expect(deleteLastTier(s, 0)).toBeNull();
    h.push(deleteLastTier(s, 1)!);
    expect(s.beads[1].nTiers).toBe(1);
    expect(s.beads[1].links).toEqual([]);
    expect(s.owner[12]).toBe(-1);
    undo(s, h);
    expect(s.beads[1].nTiers).toBe(2);
    expect(s.beads[1].links).toEqual([[1, 2]]);
    expect(s.owner[12]).toBe(ownerCode(1, 2));
  });

  it("층 비우기: 단·사면(자동 포함)·고정 — 패치 1개, 실행 취소", () => {
    const s = three();
    const h = new History<LayerName>();
    h.push(clearLayer(s, { kind: "tier", bead: 0, k: 1 }));
    expect([s.owner[0], s.owner[1], s.owner[2]]).toEqual([-1, -1, -1]);
    undo(s, h);
    expect(s.owner[1]).toBe(ownerCode(0, 1));
    const sug = new Uint8Array(30);
    sug[24] = sug[25] = 1;
    const sg = (b: number) => (b === 2 ? sug : null);
    expect([...effectiveSlope(s, 2, sug)].reduce((a, v) => a + v, 0)).toBe(3);
    h.push(clearLayer(s, { kind: "slope", bead: 2 }, sg));
    expect([...effectiveSlope(s, 2, sug)].reduce((a, v) => a + v, 0)).toBe(0);
    undo(s, h);
    expect([...effectiveSlope(s, 2, sug)].reduce((a, v) => a + v, 0)).toBe(3);
    paint(s, [5, 6], { kind: "fixed" }, "add");
    h.push(clearLayer(s, { kind: "fixed" }));
    expect(s.fixed[5] + s.fixed[6]).toBe(0);
    expect(h.size).toBe(1); // 앞의 두 패치는 되돌려 다시 실행 목록으로 갔다가 새 패치로 비워짐
    expect(h.canRedo).toBe(false);
  });

  it("이 비드 초기화(이름·단 유지)·전체 초기화(비드·고정 모두) — 실행 취소·다시", () => {
    const s = three();
    const h = new History<LayerName>();
    paint(s, [5], { kind: "fixed" }, "add");
    h.push(resetBead(s, 2)!);
    expect([s.owner[20], s.owner[22], s.remove[23]]).toEqual([-1, -1, -1]);
    expect(s.beads[2].name).toBe("원형");
    expect(s.owner[0]).toBe(ownerCode(0, 1));
    undo(s, h);
    expect(s.owner[22]).toBe(ownerCode(2, 0));
    expect(s.remove[23]).toBe(2);
    const snap = JSON.stringify(s.beads);
    h.push(resetAll(s));
    expect(s.beads).toEqual([]);
    expect([...s.owner].every((v) => v === -1) && s.fixed[5] === 0).toBe(true);
    undo(s, h);
    expect(JSON.stringify(s.beads)).toBe(snap);
    expect(s.fixed[5]).toBe(1);
    redo(s, h);
    expect(s.beads).toEqual([]);
  });
});
