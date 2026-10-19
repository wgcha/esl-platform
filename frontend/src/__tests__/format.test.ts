// 숫자 표기: 부호 있는 0 정규화("-0.0%" → "0.0%")
import { describe, expect, it } from "vitest";
import { fixedZ, fmtFixed, pct, pv, spv } from "../lib/format";

describe("format 부호 있는 0", () => {
  it("반올림해 0 이면 부호 없음, 나머지는 부호 유지", () => {
    expect(spv(-0.04)).toBe("0.0%");
    expect(spv(-0)).toBe("0.0%");
    expect(spv(0.04)).toBe("0.0%");
    expect(spv(-12.44)).toBe("-12.4%");
    expect(spv(3.26)).toBe("+3.3%");
    expect(spv(null)).toBe("–");
    expect(pv(-0.01)).toBe("0.0%");
    expect(pct(-0.0001)).toBe("0.0%");
    expect(fmtFixed(-0.001)).toBe("0.00");
    expect(fixedZ(-0.5, 0)).toBe("-1");
  });
});
