// v0.6.0 업로드 속도(계약 esl_upload_speed.md): V-US-8 구 서버 순차, V-US-12 브라우저 병렬 업로더, V-US-26 화면(압축 모드·큰 h3d 안내·배지),
// V-US-30/31 목록 선택·선택 지우기, 이슈 #29 진행 중인 업로드 목록.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";
import { ApiError } from "../api/client";
import { putChunk } from "../api/p3";
import { MockServer, createMockFetch } from "../mock/server";
import { renderApp } from "../test/render";
import { DEFAULT_CHUNK, Uploader, movingRate, type PickedFile } from "../lib/uploader";
import { DONE_SHOW_MS, uploadStore } from "../lib/uploadStore";
import { SLIM_KEY, secText, slimLine } from "../lib/slim";
import { LIMIT_NOTE } from "../pages/newcase/UploadPanel";

const file = (name: string, size: number) => new File([new Uint8Array(size).fill(65)], name, { lastModified: 1760000000000 });
const bigFile = (name: string, size: number) => {
  const f = file(name, 3);
  Object.defineProperty(f, "size", { value: size });
  return f;
};
const NEW = "/p/p-body/cases/new";
const noSleep = { deps: { sleep: async () => undefined }, retryDelayMs: 0, tickMs: 0 };

function setup(chunk = 8) {
  const server = new MockServer({ user: "power" });
  server.p3.chunkSize = chunk;
  globalThis.fetch = createMockFetch(server);
  return server;
}
/** 20 + 5 + 9 + 80 바이트(청크 8 → 3 + 1 + 2 + 10 = 16 청크) */
const picks = (): PickedFile[] => [
  { file: file("model_0000.rad", 20), rel: "rad/model_0000.rad" },
  { file: file("inc_mat.inc", 5), rel: "rad/inc_mat.inc" },
  { file: file("inc_mesh.inc", 9), rel: "rad/inc_mesh.inc" },
  { file: file("drop.h3d", 80), rel: "h3d/drop.h3d" },
];

