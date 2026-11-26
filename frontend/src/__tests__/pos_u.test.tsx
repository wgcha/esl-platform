// V-0249-PU-18 (esl_bead_pos_u.md §1.3·§2.3·§4·§5-18): 위치 U 화면 — 변수 표 U 행(체크 해제·dir_text·부호별 usable·사유 툴팁·U 있을 때만 표 안 스크롤),
// 결과 경고 줄(LOAD_FOLLOW_SPATIAL 정보 등급)·순위 정의 꼬리·민감도 U 행. 응답 새 필드는 백엔드 B1 병행 — 시험은 목 응답으로 한다.
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { POS_U_INFO_CODES, POS_U_TEXT, guardTag, isInfoWarn, loadFollowTail, rowProblem, warnText } from "../api/doe";
import { foldCounts } from "../components/MsgFold";
import { MOCK_SHAPE_RULES } from "../mock/doedata";
import { renderApp } from "../test/render";
import type { DoeParam } from "../api/types";

afterEach(() => cleanup());
const demo = (s: { doe: { demoPosU: () => void } }) => s.doe.demoPosU();
const U = (p: Partial<DoeParam> = {}) => ({ type: "U" as const, ...p });

describe("규칙 함수", () => {
  it("U 행 오류: 범위가 0 을 포함해야(비대칭 OK), D·W 는 그대로", () => {
    const r = (lo: string, hi: string) => ({ name: "B1_U", on: true, lo, hi });
    expect(rowProblem(U(), r("-3", "5"))).toBeNull();
    expect(rowProblem(U(), r("0", "5"))).toBeNull();
    expect(rowProblem(U(), r("1", "5"))).toBe(POS_U_TEXT.rangeRule);
    expect(rowProblem(U(), r("-5", "-1"))).toBe("위치 범위는 0 을 포함해야 합니다");
    expect(rowProblem({ type: "W" }, r("0", "5"))).toBe("깊이·폭 하한은 0보다 커야 합니다");
    expect(rowProblem(U(), { name: "x", on: false, lo: "9", hi: "9" })).toBeNull();
  });
  it("정보 등급 코드: level 이 없어도 ⓘ — 경고 개수에 안 셈", () => {
    for (const c of POS_U_INFO_CODES) expect(isInfoWarn({ code: c }), c).toBe(true);
    expect(isInfoWarn({ code: "LOAD_FOLLOW_SPATIAL" })).toBe(true);
    expect(isInfoWarn({ code: "JIG_GRID_ON_CLONE" })).toBe(true);
    expect(isInfoWarn({ code: "JIG_GRID_MESH_MISMATCH" })).toBe(true);
    expect(isInfoWarn({ code: "RG_OUTSIDE_GUARD" })).toBe(false);
  });
  it("경고 문구: 서버 message 우선, 없으면 표 문구 + {cell_mm} 채움", () => {
    expect(warnText({ code: "LOAD_FOLLOW_SPATIAL", message: "서버 문구", cell_mm: 3 })).toBe("서버 문구");
    expect(warnText({ code: "LOAD_FOLLOW_SPATIAL", cell_mm: 5 })).toBe("위치 변수가 있어 하중을 공간에 고정했습니다(5 mm 셀) — 기준 포함 모든 안이 같은 경로");
  });
  it("순위 정의 꼬리: spatial 일 때만 \" · 하중 공간 고정(N mm)\"", () => {
    expect(loadFollowTail({ load_follow: { mode: "spatial", cell_mm: 3 } })).toBe(" · 하중 공간 고정(3 mm)");
    expect(loadFollowTail({ load_follow: { mode: "node", cell_mm: 3 } })).toBe("");
    expect(loadFollowTail({})).toBe("");
    expect(loadFollowTail(null)).toBe("");
  });
  it("guardTag: U 만 부호별 usable 줄을 더함, D·W 툴팁 불변", () => {
    const g = { state: "limited" as const, from: [-6, 6] as [number, number], usable: [-2.4, 6] as [number, number], reason: "inverted", value: null, combo_scale: null };
    const u = guardTag(g, MOCK_SHAPE_RULES, "U")!;
    expect(u.tip).toContain("부호별 사용 가능 범위: (−) 2.4 mm · (+) 6 mm");
    expect(guardTag(g, MOCK_SHAPE_RULES, "W")!.tip).not.toContain("부호별");
    expect(guardTag(g, MOCK_SHAPE_RULES)!.tip).toBe(guardTag(g, MOCK_SHAPE_RULES, "D")!.tip);
  });
});

