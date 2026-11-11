// v0.15.1 "미리보기 했는데 안 보여 — 실패? 다음 단계 안 간 거야?" · "에러가 떴는데 창이 금방 사라졌다":
// 실패한 DOE_PREVIEW 는 phase 가 READY 로 돌아가 진행 패널(JobProgress)이 사라지고 격자는 '미리보기를 실행하면…' 만 보였다(실패가 안 보임).
// → 최신 작업 실패 배너(단계·코드·문구·[로그 보기] tail) 고정, 미리보기 칸 실패 안내, OK 0개 사유별 개수, 동작 오류는 닫기 전까지 유지.
import { fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { usePolling } from "../lib/usePolling";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import type { JobOut } from "../api/types";
import { progressText } from "../components/JobFailBanner";
import { zeroOkText } from "../pages/doe/DoeStudy";
import { fixedViolRows, fixedViolText } from "../components/FixedViol";

const primary = (c: HTMLElement) => c.querySelector("button[data-primary]") as HTMLButtonElement;

function failPreview(s: Parameters<NonNullable<Parameters<typeof renderApp>[2]>>[0]) {
  const rec = s.doe.recs.find((x) => x.out.id === "doe-5")!;
  const base = s.doe.seededJobs.find((j) => j.id === rec.jobIds[rec.jobIds.length - 1])!;
  const j: JobOut = {
    ...base,
    id: "j-pv-fail",
    job_type: "DOE_PREVIEW",
    state: "FAILED",
    failure_code: "SELECT_BASIS_FAILED",
    failure_message: "기저 계산 실패: 비드 b1 경계 고리 없음",
    steps: [
      { ...base.steps![0], step_no: 1, step_key: "BD_MATRIX", state: "SUCCEEDED" },
      { ...base.steps![0], step_no: 2, step_key: "BD_GRID", state: "FAILED", failure_code: "SELECT_BASIS_FAILED", failure_message: "기저 계산 실패: 비드 b1 경계 고리 없음" },
      { ...base.steps![0], step_no: 3, step_key: "BD_PREVIEW_REGISTER", state: "PENDING" },
    ],
  };
  s.jobs.push(j);
  s.logs[j.id] = ["[esl-worker] BD_GRID 시작", "Traceback …", "EslError: SELECT_BASIS_FAILED 경계 고리 없음"];
  rec.jobIds.push(j.id);
}

describe("미리보기 상태 표시", () => {
  it("미리보기 실패: 배너(단계 2 썸네일·코드·문구) + 미리보기 칸 안내 + [로그 보기] tail — 다른 조작·시간이 지나도 남음", async () => {
    renderApp("/p/p-body/doe/doe-5", "power", failPreview);
    const b = await screen.findByTestId("job-fail-banner");
    expect(b.textContent).toMatch(/강성 평가 미리보기 실패 · 단계 2 썸네일 · SELECT_BASIS_FAILED/);
    // v0.17.1 DOE 화면 실패 = 빨간 1줄 + [자세히](문구·[로그 보기]는 접힘)
    expect(screen.queryByTestId("job-fail-msg")).toBeNull();
    fireEvent.click(within(b).getByRole("button", { name: "자세히" }));
    expect(screen.getByTestId("job-fail-msg").textContent).toMatch(/경계 고리 없음/);
    expect(screen.getByTestId("preview-failed").textContent).toMatch(/단계 2 썸네일 · SELECT_BASIS_FAILED/);
    fireEvent.click(within(b).getByRole("button", { name: "로그 보기" }));
    await waitFor(() => expect(screen.getByTestId("job-log-tail").textContent).toMatch(/EslError: SELECT_BASIS_FAILED/));
    // 다른 조작(도구 바꾸기)·시간 경과 뒤에도 그대로
    await waitFor(() => expect(screen.getByRole("toolbar", { name: "선택 도구" })).toBeTruthy());
    fireEvent.click(screen.getByRole("radio", { name: "브러시" }));
    await new Promise((r) => setTimeout(r, 300));
    expect(screen.getByTestId("job-fail-banner")).toBeTruthy();
    expect(screen.getByTestId("job-log-tail")).toBeTruthy();
  });

  it("OK 0개: 사유별 개수(고정 침범·품질 실패·뒤집힘)", async () => {
    renderApp("/p/p-body/doe/doe-6", "power", (s) => {
      const rec = s.doe.recs.find((x) => x.out.id === "doe-6")!;
      rec.cells!.forEach((c, i) => {
        c.status = i % 3 === 0 ? "SKIPPED_FIXED" : "FAILED_MESH";
        c.code = i % 3 === 0 ? "SELECT_FIXED_VIOLATION" : i % 3 === 1 ? "SELECT_QUALITY_FAIL" : "SELECT_MORPH_INVERTED";
      });
      rec.out.doe!.preview!.ok = 0;
    });
    const z = await screen.findByTestId("preview-zero-ok");
    expect(z.textContent).toMatch(/OK\)이 0개입니다 — 고정 침범 \d+ · 품질 실패 \d+ · 뒤집힘 \d+/);
  });

  it("동작 오류는 폴링·재렌더로 지워지지 않고 [닫기]로만", async () => {
    const r = renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByTestId("param-B1_W")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("B1 블렌딩 반경"), { target: { value: "num" } });
    await waitFor(() => expect(primary(r.container).textContent).toBe("선택 저장"));
    r.server.doe.recs.find((x) => x.out.id === "doe-5")!.out.version += 1; // 다른 사용자가 먼저 바꿈
    await waitFor(() => expect(primary(r.container).disabled).toBe(false));
    fireEvent.click(primary(r.container));
    const err = await screen.findByText(/다른 사용자가 먼저/);
    fireEvent.click(screen.getByRole("radio", { name: "사각" }));
    await new Promise((x) => setTimeout(x, 300));
    expect(screen.getByText(/다른 사용자가 먼저/)).toBe(err);
    fireEvent.click(screen.getByRole("button", { name: "오류 닫기" }));
    expect(screen.queryByText(/다른 사용자가 먼저/)).toBeNull();
  });

  it("진행 줄·사유 문구 함수", () => {
    const j = { steps: [{ step_no: 1, step_key: "BD_MATRIX", state: "SUCCEEDED" }, { step_no: 2, step_key: "BD_GRID", state: "RUNNING", progress_pct: 41.6 }, { step_no: 3, step_key: "BD_PREVIEW_REGISTER", state: "PENDING" }] } as unknown as JobOut;
    expect(progressText(j)).toBe("단계 2/3 · 썸네일 42%");
    expect(zeroOkText([{ status: "SKIPPED_GEOM", code: "X" }])).toBe("그 밖 1");
  });
});