beforeEach(() => {
  localStorage.clear();
  uploadStore._reset();
});
afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("V-US-12 브라우저 병렬 업로더", () => {
  it("기본 청크 64 MB·동시 4개, 청크 번호 순서로 내보내고 버퍼는 N+1 이하", async () => {
    const server = setup(8);
    server.p3.putDelayMs = 3;
    const order: string[] = [];
    const up = new Uploader("p-body", "rear40", picks(), undefined, {
      ...noSleep,
      deps: {
        sleep: async () => undefined,
        putChunk: async (...a: Parameters<typeof putChunk>) => {
          order.push(`${a[1]}:${a[2]}`);
          return putChunk(...a);
        },
      },
    });
    expect(DEFAULT_CHUNK).toBe(64 * 1024 ** 2);
    expect(await up.run()).toBe(true);
    expect(server.p3.putCount).toBe(16);
    // 시작 순서 = 파일 순서 → 청크 번호 순서
    const want = picks().flatMap((p, i) => Array.from({ length: Math.ceil(p.file.size / 8) }, (_, k) => `${i}:${k * 8}`));
    expect(order).toEqual(want);
    expect(up.peakInflight).toBeGreaterThan(1);
    expect(up.peakInflight).toBeLessThanOrEqual(4);
    expect(up.peakBuffers).toBeLessThanOrEqual(5);
    expect(up.progress.parallel).toBe(4);
    expect(up.progress.protocol).toBe(2);
  });

  it("새 세션의 chunk_size 는 서버 기본 64 MB", async () => {
    const server = new MockServer({ user: "power" });
    globalThis.fetch = createMockFetch(server);
    const up = new Uploader("p-body", "x", [{ file: file("a_0000.rad", 5), rel: "rad/a_0000.rad" }], undefined, noSleep);
    await up.run();
    expect(up.chunk).toBe(DEFAULT_CHUNK);
  });

  it("서버 max_parallel 이 4 보다 작으면 그 값, 크면 4", async () => {
    const server = setup(8);
    server.p3.maxParallel = 2;
    server.p3.putDelayMs = 3;
    const a = new Uploader("p-body", "a", picks(), undefined, noSleep);
    await a.run();
    expect(a.peakInflight).toBeLessThanOrEqual(2);
    expect(a.progress.parallel).toBe(2);
    server.p3.maxParallel = 8;
    const b = new Uploader("p-body", "b", [{ file: file("b_0000.rad", 80), rel: "rad/b_0000.rad" }], undefined, noSleep);
    await b.run();
    expect(b.progress.parallel).toBe(4);
  });

  it("429 는 Retry-After 만큼 기다려 다시 보내며 재시도 횟수에 세지 않는다", async () => {
    const server = setup(8);
    server.p3.tooManyPuts = 3;
    const waits: number[] = [];
    const up = new Uploader("p-body", "r", picks(), undefined, { ...noSleep, deps: { sleep: async (ms: number) => void waits.push(ms) } });
    expect(await up.run()).toBe(true);
    expect(up.progress.retries).toBe(0);
    expect(waits.filter((w) => w === 1000).length).toBe(3);
    expect(server.p3.putCount).toBe(16);
  });

  it("일시 오류(503)·sha 불일치는 그 청크만 재시도(횟수 센다)", async () => {
    const server = setup(8);
    server.p3.failPuts = 2;
    server.p3.badShaPuts = 1;
    const up = new Uploader("p-body", "r", picks(), undefined, noSleep);
    expect(await up.run()).toBe(true);
    expect(up.progress.retries).toBe(3);
    expect(server.p3.putCount).toBe(16);
  });

  it("stop(): 진행 중 PUT 을 Abort 하고, 새 Uploader 는 서버가 받은 청크 범위만 건너뛴다", async () => {
    const server = setup(8);
    let aborted = 0;
    let n = 0;
    const up = new Uploader("p-body", "s", picks(), undefined, {
      ...noSleep,
      deps: {
        sleep: async () => undefined,
        putChunk: async (...a: Parameters<typeof putChunk>) => {
          if (++n === 7) {
            // 이 청크는 끝나지 않고 stop 을 기다린다
            queueMicrotask(() => up.stop());
            return new Promise((_, rej) => a[5]?.addEventListener("abort", () => (aborted++, rej(new ApiError(0, { code: "ABORTED", message: "멈춤" })))));
          }
          return putChunk(...a);
        },
      },
    });
    expect(await up.run()).toBe(false);
    expect(aborted).toBeGreaterThanOrEqual(1);
    expect(up.progress.phase).toBe("paused");
    const before = server.p3.putCount;
    expect(before).toBeGreaterThan(0);
    expect(before).toBeLessThan(16);
    const again = new Uploader("p-body", "s", picks(), undefined, noSleep);
    expect(await again.run()).toBe(true);
    expect(again.progress.resumed).toBe(true);
    expect(server.p3.putCount).toBe(16); // 받은 청크는 다시 보내지 않음
    expect(server.p3.uploads.size).toBe(1);
  });

  it("진행률은 받은 청크 바이트(서버 범위)·속도는 이동 평균", () => {
    const s = [
      { t: 0, sent: 0 },
      { t: 4000, sent: 400 },
      { t: 9000, sent: 900 },
      { t: 14000, sent: 1400 },
    ];
    // now=14000, 창 10 s → 4000 부터 → (1400-400)/10 s = 100 B/s
    expect(movingRate(s, 14000)).toBeCloseTo(100, 5);
    // 멈추면 분모가 now 까지라 내려간다
    expect(movingRate(s, 24000)!).toBeLessThan(100);
    // 창 안에 샘플이 하나뿐(큰 청크가 느리게 도착)이어도 0 이 되지 않고 바로 앞 샘플까지 넓혀 계산
    expect(movingRate([{ t: 0, sent: 0 }, { t: 30000, sent: 3000 }], 31000)).toBeGreaterThan(0);
    expect(movingRate([{ t: 0, sent: 0 }], 5000)).toBeNull();
    expect(secText(372)).toBe("6분 12초");
  });

  it("완료 직전 진행: sent = 받은 청크 합, total = 뺀 파일 제외", async () => {
    setup(8);
    const seen: number[] = [];
    const up = new Uploader("p-body", "p", picks(), (p) => seen.push(p.sent), noSleep);
    await up.run();
    expect(Math.max(...seen)).toBe(114);
    expect(up.progress.total).toBe(114);
    expect(seen.every((v, i) => i === 0 || v >= seen[i - 1])).toBe(true);
  });
});

describe("V-US-8 구 서버(protocol 없음) 순차", () => {
  it("protocol 필드가 없으면 기존 순차 경로: 동시 1, offset 순서, 완료", async () => {
    const server = setup(8);
    server.p3.protocol = 1;
    server.p3.putDelayMs = 3;
    const offs: string[] = [];
    const up = new Uploader("p-body", "old", picks(), undefined, {
      ...noSleep,
      deps: {
        sleep: async () => undefined,
        putChunk: async (...a: Parameters<typeof putChunk>) => {
          offs.push(`${a[1]}:${a[2]}`);
          return putChunk(...a);
        },
      },
    });
    expect(await up.run()).toBe(true);
    expect(up.progress.protocol).toBe(1);
    expect(up.progress.parallel).toBe(1);
    expect(up.peakInflight).toBe(1);
    expect(server.p3.putCount).toBe(16);
    expect(offs[0]).toBe("0:0");
    expect(up.canRemove).toBe(false);
    await expect(up.remove([0])).rejects.toThrow(/하나씩/);
    expect((await up.complete()).ok).toBe(true);
  });
});

