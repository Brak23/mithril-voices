"""Original synthetic repositories only; no network, actual fork or game writes."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("bootstrap", Path(__file__).with_name("bootstrap_repository.py"))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def command(repo, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    command(repo, "init", "-q")
    command(repo, "config", "user.name", "Synthetic Test")
    command(repo, "config", "user.email", "test@example.invalid")
    (repo / "fixture.txt").write_text("original synthetic fixture\n")
    command(repo, "add", "fixture.txt")
    command(repo, "commit", "-qm", "synthetic baseline")
    base = command(repo, "rev-parse", "HEAD")
    command(repo, "remote", "add", "origin", bootstrap.ORIGIN)
    command(repo, "remote", "add", "upstream", bootstrap.UPSTREAM)
    return repo, tmp_path / "baseline", base


def test_dry_run_has_no_writes(repository):
    repo, target, base = repository
    before = (repo / ".git/config").read_bytes()
    result = bootstrap.adopt(repo, target, apply=False, base=base)
    assert result["mode"] == "DRY_RUN"
    assert not target.exists()
    assert command(repo, "tag", "--list") == ""
    assert (repo / ".git/config").read_bytes() == before


def test_apply_is_idempotent_and_guards_upstream(repository):
    repo, target, base = repository
    bootstrap.adopt(repo, target, apply=True, base=base)
    again = bootstrap.adopt(repo, target, apply=True, base=base)
    assert len(again["actions"]) == 4
    assert command(target, "rev-parse", "HEAD") == base
    assert command(repo, "rev-parse", bootstrap.TAG) == base
    assert command(repo, "remote", "get-url", "--push", "upstream") == "https://example.invalid/no-push"
    assert command(repo, "config", "push.default") == "nothing"
    assert command(target, "status", "--porcelain") == ""


@pytest.mark.parametrize("collision", ["dirty", "origin", "upstream", "directory", "tag", "symlink"])
def test_conflicts_refuse_before_config_writes(repository, collision):
    repo, target, base = repository
    if collision == "dirty":
        (repo / "private.txt").write_text("keep me")
    elif collision in {"origin", "upstream"}:
        command(repo, "remote", "set-url", collision, "https://example.invalid/unrelated.git")
    elif collision == "directory":
        target.mkdir()
        (target / "keep.txt").write_text("preserve")
    elif collision == "tag":
        command(repo, "commit", "--allow-empty", "-qm", "later synthetic commit")
        command(repo, "tag", bootstrap.TAG)
    else:
        target.symlink_to(repo, target_is_directory=True)
    before = (repo / ".git/config").read_bytes()
    with pytest.raises(bootstrap.Conflict):
        bootstrap.adopt(repo, target, apply=True, base=base)
    assert (repo / ".git/config").read_bytes() == before
    if collision == "dirty":
        assert (repo / "private.txt").read_text() == "keep me"
    if collision == "directory":
        assert (target / "keep.txt").read_text() == "preserve"


def test_dirty_existing_baseline_preserved(repository):
    repo, target, base = repository
    bootstrap.adopt(repo, target, apply=True, base=base)
    (target / "fixture.txt").write_text("user change")
    with pytest.raises(bootstrap.Conflict, match="dirty"):
        bootstrap.adopt(repo, target, apply=True, base=base)
    assert (target / "fixture.txt").read_text() == "user change"


def test_native_failure_is_not_success(repository, monkeypatch):
    repo, target, base = repository
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 17, "", "synthetic native failure"))
    with pytest.raises(bootstrap.Conflict, match="exit 17"):
        bootstrap.adopt(repo, target, apply=True, base=base)
    assert not target.exists()


def test_missing_root_never_creates_or_clones(tmp_path):
    with pytest.raises(bootstrap.Conflict):
        bootstrap.adopt(tmp_path / "missing", tmp_path / "baseline", apply=True)
    assert not (tmp_path / "missing").exists()
