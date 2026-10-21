// V-H-12(UI, mock): Case 탭·프로젝트 페이지 표·필터 URL 유지·더 보기, 작업 상세 섹션,
// "그때 결과 열기" → ④/⑤ 읽기 전용(배지·diff·실행 버튼 없음), summary 안내 문구, 화면당 주 버튼 1개 규칙.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { durText, summaryText, type HistoryItem } from "../api/history";
import { diffValue } from "../components/DiffTable";
import { MockServer, createMockFetch } from "../mock/server";

const primaries = (c: HTMLElement) => c.querySelectorAll("button[data-primary]");
const rows = () => screen.getAllByTestId("history-row");
const waitRows = async () => {
  await waitFor(() => expect(screen.queryAllByTestId("history-row").length).toBeGreaterThan(0));
  return rows();
};
void useLocation;

describe("순수 함수", () => {
  it("durText", () => {
    expect(durText(null)).toBe("–");
    expect(durText(12)).toBe("12초");
    expect(durText(185)).toBe("3분 05초");
    expect(durText(3720)).toBe("1시간 02분");
  });
  it("diffValue", () => {
    expect(diffValue(null)).toBe("–");
    expect(diffValue(48210)).toBe((48210).toLocaleString());
    expect(diffValue(3.3e-4)).toBe("3.30e-4");
    expect(diffValue([1, 120])).toBe("1, 120");
    expect(diffValue(0.12345)).toBe("0.1235");
  });
  it("summaryText", () => {
    const base = { job_type: "VALIDATE", failure_code: null, summary: { verdict: "PASS", disp_rms_rel: 2.1e-9 } } as unknown as HistoryItem;
    expect(summaryText(base)).toBe("PASS · 변위 RMS 2.1e-9");
    expect(summaryText({ ...base, job_type: "EXPORT", summary: { targets: ["fem", "csv"], n_files: 3 } } as unknown as HistoryItem)).toBe("fem·csv · 파일 3개");
    expect(summaryText({ ...base, summary: null, failure_code: "X" } as unknown as HistoryItem)).toBe("X");
  });
});

describe("Case 탭 '실행 이력'", () => {
  it("Case 메뉴에 링크가 있고 그 Case 작업만, 상태 필터는 실패·중단", async () => {
    renderApp("/p/p-body/c/c-demo/stage/1");
    const menu = await screen.findByRole("navigation", { name: "Case 메뉴" });
    expect(within(menu).getByRole("link", { name: "실행 이력" }).getAttribute("href")).toBe("/p/p-body/c/c-demo/history");
  });

  it("표(시각·단계·상태·소요·실행자·결과·요약), Case 열 없음, 상태 필터", async () => {
    const { container } = renderApp("/p/p-body/c/c-demo/history");
    expect(await screen.findByRole("heading", { level: 1, name: "실행 이력" })).toBeTruthy();
    await waitRows();
    const head = screen.getByRole("table", { name: "실행 이력" }).querySelectorAll("th");
    expect([...head].map((h) => h.textContent)).toEqual(["시각", "단계·작업", "상태", "소요", "실행자", "결과", "요약"]);
    expect(rows().every((r) => !r.textContent!.includes("후방 충돌 56kph"))).toBe(true);
    expect(within(rows()[0]).getByText("현재")).toBeTruthy();
    expect(primaries(container).length).toBe(0);
    // 상태 필터: 실패·중단만
    fireEvent.change(screen.getByLabelText("상태 필터"), { target: { value: "FAILED,INTERRUPTED" } });
    await waitFor(() => expect(rows().every((r) => r.textContent!.includes("실패"))).toBe(true));
    expect(rows().length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("작업 종류")).toBeNull();
  });
});