describe("파일 빼기(US-17)·세션 취소", () => {
  it("remove: 큐에서 빼고 DELETE, total 에서 제외, 같은 이름 다시 등록 가능", async () => {
    const server = setup(8);
    const up = new Uploader("p-body", "rm", picks(), undefined, noSleep);
    expect(await up.run()).toBe(true);
    await up.remove([2]);
    expect(server.p3.removedLog).toEqual(["up-1:2"]);
    expect(up.progress.removed).toEqual([2]);
    expect(up.progress.total).toBe(105);
    const r = await up.complete();
    expect(r.missing_includes).toEqual(["rad/inc_mesh.inc"]);
    const start = await up.register([{ file: file("inc_mesh.inc", 9), rel: "rad/inc_mesh.inc" }]);
    expect(start).toBe(4);
    expect(await up.run()).toBe(true);
    expect((await up.complete()).ok).toBe(true);
  });

  it("BUSY 는 몇 번 다시 시도하고, 계속 막히면 오류와 함께 원상복구", async () => {
    const server = setup(8);
    const up = new Uploader("p-body", "busy", picks(), undefined, noSleep);
    await up.run();
    server.p3.busyFiles.add(1);
    await expect(up.remove([1])).rejects.toMatchObject({ code: "UPLOAD_FILE_BUSY" });
    expect(up.progress.removed).toEqual([]);
    expect(up.progress.total).toBe(114);
  });

  it("COMPLETED 후 파일 빼기 → 서버 OPEN, phase uploaded(재검사 필요); Case 가 쓰는 업로드는 UPLOAD_IN_USE", async () => {
    const server = setup(8);
    const up = new Uploader("p-body", "done", picks(), undefined, noSleep);
    await up.run();
    await up.complete();
    expect(up.progress.phase).toBe("done");
    await up.remove([0]);
    expect(up.progress.phase).toBe("uploaded");
    expect(server.p3.uploads.get(up.uploadId!)!.state).toBe("OPEN");
    server.p3.uploads.get(up.uploadId!)!.inUse = true;
    // OPEN 이 되었으니 다시 complete 해 COMPLETED 로 둔 뒤 사용 중 표시
    await up.register([{ file: file("model_0000.rad", 20), rel: "rad/model_0000.rad" }]).catch(() => undefined);
  });

  it("cancel: 열린 세션은 DELETE /uploads/{id}, COMPLETED 면 파일을 모두 뺀다", async () => {
    const server = setup(8);
    const a = new Uploader("p-body", "c1", picks(), undefined, noSleep);
    await a.run();
    await a.cancel();
    expect(server.p3.uploads.get("up-1")!.state).toBe("CANCELED");
    expect(a.uploadId).toBeNull();
    const b = new Uploader("p-body", "c2", picks().map((p) => ({ ...p, file: file(p.file.name + "x".repeat(0), p.file.size + 1) })), undefined, noSleep);
    await b.run();
    await b.complete();
    await b.cancel();
    expect(server.p3.removedLog.filter((x) => x.startsWith("up-2:")).length).toBe(4);
  });
});

