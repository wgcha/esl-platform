// V-0232-6·7(esl_v0232_fixes.md §3·§4.4): 지그 칩 항상 표시(계산됨·미계산·fallback) + 3D 비교 하중 조건 한 줄·지그 응답 토글
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { jigNoneText } from "../components/DoeRanking";
import { v3dCondText } from "../pages/doe/DoeStudy";

afterEach(cleanup);
const openJig = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => s.doe.demoJig());

describe("지그 칩 3상태", () => {
  it("계산됨 ok = 기본 글자색(muted 없음), 상태 띠 첫 칩", async () => {
    openJig("doe-40");
    const chip = await screen.findByTestId("jig-line");
    expect(chip.getAttribute("data-status")).toBe("ok");
    expect(chip.className).toBe("doe-chip");
    const band = screen.getByTestId("doe-status");
    expect(band.querySelector("summary, .doe-chip")).toBe(chip);
  }, 20000);
  it("poor·fallback = 경고색 유지", async () => {
    openJig("doe-41");
    expect((await screen.findByTestId("jig-line")).className).toContain("warn-text");
    cleanup();
    openJig("doe-42");
    const fb = await screen.findByTestId("jig-line");
    expect(fb.getAttribute("data-status")).toBe("fallback");
    expect(fb.className).toContain("warn-text");
  }, 20000);
  it("미계산(옛 순위 설정): jig_on_clone true = '복제하면 계산', false = '이 방식은 지그 순위 없음', 펼치면 근거 문구", async () => {
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const rec = s.doe.recs.find((r) => r.out.id === "doe-21")!;
      rec.result = { ...rec.result!, jig: null, jig_on_clone: true };
    });
    const chip = await screen.findByTestId("jig-line");
    expect(chip.getAttribute("data-status")).toBe("none");
    expect(chip.textContent).toBe("지그: 미계산(이전 설정 스터디 — 복제하면 계산)");
    expect(chip.className).toBe("doe-chip");
    fireEvent.click(chip);
    expect(screen.getByTestId("jig-line-full").textContent).toMatch(/복제하면 지금 순위 설정\(지그 포함\)으로 다시 계산/);
    expect(jigNoneText(false).chip).toBe("지그: 미계산(이전 설정 스터디 — 이 방식은 지그 순위 없음)");
    expect(jigNoneText(null).chip).toBe(jigNoneText(false).chip);
  }, 20000);
});

describe("3D 비교 하중 조건 + 지그 응답", () => {
  it("v3dCondText: 지그·전 노드 ESL 문구, 엔트리 같음/다름", () => {
    expect(v3dCondText(true, 14, ["E1", "E1"])).toBe("하중: 지그 하중 · 지지: tie 고정(14점) · 엔트리: E1");
    expect(v3dCondText(false, null, ["E1", "E2"])).toBe("하중: 전 노드 ESL 재풀이 · 지지: 3-2-1 · 엔트리: 기준 E1 · 안 E2");
    expect(v3dCondText(false, null, [null, null])).toBe("하중: 전 노드 ESL 재풀이 · 지지: 3-2-1 · 엔트리: –");
  });
  it("지그 3D 있는 스터디: 기본 = 지그 하중(tie 고정 n점), 토글로 전 노드 ESL", async () => {
    openJig("doe-40");
    const cond = await screen.findByTestId("v3d-cond");
    await waitFor(() => expect(cond.textContent).toMatch(/^하중: 지그 하중 · 지지: tie 고정\(14점\) · 엔트리: \S+/));
    const seg = screen.getByTestId("v3d-mode");
    const [jigBtn, eslBtn] = Array.from(seg.querySelectorAll("button"));
    expect(jigBtn.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(eslBtn);
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toMatch(/^하중: 전 노드 ESL 재풀이 · 지지: 3-2-1 · 엔트리: /));
    expect(eslBtn.getAttribute("aria-pressed")).toBe("true");
  }, 20000);
  it("지그 3D 없는(옛·지그 없음) 스터디: 토글 없음 + 조건 라벨(전 노드 ESL · 3-2-1)", async () => {
    renderApp("/p/p-body/doe/doe-3");
    const cond = await screen.findByTestId("v3d-cond");
    expect(cond.textContent).toMatch(/^하중: 전 노드 ESL 재풀이 · 지지: 3-2-1 · 엔트리: /);
    expect(screen.queryByTestId("v3d-mode")).toBeNull();
  }, 20000);
});
