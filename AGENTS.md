# Mithril Voices repository instructions

Current owner authorization includes bounded implementation and tests on the
Windows gaming PC. Keep one work packet per reviewable branch/PR; do not merge or
release. Do not launch or interact with LOTRO until the owner is ready to run it.
See [authorization.json](docs/planning/authorization.json) and
[ADR 0003](docs/decisions/0003-windows-implementation.md). Earlier Mac evidence
is a portable probe, not Windows qualification.

Read [START_HERE.md](START_HERE.md),
[the implementation plan](docs/planning/implementation-plan.md), and
[the v2 specification](docs/design-v2/IMPLEMENTATION_SPEC.md). The v2 Python/PySide6
design supersedes earlier C#/.NET proposals. Its JSON contracts/catalogs are
normative for future implementation. Record conflicts; never guess away a gate.

The original upstream is Thelukepet/Khazad-Voice-TTS at
`1c4c23f092fde34ce527ebb27309f57a8c5ec5bb`. Preserve its history, LICENSE and credits.
Do not execute installers/notebooks/models for source discovery. Keep legacy
`src/` and tests intact. New runtime work eventually belongs under `lvc/`.

Actual permission scope is [authorization.json](docs/planning/authorization.json).
Permissions inside the archived design are delivery templates, not current grants.
Push only bounded review branches to Brak23/mithril-voices, explicitly selecting
the destination ref. No upstream push, merge, release, paid action, workflow
execution, game/plugin changes or private capture upload. Official PyPI
development dependencies may be installed only in the isolated task venv; no
global Python or unapproved model/API subscription installation.

Validation: use the task development venv's Python. `python tools/qa.py --suite
contract` runs the 43-case bounded data lane; `--suite foundation` runs five
test-control and fixture checks; `--suite core-stop` runs seven pure reducer
tests. None is product acceptance. Other QA suites
return BLOCKED until implemented. Ruff and Pyright
must check new tooling. `python docs/planning/check_plan.py` checks catalogs only;
`python docs/design-v2/verification/validate_handoff.py` checks the adopted handoff.
Neither passes application lifecycle/device acceptance. No Windows claim from Mac.

For future authorized packets, use one bounded branch, independent desired-behavior
tests and explicit evidence. Missing Windows/game/GPU evidence is BLOCKED. Preserve
failed results, distinguish source findings from reproduced bugs, and leave gates
unpassed until their required evidence exists.
