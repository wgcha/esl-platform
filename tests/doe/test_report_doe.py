"""보고서 HTML(§11): 자체 완결·이스케이프·방법·출처·한계 절, 민감도 null 사유, 평면도 SVG."""
from esl.doe import load_method_sources
from esl.doe import report_doe as rd


def test_report_escape_and_sections(tmp_path):
    ctx = {"study": {"id": "D1", "title": "<script>x</script>", "scenario": "mesh", "entry_ids": ["E1"]},
           "inputs": {"step": {"file_name": "a&b.step", "sha256": "f" * 64}, "part_title": "chassis rear",
                      "entries": [{"entry_id": "E1", "label": "<b>", "case": "c"}]},
           "versions": {"paicad": "0.14.0"},
           "params": [{"name": "CR_BEAD_D_1", "type": "D", "nominal": 4.0, "feasible": [2, 6]}],
           "spec": {"method": "lhs", "n": 4, "seed": 1, "params": [{"name": "CR_BEAD_D_1", "lo": 3, "hi": 5}]},
           "matrix_sha256": "a" * 64, "n_designs": 5,
           "preview": {"counts": {"ok": 3, "collision": 1}, "cells": [{"id": "d004", "state": "SKIPPED_COLLISION",
                                                                     "code": "GEOM_FEATURE_COLLISION"}]},
           "result": {"C_ref": 2.0, "baseline": {"umax": 1.0}, "n_ok": 1, "ranking": [
               {"rank": 1, "id": "d001", "score": 0.9, "improvement": 0.1, "worst_entry_id": "E1", "umax": 1.0,
                "epsmax": 0.001, "values": {"CR_BEAD_D_1": 4.5}, "noise": True, "warnings_n": 0}],
               "sensitivity": {"null": True, "reason": "SENSITIVITY_TOO_FEW"}, "noise_floor": 0.02},
           "boundary": {"warnings": [{"code": "BOUNDARY_FASTENER_FAR", "label": "A RBE2#0", "d_mm": 12.0,
                                      "limit_mm": 10.0}], "info": []},
           "plan": {"frame": {"a_range": [0, 100], "b_range": [0, 50]}, "outline": [[0, 0], [100, 0], [100, 50], [0, 50]],
                    "holes": [], "beads": [], "fixed": [{"label": "B 구멍 1", "kind": "HOLE", "a": 10, "b": 10}],
                    "a_points": [{"label": "A RBE2#0", "a": 22, "b": 10}], "load_points": [],
                    "links": [{"from": "A RBE2#0", "to": "B 구멍 1", "d_mm": 12.0, "warn": True}]},
           "best": {"id": "d001", "values": {"CR_BEAD_D_1": 4.5}, "files": ["values.json"]},
           "sources": load_method_sources()}
    html = rd.render(ctx)
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html and "a&amp;b.step" in html
    for s in ("1. 입력", "4. 순위", "5. 파라미터 민감도", "6. 경계 매핑 경고", "8. 방법·출처", "9. 한계", "잡음 이내",
              "McKay", "class=\"lk\"", "충돌 스킵"):
        assert s in html, s
    assert "http://" not in html.split("<style>")[0]
    p = rd.write(str(tmp_path / "r.html"), ctx)
    assert open(p, encoding="utf-8").read() == html
    ctx["result"]["sensitivity"] = {"null": False, "r2": 0.9, "params": [{"name": "CR_BEAD_D_1", "src": -0.8,
                                                                          "spearman": -0.7}]}
    assert "<rect" in rd.render(ctx)
