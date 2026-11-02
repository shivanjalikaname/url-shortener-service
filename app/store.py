"""Storage backend.

In-memory and thread-safe, which is enough for a demo and for tests. The
interface is kept narrow so it can be swapped for Redis or Postgres without
touching the API layer.
"""

import threading


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def put(self, code: str, url: str) -> None:
        with self._lock:
            self._data[code] = url

    def get(self, code: str) -> str | None:
        with self._lock:
            return self._data.get(code)

    def exists(self, code: str) -> bool:
        with self._lock:
            return code in self._data

    def ping(self) -> bool:
        return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