describe("V-US-30/31 업로드 목록 선택·지우기", () => {
  const pickAll = async (server: MockServer) => {
    await screen.findByRole("heading", { name: "새 Case" });
    server.p3.chunkSize = 8;
    fireEvent.change(screen.getByLabelText("① rad · include 파일 파일"), { target: { files: [file("model_0000.rad", 20), file("inc_mat.inc", 5), file("inc_mesh.inc", 9)] } });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 80)] } });
    return screen.findByRole("table", { name: "올릴 파일" });
  };
  const checks = (t: HTMLElement) => within(t).getAllByRole("checkbox", { name: "파일 선택" }) as HTMLInputElement[];

  it("행 체크·머리글 전체/해제·일부 = indeterminate, 선택 0 → 지우기 비활성 + 사유", async () => {
    const { server } = renderApp(NEW);
    const t = await pickAll(server);
    const all = within(t).getByRole("checkbox", { name: "전체 선택" }) as HTMLInputElement;
    const clear = screen.getByTestId("clear-btn") as HTMLButtonElement;
    expect(clear.disabled).toBe(true);
    expect(clear.textContent).toBe("지우기(0)");
    expect(screen.getByTestId("clear-reason").textContent).toBe("지울 파일을 선택하세요");
    fireEvent.click(checks(t)[0]);
    expect(all.indeterminate).toBe(true);
    expect(all.checked).toBe(false);
    expect(clear.disabled).toBe(false);
    expect(clear.textContent).toBe("지우기(1)");
    expect(screen.queryByTestId("clear-reason")).toBeNull();
    fireEvent.click(all); // 일부 선택 → 전체 선택
    expect(checks(t).every((c) => c.checked)).toBe(true);
    expect(all.indeterminate).toBe(false);
    expect(clear.textContent).toBe("지우기(4)");
    fireEvent.click(all); // 전체 → 해제
    expect(checks(t).every((c) => !c.checked)).toBe(true);
    expect(clear.textContent).toBe("지우기(0)");
  });

  it("세션 없음: 선택한 것만 목록에서 제거, 전체 선택하면 비움(서버 호출 없음)", async () => {
    const { server } = renderApp(NEW);
    const t = await pickAll(server);
    fireEvent.click(checks(t)[0]); // 정렬: inc_mat, inc_mesh, model_0000.rad, h3d
    fireEvent.click(screen.getByTestId("clear-btn"));
    await waitFor(() => expect(within(t).getAllByRole("row").length).toBe(4));
    expect(within(t).queryByText("rad/inc_mat.inc")).toBeNull();
    expect(server.p3.uploads.size).toBe(0);
    fireEvent.click(within(t).getByRole("checkbox", { name: "전체 선택" }));
    fireEvent.click(screen.getByTestId("clear-btn"));
    await waitFor(() => expect(screen.queryByRole("table", { name: "올릴 파일" })).toBeNull());
    expect(server.p3.uploads.size).toBe(0);
  });

  it("전송 중 파일은 선택 불가, 나머지는 지울 수 있다(DELETE·큐 제외) — 같은 이름 다시 추가", async () => {
    const { server } = renderApp(NEW);
    server.p3.hangAfter = 2;
    const t = await pickAll(server);
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    await waitFor(() => expect(server.p3.putCount).toBe(2));
    await waitFor(() => expect(checks(t).some((c) => c.disabled)).toBe(true));
    const rows = within(t).getAllByRole("row").slice(1);
    // 지금 청크를 보내는 파일은 선택 칸 비활성 + 툴팁
    const busyRow = rows.map((r) => within(r).getByRole("checkbox") as HTMLInputElement).find((c) => c.disabled)!;
    expect(busyRow.parentElement!.getAttribute("title")).toBe("전송 중 — 멈춤 후 선택");
    const last = within(rows[3]).getByRole("checkbox") as HTMLInputElement;
    expect(last.disabled).toBe(false);
    fireEvent.click(last);
    fireEvent.click(screen.getByTestId("clear-btn"));
    await waitFor(() => expect(server.p3.removedLog).toEqual(["up-1:3"]));
    await waitFor(() => expect(within(t).queryByText("h3d/drop.h3d")).toBeNull());
    // 같은 이름을 다시 고르면 세션에 등록(addUploadFiles)
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 80)] } });
    await waitFor(() => expect(within(t).getByText("h3d/drop.h3d")).toBeTruthy());
    expect(server.p3.uploads.get("up-1")!.files.length).toBe(5);
  });

  it("COMPLETED 후 일부 지우기 → 파일 DELETE → 자동 재검사(누락 include 표시), 재검사 문구", async () => {
    const { server } = renderApp(NEW);
    const t = await pickAll(server);
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
    expect((screen.getByTestId("clear-btn") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(checks(t)[1]); // inc_mesh.inc
    fireEvent.click(screen.getByTestId("clear-btn"));
    expect(await screen.findByTestId("missing-includes")).toBeTruthy();
    expect(server.p3.removedLog).toEqual(["up-1:1"]);
    expect(screen.getByTestId("recheck-note").textContent).toMatch(/다시 확인했습니다/);
    expect(server.p3.uploads.get("up-1")!.state).toBe("OPEN");
  });

  it("COMPLETED 후 전체 선택 지우기 → 세션 취소 불가(409)라 파일을 모두 빼고 목록 비움", async () => {
    const { server } = renderApp(NEW);
    const t = await pickAll(server);
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
    fireEvent.click(within(t).getByRole("checkbox", { name: "전체 선택" }));
    fireEvent.click(screen.getByTestId("clear-btn"));
    await waitFor(() => expect(screen.queryByRole("table", { name: "올릴 파일" })).toBeNull());
    expect(server.p3.removedLog.length).toBe(4);
  });

  it("OPEN 전체 선택 지우기 = 세션 취소(DELETE /uploads/{id}) + 저장된 세션 잊기", async () => {
    const { server } = renderApp(NEW);
    server.p3.hangAfter = 0;
    const t = await pickAll(server);
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    await waitFor(() => expect(server.p3.uploads.size).toBe(1));
    // 전송 중이라 선택 불가 — 멈춤 후에 가능
    await waitFor(() => expect(checks(t).some((c) => c.disabled)).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "멈춤" }));
    await waitFor(() => expect(checks(t).every((c) => !c.disabled)).toBe(true));
    expect(Object.keys(localStorage).some((k) => k.startsWith("esl.upload."))).toBe(true);
    fireEvent.click(within(t).getByRole("checkbox", { name: "전체 선택" }));
    fireEvent.click(screen.getByTestId("clear-btn"));
    await waitFor(() => expect(server.p3.uploads.get("up-1")!.state).toBe("CANCELED"));
    await waitFor(() => expect(screen.queryByRole("table", { name: "올릴 파일" })).toBeNull());
    expect(Object.keys(localStorage).some((k) => k.startsWith("esl.upload."))).toBe(false);
  });

  it("UPLOAD_IN_USE: 오류 줄 '이 업로드로 만든 Case가 있어 뺄 수 없습니다'", async () => {
    const { server } = renderApp(NEW);
    const t = await pickAll(server);
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
    server.p3.uploads.get("up-1")!.inUse = true;
    fireEvent.click(checks(t)[0]);
    fireEvent.click(screen.getByTestId("clear-btn"));
    expect(await screen.findByText("이 업로드로 만든 Case가 있어 뺄 수 없습니다")).toBeTruthy();
    expect(within(t).getByText("rad/model_0000.rad")).toBeTruthy();
  });
});

