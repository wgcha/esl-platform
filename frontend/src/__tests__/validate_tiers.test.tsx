// V-0245-VT-13: ④ 검증 판정 단계화(PASS·조건부 PASS·FAIL)·MAC 화면(계약 esl_validate_tiers.md §4.5). 목 서버 + 실제 백엔드 응답 픽스처.
import GATE_SRC_LIBCOMMON from "../pages/library/common.tsx?raw";
import GATE_SRC_REGISTER from "../components/LibraryRegister.tsx?raw";
import GATE_SRC_RUNALL from "../shell/RunAllBar.tsx?raw";
import GATE_SRC_CASELIST from "../pages/CaseList.tsx?raw";
import GATE_SRC_MOCK from "../mock/server.ts?raw";
import GATE_SRC_ANALYSIS from "../pages/library/AnalysisNew.tsx?raw";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../app/App";
import real from "./fixtures/real_v0245.json";
import { COND_REASON_LABEL, FAIL_REASON_LABEL, condReasonText } from "../stages/Stage5";
import { REG_NOT_PASS, registerBlock } from "../components/LibraryRegister";
import { PASSING, STATUS_LABEL, StatusBadge, entryStatus, isPassing, statusOf } from "../components/VerdictStatus";
import { makeValidation, variantValidation } from "../mock/data";
import { MockServer, createMockFetch } from "../mock/server";
import { valSourceRows, valSourceOut } from "../mock/valsrcmock";
import { checkEntryMark, gradeMark, loadSourceChipOf } from "../view3d/loadSource";
import { isTierScheme, markOf, reactionTolText, valRowOf, valTabItems } from "../view3d/sources";
import { DEFAULT_FORM, toFilters } from "../pages/library/AnalysisNew";
import type { ValidationOut, ValidationSourcesOut } from "../api/types";

const STAGE5 = "/p/p-body/c/c-demo/step/4";
type Kind = Parameters<typeof variantValidation>[1];

function renderWith(kind: Kind | null, setup?: (s: MockServer) => void) {
  const server = new MockServer({ user: "power" });
  if (kind) server.validations[0] = variantValidation(server.validations[0], kind);
  setup?.(server);
  globalThis.fetch = createMockFetch(server);
  const view = render(
    <MemoryRouter initialEntries={[STAGE5]}>
      <App />
    </MemoryRouter>,
  );
  return { server, ...view };
}
const judge = () => screen.findByTestId("judge-stats");
const statOf = (j: HTMLElement, label: string) => within(j).getByText(label).closest(".stat") as HTMLElement;

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* 무시 */
  }
});

