// V-RA-16(프런트, mock): 새 Case 체크박스 → POST /cases run_all, Case 화면 주 버튼 [일괄 실행]/[이어서 실행] 상태 전이·비활성 사유,
// 일괄 실행 중 단계 주 버튼 비활성(RUN_ALL_ACTIVE), 진행 줄 4상태 문구·멈춤 사유·[일괄 취소] 확인, 실행 이력 '일괄' 배지·일괄 실행 기록.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";
import { MockServer, createMockFetch } from "../mock/server";
import { HistoryTable } from "../components/HistoryTable";
import type { HistoryItem } from "../api/history";
import { CODE_TEXT } from "../api/client";
import { RUN_ALL_ACTIVE_REASON } from "../stages/common";
import { RUN_ALL_CHECK_LABEL } from "../pages/newcase/NewCase";
import {
  RESUME_LABEL, RUN_ALL_ALL_DONE_REASON, RUN_ALL_BUSY_REASON, RUN_ALL_CANCELED_TEXT, RUN_ALL_CANCEL_CONFIRM, RUN_ALL_DONE_TEXT, RUN_ALL_LABEL, runAllButton,
} from "../shell/RunAllBar";
import type { Case } from "../api/types";

const NEW = "/p/p-body/cases/new";
const CNEW = "/p/p-body/c/c-new";
const LONG = { timeout: 4000 };
const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const runBtn = (c: HTMLElement) => c.querySelector("button[data-run-all]") as HTMLButtonElement;
const reasonOf = (b: HTMLElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? null;
const bar = () => screen.findByTestId("run-all-bar");

type Req = { method: string; path: string; body: unknown };
function mount(path: string, setup?: (s: MockServer) => void, user: "power" | "general" = "power") {
  const server = new MockServer({ user });
  setup?.(server);
  const inner = createMockFetch(server);
  const reqs: Req[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://mock.local");
    reqs.push({ method: (init?.method ?? "GET").toUpperCase(), path: url.pathname + url.search, body: init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined });
    return inner(input, init);
  }) as typeof fetch;
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { server, reqs, ...view };
}
/** 서버 쪽에서 체인을 시작해 끝까지 진행(화면은 결과 상태로 연다) */
const startAndDrain = (s: MockServer, caseId = "c-new", from?: string) => {
  s.handle("POST", `/cases/${caseId}/run-all`, new URLSearchParams(), from ? { from } : {});
  s.drain();
};

afterEach(() => vi.restoreAllMocks());

