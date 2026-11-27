// V-0241-V3D-19·20(프런트) + 현장 피드백: 스터디 자료 만들기 버튼 ≤ 1 · 하중 색 토글 · 재현 진단 · 불가 사유 가시 줄.
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PickEvent } from "../view3d/sceneApi";

const h = vi.hoisted(() => ({ webgl: true, scenes: [] as unknown[], loadFails: false }));

vi.mock("../view3d/webgl", () => ({ hasWebGL: () => h.webgl }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => {
    if (h.loadFails) throw new Error("chunk");
    return {
      createScene: (_c: unknown, opts: unknown) => {
        const calls: Record<string, unknown[][]> = {};
        let pick: ((e: PickEvent) => void) | null = null;
        const rec = (name: string) => (...a: unknown[]) => {
          (calls[name] ??= []).push(a);
        };
        let proj = (opts as { projection?: string }).projection ?? "ortho";
        const api = {
          calls,
          opts,
          setProjection: (p: string) => {
            rec("setProjection")(p);
            proj = p;
          },
          projection: () => proj,
          emit: (e: PickEvent) => pick?.(e),
          setGeometry: rec("setGeometry"),
          setColors: rec("setColors"),
          setDeform: rec("setDeform"),
          setArrows: rec("setArrows"),
          setSupports: rec("setSupports"),
          select: rec("select"),
          focus: rec("focus"),
          fit: rec("fit"),
          setView: rec("setView"),
          onPick: (cb: (e: PickEvent) => void) => (pick = cb),
          stats: () => ({ renders: 0 }),
          dispose: rec("dispose"),
        };
        h.scenes.push(api);
        return api;
      },
    };
  },
}));

import { renderApp } from "../test/render";
import { NO_C_TEXT } from "../view3d/View3DCard";
import { PER_ESL_HEAT_SPAN, heatStyle, perEslNote } from "../components/DoePerEslTable";
import { COLOR_SEL_BUTTONS, SCENE_TEXT, approxFor, colorDisabled, hasScenePair, sceneChoices, sceneSummary, skippedFor, toggleScene } from "../pages/doe/doeScene";
import FX from "../mock/fixtures/scene_real_v0251.json";
import FXS from "../mock/fixtures/scene_summary_real_v0251.json";
import { sceneManifest } from "../mock/scenemock";
import { css, mapFor, relLuminance, table, textOn } from "../lib/colormap";
import CM from "../../../resources/colormaps.json";
import type { DoeMock } from "../mock/doedata";
import type { DoeResultOut } from "../api/types";

afterEach(cleanup);
let doeMock: DoeMock | null = null;
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => {
  s.doe.demoScene();
  doeMock = s.doe;
});
const sel = () => screen.findByTestId("v3d-scene-select", {}, { timeout: 10000 }) as Promise<HTMLSelectElement>;

// 통합 INT-10: 실제 백엔드 응답(코어 build_scene_pack 씬 묶음 → GET manifest·파일 그대로 — backend 시험
// test_int10_frontend_fixture_is_real_api_response 가 이 파일 = API 응답임을 확인)으로 씬 요청에 답한다. 엔트리 첫째 = E0, 나머지 = E1.
const fx = FX as unknown as { manifests: Record<string, Record<string, unknown>>; files: Record<string, string> };
function openReal(id: string, patch?: (d: DoeMock) => void) {
  const seen: string[] = [];
  const r = renderApp(`/p/p-body/doe/${id}`, "power", (s) => {
    s.doe.demoScene();
    doeMock = s.doe;
    patch?.(s.doe);
  });
  const orig = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
    const m = /\/doe\/studies\/([^/]+)\/view3d-scene\/([^/]+)\/([^/]+)\/(.+)$/.exec(u.pathname);
    if (!m) return orig(input, init);
    seen.push(u.pathname + u.search);
    const [, sid, src, did, tail] = m;
    const fd = did === "d000" ? "d000" : "d001";
    const mm = /^([^/]+)\/manifest\.json$/.exec(tail);
    if (mm) {
      const entries = doeMock!.recs.find((x) => x.out.id === sid)?.result?.scene_view?.entries ?? [];
      const fe = entries.findIndex((e) => e.entry_id === decodeURIComponent(mm[1])) <= 0 ? "E0" : "E1";
      const txt = JSON.stringify(fx.manifests[`${fd}/${fe}`]).split(`/doe/studies/{SID}/view3d-scene/full/${fd}`).join(`/doe/studies/${sid}/view3d-scene/${src}/${did}`);
      return new Response(txt, { status: 200, headers: { "Content-Type": "application/json" } });
    }
    const b = fx.files[`${fd}/${tail}`];
    if (!b) return new Response(JSON.stringify({ detail: { code: "VIEW3D_SCENE_NOT_FOUND", message: "없음" } }), { status: 404, headers: { "Content-Type": "application/json" } });
    return new Response(Uint8Array.from(atob(b), (c) => c.charCodeAt(0)), { status: 200, headers: { "Content-Type": "application/octet-stream" } });
  }) as typeof fetch;
  return { ...r, seen };
}
const calls = () => doeMock!.sceneManifestCalls;
const lastCalls = (n: number) => calls().slice(-n);

