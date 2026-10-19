"""V-P1B-2 시험용 코어 대체 대상: pid 를 남기고 오래 잠든다(취소로만 끝남). 자식 프로세스에서 import 된다."""

import os
import time


def run(spec, echo):
    pid_path = os.path.join(os.path.dirname(spec["log_path"]), "slow_core.pid")
    with open(pid_path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    echo("[slow_core] 대기 시작")
    time.sleep(600)
