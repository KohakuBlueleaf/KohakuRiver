"""
GPU information utilities for HakuRiver.

This module provides functions for querying NVIDIA GPU information using
the pynvml library. It handles cases where GPUs are not available or
the required libraries are not installed.
"""

from pydantic import BaseModel

from kohakuriver.utils.logger import get_logger

try:
    import pynvml
except ImportError:
    pynvml = None

log = get_logger(__name__)


# =============================================================================
# Data Models
# =============================================================================


class GPUInfo(BaseModel):
    """
    Information about a single NVIDIA GPU.

    All fields that may not be available (due to driver limitations or
    hardware support) use -1 as a sentinel value.
    """

    gpu_id: int
    name: str
    driver_version: str
    pci_bus_id: str
    gpu_utilization: int  # Percentage (0-100), -1 if unavailable
    graphics_clock_mhz: int  # -1 if unavailable
    mem_utilization: int  # Percentage (0-100), -1 if unavailable
    mem_clock_mhz: int  # -1 if unavailable
    memory_total_mib: float
    memory_used_mib: float
    memory_free_mib: float
    temperature: int  # Celsius, -1 if unavailable
    fan_speed: int  # Percentage (0-100), -1 if unavailable
    power_usage_mw: int  # Milliwatts, -1 if unavailable
    power_limit_mw: int  # Milliwatts, -1 if unavailable


# =============================================================================
# GPU Query Functions
# =============================================================================


def get_gpu_info() -> list[GPUInfo]:
    """
    Retrieve information about all installed NVIDIA GPUs.

    Uses the pynvml library to query GPU status. Returns an empty list
    if no GPUs are found or if the required library is not installed.

    Returns:
        List of GPUInfo objects, one per GPU. Empty list if no GPUs
        are available or pynvml is not installed.

    Note:
        This function handles all exceptions internally and will never
        raise. It logs warnings for non-critical errors.
    """
    if pynvml is None:
        log.debug("pynvml not installed, GPU info unavailable")
        return []

    gpu_info_list: list[GPUInfo] = []
    nvml_initialized = False

    try:
        pynvml.nvmlInit()
        nvml_initialized = True

        driver_version = _get_driver_version(pynvml)
        device_count = pynvml.nvmlDeviceGetCount()

        if device_count == 0:
            log.debug("No NVIDIA GPUs found")
            return []

        for i in range(device_count):
            gpu_info = _query_single_gpu(pynvml, i, driver_version)
            if gpu_info:
                gpu_info_list.append(gpu_info)

    except Exception as e:
        log.debug(f"Failed to query GPU info: {e}")
        return []
    finally:
        if nvml_initialized:
            _shutdown_nvml(pynvml)

    return gpu_info_list


# =============================================================================
# Helper Functions
# =============================================================================


def _get_driver_version(pynvml) -> str:
    """Get the NVIDIA driver version string."""
    version_bytes = pynvml.nvmlSystemGetDriverVersion()
    if isinstance(version_bytes, bytes):
        return version_bytes.decode("utf-8")
    return version_bytes


def _query_single_gpu(pynvml, gpu_index: int, driver_version: str) -> GPUInfo | None:
    """
    Query information for a single GPU.

    Args:
        pynvml: The pynvml module.
        gpu_index: Zero-based GPU index.
        driver_version: NVIDIA driver version string.

    Returns:
        GPUInfo object, or None if the GPU cannot be queried.
    """
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)

        name = _decode_string(pynvml.nvmlDeviceGetName(handle))
        pci_bus_id = _decode_string(pynvml.nvmlDeviceGetPciInfo(handle).busId)
        memory = _get_memory_info(pynvml, handle)
        utilization = _get_utilization(pynvml, handle)
        clocks = _get_clock_info(pynvml, handle)
        thermal = _get_thermal_info(pynvml, handle)
        power = _get_power_info(pynvml, handle)

        return GPUInfo(
            gpu_id=gpu_index,
            name=name,
            driver_version=driver_version,
            pci_bus_id=pci_bus_id,
            memory_total_mib=memory["total"],
            memory_used_mib=memory["used"],
            memory_free_mib=memory["free"],
            gpu_utilization=utilization["gpu"],
            mem_utilization=utilization["memory"],
            graphics_clock_mhz=clocks["graphics"],
            mem_clock_mhz=clocks["memory"],
            temperature=thermal["temperature"],
            fan_speed=thermal["fan_speed"],
            power_usage_mw=power["usage"],
            power_limit_mw=power["limit"],
        )

    except Exception as e:
        log.debug(f"Failed to query GPU {gpu_index}: {e}")
        return None


def _decode_string(value: bytes | str) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _get_memory_info(pynvml, handle) -> dict[str, float]:
    """Get GPU memory information in MiB."""
    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
    return {
        "total": mem_info.total / (1024**2),
        "used": mem_info.used / (1024**2),
        "free": mem_info.free / (1024**2),
    }


def _get_utilization(pynvml, handle) -> dict[str, int]:
    """Get GPU and memory utilization percentages."""
    try:
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        return {"gpu": util.gpu, "memory": util.memory}
    except pynvml.NVMLError:
        return {"gpu": -1, "memory": -1}


def _get_clock_info(pynvml, handle) -> dict[str, int]:
    """Get GPU clock speeds in MHz."""
    try:
        return {
            "graphics": pynvml.nvmlDeviceGetClockInfo(
                handle, pynvml.NVML_CLOCK_GRAPHICS
            ),
            "memory": pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM),
        }
    except pynvml.NVMLError:
        return {"graphics": -1, "memory": -1}


def _get_thermal_info(pynvml, handle) -> dict[str, int]:
    """Get GPU temperature and fan speed."""
    temperature = -1
    fan_speed = -1

    try:
        temperature = pynvml.nvmlDeviceGetTemperature(
            handle, pynvml.NVML_TEMPERATURE_GPU
        )
    except pynvml.NVMLError:
        pass

    try:
        fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
    except pynvml.NVMLError:
        pass

    return {"temperature": temperature, "fan_speed": fan_speed}


def _get_power_info(pynvml, handle) -> dict[str, int]:
    """Get GPU power usage and limit in milliwatts."""
    try:
        return {
            "usage": pynvml.nvmlDeviceGetPowerUsage(handle),
            "limit": pynvml.nvmlDeviceGetEnforcedPowerLimit(handle),
        }
    except pynvml.NVMLError:
        return {"usage": -1, "limit": -1}


def _shutdown_nvml(pynvml) -> None:
    """Safely shutdown NVML."""
    try:
        pynvml.nvmlShutdown()
    except pynvml.NVMLError as e:
        log.warning(f"Error during nvmlShutdown: {e}")


# =============================================================================
# Main (for testing)
# =============================================================================


if __name__ == "__main__":
    gpu_info_results = get_gpu_info()

    print("\nGPU Information:")
    if not gpu_info_results:
        print("No GPU information could be retrieved.")
    else:
        for info in gpu_info_results:
            print(info.model_dump_json(indent=2))
