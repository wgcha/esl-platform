"""시연 `seed`: 합성 입력으로 Case 2개를 만든다(있으면 그대로).

- demo_new  "입력만": ①부터 화면에서 직접 실행해 보는 Case.
- demo_done "①~⑥ 완료"(--prerun, 워커가 떠 있어야 함): API로 추출(①②) → 지지점 자동(③) → ESL(④) → 검증(⑤) → 내보내기(⑥)를 돌려
  화면에서 바로 결과(t* 곡선·F_eq·검증·겹쳐보기·보고서)를 볼 수 있게 한다. 이미 있으면 다시 돌리지 않는다.
시연 설정은 auth dev_static(시연 관리자)이라 토큰이 없고, 쓰기 요청에는 X-ESL-Request: 1 헤더만 붙인다.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from demo_common import CASE_DONE, CASE_NEW, CSRF, INPUT_NAME, PROJECT_ID, _log, local_urlopen

TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")


def _api(url: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url.rstrip("/") + "/esl/api" + path, data=data, method=method)
    if method not in ("GET", "HEAD"):
        req.add_header(*CSRF)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with local_urlopen(req, timeout=60) as r:  # 127.0.0.1 시연 백엔드 — 프록시 미사용
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw or "null")
        except ValueError:
            return e.code, raw


def _must(code_body: tuple[int, object], want: int, what: str) -> object:
    code, body = code_body
    if code != want:
        raise SystemExit(f"{what} 실패({code}): {body}")
    return body


def _wait_job(url: str, job_id: str, timeout: float) -> dict:
    end = time.time() + timeout
    while True:
        j = _must(_api(url, "GET", f"/jobs/{job_id}"), 200, "작업 조회")
        if j["state"] in TERMINAL:  # type: ignore[index]
            return j  # type: ignore[return-value]
        if time.time() > end:
            raise SystemExit(f"작업 {job_id} 이(가) {timeout:g}초 안에 끝나지 않았습니다(상태 {j['state']}) — 워커 로그 확인")  # type: ignore[index]
        time.sleep(1.0)


def _run_job(url: str, cid: str, job_type: str, params: dict | None, timeout: float) -> dict:
    job = _must(_api(url, "POST", f"/cases/{cid}/jobs", {"job_type": job_type, "params": params or {}}), 201, job_type)
    j = _wait_job(url, job["id"], timeout)  # type: ignore[index]
    if j["state"] != "SUCCEEDED":
        raise SystemExit(f"{job_type} 실패: {j.get('failure_code')} {j.get('failure_message') or ''}")
    _log(f"{job_type} 완료")
    return j


def prerun(url: str, cid: str, timeout: float) -> None:
    """①~⑥ 완주(test_p1b_e2e 와 같은 API 순서)."""
    _run_job(url, cid, "CASE_EXTRACT", None, timeout)
    sug = _must(_api(url, "POST", f"/cases/{cid}/support-sets/suggest", {}), 200, "지지점 제안")
    _must(_api(url, "POST", f"/cases/{cid}/support-sets", {"node_ids": sug["node_ids"]}), 201, "지지점 저장")  # type: ignore[index]
    _run_job(url, cid, "ESL_SOLVE", None, timeout)
    case = _must(_api(url, "GET", f"/cases/{cid}"), 200, "Case 조회")
    rid = case["current_esl_run_id"]  # type: ignore[index]
    _run_job(url, cid, "VALIDATE", {"esl_run_id": rid}, timeout)
    _run_job(url, cid, "EXPORT", {"esl_run_id": rid, "targets": ["radioss_inc", "fem", "csv"]}, timeout)


def cmd_seed(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    rad = root / "inputs" / INPUT_NAME / "model_0000.rad"
    csv = root / "inputs" / INPUT_NAME / "csv"
    if not rad.is_file():
        raise SystemExit(f"합성 입력이 없습니다: {rad} — init을 먼저 실행하세요")
    cases = _must(_api(args.url, "GET", f"/cases?project_id={PROJECT_ID}"), 200, "Case 목록 조회")
    by_folder = {c.get("folder_name"): c for c in cases}  # type: ignore[union-attr]
    out = {}
    for (folder, title), run_all in ((CASE_NEW, False), (CASE_DONE, bool(args.prerun))):
        c = by_folder.get(folder)
        if c is None:
            c = _must(_api(args.url, "POST", "/cases", {"project_id": PROJECT_ID, "folder_name": folder, "title": title,
                                                        "rad_path": str(rad), "results_dir": str(csv)}), 201, f"Case 생성({folder})")
            _log(f"시연 Case 생성: {title}")
            if run_all:
                _log("①~⑥ 미리 실행(추출 → 지지점 → ESL → 검증 → 내보내기, 1~2분)")
                prerun(args.url, c["id"], float(args.timeout))  # type: ignore[index]
        else:
            _log(f"시연 Case 있음: {folder}")
        out[folder] = c["id"]  # type: ignore[index]
    print(json.dumps({"cases": out, "rad": str(rad), "results_dir": str(csv)}, ensure_ascii=False))
    return 0
