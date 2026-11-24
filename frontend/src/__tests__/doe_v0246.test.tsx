// V-0246-VW-14~16 (esl_viewer_hv.md §7·§8.3·§9.1): 스터디 결과 3행 · 지그 방식 4상태 사유 · 지그 변위·스프링 3D 열.
// 응답 새 필드(jig.methods·tie_dofs·view3d_jd*·js*)는 백엔드 B1 이 병행 구현 — 시험은 목 응답으로 한다.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { JIG_STATE_TEXT, LOAD_SOURCES, jigMethodNote, jigMethodState, supportText, tabState, visibleLoadSources } from "../pages/doe/doeTabs";
import { v3dPairCondText } from "../pages/doe/DoeStudy";
import { setHiddenSources } from "../view3d/sources";
import type { DoeJigMethodOut, DoeResultOut } from "../api/types";

afterEach(() => {
  cleanup();
  setHiddenSources([]);
});

const method = (over: Partial<DoeJigMethodOut> = {}): DoeJigMethodOut => ({
  method: "prescribed", method_name: "강제 변위", tie_dofs: "normal", status: "ok", code: null, detail: null,
  fit_mac_min: null, fit_umax_err_max: null, warnings: [], limits: [], n_jig: 40, bc: null, spring: null, ...over,
});
const base = (over: Partial<DoeResultOut> = {}) =>
  ({ ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1, metric_effective: "jig", ...over }) as unknown as DoeResultOut;
const jigOf = (methods: Record<string, DoeJigMethodOut> | null, tie: "normal" | "translation" | null = "normal") => ({ status: "ok", tie_dofs: tie, methods }) as unknown as DoeResultOut["jig"];

