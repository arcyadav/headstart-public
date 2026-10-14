"""Keeping the hosted planners across restarts. A free server (Render) loses its files
when it restarts or sleeps, so the planners folder is copied from a private Hugging Face dataset at
start, and changes are pushed back to it every few minutes. Needs HF_TOKEN (write access)
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


def forget(repo: str, planner_id: str, again_after_s: float = 0) -> None:
    """Delete a planner's folder from the dataset. With again_after_s, delete again after
    that long, in case a push that was already under way brought it back."""
    import time

    from huggingface_hub import HfApi

    for attempt in range(2 if again_after_s else 1):
        if attempt:
            time.sleep(again_after_s)
        try:
            HfApi().delete_folder(planner_id, repo_id=repo, repo_type="dataset",
                                  commit_message="A planner was deleted")
        except Exception:  # not saved yet, or already gone
            pass


def keep(root: str | Path, repo: str, every_min: float = 2):
    """Push changed planner files to the dataset every `every_min` minutes, in the
    background. Returns the scheduler (its .lock can guard a write)."""
    from huggingface_hub import CommitScheduler

    return CommitScheduler(repo_id=repo, repo_type="dataset", folder_path=root, every=every_min,
                           private=True, allow_patterns=PATTERNS)
