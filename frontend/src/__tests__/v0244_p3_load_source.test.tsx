// V-0244-JIG-14(esl_jig_case.md §9) C3 프런트: 하중 출처 선택(스터디·비드 최적화 생성 화면) · ④ 판정 표식 · 선택 불가+사유 ·
// 서버 422 확인 요청 → 확인 대화 → load_source_ack 재요청 · 안 고르면 필드 생략 · 결과 칩. 백엔드는 목(형식 = 계약 P3 절 가정).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LS_SRC from "../view3d/loadSource.ts?raw";
import { ApiError } from "../api/client";
import { LoadSourceChip, LoadSourceConfirmDialog } from "../components/LoadSourcePicker";
import { loadSourceBody, loadSourceChipOf, loadSourceErrorText, loadSourceOptions, unconfirmedOf } from "../view3d/loadSource";
import { renderApp } from "../test/render";
import type { EntrySourceRow, EntrySourcesItem } from "../api/types";
import type { MockServer } from "../mock/server";

// B3 실제 형식: ④ 출처 행 + load_available·load_code·load_reason·grade·flags
const blank = (key: string): EntrySourceRow => ({ load_available: true, load_code: null, load_reason: null, grade: "NO_RESULT", flags: ["NO_RESULT"], key, available: false, code: null, reason: null, status: null, fail_reasons: [], undetermined_reason: null, reaction_role: null, reaction_tol: null, reaction_tol_key: null, reaction_warn: null, reaction_warned: null, cond_text: null, note: null, limits: [], limit_text: [], comparable: null });
const pass = (key: string, o: Partial<EntrySourceRow> = {}): EntrySourceRow => ({ ...blank(key), available: true, status: "PASS", comparable: true, grade: "PASS", flags: ["PASS"], ...o });
const rowsOk = (): EntrySourceRow[] => [
  pass("jig"),
  pass("jig_disp", { limits: ["JIG_DISP_FROM_TARGET"], limit_text: ["tie 변위 강제"] }),
  { ...blank("jig_spring"), code: "JIG_NOT_RUN", reason: "이 ESL 결과에는 지그 스프링 계산이 없습니다", load_available: false, load_code: "JIG_NOT_RUN", load_reason: "이 ESL 결과에는 지그 스프링 계산이 없습니다" },
  pass("full"),
  pass("bforce", { status: "FAIL", comparable: false, limits: ["BF_TIE_MISSING"], grade: "FAIL", flags: ["FAIL", "not_comparable"] }),
  { ...blank("fint"), code: "VAL_SRC_NOT_RUN", reason: "검증 전" },
];
const item = (id: string, rows = rowsOk()): EntrySourcesItem => ({ entry_id: id, validation_id: `v-${id}`, rows });
const byKey = (o: ReturnType<typeof loadSourceOptions>) => Object.fromEntries(o.map((x) => [x.key, x]));

