"""상태·대기열·경로 확인 서비스."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from esl_worker import core_adapter

from ... import __version__
from ...core.auth import Principal
from ...core.inputs import results_files
from ...core.paths import check_input_path
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import workers as workers_repo
from ..context import AppContext
from .common import job_out


def status(ctx: AppContext) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        hb = workers_repo.latest(conn)
    w = ctx.settings.worker
    online = False
    last = None
    limiter = None
    if hb:
        last = hb["last_seen_at"]
        limiter = hb.get("limiter")
        online = hb["age"].total_seconds() <= 3 * w.heartbeat_interval_s
    try:
        core_ver = core_adapter.core_version()
    except core_adapter.CoreError:
        core_ver = "unavailable"
    return {
        "config": {"ok": ctx.config.ok, "errors": ctx.config.errors()},
        "worker": {"online": online, "last_seen_at": last, "limiter": limiter},
        "tools": core_adapter.solver_backends(ctx.config.core),
        "version": __version__,
        "core_version": core_ver,
    }


def queue(ctx: AppContext) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        out: dict[str, Any] = {}
        for lane in ("SLOT", "LIGHT"):
            running, queued = jobs_repo.queue_lane(conn, lane)
            out[lane] = {"running": job_out(conn, running) if running else None,
                         "queued": [job_out(conn, j) for j in queued]}
    return {"running": out["SLOT"]["running"], "queued": out["SLOT"]["queued"], "light": out["LIGHT"]}


# ---------------------------------------------------------------- 경로 확인
_TITLE_WS = re.compile(r"\s+")


def norm_title(t: str) -> str:
    return _TITLE_WS.sub(" ", str(t).strip()).lower()


def match_parts(parts: list[dict], title: str, mode: str) -> list[dict]:
    if mode == "exact":
        want = _TITLE_WS.sub(" ", title.strip())
        return [p for p in parts if _TITLE_WS.sub(" ", str(p.get("title", "")).strip()) == want]
    want = norm_title(title)
    return [p for p in parts if norm_title(p.get("title", "")) == want]


def read_done(results_dir: str) -> tuple[dict[str, Any] | None, list[str]]:
    p = os.path.join(results_dir, "done.json")
    if not os.path.isfile(p):
        return None, ["done.json 이 없습니다(TCL 추출이 끝나지 않았거나 다른 폴더)"]
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, [f"done.json 을 읽을 수 없습니다: {exc}"]
    if not isinstance(d, dict):
        return None, ["done.json 형식 오류"]
    return d, []


def _count_frames(results_dir: str) -> int | None:
    p = os.path.join(results_dir, "frames.csv")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return max(sum(1 for line in fh if line.strip()) - 1, 0)


def inspect_results(path: str) -> dict[str, Any]:
    problems: list[str] = []
    done, probs = read_done(path)
    problems += probs
    files = [{"name": k, **v} for k, v in results_files(path).items()]
    names = {f["name"] for f in files}
    for need in ("frames.csv", "model.csv"):
        if need not in names:
            problems.append(f"{need} 이 없습니다")
    done_out = None
    n_frames = None
    if done is not None:
        if not done.get("ok"):
            problems.append("done.json ok=false (TCL 추출 실패)")
        done_out = {"ok": bool(done.get("ok")), "part_id": done.get("part_id"), "part_spec": done.get("part_spec"),
                    "candidate_frames": done.get("candidate_frames"), "hot_k": done.get("hot_k"),
                    "warnings": list(done.get("warnings") or []), "h3d": done.get("h3d")}
        n_frames = done.get("n_frames")
    if n_frames is None:
        n_frames = _count_frames(path)
    return {"normalized_path": path, "ok": not problems, "problems": problems, "done": done_out,
            "n_frames": n_frames, "files": files}


def inspect_rad(ctx: AppContext, path: str, part_title: str | None = None) -> dict[str, Any]:
    core = ctx.config.core or {}
    cc = core.get("case") or {}
    depth = int(cc.get("rad_include_max_depth") or 8)
    pmap = cc.get("include_path_map") or None
    title = part_title or cc.get("part_title") or ""
    mode = cc.get("part_title_match") or "exact_ci"
    problems: list[str] = []
    parts: list[dict] = []
    includes: list[dict] = []
    try:
        parts = core_adapter.list_parts(path, depth, pmap)
    except core_adapter.CoreError as exc:
        problems.append(f"{exc.code}: {exc.message}")
    try:
        includes = [{"path": p, "ok": os.path.isfile(p)} for p in core_adapter.scan_includes(path, depth, pmap)]
    except core_adapter.CoreError as exc:
        problems.append(f"{exc.code}: {exc.message}")
    for inc in includes:
        if not inc["ok"]:
            problems.append(f"include 파일이 없습니다: {inc['path']}")
    hits = match_parts(parts, title, mode) if title else []
    target = hits[0] if len(hits) == 1 else None
    if parts and title and not hits:
        problems.append(f"PART_NOT_FOUND: /PART title '{title}' 없음")
    elif len(hits) > 1:
        problems.append(f"PART_AMBIGUOUS: /PART title '{title}' {len(hits)}개")
    return {"normalized_path": path, "ok": not problems, "problems": problems, "parts": parts,
            "includes": includes, "part_title": title, "target_part": target}


def inspect(ctx: AppContext, principal: Principal, purpose: str, raw: str) -> dict[str, Any]:
    p = check_input_path(ctx.settings, raw, purpose)
    if purpose == "RAD":
        return inspect_rad(ctx, p)
    return inspect_results(p)
