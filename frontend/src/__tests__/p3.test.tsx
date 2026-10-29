// P3-UX(계약 esl_p3_ux.md §1~§4·§6·§8·§9): 분할 업로드(청크·이어 올리기·재시도·507), 새 Case 두 탭, 서버 폴더 선택,
// 결과 받기(zip)·413, 버전 배지·업데이트 내역, 사용 가이드·user.md, 주 버튼 1개.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "../app/App";
import USER_MD from "../../../docs/manual/user.md?raw";
import VERSION_TXT from "../../../VERSION?raw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { MockServer, createMockFetch } from "../mock/server";
import { MOCK_CHANGELOG, MOCK_VERSION } from "../mock/p3mock";
import { ApiError } from "../api/client";
import { putChunk } from "../api/p3";
import { Uploader, planChunks, sha256Available, signature, type PickedFile, type UploadProgress } from "../lib/uploader";
import { uploadStore } from "../lib/uploadStore";
import { cmpVersion, isNewVersion, parseChangelog } from "../lib/changelog";
import { GUIDE, FAQ } from "../pages/guide/content";
import { PC_CODE_BUTTON, remainText, serverUrl } from "../pages/newcase/PcPanel";
import { PC_TAB_REASON } from "../pages/newcase/NewCase";
import { H3D_RUNNING } from "../components/JobProgress";
import { BUNDLE_LABEL, BUNDLE_TOO_LARGE } from "../components/BundleButton";
import { rememberCase } from "../lib/recent";

const primaries = (c: HTMLElement) => c.querySelectorAll("button[data-primary]");
const file = (name: string, size: number) => new File([new Uint8Array(size).fill(65)], name, { lastModified: 1760000000000 });
const NEW = "/p/p-body/cases/new";

function setup(chunk = 8) {
  const server = new MockServer({ user: "power" });
  server.p3.chunkSize = chunk;
  globalThis.fetch = createMockFetch(server);
  return server;
}
const noSleep = { deps: { sleep: async () => undefined }, retryDelayMs: 0 };
const picks = (): PickedFile[] => [
  { file: file("model_0000.rad", 20), rel: "rad/model_0000.rad" },
  { file: file("inc_mat.inc", 5), rel: "rad/inc_mat.inc" },
  { file: file("inc_mesh.inc", 9), rel: "rad/inc_mesh.inc" },
  { file: file("drop.h3d", 30), rel: "h3d/drop.h3d" },
];

beforeEach(() => {
  localStorage.clear();
  uploadStore._reset();
});
afterEach(() => localStorage.clear());

