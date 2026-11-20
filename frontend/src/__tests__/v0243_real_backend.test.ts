// v0.24.3 통합: 실제 코어(esl.val_src)·실제 백엔드 응답(워커 시험 worker/tests/test_val_src_e2e.py 가 저장)을 그대로 담은
// fixtures/real_v0243.json 을 프런트 파서·순수 함수에 먹여 출처 행·판정 표식·조건·한계·응답 형태를 대조한다.
// 재생성: 시험 환경에서 `VAL_SRC_DUMP=/tmp/a.json VAL_SRC_DUMP_NV=/tmp/b.json pytest worker/tests/test_val_src_e2e.py` 후
// {...a, nv: b} 를 이 파일로 저장(응답 형식이 바뀌면 다시 만든다).
import { describe, expect, it } from "vitest";
import real from "./fixtures/real_v0243.json";
import { statusOf, undeterminedText } from "../components/VerdictStatus";
import { SOURCE_ROWS, defaultValSource, markOf, unavailText, valRowOf, valTabItems } from "../view3d/sources";
import type { DispFieldOut, FieldOut, ValidationOut, ValidationSourcesHistOut, ValidationSourcesOut } from "../api/types";

const R = real as unknown as Record<string, unknown>;
const bf = real.sources_bf as unknown as ValidationSourcesOut;
const plain = real.sources_plain as unknown as ValidationSourcesOut;
const old = real.sources_old as unknown as ValidationSourcesOut;
const nv = (real.nv as unknown as { sources: ValidationSourcesOut }).sources;

