"""② t* 확정 저장(API `PUT /tstar`·일괄 실행 자동 확정 공용, 계약 esl_run_all.md §4.2). `services/cases.put_tstar` 에서 옮김.

- `select_candidate(info, metric, frame_index)`: 지표 있음·후보에 있음·in_D 아님 아님(422 INVALID_METRIC·FRAME_NOT_CANDIDATE).
- `store(conn, case, tstar, auto, created_by, version)`: 지지 세트 있음 → KEPT, 없음 → auto_321 결과 OK 면 세트 생성(source
  auto) / BLOCKED 면 t* 만 저장. `auto` = (코어 결과, node_id, x0) — 호출자가 트랜잭션 밖에서 계산해 넘긴다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Connection

from .errors import conflict, unprocessable
from .repositories import cases as cases_repo
from .repositories.cases import VersionConflict


def select_candidate(info: dict[str, Any], metric: str, frame_index: int) -> dict[str, Any]:
    m = info["metrics"].get(metric)
    if m is None:
        raise unprocessable("INVALID_METRIC", f"지표 {metric} 가 없습니다 (가능: {list(info['metrics'])})")
    hit = next((c for c in m["candidates"] if c["frame_index"] == frame_index), None)
    if hit is not None and hit.get("in_D") is False:
        raise unprocessable("FRAME_NOT_CANDIDATE", f"frame {frame_index} 은 변위가 추출된 후보 프레임(D)이 "
                            "아닙니다", candidates=[c["frame_index"] for c in m["candidates"] if c.get("in_D")
                                                   is not False])
    if hit is None:
        raise unprocessable("FRAME_NOT_CANDIDATE", f"frame {frame_index} 은 {metric} 후보가 아닙니다",
                            candidates=[c["frame_index"] for c in m["candidates"]])
    return hit


def tstar_from(hit: dict[str, Any], metric: str, *, source: str = "user",
               confirmed: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {"metric": metric, "frame_index": hit["frame_index"], "time": hit["time"], "elem_id": hit["elem_id"],
           "value": hit["value"], "source": source}
    if confirmed:
        out["confirmed"] = confirmed
    return out


def store(conn: Connection, case: dict[str, Any], tstar: dict[str, Any], auto: tuple | None, *, created_by: str,
          version: int | None) -> dict[str, Any]:
    """Case 잠금(FOR UPDATE) 아래에서 호출. 반환 = 갱신된 Case. `tstar` 에 support_auto 를 채워 저장한다."""
    vals: dict[str, Any] = {}
    if case.get("current_support_set_id"):
        # 지지 세트 있음(자동·이전 수동 편집 모두) → 그대로(MR-D-3). 잠금 중 다른 사용자가 먼저 만든 경우도 여기
        sup = cases_repo.get_support_set(conn, case["current_support_set_id"])
        tstar["support_auto"] = {"status": "KEPT", "source": (sup or {}).get("source")}
    else:
        assert auto is not None, "지지 세트가 없으면 auto_321 결과가 필요합니다"
        res, nid, _x0 = auto
        if res["status"] == "OK":
            s = cases_repo.insert_support_set(
                conn, case_id=case["id"], node_ids=[int(nid[i]) for i in res["idx"]], dofs=list(res["dofs"]),
                source="auto", plane=res.get("plane"), created_by=created_by)
            vals["current_support_set_id"] = s["id"]
            tstar["support_auto"] = {"status": "OK", "mode": res["mode"], "checks": res.get("checks"),
                                     "rule_version": res.get("rule_version")}
        else:
            tstar["support_auto"] = {"status": "BLOCKED", "mode": res["mode"], "problems": res.get("problems") or [],
                                     "checks": res.get("checks"), "rule_version": res.get("rule_version")}
    try:
        return cases_repo.update_case(conn, case["id"], version, tstar=tstar, **vals)
    except VersionConflict:
        raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요") from None