describe("① 변수 표(doe-70 = pos_u 새 스냅샷, doe-30 = 대조)", () => {
  it("U 행: 체크 해제 기본·라벨 위치(U)+dir_text·범위 mm·부호별 usable 꼬리표, 비드 안 순서 D·W·U", async () => {
    const r = renderApp("/p/p-body/doe/doe-70", "power", demo);
    await waitFor(() => expect(document.querySelectorAll('[data-testid^="param-"][data-testid$="_U"]').length).toBeGreaterThan(0), { timeout: 15000 });
    const rec = r.server.doe.recs.find((x) => x.out.id === "doe-70")!;
    const ps = r.server.doe.paramsOf(rec);
    const us = ps.filter((p) => p.type === "U");
    expect(us.length).toBeGreaterThan(0);
    for (const p of us) {
      const row = screen.getByTestId(`param-${p.name}`);
      const cb = row.querySelector("input[type=checkbox]") as HTMLInputElement;
      expect(cb.checked, p.name).toBe(false);
      expect(cb.getAttribute("aria-label")).toBe(`${p.bead.toUpperCase()} 위치 U 포함`);
      expect(row.textContent).toContain("위치(U)");
      expect(screen.getByTestId(`udir-${p.name}`).textContent?.trim()).toBe(p.dir_text);
      expect(row.textContent).toContain(`${p.feasible[0]}–${p.feasible[1]}`);
      expect(row.textContent).toContain(p.name);
      expect(row.textContent).toContain("0"); // 공칭
      // 체크하면 하한·상한 입력이 열리고 기본 범위가 채워짐(0 포함)
      fireEvent.click(cb);
      const lo = row.querySelector(`input[aria-label$="하한"]`) as HTMLInputElement;
      const hi = row.querySelector(`input[aria-label$="상한"]`) as HTMLInputElement;
      await waitFor(() => expect(lo.disabled).toBe(false));
      expect(Number(lo.value)).toBeLessThanOrEqual(0);
      expect(Number(hi.value)).toBeGreaterThanOrEqual(0);
    }
    // 같은 비드 안 순서: D → W → U
    for (const p of us) {
      const rows = Array.from(document.querySelectorAll('tr[data-testid^="param-"]')).map((x) => x.getAttribute("data-testid")!.slice(6));
      const mine = rows.filter((n) => n.startsWith(`${p.bead.toUpperCase()}_`));
      const order = mine.map((n) => n.split("_")[1][0]);
      expect(order.indexOf("U")).toBe(order.length - 1);
      if (order.includes("W")) expect(order.indexOf("W")).toBeLessThan(order.indexOf("U"));
    }
    // 표 안 스크롤 = U 행이 있을 때만
    expect(document.querySelector("table.doe-params")!.closest(".table-wrap")!.classList.contains("scroll")).toBe(true);
  }, 40000);

  it("U 불가 비드: 이름에 title = u_reason.text(서버 문구), 없는 비드는 title·testid 없음", async () => {
    const r = renderApp("/p/p-body/doe/doe-70", "power", demo);
    await waitFor(() => expect(document.querySelectorAll("tr.doe-bead-row").length).toBeGreaterThan(0), { timeout: 15000 });
    const rec = r.server.doe.recs.find((x) => x.out.id === "doe-70")!;
    const derive = r.server.doe.paramsOf(rec);
    expect(derive.length).toBeGreaterThan(0);
    await waitFor(() => expect(document.querySelectorAll('[data-testid^="u-reason-"]').length).toBeGreaterThan(0), { timeout: 15000 });
    for (const el of Array.from(document.querySelectorAll('[data-testid^="u-reason-"]'))) {
      expect(el.getAttribute("title")).toBe("한쪽 입구 비드 — 위치 대신 한쪽 W 를 쓰세요");
      expect(el.getAttribute("data-code")).toBe("U_ONE_SIDE");
    }
    // 사유가 없는 비드 이름 span 에는 title 이 없다(새 줄도 없음)
    const heads = Array.from(document.querySelectorAll("tr.doe-bead-row .doe-bead-head > span:not(.small):not(.badge)")).filter((x) => !x.hasAttribute("data-testid"));
    for (const h of heads) expect(h.hasAttribute("title")).toBe(false);
  }, 40000);

  it("대조(doe-30, 옛 스냅샷): U 행·사유·scroll 클래스 없음 — DOM 불변", async () => {
    renderApp("/p/p-body/doe/doe-30", "power", demo);
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 15000 });
    await waitFor(() => expect(document.querySelectorAll('tr[data-testid^="param-"]').length).toBeGreaterThan(0), { timeout: 15000 });
    expect(document.querySelectorAll('[data-testid^="param-"][data-testid$="_U"]').length).toBe(0);
    expect(document.querySelectorAll('[data-testid^="u-reason-"]').length).toBe(0);
    expect(document.querySelector("table.doe-params")!.closest(".table-wrap")!.className).toBe("table-wrap");
  }, 40000);
});

