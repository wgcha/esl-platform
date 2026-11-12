// V-DEL-18(esl_item_delete.md §7): 목록 삭제 버튼 3상태(–/비활성+툴팁/활성), 확인 문구 개수 반영, 성공·ITEM_DELETED 후 목록 갱신,
// FILE_LOCKED·ITEM_BUSY 문구, 분석 삭제 시 최적화 연결 끊김 안내, 상세 404 → 목록 이동. check:api 는 별도(npm run check:api).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { ApiError } from "../api/client";
import { DELETE_ERROR_TEXT, confirmText, deleteErrorText } from "../components/ItemDeleteButton";
import type { MockServer } from "../mock/server";

const rowOf = (table: HTMLElement, text: string) => within(table).getByText(text).closest("tr") as HTMLElement;
const newJob = (s: MockServer, jt: string, params: Record<string, unknown>) =>
  (s as unknown as { newJob: (c: { id: null; project_id: string }, jt: string, p: Record<string, unknown>) => unknown }).newJob({ id: null, project_id: "p-body" }, jt, params);
const noJobs = (s: MockServer) => {
  s.jobs.forEach((j) => (j.state = "SUCCEEDED"));
  s.verify.drops.forEach((d) => {
    d.phase = "DONE";
    d.submission = null;
  });
};

