// V-0248-JG-13·14·17 (esl_jig_grid_map.md §1.4·§3·§5·§9): ④ 격자 지그 화면 — 탭 사유 2종·격자 꼬리·순위 정의·noise 배지·코드 문구·정보 등급·픽스처.
// 응답 새 필드(jig.transfer·jig.grid·jig_plan grid)는 백엔드 B1 이 병행 구현 — 시험은 목 응답(withJigGrid)으로 한다.
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { GRID_TEXT, JIG_CODE_TEXT, JIG_GRID_INFO_CODES, gridOf, isInfoWarn, warnText } from "../api/doe";
import { JIG_STATE_TEXT, jigMethodState, tabState } from "../pages/doe/doeTabs";
import { setHiddenSources } from "../view3d/sources";
import type { DoeResultOut } from "../api/types";

afterEach(() => {
  cleanup();
  setHiddenSources([]);
});

const base = (over: Partial<DoeResultOut> = {}) =>
  ({ ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1, metric_effective: "jig", ...over }) as unknown as DoeResultOut;

describe("V-0248-JG-14 jig_plan none 탭 사유 2종", () => {
  it("jig_on_clone 참 = 복제하면 격자 매핑 계산 / 거짓 = rank.jig_grid 꺼짐 / null = 옛 서버 문구 그대로", () => {
    const yes = jigMethodState(base({ jig_plan: "none", jig_on_clone: true }), "jig_disp");
    expect(yes.state).toBe("not_planned");
    expect(yes.why).toBe("이 스터디는 이 모드에서 지그 ESL 을 계산하지 않았습니다(v0.24.8 이전 스냅샷): 지그 변위 — 복제하면 Case 지그를 격자 매핑해 계산합니다");
    const no = jigMethodState(base({ jig_plan: "none", jig_on_clone: false }), "jig_spring");
    expect(no.why).toBe("이 스터디는 이 모드에서 지그 ESL 을 계산하지 않았습니다(v0.24.8 이전 스냅샷): 지그 스프링 — 설정 bead_doe.rank.jig_grid 가 꺼져 있어 복제해도 계산하지 않습니다");
    expect(no.title).toBe(no.why);
    const old = jigMethodState(base({ jig_plan: "none" }), "jig_disp");
    expect(old.why).toBe(JIG_STATE_TEXT.not_planned.whyMode("지그 변위"));
    expect(old.why).toContain("복제해도 같습니다");
  });

  it("jig_plan grid = 지금 방식 상태 판정 그대로(none 사유를 내지 않음)", () => {
    const ok = base({ jig_plan: "grid", jig: { status: "ok", methods: { jig_disp: { status: "ok", warnings: [] } } } as never, rank_views: { jig_disp: {} } as never });
    expect(jigMethodState(ok, "jig_disp").state).toBe("ok");
    expect(jigMethodState(ok, "jig_spring").state).toBe("not_planned");
    expect(jigMethodState(ok, "jig_spring").why).toContain("복제(현재 설정 rank.jig.methods)로 다시 계산");
    const failed = base({ jig_plan: "grid", jig: { status: "ok", methods: { jig_disp: { status: "fallback", code: "JIG_GRID_SOURCE_MISSING", detail: "Case 에 지그 없음" } } } as never });
    expect(jigMethodState(failed, "jig_disp").state).toBe("failed");
    expect(jigMethodState(failed, "jig_disp").why).toBe("지그 변위 계산 실패: JIG_GRID_SOURCE_MISSING — Case 에 지그 없음");
    const tabs = tabState({ ...ok, rank_views: { jig_disp: {}, jig_spring: {} } } as never);
    expect(tabs.ok.jig_disp).toBe(true);
    expect(tabs.ok.jig_spring).toBe(true);
  });
});

