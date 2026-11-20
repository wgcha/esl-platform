// v0.24.4 P3 통합: 실제 코어·워커·백엔드 응답(worker/tests/test_load_source_e2e.py 가 P3_E2E_DUMP 로 저장)을 담은
// fixtures/real_v0244_p3.json 을 프런트 순수 함수·파서에 먹여 B3 실제 형식과 C3 가정이 맞는지 대조한다.
// 재생성: `P3_E2E_DUMP=/tmp/a.json pytest worker/tests/test_load_source_e2e.py` → 이 폴더에 real_v0244_p3.json 으로 저장.
import { describe, expect, it } from "vitest";
import real from "./fixtures/real_v0244_p3.json";
import { ApiError } from "../api/client";
import { normalizeDoeSettings } from "../api/doe";
import { normalizeOptSettings } from "../api/opt";
import { SOURCE_ROWS } from "../view3d/sources";
import { loadSourceChipOf, loadSourceErrorText, loadSourceOptions, unconfirmedOf } from "../view3d/loadSource";
import type { EntrySourcesOut, LoadSourceCheck } from "../api/types";

const R = real as unknown as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const es = R.entries_sources as EntrySourcesOut;
const err = (k: string) => {
  const d = R[k].detail as { code: string; message: string };
  return new ApiError(422, d);
};

describe("v0.24.4 P3 실제 백엔드 응답 ↔ 프런트(하중 출처 선택)", () => {
  it("묶음 응답: 키·순서 = SOURCE_ROWS, 행 = ④ 행 + load_available·grade·flags, sources 요약 존재", () => {
    const keys = SOURCE_ROWS.map((r) => r.key);
    expect(es.sources.map((s) => s.key)).toEqual(keys);
    expect(es.items.length).toBe(es.ids.length);
    for (const it of es.items) {
      expect(it.rows.map((r) => r.key)).toEqual(keys);
      for (const r of it.rows) expect(typeof r.load_available).toBe("boolean");
    }
    expect(es.sources.find((s) => s.key === "jig_disp")!.worst).toBe("caution");
  });

  it("스터디 옵션: 출처별 표식·불가 사유(하중 없음 fint), 변위는 주의 표식", () => {
    const o = Object.fromEntries(loadSourceOptions(es.items, "doe").map((x) => [x.key, x]));
    expect(o.full.mark).toEqual({ text: "PASS", tone: "ok" });
    expect(o.jig.disabled).toBe(false);
    expect(o.jig_disp.mark!.text).toBe("PASS ⚠");
    expect(o.jig_disp.disabled).toBe(false);
    expect(o.fint.disabled).toBe(true);
    expect(o.fint.why).toContain("불가");
  });

  it("비드 최적화 옵션: 지그 변위·스프링 = 열 사유로 불가, 지그 고정·전 노드 가능", () => {
    const o = Object.fromEntries(loadSourceOptions(es.items, "opt").map((x) => [x.key, x]));
    expect(o.jig_disp.disabled).toBe(true);
    expect(o.jig_spring.disabled).toBe(true);
    expect(o.jig.disabled).toBe(false);
    expect(o.full.disabled).toBe(false);
  });

  it("422 본문: UNCONFIRMED{entries(grade·flags 포함), worst}·UNAVAILABLE{entry_ids, reasons 사전}·UNSUPPORTED{reason}", () => {
    const u = unconfirmedOf(err("err_unconfirmed"))!;
    expect(u.worst).toBe("FAIL");
    expect(u.entries.length).toBe(3);
    expect(u.entries.every((e) => e.status === "FAIL" && e.comparable === false && e.grade === "FAIL")).toBe(true);
    const un = loadSourceErrorText(err("err_unavailable"))!;
    expect(un).toContain("하중 출처를 쓸 수 없습니다");
    for (const id of R.err_unavailable.detail.entry_ids) expect(un).toContain(id);
    expect(un).toContain(Object.values(R.err_unavailable.detail.reasons as Record<string, string>)[0]);
    const us = loadSourceErrorText(err("err_unsupported"))!;
    expect(us).toContain(R.err_unsupported.detail.reason);
  });

  it("스냅샷 칩: 비드 최적화 options.load_source(_check), 스터디 inputs.load_source(_check), 안 고르면 칩 없음", () => {
    const o = R.opt_bforce_ack;
    const c = loadSourceChipOf(o.options.load_source, o.options.load_source_check as LoadSourceCheck)!;
    expect(c.short).toBe("경계력 ESL · FAIL · 비교용 아님");
    const j = R.opt_jig;
    expect(loadSourceChipOf(j.options.load_source, j.options.load_source_check)!.short).toBe("지그 고정 · PASS");
    const s = R.study_jig_spring.study.inputs;
    expect(loadSourceChipOf(s.load_source, s.load_source_check)!.short).toBe("지그 스프링 · PASS");
    expect(loadSourceChipOf(R.study_none.study.inputs.load_source, R.study_none.study.inputs.load_source_check)).toBeNull();
    expect("load_source" in R.opt_full.options).toBe(true);
  });

  it("스터디 결과: 고른 출처의 지표가 순위 기준(metric)·metric_default 로 통과", () => {
    expect(R.study_jig_spring.result).toMatchObject({ metric: "js", metric_effective: "js", load_source: "jig_spring", metric_default: "jig" });
    expect(R.study_bforce.result).toMatchObject({ metric: "bf", load_source: "bforce" });
    expect(R.study_none.result.load_source).toBeNull();
  });

  it("설정 노출: DoeSettingsOut·OptSettingsOut 최상위 load_source_default", () => {
    expect(normalizeDoeSettings(R.doe_settings).load_source_default).toBeUndefined();   // null = 순위 지표 기준
    expect(R.doe_settings.load_source_default).toBeNull();
    expect(normalizeOptSettings(R.opt_settings).load_source_default).toBe("full");
  });
});
