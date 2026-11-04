// V-SC-10(esl_step_compare.md §10): ④ 형상 직접 비교 화면 — 라디오(비활성 사유)·카드 숨김, 형상 표(추가·빼기·이름 검사·기준 1개 + 기준 없음 경고·상한),
// [입력 준비] → 준비 결과(요소 수·상태 배지·실패 사유) → [비교 실행] 흐름, 결과(이름 열·민감도 숨김·3D 라벨·받기). 화면 크기 규칙은 scripts/screenshots-v0140.mjs.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { CODE_TEXT } from "../api/client";
import { defaultShapeName, doeBlockedReason, normalizeDoeSettings, scenarioBlocked, shapeNameProblem, shapesProblem } from "../api/doe";
import { compareIds, makeComparePrep, makeCompareResult, makeDoeSettings } from "../mock/doedata";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const reasonOf = (b: HTMLButtonElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? null;
const radio = (name: RegExp | string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const DROP = "비교할 STEP 끌어다 놓기(여러 개)";
const step = (name: string) => new File([new Uint8Array(4096)], name);

async function openCompare(path = "/p/p-body/doe/new?entries=le-1,le-2,le-9", mut?: Parameters<typeof renderApp>[2]) {
  const r = renderApp(path, "power", mut);
  await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked || radio(/① 같은 모델/).checked).toBe(true));
  fireEvent.click(radio(/④ 형상 직접 비교\(STEP 여러 개\)/));
  return r;
}
async function upload(names: string[]) {
  fireEvent.change(screen.getByLabelText(DROP), { target: { files: names.map(step) } });
  await waitFor(() => expect(screen.getByTestId(`shape-row-${names.length}`)).toBeTruthy(), { timeout: 5000 });
}

describe("④ 규칙(화면 쪽 함수)", () => {
  it("이름 규칙: 공백·64자·제어문자·대소문자 중복 / 기준 있으면 ≥ 2, 없으면 ≥ 1, 상한", () => {
    expect(shapeNameProblem("  ", [], 0)).toMatch(/이름을 입력/);
    expect(shapeNameProblem("a".repeat(65), [], 0)).toMatch(/64자/);
    expect(shapeNameProblem("a\u0007b", [], 0)).toMatch(/제어문자/);
    expect(shapeNameProblem("Rib A", ["rib a ", "Rib A"], 1)).toMatch(/겹칩니다/);
    expect(shapeNameProblem(" 리브 A ", ["x", " 리브 A "], 1)).toBeNull();
    expect(shapesProblem([], false, 20)).toMatch(/STEP 을 올리세요/);
    expect(shapesProblem([{ name: "a" }], true, 20)).toMatch(/하나 이상/);
    expect(shapesProblem([{ name: "a" }], false, 20)).toBeNull();
    expect(shapesProblem([{ name: "a" }, { name: "b" }, { name: "c" }], true, 2)).toMatch(/최대 2개/);
    expect(shapesProblem([{ name: "a" }, { name: "A" }], true, 20)).toBe("형상 1: 이름이 겹칩니다(대소문자 무시)");
    expect(defaultShapeName("chr_rib_A.stp")).toBe("chr_rib_A");
  });

  it("활성: paicad 없어도 ④ 는 막지 않음(SC-D-3), gmsh 없음·꺼짐 사유, settings.compare 보정", () => {
    const st = makeDoeSettings();
    st.enabled = false;
    st.reason = "PAICAD_NOT_CONFIGURED";
    expect(doeBlockedReason(st)).toMatch(/paicad/);
    expect(doeBlockedReason(st, "compare")).toBeNull();
    expect(scenarioBlocked(st, "compare")).toBeNull();
    st.scenarios.compare = false;
    st.gmsh.ready = false;
    expect(scenarioBlocked(st, "compare")).toMatch(/gmsh.*형상 직접 비교/);
    st.gmsh.ready = true;
    expect(scenarioBlocked(st, "compare")).toMatch(/'형상 직접 비교'가 서버에서 꺼져/);
    st.reason = "DOE_DISABLED";
    expect(doeBlockedReason(st, "compare")).toMatch(/꺼져 있습니다/);
    const n = normalizeDoeSettings({});
    expect(n.scenarios.compare).toBe(false);
    expect(n.compare).toEqual({ max_shapes: 20, total_max_mb: 1000, mesh_size_mm: 3 });
  });

  it("목: 형상 id(기준 = d000, 기준 없음 → d001…), 결과 values {}·shape·민감도 없음", () => {
    const sh = (f: string, ref = false) => ({ upload_id: f, name: f, reference: ref, file_name: `${f}.step`, sha256: f });
    expect(compareIds([sh("a"), sh("b", true), sh("c")]).map((x) => [x.id, x.name])).toEqual([["d000", "b"], ["d001", "a"], ["d002", "c"]]);
    expect(compareIds([sh("a"), sh("c")]).map((x) => x.id)).toEqual(["d001", "d002"]);
    const prep = makeComparePrep(compareIds([sh("a", true), sh("b"), sh("x_shift")]), "step");
    expect(prep.failed).toEqual([{ id: "d002", status: "FAILED_SIZE", code: "SHAPE_MISALIGNED" }]);
    const r = makeCompareResult(prep, ["e1", "e2"]);
    expect(r.sensitivity).toBeNull();
    expect(r.sensitivity_reason).toBe("COMPARE_NO_PARAMS");
    expect(r.ranking[0]).toMatchObject({ id: "d001", values: {}, shape: { name: "b" } });
    expect(r.excluded![0]).toMatchObject({ id: "d002", status: "FAILED_SIZE", shape: { name: "x_shift" } });
  });
});

