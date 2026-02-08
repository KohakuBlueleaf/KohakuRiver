"""Bidirectional stream binding utility."""

import asyncio


async def bind_reader_writer(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
    """
    Pipe data from reader to writer until EOF or error.

    Args:
        reader: AsyncIO stream reader.
        writer: AsyncIO stream writer.
    """
    while True:
        try:
            data = await reader.read(1024)
            if not data:
                break
            writer.write(data)
            await writer.drain()
        except OSError:
            break
