// v0.24.4 P2b 통합: 실제 코어·워커·백엔드 응답(워커 시험 worker/tests/test_jig_case_e2e.py 가 저장)을 담은 fixtures/real_v0244.json 을
// 프런트 파서·순수 함수에 먹여 지그 세 행(고정·변위·스프링)의 탭·표식·한계·3D 지지 기호를 대조한다.
// 재생성: 시험 환경에서 `JIG_E2E_DUMP=/tmp/a.json pytest worker/tests/test_jig_case_e2e.py` 후 val_hist·esl_summary_keys 를 빼고 이 폴더에 저장.
import { describe, expect, it } from "vitest";
import real from "./fixtures/real_v0244.json";
import { SOURCE_ROWS, caseTabItems, defaultCaseSource, markOf, valRowOf, valTabItems } from "../view3d/sources";
import { supportSymbol } from "../view3d/supports";
import type { ValidationOut, ValidationSourcesOut, View3dOut, View3dSourcesOut } from "../api/types";

const R = real as unknown as Record<string, unknown>;
const s3 = real.view3d_sources as unknown as View3dSourcesOut;
const sv = real.val_sources as unknown as ValidationSourcesOut;
const JIG = ["jig", "jig_disp", "jig_spring"];

describe("v0.24.4 실제 백엔드 응답 ↔ 프런트(지그 ESL 세 행)", () => {
  it("출처 행: 키·순서 = 화면 SOURCE_ROWS(6행), 지그 이름은 코어 라벨과 같은 표", () => {
    for (const s of [s3, sv]) expect(s.rows.map((r) => r.key)).toEqual(SOURCE_ROWS.map((r) => r.key));
    expect(SOURCE_ROWS.filter((r) => r.group === "jig").map((r) => r.label)).toEqual(["지그 고정", "지그 변위", "지그 스프링"]);
  });

  it("Case ③ 탭: 지그 3탭 활성·그룹 묶음(short), 기본 탭 = 응답 default", () => {
    const items = caseTabItems(s3)!;
    for (const k of JIG) expect(items.find((i) => i.key === k)!.ok).toBe(true);
    expect(items.filter((i) => i.group === "jig").map((i) => i.short)).toEqual(["고정", "변위", "스프링"]);
    expect(defaultCaseSource(s3)).toBe(s3.default);
    for (const r of s3.rows.filter((x) => JIG.includes(x.key))) expect(r.rigid).toBe("kabsch");
  });

  it("④ 검증 탭: 지그 3탭 판정 표식·조건 툴팁·한계(변위 = 낙하 결과 강제 → 주의 표식), 반력은 정보", () => {
    const items = valTabItems(sv, true)!;
    for (const k of JIG) {
      const row = valRowOf(sv, k)!;
      const it = items.find((i) => i.key === k)!;
      expect(it.ok).toBe(true);
      expect(row.reaction_role).toBe("info");
      expect(it.mark).toEqual(markOf(row));
      expect(it.title).toContain(row.cond_text!);
    }
    const d = valRowOf(sv, "jig_disp")!;
    expect(d.limits).toContain("JIG_DISP_FROM_TARGET");
    expect(d.limit_text.length).toBe(d.limits.length);
    expect(markOf(d)!.text).toMatch(/⚠$/);
  });

  it("3D 지지 기호: tie dof \"123\" = 채움 ▲(3축), 3-2-1 면내 \"ij\" = 반 채움 ◭(글자 2개 — 숫자가 아니라 축 선분 없음) — 세 행 모두", () => {
    for (const k of JIG) {
      const v = R[`view3d_${k}`] as View3dOut;
      const dofs = new Set(v.supports.map((x) => x.dof));
      expect([...dofs].sort()).toEqual(["123", "ij"]);
      expect(supportSymbol("123")).toMatchObject({ kind: "filled", count: 3, axes: [0, 1, 2] });
      expect(supportSymbol("ij")).toMatchObject({ kind: "half", count: 2, axes: [] });
    }
  });

  it("출처별 validation 응답: 행 판정 = 목록 행, dir_rel 은 출처 폴더", () => {
    for (const k of JIG) {
      const v = R[`validation_${k}`] as ValidationOut;
      expect(v.status).toBe(valRowOf(sv, k)!.status);
      expect(String((v as unknown as { dir_rel: string }).dir_rel)).toContain(k);
    }
  });
});