describe("분할 업로드(Uploader)", () => {
  it("청크 분할: 크기·시작 오프셋", () => {
    expect(planChunks(40, 16)).toEqual([
      { offset: 0, end: 16 },
      { offset: 16, end: 32 },
      { offset: 32, end: 40 },
    ]);
    expect(planChunks(40, 16, 32)).toEqual([{ offset: 32, end: 40 }]);
    expect(planChunks(0, 16)).toEqual([]);
  });

  it("세션 → 파일별 청크 PUT(순서대로) → complete: h3d 경로·파트", async () => {
    const server = setup(8);
    const seen: UploadProgress[] = [];
    const up = new Uploader("p-body", "rear40", picks(), (p) => seen.push(p), noSleep);
    expect(await up.run()).toBe(true);
    // 20/8→3, 5→1, 9→2, 30→4
    expect(server.p3.putCount).toBe(10);
    const u = [...server.p3.uploads.values()][0];
    expect(u.files.every((f) => f.done && f.received === f.size)).toBe(true);
    expect(seen[seen.length - 1].phase).toBe("uploaded");
    expect(seen[seen.length - 1].sent).toBe(64);
    // 청크마다 X-Chunk-Sha256(Web Crypto 가 있으면 64자리 hex)
    if (sha256Available()) {
      expect(server.p3.chunkShas.every((h) => /^[0-9a-f]{64}$/.test(h ?? ""))).toBe(true);
      expect(server.p3.chunkShas[0]).toBe("c34ab6abb7b2bb595bc25c3b388c872fd1d575819a8f55cc689510285e212385" /* sha256("AAAAAAAA") */);
    }
    const r = await up.complete();
    expect(r.ok).toBe(true);
    expect(r.h3d_path).toMatch(/h3d\\drop\.h3d$/);
    expect(r.results_dir).toBeNull();
    expect(r.parts?.map((p) => p.title)).toContain("chassis_rear");
  });

  it("일시 오류(503)는 재시도해 이어 간다", async () => {
    const server = setup(8);
    server.p3.failPuts = 2;
    const up = new Uploader("p-body", "rear40", picks(), undefined, noSleep);
    expect(await up.run()).toBe(true);
    expect(up.progress.retries).toBe(2);
    expect(server.p3.putCount).toBe(10);
  });

  it("청크 sha256 불일치(422 CHUNK_SHA256_MISMATCH)는 같은 offset 으로 다시 보낸다", async () => {
    const server = setup(8);
    server.p3.badShaPuts = 1;
    const up = new Uploader("p-body", "rear40", picks(), undefined, noSleep);
    expect(await up.run()).toBe(true);
    expect(up.progress.retries).toBe(1);
  });

  it("재시도 한도를 넘으면 멈추고, '이어 올리기'는 서버 received 부터(중복 전송 없음)", async () => {
    const server = setup(8);
    const up = new Uploader("p-body", "rear40", picks(), undefined, { ...noSleep, maxRetries: 1 });
    // 3번째 청크부터 연속 실패
    let n = 0;
    const real = createMockFetch(server);
    globalThis.fetch = (async (i: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "PUT" && ++n >= 3 && n <= 4) return new Response(JSON.stringify({ detail: { code: "X", message: "x" } }), { status: 502 });
      return real(i, init);
    }) as typeof fetch;
    expect(await up.run()).toBe(false);
    expect(up.progress.phase).toBe("error");
    expect(up.progress.sent).toBe(16);
    expect(await up.run()).toBe(true);
    expect(server.p3.putCount).toBe(10);
  });

  it("응답을 못 받은 청크(서버는 받음)를 다시 보내면 409 received 로 맞춘다", async () => {
    const server = setup(8);
    let lost = false;
    const up = new Uploader("p-body", "rear40", picks(), undefined, {
      ...noSleep,
      deps: {
        sleep: async () => undefined,
        putChunk: async (...a: Parameters<typeof putChunk>) => {
          const r = await putChunk(...a);
          if (!lost && a[2] === 8) {
            lost = true;
            throw new ApiError(0, { code: "NETWORK_ERROR", message: "끊김" });
          }
          return r;
        },
      },
    });
    expect(await up.run()).toBe(true);
    expect(server.p3.putCount).toBe(10);
    expect(up.progress.retries).toBe(1);
  });

  it("탭을 닫았다 다시 열어 같은 파일을 고르면 저장된 세션을 이어 올린다", async () => {
    const server = setup(8);
    const first = new Uploader("p-body", "rear40", picks(), (p) => p.sent >= 16 && first.stop(), noSleep);
    expect(await first.run()).toBe(false);
    const sentBefore = server.p3.putCount;
    expect(sentBefore).toBeGreaterThan(0);
    // 새 Uploader(새 탭) — 이름이 달라도 파일 이름·크기·mtime 이 같으면 같은 세션
    const again = new Uploader("p-body", "other", picks(), undefined, noSleep);
    expect(await again.run()).toBe(true);
    expect(again.progress.resumed).toBe(true);
    expect(server.p3.uploads.size).toBe(1);
    expect(server.p3.putCount).toBe(10);
    expect(signature("p-body", picks())).toBe(signature("p-body", picks()));
  });

  it("저장 공간 부족(507)은 안내 문구로 멈춘다", async () => {
    const server = setup(8);
    server.p3.storageLeft = 10;
    const up = new Uploader("p-body", "rear40", picks(), undefined, noSleep);
    expect(await up.run()).toBe(false);
    expect(up.progress.error).toContain("저장 공간");
  });

  it("누락 include → 추가로 올리기 → 다시 complete", async () => {
    setup(8);
    const files = picks().filter((f) => f.rel !== "rad/inc_mesh.inc");
    const up = new Uploader("p-body", "rear40", files, undefined, noSleep);
    expect(await up.run()).toBe(true);
    const r1 = await up.complete();
    expect(r1.ok).toBe(false);
    expect(r1.missing_includes).toEqual(["rad/inc_mesh.inc"]);
    expect(await up.add([{ file: file("inc_mesh.inc", 9), rel: "rad/inc_mesh.inc" }])).toBe(true);
    const r2 = await up.complete();
    expect(r2.ok).toBe(true);
    expect(r2.state).toBe("COMPLETED");
  });
});

