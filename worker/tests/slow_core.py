"""V-P1B-2 시험용 코어 대체 대상: pid 를 남기고 오래 잠든다(취소로만 끝남). 자식 프로세스에서 import 된다.

``slow_select_grid``(v0.15.0 select BD_GRID): 단계가 ``bd_select_grid`` 일 때만 pid 를 남기고 환경변수
``ESL_TEST_SLOW_GRID_S`` 초 잠든 뒤 실제 코어(esl_worker.child.run_core)로 넘긴다 — 다른 단계는 그대로 실제 코어."""

import os
import time


def run(spec, echo):
    pid_path = os.path.join(os.path.dirname(spec["log_path"]), "slow_core.pid")
    with open(pid_path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    echo("[slow_core] 대기 시작")
    time.sleep(600)


def slow_select_grid(spec, echo):
    from esl_worker.child import run_core

    if spec.get("stage") == "bd_select_grid":
        pid_path = os.path.join(os.path.dirname(spec["log_path"]), "slow_grid.pid")
        with open(pid_path, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        echo("[slow_select_grid] 대기 시작")
        time.sleep(float(os.environ.get("ESL_TEST_SLOW_GRID_S") or 600))
        echo("[slow_select_grid] 대기 끝")
    return run_core(spec, echo)
