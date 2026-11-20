// V-0243-VAL-17~20(프런트): ④ 검증 출처 탭·판정 표식·조건 툴팁·탭마다 같은 카드·결과 없는 탭·이력 (esl_validate_sources.md §8·§14.1).
import STAGE5_SRC from "../stages/Stage5.tsx?raw";
import TABS_SRC from "../view3d/SourceTabs.tsx?raw";
import SOURCES_SRC from "../view3d/sources.ts?raw";
import { readFileSync } from "node:fs";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../app/App";
import { makeValidation } from "../mock/data";
import { MockServer, createMockFetch } from "../mock/server";
import { valSourceRows } from "../mock/valsrcmock";
import { SourceTabs } from "../view3d/SourceTabs";
import { SOURCE_ROWS, caseTabItems, defaultValSource, markOf, tabItemsOf, unavailText, valTabItems } from "../view3d/sources";
import type { ValidationSourcesOut } from "../api/types";
import { REG_NOT_PASS } from "../components/LibraryRegister";

const STAGE5 = "/p/p-body/c/c-demo/step/4";

function renderWith(setup: (s: MockServer) => void, path = STAGE5) {
  const server = new MockServer({ user: "power" });
  setup(server);
  const calls: string[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b) => {
    calls.push(`${m} ${p}?${q.toString()}`);
    return orig(m, p, q, b);
  };
  globalThis.fetch = createMockFetch(server);
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { server, calls, ...view };
}
const ok = (s: MockServer) => (s.valSourcesMode = "ok");
const tab = (k: string) => screen.getByTestId("val-src-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const tabs = () => screen.findByTestId("val-src-tab");
const judge = () => screen.getByTestId("judge-stats");

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* 무시 */
  }
});

const SRC: ValidationSourcesOut = {
  validation_id: "v1",
  default: "full",
  rows: valSourceRows(makeValidation("v1", "r1", "c1"), "ok"),
};