describe("스터디 결과(doe-71 = spatial)", () => {
  it("경고 줄: LOAD_FOLLOW_SPATIAL 은 정보로 구분(경고 n건에 안 셈), 순위 정의 꼬리, 민감도 U 행", async () => {
    const r = renderApp("/p/p-body/doe/doe-71", "power", demo);
    await screen.findByTestId("doe-result-rows", {}, { timeout: 15000 });
    const rec = r.server.doe.recs.find((x) => x.out.id === "doe-71")!;
    const res = rec.result!;
    const fold = await screen.findByTestId("result-warn");
    const items = res.warnings.filter((w) => w.code === "LOAD_FOLLOW_SPATIAL").map((w) => ({ text: warnText(w), info: isInfoWarn(w) }));
    expect(foldCounts(items)).toEqual({ warn: 0, info: 1 });
    // 화면: 이 결과의 다른 경고는 없으므로 "경고 0건 · 정보 1건"(ⓘ) — 예전엔 ⚠ 경고 1건으로 셌음
    expect(screen.getByTestId("result-warn-count").textContent).toBe("ⓘ 경고 0건 · 정보 1건");
    // 목록을 열면 ⓘ 로 나옴
    const btn = fold.querySelector("button.msg-fold-line") as HTMLButtonElement;
    if (btn.getAttribute("aria-expanded") !== "true") fireEvent.click(btn);
    await waitFor(() => expect(fold.textContent).toContain("ⓘ 위치 변수가 있어 하중을 공간에 고정했습니다(3 mm 셀)"));
    // 순위 정의 문구 꼬리
    await waitFor(() => expect(screen.getByTestId("metric-defs").textContent).toContain(" · 하중 공간 고정(3 mm)"), { timeout: 8000 });
    // 민감도 표에 U 행(이름 "B8 U")
    const row = await screen.findByTestId("sens-B8_U", {}, { timeout: 8000 });
    expect(row.textContent).toContain("B8 U");
  }, 60000);

  it("옛 결과(doe-40, load_follow 없음): 꼬리·U 행 없음", async () => {
    renderApp("/p/p-body/doe/doe-40", "power", demo);
    await screen.findByTestId("doe-result-rows", {}, { timeout: 15000 });
    await waitFor(() => expect(screen.getByTestId("metric-defs")).toBeTruthy());
    expect(screen.getByTestId("metric-defs").textContent).not.toContain("하중 공간 고정");
    expect(screen.queryByTestId("sens-B8_U")).toBeNull();
  }, 40000);
});
