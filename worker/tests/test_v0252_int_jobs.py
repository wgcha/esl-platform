"""v0.25.2 통합 — 독립 검증 결함 1(계약 esl_tstar_manual_jig_force.md §15.4 INT-12): ④ 준비 요약 형상 행 double_sheet.

워커 BD_PREP_REGISTER(``register._register_compare_prep``)의 형상 행 화이트리스트에 ``double_sheet`` 가 없어 실서버에서는 준비 요약에서
빠졌고(화면 "앞뒷면 두 장?" 배지가 안 뜸), 코어 시험(prep/compare.json)만으로는 못 잡았다. 실제 코어 ④ 준비(합성 #96 꼴 두 장 형상) →
실제 워커 등록 → API GET 응답의 형상 행 = 프런트 fixture(``frontend/src/mock/fixtures/prep_double_sheet_v0252.json`` — vitest 가 이
fixture 로 배지를 확인)와 같음.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from doe_support import api
from esl_test_support import REPO

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_jig_grid as G  # noqa: E402
import synth_tm as T  # noqa: E402

FIXTURE = REPO / "frontend" / "src" / "mock" / "fixtures" / "prep_double_sheet_v0252.json"
KEYS = ("id", "status", "source", "double_sheet")


def _prep_world(root: Path) -> str:
    doe, out, _A = G.cmp_world(str(root), shapes=(("d001", {"mesh": T.issue96_shape()}),),
                               rank=G.rank_snap(grid=True, force=True))
    for st in ("bd_input", "bd_mesh0", "bd_loads"):
        G.run_stage(out, doe, st)
    return out


def test_int12_prep_shape_row_double_sheet_through_worker(client, engine, esl_root, tmp_path):
    from esl_platform.core.repositories import doe as doe_repo
    from esl_worker import register as rg

    out = _prep_world(tmp_path / "w")
    core_rows = {r["id"]: r for r in json.loads((Path(out) / "prep" / "compare.json").read_text(encoding="utf-8"))["shapes"]}
    assert core_rows["d001"]["double_sheet"]["frac"] >= 0.9 and "double_sheet" not in core_rows["d000"]
    sid = "s-int12"
    ddir = Path(esl_root) / "_doe" / sid
    shutil.copytree(Path(out) / "prep", ddir / "prep")
    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario="compare", title="두 장", entry_ids=["e1"], inputs={},
                              phase="PREP", dir_rel=f"_doe/{sid}", created_by="u-power", created_by_name="파워")
        rg.register_doe_prep(c, {"bead_doe_id": sid, "job_type": "DOE_PREP"}, None, str(ddir))
    r = api(client, "GET", f"/doe/studies/{sid}")
    assert r.status_code == 200, r.text
    prep = r.json()["prep"]
    rows = {x["id"]: x for x in prep["shapes"]}
    ds = rows["d001"]["double_sheet"]
    assert ds == core_rows["d001"]["double_sheet"] and ds["frac"] >= 0.9 and abs(ds["gap_mm"] - 2.0) < 1e-6
    assert "double_sheet" not in rows["d000"]                                    # 경고 안 난 행 = 키 없음(옛 요약 모양)
    assert any(w["code"] == "SHAPE_DOUBLE_SHEET" for w in prep["warnings"])
    want = json.loads(FIXTURE.read_text(encoding="utf-8"))
    got = [{k: x[k] for k in KEYS if k in x} for x in prep["shapes"]]
    assert got == want["shapes"], "프런트 fixture 와 API 형상 행이 다름 — fixture 를 이 응답으로 갱신"


def test_int12_old_summary_rows_unchanged():
    """double_sheet 가 없는 행 = 키 없음(route·mq 와 같은 규칙) — 화이트리스트 순서 시험(route·mq 끝)은 그대로."""
    from esl_worker import register as rg

    assert "double_sheet" in rg.COMPARE_SHAPE_KEYS and rg.COMPARE_SHAPE_KEYS[-2:] == ("route", "mq")
