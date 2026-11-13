// V-C2-12(esl_compare_mesh_options.md §8·§10): ④ 메시 옵션 화면 — 형상 행 [STEP | 메시] 토글(기본 = 확장자)·rad/inc 묶음 = 메시 행 1개·
// 파트 ID 칸(datalist, 하나면 자동 채움)·주 파일 고르기, 고급 설정 메시 방식(재메시 미지원 사유)·세분화 허용, 결과 '메시 방식' 열·배지·툴팁.
// 화면 크기(2560×1440·1920×1080 잘림·가로 스크롤 없음)는 scripts/screenshots-v0160.mjs.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { meshMainCandidates, meshMethodKind, meshMethodLabel, meshMethodTip, normalizeDoeSettings, partIdProblem, shapeFailText, shapeFailTip, shapeKindOf } from "../api/doe";
import type { DoeStudyOut } from "../api/types";
import { CompareShapeSummary } from "../components/DoeInputs";
import { compareIds, makeComparePrep, makeCompareResult, meshMethodsMixed } from "../mock/doedata";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const reasonOf = (b: HTMLButtonElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? null;
const radio = (name: RegExp | string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const DROP = "비교할 STEP·메시 끌어다 놓기(여러 개)";
const file = (name: string, n = 4096) => new File([new Uint8Array(n)], name);

async function openCompare(mut?: Parameters<typeof renderApp>[2]) {
  const r = renderApp("/p/p-body/doe/new?entries=le-1,le-2,le-9", "power", mut);
  await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked || radio(/① 같은 모델/).checked).toBe(true));
  fireEvent.click(radio(/④ 형상 직접 비교/));
  return r;
}
async function drop(names: string[], rows: number) {
  fireEvent.change(screen.getByLabelText(DROP), { target: { files: names.map((n) => file(n)) } });
  await waitFor(() => expect(screen.getByTestId(`shape-row-${rows}`)).toBeTruthy(), { timeout: 5000 });
}
const seg = (i: number) => within(screen.getByRole("group", { name: `형상 ${i} 출처` }));

