"""FastAPI OpenAPI 를 docs/contracts/openapi_p1b.json 으로 덤프(프런트 계약 참조용).

사용: python scripts/dump_openapi.py [--check]   (--check: 파일이 최신이 아니면 종료코드 1)
DB 에 연결하지 않는다(엔진은 만들기만 함). 설정은 config/esl_platform.example.yaml.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "backend"), os.path.join(ROOT, "worker"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

OUT = os.path.join(ROOT, "docs", "contracts", "openapi_p1b.json")


def render() -> str:
    from sqlalchemy import create_engine

    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config

    cfg = load_config(os.path.join(ROOT, "config", "esl_platform.example.yaml"), environ={})
    if cfg.settings is None:
        raise SystemExit("예시 설정 스키마 오류: " + ", ".join(cfg.error_keys()))
    engine = create_engine("postgresql+psycopg://openapi@127.0.0.1:1/none")
    app = create_app(build_context(cfg, engine))
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        try:
            with open(OUT, encoding="utf-8") as fh:
                cur = fh.read()
        except OSError:
            cur = ""
        if cur != text:
            print(f"{OUT} 가 최신이 아닙니다: python scripts/dump_openapi.py", file=sys.stderr)
            return 1
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
