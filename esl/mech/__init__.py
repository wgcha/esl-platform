"""역학 계층: 쉘 FE 솔버, 강체 제거(Kabsch), 3-2-1 지지 선택, 등가변형률, t* 탐색.

계약: docs/contracts/esl_core.md §4.
"""
from esl.mech import kabsch, shell, strain, supports, tstar
from esl.mech.shell import ShellModel

__all__ = ["ShellModel", "kabsch", "shell", "strain", "supports", "tstar"]