describe("V-0251-25 씬 연결 (순수)", () => {
  const mk = (): DoeResultOut => (doeMock ? ({} as DoeResultOut) : ({} as DoeResultOut));
  it("hasScenePair·skippedFor·sceneChoices·toggleScene", () => {
    const r = {
      ranking: [], baseline: {}, view3d: [], warnings: [],
      esl: [{ entry_id: "e1", label: "E1" }, { entry_id: "e2", label: "E2" }],
      scene_view: {
        entries: [{ entry_id: "e1", kk: 0 }, { entry_id: "e2", kk: 1 }],
        packs: { full: { designs: { d000: ["e1"], d001: ["e1"] }, skipped: [{ did: null, entry_id: "e2", code: "SCENE_BUDGET", text: "한도" }] } },
      },
    } as unknown as DoeResultOut;
    void mk;
    expect(hasScenePair(r, "full", "d001", "e1")).toBe(true);
    expect(hasScenePair(r, "full", "d001", "e2")).toBe(false);
    expect(hasScenePair(r, "jig", "d001", "e1")).toBe(false);            // 이 출처 묶음 없음 → 기존 폴더
    expect(skippedFor(r, "full", "d001", "e2")?.code).toBe("SCENE_BUDGET");
    expect(skippedFor(r, "full", "d001", "e1")).toBeNull();
    expect(sceneChoices(r, "full", "d001").map((c) => [c.entry_id, c.missing])).toEqual([["e1", false], ["e2", true]]);
    expect(sceneChoices(r, "jig", "d001").map((c) => c.missing)).toEqual([false, false]);
    expect(toggleScene(null, "e1")).toBe("e1");
    expect(toggleScene("e1", "e1")).toBeNull();
    expect(toggleScene("e1", "e2")).toBe("e2");
  });
  it("씬 요약(INT-14): 표 값만 — C·변화율 = 표 행, umax 는 기준 행이 있을 때 같은 정의끼리(ev 끼리·umax 끼리)", () => {
    const row = { entry_id: "e1", C: 800, ratio: 0.8, umax: 1.2, umax_ev: 1.1, epsmax: 0 };
    const t = sceneSummary({ label: "E1", row, baseRow: { umax: 1.0, umax_ev: 1.0 } });
    expect(t).toBe("ESL E1 · C 기준 1000 → 안 800 (−20.0 %) · umax 기준 1.000 → 안 1.100 (+10.0 %) mm");   // ev 끼리(전체 1.2 아님)
    expect(sceneSummary({ label: "E1", row, baseRow: { umax: 1.0 } })).toBe("ESL E1 · C 기준 1000 → 안 800 (−20.0 %)");   // 정의 섞임 = umax 비움
    expect(sceneSummary({ label: "E1", row: { ...row, umax_ev: null }, baseRow: { umax: 1.0, umax_ev: null } })).toContain("umax 기준 1.000 → 안 1.200 (+20.0 %) mm");
    expect(sceneSummary({ label: "E1", row, baseRow: null })).toBe("ESL E1 · C 기준 1000 → 안 800 (−20.0 %)");   // 기준 행 없음 = C 만
    expect(sceneSummary({ label: "E1", row: null })).toBe("ESL E1");   // 표 행 없음 = 숫자 없음(핀·manifest 숫자 안 씀)
  });
});

