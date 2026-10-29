// V-BD-17(esl_bead_doe.md §16): 라이브러리 진입·탭, 시나리오 라디오(자동 판별·표시), 입력 카드(시나리오별 칸·STEP 청크 업로드·③ 물성 기본값),
// 준비 후 비드 표(기본 D·W·feasible, 범위 밖 배지, 오류 차단), 방식 드롭다운(풀 팩토리얼 수준·실제 안 수), 미리보기 격자(스킵 배지),
// 주 버튼 단계 전환·비활성 사유(미리보기 성공 + 같은 sha 일 때만 DOE 실행), 경계 경고 평면도, 순위표·스킵/실패 배지·민감도·3D 비교 2개·받기,
// 솔버 칸 없음, 설정값(서버 settings)·비활성 사유. 화면 크기 규칙은 스크린샷(scripts/screenshots-v090.mjs)으로 확인.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { autoScenario, buildSpec, defaultRows, doe, normalizeDoeSettings, normalizeResult, outsideFeasible, rowProblem } from "../api/doe";
import { JOB_TYPE_LABEL, currentStepKey, linkPath, stepLabel, summaryText, type HistoryItem } from "../api/history";
import { DEFAULT_SPEC, PARAMS, makeDoeSettings, makeMatrix, makePlan } from "../mock/doedata";
import { render } from "@testing-library/react";
import { BoundaryLegend } from "../components/BoundaryPlan";
import { sortRanking } from "../api/doe";
import { heatStyle } from "../components/DoePerEslTable";
import type { DoeRankRow } from "../api/types";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const reasonOf = (b: HTMLButtonElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? null;
const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
const radio = (name: RegExp) => screen.getByRole("radio", { name }) as HTMLInputElement;
/** 작업영역(상단 상태 칩 제외)에 솔버 선택·문구 없음(확정 6) */
const noSolver = () => {
  const main = screen.getByRole("main", { name: "작업영역" });
  expect(within(main).queryByText(/솔버/)).toBeNull();
  expect(within(main).queryByRole("combobox", { name: /솔버/ })).toBeNull();
};

describe("DOE 규칙(화면 쪽 함수)", () => {
  it("시나리오 자동 판별: 모두 같은 topo → ①, 아니면 B 메시 있으면 ②, 없으면 ③", () => {
    expect(autoScenario([{ topo_sha256: "a" }, { topo_sha256: "a" }], false)).toBe("same");
    expect(autoScenario([{ topo_sha256: "a" }, { topo_sha256: "b" }], true)).toBe("mesh");
    expect(autoScenario([{ topo_sha256: "a" }, { topo_sha256: "b" }], false)).toBe("step");
    expect(autoScenario([{ topo_sha256: null }], false)).toBe("step");
  });

  it("변수 기본: use_default 인 D·W 만 포함, 범위 = feasible / 오류·경고 구분", () => {
    const rows = defaultRows(PARAMS, ["D", "W"]);
    const on = rows.filter((r) => r.on).map((r) => r.name);
    expect(on).toEqual(["CHR_BEAD_D_1", "CHR_BEAD_W_1", "CHR_BEAD_D_2", "CHR_BEAD_W_2", "CHR_BEAD_D_3", "CHR_BEAD_W_3"]);
    expect(rows.find((r) => r.name === "CHR_BEAD_U_1")!.on).toBe(false); // 위치 기본 제외
    expect(rows.find((r) => r.name === "CHR_BEAD_D_5")!.on).toBe(false); // use_default false(고정 겹침)
    const d1 = PARAMS[0];
    expect(rowProblem(d1, { name: d1.name, on: true, lo: "5", hi: "5" })).toMatch(/하한 < 상한/);
    expect(rowProblem(d1, { name: d1.name, on: true, lo: "0", hi: "3" })).toMatch(/0보다 커야/);
    expect(rowProblem(PARAMS[2], { name: "u", on: true, lo: "-5", hi: "3" })).toBeNull(); // 위치는 음수 허용
    expect(outsideFeasible(d1, { name: d1.name, on: true, lo: "2.0", hi: "6.4" })).toBe(true);
    expect(outsideFeasible(d1, { name: d1.name, on: true, lo: "2.1", hi: "6.4" })).toBe(false);
  });

  it("DoeSpec 만들기: 풀 팩토리얼 안 수 > max_designs 막음, 시드·안 수 검사(설정값 기준)", () => {
    const st = makeDoeSettings();
    const rows = defaultRows(PARAMS, ["D", "W"]);
    const ok = buildSpec({ method: "lhs", n: "30", levels: "3", seed: "1" }, PARAMS, rows, st);
    expect(ok.problem).toBeNull();
    expect(ok.spec).toMatchObject({ method: "lhs", n: 30, seed: 1 });
    expect(ok.spec!.params).toHaveLength(6);
    expect(buildSpec({ method: "fullfact", n: "30", levels: "3", seed: "1" }, PARAMS, rows, st).problem).toMatch(/729 \+ 공칭 1 > 최대 200안/);
    st.max_designs = 1000;
    expect(buildSpec({ method: "fullfact", n: "30", levels: "3", seed: "1" }, PARAMS, rows, st).spec).toMatchObject({ levels: 3 });
    expect(buildSpec({ method: "lhs", n: "30", levels: "3", seed: "-1" }, PARAMS, rows, st).problem).toMatch(/시드/);
    expect(buildSpec({ method: "lhs", n: "1", levels: "3", seed: "1" }, PARAMS, rows, st).problem).toMatch(/안 수는 2~999/);
    expect(buildSpec({ method: "lhs", n: "3", levels: "3", seed: "1" }, PARAMS, rows.map((r) => ({ ...r, on: false })), st).problem).toMatch(/하나 이상/);
  });

  it("응답 보정: 빈 settings 는 꺼짐 쪽 기본, 결과 best.files 문자열도 같은 모양", () => {
    const s = normalizeDoeSettings({});
    expect(s.enabled).toBe(false);
    expect(s.method_sources.error).toBeTruthy();
    expect(s.doe.methods).toEqual(["lhs", "halton", "fullfact"]);
    const r = normalizeResult({ best: { id: "d001", files: ["best/d001/sample.step"] } } as never);
    expect(r.best!.files).toEqual([{ rel: "best/d001/sample.step" }]);
    expect(r.ranking).toEqual([]);
  });

  it("목 행렬: 같은 spec → 같은 sha(변수 순서 무관), d000 공칭 포함, URL 규칙", () => {
    const a = makeMatrix(DEFAULT_SPEC);
    const b = makeMatrix({ ...DEFAULT_SPEC, params: [...DEFAULT_SPEC.params].reverse() });
    expect(a.matrix_sha256).toBe(b.matrix_sha256);
    expect(a.designs[0].id).toBe("d000");
    expect(a.n_designs).toBe(31);
    expect(doe.bundleUrl("x")).toMatch(/\/doe\/studies\/x\/bundle\?parts=best%2Creport%2Cranking$/);
    expect(doe.thumbUrl("x", "d003")).toMatch(/\/doe\/studies\/x\/preview\/thumb\/d003$/);
  });

  it("대기열·이력 라벨: DOE 3종·단계 키, 이력 링크 stage 11 → 연구", () => {
    expect(JOB_TYPE_LABEL.DOE_RUN).toBe("강성 평가 실행"); // v0.10.0 이름 변경(사용자 문구만)
    expect(stepLabel(currentStepKey({ job_type: "DOE_RUN", current_step_no: 2, steps: null }))).toBe("안별 해석");
    expect(stepLabel(currentStepKey({ job_type: "DOE_PREVIEW", current_step_no: 2 }))).toBe("썸네일");
    expect(linkPath("p1", null, { stage: 11, query: { doe: "doe-1" } })).toBe("/p/p1/doe/doe-1");
  });

  it("이력 요약: DOE 3종 = 연구 화면과 같은 시나리오·단계 이름(통합 정합)", () => {
    const it0 = { job_type: "DOE_PREP", summary: { scenario: "step", phase: "DONE" } } as unknown as HistoryItem;
    expect(summaryText(it0)).toBe("③ 다른 모델(STEP만) · 완료");
    expect(summaryText({ ...it0, job_type: "DOE_RUN", summary: { scenario: "same", phase: "RUN" } } as unknown as HistoryItem)).toBe("① 같은 모델 · 실행 중");
  });

  it("경계 경고 수: B 체결 후보 0 이면 선이 없어도 prep.boundary.n_warn 으로 표시", () => {
    const plan = { ...makePlan("step", ["e1"]), links: [] };
    const { getByTestId } = render(<BoundaryLegend plan={plan} st={makeDoeSettings()} showLinks nWarn={14} />);
    expect(getByTestId("boundary-warn-n").textContent).toBe("14");
    expect(getByTestId("boundary-no-cand").textContent).toMatch(/모두 경고/);
  });
});

describe("라이브러리 진입(§12.1)", () => {
  it("선택 줄에 [강성 평가 스터디 (n)] — 주 버튼은 [내보내기] 1개, 누르면 새 강성 평가 스터디(① 자동)", async () => {
    const { container } = renderApp("/p/p-body/library");
    fireEvent.click(await screen.findByRole("checkbox", { name: "75QN80H v072 146 선택" }));
    fireEvent.click(box("75QN80H v072 14 선택"));
    expect(primaries(container)).toHaveLength(1);
    expect(primaries(container)[0].textContent).toBe("내보내기 (2)");
    fireEvent.click(screen.getByRole("button", { name: "강성 평가 스터디 (2)" }));
    expect(await screen.findByRole("heading", { level: 1, name: "새 강성 평가 스터디" })).toBeTruthy();
    await waitFor(() => expect(radio(/① 같은 모델/).checked).toBe(true));
    expect(screen.getByTestId("doe-auto").textContent).toMatch(/자동 판별: ① 같은 모델/);
  });

  it("탭 [강성 평가 스터디] 목록(옛 ?tab=doe 리다이렉트): 시나리오·DOE·미리보기·상태", async () => {
    renderApp("/p/p-body/library?tab=doe");
    const t = await screen.findByRole("table", { name: "강성 평가 스터디 목록" });
    expect(screen.getByRole("tab", { name: "강성 평가 스터디" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(within(t).getAllByRole("row")).toHaveLength(3));
    expect(t.textContent).toMatch(/75형 Ch\/R 비드 1차/);
    expect(t.textContent).toMatch(/② 다른 모델\(메시 있음\)/);
    expect(t.textContent).toMatch(/LHS · 31안 · 변수 6/);
    expect(t.textContent).toMatch(/완료/);
  });
});

describe("새 비드 DOE(§3·§12.2)", () => {
  it("① 입력: 솔버 칸 없음, STEP 없으면 사유, STEP 올리면 자동 검사 → 입력 준비 → 상세(준비 중)", async () => {
    const { container, server } = renderApp("/p/p-body/doe/new?entries=le-1,le-2,le-3");
    await waitFor(() => expect(radio(/① 같은 모델/).checked).toBe(true));
    noSolver();
    const p = primaries(container);
    expect(p.map((b) => b.textContent)).toEqual(["입력 준비"]);
    await waitFor(() => expect(reasonOf(p[0])).toMatch(/STEP 을 올리세요/));
    expect(screen.queryByTestId("doe-mesh-drop")).toBeNull(); // ① 은 B 메시 칸 없음
    expect(screen.queryByRole("spinbutton", { name: "두께 t (mm)" })).toBeNull();
    // 잘못된 확장자
    fireEvent.change(screen.getByLabelText("Ch/R 중립면 STEP 끌어다 놓기"), { target: { files: [new File([new Uint8Array(10)], "a.igs")] } });
    expect(await screen.findByText(/\.step·\.stp 만 올릴 수 있습니다/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ch/R 중립면 STEP 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "chassis_mid.step")] } });
    const chk = await screen.findByTestId("doe-check", undefined, { timeout: 4000 });
    expect(chk.textContent).toMatch(/기준 Case .* 파트 chassis_rear · 노드 221,380/);
    expect(screen.getByText(/누적 씬입니다/)).toBeTruthy(); // BD_BASE_CUMULATIVE 정보 경고
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    fireEvent.change(screen.getByRole("textbox", { name: "제목" }), { target: { value: "75형 Ch/R 2차" } });
    fireEvent.click(primaries(container)[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" })).toBeTruthy();
    expect(await screen.findByText("75형 Ch/R 2차")).toBeTruthy();
    const rec = server.doe.recs[server.doe.recs.length - 1];
    expect(rec.out).toMatchObject({ scenario: "same", entry_ids: ["le-1", "le-2", "le-3"], phase: "PREP" });
    expect(server.jobs.some((j) => j.job_type === "DOE_PREP" && j.params.bead_doe_id === rec.out.id)).toBe(true);
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/입력 준비 중/));
    // 준비가 끝나면 비드 표가 열림(폴링)
    server.drain();
    expect(await screen.findByRole("table", { name: "비드 변수" }, { timeout: 6000 })).toBeTruthy();
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["미리보기"]));
  }, 15000);

  it("다른 모델 섞임: 자동 ③(STEP만) → ①로 바꾸면 ✗ + [다른 모델 빼기], ③ 쉘 물성 3칸 기본값(서버)", async () => {
    const { container } = renderApp("/p/p-body/doe/new?entries=le-1,le-2,le-9");
    await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked).toBe(true));
    fireEvent.click(radio(/① 같은 모델/));
    expect(await screen.findByRole("button", { name: "다른 모델 빼기" })).toBeTruthy();
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/다른 모델 ESL 1개/));
    fireEvent.click(radio(/③ 다른 모델\(STEP만\)/));
    expect(screen.getByTestId("doe-auto").textContent).toMatch(/자동 판별: ③/);
    fireEvent.change(screen.getByLabelText("Ch/R 중립면 STEP 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "QN80J_mid.stp")] } });
    await waitFor(() => expect((screen.getByRole("spinbutton", { name: "두께 t (mm)" }) as HTMLInputElement).value).toBe("1.2"), { timeout: 4000 });
    expect((screen.getByRole("spinbutton", { name: "E (MPa)" }) as HTMLInputElement).value).toBe("205000");
    expect((screen.getByRole("spinbutton", { name: "ν" }) as HTMLInputElement).value).toBe("0.3");
    expect((screen.getByRole("spinbutton", { name: "요소 크기 (mm)" }) as HTMLInputElement).value).toBe("5");
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    fireEvent.change(screen.getByRole("spinbutton", { name: "ν" }), { target: { value: "0.5" } });
    expect(reasonOf(primaries(container)[0])).toMatch(/ν 는 0 이상 0.5 미만/);
    fireEvent.change(screen.getByRole("spinbutton", { name: "ν" }), { target: { value: "0.3" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "요소 크기 (mm)" }), { target: { value: "25" } });
    expect(reasonOf(primaries(container)[0])).toMatch(/요소 크기는 1~20 mm/);
  }, 10000);

  it("② B 메시 칸·파트 제목 기본(서버 part_title), 메시 없으면 사유", async () => {
    const { container } = renderApp("/p/p-body/doe/new?entries=le-1,le-9");
    await waitFor(() => expect(radio(/③/).checked).toBe(true));
    fireEvent.click(radio(/② 다른 모델\(메시 있음\)/));
    expect(screen.getByTestId("doe-mesh-drop")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "B 파트 제목" }) as HTMLInputElement).value).toBe("chassis rear");
    fireEvent.change(screen.getByLabelText("Ch/R 중립면 STEP 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "b.step")] } });
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/B 메시\(\.rad\/\.inc\)를 올리세요/), { timeout: 4000 });
    fireEvent.change(screen.getByLabelText("B 메시(.rad + include 또는 .inc) 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "QN80J_chr.rad"), new File([new Uint8Array(1024)], "mesh.inc")] } });
    const chk = await screen.findByTestId("doe-check", undefined, { timeout: 4000 });
    expect(chk.textContent).toMatch(/B 메시 QN80J_chr\.rad .* 크기 검사: ξ −0\.5 % η −0\.7 %/);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
  }, 10000);

  it("비활성: paicad 없음 → 경고 띠 + 주 버튼 사유, gmsh 없음 → ③ 라디오 비활성", async () => {
    const { container } = renderApp("/p/p-body/doe/new?entries=le-1,le-2", "power", (s) => {
      s.doe.settings.enabled = false;
      s.doe.settings.reason = "PAICAD_NOT_CONFIGURED";
      s.doe.settings.gmsh.ready = false;
      s.doe.settings.scenarios.step = false;
    });
    expect((await screen.findByTestId("doe-blocked")).textContent).toMatch(/형상 엔진\(paicad\)이 설치되지 않았습니다\(관리자 문의\)/);
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/형상 엔진/));
    expect(radio(/③/).disabled).toBe(true);
    expect(radio(/③/).closest("label")!.getAttribute("title")).toMatch(/gmsh/);
  });

  it("조회 권한만: 주 버튼 사유 = 권한", async () => {
    const { container } = renderApp("/p/p-body/doe/new?entries=le-1", "general");
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/권한/));
  });
});

