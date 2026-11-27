// V-0252-30·31 (F1 몫) + #96: 스터디 결과 화면 — 제목 개수·빈 주 탭 → 순위 있는 탭·빈 탭 안내 링크·"참고" 꼬리표·옛 결과 불변,
// 3D 강제 부여 표식(자홍 테두리·빈 고리 + 선·✕·범례·탐침)·SHAPE_DOUBLE_SHEET 배지. 화면 높이 증가 0 은 scripts/screenshots-v0252-f1.mjs.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PickEvent } from "../view3d/sceneApi";

const h = vi.hoisted(() => ({ scenes: [] as unknown[] }));
vi.mock("../view3d/webgl", () => ({ hasWebGL: () => true }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => ({
    createScene: (_c: unknown, opts: unknown) => {
      const calls: Record<string, unknown[][]> = {};
      let pick: ((e: PickEvent) => void) | null = null;
      const rec = (name: string) => (...a: unknown[]) => {
        (calls[name] ??= []).push(a);
      };
      let proj = (opts as { projection?: string }).projection ?? "ortho";
      const api = {
        calls,
        opts,
        setProjection: (p: string) => {
          proj = p;
        },
        projection: () => proj,
        emit: (e: PickEvent) => pick?.(e),
        setGeometry: rec("setGeometry"),
        setColors: rec("setColors"),
        setDeform: rec("setDeform"),
        setArrows: rec("setArrows"),
        setSupports: rec("setSupports"),
        setTieMarks: rec("setTieMarks"),
        select: rec("select"),
        focus: rec("focus"),
        fit: rec("fit"),
        setView: rec("setView"),
        onPick: (cb: (e: PickEvent) => void) => (pick = cb),
        stats: () => ({ renders: 0 }),
        dispose: rec("dispose"),
      };
      h.scenes.push(api);
      return api;
    },
  }),
}));

import { renderApp } from "../test/render";
import { COUNT_LABELS, countItems, countTail, otherRankedTab, rankRows, tabState, LOAD_SOURCES } from "../pages/doe/doeTabs";
import { tieForcedText } from "../api/doe";
import { MARK_TABLE, TIE_PX, TIE_TABLE, markLegend, tieProbe } from "../view3d/supportMarks";
import { buildSupportSpecs, buildTieMarks } from "../view3d/supports";
import { infoLine } from "../view3d/info";
import { selectionFromPick } from "../view3d/selection";
import type { DoeResultOut, View3dOut, View3dSupport, View3dTieMark } from "../api/types";

afterEach(() => {
  cleanup();
  h.scenes.length = 0;
});
const tabBtn = (k: string) => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => s.doe.demoJigForce());
type Fake = { calls: Record<string, unknown[][]>; emit: (e: PickEvent) => void };
const scene = () => h.scenes[h.scenes.length - 1] as Fake;
const last = (n: string) => scene().calls[n]?.slice(-1)[0];

describe("개수 항목(순수)", () => {
  it("#96 꼴 n_failed {jd:1} → '지그 매핑 제외 1', 0 인 키는 안 나옴, 덧붙일 키 없으면 빈 꼬리(지금과 같은 글자)", () => {
    const r = { n_ok: 0, n_skipped: {}, n_failed: { mesh: 0, size: 0, solve: 0, jd: 1 } };
    expect(countItems(r).map((x) => [x.key, x.label, x.n])).toEqual([["ok", "성공", 0], ["jd", "지그 매핑 제외", 1]]);
    expect(countTail(r)).toBe(" · 지그 매핑 제외 1");
    expect(countTail({ n_ok: 3, n_skipped: { collision: 0 }, n_failed: { mesh: 0 } })).toBe("");
    expect(countTail({ n_ok: 1, n_skipped: {}, n_failed: {}, n_ref: 1 })).toBe(" · 참고용 1");
  });
  it("통합: counts 없는 결과(TM-C1-2 — 격자 지그·강제 부여 스냅샷 밖)의 계산 = 서버 count_items 와 같은 합·순서", () => {
    // 기대값 = esl.doe.rank.count_items({n_ok:2, n_skipped:{collision:1, mesh:1}, n_failed:{zz:1, mesh:2, jd:1, size:0}, n_ref:1}) 출력
    const r = { n_ok: 2, n_skipped: { collision: 1, mesh: 1 }, n_failed: { zz: 1, mesh: 2, jd: 1, size: 0 }, n_ref: 1 };
    expect(countItems(r).map((x) => [x.key, x.label, x.n])).toEqual([
      ["ok", "성공", 2], ["mesh", "메시", 3], ["collision", "스킵(충돌)", 1], ["jd", "지그 매핑 제외", 1], ["zz", "zz", 1], ["ref", "참고용", 1],
    ]);
  });
  it("API counts 가 있으면 그대로(새 결과), 라벨 거울 키", () => {
    const counts = [{ key: "ok", label: "성공", n: 1 }, { key: "x", label: "서버 라벨", n: 2 }];
    expect(countTail({ n_ok: 1, n_skipped: {}, n_failed: { jd: 9 }, counts })).toBe(" · 서버 라벨 2");
    expect(Object.keys(COUNT_LABELS).sort()).toEqual(["bf", "collision", "fi", "fixed", "geom", "jd", "jig", "js", "mesh", "morph", "ok", "ref", "size", "sm", "solve"]);
  });
});

