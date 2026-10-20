"""시연 `init`: 시연 폴더(esl_root·inputs·state·logs·config), 합성 Case 입력, 시연 설정(dev_static, 127.0.0.1) 작성·검증."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo_common import (
    INPUT_NAME,
    PKG_ROOT,
    PROJECT_ID,
    UNSAFE,
    _log,
    add_code_paths,
    fwd,
    move_to_backup,
)

HEADER = ("# ESL 시연 모드 설정 — deploy/demo/demo_setup.py init 이 config/esl_platform.example.yaml 에서 생성.\n"
          "# 시연 전용(profile dev, auth dev_static, 127.0.0.1). 운영 설정으로 쓰지 않는다.\n")


def _yaml():
    import yaml

    return yaml


def demo_settings(root: Path, port: int) -> dict:
    """플랫폼 예시 설정(config/esl_platform.example.yaml)에서 시연 값만 바꾼다(스키마는 예시와 같음)."""
    yaml = _yaml()
    d = yaml.safe_load((PKG_ROOT / "config" / "esl_platform.example.yaml").read_text(encoding="utf-8"))
    d["profile"] = "dev"
    d["server"] = {"host": "127.0.0.1", "port": int(port), "base_path": "/esl"}
    d["auth"]["mode"] = "dev_static"
    d["auth"]["dev_static_principal"] = {"user_id": "demo-admin", "username": "demo", "display_name": "시연 관리자",
                                         "is_global_admin": True,
                                         "memberships": [{"project_id": PROJECT_ID, "role": "admin"}]}
    d["storage"] = {"esl_root": fwd(root / "esl_root"), "input_roots": [fwd(root / "inputs")], "spdm_roots": []}
    d["worker"]["state_dir"] = fwd(root / "state")
    d["worker"]["max_logical_cores"] = 4
    d["worker"]["max_memory_gb"] = 8
    d["core"] = {"config_path": "esl.yaml"}
    d["report"] = {"auto": True}
    d["library"] = {"config_path": "library.yaml"}
    return d


def write_companions(cfg_dir: Path) -> list[str]:
    """코어 설정(esl.yaml — 합성 변위는 float64라 disp_precision float64)·library.yaml·ista6.yaml. 없을 때만."""
    yaml = _yaml()
    out = []
    core = cfg_dir / "esl.yaml"
    if not core.is_file():
        text = (PKG_ROOT / "config" / "esl.example.yaml").read_text(encoding="utf-8")
        text = text.replace("disp_precision: float32", "disp_precision: float64")
        if (yaml.safe_load(text).get("extract") or {}).get("disp_precision") != "float64":
            raise SystemExit("코어 예시 설정에서 extract.disp_precision 을 찾지 못했습니다")
        core.write_text("# ESL 시연 코어 설정(config/esl.example.yaml + 합성 변위 float64)\n" + text, encoding="utf-8")
        out.append(str(core))
    for name, src in (("library.yaml", "library.example.yaml"), ("ista6.yaml", "ista6.yaml")):
        p = cfg_dir / name
        if not p.is_file():
            p.write_text((PKG_ROOT / "config" / src).read_text(encoding="utf-8"), encoding="utf-8")
            out.append(str(p))
    return out


def ensure_inputs(root: Path) -> dict:
    """합성 Case 입력(<시연 폴더>/inputs/demo_drop). 있으면 그대로(done.json 기준)."""
    d = root / "inputs" / INPUT_NAME
    rad, csv = d / "model_0000.rad", d / "csv"
    if rad.is_file() and (csv / "done.json").is_file():
        return {"rad": str(rad), "csv": str(csv), "created": False}
    add_code_paths()
    import demo_synth

    _log("합성 Case 입력 생성(코어 쉘 솔버, 수십 초)")
    r = demo_synth.build(str(d))
    return {"rad": r["rad"], "csv": r["csv"], "created": True}


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if UNSAFE.search(str(root)):
        raise SystemExit(f"시연 폴더 경로에 공백·특수문자를 쓸 수 없습니다: {root}")
    for sub in ("esl_root", "inputs", "state", "config", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    yaml = _yaml()
    cfg = root / "config" / "esl_platform.yaml"
    text = HEADER + yaml.safe_dump(demo_settings(root, args.port), allow_unicode=True, sort_keys=False)
    if cfg.is_file() and cfg.read_text(encoding="utf-8") != text:
        moved = move_to_backup(root, cfg)
        _log(f"기존 설정을 _backup으로 옮겼습니다: {moved}")
    if not cfg.is_file():
        cfg.write_text(text, encoding="utf-8")
    write_companions(cfg.parent)
    frontend = ""
    if args.frontend:
        fr = Path(args.frontend).resolve()
        if not (fr / "index.html").is_file():
            raise SystemExit(f"프런트 빌드 폴더에 index.html이 없습니다: {fr}")
        frontend = str(fr)
    (root / "state" / "demo.json").write_text(json.dumps({"frontend": frontend, "port": int(args.port)}), encoding="utf-8")
    add_code_paths()
    from esl_platform.core.config import load_config

    lc = load_config(str(cfg), environ={})
    if not lc.ok:
        raise SystemExit("시연 설정 검증 실패: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues))
    inputs = ensure_inputs(root)
    _log(f"설정: {cfg}")
    print(json.dumps({"config": str(cfg), "esl_root": str(root / "esl_root"), **inputs}, ensure_ascii=False))
    return 0
