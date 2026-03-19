from __future__ import annotations

"""
Simple task-list model for manual PLC integration work.

Tasks are created whenever the generator cannot emit a fully automatic PLC
implementation and must instead generate a task marker in the produced ST code.

The task list is intentionally minimal:
- id
- plc_path
- message
"""

from dataclasses import asdict, dataclass
from typing import List


@dataclass(frozen=True)
class Task:
    """
    One manual PLC integration task.
    """
    id: str
    plc_path: str
    message: str


class TaskList:
    """
    Collect manual PLC integration tasks detected during code generation.

    A task should be added whenever the generator cannot emit a complete PLC
    implementation automatically and must leave a marked task in the generated
    Structured Text source.
    """

    def __init__(self) -> None:
        self._tasks: List[Task] = []
        self._counter: int = 1

    def add(self, plc_path: str, message: str) -> str:
        """
        Add one task and return its generated identifier.

        Example ids:
            TASK-001
            TASK-002
        """
        task_id = f"TASK-{self._counter:03d}"
        self._counter += 1

        self._tasks.append(
            Task(
                id=task_id,
                plc_path=plc_path,
                message=message,
            )
        )
        return task_id

    def make_st_comment(self, plc_path: str, message: str) -> str:
        """
        Create one task, then return the ST comment that should be emitted in the
        generated code.

        Example:
            // TASK-001: configure SEC node PLC timestamp tag
        """
        task_id = self.add(plc_path=plc_path, message=message)
        return f"// {task_id}: {message}"

    def to_list(self) -> List[dict]:
        """
        Return the collected tasks as plain dictionaries for JSON serialisation.
        """
        return [asdict(task) for task in self._tasks]

    @property
    def tasks(self) -> List[Task]:
        """
        Read-only style access to collected tasks.
        """
        return list(self._tasks)