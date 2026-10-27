class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ModelError(Exception):
    """Safe diagnostics only: never include provider bodies, prompts, or credentials."""

    def __init__(self, category: str, *, upstream_status: int | None = None):
        super().__init__(category)
        self.category = category
        self.upstream_status = upstream_status
