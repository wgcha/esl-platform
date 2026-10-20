"""시연 백엔드·워커 프로세스 확인·종료(demo_setup up/down 공용). psutil은 시연 venv에 있다(requirements.lock)."""

from __future__ import annotations

from pathlib import Path


def _proc_alive(info: dict) -> bool:
    try:
        import psutil

        p = psutil.Process(info["pid"])
        return abs(p.create_time() - info["create_time"]) < 1.0 and p.status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001
        return False


def _stop_tree(pid: int, create_time: float | None = None) -> bool:
    """프로세스와 자식 트리 종료(terminate → 15초 → kill). create_time이 다르면(PID 재사용) 건드리지 않는다."""
    import psutil

    try:
        p = psutil.Process(pid)
        if create_time is not None and abs(p.create_time() - create_time) >= 1.0:
            return False
        tree = [*p.children(recursive=True), p]
    except psutil.Error:
        return False
    for q in tree:
        try:
            q.terminate()
        except psutil.Error:
            pass
    _gone, alive = psutil.wait_procs(tree, timeout=15)
    for q in alive:
        try:
            q.kill()
        except psutil.Error:
            pass
    return True


def _stop_procs(procs: dict[str, dict]) -> list[str]:
    stopped = []
    for name in ("worker", "backend"):  # 워커 먼저(코어 자식 프로세스 포함 트리)
        info = procs.get(name)
        if info and _proc_alive(info) and _stop_tree(info["pid"], info["create_time"]):
            stopped.append(name)
    return stopped


def _orphan_backend(port: int, root: Path) -> int | None:
    """port를 듣고 있는 프로세스가 이 시연 폴더의 백엔드(cwd=root, esl_service.py backend)면 그 PID. 다른 프로그램은 건드리지 않는다."""
    import psutil

    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.Error, OSError):
        return None
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr or c.laddr.port != port or not c.pid:
            continue
        try:
            p = psutil.Process(c.pid)
            cmd = " ".join(p.cmdline())
            if "esl_service.py" in cmd and "backend" in cmd and Path(p.cwd()).resolve() == root:
                return c.pid
        except (psutil.Error, OSError):
            continue
    return None
