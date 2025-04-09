import os
from pathlib import Path


def is_dry_run() -> bool:
    """Checks if the run is a DRY_RUN"""
    return os.getenv("DRY_RUN", "True") == "True"


def _get_rerun_marker_path() -> Path:
    workdir = os.getenv("WORK")
    if not workdir:
        raise ValueError("WORK environment variable is not set")
    return Path(workdir) / "rerun"


def mark_rerun() -> None:
    """Mark the current run requires a rerun by creating a marker file."""
    _get_rerun_marker_path().touch(exist_ok=True)


def should_rerun() -> bool:
    """Check if the current run requires a rerun by checking the marker file."""
    return _get_rerun_marker_path().exists()