describe("상세 — 비드·변수·미리보기(§5·§12.2)", () => {
  it("doe-2(② 미리보기 완료): 비드 표 기본, 범위 밖 배지(차단 아님), 오류 차단, 미리보기 격자 스킵 배지, 경계 경고, DOE 실행 활성", async () => {
    const { container } = renderApp("/p/p-body/doe/doe-2");
    const tbl = await screen.findByRole("table", { name: "비드 변수" });
    expect(box("B1 깊이 D 포함").checked).toBe(true);
    expect(box("B1 폭 W 포함").checked).toBe(true);
    expect(box("B1 위치 U 포함").checked).toBe(false);
    expect(box("B5 깊이 D 포함").checked).toBe(false);
    expect(tbl.textContent).toMatch(/고정 겹침\(기본 제외\)/);
    expect(tbl.textContent).toMatch(/체결부 가까움/);
    noSolver();
    // 주 버튼 = DOE 실행(같은 sha 미리보기 성공)
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["강성 평가 실행"]));
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    // 미리보기 격자: 공칭 + 24안, 스킵 배지
    const grid = screen.getByRole("list", { name: "미리보기 썸네일" });
    expect(within(grid).getAllByRole("listitem").length).toBe(25);
    expect(screen.getByTestId("thumb-d000").textContent).toMatch(/공칭/);
    const skipped = within(grid).getAllByRole("listitem").filter((li) => li.getAttribute("data-status")?.startsWith("SKIPPED_"));
    expect(skipped.length).toBeGreaterThan(0);
    expect(skipped[0].textContent).toMatch(/⨯(충돌|고정 침범|형상 불가)/);
    expect(screen.getByRole("region", { name: /④ 미리보기 \(25\) OK \d+/ })).toBeTruthy();
    // 경계 경고(②): 평면도 빨강 점선 + 접힘 표
    expect(await screen.findByRole("img", { name: "비드·경계 평면도" })).toBeTruthy();
    await waitFor(() => expect(screen.getAllByTestId("plan-warn-link").length).toBeGreaterThan(0));
    expect(Number(screen.getByTestId("boundary-warn-n").textContent)).toBe(screen.getAllByTestId("plan-warn-link").length);
    expect(screen.getByRole("table", { name: "경계 경고" }).textContent).toMatch(/> 10 mm|> 20 mm/);
    // 범위 밖: 경고 배지만, 실행은 sha 가 바뀌어 미리보기 필요
    fireEvent.change(screen.getByRole("spinbutton", { name: "B1 깊이 D 하한" }), { target: { value: "1.5" } });
    expect(screen.getByTestId("outside-CHR_BEAD_D_1")).toBeTruthy();
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/미리보기를 다시 실행하세요/));
    expect(screen.getByTestId("preview-stale")).toBeTruthy();
    expect(await screen.findByText(/feasible\(추정\) 밖입니다/)).toBeTruthy();
    // 하한 ≥ 상한 = 오류(차단)
    fireEvent.change(screen.getByRole("spinbutton", { name: "B1 깊이 D 하한" }), { target: { value: "9" } });
    expect(screen.getByTestId("param-CHR_BEAD_D_1").textContent).toMatch(/하한 < 상한/);
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/CHR_BEAD_D_1: 하한 < 상한/));
  }, 10000);

  it("방식 드롭다운: 풀 팩토리얼 → 수준 칸·안 수 표시, 초과면 사유 / 실제 안 수 = POST /matrix", async () => {
    renderApp("/p/p-body/doe/doe-2");
    await screen.findByRole("table", { name: "비드 변수" });
    await waitFor(() => expect(screen.getByTestId("doe-count").textContent).toMatch(/실제 25안\(공칭 포함, 중복 0\)/));
    expect((screen.getByRole("spinbutton", { name: "안 수" }) as HTMLInputElement).value).toBe("24");
    expect((screen.getByRole("spinbutton", { name: "시드" }) as HTMLInputElement).value).toBe("7");
    fireEvent.change(screen.getByRole("combobox", { name: "DOE 방식" }), { target: { value: "fullfact" } });
    expect(screen.getByRole("spinbutton", { name: "수준" })).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("doe-count").textContent).toMatch(/729 \+ 공칭 1 > 최대 200안/));
    // 변수 4개만 → 3^4 = 81 → 82안
    for (const n of ["B2 깊이 D 포함", "B2 폭 W 포함"]) fireEvent.click(box(n));
    await waitFor(() => expect(screen.getByTestId("doe-count").textContent).toMatch(/실제 82안/));
  });

  it("방법·출처 ⓘ: 요약·방식별 줄(현재 강조)·출처 새 탭·Esc 닫기", async () => {
    renderApp("/p/p-body/doe/doe-2");
    await screen.findByRole("table", { name: "비드 변수" });
    fireEvent.click(screen.getByRole("button", { name: "방법·출처" }));
    const dlg = screen.getByRole("dialog", { name: "방법·출처" });
    expect(dlg.querySelector("[data-current]")!.textContent).toMatch(/LHS/);
    const link = within(dlg).getByRole("link", { name: /Altair OptiStruct/ });
    expect(link.getAttribute("target")).toBe("_blank");
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("DOE 실행 → 실행 중(보고서 비활성) → 완료 → 순위표", async () => {
    const { container, server } = renderApp("/p/p-body/doe/doe-2");
    await waitFor(() => expect(primaries(container)[0].textContent).toBe("강성 평가 실행"));
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    fireEvent.click(primaries(container)[0]);
    await waitFor(() => expect(primaries(container)[0].textContent).toBe("보고서 보기"));
    expect(reasonOf(primaries(container)[0])).toMatch(/실행이 끝나면/);
    expect(server.jobs.some((j) => j.job_type === "DOE_RUN")).toBe(true);
    server.drain();
    expect(await screen.findByRole("table", { name: "순위표" }, { timeout: 6000 })).toBeTruthy();
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
  }, 12000);

  it("미리보기 다시 → 진행 중이면 DOE 실행 사유, 끝나면 활성", async () => {
    const { container, server } = renderApp("/p/p-body/doe/doe-2");
    await screen.findByRole("table", { name: "비드 변수" });
    fireEvent.change(screen.getByRole("spinbutton", { name: "안 수" }), { target: { value: "12" } });
    await waitFor(() => expect(screen.getByTestId("doe-count").textContent).toMatch(/실제 13안/));
    const btn = await screen.findByRole("button", { name: "미리보기" });
    fireEvent.click(btn);
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/미리보기 진행 중/));
    server.drain();
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false), { timeout: 6000 });
    expect(within(screen.getByRole("list", { name: "미리보기 썸네일" })).getAllByRole("listitem").length).toBe(13);
  }, 12000);
});