describe("프로젝트 '실행 이력' 페이지", () => {
  it("프로젝트 상단 링크 → Case 열이 있는 표", async () => {
    renderApp("/p/p-body");
    const link = await screen.findByRole("link", { name: "실행 이력" });
    expect(link.getAttribute("href")).toBe("/p/p-body/history");
  });

  it("종류·상태·기간·검색·내 작업만 필터, 더 보기", async () => {
    const { container } = renderApp("/p/p-body/history");
    await waitRows();
    expect(screen.getByRole("columnheader", { name: "Case" })).toBeTruthy();
    expect(rows().length).toBe(30);
    // 더 보기(커서)
    fireEvent.click(screen.getByRole("button", { name: "더 보기" }));
    await waitFor(() => expect(rows().length).toBe(53));
    expect(screen.queryByRole("button", { name: "더 보기" })).toBeNull();
    expect(new Set(rows().map((r) => r.querySelector("a")!.getAttribute("href"))).size).toBe(53); // 중복 없음
    // 작업 종류
    fireEvent.change(screen.getByLabelText("작업 종류"), { target: { value: "VALIDATE" } });
    await waitFor(() => expect(rows().every((r) => r.textContent!.includes("검증"))).toBe(true));
    fireEvent.change(screen.getByLabelText("작업 종류"), { target: { value: "" } });
    // 검색(Case 제목)
    fireEvent.change(screen.getByPlaceholderText("Case 제목·폴더·작업 id"), { target: { value: "56kph" } });
    await waitFor(() => expect(rows().every((r) => r.textContent!.includes("후방 충돌 56kph"))).toBe(true), { timeout: 3000 });
    // 내 작업만
    fireEvent.click(screen.getByLabelText("내 작업만"));
    await waitFor(() => expect(rows().every((r) => r.textContent!.includes("김해석"))).toBe(true));
    expect(primaries(container).length).toBe(0);
  });

  it("필터는 URL query 로 유지", async () => {
    renderApp("/p/p-body/history?type=ESL_SOLVE&mine=1");
    await waitRows();
    expect((screen.getByLabelText("작업 종류") as HTMLSelectElement).value).toBe("ESL_SOLVE");
    expect((screen.getByLabelText("내 작업만") as HTMLInputElement).checked).toBe(true);
    expect(rows().every((r) => r.textContent!.includes("ESL 계산") && r.textContent!.includes("김해석"))).toBe(true);
  });

  it("조건에 맞는 이력이 없으면 안내", async () => {
    renderApp("/p/p-body/history?q=없는제목");
    expect(await screen.findByText("조건에 맞는 실행 이력이 없습니다")).toBeTruthy();
  });
});

