"""
Pydantic models for API requests and responses.

This module defines all data transfer objects (DTOs) used in the HakuRiver
API for communication between CLI, Host, and Runner components.

Model Categories:
    - Task Requests: Task submission and control
    - Task Responses: Task status and results
    - Node Requests: Node registration and heartbeat
    - Node Responses: Node status and information
    - Docker Requests/Responses: Container management
    - Health Responses: System health checks
    - Error Responses: Standardized error formats
"""

import datetime
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer


# =============================================================================
# Custom Types
# =============================================================================

# SnowflakeID: 64-bit integer that serializes to string for JavaScript compatibility
# JavaScript's Number.MAX_SAFE_INTEGER is 2^53-1, snowflake IDs exceed this
SnowflakeID = Annotated[int, PlainSerializer(lambda x: str(x), return_type=str)]


# =============================================================================
# Task Request Models
# =============================================================================


class TaskSubmitRequest(BaseModel):
    """
    Request body for task submission from CLI to host.

    This is the simplified request format used by the CLI client.
    The host converts this to internal TaskSubmission format.
    """

    command: str = Field(..., description="Command to execute")
    arguments: list[str] = Field(
        default_factory=list,
        description="Command arguments",
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables",
    )
    required_cores: int = Field(
        default=1,
        ge=1,
        description="Number of CPU cores required",
    )
    required_gpus: int = Field(
        default=0,
        ge=0,
        description="Number of GPUs required",
    )
    required_memory_bytes: int | None = Field(
        default=None,
        description="Memory requirement in bytes",
    )
    target_node: str | None = Field(
        default=None,
        description="Target node hostname (None=auto-assign)",
    )
    target_numa_node_id: int | None = Field(
        default=None,
        description="Target NUMA node ID",
    )
    container_name: str | None = Field(
        default=None,
        description="Container environment name",
    )
    registry_image: str | None = Field(
        default=None,
        description="Docker registry image (e.g. 'ubuntu:22.04'). Overrides container_name.",
    )
    docker_privileged: bool = Field(
        default=False,
        description="Run container with --privileged flag",
    )
    docker_mount_dirs: list[str] = Field(
        default_factory=list,
        description="Additional directories to mount",
    )
    ip_reservation_token: str | None = Field(
        default=None,
        description="IP reservation token for fixed container IP",
    )


class TaskSubmission(BaseModel):
    """
    Internal task submission model (host API).

    Supports both 'command' and 'vps' task types with full configuration.
    For VPS tasks, the command field stores the SSH public key.
    """

    task_type: str = Field(
        default="command",
        description="Task type: 'command' or 'vps'",
    )
    command: str = Field(
        default="",
        description="Command to execute (or SSH public key for VPS)",
    )
    arguments: list[str] = Field(
        default_factory=list,
        description="Command arguments",
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables",
    )
    required_cores: int = Field(
        default=1,
        ge=0,
        description="Number of CPU cores required",
    )
    required_gpus: list[list[int]] | None = Field(
        default=None,
        description="GPU IDs per target (list of lists)",
    )
    required_memory_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Memory limit in bytes",
    )
    targets: list[str] | None = Field(
        default=None,
        description="Target list, e.g., ['host1', 'host2:0', 'host1:1']",
    )
    container_name: str | None = Field(
        default=None,
        description="Override default container name",
    )
    registry_image: str | None = Field(
        default=None,
        description="Docker registry image (e.g. 'ubuntu:22.04'). Overrides container_name.",
    )
    privileged: bool | None = Field(
        default=None,
        description="Override default privileged setting",
    )
    additional_mounts: list[str] | None = Field(
        default=None,
        description="Override default additional mounts",
    )
    ip_reservation_token: str | None = Field(
        default=None,
        description="IP reservation token for fixed container IP",
    )


class TaskExecuteRequest(BaseModel):
    """
    Task execution request from host to runner.

    Contains all information needed by a runner to execute a task,
    including resource allocation and output paths.
    """

    task_id: int
    command: str
    arguments: list[str] | None = None
    env_vars: dict[str, str] | None = None
    required_cores: int = 1
    required_gpus: list[int] | None = None
    required_memory_bytes: int | None = None
    target_numa_node_id: int | None = None
    container_name: str
    registry_image: str | None = None
    working_dir: str = "/shared"
    stdout_path: str
    stderr_path: str
    reserved_ip: str | None = None


class VPSSubmission(BaseModel):
    """
    VPS (Virtual Private Server) submission request.

    Supports multiple SSH authentication modes:
        - disabled: No SSH server (TTY-only, fastest startup)
        - none: SSH with passwordless root login
        - upload: SSH with user-provided public key
        - generate: SSH with server-generated keypair
    """

    required_cores: int = 1
    required_gpus: list[int] | None = None
    required_memory_bytes: int | None = None
    target_hostname: str | None = None
    target_numa_node_id: int | None = None
    container_name: str | None = None
    registry_image: str | None = None
    ssh_key_mode: str = "disabled"
    ssh_public_key: str | None = None
    ip_reservation_token: str | None = None


class VPSCreateRequest(BaseModel):
    """VPS creation request from host to runner."""

    task_id: int
    required_cores: int = 1
    required_gpus: list[int] | None = None
    required_memory_bytes: int | None = None
    target_numa_node_id: int | None = None
    container_name: str
    registry_image: str | None = None
    ssh_key_mode: str = "disabled"
    ssh_public_key: str | None = None
    ssh_port: int
    reserved_ip: str | None = None


