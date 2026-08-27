from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class At:
    qq: int | str
    name: str | None = None
