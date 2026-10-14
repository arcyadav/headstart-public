"""Keeping published planners across restarts. A free server (Render) loses its files
when it restarts or sleeps, so the kept planners (planners/kept/, see planners.py) are
copied from a private Hugging Face dataset at start, and changes are pushed back to it
every few minutes. The demo is never saved. Needs HF_TOKEN (write access)
and the dataset's id, e.g. "arcyadav/headstart-planners".
"""

from __future__ import annotations

from pathlib import Path

# Only the data; plan.txt is rebuilt from it.
PATTERNS = ["*/setup.json", "*/progress.json", "*/plan.json"]


def restore(root: str | Path, repo: str) -> None:
    """Copy the saved planners into `root` (the dataset is made if it doesn't exist yet)."""
    from huggingface_hub import create_repo, snapshot_download

    create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    snapshot_download(repo, repo_type="dataset", local_dir=root, allow_patterns=PATTERNS)


def keep(root: str | Path, repo: str, every_min: float = 2):
    """Push changed planner files to the dataset every `every_min` minutes, in the
    background. Returns the scheduler (its .lock can guard a write)."""
    from huggingface_hub import CommitScheduler

    return CommitScheduler(repo_id=repo, repo_type="dataset", folder_path=root, every=every_min,
                           private=True, allow_patterns=PATTERNS)
