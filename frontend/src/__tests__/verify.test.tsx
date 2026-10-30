// v0.12.0 Radioss 검증 낙하(계약 esl_scx_relay.md §7·§9.3·§10.2·V-SR-15(B)): 목 계약(씬 선택 worst/all·상한·누적 씬 제외·②③·best 없는 안·
// 작업 연결 VERIFY_DROP(XFER) → VERIFY_POST(SLOT)·결과 모름 정리), 화면 규칙(버튼 비활성 사유·안 목록·진행 칸), [검증 낙하] → 계획 대화상자 →
// 제출 → 카드(진행·SCX 잡 ID·취소 확인) → 완료 비교 표(PASS/FAIL 없음·CSV), UNKNOWN [잡 ID 연결]·[포기]. 주 버튼은 화면당 1개.
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import { MockServer } from "../mock/server";
import { VD_ABANDON_CONFIRM, VD_CANCEL_CONFIRM, eligibleDesigns, stageMarks, verifyButtonReason } from "../api/verify";
import { JOB_STEP_KEYS, JOB_TYPE_LABEL } from "../api/history";
import { GUIDE } from "../pages/guide/content";
import type { DoeResultOut, VerifyDropCreateOut, VerifyDropOut, VerifyPlanOut } from "../api/types";

vi.setConfig({ testTimeout: 30000 });
const STUDY = "/p/p-body/doe/doe-1";
const LONG = { timeout: 8000 };
const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const post = (s: MockServer, path: string, b: Record<string, unknown>) => s.handle("POST", `/esl/api${path}`, new URLSearchParams(), b);
const get = (s: MockServer, path: string, q: Record<string, string> = {}) => s.handle("GET", `/esl/api${path}`, new URLSearchParams(q), null);
const bestOf = (s: MockServer) => s.doe.recs.find((r) => r.out.id === "doe-1")!.result!.best!.id;