describe("④ 새 연구 — 입력 카드", () => {
  it("라디오 ④ 전환: STEP 1개 칸·요소 크기 칸 숨김, 형상 표·물성 3칸·메시 설정 표시, 주 버튼 1개 사유", async () => {
    const { container } = await openCompare();
    expect(radio(/④/).checked).toBe(true);
    expect(screen.queryByLabelText("Ch/R 중립면 STEP 끌어다 놓기")).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "요소 크기 (mm)" })).toBeNull();
    expect(screen.getByRole("table", { name: "형상 표" })).toBeTruthy();
    expect(screen.getByRole("spinbutton", { name: "두께 t (mm)" })).toBeTruthy();
    expect(screen.getByTestId("compare-mesh-note").textContent).toMatch(/요소 3 mm/);
    expect(screen.getByTestId("doe-shapes-drop").textContent).toMatch(/최대 20개/);
    expect(primaries(container).map((b) => b.textContent)).toEqual(["입력 준비"]);
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/비교할 STEP 을 올리세요/));
    // 다른 시나리오로 돌아가면 형상 표 사라짐
    fireEvent.click(radio(/③ 다른 모델\(STEP만\)/));
    expect(screen.queryByRole("table", { name: "형상 표" })).toBeNull();
    expect(screen.getByLabelText("Ch/R 중립면 STEP 끌어다 놓기")).toBeTruthy();
  });

  it("형상 표: 여러 파일 → 행(기본 이름 = 파일 이름), 첫 형상 기준, 기준 라디오 1개만, 이름 검사, 기준 없음 경고, 빼기", async () => {
    const { container } = await openCompare();
    await upload(["chr_base.step", "chr_rib_A.stp", "chr_rib_B.step"]);
    expect((screen.getByRole("textbox", { name: "형상 2 이름" }) as HTMLInputElement).value).toBe("chr_rib_A");
    expect(radio("형상 1 기준").checked).toBe(true);
    expect(radio("기준 없음(Case 메시)").checked).toBe(false);
    // 기준 바꾸기 → 하나만 선택
    fireEvent.click(radio("형상 3 기준"));
    expect(radio("형상 3 기준").checked).toBe(true);
    expect(radio("형상 1 기준").checked).toBe(false);
    const chk = await screen.findByTestId("doe-check", undefined, { timeout: 4000 });
    expect(chk.textContent).toMatch(/형상 3개 .* 기준 STEP chr_rib_B/);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    // 이름: 대소문자 무시 중복 → 행 오류 + 주 버튼 사유
    fireEvent.change(screen.getByRole("textbox", { name: "형상 2 이름" }), { target: { value: "CHR_BASE" } });
    expect(within(screen.getByTestId("shape-row-2")).getByText(/이름이 겹칩니다/)).toBeTruthy();
    expect(reasonOf(primaries(container)[0])).toBe("형상 1: 이름이 겹칩니다(대소문자 무시)");
    fireEvent.change(screen.getByRole("textbox", { name: "형상 2 이름" }), { target: { value: "  " } });
    expect(reasonOf(primaries(container)[0])).toMatch(/형상 2: 이름을 입력하세요/);
    fireEvent.change(screen.getByRole("textbox", { name: "형상 2 이름" }), { target: { value: "리브 A안" } });
    // 기준 없음(Case 메시) → 경고 1줄 + check-inputs 기준 = Case 메시
    fireEvent.click(radio("기준 없음(Case 메시)"));
    expect(screen.getByTestId("ref-case-warn").textContent).toMatch(CODE_TEXT.COMPARE_REF_CASE_MESH);
    await waitFor(() => expect(screen.getByTestId("doe-check").textContent).toMatch(/기준 Case 메시/), { timeout: 4000 });
    expect(screen.getByTestId("doe-check").textContent).toMatch(/기준이 낙하 메시\(다른 메싱 방식\)/);
    // 빼기: 기준 행을 빼면 기준 없음
    fireEvent.click(radio("형상 1 기준"));
    fireEvent.click(screen.getByRole("button", { name: "형상 1 빼기" }));
    expect(screen.queryByTestId("shape-row-3")).toBeNull();
    expect(radio("기준 없음(Case 메시)").checked).toBe(true);
    expect(screen.getByTestId("shape-count").textContent).toMatch(/2 \/ 20개/);
  }, 15000);

  it("상한: max_shapes 도달 → 놓기 칸 '최대 n개'·비활성, 넘게 고르면 사유", async () => {
    await openCompare(undefined, (s) => {
      s.doe.settings.compare = { max_shapes: 2, total_max_mb: 1000, mesh_size_mm: 3 };
    });
    fireEvent.change(screen.getByLabelText(DROP), { target: { files: ["a.step", "b.step", "c.step"].map(step) } });
    expect(await screen.findByText(/STEP 은 최대 2개입니다/)).toBeTruthy();
    await upload(["a.step", "b.step"]);
    const drop = screen.getByTestId("doe-shapes-drop");
    expect(drop.querySelector(".dropzone-title")!.textContent).toBe("최대 2개");
    expect((within(drop).getByRole("button", { name: "파일 고르기" }) as HTMLButtonElement).disabled).toBe(true);
  }, 10000);

  it("비활성: paicad 없어도 ④ 선택 가능(경고 띠 없음), gmsh 없으면 ④ 라디오 비활성 + 사유", async () => {
    await openCompare("/p/p-body/doe/new?entries=le-1,le-2", (s) => {
      s.doe.settings.enabled = false;
      s.doe.settings.reason = "PAICAD_NOT_CONFIGURED";
      s.doe.settings.scenarios = { same: false, mesh: false, step: true, compare: true };
    });
    expect(radio(/④/).checked).toBe(true);
    expect(screen.queryByTestId("doe-blocked")).toBeNull();
    const r2 = renderApp("/p/p-body/doe/new?entries=le-1,le-2", "power", (s) => {
      s.doe.settings.gmsh.ready = false;
      s.doe.settings.scenarios.compare = false;
    });
    await waitFor(() => expect(within(r2.container).getByRole("radio", { name: /④/ })).toBeTruthy());
    const r4 = within(r2.container).getByRole("radio", { name: /④/ }) as HTMLInputElement;
    expect(r4.disabled).toBe(true);
    expect(r4.closest("label")!.getAttribute("title")).toMatch(/gmsh/);
  });
});

