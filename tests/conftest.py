"""Shared deterministic random sources for Pigsty tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass
class ScriptedRng:
    """Random source replaying scripted draws in call order."""

    randoms: list[float] = field(default_factory=list)
    uniforms: list[float] = field(default_factory=list)
    choices: list[int] = field(default_factory=list)
    expovariates: list[float] = field(default_factory=list)

    def random(self) -> float:
        """Pop the next scripted tier draw."""
        return self.randoms.pop(0)

    def uniform(self, a: float, b: float) -> float:
        """Pop the next scripted uniform draw."""
        return self.uniforms.pop(0)

    def choice(self, seq: Sequence[int]) -> int:
        """Pop the next scripted sign draw."""
        return self.choices.pop(0)

    def expovariate(self, lambd: float) -> float:
        """Pop the next scripted exponential draw."""
        return self.expovariates.pop(0)
