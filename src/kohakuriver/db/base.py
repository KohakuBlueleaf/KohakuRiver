"""
Database base configuration and utilities.

This module provides the foundation for HakuRiver's database layer using
Peewee ORM with SQLite backend.

Components:
    - db: Global SQLite database instance
    - BaseModel: Base class for all HakuRiver database models
    - initialize_database: Database setup function
    - run_in_executor: Async wrapper for blocking DB operations
"""

import asyncio

import peewee

from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Database Instance
# =============================================================================

# Global database instance - path set via initialize_database()
db = peewee.SqliteDatabase(None)


# =============================================================================
# Base Model
# =============================================================================


class BaseModel(peewee.Model):
    """
    Base model for all HakuRiver database models.

    All models inherit from this class to share the database connection.
    """

    class Meta:
        database = db


# =============================================================================
# Database Lifecycle
# =============================================================================


def initialize_database(db_path: str) -> None:
    """
    Connect to the database and create tables.

    Args:
        db_path: Path to the SQLite database file.

    Raises:
        peewee.OperationalError: If database connection fails.
    """
    # Import models here to avoid circular imports
    from kohakuriver.db.node import Node
    from kohakuriver.db.task import Task

    logger.debug(f"Initializing database at: {db_path}")

    try:
        db.init(db_path)
        db.connect()
        db.create_tables([Node, Task], safe=True)

        # Run migrations for new columns
        _run_migrations(Task)

        logger.info(f"Database initialized: {db_path}")

        # Log initial stats
        task_count = Task.select().count()
        node_count = Node.select().count()
        logger.debug(f"Database contains {task_count} tasks, {node_count} nodes")

    except peewee.OperationalError as e:
        logger.error(f"Failed to initialize database '{db_path}': {e}")
        raise


def _run_migrations(Task) -> None:
    """Add any missing columns to existing tables."""
    # Check if table exists first
    cursor = db.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    )
    if not cursor.fetchone():
        return  # Table doesn't exist yet (fresh DB, create_tables handles it)

    from playhouse.migrate import SqliteMigrator, migrate

    migrator = SqliteMigrator(db)

    # Get existing columns
    cursor = db.execute_sql("PRAGMA table_info(tasks)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    migrations = []
    if "registry_image" not in existing_columns:
        migrations.append(
            migrator.add_column("tasks", "registry_image", peewee.CharField(null=True))
        )

    if migrations:
        migrate(*migrations)
        logger.info(f"Ran {len(migrations)} database migration(s)")


def close_database() -> None:
    """Close the database connection if open."""
    if not db.is_closed():
        db.close()
        logger.debug("Database connection closed")


# =============================================================================
# Async Utilities
# =============================================================================


async def run_in_executor(func, *args, **kwargs):
    """
    Run a blocking database function in a thread pool executor.

    Use this in async contexts to avoid blocking the event loop.

    Args:
        func: The blocking function to execute.
        *args: Positional arguments for the function.
        **kwargs: Keyword arguments for the function.

    Returns:
        The return value of the function.

    Example:
        task = await run_in_executor(Task.get_or_none, Task.task_id == task_id)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
