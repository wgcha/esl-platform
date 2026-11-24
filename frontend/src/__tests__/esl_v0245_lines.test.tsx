// v0.24.5 Verifier 결함: ③ 결과 카드 경계력·내력 줄이 ui.hidden_sources 를 거치지 않고, 새 기본({grade:null, code:BF_DISABLED·FINT_DISABLED})
// 에서 "자료 없음 — h3d 추출…다시 실행" · "…/H3D/NODA/FINT 추가" 로 오안내하던 것(계약 esl_validate_tiers.md §11·§12).
// 3경우: 기본 숨김 / [] / 숨김 밖이면서 꺼짐. 꺼짐 문구 = 코어 esl/view3d_src.py REASON_TEXT 거울.
import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../app/App";
import type { EslBforceSummary, EslFintSummary } from "../api/types";
import { MockServer, createMockFetch } from "../mock/server";
import { SRC_DISABLED_TEXT, bforceLineText, fintLineText, summaryLinesOf } from "../stages/Stage4";
import { hiddenSourcesSig, setHiddenSources } from "../view3d/sources";

const DEFAULT_HIDDEN = ["bforce", "fint", "jig"];
const OFF = { bforce: { grade: null, code: "BF_DISABLED" } as EslBforceSummary, fint: { grade: null, code: "FINT_DISABLED" } as EslFintSummary };
const BF_OFF = "경계력 ESL: 설정에서 꺼짐(bforce.enabled)";
const FI_OFF = "내력 ESL: 설정에서 꺼짐(bforce.enabled · bforce.fint.enabled)";
const MISLEAD = /다시 실행하면|\/H3D\/NODA\/FINT|\(bforce\.fint\.enabled\)/;

afterEach(() => setHiddenSources([]));

describe("v0.24.5 ③ 경계력·내력 줄 — 순수", () => {
  it("꺼짐 code 는 !grade 보다 먼저: 설정에서 꺼짐 + 실제 키(오안내 없음)", () => {
    expect(bforceLineText(OFF.bforce)).toEqual({ text: BF_OFF, warn: false });
    expect(fintLineText(OFF.fint)).toEqual({ text: FI_OFF, warn: false });
    expect(bforceLineText(OFF.bforce).text).not.toMatch(MISLEAD);
    expect(fintLineText(OFF.fint).text).not.toMatch(MISLEAD);
    // 그 밖 분기는 그대로(자료 없음 = 옛 문구)
    expect(fintLineText({ grade: "none", code: "FINT_NO_DATA" }).text).toContain("/H3D/NODA/FINT");
    expect(bforceLineText({ grade: "none", code: "BF_NO_DATA" }).text).toContain("다시 실행하면");
  });

  it("경우 1 기본 숨김(bforce·fint·jig): 줄 없음", () => {
    setHiddenSources(DEFAULT_HIDDEN);
    expect(summaryLinesOf(OFF)).toEqual([]);
    expect(summaryLinesOf({ bforce: { grade: "contact", recon: "ok", mac: 0.97, limits: [] }, fint: { grade: "fint", recon: "ok", mac: 0.99 } })).toEqual([]);
  });

  it("경우 2 []: v0.24.4 화면 그대로(두 줄), 꺼짐이면 꺼짐 문구", () => {
    setHiddenSources([]);
    const on = summaryLinesOf({ bforce: { grade: "contact", recon: "ok", mac: 0.97, limits: [] }, fint: { grade: "fint", recon: "ok", mac: 0.99 } });
    expect(on.map((l) => l.key)).toEqual(["bforce", "fint"]);
    expect(on[0].text).toContain("등급 contact");
    expect(summaryLinesOf(OFF).map((l) => l.text)).toEqual([BF_OFF, FI_OFF]);
    expect(summaryLinesOf(null)).toEqual([]);
    expect(summaryLinesOf({ bforce: null })).toEqual([]);
  });

  it("경우 3 숨김 밖이면서 꺼짐: 보이는 출처 줄만 '설정에서 꺼짐' + 키", () => {
    setHiddenSources(["jig"]);
    expect(summaryLinesOf(OFF)).toEqual([{ key: "bforce", text: BF_OFF, warn: false }, { key: "fint", text: FI_OFF, warn: false }]);
    setHiddenSources(["bforce"]);
    expect(summaryLinesOf(OFF)).toEqual([{ key: "fint", text: FI_OFF, warn: false }]);
  });

  it("꺼짐 문구 = 코어 view3d_src.REASON_TEXT(거울 한 곳)", () => {
    const py = readFileSync(path.resolve(__dirname, "../../../esl/view3d_src.py"), "utf8");
    for (const [code, text] of Object.entries(SRC_DISABLED_TEXT)) {
      const m = py.match(new RegExp(`"${code}":\\s*"([^"]*)"`));
      expect(m?.[1], code).toBe(text);
    }
  });
});

describe("v0.24.5 ③ 경계력·내력 줄 — 화면(목 서버 /version)", () => {
  function renderStep3(hidden: string[]) {
    const server = new MockServer({ user: "power" });
    const run = server.runs.find((r) => r.id === "run-1")!;
    run.forces = { ...run.forces!, ...OFF };
    server.p3.hiddenSources = hidden;
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter initialEntries={["/p/p-body/c/c-demo/step/3"]}>
        <App />
      </MemoryRouter>,
    );
  }
  const sig = (h: string[]) => [...h].sort().join(",");

  it.each([
    ["기본 숨김", DEFAULT_HIDDEN, null],
    ["[]", [] as string[], [BF_OFF, FI_OFF]],
    ["숨김 밖(jig)", ["jig"], [BF_OFF, FI_OFF]],
  ])("%s", async (_name, hidden, exp) => {
    renderStep3(hidden);
    await screen.findByTestId("esl-plastic-line");
    await waitFor(() => expect(hiddenSourcesSig()).toBe(sig(hidden)));
    await screen.findByTestId("esl-plastic-line");
    const lines = [screen.queryByTestId("esl-bforce-line"), screen.queryByTestId("esl-fint-line")];
    if (exp === null) {
      expect(lines).toEqual([null, null]);
      expect(document.body.textContent).not.toMatch(/경계력 ESL:|내력 ESL:/);
    } else {
      expect(lines.map((x) => x?.textContent)).toEqual(exp);
    }
  });
});
