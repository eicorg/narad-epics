from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


class NaradValidationError(ValueError):
    def __init__(self, source: Path, issues: list[ValidationIssue]) -> None:
        self.source = source
        self.issues = tuple(issues)
        details = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(
            f"{source}: Narad description has {len(self.issues)} validation "
            f"error(s):\n{details}"
        )