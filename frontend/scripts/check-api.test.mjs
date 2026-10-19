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
  const run = (types) => {
    const dir = mkdtempSync(path.join(tmpdir(), "chkapi-"));
    copyFileSync(path.join(ROOT, "src", "api", "endpoints.ts"), path.join(dir, "endpoints.ts"));
    writeFileSync(path.join(dir, "types.ts"), types);
    const openapi = path.join(ROOT, "..", "docs", "contracts", "openapi_p1b.json");
    return spawnSync(process.execPath, [path.join(ROOT, "scripts", "check-api.mjs"), openapi, path.join(dir, "types.ts")],
      { encoding: "utf8" });
  };
  const real = readFileSync(path.join(ROOT, "src", "api", "types.ts"), "utf8");

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
});