describe("V-0243-VAL-17 탭 항목·표식·기본 탭 (순수)", () => {
  it("항목 = 표 순서·이름 + 응답의 가능 여부·사유(unavailText), caseTabItems 와 같은 규칙", () => {
    const items = valTabItems(SRC, true)!;
    // 응답 4행(v0.24.3 형식) = optional 열 행(jig_disp·jig_spring)은 그리지 않고 jig 는 단독 탭 "지그 ESL"
    const shown = SOURCE_ROWS.filter((r) => !r.optional);
    expect(items.map((i) => i.key)).toEqual(shown.map((r) => r.key));
    expect(items.map((i) => i.label)).toEqual(["지그 ESL", ...shown.slice(1).map((r) => r.label)]);
    expect(items.map((i) => i.ok)).toEqual([false, true, true, true]);
    expect(items[0].why).toBe(unavailText("지그 ESL", SRC.rows[0].reason));
    // tabItemsOf = caseTabItems 의 공통 규칙(ok·why 동일)
    const rows = SRC.rows.map((r) => ({ key: r.key, available: r.available, reason: r.reason }));
    expect(tabItemsOf(rows)).toEqual(caseTabItems({ esl_run_id: "r", default: "full", rows: rows.map((r) => ({ ...r, code: null, resp: true, resp_code: null, resp_reason: null, rigid: null })) }));
    expect(valTabItems(null, true)).toBeNull();
  });

  it("mark: 판정 + 한계(비교용 아님 = 경고, 한계 있음 = ⚠), 결과 없음 = 표식 없음; 조건·한계는 title", () => {
    const items = valTabItems(SRC, true)!;
    const by = Object.fromEntries(items.map((i) => [i.key, i]));
    expect(by.jig.mark).toBeUndefined();
    expect(by.full.mark).toEqual({ text: "PASS", tone: "ok" });
    expect(by.bforce.mark).toEqual({ text: "FAIL · 비교용 아님", tone: "warn" });
    expect(by.fint.mark).toEqual({ text: "PASS ⚠", tone: "ok" });
    expect(by.bforce.title).toContain(SRC.rows[2].cond_text!);
    expect(by.bforce.title).toContain("tie 체결력 미포함");
    expect(markOf({ available: true, status: "UNDETERMINED", limits: [], comparable: null })).toEqual({ text: "판정 불가", tone: "muted" });
    expect(markOf({ available: false, status: null, limits: [], comparable: null })).toBeNull();
    expect(markOf(null)).toBeNull();
  });

  it("기본 탭 = 응답 default(가능할 때) → 가능한 첫 탭 → null", () => {
    expect(defaultValSource(SRC)).toBe("full");
    expect(defaultValSource({ ...SRC, default: "bforce" })).toBe("bforce");
    expect(defaultValSource({ ...SRC, default: "jig" })).toBe("full");
    expect(defaultValSource({ ...SRC, rows: SRC.rows.map((r) => ({ ...r, available: false })) })).toBeNull();
    expect(defaultValSource(null)).toBeNull();
  });

  it("결과 없음(VAL_SRC_NOT_RUN) 탭 = canRun 일 때만 add(선택 가능)", () => {
    const nr: ValidationSourcesOut = { ...SRC, rows: valSourceRows(makeValidation("v1", "r1", "c1"), "notrun") };
    const run = valTabItems(nr, true)!;
    expect(run.map((i) => !!i.add)).toEqual([false, false, true, true]); // jig(V3D_STUDY_ONLY) 은 add 아님
    expect(valTabItems(nr, false)!.some((i) => i.add)).toBe(false);
  });

  it("출처 이름 문자열 비교 없음(소스 grep): Stage5·SourceTabs 가 출처 키 리터럴로 비교·분기하지 않는다", () => {
    for (const [f, raw] of [["Stage5.tsx", STAGE5_SRC], ["SourceTabs.tsx", TABS_SRC]] as const) {
      const text = raw.replace('availability !== "full"', ""); // 기존 코드(PastFrame 보존 상태 값 — 출처 키 아님)
      expect(text, f).not.toMatch(/(===|!==|case|\?|:)\s*["'](jig|full|bforce|fint)["']/);
    }
    const valPart = SOURCES_SRC.slice(SOURCES_SRC.indexOf("VAL_NOT_RUN_CODE"));
    expect(valPart).not.toMatch(/(===|!==)\s*["'](jig|full|bforce|fint)["']/);
  });
});

describe("V-0243-VAL-17 화면: 탭·URL", () => {
  it("탭 4개(표 순서·이름)·표식·기본 탭 full·legacy URL 은 src 없음, 다른 탭은 ?src=", async () => {
    const { calls } = renderWith(ok);
    const strip = await tabs();
    expect(Array.from(strip.querySelectorAll("[role=tab]")).map((b) => b.getAttribute("data-tab"))).toEqual(["jig", "full", "bforce", "fint"]);
    expect(tab("full").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("val-src-mark-full").textContent).toBe("PASS");
    expect(screen.getByTestId("val-src-mark-bforce").textContent).toBe("FAIL · 비교용 아님");
    expect(screen.getByTestId("val-src-mark-fint").textContent).toBe("PASS ⚠");
    expect(tab("bforce").title).toContain("하중");
    expect(tab("jig").getAttribute("aria-disabled")).toBe("true");
    await within(judge()).findByText("변위 RMS (상대)");
    expect(calls).toContain("GET /esl/api/validations/val-1?");
    expect(calls.some((c) => c.startsWith("GET /esl/api/validations/val-1?src="))).toBe(false);
    expect(calls).toContain("GET /esl/api/validations/val-1/sources?");
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(calls).toContain("GET /esl/api/validations/val-1?src=bforce"));
    await waitFor(() => expect(calls.some((c) => c.startsWith("GET /esl/api/validations/val-1/disp-field?") && c.includes("src=bforce"))).toBe(true));
    expect(calls.some((c) => c.startsWith("GET /esl/api/validations/val-1/field?") && c.includes("src=bforce"))).toBe(true);
    await waitFor(() => expect(calls.some((c) => c.startsWith("GET /esl/api/validations/val-1/section?") && c.includes("src=bforce"))).toBe(true));
    // legacy 탭의 field·disp-field 는 src 를 달지 않았다
    expect(calls.filter((c) => /\/(field|disp-field)\?/.test(c) && !c.includes("src=")).length).toBeGreaterThan(0);
    fireEvent.click(tab("full"));
    await waitFor(() => expect(tab("full").getAttribute("aria-selected")).toBe("true"));
  });

  it("탭을 바꿔도 같은 카드: 판정 4칸·변위 카드·변형률 카드·hotspot·제외 요소, 주 버튼·등록 = full 기준", async () => {
    renderWith(ok);
    await tabs();
    await within(judge()).findByText("변위 RMS (상대)");
    const regions = () => screen.getAllByRole("region").map((r) => r.getAttribute("aria-label") ?? "");
    const before = regions();
    fireEvent.click(tab("fint"));
    await waitFor(() => expect(tab("fint").getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(regions()).toEqual(before));
    expect(within(judge()).getAllByText(/기준 ≤/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole("region", { name: "변위 비교 (전 노드)" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "hotspot ε_eq 오차" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "제외 요소" })).toBeTruthy();
    // 출처 탭의 판정 배지 title: 등록·내보내기 기준 안내
    expect(document.querySelector('[title*="라이브러리 등록·내보내기 기준은 전 노드 ESL 판정"]')).toBeTruthy();
    // 주 버튼 = full(PASS) 기준 '라이브러리에 등록'(탭과 무관)
    expect(await screen.findByRole("button", { name: /라이브러리에 등록/ })).toBeTruthy();
    fireEvent.click(tab("bforce")); // 경계력 FAIL 이어도 등록 버튼은 full 기준 그대로
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByRole("button", { name: /라이브러리에 등록/ })).toBeTruthy();
  });
});

describe("V-0243-VAL-18 결과 없는 탭", () => {
  it("VAL_SRC_NOT_RUN 탭은 선택 가능('+'), 본문 = 사유 1줄 + [검증 다시 실행] 버튼 1개, 누르면 VALIDATE 작업", async () => {
    const { calls } = renderWith((s) => (s.valSourcesMode = "notrun"));
    await tabs();
    expect(tab("bforce").getAttribute("data-add")).toBe("1");
    expect(tab("bforce").textContent).toContain("+");
    expect(tab("jig").getAttribute("data-add")).toBeNull();
    const before = screen.getAllByRole("button").length;
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    const body = await screen.findByTestId("val-src-notrun");
    expect(body.textContent).toContain("경계력 ESL 불가 — 이 검증에는 출처별 결과가 없습니다");
    expect(within(body).getAllByRole("button")).toHaveLength(1);
    expect(within(body).getByRole("button", { name: "검증 다시 실행" })).toBeTruthy();
    expect(screen.queryByTestId("judge-stats")).toBeNull(); // 본문 = 사유 + 버튼 뿐(카드 나머지 없음)
    expect(screen.getAllByRole("button").length - before).toBeLessThanOrEqual(1); // 화면 버튼 추가 ≤ 1
    fireEvent.click(within(body).getByRole("button", { name: "검증 다시 실행" }));
    await waitFor(() => expect(calls.some((c) => c.startsWith("POST /esl/api/cases/c-demo/jobs"))).toBe(true));
    // 판정 카드 머리(탭)는 유지, full 탭으로 돌아오면 지금 카드
    fireEvent.click(tab("full"));
    await within(await screen.findByTestId("judge-stats")).findByText("변위 RMS (상대)");
  });

  it("과거 실행(?val=): 탭은 보이나 빈 탭은 선택 불가·버튼 없음", async () => {
    renderWith((s) => (s.valSourcesMode = "notrun"), `${STAGE5}?val=val-1`);
    await tabs();
    expect(tab("bforce").getAttribute("data-add")).toBeNull();
    expect(tab("bforce").getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(tab("bforce"));
    expect(tab("full").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByTestId("val-src-notrun")).toBeNull();
    expect(screen.queryByRole("button", { name: "검증 다시 실행" })).toBeNull();
  });

  it("권한 없는 사용자(allowed 아님)는 빈 탭도 선택 불가", async () => {
    const server = new MockServer({ user: "general" });
    server.valSourcesMode = "notrun";
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter initialEntries={[STAGE5]}>
        <App />
      </MemoryRouter>,
    );
    await tabs();
    expect(tab("bforce").getAttribute("data-add")).toBeNull();
  });
});

describe("V-0243-VAL-19 설명 줄·반력 정보·판정 불가·이력", () => {
  it("변위 설명 = 행 note(legacy 는 지금 문구 그대로), reaction_role info → 반력 칸 기준·색 없음", async () => {
    renderWith(ok);
    await tabs();
    const dc = await screen.findByRole("region", { name: "변위 비교 (전 노드)" });
    expect(within(dc).getByText(/수치 일관성을 봅니다\(물리적 차이가 아닙니다\)/)).toBeTruthy();
    const reactionStat = () => within(judge()).getByText("반력 (상대)").closest(".stat") as HTMLElement;
    expect(within(reactionStat()).getByText(/기준 ≤/)).toBeTruthy();
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "변위 비교 (전 노드)" })).getByText(/하중이 낙하 변형을 얼마나 재현하는지/)).toBeTruthy());
    const rs = reactionStat();
    expect(within(rs).getByText("정보 — 지지 반력")).toBeTruthy();
    expect(within(rs).queryByText(/기준 ≤/)).toBeNull();
    expect(rs.className).not.toMatch(/bad|ok/);
    // 다른 칸은 기준·판정 색 그대로
    const rms = within(judge()).getByText("변위 RMS (상대)").closest(".stat") as HTMLElement;
    expect(within(rms).getByText(/기준 ≤/)).toBeTruthy();
    fireEvent.click(tab("fint")); // role judge 출처는 반력 기준 표시
    await waitFor(() => expect(tab("fint").getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(within(reactionStat()).getByText(/기준 ≤/)).toBeTruthy());
  });

  it("판정 불가 출처: field 없고 undetermined_reason 이면 안내 1줄(옛 검증 안내 warn-box 와 구별)", async () => {
    const { server } = renderWith(ok);
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b) => {
      const r = orig(m, p, q, b);
      if (m === "GET" && /\/validations\/val-1$/.test(p) && q.get("src") === "bforce")
        return { ...r, body: { ...(r.body as object), verdict: "UNDETERMINED", status: "UNDETERMINED", undetermined_reason: "NO_FULL_SOLVE", field: null, disp: null, disp_rms_rel: null, disp_max_rel: null, reaction_rel: null, fail_reasons: [] } };
      return r;
    };
    await tabs();
    fireEvent.click(tab("bforce"));
    const note = await screen.findByTestId("strain-note");
    expect(note.textContent).toBe("전체 재해석이 없어 변형률 비교를 표시할 수 없습니다");
    expect(note.className).not.toContain("warn-box");
    expect(document.querySelector(".warn-box")).toBeNull();
  });

  it("이력 판정 열: legacy 탭 = 지금 StatusBadge, 출처 탭 = 그 출처 상태(없음 = – + 사유 title)", async () => {
    renderWith((s) => {
      ok(s);
      const old = { ...makeValidation("val-0", "run-1", "c-demo"), created_at: "2026-10-17T03:20:00Z", status: "FAIL" as const, verdict: "FAIL" as const, fail_reasons: ["DISP_RMS"], disp_rms_rel: 1.4e-2 };
      s.validations.unshift(old);
    });
    await tabs();
    const cells = async () => Array.from(await screen.findAllByTestId("hist-status")).map((c) => c.textContent);
    await waitFor(async () => expect(await cells()).toEqual(["PASS", "FAIL"]));
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await waitFor(async () => expect(await cells()).toEqual(["FAIL", "–"]));
    const dash = screen.getAllByTestId("hist-status")[1].querySelector("[title]") as HTMLElement;
    expect(dash.title).toContain("경계력 ESL 불가 — 이 검증에는 출처별 결과가 없습니다");
    fireEvent.click(tab("full"));
    await waitFor(async () => expect(await cells()).toEqual(["PASS", "FAIL"]));
  });
});

