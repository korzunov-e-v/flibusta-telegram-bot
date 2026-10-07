import asyncio

import pytest

from src.bot.throttle import Throttle, Throttled


def test_exclusive_slot_rejects_parallel_operation() -> None:
    throttle = Throttle(0, exclusive=True)

    with throttle.slot(1):
        with pytest.raises(Throttled) as exc_info, throttle.slot(1):
            pass

        assert exc_info.value.busy

        with throttle.slot(2):  # другой пользователь не блокируется
            pass

    with throttle.slot(1):
        pass


def test_slot_released_on_error() -> None:
    throttle = Throttle(0, exclusive=True)

    with pytest.raises(RuntimeError), throttle.slot(1):
        raise RuntimeError

    with throttle.slot(1):
        pass


def test_min_interval() -> None:
    now = [100.0]
    throttle = Throttle(1.0, exclusive=True, clock=lambda: now[0])

    with throttle.slot(1):
        pass

    now[0] = 100.5
    with pytest.raises(Throttled) as exc_info, throttle.slot(1):
        pass

    assert not exc_info.value.busy

    # отказ не продлевает ожидание
    now[0] = 101.0
    with throttle.slot(1):
        pass


def test_non_exclusive_allows_parallel() -> None:
    now = [0.0]
    throttle = Throttle(0.5, exclusive=False, clock=lambda: now[0])

    with throttle.slot(1):
        now[0] = 1.0
        with throttle.slot(1):
            pass


async def test_concurrent_tasks_get_single_slot() -> None:
    throttle = Throttle(0, exclusive=True)
    started = 0

    async def operation() -> bool:
        nonlocal started

        try:
            with throttle.slot(1):
                started += 1
                await asyncio.sleep(0.01)
        except Throttled:
            return False

        return True

    results = await asyncio.gather(*(operation() for _ in range(5)))

    assert results.count(True) == 1
    assert started == 1


def test_prune_keeps_memory_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.bot.throttle._PRUNE_THRESHOLD", 10)
    now = [0.0]
    throttle = Throttle(1.0, exclusive=True, clock=lambda: now[0])

    for user_id in range(50):
        now[0] += 5
        with throttle.slot(user_id):
            pass

    assert len(throttle._last_start) <= 11