describe("기본 탭·빈 탭 안내(순수)", () => {
  it("주 출처 순위 0 행 + 다른 탭 순위 있음 → 출처 표 순서 처음 그 탭", () => {
    const r = {
      metric_effective: "jig", ranking: [], n_ok: 0, n_skipped: {}, n_failed: { jd: 1 }, warnings: [],
      rank_views: { jig_disp: { ranking: [] }, full: { ranking: [{ id: "d001" }] } },
    } as unknown as DoeResultOut;
    const ts = tabState(r, LOAD_SOURCES);
    expect(ts.def).toBe("full");
    expect(rankRows(r, "jig_disp", "jig")).toBe(0);
    expect(otherRankedTab(r, "jig_disp", LOAD_SOURCES)?.key).toBe("full");
    expect(otherRankedTab(r, "full", LOAD_SOURCES)).toBeNull();
  });
  it("주 출처에 순위가 있으면 지금 그대로, 모든 탭이 비면 주 출처 그대로", () => {
    const ok = { metric_effective: "jig", ranking: [{ id: "d001" }], n_skipped: {}, n_failed: {}, warnings: [], rank_views: { full: { ranking: [{ id: "d001" }] } } } as unknown as DoeResultOut;
    expect(tabState(ok, LOAD_SOURCES).def).toBe("jig");
    const none = { metric_effective: "jig", ranking: [], n_skipped: {}, n_failed: {}, warnings: [], rank_views: { full: { ranking: [] } } } as unknown as DoeResultOut;
    expect(tabState(none, LOAD_SOURCES).def).toBe("jig");
  });
});

describe("스터디 결과 화면", () => {
  it("#96 꼴(doe-81): 제목 '지그 매핑 제외 1' · 기본 탭 = 순위 있는 탭 · 빈 탭 안내 + 링크", async () => {
    open("doe-81");
    // 기본 탭 = 전 노드(순위 있음) — 제목은 그 보기의 개수, 순위표가 보이고 안내는 아직 없음
    const head = await screen.findByRole("heading", { name: /② 결과 · OK/ }, { timeout: 10000 });
    expect(head.textContent).toBe("② 결과 · OK 1개 형상");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(screen.queryByTestId("empty-rank-note")).toBeNull();
    fireEvent.click(tabBtn("jig_disp"));
    await waitFor(() => expect(screen.getByRole("heading", { name: /② 결과 · OK/ }).textContent).toBe("② 결과 · OK 0개 형상 · 지그 매핑 제외 1"));
    const note = await screen.findByTestId("empty-rank-note");
    expect(note.textContent).toMatch(/^이 하중 출처에는 순위에 든 형상이 없습니다\(지그 매핑 제외 1\) — \[.+\] 탭에는 순위가 있습니다$/);
    fireEvent.click(screen.getByTestId("empty-rank-link"));
    await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(screen.queryByTestId("empty-rank-note")).toBeNull());
  });
  it("강제 부여(doe-80): 제목 '참고용 1' · 순위표 '참고' 꼬리표(title = 강제 경고 문구) · 경고 문구", async () => {
    open("doe-80");
    const head = await screen.findByRole("heading", { name: /② 결과 · OK/ }, { timeout: 10000 });
    expect(head.textContent).toMatch(/^② 결과 · OK \d+개 형상 · 참고용 1$/);
    const table = await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const tags = await within(table).findAllByText("참고");
    expect(tags.length).toBe(1);
    expect(tags[0].getAttribute("title")).toMatch(/강제로 붙였습니다/);
    expect(document.body.textContent).toMatch(/지그 순위는 참고용입니다/);
  });
  it("옛 결과(doe-60 — counts·jig_ref 없음): 제목 글자 그대로·꼬리표 없음", async () => {
    open("doe-60");
    const head = await screen.findByRole("heading", { name: /② 결과 · OK/ }, { timeout: 10000 });
    expect(head.textContent).toMatch(/^② 결과 · OK \d+개 형상$/);
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(screen.queryByText("참고")).toBeNull();
  });
  it("tieForcedText: did 로 그 형상 경고를 찾음", () => {
    const w = [{ code: "JIG_GRID_TIE_FORCED", did: "d002", message: "형상 d002: 강제" }, { code: "JIG_GRID_TIE_FORCED", did: "d003", message: "형상 d003: 강제" }];
    expect(tieForcedText(w, "d003")).toBe("형상 d003: 강제");
  });
});