describe("V-0251-27 색 모드 비활성 사유", () => {
  it("c = 두 카드 모두 배열 필요, dc = 안 카드만", () => {
    const b = sceneManifest("s", "full", "d000", "e1", 0);
    const d = sceneManifest("s", "full", "d001", "e1", 0);
    expect(colorDisabled("c", "NC", "ND", b, d)).toBeNull();
    expect(colorDisabled("dc", "NC", "ND", b, d)).toBeNull();
    expect(colorDisabled("dc", "NC", "ND", d, b)).toBe("ND");            // 안 카드 dc null
    expect(colorDisabled("c", "NC", "ND", {}, d)).toBe("NC");
    expect(colorDisabled("disp", "NC", "ND", null, null)).toBeNull();
    expect(COLOR_SEL_BUTTONS.map((x) => x.key)).toEqual(["disp", "load", "c", "dc"]);
  });
});

describe("V-0251-45 ESL 개선율 칸 색(L10)", () => {
  it("개선 = 파랑 쪽 · 악화 = 빨강 쪽 · 0 = 무색 · 세기 ±PER_ESL_HEAT_SPAN · 자원 지도와 같은 rgb", () => {
    const rgb = (b?: string) => (b ?? "").match(/\d+/g)!.map(Number);
    const up = rgb(heatStyle(0.3).background);
    const dn = rgb(heatStyle(-0.3).background);
    expect(up[2]).toBeGreaterThan(up[0]);
    expect(dn[0]).toBeGreaterThan(dn[2]);
    expect(heatStyle(0)).toEqual({});
    expect(PER_ESL_HEAT_SPAN).toBe(0.5);
    expect(heatStyle(0.5).background).toBe(css(mapFor("div"), 0));       // 끝 = 지도 −끝(파랑)
    expect(heatStyle(-0.5).background).toBe(css(mapFor("div"), 1));
    expect(heatStyle(5).background).toBe(css(mapFor("div"), 0));         // 자름
  });
  it("진한 칸 흰 글자(통합 INT): 배경 상대 휘도 < 자원 text.dark_lum → on_dark, 아니면 on_light — 보고서와 같은 표·같은 기대값", () => {
    const tx = (CM as unknown as { text: { dark_lum: number; on_dark: number[]; on_light: number[] } }).text;
    const white = `rgb(${tx.on_dark.join(",")})`;
    const dark = `rgb(${tx.on_light.join(",")})`;
    // tests/doe/test_report_doe.py::test_v0251_45_per_esl_cell_colors 와 같은 (개선율, 기대) 표
    const TEXT_CASES: [number, string][] = [[0.5, white], [0.4, white], [0.3, dark], [0.05, dark], [-0.05, dark], [-0.3, dark], [-0.4, white], [-0.5, white]];
    for (const [imp, want] of TEXT_CASES) expect(heatStyle(imp).color, String(imp)).toBe(want);
    expect(heatStyle(0).color).toBeUndefined();
    for (const role of ["div", "seq"] as const) {
      const tb = table(mapFor(role));
      for (let k = 0; k < 256; k++) {
        const c: [number, number, number] = [tb[k * 3], tb[k * 3 + 1], tb[k * 3 + 2]];
        expect(textOn(c)).toBe(relLuminance(c) < tx.dark_lum ? white : dark);
      }
    }
  });
  it("표 설명 문구", () => {
    const r = { esl: [{ entry_id: "e1" }], ranking: [] } as unknown as DoeResultOut;
    expect(perEslNote(r, null)).toContain("파랑 개선(C 감소) · 빨강 악화(C 증가)");
  });
});