describe("새 Case 화면", () => {
  it("탭 3개(기본 = 내 PC에서 올리기), 주 버튼 1개 'Case 만들기'(입력 전 비활성)", async () => {
    const { container } = renderApp(NEW);
    expect(await screen.findByRole("heading", { name: "새 Case" })).toBeTruthy();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["내 PC에서 올리기", "서버 폴더에서 고르기", "PC에서 추출해 올리기"]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(primaries(container).length).toBe(1));
    const btn = primaries(container)[0] as HTMLButtonElement;
    expect(btn.textContent).toBe("Case 만들기");
    expect(btn.disabled).toBe(true);
    // h3d 기본, 결과 폴더는 접힌 대안
    expect(screen.getByText("② h3d 결과 파일")).toBeTruthy();
    expect((container.querySelector("details.alt-input") as HTMLDetailsElement).open).toBe(false);
  });

  it("Case 목록 '새 Case' → 새 Case 화면", async () => {
    renderApp("/p/p-body");
    const b = await screen.findByRole("button", { name: "새 Case" });
    await waitFor(() => expect((b as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(b);
    expect(await screen.findByRole("heading", { name: "새 Case" })).toBeTruthy();
  });

  it("올리기: rad·include + h3d 고르기 → 목록·예상 시간 → 올리기 → 확인 → Case 만들기", async () => {
    const { container, server } = renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("① rad · include 파일 파일"), {
      target: { files: [file("model_0000.rad", 20), file("inc_mat.inc", 5), file("inc_mesh.inc", 9)] },
    });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 30)] } });
    const list = await screen.findByRole("table", { name: "올릴 파일" });
    expect(within(list).getAllByRole("row").length).toBe(5);
    expect(screen.getByTestId("upload-summary").textContent).toMatch(/4개 · 64 B.*예상 약/);
    // 이름은 rad 에서 자동
    expect((screen.getByLabelText(/^Case 이름/) as HTMLInputElement).value).toBe("model");
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
    expect(server.p3.uploads.size).toBe(1);
    const btn = primaries(container)[0] as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.change(screen.getByLabelText(/^Case 이름/), { target: { value: "QN80H_rear40" } });
    fireEvent.click(btn);
    expect(await screen.findByRole("heading", { level: 2, name: "① 입력" })).toBeTruthy();
    const c = server.cases.find((x) => x.folder_name === "QN80H_rear40")!;
    expect(c.h3d_path).toMatch(/drop\.h3d$/);
  });

  it("h3d 칸에 다른 파일·rad 칸에 h3d 는 제외 안내", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("① rad · include 파일 파일"), { target: { files: [file("big.h3d", 3), file("x.png", 3)] } });
    expect(await screen.findByText(/제외 2개/)).toBeTruthy();
  });

  it("누락 include 가 있으면 '추가로 올리기' 안내", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("① rad · include 파일 파일"), { target: { files: [file("model_0000.rad", 20)] } });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 30)] } });
    fireEvent.click(await screen.findByRole("button", { name: "올리기" }));
    const box = await screen.findByTestId("missing-includes");
    expect(box.textContent).toContain("inc_mat.inc");
    expect(within(box).getByRole("button", { name: "추가로 올리기" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("추가로 올릴 include"), { target: { files: [file("inc_mat.inc", 5), file("inc_mesh.inc", 9)] } });
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
  });

  it("서버 폴더: 폴더 들어가기 → rad·h3d 배지로 선택 → Case 만들기(h3d 서버 추출 안내)", async () => {
    const { container, server } = renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.click(screen.getByRole("tab", { name: "서버 폴더에서 고르기" }));
    const table = await screen.findByRole("table", { name: "서버 폴더 목록" });
    // SPDM 루트 없음, 루트 1개라 루트 버튼 없음
    expect(screen.queryByText(/SPDM/)).toBeNull();
    fireEvent.click(await within(table).findByRole("button", { name: /^kim\// }));
    fireEvent.click(await within(table).findByRole("button", { name: /20261019-031200_QN80H_rear40/ }));
    fireEvent.click(await within(table).findByRole("button", { name: /^rad\// }));
    fireEvent.click(await within(table).findByRole("button", { name: "rad 선택" }));
    expect(await screen.findByLabelText("rad 확인 결과")).toBeTruthy();
    fireEvent.click(within(container.querySelector(".browse-crumbs") as HTMLElement).getByRole("button", { name: "20261019-031200_QN80H_rear40" }));
    fireEvent.click(await within(table).findByRole("button", { name: /^h3d\// }));
    fireEvent.click(await within(table).findByRole("button", { name: "h3d 선택" }));
    expect(screen.getByTestId("h3d-note").textContent).toContain("서버의 HyperView");
    const btn = primaries(container)[0] as HTMLButtonElement;
    expect(primaries(container).length).toBe(1);
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    expect(await screen.findByRole("heading", { level: 2, name: "① 입력" })).toBeTruthy();
    expect(server.cases[server.cases.length - 1].h3d_path).toMatch(/chassis_rear\.h3d$/);
  });

  it("서버 폴더: done.json 폴더는 '결과 폴더 선택' 배지", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.click(screen.getByRole("tab", { name: "서버 폴더에서 고르기" }));
    const table = await screen.findByRole("table", { name: "서버 폴더 목록" });
    fireEvent.click(await within(table).findByRole("button", { name: /^kim\// }));
    fireEvent.click(await within(table).findByRole("button", { name: /QN90D_edgeB/ }));
    fireEvent.click(await within(table).findByRole("button", { name: "결과 폴더 선택" }));
    expect(await screen.findByLabelText("결과 폴더 확인 결과")).toBeTruthy();
  });

  it("조회 사용자: Case 만들기 비활성 + 권한 사유", async () => {
    const { container } = renderApp(NEW, "general");
    await screen.findByRole("heading", { name: "새 Case" });
    await waitFor(() => expect(screen.getByTestId("user").textContent).toContain("조회"));
    const btn = primaries(container)[0] as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.parentElement!.getAttribute("title")).toMatch(/실행 권한/);
  });

  it("?upload= (PC 도구가 올린 업로드)로 채워 열기 → Case 만들기만", async () => {
    const server = new MockServer({ user: "power" });
    server.p3.chunkSize = 8;
    globalThis.fetch = createMockFetch(server);
    const up = new Uploader("p-body", "pc", picks(), undefined, noSleep);
    expect(await up.run()).toBe(true);
    const { container } = render(
      <MemoryRouter initialEntries={[`${NEW}?upload=${up.uploadId}`]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("pc-upload")).toBeTruthy();
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
    expect((screen.getByLabelText(/^Case 이름/) as HTMLInputElement).value).toBe("model");
    await waitFor(() => expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(false));
  });
});

describe("PC에서 추출해 올리기(§9.1)", () => {
  it("탭: 설치 안내(update.bat·ESL_extract.bat) → 코드 만들기 → 6자리·카운트다운, 주 버튼은 PC 도구 안내로 비활성", async () => {
    const { container, server } = renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.click(screen.getByRole("tab", { name: "PC에서 추출해 올리기" }));
    const panel = await screen.findByTestId("pc-panel");
    expect(panel.textContent).toContain("update.bat");
    expect(panel.textContent).toContain("ESL_extract.bat");
    expect(panel.textContent).toMatch(/h3d와 rad/);
    expect(screen.getByTestId("pc-server-url").textContent).toBe(serverUrl());
    expect(await within(panel).findByText("아직 연결된 PC가 없습니다")).toBeTruthy();
    const btn = primaries(container)[0] as HTMLButtonElement;
    expect(primaries(container).length).toBe(1);
    expect(btn.disabled).toBe(true);
    await waitFor(() => expect(btn.parentElement!.getAttribute("title")).toBe(PC_TAB_REASON));
    fireEvent.click(within(panel).getByRole("button", { name: PC_CODE_BUTTON }));
    const code = await screen.findByTestId("pc-code");
    const digits = within(code).getByLabelText("연결 코드").textContent!.replace(/\s/g, "");
    expect(digits).toMatch(/^\d{6}$/);
    expect(server.p3.codes[0].code).toBe(digits);
    expect(server.p3.codes[0].project_id).toBe("p-body");
    expect(screen.getByTestId("pc-code-left").textContent).toMatch(/남은 시간 1[45]:\d\d/);
    expect(within(panel).getByRole("button", { name: "새 코드 만들기" })).toBeTruthy();
  });

  it("만료된 코드는 '만료됨' 표시", async () => {
    const { server } = renderApp(`${NEW}?tab=pc`);
    server.p3.clock = () => Date.now() - 16 * 60_000;     // 16분 전에 만든 코드 = 이미 만료
    fireEvent.click(await screen.findByRole("button", { name: PC_CODE_BUTTON }));
    expect((await screen.findByTestId("pc-code-left")).textContent).toContain("만료됨");
  });

  it("연결된 PC 목록(장치명·상태·만료) → 폐기", async () => {
    const server = new MockServer({ user: "power" });
    server.p3.addToken("p-body", "OLD-PC", "EXPIRED");
    const t = server.p3.addToken("p-body", "KIM-PC");
    server.p3.addToken("p-other", "다른 프로젝트 PC");
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter initialEntries={[`${NEW}?tab=pc`]}>
        <App />
      </MemoryRouter>,
    );
    const table = await screen.findByRole("table", { name: "연결된 PC" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringMatching(/KIM-PC.*사용 중/), expect.stringMatching(/OLD-PC.*만료/)]);
    expect(within(rows[1]).queryByRole("button")).toBeNull();          // 만료 토큰은 폐기 버튼 없음
    fireEvent.click(within(rows[0]).getByRole("button", { name: "KIM-PC 폐기" }));
    await waitFor(() => expect(within(table).getAllByText("폐기됨").length).toBe(1));
    expect(server.p3.tokens.find((x) => x.id === t.id)!.state).toBe("REVOKED");
  });

  it("조회 사용자: 코드 만들기 비활성(권한 사유)", async () => {
    renderApp(`${NEW}?tab=pc`, "general");
    const b = (await screen.findByRole("button", { name: PC_CODE_BUTTON })) as HTMLButtonElement;
    await waitFor(() => expect(screen.getByTestId("user").textContent).toContain("조회"));
    expect(b.disabled).toBe(true);
    expect(b.getAttribute("title")).toMatch(/실행 권한/);
  });

  it("남은 시간 표기", () => {
    expect(remainText(15 * 60_000)).toBe("15:00");
    expect(remainText(61_500)).toBe("1:02");
    expect(remainText(-5)).toBe("0:00");
    expect(serverUrl("http://dash.local")).toBe("http://dash.local/esl");
  });
});

describe("서버 h3d 추출(§6)·동시 실행", () => {
  it("h3d 로 만든 Case: input_kind H3D, 결과 폴더 = _h3d/<폴더>/raw, ① 추출 step 첫째 H3D_EXTRACT", () => {
    const server = new MockServer({ user: "power" });
    const id = server.demoH3dExtract();
    const c = server.findCase(id)!;
    expect(c.input_kind).toBe("H3D");
    expect(c.results_dir).toMatch(/\\_h3d\\QN80H_rear40\\raw$/);
    const j = server.jobs.find((x) => x.case_id === id)!;
    expect(j.steps!.map((s) => s.step_key)).toEqual(["H3D_EXTRACT", "EXTRACT", "TSTAR_SCAN", "EXTRACT_REGISTER"]);
    expect(j.steps![0].kind).toBe("LOCAL");
    // 결과 폴더 입력 Case 는 H3D_EXTRACT 없음
    expect(server.jobs.find((x) => x.case_id === "c-new")!.steps![0].step_key).toBe("EXTRACT");
  });

  it("① 화면: '서버에서 추출 중(HyperView)' 단계·로그, h3d 확인, 대기열 동시 실행 2/2", async () => {
    const server = new MockServer({ user: "power" });
    const id = server.demoH3dExtract();
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter initialEntries={[`/p/p-body/c/${id}/stage/1`]}>
        <App />
      </MemoryRouter>,
    );
    const phase = await screen.findByTestId("h3d-extract-phase");
    expect(phase.textContent).toContain(H3D_RUNNING);
    const steps = screen.getByRole("list", { name: "추출 단계" });
    expect(within(steps).getAllByRole("listitem").map((li) => li.className)).toEqual(["running", "pending", "pending", "pending"]);
    expect(within(steps).getAllByRole("listitem")[0].textContent).toContain(H3D_RUNNING);
    await waitFor(() => expect(screen.getByLabelText("작업 로그").textContent).toMatch(/\[hw\] esl_h3d_extract\.tcl pass 1\/3/));
    expect(await screen.findByLabelText("h3d 확인 결과")).toBeTruthy();
    expect(screen.getByTestId("h3d-stage-note")).toBeTruthy();
    expect(screen.getByText("추출 결과 폴더(서버가 만듦)")).toBeTruthy();
    // v0.5.8: 우측 패널 폐지 — 칩 문구로 동시 실행 확인, 서랍을 열어 대기열 행 확인
    await waitFor(() => expect(screen.getByTestId("chip-queue").textContent).toContain("계산 2/2"));
    fireEvent.click(screen.getByTestId("chip-queue"));
    expect((await screen.findByTestId("queue-slots")).textContent).toBe("동시 실행 2/2");
    const q = screen.getByRole("region", { name: "계산 대기열" });
    expect(within(q).getAllByText("추출").length).toBe(2);
  });

  it("목 대기열: slots 개까지 동시 실행, 같은 Case 는 직렬", () => {
    const server = new MockServer({ user: "power" });
    const id = server.demoH3dExtract();
    server.handle("POST", `/cases/c-demo/jobs`, new URLSearchParams(), { job_type: "CASE_EXTRACT", params: {} });
    server.tick();
    const q = server.handle("GET", "/queue", new URLSearchParams(), null).body as { running_all: { case_id: string }[]; slots: number; queued: unknown[] };
    expect(q.slots).toBe(2);
    expect(q.running_all.map((j) => j.case_id).sort()).toEqual(["c-new", id].sort());
    expect(q.queued.length).toBe(1);
    server.drain();
    expect(server.findCase(id)!.extract_summary).toBeTruthy();
  });
});

describe("결과 받기(zip)", () => {
  it("Case 상단 메뉴에 '결과 받기(zip)' 유지(주 버튼 아님), ⑥ 단계는 없음", async () => {
    const { container } = renderApp("/p/p-body/c/c-demo/step/4");
    await screen.findByRole("heading", { level: 2, name: "④ 검증" });
    const btns = await screen.findAllByRole("button", { name: BUNDLE_LABEL });
    expect(btns.length).toBe(1);
    expect(within(screen.getByRole("navigation", { name: "Case 메뉴" })).getByRole("button", { name: BUNDLE_LABEL })).toBeTruthy();
    btns.forEach((b) => expect(b.hasAttribute("data-primary")).toBe(false));
    await waitFor(() => expect(primaries(container).length).toBe(1));
    fireEvent.click(btns[0]);
    await waitFor(() => expect((btns[0] as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByTestId("bundle-too-large")).toBeNull();
  });

  it("413 이면 경로 안내 + 복사", async () => {
    renderApp("/p/p-body/c/c-stale/stage/1");
    const menu = await screen.findByRole("navigation", { name: "Case 메뉴" });
    fireEvent.click(within(menu).getByRole("button", { name: BUNDLE_LABEL }));
    const box = await screen.findByTestId("bundle-too-large");
    expect(box.textContent).toContain(BUNDLE_TOO_LARGE);
    expect(within(box).getByRole("button", { name: "경로 복사" })).toBeTruthy();
    expect(box.textContent).toMatch(/rear56/);
  });

  it("404 BUNDLE_EMPTY 는 안내 문구", async () => {
    renderApp("/p/p-body/c/c-new/stage/1");
    const menu = await screen.findByRole("navigation", { name: "Case 메뉴" });
    fireEvent.click(within(menu).getByRole("button", { name: BUNDLE_LABEL }));
    expect(await screen.findByText(/받을 결과가 아직 없습니다/)).toBeTruthy();
  });

  it("라이브러리 분석 상세에도 있음", async () => {
    renderApp("/p/p-body/library/analyses/an-1");
    expect(await screen.findByRole("button", { name: BUNDLE_LABEL })).toBeTruthy();
  });
});

describe("버전·업데이트 내역", () => {
  it("VERSION = CHANGELOG 최상단, 파서 섹션", () => {
    expect(MOCK_VERSION.version).toBe(VERSION_TXT.trim());
    expect(MOCK_CHANGELOG[0].version).toBe(MOCK_VERSION.version);
    expect(Object.values(MOCK_CHANGELOG[0].sections).flat().length).toBeGreaterThan(0);
    const p = parseChangelog("# x\n## [1.2.0] - 2026-01-02\n### 추가\n- a\n- b\n### 기타\n- z\n### 수정\n- c\n## [1.1.0]\n### 변경\n- d\n");
    expect(p).toEqual([
      { version: "1.2.0", date: "2026-01-02", sections: { 추가: ["a", "b"], 수정: ["c"] } },
      { version: "1.1.0", date: null, sections: { 변경: ["d"] } },
    ]);
  });

  it("버전 비교·배지 규칙", () => {
    expect(cmpVersion("0.10.0", "0.9.9")).toBeGreaterThan(0);
    expect(cmpVersion("v0.4.0", "0.4.0")).toBe(0);
    expect(isNewVersion("0.4.0", null)).toBe(true);
    expect(isNewVersion("0.4.0", "0.3.0")).toBe(true);
    expect(isNewVersion("0.4.0", "0.4.0")).toBe(false);
    expect(isNewVersion("0.4.0", "0.5.0")).toBe(false);
  });

  it("상단 바 현재 버전(툴팁 commit·배포) + 새 버전 점 → 업데이트 내역에서 사라짐", async () => {
    localStorage.setItem("esl.lastSeenVersion", "0.3.0");
    renderApp("/");
    const chip = await screen.findByTestId("version-chip");
    expect(chip.textContent).toBe(`v${MOCK_VERSION.version}`);
    expect(chip.getAttribute("title")).toMatch(/commit 4d927c5 · 배포 /);
    expect(screen.getByTestId("version-new")).toBeTruthy();
    fireEvent.click(chip);
    expect(await screen.findByRole("heading", { name: "업데이트 내역" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId("version-new")).toBeNull());
    expect(localStorage.getItem("esl.lastSeenVersion")).toBe(MOCK_VERSION.version);
  });

  it("이미 본 버전이면 점 없음", async () => {
    localStorage.setItem("esl.lastSeenVersion", MOCK_VERSION.version);
    renderApp("/");
    await screen.findByTestId("version-chip");
    expect(screen.queryByTestId("version-new")).toBeNull();
  });

  it("업데이트 내역: 버전별 카드(지금 버전 표시), 추가·수정 구분", async () => {
    renderApp("/updates");
    const card = await screen.findByRole("article", { name: `v${MOCK_VERSION.version}` });
    expect(within(card).getByText("지금 버전")).toBeTruthy();
    expect(within(card).queryByText("추가") ?? within(card).queryByText("수정")).toBeTruthy(); // 지금 버전 구분은 릴리스마다 다름
    expect(within(await screen.findByRole("article", { name: "v0.5.0" })).getByText("추가")).toBeTruthy();
    expect(within(await screen.findByRole("article", { name: "v0.4.0" })).getByText("수정")).toBeTruthy();
    expect(screen.getAllByRole("article").length).toBe(MOCK_CHANGELOG.length);
    expect(screen.getByRole("article", { name: "v0.1.0" })).toBeTruthy();
  });
});

describe("사용 가이드", () => {
  it("상단 바 '사용 가이드' → 단계 카드 + 바로가기, FAQ", async () => {
    renderApp("/");
    fireEvent.click(await screen.findByRole("link", { name: "사용 가이드" }));
    expect(await screen.findByRole("heading", { level: 1, name: /사용 가이드/ })).toBeTruthy();
    for (const g of GUIDE) for (const c of g.cards) expect(screen.getByRole("heading", { level: 3, name: c.title })).toBeTruthy();
    expect(screen.getAllByRole("article").length).toBe(GUIDE.flatMap((g) => g.cards).length);
    for (const f of FAQ) expect(screen.getByText(f.q)).toBeTruthy();
    expect(screen.getAllByText("판단 기준").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText(/5 GB를 넘으면 화면이 PC 도구의 압축 모드를 권합니다/)).toBeTruthy();
  });

  it("바로가기: 새 Case → /p/<프로젝트>/cases/new, 단계 카드 → 최근 연 Case 의 단계", async () => {
    rememberCase({ projectId: "p-body", caseId: "c-demo", title: "후방 충돌 40kph" });
    renderApp("/guide");
    await screen.findByRole("heading", { level: 1, name: /사용 가이드/ });
    const card = (id: string) => document.getElementById(id) as HTMLElement;
    await waitFor(() => expect(within(card("new-case")).getByRole("link", { name: "새 Case 열기" }).getAttribute("href")).toBe("/p/p-body/cases/new"));
    expect(within(card("s2")).getByRole("link", { name: "② t*·지지점 열기" }).getAttribute("href")).toBe("/p/p-body/c/c-demo/step/2");
    fireEvent.click(within(card("s4")).getByRole("link", { name: "④ 검증 열기" }));
    expect(await screen.findByRole("heading", { level: 2, name: "④ 검증" })).toBeTruthy();
  });

  it("docs/manual/user.md 에 가이드 카드·FAQ 가 모두 있음", () => {
    const md = USER_MD;
    for (const g of GUIDE) {
      expect(md).toContain(g.title);
      for (const c of g.cards) expect(md).toContain(c.title);
    }
    for (const f of FAQ) expect(md).toContain(f.q);
  });
});