describe("작업 상세", () => {
  it("실패 작업: 오류가 맨 위, 개요·입력값·step·로그, 결과 없음 → 주 버튼 없음, 재시도는 보조", async () => {
    const { container } = renderApp("/p/p-body/jobs/h-ext-fail");
    const err = await screen.findByTestId("job-error");
    expect(err.textContent).toMatch(/EXTRACT_FAILED/);
    const heads = [...container.querySelectorAll("section.card > header h3")].map((h) => h.textContent);
    expect(heads).toEqual(["오류", "개요", "입력값", "step", "로그", "결과"]);
    expect(primaries(container).length).toBe(0);
    const retry = screen.getByRole("button", { name: "재시도" });
    expect(retry.hasAttribute("data-primary")).toBe(false);
    fireEvent.click(retry);
    expect(await screen.findByText(/재시도를 요청했습니다/)).toBeTruthy();
    // 로그는 일부씩 온다(실제 서버의 next_cursor·eof): 이어서 보기로 끝까지
    await waitFor(() => expect(screen.getByLabelText("step 로그").textContent).toMatch(/입력 확인/));
    expect(screen.getByLabelText("step 로그").textContent).not.toMatch(/오류: h3d 파트/);
    fireEvent.click(screen.getByRole("button", { name: "이어서 보기" }));
    await waitFor(() => expect(screen.getByLabelText("step 로그").textContent).toMatch(/오류: h3d 파트/));
    expect(screen.queryByRole("button", { name: "이어서 보기" })).toBeNull();
    expect(screen.getByText(/결과가 없는 작업/)).toBeTruthy();
  });

  it("성공 작업: 주 버튼은 '그때 결과 열기' 1개, 로그 step 선택", async () => {
    const { container } = renderApp("/p/p-body/jobs/h-esl-old");
    await screen.findByRole("heading", { level: 1, name: /작업 상세/ });
    await waitFor(() => expect(primaries(container).length).toBe(1));
    expect(primaries(container)[0].textContent).toBe("그때 결과 열기");
    expect(screen.queryByRole("button", { name: "재시도" })).toBeNull();
    expect(screen.getByTestId("stale-chip")).toBeTruthy();
    expect(screen.getByTestId("diff-table")).toBeTruthy();
    const sel = screen.getByLabelText("로그 step") as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: "2" } });
    await waitFor(() => expect(screen.getByLabelText("step 로그").textContent).toMatch(/\[ESL_REGISTER\]/));
  });

  it("step command 는 전역 관리자에게만", async () => {
    renderApp("/p/p-body/jobs/h-esl-old", "admin");
    expect((await screen.findAllByText("command", { selector: "summary" })).length).toBeGreaterThan(0);
  });
  it("일반 사용자 응답에는 command 없음", async () => {
    renderApp("/p/p-body/jobs/h-esl-old");
    await screen.findByRole("table", { name: "step 표" });
    expect(screen.queryByText("command", { selector: "summary" })).toBeNull();
  });

  it("내보내기: 파일 목록과 받기 링크", async () => {
    renderApp("/p/p-body/jobs/h-exp-1");
    const dl = await screen.findAllByRole("link", { name: "받기" });
    expect(dl.length).toBe(3);
    expect(dl[0].getAttribute("href")).toBe("/esl/api/jobs/h-exp-1/files/esl_cload.inc/download");
  });

  it("summary 작업(추출): 파일 보존 안 됨 안내", async () => {
    renderApp("/p/p-body/jobs/h-ext-old");
    expect(await screen.findByTestId("files-gone")).toBeTruthy();
    expect(screen.getByTestId("files-gone").textContent).toBe("파일 보존 안 됨 — 기록된 값만 표시");
  });

  it("취소 작업: 오류 없이 경고만, wait_s 있어도 결과 없음", async () => {
    renderApp("/p/p-body/jobs/h-canceled");
    expect(await screen.findByTestId("job-warning")).toBeTruthy();
    expect(screen.queryByTestId("job-error")).toBeNull();
    expect(screen.getByText("경고", { selector: "h3" })).toBeTruthy();
  });

  it("내보내기 파일이 보존 안 된 작업: 크기 –·받기 없음", async () => {
    renderApp("/p/p-body/jobs/h-exp-old");
    expect(await screen.findByTestId("files-gone")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "받기" })).toBeNull();
    expect(screen.getAllByText("보존 안 됨").length).toBe(2);
  });

  it("추출 입력 파일 지문: path·size·mtime 이 null 이어도 표시(mtime 은 에포크 초)", async () => {
    renderApp("/p/p-body/jobs/h-ext-old");
    fireEvent.click(await screen.findByText(/입력 파일 지문/));
    expect(screen.getByText("h3d/chassis_rear.h3d")).toBeTruthy();
    const cells = screen.getByText("h3d/chassis_rear.h3d").closest("tr")!.querySelectorAll("td");
    expect(cells[3].textContent).toMatch(/^\d+\/\d+ \d\d:\d\d$/);
    const nullRow = screen.getByText("result").closest("tr")!.querySelectorAll("td");
    expect([nullRow[1].textContent, nullRow[2].textContent, nullRow[3].textContent]).toEqual(["–", "–", "–"]);
  });

  it("추출 결과(past={extract,tstar}) 와 ESL run(esl_run_out) 값을 펼쳐 보인다", async () => {
    renderApp("/p/p-body/jobs/h-ext-old");
    expect(await screen.findByText("extract.n_elems")).toBeTruthy();
    expect(screen.getByText("tstar.frame_index")).toBeTruthy();
  });

  it("라이브러리 작업: links={stage:8,query:{analysis}} → 라이브러리 상세로", async () => {
    renderApp("/p/p-body/jobs/h-lib-1");
    const a = await screen.findByRole("link", { name: "현재 분석 열기" });
    expect(a.getAttribute("href")).toBe("/p/p-body/library/analyses/an-1");
  });

  it("없는 작업은 오류 표시", async () => {
    renderApp("/p/p-body/jobs/h-none");
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});