describe("통합 INT-10~12 — 실제 응답 형식·근사 씬·형상 캐시", () => {
  it("INT-10·12: 실제 백엔드 응답(값 배열 c·dc)으로 자동(최악 ESL) 두 카드 정상 — C 기여도 활성, 씬을 바꿔도 형상 URL 같음·값 URL 바뀜", async () => {
    const n0 = h.scenes.length;
    const { seen } = openReal("doe-60");
    await waitFor(() => expect(screen.getAllByTestId("v3d-host").map((e) => e.getAttribute("data-phase"))).toEqual(["ready", "ready"]), { timeout: 10000 });
    expect(screen.queryByTestId("v3d-unavailable")).toBeNull();
    expect(h.scenes.length - n0).toBeGreaterThanOrEqual(2);
    const seg = screen.getByTestId("v3d-color");
    expect((seg.querySelector("[data-color=c]") as HTMLButtonElement).disabled).toBe(false);
    expect((seg.querySelector("[data-color=dc]") as HTMLButtonElement).disabled).toBe(false);
    const geo = () => new Set(seen.filter((x) => /\/part\.glb/.test(x)));
    const g0 = geo();
    expect(g0.size).toBe(2);                                            // 기준·안 묶음마다 1개
    expect([...g0].every((x) => /[?&]key=doe%2Fscene%2Fsv%2Fd00\d$/.test(x))).toBe(true);   // 키 = 묶음(씬 아님)
    const s = await sel();
    fireEvent.change(s, { target: { value: s.options[2].value } });
    await waitFor(() => expect(seen.some((x) => /\/e01\.bin/.test(x))).toBe(true), { timeout: 10000 });
    await waitFor(() => expect(screen.getAllByTestId("v3d-host").map((e) => e.getAttribute("data-phase"))).toEqual(["ready", "ready"]), { timeout: 10000 });
    expect(geo()).toEqual(g0);                                          // 씬 전환 뒤에도 형상 URL 그대로(브라우저 캐시·304)
  }, 30000);

  it("INT-11: 근사 씬(packs.approx) = 3D 바 정보 한 줄, 씬 요약 숫자 = 표(per_esl) 값", async () => {
    openReal("doe-60", (d) => {
      const rec = d.recs.find((x) => x.out.id === "doe-60")!;
      const sv = rec.result!.scene_view!;
      const text = "이 3D 의 C 기여도 합이 표의 C 와 다릅니다(하중 공간 고정 등 — 3D 하중 입력이 평가와 다름) — 색은 근사, 숫자는 표 기준";
      for (const pk of Object.values(sv.packs))
        pk.approx = Object.keys(pk.designs).filter((x) => x !== "d000").flatMap((did) => sv.entries.map((e) => ({ did, entry_id: e.entry_id, code: "SCENE_C_MISMATCH", text })));
    });
    const line = await screen.findByTestId("v3d-scene-approx", {}, { timeout: 10000 });
    expect(line.textContent).toContain("숫자는 표 기준");
    expect(screen.getByTestId("v3d-barline").getAttribute("title")).toContain("숫자는 표 기준");
    // 씬을 직접 골라 그 칸(ESL 표 셀 title = 표 값 C·umax)과 요약 숫자 비교 — 요약은 manifest(근사)가 아니라 표 값
    const s = await sel();
    const eid = s.options[1].value;
    fireEvent.change(s, { target: { value: eid } });
    const pick = (screen.getByLabelText("3D 비교 안") as HTMLSelectElement).value;
    const cell = await screen.findByTestId(`per-esl-cell-${pick}-${eid}`, {}, { timeout: 10000 });
    const tt = cell.getAttribute("title") ?? "";
    const tC = Number(/^C ([^ ]+)/.exec(tt)![1]);
    await waitFor(() => expect(screen.getByTestId("v3d-scene-summary").textContent).toContain(`ESL ${s.options[1].textContent}`), { timeout: 10000 });
    const sum = screen.getByTestId("v3d-scene-summary").textContent ?? "";
    const sC = Number(/C 기준 [^ ]+ → 안 ([^ ]+)/.exec(sum)![1]);
    expect(Math.abs(sC / tC - 1)).toBeLessThan(1e-3);
    expect(sum).not.toMatch(/umax 안 /);                                // umax 는 기준과 같은 정의 쌍으로만(INT-14)
  }, 30000);

  it("INT-14 실제 BD_POST 결과(평가 영역 있는 same_all6, 출처 6 보기): 요약 umax 증감 = 표 정의(ev)끼리, 부호 뒤집힘 0", () => {
    type P = { entry_id: string; C: number; ratio: number; umax: number; umax_ev: number | null };
    const fxs = FXS as unknown as { tabs: Record<string, { baseline: { worst_entry_id: string; umax: number; umax_ev: number | null }; rows: { id: string; per_esl: P[] }[] }> };
    let shown = 0;
    let mixedRows = 0;
    for (const [tab, t] of Object.entries(fxs.tabs)) {
      const b = t.baseline;
      for (const r of t.rows)
        for (const p of r.per_esl) {
          if (p.umax_ev != null && p.umax_ev !== p.umax) mixedRows += 1;
          const s = sceneSummary({ label: p.entry_id, row: { ...p, epsmax: 0 }, baseRow: b.worst_entry_id === p.entry_id ? b : null });
          expect(s, `${tab} ${r.id} ${p.entry_id}`).toContain(`(${p.ratio - 1 >= 0 ? "+" : "−"}${Math.abs((p.ratio - 1) * 100).toFixed(1)} %)`);
          const m = /umax 기준 ([\d.]+) → 안 ([\d.]+) \(([+−])/.exec(s);
          if (b.worst_entry_id !== p.entry_id) {
            expect(m, `${tab} ${r.id} ${p.entry_id}`).toBeNull();
            continue;
          }
          shown += 1;
          const [u0, u1] = [b.umax_ev ?? b.umax, p.umax_ev ?? p.umax];
          expect(m![1]).toBe(u0.toFixed(3));
          expect(m![2]).toBe(u1.toFixed(3));
          expect(m![3]).toBe(u1 / u0 - 1 >= 0 ? "+" : "−");             // 표 정의끼리 비교와 같은 부호
        }
    }
    expect(Object.keys(fxs.tabs).length).toBe(6);
    expect(shown).toBeGreaterThan(0);
    expect(mixedRows).toBeGreaterThan(0);                               // umax ≠ umax_ev 인 행이 있는 자료(정의 혼합을 잡음)
  });

  it("approxFor(순수)", () => {
    const r = { scene_view: { entries: [{ entry_id: "E0", kk: 0 }], packs: { full: { designs: {}, approx: [{ did: "d001", entry_id: "E0", code: "SCENE_PIN_MISMATCH", text: "a" }, { did: "d000", entry_id: "E0", code: "SCENE_C_MISMATCH", text: "b" }, { did: "d002", entry_id: "E0", code: "SCENE_C_MISMATCH", text: "c" }] } } } } as unknown as DoeResultOut;
    expect(approxFor(r, "full", "d001", "E0")).toEqual({ base: ["SCENE_C_MISMATCH"], cand: ["SCENE_PIN_MISMATCH"], texts: ["a", "b"] });
    expect(approxFor(r, "full", "d001", "E1")).toEqual({ base: [], cand: [], texts: [] });
  });
});

describe("V-0251-25·26 화면: 씬 선택·옛 결과", () => {
  it("3D 바 선택 칸·ESL 표 열 머리·셀·순위표 최악 칸 → 두 카드 요청 URL 의 씬이 바뀜, 안을 바꿔도 유지", async () => {
    open("doe-60");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const s = await sel();
    const opts = [...s.options].map((o) => o.textContent);
    expect(opts[0]).toMatch(/^자동 — 최악 ESL\(/);
    expect(opts.length).toBeGreaterThan(2);
    expect(opts[opts.length - 1]).toContain(SCENE_TEXT.noDataTail.trim());   // 한도로 빠진 마지막 씬
    // 자동 = 씬 묶음의 최악 엔트리(기준 d000 도 같은 씬)
    await waitFor(() => expect(calls().length).toBeGreaterThanOrEqual(2), { timeout: 8000 });
    const auto = calls().slice(-2);
    expect(auto[0].split("/")[2]).toBe(auto[1].split("/")[2]);
    expect(new Set(auto.map((x) => x.split("/")[1]))).toContain("d000");
    // 선택 칸으로 씬 고르기
    const e2 = s.options[2].value;
    fireEvent.change(s, { target: { value: e2 } });
    await waitFor(() => expect(lastCalls(2).every((x) => x.endsWith(`/${e2}`))).toBe(true), { timeout: 8000 });
    await waitFor(() => expect(screen.getByTestId("v3d-scene-summary").textContent).toMatch(/C 기준 .* → 안 /), { timeout: 8000 });
    // 안을 바꿔도 씬 유지
    const pickSel = screen.getByLabelText("3D 비교 안") as HTMLSelectElement;
    const other = [...pickSel.options].map((o) => o.value).find((v) => v !== pickSel.value)!;
    fireEvent.change(pickSel, { target: { value: other } });
    await waitFor(() => expect(lastCalls(2).every((x) => x.endsWith(`/${e2}`))).toBe(true), { timeout: 8000 });
    expect((await sel()).value).toBe(e2);
    // ESL 표 열 머리: 다른 씬 → 다시 누르면 자동
    const e1 = s.options[1].value;
    fireEvent.click(await screen.findByTestId(`per-esl-col-${e1}`));
    await waitFor(() => expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(e1));
    fireEvent.click(screen.getByTestId(`per-esl-col-${e1}`));
    await waitFor(() => expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(""));
    // 셀 클릭 = 그 안 + 그 씬
    const cell = document.querySelector(`[data-testid^="per-esl-cell-"][data-testid$="-${e2}"]`) as HTMLElement;
    const did = cell.getAttribute("data-testid")!.split("-")[3];
    fireEvent.click(cell);
    await waitFor(() => expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(e2));
    expect((screen.getByLabelText("3D 비교 안") as HTMLSelectElement).value).toBe(did);
    // 순위표 최악 ESL 칸 = 그 안 + 그 씬
    const worst = document.querySelector('[data-testid^="rank-worst-"]') as HTMLElement;
    const wd = worst.getAttribute("data-testid")!.replace("rank-worst-", "");
    fireEvent.click(worst);
    await waitFor(() => expect((screen.getByLabelText("3D 비교 안") as HTMLSelectElement).value).toBe(wd));
    expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).not.toBe("");
  }, 40000);

  it("C 기여도·차이 버튼: 씬 자료가 있으면 활성, 누르면 두 카드 범례 문구", async () => {
    open("doe-60");
    const seg = await screen.findByTestId("v3d-color");
    const cBtn = seg.querySelector("[data-color=c]") as HTMLButtonElement;
    const dBtn = seg.querySelector("[data-color=dc]") as HTMLButtonElement;
    await waitFor(() => expect(cBtn.disabled).toBe(false), { timeout: 8000 });
    expect(dBtn.disabled).toBe(false);
    fireEvent.click(cBtn);
    await waitFor(() => expect(screen.getAllByTestId("v3d-legend")[0].textContent).toContain("C 기여도"), { timeout: 8000 });
    fireEvent.click(dBtn);
    await waitFor(() => expect(screen.getAllByTestId("v3d-legend").map((x) => x.textContent).join("|")).toContain("차이"), { timeout: 8000 });
  }, 30000);

  it("출처 탭마다 같은 규칙: 직접 고른 씬은 탭을 바꿔도 유지, 요청 URL 의 출처 키 = 그 탭", async () => {
    open("doe-60");
    const s = await sel();
    const e2 = s.options[2].value;
    fireEvent.change(s, { target: { value: e2 } });
    const tabs = screen.getByTestId("doe-load-tab");
    let seen = 0;
    for (const k of ["full", "jig", "jig_disp", "jig_spring", "bforce", "fint"]) {
      const b = tabs.querySelector(`[data-tab=${k}]`) as HTMLButtonElement | null;
      if (!b || b.disabled || b.getAttribute("aria-disabled") === "true") continue;
      fireEvent.click(b);
      await waitFor(() => expect(lastCalls(2).every((x) => x.startsWith(`${k}/`) && x.endsWith(`/${e2}`))).toBe(true), { timeout: 8000 });
      expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(e2);
      seen += 1;
    }
    expect(seen).toBeGreaterThanOrEqual(2);
  }, 60000);

  it("한도로 빠진 씬 선택 = 안내 + [씬 3D 만들기] 1개", async () => {
    open("doe-60");
    const s = await sel();
    fireEvent.change(s, { target: { value: s.options[s.options.length - 1].value } });
    const m = await screen.findByTestId("v3d-scene-missing");
    expect(m.textContent).toContain("저장 한도");
    expect(screen.getAllByTestId("v3d-scene-add").length).toBe(1);
    fireEvent.click(screen.getByTestId("v3d-scene-add"));
    await waitFor(() => expect(doeMock!.sceneAddCalls).toBe(1));
  }, 30000);

  it("옛 결과(scene_view null): 선택 칸 없음·씬 요청 0·안내 한 줄 + [씬 3D 만들기]", async () => {
    open("doe-61");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    await screen.findByTestId("v3d-scene-oldnote");
    expect(screen.queryByTestId("v3d-scene-select")).toBeNull();
    expect(screen.queryByTestId("v3d-scene-summary")).toBeNull();
    expect(document.querySelector('[data-testid^="rank-worst-"]')).toBeNull();
    expect(document.querySelector('[data-testid^="per-esl-col-"]')).toBeNull();
    const cBtn = (screen.getByTestId("v3d-color").querySelector("[data-color=c]") as HTMLButtonElement);
    expect(cBtn.disabled).toBe(true);
    expect(cBtn.title).toBe(NO_C_TEXT);
    expect(calls().length).toBe(0);
    expect(screen.getAllByTestId("v3d-scene-add").length).toBe(1);
  }, 30000);
});