describe("V-US-26 화면: 압축 모드·큰 h3d 안내·배지", () => {
  it("PC 탭: 압축 모드 체크 기본 ON, 도움말 2줄·사용법 줄, 해제하면 'O' 안내 + localStorage esl.slim.v1", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.click(screen.getByRole("tab", { name: "PC에서 추출해 올리기" }));
    const box = await screen.findByTestId("slim-box");
    const check = within(box).getByTestId("slim-check") as HTMLInputElement;
    expect(check.checked).toBe(true);
    expect(within(box).getByText("압축 모드(권장)")).toBeTruthy();
    const help = screen.getByTestId("slim-help").textContent!;
    expect(help).toContain("변위·최대 변형률(Mid)·소성 변형률(Mid)의 전 프레임");
    expect(help).toContain("원본 h3d는 PC에 그대로 남습니다");
    expect(help).toContain("다른 파트나 다른 결과로 다시 해석할 계획이면 해제하세요");
    expect(screen.getByTestId("slim-usage").textContent).toMatch(/Enter.*압축/);
    expect(screen.getByTestId("slim-usage").textContent).toContain("기존 PC 추출");
    fireEvent.click(check);
    expect(localStorage.getItem(SLIM_KEY)).toBe("0");
    expect(screen.getByTestId("slim-usage").textContent).toMatch(/\bO\b.*원본/);
    expect(screen.getByTestId("slim-usage").textContent).toContain("/original");
  });

  it("저장소에 0 이 있으면 해제 상태로 열림, 저장소가 막혀도 기본 ON 으로 동작", async () => {
    localStorage.setItem(SLIM_KEY, "0");
    const { unmount } = renderApp(`${NEW}?tab=pc`);
    expect(((await screen.findByTestId("slim-check")) as HTMLInputElement).checked).toBe(false);
    unmount();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderApp(`${NEW}?tab=pc`);
    const c = (await screen.findByTestId("slim-check")) as HTMLInputElement;
    expect(c.checked).toBe(true);
    fireEvent.click(c);
    expect(c.checked).toBe(false);
  });

  it("5 GB 초과 h3d 를 고르면 PC 도구 압축 모드 권장 한 줄 + 탭 링크, 작으면 없음", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [bigFile("small.h3d", 4 * 1024 ** 3)] } });
    await screen.findByRole("table", { name: "올릴 파일" });
    expect(screen.queryByTestId("big-h3d-hint")).toBeNull();
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [bigFile("drop.h3d", 48.2 * 1024 ** 3)] } });
    const hint = await screen.findByTestId("big-h3d-hint");
    expect(hint.textContent).toContain("48.20 GB");
    expect(hint.textContent).toContain("압축 모드");
    fireEvent.click(within(hint).getByRole("button", { name: /PC에서 추출해 올리기/ }));
    expect(await screen.findByTestId("slim-box")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "PC에서 추출해 올리기" }).getAttribute("aria-selected")).toBe("true");
  });

  it("예상 시간 문구는 사내망 60 MB/s 가정", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 30)] } });
    expect((await screen.findByTestId("upload-summary")).textContent).toContain("사내망 60 MB/s 가정");
  });

  it("?upload= 화면: 압축 모드 배지 + '48.2 GB → 2.9 GB · hvtrans 6분 12초 · 파트 1234 chassis_rear'", async () => {
    const server = setup(8);
    const up = new Uploader("p-body", "pc", picks(), undefined, noSleep);
    await up.run();
    const u = server.p3.uploads.get(up.uploadId!)!;
    u.files[3].meta = {
      kind: "h3d_slim",
      v: 1,
      source_name: "QN80H.h3d",
      source_bytes: Math.round(48.2 * 1024 ** 3),
      slim_bytes: Math.round(2.9 * 1024 ** 3),
      hvtrans_sec: 372,
      part_id: 1234,
      part_title: "chassis_rear",
      results: [{ type: "Displacement" }, { type: "Max_Strain", layer: "Mid" }],
      cfg: "BeginParts",
    };
    expect(slimLine(u.files[3].meta!)).toBe("48.20 GB → 2.90 GB · hvtrans 6분 12초 · 파트 1234 chassis_rear");
    render(
      <MemoryRouter initialEntries={[`${NEW}?upload=${up.uploadId}`]}>
        <App />
      </MemoryRouter>,
    );
    const m = await screen.findByTestId("pc-upload-mode");
    expect(m.textContent).toContain("압축 모드");
    expect(m.textContent).toContain("hvtrans 6분 12초");
    expect(m.getAttribute("title")).toContain("원본 QN80H.h3d");
  });

  it("① 입력(Stage1): input_h3d_meta.kind = h3d_slim 이면 '압축 모드' 배지·cfg 보기, 원본이면 없음", async () => {
    const server = new MockServer({ user: "power" });
    const id = server.demoH3dExtract();
    const c = server.cases.find((x) => x.id === id)!;
    c.input_h3d_meta = { kind: "h3d_slim", v: 1, source_bytes: 3 * 1024 ** 3, slim_bytes: 200 * 1024 ** 2, hvtrans_sec: 60, part_id: 10, part_title: "chassis_rear", cfg: "BeginParts\nEnd", results: [{ type: "Displacement" }] };
    globalThis.fetch = createMockFetch(server);
    const { unmount } = render(
      <MemoryRouter initialEntries={[`/p/p-body/c/${id}/stage/1`]}>
        <App />
      </MemoryRouter>,
    );
    const badge = await screen.findByTestId("slim-badge");
    expect(badge.textContent).toContain("압축 모드");
    expect(badge.textContent).toContain("3.00 GB → 200.0 MB");
    expect(within(badge).getByText("cfg 보기")).toBeTruthy();
    unmount();
    c.input_h3d_meta = { kind: "h3d_original", v: 1 };
    render(
      <MemoryRouter initialEntries={[`/p/p-body/c/${id}/stage/1`]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByLabelText("h3d 확인 결과");
    expect(screen.queryByTestId("slim-badge")).toBeNull();
  });

  it("Case 만들기가 업로드 메타를 input_h3d_meta 로 이어 준다(목 서버)", async () => {
    const server = setup(8);
    const up = new Uploader("p-body", "pc", picks(), undefined, noSleep);
    await up.run();
    const u = server.p3.uploads.get(up.uploadId!)!;
    u.files[3].meta = { kind: "h3d_slim", v: 1, slim_bytes: 80 };
    const r = await up.complete();
    const res = await fetch("/esl/api/cases", {
      method: "POST",
      headers: { "X-ESL-Request": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: "p-body", folder_name: "M1", title: "m", rad_path: r.rad_path, h3d_path: r.h3d_path, part_title: "chassis_rear" }),
    });
    expect(((await res.json()) as { input_h3d_meta: { kind: string } }).input_h3d_meta.kind).toBe("h3d_slim");
  });
});

