"""
PDF Studio - 全局后台任务队列
跟踪 QThreadPool 中运行的 Worker 状态，支持排队与队列满拒绝
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Optional

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class TaskRecord:
    task_id: str
    name: str
    status: str = "queued"  # queued | running | done | error | cancelled
    message: str = ""
    progress: tuple[int, int] = (0, 0)
    started_at: datetime = field(default_factory=datetime.now)
    error: str = ""


@dataclass
class _PendingTask:
    task_id: str
    worker: object


class TaskHub(QObject):
    """全局任务中心（单例）"""

    tasksChanged = pyqtSignal()
    taskQueued = pyqtSignal(str, int)       # 任务名, 前面排队数
    queueRejected = pyqtSignal(str, int)    # 任务名, 队列上限

    _instance: Optional["TaskHub"] = None

    def __init__(self) -> None:
        super().__init__()
        self._tasks: dict[str, TaskRecord] = {}
        self._wait_queue: Deque[_PendingTask] = deque()
        self._counter = 0

    @classmethod
    def instance(cls) -> "TaskHub":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 提交与调度 ────────────────────────────

    def submit(
        self,
        worker,
        label: str = "",
        *,
        max_concurrent: int,
        max_total: int,
    ) -> bool:
        """
        注册任务并按策略启动或排队。

        Returns:
            True 已接受（立即运行或排队）；False 队列已满被拒绝
        """
        max_concurrent = max(1, max_concurrent)
        max_total = max(max_concurrent, max_total)

        if self.total_active() >= max_total:
            name = label or worker.__class__.__name__.replace("Worker", "")
            self.queueRejected.emit(name, max_total)
            return False

        task_id = self._register(worker, label)
        name = self._tasks[task_id].name

        if self.running_count() < max_concurrent:
            self._start_task(task_id, worker)
        else:
            self._wait_queue.append(_PendingTask(task_id, worker))
            position = len(self._wait_queue)
            self.taskQueued.emit(name, position)
            self.tasksChanged.emit()

        return True

    def _register(self, worker, label: str = "") -> str:
        self._counter += 1
        task_id = f"task-{self._counter}"
        name = label or worker.__class__.__name__.replace("Worker", "")
        record = TaskRecord(task_id=task_id, name=name, status="queued")
        self._tasks[task_id] = record

        worker.signals.progress.connect(
            lambda c, t, tid=task_id: self._on_progress(tid, c, t)
        )
        worker.signals.message.connect(
            lambda msg, tid=task_id: self._on_message(tid, msg)
        )

        def finish(_result=None, tid=task_id, w=worker):
            self._set_status(tid, "done")
            self._on_worker_slot_free(w)

        def fail(msg, tid=task_id, w=worker):
            rec = self._tasks.get(tid)
            if rec:
                rec.status = "error"
                rec.error = msg
                self.tasksChanged.emit()
            self._on_worker_slot_free(w)

        def cancel(tid=task_id, w=worker):
            self._set_status(tid, "cancelled")
            self._on_worker_slot_free(w)

        worker.signals.finished.connect(finish)
        worker.signals.error.connect(fail)
        worker.signals.cancelled.connect(cancel)
        self.tasksChanged.emit()
        return task_id

    def _start_task(self, task_id: str, worker) -> None:
        from app.workers.base_worker import get_thread_pool

        rec = self._tasks.get(task_id)
        if rec:
            rec.status = "running"
            rec.started_at = datetime.now()
            self.tasksChanged.emit()
        get_thread_pool().start(worker)

    def _on_worker_slot_free(self, worker) -> None:
        from app.config.settings import settings_mgr

        wf = settings_mgr.workflow
        max_concurrent = max(1, wf.max_workers)
        max_total = max(max_concurrent, wf.queue_max_size)
        self._dispatch_next(max_concurrent, max_total)

    def _dispatch_next(self, max_concurrent: int, max_total: int) -> None:
        while self._wait_queue and self.running_count() < max_concurrent:
            if self.total_active() > max_total:
                break
            pending = self._wait_queue.popleft()
            if pending.task_id not in self._tasks:
                continue
            if self._tasks[pending.task_id].status != "queued":
                continue
            self._start_task(pending.task_id, pending.worker)
        self.tasksChanged.emit()

    # ── 状态查询 ──────────────────────────────

    def _on_progress(self, task_id: str, current: int, total: int) -> None:
        rec = self._tasks.get(task_id)
        if rec:
            rec.progress = (current, total)
            self.tasksChanged.emit()

    def _on_message(self, task_id: str, message: str) -> None:
        rec = self._tasks.get(task_id)
        if rec:
            rec.message = message
            self.tasksChanged.emit()

    def _set_status(self, task_id: str, status: str) -> None:
        rec = self._tasks.get(task_id)
        if rec:
            rec.status = status
            self.tasksChanged.emit()

    def active_tasks(self) -> list[TaskRecord]:
        return [t for t in self._tasks.values() if t.status in ("running", "queued")]

    def recent_tasks(self, limit: int = 20) -> list[TaskRecord]:
        items = list(self._tasks.values())
        return items[-limit:][::-1]

    def clear_finished(self) -> None:
        active_ids = {
            t.task_id
            for t in self._tasks.values()
            if t.status in ("running", "queued")
        }
        self._tasks = {
            k: v for k, v in self._tasks.items() if k in active_ids
        }
        self.tasksChanged.emit()

    def running_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == "running")

    def queued_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == "queued")

    def total_active(self) -> int:
        return self.running_count() + self.queued_count()

    def wait_queue_length(self) -> int:
        return len(self._wait_queue)
