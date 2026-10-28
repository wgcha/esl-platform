// V-UI-1: 6단계 라우트, 단계당 주 버튼 1개, 권한 없는 사용자 비활성, stale 배너 + 단계별 핵심 요소
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/endpoints";
import { RadInspectView } from "../components/PathInspect";
import { renderApp } from "../test/render";
import { NO_PERMISSION } from "../app/AppContext";
import { STALE_TEXT } from "../stages/StageFrame";
import { TOO_LARGE_TEXT } from "../stages/Stage6";

const PRIMARY = ["추출 실행", "t* 확정", "지지점 저장", "ESL 계산", "검증 실행", "내보내기"];
const TITLES = ["① 입력", "② t*", "③ 지지점", "④ ESL", "⑤ 검증", "⑥ 내보내기"];
const url = (c: string, n: number) => `/p/p-body/c/${c}/stage/${n}`;
const primaries = (container: HTMLElement) => container.querySelectorAll("button[data-primary]");

describe("V-UI-1 라우트·주 버튼", () => {
  for (let n = 1; n <= 6; n++) {
    it(`단계 ${n}: 제목과 주 버튼 1개`, async () => {
      const { container } = renderApp(url("c-demo", n));
      expect(await screen.findByRole("heading", { level: 2, name: TITLES[n - 1] })).toBeTruthy();
      await waitFor(() => expect(primaries(container).length).toBe(1));
      expect(primaries(container)[0].textContent).toBe(PRIMARY[n - 1]);
      // 경로바·스텝퍼
      expect(screen.getByRole("link", { name: "대시보드로" }).getAttribute("href")).toBe("/");
      const crumbs = screen.getByRole("navigation", { name: "경로" });
      expect(screen.getByRole("link", { name: "ESL 처음으로" }).getAttribute("href")).toBe("/");
      expect(within(crumbs).getByText("등가정적하중")).toBeTruthy();
      await within(crumbs).findByText("후방 충돌 40kph");
      expect(screen.getByRole("navigation", { name: "단계" }).querySelectorAll("li").length).toBe(6);
    });
  }

  it("잘못된 단계 번호는 ①로", async () => {
    renderApp(url("c-demo", 9));
    expect(await screen.findByRole("heading", { level: 2, name: "① 입력" })).toBeTruthy();
  });

  it("프로젝트 선택 → Case 목록", async () => {
    renderApp("/");
    fireEvent.click(await screen.findByRole("link", { name: /차체 후방 충돌/ }));
    expect(await screen.findByRole("heading", { name: "Case 목록" })).toBeTruthy();
    expect(await screen.findByRole("link", { name: "후방 충돌 40kph" })).toBeTruthy();
  });
});

describe("V-UI-1 권한", () => {
  it("조회 사용자: 모든 단계 주 버튼 비활성 + 툴팁", async () => {
    for (let n = 1; n <= 6; n++) {
      const { container, unmount } = renderApp(url("c-demo", n), "general");
      await screen.findByRole("heading", { level: 2, name: TITLES[n - 1] });
      await waitFor(() => expect(screen.getByTestId("user").textContent).toContain("조회"));
      const btn = primaries(container)[0] as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      expect(btn.parentElement!.getAttribute("title")).toBe(NO_PERMISSION);
      unmount();
    }
  });

  it("조회 사용자: 새 Case 비활성", async () => {
    renderApp("/p/p-body", "general");
    await waitFor(() => expect((screen.getByRole("button", { name: "새 Case" }) as HTMLButtonElement).disabled).toBe(true));
  });

  it("실행 사용자: ④ ESL 계산 활성", async () => {
    const { container } = renderApp(url("c-demo", 4), "power");
    await screen.findByText("F_eq 상위 노드");
    await waitFor(() => expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(false));
  });
});

describe("V-UI-1 stale", () => {
  it("t*가 바뀐 Case의 ④에 stale 배너, 스텝퍼 점 stale", async () => {
    renderApp(url("c-stale", 4));
    expect(await screen.findByText(STALE_TEXT)).toBeTruthy();
    const dots = screen.getByRole("navigation", { name: "단계" }).querySelectorAll("[data-state]");
    expect(dots[3].getAttribute("data-state")).toBe("stale");
    expect(dots[0].getAttribute("data-state")).toBe("done");
  });

  it("최신 Case에는 배너 없음", async () => {
    renderApp(url("c-demo", 4));
    await screen.findByText("F_eq 상위 노드");
    expect(screen.queryByTestId("stale-banner")).toBeNull();
  });

  it("stale ESL이면 ⑤ 검증 실행 비활성", async () => {
    const { container } = renderApp(url("c-stale", 5));
    await waitFor(() => expect((primaries(container)[0] as HTMLButtonElement).parentElement!.getAttribute("title")).toMatch(/다시 계산/));
  });
});

