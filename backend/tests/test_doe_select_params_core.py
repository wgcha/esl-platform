"""백엔드 ``doe_select.params_table``(저장된 derived 요약 JSON) == 코어 ``bead_select.params_table``(Derived 객체) 동일성.

백엔드는 메시·배열 없이 DB 요약만 가지므로 코어 함수를 직접 부를 수 없다(코어는 Derived 객체 — 메시 재계산 필요) →
같은 표(→ 같은 matrix_sha256)를 시험으로 고정한다. test_doe_select_api 는 코어 대역(fake)을 쓰므로 별도 파일(실제 코어)."""
from __future__ import annotations

import json
import sys

import numpy as np


def test_params_table_matches_core():
    """합성 비드 메시(tests/doe/synth_bead) 기본·단 묶음·사용자 고정 층·바닥 고정 노드(기본 체크 해제)·열린 경계(W 없음)."""
    from esl.doe import bead_select as bs
    from esl.doe import settings as doe_settings
    from esl_platform.api.services import doe_select
    from esl_test_support import REPO

    sys.path.insert(0, str(REPO / "tests" / "doe"))
    try:
        import synth_bead as sb
    finally:
        sys.path.remove(str(REPO / "tests" / "doe"))
    cfg = doe_settings({"bead_doe": {"enabled": True}})
    g = sb.generate(10.0)
    m = g["mesh"]
    nid = m["node_id"]
    ring = {int(x) for x in g["fixed_groups"][0]}
    touch = np.array([any(c >= 0 and int(nid[c]) in ring for c in row) for row in m["conn"]])
    s_user = sb.selection(g, blend_mm=24.0)
    s_user["fixed_user"] = sb.elemset(m, touch)
    floor = np.where(g["label"] == "b1t1")[0][:3]
    go = sb.generate(10.0, open_end=True)
    cases = [(g, sb.selection(g), g["fixed_ids"]), (g, sb.selection(g, links=[[1, 2]]), g["fixed_ids"]),
             (g, s_user, g["fixed_ids"]),
             (g, sb.selection(g, links=[[1, 2]]), np.concatenate([g["fixed_ids"], nid[m["conn"][floor][:, 0]]])),
             (go, sb.selection(go), go["fixed_ids"])]
    seen_off, seen_no_w = False, False
    # v0.16.1 SR-D-8: 기본 warn 정책은 비드 안 고정 노드가 있어도 체크 해제 안 함 → skip 정책도 함께 대조(체크 해제 분기)
    skip = doe_settings({"bead_doe": {"enabled": True, "select": {"fixed_policy": "skip"}}})
    for cc in (cfg, skip):
        for gg, sel, fx in cases:
            norm = bs.normalize_input(sel, cc)
            D = bs.derive_obj(gg["mesh"], norm, cc, fixed_node_ids=fx)
            core = bs.params_table(D, cc)
            for fig in (True, False):
                doc = {"input": norm, "derived": json.loads(json.dumps(D.summary(with_figures=fig)))}
                assert doe_select.params_table(doc, cc)["params"] == core
            if cc is cfg:
                assert all(r["use_default"] for r in core)
            seen_off |= any(not r["use_default"] for r in core)
            seen_no_w |= not any(r["name"] == "B1_W" for r in core)
    assert seen_off and seen_no_w                                       # 체크 해제(skip)·W 없음 분기까지 대조