describe("메시 옵션 규칙(화면 쪽 함수)", () => {
  it("확장자 → 출처, 주 파일 규칙(C2-D-2), 파트 ID 검사, settings 보정", () => {
    expect(shapeKindOf("a.STP")).toBe("step");
    expect(shapeKindOf("a.inc")).toBe("mesh");
    expect(shapeKindOf("a.bdf")).toBeNull();
    expect(shapeKindOf("a.inc", [".rad"])).toBeNull();
    expect(meshMainCandidates(["m_0000.rad", "inc/a.rad", "b.inc"])).toEqual(["m_0000.rad"]);
    expect(meshMainCandidates(["m.rad", "a.inc", "b.inc"])).toEqual(["m.rad"]);
    expect(meshMainCandidates(["only.inc"])).toEqual(["only.inc"]);
    expect(meshMainCandidates(["z.rad", "a.rad", "c.inc"])).toEqual(["a.rad", "z.rad"]);
    expect(meshMainCandidates(["a.inc", "b.inc"])).toEqual(["a.inc", "b.inc"]);
    expect(partIdProblem("")).toBeNull();
    expect(partIdProblem("1001")).toBeNull();
    expect(partIdProblem("0")).toMatch(/1 이상 정수/);
    expect(partIdProblem("1.5")).toMatch(/1 이상 정수/);
    // 옛 서버(칸 없음) = 키 없음, 새 서버 = 그대로
    expect(normalizeDoeSettings({}).compare).not.toHaveProperty("mesh_mode");
    const n = normalizeDoeSettings({ compare: { mesh_mode: "auto", remesh_available: false, mesh_input: { enabled: true, formats: [".rad"], max_mb: 300 }, step_ready: true } });
    expect(n.compare).toMatchObject({ mesh_mode: "auto", remesh_available: false, mesh_input: { enabled: true, formats: [".rad"], max_mb: 300 }, step_ready: true });
  });

  it("'메시 방식' 문구·툴팁·배지 색(§8)", () => {
    const sh = (f: string, ref = false) => ({ upload_id: "u", name: f, reference: ref, file_name: `${f}.step`, sha256: f });
    const prep = makeComparePrep(compareIds([sh("base", true), sh("F_complex"), sh("G_hard"), sh("H_broken_coarse"), sh("I_broken")]), "step", "auto");
    const by = (id: string) => prep.shapes!.find((x) => x.id === id)!;
    expect(meshMethodLabel(by("d000"))).toBe("CAD");
    expect(meshMethodLabel(by("d001"))).toBe("세분화(국부 ×0.5 · 1.5 mm · 면 3 · 요소 ×1.4)");
    expect(meshMethodLabel(by("d002"))).toBe("세분화(전역 2.4 mm · 요소 ×1.6)");
    expect(meshMethodLabel(by("d003"))).toBe("재메시(폴백)");
    expect(meshMethodLabel({ mesh_method: "mesh_input" })).toBe("메시 입력");
    expect(meshMethodLabel({ mesh_method: "remesh" })).toBe("재메시");
    expect(meshMethodKind(by("d003"))).toBe("warn"); // 충실도 경고 초과(coarse)
    expect(meshMethodKind(by("d004"))).toBe("info");
    expect(meshMethodKind(by("d000"))).toBe("neutral");
    const tip3 = meshMethodTip(by("d003"));
    expect(tip3).toMatch(/최대 편차 0\.38 mm · 면적비 1\.00x/);
    expect(tip3).toMatch(/CAD 실패: gmsh 메시 생성에 실패/);
    const tip2 = meshMethodTip(by("d002"));
    expect(tip2).toMatch(/시도:\n1\. CAD 3 mm — 실패 MESH_FAILED · 41 s/);
    expect(tip2).toMatch(/2\. 국부 세분화 — 건너뜀\(REFINE_LOCAL_NO_FACE\)/);
    expect(tip2).toMatch(/3\. 전역 세분화 ×0\.8 2\.4 mm — 성공/);
    // 결과 shape: 수렴 점검 δ(C2-D-24)
    const res = makeCompareResult(prep, ["e1", "e2"]);
    const loc = res.ranking.find((r) => r.id === "d001")!.shape!;
    expect(meshMethodTip(loc)).toMatch(/수렴 점검 δ 최대 \+1\.2 % \(기준을 1\.5 mm 로 다시 해석 · 허용 \+1\.0 %\) — 메시 편향 큼/);
    expect(meshMethodKind(loc)).toBe("warn");
    expect(meshMethodTip({ mesh_method: "mesh_input", edge_median_mm: 3.05, n_components: 2 }, 1001)).toBe("파트 ID 1001\n요소 크기 중앙값 3.05 mm\n연결 성분 2개");
    // 경고: 방식 혼합·폴백·세분화
    expect(prep.warnings.map((w) => w.code)).toEqual(expect.arrayContaining(["COMPARE_MESH_METHOD_MIXED", "REMESH_USED", "REMESH_FIDELITY_WARN", "MESH_REFINED"]));
    // v0.15 스터디(mode 없음) = 메시 방식 칸 없음(cad 로 봄, 바이트 불변)
    expect(makeComparePrep(compareIds([sh("a", true), sh("b")]), "step").shapes![1]).not.toHaveProperty("mesh_method");
  });
});

