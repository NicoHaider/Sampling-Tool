"""Tests für `core.cancellation` – Token + OperationCancelled.

Sprint 17: Cooperative-Cancellation-Primitives für Long-Running-Operations.
Diese Tests gehören in die Unit-Schicht – kein Qt, keine I/O.
"""

from __future__ import annotations

import threading

import pytest

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled


class TestCancellationToken:
    def test_initial_not_set(self) -> None:
        token = CancellationToken()
        assert token.is_set() is False

    def test_set_changes_state(self) -> None:
        token = CancellationToken()
        token.set()
        assert token.is_set() is True

    def test_double_set_idempotent(self) -> None:
        token = CancellationToken()
        token.set()
        token.set()
        assert token.is_set() is True

    def test_thread_safe_set_from_other_thread(self) -> None:
        """Das Token muss thread-safe zwischen UI- und Worker-Thread sein."""
        token = CancellationToken()

        def setter() -> None:
            token.set()

        t = threading.Thread(target=setter)
        t.start()
        t.join()
        assert token.is_set() is True

    def test_raise_if_cancelled_no_op_when_unset(self) -> None:
        token = CancellationToken()
        token.raise_if_cancelled()  # darf NICHT werfen

    def test_raise_if_cancelled_throws_when_set(self) -> None:
        token = CancellationToken()
        token.set()
        with pytest.raises(OperationCancelled):
            token.raise_if_cancelled()


class TestOperationCancelled:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(OperationCancelled, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(OperationCancelled):
            raise OperationCancelled("test")
