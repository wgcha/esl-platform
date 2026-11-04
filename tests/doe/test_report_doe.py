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


def test_compare_report_mesh_options():
    """V-C2-11(esl_compare_mesh_options.md §9): 형상 표 출처·메시 방식 열, 메시 방식 상세(파트 ID·충실도·요소 크기·h·배율·면·
    요소 배수·CAD 첫 오류), 수렴 점검 표, 머리 경고, 한계 절, HTML 이스케이프."""
    q = {"fail_elems": 0, "fail_ratio": 0.0, "warn_elems": 0}
    fid = {"hausdorff_mm": 0.12, "max_dev_mm": 0.1, "p95_mm": 0.05, "area_ratio": 1.001, "deflection_mm": 0.05,
           "warn_mm": 0.3, "fail_mm": 1.5, "over_warn": False}
    shapes = [
        {"id": "d000", "name": "기준", "source": "step", "mesh_method": "cad", "status": "READY", "n_elems": 100,
         "quad_ratio": 1.0, "quality": q, "edge_median_mm": 3.0},
        {"id": "d001", "name": "<script>x</script>", "source": "mesh", "mesh_method": "mesh_input", "part_id": 12,
         "status": "READY", "n_elems": 90, "quad_ratio": 1.0, "quality": q, "edge_median_mm": 2.9},
        {"id": "d002", "name": "폴백", "source": "step", "mesh_method": "fallback", "status": "READY", "n_elems": 120,
         "quad_ratio": 0.95, "quality": q, "fidelity": fid, "cad_error": {"code": "MESH_FAILED", "message": "<b>면 3</b>"}},
        {"id": "d003", "name": "세분화", "source": "step", "mesh_method": "refine", "status": "READY", "n_elems": 140,
         "quad_ratio": 1.0, "quality": q,
         "refine": {"kind": "local", "h_mm": 1.5, "factor": 0.5, "base_h_mm": 3.0, "elem_ratio_ref": 1.4,
                    "faces": [{"bbox_key": "0,0,0,1,1,1", "ring": 0}] * 3}},
    ]
    bias = {"d003": {"h_mm": 2.1, "delta_max": 0.031, "tol": 0.01, "over_tol": True,
                     "per_esl": [{"entry_id": "E0", "delta": 0.031}, {"entry_id": "E1", "delta": -0.01}],
                     "improvement_same_h": 0.05}}
    ctx = {"study": {"id": "C1", "title": "t", "scenario": "compare"}, "shapes": shapes, "profile": {"size_mm": 3.0},
           "esl": [{"entry_id": "E0", "label": "씬<0>"}, {"entry_id": "E1", "label": "씬 1"}], "refine_bias": bias,
           "warnings": ["COMPARE_MESH_METHOD_MIXED: 형상마다 메시 방식이 달라 <섞임>", "MESH_REFINED: d003 세분화 …"],
           "limits_extra": ["세분화 형상은 요소 크기가 기준 메시와 달라 메시 의존 오차를 포함합니다 — 수렴 점검 δ 참고"],
           "sources": load_method_sources()}
    html = rd.render_compare(ctx)
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;면 3&lt;/b&gt;" in html
    for s in ("출처", "메시 방식", "메시 입력", "재메시(폴백)", "세분화(국부 ×0.5 · 1.5 mm · 면 3 · 요소 ×1.40)",
              "0.120 mm · 면적비 1.001 (원 CAD 대비 ≤ 0.170 mm)", "파트 ID", "CAD 첫 오류", "MESH_FAILED"):
        assert s in html, s
    assert "수렴 점검" in html and "3.10 %" in html and "초과 ⚠" in html and "씬&lt;0&gt; +3.10 %" in html
    assert "같은 h 기준 +5.0 %" in html
    assert "<b>COMPARE_MESH_METHOD_MIXED</b>" in html and "&lt;섞임&gt;" in html and "<b>MESH_REFINED</b>" in html
    assert "메시 의존 오차" in html
    # 정상 STEP(모두 cad)만이면 상세·수렴 표 없음
    html0 = rd.render_compare({**ctx, "shapes": shapes[:1], "refine_bias": {}, "warnings": [], "limits_extra": []})
    assert "<h3>메시 방식</h3>" not in html0 and "수렴 점검" not in html0 and "<td>CAD</td>" in html0
