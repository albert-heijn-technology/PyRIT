from __future__ import annotations

import asyncio
from typing import Optional

from pyrit.setup import initialize_pyrit_async, IN_MEMORY

_PYRIT_INITIALIZED = False


async def ensure_pyrit_initialized_async() -> None:
    global _PYRIT_INITIALIZED
    if _PYRIT_INITIALIZED:
        return
    await initialize_pyrit_async(memory_db_type=IN_MEMORY)
    _PYRIT_INITIALIZED = True


def ensure_pyrit_initialized() -> None:
    """
    Backward-compatible synchronous entrypoint that runs the async initializer.
    Useful for callers that are not async-aware.
    """
    asyncio.run(ensure_pyrit_initialized_async())