describe("이슈 #29 진행 중인 업로드(사용자당 한도)", () => {
  it("열린 업로드가 없으면 목록을 숨긴다", async () => {
    renderApp(NEW);
    await screen.findByRole("heading", { name: "새 Case" });
    await waitFor(() => expect(screen.getByLabelText("① rad · include 파일 파일")).toBeTruthy());
    expect(screen.queryByTestId("open-uploads")).toBeNull();
  });

  it("목록: 이름·파일 수·받은 양/전체·시각·상태(검사 문제), 접힘; 이어서 열기 = 받은 양 보기, 취소 = 확인 후 DELETE", async () => {
    const { server } = renderApp(NEW, "power", (s) => {
      s.p3.chunkSize = 8;
      s.p3.seedUpload("p-body", "QN80H_a", [{ rel: "rad/a_0000.rad", size: 20, received: 20 }, { rel: "h3d/a.h3d", size: 80, received: 16 }]);
      s.p3.seedUpload("p-body", "QN90D_b", [{ rel: "rad/b_0000.rad", size: 20, received: 20 }], { problems: ["rad 파일(_0000.rad)이 없습니다"] });
    });
    const box = await screen.findByTestId("open-uploads");
    expect((box as HTMLDetailsElement).open).toBe(false);
    expect(box.textContent).toContain("진행 중인 업로드 (2)");
    const a = screen.getByTestId("open-upload-up-1");
    expect(a.textContent).toContain("QN80H_a");
    expect(a.textContent).toMatch(/36 B \/ 100 B/);
    expect(a.textContent).toContain("받는 중 36%");
    const b = screen.getByTestId("open-upload-up-2");
    expect(b.textContent).toContain("검사 문제");
    expect(b.textContent).toContain("rad 파일(_0000.rad)이 없습니다");
    // 이어서 열기 → ?upload= 로 받은 양 표시
    fireEvent.click(within(a).getByRole("button", { name: "이어서 열기" }));
    const files = await screen.findByTestId("partial-files");
    expect(files.textContent).toContain("h3d/a.h3d · 16 B / 80 B");
    // 취소: 확인 대화(파일은 _backup 으로)
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValue(true);
    const b2 = await screen.findByTestId("open-upload-up-2");
    fireEvent.click(within(b2).getByRole("button", { name: "취소" }));
    expect(confirm.mock.calls[0][0]).toContain("_backup");
    expect(confirm.mock.calls[0][0]).toContain("삭제되지 않고");
    expect(server.p3.uploads.get("up-2")!.state).toBe("OPEN"); // 첫 확인은 거절
    fireEvent.click(within(b2).getByRole("button", { name: "취소" }));
    await waitFor(() => expect(server.p3.uploads.get("up-2")!.state).toBe("CANCELED"));
    await waitFor(() => expect(screen.queryByTestId("open-upload-up-2")).toBeNull());
  });

  it("UPLOAD_LIMIT: 목록 자동 펼침 + 오류 아래 안내 한 줄 → 하나 취소하면 이어서 올릴 수 있다", async () => {
    const { server } = renderApp(NEW, "power", (s) => {
      s.p3.chunkSize = 8;
      s.p3.seedUpload("p-body", "old1", [{ rel: "rad/x_0000.rad", size: 10, received: 10 }]);
      s.p3.seedUpload("p-body", "old2", [{ rel: "rad/y_0000.rad", size: 10, received: 3 }]);
    });
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("① rad · include 파일 파일"), { target: { files: [file("model_0000.rad", 20), file("inc_mat.inc", 5), file("inc_mesh.inc", 9)] } });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 30)] } });
    fireEvent.click(await screen.findByRole("button", { name: "올리기" }));
    expect(await screen.findByText(/진행 중인 업로드가 2개입니다/)).toBeTruthy();
    expect((await screen.findByTestId("upload-limit-note")).textContent).toBe(LIMIT_NOTE);
    await waitFor(() => expect((screen.getByTestId("open-uploads") as HTMLDetailsElement).open).toBe(true));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(within(screen.getByTestId("open-upload-up-1")).getByRole("button", { name: "취소" }));
    await waitFor(() => expect(server.p3.uploads.get("up-1")!.state).toBe("CANCELED"));
    fireEvent.click(await screen.findByRole("button", { name: "이어 올리기" }));
    expect(await screen.findByText(/rad·h3d 확인됨/)).toBeTruthy();
  });

  it("v0.6.0 정합: UPLOAD_LIMIT detail.open_uploads(서버 키 id·received_bytes·total_bytes·problems_count)를 errorOpen 으로", async () => {
    const server = setup(8);
    server.p3.seedUpload("p-body", "old1", [{ rel: "rad/x_0000.rad", size: 10, received: 10 }]);
    server.p3.seedUpload("p-body", "old2", [{ rel: "rad/y_0000.rad", size: 16, received: 8 }], { problems: ["include 누락"] });
    let last: Parameters<NonNullable<ConstructorParameters<typeof Uploader>[3]>>[0] | null = null;
    const up = new Uploader("p-body", "new", picks(), (p) => (last = p), noSleep);
    expect(await up.run()).toBe(false);
    expect(last!.errorCode).toBe("UPLOAD_LIMIT");
    const byName = Object.fromEntries(last!.errorOpen.map((o) => [o.name, o]));
    expect(Object.keys(byName).sort()).toEqual(["old1", "old2"]);
    expect(byName.old1).toMatchObject({ id: "up-1", received_bytes: 10, total_bytes: 10, problems_count: 0 });
    expect(byName.old2).toMatchObject({ id: "up-2", received_bytes: 8, total_bytes: 16, problems_count: 1 });
    expect(typeof byName.old1.created_at).toBe("string");
  });

  it("v0.6.0 정합: 새 세션 청크 크기 = 서버 응답 chunk_size(하드코딩 64 MB 아님)", async () => {
    const server = setup(8);
    const sizes: number[] = [];
    const up = new Uploader("p-body", "c8", picks(), undefined, {
      ...noSleep,
      deps: {
        sleep: async () => undefined,
        putChunk: async (...a: Parameters<typeof putChunk>) => {
          const d = a[3];
          sizes.push(d instanceof ArrayBuffer ? d.byteLength : d.size);
          return putChunk(...a);
        },
      },
    });
    expect(await up.run()).toBe(true);
    expect(server.p3.uploads.get(up.uploadId!)!.chunk).toBe(8);
    expect(Math.max(...sizes)).toBe(8);
  });

  it("v0.6.0 정합: ?upload= 화면 문구는 업로드 client.name 으로 구분(esl-pc = 'PC에서 올림', 브라우저 = '브라우저에서 올림')", async () => {
    const server = setup(8);
    const web = new Uploader("p-body", "web", picks(), undefined, noSleep);
    expect(await web.run()).toBe(true);
    expect(server.p3.uploads.get(web.uploadId!)!.client?.name).toBe("esl-web");
    const r1 = render(
      <MemoryRouter initialEntries={[`${NEW}?upload=${web.uploadId}`]}>
        <App />
      </MemoryRouter>,
    );
    const p1 = await screen.findByTestId("pc-upload");
    await waitFor(() => expect(p1.textContent).toContain("브라우저에서 올림"));
    expect(p1.textContent).not.toContain("PC에서 올림");
    r1.unmount();

    const pc = new Uploader("p-body", "pc", picks(), undefined, noSleep);
    expect(await pc.run()).toBe(true);
    server.p3.uploads.get(pc.uploadId!)!.client = { name: "esl-pc", version: "0.6.0" };
    render(
      <MemoryRouter initialEntries={[`${NEW}?upload=${pc.uploadId}`]}>
        <App />
      </MemoryRouter>,
    );
    const p2 = await screen.findByTestId("pc-upload");
    await waitFor(() => expect(p2.textContent).toContain("PC에서 올림"));
    expect(p2.textContent).toContain("PC 도구");
  });
});

