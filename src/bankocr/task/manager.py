"""A small, dependency-free, cooperative task manager."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
from threading import Condition, RLock
from typing import Protocol, runtime_checkable
from uuid import uuid4


class TaskStatus(str, Enum):
    """Lifecycle states exposed by :class:`TaskManager`."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CANCELED = "cancelled"


class InvalidTaskTransitionError(RuntimeError):
    """Raised when an operation is not valid for the current task state."""


class UnknownTaskError(KeyError):
    """Raised when a task id is not known to a manager."""


class TaskCancelledError(Exception):
    """Raised at a cooperative checkpoint after cancellation was requested."""


@dataclass(frozen=True, slots=True)
class Task:
    """Immutable work item passed to an injected executor."""

    task_id: str
    payload: object = None

    def __post_init__(self) -> None:
        if not self.task_id or not self.task_id.strip():
            raise ValueError("task_id must not be empty")


class TaskControl:
    """Cooperative controls available to a running executor.

    A workload that wants pause/cancel to take effect while it is running must
    call :meth:`checkpoint` periodically.  The manager itself remains usable
    for ordinary synchronous executors as well.
    """

    def __init__(self) -> None:
        self._condition = Condition()
        self._pause_requested = False
        self._cancel_requested = False

    @property
    def pause_requested(self) -> bool:
        with self._condition:
            return self._pause_requested

    @property
    def cancel_requested(self) -> bool:
        with self._condition:
            return self._cancel_requested

    def checkpoint(self) -> None:
        """Wait while paused and raise once cancellation is requested."""

        with self._condition:
            while self._pause_requested and not self._cancel_requested:
                self._condition.wait()
            if self._cancel_requested:
                raise TaskCancelledError("task cancellation requested")

    def pause(self) -> None:
        """Request a cooperative pause from inside a workload."""

        with self._condition:
            self._pause_requested = True

    def resume(self) -> None:
        """Release a cooperative pause."""

        with self._condition:
            self._pause_requested = False
            self._condition.notify_all()

    def cancel(self) -> None:
        """Request cancellation and wake a workload at a checkpoint."""

        with self._condition:
            self._cancel_requested = True
            self._condition.notify_all()


@runtime_checkable
class TaskExecutor(Protocol):
    """Executor boundary injected into :class:`TaskManager`."""

    def execute(self, task: Task, control: TaskControl) -> object:
        """Execute one task, using ``control`` for cooperative lifecycle work."""


@dataclass(frozen=True, slots=True)
class TaskAttempt:
    """Observable record for one execution attempt."""

    number: int
    attempt_id: str
    status: TaskStatus
    result: object = None
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """Immutable public view of a task and its attempt history."""

    task_id: str
    task: Task
    status: TaskStatus
    attempt_number: int
    attempts: tuple[TaskAttempt, ...]
    result: object = None
    error: BaseException | None = None


@dataclass
class _TaskState:
    task: Task
    attempts: list[TaskAttempt]
    control: TaskControl
    active: bool = False