describe("④ 흐름 — 입력 준비 → 준비 결과 → 비교 실행 → 결과", () => {
  it("준비 후 형상 표(요소 수·상태·실패 사유), 비드·평면도·미리보기 카드 없음, 주 버튼 [비교 실행] → 결과 이름 열", async () => {
    const { container, server } = await openCompare();
    await upload(["chr_base.step", "chr_rib_A.step", "chr_D_shift.step"]);
    fireEvent.change(screen.getByRole("textbox", { name: "형상 1 이름" }), { target: { value: "현행" } });
    await screen.findByTestId("doe-check", undefined, { timeout: 4000 });
    await waitFor(() => expect((screen.getByRole("spinbutton", { name: "두께 t (mm)" }) as HTMLInputElement).value).toBe("1.2"));
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    fireEvent.click(primaries(container)[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" })).toBeTruthy();
    const rec = server.doe.recs[server.doe.recs.length - 1];
    expect(rec.out.scenario).toBe("compare");
    expect(rec.out.inputs.shapes!.map((x) => [x.id, x.name, x.reference])).toEqual([["d000", "현행", true], ["d001", "chr_rib_A", false], ["d002", "chr_D_shift", false]]);
    expect(rec.out.inputs.props).toEqual({ t: 1.2, E: 205000, nu: 0.3 });
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/입력 준비 중/));
    server.drain();
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["비교 실행"]), { timeout: 6000 });
    const d1 = screen.getByTestId("prep-shape-d001");
    expect(d1.textContent).toMatch(/\d{3},\d{3}/);
    expect(d1.textContent).toMatch(/준비됨/);
    expect(screen.getByTestId("prep-shape-d002").textContent).toMatch(/크기·정렬 불일치.*위치·방향이 다릅니다/);
    expect(screen.getByTestId("prep-shape-d000").textContent).toMatch(/현행.*기준/);
    expect(screen.queryByRole("table", { name: "비드 변수" })).toBeNull();
    expect(screen.queryByRole("img", { name: "비드·경계 평면도" })).toBeNull();
    expect(screen.queryByRole("region", { name: /미리보기/ })).toBeNull();
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    fireEvent.click(primaries(container)[0]);
    await waitFor(() => expect(primaries(container)[0].textContent).toBe("보고서 보기"));
    expect(reasonOf(primaries(container)[0])).toMatch(/실행이 끝나면/);
    const run = server.jobs.find((j) => j.job_type === "DOE_RUN" && j.params.bead_doe_id === rec.out.id);
    expect(run).toBeTruthy();
    server.drain();
    const t = await screen.findByRole("table", { name: "순위표" }, { timeout: 6000 });
    expect(within(t).getAllByRole("columnheader").map((h) => h.textContent).slice(0, 4)).toEqual(["순위", "안", "이름", "score"]);
    expect(within(t).getByTestId("rank-d001").textContent).toMatch(/chr_rib_A/);
    expect(within(t).getByTestId("excluded-d002").textContent).toMatch(/chr_D_shift.*실패 · 크기·정렬 불일치/);
  }, 20000);

  it("doe-4(준비 완료·Case 기준): 경고 COMPARE_REF_CASE_MESH, 실패 형상 사유, [비교 실행] 활성", async () => {
    const { container } = renderApp("/p/p-body/doe/doe-4");
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["비교 실행"]));
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    expect(screen.getByText(CODE_TEXT.COMPARE_REF_CASE_MESH)).toBeTruthy();
    expect(screen.getByTestId("prep-shape-d000").textContent).toMatch(/Case 메시.*\(낙하 메시\)/);
    expect(screen.getByTestId("prep-shape-d003").textContent).toMatch(/크기·정렬 불일치.*크기가 다릅니다/);
    expect(radio(/④ 형상 직접 비교/).checked).toBe(true);
  });
});