describe("목록 삭제 — 공용 ItemDeleteButton", () => {
  it("문구: 오류 코드는 한국어, confirmText 는 개수·폴더 앞 8자리, 알 수 없는 코드는 errorText", () => {
    expect(DELETE_ERROR_TEXT.FILE_LOCKED).toMatch(/파일이 열려 있습니다/);
    expect(DELETE_ERROR_TEXT.NOT_ITEM_OWNER).toMatch(/등록자·관리자/);
    expect(deleteErrorText(new ApiError(409, { code: "ITEM_BUSY", message: "x" }))).toMatch(/진행 중인 작업/);
    expect(deleteErrorText(new ApiError(500, { code: "WHATEVER", message: "서버 오류" }))).toBe("서버 오류");
    const t = confirmText({ kind: "DOE", id: "0123456789abcdef", title: "T", can_delete: true, blocked: [], n_jobs: 4, n_verify_drops: 2, n_opt_unlinked: 0, folders: [] });
    expect(t).toContain("'T'을(를) 영구 삭제합니다. 실행 이력 4건·검증 낙하 2건과 esl 작업 폴더(_doe/…01234567)");
    expect(t).toContain("올린 입력 파일·SPDM·SCX 드라이브 파일은 그대로 둡니다");
    expect(confirmText({ kind: "OPT", id: "abcdefgh12", title: "O", can_delete: true, blocked: [], n_jobs: 1, n_verify_drops: 0, n_opt_unlinked: 0, folders: [] })).not.toContain("검증 낙하");
  });

  it("강성 평가 스터디: 등록자 = 활성 버튼 · 타인 = '–' · 진행 중 검증 낙하 = 비활성+사유 툴팁", async () => {
    const { server } = renderApp("/p/p-body/library?tab=study", "power", (s) => {
      s.verify.seedDemo("doe-1");
      s.doe.recs.find((r) => r.out.id === "doe-2")!.out.created_by_name = "다른 사람";
    });
    const tbl = await screen.findByRole("table", { name: "강성 평가 스터디 목록" });
    const busy = within(rowOf(tbl, "75형 Ch/R 비드 1차")).getByRole("button", { name: "삭제" }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    expect(busy.title).toMatch(/진행 중|취소·포기|SCX/);
    const other = rowOf(tbl, "QN80J Ch/R 비드 — 75형 ESL");
    expect(within(other).queryByRole("button", { name: "삭제" })).toBeNull();
    expect(within(other).getByText("–").title).toMatch(/등록자·관리자만/);
    // 관리자는 타인 항목도 삭제 가능(권한 칸이 서버 값을 따른다)
    expect(server.del.flags("DOE", "doe-2").can_delete).toBe(false);
  });

  it("스터디 삭제: delete-check 개수가 확인 문구에, [영구 삭제] → 행 사라짐 + 안내, 입력 취소는 아무 것도 지우지 않음", async () => {
    const { server } = renderApp("/p/p-body/library?tab=study", "power", (s) => {
      s.verify.seedDemo("doe-1");
      noJobs(s);
    });
    const tbl = await screen.findByRole("table", { name: "강성 평가 스터디 목록" });
    const row = rowOf(tbl, "75형 Ch/R 비드 1차");
    fireEvent.click(within(row).getByRole("button", { name: "삭제" }));
    const conf = await within(row).findByTestId("delete-confirm");
    const nDrops = server.verify.drops.filter((d) => d.bead_doe_id === "doe-1").length;
    expect(nDrops).toBeGreaterThan(0);
    expect(conf.textContent).toContain(`검증 낙하 ${nDrops}건`);
    expect(conf.textContent).toMatch(/실행 이력 \d+건/);
    expect(conf.textContent).toContain("_doe/…doe-1");
    fireEvent.click(within(conf).getByRole("button", { name: "취소" }));
    expect(within(row).queryByTestId("delete-confirm")).toBeNull();
    expect(server.del.calls).toEqual([]);
    fireEvent.click(within(row).getByRole("button", { name: "삭제" }));
    fireEvent.click(await within(row).findByRole("button", { name: "영구 삭제" }));
    expect(await screen.findByText("'75형 Ch/R 비드 1차' 삭제됨")).toBeTruthy();
    expect(server.del.calls).toEqual(["DELETE /doe/studies/doe-1"]);
    expect(server.doe.recs.some((r) => r.out.id === "doe-1")).toBe(false);
    expect(server.verify.drops.some((d) => d.bead_doe_id === "doe-1")).toBe(false);
    await waitFor(() => expect(within(screen.getByRole("table", { name: "강성 평가 스터디 목록" })).queryByText("75형 Ch/R 비드 1차")).toBeNull());
  });

  it("비드 최적화: 삭제 성공 · FILE_LOCKED 문구(확인은 유지, 다시 누르면 성공) · ITEM_DELETED = 성공 처리", async () => {
    const { server } = renderApp("/p/p-body/library?tab=opt");
    const tbl = await screen.findByRole("table", { name: "비드 최적화 목록" });
    const row = rowOf(tbl, "75형 강건 비드 1차");
    server.del.lockedNext = true;
    fireEvent.click(within(row).getByRole("button", { name: "삭제" }));
    expect((await within(row).findByTestId("delete-confirm")).textContent).not.toContain("검증 낙하");
    fireEvent.click(within(row).getByRole("button", { name: "영구 삭제" }));
    expect(await within(row).findByText(/파일이 열려 있습니다\(보고서·3D 보기 창을 닫고 다시\)/)).toBeTruthy();
    expect(server.opt.runs.some((r) => r.id === "opt-1")).toBe(true);
    // 그 사이 다른 곳에서 지워짐 → 404 ITEM_DELETED 를 성공으로
    server.opt.runs = [];
    server.del.deleted.add("OPT:opt-1");
    fireEvent.click(within(row).getByRole("button", { name: "영구 삭제" }));
    expect(await screen.findByText("'75형 강건 비드 1차' 삭제됨")).toBeTruthy();
  });

  it("ITEM_BUSY: 확인 뒤 새 작업이 생기면 409 → 확인 없이 사유·작업 링크만, 행은 그대로", async () => {
    const { server } = renderApp("/p/p-body/library?tab=opt");
    const tbl = await screen.findByRole("table", { name: "비드 최적화 목록" });
    const row = rowOf(tbl, "75형 강건 비드 1차");
    fireEvent.click(within(row).getByRole("button", { name: "삭제" }));
    const conf = await within(row).findByTestId("delete-confirm");
    newJob(server, "OPT_RUN", { opt_run_id: "opt-1" }); // 경합: 확인하는 사이 새 작업이 들어옴
    fireEvent.click(within(conf).getByRole("button", { name: "영구 삭제" }));
    const blk = await within(row).findByTestId("delete-blocked");
    expect(blk.textContent).toMatch(/진행 중인 작업이 있습니다/);
    expect(within(blk).getByRole("link", { name: "작업 보기" }).getAttribute("href")).toMatch(/^\/p\/p-body\/jobs\//);
    expect(within(blk).queryByRole("button", { name: "영구 삭제" })).toBeNull();
    expect(server.opt.runs.some((r) => r.id === "opt-1")).toBe(true);
  });

  it("종합분석: 연결된 비드 최적화는 남고 연결만 끊김(안내·n_opt_unlinked), 버전 비교 삭제", async () => {
    const { server } = renderApp("/p/p-body/library?tab=analyses", "power", (s) => {
      s.opt.runs[0].analysis_id = "an-1";
    });
    const at = await screen.findByRole("table", { name: "종합분석 목록" });
    const arow = rowOf(at, "QN80H 꼭지점·모서리 강건 비드");
    fireEvent.click(within(arow).getByRole("button", { name: "삭제" }));
    const conf = await within(arow).findByTestId("delete-confirm");
    expect(conf.textContent).toContain("비드 최적화 1건은 남고 연결만 끊깁니다");
    expect(conf.textContent).toContain("_analysis/…an-1");
    fireEvent.click(within(conf).getByRole("button", { name: "영구 삭제" }));
    expect(await screen.findByText("'QN80H 꼭지점·모서리 강건 비드' 삭제됨")).toBeTruthy();
    expect(server.opt.runs.length).toBe(1);
    expect(server.opt.runs[0].analysis_id).toBeNull();
    // 버전 비교
    const ct = await screen.findByRole("table", { name: "버전 비교 목록" });
    const crow = rowOf(ct, "비드 1차 반영 검증");
    fireEvent.click(within(crow).getByRole("button", { name: "삭제" }));
    const c2 = await within(crow).findByTestId("delete-confirm");
    expect(c2.textContent).toContain("_compare/…cmp-1");
    expect(c2.textContent).not.toContain("연결만 끊깁니다");
    fireEvent.click(within(c2).getByRole("button", { name: "영구 삭제" }));
    await waitFor(() => expect(server.comparisons.length).toBe(0));
    expect(server.del.calls).toEqual(["DELETE /library/analyses/an-1", "DELETE /library/comparisons/cmp-1"]);
  });

  it("차단: 진행 중 작업이 있으면 행 버튼 비활성 + 사유 툴팁", async () => {
    const { server } = renderApp("/p/p-body/library?tab=analyses", "power", (s) => {
      newJob(s, "LIB_COMPARE", { comparison_id: "cmp-1" });
    });
    const ct = await screen.findByRole("table", { name: "버전 비교 목록" });
    const btn = within(rowOf(ct, "비드 1차 반영 검증")).getByRole("button", { name: "삭제" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toMatch(/진행 중인 작업/);
    expect(server.del.flags("COMPARE", "cmp-1").delete_blocked).toBeTruthy();
  });

  it("상세 화면에서 항목이 없어졌으면(404) 해당 목록 탭으로 이동", async () => {
    renderApp("/p/p-body/opt/opt-1", "power", (s) => {
      s.opt.runs = [];
    });
    expect(await screen.findByText(/아직 비드 최적화가 없습니다/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: "비드 최적화", selected: true })).toBeTruthy();
  });
});
