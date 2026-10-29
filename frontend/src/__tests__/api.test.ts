// 목 서버·클라이언트가 백엔드 실제 형식(openapi_p1b + 서비스 코드)과 first-reach 규칙을 따르는지
import { describe, expect, it, vi } from "vitest";
import { ApiError, errorText, request } from "../api/client";
import { api } from "../api/endpoints";
import { MockServer, createMockFetch } from "../mock/server";
import { FRAMES_D, TSTAR_METRICS } from "../mock/data";
import type { Metric, TstarView } from "../api/types";

const METRICS: Metric[] = ["max_strain", "plastic_strain"];

describe("mock t*: first-reach 규칙(esl_core §7.1·§7.4)", () => {
  for (const m of METRICS) {
    it(`${m}: 후보 rank1 = 곡선 max-hold 최종 최대값에 처음 도달한 프레임 = 최종값 1위 요소의 first-reach`, () => {
      const blk = TSTAR_METRICS[m];
      const v = blk.history.value;
      const fin = Math.max(...v);
      const first = v.findIndex((x) => x >= fin * (1 - 1e-6));
      expect(blk.candidates[0].rank).toBe(1);
      expect(blk.candidates[0].frame_index).toBe(first);
      expect(blk.tstar!.frame_index).toBe(first);
      expect(blk.candidates[0].value).toBeCloseTo(fin, 6);
      // 후보 프레임은 서로 다르고 rank 순
      const frames = blk.candidates.map((c) => c.frame_index);
      expect(new Set(frames).size).toBe(frames.length);
      expect(blk.candidates.map((c) => c.rank)).toEqual(frames.map((_, k) => k + 1));
      // 값은 최종값 내림차순(= 요소 최종값), 모두 D 에 있음
      for (let k = 1; k < blk.candidates.length; k++) expect(blk.candidates[k].value).toBeLessThanOrEqual(blk.candidates[k - 1].value);
      expect(blk.candidates.every((c) => c.in_D === true && FRAMES_D.includes(c.frame_index))).toBe(true);
    });

    it(`${m}: hotspot rank1 = 최종값 1위 요소, rising=true`, () => {
      const blk = TSTAR_METRICS[m];
      expect(blk.hotspots[0].rank).toBe(1);
      expect(blk.hotspots[0].elem_id).toBe(blk.candidates[0].elem_id);
      expect(blk.hotspots[0].rising).toBe(true);
      expect(blk.hotspots.every((h) => h.rising === true)).toBe(true);
    });
  }
});

describe("mock 응답 형식", () => {
  const setup = () => {
    const server = new MockServer({ user: "power" });
    globalThis.fetch = createMockFetch(server);
    return server;
  };

  it("GET /tstar: metrics[m].hotspots, candidates[].in_D, frames_D, default_metric", async () => {
    setup();
    const t: TstarView = await api.tstar("c-demo");
    expect(t.default_metric).toBe("max_strain");
    expect(t.frames_D).toEqual(FRAMES_D);
    for (const m of METRICS) {
      expect(t.metrics[m]!.hotspots.length).toBeGreaterThan(0);
      expect(t.metrics[m]!.candidates.every((c) => typeof c.in_D === "boolean")).toBe(true);
    }
    expect(t.hotspots).toEqual(t.metrics.max_strain!.hotspots);
  });

  it("Case: folder_path·case_dir, ESL: latest_validation_id, /cases/{id}/jobs·/validations", async () => {
    const server = setup();
    const c = await api.getCase("c-demo");
    expect(c.folder_path).toBe(c.case_dir);
    const run = await api.eslRun(c.current_esl_run_id!);
    expect(run.latest_validation_id).toBe("val-1");
    const vals = await api.validations("c-demo");
    expect(vals.map((v) => v.id)).toEqual(["val-1"]);
    const j = await api.createJob("c-demo", "VALIDATE", { esl_run_id: run.id });
    expect(j.queue_position).toBe(1);
    const jobs = await api.caseJobs("c-demo");
    expect(jobs[0].id).toBe(j.id);
    const log = await api.jobLog(j.id, 0);
    expect(typeof log.next_cursor).toBe("number");
    server.drain();
    expect((await api.eslRun(run.id)).latest_validation_id).not.toBe("val-1");
  });

  it("409 JOB_NOT_TERMINAL: 실행 중 작업 재시도", async () => {
    setup();
    const c = await api.getCase("c-new");
    const j = await api.createJob(c.id, "CASE_EXTRACT");
    const e = await api.retryJob(j.id).catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(409);
    expect(e.code).toBe("JOB_NOT_TERMINAL");
    expect(errorText(e)).toMatch(/아직 끝나지 않았습니다/);
  });

  it("409 PREREQUISITE_MISSING: missing 목록을 안내", async () => {
    setup();
    const e = await api.createJob("c-new", "ESL_SOLVE").catch((x) => x);
    expect(e.code).toBe("PREREQUISITE_MISSING");
    expect(errorText(e)).toMatch(/필요: ① 추출, ② t\*, ② 지지점/);
  });

  it("비GET 요청에 X-ESL-Request: 1, GET 에는 없음", async () => {
    const spy = vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    globalThis.fetch = spy as unknown as typeof fetch;
    await request("POST", "/x", { body: {} });
    await request("GET", "/y");
    const h0 = new Headers((spy.mock.calls[0] as unknown as [string, RequestInit])[1].headers);
    const h1 = new Headers((spy.mock.calls[1] as unknown as [string, RequestInit])[1].headers);
    expect(h0.get("X-ESL-Request")).toBe("1");
    expect(h1.get("X-ESL-Request")).toBeNull();
  });

  it("413 ARTIFACT_TOO_LARGE detail: rel·path·size·limit", async () => {
    const server = setup();
    const big = server.artifacts["c-demo"].find((a) => !a.downloadable)!;
    const r = await fetch(api.downloadUrl(big.id));
    expect(r.status).toBe(413);
    const d = (await r.json()).detail;
    expect(d.code).toBe("ARTIFACT_TOO_LARGE");
    expect(d).toMatchObject({ rel: big.rel, path: big.path, size: big.size, limit: 20 * 1024 * 1024 });
  });
});
