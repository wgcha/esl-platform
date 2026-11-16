// V-RD-17·21(esl_redrop_bundle.md §7·§8): 재낙하 입력 받기 — 엔트리 선택칸 1개 + 버튼 1개.
// 판정은 서버 플래그(redrop_ok·redrop_entries[].ok)만 — 프런트에 시나리오 분기 없음. 화면 크기는 work/screens/redrop.png.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { doe } from "../api/doe";
import { redropDefault, REDROP_LABEL } from "../pages/doe/DoeStudy";
import { REDROP_BLOCKED_PLAN, REDROP_ENTRY_ARCHIVED, redropFlags } from "../mock/doedata";
import type { RedropEntryOut } from "../api/types";

const ent = (id: string, o: Partial<RedropEntryOut> = {}): RedropEntryOut => ({ entry_id: id, label: id, case_id: `c-${id}`, case_title: null, is_base: false, ok: true, blocked: null, ...o });

/** fetch 를 감싸 redrop 요청 URL 을 모으고, 필요하면 응답을 바꾼다 */
let urlsOf: string[] = [];
function spy(override?: (url: string) => Response | null) {
  const urls: string[] = [];
  const orig = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (u.includes("/redrop")) {
      urls.push(u);
      const o = override?.(u);
      if (o) return o;
    }
    return orig(input, init);
  }) as typeof fetch;
  return urls;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}) =>
  new Response(JSON.stringify({ detail: { code, message, ...extra } }), { status, headers: { "content-type": "application/json" } });
const btn = () => within(screen.getByTestId("redrop")).getByRole("button", { name: REDROP_LABEL }) as HTMLButtonElement;
const sel = () => screen.getByTestId("redrop-entry") as HTMLSelectElement;
async function open(id: string, pick = true, override?: (url: string) => Response | null) {
  const r = renderApp(`/p/p-body/doe/${id}`);
  urlsOf = spy(override);
  await screen.findByRole("table", { name: "순위표" });
  await screen.findByTestId("redrop");
  if (pick) fireEvent.click((await screen.findAllByTestId(/^rank-d\d{3}$/))[0]);
  return r;
}

describe("redropUrl·기본 선택(순수)", () => {
  it("redropUrl: entry_id 포함·인코딩", () => {
    expect(doe.redropUrl("s1", "d003", "le-1")).toMatch(/\/doe\/studies\/s1\/designs\/d003\/redrop\?entry_id=le-1$/);
    expect(doe.redropUrl("s1", "d 1", "a/b")).toMatch(/designs\/d%201\/redrop\?entry_id=a%2Fb$/);
  });
  it("redropDefault: is_base → 불가면 첫 ok → 없으면 null", () => {
    expect(redropDefault([ent("a"), ent("b", { is_base: true })])).toBe("b");
    expect(redropDefault([ent("a"), ent("b", { is_base: true, ok: false, blocked: "x" }), ent("c")])).toBe("a");
    expect(redropDefault([ent("a", { ok: false }), ent("b", { ok: false })])).toBeNull();
    expect(redropDefault(null)).toBeNull();
  });
  it("mock 계획 판정: ① same 만 가능, mesh·step·compare 는 전 행 불가 + 사유", () => {
    const o = (scenario: "same" | "mesh" | "compare") => ({ scenario, entry_ids: ["a", "b", "c"], inputs: {} });
    const ok = redropFlags(o("same"));
    expect(ok.redrop_ok).toBe(true);
    expect(ok.redrop_entries!.map((e) => [e.is_base, e.ok])).toEqual([[true, true], [false, true], [false, false]]);
    expect(ok.redrop_entries![2].blocked).toBe(REDROP_ENTRY_ARCHIVED);
    const no = redropFlags(o("mesh"));
    expect(no.redrop_ok).toBe(false);
    expect(no.redrop_blocked).toBe(REDROP_BLOCKED_PLAN);
    expect(no.redrop_entries!.every((e) => !e.ok && e.blocked === REDROP_BLOCKED_PLAN)).toBe(true);
    expect(redropFlags(o("same"), false).redrop_entries).toBeNull();
  });
});

