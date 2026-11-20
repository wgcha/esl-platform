"""옛 경로 재수출 심 — 본체는 ``esl/mech/jig.py``(v0.24.4 이동, 계약 esl_jig_case.md §4.1·D-0.24.4-JIG-10).

``from esl.doe import jig``·``import esl.doe.jig`` 모두 ``esl.mech.jig`` **모듈 객체 자체**를 돌려준다(``sys.modules`` 별칭 —
공개·비공개 이름·monkeypatch 가 같은 객체). 스터디 결과 바이트 동일(산술 불변, 골든 V-0244-JIG-1).
"""
from esl.mech.jig import _alias_module

_alias_module(__name__)
