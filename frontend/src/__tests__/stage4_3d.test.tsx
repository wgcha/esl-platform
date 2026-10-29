// V-L3-11: ④ 화면(scene mock) — 카드 순서, 표 행 수 = 화살표 수, 군집 단계 표, 표 ↔ 3D 선택 양방향, 변형 형상 컨트롤, WebGL 없음·413 폴백, ?run= 읽기 전용.
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ArrowSpec } from "../view3d/arrows";
import { PROJ_KEY, readProjection, writeProjection } from "../view3d/projection";
import type { PickEvent, SceneApi, SceneOptions } from "../view3d/sceneApi";

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

type FakeScene = SceneApi & { calls: Record<string, unknown[][]>; emit: (e: PickEvent) => void; opts: SceneOptions };
const scene = () => h.scenes[h.scenes.length - 1] as FakeScene;
const last = (name: string) => {
  const c = scene().calls[name] ?? [];
  return c[c.length - 1];
};
const url = (c: string, n: number) => `/p/p-body/c/${c}/stage/${n}`;
const rowsOf = () => within(screen.getByTestId("load-table")).getAllByRole("row").slice(1);
const ready = async () => {
  await waitFor(() => expect(screen.getByTestId("v3d-host").getAttribute("data-phase")).toBe("ready"));
  await waitFor(() => expect(last("setArrows")).toBeTruthy());
};
const setStage = (i: number) => fireEvent.change(screen.getByLabelText("화살표 단계"), { target: { value: String(i) } });

beforeEach(() => {
  h.webgl = true;
  h.loadFails = false;
  h.scenes.length = 0;
  localStorage.removeItem(PROJ_KEY);
});