describe("V-0246-VW-15 jigMethodState 4상태", () => {
  it("no_jig: r.jig 없음 — jig_on_clone 참이면 복제 안내가 붙음", () => {
    const a = jigMethodState(base({ jig: null, jig_on_clone: false }), "jig_disp");
    expect(a.state).toBe("no_jig");
    expect(a.why).toBe(JIG_STATE_TEXT.no_jig.why);
    expect(a.why).toBe("이 스터디는 지그를 계산하지 않았습니다");
    expect(a.note).toBeNull();
    const b = jigMethodState(base({ jig: null, jig_on_clone: true }), "jig_disp");
    expect(b.why).toBe("이 스터디는 지그를 계산하지 않았습니다 — 복제하면 지그를 계산합니다");
    expect(b.note).toBeNull();
  });

  it("not_planned: 옛 단일 경로(methods 없음)·키 없음 = 복제 안내, 줄 없음 / 모드가 지그 ESL 을 계산 안 함(jig_plan none) = 복제해도 같음(문구 통합)", () => {
    const old = jigMethodState(base({ jig: jigOf(null) }), "jig_spring");
    expect(old.state).toBe("not_planned");
    expect(old.why).toBe("이 스터디에서 계산하지 않은 방식입니다: 지그 스프링 — 복제(현재 설정 rank.jig.methods)로 다시 계산");
    expect(old.note).toBeNull();
    const miss = jigMethodState(base({ jig: jigOf({ jig_disp: method() }) }), "jig_spring");
    expect(miss.state).toBe("not_planned");
    expect(miss.why).toBe(old.why);
    const mode = jigMethodState(base({ jig: jigOf(null), jig_plan: "none" }), "jig_disp");
    expect(mode.state).toBe("not_planned");
    expect(mode.why).toBe(JIG_STATE_TEXT.not_planned.whyMode("지그 변위"));
    expect(mode.why).toContain("복제해도 같습니다");
    expect(jigMethodState(base({ jig: null, jig_plan: "none" }), "jig_disp").why).toBe(mode.why); // 계획 열이 먼저
  });

  it("failed: 코드·detail 120자 + 마우스 없이 보이는 줄(title = 전체 detail, 3D 다시 만들기로 못 고침 안내)", () => {
    const detail = "x".repeat(200);
    const r = base({ jig: jigOf({ jig_disp: method({ status: "fallback", code: "JIG_NO_TIE", detail }) }) });
    const s = jigMethodState(r, "jig_disp");
    expect(s.state).toBe("failed");
    expect(s.why).toBe(`지그 변위 계산 실패: JIG_NO_TIE — ${"x".repeat(120)}…`);
    expect(s.title).toBe(`지그 변위 계산 실패: JIG_NO_TIE — ${detail}`);
    expect(s.note).toBe(s.why + JIG_STATE_TEXT.failed.next);
    expect(s.note).toContain("원인을 고친 뒤 복제로 다시 계산");
    const short = jigMethodState(base({ jig: jigOf({ jig_disp: method({ status: "fallback", code: "JIG_SKIPPED", detail: "짧음" }) }) }), "jig_disp");
    expect(short.why).toBe("지그 변위 계산 실패: JIG_SKIPPED — 짧음");
    expect(short.title).toBe(short.why);
    const note = jigMethodNote(r, LOAD_SOURCES.find((x) => x.key === "jig_disp")!)!;
    expect(note.state).toBe("failed");
    expect(note.title).toBe(s.title);
  });

  it("no_view: 계산 ok ∧ rank_views 없음 = 첫 warnings 항목, 보이는 줄 / 보기가 있으면 ok(사유 없음)", () => {
    const r = base({ jig: jigOf({ jig_spring: method({ warnings: ["JIG_X: 기준 C 없음", "둘째"] }) }) });
    const s = jigMethodState(r, "jig_spring");
    expect(s.state).toBe("no_view");
    expect(s.why).toBe("지그 스프링: 계산됐지만 기준(d000) 값 C_js 가 없어 순위를 만들지 못했습니다 — JIG_X: 기준 C 없음");
    expect(s.note).toBe(s.why);
    const none = jigMethodState(base({ jig: jigOf({ jig_spring: method() }) }), "jig_spring");
    expect(none.why).toBe("지그 스프링: 계산됐지만 기준(d000) 값 C_js 가 없어 순위를 만들지 못했습니다");
    const ok = jigMethodState({ ...r, rank_views: { jig_spring: {} } } as unknown as DoeResultOut, "jig_spring");
    expect(ok.state).toBe("ok");
    expect(ok.note).toBeNull();
  });

  it("통합: no_view(예: view3d.jig_diag 끔 — rank_views 없음) 는 빈 탭 [다시 만들기] 를 두지 않음, 보기가 있으면 3D 만 없는 상태라 그대로", () => {
    const sa = { jig_disp: { available: true, allowed: true, reason: null }, jig_spring: { available: true, allowed: true, reason: null } };
    const r = base({ jig: jigOf({ jig_disp: method(), jig_spring: method() }), source_add: sa } as never);
    const ts = tabState(r, LOAD_SOURCES);
    expect(ts.ok.jig_disp).toBe(false);
    expect(ts.add.jig_disp).toBe(false);
    expect(ts.add.jig_spring).toBe(false);
    const withView = tabState({ ...r, rank_views: { jig_disp: {} } } as unknown as DoeResultOut, LOAD_SOURCES);
    expect(withView.ok.jig_disp).toBe(true);
    expect(withView.add.jig_disp).toBe(false); // 보기 있음 = 탭 가능(3D 칸 안내가 버튼을 가짐)
  });

  it("탭 사유(tabState.reason)는 상태 문구 그대로, 줄은 failed·no_view 만(jigMethod 열), 숨긴 출처는 줄도 없음", () => {
    const r = base({
      jig: jigOf({ jig_disp: method({ status: "fallback", code: "JIG_NO_TIE", detail: "d" }), jig_spring: method() }),
      rank_views: { jig: {} } as never,
    });
    const ts = tabState(r, LOAD_SOURCES);
    expect(ts.reason.jig_disp).toBe("지그 변위 계산 실패: JIG_NO_TIE — d");
    expect(ts.reason.jig_spring).toContain("계산됐지만 기준(d000)");
    expect(LOAD_SOURCES.filter((x) => jigMethodNote(r, x)).map((x) => x.key)).toEqual(["jig_disp", "jig_spring"]);
    expect(LOAD_SOURCES.filter((x) => x.jigMethod).map((x) => x.key)).toEqual(["jig_disp", "jig_spring"]);
    setHiddenSources(["jig_disp", "jig"]);
    expect(visibleLoadSources().filter((x) => jigMethodNote(r, x)).map((x) => x.key)).toEqual(["jig_spring"]);
  });
});