describe("④ 새 연구 — 형상 표 메시 행", () => {
  it("STEP 2 + rad/inc 묶음을 한 번에 놓기 → STEP 행 2 + 메시 행 1, 토글 기본 = 확장자, 파트 하나 자동 채움, 요청 source·part_id", async () => {
    const { container, server } = await openCompare();
    await drop(["chr_base.step", "chr_rib_A.stp", "chr_hm_0000.rad", "body.inc", "fix.inc"], 3);
    expect(screen.queryByTestId("shape-row-4")).toBeNull();
    // 토글: STEP 행은 STEP 눌림·메시 비활성, 메시 행은 반대
    expect(seg(1).getByRole("button", { name: "STEP" }).getAttribute("aria-pressed")).toBe("true");
    expect((seg(1).getByRole("button", { name: "메시" }) as HTMLButtonElement).disabled).toBe(true);
    expect(seg(1).getByRole("button", { name: "메시" }).getAttribute("title")).toMatch(/STEP 파일은 메시로 읽을 수 없습니다/);
    expect(seg(3).getByRole("button", { name: "메시" }).getAttribute("aria-pressed")).toBe("true");
    expect((seg(3).getByRole("button", { name: "STEP" }) as HTMLButtonElement).disabled).toBe(true);
    const r3 = screen.getByTestId("shape-row-3");
    expect(r3.textContent).toMatch(/chr_hm_0000\.rad 주 파일 \+ include 2개/);
    expect((within(r3).getByRole("textbox", { name: "형상 3 이름" }) as HTMLInputElement).value).toBe("chr_hm_0000");
    // 파트 ID 칸: 메시 행에만
    expect(screen.getByRole("columnheader", { name: "파트 ID" })).toBeTruthy();
    expect(screen.queryByRole("spinbutton", { name: "형상 1 파트 ID" })).toBeNull();
    const pid = screen.getByRole("spinbutton", { name: "형상 3 파트 ID" }) as HTMLInputElement;
    await waitFor(() => expect(pid.value).toBe("1001"), { timeout: 4000 });
    expect(within(r3).getByTestId("parts-3").querySelectorAll("option")).toHaveLength(1);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false), { timeout: 4000 });
    fireEvent.click(primaries(container)[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" })).toBeTruthy();
    const rec = server.doe.recs[server.doe.recs.length - 1];
    expect(rec.out.inputs.shapes!.map((x) => [x.id, x.rel, x.source ?? "-", x.part_id ?? "-"])).toEqual([
      ["d000", "rad/chr_base.step", "-", "-"],
      ["d001", "rad/chr_rib_A.stp", "-", "-"],
      ["d002", "rad/chr_hm_0000.rad", "mesh", 1001],
    ]);
    expect(rec.out.inputs.mesh_mode).toBe("auto");
    // 준비 후: '메시 방식' 열(STEP = CAD, 메시 = 메시 입력) + 출처 배지
    server.drain();
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["비교 실행"]), { timeout: 6000 });
    expect(screen.getByTestId("prep-method-d002").textContent).toBe("메시 입력");
    expect(screen.getByTestId("prep-method-d002").querySelector(".badge")!.getAttribute("title")).toMatch(/파트 ID 1001 · ?|파트 ID 1001/);
    expect(screen.getByTestId("prep-method-d000").textContent).toBe("CAD");
    expect(screen.getByTestId("prep-shape-d002").textContent).toMatch(/메시/);
  }, 20000);

  it("파트 여럿: 422 MESH_INPUT_PART_REQUIRED → datalist 2개·빈 칸·주 버튼 사유 → ID 입력 후 통과, 잘못된 ID 는 행 오류", async () => {
    const { container } = await openCompare();
    await drop(["chr_base.step", "chr_multi.rad", "a.inc"], 2);
    await waitFor(() => expect(screen.getByTestId("parts-2").querySelectorAll("option")).toHaveLength(2), { timeout: 4000 });
    const pid = screen.getByRole("spinbutton", { name: "형상 2 파트 ID" }) as HTMLInputElement;
    expect(pid.value).toBe("");
    expect(pid.getAttribute("placeholder")).toBe("고르기");
    expect([...screen.getByTestId("parts-2").querySelectorAll("option")].map((o) => [o.getAttribute("value"), o.textContent])).toEqual([
      ["1001", "chassis_rear · 쉘 182,400"],
      ["2001", "bracket_L · 쉘 6,120"],
    ]);
    expect(reasonOf(primaries(container)[0])).toMatch(/쉘 파트가 여러 개입니다.*\(형상 2\)/);
    fireEvent.change(pid, { target: { value: "0" } });
    expect(within(screen.getByTestId("shape-row-2")).getByText(/1 이상 정수/)).toBeTruthy();
    expect(reasonOf(primaries(container)[0])).toBe("형상 2: 파트 ID 는 1 이상 정수입니다");
    fireEvent.change(pid, { target: { value: "2001" } });
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false), { timeout: 4000 });
    expect(screen.getByTestId("doe-check")).toBeTruthy();
  }, 15000);

  it("주 파일을 못 정하는 묶음(.rad 여러 개) → 주 파일 고르기, 바꾸면 요청 rel 바뀜", async () => {
    await openCompare();
    await drop(["chr_base.step", "z_main.rad", "a_sub.rad"], 2);
    const sel = screen.getByRole("combobox", { name: "형상 2 주 파일" }) as HTMLSelectElement;
    expect([...sel.options].map((o) => o.textContent)).toEqual(["a_sub.rad", "z_main.rad"]);
    fireEvent.change(sel, { target: { value: "rad/z_main.rad" } });
    expect(sel.value).toBe("rad/z_main.rad");
    expect(screen.getByTestId("shape-row-2").textContent).toMatch(/주 파일 \+ include 1개/);
  }, 10000);

  it("메시 입력 꺼짐(옛 서버) → STEP 만 받음·출처 열 없음·고급 설정 없음", async () => {
    await openCompare((s) => {
      s.doe.settings.compare = { enabled: true, reason: null, max_shapes: 20, total_max_mb: 1000, mesh_size_mm: 3 };
      delete s.doe.settings.load_transfer; // 옛 서버: 고급 설정 칸 자체가 없음(v0.20.0 하중 전달 select 도 없음)
    });
    const input = screen.getByLabelText("비교할 STEP 끌어다 놓기(여러 개)");
    fireEvent.change(input, { target: { files: [file("a.step"), file("m.rad")] } });
    expect(await screen.findByText(/m\.rad: \.step·\.stp 만 올릴 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "출처" })).toBeNull();
    expect(screen.queryByTestId("compare-adv")).toBeNull();
  });
});