describe("§1.4 코드 문구·정보 등급·gridOf", () => {
  it("API text(message) 가 먼저, 없으면 화면 대체 문구(표 한 곳) — {필드} 는 경고 값으로", () => {
    expect(warnText({ code: "JIG_GRID_TIE_MISS", message: "서버 문구" })).toBe("서버 문구");
    expect(warnText({ code: "JIG_GRID_TIE_MISS" })).toBe(JIG_CODE_TEXT.JIG_GRID_TIE_MISS);
    expect(warnText({ code: "JIG_GRID_SOURCE_MISSING", entry: "Ch/R 낙하 A", method: "변위" })).toContain("엔트리 Ch/R 낙하 A 의 Case 에 변위 지그 결과가 없습니다");
    expect(warnText({ code: "JIG_GRID_SOURCE_MISSING" })).toContain("스터디를 복제하세요");
    for (const c of ["SOURCE_MISSING", "TIE_MISS", "OUTSIDE", "LOAD_RESID", "AREA_RATIO", "FRAME_SHIFT", "CONV", "NO_REF", "RANK"]) expect(JIG_CODE_TEXT[`JIG_GRID_${c}`]).toBeTruthy();
  });

  it("정보 등급 5개(OUTSIDE·AREA_RATIO·FRAME_SHIFT·CONV·RANK)만 level 없이도 ⓘ, 경고 등급은 ⚠", () => {
    expect([...JIG_GRID_INFO_CODES].sort()).toEqual(["JIG_GRID_AREA_RATIO", "JIG_GRID_CONV", "JIG_GRID_FRAME_SHIFT", "JIG_GRID_ON_CLONE", "JIG_GRID_OUTSIDE", "JIG_GRID_RANK"]);
    for (const c of JIG_GRID_INFO_CODES) expect(isInfoWarn({ code: c })).toBe(true);
    for (const c of ["JIG_GRID_SOURCE_MISSING", "JIG_GRID_TIE_MISS", "JIG_GRID_LOAD_RESID", "JIG_GRID_NO_REF"]) expect(isInfoWarn({ code: c })).toBe(false);
    expect(isInfoWarn({ code: "JIG_GRID_TIE_MISS", level: "info" })).toBe(true);
  });

  it("gridOf = jig.transfer grid ∧ jig.grid 있을 때만, 꼬리 문구", () => {
    expect(gridOf(null)).toBeNull();
    expect(gridOf({ jig: { transfer: "base", grid: null } })).toBeNull();
    expect(gridOf({ jig: { transfer: "grid", grid: { cell_mm: 3, noise_floor: 0.03 } } })).toEqual({ cell_mm: 3, noise_floor: 0.03 });
    expect(GRID_TEXT.support(3)).toBe(" · 격자 3 mm");
    expect(GRID_TEXT.rankDef(3)).toBe("형상마다 Case 지그를 3 mm 격자로 매핑(기준 d000)");
    expect(GRID_TEXT.rankNoise(0.03)).toBe(" · 차이 3 % 이내는 매핑 오차 범위");
  });
});

// ---- 화면(목 서버) ----
const tabBtn = (k: string) => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const open = (id: string, mod?: (r: DoeResultOut) => DoeResultOut) =>
  renderApp(`/p/p-body/doe/${id}`, "power", (s) => {
    s.doe.demoJigGrid();
    s.p3.hiddenSources = ["jig"];
    if (mod) {
      const rec = s.doe.recs.find((r) => r.out.id === id)!;
      rec.result = mod(rec.result!);
    }
  });