describe("V-RD-17 버튼 활성·비활성·URL·오류", () => {
  it("안 미선택 → 비활성(사유), 안 선택 → 활성 + URL(entry_id)", async () => {
    await open("doe-1", false);
    const urls = urlsOf;
    expect(btn().disabled).toBe(true);
    expect(btn().closest(".primary-wrap")!.getAttribute("title")).toMatch(/안을 고르세요/);
    fireEvent.click((await screen.findAllByTestId(/^rank-d\d{3}$/))[0]);
    await waitFor(() => expect(btn().disabled).toBe(false));
    expect(btn().title).toMatch(/모핑 좌표/);
    fireEvent.click(btn());
    await waitFor(() => expect(urls.length).toBe(1));
    expect(urls[0]).toMatch(/\/doe\/studies\/doe-1\/designs\/d\d{3}\/redrop\?entry_id=/);
  });
  it("redrop_ok=false(compare 스터디) → 버튼 비활성 + redrop_blocked 툴팁, 선택칸은 모두 disabled", async () => {
    await open("doe-3");
    expect(btn().disabled).toBe(true);
    expect(btn().closest(".primary-wrap")!.getAttribute("title")).toBe(REDROP_BLOCKED_PLAN);
    expect([...sel().options].every((o) => o.disabled)).toBe(true);
  });
  it("409 REDROP_DESIGN_NOT_READY 서버 메시지를 그대로 표시", async () => {
    await open("doe-1", true, () => err(409, "REDROP_DESIGN_NOT_READY", "이 안은 평가가 끝나지 않아 재낙하 입력을 만들 수 없습니다.", { design_id: "d001", status: null }));
    await waitFor(() => expect(btn().disabled).toBe(false));
    fireEvent.click(btn());
    expect(await screen.findByText(/평가가 끝나지 않아/)).toBeTruthy();
  });
  it("413 → BundleButton 기존 안내(폴더 복사)", async () => {
    await open("doe-1", true, () => err(413, "BUNDLE_TOO_LARGE", "크기 초과", { size: 3_000_000_000, limit: 2_000_000_000 }));
    await waitFor(() => expect(btn().disabled).toBe(false));
    fireEvent.click(btn());
    expect(await screen.findByTestId("bundle-too-large")).toBeTruthy();
  });
});

describe("V-RD-21 엔트리 선택칸", () => {
  it("기본 = is_base(기준 표시), 불가 옵션 disabled + 사유 title, 바꾸면 URL 의 entry_id 가 바뀜", async () => {
    await open("doe-1");
    const urls = urlsOf;
    const opts = [...sel().options];
    expect(opts.length).toBeGreaterThanOrEqual(3);
    expect(opts[0].textContent).toMatch(/\(기준\)$/);
    expect(sel().value).toBe(opts[0].value);
    expect(opts[2].disabled).toBe(true);
    expect(opts[2].title).toBe(REDROP_ENTRY_ARCHIVED);
    expect(opts[1].disabled).toBe(false);
    await waitFor(() => expect(btn().disabled).toBe(false));
    fireEvent.click(btn());
    await waitFor(() => expect(urls.length).toBe(1));
    expect(urls[0]).toContain(`entry_id=${encodeURIComponent(opts[0].value)}`);
    fireEvent.change(sel(), { target: { value: opts[1].value } });
    await waitFor(() => expect(sel().value).toBe(opts[1].value));
    fireEvent.click(btn());
    await waitFor(() => expect(urls.length).toBe(2));
    expect(urls[1]).toContain(`entry_id=${encodeURIComponent(opts[1].value)}`);
    expect(urls[1]).not.toBe(urls[0]);
  });
});