class TaskKillRequest(BaseModel):
    """Request body for killing a task."""

    signal: str = Field(
        default="SIGTERM",
        description="Signal to send (SIGTERM, SIGKILL, etc.)",
    )


class TaskControlRequest(BaseModel):
    """Request for task control operations (kill/pause/resume) from host to runner."""

    task_id: int
    container_name: str


# =============================================================================
# Task Response Models
# =============================================================================


class TaskResponse(BaseModel):
    """Complete task information response."""

    task_id: SnowflakeID
    task_type: str
    batch_id: SnowflakeID | None
    command: str
    arguments: list[str]
    env_vars: dict[str, str]
    required_cores: int
    required_gpus: list[int]
    required_memory_bytes: int | None
    target_numa_node_id: int | None
    status: str
    assigned_node: str | None
    container_name: str | None
    docker_image_name: str | None
    docker_privileged: bool
    docker_mount_dirs: list[str]
    ssh_port: int | None
    stdout_path: str
    stderr_path: str
    exit_code: int | None
    error_message: str | None
    submitted_at: str | None
    started_at: str | None
    completed_at: str | None


class TaskListResponse(BaseModel):
    """Paginated task list response."""

    items: list[TaskResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TaskSubmitResponse(BaseModel):
    """Response after single task submission."""

    task_id: SnowflakeID
    status: str
    message: str


class BatchSubmitResponse(BaseModel):
    """Response after batch task submission."""

    batch_id: SnowflakeID
    task_ids: list[SnowflakeID]
    message: str


# =============================================================================
# Node Request Models
# =============================================================================


class NodeRegisterRequest(BaseModel):
    """Request body for initial node registration."""

    hostname: str
    url: str
    total_cores: int
    memory_total_bytes: int | None = None
    numa_topology: dict[int, list[int]] | None = None
    gpu_info: list[dict] | None = None


class HeartbeatKilledTaskInfo(BaseModel):
    """Information about a task killed by the runner (e.g., OOM)."""

    task_id: int
    reason: str  # e.g., "oom", "killed_by_host"


class HeartbeatRequest(BaseModel):
    """
    Periodic heartbeat request from runner to host.

    Contains runner health metrics and task status updates.
    """

    running_tasks: list[int] = Field(
        default_factory=list,
        description="Currently running task IDs",
    )
    killed_tasks: list[HeartbeatKilledTaskInfo] = Field(
        default_factory=list,
        description="Tasks killed by runner since last heartbeat",
    )
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    current_avg_temp: float | None = None
    current_max_temp: float | None = None
    gpu_info: list[dict] | None = None


class RegisterRequest(BaseModel):
    """Runner registration request."""

    hostname: str
    url: str
    total_cores: int
    total_ram_bytes: int | None = None
    numa_topology: dict | None = None
    gpu_info: list[dict] | None = None


class TaskStatusUpdate(BaseModel):
    """Task status update from runner to host."""

    task_id: int
    status: str
    exit_code: int | None = None
    message: str | None = None
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None
    ssh_port: int | None = None


# =============================================================================
# Node Response Models
# =============================================================================


class NodeResponse(BaseModel):
    """Complete node information response."""

    hostname: str
    url: str
    total_cores: int
    memory_total_bytes: int | None
    status: str
    last_heartbeat: str | None
    cpu_percent: float | None
    memory_percent: float | None
    memory_used_bytes: int | None
    current_avg_temp: float | None
    current_max_temp: float | None
    numa_topology: dict[int, list[int]] | None
    gpu_info: list[dict]


class NodeListResponse(BaseModel):
    """Node list response."""

    items: list[NodeResponse]
    total: int


# =============================================================================
# Docker Request Models
# =============================================================================


class DockerCreateContainerRequest(BaseModel):
    """Request for creating a Docker container."""

    image_name: str = Field(..., description="Base Docker image to use")
    container_name: str = Field(..., description="Name for the new container")


class DockerCommitRequest(BaseModel):
    """Request for committing a container to an image."""

    source_container: str = Field(..., description="Container to commit from")
    kohakuriver_name: str = Field(..., description="HakuRiver environment name")


# =============================================================================
# Docker Response Models
# =============================================================================


class DockerImageResponse(BaseModel):
    """Docker image information."""

    name: str
    tag: str
    full_tag: str
    created: str | None
    size_bytes: int | None


class DockerImageListResponse(BaseModel):
    """Docker image list response."""

    items: list[DockerImageResponse]


class DockerContainerResponse(BaseModel):
    """Docker container information."""

    name: str
    image: str
    status: str
    created: str | None


class DockerContainerListResponse(BaseModel):
    """Docker container list response."""

    items: list[DockerContainerResponse]


# =============================================================================
# Health Response Models
# =============================================================================


class HealthResponse(BaseModel):
    """Basic health check response."""

    status: str
    version: str
    uptime_seconds: float


class ClusterHealthResponse(BaseModel):
    """Cluster-wide health overview."""

    total_nodes: int
    online_nodes: int
    offline_nodes: int
    total_tasks: int
    running_tasks: int
    pending_tasks: int
    completed_tasks: int
    failed_tasks: int


# =============================================================================
# Error Response Models
# =============================================================================


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: str
    detail: str | None = None
    request_id: str | None = None


class ValidationErrorResponse(BaseModel):
    """Validation error response with field-level details."""

    error: str = "Validation Error"
    detail: list[dict]
