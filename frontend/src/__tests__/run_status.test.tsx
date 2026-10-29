// V-L3-12: 상태 서랍 — 모든 Shell 화면에 칩 2개·RightPanel 없음, 폴링 1곳, 칩 문구, 토글·닫기·Esc·포커스 복귀, localStorage 기억.
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DRAWER_KEY, POLL_MS, queueChipText, workerChipText } from "../shell/RunStatus";
import { renderApp } from "../test/render";
import type { MockServer } from "../mock/server";

const chipQ = () => screen.getByTestId("chip-queue");
const chipW = () => screen.getByTestId("chip-worker");
const drawer = () => screen.queryByRole("complementary", { name: "실행 상태" });

/** fetch 를 감싸 /queue·/status 호출 수를 센다 */
function countCalls() {
  const base = globalThis.fetch;
  const counts = { queue: 0, status: 0 };
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const u = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    if (/\/esl\/api\/queue(\?|$)/.test(u)) counts.queue++;
    if (/\/esl\/api\/status(\?|$)/.test(u)) counts.status++;
    return base(input, init);
  }) as typeof fetch;
  return counts;
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* 무시 */
  }
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("V-L3-12 상태 칩·서랍", () => {
  it("모든 Shell 화면에 칩 2개, 우측 패널(aside 대기열·워커)은 없다, 서랍은 기본 닫힘", async () => {
    for (const path of ["/", "/p/p-body", "/p/p-body/c/c-demo/stage/4", "/guide", "/updates", "/p/p-body/library"]) {
      const { unmount } = renderApp(path);
      await waitFor(() => expect(chipQ().textContent).toMatch(/^계산 \d+\/\d+ · 대기 \d+/));
      expect(chipW().textContent).toContain("워커 동작 중 · 솔버 cholmod");
      expect(document.querySelector('aside[aria-label="대기열·워커"]')).toBeNull();
      expect(document.querySelector(".rightpanel")).toBeNull();
      expect(drawer()).toBeNull();
      expect(document.querySelector(".page.drawer-open")).toBeNull();
      expect(chipQ().getAttribute("aria-expanded")).toBe("false");
      unmount();
    }
  });

  it("폴링은 RunStatusProvider 1곳: 간격(POLL_MS) 타이머는 queue·status 각 1개, 칩·서랍 열림과 무관, 틱마다 각 1회", async () => {
    const timers: (() => void)[] = [];
    const realSet = globalThis.setInterval;
    vi.spyOn(globalThis, "setInterval").mockImplementation(((fn: () => void, ms?: number, ...a: unknown[]) => {
      if (ms === POLL_MS) {
        timers.push(fn);
        return 0 as unknown as ReturnType<typeof setInterval>;
      }
      return (realSet as (...x: unknown[]) => ReturnType<typeof setInterval>)(fn, ms, ...a);
    }) as typeof setInterval);
    const counts = { queue: 0, status: 0 };
    renderApp("/guide", "power", (s: MockServer) => {
      const h = s.handle.bind(s);
      s.handle = ((method: string, path: string, ...rest: unknown[]) => {
        if (method === "GET" && /\/queue$/.test(path)) counts.queue++;
        if (method === "GET" && /\/status$/.test(path)) counts.status++;
        return (h as (...a: unknown[]) => unknown)(method, path, ...rest);
      }) as MockServer["handle"];
    });
    await waitFor(() => expect(counts).toEqual({ queue: 1, status: 1 }));
    expect(timers.length).toBe(2);
    fireEvent.click(chipQ()); // 서랍 열기
    expect(drawer()).toBeTruthy();
    fireEvent.click(chipW()); // 닫기
    fireEvent.click(chipW()); // 다시 열기(워커 구획으로)
    await act(async () => {
      await Promise.resolve();
    });
    expect(counts).toEqual({ queue: 1, status: 1 });
    expect(timers.length).toBe(2); // 서랍·칩이 폴링을 더 만들지 않는다
    await act(async () => {
      timers.forEach((t) => t());
    });
    await waitFor(() => expect(counts).toEqual({ queue: 2, status: 2 }));
  });

  it("화면 이동(링크)해도 폴링 호출 수가 늘지 않는다(Provider 는 앱 루트에 1회)", async () => {
    renderApp("/p/p-body");
    const counts = countCalls();
    await screen.findByRole("heading", { name: "ESL 생성" });
    fireEvent.click(await screen.findByRole("link", { name: "사용 가이드" }));
    await screen.findByTestId("chip-queue");
    expect(counts.queue).toBeLessThanOrEqual(1);
    expect(counts.status).toBeLessThanOrEqual(1);
  });

  it("칩 문구: 실행/slots · 대기 · 보고서, 워커 오프라인, 설정 오류", async () => {
    const q = (running: number, queued: number, light = 0) =>
      queueChipText({
        queue: {
          running: null,
          running_all: Array.from({ length: running }, () => ({}) as never),
          slots: 2,
          queued: Array.from({ length: queued }, () => ({}) as never),
          light: { running: null, queued: Array.from({ length: light }, () => ({}) as never) },
        },
        queueError: null,
      });
    expect(q(1, 3)).toBe("계산 1/2 · 대기 3");
    expect(q(2, 0, 2)).toBe("계산 2/2 · 대기 0 · 보고서 2");
    expect(queueChipText({ queue: null, queueError: null })).toBe("대기열 불러오는 중…");
    const st = (online: boolean, errors: { key: string; message: string }[] = []) =>
      workerChipText({ status: { config: { ok: errors.length === 0, errors }, worker: { online }, tools: { solver_backend: "pardiso", solver_backends_available: ["pardiso"] }, version: "x", core_version: "x" }, statusError: null });
    expect(st(true)).toEqual({ text: "워커 동작 중 · 솔버 pardiso", bad: false, ok: true });
    expect(st(false)).toMatchObject({ text: "워커 응답 없음", bad: true });
    expect(st(true, [{ key: "a", message: "b" }])).toMatchObject({ text: "워커 동작 중 · 솔버 pardiso · 설정 오류 1", bad: true });

    renderApp("/", "power", (s) => {
      s.workerOnline = false;
      s.configErrors = [{ key: "storage.esl_root", message: "절대경로여야 합니다" }];
    });
    await waitFor(() => expect(chipW().textContent).toBe("워커 응답 없음 · 설정 오류 1"));
    expect(chipW().className).toContain("bad");
    fireEvent.click(chipW());
    expect(await screen.findByText(/설정 오류: storage\.esl_root: 절대경로여야 합니다/)).toBeTruthy();
  });

  it("h3d 추출 시연: 계산 2/2 · 칩 강조(내 작업) · 서랍에 동시 실행 2/2 와 행", async () => {
    renderApp("/p/p-body", "power", (s) => s.demoH3dExtract());
    await waitFor(() => expect(chipQ().textContent).toContain("계산 2/2"));
    expect(chipQ().className).toContain("running");
    fireEvent.click(chipQ());
    expect((await screen.findByTestId("queue-slots")).textContent).toBe("동시 실행 2/2");
    expect(screen.getAllByText("추출").length).toBeGreaterThanOrEqual(2);
  });

  it("토글·닫기 버튼·Esc(서랍 안 포커스) → 닫고 여는 칩으로 포커스 복귀, aria-expanded·aria-controls", async () => {
    renderApp("/p/p-body");
    await waitFor(() => expect(chipQ().textContent).toMatch(/^계산/));
    expect(chipQ().getAttribute("aria-controls")).toBe("status-drawer");
    fireEvent.click(chipQ());
    const d = await screen.findByRole("complementary", { name: "실행 상태" });
    expect(d.id).toBe("status-drawer");
    expect(chipQ().getAttribute("aria-expanded")).toBe("true");
    expect(chipW().getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector(".page.drawer-open")).toBeTruthy();
    expect(document.querySelector(".scrim, [aria-modal='true']")).toBeNull(); // 비모달
    expect(screen.getByText("계산 대기열")).toBeTruthy();
    expect(screen.getByText("워커")).toBeTruthy();
    fireEvent.click(chipQ()); // 같은 칩 = 토글(닫기)
    expect(drawer()).toBeNull();
    fireEvent.click(chipW());
    const d2 = await screen.findByRole("complementary", { name: "실행 상태" });
    (d2.querySelector("button") as HTMLButtonElement).focus();
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(drawer()).toBeNull();
    expect(document.activeElement).toBe(chipW());
    fireEvent.click(chipQ());
    fireEvent.click(await screen.findByRole("button", { name: "실행 상태 닫기" }));
    expect(drawer()).toBeNull();
  });

  it("localStorage 기억: 다시 마운트해도 열림 유지, 닫으면 closed 저장", async () => {
    const first = renderApp("/p/p-body");
    await waitFor(() => expect(chipQ().textContent).toMatch(/^계산/));
    fireEvent.click(chipQ());
    expect(localStorage.getItem(DRAWER_KEY)).toBe("open");
    first.unmount();
    renderApp("/p/p-body/c/c-demo/stage/4");
    expect(await screen.findByRole("complementary", { name: "실행 상태" })).toBeTruthy();
    expect(document.querySelector(".page.drawer-open")).toBeTruthy();
    fireEvent.click(chipQ());
    expect(localStorage.getItem(DRAWER_KEY)).toBe("closed");
  });

  it("localStorage 예외(읽기·쓰기) → 닫힘으로 동작하고 오류 없음", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    renderApp("/p/p-body");
    await waitFor(() => expect(chipQ().textContent).toMatch(/^계산/));
    expect(drawer()).toBeNull();
    fireEvent.click(chipQ());
    expect(await screen.findByRole("complementary", { name: "실행 상태" })).toBeTruthy(); // 화면 상태로는 열린다
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