describe("상세 — 결과(§11·§12.2)", () => {
  it("doe-1(완료): 순위표(score·개선율·umax·εmax·경고 수)·스킵/실패 배지·민감도·3D 비교 2개·받기·보고서", async () => {
    const { container } = renderApp("/p/p-body/doe/doe-1");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["보고서 보기"]));
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    const head = within(t).getAllByRole("columnheader").map((h) => h.textContent);
    expect(head.slice(0, 7)).toEqual(["순위", "안", "score", "개선율", "최악 ESL", "umax", "εmax"]);
    const first = within(t).getAllByRole("row")[2]; // 머리·베이스라인 다음
    expect(first.textContent).toMatch(/^1d\d{3}0\.\d{2}\+\d+ %/);
    expect(t.textContent).toMatch(/베이스라인/);
    expect(t.querySelector('[data-testid^="excluded-"]')!.textContent).toMatch(/스킵 · (충돌|고정 침범|형상 불가)|실패 · 모핑 실패/);
    expect(t.textContent).toMatch(/실패 · 모핑 실패/);
    expect(t.textContent).toMatch(/⚠ 1/);
    // 행 펼치기 = 값
    fireEvent.click(within(first).getByRole("button", { name: /값 펼치기/ }));
    expect(t.textContent).toMatch(/B1 D \d/);
    // 민감도
    expect(screen.getByRole("img", { name: "민감도 막대(SRC·Spearman)" })).toBeTruthy();
    expect(screen.getByTestId("sens-r2").textContent).toMatch(/R² 0\.\d\d/);
    expect(screen.getByTestId("sens-CHR_BEAD_D_1")).toBeTruthy();
    // 3D 비교: 카드 2개(베이스라인 | 안)
    expect(await screen.findByRole("region", { name: "베이스라인 d000" })).toBeTruthy();
    expect(await screen.findByRole("region", { name: /^안 d\d{3}$/ })).toBeTruthy();
    // 받기
    const dl = screen.getByTestId("doe-downloads");
    expect(within(dl).getByRole("link", { name: /include inc_mesh\.inc/ })).toBeTruthy();
    expect(within(dl).getByRole("link", { name: "BREP" })).toBeTruthy();
    expect(within(dl).getByRole("link", { name: "STEP" })).toBeTruthy();
    expect(within(dl).getByRole("link", { name: "순위 CSV" })).toBeTruthy();
    // 실행 후 편집 잠금·솔버 칸 없음
    expect(box("B1 깊이 D 포함").disabled).toBe(true);
    noSolver();
  });

  it("순위표 행 선택 → 3D 비교 안 바뀜", async () => {
    renderApp("/p/p-body/doe/doe-1");
    const t = await screen.findByRole("table", { name: "순위표" });
    const sel = (await screen.findByRole("combobox", { name: "3D 비교 안" })) as HTMLSelectElement;
    const opts = [...sel.options].map((o) => o.value);
    expect(opts.length).toBe(3);
    fireEvent.click(within(t).getByTestId(`rank-${opts[1]}`));
    await waitFor(() => expect(sel.value).toBe(opts[1]));
  });
});


