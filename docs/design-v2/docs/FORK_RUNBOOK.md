# Fork runbook reading extract

Generated from IMPLEMENTATION_SPEC.md section 2. The canonical specification governs; this extract is not a separate source of requirements. No commands have been executed.

## 2. Repository adoption and forking runbook

### R-REP-001 | Pinned reference and local bootstrap | CORE
Upstream repository: `Thelukepet/Khazad-Voice-TTS`. Audited commit: `1c4c23f092fde34ce527ebb27309f57a8c5ec5bb`. The GitHub API returned this as the newest commit when checked for this specification; its commit date is 10 August 2026. Do not substitute a newer head automatically. Record both the audited base and currently observed head. A newer upstream revision gets a separate diff review. Do not replace this full commit with a tag or branch name that may move. [S01]

Start with a local development copy and an immutable baseline worktree. Before cloning, choose an explicit empty workspace directory; never assume the current directory is disposable. Check `git --version`, authentication only when needed, disk space, and target-path existence. Do not execute upstream installers, notebooks, Git hooks, actions, or downloaded model code as part of discovery.

The following commands are an operational recipe, not commands executed by this package. Replace `WORKSPACE` with the approved directory. Check every native-command exit code; PowerShell's `$ErrorActionPreference` alone does not make every native command failure fatal.

```powershell
git clone --filter=blob:none --no-checkout `
  https://github.com/Thelukepet/Khazad-Voice-TTS.git WORKSPACE
Set-Location WORKSPACE
git remote rename origin upstream
git remote set-url --push upstream https://example.invalid/no-push
New-Item -ItemType Directory -Force .git/disabled-hooks
git config --local core.hooksPath (Resolve-Path .git/disabled-hooks).Path
git config --local push.default nothing
git cat-file -t 1c4c23f092fde34ce527ebb27309f57a8c5ec5bb
git switch -c lvc/main 1c4c23f092fde34ce527ebb27309f57a8c5ec5bb
git tag baseline/khazad-1c4c23f `
  1c4c23f092fde34ce527ebb27309f57a8c5ec5bb
git worktree add --detach ../khazad-baseline `
  1c4c23f092fde34ce527ebb27309f57a8c5ec5bb
```

Verify `cat-file` returns `commit`, `rev-parse HEAD` equals the full SHA, and the working tree is clean before copying this requirements package. The baseline worktree is operationally read-only: experiments run in a disposable copy, with reports outside it. Never move the baseline tag. A tag name collision must be compared, not overwritten. A dirty existing repository must be inspected and preserved; do not stash, reset, clean, or overwrite it automatically. Reuse a correctly configured existing clone rather than creating duplicates.

### R-REP-002 | Remote fork and visibility authorization | CORE
A GitHub fork of this public upstream is public. A branch named private or a draft PR does not change that. Obtain explicit approval of owner/account, fork name, public visibility, and publication of inherited history before creating the fork. Inventory inherited data/reference-audio assets and preserve license notices; do not claim all inherited assets are cleared merely because the repository is public. [S02]

Default remote name after approval: `lotro-voice-companion` under the authenticated personal account, unless the owner names another destination. First inspect whether a corresponding fork already exists. Verify its parent is the intended upstream, ownership/permissions match, and visibility is understood. Do not reuse an unrelated same-name repository.

```powershell
gh auth status --hostname github.com
gh api user --jq .login
gh repo fork Thelukepet/Khazad-Voice-TTS `
  --fork-name lotro-voice-companion --clone=false --remote=false
# OWNER is the verified, approved account, not a literal value.
git remote add origin https://github.com/OWNER/lotro-voice-companion.git
gh repo set-default OWNER/lotro-voice-companion
git config --local remote.pushDefault origin
```

Run these only once their approval and preconditions are satisfied. The guarded bootstrap script to be implemented in WP-00 MUST check every native exit code, guard each creation, support a dry-run, and be idempotent. The inline recipe is not that tested script. For an existing exact clone, inspect and reuse its paths instead of executing the creation recipe again. For an organization, use the explicitly approved organization parameter; do not infer it from work email. GitHub CLI can otherwise default repository actions to upstream, so verify both Git remotes and the `gh` default repository before any write. [S03]

Before the first push, inspect staged files, history being published, secrets, local paths, private captures, voice assets, and inherited workflow permissions. Push an explicit refspec only. Never push to upstream. The initial branch publication and changing the fork's default branch to `lvc/main` require the recorded repository-write permission. Set PR bases explicitly to the fork's `lvc/main`, not upstream `main`.

If public visibility is not approved, continue locally. A separately authorized private repository created from the local Git history is an independent derivative repository, not a private GitHub fork. Keep its `upstream` read remote and attribution. Do not silently choose this alternative or publish later without approval.

### R-REP-003 | Branch, review, and upstream policy | CORE
Use `lvc/main` as the integrated new-product branch. Use one `work/WP-XX-short-name` branch and separate worktree per work packet. Keep commits scoped to one behavior or mechanical move. PRs target the fork and identify requirements, tests, evidence, and known blockers. Shared contracts, coordinator, and database migrations have a single active implementation owner; parallel agents may review or work in independent adapters but must not concurrently rewrite those files.

No force pushes, history rewrites, unreviewed automated merges, new remote collaborators, or upstream PRs without explicit authority. Configure available branch protections/checks and verify they are effective; unavailable account features are recorded, not assumed. Merge only through the owner-approved policy. Baseline artifacts and manifests cannot be edited to hide regressions.

Inspect upstream changes deliberately on an `integration/upstream-SHA` branch. Review license, API, behavior, dependencies, and tests before merging or cherry-picking. Never run `git pull` at application startup. Do not make compatibility with every future upstream change a version-1 requirement.

### R-REP-004 | Repository structure and incremental replacement | CORE
Preserve the original `src/` paths initially. Add the new package under `lvc/`, so imports do not collide with the legacy generic package name. Do not reorganize the whole repository before a baseline exists.

```text
lvc/core/                 pure domain models, reducer, policy, interfaces
lvc/host/                 Qt Widgets, coordinator driver, audio, supervision
lvc/platform/windows/    window identity, hotkeys, known folders, job objects
lvc/adapters/legacy/      narrowly reviewed upstream adapters/importers
lvc/vision/               selected-window capture, geometry, detection, OCR
lvc/tts/                  worker entry points, Kokoro and OmniVoice adapters
lvc/storage/              SQLite migrations, state, cache, artifact registry
contracts/               reviewed JSON wire schema and defaults
planning/                tasks, requirements index, acceptance catalog
bridge/                  optional verified Lua context bridge
profiles/                data-only detector and OCR profiles
assets/manifests/        approved model/voice/runtime manifests, not weights
benchmarks/              deterministic replay, performance and fidelity tools
tests/v2/                new tests; legacy tests remain separately identifiable
packaging/               frozen host, relocatable workers, installer, rollback
tools/                   guarded setup, QA entry point, spec checks
docs/                    decisions, evidence, risks, runbooks
```

Do not import the old startup engine into the new host. Wrap only tested, narrow reusable routines or copy licensed routines with exact provenance. New domain code must not depend on Qt, Torch, OpenCV, Tesseract, or the old ConfigManager singleton. Retire a legacy path only after a test demonstrates equivalent or intentionally changed behavior. A smaller subsystem may be completely replaced when that is safer than adapting it; this is not permission for a whole-product rewrite.