describe("3D 강제 부여 표식", () => {
  const sup = (id: number, via?: "force"): View3dSupport => ({ node_id: id, vertex: id, dof: "123", x0: [id * 100, 0, 0], kind: "tie_disp", dirs: [[0, 0, 1]], val: [0.5], ...(via ? { via } : {}) });
  const marks: View3dTieMark[] = [
    { q: 1, via: "force", x: [115, 0, 0], dist: 15, n: 2, far: false },
    { q: 2, via: "force", x: [260, 0, 0], dist: 60, n: 2, far: true },
    { q: 3, via: "miss", x: [0, 300, 0], dist: 0, n: 1, far: false },
  ];
  it("강제 지지만 자홍 테두리(outline), 옛 manifest(via 없음)는 그대로", () => {
    const specs = buildSupportSpecs([sup(1, "force"), sup(2)], null, 0, 500);
    expect(specs[0].outline).toBe(TIE_TABLE.force.color);
    expect(specs[1].outline).toBeUndefined();
    expect(specs[0].markColor).toBe(MARK_TABLE.tie_disp.color); // 기호 색은 그대로 — 테두리는 겹으로
  });
  it("빈 고리 + 선(선 끝 = 가장 가까운 강제 지지), 먼 강제 = 빨강 굵은 선, 못 붙임 = ✕", () => {
    const specs = buildSupportSpecs([sup(1, "force"), sup(2, "force")], null, 0, 500);
    const t = buildTieMarks(marks, specs, 500, [0, 0, 1]);
    const by = (c: string, px: number) => t.layers.find((l) => l.color === c && l.widthPx === px);
    expect(by(TIE_TABLE.ring.color, TIE_PX.ring)!.segs.length).toBe(2 * 20);           // 고리 2개(꼭짓점 20)
    const near = by(TIE_TABLE.ring.color, TIE_PX.line)!;
    expect(near.segs.length).toBe(1);
    expect(Math.hypot(...(near.segs[0][1].map((v, i) => v - 100 * 1 * (i === 0 ? 1 : 0)) as number[]))).toBeCloseTo(0, 6); // 끝 = 지지 1 위치
    const far = by(TIE_TABLE.far.color, TIE_PX.far)!;
    expect(far.segs.length).toBe(1);                                                    // 먼 강제 1개
    expect(by(TIE_TABLE.miss.color, TIE_PX.ring)!.segs.length).toBe(2);                 // ✕ = 선분 2개
    expect(t.picks.map((p) => p.index)).toEqual([0, 1, 2]);
    // 선 길이 = 옮긴 거리(고리 가장자리 제외 — 중심~지지 거리에서 고리 반지름 뺀 만큼)
    const L = 0.04 * 500;
    const d = Math.hypot(...[0, 1, 2].map((i) => far.segs[0][1][i] - far.segs[0][0][i]));
    expect(d).toBeCloseTo(Math.hypot(260 - 200, 0, 0) - 0.5 * L, 6);
  });
  it("통합: 코어 marks[].to(붙인 노드 면적 가중 중심)가 있으면 선 끝 = to(가장 가까운 지지가 아님), miss dist null 탐침", () => {
    const specs = buildSupportSpecs([sup(1, "force"), sup(2, "force")], null, 0, 500);
    const withTo: View3dTieMark[] = [{ q: 1, via: "force", x: [115, 0, 0], to: [140, 30, 0], dist: 15, n: 2, far: false }];
    const t = buildTieMarks(withTo, specs, 500, [0, 0, 1]);
    const near = t.layers.find((l) => l.color === TIE_TABLE.ring.color && l.widthPx === TIE_PX.line)!;
    expect(near.segs[0][1]).toEqual([140, 30, 0]);
    expect(tieProbe({ q: 4, via: "miss", dist: null, far: false })).toBe("체결부 q4 · 붙일 면 없음");
  });
  it("강제 지지가 없으면 선 없음(고리만) · tie_marks 없으면 표식 없음", () => {
    const specs = buildSupportSpecs([sup(1), sup(2)], null, 0, 500);
    const t = buildTieMarks(marks.slice(0, 1), specs, 500, null);
    expect(t.layers.map((l) => l.widthPx)).toEqual([TIE_PX.ring]);
  });
  it("범례: 강제·고리·✕ 항목은 해당 표식이 있을 때만, 먼 임계는 있을 때만 숫자", () => {
    const none = markLegend([sup(1)], true);
    expect(none.join()).not.toMatch(/자홍|빈 고리|✕/);
    const all = markLegend([sup(1, "force")], true, marks, 10);
    expect(all).toContain("자홍 테두리 = 체결부가 아닌 곳에 강제로 붙인 지지");
    expect(all).toContain("빈 고리 = Case 체결부 자리(선 = 옮겨 붙인 거리 · 빨강 = 10 mm 넘음)");
    expect(all).toContain("✕ = 붙일 면이 없어 뺀 체결부");
    expect(markLegend([sup(1, "force")], true, marks.slice(0, 2))[2]).toMatch(/빨강 = 먼 곳/);
  });
  it("탐침: 고리·✕ 선택 → '체결부 q{n} · 거리 {d} mm'", () => {
    expect(tieProbe(marks[1])).toBe("체결부 q2 · 거리 60 mm · 먼 곳");
    expect(tieProbe(marks[2])).toBe("체결부 q3 · 붙일 면 없음");
    expect(selectionFromPick({ type: "tie", index: 1 }, [])).toEqual({ kind: "tie", index: 1 });
    const m = { supports: [], top: [], clusters: {}, tie_marks: marks } as unknown as View3dOut;
    expect(infoLine({ kind: "tie", index: 0 }, m, null, null)).toBe("체결부 q1 · 거리 15 mm");
  });
  it("화면(doe-80 지그 3D): 장면에 강제 테두리 지지·고리 표식이 전달되고 고리 클릭 = 탐침 줄", async () => {
    open("doe-80");
    await screen.findByTestId("doe-result-rows", {}, { timeout: 10000 });
    await waitFor(() => expect(tabBtn("jig_disp")).toBeTruthy());
    fireEvent.click(tabBtn("jig_disp"));
    await waitFor(() => expect(h.scenes.length).toBeGreaterThan(0), { timeout: 20000 });
    await waitFor(() => expect(last("setTieMarks")).toBeTruthy(), { timeout: 20000 });
    const spec = last("setTieMarks")![0] as { layers: { widthPx: number }[]; picks: unknown[] } | null;
    expect(spec?.picks.length).toBe(3);
    const sups = last("setSupports")![0] as { outline?: string }[];
    expect(sups.filter((s) => s.outline).length).toBe(2);
    scene().emit({ type: "tie", index: 1 });
    await waitFor(() => expect(document.body.textContent).toMatch(/체결부 q7 · 거리 257 mm · 먼 곳/));
  }, 40000);
});

describe("SHAPE_DOUBLE_SHEET", () => {
  it("형상 표 배지 title = 경고 문구 + 마주 보는 면 % · 간격 mm", async () => {
    const { warnText } = await import("../api/doe");
    expect(warnText({ code: "SHAPE_DOUBLE_SHEET" })).toMatch(/판 앞뒷면 표면이 둘 다 들어 있는 것 같습니다/);
  });
});