describe("V-0245-VT-13 순수: 상태·표식·통과 판정", () => {
  it("라벨·배지·statusOf·isPassing(한 곳)", () => {
    expect(STATUS_LABEL.CONDITIONAL).toBe("조건부 PASS");
    expect([...PASSING]).toEqual(["PASS", "CONDITIONAL"]);
    expect(["PASS", "CONDITIONAL"].map(isPassing)).toEqual([true, true]);
    expect(["FAIL", "UNDETERMINED", "LEGACY", null, undefined].map((x) => isPassing(x))).toEqual([false, false, false, false, false]);
    expect(statusOf({ scheme: "disp_primary/2", verdict: "CONDITIONAL" })).toBe("CONDITIONAL");
    expect(statusOf({ status: "CONDITIONAL" })).toBe("CONDITIONAL");
    expect(entryStatus({ scheme: "disp_primary/2", verdict: "CONDITIONAL" })).toBe("CONDITIONAL");
    expect(entryStatus({ verdict: "CONDITIONAL" })).toBe("LEGACY");
    const { container } = render(<StatusBadge v={{ status: "CONDITIONAL" }} />);
    expect(container.querySelector(".badge.warn")?.textContent).toBe("조건부 PASS");
  });

  it("탭 mark·gradeMark·결과 칩에 조건부 PASS(경고색)", () => {
    expect(markOf({ available: true, status: "CONDITIONAL", limits: [], comparable: true })).toEqual({ text: "조건부 PASS", tone: "warn" });
    expect(markOf({ available: true, status: "CONDITIONAL", limits: ["X"], comparable: true })).toEqual({ text: "조건부 PASS ⚠", tone: "warn" });
    expect(markOf({ available: true, status: "CONDITIONAL", limits: [], comparable: false })).toEqual({ text: "조건부 PASS · 비교용 아님", tone: "warn" });
    expect(markOf({ available: true, status: "PASS", limits: [], comparable: true })).toEqual({ text: "PASS", tone: "ok" });   // 옛 표식 불변
    expect(gradeMark("CONDITIONAL")).toEqual({ text: "조건부 PASS", tone: "warn" });
    expect(gradeMark("PASS")).toEqual({ text: "PASS", tone: "ok" });
    expect(checkEntryMark({ status: "CONDITIONAL", comparable: true })).toEqual({ text: "조건부 PASS", tone: "warn" });
    const chip = loadSourceChipOf("full", { key: "full", worst: "CONDITIONAL", entries: [{ entry_id: "a", status: "CONDITIONAL", comparable: true, validation_id: "v" }, { entry_id: "b", status: "PASS", comparable: true, validation_id: "v2" }] });
    expect(chip?.short).toContain("조건부 PASS");
    expect(chip?.tone).toBe("warn");
  });

  it("reactionTolText: 새 체계 행은 2단 문구, 옛 행은 그대로", () => {
    const row = { reaction_role: "judge" as const, reaction_tol: 0.1, reaction_tol_key: "k", reaction_warn: 0.05 };
    expect(reactionTolText({ ...row, scheme: "disp_primary/2" })).toBe("반력 PASS ≤ 5 % · 조건부 ≤ 10 %");
    expect(reactionTolText(row)).toBe("반력 허용치 ≤ 10 % · 주의 > 5 %");
    expect(reactionTolText({ ...row, scheme: "disp_primary/1" })).toBe("반력 허용치 ≤ 10 % · 주의 > 5 %");
    expect(isTierScheme("disp_primary/2") && !isTierScheme("disp_primary/1") && !isTierScheme(null)).toBe(true);
  });

  it("등록 게이트: 조건부 PASS 는 등록 가능(registerBlock null), FAIL 은 불가", () => {
    const base = makeValidation("v", "r", "c");
    expect(registerBlock(variantValidation(base, "TIER_COND"))).toBeNull();
    expect(registerBlock(variantValidation(base, "TIER_PASS"))).toBeNull();
    expect(registerBlock(variantValidation(base, "TIER_FAIL"))).toBe(REG_NOT_PASS);
    expect(REG_NOT_PASS).toContain("조건부 PASS");
  });

  it("사유 문구표: MAC 사유·조건부 사유 3종", () => {
    expect(FAIL_REASON_LABEL.MAC).toBe("변형 형상 일치(MAC)가 기준 미만");
    expect(Object.keys(COND_REASON_LABEL)).toEqual(["DISP_RMS", "MAC", "REACTION"]);
    const v = { reaction_rel: 0.072, criteria: { reaction_warn_rel: 0.05 } } as unknown as ValidationOut;
    expect(condReasonText("REACTION", v)).toBe("반력 7.2 % — 5 % 초과, 받침점 주변 국부 변형 확인");
    expect(condReasonText("MAC", v)).toBe(COND_REASON_LABEL.MAC);
  });

  it("분석 새로 만들기: 기본 필터 PASS·조건부 PASS, PASS만 선택 유지", () => {
    expect(DEFAULT_FORM.verdict).toBe("PASS_COND");
    expect(toFilters(DEFAULT_FORM).verdict).toEqual(["PASS", "CONDITIONAL"]);
    expect(toFilters({ ...DEFAULT_FORM, verdict: "PASS" }).verdict).toEqual(["PASS"]);
    expect(toFilters({ ...DEFAULT_FORM, verdict: "" }).verdict).toBeUndefined();
  });

  it("정적: 게이트 파일에 verdict·status 와 \"PASS\" 직접 비교 없음(isPassing 만)", () => {
    const re = /(verdict|status|vs|st|s)\s*(===|!==)\s*"PASS"/;
    const pick = (src: string) => src.split("\n").filter((l) => re.test(l) && !/^\s*\/\//.test(l));
    expect(pick(GATE_SRC_REGISTER)).toEqual([]);
    expect(pick(GATE_SRC_RUNALL)).toEqual([]);
    expect(pick(GATE_SRC_LIBCOMMON)).toEqual([]);
    expect(pick(GATE_SRC_ANALYSIS)).toEqual([]);
    // CaseList: 배지 tone(PASS = ok, 그 밖 = warn)은 표식이지 게이트가 아니다
    expect(GATE_SRC_MOCK).toContain("isPassing(");
    expect(GATE_SRC_CASELIST).toContain("조건부 PASS");
  });
});

describe("V-0245-VT-13 ④ 판정 카드(목 서버)", () => {
  it("옛 결과(disp_primary/1): MAC 칸은 같은 줄 5번째에 \"–\" + 툴팁, 기존 4칸·문구 불변, 조건부 사유 목록 없음", async () => {
    renderWith(null);
    const j = await judge();
    expect(j.querySelectorAll(".stat").length).toBe(5);
    expect([...j.querySelectorAll(".stat-label")].map((e) => e.textContent)).toEqual(["변위 RMS (상대)", "변위 최대 오차 (상대)", "MAC(검증)", "반력 (상대)", "변위 잡음 바닥"]);
    const mac = statOf(j, "MAC(검증)");
    expect(mac.querySelector(".stat-value")?.textContent).toBe("–");
    expect(mac.getAttribute("title")).toContain("v0.24.5 이전 검증 — 단일 기준·MAC 없음");
    expect(mac.className).toBe("stat");                                           // 색 없음
    expect(within(j).getByText("기준 ≤ 5.00e-2")).toBeTruthy();                    // 옛 기준 문구 그대로
    expect(screen.queryByTestId("cond-reasons")).toBeNull();
  });

  it("새 체계 PASS: MAC 값·2단 기준 문구·ok 색", async () => {
    renderWith("TIER_PASS");
    const j = await judge();
    const mac = statOf(j, "MAC(검증)");
    expect(mac.querySelector(".stat-value")?.textContent).toBe("0.9931");
    expect(mac.querySelector(".stat-sub")?.textContent).toBe("PASS ≥ 0.95 · 조건부 ≥ 0.9");
    expect(mac.className).toContain("ok");
    const rms = statOf(j, "변위 RMS (상대)");
    expect(rms.querySelector(".stat-sub")?.textContent).toBe("PASS ≤ 0.05 · 조건부 ≤ 0.1");
    expect(rms.className).toContain("ok");
    expect(statOf(j, "변위 최대 오차 (상대)").querySelector(".stat-sub")?.textContent).toBe("기준 ≤ 0.05");      // 단일 기준
    expect(screen.queryByTestId("cond-reasons")).toBeNull();
  });

  it("새 체계 조건부 PASS: 사유 코드로 warn 색·사유 목록·배지·등록 가능", async () => {
    renderWith("TIER_COND");
    const j = await judge();
    expect(statOf(j, "변위 RMS (상대)").className).toContain("warn");
    expect(statOf(j, "MAC(검증)").className).toContain("warn");
    expect(statOf(j, "변위 최대 오차 (상대)").className).toContain("ok");
    const list = screen.getByTestId("cond-reasons");
    expect(within(list).getAllByRole("listitem").map((l) => l.textContent)).toEqual([`DISP_RMS — ${COND_REASON_LABEL.DISP_RMS}`, `MAC — ${COND_REASON_LABEL.MAC}`]);
    expect(list.querySelector("li")?.className).toContain("warn-text");
    expect(screen.getAllByText("조건부 PASS").length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole("button", { name: "라이브러리에 등록" })).toBeTruthy());
  });

  it("새 체계 FAIL: MAC 도 사유 코드로 bad, 사유 라벨", async () => {
    renderWith("TIER_FAIL");
    const j = await judge();
    expect(statOf(j, "MAC(검증)").className).toContain("bad");
    expect(statOf(j, "변위 RMS (상대)").className).toContain("bad");
    expect(screen.getByText(`MAC — ${FAIL_REASON_LABEL.MAC}`)).toBeTruthy();
    expect(screen.queryByTestId("cond-reasons")).toBeNull();
  });

  it("출처 탭: fint 조건부 PASS(반력 REACTION) — 탭 표식·2단 반력 문구·사유 목록, 옛 \"반력 주의\" 줄 없음", async () => {
    renderWith("TIER_COND", (s) => (s.valSourcesMode = "ok"));
    const tab = (await screen.findByTestId("val-src-tab")).querySelector("[data-tab=fint]") as HTMLButtonElement;
    expect(tab.textContent).toContain("조건부 PASS");
    fireEvent.click(tab);
    await waitFor(() => expect(screen.getByTestId("cond-reasons").textContent).toContain("반력 7.2 % — 5 % 초과"));
    const j = await judge();
    const re = statOf(j, "반력 (상대)");
    expect(re.querySelector(".stat-sub")?.textContent).toBe("PASS ≤ 0.05 · 조건부 ≤ 0.1");
    expect(re.className).toContain("warn");
    expect(screen.queryByTestId("reaction-warn")).toBeNull();
  });
});

