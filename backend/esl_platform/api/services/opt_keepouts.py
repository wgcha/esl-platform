"""비드 금지 영역 세트(계약 esl_opt_run.md OR-D-11·12, §5.1·§7.5): 저장·불러오기.

- 키: S2 = template_id, S1 = topo_sha256(전역, 모델당 1세트). 낙관적 잠금 ``version``(갱신 시 필수, 다르면 409
  VERSION_CONFLICT). 세트와 함께 저장 시점 대상 frame(a_range·b_range)을 저장하고, 불러올 때 현재 frame 과
  ``opt_run.keepout.frame_warn_mm`` 이상 다르면 경고(``esl.opt.keepout.frame_shift_warning``).
- 사각형 검사 = 코어 ``esl.opt.keepout.validate_rects``(개수·이름 길이·기준 모서리·X·Y ≥ 0·가로·세로 > 0) + 대상 경계
  밖에 완전히 있으면 422 KEEPOUT_INVALID. 일부만 밖이면 저장(실행 때 잘라서 적용·경고).
- 권한: 조회 = 템플릿 세트는 ACTIVE 로그인 누구나, 모델(topo) 세트는 그 모델 ESL 이 있는 프로젝트 조회 권한.
  저장 = 템플릿 세트는 아무 프로젝트 power, 모델 세트는 그 모델 ESL 이 있는 프로젝트의 power.
- 실행은 생성 시점 화면 값을 ``opt_runs.design.keepout`` 에 스냅샷한다(이후 세트 수정은 과거 실행에 영향 없음).
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from ...core.auth import Principal
from ...core.config import opt_settings
from ...core.db.tables import library_entries
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.repositories import opt as opt_repo
from ...core.repositories.cases import VersionConflict
from ..context import AppContext
from .common import require_config_ok
from .opt_templates import load_template, template_meta


def kcfg(ctx: AppContext) -> dict[str, Any]:
    return opt_settings(ctx.settings)["keepout"]


def validate_keepout(ctx: AppContext, rects: list[dict[str, Any]], auto: dict[str, Any] | None,
                     frame: dict[str, Any] | None) -> dict[str, Any]:
    """사각형·자동 설정 검사 → {rects, auto}(정규화). frame 이 있으면 경계 밖 완전 이탈 거부."""
    from ...core.opt_core import EslError
    from ...core.opt_core import keepout

    kc = kcfg(ctx)
    try:
        out = keepout.validate_rects([{k: v for k, v in r.items() if v is not None} for r in rects], kc)
    except EslError as exc:
        raise unprocessable("KEEPOUT_INVALID", exc.message) from None
    warns: list[str] = []
    if frame is not None:
        for r in out:
            bb = keepout.rect_bounds(r, frame)
            if bb["outside"]:
                raise unprocessable("KEEPOUT_INVALID", f"사각형 '{r['name']}' 이 대상 경계 밖에 완전히 있습니다",
                                    rect=r["name"])
            if bb["clipped"]:
                warns.append(f"사각형 '{r['name']}' 이 대상 경계를 벗어나 잘라서 적용됩니다")
    a = {"hole": True, "edge": True}
    a.update({k: bool(v) for k, v in (auto or {}).items() if k in ("hole", "edge")})
    return {"rects": out, "auto": a, "warnings": warns}


def model_entries(conn, topo: str) -> list[dict[str, Any]]:
    rows = conn.execute(select(library_entries.c.id, library_entries.c.project_id, library_entries.c.dir_rel)
                        .where(and_(library_entries.c.topo_sha256 == topo, library_entries.c.status == "ACTIVE"))
                        .order_by(library_entries.c.registered_at.desc(), library_entries.c.id)).all()
    return [dict(r._mapping) for r in rows]


def entry_frame(ctx: AppContext, e: dict[str, Any]) -> dict[str, Any] | None:
    """항목 entry.json 의 frame(raw 를 읽지 않음). 없으면 None."""
    from .library import entry_folder

    try:
        with open(os.path.join(entry_folder(ctx, e), "entry.json"), encoding="utf-8") as fh:
            fr = json.load(fh).get("frame")
    except (OSError, ValueError, DomainError):
        return None
    return fr if isinstance(fr, dict) and "a_range" in fr else None


def _model_frame(ctx: AppContext, ents: list[dict[str, Any]]) -> dict[str, Any] | None:
    for e in ents:
        fr = entry_frame(ctx, e)
        if fr is not None:
            return fr
    return None


def _set_out(k: dict[str, Any], frame_now: dict[str, Any] | None, ctx: AppContext) -> dict[str, Any]:
    from ...core.opt_core import keepout

    warns = []
    if frame_now is not None:
        w = keepout.frame_shift_warning(k.get("frame"), frame_now, kcfg(ctx))
        if w:
            warns.append(w)
    return {"id": k["id"], "key": {"template_id": k.get("template_id"), "topo_sha256": k.get("topo_sha256")},
            "version": k["version"], "rects": list(k.get("rects") or []), "auto": dict(k.get("auto") or {}),
            "frame": dict(k.get("frame") or {}), "updated_by_name": k["updated_by_name"],
            "updated_at": k["updated_at"], "warnings": warns}


def get_set(ctx: AppContext, principal: Principal, template_id: str | None, topo: str | None) -> dict[str, Any]:
    if (template_id is None) == (topo is None):
        raise unprocessable("INVALID_PARAMS", "template_id 와 topo 중 정확히 하나가 필요합니다")
    with ctx.engine.connect() as conn:
        if template_id is not None:
            t = load_template(conn, template_id)
            frame_now = template_meta(ctx, t)["frame"]
            k = opt_repo.get_keepout(conn, template_id=template_id)
        else:
            ents = model_entries(conn, topo)
            if not principal.is_global_admin and not any(principal.role(e["project_id"]) for e in ents):
                raise not_found("KEEPOUT_NOT_FOUND", "이 모델의 금지 영역 세트가 없습니다")
            k = opt_repo.get_keepout(conn, topo_sha256=topo)
            frame_now = _model_frame(ctx, ents) if k is not None else None
    if k is None:
        raise not_found("KEEPOUT_NOT_FOUND", "저장된 금지 영역 세트가 없습니다(빈 세트로 시작)")
    return _set_out(k, frame_now, ctx)


def put_set(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_config_ok(ctx)
    with ctx.engine.connect() as conn:
        if body.template_id is not None:
            t = load_template(conn, body.template_id)
            if not (principal.is_global_admin or any(r in ("power", "admin") for r in principal.roles.values())):
                raise forbidden("금지 영역 세트 저장은 power 이상만 할 수 있습니다")
            if t["status"] != "ACTIVE":
                raise unprocessable("TEMPLATE_ARCHIVED", "보관된 템플릿입니다")
            frame = template_meta(ctx, t)["frame"]
        else:
            ents = model_entries(conn, body.topo_sha256)
            if not ents:
                raise not_found("ENTRY_NOT_FOUND", "이 모델(topo_sha256)의 활성 라이브러리 항목이 없습니다")
            mine = [e for e in ents if principal.can_execute(e["project_id"])]
            if not mine:
                raise forbidden("이 모델의 ESL 이 있는 프로젝트에서 power 이상만 저장할 수 있습니다")
            frame = _model_frame(ctx, mine) or _model_frame(ctx, ents)
    v = validate_keepout(ctx, [r.model_dump() for r in body.rects], body.auto.model_dump(), frame)
    fsave = {"a_range": list(frame["a_range"]), "b_range": list(frame["b_range"])} if frame else {}
    key = {"template_id": body.template_id} if body.template_id is not None else {"topo_sha256": body.topo_sha256}
    with ctx.engine.begin() as conn:
        cur = opt_repo.get_keepout(conn, for_update=True, **key)
        try:
            if cur is None:
                if body.version is not None:
                    raise conflict("VERSION_CONFLICT", "저장된 세트가 없습니다(다른 사용자가 지웠거나 키가 다름) — 새로 고치세요")
                with conn.begin_nested():
                    k = opt_repo.insert_keepout(conn, id=str(uuid.uuid4()), rects=v["rects"], auto=v["auto"],
                                                frame=fsave, updated_by=principal.user_id,
                                                updated_by_name=principal.display_name, **key)
            else:
                if body.version is None:
                    raise conflict("VERSION_CONFLICT", "이미 저장된 세트가 있습니다 — 불러온 뒤 version 과 함께 저장하세요",
                                   version=cur["version"])
                k = opt_repo.update_keepout(conn, cur["id"], body.version, rects=v["rects"], auto=v["auto"],
                                            frame=fsave, updated_by=principal.user_id,
                                            updated_by_name=principal.display_name)
        except (VersionConflict, IntegrityError):
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 저장했습니다 — 새로 고친 뒤 다시 저장하세요") from None
    out = _set_out(k, frame, ctx)
    out["warnings"] = v["warnings"] + out["warnings"]
    return out
