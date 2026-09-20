from __future__ import annotations

from threading import Event, Thread
from time import sleep

import pytest

from bankocr.task import (
    InvalidTaskTransitionError,
    Task,
    TaskCancelledError,
    TaskExecutor,
    TaskManager,
    TaskStatus,
)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task: Task, control) -> str:
        self.calls.append(task.task_id)
        control.checkpoint()
        return f"done:{task.payload}"


class CooperativeExecutor:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[str] = []

    def execute(self, task: Task, control) -> str:
        self.calls.append(task.task_id)
        self.started.set()
        while not self.release.is_set():
            control.checkpoint()
            sleep(0.005)
        return f"done:{task.payload}"


def test_real_fake_executor_is_injected_through_task_executor_protocol() -> None:
    executor = RecordingExecutor()

    assert isinstance(executor, TaskExecutor)

    manager = TaskManager(executor)
    task_id = manager.submit(Task("one", "payload"))

    result = manager.run_next()

    assert result is not None
    assert result.task_id == task_id
    assert result.status is TaskStatus.COMPLETED
    assert result.result == "done:payload"


def test_tasks_run_in_fifo_order_with_a_real_fake_workload() -> None:
    executor = RecordingExecutor()
    manager = TaskManager(executor)
    manager.submit(Task("first", 1))
    manager.submit(Task("second", 2))
    manager.submit(Task("third", 3))

    results = manager.run_all()

    assert [result.task_id for result in results] == ["first", "second", "third"]
    assert executor.calls == ["first", "second", "third"]


def test_pause_and_resume_change_a_queued_task_without_running_it() -> None:
    executor = RecordingExecutor()
    manager = TaskManager(executor)
    task_id = manager.submit(Task("paused", "payload"))

    paused = manager.pause(task_id)

    assert paused.status is TaskStatus.PAUSED
    assert manager.run_next() is None
    assert executor.calls == []

    resumed = manager.resume(task_id)

    assert resumed.status is TaskStatus.QUEUED
    completed = manager.run_next()
    assert completed is not None
    assert completed.status is TaskStatus.COMPLETED


def test_paused_head_does_not_reorder_the_fifo_order_of_runnable_tasks() -> None:
    executor = RecordingExecutor()
    manager = TaskManager(executor)
    first_id = manager.submit(Task("first", 1))
    second_id = manager.submit(Task("second", 2))
    manager.pause(first_id)

    result = manager.run_next()

    assert result is not None
    assert result.task_id == second_id
    assert manager.status(first_id) is TaskStatus.PAUSED


def test_running_task_can_pause_and_resume_cooperatively() -> None:
    executor = CooperativeExecutor()
    manager = TaskManager(executor)
    task_id = manager.submit(Task("cooperative", "payload"))
    worker = Thread(target=manager.run_next)

    worker.start()
    assert executor.started.wait(timeout=1)

    paused = manager.pause(task_id)
    assert paused.status is TaskStatus.PAUSED
    assert worker.is_alive()

    resumed = manager.resume(task_id)
    assert resumed.status is TaskStatus.RUNNING
    executor.release.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert manager.status(task_id) is TaskStatus.COMPLETED


def test_cancelled_task_cannot_resume_and_is_not_executed_again() -> None:
    executor = RecordingExecutor()
    manager = TaskManager(executor)
    task_id = manager.submit(Task("cancelled", "payload"))

    cancelled = manager.cancel(task_id)

    assert cancelled.status is TaskStatus.CANCELLED
    assert manager.run_next() is None
    assert executor.calls == []
    with pytest.raises(InvalidTaskTransitionError):
        manager.resume(task_id)
    assert manager.status(task_id) is TaskStatus.CANCELLED


def test_running_task_can_be_cancelled_by_a_cooperative_fake_workload() -> None:
    executor = CooperativeExecutor()
    manager = TaskManager(executor)
    task_id = manager.submit(Task("running-cancel", "payload"))
    worker = Thread(target=manager.run_next)

    worker.start()
    assert executor.started.wait(timeout=1)
    cancelled = manager.cancel(task_id)
    worker.join(timeout=1)

    assert cancelled.status is TaskStatus.CANCELLED
    assert not worker.is_alive()
    assert manager.status(task_id) is TaskStatus.CANCELLED


def test_restart_appends_a_new_attempt_and_requeues_the_task() -> None:
    executor = RecordingExecutor()
    manager = TaskManager(executor)
    task_id = manager.submit(Task("retryable", "payload"))
    manager.cancel(task_id)

    restarted = manager.restart(task_id)

    assert restarted.status is TaskStatus.QUEUED
    assert restarted.attempt_number == 2
    assert [attempt.number for attempt in restarted.attempts] == [1, 2]
    assert restarted.attempts[0].status is TaskStatus.CANCELLED
    assert restarted.attempts[1].status is TaskStatus.QUEUED

    completed = manager.run_next()
    assert completed is not None
    assert completed.status is TaskStatus.COMPLETED
    assert completed.attempt_number == 2
    assert len(completed.attempts) == 2


def test_invalid_transition_fails_closed_without_mutating_the_task() -> None:
    executor = RecordingExecutor()
    manager = TaskManager(executor)
    task_id = manager.submit(Task("invalid", "payload"))
    before = manager.get(task_id)

    with pytest.raises(InvalidTaskTransitionError):
        manager.resume(task_id)
    with pytest.raises(InvalidTaskTransitionError):
        manager.restart(task_id)

    assert manager.get(task_id) == before

    manager.run_next()
    completed = manager.get(task_id)
    with pytest.raises(InvalidTaskTransitionError):
        manager.pause(task_id)
    with pytest.raises(InvalidTaskTransitionError):
        manager.cancel(task_id)
    with pytest.raises(InvalidTaskTransitionError):
        manager.resume(task_id)
    assert manager.get(task_id) == completed


def test_executor_cancellation_error_is_recorded_as_cancelled_not_failed() -> None:
    class SelfCancellingExecutor:
        def execute(self, task: Task, control):
            control.cancel()
            control.checkpoint()
            raise AssertionError("checkpoint should have raised")

    manager = TaskManager(SelfCancellingExecutor())
    task_id = manager.submit(Task("self-cancel", None))

    result = manager.run_next()

    assert result is not None
    assert result.status is TaskStatus.CANCELLED
    assert isinstance(result.error, TaskCancelledError)
