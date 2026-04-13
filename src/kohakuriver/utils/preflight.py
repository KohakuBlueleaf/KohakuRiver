"""
Pre-flight checks for KohakuRiver startup.

Validates system requirements before importing heavy native extensions
that would otherwise crash silently (e.g. SIGILL from unsupported CPU
instructions).
"""


def check_native_extensions() -> None:
    """Verify that native extensions can load on this CPU.

    kohakuvault ships a C extension that may be compiled with AVX/AVX2.
    On CPUs without AVX support, importing it triggers SIGILL and kills
    the process silently — no Python exception, no log output.

    This function tests the import in a subprocess so the main process
    survives, and raises a clear RuntimeError on failure.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import kohakuvault"],
        capture_output=True,
        timeout=10,
    )

    if result.returncode != 0:
        sig = -result.returncode if result.returncode < 0 else result.returncode
        hints = []

        # exit code 132 = 128 + 4 (SIGILL), also check raw signal number
        if result.returncode in (-4, 132):
            hints.append(
                "This usually means kohakuvault was compiled with CPU instructions "
                "(e.g. AVX2) that this machine does not support."
            )
            hints.append(
                "Fix: reinstall from source with\n"
                "  uv pip install --no-binary kohakuvault --force-reinstall kohakuvault"
            )

        msg = (
            f"Failed to load kohakuvault native extension "
            f"(exit code {result.returncode})."
        )
        if result.stderr:
            msg += f"\nstderr: {result.stderr.decode(errors='replace').strip()}"
        if hints:
            msg += "\n" + "\n".join(hints)

        raise RuntimeError(msg)
