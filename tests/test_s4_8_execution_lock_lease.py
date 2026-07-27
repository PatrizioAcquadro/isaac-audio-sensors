from __future__ import annotations

import asyncio
import contextvars
import multiprocessing
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import s4_8


def _require_execution_lock_in_child(repo_root: str, outcome) -> None:
    try:
        s4_8._require_execution_lock(Path(repo_root))
    except BaseException as exc:
        outcome.put((type(exc).__name__, str(exc)))
    else:
        outcome.put(("result", "unexpected success"))


def _execution_lock_owner(repo_root: str, ready, release) -> None:
    root = Path(repo_root)
    with s4_8._exclusive_execution_lock(
        root / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    ):
        ready.set()
        release.wait(timeout=30)


def test_fabricated_lease_fails_before_contract_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    lock_path.parent.mkdir(parents=True)
    contract_loaded = False

    def forbidden_contract(_root: Path):
        nonlocal contract_loaded
        contract_loaded = True
        raise AssertionError("contract loaded before execution lease validation")

    monkeypatch.setattr(s4_8, "load_contract", forbidden_contract)
    with lock_path.open("a+b") as stream:
        fabricated = s4_8._ExecutionLockLease(
            repo_root=tmp_path.resolve(),
            lock_path=lock_path.resolve(),
            stream=stream,
        )
        token = s4_8._ACTIVE_EXECUTION_LEASE.set(fabricated)
        try:
            with pytest.raises(
                s4_8.S48Error,
                match="requires the authorized execution lock",
            ):
                s4_8._consume_grant_once(
                    tmp_path,
                    source_commit="a" * 40,
                    event_time_utc="2030-01-01T00:00:00Z",
                    recovery_context={},
                )
        finally:
            s4_8._ACTIVE_EXECUTION_LEASE.reset(token)
    assert not contract_loaded


def test_copied_context_observes_revoked_lease_after_release(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    with s4_8._exclusive_execution_lock(lock_path):
        copied = contextvars.copy_context()
        copied.run(s4_8._require_execution_lock, tmp_path)

    with pytest.raises(
        s4_8.S48Error,
        match="requires the authorized execution lock",
    ):
        copied.run(s4_8._require_execution_lock, tmp_path)


def test_async_inherited_context_observes_revoked_lease_after_release(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        released = asyncio.Event()

        async def inherited_context() -> None:
            await released.wait()
            s4_8._require_execution_lock(tmp_path)

        lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
        with s4_8._exclusive_execution_lock(lock_path):
            task = asyncio.create_task(inherited_context())
            await asyncio.sleep(0)
        released.set()
        with pytest.raises(
            s4_8.S48Error,
            match="requires the authorized execution lock",
        ):
            await task

    asyncio.run(exercise())


def test_stale_context_fails_while_another_process_owns_lock(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    with s4_8._exclusive_execution_lock(lock_path):
        copied = contextvars.copy_context()

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    owner = context.Process(
        target=_execution_lock_owner,
        args=(tmp_path.as_posix(), ready, release),
    )
    owner.start()
    assert ready.wait(timeout=15)
    try:
        with pytest.raises(
            s4_8.S48Error,
            match="requires the authorized execution lock",
        ):
            copied.run(s4_8._require_execution_lock, tmp_path)
    finally:
        release.set()
        owner.join(timeout=15)
    assert not owner.is_alive()


@pytest.mark.parametrize("start_method", ["fork", "spawn"])
def test_process_cannot_inherit_execution_lease(
    tmp_path: Path,
    start_method: str,
) -> None:
    context = multiprocessing.get_context(start_method)
    outcome = context.Queue()
    lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    with s4_8._exclusive_execution_lock(lock_path):
        child = context.Process(
            target=_require_execution_lock_in_child,
            args=(tmp_path.as_posix(), outcome),
        )
        child.start()
        child.join(timeout=15)
        assert not child.is_alive()
        result = outcome.get(timeout=5)

    assert result[0] == "S48Error"
    assert "requires the authorized execution lock" in result[1]


def test_legitimate_live_owner_holds_valid_execution_lease(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    with s4_8._exclusive_execution_lock(lock_path):
        s4_8._require_execution_lock(tmp_path)


def test_live_lease_rejects_replaced_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / s4_8.AUTHORIZED_EXECUTION_LOCK_PATH
    displaced = lock_path.with_suffix(".displaced")
    with s4_8._exclusive_execution_lock(lock_path):
        lock_path.replace(displaced)
        lock_path.touch()
        with pytest.raises(
            s4_8.S48Error,
            match="requires the authorized execution lock",
        ):
            s4_8._require_execution_lock(tmp_path)
