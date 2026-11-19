// v0.24.2 경계력 원자료 ESL 때 보충 — Case ③ 경계력·내력 줄 문구(esl_bforce_ondemand.md §6, V-0242-BFD-13)
import { describe, expect, it } from "vitest";
import { bforceLineText, fintLineText } from "../stages/Stage4";

const FAILED = "경계력 원자료 보충 실패 — 프레임 37: 시간 초과 1800 s(altair.bf_on_demand_timeout_s). ③ ESL 을 다시 계산하면 다시 시도합니다";
const SKIPPED = "경계력 원자료 보충 생략 — 프레임 37: 서버 HyperWorks 실행 파일 또는 추출 TCL 없음(altair.hw_exe_path)";

describe("v0.24.2 경계력·내력 줄 — 보충 실패·생략", () => {
  it("경계력 줄: BF_EXTRACT_FAILED·SKIPPED → 자료 없음 — reason 그대로(경고 아님)", () => {
    expect(bforceLineText({ grade: "none", code: "BF_EXTRACT_FAILED", reason: FAILED })).toEqual({ text: `경계력 ESL: 자료 없음 — ${FAILED}`, warn: false });
    expect(bforceLineText({ grade: "none", code: "BF_EXTRACT_SKIPPED", reason: SKIPPED })).toEqual({ text: `경계력 ESL: 자료 없음 — ${SKIPPED}`, warn: false });
  });
  it("BF_NO_DATA·reason 없음·그 밖 분기는 그대로", () => {
    const old = "경계력 ESL: 자료 없음 — h3d 추출(v0.24.0 TCL)을 다시 실행하면 접촉력·가속도로 계산합니다";
    expect(bforceLineText({ grade: "none", code: "BF_NO_DATA", reason: "추출물에 경계력 결과 없음" }).text).toBe(old);
    expect(bforceLineText({ grade: "none", code: "BF_EXTRACT_FAILED" }).text).toBe(old);
    expect(bforceLineText({ grade: "none" }).text).toBe(old);
    const ok = bforceLineText({ grade: "contact", recon: "ok", mac: 0.97, limits: [] });
    expect(ok.text).toContain("등급 contact");
    expect(bforceLineText({ grade: "contact", code: "BF_EXTRACT_FAILED", reason: "x" }).text).toContain("등급 contact");
  });
  it("내력 줄: 등급 none 이면 reason 그대로(변경 없음)", () => {
    expect(fintLineText({ grade: "none", code: "BF_EXTRACT_FAILED", reason: FAILED }).text).toBe(`내력 ESL: 자료 없음 — ${FAILED}`);
    expect(fintLineText({ grade: "none", code: "BF_EXTRACT_SKIPPED", reason: SKIPPED }).warn).toBe(false);
  });
});
