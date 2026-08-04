from typing import Protocol, TypeAlias

ConfigValue: TypeAlias = str | int | float | bool | None

class AstrBotConfig(Protocol):
    def get(self, key: str, default: ConfigValue = None) -> ConfigValue: ...