describe("출처 옵션(순수)", () => {
  it("④ 표식 재사용: PASS · PASS ⚠ · FAIL · 비교용 아님 · 검증 전, 경고 필요 표시", () => {
    const o = byKey(loadSourceOptions([item("a")], "doe"));
    expect(o.full.mark).toEqual({ text: "PASS", tone: "ok" });
    expect(o.full.warn).toBe(false);
    expect(o.full.text).toBe("전 노드 ESL · PASS");
    expect(o.jig_disp.mark!.text).toBe("PASS ⚠");
    expect(o.jig_disp.warn).toBe(true);
    expect(o.bforce.mark).toEqual({ text: "FAIL · 비교용 아님", tone: "warn" });
    expect(o.bforce.warn).toBe(true);
    expect(o.fint.mark).toEqual({ text: "검증 전", tone: "muted" });
    expect(o.fint.disabled).toBe(false);
  });
  it("하중 없음 = 선택 불가 + 사유(항목 수 표시)", () => {
    const o = byKey(loadSourceOptions([item("a"), item("b")], "doe"));
    expect(o.jig_spring.disabled).toBe(true);
    expect(o.jig_spring.why).toBe("지그 스프링 불가 — 이 ESL 결과에는 지그 스프링 계산이 없습니다 외 1개 항목");
    expect(o.jig_spring.text).toBe("지그 스프링 — 선택 불가: 이 ESL 결과에는 지그 스프링 계산이 없습니다 외 1개 항목");
  });
  it("여러 항목 = 최악 표식, 한 항목이라도 하중 없으면 불가", () => {
    const worse = rowsOk().map((r) => (r.key === "full" ? pass("full", { status: "FAIL" }) : r));
    const o = byKey(loadSourceOptions([item("a"), item("b", worse)], "doe"));
    expect(o.full.mark!.text).toBe("FAIL");
    const gone = rowsOk().map((r) => (r.key === "full" ? { ...blank("full"), code: "NO_LOAD", reason: "하중 파일 없음", load_available: false, load_code: "NO_LOAD", load_reason: "하중 파일 없음" } : r));
    const o2 = byKey(loadSourceOptions([item("a"), item("b", gone)], "doe"));
    expect(o2.full.disabled).toBe(true);
    expect(o2.full.why).toContain("하중 파일 없음");
  });
  it("비드 최적화: 지그 변위·스프링 = 열(optUnsupported) 사유로 선택 불가, 스터디는 가능", () => {
    const o = byKey(loadSourceOptions([item("a", rowsOk().map((r) => (r.key === "jig_spring" ? pass("jig_spring") : r)))], "opt"));
    expect(o.jig_disp.disabled).toBe(true);
    expect(o.jig_disp.why).toContain("지그 고정(병진 고정)만 지원");
    expect(o.jig_spring.disabled).toBe(true);
    expect(o.jig.disabled).toBe(false);
    expect(o.full.disabled).toBe(false);
    expect(byKey(loadSourceOptions([item("a", rowsOk().map((r) => (r.key === "jig_spring" ? pass("jig_spring") : r)))], "doe")).jig_spring.disabled).toBe(false);
  });
  it("판정 정보 없음(null) = 표식 없이 모두 선택 가능, optional 행은 응답에 없으면 숨김", () => {
    const all = loadSourceOptions(null, "doe");
    expect(all.every((x) => !x.disabled && !x.mark)).toBe(true);
    const old = loadSourceOptions([item("a", rowsOk().filter((r) => !r.key.startsWith("jig_")))], "doe");
    expect(old.map((x) => x.key)).toEqual(["jig", "full", "bforce", "fint"]);
  });
  it("출처 이름 분기 없음(소스에 키 리터럴 없음) · 요청 칸: 안 고르면 {} · ack 는 재요청에만", () => {
    expect(LS_SRC).not.toMatch(/["'`](jig|jig_disp|jig_spring|full|bforce|fint)["'`]/);
    expect(loadSourceBody("")).toEqual({});
    expect(loadSourceBody("", true)).toEqual({});
    expect(loadSourceBody("full")).toEqual({ load_source: "full" });
    expect(loadSourceBody("full", true)).toEqual({ load_source: "full", load_source_ack: true });
  });
  it("422 본문 해석 · 오류 문구 · 결과 칩", () => {
    const uc = new ApiError(422, { code: "LOAD_SOURCE_UNCONFIRMED", message: "확인 필요", entries: [{ entry_id: "a", status: "FAIL", comparable: false, grade: "FAIL", flags: ["FAIL", "not_comparable"], limits: [] }], worst: "FAIL" });
    expect(unconfirmedOf(uc)).toEqual({ entries: [{ entry_id: "a", status: "FAIL", comparable: false, grade: "FAIL", flags: ["FAIL", "not_comparable"], limits: [] }], worst: "FAIL" });
    expect(unconfirmedOf(new ApiError(422, { code: "X", message: "m" }))).toBeNull();
    expect(loadSourceErrorText(new ApiError(422, { code: "LOAD_SOURCE_UNAVAILABLE", message: "m", entry_ids: ["a"], reasons: { a: "하중 없음" } }))).toBe("하중 출처를 쓸 수 없습니다 — 하중 없음 (항목 a)");
    expect(loadSourceErrorText(new ApiError(422, { code: "LOAD_SOURCE_UNSUPPORTED", message: "m", reason: "spring 은 후속" }))).toContain("spring 은 후속");
    expect(loadSourceErrorText(new ApiError(500, { code: "X", message: "m" }))).toBeNull();
    const chip = loadSourceChipOf("bforce", { key: "bforce", worst: "FAIL", entries: [{ entry_id: "a", status: "PASS", comparable: true, validation_id: null }, { entry_id: "b", status: "FAIL", comparable: false, validation_id: "v" }] });
    expect(chip!.text).toBe("하중 출처 경계력 ESL · FAIL · 비교용 아님");
    expect(chip!.short).toBe("경계력 ESL · FAIL · 비교용 아님");
    expect(chip!.tone).toBe("warn");
    expect(loadSourceChipOf(null, null)).toBeNull();
    expect(loadSourceChipOf("full", null)!.text).toBe("하중 출처 전 노드 ESL");
  });
});

describe("확인 대화·칩(부품)", () => {
  it("항목별 판정 목록 · 취소 / 확인하고 계속", () => {
    let ok = 0, no = 0;
    render(<LoadSourceConfirmDialog sourceKey="bforce" detail={{ worst: "FAIL", entries: [{ entry_id: "le-1", status: "FAIL", comparable: false }, { entry_id: "le-2", status: "PASS", comparable: true }] }} busy={false} onConfirm={() => ok++} onCancel={() => no++} />);
    const d = screen.getByRole("alertdialog");
    expect(d.textContent).toContain("경계력 ESL");
    const li = within(screen.getByTestId("ls-confirm-list")).getAllByRole("listitem").map((x) => x.textContent);
    expect(li).toEqual(["le-1 — FAIL · 비교용 아님", "le-2 — PASS"]);
    fireEvent.click(screen.getByTestId("ls-confirm-ok"));
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect([ok, no]).toEqual([1, 1]);
  });
  it("칩 없음 = 아무것도 그리지 않음", () => {
    const { container } = render(<LoadSourceChip chip={null} />);
    expect(container.innerHTML).toBe("");
  });
});

/** 목 서버 handle 가로채기: 묶음 판정 응답 + POST 본문 기록 + 첫 요청(ack 없음) 422 확인 요청 */
function patch(server: MockServer, rows: EntrySourceRow[], calls: Record<string, unknown>[], confirm: boolean, postPath: string) {
  const orig = server.handle.bind(server);
  server.handle = (method, rawPath, q, body, size) => {
    const p = rawPath.replace(/^\/esl\/api/, "");
    if (method === "GET" && p === "/library/entries/sources") return { status: 200, body: { items: (q.get("ids") ?? "").split(",").map((id) => item(id, rows)) } };
    if (method === "POST" && p === postPath) {
      const b = (body ?? {}) as Record<string, unknown>;
      calls.push(b);
      if (confirm && b.load_source && !b.load_source_ack)
        return { status: 422, body: { detail: { code: "LOAD_SOURCE_UNCONFIRMED", message: "하중 출처 확인이 필요합니다.", entries: [{ entry_id: "le-1", status: "FAIL", comparable: false, validation_id: "v-le-1" }], worst: "FAIL" } } };
    }
    return orig(method, rawPath, q, body, size);
  };
}
const primary = (c: HTMLElement) => c.querySelector("button[data-primary]") as HTMLButtonElement;

describe("비드 최적화 생성 화면(OptNew)", () => {
  const URL = "/p/p-body/opt/new?entries=le-1,le-2,le-3";
  it("선택 요소 1개 + 판정 표식, 지그 변위·스프링은 선택 불가+사유, 안 고르면 load_source 필드 없음", async () => {
    const calls: Record<string, unknown>[] = [];
    const r = renderApp(URL, "power", (s) => patch(s, rowsOk().map((x) => (x.key === "jig_spring" ? pass("jig_spring") : x)), calls, false, "/opt/runs"));
    const sel = (await screen.findByTestId("ls-select")) as HTMLSelectElement;
    expect(screen.getAllByTestId("ls-select")).toHaveLength(1);
    await waitFor(() => expect(screen.getByTestId("ls-opt-full").textContent).toBe("전 노드 ESL · PASS"));
    expect(sel.options[0].textContent).toBe("기본 — 전 노드 ESL");
    expect(screen.getByTestId("ls-opt-jig_disp").hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("ls-opt-jig_disp").textContent).toContain("선택 불가");
    expect(screen.getByTestId("ls-opt-jig_spring").hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("ls-opt-jig").hasAttribute("disabled")).toBe(false);
    await waitFor(() => expect(primary(r.container).disabled).toBe(false), { timeout: 8000 });
    fireEvent.click(primary(r.container));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect("load_source" in calls[0]).toBe(false);
    expect("load_source_ack" in calls[0]).toBe(false);
  }, 20000);

  it("FAIL·비교용 아님 출처 선택 → 서버 422 → 확인 대화 → 확인 시 load_source_ack: true 로 재요청 → 상세로 이동", async () => {
    const calls: Record<string, unknown>[] = [];
    const r = renderApp(URL, "power", (s) => patch(s, rowsOk(), calls, true, "/opt/runs"));
    const sel = (await screen.findByTestId("ls-select")) as HTMLSelectElement;
    await waitFor(() => expect(screen.getByTestId("ls-opt-bforce").textContent).toBe("경계력 ESL · FAIL · 비교용 아님"));
    fireEvent.change(sel, { target: { value: "bforce" } });
    expect(screen.getByTestId("ls-mark").textContent).toBe("FAIL · 비교용 아님");
    await waitFor(() => expect(primary(r.container).disabled).toBe(false), { timeout: 8000 });
    fireEvent.click(primary(r.container));
    await screen.findByRole("alertdialog");
    expect(calls).toHaveLength(1);
    expect(calls[0].load_source).toBe("bforce");
    expect("load_source_ack" in calls[0]).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(calls).toHaveLength(1);
    fireEvent.click(primary(r.container));
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByTestId("ls-confirm-ok"));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls[2].load_source).toBe("bforce");
    expect(calls[2].load_source_ack).toBe(true);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  }, 25000);
});

