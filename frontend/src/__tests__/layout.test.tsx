import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RadInspectView } from "../components/PathInspect";

describe("레이아웃: 긴 표는 내부 스크롤 컨테이너 안", () => {
  it("rad 파트 표(57행)는 table-wrap scroll 안에 있다", () => {
    const parts = Array.from({ length: 57 }, (_, i) => ({ id: i + 1, title: `p${i}`, n_elems: 10 }));
    const { container } = render(<RadInspectView r={{ normalized_path: "x.rad", includes: [], part_title: "p0", target_part: null, ok: true, problems: [], parts }} partTitle="p0" />);
    const wrap = container.querySelector(".table-wrap.scroll");
    expect(wrap).not.toBeNull();
    expect(wrap!.querySelectorAll("tbody tr").length).toBe(57);
  });
});
