"""Keep the machine awake while an experiment runs from it.

A load generator runs on the operator's machine. If the machine sleeps
mid-run, publishing stops while the experiment's Dataflow job keeps
running — and billing — until the replay build's wait step times out.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

# SetThreadExecutionState flags (winbase.h).
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_awake() -> Iterator[None]:
    """Prevent idle sleep for the duration of the block (Windows only).

    Closing the lid or pressing the power button still sleeps the machine;
    this only stops the idle timer from doing it.
    """
    if sys.platform != "win32":
        yield
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