describe("V-0246-VW-16 jd·js 열 (pairKeys·support·disp·add)", () => {
  const row = (k: string) => LOAD_SOURCES.find((x) => x.key === k)!;
  it("pairKeys 가 view3d_jd*·js* 를 가리키고 load·support·disp 열이 채워짐", () => {
    expect(row("jig_disp").view3d).toBe("pair");
    expect(row("jig_disp").pairKeys).toEqual({ dir: "view3d_jd", esl: "view3d_jd_esl", ref: "view3d_jd_ref", load: "지그 변위", support: "지그 tie {tie} 강제 변위 + 3-2-1 면내", disp: expect.stringContaining("지그 강제 변위") });
    expect(row("jig_spring").pairKeys).toMatchObject({ dir: "view3d_js", esl: "view3d_js_esl", ref: "view3d_js_ref", load: "지그 스프링", support: "지그 tie {tie} 스프링 + 3-2-1 면내" });
    for (const s of LOAD_SOURCES.filter((x) => x.pairKeys)) {
      expect(s.pairKeys!.support, s.key).toBeTruthy();
      expect(s.pairKeys!.disp, s.key).toBeTruthy();
    }
  });
  it("경계력·내력 조건 줄·변위 라벨 글자 불변(열로 옮김)", () => {
    expect(row("bforce").pairKeys!.support).toBe("3-2-1");
    expect(row("fint").pairKeys!.disp).toBe("변위 |u| (mm) — 3-2-1(자기평형 하중)");
    expect(v3dPairCondText("경계력 ESL", "full", [null, null])).toBe("하중: 경계력 ESL(등급 full) · 지지: 3-2-1 · 엔트리: –");
    expect(row("jig").pairKeys!.disp).toBe("변위 |u| (mm) — 지그 고정(강체 성분 없음)");
  });
  it("{tie} = jig.tie_dofs → 법선|병진", () => {
    const tpl = row("jig_disp").pairKeys!.support;
    expect(supportText(tpl, "normal")).toBe("지그 tie 법선 강제 변위 + 3-2-1 면내");
    expect(supportText(row("jig_spring").pairKeys!.support, "translation")).toBe("지그 tie 병진 스프링 + 3-2-1 면내");
    expect(supportText(tpl, null)).toBe("지그 tie – 강제 변위 + 3-2-1 면내");
    expect(v3dPairCondText("지그 변위", null, ["A", "B"], supportText(tpl, "normal"))).toBe("하중: 지그 변위 · 지지: 지그 tie 법선 강제 변위 + 3-2-1 면내 · 엔트리: 기준 A · 안 B");
  });
  it("add 열: 두 방식 모두 v3d-regen-jd·js, legacy null", () => {
    expect(row("jig_disp").add).toMatchObject({ src: "jig_disp", label: "지그 3D 다시 만들기", testid: "v3d-regen-jd", legacy: null });
    expect(row("jig_spring").add).toMatchObject({ src: "jig_spring", label: "지그 3D 다시 만들기", testid: "v3d-regen-js", legacy: null });
  });
});

// ---- 화면(목 서버) ----
const tabBtn = (k: string) => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const openStudy = (mod: (r: DoeResultOut) => DoeResultOut, hidden: string[] = []) =>
  renderApp("/p/p-body/doe/doe-40", "power", (s) => {
    s.doe.demoJig();
    s.p3.hiddenSources = hidden;
    const rec = s.doe.recs.find((r) => r.out.id === "doe-40")!;
    rec.result = mod(rec.result!);
  });

describe("V-0246-VW-14 스터디 결과 3행", () => {
  it("행 순서 3D → 순위표|개선율 → 민감도, 정보 testid 이동 전후 동일, 옛 2열 클래스 없음", async () => {
    openStudy((r) => r);
    const rows = await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    expect(rows.id).toBe("doe-load-panel");
    expect(rows.getAttribute("role")).toBe("tabpanel");
    expect([...rows.children].map((c) => c.getAttribute("data-testid"))).toEqual(["doe-row-3d", "doe-row-tables", "doe-row-sens"]);
    const r3d = within(rows.children[0] as HTMLElement);
    expect(r3d.getByTestId("doe-pick-head")).toBeTruthy();
    expect(r3d.getByTestId("doe-pick-actions")).toBeTruthy();
    expect(r3d.getByText("3D 비교")).toBeTruthy();
    const tb = within(rows.children[1] as HTMLElement);
    await waitFor(() => expect(tb.getByRole("table", { name: "순위표" })).toBeTruthy());
    expect(tb.getByRole("table", { name: "ESL별 개선율" })).toBeTruthy();
    // 순위표가 DOM 앞(왼쪽), 개선율이 뒤(오른쪽)
    const order = [...(rows.children[1] as HTMLElement).querySelectorAll("table[aria-label]")].map((t) => t.getAttribute("aria-label"));
    expect(order.indexOf("순위표")).toBeLessThan(order.indexOf("ESL별 개선율"));
    expect(within(rows.children[2] as HTMLElement).getByText("민감도")).toBeTruthy();
    for (const id of ["doe-pick-head", "doe-pick-actions", "vd-open", "redrop", "rank-sort", "per-esl-note", "v3d-cond", "sens-r2"])
      expect(within(rows).queryAllByTestId(id).length, id).toBeGreaterThan(0);
    expect(document.querySelector(".doe-result-2col, .doe-result-left, .doe-result-right")).toBeNull();
    expect(screen.getAllByTestId("vd-open")).toHaveLength(1);
  }, 30000);
});

