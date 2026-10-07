"""Explicit registries reject configuration mistakes instead of silently changing models."""


class Registry[T]:
    def __init__(self):
        self._implementations: dict[str, T] = {}

    def register(self, version: str, implementation: T) -> None:
        if version in self._implementations:
            raise ValueError(f"Implementation already registered: {version}")
        self._implementations[version] = implementation

    def resolve(self, version: str) -> T:
        try:
            return self._implementations[version]
        except KeyError as exc:
            raise ValueError(f"Unknown implementation: {version}") from exc
