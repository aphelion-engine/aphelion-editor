"""Explicit authentication strategies selected by each wire adapter."""
from dataclasses import dataclass, field


class NoAuth:
    def headers(self) -> dict[str, str]:
        return {}


@dataclass(repr=False)
class BearerAuth:
    secret: str = field(repr=False)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret}"} if self.secret else {}


@dataclass(repr=False)
class ApiKeyHeaderAuth:
    header: str
    secret: str = field(repr=False)

    def headers(self) -> dict[str, str]:
        return {self.header: self.secret} if self.secret else {}