describe("④ 새 연구 — 고급 설정(메시 방식)", () => {
  it("기본 자동·세분화 허용 → CAD 고르면 세분화 비활성·요청 mesh_mode cad, 세분화 끄면 mesh_refine false", async () => {
    const { container, server } = await openCompare();
    const adv = screen.getByTestId("compare-adv");
    expect(adv.tagName).toBe("DETAILS");
    expect(adv.hasAttribute("open")).toBe(false);
    expect(within(adv).getByText(/메시 방식 자동/)).toBeTruthy();
    const group = within(adv).getByRole("radiogroup", { name: "메시 방식" });
    expect(within(group).getAllByRole("radio").map((b) => b.textContent)).toEqual(["자동(기본)", "CAD", "재메시", "freeform"]);
    expect(within(group).getByRole("radio", { name: "자동(기본)" }).getAttribute("aria-checked")).toBe("true");
    const chk = within(adv).getByRole("checkbox", { name: "실패 시 세분화 허용" }) as HTMLInputElement;
    expect(chk.checked).toBe(true);
    expect(chk.disabled).toBe(false);
    await drop(["chr_base.step", "chr_rib_A.step"], 2);
    // 세분화 끄기 → 요청 mesh_refine false
    fireEvent.click(chk);
    expect(within(adv).getByText(/메시 방식 자동\(세분화 끔\)/)).toBeTruthy();
    fireEvent.click(within(group).getByRole("radio", { name: "CAD" }));
    expect(within(group).getByRole("radio", { name: "CAD" }).getAttribute("aria-checked")).toBe("true");
    expect(chk.disabled).toBe(true);
    expect(screen.getByTestId("compare-adv-hint").textContent).toMatch(/CAD 면 구조 그대로/);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false), { timeout: 4000 });
    fireEvent.click(primaries(container)[0]);
    await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" });
    const rec = server.doe.recs[server.doe.recs.length - 1];
    expect(rec.out.inputs.mesh_mode).toBe("cad");
    expect(rec.out.inputs.mesh_refine).toBe(false);
  }, 15000);

  it("remesh_available false → 재메시 비활성 + 사유 툴팁(gmsh 버전), 메시 형상만이면 숨김", async () => {
    await openCompare((s) => {
      s.doe.settings.compare!.remesh_available = false;
    });
    const adv = screen.getByTestId("compare-adv");
    const rm = within(adv).getByRole("radio", { name: "재메시" }) as HTMLButtonElement;
    expect(rm.disabled).toBe(true);
    expect(rm.parentElement!.getAttribute("title")).toBe("이 gmsh 버전(4.13.1)은 삼각형 재메시를 지원하지 않습니다");
    expect(screen.getByTestId("compare-adv-hint").textContent).toMatch(/재메시 불가/);
    // 메시 형상만 → 메시 방식 줄 숨김(v0.20.0: 하중 전달 select 때문에 고급 설정 칸 자체는 남음)
    await drop(["only_0000.rad", "x.inc"], 1);
    expect(within(screen.getByTestId("compare-adv")).queryByRole("radiogroup", { name: "메시 방식" })).toBeNull();
  }, 10000);
});