describe("v0.24.3 실제 백엔드 응답 ↔ 프런트(④ 검증 출처별)", () => {
  it("출처 행: 표 키·순서·이름이 화면 SOURCE_ROWS 와 같다(코어 LABEL 은 시험 V-4 가 확인)", () => {
    for (const s of [bf, plain, old, nv]) expect(s.rows.map((r) => r.key)).toEqual(SOURCE_ROWS.filter((r) => !r.optional).map((r) => r.key));   // 실제 v0.24.3 백엔드 = 4행(v0.24.4 새 행은 optional)
    expect(bf.default).toBe("full");
  });

  it("전부 done: 탭 4개 중 지그만 비활성(사유 문구), 나머지 판정 표식 · 경계력은 '비교용 아님'", () => {
    const items = valTabItems(bf, true)!;
    expect(items.map((i) => i.ok)).toEqual([false, true, true, true]);
    expect(items[0].why).toBe(unavailText("지그 ESL", bf.rows[0].reason));
    expect(items.map((i) => i.add)).toEqual([undefined, undefined, undefined, undefined]);
    expect(items[1].mark).toEqual({ text: "PASS", tone: "ok" });
    expect(items[2].mark).toEqual({ text: "PASS · 비교용 아님", tone: "warn" });
    expect(items[3].mark).toEqual({ text: "PASS", tone: "ok" });
    const bfRow = valRowOf(bf, "bforce")!;
    expect(items[2].title).toBe([bfRow.cond_text, ...bfRow.limit_text].join("\n"));
    expect(bfRow.note).toMatch(/Radioss 변위\(강체 제거\)/);        // 코드가 아니라 문구
    expect(bfRow.reaction_role).toBe("judge");
    expect(defaultValSource(bf)).toBe("full");
  });

  it("출처 자료가 없는 Case(경계력·내력 없음): 해당 탭 비활성 + 코어 사유(BF_NO_DATA·FINT_NO_DATA), 선택 불가(add 없음)", () => {
    const items = valTabItems(plain, true)!;
    expect(items.map((i) => i.ok)).toEqual([false, true, false, false]);
    const rows = Object.fromEntries(plain.rows.map((r) => [r.key, r]));
    expect([rows.bforce.code, rows.fint.code]).toEqual(["BF_NO_DATA", "FINT_NO_DATA"]);
    expect(items[2].why).toBe(unavailText("경계력 ESL", rows.bforce.reason));
    expect(items[2].add).toBeUndefined();
    expect(items[2].mark).toBeUndefined();
    const e = R.err_plain_bforce as { code: string; src: string; reason: string; reason_code: string };
    expect(e.code).toBe("VAL_SOURCE_UNAVAILABLE");
    expect([e.src, e.reason, e.reason_code]).toEqual(["bforce", rows.bforce.reason, "BF_NO_DATA"]);
  });

  it("옛 검증(sources.json 없음): full 만 가능, 나머지 VAL_SRC_NOT_RUN → 선택 가능한 빈 탭(검증 다시 실행)", () => {
    const items = valTabItems(old, true)!;
    expect(items.map((i) => i.ok)).toEqual([false, true, false, false]);
    expect(items.map((i) => !!i.add)).toEqual([false, false, true, true]);
    expect(valTabItems(old, false)!.some((i) => i.add)).toBe(false);     // 과거 실행(읽기 전용)은 실행 버튼 없음
    expect(items[1].mark).toEqual({ text: "PASS", tone: "ok" });
    expect(markOf(old.rows[1])).toEqual({ text: "PASS", tone: "ok" });
  });

  it("판정 불가 출처(full_solve never): 판정 불가 표식, 필드·변위 카드 근거(field·disp = null)와 409 PREREQUISITE_MISSING", () => {
    const items = valTabItems(nv, true)!;
    expect(items.map((i) => i.ok)).toEqual([false, true, true, true]);
    expect(items[2].mark).toEqual({ text: "판정 불가 · 비교용 아님", tone: "warn" });
    expect(items[3].mark).toEqual({ text: "판정 불가", tone: "muted" });
    const X = real.nv as unknown as Record<string, unknown>;
    for (const k of ["bforce", "fint"]) {
      const v = X[`validation_${k}`] as ValidationOut;
      expect(statusOf(v)).toBe("UNDETERMINED");
      expect(v.disp).toBeNull();
      expect(v.field).toBeNull();                                         // 화면: 변위·겹쳐보기 카드 비활성(안내 문구)
      expect(v.hotspots).toEqual([]);
      expect(undeterminedText(v)).toContain("전체 재해석 생략(full_solve=never)");
      expect((X[`field_${k}`] as { code: string }).code).toBe("PREREQUISITE_MISSING");
      expect((X[`disp-field_${k}`] as { code: string }).code).toBe("PREREQUISITE_MISSING");
    }
  });

  it("출처별 validation: 판정·지표 = sources.json 행, 반력 역할 = criteria.reaction_role, dir_rel 은 출처 폴더", () => {
    const full = R.validation_full as ValidationOut;
    expect(statusOf(full)).toBe("PASS");
    for (const k of ["bforce", "fint"]) {
      const v = R[`validation_${k}`] as ValidationOut;
      const row = valRowOf(bf, k)!;
      expect(statusOf(v)).toBe(row.status);
      expect(v.fail_reasons).toEqual(row.fail_reasons);
      expect(v.criteria.reaction_role).toBe(row.reaction_role);
      expect(v.id).toBe(full.id);
      expect(v.disp!.n_nodes).toBe(full.disp!.n_nodes);
    }
  });

  it("출처별 field·disp-field: 같은 모양(점 열 수·평면·색 범위), 점 수는 max_points 이하", () => {
    for (const k of ["full", "bforce", "fint"]) {
      const f = R[`field_${k}`] as FieldOut;
      const d = R[`disp_${k}`] as DispFieldOut;
      expect(f.layer).toBe("err");
      expect(f.points.every((p) => p.length === 6)).toBe(true);
      expect(f.n_returned).toBe(f.points.length);
      expect(f.n_returned).toBeLessThanOrEqual(60);
      expect(Object.keys(f.plane).sort()).toEqual(["e1", "e2", "origin"]);
      expect(d.points.every((p) => p.length === 5)).toBe(true);
      expect(d.n_total).toBe((R.validation_full as ValidationOut).disp!.n_nodes);
      expect(d.U).toBeGreaterThan(0);
    }
  });

  it("이력: /cases/{id}/validations/sources 가 검증마다 같은 형식의 행(KEYS 순서)", () => {
    const h = R.hist_bf as ValidationSourcesHistOut;
    expect(h.items).toHaveLength(1);
    expect(h.items[0].rows).toEqual(bf.rows);
  });
});