describe("업로드 유지(페이지 이동·상단 진행 표시·beforeunload)", () => {
  let loc = "";
  const Probe = () => {
    const l = useLocation();
    loc = l.pathname + l.search;
    return null;
  };
  const renderAt = (server: MockServer, path: string) => {
    globalThis.fetch = createMockFetch(server);
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Probe />
        <App />
      </MemoryRouter>,
    );
  };
  const pickAll = async () => {
    await screen.findByRole("heading", { name: "새 Case" });
    fireEvent.change(screen.getByLabelText("① rad · include 파일 파일"), { target: { files: [file("model_0000.rad", 20), file("inc_mat.inc", 5), file("inc_mesh.inc", 9)] } });
    fireEvent.change(screen.getByLabelText("② h3d 결과 파일 파일"), { target: { files: [file("drop.h3d", 80)] } });
    await screen.findByRole("table", { name: "올릴 파일" });
  };

  it("세션이 생기면 URL 이 ?upload=<id> 로 바뀌고(replace), 다른 페이지에 갔다 와도 같은 업로드가 계속된다", async () => {
    const server = new MockServer({ user: "power" });
    server.p3.chunkSize = 8;
    server.p3.putDelayMs = 25;
    renderAt(server, NEW);
    await pickAll();
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    await waitFor(() => expect(loc).toBe(`${NEW}?upload=up-1`));
    const chip = await screen.findByTestId("upload-chip");
    expect(chip.textContent).toMatch(/^업로드 \d+%$/);
    // 라이브러리로 이동 — 전송은 계속
    fireEvent.click(screen.getByRole("link", { name: "ESL 라이브러리" }));
    await waitFor(() => expect(loc).toMatch(/library/));
    expect(screen.queryByRole("table", { name: "올릴 파일" })).toBeNull();
    const before = server.p3.putCount;
    await waitFor(() => expect(server.p3.putCount).toBeGreaterThan(before));
    // 상단 표시 클릭 → 그 업로드 화면으로 복귀(같은 세션·목록·진행률)
    fireEvent.click(screen.getByTestId("upload-chip"));
    await waitFor(() => expect(loc).toBe(`${NEW}?upload=up-1`));
    const t = await screen.findByRole("table", { name: "올릴 파일" });
    expect(within(t).getByText("h3d/drop.h3d")).toBeTruthy();
    expect(await screen.findByText(/rad·h3d 확인됨/, undefined, { timeout: 4000 })).toBeTruthy();
    expect(server.p3.uploads.size).toBe(1);
    expect(server.p3.putCount).toBe(16);
    // 끝나면 '업로드 완료 — 열기'
    expect(screen.getByTestId("upload-chip").textContent).toBe("업로드 완료 — 열기");
    expect(uploadStore.chip(Date.now() + DONE_SHOW_MS + 100)).toBeNull();
  });

  it("화면이 사라져도 저장소가 Uploader 를 쥐고, ?upload=<id> 로 다시 열면 같은 세션에 붙는다(진행률 표시)", async () => {
    const server = new MockServer({ user: "power" });
    server.p3.chunkSize = 8;
    server.p3.hangAfter = 3;
    const view = renderAt(server, NEW);
    await pickAll();
    fireEvent.click(screen.getByRole("button", { name: "올리기" }));
    await waitFor(() => expect(loc).toBe(`${NEW}?upload=up-1`));
    await waitFor(() => expect(server.p3.putCount).toBe(3));
    view.unmount();
    expect(uploadStore.active().length).toBe(1);
    renderAt(server, `${NEW}?upload=up-1`);
    const t = await screen.findByRole("table", { name: "올릴 파일" });
    expect(within(t).getAllByRole("row").length).toBe(5);
    expect(screen.getByRole("progressbar")).toBeTruthy();
    expect(screen.getByText(/올리는 중/)).toBeTruthy();
    expect(server.p3.uploads.size).toBe(1);
  });

  it("상단 표시: 여러 건이면 '업로드 2건 · N%', 클릭하면 그 업로드 화면", async () => {
    const server = new MockServer({ user: "power" });
    server.p3.chunkSize = 8;
    server.p3.hangAfter = 4;
    globalThis.fetch = createMockFetch(server);
    const mk = (n: string) => [
      { file: file(`${n}_0000.rad`, 20), rel: `rad/${n}_0000.rad` },
      { file: file("drop.h3d", 80), rel: "h3d/drop.h3d" },
    ];
    const a = uploadStore.create("p-body", "a", mk("a"), noSleep);
    const b = uploadStore.create("p-body", "b", mk("b"), noSleep);
    void uploadStore.start(a.key);
    void uploadStore.start(b.key);
    renderAt(server, "/p/p-body");
    await waitFor(() => expect(screen.getByTestId("upload-chip").textContent).toMatch(/^업로드 2건 · \d+%$/));
    fireEvent.click(screen.getByTestId("upload-chip"));
    await waitFor(() => expect(loc).toMatch(/cases\/new\?upload=up-/));
  });

  it("beforeunload 경고는 활성 전송 중에만 등록되고 멈추면 해제된다", async () => {
    const add = vi.spyOn(window, "addEventListener");
    const rem = vi.spyOn(window, "removeEventListener");
    const server = new MockServer({ user: "power" });
    server.p3.chunkSize = 8;
    server.p3.hangAfter = 2;
    globalThis.fetch = createMockFetch(server);
    const calls = (spy: typeof add) => spy.mock.calls.filter((c) => c[0] === "beforeunload").length;
    expect(calls(add)).toBe(0);
    const s = uploadStore.create("p-body", "u", picks(), noSleep);
    void uploadStore.start(s.key);
    await waitFor(() => expect(calls(add)).toBe(1));
    const handler = add.mock.calls.find((c) => c[0] === "beforeunload")![1] as (e: BeforeUnloadEvent) => void;
    const ev = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    handler(ev);
    expect(ev.defaultPrevented).toBe(true);
    await waitFor(() => expect(server.p3.putCount).toBe(2));
    expect(calls(add)).toBe(1); // 갱신이 여러 번이어도 한 번만 등록
    s.uploader.stop();
    await waitFor(() => expect(calls(rem)).toBe(1));
    expect(uploadStore.active().length).toBe(0);
  });
});