describe("검증 낙하 — 목 서버 계약", () => {
  it("plan: 스키마 키·worst(r 큰 순, N)·all·누적 씬 제외·best 없는 안·②③·상한", () => {
    const s = new MockServer({ user: "power" });
    const best = bestOf(s);
    const p = post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "worst" });
    expect(p.status).toBe(200);
    const plan = p.body as VerifyPlanOut;
    // 서버 VerifyPlanOut 키(openapi required 전부)
    expect(Object.keys(plan).sort()).toEqual(["default_n", "default_worst_n", "design_id", "designs", "est_hours", "excluded", "hpc", "hpc_default", "max_scenes", "mode", "n_submit", "scenes"]);
    expect([plan.design_id, plan.mode, plan.default_worst_n, plan.hpc]).toEqual([best, "worst", 3, { version: "26.1", ncpu: 16 }]);
    expect(Object.keys(plan.excluded[0]).sort()).toEqual(["case_id", "case_title", "code", "entry_id", "reason"]);
    expect(plan.excluded.map((x) => [x.case_id, x.code])).toEqual([["c-lib-2", "VD_CUMULATIVE_EXCLUDED"]]);
    expect(plan.scenes.length).toBe(plan.n_submit);
    const r = plan.scenes.map((x) => x.r_c ?? 0);
    expect([...r].sort((a, b) => b - a)).toEqual(r); // 가장 나쁜(큰 r) 먼저
    expect(Object.keys(plan.scenes[0]).sort()).toEqual(["case_id", "case_title", "entry_id", "label", "r_c", "r_epsmax", "r_umax"]);
    expect(plan.designs.map((d) => d.rank)).toEqual([1, 2, 3]);
    const one = post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "worst", n: 1 }).body as VerifyPlanOut;
    expect(one.n_submit).toBe(1);
    expect(one.scenes[0].case_id).toBe(plan.scenes[0].case_id);
    expect((post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "all" }).body as VerifyPlanOut).n_submit).toBe(plan.scenes.length);
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "worst", n: 6 }).body).toMatchObject({ detail: { code: "VD_TOO_MANY_SCENES" } });
    const r4 = s.doe.recs[0].result!.ranking.find((x) => x.rank === 4)!.id;
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: r4, mode: "worst" }).body).toMatchObject({ detail: { code: "VD_DESIGN_NO_FILES" } });
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "nope", design_id: best, mode: "worst" }).status).toBe(404);
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-2", design_id: best, mode: "worst" }).body).toMatchObject({ detail: { code: "VD_SCENARIO_UNSUPPORTED" } });
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "worst", hpc: { ncpu: 0 } }).body).toMatchObject({ detail: { code: "INVALID_PARAMS" } });
    // 원 Case 추출 결과 없음 → 씬별 제외 VD_CASE_NOT_READY(오류 아님)
    s.verify.notReadyCases = new Set(["c-demo"]);
    const nr = post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "all" }).body as VerifyPlanOut;
    expect(nr.excluded.map((x) => x.code).sort()).toEqual(["VD_CASE_NOT_READY", "VD_CUMULATIVE_EXCLUDED"]);
    expect(nr.scenes.some((x) => x.case_id === "c-demo")).toBe(false);
    s.verify.notReadyCases = new Set();
    s.verify.stateCases = new Set(["c-demo", "c-lib-2", "c-lib-3"]);
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "worst" })).toMatchObject({ status: 409, body: { detail: { code: "VD_NO_SCENES" } } });
    s.scx.verifyMode = "disabled";
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "worst" })).toMatchObject({ status: 503, body: { detail: { code: "SCX_UNAVAILABLE", reason_code: "VD_DISABLED" } } });
    // /scx/status.verify 가 같은 판정
    expect((get(s, "/scx/status", { project_id: "p-body" }).body as { verify: { reason_code: string } }).verify.reason_code).toBe("VD_DISABLED");
  });

  it("create: 씬마다 행 + VERIFY_DROP(XFER) → 끝나면 VERIFY_POST(SLOT) → DONE 비교(PASS/FAIL 없음)·CSV, 같은 안·씬 진행 중이면 제외", () => {
    const s = new MockServer({ user: "power" });
    const best = bestOf(s);
    const c = post(s, "/verify-drops", { bead_doe_id: "doe-1", design_id: best, mode: "all" });
    expect(c.status).toBe(201);
    const out = c.body as VerifyDropCreateOut;
    expect(out.drops.length).toBe(2);
    expect(out.drops[0]).toMatchObject({ project_id: "p-body", case_title: expect.any(String), job: { job_type: "VERIFY_DROP", verify_drop_id: out.drops[0].id } });
    expect(out.drops.every((d) => d.batch_id === out.batch_id && d.phase === "PREP" && d.predicted)).toBe(true);
    const j = s.jobs.find((x) => x.id === out.drops[0].job_ids[0])!;
    expect([j.job_type, j.lane]).toEqual(["VERIFY_DROP", "XFER"]);
    expect(j.steps!.map((x) => x.step_key)).toEqual(JOB_STEP_KEYS.VERIFY_DROP);
    // 진행 중 같은 안·씬 → 제외(VD_ALREADY_ACTIVE) → 0개면 409
    expect(post(s, "/verify-drops/plan", { bead_doe_id: "doe-1", design_id: best, mode: "all" }).body).toMatchObject({ detail: { code: "VD_NO_SCENES" } });
    s.drain();
    const list = get(s, "/verify-drops", { bead_doe_id: "doe-1" }).body as VerifyDropOut[];
    expect(list.map((d) => d.phase)).toEqual(["DONE", "DONE"]);
    const d = list[0];
    expect(d.scx_job_id).toMatch(/^SCX-/);
    expect(d.submission).toMatchObject({ state: "SUBMITTED", attempt: 1, error_code: null, error_message: null });
    const post2 = s.jobs.find((x) => x.id === d.job_ids[1])!;
    expect([post2.job_type, post2.lane]).toEqual(["VERIFY_POST", "SLOT"]);
    expect(d.result!.rows.map((r) => r.key)).toEqual(["eps_peak", "eps_hot", "disp_peak", "eps_tstar", "disp_tstar"]);
    expect(d.result!.rows.every((r) => ["better", "worse", "same"].includes(r.verdict))).toBe(true);
    expect(JSON.stringify(d.result)).not.toMatch(/PASS|FAIL/);
    expect(String(get(s, `/verify-drops/${d.id}/compare.csv`).body)).toMatch(/^key,label,orig,verify,ratio,predicted,verdict,agree\neps_peak,/);
  });

  it("결과 모름: 작업 FAILED SCX_SUBMISSION_UNKNOWN · 재시도 409 · attach(없는 ID 404) · abandon → 새 attempt 재시도", () => {
    const s = new MockServer({ user: "power" });
    s.verify.unknownNext = true;
    const c = post(s, "/verify-drops", { bead_doe_id: "doe-1", design_id: bestOf(s), mode: "worst", n: 1 }).body as { drops: VerifyDropOut[] };
    s.drain();
    let d = get(s, `/verify-drops/${c.drops[0].id}`).body as VerifyDropOut;
    expect([d.phase, d.submission!.state, d.submission!.error_code]).toEqual(["FAILED", "UNKNOWN", "SCX_SUBMISSION_UNKNOWN"]);
    expect(d.submission!.request_id).toBe(`esl-vd-${d.id}-a1`);
    const j = s.jobs.find((x) => x.id === d.job_ids[0])!;
    expect(j.failure_code).toBe("SCX_SUBMISSION_UNKNOWN");
    expect(post(s, `/jobs/${j.id}/retry`, {}).body).toMatchObject({ detail: { code: "SCX_SUBMISSION_UNKNOWN" } });
    expect(post(s, `/verify-drops/${d.id}/resolve`, { version: d.version, action: "attach", scx_job_id: "SCX-NOPE" }).status).toBe(404);
    expect(post(s, `/verify-drops/${d.id}/resolve`, { version: d.version - 1, action: "abandon" }).body).toMatchObject({ detail: { code: "VERSION_CONFLICT" } });
    d = post(s, `/verify-drops/${d.id}/resolve`, { version: d.version, action: "abandon" }).body as VerifyDropOut;
    expect(d.submission!.state).toBe("ABANDONED");
    expect(post(s, `/verify-drops/${d.id}/resolve`, { version: d.version, action: "abandon" }).body).toMatchObject({ detail: { code: "VD_NOT_UNKNOWN" } });
    expect(post(s, `/jobs/${j.id}/retry`, {}).status).toBe(201);
    s.drain();
    d = get(s, `/verify-drops/${d.id}`).body as VerifyDropOut;
    expect(d.phase).toBe("DONE");
    expect(d.submission!.request_id).toBe(`esl-vd-${d.id}-a2`);
    expect(d.submission!.attempt).toBe(2);
  });

  it("결과 모름 → 잡 ID 연결(link = attach): 서버가 VD_WAIT 부터 새 작업 자동 큐 — 재시도 없이 DONE", () => {
    const s = new MockServer({ user: "power" });
    s.verify.unknownNext = true;
    const c = post(s, "/verify-drops", { bead_doe_id: "doe-1", design_id: bestOf(s), mode: "worst", n: 1 }).body as VerifyDropCreateOut;
    s.drain();
    let d = get(s, `/verify-drops/${c.drops[0].id}`).body as VerifyDropOut;
    expect(d.submission!.state).toBe("UNKNOWN");
    d = post(s, `/verify-drops/${d.id}/resolve`, { version: d.version, action: "link", scx_job_id: "SCX-26-4410" }).body as VerifyDropOut;
    expect([d.phase, d.submission!.state, d.scx_job_id, d.job_ids.length]).toEqual(["SUBMITTED", "ATTACHED", "SCX-26-4410", 2]);
    const nj = s.jobs.find((x) => x.id === d.job_ids[1])!;
    expect([nj.job_type, nj.state, nj.resume_from_step, nj.retry_of_job_id]).toEqual(["VERIFY_DROP", "QUEUED", 4, d.job_ids[0]]);
    s.drain();
    d = get(s, `/verify-drops/${d.id}`).body as VerifyDropOut;
    expect([d.phase, d.scx_job_id]).toEqual(["DONE", "SCX-26-4410"]);
  });
});