describe("새 Case 체크박스 '생성 후 일괄 실행'", () => {
  async function pickServerFolder(container: HTMLElement) {
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.click(screen.getByRole("tab", { name: "서버 폴더에서 고르기" }));
    const table = await screen.findByRole("table", { name: "서버 폴더 목록" });
    fireEvent.click(await within(table).findByRole("button", { name: /^kim\// }));
    fireEvent.click(await within(table).findByRole("button", { name: /20261019-031200_QN80H_rear40/ }));
    fireEvent.click(await within(table).findByRole("button", { name: /^rad\// }));
    fireEvent.click(await within(table).findByRole("button", { name: "rad 선택" }));
    expect(await screen.findByLabelText("rad 확인 결과")).toBeTruthy();
    fireEvent.click(within(container.querySelector(".browse-crumbs") as HTMLElement).getByRole("button", { name: "20261019-031200_QN80H_rear40" }));
    fireEvent.click(await within(table).findByRole("button", { name: /^h3d\// }));
    fireEvent.click(await within(table).findByRole("button", { name: "h3d 선택" }));
    const btn = primaries(container)[0];
    await waitFor(() => expect(btn.disabled).toBe(false));
    return btn;
  }

  it("기본 꺼짐 → 그대로 만들면 run_all 없이 요청, 체인 없음", async () => {
    const { container, reqs, server } = mount(NEW);
    const btn = await pickServerFolder(container);
    const box = screen.getByLabelText(RUN_ALL_CHECK_LABEL) as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(primaries(container)).toHaveLength(1);
    fireEvent.click(btn);
    expect(await screen.findByRole("heading", { level: 2, name: "① 입력" })).toBeTruthy();
    const post = reqs.find((r) => r.method === "POST" && r.path.endsWith("/cases"))!;
    expect((post.body as Record<string, unknown>).run_all).toBeUndefined();
    expect(server.runAlls).toHaveLength(0);
    expect(screen.queryByTestId("run-all-bar")).toBeNull();
  });

  it("켜고 만들면 run_all:true → Case 화면 진행 줄 '일괄 실행 중 — ① 입력', 작업에 run_all_id", async () => {
    const { container, reqs, server } = mount(NEW);
    const btn = await pickServerFolder(container);
    fireEvent.click(screen.getByLabelText(RUN_ALL_CHECK_LABEL));
    fireEvent.click(btn);
    expect(await screen.findByRole("heading", { level: 2, name: "① 입력" })).toBeTruthy();
    const post = reqs.find((r) => r.method === "POST" && r.path.endsWith("/cases"))!;
    expect((post.body as Record<string, unknown>).run_all).toBe(true);
    expect(server.runAlls).toHaveLength(1);
    const job = server.jobs.find((j) => j.id === server.runAlls[0].cur_job_id)!;
    expect(job.job_type).toBe("CASE_EXTRACT");
    expect(job.run_all_id).toBe(server.runAlls[0].id);
    expect((await bar()).textContent).toMatch(/일괄 실행 중 — ① 입력 · 대기 중/);
  });
});

describe("Case 화면 주 버튼 [일괄 실행] 상태 전이", () => {
  it("시작 → RUNNING(버튼 '일괄 실행 중' 비활성, 단계 주 버튼 RUN_ALL_ACTIVE, ① 강조) → 끝까지 → DONE PASS", async () => {
    const { container, reqs, server } = mount(`${CNEW}/step/1`);
    await screen.findByRole("heading", { level: 2, name: "① 입력" });
    const b = await waitFor(() => {
      const x = runBtn(container);
      expect(x).toBeTruthy();
      return x;
    });
    expect(b.textContent).toBe(RUN_ALL_LABEL);
    expect(b.disabled).toBe(false);
    // 화면당 주 버튼 1개(단계 버튼) — [일괄 실행]은 data-primary 가 아님
    expect(primaries(container)).toHaveLength(1);
    expect(b.hasAttribute("data-primary")).toBe(false);
    fireEvent.click(b);
    await waitFor(() => expect(runBtn(container).disabled).toBe(true));
    const start = reqs.find((r) => r.method === "POST" && r.path.endsWith("/cases/c-new/run-all"))!;
    expect(start.body).toEqual({});
    expect(reasonOf(runBtn(container))).toBe(RUN_ALL_BUSY_REASON);
    expect(reasonOf(primaries(container)[0])).toBe(RUN_ALL_ACTIVE_REASON);
    expect(RUN_ALL_ACTIVE_REASON).toBe(CODE_TEXT.RUN_ALL_ACTIVE);
    expect(container.querySelector('[data-run-all-step="true"]')!.textContent).toContain("입력");
    expect((await bar()).getAttribute("data-status")).toBe("RUNNING");
    // 체인 RUNNING 중 상태 변경 API → 409 RUN_ALL_ACTIVE (RA-D-7)
    expect(server.handle("POST", "/cases/c-new/jobs", new URLSearchParams(), { job_type: "CASE_EXTRACT", params: {} }).status).toBe(409);
    server.drain();
    await waitFor(() => expect(screen.getByTestId("run-all-bar").getAttribute("data-status")).toBe("DONE"), LONG);
    expect(screen.getByTestId("run-all-bar").textContent).toContain(RUN_ALL_DONE_TEXT);
    expect(within(screen.getByTestId("run-all-bar")).getByRole("link", { name: "④ 검증 열기" }).getAttribute("href")).toBe(`${CNEW}/step/4`);
    // 자동 등록 없음 · ② 자동 확정 기록
    expect(server.entries.some((e) => (e as unknown as { case_id?: string }).case_id === "c-new")).toBe(false);
    expect(server.findCase("c-new")!.tstar!.confirmed?.by).toBe("run_all");
    expect(runBtn(container).disabled).toBe(true);
    expect(reasonOf(runBtn(container))).toBe(RUN_ALL_ALL_DONE_REASON);
    expect(container.querySelector('[data-run-all-step="true"]')).toBeNull();
    expect(server.runAlls[0].job_ids.map((x) => x.step)).toEqual(["input", "esl", "validate"]);
  });

  it("비활성 사유: 권한 없음 / 보관된 Case / 일괄 실행 중 / 모두 완료 PASS", () => {
    const base = { id: "c", status: "ACTIVE", step_status: null, run_all: null } as unknown as Case;
    expect(runAllButton(base, false).disabledReason).toMatch(/실행 권한/);
    expect(runAllButton({ ...base, status: "ARCHIVED" }, true).disabledReason).toBe("보관된 Case 입니다");
    const ra = { status: "RUNNING", can_resume: false, superseded: false } as Case["run_all"];
    expect(runAllButton({ ...base, run_all: ra }, true).disabledReason).toBe(RUN_ALL_BUSY_REASON);
    const done = { state: "done" as const };
    const ss = { input: done, tstar: done, esl: done, validate: done };
    expect(runAllButton({ ...base, step_status: ss, run_all: { ...ra!, status: "DONE", verdict: "PASS" } }, true).disabledReason).toBe(RUN_ALL_ALL_DONE_REASON);
    expect(runAllButton({ ...base, step_status: ss, run_all: null }, true).disabledReason).toBeNull();
    const stopped = { ...ra!, status: "STOPPED" as const, can_resume: true, stop_step: "esl" as const };
    expect(runAllButton({ ...base, run_all: stopped }, true)).toEqual({ label: RESUME_LABEL, from: "esl", disabledReason: null });
  });

  it("조회 사용자: [일괄 실행] 비활성 + 권한 사유", async () => {
    const { container } = mount(`${CNEW}/step/1`, undefined, "general");
    await waitFor(() => expect(runBtn(container)).toBeTruthy());
    await waitFor(() => expect(reasonOf(runBtn(container))).toMatch(/실행 권한/));
    expect(runBtn(container).disabled).toBe(true);
  });
});

describe("진행 줄 멈춤 사유 + [이어서 실행]", () => {
  it("② TSTAR_REVIEW_REQUIRED(TSTAR_ADJUSTED) → '② t*·지지점에서 멈춤', 주 버튼 [이어서 실행] → from=tstar", async () => {
    const { container, reqs, server } = mount(`${CNEW}/step/1`, (s) => {
      s.tstarAdjusted.add("c-new");
      startAndDrain(s);
    });
    const b = await bar();
    expect(b.getAttribute("data-status")).toBe("STOPPED");
    expect(b.textContent).toContain(`② t*·지지점에서 멈춤 — ${CODE_TEXT.TSTAR_REVIEW_REQUIRED}`);
    expect(b.textContent).toContain(CODE_TEXT.TSTAR_ADJUSTED);
    expect(within(b).getByRole("link", { name: "그 단계로 가기" }).getAttribute("href")).toBe(`${CNEW}/step/2`);
    expect(container.querySelector('[data-run-all-step="true"]')!.textContent).toContain("t*·지지점");
    // 멈춘 뒤에는 단계 주 버튼이 다시 살아 있다(사람이 고칠 수 있게)
    expect(reasonOf(primaries(container)[0])).not.toBe(RUN_ALL_ACTIVE_REASON);
    const rb = runBtn(container);
    expect(rb.textContent).toBe(RESUME_LABEL);
    expect(rb.disabled).toBe(false);
    server.tstarAdjusted.delete("c-new"); // 사람이 고침(목: 가드 통과)
    fireEvent.click(rb);
    await waitFor(() => expect(screen.getByTestId("run-all-bar").getAttribute("data-status")).toBe("RUNNING"));
    const resume = reqs.filter((r) => r.method === "POST" && r.path.endsWith("/run-all")).pop()!;
    expect(resume.body).toEqual({ from: "tstar" });
    expect(screen.getByTestId("run-all-bar").textContent).toMatch(/일괄 실행 중 — ③ ESL/);
    expect(server.runAlls[1].resumed_from_id).toBe(server.runAlls[0].id);
  });

  it("② SUPPORT_AUTO_BLOCKED → 기존 문구 + problems", async () => {
    mount(`${CNEW}/step/2`, (s) => {
      s.supportBlocked.add("c-new");
      startAndDrain(s);
    });
    const b = await bar();
    expect(b.textContent).toContain(CODE_TEXT.SUPPORT_AUTO_BLOCKED);
    expect(b.textContent).toMatch(/지지 3점이 거의 한 줄/);
  });

  it("③ 작업 실패 STEP_FAILED → 실패 코드 + [작업 보기]", async () => {
    mount(`${CNEW}/step/3`, (s) => {
      s.failJobTypes.add("ESL_SOLVE");
      startAndDrain(s);
    });
    const b = await bar();
    expect(b.textContent).toMatch(/③ ESL에서 멈춤 — ③ ESL 작업 실패: CORE_FAILED/);
    expect(within(b).getByRole("link", { name: "작업 보기" }).getAttribute("href")).toMatch(/^\/p\/p-body\/jobs\/j-/);
  });

  it("④ VALIDATION_FAIL / VALIDATION_UNDETERMINED → ④에서 멈춤", async () => {
    const { unmount } = mount(`${CNEW}/step/4`, (s) => {
      s.validationVariant.set("c-new", "FAIL");
      startAndDrain(s);
    });
    expect((await bar()).textContent).toContain(`④ 검증에서 멈춤 — ${CODE_TEXT.VALIDATION_FAIL}`);
    unmount();
    mount(`${CNEW}/step/4`, (s) => {
      s.validationVariant.set("c-new", "UNDETERMINED");
      startAndDrain(s);
    });
    expect((await bar()).textContent).toMatch(/④ 검증에서 멈춤 — 검증 판정 불가 — NO_FULL_SOLVE/);
  });
});

describe("[일괄 취소]", () => {
  it("확인 창 1회 → 취소 시 CANCELED(회색), 체인이 만든 작업도 취소 / 확인 창에서 아니오면 그대로", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { server } = mount(`${CNEW}/step/1`, (s) => s.handle("POST", "/cases/c-new/run-all", new URLSearchParams(), {}));
    const b = await bar();
    const jobId = server.runAlls[0].cur_job_id!;
    fireEvent.click(within(b).getByRole("button", { name: "일괄 취소" }));
    expect(confirm).toHaveBeenCalledWith(RUN_ALL_CANCEL_CONFIRM);
    expect(server.runAlls[0].status).toBe("RUNNING");
    fireEvent.click(within(b).getByRole("button", { name: "일괄 취소" }));
    await waitFor(() => expect(screen.getByTestId("run-all-bar").getAttribute("data-status")).toBe("CANCELED"));
    expect(screen.getByTestId("run-all-bar").textContent).toContain(RUN_ALL_CANCELED_TEXT);
    expect(screen.getByTestId("run-all-bar").className).toContain("off");
    expect(server.jobs.find((j) => j.id === jobId)!.state).toBe("CANCELED");
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});

describe("실행 이력 '일괄' 배지·일괄 실행 기록", () => {
  const item = (id: string, run_all_id: string | null): HistoryItem =>
    ({
      id, job_type: "ESL_SOLVE", stage: 4, state: "SUCCEEDED", case_id: "c-new", case_title: "x", case_folder: "x", analysis_id: null, comparison_id: null, subject_title: null,
      created_by: "u", created_by_name: "김민수", created_at: "2026-11-04T01:00:00Z", queued_at: null, started_at: null, finished_at: null, duration_s: 10, wait_s: 0,
      current_step_no: null, progress_pct: null, failure_code: null, failure_message: null, retry_of_job_id: null, retried_by_job_id: null, stale: false, run_all_id,
    }) as HistoryItem;

  it("run_all_id 있는 행에만 배지 '일괄'(title: 실행자)", () => {
    render(
      <MemoryRouter>
        <HistoryTable items={[item("j-1", "ra-1"), item("j-2", null)]} projectId="p-body" showCase={false} />
      </MemoryRouter>,
    );
    const rows = screen.getAllByTestId("history-row");
    expect(within(rows[0]).getByTestId("run-all-badge").textContent).toBe("일괄");
    expect(within(rows[0]).getByTestId("run-all-badge").getAttribute("title")).toContain("김민수");
    expect(within(rows[1]).queryByTestId("run-all-badge")).toBeNull();
  });

  it("Case 실행 이력 위 접힌 '일괄 실행 기록'(펼치면 GET run-all?all=1)", async () => {
    const { reqs } = mount("/p/p-body/c/c-new/history", (s) => {
      s.tstarAdjusted.add("c-new");
      startAndDrain(s);
    });
    const log = await screen.findByTestId("run-all-log");
    expect((log as HTMLDetailsElement).open).toBe(false);
    (log as HTMLDetailsElement).open = true;
    fireEvent(log, new Event("toggle"));
    const row = await screen.findByTestId("run-all-log-row");
    expect(row.textContent).toContain("② t*·지지점 멈춤");
    expect(row.textContent).toContain("① 입력");
    expect(reqs.some((r) => r.path.endsWith("/cases/c-new/run-all?all=1"))).toBe(true);
  });

  it("작업 상세: 일괄 실행으로 생성", async () => {
    // 목 작업 상세는 시드 이력만 — 응답에 run_all_id 를 얹어 본다(백엔드 §8: review.job.run_all_id)
    mount("/p/p-body/jobs/h-esl-old", (s) => {
      const orig = s.history.handle.bind(s.history);
      s.history.handle = (m, p, q) => {
        const r = orig(m, p, q);
        if (r && p.endsWith("/review")) {
          const b = r.body as { job: Record<string, unknown> };
          return { ...r, body: { ...b, job: { ...b.job, run_all_id: "ra-1" }, run_all_id: "ra-1" } };
        }
        return r;
      };
    });
    expect((await screen.findByTestId("run-all-origin")).textContent).toContain("일괄 실행으로 생성");
    expect(screen.getByTestId("run-all-origin").querySelector("[data-testid=run-all-badge]")).toBeTruthy();
  });
});
