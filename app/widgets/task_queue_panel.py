"""
PDF Studio - 全局任务队列面板
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem
from qfluentwidgets import CardWidget, CaptionLabel, PushButton, StrongBodyLabel

from app.utils.task_hub import TaskHub
from app.widgets.list_styles import apply_list_widget_style


class TaskQueuePanel(CardWidget):
    """显示后台任务队列"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hub = TaskHub.instance()
        self._setup_ui()
        self._hub.tasksChanged.connect(self.refresh)
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self._title = StrongBodyLabel("后台任务")
        self._count = CaptionLabel("")
        self._count.setStyleSheet("color:#888;")
        clear_btn = PushButton("清除已完成")
        clear_btn.setFixedWidth(88)
        clear_btn.clicked.connect(self._hub.clear_finished)
        header.addWidget(self._title)
        header.addStretch()
        header.addWidget(self._count)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setMaximumHeight(160)
        apply_list_widget_style(self._list)
        layout.addWidget(self._list)

    def refresh(self) -> None:
        self._list.clear()
        tasks = self._hub.recent_tasks(12)
        running = self._hub.running_count()
        queued = self._hub.queued_count()
        if queued:
            self._count.setText(f"{running} 进行中 · {queued} 排队")
        else:
            self._count.setText(f"{running} 个进行中")

        if not tasks:
            item = QListWidgetItem("暂无任务")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        status_map = {
            "queued": "排队中",
            "running": "进行中",
            "done": "已完成",
            "error": "失败",
            "cancelled": "已取消",
        }
        for t in tasks:
            prog = ""
            if t.status == "running" and t.progress[1] > 0:
                c, total = t.progress
                prog = f"  {c}/{total}"
            elif t.status == "queued":
                prog = "  等待空闲线程"
            msg = f" · {t.message[:30]}" if t.message else ""
            text = f"{status_map.get(t.status, t.status)} · {t.name}{prog}{msg}"
            if t.status == "error" and t.error:
                text += f"  ({t.error[:40]})"
            self._list.addItem(QListWidgetItem(text))