describe("V-L3-11 ④ 3D 하중 보기", () => {
  it("카드 순서: 결과 → 3D 하중 보기 → F_eq 상위 노드, 표 행 수 = 화살표 수(기본 100)", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const titles = screen.getAllByRole("heading", { level: 3 }).map((x) => x.textContent);
    const i = (t: string) => titles.indexOf(t);
    expect(i("입력 요약")).toBeGreaterThanOrEqual(0);
    expect(i("입력 요약")).toBeLessThan(i("결과"));
    expect(i("결과")).toBeLessThan(i("3D 하중 보기"));
    expect(i("3D 하중 보기")).toBeLessThan(i("F_eq 상위 노드"));
    expect(rowsOf().length).toBe(100);
    expect((last("setArrows")[0] as ArrowSpec[]).length).toBe(100);
    expect(screen.getByTestId("v3d-stage").textContent).toBe("100 노드");
    expect((last("setSupports")[0] as unknown[]).length).toBe(3);
    expect(last("setColors")).toBeTruthy();
    // 표면 색 레전드 = 면압 |Fn|/A (MPa), 범위 [0, P99]
    const lg = screen.getByTestId("v3d-legend");
    expect(lg.textContent).toContain("면압 |Fn|/A (MPa)");
    expect(lg.getAttribute("data-range-min")).toBe("0");
    expect(Number(lg.getAttribute("data-range-max"))).toBeGreaterThan(0);
    expect(screen.getByTestId("v3d-note").textContent).toMatch(/화살표 최대 = .* N · 길이 ∝ \|F\| \(최소 길이 제한\)/);
  });

  it("단계 슬라이더: 50/20/10 → 행·화살표 수, 군집 5 → '군집 합력' 표·ΣF 줄·자기평형 문구", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    for (const [stage, n] of [[1, 50], [2, 20], [3, 10]] as const) {
      setStage(stage);
      await waitFor(() => expect(rowsOf().length).toBe(n));
      expect((last("setArrows")[0] as ArrowSpec[]).length).toBe(n);
    }
    setStage(4);
    await screen.findByRole("heading", { level: 3, name: "군집 합력" });
    expect(screen.getByTestId("load-table").getAttribute("data-mode")).toBe("cluster");
    expect(rowsOf().length).toBe(5);
    const heads = within(screen.getByTestId("load-table")).getAllByRole("columnheader").map((x) => x.textContent);
    expect(heads).toEqual(["군집", "노드 수", "중심 x", "중심 y", "중심 z", "Rx", "Ry", "Rz", "|R|", "Σ|F|", "상쇄율", "|M_c|"]);
    expect(screen.getByTestId("load-sum-line").textContent).toMatch(/ΣF = .* · ΣM = .* \(자기평형, 군집 합력의 합 = ΣF\)/);
    const arrows = last("setArrows")[0] as ArrowSpec[];
    expect(arrows.length).toBe(5);
    expect(arrows[0].label).toMatch(/^C1 /);
    expect(screen.getByTestId("v3d-note").textContent).toContain("군집 모드: ΣF ≈ 0 (자기평형)");
    setStage(7);
    await waitFor(() => expect(rowsOf().length).toBe(2));
    setStage(0);
    await waitFor(() => expect(rowsOf().length).toBe(100));
  });

  it("표 행 클릭 → scene.select(화살표, 정점), 더블클릭 → focus, 3D 선택 콜백 → 행 aria-selected", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const rows = rowsOf();
    fireEvent.click(rows[2]);
    await waitFor(() => expect(rows[2].getAttribute("aria-selected")).toBe("true"));
    const sel = last("select");
    expect(sel[0]).toBe(2);
    expect(typeof sel[1]).toBe("number");
    expect(screen.getByTestId("v3d-info").textContent).toMatch(/^노드 \d+ · 면압 [\d.]+ MPa · \|Fn\| /);
    fireEvent.doubleClick(rows[4]);
    await waitFor(() => expect(last("focus")).toBeTruthy());
    expect((last("focus")[0] as number[]).length).toBe(3);
    // 3D 에서 화살표 7 번째 선택 → 그 행이 선택됨
    act(() => scene().emit({ type: "arrow", index: 6 }));
    await waitFor(() => expect(rowsOf()[6].getAttribute("aria-selected")).toBe("true"));
    expect(rowsOf().filter((r) => r.getAttribute("aria-selected") === "true").length).toBe(1);
    act(() => scene().emit({ type: "none" }));
    await waitFor(() => expect(rowsOf().filter((r) => r.getAttribute("aria-selected") === "true").length).toBe(0));
    // 단계를 줄여 사라진 화살표 선택은 해제
    act(() => scene().emit({ type: "arrow", index: 60 }));
    await waitFor(() => expect(rowsOf()[60].getAttribute("aria-selected")).toBe("true"));
    setStage(3);
    await waitFor(() => expect(rowsOf().length).toBe(10));
    expect(rowsOf().filter((r) => r.getAttribute("aria-selected") === "true").length).toBe(0);
    expect(last("select")[0]).toBeNull();
  });

  it("지지점 기호 클릭 → 정보 줄 '지지 {node} · dof ...'", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    act(() => scene().emit({ type: "support", index: 1 }));
    await waitFor(() => expect(screen.getByTestId("v3d-info").textContent).toMatch(/^지지 \d+ · dof 13 \(x·z\)$/));
  });

  it("배율 컨트롤은 '변형 형상'을 켤 때만 활성, 실제 크기 토글 k = 1, 표기 문자열", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const scale = screen.getByLabelText("변형 확대 배율") as HTMLInputElement;
    const real = screen.getByRole("button", { name: "실제 크기(×1)" }) as HTMLButtonElement;
    const toggle = screen.getByRole("button", { name: "변형 형상" });
    expect(scale.disabled).toBe(true);
    expect(real.disabled).toBe(true);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(last("setDeform")[0]).toBeNull();
    fireEvent.click(toggle);
    await waitFor(() => expect(scale.disabled).toBe(false));
    expect(real.disabled).toBe(false);
    expect(screen.getByTestId("v3d-scale-label").textContent).toMatch(/^변형 확대 배율 ×[\d.e+]+ \(실제 최대 [\d.e+-]+ mm\)$/);
    expect(last("setDeform")[0]).toBeInstanceOf(Float32Array);
    const k0 = last("setDeform")[1] as number;
    expect(k0).toBeGreaterThan(1);
    fireEvent.change(scale, { target: { value: "0" } });
    await waitFor(() => expect(last("setDeform")[1]).toBe(1));
    fireEvent.change(scale, { target: { value: "2" } });
    await waitFor(() => expect(last("setDeform")[1]).toBeCloseTo(100, 6));
    fireEvent.click(real);
    await waitFor(() => expect(last("setDeform")[1]).toBe(1));
    expect(screen.getByTestId("v3d-scale-label").textContent).toContain("×1 ");
    expect(scale.disabled).toBe(true);
    // 변형 형상이면 화살표 꼬리도 이동(배율 1 일 때 u ≠ 0 인 노드)
    fireEvent.click(real);
    fireEvent.click(toggle);
    await waitFor(() => expect(last("setDeform")[0]).toBeNull());
    expect(scale.disabled).toBe(true);
  });

  it("맞춤 버튼 → scene.fit()", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "맞춤" }));
    expect(last("fit")).toBeTruthy();
  });

  it("언마운트 시 scene.dispose()", async () => {
    const { unmount } = renderApp(url("c-demo", 4));
    await ready();
    unmount();
    expect(last("dispose")).toBeTruthy();
  });
});