describe("④ 결과 — doe-3", () => {
  it("순위표 이름 열(행 머리)·기준 행, 실패 형상, 민감도 숨김 1줄, 3D 기준 vs 선택 형상, ESL별 표 이름 열, 받기(메시·CSV), 검증 낙하 없음", async () => {
    const { container } = renderApp("/p/p-body/doe/doe-3");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["보고서 보기"]));
    const head = within(t).getAllByRole("columnheader").map((h) => h.textContent);
    expect(head.slice(0, 4)).toEqual(["순위", "안", "이름", "score"]);
    const base = t.querySelector(".doe-base-row")!;
    expect(within(base as HTMLElement).getByRole("rowheader").textContent).toBe("현행");
    expect(base.textContent).toMatch(/기준 형상/);
    const names = within(t).getAllByTestId(/^rank-d/).map((r) => within(r).getByRole("rowheader").textContent);
    expect(names.sort()).toEqual(["리브 A안", "리브 B안", "비드 C안"]);
    expect(within(t).getByTestId("excluded-d004").textContent).toMatch(/D안\(원점 다름\).*실패 · 크기·정렬 불일치/);
    expect(t.querySelector('button[aria-label$="값 펼치기"]')).toBeNull();
    // 민감도 숨김
    expect(screen.getByTestId("sens-hidden").textContent).toMatch(/변수가 없어 민감도를 계산하지 않습니다/);
    expect(screen.queryByRole("img", { name: "민감도 막대(SRC·Spearman)" })).toBeNull();
    // 3D 비교: 기준 vs 선택 형상
    expect(await screen.findByRole("region", { name: "기준: 현행" })).toBeTruthy();
    const sel = screen.getByRole("combobox", { name: "3D 비교 안" }) as HTMLSelectElement;
    expect(sel.options[0].textContent).toMatch(/^d00\d (리브|비드) .*안 · 1위$/);
    const first = sel.options[0].value;
    const nm = within(within(t).getByTestId(`rank-${first}`)).getByRole("rowheader").textContent;
    expect(await screen.findByRole("region", { name: `${first} ${nm}` })).toBeTruthy();
    // ESL별 표 이름 열
    const pe = screen.getByRole("table", { name: "ESL별 개선율" });
    expect(within(pe).getAllByRole("columnheader").map((h) => h.textContent).slice(0, 2)).toEqual(["안", "이름"]);
    // 받기
    const dl = screen.getByTestId("doe-downloads");
    expect(within(dl).getByRole("link", { name: /메시 ch_r\.rad/ })).toBeTruthy();
    expect(within(dl).getByRole("link", { name: /메시 ch_r\.fem/ })).toBeTruthy();
    expect(within(dl).getByRole("link", { name: "순위 CSV" })).toBeTruthy();
    expect(screen.queryByTestId("vd-open")).toBeNull();
    // 비드 카드 없음
    expect(screen.queryByRole("table", { name: "비드 변수" })).toBeNull();
  });
});