describe("V-0248-JG-13·17 ④ 격자 지그 결과 화면(픽스처 doe-60)", () => {
  it("지그 변위·스프링 탭 활성 + jd 3D 조건 줄 꼬리 + 순위 정의·noise 배지 + 민감도 COMPARE_NO_PARAMS 사유", async () => {
    open("doe-60");
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    await waitFor(() => expect(tabBtn("jig_disp").getAttribute("aria-disabled")).not.toBe("true"));
    expect(tabBtn("jig_spring").getAttribute("aria-disabled")).not.toBe("true");
    expect(tabBtn("jig_disp").title).not.toContain("계산하지 않");
    fireEvent.click(tabBtn("jig_disp"));
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toContain("지지: 지그 tie 법선 강제 변위 + 3-2-1 면내 · 격자 3 mm"));
    expect(screen.queryByTestId("v3d-regen-jd")).toBeNull();
    // 순위 정의 문구(같은 줄) + noise 배지 title
    const defs = screen.getByTestId("metric-defs").textContent ?? "";
    expect(defs).toContain("형상마다 Case 지그를 3 mm 격자로 매핑(기준 d000) · 차이 3 % 이내는 매핑 오차 범위");
    const badges = screen.getAllByText("잡음 이내");
    expect(badges.length).toBeGreaterThan(0);
    expect(badges[0].getAttribute("title")).toMatch(/^격자 매핑 오차 범위 .*3.* 이내$/);
    expect(badges[0].getAttribute("title")).not.toContain("③ 메시 잡음 바닥");
    // 민감도는 기존처럼 비어 있음(COMPARE_NO_PARAMS)
    expect(screen.getByTestId("doe-row-sens").textContent).toContain("민감도:");
    fireEvent.click(tabBtn("jig_spring"));
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toContain("지그 tie 법선 스프링 + 3-2-1 면내 · 격자 3 mm"));
  }, 40000);

  it("대조(transfer·grid 없음)는 꼬리·정의 꼬리가 없고 noise 배지 title 은 옛 문구", async () => {
    open("doe-61");
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    await waitFor(() => expect(tabBtn("jig_disp").getAttribute("aria-disabled")).not.toBe("true"));
    fireEvent.click(tabBtn("jig_disp"));
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toContain("지그 tie 법선 강제 변위 + 3-2-1 면내"));
    expect(screen.getByTestId("v3d-cond").textContent).not.toContain("격자");
    expect(screen.getByTestId("metric-defs").textContent).not.toContain("매핑");
    expect(screen.getAllByText("잡음 이내")[0].getAttribute("title")).toContain("③ 메시 잡음 바닥");
  }, 40000);

  it("옛 스냅샷 ④(jig_plan none)는 지금처럼 하중 정의 탭 없음 — 탭 사유 문구는 ③ 등 탭이 있는 화면에서 jig_on_clone 으로 갈림(단위 시험)", async () => {
    open("doe-62");
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    expect(screen.queryByTestId("doe-load-tab")).toBeNull();
    expect(screen.getByTestId("metric-defs").textContent).not.toContain("매핑");
    // v0.24.8 fix(JG-21): 실제 형태(코어 jig unsupported 블록 + 서버 JIG_GRID_ON_CLONE 1건) — 안내 줄이 결과 경고 목록에 보인다
    const fold = await screen.findByTestId("result-warn");
    const btn = fold.querySelector("button.msg-fold-line") as HTMLButtonElement;
    if (btn.getAttribute("aria-expanded") !== "true") fireEvent.click(btn);
    await waitFor(() => expect(fold.textContent).toContain("이 스터디는 지그 ESL 없이 계산됐습니다 — 복제하면 Case 지그를 격자 매핑해 계산합니다"));
    expect((fold.textContent ?? "").split("격자 매핑해 계산합니다").length - 1).toBe(1);
  }, 40000);

  it("옛 스냅샷 ④ 설정 꺼짐(doe-63) = 안내 줄 없음", async () => {
    open("doe-63");
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    const fold = await screen.findByTestId("result-warn");
    const btn = fold.querySelector("button.msg-fold-line") as HTMLButtonElement;
    if (btn.getAttribute("aria-expanded") !== "true") fireEvent.click(btn);
    await waitFor(() => expect(fold.querySelector("ul")).not.toBeNull());
    expect(fold.textContent).not.toContain("격자 매핑해 계산합니다");
  }, 40000);
});

describe("V-0248-JG-21 옛 ④·옛 ③ 실제 결과 형태(코어 jig{status: unsupported} 블록 있음)", () => {
  const unsup = { status: "unsupported", code: "JIG_UNSUPPORTED", methods: { jig_disp: { status: "fallback", code: "JIG_SKIPPED", warnings: [] } } } as never;
  it("블록이 있어도 탭 사유는 jig_on_clone 으로 — 옛 문구(복제해도 같습니다)가 나오지 않음", () => {
    const yes = jigMethodState(base({ jig_plan: "none", jig: unsup, jig_on_clone: true }), "jig_disp");
    expect(yes.state).toBe("not_planned");
    expect(yes.why).toContain("복제하면 Case 지그를 격자 매핑해 계산합니다");
    expect(yes.why).not.toContain("복제해도 같습니다");
    const no = jigMethodState(base({ jig_plan: "none", jig: unsup, jig_on_clone: false }), "jig_spring");
    expect(no.why).toContain("설정 bead_doe.rank.jig_grid 가 꺼져 있어 복제해도 계산하지 않습니다");
  });
});