describe("④ 결과 — doe-7(메시 입력 기준 + CAD·세분화·재메시 폴백)", () => {
  it("형상 표 '메시 방식' 열·툴팁, 순위표·ESL별 표 짧은 배지(CAD 생략), 경고", async () => {
    const { container } = renderApp("/p/p-body/doe/doe-7");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(primaries(container).map((b) => b.textContent)).toEqual(["보고서 보기"]));
    const shapeTable = screen.getAllByRole("table", { name: "형상 표" })[0];
    expect(within(shapeTable).getByRole("columnheader", { name: "메시 방식" })).toBeTruthy();
    const m = (id: string) => screen.getByTestId(`prep-method-${id}`);
    expect(m("d000").textContent).toBe("메시 입력");
    expect(m("d001").textContent).toBe("CAD");
    expect(m("d002").textContent).toBe("세분화(국부 ×0.5 · 1.5 mm · 면 3 · 요소 ×1.4)");
    expect(m("d003").textContent).toBe("세분화(전역 2.4 mm · 요소 ×1.6)");
    expect(m("d004").textContent).toBe("재메시(폴백)");
    expect(m("d004").querySelector(".badge")!.className).toMatch(/\bwarn\b/);
    expect(m("d004").querySelector(".badge")!.getAttribute("title")).toMatch(/최대 편차 .* mm · 면적비/);
    expect(m("d000").querySelector(".badge")!.getAttribute("title")).toMatch(/파트 ID 1001\n요소 크기 중앙값 3\.05 mm/);
    expect(m("d002").querySelector(".badge")!.getAttribute("title")).toMatch(/시도:\n1\. CAD 3 mm — 실패/);
    expect(screen.getByTestId("doe-input-summary").textContent).toMatch(/메시 방식 자동/);
    // 순위표: 이름 옆 짧은 배지, CAD 는 생략, 툴팁에 δ
    expect(within(t).getByTestId("rank-method-d002").textContent).toBe("세분화");
    expect(within(t).getByTestId("rank-method-d002").getAttribute("title")).toMatch(/수렴 점검 δ 최대/);
    expect(within(t).getByTestId("rank-method-d004").textContent).toBe("재메시(폴백)");
    expect(within(t).queryByTestId("rank-method-d001")).toBeNull();
    expect(within(t).getByTestId("rank-method-d000").textContent).toBe("메시 입력");
    // ESL별 표
    const pe = screen.getByRole("table", { name: "ESL별 개선율" });
    expect(within(pe).getByTestId("per-esl-method-d003").textContent).toBe("세분화");
    // 경고(서버 message)
    expect(screen.getAllByText(/형상마다 메시 방식이 달라/).length).toBeGreaterThan(0);
  });
});

