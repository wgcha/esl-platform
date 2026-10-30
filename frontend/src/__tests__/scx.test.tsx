// v0.11.0 SCX 드라이브에서 고르기(계약 esl_scx_relay.md §10.1·V-SR-15(A)): 탭 4개·비활성 사유(관리자만 상세),
// 루트·폴더 탐색·힌트 배지(rad·h3d 선택, 엔진·include·상태 자동 표시), 내려받기 → 파일별·전체 진행·취소·실패 사유·재시도(파일 단위 이어받기)
// → 기존 업로드 확인 결과 → Case 만들기. 크기 상한·여유 공간 경고. 주 버튼 1개.
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import { MockServer } from "../mock/server";
import { MOCK_SCX_ROOTS, scxHint } from "../mock/scxmock";
import { shortReason } from "../api/scx";
import { SCX_FETCH_LABEL, SCX_RETRY_NOTE } from "../pages/newcase/ScxPanel";
import { GUIDE } from "../pages/guide/content";

const NEW = "/p/p-body/cases/new";
const primaries = (c: HTMLElement) => c.querySelectorAll("button[data-primary]");
const LONG = { timeout: 6000 };
// 작업 진행은 화면 폴링(2초) 몇 번을 기다린다
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => {
  try {
    sessionStorage.clear();
  } catch {
    /* 없음 */
  }
});

async function openScx(user: "power" | "admin" | "general" = "power", setup?: (s: MockServer) => void) {
  const r = renderApp(NEW, user, setup);
  await screen.findByRole("heading", { name: "새 Case" });
  fireEvent.click(screen.getByRole("tab", { name: /SCX 드라이브에서 고르기/ }));
  return r;
}
async function enter(table: HTMLElement, ...dirs: string[]) {
  let t = table;
  for (const d of dirs) {
    fireEvent.click(await within(t).findByRole("button", { name: `${d}/` }));
    t = await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" });
    await within(t).findByRole("button", { name: ".. 위로" });
  }
  return t;
}

describe("SCX 드라이브 — 목 서버 계약", () => {
  it("hint 규칙(§7.1): _0000.rad = rad, _0001.rad = engine, .h3d, .inc/.k = include, .sta/.str = state", () => {
    expect(["a_0000.rad", "a_0001.rad", "a_0005.rad", "a.h3d", "m.inc", "m.k", "p.sta", "p.str", "x.out", "plain.rad"].map(scxHint)).toEqual([
      "rad", "engine", "engine", "h3d", "include", "include", "state", "state", null, null,
    ]);
  });

  it("status·browse·fetches 스키마와 오류 코드", () => {
    const s = new MockServer({ user: "power" });
    const st = s.handle("GET", "/esl/api/scx/status", new URLSearchParams({ project_id: "p-body" }), null).body as Record<string, unknown>;
    expect(Object.keys(st).sort()).toEqual(["adapters", "fetch", "relay", "roots", "verify"]);
    expect((st.roots as unknown[]).length).toBe(MOCK_SCX_ROOTS.length);
    const q = (o: Record<string, string>) => new URLSearchParams({ project_id: "p-body", ...o });
    const b = s.handle("GET", "/scx/browse", q({ root: "drop", path: "" }), null);
    expect(b.status).toBe(200);
    const body = b.body as { entries: { name: string; kind: string }[]; display: string; truncated: boolean };
    expect(body.entries.map((e) => e.name)).toEqual(["65QN80", "75QN90", "readme.txt"]); // 숨김(.) 제외, 폴더 먼저
    expect(body.display).toBe("/Users/vd.dashboard/share/drop");
    expect(s.handle("GET", "/scx/browse", q({ root: "drop", path: "../x" }), null).body).toMatchObject({ detail: { code: "SCX_PATH_NOT_ALLOWED" } });
    expect(s.handle("GET", "/scx/browse", q({ root: "drop", path: ".scx_tmp" }), null).status).toBe(422);
    expect(s.handle("GET", "/scx/browse", q({ root: "nope", path: "" }), null).body).toMatchObject({ detail: { code: "SCX_ROOT_NOT_FOUND" } });
    expect(s.handle("GET", "/scx/browse", q({ root: "drop", path: "nope" }), null).body).toMatchObject({ detail: { code: "SCX_PATH_NOT_FOUND" } });
    const f = (o: Record<string, string>) => s.handle("POST", "/scx/fetches", new URLSearchParams(), { project_id: "p-body", name: "t1", root: "drop", rad_rel: "75QN90/drop_front/ref_0000.rad", h3d_rel: "75QN90/drop_front/ref.h3d", ...o });
    expect(f({ rad_rel: "75QN90/drop_front/ref_0001.rad" }).body).toMatchObject({ detail: { code: "SCX_NOT_RAD" } });
    expect(f({ h3d_rel: "75QN90/drop_front/inc_mat.inc" }).body).toMatchObject({ detail: { code: "SCX_NOT_H3D" } });
    expect(f({ name: "bad name" }).body).toMatchObject({ detail: { code: "UPLOAD_NAME_INVALID" } });
    const big = f({ rad_rel: "75QN90/drop_full_rec/full_0000.rad", h3d_rel: "75QN90/drop_full_rec/full.h3d" });
    expect(big.status).toBe(422);
    expect(big.body).toMatchObject({ detail: { code: "SCX_FILE_TOO_LARGE" } });
    const ok = f({});
    expect(ok.status).toBe(202);
    const out = ok.body as { upload_id: string; job_id: string };
    const job = s.jobs.find((j) => j.id === out.job_id)!;
    expect(job.job_type).toBe("SCX_FETCH");
    expect(job.lane).toBe("XFER");
    expect(job.steps!.map((x) => x.step_key)).toEqual(["SF_RAD", "SF_H3D", "SF_REGISTER"]);
    s.drain();
    const u = s.handle("GET", `/uploads/${out.upload_id}`, new URLSearchParams(), null).body as { state: string; client: { name: string }; files: { rel: string; done: boolean }[] };
    expect(u.state).toBe("COMPLETED");
    expect(u.client.name).toBe("scx-relay");
    expect(u.files.map((x) => x.rel).sort()).toEqual(["h3d/ref.h3d", "rad/inc_mat.inc", "rad/inc_mesh.inc", "rad/ref_0000.rad", "rad/ref_0001.rad"]);
    // 일반(general) 사용자: 탐색 403
    const g = new MockServer({ user: "general" });
    expect(g.handle("GET", "/scx/browse", q({ root: "drop", path: "" }), null).status).toBe(403);
  });
});

