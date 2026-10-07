"""Import every model here so `Base.metadata` is fully populated for
Alembic autogeneration (`alembic/env.py` imports this module) and so
`relationship(...)` string references resolve at mapper-configuration time.
"""
from app.database.base import Base
from app.models.agent_action import AgentAction
from app.models.artifact import Artifact
from app.models.bug import Bug
from app.models.memory_record import MemoryRecord
from app.models.project import Project
from app.models.run_event import RunEvent
from app.models.test_run import TestRun
from app.models.ui_state import UIState
from app.models.ui_transition import UITransition

__all__ = [
    "Base",
    "Project",
    "TestRun",
    "AgentAction",
    "UIState",
    "UITransition",
    "Bug",
    "Artifact",
    "RunEvent",
    "MemoryRecord",
]
