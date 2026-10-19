"""ESL 라이브러리 · 종합분석 · 비드 최적화 덱 · 보고서 (계약 docs/contracts/esl_p2_library.md, P2-a/b/c 코어).

모듈(모두 순수 함수, 입출력은 numpy 배열·dict·파일 경로):

- ``scene_meta``     경로·파일명 → 씬 메타(정규식 named group) + ISTA 6 면 번호 해석 (§2)
- ``normalize``      PCA 평면 정규화 좌표계(ξ,η,n) + 격자 셀 합력·합모멘트 요약 (§1)
- ``entry``          Case 출력 폴더 → LibraryEntry(dict + npz) (§1)
- ``mapping``        셀 합력·합모멘트 → 대상 메시 절점력(셀당 6 제약 최소노름) (§3)
- ``normalization``  인치 간 하중 크기 정규화 none|mass|inch2 (§0 Q3)
- ``analysis``       포락·SVD·k-medoids 대표 씬·통계 뷰 (§3, §8)
- ``optdeck``        OptiStruct DTPG 비드 최적화 덱 (§4)
- ``report_analysis`` 자체 완결 HTML 보고서 (§5)
- ``store``          파일 기반 라이브러리 인덱스(<root>/library/index.jsonl) + 백업 규칙
- ``cli``            ``python -m esl.library register|analyze|optdeck|report|list``
"""
