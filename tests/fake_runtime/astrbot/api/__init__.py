"""Test-only AstrBot API configuration type."""

from typing import TypeAlias

ConfigValue: TypeAlias = str | int | float | bool | list[str] | tuple[str, ...] | None


class AstrBotConfig(dict[str, ConfigValue]):
    """Small dict-backed configuration used by adapter smoke tests."""
