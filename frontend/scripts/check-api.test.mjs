// check:api 강화 회귀: 중첩 객체 키·배열 원소 타입까지 대조하는지 (vitest, node 환경)
// @vitest-environment node
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

describe("check:api 강화", () => {
  const run = (types, historyTs) => {
    const dir = mkdtempSync(path.join(tmpdir(), "chkapi-"));
    // check-api.mjs 가 types.ts 옆에서 읽는 파일 전부(경로 대조 + history·doe·library 의 interface 대조)
    for (const f of ["endpoints.ts", "p3.ts", "history.ts", "opt.ts", "doe.ts", "library.ts"])
      copyFileSync(path.join(ROOT, "src", "api", f), path.join(dir, f));
    writeFileSync(path.join(dir, "types.ts"), types);
    if (historyTs !== undefined) writeFileSync(path.join(dir, "history.ts"), historyTs);
    const openapi = path.join(ROOT, "..", "docs", "contracts", "openapi_p1b.json");
    return spawnSync(process.execPath, [path.join(ROOT, "scripts", "check-api.mjs"), openapi, path.join(dir, "types.ts")],
      { encoding: "utf8" });
  };
  const real = readFileSync(path.join(ROOT, "src", "api", "types.ts"), "utf8");

  // v0.10.0: 백엔드(MR2 openapi)·프런트(MR4 types.ts·library.ts) 병합 후 — 조건부 건너뜀 제거, 항상 대조
  it("현재 types.ts 는 통과", () => {
    const r = run(real);
    expect(r.status, r.stderr).toBe(0);
  });

  it("중첩 객체 배열 원소 타입 불일치(errors: string[])를 잡음", () => {
    const bad = real.replace("config: ConfigStatus;", "config: { ok: boolean; errors: string[] };");
    expect(bad).not.toBe(real);
    const r = run(bad);
    expect(r.status).toBe(1);
    expect(r.stderr).toContain("StatusOut.config.errors[]");
  });

  it("중첩 interface 원시 타입·키 불일치를 잡음", () => {
    const bad = real
      .replace("solver_backends_available: string[];", "solver_backends_available: number[];")
      .replace(/export interface ConfigIssue \{\n  key: string;/, "export interface ConfigIssue {\n  key: string;\n  extra: string;");
    const r = run(bad);
    expect(r.status).toBe(1);
    expect(r.stderr).toContain("ToolsStatus.solver_backends_available[]: 타입 불일치");
    expect(r.stderr).toContain("ConfigIssue.extra: 스키마에 없는 키");
  });

  const hist = readFileSync(path.join(ROOT, "src", "api", "history.ts"), "utf8");

  it("history.ts 의 interface 도 대조(키 누락·null 허용·원시 타입)", () => {
    const bad = hist
      .replace("  duration_s: number | null;\n  wait_s: number | null;\n  current_step_no", "  duration_s: number;\n  wait_s: number | null;\n  current_step_no")
      .replace("  mtime?: number | null;", "  mtime?: string | null;")
      .replace("  has_more: boolean;\n", "");
    expect(bad).not.toBe(hist);
    const r = run(real, bad);
    expect(r.status).toBe(1);
    expect(r.stderr).toContain("HistoryItem.duration_s: null 허용 불일치");
    expect(r.stderr).toContain("ReviewFingerprint.mtime: 타입 불일치");
    expect(r.stderr).toContain("HistoryPage.has_more: types.ts 에 없음");
  });

  it("history.ts 호출 경로가 openapi 에 없으면 잡음", () => {
    const bad = hist.replace('"/history"', '"/histories"');
    expect(bad).not.toBe(hist);
    const r = run(real, bad);
    expect(r.status).toBe(1);
    expect(r.stderr).toContain("history.ts GET /histories: openapi 에 없는 경로");
  });
});
