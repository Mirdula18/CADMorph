"""TTL cleanup (T045), checked in both directions: expired terminal
artifacts really go; live jobs, RUNNING jobs (any age), in-flight creations,
and actively-written corrupt dirs are never touched."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cadmorph.pipeline import JobStore, ttl_hours


def _job_with_expiry(store: JobStore, hours_from_now: float, state: str = "done") -> str:
    job = store.create(b"%PDF-1.4 old", "a.pdf", b"%PDF-1.4 new", "b.pdf")
    job.state = state
    job.expires_at = datetime.now(UTC) + timedelta(hours=hours_from_now)
    store.save(job)
    return job.comparison_id


def _age_tree(path: Path, hours: float) -> None:
    """Backdate the directory AND every file in it (NTFS: writing into an
    existing file does not touch the parent dir's mtime, so both matter)."""
    old = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    for p in [*path.iterdir(), path]:
        os.utime(p, (old, old))


def test_expired_terminal_removed_live_kept(tmp_path):
    store = JobStore(tmp_path)
    expired = _job_with_expiry(store, hours_from_now=-1)
    live = _job_with_expiry(store, hours_from_now=+1)

    assert store.cleanup_expired() == 1
    assert not store.job_dir(expired).exists()  # gone, tree and all
    assert store.job_dir(live).exists()
    assert (store.job_dir(live) / "upload_old.pdf").exists()


@pytest.mark.parametrize("state", ["pending", "extracting", "matching", "reporting"])
def test_running_job_never_swept_regardless_of_age(tmp_path, state):
    """The dangerous direction: TTL lapsed AND every file is 10x TTL old,
    but the job is non-terminal -> it must be untouchable."""
    store = JobStore(tmp_path)
    cid = _job_with_expiry(store, hours_from_now=-100, state=state)
    _age_tree(store.job_dir(cid), hours=ttl_hours() * 10)

    assert store.cleanup_expired() == 0
    assert (store.job_dir(cid) / "upload_old.pdf").exists()


def test_same_age_terminal_state_is_swept(tmp_path):
    """Inverse of the running-job guard: identical age, terminal state."""
    store = JobStore(tmp_path)
    cid = _job_with_expiry(store, hours_from_now=-100, state="failed")
    _age_tree(store.job_dir(cid), hours=ttl_hours() * 10)

    assert store.cleanup_expired() == 1
    assert not store.job_dir(cid).exists()


def test_orphan_dir_removed_only_after_ttl(tmp_path):
    """A dir without job.json is an in-flight create() until it is TTL-old."""
    store = JobStore(tmp_path)
    fresh = store.root / "fresh-orphan"
    fresh.mkdir()
    stale = store.root / "stale-orphan"
    stale.mkdir()
    _age_tree(stale, hours=ttl_hours() + 1)

    assert store.cleanup_expired() == 1
    assert fresh.exists()  # never sweep a possible in-flight upload
    assert not stale.exists()


def test_corrupt_job_json_old_tree_is_actually_cleaned(tmp_path):
    """Not merely 'doesn't crash': corrupt job.json + everything older than
    TTL -> the tree is really removed."""
    store = JobStore(tmp_path)
    cid = _job_with_expiry(store, hours_from_now=-1)
    (store.job_dir(cid) / "job.json").write_text("{not json", encoding="utf-8")

    assert store.cleanup_expired() == 0  # files still fresh -> kept
    _age_tree(store.job_dir(cid), hours=ttl_hours() + 1)
    assert store.cleanup_expired() == 1  # now provably swept
    assert not store.job_dir(cid).exists()


def test_corrupt_job_json_with_one_fresh_file_kept(tmp_path):
    """Newest-file guard: an old corrupt dir that something is still writing
    into (one fresh artifact) is not swept."""
    store = JobStore(tmp_path)
    cid = _job_with_expiry(store, hours_from_now=-1)
    directory = store.job_dir(cid)
    (directory / "job.json").write_text("{not json", encoding="utf-8")
    _age_tree(directory, hours=ttl_hours() + 1)
    (directory / "graph_old.json").write_text("{}", encoding="utf-8")  # fresh

    assert store.cleanup_expired() == 0
    assert directory.exists()


def test_ttl_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CADMORPH_TTL_HOURS", "2")
    store = JobStore(tmp_path)
    job = store.create(b"%PDF", "a.pdf", b"%PDF", "b.pdf")
    assert job.expires_at - job.created_at == timedelta(hours=2)