describe("새 Case — SCX 드라이브에서 고르기", () => {
  it("탭 4번째, 루트 → 폴더 → rad·h3d 선택(엔진·include·상태 자동 표시) → 내려받기 → 확인 결과 → Case 만들기", async () => {
    const { server, container } = await openScx();
    const panel = screen.getByRole("tabpanel", { hidden: false, name: /SCX/ });
    const sel = await within(panel).findByRole("combobox", { name: "SCX 루트" });
    expect([...(sel as HTMLSelectElement).options].map((o) => o.textContent)).toEqual(MOCK_SCX_ROOTS.map((r) => r.label));
    const t0 = await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" });
    expect(within(t0).queryByText(/\.scx_tmp/)).toBeNull();
    const t = await enter(t0, "75QN90", "drop_corner_LT");
    // 배지: 고르는 것(rad·h3d) + 자동 포함 표시(엔진·include·상태)
    expect(within(t).getByRole("button", { name: "rad 선택" })).toBeTruthy();
    expect(within(t).getByRole("button", { name: "h3d 선택" })).toBeTruthy();
    expect(within(t).getByText("엔진 rad · 자동")).toBeTruthy();
    expect(within(t).getAllByText("include · 자동").length).toBe(2);
    expect(within(t).getByText("상태(.sta/.str) · 자동")).toBeTruthy();
    // 주 버튼은 페이지의 Case 만들기 1개(내려받기는 일반 버튼)
    expect(primaries(container).length).toBe(1);
    const start = screen.getByTestId("scx-start") as HTMLButtonElement;
    expect(start.textContent).toBe(SCX_FETCH_LABEL);
    expect(start.disabled).toBe(true);
    fireEvent.click(within(t).getByRole("button", { name: "rad 선택" }));
    expect(screen.getByTestId("scx-auto").textContent).toMatch(/엔진 rad 1개.*\.sta\/\.str 1개/);
    // Case 이름 제안(_0000.rad 뗀 stem)
    await waitFor(() => expect((screen.getByPlaceholderText("QN80H_rear40") as HTMLInputElement).value).toBe("corner"));
    expect(start.disabled).toBe(true);
    fireEvent.click(within(t).getByRole("button", { name: "h3d 선택" }));
    await waitFor(() => expect(start.disabled).toBe(false));
    fireEvent.click(start);
    expect(await screen.findByTestId("scx-fetch")).toBeTruthy();
    expect(server.scx.lastFetchIn).toEqual({ project_id: "p-body", name: "corner", root: "drop", rad_rel: "75QN90/drop_corner_LT/corner_0000.rad", h3d_rel: "75QN90/drop_corner_LT/corner.h3d" });
    // 진행: rad·include 받음 → h3d 받는 중(파일별 진행률 + 진행 문구)
    act(() => {
      server.tick(); // 시작
      server.tick(); // SF_RAD 50
      server.tick(); // SF_RAD 100 → SF_H3D
      server.tick(); // 대시보드가 받는 중
      server.tick(); // h3d 25%
    });
    const files = await screen.findByRole("table", { name: "내려받는 파일" });
    await waitFor(() => expect(within(files).getByTestId("file-progress").textContent).toMatch(/25%/), LONG);
    expect(within(files).getAllByText("받음").length).toBe(5); // rad·엔진·include 2·상태
    await waitFor(() => expect(screen.getByTestId("job-progress-label").textContent).toMatch(/^h3d .* GB$/), LONG);
    expect(screen.getByRole("button", { name: "취소" })).toBeTruthy();
    act(() => server.drain());
    await waitFor(() => expect(screen.getByLabelText("올린 파일 확인 결과").textContent).toContain("rad·h3d 확인됨"), LONG);
    const create = primaries(container)[0] as HTMLButtonElement;
    await waitFor(() => expect(create.disabled).toBe(false));
    fireEvent.click(create);
    await screen.findByRole("heading", { level: 2, name: /① 입력/ }, LONG);
    const c = server.cases[server.cases.length - 1];
    expect(c.folder_name).toBe("corner");
  });

  it("실패 → 사유 표시 → 재시도(받은 파일 건너뜀, 끊긴 h3d 는 처음부터) → 완료", async () => {
    const { server } = await openScx("power", (s) => {
      s.scx.failOnce = { step: "SF_H3D", code: "SCX_BUSY", message: "SCX 가 바쁘거나 응답이 없습니다(재시도 2회 소진)" };
    });
    const t = await enter(await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" }), "75QN90", "drop_front");
    fireEvent.click(within(t).getByRole("button", { name: "rad 선택" }));
    fireEvent.click(within(t).getByRole("button", { name: "h3d 선택" }));
    fireEvent.click(screen.getByTestId("scx-start"));
    await screen.findByTestId("scx-fetch");
    act(() => server.drain());
    await waitFor(() => expect(screen.getByTestId("job-progress").textContent).toContain("SCX_BUSY"), LONG);
    expect(screen.getByTestId("scx-retry-note").textContent).toContain(SCX_RETRY_NOTE);
    const firstJob = server.jobs.find((j) => j.job_type === "SCX_FETCH")!;
    fireEvent.click(screen.getByRole("button", { name: "재시도" }));
    await waitFor(() => expect(server.jobs.filter((j) => j.job_type === "SCX_FETCH").length).toBe(2));
    const retry = server.jobs.filter((j) => j.job_type === "SCX_FETCH")[1];
    expect(retry.retry_of_job_id).toBe(firstJob.id);
    act(() => server.drain());
    expect(server.logs[retry.id].join("\n")).toMatch(/확인된 파일 4개 건너뜀/);
    await waitFor(() => expect(screen.getByLabelText("올린 파일 확인 결과").textContent).toContain("rad·h3d 확인됨"), LONG);
  });

  it("취소 → 취소됨 + 이어받기 안내, '다른 파일 고르기'로 탐색으로", async () => {
    const { server } = await openScx();
    const t = await enter(await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" }), "65QN80", "drop_rear");
    fireEvent.click(within(t).getByRole("button", { name: "rad 선택" }));
    fireEvent.click(within(t).getByRole("button", { name: "h3d 선택" }));
    fireEvent.click(screen.getByTestId("scx-start"));
    await screen.findByTestId("scx-fetch");
    act(() => server.tick());
    fireEvent.click(await screen.findByRole("button", { name: "취소" }, LONG));
    await waitFor(() => expect(server.jobs.find((j) => j.job_type === "SCX_FETCH")!.state).toBe("CANCELED"));
    await waitFor(() => expect(screen.getByTestId("scx-retry-note").textContent).toContain("업로드 세션에 남습니다"), LONG);
    expect(server.jobs.find((j) => j.job_type === "SCX_FETCH")!.state).toBe("CANCELED");
    fireEvent.click(screen.getByRole("button", { name: "다른 파일 고르기" }));
    expect(await screen.findByTestId("scx-browse")).toBeTruthy();
  });

  it("누락 include → 같은 세션에 '추가로 올리기' → 다시 확인 OK", async () => {
    const { server } = await openScx();
    const t = await enter(await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" }), "75QN90", "drop_edge_B");
    fireEvent.click(within(t).getByRole("button", { name: "rad 선택" }));
    fireEvent.click(within(t).getByRole("button", { name: "h3d 선택" }));
    fireEvent.click(screen.getByTestId("scx-start"));
    await screen.findByTestId("scx-fetch");
    act(() => server.drain());
    const miss = await screen.findByTestId("missing-includes", {}, LONG);
    expect(miss.textContent).toContain("inc_mesh.inc");
    const input = screen.getByLabelText("빠진 include 파일") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(32).fill(65)], "inc_mesh.inc")] } });
    await waitFor(() => expect(screen.getByLabelText("올린 파일 확인 결과").textContent).toContain("rad·h3d 확인됨"), LONG);
    const up = [...server.p3.uploads.values()].pop()!;
    expect(up.state).toBe("COMPLETED");
    expect(up.files.map((f) => f.rel)).toContain("rad/inc_mesh.inc");
  });

  it("크기 상한 경고(릴레이 max_download_bytes) → 내려받기 비활성", async () => {
    await openScx();
    const t = await enter(await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" }), "75QN90", "drop_full_rec");
    fireEvent.click(within(t).getByRole("button", { name: "rad 선택" }));
    fireEvent.click(within(t).getByRole("button", { name: "h3d 선택" }));
    expect(screen.getByTestId("scx-too-big").textContent).toMatch(/상한 64\.00 GB/);
    const b = screen.getByTestId("scx-start") as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    expect(b.parentElement!.getAttribute("title")).toMatch(/상한/);
  });

  it("여유 공간 부족(507) → 필요·여유 값과 함께 사유", async () => {
    await openScx("power", (s) => {
      s.p3.storageLeft = 5 * 1024 ** 3;
    });
    const t = await enter(await screen.findByRole("table", { name: "SCX 드라이브 폴더 목록" }), "75QN90", "drop_front");
    fireEvent.click(within(t).getByRole("button", { name: "rad 선택" }));
    fireEvent.click(within(t).getByRole("button", { name: "h3d 선택" }));
    fireEvent.click(screen.getByTestId("scx-start"));
    const e = await screen.findByTestId("scx-start-error");
    expect(e.textContent).toMatch(/여유 공간이 부족/);
    expect(e.textContent).toMatch(/필요 .*GB · 현재 여유 5\.00 GB/);
    expect(screen.queryByTestId("scx-fetch")).toBeNull();
  });

  it("대시보드 다운: 탭 비활성 표시 + 사유(일반 = 요지만, 관리자 = 전체·연결 상세), 다른 탭 정상", async () => {
    await openScx("power", (s) => {
      s.scx.mode = "down";
    });
    const tab = screen.getByRole("tab", { name: /SCX 드라이브에서 고르기/ });
    await waitFor(() => expect(tab.className).toContain("dis"));
    expect(tab.getAttribute("aria-disabled")).toBe("true");
    expect(tab.getAttribute("title")).toMatch(/대시보드에 연결할 수 없습니다/);
    const off = await screen.findByTestId("scx-off");
    expect(off.textContent).toContain("대시보드에 연결할 수 없습니다");
    expect(off.textContent).not.toContain("relay_url");
    expect(screen.queryByTestId("scx-admin-detail")).toBeNull();
    // 다른 탭은 그대로
    fireEvent.click(screen.getByRole("tab", { name: "서버 폴더에서 고르기" }));
    expect(await screen.findByRole("table", { name: "서버 폴더 목록" })).toBeTruthy();
  });

  it("관리자: 꺼짐 사유 전체 + 연결 상세(reason_code·relay·adapters)", async () => {
    await openScx("admin", (s) => {
      s.scx.mode = "down";
    });
    const off = await screen.findByTestId("scx-off");
    await waitFor(() => expect(off.textContent).toContain("relay_url"));
    expect(screen.getByTestId("scx-admin-detail").textContent).toMatch(/SCX_RELAY_UNREACHABLE.*reachable=false/s);
  });

  it("shortReason: 끝 괄호(관리자 조치)를 뗀다", () => {
    expect(shortReason("대시보드 SCX 릴레이가 꺼져 있습니다(SIMDASH_SCX_RELAY_ENABLED)")).toBe("대시보드 SCX 릴레이가 꺼져 있습니다");
    expect(shortReason("사유")).toBe("사유");
  });

  it("가이드: 'SCX 드라이브에서 고르기' 카드(새 Case ?tab=scx 바로가기)", () => {
    const card = GUIDE.flatMap((g) => g.cards).find((c) => c.id === "scx-drive");
    expect(card?.title).toBe("새 Case — SCX 드라이브에서 고르기");
    expect(card?.target).toEqual({ kind: "new", tab: "scx" });
  });
});