describe("단계별 핵심 요소", () => {
  it("① inspect 요약과 추출 결과", async () => {
    renderApp(url("c-demo", 1));
    expect(await screen.findByText("done.json 정상")).toBeTruthy();
    expect(await screen.findByText("rad 읽기 가능")).toBeTruthy();
    expect(screen.getByText("7,200")).toBeTruthy(); // 노드 수(추출 결과)
  });

  it("② 지표 토글 2개, 곡선·t* 표시, 후보 라디오, t* 확정은 바꿔야 활성", async () => {
    const { container } = renderApp(url("c-demo", 2));
    expect(await screen.findByRole("img", { name: /max-hold 곡선/ })).toBeTruthy();
    expect(screen.getAllByRole("radio", { name: /Max_Strain|Plastic/ }).length).toBe(2);
    expect(screen.getByTestId("tstar-marker")).toBeTruthy();
    const btn = primaries(container)[0] as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "프레임 92" }));
    expect(btn.disabled).toBe(false);
    fireEvent.click(screen.getByRole("radio", { name: "Plastic" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: "프레임 84" })).toBeTruthy());
    expect(screen.getAllByText("상승 중").length).toBeGreaterThan(0);
  });

  it("②에서 t*를 바꾸면 ④가 stale", async () => {
    const { container, server } = renderApp(url("c-demo", 2));
    fireEvent.click(await screen.findByRole("radio", { name: "프레임 92" }));
    fireEvent.click(primaries(container)[0]);
    await waitFor(() => expect(server.findCase("c-demo")!.tstar!.frame_index).toBe(92));
    await waitFor(() =>
      expect(screen.getByRole("navigation", { name: "단계" }).querySelectorAll("[data-state]")[3].getAttribute("data-state")).toBe("stale"),
    );
  });

  it("③ 노드 입력 3칸에 자동값, 산점 표시", async () => {
    renderApp(url("c-demo", 3));
    const inputs = await screen.findAllByRole("textbox", { name: /지지 노드/ });
    expect(inputs.length).toBe(3);
    await waitFor(() => expect((inputs[0] as HTMLInputElement).value).toBe("1"));
    expect(await screen.findAllByTestId("support-marker")).toHaveLength(3);
  });

  it("④ 회전각·평형 오차·F_eq 표", async () => {
    renderApp(url("c-demo", 4));
    expect(await screen.findByText("1.84°")).toBeTruthy();
    expect(screen.getByText("평형 오차")).toBeTruthy();
    expect(await screen.findByText("3542")).toBeTruthy();
  });

  it("⑤ PASS 배지(변형률 참고 초과여도 PASS)·제외 요소", async () => {
    renderApp(url("c-demo", 5));
    expect(await screen.findByText("PASS")).toBeTruthy();
    expect(screen.queryByText(/HOTSPOT_STRAIN|FIELD_MAX_ERR/)).toBeNull();
    expect(screen.getByText(/상승 중 아님/)).toBeTruthy();
  });

  it("⑥ 대상 체크 3개·폴더 경로·파일 목록", async () => {
    renderApp(url("c-demo", 6));
    expect((await screen.findAllByRole("checkbox")).length).toBe(3);
    expect((await screen.findByTestId("folder-path")).textContent).toContain("rear40");
    expect(await screen.findByText("06_export/esl_cload.inc")).toBeTruthy();
    // esl_force.fem(31.9 MB) > 20 MB: 다운로드 대신 안내 + 경로 복사
    expect(screen.getAllByRole("link", { name: "다운로드" }).length).toBe(6);
    const tl = screen.getByTestId("too-large");
    expect(tl.textContent).toContain(TOO_LARGE_TEXT);
    expect(tl.textContent).toContain("rear40\\06_export\\esl_force.fem");
    expect(within(tl).getByRole("button", { name: "경로 복사" })).toBeTruthy();
  });

  it("⑥ 다운로드가 413 ARTIFACT_TOO_LARGE면 안내 + 서버가 준 경로 복사", async () => {
    const { server } = renderApp(url("c-demo", 6));
    await screen.findByText("06_export/esl_cload.inc");
    // 목록의 downloadable 이 낡았다고 가정: u_rel.csv 를 서버 쪽에서 크게 만든다
    const a = server.artifacts["c-demo"].find((x) => x.rel.endsWith("u_rel.csv"))!;
    a.size = 64 * 1024 * 1024;
    const row = screen.getByText("06_export/u_rel.csv").closest("tr")!;
    fireEvent.click(within(row).getByRole("link", { name: "다운로드" }));
    const tl = await within(row).findByTestId("too-large");
    expect(tl.textContent).toContain(TOO_LARGE_TEXT);
    expect(tl.textContent).toContain("한도 20.0 MB");
    expect(tl.textContent).toContain("u_rel.csv");
  });
});

