"""Guarded local adoption of an existing exact fork. Dry-run unless --apply.

Never clones, creates remotes, pushes, rewrites history or touches game files.
All conflicts are checked before mutation. R-REP-001/002; AT-076 local subset.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

BASE = "1c4c23f092fde34ce527ebb27309f57a8c5ec5bb"
TAG = "baseline/khazad-1c4c23f"
ORIGIN = "https://github.com/Brak23/mithril-voices.git"
UPSTREAM = "https://github.com/Thelukepet/Khazad-Voice-TTS.git"


class Conflict(RuntimeError):
    """Precondition or native-command failure; never silently continue."""


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if result.returncode:
        raise Conflict(f"git {args[0]} failed with exit {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def inspect(repo: Path, baseline: Path, base: str = BASE) -> list[list[str]]:
    if repo.is_symlink() or baseline.is_symlink():
        raise Conflict("Repository/baseline cannot be symlinks")
    if not repo.is_dir() or not baseline.parent.is_dir():
        raise Conflict("Existing repository and baseline parent are required; no implicit cloning")
    repo, baseline = repo.resolve(), baseline.resolve()
    if baseline == repo or baseline.is_relative_to(repo):
        raise Conflict("Baseline must be outside the working repository")
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise Conflict("Select the repository root, not a nested directory")
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise Conflict("Dirty working tree: preserve and commit/review changes before apply")
    if git(repo, "cat-file", "-t", base) != "commit":
        raise Conflict("Pinned base is not a commit")
    git(repo, "merge-base", "--is-ancestor", base, "HEAD")
    if git(repo, "remote", "get-url", "origin") != ORIGIN:
        raise Conflict("Origin is not the authorized fork")
    if git(repo, "remote", "get-url", "upstream") != UPSTREAM:
        raise Conflict("Upstream fetch identity mismatch")
    tags = git(repo, "tag", "--list", TAG)
    if tags and git(repo, "rev-parse", f"{TAG}^{{commit}}") != base:
        raise Conflict("Baseline tag collision; never move it")
    registered = git(repo, "worktree", "list", "--porcelain").splitlines()
    # Git emits forward slashes for worktree paths on Windows even when Path.resolve()
    # uses backslashes. Compare resolved paths so repeat runs remain idempotent.
    paths = {Path(line.removeprefix("worktree ")).resolve()
             for line in registered if line.startswith("worktree ")}
    exists = baseline.exists()
    if exists:
        if baseline not in paths:
            raise Conflict("Baseline path exists but is not this repository's registered worktree")
        if git(baseline, "rev-parse", "HEAD") != base:
            raise Conflict("Existing baseline has the wrong commit")
        if git(baseline, "status", "--porcelain=v1", "--untracked-files=all"):
            raise Conflict("Existing baseline is dirty; preserve it")
        if git(baseline, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD":
            raise Conflict("Baseline must be detached")
    common = Path(git(repo, "rev-parse", "--git-common-dir"))
    common = (repo / common).resolve() if not common.is_absolute() else common.resolve()
    disabled_hooks = common / "mithril-disabled-hooks"
    if disabled_hooks.exists() and (disabled_hooks.is_symlink() or any(disabled_hooks.iterdir())):
        raise Conflict("Disabled-hooks path is not an empty owned directory")
    actions = [
        ["config", "--local", "remote.upstream.pushurl", "https://example.invalid/no-push"],
        ["config", "--local", "core.hooksPath", str(disabled_hooks)],
        ["config", "--local", "push.default", "nothing"],
        ["config", "--local", "remote.pushDefault", "origin"],
    ]
    if not tags:
        actions.append(["tag", TAG, base])
    if not exists:
        actions.append(["worktree", "add", "--detach", str(baseline), base])
    return actions


def adopt(repo: Path, baseline: Path, *, apply: bool, base: str = BASE) -> dict:
    actions = inspect(repo, baseline, base)
    if apply:
        # Preflight again immediately before writes; no unchecked inline recipe.
        actions = inspect(repo, baseline, base)
        hooks = Path(actions[1][-1])
        hooks.mkdir(exist_ok=True)
        for args in actions:
            git(repo, *args)
        if git(baseline, "rev-parse", "HEAD") != base:
            raise Conflict("Baseline verification failed after setup")
    return {"mode": "APPLIED" if apply else "DRY_RUN", "base": base,
            "actions": actions, "remote_writes": False,
            "note": "Baseline is operationally read-only; run experiments in disposable copies."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(adopt(args.repo, args.baseline, apply=args.apply), indent=2))
    except (Conflict, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"BLOCKED: {exc}{os.linesep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
