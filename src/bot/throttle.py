import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

HEAVY_MIN_INTERVAL = 1.0
LIGHT_MIN_INTERVAL = 0.5

_PRUNE_THRESHOLD = 10_000


class Throttled(Exception):
    def __init__(self, *, busy: bool) -> None:
        super().__init__("busy" if busy else "too fast")
        self.busy = busy


class Throttle:
    """Ограничение на пользователя: минимальный интервал между операциями и,
    при exclusive=True, не больше одной операции одновременно.

    Состояние живёт в памяти процесса. Между проверкой и занятием слота нет
    await, поэтому при concurrent_updates гонок в пределах event loop нет.
    """

    def __init__(
        self,
        min_interval: float,
        *,
        exclusive: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval
        self._exclusive = exclusive
        self._clock = clock
        self._busy: set[int] = set()
        self._last_start: dict[int, float] = {}

    def _prune(self, now: float) -> None:
        if len(self._last_start) < _PRUNE_THRESHOLD:
            return

        self._last_start = {
            user_id: started
            for user_id, started in self._last_start.items()
            if now - started < self._min_interval or user_id in self._busy
        }

    @contextmanager
    def slot(self, user_id: int) -> Iterator[None]:
        if user_id in self._busy:
            raise Throttled(busy=True)

        now = self._clock()
        last = self._last_start.get(user_id)

        if last is not None and now - last < self._min_interval:
            raise Throttled(busy=False)

        self._prune(now)
        self._last_start[user_id] = now

        if self._exclusive:
            self._busy.add(user_id)

        try:
            yield
        finally:
            self._busy.discard(user_id)


# поиск и скачивание
heavy = Throttle(HEAVY_MIN_INTERVAL, exclusive=True)
# карточка книги и аннотация: страница книги кешируется в flib
light = Throttle(LIGHT_MIN_INTERVAL, exclusive=False)
