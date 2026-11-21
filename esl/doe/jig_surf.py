"""옛 경로 재수출 심 — 본체는 ``esl/rad/surface.py``(v0.24.4 이동, 계약 esl_jig_case.md §4.1·D-0.24.4-JIG-10).

``from esl.doe import jig_surf``·``import esl.doe.jig_surf`` 모두 ``esl.rad.surface`` **모듈 객체 자체**를 돌려준다
(``sys.modules`` 별칭 — 같은 객체).
"""
from esl.rad.surface import _alias_module

_alias_module(__name__)
