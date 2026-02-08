"""
Filesystem REST API endpoints for task/VPS containers on the Runner.

Provides file browsing and editing capabilities inside Docker containers
via Docker exec commands.

Includes WebSocket endpoint for real-time file system change notifications.

This is the entry module that assembles the filesystem router from sub-modules.
"""

from fastapi import APIRouter

from kohakuriver.runner.endpoints.filesystem_ops import router as ops_router
from kohakuriver.runner.endpoints.filesystem_shared import set_dependencies
from kohakuriver.runner.endpoints.filesystem_watcher import watch_filesystem_handler

router = APIRouter()
router.include_router(ops_router)

# Re-export for app.py compatibility
__all__ = ["router", "set_dependencies", "watch_filesystem_handler"]