describe("ESL별 개선 지표(v0.10.0 §11.4)", () => {
  const row = (id: string, score: number, extra: Partial<DoeRankRow>): DoeRankRow => ({
    rank: 0, id, values: {}, score, improvement: 1 - score, worst_entry_id: "E1", umax: 1, epsmax: 0.001, umax_all: 1,
    epsmax_all: 0.001, warnings_n: 0, ...extra,
  });

  it("sortRanking: 최소 개선율·기하평균·악화 수·Pareto, 지표 없는 행은 뒤로, 동률 = score → id", () => {
    // 문제 이동: d001 score 최상(0.5)이지만 다른 씬 악화(min_improvement −0.2), d002 는 전 씬 소폭 개선
    const rows = [
      row("d001", 0.5, { min_improvement: -0.2, geo_mean_improvement: 0.23, n_worsened: 1, pareto: true }),
      row("d002", 0.9, { min_improvement: 0.05, geo_mean_improvement: 0.07, n_worsened: 0, pareto: true }),
      row("d003", 0.95, { min_improvement: 0.025, geo_mean_improvement: 0.04, n_worsened: 0, pareto: false }),
      row("d004", 0.7, {}),
    ];
    expect(sortRanking(rows, "score").map((r) => r.id)).toEqual(["d001", "d004", "d002", "d003"]);
    expect(sortRanking(rows, "min_improvement").map((r) => r.id)).toEqual(["d002", "d003", "d001", "d004"]);
    expect(sortRanking(rows, "geo_mean_improvement").map((r) => r.id)).toEqual(["d001", "d002", "d003", "d004"]);
    expect(sortRanking(rows, "n_worsened").map((r) => r.id)).toEqual(["d002", "d003", "d001", "d004"]);
    expect(sortRanking(rows, "pareto").map((r) => r.id)).toEqual(["d001", "d002", "d004", "d003"]);
    expect(heatStyle(0.2).background).toMatch(/^rgba\(22, 163, 74/);
    expect(heatStyle(-0.2).background).toMatch(/^rgba\(220, 38, 38/);
    expect(heatStyle(null)).toEqual({});
  });

  it("doe-1: 순위표 지표 열·열 머리 정렬·ⓘ 정의, ESL별 개선율 표(행 = 상위 안, 열 = ESL, 히트맵)", async () => {
    renderApp("/p/p-body/doe/doe-1");
    const t = await screen.findByRole("table", { name: "순위표" });
    const head = within(t).getAllByRole("columnheader").map((h) => h.textContent);
    expect(head.slice(7, 12)).toEqual(["전 씬 개선", "최소 개선율", "개선/악화", "기하평균", "Pareto"]);
    const ids = () => within(t).getAllByTestId(/^rank-d/).map((r) => r.getAttribute("data-testid")!.slice(5));
    const before = ids();
    expect(t.textContent).toMatch(/[✓✗]/);
    expect(t.textContent).toMatch(/●/);                                       // Pareto 안이 하나 이상
    expect(t.textContent).toMatch(/\d+ \/ \d+/);                             // 개선/악화 씬 수
    fireEvent.click(within(t).getByRole("button", { name: "최소 개선율 기준 정렬" }));
    await waitFor(() => expect(within(t).getByRole("button", { name: "최소 개선율 기준 정렬" }).closest("th")!.getAttribute("aria-sort")).toBe("ascending"));
    const after = ids();
    expect([...after].sort()).toEqual([...before].sort());
    const minImp = after.map((id) => Number(within(within(t).getByTestId(`rank-${id}`)).getAllByRole("cell")[8].textContent!.replace(/[^\d.+−-]/g, "").replace("−", "-")));
    for (let i = 1; i < minImp.length; i++) expect(minImp[i]).toBeLessThanOrEqual(minImp[i - 1] + 1e-9);
    fireEvent.click(within(t).getByRole("button", { name: "score 기준 정렬" }));
    await waitFor(() => {
      const t2 = screen.getByRole("table", { name: "순위표" });
      const rk = within(t2).getAllByTestId(/^rank-d/).map((r) => Number(within(r).getAllByRole("cell")[0].textContent));
      expect(rk).toEqual([...rk].sort((x, y) => x - y));                          // score 정렬 = 순위 번호 순
    });
    // ⓘ 정의
    expect(screen.getByTestId("metric-defs").textContent).toMatch(/최소 개선율: 1 − max/);
    expect(screen.getByTestId("metric-defs").textContent).toMatch(/Pareto/);
    // ESL별 개선율 표
    const pe = screen.getByRole("table", { name: "ESL별 개선율" });
    const cols = within(pe).getAllByRole("columnheader");
    expect(cols[0].textContent).toBe("안");
    expect(cols.length).toBeGreaterThan(1);
    const body = within(pe).getAllByRole("row").slice(1);
    expect(body.length).toBe(Math.min(10, before.length));
    const cell = within(body[0]).getAllByRole("cell")[1] as HTMLElement;
    expect(cell.textContent).toMatch(/[+−]\d+\.\d %/);
    expect(cell.getAttribute("style") ?? "").toMatch(/background/);
    expect(screen.getByTestId("per-esl-wrap").className).toMatch(/table-wrap/);
  });
});
