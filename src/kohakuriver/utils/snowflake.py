"""
Snowflake ID generation for HakuRiver.

This module provides distributed unique ID generation using the Snowflake
algorithm. IDs are time-ordered, unique across instances, and suitable
for distributed systems.

Snowflake IDs are 64-bit integers composed of:
    - Timestamp (milliseconds since epoch)
    - Instance ID (to avoid collisions between nodes)
    - Sequence number (for multiple IDs in the same millisecond)
"""

import snowflake

# =============================================================================
# Snowflake Generator
# =============================================================================


class Snowflake:
    """
    Wrapper around the snowflake generator library.

    Provides a callable interface for generating unique IDs.

    Attributes:
        gen: The underlying snowflake generator instance.
    """

    def __init__(self, instance_id: int = 0):
        """
        Initialize the snowflake generator.

        Args:
            instance_id: Unique identifier for this instance (0-1023).
                         Different instances should use different IDs
                         to avoid collisions in distributed systems.
        """
        self.gen = snowflake.SnowflakeGenerator(instance_id)

    def __call__(self) -> int:
        """
        Generate the next unique snowflake ID.

        Returns:
            A unique 64-bit integer ID.
        """
        return next(self.gen)


# =============================================================================
# Module-Level Interface
# =============================================================================


# Global snowflake generator instance (instance_id=0 for single-node usage)
_snowflake = Snowflake()


def generate_snowflake_id() -> str:
    """
    Generate a unique snowflake ID as a string.

    Returns:
        Unique ID string suitable for use as task IDs, batch IDs, etc.

    Example:
        >>> task_id = generate_snowflake_id()
        >>> print(task_id)
        '7199539478398935040'
    """
    return str(_snowflake())