describe("usePolling(원인): 주기만 바뀌면 자료를 비우지 않음", () => {
  it("3000 → 0 으로 바꿔도 data 유지(화면 전체 깜빡임·자식 상태 초기화 없음), deps 가 바뀌면 비움", async () => {
    let n = 0;
    const seen: (number | null)[] = [];
    const { result, rerender } = renderHook(({ ms, id }) => {
      const p = usePolling(() => Promise.resolve(++n), ms, [id]);
      seen.push(p.data);
      return p;
    }, { initialProps: { ms: 3000, id: "a" } });
    await waitFor(() => expect(result.current.data).toBe(1));
    seen.length = 0;
    rerender({ ms: 0, id: "a" });
    await waitFor(() => expect(result.current.data).toBe(2));
    expect(seen.includes(null)).toBe(false);
    rerender({ ms: 0, id: "b" });
    await waitFor(() => expect(result.current.data).toBe(3));
    expect(seen.includes(null)).toBe(true);
  });
});

describe("고정 침범 원인(v0.15.1 — 스킵·경고 공통 표시)", () => {
  const fv = (name: string, n: number, mm: number) => ({ n, max_mm: mm, bead_vars: [{ name, bead: "b1", n, max_mm: mm }], node_idx: [1, 2] });
  it("변수별 묶음·문구(폭 = 해제 또는 블렌딩 축소, 깊이 = 범위 축소) · 셀 상태와 무관", () => {
    const rows = fixedViolRows([{ fixed_viol: fv("B1_W", 37, 0.8) }, { fixed_viol: fv("B1_W", 12, 0.5) }, { fixed_viol: fv("B2_D1", 3, 0.2) }, {}]);
    expect(rows.map((r) => [r.name, r.designs, r.nodes, r.maxMm])).toEqual([["B1_W", 2, 37, 0.8], ["B2_D1", 1, 3, 0.2]]);
    expect(fixedViolText(rows[0])).toBe("B1 W 를 바꾸면 고정 노드 37개가 최대 0.8 mm 움직임 → B1 W 해제 또는 블렌딩 반경 축소");
    expect(fixedViolText(rows[1])).toMatch(/^B2 D1 를 바꾸면 고정 노드 3개가 최대 0.2 mm 움직임 → B2 D1 범위 축소/);
  });

  it("OK 0개·모두 고정 침범 → 원인 비드·변수 줄", async () => {
    renderApp("/p/p-body/doe/doe-6", "power", (s) => {
      const rec = s.doe.recs.find((x) => x.out.id === "doe-6")!;
      rec.cells!.forEach((c) => {
        c.status = "SKIPPED_FIXED";
        c.code = "SELECT_FIXED_VIOLATION";
        c.fixed_viol = fv("B1_W", 37, 0.8);
      });
      rec.out.doe!.preview!.ok = 0;
    });
    const z = await screen.findByTestId("preview-zero-ok");
    expect(z.textContent).toMatch(/고정 침범 \d+/);
    expect(screen.getByTestId("fixed-viol-B1_W").textContent).toMatch(/B1 W 를 바꾸면 고정 노드 37개가 최대 0.8 mm 움직임 → B1 W 해제 또는 블렌딩 반경 축소/);
  });

  it("선택 저장 경고 SELECT_FIXED_IN_BEAD·BLEND 를 변수 표 옆에", async () => {
    renderApp("/p/p-body/doe/doe-5", "power", (s) => {
      const rec = s.doe.recs.find((x) => x.out.id === "doe-5")!;
      rec.sel!.derived.beads[0].warnings = [...(rec.sel!.derived.beads[0].warnings ?? []), { code: "SELECT_FIXED_IN_BLEND" }];
    });
    const w = await screen.findByTestId("vars-fixed-warn");
    fireEvent.click(within(w).getByRole("button", { name: /자세히/ }));
    expect(w.textContent).toMatch(/좌 경로 비드: 블렌딩 범위 안에 고정 노드가 있어/);
    expect(screen.getByTestId("param-B1_W")).toBeTruthy();
  });
});