class TaskManager:
    """FIFO task queue with fail-closed lifecycle transitions.

    Execution is synchronous from the caller's point of view: ``run_next``
    executes one item and ``run_all`` drains runnable items.  A caller may run
    ``run_next`` in a worker thread when it needs to issue pause/cancel from
    another thread; the injected workload must use ``checkpoint`` for those
    requests to interrupt it cooperatively.
    """

    _PAUSABLE = frozenset({TaskStatus.QUEUED, TaskStatus.RUNNING})
    _CANCELLABLE = frozenset(
        {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED}
    )
    _RESTARTABLE = frozenset(
        {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    )

    def __init__(self, executor: TaskExecutor) -> None:
        if not isinstance(executor, TaskExecutor):
            raise TypeError("executor must implement TaskExecutor.execute")
        self._executor = executor
        self._tasks: dict[str, _TaskState] = {}
        self._queue: deque[str] = deque()
        self._queued_ids: set[str] = set()
        self._active_task_id: str | None = None
        self._lock = RLock()

    def submit(self, task: Task | object, *, task_id: str | None = None) -> str:
        """Append a task to the FIFO queue and return its stable task id."""

        if isinstance(task, Task):
            if task_id is not None:
                raise TypeError("task_id cannot be supplied when task is a Task")
            task_value = task
        else:
            task_value = Task(task_id or uuid4().hex, task)

        with self._lock:
            if task_value.task_id in self._tasks:
                raise ValueError(f"duplicate task id: {task_value.task_id}")
            state = _TaskState(
                task=task_value,
                attempts=[self._new_attempt(task_value.task_id, 1)],
                control=TaskControl(),
            )
            self._tasks[task_value.task_id] = state
            self._queue.append(task_value.task_id)
            self._queued_ids.add(task_value.task_id)
            return task_value.task_id

    def get(self, task_id: str) -> TaskSnapshot:
        """Return an immutable snapshot of a task."""

        with self._lock:
            return self._snapshot_locked(self._require_locked(task_id))

    def status(self, task_id: str) -> TaskStatus:
        """Return the current lifecycle state."""

        return self.get(task_id).status

    def attempts(self, task_id: str) -> tuple[TaskAttempt, ...]:
        """Return the complete, ordered attempt history."""

        return self.get(task_id).attempts

    def pause(self, task_id: str) -> TaskSnapshot:
        """Pause a queued or running task; reject all other states."""

        with self._lock:
            state = self._require_locked(task_id)
            current = self._current_attempt(state)
            self._require_transition_locked(task_id, current.status, self._PAUSABLE)
            state.control.pause()
            self._replace_attempt_locked(state, status=TaskStatus.PAUSED)
            return self._snapshot_locked(state)

    def resume(self, task_id: str) -> TaskSnapshot:
        """Resume only a paused task; cancellation is terminal until restart."""

        with self._lock:
            state = self._require_locked(task_id)
            current = self._current_attempt(state)
            if current.status is not TaskStatus.PAUSED:
                raise InvalidTaskTransitionError(
                    f"cannot resume task {task_id!r} from {current.status.value}"
                )
            state.control.resume()
            if state.active and self._active_task_id == task_id:
                self._replace_attempt_locked(state, status=TaskStatus.RUNNING)
            else:
                self._replace_attempt_locked(state, status=TaskStatus.QUEUED)
                self._enqueue_locked(task_id)
            return self._snapshot_locked(state)

    def cancel(self, task_id: str) -> TaskSnapshot:
        """Cancel a queued, paused, or running task."""

        with self._lock:
            state = self._require_locked(task_id)
            current = self._current_attempt(state)
            self._require_transition_locked(task_id, current.status, self._CANCELLABLE)
            state.control.cancel()
            self._queued_ids.discard(task_id)
            self._replace_attempt_locked(state, status=TaskStatus.CANCELLED)
            return self._snapshot_locked(state)

    def restart(self, task_id: str) -> TaskSnapshot:
        """Create a fresh attempt for a completed, failed, or cancelled task."""

        with self._lock:
            state = self._require_locked(task_id)
            current = self._current_attempt(state)
            if current.status not in self._RESTARTABLE:
                raise InvalidTaskTransitionError(
                    f"cannot restart task {task_id!r} from {current.status.value}"
                )
            if state.active or self._active_task_id == task_id:
                raise InvalidTaskTransitionError(
                    f"cannot restart active task {task_id!r}"
                )
            number = current.number + 1
            state.attempts.append(self._new_attempt(task_id, number))
            state.control = TaskControl()
            self._enqueue_locked(task_id)
            return self._snapshot_locked(state)

    def update_result(self, task_id: str, result: object) -> TaskSnapshot:
        """Replace the current completed attempt result without changing history.

        This is intentionally narrow: callers may refresh durable metadata for a
        task that has already completed, but cannot mutate queued/running/failed
        attempts or resurrect old attempts.
        """

        with self._lock:
            state = self._require_locked(task_id)
            current = self._current_attempt(state)
            if current.status is not TaskStatus.COMPLETED:
                raise InvalidTaskTransitionError(
                    f"cannot update result for task {task_id!r} from {current.status.value}"
                )
            if state.active or self._active_task_id == task_id:
                raise InvalidTaskTransitionError(
                    f"cannot update result for active task {task_id!r}"
                )
            self._replace_attempt_locked(
                state,
                status=TaskStatus.COMPLETED,
                result=result,
                error=current.error,
            )
            return self._snapshot_locked(state)

    def run_next(self) -> TaskSnapshot | None:
        """Execute the next runnable task, returning its final snapshot."""

        with self._lock:
            if self._active_task_id is not None:
                raise RuntimeError("a task is already running")
            task_id = self._dequeue_next_locked()
            if task_id is None:
                return None
            state = self._tasks[task_id]
            state.active = True
            self._active_task_id = task_id
            self._replace_attempt_locked(state, status=TaskStatus.RUNNING)
            task = state.task
            control = state.control

        try:
            result = self._executor.execute(task, control)
        except TaskCancelledError as error:
            with self._lock:
                if self._current_attempt(state).status is TaskStatus.RUNNING:
                    if control.cancel_requested:
                        self._replace_attempt_locked(
                            state, status=TaskStatus.CANCELLED, error=error
                        )
                    elif control.pause_requested:
                        self._replace_attempt_locked(
                            state, status=TaskStatus.PAUSED, error=error
                        )
                    else:
                        self._replace_attempt_locked(
                            state, status=TaskStatus.FAILED, error=error
                        )
                return self._snapshot_locked(state)
        except Exception as error:
            with self._lock:
                if self._current_attempt(state).status is TaskStatus.RUNNING:
                    if control.cancel_requested:
                        status = TaskStatus.CANCELLED
                    elif control.pause_requested:
                        status = TaskStatus.PAUSED
                    else:
                        status = TaskStatus.FAILED
                    self._replace_attempt_locked(state, status=status, error=error)
                return self._snapshot_locked(state)
        else:
            with self._lock:
                if self._current_attempt(state).status is TaskStatus.RUNNING:
                    if control.cancel_requested:
                        self._replace_attempt_locked(state, status=TaskStatus.CANCELLED)
                    elif control.pause_requested:
                        self._replace_attempt_locked(state, status=TaskStatus.PAUSED)
                    else:
                        self._replace_attempt_locked(
                            state, status=TaskStatus.COMPLETED, result=result
                        )
                return self._snapshot_locked(state)
        finally:
            with self._lock:
                state.active = False
                if self._active_task_id == task_id:
                    self._active_task_id = None

    def run_all(self) -> tuple[TaskSnapshot, ...]:
        """Drain runnable tasks in FIFO order until none remain."""

        results: list[TaskSnapshot] = []
        while True:
            result = self.run_next()
            if result is None:
                return tuple(results)
            results.append(result)

    def _dequeue_next_locked(self) -> str | None:
        for _ in range(len(self._queue)):
            task_id = self._queue.popleft()
            if task_id not in self._queued_ids:
                continue
            state = self._tasks[task_id]
            current = self._current_attempt(state)
            if current.status is TaskStatus.PAUSED:
                self._queue.append(task_id)
                continue
            self._queued_ids.discard(task_id)
            if current.status is TaskStatus.QUEUED:
                return task_id
        return None

    def _enqueue_locked(self, task_id: str) -> None:
        if task_id not in self._queued_ids:
            self._queue.append(task_id)
            self._queued_ids.add(task_id)

    def _require_locked(self, task_id: str) -> _TaskState:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise UnknownTaskError(task_id) from error

    @staticmethod
    def _current_attempt(state: _TaskState) -> TaskAttempt:
        return state.attempts[-1]

    @staticmethod
    def _new_attempt(task_id: str, number: int) -> TaskAttempt:
        return TaskAttempt(
            number=number,
            attempt_id=f"{task_id}:{number}",
            status=TaskStatus.QUEUED,
        )

    @staticmethod
    def _replace_attempt_locked(
        state: _TaskState,
        *,
        status: TaskStatus,
        result: object = None,
        error: BaseException | None = None,
    ) -> None:
        state.attempts[-1] = replace(
            state.attempts[-1], status=status, result=result, error=error
        )

    @staticmethod
    def _require_transition_locked(
        task_id: str, current: TaskStatus, allowed: frozenset[TaskStatus]
    ) -> None:
        if current not in allowed:
            raise InvalidTaskTransitionError(
                f"invalid transition for task {task_id!r} from {current.value}"
            )

    @staticmethod
    def _snapshot_locked(state: _TaskState) -> TaskSnapshot:
        current = TaskManager._current_attempt(state)
        return TaskSnapshot(
            task_id=state.task.task_id,
            task=state.task,
            status=current.status,
            attempt_number=current.number,
            attempts=tuple(state.attempts),
            result=current.result,
            error=current.error,
        )
