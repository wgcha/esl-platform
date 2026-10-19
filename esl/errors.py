class EslError(Exception):
    """계약 실패 코드(docs/contracts/esl.md §4.3, esl_core.md §2)를 가진 오류."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