describe("검증 낙하 — 화면 규칙", () => {
  const result = { best: { id: "d024", files: [] }, ranking: [{ id: "d024", rank: 1 }] } as unknown as DoeResultOut;
  const base = {
    allowed: true, noPermission: "권한 없음", study: { scenario: "same" as const, phase: "DONE" as const }, result, avail: { enabled: true, reason_code: null, reason: null },
    availError: null, designs: [{ id: "d024", rank: 1 }, { id: "d027", rank: 2 }], pick: null, planError: null, isAdmin: false,
  };
  it("버튼 비활성 사유: 권한·②③·SCX 사유(일반 사용자는 짧게)·best 없음·순위 밖 안·누적 씬뿐", () => {
    expect(verifyButtonReason(base)).toBeNull();
    expect(verifyButtonReason({ ...base, allowed: false })).toBe("권한 없음");
    expect(verifyButtonReason({ ...base, study: { scenario: "mesh", phase: "DONE" } })).toMatch(/① 같은 모델 스터디만/);
    const off = { enabled: false, reason_code: "SCX_WRITES_OFF", reason: "대시보드 드라이브 쓰기가 꺼져 있습니다(SIMDASH_DRIVE_WRITES_ENABLED) — 검증 낙하만 불가" };
    expect(verifyButtonReason({ ...base, avail: off })).toBe("대시보드 드라이브 쓰기가 꺼져 있습니다");
    expect(verifyButtonReason({ ...base, avail: off, isAdmin: true })).toMatch(/SIMDASH_DRIVE_WRITES_ENABLED/);
    expect(verifyButtonReason({ ...base, designs: [] })).toMatch(/best\//);
    expect(verifyButtonReason({ ...base, pick: "d010" })).toBe("선택한 안 d010 은 모핑 사본이 없습니다 — 순위 1~2 안만 검증할 수 있습니다");
    expect(verifyButtonReason({ ...base, pick: "d027" })).toBeNull();
    expect(verifyButtonReason({ ...base, planError: { code: "VD_NO_SCENES", message: "검증 낙하할 씬이 없습니다" } })).toBe("검증 낙하할 씬이 없습니다");
  });
  it("안 목록: 서버 designs(순위 순), 없으면 결과 best 1개 · 진행 칸 표시 · 라벨", () => {
    expect(eligibleDesigns(result, { designs: [{ id: "b", rank: 2 }, { id: "a", rank: 1 }] }).map((d) => d.id)).toEqual(["a", "b"]);
    expect(eligibleDesigns(result, null)).toEqual([{ id: "d024", rank: 1 }]);
    expect(eligibleDesigns(null, null)).toEqual([]);
    expect(stageMarks("RUNNING")).toEqual(["done", "done", "cur", "todo", "todo"]);
    expect(stageMarks("DONE")).toEqual(["done", "done", "done", "done", "done"]);
    expect(stageMarks("FAILED", 1)).toEqual(["done", "fail", "todo", "todo", "todo"]);
    expect(JOB_TYPE_LABEL.VERIFY_DROP).toBeTruthy();
    expect(GUIDE.flatMap((g) => g.cards).some((c) => c.id === "verify-drop")).toBe(true);
  });
});

describe("검증 낙하 — 화면", () => {
  it("[검증 낙하] → 대화상자(안·씬 라디오·N·씬 표·제외 경고·건수·상한·고급) → 제출 → 카드 진행 → 완료 비교 표·CSV", async () => {
    const { container, server } = renderApp(STUDY);
    await screen.findByRole("table", { name: "순위표" });
    const open = (await screen.findByTestId("vd-open")) as HTMLButtonElement;
    await waitFor(() => expect(open.disabled).toBe(false), LONG);
    expect(primaries(container).map((b) => b.textContent)).toEqual(["보고서 보기"]);
    fireEvent.click(open);
    const dlg = await screen.findByRole("dialog", { name: /검증 낙하/ });
    // 안 목록 = 순위 1~keep_files_top
    const sel = within(dlg).getByRole("combobox", { name: "검증 안" }) as HTMLSelectElement;
    expect([...sel.options].map((o) => o.textContent)).toEqual([1, 2, 3].map((k) => expect.stringContaining(`순위 ${k}`)) as unknown as string[]);
    expect((within(dlg).getByRole("radio", { name: /가장 나쁜 씬/ }) as HTMLInputElement).checked).toBe(true);
    expect((within(dlg).getByRole("textbox", { name: "N" }) as HTMLInputElement).value).toBe("3");
    const scenes = within(dlg).getByRole("table", { name: "검증 씬" });
    await waitFor(() => expect(within(scenes).getAllByRole("row").length).toBe(3), LONG); // 머리 + 2씬
    expect(within(dlg).getByTestId("vd-excluded").textContent).toMatch(/75QN80H Edge 14 — 이전 런 상태를 쓰는 누적 씬/);
    expect(within(dlg).getByTestId("vd-summary").textContent).toBe("제출 2건 · 예상 씬당 약 3시간 · 상한 5건");
    // N 검사(상한)
    fireEvent.change(within(dlg).getByRole("textbox", { name: "N" }), { target: { value: "9" } });
    const start = within(dlg).getByTestId("vd-start") as HTMLButtonElement;
    await waitFor(() => expect(start.disabled).toBe(true));
    expect(start.closest(".primary-wrap")!.getAttribute("title")).toBe("N 은 최대 5입니다");
    fireEvent.change(within(dlg).getByRole("textbox", { name: "N" }), { target: { value: "1" } });
    await waitFor(() => expect(within(dlg).getByTestId("vd-summary").textContent).toMatch(/^제출 1건/), LONG);
    fireEvent.click(within(dlg).getByRole("radio", { name: "고른 ESL 전부" }));
    await waitFor(() => expect(within(dlg).getByTestId("vd-summary").textContent).toMatch(/^제출 2건/), LONG);
    // 고급(Radioss 버전·ncpu 자리표시 = 설정값)
    expect((within(dlg).getByRole("textbox", { name: "Radioss 버전" }) as HTMLInputElement).placeholder).toBe("26.1");
    fireEvent.change(within(dlg).getByRole("textbox", { name: "ncpu" }), { target: { value: "32" } });
    expect(primaries(container).length).toBe(2); // 페이지 주 버튼 + 대화상자 주 버튼(모달)
    await waitFor(() => expect(start.disabled).toBe(false), LONG);
    fireEvent.click(start);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), LONG);
    expect(server.verify.lastCreateIn).toMatchObject({ bead_doe_id: "doe-1", mode: "all", hpc: { ncpu: 32 } });
    // 카드: 씬 2행, 진행 칸
    const card = await screen.findByTestId("vd-card", {}, LONG);
    await waitFor(() => expect(within(card).getAllByRole("table", { name: "검증 낙하 씬" })[0].querySelectorAll("tbody tr").length).toBe(2), LONG);
    expect(within(card).getAllByRole("list", { name: "검증 낙하 단계" })[0].textContent).toBe("업로드대기실행회수비교");
    // 실행 중(SCX 잡 있음) → 취소는 확인 창
    act(() => {
      for (let k = 0; k < 6; k++) server.tick();
    });
    await waitFor(() => expect(card.textContent).toMatch(/SCX-26-\d+/), LONG);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const detail = within(card).getByTestId("vd-detail");
    fireEvent.click(await within(detail).findByRole("button", { name: "취소" }, LONG));
    expect(confirm).toHaveBeenCalledWith(VD_CANCEL_CONFIRM);
    confirm.mockRestore();
    // 완료 → 비교 표
    act(() => server.drain());
    const cmp = await screen.findByRole("table", { name: "원 낙하 대비 검증 낙하" }, { timeout: 10000 });
    expect(within(cmp).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["지표", "원 낙하", "검증 낙하", "비", "ESL 선형 예측 비", "판단", "예측 방향"]);
    expect(cmp.textContent).toMatch(/개선|악화|비슷/);
    expect(cmp.textContent).toMatch(/일치/);
    expect(card.textContent).not.toMatch(/PASS|FAIL|합격(?! 판정)/);
    expect(within(card).getByRole("button", { name: "CSV 받기" })).toBeTruthy();
    expect(within(card).getByTestId("vd-drive-dir").textContent).toMatch(/^\/Users\/vd\.dashboard\/esl\//);
  });

  it("결과 모름 행: 사유 + [잡 ID 연결]·[포기](확인 창), 연결하면 서버가 자동 재큐잉(재시도 버튼 없음)", async () => {
    const { server } = renderApp(STUDY, "power", (s) => s.verify.seedDemo("doe-1"));
    const box = await screen.findByTestId("vd-unknown", {}, LONG);
    expect(box.textContent).toMatch(/제출 결과를 알 수 없습니다/);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(within(box).getByRole("button", { name: "포기" }));
    expect(confirm).toHaveBeenCalledWith(VD_ABANDON_CONFIRM);
    confirm.mockRestore();
    const attach = within(box).getByRole("button", { name: "잡 ID 연결" }) as HTMLButtonElement;
    expect(attach.disabled).toBe(true);
    fireEvent.change(within(box).getByRole("textbox", { name: "SCX 잡 ID" }), { target: { value: "SCX-26-4410" } });
    fireEvent.click(attach);
    await waitFor(() => expect(screen.queryByTestId("vd-unknown")).toBeNull(), LONG);
    expect(screen.getByTestId("vd-card").textContent).toMatch(/SCX-26-4410/);
    // 연결 = 새 VERIFY_DROP 작업이 이미 큐(VD_WAIT 부터) — 화면은 [재시도]를 요구하지 않는다
    const d = server.verify.drops.find((x) => x.scx_job_id === "SCX-26-4410")!;
    const js = server.jobs.filter((j) => j.params.verify_drop_id === d.id);
    expect(js[js.length - 1]).toMatchObject({ job_type: "VERIFY_DROP", state: "QUEUED", resume_from_step: 4 });
    const detail = screen.getByTestId("vd-detail");
    await waitFor(() => expect(within(detail).queryByRole("button", { name: "재시도" })).toBeNull(), LONG);
    expect(detail.textContent).not.toMatch(/재시도/);
  });

  it("비활성: 대시보드 드라이브 쓰기 꺼짐 사유(일반 사용자는 짧게)", async () => {
    renderApp(STUDY, "power", (s) => (s.scx.verifyMode = "writes_off"));
    const open = (await screen.findByTestId("vd-open")) as HTMLButtonElement;
    await waitFor(() => expect(open.closest(".primary-wrap")!.getAttribute("title")).toBe("대시보드 드라이브 쓰기가 꺼져 있습니다"), LONG);
    expect(open.disabled).toBe(true);
  });

  it("순위 4위 안 선택 → 비활성 사유(순위 1~3 안만)", async () => {
    renderApp(STUDY);
    const t = await screen.findByRole("table", { name: "순위표" });
    const open = (await screen.findByTestId("vd-open")) as HTMLButtonElement;
    await waitFor(() => expect(open.disabled).toBe(false), LONG);
    const row4 = within(t).getAllByRole("row").find((r) => /^4d\d{3}/.test(r.textContent ?? ""))!;
    fireEvent.click(row4);
    await waitFor(() => expect(open.closest(".primary-wrap")!.getAttribute("title")).toMatch(/모핑 사본이 없습니다 — 순위 1~3 안만/), LONG);
  });

  it("조회(general): 버튼 비활성(권한 사유), 카드는 보임", async () => {
    renderApp(STUDY, "general", (s) => s.verify.seedDemo("doe-1"));
    const open = (await screen.findByTestId("vd-open")) as HTMLButtonElement;
    await waitFor(() => expect(open.disabled).toBe(true));
    expect(await screen.findByTestId("vd-card", {}, LONG)).toBeTruthy();
  });
});