describe("작업 진행", () => {
  it("⑤ 검증 실행 → 완료(Case version 불변) 후 새 검증 결과·이력 표시", async () => {
    const { container, server } = renderApp(url("c-demo", 5));
    await screen.findByText("PASS");
    const v0 = server.findCase("c-demo")!.version;
    const btn = primaries(container)[0] as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    expect(await screen.findByTestId("job-progress")).toBeTruthy();
    server.drain();
    expect(server.findCase("c-demo")!.version).toBe(v0);
    expect(await screen.findByText("검증 이력", {}, { timeout: 6000 })).toBeTruthy();
  }, 10000);

  it("실행 중 작업: 취소 버튼 → CANCELED", async () => {
    const { container, server } = renderApp(url("c-new", 1));
    await screen.findByText("done.json 정상");
    const btn = primaries(container)[0] as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    const jp = await screen.findByTestId("job-progress");
    expect(within(jp).getByRole("button", { name: "취소" })).toBeTruthy();
    fireEvent.click(within(jp).getByRole("button", { name: "취소" }));
    await waitFor(() => expect(server.jobs[0].state).toBe("CANCELED"));
  });

  it("① 추출 실행 → 진행 표시 → 완료 후 결과", async () => {
    const { container, server } = renderApp(url("c-new", 1));
    await screen.findByText("done.json 정상");
    const btn = primaries(container)[0] as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    expect(await screen.findByTestId("job-progress")).toBeTruthy();
    expect(server.jobs[0].job_type).toBe("CASE_EXTRACT");
    server.drain();
    expect(screen.getByText(/아직 추출하지 않았습니다/)).toBeTruthy();
    expect(await screen.findByText("7,200", {}, { timeout: 6000 })).toBeTruthy();
    expect(screen.queryByText(/아직 추출하지 않았습니다/)).toBeNull();
  }, 10000);
});


describe("RadInspectView 파트 행 클릭", () => {
  const base = { normalized_path: "x.rad", includes: [], part_title: "chassis rear", target_part: null };
  const parts = [
    { id: 10, title: "chassis_rear", n_elems: 5 },
    { id: 11, title: "Other", n_elems: 3 },
  ];
  it("PART_NOT_FOUND 면 행을 눌러 title 을 채운다", () => {
    const picked: string[] = [];
    render(<RadInspectView r={{ ...base, ok: false, problems: ["PART_NOT_FOUND: /PART title 'x' 없음"], parts }} partTitle="x" onPickPart={(t) => picked.push(t)} />);
    expect(screen.getByText("표에서 파트를 누르면 채워집니다")).toBeTruthy();
    fireEvent.click(screen.getByText("chassis_rear"));
    expect(picked).toEqual(["chassis_rear"]);
  });
  it("문제가 없으면 안내·클릭 없음, 정규화로 일치한 행은 강조", () => {
    const picked: string[] = [];
    const { container } = render(<RadInspectView r={{ ...base, ok: true, problems: [], parts }} partTitle="Chassis Rear" onPickPart={(t) => picked.push(t)} />);
    expect(screen.queryByText("표에서 파트를 누르면 채워집니다")).toBeNull();
    fireEvent.click(screen.getByText("chassis_rear"));
    expect(picked).toEqual([]);
    expect(container.querySelectorAll("tr.hl").length).toBe(1);
  });
});

describe("① 추출 실행 버튼: 확인 중에는 비활성", () => {
  it("rad 확인 응답 전에는 '확인 중' 사유로 비활성, 응답 후 활성", async () => {
    const real = api.inspectRad;
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const spy = vi.spyOn(api, "inspectRad").mockImplementation(async (...a) => {
      await gate;
      return real(...a);
    });
    try {
      const { container } = renderApp(url("c-demo", 1));
      await screen.findByRole("heading", { level: 2, name: "① 입력" });
      const btn = () => container.querySelector("button[data-primary]") as HTMLButtonElement;
      expect(screen.getByText("확인 중…")).toBeTruthy();
      expect(btn().disabled).toBe(true);
      release();
      await waitFor(() => expect(screen.getByLabelText("rad 확인 결과")).toBeTruthy());
      await waitFor(() => expect(btn().disabled).toBe(false));
    } finally {
      spy.mockRestore();
    }
  });
});
