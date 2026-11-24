// v0.24.5 #88 후속(사용자 2026-11-24 13:23 "스터디의 모든 모드에서도 해당 지그 esl 버그가 없어야해"): 모든 모드의 실제 결과 응답 →
// 하중 정의 탭(tabState·tabResult). fixtures/real_v0245_modes.json = 실제 코어 산출(tests/doe/test_jig_modes.py) → 백엔드 GET /results 응답
// (backend/tests/test_doe_jig_modes_api.py 가 JIG_MODES_API_DUMP 로 저장). 모드 = 계획 표 행, 기대값은 응답의 계획 열 jig_plan 으로만 고른다.
import { describe, expect, it } from "vitest";
import real from "./fixtures/real_v0245_modes.json";
import { JIG_STATE_TEXT, LOAD_SOURCES, tabResult, tabState } from "../pages/doe/doeTabs";
import { SOURCE_ROWS } from "../view3d/sources";
import type { DoeResultOut } from "../api/types";

type Mode = { scenario: string; sm_jig: "base" | "none"; result: DoeResultOut };
const MODES = (real as unknown as { modes: Record<string, Mode> }).modes;
const JIG_SRC = ["jig_disp", "jig_spring"];
const label = (k: string) => SOURCE_ROWS.find((r) => r.key === k)!.label;

describe("모든 모드: 지그 변위·스프링 탭(실제 응답)", () => {
  it("픽스처 = 계획 표 5행(같은 메시 3 · 다른 메시 2)", () => {
    const by = Object.values(MODES).map((m) => m.sm_jig);
    expect(Object.keys(MODES).length).toBe(5);
    expect(by.filter((x) => x === "base").length).toBe(3);
    expect(by.filter((x) => x === "none").length).toBe(2);
  });

  for (const [pid, m] of Object.entries(MODES)) {
    it(`${pid}: 탭 활성·사유가 계획 열(jig_plan ${m.sm_jig})과 맞음`, () => {
      const r = m.result;
      expect(r.jig_plan).toBe(m.sm_jig);
      const ts = tabState(r, LOAD_SOURCES);
      if (m.sm_jig === "base") {
        for (const k of JIG_SRC) {
          expect(ts.ok[k]).toBe(true);
          expect(ts.reason[k]).toBeNull();
          const v = r.rank_views![k as "jig_disp" | "jig_spring"]!;
          const t = tabResult(r, k, LOAD_SOURCES);
          expect(t.ranking).toEqual(v.ranking);                       // 탭 = 그 출처 보기 순위
          expect(t.metric_effective).toBe(v.metric);
        }
        expect(ts.def).toBe("jig_disp");                              // 기본 탭 = 첫 계산 방식(metric_effective jd)
        expect(ts.ok.full).toBe(true);                                // 전 노드 보기(지그 고정을 꺼도 생김)
        expect(tabResult(r, "full", LOAD_SOURCES).metric_effective).toBe("solve");
      } else {
        for (const k of JIG_SRC) {
          expect(ts.ok[k]).toBe(false);
          expect(ts.reason[k]).toBe(JIG_STATE_TEXT.not_planned.whyMode(label(k)));      // "이 모드는 지그 ESL 을 계산하지 않음"
          expect(ts.reason[k]).not.toContain("복제에서 계산");
        }
        expect(ts.def).toBe("full");
      }
    });
  }

  it("계획 열 없는 옛 응답 = 옛 문구 그대로(정보 삭제 없음)", () => {
    const none = Object.values(MODES).find((m) => m.sm_jig === "none")!;
    const old = { ...none.result, jig_plan: undefined } as DoeResultOut;
    expect(tabState(old, LOAD_SOURCES).reason.jig_disp).toBe(JIG_STATE_TEXT.not_planned.why(label("jig_disp")));
  });
});
