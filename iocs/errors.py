"""Validation errors with source locations for Narad input documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One validation failure and its YAML-oriented location."""

    location: str
    message: str

    def __str__(self) -> str:
        """Format the issue for CLI and aggregate error output."""

        return f"{self.location}: {self.message}"


class NaradValidationError(ValueError):
    """Aggregate all validation issues found in one Narad document."""

    def __init__(self, source: Path, issues: list[ValidationIssue]) -> None:
        """Build an error that preserves structured issues for callers."""

        self.source = source
        self.issues = tuple(issues)
        details = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(
            f"{source}: Narad description has {len(self.issues)} validation "
            f"error(s):\n{details}"
        )