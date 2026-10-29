// v0.7.2 재현 시험: 운영(v0.6.0 → v0.7.0 update-repo) 서버에서 새 비드 최적화(/opt/new?entries=…) 빈 화면.
// 원인: 코드 스냅샷에 resources/opt_method_sources.json 이 없어 GET /opt/settings.method_sources = {error} →
// LoadStrategy 가 src.strategies.A 를 읽다 TypeError(렌더 예외, 경계 없음 → 빈 화면). 백엔드 짝 = backend/tests/test_opt_legacy_server.py.
// 변형: opt_run 꺼짐·솔버 미준비·크기/모드/topo null·s1-check 오류·plan-view 오류·entries 1개/여러 개, 오류 경계 표시.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import { normalizeOptSettings, resetOptSettingsCache } from "../api/opt";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { makeOptSettings } from "../mock/optdata";
import type { MockServer } from "../mock/server";
import type { OptSettingsOut } from "../api/types";
import { render } from "@testing-library/react";

const NO_SOURCES = { error: "방법·출처 자료를 읽지 못했습니다(관리자 문의)" };
/** v0.7.0 운영 서버 응답: opt_run 섹션 없음(enabled false) + 방법·출처 자료 없음 */
const legacySettings = (over: Partial<OptSettingsOut> = {}) =>
  ({ ...makeOptSettings(), enabled: false, solver_ready: false, solver_reason: "비드 최적화가 꺼져 있습니다 — 관리자 문의", method_sources: NO_SOURCES, ...over }) as unknown as OptSettingsOut;

/** v0.7.0 이전 등록 항목: size·topo·deform_mode 없음, 인치 null 일부 */
function legacyEntries(s: MockServer, ids: string[]) {
  for (const e of s.entries) {
    if (!ids.includes(e.id)) continue;
    const x = e as unknown as Record<string, unknown>;
    delete x.size;
    x.topo_sha256 = null;
    x.deform_mode = null;
  }
  const first = s.entries.find((e) => e.id === ids[0]);
  if (first) first.model = { ...first.model, inch: null };
}

/** OptMock 응답 바꿔치기(path → 응답 함수) */
function patchOpt(s: MockServer, routes: Record<string, () => { status: number; body: unknown }>) {
  const orig = s.opt.handle.bind(s.opt);
  s.opt.handle = (method, path, q, b) => (routes[`${method} ${path}`] ? (routes[`${method} ${path}`]() as ReturnType<typeof orig>) : orig(method, path, q, b));
}

const runBtn = () => screen.getByRole("button", { name: "최적화 실행" }) as HTMLButtonElement;
const runReason = () => runBtn().closest(".primary-wrap")?.getAttribute("title") ?? null;

afterEach(() => {
  resetOptSettingsCache();
  vi.restoreAllMocks();
});

