"""
VPS (Virtual Private Server) endpoints.

Handles VPS container creation and management.

Supports four SSH key modes:
- disabled: No SSH server at all, TTY-only mode (default, faster startup)
- none: SSH with passwordless root login
- upload: SSH with user-provided public key
- generate: SSH with server-generated keypair (returns private key to CLI)

This module aggregates all VPS-related sub-routers:
- vps_lifecycle: VPS creation, restart, stop
- vps_querying: VPS listing and filtering
- vps_assignments: User assignment management
- vps_snapshots: Snapshot proxy endpoints
- vm_instances: VM instance management and VM image listing
"""

from fastapi import APIRouter

from kohakuriver.host.endpoints.vm_instances import router as vm_instances_router
from kohakuriver.host.endpoints.vps_assignments import router as vps_assignments_router
from kohakuriver.host.endpoints.vps_lifecycle import router as vps_lifecycle_router
from kohakuriver.host.endpoints.vps_querying import router as vps_querying_router
from kohakuriver.host.endpoints.vps_snapshots import router as vps_snapshots_router

router = APIRouter()

router.include_router(vps_lifecycle_router)
router.include_router(vps_querying_router)
router.include_router(vps_assignments_router)
router.include_router(vps_snapshots_router)
router.include_router(vm_instances_router)
