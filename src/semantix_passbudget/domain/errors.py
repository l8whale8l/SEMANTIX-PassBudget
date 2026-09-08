from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    code: str
    message: str
    scope: str
    field_paths: tuple[str, ...] = ()
    affected_branches: tuple[str, ...] = ()
    details: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "scope": self.scope,
            "field_paths": list(self.field_paths),
            "affected_branches": list(self.affected_branches),
            "details": dict(self.details),
        }


class DomainValidationError(ValueError):
    def __init__(self, detail: ErrorDetail) -> None:
        super().__init__(detail.message)
        self.detail = detail