describe("스터디 화면 — 지그 방식 사유·3D (목 응답)", () => {
  it("failed·no_view 줄(jig-unavail-note) + 비활성 탭 사유, 숨긴 출처는 줄 없음", async () => {
    const mod = (r: DoeResultOut): DoeResultOut => ({
      ...r,
      jig: { ...r.jig!, tie_dofs: "normal", methods: { jig_disp: method({ status: "fallback", code: "JIG_NO_TIE", detail: "tie 노드 없음" }), jig_spring: method({ method: "spring", warnings: ["C_js 없음"] }) } },
    });
    openStudy(mod);
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    const notes = screen.getAllByTestId("jig-unavail-note");
    expect(notes.map((n) => n.getAttribute("data-src"))).toEqual(["jig_disp", "jig_spring"]);
    expect(notes[0].getAttribute("role")).toBe("status");
    expect(notes[0].textContent).toBe("지그 변위 계산 실패: JIG_NO_TIE — tie 노드 없음" + JIG_STATE_TEXT.failed.next);
    expect(notes[1].textContent).toContain("계산됐지만 기준(d000) 값 C_js 가 없어");
    expect(tabBtn("jig_disp").getAttribute("aria-disabled")).toBe("true");
    expect(tabBtn("jig_disp").title).toContain("지그 변위 계산 실패: JIG_NO_TIE");
    cleanup();
    openStudy(mod, ["jig_disp"]);
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    expect(screen.getAllByTestId("jig-unavail-note").map((n) => n.getAttribute("data-src"))).toEqual(["jig_spring"]);
    expect(screen.getByTestId("doe-load-tab").querySelector("[data-tab=jig_disp]")).toBeNull();
  }, 30000);

  it("not_planned·no_jig 는 줄 없음(탭 사유만)", async () => {
    openStudy((r) => ({ ...r, jig: { ...r.jig!, methods: null } }));
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    expect(screen.queryAllByTestId("jig-unavail-note")).toHaveLength(0);
    expect(tabBtn("jig_disp").title).toContain("복제(현재 설정 rank.jig.methods)로 다시 계산");
  }, 30000);

  it("jd 탭: 3D 키가 있으면 조건 줄 지지 문구 = 열 + tie_dofs, 없으면 안내 + 다시 만들기 버튼 1개", async () => {
    const withView = (jd: boolean) => (r: DoeResultOut): DoeResultOut => {
      const did = r.view3d.find((d) => d !== "d000")!;
      return {
        ...r,
        jig: { ...r.jig!, tie_dofs: "translation", methods: { jig_disp: method(), jig_spring: method({ method: "spring" }) } },
        rank_views: { ...r.rank_views!, jig_disp: r.rank_views!.jig!, jig_spring: r.rank_views!.jig! },
        ...(jd ? { view3d_jd: { [did]: `${did}_jd` }, view3d_jd_esl: { [did]: "e1" }, view3d_jd_ref: { e1: "d000_jd_e01" } } : {}),
        source_add: { jig_disp: { available: true, allowed: true }, jig_spring: { available: true, allowed: true } },
      } as DoeResultOut;
    };
    openStudy(withView(true));
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    await waitFor(() => expect(tabBtn("jig_disp").getAttribute("aria-disabled")).not.toBe("true"));
    fireEvent.click(tabBtn("jig_disp"));
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toContain("하중: 지그 변위 · 지지: 지그 tie 병진 강제 변위 + 3-2-1 면내"));
    expect(screen.queryByTestId("v3d-regen-jd")).toBeNull();
    cleanup();
    openStudy(withView(false));
    await screen.findByTestId("doe-result-rows", {}, { timeout: 8000 });
    await waitFor(() => expect(tabBtn("jig_spring").getAttribute("aria-disabled")).not.toBe("true"));
    fireEvent.click(tabBtn("jig_spring"));
    await waitFor(() => expect(screen.getByText(/지그 스프링 응답 3D 가 없습니다 — \[지그 3D 다시 만들기\]로 만드세요/)).toBeTruthy());
    expect(screen.getAllByTestId("v3d-regen-js")).toHaveLength(1);
    expect(screen.queryByTestId("v3d-regen")).toBeNull();
  }, 30000);
});