describe("V-0245-VT-13 실제 백엔드 응답 픽스처(real_v0245.json)", () => {
  const v = real.validation as unknown as ValidationOut;
  const src = real.sources as unknown as ValidationSourcesOut;

  it("검증 응답: status·mac·cond_reasons·새 criteria", () => {
    expect(statusOf(v)).toBe("CONDITIONAL");
    expect(v.mac).toBeCloseTo(0.9312);
    expect(v.cond_reasons).toEqual(["DISP_RMS", "MAC"]);
    expect(isTierScheme(v.scheme)).toBe(true);
    expect(v.criteria.mac_cond_min).toBe(0.9);
    expect(registerBlock({ ...v, stale: false })).toBeNull();
  });

  it("출처 행: 탭 표식 조건부 PASS·FAIL, 새 행 scheme·cond_reasons, 반력 2단 문구", () => {
    const items = valTabItems(src, true)!;
    const by = Object.fromEntries(items.map((i) => [i.key, i]));
    expect(by.full.mark).toEqual({ text: "조건부 PASS", tone: "warn" });
    expect(by.bforce.mark?.text).toBe("FAIL · 비교용 아님");
    expect(by.fint.mark).toEqual({ text: "조건부 PASS", tone: "warn" });
    const fint = valRowOf(src, "fint")!;
    expect(fint.scheme).toBe("disp_primary/2");
    expect(fint.cond_reasons).toEqual(["REACTION"]);
    expect(by.fint.title).toContain("반력 PASS ≤ 5 % · 조건부 ≤ 10 %");
    expect(valRowOf(src, "jig")?.scheme ?? null).toBeNull();
  });
});

describe("V-0245-VT-13 목 서버 일관성", () => {
  it("출처 행·출처 응답(valSourceOut)의 새 체계 값", () => {
    const base = variantValidation(makeValidation("v", "r", "c"), "TIER_COND");
    const rows = valSourceRows(base, "ok");
    expect(rows.find((r) => r.key === "fint")?.status).toBe("CONDITIONAL");
    expect(rows.find((r) => r.key === "full")?.cond_reasons).toEqual(["DISP_RMS", "MAC"]);
    expect(valSourceOut(base, "fint").verdict).toBe("CONDITIONAL");
    expect(valSourceOut(base, "bforce").fail_reasons).toContain("MAC");
    // 옛 결과는 옛 형태 그대로(scheme/cond_reasons 없음)
    const old = valSourceRows(makeValidation("v", "r", "c"), "ok");
    expect(old.find((r) => r.key === "fint")?.status).toBe("PASS");
    expect(old.find((r) => r.key === "fint")?.scheme).toBeUndefined();
  });
});