describe("스터디 생성 화면(DoeStudy 새로 만들기)", () => {
  const URL = "/p/p-body/doe/new?entries=le-1,le-2";
  it("기본 = '기본 — 순위 지표 기준', 지그 3방식·전 노드 선택 가능(스터디), 안 고르면 load_source 필드 없음", async () => {
    const calls: Record<string, unknown>[] = [];
    const r = renderApp(URL, "power", (s) => patch(s, rowsOk().map((x) => (x.key === "jig_spring" ? pass("jig_spring") : x)), calls, false, "/doe/studies"));
    const sel = (await screen.findByTestId("ls-select")) as HTMLSelectElement;
    expect(sel.options[0].textContent).toBe("기본 — 순위 지표 기준");
    await waitFor(() => expect(screen.getByTestId("ls-opt-jig_spring").textContent).toBe("지그 스프링 · PASS"));
    expect(screen.getByTestId("ls-opt-jig_spring").hasAttribute("disabled")).toBe(false);
    await waitFor(() => expect(primary(r.container).disabled).toBe(false), { timeout: 8000 });
    fireEvent.click(primary(r.container));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect("load_source" in calls[0]).toBe(false);
  }, 20000);

  it("검증 전 출처 선택 → 422 확인 요청 → 확인 → ack 재요청", async () => {
    const calls: Record<string, unknown>[] = [];
    const r = renderApp(URL, "power", (s) => patch(s, rowsOk(), calls, true, "/doe/studies"));
    const sel = (await screen.findByTestId("ls-select")) as HTMLSelectElement;
    await waitFor(() => expect(screen.getByTestId("ls-opt-fint").textContent).toBe("내력 ESL · 검증 전"));
    fireEvent.change(sel, { target: { value: "fint" } });
    await waitFor(() => expect(primary(r.container).disabled).toBe(false), { timeout: 8000 });
    fireEvent.click(primary(r.container));
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByTestId("ls-confirm-ok"));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toMatchObject({ load_source: "fint", load_source_ack: true });
  }, 25000);
});