describe("v0.16.0 Verifier 수정(경고 조건·사다리 실패 문구)", () => {
  const sh = (f: string, ref = false) => ({ upload_id: "u", name: f, reference: ref, file_name: `${f}.step`, sha256: f });
  it("C2-D-1: {cad, Case 메시} 만이면 COMPARE_MESH_METHOD_MIXED 없음(COMPARE_REF_CASE_MESH 만), 세분화·폴백·메시 입력이 섞이면 경고", () => {
    expect(meshMethodsMixed(new Set(["cad", "case"]))).toBe(false);
    expect(meshMethodsMixed(new Set(["cad"]))).toBe(false);
    expect(meshMethodsMixed(new Set(["remesh"]))).toBe(false);
    expect(meshMethodsMixed(new Set(["cad", "refine"]))).toBe(true);
    expect(meshMethodsMixed(new Set(["case", "fallback"]))).toBe(true);
    expect(meshMethodsMixed(new Set(["cad", "mesh_input"]))).toBe(true);
    const caseOnly = makeComparePrep(compareIds([sh("a"), sh("b")]), "case", "auto");
    expect(caseOnly.warnings.map((w) => w.code)).toEqual(["COMPARE_REF_CASE_MESH"]);
    const caseMix = makeComparePrep(compareIds([sh("a"), sh("b_broken")]), "case", "auto");
    expect(caseMix.warnings.map((w) => w.code)).toEqual(expect.arrayContaining(["COMPARE_REF_CASE_MESH", "COMPARE_MESH_METHOD_MIXED"]));
  });

  it("결과 경고 목록에 REMESH_FIDELITY_WARN 포함", () => {
    const prep = makeComparePrep(compareIds([sh("base", true), sh("H_broken_coarse")]), "step", "auto");
    const res = makeCompareResult(prep, ["e1"]);
    expect(res.warnings.map((w) => w.code)).toEqual(expect.arrayContaining(["REMESH_FIDELITY_WARN", "REMESH_USED"]));
  });

  it("사다리 전부 실패: 형상 표 실패 행 문구·툴팁에 CAD 원 오류 + 마지막 오류", () => {
    const prep = makeComparePrep(compareIds([sh("base", true), sh("Z_dead")]), "step", "auto");
    const d = prep.shapes!.find((x) => x.id === "d001")!;
    expect(d.status).toBe("FAILED_MESH");
    expect(shapeFailText(d)).toBe(`CAD 메시 실패: gmsh 메시 생성에 실패했습니다(면 37: 1D 메시 실패) → 세분화·재메시도 실패: ${d.message}`);
    expect(shapeFailTip(d)).toMatch(/시도:\n1\. CAD 3 mm — 실패 MESH_FAILED[\s\S]*3\. 전역 세분화 ×0\.8 2\.4 mm — 건너뜀\(시간 예산\)[\s\S]*4\. 재메시 3 mm — 실패 REMESH_FAILED/);
    expect(shapeFailText({ status: "FAILED_MESH", code: "MESH_FAILED", message: "x" })).toBe("x");
    expect(
      shapeFailText({ status: "FAILED_MESH", code: "REMESH_FAILED", message: "m", cad_error: { code: "MESH_FAILED", message: "c" }, attempts: [{ stage: "remesh", status: "SKIPPED", skipped: true, reason: "time" }] }),
    ).toBe("CAD 메시 실패: c → 세분화·재메시는 건너뜀(time)");
    const study = { inputs: { reference_source: "step", shapes: [], mesh_mode: "auto" }, prep } as unknown as DoeStudyOut;
    render(<CompareShapeSummary study={study} />);
    const cell = screen.getByTestId("prep-fail-d001");
    expect(cell.textContent).toMatch(/CAD 메시 실패: gmsh 메시 생성에 실패했습니다\(면 37: 1D 메시 실패\) → 세분화·재메시도 실패: 삼각형 재메시에 실패/);
    expect(cell.getAttribute("title")).toMatch(/시도:\n1\. CAD/);
  });
});