describe("V-L3-11 대체 경로", () => {
  it("WebGL 없음 → 안내 문구 + 표 유지(scene 생성 안 함)", async () => {
    h.webgl = false;
    renderApp(url("c-demo", 4));
    const msg = await screen.findByTestId("v3d-unavailable");
    expect(msg.textContent).toBe("이 브라우저에서 3D 보기를 쓸 수 없습니다");
    await waitFor(() => expect(rowsOf().length).toBe(100));
    expect(h.scenes.length).toBe(0);
  });

  it("three 청크 적재 실패 → 같은 안내 + 표 유지", async () => {
    h.loadFails = true;
    renderApp(url("c-demo", 4));
    const msg = await screen.findByTestId("v3d-unavailable");
    expect(msg.textContent).toBe("이 브라우저에서 3D 보기를 쓸 수 없습니다");
    await waitFor(() => expect(rowsOf().length).toBe(100));
  });

  it("manifest 413 → 사유 한 줄 + /forces?top=100 폴백 표", async () => {
    renderApp(url("c-demo", 4), "power", (srv) => (srv.view3dMode = "too_large"));
    await waitFor(() => expect(screen.queryByTestId("v3d-error")).toBeTruthy(), { timeout: 4000 });
    expect(screen.getByTestId("v3d-error").textContent).toMatch(/너무 커서 3D 보기를 만들 수 없습니다/);
    await waitFor(() => expect(rowsOf().length).toBe(50)); // 목 /forces 는 최대 50행
    expect(h.scenes.length).toBeLessThanOrEqual(1);
  });

  it("?run= 읽기 전용(과거 실행)도 같은 배치: 3D → 표", async () => {
    const { container } = renderApp("/p/p-body/jobs/h-esl-old");
    await waitFor(() => expect(container.querySelectorAll("button.primary, .btn.primary").length).toBeGreaterThan(0));
    fireEvent.click(container.querySelector("button.primary, .btn.primary") as HTMLElement);
    expect(await screen.findByTestId("past-badge")).toBeTruthy();
    const titles = await waitFor(() => {
      const t = screen.getAllByRole("heading", { level: 3 }).map((x) => x.textContent);
      expect(t).toContain("F_eq 상위 노드");
      return t;
    });
    expect(titles.indexOf("3D 하중 보기")).toBeGreaterThanOrEqual(0);
    expect(titles.indexOf("3D 하중 보기")).toBeLessThan(titles.indexOf("F_eq 상위 노드"));
  });
});

describe("v0.7.1 투영 토글(원근/직교)", () => {
  const box = () => screen.getByTestId("v3d-persp") as HTMLInputElement;

  it("기본값 = 직교: 체크 해제, createScene({projection: 'ortho'})", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    expect(box().checked).toBe(false);
    expect(scene().opts.projection).toBe("ortho");
    expect(scene().projection()).toBe("ortho");
    expect(screen.getByText("원근")).toBeTruthy();
  });

  it("체크 → setProjection('persp') + 저장, 해제 → 'ortho' + 저장", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    fireEvent.click(box());
    await waitFor(() => expect(last("setProjection")).toEqual(["persp"]));
    expect(box().checked).toBe(true);
    expect(localStorage.getItem(PROJ_KEY)).toBe("persp");
    fireEvent.click(box());
    await waitFor(() => expect(last("setProjection")).toEqual(["ortho"]));
    expect(localStorage.getItem(PROJ_KEY)).toBe("ortho");
  });

  it("다시 열면 저장한 투영으로 복원", async () => {
    localStorage.setItem(PROJ_KEY, "persp");
    renderApp(url("c-demo", 4));
    await ready();
    expect(box().checked).toBe(true);
    expect(scene().opts.projection).toBe("persp");
  });

  it("저장소 오류·잘못된 값 → 기본값 직교로 동작", async () => {
    localStorage.setItem(PROJ_KEY, "fisheye");
    renderApp(url("c-demo", 4));
    await ready();
    expect(box().checked).toBe(false);
    cleanup();
    h.scenes.length = 0;
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const spySet = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    try {
      expect(readProjection()).toBe("ortho");
      expect(() => writeProjection("persp")).not.toThrow();
    } finally {
      spy.mockRestore();
      spySet.mockRestore();
    }
  });
});
