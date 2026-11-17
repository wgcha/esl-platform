// V-SH-16(esl_bead_shape_v021.md §10): v0.21.0 BEAD_SHAPE 화면(목) — 변수 표 guard 꼬리표(축소·조합 축소·막힘·미점검)·W 부분 칩/세그먼트 `W —`,
// ④ 형상 행 "완화 직행" 칩, 순위 ⚠ + "품질 통과 최상위" 1줄, ③ 결과 띠 1줄, 옛 결과·선택 화면 그대로. 화면 크기(2560×1440·1920×1080)는 scripts/screenshots-v0210.mjs.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { cellWarnText, guardTag, isInfoWarn, mqText, mqTip, noWTip, routeChip, warnText, wPartialOf, wPartialTip } from "../api/doe";
import type { DoeGuard, DoeShapeRules } from "../api/types";
import { MOCK_SHAPE_RULES } from "../mock/doedata";
import { renderApp } from "../test/render";

const demo = (s: { doe: { demoShape: () => void } }) => s.doe.demoShape();
const G = (p: Partial<DoeGuard>): DoeGuard => ({ state: "ok", from: [10, 20], usable: [10, 20], reason: null, value: null, combo_scale: null, ...p });

describe("규칙 함수(수치는 입력 필드·스냅샷에서만)", () => {
  it("guardTag: ok·없음 = 꼬리표 없음, limited·blocked·unchecked = 라벨·종류·툴팁(사유·값·기준값)", () => {
    expect(guardTag(null)).toBeNull();
    expect(guardTag(G({}))).toBeNull();
    const lim = guardTag(G({ state: "limited", usable: [10, 17.5], reason: "jac", value: 0.214 }), MOCK_SHAPE_RULES)!;
    expect(lim.label).toBe("축소");
    expect(lim.kind).toBe("info");
    expect(lim.tip).toMatch(/10~20 → 10~17.5 mm/);
    expect(lim.tip).toMatch(/야코비안 저하 0.214/);
    expect(lim.tip).toContain(`기준 ${MOCK_SHAPE_RULES.range_guard!.jac_min}`);
    // 기준값 출처(스냅샷)가 없으면 값만
    expect(guardTag(G({ state: "limited", usable: [10, 17.5], reason: "jac", value: 0.214 }), null)!.tip).not.toMatch(/기준/);
    const blk = guardTag(G({ state: "blocked", usable: [14.6, 15.3], reason: "tri_angle", value: 7.8 }), MOCK_SHAPE_RULES)!;
    expect([blk.label, blk.kind]).toEqual(["막힘", "warn"]);
    expect(blk.tip).toMatch(/기본 체크를 해제/);
    expect(blk.tip).toMatch(/tria 최소 내각 저하 7.8/);
    const un = guardTag(G({ state: "unchecked", usable: null }))!;
    expect([un.label, un.kind]).toEqual(["미점검", "neutral"]);
    expect(un.tip).toMatch(/미리보기 준비에서 점검/);
    // 조합 축소(ok 여도 combo_scale < 1 이면 꼬리표)
    const cmb = guardTag(G({ combo_scale: 0.6875 }))!;
    expect(cmb.label).toBe("조합 축소");
    expect(cmb.tip).toMatch(/×0.69/);
    expect(guardTag(G({ combo_scale: 1 }))).toBeNull();
  });

  it("W 부분: wPartialOf(derive 비드 → graph 요약 비드 순) · 툴팁 문구", () => {
    expect(wPartialOf(undefined, undefined)).toBeNull();
    expect(wPartialOf({}, { segs: [1, 2, 3] })).toBeNull();
    const p = wPartialOf({ w_segs: [1, 3], w_cover: 0.75 }, { segs: [1, 2, 3] })!;
    expect(p).toMatchObject({ wSegs: [1, 3], noW: [2], cover: 0.75, n: 3 });
    expect(wPartialOf(undefined, { segs: [5, 6], w_segs: [5], w_cover: 0.4 })!.noW).toEqual([6]);
    expect(noWTip([12, 40])).toBe("폭 정보 없는 구간(입구 선 한쪽): #12 · #40 — 그 구간은 깊이만 바뀝니다");
    expect(wPartialTip([12, 40], 0.7512)).toMatch(/#12 · #40 — 비드 길이의 75 %/);
  });

  it("routeChip: cad 는 칩 없음, cad_relaxed = 완화 직행 + 면 수·기준(필드에서)", () => {
    expect(routeChip(null)).toBeNull();
    expect(routeChip({ path: "cad", reason: [], n_faces: 900, min_faces: 1500 })).toBeNull();
    const c = routeChip({ path: "cad_relaxed", reason: ["faces"], n_faces: 2800, min_faces: 1500 })!;
    expect(c.label).toBe("완화 직행");
    expect(c.tip).toMatch(/STEP 면 2,800 ≥ 1,500/);
    expect(routeChip({ path: "cad_relaxed", reason: ["step_mb"], n_faces: 100, step_mb: 61.25, min_faces: 1500, min_step_mb: 50 })!.tip).toMatch(/STEP 61.3 MB ≥ 50 MB/);
  });

  it("메시 품질 문구: 수치·기준은 mq·스냅샷에서, 경고 문구는 필드 보간", () => {
    expect(mqText({ fail_ratio: 0.555, tria_pct: 21.9 })).toBe("Fail 55.5 % · tria 21.9 %");
    const rq = (MOCK_SHAPE_RULES as DoeShapeRules).mesh_route.rank_quality;
    expect(mqTip({ fail_ratio: 0.555, tria_pct: 21.9, over: ["fail", "tria"] }, MOCK_SHAPE_RULES)).toBe(`메시 품질 미달 — Fail 55.5 % > ${(rq.fail_ratio * 100).toFixed(0)} % · tria 21.9 % > ${rq.tria_pct} % — 순위 신뢰도 낮음(순위는 유지)`);
    expect(mqTip({ fail_ratio: 0.12, tria_pct: 3, over: ["fail"] }, null)).toBe("메시 품질 미달 — Fail 12.0 % — 순위 신뢰도 낮음(순위는 유지)");
    expect(warnText({ code: "MESH_QUALITY_RANK", scope: "base", fail_ratio: 0.555, tria_pct: 21.9 })).toMatch(/기준 메시 품질 미달\(Fail 55.5 % · tria 21.9 %\).*순위는 유지/);
    expect(warnText({ code: "MESH_QUALITY_RANK", scope: "shapes", n: 2, shapes: [{ id: "d001", name: "F안", fail_ratio: 0.555, tria_pct: 21.9 }, { id: "d003", name: "G안", fail_ratio: 0.2, tria_pct: 9 }] })).toMatch(/2개\(F안 Fail 55.5 % · tria 21.9 %, G안 Fail 20.0 % · tria 9.0 %\)/);
  });

  it("§8 문구(서버 문구 없을 때): 필드 값 보간 · 정보 코드 = ⓘ · 서버 문구 우선", () => {
    expect(warnText({ code: "BG_W_PARTIAL", bead: "b5", n_w: 2, n_seg: 3, cover: 0.62, no_w: [1479] })).toBe("B5: 폭 W 는 폭 정보가 있는 2/3 구간(길이 62 %)에만 적용 — 나머지 구간은 깊이만 바뀝니다");
    expect(warnText({ code: "RG_RANGE_LIMITED", bead: "b1", var: "B1_D", from: [4.2, 7.8], to: [4.2, 6.5], side: "hi", reason: "jac", value: 0.214 })).toBe("B1_D: 기본 범위 4.2~7.8 → 4.2~6.5 mm 로 줄였습니다(상한 쪽 야코비안 저하 0.214)");
    expect(warnText({ code: "RG_VAR_BLOCKED", bead: "b11", var: "B11_W", usable: [30.1, 31], reason: "tri_angle" })).toMatch(/B11_W: 양쪽 모두 거의 움직일 수 없습니다\(안전 범위 30.1~31 mm\)/);
    expect(warnText({ code: "RG_COMBO_LIMITED", vars: ["B2_D", "B2_W"], corners: 4, bad_n: 1, scale: 0.6875, reason: "inverted" })).toBe("B2_D·B2_W: 함께 바꾸면 1/4 꼭짓점이 요소 뒤집힘 — 공통 비율 ×0.69 로 줄였습니다");
    expect(warnText({ code: "RG_UNCHECKED", var: "B4_D" })).toMatch(/B4_D: 준비 표에 없어 미점검/);
    expect(warnText({ code: "RG_BUDGET", done: 40, total: 120, evals: 4000, stopped: "evals" })).toMatch(/40\/120 변수만 점검/);
    expect(warnText({ code: "MESH_ROUTE_RELAXED", id: "d001", name: "F안", n_faces: 2800, min_faces: 1500 })).toBe("F안: STEP 면 2800 ≥ 1500 — cad 를 건너뛰고 완화 메싱으로 시작했습니다");
    expect(warnText({ code: "RG_RANGE_LIMITED", message: "서버 문구" })).toBe("서버 문구");
    for (const c of ["BG_W_PARTIAL", "RG_RANGE_LIMITED", "RG_COMBO_LIMITED", "RG_COMBO_SKIPPED", "RG_UNCHECKED", "RG_BUDGET", "MESH_ROUTE_RELAXED"]) expect(isInfoWarn({ code: c })).toBe(true);
    for (const c of ["RG_VAR_BLOCKED", "RG_FAILED", "RG_OUTSIDE_GUARD", "MESH_QUALITY_RANK"]) expect(isInfoWarn({ code: c })).toBe(false);
  });

  it("셀 경고 RG_OUTSIDE_GUARD 문구", () => {
    expect(cellWarnText({ code: "RG_OUTSIDE_GUARD", vars: [{ name: "B1_D", value: 7.123, usable: [4.2, 6.5] }] })).toBe("B1_D 7.12 (안전 4.2~6.5)");
    expect(warnText({ code: "RG_OUTSIDE_GUARD", vars: [{ name: "B1_D", value: 7.123, usable: [4.2, 6.5] }] })).toBe("점검된 안전 범위 밖 값: B1_D 7.1(4.2~6.5)");
  });
});

describe("① 그래프 select 새 스냅샷(doe-30) — W 부분·guard", () => {
  it("변수 표 꼬리표(부분·축소·조합 축소·미점검·막힘) = 변수 행 guard·w_segs 와 일치, 비드 칩 D · W(부분 n/m)", async () => {
    const r = renderApp("/p/p-body/doe/doe-30", "power", demo);
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
    await waitFor(() => expect(document.querySelectorAll('[data-testid^="guard-"]').length).toBeGreaterThan(0), { timeout: 10000 });
    const rec = r.server.doe.recs.find((x) => x.out.id === "doe-30")!;
    expect(rec.out.inputs.shape_rules).toBeTruthy();
    const ps = r.server.doe.paramsOf(rec);
    // 서버 변수 행 guard → 화면 꼬리표 1:1
    for (const p of ps) {
      const tag = screen.queryByTestId(`guard-${p.name}`);
      const want = guardTag(p.guard, rec.out.inputs.shape_rules);
      if (!want) expect(tag, p.name).toBeNull();
      else {
        expect(tag?.textContent, p.name).toBe(want.label);
        expect(tag?.getAttribute("title")).toBe(want.tip);
        expect(tag?.getAttribute("data-state")).toBe(p.guard!.state);
      }
    }
    const states = new Set(ps.map((p) => p.guard?.state));
    expect([...states].sort()).toEqual(["blocked", "limited", "ok", "unchecked"]);
    expect(ps.some((p) => (p.guard?.combo_scale ?? 1) < 1)).toBe(true);
    // 막힘 변수 = 기본 체크 해제
    const blocked = ps.find((p) => p.guard?.state === "blocked")!;
    expect((screen.getByLabelText(new RegExp(`${blocked.bead.toUpperCase()} W 포함`)) as HTMLInputElement).checked).toBe(false);
    // 변수 표 W 부분 꼬리표 = 길이 비율·앵커 툴팁(w_segs 가 있는 W 행만)
    const wp = ps.filter((p) => p.w_segs?.length);
    expect(wp.length).toBeGreaterThan(0);
    for (const p of wp) {
      const t = screen.getByTestId(`wpart-${p.name}`);
      expect(t.textContent).toBe("부분");
      expect(t.getAttribute("title")).toBe(wPartialTip(p.w_segs, p.w_cover));
    }
    expect(document.querySelectorAll('[data-testid^="wpart-"]').length).toBe(wp.length);
    // 비드 칩: 부분 비드만 — 툴팁 = 폭 정보 없는 구간 앵커
    const bead = rec.sel!.derived.beads.find((b) => b.w_segs)!;
    const chip = screen.getByTestId(`bead-wpart-${bead.id}`);
    const graphBead = rec.sel!.derived.graph!.beads.find((b) => b.id === bead.id)!;
    expect(chip.textContent).toBe(`D · W(부분 ${bead.w_segs!.length}/${graphBead.segs.length})`);
    expect(chip.getAttribute("title")).toBe(noWTip(graphBead.segs.filter((a) => !bead.w_segs!.includes(a))));
    expect(document.querySelectorAll('[data-testid^="bead-wpart-"]').length).toBe(rec.sel!.derived.beads.filter((b) => b.w_segs).length);
  }, 30000);

  it("트리: 폭 정보 없는 구간은 `W —`(툴팁 같은 문구), 폭이 있는 구간·플래토는 그대로", async () => {
    const r = renderApp("/p/p-body/doe/doe-30", "power", demo);
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
    fireEvent.click(screen.getByTestId("bs-view-tree"));
    const tree = await screen.findByTestId("sg-tree");
    const rec = r.server.doe.recs.find((x) => x.out.id === "doe-30")!;
    void rec;
    const nows = [...tree.querySelectorAll('[data-testid^="sg-now-"]')];
    expect(nows.length).toBe(2);
    for (const n of nows) {
      expect(n.textContent).toMatch(/W —/);
      expect(n.getAttribute("title")).toMatch(/^폭 정보 없는 구간\(입구 선 한쪽\): #\d+ — 그 구간은 깊이만 바뀝니다$/);
    }
    // 폭이 있는 구간은 값 그대로, 플래토(entry_width 없음)는 `W —` 없음
    const seg1 = within(tree).getByTestId("sg-seg-5");
    expect(seg1.textContent).toMatch(/W 35\.0/);
    expect(seg1.textContent).not.toMatch(/W —/);
    expect(tree.querySelector('[data-testid="sg-seg-11"]')?.textContent).not.toMatch(/W —/);
  }, 30000);
});

describe("④ 새 스냅샷(doe-31) — 완화 직행 칩·메시 품질 ⚠·품질 통과 최상위", () => {
  it("형상 행: 큰 모델·중간 모델 = 완화 직행 칩(면 수·기준은 route 필드), 작은 모델 = 칩 없음", async () => {
    const r = renderApp("/p/p-body/doe/doe-31", "power", demo);
    await waitFor(() => expect(screen.getByTestId("prep-shape-d001")).toBeTruthy(), { timeout: 15000 });
    const prep = r.server.doe.recs.find((x) => x.out.id === "doe-31")!.out.prep!;
    for (const row of prep.shapes!) {
      const chip = screen.queryByTestId(`prep-route-${row.id}`);
      const want = routeChip(row.route);
      if (!want) expect(chip, row.id).toBeNull();
      else {
        expect(chip?.textContent).toBe("완화 직행");
        expect(chip?.getAttribute("title")).toBe(want.tip);
      }
    }
    expect(screen.getByTestId("prep-route-d001").getAttribute("title")).toMatch(/STEP 면 2,800 ≥ 1,500/);
    expect(screen.getByTestId("prep-route-d003")).toBeTruthy();
    expect(screen.queryByTestId("prep-route-d002")).toBeNull();
    expect(screen.queryByTestId("prep-route-d000")).toBeNull();
    // 준비 정보 MESH_ROUTE_RELAXED 는 정보(ⓘ)로 접힌 목록에
    const fold = screen.getByTestId("prep-warn");
    expect(fold.textContent).toMatch(/정보 \d+건/);
  }, 30000);

  it("순위: 순위·행 그대로 + 품질 미달 형상만 ⚠(툴팁 = 수치·기준) + '품질 통과 최상위' 1줄, 결과 경고에 MESH_QUALITY_RANK", async () => {
    const r = renderApp("/p/p-body/doe/doe-31", "power", demo);
    const table = await screen.findByRole("table", { name: "순위표" }, { timeout: 15000 });
    const res = r.server.doe.recs.find((x) => x.out.id === "doe-31")!.result!;
    // 서버 순위 그대로(재정렬 없음): 1위 = 메시 품질 미달 형상
    expect(res.ranking[0].id).toBe("d001");
    const ids = [...table.querySelectorAll('tbody tr[data-testid^="rank-d"]')].map((x) => x.getAttribute("data-testid"));
    expect(ids).toEqual(res.ranking.map((x) => `rank-${x.id}`));
    const flagged = res.ranking.filter((x) => x.mq);
    expect(flagged.map((x) => x.id)).toEqual(["d001"]);
    for (const x of res.ranking) {
      const w = screen.queryByTestId(`rank-warn-${x.id}`);
      if (!x.mq) expect(w, x.id).toBeNull();
      else expect(w?.getAttribute("title")).toBe(mqTip(x.mq, r.server.doe.recs.find((y) => y.out.id === "doe-31")!.out.inputs.shape_rules));
    }
    expect(screen.getByTestId("rank-warn-d001").getAttribute("title")).toMatch(/Fail 55\.5 % > 10 % · tria 21\.9 % > 15 %/);
    // 품질 통과 최상위 1줄 = summary.best_clean_mq
    const line = screen.getByTestId("best-clean-mq");
    expect(res.summary?.best_clean_mq).toBe("d002");
    expect(line.getAttribute("title")).toMatch(/메시 품질 미달 형상 1개\(순위는 그대로\) — 품질 통과 최상위: d002 리브 A안/);
    expect(line.textContent).toMatch(/품질 미달 1개 · 통과 최상위 d002/);
    // 기존 SR-D-11 줄은 품질 경고만이면 안 나옴
    expect(screen.queryByTestId("best-clean")).toBeNull();
    // 결과 경고 목록: 형상 이름·수치(v0.23.1 결과 경고 접기 — 한 번 펼침)
    fireEvent.click(within(screen.getByTestId("result-warn")).getAllByRole("button")[0]);
    expect(document.body.textContent).toMatch(/메시 품질 미달 형상 1개\(F안\(큰 모델\) Fail 55\.5 % · tria 21\.9 %\)/);
    // ③ 띠는 ④ 에서는 없음
    expect(screen.queryByTestId("mq-base-strip")).toBeNull();
  }, 30000);

  it("품질 통과 형상이 없으면 '없음'(summary.best_clean_mq null)", async () => {
    const r = renderApp("/p/p-body/doe/doe-31", "power", (s) => {
      demo(s);
      const rec = s.doe.recs.find((x) => x.out.id === "doe-31")!;
      rec.result = { ...rec.result!, ranking: rec.result!.ranking.map((x) => ({ ...x, mq: { fail_ratio: 0.2, tria_pct: 3, over: ["fail"] as ("fail" | "tria")[] }, warn: ["MESH_QUALITY_RANK" as const] })), summary: { best_clean_mq: null } };
    });
    await screen.findByRole("table", { name: "순위표" }, { timeout: 15000 });
    expect(screen.getByTestId("best-clean-mq").getAttribute("title")).toMatch(/품질 통과 최상위: 없음/);
    void r;
  }, 30000);
});

describe("③ 새 스냅샷(doe-32) — 기준 메시 품질 미달 결과 띠 1줄", () => {
  it("모든 안이 같은 메시 = 결과 띠 1줄(행 ⚠ 없음·품질 통과 최상위 줄 없음), 준비 요약에 완화 직행", async () => {
    const r = renderApp("/p/p-body/doe/doe-32", "power", demo);
    const strip = await screen.findByTestId("mq-base-strip", undefined, { timeout: 20000 });
    const q = r.server.doe.recs.find((x) => x.out.id === "doe-32")!.out.prep!.mesh!.quality!;
    expect(strip.getAttribute("title")).toBe(`⚠ 기준 메시 품질 미달(${mqText(q)}) — 모든 안이 같은 메시라 순위 신뢰도가 낮습니다(순위는 유지)`);
    expect(document.querySelectorAll('[data-testid="mq-base-strip"]').length).toBe(1);
    expect(screen.queryByTestId("best-clean-mq")).toBeNull();
    expect(document.querySelectorAll('[data-testid^="rank-warn-"][title*="메시 품질"]').length).toBe(0);
    expect(document.body.textContent).toMatch(/메시 CAD\(완화 직행\)/);
    // 같은 경고가 결과 경고 목록에 또 나오지 않음
    expect(document.body.textContent!.split("기준 메시 품질 미달").length - 1).toBe(1);
  }, 40000);
});

describe("옛 스냅샷·옛 결과 = 기존 화면 그대로(새 키 없음)", () => {
  it("doe-10(① 그래프 옛): 부분 칩·꼬리표·W — 없음", async () => {
    const r = renderApp("/p/p-body/doe/doe-10", "power", demo);
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
    expect(r.server.doe.recs.find((x) => x.out.id === "doe-10")!.out.inputs.shape_rules).toBeUndefined();
    fireEvent.click(screen.getByTestId("bs-view-tree"));
    const tree = await screen.findByTestId("sg-tree");
    expect(tree.querySelectorAll('[data-testid^="sg-now-"]').length).toBe(0);
    expect(document.querySelectorAll('[data-testid^="bead-wpart-"],[data-testid^="wpart-"],[data-testid^="guard-"]').length).toBe(0);
    expect(tree.textContent).not.toMatch(/W —/);
  }, 30000);

  it("doe-20(④ 옛 결과): 완화 직행 칩·메시 품질 ⚠·품질 통과 최상위 줄·③ 띠 없음", async () => {
    renderApp("/p/p-body/doe/doe-20", "power", demo);
    await screen.findByRole("table", { name: "순위표" }, { timeout: 15000 });
    expect(document.querySelectorAll('[data-testid^="prep-route-"],[data-testid="best-clean-mq"],[data-testid="mq-base-strip"]').length).toBe(0);
    expect(document.querySelectorAll('[data-testid^="rank-warn-"]').length).toBe(0);
  }, 30000);
});
