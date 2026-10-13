"""Progress reporting for long-running steps, used by the TUI.

Functions that take a `progress` callback call it with a `Progress` at the start
of each stage and periodically during it. `total` is None when the amount of
work isn't known in advance. A callback can raise `RunCancelled` to stop the run.
"""

from collections.abc import Callable
from dataclasses import dataclass


class RunCancelled(Exception):
    """Raised by a progress callback to stop a run at the next checkpoint."""


@dataclass(frozen=True)
class Progress:
    stage: str
    done: int = 0
    total: int | None = None


type ProgressCallback = Callable[[Progress], None]


def tracker(
    progress: ProgressCallback | None, stage: str, total: int | None = None, updates: int = 200
) -> Callable[[int], None]:
    """Announce a stage; return a function to call with the amount done so far.

    It forwards at most about `updates` calls, so callers can call it in tight loops.
    """
    if progress is None:
        return lambda done: None
    progress(Progress(stage, 0, total))
    step = max(1, (total or 0) // updates)

    def update(done: int) -> None:
        if done % step == 0 or done == total:
            progress(Progress(stage, done, total))

    return update
