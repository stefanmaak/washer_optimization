class NamePool:
    """Fixed set of protocol names on the BlueWasher, one per process that can run in parallel.

    A name is held for the whole lifetime of a process, so the protocol of a running process is never overwritten.
    """

    def __init__(self, names: list[str]):
        if len(set(names)) != len(names):
            raise ValueError(f"names must be unique: {names}")
        self._free = list(names)
        self._in_use: set[str] = set()

    def acquire(self) -> str:
        if not self._free:
            raise RuntimeError(f"all protocol names are in use: {sorted(self._in_use)}")
        name = self._free.pop(0)
        self._in_use.add(name)
        return name

    def release(self, name: str) -> None:
        if name not in self._in_use:
            raise ValueError(f"{name} is not in use")
        self._in_use.remove(name)
        self._free.append(name)

    @property
    def in_use(self) -> set[str]:
        return set(self._in_use)
