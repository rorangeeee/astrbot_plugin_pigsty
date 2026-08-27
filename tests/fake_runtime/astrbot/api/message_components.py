"""Test-only AstrBot message components."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class At:
    """Minimal public mention component."""

    qq: int | str
    name: str | None = None
