class HeroImageError(Exception):
    def __init__(self, code: str, detail: str, http_status: int = 502) -> None:
        self.code = code
        self.detail = detail
        self.http_status = http_status
        super().__init__(detail)
