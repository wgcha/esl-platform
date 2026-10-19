"""CLI: ``python -m esl run --config cfg.yaml --rad X_0000.rad --results <csv_dir> --out <case_dir>
[--stage extract|tstar|esl|validate|export|all] [--frame N] [--support-nodes id1,id2,id3]``.

종료코드 0 = 성공(검증 FAIL 이어도 계산 자체는 성공), 1 = 오류. 오류는 stderr 에 ``CODE: message`` 한 줄,
출력 폴더를 쓸 수 있으면 run.json 에도 기록.
"""
from __future__ import annotations

import argparse
import sys

from esl.errors import EslError
from esl.pipeline import STAGES, run


class _Parser(argparse.ArgumentParser):
    def error(self, message):            # argparse 기본(종료코드 2) 대신 계약 형식
        raise EslError("INPUT_INVALID", f"인자 오류: {message}")


def _parse_ids(text: str) -> list[int]:
    try:
        ids = [int(s) for s in text.replace(" ", "").split(",") if s]
    except ValueError:
        raise EslError("INPUT_INVALID", f"--support-nodes 는 콤마로 구분한 정수 노드 ID (값 {text!r})") from None
    if len(set(ids)) < 3:
        raise EslError("INPUT_INVALID", f"--support-nodes 는 서로 다른 노드 ID 3개 이상 (값 {text!r})")
    return ids


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m esl", description="ESL(등가정적하중) 계산 코어")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    r = sub.add_parser("run", help="파이프라인 실행")
    r.add_argument("--config", default=None, help="설정 YAML (없으면 env ESL_CONFIG)")
    r.add_argument("--rad", required=True, help="Radioss starter _0000.rad")
    r.add_argument("--results", required=True, help="TCL 출력 CSV 폴더")
    r.add_argument("--out", required=True, help="Case 출력 폴더")
    r.add_argument("--stage", default="all", choices=list(STAGES) + ["all"])
    r.add_argument("--frame", type=int, default=None, help="t* 수동 지정(frame_index, 후보 안에서만)")
    r.add_argument("--support-nodes", default=None, help="3-2-1 후보 노드 ID (콤마, 3개 이상)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        a = build_parser().parse_args(argv)
        sn = _parse_ids(a.support_nodes) if a.support_nodes else None
        run(config_path=a.config, rad=a.rad, results=a.results, out=a.out, stage=a.stage, frame=a.frame,
            support_nodes=sn, argv=argv)
        return 0
    except EslError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except SystemExit as exc:            # --help
        return int(exc.code or 0)
    except Exception as exc:             # noqa: BLE001 — 한 줄 보고(run.json 에는 pipeline 이 기록)
        msg = str(exc).replace("\n", " ")
        print(f"INTERNAL_ERROR: {type(exc).__name__}: {msg}", file=sys.stderr)
        return 1
