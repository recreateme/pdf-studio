"""
PDF Studio - 批处理工作流历史
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config.settings import settings_mgr


@dataclass
class WorkflowHistoryEntry:
    """单次批处理运行摘要（不含加密密码）"""
    id: str
    created_at: str
    file_count: int
    output_dir: str
    workflow: dict[str, Any]
    success_count: int
    total_count: int
    steps_summary: str = ""

    @classmethod
    def from_run(
        cls,
        workflow: dict[str, Any],
        output_dir: str,
        file_count: int,
        results: list[dict],
    ) -> "WorkflowHistoryEntry":
        safe_wf = dict(workflow)
        if safe_wf.get("encrypt_password"):
            safe_wf["encrypt_password"] = ""
        ok = sum(1 for r in results if not r.get("error"))
        steps = []
        if safe_wf.get("ocr_enabled"):
            steps.append("OCR")
        if safe_wf.get("compress_enabled"):
            steps.append("压缩")
        if safe_wf.get("watermark_enabled"):
            steps.append("水印")
        if safe_wf.get("page_numbers_enabled"):
            steps.append("页码")
        if safe_wf.get("encrypt_enabled"):
            steps.append("加密")
        if safe_wf.get("png_enabled"):
            steps.append("PNG")
        return cls(
            id=uuid4().hex[:12],
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            file_count=file_count,
            output_dir=output_dir,
            workflow=safe_wf,
            success_count=ok,
            total_count=len(results),
            steps_summary=" → ".join(steps) or "无",
        )

    def display_text(self) -> str:
        ts = self.created_at.replace("T", " ")[:19]
        return (
            f"{ts}  ·  {self.success_count}/{self.total_count} 成功  ·  "
            f"{self.file_count} 文件  ·  {self.steps_summary}"
        )


class WorkflowHistoryStore:
    """工作流历史读写（独立 JSON 文件）"""

    MAX_ENTRIES = 30
    _FILENAME = "workflow_history.json"

    @classmethod
    def _path(cls) -> Path:
        return settings_mgr.CONFIG_DIR / cls._FILENAME

    @classmethod
    def load(cls) -> list[WorkflowHistoryEntry]:
        path = cls._path()
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [WorkflowHistoryEntry(**item) for item in raw]
        except Exception:
            return []

    @classmethod
    def save_all(cls, entries: list[WorkflowHistoryEntry]) -> None:
        path = cls._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(e) for e in entries[: cls.MAX_ENTRIES]], indent=2),
            encoding="utf-8",
        )

    @classmethod
    def append_from_run(
        cls,
        workflow: dict[str, Any],
        output_dir: str,
        file_count: int,
        results: list[dict],
    ) -> None:
        if not settings_mgr.workflow.save_workflow_history:
            return
        entries = cls.load()
        entries.insert(
            0,
            WorkflowHistoryEntry.from_run(workflow, output_dir, file_count, results),
        )
        cls.save_all(entries[: cls.MAX_ENTRIES])

    @classmethod
    def delete(cls, entry_id: str) -> None:
        entries = [e for e in cls.load() if e.id != entry_id]
        cls.save_all(entries)

    @classmethod
    def clear(cls) -> None:
        cls.save_all([])