describe("과거 결과 읽기 전용", () => {
  it("'그때 결과 열기' → ④ ?run= : 배지·입력 바뀜·diff·실행 버튼 없음·현재 결과로", async () => {
    const { container } = renderApp("/p/p-body/jobs/h-esl-old");
    await waitFor(() => expect(primaries(container).length).toBe(1));
    fireEvent.click(primaries(container)[0]);
    expect(await screen.findByTestId("past-badge")).toBeTruthy();
    expect(screen.getByTestId("past-badge").textContent).toMatch(/^과거 실행 · \d+\/\d+ \d\d:\d\d$/);
    expect(await screen.findByTestId("stale-chip")).toBeTruthy();
    const diff = await screen.findByTestId("diff-table");
    expect(within(diff).getByText("t* 프레임")).toBeTruthy();
    expect(primaries(container).length).toBe(0);
    expect(screen.queryByRole("button", { name: "ESL 계산" })).toBeNull();
    expect(screen.queryByText("입력 요약")).toBeNull();
    expect(await screen.findByText("F_eq 상위 노드")).toBeTruthy();
    expect(screen.getByRole("link", { name: "현재 결과로" }).getAttribute("href")).toBe("/p/p-body/c/c-demo/stage/4");
  });

  it("⑤ ?val= : 읽기 전용, 판정 FAIL, 실행·등록 버튼 없음, 겹쳐보기 있음", async () => {
    const { container } = renderApp("/p/p-body/c/c-demo/stage/5?val=val-old");
    expect(await screen.findByTestId("past-badge")).toBeTruthy();
    expect((await screen.findAllByText("FAIL")).length).toBeGreaterThan(0);
    expect(primaries(container).length).toBe(0);
    expect(screen.queryByRole("button", { name: "검증 실행" })).toBeNull();
    expect(screen.queryByRole("button", { name: /라이브러리 등록/ })).toBeNull();
    expect(screen.queryByText("검증 이력")).toBeNull();
    expect(await screen.findByText("겹쳐보기 — 요소 변형률 (PCA 평면)")).toBeTruthy();
    expect(screen.getByTestId("diff-table")).toBeTruthy();
    expect(screen.getByRole("link", { name: "현재 결과로" }).getAttribute("href")).toBe("/p/p-body/c/c-demo/stage/5");
  });

  it("⑤ summary 검증: 파일 기반 패널 대신 안내 문구", async () => {
    renderApp("/p/p-body/c/c-demo/stage/5?val=val-old2");
    expect(await screen.findByTestId("files-gone")).toBeTruthy();
    expect(screen.getByTestId("files-gone").textContent).toBe("파일 보존 안 됨 — 기록된 값만 표시");
    expect(screen.queryByText("겹쳐보기 — 요소 변형률 (PCA 평면)")).toBeNull();
    expect(screen.getByText("hotspot ε_eq 오차")).toBeTruthy();
  });

  it("?run=·?val= 없으면 기존 화면(주 버튼 1개)", async () => {
    const { container } = renderApp("/p/p-body/c/c-demo/stage/4");
    await waitFor(() => expect(primaries(container).length).toBe(1));
    expect(primaries(container)[0].textContent).toBe("ESL 계산");
    expect(screen.queryByTestId("past-badge")).toBeNull();
  });

  it("현재 Case 의 ESL·검증 목록에 과거 열람용 데이터가 섞이지 않음", async () => {
    const server = new MockServer({ user: "power" });
    const f = createMockFetch(server);
    const runs = await (await f("/esl/api/cases/c-demo/esl-runs")).json();
    const vals = await (await f("/esl/api/cases/c-demo/validations")).json();
    expect(runs.map((r: { id: string }) => r.id)).toEqual(["run-1"]);
    expect(vals.map((v: { id: string }) => v.id)).toEqual(["val-1"]);
    const old = await (await f("/esl/api/validations/val-old2/field?layer=rad")).json();
    expect(old.detail.code).toBe("VALIDATION_FILES_GONE");
  });

  it("limit 200 초과는 422(목, 실제 서버와 같게)", async () => {
    const f = createMockFetch(new MockServer({ user: "power" }));
    expect((await f("/esl/api/history?project_id=p-body&limit=201")).status).toBe(422);
    expect((await f("/esl/api/history?project_id=p-body&limit=200")).status).toBe(200);
  });

  it("커서 위조는 INVALID_CURSOR(목)", async () => {
    const server = new MockServer({ user: "power" });
    const f = createMockFetch(server);
    const res = await f("/esl/api/history?project_id=p-body&cursor=" + btoa("zzz"));
    expect(res.status).toBe(422);
    expect((await res.json()).detail.code).toBe("INVALID_CURSOR");
  });
});
