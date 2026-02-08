"""
Task management endpoints for HakuRiver Host.

This module provides API endpoints for task lifecycle management including:
- Task submission (both command and VPS types)
- Status queries and listing
- Task control (kill, pause, resume)
- Output retrieval (stdout/stderr)
- Task approval workflow

Routes are split across sub-modules:
- task_submission: Task creation, validation, and dispatching
- task_querying: Status queries, listing, and status updates from runners
- task_approval: Approval/rejection workflow for pending tasks
- task_control: Kill, pause/resume commands, and stdout/stderr retrieval
"""

from fastapi import APIRouter

from kohakuriver.host.endpoints.task_approval import router as approval_router
from kohakuriver.host.endpoints.task_control import router as control_router
from kohakuriver.host.endpoints.task_querying import router as querying_router
from kohakuriver.host.endpoints.task_submission import router as submission_router

# Re-export for backward compatibility
from kohakuriver.host.endpoints.task_submission import (  # noqa: F401
    allocate_ssh_port,
    background_tasks,
)

router = APIRouter()

router.include_router(submission_router)
router.include_router(querying_router)
router.include_router(approval_router)
router.include_router(control_router)
