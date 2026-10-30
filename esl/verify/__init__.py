"""검증 낙하(계약 esl_scx_relay.md 기능 B, SR6) 코어 — 숫자·파일만, 플랫폼·네트워크 없음.

- ``patch``  : 원 Case 입력 사본 세트의 ``/NODE`` 좌표를 노드 ID 기준으로 고쳐 쓴다(SR-D-13). 바뀐 파일만 새로 쓰고 원본은 읽기만.
- ``compare``: 원 낙하 vs 검증 낙하 추출(01_extract) 비교 — 변위·변형률 지표, ESL 선형 예측 비와 방향 일치(SR-D-16, §9.3).
  PASS/FAIL 판정 없음(정보 표시).
"""

from esl.verify.compare import compare, compare_csv  # noqa: F401
from esl.verify.patch import patch_node_files  # noqa: F401

__all__ = ["patch_node_files", "compare", "compare_csv"]