describe("결과 화면 사용 출처 칩", () => {
  const check = { key: "bforce", worst: "FAIL" as const, entries: [{ entry_id: "le-1", status: "FAIL" as const, comparable: false, validation_id: "v1" }] };
  it("스터디 결과 상태 띠: 스냅샷 load_source 칩(최악 표식) · 스냅샷 없으면 칩 없음", async () => {
    renderApp("/p/p-body/doe/doe-40", "power", (s) => {
      s.doe.demoJig();
      const orig = s.handle.bind(s);
      s.handle = (m, p, q, b, z) => {
        const r = orig(m, p, q, b, z);
        if (m === "GET" && /\/doe\/studies\/doe-40$/.test(p) && r.body) {
          const o = r.body as { inputs: Record<string, unknown> };
          return { ...r, body: { ...o, inputs: { ...o.inputs, load_source: "bforce", load_source_check: check } } };
        }
        return r;
      };
    });
    const chip = await screen.findByTestId("ls-chip", undefined, { timeout: 8000 });
    expect(chip.textContent).toBe("하중 출처 경계력 ESL · FAIL · 비교용 아님");
    expect(chip.closest("[data-testid='doe-status']")).toBeTruthy();
  }, 30000);
  it("스냅샷 없는 옛 스터디 = 칩 없음", async () => {
    renderApp("/p/p-body/doe/doe-40", "power", (s) => s.doe.demoJig());
    await screen.findByTestId("doe-status", undefined, { timeout: 8000 });
    expect(screen.queryByTestId("ls-chip")).toBeNull();
  }, 30000);
  it("비드 최적화 상세 설정 카드: 하중 출처 Stat", async () => {
    renderApp("/p/p-body/opt/opt-1", "power", (s) => {
      const orig = s.handle.bind(s);
      s.handle = (m, p, q, b, z) => {
        const r = orig(m, p, q, b, z);
        if (m === "GET" && /\/opt\/runs\/opt-1$/.test(p) && r.body) { const o = r.body as { options: Record<string, unknown> }; return { ...r, body: { ...o, options: { ...o.options, load_source: "bforce", load_source_check: check } } }; }
        return r;
      };
    });
    const chip = await screen.findByTestId("ls-chip", undefined, { timeout: 8000 });
    expect(chip.textContent).toBe("경계력 ESL · FAIL · 비교용 아님");
  }, 20000);
});
