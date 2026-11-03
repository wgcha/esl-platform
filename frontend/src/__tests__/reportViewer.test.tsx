// v0.12.5 보고서 화면 안 보기(ReportViewer): sandbox iframe·src·다운로드 링크·보고서 없음·생성 중 사유·mock srcdoc.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { REPORT_NONE, ReportViewer } from "../components/ReportViewer";

const URL_ = "/esl/api/library/analyses/an-1/report";
const html = "<!doctype html><title>r</title><h1>보고서</h1><script>document.title='x'</script>";

function stubFetch(status: number, body = html) {
  const f = vi.fn(async () => new Response(body, { status, headers: { "Content-Type": "text/html" } }));
  globalThis.fetch = f as unknown as typeof fetch;
  return f;
}
const g = globalThis as unknown as { __MOCK__: boolean };

afterEach(() => {
  g.__MOCK__ = false;
});

describe("ReportViewer", () => {
  it("보고서 있음: iframe sandbox='allow-scripts'(allow-same-origin 없음)·src = 보고서 URL, [보고서 받기] = ?download=1 링크 1개, [새 탭에서 열기] 보조", async () => {
    stubFetch(200);
    const { container } = render(<ReportViewer url={URL_} filename="analysis_an-1_report.html" title="종합분석 보고서" />);
    const frame = (await screen.findByTitle("종합분석 보고서")) as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("src")).toBe(URL_);
    expect(frame.hasAttribute("srcdoc")).toBe(false);
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(Number.parseInt(frame.style.height, 10)).toBeGreaterThanOrEqual(360);
    const prim = container.querySelectorAll("[data-primary]");
    expect(prim).toHaveLength(1);
    expect(prim[0].tagName).toBe("A");
    expect(prim[0].textContent).toBe("보고서 받기");
    expect(prim[0].getAttribute("href")).toBe(`${URL_}?download=1`);
    expect(prim[0].getAttribute("download")).toBe("analysis_an-1_report.html");
    const tab = screen.getByRole("link", { name: "새 탭에서 열기" });
    expect([tab.getAttribute("href"), tab.getAttribute("target")]).toEqual([URL_, "_blank"]);
    expect(tab.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("보고서 없음(404): iframe 없이 사유, [보고서 받기] 비활성 + 같은 사유, 새 탭 링크 없음", async () => {
    stubFetch(404, JSON.stringify({ detail: { code: "REPORT_NOT_FOUND" } }));
    const { container } = render(<ReportViewer url={URL_} filename="r.html" />);
    expect((await screen.findByTestId("report-reason")).textContent).toBe(REPORT_NONE);
    expect(container.querySelector("iframe")).toBeNull();
    const b = container.querySelector("button[data-primary]") as HTMLButtonElement;
    expect([b.textContent, b.disabled, b.parentElement!.getAttribute("title")]).toEqual(["보고서 받기", true, REPORT_NONE]);
    expect(screen.queryByRole("link", { name: "새 탭에서 열기" })).toBeNull();
  });

  it("생성 중(reason): 서버에 묻지 않고 기존 사유 표시", async () => {
    const f = stubFetch(200);
    const { container } = render(<ReportViewer url={URL_} filename="r.html" reason="분석이 끝나면 볼 수 있습니다" />);
    expect(screen.getByTestId("report-reason").textContent).toBe("분석이 끝나면 볼 수 있습니다");
    expect(container.querySelector("iframe")).toBeNull();
    expect((container.querySelector("button[data-primary]") as HTMLButtonElement).disabled).toBe(true);
    expect(f).not.toHaveBeenCalled();
  });

  it("mock 모드: 목 서버 응답을 srcdoc 으로(sandbox 동일), [보고서 받기] 는 fetch(?download=1)", async () => {
    g.__MOCK__ = true;
    const f = stubFetch(200);
    const { container } = render(<ReportViewer url={URL_} filename="r.html" title="보고서" />);
    const frame = (await screen.findByTitle("보고서")) as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("srcdoc")).toBe(html);
    expect(frame.hasAttribute("src")).toBe(false);
    fireEvent.click(container.querySelector("[data-primary]")!);
    await waitFor(() => expect(f.mock.calls.map((c) => String((c as unknown[])[0]))).toContain(`${URL_}?download=1`));
  });
});