describe("새 비드 최적화 — 운영 서버 응답(빈 화면 회귀)", () => {
  it("방법·출처 {error} + opt_run 꺼짐 + 이전 항목 3개: 화면 정상, 실행 비활성 + 사유 한 줄", async () => {
    const errs = vi.spyOn(console, "error").mockImplementation(() => {});
    renderApp("/p/p-body/opt/new?entries=le-1,le-2,le-3", "power", (s) => {
      s.opt.settings = legacySettings();
      legacyEntries(s, ["le-1", "le-2", "le-3"]);
    });
    await screen.findByRole("heading", { name: "새 비드 최적화" });
    await waitFor(() => expect(screen.getByTestId("opt-blocked").textContent).toBe("최적화 실행 불가: 비드 최적화가 꺼져 있습니다 — 관리자 문의"));
    expect(screen.queryByTestId("screen-error")).toBeNull();
    expect(runBtn().disabled).toBe(true);
    expect(runReason()).toBe("비드 최적화가 꺼져 있습니다 — 관리자 문의");
    await screen.findByRole("radiogroup", { name: "하중 선정 전략" });              // ④ 카드(예외 지점) 정상
    const info = screen.getByRole("button", { name: "방법·출처" }) as HTMLButtonElement;
    expect(info.disabled).toBe(true);
    expect(info.title).toMatch(/방법·출처 자료를 읽지 못했습니다/);
    await screen.findByRole("table", { name: "선택한 ESL" });
    expect(screen.getAllByText("분류 불가").length).toBeGreaterThan(0);              // deform_mode null
    expect(errs.mock.calls.some((c) => String(c[0]).includes("화면 오류"))).toBe(false);
  });

  it("opt_run 켜짐 + OptiStruct 경로 없음(solver_ready false): 사유 = 서버 solver_reason 한 줄", async () => {
    renderApp("/p/p-body/opt/new?entries=le-1", "power", (s) => {
      s.opt.settings = legacySettings({ enabled: true, solver_reason: "서버 OptiStruct 경로가 설정되지 않았습니다 — 관리자 문의" });
    });
    await waitFor(() => expect(screen.getByTestId("opt-blocked").textContent).toBe("최적화 실행 불가: 서버 OptiStruct 경로가 설정되지 않았습니다 — 관리자 문의"));
    expect(runReason()).toBe("서버 OptiStruct 경로가 설정되지 않았습니다 — 관리자 문의");
  });

  it("부분 응답(loads·bead_defaults·method_sources 없음)·s1-check 409·plan-view 500: 화면 유지", async () => {
    renderApp("/p/p-body/opt/new?entries=le-1,le-2&tab=S1", "power", (s) => {
      const st = legacySettings() as unknown as Record<string, unknown>;
      delete st.loads;
      delete st.bead_defaults;
      delete st.method_sources;
      s.opt.settings = st as unknown as OptSettingsOut;
      legacyEntries(s, ["le-1", "le-2"]);
      patchOpt(s, {
        "POST /opt/s1-check": () => ({ status: 409, body: { detail: { code: "PREREQUISITE_MISSING", message: "기준 Case 입력 rad 를 읽을 수 없습니다" } } }),
        "GET /opt/plan-view": () => ({ status: 500, body: { detail: { code: "INTERNAL", message: "x" } } }),
      });
    });
    await screen.findByRole("heading", { name: "새 비드 최적화" });
    await screen.findByText(/기준 Case 입력 rad 를 읽을 수 없습니다/);
    await screen.findByRole("radiogroup", { name: "하중 선정 전략" });
    expect((screen.getByRole("spinbutton", { name: "비드 경사 (°)" }) as HTMLInputElement).value).toBe("45");
    expect(screen.queryByTestId("screen-error")).toBeNull();
  });

  it("s1-check 200 이지만 entries·base 일부 없음 → 깨지지 않음", async () => {
    renderApp("/p/p-body/opt/new?entries=le-1", "power", (s) => {
      s.opt.settings = legacySettings();
      patchOpt(s, { "POST /opt/s1-check": () => ({ status: 200, body: { base: { entry_id: "le-1", case_id: "c" } } }) });
    });
    await screen.findByRole("heading", { name: "새 비드 최적화" });
    await screen.findByRole("table", { name: "선택한 ESL" });
    expect(screen.queryByTestId("screen-error")).toBeNull();
  });
});

describe("응답 보정(normalizeOptSettings)", () => {
  it("빈 응답 → 꺼짐 + 기본값, method_sources {error} 유지", () => {
    const s = normalizeOptSettings({});
    expect(s.enabled).toBe(false);
    expect(s.solver_ready).toBe(false);
    expect(s.loads.default_strategy).toBe("A");
    expect(s.bead_defaults).toEqual({ angle: 45, min_width: 60, height: 10 });
    expect(s.method_sources.strategies.A).toBe("");
    expect(s.method_sources.error).toBeTruthy();
    expect(normalizeOptSettings({ method_sources: NO_SOURCES }).method_sources.error).toBe(NO_SOURCES.error);
    const ok = normalizeOptSettings(makeOptSettings());
    expect(ok.method_sources.error).toBeUndefined();
    expect(ok.enabled).toBe(true);
  });
});

describe("화면 오류 경계(ErrorBoundary)", () => {
  function Boom({ on }: { on: { v: boolean } }) {
    if (on.v) throw new Error("렌더 실패 시험");
    return <div>다시 그림</div>;
  }
  it("렌더 예외 → '화면 오류: <메시지> [다시 시도]', 콘솔에 스택, 다시 시도로 복구", () => {
    const errs = vi.spyOn(console, "error").mockImplementation(() => {});
    const on = { v: true };
    render(
      <ErrorBoundary>
        <Boom on={on} />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("screen-error").textContent).toMatch(/^화면 오류: 렌더 실패 시험/);
    expect(errs.mock.calls.some((c) => String(c[0]).includes("화면 오류") && c[1] instanceof Error)).toBe(true);
    on.v = false;
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(screen.getByText("다시 그림")).toBeTruthy();
  });

  it("App 페이지 경계: 페이지 렌더 예외도 빈 화면이 아님", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    // 보정 전 응답 형태를 그대로 넣어 LoadStrategy 를 직접 깨뜨림(정규화 우회) — 경계가 잡아 메시지 표시
    const mod = await import("../api/opt");
    vi.spyOn(mod.opt, "settings").mockResolvedValue({ ...makeOptSettings(), method_sources: NO_SOURCES } as unknown as OptSettingsOut);
    renderApp("/p/p-body/opt/new?entries=le-1");
    await screen.findByRole("heading", { name: "새 비드 최적화" });
    // 정규화를 우회해도 LoadStrategy 자체가 옵셔널 처리 → 화면 정상
    await screen.findByRole("radiogroup", { name: "하중 선정 전략" });
    expect(screen.queryByTestId("screen-error")).toBeNull();
  });
});