describe("V-0243-VAL-20 SourceTabs mark·옛 서버", () => {
  const base = [
    { key: "a", label: "에이", title: "ta", ok: true, why: null },
    { key: "b", label: "비", title: "tb", ok: false, why: "비 불가 — 사유" },
  ];
  const html = (items: Parameters<typeof SourceTabs>[0]["items"]) =>
    render(<SourceTabs items={items} tab="a" setTab={() => {}} label="L" prefix="p" testId="t" whyTestId="w" />).container.innerHTML;

  it("mark 가 없으면 DOM 이 같다(속성 추가 없음), 있으면 라벨 뒤 표식만 늘어난다", () => {
    const plain = html(base);
    document.body.innerHTML = "";
    expect(html(base.map((i) => ({ ...i })))).toBe(plain);
    expect(plain).not.toContain("mark");
    document.body.innerHTML = "";
    const marked = html([{ ...base[0], mark: { text: "PASS", tone: "ok" as const } }, base[1]]);
    expect(marked).toContain('data-testid="p-mark-a"');
    expect(marked).toContain("PASS");
  });

  it("옛 서버(sources 404) = 탭 없이 v0.24.2 화면(주 버튼·카드 그대로)", async () => {
    renderWith((s) => (s.valSourcesMode = "old"));
    await within(await screen.findByTestId("judge-stats")).findByText("변위 RMS (상대)");
    expect(screen.queryByTestId("val-src-tab")).toBeNull();
    expect(screen.getByRole("region", { name: "변위 비교 (전 노드)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /라이브러리에 등록/ })).toBeTruthy();
  });
});


describe("v0.24.3 Verifier — 판정 카드 머리 1줄(제목·탭·판정·버튼), 등록 불가 사유는 본문 첫 줄", () => {
  it("FAIL 인데 출처 탭이 있어도: 머리 안에 사유 문구 없음 · 머리 직계 = 제목 + 오른쪽 묶음 1개 · 사유는 카드 본문 첫 줄(role=note, 마우스 없이 보임)", async () => {
    const { server } = renderWith((s) => {
      ok(s);
      s.validations[0] = { ...s.validations[0], verdict: "FAIL", status: "FAIL", fail_reasons: ["DISP_RMS"] };
    });
    await tabs();
    const reason = await screen.findByTestId("reg-reason");
    expect(reason.textContent).toBe(REG_NOT_PASS);
    expect(reason.getAttribute("role")).toBe("note");
    const card = judge().closest(".card") as HTMLElement;
    const head = card.querySelector(".card-head") as HTMLElement;
    expect(head.contains(reason)).toBe(false); // 머리 밖
    expect(card.querySelector(".card-body")!.firstElementChild).toBe(reason); // 본문 첫 줄
    expect(head.textContent).not.toContain(REG_NOT_PASS);
    // 머리 한 줄: 제목(h3) + 오른쪽 묶음(.inline-actions, 줄바꿈 없음 — CSS) 둘뿐, 탭·등록 버튼은 그 묶음 안
    const kids = [...head.children].map((e) => e.tagName + "." + e.className);
    expect(kids).toEqual(["H3.", "SPAN.inline-actions"]);
    const right = head.lastElementChild as HTMLElement;
    expect(right.querySelector("[data-testid=val-src-tab]")).toBeTruthy();
    expect(within(right).getByRole("button", { name: "라이브러리에 등록" })).toBeTruthy();
    expect(server.validations[0].verdict).toBe("FAIL");
  });

  it("머리 1줄 CSS 규칙: 제목은 줄어들지 않고(nowrap) 오른쪽 묶음은 줄바꿈 없음, 탭 단추 좌우 여백 축소", async () => {
    const css = readFileSync(`${__dirname}/../styles.css`, "utf8");
    expect(css).toMatch(/\.card-head:has\(\.val-src-tabwrap\) h3\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap/);
    expect(css).toMatch(/\.card-head:has\(\.val-src-tabwrap\) > \.inline-actions\s*\{[^}]*flex-wrap:\s*nowrap/);
  });

  it("출처별 반력 허용치: fint 탭 툴팁·반력 칸 = 판정에 쓴 허용치(10 %)·주의(5 %); 전 노드 탭은 문구 없음", async () => {
    renderWith(ok);
    await tabs();
    expect(tab("fint").title).toContain("반력 허용치 ≤ 10 % · 주의 > 5 %");
    expect(tab("full").title).not.toContain("반력 허용치");
    fireEvent.click(tab("fint"));
    await waitFor(() => expect(tab("fint").getAttribute("aria-selected")).toBe("true"));
    const stat = () => within(judge()).getByText("반력 (상대)").closest(".stat") as HTMLElement;
    await waitFor(() => expect(within(stat()).getByText(/기준 ≤ 1\.00e-1 · 주의 > 5\.00e-2/)).toBeTruthy());
    expect(stat().getAttribute("title")).toBe("반력 허용치 ≤ 10 % · 주의 > 5 %");
  });
});
